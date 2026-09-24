"""W-PY29 adversarial recovery tests: race windows + rollback exactness.

Exercises the 4-state WorkerTxn machine (IDLE → CLAIMING → CLAIMED →
COMMITTING → IDLE) at its boundaries:

- Claim→publish race (TXN_CLAIMING → RACE_DETECTED, rc 4)
- ACK→clear race (TXN_COMMITTING → RACE_DETECTED, rc 4)
- SIGKILL partial-output rollback, ordered AND unordered (cursor fix)
- output_start exactness across a simulated respawn
- Publish→payload boundary (the normal catastrophic path)
- Multiple / back-to-back deaths (each transaction recovered once)
- No lseek in the claim-time publication path (white-box lock-in)

Kill-injection mechanism: FORKRUN_TEST_DIE_AT_CLAIM /
FORKRUN_TEST_DIE_AT_COMMIT make a worker SIGKILL itself inside the
exact window (checked in fr_py_claim / fr_py_ack_core, inert unless
the env var is set). Unit tests drive this in a forked child sharing
the MAP_SHARED engine; integration tests set the env var around a
real orchestrator run and expect abort/resume (RuntimeError).

No threads. Forks only where noted; every forked child is reaped.
"""

import ctypes
import os
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import (FrPyBatch, RC_OK, find_substrate,  # noqa: E402
                               get)

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _has_symbols():
    if not HAVE_LIB:
        return False
    try:
        lib = get()
        return all(hasattr(lib, s) for s in (
            "fr_py_recover_worker", "fr_py_ack_init",
            "fr_py_output_advanced"))
    except Exception:
        return False


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _write_kill_module(plugin_dir, name, condition, per_batch=False):
    """Write a payload module that SIGKILLs itself when `condition`
    (a Python expression over batch/os/MARKER) holds, once per marker.
    per_batch=True gives each batch index its own marker (multiple
    gated deaths across the run); False fires exactly once total."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    marker = os.path.join(plugin_dir, name + ".dead")
    if per_batch:
        gate = ("MARK = MARKER + '.' + str(batch.batch_index)\n"
                "    if (%s) and not os.path.exists(MARK):\n"
                "        open(MARK, 'w').write('x')\n") % condition
    else:
        gate = ("if (%s) and not os.path.exists(MARKER):\n"
                "        open(MARKER, 'w').write('x')\n") % condition
    with open(mod_path, "w") as fh:
        fh.write(
            "import os, signal\n"
            "MARKER = %r\n"
            "def payload(batch):\n"
            "    %s"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    return bytes(batch.data).upper()\n" % (marker, gate))
    return name + ":payload"


def _write_count_kill_module(plugin_dir, name, limit):
    """Payload that SIGKILLs while fewer than `limit` kill-claim files
    exist (each dying worker drops one pid-named file first)."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    with open(mod_path, "w") as fh:
        fh.write(
            "import glob, os, signal\n"
            "KDIR = %r\n"
            "LIMIT = %d\n"
            "def payload(batch):\n"
            "    have = glob.glob(os.path.join(KDIR, 'k-*'))\n"
            "    if len(have) < LIMIT:\n"
            "        open(os.path.join(KDIR, 'k-%%d' %% os.getpid()),\n"
            "             'w').write('x')\n"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    return bytes(batch.data).upper()\n" % (plugin_dir, limit))
    return name + ":payload"


def _up(batch):
    return bytes(batch.data).upper()


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestClaimPublishRace(unittest.TestCase):
    """Death between begin_claim and publish reads TXN_CLAIMING → 4."""

    def tearDown(self):
        assert_no_zombies(self)

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init_with_lines(self, lines):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_adv_in")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib

    def test_claiming_returns_code_4(self):
        """Forked child dies inside the claim window → RACE_DETECTED."""
        lib = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_adv_out")
        self.addCleanup(lambda: self._close(out_fd))

        pid = os.fork()
        if pid == 0:
            # Child: share the MAP_SHARED engine, die in the window.
            try:
                lib.fr_py_worker_init(0, 0, 0, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                os.environ["FORKRUN_TEST_DIE_AT_CLAIM"] = "1"
                claimed = FrPyBatch()
                lib.fr_py_claim(ctypes.byref(claimed))
            except BaseException:
                pass
            # If the hook failed to kill us, fail loudly (exit 42).
            os._exit(42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status),
                        "child should die by signal, got %r" % (status,))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 4)  # RACE_DETECTED

    def test_forced_claim_publish_death(self):
        """Real run with DIE_AT_CLAIM: every worker dies claiming →
        the reactor aborts (conservative) instead of losing a ticket."""
        path = _make_input(500)
        os.environ["FORKRUN_TEST_DIE_AT_CLAIM"] = "1"
        try:
            with self.assertRaisesRegex(RuntimeError, "race"):
                forkrun.map(_up, path, workers=2, orchestrator=True, nodes=1)
        finally:
            del os.environ["FORKRUN_TEST_DIE_AT_CLAIM"]
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestAckClearRace(unittest.TestCase):
    """Death between order-packet write and clear reads COMMITTING → 4."""

    def tearDown(self):
        assert_no_zombies(self)

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init_with_lines(self, lines):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_adv_in2")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib

    def test_committing_returns_code_4(self):
        """Forked child claims, then dies inside ack → RACE_DETECTED."""
        lib = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_adv_out2")
        self.addCleanup(lambda: self._close(out_fd))

        pid = os.fork()
        if pid == 0:
            try:
                lib.fr_py_worker_init(0, 0, 0, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                claimed = FrPyBatch()
                rc = lib.fr_py_claim(ctypes.byref(claimed))
                if rc != RC_OK:
                    os._exit(43)
                os.environ["FORKRUN_TEST_DIE_AT_COMMIT"] = "1"
                lib.fr_py_ack_direct(-1, -1)
            except BaseException:
                pass
            os._exit(42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status),
                        "child should die by signal, got %r" % (status,))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 4)  # RACE_DETECTED

    def test_forced_ack_clear_death(self):
        """Real run with DIE_AT_COMMIT: deaths in the commit window →
        abort (never a silent double-emit via re-execution)."""
        path = _make_input(500)
        os.environ["FORKRUN_TEST_DIE_AT_COMMIT"] = "1"
        try:
            with self.assertRaisesRegex(RuntimeError, "race"):
                forkrun.map(_up, path, workers=2, orchestrator=True, nodes=1)
        finally:
            del os.environ["FORKRUN_TEST_DIE_AT_COMMIT"]
            os.unlink(path)


