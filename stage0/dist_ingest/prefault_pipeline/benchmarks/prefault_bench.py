#!/usr/bin/env python3
"""WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0 — reproducible Python
benchmark/campaign driver. Launches the standalone C prototype with data
supplied through ACTUAL stdin/pipe input. Compares modes A/B/C
(lazy / serial_madvise / pipeline_madvise) under IDENTICAL parameters +
deterministic input + arrival schedule. Preserves raw artifacts. No
performance-improvement threshold on fake NUMA. NOT production.
"""
import argparse, json, os, random, shlex, statistics, subprocess, sys, tempfile, time

MODES = ["lazy", "serial_madvise", "pipeline_madvise"]
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
BIN = os.path.join(PKG, "prefault_pipeline")


def deterministic_bytes(total, pattern="counter"):
    """Deterministic input; byte at global offset i = i & 0xff (matches
    consumer checksum ordering; no retention of full stream by us)."""
    out = bytearray(total)
    for i in range(total):
        out[i] = i & 0xFF
    return bytes(out)


def schedule_chunks(total, schedule, burst_size, gap_s, rng):
    """Yield (chunk_bytes, gap_before_s). Same schedule for all modes."""
    chunks = []
    if schedule == "continuous":
        n = total
        off = 0
        while off < total:
            b = min(burst_size or total, total - off)
            chunks.append((b, 0.0)); off += b
    elif schedule == "burst-gap":
        off = 0
        while off < total:
            b = min(burst_size, total - off)
            chunks.append((b, gap_s)); off += b
    elif schedule == "bursty-variable":
        off = 0
        while off < total:
            b = min(max(1, int(rng.uniform(1, max(1, burst_size)))), total - off)
            g = rng.uniform(0.0, gap_s)
            chunks.append((b, g)); off += b
    else:
        raise ValueError("unknown schedule %r" % schedule)
    return chunks


def _det_chunk(off, n):
    return bytes(((off + i) & 0xFF) for i in range(n))


def feed_stdin(proc, total, chunks):
    """P2: stream actual stdin/pipe with schedule; NO full retention; NO
       repeated slicing of a retained buffer. Deterministic bytes generated
       on the fly; identical across modes."""
    writer_blocks = 0
    off = 0
    for (b, gap) in chunks:
        if gap > 0:
            time.sleep(gap)
        chunk = _det_chunk(off, b); off += b
        try:
            proc.stdin.write(chunk); proc.stdin.flush()
        except BrokenPipeError:
            writer_blocks += 1; break
    try:
        proc.stdin.close()
    except BrokenPipeError:
        writer_blocks += 1
    return {"writer_blocking_events": writer_blocks}


