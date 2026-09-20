"""Shared benchmark infrastructure (W-PY11).

Every benchmark is a function taking a BenchContext and appending Result
rows to it. The harness handles deterministic input generation, median
timing with warm-up, RSS measurement, hardware disclosure, and
table/CSV output. No engine or library code is touched from here.
"""

import csv
import os
import resource
import statistics
import sys
import tempfile
import time

SCALES = {
    "small": 100_000,
    "medium": 1_000_000,
    "large": 10_000_000,
}

# Lines are "line %06d\\n" (~12-13 bytes); JSONL/numeric generators below
# document their own sizes.
APPROX_LINE_BYTES = 13


class Result:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if not hasattr(self, "cpu_pct"):
            self.cpu_pct = -1.0  # -1 = not measured for this row


class BenchContext:
    """One benchmark run's environment (scale, trials, results)."""

    def __init__(self, scale="medium", trials=5):
        if scale not in SCALES:
            raise ValueError("scale must be one of %s" % sorted(SCALES))
        self.scale = scale
        self.trials = trials
        self.hardware = _detect_hardware()
        self.results = []
        self._tmp = []

    def input_path(self, lines=None):
        """Generate a deterministic input file. Caller must not unlink
        (paths are tracked and cleaned by cleanup()). Returns path."""
        if lines is None:
            lines = SCALES[self.scale]
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="fr_bench_")
        with os.fdopen(fd, "w") as fh:
            for i in range(lines):
                fh.write("line %06d\n" % i)
        self._tmp.append(path)
        return path

    def record(self, name, mode, path_type, lines_per_s, rss_mb,
               notes="", cpu_pct=-1.0):
        self.results.append(Result(
            name=name, mode=mode, path=path_type,
            lines_per_s=lines_per_s, rss_mb=rss_mb,
            notes=notes, hardware=self.hardware, cpu_pct=cpu_pct))

    def cleanup(self):
        for path in self._tmp:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._tmp = []


def _detect_hardware():
    """CPU, cores, kernel — the mandatory disclosure column."""
    import platform

    try:
        with open("/proc/cpuinfo") as fh:
            cpu = ""
            for line in fh:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
            if not cpu:
                cpu = platform.processor() or "unknown"
    except OSError:
        cpu = platform.processor() or "unknown"
    cores = os.cpu_count() or 0
    return "%dc/%s Linux %s" % (cores, cpu[:32], platform.release())


def time_it(fn, trials=5, warmup=1):
    """Run fn() with warm-up, return (median_seconds, all_seconds).

    Uses perf_counter. Callers pass bound closures; the FIRST timed trial
    still pays fork costs, which is honest (fork is part of the path).
    """
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(trials):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), times


def rss_mb():
    """Current peak RSS in MB (ru_maxrss is KB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _cpu_seconds():
    """Self + reaped-children CPU seconds (user + sys)."""
    me = resource.getrusage(resource.RUSAGE_SELF)
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ((me.ru_utime + me.ru_stime)
            + (kids.ru_utime + kids.ru_stime))


def cpu_pct_around(fn):
    """Run fn() once; return machine-utilization percent during it.

    Method (W-PY12 correction): delta of self+children CPU seconds over
    wall time, normalized by core count — NOT system-wide /proc/stat,
    which on a shared box measures other people's processes. 8 busy
    workers on 28 cores reads ~29%. Children must be reaped (waitpid)
    before the closing sample or their time is invisible.
    """
    cores = os.cpu_count() or 1
    fn()  # warm (page cache, fork paths) — untimed, unmeasured
    c0 = _cpu_seconds()
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    c1 = _cpu_seconds()
    if elapsed <= 0:
        return 0.0
    return 100.0 * (c1 - c0) / (elapsed * cores)


def format_rate(lines_per_s):
    if lines_per_s >= 1e6:
        return "%.1fM" % (lines_per_s / 1e6)
    if lines_per_s >= 1e3:
        return "%.0fk" % (lines_per_s / 1e3)
    if lines_per_s > 0:
        return "%.0f" % lines_per_s
    return "-"


def format_cpu(cpu_pct):
    if cpu_pct is None or cpu_pct < 0:
        return "-"
    return "%.0f%%" % cpu_pct


def format_table(results):
    """Aligned text table. Empty input yields headers only (never raises)."""
    headers = ["Benchmark", "Mode", "Path", "Lines/s", "Peak RSS", "CPU%",
               "Notes"]
    rows = []
    for r in results:
        rows.append([
            r.name, r.mode, r.path,
            format_rate(r.lines_per_s),
            "%.0fMB" % r.rss_mb,
            format_cpu(getattr(r, "cpu_pct", -1.0)),
            r.notes,
        ])
    widths = []
    for i, h in enumerate(headers):
        col = [len(str(h))] + [len(str(r[i])) for r in rows]
        widths.append(max(col))
    out = []
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out.append(sep)
    out.append("| " + " | ".join(
        str(h).ljust(w) for h, w in zip(headers, widths)) + " |")
    out.append(sep)
    for row in rows:
        out.append("| " + " | ".join(
            str(c).ljust(w) for c, w in zip(row, widths)) + " |")
    out.append(sep)
    return "\n".join(out)


def write_csv(results, path):
    """Machine-readable output for CI tracking."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "mode", "path", "lines_per_s", "rss_mb",
                         "cpu_pct", "notes", "hardware"])
        for r in results:
            writer.writerow([r.name, r.mode, r.path, r.lines_per_s,
                             r.rss_mb, getattr(r, "cpu_pct", -1.0),
                             r.notes, r.hardware])


def repo_python_path():
    """Ensure `import forkrun` resolves to the in-tree package."""
    here = os.path.dirname(os.path.abspath(__file__))
    pkg_root = os.path.dirname(here)  # python/
    if pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)
    return pkg_root
