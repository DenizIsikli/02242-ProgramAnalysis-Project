"""Baselines and ground truth for the evaluation (compared against `check_pair`).

* `z3_only`        - the symbolic checker alone, abstract interpretation gate disabled
* `random_testing` - differential testing: random inputs, same observation (outcome, value)
* `exhaustive`     - ground truth by running every input of a small domain concretely

All return a `PairVerdict` so the evaluation can treat them uniformly. Testing can only ever
find differences: without a witness it answers `unknown`, never `preserved`.
"""

from __future__ import annotations

import itertools
import random
import time

from abstractions import Region
from region_verdict import PairStats, PairVerdict, region_size
from symbolic import SymUnsupported, concrete_run, make_return_checker

import jpamb
from jpamb import jvm


def _verdict(domain, status, witness, stats) -> PairVerdict:
    total = region_size(domain)
    preserved = total if status == "preserved" else 0
    changed = 1 if status == "changed" else 0
    return PairVerdict(
        status,
        (),
        total,
        preserved,
        changed,
        total - preserved - changed,
        witness,
        stats,
    )


def z3_only(
    bc: jpamb.Bytecode,
    original: jvm.AbsMethodID,
    edited: jvm.AbsMethodID,
    domain: Region,
    timeout_ms: int = 5000,
) -> PairVerdict:
    """One SMT query over the whole domain (outcome classes and return values together)."""
    started = time.perf_counter()
    checker = make_return_checker(bc, original, edited, timeout_ms, observations=True)
    res = checker(domain)
    status = {"equal": "preserved", "differs": "changed"}.get(res.status, "unknown")
    stats = PairStats(0, 1, time.perf_counter() - started)
    return _verdict(domain, status, res.witness, stats)


def random_testing(
    bc: jpamb.Bytecode,
    original: jvm.AbsMethodID,
    edited: jvm.AbsMethodID,
    domain: Region,
    budget: int = 1000,
    seed: int = 0,
) -> PairVerdict:
    """Run `budget` uniformly random inputs on both versions; report the first difference."""
    started = time.perf_counter()
    rnd = random.Random(seed)
    bounds = list(domain.bounds.values())
    runs = 0
    witness = None
    try:
        for _ in range(budget):
            args = tuple(rnd.randint(b.min, b.max) for b in bounds)
            runs += 1
            if concrete_run(bc, original, args) != concrete_run(bc, edited, args):
                witness = args
                break
    except SymUnsupported:
        pass
    stats = PairStats(0, 0, time.perf_counter() - started, runs)
    return _verdict(domain, "changed" if witness else "unknown", witness, stats)


def exhaustive(
    bc: jpamb.Bytecode,
    original: jvm.AbsMethodID,
    edited: jvm.AbsMethodID,
    domain: Region,
    limit: int = 100_000,
) -> tuple[bool, int, tuple[int, ...] | None]:
    """Ground truth on a small domain: (any difference?, number of differing inputs, first)."""
    if region_size(domain) > limit:
        raise ValueError("domain too large for exhaustive execution")
    ranges = [range(b.min, b.max + 1) for b in domain.bounds.values()]
    count, first = 0, None
    for args in itertools.product(*ranges):
        if concrete_run(bc, original, args) != concrete_run(bc, edited, args):
            count += 1
            first = first or args
    return count > 0, count, first
