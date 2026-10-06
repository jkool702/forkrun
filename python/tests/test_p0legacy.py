"""P0LEGACY lock-in: legacy scanner-join watchdog misfire.

Bite-then-green: on the pre-fix tree this test FAILS — the legacy
parent joins the materialized scanner FIRST with the bounded
W-REL5-B4 deadline (10s), but the scanner parks under backpressure
(uma_max_ahead) for ~the full run on slow-UDF workloads, so any
legacy run past ~10s wall dies with `scan failed (status 9)`.
Post-fix the parent reaps workers first (reactor pattern) and the
run completes with exact totals.

Mechanism needs BOTH ingredients, hence the shape: a 5M-record
corpus (2570 batches > max_ahead park depth at 2 workers) AND the
real benchmark medium UDF (wall ~40s at 2 workers, well past the
deadline — a synthetic fast UDF lets the scanner finish inside the
deadline and cannot reproduce). `lines=1000` pins the batch count
(5000 batches) independent of the pre-flight CASE-A/B race: without
it the batch count — and therefore the park — depends on worker
arrival timing (observed: identical pre-fix runs both die at 10.5s
AND pass in 40s). Small/fast inputs can never reproduce it
(scanner finishes inside the deadline) — they are covered by the
existing suite. Gated on the seeded benchmark corpus; skipped with
reason when absent (the heavy-28w benchmark leg in
`headline_2026-09-29.csv` is the permanent full-scale guard).

Pre-fix FAIL verified 2026-09-29 (watchdog kill at 10.5s, with
`lines=1000` for determinism); post-fix PASS verified same day.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                               "benchmarks", "ml"))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies  # noqa: E402

# The real benchmark UDF: deliberately the slowest faithful input —
# only genuine per-line cost parks the scanner past the deadline.
from bench_ml_pipeline import (FORKRUN_PAYLOADS, count_results,  # noqa: E402
                               count_total)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

MEDIUM_5M = "/mnt/ramdisk/numa1/ml/medium_5M.jsonl"


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
@unittest.skipUnless(os.path.exists(MEDIUM_5M),
                     "seeded medium-5M corpus absent")
class TestLegacySlowUdfCompletes(unittest.TestCase):
    """Legacy fail-fast must survive a parked scanner (~40s wall)."""

    def test_legacy_python_medium_2w(self):
        out = forkrun.map(FORKRUN_PAYLOADS["medium"], MEDIUM_5M,
                          workers=2, order="index", nodes=1,
                          orchestrator=False, lines=1000)
        self.assertEqual(count_total(out), 5000000)
        self.assertEqual(count_results(out), 4997892)
        assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
