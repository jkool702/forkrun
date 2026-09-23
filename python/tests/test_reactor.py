"""W-PY19 reactor: event-driven worker lifecycle management (Stage 5).

The reactor (orchestrator=True) supervises workers with death pipes,
bounded respawn, trap-ACK confirmation, and the C orderer for
order="index" — the bash wrapper's ring_poll robustness in Python.
Default paths are untouched (all existing tests pass unchanged);
everything here opts in explicitly.

Contract under test:
  - Healthy path: byte-identical results vs orchestrator=False
    (map/run/stream × order none/index, splice, streaming ingest).
  - Worker segfault: respawned → other batches complete (the crashed
    batch itself is best-effort: a SIGKILL-class death runs no code,
    so no escrow deposit exists for it — documented, not silent).
  - Worker death without trap-ACK inside the 3s grace: RuntimeError.
  - Always-crashing workers: bounded by the respawn cap, then raise.
  - Poisoned batches: "P:idx:kills" reaches the parent summary.
  - C orderer: ordered output identical to Python reassembly.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


class TestOrchestratorValidation(unittest.TestCase):
    """Eager validation of the orchestrator flag (engine-free shape)."""

    def test_bad_orchestrator_rejected(self):
        for bad in ("yes", 1, 0, [], {}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                forkrun.map(_up, "f.txt", orchestrator=bad)

    def test_bad_orchestrator_run_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.run(_up, "f.txt", orchestrator="true")

    def test_bad_orchestrator_stream_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.stream(_up, "f.txt", orchestrator=1)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestReactorBasic(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_map_parity_none(self):
        path = _make_input(1500)
        try:
            simple = forkrun.map(_up, path, workers=4)
            react = forkrun.map(_up, path, workers=4,
                                orchestrator=True)
            self.assertEqual(sorted(simple), sorted(react))
        finally:
            os.unlink(path)

    def test_map_parity_index(self):
        path = _make_input(1500)
        try:
            simple = forkrun.map(_up, path, workers=4, order="index")
            react = forkrun.map(_up, path, workers=4,
                                orchestrator=True, order="index")
            self.assertEqual(simple, react)
        finally:
            os.unlink(path)

    def test_run_discard(self):
        path = _make_input(800)
        try:
            self.assertIsNone(forkrun.run(_up, path, workers=2,
                                          orchestrator=True))
        finally:
            os.unlink(path)

    def test_stream_parity(self):
        path = _make_input(1500)
        try:
            simple = sorted(forkrun.stream(_up, path, workers=4))
            react = sorted(forkrun.stream(_up, path, workers=4,
                                          orchestrator=True))
            self.assertEqual(simple, react)
        finally:
            os.unlink(path)

    def test_stream_ordered_parity(self):
        path = _make_input(1500)
        try:
            simple = list(forkrun.stream(_up, path, workers=4,
                                         order="index"))
            react = list(forkrun.stream(_up, path, workers=4,
                                        orchestrator=True,
                                        order="index"))
            self.assertEqual(simple, react)
        finally:
            os.unlink(path)

    def test_splice_parity(self):
        path = _make_input(3000)
        try:
            simple = forkrun.map(None, path, mode="splice",
                                 bytes=32768, workers=2)
            react = forkrun.map(None, path, mode="splice",
                                bytes=32768, workers=2,
                                orchestrator=True)
            self.assertEqual(sorted(simple), sorted(react))
        finally:
            os.unlink(path)

    def test_ingest_parity(self):
        # Pipe (streaming ingest, concurrent scan) vs file
        # (materialized, full scan) legitimately batch DIFFERENTLY
        # (adaptive batching over partial prefixes), so parity is
        # over LINES, not batch blobs.
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            with os.fdopen(w, "w") as fh:
                for i in range(1500):
                    fh.write("pipe %d\n" % i)
            os._exit(0)
        os.close(w)
        try:
            react = forkrun.map(_up, r, workers=2, orchestrator=True)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        path = _make_input(1500, prefix="pipe")
        try:
            simple = forkrun.map(_up, path, workers=2)
        finally:
            os.unlink(path)

        def _lines(res):
            return sorted(b"".join(res).splitlines())

        self.assertEqual(_lines(simple), _lines(react))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerRespawn(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_segfault_respawn_completes(self):
        """Segfault on batch 0: respawned, others complete (31/32)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w19segv_")
        mod_path = os.path.join(plugin_dir, "w19segv_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import ctypes\n"
                    "def payload(batch):\n"
                    "    if batch.batch_index == 0:\n"
                    "        ctypes.string_at(0)\n"
                    "    return bytes(batch.data).upper()\n")
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map("w19segv_mod:payload", path,
                                  workers=2, orchestrator=True)
            finally:
                sys.path.remove(plugin_dir)
            # The crashed batch is best-effort (no escrow possible
            # for a death that runs no code); everything else lands.
            # Results are batch-granular blobs: batch 0 (lowest
            # lines) is the lost one, the tail must be intact.
            healthy = forkrun.map(_up, path, workers=2)
            self.assertEqual(len(res), len(healthy) - 1)
            self.assertIn(b"LINE 1999\n", b"".join(res))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_once_full_recovery(self):
        """W-PY28 Tier-3: crash-once SIGKILL mid-run → parent-side
        WorkerTxn recovery (revert + escrow + respawn) → pipeline
        completes with byte-exact full results (zero loss).

        Pre-W-PY28 this ended in the 3s trap-ACK timeout → abort.
        The orphaned batch re-executes exactly once on the respawned
        worker (crash marker consumed), so unlike the poison-skip
        cases above, NOTHING is lost here.
        """
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w28killonce_")
        mod_path = os.path.join(plugin_dir, "w28killonce_mod.py")
        marker = os.path.join(plugin_dir, "crashed")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import os, signal\n"
                    "MARKER = %r\n"
                    "def payload(batch):\n"
                    "    if (batch.batch_index == 0\n"
                    "            and not os.path.exists(MARKER)):\n"
                    "        open(MARKER, 'w').write('x')\n"
                    "        os.kill(os.getpid(), signal.SIGKILL)\n"
                    "    return bytes(batch.data).upper()\n" % marker)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map("w28killonce_mod:payload", path,
                                  workers=2, orchestrator=True,
                                  order="index")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index")
            # Full recovery: every batch lands, order preserved.
            self.assertEqual(res, healthy)
            # No grace waits: one death + respawn, seconds not minutes.
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_always_sigkill_bounded(self):
        """Worker SIGKILLed on every batch: bounded, then raise."""
        path = _make_input(500)
        plugin_dir = tempfile.mkdtemp(prefix="w19kill_")
        mod_path = os.path.join(plugin_dir, "w19kill_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import os, signal\n"
                    "def payload(batch):\n"
                    "    os.kill(os.getpid(), signal.SIGKILL)\n")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                with self.assertRaises(RuntimeError):
                    forkrun.map("w19kill_mod:payload", path,
                                workers=1, orchestrator=True)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            # Bounded: trap-ACK grace (~3s) plus crash iterations —
            # never an infinite respawn loop.
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_recovers_then_caps(self):
        """W-PY28: SIGKILL (no trap can fire) → parent-side WorkerTxn
        recovery (revert + escrow + respawn, no 3s grace) → the
        kill-every-batch loop still terminates via the respawn cap.

        Replaces test_trap_ack_timeout: the trap-ACK grace period no
        longer exists, so there is no "trap-ACK" error and no lower
        time bound — recovery is synchronous per death.
        """
        path = _make_input(300)
        plugin_dir = tempfile.mkdtemp(prefix="w19tack_")
        mod_path = os.path.join(plugin_dir, "w19tack_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import os, signal\n"
                    "def payload(batch):\n"
                    "    os.kill(os.getpid(), signal.SIGKILL)\n")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                with self.assertRaisesRegex(RuntimeError,
                                            "respawn cap reached"):
                    forkrun.map("w19tack_mod:payload", path,
                                workers=1, orchestrator=True)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            # No grace waits: deaths recover synchronously, so the
            # cap trips in seconds, never minutes.
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_respawn_cap_raises(self):
        """ACK-confirmed deaths loop to the cap, then raise.

        on_error="fail-fast" makes every generation exit non-zero
        THROUGH the worker finally (trap-ACK confirmed each time),
        so the run ends via the respawn cap — bounded, never an
        infinite loop. (A bare sys.exit in the payload would NOT
        die: SystemExit is caught as a payload error and rides the
        escrow retry path without any worker death.)
        """
        path = _make_input(300)
        try:
            def _boom(batch):
                raise ValueError("nope")
            t0 = time.monotonic()
            with self.assertRaisesRegex(RuntimeError,
                                        "respawn cap reached"):
                forkrun.map(_boom, path, workers=1,
                            orchestrator=True, on_error="fail-fast")
            dt = time.monotonic() - t0
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestTrapACK(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_trap_ack_wire(self):
        """Death + ACK pair balances (fail-fast → cap error, not timeout)."""
        path = _make_input(400)
        try:
            def _boom(batch):
                raise ValueError("nope")
            with self.assertRaisesRegex(RuntimeError,
                                        "respawn cap reached"):
                forkrun.map(_boom, path, workers=2,
                            orchestrator=True, on_error="fail-fast")
        finally:
            os.unlink(path)

    def test_poison_notification_path(self):
        """Retry-always-fail poisons via escrow; run completes short."""
        path = _make_input(1000)
        try:
            def _boom(batch):
                raise ValueError("nope")
            res = forkrun.map(_boom, path, workers=2,
                              orchestrator=True, on_error="retry")
            healthy = forkrun.map(_up, path, workers=2)
            # Poisoned batches are skipped, never silently kept.
            self.assertLess(len(res), len(healthy))
        finally:
            os.unlink(path)

    def test_handle_trap_ack_bytes_unit(self):
        from forkrun._reactor import (ReactorState,
                                      handle_trap_ack_bytes)
        st = ReactorState(2)
        handle_trap_ack_bytes(st, b"P:7:3\n")
        self.assertEqual(st.poisoned_batches,
                         ["Index 7 (failed 3 times)"])
        # Malformed lines never raise (babbling writer).
        handle_trap_ack_bytes(st, b"garbage\nP:1\n")
        self.assertEqual(len(st.poisoned_batches), 1)
        # Partial line buffering across reads.
        handle_trap_ack_bytes(st, b"P:9")
        self.assertEqual(len(st.poisoned_batches), 1)
        handle_trap_ack_bytes(st, b":2\n")
        self.assertEqual(len(st.poisoned_batches), 2)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCOrderer(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_orderer_symbol(self):
        from forkrun._bindings import get, v1_available
        self.assertTrue(v1_available().get("orderer"))
        for sym in ("fr_py_orderer", "fr_py_set_order_pipe",
                    "fr_py_scan_with_spawn"):
            self.assertTrue(hasattr(get(), sym), sym)

    def test_orderer_eof_clean(self):
        """Orderer with no packets exits 0 (EOF = clean finish)."""
        from forkrun._reactor import ORDER_PIPE_SIZE, spawn_orderer
        import fcntl
        order_r, order_w = os.pipe()
        try:
            fcntl.fcntl(order_w, fcntl.F_SETPIPE_SZ, ORDER_PIPE_SIZE)
            self.assertEqual(
                fcntl.fcntl(order_w, fcntl.F_GETPIPE_SZ),
                ORDER_PIPE_SIZE)
        except OSError:
            pass
        fd, coll = tempfile.mkstemp(prefix="w19ord_")
        os.close(fd)
        try:
            coll_fd = os.open(coll, os.O_RDWR)
            try:
                pid = spawn_orderer(order_r, coll_fd)
            finally:
                os.close(coll_fd)
            os.close(order_r)
            order_r = None
            # No workers: close the write end → orderer EOF → rc 0.
            os.close(order_w)
            order_w = None
            _, status = os.waitpid(pid, 0)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            if order_r is not None:
                os.close(order_r)
            if order_w is not None:
                os.close(order_w)
            os.unlink(coll)

    def test_orderer_matches_reassembly(self):
        path = _make_input(1500)
        try:
            via_c = forkrun.map(_up, path, workers=4,
                                orchestrator=True, order="index")
            via_py = forkrun.map(_up, path, workers=4,
                                 orchestrator=False, order="index")
            self.assertEqual(via_c, via_py)
        finally:
            os.unlink(path)


class TestDynamicSpawnUnit(unittest.TestCase):
    """Spawn-request parsing/caps without forking (engine-free)."""

    def test_spawn_clamped_no_slots(self):
        from forkrun._reactor import ReactorState, handle_spawn_bytes
        st = ReactorState(0)  # no free IDs → no fork attempted
        st.configure(payload_spec=None, sink_spec=None, memfd=-1,
                     file_size=0, out_fds=[], signal_w=-1,
                     fallow_w=-1, order_w=-1, trap_ack_w=-1,
                     on_error="retry", engine_fds=set())
        n_before = st.live_count()
        handle_spawn_bytes(st, b"100\n")
        self.assertEqual(st.live_count(), n_before)

    def test_spawn_malformed_ignored(self):
        from forkrun._reactor import ReactorState, handle_spawn_bytes
        st = ReactorState(0)
        st.configure(payload_spec=None, sink_spec=None, memfd=-1,
                     file_size=0, out_fds=[], signal_w=-1,
                     fallow_w=-1, order_w=-1, trap_ack_w=-1,
                     on_error="retry", engine_fds=set())
        handle_spawn_bytes(st, b"bogus\n-3\n0\n1:2:3\n")
        self.assertEqual(st.live_count(), 0)

    def test_spawn_node_fallback(self):
        from forkrun._reactor import ReactorState, handle_spawn_bytes
        st = ReactorState(0, num_nodes=2)
        st.configure(payload_spec=None, sink_spec=None, memfd=-1,
                     file_size=0, out_fds=[], signal_w=-1,
                     fallow_w=-1, order_w=-1, trap_ack_w=-1,
                     on_error="retry", engine_fds=set())
        handle_spawn_bytes(st, b"9:5\n")  # bad node → node 0, clamped
        self.assertEqual(st.live_count(), 0)


class TestScannerDeathUnit(unittest.TestCase):
    """Death-pipe classification without the engine."""

    def test_clean_exit(self):
        from forkrun._reactor import check_scanner_death
        death_r, death_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(death_r)
            os.close(death_w)
            os._exit(0)
        os.close(death_w)
        kind, code = check_scanner_death(pid, death_r)
        # Either observed-exited or still-running-then-reaped below.
        if kind == "running":
            _, status = os.waitpid(pid, 0)
            os.close(death_r)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
        else:
            self.assertEqual((kind, code), ("clean", 0))

    def test_error_exit(self):
        from forkrun._reactor import check_scanner_death
        import time as _t
        death_r, death_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(death_r)
            _t.sleep(5)
            os._exit(0)  # unreachable; parent kills first
        os.close(death_w)
        os.kill(pid, 9)
        deadline = time.monotonic() + 10
        kind, code = ("running", None)
        while kind == "running" and time.monotonic() < deadline:
            kind, code = check_scanner_death(pid, death_r)
            if kind == "running":
                time.sleep(0.05)
        try:
            os.close(death_r)
        except OSError:
            pass
        self.assertEqual(kind, "error")


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestReactorPurity(unittest.TestCase):
    """Transport-file hygiene covers the reactor (no IPC smuggling)."""

    def test_no_banned_tokens(self):
        # Same token list as test_v0.TestPurity, extended to the new
        # reactor module. _spawn.py stays exempt by design.
        pkg = os.path.join(os.path.dirname(__file__), "..", "forkrun")
        offenders = []
        for name in ("_reactor.py", "run.py", "_worker.py",
                     "_bindings.py"):
            with open(os.path.join(pkg, name)) as fh:
                src = fh.read()
            for token in ("subprocess.", "Popen", "import pickle",
                          "from pickle", "cPickle", "os.system",
                          "frun.bash", "source ./frun",
                          "multiprocessing", "multiprocessing.Pipe",
                          "multiprocessing.Queue"):
                if token in src:
                    offenders.append("%s: %s" % (name, token))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
