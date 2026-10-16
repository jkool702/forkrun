#!/usr/bin/env python3
"""Regenerate DOCS/DOCS_ALL.md from its canonical component documents.

WHY THIS EXISTS
---------------
`DOCS_ALL.md` is an AGGREGATE, not a source of truth. Before this script
existed it was maintained by hand, and the only check on it was
`release_check.check_twins`, which compares CHANGELOG HEADINGS against
DOCS_ALL content. That check passed while SIX of the sixteen embedded
documents were stale by roughly 130 lines — including a README section
missing 47 lines and a RESILIENCE_PROTOCOL missing 71. A heading check
cannot see a body that was rewritten underneath it.

This script makes the aggregate reproducible, so "stale" becomes a
detectable state rather than an invisible one.

CONTRACT
--------
* Output is a pure function of the ordered component documents. Nothing
  in DOCS_ALL.md is authored here; every byte traces to a source file.
* Regeneration is idempotent: running it twice produces the same bytes.
* The document list and its order are fixed and explicit below.
* Content that has no source document is a BUG in the source layout, not
  a special case to encode here. One such block existed (W-REL5-B
  behavioral notes, present only in the aggregate) and was moved to
  `PYTHON_BEHAVIOR.md` rather than dropped.

USAGE
-----
    python3 tools/gen_docs_all.py            # write DOCS/DOCS_ALL.md
    python3 tools/gen_docs_all.py --check    # exit 1 if stale

`--check` is wired into `python/release_check.py` and, through it, into
the release gate.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO_ROOT, "DOCS")
TARGET = os.path.join(DOCS_DIR, "DOCS_ALL.md")

# The aggregate's component set, in embed order. Order is part of the
# contract: it is alphabetical by filename, with the exception of
# CHANGELOG.md, which sorts where it does alphabetically (after
# BORN_LOCAL_NUMA.md) and is kept there for continuity with the existing
# file rather than moved to the top.
#
# PYTHON_BEHAVIOR.md was added by this script's introduction, to give
# previously-orphaned content a canonical home. New documents must be
# added HERE or they will not appear in the aggregate — which is the
# point: the list is the contract.
DOCUMENTS = (
    "ARCHITECTURE.md",
    "BORN_LOCAL_NUMA.md",
    "CHANGELOG.md",
    "C_PLUGIN.md",
    "DESIGN.md",
    "ECONOMIC_IMPACT.md",
    "EOF_PROTOCOL.md",
    "FLAGS.md",
    "FORKRUN_OVERVIEW.md",
    "INVARIANTS.md",
    "MAINTAINERS.md",
    "PHYSICS.md",
    "PYTHON_BEHAVIOR.md",
    "README.md",
    "RESILIENCE_PROTOCOL.md",
    "SECURITY.md",
    "SHAPES.md",
)

SEPARATOR = "-" * 41


def _read(name):
    path = os.path.join(DOCS_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().rstrip("\n")


def build():
    """Return the full aggregate text. Pure; no I/O beyond reading."""
    parts = ["\n", SEPARATOR + "\n"]
    for i, name in enumerate(DOCUMENTS):
        if i:
            parts.append("\n" + SEPARATOR + "\n")
        parts.append("# %s\n\n" % name)
        parts.append(_read(name) + "\n")
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify DOCS_ALL.md matches its sources; "
                         "exit 1 when stale")
    args = ap.parse_args(argv)

    generated = build()

    if not args.check:
        with open(TARGET, "w", encoding="utf-8") as fh:
            fh.write(generated)
        print("wrote %s (%d docs, %d bytes)"
              % (os.path.relpath(TARGET, REPO_ROOT), len(DOCUMENTS),
                 len(generated)))
        return 0

    try:
        with open(TARGET, "r", encoding="utf-8") as fh:
            current = fh.read()
    except OSError as exc:
        print("STALE: %s could not be read: %s"
              % (os.path.relpath(TARGET, REPO_ROOT), exc), file=sys.stderr)
        return 1

    if current == generated:
        print("DOCS_ALL.md is current (%d documents)" % len(DOCUMENTS))
        return 0

    cur_lines = current.splitlines()
    gen_lines = generated.splitlines()
    detail = []
    for i in range(max(len(cur_lines), len(gen_lines))):
        a = cur_lines[i] if i < len(cur_lines) else "<EOF>"
        b = gen_lines[i] if i < len(gen_lines) else "<EOF>"
        if a != b:
            detail.append("  line %d:\n    committed: %s\n    generated: %s"
                          % (i + 1, a[:100], b[:100]))
        if len(detail) >= 5:
            break
    print("STALE: %s does not match its source documents.\n"
          "Regenerate: python3 tools/gen_docs_all.py\n%s"
          % (os.path.relpath(TARGET, REPO_ROOT), "\n".join(detail)),
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
