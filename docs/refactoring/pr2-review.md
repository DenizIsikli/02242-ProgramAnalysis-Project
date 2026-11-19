# Review of PR 2 (`feature/krish-analysis`, commit `ff8e15b`)

Reviewer: Deniz. This follows the checklist in
[region-analysis-review.md](region-analysis-review.md) §5, and checks the code
against [observation-contract.md](observation-contract.md) and
[verdict-rules.md](verdict-rules.md). The fixes described here are on
`feature/correctness-contract`, which has PR 2 merged into it.

**Summary.** The analysis is sound on everything the review could throw at it,
and it decides all three corpus pairs exactly as the real JVM does. I found one
real soundness hole: try/catch. It is fixed, with a regression test.

## 1. Checklist

- [x] **Run the tests.** 133 passed on `ff8e15b`. After the fixes below: 140.
  (The checklist says 118 in §5 and 133 in §6. 133 is right.)
- [x] **Interval `Div`/`Rem`/`refine` and random Java counterexamples.** The
  Hypothesis tests pass. A brute-force check at the edge values (`MIN`, `MAX`,
  `±1`, `0` and their neighbours: 120 intervals, about 3.9M checks) found no
  unsound result for `Add Sub Mul Div Rem Neg`, `refine` (all six conditions, both
  polarities) or `widen`. The arguments are in
  [soundness-notes.md](soundness-notes.md).
- [x] **`_step` against `OPCODES.md`.**
  - `If` pops `v2` (top) then `v1`, and tests `v1 cond v2`.
  - `Binary` uses `v1` as the dividend.
  - Branch targets use `pc % target`.
  - All of this is correct.
- [x] **No `preserved`/`changed` while `supported` is False.** An unsupported
  result carries all outcomes, and `region_verdict` returns `unknown` for it
  before Rule 1. Confirmed.
- [x] **`symbolic.py` against verdict-rules §5.** All five conditions hold:
  1. `z3.BitVec(…, 32)` everywhere. `/` and `SRem` are `bvsdiv`/`bvsrem`.
  2. Every `Div`/`Rem` adds `y ≠ 0` to the path condition, and infeasible
     continuations are dropped.
  3. Backward jumps raise "unsupported" (so `unknown`), and a path budget
     overrun does the same. UNSAT is trusted only after z3 confirms that the
     `ok` paths cover the region. A solver `unknown`/timeout in the coverage or
     mismatch query gives `unknown`. A feasibility `unknown` keeps the path,
     which is safe.
  4. Both versions use the same symbols `x0 … xn`.
  5. A model counts as `differs` only after `concrete_run` replays it with a
     different observation. Otherwise the answer is `unknown`.

  **Solver unknown or timeout never counts as preserved.**
- [x] **4.1: real `Refactorings.json` and `check_pairs.py`.** I built
  `Refactorings.class` and `target/decompiled/jpamb/cases/Refactorings.json`
  with the course image (`ghcr.io/kalhauge/jvm2json:jdk-latest`, `javac -g`
  plus `jvm2json -s`, as in `jpamb build`). `check_pairs.py` has no `WRONG`
  row:

  | Pair | Expected | Intervals only | With Z3 | Regions (without → with Z3) |
  |---|---|---|---|---|
  | `safeDiv` | preserved | preserved 49/49 | preserved 49/49 | 36 → 9 |
  | `ratio` | changed | changed, 1 differs at `(0,0)` | changed, 1 differs at `(0,0)` | 37 → 7 |
  | `sign` | changed | changed, 1 differs at `(0,)` | changed, 1 differs at `(0,)` | 4 → 4 |

  Every *region* claim was also checked against the real-JVM CSVs
  (contract §5.1), and none is refuted. This is now a test:
  [test_real_corpus.py](../../solutions/static/tests/test_real_corpus.py).
- [x] **Rule 2b.** Approved. The proof is in verdict-rules §4b. It needs one
  guard (F2).

## 2. Findings

**F1. try/catch is ignored, which is unsound (fixed).** `jvm.Method` drops the
exception table, so neither `region_analysis` nor `symbolic` sees handlers. A
caught exception is then analysed as escaping.

Reproduced with real `javac` + `jvm2json` output. Compare
`try { return a / b; } catch (ArithmeticException e) { return -1; }` with
`if (b == 0) return -1; return a / b;`, which behave identically. The analysis
gave `{divide by zero}` for `b = 0` and reported the pair as **changed**, with
witness `(−3, 0)`.

Contract §4 excludes try/catch, so the fix is to reject it:

- `has_exception_handlers` reads `code.exceptions` from the decompiled JSON;
- `analyse_outcomes` returns "unsupported" and `symbolic_paths` raises
  `SymUnsupported` for such methods;
- the regression test is `test_exception_handlers_make_the_pair_unsupported`.

No current benchmark method has a handler, which is why the existing tests
passed.

**F2. Rule 2b on an empty return interval (fixed, hardening).** With outcome
`{ok}` and an empty return interval, the "disjoint returns" test would fire
vacuously. This is the same reasoning as Rule 0. javac output cannot produce
this case, but the guard costs one condition.

## 3. Notes (no change needed now)

- **N1. Region ↔ parameter order (review I6).** `initial_state` and
  `make_return_checker` pair `region.bounds.values()` with parameters by
  position. That is correct as long as the `domain` keys in `expected.json` are
  listed in parameter order, as they are now.
- **N2. `void` pairs are never decided by Rules 2b/3.** `symbolic` rejects `void`
  returns. Under the contract, two `void` versions with outcome `{ok}` always agree
  (`v = ()`), so a later rule could decide them. This affects precision only.
- **N3. `refine_local` replaces instead of meeting.** This is sound (see
  soundness-notes §6) but slightly imprecise.
- **N4. A split Rule-3′ region's witness** counts in `changed_inputs` only if a
  child region decides that point again. The overall verdict is still `changed`.
  This only matters for coverage numbers.
- **N5. Widening goes to the `int` limits, not the `K` constants** the proposal
  planned. This costs precision in loops, not soundness.
- **N6.** `uv.lock` is not regenerated for `z3-solver`, as the checklist already
  says.
- **N7.** The README paragraph "This foundation is not yet integrated into the
  interpreter …" is out of date since PR 2.

## 4. Still open (other owners)

- Register `Refactorings` in `cases/jpamb/Runtime.java`, then run `jpamb build`
  so that `target/stats/cases.txt` lists it too (Cristina, C1). The class and
  JSON files are committed, so the analyser and tests already work without it.
- A regional checker in the harness (C3) is partly covered by
  `test_real_corpus.py`. Cristina's pair-level harness can reuse its comparison.
