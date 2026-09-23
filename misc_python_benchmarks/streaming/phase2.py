import sys, time, os
sys.path.insert(0, 'python')
from forkrun._bindings import load
import forkrun
lib = load()
t0 = [None]
last_pub = [0]
orig_dr = lib.fr_py_data_ready
def logged_dr():
    v = orig_dr()
    if v > 0:
        last_pub[0] = time.perf_counter() - t0[0]
    return v
lib.fr_py_data_ready = logged_dr
orig_claim = lib.fr_py_claim
counts = {}
def logged_claim(c):
    r = orig_claim(c)
    if r == 0:
        counts[os.getpid()] = counts.get(os.getpid(), 0) + 1
    return r
lib.fr_py_claim = logged_claim
t0[0] = time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
print('done %.3fs batches=%d last_publish=%.3fs claims=%s' % (time.perf_counter()-t0[0], len(r), last_pub[0], sorted(counts.values())), flush=True)
