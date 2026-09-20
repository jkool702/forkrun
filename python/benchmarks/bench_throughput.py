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


def bench_spawn_v1(ctx):
    """v1 spawn: C-level posix_spawnp + splice pump (W-PY13).

    The v1 path is auto-selected (same _spawn_cat/_spawn_tr entry points
    as v0); FORKRUN_NO_V1=1 in the worker env would force the v0 rows
    above. Recorded separately so the published table shows the delta.
    """
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _spawn_cat(path), trials=ctx.trials)
    ctx.record("Spawn v1 cat (map)", "spawn-v1", "map", n / t, rss_mb(),
               "C posix_spawnp + concurrent splice pump, zero-copy input",
               cpu_pct=cpu_pct_around(lambda: _spawn_cat(path)))
    t, _ = time_it(lambda: _spawn_tr(path), trials=ctx.trials)
    ctx.record("Spawn v1 tr (map)", "spawn-v1", "map", n / t, rss_mb(),
               "C posix_spawnp + tr per batch")


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


def bench_plugin_v1(ctx):
    """v1 plugin: C-level dispatch through the frozen ABI (W-PY13).

    Compiles the frozen-ABI fixture (test_plugin_v1.c, 128B forkrun_ctx,
    dialect 2 + FLAG_RAW) once, then maps process_v1. Compare with the
    "Plugin upper (map)" v0 row (ctypes + buffer copies).
    """
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "tests", "plugins", "test_plugin_v1.c")
    fd, plugin_so = tempfile.mkstemp(suffix=".so", prefix="fr_bench_p1_")
    os.close(fd)
    proc = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", plugin_so, src],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("bench v1 plugin build failed:\n%s" % proc.stderr)
    try:
        path = ctx.input_path()
        n = SCALES[ctx.scale]
        t, _ = time_it(lambda: _plugin_v1_process(plugin_so, path),
                       trials=ctx.trials)
        ctx.record("Plugin v1 upper (map)", "plugin-v1", "map", n / t,
                   rss_mb(), "C-to-C call, frozen ABI, zero-copy input",
                   cpu_pct=cpu_pct_around(
                       lambda: _plugin_v1_process(plugin_so, path)))
    finally:
        try:
            os.unlink(plugin_so)
        except OSError:
            pass


def _plugin_v1_process(plugin_so, path):
    return forkrun.map("%s:process_v1" % plugin_so, path, mode="plugin",
                       workers=_nworkers())


def bench_emit_upper(ctx):
    """W-PY14: C-level emit vs v0 Python writes, same workload.

    The emit path is auto-selected; FORKRUN_NO_V1=1 in the worker env
    forces the v0 writes (workers inherit the env at fork, so toggling
    in-process is sound). Both rows run map(upper): the workload whose
    cost is dominated by payload-side copies, bounding what any output
    path can save.
    """
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _map_upper(path), trials=ctx.trials)
    ctx.record("Python upper emit (map)", "python", "map", n / t,
               rss_mb(), "fr_py_emit: writev + zero-copy bytes")
    os.environ["FORKRUN_NO_V1"] = "1"
    try:
        t, _ = time_it(lambda: _map_upper(path), trials=ctx.trials)
    finally:
        del os.environ["FORKRUN_NO_V1"]
    ctx.record("Python upper v0 writes (map)", "python", "map", n / t,
               rss_mb(), "header pack + two writes + signal (fallback)")


def bench_streaming_overhead(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t_map, _ = time_it(lambda: _map_upper(path), trials=ctx.trials)
    t_stream, _ = time_it(lambda: _stream_upper(path), trials=ctx.trials)
    ratio = t_stream / t_map if t_map > 0 else float("inf")
    ctx.record("stream vs map", "python", "stream", n / t_stream, rss_mb(),
               "ratio=%.2fx (map=%.0f/s)" % (ratio, n / t_map),
               cpu_pct=cpu_pct_around(lambda: _stream_upper(path)))


def bench_stream_slow_consumer(ctx):
    """W-PY15: streaming throughput with a moderately slow consumer.

    The 1MB signal pipe (65536 outstanding signals vs 4096 at 64KB)
    lets workers run further ahead before backpressure stalls them.
    With a fast consumer pipe size is irrelevant; with a very slow one
    memory (not throughput) is the question — this row covers the
    middle: consumer at ~0.5ms/batch.
    """
    import time as _time

    path = ctx.input_path()
    n = SCALES[ctx.scale]

    def _drain_slow():
        count = 0
        for _blob in forkrun.stream(lambda b: bytes(b.data).upper(), path,
                                    workers=_nworkers()):
            count += 1
            _time.sleep(0.0005)
        return count

    t, _ = time_it(_drain_slow, trials=ctx.trials)
    ctx.record("stream slow-consumer", "python", "stream", n / t,
               rss_mb(), "consumer 0.5ms/batch; 1MB signal pipe")


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
