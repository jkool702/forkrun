"""Stage 0 per-case runner (campaign spec §3/§4).

Runs ONE forkrun workload in a CHILD python process (fresh process per
case, its own session/process group) and captures from OUTSIDE the
process boundary:

- end-to-end wall time and RSS samples (parent-side sampler at ~20ms,
  per-process over the whole engine tree)
- per-PROCESS and per-TASK CPU across the tree, with comm attribution.
  CPU is accumulated as a DELTA per (pid,tid) between samples, keyed by
  the task's comm AT THAT SAMPLE, so a task named `fr-ingest` only for
  the duration of the UMA spill is attributed to ingest and not to its
  later work.
- child pid + start/end timestamps, process-group id, timeout evidence
- pipe source-producer CPU and lifecycle measured SEPARATELY from the
  consumer tree (the producer is a sibling, not a tree member)
- STAGE0_DIAG/STAGE0_FINAL queue telemetry counts and source names

Containment (work order §6): the case runs in its own session/process
group. On timeout the ENTIRE group is killed, the direct child is
reaped, and the parent verifies no process with that pgrp remains.
`communicate()` is bounded both during the run and after the kill. A
pipe producer is tracked in its own process group and killed/reaped on
timeout or early consumer failure.

Corpus: generated JSONL-style records (ml_data_gen-compatible bytes),
written once by make_corpus.py.

Usage:
  run_case.py --spec stage0/specs/<case>.json --out <campaign>/cases/<id>/trialN
              --campaign-id ID [--trial N] [--python-path DIR]
"""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE_INTERVAL = 0.02  # 20ms RSS/CPU sampling
KILL_GRACE_S = 10.0     # bounded reap after SIGKILL
PRODUCER_GRACE_S = 5.0  # a healthy pipe producer exits on reader close


