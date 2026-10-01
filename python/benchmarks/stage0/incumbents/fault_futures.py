#!/usr/bin/env python3
"""Stage 0 fault harness: ProcessPoolExecutor with a segfaulting item.

The mapped function SIGSEGVs on the marked ITEM index. The future for the
dead worker's chunk raises BrokenProcessPool; the executor is unusable
after. Documents completed count and usability.

Usage: fault_futures.py INPUT MARK [--workers N] [--timeout S]
Exit 0 always (outcome is data).
"""
from __future__ import annotations

import argparse
import concurrent.futures as fut
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
    completed = 0
    h = Hasher()
    action = ""
    try:
        with fut.ProcessPoolExecutor(max_workers=args.workers) as ex:
            for ln in ex.map(work, ((i, ln, args.mark) for i, ln in enumerate(lines)),
                             chunksize=args.chunksize, timeout=args.timeout):
                h.update((ln + "\n").encode())
                completed += 1
        action = "map completed (unexpected)"
        checksum = h.hexdigest()
    except Exception as exc:  # BrokenProcessPool (+ TimeoutError subclass paths)
        action = (f"{type(exc).__name__}: {exc}; executor shut down, "
                  "unusable after (fresh executor required)")
        checksum = "INCOMPLETE"
    elapsed = now() - t0
    print(json.dumps({
        "niche": "fault-isolation", "incumbent": "futures-segv",
        "input_items": len(lines), "mark": args.mark,
        "elapsed_s": round(elapsed, 3), "output_checksum": checksum,
        "fault_outcome": {"survived": completed == len(lines),
                           "completed": completed, "total": len(lines),
                           "action": action,
                           "pool_usable_after": False},
        "notes": "item-granularity fault; compare vs forkrun batch-granularity",
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
