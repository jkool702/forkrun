import os, sys
sys.path.insert(0, 'python')
import forkrun.run as runmod
from forkrun._bindings import load
orig_fork = os.fork
lib = load()
# wrap data_ready with logging
orig_dr = lib.fr_py_data_ready
def logged_dr():
    return orig_dr()
lib.fr_py_data_ready = logged_dr
orig_ingest_done = lib.fr_py_ingest_done
def logged_done():
    with open('/tmp/spill.log', 'a') as fh:
        fh.write('GATE\n')
    return orig_ingest_done()
lib.fr_py_ingest_done = logged_done
# wrap os.write to memfd is noisy; instead patch _execute_ingest_locked? too deep.
# simpler: strace-lite via /proc: sample memfd size over time in a thread
import threading
open('/tmp/spill.log','w').close()
stop = [False]
def sampler():
    import glob
    while not stop[0]:
        for p in glob.glob('/proc/self/fd/*'):
            try:
                t = os.readlink(p)
                if 'forkrun_ingress' in t:
                    fd = int(os.path.basename(p))
                    sz = os.fstat(fd).st_size
                    with open('/tmp/spill.log', 'a') as fh:
                        fh.write('memfd size=%d\n' % sz)
            except OSError:
                pass
        import time; time.sleep(0.2)
th = threading.Thread(target=sampler); th.start()
import forkrun
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    chunk = b'x' * 999 + b'\n'
    for i in range(3000):
        os.write(w, chunk)
    os.close(w)
    os._exit(0)
os.close(w)
n = [0]
def count(batch):
    n[0] += batch.byte_length
    return None
th2 = None
try:
    forkrun.run(count, r, workers=2, streaming=True)
finally:
    stop[0] = True
    th.join()
os.close(r)
os.waitpid(pid, 0)
print('bytes=%d' % n[0], flush=True)
