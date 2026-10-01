"""W-REL4/R-V1: invariant gate — machine-checked §3/§6/§9.

forkrun's correctness lives in its invariants; a missed one is a
wrong answer, silently. Each probe runs through the public API
with boundary fault injection (existing adversarial machinery —
no new injection mechanisms) and names its invariant on failure.

- §6 Escrow Correctness: escrow advisory, never required for
  forward progress. Escrow disabled (deposit binding fails) +
  mid-batch death -> still byte-exact via transaction recovery;
  plus soft-failure leg -> loud poison-skip, never silent loss.
- §3 Batch Atomicity: claimed whole or not at all. Permanent
  per-batch failure under on_error="skip" removes EXACTLY one
  deterministic batch span — framing parseable, cursor at the
  batch boundary, batch fully present or fully absent.
- §9 Contiguous-Prefix Emission: genuine hole (poisoned batch)
  under order="index" -> everything else byte-exact in order,
  hole reported loudly, never emitted-around or duplicated.

Deterministic batching via lines= (exact line counts).
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


def _lines(path, n, fmt="line %d\n"):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(fmt % i)
    with open(path, "rb") as fh:
        return fh.read().splitlines()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestEscrowAdvisory(unittest.TestCase):
    """INVARIANTS §6: ignore escrow entirely, still complete all work."""

    def tearDown(self):
        assert_no_zombies(self)

    def _dead_deposits(self):
        lib = get()
        real = lib.fr_py_escrow_deposit

        def _dead(kills):
            return 1

        return mock.patch.object(lib, "fr_py_escrow_deposit",
                                 side_effect=_dead), real

    def test_death_recovers_with_escrow_disabled(self):
        # Mid-batch SIGSEGV, every deposit refused: transaction
        # recovery (not escrow) must still complete byte-exact.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        flag = path + ".killed"
        try:
            raw = _lines(path, 2000)

            def killer(batch):
                data = bytes(batch.data)
                if b"line 1000" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    import ctypes

                    ctypes.string_at(0)
                return data

            patcher, _real = self._dead_deposits()
            with patcher:
                out = forkrun.map(killer, path, workers=2,
                                  order="index", nodes=1)
            self.assertEqual(
                b"".join(out).splitlines(), raw,
                "INVARIANT §6 VIOLATED: escrow disabled, mid-batch "
                "death lost work (transaction recovery required "
                "escrow)")
        finally:
            os.unlink(path)
            if os.path.exists(flag):
                os.unlink(flag)

    def test_soft_failure_skips_loud_with_escrow_disabled(self):
        # Soft failure + dead deposits: the batch must go loud
        # (named poison notice), the pipeline must complete, and
        # nothing may vanish silently.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        flag = path + ".failed"
        try:
            raw = _lines(path, 500)

            def flaky(batch):
                data = bytes(batch.data)
                if b"line 100" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    raise ValueError("once")
                return data

            patcher, _real = self._dead_deposits()
            saved = redirect_fd(2, cap)
            try:
                with patcher:
                    out = forkrun.map(flaky, path, workers=1,
                                      order="index", nodes=1)
            finally:
                restore_fd(2, saved)
            with open(cap, "rb") as fh:
                err = fh.read()
            self.assertIn(
                b"escrow deposit refused", err,
                "INVARIANT §6 VIOLATED: escrow disabled, soft "
                "failure went quiet (no loud notice)")
            out_lines = b"".join(out).splitlines()
            self.assertEqual(len(out_lines), len(set(out_lines)),
                             "INVARIANT §6 VIOLATED: duplicated output")
            self.assertTrue(
                set(out_lines) < set(raw),
                "INVARIANT §6 VIOLATED: output not a strict announced "
                "subset (silent loss or corruption)")
        finally:
            os.unlink(path)
            for extra in (cap, flag):
                if os.path.exists(extra):
                    os.unlink(extra)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestBatchAtomicity(unittest.TestCase):
    """INVARIANTS §3: a batch is claimed whole or not at all."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_skipped_batch_removes_exact_span(self):
        # lines=100 makes batches deterministic (20 x 100). The
        # line-500 batch always fails -> skipped under on_error="skip".
        # Atomicity demands: exactly lines 500-599 absent, framing
        # intact, everything else byte-identical and ordered.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            raw = _lines(path, 2000)

            def poison(batch):
                data = bytes(batch.data)
                if b"line 500" in data:
                    raise ValueError("always")
                return data

            out = forkrun.map(poison, path, workers=2, lines=100,
                              order="index", nodes=1, on_error="skip")
            got = b"".join(out).splitlines()
            self.assertEqual(
                got, raw[:500] + raw[600:],
                "INVARIANT §3 VIOLATED: skipped batch did not remove "
                "exactly its span (torn batch or cursor drift)")
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestContiguousPrefix(unittest.TestCase):
    """INVARIANTS §9: emit only contiguous prefix; holes reported."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_poison_hole_reported_not_emitted_around(self):
        # The line-300 batch dies every attempt -> poisoned after
        # the retry limit (F-NUMA1 hole signature at Python level).
        # The emitter must return everything else byte-exact in
        # order, report the hole loudly, and never duplicate or
        # shuffle around it.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        try:
            raw = _lines(path, 2000)

            def killer(batch):
                data = bytes(batch.data)
                if b"line 300" in data:
                    import ctypes

                    ctypes.string_at(0)
                return data

            saved = redirect_fd(2, cap)
            try:
                out = forkrun.map(killer, path, workers=2, lines=100,
                                  order="index", nodes=1)
            finally:
                restore_fd(2, saved)
            with open(cap, "rb") as fh:
                err = fh.read()
            self.assertIn(
                b"poisoned batch", err,
                "INVARIANT §9 VIOLATED: hole completed without a "
                "report (emitted-around silently)")
            got = b"".join(out).splitlines()
            self.assertEqual(
                got, raw[:300] + raw[400:],
                "INVARIANT §9 VIOLATED: hole corrupted ordering "
                "(emitted-around, duplicates, or short)")
        finally:
            os.unlink(path)
            if os.path.exists(cap):
                os.unlink(cap)


if __name__ == "__main__":
    unittest.main()
