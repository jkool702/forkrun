#!/usr/bin/env python3
"""F6 Stage 5 (Phase 3C): separating the launch-cost components.

The end-to-end benchmark shows a large difference between the backends at
2 GiB of private ballast. An earlier report explained the gap by
subtracting the isolated spawn time from the end-to-end difference and
calling the remainder "child-side teardown". That arithmetic is valid but
the causal label was not earned: subtracting one wall-clock duration from
another does not measure a concurrent activity, and this file exists to
replace the inference with a measurement that does isolate it.

WHAT IS MEASURED DIRECTLY, in the same process, same ballast:

  A  PARENT-SIDE FORK
     Time from the call to os.fork() until it returns in the parent. This
     is the page-table copy the parent pays, and nothing else.

  B  CHILD-SIDE TEARDOWN
     A is timed alone. B is timed as fork() + waitpid() with a child that
     immediately _exit()s. Both pay the same parent-side copy and the same
     reap/scheduling; the difference is the work the CHILD does discarding
     its own copy of the address space. Because _exit() performs that
     teardown and execve() performs the same teardown as part of replacing
     the image, this measures the component directly rather than
     inferring it from a difference of two unrelated totals.

  C  EXEC OVER THE TOP
     fork() + execve() + waitpid(), for completeness: it is B plus the
     cost of loading and replacing the program image.

  D  posix_spawn EQUIVALENTS
     The same three shapes with os.posix_spawn, which shares the address
     space with the parent until execve (CLONE_VM | CLONE_VFORK), so it
     pays no per-page copy.

WHAT IS *NOT* MEASURED HERE, and is deliberately left to the end-to-end
benchmark: the parent-side work that overlaps with the child's teardown,
and any cache or bandwidth contention between them. A and B are measured
serially in a quiet process; in a real route the two overlap, so
A + B is an upper bound on the serial cost and the end-to-end paired
difference is the number that actually matters.

The conclusion the default switch rests on is the END-TO-END paired
difference, not this decomposition.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "python"))

_PAGE = os.sysconf("SC_PAGE_SIZE")


def med(vals):
    return statistics.median(vals) if vals else float("nan")


def private_ballast(mib):
    if not mib:
        return None
    chunk = 4 * 1024 * 1024
    blocks = [bytearray(chunk) for _ in range((mib * 1024 * 1024) // chunk)]
    for i, b in enumerate(blocks):
        for off in range(0, chunk, 4096):
            b[off] = i & 0xFF
    return blocks


def a_parent_fork(reps):
    """Time os.fork() only, as seen by the parent."""
    out = []
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os._exit(127)
        out.append((time.perf_counter() - t0) * 1000.0)
        os.waitpid(pid, 0)
    return out[1:]


def b_fork_exit(reps):
    """fork() + reap, child immediately _exit(): adds child-side teardown."""
    out = []
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os._exit(127)
        os.waitpid(pid, 0)
        out.append((time.perf_counter() - t0) * 1000.0)
    return out[1:]


def c_fork_exec(reps, target):
    """fork() + execve + reap."""
    out = []
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            try:
                fd = os.open("/dev/null", os.O_WRONLY)
                os.dup2(fd, 1)
                os.execv(target, [target])
            except BaseException:
                pass
            os._exit(127)
        os.waitpid(pid, 0)
        out.append((time.perf_counter() - t0) * 1000.0)
    return out[1:]


def d_spawn(reps, target):
    """posix_spawn + reap."""
    out = []
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        pid = os.posix_spawn(target, [target], os.environ)
        os.waitpid(pid, 0)
        out.append((time.perf_counter() - t0) * 1000.0)
    return out[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mib", type=int, default=2048)
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="fr-decomp-")
    target = os.path.join(tmp, "noop")
    with open(target, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(target, 0o755)

    ballast = private_ballast(args.mib)
    rss = int(open("/proc/self/statm").read().split()[1]) * (_PAGE // 1024) \
        // 1024
    print("=" * 74)
    print("launch-cost decomposition | %d MiB private ballast (RSS %d MiB)"
          % (args.mib, rss))
    print("python %s | %s | libc %s | %d reps"
          % (platform.python_version(), platform.release(),
             "-".join(platform.libc_ver()), args.reps))
    print("=" * 74)

    A = a_parent_fork(args.reps)
    B = b_fork_exit(args.reps)
    C = c_fork_exec(args.reps, target)
    D = d_spawn(args.reps, target)
    E = d_spawn(args.reps, target)

    rows = [
        ("A  parent-side fork() only", A,
         "page-table copy, parent side"),
        ("B  fork() + reap, child _exit()", B,
         "A + child-side address-space teardown + reap"),
        ("C  fork() + execve() + reap", C,
         "B + loading and replacing the program image"),
        ("D  posix_spawn + reap", E,
         "no per-page copy: CLONE_VM | CLONE_VFORK until execve"),
    ]
    for label, vals, note in rows:
        print("  %-32s median=%8.2f ms  sd=%6.2f  n=%d"
              % (label, med(vals), statistics.pstdev(vals), len(vals)))
        print("      %s" % note)

    a, b, c, e = med(A), med(B), med(C), med(E)
    print()
    print("  child-side teardown  (B - A) = %8.2f ms   <- MEASURED, not inferred"
          % (b - a))
    print("  exec over teardown   (C - B) = %8.2f ms   <- MEASURED"
          % (c - b))
    print("  forked vs spawn      (C - D) = %8.2f ms   <- MEASURED"
          % (c - e))
    print()
    print("  NOTE: A and B are measured serially in a quiet process. In a real")
    print("  route the parent's post-launch work OVERLAPS the child's")
    print("  teardown, so A + B overstates the serial cost, and the two also")
    print("  contend for cache and memory bandwidth. The number that decides")
    print("  the default switch is the END-TO-END paired difference in")
    print("  bench_cleanroom_backends.py, not this sum.")

    out = args.out or os.path.join(
        tmp, "cleanroom_launch_decomposition_%dMiB.json" % args.mib)
    with open(out, "w") as fh:
        json.dump({
            "python": platform.python_version(),
            "kernel": platform.release(),
            "libc": "-".join(platform.libc_ver()),
            "mib": args.mib, "rss_mib": rss, "reps": args.reps,
            "A_parent_fork_ms": [round(x, 2) for x in A],
            "B_fork_exit_ms": [round(x, 2) for x in B],
            "C_fork_exec_ms": [round(x, 2) for x in C],
            "D_posix_spawn_ms": [round(x, 2) for x in E],
            "derived": {
                "child_side_teardown_ms": round(b - a, 2),
                "exec_over_teardown_ms": round(c - b, 2),
                "forked_minus_spawn_ms": round(c - e, 2),
            },
            "caveat": "A and B are serial measurements in a quiet process; "
                      "in a real route they overlap and contend.",
        }, fh, indent=2)
    print()
    print("raw artifact: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())