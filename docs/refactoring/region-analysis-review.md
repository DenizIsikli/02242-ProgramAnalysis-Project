# Region analysis (Krish's M2+M3 part): what was built and how to check it

Branch `feature/krish-analysis` (off `main` @28fa721). Written 2026-11-19 for a reviewer: please try to break it.

## 1. What changed

| File | Change |
|---|---|
| `solutions/static/src/abstractions.py` | `Interval.arithmetic` now supports Add, Sub, **Mul, Div, Rem**; new `Interval.neg()` and `Interval.refine(other, cond, holds)` (branch refinement). Helpers `_trunc_div`, `_checked`, `_NEGATED`. Fixes review issues I1, I2, and routes every op through the "possible overflow => top" check (I3). |
| `solutions/static/src/region_analysis.py` (new) | `analyse_outcomes(bc, methodid, region) -> AnalysisResult(outcomes, returns, supported)`: forward worklist interval interpreter, loop-free/call-free `int` methods. Branch refinement also narrows the *local* a stack value was loaded from (tracked by `Val.src`). Anything unsupported => all outcomes, `supported=False`. |
| `solutions/static/src/region_verdict.py` (new) | `region_verdict` (rules 0,1,2,2b,3,3',4), `split_region`, `check_pair` (refinement + budget), `PairVerdict` with coverage counts. Pluggable `return_check` hook for the Z3 comparator (Deniz). |
| `solutions/static/src/symbolic.py` (new) | Z3 return comparator (rules 3/3'): 32-bit bitvector symbolic execution of both methods, `make_return_checker(bc, a, b)` plugs into `check_pair`. Includes a Z3-independent concrete interpreter used to replay witnesses. Guard: ok-paths must cover the region, else `unknown`. Needs `z3-solver` (added to `solutions/static/pyproject.toml`; `uv.lock` not regenerated). Tests: `test_symbolic.py`. |
| `solutions/static/src/check_pairs.py` (new) | Runs `check_pair` over `evaluation/expected/expected.json` pairs and flags verdicts contradicting the key (`WRONG`). Analyser never reads the key. |
| `solutions/static/tests/test_interval_ops.py` (new) | Hypothesis soundness tests of every op against hand-written Java `int` semantics. |
| `solutions/static/tests/test_region_analysis.py`, `conftest.py` (new) | Soundness of outcome analysis on every concrete input of the corpus methods (hand-assembled bytecode), rules, splitting, pair verdicts. |
| `solutions/static/tests/test_real_bytecode.py` (new) | Same pipeline on real jvm2json output of `jpamb.cases.Simple`; reproduces 0/49, 1/7, 47/49. |
| `solutions/static/tests/test_abstractions.py` | One test edited: "unsupported arithmetic" used `Div`, which is now supported; it now uses a bogus operator. |

## 2. How to run

```sh
cd FinalProjectSrc/02242-ProgramAnalysis-Project
PYTHONPATH=solutions/static/src:src ../../.jpamb-eval/bin/python -m pytest solutions/static/tests -q
# expected: 133 passed (also: uv run --with z3-solver pytest -o "pythonpath=solutions/static/src src" solutions/static/tests) (needs z3-solver installed)
```
(`.jpamb-eval` is the Python env at the outer repo root; `src` must come first on PYTHONPATH so the
team repo's jpamb 0.9.0 is used.)

The corpus run needs `target/decompiled/jpamb/cases/Refactorings.json`, which does **not exist yet**
(see 4.1): `PYTHONPATH=solutions/static/src:src python solutions/static/src/check_pairs.py`.

## 2b. Loops (added later the same day)

- `Interval.widen` (old, new): a bound that grows jumps to the int limit. `region_analysis.py` widens
  the state whenever a *backward* edge is followed, so the worklist terminates.
- Divergence: `"*"` is added to the outcome set for every reachable backward edge **unless**
  `_proven_terminating` matches a tiny syntactic pattern (javac's counting loop: `load i; load n/push c;
  if_icmpge EXIT` or `load i; ifle EXIT`, straight-line body, exactly one `iinc i +/-1`, `goto head`,
  bound not written in the body). Step +/-1 reaches the bound before wrapping. Everything else
  (do-while, step 2, branches in the body, ...) keeps `"*"`, which is always sound.
- Z3 (`symbolic.py`) still rejects loops => `unknown`. So loop pairs are decided only by Rules 1/2/2b.
- Real benchmark: `Loops.forever/neverAsserts/neverDivides` come out `{"*"}`, as they should.
- `test_soundness_on_benchmark.py` checks every int-only benchmark method (region [-3,3]^k) against
  concrete execution: 25 methods checked, 15 skipped as unsupported.
- To attack: `_proven_terminating` (is each accepted pattern really terminating for ALL start values,
  including `n = MAX_VALUE`? the `Ge`/step +1 and `Le`/step -1 forms were chosen for that reason; `Gt`/`Lt`
  forms are deliberately rejected), and widening without narrowing (precision only, not soundness).

## 3. Claims to verify (each has a test; try to find a counterexample anyway)

1. **Interval ops are sound w.r.t. Java `int`**: result contains every wrapped Java result; error set
   contains `divide by zero` exactly when `0 in divisor` (`test_interval_ops.py`).
   Things worth attacking: `MIN / -1`, `Neg(MIN)`, `Rem` with mixed-sign dividend, divisor intervals
   straddling 0 (split into negative and positive parts), `Mul` near `MAX`.
2. **`refine` is sound**: every `(x, y)` satisfying (or, with `holds=False`, violating) the condition
   stays inside the refined intervals. Intervals cannot express `!= 0` inside a range, so `Ne` only
   trims an endpoint.
3. **(S) for the outcome analysis**: for each input of a region, the concrete outcome is in
   `outcomes` and the return value in `returns` (`test_analysis_is_sound_on_every_input`).
4. **Rules**: equal two-outcome sets never give `preserved` (`test_equal_sets_with_two_outcomes_are_not_enough`);
   solver `unknown` never gives `preserved`; empty regions are discarded; children of `split_region` are
   disjoint and cover the parent (`test_split_is_disjoint_cover`); counts always sum to the domain size.
5. **Real bytecode**: `Simple` pairs give 0/49, 1/7, 47/49 (`test_real_bytecode.py`).

## 4. Known gaps and things NOT verified

1. **`Refactorings.json` is missing.** Mitigation: I compared the hand-assembled listings in `conftest.py` with `javap -c` of the real `Refactorings.class` (JDK 21): same opcodes and branch structure (javap byte offsets map to instruction indices). Only the JSON encoding is unchecked, and that path is exercised by the real `Simple.json` tests. `docker pull ghcr.io/kalhauge/jvm2json:jdk-latest` hung here, so
   the corpus was only tested with *hand-assembled* bytecode (`conftest.py`) that I wrote to mirror javac.
   It could differ from real jvm2json output. **First thing to do on a machine with Docker access:**
   pull the image, run `jpamb build` (or decompile `Refactorings.class` only), commit
   `target/decompiled/jpamb/cases/Refactorings.json`, then run `check_pairs.py`. Also note
   `Refactorings` is still not registered in `cases/jpamb/Runtime.java`.
2. **Rule 2b is my extension**, not in `docs/refactoring/verdict-rules.md`: both `{ok}` and the return
   intervals are disjoint (=> every input differs) or both are the same singleton (=> preserved).
   Argument: (S) applied to return values. Needs Deniz's review/proof. Without it the test
   `test_pair_sign_without_solver_never_claims_preserved` and the 0/49 identity result need the solver.
3. **Z3 comparator now exists** (`symbolic.py`), but was not written by Deniz (the planned owner): it needs Deniz's review against verdict-rules.md §5 (conditions 1-5). With `return_check=None` non-constant both-`ok` regions stay `unknown`. Hook contract: `(Region) -> ReturnCheck("equal" | "differs", witness | "unknown")`;
   a witness must already be replayed concretely.
4. **Fragment only**: static, call-free (loops: widening + simple termination pattern, no Z3), `int`/`boolean` params. Backward jumps, arrays,
   invokes, other opcodes => `unsupported` (`unknown` verdict, never preserved/changed).
   Assertions assumed enabled (`$assertionsDisabled` = 0), as in the course skeleton; a constructed
   `AssertionError` is treated as thrown.
5. `Cast`, `Dup2`, long/float/double are unsupported (explicitly, not silently).
6. Region splitting uses constants from `Push` opcodes plus 0; `max_regions` (default 200) bounds work.
   A rule-3' witness region is kept as a witness *and* refined so the rest can still be certified.
7. `test_pair_safediv_preserved` is deliberately weak (it only forbids a wrong `changed`) because
   deciding `safeDiv` as preserved needs the solver.
8. The ratio pair with interval-only analysis certifies by Rule 2 on point regions; this relies on the
   split at constant 0 producing point regions (works for the corpus; bisection fallback otherwise).

## 5. Suggested reviewer checklist

- [ ] Run the tests; confirm 118 pass.
- [ ] Read `Interval._div_part`, `_rem_part`, `refine` and try random Java-semantics counterexamples beyond Hypothesis' defaults.
- [ ] Check `_step` against `OPCODES.md` for operand order (`If`: `v1 cond v2` with `v2` on top) and branch targets (`pc % target`).
- [ ] Confirm that no code path returns `preserved`/`changed` while `supported` is False.
- [ ] Read `symbolic.py` against verdict-rules.md §5: BitVec (not Int), `y != 0` on division paths, same input symbols, replay before `differs`, UNSAT only trusted when ok-paths cover the region.
- [ ] Do 4.1 (real `Refactorings.json`) and run `check_pairs.py`; no row may say `WRONG`.
- [ ] Decide on Rule 2b with Deniz.

## 6. Pre-push checks run (2026-11-19)

- `ruff check .` and `ruff format --check .`: clean.
- Clean-env CI-style run (`uv run --with z3-solver pytest ... solutions/static/tests`): 133 passed. `.github/workflows/test.yml` updated to run all static tests with z3 (it only ran `test_abstractions.py` before).
- Repo core tests (`uv run pytest`): 126 passed, 4 skipped; `tests/test_jpamb_interpret.py::test_steps_from_sexpr` fails with a Hypothesis `FailedHealthCheck` on **clean `main` too** (pre-existing, unrelated).
