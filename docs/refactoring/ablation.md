# Ablation and baselines

Run: `PYTHONPATH=solutions/static/src:src python evaluation/ablation.py [--budget N] [--csv out.csv]`
(needs `z3-solver`; uses the committed `target/decompiled` files).

Four methods on every pair (the 10 corpus pairs, 5 `Simple` pairs and 5 loop / many-path pairs from `cases/jpamb/cases/EvalPairs.java`, which is evaluation-only and not part of the shared corpus; `--timeout-ms` sets the solver timeout), on a small domain
`[-3,3]^k` (ground truth: every input executed) and a large one `[-1000,1000]^k`:

| mode | what it is |
|---|---|
| `gate` | interval analysis + refinement only, no solver |
| `hybrid` | the proposed method: gate, then Z3 on regions where both versions always return |
| `z3only` | one SMT query over the whole domain, gate disabled (`make_return_checker(..., observations=True)` encodes error paths too, so outcome class and value are compared together) |
| `random` | differential testing with `--budget` random inputs (never claims `preserved`) |

A verdict that contradicts the truth is printed as **WRONG** (`preserved` although a difference
exists, `changed` without a real difference); on the large domain a `preserved` verdict is
checked by sampling 2000 inputs. `unknown` is never wrong. `check_pair` and the baselines report
`PairStats` (regions analysed, SMT queries, executions, seconds).

## Results on the first 16 rows (budget 1000), loop-free pairs only

| mode | decided | wrong | mean certified coverage |
|---|---|---|---|
| gate | 14/16 | 0 | 85% |
| hybrid | 16/16 | 0 | 99% |
| z3only | 16/16 | 0 | 40% |
| random | 9/16 | 0 | 3% |

## How to read this honestly

- All methods are correct (0 wrong). Differential testing finds large-ish differences but never
  proves preservation and misses the single-point difference of `ratio` on the large domain.
- On these tiny loop-free methods **Z3 alone decides everything and is fastest.** The hybrid's
  measurable advantage here is *certified coverage*: after a difference is found it still
  certifies the rest of the domain (99% vs 40%, because `z3only` certifies a single witness for a
  `changed` verdict), and its regional verdicts explain where the versions differ.
- The abstract gate should matter when Z3 alone cannot decide: loops (the symbolic executor
  rejects them, the interval analysis widens), many paths (path budget), or solver timeouts.
  The current pairs do not stress this. To support the NAN claim the evaluation needs pairs with
  loops and with path explosion, and runs with a tight solver timeout.
- Region splitting is weak on `justAdd~justMulitply` over `[-1000,1000]^2` (91% after the
  201-region budget): the differing inputs are almost everywhere, but only constant-based splits
  are used.

## Loop and many-path pairs (26 rows in total, 0 wrong)

| mode | decided | wrong | mean certified coverage |
|---|---|---|---|
| gate | 22/26 | 0 | 85% |
| hybrid | 24/26 | 0 | 94% |
| z3only | 20/26 | 0 | 36% |
| random | 12/26 | 0 | 2% |

- **Loops are where the gate earns its place.** The symbolic executor rejects loops, so `z3only`
  returns `unknown` on all three loop pairs. Intervals still decide `loopThenZero` (both always
  divide by zero, preserved, 100%) and find the `d == 0` difference of `loopDiv~loopDiv_guarded`
  with a witness, certifying 76% (small domain) / 50% (large) of the inputs.
- **Honest limits.** `loopDiv~loopDiv_rewritten` (identical behaviour) stays `unknown` for every
  method except that gate/hybrid certify the `d == 0` slice: both versions return a loop-dependent
  value and nothing proves them equal. Loops are outcome-only in the abstract analysis and
  loop-free in Z3.
- **Path explosion did not show up.** `ladder` has 12 sequential ifs, but the symbolic executor
  prunes infeasible paths, so Z3 decides all `ladder` pairs in one query. The gate decides them too
  (preserved without any SMT call, via rule 2b on regions split at the constants) and is
  3-5x faster than Z3 on these pairs; hybrid is slowest on `ladder~ladder_changed` over the large
  domain (13 SMT calls, 1.5 s) because it keeps refining after the witness. Do not claim a path
  explosion win from this pair.
- Random testing needs ~1000 runs to say nothing on the `equal` pairs and found the `d == 0`
  difference only after 306 runs on the large domain.

## Full run with the 10-pair corpus (40 rows, 0 wrong)

| mode | decided | wrong | mean certified coverage |
|---|---|---|---|
| gate | 32/40 | 0 | 79% |
| hybrid | 38/40 | 0 | 96% |
| z3only | 34/40 | 0 | 45% |
| random | 18/40 | 0 | 2% |

This is the table to cite: hybrid decides the most pairs and certifies the most of each domain;
Z3 alone is faster on loop-free pairs but cannot handle loops. Reproduce with
`PYTHONPATH=solutions/static/src:src python evaluation/ablation.py`.

## Variance: seeds and repeated timings

`PYTHONPATH=solutions/static/src:src python evaluation/seed_stats.py [--seeds 20] [--repeats 5]`
runs seeded random testing 20 times on every pair that really differs, and repeats every hybrid
and Z3-only timing five times. Measured on an Intel Core i5-1038NG7 (16 GB, macOS 26.5), Python
3.13.5, Z3 5.4.1.

- **Detection (19 differing pair/domain runs, 380 seeded runs):** 285 found a difference (75%).
  On the small domain 180/180. On the large domain 105/200 (53%): `ratio` 0/20 (one differing
  input out of 4,004,001), `sign`, `reciprocal`, both `checkBeforeDivideByN` 6/20, `loopDiv_guarded`
  9/20, `belowTwo` 12/20, `absVal`, `justAdd~justMulitply`, `ladder_changed` 20/20.
- **Timings are stable:** total over all 40 runs, median of five repeats: hybrid 8.85 s
  [8.33, 10.19], Z3 only 2.42 s [2.28, 2.64].
- **Z3 only has the lower median on 26 of 40 runs** (four of them loop runs where it gives up at
  once), the hybrid on 11, 3 ties. The hybrid's worst case is `justAdd~justMulitply` on the large
  domain: 3.7 s against 0.07 s.
