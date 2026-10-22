"""The teardown must not be abandonable, and a forked child must not be
orphanable.

TWO DEFECTS, ONE CONTRACT
-------------------------
These tests cover the pair of lifecycle holes that let a run leave a
child behind:

  1. THE FORK WINDOW. Between ``os.fork()`` and the bookkeeping that
     owns the child (the reactor's ``self.workers[wid] = slot``), an
     exception -- a signal handler firing, a MemoryError -- orphans
     the child. It is invisible: the teardown cannot kill it, cannot
     reap it, and when it exits it is a zombie. That is the exact
     signature seen in ``test_resume_sigint`` (a forked ``python3``
     child, terminated but unreaped), and it is reproducible on
     demand: inject an interrupt in that window and the child leaks.

  2. THE CLEANUP WINDOW. The teardown's cleanup sequence ran with
     SIGINT unblocked, so an interrupt arriving mid-sequence skipped
     the remaining reaps -- the children it had not reached were left
     behind. The cleanup now runs with the interrupt DEFERRED: it is
     not swallowed, it is delivered as soon as the sequence completes.

The invariant both holes broke is the same one, so it is asserted
once, at the end of every case: **after the run, this process has no
children**. Not "no zombies" -- no children at all. A live child and
an unreaped child are the same failure here: the run did not clean up
after itself.

Each case injects the fault at a CONTROLLED point and asserts the
outcome, so a regression is a deterministic failure rather than an
intermittent one that only shows up in a full gate run.
"""

import os
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun import _childreg  # noqa: E402

# `forkrun.run` is the public run() FUNCTION (the package __init__ binds
# it), so the module has to be fetched explicitly.
_run = __import__("importlib").import_module("forkrun.run")

from _helpers import (ChildLifecycleMixin, child_census,  # noqa: E402
                    redirect_fd, restore_fd, write_lines)


def _up(batch):
    return bytes(batch.data).upper()


class _Patch:
    """Restore a module attribute on exit."""

    def __init__(self, module, name, value):
        self.module = module
        self.name = name
        self.value = value
        self.old = None

    def __enter__(self):
        self.old = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.old)
        return False