def run_once(bin_path, mode, cfg, total, chunks, json_path):
    cmd = [bin_path, "--mode", mode,
           "--slot-size", str(cfg["slot_size"]),
           "--slots-per-node", str(cfg["slots_per_node"]),
           "--workers-per-node", str(cfg["workers_per_node"]),
           "--json-out", json_path]
    if cfg.get("nodes"):
        cmd += ["--nodes", cfg["nodes"]]
    if cfg.get("consumer_delay_ns"):
        cmd += ["--consumer-delay-ns", str(cfg["consumer_delay_ns"])]
    if cfg.get("placement_sampling"):
        cmd += ["--placement-sampling"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    feeder = feed_stdin(proc, total, chunks)
    out, err = proc.communicate(timeout=600)
    t1 = time.monotonic()
    result = None
    if os.path.exists(json_path):
        try:
            result = json.load(open(json_path))
        except Exception:
            result = None
    return {"cmd": cmd, "cmd_str": shlex.join(cmd), "returncode": proc.returncode,
            "wall_seconds": t1 - t0, "stderr": err.decode("utf-8", "replace")[-2000:],
            "result": result, "feeder": feeder}


def _discover_node_count():
    try:
        raw = open("/sys/devices/system/node/online").read().strip()
    except OSError:
        return 1
    n = 0
    for part in raw.split(","):
        if "-" in part:
            a, b = part.split("-", 1); n += int(b) - int(a) + 1
        elif part:
            n += 1
    return max(1, n)


def _valid_accounting(res):
    if not isinstance(res, dict):
        return False
    tr = res.get("total_received", 0); tc = res.get("total_copied", 0)
    tp = res.get("total_published", 0); tcons = res.get("total_consumed", 0)
    return (res.get("rc", 1) == 0 and res.get("failed", 1) == 0
            and tr == tc == tp == tcons
            and tr >= 0 and tc >= 0 and tp >= 0 and tcons >= 0)


def summarize_md(campaign, outpath):
    L = ["# Prefault pipeline campaign (fake-NUMA / dev workstation)", "",
         "NOT physical-NUMA evidence; NOT production; no improvement threshold.", ""]
    for cell in campaign["cells"]:
        L.append("## %s schedule=%s reps=%d" % (cell["schedule"], cell["schedule"], cell["reps"]))
        for mode in MODES:
            runs = [r for r in cell["runs"] if r["mode"] == mode and r.get("result") and r.get("returncode") == 0 and _valid_accounting(r.get("result"))]
            if not runs:
                L.append("- %s: no valid runs" % mode); continue
            bps = [r["result"].get("effective_ingest_bytes_per_sec", 0) for r in runs]
            ov = [r["result"].get("overlap_summed_worker_ns", 0) for r in runs]
            prep_ratio = [r["result"].get("prepared_ratio", 0) for r in runs]
            med_bps = statistics.median(bps)
            L.append("- **%s**: median_e2e_Bps=%.1f  median_overlap_summed_ns=%d  median_prepared_ratio=%.4f  valid=%d/%d" % (
                mode, med_bps, statistics.median(ov), statistics.median(prep_ratio),
                len(runs), len([r for r in cell['runs'] if r['mode'] == mode])))
        L.append("")
    with open(outpath, "w") as f:
        f.write("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bin", default=BIN)
    ap.add_argument("--out", required=True, help="campaign output directory")
    ap.add_argument("--total-bytes", type=int, default=16 * 1024 * 1024)
    ap.add_argument("--slot-size", type=int, default=2 * 1024 * 1024)
    ap.add_argument("--slots-per-node", type=int, default=2)
    ap.add_argument("--workers-per-node", type=int, default=1)
    ap.add_argument("--nodes", default=None, help="comma list of sparse physical node ids (default discovered)")
    ap.add_argument("--schedules", default="continuous,burst-gap,bursty-variable")
    ap.add_argument("--burst-size", type=int, default=256 * 1024)
    ap.add_argument("--gap", type=float, default=0.002)
    ap.add_argument("--consumer-delay-ns", type=int, default=0)
    ap.add_argument("--placement-sampling", action="store_true")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--order", default="randomize", choices=["randomize", "alternate", "fixed"])
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--min-generations", type=int, default=3,
                    help="ensure total_bytes >= slots*slot_size*min_generations")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    modes = [m for m in args.modes.split(",") if m]
    cfg = {"slot_size": args.slot_size, "slots_per_node": args.slots_per_node,
           "workers_per_node": args.workers_per_node, "nodes": args.nodes,
           "consumer_delay_ns": args.consumer_delay_ns, "placement_sampling": args.placement_sampling}
    # force many generations: total > ring capacity
    if args.nodes:
        numnodes = len(args.nodes.split(","))
    else:
        numnodes = _discover_node_count()   # P2: match C discovery; don't assume 1
    ring_cap = args.slot_size * args.slots_per_node * numnodes
    total = max(args.total_bytes, ring_cap * args.min_generations)
    rng = random.Random(args.seed)

    campaign = {"schema": "prefault-pipeline-campaign/1", "bin": args.bin,
                "config": cfg, "total_bytes": total, "ring_capacity": ring_cap,
                "min_generations": args.min_generations, "reps": args.reps, "seed": args.seed,
                "order": args.order, "environment": {"fake_nua_note": "dev workstation; NOT physical NUMA"},
                "commands": [], "cells": []}

    for schedule in args.schedules.split(","):
        cell = {"schedule": schedule, "reps": args.reps, "runs": []}
        for rep in range(args.reps):
            order = list(modes)
            if args.order == "randomize":
                rng.shuffle(order)
            elif args.order == "alternate":
                order = order[rep % len(order):] + order[:rep % len(order)]
            sched_rng = random.Random(args.seed + rep)  # same schedule seed for all modes in this rep
            for mode in order:
                # SAME schedule for all modes in a rep
                chunks = schedule_chunks(total, schedule, args.burst_size, args.gap, random.Random(args.seed + rep))
                jpath = os.path.join(args.out, "run_%s_%s_%d.json" % (schedule, mode, rep))
                r = run_once(args.bin, mode, cfg, total, chunks, jpath)
                r["mode"] = mode; r["rep"] = rep; r["schedule"] = schedule
                cell["runs"].append(r); campaign["commands"].append(r["cmd_str"])
                # raw artifacts
                logp = os.path.join(args.out, "run_%s_%s_%d.stderr.log" % (schedule, mode, rep))
                open(logp, "w").write(r["stderr"])
        campaign["cells"].append(cell)

    with open(os.path.join(args.out, "campaign.json"), "w") as f:
        json.dump(campaign, f, indent=1, sort_keys=True)
    summarize_md(campaign, os.path.join(args.out, "summary.md"))
    print("wrote", os.path.join(args.out, "campaign.json"))
    return 0

if __name__ == "__main__":
    sys.exit(main())
