import os, sys, tempfile
sys.path.insert(0, 'python/benchmarks'); sys.path.insert(0, 'python')
from bench_harness import time_it
from ml_data_gen import generate_data
from bench_ml_pipeline import build_ml_plugin
import forkrun
tmp = tempfile.mkdtemp(prefix='fr_1midx_')
path = os.path.join(tmp, 'light.jsonl')
N = 1000000
generate_data(path, N, variant='light')
so = build_ml_plugin('light', tmp)
plug = '%s:ml_process_light' % so
print('records: %d bytes: %d' % (N, os.path.getsize(path)), flush=True)
def py_touch(batch):
    data = bytes(batch.data)
    return b'%d:%d' % (batch.batch_index, len(data))
for label, payload, mode in [('py-index', py_touch, 'python'), ('plug-index', plug, 'plugin')]:
    for w in [1,2,4,8,14,28]:
        def run():
            return forkrun.map(payload, path, mode=mode, workers=w, order='index')
        t, trials = time_it(run, trials=3, warmup=1)
        print('%s %2dw: %.3fs -> %.0fk/s | %s' % (label, w, t, N/t/1e3, ' '.join('%.3f' % s for s in trials)), flush=True)
