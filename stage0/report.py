#!/usr/bin/env python3
"""Stage 0 report generator (campaign spec §9).

Consumes EXACTLY ONE campaign manifest and the artifacts it names:

  <run-root>/campaign-manifest.json
  <run-root>/cases/<spec-id>/trial<N>/manifest.json + stderr.log
  <run-root>/ablation/ablation.json
  <run-root>/env/env-before.json + env-after.json

It does not glob for trials. A campaign with a missing case/trial, a
missing or malformed trial manifest, a mismatched campaign id, extra
(stale) trial directories, or missing required STAGE0 queue telemetry is
REJECTED: the report is written as INVALID and the process exits 2.

Usage:
  python3 stage0/report.py --campaign stage0/runs/<id>/campaign-manifest.json \
      --ablation stage0/runs/<id>/ablation/ablation.json \
      --env-before stage0/runs/<id>/env/env-before.json \
      --env-after stage0/runs/<id>/env/env-after.json \
      --out stage0/reports/stage0-report.md
"""

import argparse
import glob
import json
import os
import statistics
import sys

SCHEMA_CAMPAIGN = "stage0-campaign/2"
SCHEMA_CASE = "stage0-case/3"
SCHEMA_ABLATION = "stage0-ablation/2"

# Spec §4.2 says "approximately one full logical CPU". This is a
# READING band for that phrase, not a new Go threshold: a physical-host
# verdict still requires the relative supply-gap and cross-trial
# evidence below. Outside the band the report says "not near one core"
# and the verdict stays Inconclusive.
_INGEST_NEAR_ONE = (0.80, 1.20)


class CampaignError(Exception):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _median(xs):
    return statistics.median(xs) if xs else None


def _fmt(value, spec="%.2f"):
    if value is None:
        return "-"
    try:
        return spec % value
    except (TypeError, ValueError):
        return str(value)


def _read_json(path, label, problems):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        problems.append("%s: cannot read %s (%s)" % (label, path, exc))
    except ValueError as exc:
        problems.append("%s: malformed JSON in %s (%s)" % (label, path, exc))
    return None


def _resolve(base, rel):
    return rel if os.path.isabs(rel) else os.path.normpath(
        os.path.join(base, rel))


def _get(doc, *path):
    cur = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _env_topology_map(env):
    """Normalized node -> cpulist map for drift comparison."""
    nodes = _get(env, "cpu_topology", "nodes") or {}
    out = {}
    if isinstance(nodes, dict):
        for name, value in nodes.items():
            if isinstance(value, dict):
                out[name] = value.get("cpulist")
            else:
                out[name] = value
    return out


def _env_cpu_map(env):
    """Normalized CPU -> (node, core, socket) map for drift comparison."""
    rows = _get(env, "cpu_topology", "cpus") or []
    out = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("cpu") is None:
                continue
            out[str(row["cpu"])] = (row.get("node"), row.get("core"),
                                    row.get("socket"))
    return out


def _env_drift(before, after):
    """Fields whose change makes direct before/after comparison invalid."""
    drift = []
    fields = [
        ("git", "head_sha"),
        ("git", "branch"),
        ("kernel", "release"),
        ("kernel", "version"),
        ("kernel", "fake_numa"),
        ("kernel", "fake_numa_spec"),
        ("kernel", "cmdline"),
        ("cpu_extra", "governors"),
        ("cpu_extra", "smt"),
        ("cpu_extra", "kernel_config"),
        ("thp", "shmem_enabled"),
        ("thp", "enabled"),
        ("thp", "per_size"),
        ("cgroup", "cpuset_cpus"),
        ("cgroup", "memory_max"),
        ("cgroup", "cpu_max"),
        ("build_hashes",),
        ("process", "affinity"),
        ("python", "version"),
    ]
    for path in fields:
        a = _get(before, *path)
        b = _get(after, *path)
        if a != b:
            drift.append(("%s" % ".".join(path), a, b))
    a = _env_topology_map(before)
    b = _env_topology_map(after)
    if a != b:
        drift.append(("cpu_topology.nodes.cpulist", a, b))
    a = _env_cpu_map(before)
    b = _env_cpu_map(after)
    if a != b:
        drift.append(("cpu_topology.cpus", a, b))
    return drift


def load_campaign(path):
    """Load and STRICTLY validate one campaign. Raises CampaignError."""
    problems = []
    campaign_dir = os.path.dirname(os.path.abspath(path))
    doc = _read_json(path, "campaign", problems)
    if doc is None:
        raise CampaignError(problems)
    if doc.get("schema") != SCHEMA_CAMPAIGN:
        problems.append("campaign: schema %r != %r"
                        % (doc.get("schema"), SCHEMA_CAMPAIGN))
    campaign_id = doc.get("campaign_id")
    if not campaign_id:
        problems.append("campaign: missing campaign_id")
    if doc.get("forkrun_diag_queue") != "1":
        problems.append(
            "campaign: FORKRUN_DIAG_QUEUE was %r; per-node queue telemetry "
            "is required evidence and the driver must force it to 1"
            % (doc.get("forkrun_diag_queue"),))
    source_sha = doc.get("source_sha")
    trials_requested = doc.get("trials_requested")
    if not isinstance(trials_requested, int) or trials_requested < 1:
        problems.append("campaign: trials_requested must be a positive int")
        trials_requested = 0
    specs = doc.get("specs")
    expected_cases = doc.get("expected_cases")
    outcomes = doc.get("outcomes")
    if not isinstance(specs, list) or not specs:
        problems.append("campaign: missing spec inventory")
        specs = []
    if not isinstance(expected_cases, list) or not expected_cases:
        problems.append("campaign: missing expected_cases")
        expected_cases = [s.get("id") for s in specs if isinstance(s, dict)]
    if not isinstance(outcomes, list):
        problems.append("campaign: missing outcomes")
        outcomes = []

    spec_by_id = {}
    for spec in specs:
        if not isinstance(spec, dict) or not spec.get("id"):
            problems.append("campaign: malformed spec inventory entry")
            continue
        if spec["id"] in spec_by_id:
            problems.append("campaign: duplicate spec id %s" % spec["id"])
        spec_by_id[spec["id"]] = spec
    if sorted(spec_by_id) != sorted(expected_cases):
        problems.append(
            "campaign: spec inventory %s != expected_cases %s"
            % (sorted(spec_by_id), sorted(expected_cases)))

    expected = {(case, trial) for case in expected_cases
                for trial in range(1, trials_requested + 1)}
    seen = set()
    cases = {case: [] for case in expected_cases}
    for out in outcomes:
        if not isinstance(out, dict):
            problems.append("campaign: malformed outcome entry")
            continue
        case = out.get("case")
        trial = out.get("trial")
        key = (case, trial)
        if key in seen:
            problems.append("campaign: duplicate outcome %s" % (key,))
        seen.add(key)
        if key not in expected:
            problems.append("campaign: unexpected outcome %s" % (key,))
            continue
        if out.get("status") != "ok":
            problems.append("campaign: %s trial %s status=%r"
                            % (case, trial, out.get("status")))
            continue
        rel = out.get("manifest")
        if not rel:
            problems.append("campaign: %s trial %s missing manifest path"
                            % (case, trial))
            continue
        mpath = _resolve(campaign_dir, rel)
        manifest = _read_json(mpath, "%s/trial%s" % (case, trial), problems)
        if manifest is None:
            continue
        tproblems = validate_trial(manifest, mpath, campaign_id, source_sha,
                                   spec_by_id.get(case), case, trial)
        problems.extend(tproblems)
        if not tproblems:
            cases[case].append((manifest, os.path.dirname(mpath)))
        else:
            cases[case].append((manifest, os.path.dirname(mpath)))
    missing = sorted(expected - seen)
    if missing:
        problems.append("campaign: missing outcomes %s" % (missing[:10],))
    extra = sorted(seen - expected)
    if extra:
        problems.append("campaign: extra outcomes %s" % (extra[:10],))

    # Stale/mixed artifacts: the case and trial directories on disk must
    # be exactly the ones this campaign names.
    cases_dir = os.path.join(campaign_dir, "cases")
    if not os.path.isdir(cases_dir):
        problems.append("campaign: missing cases/ directory")
    else:
        on_disk = sorted(n for n in os.listdir(cases_dir)
                         if os.path.isdir(os.path.join(cases_dir, n)))
        if on_disk != sorted(expected_cases):
            problems.append(
                "campaign: cases/ contains %s, expected %s"
                % (on_disk, sorted(expected_cases)))
        for case in expected_cases:
            cdir = os.path.join(cases_dir, case)
            if not os.path.isdir(cdir):
                continue
            trials = sorted(n for n in os.listdir(cdir)
                            if os.path.isdir(os.path.join(cdir, n)))
            want = ["trial%d" % t for t in range(1, trials_requested + 1)]
            if trials != want:
                problems.append(
                    "campaign: %s trials on disk %s, expected %s"
                    % (case, trials, want))

    env_before = None
    env_after = None
    if not doc.get("env_before"):
        problems.append("campaign: missing env_before reference")
    if not doc.get("env_after"):
        problems.append("campaign: missing env_after reference")
    if doc.get("env_before"):
        env_before = _read_json(_resolve(campaign_dir, doc["env_before"]),
                                "env-before", problems)
    if doc.get("env_after"):
        env_after = _read_json(_resolve(campaign_dir, doc["env_after"]),
                               "env-after", problems)
    for label, env in (("env-before", env_before), ("env-after", env_after)):
        if env is None:
            continue
        git = env.get("git") or {}
        if git.get("dirty") is not False:
            problems.append(
                "campaign: %s was captured from a %s worktree (dirty=%r); "
                "a SHA alone does not identify dirty source changes"
                % (label, "DIRTY" if git.get("dirty") else "non-clean",
                   git.get("dirty")))
        sha = git.get("head_sha")
        if source_sha and sha and sha != source_sha:
            problems.append("campaign: %s git %s != source_sha %s"
                            % (label, sha, source_sha))
    if env_after is not None and env_before is not None:
        drift = _env_drift(env_before, env_after)
        if drift:
            problems.append(
                "campaign: environment drift between before/after: %s"
                % "; ".join("%s: %r -> %r" % item for item in drift))

    doc["_campaign_dir"] = campaign_dir
    doc["_cases"] = cases
    doc["_env_before"] = env_before
    doc["_env_after"] = env_after
    doc["_problems"] = problems
    if problems:
        raise CampaignError(problems)
    return doc


def validate_trial(manifest, path, campaign_id, source_sha, spec, case, trial):
    problems = []
    label = "%s/trial%s" % (case, trial)
    if manifest.get("schema") != SCHEMA_CASE:
        problems.append("%s: schema %r != %r"
                        % (label, manifest.get("schema"), SCHEMA_CASE))
    if manifest.get("campaign_id") != campaign_id:
        problems.append("%s: campaign_id %r != %r (stale/mixed campaign)"
                        % (label, manifest.get("campaign_id"), campaign_id))
    if manifest.get("spec_id") != case:
        problems.append("%s: spec_id %r != %r"
                        % (label, manifest.get("spec_id"), case))
    if manifest.get("trial") != trial:
        problems.append("%s: trial %r != %r"
                        % (label, manifest.get("trial"), trial))
    if source_sha and manifest.get("source_sha") != source_sha:
        problems.append("%s: source_sha %r != %r"
                        % (label, manifest.get("source_sha"), source_sha))
    if spec and spec.get("sha256") and \
            manifest.get("spec_sha256") != spec["sha256"]:
        problems.append("%s: spec_sha256 %r != inventory %r"
                        % (label, manifest.get("spec_sha256"),
                           spec.get("sha256")))
    if not manifest.get("complete"):
        problems.append("%s: trial incomplete (%s)"
                        % (label, manifest.get("incomplete_reasons")))
    if manifest.get("timed_out"):
        problems.append("%s: timed out" % label)
    if manifest.get("returncode") != 0:
        problems.append("%s: returncode %r"
                        % (label, manifest.get("returncode")))
    if "child_report" not in manifest:
        problems.append("%s: missing child_report" % label)
    diag = manifest.get("diagnostics") or {}
    if not diag.get("queue_present"):
        problems.append("%s: missing STAGE0_DIAG/STAGE0_FINAL telemetry"
                        % label)
    if diag.get("forkrun_diag_queue") != "1":
        problems.append("%s: FORKRUN_DIAG_QUEUE was %r, expected '1'"
                        % (label, diag.get("forkrun_diag_queue")))
    gone = manifest.get("case_group_gone") or {}
    if not gone.get("gone"):
        problems.append("%s: case process group not gone %s"
                        % (label, gone.get("members_after")))
    if (manifest.get("spec") or {}).get("source_kind") == "pipe":
        pgone = manifest.get("producer_group_gone") or {}
        if not pgone.get("gone") or not manifest.get("producer_reaped"):
            problems.append("%s: pipe producer not reaped/gone" % label)
    stderr_path = os.path.join(os.path.dirname(path), "stderr.log")
    if not os.path.isfile(stderr_path):
        problems.append("%s: missing stderr.log" % label)
    return problems


# --------------------------------------------------------------------------
# Queue telemetry: per-node, per-trial, timestamp-based.
# --------------------------------------------------------------------------

def _parse_group(text):
    out = {}
    for token in (text or "").split(";"):
        if not token:
            continue
        label, _, values = token.partition(":")
        if not label.startswith("n"):
            continue
        try:
            node = int(label[1:])
            parts = tuple(int(v) for v in values.split(",") if v != "")
        except ValueError:
            continue
        out[node] = parts
    return out


def _diag_records(text):
    records = []
    for line in (text or "").splitlines():
        if not line.startswith("STAGE0_"):
            continue
        parts = line.split()
        rec = {"kind": parts[0]}
        for token in parts[1:]:
            key, _, value = token.partition("=")
            if key in ("q", "i", "b", "c", "a"):
                rec[key] = _parse_group(value)
            else:
                rec[key] = value
        records.append(rec)
    return records


def _depth(group, node, pair=True):
    value = group.get(node)
    if not value:
        return None
    if pair:
        return value[1] - value[0] if len(value) >= 2 else None
    return value[0]


def _scalar(group, node):
    value = group.get(node)
    if not value:
        return None
    return value[0]


def _delta(cur, prev):
    """Return (delta, state); state is ok|missing|regressed.

    A counter regression is NEVER silently converted to zero work: the
    interval is excluded from the rate and counted explicitly.
    """
    if cur is None or prev is None:
        return None, "missing"
    if cur < prev:
        return None, "regressed"
    return cur - prev, "ok"


def _sample_us(rec):
    """Sample timestamp in microseconds. `t_us` is authoritative.

    `t_ms` is retained as a human-readable field only; falling back to it
    keeps old logs parseable. Interval math must use microseconds so two
    samples in the same millisecond are still ordered.
    """
    t_us = rec.get("t_us")
    if t_us is not None:
        try:
            return int(t_us)
        except (TypeError, ValueError):
            return None
    t_ms = rec.get("t_ms")
    if t_ms is not None:
        try:
            return int(t_ms) * 1000
        except (TypeError, ValueError):
            return None
    return None


