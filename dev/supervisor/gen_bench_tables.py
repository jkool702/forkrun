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
        "B1_minus_A": dv["B1_minus_A_child_startup"],
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
        out.append("| %s | %.2f (%.2f) | %.2f (%.2f) | **%.1f%%** | "
                   "**%.2f ms** [%.2f, %.2f] | %.2f / %.2f |"
                   % (r["name"], r["fork"], r["fork_sd"], r["spawn"],
                      r["spawn_sd"], abs(r["delta"]), r["pd_med"],
                      r["pd_min"], r["pd_max"], r["iso_fork"],
                      r["iso_spawn"]))
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
    out.append("| **B1** | `fork()` → child's pre-exit signal | A, plus the "
               "child's startup path. Excludes teardown | %.2f ms |" % d["B1"])
    out.append("| **B2** | child's own pre-exit clock → reap | **contains** "
               "teardown, plus exit, wakeup, scheduling, reap | %.2f ms |"
               % d["B2"])
    out.append("| **C** | `fork()` + `/dev/null` open + `dup2` + `execve` + "
               "reap | differs from B in more than exec | %.2f ms |" % d["C"])
    out.append("| **D** | `posix_spawn` + reap | no per-page copy "
               "(`CLONE_VM\\|CLONE_VFORK`) | %.2f ms |" % d["D"])
    return "\n".join(out), d


DECISION = os.path.join(_HERE, "CLEANROOM_LAUNCH_DECISION.md")


def check():
    """Fail if the document's figures no longer match the artifacts."""
    doc = open(DECISION).read()
    problems = []
    rows = e2e_rows()
    for r in rows:
        for label, val in (("forkexec", r["fork"]), ("spawn", r["spawn"]),
                           ("paired", r["pd_med"])):
            needle = "%.2f" % val
            if needle not in doc:
                problems.append("%s %s median %s missing from the document"
                                % (r["name"], label, needle))
    d = decomp_rows()
    for k in ("A", "B", "B1", "B2", "C", "D"):
        needle = "%.2f ms" % d[k]
        if needle not in doc:
            problems.append("decomposition %s = %s missing from the document"
                            % (k, needle))
    for k in ("B_minus_A", "B1_minus_A", "C_minus_B", "C_minus_D"):
        needle = "%.2f" % d[k]
        if needle not in doc:
            problems.append("derived %s = %s missing from the document"
                            % (k, needle))
    if problems:
        print("STALE DOCUMENT -- these figures are in the artifacts but not "
              "in the document:")
        for p in problems:
            print("  -", p)
        return 1
    print("document figures match %s and %s"
          % (rows[0]["source"], d["source"]))
    return 0


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