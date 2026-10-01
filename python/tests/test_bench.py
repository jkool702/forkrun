"""Harness unit tests (W-PY11.a lock-in). Engine-free, milliseconds."""
import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "benchmarks"))

from bench_harness import (BenchContext, Result, _detect_hardware,  # noqa: E402
                           cpu_pct_around, format_cpu, format_rate,
                           format_table, rss_mb, time_it, write_csv)


class TestHarness(unittest.TestCase):
    def test_time_it_median_and_warmup(self):
        calls = []

        def fn():
            calls.append(1)

        med, all_t = time_it(fn, trials=5, warmup=2)
        self.assertEqual(len(calls), 7)  # warmup runs count, untimed
        self.assertEqual(len(all_t), 5)
        self.assertGreaterEqual(med, 0)
        self.assertEqual(med, sorted(all_t)[2])

    def test_format_table_aligned(self):
        rows = [Result(name="a", mode="m", path="p", lines_per_s=1400,
                       rss_mb=3.2, cpu_pct=28.4, notes="n")]
        table = format_table(rows)
        lines = table.splitlines()
        self.assertEqual(len(lines), 5)  # sep/head/sep/row/sep
        self.assertIn("1k", table)
        self.assertIn("28%", table)
        # All lines same width (aligned).
        self.assertEqual(len({len(ln) for ln in lines}), 1)

    def test_format_table_empty(self):
        table = format_table([])
        self.assertIn("Benchmark", table)

    def test_format_rate(self):
        self.assertEqual(format_rate(25e6), "25.0M")
        self.assertEqual(format_rate(1400), "1k")
        self.assertEqual(format_rate(0), "-")

    def test_write_csv_round_trip(self):
        rows = [Result(name="a", mode="m", path="p", lines_per_s=1.0,
                       rss_mb=2.0, cpu_pct=12.5, notes="n", hardware="h")]
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            write_csv(rows, path)
            with open(path, newline="") as fh:
                parsed = list(csv.reader(fh))
            self.assertEqual(parsed[0],
                             ["name", "mode", "path", "lines_per_s",
                              "rss_mb", "cpu_pct", "notes", "hardware"])
            self.assertEqual(parsed[1][0], "a")
            self.assertEqual(parsed[1][5], "12.5")
            self.assertEqual(parsed[1][-1], "h")
        finally:
            os.unlink(path)

    def test_hardware_disclosure(self):
        hw = _detect_hardware()
        self.assertIn("Linux", hw)
        self.assertTrue(len(hw) > 8)

    def test_context_scale_validation(self):
        with self.assertRaises(ValueError):
            BenchContext(scale="xxl")
        ctx = BenchContext(scale="small", trials=1)
        self.assertEqual(ctx.trials, 1)
        p = ctx.input_path(lines=10)
        try:
            with open(p) as fh:
                self.assertEqual(len(fh.readlines()), 10)
        finally:
            ctx.cleanup()
        self.assertFalse(os.path.exists(p))

    def test_rss_mb(self):
        self.assertGreater(rss_mb(), 0)

    def test_format_cpu(self):
        self.assertEqual(format_cpu(-1.0), "-")
        self.assertEqual(format_cpu(28.4), "28%")

    def test_cpu_pct_around_trivial(self):
        # Idle fn: near-zero attributable CPU, but never negative.
        pct = cpu_pct_around(lambda: None)
        self.assertGreaterEqual(pct, 0.0)
        self.assertLess(pct, 100.0)

    def test_cpu_pct_around_busy_children(self):
        # Reaped busy children attribute: N forks each burning ~0.2s
        # must register well above idle on a multi-core box.
        import subprocess

        def burn():
            for _ in range(4):
                p = subprocess.run(
                    ["python3", "-c",
                     "t=__import__('time').perf_counter()\n"
                     "while __import__('time').perf_counter()-t < 0.2: pass"],
                    capture_output=True, timeout=60)
                assert p.returncode == 0

        pct = cpu_pct_around(burn)
        self.assertGreater(pct, 1.0)


if __name__ == "__main__":
    unittest.main()
