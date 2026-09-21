"""C drain vs Python drain benchmarks (W-PY21-A).

The money comparison: parent-side per-result work (select + signal
unpack + pread + parse) against the forked C loop (signal consume +
pread + verbatim copy). Same framed bytes, same parse — only the
byte movement moves. Includes the NUMA convergence check (UMA vs
@N with the drain on the same box).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import BenchContext, SCALES, rss_mb, time_it  # noqa: E402
from forkrun._numa import detect_numa_nodes  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _map_upper(path, c_drain):
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), order="index",
                       c_drain=c_drain)


def bench_c_drain_vs_python(ctx):
    """THE money benchmark: C drain vs Python drain (map, upper)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t_py, _ = time_it(lambda: _map_upper(path, False),
                      trials=ctx.trials)
    t_c, _ = time_it(lambda: _map_upper(path, True),
                     trials=ctx.trials)
    ratio = t_py / t_c if t_c > 0 else 0.0
    ctx.record("Python drain (map)", "python", "map", n / t_py,
               rss_mb(), "parent select+pread+parse per result")
    ctx.record("C drain (map)", "python", "map", n / t_c, rss_mb(),
               "forked C loop; %.1fx — same framed bytes" % ratio)


def bench_c_drain_numa(ctx):
    """NUMA convergence with the drain (same box, UMA vs @N)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    online = detect_numa_nodes()

    def _map_numa(path, nodes):
        return forkrun.map(lambda b: bytes(b.data).upper(), path,
                           workers=_nworkers(), order="index",
                           nodes=nodes, c_drain=True)

    t_uma, _ = time_it(lambda: _map_numa(path, 1), trials=ctx.trials)
    ctx.record("UMA + C drain", "python", "map", n / t_uma, rss_mb(),
               "single ring, C drain")
    for forced in (2, 4):
        t_numa, _ = time_it(
            lambda f=forced: _map_numa(path, "@%d" % f),
            trials=ctx.trials)
        over = ((t_numa / t_uma) - 1.0) * 100.0 if t_uma > 0 else 0.0
        ctx.record("NUMA @%d + C drain (%d online)" % (forced,
                                                       len(online)),
                   "python", "map", n / t_numa, rss_mb(),
                   "per-node rings; overhead %+.1f%%" % over)


def bench_c_drain_streaming(ctx):
    """Streaming throughput: results-pipe drain vs Python drain."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def _run(c_drain):
        total = 0
        for blob in forkrun.stream(
                lambda b: bytes(b.data).upper(), path,
                workers=_nworkers(), c_drain=c_drain):
            total += len(blob)
        return total

    t_py, _ = time_it(lambda: _run(False), trials=ctx.trials)
    t_c, _ = time_it(lambda: _run(True), trials=ctx.trials)
    ratio = t_py / t_c if t_c > 0 else 0.0
    ctx.record("Python drain (stream)", "python", "stream", n / t_py,
               rss_mb(), "parent select+pread per signal")
    ctx.record("C drain (stream)", "python", "stream", n / t_c,
               rss_mb(), "results pipe; %.1fx" % ratio)
