# Review: Interval Primitives and Corpus Against the Correctness Assumptions

This review checks Krish's interval and region primitives (commit `71dc935`) and
Cristina's corpus and evaluation (commits `4f38873`, `1b8310b`) against
[observation-contract.md](observation-contract.md) and
[verdict-rules.md](verdict-rules.md). It ends with the list of unresolved
correctness issues.

**What was run** on `main` at `28fa721`:

- `pytest solutions/static/tests/test_abstractions.py`: 79 passed.
- `python3 evaluation/check_expected.py`: answer key and `@Case` annotations agree
  with the committed observations.
- `bash evaluation/observe.sh` (Temurin JDK 21): the regenerated CSVs are
  byte-identical to the committed ones (`git status` clean), with 0/49, 1/49 and
  1/7 differing inputs for `safeDiv`, `ratio` and `sign`.
- The z3 semantics claims below were checked with `z3-solver` directly.

## 1. Interval primitives (`solutions/static/src/abstractions.py`)

### 1.1 What is correct

Each operation was checked against the soundness condition from the lecture,
`α(op(X, Y)) ⊑ op♯(α(X), α(Y))`, over Java `int`s.

| Primitive | Verdict | Argument |
|---|---|---|
| `abstract`, `in` | sound and exact | `α(S) = [min S, max S]`. `γ([l, u])` is every Java `int` in `[l, u]`, so `S ⊆ γ(α(S))`. The Galois property is hypothesis-tested (`test_interval_is_galoi`). |
| `<=` | correct | Inclusion, with `⊥` below everything. Endpoint order is not used (`test_interval_order_is_inclusion_not_endpoint_order`). |
| `\|` (join) | sound, least | `[min, max]` of the endpoints, with `⊥` as identity. It is the least interval containing both. |
| `&` (meet) | exact | The intersection of two intervals is an interval. |
| `+` | sound | For `x ∈ [a, b]` and `y ∈ [c, d]`, the mathematical sum is in `[a+c, b+d]`. If both bounds stay in the `int` range, the Java sum equals the mathematical sum. Otherwise the result is `⊤`, which contains every wrapped value. |
| `-` | sound | Same argument with `[a−d, b−c]`. |
| `⊥` canonical | correct | Every empty interval is `Interval(0, -1)`, so `==` works on empties. |

The overflow test `test_interval_arithmetic_includes_wrapped_java_results`
checks exactly the property the verdict rules need from (S). Arithmetic never
drops a wrapped Java result.

`Region` is a correct box. Membership is the Cartesian product (property-tested).
An empty parameter interval makes the region empty, and `Region({})` contains
the single empty input, as a no-argument method needs.

### 1.2 Issues

**I1. No division or remainder.** Every corpus pair executes `idiv`, but
`Interval.arithmetic` raises `NotImplementedError` for `Div` and `Rem`. A sound
transfer function must:

- report `divide by zero` iff `0 ∈ divisor`;
- compute the quotient over the divisor *without 0*, split into its negative
  part and its positive part. The divisor `[-1, 1]` with `0` removed is not an
  interval;
- account for `MIN_VALUE / -1 = MIN_VALUE`, which wraps silently in Java.

Rule 1 and Rule 2 depend directly on this error set.

**I2. No comparison or branch refinement.** `Ifz` and `If` appear in all three
pairs. Without refinement (meeting the interval with the branch condition), a
guard like `if (b == 0) return 0` does not remove `0` from `b` on the
fall-through path. `safeDiv` would then wrongly get `{ok, divide by zero}`. Two
limits to keep in mind:

- Intervals cannot represent "≠ 0" inside a range. `[-3, 3]` refined by `≠ 0`
  stays `[-3, 3]`. Only a bound that equals the excluded value can be removed.
  Region refinement is what recovers this precision.
- Refining a stack copy does not refine the local it came from. This is the
  `safeDivByN` dependency problem from the unbounded-analysis lecture. In
  `ratio`, `d = b - a` is a computed value, so refining `d ≠ 0` says nothing
  about `a` or `b`.

