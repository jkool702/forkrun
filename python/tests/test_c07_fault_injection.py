"""C0.7 fault injection -- the part that needs NO ring change.

Round 18 blocked the counter on a lifecycle question, not a counting
question:

    emission is not commit.

`fr_py_complete` is "output + signal + ack", and the ACK is the commit
linearization point. A worker can write a DATA frame, die before acking,
have recovery truncate the output back to `output_start`
(`forkrun_ring.c:7163`, Case 2b "THE ORPHAN"), and then retry the batch.

So a counter incremented at `fr_py_emit` counts WRITTEN frames, while the
parent collects COMMITTED frames, and the two legitimately differ on a
perfectly healthy recovered run.

This module pins that divergence empirically, before any counter exists.
It is the evidence the commit-accounting design has to satisfy, and it
costs no production code: the engine already exposes exactly the two
quantities (`fr_py_emit` success, `fr_py_recover_worker`, and the framed
output stream), so the difference between them is directly observable.

Three things are pinned:

  1. WRITTEN != COMMITTED. A rollback makes successful emits exceed
     committed records. Any emit-counting certificate false-positives here.
  2. The gap GROWS with repeat deaths, so the error is unbounded rather
     than a constant +1 that a calibration could absorb.
  3. A dropped frame between emission and collection IS detectable --
     the same counter that over-counts on rollback is the one that
     detects genuine loss. Any replacement must keep property 3.

Nothing here touches the ring, and nothing here asserts a design. It
only establishes what the design must reconcile.
"""

import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forkrun._bindings import FrPyBatch, RC_OK, find_substrate  # noqa: E402
from forkrun._worker import _HDR  # noqa: E402
from forkrun.run import _DISP_DATA as DISP_DATA, _DISP_NO_RESULT as DISP_NO_RESULT  # noqa: E402


def _parse(blob):
    """Framed records -> [(batch_idx, disposition, payload)].

    Non-DATA dispositions are filtered, because that is what the parent
    framer does (run.py _DISP_DATA filter). Taking DISP_DATA from run.py
    rather than hardcoding it is deliberate: an earlier draft of this file
    hardcoded 1, which silently filtered out every real DATA frame and
    made the whole module vacuous.
    """
    out, off, n = [], 0, len(blob)
    while off + _HDR.size <= n:
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            break
        payload = blob[off:off + ln]
        off += ln
        if disp != DISP_DATA:
            continue
        out.append((idx, disp, payload))
    return out


class _Engine(unittest.TestCase):
    """Mirrors test_exactly_once._Engine: one worker, one batch slot."""

    @classmethod
    def setUpClass(cls):
        cls.lib = ctypes.CDLL(find_substrate())
        cls.lib.fr_py_emit.restype = ctypes.c_int
        cls.lib.fr_py_emit.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ctypes.c_uint64, ctypes.c_char_p, ctypes.c_size_t]

    LINES = 40

    def setUp(self):
        self.emitted = 0
        self._start_generation()

    def _start_generation(self):
        """Bring up a complete engine generation: init, ingress, worker,
        output. Split out of setUp so a test that tears the engine down
        can build a genuine fresh generation rather than leaving the
        worker un-armed (which makes claim() block forever)."""
        lib = self.lib
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        self.addCleanup(lib.fr_py_destroy)

        memfd = os.memfd_create("fr_c07_faults_in")
        # Bind the descriptor at registration: a lambda closing
        # self.out_fd would, after a second generation replaced it, close
        # the NEW fd and leave the old one leaked.
        self.addCleanup(lambda fd=memfd: os.close(fd))
        os.write(memfd, "".join("line %d\n" % i
                                for i in range(self.LINES)).encode())
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)

        out_fd = os.memfd_create("fr_c07_faults_out")
        self.addCleanup(lambda fd=out_fd: os.close(fd))
        self.out_fd = out_fd
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(self.out_fd)
        lib.fr_py_ack_init(self.out_fd)

    def claim(self):
        b = FrPyBatch()
        self.assertEqual(self.lib.fr_py_claim(ctypes.byref(b)), RC_OK)
        return b

    def emit(self, batch_idx, payload):
        """Returns rc; tallies only SUCCESSFUL writes -- exactly what a
        counter placed after a successful fr_py_emit would increment."""
        rc = self.lib.fr_py_emit(self.out_fd, -1, 0, batch_idx,
                                 payload, len(payload))
        if rc == RC_OK:
            self.emitted += 1
        return rc

    def committed(self):
        """What the parent would actually collect."""
        return _parse(os.pread(self.out_fd, 1 << 20, 0))

    def kill_and_recover(self, batch):
        """Worker dies before acking. Returns after the output has been
        rolled back to the committed frontier."""
        self.assertEqual(
            self.lib.fr_py_recover_worker(0, 0, self.out_fd, 9), 0,
            "recovery must accept the orphaned batch")
        self.assertEqual(0, self.lib.fr_py_escrow_deposit(batch.num_kills + 1),
                         "the orphan must be escrowed so the batch retries")


