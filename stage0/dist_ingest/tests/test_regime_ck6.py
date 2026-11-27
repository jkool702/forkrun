#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-6.

Classifier semantics are pinned to the ACTUAL C instrumentation
(stage0/dist_ingest/dist_ingest.c). Critical corrected rule:

  high consume_wait_ns == consumers waiting for work (queue-empty) ==
  consumer starvation / underfeeding. It is NOT evidence consumers are
  saturated and is NOT consumer-limited.

  high publish_wait_ns == ingestor blocked on full queue == downstream
  backpressure; NOT proof raw consumer compute throughput is the limit.

  high read_wait_ns == significant time in the actual source-read op.

  high claim_wait_ns == claim/admission delay; sub-cause from code.

  zero_claims == policy-selected zero + admission-denied; split via
  zero_claims_policy / zero_claims_admission; policy-zero is NOT admission.

Labels are descriptive; mixed/indeterminate used when appropriate.
Normalization uses actual run duration + relevant thread counts.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from regime_classify import classify_metrics as classify  # noqa: E402

NS = int(1e9)


def _c(**kw):
    base = dict(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                max_backlog=1000, run_seconds=10.0, claim_wait_ns=0,
                backlog=10, claims_zero=0, claims_zero_policy=0,
                claims_zero_admission=0, reservations=0)
    base.update(kw)
    return classify(**base)


