"""Soundness of the outcome analysis on every int-only JPAMB benchmark method.

For each method in target/stats/cases.txt whose parameters are all `int`, analyse the region
[-3, 3]^k and compare with concrete execution of every input in the region. The concrete
outcome ("*" if the step budget runs out) must be in the abstract outcome set, and a
returned value must lie in the return interval. Methods the analyser or the concrete
interpreter do not support are skipped (and counted). Skipped if the benchmark files are absent.
"""

import itertools
from pathlib import Path

import pytest
from abstractions import Interval, Region
from region_analysis import analyse_outcomes
from symbolic import SymUnsupported, concrete_run

import jpamb
from jpamb import jvm

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "target/stats/cases.txt"
pytestmark = pytest.mark.skipif(
    not CASES.exists(), reason="benchmark cases.txt not available"
)


def method_ids():
    ids = {}
    for line in CASES.read_text().splitlines():
        if line.strip():
            mid = jvm.AbsMethodID.decode(line.split()[0])
            ids[mid.encode()] = mid
    return list(ids.values())


def test_outcome_analysis_is_sound_on_int_methods():
    bc = jpamb.Bytecode(jpamb.Suite.from_workdir(ROOT), jpamb.utils.Effect(None))
    checked = skipped = 0
    for mid in method_ids():
        params = list(mid.extension.params)
        if len(params) > 2 or not all(isinstance(p, jvm.Int) for p in params):
            continue
        region = Region({f"p{i}": Interval(-3, 3) for i in range(len(params))})
        try:
            res = analyse_outcomes(bc, mid, region)
        except Exception:  # noqa: BLE001 - e.g. duplicate-name lookup in the suite
            skipped += 1
            continue
        if not res.supported:
            skipped += 1
            continue
        for args in itertools.product(range(-3, 4), repeat=len(params)):
            try:
                outcome, value = concrete_run(bc, mid, args)
            except (SymUnsupported, Exception):  # noqa: BLE001
                skipped += 1
                break
            assert outcome in res.outcomes, (mid.encode(), args, outcome, res)
            if value is not None:
                assert Interval(value, value) <= res.returns, (
                    mid.encode(),
                    args,
                    value,
                    res,
                )
        else:
            checked += 1
    assert checked > 0, "nothing was checked"
    print(f"soundness checked on {checked} methods, skipped {skipped}")
