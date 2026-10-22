"""The child-lifecycle helper must check the invariant it claims to.

`assert_no_zombies()` used to do a single `waitpid(-1, WNOHANG)` and
report the result as a "zombie leak". That conflates three different
outcomes, and the conflation had consequences beyond the wrong wording:

  * `waitpid` returning (0, 0) means "a child exists and has NOT
    terminated". A child that is still RUNNING is not a zombie. Worse,
    because the child stayed alive, the check kept failing EVERY later
    test in the run -- one test's leftover child failed 169 unrelated
    tests, and the failure moved between runs, so it looked like a
    production regression in a different place each time.

  * `waitpid(-1, ...)` reaps ANY child of this process, including one
    an EARLIER test left behind. That misattributes the failure to
    whichever test runs next, and destroys the evidence that the
    earlier test left the child.

  * A live child and an unreaped (terminated) child are DIFFERENT
    faults with different owners, and the report should say which.

And a fix that merely SUPPRESSES the repeat report is not a fix: making
a failure appear only once is not the same as making the resource leak
occur only once. The helper must RESOLVE the condition it reports --
the child terminated, waited for and reaped -- and it must attribute
the child to the test that CREATED it, not to whichever test noticed
it first.

These tests supply an EXPLICIT baseline, because that is the contract:
the helper must not terminate or reap a child whose owner it cannot
establish.

This file pins all of that, so a future change cannot quietly weaken
the assertion, re-introduce the misattribution, or reintroduce the
"remember to ignore it" behaviour.
"""

import io
import os
import signal
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import (ChildLifecycleMixin, assert_no_zombies,  # noqa: E402
                       child_census)


class _FailureSink:
    """Carries a failure message out of the helper.

    Deliberately NOT a TestCase: unittest collects every TestCase
    subclass in a module, and this is a carrier, not a test.
    """

    def __init__(self):
        self.message = None

    def fail(self, msg):
        self.message = msg


def _run_helper(before=None):
    """Run the helper; return its failure message, or None."""
    sink = _FailureSink()
    assert_no_zombies(sink, before=before)
    return sink.message


