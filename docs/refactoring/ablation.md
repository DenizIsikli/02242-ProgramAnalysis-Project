# Ablation and baselines

Run: `PYTHONPATH=solutions/static/src:src python evaluation/ablation.py [--budget N] [--csv out.csv]`
(needs `z3-solver`; uses the committed `target/decompiled` files).

Four methods on every pair (the 3 corpus pairs plus 5 `Simple` pairs), on a small domain
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

## First results (budget 1000, 16 rows)

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
