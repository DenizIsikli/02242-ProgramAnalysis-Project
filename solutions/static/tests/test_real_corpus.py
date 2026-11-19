"""The corpus pairs on real jvm2json output, checked region by region against the JVM.

Every region claim must hold on the reference observations (observation-contract.md
§5.1): `preserved` regions have only `same = yes` inputs, whole-region `changed` regions
only `same = no`, and a witness must be an input that differs. Skipped if
target/decompiled/jpamb/cases/Refactorings.json is absent.
"""

import csv
from pathlib import Path

import pytest
from check_pairs import load_pairs
from region_verdict import check_pair
from symbolic import make_return_checker

import jpamb

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    not (ROOT / "target/decompiled/jpamb/cases/Refactorings.json").exists(),
    reason="decompiled Refactorings.json not available",
)
PAIRS = list(load_pairs(ROOT))


@pytest.fixture(scope="module")
def bc():
    return jpamb.Bytecode(jpamb.Suite.from_workdir(ROOT), jpamb.utils.Effect(None))


@pytest.mark.parametrize("with_z3", [False, True])
@pytest.mark.parametrize("pair", PAIRS, ids=[p[0] for p in PAIRS])
def test_every_region_claim_holds_on_the_jvm(bc, pair, with_z3):
    name, a, b, domain, expected = pair
    path = ROOT / "evaluation" / "observations" / f"{name}.csv"
    params = list(domain.bounds)
    same = {
        tuple(int(r[p]) for p in params): r["same"] == "yes"
        for r in csv.DictReader(path.open())
    }
    v = check_pair(bc, a, b, domain, make_return_checker(bc, a, b) if with_z3 else None)

    for rv in v.regions:
        inside = [
            x
            for x in same
            if all(
                rv.region.bounds[p].min <= x[i] <= rv.region.bounds[p].max
                for i, p in enumerate(params)
            )
        ]
        if rv.status == "preserved":
            assert all(same[x] for x in inside), (name, rv)
        elif rv.status == "changed" and rv.whole_region:
            assert not any(same[x] for x in inside), (name, rv)
        elif rv.status == "changed":
            assert not same[rv.witness], (name, rv)
    assert v.overall == expected
    assert v.changed_inputs == sum(not s for s in same.values())
