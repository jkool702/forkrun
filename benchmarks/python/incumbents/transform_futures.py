#!/usr/bin/env python3
"""Stage 0 incumbent (context row): per-record transform via futures.

Same workload/contract as transform_pool.py (calibrated burn, verbatim
re-emit of the consumed prefix).

Usage: transform_futures.py INPUT OUTPREFIX --cost-us C [--chunksize K]
       [--budget-s S] [--workers N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as fut
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import Hasher, emit, now

CAL_OPS = 200_000


def _ops_per_us() -> float:
    x = 1.000001
    t0 = time.perf_counter()
    for _ in range(CAL_OPS):
        x = x * 1.000001 + 0.5
    dt = time.perf_counter() - t0
    if x == 0.0:
        print("unreachable", file=sys.stderr)
    return CAL_OPS / max(dt * 1e6, 1e-9)


def burn(args: tuple[str, int]) -> str:
    line, ops = args
    x = 1.000001
    for _ in range(ops):
        x = x * 1.000001 + 0.5
    if x == 0.0:
        return "unreachable"
    return line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outprefix")
    ap.add_argument("--cost-us", type=float, required=True)
    ap.add_argument("--chunksize", type=int, default=100)
    ap.add_argument("--budget-s", type=float, default=25.0)
    ap.add_argument("--workers", type=int, default=mp.cpu_count())
    args = ap.parse_args()
    with open(args.input, "r", encoding="ascii") as fh:
        all_lines = fh.read().splitlines()
    n = int(min(len(all_lines), max(1000, (args.budget_s * 1e6) / args.cost_us)))
    lines = all_lines[:n]
    in_bytes = sum(len(ln) + 1 for ln in lines)
    ops = max(1, int(round(_ops_per_us() * args.cost_us)))
    t0 = now()
    with fut.ProcessPoolExecutor(max_workers=args.workers) as ex:
        out = list(ex.map(burn, ((ln, ops) for ln in lines),
                          chunksize=args.chunksize))
    h = Hasher()
    opath = f"{args.outprefix}_c{args.cost_us:g}_k{args.chunksize}.out"
    with open(opath, "w", encoding="ascii") as fh:
        for ln in out:
            fh.write(ln)
            fh.write("\n")
            h.update((ln + "\n").encode("ascii"))
    emit("per-record-transform",
         f"futures-w{args.workers}-c{args.chunksize}",
         in_bytes, now() - t0, h.hexdigest(),
         notes=f"cost_us={args.cost_us:g} items={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
