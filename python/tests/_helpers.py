"""Shared helpers for the W-PY4 robustness suites (no tests in here).

Discover pattern is test*.py, so this module is never collected directly.
"""

import os


def redirect_fd(fd, path):
    """Dup2 fd onto a fresh capture file. Returns the saved fd."""
    saved = os.dup(fd)
    tmp = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(tmp, fd)
    os.close(tmp)
    return saved


def restore_fd(fd, saved):
    os.dup2(saved, fd)
    os.close(saved)


def nfd():
    return len(os.listdir("/proc/self/fd"))


def write_lines(path, n, fmt="line %d\n"):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(fmt % i)


def assert_no_zombies(testcase):
    """All children reaped: a WNOHANG poll must report ECHILD."""
    try:
        pid = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        return
    testcase.fail("reaped unexpected child %r — zombie leak" % (pid,))


def lines_of(blobs):
    """All output lines across result blobs, sorted.

    Split-agnostic: batch boundaries are an implementation
    detail (pre-flight timing changes them run to run), so
    cross-run comparisons must use lines (or joined bytes),
    never blob identity or blob sort order.
    """
    out = []
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, str):
            b = b.encode()
        out.extend(b.splitlines())
    return sorted(out)


def joined_bytes(blobs):
    """Concatenated output bytes (split-agnostic, order-sensitive)."""
    parts = []
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, str):
            b = b.encode()
        parts.append(bytes(b))
    return b"".join(parts)
