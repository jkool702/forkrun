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
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(REPO_ROOT, "stage0", "dist_ingest")
SO_PATH = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")


def _run(cmd, cwd, timeout=600):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "TIMEOUT")


def probe_mandatory_engine_build():
    """Build stage0/libdist_ingest.so. Returns (ok, {stderr, stdout})."""
    r = _run(["make", "clean"], DIST_DIR)
    if r is None:
        return False, {"error": "make not found"}
    r = _run(["make"], DIST_DIR)
    if r is None:
        return False, {"error": "make not found"}
    ok = (r.returncode == 0 and os.path.exists(SO_PATH))
    return ok, {"returncode": r.returncode,
                "stdout_tail": (r.stdout or "")[-400:],
                "stderr_tail": (r.stderr or "")[-400:]}


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
    if result["numaif_h"] and not result["SYS_mbind"]:
        result["warning"] = ("numaif.h present but SYS_mbind missing — engine "
                             "uses the mbind() wrapper as fallback")
    elif not result["numaif_h"]:
        result["note"] = ("libnuma-dev absent — engine builds via syscall "
                          "interface only (P1 mandatory path, no optional degradation)")
    return result


def probe_environment():
    """Record compiler, flags, kernel, Python version, arch, platform."""
    def _read(p):
        try:
            return open(p).read().strip()
        except OSError:
            return None
    def _compiler():
        for cc in ("cc", "gcc", "clang"):
            r = _run([cc, "--version"], "/", 30)
            if r and r.returncode == 0:
                return {"compiler": cc,
                        "version_output_head": (r.stdout or "")[:300]}
        return {"compiler": None, "warning": "no C compiler found (cc/gcc/clang)"}
    return {
        "compiler": _compiler(),
        "kernel": os.uname().release if hasattr(os, "uname") else None,
        "arch": os.uname().machine if hasattr(os, "uname") else None,
        "python_version": sys.version,
        "platform": sys.platform,
        "numa_balancing": _read("/proc/sys/kernel/numa_balancing"),
        "thp_enabled": _read("/sys/kernel/mm/transparent_hugepage/enabled"),
        "thp_defrag": _read("/sys/kernel/mm/transparent_hugepage/defrag"),
        "swap_list": _read("/proc/swaps"),
        "sysctl_shmem": _read("/proc/sys/vm/drop_caches"),  # placeholder for VM tuning check
    }


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
    probes["mandatory_engine_build"] = {
        "available": ok, **detail,
        "artifact": SO_PATH if os.path.exists(SO_PATH) else None,
    }

    # Probe optional Python substrate build without failing the run.
    r = _run(["make", "-f", "Makefile.substrate", "python-substrate"], REPO_ROOT, 300)
    probes["optional_python_substrate"] = {
        "returncode": r.returncode if r else None,
        "available": bool(r and r.returncode == 0 and
                          os.path.exists(os.path.join(REPO_ROOT, "stage0", "libstage0.so")))
        if r else False,
        "note": "build attempted; failure here is a WARNING, not a preflight failure",
    }

    status_lines = []
    failures = []
    if not ok:
        failures.append("mandatory_engine_build")
        status_lines.append("FAIL mandatory: dist_ingest engine build failed — see below")
    else:
        status_lines.append("PASS mandatory: libdist_ingest.so built (%s)" % SO_PATH)

    for key, p in probes.items():
        if isinstance(p, dict) and p.get("available"):
            status_lines.append("PASS/OK: %s available" % key)
        elif isinstance(p, dict) and p.get("warning"):
            status_lines.append("WARN: %s — %s" % (key, p["warning"]))
        elif isinstance(p, dict) and p.get("available") is False and p.get("warning"):
            status_lines.append("WARN: %s — %s" % (key, p["warning"]))
        elif p is not None and not isinstance(p, (bool, dict)):
            status_lines.append("INFO: %s=%s" % (key, p))

    print("\n".join(status_lines))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"preflight": probes, "exit_status_expected": 0 if ok else 1},
                      f, indent=2, sort_keys=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
