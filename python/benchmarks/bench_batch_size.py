"""Batch size sweep: the amortization study (W-PY17).

Python's per-batch overhead is (hypothesized) fixed regardless of batch
size. With adaptive batching the engine produces ~1000-line batches for
fast payloads; forced large batches should amortize the overhead — IF
dispatch is the bottleneck. If something else binds (claim/ack loop,
scan, parent collect), larger batches stall or regress, which is
equally important to know.

Also runnable standalone:
    python3 python/benchmarks/bench_batch_size.py [--scale S] [--trials N]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import (BenchContext, SCALES, format_table,  # noqa: E402
                           rss_mb, time_it)

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BATCH_SIZES = [None, 100, 500, 1000, 5000, 10000, 50000, 100000]


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _label(lines):
    return "lines=%d" % lines if lines else "adaptive"


def _map_noop(path, lines=None, workers=None):
    kw = {} if lines is None else {"lines": lines}
    return forkrun.map(lambda b: None, path,
                       workers=_nworkers() if workers is None else workers,
                       **kw)


def _map_upper(path, lines=None):
    kw = {} if lines is None else {"lines": lines}
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), **kw)


def _map_sum(path, lines=None):
    kw = {} if lines is None else {"lines": lines}
    return forkrun.map(lambda b: str(sum(b.data)).encode(), path,
                       workers=_nworkers(), **kw)


def _map_noop_bytes(path, bytes_):
    return forkrun.map(lambda b: None, path, workers=_nworkers(),
                       bytes=bytes_)


def bench_bytes_mode(ctx):
    """Byte-based batching (W-PY18): bash -b equivalent shapes.

    The scanner publishes fixed-size byte ranges; boundary detection
    cost differs from lines=N. Measures where byte mode lands relative
    to the lines=N sweep (same input, same workers).
    """
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for bs in [64 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024,
               4 * 1024 * 1024]:
        t, _ = time_it(lambda bs=bs: _map_noop_bytes(path, bs),
                       trials=ctx.trials)
        ctx.record("No-op bytes=%dKB" % (bs // 1024), "python", "map",
                   n / t, rss_mb(), "byte-mode batching")
    t, _ = time_it(lambda: _map_noop(path, lines=1000),
                   trials=ctx.trials)
    ctx.record("No-op lines=1000 (comparison)", "python", "map", n / t,
               rss_mb(), "line-mode, boundary detection")


def _count_batches(path, lines=None):
    """Exact batch count: b'' yields one (empty) record per batch."""
    kw = {} if lines is None else {"lines": lines}
    return len(forkrun.map(lambda b: b"", path, workers=_nworkers(), **kw))


def bench_noop_batch_sweep(ctx):
    """No-op: pure dispatch overhead at each batch size (the critical
    measurement — per-batch cost isolated from payload work)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in BATCH_SIZES:
        t, _ = time_it(lambda lines=lines: _map_noop(path, lines=lines),
                       trials=ctx.trials)
        ctx.record("No-op (%s)" % _label(lines), "python", "map", n / t,
                   rss_mb(), "")


def bench_upper_batch_sweep(ctx):
    """Upper: trivially-fast transform at each batch size."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in BATCH_SIZES:
        t, _ = time_it(lambda lines=lines: _map_upper(path, lines=lines),
                       trials=ctx.trials)
        ctx.record("Upper (%s)" % _label(lines), "python", "map", n / t,
                   rss_mb(), "")


def bench_sum_batch_sweep(ctx):
    """Sum: slightly more per-byte compute at each batch size."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in BATCH_SIZES:
        t, _ = time_it(lambda lines=lines: _map_sum(path, lines=lines),
                       trials=ctx.trials)
        ctx.record("Sum (%s)" % _label(lines), "python", "map", n / t,
                   rss_mb(), "")


def _generate_jsonl(n):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="fr_bench_js_")
    with os.fdopen(fd, "w") as fh:
        for i in range(n):
            fh.write(json.dumps({"id": i, "value": i * 2,
                                 "tag": "x" * 10}) + "\n")
    return path


def _map_jsonl(path, lines=None):
    def parse(batch):
        count = 0
        for line in bytes(batch.data).split(b"\n"):
            if line:
                try:
                    json.loads(line)
                    count += 1
                except ValueError:
                    pass
        return str(count).encode()

    kw = {} if lines is None else {"lines": lines}
    return forkrun.map(parse, path, workers=_nworkers(), **kw)