class TestWrittenIsNotCommitted(_Engine):
    """THE blocker, reproduced without a counter."""

    def test_successful_emit_is_rolled_back_so_writes_exceed_commits(self):
        b = self.claim()
        idx = b.batch_idx

        # Attempt 1: the write SUCCEEDS. An emit-side counter reads 1 here.
        self.assertEqual(0, self.emit(idx, b"partial"))
        self.assertEqual([(idx, DISP_DATA, b"partial")], self.committed(),
                         "precondition: the record is really in the stream "
                         "when the worker dies")

        # The worker now dies before acking. Output is truncated.
        self.kill_and_recover(b)
        self.assertEqual([], self.committed(),
                         "recovery must roll back the un-acked record")

        # Attempt 2: same batch, writes again. An emit-side counter reads 2.
        again = self.claim()
        self.assertEqual(idx, again.batch_idx, "the batch must be re-issued")
        self.assertEqual(0, self.emit(idx, b"final"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))

        recs = self.committed()
        self.assertEqual(1, len(recs), "exactly one committed record")
        self.assertEqual(b"final", recs[0][2],
                         "the survivor is the COMMITTED record, not the "
                         "rolled-back orphan")

        # The whole point: two successful writes, one committed record.
        self.assertEqual(2, self.emitted,
                         "precondition for the certificate hazard")
        self.assertEqual(
            self.emitted, len(recs) + 1,
            "REGRESSION GUARD: a counter incremented per successful "
            "fr_py_emit would report %d for a run the parent collects %d "
            "records from. This is a healthy, fully-recovered run -- it "
            "must not be able to fail the certificate."
            % (self.emitted, len(recs)))

    def test_the_gap_grows_with_repeat_deaths(self):
        """A constant +1 could be calibrated away. A growing gap cannot."""
        b = self.claim()
        idx = b.batch_idx
        for _ in range(3):
            self.assertEqual(0, self.emit(idx, b"orphan"))
            self.kill_and_recover(b)
            b = self.claim()
            self.assertEqual(idx, b.batch_idx)

        self.assertEqual(0, self.emit(idx, b"survivor"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))

        recs = self.committed()
        self.assertEqual(1, len(recs))
        self.assertEqual(b"survivor", recs[0][2])
        self.assertEqual(
            4, self.emitted,
            "four successful writes, one committed record")
        self.assertEqual(3, self.emitted - len(recs),
                         "the divergence is unbounded in the number of "
                         "deaths, so it cannot be absorbed by calibration")


