"""Splice-mode benchmarks: C-loop passthrough vs Python (W-PY18).

mode="splice" runs claim→sendfile→signal→ack entirely in C (zero
Python per batch) over byte-mode batches. The fair comparison is
Python passthrough (moving the same bytes), not no-op (moving
nothing) — both are parent-bound (spill/scan/parse) at these scales.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                            "..", ".."))  # python/ for forkrun

import forkrun  # noqa: E402
from bench_harness import BenchContext, SCALES, rss_mb, time_it  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _map_splice(path, bytes_):
    return forkrun.map(None, path, mode="splice", bytes=bytes_,
                       workers=_nworkers(), order="index")


def _map_passthrough(path):
    return forkrun.map(lambda b: bytes(b.data), path,
                       workers=_nworkers(), order="index")


def bench_splice_vs_python(ctx):
    """The money benchmark: C-loop passthrough vs Python passthrough
    (same bytes moved — the honest comparison)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _map_passthrough(path), trials=ctx.trials)
    ctx.record("Python passthrough (map)", "python", "map", n / t,
               rss_mb(), "bytes(data) per batch, same bytes moved")
    for bs in [64 * 1024, 512 * 1024, 1024 * 1024]:
        t, _ = time_it(lambda bs=bs: _map_splice(path, bs),
                       trials=ctx.trials)
        ctx.record("Splice %dKB (map)" % (bs // 1024), "splice", "map",
                   n / t, rss_mb(), "C claim→sendfile→signal→ack")


def bench_splice_stream(ctx):
    """Splice over stream(): pipelined drain (no parent collect-parse
    join at the end)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def _run():
        total = 0
        for blob in forkrun.stream(None, path, mode="splice",
                                   bytes=512 * 1024,
                                   workers=_nworkers()):
            total += len(blob)
        return total

    t, _ = time_it(_run, trials=ctx.trials)
    ctx.record("Splice 512KB (stream)", "splice", "stream", n / t,
               rss_mb(), "pipelined drain")
