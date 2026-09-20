"""Baseline comparisons: forkrun vs plain Python (W-PY11).

CONTEXT rows, not headlines. Question: is forkrun faster than the obvious
alternatives? multiprocessing.Pool runs at SMALL scale unconditionally —
pool.map pickles every line, so medium scale would blow the time budget
and prove nothing beyond "pickling 1M lines is slow".
"""

import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import BenchContext, SCALES, rss_mb, time_it  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def bench_serial_python(ctx):
    """Single-threaded read loop (I/O + interpreter overhead floor)."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def serial():
        with open(path, "rb") as fh:
            for _line in fh:
                pass

    t, _ = time_it(serial, trials=ctx.trials)
    ctx.record("Serial Python (no-op)", "serial", "baseline", n / t,
               rss_mb(), "I/O bound")


def bench_serial_upper(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def serial():
        results = []
        with open(path, "rb") as fh:
            for line in fh:
                results.append(line.upper())
        return results

    t, _ = time_it(serial, trials=ctx.trials)
    ctx.record("Serial Python (upper)", "serial", "baseline", n / t,
               rss_mb(), "")


def bench_mp_pool(ctx):
    """Pool.map over readlines (pickles every line). SMALL scale only."""
    path = ctx.input_path(lines=SCALES["small"])
    n = SCALES["small"]

    def mp_pool():
        with multiprocessing.Pool(_nworkers()) as pool:
            with open(path, "rb") as fh:
                lines = fh.readlines()
            return pool.map(bytes.upper, lines)

    t, _ = time_it(mp_pool, trials=min(ctx.trials, 3))
    ctx.record("multiprocessing.Pool (upper)", "mp", "baseline", n / t,
               rss_mb(), "small scale; per-line pickling")


def bench_forkrun_vs_baselines(ctx):
    """Same workload, three approaches, speedup ratios."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]

    t_fr, _ = time_it(
        lambda: forkrun.map(lambda b: bytes(b.data).upper(), path,
                            workers=_nworkers()),
        trials=ctx.trials)

    def serial_upper():
        results = []
        with open(path, "rb") as fh:
            for line in fh:
                results.append(line.upper())
        return results

    t_serial, _ = time_it(serial_upper, trials=ctx.trials)

    def mp_upper():
        with multiprocessing.Pool(_nworkers()) as pool:
            with open(path, "rb") as fh:
                lines = fh.readlines()
            return pool.map(bytes.upper, lines)

    # mp baseline at the SAME scale would dominate runtime; measure once.
    t0 = time.perf_counter()
    mp_upper()
    t_mp = time.perf_counter() - t0

    speedup_serial = t_serial / t_fr if t_fr > 0 else 0
    speedup_mp = t_mp / t_fr if t_fr > 0 else 0
    ctx.record("forkrun.map vs baselines", "python", "map", n / t_fr,
               rss_mb(),
               "%.1fx vs serial, %.1fx vs mp.Pool (mp single-trial)"
               % (speedup_serial, speedup_mp))
