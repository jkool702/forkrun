"""Extra-long ML sweep RESUME: only missing 5M-record configs run.

Workers 8/14/28. Fast systems trials=3 (+1 warmup); HF/Ray 1 trial.
Guards every bench by row name in /tmp/ml_xlong.csv.
"""
import csv
import os
import sys

sys.path.insert(0, 'python/benchmarks')
sys.path.insert(0, 'python')

from bench_harness import BenchContext, format_table
from bench_ml_pipeline import (RayBench, bench_executor, bench_forkrun,
                               bench_forkrun_plugin, bench_hf_datasets,
                               bench_native, bench_pool, bench_serial)

TMPDIR = '/tmp/fr_ml_xlong'
CSV = '/tmp/ml_xlong.csv'
N = 5000000
WORKERS = [8, 14, 28]

ctx = BenchContext(scale='small', trials=3)
written = 0

HAVE = set()
if os.path.exists(CSV):
    with open(CSV) as _fh:
        for _r in csv.DictReader(_fh):
            HAVE.add(_r['name'])


def have(name):
    return name in HAVE


def flush_rows():
    global written
    rows = ctx.results[written:]
    if not rows:
        return
    new = not os.path.exists(CSV)
    with open(CSV, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['name', 'mode', 'path', 'lines_per_s', 'rss_mb',
                        'cpu_pct', 'notes', 'hardware'])
        for r in rows:
            w.writerow([r.name, r.mode, r.path, r.lines_per_s,
                        r.rss_mb, getattr(r, 'cpu_pct', -1.0),
                        r.notes, r.hardware])
            HAVE.add(r.name)
    written = len(ctx.results)


def bench_ploop(path, n_records, input_bytes, variant, workers, trials,
                plugin_so):
    """forkrun C plugin via the W-PY26 C worker loop."""
    import forkrun
    from bench_harness import rss_mb, time_it
    payload = '%s:ml_process_%s' % (plugin_so, variant)

    def run():
        return forkrun.map(payload, path, mode='plugin',
                           workers=workers, order='index',
                           c_worker_loop=True)

    t, _ = time_it(run, trials=trials, warmup=1)
    from bench_ml_pipeline import count_results
    n_out = count_results(run())
    ctx.record('forkrun-ploop-%s-%dw' % (variant, workers), 'plugin-loop',
               'c-loop', n_records / t, rss_mb(),
               'out=%d/%d records, frozen ABI + C loop'
               % (n_out, n_records))
    return n_records / t


def maybe(label, name, fn):
    if have(name):
        print('skip %s' % name, flush=True)
        return None
    try:
        r = fn()
        print('%s: %.0f/s' % (label, r), flush=True)
    except Exception as exc:
        print('%s FAILED: %s' % (label, str(exc)[:150]), flush=True)
    flush_rows()
    return None


def main():
    for variant in ['light', 'medium', 'heavy']:
        path = os.path.join(TMPDIR, 'ml_%s.jsonl' % variant)
        so = os.path.join(TMPDIR, 'ml_plugin_%s.so' % variant)
        assert os.path.exists(path), path
        input_bytes = os.path.getsize(path)
        print('--- %s: %d records, %.1fMB ---'
              % (variant, N, input_bytes / 2 ** 20), flush=True)

        maybe('serial %s' % variant, 'serial-%s' % variant,
              lambda: bench_serial(ctx, path, N, input_bytes,
                                   variant, 3))

        for w in WORKERS:
            tag = '%s-%dw' % (variant, w)
            maybe('pool ' + tag, 'pool-' + tag,
                  lambda: bench_pool(ctx, path, N, input_bytes,
                                     variant, w, 3))
            maybe('executor ' + tag, 'executor-' + tag,
                  lambda: bench_executor(ctx, path, N, input_bytes,
                                         variant, w, 3))
            maybe('hf ' + tag, 'hf-datasets-' + tag,
                  lambda: bench_hf_datasets(ctx, path, N, input_bytes,
                                            variant, w, 1))
            maybe('forkrun ' + tag, 'forkrun-' + tag,
                  lambda: bench_forkrun(ctx, path, N, input_bytes,
                                        variant, w, 3))
            maybe('plugin ' + tag, 'forkrun-plugin-' + tag,
                  lambda: bench_forkrun_plugin(ctx, path, N,
                                               input_bytes, variant,
                                               w, 3, so))
            maybe('ploop ' + tag, 'forkrun-ploop-' + tag,
                  lambda: bench_ploop(path, N, input_bytes, variant,
                                      w, 3, so))

        if all(have('ray-%s-%dw' % (variant, w)) for w in WORKERS):
            print('skip ray-%s (all workers done)' % variant,
                  flush=True)
        else:
            try:
                rb = RayBench(cpus=max(WORKERS))
                for w in WORKERS:
                    maybe('ray %s-%dw' % (variant, w),
                          'ray-%s-%dw' % (variant, w),
                          lambda: rb.run_variant(ctx, path, N,
                                                 input_bytes, variant,
                                                 w, 1))
                rb.shutdown()
            except Exception as exc:
                print('ray %s setup FAILED: %s'
                      % (variant, str(exc)[:200]), flush=True)

        if have('polars-native') and have('duckdb-native'):
            print('skip native-%s' % variant, flush=True)
        else:
            try:
                bench_native(ctx, path, N, input_bytes, variant, 3)
                print('native %s done' % variant, flush=True)
            except Exception as exc:
                print('native %s FAILED: %s'
                      % (variant, str(exc)[:150]), flush=True)
            flush_rows()
        print(format_table(ctx.results[-25:]), flush=True)

    print('CSV: %s (%d rows total)' % (CSV, len(HAVE)))


if __name__ == '__main__':
    main()
