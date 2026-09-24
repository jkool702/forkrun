"""W-PY33 C worker loop: zero-Python-per-batch spawn path (Stage 5).

fr_py_worker_spawn_loop owns claim → posix_spawnp → signal → ack in
C — the spawn analogue of the W-PY26 plugin loop. Results are
byte-identical to the Python worker loop on every path (plain,
ordered, reactor); error semantics (retry/skip/fail-fast, poison,
sentinel) match _worker.py; the flag is gated to its supported
envelope (map, mode="spawn", UMA, materialized) and raises loudly
elsewhere. Output is capture-then-framed (never direct-to-memfd —
the v0 emitter contract needs the true length up front), so large
batches cannot deadlock.

No threads anywhere (fork-before-threads stays intact).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, v1_available  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _has_loop():
    if not HAVE_LIB:
        return False
    try:
        return bool(v1_available().get("spawn_loop"))
    except Exception:
        return False


def _make_input(n=300, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


class TestCSpawnLoopValidation(unittest.TestCase):
    """Eager validation of the c_spawn_loop flag (engine-free shape)."""

    def test_bad_flag_rejected(self):
        for bad in ("yes", 1, 0, [], {}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                forkrun.map("cat", "f.txt", mode="spawn",
                            c_spawn_loop=bad)

    def test_non_spawn_mode_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.map(lambda b: b"x", "f.txt", c_spawn_loop=True)

    def test_run_rejected(self):
        # run() takes no c_spawn_loop parameter at all (map-only
        # flag) — unexpected keyword is a TypeError.
        with self.assertRaises(TypeError):
            forkrun.run("cat", "f.txt", mode="spawn",
                        c_spawn_loop=True)

    def test_stream_rejected(self):
        # stream() validates eagerly (raises on call, before next()).
        with self.assertRaises(RuntimeError):
            forkrun.stream("cat", "f.txt", mode="spawn",
                           c_spawn_loop=True)

    def test_numa_rejected(self):
        with self.assertRaises(RuntimeError):
            forkrun.map("cat", "f.txt", mode="spawn",
                        c_spawn_loop=True, nodes="@2")


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestCSpawnLoopParity(unittest.TestCase):
    """Byte-identical results to the Python worker loop."""

    def setUp(self):
        if not _has_loop():
            self.skipTest("fr_py_worker_spawn_loop absent — rebuild")

    def tearDown(self):
        assert_no_zombies(self)

    def _both(self, payload, path, **kw):
        a = forkrun.map(payload, path, mode="spawn", **kw)
        b = forkrun.map(payload, path, mode="spawn", c_spawn_loop=True,
                        **kw)
        return a, b

    def test_plain_none_identical(self):
        path = _make_input()
        try:
            a, b = self._both("tr a-z A-Z", path, workers=2)
            self.assertEqual(sorted(a), sorted(b))
        finally:
            os.unlink(path)

    def test_plain_index_identical(self):
        path = _make_input()
        try:
            a, b = self._both("tr a-z A-Z", path, workers=2,
                              order="index")
            self.assertEqual(a, b)
        finally:
            os.unlink(path)

    def test_reactor_index_identical(self):
        path = _make_input(1500)
        try:
            a, b = self._both("tr a-z A-Z", path, workers=4,
                              orchestrator=True, order="index")
            self.assertEqual(a, b)
        finally:
            os.unlink(path)

    def test_large_batch_no_deadlock(self):
        """Batches >> 64KB pipe buffer complete identically (the
        capture-memfd design never blocks on output)."""
        path = _make_input(3000)
        try:
            a, b = self._both("cat", path, workers=2,
                              bytes=256 * 1024, order="index")
            self.assertEqual(a, b)
            self.assertGreater(len(a), 0)
        finally:
            os.unlink(path)

    def test_fail_retry_poison_parity(self):
        """Always-failing command: bounded retries then poison-skip
        on both paths (completed run, empty results)."""
        path = _make_input(120)
        try:
            a = forkrun.map("false", path, mode="spawn", workers=1)
            b = forkrun.map("false", path, mode="spawn", workers=1,
                            c_spawn_loop=True)
            self.assertEqual(a, b)
            self.assertEqual(a, [])
        finally:
            os.unlink(path)

    def test_fail_skip_parity(self):
        path = _make_input(120)
        try:
            a = forkrun.map("false", path, mode="spawn", workers=1,
                            on_error="skip")
            b = forkrun.map("false", path, mode="spawn", workers=1,
                            on_error="skip", c_spawn_loop=True)
            self.assertEqual(a, b)
            self.assertEqual(a, [])
        finally:
            os.unlink(path)

    def test_fail_fast_raises_both(self):
        path = _make_input(120)
        try:
            with self.assertRaises(RuntimeError):
                forkrun.map("false", path, mode="spawn", workers=1,
                            on_error="fail-fast")
            with self.assertRaises(RuntimeError):
                forkrun.map("false", path, mode="spawn", workers=1,
                            on_error="fail-fast", c_spawn_loop=True)
        finally:
            os.unlink(path)

    def test_kill_recovery_parity(self):
        """A spawn command that SIGKILLs its worker parent once, then
        behaves as cat: parent-side WorkerTxn recovery heals the C
        loop with byte-exact output (same as the Python loop)."""
        path = _make_input(1500)
        tmpdir = tempfile.mkdtemp(prefix="w33skill_")
        marker = os.path.join(tmpdir, "dead")
        # $PPID of the spawned command is the C-loop worker itself.
        cmd = ["sh", "-c",
               "if [ ! -e %s ]; then touch %s; kill -9 $PPID; fi; "
               "cat" % (marker, marker)]
        try:
            res = forkrun.map(cmd, path, mode="spawn", workers=2,
                              orchestrator=True, order="index",
                              c_spawn_loop=True)
            healthy = forkrun.map("cat", path, mode="spawn",
                                  workers=2, order="index")
            self.assertEqual(res, healthy)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
