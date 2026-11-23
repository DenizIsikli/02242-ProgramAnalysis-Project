"""Checks the corpus answer key against the reference observations.

Checks, all independent of our analyser:
  1. pairs.txt and expected.json agree on the corpus and domains, with the
     required pair count and fault categories.
  2. evaluation/expected/expected.json (hand-written verdicts and counterexamples)
     agrees with evaluation/observations/*.csv (real JVM runs).
     Observations cover each domain exactly once.
  3. Every @Case annotation in Refactorings.java that falls inside the declared
     domain agrees with the observed outcome.

Run after `bash evaluation/observe.sh`:   python3 evaluation/check_expected.py
Exits with status 1 and prints the problems if anything disagrees.
"""

import csv
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "evaluation" / "expected" / "expected.json"


def load_observations(pair, *, root=ROOT):
    """Returns (parameter names, rows) where each row maps column -> value."""
    with open(root / "evaluation/observations" / f"{pair}.csv", newline="") as f:
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


def check_manifest(expected, problems, *, root=ROOT):
    """Keep the declared corpus, answer key and category requirements in sync."""
    manifest = {}
    for line in (root / "evaluation/pairs.txt").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, low, high = line.split()
        if name in manifest:
            problems.append(f"{name}: duplicate pair in pairs.txt")
        manifest[name] = (int(low), int(high))
    names = [entry["pair"] for entry in expected["pairs"]]
    if len(set(names)) != len(names):
        problems.append("duplicate pair in expected.json")
    if set(manifest) != set(names):
        problems.append("pairs.txt and expected.json declare different pairs")
    categories = Counter(entry["category"] for entry in expected["pairs"])
    if len(names) < 10 or categories["return-only"] < 3 or categories["exception"] < 2:
        problems.append(
            "corpus requires >=10 pairs, >=3 return-only and >=2 exception faults"
        )
    if set(categories) - {"preserving", "return-only", "exception"}:
        problems.append("unrecognised corpus category")
    for entry in expected["pairs"]:
        name = entry["pair"]
        if name not in manifest:
            continue
        low, high = manifest[name]
        if low > high or any(
            bounds != [low, high] for bounds in entry["domain"].values()
        ):
            problems.append(f"{name}: domain disagrees with pairs.txt")
        descriptor = "(" + "I" * len(entry["domain"]) + ")I"
        for field, suffix in (("method", ""), ("edited", "_edited")):
            if entry[field] != f"jpamb.cases.Refactorings.{name}{suffix}:{descriptor}":
                problems.append(f"{name}: incorrect {field} method ID")
        verdict = "preserved" if entry["category"] == "preserving" else "changed"
        if entry["verdict"] != verdict:
            problems.append(f"{name}: category disagrees with verdict")


def check_verdicts(expected, problems, *, root=ROOT):
    for entry in expected["pairs"]:
        pair = entry["pair"]
        params, rows = load_observations(pair, root=root)

        if list(entry["domain"]) != params:
            problems.append(
                f"{pair}: domain names {list(entry['domain'])} != CSV columns {params}"
            )

        wanted = set(
            itertools.product(
                *[range(lo, hi + 1) for lo, hi in entry["domain"].values()]
            )
        )
        actual = [tuple(int(row[p]) for p in params) for row in rows]
        if len(set(actual)) != len(actual) or set(actual) != wanted:
            problems.append(
                f"{pair}: observations do not cover the domain exactly once"
            )
        observed = {}
        for row in rows:
            original, edited = side(row, "orig"), side(row, "edited")
            same = original == edited
            if row["same"] != ("yes" if same else "no"):
                problems.append(f"{pair}: incorrect CSV same flag")
            if entry["category"] == "return-only" and (
                original["outcome"] != "ok" or edited["outcome"] != "ok"
            ):
                problems.append(f"{pair}: return-only fault has an exceptional outcome")
            if not same:
                key = tuple(int(row[p]) for p in params)
                observed[key] = {
                    "original": original,
                    "edited": edited,
                }
        if entry["category"] == "exception" and not any(
            c["original"]["outcome"] != c["edited"]["outcome"]
            for c in observed.values()
        ):
            problems.append(f"{pair}: exception fault has no outcome difference")

        verdict = "changed" if observed else "preserved"
        if entry["verdict"] != verdict:
            problems.append(
                f"{pair}: expected verdict {entry['verdict']!r}, observed {verdict!r}"
            )

        recorded = {
            tuple(c["input"]): {"original": c["original"], "edited": c["edited"]}
            for c in entry["counterexamples"]
        }
        if len(recorded) != len(entry["counterexamples"]):
            problems.append(f"{pair}: duplicate counterexample input")
        for key in observed.keys() - recorded.keys():
            problems.append(
                f"{pair}: input {key} differs but is not listed as a counterexample"
            )
        for key in recorded.keys() - observed.keys():
            problems.append(
                f"{pair}: listed counterexample {key} does not actually differ"
            )
        for key in recorded.keys() & observed.keys():
            if recorded[key] != observed[key]:
                problems.append(
                    f"{pair}: counterexample {key} recorded as {recorded[key]}, "
                    f"observed {observed[key]}"
                )


CASE_RE = re.compile(r'@Case\("\(([^)]*)\)\s*->\s*([^"]+)"\)')
METHOD_RE = re.compile(r"public static \w+ (\w+)\(")


def check_case_annotations(expected, problems, *, root=ROOT):
    """Every in-domain @Case must match what the JVM actually did."""
    pending = []
    annotations = {}
    for line in (root / "cases/jpamb/cases/Refactorings.java").read_text().splitlines():
        if m := CASE_RE.search(line):
            args = tuple(int(a) for a in m.group(1).split(",") if a.strip())
            pending.append((args, m.group(2).strip()))
        elif m := METHOD_RE.search(line):
            annotations[m.group(1)] = pending
            pending = []

    for entry in expected["pairs"]:
        pair = entry["pair"]
        params, rows = load_observations(pair, root=root)
        by_input = {tuple(int(r[p]) for p in params): r for r in rows}
        for method, prefix in ((pair, "orig"), (pair + "_edited", "edited")):
            for args, outcome in annotations.get(method, []):
                row = by_input.get(args)
                if row is None:
                    problems.append(
                        f"{method}: @Case input {args} is outside the declared domain"
                    )
                elif row[f"{prefix}_outcome"] != outcome:
                    problems.append(
                        f"{method}: @Case says {args} -> {outcome}, "
                        f"observed {row[f'{prefix}_outcome']}"
                    )


def main():
    expected = json.loads(EXPECTED.read_text())
    problems = []
    check_manifest(expected, problems)
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
