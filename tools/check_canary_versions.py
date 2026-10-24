#!/usr/bin/env python3
"""W-BASHCOMPAT-BC5: canary version-floor check (signatures only).

Every bash-internal stub in substratestubs.c carries its first-export
bash version (``/* since X.Y */``) or an explicit ``/* unexported: ... */``
boundary marker. This check enforces, against the BUILT artifacts'
undefined symbols (``nm -u``):

- every stub has an annotation (a new stub without one fails);
- no annotation exceeds the floor (single FLOOR constant below);
- every undefined symbol matching a stub name is floor-clean
  (``unexported`` markers are explicit opt-ins for lazy-never-bound
  symbols like array_cell — reviewable, grep-able; W-REL5-D D-STRICT
  retired the add_builtin stub outright).

Non-stub undefined symbols (libc etc.) are out of scope: the canary's
``-Wl,--no-undefined`` link already forces every bash reference to
have a stub, so any bash reference IS a stub name by construction.

Usage:
  python3 tools/check_canary_versions.py [artifact ...]
  (default artifacts: the shipped prebuilts in
  ring_loadables/forkrun-libs/ (required — always in git) plus the
  locally built substrate .so when present (opportunistic — fresh
  checkouts without a build step stay green).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUBS = os.environ.get(
    "FORKRUN_STUBS",
    os.path.join(REPO_ROOT, "substratestubs.c"))

# Ratified floor (W-BASHCOMPAT): bash 4.4.
FLOOR = (4, 4)

_STUB_PAT = re.compile(
    r"^(?:void|int|char|unsigned)\s+\*?(\w+)\s*\(.*?\)\s*"
    r"(?:/\*\s*since\s+(\d+)\.(\d+)\s*\*/"
    r"|\s*/\*\s*unexported:[^*]*\*/)?",
    re.M)


def parse_stubs(path=STUBS):
    """Return {name: (major, minor) | None(marker)}; bare -> ('BARE',)."""
    with open(path) as fh:
        src = fh.read()
    table = {}
    for m in _STUB_PAT.finditer(src):
        name = m.group(1)
        if m.group(2) is not None:
            table[name] = (int(m.group(2)), int(m.group(3)))
        elif m.group(0).rstrip().endswith("*/"):
            table[name] = None  # unexported marker
        else:
            table[name] = ("BARE",)
    return table


def undefined_symbols(artifact):
    # .so files here are stripped: static symtabs are empty, so read
    # the DYNAMIC undefined set (what enable(1) resolves at runtime).
    # .o files keep static symtabs: plain -u. Using -D on an object
    # (or plain -u on a stripped .so) silently yields nothing — the
    # exact false-green this gate exists to prevent.
    args = ["nm", "-D", "-u", artifact] if artifact.endswith(".so") \
        else ["nm", "-u", artifact]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("nm -u failed on %s: %s"
                           % (artifact, out.stderr[-500:]))
    names = set()
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # `nm -u` prints "  U name" (or "w name"); take last token,
        # strip any @version suffix.
        name = line.split()[-1].split("@")[0]
        names.add(name)
    return names


def default_artifacts():
    # The shipped prebuilts are the floor surface that matters (in
    # git, always present). A locally built substrate .so is checked
    # opportunistically (noted, never fatal when absent — fresh
    # checkouts and CI jobs without a build step must stay green).
    cands = []
    libs = os.path.join(REPO_ROOT, "ring_loadables", "forkrun-libs")
    if os.path.isdir(libs):
        for fn in sorted(os.listdir(libs)):
            if fn.endswith(".so"):
                cands.append(os.path.join(libs, fn))
    return cands


def extra_artifacts():
    extra = []
    local = os.path.join(REPO_ROOT, "python", "forkrun",
                         "libforkrun_python.so")
    if os.path.exists(local):
        extra.append(local)
    return extra


def check(artifacts):
    table = parse_stubs()
    failures = []
    bare = sorted(n for n, v in table.items() if v == ("BARE",))
    if bare:
        failures.append("stubs without version annotation: %s"
                        % ", ".join(bare))
    over = sorted("%s(%d.%d)" % (n, v[0], v[1])
                  for n, v in table.items()
                  if isinstance(v, tuple) and len(v) == 2
                  and isinstance(v[0], int) and v > FLOOR)
    if over:
        # Was: "%d.%d" % (FLOOR + tuple(over)). FLOOR is a 2-tuple and
        # `over` is a list of strings, so that concatenation produced a
        # 2+N tuple which then failed to match two numeric specifiers --
        # i.e. the gate raised TypeError instead of reporting the finding
        # it exists to report. A gate that crashes is not a gate: every
        # stub-above-floor finding went unnoticed.
        failures.append("stubs above floor %d.%d: %s"
                        % (FLOOR[0], FLOOR[1], ", ".join(over)))
    if not artifacts:
        failures.append("no artifacts to check")
    for art in artifacts:
        if not os.path.exists(art):
            failures.append("missing artifact: %s" % art)
            continue
        undef = undefined_symbols(art)
        for name in sorted(undef):
            if name not in table:
                continue  # libc etc. — canary link constrains these
            ver = table[name]
            if ver is None:
                print("note: %s: unexported marker (lazy, never bound)"
                      % name)
            elif ver == ("BARE",):
                pass  # reported globally above; don't crash here
            elif ver <= FLOOR:
                pass
            else:
                failures.append(
                    "%s: stub %s is %d.%d, above floor %d.%d"
                    % (art, name, ver[0], ver[1], FLOOR[0], FLOOR[1]))
        print("OK %s (%d undefined, %d stub-matched)" % (
            os.path.relpath(art, REPO_ROOT), len(undef),
            len([n for n in undef if n in table])))
    if failures:
        print("CANARY-VERSIONS FAIL:")
        for f in failures:
            print("  - %s" % f)
        return 1
    print("CANARY-VERSIONS green: floor %d.%d over %d artifact(s)"
          % (FLOOR + (len(artifacts),)))
    return 0


def main(argv):
    arts = [a for a in argv if not a.startswith("-")]
    if not arts:
        arts = default_artifacts()
        for extra in extra_artifacts():
            if extra not in arts:
                print("note: also checking local build %s" %
                      os.path.relpath(extra, REPO_ROOT))
                arts.append(extra)
        if not arts:
            print("CANARY-VERSIONS FAIL:\n  - no artifacts to check")
            return 1
    return check(arts)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
