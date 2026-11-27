# Observation Contract

This document fixes what "the two versions behave the same" means in the
region-based refactoring checker. The verdict rules in
[verdict-rules.md](verdict-rules.md) and the reference observations in
[evaluation/](../../evaluation/) both rely on it. If the analyser, the harness or
the corpus disagrees with this document, this document wins and the other part
must change.

## 1. Setting

A *pair* is two static methods `m` and `m_edited` in the same class with the
same descriptor. They are run on the same input, one call at a time, starting
from a fresh JVM state each time. Assertions are enabled (`java -ea`), so
`$assertionsDisabled` is `false`. JPAMB uses the same convention, and so does
[Observe.java](../../evaluation/observe/Observe.java).

An *input* is a vector `x = (x1, …, xn)` with one value per parameter. A
*region* `R` is a box: one inclusive interval per parameter (see `Region` in
[abstractions.py](../../solutions/static/src/abstractions.py)).

## 2. What counts as behaviour

The behaviour of a version `P` on an input `x` is the *observation*

```
obs_P(x) = (o, v)
```

where `o` is the outcome class and `v` is the return value.

| Outcome `o` (JPAMB spelling) | Meaning | `v` |
|---|---|---|
| `ok` | the call returns normally | the returned value (`void` gives the unit value `()`) |
| `assertion error` | an `AssertionError` escapes the method | `⊥` (none) |
| `divide by zero` | an `ArithmeticException` escapes (`/` or `%` by zero) | `⊥` |
| `null pointer` | a `NullPointerException` escapes | `⊥` |
| `out of bounds` | an `ArrayIndexOutOfBoundsException` escapes | `⊥` |
| `*` | the call does not terminate | `⊥` |

Two versions **agree on `x`** iff `obs_m(x) = obs_m_edited(x)`. That means the
same outcome class and, when the outcome is `ok`, the same return value.

They **preserve behaviour on `R`** iff they agree on every `x ∈ R`, and
**change behaviour on `R`** iff they disagree on some `x ∈ R`.

### 2.1 What is deliberately *not* observed

- **Error payloads.** The exception message, stack trace, throwing instruction
  and exception object identity are not observed. Two versions that both throw
  `ArithmeticException`, from different divisions, agree.
- **The path taken.** Instruction counts, timing and intermediate values are
  not observed. Only the final observation matters, so removing dead code or
  reordering pure computations is allowed.
- **Side channels.** Standard output, logging and allocation are not observed.
  Supported methods cannot write to the heap anyway (§3).

### 2.2 Return values

Return values are compared as JVM stack values, that is as signed 32-bit two's
complement integers. `boolean`, `byte`, `char` and `short` results are compared
after widening to `int`, the way the JVM returns them (`true` = 1, `false` = 0).
The harness must use the same encoding. Reflection gives `"true"`/`"false"` for
a `boolean`, so it has to map these to 1/0 before comparing with the analyser.

### 2.3 Determinism

Under §3, every supported method is a *function* of its input: same input,
same observation. The verdict rules need this. Without it, "both versions throw
on every input" would not imply "both versions agree on every input".

## 3. Supported methods

A pair is supported iff **both** versions satisfy every condition below. A
syntactic pass over the decompiled bytecode can check all of them.

1. **Static**, with only parameters of type `int` (JVM `I`). `boolean`, `byte`,
   `char` and `short` (`Z B C S`) are integers on the JVM stack and may be added
   later with the matching interval bounds. The analyser already accepts
   `boolean` parameters, but the corpus and `Observe.java` only use `int`.
2. **Return type** `int` or `void`.
3. **Allowed instructions:** `Push` (int constants), `Load`/`Store` (int locals),
   `Incr`, `Dup`, `Negate`, `Binary` on ints (`add sub mul div rem`), `Ifz`,
   `If`, `Goto` and `Return`.
4. **Assertion pattern only.** `Get` is allowed only for the static field
   `$assertionsDisabled`. `New` and `InvokeSpecial` are allowed only for
   `java/lang/AssertionError` and its `<init>`. `Throw` is allowed only for that
   object.
5. **No heap writes and no calls.** `ArrayStore`, `NewArray`, any other `New`,
   `InvokeStatic`, `InvokeVirtual` and `InvokeInterface` are rejected. This is
   stricter than "no heap writes". Rejecting calls keeps every method
   deterministic and intraprocedural. Calls to other supported static methods
   could be allowed later by inlining them.
6. **Same descriptor** for `m` and `m_edited`, so one region describes the
   inputs of both.

**Loops.** The interval analysis supports loops through widening
([soundness-notes.md](soundness-notes.md) §7). The rules in
[verdict-rules.md](verdict-rules.md) do not change, but outcome `*` becomes
reachable. The Z3 return comparator is still loop-free: a backward jump makes
it answer `unknown`. So loop pairs are decided only by Rules 1, 2 and 2b (for
example `loopThenZero` in `EvalPairs.java`).

## 4. Excluded

The checker answers `unsupported` for the pair (never `preserved`) when either
version uses:

- reference, array, `String`, `long`, `float` or `double` parameters or results,
- instance methods, heap writes, method calls, or static fields other than
  `$assertionsDisabled`,
- exceptions other than the five classes in §2. For example, a `throw` of a
  `RuntimeException` the method builds itself is excluded, because §2 has no
  outcome class for it,
- `try`/`catch`. An exception caught inside the method is not an outcome, and
  the analyser does not model handlers.

## 5. Reference observations

The ground truth comes from the real JVM, not from our analyser or interpreter.
[Observe.java](../../evaluation/observe/Observe.java) runs both versions on
every input of the declared domain in
[pairs.txt](../../evaluation/pairs.txt) and writes `obs` for both into
`evaluation/observations/<pair>.csv`.

- A call that runs longer than 1 s is recorded as `*`. For loop-free methods this
  cannot misclassify anything. For loops it is an approximation: a slow
  method that does terminate would be labelled `*`. Keep inputs small enough
  that this does not happen.
- An exception outside §2 makes `Observe` stop with an error rather than
  record a made-up outcome. This is intentional: the pair is outside the
  contract.

### 5.1 How analyser claims are checked

The analyser reports a verdict for each region (see Listing 2 in the proposal).
The harness checks each claim only on `R ∩ D`, where `D` is the declared
domain:

| Claim | Checked by |
|---|---|
| `preserved` on `R` | every observed `x ∈ R ∩ D` has `same = yes` |
| `changed` on `R` with witness `w` | `w ∈ R`, and replaying `w` on the JVM gives different observations |
| `unknown` on `R` | nothing to check; counts as not decided |

A claim on inputs outside `D` cannot be refuted by the reference data. The paper
must state this as a threat to validity.
