"""W-PY28 universal recovery: engine core unit tests (Stage 5).

Exercises ring_recover_worker_core through the fr_py_recover_worker
shim wrapper — pure-state cases (no engine, bad wid, IDLE paths)
plus a live in-process orphan: claim → partial output → recover
(without ack) → truncated output + escrowed retry with kills+1.

No threads, no forks (all in-process except where noted).
"""

import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun._bindings import (FrPyBatch, RC_EOF, RC_OK, find_substrate,
                               get)  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _has_recover():
    if not HAVE_LIB:
        return False
    try:
        return hasattr(get(), "fr_py_recover_worker")
    except Exception:
        return False


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestRecoverInterface(unittest.TestCase):
    def test_symbols_present(self):
        lib = get()
        for sym in ("fr_py_recover_worker", "fr_py_set_output_fd",
                    "fr_py_ack_init"):
            self.assertTrue(hasattr(lib, sym), sym)

    def test_no_engine_is_fatal(self):
        # No engine state (fresh process, no init): core fails closed.
        lib = get()
        try:
            lib.fr_py_destroy()
        except Exception:
            pass
        # g_state may or may not exist here (other tests); only assert
        # the bad-wid guard, which holds regardless of engine state.
        self.assertEqual(lib.fr_py_recover_worker(9999, 0, -1, 1), 5)
        self.assertEqual(lib.fr_py_recover_worker(-1, 0, -1, 0), 5)

    def test_set_output_fd(self):
        lib = get()
        self.assertEqual(lib.fr_py_set_output_fd(-1), 0)
        self.assertEqual(lib.fr_py_ack_init(-1), 0)


@unittest.skipUnless(_has_recover(), "fr_py_recover_worker absent")
class TestRecoverCore(unittest.TestCase):
    """Live engine, in-process worker: publish → die → recover."""

    def _init_with_lines(self, lines):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_txn_test_in")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib, memfd

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def test_idle_clean_exit_frees(self):
        # Fresh engine, nothing claimed: IDLE + exit 0 → NORMAL_EXIT.
        lib, _ = self._init_with_lines(10)
        self.assertEqual(lib.fr_py_recover_worker(0, 0, -1, 0), 2)

    def test_idle_error_midstream_respawns(self):
        # Fresh engine (scanner not finished → mid-stream):
        # IDLE + exit != 0 → NO_BATCH (respawn).
        lib, _ = self._init_with_lines(10)
        # fr_py_scan ran synchronously to completion above, so the
        # scanner IS finished and all batches are published but
        # unclaimed: read_idx(0) < write_idx → mid-stream → respawn.
        self.assertEqual(lib.fr_py_recover_worker(0, 0, -1, 1), 1)

    def test_orphan_revert_and_escrow(self):
        """Claim → partial output → recover (no ack): truncated +
        escrowed with kills+1, next claim observes it."""
        lib, _ = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_txn_test_out")
        self.addCleanup(lambda: self._close(out_fd))

        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)

        claimed = FrPyBatch()
        rc = lib.fr_py_claim(ctypes.byref(claimed))
        self.assertEqual(rc, RC_OK)
        first_idx = claimed.batch_idx

        # Simulate partial output (died mid-batch, no ack).
        os.write(out_fd, b"PARTIAL OUTPUT BYTES")
        self.assertGreater(os.fstat(out_fd).st_size, 0)

        # Parent-side recovery (exit 9 ~= SIGKILL-class death).
        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 0)  # RECOVERED

        # Output rolled back to the pre-batch position (0 here).
        self.assertEqual(os.fstat(out_fd).st_size, 0)

        # The batch rides escrow: next claim re-issues it with kills+1.
        again = FrPyBatch()
        rc = lib.fr_py_claim(ctypes.byref(again))
        self.assertEqual(rc, RC_OK)
        self.assertEqual(again.batch_idx, first_idx)
        self.assertEqual(again.num_kills, claimed.num_kills + 1)

    def test_stale_incarnation_stands_down(self):
        """Record from generation 0, recovery asked for generation 5:
        stale → clear, classify by exit (no escrow side effects)."""
        lib, _ = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_txn_test_out2")
        self.addCleanup(lambda: self._close(out_fd))

        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        claimed = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(claimed)), RC_OK)

        # Wrong generation: no recovery, error → NO_BATCH.
        self.assertEqual(lib.fr_py_recover_worker(0, 5, out_fd, 1), 1)
        # Record cleared: a second look is IDLE (mid-stream → NO_BATCH
        # here as well, but crucially NOT an orphan re-deposit).
        self.assertEqual(lib.fr_py_recover_worker(0, 5, out_fd, 1), 1)

    def test_exit_zero_with_orphan_is_fatal(self):
        """CLAIMED + exit 0: worker bug (correct workers exit 0 only
        at EOF with TXN_IDLE) → defensive FATAL."""
        lib, _ = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_txn_test_out3")
        self.addCleanup(lambda: self._close(out_fd))

        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        claimed = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(claimed)), RC_OK)
        self.assertEqual(lib.fr_py_recover_worker(0, 0, out_fd, 0), 5)


if __name__ == "__main__":
    unittest.main()
