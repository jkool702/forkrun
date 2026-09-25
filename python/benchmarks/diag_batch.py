"""Batch sizing diagnostic: are workers idle between batches? (W-PY41)

For map(), each output blob is one batch, so len(results) is the
batch count and sum-of-lines is the record count. Reports batches,
records/batch, per-batch wall time, and per-worker batch rate for
UMA vs NUMA at a given scale.

Idle-vs-saturated verdict needs aggregate CPU too (task-clock
from perf stat or /usr/bin/time -v alongside): avg_CPUs =
task_clock / elapsed. If avg_CPUs << workers while the hotspot
stays in the payload, workers idle between batches (batch
sizing). If avg_CPUs ~= workers, the pipeline is saturated and
the per-record cost is the ceiling.

Usage:
  python3 python/benchmarks/diag_batch.py
      --input /tmp/numa5m/ml_medium_5000000.jsonl
      --plugin /tmp/numa5m/ml_plugin_yyjson.so:ml_process_medium_yyjson
      [--workers 28] [--nodes 1,auto] [--trials 2]
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # python/ for forkrun

import forkrun  # noqa: E402


def count_lines(blobs):
    total = 0
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, str):
            b = b.encode()
        total += bytes(b).count(b"\n")
    return total


def run_once(input_path, payload, workers, nodes):
    t0 = time.perf_counter()
    results = forkrun.map(payload, input_path, mode="plugin",
                          workers=workers, nodes=nodes, order="index")
    dt = time.perf_counter() - t0
    n_batches = len(results)
    # Output records are one JSON line each (may lack trailing
    # newline per blob — junction undercount, see W-PY35 notes);
    # input line count is the ground truth for records.
    return dt, n_batches, results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",
                    default="/tmp/numa5m/ml_medium_5000000.jsonl")
    ap.add_argument("--plugin",
                    default="/tmp/numa5m/ml_plugin_yyjson.so"
                    ":ml_process_medium_yyjson")
    ap.add_argument("--workers", type=int, default=28)
    ap.add_argument("--nodes", default="1,auto")
    ap.add_argument("--trials", type=int, default=2)
    args = ap.parse_args(argv)

    with open(args.input, "rb") as fh:
        n_input_lines = sum(1 for _ in fh)
    input_bytes = os.path.getsize(args.input)
    nodes_list = [int(t) if t.strip().lstrip("-").isdigit() else t.strip()
                  for t in args.nodes.split(",") if t.strip()]
    print("input: %s (%.1fGB, %d lines)" % (
        args.input, input_bytes / 2**30, n_input_lines), flush=True)

    for nodes in nodes_list:
        best = None
        for _ in range(args.trials):
            dt, n_batches, results = run_once(
                args.input, args.plugin, args.workers, nodes)
            rate = n_input_lines / dt
            if best is None or rate > best[0]:
                best = (rate, dt, n_batches, results)
        rate, dt, n_batches, results = best
        n_out_lines = count_lines(results)
        rpb = n_input_lines / n_batches
        per_batch_us = dt / n_batches * 1e6
        print("nodes=%s: %.0f rec/s  batches=%d  rec/batch=%.0f  "
              "batches/s=%.0f  per-worker=%.1f batch/s  "
              "per-batch=%.0f us  out-lines=%d/%d" % (
                  nodes, rate, n_batches, rpb, n_batches / dt,
                  n_batches / dt / args.workers, per_batch_us,
                  n_out_lines, n_input_lines), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