class TestLossRemainsDetectable(_Engine):
    """Any replacement for emit-counting must keep this property.

    The rollback tests above show emit-counting OVER-counts. These show
    the underlying quantity is genuinely needed: frames CAN vanish
    between emission and collection, and a certificate that cannot see
    that is worthless. This is the failure the certificate exists to
    catch, so a commit-scoped design must still catch it.
    """

    def test_collection_truncation_undercounts_and_is_visible(self):
        """Simulate loss AFTER commit by reading a prefix.

        The parent observes fewer frames than were committed, which is the
        signature a completeness certificate must surface. Recorded here so
        that when the counter moves to a commit-scoped definition, the
        detection side is not quietly dropped along the way.
        """
        b = self.claim()
        idx = b.batch_idx
        self.assertEqual(0, self.emit(idx, b"only"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))
        self.assertEqual(1, len(self.committed()))

        # A reader that loses the final record observes 0 committed frames.
        blob = os.pread(self.out_fd, 1 << 20, 0)
        partial = _parse(blob[:len(blob) // 2])
        self.assertEqual([], partial,
                         "a truncated view must not report the frame as "
                         "collected -- this is the gap the certificate must "
                         "make non-zero")

    def test_non_data_dispositions_are_not_counted_as_frames(self):
        """A NO_RESULT is written but the parent filters it.

        This is the disposition half of the round-17/18 counting argument:
        a written record that the framer discards must not appear on
        either side of the correspondence.

        Written with the raw framer pack, exactly as the Python fallback
        emitter in _worker.py does it -- NOT via fr_py_emit, which writes
        only DATA and writes nothing at all for a NULL payload. An earlier
        draft used fr_py_emit and was VACUOUS: removing the filter changed
        no result, because there was no non-DATA record for it to reject.
        The mutation below is what proves this case is now real.
        """
        b = self.claim()
        idx = b.batch_idx

        # A null emission contributes no record at all.
        self.assertEqual(0, self.lib.fr_py_emit(self.out_fd, -1, 0, idx,
                                               None, 0))
        self.assertEqual([], self.committed(),
                         "a null emission contributes no committed frame")

        # A legitimate EMPTY DATA frame is a real frame and must count.
        self.assertEqual(0, self.lib.fr_py_emit(self.out_fd, -1, 0, idx,
                                               b"", 0))
        self.assertEqual([(idx, DISP_DATA, b"")], self.committed(),
                         "a zero-length DATA frame is a real frame, unlike "
                         "a null emission")

        # Now the Python-fallback framing: a NO_RESULT record with no
        # payload. It IS on disk, and the parent MUST filter it.
        raw = _HDR.pack(idx, 0, DISP_NO_RESULT, 0)
        os.pwrite(self.out_fd, raw, os.lseek(self.out_fd, 0, os.SEEK_END))

        # Prove it is really in the byte stream, unfiltered.
        blob = os.pread(self.out_fd, 1 << 20, 0)
        self.assertIn(raw, blob,
                      "precondition: the NO_RESULT record must be on disk, "
                      "otherwise the filter has nothing to reject and this "
                      "test would be vacuous")

        # And the parsed view must still show exactly the one DATA frame.
        self.assertEqual([(idx, DISP_DATA, b"")], self.committed(),
                         "a NO_RESULT is filtered by the parent framer and "
                         "must not count as a collected frame")
class TestPendingDoesNotSurviveAFreshGeneration(_Engine):
    """A real defect this work item surfaced, pinned so it cannot return.

    fr_py_txn_pending_data is thread-local and survives fork. It was NOT
    reset by fr_py_init, so a value left over from a previous generation
    -- or inherited across a fork -- would be flushed into the NEW run's
    shared counter, reporting frames nobody committed in it.

    This is the same hazard as the documented W-PY28 fix for
    fr_py_txn_out_fd ("fresh generation -- drop any inherited
    output-fd naming"), applied to the counter.

    It was found only because a test failed when run AFTER another that
    left a pending value behind, and passed when run alone. That is
    exactly the shape a single-test invocation hides, so the fix needs a
    test that fails without it rather than one that merely describes it.
    """

    def test_pending_count_does_not_leak_into_the_next_generation(self):
        import ctypes as _c
        b = self.claim()
        # Write a DATA frame and leave it UNCOMMITTED: pending is now 1
        # in this thread, and nothing will flush it.
        self.assertEqual(0, self.emit(b.batch_idx, b"never-committed"))

        # Tear the engine down and bring up a COMPLETE fresh generation,
        # exactly as a re-entrant run in one process would.
        self.lib.fr_py_destroy()
        self._start_generation()

        out = _c.c_uint64(0)
        self.assertEqual(
            0, self.lib.fr_py_committed_data_frames(0, _c.byref(out)))
        self.assertEqual(
            0, out.value,
            "REGRESSION GUARD: a pending count from a previous generation "
            "must not be inherited into the new run's committed total")

        # And it must not resurface later: a commit in the new
        # generation must flush 0, not the stale 1.
        b2 = self.claim()
        self.assertEqual(0, self.emit(b2.batch_idx, b"first-of-new-run"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))
        self.assertEqual(
            0, self.lib.fr_py_committed_data_frames(0, _c.byref(out)))
        self.assertEqual(
            1, out.value,
            "the new generation commits exactly its own one frame -- a "
            "stale pending would have reported 2")


class TestCommittedCounter(_Engine):
    """The counter itself, and the two-sided gate round 19 requires.

    Everything below exercises the SHARED committed total, read through
    fr_py_committed_data_frames. The two properties that matter:

      1. a recovered run counts EXACTLY the records ultimately committed
         (so the certificate cannot false-positive on a healthy run);
      2. a deliberately dropped committed DATA frame makes the
         certificate FAIL (so it is not vacuously satisfiable).

    Round 19 requires BOTH before the certificate may be wired. A test
    that only proves (1) would pass against a counter that never moves;
    a test that only proves (2) would pass against one that always
    reports a huge number. Both are required because they are the two
    ways the certificate could be wrong in opposite directions.
    """

    def committed_count(self):
        import ctypes as _c
        out = _c.c_uint64(0)
        rc = self.lib.fr_py_committed_data_frames(0, _c.byref(out))
        self.assertEqual(0, rc, "counter snapshot must succeed on node 0")
        return out.value

    def test_clean_run_counts_every_committed_frame(self):
        # One claim per committed record: a batch is acked once. Claiming
        # once and acking three times is invalid (the second ack fails),
        # which is the engine correctly refusing to double-commit.
        for payload in (b"a", b"", b"c"):
            b = self.claim()
            self.assertEqual(0, self.emit(b.batch_idx, payload))
            self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))
        # a, b"", c -- the empty DATA frame is a REAL frame and must count
        self.assertEqual(3, self.committed_count(),
                         "three committed DATA frames, including a "
                         "zero-length one")
        self.assertEqual(3, self.emitted,
                         "no rollback happened, so writes == commits")

    def test_rollback_leaves_the_counter_at_one_not_two(self):
        """THE regression this whole work item exists to prevent."""
        b = self.claim()
        idx = b.batch_idx
        self.assertEqual(0, self.emit(idx, b"orphan"))
        # Before the ack the frame is written but NOT committed.
        self.assertEqual(0, self.committed_count(),
                         "an uncommitted write must not be counted yet")
        self.kill_and_recover(b)

        again = self.claim()
        self.assertEqual(idx, again.batch_idx)
        self.assertEqual(0, self.emit(idx, b"survivor"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))

        self.assertEqual(2, self.emitted, "two successful writes")
        self.assertEqual(1, len(self.committed()), "one committed record")
        self.assertEqual(
            1, self.committed_count(),
            "REGRESSION GUARD: counting at WRITE time would report 2 here "
            "and fail a healthy, fully-recovered run")

    def test_repeated_rollbacks_do_not_accumulate(self):
        b = self.claim()
        idx = b.batch_idx
        for _ in range(3):
            self.assertEqual(0, self.emit(idx, b"orphan"))
            self.kill_and_recover(b)
            b = self.claim()
            self.assertEqual(idx, b.batch_idx)
        self.assertEqual(0, self.emit(idx, b"survivor"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))

        self.assertEqual(4, self.emitted, "four writes")
        self.assertEqual(1, len(self.committed()), "one committed record")
        self.assertEqual(
            1, self.committed_count(),
            "the divergence must not accumulate: write-counting would "
            "report 4 against a single collected frame")

    def test_no_result_records_never_count(self):
        """A NO_RESULT terminal record is written but filtered."""
        b = self.claim()
        idx = b.batch_idx
        raw = _HDR.pack(idx, 0, DISP_NO_RESULT, 0)
        os.pwrite(self.out_fd, raw, os.lseek(self.out_fd, 0, os.SEEK_END))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))
        self.assertEqual(
            0, self.committed_count(),
            "a filtered control record must not count as a DATA frame")
        self.assertEqual([], self.committed(),
                         "and the parent collects nothing for it")


