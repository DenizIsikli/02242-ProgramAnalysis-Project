"""Ablation / baseline comparison: gate only, hybrid, Z3 only, random testing.

    PYTHONPATH=solutions/static/src:src python evaluation/ablation.py [--budget 1000] [--csv out.csv]

For every pair (the corpus in evaluation/expected/expected.json, a few `Simple` pairs and the loop /
many-path pairs of cases/jpamb/cases/EvalPairs.java) it
runs four methods on a small domain [-3,3]^k (ground truth by exhaustive execution) and a
large domain [-1000,1000]^k (no exhaustive truth; verdicts are sanity-checked by sampling):

  gate    intervals + refinement only (no solver)
  hybrid  intervals + refinement, Z3 on regions where both versions are proved to return
  z3only  one SMT query over the whole domain, abstract gate disabled
  random  differential testing, `--budget` random inputs

A verdict contradicting the truth (preserved but a difference exists, changed without a real
difference) is counted as WRONG. `unknown` is never wrong, only incomplete.
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from abstractions import Interval, Region
from baselines import exhaustive, random_testing, z3_only
from region_verdict import check_pair
from symbolic import concrete_run, make_return_checker

import jpamb
from jpamb import jvm

ROOT = Path(__file__).resolve().parents[1]

# Extra pairs from the stock benchmark class (name, edited name, descriptor).
SIMPLE = [
    ("justAdd", "justAdd", "(II)I"),
    ("justAdd", "justMulitply", "(II)I"),
    ("divideByN", "divideByN", "(I)I"),
    ("checkBeforeDivideByN", "divideByN", "(I)I"),
    ("checkBeforeDivideByN2", "divideByN", "(I)I"),
]


# Evaluation-only pairs (cases/jpamb/cases/EvalPairs.java): loops and many paths.
EVAL = [
    ("loopDiv", "loopDiv_guarded", "(II)I"),
    ("loopDiv", "loopDiv_rewritten", "(II)I"),
    ("loopThenZero", "loopThenZero_edited", "(I)I"),
    ("ladder", "ladder_reordered", "(I)I"),
    ("ladder", "ladder_changed", "(I)I"),
]


def pairs(root: Path):
    key = json.loads((root / "evaluation/expected/expected.json").read_text())
    for p in key["pairs"]:
        yield (
            p["pair"],
            jvm.AbsMethodID.decode(p["method"]),
            jvm.AbsMethodID.decode(p["edited"]),
        )
    for a, b, desc in SIMPLE:
        yield (
            f"{a}~{b}",
            jvm.AbsMethodID.decode(f"jpamb.cases.Simple.{a}:{desc}"),
            jvm.AbsMethodID.decode(f"jpamb.cases.Simple.{b}:{desc}"),
        )
    for a, b, desc in EVAL:
        yield (
            f"{a}~{b}",
            jvm.AbsMethodID.decode(f"jpamb.cases.EvalPairs.{a}:{desc}"),
            jvm.AbsMethodID.decode(f"jpamb.cases.EvalPairs.{b}:{desc}"),
        )


def domain(a: jvm.AbsMethodID, lo: int, hi: int) -> Region:
    return Region({f"p{i}": Interval(lo, hi) for i in range(len(a.extension.params))})


def sample_differs(bc, a, b, dom: Region, n: int = 2000) -> tuple[int, ...] | None:
    rnd = random.Random(1)
    bounds = list(dom.bounds.values())
    for _ in range(n):
        args = tuple(rnd.randint(x.min, x.max) for x in bounds)
        if concrete_run(bc, a, args) != concrete_run(bc, b, args):
            return args
    return None


def run(bc, name, a, b, lo, hi, budget, truth_exact, timeout_ms=5000):
    dom = domain(a, lo, hi)
    if truth_exact:
        differs, _count, _ = exhaustive(bc, a, b, dom)
    results = {}
    results["gate"] = check_pair(bc, a, b, dom)
    results["hybrid"] = check_pair(
        bc, a, b, dom, make_return_checker(bc, a, b, timeout_ms)
    )
    results["z3only"] = z3_only(bc, a, b, dom, timeout_ms)
    results["random"] = random_testing(bc, a, b, dom, budget)
    rows = []
    for mode, v in results.items():
        if truth_exact:
            wrong = (v.overall == "preserved" and differs) or (
                v.overall == "changed" and not differs
            )
        else:  # no exhaustive truth: a preserved verdict must survive sampling
            wrong = v.overall == "preserved" and sample_differs(bc, a, b, dom)
        rows.append(
            {
                "pair": name,
                "domain": f"[{lo},{hi}]^{len(a.extension.params)}",
                "size": "small" if truth_exact else "large",
                "truth": ("differs" if differs else "equal") if truth_exact else "n/a",
                "mode": mode,
                "verdict": v.overall,
                "coverage": round(v.certified_coverage, 4),
                "witness": v.witness,
                "regions": v.stats.regions_analysed,
                "solver_calls": v.stats.checker_calls,
                "executions": v.stats.executions,
                "ms": round(v.stats.seconds * 1000, 1),
                "wrong": bool(wrong),
            }
        )
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--budget", type=int, default=1000, help="random-testing executions"
    )
    ap.add_argument(
        "--timeout-ms", type=int, default=5000, help="per-query solver timeout"
    )
    ap.add_argument("--csv", help="also write all rows to this CSV file")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root)
    bc = jpamb.Bytecode(
        jpamb.Suite.from_workdir(root.resolve()), jpamb.utils.Effect(None)
    )

    rows = []
    for name, a, b in pairs(root):
        rows += run(bc, name, a, b, -3, 3, args.budget, True, args.timeout_ms)
        rows += run(bc, name, a, b, -1000, 1000, args.budget, False, args.timeout_ms)

    for size, label in (
        ("small", "small domain [-3,3]^k (ground truth by exhaustive execution)"),
        (
            "large",
            "large domain [-1000,1000]^k (preserved verdicts sanity-checked by sampling)",
        ),
    ):
        print(f"\n### {label}")
        print(
            "| pair | truth | mode | verdict | coverage | regions | SMT | runs | ms | witness |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|")
        for r in (r for r in rows if r["size"] == size):
            flag = " **WRONG**" if r["wrong"] else ""
            print(
                f"| {r['pair']} | {r['truth']} | {r['mode']} | {r['verdict']}{flag} | "
                f"{r['coverage']:.0%} | {r['regions']} | {r['solver_calls']} | "
                f"{r['executions']} | {r['ms']} | {r['witness'] or ''} |"
            )

    print("\n### summary (all domains)")
    print("| mode | decided | wrong | mean coverage | total ms |")
    print("|---|---|---|---|---|")
    for mode in ("gate", "hybrid", "z3only", "random"):
        sel = [r for r in rows if r["mode"] == mode]
        decided = sum(r["verdict"] != "unknown" for r in sel)
        print(
            f"| {mode} | {decided}/{len(sel)} | {sum(r['wrong'] for r in sel)} | "
            f"{sum(r['coverage'] for r in sel) / len(sel):.0%} | "
            f"{sum(r['ms'] for r in sel):.0f} |"
        )

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 1 if any(r["wrong"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
