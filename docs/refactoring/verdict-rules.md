# Verdict Rules and Their Correctness

This document states the rules that turn two independent analyses into a
verdict for a region, and argues that each verdict is correct. The terms
(*observation*, *agree*, *supported*) are defined in
[observation-contract.md](observation-contract.md).

## 1. Notation and assumptions

Fix a supported pair `A = m`, `B = m_edited` and a non-empty region `R`.

- `out_P(x)` is the outcome class of `P` on `x`, and `ret_P(x)` is its return
  value when `out_P(x) = ok`. So `obs_P(x) = (out_P(x), ret_P(x))`.
- `Â(R)` and `B̂(R)` are the outcome sets the interval analysis computes for `A`
  and `B` on `R`. Each version is analysed on its own.

We rely on three assumptions.

**(S) Soundness of the outcome analysis.** For every `x ∈ R`:
`out_A(x) ∈ Â(R)` and `out_B(x) ∈ B̂(R)`.
The analysis may over-approximate (report outcomes that never happen) but never
miss one. Proving (S) for the interval abstraction is the TAB contribution.
For `*` it needs an unbounded analysis (a fixpoint, with widening), because a
depth-bounded analysis that silently drops long traces breaks (S).

**(D) Determinism.** `obs_P` is a function (contract §2.3).

**(E) Error observations carry no value.** If `out_P(x) ≠ ok`, then
`obs_P(x) = (out_P(x), ⊥)` (contract §2.1).

From (S) and `R ≠ ∅` it follows that `Â(R) ≠ ∅` and `B̂(R) ≠ ∅`. If the analysis
ever returns an empty set for a non-empty region, (S) is broken. The checker must
then answer `unknown`, never `changed` (see Rule 2).

## 2. The rules

Apply the rules in this order. The first that matches decides.

| # | Condition | Verdict | Witness |
|---|---|---|---|
| 0 | `Â(R) = ∅` or `B̂(R) = ∅` | `unknown` (analysis failure) | — |
| 1 | `Â(R) = B̂(R) = {e}`, `e ≠ ok` | `preserved` | — |
| 2 | `Â(R) ∩ B̂(R) = ∅` | `changed` | any `x ∈ R` |
| 3 | `Â(R) = B̂(R) = {ok}` and `Φ(R)` is UNSAT | `preserved` | — |
| 3′ | `Â(R) = B̂(R) = {ok}` and `Φ(R)` has model `w` that replays | `changed` | `w` |
| 4 | otherwise (including solver `unknown`/timeout, or a model that does not replay) | `unknown`, refine `R` | — |

`Φ(R)` is the return-comparison query from §5.

## 3. Rule 1: matching singleton errors

**Claim.** If `Â(R) = B̂(R) = {e}` with `e ≠ ok`, then `A` and `B` agree on every
`x ∈ R`.

**Argument.** Take any `x ∈ R`. By (S), `out_A(x) ∈ {e}`, so `out_A(x) = e`.
Likewise `out_B(x) = e`. Since `e ≠ ok`, (E) gives
`obs_A(x) = (e, ⊥) = obs_B(x)`. Since `x` was arbitrary, the versions agree on
all of `R`. ∎

**Remarks.**

- The argument never inspects the return value. That is why the error case
  needs no solver.
- `e = *` is included: both versions diverge on every input of `R`. This is only
  as trustworthy as (S) is for `*` (see §1).
- The rule needs the sets to be equal *and* singletons. §6 shows that equal
  non-singleton sets are not enough.

## 4. Rule 2: disjoint outcome sets

**Claim.** If `Â(R) ∩ B̂(R) = ∅`, then `A` and `B` disagree on *every* `x ∈ R`.
In particular, any point of `R` is a witness.

**Argument.** Take any `x ∈ R`. By (S), `out_A(x) ∈ Â(R)` and
`out_B(x) ∈ B̂(R)`. The two sets are disjoint, so `out_A(x) ≠ out_B(x)`.
Observations with different outcome classes are different. ∎

**Remarks.**

- This rule is stronger than `changed` needs: it proves a change on every input,
  not just one. If the evaluation counts *decided inputs*, it can count all of
  `R` as decided. A `changed` verdict from Rule 3′ only decides the witness
  point (see review issue C6).
- Rule 0 must run first. With `Â(R) = ∅`, Rule 2 would fire vacuously and
  report a change backed by nothing.
- A convenient witness is the lower corner `(min R1, …, min Rn)`. The harness
  replays it on the JVM. A failed replay means (S) is broken, not that the rule
  is wrong.

## 5. Rule 3: matching `{ok}` needs a return comparison

**Why outcomes are not enough.** If `Â(R) = B̂(R) = {ok}`, then by (S) both
versions return normally on every `x ∈ R`. So they agree on `x` iff
`ret_A(x) = ret_B(x)`, and the outcome analysis says nothing about return
values. The corpus has a direct instance. `sign` and `sign_edited` both have
outcome set `{ok}` on every region, yet at `x = 0` the original returns `0` and
the edited version returns `-1`
([sign.csv](../../evaluation/observations/sign.csv)). Rule 1 cannot be extended
to `{ok}`.

