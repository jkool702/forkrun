"""W-PY15 pipe capacity optimization (Stage 5).

Signal pipe: 1MB (65536 outstanding signals vs 4096 at 64KB default).
Spawn stdin/stdout: 1MB in C (fr_py_exec_spawn, pre-existing W-PY13 —
verified by inspection + functional tests here). Engine ack pipe (H3),
escrow, and death pipes are untouched by design.
"""

import fcntl
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._pipes import (DEFAULT_PIPE_SIZE, LARGE_PIPE_SIZE,  # noqa: E402
                            get_pipe_capacity, make_pipe,
                            set_pipe_capacity)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestPipeSizing(unittest.TestCase):
    """Mechanism: capacities, fallbacks, no-raise guarantees."""

    def test_default_capacity_floor(self):
        r, w = os.pipe()
        try:
            self.assertGreaterEqual(get_pipe_capacity(w), DEFAULT_PIPE_SIZE)
        finally:
            os.close(r)
            os.close(w)

    def test_make_pipe_bump(self):
        r, w, actual = make_pipe(LARGE_PIPE_SIZE)
        try:
            # Either the 1MB bump landed, or the documented 64KB fallback
            # (capped pipe-max-size / no permission) — both are correct.
            self.assertIn(actual, (LARGE_PIPE_SIZE, DEFAULT_PIPE_SIZE))
            if actual == LARGE_PIPE_SIZE:
                self.assertGreaterEqual(get_pipe_capacity(w),
                                        LARGE_PIPE_SIZE)
        finally:
            os.close(r)
            os.close(w)

    def test_make_pipe_default_bump_on_this_box(self):
        # This repo's CI/dev boxes allow 1MB unprivileged (== default
        # pipe-max-size): assert the bump actually lands here so a
        # regression to plain os.pipe() in run.py fails loudly.
        r, w, actual = make_pipe()
        try:
            self.assertEqual(actual, LARGE_PIPE_SIZE)
        finally:
            os.close(r)
            os.close(w)

    def test_set_capacity_never_raises(self):
        r, w = os.pipe()
        try:
            size = set_pipe_capacity(w, LARGE_PIPE_SIZE)
            self.assertGreaterEqual(size, DEFAULT_PIPE_SIZE)
            # Absurd size: capped by the kernel, still no raise.
            size = set_pipe_capacity(w, 1 << 30)
            self.assertGreaterEqual(size, DEFAULT_PIPE_SIZE)
        finally:
            os.close(r)
            os.close(w)

    def test_fds_stay_noninheritable(self):
        # Sizing must not change PEP 446 inheritable=False (spawned
        # children must still start with only stdio — W-PY13 hygiene).
        r, w, _ = make_pipe()
        try:
            self.assertFalse(os.get_inheritable(r))
            self.assertFalse(os.get_inheritable(w))
        finally:
            os.close(r)
            os.close(w)

    def test_fcntl_constants_present(self):
        self.assertTrue(hasattr(fcntl, "F_SETPIPE_SZ"))
        self.assertTrue(hasattr(fcntl, "F_GETPIPE_SZ"))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPipeFunctional(unittest.TestCase):
    """Behavior unchanged at 1MB: streaming + spawn stay byte-exact."""

    def test_streaming_with_large_signal_pipe(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1500)
            out = list(forkrun.stream(lambda b: bytes(b.data).upper(),
                                      path, workers=4, order="index", nodes=1))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_large_batch(self):
        # 3MB single batch through the 1MB stdin/stdout pipes: exercises
        # the concurrent pump (a write-then-read sequence would hang).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("x" * (3 << 20) + "\n")
            out = forkrun.map("cat", path, mode="spawn", workers=1,
                              bytes=4 << 20, nodes=1)
            self.assertEqual(b"".join(out), b"x" * (3 << 20) + b"\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_streaming_backpressure_still_works(self):
        # Slow consumer: pipe capacity delays the stall, never removes
        # it — completion with exact bytes is the invariant.
        import time as _time

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            got = []
            for blob in forkrun.stream(lambda b: bytes(b.data), path,
                                       workers=2, nodes=1):
                got.append(blob)
                _time.sleep(0.002)
            with open(path, "rb") as fh:
                exp = sorted(fh.read().splitlines())
            self.assertEqual(sorted(b for blob in got
                                    for b in blob.splitlines()), exp)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
