#!/usr/bin/env python3
"""Stage 3.0 IDL generator — one generation pipeline (v1.3 plan section 2.2).

Reads tools/idl_schema.py (the single source) and emits:
  forkrun_callschema.h          — convention companion table + field lists
  tools/generated/fr_ctypes.py  — Python ctypes mirror (data + type map)
  tools/generated/usage_table.json — usage/doc strings (outputs, not inputs)

v3.5.2 scaffolding: the generator exists, is tested, produces valid output
— but nothing consumes it yet. CI runs `gen_idl.py --check`, which fails
when the committed artifacts differ from generated output (the plan's
"generated artifacts match committed" rule).

Usage:
  python3 tools/gen_idl.py            # write artifacts in place
  python3 tools/gen_idl.py --check    # verify committed artifacts match
  python3 tools/gen_idl.py --out DIR  # write artifacts under DIR (for tests)
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from idl_schema import ARGC_ARGV, BASH_ONLY, SCHEMA, THUNK  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATED_DIR = os.path.join(REPO_ROOT, "tools", "generated")

CONV_C_MACRO = {ARGC_ARGV: "FR_CONV_ARGC_ARGV", THUNK: "FR_CONV_THUNK",
                BASH_ONLY: "FR_CONV_BASH_ONLY"}


def _c_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def render_header():
    lines = []
    lines.append("/* forkrun_callschema.h — Stage 3.0 call-schema (v1.3 section 2.2).")
    lines.append(" *")
    lines.append(" * GENERATED FILE — do not edit. Regenerate with:")
    lines.append(" *   python3 tools/gen_idl.py")
    lines.append(" * Single source: tools/idl_schema.py. CI enforces")
    lines.append(" * `gen_idl.py --check` (committed output must match).")
    lines.append(" *")
    lines.append(" * ANNOTATION-ONLY in v3.5.2: every loadable is ARGC_ARGV")
    lines.append(" * (current string-argv behavior). The convention column exists")
    lines.append(" * so Stage 3 flips are per-function commits (migration order:")
    lines.append(" * ring_claim -> ring_ack -> ring_call -> ring_poll). No thunk")
    lines.append(" * calling, no fr_call_t, no usage-string changes here.")
    lines.append(" *")
    lines.append(" * Companion to FORKRUN_LOADABLES in forkrun_ring.c (which is")
    lines.append(" * frozen and carries no convention column): the schema test")
    lines.append(" * (tools/test_idl.py) enforces name-for-name coverage and")
    lines.append(" * usage/doc equality textually instead.")
    lines.append(" *")
    lines.append(" * Header hygiene (substrate rules): self-contained (no includes),")
    lines.append(" * include-guarded, FTM-independent, order-independent.")
    lines.append(" */")
    lines.append("#ifndef FORKRUN_CALLSCHEMA_H")
    lines.append("#define FORKRUN_CALLSCHEMA_H")
    lines.append("")
    lines.append("/* Calling convention per loadable (Stage 3 flips THUNK). */")
    lines.append("typedef enum fr_convention {")
    lines.append("    FR_CONV_ARGC_ARGV = 0,")
    lines.append("    FR_CONV_THUNK = 1,")
    lines.append("    FR_CONV_BASH_ONLY = 2")
    lines.append("} fr_convention_t;")
    lines.append("")
    lines.append("/* Companion table: X(name, convention). Scaffolding-grade: the")
    lines.append(" * field lists below (FR_FIELDS_<name>, FR_F no-ops until Stage 3")
    lines.append(" * gives them meaning) carry direction/optionality/PTR+LEN for the")
    lines.append(" * migration-order functions only. */")
    lines.append("#define FORKRUN_CALL_SCHEMA(X) \\")
    names = sorted(SCHEMA)
    for i, name in enumerate(names):
        conv = CONV_C_MACRO[SCHEMA[name]["convention"]]
        cont = " \\" if i < len(names) - 1 else ""
        lines.append("    X(%s, %s)%s" % (name, conv, cont))
    lines.append("")
    lines.append("/* Field-descriptor hook: no-op until Stage 3. */")
    lines.append("#define FR_F(dir, type, name, opt)")
    lines.append("")
    for name in names:
        fields = SCHEMA[name]["fields"]
        if not fields:
            continue
        lines.append("/* %s %s */" % (name, SCHEMA[name]["usage"]))
        lines.append("#define FR_NFIELDS_%s %d" % (name, len(fields)))
        lines.append("#define FR_FIELDS_%s \\" % name)
        for j, (direction, ftype, fname, opt) in enumerate(fields):
            cont = " \\" if j < len(fields) - 1 else ""
            lines.append("    FR_F(%s, %s, %s, %d)%s"
                         % (direction, ftype, fname, 1 if opt else 0, cont))
        lines.append("")
    lines.append("#endif /* FORKRUN_CALLSCHEMA_H */")
    lines.append("")
    return "\n".join(lines)


def render_ctypes():
    lines = []
    lines.append('"""Generated ctypes mirror of the call-schema (v3.5.2 scaffolding).')
    lines.append("")
    lines.append("GENERATED FILE — do not edit. Regenerate with:")
    lines.append("  python3 tools/gen_idl.py")
    lines.append("Single source: tools/idl_schema.py.")
    lines.append("")
    lines.append('Nothing consumes this yet (Stage 4 wires the substrate).')
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import ctypes")
    lines.append("")
    lines.append("# Convention tags (mirror fr_convention_t).")
    lines.append('ARGC_ARGV = "ARGC_ARGV"')
    lines.append('THUNK = "THUNK"')
    lines.append('BASH_ONLY = "BASH_ONLY"')
    lines.append("")
    lines.append("# Scalar type map for field descriptors.")
    lines.append("_CTYPE = {")
    lines.append('    "I32": ctypes.c_int32,')
    lines.append('    "U32": ctypes.c_uint32,')
    lines.append('    "U64": ctypes.c_uint64,')
    lines.append('    "U8": ctypes.c_uint8,')
    lines.append('    "STR": ctypes.c_char_p,')
    lines.append('    "PTR": ctypes.c_void_p,')
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def field_ctype(ftype):")
    lines.append('    """Map a schema scalar type to its ctypes type."""')
    lines.append("    return _CTYPE[ftype]")
    lines.append("")
    lines.append("")
    lines.append("# Per-loadable calling convention (all ARGC_ARGV in v3.5.2).")
    lines.append("CONVENTIONS = {")
    for name in sorted(SCHEMA):
        lines.append('    "%s": %s,' % (name, SCHEMA[name]["convention"]))
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("# Per-function field lists: [(direction, type, name, optional)].")
    lines.append("# Only migration-order functions carry fields in v3.5.2.")
    lines.append("FIELDS = {")
    for name in sorted(SCHEMA):
        fields = SCHEMA[name]["fields"]
        if not fields:
            continue
        lines.append('    "%s": [' % name)
        for direction, ftype, fname, opt in fields:
            lines.append('        ("%s", "%s", "%s", %s),'
                         % (direction, ftype, fname, repr(bool(opt))))
        lines.append("    ],")
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("# Usage/doc strings (outputs of the pipeline, not inputs).")
    lines.append("USAGE = {")
    for name in sorted(SCHEMA):
        lines.append('    "%s": %s,' % (name, repr(SCHEMA[name]["usage"])))
    lines.append("}")
    lines.append("DOC = {")
    for name in sorted(SCHEMA):
        lines.append('    "%s": %s,' % (name, repr(SCHEMA[name]["doc"])))
    lines.append("}")
    lines.append("")
    lines.append('__all__ = ["ARGC_ARGV", "THUNK", "BASH_ONLY", "field_ctype",')
    lines.append('           "CONVENTIONS", "FIELDS", "USAGE", "DOC"]')
    lines.append("")
    return "\n".join(lines)


def render_usage_table():
    table = {name: {"usage": SCHEMA[name]["usage"], "doc": SCHEMA[name]["doc"]}
             for name in sorted(SCHEMA)}
    return json.dumps(table, indent=2) + "\n"


ARTIFACTS = (
    ("forkrun_callschema.h", render_header),
    (os.path.join("tools", "generated", "fr_ctypes.py"), render_ctypes),
    (os.path.join("tools", "generated", "usage_table.json"),
     render_usage_table),
)


def generate(out_root):
    """Render all artifacts; return {relpath: content}."""
    return {rel: fn() for rel, fn in ARTIFACTS}


def write_all(out_root):
    for rel, content in generate(out_root).items():
        path = rel if os.path.isabs(rel) else os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
        print("wrote %s" % path)


def check():
    """Verify committed artifacts match generated output. Returns rc."""
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
