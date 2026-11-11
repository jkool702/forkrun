#!/usr/bin/env python3
"""Stage 0 harness acceptance tests (work order §10).

These tests exercise the REAL report validator, queue parser, ablation
validator, verdict derivation, timeout containment, and campaign
driver. They are not source-text assertions: a fixture is mutated and
the authoritative component must reject it; a case is run and its
process group must be gone; the one-command driver is invoked
end-to-end.

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
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE0 = os.path.dirname(HERE)
REPO = os.path.dirname(STAGE0)
sys.path.insert(0, STAGE0)

import ablation_2x2  # noqa: E402
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


def env_doc(dirty=False, physical=False, release="test-kernel"):
    nodes = ({"node0": {"cpulist": "0-3"}, "node1": {"cpulist": "4-7"}}
             if physical else
             {"node0": {"cpulist": "0-27"}, "node1": {"cpulist": "0-27"}})
    return {
        "git": {"head_sha": SHA, "branch": "test", "dirty": dirty},
        "kernel": {"release": release, "version": "#1",
                   "fake_numa": not physical,
                   "fake_numa_spec": None if physical else "numa=fake=4",
                   "cmdline": "quiet"},
        "thp": {"shmem_enabled": "always", "enabled": "always",
                "per_size": {}},
        "cpu_topology": {"nodes": nodes,
                         "cpus": [{"cpu": 0, "node": 0, "core": "0",
                                   "socket": "0"},
                                  {"cpu": 4, "node": 1, "core": "0",
                                   "socket": "0"}]},
        "cpu_extra": {"governors": ["performance"],
                      "smt": {"thread_siblings": "2"},
                      "kernel_config": {"CONFIG_NUMA": "y"}},
        "cgroup": {"cpuset_cpus": "0-27", "memory_max": "max",
                   "cpu_max": "max 100000"},
        "build_hashes": {"python/forkrun/libforkrun_python.so": "c" * 64},
        "process": {"affinity": [0, 1, 2, 3]},
        "python": {"version": "3.14.0"},
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
        "ingest_cpu_direct_sec": 2.25,
        "ingest_cpu_direct_source": "python-spill (CLOCK_THREAD_CPUTIME_ID)",
        "ingest_cpu_direct_basis_cores": 0.9,
        "ingest_phase_s": 2.0,
        "ingest_cpu_attribution": "direct",
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
                 "lim=4 gated_ms=0 b=n0:0,0 c=n0:0 a=n0:0,1\n")
        fh.write("STAGE0_FINAL src=scan t_ms=10 moved=10 major=0 tgt=0 "
                 "lim=4 gated_ms=0 b=n0:1,1 c=n0:1 a=n0:0,1\n")
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


class FakeGit:
    """A temporary clean git identity over the real work tree.

    The driver's clean-source check and env_capture.py both use the
    ambient git environment. Pointing GIT_DIR at a temp repo and
    GIT_WORK_TREE at the checkout lets the tests run the REAL driver
    without requiring the developer tree to be committed, while still
    exercising the clean/dirty logic and a real source SHA.
    """

    def __init__(self, repo):
        self.repo = repo
        self.tmp = tempfile.mkdtemp(prefix="stage0-git-")
        self.git_dir = os.path.join(self.tmp, "git")
        self.env = {
            **os.environ,
            "GIT_DIR": self.git_dir,
            "GIT_WORK_TREE": repo,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": self.tmp,
        }
        self._git("init", "--quiet")
        self._git("add", "-A")
        self._git("-c", "user.name=stage0", "-c", "user.email=stage0@test",
                  "commit", "--quiet", "-m", "stage0 test identity")
        self.sha = self._git("rev-parse", "HEAD").strip()

    def _git(self, *args):
        return subprocess.run(
            ["git"] + list(args), cwd=self.repo, env=self.env,
            capture_output=True, text=True, timeout=180,
            check=True).stdout

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def online_memory_nodes():
    out = []
    base = "/sys/devices/system/node"
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        if not name.startswith("node") or not name[4:].isdigit():
            continue
        mem = os.path.join(base, name, "meminfo")
        if os.path.isfile(mem):
            try:
                with open(mem, encoding="ascii", errors="replace") as fh:
                    if "MemTotal" in fh.read():
                        out.append(int(name[4:]))
            except OSError:
                pass
    return out


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
        self.assertEqual(doc["forkrun_diag_queue"], "1")

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

    def test_campaign_env_must_be_one(self):
        manifest = read_json(self.path)
        manifest["forkrun_diag_queue"] = None
        write_json(self.path, manifest)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("FORKRUN_DIAG_QUEUE",
                      " ".join(ctx.exception.problems))

    def test_dirty_env_before_is_rejected(self):
        write_json(os.path.join(self.camp, "env", "env-before.json"),
                   env_doc(dirty=True))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        text = " ".join(ctx.exception.problems)
        self.assertIn("DIRTY", text)
        self.assertIn("env-before", text)

    def test_dirty_env_after_is_rejected(self):
        write_json(os.path.join(self.camp, "env", "env-after.json"),
                   env_doc(dirty=True))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("env-after", " ".join(ctx.exception.problems))

    def test_environment_drift_is_rejected(self):
        write_json(os.path.join(self.camp, "env", "env-after.json"),
                   env_doc(release="different-kernel"))
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        text = " ".join(ctx.exception.problems)
        self.assertIn("environment drift", text)
        self.assertIn("kernel.release", text)

    def test_topology_drift_is_rejected(self):
        after = env_doc()
        after["cpu_topology"]["nodes"]["node1"]["cpulist"] = "8-11"
        write_json(os.path.join(self.camp, "env", "env-after.json"), after)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("cpu_topology.nodes.cpulist",
                      " ".join(ctx.exception.problems))

    def test_cpu_mapping_drift_is_rejected(self):
        after = env_doc()
        after["cpu_topology"]["cpus"][1]["node"] = 0
        write_json(os.path.join(self.camp, "env", "env-after.json"), after)
        with self.assertRaises(report.CampaignError) as ctx:
            report.load_campaign(self.path)
        self.assertIn("cpu_topology.cpus",
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

    def test_batch_rates_use_raw_write_and_read_deltas(self):
        lines = [
            "STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:0,0 c=n0:0 a=n0:0,2",
            "STAGE0_DIAG src=scan t_ms=100 moved=10 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:5,10 c=n0:5 a=n0:0,2",
            "STAGE0_DIAG src=scan t_ms=200 moved=20 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:10,20 c=n0:10 a=n0:1,2",
            "STAGE0_FINAL src=scan t_ms=300 moved=30 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:20,30 c=n0:20 a=n0:0,2",
        ]
        stats = self._stats(lines)
        self.assertAlmostEqual(stats["duration_s"], 0.3)
        self.assertEqual(stats["published_batches_total"], 30)
        self.assertEqual(stats["claimed_batches_total"], 20)
        self.assertEqual(stats["claims_c_total"], 20)
        self.assertEqual(stats["supply_gap_batches_total"], -10)
        node = stats["nodes"][0]
        self.assertAlmostEqual(node["nonempty_fraction"], 1.0)
        self.assertAlmostEqual(node["published_batches_per_s"], 100.0)
        self.assertAlmostEqual(node["claimed_batches_per_s"], 20 / 0.3)
        self.assertAlmostEqual(node["claimed_batches_per_s_nonempty"], 75.0)
        self.assertEqual(node["consumption_intervals"], 2)
        self.assertEqual(node["claim_crosscheck_mismatch_intervals"], 0)
        self.assertFalse(stats["has_supply_gap"])
        self.assertEqual(stats["all_empty_fraction"], 0.0)

    def test_per_node_supply_gap_is_not_aggregate_vs_fastest(self):
        lines = [
            "STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:0,0;n1:0,0 c=n0:0;n1:0 a=n0:0,2;n1:0,2",
            "STAGE0_FINAL src=scan t_ms=1000 moved=11 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:10,5;n1:1,5 c=n0:10;n1:1 a=n0:0,2;n1:0,2",
        ]
        stats = self._stats(lines)
        self.assertAlmostEqual(stats["nodes"][0]["supply_gap_batches_per_s"],
                               5.0)
        self.assertAlmostEqual(stats["nodes"][1]["supply_gap_batches_per_s"],
                               -4.0)
        self.assertEqual(stats["gap_nodes"], [0])
        self.assertTrue(stats["has_supply_gap"])

    def test_crosscheck_mismatch_and_counter_regressions(self):
        stats = self._stats([
            "STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:10,10 c=n0:10 a=n0:0,2",
            "STAGE0_DIAG src=scan t_ms=100 moved=10 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:5,5 c=n0:5 a=n0:0,2",
            "STAGE0_DIAG src=scan t_ms=200 moved=20 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:10,10 c=n0:9 a=n0:0,2",
            "STAGE0_FINAL src=scan t_ms=300 moved=30 major=0 tgt=0 lim=4 "
            "gated_ms=0 b=n0:18,18 c=n0:17 a=n0:0,2",
        ])
        node = stats["nodes"][0]
        self.assertEqual(node["counter_regressions"].get("publication"), 1)
        self.assertEqual(node["counter_regressions"].get("claim_position"), 1)
        self.assertEqual(node["counter_regressions"].get("claim_counter"), 1)
        self.assertEqual(node["claim_crosscheck_mismatch_intervals"], 1)
        self.assertEqual(node["published_batches"], 13)
        self.assertEqual(node["claimed_batches"], 13)
        self.assertEqual(node["claims_c_batches"], 12)

    def test_chunk_queue_and_indexer_waiters(self):
        stats = self._stats([
            "STAGE0_DIAG src=ingest t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_DIAG src=ingest t_ms=100 moved=1 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:1 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_DIAG src=ingest t_ms=200 moved=2 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:1,1 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_FINAL src=ingest t_ms=300 moved=3 major=0 tgt=0 lim=4 "
            "gated_ms=42 q=n0:2,2 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
        ])
        chunk = stats["chunk"]
        # The ingest sampler owns BOTH the chunk path and the batch
        # groups; batch telemetry must not be discarded by src.
        self.assertEqual(stats["samples"], 4)
        self.assertEqual(stats["published_batches_total"], 0)
        self.assertEqual(stats["claimed_batches_total"], 0)
        self.assertEqual(chunk["samples"], 4)
        self.assertEqual(stats["gated_ms"], 42)
        self.assertEqual(chunk["chunk_published_total"], 2)
        self.assertEqual(chunk["chunk_consumed_total"], 2)
        self.assertEqual(chunk["indexer_waiters_max"], 1)
        self.assertTrue(chunk["indexer_waiters_observed"])
        self.assertEqual(chunk["empty_samples"], 3)
        self.assertEqual(chunk["empty_with_waiters"], 1)
        self.assertAlmostEqual(chunk["indexer_wait_while_empty_fraction"],
                               1 / 3)
        self.assertTrue(stats["has_ingest_starvation"])

    def test_ingest_batch_samples_are_not_dropped(self):
        """The NUMA C ingest is the only sampler on that path."""
        stats = self._stats([
            "STAGE0_DIAG src=ingest t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:1 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_DIAG src=ingest t_ms=100 moved=1 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:1,1 i=n0:1 b=n0:4,10 c=n0:4 a=n0:2,1",
            "STAGE0_FINAL src=ingest t_ms=200 moved=2 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:2,2 i=n0:0 b=n0:8,20 c=n0:8 a=n0:0,1",
        ])
        self.assertEqual(stats["samples"], 3)
        self.assertEqual(stats["published_batches_total"], 20)
        self.assertEqual(stats["claimed_batches_total"], 8)
        self.assertEqual(stats["claims_c_total"], 8)
        self.assertAlmostEqual(stats["published_batches_per_s"], 100.0)
        self.assertAlmostEqual(stats["claimed_batches_per_s"], 40.0)
        self.assertEqual(stats["nodes"][0]["samples"], 2)

    def test_chunk_wire_order_is_published_then_claimed(self):
        """q = (chunk_queue_head=published, tail=claimed), unlike b."""
        stats = self._stats([
            "STAGE0_DIAG src=ingest t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_DIAG src=ingest t_ms=100 moved=1 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:10,4 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_DIAG src=ingest t_ms=200 moved=2 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:20,8 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_FINAL src=ingest t_ms=300 moved=3 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:30,12 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
        ])
        chunk = stats["chunk"]
        self.assertEqual(chunk["chunk_published_total"], 30)
        self.assertEqual(chunk["chunk_consumed_total"], 12)
        self.assertAlmostEqual(chunk["chunk_published_per_s"], 100.0)
        self.assertAlmostEqual(chunk["chunk_consumed_per_s"], 40.0)
        self.assertAlmostEqual(chunk["all_empty_fraction"], 0.0)
        self.assertAlmostEqual(chunk["any_nonempty_fraction"], 1.0)
        self.assertFalse(stats["has_ingest_starvation"])

    def test_uma_chunk_path_is_not_measurable(self):
        # The UMA scanner emits q/i groups too (the sampler is shared),
        # but it has no ingest->indexer path; src=scan must not make the
        # chunk path measurable.
        stats = self._stats([
            "STAGE0_DIAG src=scan t_ms=0 moved=0 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:0 b=n0:0,0 c=n0:0 a=n0:0,1",
            "STAGE0_FINAL src=scan t_ms=100 moved=1 major=0 tgt=0 lim=4 "
            "gated_ms=0 q=n0:0,0 i=n0:0 b=n0:1,1 c=n0:1 a=n0:0,1",
        ])
        self.assertFalse(stats["chunk_measurable"])
        self.assertEqual(stats["chunk"]["nodes"], {})
        self.assertIsNone(stats["has_scanner_starvation"])
        self.assertFalse(stats["has_ingest_starvation"])

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
                         "tgt=0 lim=4 gated_ms=0 b=n0:0,1 "
                         "c=n0:0 a=n0:0,1\n")
                fh.write("STAGE0_FINAL src=scan t_ms=100 moved=1 major=0 "
                         "tgt=0 lim=4 gated_ms=0 b=n0:1,1 "
                         "c=n0:1 a=n0:0,1\n")
            with open(os.path.join(d2, "stderr.log"), "w",
                      encoding="utf-8") as fh:
                fh.write("STAGE0_DIAG src=scan t_ms=5000 moved=0 major=0 "
                         "tgt=0 lim=4 gated_ms=0 b=n0:0,1 "
                         "c=n0:0 a=n0:0,1\n")
                fh.write("STAGE0_FINAL src=scan t_ms=5100 moved=1 major=0 "
                         "tgt=0 lim=4 gated_ms=0 b=n0:1,1 "
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
            "gated_ms=7 q=n0:1,1 i=n0:0 b=n0:1,1 c=n0:1 a=n0:0,1"])
        self.assertEqual(stats["samples"], 1)
        self.assertEqual(stats["published_batches_total"], 0)
        self.assertEqual(stats["chunk"]["samples"], 1)
        self.assertEqual(stats["gated_ms"], 7)
        self.assertIn(0, stats["chunk"]["nodes"])

    def test_malformed_group_is_ignored(self):
        self.assertEqual(report._parse_group("n0:1,2;nope:3;n1:x"),
                         {0: (1, 2)})


def ablation_doc(cid="campaign-1"):
    nodes = {"x": 0, "y": 1, "x_cpus": [0, 1], "y_cpus": [2, 3],
             "allowed_cpus": [0, 1, 2, 3], "fake_numa": False}
    results = []
    for cell in ("A", "B", "C", "D"):
        for form in ("map-fault", "write-path"):
            bind = cell in ("C", "D")
            pinned = cell in ("B", "D")
            results.append({
                "cell": cell,
                "form": form,
                "valid": True,
                "invalid_reason": None,
                "child_rc": 0,
                "child_timed_out": False,
                "policy_requested": {
                    "mode_numeric": 2 if bind else 0,
                    "mode_symbolic": "MPOL_BIND" if bind else "MPOL_DEFAULT",
                    "set_rc": 0,
                },
                "effective": {
                    "get_mempolicy_rc": 0,
                    "mempolicy_mode": 2 if bind else 0,
                    "mempolicy_mask_nodes": [1] if bind else [],
                    "affinity_cpus": [0] if pinned else [0, 1, 2, 3],
                },
                "affinity_requested": {
                    "mode": "pinned" if pinned else "default",
                    "cpu": 0 if pinned else None,
                    "set_rc": 0 if pinned else None,
                },
                "cpu_at_first_touch": 0,
                "pages_total": 8,
                "pages_by_node": {"1": 8} if bind else {"0": 8},
                "pages_unknown": 0,
                "placement_measured": True,
                "move_pages_post": {"rc": 0, "statuses": [1] * 8
                                    if bind else [0] * 8},
                "mincore": {"rc": 0, "total_pages": 8,
                            "resident_pages": 8},
                "touch": {"kind": "read" if form == "write-path"
                          else "write", "pages_touched": 8},
                "read_touch_stable": True if form == "write-path" else None,
                "read_touch_unstable_pages": (0 if form == "write-path"
                                              else None),
            })
    return {
        "schema": "stage0-ablation/2",
        "campaign_id": cid,
        "nodes": nodes,
        "cells": ["A", "B", "C", "D"],
        "forms": ["map-fault", "write-path"],
        "results": results,
    }


class TestAblationValidation(unittest.TestCase):
    @staticmethod
    def _row(doc, cell, form="map-fault"):
        return next(r for r in doc["results"]
                    if r["cell"] == cell and r["form"] == form)

    def test_valid_eight_pair_ablation_passes(self):
        ok, problems = report.ablation_ok(ablation_doc(), "campaign-1")
        self.assertTrue(ok, problems)

    def test_missing_pair_is_rejected(self):
        doc = ablation_doc()
        doc["results"].pop()
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("missing result pairs" in p for p in problems))
        self.assertTrue(any("exactly 8" in p for p in problems))

    def test_duplicate_pair_is_rejected(self):
        doc = ablation_doc()
        doc["results"].append(dict(doc["results"][0]))
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("duplicate result row" in p for p in problems))

    def test_campaign_id_mismatch_is_rejected(self):
        ok, problems = report.ablation_ok(ablation_doc(), "other")
        self.assertFalse(ok)
        self.assertTrue(any("campaign_id" in p for p in problems))

    def test_child_failure_is_rejected(self):
        doc = ablation_doc()
        doc["results"][0]["child_rc"] = 1
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("child_rc" in p for p in problems))

    def test_child_timeout_is_rejected(self):
        doc = ablation_doc()
        doc["results"][0]["child_timed_out"] = True
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("child_timed_out" in p for p in problems))

    def test_preferred_mode_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "C")["policy_requested"]["mode_numeric"] = 1
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("MPOL_BIND" in p for p in problems))

    def test_default_cell_with_nondefault_effective_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["effective"]["mempolicy_mode"] = 2
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("MPOL_DEFAULT" in p for p in problems))

    def test_wrong_policy_mask_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "C")["effective"]["mempolicy_mask_nodes"] = [0]
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("effective mask" in p for p in problems))

    def test_pinned_cpu_off_node_x_is_rejected(self):
        doc = ablation_doc()
        row = self._row(doc, "B")
        row["affinity_requested"]["cpu"] = 2
        row["effective"]["affinity_cpus"] = [2]
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("not on node X" in p for p in problems))

    def test_inherited_affinity_mismatch_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["effective"]["affinity_cpus"] = [0]
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("inherited affinity" in p for p in problems))

    def test_unknown_pages_are_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["pages_unknown"] = 1
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("pages_unknown" in p for p in problems))

    def test_page_accounting_mismatch_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["pages_by_node"] = {"0": 7}
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("sum to" in p for p in problems))

    def test_raw_status_count_mismatch_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["move_pages_post"]["statuses"] = [0] * 7
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("raw statuses" in p for p in problems))

    def test_mincore_residency_mismatch_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["mincore"]["resident_pages"] = 7
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("mincore resident" in p for p in problems))

    def test_unstable_read_touch_is_rejected(self):
        doc = ablation_doc()
        row = self._row(doc, "A", "write-path")
        row["read_touch_stable"] = False
        row["read_touch_unstable_pages"] = 2
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("read-touch" in p for p in problems))
        self.assertTrue(any("changed placement" in p for p in problems))

    def test_wrong_touch_kind_is_rejected(self):
        doc = ablation_doc()
        self._row(doc, "A")["touch"]["kind"] = "read"
        ok, problems = report.ablation_ok(doc, "campaign-1")
        self.assertFalse(ok)
        self.assertTrue(any("touch kind" in p for p in problems))


def summary_row(case="case-a", map_s=2.5, cores=0.95, n_ok=3):
    return {
        "case": case,
        "n_ok": n_ok,
        "median_map_s": map_s,
        "median_ingest_cores": cores,
        "ingest_attribution": "direct",
    }


def queue_row(trials=3, gap=True, ingest_starved=True, scanner_starved=False,
              saturated=True, idle=0.5, cores=None, gated=0):
    nodes = {0: {"supply_gap_batches_per_s": 5.0 if gap else -1.0}}
    chunk_nodes = {0: {"chunk_published_per_s": 10.0}}
    return {
        "trials": trials,
        "supply_gap_trials": trials if gap else 0,
        "no_supply_gap_trials": 0 if gap else trials,
        "ingest_starvation_trials": trials if ingest_starved else 0,
        "scanner_starvation_trials": 1 if scanner_starved else 0,
        "scanner_starvation_measurable_trials": trials,
        "workers_saturated_trials": trials if saturated else 0,
        "gated_ms": gated,
        "idle_waiter_fraction": idle,
        "nodes": nodes,
        "chunk": {"nodes": chunk_nodes,
                  "indexer_waiters_observed": True},
    }


class TestVerdict(unittest.TestCase):
    def _verdict(self, summary, queue, env=None, trials=3, ablation=None):
        return report.derive_verdict(
            summary, queue, env or env_doc(physical=True),
            ablation or [], [], trials_requested=trials)

    def test_go_requires_supply_gap_ingest_starvation_and_cores(self):
        v = self._verdict([summary_row()], {"case-a": queue_row()})
        self.assertEqual(v["decision"], "GO", v["evidence"])

    def test_source_limited_is_no_go(self):
        v = self._verdict(
            [summary_row(cores=0.2)],
            {"case-a": queue_row(gap=False, ingest_starved=True,
                                 saturated=False)})
        self.assertEqual(v["decision"], "NO-GO", v["evidence"])
        self.assertIn("source", " ".join(v["evidence"]))

    def test_scanner_worker_starvation_is_no_go(self):
        v = self._verdict(
            [summary_row(cores=0.2)],
            {"case-a": queue_row(gap=False, ingest_starved=False,
                                 scanner_starved=True, saturated=False)})
        self.assertEqual(v["decision"], "NO-GO", v["evidence"])

    def test_saturated_workers_without_supply_gap_is_no_go(self):
        v = self._verdict(
            [summary_row()],
            {"case-a": queue_row(gap=False, ingest_starved=False,
                                 saturated=True)})
        self.assertEqual(v["decision"], "NO-GO", v["evidence"])

    def test_one_trial_physical_cannot_decide(self):
        v = self._verdict([summary_row()], {"case-a": queue_row(trials=1)},
                          trials=1)
        self.assertEqual(v["decision"], "INCONCLUSIVE", v["evidence"])
        self.assertIn("three trials", v["verdict"])

    def test_fewer_than_three_completed_trials_cannot_decide(self):
        v = self._verdict([summary_row(n_ok=2)],
                          {"case-a": queue_row(trials=2)})
        self.assertEqual(v["decision"], "INCONCLUSIVE", v["evidence"])
        self.assertIn("three completed", v["verdict"])

    def test_fake_numa_is_always_inconclusive(self):
        v = self._verdict([summary_row()], {"case-a": queue_row()},
                          env=env_doc(physical=False))
        self.assertEqual(v["decision"], "INCONCLUSIVE", v["evidence"])
        self.assertIn("fake NUMA", v["verdict"])

    def test_mixed_go_and_no_go_is_inconclusive(self):
        v = self._verdict(
            [summary_row("case-a"), summary_row("case-b")],
            {"case-a": queue_row(),
             "case-b": queue_row(gap=False, ingest_starved=False,
                                 saturated=True)})
        self.assertEqual(v["decision"], "INCONCLUSIVE", v["evidence"])

    def test_no_decisive_case_is_inconclusive(self):
        v = self._verdict([summary_row(map_s=0.3)],
                          {"case-a": queue_row()})
        self.assertEqual(v["decision"], "INCONCLUSIVE", v["evidence"])
        self.assertIn("2-second", " ".join(v["evidence"]))


class TestIngestCpuParsing(unittest.TestCase):
    def test_direct_python_and_c_records(self):
        parsed = run_case._parse_diag(
            "STAGE0_INGEST_CPU src=uma-spill cpu_ns=1500000000 "
            "wall_ns=2000000000\n"
            "STAGE0_INGEST_CPU src=uma-stream-spill cpu_ns=500000000 "
            "wall_ns=1000000000\n"
            "STAGE0_FINAL src=ingest t_ms=1234 t_us=1234567 moved=1 major=0 "
            "tgt=0 lim=4 gated_ms=0 cpu_ns=990000000 q=n0:0,0 i=n0:0 "
            "b=n0:0,0 c=n0:0 a=n0:0,1\n")
        self.assertEqual(parsed["direct_ingest_cpu_ns"]["uma-spill"],
                         1500000000)
        self.assertEqual(
            parsed["direct_ingest_cpu_ns"]["uma-stream-spill"], 500000000)
        self.assertEqual(parsed["direct_ingest_wall_ns"]["uma-spill"],
                         2000000000)
        self.assertEqual(parsed["final_cpu_ns"]["ingest"], 990000000)
        self.assertEqual(parsed["final_t_ms"]["ingest"], 1234)
        self.assertEqual(parsed["final_t_us"]["ingest"], 1234567)
        self.assertEqual(parsed["finals"], 1)

    def test_c_phase_prefers_microseconds_over_truncated_ms(self):
        # t_ms=3 truncates a 3.9 ms phase; using it would report >1 core
        # for a single thread. t_us is the precise phase basis.
        diag = run_case._parse_diag(
            "STAGE0_FINAL src=ingest t_ms=3 t_us=3900 moved=1 major=0 "
            "tgt=0 lim=4 gated_ms=0 cpu_ns=3900000 q=n0:0,0 i=n0:0 "
            "b=n0:0,0 c=n0:0 a=n0:0,1\n")
        direct = run_case._direct_ingest_cpu(diag, 0.02)
        self.assertEqual(
            direct["source"],
            "c-ingest-final (CLOCK_THREAD_CPUTIME_ID)")
        self.assertAlmostEqual(direct["phase_s"], 0.0039)
        # With t_ms=3 this would be 1.3 cores for a single thread.
        self.assertAlmostEqual(direct["phase_cores"], 1.0)
        self.assertAlmostEqual(direct["map_basis_cores"], 0.195)

    def test_c_phase_falls_back_to_ms_without_t_us(self):
        diag = run_case._parse_diag(
            "STAGE0_FINAL src=ingest t_ms=500 moved=1 major=0 tgt=0 "
            "lim=4 gated_ms=0 cpu_ns=400000000 q=n0:0,0 i=n0:0 "
            "b=n0:0,0 c=n0:0 a=n0:0,1\n")
        direct = run_case._direct_ingest_cpu(diag, 1.0)
        self.assertAlmostEqual(direct["phase_s"], 0.5)
        self.assertAlmostEqual(direct["phase_cores"], 0.8)

    def test_phase_basis_is_preferred_over_whole_map_basis(self):
        manifest = trial_manifest()
        manifest["ingest_cpu_direct_basis_cores"] = 0.20
        manifest["ingest_cpu_phase_cores"] = 1.10
        rows = report.case_summary({"case-a": [(manifest, "/tmp")]})
        self.assertAlmostEqual(rows[0]["median_ingest_cores"], 1.10)
        self.assertEqual(rows[0]["ingest_attribution"], "direct")


class TestSelectNodes(unittest.TestCase):
    def test_policy_node_needs_memory_not_an_allowed_cpu(self):
        with mock.patch.object(ablation_2x2, "_online_nodes",
                               return_value=[0, 1]), \
             mock.patch.object(ablation_2x2, "_node_mem_total_kb",
                               side_effect=lambda n: 1024), \
             mock.patch.object(ablation_2x2, "_node_cpus",
                               side_effect=lambda n: [0, 1] if n == 0
                               else [2, 3]), \
             mock.patch.object(ablation_2x2, "_allowed_cpus",
                               return_value=[0, 1]):
            nodes = ablation_2x2._select_nodes(None, 1)
            self.assertEqual((nodes["x"], nodes["y"]), (0, 1))
            with self.assertRaises(SystemExit):
                ablation_2x2._select_nodes(1, None)


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
        self.git = FakeGit(REPO)

    def tearDown(self):
        self.git.close()
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
        args = ["bash", os.path.join(STAGE0, "run_campaign.sh"),
                "--out", out, "--campaign-id", campaign_id,
                "--trials", str(trials),
                "--env-before", env_before, "--env-after", env_after]
        for spec in specs:
            args += ["--spec", spec]
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              timeout=240, env={
                                  **self.git.env,
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
        self.assertEqual(doc["source_sha"], self.git.sha)
        self.assertEqual(doc["forkrun_diag_queue"], "1")
        trial = read_json(os.path.join(
            out, "cases", "mini-ok", "trial1", "manifest.json"))
        self.assertTrue(trial["diagnostics"]["queue_present"])
        self.assertEqual(trial["diagnostics"]["forkrun_diag_queue"], "1")
        self.assertIsNotNone(trial.get("ingest_cpu_attribution"))

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

    def test_precreated_env_before_is_allowed(self):
        spec = self._spec("mini-env", self._corpus())
        out = os.path.join(self.tmp, "campaign-env")
        os.makedirs(os.path.join(out, "env"))
        env_before = os.path.join(out, "env", "env-before.json")
        subprocess.run(
            [sys.executable, os.path.join(STAGE0, "env_capture.py"),
             "--out", env_before, "--run-id", "mini-env-1"],
            cwd=REPO, env=self.git.env, check=True, timeout=120,
            capture_output=True)
        proc = self._run(out, "mini-env-1", [spec])
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestRunAllCampaignIntegration(unittest.TestCase):
    """Invoke the REAL one-command driver end-to-end.

    Uses a temporary git identity over the real work tree so the driver
    exercises its clean-source check, a real source SHA, and the real
    campaign/ablation/report chain without requiring the developer tree
    to be committed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stage0-runall-")
        self.git = FakeGit(REPO)

    def tearDown(self):
        self.git.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_source_sha_mismatch_is_refused(self):
        spec = os.path.join(self.tmp, "tiny.json")
        write_json(spec, {"id": "tiny-sha", "input": "/dev/null",
                          "workers": 1, "nodes": 1, "mode": "udf",
                          "timeout": 30})
        env = {**self.git.env, "SOURCE_SHA": "b" * 40}
        proc = subprocess.run(
            ["bash", os.path.join(STAGE0, "run_all_campaign.sh"),
             "--spec", spec, "--no-corpus", "--trials", "1",
             "--campaign-id", "sha-mismatch-1",
             "--run-dir", os.path.join(self.tmp, "sha-run"),
             "--no-publish"],
            cwd=REPO, env=env, capture_output=True, text=True,
            timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not match", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sha-run")))

    def test_one_command_driver_end_to_end(self):
        nodes = online_memory_nodes()
        if len(nodes) < 2:
            self.skipTest("needs at least two online memory nodes")
        node_x, node_y = nodes[0], nodes[1]

        corpus = os.path.join(self.tmp, "tiny.txt")
        with open(corpus, "w", encoding="utf-8") as fh:
            for i in range(300):
                fh.write(json.dumps({"id": i, "text": "x" * 12},
                                    separators=(",", ":")) + "\n")
        spec = os.path.join(self.tmp, "tiny.json")
        write_json(spec, {"id": "tiny-e2e", "input": corpus,
                          "workers": 2, "nodes": 1, "mode": "udf",
                          "timeout": 120})

        run_dir = os.path.join(self.tmp, "run")
        report_out = os.path.join(self.tmp, "report.md")
        campaign_id = "e2e-campaign-1"
        env = {
            **self.git.env,
            "FORKRUN_DIAG_QUEUE": "0",
            "ABLATION_NODE_X": str(node_x),
            "ABLATION_NODE_Y": str(node_y),
        }
        proc = subprocess.run(
            ["bash", os.path.join(STAGE0, "run_all_campaign.sh"),
             "--spec", spec, "--no-corpus", "--trials", "1",
             "--campaign-id", campaign_id, "--run-dir", run_dir,
             "--report-out", report_out, "--no-publish"],
            cwd=REPO, env=env, capture_output=True, text=True,
            timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        manifest = read_json(os.path.join(run_dir,
                                          "campaign-manifest.json"))
        self.assertEqual(manifest["campaign_id"], campaign_id)
        self.assertEqual(manifest["source_sha"], self.git.sha)
        self.assertEqual(manifest["forkrun_diag_queue"], "1")
        self.assertEqual(manifest["trials_requested"], 1)
        self.assertEqual(manifest["expected_cases"], ["tiny-e2e"])
        self.assertTrue(manifest["all_ok"], manifest)

        trial = read_json(os.path.join(run_dir, "cases", "tiny-e2e",
                                       "trial1", "manifest.json"))
        self.assertEqual(trial["campaign_id"], campaign_id)
        self.assertEqual(trial["source_sha"], self.git.sha)
        self.assertEqual(trial["diagnostics"]["forkrun_diag_queue"], "1")
        self.assertTrue(trial["diagnostics"]["queue_present"])

        ablation = read_json(os.path.join(run_dir, "ablation",
                                          "ablation.json"))
        self.assertEqual(ablation["campaign_id"], campaign_id)
        self.assertEqual((ablation["nodes"]["x"], ablation["nodes"]["y"]),
                         (node_x, node_y))
        self.assertEqual(len(ablation["results"]), 8)
        ok, problems = report.ablation_ok(ablation, campaign_id)
        self.assertTrue(ok, problems)

        with open(report_out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(campaign_id, text)
        self.assertIn(self.git.sha, text)
        self.assertIn("INCONCLUSIVE", text)
        self.assertIn("Ablation validity: PASS", text)


if __name__ == "__main__":
    unittest.main()
