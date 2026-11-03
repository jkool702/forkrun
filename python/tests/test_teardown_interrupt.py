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

import ast
import os
import signal
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun import _childreg  # noqa: E402

# `forkrun.run` is the public run() FUNCTION (the package __init__ binds
# it), so the module has to be fetched explicitly.
_run = __import__("importlib").import_module("forkrun.run")

from _helpers import (ChildLifecycleMixin, DefaultSigint as _DefaultSigint,
                      child_census, redirect_fd, restore_fd,
                      sigint_action_addr as _sigint_action_addr,
                      sigint_from_thread, write_lines)


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
        # The run-lock session marker is the other half of "the run
        # finished". A late deferred delivery could land inside
        # __exit__ before the marker was cleared; that leaves every
        # later run in this thread refused as a nested run. It passed
        # here once while poisoning every test after it, so it is
        # asserted where the other lifecycle invariants are.
        local = _run._RUN_LOCK._local
        self.assertFalse(
            getattr(local, "active", False),
            "the run left this thread marked as having a live forkrun "
            "session: every later run in this thread will be refused as "
            "nested")

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
        with _DefaultSigint(), patches[0], patches[1], patches[2]:
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

    def test_a_sibling_thread_signal_cannot_abandon_the_teardown(self):
        """The ORIGINAL failure shape: delivered to an eligible sibling.

        The old ``pthread_sigmask`` deferred only the MAIN thread. In a
        multi-threaded host the kernel delivered the worker's SIGINT to
        an eligible sibling, and CPython raised KeyboardInterrupt in the
        main thread anyway -- inside the cleanup, abandoning the reaps.
        This test masks the main thread and keeps an unmasked sibling
        alive, so the signal MUST go to the sibling. The process-wide
        recorder is the only thing that can defer it.

        The run itself is normal (no abort): this is the late-signal
        case. The run had already completed when the interrupt arrived,
        so there is no checkpoint to write; what must survive is the
        cleanup. The original failure reported exactly this signature --
        no checkpoint, one killed-but-unreaped child, three still live.
        """
        ready = threading.Event()
        stop = threading.Event()

        def _spin():
            ready.set()
            while not stop.is_set():
                time.sleep(0.005)

        sibling = threading.Thread(target=_spin, daemon=True)
        sibling.start()
        self.assertTrue(ready.wait(5), "the sibling thread never started")
        oldmask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGINT})
        try:
            state, patches = self._fire_sigint_during_the_teardown()
            with _DefaultSigint(), patches[0], patches[1], patches[2]:
                with self.assertRaises(KeyboardInterrupt):
                    forkrun.map(_up, self.path, workers=2,
                                orchestrator=True, order="index", nodes=1)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, oldmask)
            stop.set()
            sibling.join(5)
        self.assertTrue(state["fired"],
                        "the SIGINT was never delivered -- the test would "
                        "pass without exercising the cleanup window")
        self.assertTrue(
            state["reconciled"],
            "the cleanup was ABANDONED by a signal delivered to a sibling "
            "thread: the last step never ran, so the children it had not "
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
        with _DefaultSigint(), patches[0], patches[1], patches[2]:
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
        with _DefaultSigint(), patches[0], patches[1], patches[2]:
            # bytes=16 is load-bearing, not a tuning knob. With the
            # default batch sizing this 200-line input yields 25
            # batches on a 28-vCPU host but only 7 on a 4-vCPU runner
            # (GitHub's), so the 8th invocation below never happens and
            # the run COMPLETES. The teardown then delivers the
            # injected SIGINT with no exception in flight -- correct
            # behaviour, but not the abort this test is about, and
            # unittest re-raises KeyboardInterrupt, which aborted the
            # whole suite with exit 130. An explicit cap makes the
            # batch count independent of the CPU count.
            try:
                forkrun.map(_aborting, self.path, workers=2,
                            orchestrator=True, order="index",
                            on_error="fail-fast", checkpoint_file=ckpt,
                            nodes=1, bytes=16)
            except BaseException as exc:
                # Catch KeyboardInterrupt HERE on purpose: if the
                # premise ever breaks again it must be a reported test
                # failure, not a suite-aborting escape. The negative
                # check is load-bearing: ForkrunInterrupted subclasses
                # BOTH RuntimeError and KeyboardInterrupt, so the
                # positive check alone cannot tell the run's synthetic
                # RuntimeError from a deferred interrupt that surfaced
                # as ForkrunInterrupted. This one separates them.
                self.assertNotIsInstance(
                    exc, KeyboardInterrupt,
                    "the deferred signal surfaced as KeyboardInterrupt: "
                    "either it replaced the run's own abort, or the run "
                    "completed first so no abort was in flight (broken "
                    "premise) -- %r" % (exc,))
                self.assertIsInstance(
                    exc, RuntimeError,
                    "expected the run's synthetic abort, got %r" % (exc,))
            else:
                self.fail("the run completed without aborting; the "
                          "checkpoint path was never exercised")
        self.assertTrue(state["reconciled"],
                        "the cleanup was abandoned at the interrupt")
        self.assertTrue(os.path.exists(ckpt),
                        "the interrupt during the cleanup cost the run "
                        "its checkpoint")
        self._assert_no_children()


class TestRunDepthBoundaries(ChildLifecycleMixin, unittest.TestCase):
    """The run-depth token owns BOTH edges of every executor's window.

    The old shape incremented BEFORE the ``try`` and decremented as the
    first statement of ``finally``. A SIGINT in either window leaked the
    depth (every later run believes it is nested and stops certifying)
    or skipped the teardown after the depth was already released.

    Both edges are exercised: a REAL signal at the acquisition boundary
    and at the release boundary, plus a deterministic before-acquire
    failure and an unwinding release where the signal must be dropped.
    """

    def setUp(self):
        super().setUp()
        fd, self.path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        write_lines(self.path, 200)
        self.addCleanup(os.unlink, self.path)

    def _assert_clean(self, base):
        self.assertEqual(
            _run._C07_RUN_DEPTH[0], base,
            "the run depth leaked: every later top-level run would "
            "believe it is nested and silently stop certifying")
        self.assertEqual({}, child_census(),
                         "the interrupted run left children behind")

    def test_an_interrupt_before_acquisition_leaves_no_depth(self):
        """No token was acquired, so release must be a harmless no-op."""
        base = _run._C07_RUN_DEPTH[0]

        def _fail(_token):
            raise KeyboardInterrupt("injected before acquisition")

        with _Patch(_run, "_begin_run_depth", _fail):
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, nodes=1)
        self._assert_clean(base)

    def test_an_interrupt_after_acquisition_is_released_by_the_finally(self):
        """A REAL signal in the acquire -> try-body gap still cleans up."""
        base = _run._C07_RUN_DEPTH[0]
        real = _run._begin_run_depth

        def _acquire_then_signal(token):
            token = real(token)
            # Delivered immediately (we are on the main thread), i.e.
            # between acquisition and the rest of the try body -- the
            # exact window the old increment-before-try shape leaked.
            os.kill(os.getpid(), signal.SIGINT)
            return token

        with _DefaultSigint(), _Patch(_run, "_begin_run_depth",
                                      _acquire_then_signal):
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, nodes=1)
        self._assert_clean(base)

    def test_a_signal_during_release_does_not_skip_the_teardown(self):
        """Release and teardown are ONE non-abandonable region."""
        base = _run._C07_RUN_DEPTH[0]
        state = {"fired": False, "torn_down": False}
        real_release = _run._RunDepthToken.release
        real_teardown = _run._teardown_reactor

        def _release_then_signal(token):
            held = real_release(token)
            if not state["fired"]:
                state["fired"] = True
                os.kill(os.getpid(), signal.SIGINT)
            return held

        def _teardown(*args, **kwargs):
            state["torn_down"] = True
            return real_teardown(*args, **kwargs)

        with _DefaultSigint(), \
                _Patch(_run._RunDepthToken, "release",
                       _release_then_signal), \
                _Patch(_run, "_teardown_reactor", _teardown):
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(_up, self.path, workers=2, nodes=1)
        self.assertTrue(state["fired"],
                        "the release-boundary signal was never delivered")
        self.assertTrue(
            state["torn_down"],
            "the signal after the depth release SKIPPED the teardown: "
            "the depth and the cleanup were not one region")
        self._assert_clean(base)

    def test_a_signal_during_an_unwinding_release_keeps_the_run_error(self):
        """A second signal while already failing must not replace the error."""
        base = _run._C07_RUN_DEPTH[0]
        state = {"fired": False, "torn_down": False}
        real_release = _run._RunDepthToken.release
        real_teardown = _run._teardown_reactor

        def _boom(_batch):
            raise RuntimeError("synthetic worker failure")

        def _release_then_signal(token):
            held = real_release(token)
            if not state["fired"]:
                state["fired"] = True
                os.kill(os.getpid(), signal.SIGINT)
            return held

        def _teardown(*args, **kwargs):
            state["torn_down"] = True
            return real_teardown(*args, **kwargs)

        with _DefaultSigint(), \
                _Patch(_run._RunDepthToken, "release",
                       _release_then_signal), \
                _Patch(_run, "_teardown_reactor", _teardown):
            with self.assertRaises(RuntimeError) as cm:
                forkrun.map(_boom, self.path, workers=2, nodes=1,
                            on_error="fail-fast")
        self.assertNotIsInstance(
            cm.exception, KeyboardInterrupt,
            "the deferred signal replaced the run's own error")
        self.assertTrue(state["fired"])
        self.assertTrue(state["torn_down"])
        self._assert_clean(base)