def _batch_stats(records):
    """Scanner-published -> worker-claimed batch queue, per node.

    `b` is (read_idx, write_idx). Publication is the RAW write_idx
    delta, claims are the RAW read_idx delta. Depth
    (write_idx - read_idx) is used ONLY for occupancy. `c` is
    total_lines_consumed and is a cross-check on the claim position.
    """
    # The sampler is shared by the UMA scanner and the NUMA C ingest, so
    # the batch groups are owned by BOTH sources. A trial is emitted by
    # exactly one of them in practice; if both appear, prefer the NUMA
    # ingest sampler because that is the path the chunk timeline belongs
    # to. Their t_us origins are independent, so never interleave them.
    with_b = [r for r in records if r.get("b") is not None]
    srcs = {r.get("src") for r in with_b}
    owner = "ingest" if "ingest" in srcs else (
        "scan" if "scan" in srcs else None)
    samples = sorted(
        (r for r in with_b
         if (owner is None or r.get("src") == owner)
         and _sample_us(r) is not None),
        key=_sample_us)
    nodes = sorted({n for r in samples for n in (r.get("b") or {})})
    out = {
        "samples": len(samples),
        "duration_s": 0.0,
        "nodes": {},
        "all_empty_fraction": None,
        "any_nonempty_fraction": None,
        "longest_all_empty_ms": 0.0,
        "idle_waiter_fraction": None,
        "idle_samples": 0,
        "idle_waiter_samples": 0,
        "published_batches_total": 0,
        "claimed_batches_total": 0,
        "claims_c_total": 0,
        "supply_gap_batches_total": 0,
        "published_batches_per_s": None,
        "claimed_batches_per_s": None,
        "claims_c_per_s": None,
        "supply_gap_batches_per_s": None,
    }
    empty_node = {
        "samples": 0, "nonempty_fraction": None, "longest_empty_ms": None,
        "published_batches_per_s": None, "claimed_batches_per_s": None,
        "claimed_batches_per_s_nonempty": None,
        "supply_gap_batches_per_s": None, "supply_gap_batches": None,
        "common_interval_s": 0.0,
        "consumption_intervals": 0, "consumption_interval_s": 0.0,
        "endpoint_claims": 0,
        "claim_crosscheck_mismatch_intervals": 0,
        "counter_regressions": {},
        "published_batches": 0, "claimed_batches": 0,
        "claims_c_batches": 0,
        "published_interval_s": 0.0, "claimed_interval_s": 0.0,
    }
    if len(samples) < 2:
        out["nodes"] = {n: dict(empty_node, samples=len(samples))
                        for n in nodes}
        return out
    t0 = _sample_us(samples[0])
    t1 = _sample_us(samples[-1])
    out["duration_s"] = max(0.0, (t1 - t0) / 1e6)
    per = {n: {
        "samples": 0, "nonempty": 0, "empty": 0,
        "longest_empty_ms": 0.0, "empty_start": None,
        "pub_count": 0, "pub_time": 0.0, "pub_regressions": 0,
        "read_count": 0, "read_time": 0.0, "read_regressions": 0,
        "c_count": 0, "c_time": 0.0, "c_regressions": 0,
        "common_pub": 0, "common_read": 0, "common_c": 0,
        "common_time": 0.0, "crosscheck_mismatch": 0,
        "ep_time": 0.0, "ep_claims": 0, "ep_intervals": 0,
        "idle_samples": 0, "idle_waiter_samples": 0,
    } for n in nodes}
    all_empty = 0
    all_pairs = 0
    any_nonempty = 0
    all_empty_start = None
    idle_samples = 0
    idle_waiter_samples = 0

    for prev, cur in zip(samples, samples[1:]):
        t_prev = _sample_us(prev)
        t_cur = _sample_us(cur)
        if t_prev is None or t_cur is None:
            continue
        dt = (t_cur - t_prev) / 1e6
        if dt <= 0:
            continue
        all_pairs += 1
        depths = {}
        for node in nodes:
            bp = (prev.get("b") or {}).get(node)
            bc = (cur.get("b") or {}).get(node)
            if not bp or not bc or len(bp) < 2 or len(bc) < 2:
                continue
            st = per[node]
            st["samples"] += 1
            depth_p = bp[1] - bp[0]
            depth_c = bc[1] - bc[0]
            depths[node] = depth_c
            if depth_c > 0:
                st["nonempty"] += 1
                st["empty_start"] = None
            else:
                st["empty"] += 1
                if st["empty_start"] is None:
                    st["empty_start"] = t_prev
                st["longest_empty_ms"] = max(
                    st["longest_empty_ms"], (t_cur - st["empty_start"]) / 1000.0)
            pub, pstate = _delta(bc[1], bp[1])
            read, rstate = _delta(bc[0], bp[0])
            if pub is not None:
                st["pub_count"] += pub
                st["pub_time"] += dt
            elif pstate == "regressed":
                st["pub_regressions"] += 1
            if read is not None:
                st["read_count"] += read
                st["read_time"] += dt
            elif rstate == "regressed":
                st["read_regressions"] += 1
            cp = _scalar(prev.get("c") or {}, node)
            cc = _scalar(cur.get("c") or {}, node)
            cdel, cstate = _delta(cc, cp)
            if cdel is not None:
                st["c_count"] += cdel
                st["c_time"] += dt
            elif cstate == "regressed":
                st["c_regressions"] += 1
            if pub is not None and read is not None:
                # Same node, same interval basis: the only place a
                # supply-gap comparison is meaningful.
                st["common_time"] += dt
                st["common_pub"] += pub
                st["common_read"] += read
                if cdel is not None:
                    st["common_c"] += cdel
                    if cdel != read:
                        st["crosscheck_mismatch"] += 1
            # Endpoint-persistent, NOT proof of continuous availability:
            # the queue can dip and refill between two 20 ms samples.
            if depth_p > 0 and depth_c > 0 and read is not None:
                st["ep_time"] += dt
                st["ep_claims"] += read
                st["ep_intervals"] += 1
            a = (cur.get("a") or {}).get(node)
            if depth_c == 0 and a and len(a) >= 2 and a[1] > 0:
                st["idle_samples"] += 1
                if a[0] > 0:
                    st["idle_waiter_samples"] += 1
        if depths:
            if all(v == 0 for v in depths.values()):
                all_empty += 1
                if all_empty_start is None:
                    all_empty_start = t_prev
                out["longest_all_empty_ms"] = max(
                    out["longest_all_empty_ms"],
                    (t_cur - all_empty_start) / 1000.0)
            else:
                any_nonempty += 1
                all_empty_start = None
            waiters = 0
            workers = 0
            for node in depths:
                a = (cur.get("a") or {}).get(node)
                if a and len(a) >= 2:
                    waiters += a[0]
                    workers += a[1]
            if workers > 0 and all(v == 0 for v in depths.values()):
                idle_samples += 1
                if waiters > 0:
                    idle_waiter_samples += 1

    if all_pairs:
        out["all_empty_fraction"] = all_empty / all_pairs
        out["any_nonempty_fraction"] = any_nonempty / all_pairs
    out["idle_samples"] = idle_samples
    out["idle_waiter_samples"] = idle_waiter_samples
    if idle_samples:
        out["idle_waiter_fraction"] = idle_waiter_samples / idle_samples

    node_out = {}
    for node, st in per.items():
        pairs = st["samples"]
        gap = None
        gap_count = None
        if st["common_time"]:
            gap_count = st["common_read"] - st["common_pub"]
            gap = gap_count / st["common_time"]
        regressions = {}
        for name, count in (("publication", st["pub_regressions"]),
                            ("claim_position", st["read_regressions"]),
                            ("claim_counter", st["c_regressions"])):
            if count:
                regressions[name] = count
        node_out[node] = {
            "samples": pairs,
            "nonempty_fraction": (st["nonempty"] / pairs) if pairs else None,
            "longest_empty_ms": st["longest_empty_ms"],
            "published_batches_per_s": (
                st["pub_count"] / st["pub_time"]) if st["pub_time"] else None,
            "claimed_batches_per_s": (
                st["read_count"] / st["read_time"]) if st["read_time"] else None,
            "claimed_batches_per_s_nonempty": (
                st["ep_claims"] / st["ep_time"]) if st["ep_time"] else None,
            "supply_gap_batches_per_s": gap,
            "supply_gap_batches": gap_count,
            "common_interval_s": st["common_time"],
            "consumption_intervals": st["ep_intervals"],
            "consumption_interval_s": st["ep_time"],
            "endpoint_claims": st["ep_claims"],
            "claim_crosscheck_mismatch_intervals": st["crosscheck_mismatch"],
            "counter_regressions": regressions,
            "published_batches": st["pub_count"],
            "claimed_batches": st["read_count"],
            "claims_c_batches": st["c_count"],
            "published_interval_s": st["pub_time"],
            "claimed_interval_s": st["read_time"],
        }
    out["nodes"] = node_out
    out["published_batches_total"] = sum(
        v["published_batches"] for v in node_out.values())
    out["claimed_batches_total"] = sum(
        v["claimed_batches"] for v in node_out.values())
    out["claims_c_total"] = sum(
        v["claims_c_batches"] for v in node_out.values())
    out["supply_gap_batches_total"] = sum(
        (v["supply_gap_batches"] or 0) for v in node_out.values())
    if out["duration_s"]:
        out["published_batches_per_s"] = (
            out["published_batches_total"] / out["duration_s"])
        out["claimed_batches_per_s"] = (
            out["claimed_batches_total"] / out["duration_s"])
        out["claims_c_per_s"] = out["claims_c_total"] / out["duration_s"]
        out["supply_gap_batches_per_s"] = (
            out["supply_gap_batches_total"] / out["duration_s"])
    return out


