import sys, time, threading
sys.path.insert(0, 'python')
from forkrun._bindings import load
import forkrun
lib = load()
t0 = [None]
stop = [False]
def sampler():
    last = -1
    while not stop[0]:
        try:
            v = lib.fr_py_data_ready()
        except Exception:
            v = -2
        if v != last:
            print('t=%.3f published=%d' % (time.perf_counter()-t0[0], v), flush=True)
            last = v
        time.sleep(0.005)
t0[0] = time.perf_counter()
th = threading.Thread(target=sampler)
th.start()
# NOTE: threads + fork = forbidden ordering! start sampler AFTER? engine fork
# happens inside map... sampler thread + os.fork in worker path = DANGER.
# Instead: sample from a SEPARATE process via... can't (no shared API).
# Fall back: threads started before map WILL break fork. ABORT this approach.
stop[0] = True
th.join()
print('aborted: sampler thread + fork unsafe', flush=True)
