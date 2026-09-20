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
"""

from __future__ import annotations


class ReassemblyBuffer:
    """Sequence reassembly keyed by batch_idx."""

    def __init__(self, start: int = 0) -> None:
        self._buffer: dict = {}
        self._next_idx = start
        self._max_size = 0

    def add(self, batch_idx: int, data) -> None:
        """Buffer one completed result (duplicates overwrite — the engine
        never delivers the same batch twice; overwrite is defensive)."""
        self._buffer[batch_idx] = data
        if len(self._buffer) > self._max_size:
            self._max_size = len(self._buffer)

    def drain(self):
        """Yield the consecutive run starting at _next_idx, in order.

        Stops at the first hole. Returns a generator of (batch_idx, data).
        """
        while self._next_idx in self._buffer:
            data = self._buffer.pop(self._next_idx)
            yield (self._next_idx, data)
            self._next_idx += 1

    def final_drain(self):
        """Yield ALL leftovers sorted by batch_idx (EOF path).

        Skips holes (never-delivered batches). Empties the buffer.
        Returns a generator of (batch_idx, data).
        """
        for idx in sorted(self._buffer.keys()):
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
    def next_idx(self) -> int:
        """Next expected batch_idx."""
        return self._next_idx


__all__ = ["ReassemblyBuffer"]
