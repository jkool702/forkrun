"""C0.7 -- end-to-end proof that the certificate is actually CONNECTED.

Round 20 asked for this, and I first treated it as nice-to-have. That
was the wrong call, and the reason is recorded here because it is the
whole point of the module.

Every other C0.7 test exercises either the counter or the comparison
helper *in isolation*. None of them proves the two are still wired
together in the production path. Disconnecting `_c07_evaluate` from the
collection branch entirely -- deleting the certificate, the thing this
entire work stream exists to provide -- leaves the full 1095-test suite
GREEN. A future refactor could remove it and CI would report success.

So these tests go through the public `map()` and assert on whether the
CALL ITSELF fails.

The fault injected is a DATA frame that was committed by the engine but
never delivered to the collector. That is the shape the certificate
exists to catch, and it is deliberately injected on the OBSERVED side:
dropping at emission would drop the commit too, and both sides would
fall together -- which is precisely the case the certificate must NOT
flag.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402

Rm = sys.modules["forkrun.run"]


def _src(d, n=400):
    p = os.path.join(d, "in.txt")
    with open(p, "w") as fh:
        for i in range(n):
            fh.write("line %d payload text\n" % i)
    return p


def _up(b):
    return b.copy()


class TestCertificateIsConnected(unittest.TestCase):
    """The production path, reached through the public API."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.src = _src(self.d)
        self._saved = os.environ.pop("FORKRUN_C07_DROP_FRAME", None)

        def restore():
            Rm._C07_DROP[0] = None
            Rm._C07_DROP_SEEN[0] = 0
            if self._saved is None:
                os.environ.pop("FORKRUN_C07_DROP_FRAME", None)
            else:
                os.environ["FORKRUN_C07_DROP_FRAME"] = self._saved
        self.addCleanup(restore)

    def _run(self, drop=None):
        if drop is None:
            os.environ.pop("FORKRUN_C07_DROP_FRAME", None)
        else:
            os.environ["FORKRUN_C07_DROP_FRAME"] = str(drop)
        Rm._C07_DROP[0] = None      # force a re-read of the env
        Rm._C07_DROP_SEEN[0] = 0
        return forkrun.map(_up, self.src, workers=1, nodes=1,
                           order="index")

    def test_control_a_clean_run_returns_normally(self):
        """The control.

        Without it, "map() always raises" would satisfy the loss test
        below, and the certificate would be indistinguishable from a
        run that fails unconditionally.
        """
        out = self._run(drop=None)
        self.assertTrue(out, "a clean ordered run must return results")
        self.assertEqual(len(out), Rm.committed_frames()["total"],
                         "a clean run must satisfy the correspondence")

    def test_a_lost_committed_frame_makes_map_raise(self):
        """The e2e proof: dropped frame -> public API fails."""
        with self.assertRaises(RuntimeError) as cm:
            self._run(drop=3)
        msg = str(cm.exception)
        self.assertIn("refusing silent partial completion", msg)
        self.assertIn("short by 1", msg,
                      "exactly one frame was dropped, so the shortfall "
                      "must be exactly one")

    def test_dropping_near_the_end_is_still_caught(self):
        """A drop at the tail, which a heap-drain check would miss.

        The orderer's heap empties cleanly either way, so "drained and
        heap empty" cannot detect this. The counter can, because it does
        not care where the missing frame would have been.
        """
        baseline = len(self._run(drop=None))
        with self.assertRaises(RuntimeError):
            self._run(drop=baseline)

    def test_drop_at_several_positions_is_caught(self):
        """The hook drops exactly ONE frame -- the Nth -- so each case
        must report "short by 1" regardless of position.

        Worth stating explicitly because an earlier draft of this test
        asserted "short by 2" and failed: the hook cannot drop two
        frames, and a test that implies otherwise would be testing
        behaviour the injector does not have.
        """
        for n in (1, 2, 5, 10):
            with self.subTest(drop=n):
                with self.assertRaises(RuntimeError) as cm:
                    self._run(drop=n)
                self.assertIn("short by 1", str(cm.exception),
                              "dropping frame %d must be caught as a "
                              "single-frame shortfall" % n)

    def test_dropping_a_frame_beyond_the_output_is_not_an_error(self):
        """A drop target past the end must not manufacture a failure.

        Guards the hook itself: if it fired on a non-existent frame it
        could make the comparison disagree with reality.
        """
        out = self._run(drop=100000)
        self.assertTrue(out, "dropping a frame that does not exist must "
                             "leave the run untouched")


