# Soundness Notes: Interval Operations Added in PR 2

These notes argue that the operations Krish added in
[abstractions.py](../../solutions/static/src/abstractions.py) and
[region_analysis.py](../../solutions/static/src/region_analysis.py) are sound.
They close review issues I1–I3 ([review.md](review.md)) and are the groundwork
for the TAB proof.

**Soundness condition.** It is the one from the lecture, over Java `int`s
(32-bit, wrapping). For an operation `op` with abstract version `op♯`, for all
`X, Y` and every `x ∈ γ(X)`, `y ∈ γ(Y)` on which `op` does not throw:

```
op(x, y) ∈ γ(op♯(X, Y))
```

If `op` can throw on some such pair, the error set of `op♯` must contain the
matching outcome. Below, `X = [a, b]` and `Y = [c, d]` are non-empty, and
`MIN`/`MAX` are the `int` limits.

**Evidence besides the arguments.**

- The Hypothesis tests in `test_interval_ops.py`.
- A brute-force check run during review. All 120 intervals with endpoints in
  `{MIN, MIN+1, MIN+2, −7, −3, −2, −1, 0, 1, 2, 3, 7, MAX−2, MAX−1, MAX}` were
  paired with each other. Each pair was tested on its endpoints, edge values
  and random members, for every operation and every comparison. That is about
  3.9 million checks, with no failures.

## 1. Overflow rule (I3: resolved)

`_checked(lo, hi)` returns `⊤` whenever a mathematical bound leaves the `int`
range, and the exact interval otherwise.

**Why it is sound.** If both mathematical bounds are in range, then every
mathematical result is in range. For results in range, the Java result equals
the mathematical one. Otherwise `⊤` contains every `int`, wrapped results
included.

The risk named in I3 was the constructor's clipping, which silently drops
wrapped values. `Add`, `Sub`, `Mul` and `Neg` all go through `_checked`. `Div`
and `Rem` produce in-range bounds by construction (§3, §4), and `MIN / −1` is
handled explicitly. So no operation passes unchecked bounds to the constructor.
In `refine` the clipping is *wanted*: a bound like `d − 1 < MIN` means "no
`int` is that small", and an empty result is correct there. **I3 is resolved.**

## 2. `Mul`

**Claim.** `x·y ∈ γ(_checked(min P, max P))` with `P = {ac, ad, bc, bd}`.

**Argument.** Fix `y`. Then `x·y` is linear in `x`, so over `[a, b]` its extremes
are at `x = a` or `x = b`. Likewise in `y`. So the extremes of the mathematical
product over the box are among the four corners, and `x·y ∈ [min P, max P]`.
The overflow rule (§1) then covers wrapping. ∎

## 3. `Div` (I1)

**Error set.** Java throws `ArithmeticException` iff `y = 0`. The code adds
`divide by zero` iff `c ≤ 0 ≤ d`, which is exactly "some `y ∈ Y` is `0`". This is
exact in both directions, and Rules 1 and 2 rely on it.

**Quotient.** Only `y ∈ Y \ {0}` reaches the result. That set is
`Y⁻ = [c, min(d, −1)]` together with `Y⁺ = [max(c, 1), d]`. Each part is an
interval, possibly empty (`_nonzero_parts`). The result is the join of the two
parts, and the join is an upper bound, so it is enough to argue each part
separately.

Fix a part with constant sign, and write `q(x, y) = trunc(x / y)`:

- For fixed `y`, `q` is monotone in `x`: increasing if `y > 0`, decreasing if
  `y < 0`.
- For fixed `x`, `q` is monotone in `y` on a fixed-sign range. The direction
  depends on the sign of `x`, but for each `x` the extreme over `y` is at an
  endpoint of the part.
- So `max q = max over y ∈ {ends} of max over x of q(x, y)`. Each `q(·, y)` is
  monotone in `x`, so this is attained at an `x` endpoint. The extremes are
  therefore among the four corners, which is what `_div_part` computes.

**Overflow.** `|trunc(x / y)| ≤ |x|` for `|y| ≥ 1`, so the quotient is in range,
with one exception: `MIN / −1`. Mathematically that is `2³¹`, and Java wraps it to
`MIN`. `_div_part` returns `⊤` whenever `a = MIN` and `−1` is in the part. ∎

## 4. `Rem` (I1)

Java defines `x % y = x − trunc(x / y)·y`. For `y ≠ 0` it satisfies:

1. `x % y` is `0` or has the sign of `x`;
2. `|x % y| ≤ |y| − 1`;
3. `|x % y| ≤ |x|`.

