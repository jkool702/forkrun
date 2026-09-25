"""Streaming-ingest benchmarks: materialized vs streaming (W-PY16).

Same input through both paths: throughput parity check + the TB story
(10GB-equivalent via pipe generation would need minutes; the committed
rows use suite scales and the slow-consumer streaming row).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                            "..", ".."))  # python/ for forkrun

import forkrun  # noqa: E402
from bench_harness import (BenchContext, SCALES, cpu_pct_around, rss_mb, time_it)  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _map_upper_streaming(path):
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), streaming=True)


def _map_upper_materialized(path):
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), streaming=False)


def bench_streaming_vs_materialized(ctx):
    """Same input, both ingest paths: throughput + parity."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _map_upper_materialized(path), trials=ctx.trials)
    ctx.record("Ingest materialized upper (map)", "python", "map", n / t,
               rss_mb(), "spill-then-scan (bounded inputs)")
    t, _ = time_it(lambda: _map_upper_streaming(path), trials=ctx.trials)
    ctx.record("Ingest streaming upper (map)", "python", "map", n / t,
               rss_mb(), "concurrent scan + fallow reclaim",
               cpu_pct=cpu_pct_around(lambda: _map_upper_streaming(path)))


def bench_streaming_pipe(ctx):
    """Pipe-fed streaming (the shape materialized cannot do bounded)."""
    n = SCALES[ctx.scale]
    # Materialize the reference file once; feed copies through a pipe.
    path = ctx.input_path()

    def _pipe_upper():
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(r)
                with open(path, "rb") as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            written = os.write(w, view)
                            view = view[written:]
            finally:
                try:
                    os.close(w)
                except OSError:
                    pass
                os._exit(0)
        os.close(w)
        try:
            return forkrun.map(lambda b: bytes(b.data).upper(), r,
                               workers=_nworkers(), streaming=True)
        finally:
            os.close(r)
            os.waitpid(pid, 0)

    t, _ = time_it(_pipe_upper, trials=ctx.trials)
    ctx.record("Ingest pipe upper (map)", "python", "map", n / t,
               rss_mb(), "unbounded-source shape, fallow-bounded")
