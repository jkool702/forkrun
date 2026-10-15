"""C0.7: the designed completeness correspondence does NOT hold for NUMA.

The design states:

    expected_records = sum over nodes of write_idx   (slots published)
    actual_records   = framed records the parent collected
    certificate      = (actual_records == expected_records)

and claims the premise was "measured across five sizes and two batch
granularities". Implementing it immediately falsifies that premise for
multi-node NUMA, so this file pins the measurement rather than the
assumption.

WHAT WAS MEASURED (27-line input, 4 workers, nodes="@2"):

    node0 write=14 read=14 finished=1 tail_empty=1
    node1 write=1  read=1  finished=1 tail_empty=1
    orderer: recv=15 emitted=15 heap_left=0 stdout_broken=0
    parent collected 14 records, 179 bytes total

179 bytes is exactly the input size, so NOTHING was lost. The extra
published slot is the EOF sentinel / empty tail: it occupies a slot but
yields no record. write_idx counts SLOTS; fr_py_diag_node exposes no
DATA-slot count, and the same concept is already handled by the drain
audit via tail_empty.

Why this test exists: without it, the next person re-reads the design,
wires the certificate, and spends an hour on the same false positive --
while the whole NUMA test suite reports failures that look like a
correctness bug discovered in the engine.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402
from forkrun.run import _ordered_completeness_certificate  # noqa: E402


def _up(b):
    return b.copy()


class C07Correspondence(unittest.TestCase):
    def test_uma_equality_holds_because_no_sentinel_is_published(self):
        """The designed equality is true for UMA -- which is why the
        premise survived five sizes of single-worker measurement."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as fh:
            for i in range(27):
                fh.write("line%d\n" % i)
            path = fh.name
        self.addCleanup(os.unlink, path)
        out = forkrun.map(_up, path, workers=1, nodes=1, order="index")
        self.assertEqual(len(out), 14)
        # A UMA run publishes one slot per batch and no sentinel, so the
        # count corresponds 1:1. Passing 14 for 14 does not raise.

    def test_numa_publishes_a_slot_that_yields_no_record(self):
        """The discrepancy, pinned so it cannot be rediscovered as a bug."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as fh:
            for i in range(27):
                fh.write("line%d\n" % i)
            path = fh.name
        self.addCleanup(os.unlink, path)

        out = forkrun.map(_up, path, workers=4, nodes="@2", order="index")

        # No record is lost: the collected bytes are the whole input.
        expected_bytes = sum(len(("line%d\n" % i).encode()) for i in range(27))
        self.assertEqual(sum(len(r) for r in out), expected_bytes,
                         "every input byte must appear in the output")

        # WO-ROI-1-R1: the record COUNT is not an invariant and must not
        # be asserted as one.
        #
        # This used to assert exactly 14, measured once at round 18. It is
        # flaky -- 2 failures in 10 runs at 7b363270, before any of that
        # round's work -- because with 4 workers over 2 NUMA nodes the
        # batch interleaving changes how many frames the parent receives.
        # The count is an artefact of scheduling; only the BYTES are
        # promised.
        #
        # What IS invariant, and is the property this file exists to
        # protect, is the correspondence with COMMITTED DATA frames --
        # which holds exactly on every configuration the sweep covers.
        from forkrun.run import committed_frames
        committed = committed_frames()["total"]
        self.assertIsNotNone(
            committed,
            "the committed-frame count must be available; a None here "
            "means the counter was never read, not that it was zero")
        self.assertEqual(
            len(out), committed,
            "collected records must equal COMMITTED DATA frames. The "
            "retired design compared against published SLOTS, which "
            "includes the EOF sentinel and is therefore short by one.")

    def test_certificate_would_fire_on_this_correct_run(self):
        """The RETIRED design, kept as arithmetic.

        Pure arithmetic on literal values -- no forkrun call -- so it is
        deterministic. It documents the false invariant that C0.7 was
        built to replace: comparing collected records against published
        SLOTS raises on a perfectly correct run, because the EOF
        sentinel occupies a slot and yields no record.

        Retained deliberately. The certificate now compares committed
        DATA frames and is wired, so nothing else in the suite would
        notice if someone re-derived the slot-based comparison and
        reintroduced this false positive.
        """
        with self.assertRaises(RuntimeError) as cm:
            _ordered_completeness_certificate(15, 14, label="map/run")
        self.assertIn("lost published records", str(cm.exception))
        # A matching count is silent.
        self.assertIsNone(_ordered_completeness_certificate(14, 14,
                                                            label="map/run"))
        # Undisarmed on either scope exclusion.
        self.assertIsNone(_ordered_completeness_certificate(15, 14,
                                                            label="x",
                                                            unordered=True))
        self.assertIsNone(_ordered_completeness_certificate(15, 14,
                                                            label="x",
                                                            emit_failed=True))
        self.assertIsNone(_ordered_completeness_certificate(None, 14,
                                                            label="x"))


if __name__ == "__main__":
    unittest.main()
