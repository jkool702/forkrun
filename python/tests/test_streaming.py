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

from _helpers import ChildLifecycleMixin, assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _identity(batch):
    return bytes(batch.data)


# The number of ALTERNATING paired measurements behind the streaming-memory margin.
# Odd, so the median is a measured pair rather than an average of two.
_PAIRS = 3


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreaming(ChildLifecycleMixin, unittest.TestCase):
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

    def test_slow_consumer_holds_less_than_collect_all(self):
        """Slow-consumer memory, measured correctly (WO-PY-REL-1).

        REPLACES a ru_maxrss before/after delta. That measurement was
        invalid: ru_maxrss is a process PEAK, so `after - before` is "the
        largest transient allocation seen anywhere between two samples",
        not "memory this workload used". Its real margin was 56824 KB
        against a 61440 KB bound -- 8% -- which is why it flaked under
        load.

        What replaced it, and why each part matters:

        * an ISOLATED SUBPROCESS, because the thing under test is the
          process calling stream(); the unittest runner's resident set is
          dominated by unrelated fixtures and no sampling can separate it;
        * CURRENT RSS from /proc/self/statm, which falls as well as rises,
          unlike a peak counter;
        * sampling INSIDE the consumer loop, not once at the end -- a
          final sample measures whatever the consumer chose to keep, which
          is the opposite of what we are trying to observe;
        * no monitoring thread, because this process forks workers.

        THE PROPERTY. Measured, not assumed: with this fixture the
        streaming parent retains 0.50x the output bytes at peak, while a
        consumer that simply keeps everything retains ~1.0x. That ratio is
        stable from 47 MB to 380 MB of output. The assertion is therefore
        RELATIVE -- streaming must retain materially less than
        collect-all -- because that is the property that actually holds
        and that a regression would break.

        A note on the old absolute bound: 60 MB sat ABOVE the measured
        collect-all figure for this very workload (58.9 MB), so even with
        a perfect measurement it could not have told streaming from
        naive accumulation.

        WHAT THIS DOES NOT PROVE, stated plainly because it is easy to
        misread: streaming is NOT output-size independent. The ratio is a
        constant 0.50, not a constant number of bytes. Retention scales
        with output; it is simply about half of what collection costs.
        Recorded as TD-13. The original comment claimed "output-size
        independence with wide margin"; that was never true.

        WHAT IT DOES PROVE: that the streaming parent retains
        materially less memory than a consumer retaining everything, on
        the same input, in the same process shape, with the slow consumer
        intact -- and that a regression to collect-all behaviour fails
        this test.
        """
        import json
        import subprocess

        probe = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "_streaming_rss_probe.py")
        self.assertTrue(os.path.exists(probe),
                        "the RSS probe is missing; this test cannot measure "
                        "anything without it")

        common = ["--lines", "800000", "--amp", "5", "--workers", "4",
                  "--order", "none", "--delay", "0.001"]

        def run(extra):
            cmd = [sys.executable, probe] + common + extra
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=900)
            self.assertEqual(
                proc.returncode, 0,
                "RSS probe failed (rc=%d).\ncmd: %s\nstderr:\n%s"
                % (proc.returncode, " ".join(cmd), proc.stderr[-2000:]))
            try:
                return json.loads(proc.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                self.fail("RSS probe produced no JSON.\nstdout: %r\n"
                          "stderr: %s" % (proc.stdout[-1000:],
                                          proc.stderr[-1000:]))

        # PAIRED, ALTERNATING measurements.
        #
        # A single pair made the gate depend on one sample: a
        # cleanroom-on gate run once measured 0.82x (just over the
        # 0.80 margin) while the same workload measured 0.39-0.50x
        # in every controlled condition (alternating order, CPU load,
        # memory pressure). A one-shot assertion cannot tell a
        # property of the workload from a property of the moment.
        #
        # So: PAIRS, with the arm order ALTERNATED between pairs (so
        # neither arm systematically benefits from going first), and
        # the margin asserted on the MEDIAN ratio. The median is
        # robust to a single anomalous pair, and a genuine regression
        # to collect-all behaviour moves every pair to ~1.0x.
        #
        # The strict relation -- streaming retains LESS than
        # collect-all -- is asserted for EVERY pair, not for the
        # aggregate: that is the property, and it has no tolerance.
        pairs = []
        for i in range(_PAIRS):
            if i % 2 == 0:
                streaming = run([])
                collecting = run(["--collect"])
            else:
                collecting = run(["--collect"])
                streaming = run([])
            pairs.append((streaming, collecting))

        for streaming, collecting in pairs:
            for got, label in ((streaming, "streaming"),
                               (collecting, "collect-all")):
                self.assertGreater(
                    got["blobs"], 10,
                    "%s: the workload produced too few batches to say "
                    "anything" % label)
                self.assertGreater(
                    got["samples"], 10,
                    "%s: RSS was sampled %d times; a single sample measures "
                    "the wrong thing" % (label, got["samples"]))

        ratios = []
        for streaming, collecting in pairs:
            s_growth = streaming["growth_kb"]
            c_growth = collecting["growth_kb"]
            self.assertIsNotNone(s_growth)
            self.assertIsNotNone(c_growth)
            self.assertGreater(
                s_growth, 0,
                "streaming growth measured as %r; a zero baseline makes the "
                "comparison meaningless" % (s_growth,))

            # The regression this exists to catch: a parent that ends
            # up retaining everything, i.e. what naive collection
            # costs. Asserted for EVERY pair -- no tolerance.
            self.assertLess(
                s_growth, c_growth,
                "streaming parent retained %d KB but collect-all retained "
                "%d KB -- streaming is not holding less than naive "
                "collection (output=%d bytes).\nstreaming: %r\ncollect: %r"
                % (s_growth, c_growth, streaming["out_bytes"],
                   streaming, collecting))
            ratios.append(s_growth / float(c_growth))

        # The margin, on the MEDIAN of the paired ratios. The measured
        # separation is ~0.39-0.50x vs ~1.0-1.2x; 0.80 leaves room for
        # ordinary variation and still fails a collect-all regression
        # outright (that would sit at ~1.0x).
        ordered = sorted(ratios)
        median = ordered[len(ordered) // 2]
        self.assertLess(
            median, 0.80,
            "the median streaming/collect-all ratio is %.3f over %d "
            "alternating pairs (ratios: %s; raw growths: %s) -- the "
            "measured separation is ~0.40-0.50x vs ~1.0-1.2x, so this is "
            "a real change in behaviour, not noise"
            % (median, len(ratios),
               ", ".join("%.3f" % r for r in ratios),
               "; ".join("s=%d KB c=%d KB" % (st["growth_kb"],
                                             co["growth_kb"])
                         for st, co in pairs)))

        assert_no_zombies(self)

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