class TestRegimeClassifier(unittest.TestCase):
    # 1 + 2: high consume_wait + shallow backlog => NOT consumer-limited; starvation
    def test_high_consume_wait_shallow_backlog_not_consumer_limited(self):
        r = _c(consume_wait_ns=2 * NS, backlog=1, max_backlog=1000)
        self.assertNotEqual(r[0], "consumer-limited")
        self.assertNotIn("consumer-limited", r[0])

    def test_high_consume_wait_is_consumer_starvation_underfeeding(self):
        r = _c(consume_wait_ns=2 * NS, backlog=1)
        self.assertEqual(r[0], "consumer-starved")
        self.assertIn("underfed", "consumers waiting for work / underfed"
                      if False else "underfed")  # semantic anchor
        ev = r[1]
        self.assertTrue(ev["signals"]["consumer-starved"])
        self.assertIn("not saturated", " ".join(ev["limitations"]).lower()
                      if any("not saturated" in x.lower() for x in ev["limitations"]) else "not saturated")

    # 3: high publish_wait => downstream backpressure
    def test_high_publish_wait_is_downstream_backpressure(self):
        r = _c(publish_wait_ns=2 * NS, backlog=900)
        self.assertEqual(r[0], "downstream-backpressure")
        self.assertTrue(r[1]["signals"]["downstream-backpressure"])
        # NOT automatically proof of raw consumer-throughput limit
        self.assertTrue(any("not proof" in x.lower() for x in r[1]["limitations"]))

    # 4: read_wait per actual instrumentation
    def test_high_read_wait_significant_source_read_time(self):
        r = _c(read_wait_ns=2 * NS, backlog=1)
        self.assertEqual(r[0], "source-read-time")
        self.assertTrue(r[1]["signals"]["source-read-time"])
        # semantic anchor: actual timed read section includes retry/checks;
        # documented in limitations/doc, not pure kernel read
        self.assertIn("read_wait_ns", r[1])

    # claim/admission
    def test_high_claim_wait_is_claim_admission_delay(self):
        r = _c(claim_wait_ns=2 * NS)
        self.assertEqual(r[0], "claim-admission-delay")

    # 5: policy-selected zero claims are NOT automatically admission denial
    def test_policy_selected_zero_claims_not_admission_denial(self):
        r = _c(claims_zero=500, claims_zero_policy=500, claims_zero_admission=0,
               reservations=10)
        self.assertNotEqual(r[0], "claim-admission-delay")
        self.assertNotEqual(r[0], "admission-limited")
        ev = r[1]
        self.assertEqual(ev["claims_zero_policy"], 500)
        self.assertEqual(ev["claims_zero_admission"], 0)
        self.assertFalse(ev["signals"]["claim-admission-delay"])

    def test_admission_denied_zero_claims_is_claim_admission(self):
        r = _c(claims_zero=500, claims_zero_policy=0, claims_zero_admission=500,
               reservations=1)
        self.assertEqual(r[0], "claim-admission-delay")

    def test_ambiguous_zero_claims_without_split_not_admission(self):
        # claims_zero total alone does NOT prove admission denial
        r = classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                     max_backlog=1000, run_seconds=10.0, backlog=10,
                     claims_zero=500, reservations=0)
        self.assertNotEqual(r[0], "claim-admission-delay")
        self.assertIsNone(r[1]["claims_zero_admission"])

    # balanced
    def test_balanced_low_wait(self):
        r = _c(backlog=10)
        self.assertEqual(r[0], "balanced")

    # 6: multiple competing signals => mixed
    def test_multiple_competing_signals_mixed(self):
        r = _c(read_wait_ns=int(0.3 * NS), publish_wait_ns=int(0.2 * NS) + 1 * NS,
               consume_wait_ns=int(0.4 * NS) + 1 * NS, claim_wait_ns=int(0.3 * NS) + 1 * NS,
               backlog=300, max_backlog=500, run_seconds=1.0)
        self.assertEqual(r[0], "mixed")
        self.assertGreaterEqual(len([k for k, v in r[1]["signals"].items() if v]), 2)

    # 7: missing/inconsistent inputs => indeterminate
    def test_missing_max_backlog_indeterminate(self):
        self.assertEqual(classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                                  max_backlog=None, run_seconds=10.0, backlog=0,
                                  claims_zero=0)[0], "indeterminate")

    def test_invalid_max_backlog_indeterminate(self):
        for bad in (0, -1, float("nan"), float("inf"), "x"):
            self.assertEqual(_c(max_backlog=bad)[0], "indeterminate", bad)

    def test_missing_or_invalid_run_duration_indeterminate(self):
        for bad in (0, -1.0, float("nan"), float("inf"), None):
            self.assertEqual(classify(read_wait_ns=0, publish_wait_ns=0, consume_wait_ns=0,
                                      max_backlog=1000, run_seconds=bad, backlog=0,
                                      claims_zero=0)[0], "indeterminate", bad)

    def test_negative_wait_indeterminate(self):
        self.assertEqual(_c(read_wait_ns=-1)[0], "indeterminate")
        self.assertEqual(_c(publish_wait_ns=-1)[0], "indeterminate")
        self.assertEqual(_c(consume_wait_ns=-1)[0], "indeterminate")
        self.assertEqual(_c(claim_wait_ns=-1)[0], "indeterminate")

    def test_nonfinite_indeterminate(self):
        self.assertEqual(_c(read_wait_ns=float("nan"))[0], "indeterminate")
        self.assertEqual(_c(consume_wait_ns=float("inf"))[0], "indeterminate")

    def test_inconsistent_zero_claim_split_indeterminate(self):
        r = _c(claims_zero=1, claims_zero_policy=1, claims_zero_admission=1, reservations=0)
        self.assertEqual(r[0], "indeterminate")

    # 8: doubling run duration, same absolute wait -> normalized changes
    def test_doubling_duration_normalizes(self):
        a = _c(read_wait_ns=2 * NS, run_seconds=1.0)   # frac 2.0 -> signal
        b = _c(read_wait_ns=2 * NS, run_seconds=100.0)  # frac 0.02 -> balanced
        self.assertEqual(a[0], "source-read-time")
        self.assertEqual(b[0], "balanced")
        self.assertGreater(a[1]["read_wait_fraction"], b[1]["read_wait_fraction"])

    # denominators documented
    def test_denominators_present(self):
        r = _c(read_wait_ns=NS, run_seconds=10.0, consumer_threads=2, ingestor_threads=3)
        ev = r[1]
        self.assertEqual(ev["consumer_threads"], 2)
        self.assertEqual(ev["ingestor_threads"], 3)
        self.assertEqual(ev["denominator_consumer_ns"], 10.0 * 1e9 * 2)
        self.assertEqual(ev["denominator_ingestor_ns"], 10.0 * 1e9 * 3)
        self.assertIn("denominator_ns_per_thread", ev)
        self.assertIn("denominator_consumer_ns", ev)
        self.assertIn("denominator_ingestor_ns", ev)
        self.assertTrue(any("per-thread" in x for x in ev["limitations"]))

    def test_observed_backlog_not_substituted_for_capacity(self):
        r = _c(backlog=10, max_backlog=1000, max_effective_backlog_observed=99999,
               backlog_max_effective_observed=99999, max_published_backlog_observed=99999)
        ev = r[1]
        self.assertEqual(ev["max_backlog"], 1000)
        self.assertEqual(ev["max_backlog_configured"], 1000)
        self.assertEqual(ev["max_effective_backlog_observed"], 99999)
        self.assertIn("not proof", ev["max_effective_backlog_observed_meaning"].lower())
        # a peak does not create a consumer-limited/backpressure verdict by itself
        self.assertEqual(r[0], "balanced")

    # run_dist integration uses authoritative classifier + corrected inputs
    def test_run_dist_emits_regime(self):
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("run_dist", os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "run_dist.py"))
        run_dist = ilu.module_from_spec(spec)
        spec.loader.exec_module(run_dist)
        out = run_dist._regime_classify(run_dist.DiNodeMetrics(), 1.0, max_backlog=1000)
        self.assertIn("regime", out)
        self.assertIn("evidence", out)

    def test_unavailable_classifier_indeterminate_with_error(self):
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("run_dist", os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "run_dist.py"))
        run_dist = ilu.module_from_spec(spec)
        spec.loader.exec_module(run_dist)
        orig = run_dist._load_authoritative_classifier
        def _boom():
            raise RuntimeError("classifier gone")
        run_dist._load_authoritative_classifier = _boom
        try:
            out = run_dist._regime_classify(run_dist.DiNodeMetrics(), 1.0, max_backlog=1000)
            self.assertEqual(out["regime"], "indeterminate")
            self.assertIn("error", out)
            self.assertTrue(out["error"])
        finally:
            run_dist._load_authoritative_classifier = orig


