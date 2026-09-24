"""W-PY4.b G/Q-Series: process reuse (Stage 4 Phase 3).

Sequential invocations re-init/re-scan/re-fork in one process (no state
leakage, no fd/memfd leaks). Concurrent invocations from parent threads
are serialized by run._RUN_LOCK (engine globals are process-wide), so
both complete correctly — threads in the PARENT are fine; the v0
single-threaded contract constrains WORKER payloads only.
"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, nfd, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _identity(batch):
    return bytes(batch.data)


def _upper(batch):
    return bytes(batch.data).upper()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSequentialInvocations(unittest.TestCase):
    def test_two_runs_same_process(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pb = fh.name
        try:
            write_lines(pa, 1500)
            write_lines(pb, 700, fmt="other %d\n")
            out_a = forkrun.map(_identity, pa, workers=2, order="index", nodes=1)
            out_b = forkrun.map(_upper, pb, workers=2, order="index", nodes=1)
            with open(pa, "rb") as fh:
                self.assertEqual(b"".join(out_a), fh.read())
            with open(pb, "rb") as fh:
                self.assertEqual(b"".join(out_b), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(pa)
            os.unlink(pb)

    def test_many_runs_fd_stable(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 300)
            with open(path, "rb") as fh:
                raw = fh.read()
            before = nfd()
            for _ in range(10):
                out = forkrun.map(_identity, path, workers=2, order="index", nodes=1)
                self.assertEqual(b"".join(out), raw)
            self.assertEqual(nfd(), before)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestConcurrentInvocations(unittest.TestCase):
    def test_two_runs_concurrent_threads(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pb = fh.name
        try:
            write_lines(pa, 1200)
            write_lines(pb, 900, fmt="other %d\n")
            with open(pa, "rb") as fh:
                raw_a = fh.read()
            with open(pb, "rb") as fh:
                raw_b = fh.read().upper()
            results = {}
            errors = {}

            def run_a():
                try:
                    results["a"] = forkrun.map(_identity, pa, workers=2,
                                               order="index", nodes=1)
                except BaseException as exc:  # noqa: BLE001
                    errors["a"] = exc

            def run_b():
                try:
                    results["b"] = forkrun.map(_upper, pb, workers=2,
                                               order="index", nodes=1)
                except BaseException as exc:  # noqa: BLE001
                    errors["b"] = exc

            ta = threading.Thread(target=run_a)
            tb = threading.Thread(target=run_b)
            ta.start()
            tb.start()
            ta.join(300)
            tb.join(300)
            self.assertFalse(ta.is_alive())
            self.assertFalse(tb.is_alive())
            self.assertEqual(errors, {})
            # No cross-contamination: each result matches its own source.
            self.assertEqual(b"".join(results["a"]), raw_a)
            self.assertEqual(b"".join(results["b"]), raw_b)
            assert_no_zombies(self)
        finally:
            os.unlink(pa)
            os.unlink(pb)


if __name__ == "__main__":
    unittest.main()
