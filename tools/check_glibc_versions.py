#!/usr/bin/env python3
"""Glibc symbol-version gate for shipped ELF artifacts (WO-COMPAT-03).

Independent of tools/check_canary_versions.py (which checks Bash symbol/export
floors). This checks the glibc floor: the highest GLIBC_* version required
by an artifact's undefined symbols must not exceed the declared floor.

FAIL-CLOSED: every expected artifact must be present; unknown architectures
and artifacts with no versioned GLIBC undefined symbols are failures unless an
explicit, reviewed exception is recorded in PER_ARCH_EXCEPTIONS.

Usage:
    python3 tools/check_glibc_versions.py [--floor 2.28] [artifact ...]
    (default: check the expected shipped artifact set, which is a hard-coded
    manifest; missing entries fail)

Exit 0 on success, 1 on any failure.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Hard-coded manifest of expected shipped artifacts. A missing entry is a
# failure, not a skip. (Architecture -> declared floor.)
EXPECTED_ARTIFACTS = {
    "ring_loadables/forkrun-libs/forkrun_ring.x86-64-v2.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.x86-64-v3.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.x86-64-v4.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.aarch64.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.ppc64le.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.s390x.so": (2, 28),
    "ring_loadables/forkrun-libs/forkrun_ring.riscv64.so": (2, 38),
}

# Explicit, reviewed exceptions: artifact -> (reason). Artifacts listed here
# may have no versioned GLIBC undefined symbols without failing. Currently
# empty: every shipped artifact must carry GLIBC versioned symbols.
EXPLICIT_NO_SYMBOL_EXCEPTIONS = set()


def _parse_floor(s):
    m = re.match(r"(\d+)\.(\d+)", s)
    if not m:
        raise argparse.ArgumentTypeError("floor must look like 2.38")
    return (int(m.group(1)), int(m.group(2)))


def _undefined_glibc_versions(artifact):
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
    if "x86-64" in txt:
        return "x86-64"
    if "PowerPC" in txt or "ppc64" in txt:
        return "ppc64le"
    if "IBM S/390" in txt:
        return "s390x"
    if "RISC-V" in txt:
        return "riscv64"
    return None  # unknown -> fail


def default_artifacts():
    # Fail-closed: every expected artifact must be present.
    arts = []
    for rel in EXPECTED_ARTIFACTS:
        p = os.path.join(REPO_ROOT, rel)
        if not os.path.exists(p):
            arts.append(("MISSING", rel, p))
        else:
            arts.append(("OK", rel, p))
    return arts


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--floor", type=_parse_floor, default=None,
                    help="override floor for ALL artifacts (default: per-arch manifest)")
    ap.add_argument("artifacts", nargs="*", help="ELF artifacts to check")
    args = ap.parse_args(argv)

    failures = []

    # Build the work list.
    if args.artifacts:
        work = [(None, a) for a in args.artifacts]  # (expected_floor or None, path)
    else:
        # Manifest mode: every expected artifact must exist.
        work = []
        for rel, floor in EXPECTED_ARTIFACTS.items():
            p = os.path.join(REPO_ROOT, rel)
            if not os.path.exists(p):
                failures.append("MISSING expected artifact: %s" % rel)
                print("FAIL %s: MISSING" % rel)
            else:
                work.append((floor, p))

    for floor, art in work:
        if floor is None:
            floor = args.floor if args.floor is not None else None
        if not os.path.exists(art):
            failures.append("missing artifact: %s" % art)
            print("FAIL %s: missing" % art)
            continue
        arch = _arch_of(art)
        if arch is None:
            failures.append("%s: unrecognized architecture" % os.path.basename(art))
            print("FAIL %s: unrecognized architecture" % os.path.basename(art))
            continue
        if floor is None:
            # No manifest entry and no --floor: unknown arch floor policy.
            failures.append("%s: no declared floor (pass --floor or use manifest)"
                            % os.path.basename(art))
            print("FAIL %s: no declared floor" % os.path.basename(art))
            continue
        vers, gnu2 = _undefined_glibc_versions(art)
        if not vers:
            if os.path.relpath(art, REPO_ROOT) in EXPLICIT_NO_SYMBOL_EXCEPTIONS:
                print("NOTE %s: no GLIBC versioned symbols (explicit exception)"
                      % os.path.basename(art))
                continue
            failures.append("%s: no versioned GLIBC undefined symbols (not a "
                            "valid ELF gate result)" % os.path.basename(art))
            print("FAIL %s: no versioned GLIBC undefined symbols"
                  % os.path.basename(art))
            continue
        need = max(vers)
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
    print("GLIBC-VERSIONS green: %d artifact(s) checked" % len(work))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY