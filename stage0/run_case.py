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
import math
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
    """Count STAGE0_DIAG / STAGE0_FINAL lines and their src= values.

    Also extracts the DIRECT ingest-thread CPU records:
      - STAGE0_FINAL src=ingest cpu_ns=... (C NUMA ingest)
      - STAGE0_INGEST_CPU src=... cpu_ns=... wall_ns=... (Python spill)
    The comm-delta sampler is a cross-check, not the authority.
    """
    samples = 0
    finals = 0
    by_src = {}
    queue_lines = []
    direct_cpu_ns = {}
    direct_wall_ns = {}
    final_cpu_ns = {}
    final_t_ms = {}
    final_t_us = {}
    for line in (stderr or "").splitlines():
        if not line.startswith("STAGE0_"):
            continue
        fields = {}
        for token in line.split()[1:]:
            key, _, value = token.partition("=")
            fields[key] = value
        src = fields.get("src")
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
            try:
                final_cpu_ns[src or "?"] = int(fields.get("cpu_ns", 0))
            except ValueError:
                pass
            try:
                final_t_ms[src or "?"] = int(fields.get("t_ms", 0))
            except ValueError:
                pass
            try:
                if fields.get("t_us") is not None:
                    final_t_us[src or "?"] = int(fields.get("t_us", 0))
            except ValueError:
                pass
        elif line.startswith("STAGE0_INGEST_CPU "):
            try:
                cpu = int(fields.get("cpu_ns", 0))
                wall = int(fields.get("wall_ns", 0))
            except ValueError:
                continue
            phase = src or "?"
            direct_cpu_ns[phase] = direct_cpu_ns.get(phase, 0) + cpu
            direct_wall_ns[phase] = direct_wall_ns.get(phase, 0) + wall
    return {
        "samples": samples,
        "finals": finals,
        "by_src": by_src,
        "queue_present": samples >= 1 and finals >= 1,
        "sample_lines": queue_lines,
        "direct_ingest_cpu_ns": direct_cpu_ns,
        "direct_ingest_wall_ns": direct_wall_ns,
        "final_cpu_ns": final_cpu_ns,
        "final_t_ms": final_t_ms,
        "final_t_us": final_t_us,
    }