**I3. The constructor clips instead of rejecting.** `Interval(MAX+1, MAX+10)`
becomes `⊥`, and `Interval(MIN-5, x)` becomes `[MIN, x]`. This is safe today
only because `arithmetic` checks for overflow *before* it constructs the
result. A future operation (`Mul`, `Negate`, `Div`) that passes unchecked
mathematical bounds to the constructor would silently drop the wrapped values,
and (S) would no longer hold. Recommendation: route every new operation
through the same "out of range ⇒ `⊤`" check. One example to watch:
`Negate([MIN, MIN]) = [MIN, MIN]`, not `[MAX+1, MAX+1]`.

**I4. Overflow gives `⊤`.** This is sound but coarse. A sum that overflows
by one loses the whole interval. It only matters near the `int` limits, which
the current corpus never reaches (C4). Note it in the paper's precision
discussion rather than fixing it now.

**I5. Regions cannot be split yet.** Refinement needs
`split(R, k, parameter) → [R≤k, R>k]` with two guarantees: the parts are
disjoint, and together they cover `R`. The pair-level verdict and certified
coverage (verdict-rules §7) are only meaningful under those guarantees. A
`size(R)` (the product of interval widths) is also needed to report coverage.

**I6. Regions use names, the analyser uses local slots.** `Region` is keyed by
parameter names. The analyser and the JPAMB decompiled bytecode work with
local indices, and names exist only when the code is compiled with
`-parameters`. `Observe.java` does that, `jpamb build` may not. For static
`int` methods, parameter *i* lives in local slot *i*. Fix the mapping in one
place, keyed by index or by an ordered name list taken from the descriptor.

**I7. Not wired into the analyser.** `State`, `initialstate` and `step` in
[static.py](../../solutions/static/src/static.py) still use `SignSet` (lines
6–127). `initialstate` is where locals must be set from region bounds, one
local per parameter interval. The README already says this.

**I8. No widening.** The lattice is bounded by the Java range, so ascending
chains are finite in theory (height ~2³²) but far too long in practice. The
plan is the K-interval widening from the lecture, with
`K = constants of both versions ∪ {MIN_VALUE, MAX_VALUE}`. Termination of
this operator is the TWI proof obligation. It does not block the loop-free
round.

## 2. Corpus and evaluation (`cases/.../Refactorings.java`, `evaluation/`)

### 2.1 What is correct

- **The pairs fit the contract.** All six methods are static, take only `int`
  parameters, return `int`, have no heap writes or calls, and are loop-free.
- **The three intended kinds are present.** `safeDiv` is unchanged,
  `ratio` is a faulty guard removal and `sign` is a return-value-only change.
  Together they exercise Rule 2 (after refinement), Rule 3 (`safeDiv`: UNSAT)
  and Rule 3′ (`sign`: SAT at `x = 0`).
- **The ground truth is independent.** `Observe.java` runs the real JVM with
  `-ea`, matching contract §1. Exceptions map to JPAMB outcome names, and an
  unexpected exception stops the run instead of being guessed. The answer key
  is kept away from the analyser.
- **The `ratio` comment is right.** The original also divides by zero when
  `max(a, b) = 0` and `a ≠ b`. All six such inputs in the domain agree in
  [ratio.csv](../../evaluation/observations/ratio.csv). This makes `ratio` the
  corpus instance of "equal non-singleton outcome sets do not imply
  preservation" (verdict-rules §6).
- **The observed outcome sets match the rules' expectations:**

  | Pair | Original | Edited | Differ |
  |---|---|---|---|
  | `safeDiv` | `{ok}` | `{ok}` | 0 / 49 |
  | `ratio` | `{ok, divide by zero}` | `{ok, divide by zero}` | 1 / 49 |
  | `sign` | `{ok}` | `{ok}` | 1 / 7 |

### 2.2 Issues