class TestChildLifecycleHelper(unittest.TestCase):
    """Each case is a deliberate child, and the helper's verdict on it."""

    def setUp(self):
        self._kids = []
        self._keep = []
        # The baseline: the children that existed BEFORE this test
        # created anything. The helper must treat only what is NOT in
        # here as this test's to answer for.
        self.baseline = child_census()

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
        """A child that stays ALIVE until released.

        The child blocks reading a pipe the parent holds open, so its
        lifetime is controlled rather than a race: `os.pause()` would
        depend on a signal arriving, and the cleanup's blocking wait
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

    def _exited_child(self):
        """A child that has EXITED and was NOT reaped: a real zombie."""
        pid = os.fork()
        if pid == 0:
            os._exit(3)
        self._kids.append(pid)
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
        return pid

    # -- the three outcomes --------------------------------------------

    def test_no_children_passes(self):
        """A process whose children have all been reaped passes."""
        self.assertEqual({}, child_census(),
                         "this test process should have no children")
        self.assertIsNone(_run_helper(before=self.baseline),
                          "the helper must pass when there are no children")

    def test_a_live_child_is_reported_as_running_not_as_a_zombie(self):
        """A child that has NOT terminated is a lifecycle leak, and it
        is reported as such -- not as a zombie."""
        self._live_child()
        msg = _run_helper(before=self.baseline)
        self.assertIsNotNone(msg,
                            "a child that is still running must be "
                            "reported, not ignored")
        self.assertIn("RUNNING", msg)
        self.assertNotIn("zombie", msg.lower(),
                         "a running child is not a zombie")

    def test_an_unreaped_terminated_child_is_reported_and_reaped(self):
        """A child that EXITED and was not reaped is the real zombie
        case: reported, and reaped here so it does not accumulate."""
        pid = self._exited_child()
        msg = _run_helper(before=self.baseline)
        self.assertIsNotNone(msg,
                            "an unreaped terminated child must be reported")
        self.assertIn("unreaped", msg)
        self.assertNotIn(pid, child_census(),
                         "the helper must reap the child it reports")

    # -- the leak must be RESOLVED, not just reported once -------------

    def test_a_reported_live_child_is_resolved_not_left_running(self):
        """A reported child must not be left behind.

        Reporting a leak and leaving the child alive is how one test's
        leftover failed every later test in the run. The helper must
        terminate it, wait for it and reap it, so the process is clean
        and the NEXT test inherits nothing.
        """
        pid = self._live_child()
        self.assertIsNotNone(_run_helper(before=self.baseline),
                            "the live child must be reported")
        self.assertNotIn(pid, child_census(),
                         "a reported child must be RESOLVED, not left "
                         "behind -- that is what made one leftover fail "
                         "169 unrelated tests")
        for p, state in child_census().items():
            self.assertNotEqual("Z", state,
                                "a reported child must not be left as a "
                                "zombie: pid %s" % (p,))

    def test_a_later_check_does_not_inherit_the_leak(self):
        """After the helper has resolved the leak, a later check passes
        because the child is GONE -- not because the helper remembers
        to skip it.

        This is the distinction the review asked for: making a failure
        appear only once is not the same as making the leak occur only
        once. If the helper were merely skipping a reported pid, the
        child would still be there.
        """
        pid = self._live_child()
        self.assertIsNotNone(_run_helper(before=self.baseline))
        self.assertNotIn(pid, child_census(),
                         "the child must be gone, not merely skipped")
        self.assertIsNone(_run_helper(before=self.baseline),
                          "a later check must pass because the leak was "
                          "resolved")

    def test_a_child_that_exits_after_being_reported_is_not_lost(self):
        """The state transition: observed alive, then exits.

        The old implementation recorded the pid as 'already reported'
        and SKIPPED it afterwards -- so a child that exited later became
        an unreaped zombie that nothing would ever reap. The helper
        must not lose track of it: it resolves the child when it
        reports it, so it never gets the chance to become a zombie, and
        nothing is left unreaped.
        """
        self._live_child()
        self.assertIsNotNone(_run_helper(before=self.baseline),
                            "the live child must be reported")
        self.assertIsNone(_run_helper(before=self.baseline),
                          "the resolved child must not reappear")
        for p, state in child_census().items():
            self.assertNotEqual("Z", state,
                                "a child that exited after being reported "
                                "must not be left unreaped: pid %s" % (p,))

    # -- ownership ------------------------------------------------------

    def test_a_child_that_predates_the_test_is_not_this_tests_business(self):
        """A child that existed BEFORE the test ran is not the test's to
        report -- and not the test's to kill."""
        pid = self._live_child()
        baseline = child_census()
        self.assertIsNone(_run_helper(before=baseline),
                          "a child from before the baseline is not this "
                          "test's to report")
        self.assertIn(pid, child_census(),
                      "a child that predates the test must NOT be killed "
                      "by the test's check -- it belongs to another owner")

    def test_without_a_baseline_the_helper_fails_closed(self):
        """No baseline means no ownership, and the helper must then touch
        NOTHING.

        Reporting that it does not know who owns a child does not make it
        safe to terminate one: the child may belong to another test, and
        killing it would destroy that test's evidence. So the helper
        reports the uncertainty and leaves every child alone.
        """
        pid = self._live_child()
        msg = _run_helper()          # no baseline at all
        self.assertIsNotNone(msg,
                            "without a baseline the helper must still "
                            "report, not pass silently")
        self.assertIn("ownership could NOT be established", msg)
        self.assertIn(pid, child_census(),
                      "without a baseline the helper must NOT terminate a "
                      "child whose owner it cannot establish")


class TestChildLifecycleMixin(unittest.TestCase):
    """The mixin must take the baseline BEFORE the class's own setup."""

    def test_the_baseline_precedes_the_class_setup(self):
        import _helpers

        seen = {}

        class Probe(_helpers.ChildLifecycleMixin, unittest.TestCase):
            def setUp(self):
                seen["baseline_at_setup"] = getattr(
                    self, "_child_baseline", None)
                seen["census_at_setup"] = _helpers.child_census()
                super().setUp()

            def test_nothing(self):
                pass

        case = Probe("test_nothing")
        case.setUp()
        try:
            self.assertIsNotNone(seen["baseline_at_setup"],
                                 "the mixin must record a baseline")
            self.assertEqual(seen["baseline_at_setup"],
                             seen["census_at_setup"],
                             "the baseline must be the census as it was "
                             "BEFORE the class's own setup ran")
        finally:
            case.doCleanups()


