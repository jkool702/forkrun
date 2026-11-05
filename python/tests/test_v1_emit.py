"""W-PY14 C-level output emit: one fr_py_emit call per batch (Stage 5).

Covers the C function directly (framing, edge cases, error codes) and
the worker integration (byte-exact map/stream, None-vs-b"", fallback,
validation preserved). The emit path is auto-selected when the symbol
exists; FORKRUN_NO_V1=1 forces the v0 Python writes.

STAGE0: emit and publication are now SEPARATE steps. fr_py_emit writes
the record and deliberately does NOT signal -- publishing before the
commit is the race Stage 0 removes. Notification happens afterwards via
fr_py_notify_committed, which carries the COMMITTED FRONTIER (an
absolute output offset), not a batch index. These tests pin that split:
nothing may appear on the signal pipe until the frontier is published,
and what appears is (wid, offset).
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

from _helpers import ChildLifecycleMixin, assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

# DECISION-02: the record header gained an explicit disposition field.
# The v0 contract this file pins is EXTENDED, not changed: a zero-length
# payload is still a real empty result, and it is now distinguishable from
# "completed with no result" by an explicit tag rather than by absence.
_HDR = struct.Struct("<QQII")   # batch_idx, len, disposition, reserved
_HDR_BYTES = _HDR.size          # was 16
_DISP_DATA = 0
_DISP_NO_RESULT = 1
_SIG = struct.Struct("<QQ")


def _drain_signal(fd, want):
    """Read whatever is available on the signal pipe, up to 16 bytes."""
    import select
    got = b""
    while len(got) < 16:
        r, _, _ = select.select([fd], [], [], want)
        if not r:
            break
        chunk = os.read(fd, 16 - len(got))
        if not chunk:
            break
        got += chunk
    return got


def _emit_lib():
    lib = get()
    lib.fr_py_emit.argtypes = [
        ctypes.c_int, ctypes.c_int,
        ctypes.c_uint64, ctypes.c_uint64,
        ctypes.c_char_p, ctypes.c_uint64]
    lib.fr_py_emit.restype = ctypes.c_int
    # STAGE0: publication is a separate exported entry point.
    lib.fr_py_notify_committed.argtypes = [ctypes.c_int, ctypes.c_int,
                                           ctypes.c_uint64]
    lib.fr_py_notify_committed.restype = ctypes.c_int
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
            # STAGE0: emit alone publishes nothing.
            self.assertEqual(b"", _drain_signal(r, 0))
            # Publication is explicit and carries the committed frontier,
            # which is the output offset -- not the batch index.
            self.assertEqual(lib.fr_py_notify_committed(w, out, 3), 0)
            self.assertEqual((3, _HDR_BYTES + 5),
                             _SIG.unpack(os.read(r, 16)))
            os.close(w)
            w = -1
            os.lseek(out, 0, 0)
            idx, ln, disp, _res = _HDR.unpack(_read_all(out)[:_HDR_BYTES])
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            self.assertEqual((idx, ln), (7, 5))
            self.assertEqual(raw[_HDR_BYTES:_HDR_BYTES + ln], b"hello")
        finally:
            os.close(out)
            os.close(r)
            if w >= 0:
                os.close(w)

    def test_emit_none_signal_only(self):
        # Payload returned None: no record bytes. STAGE0: no signal
        # either -- emit never publishes. The caller publishes the
        # committed frontier, which for a no-output batch equals the
        # previous frontier, so the drain has nothing new to forward.
        lib = _emit_lib()
        out = os.memfd_create("e")
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(out, w, 1, 8, None, 0), 0)
            self.assertEqual(os.fstat(out).st_size, 0)
            self.assertEqual(b"", _drain_signal(r, 0))
            self.assertEqual(lib.fr_py_notify_committed(w, out, 1), 0)
            self.assertEqual((1, 0), _SIG.unpack(os.read(r, 16)))
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
            # STAGE0: still no publication until the frontier is sent.
            self.assertEqual(b"", _drain_signal(r, 0))
            self.assertEqual(lib.fr_py_notify_committed(w, out, 1), 0)
            self.assertEqual((1, _HDR_BYTES), _SIG.unpack(os.read(r, 16)))
            os.close(w)
            w = -1
            os.lseek(out, 0, 0)
            raw = _read_all(out)
            self.assertEqual(len(raw), _HDR_BYTES)
            # b"" is a REAL empty result, so it stays DATA -- NOT
            # NO_RESULT. This is the distinction DECISION-02 exists to
            # preserve: len == 0 was already spoken for.
            self.assertEqual((9, 0, _DISP_DATA, 0), _HDR.unpack(raw))
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
            self.assertEqual(raw, _HDR.pack(10, 2, _DISP_DATA, 0) + b"xy")
            # STAGE0: out_fd < 0 frames nothing and publishes nothing.
            self.assertEqual(b"", _drain_signal(r, 0))
            import select
            self.assertEqual(select.select([r], [], [], 0.0)[0], [])
        finally:
            os.close(out)
            os.close(r)
            os.close(w)

    def test_emit_no_output(self):
        # out_fd=-1 (discard path): nothing framed. STAGE0: nothing
        # published either, and the notifier reports failure because
        # there is no output fd to take a frontier from -- the caller
        # must not treat that as "published successfully".
        lib = _emit_lib()
        r, w = os.pipe()
        try:
            self.assertEqual(lib.fr_py_emit(-1, w, 2, 4, b"zz", 2), 0)
            self.assertEqual(b"", _drain_signal(r, 0))
            # Notifying with no signal fd is a no-op success...
            self.assertEqual(lib.fr_py_notify_committed(-1, -1, 2), 0)
            # ...but asking to publish with no output fd to read a
            # frontier from must NOT report success.
            self.assertNotEqual(lib.fr_py_notify_committed(w, -1, 2), 0)
            self.assertEqual(b"", _drain_signal(r, 0))
            os.close(w)
            w = -1
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
            idx, ln, disp, _res = _HDR.unpack_from(raw, 0)
            self.assertEqual((idx, ln), (0, len(big)))
            self.assertEqual(raw[_HDR_BYTES:], big)
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
            # STAGE0: the signal write moved out of fr_py_emit into
            # fr_py_notify_committed, so this is now a plain success and
            # the failure is reported by the notifier instead.
            self.assertEqual(lib.fr_py_emit(out, w, 0, 0, b"d", 1), 0)
            self.assertNotEqual(lib.fr_py_notify_committed(w, out, 0), 0)
        finally:
            os.close(out)
            os.close(w)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerEmitIntegration(ChildLifecycleMixin, unittest.TestCase):
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
