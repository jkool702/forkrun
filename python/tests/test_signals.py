"""D-PORT1: opt-in parent signal policy (P4).

Default installs nothing (library non-invasive); "checkpoint"
installs HUP/TERM (+USR1 under FORKRUN_PREEMPT_MODE=1) for one
run, aborts + checkpoints via existing choreography, raises the
taxonomy error, and restores prior handlers (restoration is a
release-blocking invariant).
"""

import contextlib
import io
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


# The C recorder's test-only knobs (python/forkrun/_shim.c). A test that
# sets one must restore the previous value, or a later test inherits it.
_ENV_KNOBS = (
    "FORKRUN_SIGINT_HANDLER_DELAY_US",
    "FORKRUN_SIGINT_DRAIN_BUDGET_US",
    "FORKRUN_SIGINT_FAULT_RESTORE",
    "FORKRUN_SIGINT_FAULT_STALE",
    "FORKRUN_SIGINT_FAULT_LATE",
)


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
        # Patch the MODULE ATTRIBUTE _signals.os, not _signals.os.kill:
        # `_signals.os` IS the os module, so patching `.kill` on it also
        # patches the sender's os.kill and the SIGINT is never sent --
        # the test then fails for the opposite of the reason it names.
        class _NoKill:
            def __getattr__(self, name):
                return getattr(os, name)

            def kill(self, *a, **k):
                raise boom

        with mock.patch.object(_signals, "os", _NoKill()):
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
class TestRecorderConcurrency(unittest.TestCase):
    """The C recorder's boundary protocol, exercised deterministically.

    The recorder is a RUNNING FUNCTION, not a queued message: a handler
    the kernel has already entered can still be executing when the
    section closes. The test-only delay hook puts an invocation provably
    in flight at that moment; the fault hooks cover the two states that
    cannot be provoked through the public API (a failed restore and a
    parked stale signal).
    """

    def setUp(self):
        self._old_int = _signal.getsignal(_signal.SIGINT)
        self._old_failure = _signals._LAST_DEFERRAL_FAILURE
        self._old_env = {k: os.environ.get(k) for k in _ENV_KNOBS}
        self._siblings = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for _th, stop in self._siblings:
            stop.set()
        for th, _stop in self._siblings:
            th.join(5)
        try:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, set())
        except (OSError, ValueError):
            pass
        try:
            _signals._shim().fr_py_sigint_defer_cancel()
        except Exception:
            pass
        try:
            _signal.signal(_signal.SIGINT, self._old_int)
        except (OSError, ValueError):
            pass
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _signals._LAST_DEFERRAL_FAILURE = self._old_failure
        depth = _signals.deferral_state()["depth"]
        if depth:
            # Never poison the rest of the suite with a test's leak;
            # the assertion below still fails this test.
            _signals._STATE.depth = 0
            _signals._STATE.generation += 1
        self.assertEqual(depth, 0,
                         "a recorder test left a deferral section open")

    def _env(self, **kw):
        for key, value in kw.items():
            os.environ[key] = str(value)

    def _busy_sibling(self):
        """An eligible receiver, created UNMASKED (before _mask_main)."""
        ready = threading.Event()
        stop = threading.Event()

        def run():
            ready.set()
            while not stop.is_set():
                time.sleep(0.002)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        self.assertTrue(ready.wait(5), "the sibling never started")
        self._siblings.append((th, stop))
        return th, stop

    def _mask_main(self):
        old = _signal.pthread_sigmask(
            _signal.SIG_BLOCK, {_signal.SIGINT})
        self.addCleanup(
            _signal.pthread_sigmask, _signal.SIG_SETMASK, old)
        return old

    def _send(self):
        # Created while the main thread is masked: the timer inherits
        # that mask and cannot receive, so the busy sibling is the
        # eligible receiver.
        timer = threading.Timer(
            0.0, os.kill, (os.getpid(), _signal.SIGINT))
        timer.daemon = True
        timer.start()
        return timer

    def test_a_kernel_pending_sigint_is_claimed_at_the_boundary(self):
        """A signal still pending in the KERNEL must be claimed, not lost.

        The recorder can only see a signal the kernel has delivered to a
        thread. With SIGINT blocked on every thread, it stays in the
        process pending set: no recorder invocation exists to drain, so
        an in-flight drain alone cannot see it. Restoring the host
        disposition in that state hands it to CPython's handler and it
        surfaces at an arbitrary later bytecode -- the exact CI failure.
        ``end()`` must claim it with ``sigtimedwait()`` and report SEEN.
        """
        calls = []

        def handler(signo, frame):
            calls.append((signo, threading.get_ident()))

        _signal.signal(_signal.SIGINT, handler)
        old = _signal.pthread_sigmask(
            _signal.SIG_BLOCK, {_signal.SIGINT})
        try:
            with defer_interrupts():
                os.kill(os.getpid(), _signal.SIGINT)
                self.assertIn(
                    _signal.SIGINT, _signal.sigpending(),
                    "the test premise failed: another thread was eligible, "
                    "so the signal was delivered to the recorder instead "
                    "of staying kernel-pending")
                self.assertEqual(
                    calls, [], "delivered inside the protected section")
            self.assertEqual(
                calls, [(_signal.SIGINT, threading.get_ident())],
                "the kernel-pending SIGINT was not claimed and delivered "
                "synchronously on the closing thread")
            self.assertNotIn(
                _signal.SIGINT, _signal.sigpending(),
                "the signal is still pending after the boundary")
        finally:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, old)

    def test_a_late_recorder_invocation_is_forwarded_not_parked(self):
        """A handler that misses the FINAL boundary must not park forever.

        The kernel can dequeue a signal and be preempted before the
        recorder's first instruction; no userspace state observes that
        window. The fault hook closes the generation while an invocation
        is provably in flight, so the invocation's CAS must fail, it must
        observe IDLE, and it must forward the signal through the restored
        host disposition. Parking it for a begin() that never comes would
        silently swallow the interrupt.
        """
        self._env(FORKRUN_SIGINT_HANDLER_DELAY_US=400000,
                  FORKRUN_SIGINT_FAULT_LATE=1)
        calls = []

        def handler(signo, frame):
            calls.append((signo, threading.get_ident()))

        _signal.signal(_signal.SIGINT, handler)
        self._busy_sibling()
        self._mask_main()
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self._send()
        time.sleep(0.10)          # the recorder is now inside the delay
        self.assertEqual(
            lib.fr_py_sigint_defer_end(), _signals._RC_OK,
            "the fault hook was supposed to close the generation while "
            "the recorder was still in flight")
        self.assertEqual(_signals.deferral_state()["depth"], 0)
        self.assertTrue(
            wait_until(lambda: calls, 2.0),
            "the late recorder invocation parked the SIGINT for a "
            "begin() that never came: the signal was silently lost")
        self.assertEqual(len(calls), 1)
        # The forwarded signal must not be replayed by the next section.
        with defer_interrupts():
            pass
        self.assertEqual(
            len(calls), 1,
            "the forwarded signal was recorded into the next generation")

    def test_a_recorded_signal_is_reported_once_and_cleared(self):
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        sigint_from_thread(0.02)
        time.sleep(0.15)
        self.assertEqual(
            lib.fr_py_sigint_defer_end(), _signals._RC_SEEN,
            "the recorder did not report the signal it saw")
        self.assertEqual(
            lib.fr_py_sigint_defer_begin(), _signals._RC_OK,
            "a signal from the previous generation was replayed as a "
            "stale handoff")
        self.assertEqual(lib.fr_py_sigint_defer_end(), _signals._RC_OK)

    def test_an_inflight_recorder_hands_off_and_end_waits(self):
        self._env(FORKRUN_SIGINT_HANDLER_DELAY_US=400000,
                  FORKRUN_SIGINT_DRAIN_BUDGET_US=2000000)
        calls = []
        _signal.signal(_signal.SIGINT,
                       lambda s, f: calls.append(threading.get_ident()))
        self._busy_sibling()
        self._mask_main()
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self._send()
        time.sleep(0.10)
        started = time.monotonic()
        rc = lib.fr_py_sigint_defer_end()
        elapsed = time.monotonic() - started
        self.assertEqual(
            rc, _signals._RC_HANDOFF,
            "an invocation that was in flight at the boundary did not "
            "park a handoff (rc=%r)" % (rc,))
        self.assertGreaterEqual(
            elapsed, 0.15,
            "end() did not wait for the in-flight invocation (%.3fs)"
            % elapsed)
        self.assertLess(
            elapsed, 1.0,
            "end() waited for the whole handler delay instead of the "
            "drain budget (%.3fs)" % elapsed)
        self.assertEqual(
            calls, [],
            "the in-flight invocation re-raised through the kernel "
            "instead of handing off: a Python-level handler would then "
            "run asynchronously on the main thread")
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self.assertEqual(lib.fr_py_sigint_defer_end(), _signals._RC_OK)

    def test_the_handoff_is_delivered_synchronously_on_the_closing_thread(
            self):
        self._env(FORKRUN_SIGINT_HANDLER_DELAY_US=400000,
                  FORKRUN_SIGINT_DRAIN_BUDGET_US=2000000)
        calls = []

        def handler(signo, frame):
            calls.append((signo, threading.get_ident()))

        _signal.signal(_signal.SIGINT, handler)
        self._busy_sibling()
        self._mask_main()
        started = time.monotonic()
        with defer_interrupts():
            self._send()
            time.sleep(0.10)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(
            elapsed, 0.15,
            "the section did not wait for the in-flight invocation")
        self.assertEqual(
            calls, [(_signal.SIGINT, threading.get_ident())],
            "the handoff was not delivered exactly once, synchronously, "
            "on the thread that closed the section")
        self.assertEqual(_signals.deferral_state()["depth"], 0)

    def test_a_drain_timeout_fails_closed_and_can_be_reset(self):
        self._env(FORKRUN_SIGINT_HANDLER_DELAY_US=600000,
                  FORKRUN_SIGINT_DRAIN_BUDGET_US=100000)
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        self._busy_sibling()
        self._mask_main()
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self._send()
        time.sleep(0.15)
        started = time.monotonic()
        rc = lib.fr_py_sigint_defer_end()
        elapsed = time.monotonic() - started
        self.assertEqual(rc, -4, "a drain timeout was not reported")
        self.assertLess(
            elapsed, 0.45,
            "end() waited for the whole handler delay instead of its "
            "budget (%.3fs)" % elapsed)
        self.assertEqual(
            lib.fr_py_sigint_defer_begin(), -5,
            "a drain timeout did not make later sections fail closed")
        # Let the delayed invocation finish and park, then reset the
        # test-only broken state through the child-side reset.
        time.sleep(0.55)
        self.assertGreaterEqual(lib.fr_py_sigint_defer_cancel(), 0)
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self.assertEqual(lib.fr_py_sigint_defer_end(), _signals._RC_OK)

    def test_a_restore_failure_is_fail_closed_and_leaves_the_recorder_visible(
            self):
        self._env(FORKRUN_SIGINT_FAULT_RESTORE=1)
        calls = []
        _signal.signal(_signal.SIGINT, lambda s, f: calls.append(s))
        host = _signal.getsignal(_signal.SIGINT)
        host_addr = sigint_action_addr()
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self.assertEqual(
            lib.fr_py_sigint_defer_end(), -3,
            "a failed restore was not reported")
        self.assertNotEqual(
            sigint_action_addr(), host_addr,
            "a failed restore pretended the recorder was gone")
        self.assertEqual(
            lib.fr_py_sigint_defer_begin(), -5,
            "a failed restore did not make later sections fail closed")
        self.assertIs(_signal.getsignal(_signal.SIGINT), host)
        self.assertGreaterEqual(lib.fr_py_sigint_defer_cancel(), 0)
        self.assertEqual(
            sigint_action_addr(), host_addr,
            "cancel() did not restore the host disposition")
        os.environ.pop("FORKRUN_SIGINT_FAULT_RESTORE", None)
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        self.assertEqual(lib.fr_py_sigint_defer_end(), _signals._RC_OK)

    def test_the_python_layer_raises_and_refuses_later_sections(self):
        self._env(FORKRUN_SIGINT_FAULT_RESTORE=1)
        _signal.signal(_signal.SIGINT, lambda s, f: None)
        with self.assertRaises(_signals.DeferralError) as ctx:
            with defer_interrupts():
                pass
        self.assertIn("could not restore", str(ctx.exception))
        with self.assertRaises(_signals.DeferralError) as ctx2:
            with defer_interrupts():
                self.fail("a broken deferral state opened a section")
        self.assertIn("rc=-5", str(ctx2.exception))
        _signals._shim().fr_py_sigint_defer_cancel()
        os.environ.pop("FORKRUN_SIGINT_FAULT_RESTORE", None)
        with defer_interrupts():
            self.assertEqual(_signals.deferral_state()["depth"], 1)
        self.assertEqual(_signals.deferral_state()["depth"], 0)

    def test_an_unwinding_failure_keeps_the_run_error_and_is_recorded(self):
        self._env(FORKRUN_SIGINT_FAULT_RESTORE=1)
        _signal.signal(_signal.SIGINT, lambda s, f: None)
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            with self.assertRaises(ValueError):
                with defer_interrupts():
                    raise ValueError("the run's own error")
        failure = _signals.deferral_failure()
        self.assertIsInstance(failure, _signals.DeferralError)
        self.assertIn("could not restore", str(failure))
        self.assertIn("forkrun [FATAL]", captured.getvalue())
        _signals._shim().fr_py_sigint_defer_cancel()
        os.environ.pop("FORKRUN_SIGINT_FAULT_RESTORE", None)
        with defer_interrupts():
            pass

    def test_a_host_disposition_change_mid_section_wins(self):
        calls = []

        def host_a(signo, frame):
            calls.append("a")

        def host_b(signo, frame):
            calls.append("b")

        _signal.signal(_signal.SIGINT, host_a)
        lib = _signals._shim()
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        self.assertEqual(
            lib.fr_py_sigint_defer_end(), _signals._RC_OK,
            "the newer host disposition was reported as a deferred signal")
        self.assertIs(_signal.getsignal(_signal.SIGINT), _signal.SIG_IGN)
        self.assertEqual(
            sigint_action_addr(), 1,
            "the recorder clobbered the host's SIG_IGN")

        _signal.signal(_signal.SIGINT, host_a)
        self.assertEqual(lib.fr_py_sigint_defer_begin(), _signals._RC_OK)
        _signal.signal(_signal.SIGINT, host_b)
        self.assertEqual(lib.fr_py_sigint_defer_end(), _signals._RC_OK)
        self.assertIs(_signal.getsignal(_signal.SIGINT), host_b)
        os.kill(os.getpid(), _signal.SIGINT)
        self.assertTrue(
            wait_until(lambda: calls == ["b"], 2.0),
            "the newer host handler was not the live one")

    def test_multiple_signals_coalesce_to_one_delivery(self):
        calls = []
        _signal.signal(_signal.SIGINT, lambda s, f: calls.append(s))
        with defer_interrupts():
            for _ in range(5):
                os.kill(os.getpid(), _signal.SIGINT)
                time.sleep(0.01)
            self.assertEqual(calls, [], "delivered inside the section")
        self.assertEqual(
            calls, [_signal.SIGINT],
            "one interval with several SIGINTs must deliver at least "
            "once; the boolean contract is exactly one")
        with defer_interrupts():
            pass
        self.assertEqual(
            calls, [_signal.SIGINT],
            "a signal from the previous generation reappeared")

    def test_boundary_race_never_loses_or_duplicates_a_signal(self):
        self._env(FORKRUN_SIGINT_HANDLER_DELAY_US=5000)
        calls = []
        in_section = [False]

        def handler(signo, frame):
            calls.append((signo, in_section[0]))

        _signal.signal(_signal.SIGINT, handler)
        self._busy_sibling()
        self._mask_main()
        n = 60
        for i in range(n):
            with defer_interrupts():
                in_section[0] = True
                self._send()
                if i % 4:
                    time.sleep(0.002)
                in_section[0] = False
            # A recorder invocation that was already running when this
            # section closed forwards the signal through the restored
            # host disposition (late, never lost); it does NOT park for
            # the next begin(). Wait for that forwarding. The invariant
            # is exactly one delivery per send, never inside a section.
            self.assertTrue(
                wait_until(lambda: len(calls) > i, 1.0),
                "signal %d was LOST (calls=%d)" % (i, len(calls)))
            self.assertEqual(
                len(calls), i + 1,
                "signal %d was delivered %d times"
                % (i, len(calls) - i))
            self.assertFalse(
                calls[-1][1],
                "signal %d was delivered INSIDE a protected section" % i)

    def test_a_stale_handoff_is_delivered_before_the_section_opens(self):
        self._env(FORKRUN_SIGINT_FAULT_STALE=1)
        seen = []

        def handler(signo, frame):
            seen.append((signo, _signals.deferral_state()["depth"]))
            os.environ.pop("FORKRUN_SIGINT_FAULT_STALE", None)

        _signal.signal(_signal.SIGINT, handler)
        with defer_interrupts():
            self.assertEqual(
                seen, [(_signal.SIGINT, 0)],
                "the parked signal was not delivered BEFORE the section "
                "opened")
            self.assertEqual(_signals.deferral_state()["depth"], 1)
        self.assertEqual(_signals.deferral_state()["depth"], 0)
        with defer_interrupts():
            pass
        self.assertEqual(seen, [(_signal.SIGINT, 0)],
                         "the parked signal was replayed")

    def test_a_stale_handoff_that_raises_prevents_the_section(self):
        self._env(FORKRUN_SIGINT_FAULT_STALE=1)
        calls = []

        def handler(signo, frame):
            calls.append(signo)
            os.environ.pop("FORKRUN_SIGINT_FAULT_STALE", None)
            raise KeyboardInterrupt("stale")

        _signal.signal(_signal.SIGINT, handler)
        with self.assertRaises(KeyboardInterrupt):
            with defer_interrupts():
                self.fail("the section opened despite a delivered stale "
                          "signal")
        self.assertEqual(calls, [_signal.SIGINT])
        self.assertEqual(
            _signals.deferral_state()["depth"], 0,
            "the failed arm left the section open")
        with defer_interrupts():
            pass


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
