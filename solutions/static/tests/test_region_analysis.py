"""Region outcome analysis + regional verdicts on the corpus pairs (hand-assembled bytecode)."""

import itertools

from abstractions import Interval, Region
from region_analysis import analyse_outcomes
from region_verdict import (
    ReturnCheck,
    check_pair,
    region_size,
    region_verdict,
    split_region,
)

DOM = Interval(-3, 3)


def region(*ivs):
    return Region({f"p{i}": iv for i, iv in enumerate(ivs)})


def java_outcome(name, args):
    """Concrete Java behaviour of the corpus methods, written by hand."""
    a, *rest = args
    if name.startswith("safeDiv"):
        b = rest[0]
        return ("ok", 0) if b == 0 else ("ok", int(a / b))
    if name == "ratio":
        b = rest[0]
        d = b - a
        if d == 0:
            return ("ok", 0)
        m = max(a, b)
        return ("divide by zero", None) if m == 0 else ("ok", int(d / m))
    if name == "ratio_edited":
        b = rest[0]
        d, m = b - a, max(a, b)
        return ("divide by zero", None) if m == 0 else ("ok", int(d / m))
    if name == "sign":
        return ("ok", (a > 0) - (a < 0))
    if name == "sign_edited":
        return ("ok", 1 if a > 0 else -1)
    raise AssertionError(name)


def test_analysis_is_sound_on_every_input(fake_bc):
    """S: each concrete outcome/return lies in the abstract result (all corpus methods)."""
    for name, mid in fake_bc.ids.items():
        arity = len(mid.extension.params)
        for sub in [
            (DOM,) * arity,
            (Interval(1, 3),) * arity,
            (Interval(-3, -1),) * arity,
        ]:
            res = analyse_outcomes(fake_bc, mid, region(*sub))
            assert res.supported, (name, res.reason)
            for args in itertools.product(*[range(i.min, i.max + 1) for i in sub]):
                outcome, ret = java_outcome(name, args)
                assert outcome in res.outcomes, (name, args, res)
                if ret is not None:
                    assert Interval(ret, ret) <= res.returns, (name, args, res)


def test_guard_refines_local(fake_bc):
    """safeDiv: after `if (b == 0) return 0`, b != 0 on [0,3] -> no divide by zero."""
    res = analyse_outcomes(fake_bc, fake_bc.ids["safeDiv"], region(DOM, Interval(0, 3)))
    assert res.outcomes == {"ok"}
    # On [-3,3] intervals cannot express b != 0, so the analysis stays imprecise (sound).
    res = analyse_outcomes(fake_bc, fake_bc.ids["safeDiv"], region(DOM, DOM))
    assert "ok" in res.outcomes


def test_empty_region_has_no_outcomes(fake_bc):
    res = analyse_outcomes(fake_bc, fake_bc.ids["sign"], region(Interval.bot()))
    assert res.outcomes == frozenset() and res.supported


def test_rules_on_point_regions(fake_bc):
    a, b = fake_bc.ids["ratio"], fake_bc.ids["ratio_edited"]
    pt = region(Interval(0, 0), Interval(0, 0))
    v = region_verdict(
        analyse_outcomes(fake_bc, a, pt), analyse_outcomes(fake_bc, b, pt), pt
    )
    assert (v.status, v.whole_region) == ("changed", True) and v.rule.startswith("2")
    assert v.witness == (0, 0)
    pt = region(Interval(0, 0), Interval(-1, -1))  # both divide by zero
    v = region_verdict(
        analyse_outcomes(fake_bc, a, pt), analyse_outcomes(fake_bc, b, pt), pt
    )
    assert (v.status, v.rule) == ("preserved", "1: same singleton error")


def test_equal_sets_with_two_outcomes_are_not_enough(fake_bc):
    """ratio on [-3,3]^2: both {ok, dbz} -> must NOT be called preserved (Rule 4)."""
    a, b = fake_bc.ids["ratio"], fake_bc.ids["ratio_edited"]
    r = region(DOM, DOM)
    v = region_verdict(
        analyse_outcomes(fake_bc, a, r), analyse_outcomes(fake_bc, b, r), r
    )
    assert v.status == "unknown"


