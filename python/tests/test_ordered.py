"""W-PY7 ordered streaming: parent-side reassembly (Stage 5 Phase 2).

order="none": completion order (W-PY6 contract, preserved).
order="index": batch_idx sequence via ReassemblyBuffer; holes (poisoned
batches) flush sorted at EOF. Determinism notes: fixed lines=N batching
makes batch counts exact (50k/500 = 100); the poison-hole test pins the
marker to a computable batch; the bound test forces out-of-order arrival
with idx-gated sleeps (50ms vs ~1ms engine overhead — no absolute
deadlines anywhere).
"""

import importlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._reassembly import ReassemblyBuffer  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestReassemblyBuffer(unittest.TestCase):
    """Unit lock-ins for the buffer mechanics (engine-free)."""

    def test_add_drain_ordered(self):
        buf = ReassemblyBuffer()
        for idx in (2, 0, 1, 4):
            buf.add(idx, b"d%d" % idx)
        # Only the consecutive run from 0 drains; 4 waits (hole at 3).
        self.assertEqual(list(buf.drain()), [(0, b"d0"), (1, b"d1"),
                                             (2, b"d2")])
        self.assertEqual(buf.pending, 1)
        self.assertEqual(buf.next_idx, 3)
        buf.add(3, b"d3")
        self.assertEqual(list(buf.drain()), [(3, b"d3"), (4, b"d4")])
        self.assertEqual(buf.pending, 0)

    def test_final_drain_skips_holes(self):
        buf = ReassemblyBuffer()
        for idx in (6, 4, 9):
            buf.add(idx, b"d%d" % idx)
        self.assertEqual(list(buf.drain()), [])  # hole at 0
        self.assertEqual(list(buf.final_drain()),
                         [(4, b"d4"), (6, b"d6"), (9, b"d9")])
        self.assertEqual(buf.pending, 0)

    def test_diagnostics(self):
        buf = ReassemblyBuffer()
        self.assertEqual(buf.max_size, 0)
        for idx in (3, 2, 1):
            buf.add(idx, b"x")
        self.assertEqual(buf.max_size, 3)
        self.assertEqual(buf.pending, 3)
        list(buf.drain())  # nothing consecutive from 0
        self.assertEqual(buf.pending, 3)
        buf.add(0, b"x")
        self.assertEqual(len(list(buf.drain())), 4)
        self.assertEqual(buf.max_size, 4)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestOrderedStreaming(unittest.TestCase):
    def test_ordered_yields_in_sequence(self):
        def marked(batch):
            return b"%08d:" % batch.batch_index + bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 3000)
            out = list(forkrun.stream(marked, path, workers=4,
                                      order="index", nodes=1))
            idxs = [int(rec.split(b":", 1)[0]) for rec in out]
            self.assertEqual(idxs, sorted(idxs))
            self.assertEqual(len(set(idxs)), len(idxs))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_unordered_regression(self):
        # order="none" keeps the W-PY6 contract: every line exactly once,
        # completion order (no sequencing imposed).
        def ident(batch):
            return bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 3000)
            out = list(forkrun.stream(ident, path, workers=4, nodes=1))
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(sorted(b"".join(out).splitlines()),
                             sorted(raw.splitlines()))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_ordered_matches_map(self):
        # Same deterministic scan => identical key-ordered sequences.
        def ident(batch):
            return bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 3000)
            streamed = list(forkrun.stream(ident, path, workers=4,
                                           order="index", nodes=1))
            mapped = forkrun.map(ident, path, workers=4, order="index", nodes=1)
            self.assertEqual(streamed, mapped)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_buffer_bounded(self):
        # Idx-gated sleeps force out-of-order arrival deterministically:
        # batches 0,4,8... sleep 50ms while others finish in ~1ms, so
        # triples {4k+1,4k+2,4k+3} always buffer behind each sleeping head.
        run_mod = importlib.import_module("forkrun.run")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 4000)

            def gated(batch):
                if batch.batch_index % 4 == 0:
                    import time as _t

                    _t.sleep(0.05)
                return bytes(batch.data)

            stats: dict = {}
            out = list(run_mod._execute_streaming(
                gated, path, lines=None, bytes_=None, workers=4,
                on_error="retry", order="index", stats=stats))
            with open(path, "rb") as fh:
                # No poison: ordered reassembly is byte-exact.
                self.assertEqual(b"".join(out), fh.read())
            max_size = stats.get("reassembly_max", 0)
            self.assertGreaterEqual(max_size, 3)
            self.assertLess(max_size, len(out))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_poisoned_gap_skipped(self):
        # Fixed lines=500 batching: 50k lines = exactly 100 batches;
        # MARKER at line 25000 sits in batch 50, which poisons. The
        # ordered stream must yield 0..49,51..99 in sequence (hole at 50
        # flushes past at EOF), and the buffer must have held 51..99.
        run_mod = importlib.import_module("forkrun.run")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                for i in range(50000):
                    fh.write("MARKER\n" if i == 25000 else "line %d\n" % i)

            def flaky(batch):
                data = bytes(batch.data)
                if b"MARKER" in data:
                    raise RuntimeError("poison me")
                return b"%08d:" % batch.batch_index + data

            stats: dict = {}
            out = list(run_mod._execute_streaming(
                flaky, path, lines=500, bytes_=None, workers=4,
                on_error="retry", order="index", stats=stats))
            idxs = [int(rec.split(b":", 1)[0]) for rec in out]
            expected = [i for i in range(100) if i != 50]
            self.assertEqual(idxs, expected)
            self.assertGreaterEqual(stats.get("reassembly_max", 0), 49)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_empty_input_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(list(forkrun.stream(
                lambda b: bytes(b.data), path, workers=2,
                order="index", nodes=1)), [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_single_batch_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("only\n")
            out = list(forkrun.stream(lambda b: bytes(b.data), path,
                                      workers=2, order="index", nodes=1))
            self.assertEqual(b"".join(out), b"only\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
