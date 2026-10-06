"""W-REL5-B bite lock-ins (Python behavioral correctness).

Bite-then-green: each test FAILS on the pre-fix tree (typo'd kwarg
silently runs / bare taxonomy / blocking poll / unbounded join /
signo-less failure) and PASSES post-fix. Deterministic items ×5,
timing-sensitive (B3/B5) ×10 — see tambura runs in the report.
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
from forkrun.exceptions import ForkrunInterrupted  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data)


def _slow(batch):
    time.sleep(0.05)
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB1UnknownKwarg(unittest.TestCase):
    """B1: map/stream/sweep reject unknown kwargs; sink= rejected."""

    def _path(self, n=50):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False)
        path = fh.name
        fh.close()
        write_lines(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def test_map_rejects_typo_kwarg(self):
        path = self._path()
        with self.assertRaises(TypeError):
            forkrun.map(_up, path, wokers=2, nodes=1)
        assert_no_zombies(self)

    def test_stream_rejects_typo_kwarg(self):
        path = self._path()
        with self.assertRaises(TypeError):
            forkrun.stream(_up, path, wokers=2, nodes=1)
        assert_no_zombies(self)

    def test_sweep_rejects_typo_kwarg(self):
        with self.assertRaises(TypeError):
            forkrun.sweep(_up, args=[["a", "b"]], wokers=2)
        assert_no_zombies(self)

    def test_map_rejects_sink(self):
        path = self._path()
        with self.assertRaises(ValueError):
            forkrun.map(_up, path, sink=print, nodes=1)
        assert_no_zombies(self)

    def test_stream_rejects_sink(self):
        path = self._path()
        with self.assertRaises(ValueError):
            forkrun.stream(_up, path, sink=print, nodes=1)
        assert_no_zombies(self)

    def test_valid_kwargs_still_run(self):
        path = self._path()
        out = forkrun.map(_up, path, workers=1, nodes=1,
                          order="index")
        self.assertTrue(len(b"".join(out)) > 0)
        out = list(forkrun.stream(_up, path, workers=1, nodes=1,
                                  order="index"))
        self.assertTrue(len(b"".join(out)) > 0)
        out = forkrun.sweep(lambda b: b"ok", args=[["a", "b"]],
                            workers=1)
        self.assertEqual(len(out), 2)
        assert_no_zombies(self)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB2StreamTaxonomy(unittest.TestCase):
    """B2: SIGINT mid-stream raises ForkrunInterrupted (uniform with
    the six blocking executors), not bare KeyboardInterrupt."""

    def _path(self, n=4000):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False)
        path = fh.name
        fh.close()
        write_lines(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def _check_sigint(self, **kw):
        # 5000 lines, and the SIGINT is armed on PROGRESS, not on a fixed
        # wall clock. Two independent reasons, both learned the hard way:
        #
        # 1. A fixed timer races a bimodal workload. When the pre-flight
        #    wins its race against the first forked worker, CASE A picks a
        #    very wide L (measured 9 batches for 5000 lines -- ~555 lines
        #    each); when it loses, CASE B resumes from sim_L and the same
        #    input becomes ~79 narrow batches. So the fast mode finished in
        #    0.472 s and a 0.5 s timer arrived 28 ms too late, with caught
        #    None. Every fixed-timer sizing I tried was wrong for one mode.
        #
        # 2. Arming only after the first blob means the interrupt cannot
        #    land before the stream is live, and cannot land after it is
        #    done -- the two ways a wall-clock timer fails. What remains is
        #    guaranteed work in flight: at n=5000 even the widest batching
        #    observed yields ~9 batches, so ~8 remain after the first.
        #    0.05 s is short against _slow's 0.05 s per batch.
        path = self._path(n=5000)
        old = _signal.getsignal(_signal.SIGINT)
        _signal.signal(_signal.SIGINT, _signal.default_int_handler)
        # Deliver SIGINT from the kernel via setitimer, NOT a
        # threading.Timer. forkrun forks ~21 times, so a timer thread makes
        # the parent multi-threaded at exactly the moment it forks -- the
        # hazard forkrun warns about in its own RuntimeWarning. That race is
        # what made this test flaky (~1 in 3) once worker fork timing moved:
        # the SIGINT could land inside the fork sequence and be swallowed,
        # so `caught` came back None. A SIGALRM handler runs in the MAIN
        # thread and raises nothing itself, so the parent stays
        # single-threaded and the only signal in play is the SIGINT under
        # test. setitimer is also more precise than Timer, which matters when
        # the thing being timed is a half-second window.
        def _fire_sigint(_signum, _frame):
            os.kill(os.getpid(), _signal.SIGINT)

        old_alrm = _signal.signal(_signal.SIGALRM, _fire_sigint)
        caught = None
        _nb = 0
        _t0 = time.monotonic()
        try:
            try:
                for _blob in forkrun.stream(_slow, path, workers=2,
                                            nodes=1, **kw):
                    _nb += 1
                    if _nb == 1:
                        # Stream is demonstrably live; now start the clock.
                        _signal.setitimer(_signal.ITIMER_REAL, 0.05)
            except BaseException as exc:  # noqa: BLE001
                # Catch KI itself: pre-fix the bare
                # KeyboardInterrupt lands here (bite); post-fix the
                # translated ForkrunInterrupted does.
                caught = exc
        finally:
            _elapsed = time.monotonic() - _t0
            _signal.setitimer(_signal.ITIMER_REAL, 0)
            _signal.signal(_signal.SIGALRM, old_alrm)
            _signal.signal(_signal.SIGINT, old)
        self.assertIsInstance(
            caught, ForkrunInterrupted,
            "stream SIGINT taxonomy: got %r after %d batch(s) in %.3fs "
            "(SIGINT scheduled at 0.500s) kw=%r"
            % (caught, _nb, _elapsed, kw))
        self.assertEqual(caught.signo, _signal.SIGINT)
        self.assertEqual(caught.bash_code, 130)
        self.assertIsInstance(caught, KeyboardInterrupt)
        assert_no_zombies(self)

    def test_sigint_stream_reactor(self):
        self._check_sigint()

    def test_sigint_stream_plain(self):
        self._check_sigint(orchestrator=False)

    def test_sigint_ingest_stream_reactor(self):
        self._check_sigint(streaming=True)

    def test_sigint_ingest_stream_plain(self):
        self._check_sigint(streaming=True, orchestrator=False)


def _segv(batch):
    import ctypes

    ctypes.string_at(0)
    return b"unreachable"


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB8SignalFidelity(unittest.TestCase):
    """B8: worker-failure raises carry .signo (SIGSEGV ⇒ 11) while
    staying plain RuntimeError (Bash exit-1 contract)."""

    def _path(self, n=200):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False)
        path = fh.name
        fh.close()
        write_lines(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def _check_segv_signo(self, **kw):
        from forkrun.exceptions import ForkrunSignalError

        path = self._path()
        with self.assertRaises(RuntimeError) as ctx:
            forkrun.map(_segv, path, workers=2, nodes=1, **kw)
        exc = ctx.exception
        self.assertNotIsInstance(exc, ForkrunSignalError)
        self.assertEqual(exc.signo, _signal.SIGSEGV,
                         "worker SIGSEGV must ride along as .signo")
        assert_no_zombies(self)

    def test_segv_plain_path_carries_signo(self):
        self._check_segv_signo(orchestrator=False)

    def test_segv_reactor_path_carries_signo(self):
        self._check_segv_signo()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB5ReactorPollNonblocking(unittest.TestCase):
    """B5: reactor_poll_once never blocks on an unreaped child
    (death-pipe EOF precedes os._exit — WNOHANG + bounded spin,
    then defer to the reap sweep)."""

    def test_poll_defers_unreaped_child(self):
        from forkrun._reactor import (ReactorState, WorkerSlot,
                                      reactor_poll_once)

        state = ReactorState(2)
        death_r, death_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(death_r)
            except OSError:
                pass
            try:
                os.close(death_w)  # EOF now; exit comes 3s later
            except OSError:
                pass
            time.sleep(3)
            os._exit(0)
        # Parent drops its write copy (like spawn_worker): the
        # pipe is at EOF while the child is still alive.
        try:
            os.close(death_w)
        except OSError:
            pass
        slot = WorkerSlot(0, 0, pid, death_r, -1)
        state.workers[0] = slot
        # Settle: the child has closed its write copy (EOF
        # present) but sleeps 3s before exiting (descheduled
        # child between pipe EOF and os._exit).
        time.sleep(0.5)
        try:
            t0 = time.monotonic()
            try:
                reactor_poll_once(state)
            except RuntimeError:
                # Pre-fix classify path (blocking reap, then
                # engine-less _classify raises): the latency
                # below is the real assertion.
                pass
            dt = time.monotonic() - t0
        finally:
            # Reap the child (exited by now or shortly after).
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass
            try:
                os.close(death_r)
            except OSError:
                pass
        # Bounded: spin only, not the 3s child sleep.
        self.assertLess(dt, 2.0)
        # Deferred, slot untouched (still alive, pipe open) for
        # the reap sweep — never a blocking reap inside the poll.
        self.assertTrue(state.workers[0].alive)
        assert_no_zombies(self)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB4BoundedHelperJoin(unittest.TestCase):
    """B4: helper joins are bounded (SIGKILL on expiry + alarm
    naming the helper) instead of unbounded os.waitpid(pid, 0)."""

    def test_wedged_helper_reaped_with_alarm(self):
        import sys as _sys

        from _helpers import redirect_fd, restore_fd

        _run_mod = _sys.modules["forkrun.run"]
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        cap = tempfile.mktemp(suffix=".err")
        self.addCleanup(lambda: os.path.exists(cap)
                        and os.unlink(cap))
        saved = redirect_fd(2, cap)
        try:
            t0 = time.monotonic()
            st = _run_mod._join_helper_bounded(
                pid, "test-helper", timeout=0.5)
            dt = time.monotonic() - t0
        finally:
            restore_fd(2, saved)
        # Bounded: ~timeout, not 30s.
        self.assertLess(dt, 5.0)
        # Reaped via SIGKILL on expiry.
        self.assertTrue(st is not None and os.WIFSIGNALED(st)
                        and os.WTERMSIG(st) == 9)
        with open(cap, "rb") as fh:
            err = fh.read()
        self.assertIn(b"test-helper", err)
        try:
            leaked = os.waitpid(pid, os.WNOHANG)
            self.fail("helper child leaked: %r" % (leaked,))
        except ChildProcessError:
            pass
        assert_no_zombies(self)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestB3IngestReactorLiveness(unittest.TestCase):
    """B3: the ingest-reactor spill observes worker deaths while the
    source is stalled (O_NONBLOCK + drain-to-EAGAIN + poll per
    quantum), instead of blocking in os.read until data arrives."""

    def _children(self):
        me = os.getpid()
        kids = set()
        try:
            names = os.listdir("/proc")
        except OSError:
            return kids
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open("/proc/%s/stat" % name) as fh:
                    parts = fh.read().rsplit(")", 1)[1].split()
                if int(parts[1]) == me:
                    kids.add(int(name))
            except (OSError, ValueError, IndexError):
                continue
        return kids

    def test_reactor_alive_during_source_stall(self):
        import forkrun._reactor as _reactor_mod

        stall_s = 8.0
        rfd, wfd = os.pipe()

        # Small first chunk: fully claimed+processed within a
        # second, so the stall-forked workers are blocked on
        # claims (at rest, no in-flight batch) when one is
        # killed mid-stall — a SIGKILL landing mid-claim is the
        # honest claim-without-publish abort (rc==4), not a
        # recovery case.
        lines1 = "".join("line %d\n" % i for i in range(200))
        lines2 = "".join("line %d\n" % i for i in range(200, 400))

        def _writer():
            try:
                os.write(wfd, lines1.encode())
                time.sleep(stall_s)
                try:
                    os.write(wfd, lines2.encode())
                except OSError:
                    pass  # run may have aborted mid-stall: reader gone
            finally:
                try:
                    os.close(wfd)
                except OSError:
                    pass

        real_wd = _reactor_mod.ReactorState.worker_died_poll
        observed = []

        def _spy_wd(self, wid):
            observed.append((wid, time.monotonic()))
            return real_wd(self, wid)

        _reactor_mod.ReactorState.worker_died_poll = _spy_wd
        wt = threading.Thread(target=_writer, daemon=True)
        wt.start()
        try:
            result = {}

            def _run():
                try:
                    result["out"] = forkrun.map(
                        _up, rfd, workers=2, nodes=1,
                        streaming=True, order="index")
                except BaseException as exc:  # noqa: BLE001
                    result["error"] = exc

            rt = threading.Thread(target=_run, daemon=True)
            rt.start()
            time.sleep(1.0)
            early_kids = self._children()
            # Mid-stall (writer quiet until t=8): the spill loop
            # must be alive — stall-forked workers present beyond
            # the two helpers (fallow + scanner).
            time.sleep(3.0)
            mid_kids = self._children()
            # Assert the INVARIANT, not the fork schedule. The property
            # under test is "the spill loop stays alive during a source
            # stall, with workers present beyond the two helpers" -- the
            # parent being blocked in read with the reactor blind is the
            # bug being guarded. The old form asserted children *increase
            # between t=1s and t=4s*, which was only true because worker
            # forking was pinned to STALL_FORK_AFTER=2.0s; fork earlier and
            # the workers are already present at t=1s, so the count is flat
            # and the test failed while the invariant held. Compare against
            # the helper count instead.
            self.assertGreater(
                len(mid_kids), 2,
                "spill loop dead during stall: only helpers present %s "
                "(reactor blind while blocked in read)"
                % (sorted(mid_kids),))
            # Kill a stall-forked worker; observation must be
            # prompt (poll quantum), not at writer release.
            # NOTE: a SIGKILL landing while pre-gate workers are
            # claim-spinning is the honest claim-without-publish
            # abort (rc==4, engine semantics — unattributable
            # batch), not a respawn: the promise under test is
            # prompt OBSERVATION/termination, not recovery.
            # Pick a WORKER, not a helper. Helpers (fallow + scanner) are
            # always forked before workers, and Linux pids are monotonic,
            # so the highest child is a worker. Selecting by "appeared
            # after t=1s" no longer works now that workers fork without an
            # artificial delay -- by t=1s they are already present, so the
            # newly-appeared set is empty.
            victim = max(mid_kids)
            t_kill = time.monotonic()
            os.kill(victim, 9)
            rt.join(30)
            t_end = time.monotonic()
            self.assertFalse(rt.is_alive(), "run hung")
            err = result.get("error")
            self.assertIsInstance(err, RuntimeError)
            self.assertIn("signal 9", str(err))
        finally:
            _reactor_mod.ReactorState.worker_died_poll = real_wd
            try:
                os.close(rfd)
            except OSError:
                pass
            wt.join(30)
        after = [t for _, t in observed if t >= t_kill]
        self.assertTrue(after, "death never observed")
        latency = min(after) - t_kill
        self.assertLess(
            latency, 4.0,
            "worker death unobserved for %.1fs during source stall "
            "(reactor blind while blocked in read)" % latency)
        # Prompt termination: the abort surfaced from the stall
        # (~0.5s), not at writer release (t=8s, i.e. ~4s later).
        self.assertLess(t_end - t_kill, 3.0)
        assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
