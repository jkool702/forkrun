#!/usr/bin/env python3
"""Run the forkrun Python benchmark suite (W-PY11).

Usage:
    python3 python/benchmarks/run_all.py [--scale small|medium|large]
                                         [--trials N] [--csv PATH]
                                         [--filter PATTERN] [--list]

Requires the built substrate (make -f Makefile.substrate python-substrate).
Scales: small (100k lines, smoke), medium (1M, default), large (10M, manual).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))

from bench_harness import BenchContext, SCALES, format_table, write_csv  # noqa: E402

try:
    import forkrun  # noqa: E402
except ImportError as exc:
    sys.stderr.write("cannot import forkrun: %s\n"
                     "run from the repo root after building the substrate:\n"
                     "  make -f Makefile.substrate python-substrate\n"
                     % exc)
    sys.exit(2)

import bench_baselines  # noqa: E402
import bench_fault  # noqa: E402
import bench_memory  # noqa: E402
import bench_niches  # noqa: E402
import bench_throughput  # noqa: E402

BENCHMARKS = {
    "python_noop": bench_throughput.bench_python_identity,
    "python_transform": bench_throughput.bench_python_transform,
    "python_compute": bench_throughput.bench_python_compute,
    "spawn_cat": bench_throughput.bench_spawn_cat,
    "spawn_tr": bench_throughput.bench_spawn_tr,
    "plugin_process": bench_throughput.bench_plugin_process,
    "streaming_overhead": bench_throughput.bench_streaming_overhead,
    "ordered_vs_unordered": bench_throughput.bench_ordered_vs_unordered,
    "batch_size_effect": bench_throughput.bench_batch_size_effect,
    "rss_no_output": bench_memory.bench_rss_no_output,
    "rss_output_sized": bench_memory.bench_rss_output_sized,
    "rss_streaming_bounded": bench_memory.bench_rss_streaming_bounded,
    "rss_amplification": bench_memory.bench_rss_amplification,
    "rss_in_process": bench_memory.bench_rss_in_process,
    "fault_overhead": bench_fault.bench_healthy_vs_faulty,
    "serial_python": bench_baselines.bench_serial_python,
    "serial_upper": bench_baselines.bench_serial_upper,
    "mp_pool": bench_baselines.bench_mp_pool,
    "forkrun_vs_baselines": bench_baselines.bench_forkrun_vs_baselines,
    "jsonl_ingest": bench_niches.bench_jsonl_ingest,
    "transform_filter": bench_niches.bench_transform_filter,
    "aggregation": bench_niches.bench_aggregation,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=["small", "medium", "large"],
                        default="medium")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--csv", type=str, default=None)
    parser.add_argument("--filter", type=str, default=None)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for name in sorted(BENCHMARKS):
            print("  %s" % name)
        return 0

    ctx = BenchContext(scale=args.scale, trials=args.trials)

    print("forkrun Python Benchmark Suite")
    print("Scale: %s (%s lines)" % (args.scale, f"{SCALES[args.scale]:,}"))
    print("Trials: %d (median reported)" % args.trials)
    print("Hardware: %s" % ctx.hardware)
    try:
        print("Engine: %s" % forkrun.__engine_version__)
    except AttributeError:
        pass
    print(flush=True)

    to_run = BENCHMARKS
    if args.filter:
        to_run = {k: v for k, v in BENCHMARKS.items() if args.filter in k}
        if not to_run:
            print("no benchmarks match %r" % args.filter)
            return 1

    failed = []
    try:
        for name, fn in to_run.items():
            print("Running: %s..." % name, end=" ", flush=True)
            try:
                fn(ctx)
                print("done")
            except Exception as exc:  # noqa: BLE001
                print("FAILED: %s" % exc)
                failed.append(name)
    finally:
        ctx.cleanup()

    print()
    print(format_table(ctx.results))
    print()
    print("Hardware: %s" % ctx.hardware)

    if args.csv:
        write_csv(ctx.results, args.csv)
        print("CSV written to: %s" % args.csv)
    if failed:
        print("failed: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
