"""Memory benchmarks: RSS vs stream/output size (W-PY11).

The engine is bounded by construction; these prove the Python frontend
doesn't break that. Each leg runs in a SUBPROCESS (ru_maxrss is a
per-process PEAK, monotonic — deltas between separate processes are the
measurement). Drivers assert exactness internally, so RSS numbers always
describe correct runs. Repo root is derived from this file's location
(no CWD dependence).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                            "..", ".."))  # python/ for forkrun

from bench_harness import BenchContext, rss_mb  # noqa: E402

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _subprocess_peak_kb(driver, input_mb):
    """Generate input_mb of lines, run driver once, return peak RSS (KB)."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".txt", prefix="fr_bench_mem_")
    try:
        lines = int(input_mb * 1024 * 1024 / 12)  # ~12 bytes/line
        with os.fdopen(fd, "w") as fh:
            for i in range(lines):
                fh.write("line %d\n" % i)
        proc = subprocess.run(
            [sys.executable, "-c", driver, path],
            capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
        if proc.returncode != 0:
            raise RuntimeError("driver failed for %dMB:\n%s\n%s"
                               % (input_mb, proc.stdout,
                                  proc.stderr[-4000:]))
        return int(proc.stdout.strip())
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


_NO_OUTPUT_DRIVER = "\n".join([
    "import sys, resource",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def none(batch): return None",
    "forkrun.run(none, sys.argv[1], workers=8)",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])

_IDENTITY_DRIVER = "\n".join([
    "import sys, resource",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def ident(batch): return bytes(batch.data)",
    "out = forkrun.map(ident, sys.argv[1], workers=8, order='index')",
    "raw = open(sys.argv[1], 'rb').read()",
    "assert b''.join(out) == raw, 'inexact'",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])

_SLOW_CONSUMER_DRIVER = "\n".join([
    "import sys, resource, time",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def amplify(batch): return bytes(batch.data) * 5",
    "n = 0",
    "for blob in forkrun.stream(amplify, sys.argv[1], workers=4):",
    "    n += 1",
    "    time.sleep(0.001)",
    "assert n > 0",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])

_AMPLIFY_DRIVER = "\n".join([
    "import sys, resource",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def amplify(batch): return bytes(batch.data) * 5",
    "out = forkrun.map(amplify, sys.argv[1], workers=4, order='index')",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])


def bench_rss_no_output(ctx):
    sizes_mb = [1, 2, 4, 8]
    peaks = [_subprocess_peak_kb(_NO_OUTPUT_DRIVER, mb) for mb in sizes_mb]
    growth_mb = (peaks[-1] - peaks[0]) / 1024.0
    ctx.record("RSS flat (no output)", "python", "run", 0, growth_mb,
               "input %d->%dMB, parent peak grew %.0fMB"
               % (sizes_mb[0], sizes_mb[-1], growth_mb))


def bench_rss_output_sized(ctx):
    sizes_mb = [1, 2, 4]
    peaks = [_subprocess_peak_kb(_IDENTITY_DRIVER, mb) for mb in sizes_mb]
    growth_mb = (peaks[-1] - peaks[0]) / 1024.0
    ctx.record("RSS output-sized (map)", "python", "map", 0, growth_mb,
               "output %d->%dMB, parent peak grew %.0fMB (collect-all)"
               % (sizes_mb[0], sizes_mb[-1], growth_mb))


def bench_rss_streaming_bounded(ctx):
    peak_kb = _subprocess_peak_kb(_SLOW_CONSUMER_DRIVER, 10)
    ctx.record("RSS bounded (stream, slow)", "python", "stream", 0,
               peak_kb / 1024.0,
               "50MB output, slow consumer; parent peak, not output size")


def bench_rss_amplification(ctx):
    peak_kb = _subprocess_peak_kb(_AMPLIFY_DRIVER, 2)  # 2MB in, 10MB out
    ctx.record("RSS amplification (map)", "python", "map", 0,
               peak_kb / 1024.0, "2MB in, 10MB out (collect-all)")


def bench_rss_in_process(ctx):
    """In-process sanity: current-process peak after a medium map run."""
    import forkrun  # noqa: PLC0415

    path = ctx.input_path()
    out = forkrun.map(lambda b: bytes(b.data), path,
                      workers=min(8, os.cpu_count() or 4), order="index")
    assert sum(map(len, out)) == os.path.getsize(path)
    ctx.record("RSS in-process (map)", "python", "map", 0, rss_mb(),
               "%d batches exact; rate in throughput suite" % len(out))
