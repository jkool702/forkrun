import sys, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_heavy
so = '/tmp/ml_plugin_heavy.so'
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
py = records(forkrun.map(forkrun_payload_heavy, '/tmp/mlv_heavy.jsonl', workers=4, order='index'))
pl = records(forkrun.map('%s:ml_process_heavy' % so, '/tmp/mlv_heavy.jsonl', mode='plugin', workers=4, order='index'))
for a, b in zip(py, pl):
    if abs(a['rv_ld'] - b['rv_ld']) > 1e-12:
        print('py :', {k: a[k] for k in ('rv_wc','rv_uw','rv_ld')})
        print('c  :', {k: b[k] for k in ('rv_wc','rv_uw','rv_ld')})
        print('eid:', a['eid'])
        break
