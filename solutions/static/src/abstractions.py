from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Self

import jvm
import jvm.state as jvms


class Poset(ABC):
    @abstractmethod
    def __eq__(self, other: Self) -> bool: ...

    @abstractmethod
    def __lt__(self, other: Self) -> bool: ...

    def __le__(self, other: Self) -> bool:
        return self == other or self < other

    @abstractmethod
    def __gt__(self, other: Self) -> bool: ...

    def __ge__(self, other: Self) -> bool:
        return self == other or self > other


def is_reflexive(a: Poset):
    # Checking if the relation is reflexive (a == a)
    assert a == a, f"Reflexivity check failed: Element {a} is not related to itself."  # noqa: PLR0124


def is_antisymmetric(a: Poset, b: Poset):
    if a != b:
        # Checking that if a <= b and b <= a, then a must equal b
        assert not (a <= b <= a), (
            f"Antisymmetry violation: Found elements where {a} <= {b} and {b} <= {a}, "
            f"but {a} != {b}."
        )


def is_transitive(a: Poset, b: Poset, c: Poset):
    if a <= b <= c:
        # Checking that if a <= b and b <= c, then a <= c
        assert a <= c, (
            f"Transitivity violation: Found path {a} <= {b} and {b} <= {c}, "
            f"but {a} is not related to {c}."
        )


def is_poset(a: Poset, b: Poset, c: Poset):
    for x in [a, b, c]:
        is_reflexive(x)

    for x in [b, c]:
        is_antisymmetric(a, x)

    is_transitive(a, b, c)


class Lattice(Poset):
    @classmethod
    @abstractmethod
    def top(cls) -> Self:
        raise NotImplementedError(f"top: {cls}")

    @classmethod
    def bot(cls) -> Self:
        return cls.abstract([])

    @abstractmethod
    def __or__(self, other: Self) -> Self: ...

    @abstractmethod
    def __and__(self, other: Self) -> Self: ...


def is_lattice_identities(a: Lattice):
    # Top element identity checks
    assert (a | a.top()) == a.top(), (
        f"Top identity fail: ({a} | {a.top()}) -> {a | a.top()} != {a.top()}"
    )
    assert (a.top() | a) == a.top(), (
        f"Top identity fail (commute): ({a.top()} | {a}) != {a.top()}"
    )
    assert (a & a.top()) == a, f"Top identity fail (meet): ({a} & {a.top()}) != {a}"
    assert (a.top() & a) == a, (
        f"Top identity fail (meet commute): ({a.top()} & {a}) != {a}"
    )

    # Bottom element identity checks
    assert (a & a.bot()) == a.bot(), (
        f"Bottom identity fail: ({a} & {a.bot()}) != {a.bot()}"
    )
    assert (a.bot() & a) == a.bot(), (
        f"Bottom identity fail (commute): ({a.bot()} & {a}) != {a.bot()}"
    )
    assert (a.bot() | a) == a, f"Bottom identity fail (join): ({a.bot()} | {a}) != {a}"
    assert (a | a.bot()) == a, (
        f"Bottom identity fail (join commute): ({a} | {a.bot()}) != {a}"
    )


def is_lattice(a: Lattice, b: Lattice, c: Lattice):
    for x in [a, b, c]:
        is_lattice_identities(x)

    if not (a | b <= c):
        # Calculate values for the error message
        assert not (a <= c and b <= c), (
            f"Upper bound check failed: ({a} | {b}) -> {a | b} is not <= {c}. "
            f"Check individual bounds: {a <= c=}, {b <= c=}."
        )

    if not (c <= a & b):
        # Calculate values for the error message
        assert not (c <= a and c <= b), (
            f"Lower bound check failed: {c} is not <= ({a} & {b}) -> {a & b}. "
            f"Check individual bounds: {c <= a=}, {c <= b=}."
        )


class Abstraction(ABC):
    """This is the minimal interface for an abstraction."""

    @classmethod
    @abstractmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        raise NotImplementedError(f"abstract: {cls}")

    @abstractmethod
    def __contains__(self, value: jvms.StackValue) -> bool: ...


