#!/usr/bin/env python3
"""C0.1 -- generate the cleanroom capability matrix.

The matrix is a DELIVERABLE, not an exercise (roadmap section 4.1): it is
generated from `_cleanroom_eligible()` rather than hand-maintained, so it
cannot drift from the predicate the way a hand-written table would.

    python3 tools/capability_matrix.py            # write the matrix doc
    python3 tools/capability_matrix.py --check    # fail if the doc is stale

The expected-behaviour oracle lives in `tools/capability_oracle.py`, which
imports nothing from forkrun. This module is the half that knows the
predicate; keeping them in separate files is what makes the independence
structural rather than a promise in a comment.
"""

import argparse
import itertools
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "python"))

import capability_oracle as oracle                              # noqa: E402
from forkrun.run import _cleanroom_eligible                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
MATRIX = os.path.join(ROOT, "dev", "supervisor",
                      "CLEANROOM_CAPABILITY_MATRIX.md")

AXES = [
    ("kind", ("map", "stream")),
    ("source_kind", oracle.SOURCE_KINDS),
    ("mode", ("plugin", "python", "spawn", "splice")),
    ("nodes", (1, 2, 4)),
    ("order", ("none", "index", "sorted")),
    ("orchestrator", (True, False)),
    ("strict_poison", (True, False)),
    ("return_stats", (True, False)),
    ("resume", (None, "state.json")),
    ("checkpoint_file", (None, "ckpt.json")),
]


def make_source(kind, tmpdir):
    """Build a real object for each source kind.

    Real objects, not sentinels: the predicate calls os.path.exists and
    os.path.isdir on paths, so a stub would test the stub.
    """
    good = os.path.join(tmpdir, "batches.txt")
    if not os.path.exists(good):
        with open(good, "w") as fh:
            fh.write("0:A\n1:B\n")
    if kind == "path":
        return good
    if kind == "fd":
        return os.open(good, os.O_RDONLY)
    if kind == "fileobj":
        return open(good)
    if kind == "iterable":
        return ["0:A\n", "1:B\n"]
    if kind == "missing":
        return os.path.join(tmpdir, "does-not-exist.txt")
    if kind == "dir":
        return tmpdir
    return object()


def cleanup_source(kind, src):
    if kind == "fd":
        os.close(src)
    elif kind == "fileobj":
        src.close()


def call_predicate(f, src):
    """Invoke the predicate exactly as the dispatch sites do."""
    return _cleanroom_eligible(
        src, f.mode, f.nodes, f.order, f.strict_poison,
        f.orchestrator, f.return_stats,
        streaming=(f.kind == "stream"),
        resume=f.resume, checkpoint_file=f.checkpoint_file)


def collect():
    """Every (facts, ok, reason, outcome) cell of the cross product."""
    cells = []
    names = [a for a, _ in AXES]
    with tempfile.TemporaryDirectory() as tmpdir:
        for combo in itertools.product(*[v for _, v in AXES]):
            f = oracle.Facts(**dict(zip(names, combo)))
            src = make_source(f.source_kind, tmpdir)
            try:
                ok, reason = call_predicate(f, src)
            finally:
                cleanup_source(f.source_kind, src)
            cells.append((f, ok, reason, oracle.classify(ok, reason)))
    return cells


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

LONG_CITATIONS = {r[0]: r[4] for r in oracle.RULES}


