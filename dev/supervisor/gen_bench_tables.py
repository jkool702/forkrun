#!/usr/bin/env python3
"""Generate the F6 benchmark tables in the decision record FROM the artifacts.

Stage 5.1 produced a defect that a reviewer caught and Stage 5.2 must not
repeat: the published §8.1/§8.1b figures did not match the committed raw
artifact, because the numbers had been transcribed from a console during
one run while the artifact on disk came from a later run into the same
path. The two differed by 10%, which is not rounding.

The fix is to stop transcribing. This script READS the committed artifacts
and emits the markdown, so the document cannot disagree with the evidence
by more than the artefact's own numbers.

It also doubles as the check: `tools/check_bench_docs.py` verifies that the
figures currently in the document match the artifacts, and fails if they
have drifted.

Usage:
    python3 dev/supervisor/gen_bench_tables.py --print
    python3 dev/supervisor/gen_bench_tables.py --check
"""

import argparse
import glob
import json
import os
import re
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def latest(pattern):
    # Exclude the per-cell intermediates ("<name>.json.private.json"),
    # which would otherwise sort after the aggregate and be picked instead.
    hits = [h for h in sorted(glob.glob(os.path.join(_HERE, "bench_artifacts",
                                                     pattern)))
            if h.count(".json") == 1]
    if not hits:
        raise SystemExit("no artifact matching %s" % pattern)
    return hits[-1]


def med(xs):
    return round(statistics.median(xs), 2)


def e2e_rows():
    d = json.load(open(latest("cleanroom_backends_*.json")))
    if d.get("void_cells"):
        raise SystemExit("artifact %s is VOID for %s -- refusing to publish"
                         % (d.get("mib"), d["void_cells"]))
    rows = []
    for c in d["cells"]:
        name = ("MAP_PRIVATE" if "PRIVATE" in c["cell"] else "MAP_SHARED")
        f = c["end_to_end"]["forkexec"]
        p = c["end_to_end"]["posix_spawn"]
        rows.append({
            "name": name,
            "fork": f["median"], "fork_sd": f["sd"],
            "spawn": p["median"], "spawn_sd": p["sd"],
            "delta": c["median_delta_pct"],
            "pd_med": c["paired_diff_ms"]["median"],
            "pd_min": c["paired_diff_ms"]["min"],
            "pd_max": c["paired_diff_ms"]["max"],
            "iso_fork": c["isolated_spawn_ms"]["forkexec"],
            "iso_spawn": c["isolated_spawn_ms"]["posix_spawn"],
            "valid": c["valid"],
            "source": os.path.basename(
                latest("cleanroom_backends_*.json")),
        })
    return rows


def decomp_rows():
    d = json.load(open(latest("launch_decomposition_*.json")))
    m = d["measurements_ms"]
    dv = d["derived_ms"]
    return {
        "A": med(m["A_fork_return_no_reap"]),
        "B": med(m["B_fork_exit_reap"]),
        "B1": med(m["B1_fork_to_child_signal"]),
        "B2": med(m["B2_child_pre_exit_to_reap"]),
        "C": med(m["C_fork_devnull_exec_reap"]),
        "D": med(m["D_posix_spawn_reap"]),
        "B_minus_A": dv["B_minus_A_additional_fork_exit_reap_cost"],
        "B1_minus_A": dv["B1_minus_A_latency_difference_NOT_startup"],
        "C_minus_B": dv["C_minus_B_configuration_difference"],
        "C_minus_D": dv["C_minus_D_complete_launch_difference"],
        "source": os.path.basename(
            latest("launch_decomposition_*.json")),
    }