def is_galoi(a: set[jvms.StackValue], b: Abstraction):
    alpha_a = b.abstract(a)

    for value in a:
        assert value in alpha_a, f"{value} not in {a}"

    if alpha_a <= b:
        for value in a:
            assert value in b, f"{value} not in {b}"


type Sign = Literal[-1, 0, 1]


def to_sign(value: jvms.StackValue) -> Sign:
    match value:
        case jvms.StackInt(v):
            return (v > 0) - (v < 0)
        case a:
            raise NotImplementedError(f"Unsupported value {value!r}")


@dataclass(frozen=True, order=True)
class SignSet(Abstraction, Lattice):
    signs: frozenset[Sign]

    def __str__(self):
        return f"{{{''.join(z for z, b in zip('-0+', [-1, 0, 1]) if b in self.signs)}}}"

    def __sexpr__(self):
        return str(self)

    @classmethod
    def from_sign(cls, code):
        return cls(frozenset(b for z, b in zip("-0+", [-1, 0, 1]) if z in code))

    @classmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        signs = set()
        for value in values:
            signs.add(to_sign(value))
        return cls(frozenset(signs))

    def __contains__(self, value: jvms.StackValue) -> bool:
        return to_sign(value) in self.signs

    @classmethod
    def top(cls) -> bool:
        return cls(frozenset([-1, 0, 1]))

    def __or__(self, other: "SignSet") -> "SignSet":
        if not isinstance(other, SignSet):
            return NotImplemented

        return SignSet(self.signs | other.signs)

    def __and__(self, other: "SignSet") -> "SignSet":
        if not isinstance(other, SignSet):
            return NotImplemented

        return SignSet(self.signs & other.signs)

    def arithmetic(
        self, other: "SignSet", opr: jvm.BinaryOpr
    ) -> tuple["SignSet", set[str]]:
        match opr:
            case jvm.BinaryOpr.Add:
                output = set()
                if 1 in self.signs:
                    output.add(1)
                    if -1 in other.signs:
                        output.update([0, -1])

                if -1 in self.signs:
                    output.add(-1)
                    if 1 in other.signs:
                        output.update([0, 1])

                if 0 in self.signs:
                    output.update(other.signs)

                return (SignSet(output), set())
            case _:
                raise NotImplementedError(f"TODO: {opr}")

    def compare(self, other: "SignSet", opr: jvm.CmpOpr) -> Iterable[bool]:
        match opr:
            case jvm.CmpOpr.Le:
                cases = set()
                for x in self.signs:
                    for y in other.signs:
                        if x == 0 or y == 0:
                            cases.add(x <= y)
                            continue
                        if x <= y:
                            cases.add(True)
                        if x >= y:
                            cases.add(False)
                return cases
            case _:
                raise NotImplementedError(f"TODO: {opr}")


import builtins
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

INT_MIN = -(2**31)
INT_MAX = 2**31 - 1


