"""Checks the corpus answer key against the reference observations.

Two checks, both independent of our analyser:
  1. evaluation/expected/expected.json (hand-written verdicts and counterexamples)
     agrees with evaluation/observations/*.csv (real JVM runs).
  2. Every @Case annotation in Refactorings.java that falls inside the declared
     domain agrees with the observed outcome.

Run after `bash evaluation/observe.sh`:   python3 evaluation/check_expected.py
Exits with status 1 and prints the problems if anything disagrees.
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "evaluation" / "expected" / "expected.json"
OBSERVATIONS = ROOT / "evaluation" / "observations"
CASES = ROOT / "cases" / "jpamb" / "cases" / "Refactorings.java"


def load_observations(pair):
    """Returns (parameter names, rows) where each row maps column -> value."""
    with open(OBSERVATIONS / f"{pair}.csv", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        params = reader.fieldnames[: reader.fieldnames.index("orig_outcome")]
    return params, rows


def side(row, prefix):
    """The {outcome, return} record for one version, in expected.json's shape."""
    result = {"outcome": row[f"{prefix}_outcome"]}
    if result["outcome"] == "ok":
        result["return"] = int(row[f"{prefix}_return"])
    return result


def check_verdicts(expected, problems):
    for entry in expected["pairs"]:
        pair = entry["pair"]
        params, rows = load_observations(pair)

        if list(entry["domain"]) != params:
            problems.append(f"{pair}: domain names {list(entry['domain'])} != CSV columns {params}")

        observed = {}
        for row in rows:
            if row["same"] == "no":
                key = tuple(int(row[p]) for p in params)
                observed[key] = {"original": side(row, "orig"), "edited": side(row, "edited")}

        verdict = "changed" if observed else "preserved"
        if entry["verdict"] != verdict:
            problems.append(f"{pair}: expected verdict {entry['verdict']!r}, observed {verdict!r}")

        recorded = {tuple(c["input"]): {"original": c["original"], "edited": c["edited"]}
                    for c in entry["counterexamples"]}
        for key in observed.keys() - recorded.keys():
            problems.append(f"{pair}: input {key} differs but is not listed as a counterexample")
        for key in recorded.keys() - observed.keys():
            problems.append(f"{pair}: listed counterexample {key} does not actually differ")
        for key in recorded.keys() & observed.keys():
            if recorded[key] != observed[key]:
                problems.append(f"{pair}: counterexample {key} recorded as {recorded[key]}, "
                                f"observed {observed[key]}")


CASE_RE = re.compile(r'@Case\("\(([^)]*)\)\s*->\s*([^"]+)"\)')
METHOD_RE = re.compile(r"public static \w+ (\w+)\(")


def check_case_annotations(expected, problems):
    """Every in-domain @Case must match what the JVM actually did."""
    pending = []
    annotations = {}
    for line in CASES.read_text().splitlines():
        if m := CASE_RE.search(line):
            args = tuple(int(a) for a in m.group(1).split(",") if a.strip())
            pending.append((args, m.group(2).strip()))
        elif m := METHOD_RE.search(line):
            annotations[m.group(1)] = pending
            pending = []

    for entry in expected["pairs"]:
        pair = entry["pair"]
        params, rows = load_observations(pair)
        by_input = {tuple(int(r[p]) for p in params): r for r in rows}
        for method, prefix in ((pair, "orig"), (pair + "_edited", "edited")):
            for args, outcome in annotations.get(method, []):
                row = by_input.get(args)
                if row is None:
                    problems.append(f"{method}: @Case input {args} is outside the declared domain")
                elif row[f"{prefix}_outcome"] != outcome:
                    problems.append(f"{method}: @Case says {args} -> {outcome}, "
                                    f"observed {row[f'{prefix}_outcome']}")


def main():
    expected = json.loads(EXPECTED.read_text())
    problems = []
    check_verdicts(expected, problems)
    check_case_annotations(expected, problems)

    if problems:
        print("Answer key does NOT match the observations:")
        for p in problems:
            print("  -", p)
        sys.exit(1)

    for entry in expected["pairs"]:
        n = len(entry["counterexamples"])
        print(f"ok  {entry['pair']:<10} {entry['verdict']:<10} {n} counterexample(s)")
    print("Answer key and @Case annotations agree with the observations.")


if __name__ == "__main__":
    main()
