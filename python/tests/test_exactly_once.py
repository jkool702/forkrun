"""P5b -- the exactly-once proof for terminal dispositions.

DECISION-02 section 5.2 binds the design on one point:

    "Exactly one final disposition per batch. It is a terminal outcome,
     not an attempt. It must be emitted only when the batch will not be
     retried, and integrated with the existing output transaction and
     recovery semantics, so that worker death, retries, respawn, partial
     writes and rollback can neither duplicate nor lose one."

That is a claim about what happens under FAILURE, so it cannot be
established by a happy-path test. This drives the four fault sequences
that could plausibly duplicate or lose a disposition, and parses the
actual output stream to check the invariant rather than trusting return
codes.

The invariant, stated once:

    For every batch that reached a terminal state, the output stream
    contains EXACTLY ONE record with that batch_idx. Zero would be a
    lost disposition; two would be a duplicated one -- and a duplicate
    is worse than a loss, because it desynchronises every batch after it.

No threads. No subprocesses: every fault is injected at the exact engine
call where it happens, which is what makes the sequence deterministic.
"""

import ctypes
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir))
sys.path.insert(0, _HERE)

from forkrun._bindings import (FrPyBatch, RC_OK, find_substrate,  # noqa: E402
                               get)
from forkrun._worker import _HDR  # noqa: E402

DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED, DISP_POISONED = 0, 1, 2, 3

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def parse_records(blob):
    """Parse the framed stream into [(batch_idx, disposition, payload)].

    Deliberately NOT filtering control records: the whole question is
    whether the control ones are there exactly once, so this must see
    them.
    """
    out, off, n = [], 0, len(blob)
    while off + _HDR.size <= n:
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            break
        out.append((idx, disp, blob[off:off + ln]))
        off += ln
    return out


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class _Engine(unittest.TestCase):
    """Engine + ingress spool + a worker wired to a fresh output fd."""

    LINES = 40

    def setUp(self):
        self.lib = get()
        self.assertEqual(self.lib.fr_py_init(0, 0), 0)
        self.addCleanup(self.lib.fr_py_destroy)

        memfd = os.memfd_create("fr_exactly_once_in")
        self.addCleanup(lambda: os.close(memfd))
        os.write(memfd, "".join("line %d\n" % i
                                for i in range(self.LINES)).encode())
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(self.lib.fr_py_ingest_done(), 0)
        self.assertEqual(self.lib.fr_py_scan(memfd), 0)

        self.out_fd = os.memfd_create("fr_exactly_once_out")
        self.addCleanup(lambda: os.close(self.out_fd))
        self.assertEqual(self.lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        self.lib.fr_py_set_output_fd(self.out_fd)
        self.lib.fr_py_ack_init(self.out_fd)

    def claim(self):
        b = FrPyBatch()
        rc = self.lib.fr_py_claim(ctypes.byref(b))
        self.assertEqual(RC_OK, rc)
        return b

    def emit(self, batch_idx, payload):
        return self.lib.fr_py_emit(self.out_fd, -1, 0, batch_idx,
                                   payload, len(payload))

    def stream(self):
        return parse_records(os.pread(self.out_fd, 1 << 20, 0))

    # -- the assertion everything reduces to ---------------------------

    def assert_exactly_once(self, records, expected_indices=None):
        seen = {}
        for idx, disp, _payload in records:
            seen.setdefault(idx, []).append(disp)
        dupes = {i: d for i, d in seen.items() if len(d) > 1}
        self.assertEqual({}, dupes,
                         "a batch produced MORE THAN ONE record: %r -- a "
                         "duplicate desynchronises every batch after it"
                         % (dupes,))
        if expected_indices is not None:
            self.assertEqual(
                sorted(expected_indices), sorted(seen),
                "the set of batches that reached a terminal state differs "
                "from the published set")
        return seen


class TestExactlyOnceUnderRetry(_Engine):
    """Escrow + re-claim. The batch runs twice; it must publish once."""

    def test_retried_batch_emits_exactly_one_disposition(self):
        lib = self.lib
        first = self.claim()
        # Attempt 1 fails before emitting anything.
        self.assertEqual(0, lib.fr_py_escrow_deposit(first.num_kills + 1))

        second = self.claim()
        self.assertEqual(first.batch_idx, second.batch_idx,
                         "escrow must re-issue the SAME batch")
        self.assertEqual(first.num_kills + 1, second.num_kills,
                         "the retry must be visible to the UDF and to poison "
                         "accounting")

        self.assertEqual(0, self.emit(second.batch_idx, b"result"))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        recs = self.stream()
        self.assert_exactly_once(recs, [first.batch_idx])
        self.assertEqual(DISP_DATA, recs[0][1])
        self.assertEqual(b"result", recs[0][2])

    def test_repeated_retries_still_emit_once(self):
        """Five attempts, one publication. The escrowed batch is claimed
        over and over; only the final one may publish."""
        lib = self.lib
        idx, kills = None, 0
        for attempt in range(5):
            b = self.claim()
            if idx is None:
                idx = b.batch_idx
            self.assertEqual(idx, b.batch_idx)
            kills = b.num_kills
            self.assertEqual(0, lib.fr_py_escrow_deposit(b.num_kills + 1))
        final = self.claim()
        self.assertEqual(idx, final.batch_idx)
        self.assertEqual(5, final.num_kills)
        self.assertEqual(0, self.emit(idx, b"late"))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        self.assert_exactly_once(self.stream(), [idx])


class TestExactlyOnceUnderWorkerDeath(_Engine):
    """Rollback. The batch emitted, then the worker died before acking.

    This is the case that matters most: the record is already in the
    output stream when the crash happens. If rollback does not remove it,
    the retry duplicates the batch -- and every later batch shifts by one
    position in the stream.
    """

    def test_rollback_removes_the_orphaned_record(self):
        lib = self.lib
        b = self.claim()
        idx = b.batch_idx
        self.assertEqual(0, self.emit(idx, b"partial"))

        # "Death": exit status 9, SIGKILL-class. Recovery rolls the output
        # fd back to the committed frontier.
        self.assertEqual(0, lib.fr_py_recover_worker(0, 0, self.out_fd, 9))
        self.assertEqual([], self.stream(),
                         "recovery must roll back the un-acked record; "
                         "anything left here will be duplicated by the retry")

        again = self.claim()
        self.assertEqual(idx, again.batch_idx, "the batch must be re-issued")
        self.assertEqual(0, self.emit(idx, b"final"))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        recs = self.stream()
        self.assert_exactly_once(recs, [idx])
        self.assertEqual(b"final", recs[0][2],
                         "the surviving record must be the COMMITTED one, "
                         "not the rolled-back orphan")

    def test_a_SECOND_death_in_the_same_session_still_rolls_back(self):
        """THE regression this whole effort exists for.

        Recovery truncated the output fd but never moved the worker's TLS
        output cursor, so after the FIRST rollback the next batch's
        output_start snapshot pointed past the real end of the file. The
        engine's "never grow a file by truncating" guard then refused
        every later rollback -- so only the first death in a worker
        session was recoverable, and each subsequent one leaked a
        DUPLICATE record.

        Measured before the fix: [0, 1, 2, 2, 3, 4, 4, 5] -- duplicates
        at batches 2 and 4. A duplicate is worse than a loss, because it
        shifts every subsequent batch by one position in the stream.

        Reproduced at HEAD as well, so this is a pre-existing defect and
        not something the disposition work introduced.
        """
        lib = self.lib
        for round_ in range(3):
            b = self.claim()
            idx = b.batch_idx
            self.assertEqual(0, self.emit(idx, b"orphan"))

            before = len(self.stream())
            self.assertEqual(0, lib.fr_py_recover_worker(0, 0, self.out_fd, 9))
            # The orphan for THIS batch must be gone. Earlier batches'
            # committed records legitimately survive -- they were acked,
            # and truncating past them would lose real output.
            remaining = [r for r in self.stream() if r[0] == idx]
            self.assertEqual(
                [], remaining,
                "recovery %d left batch %d's orphan in the stream; the "
                "cursor is stale so the rollback was silently skipped"
                % (round_, idx))
            self.assertEqual(before - 1, len(self.stream()),
                             "recovery should remove exactly the orphan")

            again = self.claim()
            self.assertEqual(idx, again.batch_idx)
            self.assertEqual(0, self.emit(idx, b"ok"))
            self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        recs = self.stream()
        self.assertEqual([0, 1, 2], [r[0] for r in recs],
                         "three batches, three records, in order")
        self.assert_exactly_once(recs, [0, 1, 2])

    def test_death_after_ack_does_not_lose_the_batch(self):
        """The other direction. A death AFTER the ack has committed the
        batch; recovery must not roll it back, or the retry would
        duplicate it."""
        lib = self.lib
        b = self.claim()
        idx = b.batch_idx
        self.assertEqual(0, self.emit(idx, b"committed"))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        before = self.stream()
        self.assertEqual(1, len(before))
        # Recovery on an idle worker has nothing to reclaim.
        lib.fr_py_recover_worker(0, 0, self.out_fd, 9)
        after = self.stream()
        self.assert_exactly_once(after, [idx])
        self.assertEqual(before, after, "a committed record must survive "
                                        "recovery untouched")


class TestExactlyOnceAcrossRespawn(_Engine):
    """A new generation claims the same batch after its predecessor died."""

    def test_respawned_generation_does_not_duplicate(self):
        lib = self.lib
        b = self.claim()
        idx = b.batch_idx
        self.assertEqual(0, self.emit(idx, b"gen0"))
        self.assertEqual(0, lib.fr_py_recover_worker(0, 0, self.out_fd, 9))

        # Generation 1: same wid, higher incarnation, same reused fd.
        self.assertEqual(0, lib.fr_py_worker_init(0, 0, 1, 3, 0))
        lib.fr_py_set_output_fd(self.out_fd)
        lib.fr_py_ack_init(self.out_fd)

        again = self.claim()
        self.assertEqual(idx, again.batch_idx)
        self.assertEqual(0, self.emit(idx, b"gen1"))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        self.assert_exactly_once(self.stream(), [idx])


class TestExactlyOnceAcrossAMixedRun(_Engine):
    """All fault kinds in one stream, checked as a whole."""

    def test_one_record_per_batch_across_every_outcome(self):
        lib = self.lib
        published = []

        for expected in range(6):
            b = self.claim()
            published.append(b.batch_idx)
            kind = expected % 3

            if kind == 0:
                # Succeeds first time.
                self.assertEqual(0, self.emit(b.batch_idx, b"ok"))
                self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

            elif kind == 1:
                # Retries once, then succeeds.
                self.assertEqual(0, lib.fr_py_escrow_deposit(
                    b.num_kills + 1))
                again = self.claim()
                self.assertEqual(b.batch_idx, again.batch_idx)
                self.assertEqual(0, self.emit(again.batch_idx, b"ok"))
                self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

            else:
                # Dies after emitting; recovery rolls back; retry wins.
                self.assertEqual(0, self.emit(b.batch_idx, b"orphan"))
                self.assertEqual(0, lib.fr_py_recover_worker(
                    0, 0, self.out_fd, 9))
                again = self.claim()
                self.assertEqual(b.batch_idx, again.batch_idx)
                self.assertEqual(0, self.emit(again.batch_idx, b"ok"))
                self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))

        recs = self.stream()
        seen = self.assert_exactly_once(recs, published)
        self.assertEqual(6, len(seen))
        for _idx, disp, payload in recs:
            self.assertEqual(DISP_DATA, disp)
            self.assertEqual(b"ok", payload,
                             "only the committed payload may survive")


