"""Result-record representation and lifetime (W-PYZEROCOPY).

output="view" (the default since 0.17.0) returns memoryview slices over
a read-only mapping of the result stream. These tests pin down what that
does and does not promise, and specifically try to BREAK it -- the
failure modes that matter are the ones that would be silent.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402


def _up(batch):
    return batch.data


def _write_lines(path, n, fmt="line %d\n"):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(fmt % i)


class TestOutputRepresentation(unittest.TestCase):
    """The two modes, and that they agree byte-for-byte."""

    def test_default_is_view(self):
        path = _tmp(_write_lines, 200)
        try:
            out = forkrun.map(_up, path, workers=4, nodes=1)
            self.assertEqual(type(out[0]).__name__, "memoryview",
                             "default output must be zero-copy views")
        finally:
            os.unlink(path)

    def test_explicit_bytes(self):
        path = _tmp(_write_lines, 200)
        try:
            out = forkrun.map(_up, path, workers=4, nodes=1,
                              output="bytes")
            self.assertIsInstance(out[0], bytes)
        finally:
            os.unlink(path)

    def test_bad_output_rejected(self):
        path = _tmp(_write_lines, 20)
        try:
            for bad in ("nope", "VIEW", "", 1, True):
                with self.assertRaises(ValueError):
                    forkrun.map(_up, path, workers=2, nodes=1, output=bad)
        finally:
            os.unlink(path)

    def test_modes_are_byte_identical(self):
        """Same records, same order, both representations.

        order="index" because the default order="none" is
        worker-completion order, which differs run to run by design.
        """
        path = _tmp(_write_lines, 500)
        try:
            v = forkrun.map(_up, path, workers=4, nodes=1, output="view",
                            order="index")
            b = forkrun.map(_up, path, workers=4, nodes=1, output="bytes",
                            order="index")
            self.assertEqual(len(v), len(b))
            self.assertEqual(b"".join(bytes(x) for x in v),
                             b"".join(bytes(x) for x in b))
        finally:
            os.unlink(path)

    def test_materialize_roundtrip(self):
        path = _tmp(_write_lines, 50)
        try:
            out = forkrun.map(_up, path, workers=2, nodes=1)
            for rec in out:
                m = forkrun.materialize(rec)
                self.assertIsInstance(m, bytes)
                self.assertEqual(m, bytes(rec))
            # idempotent on something already bytes
            self.assertEqual(forkrun.materialize(b"x"), b"x")
        finally:
            os.unlink(path)

    def test_views_satisfy_the_obvious_buffer_operations(self):
        """What a caller can do with a view without converting."""
        path = _tmp(_write_lines, 50)
        try:
            out = forkrun.map(_up, path, workers=2, nodes=1, order="index")
            rec = out[0]
            # A record is a whole batch (adaptive), so assert against the
            # input prefix rather than a single line.
            raw = open(path, "rb").read()
            self.assertEqual(bytes(rec), raw[:len(rec)])
            self.assertTrue(bytes(rec).startswith(b"line 0\n"))
            # slicing a view yields another VIEW, not bytes
            sub = rec[:4]
            self.assertEqual(type(sub).__name__, "memoryview")
            self.assertEqual(bytes(sub), b"line")
            self.assertEqual(rec.tobytes(), bytes(rec))
            self.assertEqual(rec.hex(), bytes(rec).hex())
            # whole-record equality against bytes works in both
            # directions -- this is what c_ubyte over c_char buys; a
            # '<c'-format view compares False against bytes.
            self.assertEqual(rec.format, "<B")  # native-endian uint8
            self.assertEqual(rec, bytes(rec))
            self.assertEqual(bytes(rec), rec)
        finally:
            os.unlink(path)

    def test_views_are_not_sequences_of_bytes(self):
        """The compatibility cliff, asserted so it stays documented.

        memoryview is a buffer, not a str/bytes: these are the calls
        that a bytes-returning caller would reasonably make and that
        now need forkrun.materialize() or bytes(rec).

        Note the mixed exception types are CPython's, not ours:
        AttributeError for the missing str/bytes methods, and
        NotImplementedError for `in`, which rejects memoryview's
        multi-byte format outright.
        """
        path = _tmp(_write_lines, 20)
        try:
            rec = forkrun.map(_up, path, workers=2, nodes=1,
                              order="index")[0]
            for name, fn in (("split", lambda: rec.split(b"\n")),
                             ("decode", lambda: rec.decode()),
                             ("startswith", lambda: rec.startswith(b"line")),
                             ("in", lambda: b"line" in rec)):
                with self.assertRaises((AttributeError, TypeError,
                                        NotImplementedError), msg=name):
                    fn()
        finally:
            os.unlink(path)


class TestOutputAcrossExecutorLattice(unittest.TestCase):
    """output= must hold on every map() lattice cell.

    Two real bugs lived here and neither showed up in a single-path
    test: streaming-ingest (pipe) sources dropped the flag, and the
    fail-fast (orchestrator=False) collect had its own parse that never
    consulted it. Both returned bytes while the caller had asked for
    views, with no error. So sweep the whole grid.
    """

    def test_map_lattice_honors_output(self):
        path = _tmp(_write_lines, 300)
        want_total = os.path.getsize(path)   # variable-width lines
        try:
            bad = []
            for orch in (True, False):
                for streaming in (True, False, None):
                    for output in ("view", "bytes"):
                        for order in ("none", "index"):
                            out = forkrun.map(
                                _up, path, workers=2, orchestrator=orch,
                                streaming=streaming, output=output,
                                order=order, nodes=1)
                            want = ("memoryview" if output == "view"
                                    else "bytes")
                            got = type(out[0]).__name__
                            total = sum(map(len, out))
                            if got != want or total != want_total:
                                bad.append((orch, streaming, output,
                                            order, got, total))
            self.assertEqual(bad, [], "output= ignored on %r" % (bad,))
        finally:
            os.unlink(path)

    def test_pipe_source_honors_output(self):
        """The streaming-ingest path had its own dispatch."""
        def fresh_pipe():
            r, w = os.pipe()
            os.write(w, b"x\n" * 50)
            os.close(w)
            return r

        for output, want in (("view", "memoryview"), ("bytes", "bytes")):
            r = fresh_pipe()          # a consumed pipe yields nothing
            try:
                out = forkrun.map(_up, r, workers=2, order="index",
                                  nodes=1, output=output)
                self.assertTrue(out, "empty result for output=%r" % output)
                self.assertEqual(type(out[0]).__name__, want,
                                 "pipe source ignored output=%r" % output)
            finally:
                os.close(r)

    def test_stream_always_bytes(self):
        """Documented exception: no finished file to map on a live drain."""
        path = _tmp(_write_lines, 200)
        try:
            for orch in (True, False):
                for output in ("view", "bytes"):
                    got = list(forkrun.stream(_up, path, workers=2,
                                              orchestrator=orch,
                                              output=output, nodes=1))
                    self.assertTrue(got)
                    self.assertIsInstance(got[0], bytes)
        finally:
            os.unlink(path)


class TestViewLifetime(unittest.TestCase):
    """The load-bearing safety property.

    A view is backed by a C mapping that is unmapped by a
    weakref.finalize attached to the ctypes array the memoryview
    references. So the mapping CANNOT be torn down while a view is
    reachable -- reading a stale view would be SIGSEGV, not an
    exception, which is why this is tested rather than documented.
    """

    def test_view_outlives_the_run(self):
        """Holding one record long after the run must stay valid."""
        path = _tmp(_write_lines, 100)
        try:
            kept = forkrun.map(_up, path, workers=4, nodes=1,
                               order="index")[0]
            expected = bytes(kept)
            import gc
            for _ in range(3):
                gc.collect()
            self.assertEqual(bytes(kept), expected)
            self.assertEqual(len(kept), len(expected))
        finally:
            os.unlink(path)

    def test_view_survives_run_and_source_teardown(self):
        """The source file is gone; the record must not be."""
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        _write_lines(path, 300)
        kept = forkrun.map(_up, path, workers=4, nodes=1,
                           order="index")[0]
        expected = bytes(kept)
        os.unlink(path)
        import gc
        gc.collect()
        self.assertEqual(bytes(kept), expected)
        self.assertNotEqual(len(kept), 0)

    def test_views_retained_across_stream_iterations(self):
        """stream() consumers that buffer views must not corrupt them."""
        path = _tmp(_write_lines, 400)
        try:
            held = []
            for blob in forkrun.stream(_up, path, workers=4, nodes=1):
                held.append(blob)
                if len(held) >= 20:
                    break
            import gc
            gc.collect()
            # every retained view still reads back its own bytes
            for h in held:
                self.assertTrue(bytes(h).endswith(b"\n"))
                self.assertGreater(len(h), 0)
            # and the full set is still readable
            self.assertEqual(len(held), 20)
        finally:
            os.unlink(path)

    def test_no_fd_leak_from_mappings(self):
        """The mapping must not cost a descriptor.

        Python's own mmap.mmap(fd, ...) would: it dups the fd and
        releases it only when the mapping is collected. This is the
        regression guard for why the mapping is made in C.
        """
        path = _tmp(_write_lines, 200)

        def nfd():
            return len(os.listdir("/proc/self/fd"))

        try:
            base = nfd()
            for _ in range(8):
                out = forkrun.map(_up, path, workers=4, nodes=1,
                                  output="view")
                self.assertEqual(nfd(), base,
                                 "fd count moved while results held")
                del out
            import gc
            gc.collect()
            self.assertEqual(nfd(), base)
        finally:
            os.unlink(path)

    def test_zero_length_and_single_record(self):
        """Degenerate shapes still work under a mapping."""
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as fh:
            empty = fh.name
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as fh:
            one = fh.name
        try:
            fh = open(one, "w")
            fh.write("only\n")
            fh.close()
            self.assertEqual(forkrun.map(_up, empty, workers=2, nodes=1), [])
            got = forkrun.map(_up, one, workers=2, nodes=1)
            self.assertEqual(len(got), 1)
            self.assertEqual(bytes(got[0]), b"only\n")
        finally:
            os.unlink(empty)
            os.unlink(one)


def _tmp(fn, *a, **kw):
    with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                     delete=False) as fh:
        path = fh.name
    fn(path, *a, **kw)
    return path


if __name__ == "__main__":
    unittest.main()