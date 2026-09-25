import sys, importlib, time, resource
sys.path.insert(0, 'python')
import forkrun
runmod = importlib.import_module('forkrun.run')
orig_wm = runmod.worker_main
NOFALLOW = [False]
def wm(*a, **k):
    a = list(a)
    if len(a) > 8 and NOFALLOW[0]:
        a[8] = None
    return orig_wm(*a, **k)
runmod.worker_main = wm
def cpu():
    me = resource.getrusage(resource.RUSAGE_SELF); k = resource.getrusage(resource.RUSAGE_CHILDREN)
    return me.ru_utime+me.ru_stime+k.ru_utime+k.ru_stime
for i in range(8):
    NOFALLOW[0] = bool(i % 2)
    c0=cpu(); t0=time.perf_counter()
    forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=1, streaming=True)
    print('%s run%d: wall=%.3f cpu=%.3fs' % ('nofallow' if NOFALLOW[0] else 'fallow  ', i, time.perf_counter()-t0, cpu()-c0), flush=True)