class TestTeardownInterruptSafety(ChildLifecycleMixin, unittest.TestCase):
    """A run that is interrupted must still clean up after itself."""

    def setUp(self):
        super().setUp()
        fd, self.path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        write_lines(self.path, 200)
        self.addCleanup(os.unlink, self.path)
        self._reports = []
        # The registry's report is the instrumentation: it names the
        # orphan it resolved. Capture it instead of scraping stderr.
        self._patch_report = _Patch(_childreg, "report_orphans",
                                    self._capture_reports)
        self._patch_report.__enter__()
        self.addCleanup(self._patch_report.__exit__, None, None, None)

    def _capture_reports(self, resolved, stream=None):
        self._reports.extend(resolved)

    def _assert_no_children(self):
        """The invariant: after the run, this process has no children."""
        census = child_census()
        self.assertEqual(
            {}, census,
            "the run left children behind: %s" % (
                {p: s for p, s in census.items()},))

    # -- 1. the fork window ------------------------------------------

    def test_an_interrupt_in_the_fork_window_leaves_no_child(self):
        """An exception between os.fork() and the record that owns the
        child must not orphan it.

        This is the regression. The reactor records the worker in
        ``self.workers[wid]`` a few statements AFTER the fork; an
        interrupt in that window left the child forked, unowned, and
        (once it exited) a zombie. The registry closes the window: the
        child is adopted at the fork, so the teardown can find it.
        """
        from forkrun import _executor_core

        real = _executor_core.warn_fork_cost_once
        state = {"fired": False}

        def _boom(fork_ms, n_workers, rss_kb=None):
            # The reactor calls this in the PARENT, between os.fork()
            # and self.workers[wid] = slot.
            if not state["fired"]:
                state["fired"] = True
                raise KeyboardInterrupt("injected in the fork window")
            return real(fork_ms, n_workers, rss_kb)

        with _Patch(_executor_core, "warn_fork_cost_once", _boom):
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, orchestrator=True,
                            order="index", nodes=1)

        self.assertTrue(state["fired"],
                        "the injection point was not reached -- the test "
                        "would pass without exercising anything")
        self._assert_no_children()

    def test_the_orphan_is_reported_not_silently_resolved(self):
        """The fix does not hide the event: the orphan is named.

        A cleanup that silently swallows a leak is a cleanup that
        hides the defect. The registry reports what it resolved, so a
        future occurrence is diagnosable rather than mysterious.
        """
        from forkrun import _executor_core

        real = _executor_core.warn_fork_cost_once
        state = {"fired": False}

        def _boom(fork_ms, n_workers, rss_kb=None):
            if not state["fired"]:
                state["fired"] = True
                raise KeyboardInterrupt("injected in the fork window")
            return real(fork_ms, n_workers, rss_kb)

        with _Patch(_executor_core, "warn_fork_cost_once", _boom):
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, orchestrator=True,
                            order="index", nodes=1)

        self.assertTrue(self._reports,
                        "the orphan was resolved but NOT reported -- a "
                        "silent cleanup hides the defect it just fixed")
        pid, owner, outcome = self._reports[0]
        self.assertEqual("worker", owner,
                         "the report must name what leaked")
        self.assertNotIn(pid, child_census(),
                         "the reported orphan must be gone")

    # -- 2. the cleanup window ---------------------------------------

    def _fire_sigint_during_the_teardown(self):
        """Deliver a REAL SIGINT from inside the teardown.

        A real signal, not a raised exception: the deferral is about
        SIGNALS, and a raised exception would exercise a different
        path. The teardown is entered through its own symbol, so the
        "in teardown" flag is exact -- the run's own path also joins
        helpers, and firing there would not test the cleanup window.
        """
        real_teardown = _run._teardown_reactor
        real_join = _run._join_helper_bounded
        state = {"fired": False, "in_teardown": False, "reconciled": False}

        def _patched_teardown(*args, **kwargs):
            state["in_teardown"] = True
            try:
                return real_teardown(*args, **kwargs)
            finally:
                state["in_teardown"] = False

        def _patched_join(pid, name, timeout=None):
            if not state["fired"] and state["in_teardown"]:
                state["fired"] = True
                os.kill(os.getpid(), signal.SIGINT)
            if timeout is None:
                return real_join(pid, name)
            return real_join(pid, name, timeout)

        def _patched_reconcile():
            state["reconciled"] = True
            return []

        return state, [
            _Patch(_run, "_teardown_reactor", _patched_teardown),
            _Patch(_run, "_join_helper_bounded", _patched_join),
            _Patch(_childreg, "reconcile", _patched_reconcile),
        ]

    def test_a_signal_during_the_teardown_does_not_abandon_the_cleanup(self):
        """A SIGINT that arrives DURING the cleanup must not skip the
        remaining steps.

        The cleanup sequence is not abandonable: it runs with the
        interrupt deferred, so the steps it had not reached still run
        (the reconciliation -- the LAST step -- still happens). And
        the interrupt is NOT swallowed: it is delivered once the
        sequence completes.
        """
        state, patches = self._fire_sigint_during_the_teardown()
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, orchestrator=True,
                            order="index", nodes=1)

        self.assertTrue(state["fired"],
                        "the SIGINT was never delivered -- the test would "
                        "pass without exercising the cleanup window")
        self.assertTrue(state["reconciled"],
                        "the cleanup was ABANDONED at the interrupt: its "
                        "last step never ran, so the children it had not "
                        "reached were left behind")
        self._assert_no_children()

    def test_a_signal_during_the_teardown_keeps_the_runs_own_error(self):
        """Exception precedence: a cleanup interrupted by a second
        signal must not replace the error the run was already raising.

        The run's exception is the run's REASON for stopping. A second
        Ctrl-C during the cleanup is redundant -- it must not become
        the reported error, or the operator loses the diagnosis.
        """
        def _boom(batch):
            raise RuntimeError("synthetic worker failure")

        state, patches = self._fire_sigint_during_the_teardown()
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(RuntimeError) as cm:
                forkrun.map(_boom, self.path, workers=2, orchestrator=True,
                            order="index", on_error="fail-fast", nodes=1)

        self.assertTrue(state["fired"],
                        "the SIGINT was never delivered -- the test would "
                        "pass without exercising the cleanup window")
        self.assertNotIsInstance(cm.exception, KeyboardInterrupt,
                                 "the deferred signal replaced the run's "
                                 "own error")
        self.assertTrue(state["reconciled"],
                        "the cleanup was abandoned at the interrupt")
        self._assert_no_children()

    def test_a_signal_during_the_teardown_still_checkpoints(self):
        """Checkpoint semantics survive the deferred interrupt.

        The abort choreography publishes the checkpoint BEFORE the
        teardown runs, so a signal delivered during the cleanup
        cannot cost the run its checkpoint: the checkpoint is on disk
        and the run is resumable. This is the real shape of the
        failure that started the investigation -- an operator Ctrl-C
        during a run, with the cleanup interrupted as well.
        """
        ckpt = self.path + ".ckpt"
        counter = self.path + ".count"
        self.addCleanup(
            lambda: os.path.exists(ckpt) and os.unlink(ckpt))
        self.addCleanup(
            lambda: os.path.exists(counter) and os.unlink(counter))
        for extra in (ckpt, ckpt + ".coll"):
            if os.path.exists(extra):
                os.unlink(extra)

        def _aborting(batch):
            # Abort after some progress, so the checkpoint has
            # something to record.
            with open(counter, "ab") as fh:
                fh.write(b"x")
            if os.path.getsize(counter) >= 8:
                raise RuntimeError("synthetic abort")
            return bytes(batch.data).upper()

        state, patches = self._fire_sigint_during_the_teardown()
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(RuntimeError) as cm:
                forkrun.map(_aborting, self.path, workers=2,
                            orchestrator=True, order="index",
                            on_error="fail-fast", checkpoint_file=ckpt,
                            nodes=1)

        self.assertNotIsInstance(cm.exception, KeyboardInterrupt,
                                 "the deferred signal replaced the run's "
                                 "own error")
        self.assertTrue(state["reconciled"],
                        "the cleanup was abandoned at the interrupt")
        self.assertTrue(os.path.exists(ckpt),
                        "the interrupt during the cleanup cost the run "
                        "its checkpoint")
        self._assert_no_children()


