"""W-REL2/R14a: refused escrow deposits go loud, never silent.

INVARIANTS §6: escrow is advisory, never required for forward
progress. A deposit that fails (closed fd, blocking/EBADF) is
retried once, then the batch is poison-skipped LOUDLY (stderr
notice naming the batch) while the pipeline completes — the
W-PY22 refused-instead-of-silent-loss doctrine.

Lock-in: monkeypatch fr_py_escrow_deposit to fail twice, then
provoke exactly one failure-path deposit. Deterministic:
workers=1, order=index (contiguous batches).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get  # noqa: E402

from _helpers import (assert_no_zombies, redirect_fd, restore_fd,  # noqa: E402
                      write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestEscrowRefusedLoud(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_deposit_refused_twice_poison_skips_loud(self):
        # Deposit fails twice (return 5) on the single failure-path
        # deposit, then the binding behaves. Expect: rc 0, loud
        # notice naming the batch, the failed batch skipped, every
        # other line byte-exact with no duplication.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        flag = path + ".failed"
        calls_log = path + ".calls"
        lib = get()
        try:
            write_lines(path, 500)
            with open(path, "rb") as fh:
                raw_lines = fh.read().splitlines()

            def flaky(batch):
                data = bytes(batch.data)
                if b"line 100" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    raise ValueError("once")
                return data

            calls = {"n": 0}
            real = lib.fr_py_escrow_deposit

            def refuse_twice(kills):
                # NOTE: this runs in forked workers — the count must
                # live on the filesystem (parent memory is not
                # shared across fork).
                with open(calls_log, "a") as _fh:
                    _fh.write("1\n")
                n = sum(1 for _ in open(calls_log))
                if n <= 2:
                    return 5
                return real(kills)

            saved = redirect_fd(2, cap)
            try:
                with mock.patch.object(lib, "fr_py_escrow_deposit",
                                       side_effect=refuse_twice):
                    out = forkrun.map(flaky, path, workers=1,
                                      order="index", nodes=1)
            finally:
                restore_fd(2, saved)
            with open(calls_log) as _fh:
                self.assertEqual(sum(1 for _ in _fh), 2)
            with open(cap, "rb") as fh:
                err = fh.read()
            self.assertIn(b"escrow deposit refused twice", err)
            self.assertIn(b"Skipping batch", err)
            got_lines = b"\n".join(
                b"".join(out).splitlines())
            self.assertNotIn(b"line 100", got_lines)
            # No silent corruption: output lines are a duplicate-free
            # subset of the input, strictly smaller (one batch loud-
            # skipped), and the pipeline completed (rc 0 implied).
            out_lines = b"".join(out).splitlines()
            self.assertEqual(len(out_lines), len(set(out_lines)),
                             "duplicated output lines")
            self.assertTrue(set(out_lines) < set(raw_lines),
                            "output must be a strict subset (one skip)")
            self.assertTrue(len(out_lines) > 0)
        finally:
            os.unlink(path)
            for extra in (cap, flag, calls_log):
                if os.path.exists(extra):
                    os.unlink(extra)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestDoubleDepositSingleEntry(unittest.TestCase):
    """W-REL2/R14b: fr_py_escrow_deposit clears worker_last_cnt on
    success (mirroring ring_ack_main). Two deposits without an
    intervening claim must leave exactly one escrow entry — the
    batch executes once, never twice.

    Shape: the payload deposits twice itself, then segfaults (so
    the EXIT-trap deposit is a third no-claim deposit attempt).
    Pre-fix the duplicate entries corrupt recovery (observed:
    inexact output — missing lines); post-fix the batch appears
    exactly once. Verified FAIL pre-fix / 10x10 PASS post-fix.
    Deterministic: workers=2, order=index.
    """

    def tearDown(self):
        assert_no_zombies(self)

    def test_double_deposit_no_duplicates(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        flag = path + ".killed"
        try:
            write_lines(path, 500)
            with open(path, "rb") as fh:
                raw_lines = fh.read().splitlines()

            def killer(batch):
                from forkrun._bindings import get as _get
                data = bytes(batch.data)
                if b"line 100" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    lib = _get()
                    lib.fr_py_escrow_deposit(1)
                    lib.fr_py_escrow_deposit(1)
                    import ctypes

                    ctypes.string_at(0)
                return data

            out = forkrun.map(killer, path, workers=2,
                              order="index", nodes=1)
            out_lines = b"".join(out).splitlines()
            self.assertEqual(len(out_lines), len(set(out_lines)),
                             "duplicated output lines (double-deposit)")
            self.assertEqual(set(out_lines), set(raw_lines),
                             "every input line exactly once")
        finally:
            os.unlink(path)
            if os.path.exists(flag):
                os.unlink(flag)


if __name__ == "__main__":
    unittest.main()
