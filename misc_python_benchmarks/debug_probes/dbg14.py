import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load, FrPyBatch
from forkrun.run import (_close_all_except, _new_ingress_memfd,
                         _new_output_memfds)
lib = load()
lib.fr_py_init(0, 0)
src = os.open('/tmp/q.txt', os.O_RDONLY)
memfd, _hold = _new_ingress_memfd()
os.lseek(memfd, 0, 0)
out_fds, _oh = _new_output_memfds(1)
spid = os.fork()
if spid == 0:
    _close_all_except({memfd})
    rc = lib.fr_py_scan(memfd)
    os._exit(0 if rc == 0 else 5)
# NO worker fork; NO sleep (dbg13 shape otherwise)
while True:
    ch = os.read(src, 1 << 20)
    if not ch: break
    os.write(memfd, ch)
lib.fr_py_ingest_done()
lib.fr_py_worker_init(0, 0, 0, 3, 0)
for _ in range(5):
    c = FrPyBatch(); r = lib.fr_py_claim(ctypes.byref(c))
    sys.stderr.write('claim %d idx %d len %d\n' % (r, c.batch_idx, c.length))
    if r != 0: break
