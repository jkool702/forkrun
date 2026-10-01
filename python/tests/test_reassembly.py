"""W-REL6-3.2: ReassemblyBuffer high-water warning (engine-free units).

The poisoned-head path buffers the whole tail by design; the buffer
warns once past the limit (explicit reassembly_limit bytes, else the
dynamic 2x-largest-batch x depth rule; 0/negative or
FORKRUN_REASSEMBLY_LIMIT=0 silences). Byte accounting drains with the
entries (drain/final_drain subtract).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun._reassembly import ReassemblyBuffer  # noqa: E402


class _CaptureFd2:
    """Capture raw fd-2 writes (os.write bypasses sys.stderr)."""

    def __init__(self):
        self.saved = None
        self.path = None
        self._file = None

    def __enter__(self):
        import tempfile
        self.saved = os.dup(2)
        self._file = tempfile.TemporaryFile()
        os.dup2(self._file.fileno(), 2)
        return self

    def __exit__(self, *exc):
        sys.stderr.flush()
        os.dup2(self.saved, 2)
        os.close(self.saved)
        self._file.seek(0)
        self.text = self._file.read().decode("utf-8", "replace")
        self._file.close()
        return False


class TestReassemblyWarning(unittest.TestCase):
    def test_dynamic_warn_fires_once(self):
        buf = ReassemblyBuffer()
        with _CaptureFd2() as cap:
            # Hole at 0; 70 x 1KB blobs behind it trips the dynamic
            # rule (2 x 1KB x 32 = 64KB) exactly once.
            for i in range(1, 71):
                buf.add(i, b"x" * 1024)
                list(buf.drain())
        self.assertIn("reassembly", cap.text)
        self.assertIn("behind batch 0", cap.text)
        self.assertEqual(cap.text.count("reassembly"), 1)
        # max_bytes diagnostic tracks the high water.
        self.assertEqual(buf.max_bytes, 70 * 1024)

    def test_drain_accounting_no_warn_when_flowing(self):
        buf = ReassemblyBuffer()
        with _CaptureFd2() as cap:
            for i in range(200):
                buf.add(i, b"y" * 1024)
                list(buf.drain())
        self.assertEqual(cap.text, "")
        self.assertEqual(buf.max_bytes, 1024)

    def test_explicit_limit(self):
        buf = ReassemblyBuffer(reassembly_limit=4096)
        with _CaptureFd2() as cap:
            for i in range(1, 6):
                buf.add(i, b"z" * 1024)
        self.assertIn("4096 bytes", cap.text)

    def test_zero_limit_silences(self):
        buf = ReassemblyBuffer(reassembly_limit=0)
        with _CaptureFd2() as cap:
            for i in range(1, 200):
                buf.add(i, b"w" * 4096)
        self.assertEqual(cap.text, "")

    def test_env_limit_and_silence(self):
        from unittest import mock as _mock
        with _mock.patch.dict(os.environ,
                              {"FORKRUN_REASSEMBLY_LIMIT": "2048"}):
            buf = ReassemblyBuffer()
            with _CaptureFd2() as cap:
                for i in range(1, 5):
                    buf.add(i, b"v" * 1024)
            self.assertIn("2048 bytes", cap.text)
        with _mock.patch.dict(os.environ,
                              {"FORKRUN_REASSEMBLY_LIMIT": "0"}):
            buf = ReassemblyBuffer()
            with _CaptureFd2() as cap:
                for i in range(1, 200):
                    buf.add(i, b"v" * 4096)
            self.assertEqual(cap.text, "")

    def test_final_drain_empties_accounting(self):
        buf = ReassemblyBuffer(reassembly_limit=10 ** 12)
        for i in range(1, 11):
            buf.add(i, b"q" * 100)
        self.assertEqual(buf.pending, 10)
        got = list(buf.final_drain())
        self.assertEqual(len(got), 10)
        self.assertEqual(buf.pending, 0)
        self.assertEqual(buf._bytes, 0)


if __name__ == "__main__":
    unittest.main()
