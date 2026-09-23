import sys, time, tempfile, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
markdir = tempfile.mkdtemp(prefix='w29sp_')
moddir = tempfile.mkdtemp(prefix='w29spm_')
sys.path.insert(0, moddir)
with open(os.path.join(moddir, 'sp.py'), 'w') as fh:
    fh.write('''import os
MARKER_DIR = %r
def payload(batch):
    from ml_payload import forkrun_payload_medium
    if batch.batch_index == 5:
        mark = os.path.join(MARKER_DIR, "segv")
        if not os.path.exists(mark):
            open(mark, "w").write("x")
            import ctypes
            ctypes.string_at(0)
    return forkrun_payload_medium(batch)
''' % markdir)
print('PARENT=%d' % os.getpid(), flush=True)
t0 = time.perf_counter()
res = forkrun.map('sp:payload', '/mnt/ramdisk/w29bench/ml_medium.jsonl', workers=28, order='index', lines=100, orchestrator=True)
print('done %.1fs out=%d' % (time.perf_counter()-t0, len(res)), flush=True)
