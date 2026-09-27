"""F-PORT6: degenerate-input edge parity (P27) + resume no-op/sync (P16).

Bash T/M-series lock empty/single/NUL/huge-line/no-trailing-NL and
M18 (complete-stream resume no-op) / M19 (stale horizon fails
loud); the Python suite covered empty+single only. Byte-exactness
is asserted over joined bytes with order="index" (per-node NUMA
batching varies — never blob identity).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._checkpoint import CheckpointState, write_checkpoint  # noqa: E402

from _helpers import assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _identity(batch):
    return bytes(batch.data)


def _run_case(testcase, payload_bytes, **kw):
    """Write payload_bytes, map identity, assert joined output exact."""
    with tempfile.NamedTemporaryFile(suffix=".bin",
                                     delete=False) as fh:
        path = fh.name
    try:
        with open(path, "wb") as fh:
            fh.write(payload_bytes)
        out = forkrun.map(_identity, path, workers=2, nodes=1,
                          order="index", **kw)
        testcase.assertEqual(b"".join(out), payload_bytes)
        assert_no_zombies(testcase)
    finally:
        os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestDegenerateInputs(unittest.TestCase):
    def test_empty(self):
        _run_case(self, b"")

    def test_single_line(self):
        _run_case(self, b"only\n")

    def test_no_trailing_newline(self):
        _run_case(self, b"no-newline-at-eof")

    def test_nul_laden_lines_mode(self):
        _run_case(self, b"a\0b\0c\ndef\0\n\0\n")

    def test_nul_laden_bytes_mode(self):
        _run_case(self, b"a\0b\0c\ndef\0\n\0\n", bytes=1024)

    def test_huge_single_line(self):
        # T3a shape: 3MB single line (line-scanner stress, not just
        # a 3MB batch through 1MB pipes).
        _run_case(self, b"A" * (3 * 1024 * 1024) + b"\ntail\n")

    def test_huge_single_line_bytes_mode(self):
        _run_case(self, b"A" * (3 * 1024 * 1024) + b"\ntail\n",
                  bytes=1024 * 1024)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestResumeBoundaries(unittest.TestCase):
    def _write_input(self, data):
        fh = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt",
                                         delete=False)
        path = fh.name
        fh.write(data)
        fh.close()
        self.addCleanup(os.unlink, path)
        return path

    def _write_ckpt(self, state):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        write_checkpoint(path, state)
        return path

    def test_m18_complete_stream_is_clean_noop(self):
        # HORIZON == EOF: resumed run commits nothing, returns [], rc clean.
        data = b"".join(b"line %d\n" % i for i in range(100))
        path = self._write_input(data)
        ckpt = self._write_ckpt(CheckpointState(len(data), 0, []))
        out = forkrun.map(_identity, path, workers=2, nodes=1,
                          order="index", orchestrator=True, resume=ckpt)
        self.assertEqual(b"".join(out), b"")
        assert_no_zombies(self)

    def test_m19_stale_horizon_fails_loud(self):
        # HORIZON far beyond EOF: engine resume-sync fails loudly —
        # never a silent short/empty success.
        data = b"".join(b"line %d\n" % i for i in range(100))
        path = self._write_input(data)
        ckpt = self._write_ckpt(CheckpointState(1 << 40, 0, []))
        with self.assertRaises(RuntimeError):
            forkrun.map(_identity, path, workers=2, nodes=1,
                        order="index", orchestrator=True, resume=ckpt)
        assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
