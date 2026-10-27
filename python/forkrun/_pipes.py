"""Pipe capacity utilities (W-PY15).

Linux pipes default to 64KB (16 pages). forkrun's Python-frontend pipes
fall into two groups, and they want OPPOSITE things.

General-purpose pipes want to be LARGE, so a batch-sized transfer does
not block on a 64KB pipe:

- Spawn stdin/stdout: 1MB allows batch-sized transfers without
  intermediate blocking. Set in C at creation (fr_py_exec_spawn); this
  module covers the Python-created pipes.

The worker-completion NOTIFICATION pipe is the opposite. Its capacity IS
the producer's run-ahead window. A worker that finishes a batch writes
one notification; the parent reads them. The pipe holds N notifications,
so N is how many completions may be outstanding before a worker blocks
writing its notification -- and a blocked worker cannot claim its next
batch. The per-worker output memfds have no backpressure of their own,
so this pipe is the ONLY thing bounding how far a worker may run ahead
of the consumer.

For the public stream() paths that window was 1MB (65536 outstanding
16-byte notifications), which let workers run a very long way ahead of a
slow consumer. That is the measured shape behind TD-13: parent peak
retention scaling with total amplified output (~0.5x OUTPUT bytes)
rather than with a bounded window. The stream paths now ask for
STREAM_NOTIFY_PIPE_SIZE (4KB = 256 notifications), the same order of
window the bash frontend's ack pipe uses (ORDER_PIPE_SIZE=4096, the H3
backpressure invariant). The map/run paths still ask for 1MB: they
collect every result, so there is no slow consumer to run ahead of.

Deliberately NEVER bumped: the engine ack pipe (H3 invariant -- 4KB for
backpressure), escrow/death pipes (engine-owned), or anything in
forkrun_ring.c (frozen).

F_SETPIPE_SZ needs Linux 2.6.35+ and is capped by
/proc/sys/fs/pipe-max-size (usually 1MB); above the cap needs
CAP_SYS_RESOURCE. Everything here falls back to the default capacity
silently -- capacity is an optimization, never correctness.
"""

from __future__ import annotations

import fcntl
import os

DEFAULT_PIPE_SIZE = 64 * 1024  # Linux default (16 pages)
LARGE_PIPE_SIZE = 1024 * 1024  # 1MB (== default pipe-max-size)

#: Capacity requested for the worker-completion notification pipe on the
#: public stream() paths. 4096 bytes holds 256 queued 16-byte completion
#: notifications, and that count IS the producer run-ahead window: a
#: worker with this many completions outstanding blocks in its
#: notification write and cannot claim another batch.
#:
#: This is the same order of window as the bash frontend's ack pipe
#: (ORDER_PIPE_SIZE=4096). The bash frontend is the reference
#: implementation, and its small ACK-pipe feedback mechanism is the
#: conceptual model for this change.
STREAM_NOTIFY_PIPE_SIZE = 4096

#: Measurement-only override for STREAM_NOTIFY_PIPE_SIZE.
#:
#: It exists so the A/B comparison can run both arms of the experiment
#: on ONE build, with nothing but the capacity differing. It is NOT a
#: product knob: with it unset the capacity is STREAM_NOTIFY_PIPE_SIZE,
#: and that constant is the unambiguous default in code.
#:
#: The value is a capacity in BYTES. The completion notification is 16
#: bytes, so a capacity of N bytes holds N/16 notifications.
_STREAM_NOTIFY_SIZE_ENV = "FORKRUN_STREAM_NOTIFY_PIPE_SIZE"

#: DIAGNOSTIC: the ACTUAL capacity (F_GETPIPE_SZ) of the most recently
#: created stream notification pipe in this process. Tests and benchmark
#: probes read this to report what the kernel really granted rather
#: than what was requested -- a best-effort F_SETPIPE_SZ that the kernel
#: refuses must never be reported as the size that was asked for.
#: Not part of the public API.
_last_stream_notify_capacity = None


def get_pipe_capacity(fd) -> int:
    """Return a pipe fd's current capacity in bytes.

    Returns DEFAULT_PIPE_SIZE when the query is unavailable (non-Linux,
    old kernel) — callers treat it as "at least default".
    """
    try:
        return fcntl.fcntl(fd, fcntl.F_GETPIPE_SZ)
    except (OSError, AttributeError):
        return DEFAULT_PIPE_SIZE


def set_pipe_capacity(fd, size: int) -> int:
    """Best-effort set of a pipe's capacity; returns the actual size.

    Never raises: on failure (permissions, cap, old kernel) the pipe
    keeps its current capacity and that is what is returned.
    """
    try:
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, size)
    except (OSError, AttributeError):
        pass
    return get_pipe_capacity(fd)


def make_pipe(size: int = LARGE_PIPE_SIZE) -> tuple:
    """Create a pipe sized to `size` (best-effort).

    Returns (read_fd, write_fd, actual_capacity). os.pipe() fds are
    non-inheritable (PEP 446); sizing via fcntl does not change that.
    """
    r, w = os.pipe()
    try:
        return r, w, set_pipe_capacity(w, size)
    except Exception:
        return r, w, DEFAULT_PIPE_SIZE


def stream_notify_pipe_size() -> int:
    """The capacity, in bytes, to request for stream notification pipes.

    STREAM_NOTIFY_PIPE_SIZE unless the measurement-only environment
    override is set to a positive value.
    """
    raw = os.environ.get(_STREAM_NOTIFY_SIZE_ENV, "")
    if raw.strip():
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return STREAM_NOTIFY_PIPE_SIZE


def make_stream_notify_pipe() -> tuple:
    """Create the SMALL worker-completion notification pipe.

    Same return shape as make_pipe() -- (read_fd, write_fd,
    actual_capacity) -- so a caller that does not care about the
    capacity can ignore it here too.

    The capacity is best effort: F_SETPIPE_SZ can be refused (an
    unprivileged process may not exceed the user page limit), and then
    the pipe keeps whatever capacity it already had. The ACTUAL capacity
    is what the returned third element reports, and it is also recorded
    for last_stream_notify_capacity().
    """
    global _last_stream_notify_capacity
    r, w = os.pipe()
    try:
        actual = set_pipe_capacity(w, stream_notify_pipe_size())
    except Exception:
        actual = DEFAULT_PIPE_SIZE
    _last_stream_notify_capacity = actual
    return r, w, actual


def last_stream_notify_capacity():
    """DIAGNOSTIC: actual capacity of the last stream notification pipe.

    None if this process has not created one yet. Tests and benchmark
    probes use it to report the capacity the kernel granted. Not part of
    the public API.
    """
    return _last_stream_notify_capacity


__all__ = ["DEFAULT_PIPE_SIZE", "LARGE_PIPE_SIZE", "STREAM_NOTIFY_PIPE_SIZE",
           "get_pipe_capacity", "set_pipe_capacity", "make_pipe",
           "stream_notify_pipe_size", "make_stream_notify_pipe",
           "last_stream_notify_capacity"]
