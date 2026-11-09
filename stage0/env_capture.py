#!/usr/bin/env python3
"""Stage 0 environment + provenance capture (campaign spec §5).

Captures every fact a result can be interpreted against: git state,
kernel/cmdline, CPU+NUMA topology, shmem/THP settings, cgroup limits,
build hashes. Output is a JSON manifest; human summary on stdout.
"""

import argparse
import glob
import hashlib
import json
import os
import platform
import re
import subprocess
import sys


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def git_state(repo):
    def run(*args):
        try:
            return subprocess.run(["git"] + list(args), cwd=repo,
                                  capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    dirty = run("status", "--porcelain") or ""
    return {
        "head_sha": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(dirty),
        "dirty_paths": sorted(dirty.splitlines()),
        "log_1": run("log", "-1", "--format=%H %cs %s"),
    }


def build_hashes(repo):
    out = {}
    for rel in ("python/forkrun/libforkrun_python.so",
                "python/forkrun/_forkrun_cleanroom",
                "python/forkrun/_fr_udf.cpython-314-x86_64-linux-gnu.so",
                "frun.bash"):
        path = os.path.join(repo, rel)
        if os.path.isfile(path):
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return out


def cpu_topology():
    out = {"lscpu": {}, "nodes": {}}
    try:
        proc = subprocess.run(["lscpu", "-p"], capture_output=True,
                              text=True, timeout=30)
        rows = []
        for line in proc.stdout.splitlines():
            if line and not line.startswith("#"):
                rows.append(line.split(","))
        for row in rows:
            if len(row) >= 4:
                out.setdefault("cpus", []).append(
                    {"cpu": int(row[0]), "node": int(row[3]),
                     "core": row[1], "socket": row[2]})
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc = subprocess.run(["lscpu"], capture_output=True, text=True,
                              timeout=30)
        for line in proc.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                out["lscpu"][key.strip()] = value.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    node_dir = "/sys/devices/system/node"
    if os.path.isdir(node_dir):
        for name in sorted(os.listdir(node_dir)):
            if not name.startswith("node"):
                continue
            d = os.path.join(node_dir, name)
            if not os.path.isdir(d):
                continue
            cpulist = _read(os.path.join(d, "cpulist"), "")
            meminfo = _read(os.path.join(d, "meminfo"), "")
            stats = _read(os.path.join(d, "numastat"), "")
            out["nodes"][name] = {
                "cpulist": cpulist,
                "meminfo": meminfo[:2000],
                "numastat": stats[:2000],
            }
    return out


def _cpu_extra():
    """Governor + scaling driver, SMT state, and node memory totals."""
    out = {}
    try:
        lscpu = subprocess.run(["lscpu"], capture_output=True, text=True,
                               timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        lscpu = ""
    for line in lscpu.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip() in ("CPU governor", "CPU MHz", "BogoMIPS",
                           "Threads per core", "CPU(s)",
                           "Model name", "CPU max MHz", "CPU min MHz"):
            out.setdefault("lscpu_key", {})[key.strip()] = value.strip()
    governors = set()
    for path in glob.glob("/sys/devices/system/cpu/cpu*/"
                          "cpufreq/scaling_governor"):
        g = _read(path, "")
        if g:
            governors.add(g)
    out["governors"] = sorted(governors) or "unavailable"
    out["smt"] = {"thread_siblings": out.get("lscpu_key", {}).get(
        "Threads per core", "unknown")}
    out["node_memory"] = {}
    for name in ("node0", "node1", "node2", "node3", "node4", "node5"):
        mi = _read("/sys/devices/system/node/%s/meminfo" % name)
        if mi:
            out["node_memory"][name] = mi[:400]
    cfg_path = "/boot/config-%s" % platform.release()
    out["kernel_config"] = {}
    for token in ("CONFIG_PER_VMA_LOCK", "CONFIG_NUMA",
                  "CONFIG_NUMA_EMU", "CONFIG_NUMA_BALANCING"):
        hit = None
        try:
            with open(cfg_path, encoding="ascii",
                      errors="replace") as fh:
                for line in fh:
                    if line.startswith(token):
                        hit = line.strip()
                        break
        except OSError:
            try:
                import gzip
                with gzip.open("/proc/config.gz", "rt",
                               errors="replace") as fh:
                    for line in fh:
                        if line.startswith(token):
                            hit = line.strip()
                            break
            except OSError:
                hit = "unknown/unavailable (no %s, no /proc/config.gz)" \
                    % cfg_path
        out["kernel_config"][token] = hit if hit is not None \
            else "unknown/unavailable"
    try:
        r = subprocess.run(
            ["bash", "-c", ". ./frun.bash; ring_version"],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))),
            env=dict(os.environ))
        out["check_thp_diagnostic"] = (
            r.stdout + r.stderr).strip()[:2000]
    except (OSError, subprocess.SubprocessError):
        out["check_thp_diagnostic"] = "unavailable (ring_version probe)"
    return out


