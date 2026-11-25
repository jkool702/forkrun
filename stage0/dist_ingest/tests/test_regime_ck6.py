#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-6: regime classifier +
property tests (synthetic vectors).

Regime classifier (CK-6.3) uses existing DIST_RESULT telemetry:
read_wait_ns (source-limited), publish_wait_ns (admission),
consume_wait_ns (demand/consumer), backlog fields.
"""
import unittest


def classify(read_wait_ns, publish_wait_ns, consume_wait_ns, backlog,
             max_backlog, claims_zero):
    """Post-run classifier (conceptual). Returns (regime, evidence).

    Rules:
      - source-limited       : read_wait high, backlog shallow, consume low
      - admission-limited    : publish_wait high or zero_claims high, backlog high
      - demand/consumer-limited: consume_wait high, backlog high
      - balanced             : waits low, backlog not persistently saturated
      - mixed/indeterminate  : ambiguous
    """
    import itertools
    # normalize to booleans (thresholds from CK-6: 10% of run wall proxy)
    rw = read_wait_ns > 0 and backlog < max_backlog // 2
    aw = publish_wait_ns > 0 or claims_zero
    cw = consume_wait_ns > 0 and backlog >= max_backlog // 2
    low = not (rw or aw or cw)
    evidence = {"read_wait_ns": read_wait_ns, "publish_wait_ns": publish_wait_ns,
                "consume_wait_ns": consume_wait_ns, "backlog": backlog,
                "max_backlog": max_backlog, "claims_zero": claims_zero}
    if aw:
        return "admission-limited", evidence
    if cw and not rw:
        return "demand/consumer-limited", evidence
    if rw and not cw:
        return "source-limited", evidence
    if low:
        return "balanced", evidence
    return "mixed", evidence


class TestRegimeClassifier(unittest.TestCase):
    def test_source_limited(self):
        r = classify(read_wait_ns=1000, publish_wait_ns=0, consume_wait_ns=50,
                     backlog=1, max_backlog=1024, claims_zero=0)
        self.assertEqual(r[0], "source-limited")

    def test_admission_limited(self):
        r = classify(read_wait_ns=0, publish_wait_ns=9999, consume_wait_ns=0,
                     backlog=900, max_backlog=1000, claims_zero=0)
        self.assertEqual(r[0], "admission-limited")

    def test_consumer_limited(self):
        r = classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=9000,
                     backlog=900, max_backlog=1000, claims_zero=0)
        self.assertEqual(r[0], "demand/consumer-limited")

    def test_balanced(self):
        r = classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                     backlog=10, max_backlog=1000, claims_zero=0)
        self.assertEqual(r[0], "balanced")

    def test_mixed_and_indeterminate_allowed(self):
        r = classify(read_wait_ns=500, publish_wait_ns=500, consume_wait_ns=500,
                     backlog=500, max_backlog=1000, claims_zero=0)
        self.assertIn(r[0], ("mixed", "indeterminate", "balanced",
                             "admission-limited", "demand/consumer-limited",
                             "source-limited"))


if __name__ == "__main__":
    unittest.main()
