"""v1.3 §3.5 Batch object — Stage 4 Phase 1 (W-PY1) working implementation.

Borrowed-lifetime contract (layered):
  claim() -> Batch valid -> payload(batch) -> [invalidate views at return] -> ack()
Layer 1 (enforced, direct views): post-release access raises ValueError.
Layer 2 (enforced, timing): the worker calls invalidate() in a finally block
  immediately after payload return, before ack().
Layer 3 (unenforceable, UB-by-contract): exported buffers (np.frombuffer)
  hold their own refs; past invalidation the pages may be reused or the
  mapping torn down. v0 MEASUREMENT (test_numpy_ub.py): reads stay intact
  for the run's duration — the worker holds the whole-file MAP_SHARED mmap
  until os._exit() and no fallow runs. This is an observation, NOT a
  contract: v1 fallow (PUNCH_HOLE: silent zeros or SIGBUS) or windowed
  unmapping may change it without notice. Never depend on intactness.
Layer 4 (sanctioned persistence): batch.copy() BEFORE invalidation. After
  invalidation copy() raises like data — the payload's window is gone; the
  retained Batch reference keeps only metadata (coordinates/kill count) so
  the finally path can deposit the escrow packet.

CUDA: workers are CPU-only. The parent must not hold a live CUDA context
at fork time (the spawn-time guard in _cuda_guard.py refuses with an
actionable message). GPU work belongs in the parent or consumer, never
in workers.

Data plane: the worker mmaps the whole ingress memfd once (MAP_SHARED,
zero-copy) and each Batch is a sliced memoryview over it. Offsets are lazy
absolute plane coordinates (one-currency rule).
"""

from __future__ import annotations

from typing import Optional


class Batch:
    """Borrowed batch view. Validity bounded by claim→invalidate→ack."""

    def __init__(self, batch_index: int, byte_offset: int,
                 byte_length: int, line_count: Optional[int],
                 data: memoryview, offsets: Optional[memoryview] = None,
                 metadata=None) -> None:
        # Metadata is plain state — it survives invalidate() so the worker's
        # finally path can escrow with live coordinates.
        self.batch_index = batch_index
        self.byte_offset = byte_offset
        self.byte_length = byte_length
        # 0-means-undefined is the C ABI convention; the Python wrapper
        # maps 0 -> None. One sentinel per language layer.
        self.line_count = line_count
        # W-PY20 sweep arguments (optional tuple, one entry per sweep
        # dimension). Plain metadata: set by the sweep wrapper before
        # the user payload runs, retained across invalidate() like the
        # other coordinates. None outside sweeps.
        self.metadata = metadata
        self._data = data
        self._offsets = offsets
        self._offsets_materialized = offsets is not None
        self._mm = None  # shared mmap anchor (see from_window)
        self._valid = True

    @classmethod
    def from_window(cls, batch_index: int, byte_offset: int,
                    byte_length: int, line_count: Optional[int],
                    mm: memoryview, base: int = 0,
                    metadata=None) -> "Batch":
        """Build a Batch as a slice of a worker-held shared mapping.

        mm is the worker's whole-file MAP_SHARED view (or any buffer-like);
        base is the mapping's plane offset (v0: 0). The Batch keeps a
        reference to mm so the window cannot be torn down mid-payload, but
        does not own it — the worker owns the mapping's lifetime.
        metadata is an optional W-PY20 sweep tuple, carried through.
        """
        start = base + byte_offset if base else byte_offset
        # Note: byte_offset is already absolute (scanner publishes absolute
        # plane coordinates with buf_base_offset 0 in v0), so base is 0.
        view = mm[start:start + byte_length]
        obj = cls(batch_index, byte_offset, byte_length, line_count, view,
                  metadata=metadata)
        obj._mm = mm
        return obj

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
            self._offsets = self._scan_offsets()
            self._offsets_materialized = True
        return self._offsets

    def copy(self) -> bytes:
        """Sanctioned persistence (Layer 4). Call before invalidation."""
        if not self._valid:
            raise ValueError("Batch invalidated at payload return")
        return bytes(self._data)

    def invalidate(self) -> None:
        """Release owned views at payload return (Layers 1-2). Metadata
        (batch_index/byte_offset/byte_length/line_count) is retained."""
        if self._valid:
            self._valid = False
            try:
                self._data.release()
            except (ValueError, BufferError, AttributeError):
                pass
            self._data = None  # type: ignore[assignment]
            if self._offsets is not None:
                try:
                    self._offsets.release()
                except (ValueError, BufferError, AttributeError):
                    pass
            self._offsets = None
            # Drop the mapping anchor (the worker still owns the mapping).
            self._mm = None

    def _scan_offsets(self) -> memoryview:
        """Materialize absolute line-start offsets by scanning data.

        v0.1: find()-based scan (C-speed substring search per line start;
        the per-byte Python loop was the bottleneck). Stage 4 refinement:
        C SIMD helper. Returns offsets as a memoryview over a privately
        owned uint64 array, in plane coordinates: [byte_offset, ...after
        each newline...]. Relative slicing is a caller-side helper.
        """
        import ctypes

        data = bytes(self._data)
        # Count newlines (fast C implementation) to size the array.
        nn = data.count(b"\n")
        arr = (ctypes.c_uint64 * (nn + 1))()
        arr[0] = self.byte_offset
        base = self.byte_offset
        pos = 0
        for k in range(1, nn + 1):
            nxt = data.find(b"\n", pos)
            if nxt < 0:
                break  # defensive: count/find disagree (cannot happen)
            pos = nxt + 1
            arr[k] = base + pos
        return memoryview(arr)
