"""W-PY18 addendum: zero-copy ingest + raw window primitives (Stage 5).

fr_py_copy_range: kernel copy with explicit offsets (copy_file_range,
then sendfile; -1 punts to the userspace loop). _spill_to_memfd uses
it first, falls back silently — bytes identical either way.

fr_py_get_raw_window: borrowed MAP_SHARED pointer into the ingress
memfd (the engine's TLS-cached mapping, same as FLAG_RAW delivery).
"""

import ctypes
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get  # noqa: E402
from forkrun.run import _spill_to_memfd  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _lib():
    lib = get()
    lib.fr_py_copy_range.argtypes = [
        ctypes.c_int, ctypes.c_uint64, ctypes.c_int,
        ctypes.c_uint64, ctypes.c_uint64]
    lib.fr_py_copy_range.restype = ctypes.c_int64
    lib.fr_py_get_raw_window.argtypes = [
        ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64]
    lib.fr_py_get_raw_window.restype = ctypes.c_void_p
    return lib


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCopyRange(unittest.TestCase):
    def test_copy_exact(self):
        lib = _lib()
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin",
                                         delete=False) as fh:
            path = fh.name
            fh.write(os.urandom(2 << 20))
        try:
            src = os.open(path, os.O_RDONLY)
            dst = os.memfd_create("t")
            try:
                total, off = 0, 0
                while True:
                    n = lib.fr_py_copy_range(src, off, dst, off,
                                             (2 << 20) - off)
                    self.assertGreaterEqual(n, 0)
                    if n == 0:
                        break
                    total += n
                    off += n
                self.assertEqual(total, 2 << 20)
                os.lseek(dst, 0, 0)
                got = os.read(dst, 2 << 20)
                with open(path, "rb") as fh:
                    self.assertEqual(got, fh.read())
            finally:
                os.close(src)
                os.close(dst)
        finally:
            os.unlink(path)

    def test_copy_offsets(self):
        lib = _lib()
        src = os.memfd_create("s")
        os.write(src, b"abcdefghij")
        dst = os.memfd_create("d")
        try:
            n = lib.fr_py_copy_range(src, 2, dst, 5, 4)
            self.assertEqual(n, 4)
            self.assertEqual(os.pread(dst, 4, 5), b"cdef")
        finally:
            os.close(src)
            os.close(dst)

    def test_copy_eof_and_empty(self):
        lib = _lib()
        src = os.memfd_create("s")
        os.write(src, b"abc")
        dst = os.memfd_create("d")
        try:
            self.assertEqual(lib.fr_py_copy_range(src, 3, dst, 0, 100),
                             0)  # EOF at src_off
            self.assertEqual(lib.fr_py_copy_range(src, 0, dst, 0, 0),
                             0)  # len 0
        finally:
            os.close(src)
            os.close(dst)

    def test_copy_bad_fds(self):
        lib = _lib()
        self.assertEqual(lib.fr_py_copy_range(-1, 0, 2, 0, 10), -1)
        self.assertEqual(lib.fr_py_copy_range(2, 0, -1, 0, 10), -1)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSpillPaths(unittest.TestCase):
    def test_spill_file_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 5000)
            fd = os.open(path, os.O_RDONLY)
            try:
                memfd, size = _spill_to_memfd(fd)
            finally:
                os.close(fd)
            try:
                with open(path, "rb") as fh:
                    exp = fh.read()
                self.assertEqual(size, len(exp))
                self.assertEqual(os.pread(memfd, len(exp), 0), exp)
            finally:
                os.close(memfd)
        finally:
            os.unlink(path)

    def test_spill_pipe_exact(self):
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(r)
                for i in range(1000):
                    os.write(w, ("line %d\n" % i).encode())
            finally:
                try:
                    os.close(w)
                except OSError:
                    pass
                os._exit(0)
        os.close(w)
        try:
            memfd, size = _spill_to_memfd(r)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        try:
            exp = b"".join(("line %d\n" % i).encode()
                           for i in range(1000))
            self.assertEqual(size, len(exp))
            self.assertEqual(os.pread(memfd, len(exp), 0), exp)
        finally:
            os.close(memfd)

    def test_spill_fallback_exact(self):
        # Force the userspace loop (CDLL attribute shadows dlsym).
        lib = get()
        real = lib.fr_py_copy_range
        lib.fr_py_copy_range = lambda *a: -1
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            fd = os.open(path, os.O_RDONLY)
            try:
                memfd, size = _spill_to_memfd(fd)
            finally:
                os.close(fd)
            try:
                with open(path, "rb") as fh:
                    exp = fh.read()
                self.assertEqual(size, len(exp))
                self.assertEqual(os.pread(memfd, len(exp), 0), exp)
            finally:
                os.close(memfd)
            # End-to-end over the fallback path.
            out = forkrun.map(lambda b: bytes(b.data).upper(), path,
                              workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            lib.fr_py_copy_range = real
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestRawWindow(unittest.TestCase):
    def test_window_read(self):
        lib = _lib()
        fd = os.memfd_create("w")
        os.write(fd, b"hello world, raw window")
        try:
            ptr = lib.fr_py_get_raw_window(fd, 6, 5)
            self.assertNotEqual(ptr, None)
            self.assertEqual(ctypes.string_at(ptr, 5), b"world")
            ptr0 = lib.fr_py_get_raw_window(fd, 0, 23)
            self.assertEqual(ctypes.string_at(ptr0, 23),
                             b"hello world, raw window")
        finally:
            os.close(fd)

    def test_window_invalid(self):
        lib = _lib()
        self.assertEqual(lib.fr_py_get_raw_window(-1, 0, 10), None)
        fd = os.memfd_create("w")
        try:
            self.assertEqual(lib.fr_py_get_raw_window(fd, 0, 0), None)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
