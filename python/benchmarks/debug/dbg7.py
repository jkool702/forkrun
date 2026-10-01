import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load, FrPyBatch
from forkrun.run import _close_all_except
lib = load()
print('init:', lib.fr_py_init(0, 0), flush=True)
memfd = os.memfd_create('dbg')
os.lseek(memfd, 0, 0)
fr, fw = os.pipe()
fpid = os.fork()
if fpid == 0:
    _close_all_except({fr, memfd})
    rc = lib.fr_py_fallow_loop(fr, memfd)
    os._exit(0 if rc == 0 else 6)
spid = os.fork()
if spid == 0:
    _close_all_except({memfd})
    rc = lib.fr_py_scan(memfd)
    os._exit(0 if rc == 0 else 5)
os.close(fr)
wpid = os.fork()
if wpid == 0:
    _close_all_except({memfd, fw})
    sys.stderr.write('worker: scrubbed, fds=%s\n' % os.listdir('/proc/self/fd'))
    rc = lib.fr_py_worker_init(0, 0, 0, 3, 0)
    sys.stderr.write('worker: init %d\n' % rc)
    c = FrPyBatch(); r = lib.fr_py_claim(ctypes.byref(c))
    sys.stderr.write('worker: claim %d idx %d len %d\n' % (r, c.batch_idx, c.length))
    os._exit(0)
time.sleep(0.3)
os.write(memfd, b'a\nb\nc\n')
print('ingest_done:', lib.fr_py_ingest_done(), flush=True)
_, st = os.waitpid(wpid, 0)
print('worker:', os.WEXITSTATUS(st) if os.WIFEXITED(st) else st, flush=True)
