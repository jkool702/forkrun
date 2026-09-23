import os, sys, tempfile
sys.path.insert(0, 'python/benchmarks'); sys.path.insert(0, 'python')
from bench_harness import time_it
from ml_data_gen import generate_data
from bench_ml_pipeline import build_ml_plugin
import forkrun
tmp = tempfile.mkdtemp(prefix='fr_real_')
path = os.path.join(tmp, 'light.jsonl')
generate_data(path, 100000, variant='light')
so = build_ml_plugin('light', tmp)
plug = '%s:ml_process_light' % so
print('plugin:', so, 'size:', os.path.getsize(path))
for w in [1,2,4,8,14,28]:
    t,_ = time_it(lambda: forkrun.map(plug, path, mode='plugin', workers=w, order='none'), trials=3, warmup=1)
    print('py-loop %2dw: %7.0fk/s' % (w, 100000/t/1e3), flush=True)
for w in [1,2,4,8,14,28]:
    t,_ = time_it(lambda: forkrun.map(plug, path, mode='plugin', workers=w, order='none', c_worker_loop=True), trials=3, warmup=1)
    print('c-loop  %2dw: %7.0fk/s' % (w, 100000/t/1e3), flush=True)
