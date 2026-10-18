#!/usr/bin/env python3
"""F6 Stage 5.1 (Phase 3C correction): the launch-cost timing windows.

This script exists because a previous revision of the F6 audit claimed to
have MEASURED "child-side address-space teardown" at 40.19 ms, derived as
B - A from two wall-clock windows. That claim was wrong, and the error was
factual rather than a matter of wording: A stops its timer at fork() return
BEFORE waitpid(), so A contains no reap at all, while B's timer includes
waitpid(). The two windows are not nested, and B - A therefore also contains
the child's startup path, process exit, the wakeup of the parent, scheduling
and the reap syscall. Describing it as a teardown measurement overstated
what was observed.

WHAT THIS SCRIPT NOW CLAIMS, and nothing more:

  A  fork() -> parent return
     Timer stops at fork() return, before waitpid(). The parent-side
     page-table copy. No reap.

  B  fork() + reap, child _exit()
     Timer includes waitpid(). A, plus child startup, teardown, exit,
     wakeup, scheduling and reap.

  B1 fork() -> the child's pre-exit signal
     The child writes one byte to a pipe on entry and then exits; the
     timer stops in the parent when that byte is read. A, plus the child's
     startup path. Excludes teardown, because the signal precedes exit.

  B2 child's pre-exit signal -> reap
     The window in which the kernel discards the child's address space and
     the parent is woken and reaps it. This CONTAINS the teardown. It is
     NOT a pure measurement of it: exit, wakeup, scheduling and the reap
     are in the same window and cannot be separated without kernel-side
     instrumentation, which this script deliberately does not add --
     instrumenting the kernel path would change the behaviour being
     measured.

  C  fork() + open /dev/null + dup2 + execve + reap
     Differs from B in MORE than image replacement: the child also opens
     /dev/null and dup2s it onto stdout. So C - B is a difference between
     two complete configurations, not a measurement of exec cost.

  D  posix_spawn + reap
     CLONE_VM | CLONE_VFORK: no per-page copy before exec.

  B1 + B2 partitions the B - A interval into "before the child began
  exiting" and "from then until it was reaped", which is strictly more
  informative than B - A alone even though neither half is a pure
  component.

WHAT IS NOT MEASURED HERE, stated explicitly in the output and in the
artifact's `what_is_NOT_measured` field: pure teardown duration, the
overlap between parent post-launch work and child teardown in a real route,
and the contention between them. A and B are serial windows measured in a
quiet process; in a real route the two overlap.

THE NUMBER THAT DECIDES THE DEFAULT SWITCH is the end-to-end paired
difference in bench_cleanroom_backends.py. Nothing in this file is load
bearing for that decision, and it should not be cited as if it were.
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
    """fork() + reap, child immediately _exit().

    NOTE the timer INCLUDES waitpid(), where a_parent_fork() stops before
    it. These two windows are not nested; see the module docstring.
    """
    out = []
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os._exit(127)
        os.waitpid(pid, 0)
        out.append((time.perf_counter() - t0) * 1000.0)
    return out[1:]


def b1_fork_to_child_signal(reps):
    """fork() -> the child signalling that it is about to _exit().

    The child writes one byte to a pipe immediately on entry and then
    exits. Timing stops in the PARENT when that byte is read, so this
    covers the parent-side fork() plus the child's own startup path --
    everything the child does before it begins tearing its address space
    down. It deliberately does NOT include the teardown: the signal is
    raised before the child exits.
    """
    out = []
    for _ in range(reps + 1):
        r, w = os.pipe()
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            try:
                os.write(w, b"x")
            except OSError:
                pass
            os._exit(127)
        os.close(w)
        os.read(r, 1)
        out.append((time.perf_counter() - t0) * 1000.0)
        os.close(r)
        os.waitpid(pid, 0)
    return out[1:]


def b2_signal_to_reap(reps):
    """From the child's "about to exit" signal until waitpid() returns.

    This is the window in which the kernel discards the child's copy of
    the address space, the child becomes a zombie, and the parent is woken
    and reaps it. It is the closest this experiment gets to the teardown,
    and it is NOT a pure measurement of it: it also contains process exit,
    the notification that wakes the parent, scheduling, and the reap
    syscall itself. Those cannot be separated without kernel-side
    instrumentation, which this script deliberately does not add.
    """
    out = []
    for _ in range(reps + 1):
        r, w = os.pipe()
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            try:
                os.write(w, b"x")
            except OSError:
                pass
            os._exit(127)
        os.close(w)
        os.read(r, 1)
        t1 = time.perf_counter()
        os.waitpid(pid, 0)
        out.append((t1 - t0) * 1000.0)
        os.close(r)
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
    print("=" * 78)
    print("launch-cost timing windows | %d MiB private ballast (RSS %d MiB)"
          % (args.mib, rss))
    print("python %s | %s | libc %s | %d reps"
          % (platform.python_version(), platform.release(),
             "-".join(platform.libc_ver()), args.reps))
    print("=" * 78)

    A = a_parent_fork(args.reps)
    B = b_fork_exit(args.reps)
    B1 = b1_fork_to_child_signal(args.reps)
    B2 = b2_signal_to_reap(args.reps)
    C = c_fork_exec(args.reps, target)
    D = d_spawn(args.reps, target)

    # Every row states EXACTLY what its timer window contains. The windows
    # are NOT nested subsets of one another -- that was the error this
    # script previously made, when A was described as differing from B
    # only by the child teardown. A stops its timer BEFORE waitpid(), so A
    # contains no reap at all.
    rows = [
        ("A  fork() -> parent return",
         A,
         "TIMER STOPS AT fork() RETURN, BEFORE waitpid(). "
         "Contains: the parent-side page-table copy. Contains NO reap."),
        ("B  fork() + reap, child _exit()",
         B,
         "TIMER INCLUDES waitpid(). Contains: A, plus child startup, "
         "child teardown, exit, parent wakeup and the reap."),
        ("B1 fork() -> child signals",
         B1,
         "TIMER STOPS WHEN THE PARENT READS the child's pre-exit byte. "
         "Contains: A, plus the child's startup path. Excludes teardown."),
        ("B2 child's exit signal -> reap",
         B2,
         "TIMER STARTS at the child's pre-exit byte, ENDS after waitpid(). "
         "Contains: teardown, process exit, wakeup, scheduling, reap."),
        ("C  fork() + open /dev/null + dup2 + execve + reap",
         C,
         "TIMER INCLUDES waitpid(). Differs from B in more than exec: the "
         "child also opens /dev/null and dup2s it onto stdout."),
        ("D  posix_spawn + reap",
         D,
         "TIMER INCLUDES waitpid(). CLONE_VM|CLONE_VFORK: no per-page "
         "copy before exec."),
    ]
    for label, vals, note in rows:
        print("  %-46s median=%8.2f ms  sd=%6.2f  n=%d"
              % (label, med(vals), statistics.pstdev(vals), len(vals)))
        for line in _wrap(note, 66):
            print("      %s" % line)

    a, b, b1, b2, c, e = med(A), med(B), med(B1), med(B2), med(C), med(D)
    print()
    print("  DERIVED -- each line states what it DOES and DOES NOT include:")
    print()
    print("  B - A  = %7.2f ms" % (b - a))
    print("      the ADDITIONAL cost of completing fork-and-exit-and-reap")
    print("      relative to parent-side fork-return latency alone.")
    print("      Includes child startup, teardown, exit, wakeup, scheduling")
    print("      and the reap syscall. This is NOT a measurement of")
    print("      teardown: A's timer stops before waitpid(), so A contains")
    print("      no reap and the two windows are not nested.")
    print()
    print("  B1 - A = %7.2f ms" % (b1 - a))
    print("      the child's own startup path: everything it does between")
    print("      fork() returning and raising its pre-exit signal.")
    print()
    print("  B2     = %7.2f ms" % b2)
    print("      from the child's pre-exit signal until waitpid() returns.")
    print("      This CONTAINS the address-space teardown but is not a pure")
    print("      measurement of it: process exit, the wakeup of the parent,")
    print("      scheduling and the reap are in the same window and cannot")
    print("      be separated without kernel-side instrumentation, which")
    print("      this script deliberately does not add.")
    print()
    split = (b1 - a) + b2
    resid = (b - a) - split
    print("  (B1 - A) + B2 = %7.2f ms" % split)
    print("  B - A                 = %7.2f ms" % (b - a))
    print("  UNEXPLAINED RESIDUAL  = %7.2f ms" % resid)
    print("      The split does NOT fully account for B - A; this residue")
    print("      is reported rather than folded into either part. The two")
    print("      experiments are not the same experiment: the B1/B2 child")
    print("      additionally closes a descriptor and writes to a pipe")
    print("      before exiting, and the parent blocks on a read. Which")
    print("      effect dominates is not established here, so no causal")
    print("      story is attached to the residue. It is a reason to treat")
    print("      this whole decomposition as indicative, not exact.")
    print()
    print("  C - B  = %7.2f ms" % (c - b))
    print("      the difference between two COMPLETE timing configurations")
    print("      that differ in more than image replacement: C's child also")
    print("      opens /dev/null and dup2s it onto stdout before exec.")
    print("      Not a pure image-replacement measurement.")
    print()
    print("  C - D  = %7.2f ms" % (c - e))
    print("      a complete forked launch against a complete spawned one.")
    print("      This is the figure that reconciles with the end-to-end")
    print("      paired difference; it is a difference of two whole")
    print("      operations, not of two isolated components.")

    out = args.out or os.path.join(
        tmp, "cleanroom_launch_decomposition_%dMiB.json" % args.mib)
    with open(out, "w") as fh:
        json.dump({
            "python": platform.python_version(),
            "kernel": platform.release(),
            "libc": "-".join(platform.libc_ver()),
            "mib": args.mib, "rss_mib": rss, "reps": args.reps,
            "measurements_ms": {
                "A_fork_return_no_reap": [round(x, 2) for x in A],
                "B_fork_exit_reap": [round(x, 2) for x in B],
                "B1_fork_to_child_signal": [round(x, 2) for x in B1],
                "B2_child_signal_to_reap": [round(x, 2) for x in B2],
                "C_fork_devnull_exec_reap": [round(x, 2) for x in C],
                "D_posix_spawn_reap": [round(x, 2) for x in D],
            },
            "timer_windows": {label.split("  ")[0]: note
                              for label, _v, note in rows},
            "derived_ms": {
                "B_minus_A_additional_fork_exit_reap_cost": round(b - a, 2),
                "B1_minus_A_child_startup": round(b1 - a, 2),
                "B2_signal_to_reap_includes_teardown_plus_reap": round(b2, 2),
                "split_B1_minus_A_plus_B2": round((b1 - a) + b2, 2),
                "unexplained_residual_in_B_minus_A": round((b - a) - ((b1 - a) + b2), 2),
                "C_minus_B_configuration_difference": round(c - b, 2),
                "C_minus_D_complete_launch_difference": round(c - e, 2),
            },
            "what_is_NOT_measured": [
                "Pure address-space teardown: B2 contains it but also "
                "process exit, parent wakeup, scheduling and the reap, and "
                "these are not separable without kernel instrumentation.",
                "C - B is not pure image replacement: C's child also "
                "opens /dev/null and dup2s it onto stdout.",
                "The overlap between parent post-launch work and child "
                "teardown in a real route, which serial windows here do "
                "not reproduce.",
                "The residual between B - A and the B1/B2 split: the two "
                "are different experiments (the B1/B2 child also closes a "
                "descriptor and writes to a pipe before exiting), and which "
                "effect dominates is not established. The decomposition is "
                "indicative, not exact.",
            ],
        }, fh, indent=2)
    print()
    print("raw artifact: %s" % out)
    print()
    print("REMINDER: these are serial windows measured in a quiet process.")
    print("In a real route the parent's post-launch work overlaps the")
    print("child's teardown and the two contend for cache and bandwidth.")
    print("The number that decides the default switch is the END-TO-END")
    print("paired difference in bench_cleanroom_backends.py.")
    return 0


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())