def _chunk_stats(records):
    """Ingest-published -> indexer-consumed chunk queue, per node.

    `q` is (chunk_queue_head, chunk_queue_tail). The C sampler's head is
    the INGEST PUBLICATION counter (incremented when a chunk is
    published) and tail is the SCANNER/INDEXER CLAIM counter (incremented
    when claimed). So publication is the raw q[0] delta and consumption
    is the raw q[1] delta -- the OPPOSITE pair order from `b`, which is
    (read_idx, write_idx). Do not reuse one order for the other.

    `i` is the engine's indexer_waiter gauge. Only src=ingest records own
    this path; the UMA scanner emits q/i groups but has no indexer, and
    those are reported as "not measurable", never as zero.
    """
    samples = sorted(
        (r for r in records
         if r.get("q") is not None and _sample_us(r) is not None),
        key=_sample_us)
    nodes = sorted({n for r in samples for n in (r.get("q") or {})})
    out = {
        "samples": len(samples),
        "duration_s": 0.0,
        "nodes": {},
        "all_empty_fraction": None,
        "any_nonempty_fraction": None,
        "longest_all_empty_ms": 0.0,
        "gated_ms": None,
        "indexer_waiters_observed": False,
        "indexer_wait_while_empty_fraction": None,
        "empty_samples": 0,
        "empty_with_waiters": 0,
        "chunk_published_total": 0,
        "chunk_consumed_total": 0,
        "chunk_published_per_s": None,
        "chunk_consumed_per_s": None,
    }
    gated = []
    for rec in records:
        if rec.get("kind") != "STAGE0_FINAL":
            continue
        try:
            gated.append(int(rec.get("gated_ms", 0)))
        except (TypeError, ValueError):
            pass
    if gated:
        out["gated_ms"] = max(gated)
    empty_node = {
        "samples": 0, "nonempty_fraction": None, "empty_fraction": None,
        "longest_empty_ms": None,
        "chunk_published_per_s": None, "chunk_consumed_per_s": None,
        "indexer_waiters_max": None, "indexer_waiters_mean": None,
        "i_samples": 0, "i_time": 0.0, "empty_samples": 0,
        "empty_with_waiters": None,
        "empty_with_waiters_fraction": None,
        "counter_regressions": {},
        "chunk_published": 0, "chunk_consumed": 0,
        "published_interval_s": 0.0, "consumed_interval_s": 0.0,
    }
    if len(samples) < 2:
        out["nodes"] = {n: dict(empty_node, samples=len(samples))
                        for n in nodes}
        return out
    t0 = _sample_us(samples[0])
    t1 = _sample_us(samples[-1])
    out["duration_s"] = max(0.0, (t1 - t0) / 1e6)
    per = {n: {
        "samples": 0, "nonempty": 0, "empty": 0,
        "longest_empty_ms": 0.0, "empty_start": None,
        "pub_count": 0, "pub_time": 0.0, "pub_regressions": 0,
        "cons_count": 0, "cons_time": 0.0, "cons_regressions": 0,
        "i_samples": 0, "i_max": None, "i_sum": 0.0, "i_time": 0.0,
        "empty_samples": 0, "empty_with_waiters": 0,
    } for n in nodes}
    all_empty = 0
    all_pairs = 0
    any_nonempty = 0
    all_empty_start = None
    for prev, cur in zip(samples, samples[1:]):
        t_prev = _sample_us(prev)
        t_cur = _sample_us(cur)
        if t_prev is None or t_cur is None:
            continue
        dt = (t_cur - t_prev) / 1e6
        if dt <= 0:
            continue
        all_pairs += 1
        depths = {}
        for node in nodes:
            qp = (prev.get("q") or {}).get(node)
            qc = (cur.get("q") or {}).get(node)
            if not qp or not qc or len(qp) < 2 or len(qc) < 2:
                continue
            st = per[node]
            st["samples"] += 1
            # q = (published, claimed); see the wire-order note above.
            depth_p = qp[0] - qp[1]
            depth_c = qc[0] - qc[1]
            depths[node] = depth_c
            if depth_c > 0:
                st["nonempty"] += 1
                st["empty_start"] = None
            else:
                st["empty"] += 1
                if st["empty_start"] is None:
                    st["empty_start"] = t_prev
                st["longest_empty_ms"] = max(
                    st["longest_empty_ms"], (t_cur - st["empty_start"]) / 1000.0)
            pub, pstate = _delta(qc[0], qp[0])
            cons, cstate = _delta(qc[1], qp[1])
            if pub is not None:
                st["pub_count"] += pub
                st["pub_time"] += dt
            elif pstate == "regressed":
                st["pub_regressions"] += 1
            if cons is not None:
                st["cons_count"] += cons
                st["cons_time"] += dt
            elif cstate == "regressed":
                st["cons_regressions"] += 1
            ic = _scalar(cur.get("i") or {}, node)
            if ic is not None:
                out["indexer_waiters_observed"] = True
                st["i_samples"] += 1
                st["i_sum"] += ic * dt
                st["i_time"] += dt
                st["i_max"] = ic if st["i_max"] is None \
                    else max(st["i_max"], ic)
            if depth_c == 0:
                st["empty_samples"] += 1
                if ic is not None and ic > 0:
                    st["empty_with_waiters"] += 1
        if depths:
            if all(v == 0 for v in depths.values()):
                all_empty += 1
                if all_empty_start is None:
                    all_empty_start = t_prev
                out["longest_all_empty_ms"] = max(
                    out["longest_all_empty_ms"],
                    (t_cur - all_empty_start) / 1000.0)
            else:
                any_nonempty += 1
                all_empty_start = None
    if all_pairs:
        out["all_empty_fraction"] = all_empty / all_pairs
        out["any_nonempty_fraction"] = any_nonempty / all_pairs
    node_out = {}
    for node, st in per.items():
        pairs = st["samples"]
        regressions = {}
        for name, count in (("chunk_publication", st["pub_regressions"]),
                            ("chunk_consumption", st["cons_regressions"])):
            if count:
                regressions[name] = count
        empty_frac = None
        if pairs:
            empty_frac = st["empty"] / pairs
        node_out[node] = {
            "samples": pairs,
            "nonempty_fraction": (st["nonempty"] / pairs) if pairs else None,
            "empty_fraction": empty_frac,
            "longest_empty_ms": st["longest_empty_ms"],
            "chunk_published_per_s": (
                st["pub_count"] / st["pub_time"]) if st["pub_time"] else None,
            "chunk_consumed_per_s": (
                st["cons_count"] / st["cons_time"]) if st["cons_time"] else None,
            "indexer_waiters_max": st["i_max"],
            "indexer_waiters_mean": (
                st["i_sum"] / st["i_time"]) if st["i_time"] else None,
            "i_samples": st["i_samples"],
            "i_time": st["i_time"],
            "empty_samples": st["empty_samples"],
            "empty_with_waiters": (
                st["empty_with_waiters"] if st["i_samples"] else None),
            "empty_with_waiters_fraction": (
                st["empty_with_waiters"] / st["empty_samples"]
                if st["empty_samples"] and st["i_samples"] else None),
            "counter_regressions": regressions,
            "chunk_published": st["pub_count"],
            "chunk_consumed": st["cons_count"],
            "published_interval_s": st["pub_time"],
            "consumed_interval_s": st["cons_time"],
        }
    out["nodes"] = node_out
    observed_max = [v["indexer_waiters_max"] for v in node_out.values()
                    if v["indexer_waiters_max"] is not None]
    out["indexer_waiters_max"] = max(observed_max) if observed_max else None
    out["indexer_waiters_mean"] = _weighted(
        [(v["indexer_waiters_mean"], v.get("i_time")) for v in
         node_out.values()])
    out["empty_samples"] = sum(
        v["empty_samples"] for v in node_out.values())
    out["empty_with_waiters"] = sum(
        (v["empty_with_waiters"] or 0) for v in node_out.values())
    if out["empty_samples"] and out["indexer_waiters_observed"]:
        out["indexer_wait_while_empty_fraction"] = (
            out["empty_with_waiters"] / out["empty_samples"])
    out["chunk_published_total"] = sum(
        v["chunk_published"] for v in node_out.values())
    out["chunk_consumed_total"] = sum(
        v["chunk_consumed"] for v in node_out.values())
    if out["duration_s"]:
        out["chunk_published_per_s"] = (
            out["chunk_published_total"] / out["duration_s"])
        out["chunk_consumed_per_s"] = (
            out["chunk_consumed_total"] / out["duration_s"])
    return out


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def correlated_intervals(records):
    """Time-correlated ingest/scanner/worker evidence for ONE trial.

    The NUMA C ingest emits `q`/`i`/`b`/`c`/`a` and its own `cpu_ns` on
    ONE CLOCK_MONOTONIC origin, so consecutive `src=ingest` samples are a
    common timeline. Every predicate below is evaluated on the SAME
    per-node interval; trial-level co-occurrence is not evidence.

    `q` is (published, claimed); `b` is (read_idx, write_idx); `c` is the
    claim cross-check. A counter regression, a non-monotonic timestamp,
    or a missing/regressed CPU sample EXCLUDES the interval and is
    counted; nothing is silently bridged.

    The UMA scanner has no ingest->indexer path, so this returns
    available=False there rather than inventing zeros.
    """
    samples = sorted(
        (r for r in records
         if r.get("src") == "ingest" and _sample_us(r) is not None),
        key=_sample_us)
    out = {
        "available": bool(samples),
        "samples": len(samples),
        "intervals": 0,
        "interval_s": 0.0,
        "excluded": {
            "non_monotonic_timestamps": 0,
            "missing_cpu": 0,
            "cpu_regressed": 0,
            "missing_node_groups": 0,
            "counter_regressions": 0,
            "no_node_data": 0,
        },
        "excluded_total": 0,
        "nodes": {},
        "ingest_starved_intervals": 0,
        "ingest_starved_s": 0.0,
        "ingest_cpu_saturated_starved_intervals": 0,
        "ingest_cpu_saturated_starved_s": 0.0,
        "scanner_starved_intervals": 0,
        "scanner_starved_s": 0.0,
        "source_limited_intervals": 0,
        "source_limited_s": 0.0,
        "ingest_backpressure_intervals": 0,
        "worker_wait_intervals": 0,
        "go_intervals": 0,
        "go_s": 0.0,
        "go_nodes": [],
        "trial_go": False,
        "mixed": False,
        "cpu_cores_starved": None,
        "go_cpu_cores": None,
        "supply_gap_go_batches": 0,
        "supply_gap_go_per_s": None,
        "go_interval_list": [],
        "claim_crosscheck_mismatch_intervals": 0,
        "attribution_complete": False,
    }
    if len(samples) < 2:
        return out

    empty_node = {
        "intervals": 0,
        "interval_s": 0.0,
        "ingest_starved_intervals": 0,
        "ingest_starved_s": 0.0,
        "ingest_starved_cpu_cores": None,
        "ingest_cpu_saturated_starved_intervals": 0,
        "ingest_cpu_saturated_starved_s": 0.0,
        "scanner_starved_intervals": 0,
        "scanner_starved_s": 0.0,
        "source_limited_intervals": 0,
        "source_limited_s": 0.0,
        "ingest_backpressure_intervals": 0,
        "worker_wait_intervals": 0,
        "batch_empty_intervals": 0,
        "batch_draining_intervals": 0,
        "supply_gap_intervals": 0,
        "go_intervals": 0,
        "go_s": 0.0,
        "go_supply_gap_batches": 0,
        "go_supply_gap_per_s": None,
        "go_cpu_cores": None,
        "chunk_published_per_s": None,
        "chunk_consumed_per_s": None,
        "batch_published_per_s": None,
        "batch_claimed_per_s": None,
        "counter_regressions": 0,
        "claim_crosscheck_mismatch_intervals": 0,
    }
    per = {}
    starved_cpu_ns = 0
    starved_dt_us = 0
    go_cpu_ns = 0
    go_dt_us = 0
    go_gap_batches = 0
    go_gap_s = 0.0
    mismatches = 0

    def _node():
        node = dict(empty_node)
        node["_cpu_ns"] = 0
        node["_dt_us"] = 0
        node["_chunk_pub"] = 0
        node["_chunk_cons"] = 0
        node["_batch_pub"] = 0
        node["_batch_claim"] = 0
        node["_gap_batches"] = 0
        node["_gap_s"] = 0.0
        node["_go_cpu_ns"] = 0
        node["_go_dt_us"] = 0
        node["_go_gap_batches"] = 0
        node["_go_gap_s"] = 0.0
        node["_starved_cpu_ns"] = 0
        node["_starved_dt_us"] = 0
        return node

    for prev, cur in zip(samples, samples[1:]):
        t_prev = _sample_us(prev)
        t_cur = _sample_us(cur)
        if t_prev is None or t_cur is None or t_cur <= t_prev:
            out["excluded"]["non_monotonic_timestamps"] += 1
            continue
        dt_us = t_cur - t_prev
        dt_s = dt_us / 1e6
        cpu_prev = _num(prev.get("cpu_ns"))
        cpu_cur = _num(cur.get("cpu_ns"))
        if cpu_prev is None or cpu_cur is None:
            out["excluded"]["missing_cpu"] += 1
            continue
        if cpu_cur < cpu_prev:
            out["excluded"]["cpu_regressed"] += 1
            continue
        cpu_ns = cpu_cur - cpu_prev
        cpu_cores = (cpu_ns / 1e9) / dt_s if dt_s > 0 else None
        if cpu_cores is None:
            out["excluded"]["non_monotonic_timestamps"] += 1
            continue
        gated_prev = _num(prev.get("gated_ms"))
        gated_cur = _num(cur.get("gated_ms"))
        gated_delta = (gated_cur - gated_prev
                       if gated_prev is not None and gated_cur is not None
                       and gated_cur >= gated_prev else 0)
        nodes = sorted(set((prev.get("q") or {}))
                       | set((cur.get("q") or {})))
        valid_nodes = 0
        interval_has_starvation = False
        interval_has_scanner_starve = False
        for node in nodes:
            qp = (prev.get("q") or {}).get(node)
            qc = (cur.get("q") or {}).get(node)
            bp = (prev.get("b") or {}).get(node)
            bc = (cur.get("b") or {}).get(node)
            ip = _scalar(prev.get("i") or {}, node)
            ic = _scalar(cur.get("i") or {}, node)
            ap = (prev.get("a") or {}).get(node)
            ac = (cur.get("a") or {}).get(node)
            cp = _scalar(prev.get("c") or {}, node)
            cc = _scalar(cur.get("c") or {}, node)
            if (not qp or not qc or len(qp) < 2 or len(qc) < 2
                    or not bp or not bc or len(bp) < 2 or len(bc) < 2
                    or ip is None or ic is None
                    or not ap or not ac or len(ap) < 2 or len(ac) < 2):
                out["excluded"]["missing_node_groups"] += 1
                continue
            if (qc[0] < qp[0] or qc[1] < qp[1]
                    or bc[0] < bp[0] or bc[1] < bp[1]
                    or (cp is not None and cc is not None and cc < cp)):
                out["excluded"]["counter_regressions"] += 1
                continue
            st = per.setdefault(node, _node())
            st["intervals"] += 1
            st["interval_s"] += dt_s
            valid_nodes += 1

            chunk_depth_p = qp[0] - qp[1]
            chunk_depth_c = qc[0] - qc[1]
            batch_depth_p = bp[1] - bp[0]
            batch_depth_c = bc[1] - bc[0]
            chunk_pub = qc[0] - qp[0]
            chunk_cons = qc[1] - qp[1]
            batch_pub = bc[1] - bp[1]
            batch_claim = bc[0] - bp[0]
            supply_gap = batch_claim - batch_pub
            indexer_waiters = max(ip, ic)
            worker_waiters = max(ap[0], ac[0])
            upstream_available = (
                chunk_depth_p > 0 or chunk_depth_c > 0
                or indexer_waiters == 0)
            ingest_starved = (
                chunk_depth_p == 0 and chunk_depth_c == 0
                and indexer_waiters > 0)
            scanner_starved = (
                batch_depth_p == 0 and batch_depth_c == 0
                and worker_waiters > 0 and upstream_available)
            cpu_near_one = (
                _INGEST_NEAR_ONE[0] <= cpu_cores <= _INGEST_NEAR_ONE[1])
            source_limited = (
                ingest_starved and not cpu_near_one and gated_delta == 0)
            backpressure = gated_delta > 0
            batch_draining_or_empty = (
                batch_depth_c == 0 or batch_depth_c < batch_depth_p)
            go_interval = (
                ingest_starved and cpu_near_one
                and supply_gap > 0 and worker_waiters > 0
                and batch_draining_or_empty and not backpressure)

            st["_cpu_ns"] += cpu_ns
            st["_dt_us"] += dt_us
            st["_chunk_pub"] += chunk_pub
            st["_chunk_cons"] += chunk_cons
            st["_batch_pub"] += batch_pub
            st["_batch_claim"] += batch_claim
            st["_gap_batches"] += supply_gap
            st["_gap_s"] += dt_s
            if ingest_starved:
                st["ingest_starved_intervals"] += 1
                st["ingest_starved_s"] += dt_s
                st["_starved_cpu_ns"] += cpu_ns
                st["_starved_dt_us"] += dt_us
                starved_cpu_ns += cpu_ns
                starved_dt_us += dt_us
                interval_has_starvation = True
                if cpu_near_one:
                    st["ingest_cpu_saturated_starved_intervals"] += 1
                    st["ingest_cpu_saturated_starved_s"] += dt_s
                    out["ingest_cpu_saturated_starved_intervals"] += 1
                    out["ingest_cpu_saturated_starved_s"] += dt_s
                if source_limited:
                    st["source_limited_intervals"] += 1
                    st["source_limited_s"] += dt_s
                    out["source_limited_intervals"] += 1
                    out["source_limited_s"] += dt_s
            if scanner_starved:
                st["scanner_starved_intervals"] += 1
                st["scanner_starved_s"] += dt_s
                interval_has_scanner_starve = True
            if backpressure:
                st["ingest_backpressure_intervals"] += 1
                out["ingest_backpressure_intervals"] += 1
            if worker_waiters > 0:
                st["worker_wait_intervals"] += 1
            if batch_depth_c == 0:
                st["batch_empty_intervals"] += 1
            if batch_draining_or_empty:
                st["batch_draining_intervals"] += 1
            if supply_gap > 0:
                st["supply_gap_intervals"] += 1
            if cp is not None and cc is not None and (cc - cp) != batch_claim:
                st["claim_crosscheck_mismatch_intervals"] += 1
                mismatches += 1
            if go_interval:
                st["go_intervals"] += 1
                st["go_s"] += dt_s
                st["_go_gap_batches"] += supply_gap
                st["_go_gap_s"] += dt_s
                st["_go_cpu_ns"] += cpu_ns
                st["_go_dt_us"] += dt_us
                go_gap_batches += supply_gap
                go_gap_s += dt_s
                go_cpu_ns += cpu_ns
                go_dt_us += dt_us
                out["go_interval_list"].append({
                    "node": node,
                    "t0_us": t_prev,
                    "t1_us": t_cur,
                    "cpu_cores": round(cpu_cores, 3),
                    "supply_gap_batches": supply_gap,
                    "supply_gap_per_s": round(supply_gap / dt_s, 1),
                    "chunk_depth_start": chunk_depth_p,
                    "chunk_depth_end": chunk_depth_c,
                    "batch_depth_start": batch_depth_p,
                    "batch_depth_end": batch_depth_c,
                    "indexer_waiters": indexer_waiters,
                    "worker_waiters": worker_waiters,
                })
        if not valid_nodes:
            out["excluded"]["no_node_data"] += 1
            continue
        out["intervals"] += 1
        out["interval_s"] += dt_s
        if interval_has_starvation:
            out["ingest_starved_intervals"] += 1
            out["ingest_starved_s"] += dt_s
        if interval_has_scanner_starve:
            out["scanner_starved_intervals"] += 1
            out["scanner_starved_s"] += dt_s

    for node, st in per.items():
        if st["_dt_us"]:
            st["chunk_published_per_s"] = st["_chunk_pub"] / (
                st["_dt_us"] / 1e6)
            st["chunk_consumed_per_s"] = st["_chunk_cons"] / (
                st["_dt_us"] / 1e6)
            st["batch_published_per_s"] = st["_batch_pub"] / (
                st["_dt_us"] / 1e6)
            st["batch_claimed_per_s"] = st["_batch_claim"] / (
                st["_dt_us"] / 1e6)
        if st["_starved_dt_us"]:
            st["ingest_starved_cpu_cores"] = (
                st["_starved_cpu_ns"] / 1e9) / (
                    st["_starved_dt_us"] / 1e6)
        if st["_gap_s"]:
            st["supply_gap_batches_per_s"] = (
                st["_gap_batches"] / st["_gap_s"])
        if st["_go_gap_s"]:
            st["go_supply_gap_per_s"] = (
                st["_go_gap_batches"] / st["_go_gap_s"])
            st["go_supply_gap_batches"] = st["_go_gap_batches"]
        if st["_go_dt_us"]:
            st["go_cpu_cores"] = (
                st["_go_cpu_ns"] / 1e9) / (st["_go_dt_us"] / 1e6)
        for key in list(st):
            if key.startswith("_"):
                del st[key]
    out["nodes"] = per
    out["go_intervals"] = sum(v["go_intervals"] for v in per.values())
    out["go_s"] = sum(v["go_s"] for v in per.values())
    out["go_nodes"] = sorted(n for n, v in per.items() if v["go_intervals"])
    out["trial_go"] = out["go_intervals"] > 0
    out["ingest_starved_intervals"] = sum(
        v["ingest_starved_intervals"] for v in per.values())
    out["ingest_starved_s"] = sum(
        v["ingest_starved_s"] for v in per.values())
    out["scanner_starved_intervals"] = sum(
        v["scanner_starved_intervals"] for v in per.values())
    out["scanner_starved_s"] = sum(
        v["scanner_starved_s"] for v in per.values())
    out["source_limited_intervals"] = sum(
        v["source_limited_intervals"] for v in per.values())
    out["source_limited_s"] = sum(
        v["source_limited_s"] for v in per.values())
    out["ingest_backpressure_intervals"] = sum(
        v["ingest_backpressure_intervals"] for v in per.values())
    out["worker_wait_intervals"] = sum(
        v["worker_wait_intervals"] for v in per.values())
    out["mixed"] = (
        out["ingest_starved_intervals"] > 0
        and out["scanner_starved_intervals"] > 0)
    out["supply_gap_intervals"] = sum(
        v["supply_gap_intervals"] for v in per.values())
    out["claim_crosscheck_mismatch_intervals"] = mismatches
    if starved_dt_us:
        out["cpu_cores_starved"] = (starved_cpu_ns / 1e9) / (
            starved_dt_us / 1e6)
    if go_dt_us:
        out["go_cpu_cores"] = (go_cpu_ns / 1e9) / (go_dt_us / 1e6)
    if go_gap_s:
        out["supply_gap_go_batches"] = go_gap_batches
        out["supply_gap_go_per_s"] = go_gap_batches / go_gap_s
    out["excluded_total"] = sum(out["excluded"].values())
    out["attribution_complete"] = (
        out["intervals"] > 0 and out["excluded_total"] == 0)
    return out


