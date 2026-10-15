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
import capability_dispatch as dispatch                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
MATRIX = os.path.join(ROOT, "dev", "supervisor",
                      "CLEANROOM_CAPABILITY_MATRIX.md")

AXES = [
    # WO-CM1: "run" is a first-class entry point here. It was absent, and
    # `run()` turns out to have NO cleanroom branch at all, so the matrix
    # was structurally unable to report that.
    ("entry", ("map", "stream", "run")),
    # The EFFECTIVE ingestion decision for stream(). Not a synonym for
    # the entry point: `stream()` only consults the predicate inside its
    # streaming branch, so a materialised source never reaches it.
    ("streaming", (False, True)),
    ("source_kind", oracle.SOURCE_KINDS),
    # P1-3 added mode="udf" (embedded-CPython worker loop, DECISION-01
    # Option A). Without it here the axis undercounts what is actually
    # served: the oracle admits udf but no cell is ever generated for it.
    ("mode", ("plugin", "udf", "python", "spawn", "splice")),
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
    # `resume`/`checkpoint_file` cells reference these by name. Public
    # validation requires the path to EXIST (FileNotFoundError otherwise),
    # so the fixture must be real -- otherwise every resume cell would be
    # invalid for a reason that has nothing to do with the capability
    # under test, and the resume axis would silently measure nothing.
    for _name in ("state.json", "ckpt.json"):
        _p = os.path.join(tmpdir, _name)
        if not os.path.exists(_p):
            with open(_p, "w") as fh:
                fh.write("{}")
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
    """Invoke the predicate exactly as the dispatch sites do.

    `streaming` here is the EFFECTIVE ingestion decision, which is what
    the live sites pass. It is not the same thing as "the caller used
    stream()": stream() over a materialised source passes False, and a
    materialised map() passes False too.
    """
    return _cleanroom_eligible(
        src, f.mode, f.nodes, f.order, f.strict_poison,
        f.orchestrator, f.return_stats,
        streaming=f.streaming,
        resume=f.resume, checkpoint_file=f.checkpoint_file)


def cell_route(f, reached, valid, ok):
    """The route a public call for this cell ACTUALLY takes.

    Derived from the dispatch contract in the oracle, which is why it can
    disagree with `ok`: a cell can satisfy the envelope and never be
    asked about it. tools/capability_dispatch.py observes the live
    branches independently, and the tests assert the two agree.

    Argument order is (facts, reached, valid, ok) and the last two are
    both booleans of different meaning. Swapping them does not raise --
    it silently relabels thousands of valid cells as validation
    rejections, which is exactly what happened once during WO-CM1-R1.
    """
    # An invalid configuration never reaches an executor at all, so it
    # must not be given an execution route. The previous version assigned
    # one anyway, which is why the "all cells" table showed normal
    # execution categories for calls that public validation refuses.
    if not valid:
        return dispatch.VALIDATION_REJECTED
    # Precedence mirrors the live branch order. NUMA is tested BEFORE
    # splice: both map() and stream() take the num_nodes > 1 branch first,
    # so a multi-node splice call is a NUMA route, not a splice one. The
    # old order checked mode == "splice" first and mislabelled it.
    if f.nodes != 1:
        return dispatch.NUMA_PIPELINE
    if f.mode == "splice":
        return dispatch.SPLICE_PIPELINE
    if not reached:
        if f.entry == "run":
            # run() has no cleanroom branch. Recorded as its own category
            # rather than folded into "in-process", because "run() cannot
            # be cleanroom-served" is the single most important fact this
            # audit produced.
            return dispatch.CLEANROOM_UNREACHABLE
        return dispatch.PREDICATE_NOT_CONSULTED
    # The predicate WAS consulted. Serving and declining are different
    # facts and must not share a label.
    return (dispatch.CLEANROOM_SELECTED if ok
            else dispatch.PREDICATE_DECLINED)


def collect():
    """Every cell of the cross product, with its public validity and its
    ACTUAL dispatch route alongside the predicate's answer.

    A cell tuple is (facts, ok, reason, outcome, valid, reached, route).
    The last three are what make this an inventory of implementation
    facts rather than a predicate truth table.
    """
    cells = []
    names = [a for a, _ in AXES]
    with tempfile.TemporaryDirectory() as tmpdir:
        for combo in itertools.product(*[v for _, v in AXES]):
            values = dict(zip(names, combo))
            # `streaming` is INAPPLICABLE to map/run: those entry points
            # have no streaming notion and always pass streaming=False to
            # the predicate, so map(streaming=True) is a configuration no
            # public call can make.
            #
            # SKIP the combination. The previous fix overwrote the value
            # after generating the full cross product, which silently
            # turned map(streaming=True) into a SECOND COPY of
            # map(streaming=False) and counted every map/run cell twice:
            # 60,480 rows containing only 40,320 distinct configurations.
            # Rewriting a generated value is not the same as not
            # generating it.
            if values["entry"] != "stream" and values["streaming"]:
                continue
            f = oracle.Facts(kind="map", **values)
            src = make_source(f.source_kind, tmpdir)
            try:
                ok, reason = call_predicate(f, src)
            finally:
                cleanup_source(f.source_kind, src)
            valid = oracle.public_valid(f)
            reached = oracle.dispatch_reaches_predicate(f)
            cells.append((f, ok, reason, oracle.classify(ok, reason),
                          valid, reached, cell_route(f, reached, valid, ok)))
    # Uniqueness is a property of the GENERATOR, so it is asserted here
    # rather than only in a test: a future axis could reintroduce
    # duplicates and the error would otherwise show up as a plausible
    # count change.
    unique = {c[0] for c in cells}
    if len(unique) != len(cells):
        dupes = len(cells) - len(unique)
        raise AssertionError(
            "capability_matrix generated %d rows for %d distinct "
            "configurations: %d duplicate(s). An axis is being enumerated "
            "where it is inapplicable."
            % (len(cells), len(unique), dupes))
    return cells


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

LONG_CITATIONS = {r[0]: r[4] for r in oracle.RULES}


def render(cells):
    """Render the matrix.

    Reports TWO denominators and refuses to collapse them: the full grid
    (every generated cell) and the public-VALID subset (configurations a
    caller could actually make). The previous document reported only the
    first, which inflated the denominator with configurations that public
    validation rejects before any envelope is consulted.
    """
    total = len(cells)
    valid = [c for c in cells if c[4]]
    nvalid = len(valid)

    def _route_table(rows, title):
        counts = {}
        for c in rows:
            counts.setdefault(c[6], {"n": 0, "example": c[0]})
            counts[c[6]]["n"] += 1
        w2 = []
        w2.append("### %s" % title)
        w2.append("")
        w2.append("| Actual route | Cells | Share |")
        w2.append("|---|---:|---:|")
        for rid, d in sorted(counts.items(), key=lambda kv: -kv[1]["n"]):
            f = d["example"]
            share = 100.0 * d["n"] / len(rows) if rows else 0.0
            w2.append("| `%s` | %d | %.1f%% |" % (rid, d["n"], share))
        w2.append("")
        return w2

    L = []
    w = L.append
    w("# Cleanroom capability matrix")
    w("")
    w("**Generated. Do not edit by hand.** Regenerate with")
    w("`python3 tools/capability_matrix.py`; verify with `--check`.")
    w("")
    w("WO-CM1 rebuilt this. The previous version was a truth table over")
    w("`_cleanroom_eligible()`, which answers only *\"is this envelope")
    w("acceptable?\"* -- never *\"does a public call ever ask?\"* Those")
    w("diverge at the current head in three independent ways, so this")
    w("document now reports the predicate's answer **and** the route the")
    w("public entry point actually takes.")
    w("")
    w("| | |")
    w("|---|---|")
    w("| Cells enumerated | %d |" % total)
    w("| Public-VALID cells | %d (%.1f%% of grid) |"
      % (nvalid, 100.0 * nvalid / total if total else 0.0))
    w("| Cells rejected by public validation | %d |" % (total - nvalid))
    w("| Predicate accepts (of valid) | %d |"
      % sum(1 for c in valid if c[1]))
    w("| **Launcher selected (of valid)** | **%d (%.2f%%)** |"
      % (sum(1 for c in valid if c[6] == dispatch.CLEANROOM_SELECTED),
         100.0 * sum(1 for c in valid
                     if c[6] == dispatch.CLEANROOM_SELECTED) / nvalid
         if nvalid else 0.0))
    w("| Distinct routes | %d |" % len({c[6] for c in cells}))
    w("")
    w("Percentages are against the **public-valid** denominator. The full")
    w("grid includes configurations no public call can make (iterable")
    w("sources, a missing path, a directory, `order=\"sorted\"`); those keep")
    w("their conformance tests and are counted as *validation rejection*,")
    w("never as cleanroom refusals.")
    w("")
    w("---")
    w("")
    w("## Axes")
    w("")
    for name, values in AXES:
        w("- **%s**: %s" % (name, ", ".join("`%r`" % v for v in values)))
    w("")
    w("`entry` and `streaming` are new in WO-CM1. See \"Corrections\" below")
    w("for what they made visible that the old axis set could not.")
    w("")
    w("---")
    w("")
    w("## Actual dispatch route")
    w("")
    L.extend(_route_table(valid, "Public-VALID cells"))
    L.extend(_route_table(cells, "All cells, including invalid ones"))
    w("---")
    w("")
    w("## Corrections this audit made")
    w("")
    w("Each was verified against the live source and, where possible,")
    w("observed directly rather than inferred.")
    w("")
    w("### 1. `run()` is never cleanroom-served")
    w("")
    w("`run()` contains no cleanroom branch at all: 0 calls to")
    w("`_cleanroom_eligible`, 0 evaluations of `_cleanroom_enabled()`. It")
    w("dispatches straight to the NUMA, reactor, or in-process executor.")
    w("The previous matrix never mentioned `run`.")
    w("")
    w("### 2. The predicate was unreachable for most of the grid")
    w("")
    w("`map()` consults it only when the gate is on **and** `raw_mode` is")
    w("in `(plugin, udf, spawn)`. `stream()` only for `(plugin, udf)`. Every")
    w("other mode returns before the predicate is reached, so a cell could")
    w("satisfy the envelope and never be asked about it.")
    w("")
    w("### 3. `stream()` reaches the predicate only when streaming")
    w("")
    w("The call sits inside stream()'s streaming branch, so a materialised")
    w("source never consults it. Observed with a real plugin:")
    w("`stream(..., streaming=True)` selects the launcher; the same call")
    w("with `streaming=None` over a regular file does not.")
    w("")
    w("### 4. Both `map()` and `stream()` bypass the predicate for NUMA")
    w("")
    w("`num_nodes > 1` takes the NUMA path and returns before the")
    w("predicate (run.py:3834 for map, :4254 for stream).")
    w("")
    w("### 5. Duplicate configurations were being counted")
    w("")
    w("The first WO-CM1 pass normalised the inapplicable `streaming`")
    w("value for map/run *after* expanding the Cartesian product, which")
    w("turned `map(streaming=True)` into a second copy of")
    w("`map(streaming=False)`. The grid reported %d rows for %d distinct" % (60480, 40320))
    w("configurations -- every map/run cell counted twice, and every")
    w("headline figure inflated with it. The generator now SKIPS")
    w("inapplicable combinations and asserts uniqueness itself, so the")
    w("error cannot recur silently.")
    w("")
    w("### 6. Public validity is entry-point aware")
    w("")
    w("The first pass called every surviving cell \"public-valid\", which")
    w("overstated the denominator. Verified by calling each entry point:")
    w("")
    w("| Configuration | Observed |")
    w("|---|---|")
    w("| `run(return_stats=True)` | TypeError -- unexpected keyword |")
    w("| `stream(return_stats=True)` | TypeError -- unexpected keyword |")
    w("| `run(mode=\"udf\")` | NotImplementedError: unknown mode |")
    w("| `run(mode=\"splice\")` | ValueError for BOTH payload shapes |")
    w("| `resume=` with a missing path | FileNotFoundError |")
    w("")
    w("`resume`/`checkpoint_file` cells are therefore backed by a real")
    w("fixture file, so the axis measures the capability rather than a")
    w("missing-file error.")
    w("")
    w("### 7. `map()` and `stream()` differ on a missing launcher")
    w("")
    w("`map()` gates only on the predicate and calls the cleanroom")
    w("executor, which resolves the launcher itself and, if absent, warns")
    w("and falls back internally. `stream()` tests launcher availability")
    w("*before* selecting (run.py:4345). So the two are not")
    w("interchangeable on that boundary, and the earlier assumption that")
    w("a missing artifact stops selection was wrong for `map()`.")
    w("")
    w("Invalid configurations were counted against the capability")
    w("denominator. **%d cells were reported as served that no public call"
      % sum(1 for c in cells if c[1] and not c[4]))
    w("could ever make** -- every one of them an iterable source, which")
    w("`_api._reject_iterable_source` rejects before any envelope check.")
    w("")
    w("---")
    w("")
    w("## Predicate outcomes (valid cells only)")
    w("")
    counts = {}
    for c in valid:
        counts.setdefault(c[3], {"n": 0, "reason": c[2]})
        counts[c[3]]["n"] += 1
    w("| Outcome | Cells | Reason fragment |")
    w("|---|---:|---|")
    for oid, d in sorted(counts.items(), key=lambda kv: -kv[1]["n"]):
        w("| `%s` | %d | %s |"
          % (oid, d["n"], (d["reason"] or "")[:58].replace("|", "\\|")))
    w("")
    w("---")
    w("")
    w("## Oracle rules")
    w("")
    w("| Rule | Fires on | Citation |")
    w("|---|---|---|")
    for rule in oracle.RULES:
        name, desc, _test, anchor, cite = rule[0], rule[1], rule[2], rule[3], rule[4]
        fired = sum(1 for c in valid
                    if anchor and c[3] != "SERVED" and anchor in (c[2] or ""))
        w("| `%s` | %s | %s |" % (name, fired, (cite or "")[:60]))
    w("")
    w("---")
    w("")
    w("## Reproducing")
    w("")
    w("```")
    w("python3 tools/capability_matrix.py            # write")
    w("python3 tools/capability_matrix.py --check    # fail if stale")
    w("python3 -m unittest discover -s python/tests -p test_capability_matrix.py")
    w("```")
    w("")
    w("The expected behaviour is not taken from the predicate: it comes")
    w("from `tools/capability_oracle.py`, which imports nothing from")
    w("`forkrun`. The two agreeing is the evidence; neither alone is.")
    w("")
    w("## Limitations not expressible as cell counts")
    w("")
    w("- **Default is OFF.** `FORKRUN_CLEANROOM` is opt-in, so on a default")
    w("  configuration the launcher-selected row above is reachable but")
    w("  not *selected*. Capability and default behaviour are different")
    w("  questions; this table answers the first.")
    w("- **Artifacts are a separate axis.** A missing launcher or an")
    w("  incompatible UDF helper changes the route without changing any")
    w("  cell in this grid; they are tested as boundary conditions, not")
    w("  enumerated.")
    w("- **Fake NUMA is not physical NUMA.** `nodes=\"@N\"` models the")
    w("  multi-node code path only.")
    w("- **Counts are synthetic.** They enumerate a configuration space;")
    w("  they are not an estimate of real-world usage.")
    return "\n".join(L) + "\n"



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
