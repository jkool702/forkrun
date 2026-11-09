"""Stage 0 per-case runner (campaign spec §3/§4).

Runs ONE forkrun workload in a CHILD python process (fresh process per
case; bounded by the spec timeout), and captures from OUTSIDE the
process boundary:

- end-to-end wall time and RSS samples (parent-side sampler at ~20ms,
  per-process over the whole engine tree)
- per-PROCESS CPU time across the tree (utime+stime summed over each
  member's tasks) + per-TID top samples with comm for role attribution
- child pid + start/end timestamps for the manifest
- pipe source-producer (e.g. `cat`) CPU measured SEPARATELY from the
  consumer tree (the producer is a sibling of the case process, not a
  member of its tree)

Downstream-demand estimation (spec §3): scanner/worker queue telemetry
is NOT exposed by this harness (no ring internals here). This runner
derives: ingest publish rate (materialized bytes / elapsed) vs.
observed completion rate (completed bytes / elapsed), and flags
ingest-limited vs downstream-limited vs source-limited via concurrent
external sampling (ingest thread CPU vs worker idle). The spec's
queue-non-empty-interval method is reported as NOT AVAILABLE here —
that is the honest limitation, and it motivates least-invasive ring
HELPERS for the rental phase.

Corpus: generated JSONL-style records (ml_data_gen-compatible bytes),
written once by make_corpus.py.

Usage:
  run_case.py --spec stage0/specs/<case>.json --out stage0/runs/<id>/
"""

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "python"))

SAMPLE_INTERVAL = 0.02  # 20ms RSS/progress sampling