**C1. The pairs are not in the JPAMB build.** `target/` has no
`Refactorings.class`, no `target/decompiled/jpamb/cases/Refactorings.json`, and
`target/stats/cases.txt` has no `Refactorings` entry. The analyser cannot load
the pairs through JPAMB's method-loading infrastructure, as the proposal
requires, until someone runs `jpamb build` (it needs Docker) and commits the
output. The course's benchmark freeze is 16 Nov. That date only matters if the
pairs should go upstream.

**C2. Rule 1 is never exercised on its own.** No pair has a region where both
versions throw the same error on every input, except small regions that
`ratio` produces after refinement. A pair whose versions always fail the same
way, for example an `assert` that is restructured, would test Rule 1 directly.
The proposal also says "half the pairs faulty": currently 2 of 3 are.

**C3. Only pair-level checking exists.** `check_expected.py` checks the
pair-level verdict and the list of counterexamples. The regional checks in
contract §5.1 are not implemented yet: preserved regions agree on `R ∩ D`, and
witnesses lie in `R` and replay.

**C4. The domain `[-3, 3]` is small.** It contains the shared constant `0`, so
refinement points are covered, but it never reaches overflow behaviour. Claims
on the rest of the `int` range cannot be refuted (contract §5.1). For `ratio`
this is harmless: `d = b - a` wraps the same way in both versions.

**C5. Return values are compared as strings.** `Observe` records
`String.valueOf(value)`. That is fine for `int`, but it gives `true`/`false` for
`boolean` and `null` for `void`. Contract §2.2 fixes the encoding at 1/0 and
`()`. Map these before boolean or void pairs are added.

**C6. What does "changed" count as?** A Rule 2 `changed` proves a difference on
*every* input of the region. A Rule 3′ `changed` proves one witness. The EST
analysis must decide whether certified coverage counts the whole region in the
first case. My proposal: count Rule 2 regions fully, and count Rule 3′ as the
witness point only, then keep refining the rest of the region.

## 3. Unresolved correctness issues

| ID | Issue | Blocks | Owner (suggested) |
|---|---|---|---|
| I1 | Interval `Div`/`Rem` with divide-by-zero error set and `MIN/-1` | every pair | Krish |
| I2 | Branch refinement for `Ifz`/`If` | every pair | Krish |
| I3 | Constructor clipping is unsound for unchecked bounds | future ops | Krish |
| I5 | `Region.split` with a disjoint-cover guarantee, plus `size` | refinement, coverage | Krish / Cristina |
| I6 | Parameter name ↔ local slot mapping | region initialisation | Krish |
| I7 | Replace `SignSet` with `Interval` in `static.py` | analyser | Krish |
| C1 | Build `Refactorings` into JPAMB `target/` | loading pairs via JPAMB | Cristina |
| C3 | Regional claim checker (contract §5.1) | evaluation | Cristina |
| C6 | Coverage counting for Rule 2 vs Rule 3′ `changed` | EST | Deniz / Cristina |
| Φ | Encode returns with 32-bit bitvectors, divisor ≠ 0 in path conditions | Rule 3 soundness | whoever builds the SMT step |
| I8 | K-widening (needed for loops) | loop round, TWI | Krish (impl.), Deniz (proof) |
| C2, C4, C5, I4 | Corpus coverage and precision notes | paper / later rounds | — |

### Status after PR 2 (2026-11-19)

See [pr2-review.md](pr2-review.md) and [soundness-notes.md](soundness-notes.md).

- **Resolved:** I1, I2, I3 (soundness-notes §1–§6), I5 (`split_region`,
  `region_size`), I7 (`region_analysis.py`), Φ (`symbolic.py` meets §5), C6
  (Rule 2 counts the whole region, Rule 3′ counts the witness only).
- **Partly resolved:**
  - I8: widening exists but goes to the `int` limits, not to `K`.
  - C1: `Refactorings.class` and `Refactorings.json` are built, but the class is
    not yet registered in `Runtime.java`.
  - C3: `test_real_corpus.py` checks every region claim against the JVM
    observations.
- **Still open:** I6 (positional parameter order, see PR 2 review N1), C2, C4,
  C5, I4.