def test_return_only_change_needs_return_check(fake_bc):
    a, b = fake_bc.ids["sign"], fake_bc.ids["sign_edited"]
    r = region(DOM)
    ra, rb = analyse_outcomes(fake_bc, a, r), analyse_outcomes(fake_bc, b, r)
    assert ra.outcomes == rb.outcomes == {"ok"}
    assert region_verdict(ra, rb, r).status == "unknown"  # no solver plugged in
    plugged = region_verdict(ra, rb, r, lambda _r: ReturnCheck("differs", (0,)))
    assert (plugged.status, plugged.whole_region, plugged.witness) == (
        "changed",
        False,
        (0,),
    )
    # A solver that gives up must never produce preserved.
    assert (
        region_verdict(ra, rb, r, lambda _r: ReturnCheck("unknown")).status == "unknown"
    )


def test_split_is_disjoint_cover():
    r = region(Interval(-3, 3), Interval(-3, 3))
    for consts in ({0}, set(), {5}, {-3}, {3}):
        kids = split_region(r, consts)
        assert kids
        points = [
            p
            for k in kids
            for p in itertools.product(
                range(k.bounds["p0"].min, k.bounds["p0"].max + 1),
                range(k.bounds["p1"].min, k.bounds["p1"].max + 1),
            )
        ]
        assert sorted(points) == sorted(itertools.product(range(-3, 4), range(-3, 4)))
        assert sum(region_size(k) for k in kids) == 49
    assert split_region(region(Interval(2, 2)), {0}) == []


def test_pair_safediv_preserved(fake_bc):
    ids = fake_bc.ids
    v = check_pair(fake_bc, ids["safeDiv"], ids["safeDiv_edited"], region(DOM, DOM))
    # Equal singleton returns are rare; without a solver the preserved verdict is not
    # reachable for safeDiv, but nothing may be called changed.
    assert v.overall in ("unknown", "preserved")
    assert v.changed_inputs == 0


def test_pair_ratio_changed_with_witness(fake_bc):
    ids = fake_bc.ids
    v = check_pair(fake_bc, ids["ratio"], ids["ratio_edited"], region(DOM, DOM))
    assert v.overall == "changed" and v.witness == (0, 0)
    assert v.preserved_inputs + v.changed_inputs + v.unknown_inputs == 49
    # The only differing input is (0,0): never claim more than that as changed.
    assert v.changed_inputs == 1


def test_pair_sign_with_exact_oracle(fake_bc):
    ids = fake_bc.ids

    def oracle(r):  # stands in for Z3 in this test: exhaustive on the region
        pts = range(r.bounds["p0"].min, r.bounds["p0"].max + 1)
        diff = [
            x
            for x in pts
            if java_outcome("sign", (x,)) != java_outcome("sign_edited", (x,))
        ]
        return ReturnCheck("differs", (diff[0],)) if diff else ReturnCheck("equal")

    v = check_pair(fake_bc, ids["sign"], ids["sign_edited"], region(DOM), oracle)
    assert v.overall == "changed" and v.witness == (0,)
    assert v.preserved_inputs == 6  # every x != 0 is certified equal


def test_pair_sign_without_solver_never_claims_preserved(fake_bc):
    ids = fake_bc.ids
    v = check_pair(fake_bc, ids["sign"], ids["sign_edited"], region(DOM))
    # x=0 is isolated by refinement and decided by Rule 2b (returns 0 vs -1).
    assert v.overall == "changed" and v.witness == (0,)


def test_budget_leaves_unknown(fake_bc):
    ids = fake_bc.ids
    v = check_pair(
        fake_bc, ids["ratio"], ids["ratio_edited"], region(DOM, DOM), max_regions=1
    )
    assert v.overall == "unknown" and v.unknown_inputs == 49


# --- loops -------------------------------------------------------------------------------


def _loop_bc():
    from conftest import (
        FakeBytecode,
        _ops,
        binop,
        goto,
        if_,
        ifz,
        load,
        push,
        ret,
        store,
    )

    from jvm import BinaryOpr as B
    from jvm import CmpOpr as C
    from jvm import opcode as o

    incr = lambda n, k: lambda i: o.Incr(offset=i, index=n, amount=k)
    # sum(n): i=0; s=0; while (i < n) { s += i; i++; } return s     -> counting loop
    total = _ops(
        push(0),
        store(1),
        push(0),
        store(2),
        load(1),
        load(0),
        if_(C.Ge, 13),
        load(2),
        load(1),
        binop(B.Add),
        store(2),
        incr(1, 1),
        goto(4),
        load(2),
        ret(),
    )
    # same loop but steps by 2: may skip the bound and wrap forever -> NOT proved terminating
    by2 = _ops(
        push(0),
        store(1),
        push(0),
        store(2),
        load(1),
        load(0),
        if_(C.Ge, 13),
        load(2),
        load(1),
        binop(B.Add),
        store(2),
        incr(1, 2),
        goto(4),
        load(2),
        ret(),
    )
    # countdown: while (n > 0) n--; return n                         -> ifle form, step -1
    down = _ops(load(0), ifz(C.Le, 5), incr(0, -1), goto(0), push(0), load(0), ret())
    # while (true) {}
    spin = _ops(goto(0))
    return FakeBytecode(
        {
            "total": (total, 3, "(I)I"),
            "by2": (by2, 3, "(I)I"),
            "down": (down, 1, "(I)I"),
            "spin": (spin, 1, "(I)V"),
        }
    )


