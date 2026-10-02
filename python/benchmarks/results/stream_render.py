"""Render the two streaming tables from the raw cell logs.

Table 1: nodes="auto" (4 fake nodes) -- the DEFAULT configuration.
Table 2: nodes=1 (UMA), same fake-4 boot -- for comparison.

Missing cells are emitted as explicit placeholders, never silently
dropped: a table with a hole reads as "not measured" when it should
read "not finished yet".
"""
import sys


def load(path):
    rows = {}
    for ln in open(path):
        if not ln.startswith("RESULT"):
            continue
        p = ln.split()
        # Two formats on disk: the original 9-field RESULT (no `nodes`
        # column) and the 10-field one cell.py emits now. Detect rather
        # than assume, or half the study reads as missing.
        if len(p) >= 10:
            rows[(p[1], p[2], p[3], p[4], p[5])] = float(p[7])
        elif len(p) == 9:
            rows[(p[1], p[2], p[3], p[4], p[5])] = float(p[6])
    return rows


auto = load("/tmp/opencode/mlbench/cells_auto.log")
uma = load("/tmp/opencode/mlbench/cells.log")
CORPORA = ("light", "medium", "heavy")
COMBOS = [("default", "view"), ("default", "bytes"),
          ("max", "view"), ("max", "bytes")]


def recs(sec, n):
    v = n / sec
    return "%.2fM" % (v / 1e6) if v >= 1e6 else "%.0fk" % (v / 1e3)


NIN = {"light": 5000000, "medium": 5000000, "heavy": 5000000}


def table(rows, label):
    out = []
    out.append("### %s\n" % label)
    out.append("| payload | config | output | source | Light (533 MB) | "
               "Medium (2.35 GB) | Heavy (6.72 GB) |")
    out.append("|---|---|---|---|---|---|---|")
    for pl, nice in (("plugin", "C plugin"), ("udf", "Python UDF")):
        for cfg, o in COMBOS:
            cells = []
            for v in CORPORA:
                for src in ("file", "pipe"):
                    pass
                f = rows.get((v, pl, cfg, o, "file"))
                p = rows.get((v, pl, cfg, o, "pipe"))
                if f is None or p is None:
                    cells.append("_(pending)_" if f is None or p is None
                                 else "")
                    continue
                cells.append("%.3f s / %s rec/s (pipe %+.0f%%)"
                             % (p, recs(p, NIN[v]),
                                (p - f) / f * 100.0))
            out.append("| %s | `%s` | %s | pipe | %s |"
                       % (nice, cfg, o, " | ".join(cells)))
    return "\n".join(out)


print("### A. nodes=\"auto\" — DEFAULT (4 fake nodes, numa=fake=4 boot)\n")
print(table(auto, "auto"))
print()
print("### B. nodes=1 — UMA (same fake-4 boot)\n")
print(table(uma, "UMA"))