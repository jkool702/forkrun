import os, sys, tempfile
sys.path.insert(0, 'python/benchmarks'); sys.path.insert(0, 'python')
from bench_harness import time_it
from ml_data_gen import generate_data
from bench_ml_pipeline import build_ml_plugin
import forkrun
tmp = tempfile.mkdtemp(prefix='fr_raw_')
path = os.path.join(tmp, 'light.jsonl')
generate_data(path, 100000, variant='light')
so = build_ml_plugin('light', tmp)
plug = '%s:ml_process_light' % so
print('input bytes: %d, plugin: %s' % (os.path.getsize(path), so), flush=True)
for label, kw in [('py-loop', {}), ('c-loop ', {'c_worker_loop': True})]:
    for w in [1,2,4,8,14,28]:
        def run():
            return forkrun.map(plug, path, mode='plugin', workers=w, order='none', **kw)
        t, trials = time_it(run, trials=3, warmup=1)
        rate = 100000/t/1e3
        print('%s %2dw: median %.3fs -> %7.0fk/s | trials: %s' % (
            label, w, t, rate, ' '.join('%.3f' % s for s in trials)), flush=True)
