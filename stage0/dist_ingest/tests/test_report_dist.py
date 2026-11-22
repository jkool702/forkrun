import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PKG))

REPORT = os.path.join(PKG, 'report_dist.py')


def make_campaign(tmp, outcomes, manifests):
    os.makedirs(tmp, exist_ok=True)
    camp = {
        "schema": "dist-campaign/3",
        "campaign_id": "test-camp",
        "source_sha": "deadbeef",
        "all_ok": False,
        "outcomes": outcomes,
        "campaign_config": {"consumer_kernel": "full_byte_scan", "strict_affinity": False, "strict_mbind": False},
    }
    with open(os.path.join(tmp, "campaign-manifest.json"), "w") as f:
        json.dump(camp, f)
    for rel, obj in manifests.items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if obj == "__UNREADABLE__":
            with open(path, "w") as f:
                f.write("{not json")
        elif obj is not None:
            with open(path, "w") as f:
                json.dump(obj, f)


def run_report(camp_dir):
    out = os.path.join(camp_dir, "report.md")
    p = subprocess.run([sys.executable, REPORT, "--campaign", camp_dir, "--out", out],
                       capture_output=True, text=True, cwd=REPO)
    text = ""
    if os.path.exists(out):
        with open(out) as f:
            text = f.read()
    return p.returncode, text, p.stderr


def _dist_manifest_base(complete=True, wall=1.25, harness_wall=1.80, correct=True, validity=None, consumed=1000,
                        kernel="full_byte_scan", scan_bytes=None, scan_ok=None):
    if scan_bytes is None:
        scan_bytes = consumed if kernel == "full_byte_scan" else 0
    if scan_ok is None:
        if kernel == "full_byte_scan":
            scan_ok = (scan_bytes == consumed)
        else:
            scan_ok = (scan_bytes == 0)
    dr = {
        "correct": correct,
        "wall_seconds": wall,
        "total_consumed": consumed,
        "reservations_total": 10,
        "ingest_cpu_ns": 123456,
        "consumer_kernel": {"name": kernel, "scan_bytes_evidence": {"total_consumer_bytes_scanned": scan_bytes, "scan_equals_consumed": scan_ok}},
        "nodes": [{"node": 0, "consumer_bytes_scanned": scan_bytes, "bytes_consumed": consumed, "max_effective_backlog": 1,
                   "affinity": {"ingestor": {"required": True, "requested": False, "applicable": True, "set_applied": False, "query_succeeded": False, "matched": False},
                                "consumer": {"required": True, "requested": False, "applicable": True, "set_applied": False, "query_succeeded": False, "matched": False}},
                   "memory_policy": {"requested_count": 0, "success_count": 0, "failure_count": 0, "all_requested_succeeded": False, "error": 0},
                   "placement": {"local_pages_on_target_node": 0, "remote_pages_other_node": 0, "unknown_pages": 0, "sampled_pages": 0}}],
        "validity": validity or {
            "functional_correctness": correct,
            "performance_measurement": None if correct else False,
            "affinity": None,
            "memory_policy_application": None,
            "placement_observed": None,
            "numa_placement": None,
        },
        "rc": 0 if correct else 1,
        "overlap_detected": False, "lost_detected": False, "duplicate_detected": False,
    }
    return {
        "complete": complete,
        "incomplete_reasons": [] if complete else ["missing child_report"],
        "wall_s": harness_wall,
        "map_s": None,
        "child_report": {"completed_bytes": consumed},
        "dist_result": dr,
    }


