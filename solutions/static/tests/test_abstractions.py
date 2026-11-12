import abstractions as ab
import pytest
from hypothesis import given
from hypothesis import strategies as st

import jvm
import jvm.state as jvms


def st_i32():
    return st.integers(min_value=-(2**31), max_value=2**31 - 1)


def st_u32():
    return st.integers(min_value=0, max_value=2**32)


def st_stack_ints():
    return st_i32().map(jvms.StackInt)


def st_stack_refs():
    return st_u32().map(jvms.StackReference)


def st_signset():
    return (
        st.sets(st.integers(min_value=-1, max_value=1)).map(frozenset).map(ab.SignSet)
    )


@given(st_signset(), st_signset(), st_signset())
def test_signset_is_poset(a: ab.SignSet, b: ab.SignSet, c: ab.SignSet):
    ab.is_poset(a, b, c)


@given(st_signset(), st_signset(), st_signset())
def test_signset_is_lattice(a: ab.SignSet, b: ab.SignSet, c: ab.SignSet):
    ab.is_lattice(a, b, c)


@given(st.sets(st_stack_ints()), st_signset())
def test_signset_is_galoi(a: set[jvms.StackInt], b: ab.SignSet):
    ab.is_galoi(a, b)


def arithmetic(opr, x, y):
    match opr:
        case jvm.BinaryOpr.Add:
            return jvms.StackInt(x.value + y.value)
        case _:
            raise NotImplementedError("TODO")


@given(
    st.sampled_from([jvm.BinaryOpr.Add]),
    st.sets(st_stack_ints()),
    st.sets(
        st_stack_ints(),
    ),
)
def test_signset_arithmetic(
    opr: jvm.BinaryOpr, xs: set[jvms.StackInt], ys: set[jvms.StackInt]
):
    real = ab.SignSet.abstract(arithmetic(opr, x, y) for x in xs for y in ys)
    (abstracted, _errs) = ab.SignSet.abstract(xs).arithmetic(
        ab.SignSet.abstract(ys), opr
    )
    assert real <= abstracted


def compare(opr, x, y):
    match opr:
        case jvm.CmpOpr.Le:
            return x.value <= y.value
        case _:
            raise NotImplementedError("TODO")


@given(
    st.sampled_from([jvm.CmpOpr.Le]),
    st.sets(st_stack_ints()),
    st.sets(
        st_stack_ints(),
    ),
)
def test_signset_compare(
    opr: jvm.CmpOpr, xs: set[jvms.StackInt], ys: set[jvms.StackInt]
):
    real = {compare(opr, x, y) for x in xs for y in ys}
    abstracted = set(ab.SignSet.abstract(xs).compare(ab.SignSet.abstract(ys), opr))
    assert real <= abstracted


@st.composite
def st_interval(draw):
    lower = draw(st.one_of(st.none(), st_i32()))
    upper = draw(st.one_of(st.none(), st_i32()))
    return ab.Interval(lower, upper)


@pytest.mark.parametrize(
    "lower,upper,number,expected",
    [
        (2, 5, 2, True),
        (2, 5, 5, True),
        (2, 5, 3, True),
        (2, 5, 1, False),
        (2, 5, 6, False),
        (0, 0, 0, True),
        (0, 0, 1, False),
        (1, 0, 0, False),
        (1, 0, 1, False),
        (None, 5, -100, True),
        (None, 5, 6, False),
        (2, None, 100, True),
        (2, None, 1, False),
        (None, None, -(2**31), True),
        (None, None, 2**31 - 1, True),
    ],
)
def test_interval_contains(lower, upper, number, expected):
    interval = ab.Interval(lower, upper)
    assert (jvms.StackInt(number) in interval) is expected


@given(st_interval(), st_interval(), st_interval())
def test_interval_is_poset(a: ab.Interval, b: ab.Interval, c: ab.Interval):
    ab.is_poset(a, b, c)


@given(st_interval(), st_interval(), st_interval())
def test_interval_is_lattice(a: ab.Interval, b: ab.Interval, c: ab.Interval):
    ab.is_lattice(a, b, c)


@given(st.sets(st_stack_ints()), st_interval())
def test_interval_is_galoi(a: set[jvms.StackInt], b: ab.Interval):
    ab.is_galoi(a, b)


def test_interval_empty_is_canonical():
    assert ab.Interval(5, 2) == ab.Interval(1, 0) == ab.Interval.bot()
    assert ab.Interval.bot().is_empty
    assert ab.Interval(0, 0) != ab.Interval.bot()


