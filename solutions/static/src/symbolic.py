"""Symbolic return comparison (verdict rules 3 / 3') with Z3 32-bit bitvectors.

Plugs into `region_verdict.check_pair(..., return_check=make_return_checker(...))`.

For a region where both versions are proved to return normally, we symbolically execute
both (loop-free, call-free `int` methods), collect (path condition, return expression)
pairs, and ask Z3 whether some input in the region makes the returns differ:

    Phi(R) = x in R  and  OR_{i,j} ( pi_A,i  and  pi_B,j  and  r_A,i != r_B,j )

* UNSAT and the ok-paths cover the region     -> "equal"      (rule 3)
* SAT and the model replays concretely         -> "differs"    (rule 3'), witness = model
* anything else (timeout, solver unknown, unsupported opcode, path budget, model that
  does not replay)                              -> "unknown"   (never "equal")

Java semantics: Add/Sub/Mul wrap (BitVec), Div = bvsdiv (truncates, MIN/-1 = MIN), Rem =
bvsrem (sign of dividend), comparisons are signed. SMT defines x/0, Java throws, so every
division adds "divisor != 0" to the path condition: only paths that return normally are
collected, which is exactly the situation of rules 3/3'.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3
from abstractions import Region
from region_verdict import ReturnCheck, ReturnChecker

import jpamb
from jpamb import jvm
from jvm.state import PC

INT_MIN = -(2**31)
BITS = 32
MAX_CONCRETE_STEPS = 10_000


class SymUnsupported(Exception):
    """Outside the supported fragment, or a budget was exceeded."""


# --- symbolic execution -----------------------------------------------------------------


@dataclass(frozen=True)
class SymPath:
    cond: tuple  # z3 Bool expressions
    ret: z3.BitVecRef


def _is_int(t) -> bool:
    return isinstance(t, (jvm.Int, jvm.Boolean))


_CMP = {
    jvm.CmpOpr.Eq: lambda a, b: a == b,
    jvm.CmpOpr.Ne: lambda a, b: a != b,
    jvm.CmpOpr.Lt: lambda a, b: a < b,  # z3py BitVec comparisons are signed
    jvm.CmpOpr.Le: lambda a, b: a <= b,
    jvm.CmpOpr.Gt: lambda a, b: a > b,
    jvm.CmpOpr.Ge: lambda a, b: a >= b,
}


def symbolic_paths(
    bc: jpamb.Bytecode,
    methodid: jvm.AbsMethodID,
    inputs: list[z3.BitVecRef],
    max_paths: int = 256,
) -> list[SymPath]:
    """All feasible normally-returning paths of `methodid` over the symbolic `inputs`."""
    method = bc.getmethod(methodid)
    params = list(methodid.extension.params)
    if len(params) != len(inputs):
        raise SymUnsupported("input arity differs from parameters")
    if not all(_is_int(p) for p in params):
        raise SymUnsupported("non-int parameter")
    locals_ = [z3.BitVecVal(0, BITS)] * method.max_locals
    for i, x in enumerate(inputs):
        locals_[i] = x

    paths: list[SymPath] = []
    # Explicit DFS stack of (offset, locals, stack, conds).
    work = [(0, tuple(locals_), (), ())]
    steps = 0
    solver = z3.Solver()
    solver.set("timeout", 2000)

    def feasible(conds) -> bool:
        solver.push()
        solver.add(*conds)
        r = solver.check()
        solver.pop()
        if r == z3.unknown:
            return True  # keep the path: dropping it could lose behaviour
        return r == z3.sat

    while work:
        off, locs, stack, conds = work.pop()
        while True:
            steps += 1
            if steps > MAX_CONCRETE_STEPS:
                raise SymUnsupported("step budget exhausted")
            opr = bc[PC(methodid, off)]
            match opr:
                case jvm.Push(value=v) if isinstance(v, int) and not isinstance(
                    v, bool
                ):
                    stack = stack + (z3.BitVecVal(v, BITS),)
                case jvm.Load(index=i, type=t) if _is_int(t):
                    stack = stack + (locs[i],)
                case jvm.Store(index=i, type=t) if _is_int(t):
                    locs = locs[:i] + (stack[-1],) + locs[i + 1 :]
                    stack = stack[:-1]
                case jvm.Incr(index=i, amount=a):
                    locs = locs[:i] + (locs[i] + z3.BitVecVal(a, BITS),) + locs[i + 1 :]
                case jvm.Dup(words=1):
                    stack = stack + (stack[-1],)
                case jvm.Negate(type=t) if _is_int(t):
                    stack = stack[:-1] + (-stack[-1],)
                case jvm.Binary(type=t, operant=op) if _is_int(t):
                    x, y = stack[-2], stack[-1]
                    stack = stack[:-2]
                    match op:
                        case jvm.BinaryOpr.Add:
                            r = x + y
                        case jvm.BinaryOpr.Sub:
                            r = x - y
                        case jvm.BinaryOpr.Mul:
                            r = x * y
                        case jvm.BinaryOpr.Div | jvm.BinaryOpr.Rem:
                            # Only the non-throwing continuation is an "ok" path.
                            conds = conds + (y != 0,)
                            if not feasible(conds):
                                break
                            r = x / y if op == jvm.BinaryOpr.Div else z3.SRem(x, y)
                        case _:
                            raise SymUnsupported(f"binary op {op}")
                    stack = stack + (r,)
                case jvm.Ifz(condition=c, target=target):
                    v = stack[-1]
                    stack = stack[:-1]
                    cond = _CMP[c](v, z3.BitVecVal(0, BITS))
                    off = _branch(work, locs, stack, conds, cond, off, target, feasible)
                    if off is None:
                        break
                    continue
                case jvm.If(condition=c, target=target):
                    y, x = stack[-1], stack[-2]
                    stack = stack[:-2]
                    off = _branch(
                        work, locs, stack, conds, _CMP[c](x, y), off, target, feasible
                    )
                    if off is None:
                        break
                    continue
                case jvm.Goto(target=t):
                    if t <= off:
                        raise SymUnsupported("backward jump (loop)")
                    off = t
                    continue
                case jvm.Get(static=True, field=f) if (
                    f.extension.name == "$assertionsDisabled"
                ):
                    stack = stack + (z3.BitVecVal(0, BITS),)
                case jvm.Return(type=t) if _is_int(t):
                    paths.append(SymPath(conds, stack[-1]))
                    if len(paths) > max_paths:
                        raise SymUnsupported("path budget exceeded")
                    break
                case jvm.New(classname=jvm.ClassName("java.lang.AssertionError")):
                    break  # not a normal return: not an "ok" path
                case other:
                    raise SymUnsupported(f"opcode {other}")
            off += 1
    return paths


def _branch(work, locs, stack, conds, cond, off, target, feasible):
    """Fork on `cond`: push the taken side on the work list, continue with fall-through."""
    if target <= off:
        raise SymUnsupported("backward jump (loop)")
    taken = conds + (cond,)
    fall = conds + (z3.Not(cond),)
    if feasible(taken):
        work.append((target, locs, stack, taken))
    if feasible(fall):
        work.append((off + 1, locs, stack, fall))
    # both successors are queued; this path of the loop is finished


# --- concrete replay (independent of Z3) ------------------------------------------------


def _wrap(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 2**32 if v >= 2**31 else v


def _cmp(c, a: int, b: int) -> bool:
    return {
        jvm.CmpOpr.Eq: a == b,
        jvm.CmpOpr.Ne: a != b,
        jvm.CmpOpr.Lt: a < b,
        jvm.CmpOpr.Le: a <= b,
        jvm.CmpOpr.Gt: a > b,
        jvm.CmpOpr.Ge: a >= b,
    }[c]


def concrete_run(
    bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, args: tuple[int, ...]
) -> tuple[str, int | None]:
    """Run a method with Java int semantics: ("ok", value) or (error outcome, None)."""
    method = bc.getmethod(methodid)
    locs = [0] * method.max_locals
    for i, a in enumerate(args):
        locs[i] = a
    stack: list[int] = []
    off = 0
    for _ in range(MAX_CONCRETE_STEPS):
        opr = bc[PC(methodid, off)]
        nxt = off + 1
        match opr:
            case jvm.Push(value=v) if isinstance(v, int):
                stack.append(_wrap(int(v)))
            case jvm.Load(index=i):
                stack.append(locs[i])
            case jvm.Store(index=i):
                locs[i] = stack.pop()
            case jvm.Incr(index=i, amount=a):
                locs[i] = _wrap(locs[i] + a)
            case jvm.Dup(words=1):
                stack.append(stack[-1])
            case jvm.Negate():
                stack.append(_wrap(-stack.pop()))
            case jvm.Binary(operant=op):
                y, x = stack.pop(), stack.pop()
                if op in (jvm.BinaryOpr.Div, jvm.BinaryOpr.Rem):
                    if y == 0:
                        return ("divide by zero", None)
                    q = abs(x) // abs(y)
                    q = -q if (x < 0) != (y < 0) else q
                    stack.append(_wrap(q if op == jvm.BinaryOpr.Div else x - q * y))
                else:
                    stack.append(
                        _wrap(
                            {
                                jvm.BinaryOpr.Add: x + y,
                                jvm.BinaryOpr.Sub: x - y,
                                jvm.BinaryOpr.Mul: x * y,
                            }[op]
                        )
                    )
            case jvm.Ifz(condition=c, target=t):
                if _cmp(c, stack.pop(), 0):
                    nxt = t
            case jvm.If(condition=c, target=t):
                y, x = stack.pop(), stack.pop()
                if _cmp(c, x, y):
                    nxt = t
            case jvm.Goto(target=t):
                nxt = t
            case jvm.Get(static=True, field=f) if (
                f.extension.name == "$assertionsDisabled"
            ):
                stack.append(0)
            case jvm.New(classname=jvm.ClassName("java.lang.AssertionError")):
                return ("assertion error", None)
            case jvm.Return(type=None):
                return ("ok", None)
            case jvm.Return():
                return ("ok", stack.pop())
            case other:
                raise SymUnsupported(f"opcode {other}")
        off = nxt
    return ("*", None)


# --- the plug-in ------------------------------------------------------------------------


def make_return_checker(
    bc: jpamb.Bytecode,
    original: jvm.AbsMethodID,
    edited: jvm.AbsMethodID,
    timeout_ms: int = 5000,
    max_paths: int = 256,
) -> ReturnChecker:
    """Build the `(Region) -> ReturnCheck` callable used by `check_pair`."""
    arity = len(original.extension.params)
    xs = [z3.BitVec(f"x{i}", BITS) for i in range(arity)]
    try:
        paths_a = symbolic_paths(bc, original, xs, max_paths)
        paths_b = symbolic_paths(bc, edited, xs, max_paths)
        failure = None
    except SymUnsupported as exc:
        paths_a = paths_b = []
        failure = str(exc)

    def check(region: Region) -> ReturnCheck:
        if failure is not None or len(region.bounds) != arity:
            return ReturnCheck("unknown")
        if not paths_a or not paths_b:
            return ReturnCheck("unknown")  # no ok path found: cannot argue equality
        in_region = [
            z3.And(x >= iv.min, x <= iv.max)
            for x, iv in zip(xs, region.bounds.values())
        ]
        # Completeness guard: the collected ok-paths must cover the whole region for both
        # versions. Otherwise some input errors (or loops) and "no mismatch among ok-paths"
        # would not mean "equal". This makes the checker safe even outside its precondition.
        for paths in (paths_a, paths_b):
            cover = z3.Solver()
            cover.set("timeout", timeout_ms)
            cover.add(*in_region, z3.Not(z3.Or(*[z3.And(*p.cond) for p in paths])))
            if cover.check() != z3.unsat:
                return ReturnCheck("unknown")
        mismatch = z3.Or(
            *[
                z3.And(*pa.cond, *pb.cond, pa.ret != pb.ret)
                for pa in paths_a
                for pb in paths_b
            ]
        )
        solver = z3.Solver()
        solver.set("timeout", timeout_ms)
        solver.add(*in_region, mismatch)
        res = solver.check()
        if res == z3.unsat:
            return ReturnCheck("equal")
        if res != z3.sat:
            return ReturnCheck("unknown")  # timeout / unknown is NOT unsat
        model = solver.model()
        witness = tuple(
            model.eval(x, model_completion=True).as_signed_long() for x in xs
        )
        # Rule 3': only trust a model that replays concretely.
        try:
            obs_a = concrete_run(bc, original, witness)
            obs_b = concrete_run(bc, edited, witness)
        except SymUnsupported:
            return ReturnCheck("unknown")
        if obs_a != obs_b:
            return ReturnCheck("differs", witness)
        return ReturnCheck("unknown")

    return check
