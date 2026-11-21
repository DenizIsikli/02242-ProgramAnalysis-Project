"""Outcome analysis of one method on one input region (interval abstract interpreter).

Scope (deliberately small): static, call-free methods whose parameters are `int`/`boolean`.
Loops are handled by interval widening at loop heads (backward-jump targets). Divergence
("*") is added to the outcome set unless a loop is proved to terminate by a simple syntactic
counting pattern (see `_proven_terminating`). Anything else (calls, arrays, unknown opcodes)
makes the result *unsupported*: the outcome set is then "everything", which can never justify a
`preserved` or `changed` verdict.

Soundness contract (S): for every input x in the region, the concrete outcome of the method
is in `AnalysisResult.outcomes`, and if it returns normally its value is in `.returns`.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from abstractions import Interval, Region

import jpamb
from jpamb import jvm
from jvm.state import PC

# The JPAMB outcome vocabulary ("*" = does not terminate).
ALL_OUTCOMES = frozenset(
    {"ok", "assertion error", "divide by zero", "null pointer", "out of bounds", "*"}
)
MAX_STEPS = 10_000


class Unsupported(Exception):
    """The method uses something outside the supported fragment."""


@dataclass(frozen=True)
class Val:
    """A stack value: its interval, plus the local it was loaded from (if unchanged)."""

    interval: Interval
    src: int | None = None


@dataclass(frozen=True)
class AState:
    locals: tuple[Interval, ...]
    stack: tuple[Val, ...]

    def widen(self, other: AState) -> AState:
        """Join, but widen intervals (used when following a backward jump)."""
        assert len(self.stack) == len(other.stack), (
            "stack heights differ at a loop head"
        )
        return AState(
            tuple(a.widen(b) for a, b in zip(self.locals, other.locals)),
            tuple(
                Val(a.interval.widen(b.interval), a.src if a.src == b.src else None)
                for a, b in zip(self.stack, other.stack)
            ),
        )

    def join(self, other: AState) -> AState:
        assert len(self.stack) == len(other.stack), "stack heights differ at a join"
        return AState(
            tuple(a | b for a, b in zip(self.locals, other.locals)),
            tuple(
                Val(a.interval | b.interval, a.src if a.src == b.src else None)
                for a, b in zip(self.stack, other.stack)
            ),
        )

    def push(self, interval: Interval, src: int | None = None) -> AState:
        return AState(self.locals, self.stack + (Val(interval, src),))

    def pop(self, n: int = 1) -> tuple[tuple[Val, ...], AState]:
        return self.stack[len(self.stack) - n :], AState(
            self.locals, self.stack[: len(self.stack) - n]
        )

    def store(self, index: int, interval: Interval) -> AState:
        locals_ = self.locals[:index] + (interval,) + self.locals[index + 1 :]
        # Stack copies of the old local no longer track it.
        stack = tuple(
            Val(v.interval, None if v.src == index else v.src) for v in self.stack
        )
        return AState(locals_, stack)

    def refine_local(self, index: int, interval: Interval) -> AState:
        locals_ = self.locals[:index] + (interval,) + self.locals[index + 1 :]
        return AState(locals_, self.stack)


@dataclass(frozen=True)
class AnalysisResult:
    outcomes: frozenset[str]
    returns: Interval | None  # join of returned values; None if it never returns
    supported: bool
    reason: str = ""


UNSUPPORTED_OUTCOMES = ALL_OUTCOMES


def unsupported(reason: str) -> AnalysisResult:
    return AnalysisResult(UNSUPPORTED_OUTCOMES, Interval.top(), False, reason)


def _is_int_type(t) -> bool:
    return isinstance(t, (jvm.Int, jvm.Boolean))


def has_exception_handlers(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID) -> bool:
    """Does the method have a try/catch (a non-empty exception table)?

    try/catch is excluded by observation-contract.md §4: a caught exception is not an
    outcome, and neither analyser models handlers. Ignoring a handler is unsound: the
    division in `try { return a / b; } catch (ArithmeticException e) { return -1; }`
    would be reported as `divide by zero`. `jvm.Method` drops the exception table, so it
    is read from the decompiled JSON. Test doubles without a `suite` have no handlers.
    """
    suite = getattr(bc, "suite", None)
    if suite is None:
        return False
    return bool(suite.findmethod(methodid, eff=bc.eff)["code"].get("exceptions"))


def initial_state(
    bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, region: Region
) -> AState:
    if has_exception_handlers(bc, methodid):
        raise Unsupported("method has exception handlers (try/catch)")
    method = bc.getmethod(methodid)
    params = list(methodid.extension.params)
    bounds = list(region.bounds.values())
    if len(params) != len(bounds):
        raise ValueError(
            f"region has {len(bounds)} bounds but method has {len(params)} params"
        )
    locals_ = [Interval.bot()] * method.max_locals
    for i, (p, b) in enumerate(zip(params, bounds)):
        if not _is_int_type(p):
            raise Unsupported(f"parameter {i} has non-int type {p}")
        locals_[i] = b
    return AState(tuple(locals_), ())


def _step(bc: jpamb.Bytecode, pc: PC, st: AState):
    """Yield successors: (pc, state), ("ret", interval) or an outcome string."""
    opr = bc[pc]
    match opr:
        case jvm.Push(value=v):
            if isinstance(v, bool):
                v = int(v)
            if not isinstance(v, int):
                raise Unsupported(f"push of non-int constant {v!r}")
            yield (pc + 1, st.push(Interval(v, v)))

        case jvm.Load(index=i, type=t):
            if not _is_int_type(t):
                raise Unsupported(f"load of non-int {t}")
            yield (pc + 1, st.push(st.locals[i], src=i))

        case jvm.Store(index=i, type=t):
            if not _is_int_type(t):
                raise Unsupported(f"store of non-int {t}")
            [v], after = st.pop(1)
            yield (pc + 1, after.store(i, v.interval))

        case jvm.Incr(index=i, amount=amount):
            res, _ = st.locals[i].arithmetic(
                Interval(amount, amount), jvm.BinaryOpr.Add
            )
            yield (pc + 1, st.store(i, res))

        case jvm.Dup(words=1):
            [v], _ = st.pop(1)
            yield (pc + 1, AState(st.locals, st.stack + (v,)))

        case jvm.Negate(type=t):
            if not _is_int_type(t):
                raise Unsupported(f"negate of non-int {t}")
            [v], after = st.pop(1)
            yield (pc + 1, after.push(v.interval.neg()))

        case jvm.Binary(type=t, operant=op):
            if not _is_int_type(t):
                raise Unsupported(f"binary op on non-int {t}")
            [v1, v2], after = st.pop(2)
            res, errors = v1.interval.arithmetic(v2.interval, op)
            yield from errors
            if not res.is_empty:
                yield (pc + 1, after.push(res))

        case jvm.Ifz(condition=cond, target=target):
            [v], after = st.pop(1)
            zero = Interval(0, 0)
            for holds, nxt in ((True, pc % target), (False, pc + 1)):
                new, _ = v.interval.refine(zero, cond, holds)
                if new.is_empty:
                    continue
                s = after if v.src is None else after.refine_local(v.src, new)
                yield (nxt, s)

        case jvm.If(condition=cond, target=target):
            [v1, v2], after = st.pop(2)
            for holds, nxt in ((True, pc % target), (False, pc + 1)):
                n1, n2 = v1.interval.refine(v2.interval, cond, holds)
                if n1.is_empty or n2.is_empty:
                    continue
                s = after
                if v1.src is not None:
                    s = s.refine_local(v1.src, n1)
                if v2.src is not None:
                    s = s.refine_local(v2.src, n2)
                yield (nxt, s)

        case jvm.Goto(target=t):
            yield (pc % t, st)

        case jvm.Get(static=True, field=field) if (
            field.extension.name == "$assertionsDisabled"
        ):
            # Same assumption as the course skeleton: assertions are enabled (run with -ea).
            yield (pc + 1, st.push(Interval(0, 0)))

        case jvm.New(classname=jvm.ClassName("java.lang.AssertionError")):
            # Constructing an AssertionError in the benchmark means it is thrown next.
            yield "assertion error"

        case jvm.Return(type=None):
            yield "ok"

        case jvm.Return(type=t):
            if not _is_int_type(t):
                raise Unsupported(f"return of non-int {t}")
            [v], _ = st.pop(1)
            yield ("ret", v.interval)

        case other:
            raise Unsupported(f"opcode {other}")


def _proven_terminating(ops: list, head: int, src: int) -> bool:
    """Is the loop [head, src] (back edge at `src`) a simple counting loop that must exit?

    Pattern (what javac emits for `while (i < n) { ...; i++; }`):
      head: load i; [load n | push c]; if_icmpge EXIT      (or: load i; ifle EXIT for i--)
      body: straight-line code with exactly one `iinc i +1` (or -1 for the `ifle` form),
            no other write to i or n, no jumps; src: goto head.
    Counting by exactly 1 reaches the bound before wrapping, so the loop exits.
    Anything not matching is NOT proved (we then admit divergence).
    """
    if not isinstance(ops[src], jvm.Goto) or ops[src].target != head:
        return False
    i, operands = head, []
    while i < src and isinstance(ops[i], (jvm.Load, jvm.Push)):
        operands.append(ops[i])
        i += 1
    if i >= src or not operands or not isinstance(operands[0], jvm.Load):
        return False
    test, counter = ops[i], operands[0].index
    match test:
        case jvm.If(condition=jvm.CmpOpr.Ge, target=ex) if len(operands) == 2:
            step = 1
        case jvm.If(condition=jvm.CmpOpr.Le, target=ex) if len(operands) == 2:
            step = -1
        case jvm.Ifz(condition=jvm.CmpOpr.Le, target=ex) if len(operands) == 1:
            step = -1
        case jvm.Ifz(condition=jvm.CmpOpr.Ge, target=ex) if len(operands) == 1:
            step = 1
        case _:
            return False
    if ex <= src:
        return False  # the exit must leave the loop
    bound = operands[1] if len(operands) == 2 else None
    incs = 0
    for op in ops[i + 1 : src]:
        match op:
            case jvm.Incr(index=k, amount=a) if k == counter:
                if a != step:
                    return False
                incs += 1
            case jvm.Store(index=k) | jvm.Incr(index=k) if k == counter:
                return False
            case jvm.Store(index=k) | jvm.Incr(index=k) if (
                isinstance(bound, jvm.Load) and k == bound.index
            ):
                return False
            case jvm.If() | jvm.Ifz() | jvm.Goto():
                return False
    return incs == 1


def analyse_outcomes(
    bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, region: Region
) -> AnalysisResult:
    """Over-approximate the outcomes of `methodid` on every input in `region`."""
    if region.is_empty:
        return AnalysisResult(frozenset(), None, True, "empty region")
    try:
        states = {PC(methodid, 0): initial_state(bc, methodid, region)}
        # Forward-only control flow: processing the smallest offset first visits each
        # pc after all of its predecessors, so each pc is normally processed once.
        heap = [0]
        queued = {0}
        outcomes: set[str] = set()
        returns = Interval.bot()
        returned = False
        loop_edges: set[tuple[int, int]] = set()  # (source offset, head offset)
        steps = 0
        while heap:
            steps += 1
            if steps > MAX_STEPS:
                raise Unsupported("step budget exhausted")
            off = heapq.heappop(heap)
            queued.discard(off)
            pc = PC(methodid, off)
            for res in _step(bc, pc, states[pc]):
                if isinstance(res, str):
                    outcomes.add(res)
                elif res[0] == "ret":
                    outcomes.add("ok")
                    returns = returns | res[1]
                    returned = True
                else:
                    nxt, st = res
                    before = states.get(nxt)
                    backward = nxt.offset <= pc.offset
                    if backward:
                        loop_edges.add((pc.offset, nxt.offset))
                    if before is None:
                        after = st
                    elif backward:
                        after = before.widen(before.join(st))
                    else:
                        after = before.join(st)
                    if before is None or after != before:
                        states[nxt] = after
                        if nxt.offset not in queued:
                            queued.add(nxt.offset)
                            heapq.heappush(heap, nxt.offset)
        ops = bc.getmethod(methodid).opcodes
        for src, head in loop_edges:
            if not _proven_terminating(ops, head, src):
                outcomes.add("*")  # cannot rule out divergence
        return AnalysisResult(frozenset(outcomes), returns if returned else None, True)
    except Unsupported as exc:
        return unsupported(str(exc))