@unittest.skipUnless(_has_symbols(), "recovery symbols absent")
class TestPythonOutputRollback(unittest.TestCase):
    """SIGKILL mid-payload rolls back to the cursor, both orders."""

    def tearDown(self):
        assert_no_zombies(self)

    def _kill_once_run(self, order):
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w29rb_")
        mod_name = "w29rb_%s_mod" % order
        try:
            spec = _write_kill_module(
                plugin_dir, mod_name, "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=2,
                                  orchestrator=True, order=order, nodes=1)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order=order, nodes=1)
            if order == "none":
                # Completion order is nondeterministic — compare sets.
                self.assertEqual(lines_of(res), lines_of(healthy))
            else:
                self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_partial_output_ordered(self):
        """order=index: orphaned bytes never referenced downstream."""
        self._kill_once_run("index")

    def test_sigkill_partial_output_unordered(self):
        """order=none: cursor rollback (catches the stale-cursor bug —
        pre-W-PY29 the first claim published no usable frontier)."""
        self._kill_once_run("none")

    def test_output_start_exact_sequence_with_respawn(self):
        """output_start is the exact live end across batches AND across
        a simulated respawn (worker_init incarn+1 + ack_init on the
        reused fd). Recovery truncates exactly to it — no more (would
        destroy committed output), no less (would duplicate)."""
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        self.addCleanup(lib.fr_py_destroy)
        memfd = os.memfd_create("fr_adv_in3")
        self.addCleanup(lambda: os.close(memfd))
        data = "".join("line %d\n" % i for i in range(60)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        out_fd = os.memfd_create("fr_adv_out3")
        self.addCleanup(lambda: os.close(out_fd))

        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        lib.fr_py_ack_init(out_fd)

        # Batch 0: emit D0 + ack → end0 is the committed frontier.
        c0 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c0)), RC_OK)
        d0 = b"x" * 100
        self.assertEqual(lib.fr_py_emit(out_fd, -1, 0, c0.batch_idx,
                                        d0, len(d0)), 0)
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        end0 = os.fstat(out_fd).st_size
        self.assertEqual(end0, 16 + len(d0))

        # Batch 1: emit D1 + ack → end1.
        c1 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c1)), RC_OK)
        d1 = b"y" * 200
        self.assertEqual(lib.fr_py_emit(out_fd, -1, 0, c1.batch_idx,
                                        d1, len(d1)), 0)
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        end1 = os.fstat(out_fd).st_size
        self.assertEqual(end1, end0 + 16 + len(d1))

        # Simulated respawn: fresh generation on the reused fd. The
        # cursor must restart at the live end (one lseek at init).
        self.assertEqual(lib.fr_py_worker_init(0, 0, 1, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        lib.fr_py_ack_init(out_fd)

        # Batch 2: partial output, no ack (death mid-batch).
        c2 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c2)), RC_OK)
        os.write(out_fd, b"PARTIAL")
        self.assertGreater(os.fstat(out_fd).st_size, end1)

        rc = lib.fr_py_recover_worker(0, 1, out_fd, 9)
        self.assertEqual(rc, 0)  # RECOVERED
        # Exact truncation: committed prefix intact, partial gone.
        self.assertEqual(os.fstat(out_fd).st_size, end1)

        # Escrowed with kills+1: the next claim re-issues batch 2.
        again = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(again)), RC_OK)
        self.assertEqual(again.batch_idx, c2.batch_idx)
        self.assertEqual(again.num_kills, c2.num_kills + 1)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestPublishPayloadBoundary(unittest.TestCase):
    """Kill after CLAIMED but before any payload work: the fundamental
    normal-catastrophic path — truncate (no-op), escrow, retry wins."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_kill_after_publish_before_payload(self):
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w29pp_")
        try:
            # First payload invocation in the whole run dies instantly
            # (marker gates exactly one death; the retry succeeds).
            spec = _write_kill_module(plugin_dir, "w29pp_mod", "True")
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map(spec, path, workers=2,
                                  orchestrator=True, order="index", nodes=1)
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestMultipleDeaths(unittest.TestCase):
    """Each dead worker's transaction is recovered exactly once;
    the final output is complete regardless of death interleaving."""

    def tearDown(self):
        assert_no_zombies(self)

    def _count_kill_run(self, limit, workers):
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w29mk_")
        try:
            spec = _write_count_kill_module(plugin_dir, "w29mk_mod",
                                            limit)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=workers,
                                  orchestrator=True, order="index", nodes=1)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=workers,
                                  order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_two_workers_killed(self):
        self._count_kill_run(2, 4)

    def test_three_workers_killed(self):
        self._count_kill_run(3, 4)

    def test_worker_killed_while_recovery_in_progress(self):
        """Back-to-back deaths on different batches: the reactor handles
        deaths sequentially (synchronous recovery) — the second death
        lands while the first generation's replacement is still
        draining escrow. Both recover; output is complete."""
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w29seq_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w29seq_mod",
                "batch.batch_index in (0, 7)", per_batch=True)
            # Two markers (one per target batch): each fires once.
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map(spec, path, workers=2,
                                  orchestrator=True, order="index", nodes=1)
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestNoLseekInPublication(unittest.TestCase):
    """Lock-in: the claim-time publication path performs no lseek.

    The ordered ACK path keeps its pre-existing position lseek (commit
    accounting) — only the per-batch CLAIM path must be syscall-free.
    Verified white-box (the publish/bracket helpers' bodies) plus the
    behavioral rollback tests above (a cursor that required a per-batch
    lseek could not produce the exact frontiers they assert)."""

    def test_no_lseek_during_claim(self):
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        engine = os.path.join(root, "forkrun_ring.c")
        with open(engine) as fh:
            src = fh.read()
        for name in ("worker_txn_begin_claim",
                     "worker_txn_publish",
                     "worker_txn_abort_claim",
                     "worker_txn_begin_commit",
                     "worker_txn_clear",
                     "worker_txn_advance_output",
                     "worker_txn_init_output_cursor"):
            start = src.find(name + "(")
            # Definition site: "static inline ... name(" precedes it.
            decl = src.rfind("static inline", 0, start)
            self.assertNotEqual(decl, -1, name)
            depth = 0
            end = -1
            for i in range(src.find("{", decl), len(src)):
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            self.assertNotEqual(end, -1, name)
            body = src[decl:end]
            if name == "worker_txn_init_output_cursor":
                # The once-per-worker initializer OWNS the cursor lseek.
                self.assertIn("lseek", body, name)
            else:
                self.assertNotIn("lseek", body,
                                 "%s must not call lseek" % name)


if __name__ == "__main__":
    unittest.main()
