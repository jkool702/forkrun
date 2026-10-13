"""Poison accounting must not differ between supported configurations.

TD-09. `last_run_stats()` documents five keys, and one of them --
``poisoned_batches`` -- is populated on the reactor path (the default) and
on both cleanroom paths, but comes back EMPTY on ``orchestrator=False``.
The engine exposes only a poisoned COUNT there, so the list cannot be
built from what that path has.

This test does NOT bless that asymmetry. It pins what each path actually
returns so the divergence cannot be quietly re-promised by a docstring,
and so the day the C accessor lands this test is the thing that changes.
The assertion on the plain path is written as a known-gap assertion with
a defect reference, not as "this is correct".
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402
from forkrun.run import last_run_stats  # noqa: E402


def _maybe_fail(b):
    if b"BOOM" in b:
        raise ValueError("deliberate failure")
    return b"ok:" + b


class PoisonAccountingParity(unittest.TestCase):
    """Same scenario, every supported configuration, compared."""

    def setUp(self):
        self._old_limit = os.environ.get("FORKRUN_RETRY_LIMIT")
        # 0 == declared poisoned after the 1st failure, so this is
        # deterministic and does not depend on retry timing.
        os.environ["FORKRUN_RETRY_LIMIT"] = "0"
        self.tmp = tempfile.mkdtemp(prefix="poison-parity-")
        self.src = os.path.join(self.tmp, "src.txt")
        with open(self.src, "w") as fh:
            for i in range(8):
                fh.write("BOOM\n" if i == 3 else "line%d\n" % i)

    def tearDown(self):
        if self._old_limit is None:
            os.environ.pop("FORKRUN_RETRY_LIMIT", None)
        else:
            os.environ["FORKRUN_RETRY_LIMIT"] = self._old_limit

    def _run(self, **kw):
        out, stats = forkrun.map(
            _maybe_fail, self.src, workers=1, on_error="retry",
            output="bytes", return_stats=True, **kw)
        return out, stats, last_run_stats()

    def test_poisoned_count_agrees_across_orchestrator_settings(self):
        """The PORTABLE field must agree, whatever orchestrator is set to.

        This is the assertion that actually protects callers: `poisoned`
        is what `total` is derived from, so if the count diverged the
        headline numbers would be wrong on one path only.
        """
        _, plain_stats, plain_last = self._run(orchestrator=False)
        _, reactor_stats, reactor_last = self._run(orchestrator=True)

        self.assertGreater(plain_stats["poisoned"], 0,
                           "scenario must actually poison something, or "
                           "this test proves nothing")
        self.assertEqual(plain_stats["poisoned"], reactor_stats["poisoned"])
        self.assertEqual(plain_last["poisoned"], reactor_last["poisoned"])
        self.assertEqual(plain_stats["total"], reactor_stats["total"])

    def test_poisoned_batches_indices_populated_on_reactor_path(self):
        """The default path honours the documented contract."""
        _, stats, last = self._run(orchestrator=True)
        self.assertEqual(
            len(stats["poisoned_batches"]), stats["poisoned"],
            "every poisoned batch must be listed when indices are "
            "available; a truncated list must set poisoned_batches_"
            "truncated instead")
        self.assertFalse(stats["poisoned_batches_truncated"])
        self.assertEqual(stats["poisoned_batches"],
                         sorted(set(stats["poisoned_batches"])))
        self.assertEqual(last["poisoned_batches"],
                         stats["poisoned_batches"])

    def test_poisoned_batches_empty_on_non_reactor_path_KNOWN_GAP(self):
        """KNOWN GAP (TD-09), pinned so it cannot be forgotten.

        `orchestrator=False` is a supported public value, yet it reports
        `poisoned_batches == []` alongside a non-zero `poisoned`. If this
        assertion ever starts failing because the gap was closed, delete
        it and extend the test above to cover orchestrator=False -- do not
        just relax it.
        """
        out, stats, last = self._run(orchestrator=False)
        self.assertGreater(stats["poisoned"], 0)
        self.assertEqual(
            stats["poisoned_batches"], [],
            "TD-09 said this path cannot list indices. If it now can, the "
            "C accessor landed and this gap assertion is obsolete.")
        self.assertEqual(last["poisoned_batches"], [])
        # out is None here: on_error="retry" poisons rather than skipping,
        # so no batch completes.
        self.assertEqual(stats["completed"], len(out) if out else 0)


if __name__ == "__main__":
    unittest.main()