"""W-PY18 mode="splice": kernel passthrough via the C loop (Stage 5).

Splice workers run claim→sendfile→signal→ack entirely in C (zero
Python per batch) over byte-mode batches. Framing is the unchanged
[batch_idx u64][len u64][bytes] emitter format, so the parent parses
untouched. Payload must be None (an ignored payload would silently
drop user code); lines=N rejected (boundaries never detected);
run() rejected (passthrough produces output).
"""

import os
import sys
import tempfile
import time
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


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSpliceValidation(unittest.TestCase):
    """Eager, engine-free validation."""

    def test_splice_symbol_present(self):
        self.assertTrue(v1_available()["splice"])
        self.assertTrue(hasattr(get(), "fr_py_worker_splice_loop"))

    def test_payload_required_absent(self):
        for bad in (lambda b: b, "cmd", ["a"], 42):
            with self.assertRaises(ValueError, msg=repr(bad)):
                forkrun.map(bad, "f.txt", mode="splice")

    def test_lines_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.map(None, "f.txt", mode="splice", lines=100)

    def test_run_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.run(None, "f.txt", mode="splice")

    def test_sink_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.run(None, "f.txt", mode="splice",
                        sink=lambda m, r: None)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSpliceMode(unittest.TestCase):
    def test_splice_basic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("hello\nworld\n" * 100)
            out = forkrun.map(None, path, mode="splice", bytes=4096,
                              workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_binary_exact(self):
        data = os.urandom(1024 * 1024)
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin",
                                         delete=False) as fh:
            path = fh.name
            fh.write(data)
        try:
            out = forkrun.map(None, path, mode="splice",
                              bytes=512 * 1024, workers=4,
                              order="index")
            self.assertEqual(b"".join(out), data)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(
                forkrun.map(None, path, mode="splice", bytes=4096,
                            workers=1), [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_default_bytes(self):
        # bytes=N omitted → 512KB default (bash -b default).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map(None, path, mode="splice", workers=2,
                              order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_with_stream(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 3000)
            out = list(forkrun.stream(None, path, mode="splice",
                                      bytes=64 * 1024, workers=2,
                                      order="index"))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_stream_unordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 3000)
            out = list(forkrun.stream(None, path, mode="splice",
                                      bytes=64 * 1024, workers=2))
            # Byte windows are order-free chunks: compare as a multiset
            # of lines (newlines may split across windows).
            with open(path, "rb") as fh:
                exp = sorted(fh.read().splitlines())
            self.assertEqual(sorted(b"".join(out).splitlines()), exp)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_streaming_ingest(self):
        # Unbounded-style ingest + passthrough (bash -s shape).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            out = forkrun.map(None, path, mode="splice",
                              bytes=64 * 1024, workers=2, order="index",
                              streaming=True)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_splice_pipe_source(self):
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(r)
                for i in range(500):
                    os.write(w, ("line %d\n" % i).encode())
            finally:
                try:
                    os.close(w)
                except OSError:
                    pass
                os._exit(0)
        os.close(w)
        try:
            out = forkrun.map(None, r, mode="splice", bytes=16384,
                              workers=2, order="index")
            got = sorted(b for blob in out for b in blob.splitlines())
            exp = sorted(("line %d" % i).encode() for i in range(500))
            self.assertEqual(got, exp)
            os.waitpid(pid, 0)
            assert_no_zombies(self)
        finally:
            os.close(r)

    def test_splice_faster_than_python_passthrough(self):
        # Same bytes moved both ways; the C loop must not lose to the
        # Python loop (margin 0.9× guards machine noise — measures
        # non-regression, not a speedup ratio).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 20000, fmt="line %06d padding data\n")
            t0 = time.perf_counter()
            ref = forkrun.map(lambda b: bytes(b.data), path, workers=4,
                              order="index")
            t_py = time.perf_counter() - t0
            t0 = time.perf_counter()
            got = forkrun.map(None, path, mode="splice",
                              bytes=256 * 1024, workers=4,
                              order="index")
            t_sp = time.perf_counter() - t0
            self.assertEqual(b"".join(got), b"".join(ref))
            self.assertLess(t_sp, t_py / 0.9,
                            "splice slower than Python passthrough: "
                            "%.3fs vs %.3fs" % (t_sp, t_py))
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
