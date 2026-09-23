import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load
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
time.sleep(0.3)
os.write(memfd, b'a\nb\nc\n')
print('ingest_done:', lib.fr_py_ingest_done(), flush=True)
from forkrun._bindings import FrPyBatch
lib.fr_py_worker_init(0, 0, 0, 3, 0)
c = FrPyBatch(); rc = lib.fr_py_claim(ctypes.byref(c))
print('claim:', rc, 'idx', c.batch_idx, 'len', c.length, flush=True)
print('fallow poll:', os.waitpid(fpid, os.WNOHANG), flush=True)
_, st = os.waitpid(spid, 0)
print('scanner:', os.WEXITSTATUS(st) if os.WIFEXITED(st) else st, flush=True)
