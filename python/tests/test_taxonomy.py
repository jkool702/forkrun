"""D-PORT3: cause-fidelity exception taxonomy (P3).

Bash numeric exit codes (130/143/138/3) map to distinct Python
exceptions carrying signo + bash_code — cause fidelity, not number
fidelity. Engine faults with no signal cause stay RuntimeError.
"""

import os
import signal as _signal
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._reactor import _death_cause  # noqa: E402
from forkrun.exceptions import (BASH_CODE_MAP, ForkrunInterrupted,  # noqa: E402
                                ForkrunPoisonSkip, ForkrunPreempted,
                                ForkrunSignalError, ForkrunTerminated,
                                ForkrunWorkerFailure)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestTaxonomyShape(unittest.TestCase):
    def test_hierarchy_and_codes(self):
        self.assertTrue(issubclass(ForkrunInterrupted,
                                   ForkrunSignalError))
        self.assertTrue(issubclass(ForkrunInterrupted, KeyboardInterrupt))
        self.assertTrue(issubclass(ForkrunInterrupted, RuntimeError))
        self.assertTrue(issubclass(ForkrunPreempted, ForkrunSignalError))
        self.assertTrue(issubclass(ForkrunTerminated, ForkrunSignalError))
        self.assertTrue(issubclass(ForkrunPoisonSkip, RuntimeError))
        self.assertNotIsInstance(ForkrunPoisonSkip("x", count=1),
                                 ForkrunSignalError)
        self.assertEqual(ForkrunInterrupted.bash_code, 130)
        self.assertEqual(ForkrunPreempted.bash_code, 138)
        self.assertEqual(ForkrunTerminated.bash_code, 143)
        self.assertEqual(ForkrunPoisonSkip.bash_code, 3)
        self.assertEqual(BASH_CODE_MAP[130], ForkrunInterrupted)
        self.assertEqual(BASH_CODE_MAP[138], ForkrunPreempted)
        self.assertEqual(BASH_CODE_MAP[143], ForkrunTerminated)
        self.assertEqual(BASH_CODE_MAP[3], ForkrunPoisonSkip)

    def test_signo_and_count_attrs(self):
        exc = ForkrunTerminated("t", signo=15)
        self.assertEqual(exc.signo, 15)
        self.assertEqual(exc.bash_code, 143)
        self.assertIsNone(ForkrunSignalError("b").signo)
        perr = ForkrunPoisonSkip("p", count=7)
        self.assertEqual(perr.count, 7)

    def test_death_cause_mapping(self):
        # W-FLAKEFIX self-isolation: this test self-kills children and
        # therefore needs default dispositions for the catchable signals
        # it uses. A backgrounded launcher (nohup SigIgn=0x7) bequeaths
        # ignored HUP/INT/QUIT, which Python honors by NOT installing its
        # handlers — the kill then becomes exit-42 and WIFSIGNALED fails
        # (M1a family; see dev/supervisor/FLAKEFIX_DIAGNOSIS.md). Pin DFL
        # for exactly the signals under test; restore afterwards.
        _fl_pins = (_signal.SIGTERM, _signal.SIGINT, _signal.SIGSEGV)
        _fl_saved = {s: _signal.getsignal(s) for s in _fl_pins}
        self.addCleanup(lambda: [_signal.signal(s, _fl_saved[s])
                                 for s in _fl_pins])
        for s in _fl_pins:
            _signal.signal(s, _signal.SIG_DFL)
        # Exited statuses pass through with no signal.
        code, sig = _death_cause(0)
        self.assertEqual((code, sig), (0, None))
        code, sig = _death_cause(os.waitstatus_to_exitcode(0)
                                 if False else 3 << 8)
        self.assertEqual((code, sig), (3, None))
        # Signaled deaths ride 128+signo (Bash 130/143 reachable).
        for sig, want in ((15, 143), (2, 130), (9, 137), (11, 139)):
            # Build a real signaled status via a killed child.
            pid = os.fork()
            if pid == 0:
                os.kill(os.getpid(), sig)
                os._exit(42)  # unreachable when signaled
            _, st = os.waitpid(pid, 0)
            self.assertTrue(os.WIFSIGNALED(st))
            code, got = _death_cause(st)
            self.assertEqual((code, got), (want, sig))


