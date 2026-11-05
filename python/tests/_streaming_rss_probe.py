#!/usr/bin/env python3
"""Isolated probe: measure CURRENT RSS of a forkrun streaming PARENT.

WO-PY-REL-1 Workstream B.

Why a separate process
----------------------
The thing being measured is the process that calls `forkrun.stream()` and
consumes its output. Measuring it from the unittest runner cannot work:
the runner has already imported every test module, built plugin fixtures
and forked workers, so its resident set is dominated by unrelated state,
and no sampling scheme can separate the two.

Why CURRENT RSS, not a ru_maxrss delta
--------------------------------------
`ru_maxrss` is a process PEAK. `after - before` is therefore not "memory
this workload used" -- it is "the largest transient allocation observed
anywhere in the process between the two samples", which any unrelated
thread, GC pause or import can supply. That is the defect this file
exists to replace. Current RSS comes from /proc/self/statm field 2
(resident pages), which goes down as well as up.

Sampling
--------
Sampled in the consumer loop, not once at the end. A single sample after
the generator is exhausted measures the final state, which for a bounded
stream is dominated by whatever the consumer chose to keep -- the exact
opposite of what we want to observe. No monitoring THREAD is used: this
process is about to fork workers, and forking from a threaded process is
a documented hazard in this codebase.

Units are KiB, stated explicitly. Linux `ru_maxrss` is KiB but macOS
bytes; /proc/self/statm is Linux-only, which is fine here because
SC_PAGE_SIZE is the unit that actually matters.
"""

import argparse
import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is <repo>/python/tests, so its parent is the directory holding
# the forkrun PACKAGE. (Joining "python" onto it yields <repo>/python/python,
# which is how the first version of this file failed to import anything.)
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)


