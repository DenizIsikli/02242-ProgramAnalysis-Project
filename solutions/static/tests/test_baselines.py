"""Baselines, ground truth, pair statistics and the ablation script."""

from pathlib import Path

import pytest
from abstractions import Interval, Region
from baselines import exhaustive, random_testing, z3_only
from region_verdict import check_pair
from symbolic import make_return_checker

DOM = Interval(-3, 3)
ROOT = Path(__file__).resolve().parents[3]


def region(*ivs):
    return Region({f"p{i}": iv for i, iv in enumerate(ivs)})


def test_exhaustive_counts_differing_inputs(fake_bc):
    ids = fake_bc.ids
    assert exhaustive(
        fake_bc, ids["safeDiv"], ids["safeDiv_edited"], region(DOM, DOM)
    ) == (
        False,
        0,
        None,
    )
    assert exhaustive(fake_bc, ids["ratio"], ids["ratio_edited"], region(DOM, DOM)) == (
        True,
        1,
        (0, 0),
    )
    assert exhaustive(fake_bc, ids["sign"], ids["sign_edited"], region(DOM))[:2] == (
        True,
        1,
    )
    with pytest.raises(ValueError):
        exhaustive(fake_bc, ids["sign"], ids["sign_edited"], region(Interval(0, 10**6)))


def test_z3_only_decides_with_error_paths(fake_bc):
    ids = fake_bc.ids
    v = z3_only(fake_bc, ids["ratio"], ids["ratio_edited"], region(DOM, DOM))
    assert v.overall == "changed" and v.witness == (0, 0) and v.stats.checker_calls == 1
    v = z3_only(fake_bc, ids["safeDiv"], ids["safeDiv_edited"], region(DOM, DOM))
    assert v.overall == "preserved" and v.certified_coverage == 1.0


def test_random_testing_never_claims_preserved(fake_bc):
    ids = fake_bc.ids
    v = random_testing(
        fake_bc, ids["safeDiv"], ids["safeDiv_edited"], region(DOM, DOM), 500
    )
    assert v.overall == "unknown" and v.stats.executions == 500
    v = random_testing(fake_bc, ids["sign"], ids["sign_edited"], region(DOM), 500)
    assert v.overall == "changed" and v.witness == (0,)
    # a difference at a single point of a huge domain is (almost surely) missed
    big = region(Interval(-(10**6), 10**6), Interval(-(10**6), 10**6))
    v = random_testing(fake_bc, ids["ratio"], ids["ratio_edited"], big, 200, seed=1)
    assert v.overall == "unknown"


def test_pair_stats_are_reported(fake_bc):
    ids = fake_bc.ids
    chk = make_return_checker(fake_bc, ids["sign"], ids["sign_edited"])
    v = check_pair(fake_bc, ids["sign"], ids["sign_edited"], region(DOM), chk)
    assert v.stats.regions_analysed >= 1 and v.stats.checker_calls >= 1
    assert v.stats.seconds > 0
    v = check_pair(fake_bc, ids["sign"], ids["sign_edited"], region(DOM))
    assert v.stats.checker_calls == 0


@pytest.mark.skipif(
    not (ROOT / "target/decompiled/jpamb/cases/Refactorings.json").exists(),
    reason="decompiled corpus not available",
)
def test_ablation_script_runs_and_nothing_is_wrong(capsys):
    import sys

    sys.path.insert(0, str(ROOT / "evaluation"))
    import ablation

    assert ablation.main(["--budget", "50", "--root", str(ROOT)]) == 0
    out = capsys.readouterr().out
    assert "### summary" in out and "WRONG" not in out