def render_e2e():
    rows = e2e_rows()
    out = []
    out.append("| mapping | fork+execv (sd) | posix_spawn (sd) | median delta "
               "| paired diff median [range] | isolated spawn: fork / spawn |")
    out.append("|---|---|---|---|---|---|")
    for r in rows:
        # The sign is PRESERVED, not taken by absolute value. The artifact
        # stores median_delta_pct as a reduction, i.e. negative when
        # posix_spawn is faster. Printing abs() of it rendered "32.7%" in a
        # column headed "median delta" while the prose said "-32.7%": the
        # same quantity with opposite signs in one document, and under that
        # column heading a positive number reads as a slowdown.
        out.append("| %s | %.2f (%.2f) | %.2f (%.2f) | **%+.1f%%** | "
                   "**%.2f ms** [%.2f, %.2f] | %.2f / %.2f |"
                   % (r["name"], r["fork"], r["fork_sd"], r["spawn"],
                      r["spawn_sd"], r["delta"], r["pd_med"],
                      r["pd_min"], r["pd_max"], r["iso_fork"],
                      r["iso_spawn"]))
    out.append("")
    out.append("Source: `bench_artifacts/%s`." % rows[0]["source"])
    return "\n".join(out), rows


def render_decomp():
    d = decomp_rows()
    out = []
    out.append("| | measurement | timer window contains | median |")
    out.append("|---|---|---|---|")
    out.append("| **A** | `fork()` → parent return | parent-side page-table "
               "copy. **No reap** | %.2f ms |" % d["A"])
    out.append("| **B** | `fork()` + reap, child `_exit()` | A, plus child "
               "startup, teardown, exit, wakeup, scheduling, reap | "
               "%.2f ms |" % d["B"])
    out.append("| **B1** | `fork()` → parent's read of the child's byte | "
               "fork-to-parent-read **latency**; a latency measurement, not "
               "a component — whether the teardown falls inside depends on "
               "scheduling | %.2f ms |" % d["B1"])
    out.append("| **B2** | child's own pre-exit clock → reap | **contains** "
               "teardown, plus exit, wakeup, scheduling, reap | %.2f ms |"
               % d["B2"])
    out.append("| **C** | `fork()` + `/dev/null` open + `dup2` + `execve` + "
               "reap | differs from B in more than exec | %.2f ms |" % d["C"])
    out.append("| **D** | `posix_spawn` + reap | no per-page copy "
               "(`CLONE_VM\\|CLONE_VFORK`) | %.2f ms |" % d["D"])
    out.append("")
    out.append("Derived, with the same care about what each one is:")
    out.append("")
    out.append("* **`B - A` = %.2f ms** — the additional cost of completing "
               "fork-and-exit-and-reap relative to parent-side fork-return "
               "latency. Includes child startup, teardown, exit, wakeup, "
               "scheduling and the reap. **Not a measurement of teardown**, "
               "because `A`'s timer stops before `waitpid()`."
               % d["B_minus_A"])
    out.append("* **`B1 - A` = %.2f ms** — the difference between two "
               "parent-observed latency measurements, fork-to-parent-read "
               "versus fork-return. **Not a measurement of child startup**: "
               "the windows differ by more than startup, and B1's "
               "relationship to teardown is scheduling-dependent."
               % d["B1_minus_A"])
    out.append("* **`C - B` = %.2f ms** — a difference between two complete "
               "timing configurations that differ in more than image "
               "replacement; C's child also opens `/dev/null` and `dup2`s it "
               "onto stdout. Not a pure exec-cost figure." % d["C_minus_B"])
    out.append("* **`C - D` = %.2f ms** — a complete forked launch against a "
               "complete spawned one: a difference of two whole operations, "
               "not of two isolated components." % d["C_minus_D"])
    out.append("")
    out.append("Source: `bench_artifacts/%s`." % d["source"])
    return "\n".join(out), d


DECISION = os.path.join(_HERE, "CLEANROOM_LAUNCH_DECISION.md")

# Header rows that must appear exactly once in the whole document. These are
# matched verbatim, so a duplicate table with even slightly different wording
# is still caught by the region comparison or by a reviewer reading it.
_TABLE_HEADERS = (
    ("| mapping | fork+execv (sd) | posix_spawn (sd) |", "end-to-end"),
    ("| | measurement | timer window contains | median |", "decomposition"),
)

