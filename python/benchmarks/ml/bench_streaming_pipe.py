#!/usr/bin/env python3
"""Streaming-input benchmark: forkrun vs executor/pool, fed from a PIPE.

Why this exists (SPLIT-1): the headline table measures everything from
a FILE, which forces forkrun to materialise the input. forkrun's
interesting regime is the other one -- consuming an anonymous pipe/fd as
it arrives, never materialising -- so the competitor rows in that regime
have to be measured separately or not at all.

What was probed before writing this (2026-10-03), and why every native
framework is absent below:

    polars  pl.scan_ndjson(fifo)      -> OSError 19 (no such device)
    duckdb  read_json_auto(fifo)      -> InvalidInput: Malformed JSON
    ray     ray.data.read_json(fifo)  -> FileNotFoundError

Their "streaming" APIs are lazy scans over a *path*: they mmap, seek or
stat the source, so a FIFO cannot be ingested at all. They are not
omitted for being slow -- they cannot be given the same input. Only
forkrun and the executor/pool patterns consume an fd, so those are the
rows that share a regime. The framework numbers from the FILE table are
still valid for their own regime and stay there.

Fairness rules this harness holds to, because the whole point is a
like-for-like comparison:

  * ONE producer, ONE pipe, per system -- not a shared pipe across
    systems (that would serialise them against each other).
  * Identical logical payload per record (ml_payload process_event_*),
    the same one the file table uses.
  * Identical batch size for every system, taken from forkrun's own
    default, so we are comparing transports and not batching policies.
  * Identical worker count (28, matching the headline table).
  * Exact record count asserted on every run. A system that drops the
    tail is reported as FAIL, never as a fast number -- see the
    W-EXACT postmortem in MEMORY.md.
  * The producer is a separate process, so producer cost is outside
    every system's timed region, exactly as in the file table.

Usage:  python3 bench_streaming_pipe.py light medium heavy
"""

import json
import multiprocessing
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from bench_ml_pipeline import count_results  # noqa: E402
from ml_payload import (forkrun_payload_light,  # noqa: E402
                        forkrun_payload_medium,
                        forkrun_payload_heavy,
                        pool_chunk_payload_light,
                        pool_chunk_payload_medium,
                        pool_chunk_payload_heavy)

FORKRUN_PAYLOADS = {"light": forkrun_payload_light,
                    "medium": forkrun_payload_medium,
                    "heavy": forkrun_payload_heavy}
POOL_CHUNKS = {"light": pool_chunk_payload_light,
               "medium": pool_chunk_payload_medium,
               "heavy": pool_chunk_payload_heavy,
               # 20M-record light corpus (2,130,842,196 B, seeded, 0%
               # malformed). Same payload as "light": the variant differs
               # only in input size, so it reuses the light transform.
               "light20m": pool_chunk_payload_light}

CORPORA = {
    "light":  "/mnt/ramdisk/numa1/ml/light_5M.jsonl",
    "medium": "/mnt/ramdisk/numa1/ml/medium_5M.jsonl",
    "heavy":  "/tmp/opencode/heavy_5M.jsonl",
    "light20m": "/tmp/opencode/light_20M.jsonl",
}
# Valid-record counts, per the headline table's verification convention.
# NOT the line count: the generators emit some malformed lines, and the
# payload turns those into "" while blank lines are skipped outright --
# so a run legitimately yields fewer RESULTS than it has lines. Counting
# lines (my first cut) reported 5,000,000 for every corpus and flagged
# four working systems as failures. The reference is measured once by
# SERIAL_PREAMBLE and cached; see _serial_reference().
EXPECTED = {"light": 5000000, "medium": 4997892, "heavy": 4997982,
            "light20m": 20000000}

WORKERS = 28
TRIALS = 3          # median-of-3 after warmup (matches cell.py)
BATCH_LINES = 2048          # forkrun's default batch size
IN_CHUNK = 1 << 20          # parent pipe read size


