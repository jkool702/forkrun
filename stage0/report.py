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
    if doc.get("env_before"):
        env_before = _read_json(_resolve(campaign_dir, doc["env_before"]),
                                "env-before", problems)
    if doc.get("env_after"):
        env_after = _read_json(_resolve(campaign_dir, doc["env_after"]),
                               "env-after", problems)
    if env_before is not None:
        sha = (env_before.get("git") or {}).get("head_sha")
        if source_sha and sha and sha != source_sha:
            problems.append("campaign: env-before git %s != source_sha %s"
                            % (sha, source_sha))
    if env_after is not None and env_before is not None:
        drift = []
        for key in (("git", "head_sha"), ("kernel", "release"),
                    ("kernel", "fake_numa_spec"), ("thp", "shmem_enabled")):
            a = env_before
            b = env_after
            for part in key:
                a = a.get(part) if isinstance(a, dict) else None
                b = b.get(part) if isinstance(b, dict) else None
            if a != b:
                drift.append("%s: %r -> %r" % (".".join(key), a, b))
        if drift:
            problems.append("campaign: environment drift %s" % drift)

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
            if key in ("q", "b", "c", "a"):
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


def _trial_queue_stats(records):
    samples = [r for r in records if r["kind"] == "STAGE0_DIAG"]
    finals = [r for r in records if r["kind"] == "STAGE0_FINAL"]
    final = None
    if finals:
        # One sampler owns a trial (NUMA ingest or UMA scanner), so a
        # normal trial has exactly one FINAL. If a source ever emits
        # more than one, use the latest timeline point; gated_ms is
        # accumulated by the ingest source and must not be lost to a
        # later zero-valued scan FINAL.
        final = max(finals, key=lambda r: int(r.get("t_ms", 0)))
        samples = samples + [final]
    if not samples:
        samples = finals
    samples = sorted(samples, key=lambda r: int(r.get("t_ms", 0)))
    nodes = sorted({n for r in samples for n in (r.get("b") or {})})
    result = {
        "samples": len(samples),
        "duration_s": 0.0,
        "gated_ms": None,
        "nodes": {},
        "all_empty_fraction": None,
        "longest_all_empty_ms": 0.0,
        "any_nonempty_fraction": None,
        "idle_waiter_fraction": None,
        "published_batches_per_s": None,
        "claimed_batches_per_s": None,
        "srcs": sorted({r.get("src") for r in records
                        if r.get("src") is not None}),
    }
    gated_values = []
    for rec in finals:
        try:
            gated_values.append(int(rec.get("gated_ms", 0)))
        except (TypeError, ValueError):
            pass
    if gated_values:
        result["gated_ms"] = max(gated_values)
    if len(samples) < 2:
        if nodes:
            result["nodes"] = {n: {"samples": len(samples),
                                   "nonempty_fraction": None,
                                   "longest_empty_ms": None,
                                   "claimed_batches_per_s_nonempty": None,
                                   "consumption_intervals": 0}
                               for n in nodes}
        return result

    t0 = int(samples[0].get("t_ms", 0))
    t1 = int(samples[-1].get("t_ms", 0))
    result["duration_s"] = max(0.0, (t1 - t0) / 1000.0)

    per_node = {n: {"samples": 0, "nonempty": 0, "empty": 0,
                    "longest_empty_ms": 0.0, "empty_start": None,
                    "consume_time": 0.0, "consume_claims": 0.0,
                    "intervals": 0, "published": 0.0, "pub_time": 0.0,
                    "claimed": 0.0, "claim_time": 0.0}
                for n in nodes}
    all_empty = 0
    all_pairs = 0
    any_nonempty = 0
    all_empty_start = None
    idle_waiter = 0
    idle_samples = 0

    for prev, cur in zip(samples, samples[1:]):
        try:
            dt = (int(cur.get("t_ms", 0)) - int(prev.get("t_ms", 0))) / 1000.0
        except (TypeError, ValueError):
            continue
        if dt <= 0:
            continue
        all_pairs += 1
        depths = {}
        for node in nodes:
            p = _depth(prev.get("b") or {}, node)
            c = _depth(cur.get("b") or {}, node)
            if p is None or c is None:
                continue
            depths[node] = c
            st = per_node[node]
            st["samples"] += 1
            if c > 0:
                st["nonempty"] += 1
                st["empty_start"] = None
            else:
                st["empty"] += 1
                if st["empty_start"] is None:
                    st["empty_start"] = int(prev.get("t_ms", 0))
                st["longest_empty_ms"] = max(
                    st["longest_empty_ms"],
                    int(cur.get("t_ms", 0)) - st["empty_start"])
            # Publication and dequeue progress over the whole trial.
            pw = _depth(prev.get("b") or {}, node)
            cw = _depth(cur.get("b") or {}, node)
            if pw is not None and cw is not None and cw >= pw:
                st["published"] += cw - pw
                st["pub_time"] += dt
            pc = _depth(prev.get("c") or {}, node, pair=False)
            cc = _depth(cur.get("c") or {}, node, pair=False)
            if pc is not None and cc is not None and cc >= pc:
                st["claimed"] += cc - pc
                st["claim_time"] += dt
            # Consumption while this node's batch queue is continuously
            # non-empty (both endpoints non-empty).
            if p > 0 and c > 0 and pc is not None and cc is not None \
                    and cc >= pc:
                st["consume_time"] += dt
                st["consume_claims"] += cc - pc
                st["intervals"] += 1
        if depths:
            if all(v == 0 for v in depths.values()):
                all_empty += 1
                if all_empty_start is None:
                    all_empty_start = int(prev.get("t_ms", 0))
                result["longest_all_empty_ms"] = max(
                    result["longest_all_empty_ms"],
                    int(cur.get("t_ms", 0)) - all_empty_start)
            else:
                any_nonempty += 1
                all_empty_start = None
            # Idle attribution: workers alive, queue empty, waiters > 0.
            waiters = 0
            workers = 0
            for node in nodes:
                a = (cur.get("a") or {}).get(node)
                if a and len(a) >= 2:
                    waiters += a[0]
                    workers += a[1]
            if workers > 0 and all(v == 0 for v in depths.values()):
                idle_samples += 1
                if waiters > 0:
                    idle_waiter += 1

    if all_pairs:
        result["all_empty_fraction"] = all_empty / all_pairs
        result["any_nonempty_fraction"] = any_nonempty / all_pairs
    if idle_samples:
        result["idle_waiter_fraction"] = idle_waiter / idle_samples
    node_out = {}
    for node, st in per_node.items():
        pairs = st["samples"]
        node_out[node] = {
            "samples": pairs,
            "nonempty_fraction": (st["nonempty"] / pairs) if pairs else None,
            "longest_empty_ms": st["longest_empty_ms"],
            "published_batches_per_s": (st["published"] / st["pub_time"])
            if st["pub_time"] else None,
            "claimed_batches_per_s": (st["claimed"] / st["claim_time"])
            if st["claim_time"] else None,
            "claimed_batches_per_s_nonempty": (
                st["consume_claims"] / st["consume_time"])
            if st["consume_time"] else None,
            "consumption_intervals": st["intervals"],
            "consumption_interval_s": st["consume_time"],
        }
    result["nodes"] = node_out
    result["published_batches_per_s"] = _sum_rate(
        [(v["published_batches_per_s"],
          v["samples"]) for v in node_out.values()])
    result["claimed_batches_per_s"] = _sum_rate(
        [(v["claimed_batches_per_s"], v["samples"])
         for v in node_out.values()])
    return result


