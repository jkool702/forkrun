import sys, time
sys.path.insert(0, 'python')
import forkrun
from forkrun._bindings import load
lib = load()
t0 = [None]
orig_dr = lib.fr_py_data_ready
last = [0]
def logged_dr():
    v = orig_dr()
    # log every call for the first run only (parent-side calls)
    import os
    if os.getpid() == parent_pid[0]:
        with open('/tmp/pub.log', 'a') as fh:
            fh.write('t=%.3f data=%d\n' % (time.perf_counter()-t0[0], v))
    return v
lib.fr_py_data_ready = logged_dr
import os
parent_pid = [os.getpid()]
open('/tmp/pub.log','w').close()
# force data_ready polling to continue: patch _maybe_fork_workers? No—call pattern is per-chunk (30 chunks).
# Instead run with MANY small chunks: lines=100 forces more spill iterations? spill is 1MB chunks regardless.
# Just run and observe call pattern.
t0[0] = time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=1, streaming=True)
print('done %.3fs batches=%d' % (time.perf_counter()-t0[0], len(r)), flush=True)
