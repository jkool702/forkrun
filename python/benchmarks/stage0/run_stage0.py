#!/usr/bin/env python3
"""Stage 0 measurement runner — one command end to end.

    bash python/benchmarks/stage0/run_stage0.sh

What it does (all output under python/benchmarks/stage0/, all legs logged to
files; only JSON summary lines + derived stats are read back):
  1. generate deterministic inputs (skip if manifest matches),
  2. compile the forkrun-side C plugins,
  3. run incumbent legs (Pool / futures / torch-probe / parallel / split),
  4. run forkrun legs (bash frontend + C-plugin substrate ceiling),
  5. run fault-isolation legs,
  6. write results JSON, then the CSV + Markdown tables and the report.

Zero product code: measures through frun.bash and the C plugin ABI only.
Long legs run as subprocesses with generous timeouts; run this script with
nohup in background and poll results/progress.log.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))          # .../python/benchmarks/stage0
REPO = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))  # repo root
INCDIR = os.path.join(ROOT, "incumbents")
FRDIR = os.path.join(ROOT, "forkrun")
WORK = os.path.join(ROOT, "work")
INPUTS = os.path.join(ROOT, "inputs")
RESULTS = os.path.join(ROOT, "results")
LOGS = os.path.join(ROOT, "logs")
FRUN = os.path.join(REPO, "frun.bash")
RING_HDR = os.path.join(REPO, "ring_loadables")

NPROC = os.cpu_count() or 8

COSTS_US = [1, 10, 100, 1000, 10000]
POOL_CHUNKS = [1, 100, 1000]
LEG_BUDGET_S = 25.0


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(RESULTS, "progress.log"), "a") as fh:
        fh.write(line + "\n")


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: str, logpath: str, timeout: float) -> tuple[int, float]:
    """Run shell cmd, redirect all output to logpath. Returns (rc, elapsed)."""
    t0 = time.monotonic()
    with open(logpath, "wb") as fh:
        try:
            p = subprocess.run(cmd, shell=True, executable="/bin/bash",
                               stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    return rc, time.monotonic() - t0


def json_line(logpath: str) -> dict:
    """Read back only the single JSON summary line (context hygiene)."""
    with open(logpath, "rb") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith(b"{") and line.endswith(b"}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    return {}


def grep_count(logpath: str, pattern: str, max_bytes: int = 200000) -> int:
    rx = re.compile(pattern.encode())
    n = 0
    try:
        with open(logpath, "rb") as fh:
            data = fh.read(max_bytes)
        n = len(rx.findall(data))
    except OSError:
        pass
    return n


# ---- whole-tree RSS sampler (for frun / parallel legs) ----

def _tree_pids(root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    own: set[int] = set()
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/stat") as fh:
                    parts = fh.read().rsplit(")", 1)
                ppid = int(parts[1].split()[1])
                children.setdefault(ppid, []).append(int(pid))
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        return {root}
    stack = [root]
    while stack:
        p = stack.pop()
        if p in own:
            continue
        own.add(p)
        stack.extend(children.get(p, ()))
    return own


def _tree_hwm_mb(pids: set[int]) -> float:
    total_kb = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status") as fh:
                for ln in fh:
                    if ln.startswith("VmHWM:"):
                        total_kb += int(ln.split()[1])
                        break
        except (OSError, ValueError):
            continue
    return total_kb / 1024.0


class Sampler(threading.Thread):
    """Polls whole-tree VmHWM until stop(); peak_megabytes is the result."""

    def __init__(self, root_pid: int, interval: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.root = root_pid
        self.interval = interval
        self.peak = 0.0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                v = _tree_hwm_mb(_tree_pids(self.root))
            except Exception:
                v = 0.0
            self.peak = max(self.peak, v)
            self._stop.wait(self.interval)

    def stop(self) -> float:
        self._stop.set()
        self.join()
        return self.peak


def run_sampled(cmd: str, logpath: str, timeout: float) -> tuple[int, float, float]:
    """Run cmd with whole-tree RSS sampling. Returns (rc, elapsed, peak_mb)."""
    t0 = time.monotonic()
    with open(logpath, "wb") as fh:
        try:
            p = subprocess.Popen(cmd, shell=True, executable="/bin/bash",
                                 stdout=fh, stderr=subprocess.STDOUT)
            samp = Sampler(p.pid)
            samp.start()
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                rc = 124
            peak = samp.stop()
        except Exception:
            rc, peak = 1, 0.0
    return rc, time.monotonic() - t0, peak


def parse_timev(logpath: str) -> dict:
    """Independent cross-check from /usr/bin/time -v (if present in log)."""
    out: dict = {}
    try:
        with open(logpath, "rb") as fh:
            data = fh.read().decode("utf-8", "replace")
        m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", data)
        if m:
            out["timev_maxrss_mb"] = round(int(m.group(1)) / 1024.0, 1)
        m = re.search(r"Elapsed \(wall clock\) time.*: (\d+):([\d.]+)", data)
        if m:
            out["timev_elapsed_s"] = round(int(m.group(1)) * 60 + float(m.group(2)), 3)
    except OSError:
        pass
    return out


def frun_cmd(inner: str) -> str:
    return f"bash -c '. \"{FRUN}\" && frun {inner}'"


def hardware_label() -> str:
    model = "unknown-cpu"
    try:
        with open("/proc/cpuinfo") as fh:
            for ln in fh:
                if ln.startswith("model name"):
                    model = ln.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    mem_gb = 0
    try:
        with open("/proc/meminfo") as fh:
            for ln in fh:
                if ln.startswith("MemTotal:"):
                    mem_gb = int(ln.split()[1]) // 1024 // 1024
                    break
    except OSError:
        pass
    import platform
    return (f"{model} | {NPROC}t | {mem_gb}GB single-socket | "
            f"{platform.node()} | {time.strftime('%Y-%m-%d')}")


def main() -> int:
    import s0legs
    import report
    os.makedirs(RESULTS, exist_ok=True)
    # Fresh run = clean slate for the failure marker (a stale one from an
    # aborted run must never sit beside green tables).
    for stale in ("stage0_error.txt",):
        try:
            os.remove(os.path.join(RESULTS, stale))
        except OSError:
            pass
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    want = set(only.split(",")) if only != "all" else {
        "jsonl", "transform", "tensor", "streaming", "faults"}
    ctx: dict = {"rows": [], "faults": [], "hw": ""}
    open(os.path.join(RESULTS, "progress.log"), "w").write(
        f"stage0 start {time.strftime('%Y-%m-%d %H:%M:%S')} only={only}\n")
    # Merge with any prior rows.json so --only re-runs refresh their niche.
    prior = os.path.join(RESULTS, "rows.json")
    if only != "all" and os.path.exists(prior):
        try:
            old = json.load(open(prior))
            niches_map = {"jsonl": "jsonl-ingest",
                          "transform": "per-record-transform",
                          "tensor": "tokenize-to-tensor",
                          "streaming": "tb-streaming",
                          "faults": "fault-isolation"}
            drop = {niches_map[w] for w in want if w in niches_map}
            ctx["rows"] = [r for r in old.get("rows", [])
                           if r["niche"] not in drop]
            ctx["faults"] = ([] if "faults" in want
                             else old.get("faults", []))
            ctx["hw"] = old.get("hardware", "")
        except (OSError, ValueError):
            pass
    try:
        s0legs.setup(ctx)
        if "jsonl" in want:
            s0legs.jsonl(ctx)
        if "transform" in want:
            s0legs.transform(ctx)
        if "tensor" in want:
            s0legs.tensor(ctx)
        if "streaming" in want:
            s0legs.streaming(ctx)
        if "faults" in want:
            s0legs.faults(ctx)
    except Exception as exc:  # stage boundary failure is data, not a crash
        log(f"STAGE FAILED: {type(exc).__name__}: {exc}")
        with open(os.path.join(RESULTS, "stage0_error.txt"), "w") as fh:
            fh.write(f"{type(exc).__name__}: {exc}\n")
    with open(os.path.join(RESULTS, "rows.json"), "w") as fh:
        json.dump({"hardware": ctx["hw"],
                   "engine_provenance": ctx.get("engine_provenance", ""),
                   "rows": ctx["rows"],
                   "faults": ctx["faults"]}, fh, indent=1)
    report.write_tables(ctx, RESULTS)
    report.write_faults(ctx, RESULTS)
    report.write_report(ctx, RESULTS)
    log("stage0 complete: tables + report in results/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
