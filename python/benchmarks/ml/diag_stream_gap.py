#!/usr/bin/env python3
"""Why is stream() ~20% slower than map() over the same pipe? (#1)

Known: light/plugin, 28 workers, all warm, bare consumers.
    map   bytes  7.68M rec/s
    map   view   9.72M rec/s
    stream       6.14M rec/s

stream() yields ONE joined bytes blob per BATCH; map() collects and returns
per-record results. So there are two candidate costs, and they are not
mutually exclusive:

  (a) ENGINE: stream has no finished collection file to map, so it must
      build a contiguous blob per batch. map(output="view") maps the
      engine's buffer instead and copies nothing. That is a real
      per-batch memcpy that map-with-views never pays.
  (b) CONSUMER: with map() the parent collects into a list and you iterate
      afterwards -- one append per record, then done. With stream() the
      parent is running a Python generator loop CONCURRENTLY with the
      drain, so 28 workers and the consumer contend for the GIL.

This splits them by measuring parent CPU against child CPU, and by
removing the orderer, which is the one thing that differs in the engine
between the two shapes.

Run: python3 diag_stream_gap.py [variant] [trials]
"""
import os
import resource
import statistics
import sys
import time

sys.path.insert(0, "/mnt/ramdisk/forkrun/python")
sys.path.insert(0, "/mnt/ramdisk/forkrun/python/benchmarks/ml")

import forkrun  # noqa: E402

WORK = "/tmp/opencode/mlbench"
CORPORA = {
    "light":  "/mnt/ramdisk/numa1/ml/light_5M.jsonl",
    "medium": "/mnt/ramdisk/numa1/ml/medium_5M.jsonl",
    "heavy":  "/tmp/opencode/heavy_5M.jsonl",
}
EXPECT = {"light": 5000000, "medium": 4997892, "heavy": 4997982}
WORKERS = 28


def producer(path):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        rc = 0
        try:
            os.close(r)
            with open(path, "rb") as src, os.fdopen(w, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
        except BaseException:
            rc = 1
        finally:
            os._exit(rc)
    os.close(w)
    return r, pid


def _cpu():
    """(user, sys) for SELF and CHILDREN separately.

    The split is the whole point: "user" is Python work in the consumer
    loop, "sys" is the parent spinning in poll/epoll while it waits. Both
    land in the parent's CPU bill but only one is avoidable by changing
    what the parent does.
    """
    s = resource.getrusage(resource.RUSAGE_SELF)
    c = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (s.ru_utime, s.ru_stime, c.ru_utime, c.ru_stime)


def run_map(path, payload, output):
    r, pid = producer(path)
    try:
        p0 = _cpu()
        t0 = time.perf_counter()
        out = forkrun.map(payload, r, mode="plugin", workers=WORKERS,
                          nodes="auto", orchestrator=True, order="index",
                          output=output)
        dt = time.perf_counter() - t0
        p1u, p1s, c1u, c1s = _cpu()
        n = len(out)
        del out
    finally:
        os.close(r)
        os.waitpid(pid, 0)
    return dt, n, (p1u - p0[0], p1s - p0[1], c1u - p0[2], c1s - p0[3])


def run_stream(path, payload, order="index"):
    r, pid = producer(path)
    try:
        p0 = _cpu()
        t0 = time.perf_counter()
        n = 0
        for _out in forkrun.stream(payload, r, workers=WORKERS,
                                   streaming=True, nodes="auto",
                                   order=order, mode="plugin"):
            n += 1                      # one item per BATCH
        dt = time.perf_counter() - t0
        p1u, p1s, c1u, c1s = _cpu()
    finally:
        os.close(r)
        os.waitpid(pid, 0)
    return dt, n, (p1u - p0[0], p1s - p0[1], c1u - p0[2], c1s - p0[3])


def report(label, dt, n, cpu, expect):
    pu, ps, cu, cs = cpu
    print("  %-26s %6.2fs %6.2fM rec/s | parent user %5.2fs sys %5.2fs"
          " | child user %5.2fs sys %5.2fs | batches %d"
          % (label, dt, expect / dt / 1e6, pu, ps, cu, cs, n))


def main(argv):
    variant = argv[0] if argv else "light"
    trials = int(argv[1]) if len(argv) > 1 else 3
    path = CORPORA[variant]
    expect = EXPECT[variant]
    payload = "%s/ml_plugin_%s.so:ml_process_%s" % (WORK, variant, variant)
    print("variant=%s workers=%d  (parentCPU is the consumer loop; "
          "childCPU is workers+scanner)\n" % (variant, WORKERS))

    cases = [
        ("map bytes", lambda: run_map(path, payload, "bytes")),
        ("map view", lambda: run_map(path, payload, "view")),
        ("stream order=index", lambda: run_stream(path, payload, "index")),
        ("stream order=none", lambda: run_stream(path, payload, "none")),
    ]
    # warm everything once first
    for _lbl, fn in cases:
        fn()
    acc = {}
    for lbl, fn in cases:
        rows = [fn() for _ in range(trials)]
        dt = statistics.median(r[0] for r in rows)
        n = rows[0][1]
        cpu = [statistics.median(r[2][k] for r in rows) for k in range(4)]
        report(lbl, dt, n, cpu, expect)
        acc[lbl] = dt

    print()
    base = acc["map bytes"]
    for lbl in acc:
        print("  %-30s %+.1f%% vs map bytes"
              % (lbl, 100 * (acc[lbl] - base) / base))
    print()
    m = acc["map view"]
    print("  map view is %.2fx map bytes  (zero-copy dividend)"
          % (base / m))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))