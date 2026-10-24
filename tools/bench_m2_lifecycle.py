#!/usr/bin/env python3
"""C0.6 — M2 measurement: pre-fork vs post-fork interpreter lifecycle.

    python3 tools/bench_m2_lifecycle.py [--trials N] [--quick]

The roadmap withdrew the earlier preference for pre-fork and requires both
candidates be measured as co-equal, publishing the crossover as a
distribution rather than one row:

> Crossover discovery happens in M2.
> publish crossover as a distribution, not one row.

This drives `fr_udf_fork` — the C0.4 prototype — across the axes the
roadmap names: parent resident size at the moment of fork, worker count,
and THP state. It records PSS/USS alongside RSS, because RSS double-counts
every shared page once per sharer, which is precisely the quantity the
"one interpreter shared, copy-on-write" claim rests on.

It does not reimplement the comparison. `fr_udf_fork` owns both
candidates and the per-child outcome check; this only sweeps it.

Honesty rules enforced here, all of them learned the hard way:

* A run with any child failure is DISCARDED, not averaged in. The driver
  refuses to state a verdict when either arm fails, and so does this.
  The driver also counts protocol integrity faults -- a missing barrier
  ack, a failed release, a report whose version or pid does not match
  the expected child -- and DISCARDS the configuration on any of them,
  because a fleet figure computed from an incomplete barrier is not a
  smaller measurement but a wrong one that prints just as confidently.
* Nothing is compared across differing configurations. Each row is its
  own baseline.
* The interpreter version, THP state and parent RSS are printed with
  every row, because a number without its configuration is not a
  measurement.

Limitation, stated rather than hidden: only the locally available
interpreter is measured. The C0.5 gate names 3.10-3.15 and this run
covers whatever `python3` is, so the matrix is NOT complete and the
crossover below is a single-interpreter result.
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The driver may be built against a DIFFERENT interpreter than the one
# running this harness -- that is the whole point of running the C0.5
# matrix. FR_BENCH_DRIVER selects it.
#
# Without this the harness printed platform.python_version() while
# measuring a driver linked against something else, so a 3.10 sweep
# labelled itself "3.14.7" and its numbers were a 3.14.7 re-run. Same
# class as round 7's launch-vs-in-process mislabelling: the label must
# describe what was measured.
DRIVER = os.environ.get(
    "FR_BENCH_DRIVER",
    os.path.join(_ROOT, "python", "forkrun", "fr_udf_fork"))


def _driver_interpreter():
    """Version the DRIVER reports, not the interpreter running us."""
    import subprocess
    try:
        out = subprocess.run([DRIVER, "--version-probe"],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        # Loudly, not silently: a probe that fails must not look like a
        # probe that succeeded with an unexpected version.
        raise RuntimeError("driver --version-probe failed (rc=%d): %s"
                           % (out.returncode,
                              (out.stderr.decode(errors="replace") or
                               out.stdout.decode(errors="replace"))[-200:]))
    txt = out.stdout.decode(errors="replace")
    for line in txt.splitlines():
        if "interpreter" in line and ":" in line:
            return line.split(":", 1)[1].strip()
    return None

UDF_SRC = '''\
def up(b):
    return b.upper()
'''

# The roadmap's parent-RSS axis.
PARENT_MB = [0, 30, 64, 128, 256, 554, 2127]


def make_root():
    d = tempfile.mkdtemp(prefix="m2-")
    with open(os.path.join(d, "myudf.py"), "w") as fh:
        fh.write(UDF_SRC)
    return d


def run_once(root, children, iters, parent_mb, thp):
    proc = subprocess.run(
        [DRIVER, root, "myudf:up", str(children), str(iters), "",
         str(parent_mb), thp],
        capture_output=True, timeout=900)
    out = proc.stdout.decode(errors="replace")
    err = proc.stderr.decode(errors="replace")

    f_post = re.search(r"post-fork :\s+([\d.]+) s\s+\(failures: (\d+)\)", out)
    f_pre = re.search(r"pre-fork\s+:\s+([\d.]+) s\s+\(failures: (\d+)\)", out)
    if not (f_post and f_pre):
        return None, "driver produced no parseable result: %s" % (
            err[-200:] or out[-200:])

    t_post, fail_post = float(f_post.group(1)), int(f_post.group(2))
    t_pre, fail_pre = float(f_pre.group(1)), int(f_pre.group(2))

    fields = {}
    for key in ("parent_rss_cur_kb", "parent_rss_peak_kb",
                "parent_pss_kb", "parent_uss_kb"):
        m = re.search(r"%s\s*:\s*(-?\d+)" % key, out)
        fields[key] = int(m.group(1)) if m else -1

    # Same rule as tools/bench_splice.py: one failed child discards the
    # configuration. A ratio between two failing runs is not a number.
    if fail_post or fail_pre:
        return None, "%d child failure(s) (post %d, pre %d)" % (
            fail_post + fail_pre, fail_post, fail_pre)
    if t_pre <= 0 or t_post <= 0:
        return None, "non-positive timing (pre %.6f, post %.6f)" % (
            t_pre, t_post)

    return {
        "t_post": t_post, "t_pre": t_pre,
        "speedup": t_post / t_pre,
        "children": children, "parent_mb": parent_mb, "thp": thp,
        **fields,
    }, None


def cell(root, children, parent_mb, thp, iters, trials):
    """Median of `trials`, or None. The distribution is kept for the
    crossover statement rather than collapsed to a mean."""
    good, errs = [], []
    for _ in range(trials):
        r, e = run_once(root, children, iters, parent_mb, thp)
        if r:
            good.append(r)
        else:
            errs.append(e)
    # A configuration is published ONLY if EVERY requested trial
    # succeeded.
    #
    # The rule this harness documents -- and the rule
    # tools/bench_splice.py follows -- is that a configuration with any
    # child failure is DISCARDED, not averaged from the survivors. The
    # code did not enforce it: `if not good` let a configuration
    # requested with 3 trials publish on the strength of 1.
    #
    # That is not a hypothetical. The published table's minimum speedup
    # is 1.05x, which is close enough to parity that the sample it rests
    # on had better be the one that was asked for. A partial sample is
    # also the shape that hides a flaky configuration: the trials that
    # fail are the ones dropped, so the surviving ones are biased toward
    # the favourable case by construction.
    if len(good) != trials:
        return None, ("only %d of %d trials succeeded -- %s"
                      % (len(good), trials,
                         errs[0] if errs else "no reason recorded"))
    speedups = sorted(g["speedup"] for g in good)
    return {
        "n": len(good),
        "speedup_median": statistics.median(speedups),
        "speedup_min": speedups[0],
        "speedup_max": speedups[-1],
        "rss_cur_kb": statistics.median(g["parent_rss_cur_kb"]
                                        for g in good),
        "rss_peak_kb": statistics.median(g["parent_rss_peak_kb"]
                                         for g in good),
        "pss_kb": statistics.median(g["parent_pss_kb"] for g in good),
        "uss_kb": statistics.median(g["parent_uss_kb"] for g in good),
        "t_pre": statistics.median(g["t_pre"] for g in good),
        "t_post": statistics.median(g["t_post"] for g in good),
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--quick", action="store_true",
                    help="small sweep; skips the largest parent-RSS point")
    args = ap.parse_args()

    if not os.path.exists(DRIVER):
        print("driver not built: make -f Makefile.substrate udf-fork",
              file=sys.stderr)
        return 2

    root = make_root()
    iters = 50
    parents = PARENT_MB[:-1] if args.quick else PARENT_MB
    children_set = [1, 2, 4, 8]

    import platform
    print("C0.6 M2 -- pre-fork vs post-fork interpreter lifecycle")
    print("  driver      : %s" % DRIVER)
    print("  driver cp   : %s" % (_driver_interpreter()
                                   or platform.python_version()))
    print("  driver      : %s" % os.path.relpath(DRIVER, _ROOT))
    print("  udf         : myudf:up  (pure-Python, 11 B batch)")
    print("  iters/child : %d   trials: %d" % (iters, args.trials))
    print("  thp knob    : prctl(PR_SET_THP_DISABLE); host default is "
          "'madvise'\n")

    print("  %-9s %-6s %-9s %-9s %-9s %-4s %s"
          % ("parent", "thp", "pre-fork", "post-fork", "speedup", "n",
             "parent RSScur/PSS/USS MB"))
    print("  " + "-" * 78)

    rows, skipped = [], []
    for thp in ("off", "on"):
        for parent_mb in parents:
            for children in children_set:
                c, err = cell(root, children, parent_mb, thp, iters,
                              args.trials)
                tag = "parent=%dMB thp=%s children=%d" % (
                    parent_mb, thp, children)
                if c is None:
                    skipped.append((tag, err))
                    continue
                rows.append((parent_mb, thp, children, c))
                mb = lambda k: ("%.1f" % (c[k] / 1024.0)
                                if c[k] >= 0 else "n/a")
                print("  %-9s %-6s %-9.4f %-9.4f %5.2fx-%-5.2f %-4d %s/%s/%s"
                      % ("%d" % parent_mb if parent_mb else "0", thp,
                         c["t_pre"], c["t_post"],
                         c["speedup_min"], c["speedup_max"], c["n"],
                         mb("rss_cur_kb"), mb("pss_kb"), mb("uss_kb")))

    if skipped:
        print("\n  DISCARDED (not averaged, not compared):")
        for tag, err in skipped:
            print("    %-40s %s" % (tag, err))

    if not rows:
        print("\n  NO VALID DATA. Nothing was measured; do not cite this "
              "run.", file=sys.stderr)
        return 1

    # ---- the crossover, as a distribution -------------------------
    print("\n  --- crossover (distribution, not one row) ---")
    sp = sorted(r[3]["speedup_median"] for r in rows)
    print("    pre-fork faster on %d/%d configurations" % (
        sum(1 for x in sp if x > 1.0), len(sp)))
    print("    speedup  min %.2fx  p25 %.2fx  median %.2fx  p75 %.2fx  "
          "max %.2fx"
          % (sp[0], sp[len(sp) // 4], statistics.median(sp),
         sp[(3 * len(sp)) // 4], sp[-1]))

    by_parent = {}
    for parent_mb, thp, children, c in rows:
        by_parent.setdefault(parent_mb, []).append(c["speedup_median"])
    print("\n    speedup vs parent RSS (all worker counts, both THP states):")
    for parent_mb in sorted(by_parent):
        v = by_parent[parent_mb]
        print("      %-6s %5.2fx  (n=%d)" % (
            "%dMB" % parent_mb if parent_mb else "0",
            statistics.median(v), len(v)))

    print("\n  LIMITATION: single interpreter (%s). The C0.5 gate names "
          "3.10-3.15;\n  this run covers only what is installed here, so "
          "the matrix is INCOMPLETE and\n  the crossover above is a "
          "single-interpreter result, not a\n  cross-version claim."
          % (_driver_interpreter() or platform.python_version()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
