"""W-PY9 Mode 3 (plugin): C callbacks via ctypes (Stage 5 Phase 4).

The test plugin is compiled at test time (setUpModule); the .so is
gitignored. Layout pinning is two-sided: C _Static_asserts in
test_plugin.c + exact ctypes offsets here. Either side drifting fails
its own suite loudly.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._plugin import (ForkrunCtx, PluginError,  # noqa: E402
                             load_plugin)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "plugins")
PLUGIN_SRC = os.path.join(PLUGINS_DIR, "test_plugin.c")
PLUGIN_SO = os.path.join(PLUGINS_DIR, "test_plugin.so")


def setUpModule():
    proc = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", PLUGIN_SO, PLUGIN_SRC],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise AssertionError(
            "test plugin build failed:\n%s" % proc.stderr)


class TestPluginLoading(unittest.TestCase):
    def test_load_valid_plugin(self):
        lib, func = load_plugin(PLUGIN_SO, "process")
        self.assertIsNotNone(lib)
        self.assertIsNotNone(func)
        self.assertEqual(func.restype, ctypes.c_int)

    def test_load_missing_file(self):
        with self.assertRaises(PluginError):
            load_plugin("/nonexistent/path_xyz.so", "func")

    def test_load_missing_function(self):
        with self.assertRaises(PluginError):
            load_plugin(PLUGIN_SO, "nonexistent_function_xyz")

    def test_load_not_a_so(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            path = fh.name
        try:
            with open(path, "wb") as fh:
                fh.write(b"not a shared library")
            with self.assertRaises(PluginError):
                load_plugin(path, "func")
        finally:
            os.unlink(path)


class TestPluginLayout(unittest.TestCase):
    """Two-sided pin: exact offsets + total (C asserts mirror these)."""

    EXPECTED = {
        "data": (0, 8), "data_len": (8, 8), "batch_idx": (16, 8),
        "flags": (24, 4), "_pad0": (28, 4), "out_buf": (32, 8),
        "out_len": (40, 8), "out_written": (48, 8),
        "line_count": (56, 8), "user_data": (64, 8),
    }

    def test_exact_layout(self):
        self.assertEqual(ctypes.sizeof(ForkrunCtx), 72)
        for name, (off, _size) in self.EXPECTED.items():
            self.assertEqual(getattr(ForkrunCtx, name).offset, off, name)
        # No fryer: total covered exactly, alignment 8.
        self.assertEqual(ctypes.alignment(ForkrunCtx), 8)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPluginMode(unittest.TestCase):
    def _spec(self, fn):
        return "%s:%s" % (PLUGIN_SO, fn)

    def test_basic_plugin(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("hello world\nmixed CASE\n")
            out = forkrun.map(self._spec("process"), path, mode="plugin",
                              workers=2, order="index")
            self.assertEqual(b"".join(out), b"HELLO WORLD\nMIXED CASE\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_batch_index(self):
        # identify() echoes the ctx batch_idx the worker populated:
        # indices must be exactly 0..N-1 (claim sequence, no gaps here).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map(self._spec("identify"), path, mode="plugin",
                              workers=4, order="index")
            idxs = [int(rec.split(b"=", 1)[1]) for rec in out]
            self.assertEqual(idxs, list(range(len(out))))
            self.assertGreater(len(out), 1)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_error_retries_then_poisons(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 300)
            out = forkrun.map(self._spec("always_fail"), path,
                              mode="plugin", workers=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_callable_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.run(lambda b: None, "f.txt", mode="plugin")
        with self.assertRaises(ValueError):
            forkrun.map(lambda b: None, "f.txt", mode="plugin")

    def test_plugin_bad_format_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.run("no_colon_here", "f.txt", mode="plugin")
        with self.assertRaises(ValueError):
            forkrun.run(":nofunc", "f.txt", mode="plugin")
        with self.assertRaises(ValueError):
            forkrun.run(12345, "f.txt", mode="plugin")

    def test_plugin_empty_input(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(forkrun.map(self._spec("process"), path,
                                         mode="plugin", workers=2), [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_with_stream(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            out = list(forkrun.stream(self._spec("process"), path,
                                      mode="plugin", workers=2))
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(sorted(b"".join(out).splitlines()),
                             sorted(raw.upper().splitlines()))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            streamed = list(forkrun.stream(
                self._spec("process"), path, mode="plugin", workers=2,
                order="index"))
            mapped = forkrun.map(self._spec("process"), path,
                                 mode="plugin", workers=2, order="index")
            self.assertEqual(streamed, mapped)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(streamed), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_buffer_boundary_exact(self):
        # Engine byte-mode batches clamp to min(L2, 1MB) == the v0 output
        # buffer size, so data_len == out_len must SUCCEED (the plugin's
        # -2 arm is strict `n > out_len`; defense-in-depth only —
        # oversize is unreachable via engine batching). 3MB / 1MB batches.
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "wb") as fh:
                fh.write(b"q" * (3 * 1024 * 1024))
            out = forkrun.map(self._spec("process"), path, mode="plugin",
                              workers=1, bytes=1024 * 1024, order="index")
            self.assertEqual(b"".join(out), b"Q" * (3 * 1024 * 1024))
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
