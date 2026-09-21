"""Checkpoint codec for forkrun resume support (W-PY22).

Format (compatible with bash ring_dump_resume output):
  FORKRUN_RESUME_HORIZON=<uint64>
  FORKRUN_RESUME_STDOUT_BYTES=<uint64>
  FORKRUN_RESUME_JAGGED=("s:e" "s:e" ...)

Strict parsing: fail-closed. Exactly three keys, no duplicates,
decimal uint64 only, <=1024 intervals, start < end, no extra content.

Atomic publication: temp file -> fsync -> chmod 600 -> rename.
Previous checkpoint preserved if generation fails.

NOTE: these are BYTE COORDINATES on the Universal Coordinate Plane,
not batch numbers. The horizon is the contiguous committed input
byte offset. The jagged intervals are out-of-order committed byte
ranges beyond the horizon. stdout_bytes tracks bytes committed
through the engine's internal output transport (framed records in
memfds) — NOT the byte count of a user-visible file.
"""

from __future__ import annotations

import os
import re

DEFAULT_CHECKPOINT_FILE = ".forkrun_resume"
MAX_JAGGED = 1024


class CheckpointState:
    """Engine resume state (byte coordinates)."""

    __slots__ = ("horizon", "stdout_bytes", "jagged")

    def __init__(self, horizon=0, stdout_bytes=0, jagged=None):
        self.horizon = horizon
        self.stdout_bytes = stdout_bytes
        self.jagged = list(jagged) if jagged else []

    def __repr__(self):
        return ("CheckpointState(horizon=%d, stdout_bytes=%d, "
                "jagged_count=%d)"
                % (self.horizon, self.stdout_bytes, len(self.jagged)))

    def __eq__(self, other):
        return (isinstance(other, CheckpointState)
                and self.horizon == other.horizon
                and self.stdout_bytes == other.stdout_bytes
                and list(self.jagged) == list(other.jagged))


# Strict patterns — decimal uint64 only (no hex, no signs, no spaces).
_HORIZON_RE = re.compile(r"^FORKRUN_RESUME_HORIZON=(\d{1,20})$")
_STDOUT_RE = re.compile(r"^FORKRUN_RESUME_STDOUT_BYTES=(\d{1,20})$")
_JAGGED_RE = re.compile(r"^FORKRUN_RESUME_JAGGED=\((.*)\)$")
_INTERVAL_RE = re.compile(r"^\"(\d{1,20}):(\d{1,20})\"$")

_UINT64_MAX = (1 << 64) - 1


def _check_u64(value, what):
    if value > _UINT64_MAX:
        raise ValueError("%s out of uint64 range: %d" % (what, value))
    return value


def parse_checkpoint(path):
    """Parse a checkpoint file with strict, fail-closed semantics.

    Rules: exactly 3 lines in HORIZON/STDOUT_BYTES/JAGGED order, each
    key exactly once, decimal uint64 only, at most 1024 jagged
    intervals, each interval start < end (strictly), no extra lines.

    Raises ValueError when malformed (fail-closed), FileNotFoundError
    when missing, PermissionError/OSError on I/O failure.
    """
    with open(path, "r") as fh:
        content = fh.read()

    lines = content.strip().split("\n")
    if len(lines) != 3:
        raise ValueError(
            "checkpoint must have exactly 3 lines, got %d: %r"
            % (len(lines), path))

    m = _HORIZON_RE.match(lines[0])
    if not m:
        raise ValueError("invalid HORIZON line: %r" % (lines[0],))
    horizon = _check_u64(int(m.group(1)), "horizon")

    m = _STDOUT_RE.match(lines[1])
    if not m:
        raise ValueError("invalid STDOUT_BYTES line: %r" % (lines[1],))
    stdout_bytes = _check_u64(int(m.group(1)), "stdout_bytes")

    m = _JAGGED_RE.match(lines[2])
    if not m:
        raise ValueError("invalid JAGGED line: %r" % (lines[2],))

    jagged = []
    inner = m.group(1).strip()
    if inner:
        tokens = inner.split()
        if len(tokens) > MAX_JAGGED:
            raise ValueError(
                "too many jagged intervals: %d > %d"
                % (len(tokens), MAX_JAGGED))
        for token in tokens:
            im = _INTERVAL_RE.match(token)
            if not im:
                raise ValueError("invalid interval token: %r" % (token,))
            start = _check_u64(int(im.group(1)), "interval start")
            end = _check_u64(int(im.group(2)), "interval end")
            if start >= end:
                raise ValueError(
                    "invalid interval (start >= end): %d:%d"
                    % (start, end))
            jagged.append((start, end))

    return CheckpointState(horizon, stdout_bytes, jagged)