class TestHookIsInertByDefault(unittest.TestCase):
    """The fault injector must not be able to fire in production."""

    def test_no_env_means_no_drop(self):
        d = tempfile.mkdtemp()
        try:
            src = _src(d)
            os.environ.pop("FORKRUN_C07_DROP_FRAME", None)
            Rm._C07_DROP[0] = None
            Rm._C07_DROP_SEEN[0] = 0
            out = forkrun.map(_up, src, workers=1, nodes=1, order="index")
            self.assertEqual(len(out), Rm.committed_frames()["total"])
        finally:
            shutil.rmtree(d, ignore_errors=True)
            Rm._C07_DROP[0] = None
            Rm._C07_DROP_SEEN[0] = 0

    def test_unset_reads_as_zero(self):
        d = tempfile.mkdtemp()
        try:
            saved = os.environ.pop("FORKRUN_C07_DROP_FRAME", None)
            from forkrun._worker import _HDR  # noqa: F401
            blob = b"".join(
                _HDR.pack(i, 2, 0, 0) + b"ab" for i in range(5))
            recs, _tail = Rm._split_records(blob)
            self.assertEqual(5, len(recs),
                             "with the hook unset every frame must survive")
            if saved is not None:
                os.environ["FORKRUN_C07_DROP_FRAME"] = saved
        finally:
            shutil.rmtree(d, ignore_errors=True)
            Rm._C07_DROP[0] = None
            Rm._C07_DROP_SEEN[0] = 0


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestAccountingSwitchIsCoupled(unittest.TestCase):
    """Round 20 §6: one switch, both halves, or neither.

    Separating them is a false-pass factory. With accounting off and the
    certificate still live, the counter reads 0 while the parent collects
    real frames -- verified, every correct run then raises "collected 25,
    published 0". The inverse silently measures nothing while reporting
    success.

    So FORKRUN_C07_COUNT=0 must disable BOTH, and the only reachable
    states are "measured and checked" or "not attempted".
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.src = _src(self.d)
        self._saved = os.environ.get("FORKRUN_C07_COUNT")

        def restore():
            if self._saved is None:
                os.environ.pop("FORKRUN_C07_COUNT", None)
            else:
                os.environ["FORKRUN_C07_COUNT"] = self._saved
        self.addCleanup(restore)

    def test_default_is_enabled(self):
        os.environ.pop("FORKRUN_C07_COUNT", None)
        self.assertTrue(Rm._c07_enabled(),
                        "the certificate is live by default; opting out "
                        "must be explicit")

    def test_zero_disables_both_halves(self):
        os.environ["FORKRUN_C07_COUNT"] = "0"
        self.assertFalse(Rm._c07_enabled())

    def test_disabled_run_neither_measures_nor_fails(self):
        """The decisive case: off must not become a false failure.

        If the accounting is off but the certificate still runs, the
        counter reads 0 against real collected frames and every correct
        run raises. This is what the coupling prevents.
        """
        os.environ["FORKRUN_C07_COUNT"] = "0"
        # Reset first: when disabled the run never WRITES the telemetry,
        # so an earlier test's value would otherwise still be sitting
        # there and this would assert against another test's leftovers.
        Rm._COMMITTED_FRAMES["total"] = None
        Rm._COMMITTED_FRAMES["nodes"] = 0
        out = forkrun.map(_up, self.src, workers=1, nodes=1,
                          order="index")
        self.assertTrue(out, "a disabled run must still return its output")
        self.assertIsNone(Rm.committed_frames()["total"],
                          "and must record no committed count, since none "
                          "was accumulated")

    def test_enabled_run_measures_and_checks(self):
        os.environ["FORKRUN_C07_COUNT"] = "1"
        out = forkrun.map(_up, self.src, workers=1, nodes=1,
                          order="index")
        self.assertEqual(len(out), Rm.committed_frames()["total"],
                         "an enabled run must measure and correspond")