def _direct_ingest_cpu(diag, ingest_basis_s):
    """Authoritative direct ingest-thread CPU figures for one trial.

    Python spill records are already CPU/wall deltas around the copy.
    The C NUMA ingest emits its FINAL with `cpu_ns` measured as a delta
    since sampler init and `t_us` as the phase duration at microsecond
    resolution. Prefer `t_us` over `t_ms`: a millisecond field truncates
    a 3.9 ms phase to 3 ms, which would report >1 core for a single
    thread. The map-basis figure is a run-level cross-check only.
    """
    direct_ns = sum(diag["direct_ingest_cpu_ns"].values())
    source = None
    phase_s = None
    if direct_ns > 0:
        source = "python-spill (CLOCK_THREAD_CPUTIME_ID)"
        phase_s = sum(diag["direct_ingest_wall_ns"].values()) / 1e9
    else:
        c_ns = diag["final_cpu_ns"].get("ingest", 0)
        if c_ns > 0:
            direct_ns = c_ns
            source = "c-ingest-final (CLOCK_THREAD_CPUTIME_ID)"
            t_us = diag["final_t_us"].get("ingest")
            if t_us is not None:
                phase_s = t_us / 1e6
            else:
                phase_s = diag["final_t_ms"].get("ingest", 0) / 1000.0
    return {
        "cpu_ns": direct_ns,
        "source": source,
        "phase_s": phase_s,
        "map_basis_cores": (
            (direct_ns / 1e9) / ingest_basis_s
            if direct_ns > 0 and ingest_basis_s > 0 else None),
        "phase_cores": (
            (direct_ns / 1e9) / phase_s
            if direct_ns > 0 and phase_s and phase_s > 0 else None),
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


# C3: cache-preconditioning policy (attributable, factual).
CACHE_PRECONDITION_POLICIES = (
    "best_effort_os_cache",
    "warm_repeat",
    "drop_caches_if_privileged",
)


def _cache_precondition(spec, resolved):
    """Apply requested cache-preconditioning policy before timed measurement.

    Returns a factual record; never claims privileged cold-cache control unless
    the action actually succeeded. Policies are separate from performance axes.
    """
    req = str(spec.get("cache_precondition_policy") or spec.get("cache_policy") or "best_effort_os_cache")
    # Accept legacy descriptive string as best-effort default.
    if req.startswith("best_effort_os_cache"):
        req = "best_effort_os_cache"
    rec = {
        "requested_policy": req,
        "policy": req if req in CACHE_PRECONDITION_POLICIES else "invalid",
        "actions": [],
        "achieved": None,
        "privileged_action_attempted": False,
        "privileged_action_succeeded": False,
        "fallback": None,
        "notes": [],
    }
    if req not in CACHE_PRECONDITION_POLICIES:
        rec["achieved"] = False
        rec["notes"].append("unknown cache_precondition_policy")
        return rec
    inp = resolved.get("input") or spec.get("input")
    if req == "best_effort_os_cache":
        rec["actions"].append({"action": "none", "reason": "best-effort OS page cache; no privileged control"})
        rec["achieved"] = True
        rec["notes"].append("no privileged cold-cache control claimed")
        return rec
    if req == "warm_repeat":
        # Factual warm preconditioning: read corpus into OS page cache before measurement.
        bytes_read = 0
        ok = False
        err = None
        if inp and os.path.exists(inp):
            try:
                with open(inp, "rb") as fh:
                    while True:
                        b = fh.read(4 * 1024 * 1024)
                        if not b:
                            break
                        bytes_read += len(b)
                ok = True
            except Exception as e:
                err = str(e)
        else:
            err = "input missing/unreadable for warm preconditioning"
        rec["actions"].append({"action": "read_input_into_page_cache", "path": inp, "bytes_read": bytes_read, "ok": ok, "error": err})
        rec["achieved"] = bool(ok)
        if not ok:
            rec["fallback"] = "warm_precondition_failed"
        return rec
    if req == "drop_caches_if_privileged":
        rec["privileged_action_attempted"] = True
        path = "/proc/sys/vm/drop_caches"
        err = None
        ok = False
        try:
            with open(path, "w", encoding="ascii") as fh:
                fh.write("3\n")
            ok = True
        except Exception as e:
            err = str(e)
        rec["actions"].append({"action": "write_drop_caches_3", "path": path, "ok": ok, "error": err})
        rec["privileged_action_succeeded"] = bool(ok)
        if ok:
            rec["achieved"] = True
            rec["notes"].append("drop_caches succeeded; actual cache state still OS/kernel dependent")
        else:
            # Factual fallback: no privileged control available.
            rec["fallback"] = "best_effort_os_cache"
            rec["achieved"] = False
            rec["notes"].append("drop_caches not available/permitted; no cold-cache control claimed")
        return rec
    rec["achieved"] = False
    return rec


# ---------------------------------------------------------------------------
# C3-correction-2: duration-qualification pass accounting (authoritative
# helpers). One decision, one implementation: the outcome of each dist-engine
# pass and the aggregation of qualified passes are decided here. The
# repetition loop (_run_duration_repetition) and the pass-1 record
# (run_case) consume these; no other code re-implements the rules.
# ---------------------------------------------------------------------------


def _finite_nonneg(value):
    """Authoritative parse: float if present, finite and >= 0, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


def _dist_pass_wall_seconds(dist_result):
    """AUTHORITATIVE engine wall_seconds of one DIST_RESULT (None if invalid)."""
    if not isinstance(dist_result, dict):
        return None
    return _finite_nonneg(dist_result.get("wall_seconds"))


def _dist_pass_qualified(timed_out, process_rc, dist_result):
    """AUTHORITATIVE: does one dist-engine pass establish qualification?

    WO §2: a pass contributes to accumulated effective duration only when ALL
    of: (1) the process exited successfully, (2) it did not time out,
    (3) a valid DIST_RESULT is present and parseable, (4) the result reports
    successful execution (rc), (5) functional correctness is established
    (correct), (6) engine wall_seconds is present, finite and valid.

    Distinct validity dimensions (P1 §2): process-execution success
    (timed_out / process_rc), functional correctness (correct), performance
    validity (via _dist_pass_performance_validity) and duration qualification
    (this decision) are separate -- none implies another.

    Returns (qualified, reasons); reasons is empty iff qualified.
    """
    reasons = []
    if timed_out:
        reasons.append("pass timed out")
    elif process_rc is None:
        reasons.append("no process run (pass not launched)")
    elif process_rc != 0:
        reasons.append("process returncode %r" % (process_rc,))
    if isinstance(dist_result, dict):
        if not timed_out and dist_result.get("rc") != 0:
            reasons.append("DIST_RESULT rc=%r" % (dist_result.get("rc"),))
        if dist_result.get("correct") is not True:
            reasons.append(
                "functional correctness not established (correct=%r)"
                % (dist_result.get("correct"),))
        if _dist_pass_wall_seconds(dist_result) is None:
            reasons.append("engine wall_seconds missing/invalid")
    else:
        reasons.append("no parseable DIST_RESULT")
    return (not reasons), reasons


def _dist_pass_performance_validity(dist_result):
    """AUTHORITATIVE tri-state performance validity of one pass.

    True/False/None from DIST_RESULT.validity.performance_measurement (with
    compat aliases). None = unknown/not established.
    """
    v = (dist_result or {}).get("validity") or {}
    for key in ("performance_measurement", "performance_measurement_valid",
                "performance_valid"):
        if key in v:
            val = v[key]
            if isinstance(val, bool) or val is None:
                return val
            return None
    return None


def _dist_pass_scan_evidence(dist_result):
    """AUTHORITATIVE consumer-scan evidence for one pass."""
    dr = dist_result if isinstance(dist_result, dict) else {}
    ev = (dr.get("consumer_kernel") or {}).get("scan_bytes_evidence") or {}
    return {
        "total_consumer_bytes_scanned": ev.get("total_consumer_bytes_scanned"),
        "total_consumed": dr.get("total_consumed"),
        "scan_equals_consumed": ev.get("scan_equals_consumed"),
    }


def _cache_precondition_compatible(cache_record):
    """AUTHORITATIVE cache-precondition compatibility rule (WO §4).

    Conservative: passes whose actual cache treatment differs from the
    policy's controlled state are not comparable in one uniformly
    preconditioned composite measurement. A pass with unknown treatment is
    never silently treated as compatible.
    """
    if not isinstance(cache_record, dict):
        return False
    pol = cache_record.get("policy") or "best_effort_os_cache"
    if pol == "best_effort_os_cache":
        # Never described as a controlled cold-cache state (factual).
        return True
    if pol == "warm_repeat":
        return bool(cache_record.get("achieved"))
    if pol == "drop_caches_if_privileged":
        return bool(cache_record.get("privileged_action_succeeded"))
    return False


def _parse_dist_result_lines(stderr):
    """Parse DIST_RESULT JSON lines from a process's stderr text."""
    result = None
    error = None
    for line in (stderr or "").splitlines():
        if not line.startswith("DIST_RESULT "):
            continue
        try:
            result = json.loads(line[len("DIST_RESULT "):])
        except ValueError:
            if error is None:
                error = "malformed DIST_RESULT JSON"
    return result, error


def _build_duration_pass_record(pass_n, is_initial, timed_out, process_rc,
                                dist_result, dist_result_error, wall_s_harness,
                                cache_record, cleanup=None, output_dir=None):
    """AUTHORITATIVE per-pass evidence record for duration qualification.

    Preserves complete pass-level evidence: process success/rc/timeout,
    failure reasons, full DIST_RESULT, functional correctness, performance
    validity, engine wall, consumed/scanned bytes, reservations, cache
    outcome and cleanup facts. `duration_contributes` is True iff the pass is
    qualified (WO §2); a pass that fails any qualification condition
    contributes no duration.
    """
    qualified, reasons = _dist_pass_qualified(timed_out, process_rc,
                                              dist_result)
    wall = _dist_pass_wall_seconds(dist_result)
    scan_ev = _dist_pass_scan_evidence(dist_result)
    drc = dist_result.get("rc") if isinstance(dist_result, dict) else None
    if qualified:
        status = "success"
    elif timed_out:
        status = "failed_timeout"
    else:
        status = "failed_execution"
    rec = {
        "pass": pass_n,
        "is_initial_pass": bool(is_initial),
        "output_dir": output_dir,
        "status": status,
        "complete": bool(qualified),
        "qualified": bool(qualified),
        "duration_contributes": bool(qualified),
        "reasons": list(reasons),
        "failure_reason": (reasons[0] if reasons else None),
        "process_returncode": process_rc,
        "process_success": (not timed_out) and process_rc == 0,
        "timed_out": bool(timed_out),
        "termination_reason": ("timeout" if timed_out
                               else ("completed" if process_rc == 0
                                     else "nonzero_exit")),
        "dist_result": dist_result if isinstance(dist_result, dict) else None,
        "dist_result_rc": drc,
        "dist_result_error": dist_result_error,
        "functional_correctness": (dist_result.get("correct")
                                   if isinstance(dist_result, dict) else None),
        "performance_validity": _dist_pass_performance_validity(dist_result),
        "engine_wall_seconds": wall,
        "wall_seconds_harness": (float(wall_s_harness)
                                 if wall_s_harness is not None else None),
        "total_consumed": (dist_result.get("total_consumed")
                           if isinstance(dist_result, dict) else None),
        "total_consumer_bytes_scanned": scan_ev.get("total_consumer_bytes_scanned"),
        "scan_equals_consumed": scan_ev.get("scan_equals_consumed"),
        "reservations_total": (dist_result.get("reservations_total")
                               if isinstance(dist_result, dict) else None),
        "cache_precondition": cache_record if isinstance(cache_record, dict) else None,
        "cache_compatible": _cache_precondition_compatible(cache_record),
        "cleanup": cleanup,
        "effective_wall_seconds": (float(wall) if qualified else 0.0),
    }
    return rec


def _run_repeat_pass(pass_cmd, timeout_s, label="repeat-pass"):
    """AUTHORITATIVE repeated-pass lifecycle (WO §5).

    Runs one repeated dist pass in a NEW process group (start_new_session,
    so pgid == child pid). On timeout: SIGTERM to the group -> grace ->
    SIGKILL escalation when needed -> reap the direct child -> verify the
    group is gone. Cleanup outcomes are recorded factually.
    """
    t0 = time.monotonic()
    p = subprocess.Popen(pass_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, cwd=REPO, start_new_session=True)
    pgid = p.pid
    cleanup = {"label": label if label else "repeat-pass", "pgid": pgid,
               "terminate_signals": [], "reaped": False,
               "group_gone": None, "members_after": []}
    timed_out = False
    stdout = stderr = ""
    try:
        stdout, stderr = p.communicate(timeout=max(float(timeout_s), 0.001))
    except subprocess.TimeoutExpired:
        timed_out = True
        # 1. Reliably terminate the launched process group.
        try:
            os.killpg(pgid, signal.SIGTERM)
            cleanup["terminate_signals"].append("SIGTERM")
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            stdout, stderr = p.communicate(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            # 2. Escalate to forced termination.
            try:
                os.killpg(pgid, signal.SIGKILL)
                cleanup["terminate_signals"].append("SIGKILL")
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                stdout, stderr = p.communicate(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
    # 3. Reap the direct child.
    try:
        p.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass
    cleanup["reaped"] = p.poll() is not None
    # 4. Verify the process group is gone.
    verify = _verify_group_gone(pgid, label)
    cleanup["group_gone"] = verify["gone"]
    cleanup["members_after"] = verify["members_after"]
    cleanup["wall_s"] = time.monotonic() - t0
    return {"rc": p.returncode, "stdout": stdout or "", "stderr": stderr or "",
            "wall_s": cleanup["wall_s"], "timed_out": timed_out,
            "cleanup": cleanup}


def _run_duration_repetition(first_pass_record, cmd, target_s, budget_s,
                             repeat_runner, cache_precondition_fn,
                             pass_cap=30, case_timeout_s=None, out_dir=None):
    """AUTHORITATIVE repetition loop for duration qualification (WO §5).

    Bounds: pass-count cap (pass_cap), repetition wall-clock budget
    (budget_s from the repetition start), and per-pass timeout
    min(case_timeout_s, remaining budget). Stops after the first
    unsuccessful repeated pass. Every attempted pass is recorded in
    pass_records; timeout passes contribute no duration.

    repeat_runner: callable(pass_n, timeout_s) -> run dict with keys
        stdout, stderr, timed_out, rc, wall_s, cleanup.
    cache_precondition_fn: callable(pass_n) -> cache-precondition record,
        applied BEFORE the pass runs (outside the timed interval).

    Returns (pass_records, accumulated_effective_wall_seconds,
    stop_reason, repeat_runs). stop_reason is one of:
    "target_reached", "max_pass_count_reached",
    "repetition_budget_exhausted", "pass_timeout",
    "pass_execution_failure", "cache_precondition_incompatibility",
    "repetition_unavailable", or None.
    """
    pass_records = [first_pass_record]
    repeat_runs = {}
    accumulated = float(sum(p["effective_wall_seconds"]
                            for p in pass_records if p["duration_contributes"]))
    target_s = float(target_s)
    budget_s = float(budget_s)
    cmd_ok = bool(cmd)
    can_repeat = cmd_ok and first_pass_record["qualified"]
    stop_reason = None
    if first_pass_record.get("cache_compatible") is False and \
            first_pass_record["qualified"]:
        # P2 (WO §2 finding 2): an incompatible INITIAL pass stops
        # repetition even when it reached the target. Pass 1 still
        # contributes duration (P1); the aggregate excludes it (P2).
        stop_reason = "cache_precondition_incompatibility"
    elif accumulated >= target_s:
        stop_reason = "target_reached"
    elif not can_repeat:
        if not cmd_ok:
            stop_reason = "repetition_unavailable"
        elif first_pass_record["timed_out"]:
            stop_reason = "pass_timeout"
        else:
            stop_reason = "pass_execution_failure"
    else:
        t_start = time.monotonic()
        pass_n = 1
        while True:
            if accumulated >= target_s:
                stop_reason = "target_reached"
                break
            if pass_n >= pass_cap:
                stop_reason = "max_pass_count_reached"
                break
            remaining_budget = budget_s - (time.monotonic() - t_start)
            if remaining_budget <= 0:
                stop_reason = "repetition_budget_exhausted"
                break
            next_pass = pass_n + 1
            cache_record = cache_precondition_fn(next_pass)
            # P2 (WO §3 finding 3): preconditioning (e.g. warm_repeat
            # reading the corpus) can consume the budget. Recalculate the
            # remaining budget AFTER it and never launch a measurement
            # that overruns the total repetition budget; record the
            # preconditioning attempt on a not-launched pass record.
            remaining_budget = budget_s - (time.monotonic() - t_start)
            if remaining_budget <= 0:
                pending = _build_duration_pass_record(
                    pass_n=next_pass, is_initial=False,
                    timed_out=False, process_rc=None,
                    dist_result=None, dist_result_error=None,
                    wall_s_harness=None,
                    cache_record=cache_record,
                    cleanup=None,
                    output_dir=(os.path.join(out_dir, "duration_passes",
                                             "pass%d" % next_pass)
                                if out_dir else None))
                pending["status"] = "not_launched_budget_exhausted"
                pending["failure_reason"] = (
                    "repetition budget exhausted during cache "
                    "preconditioning")
                pass_records.append(pending)
                stop_reason = "repetition_budget_exhausted"
                break
            if case_timeout_s is not None:
                timeout_s = min(float(case_timeout_s), remaining_budget)
            else:
                timeout_s = remaining_budget
            run = repeat_runner(next_pass, timeout_s)
            pass_n = next_pass
            repeat_runs[pass_n] = run
            dr, dr_err = _parse_dist_result_lines(run.get("stderr"))
            rec = _build_duration_pass_record(
                pass_n=pass_n, is_initial=False,
                timed_out=bool(run.get("timed_out")),
                process_rc=run.get("rc"),
                dist_result=dr, dist_result_error=dr_err,
                wall_s_harness=run.get("wall_s"),
                cache_record=cache_record,
                cleanup=run.get("cleanup"),
                output_dir=(os.path.join(out_dir, "duration_passes", "pass%d" % pass_n)
                            if out_dir else None))
            pass_records.append(rec)
            if rec["timed_out"]:
                stop_reason = "pass_timeout"
                break
            if not rec["qualified"]:
                stop_reason = "pass_execution_failure"
                break
            # P1: a qualified pass contributes duration (the six
            # qualification conditions are met); cache compatibility is a
            # separate composite-validity dimension (P2).
            accumulated += rec["effective_wall_seconds"]
            if rec["cache_compatible"] is False:
                stop_reason = "cache_precondition_incompatibility"
                break
    return pass_records, float(accumulated), stop_reason, repeat_runs


def _build_duration_aggregate(pass_records):
    """AUTHORITATIVE composite-measurement definition (WO §3).

    Contributing passes: duration-contributing passes whose actual cache
    treatment is compatible. Aggregate: T_agg = sum T_i, B_agg = sum B_i,
    throughput_agg = B_agg / T_agg; scanned bytes summed per-pass with
    scan-equals-consumed checked and once across the aggregate; reservations
    summed with explicit aggregate semantics. Aggregate validity requires
    every contributing pass to independently satisfy the performance-
    validity requirements -- invalid or unknown per-pass validity is never
    promoted to a valid aggregate.
    """
    contributing = [p for p in pass_records
                    if p.get("duration_contributes")
                    and p.get("cache_compatible") is not False]
    excluded = [p for p in pass_records
                if p.get("duration_contributes")
                and p.get("cache_compatible") is False]
    agg_wall = float(sum((p.get("engine_wall_seconds") or 0.0)
                         for p in contributing))
    agg_bytes = int(sum((p.get("total_consumed") or 0) for p in contributing))
    agg_res = int(sum((p.get("reservations_total") or 0) for p in contributing))
    agg_scanned = 0
    scan_ok_all = True
    for p in contributing:
        if p.get("scan_equals_consumed") is True:
            agg_scanned += int(p.get("total_consumer_bytes_scanned") or 0)
        else:
            scan_ok_all = False
    if not contributing:
        scan_ok_all = None
    throughput = (agg_bytes / agg_wall) if (agg_wall > 0) else None
    reasons = []
    for p in contributing:
        pv = p.get("performance_validity")
        if pv is not True:
            reasons.append("pass %s performance validity=%s"
                           % (p.get("pass"),
                              pv if pv is not None else "unknown"))
        if p.get("cache_compatible") is False:
            reasons.append("pass %s cache preconditioning incompatible"
                           % p.get("pass"))
    if excluded:
        reasons.append("excluded cache-incompatible passes: %s"
                       % [p.get("pass") for p in excluded])
    if scan_ok_all is False:
        reasons.append("aggregate scan does not equal aggregate consumed")
    if not contributing:
        reasons.append("no contributing passes")
    return {
        "contributing_passes": [p.get("pass") for p in contributing],
        "excluded_passes": [{"pass": p.get("pass"),
                             "reason": "cache_precondition_incompatible"}
                            for p in excluded],
        "pass_count": len(contributing),
        "aggregate_engine_wall_seconds": agg_wall,
        "aggregate_consumed_bytes": agg_bytes,
        "aggregate_scanned_bytes": agg_scanned,
        "aggregate_scan_equals_consumed": scan_ok_all,
        "aggregate_reservations": agg_res,
        "aggregate_throughput_bps": throughput,
        "aggregate_valid": (not reasons),
        "aggregate_invalid_reasons": reasons,
    }


def _write_duration_pass_files(pass_dir, pass_record, stdout_text,
                               stderr_text, dist_result):
    """Write pass-level evidence: logs, pass-summary, full DIST_RESULT."""
    try:
        os.makedirs(pass_dir, exist_ok=True)
        with open(os.path.join(pass_dir, "stdout.log"), "w") as fh:
            fh.write(stdout_text or "")
        with open(os.path.join(pass_dir, "stderr.log"), "w") as fh:
            fh.write(stderr_text or "")
        with open(os.path.join(pass_dir, "pass-summary.json"), "w") as fh:
            json.dump(pass_record, fh, indent=2, sort_keys=True, default=str)
        if isinstance(dist_result, dict):
            with open(os.path.join(pass_dir, "dist_result.json"), "w") as fh:
                json.dump(dist_result, fh, indent=2, sort_keys=True)
    except OSError:
        pass


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
    # C3: cache-preconditioning policy (attributable, factual; separate axis).
    manifest["cache_precondition"] = _cache_precondition(spec, resolved)
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    python_dir = python_path or os.path.join(REPO, "python")

    # Experimental distributed-ingest candidates (WO-NUMA-DISTRIBUTED-INGEST).
    # Section 5 comparability: distributed candidates and centralized control
    # run on the same experimental dist_ingest engine, consumer implementation,
    # work units, and measurement boundaries. Production forkrun "control"/absent
    # remains a separate reference path only (not apples-to-apples).
    ingest_candidate = spec.get("ingest_candidate")
    dist_engine_candidates = {
        "fixed_faa", "local_adaptive", "relative_adaptive",
        "centralized_ingest", "centralized",
    }
    use_dist = ingest_candidate in dist_engine_candidates

    script = child_script or CHILD_SCRIPT

    pipe_writer = None
    pipe_reader = None
    pass_fds = ()
    pipe_close_after_spawn = ()
    if spec.get("source_kind") == "pipe" and not use_dist:
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

    if use_dist:
        dist_runner = os.path.join(REPO, "stage0", "dist_ingest", "run_dist.py")
        cmd = [sys.executable, dist_runner,
               "--candidate", ingest_candidate,
               "--input", resolved.get("input", spec.get("input", "")),
               "--nodes", str(spec.get("dist_nodes", spec.get("nodes", 2) if isinstance(spec.get("nodes"), int) else 2)),
               "--base-quantum", str(spec.get("base_quantum", 2 * 1024 * 1024)),
               "--max-backlog", str(spec.get("max_backlog", 64 * 1024 * 1024)),
               "--relative-rounding", str(spec.get("relative_rounding", 1)),
               "--consumer-mode", str(spec.get("consumer_mode", "fast")),
               "--consumer-bps", str(spec.get("consumer_bps", 0)),
               "--consumer-stall-ms", str(spec.get("consumer_stall_ms", 0))]
        if spec.get("max_reservation"):
            cmd += ["--max-reservation", str(spec.get("max_reservation"))]
        if spec.get("local_max_claim_quanta"):
            cmd += ["--local-max-claim-quanta", str(spec.get("local_max_claim_quanta"))]
        if spec.get("rel_max_claim_quanta"):
            cmd += ["--rel-max-claim-quanta", str(spec.get("rel_max_claim_quanta"))]
        if spec.get("prefer_hugepage"):
            cmd += ["--prefer-hugepage"]
        if spec.get("phys_nodes"):
            pn = spec.get("phys_nodes")
            if isinstance(pn, (list, tuple)):
                pn = ",".join(str(x) for x in pn)
            cmd += ["--phys-nodes", str(pn)]
        if spec.get("mapping_profile"):
            cmd += ["--mapping-profile", str(spec.get("mapping_profile"))]
        if spec.get("mapping_variant"):
            cmd += ["--mapping-variant", str(spec.get("mapping_variant"))]
        if spec.get("sysfs_root"):
            cmd += ["--sysfs-root", str(spec.get("sysfs_root"))]
        if spec.get("proc_root"):
            cmd += ["--proc-root", str(spec.get("proc_root"))]
        if spec.get("consumer_kernel") is not None:
            cmd += ["--consumer-kernel", str(spec.get("consumer_kernel"))]
        if spec.get("placement_sampling") is not None:
            cmd += ["--placement-sampling", str(spec.get("placement_sampling"))]
        if spec.get("trial_class") is not None:
            cmd += ["--trial-class", str(spec.get("trial_class"))]
        if spec.get("linked_performance_trial") is not None:
            cmd += ["--linked-performance-trial", str(spec.get("linked_performance_trial"))]
        if spec.get("strict_affinity"):
            cmd += ["--strict-affinity"]
        if spec.get("strict_mbind"):
            cmd += ["--strict-mbind"]
        if spec.get("no_pin"):
            cmd += ["--no-pin"]
        if spec.get("slow_node") is not None:
            cmd += ["--slow-node", str(spec.get("slow_node"))]
        if spec.get("slow_mode"):
            cmd += ["--slow-mode", str(spec.get("slow_mode")),
                    "--slow-bps", str(spec.get("slow_bps", 0)),
                    "--slow-stall-ms", str(spec.get("slow_stall_ms", 0))]
        if spec.get("json_out_rel"):
            cmd += ["--json-out", os.path.join(out_dir, spec.get("json_out_rel"))]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True, cwd=REPO)
    else:
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
    # Experimental dist-ingest result payload (stderr)
    for line in (stderr or "").splitlines():
        if line.startswith("DIST_RESULT "):
            try:
                manifest["dist_result"] = json.loads(
                    line[len("DIST_RESULT "):])
            except ValueError:
                manifest["dist_result_error"] = "malformed DIST_RESULT JSON"
    # The child's own timer covers only forkrun.map(); the outer wall
    # also includes the harness's post-run exactness accounting.
    manifest["map_s"] = (manifest.get("child_report") or {}).get(
        "elapsed_s")
    # C3: duration qualification (separate attributable axis; factual).
    # C3-correction-2: qualification accounting fixes (WO-NUMA-ONE-SHOT-
    # RENTAL-PREPARATION-C3-CORRECTIONS-2, P1/P2):
    #  - only qualified passes contribute duration (no harness-wall fallback
    #    for missing engine measurement time);
    #  - failed/timed-out passes contribute nothing;
    #  - repetition has its own wall-clock budget and process-group-aware
    #    lifecycle; per-pass timeout = min(case timeout, remaining budget);
    #  - cache preconditioning is applied per pass (outside the timed
    #    interval) and per-pass outcomes are recorded;
    #  - a composite aggregate (duration_aggregate) is built from
    #    cache-compatible qualified passes only;
    #  - stop reasons distinguish the stopping condition factually.
    dq_target = spec.get("min_duration_seconds")
    if dq_target is None:
        dq_target = spec.get("duration_qualification_seconds")
    try:
        dq_target = float(dq_target) if dq_target is not None else None
    except Exception:
        dq_target = None
        manifest["duration_qualification_error"] = (
            manifest.get("duration_qualification_error")
            or "invalid min_duration_seconds (unparseable)")
    if dq_target is not None and (not math.isfinite(dq_target) or dq_target < 0):
        # Invalid targets are rejected by campaign prevalidation; run_case
        # defends here too: the target is recorded as invalid and never used
        # for qualification.
        manifest["duration_qualification_error"] = (
            manifest.get("duration_qualification_error")
            or "invalid min_duration_seconds (must be finite and >= 0)")
        dq_target = None
    dr_wall = ((manifest.get("dist_result") or {}).get("wall_seconds"))
    try:
        dr_wall = float(dr_wall) if dr_wall is not None else None
    except Exception:
        dr_wall = None
    # Pass-1 record: authoritative qualification from completed-run evidence
    # (process success, not timed out, parseable DIST_RESULT, dist rc
    # success, functional correctness, valid engine wall_seconds). The old
    # `complete` field was constructed before the final incomplete-state
    # determination and defaulted to True; now the pass's actual status
    # comes from _dist_pass_qualified on the authoritative inputs.
    first_pass_record = _build_duration_pass_record(
        pass_n=1, is_initial=True,
        timed_out=bool(timed_out),
        process_rc=manifest.get("returncode"),
        dist_result=manifest.get("dist_result"),
        dist_result_error=manifest.get("dist_result_error"),
        wall_s_harness=float(dt),
        cache_record=manifest["cache_precondition"],
        cleanup={"label": "case-initial", "timed_out": bool(timed_out),
                 "group_gone": (manifest.get("case_group_gone")
                                or {}).get("gone")},
        output_dir=os.path.join(out_dir, "duration_passes", "pass1"))
    dq_passes = [first_pass_record]
    accumulated = float(sum(p["effective_wall_seconds"] for p in dq_passes
                            if p["duration_contributes"]))
    _write_duration_pass_files(first_pass_record["output_dir"],
                               first_pass_record, stdout, stderr,
                               manifest.get("dist_result"))

    # Repetition budget: explicit overall wall-clock budget for the
    # repetition extension; default derived from the target.
    rep_budget_raw = spec.get("min_duration_repetition_budget_s")
    if rep_budget_raw is None and dq_target is not None:
        rep_budget_s = max(30.0, float(dq_target) * 10.0)
    elif rep_budget_raw is None:
        rep_budget_s = 0.0
    else:
        try:
            rep_budget_s = float(rep_budget_raw)
        except Exception:
            rep_budget_s = (max(30.0, float(dq_target) * 10.0)
                            if dq_target is not None else 0.0)
        if not math.isfinite(rep_budget_s) or rep_budget_s < 0:
            rep_budget_s = (max(30.0, float(dq_target) * 10.0)
                            if dq_target is not None else 0.0)
    case_timeout_s = float(timeout)
    repeat_runs = {}
    stop_reason = None
    if dq_target is not None and float(dq_target) > 0:
        # The authoritative loop decides all stop reasons, including
        # initial-pass cache incompatibility (P2 finding 2) and
        # target_reached; see _run_duration_repetition.
        cmd_ok = bool(use_dist and 'cmd' in locals() and cmd)

        def _repeat_runner(pass_n, timeout_s, _cmd=list(cmd) if cmd_ok else None):
            # Real lifecycle runner; `_run_duration_repetition` calls
            # this with (pass_n, timeout_s) positionally.
            return _run_repeat_pass(_cmd, timeout_s)

        def _cache_fn(pass_n):
            # Per-pass preconditioning, applied before each pass runs
            # (outside the timed interval).
            return _cache_precondition(spec, resolved)

        dq_passes, accumulated, stop_reason, repeat_runs = \
            _run_duration_repetition(
                first_pass_record, list(cmd) if cmd_ok else None,
                float(dq_target), rep_budget_s,
                _repeat_runner, _cache_fn, case_timeout_s=case_timeout_s,
                out_dir=out_dir)
        for rec in dq_passes[1:]:
            run = repeat_runs.get(rec["pass"]) or {}
            _write_duration_pass_files(rec["output_dir"], rec,
                                       run.get("stdout", ""),
                                       run.get("stderr", ""),
                                       rec.get("dist_result"))
    dq_repetition_used = len(dq_passes) > 1
    dq_repetition_capped = bool(
        dq_repetition_used and dq_target is not None
        and accumulated < float(dq_target))
    dq_repetition_error = None
    if (dq_target is not None and dq_target > 0
            and accumulated < float(dq_target) and not dq_repetition_used):
        dq_repetition_error = ("repetition unavailable or stopped: %s"
                               % (stop_reason or "unknown"))
    duration_aggregate = _build_duration_aggregate(dq_passes)
    manifest["duration_aggregate"] = duration_aggregate
    manifest["duration_qualification"] = {
        "target_seconds": dq_target,
        "target_repetition_budget_seconds": rep_budget_s if dq_target is not None else None,
        "effective_wall_seconds": float(dq_passes[0]["effective_wall_seconds"]),
        "accumulated_effective_wall_seconds": float(accumulated),
        "wall_seconds_harness": float(dt),
        "wall_seconds_engine_or_map": dr_wall if dr_wall is not None else manifest.get("map_s"),
        "passes": dq_passes,
        "pass_count": len(dq_passes),
        "repetition_used": dq_repetition_used,
        "repetition_capped": dq_repetition_capped,
        "repetition_budget_exhausted": stop_reason == "repetition_budget_exhausted",
        "repetition_error": dq_repetition_error,
        "stop_reason": stop_reason,
        "meets_target": (None if dq_target is None else bool(accumulated >= float(dq_target))),
        "qualified": (None if dq_target is None else bool(accumulated >= float(dq_target))),
        "duration_aggregate": duration_aggregate,
    }
    diag = _parse_diag(stderr)
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
    # DIRECT ingest CPU: authoritative when available. The comm-delta
    # figure above remains as a cross-check because it can miss a short
    # rename or assign a sample's CPU to the wrong name.
    direct = _direct_ingest_cpu(diag, ingest_basis_s)
    direct_ns = direct["cpu_ns"]
    manifest["ingest_cpu_direct_sec"] = (
        round(direct_ns / 1e9, 6) if direct_ns > 0 else None)
    manifest["ingest_cpu_direct_source"] = direct["source"]
    manifest["ingest_phase_s"] = direct["phase_s"]
    manifest["ingest_cpu_direct_basis_cores"] = direct["map_basis_cores"]
    # The direct record covers the ingest PHASE, not the whole map, so
    # its phase duration is the honest denominator for "is this task
    # using about one core while it ingests?". The map-basis figure
    # above is retained as a run-level cross-check.
    manifest["ingest_cpu_phase_cores"] = direct["phase_cores"]
    manifest["ingest_cpu_attribution"] = (
        "direct" if direct_ns > 0 else
        ("comm-sampled" if ingest_found else "unavailable"))
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
    is_dist_engine = (manifest.get("dist_result") is not None) or (spec.get("ingest_candidate") in {
        "fixed_faa", "local_adaptive", "relative_adaptive", "centralized_ingest", "centralized",
    })
    # C3-correction-2 (P1): an unsuccessful initial pass must never be
    # represented as a successful pass; when the dist-engine pass is not
    # qualified, the case is incomplete with a factual reason.
    if is_dist_engine and dq_passes and not dq_passes[0]["qualified"]:
        incomplete.append("duration pass 1 not qualified: %s"
                          % ("; ".join(dq_passes[0]["reasons"]) or "unknown"))
    if is_dist_engine:
        # Section 8: DIST_RESULT is authoritative for experimental dist-engine
        # candidates; do not require fabricated STAGE0_DIAG/STAGE0_FINAL time-series.
        dr = manifest.get("dist_result") or {}
        if "dist_result" not in manifest:
            incomplete.append("missing dist_result")
        else:
            if not dr.get("correct", False):
                incomplete.append("dist_result not correct (functional validity failed)")
    else:
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
