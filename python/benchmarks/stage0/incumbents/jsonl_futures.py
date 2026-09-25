#!/usr/bin/env python3
"""Stage 0 incumbent (context row): JSONL ingestion via ProcessPoolExecutor.

Same workload and output contract as jsonl_pool.py (verbatim re-emit;
checksum must equal input sha256).

Usage: jsonl_futures.py INPUT OUTPUT [--workers N] [--chunksize C]
"""
from __future__ import annotations

import argparse
import concurrent.futures as fut
import json
import multiprocessing as mp
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import Hasher, emit, now


def parse_line(line: str) -> str:
    obj = json.loads(line)
    if not isinstance(obj["id"], int) or "user" not in obj:
        raise ValueError("bad record")
    return line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--workers", type=int, default=mp.cpu_count())
    ap.add_argument("--chunksize", type=int, default=100)
    args = ap.parse_args()
    t0 = now()
    with open(args.input, "r", encoding="ascii") as fh:
        lines = fh.read().splitlines()
    in_bytes = os.path.getsize(args.input)
    with fut.ProcessPoolExecutor(max_workers=args.workers) as ex:
        out_lines = list(ex.map(parse_line, lines, chunksize=args.chunksize))
    h = Hasher()
    with open(args.output, "w", encoding="ascii") as fh:
        for ln in out_lines:
            fh.write(ln)
            fh.write("\n")
            h.update((ln + "\n").encode("ascii"))
    emit("jsonl-ingest", f"futures-w{args.workers}-c{args.chunksize}",
         in_bytes, now() - t0, h.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