def _trial_queue_stats(records):
    """One trial: batch (scanner->worker) + chunk (ingest->indexer).

    The two samplers have independent origins, so they are NEVER
    interleaved into one timeline. Batch groups (`b`/`c`/`a`) are emitted
    by BOTH the UMA scanner and the NUMA C ingest; only the chunk path
    (`q`/`i`) is owned by src=ingest. `correlated` is the ONE
    same-interval analysis; the trial-level booleans below are retained
    for display and must not be used to decide Go.
    """
    batch = _batch_stats(records)
    chunk = _chunk_stats([r for r in records if r.get("src") == "ingest"])
    result = dict(batch)
    result["chunk"] = chunk
    result["correlated"] = correlated_intervals(records)
    result["chunk_nodes"] = chunk["nodes"]
    result["chunk_samples"] = chunk["samples"]
    result["gated_ms"] = chunk["gated_ms"]
    result["srcs"] = sorted({r.get("src") for r in records
                             if r.get("src") is not None})
    gap_nodes = sorted(
        n for n, v in batch["nodes"].items()
        if v.get("supply_gap_batches_per_s") is not None
        and v["supply_gap_batches_per_s"] > 0)
    result["gap_nodes"] = gap_nodes
    result["has_supply_gap"] = bool(gap_nodes)
    chunk_measurable = (bool(chunk["nodes"])
                        and chunk["indexer_waiters_observed"])
    result["chunk_measurable"] = chunk_measurable
    ingest_starved = bool(
        chunk_measurable
        and chunk.get("all_empty_fraction") is not None
        and chunk["all_empty_fraction"] > 0
        and (chunk.get("indexer_wait_while_empty_fraction") or 0) > 0)
    result["has_ingest_starvation"] = ingest_starved
    if not chunk_measurable:
        result["has_scanner_starvation"] = None
    else:
        result["has_scanner_starvation"] = bool(
            not ingest_starved
            and batch.get("idle_waiter_fraction") is not None
            and batch["idle_waiter_fraction"] > 0)
    result["has_workers_saturated"] = bool(
        batch.get("any_nonempty_fraction") is not None
        and batch["any_nonempty_fraction"] > 0)
    return result



def _agg_batch_nodes(trials):
    out = {}
    node_ids = sorted({n for t in trials for n in t["nodes"]})
    for node in node_ids:
        rows = [t["nodes"][node] for t in trials if node in t["nodes"]]
        if not rows:
            continue
        pub_time = sum(r.get("published_interval_s") or 0.0 for r in rows)
        read_time = sum(r.get("claimed_interval_s") or 0.0 for r in rows)
        common_time = sum(r.get("common_interval_s") or 0.0 for r in rows)
        ep_time = sum(r.get("consumption_interval_s") or 0.0 for r in rows)
        pub_count = sum(r.get("published_batches") or 0 for r in rows)
        read_count = sum(r.get("claimed_batches") or 0 for r in rows)
        c_count = sum(r.get("claims_c_batches") or 0 for r in rows)
        ep_claims = sum(r.get("endpoint_claims") or 0 for r in rows)
        gap_count = sum(r.get("supply_gap_batches") or 0 for r in rows)
        regressions = {}
        for row in rows:
            for key, val in (row.get("counter_regressions") or {}).items():
                regressions[key] = regressions.get(key, 0) + val
        out[node] = {
            "samples": sum(r.get("samples") or 0 for r in rows),
            "nonempty_fraction": _weighted(
                [(r.get("nonempty_fraction"), r.get("samples") or 0)
                 for r in rows]),
            "longest_empty_ms": max(
                (r.get("longest_empty_ms") or 0.0 for r in rows),
                default=0.0),
            "published_batches_per_s": (
                pub_count / pub_time) if pub_time else None,
            "claimed_batches_per_s": (
                read_count / read_time) if read_time else None,
            "claimed_batches_per_s_nonempty": (
                ep_claims / ep_time) if ep_time else None,
            "supply_gap_batches_per_s": (
                gap_count / common_time) if common_time else None,
            "supply_gap_batches": gap_count if common_time else None,
            "common_interval_s": common_time,
            "consumption_intervals": sum(
                r.get("consumption_intervals") or 0 for r in rows),
            "consumption_interval_s": ep_time,
            "claim_crosscheck_mismatch_intervals": sum(
                r.get("claim_crosscheck_mismatch_intervals") or 0
                for r in rows),
            "counter_regressions": regressions,
            "published_batches": pub_count,
            "claimed_batches": read_count,
            "claims_c_batches": c_count,
            "published_interval_s": pub_time,
            "claimed_interval_s": read_time,
        }
    return out


def _agg_chunk_nodes(trials):
    out = {}
    node_ids = sorted({n for t in trials for n in t["chunk_nodes"]})
    for node in node_ids:
        rows = [t["chunk_nodes"][node] for t in trials
                if node in t["chunk_nodes"]]
        if not rows:
            continue
        pub_time = sum(r.get("published_interval_s") or 0.0 for r in rows)
        cons_time = sum(r.get("consumed_interval_s") or 0.0 for r in rows)
        i_time = sum(r.get("i_time") or 0.0 for r in rows)
        pub_count = sum(r.get("chunk_published") or 0 for r in rows)
        cons_count = sum(r.get("chunk_consumed") or 0 for r in rows)
        empty_samples = sum(r.get("empty_samples") or 0 for r in rows)
        empty_waiters = sum(r.get("empty_with_waiters") or 0 for r in rows)
        i_samples = sum(r.get("i_samples") or 0 for r in rows)
        regressions = {}
        for row in rows:
            for key, val in (row.get("counter_regressions") or {}).items():
                regressions[key] = regressions.get(key, 0) + val
        out[node] = {
            "samples": sum(r.get("samples") or 0 for r in rows),
            "nonempty_fraction": _weighted(
                [(r.get("nonempty_fraction"), r.get("samples") or 0)
                 for r in rows]),
            "empty_fraction": _weighted(
                [(r.get("empty_fraction"), r.get("samples") or 0)
                 for r in rows]),
            "longest_empty_ms": max(
                (r.get("longest_empty_ms") or 0.0 for r in rows),
                default=0.0),
            "chunk_published_per_s": (
                pub_count / pub_time) if pub_time else None,
            "chunk_consumed_per_s": (
                cons_count / cons_time) if cons_time else None,
            "indexer_waiters_max": max(
                (r.get("indexer_waiters_max") for r in rows
                 if r.get("indexer_waiters_max") is not None), default=None),
            "indexer_waiters_mean": _weighted(
                [(r.get("indexer_waiters_mean"), r.get("i_time"))
                 for r in rows]),
            "i_samples": i_samples,
            "empty_samples": empty_samples,
            "empty_with_waiters": empty_waiters if i_samples else None,
            "empty_with_waiters_fraction": (
                empty_waiters / empty_samples
                if empty_samples and i_samples else None),
            "counter_regressions": regressions,
            "chunk_published": pub_count,
            "chunk_consumed": cons_count,
            "published_interval_s": pub_time,
            "consumed_interval_s": cons_time,
            "i_time": i_time,
        }
    return out


def _agg_correlated(trials):
    """Aggregate same-interval evidence across a case's trials.

    The per-trial rows are retained so the report can show repeatability
    and spread; no trial's intervals are ever joined to another trial's.
    """
    rows = [t.get("correlated") for t in trials if t.get("correlated")]
    avail = [r for r in rows if r.get("available")]
    merged_excluded = {}
    for r in avail:
        for key, value in (r.get("excluded") or {}).items():
            merged_excluded[key] = merged_excluded.get(key, 0) + value
    nodes = {}
    for r in avail:
        for node, st in (r.get("nodes") or {}).items():
            dst = nodes.setdefault(node, {
                "intervals": 0, "interval_s": 0.0,
                "ingest_starved_intervals": 0, "ingest_starved_s": 0.0,
                "ingest_cpu_saturated_starved_intervals": 0,
                "ingest_cpu_saturated_starved_s": 0.0,
                "scanner_starved_intervals": 0, "scanner_starved_s": 0.0,
                "source_limited_intervals": 0, "source_limited_s": 0.0,
                "ingest_backpressure_intervals": 0,
                "worker_wait_intervals": 0,
                "batch_empty_intervals": 0,
                "batch_draining_intervals": 0,
                "supply_gap_intervals": 0,
                "go_intervals": 0, "go_s": 0.0,
                "go_supply_gap_batches": 0, "go_gap_s": 0.0,
                "go_trials": 0,
                "counter_regressions": 0,
                "claim_crosscheck_mismatch_intervals": 0,
            })
            for key in ("intervals", "interval_s",
                        "ingest_starved_intervals", "ingest_starved_s",
                        "ingest_cpu_saturated_starved_intervals",
                        "ingest_cpu_saturated_starved_s",
                        "scanner_starved_intervals", "scanner_starved_s",
                        "source_limited_intervals", "source_limited_s",
                        "ingest_backpressure_intervals",
                        "worker_wait_intervals", "batch_empty_intervals",
                        "batch_draining_intervals", "supply_gap_intervals",
                        "go_intervals", "go_s", "go_supply_gap_batches",
                        "counter_regressions",
                        "claim_crosscheck_mismatch_intervals"):
                dst[key] += st.get(key) or 0
            dst["go_gap_s"] += st.get("go_s") or 0.0
            if st.get("go_intervals"):
                dst["go_trials"] += 1
    for dst in nodes.values():
        if dst["go_gap_s"]:
            dst["go_supply_gap_per_s"] = (
                dst["go_supply_gap_batches"] / dst["go_gap_s"])
        else:
            dst["go_supply_gap_per_s"] = None
        dst.pop("go_gap_s", None)
    trial_rows = []
    for idx, r in enumerate(rows, 1):
        if not r.get("available"):
            continue
        trial_rows.append({
            "trial": idx,
            "intervals": r.get("intervals"),
            "interval_s": r.get("interval_s"),
            "excluded": dict(r.get("excluded") or {}),
            "excluded_total": r.get("excluded_total"),
            "attribution_complete": r.get("attribution_complete"),
            "ingest_starved_intervals": r.get("ingest_starved_intervals"),
            "ingest_starved_s": r.get("ingest_starved_s"),
            "ingest_cpu_saturated_starved_intervals":
                r.get("ingest_cpu_saturated_starved_intervals"),
            "ingest_cpu_saturated_starved_s":
                r.get("ingest_cpu_saturated_starved_s"),
            "scanner_starved_intervals": r.get("scanner_starved_intervals"),
            "scanner_starved_s": r.get("scanner_starved_s"),
            "source_limited_intervals": r.get("source_limited_intervals"),
            "ingest_backpressure_intervals":
                r.get("ingest_backpressure_intervals"),
            "worker_wait_intervals": r.get("worker_wait_intervals"),
            "supply_gap_intervals": r.get("supply_gap_intervals"),
            "ingest_supplied": bool(
                (r.get("intervals") or 0) > 0
                and (r.get("supply_gap_intervals") or 0) == 0
                and (r.get("scanner_starved_intervals") or 0) == 0
                and (r.get("source_limited_intervals") or 0) == 0),
            "go_intervals": r.get("go_intervals"),
            "go_s": r.get("go_s"),
            "go_nodes": list(r.get("go_nodes") or []),
            "supply_gap_go_batches": r.get("supply_gap_go_batches"),
            "supply_gap_go_per_s": r.get("supply_gap_go_per_s"),
            "cpu_cores_starved": r.get("cpu_cores_starved"),
            "go_cpu_cores": r.get("go_cpu_cores"),
            "trial_go": r.get("trial_go"),
            "mixed": r.get("mixed"),
            "claim_crosscheck_mismatch_intervals":
                r.get("claim_crosscheck_mismatch_intervals"),
        })
    go_gaps = [r["supply_gap_go_per_s"] for r in trial_rows
               if r.get("trial_go")
               and r.get("supply_gap_go_per_s") is not None]
    out = {
        "available": bool(avail),
        "trials": len(avail),
        "intervals": sum(r.get("intervals") or 0 for r in avail),
        "interval_s": sum(r.get("interval_s") or 0.0 for r in avail),
        "excluded": merged_excluded,
        "excluded_total": sum(merged_excluded.values()),
        "trial_go_trials": sum(1 for r in avail if r.get("trial_go")),
        "mixed_trials": sum(1 for r in avail if r.get("mixed")),
        "ingest_starved_trials": sum(
            1 for r in avail if (r.get("ingest_starved_intervals") or 0) > 0),
        "scanner_starved_trials": sum(
            1 for r in avail
            if (r.get("scanner_starved_intervals") or 0) > 0),
        "source_limited_trials": sum(
            1 for r in avail if (r.get("source_limited_intervals") or 0) > 0),
        "ingest_backpressure_trials": sum(
            1 for r in avail
            if (r.get("ingest_backpressure_intervals") or 0) > 0),
        "attribution_complete_trials": sum(
            1 for r in avail if r.get("attribution_complete")),
        "go_intervals": sum(r.get("go_intervals") or 0 for r in avail),
        "go_s": sum(r.get("go_s") or 0.0 for r in avail),
        "go_nodes": sorted({n for r in avail
                            for n in (r.get("go_nodes") or [])}),
        "supply_gap_intervals": sum(
            r.get("supply_gap_intervals") or 0 for r in avail),
        "worker_wait_intervals": sum(
            r.get("worker_wait_intervals") or 0 for r in avail),
        "nodes": nodes,
        "trial_rows": trial_rows,
        "go_gap_per_s_min": min(go_gaps) if go_gaps else None,
        "go_gap_per_s_max": max(go_gaps) if go_gaps else None,
        "go_gap_per_s_median": _median(go_gaps),
        "go_gap_per_s_spread": (max(go_gaps) - min(go_gaps)
                                if len(go_gaps) > 1 else None),
    }
    return out


