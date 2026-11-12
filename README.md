# JPAMB: Java Program Analysis Micro Benchmarks

JPAMB is a collection of small Java programs with various behaviors (crashes, infinite loops, and normal completion).
Your task is to build a program analysis tool that can predict what will happen when these programs run.
This benchmark is centered around Java methods with @Case annotations.
Your analyzer is given a method, but no input or annotations. The `@Case` annotations specify every possible outcome your analyzer is tested against.
Consider the following method:

```java
@Case("(false) -> assertion error")
@Case("(true) -> ok")
public static void assertBoolean(boolean shouldFail) {
    assert shouldFail;
}
```

`assertBoolean` has two known outcomes.
If given `false`, it throws an `assertion error`.
If given `true`, it finishes normally (`ok`).
The goal of the analysis is to predict which behaviors can happen in the method (e.g., `ok` and `assertion error`) without predicting behaviors that cannot happen (e.g., `divide by zero`).

## Getting Started

To get started with this repository, follow the following guides:

- First read and follow the [Setup](docs/setup.md) section.
- Then, consult the [Rules](docs/rules.md) section.
- To get inspired you can take a look at the [Partial Solutions](solutions/). They
  are written in Python so to run them check out the [Python](docs/python.md) section.
- To test a (concrete or abstract) interpreter, take a look at the [Interpret](docs/interpret.md) section.
- To figure out how to extend the benchmark suite consult the [Extending The Benchmark Suite](docs/extending-jpamb.md) section.

## Refactoring Project: Interval and Region Foundation

The region-based refactoring checker currently has a tested interval and region
foundation in [abstractions.py](solutions/static/src/abstractions.py), with tests
in [test_abstractions.py](solutions/static/tests/test_abstractions.py).

- `Interval(lower, upper)` describes inclusive signed 32-bit Java integer bounds.
  `None` means the corresponding Java integer limit, not mathematical infinity.
  Bounds are intersected with the Java integer range.
- `Interval.bot()` is empty; all empty intervals normalize to `Interval(0, -1)`.
  `Interval.top()` covers every Java `int`. `interval.is_empty` detects emptiness.
- `Interval.abstract(values)` accepts an iterable of `StackInt` values, including
  an empty iterable. Non-integer values and integers outside the Java range are
  rejected.
- `value in interval` checks membership. `first <= second` means inclusion,
  `first | second` is the enclosing interval, and `first & second` is intersection.
- `first.arithmetic(second, operation)` supports `jvm.BinaryOpr.Add` and `Sub`,
  returning `(result_interval, errors)`. These operations cannot throw, so their
  error set is empty. Possible overflow produces top, conservatively including
  wrapped Java results. Unsupported operations raise `NotImplementedError`.
- `Region({"a": Interval(-3, 3), "b": Interval(2, 5)})` is a box over named
  parameters. Its `bounds` are a read-only snapshot of the supplied mapping.
- `{"a": 0, "b": 2} in region` checks a complete input. Names must match exactly,
  and values must be Python integers, not booleans, floats, or `StackInt` wrappers.
- `region.is_empty` is true if any parameter interval is empty. `Region({})` is
  not empty: it contains the one no-argument input `{}`.

With Python 3.13+, the root JPAMB dependencies, pytest, and Hypothesis installed,
run from this repository's root:

```sh
PYTHONPATH=solutions/static/src:src python -m pytest solutions/static/tests/test_abstractions.py -q
```

This foundation is not yet integrated into the interpreter. In
[static.py](solutions/static/src/static.py), `State` and `initialstate` still use
`SignSet`; changing the import alone is not sufficient. Region boxes, branch
refinement, loop widening, and paired-method verdicts are not yet wired into the
interpreter; branch refinement, widening, and verdict computation still need
implementing.

## Supported Languages

You can write your analysis in any language you like, however, we have bindings
for Python, which makes it easier to work with the bytecode.

The downside is that running Python applications is a little bit harder.
To effectively do that please consult the [Python](docs/python.md) section.

## Quick Links

- **[uv documentation](https://docs.astral.sh/uv/)** - Python package manager we use
- **[Tree-sitter Java](https://tree-sitter.github.io/tree-sitter/using-parsers)** - For parsing Java source code
- **[JVM2JSON codec](https://github.com/kalhauge/jvm2json/blob/main/CODEC.txt)** - Understanding bytecode format
- **[Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)** - Windows C++ compiler
- **[JPAMB GitHub Issues](https://github.com/kalhauge/jpamb/issues)** - Get help if stuck
