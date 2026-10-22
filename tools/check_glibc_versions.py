#!/usr/bin/env python3
"""Glibc symbol-version gate for shipped ELF artifacts (WO-COMPAT-03).

Independent of tools/check_canary_versions.py (which checks Bash symbol/export
floors). This checks the glibc floor: the highest GLIBC_* version required
by an artifact's undefined symbols must not exceed the declared floor.

Usage:
    python3 tools/check_glibc_versions.py [--floor 2.38] [artifact ...]
    (default artifacts: ring_loadables/forkrun-libs/*.so plus the local
    python substrate .so when present)

Exit 0 on success, 1 on any failure.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_floor(s):
    m = re.match(r"(\d+)\.(\d+)", s)
    if not m:
        raise argparse.ArgumentTypeError("floor must look like 2.38")
    return (int(m.group(1)), int(m.group(2)))


def _undefined_glibc_versions(artifact):
    """Return (set of (major, minor) GLIBC versions, has_gnu2_tls)."""
    out = subprocess.run(
        ["objdump", "-T", artifact], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("objdump failed on %s: %s" % (artifact, out.stderr[-300:]))
    versions = set()
    gnu2 = False
    for line in out.stdout.splitlines():
        if "*UND*" not in line:
            continue
        for m in re.finditer(r"GLIBC_(\d+)\.(\d+)", line):
            versions.add((int(m.group(1)), int(m.group(2))))
        if "GLIBC_ABI_GNU2_TLS" in line:
            gnu2 = True
    return versions, gnu2


def _arch_of(artifact):
    out = subprocess.run(["file", artifact], capture_output=True, text=True)
    txt = out.stdout
    if "aarch64" in txt:
        return "aarch64"
    if "80386" in txt or "x86-64" in txt:
        return "x86-64"
    if "PowerPC" in txt or "ppc64" in txt:
        return "ppc64le"
    if "IBM S/390" in txt:
        return "s390x"
    if "RISC-V" in txt:
        return "riscv64"
    return "unknown"


def default_artifacts():
    arts = []
    libs = os.path.join(REPO_ROOT, "ring_loadables", "forkrun-libs")
    if os.path.isdir(libs):
        for fn in sorted(os.listdir(libs)):
            if fn.endswith(".so"):
                arts.append(os.path.join(libs, fn))
    local = os.path.join(REPO_ROOT, "python", "forkrun", "libforkrun_python.so")
    if os.path.exists(local):
        arts.append(local)
    return arts


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--floor", type=_parse_floor, default=None,
                    help="declared glibc floor, e.g. 2.28 (default: per-arch "
                         "map: riscv64=2.38, everything else=2.28)")
    ap.add_argument("artifacts", nargs="*", help="ELF artifacts to check")
    args = ap.parse_args(argv)

    arts = args.artifacts or default_artifacts()
    if not arts:
        print("GLIBC-VERSIONS FAIL: no artifacts to check", file=sys.stderr)
        return 1

    PER_ARCH_FLOOR = {"riscv64": (2, 38)}
    DEFAULT_FLOOR = (2, 28)
    failures = []
    for art in arts:
        if not os.path.exists(art):
            failures.append("missing artifact: %s" % art)
            print("FAIL %s: missing" % art)
            continue
        vers, gnu2 = _undefined_glibc_versions(art)
        if not vers:
            print("WARN %s: no GLIBC versioned undefined symbols" % art)
            continue
        need = max(vers)
        arch = _arch_of(art)
        if args.floor is not None:
            floor = args.floor
        else:
            floor = PER_ARCH_FLOOR.get(arch, DEFAULT_FLOOR)
        status = "OK"
        if gnu2:
            status = "FAIL (GLIBC_ABI_GNU2_TLS present)"
            failures.append("%s: carries GLIBC_ABI_GNU2_TLS (D-TLS regression)"
                            % os.path.basename(art))
        if need > floor:
            status = "FAIL (needs %d.%d > floor %d.%d)" % (need[0], need[1],
                                                           floor[0], floor[1])
            failures.append("%s: needs glibc %d.%d, floor is %d.%d"
                            % (os.path.basename(art), need[0], need[1],
                               floor[0], floor[1]))
        print("%-40s arch=%-9s max=GLIBC_%d.%-2d floor=%d.%d %s"
              % (os.path.basename(art), arch, need[0], need[1],
                 floor[0], floor[1], status))

    if failures:
        print("GLIBC-VERSIONS FAIL:", file=sys.stderr)
        for f in failures:
            print("  - %s" % f, file=sys.stderr)
        return 1
    print("GLIBC-VERSIONS green: per-arch floors (riscv64=2.38, others=2.28) "
          "over %d artifact(s)" % len(arts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