def _always_fail(batch):
    raise ValueError("boom")


def _segv(batch):
    import ctypes

    ctypes.string_at(0)
    return b"unreachable"


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStrictPoison(unittest.TestCase):
    def test_strict_raises_with_count(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            with self.assertRaises(ForkrunPoisonSkip) as ctx:
                forkrun.map(_always_fail, path, workers=1, nodes=1,
                            lines=500, strict_poison=True)
            # 1000 lines / lines=500 = 2 batches, both poisoned.
            self.assertEqual(ctx.exception.count, 2)
            self.assertEqual(ctx.exception.bash_code, 3)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_default_stays_warn_and_partial(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            out = forkrun.map(_always_fail, path, workers=1, nodes=1,
                              lines=500)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_strict_stream_raises_at_exhaustion(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            seen = []
            with self.assertRaises(ForkrunPoisonSkip):
                for blob in forkrun.stream(_always_fail, path,
                                           workers=1, nodes=1,
                                           lines=500, strict_poison=True):
                    seen.append(blob)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCrashStaysRuntimeError(unittest.TestCase):
    def test_segfault_is_plain_runtime_error(self):
        # Engine faults with no signal *cause contract* (claim race,
        # worker crash) stay RuntimeError (Bash exit 1) — taxonomy
        # only claims signal causes + strict poison.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            with self.assertRaises(RuntimeError) as ctx:
                forkrun.map(_segv, path, workers=2, nodes=1)
            self.assertNotIsInstance(ctx.exception, ForkrunSignalError)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_worker_failure_carries_typed_signo(self):
        """W-REL6-3.5: ForkrunWorkerFailure is a RuntimeError with a
        typed .signo (x5, deterministic -- genuine waitpid statuses
        from real SIGKILLed children, no engine needed)."""
        import sys as _sys
        run_mod = _sys.modules["forkrun.run"]
        for _ in range(5):
            pid = os.fork()
            if pid == 0:
                os.kill(os.getpid(), _signal.SIGKILL)
                os._exit(42)  # unreachable
            _, status = os.waitpid(pid, 0)
            self.assertTrue(os.WIFSIGNALED(status))
            with self.assertRaises(ForkrunWorkerFailure) as ctx:
                run_mod._raise_worker_failure(
                    [pid], 1, "retry", statuses=[(pid, status)])
            self.assertIsInstance(ctx.exception, RuntimeError)
            self.assertNotIsInstance(ctx.exception, ForkrunSignalError)
            self.assertEqual(ctx.exception.signo, _signal.SIGKILL)
            # Plain-exit deaths carry None, not AttributeError.
            with self.assertRaises(ForkrunWorkerFailure) as ctx2:
                run_mod._raise_worker_failure(
                    [pid], 1, "retry", statuses=[(pid, 0)])
            self.assertIsNone(ctx2.exception.signo)


def _slow(batch):
    time.sleep(0.05)
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestParentInterrupt(unittest.TestCase):
    def test_sigint_becomes_forkrun_interrupted(self):
        # Parent-side SIGINT mid-run translates to
        # ForkrunInterrupted (still a KeyboardInterrupt).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 4000)
            old = _signal.getsignal(_signal.SIGINT)
            _signal.signal(_signal.SIGINT, _signal.default_int_handler)
            timer = threading.Timer(0.5, lambda: os.kill(os.getpid(),
                                                         _signal.SIGINT))
            try:
                timer.start()
                with self.assertRaises(ForkrunInterrupted) as ctx:
                    forkrun.map(_slow, path, workers=2, nodes=1)
            finally:
                timer.cancel()
                _signal.signal(_signal.SIGINT, old)
            self.assertEqual(ctx.exception.signo, _signal.SIGINT)
            self.assertEqual(ctx.exception.bash_code, 130)
            self.assertIsInstance(ctx.exception, KeyboardInterrupt)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
