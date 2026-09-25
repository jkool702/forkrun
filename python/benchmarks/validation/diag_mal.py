import sys, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_medium
path = '/tmp/mlv_dirty.jsonl'
so = '/tmp/ml_plugin_medium.so'
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
py = records(forkrun.map(forkrun_payload_medium, path, workers=4, order='index'))
pl = records(forkrun.map('%s:ml_process_medium' % so, path, mode='plugin', workers=4, order='index'))
print('py:', len(py), 'plugin:', len(pl))
# find differing eids
pye = {r['eid'] for r in py}; ple = {r['eid'] for r in pl}
print('only-py:', len(pye - ple), 'only-plugin:', len(ple - pye))
