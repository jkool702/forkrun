#!/usr/bin/env python3
"""Stage 0 fault harness: multiprocessing.Pool with a segfaulting item.

The mapped function SIGSEGVs (os.kill SIGSEGV) on the marked ITEM index.
Pool.map is awaited with a timeout: a dead worker's chunk never resolves,
so the documented question is whether map returns, raises, or hangs.

Usage: fault_pool.py INPUT MARK [--workers N] [--timeout S]
Prints one JSON line: ajoute "fault_outcome" describing pool usability,
completed count, and recovery action. Exit 0 always (outcome is data).
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import Hasher, now
import json


def work(args: tuple[int, str, int]) -> str:
    idx, line, mark = args
    if idx == mark:
        os.kill(os.getpid(), signal.SIGSEGV)
        time.sleep(60)
    return line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--mark", type=int, default=50000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--chunksize", type=int, default=100)
    args = ap.parse_args()
    with open(args.input) as fh:
        lines = fh.read().splitlines()
    t0 = now()
    outcome: dict = {"survived": None, "completed": 0, "total": len(lines),
                     "action": "", "pool_usable_after": None}
    try:
        with mp.Pool(processes=args.workers) as pool:
            async_res = pool.map_async(work,
                                       [(i, ln, args.mark) for i, ln in enumerate(lines)],
                                       chunksize=args.chunksize)
            out = async_res.get(timeout=args.timeout)
        outcome["survived"] = True
        outcome["completed"] = len(out)
        outcome["action"] = "map returned"
        h = Hasher()
        for ln in out:
            h.update((ln + "\n").encode())
        checksum = h.hexdigest()
    except mp.TimeoutError:
        outcome["survived"] = False
        outcome["action"] = f"map_async hung > {args.timeout}s (dead worker chunk never resolves); pool terminated"
        checksum = "INCOMPLETE"
    outcome["pool_usable_after"] = False
    outcome["pool_usable_after_note"] = ("fresh Pool required; faulted pool "
                                         "was terminated, not reused")
    elapsed = now() - t0
    print(json.dumps({
        "niche": "fault-isolation", "incumbent": "mp-pool-segv",
        "input_items": len(lines), "mark": args.mark,
        "elapsed_s": round(elapsed, 3), "output_checksum": checksum,
        "fault_outcome": outcome,
        "notes": "item-granularity fault; compare vs forkrun batch-granularity",
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