@dataclass(frozen=True, init=False)
class Interval(Abstraction, Lattice):
    min: int
    max: int

    def __init__(self, min: int | None, max: int | None):
        lower = INT_MIN if min is None else min
        upper = INT_MAX if max is None else max
        if not isinstance(lower, int) or not isinstance(upper, int):
            raise TypeError("Interval bounds must be integers or None")
        lower = builtins.max(lower, INT_MIN)
        upper = builtins.min(upper, INT_MAX)
        if lower > upper:
            lower, upper = 0, -1
        object.__setattr__(self, "min", lower)
        object.__setattr__(self, "max", upper)

    @property
    def is_empty(self) -> bool:
        return self.min > self.max

    def __str__(self):
        return f"{self.min}:{self.max}"

    def __sexpr__(self):
        return str(self)

    @classmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        lower, upper = INT_MAX, INT_MIN
        for value in values:
            if not isinstance(value, jvms.StackInt):
                raise TypeError(f"Expected a StackInt, got {value!r}")
            if not INT_MIN <= value.value <= INT_MAX:
                raise ValueError(f"Not a signed 32-bit integer: {value.value}")
            lower = min(lower, value.value)
            upper = max(upper, value.value)
        return cls(lower, upper)

    def __contains__(self, value: jvms.StackValue) -> bool:
        if not isinstance(value, jvms.StackInt):
            return False
        return self.min <= value.value <= self.max

    @classmethod
    def top(cls) -> Self:
        return cls(INT_MIN, INT_MAX)

    def __or__(self, other: "Interval") -> "Interval":
        if not isinstance(other, Interval):
            return NotImplemented
        if self.is_empty:
            return other
        if other.is_empty:
            return self
        return Interval(min(self.min, other.min), max(self.max, other.max))

    def __and__(self, other: "Interval") -> "Interval":
        if not isinstance(other, Interval):
            return NotImplemented
        if self.is_empty or other.is_empty:
            return Interval.bot()
        return Interval(max(self.min, other.min), min(self.max, other.max))

    def __lt__(self, other: "Interval") -> bool:
        if not isinstance(other, Interval):
            return NotImplemented
        return self != other and (
            self.is_empty
            or (not other.is_empty and other.min <= self.min and self.max <= other.max)
        )

    def __gt__(self, other: "Interval") -> bool:
        if not isinstance(other, Interval):
            return NotImplemented
        return other < self

    def arithmetic(
        self, other: "Interval", opr: jvm.BinaryOpr
    ) -> tuple["Interval", set[str]]:
        """Abstract Java `int` arithmetic: returns (result interval, error outcomes).

        Soundness contract (S): for every x in self and y in other for which the
        operation does not throw, the wrapped Java result is in the interval; if
        it can throw, "divide by zero" is in the error set. Anything that might
        overflow becomes top, so wrapped results are never lost.
        """
        if self.is_empty or other.is_empty:
            return (Interval.bot(), set())
        match opr:
            case jvm.BinaryOpr.Add:
                return (
                    _checked(self.min + other.min, self.max + other.max),
                    set(),
                )
            case jvm.BinaryOpr.Sub:
                return (
                    _checked(self.min - other.max, self.max - other.min),
                    set(),
                )
            case jvm.BinaryOpr.Mul:
                corners = [
                    self.min * other.min,
                    self.min * other.max,
                    self.max * other.min,
                    self.max * other.max,
                ]
                return (_checked(min(corners), max(corners)), set())
            case jvm.BinaryOpr.Div | jvm.BinaryOpr.Rem:
                errors = {"divide by zero"} if other.min <= 0 <= other.max else set()
                result = Interval.bot()
                for part in other._nonzero_parts():
                    result = result | (
                        self._div_part(part)
                        if opr == jvm.BinaryOpr.Div
                        else self._rem_part(part)
                    )
                return (result, errors)
            case _:
                raise NotImplementedError(f"Unsupported interval arithmetic: {opr}")

    def _nonzero_parts(self) -> list["Interval"]:
        """The divisor with 0 removed, as up to two intervals (negative, positive)."""
        parts = []
        if self.min <= -1:
            parts.append(Interval(self.min, builtins.min(self.max, -1)))
        if self.max >= 1:
            parts.append(Interval(builtins.max(self.min, 1), self.max))
        return [p for p in parts if not p.is_empty]

    def _div_part(self, divisor: "Interval") -> "Interval":
        # divisor has a fixed sign, so truncated division is monotone in both
        # arguments and its extremes are at the corners.
        if self.min == INT_MIN and divisor.min <= -1 <= divisor.max:
            return Interval.top()  # MIN / -1 wraps to MIN in Java
        corners = [
            _trunc_div(x, y)
            for x in (self.min, self.max)
            for y in (divisor.min, divisor.max)
        ]
        return Interval(min(corners), max(corners))

    def _rem_part(self, divisor: "Interval") -> "Interval":
        # Java: the remainder has the sign of the dividend and |r| < |divisor|.
        m = builtins.max(abs(divisor.min), abs(divisor.max)) - 1
        lower = 0 if self.min >= 0 else builtins.max(self.min, -m)
        upper = 0 if self.max <= 0 else builtins.min(self.max, m)
        return Interval(lower, upper)

    def widen(self, other: "Interval") -> "Interval":
        """Standard interval widening: any bound that grows jumps to the int limit.

        `self` is the old value, `other` the new one. Result contains both, and a
        chain of widenings changes each bound at most once, so it terminates.
        """
        if self.is_empty:
            return other
        if other.is_empty:
            return self
        lower = self.min if other.min >= self.min else INT_MIN
        upper = self.max if other.max <= self.max else INT_MAX
        return Interval(lower, upper)

    def neg(self) -> "Interval":
        if self.is_empty:
            return self
        return _checked(-self.max, -self.min)

    def refine(
        self, other: "Interval", cond: jvm.CmpOpr, holds: bool = True
    ) -> tuple["Interval", "Interval"]:
        """Narrow (self, other) to the pairs (x, y) with `x cond y` == holds.

        Sound: every x in self, y in other with the condition true stay inside
        the returned intervals. May return empty intervals (branch infeasible).
        """
        if not holds:
            cond = _NEGATED[cond]
        a, b = self, other
        if a.is_empty or b.is_empty:
            return (Interval.bot(), Interval.bot())
        match cond:
            case jvm.CmpOpr.Eq:
                both = a & b
                return (both, both)
            case jvm.CmpOpr.Ne:
                if a.min == a.max == b.min == b.max:
                    return (Interval.bot(), Interval.bot())
                return (a._without_endpoint(b), b._without_endpoint(a))
            case jvm.CmpOpr.Lt:
                return (a & Interval(None, b.max - 1), b & Interval(a.min + 1, None))
            case jvm.CmpOpr.Le:
                return (a & Interval(None, b.max), b & Interval(a.min, None))
            case jvm.CmpOpr.Gt:
                return (a & Interval(b.min + 1, None), b & Interval(None, a.max - 1))
            case jvm.CmpOpr.Ge:
                return (a & Interval(b.min, None), b & Interval(None, a.max))
        raise NotImplementedError(f"Unsupported comparison: {cond}")

    def _without_endpoint(self, other: "Interval") -> "Interval":
        """self minus the single value `other`, if that value is an endpoint."""
        if other.min != other.max:
            return self
        v = other.min
        if self.min == self.max == v:
            return Interval.bot()
        if self.min == v:
            return Interval(self.min + 1, self.max)
        if self.max == v:
            return Interval(self.min, self.max - 1)
        return self


