"""Regional verdicts, refinement and the overall verdict for a method pair.

Implements the rules of docs/refactoring/verdict-rules.md (Deniz). Applied in order, first
match wins:

  0  an outcome set is empty                       -> unknown (analysis failure)
  1  A^ = B^ = {e}, e != ok                        -> preserved (whole region)
  2  A^ and B^ disjoint                            -> changed   (whole region differs)
  2b both {ok} and the return intervals are
     disjoint / equal singletons                   -> changed (whole region) / preserved
  3  both {ok} and the Z3 return check says equal  -> preserved (whole region)
  3' both {ok} and the return check finds a
     replayed witness                              -> changed (witness only)
  4  otherwise                                     -> unknown, refine

Rule 2b is an extension of ours (not in the Deniz document): by (S) applied to return
values, singleton return intervals describe a constant function on the region. It lets the
pipeline decide e.g. `sign` on point regions without calling Z3. Deniz should review it.

The return checker (rules 3/3') is a plug-in: any callable
`(region) -> ReturnCheck`, so the Z3 comparator can be dropped in later. Solver unknown,
timeout or a model that does not replay MUST be reported as `unknown`.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from abstractions import Interval, Region
from region_analysis import AnalysisResult, analyse_outcomes

import jpamb
from jpamb import jvm

Status = Literal["preserved", "changed", "unknown"]


@dataclass(frozen=True)
class ReturnCheck:
    """Result of comparing return values of A and B on a region where both are {ok}."""

    status: Literal["equal", "differs", "unknown"]
    witness: tuple[int, ...] | None = None  # for "differs"; must already be replayed


ReturnChecker = Callable[[Region], ReturnCheck]


@dataclass(frozen=True)
class RegionVerdict:
    region: Region
    status: Status
    rule: str
    # True if the verdict holds for EVERY input of the region (rules 1, 2, 2b, 3).
    # A rule-3' `changed` only certifies its single witness.
    whole_region: bool
    witness: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PairVerdict:
    overall: Status  # "preserved" here means: on the whole declared domain
    regions: tuple[RegionVerdict, ...]
    domain_size: int
    preserved_inputs: int
    changed_inputs: (
        int  # inputs certified as differing (whole-region changed + witnesses)
    )
    unknown_inputs: int
    witness: tuple[int, ...] | None

    @property
    def certified_coverage(self) -> float:
        """Fraction of the domain with a certified verdict (preserved or changed)."""
        return (self.preserved_inputs + self.changed_inputs) / self.domain_size


def region_size(region: Region) -> int:
    if region.is_empty:
        return 0
    return math.prod(i.max - i.min + 1 for i in region.bounds.values())


def lower_corner(region: Region) -> tuple[int, ...]:
    return tuple(i.min for i in region.bounds.values())


def region_verdict(
    a: AnalysisResult,
    b: AnalysisResult,
    region: Region,
    return_check: ReturnChecker | None = None,
) -> RegionVerdict:
    def unk(rule: str) -> RegionVerdict:
        return RegionVerdict(region, "unknown", rule, False)

    # Rule 0: an empty outcome set for a non-empty region means the analysis is broken.
    if not a.outcomes or not b.outcomes:
        return unk("0: empty outcome set")

    # Unsupported results carry the full outcome set, so rules 1/2 cannot fire by accident;
    # still, be explicit so Rule 3 never trusts bogus return intervals.
    if not (a.supported and b.supported):
        return unk("4: unsupported method")

    # Rule 1: same single error.
    if a.outcomes == b.outcomes and len(a.outcomes) == 1 and "ok" not in a.outcomes:
        return RegionVerdict(region, "preserved", "1: same singleton error", True)

    # Rule 2: disjoint outcome sets -> every input differs; the lower corner is a witness.
    if a.outcomes.isdisjoint(b.outcomes):
        return RegionVerdict(
            region, "changed", "2: disjoint outcomes", True, lower_corner(region)
        )

    if a.outcomes == b.outcomes == {"ok"}:
        ra, rb = a.returns, b.returns
        if ra is not None and rb is not None:
            # Rule 2b: return intervals disjoint -> every input returns different values.
            if (ra & rb).is_empty:
                return RegionVerdict(
                    region,
                    "changed",
                    "2b: disjoint returns",
                    True,
                    lower_corner(region),
                )
            # Rule 2b': both return the same constant on the whole region.
            if ra.min == ra.max == rb.min == rb.max:
                return RegionVerdict(
                    region, "preserved", "2b: equal constant return", True
                )
        # Rules 3 / 3': ask the return checker, if one is plugged in.
        if return_check is not None:
            res = return_check(region)
            if res.status == "equal":
                return RegionVerdict(
                    region, "preserved", "3: return values equal (SMT)", True
                )
            if res.status == "differs" and res.witness is not None:
                return RegionVerdict(
                    region, "changed", "3': return witness", False, res.witness
                )
        return unk("4: both ok, return values not decided")

    return unk("4: outcome sets overlap")


# --- refinement -----------------------------------------------------------------------


def constants_of(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID) -> set[int]:
    """Integer constants a method compares against or computes with (plus 0)."""
    consts = {0}
    for op in bc.getmethod(methodid).opcodes:
        if (
            isinstance(op, jvm.Push)
            and isinstance(op.value, int)
            and not isinstance(op.value, bool)
        ):
            consts.add(op.value)
    return consts


def split_region(region: Region, constants: Iterable[int]) -> list[Region]:
    """Split into disjoint children that cover the parent, or [] if it is a single point.

    Prefers splitting off a constant c as its own slice: [lo, c-1], [c, c], [c+1, hi].
    With no usable constant, bisects the widest parameter.
    """
    names = list(region.bounds)
    if region_size(region) <= 1:
        return []
    for name in names:
        iv = region.bounds[name]
        usable = sorted(
            c for c in constants if iv.min <= c <= iv.max and iv.min != iv.max
        )
        if usable:
            c = usable[0]
            pieces = [
                Interval(iv.min, c - 1),
                Interval(c, c),
                Interval(c + 1, iv.max),
            ]
            return _children(region, name, pieces)
    name = max(names, key=lambda n: region.bounds[n].max - region.bounds[n].min)
    iv = region.bounds[name]
    mid = iv.min + (iv.max - iv.min) // 2
    return _children(region, name, [Interval(iv.min, mid), Interval(mid + 1, iv.max)])


def _children(region: Region, name: str, pieces: list[Interval]) -> list[Region]:
    kids = []
    for p in pieces:
        if p.is_empty:
            continue
        kids.append(Region({**region.bounds, name: p}))
    return kids


# --- pair checking --------------------------------------------------------------------


def check_pair(
    bc: jpamb.Bytecode,
    original: jvm.AbsMethodID,
    edited: jvm.AbsMethodID,
    domain: Region,
    return_check: ReturnChecker | None = None,
    max_regions: int = 200,
) -> PairVerdict:
    """Decide a method pair over `domain` by regional analysis and refinement.

    `max_regions` bounds how many regions are analysed; regions still undecided when the
    budget runs out stay `unknown`. Children are disjoint and cover their parent, so the
    input counts never double-count.
    """
    consts = constants_of(bc, original) | constants_of(bc, edited)
    queue: deque[Region] = deque([domain])
    decided: list[RegionVerdict] = []
    witnesses: list[tuple[int, ...]] = []
    analysed = 0

    while queue:
        region = queue.popleft()
        if region.is_empty:
            continue  # empty regions are discarded and never produce a witness
        a = analyse_outcomes(bc, original, region)
        b = analyse_outcomes(bc, edited, region)
        analysed += 1
        v = region_verdict(a, b, region, return_check)
        if v.status != "unknown" and v.whole_region:
            decided.append(v)
            continue
        if v.witness is not None:
            witnesses.append(v.witness)  # a validated counterexample: keep it ...
        # ... but still refine, so the rest of the region can be certified.
        kids = (
            split_region(region, consts) if analysed + len(queue) < max_regions else []
        )
        if kids:
            queue.extend(kids)
        else:
            decided.append(v)

    return _combine(domain, decided, witnesses)


def _combine(
    domain: Region, verdicts: list[RegionVerdict], witnesses: list[tuple[int, ...]]
) -> PairVerdict:
    preserved = changed = unknown = 0
    witness = witnesses[0] if witnesses else None
    for v in verdicts:
        size = region_size(v.region)
        if v.status == "preserved":
            preserved += size
        elif v.status == "changed":
            changed += size if v.whole_region else 1
            unknown += 0 if v.whole_region else size - 1
            witness = witness or v.witness
        else:
            unknown += size
    total = region_size(domain)
    if witness is not None:
        overall: Status = "changed"
    elif preserved == total:
        overall = "preserved"
    else:
        overall = "unknown"
    return PairVerdict(
        overall, tuple(verdicts), total, preserved, changed, unknown, witness
    )
