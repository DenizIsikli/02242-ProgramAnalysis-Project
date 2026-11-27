# Review: Is the Implementation Correct?

This review checks the implementation against
[observation-contract.md](observation-contract.md) and
[verdict-rules.md](verdict-rules.md). It covers the interval domain, the region
analysis, the verdict rules and the Z3 return comparator. The proofs themselves
are in [soundness-notes.md](soundness-notes.md) and in verdict-rules §3–§5.

## 1. Interval operations

[abstractions.py](../../solutions/static/src/abstractions.py) provides `abstract`,
`in`, join, meet, `+ − × / %`, negation, `refine` and `widen`. Each was checked
against the soundness condition `α(op(X, Y)) ⊑ op♯(α(X), α(Y))` over Java `int`s,
including wrapping:

- **Arguments:** see [soundness-notes.md](soundness-notes.md) §1–§7. In short:
  - every bound that could overflow becomes `⊤`;
  - `/` and `%` report `divide by zero` exactly when `0 ∈ Y`, and handle the
    negative and positive parts of `Y` separately;
  - `MIN / −1` and `−MIN` give `⊤`;
  - `refine` keeps every pair that satisfies the branch condition.
- **Property tests:** the Hypothesis tests in `test_interval_ops.py` and
  `test_abstractions.py`.
- **Brute force:** 120 intervals with endpoints at the edge values (`MIN`, `MAX`,
  `0`, `±1` and their neighbours), every operation and comparison, about 3.9
  million checks, no failures.

## 2. Region analysis

[region_analysis.py](../../solutions/static/src/region_analysis.py) has to satisfy
(S): every real outcome and return value of an input in `R` is in the computed
outcome set and return interval.

- **Branch refinement through locals.** The analyser narrows the local that a
  compared value was loaded from. This is sound because the `src` tag is cleared
  on every write to that local (soundness-notes §6).
- **Operand order and branch targets** match the JVM specification (`If` tests
  `v1 cond v2`, and `v1` is the dividend).
- **Unsupported code never gets a verdict.** It returns every outcome and is
  reported `unknown` before Rule 1 can fire.
- **Loops.** `*` is added for every back edge except a counting loop that provably
  exits (soundness-notes §7).

## 3. Verdict rules and Z3 comparator

- **The rules** in [region_verdict.py](../../solutions/static/src/region_verdict.py)
  match verdict-rules §2. Rule 0 runs first. Equal outcome sets with two
  outcomes never give `preserved`. A solver `unknown` or timeout never gives
  `preserved`.
- **Rule 2b** was added during implementation. I approved it and proved it
  (verdict-rules §4b), and added a guard against an empty return interval.
- **[symbolic.py](../../solutions/static/src/symbolic.py)** meets all five
  conditions of verdict-rules §5:
  1. 32-bit bitvectors;
  2. `divisor ≠ 0` on every division;
  3. complete paths, with loops and budget overruns giving `unknown` and an
     explicit check that the `ok` paths cover `R`;
  4. the same input symbols for both versions;
  5. concrete replay before `changed`.

  The `observations` mode used by the Z3-only baseline keeps the same guarantees.

## 4. Bug found: try/catch

`jvm.Method` drops the exception table, so neither analyser saw handlers. A caught
division was then analysed as escaping. On real `javac` output, the pair
`try { return a / b; } catch (ArithmeticException e) { return -1; }` and
`if (b == 0) return -1; return a / b;` behave identically, but the tool reported
it as **changed**.

The contract (§4) excludes try/catch, so the fix is to reject it:
`has_exception_handlers` marks such methods unsupported in both analysers. The
regression test is `test_exception_handlers_make_the_pair_unsupported`. The
`javap` adapter in `corpus_bytecode.py` also refuses exception tables.

## 5. End-to-end check

- [test_real_corpus.py](../../solutions/static/tests/test_real_corpus.py) runs
  the checker on the real corpus bytecode and checks **every region claim**
  against the real-JVM observations, as contract §5.1 requires:
  - `preserved` regions contain only agreeing inputs;
  - whole-region `changed` regions contain only differing inputs;
  - every witness really differs.

  It also checks the replay interpreter against every JVM observation.
- All 184 tests pass.
- The ablation (20 pairs, 2 domains, 4 configurations, 160 runs) gives no wrong
  verdict.

## 6. Known limitations

None of these breaks soundness; they cost precision or completeness.

- Widening jumps to the `int` limits, not to the program's constants.
- Intervals cannot relate the two versions, so non-constant returns need the
  solver, and loop-dependent returns stay `unknown`.
- `void` pairs are never decided by Rules 2b and 3.
- Region bounds are matched to parameters by position.
- Ground truth is exhaustive only on `[-3,3]^k`. Larger domains are checked by
  sampling and witness replay.