class TestRunDepthArchitecture(unittest.TestCase):
    """Every executor shape routes through the ONE token.

    The SSoT invariant is structural: a new executor that grows its own
    increment/decrement, or a checkpoint call that forgets the deferral,
    must fail here rather than only at runtime under a signal race.
    """

    RUN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "forkrun", "run.py")
    CHILDREG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "forkrun", "_childreg.py")

    def _tree(self, path):
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    @staticmethod
    def _call_name(node):
        if isinstance(node, ast.Expr):
            node = node.value
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def _parent_map(self, tree):
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        return parents

    def test_every_executor_uses_the_one_token(self):
        tree = self._tree(self.RUN)
        found = 0
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(fn)
                     if self._call_name(n) == "_begin_run_depth"]
            if not calls:
                continue
            found += 1
            # The token is constructed before the outer try that
            # acquires it, so the finally can always name it.
            token_assign = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_depth"
                        for t in n.targets)
                and self._call_name(n.value) == "_RunDepthToken"]
            self.assertTrue(token_assign,
                            "%s has no `_depth = _RunDepthToken()`" % fn.name)
            outer = None
            for try_node in [n for n in ast.walk(fn)
                             if isinstance(n, ast.Try)]:
                if any(self._call_name(s) == "_begin_run_depth"
                       for s in try_node.body):
                    outer = try_node
                    break
            self.assertIsNotNone(
                outer, "%s acquires the depth outside a try" % fn.name)
            self.assertEqual(
                "_begin_run_depth", self._call_name(outer.body[0]),
                "%s does not acquire the depth as the FIRST protected "
                "statement; an interrupt can land between acquisition "
                "and the finally that releases it" % fn.name)
            self.assertLess(
                token_assign[0].lineno, outer.lineno,
                "%s constructs the token after the try" % fn.name)
            protected = [
                n for n in ast.walk(outer)
                if isinstance(n, ast.With)
                and self._call_name(n.items[0].context_expr)
                == "_defer_interrupts_for_cleanup"]
            self.assertTrue(
                protected,
                "%s's finally has no _defer_interrupts_for_cleanup "
                "region" % fn.name)
            region = protected[0]
            first = region.body[0]
            self.assertEqual(
                "release", self._call_name(first),
                "%s releases the depth outside the protected cleanup "
                "region (or not first)" % fn.name)
            self.assertEqual(
                "_depth", getattr(first.value.func.value, "id", None)
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Call) else None,
                "%s releases a different token than the one it acquired"
                % fn.name)
            self.assertTrue(
                any(self._call_name(n) == "_teardown_reactor"
                    for n in ast.walk(region)),
                "%s calls the teardown outside the protected cleanup "
                "region" % fn.name)
        self.assertEqual(
            found, 6,
            "expected six executor shapes with a run depth (UMA reactor, "
            "UMA stream reactor, UMA ingest reactor, UMA ingest stream "
            "reactor, NUMA blocking, NUMA stream); found %d -- a new "
            "executor shape was added without the token" % found)

    def test_no_direct_depth_mutation_outside_the_token(self):
        tree = self._tree(self.RUN)
        token_cls = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and \
                    node.name == "_RunDepthToken":
                token_cls = node
        self.assertIsNotNone(token_cls, "_RunDepthToken is gone")
        lo, hi = token_cls.lineno, max(
            getattr(n, "lineno", 0) for n in ast.walk(token_cls))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AugAssign, ast.Assign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            for target in targets:
                if not (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "_C07_RUN_DEPTH"):
                    continue
                if not (lo <= node.lineno <= hi):
                    offenders.append("%s:%d" % (self.RUN, node.lineno))
        self.assertEqual(
            [], offenders,
            "direct depth accounting outside _RunDepthToken: %s"
            % ", ".join(offenders))

    def test_every_checkpoint_call_is_uninterruptible(self):
        tree = self._tree(self.RUN)
        direct = []
        wrapped = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = self._call_name(node)
            if name == "checkpoint_on_abort":
                direct.append("%s:%d" % (self.RUN, node.lineno))
            elif (name == "_uninterruptible" and node.args
                  and isinstance(node.args[0], ast.Name)
                  and node.args[0].id == "checkpoint_on_abort"):
                wrapped += 1
        self.assertGreaterEqual(
            wrapped, 4,
            "expected the four abort-choreography call sites, found %d"
            % wrapped)
        self.assertEqual(
            [], direct,
            "checkpoint choreography called WITHOUT _uninterruptible(): %s"
            % ", ".join(direct))

    def test_every_teardown_is_inside_a_deferral(self):
        tree = self._tree(self.RUN)
        parents = self._parent_map(tree)
        offenders = []
        for node in ast.walk(tree):
            if self._call_name(node) != "_teardown_reactor":
                continue
            cur = node
            protected = False
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.With) and \
                        self._call_name(cur.items[0].context_expr) == \
                        "_defer_interrupts_for_cleanup":
                    protected = True
                    break
            if not protected:
                offenders.append("%s:%d" % (self.RUN, node.lineno))
        self.assertEqual(
            [], offenders,
            "teardown outside _defer_interrupts_for_cleanup(): %s"
            % ", ".join(offenders))

    def test_fork_child_protects_and_adopts_inside_the_window(self):
        tree = self._tree(self.CHILDREG)
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == "fork_child":
                fn = node
        self.assertIsNotNone(fn, "fork_child is gone")
        forks = [n for n in ast.walk(fn)
                 if self._call_name(n) == "fork"]
        self.assertEqual(1, len(forks), "fork_child must fork exactly once")
        parents = self._parent_map(tree)
        cur = forks[0]
        protected = False
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, ast.With) and \
                    self._call_name(cur.items[0].context_expr) == \
                    "defer_interrupts":
                protected = True
                break
        self.assertTrue(
            protected,
            "fork_child forks OUTSIDE defer_interrupts(): an interrupt "
            "between os.fork() and adoption orphans the child")
        self.assertTrue(
            any(self._call_name(n) == "after_fork_child"
                for n in ast.walk(fn)),
            "fork_child never resets the child's deferral state")


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