def _comm(pid, tid=None):
    try:
        p = "/proc/%d/task/%d/comm" % (pid, tid) if tid else "/proc/%d/comm" % pid
        with open(p, encoding="ascii", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return "?"


def _pid_tree_cpu(pid, with_comms=False, max_tids=8):
    """Total CPU seconds for pid's whole process TREE.

    The engine forks workers and an ingest child; sampling only the
    direct child's /proc/<pid>/task misses their CPU entirely. Build
    the ppid map globally each sample and walk the tree from `pid`,
    summing utime+stime over every descendant's task group. Returns
    (total_sec, {pid: {"cpu": sec, "comm": str, "top_tids": [...]}})
    or (None, {}) when unavailable.
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
    per_pid = {}
    for member in members:
        tasks = "/proc/%d/task" % member
        sub = 0.0
        top = []
        try:
            tids = os.listdir(tasks)
        except OSError:
            continue
        for tid in tids:
            try:
                with open(os.path.join(tasks, tid, "stat"),
                          encoding="utf-8") as fh:
                    parts = fh.read().rsplit(")", 1)[1].split()
                ticks = int(parts[11]) + int(parts[12])
                sec = ticks / os.sysconf("SC_CLK_TCK")
                sub += sec
                if with_comms:
                    top.append((sec, tid, _comm(member, int(tid))))
            except (OSError, ValueError, IndexError):
                pass
        if sub > 0:
            entry = {"cpu": sub, "comm": _comm(member)}
            if with_comms:
                top.sort(reverse=True)
                entry["top_tids"] = [
                    {"tid": t, "cpu": round(s, 4), "comm": c}
                    for s, t, c in top[:max_tids]]
            per_pid[member] = entry
            total += sub
    if not per_pid:
        return None, {}
    return total, per_pid


def _rss_kb(pid):
    try:
        with open("/proc/%d/status" % pid, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def _tree_rss_peak(root_pid, snapshot=None):
    """RSS per member of root's tree from one /proc snapshot."""
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return {}
    ppid = {}
    for name in names:
        try:
            with open("/proc/%s/stat" % name, encoding="utf-8") as fh:
                parts = fh.read().rsplit(")", 1)[1].split()
            ppid[int(name)] = int(parts[1])
        except (OSError, ValueError, IndexError):
            pass
    members = {root_pid}
    frontier = [root_pid]
    while frontier:
        nxt = []
        for cand, parent in ppid.items():
            if parent in frontier and cand not in members:
                members.add(cand)
                nxt.append(cand)
        frontier = nxt
    out = {}
    for member in members:
        r = _rss_kb(member)
        if r is not None:
            out[member] = r
    return out


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
payload_arg = upper
if spec.get("mode") == "plugin":
    args["mode"] = "plugin"
    payload_arg = spec["plugin_payload"]

t0 = time.monotonic()
results = forkrun.map(payload_arg, src_fd, **args)
total_bytes = 0
total_records = 0
for r in results:
    b = bytes(r)
    total_bytes += len(b)
    total_records += b.count(b"\n")
dt = time.monotonic() - t0
print("CHILD_DONE " + json.dumps({
    "elapsed_s": dt, "completed_bytes": total_bytes,
    "completed_records": total_records,
    "rec_per_s": total_records / dt if dt > 0 else 0,
    "completed_output_bytes_per_s": total_bytes / dt if dt > 0 else 0}))
"""


def run_case(spec, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    timeout = float(spec.get("timeout", 300))
    manifest = {
        "spec": spec,
        "schema": "stage0-case/2",
        "timeout_s": timeout,
        "started_monotonic": time.monotonic(),
        "started_epoch": time.time(),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    pipe_writer = None
    pass_fds = ()
    pipe_close_after_spawn = ()
    if spec.get("source_kind") == "pipe":
        # Pipe baseline: parent creates os.pipe(); the child inherits
        # the READ end remapped onto fd 3. We pass the ACTUAL r_fd in
        # pass_fds (not a literal 3 — that only worked when os.pipe()
        # happened to hand back fd 3 in the parent).
        r_fd, w_fd = os.pipe()
        def _remap():
            os.dup2(r_fd, 3)
        pass_fds = (r_fd,)
        pipe_writer = subprocess.Popen(
            ["cat", os.path.join(REPO, spec["input"])],
            stdout=w_fd, stderr=subprocess.DEVNULL,
            start_new_session=False)
        os.close(w_fd)
        pipe_close_after_spawn = (r_fd,)
    else:
        _remap = None
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT,
         os.path.join(REPO, "python"), json.dumps(spec)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        pass_fds=pass_fds, preexec_fn=_remap)
    manifest["child_pid"] = proc.pid
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    t0 = time.monotonic()
    deadline = t0 + timeout
    stdout = stderr = None
    cpu_peak = (None, {})
    producer_peak = (None, {})
    rss_peak_by_pid = {}
    timed_out = False
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.02)
            break
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                proc.kill()
                stdout, stderr = proc.communicate()
                break
            c, pt = _pid_tree_cpu(proc.pid, with_comms=True)
            if c is not None and (cpu_peak[0] is None or c > cpu_peak[0]):
                cpu_peak = (c, pt)
            if pipe_writer is not None:
                pc, ppt = _pid_tree_cpu(pipe_writer.pid, with_comms=False)
                if pc is not None and (producer_peak[0] is None
                                       or pc > producer_peak[0]):
                    producer_peak = (pc, ppt)
            for member, r in _tree_rss_peak(proc.pid).items():
                if r > rss_peak_by_pid.get(member, 0):
                    rss_peak_by_pid[member] = r
    dt = time.monotonic() - t0
    for fd in pipe_close_after_spawn:
        try:
            os.close(fd)
        except OSError:
            pass
    writer_rc = None
    if pipe_writer is not None:
        try:
            writer_rc = pipe_writer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pipe_writer.kill()
            writer_rc = pipe_writer.wait()
    manifest["wall_s"] = dt
    manifest["returncode"] = proc.returncode
    manifest["timed_out"] = timed_out
    manifest["child_stdout_tail"] = (stdout or "")[-2000:]
    manifest["child_stderr_tail"] = (stderr or "")[-3000:]
    for line in (stdout or "").splitlines():
        if line.startswith("CHILD_DONE "):
            manifest["child_report"] = json.loads(line[len("CHILD_DONE "):])
    cpu_total, per_pid = cpu_peak
    manifest["consumer_tree_cpu_sec"] = cpu_total
    manifest["consumer_cpu_per_pid"] = {
        str(k): v for k, v in per_pid.items()}
    # Role attribution: the engine names its ingest task "fr-ingest"
    # (prctl — see forkrun_ring.c STAGE0 instrumentation). Sum any
    # thread whose comm is exactly that, anywhere in the tree.
    ingest_cpu = 0.0
    ingest_found = False
    for e in per_pid.values():
        for t in e.get("top_tids", []):
            if t.get("comm") == "fr-ingest":
                ingest_cpu += t["cpu"]
                ingest_found = True
    manifest["ingest_cpu_sec"] = ingest_cpu if ingest_found else None
    manifest["ingest_cpu_basis_cores"] = (
        ingest_cpu / dt) if ingest_found else None
    manifest["ingest_attrib_note"] = ("fr-ingest named via prctl in the "
                                      "engine (if the engine predates the "
                                      "diagnostic, no thread carries the "
                                      "name and this is null)")
    manifest["cpu_per_core_basis"] = (cpu_total / dt) if cpu_total else None
    producer_total, producer_by_pid = producer_peak
    manifest["producer_cpu_sec"] = producer_total
    manifest["producer_cpu_per_pid"] = {
        str(k): v for k, v in producer_by_pid.items()}
    manifest["rss_peak_by_pid_kb"] = {
        str(k): v for k, v in rss_peak_by_pid.items()}
    manifest["rss_peak_kb"] = max(rss_peak_by_pid.values(), default=None)
    manifest["cpu_note"] = ("consumer tree sampled concurrently; "
                            "producer (pipe) excluded from consumer CPU "
                            "and reported separately")
    if cpu_total is None:
        manifest["cpu_note"] = ("sampler incomplete (child exited before "
                                "first sample; rerun with a bigger corpus)")
    manifest["complete"] = (not timed_out
                            and "child_report" in manifest
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
    print("complete=%s rc=%s wall=%.2fs rec/s=%s consumer_cpu=%s "
          "producer_cpu=%s timed_out=%s" % (
              m["complete"], m["returncode"], m["wall_s"],
              rep.get("rec_per_s"), m["consumer_tree_cpu_sec"],
              m["producer_cpu_sec"], m.get("timed_out", False)))
    return 0 if m["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
