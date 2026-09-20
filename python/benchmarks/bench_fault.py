"""Fault-tolerance benchmarks: what resilience costs (W-PY11).

Healthy vs 10% deterministic failures (retry x3 -> poison) vs 100%.
Failures key on batch_index (deterministic, no timing dependence).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import BenchContext, SCALES, rss_mb, time_it  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _map_healthy(path):
    return forkrun.map(lambda b: b.copy(), path, workers=_nworkers(),
                       order="index")


def _map_10pct_faulty(path):
    def flaky(batch):
        if batch.batch_index % 10 == 0:
            raise RuntimeError("deterministic failure")
        return bytes(batch.data)
    return forkrun.map(flaky, path, workers=_nworkers(), order="index")


def _map_all_faulty(path):
    def always_fail(batch):
        raise RuntimeError("always fails")
    return forkrun.map(always_fail, path, workers=_nworkers(),
                       order="index")


def bench_healthy_vs_faulty(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t_healthy, _ = time_it(lambda: _map_healthy(path), trials=ctx.trials)
    t_10pct, _ = time_it(lambda: _map_10pct_faulty(path), trials=ctx.trials)
    t_100pct, _ = time_it(lambda: _map_all_faulty(path), trials=ctx.trials)
    overhead_10 = (t_10pct / t_healthy - 1) * 100 if t_healthy > 0 else 0
    ctx.record("Healthy baseline", "python", "map", n / t_healthy,
               rss_mb(), "")
    ctx.record("10% failures (retry+poison)", "python", "map", n / t_10pct,
               rss_mb(), "%+.0f%% vs healthy (skipped payload work)" % overhead_10)
    ctx.record("100% failures (all poison)", "python", "map", n / t_100pct,
               rss_mb(), "completes; every batch poisoned")
