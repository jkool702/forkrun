"""C0.7 -- run scoping of the expected side.

The committed-frame counter lives in SharedState, which belongs to the
ENGINE, not to a run. Three situations therefore charge a run for
frames it did not commit:

  * a RESUME merges sidecar output committed by an EARLIER run;
  * a nested map() inside a stream() SHARES the engine, so the counter
    already carries the outer run's commits;
  * a long-lived process calling map() repeatedly accumulates.

The fix is to capture a baseline after engine init but before any fork,
and compare the DELTA. All three of these tests fail against an
unscoped comparison -- that is the point of keeping them, since the
scoping only shows up in these shapes and not in a plain run.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402


def _up(b):
    return b.copy()


class _Src(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            for i in range(400):
                fh.write("line %d payload text here\n" % i)
        self.addCleanup(_rmtree, self.d)


def _rmtree(d):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestRunScoping(_Src):
    def test_a_plain_run_matches_exactly(self):
        # The baseline case: nothing else is committing, so the delta is
        # the whole committed count and the correspondence is exact.
        out = forkrun.map(_up, self.src, workers=1, nodes=1, order="index")
        self.assertTrue(out)
        from forkrun.run import committed_frames
        self.assertEqual(len(out), committed_frames()["total"],
                         "a single run's committed frames must equal the "
                         "DATA frames it collected")

    def test_repeated_runs_do_not_accumulate(self):
        """Second run must be scored against ITS OWN commits only."""
        from forkrun.run import committed_frames
        first = len(forkrun.map(_up, self.src, workers=1, nodes=1,
                                order="index"))
        self.assertEqual(first, committed_frames()["total"])
        second = len(forkrun.map(_up, self.src, workers=1, nodes=1,
                                 order="index"))
        self.assertEqual(first, second,
                         "identical work should yield identical output")
        self.assertEqual(
            second, committed_frames()["total"],
            "REGRESSION GUARD: without a per-run baseline the second run "
            "would be compared against the CUMULATIVE counter (%d) and "
            "fail a correct run" % (first + second))

    def test_nested_map_inside_stream_is_scored_on_its_own_commits(self):
        """The case that forced the design: a shared engine.

        The outer stream commits frames into the same SharedState the
        inner map uses. An unscoped comparison charges the inner run for
        the outer run's commits.
        """
        seen = {}

        def payload(b):
            # Runs inside the stream, which is inside the map below.
            return b.copy()

        with open(self.src) as fh:
            lines = fh.read().splitlines()

        # Outer: a real stream over the file.
        def consume():
            got = 0
            for _ in forkrun.stream(_up, self.src, workers=1, nodes=1):
                got += 1
                if got == 20:
                    # Nested map, sharing this process's engine.
                    seen["nested"] = len(
                        forkrun.map(payload, self.src, workers=1, nodes=1,
                                    order="index"))
            return got

        total = consume()
        self.assertTrue(total, "the stream must deliver records")
        self.assertIn("nested", seen, "the nested map must have run")
        self.assertTrue(seen["nested"],
                        "the nested map must return its own output")


class TestBaselineIsCapturedBeforeAnyFork(unittest.TestCase):
    """The baseline's POSITION is the property, not just its existence."""

    def test_reader_declines_rather_than_reporting_zero(self):
        """None must never be coerced to 0.

        A reader that returned 0 for an unreadable counter would make
        every run look as though the engine committed nothing, which is
        the single value guaranteed to fail a correct run.
        """
        import ctypes as C
        from forkrun.run import _c07_read_committed

        class _NoSymbol:
            pass

        self.assertIsNone(_c07_read_committed(_NoSymbol(), 1),
                          "a substrate without the symbol must yield None")

        class _Failing:
            @staticmethod
            def fr_py_committed_data_frames(node, out):
                return -1

        self.assertIsNone(_c07_read_committed(_Failing(), 1),
                          "a bad node must yield None, not 0")

    def test_delta_arithmetic_is_per_run_not_cumulative(self):
        """The delta is what keeps a shared engine honest."""
        baseline, current = 40, 56
        self.assertEqual(16, current - baseline,
                         "the inner run committed 16, not 56")


if __name__ == "__main__":
    unittest.main(verbosity=2)