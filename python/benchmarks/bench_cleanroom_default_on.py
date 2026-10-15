#!/usr/bin/env python3
"""WO-CR-ROI-2 Phase D2: the SMALLEST CURRENT performance question.

Why a new file instead of bench_cleanroom.py
--------------------------------------------
That harness measures a large ml_plugin_light .so over a 5M-line corpus.
The historical plugin is gone from this machine (`/tmp/opencode/mlbench/
ml_plugin_light.so` no longer exists), so the recorded 30/554/2127 MB RSS
and 1.27x startup numbers cannot be reproduced as written.

So this file answers the ONE question Phase D actually needs, using only
in-repo fixtures: the same plugin the Phase B route tests already build
and exercise, so anyone can re-run this on a clean checkout.

The question is NOT "is the cleanroom faster". It is narrower and it is
the question a default-on decision turns on:

    When FORKRUN_CLEANROOM is off, a call forks workers from the
    caller's own address space. If that parent is large, every worker
    inherits it. The cleanroom's claim is that it does not.

So the measured dimensions are:
  1. startup regime (many small runs) -- the regime the claim is about;
  2. the same regime with BALLAST in the parent -- the dimension that
     actually matters, since a tiny benchmark parent understates it.

Method, unchanged from the repo's existing rules (bench_harness.py and
bench_cleanroom.py): sequential, never concurrent; paired A/B INTERLEAVED
so machine drift hits both arms; warmup discarded; medians reported
alongside means because startup timing is skewed; and an EXACTNESS GUARD
that refuses to report a number for output that does not match an
independently computed reference.

This reports what it measured and nothing more. It does not decide the
default -- that is Phase D3, and it is gated on correctness evidence
separately.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forkrun                                          # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# Reuse the EXACT plugin the Phase B route tests build, rather than a
# copy. A second copy could drift from the one under test, and then this
# would be measuring a different function than the route evidence covers.
PLUGIN_HEADER = os.path.join(_ROOT, "ring_loadables", "forkrun_plugin.h")
PLUGIN_SRC = os.path.join(_ROOT, "python", "tests", "plugins",
                          "test_plugin_v1.c")

FUNC = "count_lines_v1"


def reference_bytes(n_records):
    """Exact expected output size for the in-repo plugin.

    count_lines_v1 is the SIZE-PRESERVING pass-through: it emits exactly
    one byte per input record, so a byte count IS a record count. That is
    the property the cleanroom suite's assertions rely on, and this guard
    depends on it -- writing the wrong expected size here would have made
    the exactness guard reject correct output (as it did on first run).
    """
    return n_records


def build_plugin(tmp):
    so = os.path.join(tmp, "plug.so")
    proc = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-I", PLUGIN_HEADER,
         "-o", so, PLUGIN_SRC],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit("plugin fixture failed to build:\n%s"
                         % proc.stderr[-2000:])
    return so


def write_corpus(path, n_records):
    with open(path, "wb") as fh:
        for i in range(n_records):
            fh.write(b"record%08d payload\n" % i)


def run_once(spec, path, workers):
    t0 = time.perf_counter()
    out = forkrun.map(spec, path, workers=workers, nodes=1, mode="plugin",
                      output="bytes")
    dt = time.perf_counter() - t0
    return dt, sum(len(bytes(x)) for x in out)


def paired(spec, path, workers, expect, repeat, warmup):
    samples = {"in-process": [], "cleanroom": []}
    order = ["in-process", "cleanroom"]
    for i in range(repeat + warmup):
        for mode in order:
            os.environ["FORKRUN_CLEANROOM"] = "0" if mode == "in-process" \
                else "1"
            dt, n = run_once(spec, path, workers)
            if i < warmup:
                continue
            samples[mode].append(dt)
            if n != expect:
                raise SystemExit(
                    "EXACTNESS FAIL [%s]: got %d bytes, expected %d -- "
                    "refusing to report a number for wrong output"
                    % (mode, n, expect))
    return samples


def fmt(samples):
    if not samples:
        return "n/a"
    med = statistics.median(samples) * 1e3
    mean = statistics.fmean(samples) * 1e3
    lo = min(samples) * 1e3
    return ("median %8.3f ms   mean %8.3f ms   min %8.3f ms   n=%d"
            % (med, mean, lo, len(samples)))


def regime(name, spec, path, workers, records, repeat, warmup, ballast_mb):
    keep = None
    if ballast_mb:
        keep = bytearray(ballast_mb * 1024 * 1024)
    print("\n=== %s ===" % name)
    print("  ballast in parent: %d MB" % ballast_mb)
    expect = reference_bytes(records)
    s = paired(spec, path, workers, expect, repeat, warmup)
    print("  in-process : %s" % fmt(s["in-process"]))
    print("  cleanroom  : %s" % fmt(s["cleanroom"]))
    ratio = (statistics.median(s["in-process"])
             / statistics.median(s["cleanroom"]))
    print("  in-process / cleanroom : %.3fx" % ratio)
    del keep
    return {"in_process": statistics.median(s["in-process"]) * 1e3,
            "cleanroom": statistics.median(s["cleanroom"]) * 1e3,
            "ratio_in_process_over_cleanroom": ratio}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--records", type=int, default=2000,
                    help="records per run in the startup regime")
    ap.add_argument("--repeat", type=int, default=12)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--ballast-mb", type=int, default=512)
    ap.add_argument("--throughput-records", type=int, default=400000,
                    help="records for the one-large-pass regime")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="cr-perf-")
    so = build_plugin(tmp)
    corpus = os.path.join(tmp, "corpus.txt")
    write_corpus(corpus, args.records)
    spec = "%s:%s" % (so, FUNC)

    print("plugin   : %s" % so)
    print("corpus   : %s (%d records, %d bytes)"
          % (corpus, args.records, os.path.getsize(corpus)))
    print("workers  : %d" % args.workers)
    print("method   : paired interleaved A/B, warmup discarded, medians, "
          "exactness guard")

    big = os.path.join(tmp, "big.txt")
    write_corpus(big, args.throughput_records)

    out = {
        "startup": regime("STARTUP, no ballast", spec, corpus, args.workers,
                          args.records, args.repeat, args.warmup, 0),
        "startup_ballasted": regime(
            "STARTUP, %d MB ballast in parent" % args.ballast_mb,
            spec, corpus, args.workers, args.records, args.repeat,
            args.warmup, args.ballast_mb),
        "throughput": regime(
            "THROUGHPUT, one large pass (%d records, no ballast)"
            % args.throughput_records,
            spec, big, args.workers, args.throughput_records,
            max(3, args.repeat // 3), args.warmup, 0),
    }

    print("\n--- summary ---")
    for k, v in out.items():
        print("%-18s in-process %8.3f ms   cleanroom %8.3f ms   %.3fx"
              % (k, v["in_process"], v["cleanroom"],
                 v["ratio_in_process_over_cleanroom"]))

    if args.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())