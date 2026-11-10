#!/usr/bin/env python3
"""Campaign manifest writer (Stage 0, schema 2).

ONE authoritative implementation of campaign identity: the spec
inventory (id + sha256), the expected case/trial matrix, the outcome
records, and the environment-manifest references. `run_campaign.sh`
calls `start` before the first trial and `finish` after the last; the
report validates the same schema in `stage0/report.py`.

A campaign is identified by `campaign_id` and lives in exactly one
directory. The report refuses artifacts whose campaign_id or spec
inventory does not match this manifest, so a rerun cannot inherit a
previous invocation's trials.
"""

import argparse
import hashlib
import json
import os
import sys
import time


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_to(base, path):
    ap = os.path.abspath(path)
    base = os.path.abspath(base)
    if ap == base or ap.startswith(base + os.sep):
        return os.path.relpath(ap, base)
    return ap


def inventory(spec_paths):
    specs = []
    ids = set()
    for path in spec_paths:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        spec_id = doc.get("id")
        if not isinstance(spec_id, str) or not spec_id:
            raise SystemExit("campaign: spec %s has no id" % path)
        if any(c not in
               "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
               "0123456789._-" for c in spec_id):
            raise SystemExit("campaign: unsafe spec id %r" % spec_id)
        if spec_id in ids:
            raise SystemExit("campaign: duplicate spec id %r" % spec_id)
        ids.add(spec_id)
        specs.append({
            "id": spec_id,
            "path": rel_to(os.getcwd(), path),
            "sha256": sha256(path),
        })
    return sorted(specs, key=lambda s: s["id"])


def start(out, campaign_id, source_sha, trials, env_before, env_after,
          spec_paths):
    specs = inventory(spec_paths)
    doc = {
        "schema": "stage0-campaign/2",
        "campaign_id": campaign_id,
        "source_sha": source_sha,
        "trials_requested": int(trials),
        "specs": specs,
        "expected_cases": [s["id"] for s in specs],
        "outcomes": [],
        "state": "running",
        "env_before": rel_to(out, env_before),
        "env_after": rel_to(out, env_after),
        "forkrun_diag_queue": os.environ.get("FORKRUN_DIAG_QUEUE"),
        "started_epoch": time.time(),
        "started_monotonic": time.monotonic(),
    }
    manifest_path = os.path.join(out, "campaign-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
    return manifest_path


def finish(out, outcomes_path):
    manifest_path = os.path.join(out, "campaign-manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    outcomes = []
    with open(outcomes_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            case, trial, status, manifest = line.split("\t")
            outcomes.append({
                "case": case,
                "trial": int(trial),
                "status": status,
                "manifest": manifest,
            })
    outcomes.sort(key=lambda o: (o["case"], o["trial"]))
    doc["outcomes"] = outcomes
    doc["state"] = "complete" if all(
        o["status"] == "ok" for o in outcomes) else "failed"
    doc["finished_epoch"] = time.time()
    doc["finished_monotonic"] = time.monotonic()
    doc["all_ok"] = doc["state"] == "complete"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
    return manifest_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="phase", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--out", required=True)
    p_start.add_argument("--campaign-id", required=True)
    p_start.add_argument("--source-sha", required=True)
    p_start.add_argument("--trials", required=True, type=int)
    p_start.add_argument("--env-before", required=True)
    p_start.add_argument("--env-after", required=True)
    p_start.add_argument("--spec", action="append", required=True)

    p_finish = sub.add_parser("finish")
    p_finish.add_argument("--out", required=True)
    p_finish.add_argument("--outcomes", required=True)

    args = ap.parse_args()
    if args.phase == "start":
        if args.trials < 1:
            print("campaign: --trials must be >= 1", file=sys.stderr)
            return 2
        start(args.out, args.campaign_id, args.source_sha, args.trials,
              args.env_before, args.env_after, args.spec)
        return 0
    finish(args.out, args.outcomes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
