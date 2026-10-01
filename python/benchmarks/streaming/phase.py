import sys, time
sys.path.insert(0, 'python')
from forkrun._bindings import load
import forkrun, forkrun.run as runmod
lib = load()
t0 = [None]
orig_dr = lib.fr_py_data_ready
def logged_dr():
    v = orig_dr()
    if v > 0 and t0[0] is not None and not hasattr(logged_dr, 'fired'):
        logged_dr.fired = True
        print('first publish at %.3fs' % (time.perf_counter() - t0[0]), flush=True)
    return v
lib.fr_py_data_ready = logged_dr
orig_done = lib.fr_py_ingest_done
def logged_done():
    print('gate at %.3fs' % (time.perf_counter() - t0[0]), flush=True)
    return orig_done()
lib.fr_py_ingest_done = logged_done
orig_fork = __import__('os').fork
import os
def logged_fork():
    return orig_fork()
t0[0] = time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
print('done %.3fs batches=%d' % (time.perf_counter()-t0[0], len(r)), flush=True)
