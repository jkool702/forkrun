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


class TestReportDist(unittest.TestCase):
    def _dist_manifest(self, complete=True, wall=1.25, harness_wall=1.80, correct=True, validity=None, consumed=1000,
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
            self.assertIn("1/5", text)
            # all invalid/incomplete accounted for
            self.assertIn("failed/invalid/incomplete=4", text)
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
            self.assertIn("1/2", text)
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
            self.assertIn("| sc | fixed_faa | 3 | 3/3 | 1/3 | 1/3 | 0.001 | 2.000 |", text)
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
            self.assertIn("NO PERFORMANCE-VALID TRIALS", text)
            # headline performance medians must not substitute functional values
            self.assertIn("| sc | fixed_faa | 1 | 1/1 | 0/1 | 0/1 | n/a | n/a |", text)
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
            self.assertIn("MIXED KERNELS (full_byte_scan/none)", text)
            self.assertIn("not comparable", text.lower())
            # no headline performance medians when mixed kernels not comparable
            self.assertIn("| sc | fixed_faa | 2 | 2/2 | 2/2 | 2/2 | n/a | n/a |", text)
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


if __name__ == '__main__':
    unittest.main()



if __name__ == '__main__':
    unittest.main()