def _trunc_div(x: int, y: int) -> int:
    """Java integer division (truncates toward zero), y != 0, no wrapping."""
    q = abs(x) // abs(y)
    return -q if (x < 0) != (y < 0) else q


def _checked(lower: int, upper: int) -> "Interval":
    """Interval of mathematical bounds, or top if a Java int could wrap."""
    if lower < INT_MIN or upper > INT_MAX:
        return Interval.top()
    return Interval(lower, upper)


_NEGATED = {
    jvm.CmpOpr.Eq: jvm.CmpOpr.Ne,
    jvm.CmpOpr.Ne: jvm.CmpOpr.Eq,
    jvm.CmpOpr.Lt: jvm.CmpOpr.Ge,
    jvm.CmpOpr.Ge: jvm.CmpOpr.Lt,
    jvm.CmpOpr.Le: jvm.CmpOpr.Gt,
    jvm.CmpOpr.Gt: jvm.CmpOpr.Le,
}


@dataclass(frozen=True)
class Region:
    bounds: Mapping[str, Interval]

    def __post_init__(self):
        bounds = dict(self.bounds)
        if any(
            not isinstance(name, str) or not isinstance(interval, Interval)
            for name, interval in bounds.items()
        ):
            raise TypeError("Region bounds must map parameter names to intervals")
        object.__setattr__(self, "bounds", MappingProxyType(bounds))

    @property
    def is_empty(self) -> bool:
        return any(interval.is_empty for interval in self.bounds.values())

    def __contains__(self, values: object) -> bool:
        if not isinstance(values, Mapping) or values.keys() != self.bounds.keys():
            return False
        return all(
            type(values[name]) is int and jvms.StackInt(values[name]) in interval
            for name, interval in self.bounds.items()
        )