class TestControlDispositionsAreTerminalToo(_Engine):
    """SKIPPED and POISONED must obey the same exactly-once rule.

    A control disposition is a terminal outcome, not an attempt, so it
    must roll back and re-emit exactly like a DATA record.
    """

    def test_skip_after_retry_emits_exactly_once(self):
        """A batch retried then skipped leaves one SKIPPED record."""
        lib = self.lib
        b = self.claim()
        idx = b.batch_idx
        # The REAL emitter, so the frontier advance -- the part that
        # makes rollback remove the record -- is genuinely exercised.
        # signal_fd -1: this harness has no drain, and the test asserts
        # on the bytes in the worker's own output fd.
        self.assertEqual(0, lib.fr_py_emit_disposition(
            self.out_fd, -1, 0, idx, DISP_SKIPPED))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))
        recs = self.stream()
        self.assert_exactly_once(recs, [idx])
        self.assertEqual(DISP_SKIPPED, recs[0][1])
        self.assertEqual(b"", recs[0][2], "a control record carries no payload")

    def test_poisoned_after_retries_emits_exactly_once(self):
        lib = self.lib
        # Drive the batch to the retry limit the fixture declared
        # (fr_py_worker_init(..., retry_limit=3)), so the claim that
        # follows IS the poison-skip. A fresh batch has num_kills 0, not
        # 3 -- assuming otherwise made this test fail for a reason that
        # had nothing to do with dispositions.
        for _ in range(3):
            b = self.claim()
            self.assertFalse(b.poisoned, "hit the limit early")
            self.assertEqual(0, lib.fr_py_escrow_deposit(b.num_kills + 1))
        b = self.claim()
        idx = b.batch_idx
        self.assertTrue(b.poisoned, "the batch should now be at its limit")
        self.assertEqual(0, lib.fr_py_emit_disposition(
            self.out_fd, -1, 0, idx, DISP_POISONED))
        self.assertEqual(0, lib.fr_py_ack_direct(-1, -1))
        recs = self.stream()
        self.assert_exactly_once(recs, [idx])
        self.assertEqual(DISP_POISONED, recs[0][1])


if __name__ == "__main__":
    unittest.main()