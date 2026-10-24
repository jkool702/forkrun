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

import contextlib
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      ChildLifecycleMixin,
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data).upper()


#: stderr emitted by the most recent _capture_stderr() block.
_LAST_STDERR = [""]


@contextlib.contextmanager
def _capture_stderr():
    """Capture fd 2 for the duration of the block.

    The poison pill reports on stderr, and asserting that report exists
    is part of the guarantee -- a batch skipped WITHOUT telling the user
    is silent partial data loss. Redirecting fd 2 rather than using
    warnings catches the C-level write as well as any Python-level
    message, so the assertion cannot be satisfied by a stray UserWarning.
    """
    saved = os.dup(2)
    tmp = os.memfd_create("stderr")
    try:
        os.dup2(tmp, 2)
        yield
        # Flush the PYTHON-level stderr buffer too: sys.stderr wraps fd 2
        # and may hold buffered text that has not reached the fd yet.
        # (os has no flush() -- that was the first attempt's bug.)
        try:
            sys.stderr.flush()
        except Exception:
            pass
        os.fsync(tmp)
        os.lseek(tmp, 0, os.SEEK_SET)
        chunks = []
        while True:
            b = os.read(tmp, 65536)
            if not b:
                break
            chunks.append(b)
        _LAST_STDERR[0] = b"".join(chunks).decode("utf-8", "replace")
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(tmp)


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
                forkrun.map(_up, "f.txt", orchestrator=bad, nodes=1)

    def test_bad_orchestrator_run_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.run(_up, "f.txt", orchestrator="true", nodes=1)

    def test_bad_orchestrator_stream_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.stream(_up, "f.txt", orchestrator=1, nodes=1)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestReactorBasic(ChildLifecycleMixin, unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_map_parity_none(self):
        path = _make_input(1500)
        try:
            simple = forkrun.map(_up, path, workers=4, nodes=1, output="bytes")
            react = forkrun.map(_up, path, workers=4,
                                orchestrator=True, nodes=1, output="bytes")
            self.assertEqual(lines_of(simple), lines_of(react))
        finally:
            os.unlink(path)

    def test_map_parity_index(self):
        path = _make_input(1500)
        try:
            simple = forkrun.map(_up, path, workers=4, order="index", nodes=1)
            react = forkrun.map(_up, path, workers=4,
                                orchestrator=True, order="index", nodes=1)
            self.assertEqual(joined_bytes(simple), joined_bytes(react))
        finally:
            os.unlink(path)

    def test_run_discard(self):
        path = _make_input(800)
        try:
            self.assertIsNone(forkrun.run(_up, path, workers=2,
                                          orchestrator=True, nodes=1))
        finally:
            os.unlink(path)

    def test_stream_parity(self):
        path = _make_input(1500)
        try:
            simple = forkrun.stream(_up, path, workers=4, nodes=1)
            react = forkrun.stream(_up, path, workers=4,
                                   orchestrator=True, nodes=1)
            self.assertEqual(lines_of(simple), lines_of(react))
        finally:
            os.unlink(path)

    def test_stream_ordered_parity(self):
        path = _make_input(1500)
        try:
            simple = list(forkrun.stream(_up, path, workers=4,
                                         order="index", nodes=1))
            react = list(forkrun.stream(_up, path, workers=4,
                                        orchestrator=True,
                                        order="index", nodes=1))
            self.assertEqual(joined_bytes(simple), joined_bytes(react))
        finally:
            os.unlink(path)

    def test_splice_parity(self):
        path = _make_input(3000)
        try:
            simple = forkrun.map(None, path, mode="splice",
                                 bytes=32768, workers=2, nodes=1, output="bytes")
            react = forkrun.map(None, path, mode="splice",
                                bytes=32768, workers=2,
                                orchestrator=True, nodes=1, output="bytes")
            self.assertEqual(lines_of(simple), lines_of(react))
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
            react = forkrun.map(_up, r, workers=2, orchestrator=True, nodes=1)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        path = _make_input(1500, prefix="pipe")
        try:
            simple = forkrun.map(_up, path, workers=2, nodes=1)
        finally:
            os.unlink(path)

        def _lines(res):
            return sorted(b"".join(res).splitlines())

        self.assertEqual(_lines(simple), _lines(react))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerRespawn(ChildLifecycleMixin, unittest.TestCase):
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
                # order="index" EXPLICITLY (round-9 review). Both runs
                # previously used the default order="none", where output
                # is COMPLETION order -- so `healthy_recs[0]` was the
                # first record to COMPLETE, not necessarily batch 0, and
                # `healthy_recs[1:] == res_recs` treated list position as
                # batch identity. That is not a contract order="none"
                # makes, and it would reject a correct run whose later
                # batches happened to complete in a different order.
                #
                # Indexed order is a promise, so under it "the first
                # record IS batch 0" is supported rather than assumed,
                # and the rest of the assertion becomes meaningful.
                res = forkrun.map("w19segv_mod:payload", path,
                                  workers=2, orchestrator=True, nodes=1,
                                  order="index")
            finally:
                sys.path.remove(plugin_dir)
            # The crashed batch is best-effort (no escrow possible
            # for a death that runs no code); everything else lands.
            #
            # Was: assertEqual(len(res), len(healthy) - 1) plus
            # assertIn(b"LINE 1999\n", ...). The count says ONE blob is
            # missing but not WHICH -- a run that dropped batch 500 and
            # kept batch 0 satisfies it just as well as the opposite.
            # The round-8 review is right that it does not establish that
            # the correct batch was lost and the rest intact.
            #
            # Now asserts the CONTENT: exactly the first record of the
            # healthy run is absent, and every other record is present
            # byte-identical. That names the loss and proves the tail,
            # which a count cannot.
            healthy = forkrun.map(_up, path, workers=2, nodes=1,
                                  order="index")
            healthy_recs = [bytes(x) for x in healthy if x is not None]
            res_recs = [bytes(x) for x in res if x is not None]
            self.assertEqual(
                len(healthy_recs) - 1, len(res_recs),
                "expected exactly one batch to be lost (%d healthy, %d "
                "recovered)" % (len(healthy_recs), len(res_recs)))
            self.assertNotIn(
                healthy_recs[0], res_recs,
                "batch 0 should be the LOST one -- a crash on the first "
                "batch cannot escrow, so it is dropped")
            self.assertEqual(
                healthy_recs[1:], res_recs,
                "every batch after the lost one must arrive byte-identical "
                "and in order; got %d record(s) against %d"
                % (len(res_recs), len(healthy_recs) - 1))
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
                    "        with open(MARKER, 'w') as _m:\n"
                    "            _m.write('x')\n"
                    "        os.kill(os.getpid(), signal.SIGKILL)\n"
                    "    return bytes(batch.data).upper()\n" % marker)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map("w28killonce_mod:payload", path,
                                  workers=2, orchestrator=True,
                                  order="index", nodes=1)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index", nodes=1)
            # Full recovery: every batch lands, order preserved.
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
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
                                workers=1, orchestrator=True, nodes=1)
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
                                workers=1, orchestrator=True, nodes=1)
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
                            orchestrator=True, on_error="fail-fast", nodes=1)
            dt = time.monotonic() - t0
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestTrapACK(ChildLifecycleMixin, unittest.TestCase):
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
                            orchestrator=True, on_error="fail-fast", nodes=1)
        finally:
            os.unlink(path)

    def test_poison_notification_path(self):
        """Retry-always-fail poisons via escrow; run completes short."""
        path = _make_input(1000)
        try:
            # Selective failure (round-9 review). The payload raised for
            # EVERY batch, so the result was empty and
            # `set(got_lines) <= set(healthy_lines)` was trivially true of
            # the empty set -- it established nothing about surviving
            # content, and an early abort after the warning would also
            # have satisfied it. Failing only EVEN batches leaves real
            # output behind, so the surviving set can be checked against
            # what a correct skip should leave.
            def _boom(batch):
                if batch.batch_index % 2 == 0:
                    raise ValueError("nope")
                return bytes(batch.data).upper()
            with _capture_stderr():
                res = forkrun.map(_boom, path, workers=2,
                                  orchestrator=True, on_error="retry",
                                  nodes=1)
            healthy = forkrun.map(_up, path, workers=2, nodes=1)
            # Poisoned batches are skipped, never silently kept.
            #
            # Was: assertLess(len(res), len(healthy)). That proves
            # something was dropped, which is also what any truncation,
            # any lost batch and any early exit would satisfy -- and it
            # never checks the user was TOLD. A poison pill that skipped
            # batches silently would pass.
            #
            # Now: the poison warning must appear on stderr, and the
            # surviving content must be the healthy content minus whole
            # records -- dropped, never altered or duplicated.
            self.assertLess(len(res), len(healthy))
            # PINNED to the per-batch warning, not merely the word.
            #
            # Mutation-checked: silencing every "Skipping poisoned batch"
            # fprintf in _shim.c still passed a bare
            # assertIn("poison", stderr), because the run ALSO prints
            # "N poisoned batch(es) skipped" and a POISONED BATCH
            # SUMMARY. So the assertion was satisfiable without the
            # notification the test is about.
            self.assertRegex(
                _LAST_STDERR[0],
                r"\[WARN\]: Skipping poisoned batch \d+",
                "the per-batch poison warning is missing; stderr had:\n%s"
                % _LAST_STDERR[0][:400])
            healthy_lines = sorted(
                b"".join(bytes(x) for x in healthy if x is not None)
                .splitlines())
            got_lines = sorted(
                b"".join(bytes(x) for x in res if x is not None)
                .splitlines())
            # There IS surviving content now, so these are load-bearing.
            self.assertTrue(
                got_lines, "no output survived; the selective payload "
                           "should have let the odd batches through")
            self.assertTrue(
                set(got_lines) <= set(healthy_lines),
                "the poisoned run produced lines the healthy run did not, "
                "so records were altered rather than skipped")
            self.assertLess(
                len(got_lines), len(healthy_lines),
                "nothing was actually skipped -- every batch should have "
                "been poisoned by the even-index rule")
            # And the surviving content is a PROPER, substantial subset:
            # roughly the odd half, not a token remnant.
            self.assertGreater(
                len(got_lines), 0.4 * len(healthy_lines),
                "only %d of %d lines survived; that looks like an early "
                "abort rather than selective skipping"
                % (len(got_lines), len(healthy_lines)))
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
class TestCOrderer(ChildLifecycleMixin, unittest.TestCase):
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
                                orchestrator=True, order="index", nodes=1)
            via_py = forkrun.map(_up, path, workers=4,
                                 orchestrator=False, order="index", nodes=1)
            # Split-agnostic parity: the C orderer and the Python
            # reassembly consume the same records, but the two runs
            # batch independently (F-PY-UMA1 comparison doctrine).
            self.assertEqual(joined_bytes(via_c), joined_bytes(via_py))
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


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerStartupDeadline(ChildLifecycleMixin, unittest.TestCase):
    """W-REL6-3.1: fork-in-threaded-host hang is bounded.

    String payloads resolve in the parent (no post-fork import);
    children signal readiness (READY_BYTE); generations that never
    signal are SIGKILLed at the startup deadline and recovery
    proceeds through the normal death path.
    """

    def tearDown(self):
        assert_no_zombies(self)

    def test_string_payload_imports_in_parent(self):
        """String payload's module is imported by the parent (x5).

        Deterministic: fresh module name per iteration (import cache).
        Pre-fix the import happened in the child (post-fork) -- the
        IMPORT_PID record distinguishes the two.
        """
        from forkrun import _worker as _worker_mod  # noqa: F401
        for i in range(5):
            modname = "w31par_%d_%d" % (os.getpid(), i)
            plugdir = tempfile.mkdtemp(prefix="w31par_")
            path = _make_input(200)
            try:
                with open(os.path.join(plugdir, modname + ".py"),
                          "w") as fh:
                    fh.write(
                        "import os\n"
                        "IMPORT_PID = os.getpid()\n"
                        "def payload(batch):\n"
                        "    return bytes(batch.data).upper()\n")
                sys.path.insert(0, plugdir)
                try:
                    sys.modules.pop(modname, None)
                    res = forkrun.map(modname + ":payload", path,
                                      workers=2, nodes=1)
                    self.assertIn(modname, sys.modules)
                    self.assertEqual(
                        sys.modules[modname].IMPORT_PID, os.getpid(),
                        "payload module imported in a child, not parent")
                    got = sorted(b"".join(res).split())
                    want = sorted([b"LINE"] * 200 +
                                  [str(n).encode() for n in range(200)])
                    self.assertEqual(got, want)
                finally:
                    sys.path.remove(plugdir)
            finally:
                os.unlink(path)
                import shutil as _shutil
                _shutil.rmtree(plugdir, ignore_errors=True)

    def test_startup_deadline_fires_and_recovers(self):
        """Pre-ready hang is SIGKILLed; recovery completes (x10).

        Timing: the child-side mock hangs pre-ready while the wall
        clock is inside the gate, so early generations must be
        deadline-killed; generations forked past the gate proceed.
        Deadline 1.0s / gate 1.2s admits at most 2 kills per worker
        (gen-1 dies ~1.1s; a gen-2 forked just under the gate dies
        ~2.2s; later generations proceed) -- safely under the
        default respawn cap of 3, so the run always completes via
        recovery. Without the deadline the first generation sleeps
        10s (>=10s run); with it the run completes in ~gate+work.
        The 8s bound has 2x+ headroom over the ~2.5s nominal.
        """
        from unittest import mock as _mock
        from forkrun import _worker as _worker_mod
        path = _make_input(500)
        try:
            parent = os.getpid()
            real_resolve = _worker_mod._resolve_payload
            for i in range(10):
                gate = time.monotonic() + 1.2

                def _blocking(spec, _real=real_resolve,
                              _pp=parent, _gate=gate):
                    if os.getpid() != _pp \
                            and time.monotonic() < _gate:
                        time.sleep(10)  # pre-ready hang, past deadline
                    return _real(spec)

                with _mock.patch.dict(
                        os.environ,
                        {"FORKRUN_WORKER_STARTUP_S": "1.0"}):
                    with _mock.patch.object(
                            _worker_mod, "_resolve_payload", _blocking):
                        t0 = time.monotonic()
                        res = forkrun.map(_up, path, workers=2, nodes=1)
                        dt = time.monotonic() - t0
                got = sorted(b"".join(res).split())
                want = sorted([b"LINE"] * 500 +
                              [str(n).encode() for n in range(500)])
                self.assertEqual(got, want,
                                 "iter %d: recovery lost data" % i)
                self.assertLess(
                    dt, 8.0,
                    "iter %d: %.1fs -- deadline never fired (hang "
                    "survived to the mock sleep)" % (i, dt))
        finally:
            os.unlink(path)

    def test_check_startup_timeouts_kills_and_records(self):
        """Expired unready slot is SIGKILLed + recorded; ready spared.

        Engine-free unit (x5): real sleeper subprocess as the victim
        verifies the kill signal, not just the bookkeeping.
        """
        import signal as _signal
        from forkrun._reactor import ReactorState, WorkerSlot
        for i in range(5):
            state = ReactorState(2, startup_deadline=0.2)
            pid = os.fork()
            if pid == 0:
                time.sleep(30)
                os._exit(0)
            try:
                slot = WorkerSlot(0, 0, pid, -1, -1)
                slot.spawned_at = time.monotonic() - 10.0
                state.workers[0] = slot
                state.check_startup_timeouts()
                self.assertEqual(state.startup_kills, [0])
                _, status = os.waitpid(pid, 0)
                pid = None
                self.assertTrue(os.WIFSIGNALED(status),
                                "victim was not signaled")
                self.assertEqual(os.WTERMSIG(status), _signal.SIGKILL)
            finally:
                if pid is not None:
                    try:
                        os.kill(pid, _signal.SIGKILL)
                    except OSError:
                        pass
                    try:
                        os.waitpid(pid, 0)
                    except (ChildProcessError, OSError):
                        pass
            # Control: a ready worker past its deadline is spared.
            pid = os.fork()
            if pid == 0:
                time.sleep(30)
                os._exit(0)
            try:
                slot = WorkerSlot(0, 0, pid, -1, -1)
                slot.ready = True
                slot.spawned_at = time.monotonic() - 10.0
                state.workers[0] = slot
                state.check_startup_timeouts()
                self.assertEqual(state.startup_kills, [0])
                os.kill(pid, 0)  # still alive: raises otherwise
            finally:
                try:
                    os.kill(pid, _signal.SIGKILL)
                except OSError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except (ChildProcessError, OSError):
                    pass

    def test_note_ready_consumes_handshake(self):
        """note_ready marks ready on READY_BYTE, EOF means death (x5)."""
        from forkrun._reactor import ReactorState, WorkerSlot
        from forkrun._worker import READY_BYTE
        for i in range(5):
            st = ReactorState(1)
            slot = WorkerSlot(0, 0, 424242 + i, -1, -1)
            st.workers[0] = slot
            self.assertTrue(st.note_ready(0, READY_BYTE))
            self.assertTrue(slot.ready)
            self.assertTrue(st.note_ready(0, READY_BYTE))
            self.assertFalse(st.note_ready(0, b""))
            self.assertFalse(st.note_ready(999, READY_BYTE))


if __name__ == "__main__":
    unittest.main()
