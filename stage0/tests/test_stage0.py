#!/usr/bin/env python3
"""Stage 0 harness acceptance tests (work order §10).

These tests exercise the REAL report validator, queue parser, ablation
validator, timeout containment, and campaign driver. They are not
source-text assertions: a fixture is mutated and the authoritative
component must reject it; a case is run and its process group must be
gone.

Run from the repository root:
  python3 -m unittest discover -s stage0/tests -p "test_*.py" -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE0 = os.path.dirname(HERE)
REPO = os.path.dirname(STAGE0)
sys.path.insert(0, STAGE0)

import campaign_manifest  # noqa: E402
import report  # noqa: E402
import run_case  # noqa: E402

SHA = "a" * 40


def write_json(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def env_doc():
    return {
        "git": {"head_sha": SHA, "branch": "test", "dirty": False},
        "kernel": {"release": "test-kernel", "fake_numa": True,
                   "fake_numa_spec": "numa=fake=4"},
        "thp": {"shmem_enabled": "always"},
        "cpu_topology": {"nodes": {"node0": {}, "node1": {}}},
    }


def trial_manifest(cid="campaign-1", trial=1, case="case-a",
                   spec_sha="b" * 64):
    return {
        "schema": "stage0-case/3",
        "campaign_id": cid,
        "source_sha": SHA,
        "spec_id": case,
        "spec_sha256": spec_sha,
        "trial": trial,
        "spec": {"id": case, "source_kind": "file", "workers": 4,
                 "nodes": 1, "mode": "udf"},
        "complete": True,
        "timed_out": False,
        "returncode": 0,
        "child_report": {"rec_per_s": 1000.0, "elapsed_s": 2.5,
                         "completed_records": 1000},
        "map_s": 2.5,
        "wall_s": 3.0,
        "cpu_per_core_basis": 1.0,
        "ingest_cpu_basis_cores": 0.9,
        "rss_peak_kb": 1024,
        "diagnostics": {
            "samples": 3,
            "finals": 1,
            "queue_present": True,
            "forkrun_diag_queue": "1",
        },
        "case_group_gone": {"gone": True, "members_after": []},
    }


def make_campaign(root, cid="campaign-1"):
    """Create one valid campaign; returns (manifest_path, spec_path)."""
    spec_path = os.path.join(root, "specs", "case-a.json")
    spec = {"id": "case-a", "input": "stage0/corpus/light_100k.txt",
            "workers": 4, "nodes": 1, "mode": "udf"}
    write_json(spec_path, spec)
    spec_sha = campaign_manifest.sha256(spec_path)

    camp = os.path.join(root, "campaign")
    os.makedirs(os.path.join(camp, "cases", "case-a", "trial1"))
    os.makedirs(os.path.join(camp, "env"))
    write_json(os.path.join(camp, "cases", "case-a", "trial1",
                            "manifest.json"),
               trial_manifest(cid=cid, spec_sha=spec_sha))
    with open(os.path.join(camp, "cases", "case-a", "trial1",
                           "stderr.log"), "w", encoding="utf-8") as fh:
        fh.write("STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 "
                 "lim=4 gated_ms=0 q=n0:0,0 b=n0:0,0 c=n0:0 a=n0:0,1\n")
        fh.write("STAGE0_FINAL src=scan t_ms=10 moved=10 major=0 tgt=0 "
                 "lim=4 gated_ms=0 q=n0:1,1 b=n0:1,1 c=n0:1 a=n0:0,1\n")
    write_json(os.path.join(camp, "env", "env-before.json"), env_doc())
    write_json(os.path.join(camp, "env", "env-after.json"), env_doc())
    manifest = {
        "schema": "stage0-campaign/2",
        "campaign_id": cid,
        "source_sha": SHA,
        "trials_requested": 1,
        "specs": [{"id": "case-a", "path": "specs/case-a.json",
                   "sha256": spec_sha}],
        "expected_cases": ["case-a"],
        "outcomes": [{"case": "case-a", "trial": 1, "status": "ok",
                      "manifest": "cases/case-a/trial1/manifest.json"}],
        "state": "complete",
        "env_before": "env/env-before.json",
        "env_after": "env/env-after.json",
        "forkrun_diag_queue": "1",
    }
    path = os.path.join(camp, "campaign-manifest.json")
    write_json(path, manifest)
    return path, spec_path


class TestReportRejection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stage0-report-")
        self.path, _ = make_campaign(self.tmp)
        self.camp = os.path.dirname(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_campaign_loads(self):
        doc = report.load_campaign(self.path)
        self.assertEqual(doc["campaign_id"], "campaign-1")
        self.assertEqual(doc["expected_cases"], ["case-a"])

    def test_missing_case_is_rejected(self):
        shutil.rmtree(os.path.join(self.camp, "cases", "case-a"))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        text = " ".join(ctx.exception.problems)
        self.assertIn("cases/", text)

    def test_missing_outcome_is_rejected(self):
        manifest = read_json(self.path)
        manifest["outcomes"] = []
        write_json(self.path, manifest)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("missing outcomes", " ".join(ctx.exception.problems))

    def test_missing_diagnostics_is_rejected(self):
        mpath = os.path.join(self.camp, "cases", "case-a", "trial1",
                             "manifest.json")
        trial = read_json(mpath)
        trial["diagnostics"]["queue_present"] = False
        write_json(mpath, trial)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("missing STAGE0_DIAG",
                      " ".join(ctx.exception.problems))

    def test_diagnostics_env_must_be_one(self):
        mpath = os.path.join(self.camp, "cases", "case-a", "trial1",
                             "manifest.json")
        trial = read_json(mpath)
        trial["diagnostics"]["forkrun_diag_queue"] = None
        write_json(mpath, trial)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("FORKRUN_DIAG_QUEUE",
                      " ".join(ctx.exception.problems))

    def test_stale_campaign_id_is_rejected(self):
        mpath = os.path.join(self.camp, "cases", "case-a", "trial1",
                             "manifest.json")
        trial = read_json(mpath)
        trial["campaign_id"] = "campaign-OLD"
        write_json(mpath, trial)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("stale/mixed", " ".join(ctx.exception.problems))

    def test_malformed_trial_json_is_rejected(self):
        mpath = os.path.join(self.camp, "cases", "case-a", "trial1",
                             "manifest.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("malformed JSON", " ".join(ctx.exception.problems))

    def test_extra_trial_directory_is_rejected(self):
        os.makedirs(os.path.join(self.camp, "cases", "case-a", "trial2"))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("trials on disk", " ".join(ctx.exception.problems))

    def test_missing_env_after_is_rejected(self):
        os.remove(os.path.join(self.camp, "env", "env-after.json"))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("env-after", " ".join(ctx.exception.problems))

    def test_cli_writes_invalid_report_and_exits_2(self):
        mpath = os.path.join(self.camp, "cases", "case-a", "trial1",
                             "manifest.json")
        trial = read_json(mpath)
        trial["campaign_id"] = "campaign-OLD"
        write_json(mpath, trial)
        out = os.path.join(self.tmp, "report.md")
        proc = subprocess.run(
            [sys.executable, os.path.join(STAGE0, "report.py"),
             "--campaign", self.path, "--out", out],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("INVALID", fh.read())


class TestQueueTelemetry(unittest.TestCase):
    def _stats(self, lines):
        return report._trial_queue_stats(report._diag_records("\n".join(lines)))

    def test_per_node_empty_conditions_and_real_duration(self):
        lines = [
            "STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0;n1:0,0 b=n0:0,10;n1:0,0 "
            "c=n0:0;n1:0 a=n0:0,2;n1:0,2",
            "STAGE0_DIAG src=scan t_ms=100 moved=100 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0;n1:0,0 b=n0:10,20;n1:0,0 "
            "c=n0:10;n1:0 a=n0:0,2;n1:1,2",
            "STAGE0_DIAG src=scan t_ms=200 moved=200 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0;n1:0,0 b=n0:20,30;n1:0,0 "
            "c=n0:20;n1:0 a=n0:0,2;n1:2,2",
            "STAGE0_FINAL src=scan t_ms=300 moved=300 major=0 tgt=0 lim=4 "
            "gated_ms=42 q=n0:0,0;n1:0,0 b=n0:30,30;n1:0,0 "
            "c=n0:30;n1:0 a=n0:0,2;n1:2,2",
        ]
        stats = self._stats(lines)
        self.assertAlmostEqual(stats["duration_s"], 0.3)
        self.assertEqual(stats["gated_ms"], 42)
        self.assertEqual(sorted(stats["nodes"]), [0, 1])
        self.assertAlmostEqual(stats["nodes"][0]["nonempty_fraction"], 1.0)
        self.assertAlmostEqual(stats["nodes"][1]["nonempty_fraction"], 0.0)
        self.assertAlmostEqual(stats["all_empty_fraction"], 0.0)
        self.assertAlmostEqual(stats["any_nonempty_fraction"], 1.0)
        self.assertIsNotNone(stats["nodes"][0]["published_batches_per_s"])
        self.assertIsNotNone(stats["nodes"][0]["claimed_batches_per_s"])
        self.assertAlmostEqual(stats["nodes"][0]["claimed_batches_per_s"],
                               20 / 0.3)

    def test_trial_boundaries_are_never_joined(self):
        tmp = tempfile.mkdtemp(prefix="stage0-queue-")
        try:
            d1 = os.path.join(tmp, "trial1")
            d2 = os.path.join(tmp, "trial2")
            os.makedirs(d1)
            os.makedirs(d2)
            with open(os.path.join(d1, "stderr.log"), "w",
                      encoding="utf-8") as fh:
                fh.write("STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 "
                         "tgt=0 lim=4 gated_ms=0 q=n0:0,0 b=n0:0,1 "
                         "c=n0:0 a=n0:0,1\n")
                fh.write("STAGE0_FINAL src=scan t_ms=100 moved=1 major=0 "
                         "tgt=0 lim=4 gated_ms=0 q=n0:0,0 b=n0:1,1 "
                         "c=n0:1 a=n0:0,1\n")
            with open(os.path.join(d2, "stderr.log"), "w",
                      encoding="utf-8") as fh:
                fh.write("STAGE0_DIAG src=scan t_ms=5000 moved=0 major=0 "
                         "tgt=0 lim=4 gated_ms=0 q=n0:0,0 b=n0:0,1 "
                         "c=n0:0 a=n0:0,1\n")
                fh.write("STAGE0_FINAL src=scan t_ms=5100 moved=1 major=0 "
                         "tgt=0 lim=4 gated_ms=0 q=n0:0,0 b=n0:1,1 "
                         "c=n0:1 a=n0:0,1\n")
            agg = report.queue_demand_stats({
                "case": [({}, d1), ({}, d2)]})
            self.assertAlmostEqual(agg["case"]["duration_s"], 0.1)
            self.assertEqual(agg["case"]["samples"], 4)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_final_only_is_a_valid_sample(self):
        stats = self._stats([
            "STAGE0_FINAL src=ingest t_ms=4 moved=10 major=0 tgt=0 lim=4 "
            "gated_ms=7 q=n0:1,1 b=n0:1,1 c=n0:1 a=n0:0,1"])
        self.assertEqual(stats["samples"], 1)
        self.assertEqual(stats["gated_ms"], 7)
        self.assertIn(0, stats["nodes"])

    def test_malformed_group_is_ignored(self):
        self.assertEqual(report._parse_group("n0:1,2;nope:3;n1:x"),
                         {0: (1, 2)})


class TestAblationValidation(unittest.TestCase):
    def _doc(self):
        return {
            "schema": "stage0-ablation/2",
            "campaign_id": "campaign-1",
            "nodes": {"x": 0, "y": 1},
            "results": [
                {"cell": "A", "form": "map-fault", "valid": True,
                 "policy_requested": {"mode_numeric": 0},
                 "effective": {"mempolicy_mode": 0},
                 "placement_measured": True},
                {"cell": "C", "form": "write-path", "valid": True,
                 "policy_requested": {"mode_numeric": 2},
                 "effective": {"mempolicy_mode": 2,
                               "mempolicy_mask_nodes": [1]},
                 "placement_measured": True,
                 "read_touch_stable": True},
            ],
        }

    def test_valid_ablation_passes(self):
        ok, problems = report.ablation_ok(self._doc(), "campaign-1")
        self.assertTrue(ok, problems)

    def test_preferred_mode_is_rejected(self):
        doc = self._doc()
        doc["results"][1]["policy_requested"]["mode_numeric"] = 1
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("MPOL_BIND" in p for p in problems))

    def test_default_cell_with_nondefault_effective_is_rejected(self):
        doc = self._doc()
        doc["results"][0]["effective"]["mempolicy_mode"] = 2
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("MPOL_DEFAULT" in p for p in problems))

    def test_unstable_read_touch_is_rejected(self):
        doc = self._doc()
        doc["results"][1]["read_touch_stable"] = False
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("read-touch" in p for p in problems))


class TestContainment(unittest.TestCase):
    SLEEP_CHILD = (
        "import os, signal, time\n"
        "if os.fork() == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(300)\n"
        "    os._exit(0)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(300)\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stage0-contain-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timeout_kills_whole_case_group(self):
        spec = {"id": "timeout-desc", "input": "/dev/null", "workers": 2,
                "nodes": 1, "mode": "udf", "timeout": 1}
        out = os.path.join(self.tmp, "case")
        started = time.monotonic()
        manifest = run_case.run_case(
            spec, out, child_script=self.SLEEP_CHILD)
        elapsed = time.monotonic() - started
        self.assertTrue(manifest["timed_out"])
        self.assertLess(elapsed, 20.0)
        self.assertNotEqual(manifest["returncode"], 0)
        self.assertTrue(manifest["case_group_gone"]["gone"],
                        manifest["case_group_gone"])
        self.assertEqual(manifest["case_group_gone"]["members_after"], [])

    def test_timeout_kills_pipe_producer(self):
        src = os.path.join(self.tmp, "big.txt")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("x" * (8 << 20))
        spec = {"id": "timeout-pipe", "input": src,
                "source_kind": "pipe", "workers": 2, "nodes": 1,
                "mode": "udf", "timeout": 1}
        out = os.path.join(self.tmp, "pipe-case")
        manifest = run_case.run_case(
            spec, out, child_script=self.SLEEP_CHILD)
        self.assertTrue(manifest["timed_out"])
        self.assertTrue(manifest["producer_killed"])
        self.assertTrue(manifest["producer_reaped"])
        self.assertTrue(manifest["producer_group_gone"]["gone"],
                        manifest["producer_group_gone"])
        self.assertTrue(manifest["case_group_gone"]["gone"],
                        manifest["case_group_gone"])


class TestCampaignIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stage0-campaign-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _corpus(self, records=2000):
        path = os.path.join(self.tmp, "corpus.txt")
        with open(path, "w", encoding="utf-8") as fh:
            for i in range(records):
                fh.write(json.dumps({"id": i, "text": "x" * 20,
                                     "ts": 1700000000 + i},
                                    separators=(",", ":")) + "\n")
        return path

    def _spec(self, name, input_path, timeout=60):
        path = os.path.join(self.tmp, name + ".json")
        write_json(path, {"id": name, "input": input_path, "workers": 2,
                          "nodes": 1, "mode": "udf", "timeout": timeout})
        return path

    def _run(self, out, campaign_id, specs, trials=1):
        env_before = os.path.join(out, "env", "env-before.json")
        env_after = os.path.join(out, "env", "env-after.json")
        # The shell driver is the unit under test.
        args = ["bash", os.path.join(STAGE0, "run_campaign.sh"),
                "--out", out, "--campaign-id", campaign_id,
                "--trials", str(trials),
                "--env-before", env_before, "--env-after", env_after]
        for spec in specs:
            args += ["--spec", spec]
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              timeout=180, env={
                                  **os.environ,
                                  "FORKRUN_DIAG_QUEUE": "0",
                              })

    def test_specs_are_repo_relative_and_host_adaptive(self):
        specs = sorted(os.listdir(os.path.join(STAGE0, "specs")))
        self.assertTrue(specs)
        for name in specs:
            doc = read_json(os.path.join(STAGE0, "specs", name))
            self.assertFalse(os.path.isabs(doc["input"]),
                             "%s input is absolute" % name)
            self.assertIn(doc.get("nodes"), ("1", "auto"), name)
            payload = doc.get("plugin_payload")
            if payload:
                self.assertFalse(os.path.isabs(payload.rsplit(":", 1)[0]),
                                 "%s plugin is absolute" % name)

    def test_mini_campaign_passes_and_report_loads(self):
        spec = self._spec("mini-ok", self._corpus())
        out = os.path.join(self.tmp, "campaign-ok")
        proc = self._run(out, "mini-ok-1", [spec])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest_path = os.path.join(out, "campaign-manifest.json")
        doc = report.load_campaign(manifest_path)
        self.assertEqual(doc["campaign_id"], "mini-ok-1")
        self.assertEqual(doc["forkrun_diag_queue"], "1")
        trial = read_json(os.path.join(
            out, "cases", "mini-ok", "trial1", "manifest.json"))
        self.assertTrue(trial["diagnostics"]["queue_present"])
        self.assertEqual(trial["diagnostics"]["forkrun_diag_queue"], "1")

    def test_failed_trial_does_not_block_matrix_and_report_rejects(self):
        good = self._spec("good-case", self._corpus())
        bad = self._spec("bad-case", os.path.join(self.tmp, "missing.txt"))
        out = os.path.join(self.tmp, "campaign-fail")
        proc = self._run(out, "mini-fail-1", [good, bad])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        manifest_path = os.path.join(out, "campaign-manifest.json")
        doc = read_json(manifest_path)
        self.assertEqual(doc["state"], "failed")
        statuses = {(o["case"], o["status"]) for o in doc["outcomes"]}
        self.assertIn(("good-case", "ok"), statuses)
        self.assertIn(("bad-case", "failed"), statuses)
        self.assertTrue(os.path.isfile(os.path.join(
            out, "cases", "good-case", "trial1", "manifest.json")))
        with self.assertRaises(report.CampaignError):
            report.load_campaign(manifest_path)

    def test_nonempty_output_dir_is_refused(self):
        spec = self._spec("mini-ok2", self._corpus())
        out = os.path.join(self.tmp, "campaign-reuse")
        os.makedirs(out)
        with open(os.path.join(out, "stale.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("stale")
        proc = self._run(out, "mini-reuse-1", [spec])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("not empty", proc.stderr)


if __name__ == "__main__":
    unittest.main()