class _Patch:
    """Set an attribute for the duration of a block."""

    def __init__(self, obj, name, value):
        self.obj = obj
        self.name = name
        self.value = value
        self.old = None

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)
        return False


class TestCensusBoundaries(ChildLifecycleMixin, unittest.TestCase):
    """The census must distinguish "no children" from "do not know".

    An empty census and an UNAVAILABLE census are different states.
    The first means "this process has no children"; the second means
    "we could not find out". Reporting the second as the first turns
    an unknown into a clean result -- which is the failure mode this
    helper exists to prevent.

    These are the boundaries where the census can go wrong, and each
    one is pinned here.
    """

    def test_an_unreadable_task_list_is_not_an_empty_census(self):
        """If /proc/self/task cannot be listed, the census is
        UNAVAILABLE, not empty."""
        import _helpers
        real = os.listdir

        def _boom(path):
            if path == "/proc/self/task":
                raise OSError(13, "Permission denied")
            return real(path)

        with _Patch(os, "listdir", _boom):
            with self.assertRaises(_helpers.CensusUnavailable):
                _helpers.child_census()

    def test_an_unreadable_child_list_is_not_an_empty_census(self):
        """A per-task child list that cannot be read is the same
        failure: part of the census is missing."""
        import _helpers
        import builtins
        real_open = builtins.open

        def _boom(path, *args, **kwargs):
            if "/children" in str(path):
                raise OSError(5, "I/O error")
            return real_open(path, *args, **kwargs)

        with _Patch(builtins, "open", _boom):
            with self.assertRaises(_helpers.CensusUnavailable):
                _helpers.child_census()

    def test_a_thread_that_exits_mid_census_is_not_a_failure(self):
        """A thread that exits between the listing and the read is NOT
        an incomplete census: its children were re-parented, so they
        are not ours to answer for."""
        import _helpers
        import builtins
        real_open = builtins.open

        def _boom(path, *args, **kwargs):
            if "/children" in str(path):
                raise FileNotFoundError(2, "No such file or directory")
            return real_open(path, *args, **kwargs)

        with _Patch(builtins, "open", _boom):
            census = _helpers.child_census()
        self.assertIsInstance(census, dict)

    def test_a_child_that_exits_during_the_census_reads_as_unknown(self):
        """A child that exits between the enumeration and the state
        read has an unknown state -- not a false 'Z' and not a false
        'R'."""
        import _helpers
        import builtins
        real_open = builtins.open

        def _boom(path, *args, **kwargs):
            if "/children" in str(path):
                return io.StringIO("999999\n")
            if "/stat" in str(path):
                raise FileNotFoundError(2, "No such file or directory")
            return real_open(path, *args, **kwargs)

        with _Patch(builtins, "open", _boom):
            census = _helpers.child_census()
        self.assertIn(999999, census)
        self.assertEqual("?", census[999999],
                         "a child that vanished must read as UNKNOWN, not "
                         "as a zombie and not as running")

    def test_the_lifecycle_check_fails_closed_on_an_unknown_census(self):
        """An unavailable census must FAIL the check, not pass it."""
        import _helpers

        def _boom():
            raise _helpers.CensusUnavailable("no /proc here")

        with _Patch(_helpers, "child_census", _boom):
            sink = _FailureSink()
            _helpers.assert_no_zombies(sink, before={})
        self.assertIsNotNone(sink.message,
                            "an unavailable census was reported as a clean "
                            "result")
        self.assertIn("UNKNOWN", sink.message)

    def test_a_pre_existing_child_is_never_touched(self):
        """A child that predates the baseline belongs to another owner:
        it is neither reported nor killed."""
        import _helpers
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(w)
                os.read(r, 1)
            except BaseException:
                pass
            os._exit(0)
        os.close(r)
        try:
            baseline = _helpers.child_census()
            self.assertIn(pid, baseline)
            sink = _FailureSink()
            _helpers.assert_no_zombies(sink, before=baseline)
            self.assertIsNone(sink.message,
                              "a pre-existing child was reported as a leak")
            self.assertIn(pid, _helpers.child_census(),
                          "a pre-existing child was killed")
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass
            try:
                os.close(w)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