def test_interval_top_is_machine_integer_range():
    assert ab.Interval(None, None) == ab.Interval.top()
    assert ab.Interval.top() == ab.Interval(-(2**31), 2**31 - 1)
    assert jvms.StackInt(2**31) not in ab.Interval.top()
    assert jvms.StackInt(-(2**31) - 1) not in ab.Interval.top()


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], ab.Interval.bot()),
        ([3], ab.Interval(3, 3)),
        ([2, 8, 4], ab.Interval(2, 8)),
    ],
)
def test_interval_abstract_examples(values, expected):
    assert ab.Interval.abstract(jvms.StackInt(value) for value in values) == expected


@pytest.mark.parametrize("value", [-(2**31) - 1, 2**31])
def test_interval_abstract_rejects_non_i32(value):
    with pytest.raises(ValueError):
        ab.Interval.abstract([jvms.StackInt(value)])


@pytest.mark.parametrize(
    "lower,upper,expected",
    [
        (ab.INT_MIN - 5, ab.INT_MIN + 2, ab.Interval(ab.INT_MIN, ab.INT_MIN + 2)),
        (ab.INT_MAX - 2, ab.INT_MAX + 5, ab.Interval(ab.INT_MAX - 2, ab.INT_MAX)),
        (ab.INT_MIN - 1, ab.INT_MAX + 1, ab.Interval.top()),
        (ab.INT_MAX + 1, ab.INT_MAX + 10, ab.Interval.bot()),
        (ab.INT_MIN - 10, ab.INT_MIN - 1, ab.Interval.bot()),
        (None, ab.INT_MIN - 1, ab.Interval.bot()),
        (ab.INT_MAX + 1, None, ab.Interval.bot()),
    ],
)
def test_interval_constructor_clips_to_java_range(lower, upper, expected):
    assert ab.Interval(lower, upper) == expected


@pytest.mark.parametrize("lower,upper", [("0", 1), (0, "1"), (0.5, 1), (0, 1.5)])
def test_interval_constructor_rejects_invalid_bound_types(lower, upper):
    with pytest.raises(TypeError):
        ab.Interval(lower, upper)


def test_interval_rejects_non_integer_values():
    with pytest.raises(TypeError):
        ab.Interval.abstract([jvms.StackReference(0)])
    assert jvms.StackReference(0) not in ab.Interval.top()


def test_interval_join_and_meet_examples():
    assert ab.Interval(1, 3) | ab.Interval(7, 9) == ab.Interval(1, 9)
    assert ab.Interval(1, 6) & ab.Interval(4, 9) == ab.Interval(4, 6)
    assert ab.Interval(1, 3) & ab.Interval(5, 8) == ab.Interval.bot()


def test_interval_order_is_inclusion_not_endpoint_order():
    assert ab.Interval(2, 5) <= ab.Interval(1, 9)
    assert not ab.Interval(1, 9) <= ab.Interval(2, 5)
    assert not ab.Interval(1, 3) < ab.Interval(5, 8)


@given(st_interval(), st_interval(), st_interval())
def test_interval_lattice_laws(first, second, third):
    assert first | second == second | first
    assert first & second == second & first
    assert (first | second) | third == first | (second | third)
    assert (first & second) & third == first & (second & third)
    assert first | first == first
    assert first & first == first
    assert first | (first & second) == first
    assert first & (first | second) == first
    assert first <= first | second
    assert second <= first | second
    assert first & second <= first
    assert first & second <= second


@pytest.mark.parametrize(
    "first,second,operation,expected",
    [
        (ab.Interval(2, 5), ab.Interval(1, 3), jvm.BinaryOpr.Add, ab.Interval(3, 8)),
        (ab.Interval(4, 8), ab.Interval(1, 3), jvm.BinaryOpr.Sub, ab.Interval(1, 7)),
        (ab.Interval(2, 5), ab.Interval(2, 5), jvm.BinaryOpr.Sub, ab.Interval(-3, 3)),
        (
            ab.Interval(ab.INT_MAX, ab.INT_MAX),
            ab.Interval(1, 1),
            jvm.BinaryOpr.Add,
            ab.Interval.top(),
        ),
        (
            ab.Interval(ab.INT_MIN, ab.INT_MIN),
            ab.Interval(1, 1),
            jvm.BinaryOpr.Sub,
            ab.Interval.top(),
        ),
        (
            ab.Interval(ab.INT_MIN, ab.INT_MIN),
            ab.Interval(-1, -1),
            jvm.BinaryOpr.Add,
            ab.Interval.top(),
        ),
        (
            ab.Interval(ab.INT_MAX, ab.INT_MAX),
            ab.Interval(-1, -1),
            jvm.BinaryOpr.Sub,
            ab.Interval.top(),
        ),
        (
            ab.Interval(ab.INT_MAX, ab.INT_MAX),
            ab.Interval(0, 0),
            jvm.BinaryOpr.Add,
            ab.Interval(ab.INT_MAX, ab.INT_MAX),
        ),
        (ab.Interval.top(), ab.Interval(0, 0), jvm.BinaryOpr.Add, ab.Interval.top()),
        (ab.Interval.bot(), ab.Interval(1, 2), jvm.BinaryOpr.Add, ab.Interval.bot()),
        (ab.Interval(1, 2), ab.Interval.bot(), jvm.BinaryOpr.Sub, ab.Interval.bot()),
    ],
)
def test_interval_arithmetic_examples(first, second, operation, expected):
    result, errors = first.arithmetic(second, operation)
    assert result == expected
    assert errors == set()


