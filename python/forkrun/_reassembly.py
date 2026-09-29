"""Parent-side ordered reassembly over the keyed transport (W-PY7).

The v1 drain loop yields (batch_idx, blob) in worker-completion order.
With order="index" this buffer re-emits them in batch_idx sequence: each
add() is followed by drain() of the consecutive run from _next_idx.

Correctness notes:
- Gaps (poisoned/skipped batches never emit signals) do NOT stall
  termination: at EOF the drain loop final-flushes leftovers sorted
  (final_drain), skipping holes. Mid-stream head-of-line blocking behind
  a hole is the inherent cost of ordered streaming — documented, not
  fixed (the parent has no poisoned-index channel; only a scalar count).
- No hard size cap is enforced: a poisoned head-of-line legitimately
  buffers everything after it until EOF, so any cap would risk dropping
  data. max_size is a diagnostic; in the common case the buffer holds
  only the out-of-order depth (workers x in-flight), and the 16-byte
  signal pipe itself caps outstanding un-drained completions at 4096.
- W-REL6-3.2: high-water warning. Buffered bytes past the limit warn
  ONCE on stderr (actionable: names the head batch, the buffered
  total, and the knob). The limit is reassembly_limit (bytes) when
  set explicitly, else the dynamic default 2 x largest-blob x 32.
  NOTE on the factor: a literal 2 x largest-batch rule false-positives
  on every healthy run with 3+ workers (completion skew alone holds
  (W-1) batches > 2 batches); x32 admits healthy skew up to 32
  in-flight batches while a poisoned head trips it within dozens of
  batches on any real stream. Absolute caps belong to the explicit
  knob (FORKRUN_REASSEMBLY_LIMIT env, bytes; 0/negative silences).
"""

from __future__ import annotations

import os as _os

#: Depth allowance inside the dynamic warn limit (see module notes).
_WARN_DEPTH_FACTOR = 32

#: Env override for the warn limit in bytes (explicit beats dynamic;
#: "0" or negative silences the warning).
_LIMIT_ENV = "FORKRUN_REASSEMBLY_LIMIT"


def _env_limit():
    raw = _os.environ.get(_LIMIT_ENV, "")
    if not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else 0


class ReassemblyBuffer:
    """Sequence reassembly keyed by batch_idx."""

    def __init__(self, start: int = 0, reassembly_limit=None) -> None:
        self._buffer: dict = {}
        self._next_idx = start
        self._max_size = 0
        # W-REL6-3.2: byte accounting for the high-water warning.
        self._sizes: dict = {}
        self._bytes = 0
        self._max_blob = 0
        self._max_bytes = 0
        self._warned = False
        if reassembly_limit is None:
            reassembly_limit = _env_limit()
        self._limit = reassembly_limit  # None = dynamic rule

    def _check_warn(self) -> None:
        if self._warned:
            return
        if self._limit is not None and self._limit <= 0:
            return  # explicitly silenced
        if self._limit is not None:
            tripped = self._bytes > self._limit
            desc = "%d bytes" % self._limit
        else:
            if self._max_blob <= 0:
                return
            tripped = (self._bytes >
                       2 * self._max_blob * _WARN_DEPTH_FACTOR)
            desc = ("dynamic 2x-largest-batch rule "
                    "(largest %d bytes)" % self._max_blob)
        if not tripped:
            return
        self._warned = True
        try:
            _os.write(2, ("forkrun [WARN]: order=\"index\" reassembly "
                          "buffering %d bytes in %d batch(es) behind "
                          "batch %d (limit: %s) -- a poisoned/skipped "
                          "head buffers the whole tail by design "
                          "(see STREAMING.md); set "
                          "FORKRUN_REASSEMBLY_LIMIT=0 to silence.\n"
                          % (self._bytes, len(self._buffer),
                             self._next_idx, desc)).encode())
        except OSError:
            pass

    @staticmethod
    def _weighed(data) -> int:
        try:
            return len(data)
        except TypeError:
            return 0

    def add(self, batch_idx: int, data) -> None:
        """Buffer one completed result (duplicates overwrite — the engine
        never delivers the same batch twice; overwrite is defensive)."""
        size = self._weighed(data)
        if batch_idx in self._buffer:
            self._bytes -= self._sizes.get(batch_idx, 0)
        self._buffer[batch_idx] = data
        self._sizes[batch_idx] = size
        self._bytes += size
        if size > self._max_blob:
            self._max_blob = size
        if len(self._buffer) > self._max_size:
            self._max_size = len(self._buffer)
        if self._bytes > self._max_bytes:
            self._max_bytes = self._bytes
        self._check_warn()

    def drain(self):
        """Yield the consecutive run starting at _next_idx, in order.

        Stops at the first hole. Returns a generator of (batch_idx, data).
        """
        while self._next_idx in self._buffer:
            data = self._buffer.pop(self._next_idx)
            self._bytes -= self._sizes.pop(self._next_idx, 0)
            yield (self._next_idx, data)
            self._next_idx += 1

    def final_drain(self):
        """Yield ALL leftovers sorted by batch_idx (EOF path).

        Skips holes (never-delivered batches). Empties the buffer.
        Returns a generator of (batch_idx, data).
        """
        for idx in sorted(self._buffer.keys()):
            self._bytes -= self._sizes.pop(idx, 0)
            yield (idx, self._buffer.pop(idx))

    @property
    def pending(self) -> int:
        """Buffered (not yet yielded) results."""
        return len(self._buffer)

    @property
    def max_size(self) -> int:
        """High-water mark of buffered entries (diagnostic)."""
        return self._max_size

    @property
    def max_bytes(self) -> int:
        """High-water mark of buffered bytes (W-REL6-3.2 diagnostic)."""
        return self._max_bytes

    @property
    def next_idx(self) -> int:
        """Next expected batch_idx."""
        return self._next_idx


__all__ = ["ReassemblyBuffer"]