def render(cells):
    total = len(cells)
    served = sum(1 for c in cells if c[1])

    # outcome -> count, and a representative cell for each
    outcomes = {}
    for f, ok, reason, oid in cells:
        rec = outcomes.setdefault(oid, {"n": 0, "example": f, "reason": reason})
        rec["n"] += 1

    L = []
    w = L.append
    w("# Cleanroom capability matrix")
    w("")
    w("**Generated. Do not edit by hand.** Regenerate with")
    w("`python3 tools/capability_matrix.py`; verify with `--check`.")
    w("")
    w("Produced by `tools/capability_matrix.py` from the live")
    w("`_cleanroom_eligible` predicate. The expected behaviour is *not* taken")
    w("from the predicate: it comes from `tools/capability_oracle.py`, a module")
    w("that imports nothing from `forkrun`. The two agreeing is the evidence;")
    w("neither alone would be.")
    w("")
    w("| | |")
    w("|---|---|")
    w("| Cells enumerated | %d |" % total)
    w("| Served by the launcher | %d (%.2f%%) |"
      % (served, 100.0 * served / total))
    w("| Declined | %d |" % (total - served))
    w("| Distinct outcomes | %d |" % len(outcomes))
    w("")
    w("---")
    w("")

    # ---- axes
    w("## Axes")
    w("")
    w("The axes are the facts a call carries to the envelope:")
    w("")
    w("| axis | values |")
    w("|---|---|")
    for name, vals in AXES:
        w("| `%s` | %s |" % (name, ", ".join(repr(v) for v in vals)))
    w("")
    w("### Two corrections to the roadmap's axis list")
    w("")
    w("**1. Replayability is not an eligibility axis.** Roadmap section 4.1")
    w("lists `{replayable, non-replayable}` among the envelope axes. It is not")
    w("an input to `_cleanroom_eligible` at all. Replayability is computed in")
    w("the *outcome* contract, after the launcher has run:")
    w("`replayable = pre_ingest or _source_is_reopenable(source)` (run.py:1025)")
    w("and gates `may_fallback`. It answers \"may we fall back?\", not \"may the")
    w("launcher serve this call?\". Conflating the two would make the matrix")
    w("claim to predict something it cannot observe.")
    w("")
    w("**2. `return_stats` is a real axis, and the roadmap omits it.** It is a")
    w("parameter of the predicate and of the dispatch sites. It is a")
    w("**constant axis**: the predicate never consults it, so it always")
    w("serves. It is kept in the matrix anyway, because an axis that is")
    w("currently constant is exactly what a future change would silently")
    w("start varying.")
    w("")

    # ---- outcomes
    w("## Outcomes")
    w("")
    w("Every cell resolves to exactly one of these. There are no others:")
    w("the enumeration produces no `UNCLASSIFIED` cell.")
    w("")
    w("| # | outcome | cells | example |")
    w("|---|---|---|---|")
    for i, (oid, rec) in enumerate(
            sorted(outcomes.items(), key=lambda kv: -kv[1]["n"]), 1):
        f = rec["example"]
        w("| %d | `%s` | %d | `%s` |" % (i, oid, rec["n"], f))
    w("")

    # ---- rules
    w("## The oracle's rules")
    w("")
    w("Evaluated **first-match-wins**. Each is the contract's own words.")
    w("")
    for rid, name, _cond, outcome, cite in oracle.RULES:
        w("- **%s `%s`** &rarr; `%s`  " % (rid, name, outcome))
        w("  %s" % cite)
    w("")

    # ---- precedence
    w("## Precedence")
    w("")
    w("The order of declines is part of the contract: when several conditions")
    w("hold at once, the winner is the message the caller actually sees.")
    w("")
    w("- **R1-R7 precedence is load-bearing.** Several can hold simultaneously")
    w("  (nodes=2 *and* mode=\"python\" *and* orchestrator=False), so reordering")
    w("  these silently changes observable behaviour.")
    w("- **R8-R10 precedence is immaterial.** They classify mutually exclusive")
    w("  source kinds; at most one can hold. Their relative order carries no")
    w("  contract weight.")
    w("")

    # ---- regressions
    w("## Contract points that were historically wrong")
    w("")
    w("These are the assertions carrying the most weight, because each")
    w("corresponds to a defect that actually reached this codebase. A generic")
    w("rule check would not catch a regression in any of them.")
    w("")
    w("| assertion | expected | why it matters |")
    w("|---|---|---|")
    for name, _f, outcome, _rid, why in oracle.REGRESSIONS:
        w("| `%s` | `%s` | %s |" % (name, outcome, why))
    w("")
    w("---")
    w("")
    w("Next: the independent oracle is `tools/capability_oracle.py`; the")
    w("agreement test is `python/tests/test_capability_matrix.py`.")
    w("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed matrix is stale")
    args = ap.parse_args(argv)

    cells = collect()
    text = render(cells)

    if args.check:
        if not os.path.exists(MATRIX):
            print("MISSING: %s" % MATRIX)
            return 1
        with open(MATRIX) as fh:
            have = fh.read()
        if have != text:
            print("STALE: %s differs from the generated matrix" % MATRIX)
            print("  regenerate: python3 tools/capability_matrix.py")
            return 1
        print("OK: %d cells, matrix is current" % len(cells))
        return 0

    os.makedirs(os.path.dirname(MATRIX), exist_ok=True)
    with open(MATRIX, "w") as fh:
        fh.write(text)
    print("wrote %s (%d cells)" % (MATRIX, len(cells)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
