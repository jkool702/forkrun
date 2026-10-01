import sys, os, random, shutil, tempfile
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_medium
SRC = '/tmp/mldata/ml_medium.jsonl'
D = tempfile.mkdtemp(prefix='fv_')
rng = random.Random(999)
crash_idx = {rng.randint(0, 100)}
trans_idx = {rng.randint(0, 100) for _ in range(5)}
print('crash targets:', crash_idx, 'transient targets:', sorted(trans_idx))
def fault_payload(batch):
    import ctypes, os as _o
    idx = batch.batch_index
    if idx in crash_idx:
        m = os.path.join(D, 'crash_%d' % idx)
        if not _o.path.exists(m):
            open(m, 'w').write('1')
            ctypes.string_at(0)
    if idx in trans_idx:
        m = os.path.join(D, 'trans_%d' % idx)
        if not _o.path.exists(m):
            open(m, 'w').write('1')
            raise RuntimeError('transient')
    return forkrun_payload_medium(batch)
res = forkrun.map(fault_payload, SRC, workers=8, order='index', on_error='retry', orchestrator=True)
n = sum(1 for b in res for _ in b.split(b'\n') if _.strip())
markers = sorted(os.listdir(D))
print('records:', n, 'markers:', markers)
shutil.rmtree(D, ignore_errors=True)
