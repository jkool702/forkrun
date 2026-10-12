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

# DECISION-02 dispositions. Duplicated rather than imported to keep this
# module free of run.py imports (it is loaded on every ordered path);
# test_stage1_reassembly pins the two definitions agree.
_DISP_DATA = 0
_DISP_NO_RESULT = 1
_DISP_SKIPPED = 2
_DISP_POISONED = 3

NAME_OF = {_DISP_DATA: "DATA", _DISP_NO_RESULT: "NO_RESULT",
           _DISP_SKIPPED: "SKIPPED", _DISP_POISONED: "POISONED"}

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
        # Stage 1: batches that reached a terminal outcome WITHOUT a
        # payload (NO_RESULT / SKIPPED / POISONED). Tracked separately
        # from _buffer so they advance the contiguous prefix without
        # yielding, and so their dispositions stay distinguishable.
        self._terminal: set = set()
        self._terminal_seen: dict = {}
        self._conflicts: dict = {}
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

    def add_disposition(self, batch_idx: int, disposition: int,
                        payload=None) -> None:
        """Record a batch's TERMINAL outcome, preserving its disposition.

        Stage 1. ``add()`` takes only results, so every control record is
        invisible to it: a batch that completed with NO_RESULT, was
        SKIPPED, or was POISONED simply never appears, and an ordered
        consumer reads that absence as a HOLE. Worse, a batch that later
        completes successfully would still look like a hole to anything
        that already consumed the earlier state.

        All four dispositions advance the contiguous prefix; only DATA
        yields a payload:

        * ``DATA``          -- record the payload and yield it. A genuine
          ``b""`` is a REAL empty result and is stored as such.
        * ``NO_RESULT``     -- the batch completed with no output.
        * ``SKIPPED``       -- on_error=skip gave up on the batch.
        * ``POISONED``      -- the retry limit was reached.

        The last three are retained distinctly rather than collapsed:
        poison accounting and the skip/skip distinction are exactly what
        a consumer needs to report, and DECISION-02 introduced them to
        remove a conflation, not to add another.
        """
        # Contradictions are PROTOCOL VIOLATIONS, not cases to merge.
        #
        # A correct producer emits exactly one terminal outcome per
        # batch. Silently accepting a second one would hide a future
        # exactly-once regression: the reassembly layer is precisely the
        # place that would absorb it and make the stream look healthy.
        # So each contradiction is recorded and the FIRST outcome kept.
        if disposition == _DISP_DATA:
            if batch_idx in self._terminal:
                self._note_conflict(batch_idx, "DATA after terminal %s"
                                    % NAME_OF.get(
                                        self._terminal_seen.get(batch_idx),
                                        "?"))
                return
            if batch_idx in self._buffer:
                # Duplicate DATA for a batch already holding a payload:
                # the engine never delivers one batch twice.
                self._note_conflict(batch_idx, "duplicate DATA")
            self.add(batch_idx, payload)
            return
        if batch_idx in self._buffer:
            self._note_conflict(batch_idx, "%s after DATA"
                                % NAME_OF.get(disposition, disposition))
            return
        if batch_idx in self._terminal:
            self._note_conflict(batch_idx, "%s after %s"
                                % (NAME_OF.get(disposition, disposition),
                                   NAME_OF.get(
                                       self._terminal_seen.get(batch_idx),
                                       "?")))
            return
        self._terminal.add(batch_idx)
        self._terminal_seen[batch_idx] = disposition
        if len(self._terminal) > self._max_size:
            self._max_size = len(self._terminal)

    def _note_conflict(self, batch_idx, what):
        """Record a contradictory terminal outcome for this batch.

        Reported rather than raised: the caller is a streaming loop that
        has already consumed real input, so raising would convert a
        protocol defect into a lost run. It is surfaced through
        `conflicts()` so a caller can refuse the result.
        """
        self._conflicts.setdefault(batch_idx, []).append(what)

    def conflicts(self) -> dict:
        """batch_idx -> [contradictory outcome descriptions].

        Empty for a correct producer. A non-empty result means the
        stream is not trustworthy even if it looks well-formed, so the
        caller should refuse it rather than return it.
        """
        return dict(self._conflicts)

    def drain(self):
        """Yield the consecutive run starting at _next_idx, in order.

        Stops at the first hole. Terminal-without-payload batches advance
        the prefix without yielding, so a NO_RESULT / SKIPPED / POISONED
        batch no longer strands everything behind it.

        Returns a generator of (batch_idx, data).
        """
        while True:
            if self._next_idx in self._buffer:
                data = self._buffer.pop(self._next_idx)
                self._bytes -= self._sizes.pop(self._next_idx, 0)
                yield (self._next_idx, data)
                self._next_idx += 1
            elif self._next_idx in self._terminal:
                self._terminal.discard(self._next_idx)
                self._terminal_seen.pop(self._next_idx, None)
                self._next_idx += 1
            else:
                return

    def terminal_dispositions(self) -> dict:
        """batch_idx -> disposition for terminals not yet yielded.

        Diagnostics only; the map is mutated by drain().
        """
        return dict(self._terminal_seen)

    def unresolved_gaps(self, upto: int) -> list:
        """Indices in [start, upto) that no terminal outcome has covered.

        DIAGNOSTIC ONLY. Deliberately not wired into the production
        completion check, because no single call site can tell whether its
        producer emits an authoritative disposition for EVERY published
        batch:

          * the C loops under the launcher do emit SKIPPED/POISONED;
          * ordinary Python-mode payloads do NOT -- a payload returning
            None passes data=NULL to fr_py_emit(), which writes no record
            at all, so such a batch is a genuine hole rather than a
            missing marker.

        Enforcing this unconditionally would therefore report false
        completeness failures on ordinary None results. It is offered for
        callers that can scope it to a known terminal-aware producer, and
        as a diagnostic for anyone investigating a short run. Turning it
        into an enforced invariant needs a per-producer capability flag,
        which is Stage 1 follow-up work rather than something to smuggle
        in here.
        """
        return [i for i in range(self._next_idx, upto) if i not in self._seen()]

    def _seen(self) -> set:
        return set(self._buffer) | self._terminal

    def final_drain(self):
        """Yield ALL leftovers sorted by batch_idx (EOF path).

        Skips holes (never-delivered batches). Empties the buffer.
        Returns a generator of (batch_idx, data).
        """
        for idx in sorted(self._buffer.keys()):
            self._bytes -= self._sizes.pop(idx, 0)
            yield (idx, self._buffer.pop(idx))
        # Terminal-without-payload indices are not yielded (there is no
        # payload to yield) but must not linger as phantom holes.
        self._terminal.clear()
        self._terminal_seen.clear()

    @property
    def pending(self) -> int:
        """Buffered (not yet yielded) outcomes, payloads and terminals."""
        return len(self._buffer) + len(self._terminal)

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
