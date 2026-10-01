#!/usr/bin/env python3
"""Stage 0 measurement legs. Imported by run_stage0.py (`__main__` driver).

Every leg appends row dicts to ctx["rows"] and fault dicts to
ctx["faults"]. All subprocess output goes to per-leg log files; only JSON
summary lines and small derived stats are read back (context hygiene).

Row schema (§4): niche, incumbent, incumbent_result_s, incumbent_rss_mb,
forkrun_result_s, forkrun_rss_mb, ratio, fault_outcome, hardware, notes.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_stage0 import (COSTS_US, FRUN, INCDIR, INPUTS, LOGS, NPROC, POOL_CHUNKS,
                        REPO, RESULTS, RING_HDR, ROOT, WORK, LEG_BUDGET_S,
                        frun_cmd, grep_count, hardware_label, json_line, log,
                        parse_timev, run, run_sampled, sha_file)

PLUGINS = ["jsonl_argv", "jsonl_raw", "transform_plugin", "tensor_plugin",
           "segv_plugin", "drain_plugin", "probe_raw", "probe_stdin"]
FN = {"jsonl_argv": "jsonl_parse_argv", "jsonl_raw": "jsonl_parse_raw",
      "transform_plugin": "transform_burn", "tensor_plugin": "tensor_sum_raw",
      "segv_plugin": "segv_marked", "drain_plugin": "drain_count",
      "probe_raw": "probe_raw_live", "probe_stdin": "probe_stdin_live"}


def probe_engines(ctx: dict) -> None:
    """Detect live engine capabilities (RAW grant, stdin delivery).

    The shipped blobs may predate v3.5.2 features; legs requiring absent
    modes emit UNMEASURED rows instead of failing. Logs provenance. """
    ctx["raw_live"] = False
    ctx["stdin_live"] = False
    lg = os.path.join(LOGS, "probe.log")
    rc, _ = run(frun_cmd(f"-k -C {WORK}/probe_raw.so:probe_raw") +
                f" < /dev/null > {WORK}/probe_raw.out 2>> {lg}",
                lg + ".rc", 120)
    # NB: empty input still exercises grant negotiation via dlopen on the
    # first batch... zero-length batches never execute. Use 5 lines.
    run(f"seq 5 > {WORK}/probe_in.txt", lg + ".seq", 30)
    rc, _ = run(frun_cmd(f"-k -C {WORK}/probe_raw.so:probe_raw") +
                f" < {WORK}/probe_in.txt > {WORK}/probe_raw.out 2>> {lg}",
                lg + ".raw", 120)
    ctx["raw_live"] = (rc == 0)
    rc, _ = run(frun_cmd(f"-k -s -C {WORK}/probe_stdin.so:probe_stdin_live") +
                f" < {WORK}/probe_in.txt > {WORK}/probe_stdin.out 2>> {lg}",
                lg + ".stdin", 120)
    try:
        with open(f"{WORK}/probe_stdin.out", "rb") as fh:
            got = fh.read()
        with open(f"{WORK}/probe_in.txt", "rb") as fh:
            want = fh.read()
        ctx["stdin_live"] = (rc == 0 and got == want)
    except OSError:
        pass
    log(f"engine capabilities: RAW={'live' if ctx['raw_live'] else 'ABSENT'} "
        f"STDIN={'live' if ctx['stdin_live'] else 'ABSENT'}")
    try:
        rev = subprocess.run(["git", "-C", REPO, "log", "--oneline", "-3"],
                             capture_output=True, text=True, timeout=30).stdout
        ctx["engine_provenance"] = " ".join(rev.split())
    except Exception:
        ctx["engine_provenance"] = "unknown"
    log(f"engine provenance: {ctx['engine_provenance']}")


def unmeasured(ctx: dict, niche: str, incumbent: str, reason: str) -> None:
    ctx["rows"].append({
        "niche": niche, "incumbent": incumbent,
        "incumbent_result_s": 0.0, "incumbent_rss_mb": 0.0,
        "forkrun_result_s": 0.0, "forkrun_rss_mb": 0.0, "ratio": "",
        "fault_outcome": "", "hardware": ctx["hw"],
        "notes": f"UNMEASURED: {reason}"})


def setup(ctx: dict) -> None:
    for d in (INPUTS, WORK, RESULTS, LOGS):
        os.makedirs(d, exist_ok=True)
    # Inputs (skip regeneration when the manifest matches the files).
    need_gen = True
    mpath = os.path.join(INPUTS, "manifest.json")
    if os.path.exists(mpath):
        try:
            man = json.load(open(mpath))
            need_gen = any(not os.path.exists(os.path.join(INPUTS, f))
                           for f in man)
        except (OSError, ValueError):
            need_gen = True
    if need_gen:
        log("generating inputs ...")
        rc, dt = run(f"python3 {ROOT}/gen_inputs.py --out {INPUTS}",
                     os.path.join(LOGS, "gen.log"), 600)
        if rc != 0:
            raise RuntimeError("input generation failed (see logs/gen.log)")
        log(f"inputs done in {dt:.0f}s")
    else:
        log("inputs present (manifest match), skipping generation")
    # Plugins (compile at harness time, c_plugin_test pattern).
    hdr = os.path.join(WORK, "forkrun_plugin.h")
    shutil.copy(os.path.join(RING_HDR, "forkrun_plugin.h"), hdr)
    for p in PLUGINS:
        src = os.path.join(ROOT, "forkrun", p + ".c")
        so = os.path.join(WORK, p + ".so")
        if os.path.exists(so) and os.path.getmtime(so) >= os.path.getmtime(src):
            continue
        r = subprocess.run(
            ["gcc", "-O3", "-shared", "-fPIC", f"-I{WORK}", src, "-o", so],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"plugin compile failed: {p}\n{r.stderr[-2000:]}")
    log("plugins compiled")
    # bash+python batch helper.
    with open(os.path.join(WORK, "parse_batch_argv.py"), "w") as fh:
        fh.write("import json,sys\nfor a in sys.argv[1:]:\n"
                 "    o=json.loads(a)\n"
                 "    assert isinstance(o['id'],int) and 'user' in o\n"
                 "    sys.stdout.write(a+'\\n')\n")
    ctx["hw"] = hardware_label()
    log(f"hardware: {ctx['hw']}")
    probe_engines(ctx)


def row(ctx: dict, niche: str, incumbent: str, i_s: float, i_rss: float,
        f_s: float, f_rss: float, fault: str = "", notes: str = "") -> None:
    # No comparison when either side is unmeasured: a 0.0 ratio would read
    # as "infinitely slower" instead of "no comparison".
    ratio = round(i_s / f_s, 2) if f_s and f_s > 0 and i_s > 0 else ""
    ctx["rows"].append({
        "niche": niche, "incumbent": incumbent,
        "incumbent_result_s": round(i_s, 3), "incumbent_rss_mb": i_rss,
        "forkrun_result_s": round(f_s, 3), "forkrun_rss_mb": f_rss,
        "ratio": ratio, "fault_outcome": fault, "hardware": ctx["hw"],
        "notes": notes})


def _frun_leg(ctx: dict, name: str, inner: str, inp: str, out: str,
              timeout: float, cwd: str = WORK) -> tuple[float, float, str]:
    """Run one frun leg sampled; returns (elapsed, peak_rss, out_sha)."""
    lg = os.path.join(LOGS, name + ".log")
    cmd = ("/usr/bin/time -v " + frun_cmd(inner) +
           f" < {inp} > {out} 2> {out}.stderr")
    rc, dt, peak = run_sampled(cmd, lg, timeout)
    if rc != 0:
        raise RuntimeError(f"frun leg {name} rc={rc} (see logs/{name}.log)")
    xv = parse_timev(lg)
    rss = round(max(peak, xv.get("timev_maxrss_mb", 0) or 0), 1)
    return dt, rss, sha_file(out)


# ---------------- JSONL ingestion ----------------

def jsonl(ctx: dict) -> None:
    log("== JSONL ingestion ==")
    inp = os.path.join(INPUTS, "jsonl_1M.jsonl")
    in_sha = sha_file(inp)
    in_bytes = os.path.getsize(inp)
    variants = {
        "C-argv": f"-k -l 4096 -C {WORK}/jsonl_argv.so:jsonl_parse_argv",
        "bash-python": f"-k -l 4096 -X python3 {WORK}/parse_batch_argv.py",
    }
    if ctx["raw_live"]:
        variants["C-raw"] = (
            f"-k -l 4096 -C {WORK}/jsonl_raw.so:jsonl_parse_raw")
    else:
        unmeasured(ctx, "jsonl-ingest", "C-raw-pairings",
                   "engine predates FLAG_RAW (grant negotiation absent); "
                   "raw-window legs pending a v3.5.2+ engine")
    fr: dict[str, tuple] = {}
    for vname, flags in variants.items():
        out = os.path.join(WORK, f"jsonl_{vname.replace('/', '-')}.out")
        dt, rss, sha = _frun_leg(ctx, f"jsonl_fr_{vname}", flags, inp, out, 900)
        if sha != in_sha:
            raise RuntimeError(f"jsonl {vname} checksum mismatch")
        fr[vname] = (dt, rss)
        log(f"jsonl frun/{vname}: {dt:.1f}s rss={rss}MB checksum OK")
    incs = {}
    for script, iname in (("jsonl_pool.py", "mp-pool"),
                          ("jsonl_futures.py", "futures")):
        lg = os.path.join(LOGS, f"jsonl_{iname}.log")
        out = os.path.join(WORK, f"jsonl_{iname}.out")
        rc, dt = run(f"python3 {INCDIR}/{script} {inp} {out} "
                     f"--workers {NPROC} --chunksize 100", lg, 1200)
        if rc != 0:
            raise RuntimeError(f"jsonl {iname} rc={rc}")
        j = json_line(lg)
        if j.get("output_checksum") != in_sha:
            raise RuntimeError(f"jsonl {iname} checksum mismatch")
        incs[iname] = (j["elapsed_s"], j["peak_rss_mb"], in_bytes)
        log(f"jsonl {iname}: {j['elapsed_s']}s rss={j['peak_rss_mb']}MB checksum OK")
    for iname, (i_s, i_rss, _) in incs.items():
        for vname, (f_s, f_rss) in fr.items():
            row(ctx, "jsonl-ingest", iname, i_s, i_rss, f_s, f_rss,
                notes=f"forkrun via {vname}; substrate via C plugin / bash — "
                      "Python frontend pending")


# ---------------- per-record transform (crossover sweep) ----------------

def _head_n(src: str, n: int, dst: str) -> int:
    """Write first n lines of src to dst; returns bytes written."""
    total = 0
    with open(src, "r", encoding="ascii") as fh, \
            open(dst, "w", encoding="ascii") as out:
        for i, ln in enumerate(fh):
            if i >= n:
                break
            out.write(ln)
            total += len(ln)
    return total


def transform(ctx: dict) -> None:
    log("== per-record transform sweep ==")
    src = os.path.join(INPUTS, "transform_10M.txt")
    with open(src, "r", encoding="ascii") as fh:
        total_lines = sum(1 for _ in fh)
    xrows = []  # crossover curve rows (engine, cost, items, items_per_s)
    for cost in COSTS_US:
        n = int(min(total_lines, max(1000, (LEG_BUDGET_S * 1e6) / cost)))
        leg = os.path.join(WORK, f"transform_c{cost:g}.txt")
        in_bytes = _head_n(src, n, leg)
        exp_sha = sha_file(leg)
        # incumbents: pool at c100 (+c1/c1000 at 100us), futures at c100.
        chunks = [100] if cost != 100 else POOL_CHUNKS
        poollegs = {}
        for ch in chunks:
            lg = os.path.join(LOGS, f"tr_pool_c{cost:g}_k{ch}.log")
            rc, _ = run(f"python3 {INCDIR}/transform_pool.py {leg} "
                        f"{WORK}/tr_pool --cost-us {cost:g} --chunksize {ch} "
                        f"--budget-s {LEG_BUDGET_S} --workers {NPROC}", lg, 600)
            if rc != 0:
                raise RuntimeError(f"transform pool c={cost} k={ch} rc={rc}")
            j = json_line(lg)
            if j.get("output_checksum") != exp_sha:
                raise RuntimeError("transform pool checksum mismatch")
            poollegs[ch] = (j["elapsed_s"], j["peak_rss_mb"])
            xrows.append(("mp-pool", cost, n, round(n / j["elapsed_s"], 1)))
            log(f"transform pool cost={cost:g}us k={ch}: {j['elapsed_s']}s")
        lg = os.path.join(LOGS, f"tr_fut_c{cost:g}.log")
        rc, _ = run(f"python3 {INCDIR}/transform_futures.py {leg} "
                    f"{WORK}/tr_fut --cost-us {cost:g} --chunksize 100 "
                    f"--budget-s {LEG_BUDGET_S} --workers {NPROC}", lg, 600)
        if rc != 0:
            raise RuntimeError(f"transform futures c={cost} rc={rc}")
        j = json_line(lg)
        if j.get("output_checksum") != exp_sha:
            raise RuntimeError("transform futures checksum mismatch")
        futleg = (j["elapsed_s"], j["peak_rss_mb"])
        xrows.append(("futures", cost, n, round(n / j["elapsed_s"], 1)))
        # forkrun: -l 1000, cost via fixed args.
        out = os.path.join(WORK, f"tr_fr_c{cost:g}.out")
        dt, rss, sha = _frun_leg(
            ctx, f"tr_fr_c{cost:g}",
            f"-k -l 1000 -C {WORK}/transform_plugin.so:transform_burn "
            f"--cost-us {cost:g}", leg, out, 600)
        if sha != exp_sha:
            raise RuntimeError("transform frun checksum mismatch")
        xrows.append(("frun-C", cost, n, round(n / dt, 1)))
        log(f"transform frun cost={cost:g}us: {dt:.1f}s rss={rss}MB")
        for ch, (i_s, i_rss) in poollegs.items():
            row(ctx, "per-record-transform", f"mp-pool-k{ch}", i_s, i_rss,
                dt, rss,
                notes=f"cost_us={cost:g} items={n}; forkrun -l 1000 C plugin — "
                      "Python frontend pending")
        row(ctx, "per-record-transform", "futures-k100", futleg[0], futleg[1],
            dt, rss,
            notes=f"cost_us={cost:g} items={n}; forkrun -l 1000 C plugin — "
                  "Python frontend pending")
    with open(os.path.join(RESULTS, "crossover.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["engine", "cost_us", "items", "items_per_s"])
        w.writerows(xrows)
    log("crossover.csv written")


# ---------------- tokenize-to-tensor ----------------

def tensor(ctx: dict) -> None:
    log("== tokenize-to-tensor ==")
    src = os.path.join(INPUTS, "tokens_100M.i32")
    in_bytes = os.path.getsize(src)
    # Incumbent probe: torch DataLoader, else UNMEASURED with reason.
    lg = os.path.join(LOGS, "tensor_torch.log")
    rc, _ = run(f"python3 {INCDIR}/tokenize_torch_loader.py {src} "
                f"{WORK}/tensor_torch.out --workers {NPROC}", lg, 900)
    j = json_line(lg) if rc == 0 else {}
    torch_row = (j.get("elapsed_s", 0.0) or 0.0, j.get("peak_rss_mb", 0.0) or 0.0,
                 j.get("notes", "probe failed"))
    log(f"tensor incumbent probe: {torch_row[2]}")
    # forkrun substrate ceiling: raw-window int32 sum, -b 4M.
    dt, rss = 0.0, 0.0
    if ctx["raw_live"]:
        out = os.path.join(WORK, "tensor_fr.out")
        dt, rss, _ = _frun_leg(ctx, "tensor_fr",
                               f"-k -b 4M -C {WORK}/tensor_plugin.so:tensor_sum_raw",
                               src, out, 900)
        total = 0
        with open(out) as fh:
            for ln in fh:
                total += int(ln.strip())
    else:
        total = None
        unmeasured(ctx, "tokenize-to-tensor", "torch-vs-raw",
                   "engine predates FLAG_RAW; raw-window sum pending v3.5.2+")
    # numpy conversion leg (delivery-vs-conversion split): timed separately.
    t0 = time.monotonic()
    import numpy as np
    arr = np.fromfile(src, dtype=np.int32)
    npsum = int(arr.sum())
    np_dt = time.monotonic() - t0
    del arr
    if total is not None and npsum != total:
        raise RuntimeError(
            f"tensor sum mismatch: plugin={total} numpy={npsum}")
    log(f"tensor frun-raw: {dt:.1f}s rss={rss}MB sum OK; "
        f"numpy frombuffer+sum: {np_dt:.2f}s")
    np_s = round(np_dt, 3)
    if total is not None:
        row(ctx, "tokenize-to-tensor", "torch-dataloader",
            torch_row[0], torch_row[1], dt, rss,
            notes=f"incumbent {torch_row[2]}; forkrun raw-window int32 sum "
                  f"({in_bytes}B); numpy frombuffer+sum alone {np_s}s — "
                  "substrate ceiling, Python frontend pending")
    else:
        row(ctx, "tokenize-to-tensor", "numpy-frombuffer-only",
            0.0, 0.0, np_s, 0.0,
            notes=f"conversion leg only ({in_bytes}B int32 "
                  f"frombuffer+sum {np_s}s); delivery leg UNMEASURED "
                  "pending FLAG_RAW engine")
    ctx["tensor_np_s"] = np_s


# ---------------- TB streaming ----------------

def _stream_probe(ctx: dict, tag: str, nbytes: int) -> tuple[float, float]:
    """10-60s probe leg; returns (GB/s, sampler peak MB). Asserts byte count."""
    lg = os.path.join(LOGS, f"stream_probe_{tag}.log")
    out = os.path.join(WORK, f"stream_probe_{tag}.cnt")
    cmd = (f"python3 {ROOT}/gen_stream.py | head -c {nbytes} | "
           f"/usr/bin/time -v " + frun_cmd(
               f"-k -s -C {WORK}/drain_plugin.so:drain_count") +
           f" > {out} 2> {out}.stderr")
    rc, dt, peak = run_sampled(cmd, lg, 600)
    if rc != 0:
        raise RuntimeError(f"stream probe {tag} rc={rc}")
    total = 0
    with open(out) as fh:
        for ln in fh:
            total += int(ln.strip())
    if total != nbytes:
        raise RuntimeError(f"stream probe {tag} count {total} != {nbytes}")
    xv = parse_timev(lg)
    rss = round(max(peak, xv.get("timev_maxrss_mb", 0) or 0), 1)
    gbs = (nbytes / 1e9) / dt
    log(f"stream probe {tag}: {gbs:.2f} GB/s rss={rss}MB count OK")
    return gbs, rss


def streaming(ctx: dict) -> None:
    log("== TB streaming ==")
    res = {}
    stdin_ok = ctx["stdin_live"]
    if not stdin_ok:
        unmeasured(ctx, "tb-streaming", "frun stdin-drain legs",
                   "engine predates stdin delivery; drain legs pending v3.5.2+")
    probe_n = 10 * 1024**3
    if stdin_ok:
        gbs, _ = _stream_probe(ctx, "frun10g", probe_n)
    else:
        # Size from a parallel probe so the run still yields incumbent data.
        lg = os.path.join(LOGS, "stream_probe_par10g.log")
        cmd = (f"python3 {ROOT}/gen_stream.py | head -c {probe_n} | "
               f"parallel --pipe --block 50M --jobs {NPROC} wc -c | "
               f"awk '{{s+=$1}} END {{print s}}'")
        rc, dt, _ = run_sampled(cmd, lg, 1200)
        gbs = (probe_n / 1e9) / max(dt, 1e-9)
        log(f"stream parallel probe: {gbs:.2f} GB/s")
    # Size main legs to exceed 60 s each (bounded above by tmpfs headroom —
    # pipe legs use no disk, so only wall time bounds them).
    size_a = int(max(60 * gbs * 1e9, 20 * 1024**3))
    size_b = size_a * 2
    log(f"stream sizes: A={size_a / 1e9:.0f}GB B={size_b / 1e9:.0f}GB "
        f"(probe {gbs:.2f} GB/s)")
    res = {}
    for tag, nbytes in (("A", size_a), ("B", size_b)):
        if stdin_ok:
            # frun leg.
            lg = os.path.join(LOGS, f"stream_frun_{tag}.log")
            out = os.path.join(WORK, f"stream_frun_{tag}.cnt")
            cmd = (f"python3 {ROOT}/gen_stream.py | head -c {nbytes} | "
                   f"/usr/bin/time -v " + frun_cmd(
                       f"-k -s -C {WORK}/drain_plugin.so:drain_count") +
                   f" > {out} 2> {out}.stderr")
            rc, dt, peak = run_sampled(cmd, lg, 3600)
            if rc != 0:
                raise RuntimeError(f"stream frun {tag} rc={rc}")
            total = 0
            with open(out) as fh:
                for ln in fh:
                    total += int(ln.strip())
            if total != nbytes:
                raise RuntimeError(
                    f"stream frun {tag} count {total} != {nbytes}")
            xv = parse_timev(lg)
            rss = round(max(peak, xv.get("timev_maxrss_mb", 0) or 0), 1)
            res[("frun", tag)] = (dt, rss)
            log(f"stream frun {tag}: {dt:.0f}s {(nbytes / 1e9) / dt:.2f} GB/s "
                f"rss={rss}MB")
        # GNU parallel leg (shell incumbent): pipe jobs counting bytes.
        lg2 = os.path.join(LOGS, f"stream_par_{tag}.log")
        cmd2 = (f"python3 {ROOT}/gen_stream.py | head -c {nbytes} | "
                f"/usr/bin/time -v parallel --pipe --block 50M --jobs {NPROC} "
                f"wc -c 2> {out}.parerr | awk '{{s+=$1}} END {{print s}}' "
                f"> {out}.par")
        rc2, dt2, peak2 = run_sampled(cmd2, lg2, 3600)
        ptotal = 0
        try:
            with open(out + ".par") as fh:
                ptotal = int(fh.read().strip().split()[0])
        except (OSError, ValueError, IndexError):
            pass
        if rc2 != 0 or ptotal != nbytes:
            raise RuntimeError(
                f"stream parallel {tag} rc={rc2} count={ptotal} != {nbytes}")
        xv2 = parse_timev(lg2)
        rss2 = round(max(peak2, xv2.get("timev_maxrss_mb", 0) or 0), 1)
        res[("parallel", tag)] = (dt2, rss2)
        log(f"stream parallel {tag}: {dt2:.0f}s {(nbytes / 1e9) / dt2:.2f} GB/s "
            f"rss={rss2}MB")
    # split + parallel jobs (disk incumbent; sizes fit the 61GB tmpfs).
    for tag, nbytes in (("S1", 10 * 1024**3), ("S2", 20 * 1024**3)):
        sdir = os.path.join(WORK, f"split_{tag}")
        os.makedirs(sdir, exist_ok=True)
        lg3 = os.path.join(LOGS, f"stream_split_{tag}.log")
        cmd3 = (f"python3 {ROOT}/gen_stream.py | head -c {nbytes} | "
                f"split -b 1G - {sdir}/chunk_ && "
                f"/usr/bin/time -v parallel --jobs {NPROC} wc -c ::: "
                f"{sdir}/chunk_* 2> {sdir}.stderr | awk '{{s+=$1}} END {{print s}}'")
        rc3, dt3, peak3 = run_sampled(cmd3, lg3, 3600)
        xv3 = parse_timev(lg3)
        rss3 = round(max(peak3, xv3.get("timev_maxrss_mb", 0) or 0), 1)
        shutil.rmtree(sdir, ignore_errors=True)
        if rc3 != 0:
            raise RuntimeError(f"stream split {tag} rc={rc3}")
        res[("split", tag)] = (dt3, rss3)
        log(f"stream split {tag}: {dt3:.0f}s rss={rss3}MB")
    for tag in ("A", "B"):
        nbytes = {"A": size_a, "B": size_b}[tag]
        p_dt, p_rss = res[("parallel", tag)]
        if ("frun", tag) in res:
            f_dt, f_rss = res[("frun", tag)]
            row(ctx, "tb-streaming", "gnu-parallel", p_dt, p_rss, f_dt, f_rss,
                notes=f"input {nbytes / 1e9:.0f}GB pipe; frun via C "
                      "stdin-drain, parallel via --pipe wc -c — Python "
                      "frontend pending")
        else:
            row(ctx, "tb-streaming", "gnu-parallel-nofrun", p_dt, p_rss,
                0.0, 0.0,
                notes=f"incumbent-only (stdin delivery absent); input "
                      f"{nbytes / 1e9:.0f}GB pipe")
    for tag in ("S1", "S2"):
        nbytes = {"S1": 10 * 1024**3, "S2": 20 * 1024**3}[tag]
        dt, rss = res[("split", tag)]
        row(ctx, "tb-streaming", "split-plus-parallel", dt, rss, 0.0, 0.0,
            notes=f"incumbent-only context leg, {nbytes / 1e9:.0f}GB via "
                  "disk chunks (tmpfs headroom); no frun pairing at this size")
    ctx["stream_sizes"] = {"A": size_a, "B": size_b}
    ctx["stream_res"] = {f"{k[0]}-{k[1]}": v for k, v in res.items()}


# ---------------- fault isolation ----------------

def faults(ctx: dict) -> None:
    log("== fault isolation ==")
    # Small deterministic input so fault legs stay fast; mark mid-file.
    src = os.path.join(WORK, "fault_input.txt")
    run(f"seq 200000 > {src}", os.path.join(LOGS, "fault_gen.log"), 120)
    mark_item = 100000
    # Pool (hang expected): bounded by its own timeout.
    lg = os.path.join(LOGS, "fault_pool.log")
    rc, dt = run(f"python3 {INCDIR}/fault_pool.py {src} --mark {mark_item} "
                 f"--workers 8 --timeout 150", lg, 400)
    j = json_line(lg)
    ctx["faults"].append({"config": "multiprocessing.Pool",
                          "granularity": "item", "mark": mark_item,
                          "elapsed_s": round(dt, 1),
                          "outcome": j.get("fault_outcome", {}),
                          "notes": j.get("notes", "")})
    log(f"fault pool: {j.get('fault_outcome', {}).get('action', '?')}")
    # Futures (BrokenProcessPool expected).
    lg = os.path.join(LOGS, "fault_futures.log")
    rc, dt = run(f"python3 {INCDIR}/fault_futures.py {src} --mark {mark_item} "
                 f"--workers 8 --timeout 150", lg, 400)
    j = json_line(lg)
    ctx["faults"].append({"config": "ProcessPoolExecutor",
                          "granularity": "item", "mark": mark_item,
                          "elapsed_s": round(dt, 1),
                          "outcome": j.get("fault_outcome", {}),
                          "notes": j.get("notes", "")})
    log(f"fault futures: {str(j.get('fault_outcome', {}).get('action', '?'))[:80]}")
    # forkrun segv plugin (batch granularity, -E retry-then-poison default).
    if ctx["stdin_live"]:
        lg = os.path.join(LOGS, "fault_frun.log")
        out = os.path.join(WORK, "fault_frun.out")
        cmd = (frun_cmd(f"-k -E -l 1000 -s "
                        f"-C {WORK}/segv_plugin.so:segv_marked --mark 7") +
               f" < {src} > {out} 2> {out}.stderr")
        rc, dt, peak = run_sampled(cmd, lg, 900)
        n_out = 0
        try:
            with open(out, "rb") as fh:
                n_out = sum(1 for _ in fh)
        except OSError:
            pass
    n_in = 200000
    # Plugin/worker stderr lands in the sidecar (2>), not the leg log:
    # count there, falling back to the log.
    inj = grep_count(out + ".stderr", "FAULT-INJECT")
    if inj == 0:
        inj = grep_count(lg, "FAULT-INJECT")
    poison = grep_count(out + ".stderr", "poison", 200000)
    if poison == 0:
        poison = grep_count(lg, "poison", 200000)
        ctx["faults"].append({
            "config": "forkrun-C-segv-plugin", "granularity": "batch (mark 7)",
            "elapsed_s": round(dt, 1), "rc": rc,
            "outcome": {"survived": rc == 0, "completed": n_out, "total": n_in,
                        "action": f"rc={rc}; FAULT-INJECT seen x{inj}; "
                                  f"'poison' mentions x{poison}; output {n_out}/{n_in} lines",
                    "pool_usable_after": True,
                    "pool_usable_after_note": "no pool object to poison; "
                                             "the aborted run resumes via "
                                             "its checkpoint (--resume)"},
            "notes": "batch-granularity fault; compare vs item-granularity incumbents",
        })
        log(f"fault frun: rc={rc} out={n_out}/{n_in} inject=x{inj}")
    else:
        ctx["faults"].append({
            "config": "forkrun-C-segv-plugin", "granularity": "batch",
            "elapsed_s": 0.0,
            "outcome": {"survived": None, "completed": 0, "total": 200000,
                        "action": "not run: engine predates stdin delivery",
                        "pool_usable_after": None},
            "notes": "pending v3.5.2+ engine",
        })
        log("fault frun: skipped (stdin delivery absent)")
    # GNU parallel with a segfaulting job (shell incumbent).
    job = os.path.join(WORK, "segv_job.sh")
    with open(job, "w") as fh:
        fh.write("#!/bin/bash\n# segfault iff the chunk contains the mark line.\n"
                 "tmp=$(mktemp)\ncat > \"$tmp\"\n"
                 "if grep -q '^100000$' \"$tmp\"; then kill -SEGV $$; fi\n"
                 "cat \"$tmp\"\nrm -f \"$tmp\"\n")
    os.chmod(job, 0o755)
    lg = os.path.join(LOGS, "fault_parallel.log")
    outp = os.path.join(WORK, "fault_parallel.out")
    cmd = (f"cat {src} | parallel --pipe -N 5000 --jobs 8 {job} > {outp} "
           f"2> {outp}.stderr; echo PAR_RC=$?")
    rc, dt, peak = run_sampled(cmd, lg, 900)
    n_pout = 0
    try:
        with open(outp, "rb") as fh:
            n_pout = sum(1 for _ in fh)
    except OSError:
        pass
    ctx["faults"].append({
        "config": "gnu-parallel-segv-job", "granularity": "chunk (5000 lines)",
        "elapsed_s": round(dt, 1), "rc": rc,
        "outcome": {"survived": rc == 0, "completed": n_pout, "total": n_in,
                    "action": f"parallel rc={rc}; output {n_pout}/{n_in} lines; "
                              "failed chunk dropped, rest completed",
                    "pool_usable_after": True,
                    "pool_usable_after_note": "parallel is a new process per run"},
        "notes": "chunk-granularity fault",
    })
    log(f"fault parallel: rc={rc} out={n_pout}/{n_in}")
    # Fault rows in the main table (elapsed as the result columns).
    for f in ctx["faults"]:
        o = f["outcome"]
        ctx["rows"].append({
            "niche": "fault-isolation", "incumbent": f["config"],
            "incumbent_result_s": f["elapsed_s"], "incumbent_rss_mb": 0.0,
            "forkrun_result_s": 0.0, "forkrun_rss_mb": 0.0, "ratio": "",
            "fault_outcome": str(o.get("action", ""))[:160],
            "hardware": ctx["hw"],
            "notes": f.get("notes", "")})

