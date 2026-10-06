"""Re-measure the forkrun rows of the v3.6.0 release table.

Eight configurations per corpus, replacing the four rows that were there:

  payload  x  supervisor  x  output representation
  C plugin x {reactor-default, fail-fast-max} x {bytes, memoryview}
  PythonUDF x {reactor-default, fail-fast-max} x {bytes, memoryview}

  reactor-default = orchestrator=True,  order="index"  (the † rows)
  fail-fast-max   = orchestrator=False, order="none"    (the (max) rows)

Same methodology the table documents: 28 workers, nodes=1, median of 3
after a warmup, and count_results() on the measured output so every
cell is exactness-checked rather than trusted.
"""
import gc
import json
import os
import statistics
import sys
import time

sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks/ml')

import forkrun
from bench_ml_pipeline import FORKRUN_PAYLOADS, count_results

WORK = '/tmp/opencode/mlbench'
CORPORA = {
    'light':  ('/mnt/ramdisk/numa1/ml/light_5M.jsonl', 5000000),
    'medium': ('/mnt/ramdisk/numa1/ml/medium_5M.jsonl', 5000000),
    'heavy':  ('/tmp/opencode/heavy_5M.jsonl', 5000000),
}
WORKERS = 28
TRIALS = 3
# exact totals the release table carries, so a config that silently
# drops or duplicates records fails here instead of scoring faster
EXPECT = {'light': 5000000, 'medium': 4997892, 'heavy': 4997982}


def measure(make, n_records, trials=TRIALS):
    """median of `trials` timed runs after one warmup.

    Returns (seconds, results) where results is from the final timed run
    so the caller can count records without paying for another run.
    """
    make()                                    # warmup
    times, out = [], None
    for _ in range(trials):
        gc.collect()
        t0 = time.perf_counter()
        out = make()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), out


def main():
    only = sys.argv[1:] or list(CORPORA)
    rows = []
    for variant in only:
        path, n_in = CORPORA[variant]
        n_bytes = os.path.getsize(path)
        plugin_so = os.path.join(WORK, "ml_plugin_%s.so" % variant)

        for payload_kind in ("C plugin", "Python UDF"):
            for label, orch, order in (("default", True, "index"),
                                       ("max", False, "none")):
                for output in ("bytes", "view"):
                    if payload_kind == "C plugin":
                        pl = "%s:ml_process_%s" % (plugin_so, variant)
                        mode = "plugin"
                    else:
                        pl = FORKRUN_PAYLOADS[variant]
                        mode = "python"

                    def run(pl=pl, mode=mode, orch=orch, order=order,
                            output=output, p=path):
                        return forkrun.map(
                            pl, p, mode=mode, workers=WORKERS, nodes=1,
                            orchestrator=orch, order=order, output=output)

                    secs, out = measure(run, n_in)
                    n_out = count_results(out)
                    kind = type(out[0]).__name__ if out else "?"
                    del out
                    ok = (n_out == EXPECT[variant])
                    row = dict(
                        variant=variant, payload=payload_kind,
                        config=label, output=output, seconds=round(secs, 4),
                        rec_per_s=round(n_in / secs),
                        mb_per_s=round(n_bytes / 1e6 / secs),
                        out_records=n_out, expect=EXPECT[variant],
                        ok=ok, got_type=kind)
                    rows.append(row)
                    print("%-6s %-11s %-7s %-6s %7.3fs %8.3fM rec/s "
                          "%7.1f MB/s out=%d %s %s"
                          % (variant, payload_kind, label, ("view" if output == "view" else output), secs,
                             n_in / secs / 1e6, n_bytes / 1e6 / secs,
                             n_out, "OK" if ok else "*** MISMATCH ***",
                             kind), flush=True)
    with open(os.path.join(WORK, "results.json"), "w") as fh:
        json.dump(rows, fh, indent=1)
    print("\nwrote %s/results.json" % WORK)
    bad = [r for r in rows if not r["ok"]]
    print("cells: %d, exactness failures: %d" % (len(rows), len(bad)))
    for r in bad:
        print("  FAIL", r)


if __name__ == "__main__":
    main()
