"""C0.7 -- the certificate itself, and its fail-closed envelope.

Round 19 requires BOTH sides before the certificate may be wired:

  1. a recovered execution counts exactly the records ultimately
     committed, so the certificate cannot false-positive on a healthy
     run (proved in test_c07_fault_injection against the real counter);
  2. a deliberately dropped committed DATA frame makes the certificate
     FAIL, so it is not vacuously satisfiable.

Side 1 alone would pass against a comparison that never trips. Side 2
alone would pass against one that always trips. This file proves side 2
and the envelope; the two together are what make the guarantee real.

The envelope tests matter for a different reason: a certificate that
refuses to certify an uncovered path is honest, but a certificate that
refuses for the WRONG reason -- or fails open -- is worse than no
certificate, because it teaches people to ignore it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forkrun.run import (  # noqa: E402
    _c07_envelope,
    _ordered_completeness_certificate,
    _FRAME_STATS,
    _split_records,
    reset_frame_stats,
)


class TestCertificateDetectsLoss(unittest.TestCase):
    """Side 2: the comparison must trip on a lost committed frame."""

    def setUp(self):
        reset_frame_stats()

    @staticmethod
    def _frames(blob):
        return _split_records(blob)[0]

    def test_matching_counts_do_not_trip(self):
        # The control. Without it, "always raises" would satisfy every
        # other test in this file.
        self.assertIsNone(
            _ordered_completeness_certificate(3, 3, label="control"))
        self.assertIsNone(
            _ordered_completeness_certificate(0, 0, label="control-empty"))

    def test_one_lost_frame_trips_the_certificate(self):
        with self.assertRaises(RuntimeError) as cm:
            _ordered_completeness_certificate(3, 2, label="dropped-one")
        msg = str(cm.exception)
        self.assertIn("refusing silent partial completion", msg)
        self.assertIn("short by 1", msg,
                      "the diagnostic must say how many frames are missing")

    def test_observed_side_counts_only_data_frames(self):
        """The observed side must not be the generic 'complete' count.

        'complete' counts filtered control records too, so comparing it
        against a DATA-only committed counter would report a spurious
        shortfall whenever a NO_RESULT terminal record was written --
        which is routine, not a loss. That would make the certificate
        fire on healthy runs, so the distinction is load-bearing rather
        than cosmetic.
        """
        import struct
        from forkrun._worker import _HDR
        from forkrun.run import _DISP_DATA, _DISP_NO_RESULT

        blob = (b"".join(_HDR.pack(i, 3, d, 0) + b"abc"
                         for i, d in ((0, _DISP_DATA),
                                      (1, _DISP_NO_RESULT),
                                      (2, _DISP_DATA))))
        recs = self._frames(blob)
        self.assertEqual(2, len(recs), "the parent collects DATA frames only")
        self.assertEqual(3, _FRAME_STATS["complete"],
                         "precondition: the generic counter DOES include the "
                         "filtered record")
        self.assertEqual(2, _FRAME_STATS["data_frames"],
                         "the DATA-only counter is the observed side")
        # So a committed count of 2 must match, not 3.
        self.assertIsNone(
            _ordered_completeness_certificate(2, _FRAME_STATS["data_frames"],
                                              label="with-no-result"))

    def test_zero_length_data_result_counts_as_a_frame(self):
        """b"" is a real frame; counting it as zero would fake a loss."""
        import struct
        from forkrun._worker import _HDR
        from forkrun.run import _DISP_DATA

        blob = b"".join(_HDR.pack(i, 0, _DISP_DATA, 0)
                        for i in range(3))
        self.assertEqual(3, len(self._frames(blob)))
        self.assertEqual(3, _FRAME_STATS["data_frames"],
                         "zero-length DATA results are frames, not absences")


class TestCertificateScope(unittest.TestCase):
    """The arms that must NOT fire, each for its own stated reason."""

    def test_unavailable_diag_disarms_rather_than_failing(self):
        # expected is None means "counter not readable". Declining is
        # correct; raising would make an old substrate unusable.
        self.assertIsNone(_ordered_completeness_certificate(
            None, 0, label="no-diag"))

    def test_unordered_and_emit_failed_are_out_of_scope(self):
        self.assertIsNone(_ordered_completeness_certificate(
            3, 1, label="unordered", unordered=True))
        self.assertIsNone(_ordered_completeness_certificate(
            3, 1, label="emit-failed", emit_failed=True))

    def test_under_covered_pool_warns_instead_of_failing(self):
        # A benchmark sweep deliberately probes under-covered pools; a
        # hard failure there would be a false positive, so it warns.
        self.assertIsNone(_ordered_completeness_certificate(
            3, 1, label="under-covered", covered=False))


class TestEnvelopeIsFailClosed(unittest.TestCase):
    """Uncovered paths must REFUSE, and the reason must be specific.

    A bare refusal is not enough: an operator seeing "certificate
    unavailable" with no cause cannot act on it. Each branch asserts its
    own reason mentions the path that caused it.
    """

    def test_splice_is_excluded_because_it_bypasses_the_counted_emitters(self):
        covered, reason = _c07_envelope(
            None, "splice", use_complete=True, has_emit=True,
            has_ack_direct=True)
        self.assertFalse(covered)
        self.assertIn("splice", reason)
        self.assertIn("sendfile", reason,
                      "the reason must name the mechanism that bypasses "
                      "the counter, not just the mode name")

    def test_python_write_all_fallback_is_excluded(self):
        covered, reason = _c07_envelope(
            None, "python", use_complete=False, has_emit=False,
            has_ack_direct=True)
        self.assertFalse(covered)
        self.assertIn("_write_all", reason)

    def test_missing_ack_direct_is_excluded(self):
        # No fr_py_ack_direct DETERMINES that _ack() falls back to
        # fr_py_ack -> ring_ack_main, which skips the commit flush. So
        # this is decidable up front without observing a child process.
        covered, reason = _c07_envelope(
            None, "python", use_complete=True, has_emit=True,
            has_ack_direct=False)
        self.assertFalse(covered)
        self.assertIn("fr_py_ack_direct", reason)
        self.assertIn("ring_ack_main", reason)

    def test_covered_path_is_accepted(self):
        covered, reason = _c07_envelope(
            None, "python", use_complete=True, has_emit=True,
            has_ack_direct=True)
        self.assertTrue(covered, "a fully covered path must certify: %s"
                        % reason)
        self.assertEqual("", reason)

    def test_every_excluded_path_names_a_distinct_cause(self):
        """Two branches sharing a reason means one is misdiagnosed."""
        cases = [
            _c07_envelope(None, "splice", use_complete=True,
                          has_emit=True, has_ack_direct=True)[1],
            _c07_envelope(None, "python", use_complete=False,
                          has_emit=False, has_ack_direct=True)[1],
            _c07_envelope(None, "python", use_complete=True, has_emit=True,
                          has_ack_direct=False)[1],
        ]
        self.assertEqual(3, len(set(cases)),
                         "each excluded path must report its own cause: %r"
                         % cases)


if __name__ == "__main__":
    unittest.main(verbosity=2)