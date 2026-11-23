"""Pair-level evaluation and a matched-budget differential-testing baseline.

Only the parent harness reads the answer key. Each strategy runs in an isolated
subprocess with the same wall-clock limit, including imports, bytecode loading and
solver setup. Common Java compilation and reference checking are outside the budget.
"""

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from abstractions import Interval, Region
from corpus_bytecode import compile_corpus, load_bytecode
from region_verdict import check_pair, region_size

from jpamb import jvm


def load_pairs(root: Path):
    key = json.loads((root / "evaluation/expected/expected.json").read_text())
    for p in key["pairs"]:
        domain = Region({n: Interval(lo, hi) for n, (lo, hi) in p["domain"].items()})
        yield (
            p["pair"],
            jvm.AbsMethodID.decode(p["method"]),
            jvm.AbsMethodID.decode(p["edited"]),
            domain,
            p["verdict"],
        )


def differential_check(bc, original, edited, domain, *, seed=0, max_inputs=1000):
    """Test a seeded sample without replacement; only exhaustion proves preservation."""
    from region_analysis import has_exception_handlers
    from symbolic import concrete_run

    size = region_size(domain)
    if size == 0 or max_inputs <= 0:
        raise ValueError(
            "differential testing requires a nonempty domain and positive input budget"
        )
    if any(has_exception_handlers(bc, method) for method in (original, edited)):
        raise ValueError("differential testing does not support exception handlers")
    rng = random.Random(seed)
    widths = [iv.max - iv.min + 1 for iv in domain.bounds.values()]
    tested = 0
    inconclusive = 0
    for index in rng.sample(range(size), min(size, max_inputs)):
        coordinates = []
        for iv, width in reversed(list(zip(domain.bounds.values(), widths))):
            coordinates.append(iv.min + index % width)
            index //= width
        args = tuple(reversed(coordinates))
        observed_a = concrete_run(bc, original, args)
        observed_b = concrete_run(bc, edited, args)
        tested += 1
        if "*" in (observed_a[0], observed_b[0]):
            inconclusive += 1
            continue
        if observed_a != observed_b:
            return {
                "verdict": "changed",
                "witness": args,
                "tested_inputs": tested,
                "tested_fraction": tested / size,
                "certified_coverage": (tested - inconclusive) / size,
                "inconclusive_inputs": inconclusive,
            }
    return {
        "verdict": "preserved" if tested == size and not inconclusive else "unknown",
        "witness": None,
        "tested_inputs": tested,
        "tested_fraction": tested / size,
        "certified_coverage": (tested - inconclusive) / size,
        "inconclusive_inputs": inconclusive,
    }


def worker(payload: dict) -> dict:
    from symbolic import make_return_checker

    bc = load_bytecode(Path(payload["root"]), payload["class_data"])
    a = jvm.AbsMethodID.decode(payload["original"])
    b = jvm.AbsMethodID.decode(payload["edited"])
    domain = Region({n: Interval(*iv) for n, iv in payload["domain"].items()})
    if payload["strategy"] == "differential":
        return differential_check(
            bc, a, b, domain, seed=payload["seed"], max_inputs=payload["max_inputs"]
        )
    verdict = check_pair(
        bc,
        a,
        b,
        domain,
        make_return_checker(bc, a, b),
        max_regions=payload["max_regions"],
    )
    return {
        "verdict": verdict.overall,
        "witness": verdict.witness,
        "certified_coverage": verdict.certified_coverage,
        "preserved_inputs": verdict.preserved_inputs,
        "changed_inputs": verdict.changed_inputs,
        "unknown_inputs": verdict.unknown_inputs,
    }


def run_strategy(payload: dict, budget: float) -> dict:
    started = time.perf_counter()
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "unknown",
            "status": "TIMEOUT",
            "witness": None,
            "certified_coverage": 0.0,
            "elapsed_s": time.perf_counter() - started,
        }
    elapsed = time.perf_counter() - started
    if process.returncode:
        return {
            "verdict": None,
            "status": "ERROR",
            "witness": None,
            "certified_coverage": 0.0,
            "elapsed_s": elapsed,
            "error": process.stderr.strip(),
        }
    result = json.loads(process.stdout)
    result.update(status="COMPLETED", elapsed_s=elapsed)
    return result


