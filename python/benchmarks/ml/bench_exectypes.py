"""Executor + C (ctypes) control row for the headline benchmark (W-EXECTYPES).

Question: how much of "forkrun C vs Executor" is the payload language (C vs
Python) and how much is orchestration (ring/claim/zero-copy vs queue/future
machinery)? This runs ProcessPoolExecutor over the SAME C payload forkrun's
plugin rows load (ml_plugin_light / ml_plugin_yyjson / ml_plugin_heavy),
decomposing the win into payload dividend vs architecture dividend.

Fairness rules (all enforced, all asserted in --sanity):
  1. Same .so, same entry point, same input bytes as the forkrun C rows.
  2. Workers pread assigned byte ranges from the input file (fd opened once
     per worker, cached). Only (offset, length) ints + paths cross the
     Executor boundary — NO pickled input. Output bytes return via pickle
     (output must cross somehow; forkrun transports output too).
  3. ctypes CDLL loads worker-side, post-fork, lazily on first task, cached.
     The parent never touches the .so (fork-safety hazard class).
  4. Chunking: line-aligned byte ranges at ~4k-line granularity (comparable
     to forkrun's adaptive batching) for the primary row; an optional
     coarse (~100k-line) variant records dispatch-amortization sensitivity.
  5. Methodology parity: 28 workers, median-of-3 + warmup, same input files,
     exact-totals assertion, environment echo.

Plugin ABI notes: the dialect-2 ctx is built here by hand (128 bytes, per
ring_loadables/forkrun_plugin.h). flags_granted=0, so the plugin takes its
documented ungranted fallback: pread(ctx->fd_in) at ctx->batch_offset, and
writes output to stdout — captured per task via dup2 to a per-worker file
(+ libc fflush). This exercises the same process() core as the forkrun rows.

Usage:
  python3 python/benchmarks/ml/bench_exectypes.py --sanity
  python3 python/benchmarks/ml/bench_exectypes.py --cells light,medium [--trials 3]
  python3 python/benchmarks/ml/bench_exectypes.py --cells light,medium,heavy --coarse

No engine or library code is touched from here (benchmark-harness only).
"""

import argparse
import ctypes
import mmap
import os
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # benchmarks/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # python/ for forkrun

from bench_harness import rss_mb, time_it  # noqa: E402

WORKERS = 28
GRANULARITY_LINES = 4096
COARSE_LINES = 100000

# variant -> (plugin source key, entry symbol). Medium uses the yyjson
# single-pass plugin — the same .so the forkrun C-plugin rows load.
VARIANTS = {
    "light": ("light", "ml_process_light"),
    "medium": ("yyjson", "ml_process_medium_yyjson"),
    "heavy": ("heavy", "ml_process_heavy"),
}


