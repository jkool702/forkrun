"""F-PY-UMA1b closure: the ingress-memfd file offset is not part of
any forkrun contract (INVARIANTS.md §20).

Background: F-PY-UMA1 fixed the UMA scanner seeding its base from
lseek(SEEK_CUR) (base is now unconditionally 0); W-MOVER proved a
live offset-mover still exists (8-byte positional reads on the
shared ingress from do_lockfree_claim's eventfd-drain path landing
on the ingress description — traced, disassembled, sentried — plus
spill-path residue neutralized by the pre-fork lseek(0)). The
mover is engine-resident; the engine fix is halted per red lines.
This file locks the CONTRACT instead: no forkrun consumer may
read or rely on the ingress file offset, so ANY offset — including
a deliberately dirtied one — must yield byte-exact output.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
import importlib as _importlib  # noqa: E402
_run_mod = _importlib.import_module("forkrun.run")  # module, not forkrun.run()
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _identity(batch):
    return bytes(batch.data)


def make_dirty_scanner_fork(real_fork):
    """Wrap a scanner-fork to trash the shared ingress offset.

    Simulates the live mover at its worst (mid-line dirty offset
    visible before any worker runs). A positional consumer would
    drop [0, K); the base-0 contract must hold regardless.
    """
    def _dirty(lib, memfd, engine_fds):
        pid = real_fork(lib, memfd, engine_fds)
        try:
            size = os.fstat(memfd).st_size
            if size > 64:
                os.lseek(memfd, size // 2, os.SEEK_SET)
                # The dirty state must really be visible (shared
                # description); the scanner child's scrub latency
                # (~50-200us of readdir+close) means this lands
                # before its entry query essentially always.
                got = os.lseek(memfd, 0, os.SEEK_CUR)
                assert got == size // 2, (got, size)
        except OSError:
            pass
        return pid
    return _dirty


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPositionIndependence(unittest.TestCase):
    def test_dirty_offset_still_exact(self):
        # The F-PY-UMA1 forensic shape: nonzero shared offset at
        # scanner entry must not cost a single head byte.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            dirty = make_dirty_scanner_fork(
                _run_mod._fork_materialized_scanner)
            with mock.patch.object(_run_mod, "_fork_materialized_scanner",
                                   dirty):
                out = forkrun.map(_identity, path, workers=2, nodes=1,
                                  order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_dirty_offset_spawn_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            dirty = make_dirty_scanner_fork(
                _run_mod._fork_materialized_scanner)
            with mock.patch.object(_run_mod, "_fork_materialized_scanner",
                                   dirty):
                out = forkrun.map("cat", path, mode="spawn", workers=2,
                                  nodes=1, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSequentialHeadExactness(unittest.TestCase):
    def test_ten_sequential_maps_exact(self):
        # The original F-PY-UMA1 hunting ground: sequential
        # in-process maps must be head-exact every time.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pb = fh.name
        try:
            write_lines(pa, 1500)
            write_lines(pb, 700, fmt="other %d\n")
            with open(pa, "rb") as fh:
                rawa = fh.read()
            with open(pb, "rb") as fh:
                rawb = fh.read()
            for _ in range(10):
                self.assertEqual(
                    b"".join(forkrun.map(_identity, pa, workers=2,
                                         order="index", nodes=1)), rawa)
                self.assertEqual(
                    b"".join(forkrun.map(
                        "cat", pb, mode="spawn", workers=2,
                        order="index", nodes=1)), rawb)
            assert_no_zombies(self)
        finally:
            os.unlink(pa)
            os.unlink(pb)


if __name__ == "__main__":
    unittest.main()
