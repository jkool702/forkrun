"""v1.3 §3.5 Batch object — Stage 0 shape stub.

Borrowed-lifetime contract (layered):
  claim() -> Batch valid -> payload(batch) -> [invalidate views at return] -> ack()
Layer 1 (enforced, direct views): post-release access raises (observed:
  ValueError on memoryview — documented behavior, not contract).
Layer 2 (enforced, timing): invalidation at payload return.
Layer 3 (unenforceable, UB-by-contract): exported buffers (np.frombuffer)
  hold their own refs; past invalidation fallow may PUNCH_HOLE: silent
  zeros or SIGBUS. Stage 4 test characterizes actual behavior.
Layer 4 (sanctioned persistence): batch.copy().
"""

from __future__ import annotations

from typing import Optional


class Batch:
    """Borrowed batch view. Validity bounded by claim→invalidate→ack."""

    def __init__(self, batch_index: int, byte_offset: int,
                 byte_length: int, line_count: Optional[int],
                 data: memoryview, offsets: Optional[memoryview] = None) -> None:
        self.batch_index = batch_index
        self.byte_offset = byte_offset
        self.byte_length = byte_length
        # 0-means-undefined is the C ABI convention; the Python wrapper
        # maps 0 -> None. One sentinel per language layer.
        self.line_count = line_count
        self._data = data
        self._offsets = offsets
        self._offsets_materialized = offsets is not None
        self._valid = True

    @property
    def data(self) -> memoryview:
        if not self._valid:
            raise ValueError("Batch invalidated at payload return")
        return self._data

    @property
    def offsets(self) -> memoryview:
        """Lazy, absolute plane coordinates (one-currency rule)."""
        if not self._valid:
            raise ValueError("Batch invalidated at payload return")
        if self._offsets is None:
            raise NotImplementedError("offsets materialization lands in Stage 4")
        return self._offsets

    def copy(self) -> bytes:
        """Sanctioned persistence (Layer 4)."""
        if not self._valid:
            raise ValueError("Batch invalidated at payload return")
        return bytes(self._data)

    def invalidate(self) -> None:
        """Release owned views at payload return (Layers 1-2)."""
        if self._valid:
            self._valid = False
            try:
                self._data.release()
            except (ValueError, BufferError):
                pass
            if self._offsets is not None:
                try:
                    self._offsets.release()
                except (ValueError, BufferError):
                    pass
