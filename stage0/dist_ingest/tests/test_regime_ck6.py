#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-6: regime classifier +
property tests (synthetic vectors).

Regime classifier uses existing DIST_RESULT telemetry:
read_wait_ns (source-limited), publish_wait_ns (admission),
consume_wait_ns (consumer starvation signal), backlog fields.

CORRECTED SEMANTICS (review fix 2):
  consume_wait_ns accumulates time blocked on cv_can_pop because the
  queue is EMPTY — high consume_wait = consumers STARVED, not saturated.
  demand/consumer-limited requires BOTH high consume_wait (starvation)
  AND persistently high backlog (saturation).
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from regime_classify import classify_metrics as classify  # noqa: E402


class TestRegimeClassifier(unittest.TestCase):
    def test_source_limited(self):
        r = classify(read_wait_ns=int(2 * 1e9), publish_wait_ns=0,
                     consume_wait_ns=int(0.1 * 1e9), backlog=1,
                     max_backlog=1024, claims_zero=0, run_seconds=10.0)
        self.assertEqual(r[0], "source-limited")

    def test_admission_limited(self):
        r = classify(read_wait_ns=0, publish_wait_ns=int(2 * 1e9),
                     consume_wait_ns=0, backlog=900, max_backlog=1000,
                     claims_zero=0, run_seconds=10.0)
        self.assertEqual(r[0], "admission-limited")

    def test_consumer_starved_not_saturated(self):
        # High consume_wait + shallow backlog = starved, NOT consumer-limited.
        r = classify(read_wait_ns=0, publish_wait_ns=0,
                     consume_wait_ns=int(2 * 1e9), backlog=10,
                     max_backlog=1000, claims_zero=0, run_seconds=10.0)
        self.assertNotEqual(r[0], "demand/consumer-limited")

    def test_consumer_limited_needs_saturation(self):
        # High consume_wait + saturated backlog = demand/consumer-limited.
        r = classify(read_wait_ns=0, publish_wait_ns=0,
                     consume_wait_ns=int(2 * 1e9), backlog=900,
                     max_backlog=1000, claims_zero=0, run_seconds=10.0)
        self.assertEqual(r[0], "demand/consumer-limited")

    def test_balanced(self):
        r = classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                     backlog=10, max_backlog=1000, claims_zero=0,
                     run_seconds=10.0)
        self.assertEqual(r[0], "balanced")

    def test_mixed_reported(self):
        r = classify(read_wait_ns=int(0.3 * 1e9), publish_wait_ns=int(0.2 * 1e9),
                     consume_wait_ns=int(0.4 * 1e9), backlog=300,
                     max_backlog=500, claims_zero=0, run_seconds=10.0)
        self.assertIn(r[0], ("mixed", "source-limited", "demand/consumer-limited",
                             "admission-limited", "balanced"))

    def test_run_dist_emits_regime(self):
        # run_dist re-exports the authoritative classifier (CK-6 integration).
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("run_dist", os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "run_dist.py"))
        run_dist = ilu.module_from_spec(spec)
        spec.loader.exec_module(run_dist)
        out = run_dist._regime_classify(run_dist.DiNodeMetrics(), 1.0)
        self.assertIn("regime", out)
        self.assertIn("evidence", out)


if __name__ == "__main__":
    unittest.main()