def _process_state():
    """This process's effective CPU affinity and memory policy."""
    out = {}
    try:
        out["affinity"] = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        out["affinity"] = "unknown/unavailable"
    try:
        import ctypes
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "libstage0.so")
        if not os.path.exists(p):
            raise RuntimeError("no shim built")
        lib = ctypes.CDLL(p, use_errno=True)
        lib.stage0_get_mempolicy.restype = ctypes.c_int
        lib.stage0_get_mempolicy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        mode = ctypes.c_int()
        mask = (ctypes.c_ulong * 64)(0)
        rc = lib.stage0_get_mempolicy(ctypes.byref(mode), mask, 64)
        out["mempolicy"] = {"mode": mode.value, "mask": mask[0],
                            "rc": rc}
    except Exception as exc:  # keep provenance honest, never crash it
        out["mempolicy"] = "unknown/unavailable (%s)" % type(exc).__name__
    return out



def _process_state():
    """This process's effective CPU affinity and memory policy."""
    out = {}
    try:
        out["affinity"] = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        out["affinity"] = "unknown/unavailable"
    try:
        import ctypes
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "libstage0.so")
        if not os.path.exists(p):
            raise RuntimeError("no shim built")
        lib = ctypes.CDLL(p, use_errno=True)
        lib.stage0_get_mempolicy.restype = ctypes.c_int
        lib.stage0_get_mempolicy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        mode = ctypes.c_int()
        mask = (ctypes.c_ulong * 64)(0)
        rc = lib.stage0_get_mempolicy(ctypes.byref(mode), mask, 64)
        out["mempolicy"] = {"mode": mode.value, "mask": mask[0],
                            "rc": rc}
    except Exception as exc:  # keep provenance honest, never crash it
        out["mempolicy"] = "unknown/unavailable (%s)" % type(exc).__name__
    return out


def env_manifest(repo, extra=None):
    cmdline = _read("/proc/cmdline", "")
    m = re.search(r"numa=fake=\d+", cmdline)
    manifest = {
        "git": git_state(repo),
        "build_hashes": build_hashes(repo),
        "kernel": {"release": platform.release(),
                   "version": platform.version(),
                   "machine": platform.machine(),
                   "uname": platform.uname()._asdict(),
                   "cmdline": cmdline,
                   "fake_numa": bool(m),
                   "fake_numa_spec": m.group(0) if m else None,
                   "uptime": _read("/proc/uptime", "")},
        "cpu_topology": cpu_topology(),
        "cpu_extra": _cpu_extra(),
        "thp": {
            "shmem_enabled": _read(
                "/sys/kernel/mm/transparent_hugepage/shmem_enabled", ""),
            "enabled": _read(
                "/sys/kernel/mm/transparent_hugepage/enabled", ""),
            "per_size": {},
        },
        "python": {"version": platform.python_version(),
                   "executable": sys.executable},
        "cgroup": {
            "cpuset_cpus": _read(
                "/sys/fs/cgroup/cpuset.cpus", None) or _read(
                "/sys/fs/cgroup/cpuset/cpuset.cpus", None),
            "memory_max": _read("/sys/fs/cgroup/memory.max", None),
            "cpu_max": _read("/sys/fs/cgroup/cpu.max", None),
        },
        "process": _process_state(),
        "load": {"loadavg": _read("/proc/loadavg", "")},
    }
    thp_dir = "/sys/kernel/mm/transparent_hugepage"
    if os.path.isdir(thp_dir):
        for name in sorted(os.listdir(thp_dir)):
            if name.startswith("hugepages-") and name.endswith("kB"):
                val = _read(os.path.join(thp_dir, name, "shmem_enabled"))
                if val is not None:
                    manifest["thp"]["per_size"][name] = val
    if extra:
        manifest["extra"] = extra
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--out", required=True,
                    help="where to write the JSON manifest")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    extra = {"run_id": args.run_id} if args.run_id else None
    manifest = env_manifest(args.repo, extra=extra)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    topo = manifest["cpu_topology"]
    print("git: %(branch)s @ %(head_sha)s dirty=%(dirty)s" % manifest["git"])
    print("fake NUMA: %s (%s)" % (manifest["kernel"]["fake_numa"],
                                   manifest["kernel"]["fake_numa_spec"]))
    print("physical nodes:", list(topo.get("nodes", {})))
    print("shmem THP:", manifest["thp"]["shmem_enabled"])
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