**Claim.** For a fixed-sign divisor part with `m = max(|c'|, |d'|) − 1`, the result
is in `[lo, hi]`, where:

- `lo = 0` if `a ≥ 0`, otherwise `max(a, −m)`;
- `hi = 0` if `b ≤ 0`, otherwise `min(b, m)`.

**Argument.** If `x ≥ 0`, then by (1) and (2) `0 ≤ x % y ≤ min(x, m) ≤ hi`. If `x < 0`,
then `max(x, −m) ≤ x % y ≤ 0`, so `x % y ≥ max(a, −m) = lo`. All bounds are
in range, and `MIN % −1 = 0` gives `m = 0`, so the result is `[0, 0]`, which is
correct. The error set is the same as for `Div`. ∎

## 5. `Neg`

`−x` for `x ∈ [a, b]` is in `[−b, −a]` mathematically. The only value that overflows
is `x = MIN` (`−MIN = 2³¹`, which wraps to `MIN`). `_checked(−b, −a)` turns that into
`⊤`. ∎

## 6. `refine` (I2)

**Claim.** For every `x ∈ X`, `y ∈ Y` with `(x cond y) = holds`, the result
`(X', Y') = X.refine(Y, cond, holds)` satisfies `x ∈ X'` and `y ∈ Y'`. An empty `X'`
or `Y'` therefore proves the branch infeasible.

**Argument.** `holds = False` is handled by negating the condition. On `int`s,
`¬(x < y) ⇔ x ≥ y`, `¬(x ≤ y) ⇔ x > y`, and `¬(x = y) ⇔ x ≠ y`, which matches
`_NEGATED`. So it is enough to check each condition with `holds = True`:

| `cond` | `X'` | `Y'` | Why |
|---|---|---|---|
| `=` | `X ∩ Y` | `X ∩ Y` | `x = y` puts both values in both intervals |
| `<` | `X ∩ [MIN, d−1]` | `Y ∩ [a+1, MAX]` | `x < y ≤ d`, and `y > x ≥ a` |
| `≤` | `X ∩ [MIN, d]` | `Y ∩ [a, MAX]` | the same without the `+1` |
| `>`, `≥` | mirror images | | |
| `≠` | `X` minus `v`, only if `Y = [v, v]` and `v` is an endpoint of `X` | symmetric | `x ≠ v`. Intervals cannot represent a hole, so only an endpoint can go. If both are `[v, v]`, the branch is infeasible. |

**Refining locals through stack copies.** The analyser narrows local `i` when the
compared stack value is tagged `src = i`. This is sound because the tag means
"this value equals the *current* content of local `i`":

- `Load i` sets the tag.
- `Store i` and `Incr i` clear it on every stack copy (`AState.store`).
- Arithmetic results carry no tag.
- A join keeps a tag only if both sides have the same one.

So at the branch, the concrete local equals the concrete stack value, and the
condition holds for both. This is exactly the dependency problem the review
warned about in I2, and the tag handles it correctly.

`refine_local` *replaces* the local with the refined copy instead of meeting
with it. That is still sound, because the copy over-approximates the local.
Meeting would be more precise when the local was refined again after the load.

## 7. Widening and loop termination (TWI sketch)

**Upper bound.** `X ∇ Y` keeps a bound if it did not grow, and otherwise jumps to
`MIN`/`MAX`. So `X ⊑ X ∇ Y` and `Y ⊑ X ∇ Y`.

**Termination.** Along a chain `X₀, X₀ ∇ X₁, …`, each bound can change at most
once, to its limit, and it stays there. So with `k` locals and stack slots at a
loop head, the state there changes at most `2k` times, and the worklist
terminates. This is the core of the TWI proof.

The implementation widens to the `int` limits, not to the constants `K` the
proposal planned. That costs precision, not soundness.

**Divergence (`*`).** `*` is added for every reachable back edge, except loops
accepted by `_proven_terminating`. Take the `while (i < n) { …; i++; }` form,
`if_icmpge` with exactly one `iinc i +1` and no other jumps or writes to `i` or
`n` in the body:

- The body runs only when `i < n ≤ MAX`, so `i + 1` cannot wrap.
- `n − i` is a natural number that decreases by exactly 1 per iteration.
- An exception or a `return` in the body also ends the loop.

So the loop terminates. The `ifge` (+1 toward `0`) and `if_icmple`/`ifle`
(−1, downward) forms are symmetric. The `<`/`>` forms are rejected because
`i ≤ n` with `n = MAX` never fails. Every other loop keeps `*`, which is always
sound.
