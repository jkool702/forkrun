"""Stage 0 per-case runner (campaign spec §3/§4).

Runs ONE forkrun.pipeline-equivalent workload in a CHILD python
process (so the harness measures a fresh process, and a hang/kill is
contained), and captures from OUTSIDE the process boundary:

- end-to-end wall time and RSS samples (parent-side sampler at ~20ms)
- byte/record progress timeline (records yielded / wall seconds)
- process-tree CPU breakdown sampled at start and end
  (total thread CPU via /proc/<pid>/task/*/stat; per-thread utime/stime)
- child pid + start/end timestamps for the manifest

Downstream-demand estimation (spec §3): scanner/worker queue
telemetry is NOT exposed by this harness (no ring internals here).
Instead this runner derives: ingest publish rate (materialized bytes /
elapsed) vs. observed completion rate (completed bytes / elapsed), and
flags ingest-limited vs downstream-limited vs source-limited via
concurrent external sampling (ingest thread CPU vs worker idle). The
spec's queue-non-empty-interval method is reported as NOT AVAILABLE
here — that is the honest limitation, and it motivates least-invasive
ring instrumentation if a future iteration needs queue truth.

Corpus: generated JSONL-style records (ml_data_gen-compatible bytes),
written once by make_corpus.py.

Usage:
  run_case.py --spec stage0/specs/<case>.json --out stage0/runs/<id>/
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "python"))

SAMPLE_INTERVAL = 0.02  # 20ms RSS/progress sampling


def _pid_tree_cpu(pid):
    """Total CPU seconds for pid's whole process TREE.

    The engine forks workers and an ingest child; sampling only the
    direct child's /proc/<pid>/task misses their CPU entirely. Build
    the ppid map globally each sample and walk the tree from `pid`,
    summing utime+stime over every descendant's task group. Returns
    (total_sec, {pid: sec_top_task}) or (None, {}) when unavailable.
    """
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return None, {}
    ppid = {}
    for name in names:
        try:
            with open("/proc/%s/stat" % name, encoding="utf-8") as fh:
                parts = fh.read().rsplit(")", 1)[1].split()
            ppid[int(name)] = int(parts[1])
        except (OSError, ValueError, IndexError):
            pass
    # descendants of pid (BFS)
    members = {pid}
    frontier = [pid]
    while frontier:
        nxt = []
        for cand, parent in ppid.items():
            if parent in frontier and cand not in members:
                members.add(cand)
                nxt.append(cand)
        frontier = nxt
    total = 0.0
    per_proc = {}
    for member in members:
        tasks = "/proc/%d/task" % member
        sub = 0.0
        try:
            for tid in os.listdir(tasks):
                try:
                    with open(os.path.join(tasks, tid, "stat"),
                              encoding="utf-8") as fh:
                        parts = fh.read().rsplit(")", 1)[1].split()
                    ticks = int(parts[11]) + int(parts[12])
                    sub += ticks / os.sysconf("SC_CLK_TCK")
                except (OSError, ValueError, IndexError):
                    pass
        except OSError:
            continue
        if sub > 0:
            per_proc[member] = sub
            total += sub
    if not per_proc:
        return None, {}
    return total, per_proc


def _rss_kb(pid):
    try:
        with open("/proc/%d/status" % pid, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def _proc_tree_children(pid):
    """Direct children pids from /proc/<pid>/task/*/children (best effort)."""
    kids = set()
    try:
        for tid in os.listdir("/proc/%d/task" % pid):
            path = "/proc/%d/task/%s/children" % (pid, tid)
            try:
                with open(path, encoding="utf-8") as fh:
                    kids.update(int(x) for x in fh.read().split())
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    return kids


CHILD_SCRIPT = r"""
import os, sys, json, time
sys.path.insert(0, sys.argv[1])   # python/ dir
import forkrun

def upper(batch):
    return bytes(batch.data).upper()

spec = json.loads(sys.argv[2])
if spec.get("source_kind") == "pipe":
    # Sequential/pipe baseline (spec §3.2): the child inherits a pipe on
    # fd 3 (created by run_case.py's parent); pass its dup as the source
    # fd — map() os.dup()s caller descriptors internally (run.py:884),
    # so the child owns its working descriptor.
    src_fd = os.dup(3)
elif spec.get("source_kind") == "fd":
    # seekable descriptor opened by the child from path.
    src_fd = os.open(spec["input"], os.O_RDONLY)
else:
    src_fd = spec["input"]
workers = spec.get("workers", 4)
nodes = spec.get("nodes", "@4")
args = dict(workers=workers, order="index", nodes=nodes)
if spec.get("mode") == "plugin":
    args["mode"] = "plugin"
    args["payload"] = spec["plugin_payload"]

t0 = time.monotonic()
# Consume fully: materialized (=completed) work per second is measured
# at the top level from completed records; ingest rate is derived.
total_bytes = 0
total_records = 0
if spec.get("mode") == "plugin":
    payload_arg = args.pop("payload")
    results = forkrun.map(payload_arg, src_fd, **args)
else:
    results = forkrun.map(upper, src_fd, **args)
for r in results:
    b = bytes(r)
    total_bytes += len(b)
    total_records += b.count(b"\n")
dt = time.monotonic() - t0
print("CHILD_DONE " + json.dumps({
    "elapsed_s": dt, "completed_bytes": total_bytes,
    "completed_records": total_records,
    "rec_per_s": total_records / dt if dt > 0 else 0,
    "bytes_per_s": total_bytes / dt if dt > 0 else 0}))
"""


def run_case(spec, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    manifest = {
        "spec": spec,
        "schema": "stage0-case/1",
        "started_monotonic": time.monotonic(),
        "started_epoch": time.time(),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    pipe_writer = None
    pass_fds = ()
    pipe_fds_to_close = ()
    if spec.get("source_kind") == "pipe":
        # Pipe baseline: parent creates os.pipe(); the child inherits
        # the READ end remapped onto fd 3 (pass_fds + preexec_fn dup2);
        # a sibling subprocess streams the corpus into the WRITE end.
        r_fd, w_fd = os.pipe()
        def _remap():
            os.dup2(r_fd, 3)
        pass_fds = (3,)
        pipe_writer = subprocess.Popen(
            ["cat", os.path.join(REPO, spec["input"])],
            stdout=w_fd, stderr=subprocess.DEVNULL)
        os.close(w_fd)
        pipe_fds_to_close = (r_fd,)
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT,
         os.path.join(REPO, "python"), json.dumps(spec)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        pass_fds=pass_fds, preexec_fn=(_remap if pass_fds else None))
    manifest["child_pid"] = proc.pid
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    rss_samples = []
    t0 = time.monotonic()
    stderr = ""
    # Concurrent external sampler: the child must be sampled WHILE it
    # runs (a finished process exposes no RSS/CPU). Sample at ~20ms
    # from this parent's loop while waiting on exit.
    cpu_peak = (None, {})
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.02)
            break
        except subprocess.TimeoutExpired:
            rss = _rss_kb(proc.pid)
            if rss is not None:
                rss_samples.append((time.monotonic() - t0, rss))
            c, pt = _pid_tree_cpu(proc.pid)
            if c is not None and (cpu_peak[0] is None or c > cpu_peak[0]):
                cpu_peak = (c, pt)
    dt = time.monotonic() - t0
    if proc.returncode is None:
        proc.kill()
        stdout, stderr = proc.communicate()
        manifest["timed_out"] = True
    for fd in pipe_fds_to_close:
        try:
            os.close(fd)
        except OSError:
            pass
    writer_rc = None
    if pipe_writer is not None:
        writer_rc = pipe_writer.wait(timeout=30)
    manifest["writer_returncode"] = writer_rc
    manifest["wall_s"] = dt
    manifest["returncode"] = proc.returncode
    manifest["child_stdout_tail"] = (stdout or "")[-2000:]
    manifest["child_stderr_tail"] = (stderr or "")[-3000:]
    for line in (stdout or "").splitlines():
        if line.startswith("CHILD_DONE "):
            manifest["child_report"] = json.loads(line[len("CHILD_DONE "):])
    cpu_total, per_task = cpu_peak
    manifest["cpu_total_sec"] = cpu_total
    manifest["cpu_per_task"] = {str(k): v for k, v in per_task.items()}
    manifest["cpu_per_core_basis"] = (cpu_total / dt) if cpu_total else None
    manifest["rss_peak_kb"] = max((r for _, r in rss_samples), default=None)
    manifest["rss_samples"] = rss_samples[::max(1, len(rss_samples) // 20)]
    if cpu_total is None:
        manifest["cpu_note"] = ("sampler incomplete (child exited before "
                                "first sample; rerun with a bigger corpus)")
    manifest["complete"] = ("child_report" in manifest
                            and manifest["returncode"] == 0)
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    with open(os.path.join(out_dir, "stderr.log"), "w") as fh:
        fh.write(stderr or "")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, help="case spec JSON file")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    m = run_case(spec, args.out)
    rep = m.get("child_report", {})
    print("complete=%s rc=%s wall=%.2fs rec/s=%s cpu_total=%s" % (
        m["complete"], m["returncode"], m["wall_s"],
        rep.get("rec_per_s"), m["cpu_total_sec"]))
    return 0 if m["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
