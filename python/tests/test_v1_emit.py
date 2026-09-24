"""W-PY14 C-level output emit: one fr_py_emit call per batch (Stage 5).

Covers the C function directly (framing, signal, edge cases, error
codes) and the worker integration (byte-exact map/stream, None-vs-b"",
fallback, validation preserved). The emit path is auto-selected when
the symbol exists; FORKRUN_NO_V1=1 forces the v0 Python writes.
"""

import ctypes
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get, v1_available  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

_HDR = struct.Struct("<QQ")
_SIG = struct.Struct("<QQ")


def _emit_lib():
    lib = get()
    lib.fr_py_emit.argtypes = [
        ctypes.c_int, ctypes.c_int,
        ctypes.c_uint64, ctypes.c_uint64,
        ctypes.c_char_p, ctypes.c_uint64]
    lib.fr_py_emit.restype = ctypes.c_int
    return lib


def _read_all(fd):
    chunks = []
    while True:
        try:
            c = os.read(fd, 65536)
        except OSError:
            break
        if not c:
            break
        chunks.append(c)
    return b"".join(chunks)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestFrPyEmit(unittest.TestCase):
    """Direct C-level tests: framing, signals, edges, error codes."""

    def test_emit_basic(self):
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 3, 7, b"hello", 5), 0)
            os.close(w)
            w = -1
            os.lseek(out, 0, 0)
            idx, ln = _HDR.unpack(_read_all(out)[:16])
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            self.assertEqual((idx, ln), (7, 5))
            self.assertEqual(raw[16:16 + ln], b"hello")
            sig = os.read(r, 16)
            self.assertEqual(_SIG.unpack(sig), (3, 7))
        finally:
            os.close(out)
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_none_signal_only(self):
        # Payload returned None: no record bytes, signal still sent.
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 1, 8, None, 0), 0)
            os.close(w)
            w = -1
            self.assertEqual(os.fstat(out).st_size, 0)
            self.assertEqual(_SIG.unpack(os.read(r, 16)), (1, 8))
        finally:
            os.close(out)
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_empty_bytes_writes_empty_record(self):
        # b"" is NOT None: v0 emits a len-0 record — preserved.
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 1, 9, b"", 0), 0)
            os.close(w)
            w = -1
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            self.assertEqual(len(raw), 16)
            self.assertEqual((9, 0), _HDR.unpack(raw))
            self.assertEqual(_SIG.unpack(os.read(r, 16)), (1, 9))
        finally:
            os.close(out)
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_no_signal(self):
        # signal_fd=-1 (map/run path): output framed, pipe untouched.
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, -1, 1, 10, b"xy", 2), 0)
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            self.assertEqual(raw, _HDR.pack(10, 2) + b"xy")
            import select
            self.assertEqual(select.select([r], [], [], 0.0)[0], [])
        finally:
            os.close(out)
            os.close(r)
            os.close(w)

    def test_emit_no_output(self):
        # out_fd=-1 (discard path): nothing framed, signal still sent.
        lib = _emit_lib()
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(-1, w, 2, 4, b"zz", 2), 0)
            os.close(w)
            w = -1
            self.assertEqual(_SIG.unpack(os.read(r, 16)), (2, 4))
        finally:
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_large_output(self):
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            big = b"q" * (1 << 20) + b"\n"
            self.assertEqual(lib.fr_py_emit(out, w, 0, 0, big, len(big)), 0)
            os.close(w)
            w = -1
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            idx, ln = _HDR.unpack_from(raw, 0)
            self.assertEqual((idx, ln), (0, len(big)))
            self.assertEqual(raw[16:], big)
        finally:
            os.close(out)
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_output_error(self):
        lib = _emit_lib()
        out = os.memfd_create("e")
        os.close(out)  # bad fd → -1
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 0, 0, b"d", 1), -1)
        finally:
            os.close(r)
            os.close(w)

    def test_emit_signal_error(self):
        # Read end closed, write end open, no reader: EPIPE → -2. (The
        # calling process ignores SIGPIPE — Python sets SIG_IGN at
        # startup — so the write fails loudly instead of killing us.)
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        os.close(r)
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 0, 0, b"d", 1), -2)
        finally:
            os.close(out)
            os.close(w)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerEmitIntegration(unittest.TestCase):
    """End-to-end: the worker's emit path is byte-exact."""

    def test_emit_available(self):
        self.assertTrue(v1_available()["emit"])

    def test_map_upper_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map(lambda b: bytes(b.data).upper(), path,
                              workers=4, order="index", nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_stream_ordered_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1500)
            out = list(forkrun.stream(lambda b: bytes(b.data).upper(),
                                      path, workers=4, order="index",
                                      nodes=1))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_none_vs_empty_preserved(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            self.assertEqual(
                forkrun.map(lambda b: None, path, workers=2, nodes=1),
                [])
            out = forkrun.map(lambda b: b"", path, workers=2,
                              order="index", nodes=1)
            self.assertTrue(out)
            self.assertTrue(all(b == b"" for b in out))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_str_and_memoryview_returns(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            out = forkrun.map(lambda b: "s", path, workers=2,
                              order="index", nodes=1)
            self.assertTrue(all(b == b"s" for b in out))
            out = forkrun.map(lambda b: memoryview(b"m"), path,
                              workers=2, order="index", nodes=1)
            self.assertTrue(all(b == b"m" for b in out))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_bad_return_type_still_poisons(self):
        # _coerce_result validation is preserved on the emit path.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 50)
            out = forkrun.map(lambda b: 42, path, workers=1, nodes=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_emit_fallback_no_v1(self):
        old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertFalse(v1_available()["emit"])
            write_lines(path, 500)
            out = forkrun.map(lambda b: bytes(b.data).upper(), path,
                              workers=2, order="index", nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            if old is None:
                del os.environ["FORKRUN_NO_V1"]
            else:
                os.environ["FORKRUN_NO_V1"] = old
            os.unlink(path)

    def test_spawn_plugin_with_emit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map("cat", path, mode="spawn", workers=2,
                              order="index", nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
