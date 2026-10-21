"""The child-lifecycle helper must check the invariant it claims to.

`assert_no_zombies()` used to do a single `waitpid(-1, WNOHANG)` and
report the result as a "zombie leak". That conflates three different
outcomes, and the conflation had consequences beyond the wrong wording:

  * `waitpid` returning (0, 0) means "a child exists and has NOT
    terminated". A child that is still RUNNING is not a zombie. Worse,
    because the child stayed alive, the check kept failing EVERY later
    test in the run -- one test's leftover child failed 169 unrelated
    tests, and the failure moved between runs, so it looked like a
    production regression.

  * `waitpid(-1, ...)` reaps ANY child of this process, including one
    an EARLIER test left behind. That misattributes the failure to
    whichever test runs next, and destroys the evidence that the
    earlier test left the child.

  * A live child and an unreaped (terminated) child are DIFFERENT
    faults with different owners, and the report should say which.

This file pins the helper's behaviour on all three, so a future change
to it cannot quietly weaken the assertion or re-introduce the
misattribution.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import (assert_no_zombies, child_census,  # noqa: E402
                       _REPORTED)


class _FailureSink:
    """Carries a failure message out of the helper.

    Deliberately NOT a TestCase: unittest collects every TestCase
    subclass in a module, and this is a carrier, not a test.
    """

    def __init__(self):
        self.message = None

    def fail(self, msg):
        self.message = msg


class TestChildLifecycleHelper(unittest.TestCase):
    """Each case is a deliberate child, and the helper's verdict on it."""

    def setUp(self):
        self._kids = []
        self._keep = []

    def tearDown(self):
        for fd in self._keep:
            try:
                os.close(fd)
            except OSError:
                pass
        for pid in self._kids:
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass

    def _live_child(self):
        """A child that stays ALIVE until the test releases it.

        The child blocks reading a pipe the parent holds open, so its
        lifetime is controlled rather than a race: `os.pause()` would
        depend on a signal arriving, and the cleanup's blocking waitpid
        would then be at the mercy of that race.
        """
        r, w = os.pipe()
        self._keep.append(w)
        pid = os.fork()
        if pid == 0:
            try:
                os.close(w)
                os.read(r, 1)          # returns when the parent closes w
            except BaseException:
                pass
            os._exit(0)
        os.close(r)
        self._kids.append(pid)
        return pid

    def _failing_helper(self):
        """Run the helper and return the failure message, or None."""
        sink = _FailureSink()
        assert_no_zombies(sink)
        return sink.message

    def test_no_children_passes(self):
        """A process whose children have all been reaped passes."""
        self.assertEqual({}, child_census(),
                         "this test process should have no children")
        self.assertIsNone(self._failing_helper(),
                          "the helper must pass when there are no children")

    def test_a_live_child_is_reported_as_running_not_as_a_zombie(self):
        """A child that has NOT terminated is a lifecycle leak, and it is
        reported as such -- not as a zombie, and not reaped."""
        pid = self._live_child()
        msg = self._failing_helper()
        self.assertIsNotNone(msg,
                            "a child that is still running must be "
                            "reported, not ignored")
        self.assertIn("RUNNING", msg)
        self.assertNotIn("zombie", msg.lower(),
                         "a running child is not a zombie")
        # It must NOT have been reaped: it is still running.
        self.assertIn(pid, child_census(),
                      "the helper must not reap a running child")

    def test_an_unreaped_terminated_child_is_reported_and_reaped(self):
        """A child that EXITED and was not reaped is the real zombie
        case: reported, and reaped here so it does not accumulate."""
        pid = os.fork()
        if pid == 0:
            os._exit(3)
        self._kids.append(pid)
        # wait for it to exit, WITHOUT reaping it
        deadline = 0
        while deadline < 1000:
            try:
                with open("/proc/%d/stat" % pid) as fh:
                    data = fh.read()
                if data[data.rfind(")") + 2] == "Z":
                    break
            except OSError:
                break
            deadline += 1
        msg = self._failing_helper()
        self.assertIsNotNone(msg,
                            "an unreaped terminated child must be reported")
        self.assertIn("unreaped", msg)
        # The helper reaped it, so it is gone from the census.
        self.assertNotIn(pid, child_census(),
                         "the helper must reap the child it reports")

    def test_a_leftover_child_is_reported_once_not_by_every_later_test(self):
        """The attribution property: a child left behind is blamed on
        the test that left it, and the LATER tests are not failed by
        it. This is what stops one test's leftover from failing the
        rest of the run."""
        pid = self._live_child()
        first = self._failing_helper()
        self.assertIsNotNone(first,
                            "the test that leaves a child must fail")
        second = self._failing_helper()
        self.assertIsNone(second,
                          "a child already reported must not fail the "
                          "NEXT test as well -- that is how one leftover "
                          "failed 169 unrelated tests")


if __name__ == "__main__":
    unittest.main()