def test_counting_loop_terminates_and_is_sound():
    bc = _loop_bc()
    r = analyse_outcomes(bc, bc.ids["total"], region(Interval(0, 5)))
    assert r.supported and r.outcomes == {"ok"}  # termination proved, no "*"
    for n in range(6):
        assert Interval(sum(range(n)), sum(range(n))) <= r.returns
    # negative n: loop body never runs, still fine
    r = analyse_outcomes(bc, bc.ids["total"], region(Interval(-3, 3)))
    assert r.outcomes == {"ok"}


def test_countdown_loop_terminates():
    bc = _loop_bc()
    r = analyse_outcomes(bc, bc.ids["down"], region(Interval(-2, 5)))
    assert r.outcomes == {"ok"}
    for n in range(-2, 6):
        assert Interval(min(n, 0), min(n, 0)) <= r.returns


def test_unproved_loops_admit_divergence():
    bc = _loop_bc()
    assert "*" in analyse_outcomes(bc, bc.ids["by2"], region(Interval(0, 5))).outcomes
    assert analyse_outcomes(bc, bc.ids["spin"], region(Interval(0, 5))).outcomes == {
        "*"
    }


def test_unproved_loops_never_decided_preserved_or_changed_by_outcomes_alone():
    bc = _loop_bc()
    a, b = bc.ids["by2"], bc.ids["total"]
    v = region_verdict(
        analyse_outcomes(bc, a, region(Interval(0, 5))),
        analyse_outcomes(bc, b, region(Interval(0, 5))),
        region(Interval(0, 5)),
    )
    assert v.status == "unknown"  # {ok,*} vs {ok}: overlap, nothing certified


def test_widening_is_sound_and_terminates():
    from abstractions import INT_MAX, INT_MIN

    old, new = Interval(0, 0), Interval(0, 1)
    w = old.widen(new)
    assert w == Interval(0, INT_MAX) and new <= w and old <= w
    assert w.widen(Interval(-1, 5)) == Interval(INT_MIN, INT_MAX)
    assert old.widen(old) == old and Interval.bot().widen(new) == new


# --- try/catch is outside the contract (observation-contract.md §4) -------------------


def test_exception_handlers_make_the_pair_unsupported():
    """`try { return a / b; } catch (ArithmeticException e) { return -1; }` vs
    `if (b == 0) return -1; return a / b;` behave identically. Ignoring the handler
    would report `divide by zero` for b = 0 and a false `changed` (found in review)."""
    from conftest import FakeBytecode, _ops, binop, ifz, load, push, ret
    from region_analysis import has_exception_handlers
    from symbolic import make_return_checker

    import jvm
    from jvm import CmpOpr as C

    B = jvm.BinaryOpr
    with_try = _ops(load(0), load(1), binop(B.Div), ret(), push(-1), ret())
    with_if = _ops(
        load(1), ifz(C.Ne, 4), push(-1), ret(), load(0), load(1), binop(B.Div), ret()
    )
    handler = [
        {
            "start": 0,
            "end": 3,
            "handler": 4,
            "catchType": "java/lang/ArithmeticException",
        }
    ]

    class Suite:
        def findmethod(self, mid, eff):
            name = mid.extension.name
            return {"code": {"exceptions": handler if name == "div" else []}}

    bc = FakeBytecode(
        {"div": (with_try, 3, "(II)I"), "div_edited": (with_if, 2, "(II)I")}
    )
    bc.suite, bc.eff = Suite(), None
    a, b = bc.ids["div"], bc.ids["div_edited"]

    assert has_exception_handlers(bc, a) and not has_exception_handlers(bc, b)
    assert not analyse_outcomes(bc, a, region(DOM, DOM)).supported
    v = check_pair(bc, a, b, region(DOM, DOM), make_return_checker(bc, a, b))
    assert v.overall == "unknown" and v.changed_inputs == 0