E2E_BEGIN = "<!-- BEGIN GENERATED: bench-e2e -->"
E2E_END = "<!-- END GENERATED: bench-e2e -->"
DECOMP_BEGIN = "<!-- BEGIN GENERATED: bench-decomposition -->"
DECOMP_END = "<!-- END GENERATED: bench-decomposition -->"


def region(doc, begin, end):
    """Return the text between two markers, or None if absent."""
    i = doc.find(begin)
    j = doc.find(end)
    if i < 0 or j < 0 or j < i:
        return None
    return doc[i + len(begin):j].strip()


def check():
    """Compare the GENERATED REGIONS against freshly generated tables.

    Stage 5.2's check searched the whole document for each number. That is
    too weak in two ways, both of which this commit was caught by: it did
    not check the SIGN of a value (so a table showing "32.7%" while the
    prose said "-32.7%" passed), and it did not tie a number to the table
    it belonged to (so a value appearing anywhere in the document
    satisfied it).

    This compares the marked regions byte for byte against what the
    artifacts generate now, which pins value, sign, order and formatting
    together. A hand-edited table, a stale artifact, or a sign flip all
    fail here.
    """
    doc = open(DECISION).read()
    problems = []
    e2e_now, _ = render_e2e()
    dec_now, _ = render_decomp()
    have_e2e = region(doc, E2E_BEGIN, E2E_END)
    have_dec = region(doc, DECOMP_BEGIN, DECOMP_END)
    if have_e2e is None:
        problems.append("the end-to-end table is not marked with %s / %s"
                        % (E2E_BEGIN, E2E_END))
    elif have_e2e != e2e_now.strip():
        problems.append("the end-to-end table does not match the artifact")
        for line in _diff(have_e2e.splitlines(), e2e_now.strip().splitlines()):
            problems.append("    " + line)
    if have_dec is None:
        problems.append("the decomposition table is not marked with %s / %s"
                        % (DECOMP_BEGIN, DECOMP_END))
    elif have_dec != dec_now.strip():
        problems.append("the decomposition table does not match the artifact")
        for line in _diff(have_dec.splitlines(), dec_now.strip().splitlines()):
            problems.append("    " + line)
    # A DUPLICATE benchmark table outside the markers. Comparing the marked
    # regions alone is not enough: an obsolete table left beside a correct
    # generated one passes, and it is free to contradict it. Stage 5.3
    # shipped exactly that -- an unmarked table carrying the previous run's
    # numbers and the withdrawn "excludes teardown" wording, sitting directly
    # above the corrected generated table. A reader comparing the two sees a
    # contradiction, and the check reported the document as clean.
    for header, label in _TABLE_HEADERS:
        n = doc.count(header)
        if n != 1:
            problems.append(
                "expected exactly ONE %s table in the document, found %d. "
                "A duplicate outside the generated markers can contradict "
                "the generated one, and the region comparison below cannot "
                "see it." % (label, n))
    for begin, end, label in ((E2E_BEGIN, E2E_END, "bench-e2e"),
                              (DECOMP_BEGIN, DECOMP_END,
                               "bench-decomposition")):
        if doc.count(begin) != 1 or doc.count(end) != 1:
            problems.append(
                "expected exactly one %s marker pair, found %d begin / %d end"
                % (label, doc.count(begin), doc.count(end)))

    if problems:
        print("STALE, EDITED OR DUPLICATED DOCUMENT:")
        for p in problems:
            print("  -", p)
        return 1
    print("generated tables match the committed artifacts exactly "
          "(value, sign, order and formatting)")
    return 0


def _diff(have, want):
    out = []
    for i in range(max(len(have), len(want))):
        a = have[i] if i < len(have) else "<missing>"
        b = want[i] if i < len(want) else "<extra>"
        if a != b:
            out.append("line %d: document %r != artifact %r" % (i + 1, a, b))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.do_print:
        t1, _ = render_e2e()
        t2, _ = render_decomp()
        print("### END-TO-END (generated)")
        print(t1)
        print()
        print("### DECOMPOSITION (generated)")
        print(t2)
        return 0
    if a.check:
        return check()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())