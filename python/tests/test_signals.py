"""D-PORT1: opt-in parent signal policy (P4).

Default installs nothing (library non-invasive); "checkpoint"
installs HUP/TERM (+USR1 under FORKRUN_PREEMPT_MODE=1) for one
run, aborts + checkpoints via existing choreography, raises the
taxonomy error, and restores prior handlers (restoration is a
release-blocking invariant).
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
from forkrun._signals import validate_signal_policy  # noqa: E402
from forkrun.exceptions import (ForkrunPreempted,  # noqa: E402
                                ForkrunTerminated)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

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
class TestDefaultPolicy(unittest.TestCase):
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
class TestCheckpointPolicy(unittest.TestCase):
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