@given(
    st.sets(st_stack_ints(), max_size=8),
    st.sets(st_stack_ints(), max_size=8),
    st.sampled_from([jvm.BinaryOpr.Add, jvm.BinaryOpr.Sub]),
)
def test_interval_arithmetic_includes_wrapped_java_results(first, second, operation):
    result, errors = ab.Interval.abstract(first).arithmetic(
        ab.Interval.abstract(second), operation
    )
    assert errors == set()
    for left in first:
        for right in second:
            concrete = (
                left.value + right.value
                if operation == jvm.BinaryOpr.Add
                else left.value - right.value
            )
            wrapped = (concrete + 2**31) % 2**32 - 2**31
            assert jvms.StackInt(wrapped) in result


def test_interval_unsupported_arithmetic_is_explicit():
    with pytest.raises(NotImplementedError):
        ab.Interval(1, 2).arithmetic(ab.Interval(1, 2), jvm.BinaryOpr.Div)


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"a": -3, "b": 2}, True),
        ({"a": 3, "b": 5}, True),
        ({"b": 3, "a": 0}, True),
        ({"a": -4, "b": 2}, False),
        ({"a": 0, "b": 6}, False),
        ({"a": 0}, False),
        ({"a": 0, "b": 2, "c": 1}, False),
        ({"a": 0, "c": 2}, False),
        ({"a": True, "b": 2}, False),
        ({"a": 0.0, "b": 2}, False),
        ({"a": "0", "b": 2}, False),
        ({"a": jvms.StackInt(0), "b": 2}, False),
        ([0, 2], False),
        (None, False),
    ],
)
def test_region_contains_named_integer_inputs(values, expected):
    region = ab.Region({"a": ab.Interval(-3, 3), "b": ab.Interval(2, 5)})
    assert not region.is_empty
    assert (values in region) is expected


@pytest.mark.parametrize("empty_parameter", ["a", "b"])
def test_region_is_empty_if_any_parameter_is_empty(empty_parameter):
    bounds = {"a": ab.Interval.top(), "b": ab.Interval.top()}
    bounds[empty_parameter] = ab.Interval.bot()
    region = ab.Region(bounds)
    assert region.is_empty
    assert {"a": 0, "b": 0} not in region


def test_region_without_parameters_contains_the_empty_input():
    region = ab.Region({})
    assert not region.is_empty
    assert {} in region
    assert {"a": 0} not in region


def test_region_keeps_an_immutable_snapshot_of_bounds():
    bounds = {"a": ab.Interval(1, 3)}
    region = ab.Region(bounds)
    bounds["a"] = ab.Interval.bot()
    bounds["b"] = ab.Interval.top()
    assert region.bounds == {"a": ab.Interval(1, 3)}
    assert {"a": 2} in region
    with pytest.raises(TypeError):
        region.bounds["a"] = ab.Interval.bot()


@pytest.mark.parametrize("bounds", [{0: ab.Interval.top()}, {"a": (1, 3)}])
def test_region_rejects_invalid_bounds(bounds):
    with pytest.raises(TypeError):
        ab.Region(bounds)


@given(
    st.lists(st_interval(), max_size=4),
    st.lists(st_i32(), max_size=4),
)
def test_region_membership_is_the_cartesian_product(intervals, values):
    region = ab.Region(
        {f"arg{index}": interval for index, interval in enumerate(intervals)}
    )
    inputs = {f"arg{index}": value for index, value in enumerate(values)}
    expected = len(intervals) == len(values) and all(
        jvms.StackInt(value) in interval for value, interval in zip(values, intervals)
    )
    assert (inputs in region) is expected
    assert region.is_empty == any(interval.is_empty for interval in intervals)