class TestRealProcessDeath(_Engine):
    """Process-level, as round 19 requires.

    The in-process tests above call fr_py_recover_worker from the SAME
    thread that emitted the frame, so the pending count is cleared from
    the supervisor's own TLS. A real worker death is different: the
    process is gone, so its thread-local state is GONE -- there is
    nothing for recovery to clear.

    That distinction is the whole point. If the shared counter were
    moved by anything other than a commit, a dead worker's pending value
    would either persist (counting an uncommitted frame) or be reachable
    by a future fork. Forking a real child and letting it die before the
    ack exercises the situation the in-process harness cannot.

    Lifecycle:
      1. parent inits the engine and forks a worker child;
      2. the child claims a batch, writes a DATA frame, and dies BEFORE
         the ack -- so the frame is on disk but never committed;
      3. the parent recovers, truncating the orphan;
      4. the parent re-claims the same batch and commits it;
      5. the committed count must be exactly 1, and the parent must
         collect exactly 1 DATA frame.
    """

    def _run_child_dying_before_ack(self, payload):
        """Fork a child that emits `payload` then exits before acking."""
        b = self.claim()
        idx = b.batch_index if hasattr(b, "batch_index") else b.batch_idx
        pid = os.fork()
        if pid == 0:
            # -- child --
            try:
                rc = self.lib.fr_py_emit(self.out_fd, -1, 0, idx,
                                         payload, len(payload))
                _exitcode = 0 if rc == RC_OK else 3
            except BaseException:
                _exitcode = 4
            # Die BEFORE fr_py_ack_direct: the frame is written, the
            # batch is not committed, and this process's TLS dies with
            # us -- which is the point.
            os._exit(_exitcode)
        _, status = os.waitpid(pid, 0)
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            self.fail("worker child did not exit cleanly (status=%d)"
                      % status)
        return b

    def test_dead_worker_pending_is_destroyed_with_the_process(self):
        import ctypes as _c

        b = self._run_child_dying_before_ack(b"orphan")

        # The frame is really on disk, written by a process that is now
        # gone -- so nothing can have flushed a count for it.
        self.assertEqual(1, len(self.committed()),
                         "precondition: the orphan is in the stream")
        out = _c.c_uint64(0)
        self.assertEqual(0, self.lib.fr_py_committed_data_frames(
            0, _c.byref(out)))
        self.assertEqual(
            0, out.value,
            "a worker that died before its ack committed nothing, so the "
            "shared count must still be 0")

        # Parent recovers: truncation happens in the parent, and the
        # dead child's TLS is not merely cleared -- it is unreachable.
        self.kill_and_recover(b)
        self.assertEqual([], self.committed(), "the orphan was truncated")

        again = self.claim()
        self.assertEqual(b.batch_idx, again.batch_idx)
        self.assertEqual(0, self.emit(again.batch_idx, b"survivor"))
        self.assertEqual(0, self.lib.fr_py_ack_direct(-1, -1))

        self.assertEqual(1, len(self.committed()),
                         "exactly one DATA frame survives")
        self.assertEqual(0, self.lib.fr_py_committed_data_frames(
            0, _c.byref(out)))
        self.assertEqual(
            1, out.value,
            "REGRESSION GUARD: the committed count must be 1 after a real "
            "worker death and retry -- not 0 (the commit never flushed) "
            "and not 2 (the dead worker's pending leaked)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
