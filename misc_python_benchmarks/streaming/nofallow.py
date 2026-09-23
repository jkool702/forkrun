import sys, time
sys.path.insert(0, 'python')
import forkrun
import importlib
runmod = importlib.import_module('forkrun.run')
orig_wm = runmod.worker_main
def wm(*a, **k):
    a = list(a)
    if len(a) > 8:
        a[8] = None
    return orig_wm(*a, **k)
runmod.worker_main = wm
t0 = time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
dt = time.perf_counter() - t0
print('no-fallow-ack: %.1f lines/s (%.3fs)' % (1000000 / dt, dt), flush=True)