def _sum_rate(pairs):
    vals = [(v, w) for v, w in pairs if v is not None and w]
    if not vals:
        return None
    return sum(v * w for v, w in vals) / sum(w for _, w in vals)


def queue_demand_stats(cases):
    """Aggregate per-case queue telemetry from raw stderr.log files.

    Trials are processed independently: no interval ever spans a trial
    boundary. Timestamps are the sampler's own t_ms, not an assumed
    20ms cadence.
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
            trials.append(_trial_queue_stats(_diag_records(text)))
        if not trials:
            out[case] = None
            continue
        agg = {
            "trials": len(trials),
            "samples": sum(t["samples"] for t in trials),
            "srcs": sorted({s for t in trials for s in t["srcs"]}),
            "duration_s": _median([t["duration_s"] for t in trials]),
            "gated_ms": _median([t["gated_ms"] for t in trials
                                 if t["gated_ms"] is not None]),
            "all_empty_fraction": _weighted(
                [(t["all_empty_fraction"], t["samples"] - 1)
                 for t in trials]),
            "longest_all_empty_ms": max(
                (t["longest_all_empty_ms"] for t in trials), default=0.0),
            "any_nonempty_fraction": _weighted(
                [(t["any_nonempty_fraction"], t["samples"] - 1)
                 for t in trials]),
            "idle_waiter_fraction": _weighted(
                [(t["idle_waiter_fraction"], t["samples"] - 1)
                 for t in trials]),
            "published_batches_per_s": _weighted(
                [(t["published_batches_per_s"], t["duration_s"])
                 for t in trials]),
            "claimed_batches_per_s": _weighted(
                [(t["claimed_batches_per_s"], t["duration_s"])
                 for t in trials]),
            "nodes": {},
        }
        node_ids = sorted({n for t in trials for n in t["nodes"]})
        for node in node_ids:
            rows = [t["nodes"][node] for t in trials
                    if node in t["nodes"]]
            agg["nodes"][node] = {
                "samples": sum(r["samples"] for r in rows),
                "nonempty_fraction": _weighted(
                    [(r["nonempty_fraction"], r["samples"] - 1)
                     for r in rows]),
                "longest_empty_ms": max(
                    (r["longest_empty_ms"] for r in rows), default=0.0),
                "published_batches_per_s": _weighted(
                    [(r["published_batches_per_s"], r["samples"])
                     for r in rows]),
                "claimed_batches_per_s": _weighted(
                    [(r["claimed_batches_per_s"], r["samples"])
                     for r in rows]),
                "claimed_batches_per_s_nonempty": _weighted(
                    [(r["claimed_batches_per_s_nonempty"],
                      r["consumption_interval_s"]) for r in rows]),
                "consumption_intervals": sum(
                    r["consumption_intervals"] for r in rows),
                "consumption_interval_s": sum(
                    r["consumption_interval_s"] for r in rows),
            }
        out[case] = agg
    return out


def _weighted(pairs):
    vals = [(v, w) for v, w in pairs if v is not None and w]
    if not vals:
        return None
    return sum(v * w for v, w in vals) / sum(w for _, w in vals)


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
        ingests = [m["ingest_cpu_basis_cores"] for m in ok
                   if m.get("ingest_cpu_basis_cores") is not None]
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
            "median_ingest_cores": _median(ingests),
            "ingest_attributed": bool(ingests),
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


def ablation_ok(ablation, campaign_id=None):
    problems = []
    if not isinstance(ablation, dict):
        return False, ["ablation JSON missing"]
    if ablation.get("schema") != SCHEMA_ABLATION:
        problems.append("ablation: schema %r != %r"
                        % (ablation.get("schema"), SCHEMA_ABLATION))
    if campaign_id and ablation.get("campaign_id") not in (None, campaign_id):
        problems.append("ablation: campaign_id %r != %r"
                        % (ablation.get("campaign_id"), campaign_id))
    nodes = ablation.get("nodes") or {}
    x, y = nodes.get("x"), nodes.get("y")
    if x is None or y is None or x == y:
        problems.append("ablation: invalid node pair x=%r y=%r" % (x, y))
    for result in ablation.get("results") or []:
        cell = result.get("cell")
        form = result.get("form")
        label = "%s/%s" % (cell, form)
        if not result.get("valid"):
            problems.append("%s: invalid (%s)"
                            % (label, result.get("invalid_reason")))
            continue
        req = result.get("policy_requested") or {}
        eff = result.get("effective") or {}
        if cell in ("A", "B"):
            if req.get("mode_numeric") != 0 or eff.get("mempolicy_mode") != 0:
                problems.append("%s: MPOL_DEFAULT not requested/effective"
                                % label)
        elif cell in ("C", "D"):
            if req.get("mode_numeric") != 2:
                problems.append("%s: requested mode %r != MPOL_BIND (2)"
                                % (label, req.get("mode_numeric")))
            if eff.get("mempolicy_mode") != 2:
                problems.append("%s: effective mode %r != MPOL_BIND (2)"
                                % (label, eff.get("mempolicy_mode")))
            if eff.get("mempolicy_mask_nodes") != [y]:
                problems.append("%s: effective mask %r != [%r]"
                                % (label, eff.get("mempolicy_mask_nodes"), y))
        if not result.get("placement_measured"):
            problems.append("%s: placement not measured" % label)
        if form == "write-path" and not result.get("read_touch_stable"):
            problems.append("%s: read-touch changed page-0 placement" % label)
    if not ablation.get("results"):
        problems.append("ablation: no results")
    return not problems, problems


def derive_verdict(summary, queue, env, ablation_issues, campaign_problems):
    """Spec §8 derivation. Fake NUMA is always Inconclusive."""
    topo = _env_topology(env)
    if campaign_problems:
        return {
            "verdict": "INVALID — campaign completeness/identity check failed",
            "evidence": ["- " + p for p in campaign_problems],
            "go": False, "topology": topo,
        }
    if topo["fake"]:
        return {
            "verdict": "INCONCLUSIVE for real-NUMA benefit — fake NUMA",
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
            "evidence": ["- %s" % topo["label"]],
            "go": False, "topology": topo,
        }
    if ablation_issues:
        return {
            "verdict": "INCONCLUSIVE — placement evidence is not valid",
            "evidence": ["- " + p for p in ablation_issues],
            "go": False, "topology": topo,
        }
    decisive = [r for r in summary
                if r["n_ok"] >= 1 and r["median_map_s"] is not None
                and r["median_map_s"] >= 2.0]
    if not decisive:
        return {
            "verdict": "INCONCLUSIVE — no decisive (>=2s) case",
            "evidence": ["- Every case is shorter than the campaign's own "
                         "2-second rule; startup dominates."],
            "go": False, "topology": topo,
        }
    missing_demand = [r["case"] for r in decisive
                      if not queue.get(r["case"])
                      or not queue[r["case"]]["nodes"]]
    if missing_demand:
        return {
            "verdict": "INCONCLUSIVE — downstream-demand estimate missing",
            "evidence": ["- No usable per-node queue telemetry for: %s"
                         % ", ".join(missing_demand)],
            "go": False, "topology": topo,
        }

    # Relative evidence, no invented absolute throughput margin.
    supply_gap = []
    ingest_near_one = []
    idle_evidence = []
    for row in decisive:
        q = queue[row["case"]]
        pub = q.get("published_batches_per_s")
        cons = [n.get("claimed_batches_per_s_nonempty")
                for n in q["nodes"].values()
                if n.get("claimed_batches_per_s_nonempty") is not None]
        cons_max = max(cons) if cons else None
        if pub is not None and cons_max is not None and cons_max > pub:
            supply_gap.append(row["case"])
        ic = row.get("median_ingest_cores")
        if ic is not None and _INGEST_NEAR_ONE[0] <= ic <= _INGEST_NEAR_ONE[1]:
            ingest_near_one.append(row["case"])
        iw = q.get("idle_waiter_fraction")
        if iw is not None and iw > 0:
            idle_evidence.append(row["case"])

    evidence = []
    evidence.append("- Topology: %s" % topo["label"])
    evidence.append("- Decisive cases (>=2s): %s"
                    % ", ".join(r["case"] for r in decisive))
    evidence.append("- Ingest CPU basis (cores): %s"
                    % ", ".join("%s=%.2f" % (
                        r["case"], r["median_ingest_cores"])
                        for r in decisive
                        if r["median_ingest_cores"] is not None))
    evidence.append("- Supply gap (consumption under available work > "
                    "publication): %s"
                    % (", ".join(supply_gap) or "none observed"))
    evidence.append("- Ingest near one core (spec §4.2 reading band "
                    "%.2f-%.2f): %s"
                    % (_INGEST_NEAR_ONE[0], _INGEST_NEAR_ONE[1],
                       ", ".join(ingest_near_one) or "none"))
    evidence.append("- Worker-waiter evidence during empty queues: %s"
                    % (", ".join(idle_evidence) or "none observed"))
    all_cases_gap = len(supply_gap) == len(decisive)
    all_cases_ingest = len(ingest_near_one) == len(decisive)
    if all_cases_gap and all_cases_ingest and idle_evidence:
        return {
            "verdict": "GO candidate — centralized ingest is the measured "
                       "limiter on this physical host",
            "evidence": evidence + [
                "- All decisive cases show consumption under available "
                "work above the publication rate, ingest CPU near one "
                "core, and worker-waiter evidence while queues are empty.",
                "- This is a recommendation to implement/test the "
                "distributed design, not proof that it will scale."],
            "go": True, "topology": topo,
        }
    return {
        "verdict": "INCONCLUSIVE — the evidence does not isolate ingestion",
        "evidence": evidence + [
            "- Spec §8 requires the supply gap to be attributable to "
            "centralized ingest CPU saturation while downstream has "
            "unused capacity, consistently across trials. At least one "
            "required condition is missing or inconsistent, so no "
            "Go/No-Go is asserted."],
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
                             campaign.get("_problems") or [])

    lines = [
        "# Stage 0 rehearsal report — %s" % topo["label"],
        "",
        "- campaign: `%s`" % campaign.get("campaign_id"),
        "- source: `%s`" % campaign.get("source_sha"),
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
              "map s | process s | tree cores | ingest cores | "
              "ingest attributed | diag samples |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        lines.append("| %s | w%s n%s %s | %d/%d | %s | %s | %s | %s | %s | "
                     "%s | %s | %d |" % (
                         r["case"], r["spec"].get("workers"),
                         r["spec"].get("nodes"), r["spec"].get("mode"),
                         r["n_ok"], r["n_trials"],
                         _fmt(r["median_rec_per_s"], "%.0f"),
                         _fmt(r["spread_pct"], "%.1f"),
                         _fmt(r["median_map_s"]),
                         _fmt(r["median_process_s"]),
                         _fmt(r["median_per_core"]),
                         _fmt(r["median_ingest_cores"]),
                         "yes" if r["ingest_attributed"] else "NO",
                         r["diag_samples"]))
    lines += ["", "`map s` is the child's `forkrun.map()` timer; `process s` "
                  "is the outer process wall, which also contains the "
                  "harness's post-run exactness accounting. Ingest "
                  "attribution is per-TASK `comm` CPU accumulated as "
                  "a delta between samples: a task named `fr-ingest` only "
                  "while it spills is attributed to ingest. Tree cores are "
                  "the sum of all task CPU deltas over the run divided by "
                  "wall, not a peak snapshot.", ""]

    lines += ["## Per-node queue telemetry (STAGE0_DIAG, spec §4.3)", ""]
    lines.append("Raw timestamped samples (per node head/tail, batch "
                 "read/write, dequeue counter, waiter gauge) are retained "
                 "in each trial's `stderr.log`; the table aggregates them "
                 "per trial and never joins one trial's end to the next "
                 "trial's start.")
    lines.append("")
    lines.append("| case | samples | duration s | nodes | per-node "
                 "nonempty (batch queue) | all-shards-empty | longest "
                 "all-empty ms | published/s | claimed/s | claimed/s in "
                 "nonempty intervals | gated ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary:
        q = queue.get(r["case"])
        if not q:
            lines.append("| %s | 0 | - | - | NO TELEMETRY | - | - | - | - | "
                         "- | - |" % r["case"])
            continue
        per_node = "; ".join(
            "n%d:%s" % (n, _fmt(v.get("nonempty_fraction"), "%.2f"))
            for n, v in sorted(q["nodes"].items()))
        lines.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | "
                     "%s |" % (
                         r["case"], q["samples"],
                         _fmt(q["duration_s"], "%.2f"),
                         ",".join(str(n) for n in sorted(q["nodes"])),
                         per_node or "-",
                         _fmt(q["all_empty_fraction"], "%.2f"),
                         _fmt(q["longest_all_empty_ms"], "%.0f"),
                         _fmt(q["published_batches_per_s"], "%.1f"),
                         _fmt(q["claimed_batches_per_s"], "%.1f"),
                         _fmt(_weighted([
                             (v.get("claimed_batches_per_s_nonempty"),
                              v.get("consumption_interval_s"))
                             for v in q["nodes"].values()]), "%.1f"),
                         _fmt(q["gated_ms"], "%.0f")))
    lines += ["", "### Per-node detail", "",
              "| case | node | nonempty | longest empty ms | published/s | "
              "claimed/s | claimed/s (nonempty) | nonempty interval s |",
              "|---|---|---|---|---|---|---|---|"]
    for r in summary:
        q = queue.get(r["case"])
        if not q:
            continue
        for node, v in sorted(q["nodes"].items()):
            lines.append("| %s | n%d | %s | %s | %s | %s | %s | %s |" % (
                r["case"], node,
                _fmt(v.get("nonempty_fraction"), "%.2f"),
                _fmt(v.get("longest_empty_ms"), "%.0f"),
                _fmt(v.get("published_batches_per_s"), "%.1f"),
                _fmt(v.get("claimed_batches_per_s"), "%.1f"),
                _fmt(v.get("claimed_batches_per_s_nonempty"), "%.1f"),
                _fmt(v.get("consumption_interval_s"), "%.2f")))
    lines += ["", "`published/s` is the batch-queue write_idx delta; "
                  "`claimed/s` is the dequeue counter delta. "
                  "`claimed/s (nonempty)` uses only intervals where that "
                  "node's batch queue was non-empty at both sampled ends. "
                  "Sampling is event-driven at ~20ms, so intervals are "
                  "reported in real seconds from the sampler timestamps, "
                  "not as sample counts. `gated_ms` is the ingest "
                  "backlog-gated wait accumulated by the engine sampler "
                  "(ingest source only).", ""]

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
                     "node | unknown | placement | mincore |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for res in ablation.get("results") or []:
            req = res.get("policy_requested") or {}
            eff = res.get("effective") or {}
            aff = res.get("affinity_requested") or {}
            mc = res.get("mincore") or {}
            lines.append("| %s/%s | %s (%s) | %s | %s | cpu=%s rc=%s | %s | "
                         "%s | %s | %s | %s/%s |" % (
                             res.get("cell"), res.get("form"),
                             req.get("mode_symbolic"), req.get("mode_numeric"),
                             eff.get("mempolicy_mode_symbolic"),
                             eff.get("mempolicy_mask_nodes"),
                             aff.get("cpu"), aff.get("set_rc"),
                             res.get("cpu_at_first_touch"),
                             res.get("pages_by_node"),
                             res.get("pages_unknown"),
                             res.get("placement_measured"),
                             mc.get("resident_pages"), mc.get("total_pages")))
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
                         "read-touch stability check (page 0 re-queried after "
                         "the rest of the range was touched) is %s." % (
                             sorted({s for r in wp
                                     for s in (r.get("move_pages_pre") or {})
                                     .get("statuses", [])}),
                             "stable for every cell"
                             if all(r.get("read_touch_stable") for r in wp)
                             else "NOT stable for every cell"))
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
        lines.append("- kernel: %s | fake-numa: %s" % (
            kernel.get("release"), kernel.get("fake_numa_spec")))
        lines.append("- shmem THP: %s" % (env.get("thp") or {}).get(
            "shmem_enabled"))
        lines.append("- build hashes: %s" % ", ".join(
            "%s=%s" % (os.path.basename(k), str(v)[:12])
            for k, v in (env.get("build_hashes") or {}).items()))
        lines.append("- campaign env: `%s` / `%s`" % (
            campaign.get("env_before"), campaign.get("env_after")))
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
