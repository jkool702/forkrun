"""Stage 0 API-surface tests (validation only — engine lands in Stage 4)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from forkrun._batch import Batch  # noqa: E402


class TestSourceValidation(unittest.TestCase):
    def test_iterable_rejected_with_reason(self):
        with self.assertRaisesRegex(TypeError, "never an input pump"):
            forkrun.run("pkg.mod:func", source=[1, 2, 3])

    def test_generator_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.run("pkg.mod:func", source=(x for x in range(3)))

    def test_path_accepted_shape(self):
        with self.assertRaises(NotImplementedError):
            forkrun.run("pkg.mod:func", source="/tmp/in.txt")

    def test_fd_accepted_shape(self):
        with self.assertRaises(NotImplementedError):
            forkrun.run("pkg.mod:func", source=0)

    def test_pipe_accepted_shape(self):
        r, w = os.pipe()
        try:
            with self.assertRaises(NotImplementedError):
                forkrun.run("pkg.mod:func", source=os.fdopen(r, "rb"))
        finally:
            os.close(w)


class TestOptionValidation(unittest.TestCase):
    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            forkrun.run("p:m", source="f", mode="bogus")

    def test_bad_order(self):
        with self.assertRaises(ValueError):
            forkrun.run("p:m", source="f", order="sorted")

    def test_lines_bytes_exclusive(self):
        with self.assertRaises(ValueError):
            forkrun.run("p:m", source="f", lines=10, bytes=10)

    def test_nonpositive(self):
        with self.assertRaises(ValueError):
            forkrun.run("p:m", source="f", lines=0)

    def test_sink_must_be_callable(self):
        with self.assertRaises(TypeError):
            forkrun.run("p:m", source="f", sink="not-callable")

    def test_wrappers_delegate(self):
        with self.assertRaises(NotImplementedError):
            forkrun.map("p:m", source="f")
        with self.assertRaises(NotImplementedError):
            forkrun.stream("p:m", source="f")


class TestBatchLifetime(unittest.TestCase):
    def test_direct_view_invalidated(self):
        buf = bytearray(b"hello\nworld\n")
        b = Batch(0, 0, len(buf), 2, memoryview(buf))
        self.assertEqual(bytes(b.data), b"hello\nworld\n")
        self.assertEqual(b.copy(), b"hello\nworld\n")
        b.invalidate()
        with self.assertRaises(ValueError):
            b.data
        with self.assertRaises(ValueError):
            b.copy()


if __name__ == "__main__":
    unittest.main()
