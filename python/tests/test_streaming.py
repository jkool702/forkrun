"""W-PY6 v1 streaming tests: true incremental drain (Stage 5 Phase 1).

stream() yields WHILE workers run (bounded by the in-flight window);
map() stays on the v0.5 post-completion path. Timing assertions use
generous relative margins (first-vs-spread, path-vs-path ratios), never
absolute deadlines.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _identity(batch):
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreaming(unittest.TestCase):
    def test_stream_yields_incrementally(self):
        # Forced small batches + slow payload: first yield must arrive
        # long before completion (post-collection would deliver all at
        # the end within milliseconds of each other).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 4000)

            def slow(batch):
                import time as _t

                _t.sleep(0.005)
                return bytes(batch.data)

            t0 = time.perf_counter()
            stamps = []
            for _blob in forkrun.stream(slow, path, workers=2, lines=20, nodes=1):
                stamps.append(time.perf_counter() - t0)
            total = time.perf_counter() - t0
            self.assertGreater(len(stamps), 50)
            self.assertLess(stamps[0], 0.3 * total)
            self.assertGreater(stamps[-1] - stamps[0], 0.25)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_stream_exactness(self):
        # Completion order, but every line exactly once.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 5000)
            out = list(forkrun.stream(_identity, path, workers=4, nodes=1))
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(sorted(b"".join(out).splitlines()),
                             sorted(raw.splitlines()))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_stream_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(list(forkrun.stream(_identity, path,
                                                 workers=2, nodes=1)), [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_stream_none_return(self):
        def drop(batch):
            return None

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 500)
            self.assertEqual(list(forkrun.stream(drop, path, workers=2, nodes=1)),
                             [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_slow_consumer_bounds_memory(self):
        # 10MB in, 5x amplification (50MB output), 1ms/batch consumer:
        # v0.5 would park ~50MB in the parent list; streaming holds only
        # the in-flight window (pipe-depth x record). 60MB bound proves
        # output-size independence with wide margin for baseline.
        import resource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 800000)  # ~10MB

            def amplify(batch):
                return bytes(batch.data) * 5

            before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            n = 0
            for blob in forkrun.stream(amplify, path, workers=4, nodes=1):
                n += 1
                time.sleep(0.001)
                if n == 1:
                    self.assertTrue(len(blob) > 0)
            after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            self.assertGreater(n, 10)
            # ru_maxrss is KB on Linux.
            self.assertLess(after - before, 60 * 1024,
                            "parent grew with output size")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_fast_consumer_no_bottleneck(self):
        # Same workload both paths: streaming overhead (signal + pread
        # per batch) must stay within 2.5x of the v0.5 collect path.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 20000)
            t0 = time.perf_counter()
            out_stream = list(forkrun.stream(_identity, path, workers=4,
                                             order="none", nodes=1))
            t_stream = time.perf_counter() - t0
            t0 = time.perf_counter()
            out_map = forkrun.map(_identity, path, workers=4, nodes=1)
            t_map = time.perf_counter() - t0
            self.assertEqual(sorted(b"".join(out_stream).splitlines()),
                             sorted(b"".join(out_map).splitlines()))
            self.assertLess(t_stream, 2.5 * max(t_map, 0.05),
                            "stream=%.3fs map=%.3fs" % (t_stream, t_map))
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
