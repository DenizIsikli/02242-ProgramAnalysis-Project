"""Current compiled corpus bytecode, checked region by region against the JVM.

Every region claim must hold on the reference observations (observation-contract.md
§5.1): `preserved` regions have only `same = yes` inputs, whole-region `changed` regions
only `same = no`, and a witness must be an input that differs. Skipped if
the JDK is absent. The native adapter is also checked against committed jvm2json output.
"""

import csv
import shutil
from pathlib import Path

import pytest
from check_pairs import load_pairs
from corpus_bytecode import compile_corpus, load_bytecode
from region_verdict import check_pair
from symbolic import make_return_checker

import jpamb

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    not (shutil.which("javac") and shutil.which("javap")),
    reason="JDK needed to test the current Java corpus",
)
PAIRS = list(load_pairs(ROOT))


@pytest.fixture(scope="module")
def bc():
    return load_bytecode(ROOT, compile_corpus(ROOT))


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


def test_jdk_adapter_matches_existing_jvm2json(bc):
    """Cross-check decoding and branch targets against the original jvm2json artifact."""
    committed = jpamb.Bytecode(jpamb.Suite.from_workdir(ROOT), jpamb.utils.Effect(None))
    for pair in PAIRS[:3]:
        for mid in pair[1:3]:
            assert bc.getmethod(mid) == committed.getmethod(mid)


@pytest.mark.parametrize("pair", PAIRS, ids=[p[0] for p in PAIRS])
def test_baseline_interpreter_matches_every_real_jvm_observation(bc, pair):
    from symbolic import concrete_run

    name, a, b, domain, _ = pair
    with (ROOT / "evaluation/observations" / f"{name}.csv").open() as stream:
        for row in csv.DictReader(stream):
            args = tuple(int(row[p]) for p in domain.bounds)
            for mid, prefix in ((a, "orig"), (b, "edited")):
                outcome = row[f"{prefix}_outcome"]
                value = int(row[f"{prefix}_return"]) if outcome == "ok" else None
                assert concrete_run(bc, mid, args) == (outcome, value)
