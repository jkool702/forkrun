#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-1 (build portability and
preflight honesty).

Probes the experimental distributed-ingest build and records:
  * mandatory: build of `stage0/libdist_ingest.so` (P1 engine)
  * optional:  Python substrate build (`libstage0.so`), production-reference
               candidate capability, libnuma presence, THP/swap settings

Each probe emits a machine-readable record; warnings identify the
downstream consequence. Exit status is nonzero ONLY for mandatory failures
(the P1 engine build). Output goes to stdout (console summary) and
`--json-out` (machine-readable evidence).
"""
import argparse
import json
import tempfile
import time
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(REPO_ROOT, "stage0", "dist_ingest")
SO_PATH = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")


def _run(cmd, cwd, timeout=600, env=None):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "TIMEOUT")


def _default_isolated_output():
    """A fresh, empty temporary directory; output artifact never pre-exists."""
    import tempfile
    d = tempfile.mkdtemp(prefix="di_preflight_build_")
    return os.path.join(d, "libdist_ingest.so")


def probe_mandatory_engine_build(output_path=None, dist_dir=None, env=None,
                                 make="make", keep_artifact=False):
    """Mandatory CK-1.4 build contract. Returns (ok, details).

    ok requires ALL of:
      1. `make clean` completes successfully (rc==0);
      2. the expected output artifact is ABSENT after a successful clean;
      3. a fresh mandatory build completes successfully (rc==0);
      4. the expected shared library exists after that build;
      5. the resulting artifact was produced by THIS build (absent before;
         created after; mtime not older than build start).

    A pre-existing artifact is never sufficient evidence. Builds are ISOLATED
    (CK-1.2): default output is a fresh temp path; `make clean` removes only
    that output and never a pre-existing `stage0/libdist_ingest.so` or an
    instrumented sanitizer artifact. No sanitizer-environment (LD_PRELOAD /
    ASAN_OPTIONS) exception exists; ordinary preflight contract is never
    weakened. The actual compiler, resolved compiler path/version, build
    command, and flags used are recorded.
    """
    dist = dist_dir or DIST_DIR
    auto_tmp = output_path is None
    if output_path is None:
        output_path = _default_isolated_output()
    output_path = os.path.abspath(output_path)
    # ensure parent directory exists for an explicit isolated destination
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    build_env = dict(os.environ if env is None else env)
    # explicit output for BOTH clean and build
    make_base = [make, "DI_OUTPUT=" + output_path]

    detail = {"output_artifact": output_path, "dist_dir": dist}

    r_clean = _run(make_base + ["clean"], dist, env=build_env)
    if r_clean is None:
        return False, {**detail, "error": "make not found"}
    detail["clean_returncode"] = r_clean.returncode
    detail["clean_stdout_tail"] = (r_clean.stdout or "")[-400:]
    detail["clean_stderr_tail"] = (r_clean.stderr or "")[-400:]

    # (2) expected output artifact ABSENT after a successful clean
    artifact_absent_after_clean = (not os.path.exists(output_path))
    detail["artifact_absent_after_clean"] = artifact_absent_after_clean

    # (3) fresh mandatory build
    t0 = time.time()
    r = _run(make_base, dist, env=build_env)
    if r is None:
        return False, {**detail, "error": "make not found"}
    detail["returncode"] = r.returncode
    detail["stdout_tail"] = (r.stdout or "")[-400:]
    detail["stderr_tail"] = (r.stderr or "")[-400:]
    detail["build_stdout_full"] = (r.stdout or "")[-4000:]
    detail["build_start_epoch"] = t0

    # actual compiler + build command/flags used for the mandatory build:
    # take the compile command echoed by make (ground truth), resolve it on PATH.
    cmd_lines = [ln.strip() for ln in (r.stdout or "").splitlines()
                 if ln.strip() and (ln.strip().split()[0].endswith(("cc", "gcc", "clang"))
                                    or ln.strip().split()[0] == build_env.get("CC", ""))]
    detail["build_commands"] = cmd_lines[-5:]
    cc_from_cmd = cmd_lines[0].split()[0] if cmd_lines else None
    cc_actual = cc_from_cmd or build_env.get("CC") or "cc"
    cc_resolved = shutil.which(cc_actual, path=build_env.get("PATH", os.environ.get("PATH", "")))
    detail["compiler"] = cc_actual
    detail["compiler_resolved_path"] = cc_resolved
    detail["compiler_version_output_head"] = _compiler_version(cc_resolved or cc_actual, build_env)
    # effective flags: Makefile defaults + env overrides actually passed
    detail["cflags"] = build_env.get("CFLAGS", "(Makefile default -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -pthread)")
    detail["ldflags"] = build_env.get("LDFLAGS", "(Makefile default -shared -pthread)")
    detail["cc_env"] = build_env.get("CC")

    # (4) expected shared library exists after build
    built = os.path.exists(output_path)
    detail["artifact_present"] = built
    # (5) produced by THIS build: created after t0 and not pre-existing
    produced_by_this_build = bool(
        artifact_absent_after_clean and built
        and os.path.getmtime(output_path) >= (t0 - 1e-3))
    detail["artifact_produced_by_this_build"] = produced_by_this_build
    try:
        if built:
            import hashlib
            with open(output_path, "rb") as f:
                detail["artifact_sha256"] = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        detail["artifact_sha256"] = None

    ok = bool(
        r_clean.returncode == 0
        and artifact_absent_after_clean
        and r.returncode == 0
        and built
        and produced_by_this_build
    )
    # P2 (CK-1): artifact_retained accuracy. Honor `keep_artifact`.
    # - auto-created temp output + not keep_artifact: artifact REMOVED; retained=null.
    # - explicit output_path or keep_artifact: artifact KEPT; retained=path.
    should_remove = auto_tmp and not keep_artifact
    if should_remove:
        try:
            parent = os.path.dirname(output_path)
            if built:
                os.unlink(output_path)
            if os.path.basename(parent).startswith("di_preflight_build_"):
                os.rmdir(parent)
        except OSError:
            pass
    retained = bool(built and not should_remove)
    detail["artifact_retained"] = (output_path if retained else None)
    detail["artifact_retained_on_disk"] = retained
    return ok, {**detail, "available": ok, "artifact": output_path if retained else None}


def _compiler_version(cc, env):
    if not cc:
        return None
    r = _run([cc, "--version"], "/", 30, env=env)
    return (r.stdout or r.stderr or "")[:300] if r and (r.returncode == 0 or r.stdout or r.stderr) else None


def probe_optional_pynuma_symbols():
    """Probe whether libstage0.so (Python substrate) builds and has the
    residency_shim symbols. Optional: warn, identify the capability lost."""
    result = {"probe": "libstage0.so", "available": False}
    so = os.path.join(REPO_ROOT, "stage0", "libstage0.so")
    if not os.path.exists(so):
        result["warning"] = ("libstage0.so not built; stage0_query_nodes / "
                             "stage0_set_mempolicy / stage0_get_mempolicy / "
                             "stage0_apply_affinity are unavailable (optional; "
                             "stage0_query_nodes via ctypes Python fallback)")
        return result
    try:
        nm = _run(["nm", "-D", so], REPO_ROOT)
        symbols = nm.stdout if nm and nm.returncode == 0 else ""
        result["available"] = bool(symbols)
        result["symbols"] = [s for s in
                             ("stage0_query_nodes", "stage0_set_mempolicy",
                              "stage0_get_mempolicy", "stage0_apply_affinity",
                              "stage0_get_affinity", "stage0_sched_getcpu")
                             if s in symbols]
    except FileNotFoundError:
        result["warning"] = "nm unavailable; libstage0.so present but symbols unverified"
    return result


def probe_optional_production_reference():
    """Optional: production-reference candidate (forkrun). Distinguish from
    the experimental engine — never claim complete candidate coverage."""
    result = {"probe": "production_reference", "available": False}
    try:
        r = subprocess.run([sys.executable, "-c",
                            "import forkrun; print(forkrun.__file__)"],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            result["available"] = True
            result["path"] = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if not result["available"]:
        result["warning"] = ("production reference 'forkrun' not importable; "
                             "downstream consequence: production-reference "
                             "candidates unavailable for this campaign "
                             "(experimental dist_ingest remains the P1 target)")
    return result


def probe_numa_headers():
    """Check numaif.h / linux/mempolicy.h presence and the mbind syscall
    interface used by the engine."""
    result = {"probe": "numa_headers", "numaif_h": False, "mempolicy_h": False,
              "SYS_mbind": False}
    for p in ("/usr/include/numaif.h", "/usr/include/x86_64-linux-gnu/numaif.h"):
        if os.path.exists(p):
            result["numaif_h"] = True
    if os.path.exists("/usr/include/linux/mempolicy.h"):
        result["mempolicy_h"] = True
    r = _run(["grep", "-c", "SYS_mbind\\|__NR_mbind",
              "/usr/include/bits/syscall.h"], "/", 30)
    if r and r.returncode == 0 and r.stdout.strip() != "0":
        result["SYS_mbind"] = True
    # CK-1.4: engine uses the Linux syscall interface (SYS_mbind/__NR_mbind,
    # SYS_move_pages); NO libnuma wrapper fallback exists and libnuma-dev is
    # not required. numaif.h is informational only.
    result["interface"] = "linux-syscall (SYS_mbind/__NR_mbind; SYS_move_pages)"
    result["libnuma_wrapper_fallback"] = False
    if not result["SYS_mbind"]:
        result["note"] = ("SYS_mbind not found in bits/syscall.h on this host; "
                          "engine falls back to __NR_mbind if defined, else mbind "
                          "application returns failure (reported, not silently "
                          "ignored); NOT a libnuma wrapper fallback")
    else:
        result["note"] = ("libnuma-dev optional; engine does not call libnuma "
                          "functions and does not link it")
    return result


def _read(p):
    """Defensive read; explicit None when unavailable. Never fabricate."""
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def _parse_kv(text, key):
    """Parse `Key: value` from /proc/meminfo-style text; None if absent."""
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith(key + ":"):
            parts = line.split(":", 1)[1].split()
            if parts:
                try:
                    return int(parts[0])
                except ValueError:
                    return parts[0]
    return None


def probe_environment():
    """Record actual environment + real probe results. Optional fields that
    are missing/unsupported on this kernel/distribution are explicitly
    None/unavailable — never a fabricated default. Global THP state is kept
    separate from shmem-specific state; configured swap is kept separate
    from active swap I/O."""
    THP = "/sys/kernel/mm/transparent_hugepage"
    # --- shmem-specific THP (actual shmem controls; separate from global) ---
    shmem_enabled = _read(os.path.join(THP, "shmem_enabled"))
    # per-size shmem THP controls where exposed (e.g. hugepages-2048kB/shmem_enabled)
    per_size_shmem = {}
    try:
        for name in sorted(os.listdir(THP)):
            if name.startswith("hugepages-"):
                v = _read(os.path.join(THP, name, "shmem_enabled"))
                if v is not None:
                    per_size_shmem[name] = v
                else:
                    per_size_shmem[name] = None
    except OSError:
        per_size_shmem = None
    meminfo = _read("/proc/meminfo")
    swaps = _read("/proc/swaps")
    vmstat = _read("/proc/vmstat")
    def _vmstat(key):
        if not vmstat:
            return None
        for line in vmstat.splitlines():
            if line.startswith(key + " "):
                try:
                    return int(line.split()[1])
                except (ValueError, IndexError):
                    return None
        return None
    return {
        # actual compiler used for the mandatory build is recorded in
        # preflight.mandatory_engine_build; this is informational PATH scan.
        "compiler_path_scan": _path_compiler_scan(),
        "kernel": os.uname().release if hasattr(os, "uname") else None,
        "arch": os.uname().machine if hasattr(os, "uname") else None,
        "python_version": sys.version,
        "platform": sys.platform,
        "numa_balancing": _read("/proc/sys/kernel/numa_balancing"),
        # global (anonymous) THP state — separate from shmem-specific state
        "thp_enabled": _read(os.path.join(THP, "enabled")),
        "thp_defrag": _read(os.path.join(THP, "defrag")),
        "thp_hpage_pmd_size": _read(os.path.join(THP, "hpage_pmd_size")),
        # shmem-specific THP state (actual shmem control; NOT khugepaged)
        "thp_shmem_enabled": shmem_enabled,
        "thp_shmem_per_size": per_size_shmem,
        "thp_shmem_source": os.path.join(THP, "shmem_enabled"),
        # configured swap (distinct from active swap I/O)
        "swap_configured": swaps,                       # /proc/swaps raw
        "swap_total_kb": _parse_kv(meminfo, "SwapTotal"),
        "swap_free_kb": _parse_kv(meminfo, "SwapFree"),
        "swap_cached_kb": _parse_kv(meminfo, "SwapCached"),  # cached swap pages, NOT active I/O
        # active swap I/O activity (distinct from configured swap)
        "pswpin": _vmstat("pswpin"),                    # pages swapped in
        "pswpout": _vmstat("pswpout"),                  # pages swapped out
        "swap_active_io_source": "/proc/vmstat pswpin/pswpout",
    }


def _path_compiler_scan():
    """Informational: first compiler found in PATH. The ACTUAL compiler used
    for the mandatory build is recorded in mandatory_engine_build."""
    for cc in ("cc", "gcc", "clang"):
        r = _run([cc, "--version"], "/", 30)
        if r and r.returncode == 0:
            return {"compiler": cc, "resolved": shutil.which(cc),
                    "version_output_head": (r.stdout or "")[:300]}
    return {"compiler": None, "warning": "no C compiler found in PATH (cc/gcc/clang)"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-out", default=None,
                    help="Write machine-readable evidence here.")
    args = ap.parse_args()

    probes = {
        "mandatory_engine_build": None,
        "optional_pynuma": probe_optional_pynuma_symbols(),
        "optional_production_reference": probe_optional_production_reference(),
        "numa_headers": probe_numa_headers(),
        "environment": probe_environment(),
    }

    ok, detail = probe_mandatory_engine_build()
    probes["mandatory_engine_build"] = detail

    # Probe optional Python substrate build without failing the run.
    r = _run(["make", "-f", "Makefile.substrate", "python-substrate"], REPO_ROOT, 300)
    sub_ok = bool(r and r.returncode == 0 and
                  os.path.exists(os.path.join(REPO_ROOT, "stage0", "libstage0.so")))
    probes["optional_python_substrate"] = {
        "returncode": r.returncode if r else None,
        "available": sub_ok if r else False,
        "note": "build attempted; failure here is a WARNING, not a preflight failure",
        "warning": (None if sub_ok else
                    "optional Python substrate libstage0.so build failed; "
                    "downstream consequence: stage0 Python-extension substrate "
                    "features unavailable (experimental dist_ingest P1 engine "
                    "unaffected)"),
    }

    status_lines = []
    failures = []
    if not ok:
        failures.append("mandatory_engine_build")
        status_lines.append("FAIL mandatory: dist_ingest engine build failed — see below")
    else:
        status_lines.append("PASS mandatory: libdist_ingest.so built (%s)"
                            % probes["mandatory_engine_build"].get("output_artifact", SO_PATH))

    for key, p in probes.items():
        if not isinstance(p, dict):
            if p is not None and not isinstance(p, bool):
                status_lines.append("INFO: %s=%s" % (key, p))
            continue
        if p.get("available"):
            status_lines.append("PASS/OK: %s available" % key)
        if p.get("warning"):
            status_lines.append("WARN: %s — %s" % (key, p["warning"]))
        # optional capability failures visible with actual downstream consequences
        if key != "mandatory_engine_build" and p.get("available") is False and not p.get("warning"):
            status_lines.append("WARN: %s — optional capability unavailable; "
                                "downstream consequence: features depending on it "
                                "cannot be verified in this campaign" % key)

    print("\n".join(status_lines))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"preflight": probes, "exit_status_expected": 0 if ok else 1},
                      f, indent=2, sort_keys=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