class TestForkIsACriticalSection(ChildLifecycleMixin, unittest.TestCase):
    """The fork itself must not be interruptible.

    CPython's os.fork() calls logging._prepareFork() in the PARENT
    before the syscall and logging._afterFork() after it: the
    logging module's lock is held across the fork. An ASYNCHRONOUS
    EXCEPTION in that window -- a SIGINT arriving mid-fork -- leaves
    that lock held FOREVER, and every later fork in the process then
    blocks inside _prepareFork.

    That is not theoretical. It is the hang this work order was
    pointed at: a process stuck in logging._prepareFork while the
    main thread waited for the engine session lock the forking
    thread held -- a deadlock that wedges the whole suite, in the
    suite's own release check.

    So the fork is a critical section, and the deferral that protects
    the cleanup protects the fork too.
    """

    def test_the_fork_window_arms_the_process_wide_recorder(self):
        """The KERNEL disposition is the recorder for the whole window.

        The contract changed from "SIGINT is blocked in the forking
        thread's mask" to "the process-wide kernel disposition is a
        recorder". The mask was the defect: it is per thread, so a
        process-directed SIGINT delivered to any sibling still raised
        KeyboardInterrupt on the main thread inside the window.

        Assert the kernel handler CHANGES for the window and is restored
        exactly afterwards -- read with sigaction(), not getsignal():
        the latter only reports CPython's Python-level table, which the
        deferral deliberately leaves untouched so a host's callable is
        preserved across an off-main section.
        """
        from forkrun import _childreg

        real_fork = os.fork
        before = _sigint_action_addr()
        seen = {}

        def _probe():
            seen["during"] = _sigint_action_addr()
            return real_fork()

        pid = None
        with _Patch(os, "fork", _probe):
            pid = _childreg.fork_child("test")
        try:
            if pid == 0:
                os._exit(0)
            self.assertIsNotNone(before)
            self.assertNotEqual(
                before, seen.get("during"),
                "the fork window ran WITHOUT the process-wide recorder: "
                "an async exception between os.fork() and the logging "
                "lock release leaves that lock held forever, and a "
                "sibling thread makes a pthread mask useless")
            self.assertEqual(
                before, _sigint_action_addr(),
                "the host's SIGINT disposition was not restored exactly "
                "after the fork window")
        finally:
            if pid:
                try:
                    os.waitpid(pid, 0)
                except (ChildProcessError, OSError):
                    pass

    def test_a_sigint_in_the_fork_window_still_adopts_the_child(self):
        """The adoption is INSIDE the protected fork window.

        A child that is forked but not yet recorded is INVISIBLE: the
        teardown cannot kill it, cannot reap it, and when it exits it
        is a zombie. So the adoption is not "the next statement after
        the fork" -- it is part of the same critical section, and the
        deferral is what keeps the interrupt out of the gap.

        Measured: with the adoption outside the window, a SIGINT
        arriving there left an unreaped `python3` child behind --
        exactly the leak the improved helper reported.
        """
        from forkrun import _childreg

        real_fork = os.fork
        holder = {}

        def _fork_then_sigint():
            pid = real_fork()
            holder["pid"] = pid
            if pid > 0:
                # A REAL SIGINT, delivered in the fork's window.
                os.kill(os.getpid(), signal.SIGINT)
            return pid

        _childreg.reset()
        try:
            with _DefaultSigint(), _Patch(os, "fork", _fork_then_sigint):
                try:
                    _childreg.fork_child("test")
                except KeyboardInterrupt:
                    # The deferred interrupt is delivered as the fork
                    # returns. That is the point: it is deferred, not
                    # swallowed.
                    pass
            pid = holder.get("pid")
            if pid == 0:
                os._exit(0)       # the child
            try:
                self.assertIn(
                    pid, _childreg.pending(),
                    "the child was forked but NOT adopted: an interrupt "
                    "in the fork window must not orphan it")
            finally:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except (ChildProcessError, OSError):
                    pass
        finally:
            _childreg.reset()

    def test_the_child_starts_with_the_host_disposition(self):
        """The child must behave as if the deferral had not happened.

        A child that kept the recorder would defer SIGINT forever and
        never honour the operator's interrupt. The child proves three
        things: its depth is 0 (the copied scope did not survive), its
        KERNEL handler is the host's again, and a real SIGINT raises
        KeyboardInterrupt in the child.
        """
        from forkrun import _childreg
        from forkrun._signals import deferral_state as _state

        r, w = os.pipe()
        with _DefaultSigint():
            host = _sigint_action_addr()
            pid = _childreg.fork_child("test")
        if pid == 0:
            ok = False
            try:
                os.close(r)
                st = _state()
                addr = _sigint_action_addr()
                got = False
                try:
                    os.kill(os.getpid(), signal.SIGINT)
                    # CPython runs the handler on the main thread at the
                    # next bytecode boundary.
                    for _ in range(10000):
                        pass
                except KeyboardInterrupt:
                    got = True
                ok = (st["depth"] == 0 and addr == host and got)
            except BaseException:
                ok = False
            try:
                os.write(w, b"1" if ok else b"0")
            except OSError:
                pass
            os._exit(0)
        os.close(w)
        try:
            data = os.read(r, 1)
        finally:
            os.close(r)
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass
        self.assertEqual(
            b"1", data,
            "the child did not start clean: it kept the recorder, or "
            "kept the parent's depth, or could not take a SIGINT")

    def test_a_pending_parent_signal_survives_the_fork_and_is_not_replayed(self):
        """The parent's deferral belongs to the PARENT, not the child.

        A SIGINT recorded before the fork is pending in the parent's
        recorder. The child must start with depth 0, the host's kernel
        disposition, and NO replay of the parent's signal -- otherwise
        it would interrupt a worker whose parent never received that
        interrupt. The parent's signal must still be delivered through
        the parent's restored disposition after the section.
        """
        from forkrun import _childreg, _signals

        r, w = os.pipe()
        parent_raised = False
        data = b""
        with _DefaultSigint():
            host = _sigint_action_addr()
            try:
                with _signals.defer_interrupts():
                    # Recorded by the PARENT's process-wide recorder
                    # before any fork. 120ms is far longer than signal
                    # delivery needs; this is not a timing race.
                    sigint_from_thread(0.02)
                    time.sleep(0.12)
                    pid = _childreg.fork_child("test")
                    if pid == 0:
                        ok = False
                        try:
                            os.close(r)
                            # Any inherited/replayed delivery would have
                            # fired before this sleep finished.
                            time.sleep(0.10)
                            st = _signals.deferral_state()
                            ok = (st["depth"] == 0
                                  and _sigint_action_addr() == host)
                        except BaseException:
                            ok = False
                        try:
                            os.write(w, b"1" if ok else b"0")
                        except OSError:
                            pass
                        os._exit(0)
                    os.close(w)
                    data = os.read(r, 1)
                    os.close(r)
                    try:
                        os.waitpid(pid, 0)
                    except (ChildProcessError, OSError):
                        pass
                    _childreg.reconcile()
            except KeyboardInterrupt:
                parent_raised = True
        self.assertEqual(
            b"1", data,
            "the child did not start clean: it kept the parent's depth, "
            "kept the recorder, or replayed the parent's pending SIGINT")
        self.assertTrue(
            parent_raised,
            "the parent's deferred SIGINT was lost across the fork: it "
            "must still be delivered through the parent's disposition")


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