def _comm(pid, tid=None):
    try:
        p = "/proc/%d/task/%d/comm" % (pid, tid) if tid else \
            "/proc/%d/comm" % pid
        with open(p, encoding="ascii", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return "?"


def _proc_stat(pid):
    """Return (ppid, pgrp, cpu_sec) for one pid, or None."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as fh:
            parts = fh.read().rsplit(")", 1)[1].split()
        return (int(parts[1]), int(parts[2]),
                (int(parts[11]) + int(parts[12]))
                / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError):
        return None


def _tree_snapshot(root_pid):
    """Snapshot root's whole process tree.

    Returns (total_cpu_sec, {(pid,tid): (cpu_sec, comm)}). CPU is the
    task's cumulative utime+stime; the caller deltas consecutive
    snapshots. Missing processes are simply absent from a snapshot.
    """
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return None, {}
    ppid = {}
    pgrp = {}
    for name in names:
        st = _proc_stat(int(name))
        if st is None:
            continue
        ppid[int(name)] = st[0]
        pgrp[int(name)] = st[1]
    members = {root_pid}
    frontier = [root_pid]
    while frontier:
        nxt = []
        for cand, parent in ppid.items():
            if parent in frontier and cand not in members:
                members.add(cand)
                nxt.append(cand)
        frontier = nxt
    total = 0.0
    tasks = {}
    for member in members:
        task_dir = "/proc/%d/task" % member
        try:
            tids = os.listdir(task_dir)
        except OSError:
            continue
        for tid in tids:
            try:
                with open(os.path.join(task_dir, tid, "stat"),
                          encoding="utf-8") as fh:
                    parts = fh.read().rsplit(")", 1)[1].split()
                sec = (int(parts[11]) + int(parts[12])) \
                    / os.sysconf("SC_CLK_TCK")
            except (OSError, ValueError, IndexError):
                continue
            total += sec
            tasks[(member, int(tid))] = (sec, _comm(member, int(tid)))
    return total, tasks


def _accumulate_comm(prev, tasks, comm_cpu):
    """Accumulate per-comm CPU deltas between two tree snapshots."""
    for key, (sec, comm) in tasks.items():
        old = prev.get(key)
        if old is None or sec < old:
            delta = sec  # first observation or counter reset
        else:
            delta = sec - old
        prev[key] = sec
        if delta:
            comm_cpu[comm] = comm_cpu.get(comm, 0.0) + delta
    return comm_cpu


def _group_members(pgid):
    """PIDs whose process group is pgid (excluding zombies? no: include)."""
    out = []
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return out
    for name in names:
        st = _proc_stat(int(name))
        if st is not None and st[1] == pgid:
            out.append(int(name))
    return out


def _kill_group(pgid, label):
    """SIGKILL every member of pgid; return what was observed."""
    before = _group_members(pgid)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    return {"label": label, "pgid": pgid, "members_before": before}


def _verify_group_gone(pgid, label):
    """Wait briefly for the group to disappear; return remaining pids."""
    deadline = time.monotonic() + KILL_GRACE_S
    remaining = _group_members(pgid)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.01)
        remaining = _group_members(pgid)
    return {"label": label, "pgid": pgid, "members_after": remaining,
            "gone": not remaining}


def _parse_diag(stderr):
    """Count STAGE0_DIAG / STAGE0_FINAL lines and their src= values."""
    samples = 0
    finals = 0
    by_src = {}
    queue_lines = []
    for line in (stderr or "").splitlines():
        if not line.startswith("STAGE0_"):
            continue
        src = None
        for token in line.split():
            if token.startswith("src="):
                src = token[4:]
                break
        if line.startswith("STAGE0_DIAG "):
            samples += 1
            entry = by_src.setdefault(src or "?", {"samples": 0,
                                                   "finals": 0})
            entry["samples"] += 1
            queue_lines.append(line)
        elif line.startswith("STAGE0_FINAL "):
            finals += 1
            entry = by_src.setdefault(src or "?", {"samples": 0,
                                                   "finals": 0})
            entry["finals"] += 1
    return {
        "samples": samples,
        "finals": finals,
        "by_src": by_src,
        "queue_present": samples >= 1 and finals >= 1,
        "sample_lines": queue_lines,
    }


def _resolve_spec_paths(spec):
    """Resolve repo-relative input/plugin paths for the child."""
    out = dict(spec)
    inp = out.get("input")
    if inp and not os.path.isabs(inp):
        out["input"] = os.path.join(REPO, inp)
    payload = out.get("plugin_payload")
    if payload and ":" in payload:
        path, _, symbol = payload.rpartition(":")
        if path and not os.path.isabs(path):
            out["plugin_payload"] = os.path.join(REPO, path) + ":" + symbol
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
    # fd — map() os.dup()s caller descriptors internally, so the child
    # owns its working descriptor.
    src_fd = os.dup(3)
elif spec.get("source_kind") == "fd":
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
dt = time.monotonic() - t0
# Exactness accounting is harness work, not system work: it runs AFTER
# the map timer stops (MEMORY.md: never time the verifier).
total_bytes = 0
total_records = 0
for r in results:
    b = bytes(r)
    total_bytes += len(b)
    total_records += b.count(b"\n")
print("CHILD_DONE " + json.dumps({
    "elapsed_s": dt, "completed_bytes": total_bytes,
    "completed_records": total_records,
    "rec_per_s": total_records / dt if dt > 0 else 0,
    "completed_output_bytes_per_s": total_bytes / dt if dt > 0 else 0}))
"""


def run_case(spec, out_dir, campaign_id=None, trial=None,
             python_path=None, child_script=None, source_sha=None,
             spec_sha256=None):
    os.makedirs(out_dir, exist_ok=True)
    resolved = _resolve_spec_paths(spec)
    timeout = float(spec.get("timeout", 300))
    manifest = {
        "schema": "stage0-case/3",
        "campaign_id": campaign_id,
        "source_sha": source_sha,
        "spec_id": spec.get("id"),
        "spec_sha256": spec_sha256,
        "trial": trial,
        "spec": spec,
        "spec_resolved": resolved,
        "timeout_s": timeout,
        "started_monotonic": time.monotonic(),
        "started_epoch": time.time(),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    python_dir = python_path or os.path.join(REPO, "python")
    script = child_script or CHILD_SCRIPT

    pipe_writer = None
    pipe_reader = None
    pass_fds = ()
    pipe_close_after_spawn = ()
    if spec.get("source_kind") == "pipe":
        r_fd, w_fd = os.pipe()
        def _remap():
            os.dup2(r_fd, 3)
        pass_fds = (r_fd,)
        pipe_writer = subprocess.Popen(
            ["cat", resolved["input"]],
            stdout=w_fd, stderr=subprocess.DEVNULL,
            start_new_session=True)
        os.close(w_fd)
        pipe_reader = r_fd
        pipe_close_after_spawn = (r_fd,)
    else:
        _remap = None
    proc = subprocess.Popen(
        [sys.executable, "-c", script, python_dir, json.dumps(resolved)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        pass_fds=pass_fds, preexec_fn=_remap, start_new_session=True)
    manifest["child_pid"] = proc.pid
    manifest["case_pgid"] = proc.pid
    manifest["producer_pid"] = pipe_writer.pid if pipe_writer else None
    manifest["producer_pgid"] = pipe_writer.pid if pipe_writer else None
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    t0 = time.monotonic()
    deadline = t0 + timeout
    stdout = stderr = None
    timed_out = False
    cpu_peak = (None, {})
    producer_peak = (None, {})
    rss_peak_by_pid = {}
    prev_tasks = {}
    comm_cpu = {}
    producer_prev = {}
    producer_comm_cpu = {}
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=SAMPLE_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                manifest["timeout_kill"] = _kill_group(proc.pid, "case")
                try:
                    stdout, stderr = proc.communicate(timeout=KILL_GRACE_S)
                except subprocess.TimeoutExpired:
                    # Descendants still hold the pipes. The group was
                    # SIGKILLed; close our ends and reap the direct
                    # child so nothing can block this harness.
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    try:
                        proc.wait(timeout=KILL_GRACE_S)
                    except subprocess.TimeoutExpired:
                        pass
                    stdout = stdout or ""
                    stderr = stderr or ""
                break
            total, tasks = _tree_snapshot(proc.pid)
            if tasks:
                _accumulate_comm(prev_tasks, tasks, comm_cpu)
            if total is not None and (cpu_peak[0] is None
                                      or total > cpu_peak[0]):
                cpu_peak = (total, tasks)
            if pipe_writer is not None:
                ptotal, ptasks = _tree_snapshot(pipe_writer.pid)
                if ptasks:
                    _accumulate_comm(producer_prev, ptasks,
                                     producer_comm_cpu)
                if ptotal is not None and (producer_peak[0] is None
                                           or ptotal > producer_peak[0]):
                    producer_peak = (ptotal, ptasks)
            for member in {m for m, _ in tasks}:
                try:
                    with open("/proc/%d/status" % member,
                              encoding="utf-8") as fh:
                        for line in fh:
                            if line.startswith("VmRSS:"):
                                r = int(line.split()[1])
                                if r > rss_peak_by_pid.get(member, 0):
                                    rss_peak_by_pid[member] = r
                                break
                except (OSError, ValueError):
                    pass
    dt = time.monotonic() - t0
    for fd in pipe_close_after_spawn:
        try:
            os.close(fd)
        except OSError:
            pass

    # Producer lifecycle: separately tracked, killed/reaped if the case
    # timed out or failed, or if it outlives the consumer.
    producer_killed = False
    writer_rc = None
    if pipe_writer is not None:
        failed = timed_out or proc.returncode != 0
        if failed and pipe_writer.poll() is None:
            producer_killed = True
            manifest["producer_kill_after_failure"] = _kill_group(
                pipe_writer.pid, "producer")
        grace = KILL_GRACE_S if producer_killed else PRODUCER_GRACE_S
        try:
            writer_rc = pipe_writer.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            producer_killed = True
            manifest["producer_kill"] = _kill_group(pipe_writer.pid,
                                                    "producer")
            try:
                writer_rc = pipe_writer.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                try:
                    pipe_writer.kill()
                except OSError:
                    pass
                writer_rc = pipe_writer.poll()
        if timed_out and not producer_killed:
            producer_killed = True
            manifest["producer_kill_after_timeout"] = _kill_group(
                pipe_writer.pid, "producer")
            try:
                writer_rc = pipe_writer.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                writer_rc = pipe_writer.poll()
        manifest["producer_reaped"] = pipe_writer.poll() is not None
        manifest["producer_group_gone"] = _verify_group_gone(
            pipe_writer.pid, "producer")

    # If the direct child exited but descendants are still alive in its
    # group, kill them too: they may hold the captured pipes open.
    descendants_before = _group_members(proc.pid)
    if descendants_before:
        manifest["orphan_kill"] = _kill_group(proc.pid, "case-orphans")
    manifest["case_group_gone"] = _verify_group_gone(proc.pid, "case")

    manifest["wall_s"] = dt
    manifest["returncode"] = proc.returncode
    manifest["timed_out"] = timed_out
    manifest["child_stdout_tail"] = (stdout or "")[-2000:]
    manifest["child_stderr_tail"] = (stderr or "")[-3000:]
    for line in (stdout or "").splitlines():
        if line.startswith("CHILD_DONE "):
            try:
                manifest["child_report"] = json.loads(
                    line[len("CHILD_DONE "):])
            except ValueError:
                manifest["child_report_error"] = "malformed CHILD_DONE JSON"
    # The child's own timer covers only forkrun.map(); the outer wall
    # also includes the harness's post-run exactness accounting.
    manifest["map_s"] = (manifest.get("child_report") or {}).get(
        "elapsed_s")
    cpu_peak_total, per_pid = cpu_peak
    cpu_total = sum(comm_cpu.values()) if comm_cpu else None
    manifest["consumer_tree_cpu_sec"] = (
        round(cpu_total, 6) if cpu_total is not None else None)
    manifest["consumer_tree_cpu_peak_sec"] = cpu_peak_total
    per_pid_cpu = {}
    for (member, _tid), (sec, _comm_name) in (per_pid or {}).items():
        per_pid_cpu[member] = per_pid_cpu.get(member, 0.0) + sec
    manifest["consumer_cpu_per_pid"] = {
        str(k): round(v, 6) for k, v in sorted(per_pid_cpu.items())}
    manifest["thread_comm_cpu_sec"] = {
        k: round(v, 6) for k, v in sorted(comm_cpu.items())}
    ingest_cpu = comm_cpu.get("fr-ingest")
    ingest_found = ingest_cpu is not None and ingest_cpu > 0
    # The ingest task exists only inside forkrun.map(); the outer wall
    # also contains the harness's post-run exactness accounting, which
    # would dilute the utilization figure. Use the child's map timer.
    ingest_basis_s = manifest.get("map_s") or dt
    manifest["ingest_cpu_sec"] = ingest_cpu if ingest_found else None
    manifest["ingest_cpu_basis_s"] = ingest_basis_s if ingest_found else None
    manifest["ingest_cpu_basis_cores"] = (
        ingest_cpu / ingest_basis_s) if ingest_found and ingest_basis_s > 0 \
        else None
    manifest["ingest_attrib_note"] = (
        "comm-delta attribution: CPU is accumulated per (pid,tid) "
        "between samples and keyed by the task's comm at that sample. "
        "UMA spill/ingest is named fr-ingest via fr_py_set_task_name; "
        "the NUMA C ingest names itself. No fr-ingest CPU => null. "
        "The basis is the child's forkrun.map() timer, not the outer "
        "process wall (which includes post-run exactness accounting).")
    manifest["cpu_per_core_basis"] = (cpu_total / dt) if cpu_total else None
    producer_peak_total, producer_by_pid = producer_peak
    producer_total = (sum(producer_comm_cpu.values())
                      if producer_comm_cpu else None)
    manifest["producer_cpu_sec"] = (
        round(producer_total, 6) if producer_total is not None else None)
    manifest["producer_cpu_peak_sec"] = producer_peak_total
    manifest["producer_thread_comm_cpu_sec"] = {
        k: round(v, 6) for k, v in sorted(producer_comm_cpu.items())}
    producer_pid_cpu = {}
    for (member, _tid), (sec, _comm_name) in (producer_by_pid or {}).items():
        producer_pid_cpu[member] = producer_pid_cpu.get(member, 0.0) + sec
    manifest["producer_cpu_per_pid"] = {
        str(k): round(v, 6) for k, v in sorted(producer_pid_cpu.items())}
    manifest["producer_returncode"] = writer_rc
    manifest["producer_killed"] = producer_killed
    manifest["rss_peak_by_pid_kb"] = {
        str(k): v for k, v in rss_peak_by_pid.items()}
    manifest["rss_peak_kb"] = max(rss_peak_by_pid.values(), default=None)
    manifest["cpu_note"] = ("consumer tree sampled concurrently; "
                            "producer (pipe) excluded from consumer CPU "
                            "and reported separately")
    if cpu_total is None:
        manifest["cpu_note"] = ("sampler incomplete (child exited before "
                                "first sample; rerun with a bigger corpus)")
    diag = _parse_diag(stderr)
    manifest["diagnostics"] = {
        "samples": diag["samples"],
        "finals": diag["finals"],
        "by_src": diag["by_src"],
        "queue_present": diag["queue_present"],
        "forkrun_diag_queue": os.environ.get("FORKRUN_DIAG_QUEUE"),
    }
    incomplete = []
    if timed_out:
        incomplete.append("timed out")
    if manifest.get("returncode") != 0:
        incomplete.append("child returncode %s" % manifest.get("returncode"))
    if "child_report" not in manifest:
        incomplete.append("missing child_report")
    if not diag["queue_present"]:
        incomplete.append("missing STAGE0_DIAG/STAGE0_FINAL telemetry")
    if manifest.get("producer_returncode") not in (None, 0):
        incomplete.append("producer returncode %s"
                          % manifest.get("producer_returncode"))
    manifest["incomplete_reasons"] = incomplete
    manifest["complete"] = not incomplete
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    with open(os.path.join(out_dir, "stderr.log"), "w") as fh:
        fh.write(stderr or "")
    with open(os.path.join(out_dir, "stdout.log"), "w") as fh:
        fh.write(stdout or "")
    return manifest


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, help="case spec JSON file")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--campaign-id", default=None)
    ap.add_argument("--trial", type=int, default=None)
    ap.add_argument("--source-sha", default=None)
    ap.add_argument("--python-path", default=None,
                    help="python/ dir to import (baseline comparisons)")
    ap.add_argument("--child-script", default=None,
                    help="override the child payload (containment tests)")
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    m = run_case(spec, args.out, campaign_id=args.campaign_id,
                 trial=args.trial, python_path=args.python_path,
                 child_script=args.child_script,
                 source_sha=args.source_sha,
                 spec_sha256=_sha256(args.spec))
    rep = m.get("child_report", {})
    print("complete=%s rc=%s wall=%.2fs rec/s=%s consumer_cpu=%s "
          "ingest_cpu=%s producer_cpu=%s diag=%s timed_out=%s" % (
              m["complete"], m["returncode"], m["wall_s"],
              rep.get("rec_per_s"), m["consumer_tree_cpu_sec"],
              m.get("ingest_cpu_sec"), m["producer_cpu_sec"],
              m["diagnostics"]["samples"], m.get("timed_out", False)))
    return 0 if m["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
