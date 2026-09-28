"""W-REL5-B bite lock-ins (Python behavioral correctness).

Bite-then-green: each test FAILS on the pre-fix tree (typo'd kwarg
silently runs / bare taxonomy / blocking poll / unbounded join /
signo-less failure) and PASSES post-fix. Deterministic items ×5,
timing-sensitive (B3/B5) ×10 — see tambura runs in the report.
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


if __name__ == "__main__":
    unittest.main()
