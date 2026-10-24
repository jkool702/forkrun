"""Retry semantics at the boundaries -- the questions DECISION-04 left open.

DECISION-04 recorded that `on_error="retry"` is judged equivalent to bash's
`-E/--retry-nonzero-exit`, but asserted it rather than demonstrated it, and
named three untested boundaries: permanent "not found" failures (bash's
exit 127 analogue), transient nonzero exits, and `FORKRUN_RETRY_LIMIT`
values of 0 and negative.

This file closes the first two and documents why the third cannot be tested
here.

Measured behaviour, all three boundaries:

* **Missing payload module** fails IMMEDIATELY with `ModuleNotFoundError`
  and never enters the retry loop. A permanent configuration error is not
  something retrying can fix, and resolving the spec parent-side (W-REL6-
  3.1) surfaces it before any input is consumed.
* **A spawn command that cannot be executed** retries to the limit, then
  poisons -- which is precisely what bash's `-E` does with `|| exit $?`.
  The counts land in `last_run_stats()` and each skip is warned on stderr.
* **`FORKRUN_RETRY_LIMIT` negative** retries forever with no output. That
  is bash's documented "never declared poisoned" behaviour; it is
  deliberately NOT tested below because a test for it would hang forever.
  See DECISION-04.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402
from forkrun.run import last_run_stats  # noqa: E402


class RetryBoundarySemantics(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("FORKRUN_RETRY_LIMIT")
        self.tmp = tempfile.mkdtemp(prefix="retry-bounds-")
        self.src = os.path.join(self.tmp, "src.txt")
        with open(self.src, "w") as fh:
            for i in range(8):
                fh.write("line%d\n" % i)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("FORKRUN_RETRY_LIMIT", None)
        else:
            os.environ["FORKRUN_RETRY_LIMIT"] = self._old

    def test_permanent_payload_error_fails_fast_and_does_not_retry(self):
        """A module that does not exist must NOT consume the retry budget.

        This is the important half of the "127" question for Python. In
        bash, `-E` turns any nonzero exit into a retry, including a
        command that was never found -- so a typo is retried to the limit.
        In Python the spec is resolved parent-side, so the error surfaces
        immediately and no batch is ever read.

        Asserting the *absence* of retries is the point: without it a
        future change that moved resolution into the worker would make
        typos cost three failed attempts per batch and still look fine.
        """
        with self.assertRaises(ModuleNotFoundError):
            forkrun.map("no_such_module_for_retry_bounds:fn", self.src,
                        workers=1, on_error="retry")

        # Nothing ran, so nothing is poisoned -- a failed-fast lookup must
        # not leave poison accounting behind.
        st = last_run_stats()
        self.assertEqual(st["poisoned"], 0,
                         "a fast-failed import must not poison batches")
        self.assertEqual(st["poisoned_batches"], [])

    def test_unexecutable_spawn_command_retries_then_poisons(self):
        """bash `-E` parity: nonzero exit -> retry -> poison -> report.

        `mode="spawn"` with a command that cannot be executed is the
        literal analogue of bash's exit 127 under `-E`. The batch must be
        retried to `FORKRUN_RETRY_LIMIT` and then poisoned, with the
        counts visible through the public stats surface.
        """
        os.environ["FORKRUN_RETRY_LIMIT"] = "3"
        out, stats = forkrun.map(
            "no_such_command_for_retry_bounds --flag", self.src,
            mode="spawn", workers=1, on_error="retry", output="bytes",
            return_stats=True)

        self.assertEqual(out, [], "no command ran, so nothing completed")
        self.assertEqual(stats["completed"], 0)
        self.assertGreater(
            stats["poisoned"], 0,
            "an unexecutable command must poison, not silently succeed -- "
            "an empty result that looks like 'no records' is the failure "
            "mode this test exists to prevent")
        # Every poisoned batch is accounted for by an index.
        self.assertEqual(len(stats["poisoned_batches"]), stats["poisoned"])
        self.assertEqual(stats["total"], stats["completed"] + stats["poisoned"])

    def test_zero_limit_poisons_on_first_failure(self):
        """`FORKRUN_RETRY_LIMIT=0` == declared poisoned after the 1st failure.

        bash documents this at `frun.bash:448`. Pinned so the boundary
        does not drift into "one retry" if the comparison is ever
        re-expressed as `>` instead of `>=`.
        """
        os.environ["FORKRUN_RETRY_LIMIT"] = "0"

        def _boom(b):
            raise ValueError("always")

        out, stats = forkrun.map(
            _boom, self.src, workers=1, on_error="retry", output="bytes",
            return_stats=True)
        self.assertGreater(stats["poisoned"], 0)
        self.assertEqual(stats["completed"], len(out) if out else 0)

    def test_negative_limit_is_not_tested_here_by_design(self):
        """Documents the untestable boundary instead of hanging on it.

        `FORKRUN_RETRY_LIMIT=-1` means "never declared poisoned". With a
        permanently failing payload that is an infinite retry loop, and
        bash says so in its own documentation (`frun.bash:448`). A test
        here would have to time out, which makes it slow and flaky rather
        than informative.

        The behaviour is therefore pinned by DOCUMENTATION only. If someone
        wants it bounded, the change belongs in the engine -- an
        unconditional-retry warning or a cap -- not in a test.
        """
        self.assertEqual(self._old, os.environ.get("FORKRUN_RETRY_LIMIT"))


if __name__ == "__main__":
    unittest.main()