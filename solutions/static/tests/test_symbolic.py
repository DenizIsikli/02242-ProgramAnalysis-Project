"""Z3 return comparator: Java semantics, rules 3/3', and never-unsound fallbacks."""

import itertools
import random

import pytest
import z3
from abstractions import Interval, Region
from conftest import FakeBytecode, _ops, binop, goto, if_, load, push, ret
from region_verdict import ReturnCheck, check_pair
from symbolic import (
    BITS,
    SymUnsupported,
    concrete_run,
    make_return_checker,
    symbolic_paths,
)

import jvm
from jvm import CmpOpr as C

B = jvm.BinaryOpr
MAXI = 2**31 - 1
DOM = Interval(-3, 3)


def region(*ivs):
    return Region({f"p{i}": iv for i, iv in enumerate(ivs)})


def test_sign_pair_end_to_end(fake_bc):
    ids = fake_bc.ids
    chk = make_return_checker(fake_bc, ids["sign"], ids["sign_edited"])
    v = check_pair(fake_bc, ids["sign"], ids["sign_edited"], region(DOM), chk)
    assert v.overall == "changed" and v.witness == (0,)
    assert v.preserved_inputs == 6 and v.changed_inputs == 1 and v.unknown_inputs == 0


def test_safediv_preserved_for_whole_domain(fake_bc):
    ids = fake_bc.ids
    chk = make_return_checker(fake_bc, ids["safeDiv"], ids["safeDiv_edited"])
    v = check_pair(
        fake_bc, ids["safeDiv"], ids["safeDiv_edited"], region(DOM, DOM), chk
    )
    assert v.overall == "preserved" and v.preserved_inputs == 49


def test_ratio_changed_only_at_origin(fake_bc):
    ids = fake_bc.ids
    chk = make_return_checker(fake_bc, ids["ratio"], ids["ratio_edited"])
    v = check_pair(fake_bc, ids["ratio"], ids["ratio_edited"], region(DOM, DOM), chk)
    assert v.overall == "changed" and v.witness == (0, 0)
    assert v.changed_inputs == 1 and v.preserved_inputs == 48 and v.unknown_inputs == 0


def _overflow_pair():
    # m1(x) = (x + 1 > x) ? 1 : 0   (false at MAX_VALUE because of wrap-around);  m2(x) = 1
    m1 = _ops(
        load(0),
        push(1),
        binop(B.Add),
        load(0),
        if_(C.Le, 7),
        push(1),
        ret(),
        push(0),
        ret(),
    )
    m2 = _ops(push(1), ret())
    return FakeBytecode({"m1": (m1, 1, "(I)I"), "m2": (m2, 1, "(I)I")})


def test_overflow_is_modelled_with_bitvectors():
    bc = _overflow_pair()
    a, b = bc.ids["m1"], bc.ids["m2"]
    chk = make_return_checker(bc, a, b)
    assert chk(region(Interval(0, 100))) == ReturnCheck("equal")
    res = chk(region(Interval(0, MAXI)))
    assert res == ReturnCheck("differs", (MAXI,))


def test_concrete_replay_matches_java_division():
    m = _ops(load(0), load(1), binop(B.Div), ret())
    r = _ops(load(0), load(1), binop(B.Rem), ret())
    bc = FakeBytecode({"d": (m, 2, "(II)I"), "r": (r, 2, "(II)I")})
    d, rem = bc.ids["d"], bc.ids["r"]
    assert concrete_run(bc, d, (-7, 2)) == ("ok", -3)  # truncates toward zero
    assert concrete_run(bc, rem, (-7, 2)) == ("ok", -1)  # sign of dividend
    assert concrete_run(bc, d, (-(2**31), -1)) == ("ok", -(2**31))  # MIN / -1 wraps
    assert concrete_run(bc, d, (5, 0)) == ("divide by zero", None)