class TestBoundedReap(unittest.TestCase):
    """A child that cannot be reaped must be REPORTED, not waited on
    forever.

    The post-SIGKILL reap used to be an unbounded blocking wait. A
    process in uninterruptible sleep does not die on SIGKILL, so that
    wait could hang the entire run with no report -- and a run that
    hangs is a run that never says what went wrong.
    """

    def test_the_post_sigkill_reap_is_bounded(self):
        """The reap gives up at the deadline and says the child is
        unresolved."""
        from forkrun import _resume

        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(w)
                os.read(r, 1)        # block until the parent closes w
            except BaseException:
                pass
            os._exit(0)
        os.close(r)

        real_waitpid = os.waitpid

        def _never_reaped(wpid, opts):
            if wpid == pid:
                return (0, 0)        # as if the child never exits
            return real_waitpid(wpid, opts)

        os.waitpid = _never_reaped
        try:
            import time
            start = time.monotonic()
            reaped, status = _resume._waitpid_bounded(pid, 0.05)
            elapsed = time.monotonic() - start
        finally:
            os.waitpid = real_waitpid
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

        self.assertFalse(reaped,
                         "a child that could not be reaped was reported "
                         "as REAPED")
        self.assertIsNone(status,
                          "a child that could not be reaped must not "
                          "carry a wait status")
        self.assertLess(elapsed, 5.0,
                        "the reap was not bounded: it took %.1fs"
                        % (elapsed,))

    def test_an_unreapable_helper_is_reported_by_name(self):
        """The join names the helper it could not reap.

        The report goes to fd 2 (the process's stderr), not to
        sys.stderr, so it is captured at the fd level.
        """
        run_mod = __import__("importlib").import_module("forkrun.run")
        real_join = run_mod._join_helper_bounded

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

        real_waitpid = os.waitpid

        def _never_reaped(wpid, opts):
            if wpid == pid:
                return (0, 0)
            return real_waitpid(wpid, opts)

        os.waitpid = _never_reaped
        cap = os.path.join(os.path.dirname(__file__), "_stderr_cap.txt")
        saved = redirect_fd(2, cap)
        try:
            status = real_join(pid, "the-helper", 0.05)
        finally:
            restore_fd(2, saved)
            os.waitpid = real_waitpid
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
        with open(cap, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        try:
            os.unlink(cap)
        except OSError:
            pass

        self.assertIsNone(status,
                          "an unreapable helper must not carry a status")
        self.assertIn("the-helper", text,
                      "the report must NAME the helper it could not reap")


class TestChildRegistry(unittest.TestCase):
    """The registry itself: it must never report a bystander."""

    def test_a_pid_that_is_not_our_child_is_not_signalled(self):
        """The registry signals a registered pid only while it is still
        OUR child.

        The PID-reuse hazard is real: a pid in the registry may have
        been reaped long ago and recycled. The check is "is it still
        my child?" (waitpid raises ChildProcessError otherwise), not
        "was it ever my child?" -- so a bystander is never signalled.
        """
        _childreg.reset()
        try:
            # A pid that is definitely not our child.
            _childreg.adopt(999999, "bystander")
            resolved = _childreg.reap_orphans(timeout=0.1)
            self.assertEqual([], resolved,
                             "the registry signalled a pid that is not "
                             "our child")
        finally:
            _childreg.reset()

    def test_adopt_ignores_the_child_branch(self):
        """The child branch of a fork must not register pid 0."""
        _childreg.reset()
        try:
            _childreg.adopt(0, "worker")
            self.assertEqual({}, _childreg.pending(),
                             "the child branch must not register a pid")
        finally:
            _childreg.reset()


if __name__ == "__main__":
    unittest.main()
