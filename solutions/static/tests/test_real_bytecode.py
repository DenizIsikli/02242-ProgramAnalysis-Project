"""The analyser on real jvm2json output (jpamb.cases.Simple), no Docker needed.

Reproduces the three sanity checks from docs/project-start.md: 0/49, 1/7 and 47/49 inputs
differ. Skipped if target/decompiled/jpamb/cases/Simple.json is absent.
"""

from pathlib import Path

import pytest
from abstractions import Interval, Region
from region_verdict import check_pair

import jpamb
from jpamb import jvm

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    not (ROOT / "target/decompiled/jpamb/cases/Simple.json").exists(),
    reason="decompiled Simple.json not available",
)


def M(name, desc):
    return jvm.AbsMethodID.decode(f"jpamb.cases.Simple.{name}:{desc}")


@pytest.fixture(scope="module")
def bc():
    return jpamb.Bytecode(jpamb.Suite.from_workdir(ROOT), jpamb.utils.Effect(None))


def dom(k):
    return Region({f"p{i}": Interval(-3, 3) for i in range(k)})


def test_identity_pair_preserved(bc):
    v = check_pair(bc, M("justAdd", "(II)I"), M("justAdd", "(II)I"), dom(2))
    assert (v.overall, v.preserved_inputs, v.changed_inputs) == ("preserved", 49, 0)


def test_guard_removal_has_one_witness(bc):
    v = check_pair(
        bc, M("checkBeforeDivideByN", "(I)I"), M("divideByN", "(I)I"), dom(1)
    )
    assert v.overall == "changed" and v.witness == (0,)
    assert v.changed_inputs == 1 and v.preserved_inputs == 6 and v.unknown_inputs == 0


def test_return_only_difference_not_hidden_by_two_oks(bc):
    v = check_pair(bc, M("justAdd", "(II)I"), M("justMulitply", "(II)I"), dom(2))
    assert v.overall == "changed" and v.changed_inputs == 47 and v.preserved_inputs == 2


def test_z3_comparator_on_real_bytecode(bc):
    from symbolic import make_return_checker

    a, b = M("justAdd", "(II)I"), M("justMulitply", "(II)I")
    big = Region({"a": Interval(-1000, 1000), "b": Interval(-1000, 1000)})
    v = check_pair(bc, a, a, big, make_return_checker(bc, a, a))
    assert v.overall == "preserved" and v.certified_coverage == 1.0
    v = check_pair(bc, a, b, big, make_return_checker(bc, a, b), max_regions=20)
    assert v.overall == "changed" and v.witness is not None