def judge(result: dict, expected: str, domain: Region, differing: set) -> str:
    if result["status"] == "ERROR":
        return "ERROR"
    witness = result["witness"]
    if witness is not None:
        args = tuple(witness)
        if len(args) != len(domain.bounds) or args not in differing:
            return "WRONG"
        if dict(zip(domain.bounds, args)) not in domain:
            return "WRONG"
    if result["verdict"] == "unknown":
        return "INCOMPLETE"
    if result["verdict"] == "changed" and witness is None:
        return "WRONG"
    return "PASS" if result["verdict"] == expected else "WRONG"


def positive_int(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--budget-seconds", type=positive_seconds, default=5.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-inputs", type=positive_int, default=1000)
    parser.add_argument("--max-regions", type=positive_int, default=200)
    parser.add_argument("--pair", help="evaluate only this pair")
    parser.add_argument(
        "--committed-bytecode",
        action="store_true",
        help="use target/decompiled instead of compiling with the local JDK",
    )
    parser.add_argument("--json", type=Path, help="write the full evaluation report")
    options = parser.parse_args(argv)
    root = options.root.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from evaluation.check_expected import (
        check_case_annotations,
        check_manifest,
        check_verdicts,
        load_observations,
        side,
    )

    key = json.loads((root / "evaluation/expected/expected.json").read_text())
    problems = []
    check_manifest(key, problems, root=root)
    check_verdicts(key, problems, root=root)
    check_case_annotations(key, problems, root=root)
    if problems:
        parser.error("invalid reference corpus:\n" + "\n".join(problems))
    pairs = list(load_pairs(root))
    if options.pair:
        pairs = [p for p in pairs if p[0] == options.pair]
        if not pairs:
            parser.error(f"unknown pair: {options.pair}")
    class_data = None if options.committed_bytecode else compile_corpus(root)
    results = []
    print(
        f"{'pair':<12} {'strategy':<13} {'expected':<10} {'got':<10} {'coverage':>9} {'status'}"
    )
    for name, a, b, domain, expected in pairs:
        params, rows = load_observations(name, root=root)
        differing = {
            tuple(int(row[p]) for p in params)
            for row in rows
            if side(row, "orig") != side(row, "edited")
        }
        for strategy in ("analyser", "differential"):
            payload = {
                "root": str(root),
                "class_data": class_data,
                "strategy": strategy,
                "original": a.encode(),
                "edited": b.encode(),
                "domain": {n: [iv.min, iv.max] for n, iv in domain.bounds.items()},
                "seed": options.seed,
                "max_inputs": options.max_inputs,
                "max_regions": options.max_regions,
            }
            result = run_strategy(payload, options.budget_seconds)
            result["assessment"] = judge(result, expected, domain, differing)
            result.update(
                pair=name,
                strategy=strategy,
                expected=expected,
                domain_size=region_size(domain),
            )
            results.append(result)
            print(
                f"{name:<12} {strategy:<13} {expected:<10} "
                f"{result['verdict']!s:<10} {result['certified_coverage']:>8.0%} "
                f"{result['assessment']} ({result['status']})"
            )
            if "error" in result:
                print(result["error"], file=sys.stderr)
    summary = {
        strategy: {
            assessment: sum(
                r["strategy"] == strategy and r["assessment"] == assessment
                for r in results
            )
            for assessment in ("PASS", "WRONG", "INCOMPLETE", "ERROR")
        }
        for strategy in ("analyser", "differential")
    }
    report = {
        "config": {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "corpus_sha256": hashlib.sha256(
                (root / "cases/jpamb/cases/Refactorings.java").read_bytes()
            ).hexdigest(),
            "budget_seconds_per_pair_per_strategy": options.budget_seconds,
            "budget_includes": "process startup, imports, bytecode loading, solver setup and execution",
            "budget_excludes": "common Java compilation and reference validation",
            "bytecode": "committed"
            if options.committed_bytecode
            else "local javac/javap via JPAMB",
            "seed": options.seed,
            "max_inputs": options.max_inputs,
            "max_regions": options.max_regions,
            "baseline": "seeded differential testing using the concrete Java-int interpreter",
        },
        "results": results,
        "summary": summary,
    }
    print(json.dumps(summary, indent=2))
    if options.json:
        options.json.write_text(json.dumps(report, indent=2) + "\n")
    return int(any(r["assessment"] in ("WRONG", "ERROR") for r in results))


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        print(json.dumps(worker(json.load(sys.stdin))))
    else:
        sys.exit(main())
