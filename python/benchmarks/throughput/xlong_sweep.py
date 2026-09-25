"""Extra-long ML sweep: reuse 5M-record inputs, fast feedback first.

Workers 8/14/28 only. Fast systems: trials=3 (+1 warmup). HF/Ray:
1 trial. Serial: suite default. Incremental CSV (flush per row) so
a timeout never loses data. Mirrors bench_ml_pipeline row names,
plus forkrun-ploop (c_worker_loop=True plugin variant).
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
    import csv as _csv
    with open(CSV) as _fh:
        for _r in _csv.DictReader(_fh):
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


def done(variant, workers):
    want = {'forkrun-%s-%dw', 'forkrun-plugin-%s-%dw',
            'forkrun-ploop-%s-%dw', 'pool-%s-%dw', 'executor-%s-%dw',
            'hf-datasets-%s-%dw', 'ray-%s-%dw'}
    names = {r.name for r in ctx.results}
    return all(t % (variant, workers) in names for t in want)




def main():
    for variant in ['light', 'medium', 'heavy']:
        path = os.path.join(TMPDIR, 'ml_%s.jsonl' % variant)
        so = os.path.join(TMPDIR, 'ml_plugin_%s.so' % variant)
        assert os.path.exists(path), path
        input_bytes = os.path.getsize(path)
        print('--- %s: %d records, %.1fMB ---'
              % (variant, N, input_bytes / 2 ** 20), flush=True)

        r = bench_serial(ctx, path, N, input_bytes, variant, 3)
        print('serial %s: %.0f/s' % (variant, r), flush=True)
        flush_rows()

        for w in WORKERS:
            tag = '%s-%dw' % (variant, w)
            if done(variant, w):
                print('skip %s (already have rows)' % tag, flush=True)
                continue
            r = bench_pool(ctx, path, N, input_bytes, variant, w, 3)
            print('pool %s: %.0f/s' % (tag, r), flush=True)
            flush_rows()
            r = bench_executor(ctx, path, N, input_bytes, variant, w, 3)
            print('executor %s: %.0f/s' % (tag, r), flush=True)
            flush_rows()
            try:
                r = bench_hf_datasets(ctx, path, N, input_bytes, variant,
                                      w, 1)
                print('hf %s: %.0f/s' % (tag, r), flush=True)
            except Exception as exc:
                print('hf %s FAILED: %s' % (tag, str(exc)[:150]),
                      flush=True)
            flush_rows()
            r = bench_forkrun(ctx, path, N, input_bytes, variant, w, 3)
            print('forkrun %s: %.0f/s' % (tag, r), flush=True)
            flush_rows()
            try:
                r = bench_forkrun_plugin(ctx, path, N, input_bytes,
                                         variant, w, 3, so)
                print('plugin %s: %.0f/s' % (tag, r), flush=True)
            except Exception as exc:
                print('plugin %s FAILED: %s' % (tag, str(exc)[:150]),
                      flush=True)
            flush_rows()
            try:
                r = bench_ploop(path, N, input_bytes, variant, w, 3, so)
                print('ploop %s: %.0f/s' % (tag, r), flush=True)
            except Exception as exc:
                print('ploop %s FAILED: %s' % (tag, str(exc)[:150]),
                      flush=True)
            flush_rows()

        try:
            rb = RayBench(cpus=max(WORKERS))
            for w in WORKERS:
                try:
                    r = rb.run_variant(ctx, path, N, input_bytes, variant,
                                       w, 1)
                    print('ray %s-%dw: %.0f/s' % (variant, w, r),
                          flush=True)
                except Exception as exc:
                    print('ray %s-%dw FAILED: %s'
                          % (variant, w, str(exc)[:150]), flush=True)
                flush_rows()
            rb.shutdown()
        except Exception as exc:
            print('ray %s setup FAILED: %s' % (variant, str(exc)[:200]),
                  flush=True)

        try:
            bench_native(ctx, path, N, input_bytes, variant, 3)
            print('native %s done' % variant, flush=True)
        except Exception as exc:
            print('native %s FAILED: %s' % (variant, str(exc)[:150]),
                  flush=True)
        flush_rows()
        print(format_table(ctx.results[-40:]), flush=True)

    print('CSV: %s (%d rows)' % (CSV, len(ctx.results)))


if __name__ == '__main__':
    main()