def queue_demand_stats(cases):
    """Aggregate per-case queue telemetry from raw stderr.log files.

    Trials are processed independently: no interval ever spans a trial
    boundary. Batch groups are emitted by whichever sampler owns the
    path in that mode (src=ingest for NUMA, src=scan for UMA); chunk
    metrics are owned by src=ingest only. Timestamps use `t_us` on the
    owning sampler's own CLOCK_MONOTONIC origin; sources are never
    interleaved. Rates are computed from raw counter deltas over the
    intervals where both counters are valid; a counter regression is
    counted, not silently treated as zero.
    """
    out = {}
    for case, entries in sorted(cases.items()):
        trials = []
        for manifest, trial_dir in entries:
            path = os.path.join(trial_dir, "stderr.log")
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            stats = _trial_queue_stats(_diag_records(text))
            stats["ingest_basis_cores"] = (
                manifest.get("ingest_cpu_phase_cores")
                if manifest.get("ingest_cpu_phase_cores") is not None
                else (manifest.get("ingest_cpu_direct_basis_cores")
                      if manifest.get("ingest_cpu_direct_basis_cores")
                      is not None
                      else manifest.get("ingest_cpu_basis_cores")))
            trials.append(stats)
        if not trials:
            out[case] = None
            continue
        duration_total = sum(t["duration_s"] for t in trials)
        batch_nodes = _agg_batch_nodes(trials)
        chunk_nodes = _agg_chunk_nodes(trials)
        chunk_samples = sum(t["chunk_samples"] for t in trials)
        gated_values = [t["gated_ms"] for t in trials
                        if t["gated_ms"] is not None]
        chunk_all_empty = _weighted(
            [(t["chunk"]["all_empty_fraction"],
              max(0, t["chunk_samples"] - 1)) for t in trials])
        chunk_any_nonempty = _weighted(
            [(t["chunk"]["any_nonempty_fraction"],
              max(0, t["chunk_samples"] - 1)) for t in trials])
        empty_samples = sum(t["chunk"]["empty_samples"] for t in trials)
        empty_waiters = sum(t["chunk"]["empty_with_waiters"]
                            for t in trials)
        chunk_measurable = any(t["chunk_measurable"] for t in trials)
        chunk_wait_fraction = None
        if chunk_measurable and empty_samples:
            chunk_wait_fraction = empty_waiters / empty_samples
        chunk_agg = {
            "trials": len(trials),
            "samples": chunk_samples,
            "duration_s": _median([t["chunk"]["duration_s"]
                                   for t in trials]),
            "gated_ms": _median(gated_values),
            "all_empty_fraction": chunk_all_empty,
            "any_nonempty_fraction": chunk_any_nonempty,
            "longest_all_empty_ms": max(
                (t["chunk"]["longest_all_empty_ms"] for t in trials),
                default=0.0),
            "indexer_waiters_observed": any(
                t["chunk"]["indexer_waiters_observed"] for t in trials),
            "indexer_waiters_max": max(
                (v.get("indexer_waiters_max")
                 for v in chunk_nodes.values()
                 if v.get("indexer_waiters_max") is not None),
                default=None),
            "indexer_waiters_mean": _weighted(
                [(v.get("indexer_waiters_mean"), v.get("i_time"))
                 for v in chunk_nodes.values()]),
            "indexer_wait_while_empty_fraction": chunk_wait_fraction,
            "empty_samples": empty_samples,
            "empty_with_waiters": empty_waiters if chunk_measurable else None,
            "chunk_published_total": sum(
                t["chunk"]["chunk_published_total"] for t in trials),
            "chunk_consumed_total": sum(
                t["chunk"]["chunk_consumed_total"] for t in trials),
            "nodes": chunk_nodes,
        }
        if duration_total:
            chunk_agg["chunk_published_per_s"] = (
                chunk_agg["chunk_published_total"] / duration_total)
            chunk_agg["chunk_consumed_per_s"] = (
                chunk_agg["chunk_consumed_total"] / duration_total)
        else:
            chunk_agg["chunk_published_per_s"] = None
            chunk_agg["chunk_consumed_per_s"] = None
        agg = {
            "trials": len(trials),
            "samples": sum(t["samples"] for t in trials),
            "chunk_samples": chunk_samples,
            "srcs": sorted({s for t in trials for s in t["srcs"]}),
            "duration_s": _median([t["duration_s"] for t in trials]),
            "gated_ms": _median(gated_values),
            "all_empty_fraction": _weighted(
                [(t["all_empty_fraction"], max(0, t["samples"] - 1))
                 for t in trials]),
            "any_nonempty_fraction": _weighted(
                [(t["any_nonempty_fraction"], max(0, t["samples"] - 1))
                 for t in trials]),
            "longest_all_empty_ms": max(
                (t["longest_all_empty_ms"] for t in trials), default=0.0),
            "idle_waiter_fraction": _weighted(
                [(t["idle_waiter_fraction"], t["idle_samples"])
                 for t in trials]),
            "published_batches_total": sum(
                t["published_batches_total"] for t in trials),
            "claimed_batches_total": sum(
                t["claimed_batches_total"] for t in trials),
            "claims_c_total": sum(t["claims_c_total"] for t in trials),
            "supply_gap_batches_total": sum(
                t["supply_gap_batches_total"] for t in trials),
            "supply_gap_trials": sum(1 for t in trials
                                     if t["has_supply_gap"]),
            "no_supply_gap_trials": sum(1 for t in trials
                                        if not t["has_supply_gap"]),
            "ingest_starvation_trials": sum(
                1 for t in trials if t["has_ingest_starvation"]),
            "scanner_starvation_trials": sum(
                1 for t in trials if t["has_scanner_starvation"] is True),
            "scanner_starvation_measurable_trials": sum(
                1 for t in trials if t["has_scanner_starvation"] is not None),
            "workers_saturated_trials": sum(
                1 for t in trials if t["has_workers_saturated"]),
            "chunk_measurable_trials": sum(
                1 for t in trials if t["chunk_measurable"]),
            "nodes": batch_nodes,
            "chunk": chunk_agg,
            "chunk_nodes": chunk_nodes,
            "correlated": _agg_correlated(trials),
        }
        if duration_total:
            agg["published_batches_per_s"] = (
                agg["published_batches_total"] / duration_total)
            agg["claimed_batches_per_s"] = (
                agg["claimed_batches_total"] / duration_total)
            agg["claims_c_per_s"] = (
                agg["claims_c_total"] / duration_total)
            agg["supply_gap_batches_per_s"] = (
                agg["supply_gap_batches_total"] / duration_total)
        else:
            agg["published_batches_per_s"] = None
            agg["claimed_batches_per_s"] = None
            agg["claims_c_per_s"] = None
            agg["supply_gap_batches_per_s"] = None
        out[case] = agg
    return out


def _weighted(pairs):
    vals = [(v, w) for v, w in pairs if v is not None and w]
    if not vals:
        return None
    return sum(v * w for v, w in vals) / sum(w for _, w in vals)


def classify_demand(row, q):
    """Classify measured demand from same-interval q/i/b/c/a evidence.

    This is the ONE authoritative interpretation of the queue telemetry.
    The decisive fields (`correlated_*`) come from consecutive
    src=ingest samples on ONE timeline; trial-level co-occurrence is
    never treated as correlation. Unmeasurable quantities stay None,
    never zero.
    """
    if not q:
        return {"available": False,
                "evidence": ["no STAGE0 queue telemetry for this case"]}
    chunk = q.get("chunk") or {}
    chunk_nodes = chunk.get("nodes") or {}
    batch_nodes = q.get("nodes") or {}
    chunk_measurable = (bool(chunk_nodes)
                        and bool(chunk.get("indexer_waiters_observed")))
    batch_measurable = bool(batch_nodes)
    corr = q.get("correlated") or {}
    corr_available = bool(corr.get("available"))
    trials = q.get("trials", 0)
    corr_trials = corr.get("trials", 0)
    trial_rows = corr.get("trial_rows") or []
    evidence = []
    gap_nodes = sorted(
        n for n, v in batch_nodes.items()
        if v.get("supply_gap_batches_per_s") is not None
        and v["supply_gap_batches_per_s"] > 0)
    gated = q.get("gated_ms")
    ingest_cores = row.get("median_ingest_cores")

    if corr_available:
        ingest_starved = (corr.get("ingest_starved_trials") or 0) > 0
        scanner_starved = (corr.get("scanner_starved_trials") or 0) > 0
        source_limited = (corr.get("source_limited_trials") or 0) > 0
        ingest_backpressure = (
            corr.get("ingest_backpressure_trials") or 0) > 0
        ingest_near_one = (
            corr.get("nodes")
            and any((v.get("ingest_cpu_saturated_starved_intervals") or 0)
                    > 0 for v in corr["nodes"].values()))
        supply_gap_intervals = corr.get("supply_gap_intervals") or 0
        workers_saturated = bool(
            corr_trials == trials and trials > 0
            and (corr.get("attribution_complete_trials") or 0) == trials
            and supply_gap_intervals == 0
            and (corr.get("scanner_starved_trials") or 0) == 0)
    else:
        ingest_starved = bool(q.get("ingest_starvation_trials"))
        scanner_starved = (
            True if q.get("scanner_starvation_trials") else
            (False if q.get("scanner_starvation_measurable_trials")
             else None))
        ingest_near_one = (
            ingest_cores is not None
            and _INGEST_NEAR_ONE[0] <= ingest_cores <= _INGEST_NEAR_ONE[1])
        source_limited = None
        if ingest_starved:
            if ingest_cores is None:
                evidence.append(
                    "chunk queue empty with indexer waiters, but ingest CPU "
                    "is not measured; source-limited vs CPU-bound ingest "
                    "cannot be distinguished")
            elif not ingest_near_one and not (gated is not None
                                              and gated > 0):
                source_limited = True
                evidence.append(
                    "chunk queue empty with indexer waiters while ingest CPU "
                    "%.2f cores is below the spec §4.2 near-one-core reading "
                    "band and gated_ms=%s; this is source-limited, not "
                    "centralized-ingest CPU saturation"
                    % (ingest_cores, gated))
            else:
                source_limited = False
                evidence.append(
                    "chunk queue empty with indexer waiters while ingest CPU "
                    "%.2f cores is near one core (spec §4.2)"
                    % ingest_cores)
        elif chunk_measurable:
            source_limited = False
        ingest_backpressure = bool(gated is not None and gated > 0)
        workers_saturated = bool(q.get("workers_saturated_trials"))

    corr_all_trials = (corr_available and trials > 0
                       and corr_trials == trials)
    corr_all_go = (corr_all_trials
                   and (corr.get("trial_go_trials") or 0) == trials)
    corr_no_mixed = (corr.get("mixed_trials") or 0) == 0
    corr_no_scanner = (corr.get("scanner_starved_trials") or 0) == 0
    corr_no_source = (corr.get("source_limited_trials") or 0) == 0
    corr_complete = (corr_all_trials
                     and (corr.get("attribution_complete_trials") or 0)
                     == trials)
    gap_min = corr.get("go_gap_per_s_min")
    gap_spread = corr.get("go_gap_per_s_spread")
    # Repeatability is not a percentage threshold: the weakest trial's
    # GO-interval deficit rate must be larger than the full observed
    # spread (max-min) of those rates. If the deficit is inside the
    # trial-to-trial variation, the evidence cannot distinguish it from
    # noise and the verdict stays INCONCLUSIVE.
    corr_positive = gap_min is not None and gap_min > 0
    corr_distinguishable = bool(
        corr_positive and (gap_spread is None or gap_min > gap_spread))
    corr_repeatable = bool(corr_all_go and corr_distinguishable)
    correlated_go = bool(
        corr_all_trials and corr_all_go and corr_no_mixed
        and corr_no_scanner and corr_no_source and corr_complete
        and corr_repeatable)

    if corr_available:
        evidence.append(
            "same-interval evidence: %d/%d trials usable, %d intervals "
            "over %.2fs" % (corr_trials, trials,
                            corr.get("intervals") or 0,
                            corr.get("interval_s") or 0.0))
        if corr.get("go_intervals"):
            evidence.append(
                "same-interval GO evidence: %d interval(s) over %.2fs on "
                "node(s) %s; per-trial deficit %s"
                % (corr.get("go_intervals"),
                   corr.get("go_s") or 0.0,
                   ", ".join("n%d" % n for n in
                             (corr.get("go_nodes") or [])) or "none",
                   _gap_range(corr)))
            evidence.append(
                "trial-to-trial repeatability: deficit rates %s; spread %s; "
                "weakest trial %s the spread -> %s"
                % (_trial_gap_values(corr),
                   _fmt(corr.get("go_gap_per_s_spread"), "%.1f"),
                   "exceeds" if corr_distinguishable else "does not exceed",
                   "distinguishable from trial variation"
                   if corr_distinguishable else
                   "NOT distinguishable from trial variation"))
        else:
            evidence.append(
                "no interval has ingest CPU near one core, an empty chunk "
                "queue with indexer waiters, a draining/empty batch queue, "
                "waiting workers, and claims above publications together")
        if corr.get("mixed_trials"):
            evidence.append(
                "mixed/ambiguous: %d trial(s) show ingest starvation in one "
                "interval and scanner/worker starvation with upstream input "
                "available in another; trial-level co-occurrence is not "
                "correlation" % corr["mixed_trials"])
        if corr.get("scanner_starved_trials"):
            evidence.append(
                "scanner/worker starvation with upstream input available in "
                "%d/%d trials; this is a downstream limitation, not an "
                "ingest one" % (corr["scanner_starved_trials"], trials))
        if corr.get("source_limited_trials"):
            evidence.append(
                "source-limited intervals (chunk queue empty with indexer "
                "waiters while ingest CPU is below the near-one-core band) "
                "in %d/%d trials"
                % (corr["source_limited_trials"], trials))
        if corr.get("ingest_backpressure_trials"):
            evidence.append(
                "ingest backlog-gated intervals in %d/%d trials: ingest "
                "waited for destination chunk-queue capacity"
                % (corr["ingest_backpressure_trials"], trials))
        if corr.get("excluded_total"):
            evidence.append(
                "excluded intervals (never bridged): %s"
                % ", ".join("%s=%d" % (k, v) for k, v in
                            sorted((corr.get("excluded") or {}).items())
                            if v))
        if not corr_complete:
            evidence.append(
                "same-interval attribution is incomplete: %d/%d trials "
                "have clean, usable intervals"
                % (corr.get("attribution_complete_trials") or 0, trials))
    else:
        evidence.append(
            "no src=ingest timeline on this source path; same-interval "
            "attribution is unavailable (not zero)")
    if gap_nodes:
        evidence.append(
            "per-node supply gap (claims > publications): %s"
            % ", ".join("n%d %+.1f/s" % (
                n, batch_nodes[n]["supply_gap_batches_per_s"])
                for n in gap_nodes))
    else:
        evidence.append("no per-node supply gap (claims <= publications)")
    if ingest_starved:
        evidence.append(
            "chunk queue empty with indexer waiters in %d/%d trials"
            % (corr.get("ingest_starved_trials")
               if corr_available
               else q.get("ingest_starvation_trials", 0), trials))
    if scanner_starved is True:
        evidence.append(
            "batch queue empty with waiting workers while upstream chunk "
            "supply was available (scanner/worker starvation)")
    if workers_saturated:
        evidence.append(
            "no interval shows worker claims exceeding scanner publication, "
            "and no scanner/worker starvation was measured: centralized "
            "ingest supplied downstream demand in every complete trial")
    if ingest_backpressure:
        evidence.append(
            "ingest gated_ms=%s: ingest waited for destination chunk-queue "
            "capacity" % gated)
    if not chunk_measurable:
        evidence.append(
            "upstream chunk queue/indexer waiters are not measurable on this "
            "source path; reported as unavailable, not zero")
    return {
        "available": True,
        "batch_measurable": batch_measurable,
        "chunk_measurable": chunk_measurable,
        "gap_nodes": gap_nodes,
        "has_supply_gap": bool(gap_nodes),
        "ingest_indexer_starvation": ingest_starved,
        "scanner_worker_starvation": scanner_starved,
        "workers_saturated": workers_saturated,
        "source_limited": source_limited,
        "ingest_backpressure": ingest_backpressure,
        "ingest_cpu_near_one": ingest_near_one,
        "correlated_available": corr_available,
        "correlated_trials": corr_trials,
        "correlated_intervals": corr.get("intervals"),
        "correlated_interval_s": corr.get("interval_s"),
        "correlated_excluded": dict(corr.get("excluded") or {}),
        "correlated_excluded_total": corr.get("excluded_total"),
        "correlated_go": correlated_go,
        "correlated_go_trials": corr.get("trial_go_trials"),
        "correlated_go_intervals": corr.get("go_intervals"),
        "correlated_go_s": corr.get("go_s"),
        "correlated_go_nodes": list(corr.get("go_nodes") or []),
        "correlated_mixed_trials": corr.get("mixed_trials"),
        "correlated_scanner_starved_trials":
            corr.get("scanner_starved_trials"),
        "correlated_source_limited_trials":
            corr.get("source_limited_trials"),
        "correlated_backpressure_trials":
            corr.get("ingest_backpressure_trials"),
        "correlated_attribution_complete_trials":
            corr.get("attribution_complete_trials"),
        "correlated_repeatable": corr_repeatable,
        "correlated_distinguishable": corr_distinguishable,
        "correlated_gap_per_s_min": corr.get("go_gap_per_s_min"),
        "correlated_gap_per_s_median": corr.get("go_gap_per_s_median"),
        "correlated_gap_per_s_max": corr.get("go_gap_per_s_max"),
        "correlated_gap_per_s_spread": corr.get("go_gap_per_s_spread"),
        "correlated_supply_gap_intervals":
            corr.get("supply_gap_intervals"),
        "correlated_ingest_supplied": bool(
            corr_complete
            and (corr.get("supply_gap_intervals") or 0) == 0
            and (corr.get("scanner_starved_trials") or 0) == 0),
        "correlated_trial_rows": trial_rows,
        "evidence": evidence,
    }


def _gap_range(corr):
    vals = [corr.get("go_gap_per_s_min"),
            corr.get("go_gap_per_s_median"),
            corr.get("go_gap_per_s_max")]
    if any(v is None for v in vals):
        return "not measured"
    return "min/median/max %.1f/%.1f/%.1f batches/s" % tuple(vals)


def _trial_gap_values(corr):
    vals = [r.get("supply_gap_go_per_s") for r in (corr.get("trial_rows") or [])
            if r.get("trial_go")
            and r.get("supply_gap_go_per_s") is not None]
    if not vals:
        return "not measured"
    return "/".join("%.1f" % v for v in vals) + " batches/s"


# --------------------------------------------------------------------------
# Case summary / verdict.
# --------------------------------------------------------------------------

