"""D-PORT1: opt-in parent signal policy (P4).

Default installs nothing (library non-invasive); "checkpoint"
installs HUP/TERM (+USR1 under FORKRUN_PREEMPT_MODE=1) for one
run, aborts + checkpoints via existing choreography, raises the
taxonomy error, and restores prior handlers (restoration is a
release-blocking invariant).
"""

import os
import signal as _signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun import _signals  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._signals import (defer_interrupts,  # noqa: E402
                              deferral_state,
                              validate_signal_policy)
from forkrun.exceptions import (ForkrunPreempted,  # noqa: E402
                                ForkrunTerminated)

from _helpers import (ChildLifecycleMixin, DefaultSigint,  # noqa: E402
                      assert_no_zombies, sigint_action_addr,
                      sigint_from_thread, wait_until, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _slow(batch):
    time.sleep(0.15)
    return bytes(batch.data)


def _slow_up(batch):
    time.sleep(0.15)
    return bytes(batch.data).upper()


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=3000):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n)
    return path


def _kill_me_later(sig, delay):
    t = threading.Timer(delay, lambda: os.kill(os.getpid(), sig))
    t.daemon = True
    t.start()
    return t


class TestPolicyValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_signal_policy(None), "default")
        self.assertEqual(validate_signal_policy("default"), "default")
        self.assertEqual(validate_signal_policy("checkpoint"), "checkpoint")

    def test_invalid_fail_closed(self):
        for bad in ("check", "", "CHECKPOINT", 1, True):
            with self.assertRaises(ValueError):
                validate_signal_policy(bad)

    def test_wrappers_reject_invalid(self):
        with self.assertRaises(ValueError):
            forkrun.run("p:m", source="f", signal_policy="bogus")
        with self.assertRaises(ValueError):
            forkrun.map("p:m", source="f", signal_policy="bogus")
        with self.assertRaises(ValueError):
            forkrun.stream("p:m", source="f", signal_policy="bogus")


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestProcessWideDeferral(unittest.TestCase):
    """SIGINT deferral is PROCESS-WIDE, not a per-thread mask.

    THE DEFECT. ``signal.pthread_sigmask`` is per thread, but CPython
    raises the Python-level KeyboardInterrupt on the MAIN thread no
    matter which thread received the signal. With any sibling thread
    eligible, a process-directed SIGINT was handled by the sibling and
    raised in the main thread INSIDE the "protected" section -- so the
    old mask protected nothing. ``signal.signal`` cannot fix it either:
    it is main-thread-only. The kernel disposition is the only
    process-scoped control point.

    These tests deliver REAL signals (``os.kill`` from a non-main
    thread, which leaves the receiving thread to the kernel). The main
    thread blocks SIGINT in several of them, so the signal MUST be
    delivered to a sibling -- exactly the shape that defeated the mask.
    """

    def setUp(self):
        self._old = _signal.getsignal(_signal.SIGINT)
        self.addCleanup(self._restore)

    def _restore(self):
        _signal.signal(_signal.SIGINT, self._old)
        # never leave the test process masked, even on failure
        try:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, set())
        except (OSError, ValueError):
            pass

    def _busy_sibling(self):
        """A genuinely eligible sibling thread (created UNMASKED)."""
        ready = threading.Event()
        stop = threading.Event()

        def run():
            ready.set()
            while not stop.is_set():
                time.sleep(0.005)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        self.assertTrue(ready.wait(5), "the sibling thread never started")
        return th, stop

    def test_without_deferral_a_sibling_delivery_reaches_the_main_thread(self):
        """Control: the harness REALLY interrupts the main thread.

        Without this the deferred-delivery test could pass because the
        signal was never sent, or because the main thread was the only
        eligible receiver. Here the main thread is masked, the only
        eligible receiver is the sibling, and CPython still raises
        KeyboardInterrupt in the main thread -- the bug in one frame.
        """
        th, stop = self._busy_sibling()
        oldmask = _signal.pthread_sigmask(
            _signal.SIG_BLOCK, {_signal.SIGINT})
        try:
            with DefaultSigint():
                sigint_from_thread(0.05)
                with self.assertRaises(KeyboardInterrupt):
                    time.sleep(0.6)
        finally:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, oldmask)
            stop.set()
            th.join(5)

    def test_a_sibling_delivery_is_deferred_and_lands_after_the_section(self):
        """The real case: main masked, sibling eligible, signal deferred.

        The main thread cannot receive the signal at the kernel level,
        so if deferral were per-thread this would raise immediately.
        Instead the body completes, the recorder is restored, and the
        interrupt is delivered once at the outermost exit.
        """
        th, stop = self._busy_sibling()
        oldmask = _signal.pthread_sigmask(
            _signal.SIG_BLOCK, {_signal.SIGINT})
        body_complete = False
        raised = False
        try:
            with DefaultSigint():
                host = sigint_action_addr()
                try:
                    with defer_interrupts():
                        # The kernel disposition is the process-wide
                        # recorder for the whole section.
                        self.assertNotEqual(
                            sigint_action_addr(), host,
                            "the process-wide recorder was not installed")
                        sigint_from_thread(0.05)
                        time.sleep(0.20)
                        body_complete = True
                        self.assertEqual(
                            deferral_state()["depth"], 1,
                            "the section is not open")
                    # Delivery is synchronous: the host callable runs
                    # before the section's exit returns. The loop keeps
                    # the assertion valid for a host whose handler itself
                    # defers, and would fail a lost delivery.
                    for _ in range(100):
                        if raised:
                            break
                        time.sleep(0.005)
                except KeyboardInterrupt:
                    raised = True
                self.assertEqual(
                    sigint_action_addr(), host,
                    "the host SIGINT disposition was not restored")
        finally:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, oldmask)
            stop.set()
            th.join(5)
        self.assertTrue(
            body_complete,
            "the protected body did not complete: the signal interrupted "
            "the section despite the process-wide recorder")
        self.assertTrue(
            raised,
            "the deferred SIGINT was LOST: it was never delivered after "
            "the section")
        self.assertEqual(deferral_state()["depth"], 0)

    def test_python_level_delivery_is_synchronous_not_a_kernel_reraises(self):
        """The deferred interrupt must not go back through the kernel.

        A kernel re-raise with the main thread masked is handled by an
        eligible sibling; CPython then sets the main thread's trip flag
        and raises KeyboardInterrupt at an arbitrary later bytecode --
        including inside the NEXT protected section, or inside
        ``_RUN_LOCK.__exit__`` before it clears the session marker.
        Measured: one such late raise left the run lock marked live and
        every later run in the process was refused as nested.

        A Python-level disposition is therefore called directly, on the
        thread that closes the section, after the kernel disposition has
        been restored. ``SIG_DFL`` still re-raises (tested separately in
        a subprocess), because the default action is the kernel's.
        """
        calls = []
        _signal.signal(_signal.SIGINT,
                       lambda s, f: calls.append(threading.get_ident()))
        self.addCleanup(_signal.signal, _signal.SIGINT, self._old)
        boom = AssertionError(
            "a Python-level disposition was re-raised through the kernel")
        with mock.patch.object(_signals.os, "kill", side_effect=boom):
            with defer_interrupts():
                sigint_from_thread(0.02)
                time.sleep(0.15)
        self.assertEqual(
            calls, [threading.get_ident()],
            "the host callable did not run synchronously on the thread "
            "that closed the section")

    def test_restore_precedes_delivery_for_a_host_callable(self):
        """The host callable sees the RESTORED kernel disposition.

        ``_disarm`` restores first and reports second on purpose: a
        signal racing the swap is then handled either by the recorder
        or by the host, never discarded. The callable can observe the
        order, which makes it a test rather than a comment.
        """
        calls = []
        seen = {}

        def handler(signo, frame):
            seen["signo"] = signo
            seen["addr"] = sigint_action_addr()
            calls.append(signo)

        _signal.signal(_signal.SIGINT, handler)
        # The kernel address is CPython's one trampoline for every
        # Python-level handler, so measure it AFTER installing ours.
        host = sigint_action_addr()
        with defer_interrupts():
            sigint_from_thread(0.02)
            time.sleep(0.15)
            self.assertEqual(
                calls, [],
                "the host callable ran INSIDE the protected section")
        self.assertTrue(wait_until(lambda: calls, 2.0),
                        "the deferred SIGINT never reached the host callable")
        self.assertEqual(calls, [_signal.SIGINT])
        self.assertEqual(seen["signo"], _signal.SIGINT)
        self.assertEqual(
            seen["addr"], host,
            "the callable observed the recorder still installed: restore "
            "must precede delivery")
        self.assertIs(_signal.getsignal(_signal.SIGINT), handler)

    def test_sig_ign_is_preserved_and_the_signal_is_dropped(self):
        """A host that IGNORES SIGINT keeps ignoring it -- no surprise KI."""
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        self.addCleanup(_signal.signal, _signal.SIGINT, _signal.SIG_IGN)
        with defer_interrupts():
            sigint_from_thread(0.02)
            time.sleep(0.15)
        # A delivery through SIG_IGN is a no-op by definition.
        time.sleep(0.05)
        self.assertIs(_signal.getsignal(_signal.SIGINT), _signal.SIG_IGN)
        # The recorder must not have turned it into an exception.
        self.assertEqual(deferral_state()["depth"], 0)

    def test_sig_dfl_is_restored_and_delivered_in_a_subprocess(self):
        """SIG_DFL must terminate: run it where that is assertable.

        The runner cannot be allowed to die, so the whole contract runs
        in a child: the section completes, the checkpoint marker is
        written, and the deferred signal then kills the process with
        the default action.
        """
        marker = tempfile.mktemp(prefix="forkrun-sigint-")
        self.addCleanup(lambda: os.path.exists(marker) and os.unlink(marker))
        pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        script = r"""
import os, signal, sys, time
sys.path.insert(0, sys.argv[1])
from forkrun._signals import defer_interrupts
signal.signal(signal.SIGINT, signal.SIG_DFL)
marker = sys.argv[2]
with defer_interrupts():
    os.kill(os.getpid(), signal.SIGINT)
    time.sleep(0.05)
    with open(marker, "w") as fh:
        fh.write("body")
with open(marker, "a") as fh:
    fh.write("-after")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, pkg, marker],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        self.assertEqual(
            proc.returncode, -_signal.SIGINT,
            "SIG_DFL was not delivered (rc=%r, stderr=%r)"
            % (proc.returncode, proc.stderr[-400:]))
        with open(marker) as fh:
            self.assertEqual(
                fh.read(), "body",
                "the process executed PAST the section: the deferred "
                "signal was not delivered")

    def test_an_exception_in_flight_keeps_the_run_error(self):
        """A deferred SIGINT must not replace the exception already raised."""
        calls = []
        _signal.signal(_signal.SIGINT,
                       lambda s, f: calls.append(s))
        self.addCleanup(_signal.signal, _signal.SIGINT, self._old)
        with self.assertRaises(ValueError):
            with defer_interrupts():
                sigint_from_thread(0.02)
                time.sleep(0.15)
                raise ValueError("the run's own error")
        time.sleep(0.05)
        self.assertEqual(
            calls, [],
            "the deferred signal was delivered while an exception was "
            "unwinding, replacing the run's own error")
        self.assertEqual(deferral_state()["depth"], 0)

    def test_nested_sections_deliver_once_at_the_outermost_exit(self):
        calls = []
        _signal.signal(_signal.SIGINT, lambda s, f: calls.append(s))
        self.addCleanup(_signal.signal, _signal.SIGINT, self._old)
        with defer_interrupts():
            with defer_interrupts():
                sigint_from_thread(0.02)
                time.sleep(0.15)
                self.assertEqual(calls, [],
                                 "delivered before the outermost exit")
                self.assertEqual(deferral_state()["depth"], 2)
            self.assertEqual(calls, [],
                             "the inner exit delivered early")
            self.assertEqual(deferral_state()["depth"], 1)
        self.assertTrue(wait_until(lambda: calls, 2.0),
                        "the outermost exit never delivered")
        self.assertEqual(calls, [_signal.SIGINT],
                         "one signal must produce exactly one delivery")

    def test_cross_thread_nesting_restores_on_the_last_exit(self):
        """Permitted overlap: main enters first, sibling exits last.

        The old ownership model checked the EXITING thread's identity
        after decrementing to zero, so this order raised and left the
        recorder installed. Depth is process-wide now; the last exit
        restores and delivers, whichever thread it is.
        """
        calls = []
        _signal.signal(_signal.SIGINT, lambda s, f: calls.append(s))
        host = sigint_action_addr()
        main_scope = defer_interrupts()
        main_scope.__enter__()
        entered = threading.Event()
        proceed = threading.Event()
        errors = []

        def sibling():
            try:
                with defer_interrupts():
                    entered.set()
                    if not proceed.wait(5):
                        errors.append("sibling was never released")
            except BaseException as exc:  # pragma: no cover - diagnostic
                errors.append(repr(exc))

        th = threading.Thread(target=sibling, daemon=True)
        try:
            th.start()
            self.assertTrue(entered.wait(5), "the sibling never entered")
            sigint_from_thread(0.02)
            time.sleep(0.15)
            self.assertEqual(calls, [], "delivered while both scopes open")
            main_scope.__exit__(None, None, None)
            self.assertEqual(deferral_state()["depth"], 1,
                             "the first exit disarmed the shared section")
            self.assertNotEqual(
                sigint_action_addr(), host,
                "the recorder was restored while a scope was still open")
            self.assertEqual(calls, [], "the first exit delivered early")
        finally:
            proceed.set()
            th.join(5)
            if deferral_state()["depth"]:
                main_scope.__exit__(None, None, None)
        self.assertEqual(errors, [])
        self.assertTrue(wait_until(lambda: calls, 2.0),
                        "the last exit never delivered")
        self.assertEqual(calls, [_signal.SIGINT])
        self.assertEqual(deferral_state()["depth"], 0)
        self.assertEqual(sigint_action_addr(), host)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestDefaultPolicy(ChildLifecycleMixin, unittest.TestCase):
    def test_installs_nothing(self):
        before = {s: _signal.getsignal(s) for s in
                  (_signal.SIGHUP, _signal.SIGTERM, _signal.SIGUSR1)}
        path = _make_input(500)
        try:
            forkrun.map(_up, path, workers=2, nodes=1)
            after = {s: _signal.getsignal(s) for s in
                     (_signal.SIGHUP, _signal.SIGTERM, _signal.SIGUSR1)}
            self.assertEqual(before, after)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_host_hup_handler_fires_untouched(self):
        # Default policy must not capture the host's signals: a
        # host HUP handler fires mid-run and the run completes.
        fired = []
        old = _signal.getsignal(_signal.SIGHUP)
        _signal.signal(_signal.SIGHUP, lambda s, f: fired.append(s))
        path = _make_input()
        try:
            _kill_me_later(_signal.SIGHUP, 0.5)
            out = forkrun.map(_slow, path, workers=2, nodes=1,
                              lines=100)
            self.assertEqual(fired, [_signal.SIGHUP])
            self.assertEqual(_signal.getsignal(_signal.SIGHUP).
                             __class__, type(lambda s, f: None))
            self.assertTrue(out)
            assert_no_zombies(self)
        finally:
            _signal.signal(_signal.SIGHUP, old)
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCheckpointPolicy(ChildLifecycleMixin, unittest.TestCase):
    def test_hup_aborts_checkpoints_raises(self):
        path = _make_input()
        fd, ckpt = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        os.unlink(ckpt)  # published by the abort, must not pre-exist
        try:
            _kill_me_later(_signal.SIGHUP, 0.7)
            with self.assertRaises(ForkrunTerminated) as ctx:
                forkrun.map(_slow, path, workers=2, nodes=1,
                            order="index", orchestrator=True,
                            lines=100, checkpoint_file=ckpt,
                            signal_policy="checkpoint")
            self.assertEqual(ctx.exception.signo, _signal.SIGHUP)
            self.assertEqual(ctx.exception.bash_code, 143)
            self.assertTrue(os.path.exists(ckpt),
                            "HUP abort must publish the checkpoint")
            assert_no_zombies(self)
        finally:
            if os.path.exists(ckpt):
                os.unlink(ckpt)
            os.unlink(path)

    def test_hup_checkpoint_resumes_byte_identical(self):
        path = _make_input()
        fd, ckpt = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        os.unlink(ckpt)
        try:
            _kill_me_later(_signal.SIGHUP, 0.7)
            with self.assertRaises(ForkrunTerminated):
                forkrun.map(_slow_up, path, workers=2, nodes=1,
                            order="index", orchestrator=True,
                            lines=100, checkpoint_file=ckpt,
                            signal_policy="checkpoint")
            res = forkrun.map(_slow_up, path, workers=4, nodes=1,
                              order="index", orchestrator=True,
                              resume=ckpt)
            expect = forkrun.map(_slow_up, path, workers=4, nodes=1,
                                 order="index", orchestrator=True)
            self.assertEqual(b"".join(res), b"".join(expect))
            assert_no_zombies(self)
        finally:
            for p in (ckpt, ckpt + ".coll", path):
                if os.path.exists(p):
                    os.unlink(p)

    def test_term_restores_host_handler(self):
        # Restoration invariant: a pre-existing host handler is
        # the same object after the run and still fires.
        fired = []
        old = _signal.getsignal(_signal.SIGTERM)
        def host(sig, frame):
            fired.append(sig)
        _signal.signal(_signal.SIGTERM, host)
        path = _make_input(500)
        try:
            forkrun.map(_up, path, workers=2, nodes=1,
                        signal_policy="checkpoint")
            self.assertIs(_signal.getsignal(_signal.SIGTERM), host)
            os.kill(os.getpid(), _signal.SIGTERM)
            self.assertEqual(fired, [_signal.SIGTERM])
            assert_no_zombies(self)
        finally:
            _signal.signal(_signal.SIGTERM, old)
            os.unlink(path)

    def test_usr1_ignored_without_preempt(self):
        # No PREEMPT_MODE: USR1 is NOT captured even under the
        # checkpoint policy (mirrors the Bash conditional trap).
        os.environ.pop("FORKRUN_PREEMPT_MODE", None)
        fired = []
        old = _signal.getsignal(_signal.SIGUSR1)
        _signal.signal(_signal.SIGUSR1, lambda s, f: fired.append(s))
        path = _make_input()
        try:
            _kill_me_later(_signal.SIGUSR1, 0.5)
            out = forkrun.map(_slow, path, workers=2, nodes=1,
                              lines=100, signal_policy="checkpoint")
            self.assertEqual(fired, [_signal.SIGUSR1])
            self.assertTrue(out)
            assert_no_zombies(self)
        finally:
            _signal.signal(_signal.SIGUSR1, old)
            os.unlink(path)

    def test_usr1_preempts_with_preempt_mode(self):
        os.environ["FORKRUN_PREEMPT_MODE"] = "1"
        path = _make_input()
        try:
            _kill_me_later(_signal.SIGUSR1, 0.5)
            with self.assertRaises(ForkrunPreempted) as ctx:
                forkrun.map(_slow, path, workers=2, nodes=1,
                            lines=100, signal_policy="checkpoint")
            self.assertEqual(ctx.exception.signo, _signal.SIGUSR1)
            self.assertEqual(ctx.exception.bash_code, 138)
            assert_no_zombies(self)
        finally:
            os.environ.pop("FORKRUN_PREEMPT_MODE", None)
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