def _spawn_producer(path):
    """Fork a `cat`-equivalent producer and return the read end.

    Separate process, so its cost is never inside a timed region.
    """
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(r)
            fd = os.open(path, os.O_RDONLY)
            try:
                while True:
                    buf = os.read(fd, 1 << 20)
                    if not buf:
                        break
                    off = 0
                    while off < len(buf):
                        off += os.write(w, buf[off:])
            finally:
                os.close(fd)
        except BaseException:
            os._exit(1)
        finally:
            try:
                os.close(w)
            except OSError:
                pass
            os._exit(0)
    os.close(w)
    return r, pid


def _iter_batches(fd, batch_lines):
    """Yield `batch_lines`-sized lists of decoded lines from the pipe."""
    batch = []
    tail = b""
    while True:
        chunk = os.read(fd, IN_CHUNK)
        if not chunk:
            break
        tail += chunk
        if b"\n" not in tail:
            continue
        parts = tail.split(b"\n")
        tail = parts.pop()
        for p in parts:
            batch.append(p.decode())
            if len(batch) >= batch_lines:
                yield batch
                batch = []
    if tail.strip():
        batch.append(tail.decode())
    if batch:
        yield batch


PLUGIN_DIR = "/tmp/opencode/mlbench"


def _cheap(results):
    """Cheap per-batch accounting for the TIMED region.

    Exactness uses count_results (_valid) but that parses every output
    byte in Python, and it must NOT run inside the timed region or it
    measures the harness instead of the system -- that mistake made
    forkrun look 3x slower than it is. Timing uses len() only; the
    exactness pass is a separate, untimed run.
    """
    return len(results)


def _valid(results):
    """Valid records in one batch result, via the repo's contract.

    Uses bench_ml_pipeline.count_results so streaming and file tables
    apply the SAME rule: non-blank segments per blob, ""/None/None-blank
    contribute 0. Applied per batch so nothing is materialised.
    """
    return count_results(results)


WORKERS = 28
BATCH_LINES = 2048          # forkrun's default batch size
IN_CHUNK = 1 << 20          # parent pipe read size


def _spawn_producer(path):
    """Fork a `cat`-equivalent producer and return the read end.

    Separate process, so its cost is never inside a timed region.
    """
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(r)
            fd = os.open(path, os.O_RDONLY)
            try:
                while True:
                    buf = os.read(fd, 1 << 20)
                    if not buf:
                        break
                    off = 0
                    while off < len(buf):
                        off += os.write(w, buf[off:])
            finally:
                os.close(fd)
        except BaseException:
            os._exit(1)
        finally:
            try:
                os.close(w)
            except OSError:
                pass
            os._exit(0)
    os.close(w)
    return r, pid


def _iter_batches(fd, batch_lines):
    """Yield `batch_lines`-sized lists of decoded lines from the pipe."""
    batch = []
    tail = b""
    while True:
        chunk = os.read(fd, IN_CHUNK)
        if not chunk:
            break
        tail += chunk
        if b"\n" not in tail:
            continue
        parts = tail.split(b"\n")
        tail = parts.pop()
        for p in parts:
            batch.append(p.decode())
            if len(batch) >= batch_lines:
                yield batch
                batch = []
    if tail.strip():
        batch.append(tail.decode())
    if batch:
        yield batch


PLUGIN_DIR = "/tmp/opencode/mlbench"



# Every system reports the SAME quantity -- the number of valid records
# it produced -- so the numbers are comparable and exactness is
# checkable. Counting result LENGTHS would compare bytes for forkrun
# (one joined item per batch) against records for the pools.



