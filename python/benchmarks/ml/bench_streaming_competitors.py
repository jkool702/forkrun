#!/usr/bin/env python3
"""Competitor-only streaming rows, one corpus per process.

Two reasons this exists instead of just running bench_streaming_pipe:

 1. forkrun's streaming numbers come from the 48-cell grid (map over a
    pipe), per the table design -- so there is no reason to re-measure
    forkrun here and risk a third methodology.
 2. MEASUREMENT ISOLATION. Running forkrun's big ingress memfd and the
    pool benchmarks in the same process sequence starves the page cache:
    a single combined run decayed ~2.5x from the first corpus to the
    last, with EVERY row falling together. One corpus per process, and
    only the pool systems, keeps the competitor numbers comparable to
    the grid's.

Exactness is a separate untimed pass; the timed pass uses the cheap
consumer so benchmark scaffolding is never inside the clock.
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench_streaming_pipe as B  # noqa: E402

COMPETITORS = [
    ("ProcessPoolExecutor (pipe)", B.bench_executor_stream),
    ("multiprocessing.Pool (pipe)", B.bench_pool_stream),
]


def main(argv):
    variant = argv[0]
    path = B.CORPORA[variant]
    exp = B.EXPECTED[variant]
    in_bytes = os.path.getsize(path)
    out = {}
    for name, fn in COMPETITORS:
        try:
            fn(path, variant, exp, count=False)            # warmup
            times = []
            for _ in range(B.TRIALS):
                _n, dt = fn(path, variant, exp, count=False)
                times.append(dt)
            n, _ = fn(path, variant, exp, count=True)       # untimed
        except Exception as exc:                            # noqa: BLE001
            print("%s\t%s\tFAILED %s" % (variant, name, exc), flush=True)
            continue
        if n != exp:
            print("%s\t%s\tFAIL exactness %d != %d"
                  % (variant, name, n, exp), flush=True)
            continue
        med = statistics.median(times)
        print("%s\t%s\t%.4f\t%.0f\t%d"
              % (variant, name, med, exp / med / 1e6, exp), flush=True)
        out[name] = {"sec": med, "rec_s": exp / med,
                     "mb_s": in_bytes / med / 1e6}
    with open("/tmp/opencode/stream_competitors_%s.json" % variant, "w") as fh:
        json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))