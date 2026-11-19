"""Soundness tests for the Interval operations used by the region analysis.

Reference semantics are Java `int` semantics written out by hand (wrap to 32
bits, truncating division), NOT Python's unbounded `//` and `%`.
"""

import itertools

import pytest
from abstractions import INT_MAX, INT_MIN, Interval
from hypothesis import given
from hypothesis import strategies as st

import jvm

B = jvm.BinaryOpr
C = jvm.CmpOpr


def wrap(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 2**32 if v >= 2**31 else v


def java(op, x: int, y: int) -> int | None:
    """Java result of `x op y`, or None if Java throws ArithmeticException."""
    match op:
        case B.Add:
            return wrap(x + y)
        case B.Sub:
            return wrap(x - y)
        case B.Mul:
            return wrap(x * y)
        case B.Div | B.Rem:
            if y == 0:
                return None
            q = abs(x) // abs(y)
            q = -q if (x < 0) != (y < 0) else q
            return wrap(q) if op == B.Div else wrap(x - q * y)
    raise AssertionError(op)


EDGE = [INT_MIN, INT_MIN + 1, -7, -2, -1, 0, 1, 2, 7, INT_MAX - 1, INT_MAX]
bound = st.sampled_from(EDGE) | st.integers(-20, 20)


@st.composite
def intervals(draw):
    a, b = draw(bound), draw(bound)
    return Interval(min(a, b), max(a, b))


def members(i: Interval, extra=()):
    """A few concrete members, always including both endpoints."""
    pts = {i.min, i.max, *[v for v in extra if i.min <= v <= i.max]}
    if i.max - i.min < 12:
        pts |= set(range(i.min, i.max + 1))
    return pts


@pytest.mark.parametrize("op", [B.Add, B.Sub, B.Mul, B.Div, B.Rem])
@given(intervals(), intervals())
def test_arithmetic_is_sound(op, a, b):
    result, errors = a.arithmetic(b, op)
    for x, y in itertools.product(members(a, EDGE), members(b, EDGE)):
        expected = java(op, x, y)
        if expected is None:
            assert "divide by zero" in errors, (op, a, b, x, y)
        else:
            assert Interval(expected, expected) <= result, (op, a, b, x, y, result)


@pytest.mark.parametrize("op", [B.Div, B.Rem])
@given(intervals(), intervals())
def test_division_errors_exact(op, a, b):
    _, errors = a.arithmetic(b, op)
    assert ("divide by zero" in errors) == (b.min <= 0 <= b.max)


def test_division_examples():
    r, e = Interval(-3, 3).arithmetic(Interval(2, 5), B.Div)
    assert (r, e) == (Interval(-1, 1), set())
    r, e = Interval(7, 7).arithmetic(Interval(-2, -2), B.Div)
    assert (r, e) == (Interval(-3, -3), set())  # truncates toward zero
    r, e = Interval(5, 5).arithmetic(Interval(0, 0), B.Div)
    assert r.is_empty and e == {"divide by zero"}
    r, e = Interval(1, 9).arithmetic(Interval(-1, 1), B.Div)
    assert e == {"divide by zero"} and Interval(-9, 9) <= r


def test_min_div_minus_one_wraps():
    r, _ = Interval(INT_MIN, INT_MIN).arithmetic(Interval(-1, -1), B.Div)
    assert Interval(INT_MIN, INT_MIN) <= r


def test_rem_examples():
    r, e = Interval(-7, 7).arithmetic(Interval(3, 3), B.Rem)
    assert (r, e) == (Interval(-2, 2), set())
    r, _ = Interval(0, 9).arithmetic(Interval(4, 4), B.Rem)
    assert r == Interval(0, 3)


@given(intervals())
def test_neg_is_sound(a):
    r = a.neg()
    for x in members(a, EDGE):
        assert Interval(wrap(-x), wrap(-x)) <= r


@pytest.mark.parametrize("cond", list(C))
@pytest.mark.parametrize("holds", [True, False])
@given(intervals(), intervals())
def test_refine_is_sound(cond, holds, a, b):
    ra, rb = a.refine(b, cond, holds)
    test = {
        C.Eq: lambda x, y: x == y,
        C.Ne: lambda x, y: x != y,
        C.Lt: lambda x, y: x < y,
        C.Le: lambda x, y: x <= y,
        C.Gt: lambda x, y: x > y,
        C.Ge: lambda x, y: x >= y,
    }[cond]
    for x, y in itertools.product(members(a, EDGE), members(b, EDGE)):
        if test(x, y) == holds:
            assert Interval(x, x) <= ra and Interval(y, y) <= rb, (
                cond,
                holds,
                a,
                b,
                x,
                y,
            )


def test_refine_examples():
    assert Interval(0, 5).refine(Interval(0, 0), C.Ne) == (
        Interval(1, 5),
        Interval(0, 0),
    )
    assert Interval(0, 0).refine(Interval(0, 0), C.Ne)[0].is_empty
    assert Interval(-3, 3).refine(Interval(0, 0), C.Gt) == (
        Interval(1, 3),
        Interval(0, 0),
    )
    assert Interval(-3, 3).refine(Interval(0, 0), C.Gt, holds=False) == (
        Interval(-3, 0),
        Interval(0, 0),
    )
    assert Interval(INT_MAX, INT_MAX).refine(Interval(0, 0), C.Lt)[0].is_empty
