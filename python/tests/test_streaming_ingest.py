"""W-PY16 streaming ingest: unbounded input, bounded memory (Stage 5).

Streams the source into the ingress memfd in 1MB chunks while a forked
scanner publishes concurrently and a forked reaper punches holes behind
the contiguous acked prefix. Workers fork on first DATA publish (never
during pre-flight — a waiting worker trips the pre-flight bail, and
phase 1 entered with already-complete input publishes nothing).

Writer processes use os.fork + pipe (no pickle, no multiprocessing).
"""

import os
import resource
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _pipe_with_lines(n, fmt="line %d\n", delay=0.0):
    """Fork a writer producing n lines; return the read end.

    The writer exits after delivery. delay>0 dribbles (slow source).
    """
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(r)
            for i in range(n):
                os.write(w, (fmt % i).encode())
                if delay:
                    time.sleep(delay)
        finally:
            try:
                os.close(w)
            except OSError:
                pass
            os._exit(0)
    os.close(w)
    return r, pid


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreamingIngest(unittest.TestCase):
    def test_streaming_matches_materialized(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 5000)
            exp = b"".join(forkrun.map(lambda b: bytes(b.data).upper(),
                                       path, workers=4, order="index",
                                       streaming=False, nodes=1))
            got = b"".join(forkrun.map(lambda b: bytes(b.data).upper(),
                                       path, workers=4, order="index",
                                       streaming=True, nodes=1))
            with open(path, "rb") as fh:
                self.assertEqual(got, fh.read().upper())
            self.assertEqual(got, exp)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_explicit_false_forces_materialized(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            out = forkrun.map(lambda b: bytes(b.data), path, workers=2,
                              order="index", streaming=False, nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_streaming_validation(self):
        with self.assertRaises(TypeError):
            forkrun.run(lambda b: None, "f.txt", streaming="yes", nodes=1)
        with self.assertRaises(TypeError):
            forkrun.map(lambda b: None, "f.txt", streaming=1, nodes=1)

    def test_pipe_auto_streams(self):
        r, pid = _pipe_with_lines(1000)
        try:
            out = forkrun.map(lambda b: bytes(b.data).upper(), r,
                              workers=2, order="index", nodes=1, output="bytes")
            self.assertEqual(len(out) > 0, True)
            got = sorted(b for blob in out for b in blob.splitlines())
            exp = sorted(("line %d" % i).upper().encode()
                         for i in range(1000))
            self.assertEqual(got, exp)
            os.waitpid(pid, 0)
            assert_no_zombies(self)
        finally:
            os.close(r)

    def test_streaming_run_and_stream(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            self.assertIsNone(forkrun.run(lambda b: None, path, workers=2,
                                          streaming=True, nodes=1))
            out = list(forkrun.stream(lambda b: bytes(b.data).upper(),
                                      path, workers=2, order="index",
                                      streaming=True, nodes=1))
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_streaming_spawn_plugin_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            out = forkrun.map("cat", path, mode="spawn", workers=2,
                              order="index", streaming=True, nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            so = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "plugins", "test_plugin_v1.so")
            if os.path.exists(so):
                out = forkrun.map("%s:process_v1" % so, path,
                                  mode="plugin", workers=2, order="index",
                                  streaming=True, nodes=1)
                with open(path, "rb") as fh:
                    self.assertEqual(b"".join(out), fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_empty_file_and_pipe(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(
                forkrun.map(lambda b: bytes(b.data), path, workers=2,
                            streaming=True, nodes=1), [])
            r, pid = _pipe_with_lines(0)
            try:
                self.assertEqual(
                    forkrun.map(lambda b: bytes(b.data), r, workers=2,
                                streaming=True, nodes=1), [])
                os.waitpid(pid, 0)
            finally:
                os.close(r)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_slow_source_pipelines(self):
        # Dribbled source: first results arrive before the writer is
        # done (stall timeout forks workers → CASE-B pipelining).
        r, pid = _pipe_with_lines(10, delay=0.3)
        try:
            gen = forkrun.stream(lambda b: bytes(b.data), r, workers=2,
                                 streaming=True, nodes=1)
            t0 = time.monotonic()
            first = next(gen)
            dt = time.monotonic() - t0
            rest = list(gen)
            self.assertTrue(first)
            # Writer needs ~3s total; first batch must not wait for it.
            self.assertLess(dt, 2.9,
                            "no pipelining: first batch took %.1fs" % dt)
            self.assertEqual(1 + len(rest) > 0, True)
            os.waitpid(pid, 0)
            assert_no_zombies(self)
        finally:
            os.close(r)

    def test_reactor_stream_does_not_sleep_per_chunk(self):
        """A streamed reactor run must WAIT on the source, not pace.

        Regression: the reactor ingest drained to EAGAIN then slept a
        flat 20 ms, once per chunk, because the reader outruns the
        writer. 645 sleeps on light-5M -- 12.9 s of a 14.65 s wall, 88%
        of the run. It now select()s on the source fd.

        Asserts the mechanism (the pacing sleep does not fire per
        chunk) rather than wall time, so it is not a benchmark: it
        fails on the old code and passes on the new in well under a
        second either way.
        """
        import collections
        import time as _t
        real_sleep = _t.sleep
        seen = collections.Counter()

        def counting(d):
            seen[round(d, 4)] += 1
            real_sleep(d)

        # The writer must be SLOWER than the reader, or the reader
        # never sees EAGAIN and the bug never fires. A memory-speed
        # writer pushing 64 KB chunks keeps the pipe permanently full:
        # this test passed against the reverted fix until the writer
        # was made to pull from a file, which is the real condition
        # (and the one the benchmark hit at 645 sleeps).
        src_path = os.path.join(tempfile.gettempdir(),
                                "forkrun_ingest_wait_src.bin")
        n_chunks = 16
        with open(src_path, "wb") as fh:
            for _ in range(n_chunks):
                fh.write(b"y" * (1 << 20))

        r, w = os.pipe()
        try:
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(r)
                    with open(src_path, "rb") as s, os.fdopen(w, "wb") as d:
                        while True:
                            b = s.read(1 << 20)
                            if not b:
                                break
                            d.write(b)
                finally:
                    os._exit(0)
            os.close(w)
            _t.sleep = counting
            try:
                out = forkrun.map(lambda b: b.data, r, workers=4, nodes=1,
                                  orchestrator=True, output="bytes")
                n = len(out)
                del out
            finally:
                _t.sleep = real_sleep
                os.close(r)
                os.waitpid(pid, 0)
        finally:
            try:
                os.close(w)
            except OSError:
                pass
            try:
                os.unlink(src_path)
            except OSError:
                pass

        self.assertGreater(n, 0)
        # Before the fix this fired ~n_chunks times; the wait is now a
        # select() that returns as soon as the writer lands a chunk.
        self.assertLess(
            seen[0.02], n_chunks // 4,
            "20 ms pacing sleep fired %d times for %d chunks -- the "
            "streamed reactor path is pacing instead of waiting"
            % (seen[0.02], n_chunks))

    def test_pipe_exactness_slow_source(self):
        """EXACT record count from a slow pipe source.

        W-EXACT: the pre-flight scan counts the input to size its
        initial batch. If it is told "input complete" before the
        ingest has actually spilled everything, it stops counting, the
        scanner treats that as EOF, and the tail is silently DROPPED
        with no error anywhere -- the run just returns fewer records.

        This is not hypothetical: an earlier attempt at the pre-flight
        fix lost 9,839 of 5,000,000 records this way and the entire
        667-test suite passed. So assert the count exactly, and assert
        it under a SLOW producer, which is the case where the pre-flight
        spends its time waiting.
        """
        n = 4000
        r, pid = _pipe_with_lines(n, fmt='{"i": %d}\n', delay=0.0005)
        try:
            def _count(batch):
                # one RESULT per batch, so report the record count the
                # batch carried rather than 1 -- a batch spans many lines
                return b"%d" % bytes(batch.data).count(b"\n")
            got = sum(int(v) for v in forkrun.stream(
                _count, r, workers=4, streaming=True, nodes=1))
        finally:
            try:
                os.close(r)
            except OSError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        self.assertEqual(
            got, n,
            "W-EXACT: lost the tail off a slow pipe -- %d of %d records "
            "returned. The pre-flight must never treat 'ingest finished' "
            "as EOF unless the input was genuinely drained." % (got, n))

    def test_memory_bounded(self):
        # 256MB through a pipe: parent growth must stay far below input
        # size (fallow punches acked prefixes). The headline 1GB run
        # (0.2MB growth) was verified manually; this keeps CI fast.
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(r)
                chunk = b"x" * 999 + b"\n"
                for _ in range(256 * 1024):
                    os.write(w, chunk)
            finally:
                try:
                    os.close(w)
                except OSError:
                    pass
                os._exit(0)
        os.close(w)
        try:
            before = resource.getrusage(
                resource.RUSAGE_SELF).ru_maxrss
            forkrun.run(lambda b: None, r, workers=4, streaming=True, nodes=1)
            after = resource.getrusage(
                resource.RUSAGE_SELF).ru_maxrss
            growth_mb = (after - before) / 1024.0
            self.assertLess(growth_mb, 100,
                            "RSS grew %.1fMB for 256MB streaming input "
                            "(fallow not reclaiming?)" % growth_mb)
            os.waitpid(pid, 0)
            assert_no_zombies(self)
        finally:
            os.close(r)

    def test_bytes_mode_wide_lines(self):
        # Byte-batched wide lines (pre-flight byte-ceiling corner):
        # must be byte-exact, never silently short.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                for _ in range(50):
                    fh.write("y" * 200000 + "\n")
            got = b"".join(forkrun.map(lambda b: bytes(b.data).upper(),
                                       path, workers=2, bytes=1 << 20,
                                       order="index", streaming=True, nodes=1))
            with open(path, "rb") as fh:
                self.assertEqual(got, fh.read().upper())
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