The interval analysis cannot close this gap either. It abstracts each version
on its own, so it can show that both returns lie in `[-1, 1]` but not that they
are *equal* for each input. Equality is a relation between the two executions,
and that relation is what the solver adds.

**The query.** Symbolically execute each version on `R`. Since the region has
outcome set `{ok}`, the feasible paths of `P` within `R` all end in a return.
Write them as `(π_P,i, r_P,i)`: a path condition and a return expression, both
over the same input symbols `x`. Then

```
Φ(R) = x ∈ R
     ∧ (∨_i (π_A,i ∧ ret_A = r_A,i))
     ∧ (∨_j (π_B,j ∧ ret_B = r_B,j))
     ∧ ret_A ≠ ret_B
```

**Claim (3).** If the path enumeration is complete for `R` and `Φ(R)` is UNSAT,
then `A` and `B` agree on every `x ∈ R`.

**Argument.** Suppose they disagree on some `x ∈ R`. Both outcomes are `ok`, so
`ret_A(x) ≠ ret_B(x)`. Execution is deterministic and the enumeration is
complete, so `x` satisfies exactly one `π_A,i`, and `r_A,i(x) = ret_A(x)`.
Likewise for `B` with some `j`. Then `x` with `ret_A = r_A,i(x)` and
`ret_B = r_B,j(x)` satisfies `Φ(R)`, which contradicts UNSAT. ∎

**Claim (3′).** If `w` is a model of `Φ(R)` and replaying `w` on both versions
gives different observations, the region has changed.

**Argument.** Immediate: the replay is a concrete disagreement inside `R`. ∎

**Conditions that Claim (3) depends on.** All of them must hold in the
implementation:

1. **Machine integers.** Use 32-bit bitvectors (`z3.BitVec(…, 32)`), not
   `z3.Int`. `Int` is unbounded and floors division. With `Int`, the constraints
   `x > 0 ∧ x + 1 < 0` are UNSAT, but Java has `x = 2147483647`. And `Int`
   computes `(-7)/2 = -4`, where Java gives `-3`. SMT-LIB `bvsdiv`/`bvsrem` match
   Java's `idiv`/`irem`, including `MIN_VALUE / -1 = MIN_VALUE`. We checked this
   with z3.
2. **Division by zero in the encoding.** SMT-LIB defines `x bvsdiv 0`, where Java
   throws. Every division on an `ok` path must therefore carry its
   "divisor ≠ 0" condition in `π`. Otherwise a model could pass through a
   division that would really throw.
3. **Completeness.** For loop-free methods the path set is finite. Enumerating
   it with an unsatisfiable-prefix check is complete. With loops, an
   enumeration cut off at depth *k* is not complete. A depth-bounded UNSAT must
   then be reported as `unknown`, not `preserved`.
4. **Same input symbols.** Both versions are encoded over the *same* symbols
   `x`. That shared input is the only place the two executions are correlated.
5. **Replay before reporting 3′.** A model is accepted only after concrete
   replay. That catches encoding bugs in the `changed` direction. In the
   `preserved` direction an encoding bug cannot be caught this way, which is
   why conditions 1–3 matter.

## 6. Why the singleton condition is needed

The proposal says that two versions can *exchange outcomes between inputs* and
still have equal outcome sets. A minimal pair:

```java
static int a(int x) { if (x > 0) return 0; return 1 / 0; }   // ok on x>0, dbz otherwise
static int b(int x) { if (x > 0) return 1 / 0; return 0; }   // dbz on x>0, ok otherwise
```

On `R = [-1, 1]` even a perfectly precise analysis gives
`Â(R) = B̂(R) = {ok, divide by zero}`, yet the versions disagree on *every*
input. Equal sets therefore prove nothing once they contain two outcomes.

The corpus has the same effect without any swapping. On the declared domain
`[-3, 3]²`, `ratio` and `ratio_edited` both have the observed outcome set
`{ok, divide by zero}` and agree on 48 of the 49 inputs. They differ only at
`(0, 0)`, where the original returns `0` and the edited version divides by zero
([ratio.csv](../../evaluation/observations/ratio.csv)). A rule that accepted
equal sets would wrongly report `preserved`. Under our rules the full domain
is `unknown`. Refinement then splits at the constants the two versions share,
for example `0`. Once `(0, 0)` is a region of its own, Rule 2 decides it as
`changed` (`{ok}` against `{divide by zero}`).

## 7. Pair-level verdict

From the region verdicts `{(R_k, v_k)}`:

- `changed` if some `v_k = changed`, with that region's witness;
- `preserved` if the regions cover the whole input space (every input of the
  parameter types) and every `v_k = preserved`;
- `unknown` otherwise. The fraction of inputs in `preserved` or Rule-2 `changed`
  regions is the *certified coverage*.

Regions produced by refinement must be pairwise disjoint and together cover the
region they split. Otherwise coverage double-counts or misses inputs (review
issue I5).
