import sys, time, os
sys.path.insert(0, 'python')
import forkrun
from forkrun._bindings import load
lib = load()
t0 = [None]
parent_pid = [os.getpid()]
orig_pwrite = os.pwrite
def logged_pwrite(fd, data, off):
    n = orig_pwrite(fd, data, off)
    if os.getpid() == parent_pid[0]:
        try:
            v = lib.fr_py_data_ready()
        except Exception:
            v = -1
        with open('/tmp/pub2.log', 'a') as fh:
            fh.write('t=%.3f pwrite off=%d n=%d data_ready=%d\n' % (time.perf_counter()-t0[0], off, n, v))
    return n
os.pwrite = logged_pwrite
open('/tmp/pub2.log','w').close()
t0[0] = time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=1, streaming=True)
print('done %.3fs batches=%d' % (time.perf_counter()-t0[0], len(r)), flush=True)