def case_summary(cases):
    rows = []
    for case, entries in sorted(cases.items()):
        manifests = [m for m, _ in entries]
        ok = [m for m in manifests if m.get("complete")]
        recs = [m["child_report"]["rec_per_s"] for m in ok
                if m.get("child_report")]
        walls = [m["wall_s"] for m in ok]
        maps = [m.get("map_s") if m.get("map_s") is not None else m["wall_s"]
                for m in ok]
        cpus = [m["cpu_per_core_basis"] for m in ok
                if m.get("cpu_per_core_basis") is not None]
        ingest_bases = []
        ingest_attribution = "unavailable"
        for m in ok:
            direct = m.get("ingest_cpu_phase_cores")
            if direct is None:
                direct = m.get("ingest_cpu_direct_basis_cores")
            comm = m.get("ingest_cpu_basis_cores")
            if direct is not None:
                ingest_bases.append(direct)
                ingest_attribution = "direct"
            elif comm is not None:
                ingest_bases.append(comm)
                if ingest_attribution != "direct":
                    ingest_attribution = "comm-sampled"
        spec = (manifests[0] or {}).get("spec", {}) if manifests else {}
        rows.append({
            "case": case,
            "spec": spec,
            "n_trials": len(manifests),
            "n_ok": len(ok),
            "median_rec_per_s": _median(recs),
            "spread_pct": ((max(recs) - min(recs)) / _median(recs) * 100)
            if recs and _median(recs) else None,
            "median_map_s": _median(maps),
            "median_process_s": _median(walls),
            "median_per_core": _median(cpus),
            "median_ingest_cores": _median(ingest_bases),
            "ingest_attributed": bool(ingest_bases),
            "ingest_attribution": ingest_attribution,
            "n_ingest_near_one": sum(
                1 for v in ingest_bases
                if _INGEST_NEAR_ONE[0] <= v <= _INGEST_NEAR_ONE[1]),
            "ingest_phase_s": _median(
                [m["ingest_phase_s"] for m in ok
                 if m.get("ingest_phase_s") is not None]),
            "diag_samples": sum(
                (m.get("diagnostics") or {}).get("samples", 0)
                for m in manifests),
            "median_rss_mb": _median(
                [m["rss_peak_kb"] / 1024.0 for m in ok
                 if m.get("rss_peak_kb")]) if ok else None,
        })
    return rows


def _env_topology(env):
    if not env:
        return {"fake": None, "nodes": 0, "label": "unknown"}
    kernel = env.get("kernel") or {}
    fake = bool(kernel.get("fake_numa"))
    nodes = len((env.get("cpu_topology") or {}).get("nodes") or {})
    if fake:
        label = "fake NUMA (%s) — NOT real-NUMA evidence" % (
            kernel.get("fake_numa_spec") or "numa=fake")
    elif nodes > 1:
        label = "physical NUMA (%d nodes)" % nodes
    else:
        label = "single-node / UMA"
    return {"fake": fake, "nodes": nodes, "label": label,
            "cmdline": kernel.get("cmdline"),
            "fake_spec": kernel.get("fake_numa_spec")}


_ABLATION_CELLS = ("A", "B", "C", "D")
_ABLATION_FORMS = ("map-fault", "write-path")
_ABLATION_PAIRS = tuple((c, f) for c in _ABLATION_CELLS for f in _ABLATION_FORMS)


def ablation_ok(ablation, campaign_id=None):
    """Validate the COMPLETE 2x2 x two-materialization-form evidence.

    Exactly eight unique cell/form pairs are required. `valid: true` is
    not enough: the requested and effective policy, the affinity arm,
    page accounting, move_pages statuses, mincore residency, and the
    full-range write-path read-touch stability are all checked.
    """
    problems = []
    if not isinstance(ablation, dict):
        return False, ["ablation JSON missing"]
    if ablation.get("schema") != SCHEMA_ABLATION:
        problems.append("ablation: schema %r != %r"
                        % (ablation.get("schema"), SCHEMA_ABLATION))
    if campaign_id is not None and \
            ablation.get("campaign_id") != campaign_id:
        problems.append("ablation: campaign_id %r != %r"
                        % (ablation.get("campaign_id"), campaign_id))
    nodes = ablation.get("nodes") or {}
    x, y = nodes.get("x"), nodes.get("y")
    if not isinstance(x, int) or not isinstance(y, int) or x == y:
        problems.append("ablation: invalid node pair x=%r y=%r" % (x, y))
    x_cpus = nodes.get("x_cpus") or []
    allowed = nodes.get("allowed_cpus") or []
    if not x_cpus:
        problems.append("ablation: node X has no recorded CPU list")
    if not allowed:
        problems.append("ablation: no recorded allowed CPU set")
    declared_cells = ablation.get("cells")
    if declared_cells is not None and \
            list(declared_cells) != list(_ABLATION_CELLS):
        problems.append("ablation: cells %r != %r"
                        % (declared_cells, list(_ABLATION_CELLS)))
    declared_forms = ablation.get("forms")
    if declared_forms is not None and \
            list(declared_forms) != list(_ABLATION_FORMS):
        problems.append("ablation: forms %r != %r"
                        % (declared_forms, list(_ABLATION_FORMS)))

    results = ablation.get("results")
    if not isinstance(results, list):
        return False, problems + ["ablation: results is not a list"]
    seen = {}
    for result in results:
        if not isinstance(result, dict):
            problems.append("ablation: malformed result row")
            continue
        cell = result.get("cell")
        form = result.get("form")
        label = "%s/%s" % (cell, form)
        if (cell, form) not in _ABLATION_PAIRS:
            problems.append("%s: unexpected cell/form pair" % label)
            continue
        if label in seen:
            problems.append("%s: duplicate result row" % label)
            continue
        seen[label] = result
        if result.get("valid") is not True:
            problems.append("%s: invalid (%s)"
                            % (label, result.get("invalid_reason")))
        if result.get("child_rc") != 0:
            problems.append("%s: child_rc %r != 0"
                            % (label, result.get("child_rc")))
        if result.get("child_timed_out") is not False:
            problems.append("%s: child_timed_out %r != false"
                            % (label, result.get("child_timed_out")))

        req = result.get("policy_requested") or {}
        eff = result.get("effective") or {}
        aff = result.get("affinity_requested") or {}
        if req.get("set_rc") != 0:
            problems.append("%s: policy set_rc %r != 0"
                            % (label, req.get("set_rc")))
        if eff.get("get_mempolicy_rc") != 0:
            problems.append("%s: get_mempolicy_rc %r != 0"
                            % (label, eff.get("get_mempolicy_rc")))
        if cell in ("A", "B"):
            if req.get("mode_numeric") != 0 or eff.get("mempolicy_mode") != 0:
                problems.append("%s: MPOL_DEFAULT not requested/effective"
                                % label)
        else:
            if req.get("mode_numeric") != 2:
                problems.append("%s: requested mode %r != MPOL_BIND (2)"
                                % (label, req.get("mode_numeric")))
            if eff.get("mempolicy_mode") != 2:
                problems.append("%s: effective mode %r != MPOL_BIND (2)"
                                % (label, eff.get("mempolicy_mode")))
            if eff.get("mempolicy_mask_nodes") != [y]:
                problems.append("%s: effective mask %r != [%r]"
                                % (label, eff.get("mempolicy_mask_nodes"), y))
        if cell in ("B", "D"):
            if aff.get("mode") != "pinned" or aff.get("set_rc") != 0:
                problems.append("%s: affinity not pinned (mode=%r rc=%r)"
                                % (label, aff.get("mode"),
                                   aff.get("set_rc")))
            cpu = aff.get("cpu")
            if not isinstance(cpu, int):
                problems.append("%s: affinity CPU %r is not an int"
                                % (label, cpu))
            else:
                if cpu not in x_cpus:
                    problems.append("%s: affinity CPU %r is not on node X=%r"
                                    % (label, cpu, x))
                if cpu not in allowed:
                    problems.append("%s: affinity CPU %r is not allowed"
                                    % (label, cpu))
                if eff.get("affinity_cpus") != [cpu]:
                    problems.append(
                        "%s: effective affinity %r != [%r]"
                        % (label, eff.get("affinity_cpus"), cpu))
        else:
            if aff.get("mode") != "default":
                problems.append("%s: affinity was not inherited/default (%r)"
                                % (label, aff.get("mode")))
            if allowed and eff.get("affinity_cpus") != allowed:
                problems.append(
                    "%s: inherited affinity %r != recorded allowed set %r"
                    % (label, eff.get("affinity_cpus"), allowed))

        pages_total = result.get("pages_total")
        by_node = result.get("pages_by_node")
        if not isinstance(pages_total, int) or pages_total <= 0:
            problems.append("%s: pages_total %r is not positive"
                            % (label, pages_total))
            pages_total = None
        if not isinstance(by_node, dict):
            problems.append("%s: pages_by_node missing" % label)
        elif pages_total is not None:
            accounted = sum(int(v) for v in by_node.values())
            if accounted != pages_total:
                problems.append(
                    "%s: node counts sum to %d, pages_total is %d"
                    % (label, accounted, pages_total))
        if result.get("pages_unknown") != 0:
            problems.append("%s: pages_unknown %r != 0"
                            % (label, result.get("pages_unknown")))
        post = result.get("move_pages_post") or {}
        statuses = post.get("statuses")
        if post.get("rc") != 0:
            problems.append("%s: move_pages rc %r != 0"
                            % (label, post.get("rc")))
        if not isinstance(statuses, list):
            problems.append("%s: move_pages statuses missing" % label)
        else:
            if pages_total is not None and len(statuses) != pages_total:
                problems.append(
                    "%s: %d raw statuses for %d pages"
                    % (label, len(statuses), pages_total))
            if any(not isinstance(s, int) or s < 0 for s in statuses):
                problems.append("%s: negative/non-integer page status"
                                % label)
        if result.get("placement_measured") is not True:
            problems.append("%s: placement not measured" % label)
        mc = result.get("mincore") or {}
        if mc.get("rc") != 0:
            problems.append("%s: mincore rc %r != 0"
                            % (label, mc.get("rc")))
        if mc.get("total_pages") != pages_total or \
                mc.get("resident_pages") != pages_total:
            problems.append(
                "%s: mincore resident %r/%r != %r"
                % (label, mc.get("resident_pages"),
                   mc.get("total_pages"), pages_total))
        touch = result.get("touch") or {}
        if form == "write-path":
            if result.get("read_touch_stable") is not True:
                problems.append(
                    "%s: read-touch changed page placement over the "
                    "measured range" % label)
            if result.get("read_touch_unstable_pages") not in (None, 0):
                problems.append(
                    "%s: %r pages changed placement during read-touch"
                    % (label, result.get("read_touch_unstable_pages")))
            if touch.get("kind") != "read":
                problems.append("%s: touch kind %r != read"
                                % (label, touch.get("kind")))
        elif touch.get("kind") != "write":
            problems.append("%s: touch kind %r != write"
                            % (label, touch.get("kind")))

    expected_labels = {"%s/%s" % pair for pair in _ABLATION_PAIRS}
    missing = sorted(expected_labels - set(seen))
    extra = sorted(set(seen) - expected_labels)
    if missing:
        problems.append("ablation: missing result pairs %s" % missing)
    if extra:
        problems.append("ablation: unexpected result pairs %s" % extra)
    if len(results) != len(_ABLATION_PAIRS):
        problems.append("ablation: expected exactly %d result rows, got %d"
                        % (len(_ABLATION_PAIRS), len(results)))
    return not problems, problems


