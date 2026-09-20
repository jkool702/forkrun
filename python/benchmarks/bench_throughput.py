"""Throughput benchmarks: lines/sec per mode x workload x output path.

Reference (bash README, same box class): ~25M lines/s builtins, ~87M -X,
~191M -l 1:-1. Python v0 numbers will be lower — the honest number is the
deliverable, not a target. Payloads are fork-inherited closures (no
pickle); workers = min(8, ncpu).
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import (BenchContext, SCALES, cpu_pct_around, rss_mb, time_it)  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _run_noop(path):
    forkrun.run(lambda b: None, path, workers=_nworkers())


def _map_noop(path):
    return forkrun.map(lambda b: None, path, workers=_nworkers())


def _stream_noop(path):
    for _ in forkrun.stream(lambda b: None, path, workers=_nworkers()):
        pass


def _map_upper(path, lines=None):
    kw = {} if lines is None else {"lines": lines}
    return forkrun.map(lambda b: bytes(b.data).upper(), path,
                       workers=_nworkers(), **kw)


def _stream_upper(path, ordered=False):
    kw = {"order": "index"} if ordered else {}
    for _ in forkrun.stream(lambda b: bytes(b.data).upper(), path,
                            workers=_nworkers(), **kw):
        pass


def _map_compute(path):
    return forkrun.map(lambda b: str(sum(b.data)).encode(), path,
                       workers=_nworkers())


def _spawn_cat(path):
    return forkrun.map("cat", path, mode="spawn", workers=_nworkers())


def _spawn_tr(path):
    return forkrun.map("tr a-z A-Z", path, mode="spawn",
                       workers=_nworkers())


def _plugin_process(plugin_so, path):
    return forkrun.map("%s:process" % plugin_so, path, mode="plugin",
                       workers=_nworkers())


def bench_python_identity(ctx):
    """No-op payload: claim/ack/emitter overhead floor per output path."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _run_noop(path), trials=ctx.trials)
    ctx.record("Python no-op (run/discard)", "python", "run", n / t,
               rss_mb(), "claim/ack loop only")
    t, _ = time_it(lambda: _map_noop(path), trials=ctx.trials)
    ctx.record("Python no-op (map/collect)", "python", "map", n / t,
               rss_mb(), "per-worker memfds, parent parse",
               cpu_pct=cpu_pct_around(lambda: _map_noop(path)))
    t, _ = time_it(lambda: _stream_noop(path), trials=ctx.trials)
    ctx.record("Python no-op (stream)", "python", "stream", n / t,
               rss_mb(), "signal + pread per batch")


def bench_python_transform(ctx):
    """upper(): realistic string transform through map."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _map_upper(path), trials=ctx.trials)
    ctx.record("Python upper (map)", "python", "map", n / t, rss_mb(),
               "bytes(batch.data).upper() per batch",
               cpu_pct=cpu_pct_around(lambda: _map_upper(path)))


def bench_python_compute(ctx):
    """sum(): CPU-bound per-batch compute."""
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _map_compute(path), trials=ctx.trials)
    ctx.record("Python sum (map)", "python", "map", n / t, rss_mb(),
               "sum(memoryview) per batch",
               cpu_pct=cpu_pct_around(lambda: _map_compute(path)))


def bench_spawn_cat(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _spawn_cat(path), trials=ctx.trials)
    ctx.record("Spawn cat (map)", "spawn", "map", n / t, rss_mb(),
               "subprocess.run per batch",
               cpu_pct=cpu_pct_around(lambda: _spawn_cat(path)))


def bench_spawn_tr(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _spawn_tr(path), trials=ctx.trials)
    ctx.record("Spawn tr (map)", "spawn", "map", n / t, rss_mb(),
               "subprocess.run + tr per batch")


def bench_plugin_process(ctx):
    """C callback via ctypes (test plugin compiled once, not per trial)."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "tests", "plugins", "test_plugin.c")
    fd, plugin_so = tempfile.mkstemp(suffix=".so", prefix="fr_bench_plug_")
    os.close(fd)
    proc = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", plugin_so, src],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("bench plugin build failed:\n%s" % proc.stderr)
    try:
        path = ctx.input_path()
        n = SCALES[ctx.scale]
        t, _ = time_it(lambda: _plugin_process(plugin_so, path),
                       trials=ctx.trials)
        ctx.record("Plugin upper (map)", "plugin", "map", n / t, rss_mb(),
                   "ctypes callback per batch",
                   cpu_pct=cpu_pct_around(
                       lambda: _plugin_process(plugin_so, path)))
    finally:
        try:
            os.unlink(plugin_so)
        except OSError:
            pass


def bench_streaming_overhead(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t_map, _ = time_it(lambda: _map_upper(path), trials=ctx.trials)
    t_stream, _ = time_it(lambda: _stream_upper(path), trials=ctx.trials)
    ratio = t_stream / t_map if t_map > 0 else float("inf")
    ctx.record("stream vs map", "python", "stream", n / t_stream, rss_mb(),
               "ratio=%.2fx (map=%.0f/s)" % (ratio, n / t_map),
               cpu_pct=cpu_pct_around(lambda: _stream_upper(path)))


def bench_ordered_vs_unordered(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t_unordered, _ = time_it(lambda: _stream_upper(path),
                             trials=ctx.trials)
    t_ordered, _ = time_it(lambda: _stream_upper(path, ordered=True),
                           trials=ctx.trials)
    ratio = t_ordered / t_unordered if t_unordered > 0 else float("inf")
    ctx.record("ordered vs unordered (stream)", "python", "stream",
               n / t_ordered, rss_mb(),
               "ratio=%.2fx (unordered=%.0f/s)"
               % (ratio, n / t_unordered))


def bench_batch_size_effect(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    for lines in (100, 1000, None):
        label = "lines=%s" % lines if lines else "adaptive"
        # Default-arg binding: loop variable must not leak into the closure.
        t, _ = time_it(lambda lines=lines: _map_upper(path, lines=lines),
                       trials=ctx.trials)
        ctx.record("Python upper (%s)" % label, "python", "map", n / t,
                   rss_mb(), "")