class ForkrunCtx(ctypes.Structure):
    """Mirror of `struct forkrun_ctx` (forkrun_plugin.h, 128 bytes)."""

    _fields_ = [
        ("batch_index", ctypes.c_uint64),
        ("batch_offset", ctypes.c_uint64),
        ("batch_byte_length", ctypes.c_uint64),
        ("version", ctypes.c_uint32),
        ("worker_id", ctypes.c_uint32),
        ("node_id", ctypes.c_uint32),
        ("num_kills", ctypes.c_uint32),
        ("numa_batch_id", ctypes.c_uint64),
        ("fd_in", ctypes.c_int32),
        ("delimiter", ctypes.c_char),
        ("cfg_state", ctypes.c_uint8 * 4),
        ("batch_lines", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("worker_incarn", ctypes.c_uint32),
        ("flags_granted", ctypes.c_uint32),
        ("reserved32", ctypes.c_uint32),
        ("reserved", ctypes.c_uint64 * 6),
    ]


assert ctypes.sizeof(ForkrunCtx) == 128, ctypes.sizeof(ForkrunCtx)

try:
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
    _LIBC.fflush.argtypes = [ctypes.c_void_p]
    _LIBC.fflush.restype = ctypes.c_int
except OSError:  # pragma: no cover - glibc hosts only
    _LIBC = None


# --- worker side (module top level: pickle-safe) ---

_W = {"lib": None, "func": None, "fd": -1, "cap": -1, "saved": -1,
      "so": None, "path": None, "marked": False, "marker_dir": None}


def _ensure_worker(so_path, func_name, in_path, marker_dir):
    st = _W
    if st["lib"] is not None and st["so"] == so_path:
        return st
    if st["lib"] is not None:
        raise RuntimeError("worker re-targeted at a second .so")
    lib = ctypes.CDLL(so_path)
    try:
        fn = getattr(lib, func_name)
    except AttributeError:
        raise RuntimeError("entry %s not in %s" % (func_name, so_path))
    fn.argtypes = [ctypes.c_int, ctypes.c_void_p,
                   ctypes.POINTER(ForkrunCtx)]
    fn.restype = ctypes.c_int
    fd = os.open(in_path, os.O_RDONLY)
    cap_fd, cap_path = tempfile.mkstemp(prefix="exectypes_cap_")
    os.unlink(cap_path)  # anonymous: fd only, auto-freed on close
    st.update(lib=lib, func=fn, fd=fd, cap=cap_fd, saved=os.dup(1),
              so=so_path, path=in_path)
    if marker_dir and not st["marked"]:
        with open(os.path.join(marker_dir, "worker-%d" % os.getpid()),
                  "w") as fh:
            fh.write("%s\n" % func_name)
        st["marked"] = True
        st["marker_dir"] = marker_dir
    return st


def _process_range(task):
    """Process one line-aligned byte range through the C plugin.

    task = (offset, length, in_path, so_path, func_name, marker_dir,
            want_pid). Only ints/strs/bools/None cross the Executor
    boundary (asserted in --sanity) — NO pickled input.
    Returns the output bytes (terminated framing, like the forkrun rows),
    or (bytes, pid) when want_pid is set (sanity only).
    """
    offset, length, in_path, so_path, func_name, marker_dir = task[:6]
    want_pid = len(task) > 6 and bool(task[6])
    st = _ensure_worker(so_path, func_name, in_path, marker_dir)
    ctx = ForkrunCtx()
    ctx.batch_index = offset  # unique-ish per task; informational only
    ctx.batch_offset = offset
    ctx.batch_byte_length = length
    ctx.version = 2
    ctx.worker_id = os.getpid() & 0xFFFFFFFF
    ctx.node_id = 0
    ctx.fd_in = st["fd"]
    ctx.delimiter = b"\n"
    ctx.batch_lines = 0
    ctx.struct_size = 128
    ctx.flags_granted = 0  # ungranted: plugin preads fd_in (the point)
    sys.stdout.flush()
    os.lseek(st["cap"], 0, os.SEEK_SET)
    os.ftruncate(st["cap"], 0)
    os.dup2(st["cap"], 1)
    try:
        rc = st["func"](0, None, ctypes.byref(ctx))
        if _LIBC is not None:
            _LIBC.fflush(None)
    finally:
        os.dup2(st["saved"], 1)
    if rc != 0:
        raise RuntimeError("plugin rc=%d @offset=%d len=%d"
                           % (rc, offset, length))
    os.lseek(st["cap"], 0, os.SEEK_SET)
    chunks = []
    while True:
        buf = os.read(st["cap"], 1 << 20)
        if not buf:
            break
        chunks.append(buf)
    out = b"".join(chunks)
    if want_pid:
        return out, os.getpid()
    return out


# --- driver side ---

def compute_ranges(path, lines_per_chunk):
    """Line-aligned (offset, length) byte ranges, ~lines_per_chunk lines."""
    size = os.path.getsize(path)
    bounds = [0]
    with open(path, "rb") as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            count = 0
            pos = 0
            while True:
                nxt = mm.find(b"\n", pos)
                if nxt == -1:
                    break
                count += 1
                pos = nxt + 1
                if count >= lines_per_chunk:
                    bounds.append(pos)
                    count = 0
            if bounds[-1] != size:
                bounds.append(size)
    ranges = [(bounds[i], bounds[i + 1] - bounds[i])
              for i in range(len(bounds) - 1)]
    return [r for r in ranges if r[1] > 0]


def build_plugins(workdir):
    """Compile the three C plugins fresh (same flags as bench_ml_pipeline)."""
    import shutil as _shutil
    if _shutil.which("gcc") is None:
        raise RuntimeError("need gcc to build the ML plugins")
    repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(HERE)))
    plugin_dir = os.path.join(HERE, "plugins")
    inc = os.path.join(repo_root, "ring_loadables")
    out = {}
    jobs = [("light", ["ml_plugin_light.c"]),
            ("yyjson", ["ml_plugin_yyjson.c", "yyjson.c"]),
            ("heavy", ["ml_plugin_heavy.c"])]
    for key, srcs in jobs:
        so_path = os.path.join(workdir, "ml_plugin_%s.so" % key)
        cmd = (["gcc", "-O3", "-shared", "-fPIC", "-march=native",
                "-I", inc, "-o", so_path]
               + [os.path.join(plugin_dir, s) for s in srcs] + ["-lm"])
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=300)
        if proc.returncode != 0:
            raise RuntimeError("plugin %s build failed:\n%s"
                               % (key, proc.stderr[-2000:]))
        out[key] = so_path
    return out