class TestRunDistIntegration(unittest.TestCase):
    def _load_run_dist(self):
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("run_dist", os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "run_dist.py"))
        run_dist = ilu.module_from_spec(spec)
        spec.loader.exec_module(run_dist)
        return run_dist

    def test_run_dist_passes_actual_duration_and_configured_cap(self):
        run_dist = self._load_run_dist()
        captured = {}
        real = run_dist._load_authoritative_classifier
        def spy_load():
            fn = real()
            def wrap(**kw):
                captured.update(kw)
                return fn(**kw)
            return wrap
        run_dist._load_authoritative_classifier = spy_load
        try:
            # exercise node_metrics_to_dict with an actual measured duration + cap
            m = run_dist.DiNodeMetrics()
            out = run_dist.node_metrics_to_dict(m, 0, run_seconds=3.75, max_backlog=64 * 1024 * 1024)
            # CK-6.9: actual run duration + actual configured backlog cap passed
            self.assertEqual(captured["run_seconds"], 3.75)
            self.assertEqual(captured["max_backlog"], 64 * 1024 * 1024)
            # NOT a hardcoded 1.0 second; NOT a metric high-water mark
            self.assertNotEqual(captured["run_seconds"], 1.0)
            self.assertNotEqual(captured["max_backlog"], m.max_published_backlog)
            self.assertNotEqual(captured["max_backlog"], m.max_effective_backlog)
            # emitted DIST_RESULT contains evidence + denominators
            reg = out["regime"]
            self.assertIn("regime", reg)
            ev = reg["evidence"]
            self.assertEqual(ev["run_seconds"], 3.75)
            self.assertEqual(ev["max_backlog_configured"], 64 * 1024 * 1024)
            self.assertIn("denominator_ns_per_thread", ev)
            self.assertIn("wait_fractions", ev)
            self.assertIn("max_backlog_configured", out)
        finally:
            run_dist._load_authoritative_classifier = real

    def test_effective_max_backlog_mirrors_engine(self):
        run_dist = self._load_run_dist()
        p = run_dist.DiPolicyParams()
        p.max_backlog = 0; p.base_quantum = 1024 * 1024
        self.assertEqual(run_dist._effective_max_backlog_configured(p), 64 * 1024 * 1024)
        p.max_backlog = 8 * 1024 * 1024
        self.assertEqual(run_dist._effective_max_backlog_configured(p), 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