class TestReportDist(unittest.TestCase):
    _dist_manifest = staticmethod(_dist_manifest_base)

    def test_denominators_include_failed_missing_unreadable_incomplete(self):
        tmp = tempfile.mkdtemp(prefix='rpt_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 2, "status": "failed", "manifest": "cases/a/trial2/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 3, "status": "ok", "manifest": "cases/a/trial3/manifest.json"},  # missing file
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 4, "status": "ok", "manifest": "cases/a/trial4/manifest.json"},  # unreadable
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 5, "status": "ok", "manifest": "cases/a/trial5/manifest.json"},  # incomplete
            ]
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True),
                # trial2: status failed, manifest may not matter but missing is fine
                "cases/a/trial4/manifest.json": "__UNREADABLE__",
                "cases/a/trial5/manifest.json": self._dist_manifest(complete=False, correct=False),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # 5 attempted trials total for scenario/candidate; only 1 functionally valid
            # 5 attempted performance trials total for scenario/candidate; only 1 functionally complete
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 5 | 1 | 0 | 0 |", text)
            # all invalid/incomplete accounted for (performance-class)
            self.assertIn("invalid/incomplete=4", text)
            self.assertIn("no-performance-valid-trials", text)
            self.assertIn("unreadable", text.lower())
            self.assertIn("missing manifest", text.lower())
            self.assertIn("incomplete", text.lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dist_wall_time_authoritative_not_harness(self):
        tmp = tempfile.mkdtemp(prefix='rptw_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
            ]
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, wall=1.111, harness_wall=9.999, correct=True),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # engine wall (1.111) and harness wall (9.999/10.0) shown separately; engine authoritative in summary column
            self.assertIn("1.111", text)
            self.assertIn("9.999", text)  # harness shown separately
            self.assertIn("engine wall", text.lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_per_dimension_validity_unknown_distinct_from_false(self):
        tmp = tempfile.mkdtemp(prefix='rptv_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
            ]
            validity = {
                "functional_correctness": True,
                "performance_measurement": None,
                "affinity": None,
                "memory_policy_application": True,
                "placement_observed": False,
                "numa_placement": False,
            }
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True, validity=validity),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # unknown and false both appear distinctly
            self.assertIn("unknown", text)
            self.assertIn("false", text)
            self.assertIn("affinity=unknown", text)
            self.assertIn("placement_obs=false", text)
            self.assertIn("numa=false", text)
            # kernel/scan evidence surfaced
            self.assertIn("full_byte_scan", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_mixture_valid_and_invalid_attempts(self):
        tmp = tempfile.mkdtemp(prefix='rptm_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 2, "status": "ok", "manifest": "cases/a/trial2/manifest.json"},
            ]
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True),
                "cases/a/trial2/manifest.json": self._dist_manifest(complete=True, correct=False),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # 2 attempted performance trials, 1 functionally complete, 0 perf-valid
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 2 | 1 | 0 | 0 |", text)
            self.assertIn("no-performance-valid-trials", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_headline_performance_medians_use_performance_valid_only(self):
        tmp = tempfile.mkdtemp(prefix='rptperf_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 2, "status": "ok", "manifest": "cases/a/trial2/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 3, "status": "ok", "manifest": "cases/a/trial3/manifest.json"},
            ]
            v_true = {"functional_correctness": True, "performance_measurement": True, "affinity": True,
                      "memory_policy_application": True, "placement_observed": True, "numa_placement": True}
            v_unknown = {"functional_correctness": True, "performance_measurement": None, "affinity": None,
                         "memory_policy_application": None, "placement_observed": None, "numa_placement": None}
            v_false = {"functional_correctness": True, "performance_measurement": False, "affinity": False,
                       "memory_policy_application": True, "placement_observed": None, "numa_placement": False}
            # perf-valid trial: 2.0s for 1000 bytes => 500 B/s => 0.001 MB/s (rounded in report)
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True, wall=2.0, consumed=1000, validity=v_true),
                "cases/a/trial2/manifest.json": self._dist_manifest(complete=True, correct=True, wall=0.5, consumed=1000, validity=v_unknown),
                "cases/a/trial3/manifest.json": self._dist_manifest(complete=True, correct=True, wall=0.25, consumed=1000, validity=v_false),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # only trial 1 is performance-valid: median engine wall 2.000, throughput 0.001 MB/s
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 3 | 3 | 1 | 1 | 0.001 | 2.000 |", text)
            self.assertIn("func-but-perf-invalid/unknown=2", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_performance_valid_trials_obvious(self):
        tmp = tempfile.mkdtemp(prefix='rptnoperf_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
            ]
            v_unknown = {"functional_correctness": True, "performance_measurement": None, "affinity": None,
                         "memory_policy_application": None, "placement_observed": None, "numa_placement": None}
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True, wall=1.5, consumed=1000, validity=v_unknown),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            self.assertIn("no-performance-valid-trials", text)
            # headline performance medians must not substitute functional values
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 0 | 0 | n/a | n/a |", text)
            # functional-but-perf-invalid/unknown trial retained in detail with raw throughput info
            self.assertIn("engine_wall=1.500000", text)
            self.assertIn("valid[func=true perf=unknown", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_mixed_full_scan_and_none_not_comparable(self):
        tmp = tempfile.mkdtemp(prefix='rptmixk_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 2, "status": "ok", "manifest": "cases/a/trial2/manifest.json"},
            ]
            v_true = {"functional_correctness": True, "performance_measurement": True, "affinity": True,
                      "memory_policy_application": True, "placement_observed": True, "numa_placement": True}
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True, wall=1.0, consumed=1000, validity=v_true, kernel='full_byte_scan', scan_bytes=1000, scan_ok=True),
                "cases/a/trial2/manifest.json": self._dist_manifest(complete=True, correct=True, wall=0.5, consumed=1000, validity=v_true, kernel='none', scan_bytes=0, scan_ok=True),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            self.assertIn("mixed-kernels-not-comparable", text)
            # no headline performance medians when mixed kernels not comparable
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 2 | 2 | 2 | 2 | n/a | n/a |", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_functional_but_perf_invalid_unknown_trials_retained_with_evidence(self):
        tmp = tempfile.mkdtemp(prefix='rptretain_')
        try:
            outcomes = [
                {"case": "sc__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok", "manifest": "cases/a/trial1/manifest.json"},
            ]
            v = {"functional_correctness": True, "performance_measurement": False, "affinity": False,
                 "memory_policy_application": True, "placement_observed": None, "numa_placement": False}
            manifests = {
                "cases/a/trial1/manifest.json": self._dist_manifest(complete=True, correct=True, wall=3.0, consumed=2000, validity=v),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # retained in detail with raw throughput-relevant info and validity reasons/dimensions
            self.assertIn("engine_wall=3.000000", text)
            self.assertIn("scanned=2000 consumed=2000", text)
            self.assertIn("perf=false", text)
            self.assertIn("affinity=false", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



class TestCheckpoint2PlacementSamplingReporting(unittest.TestCase):
    """C2: placement-validation experiments are distinct and excluded from headline performance stats."""

    def _perf_manifest(self, wall=1.0, consumed=1000):
        v_true = {"functional_correctness": True, "performance_measurement": True, "affinity": True,
                  "memory_policy_application": True, "placement_observed": True, "numa_placement": True}
        dr = {
            "correct": True,
            "wall_seconds": wall,
            "total_consumed": consumed,
            "reservations_total": 10,
            "ingest_cpu_ns": 123456,
            "trial_class": "performance",
            "linked_performance_trial": None,
            "measurement_integrity": {
                "placement_sampling": "off",
                "placement_sampling_mode": 0,
                "timing_tainted_by_in_run_sampling": False,
                "performance_isolated": True,
                "linked_performance_trial": None,
            },
            "consumer_kernel": {"name": "full_byte_scan", "scan_bytes_evidence": {"total_consumer_bytes_scanned": consumed, "scan_equals_consumed": True}},
            "nodes": [{"node": 0, "consumer_bytes_scanned": consumed, "bytes_consumed": consumed, "max_effective_backlog": 1,
                       "affinity": {"ingestor": {"required": True, "requested": True, "applicable": True, "set_applied": True, "query_succeeded": True, "matched": True},
                                    "consumer": {"required": True, "requested": True, "applicable": True, "set_applied": True, "query_succeeded": True, "matched": True}},
                       "memory_policy": {"requested_count": 1, "success_count": 1, "failure_count": 0, "all_requested_succeeded": True, "error": 0},
                       "placement": {"local_pages_on_target_node": 10, "remote_pages_other_node": 0, "unknown_pages": 0, "sampled_pages": 0, "sampling_not_performed": True}}],
            "validity": v_true,
            "rc": 0, "overlap_detected": False, "lost_detected": False, "duplicate_detected": False,
        }
        return {"complete": True, "incomplete_reasons": [], "wall_s": 1.5, "map_s": None,
                "child_report": {"completed_bytes": consumed}, "dist_result": dr}

    def _placement_validation_manifest(self, linked, wall=1.2, consumed=1000):
        v_pv = {"functional_correctness": True, "performance_measurement": False, "affinity": True,
                "memory_policy_application": True, "placement_observed": True, "numa_placement": True}
        dr = {
            "correct": True,
            "wall_seconds": wall,
            "total_consumed": consumed,
            "reservations_total": 10,
            "ingest_cpu_ns": 123456,
            "trial_class": "placement_validation",
            "linked_performance_trial": linked,
            "measurement_integrity": {
                "placement_sampling": "on",
                "placement_sampling_mode": 1,
                "timing_tainted_by_in_run_sampling": True,
                "performance_isolated": False,
                "linked_performance_trial": linked,
            },
            "consumer_kernel": {"name": "full_byte_scan", "scan_bytes_evidence": {"total_consumer_bytes_scanned": consumed, "scan_equals_consumed": True}},
            "nodes": [{"node": 0, "consumer_bytes_scanned": consumed, "bytes_consumed": consumed, "max_effective_backlog": 1,
                       "affinity": {"ingestor": {"required": True, "requested": True, "applicable": True, "set_applied": True, "query_succeeded": True, "matched": True},
                                    "consumer": {"required": True, "requested": True, "applicable": True, "set_applied": True, "query_succeeded": True, "matched": True}},
                       "memory_policy": {"requested_count": 1, "success_count": 1, "failure_count": 0, "all_requested_succeeded": True, "error": 0},
                       "placement": {"local_pages_on_target_node": 10, "remote_pages_other_node": 0, "unknown_pages": 0, "sampled_pages": 10, "sampling_not_performed": False}}],
            "validity": v_pv,
            "rc": 0, "overlap_detected": False, "lost_detected": False, "duplicate_detected": False,
        }
        return {"complete": True, "incomplete_reasons": [], "wall_s": 1.7, "map_s": None,
                "child_report": {"completed_bytes": consumed}, "dist_result": dr}

    def test_placement_validation_excluded_from_headline_performance_stats(self):
        tmp = tempfile.mkdtemp(prefix='rptc2_')
        try:
            linked = "cases/sc__legacy__fixed_faa/trial1/manifest.json"
            outcomes = [
                {"case": "sc__legacy__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok",
                 "manifest": "cases/sc__legacy__fixed_faa/trial1/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "performance", "placement_sampling": "off", "linked_performance_trial": None},
                {"case": "sc__legacy__fixed_faa__placement_validation", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok",
                 "manifest": "cases/sc__legacy__fixed_faa__placement_validation/trial1/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "placement_validation", "placement_sampling": "on", "linked_performance_trial": linked},
            ]
            manifests = {
                "cases/sc__legacy__fixed_faa/trial1/manifest.json": self._perf_manifest(wall=2.0, consumed=1000),
                "cases/sc__legacy__fixed_faa__placement_validation/trial1/manifest.json": self._placement_validation_manifest(linked=linked, wall=0.1, consumed=1000),
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # headline stats must reflect only the performance trial (2.0s, 0.001 MB/s), not the placement-validation trial
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 1 | 1 | 0.001 | 2.000 |", text)
            self.assertIn("placement-validation=1(distinct,excluded)", text)
            # placement-validation reported separately and linked
            self.assertIn("## Placement-validation experiments (distinct from performance trials; not mixed into headline statistics)", text)
            self.assertIn(linked, text)
            self.assertIn("placement_validation", text)
            self.assertIn("timing-tainted-by-sampling", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_or_unreadable_placement_validation_preserves_classification(self):
        tmp = tempfile.mkdtemp(prefix='rptc2fail_')
        try:
            linked = "cases/sc__legacy__fixed_faa/trial1/manifest.json"
            outcomes = [
                {"case": "sc__legacy__fixed_faa", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "ok",
                 "manifest": "cases/sc__legacy__fixed_faa/trial1/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "performance", "placement_sampling": "off", "linked_performance_trial": None},
                {"case": "sc__legacy__fixed_faa__placement_validation", "scenario": "sc", "candidate": "fixed_faa", "trial": 1, "status": "failed",
                 "manifest": "cases/pv_fail/trial1/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "placement_validation", "placement_sampling": "on", "linked_performance_trial": linked},
                {"case": "sc__legacy__fixed_faa__placement_validation", "scenario": "sc", "candidate": "fixed_faa", "trial": 2, "status": "ok",
                 "manifest": "cases/pv_missing/trial2/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "placement_validation", "placement_sampling": "on", "linked_performance_trial": linked},
                {"case": "sc__legacy__fixed_faa__placement_validation", "scenario": "sc", "candidate": "fixed_faa", "trial": 3, "status": "ok",
                 "manifest": "cases/pv_unreadable/trial3/manifest.json", "mapping_id": "legacy", "mapping_profile": "auto",
                 "trial_class": "placement_validation", "placement_sampling": "on", "linked_performance_trial": linked},
            ]
            manifests = {
                "cases/sc__legacy__fixed_faa/trial1/manifest.json": self._perf_manifest(wall=2.0, consumed=1000),
                # pv_fail: no manifest file
                # pv_missing: no manifest file
                "cases/pv_unreadable/trial3/manifest.json": "__UNREADABLE__",
            }
            make_campaign(tmp, outcomes, manifests)
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            # performance-class denominator/stats must include only the performance trial
            self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 1 | 1 | 0.001 | 2.000 |", text)
            self.assertIn("placement-validation=3(distinct,excluded)", text)
            # failed/missing/unreadable placement-validation outcomes remain classified and linked
            self.assertIn("## Placement-validation experiments (distinct from performance trials; not mixed into headline statistics)", text)
            self.assertEqual(text.count("| sc | legacy | pset__default | fixed_faa |"), 4)  # 1 summary row + 3 placement-validation rows
            self.assertIn(linked, text)
            self.assertIn("placement_validation", text)
            self.assertIn("placement sampling | complete", text)  # section header present
            # invalid visibility
            self.assertIn("trial status failed or missing manifest", text)
            self.assertIn("manifest unreadable", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



class TestReportDistRepeatedTrials(unittest.TestCase):
    """C3-corrections-2: repeated trials report the QUALIFIED AGGREGATE.

    The headline shows the aggregate measurement for repeated trials; the
    pass-1 result stays as provenance in the per-trial detail section.
    Aggregate metrics are labeled separately from individual-pass metrics,
    and invalid/excluded aggregates are reported explicitly.
    """

    _dist_manifest = staticmethod(_dist_manifest_base)

    V_TRUE = {"functional_correctness": True, "performance_measurement": True,
              "affinity": True, "memory_policy_application": True,
              "placement_observed": True, "numa_placement": True}

    def _repeated_manifest(self, pass1_wall=1.0, agg_t=5.0, agg_b=2000000,
                           agg_scan=2000000, agg_res=20, valid=True,
                           invalid_reasons=None, stop="target_reached",
                           failed_pass2=False):
        m = self._dist_manifest(complete=True, wall=pass1_wall, consumed=1000,
                                validity=self.V_TRUE)
        p2 = {"pass": 2, "is_initial_pass": False,
              "engine_wall_seconds": agg_t - pass1_wall,
              "total_consumed": agg_b - 1000,
              "reservations_total": agg_res - 10,
              "performance_validity": True, "cache_compatible": True,
              "qualified": not failed_pass2, "duration_contributes": not failed_pass2}
        if failed_pass2:
            p2.update({"status": "failed_execution", "qualified": False,
                       "duration_contributes": False, "failure_reason": "process returncode 1"})
        else:
            p2.update({"status": "success"})
        p1 = {"pass": 1, "is_initial_pass": True, "status": "success",
              "qualified": True, "duration_contributes": True,
              "engine_wall_seconds": pass1_wall, "total_consumed": 1000,
              "reservations_total": 10, "performance_validity": True,
              "cache_compatible": True}
        agg = {
            "contributing_passes": ([1] if failed_pass2 else [1, 2]),
            "excluded_passes": [],
            "pass_count": (1 if failed_pass2 else 2),
            "aggregate_engine_wall_seconds": agg_t,
            "aggregate_consumed_bytes": agg_b,
            "aggregate_scanned_bytes": agg_scan,
            "aggregate_scan_equals_consumed": True,
            "aggregate_reservations": agg_res,
            "aggregate_throughput_bps": (agg_b / agg_t) if agg_t else None,
            "aggregate_valid": valid,
            "aggregate_invalid_reasons": (invalid_reasons or []),
        }
        m["duration_qualification"] = {
            "target_seconds": 0.5, "repetition_used": True,
            "pass_count": (1 if failed_pass2 else 2),
            "accumulated_effective_wall_seconds": agg_t,
            "meets_target": True, "stop_reason": stop,
            "duration_aggregate": agg,
            "passes": [p1, p2],
        }
        m["duration_aggregate"] = agg
        return m

    def _run_one_trial(self, manifest):
        tmp = tempfile.mkdtemp(prefix='rptrep_')
        try:
            outcomes = [{"case": "sc__fixed_faa", "scenario": "sc",
                         "candidate": "fixed_faa", "trial": 1, "status": "ok",
                         "manifest": "cases/a/trial1/manifest.json"}]
            make_campaign(tmp, outcomes, {"cases/a/trial1/manifest.json": manifest})
            rc, text, err = run_report(tmp)
            self.assertEqual(rc, 0, msg=err + "\n" + text)
            return text
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repeated_trial_headline_uses_aggregate(self):
        # aggregate: T=5s, B=2,000,000 -> 400,000 B/s -> 0.400 MB/s; wall 5.000
        text = self._run_one_trial(self._repeated_manifest())
        self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 1 | 1 | 0.400 | 5.000 |", text)
        # headline scan/consumed use the aggregate, not the pass-1 provenance
        row = [l for l in text.splitlines() if l.startswith("| sc | legacy | pset__default | fixed_faa |")][0]
        self.assertIn("2000000/2000000", row)
        self.assertIn("duration-repeated(trials=1)", text)
        # per-trial detail: aggregate metrics + pass evidence
        self.assertIn("duration_aggregate: contributing=[1, 2] engine_wall=5.000", text)
        self.assertIn("duration_pass: pass=1 initial=true status=success", text)
        self.assertIn("duration_pass: pass=2 initial=false status=success", text)
        self.assertIn("stop_reason=target_reached", text)

    def test_repeated_trial_invalid_aggregate_reported_explicitly(self):
        text = self._run_one_trial(self._repeated_manifest(
            valid=False, invalid_reasons=["pass 2 performance validity=unknown"]))
        row = [l for l in text.splitlines() if l.startswith("| sc | legacy | pset__default | fixed_faa |")][0]
        # pass 1 is valid (provenance) but the invalid aggregate must exclude
        # the trial from the perf-valid headline count: no misleading
        # pass-1 throughput/wall is used.
        self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 0 |", row)
        self.assertIn("n/a", row)
        self.assertIn("duration-aggregate-invalid(trials=1)", text)
        self.assertIn("valid=false", text)
        self.assertIn("pass 2 performance validity=unknown", text)

    def _not_launched_manifest(self):
        """Manifest where preconditioning exhausted the budget: pass 2 was
        never launched. Pass 2 is preserved as evidence but must not count
        as a repetition or as a failed execution."""
        m = self._dist_manifest(complete=True, wall=1.0, consumed=1000,
                                validity=self.V_TRUE)
        p1 = {"pass": 1, "is_initial_pass": True, "status": "success",
              "qualified": True, "duration_contributes": True,
              "engine_wall_seconds": 1.0, "total_consumed": 1000,
              "reservations_total": 10, "performance_validity": True,
              "cache_compatible": True}
        p2 = {"pass": 2, "is_initial_pass": False,
              "status": "not_launched_budget_exhausted",
              "qualified": False, "duration_contributes": False,
              "failure_reason": "repetition budget exhausted during cache preconditioning",
              "engine_wall_seconds": None, "total_consumed": None,
              "reservations_total": None, "performance_validity": None,
              "cache_compatible": True}
        agg = {
            "contributing_passes": [1],
            "excluded_passes": [],
            "pass_count": 1,
            "aggregate_engine_wall_seconds": 1.0,
            "aggregate_consumed_bytes": 1000,
            "aggregate_scanned_bytes": 1000,
            "aggregate_scan_equals_consumed": True,
            "aggregate_reservations": 10,
            "aggregate_throughput_bps": 1000.0,
            "aggregate_valid": True,
            "aggregate_invalid_reasons": [],
        }
        m["duration_qualification"] = {
            "target_seconds": 999.0, "repetition_used": False,
            "pass_count": 2,
            "accumulated_effective_wall_seconds": 1.0,
            "meets_target": False, "stop_reason": "repetition_budget_exhausted",
            "duration_aggregate": agg,
            "passes": [p1, p2],
        }
        m["duration_aggregate"] = agg
        return m

    def test_repeated_trial_budget_exhaustion_not_launched_pass_not_counted(self):
        text = self._run_one_trial(self._not_launched_manifest())
        # one-pass headline semantics: pass-1 metrics, no aggregate switch
        row = [l for l in text.splitlines() if l.startswith("| sc | legacy | pset__default | fixed_faa |")][0]
        self.assertIn("| sc | legacy | pset__default | fixed_faa | 1 | 1 | 1 | 1 | 0.001 | 1.000 |", row)
        # no duration-repeated note: repetition_used is False (no repeat launched)
        self.assertNotIn("duration-repeated", text)
        # the unlaunched attempt is classified separately, not as a failure
        self.assertIn("duration-not-launched(trials=1)", text)
        self.assertNotIn("duration-failed-passes", text)
        self.assertIn("duration-stop=repetition_budget_exhausted", text)
        # the not-launched pass is still preserved as evidence
        self.assertIn("duration_pass: pass=2 initial=false status=not_launched_budget_exhausted", text)

    def test_repeated_trial_failed_passes_identified(self):
        text = self._run_one_trial(self._repeated_manifest(failed_pass2=True,
                                                           stop="pass_execution_failure"))
        self.assertIn("duration-failed-passes(trials=1)", text)
        self.assertIn("duration_pass: pass=2 initial=false status=failed_execution", text)
        self.assertIn("contributes=false", text)
        # pass 1 remains the provenance
        self.assertIn("duration_pass: pass=1 initial=true status=success", text)


if __name__ == '__main__':
    unittest.main()
