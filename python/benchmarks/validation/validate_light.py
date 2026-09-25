import sys, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_light
path = sys.argv[1]
so = '/tmp/ml_plugin_light.so'
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
py = records(forkrun.map(forkrun_payload_light, path, workers=4, order='index'))
pl = records(forkrun.map('%s:ml_process_light' % so, path, mode='plugin', workers=4, order='index'))
print('py records:', len(py), 'plugin records:', len(pl))
