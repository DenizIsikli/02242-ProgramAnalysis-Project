"""Evaluation semantics: bounded testing must not invent proofs or hide failures."""

import json
import subprocess
from pathlib import Path

import pytest
from abstractions import Interval, Region
from check_pairs import differential_check, judge, run_strategy
from corpus_bytecode import parse_javap

ROOT = Path(__file__).resolve().parents[3]


def test_differential_return_only_fault_and_seed_reproducibility(fake_bc):
    domain = Region({"x": Interval(-3, 3)})
    a, b = fake_bc.ids["sign"], fake_bc.ids["sign_edited"]
    first = differential_check(fake_bc, a, b, domain, seed=7)
    assert first == differential_check(fake_bc, a, b, domain, seed=7)
    assert first["verdict"] == "changed"
    assert first["witness"] == (0,)


def test_differential_only_exhaustion_proves_preservation(fake_bc):
    domain = Region({"a": Interval(-3, 3), "b": Interval(-3, 3)})
    a, b = fake_bc.ids["safeDiv"], fake_bc.ids["safeDiv_edited"]
    partial = differential_check(fake_bc, a, b, domain, max_inputs=3)
    assert partial["verdict"] == "unknown"
    assert partial["tested_inputs"] == 3
    complete = differential_check(fake_bc, a, b, domain, max_inputs=49)
    assert complete["verdict"] == "preserved"
    assert complete["tested_inputs"] == 49


def test_execution_step_limit_is_not_a_nontermination_proof(fake_bc, monkeypatch):
    import symbolic

    monkeypatch.setattr(symbolic, "concrete_run", lambda *args: ("*", None))
    mid = fake_bc.ids["sign"]
    result = differential_check(fake_bc, mid, mid, Region({"x": Interval(0, 0)}))
    assert result["verdict"] == "unknown"
    assert result["inconclusive_inputs"] == 1
    assert result["certified_coverage"] == 0


def test_matched_budget_timeout_and_worker_error_are_distinct(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 0.25
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    result = run_strategy({}, 0.25)
    assert result["verdict"] == "unknown" and result["status"] == "TIMEOUT"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "broken"),
    )
    result = run_strategy({}, 0.25)
    assert result["verdict"] is None and result["status"] == "ERROR"
    assert result["error"] == "broken"


def test_false_verdicts_and_invalid_witnesses_fail_evaluation():
    domain = Region({"x": Interval(-3, 3)})
    result = {"status": "COMPLETED", "verdict": "changed", "witness": [3]}
    assert judge(result, "changed", domain, {(0,)}) == "WRONG"
    result["witness"] = [0]
    assert judge(result, "changed", domain, {(0,)}) == "PASS"
    result["verdict"], result["witness"] = "preserved", None
    assert judge(result, "changed", domain, {(0,)}) == "WRONG"
    result["verdict"] = "unknown"
    assert judge(result, "preserved", domain, set()) == "INCOMPLETE"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "         0: invokestatic #1\n         3: ireturn\n",
            "unsupported instruction",
        ),
        (
            "         0: iconst_0\n         1: ireturn\n    Exception table:\n",
            "exception handlers",
        ),
    ],
)
def test_local_decoder_rejects_unsupported_bytecode(body, message):
    text = (
        "  public static int example(int);\n    descriptor: (I)I\n"
        "    Code:\n      stack=1, locals=1, args_size=1\n" + body
    )
    with pytest.raises(ValueError, match=message):
        parse_javap(text)


def test_full_reference_corpus_validation(monkeypatch):

    monkeypatch.syspath_prepend(str(ROOT))
    from evaluation import check_expected

    key = json.loads((ROOT / "evaluation/expected/expected.json").read_text())
    problems = []
    check_expected.check_manifest(key, problems)
    check_expected.check_verdicts(key, problems)
    check_expected.check_case_annotations(key, problems)
    assert problems == []
    key["pairs"][0]["domain"]["a"] = [-2, 3]
    problems = []
    check_expected.check_manifest(key, problems)
    assert any("domain disagrees" in problem for problem in problems)


@pytest.mark.parametrize("damage", ["missing-row", "duplicate-row", "wrong-same"])
def test_reference_validation_rejects_incomplete_or_corrupt_observations(
    monkeypatch, damage
):
    monkeypatch.syspath_prepend(str(ROOT))
    from evaluation import check_expected

    entry = json.loads((ROOT / "evaluation/expected/expected.json").read_text())[
        "pairs"
    ][0]
    params, rows = check_expected.load_observations(entry["pair"])
    if damage == "missing-row":
        rows.pop()
    elif damage == "duplicate-row":
        rows.append(rows[0])
    else:
        rows[0]["same"] = "no"
    monkeypatch.setattr(
        check_expected, "load_observations", lambda *a, **k: (params, rows)
    )
    problems = []
    check_expected.check_verdicts({"pairs": [entry]}, problems)
    assert any(
        "exactly once" in problem or "same flag" in problem for problem in problems
    )
