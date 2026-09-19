"""Stage 0 API-surface tests (validation only — engine lands in Stage 4).

Validation-shape tests assert against _validate_config directly (engine-free:
they pass with or without libforkrun_python.so). Rejection tests go through
forkrun.run (validation raises before any engine contact). Engine behavior
lives in test_v0.py.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from forkrun._batch import Batch  # noqa: E402

_DEFAULTS = dict(mode="python", sink=None, order="none", lines=None,
                 bytes_=None, workers=None, nodes="auto", on_error="retry")


class TestSourceValidation(unittest.TestCase):
    def test_iterable_rejected_with_reason(self):
        with self.assertRaisesRegex(TypeError, "never an input pump"):
            forkrun.run("pkg.mod:func", source=[1, 2, 3])

    def test_generator_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.run("pkg.mod:func", source=(x for x in range(3)))

    def test_path_accepted_shape(self):
        cfg = forkrun._validate_config("pkg.mod:func", "/tmp/in.txt",
                                       **_DEFAULTS)
        self.assertEqual(cfg.source, "/tmp/in.txt")

    def test_fd_accepted_shape(self):
        cfg = forkrun._validate_config("pkg.mod:func", 0, **_DEFAULTS)
        self.assertEqual(cfg.source, 0)

    def test_pipe_accepted_shape(self):
        r, w = os.pipe()
        try:
            with os.fdopen(r, "rb") as reader:
                cfg = forkrun._validate_config("pkg.mod:func", reader,
                                               **_DEFAULTS)
                self.assertIs(cfg.source, reader)
        finally:
            os.close(w)

    def test_bool_rejected(self):
        # bool is an int subclass: True would otherwise pass as fd 1.
        with self.assertRaisesRegex(TypeError, "bool is an int subclass"):
            forkrun.run("pkg.mod:func", source=True)
        with self.assertRaisesRegex(TypeError, "bool is an int subclass"):
            forkrun.run("pkg.mod:func", source=False)

    def test_negative_fd_rejected(self):
        with self.assertRaisesRegex(TypeError, "must be non-negative"):
            forkrun.run("pkg.mod:func", source=-1)


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
        # Delegation proven engine-free: invalid options raise through the
        # wrappers' shared validation path (map/stream validate like run).
        with self.assertRaises(ValueError):
            forkrun.map("p:m", source="f", mode="bogus")
        with self.assertRaises(ValueError):
            forkrun.stream("p:m", source="f", order="sorted")

    def test_v0_mode_gate(self):
        # v0 implements mode="python" only; spawn/plugin stage before any
        # engine contact (needs only a real-enough source path).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as fh:
            fh.write("a\n")
            fh.flush()
            with self.assertRaises(NotImplementedError):
                forkrun.run("p:m", source=fh.name, mode="spawn")
            with self.assertRaises(NotImplementedError):
                forkrun.run("p:m", source=fh.name, mode="plugin")


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
