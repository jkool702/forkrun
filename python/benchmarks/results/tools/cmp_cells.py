#!/usr/bin/env python3
"""Compare two 48-cell stream_driver.sh logs cell by cell.

Throughput is MB/s (the 8th RESULT field). Reports the ratio
new/base per cell plus the worst regressions, because a single median
cell is noisy and only the pattern across all 48 says whether something
regressed.

Usage: cmp_cells.py <baseline.log> <new.log>
"""
import sys


def load(path):
    cells = {}
    for line in open(path):
        f = line.split()
        if len(f) >= 9 and f[0] == "RESULT":
            key = " ".join(f[1:6])          # variant payload cfg output src
            cells[key] = {
                "nodes": f[6],
                "secs": float(f[7]),
                "mbps": float(f[8]),
                "n_out": int(f[9]) if len(f) > 9 else None,
            }
    return cells


def main():
    base = load(sys.argv[1])
    new = load(sys.argv[2])
    common = [k for k in base if k in new]
    if not common:
        sys.exit("no cells in common: base=%d new=%d" % (len(base), len(new)))

    print("base=%s (%d cells)  new=%s (%d cells)  compared=%d"
          % (sys.argv[1].split("/")[-1], len(base),
             sys.argv[2].split("/")[-1], len(new), len(common)))
    only_base = sorted(set(base) - set(new))
    only_new = sorted(set(new) - set(base))
    if only_base:
        print("  MISSING FROM NEW (%d): %s" % (len(only_base), only_base[:4]))
    if only_new:
        print("  only in new (%d): %s" % (len(only_new), only_new[:4]))
    mism = [k for k in common if new[k]["n_out"] not in (None, base[k]["n_out"])]
    if mism:
        print("  !! n_out differs on %d cells -- correctness, not speed" % len(mism))
        for k in mism[:5]:
            print("     %s base=%s new=%s" % (k, base[k]["n_out"], new[k]["n_out"]))

    ratios = []
    for k in common:
        ratios.append((new[k]["mbps"] / base[k]["mbps"], k))
    ratios.sort()

    print("\n--- 10 worst (throughput ratio new/base) ---")
    for r, k in ratios[:10]:
        print("  %6.3fx  %-42s %8.1f -> %8.1f MB/s" % (r, k, base[k]["mbps"], new[k]["mbps"]))
    print("--- 5 best ---")
    for r, k in ratios[-5:]:
        print("  %6.3fx  %-42s %8.1f -> %8.1f MB/s" % (r, k, base[k]["mbps"], new[k]["mbps"]))

    import statistics
    rs = [r for r, _ in ratios]
    print("\nmedian ratio %.4f   geomean %.4f   min %.3f   max %.3f"
          % (statistics.median(rs),
             statistics.geometric_mean(rs), min(rs), max(rs)))
    for thr, label in ((0.95, ">=5% slower"), (0.90, ">=10% slower"), (1.05, ">=5% faster")):
        n = len([r for r in rs if (r < thr if "slower" in label else r > thr)])
        print("  %-12s %d/%d cells" % (label, n, len(rs)))


main()