def test_symbolic_paths_agree_with_concrete_replay(fake_bc):
    """Cross-check the two executors on random inputs (z3 paths vs concrete interpreter)."""
    rnd = random.Random(0)
    for name, mid in fake_bc.ids.items():
        arity = len(mid.extension.params)
        xs = [z3.BitVec(f"x{i}", BITS) for i in range(arity)]
        paths = symbolic_paths(fake_bc, mid, xs)
        for _ in range(60):
            args = tuple(
                rnd.choice([-3, -1, 0, 1, 2, 3, MAXI, -(2**31), rnd.randint(-50, 50)])
                for _ in range(arity)
            )
            outcome, value = concrete_run(fake_bc, mid, args)
            subst = [(x, z3.BitVecVal(a, BITS)) for x, a in zip(xs, args)]
            hits = [
                p
                for p in paths
                if all(
                    z3.is_true(z3.simplify(z3.substitute(c, *subst))) for c in p.cond
                )
            ]
            if outcome == "ok":
                assert len(hits) == 1, (name, args)
                got = z3.simplify(z3.substitute(hits[0].ret, *subst)).as_signed_long()
                assert got == value, (name, args)
            else:
                assert hits == [], (name, args)  # error inputs lie on no "ok" path


def test_unsupported_and_loops_give_unknown():
    loop = _ops(load(0), goto(0))
    bc = FakeBytecode({"l": (loop, 1, "(I)I"), "m": (_ops(push(1), ret()), 1, "(I)I")})
    with pytest.raises(SymUnsupported):
        symbolic_paths(bc, bc.ids["l"], [z3.BitVec("x", BITS)])
    chk = make_return_checker(bc, bc.ids["l"], bc.ids["m"])
    assert chk(region(DOM)) == ReturnCheck("unknown")


def test_exhaustive_agreement_with_checker(fake_bc):
    """On the corpus domain the checker's equal/differs always matches brute force."""
    ids = fake_bc.ids
    for name in ("safeDiv", "ratio", "sign"):
        a, b = ids[name], ids[name + "_edited"]
        chk = make_return_checker(fake_bc, a, b)
        arity = len(a.extension.params)
        for lo, hi in [(-3, 3), (0, 3), (-3, -1), (0, 0)]:
            r = region(*[Interval(lo, hi)] * arity)
            diff = any(
                concrete_run(fake_bc, a, p) != concrete_run(fake_bc, b, p)
                for p in itertools.product(range(lo, hi + 1), repeat=arity)
            )
            res = chk(r)
            if res.status == "equal":
                assert not diff, (name, lo, hi)
            elif res.status == "differs":
                assert diff


# --- full-observation checker (Z3-only baseline) ------------------------------------------


def test_observation_checker_finds_error_vs_ok_witness(fake_bc):
    ids = fake_bc.ids
    chk = make_return_checker(
        fake_bc, ids["ratio"], ids["ratio_edited"], observations=True
    )
    res = chk(region(DOM, DOM))
    assert res.status == "differs" and res.witness == (0, 0)


def test_observation_checker_equal_even_with_errors(fake_bc):
    """safeDiv pair: equal; ratio on a region excluding (0,0): equal although both can throw."""
    ids = fake_bc.ids
    chk = make_return_checker(
        fake_bc, ids["safeDiv"], ids["safeDiv_edited"], observations=True
    )
    assert chk(region(DOM, DOM)).status == "equal"
    chk = make_return_checker(
        fake_bc, ids["ratio"], ids["ratio_edited"], observations=True
    )
    assert chk(region(Interval(1, 3), DOM)).status == "equal"


def test_observation_checker_agrees_with_brute_force(fake_bc):
    ids = fake_bc.ids
    for name in ("safeDiv", "ratio", "sign"):
        a, b = ids[name], ids[name + "_edited"]
        chk = make_return_checker(fake_bc, a, b, observations=True)
        arity = len(a.extension.params)
        for lo, hi in [(-3, 3), (0, 3), (-3, -1), (0, 0), (-1, 1)]:
            r = region(*[Interval(lo, hi)] * arity)
            diff = any(
                concrete_run(fake_bc, a, p) != concrete_run(fake_bc, b, p)
                for p in itertools.product(range(lo, hi + 1), repeat=arity)
            )
            res = chk(r)
            assert res.status == ("differs" if diff else "equal"), (name, lo, hi, res)
