import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_light
path, so = sys.argv[1], sys.argv[2]
a = b''.join(forkrun.map(forkrun_payload_light, path, workers=4, order='index'))
b = b''.join(forkrun.map('%s:ml_process_light' % so, path, mode='plugin', workers=4, order='index'))
print('bytes:', len(a), len(b), 'BYTE-IDENTICAL:', a == b)
