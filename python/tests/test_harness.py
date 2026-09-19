"""W-PY4.e K-Analogue harness self-test (Stage 4 Phase 3).

Meta-tests: if THESE helpers lie, the main suites lie. Verifies the
emitter framing codec, the record parser (including truncated-tail
behavior), and the fd-counting helper used across the robustness suites.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun.run import _HDR, _parse_records  # noqa: E402

from _helpers import nfd  # noqa: E402


class TestFramingCodec(unittest.TestCase):
    def test_hdr_round_trip(self):
        packed = _HDR.pack(12345, 67)
        idx, ln = _HDR.unpack_from(packed, 0)
        self.assertEqual((idx, ln), (12345, 67))
        self.assertEqual(_HDR.size, 16)

    def test_parse_records_exact(self):
        blob = (_HDR.pack(2, 3) + b"abc"
                + _HDR.pack(0, 0)
                + _HDR.pack(1, 5) + b"hello")
        recs = _parse_records(blob)
        self.assertEqual(recs, [(2, b"abc"), (0, b""), (1, b"hello")])

    def test_parse_records_drops_truncated_tail(self):
        # A complete record followed by a header claiming 10 bytes with
        # only 3 present (dead worker's partial write): the tail is
        # dropped — waitpid already raised before parsing runs.
        blob = _HDR.pack(5, 2) + b"ok" + _HDR.pack(6, 10) + b"abc"
        self.assertEqual(_parse_records(blob), [(5, b"ok")])
        # Truncated header alone is also dropped, not raised.
        self.assertEqual(_parse_records(b"\x01\x02"), [])

    def test_parse_records_empty(self):
        self.assertEqual(_parse_records(b""), [])

    def test_parse_catches_corruption(self):
        # Deliberately wrong expectation: proves the helper discriminates
        # (a comparator that always passes is worse than none).
        blob = _HDR.pack(0, 3) + b"abc"
        self.assertNotEqual(_parse_records(blob), [(0, b"abd")])


class TestFdHelper(unittest.TestCase):
    def test_fd_count_tracks_opens(self):
        base = nfd()
        fds = [os.open("/dev/null", os.O_RDONLY) for _ in range(7)]
        try:
            self.assertEqual(nfd(), base + 7)
        finally:
            for fd in fds:
                os.close(fd)
        self.assertEqual(nfd(), base)

    def test_fd_count_tracks_memfd(self):
        base = nfd()
        try:
            m = os.memfd_create("selftest")
        except AttributeError:
            self.skipTest("no os.memfd_create")
            return
        try:
            self.assertEqual(nfd(), base + 1)
        finally:
            os.close(m)
        self.assertEqual(nfd(), base)


if __name__ == "__main__":
    unittest.main()
