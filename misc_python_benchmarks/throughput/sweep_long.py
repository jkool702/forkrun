import os, sys, tempfile
sys.path.insert(0, 'python/benchmarks'); sys.path.insert(0, 'python')
from bench_harness import time_it
from ml_data_gen import generate_data
from bench_ml_pipeline import build_ml_plugin
import forkrun
tmp = tempfile.mkdtemp(prefix='fr_long_')
path = os.path.join(tmp, 'light.jsonl')
N = 1000000
generate_data(path, N, variant='light')
so = build_ml_plugin('light', tmp)
plug = '%s:ml_process_light' % so
print('records: %d, input bytes: %d' % (N, os.path.getsize(path)), flush=True)
for label, kw in [('py-loop', {}), ('c-loop ', {'c_worker_loop': True})]:
    for w in [1,2,4,8,14,28]:
        def run():
            return forkrun.map(plug, path, mode='plugin', workers=w, order='none', **kw)
        t, trials = time_it(run, trials=5, warmup=2)
        print('%s %2dw: median %.3fs -> %8.0fk/s | trials: %s' % (
            label, w, t, N/t/1e3, ' '.join('%.3f' % s for s in trials)), flush=True)
