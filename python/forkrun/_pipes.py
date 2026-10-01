"""Pipe capacity utilities (W-PY15).

Linux pipes default to 64KB (16 pages). forkrun's Python-frontend pipes
benefit from 1MB:

- Signal pipe (streaming): 1MB = 65536 outstanding 16-byte batch signals
  (vs 4096 at default) — workers run further ahead of a slow consumer
  before blocking.
- Spawn stdin/stdout (C side, fr_py_exec_spawn): 1MB allows batch-sized
  transfers without intermediate blocking. Set in C at creation;
  this module covers the Python-created pipes.

Deliberately NEVER bumped: the engine ack pipe (H3 invariant — 4KB for
backpressure), escrow/death pipes (engine-owned), or anything in
forkrun_ring.c (frozen).

F_SETPIPE_SZ needs Linux 2.6.35+ and is capped by
/proc/sys/fs/pipe-max-size (usually 1MB); above the cap needs
CAP_SYS_RESOURCE. Everything here falls back to the default capacity
silently — capacity is an optimization, never correctness.
"""

from __future__ import annotations

import fcntl
import os

DEFAULT_PIPE_SIZE = 64 * 1024  # Linux default (16 pages)
LARGE_PIPE_SIZE = 1024 * 1024  # 1MB (== default pipe-max-size)


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


__all__ = ["DEFAULT_PIPE_SIZE", "LARGE_PIPE_SIZE", "get_pipe_capacity",
           "set_pipe_capacity", "make_pipe"]