def collapse_intervals(intervals):
    """Sort + collapse overlapping/contiguous intervals.

    Mirrors ring_dump_resume_main's canonicalization (sort by start,
    merge where next.s <= current.e) so Python-written checkpoints
    are textually interchangeable with bash-written ones.
    """
    ordered = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    out = []
    for start, end in ordered:
        if out and start <= out[-1][1]:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def serialize_checkpoint(state):
    """Serialize CheckpointState to the checkpoint file format.

    Intervals are sorted + collapsed (bash-canonical form).
    Returns the string content (caller handles file I/O).
    """
    if len(state.jagged) > MAX_JAGGED:
        raise ValueError(
            "too many jagged intervals: %d > %d"
            % (len(state.jagged), MAX_JAGGED))
    _check_u64(state.horizon, "horizon")
    _check_u64(state.stdout_bytes, "stdout_bytes")
    lines = [
        "FORKRUN_RESUME_HORIZON=%d" % state.horizon,
        "FORKRUN_RESUME_STDOUT_BYTES=%d" % state.stdout_bytes,
    ]
    canon = collapse_intervals([(s, e) for s, e in state.jagged])
    for s, e in state.jagged:
        # Degenerate intervals (start >= end) never enter the ledger;
        # refusing to serialize them is fail-closed (the strict parser
        # would reject them on read-back).
        if e <= s:
            raise ValueError(
                "degenerate jagged interval (start >= end): %d:%d"
                % (s, e))
    if canon:
        lines.append("FORKRUN_RESUME_JAGGED=(%s)"
                     % " ".join("\"%d:%d\"" % (s, e) for s, e in canon))
    else:
        lines.append("FORKRUN_RESUME_JAGGED=()")
    return "\n".join(lines) + "\n"


def write_checkpoint(path, state):
    """Atomically write a checkpoint file.

    Publication: temp file -> fsync -> chmod 600 -> rename. When any
    step fails the previous checkpoint is preserved (temp removed,
    original untouched) and the error propagates.
    """
    content = serialize_checkpoint(state)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def check_checkpoint_safety(path):
    """Integrity defense (not a code-execution boundary).

    Checks the file exists and is not group/world-writable.
    Returns (is_safe, warnings).
    """
    try:
        st = os.stat(path)
    except (OSError, FileNotFoundError):
        return False, ["cannot stat checkpoint file: %s" % (path,)]
    if st.st_mode & 0o022:
        return False, ["checkpoint file is group/world-writable "
                       "(fix with: chmod go-w %r)" % (path,)]
    return True, []


def snapshot_from_engine(lib):
    """Read the engine resume ledger via the structured snapshot.

    Returns CheckpointState, or None when the engine has no state
    (not initialized) or no progress to report. Never raises for
    engine absence (returns None); ctypes-level failures also
    return None (the abort path must not turn a dead engine into
    a second failure).
    """
    import ctypes

    from ._bindings import FrPyInterval

    fn = getattr(lib, "fr_py_resume_snapshot", None)
    if fn is None:
        return None
    try:
        horizon = ctypes.c_uint64()
        stdout_bytes = ctypes.c_uint64()
        # One call with a full-size array (16KB — snapshots happen
        # once per abort, so no count-query dance; the ledger caps
        # at 1024 intervals engine-side, hence count <= cap always).
        arr = (FrPyInterval * MAX_JAGGED)()
        count = ctypes.c_uint32(MAX_JAGGED)
        rc = fn(ctypes.byref(horizon), ctypes.byref(stdout_bytes),
                arr, ctypes.byref(count), MAX_JAGGED)
        if rc != 0:
            return None
        n = int(count.value)
        if n < 0 or n > MAX_JAGGED:
            return None
        jagged = [(int(arr[i].start), int(arr[i].end))
                  for i in range(n)]
        return CheckpointState(int(horizon.value),
                               int(stdout_bytes.value), jagged)
    except Exception:
        return None


__all__ = ["DEFAULT_CHECKPOINT_FILE", "MAX_JAGGED", "CheckpointState",
           "parse_checkpoint", "serialize_checkpoint", "write_checkpoint",
           "check_checkpoint_safety", "collapse_intervals",
           "snapshot_from_engine"]
