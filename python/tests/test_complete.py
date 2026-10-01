"""W-PY21-B frontend datapath consolidation (Stage 5).

Batch commit primitive (fr_py_complete = fr_py_emit + fr_py_ack_direct),
C sequential spill for non-seekable sources, and C descriptor parsing
for the map() collect path. Lock-in is byte-identity: every new path
produces exactly what the legacy Python path produced.

Conventions: top-level payload fns (fork-safe), assert_no_zombies,
skip cleanly when the .so is missing. FORKRUN_NO_V1 selects the
legacy split path (Python signal + argv ack + Python parse) as the
differential baseline — same tests, both settings, identical results.
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
from forkrun.run import _parse_records_c, _spill_to_memfd  # noqa: E402
from forkrun.run import _split_records  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

_HDR = struct.Struct("<QQ")


def _up(batch):
    return bytes(batch.data).upper()


def _none(batch):
    return None


def _empty(batch):
    return b""


def _fail_twice_factory():
    # Fork-safe failure needs process-local state: use a file flag.
    # Simpler deterministic fault: fail on a marked record content.
    def _fail(batch):
        data = bytes(batch.data)
        if b"POISON-ME" in data:
            raise RuntimeError("marked batch fails")
        return data
    return _fail


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _lines(res):
    return sorted(b"".join(res).splitlines())


class _LegacyPath:
    """Context manager selecting the pre-W-PY21-B split path."""

    def __enter__(self):
        self._old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("FORKRUN_NO_V1", None)
        else:
            os.environ["FORKRUN_NO_V1"] = self._old
        return False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCompleteSymbols(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_symbols_present(self):
        lib = get()
        for sym in ("fr_py_ack_direct", "fr_py_complete",
                    "fr_py_spill_sequential", "fr_py_parse_descriptors"):
            self.assertTrue(hasattr(lib, sym), sym)
        caps = v1_available()
        for key in ("ack_direct", "complete", "spill", "parse"):
            self.assertTrue(caps.get(key), key)

    def test_no_v1_masks_new_paths(self):
        with _LegacyPath():
            caps = v1_available()
            for key in ("ack_direct", "complete", "spill", "parse"):
                self.assertFalse(caps.get(key), key)

    def test_no_thread_check_in_hot_path(self):
        # Checklist item: threading.active_count() deleted, not moved.
        import forkrun._worker as worker_mod

        path = worker_mod.__file__
        with open(path) as fh:
            src = fh.read()
        self.assertNotIn("active_count", src)
        self.assertNotIn("import threading", src)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCompleteReturnCodes(unittest.TestCase):
    """fr_py_complete codes without engine state (returns before ack)."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_output_failure_is_minus_one(self):
        lib = get()
        if not hasattr(lib, "fr_py_complete"):
            self.skipTest("fr_py_complete missing")
        fd = os.open("/dev/null", os.O_WRONLY)
        os.close(fd)  # writev(closed) -> EBADF, before signal/ack
        rc = lib.fr_py_complete(-1, 0, 0, -1, fd, b"xyz", 3)
        self.assertEqual(rc, -1)

    def test_signal_failure_is_minus_two(self):
        lib = get()
        if not hasattr(lib, "fr_py_complete"):
            self.skipTest("fr_py_complete missing")
        r, w = os.pipe()
        os.close(r)  # write end -> EPIPE (SIGPIPE is SIG_IGN here)
        try:
            rc = lib.fr_py_complete(w, 0, 0, -1, -1, None, 0)
        finally:
            os.close(w)
        self.assertEqual(rc, -2)

    def test_ack_without_state_is_minus_three(self):
        lib = get()
        if not hasattr(lib, "fr_py_complete"):
            self.skipTest("fr_py_complete missing")
        # No output, no signal: reaches ack with NULL engine state.
        rc = lib.fr_py_complete(-1, 0, 0, -1, -1, None, 0)
        self.assertEqual(rc, -3)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestDescriptorParsing(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def _blob(self, sizes, tail=b""):
        parts = []
        for i, s in enumerate(sizes):
            parts.append(_HDR.pack(i, s) + b"x" * s)
        return b"".join(parts) + tail

    def test_parity_basic(self):
        blob = self._blob([0, 1, 7, 100, 4096, 0, 13])
        self.assertEqual(_parse_records_c(blob),
                         _split_records(blob)[0])

    def test_parity_truncated_tail(self):
        blob = self._blob([5, 10]) + _HDR.pack(2, 100) + b"short"
        self.assertEqual(_parse_records_c(blob),
                         _split_records(blob)[0])

    def test_parity_short_header(self):
        blob = self._blob([3]) + b"\x01\x02\x03"
        self.assertEqual(_parse_records_c(blob),
                         _split_records(blob)[0])

    def test_empty(self):
        self.assertEqual(_parse_records_c(b""), [])

    def test_raw_descriptor_boundaries(self):
        from forkrun._bindings import RecordDescriptor as RD

        lib = get()
        if not hasattr(lib, "fr_py_parse_descriptors"):
            self.skipTest("fr_py_parse_descriptors missing")
        blob = self._blob([4, 0, 9])
        arr = (RD * 8)()
        cnt = lib.fr_py_parse_descriptors(blob, len(blob), arr, 8)
        self.assertEqual(cnt, 3)
        self.assertEqual(
            [(arr[i].batch_idx, arr[i].offset, arr[i].length)
             for i in range(cnt)],
            [(0, 16, 4), (1, 36, 0), (2, 52, 9)])

    def test_max_bound_truncates_descriptors_not_input(self):
        from forkrun._bindings import RecordDescriptor as RD

        lib = get()
        if not hasattr(lib, "fr_py_parse_descriptors"):
            self.skipTest("fr_py_parse_descriptors missing")
        blob = self._blob([1, 2, 3, 4])
        arr = (RD * 2)()
        cnt = lib.fr_py_parse_descriptors(blob, len(blob), arr, 2)
        self.assertEqual(cnt, 2)  # filled before input consumed

    def test_bad_args(self):
        lib = get()
        if not hasattr(lib, "fr_py_parse_descriptors"):
            self.skipTest("fr_py_parse_descriptors missing")
        self.assertEqual(
            lib.fr_py_parse_descriptors(None, 10, None, 0), -1)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSequentialSpill(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_pipe_source_parity(self):
        # Single write under the 64KB pipe capacity (no reader yet —
        # a bigger write would block; large-pipe coverage comes from
        # the streaming suite's live-writer tests).
        data = b"".join(b"pipe line %d\n" % i for i in range(500))
        r, w = os.pipe()
        try:
            os.write(w, data)
        finally:
            os.close(w)
        try:
            memfd, size = _spill_to_memfd(r)
        finally:
            os.close(r)
        try:
            self.assertEqual(size, len(data))
            os.lseek(memfd, 0, os.SEEK_SET)
            got = b""
            while True:
                chunk = os.read(memfd, 1 << 20)
                if not chunk:
                    break
                got += chunk
            self.assertEqual(got, data)
        finally:
            os.close(memfd)

    def test_file_source_parity(self):
        path = _make_input(n=3000)
        try:
            with open(path, "rb") as fh:
                expect = fh.read()
            src = os.open(path, os.O_RDONLY)
            try:
                memfd, size = _spill_to_memfd(src)
            finally:
                os.close(src)
            try:
                self.assertEqual(size, len(expect))
                got = os.pread(memfd, len(expect), 0)
                self.assertEqual(got, expect)
            finally:
                os.close(memfd)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCompleteParity(unittest.TestCase):
    """Same workload, legacy vs commit path: byte-identical results."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_map_unordered_parity(self):
        path = _make_input()
        try:
            with _LegacyPath():
                old = forkrun.map(_up, path, workers=4, nodes=1)
            new = forkrun.map(_up, path, workers=4, nodes=1)
            self.assertEqual(_lines(old), _lines(new))
            with open(path, "rb") as fh:
                expect = fh.read().upper()
            self.assertEqual(_lines(new), _lines([expect]))
        finally:
            os.unlink(path)

    def test_map_ordered_parity(self):
        path = _make_input()
        try:
            with _LegacyPath():
                old = forkrun.map(_up, path, workers=4, order="index",
                                  nodes=1)
            new = forkrun.map(_up, path, workers=4, order="index",
                              nodes=1)
            # Split-agnostic parity: adaptive batching is race-dependent
            # (pre-flight overlap sets L per run), so blob counts/splits
            # legitimately differ run to run. Joined bytes are the
            # invariant — never compare blob identity across runs.
            self.assertEqual(b"".join(old), b"".join(new))
            flat = b"".join(new)
            with open(path, "rb") as fh:
                self.assertEqual(flat, fh.read().upper())
        finally:
            os.unlink(path)

    def test_none_and_empty_output_parity(self):
        path = _make_input(n=500)
        try:
            with _LegacyPath():
                old_none = forkrun.map(_none, path, workers=2, nodes=1)
                old_empty = forkrun.map(_empty, path, workers=2, nodes=1)
            new_none = forkrun.map(_none, path, workers=2, nodes=1)
            new_empty = forkrun.map(_empty, path, workers=2, nodes=1)
            self.assertEqual(old_none, new_none)
            self.assertEqual(old_empty, new_empty)
        finally:
            os.unlink(path)

    def test_streaming_fallow_parity(self):
        path = _make_input()
        try:
            with _LegacyPath():
                old = sorted(forkrun.stream(_up, path, workers=4,
                                            streaming=True, nodes=1))
            new = sorted(forkrun.stream(_up, path, workers=4,
                                        streaming=True, nodes=1))
            self.assertEqual(old, new)
        finally:
            os.unlink(path)

    def test_retry_still_poisons(self):
        # One poisoned batch: skipped with warning, rest intact —
        # exercises escrow + ack-only commit on the new path.
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "wb") as fh:
                for i in range(300):
                    fh.write(b"POISON-ME\n" if i == 150
                             else b"ok line %d\n" % i)
            res = forkrun.map(_fail_twice_factory(), path, workers=2,
                              on_error="skip", nodes=1)
            joined = b"".join(res)
            self.assertNotIn(b"POISON-ME", joined)
            self.assertIn(b"ok line 0", joined)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