def current_rss_kb():
    """Resident set size in KiB, from /proc/self/statm.

    statm field 2 is "resident" in pages. Preferred over parsing
    /proc/self/status VmRSS because it is one short line and one read,
    and this is called once per batch.
    """
    try:
        with open("/proc/self/statm", "rb") as fh:
            resident_pages = int(fh.read().split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return resident_pages * (os.sysconf("SC_PAGE_SIZE") // 1024)


def produced_output_bytes():
    """Bytes the workers have written into the per-worker OUTPUT memfds.

    The parent holds every worker's output memfd open (they are created
    pre-fork so the parent can pread them), and they are named
    "forkrun_out<N>".

    NOTE WHAT THIS IS NOT: a memfd is never truncated, so this is the
    TOTAL OUTPUT PRODUCED SO FAR, not the part still unconsumed. The
    SIGNAL is therefore the SHAPE, not the value: while the workers are
    blocked by the notification pipe the figure PLATEAUS (they stop
    producing), and it resumes climbing only as the consumer drains and
    frees them. A figure that climbs straight to the total means the
    workers were never blocked.

    Parent RSS cannot answer this at all: the memfd pages are
    page-cache backed, and the parent preads them into a buffer rather
    than mapping them, so they are in neither the parent's nor the
    workers' RSS. Measuring only the parent's RSS therefore cannot
    distinguish "the pipeline is bounded" from "the output is parked in
    the memfds" -- which is the distinction that decides whether the
    notification pipe actually reached the workers.
    """
    total = 0
    try:
        names = os.listdir("/proc/self/fd")
    except OSError:
        return None
    for name in names:
        try:
            target = os.readlink("/proc/self/fd/" + name)
        except OSError:
            continue
        # The link is "/memfd:forkrun_out<N> (deleted)".
        if "memfd:forkrun_out" not in target:
            continue
        try:
            total += os.fstat(int(name)).st_size
        except (OSError, ValueError):
            pass
    return total


def child_rss_kb():
    """Summed RSS of this process's live children (the workers).

    The same caveat as above: a worker's RSS is its own heap, not the
    output it has already handed to the memfd. The two numbers together
    are what the pipeline costs.
    """
    import glob
    page = os.sysconf("SC_PAGE_SIZE") // 1024
    total = 0
    for d in glob.glob("/proc/self/task/*/children"):
        try:
            kids = [int(x) for x in open(d).read().split()]
        except (OSError, ValueError):
            continue
        for kid in kids:
            try:
                with open("/proc/%s/statm" % kid) as fh:
                    total += int(fh.read().split()[1]) * page
            except (OSError, ValueError, IndexError):
                pass
    return total


def write_corpus(path, n):
    """Same fixture shape the original test used (_helpers.write_lines)."""
    with open(path, "w") as fh:
        for i in range(n):
            fh.write("line %d\n" % i)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=800000)
    ap.add_argument("--amp", type=int, default=5,
                    help="payload output multiplier")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--order", default="none")
    ap.add_argument("--orchestrator", default="0")
    ap.add_argument("--delay", type=float, default=0.001,
                    help="consumer delay; this is the SLOW consumer")
    ap.add_argument("--collect", action="store_true",
                    help="retain every blob (the accumulate regression)")
    ap.add_argument("--c-drain", dest="c_drain", action="store_true",
                    help="use the C drain (c_drain=True) instead of the "
                         "legacy Python drain. The C drain has its own "
                         "results pipe, which is a SEPARATE backpressure "
                         "stage from the notification pipe this probe "
                         "measures.")
    args = ap.parse_args(argv)

    import forkrun
    from _helpers import write_lines
    from forkrun import _pipes

    tmp = tempfile.mkdtemp(prefix="rssprobe-")
    path = os.path.join(tmp, "in.txt")
    write_lines(path, args.lines)

    amp = args.amp

    def amplify(batch):
        return bytes(batch.data) * amp

    orchestrator = args.orchestrator == "1"

    # Baseline AFTER setup: corpus written, forkrun imported. The original
    # test took its baseline before the run but inside the unittest
    # process, where setup allocations from unrelated tests were already
    # inside the peak -- which is part of why its number was unstable.
    base = current_rss_kb()

    # Reset the diagnostic so the capacity reported below is the one THIS
    # run created, not a leftover from an earlier call in this process.
    _pipes._last_stream_notify_capacity = None

    peak = base
    blobs = 0
    out_bytes = 0
    kept = []
    samples = []
    first_result_s = None
    peak_unread_output = 0
    peak_child_rss = 0
    t0 = time.monotonic()
    for blob in forkrun.stream(amplify, path, workers=args.workers,
                               nodes=1, orchestrator=orchestrator,
                               order=args.order, c_drain=args.c_drain):
        if first_result_s is None:
            first_result_s = time.monotonic() - t0
        blobs += 1
        out_bytes += len(blob)
        r = current_rss_kb()
        if r is not None:
            samples.append(r)
            if r > peak:
                peak = r
        unread = produced_output_bytes()
        if unread is not None and unread > peak_unread_output:
            peak_unread_output = unread
        kids = child_rss_kb()
        if kids is not None and kids > peak_child_rss:
            peak_child_rss = kids
        if args.collect:
            kept.append(blob)
        else:
            del blob
        time.sleep(args.delay)
    wall_s = time.monotonic() - t0

    final = current_rss_kb()
    result = {
        "mode": "collect" if args.collect else "stream",
        "lines": args.lines,
        "amp": amp,
        "workers": args.workers,
        "order": args.order,
        "orchestrator": orchestrator,
        "c_drain": bool(args.c_drain),
        "delay": args.delay,
        "input_bytes": os.path.getsize(path),
        "blobs": blobs,
        "out_bytes": out_bytes,
        "baseline_kb": base,
        "peak_kb": peak,
        "final_kb": final,
        "growth_kb": None if base is None else peak - base,
        "samples": len(samples),
        # The UPSTREAM half of the backpressure chain: output produced
        # into the per-worker memfds but not yet consumed by the parent.
        "peak_produced_output_bytes": peak_unread_output,
        "peak_child_rss_kb": peak_child_rss,
        # The ACTUAL capacity the kernel granted the notification pipe
        # this run created (F_GETPIPE_SZ), not the size that was
        # requested. A best-effort F_SETPIPE_SZ the kernel refuses must
        # never be reported as the size that was asked for.
        "notify_pipe_capacity": _pipes.last_stream_notify_capacity(),
        "notify_pipe_capacity_requested": _pipes.stream_notify_pipe_size(),
        "wall_s": wall_s,
        "first_result_s": first_result_s,
        "records_per_s": (blobs / wall_s) if wall_s > 0 else None,
        "out_bytes_per_s": (out_bytes / wall_s) if wall_s > 0 else None,
        # Kept live so the interpreter does not free it early and flatter
        # the final reading; the consumer is supposed to be retaining it.
        "retained_bytes": sum(len(b) for b in kept),
    }
    try:
        os.unlink(path)
        os.rmdir(tmp)
    except OSError:
        pass
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())