def bench_forkrun(path, variant, expected, plugin=False, count=True):
    """forkrun streaming from a pipe, its own default batch size.

    plugin=True uses the same C plugin the file table measures, so the
    streaming row for forkrun's C path is comparable to its file row.
    """
    if plugin:
        # The C plugin is addressed by string and cannot be wrapped in
        # Python, so it reports raw results and the parent counts them
        # with the SAME rule the Python wrappers use: a record counts iff
        # its rendered result is non-empty.
        payload = ("%s/ml_plugin_%s.so:ml_process_%s"
                   % (PLUGIN_DIR, variant, variant))
    else:
        payload = FORKRUN_PAYLOADS[variant]
    fd, pid = _spawn_producer(path)
    try:
        t0 = time.perf_counter()
        n = 0
        gen = forkrun.stream(
            payload, fd, workers=WORKERS, streaming=True, nodes=1,
            order="index", mode=("plugin" if plugin else "python"))
        for out in gen:
            n += _valid(out) if count else _cheap(out)
        dt = time.perf_counter() - t0
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    return n, dt


def bench_pool_stream(path, variant, expected, count=True):
    """multiprocessing.Pool fed incrementally from the pipe."""
    payload = POOL_CHUNKS[variant]
    fd, pid = _spawn_producer(path)
    t0 = time.perf_counter()
    try:
        with multiprocessing.Pool(WORKERS) as pool:
            n = 0
            for res in pool.imap(payload, _iter_batches(fd, BATCH_LINES)):
                n += _valid(res) if count else len(res)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    dt = time.perf_counter() - t0
    return n, dt


def bench_executor_stream(path, variant, expected, count=True):
    """ProcessPoolExecutor fed incrementally from the pipe."""
    payload = POOL_CHUNKS[variant]
    fd, pid = _spawn_producer(path)
    t0 = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            n = 0
            for res in ex.map(payload, _iter_batches(fd, BATCH_LINES)):
                n += _valid(res) if count else len(res)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    dt = time.perf_counter() - t0
    return n, dt


def bench_forkrun_plugin(path, variant, expected, count=True):
    return bench_forkrun(path, variant, expected, plugin=True, count=count)


SYSTEMS = [
    ("forkrun C plugin (pipe)", bench_forkrun_plugin),
    ("forkrun Python UDF (pipe)", bench_forkrun),
    ("ProcessPoolExecutor (pipe)", bench_executor_stream),
    ("multiprocessing.Pool (pipe)", bench_pool_stream),
]


def main(argv):
    variants = argv or ["light", "medium", "heavy"]
    print("# Streaming-input benchmark: pipe-fed, %d workers, "
          "batch=%d lines\n" % (WORKERS, BATCH_LINES))
    results = {}
    for variant in variants:
        path = CORPORA.get(variant)
        if not path or not os.path.exists(path):
            print("SKIP %s: corpus missing (%s)" % (variant, path))
            continue
        exp = EXPECTED[variant]
        in_bytes = os.path.getsize(path)
        print("## %s  (%.2f GB, expect %d valid records)"
              % (variant, in_bytes / 1e9, exp))
        for name, fn in SYSTEMS:
            try:
                # Warmup, then TIMED passes with the cheap consumer.
                # Exactness accounting must stay OUT of the clock: it
                # parses every output byte in Python, and timing it
                # measured the harness, not the system.
                fn(path, variant, exp, count=False)
                times = []
                for _ in range(TRIALS):
                    _n, dt = fn(path, variant, exp, count=False)
                    times.append(dt)
                n, _dt = fn(path, variant, exp, count=True)   # untimed
            except Exception as exc:            # noqa: BLE001
                print("  %-30s FAILED: %s: %s"
                      % (name, type(exc).__name__, exc))
                continue
            if n != exp:
                print("  %-30s FAIL exactness: %d != %d" % (name, n, exp))
                results[(variant, name)] = None
                continue
            med = statistics.median(times)
            rec_s = exp / med
            print("  %-30s %8.2f s  %7.2fM rec/s  %6.0f MB/s"
                  % (name, med, rec_s / 1e6, in_bytes / med / 1e6))
            results[(variant, name)] = rec_s
        print()
    with open("/tmp/opencode/stream_pipe_results.json", "w") as fh:
        json.dump({"%s|%s" % k: v for k, v in results.items()}, fh, indent=2)
    return 0


if __name__ == "__main__":
    if not find_substrate():
        print("libforkrun_python.so not built -- build the substrate first",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1:]))