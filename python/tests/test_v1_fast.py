"""W-PY13 v1 fast paths: C-level spawn & plugin dispatch (Stage 5 Phase 5).

Covers fr_py_exec_spawn (posix_spawnp + concurrent splice pump) and
fr_py_plugin_call (frozen 128B forkrun_ctx dispatch), the worker's
v1/v0 selection, and the parent-side use_ctx probe gate. The v1 test
plugin (plugins/test_plugin_v1.c) includes the REAL frozen header, so
the layout test pins ABI unification, not a parallel convention.

Requires cat/tr/grep/false (coreutils) + gcc (plugin compiled here).
"""

import ctypes
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get, v1_available  # noqa: E402
from forkrun._plugin import make_plugin_payload  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "plugins")
PLUGIN_V1_SRC = os.path.join(PLUGINS_DIR, "test_plugin_v1.c")
PLUGIN_V1_SO = os.path.join(PLUGINS_DIR, "test_plugin_v1.so")
PLUGIN_V0_SO = os.path.join(PLUGINS_DIR, "test_plugin.so")


def setUpModule():
    if HAVE_LIB:
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-o", PLUGIN_V1_SO,
             PLUGIN_V1_SRC],
            check=True)


def _v1_spec(func):
    return "%s:%s" % (PLUGIN_V1_SO, func)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestV1Detection(unittest.TestCase):
    def test_v1_available_reports_both(self):
        caps = v1_available()
        self.assertTrue(caps["exec"], "fr_py_exec_spawn missing from .so")
        self.assertTrue(caps["plugin"], "fr_py_plugin_call missing from .so")
        self.assertTrue(caps["emit"], "fr_py_emit missing from .so")

    def test_v1_symbols_exported(self):
        lib = get()
        self.assertTrue(hasattr(lib, "fr_py_exec_spawn"))
        self.assertTrue(hasattr(lib, "fr_py_plugin_call"))

    def test_no_v1_kill_switch(self):
        old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        try:
            caps = v1_available()
            self.assertEqual(caps, {"exec": False, "plugin": False,
                                    "emit": False})
        finally:
            if old is None:
                del os.environ["FORKRUN_NO_V1"]
            else:
                os.environ["FORKRUN_NO_V1"] = old


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSpawnV1(unittest.TestCase):
    def test_spawn_v1_cat_byte_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map("cat", path, mode="spawn", workers=4,
                              order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_transform(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("old dog\nold cat\n")
            out = forkrun.map(["sed", "s/old/new/"], path, mode="spawn",
                              workers=1, order="index")
            self.assertEqual(b"".join(out), b"new dog\nnew cat\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_error_retries_then_continues(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                for i in range(1000):
                    fh.write("MARKER\n" if i == 500 else "line %d\n" % i)
            out = forkrun.map("grep MARKER", path, mode="spawn", workers=1)
            self.assertIn(b"MARKER\n", b"".join(out))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_not_found_poisons_like_v0(self):
        # 127 (shell "command not found") rides retry-then-poison, not
        # fatal — v0 parity (test_spawn.py::not_found case goes v1 now).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            out = forkrun.map("nonexistent_command_xyz_123", path,
                              mode="spawn", workers=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_zero_copy(self):
        # The v1 path never builds a Batch: fail the constructor and the
        # run must still succeed (input stays in the shared memfd).
        import forkrun._worker as worker_mod
        orig = worker_mod.Batch.from_window

        @classmethod
        def _boom(cls, *args, **kwargs):
            raise AssertionError("v1 must not touch Batch")

        worker_mod.Batch.from_window = _boom
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map("cat", path, mode="spawn", workers=2,
                              order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            worker_mod.Batch.from_window = orig
            os.unlink(path)

    def test_spawn_v1_stream_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1500)
            out = list(forkrun.stream("cat", path, mode="spawn", workers=4,
                                      order="index"))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_large_output_no_deadlock(self):
        # One batch >> any pipe buffer, stdout-heavy filter: the pump
        # must feed and drain concurrently (write-then-read would hang).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("x" * (3 << 20) + "\n")
            out = forkrun.map("cat", path, mode="spawn", workers=1,
                              bytes=4 << 20)
            self.assertEqual(b"".join(out), b"x" * (3 << 20) + b"\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_child_fd_hygiene(self):
        # A spawned child must start with ONLY stdio (0/1/2): the shim
        # addclose()s the pipes + memfds in the spawn actions and the
        # worker marks everything else CLOEXEC (v1 analogue of v0's
        # subprocess close_fds=True). Entry 3 is ls's own /proc/self/fd
        # dir fd. Any engine/signal/memfd leak would show up here.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 20)
            out = forkrun.map(["ls", "/proc/self/fd"], path, mode="spawn",
                              workers=2, order="index")
            for blob in out:
                self.assertEqual(sorted(blob.decode().split()),
                                 ["0", "1", "2", "3"])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_v1_fallback_no_v1(self):
        # Kill switch forces the v0 subprocess path: same bytes out.
        old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map("cat", path, mode="spawn", workers=2,
                              order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            if old is None:
                del os.environ["FORKRUN_NO_V1"]
            else:
                os.environ["FORKRUN_NO_V1"] = old
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPluginV1(unittest.TestCase):
    def test_plugin_v1_frozen_abi_layout(self):
        # The .so must export dialect 2 + FLAG_RAW (2 | 1<<8 == 258);
        # the layout pin itself lives in C (_Static_assert == 128).
        lib = ctypes.CDLL(PLUGIN_V1_SO)
        use_ctx = ctypes.c_int.in_dll(lib, "forkrun_use_ctx").value
        self.assertEqual(use_ctx, 258)
        self.assertEqual(use_ctx & 0xFF, 2)

    def test_plugin_probe_tags(self):
        v1 = make_plugin_payload(PLUGIN_V1_SO, "process_v1")
        self.assertTrue(v1._forkrun_plugin_v1)
        v0 = make_plugin_payload(PLUGIN_V0_SO, "process")
        self.assertFalse(v0._forkrun_plugin_v1)

    def test_plugin_v1_basic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map(_v1_spec("process_v1"), path, mode="plugin",
                              workers=4, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_v1_ctx_identity(self):
        # identify_v1 echoes idx/kills through the REAL ctx fields.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 8, fmt="row %d\n")
            out = forkrun.map(_v1_spec("identify_v1"), path, mode="plugin",
                              workers=2, lines=1, order="index")
            idxs = sorted(int(m.group(1)) for m in
                          (re.match(rb"idx=(\d+) kills=0\n", b) for b in out)
                          if m)
            self.assertEqual(idxs, [0, 1, 2, 3, 4, 5, 6, 7])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_v1_error_poisons(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            out = forkrun.map(_v1_spec("always_fail_v1"), path,
                              mode="plugin", workers=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_v1_v0_convention_untouched(self):
        # The 72B v0 plugin (no forkrun_use_ctx) stays on ctypes: exact
        # bytes, no v1 misdispatch.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map("%s:process" % PLUGIN_V0_SO, path,
                              mode="plugin", workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_v1_zero_copy(self):
        import forkrun._worker as worker_mod
        orig = worker_mod.Batch.from_window

        @classmethod
        def _boom(cls, *args, **kwargs):
            raise AssertionError("v1 must not touch Batch")

        worker_mod.Batch.from_window = _boom
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map(_v1_spec("process_v1"), path, mode="plugin",
                              workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            worker_mod.Batch.from_window = orig
            os.unlink(path)

    def test_plugin_v1_stream_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1500)
            out = list(forkrun.stream(_v1_spec("process_v1"), path,
                                      mode="plugin", workers=4,
                                      order="index"))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_plugin_v1_fallback_no_v1(self):
        # v1 .so through the v0 path is NOT supported (conventions
        # differ) — but the kill switch on a v0 .so must stay exact.
        old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map("%s:process" % PLUGIN_V0_SO, path,
                              mode="plugin", workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            if old is None:
                del os.environ["FORKRUN_NO_V1"]
            else:
                os.environ["FORKRUN_NO_V1"] = old
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