class TestEveryForkIsProtected(unittest.TestCase):
    """Every production fork must go through the canonical primitive.

    The invariant is not "the package calls fork_child somewhere" --
    it is that NO fork bypasses it. A bypass is a child that is
    neither adopted nor protected from an interrupt landing in the
    fork window, which is exactly the defect this work order found.

    The census is over the AST, not a grep: it looks for
    `os.fork()`, an ALIAS of it (`from os import fork`, `import os as
    _os` then `_os.fork()`), and the alternate process-creation paths
    (posix_spawn, subprocess, multiprocessing) -- and it classifies
    each one rather than assuming.
    """

    PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "forkrun")
    ALIASES = ("fork",)

    def _package_files(self):
        out = []
        for name in sorted(os.listdir(self.PKG)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(self.PKG, name)
            with open(path, encoding="utf-8") as fh:
                out.append((name, fh.read()))
        return out

    def test_no_module_forks_outside_the_primitive(self):
        """The only os.fork() in the package is inside fork_child()."""
        offenders = []
        for name, src in self._package_files():
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                is_fork = False
                if isinstance(func, ast.Attribute) and func.attr == "fork":
                    is_fork = True
                elif isinstance(func, ast.Name) and func.id in self.ALIASES:
                    # `fork(...)` -- only a bypass if it is NOT
                    # os.fork reached through an alias import.
                    is_fork = self._is_os_alias(src, func.id)
                if not is_fork:
                    continue
                if name == "_childreg.py":
                    continue        # the primitive itself
                offenders.append("%s:%d: a direct fork() bypasses "
                                 "forkrun._childreg.fork_child()" % (
                                     name, node.lineno))
        self.assertEqual([], offenders,
                         "these forks bypass the canonical primitive:\n  %s"
                         % "\n  ".join(offenders))

    def _is_os_alias(self, src, name):
        """Is `name` an alias of os.fork (not a local function)?"""
        for line in src.split("\n"):
            if line.startswith("from os import") and name in line:
                return True
            if line.startswith("import os as %s" % name):
                return True
        return False

    def test_no_module_uses_an_alternate_process_creation_path(self):
        """posix_spawn does not fork, so it is a legitimate exception --
        but only if it is the documented one.

        The cleanroom launcher uses os.posix_spawn (no fork, no child
        to adopt). Any OTHER use of an alternate creation path would
        create a child this package does not own.
        """
        # The documented exceptions, each with its reason:
        #   _childreg.py / fork  -- the primitive itself
        #   run.py / posix_spawn -- the cleanroom launcher: posix_spawn
        #                           does not fork, so there is no child
        #                           to adopt and no fork window to
        #                           protect
        allowed = {("run.py", "posix_spawn"), ("_childreg.py", "fork")}
        offenders = []
        for name, src in self._package_files():
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr not in ("posix_spawn", "Popen", "fork",
                                     "vfork", "clone"):
                    continue
                if (name, func.attr) in allowed:
                    continue
                offenders.append("%s:%d: %s() creates a process this "
                                 "package does not own" % (
                                     name, node.lineno, func.attr))
        self.assertEqual([], offenders,
                         "alternate process creation outside the "
                         "documented exception:\n  %s"
                         % "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
