"""NUMA scaling benchmarks: UMA vs forced multi-node (W-PY21).

On real multi-socket hardware this measures born-local scaling
(per-node rings, MPOL_BIND ingest, distance-charged stealing). On
single-socket (like CI) @N runs the full NUMA pipeline on shared
physicals — a correctness + overhead measurement, not a scaling
claim: expect ~1-5% overhead from per-node ring management, never
a speedup. The honest comparison is same-box UMA vs @N.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import BenchContext, SCALES, rss_mb, time_it  # noqa: E402
from forkrun._numa import detect_numa_nodes  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _map_upper_nodes(path, nodes):
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), order="index", nodes=nodes)


def bench_numa_scaling(ctx):
    """UMA vs @2 vs @4 on the same box (upper transform, map)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    online = detect_numa_nodes()

    t, _ = time_it(lambda: _map_upper_nodes(path, 1),
                   trials=ctx.trials)
    ctx.record("Upper nodes=1 (UMA)", "python", "map", n / t,
               rss_mb(), "single ring, node 0")
    for forced in (2, 4):
        label = ("Upper nodes=@%d (%d physical online)" %
                 (forced, len(online)))
        t, _ = time_it(lambda f=forced: _map_upper_nodes(
            path, "@%d" % f), trials=ctx.trials)
        ctx.record(label, "python", "map", n / t, rss_mb(),
                   "per-node rings, born-local ingest, pinning")


def bench_numa_stream(ctx):
    """NUMA over stream(): live drain off per-node rings."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def _run(nodes):
        total = 0
        for blob in forkrun.stream(
                lambda b: bytes(b.data).upper(), path,
                workers=_nworkers(), nodes=nodes):
            total += len(blob)
        return total

    for nodes in (1, "@2"):
        t, _ = time_it(lambda n=nodes: _run(n), trials=ctx.trials)
        ctx.record("Upper stream nodes=%s" % (nodes,), "python",
                   "stream", n / t, rss_mb(),
                   "live drain, per-worker memfds")
