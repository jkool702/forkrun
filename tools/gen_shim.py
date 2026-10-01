#!/usr/bin/env python3
"""W-DEDUP R-D8 ABI gate — generate the shim header from the C source.

Single source: ``python/forkrun/_shim.c`` (the ``fr_py_*`` definitions).
Emits:
  forkrun_shim.h                        — extern declarations (signatures only)
  tools/generated/shim_signatures.json  — name -> {return, args, linkage}
    (the ctypes cross-check table; ``test_shim_abi.py`` diffs live
    bindings against it — the practical equivalent of typechecking the
    Python/C boundary, since ctypes cannot compile-check against C).

Scope guard (work order §3): signatures only — declarations, argument
types, return types, the --check gate. No semantic contracts (which entry
clears worker_last_cnt, which returns 5-on-fatal) — that's the invariant
gate's territory (test_invariant_gate.py §3/§6/§9 probes).

Usage:
  python3 tools/gen_shim.py            # write artifacts in place
  python3 tools/gen_shim.py --check    # verify committed artifacts match
  python3 tools/gen_shim.py --out DIR  # write artifacts under DIR (tests)
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM_SRC = os.path.join(REPO_ROOT, "python", "forkrun", "_shim.c")
GENERATED_DIR = os.path.join(REPO_ROOT, "tools", "generated")

# Robust multi-line definition parser (see DEDUP_DESIGN.md §5):
# - ``[^;()]*`` for args excludes forward declarations (which contain ``;``)
#   and prevents spanning across definitions.
# - ``\\s*`` (not ``\\s+``) between return and name: pointer returns hug
#   the name (``const char *fr_py_version``, ``void *fr_py_get_raw_window``).
_DEF_PAT = re.compile(
    r"^([a-zA-Z_][\w\s\*]*?)\s*\b(fr_py_\w+)\s*\(([^;()]*)\)\s*\{",
    re.M | re.S)


def _norm_ws(s):
    return " ".join(s.split())


def parse_shim(path=SHIM_SRC):
    """Parse fr_py_* definitions. Returns [(return, name, args, linkage)]."""
    with open(path) as fh:
        src = fh.read()
    out = []
    for ret, name, args in _DEF_PAT.findall(src):
        ret_n = _norm_ws(ret)
        args_n = _norm_ws(args)
        linkage = "static" if "static" in ret_n.split() else "extern"
        # Strip the storage-class keyword from the return for the header.
        ret_n = re.sub(r"^static\s+", "", ret_n).strip()
        out.append((ret_n, name, args_n, linkage))
    # Deterministic order: source order is the ABI order (no sorting —
    # reordering is itself an ABI change the gate must catch; the JSON
    # preserves source order, the header follows it).
    seen = set()
    for _, name, _, _ in out:
        if name in seen:
            raise ValueError("duplicate fr_py_ definition: %s" % name)
        seen.add(name)
    return out


def render_header(defs):
    lines = []
    lines.append("/* forkrun_shim.h — W-DEDUP R-D8 ABI gate (signatures only).")
    lines.append(" *")
    lines.append(" * GENERATED FILE — do not edit. Regenerate with:")
    lines.append(" *   python3 tools/gen_shim.py")
    lines.append(" * Single source: python/forkrun/_shim.c (the fr_py_*")
    lines.append(" * definitions). CI enforces `gen_shim.py --check`")
    lines.append(" * (committed output must match).")
    lines.append(" *")
    lines.append(" * Scope: declarations, argument types, return types only.")
    lines.append(" * No semantic contracts (see test_invariant_gate.py §3/§6/§9).")
    lines.append(" * Extern entries are the dlsym-visible ABI surface (45);")
    lines.append(" * static entries are internal (listed with linkage in")
    lines.append(" * shim_signatures.json, omitted here).")
    lines.append(" *")
    lines.append(" * Header hygiene (substrate rules): self-contained (no includes")
    lines.append(" * beyond <stdint.h>, include-guarded, FTM-independent,")
    lines.append(" * order-independent (alphabetical within linkage class).")
    lines.append(" */")
    lines.append("#ifndef FORKRUN_SHIM_H")
    lines.append("#define FORKRUN_SHIM_H")
    lines.append("")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append("/* Opaque forward decls for struct out-params (defined in _shim.c).")
    lines.append(" * The header carries signatures, not layouts — ctypes binds")
    lines.append(" * layouts positionally in _bindings.py (checked by")
    lines.append(" * test_shim_abi.py against shim_signatures.json). */")
    lines.append("typedef struct fr_py_batch fr_py_batch_t;")
    lines.append("typedef struct fr_py_record_desc fr_py_record_desc_t;")
    lines.append("typedef struct FrPyInterval FrPyInterval_t;")
    lines.append("")
    for ret, name, args, linkage in sorted(
            [d for d in defs if d[3] == "extern"], key=lambda d: d[1]):
        lines.append("%s %s(%s);" % (ret, name, args))
    lines.append("")
    lines.append("#endif /* FORKRUN_SHIM_H */")
    lines.append("")
    return "\n".join(lines)


def render_signatures(defs):
    table = {}
    for ret, name, args, linkage in defs:
        table[name] = {"return": ret, "args": args, "linkage": linkage}
    return json.dumps(table, indent=2, sort_keys=True) + "\n"


ARTIFACTS = (
    ("forkrun_shim.h", render_header),
    (os.path.join("tools", "generated", "shim_signatures.json"),
     render_signatures),
)


def generate(out_root):
    defs = parse_shim()
    return {rel: fn(defs) for rel, fn in ARTIFACTS}


def write_all(out_root):
    for rel, content in generate(out_root).items():
        path = rel if os.path.isabs(rel) else os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
        print("wrote %s" % path)


def check():
    rc = 0
    for rel, content in generate(REPO_ROOT).items():
        path = os.path.join(REPO_ROOT, rel)
        try:
            with open(path) as fh:
                committed = fh.read()
        except OSError:
            print("MISSING committed artifact: %s" % rel)
            rc = 1
            continue
        if committed != content:
            print("STALE artifact: %s" % rel)
            for line in difflib.unified_diff(
                    committed.splitlines(), content.splitlines(),
                    "committed/" + rel, "generated/" + rel, lineterm=""):
                print(line)
            rc = 1
        else:
            print("OK %s" % rel)
    return rc


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify committed artifacts match")
    parser.add_argument("--out", default=REPO_ROOT,
                        help="output root (default: repo root)")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    write_all(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