def run_cell(path, n_records, so_path, func_name, ranges, workers,
             trials, marker_dir=None):
    """Timed executor.map over pre-computed ranges. Returns dict of stats."""
    tasks = [(off, ln, path, so_path, func_name, marker_dir)
             for off, ln in ranges]

    def run():
        total = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for out in ex.map(_process_range, tasks, chunksize=1):
                total += out.count(b"\n")
        return total

    t_med, t_all = time_it(run, trials=trials, warmup=1)
    total = run()
    if total != n_records:
        raise RuntimeError("totals mismatch: got %d segments, want %d"
                           % (total, n_records))
    return {"median_s": t_med, "trials": t_all,
            "rate": n_records / t_med, "total": total,
            "n_tasks": len(tasks), "rss_mb": rss_mb()}


def environment_echo():
    out = []

    def knob(p):
        try:
            with open(p) as fh:
                return fh.read().strip().replace("\n", " ")
        except OSError:
            return "<n/a>"

    out.append("THP enabled: %s" % knob(
        "/sys/kernel/mm/transparent_hugepage/enabled"))
    out.append("THP shmem:   %s" % knob(
        "/sys/kernel/mm/transparent_hugepage/shmem_enabled"))
    out.append("THP defrag:  %s" % knob(
        "/sys/kernel/mm/transparent_hugepage/defrag"))
    out.append("NUMA online: %s" % knob("/sys/devices/system/node/online"))
    try:
        cpu = next(l.split(":", 1)[1].strip() for l in
                   open("/proc/cpuinfo") if l.startswith("model name"))
    except (OSError, StopIteration):
        cpu = "?"
    import platform
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True,
                             cwd=os.path.join(HERE, "..", "..")
                             ).stdout.strip()
    except OSError:
        sha = "?"
    try:
        import forkrun  # noqa: E402
        frv = getattr(forkrun, "__version__", "?")
    except ImportError:
        frv = "<unimportable>"
    try:
        gccv = subprocess.run(["gcc", "-dumpversion"], capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        gccv = "?"
    out.append("CPU: %s (%s logical)" % (cpu, os.cpu_count()))
    out.append("kernel: %s | python: %s | gcc: %s"
               % (platform.release(), platform.python_version(), gccv))
    out.append("forkrun: %s | SHA: %s" % (frv, sha))
    return "\n".join(out)


def sanity(workers):
    """Harness gates (a)-(e): ABI, totals, task types, lazy load, framing."""
    print("# sanity: building plugins fresh", flush=True)
    workdir = tempfile.mkdtemp(prefix="exectypes_sanity_")
    sos = build_plugins(workdir)
    in_path = "/mnt/ramdisk/numa1/ml/light_5M.jsonl"
    ranges = compute_ranges(in_path, 1000)[:40]
    n_lines = 40 * 1000
    so_path, func_name = sos["light"], VARIANTS["light"][1]
    tasks = [(off, ln, in_path, so_path, func_name, None)
             for off, ln in ranges]
    # (d) task tuples carry only ints/strs/bools/None (no pickled input)
    for t in tasks:
        for elt in t:
            assert elt is None or isinstance(elt, (int, str, bool)), \
                type(elt)
    print("# sanity: task-type gate PASS (%d tasks)" % len(tasks),
          flush=True)
    marker_dir = tempfile.mkdtemp(prefix="exectypes_markers_")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        pairs = list(ex.map(_process_range,
                            [(o, l, in_path, so_path, func_name, marker_dir,
                              True) for o, l in ranges], chunksize=1))
    outs = [p[0] for p in pairs]
    task_pids = set(p[1] for p in pairs)
    # (c) EVERY worker that ran a task loaded the plugin itself, post-fork:
    # the set of task-running pids must equal the set of marker pids.
    markers = sorted(os.listdir(marker_dir))
    marker_pids = set(int(m.split("-")[1]) for m in markers)
    assert task_pids == marker_pids, (sorted(task_pids),
                                      sorted(marker_pids))
    print("# sanity: lazy-load gate PASS (%d task workers, all marked)"
          % len(markers), flush=True)
    # parent never touched the .so
    assert _W["lib"] is None
    print("# sanity: parent-clean gate PASS", flush=True)
    blob = b"".join(outs)
    # (b) totals + (a/e) framing
    assert blob.endswith(b"\n") and blob.count(b"\n") == n_lines, (
        blob.count(b"\n"), n_lines)
    print("# sanity: totals+framing PASS (%d segments)" % n_lines,
          flush=True)
    # sample JSON well-formedness
    import json as _json
    for ln in blob.split(b"\n")[:5]:
        if ln.strip():
            _json.loads(ln)
    print("# sanity: output-wellformed PASS", flush=True)
    # (a) byte-identity vs the forkrun plugin path on the same bytes
    import forkrun  # noqa: E402
    end = ranges[-1][0] + ranges[-1][1]
    with open(in_path, "rb") as fh:
        head = fh.read(end)
    assert len(head) == end
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.write(head)
    tmp.close()
    try:
        ref = forkrun.map("%s:%s" % (so_path, func_name), tmp.name,
                          mode="plugin", workers=4, order="index")
    finally:
        os.unlink(tmp.name)
    ref_blob = ref if isinstance(ref, (bytes, bytearray)) else b"".join(ref)
    assert bytes(ref_blob) == blob, (
        "executor-ctypes output diverges from forkrun plugin output: "
        "%d vs %d bytes" % (len(ref_blob), len(blob)))
    print("# sanity: forkrun-byte-identity PASS (%d bytes)" % len(blob),
          flush=True)
    print("SANITY ALL GREEN", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sanity", action="store_true")
    ap.add_argument("--cells", default="light,medium",
                    help="subset of light,medium,heavy")
    ap.add_argument("--coarse", action="store_true",
                    help="also run the ~100k-line coarse variant")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--granularity", type=int, default=GRANULARITY_LINES)
    ap.add_argument("--datadir", default="/mnt/ramdisk/numa1/ml")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    if args.sanity:
        sanity(args.workers)
        return

    files = {"light": ("light_5M.jsonl", 5000000),
             "medium": ("medium_5M.jsonl", 5000000),
             "heavy": ("heavy_20M.jsonl", 20000000)}
    workdir = args.workdir or tempfile.mkdtemp(prefix="exectypes_plugins_")
    os.makedirs(workdir, exist_ok=True)
    print("# building plugins -> %s" % workdir, flush=True)
    sos = build_plugins(workdir)
    print(environment_echo(), flush=True)
    rows = []
    for cell in [c.strip() for c in args.cells.split(",") if c.strip()]:
        fname, n_records = files[cell]
        path = os.path.join(args.datadir, fname)
        key, func = VARIANTS[cell]
        for gran, tag in [(args.granularity, "fine")] + (
                [(COARSE_LINES, "coarse")] if args.coarse else []):
            t0 = time.perf_counter()
            ranges = compute_ranges(path, gran)
            setup_s = time.perf_counter() - t0
            avg_lines = n_records / len(ranges)
            print("# %s/%s: %d ranges (~%.0f lines), setup %.1fs"
                  % (cell, tag, len(ranges), avg_lines, setup_s),
                  flush=True)
            st = run_cell(path, n_records, sos[key], func, ranges,
                          args.workers, args.trials)
            print("CELL %s/%s workers=%d median=%.3fs trials=%s "
                  "rate=%.1f rec/s total=%d/%d rss=%.0fMB setup=%.1fs" % (
                      cell, tag, args.workers, st["median_s"],
                      ",".join("%.3f" % t for t in st["trials"]),
                      st["rate"], st["total"], n_records,
                      st["rss_mb"], setup_s), flush=True)
            rows.append((cell, tag, n_records, os.path.getsize(path),
                         args.workers, st))
    print("# RESULT-ROWS %s" % (rows,), flush=True)


if __name__ == "__main__":
    main()
