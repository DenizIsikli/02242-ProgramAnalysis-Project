"""Run the region-based pair checker over the corpus and compare with the answer key.

Usage (from the repo root, needs target/decompiled/jpamb/cases/Refactorings.json):

    PYTHONPATH=solutions/static/src:src python solutions/static/src/check_pairs.py

The analyser itself never reads expected.json; only this evaluation script does, after the
verdict is computed. A hybrid verdict that contradicts the answer key is reported as WRONG
(`changed` for a preserved pair, `preserved` for a changed pair); `unknown` is never wrong,
just incomplete.
"""

import json
import sys
from pathlib import Path

from abstractions import Interval, Region
from region_verdict import check_pair

import jpamb
from jpamb import jvm


def load_pairs(root: Path):
    key = json.loads((root / "evaluation" / "expected" / "expected.json").read_text())
    for p in key["pairs"]:
        domain = Region({n: Interval(lo, hi) for n, (lo, hi) in p["domain"].items()})
        yield (
            p["pair"],
            jvm.AbsMethodID.decode(p["method"]),
            jvm.AbsMethodID.decode(p["edited"]),
            domain,
            p["verdict"],
        )


def main(root: Path | None = None, return_check=None) -> int:
    root = root or Path.cwd()
    suite = jpamb.Suite.from_workdir(root.resolve())
    bc = jpamb.Bytecode(suite, jpamb.utils.Effect(None))
    wrong = 0
    print(f"{'pair':<10} {'expected':<10} {'got':<10} {'certified':>9} {'witness'}")
    for name, a, b, domain, expected in load_pairs(root):
        v = check_pair(bc, a, b, domain, return_check)
        bad = (v.overall != "unknown") and v.overall != expected
        wrong += bad
        flag = "WRONG" if bad else ""
        print(
            f"{name:<10} {expected:<10} {v.overall:<10} {v.certified_coverage:>8.0%} "
            f"{v.witness or '-'} {flag}"
        )
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