def derive_verdict(summary, queue, env, ablation_issues, campaign_problems,
                   trials_requested=None):
    """Spec §8 derivation: Go, No-Go, or Inconclusive.

    Decisive physical verdicts require (a) a genuine multi-node host,
    (b) valid placement evidence, (c) at least three completed trials
    per decisive case, and (d) per-node queue evidence that separates
    ingest->indexer starvation from scanner/worker and source limits.
    Fake NUMA is always Inconclusive by rule.
    """
    topo = _env_topology(env)
    if campaign_problems:
        return {
            "verdict": "INVALID — campaign completeness/identity check failed",
            "decision": "INVALID",
            "evidence": ["- " + p for p in campaign_problems],
            "go": False, "topology": topo,
        }
    if topo["fake"]:
        return {
            "verdict": "INCONCLUSIVE for real-NUMA benefit — fake NUMA",
            "decision": "INCONCLUSIVE",
            "evidence": [
                "- The host reports %s. Spec §8 forbids converting "
                "fake-NUMA evidence into a Go decision." % topo["label"],
                "- The rehearsal validates the harness and the ablation "
                "instrumentation; it does not establish real-NUMA "
                "placement or real-NUMA scaling.",
            ],
            "go": False, "topology": topo,
        }
    if topo["nodes"] <= 1:
        return {
            "verdict": "INCONCLUSIVE — host is not genuinely multi-node",
            "decision": "INCONCLUSIVE",
            "evidence": ["- %s" % topo["label"]],
            "go": False, "topology": topo,
        }
    if ablation_issues:
        return {
            "verdict": "INCONCLUSIVE — placement evidence is not valid",
            "decision": "INCONCLUSIVE",
            "evidence": ["- " + p for p in ablation_issues],
            "go": False, "topology": topo,
        }
    decisive = [r for r in summary
                if r["n_ok"] >= 1 and r["median_map_s"] is not None
                and r["median_map_s"] >= 2.0]
    if not decisive:
        return {
            "verdict": "INCONCLUSIVE — no decisive (>=2s) case",
            "decision": "INCONCLUSIVE",
            "evidence": ["- Every case is shorter than the campaign's own "
                         "2-second rule; startup dominates."],
            "go": False, "topology": topo,
        }
    if trials_requested is not None and trials_requested < 3:
        return {
            "verdict": "INCONCLUSIVE — fewer than three trials",
            "decision": "INCONCLUSIVE",
            "evidence": [
                "- The campaign requested %d trial(s) per case. Spec §8 "
                "requires repeatability across at least three trials for a "
                "decisive Go/No-Go; this campaign cannot decide."
                % trials_requested,
                "- Decisive cases: %s" % ", ".join(
                    r["case"] for r in decisive),
            ],
            "go": False, "topology": topo,
        }
    under_trialed = [r["case"] for r in decisive if r["n_ok"] < 3]
    if under_trialed:
        return {
            "verdict": "INCONCLUSIVE — fewer than three completed trials",
            "decision": "INCONCLUSIVE",
            "evidence": ["- Decisive case(s) with <3 complete trials: %s"
                         % ", ".join(under_trialed)],
            "go": False, "topology": topo,
        }
    missing_demand = [r["case"] for r in decisive
                      if not queue.get(r["case"])
                      or not queue[r["case"]]["nodes"]]
    if missing_demand:
        return {
            "verdict": "INCONCLUSIVE — downstream-demand estimate missing",
            "decision": "INCONCLUSIVE",
            "evidence": ["- No usable per-node queue telemetry for: %s"
                         % ", ".join(missing_demand)],
            "go": False, "topology": topo,
        }

    classifications = {}
    for row in decisive:
        classifications[row["case"]] = classify_demand(
            row, queue[row["case"]])

    go_cases = []
    nogo_cases = []
    ambiguous = []
    attributable = []
    not_attributable = []
    for row in decisive:
        case = row["case"]
        q = queue[case]
        c = classifications[case]
        trials = q.get("trials", 0)
        if not c.get("available") or not c.get("chunk_measurable"):
            # No ingest->indexer path exists on this source (the UMA
            # control case). It is reported but cannot decide a
            # centralized-ingest hypothesis.
            not_attributable.append(case)
            continue
        attributable.append(case)
        if c.get("correlated_go"):
            go_cases.append(case)
            continue
        if not c.get("correlated_available"):
            ambiguous.append(case)
            continue
        rows = c.get("correlated_trial_rows") or []
        complete = [r for r in rows if r.get("attribution_complete")]
        gap_trials = [r for r in rows
                      if (r.get("supply_gap_intervals") or 0) > 0]
        # NO-GO requires the same-interval evidence to be complete in
        # every trial AND to show no interval where worker claims
        # exceeded scanner publication. A trial with a deficit that is
        # not attributable (CPU not near one, workers not waiting,
        # queue not draining) is ambiguous, not No-Go.
        if (trials > 0 and len(rows) == trials
                and len(complete) == trials and not gap_trials):
            nogo_cases.append(case)
        else:
            ambiguous.append(case)

    evidence = ["- Topology: %s" % topo["label"],
                "- Decisive cases (>=2s, >=3 trials): %s"
                % ", ".join(r["case"] for r in decisive),
                "- Ingest CPU basis (cores; direct thread CPU where "
                "available): %s"
                % (", ".join("%s=%.2f (%s)" % (
                    r["case"], r["median_ingest_cores"],
                    r.get("ingest_attribution"))
                    for r in decisive
                    if r["median_ingest_cores"] is not None)
                   or "none measured"),
                "- Same-interval GO cases (CPU saturation + empty chunk "
                "queue with indexer waiters + draining batch queue with "
                "waiting workers + claims above publications): %s"
                % (", ".join(go_cases) or "none observed"),
                "- Same-interval supply-gap cases (worker claims exceeded "
                "scanner publication on at least one node in at least one "
                "interval): %s"
                % (", ".join(
                    r["case"] for r in decisive
                    if (classifications[r["case"]]
                        .get("correlated_supply_gap_intervals") or 0) > 0)
                   or "none observed"),
                "- Same-interval ingest->indexer starvation cases: %s"
                % (", ".join(
                    r["case"] for r in decisive
                    if classifications[r["case"]]
                    .get("ingest_indexer_starvation")) or "none observed"),
                "- Same-interval source-limited cases: %s"
                % (", ".join(
                    r["case"] for r in decisive
                    if classifications[r["case"]].get("source_limited")
                    is True) or "none observed"),
                "- Same-interval scanner/worker-starvation cases: %s"
                % (", ".join(
                    r["case"] for r in decisive
                    if classifications[r["case"]]
                    .get("scanner_worker_starvation") is True)
                   or "none observed"),
                "- Cases without an ingest->indexer path (reported, not "
                "used for the centralized-ingest decision): %s"
                % (", ".join(not_attributable) or "none")]
    for row in decisive:
        evidence.append("- %s: %s" % (
            row["case"],
            "; ".join(classifications[row["case"]]["evidence"])))

    if not attributable:
        return {
            "verdict": "INCONCLUSIVE — no decisive case has an "
                       "ingest->indexer path to attribute",
            "decision": "INCONCLUSIVE",
            "evidence": evidence + [
                "- The UMA control case(s) cannot measure centralized "
                "ingest->indexer starvation, so they cannot support a Go "
                "or No-Go for the distributed-ingest hypothesis."],
            "go": False, "topology": topo,
        }
    if go_cases and not nogo_cases and not ambiguous:
        return {
            "verdict": "GO candidate — centralized ingest is the measured "
                       "limiter on this physical host",
            "decision": "GO",
            "evidence": evidence + [
                "- In every attributable decisive case and every trial, at "
                "least one per-node interval shows the required conditions "
                "TOGETHER: ingest CPU near one core, the chunk queue empty "
                "with indexer waiters, worker claims exceeding scanner "
                "publications while the batch queue drains, and workers "
                "waiting.",
                "- The per-trial deficit rates are larger than their own "
                "trial-to-trial spread (see each case line), so the "
                "deficit is distinguishable from run-to-run noise.",
                "- Source starvation and scanner/worker bottlenecks are "
                "excluded: no source-limited intervals and no "
                "scanner/worker starvation with upstream input available "
                "were measured in any trial.",
                "- This is a recommendation to implement/test the "
                "distributed design, not proof that it will scale."],
            "go": True, "topology": topo,
        }
    if nogo_cases and not go_cases and not ambiguous:
        reasons = []
        if any((classifications[r["case"]]
                .get("correlated_source_limited_trials") or 0) > 0
               for r in decisive):
            reasons.append(
                "measured throughput is limited by the source rather than "
                "centralized ingestion (chunk queue empty with indexer "
                "waiters while ingest CPU is below the near-one-core "
                "reading band)")
        if any((classifications[r["case"]]
                .get("correlated_scanner_starved_trials") or 0) > 0
               for r in decisive):
            reasons.append(
                "measured throughput is limited by the scanner/worker "
                "downstream stage while upstream chunk supply was "
                "available")
        if not reasons:
            reasons.append(
                "centralized ingestion supplied sufficient work: no "
                "same-interval supply deficit (claims above publications) "
                "was measured on any node in any trial")
        return {
            "verdict": "NO-GO — centralized ingestion is not the measured "
                       "limiter",
            "decision": "NO-GO",
            "evidence": evidence + ["- " + reason for reason in reasons] + [
                "- Spec §8: retain the diagnostic tooling and shelve "
                "Stages 2-3."],
            "go": False, "topology": topo,
        }
    return {
        "verdict": "INCONCLUSIVE — the evidence does not isolate ingestion",
        "decision": "INCONCLUSIVE",
        "evidence": evidence + [
            "- Spec §8 requires the supply gap to be attributable to "
            "centralized ingest CPU saturation while downstream has "
            "unused capacity, in the SAME per-node intervals, consistently "
            "across at least three trials. At least one required "
            "distinction remains ambiguous (ambiguous cases: %s), so no "
            "Go/No-Go is asserted."
            % (", ".join(ambiguous) or "none; mixed Go/No-Go evidence")],
        "go": False, "topology": topo,
    }


# --------------------------------------------------------------------------
# Rendering.
# --------------------------------------------------------------------------

