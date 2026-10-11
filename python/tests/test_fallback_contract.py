"""DECISION-03 section 7.2 -- the fallback contract, and the bug it closes.

The cleanroom launcher treats a nonzero exit as "accelerator unavailable"
and reruns the workload in-process. That is only safe if NOTHING destructive
happened first.

The bug this file pins: the decision was

    replayable   = pre_ingest or _source_is_reopenable(source)
    may_fallback = replayable and not forbidden

The `or` answers "can the INPUT be re-read?" and then uses that answer for
"is it SAFE to run every batch again?". A path source is re-readable, so a
runtime worker failure -- where workers ran and user code ran -- replayed
the entire workload from batch zero, re-executing side effects. A
caller-supplied descriptor did not, for the identical failure. The decision
turned on the shape of the source rather than on whether anything had
happened.

These tests exercise the DECISION, not the launcher, because the decision is
where the defect lives and where it is cheapest to pin. An end-to-end
demonstration is confounded: the recovering supervisor's respawn multiplies
execution far more than any fallback does, so the two cannot be separated by
counting side effects.

Run: python3 -m unittest discover -s python/tests
"""

import importlib
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

frun = importlib.import_module("forkrun.run")

# waitpid status for "exited with code N". os has no W_EXITCODE helper.
def _exited(code):
    return code << 8


# Sentinel: the fixed policy takes no source, so passing one is the point
# of the shape test rather than a mistake.
_UNUSED = object()


class TestFallbackDecision(unittest.TestCase):
    """The decision, per (launcher outcome x source shape)."""

    def _decide(self, code, source=_UNUSED):
        """Ask the PRODUCTION policy, not a copy of it.

        The first version of this test re-implemented the decision inline
        and therefore passed identically with and without the fix. The
        policy is now a named function in run.py precisely so this can call
        it; `source` is accepted and ignored because the old rule depended
        on it, and test_source_shape_no_longer_decides needs to say so.
        """
        return (frun._decode_launcher_status(_exited(code))[3],
                frun._fallback_forbidden(_exited(code)),
                frun._cleanroom_may_fallback(_exited(code)))

    def test_runtime_failure_must_not_replay_a_path_source(self):
        """THE regression. Exit 1 after workers ran is not replayable."""
        pre, forbidden, may = self._decide(1, "/tmp/data.jsonl")
        self.assertFalse(pre, "exit 1 must not claim to be pre-ingest")
        self.assertFalse(forbidden)
        self.assertFalse(
            may,
            "a runtime worker failure must NOT trigger an in-process "
            "replay of a path source: workers ran, user code ran, and "
            "replaying re-executes side effects")

    def test_source_shape_no_longer_decides(self):
        """Path and fd must be treated the SAME for the same failure.

        This is the incoherence in its sharpest form: the old rule gave a
        path source a replay and a descriptor none, for one identical
        failure.
        """
        _pre, _forb, may_path = self._decide(1, "/tmp/data.jsonl")
        _pre, _forb, may_fd = self._decide(1, 42)
        self.assertEqual(may_path, may_fd,
                         "the fallback decision must not depend on the "
                         "shape of the source")

    def test_confirmed_pre_ingest_declines_still_fall_back(self):
        """The fix must not break the safe case it was meant to keep.

        A confirmed pre-execution decline is exactly what fallback is for:
        the launcher never ran user code, so routing around it is free.
        """
        for code in sorted(frun._CR_EXIT_PRE_INGEST):
            with self.subTest(exit_code=code):
                pre, forbidden, may = self._decide(code, "/tmp/data.jsonl")
                self.assertTrue(pre, "code %d is declared pre-ingest" % code)
                self.assertTrue(
                    may,
                    "a confirmed pre-ingest decline must still fall back; "
                    "otherwise the launcher is pointless for these")

    def test_probe_failure_still_forbidden(self):
        """Exit 79 stays refused: replaying would reproduce the hazard."""
        _pre, forbidden, may = self._decide(79, "/tmp/data.jsonl")
        self.assertTrue(forbidden)
        self.assertFalse(may,
                         "exit 79 must never fall back -- the plugin load "
                         "itself is unsafe")

    def test_source_is_reopenable_still_describes_the_input(self):
        """The helper keeps its meaning; only its ROLE in the decision ends.

        It still answers "is this input re-readable?", which is true and
        useful. It just no longer gets to answer a safety question.
        """
        self.assertTrue(frun._source_is_reopenable("/tmp/x.jsonl"))
        self.assertTrue(frun._source_is_reopenable(b"/tmp/x.jsonl"))
        self.assertFalse(frun._source_is_reopenable(7))


class TestFallbackIsFailClosed(unittest.TestCase):
    """Ambiguity must not resolve in favour of replaying."""

    def test_signal_death_never_falls_back(self):
        """A signalled launcher never gets to claim a clean pre-ingest."""
        status = 9  # killed by SIGKILL; WIFSIGNALED
        _c, signum, _label, pre_ingest = frun._decode_launcher_status(status)
        self.assertIsNone(_c)
        self.assertEqual(9, signum)
        self.assertFalse(pre_ingest)
        forbidden = frun._fallback_forbidden(status)
        self.assertFalse(pre_ingest and not forbidden)

    def test_unrecognised_status_never_falls_back(self):
        """An exit code we do not know must not be assumed safe."""
        for code in (2, 3, 42, 200):
            with self.subTest(exit_code=code):
                _c, _s, label, pre_ingest = frun._decode_launcher_status(
                    _exited(code))
                self.assertIn("unknown exit code", label)
                self.assertFalse(
                    pre_ingest,
                    "an unrecognised exit code must not be treated as "
                    "pre-ingest; unknown means unknown")


if __name__ == "__main__":
    unittest.main()
