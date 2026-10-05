#!/usr/bin/env python3
"""W-CR1: end-to-end benchmark of the INTEGRATED cleanroom path.

Why this file exists
--------------------
The launcher's standalone microbenchmarks (2.49 ms spawn at 28 workers,
2.7 MB RSS) are NOT end-to-end numbers and must never reach the release
tables. They measure the launcher in isolation. This measures what a
caller of `forkrun.map()` actually gets.

Two regimes, because they answer different questions:

* THROUGHPUT -- one large pass over a corpus. The cleanroom's advantage
  here is small: with a big input the per-batch work dominates and the
  fixed startup saving is amortised away. This is the regime where a
  regression would hide.
* STARTUP -- many small runs. The cleanroom's whole claim is that
  workers must not fork from a large Python address space, so this is
  where it should show. Reported as per-run wall time.

Method rules this repo already imposes (bench_harness.py):
sequential, never concurrent; exact record counts asserted, not assumed;
paired A/B INTERLEAVED so machine drift hits both arms equally; warmup
discarded; medians reported alongside means because startup timing is
skewed.
"""
import argparse
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402


def _plugin_spec(args):
    if ":" in args.plugin:
        return args.plugin
    return "%s:%s" % (args.plugin, args.func)


def _corpus_lines(path):
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n


def _run_once(spec, path, args):
    t0 = time.perf_counter()
    out = forkrun.map(spec, path, workers=args.workers, nodes=1,
                      mode="plugin", output="bytes",
                      orchestrator=False)
    dt = time.perf_counter() - t0
    n = sum(len(bytes(x)) for x in out)
    return dt, n


def _reference_bytes(spec, path, args):
    """Output size from the in-process path.

    NOT the input size: the plugin transforms records, so output bytes
    != input bytes. The reference is what the two arms must AGREE with.
    """
    os.environ["FORKRUN_CLEANROOM"] = "0"
    _dt, n = _run_once(spec, path, args)
    return n


def _paired(spec, path, args, expect_bytes, passes=None):
    """Interleaved A/B. Returns {mode: [wall times]}."""
    samples = {"in-process": [], "cleanroom": []}
    counts = {}
    order = ["in-process", "cleanroom"]
    if args.first == "cleanroom":
        order.reverse()
    passes = args.repeat if passes is None else passes
    for i in range(passes + args.warmup):
        for mode in order:
            os.environ["FORKRUN_CLEANROOM"] = "0" if mode == "in-process" \
                else "1"
            dt, n = _run_once(spec, path, args)
            if i < args.warmup:
                continue                      # warmup, discarded
            samples[mode].append(dt)
            counts[mode] = n
            if n != expect_bytes:
                raise SystemExit(
                    "EXACTNESS FAIL [%s]: got %d bytes, expected %d -- "
                    "refusing to report a throughput number for wrong "
                    "output" % (mode, n, expect_bytes))
    return samples


def _fmt(samples):
    if not samples:
        return "n/a"
    return ("median %7.2f ms   mean %7.2f ms   min %7.2f ms   n=%d"
            % (statistics.median(samples) * 1e3,
               statistics.fmean(samples) * 1e3,
               min(samples) * 1e3, len(samples)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin",
                    default="/tmp/opencode/mlbench/ml_plugin_light.so")
    ap.add_argument("--func", default="ml_process_light")
    ap.add_argument("--corpus", default="/mnt/ramdisk/numa1/ml/light_5M.jsonl")
    ap.add_argument("--workers", type=int, default=28)
    ap.add_argument("--repeat", type=int, default=15,
                    help="paired passes (throughput)")
    ap.add_argument("--startup-passes", type=int, default=40,
                    help="paired passes on the small input (startup)")
    ap.add_argument("--startup-records", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--first", choices=["in-process", "cleanroom"],
                    default="in-process")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ballast-mb", type=int, default=0,
                    help="allocate this much in the PARENT before "
                         "running, to model a realistically bloated "
                         "Python process. This is the dimension that "
                         "matters most: the cleanroom exists because "
                         "workers must not fork from a large address "
                         "space, and a tiny benchmark parent understates "
                         "that benefit (and overstates the in-process "
                         "path's cost of nothing).")
    args = ap.parse_args()

    if args.ballast_mb > 0:
        _ballast = bytearray(args.ballast_mb * 1024 * 1024)
        for _i in range(0, len(_ballast), 4096):
            _ballast[_i] = 1

    spec = _plugin_spec(args)
    out = {"plugin": spec, "workers": args.workers}

    # ---- startup regime: small input, many runs -----------------------
    records = args.startup_records
    body = "".join(
        '{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,"et":"view",'
        '"dev":"ios","dur":5}\n' % i for i in range(records))
    fd, small = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    expect_small = _reference_bytes(spec, small, args)
    try:
        s = _paired(spec, small, args, expect_small,
                    passes=args.startup_passes)
        out["startup"] = {k: _fmt(v) for k, v in s.items()}
        out["startup_median_ms"] = {
            k: statistics.median(v) * 1e3 for k, v in s.items()}
        base = out["startup_median_ms"]["in-process"]
        out["startup_speedup"] = (
            base / out["startup_median_ms"]["cleanroom"]
            if out["startup_median_ms"]["cleanroom"] else None)
    finally:
        os.unlink(small)

    # ---- throughput regime: one large pass ---------------------------
    if os.path.exists(args.corpus):
        expect_big = _reference_bytes(spec, args.corpus, args)
        t = _paired(spec, args.corpus, args, expect_big)
        out["throughput"] = {k: _fmt(v) for k, v in t.items()}
        out["throughput_median_ms"] = {
            k: statistics.median(v) * 1e3 for k, v in t.items()}
        out["corpus_bytes"] = expect_big
        a = out["throughput_median_ms"]["in-process"]
        b = out["throughput_median_ms"]["cleanroom"]
        out["throughput_ratio"] = (a / b) if b else None
    else:
        out["throughput"] = "skipped (no corpus at %s)" % args.corpus

    if args.json:
        print(json.dumps(out, indent=2))
        return
    print("W-CR1 integrated cleanroom benchmark")
    print("  plugin  %s" % spec)
    print("  workers %d   node 1 (UMA)   orchestrator=False" % args.workers)
    try:
        with open("/proc/self/status") as fh:
            for ln in fh:
                if ln.startswith("VmRSS:"):
                    print("  parent RSS %s" % ln.split(":", 1)[1].strip())
    except OSError:
        pass
    if args.ballast_mb:
        print("  ballast     %d MB allocated in the parent" % args.ballast_mb)
    print()
    print("STARTUP  (%d records, %d paired passes, %d discarded)"
          % (records, args.startup_passes, args.warmup))
    for k in ("in-process", "cleanroom"):
        print("  %-11s %s" % (k, out["startup"][k]))
    if out.get("startup_speedup"):
        print("  -> cleanroom is %.2fx %s at startup"
              % (out["startup_speedup"],
                 "faster" if out["startup_speedup"] > 1 else "SLOWER"))
    print()
    print("THROUGHPUT  (%d paired passes)"
          % (args.repeat + args.warmup))
    if isinstance(out["throughput"], dict):
        for k in ("in-process", "cleanroom"):
            print("  %-11s %s" % (k, out["throughput"][k]))
        if out.get("throughput_ratio"):
            print("  -> cleanroom is %.2fx %s end-to-end"
                  % (out["throughput_ratio"],
                     "faster" if out["throughput_ratio"] > 1 else "SLOWER"))
    else:
        print("  %s" % out["throughput"])
    print()
    print("Record counts asserted exact on every pass; a mismatch aborts.")


if __name__ == "__main__":
    main()
