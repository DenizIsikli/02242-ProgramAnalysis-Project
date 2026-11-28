"""Variance of the evaluation: random-testing seeds and repeated timings.

    PYTHONPATH=solutions/static/src:src python evaluation/seed_stats.py [--seeds 20] [--repeats 5]

Two things the single run of `ablation.py` cannot show:

1. How often seeded random testing finds a difference at all. Only pairs that really differ
   are listed, because on equal pairs random testing can only answer `unknown`. On the small
   domain the exact fraction of differing inputs is known, so the table also gives the
   probability that 1000 random inputs hit one.
2. How stable the timings of the hybrid and of Z3 alone are: median and range over
   `--repeats` runs.
"""

import argparse
import statistics
import sys
import time
from functools import partial
from pathlib import Path

from ablation import ROOT, domain, pairs
from baselines import exhaustive, seed_statistics, z3_only
from region_verdict import check_pair, region_size
from symbolic import make_return_checker

import jpamb


def timed(fn, repeats: int) -> list[float]:
    out = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        out.append((time.perf_counter() - started) * 1000)
    return out


def fmt(t: list[float]) -> str:
    return f"{statistics.median(t):.0f} [{min(t):.0f}, {max(t):.0f}]"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root)
    bc = jpamb.Bytecode(
        jpamb.Suite.from_workdir(root.resolve()), jpamb.utils.Effect(None)
    )

    detect_rows, timing_rows = [], []
    for name, a, b in pairs(root):
        for lo, hi, exact in ((-3, 3, True), (-1000, 1000, False)):
            dom = domain(a, lo, hi)
            tag = f"[{lo},{hi}]^{len(a.extension.params)}"
            hybrid = check_pair(bc, a, b, dom, make_return_checker(bc, a, b))
            p_hit = None
            if exact:
                differs, count, _ = exhaustive(bc, a, b, dom)
                if differs:
                    p_hit = 1 - (1 - count / region_size(dom)) ** args.budget
            else:
                differs = hybrid.overall == "changed"
            if differs:
                s = seed_statistics(bc, a, b, dom, args.seeds, args.budget)
                detect_rows.append((name, tag, s, p_hit))
            hyb = partial(
                check_pair, bc, a, b, dom, return_check=make_return_checker(bc, a, b)
            )
            t_hyb = timed(hyb, args.repeats)
            t_z3 = timed(partial(z3_only, bc, a, b, dom), args.repeats)
            timing_rows.append((name, tag, t_hyb, t_z3))

    print(f"\n### random testing over {args.seeds} seeds, budget {args.budget}")
    print("| pair | domain | seeds that found it | median runs | P(hit) exact |")
    print("|---|---|---|---|---|")
    for name, tag, s, p in detect_rows:
        ph = f"{p:.1%}" if p is not None else "n/a"
        print(
            f"| {name} | {tag} | {s['detected']}/{s['seeds']} | "
            f"{s['median_runs'] or '-'} | {ph} |"
        )
    total = sum(r[2]["seeds"] for r in detect_rows)
    found = sum(r[2]["detected"] for r in detect_rows)
    print(
        f"\nOverall: {found}/{total} seeded runs found a difference "
        f"({found / total:.0%}) over {len(detect_rows)} differing pair/domain runs."
    )

    print(f"\n### timings over {args.repeats} repeats (ms: median [min, max])")
    print("| pair | domain | hybrid | z3only |")
    print("|---|---|---|---|")
    for name, tag, th, tz in timing_rows:
        print(f"| {name} | {tag} | {fmt(th)} | {fmt(tz)} |")
    for label, i in (("hybrid", 2), ("z3only", 3)):
        t = [sum(r[i][k] for r in timing_rows) for k in range(args.repeats)]
        print(
            f"\nTotal {label}: median {statistics.median(t) / 1000:.2f} s "
            f"[{min(t) / 1000:.2f}, {max(t) / 1000:.2f}] over all {len(timing_rows)} runs."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