def bench_jsonl_batch_sweep(ctx):
    """JSONL: compute-bound control — batch size should NOT help here
    (dispatch is ~2% of total time). Fewer sizes/trials (slow)."""
    path = _generate_jsonl(SCALES[ctx.scale])
    n = SCALES[ctx.scale]
    try:
        for lines in [None, 1000, 10000]:
            t, _ = time_it(
                lambda lines=lines: _map_jsonl(path, lines=lines),
                trials=max(2, ctx.trials // 2))
            ctx.record("JSONL (%s)" % _label(lines), "python", "map",
                       n / t, rss_mb(), "compute-bound control")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def bench_stream_batch_sweep(ctx):
    """Streaming upper: does batch size help or hurt streaming?
    Larger batches may reduce overlap (fewer, later yields)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    for lines in [None, 1000, 10000]:
        kw = {} if lines is None else {"lines": lines}

        def _run(path=path, kw=dict(kw)):
            for _ in forkrun.stream(lambda b: bytes(b.data).upper(),
                                    path, workers=_nworkers(), **kw):
                pass

        t, _ = time_it(_run, trials=ctx.trials)
        ctx.record("Stream upper (%s)" % _label(lines), "python",
                   "stream", n / t, rss_mb(), "")


def bench_single_worker_isolation(ctx):
    """Single worker: dispatch cost without multi-worker interference
    (no ring contention). Adaptive + two fixed sizes."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in [None, 1000, 10000]:
        t, _ = time_it(
            lambda lines=lines: _map_noop(path, lines=lines, workers=1),
            trials=ctx.trials)
        ctx.record("No-op 1-worker (%s)" % _label(lines), "python",
                   "map", n / t, rss_mb(), "")


def bench_per_batch_cost(ctx):
    """Direct per-batch cost: time / exact batch count.

    Batch counts come from measured b''-record runs (exact), not
    n/lines estimates — except adaptive, whose count is measured the
    same way (one extra run, no estimate anywhere).
    """
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in [100, 1000, 10000, 100000]:
        n_batches = _count_batches(path, lines=lines)
        t, _ = time_it(lambda lines=lines: _map_noop(path, lines=lines),
                       trials=ctx.trials)
        per_batch_us = (t / n_batches) * 1e6 if n_batches else float("inf")
        ctx.record("Per-batch cost (%s)" % _label(lines), "python",
                   "measure", 0, 0,
                   "%.2fµs/batch × %d batches" % (per_batch_us,
                                                  n_batches))
    n_batches = _count_batches(path)
    t, _ = time_it(lambda: _map_noop(path), trials=ctx.trials)
    per_batch_us = (t / n_batches) * 1e6 if n_batches else float("inf")
    ctx.record("Per-batch cost (adaptive)", "python", "measure", 0, 0,
               "%.2fµs/batch × %d batches" % (per_batch_us, n_batches))
    _ = n  # throughput denominator unused here (cost rows carry notes)


def _batch_mem_driver(lines):
    return "\n".join([
        "import sys, resource",
        "sys.path.insert(0, 'python')",
        "import forkrun",
        "def ident(batch): return bytes(batch.data)",
        "out = forkrun.map(ident, sys.argv[1], workers=8, order='index',",
        "                  lines=%d)" % lines,
        "raw = open(sys.argv[1], 'rb').read()",
        "assert b''.join(out) == raw, 'inexact'",
        "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
    ])


def bench_batch_memory(ctx):
    """Peak RSS per batch size, each in a clean subprocess (ru_maxrss
    is monotonic — in-process deltas lie). 20MB input keeps it fast;
    memory here is about in-flight batch buffering, not input size."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="fr_bench_bm_")
    try:
        n_lines = int(20 * 1024 * 1024 / 12)
        with os.fdopen(fd, "w") as fh:
            for i in range(n_lines):
                fh.write("line %06d\n" % (i % 1000000))
        for lines in [1000, 10000, 100000]:
            proc = subprocess.run(
                [sys.executable, "-c", _batch_mem_driver(lines), path],
                capture_output=True, text=True, timeout=600,
                cwd=REPO_ROOT)
            if proc.returncode != 0:
                raise RuntimeError("batch-mem driver failed:\n%s\n%s"
                                   % (proc.stdout, proc.stderr[-4000:]))
            ctx.record("Memory upper (%s)" % _label(lines), "python",
                       "map", 0, int(proc.stdout.strip()) / 1024.0,
                       "peak RSS, clean process, exact run")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


SWEEP = {
    "noop_batch_sweep": bench_noop_batch_sweep,
    "upper_batch_sweep": bench_upper_batch_sweep,
    "sum_batch_sweep": bench_sum_batch_sweep,
    "jsonl_batch_sweep": bench_jsonl_batch_sweep,
    "stream_batch_sweep": bench_stream_batch_sweep,
    "single_worker_isolation": bench_single_worker_isolation,
    "batch_memory": bench_batch_memory,
    "per_batch_cost": bench_per_batch_cost,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=["small", "medium", "large"],
                        default="medium")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--filter", type=str, default=None)
    args = parser.parse_args(argv)
    ctx = BenchContext(scale=args.scale, trials=args.trials)
    print("forkrun batch-size sweep (W-PY17)")
    print("Scale: %s (%s lines), trials: %d, hardware: %s"
          % (args.scale, f"{SCALES[args.scale]:,}", args.trials,
             ctx.hardware))
    try:
        for name in sorted(SWEEP):
            if args.filter and args.filter not in name:
                continue
            print("Running: %s..." % name, flush=True)
            SWEEP[name](ctx)
        print(format_table(ctx.results))
    finally:
        ctx.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