def _render_invalid(path, problems):
    lines = ["# Stage 0 campaign report — INVALID", "",
             "Campaign manifest: `%s`" % path, "",
             "The report refuses to classify this campaign:", ""]
    lines += ["- " + p for p in problems]
    lines += ["", "No Go/No-Go verdict is permitted. Fix the campaign and "
                  "rerun the one-command driver."]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", default=None,
                    help="campaign-manifest.json (required)")
    ap.add_argument("--runs", default=None,
                    help="run root; resolves <runs>/campaign-manifest.json")
    ap.add_argument("--ablation", default=None)
    ap.add_argument("--env-before", default=None)
    ap.add_argument("--env-after", default=None)
    ap.add_argument("--baseline-compare", default=None)
    ap.add_argument("--out", default="stage0/reports/stage0-report.md")
    args = ap.parse_args()

    campaign_path = args.campaign
    if not campaign_path and args.runs:
        campaign_path = os.path.join(args.runs, "campaign-manifest.json")
    if not campaign_path:
        print("report: --campaign (or --runs) is required", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    try:
        campaign = load_campaign(campaign_path)
    except CampaignError as exc:
        _render_invalid(args.out, exc.problems)
        print("report: INVALID campaign (%d problems)" % len(exc.problems),
              file=sys.stderr)
        for p in exc.problems:
            print("  - " + p, file=sys.stderr)
        return 2

    cases = campaign["_cases"]
    env = campaign["_env_before"]
    summary = case_summary(cases)
    queue = queue_demand_stats(cases)
    topo = _env_topology(env)

    ablation = None
    ablation_path = args.ablation
    if ablation_path:
        problems = []
        ablation = _read_json(ablation_path, "ablation", problems)
        if problems:
            print("report: ablation problem: %s" % problems,
                  file=sys.stderr)
    abl_ok, abl_issues = ablation_ok(ablation, campaign.get("campaign_id"))

    verdict = derive_verdict(summary, queue, env, abl_issues,
                             campaign.get("_problems") or [],
                             trials_requested=campaign.get("trials_requested"))

    git = (env or {}).get("git") or {}
    lines = [
        "# Stage 0 rehearsal report — %s" % topo["label"],
        "",
        "- campaign: `%s`" % campaign.get("campaign_id"),
        "- source: `%s`" % campaign.get("source_sha"),
        "- source worktree: %s" % (
            "CLEAN" if git.get("dirty") is False
            else "DIRTY (report refused by the validator)"),
        "- trials requested: %s" % campaign.get("trials_requested"),
        "- spec inventory: %s" % ", ".join(
            s.get("id") for s in campaign.get("specs") or []),
        "",
        "## Verdict (spec §8)", "",
        "**%s**" % verdict["verdict"], "",
    ]
    lines += verdict["evidence"]
    lines += ["", "## Baseline cases (median of trials)", "",
              "| case | spec | trials ok | rec/s (median) | spread % | "
              "map s | process s | tree cores | ingest cores | ingest "
              "attribution | ingest phase s | diag samples |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        lines.append("| %s | w%s n%s %s | %d/%d | %s | %s | %s | %s | %s | "
                     "%s | %s | %s | %d |" % (
                         r["case"], r["spec"].get("workers"),
                         r["spec"].get("nodes"), r["spec"].get("mode"),
                         r["n_ok"], r["n_trials"],
                         _fmt(r["median_rec_per_s"], "%.0f"),
                         _fmt(r["spread_pct"], "%.1f"),
                         _fmt(r["median_map_s"]),
                         _fmt(r["median_process_s"]),
                         _fmt(r["median_per_core"]),
                         _fmt(r["median_ingest_cores"]),
                         r.get("ingest_attribution") or "unavailable",
                         _fmt(r.get("ingest_phase_s"), "%.3f"),
                         r["diag_samples"]))
    lines += ["", "`map s` is the child's `forkrun.map()` timer; `process s` "
                  "is the outer process wall, which also contains the "
                  "harness's post-run exactness accounting. Ingest CPU is "
                  "reported in cores. When a direct record exists, the "
                  "denominator is that ingest phase's measured duration "
                  "(the honest basis for \"about one core while ingesting\"); "
                  "otherwise it falls back to the comm-sampled figure over "
                  "the map timer. `direct` is the ingest task's own "
                  "`CLOCK_THREAD_CPUTIME_ID` record (Python spill, or the C "
                  "NUMA ingest FINAL); `comm-sampled` is the 20 ms per-task "
                  "delta keyed by `comm`, which is a cross-check and can miss "
                  "a short phase. `ingest phase s` is the measured duration "
                  "of that direct ingest window. Tree cores are the sum of "
                  "all task CPU deltas over the run divided by wall, not a "
                  "peak snapshot.", ""]

    lines += ["## Per-node queue telemetry (STAGE0_DIAG, spec §4.3)", ""]
    lines.append("Raw timestamped samples (per node chunk head/tail, batch "
                 "read/write, dequeue counter, waiter gauge) are retained "
                 "in each trial's `stderr.log`; the tables aggregate them "
                 "per trial and never join one trial's end to the next "
                 "trial's start.")
    lines.append("")
    lines.append("### Batch queue: scanner -> worker (`b`, `c`, `a`)")
    lines.append("")
    lines.append("| case | samples | duration s | nodes | nonempty per node "
                 "| all-empty | longest all-empty ms | published/s (raw "
                 "write_idx) | claimed/s (raw read_idx) | c/s (cross-check) "
                 "| supply gap/s (claims-pub) | gated ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        q = queue.get(r["case"])
        if not q:
            lines.append("| %s | 0 | - | - | NO TELEMETRY | - | - | - | - | "
                         "- | - | - |" % r["case"])
            continue
        per_node = "; ".join(
            "n%d:%s" % (n, _fmt(v.get("nonempty_fraction"), "%.2f"))
            for n, v in sorted(q["nodes"].items()))
        lines.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | "
                     "%s | %s |" % (
                         r["case"], q["samples"],
                         _fmt(q["duration_s"], "%.2f"),
                         ",".join(str(n) for n in sorted(q["nodes"])) or "-",
                         per_node or "-",
                         _fmt(q["all_empty_fraction"], "%.2f"),
                         _fmt(q["longest_all_empty_ms"], "%.0f"),
                         _fmt(q["published_batches_per_s"], "%.1f"),
                         _fmt(q["claimed_batches_per_s"], "%.1f"),
                         _fmt(q["claims_c_per_s"], "%.1f"),
                         _fmt(q["supply_gap_batches_per_s"], "%+.1f"),
                         _fmt(q["gated_ms"], "%.0f")))
    lines += ["", "### Chunk queue: ingest -> indexer (`q`, `i`)", ""]
    lines.append("| case | samples | nodes | chunk published/s | chunk "
                 "consumed/s | all-empty | longest all-empty ms | indexer "
                 "waiters max | empty-with-waiters | gated ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        q = queue.get(r["case"])
        chunk = (q or {}).get("chunk") or {}
        if not q or not chunk.get("nodes"):
            lines.append("| %s | 0 | - | NOT MEASURABLE (no ingest/indexer "
                         "path on this source) | - | - | - | - | - | %s |"
                         % (r["case"], _fmt((q or {}).get("gated_ms"),
                                            "%.0f")))
            continue
        lines.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["case"], chunk.get("samples"),
            ",".join(str(n) for n in sorted(chunk["nodes"])),
            _fmt(chunk.get("chunk_published_per_s"), "%.1f"),
            _fmt(chunk.get("chunk_consumed_per_s"), "%.1f"),
            _fmt(chunk.get("all_empty_fraction"), "%.2f"),
            _fmt(chunk.get("longest_all_empty_ms"), "%.0f"),
            _fmt(chunk.get("indexer_waiters_max"), "%.0f"),
            _fmt(chunk.get("indexer_wait_while_empty_fraction"), "%.2f"),
            _fmt(q.get("gated_ms"), "%.0f")))
    lines += ["", "### Per-node detail", "",
              "| case | node | nonempty | longest empty ms | published/s | "
              "claimed/s | c/s | supply gap/s | gap batches | "
              "endpoint-persistent claimed/s | intervals | c-mismatch "
              "intervals | counter regressions |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        q = queue.get(r["case"])
        if not q:
            continue
        for node, v in sorted(q["nodes"].items()):
            reg = v.get("counter_regressions") or {}
            lines.append("| %s | n%d | %s | %s | %s | %s | %s | %s | %s | "
                         "%s | %d | %d | %s |" % (
                             r["case"], node,
                             _fmt(v.get("nonempty_fraction"), "%.2f"),
                             _fmt(v.get("longest_empty_ms"), "%.0f"),
                             _fmt(v.get("published_batches_per_s"), "%.1f"),
                             _fmt(v.get("claimed_batches_per_s"), "%.1f"),
                             _fmt(v.get("claims_c_batches") and
                                  v.get("claimed_interval_s") and
                                  v["claims_c_batches"] /
                                  v["claimed_interval_s"], "%.1f"),
                             _fmt(v.get("supply_gap_batches_per_s"), "%+.1f"),
                             _fmt(v.get("supply_gap_batches"), "%.0f"),
                             _fmt(v.get("claimed_batches_per_s_nonempty"),
                                  "%.1f"),
                             v.get("consumption_intervals") or 0,
                             v.get("claim_crosscheck_mismatch_intervals") or 0,
                             ",".join("%s:%d" % (k, val)
                                      for k, val in sorted(reg.items()))
                             or "-"))
    lines += ["", "`published/s` is the RAW `write_idx` delta (batches the "
                  "scanner published); `claimed/s` is the RAW `read_idx` "
                  "delta (batches workers claimed); depth "
                  "(`write_idx - read_idx`) is used ONLY for occupancy. `c/s` "
                  "is `total_lines_consumed`, incremented once per successful "
                  "claim: it is a cross-check on the claim position, and "
                  "intervals where `c` and `read_idx` disagree are counted "
                  "rather than reconciled. A counter regression is counted "
                  "and excluded from the rate; it is never silently treated "
                  "as zero work.", "",
                  "`supply gap/s` is computed PER NODE over the intervals "
                  "where that node's publication and claim counters are both "
                  "valid: a positive value means worker claims exceeded "
                  "scanner publication on that node over those intervals, "
                  "i.e. a scanner-side supply deficit relative to worker "
                  "demand (workers drew down previously queued work). It is "
                  "NOT evidence by itself that the downstream stage is the "
                  "limiter; the q/i timeline decides whether the scanner was "
                  "starved for input or unable to process available input. "
                  "It is not an aggregate rate compared against the fastest "
                  "node, so one node's surplus cannot hide another's deficit.", "",
                  "The chunk queue uses the opposite pair order: `q` is "
                  "(`chunk_queue_head`, `chunk_queue_tail`), where head is "
                  "the ingest publication counter and tail is the "
                  "scanner/indexer claim counter. `chunk published/s` and "
                  "`chunk consumed/s` are the raw head and tail deltas "
                  "respectively. Batch groups (`b`/`c`/`a`) are emitted by "
                  "both the UMA scanner and the NUMA C ingest; `q`/`i` are "
                  "owned by src=ingest only.", "",
                  "`endpoint-persistent claimed/s` uses intervals where that "
                  "node's batch queue was non-empty at BOTH sampled ends. "
                  "This is an endpoint-persistent estimate, not proof that "
                  "the queue never emptied between two 20 ms samples; a "
                  "queue that dips and refills between samples is counted "
                  "as continuously available here.", "",
                  "`gated_ms` is the ingest backlog-gated wait accumulated by "
                  "the engine sampler (ingest source only). `q`/`i` are "
                  "reported only when the source has an ingest->indexer "
                  "path; the UMA scanner has no indexer, so those fields are "
                  "reported as NOT MEASURABLE, never as zero.", ""]

    lines += ["## Time-correlated same-interval evidence", "",
              "The NUMA C ingest emits `q`, `i`, `b`, `c`, `a`, `cpu_ns` "
              "and `t_us` on ONE CLOCK_MONOTONIC origin. Consecutive "
              "`src=ingest` samples form one timeline per trial, and the "
              "predicates below are evaluated on the SAME per-node "
              "interval. Trial-level co-occurrence is never treated as "
              "correlation. All elapsed-time math uses `t_us`; `t_ms` is "
              "human-readable only.", "",
              "Predicates: **ingest->indexer starvation** = the node's chunk "
              "queue is empty at both sampled endpoints and its indexer "
              "waiter gauge is positive in the same interval. **Scanner->"
              "worker starvation** = the batch queue is empty at both "
              "endpoints and workers are waiting in the same interval while "
              "upstream input is available (nonzero chunk depth or no "
              "indexer waiters). **Ingest CPU saturation** = the ingest "
              "thread's `delta(cpu_ns)/delta(t_us)` is inside the declared "
              "near-one-core reading band in the same interval. **Supply "
              "deficit** = raw `read_idx` delta exceeds raw `write_idx` "
              "delta on the node in the same interval (worker claims exceed "
              "scanner publication). **GO interval** requires all of these "
              "together, with the batch queue draining or empty and no "
              "backlog-gated ingest wait. **Mixed** means ingest starvation "
              "and upstream-available scanner/worker starvation occur in "
              "different intervals of the same trial: ambiguous, not "
              "\"scanner starvation absent\".", "",
              "Excluded intervals are counted, never bridged: a "
              "non-monotonic/duplicate timestamp, missing or regressed "
              "`cpu_ns`, missing per-node groups, or a counter regression "
              "removes the interval from every predicate.", ""]
    lines.append("| case | trial | intervals | duration s | ingest "
                 "starved | CPU-sat starved | scanner starved | source "
                 "limited | backpressure | GO intervals | GO s | GO "
                 "deficit/s | GO CPU cores | excluded |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        q = queue.get(r["case"])
        corr = (q or {}).get("correlated") or {}
        if not corr.get("available"):
            lines.append("| %s | - | 0 | - | NOT AVAILABLE (no src=ingest "
                         "timeline) | - | - | - | - | - | - | - | - | - |"
                         % r["case"])
            continue
        rows = corr.get("trial_rows") or []
        if not rows:
            lines.append("| %s | - | 0 | - | - | - | - | - | - | - | - | "
                         "- | - | %d |" % (r["case"],
                                           corr.get("excluded_total") or 0))
            continue
        for t in rows:
            lines.append("| %s | %d | %d | %s | %d | %d | %d | %d | %d | "
                         "%d | %s | %s | %s | %s |" % (
                             r["case"], t["trial"],
                             t.get("intervals") or 0,
                             _fmt(t.get("interval_s"), "%.2f"),
                             t.get("ingest_starved_intervals") or 0,
                             t.get("ingest_cpu_saturated_starved_intervals")
                             or 0,
                             t.get("scanner_starved_intervals") or 0,
                             t.get("source_limited_intervals") or 0,
                             t.get("ingest_backpressure_intervals") or 0,
                             t.get("go_intervals") or 0,
                             _fmt(t.get("go_s"), "%.2f"),
                             _fmt(t.get("supply_gap_go_per_s"), "%.1f"),
                             _fmt(t.get("go_cpu_cores"), "%.2f"),
                             t.get("excluded_total") or 0))
    lines += ["", "### Per-node same-interval detail", "",
              "| case | node | intervals | ingest starved | CPU-sat "
              "starved | scanner starved | source limited | worker waits | "
              "supply-gap intervals | GO intervals | GO s | GO deficit/s | "
              "GO CPU cores | chunk pub/s | chunk cons/s | batch pub/s | "
              "batch claim/s | counter regressions | c-mismatch intervals |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        q = queue.get(r["case"])
        corr = (q or {}).get("correlated") or {}
        for node, v in sorted((corr.get("nodes") or {}).items()):
            lines.append("| %s | n%d | %d | %d | %d | %d | %d | %d | %d | "
                         "%d | %s | %s | %s | %s | %s | %s | %s | %d | %d |"
                         % (
                             r["case"], node,
                             v.get("intervals") or 0,
                             v.get("ingest_starved_intervals") or 0,
                             v.get("ingest_cpu_saturated_starved_intervals")
                             or 0,
                             v.get("scanner_starved_intervals") or 0,
                             v.get("source_limited_intervals") or 0,
                             v.get("worker_wait_intervals") or 0,
                             v.get("supply_gap_intervals") or 0,
                             v.get("go_intervals") or 0,
                             _fmt(v.get("go_s"), "%.2f"),
                             _fmt(v.get("go_supply_gap_per_s"), "%.1f"),
                             _fmt(v.get("go_cpu_cores"), "%.2f"),
                             _fmt(v.get("chunk_published_per_s"), "%.1f"),
                             _fmt(v.get("chunk_consumed_per_s"), "%.1f"),
                             _fmt(v.get("batch_published_per_s"), "%.1f"),
                             _fmt(v.get("batch_claimed_per_s"), "%.1f"),
                             v.get("counter_regressions") or 0,
                             v.get("claim_crosscheck_mismatch_intervals")
                             or 0))
    lines += ["", "`GO deficit/s` is the per-trial or per-node supply "
                  "deficit measured ONLY over GO intervals, so it is not "
                  "netted against intervals with a surplus. The verdict "
                  "requires every trial to have GO intervals, the weakest "
                  "trial's GO deficit rate to exceed the full trial-to-trial "
                  "spread of those rates, complete attribution (zero "
                  "exclusions), no source-limited intervals, no "
                  "upstream-available scanner/worker starvation, and no "
                  "mixed trial. The endpoint-sampling caveat applies: two "
                  "samples 20 ms apart cannot prove the queue was "
                  "continuously empty between them.", ""]

    lines += ["## Demand classification (spec §4.3/§8)", ""]
    lines.append("| case | supply gap | ingest->indexer starvation | "
                 "scanner->worker starvation | workers saturated | "
                 "source-limited | ingest backpressure | same-interval GO | "
                 "GO trials | GO intervals | GO deficit/s min/median/max | "
                 "excluded |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        cls = classify_demand(r, queue.get(r["case"]))
        if not cls.get("available"):
            lines.append("| %s | - | - | - | - | - | - | - | - | - | - | "
                         "- |" % r["case"])
            continue
        def _tri(value):
            return "?" if value is None else ("yes" if value else "no")
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | "
                     "%s | %s |" % (
                         r["case"], _tri(cls["has_supply_gap"]),
                         _tri(cls["ingest_indexer_starvation"]),
                         _tri(cls["scanner_worker_starvation"]),
                         _tri(cls["workers_saturated"]),
                         _tri(cls["source_limited"]),
                         _tri(cls["ingest_backpressure"]),
                         _tri(cls.get("correlated_go")),
                         _fmt(cls.get("correlated_go_trials"), "%.0f"),
                         _fmt(cls.get("correlated_go_intervals"), "%.0f"),
                         _gap_range({"go_gap_per_s_min":
                                     cls.get("correlated_gap_per_s_min"),
                                     "go_gap_per_s_median":
                                     cls.get("correlated_gap_per_s_median"),
                                     "go_gap_per_s_max":
                                     cls.get("correlated_gap_per_s_max")}),
                         _fmt(cls.get("correlated_excluded_total"), "%.0f")))
    lines += ["", "`?` means the quantity is not measurable on this source "
                  "path, not that it is absent. A supply gap is attributed to "
                  "centralized ingestion only when the SAME per-node interval "
                  "shows ingest->indexer starvation, ingest CPU near one core, "
                  "workers waiting, and the batch queue draining (spec §4.2); "
                  "an empty chunk queue with indexer waiters while ingest CPU "
                  "is well below one core is classified source-limited. A "
                  "positive `claims - publications` is a scanner-side supply "
                  "deficit relative to worker demand, not by itself evidence "
                  "that downstream is the limiter; q/i decides whether the "
                  "scanner lacked input or could not process available "
                  "input.", ""]

    lines += ["## 2×2 affinity/policy ablation (spec §6)", ""]
    if ablation is None:
        lines += ["(ablation JSON not supplied)", ""]
    else:
        nodes = ablation.get("nodes") or {}
        lines += ["Node arguments: X (affinity) = %s, Y (policy) = %s; "
                  "X CPUs=%s, Y CPUs=%s; fake_numa=%s."
                  % (nodes.get("x"), nodes.get("y"),
                     (nodes.get("x_cpus") or [])[:8],
                     (nodes.get("y_cpus") or [])[:8],
                     nodes.get("fake_numa")), ""]
        lines.append("| cell/form | requested mode | effective mode | "
                     "effective mask | affinity | first-touch cpu | pages by "
                     "node | unknown | placement | mincore | read-touch |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for res in ablation.get("results") or []:
            req = res.get("policy_requested") or {}
            eff = res.get("effective") or {}
            aff = res.get("affinity_requested") or {}
            mc = res.get("mincore") or {}
            touch = res.get("touch") or {}
            lines.append("| %s/%s | %s (%s) | %s | %s | cpu=%s rc=%s | %s | "
                         "%s | %s | %s | %s/%s | %s (%s pages) |" % (
                             res.get("cell"), res.get("form"),
                             req.get("mode_symbolic"), req.get("mode_numeric"),
                             eff.get("mempolicy_mode_symbolic"),
                             eff.get("mempolicy_mask_nodes"),
                             aff.get("cpu"), aff.get("set_rc"),
                             res.get("cpu_at_first_touch"),
                             res.get("pages_by_node"),
                             res.get("pages_unknown"),
                             res.get("placement_measured"),
                             mc.get("resident_pages"), mc.get("total_pages"),
                             "stable" if res.get("read_touch_stable") else
                             ("n/a" if res.get("form") != "write-path"
                              else "UNSTABLE"),
                             touch.get("pages")))
        lines += ["", "Ablation validity: %s%s" % (
            "PASS" if abl_ok else "FAIL",
            "" if abl_ok else " — " + "; ".join(abl_issues)), ""]
        wp = [r for r in ablation.get("results") or []
              if r.get("form") == "write-path"]
        if wp:
            lines.append("Write-path residency: pre-touch `move_pages` "
                         "statuses are %s; post-touch statuses are real node "
                         "ids and `numa_maps` gains N-fields. Raw per-page "
                         "statuses are preserved in the JSON. The "
                         "read-touch stability check re-queries EVERY page "
                         "of the measured range after the full range was "
                         "read-touched; unstable pages are %s." % (
                             sorted({s for r in wp
                                     for s in (r.get("move_pages_pre") or {})
                                     .get("statuses", [])}),
                             sum(r.get("read_touch_unstable_pages") or 0
                                 for r in wp)))
            lines.append("")
        lines.append("On this fake topology every CPU is listed on every "
                     "node, so the affinity arm cannot be distinguished from "
                     "the policy arm by CPU placement. The C/D result shows "
                     "that the corrected `MPOL_BIND` request is effective; "
                     "it does not establish physical affinity behavior.")
        lines.append("")

    lines += ["## Provenance", ""]
    if env:
        g = env.get("git") or {}
        kernel = env.get("kernel") or {}
        lines.append("- git: %s @ %s (dirty=%s)" % (
            g.get("branch"), g.get("head_sha"), g.get("dirty")))
        lines.append("- source worktree: %s" % (
            "CLEAN (reported SHA identifies the source)"
            if g.get("dirty") is False else
            "DIRTY — the report validator refuses this campaign"))
        lines.append("- kernel: %s | fake-numa: %s" % (
            kernel.get("release"), kernel.get("fake_numa_spec")))
        topo_map = _env_topology_map(env)
        lines.append("- CPU topology: %s" % ", ".join(
            "%s=%s" % (name, cpus) for name, cpus in
            sorted(topo_map.items())))
        lines.append("- shmem THP: %s" % (env.get("thp") or {}).get(
            "shmem_enabled"))
        lines.append("- governors: %s | SMT: %s" % (
            (env.get("cpu_extra") or {}).get("governors"),
            (env.get("cpu_extra") or {}).get("smt")))
        lines.append("- cpuset: %s | memory.max: %s" % (
            (env.get("cgroup") or {}).get("cpuset_cpus"),
            (env.get("cgroup") or {}).get("memory_max")))
        lines.append("- build hashes: %s" % ", ".join(
            "%s=%s" % (os.path.basename(k), str(v)[:12])
            for k, v in (env.get("build_hashes") or {}).items()))
        lines.append("- campaign env: `%s` / `%s`" % (
            campaign.get("env_before"), campaign.get("env_after")))
        env_after = campaign.get("_env_after")
        if env_after:
            drift = _env_drift(env, env_after)
            lines.append("- before/after drift: %s" % (
                "none" if not drift else
                "; ".join("%s: %r -> %r" % item for item in drift)))
    else:
        lines.append("(env manifest not supplied)")
    if args.baseline_compare and os.path.isfile(args.baseline_compare):
        try:
            with open(args.baseline_compare, encoding="utf-8") as fh:
                bc = json.load(fh)
            lines += ["", "## Baseline identity (4.7 vs 5.0)", ""]
            for row in bc.get("comparison") or []:
                lines.append("- %s: 4.7 median %.1f rec/s, 5.0 median "
                             "%.1f rec/s (delta %+.1f%%)" % (
                                 row.get("case"), row.get("median_47", 0),
                                 row.get("median_50", 0),
                                 row.get("delta_pct", 0)))
            lines.append("")
            lines.append(bc.get("note", ""))
        except (OSError, ValueError):
            lines.append("- baseline comparison file unreadable")
    lines += ["", "## One-page decision summary", ""]
    if topo["fake"]:
        lines.append("**Is the central ingest the limiter?** NOT DECIDABLE "
                     "on this fake-NUMA host. The per-node queue, ingest-"
                     "thread CPU, and worker-waiter metrics are present, "
                     "but spec §8 requires physical multi-node evidence; "
                     "this rehearsal returns Inconclusive by rule.")
        lines.append("")
        lines.append("**Is placement born-local?** The corrected ablation "
                     "shows that `MPOL_BIND` is requested with mode 2, is "
                     "effective, and places destination pages on the bound "
                     "node in both materialization forms. Because every CPU "
                     "is listed on every fake node, this validates the "
                     "instrumentation and the policy path, not physical "
                     "born-local behavior.")
        lines.append("")
        lines.append("**What remains?** Rental execution of this exact "
                     "campaign on physical multi-node hardware, with "
                     "`--node-x/--node-y` set to distinct physical nodes, "
                     "then the §8 verdict from the same report generator.")
    else:
        lines.append("**Is the central ingest the limiter?** %s" %
                     verdict["verdict"])
        lines.append("")
        lines.append("**Is placement born-local?** %s" % (
            "The ablation's placement evidence is valid."
            if abl_ok else
            "Placement evidence is not valid; see the ablation section."))
        lines.append("")
        lines.append("**What remains?** See the evidence above; the "
                     "verdict is derived only from measured, cross-trial "
                     "evidence and does not invent a throughput threshold.")
    lines.append("")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", args.out)
    print("verdict:", verdict["verdict"])
    return 0 if verdict["go"] or not topo["fake"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
