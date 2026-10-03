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
retry/poison and forces claim-polling into POLLNVAL hot-spins.
Callers snapshot them
(see run.py: fds present after fr_py_init minus fds present before).
W-REL2/R14a: a refused deposit is no longer a silent-continue even
when the keep set is right (closed fd, blocking/EBADF) — the return
is checked, retried once, then poison-skipped LOUDLY (§6: escrow
advisory, never required for forward progress).
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
    """Current open-fd set (for engine-fd differencing).

    The listdir is validated, not trusted. ``os.listdir("/proc/self/fd")``
    opens its own transient directory descriptor, and that descriptor's
    NUMBER appears in the listing -- so a naive read returns an fd that
    is already closed by the time we return.

    That is not cosmetic. Callers compute ``engine_fds =
    snapshot_fds() - pre_fds``: if pre_fds holds a phantom N, and the
    engine's first descriptor is later allocated as N, the subtraction
    cancels a REAL engine fd out of the set. Workers then do not scrub
    it and inherit the engine's memfd/eventfd, where a poll on it never
    blocks. Measured here: pre_fds=[0,1,2,3,4] with 4 a phantom; engine
    init then opens 4 and 5; computed engine_fds=[5,6] -- 4 dropped.

    So re-check each number with fstat after the listing closes. A
    number the kernel has already recycled fails fstat and is dropped,
    which is exactly the behaviour wanted: it was never ours.
    """
    try:
        names = os.listdir("/proc/self/fd")
    except (OSError, ValueError):
        return set()
    live = set()
    for name in names:
        try:
            fd = int(name)
            os.fstat(fd)
        except (OSError, ValueError):
            continue          # transient (or already recycled): not ours
        live.add(fd)
    return live


__all__ = ["scrub_fds", "verify_scrubbed", "snapshot_fds"]
