"""FD scrubbing for forked children (W-PY16 addendum).

When forkrun runs inside a process with an event loop (opencode,
Jupyter, asyncio applications, IDEs, debuggers), forked children
inherit the event loop's file descriptors: epoll fds, timerfds,
eventfds, sockets, pipes. A child that polls or reads those fds
corrupts the parent's event loop state and deadlocks.

Observed shape (opencode): the parent holds an epoll fd, timerfds,
and LSP/watcher sockets. A forked child inherits them all; engine
poll() sets can intersect those numbers, timer ticks get consumed in
the wrong process, and parent/child end up waiting on each other.

THE FIX: every forked child calls scrub_fds() immediately after fork,
keeping ONLY an explicit set (its engine/job fds) plus 0/1/2 (error
messages must reach the user). CLOEXEC does not help: it acts on
exec(), and forkrun's children never exec (they run C directly).

The keep set MUST include the engine's own fds (escrow pipes,
eventfds) — not just the job fds. Closing those breaks escrow
retry/poison (silent retry loss: the deposit return is unchecked) and
forces claim-polling into POLLNVAL hot-spins. Callers snapshot them
(see run.py: fds present after fr_py_init minus fds present before).
"""

from __future__ import annotations

import os
import sys


def scrub_fds(keep_fds, quiet=True) -> int:
    """Close all inherited fds except keep_fds plus 0/1/2.

    keep_fds: iterable of int fds the child needs (job fds + the
      engine-fd snapshot). 0/1/2 always kept.
    Returns the number of fds closed. Best-effort and never raises:
    without /proc/self/fd (non-Linux, chroot) it returns 0 having
    closed nothing.
    MUST be called in every forked child before any engine work.
    """
    keep = set(keep_fds) | {0, 1, 2}
    try:
        entries = os.listdir("/proc/self/fd")
    except (OSError, AttributeError):
        return 0
    closed = 0
    for entry in entries:
        try:
            fd = int(entry)
        except ValueError:
            continue
        if fd in keep:
            continue
        try:
            os.close(fd)
            closed += 1
        except OSError:
            pass
    if not quiet and closed > 0:
        try:
            sys.stderr.write(
                "[fd_scrub] closed %d inherited fds\n" % closed)
        except Exception:
            pass
    return closed


def verify_scrubbed(keep_fds) -> list:
    """List open fds outside keep_fds plus 0/1/2 ([] when clean).

    Test helper: fails loudly when scrubbing regresses. Returns []
    (not raises) when /proc/self/fd is unavailable.
    """
    keep = set(keep_fds) | {0, 1, 2}
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError:
        return []
    leaked = []
    for entry in entries:
        try:
            fd = int(entry)
        except ValueError:
            continue
        if fd not in keep:
            leaked.append(fd)
    return leaked


def snapshot_fds() -> set:
    """Current open-fd set (for engine-fd differencing)."""
    try:
        return {int(n) for n in os.listdir("/proc/self/fd")}
    except (OSError, ValueError):
        return set()


__all__ = ["scrub_fds", "verify_scrubbed", "snapshot_fds"]
