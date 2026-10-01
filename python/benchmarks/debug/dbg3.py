import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load
lib = load()
print('init:', lib.fr_py_init(0, 0), flush=True)
memfd = os.memfd_create('dbg')
os.lseek(memfd, 0, 0)
fr, fw = os.pipe()
fpid = os.fork()
if fpid == 0:
    rc = lib.fr_py_fallow_loop(fr, memfd)
    os._exit(0 if rc == 0 else 6)
print('fallow forked', flush=True)
spid = os.fork()
if spid == 0:
    rc = lib.fr_py_scan(memfd)
    os._exit(0 if rc == 0 else 5)
print('scanner forked', flush=True)
os.close(fr)
time.sleep(0.3)
os.write(memfd, b'a\nb\nc\n')
print('wrote', flush=True)
print('ingest_done:', lib.fr_py_ingest_done(), flush=True)
from forkrun._bindings import FrPyBatch
lib.fr_py_worker_init(0, 0, 0, 3, 0)
print('worker_init done', flush=True)
c = FrPyBatch(); rc = lib.fr_py_claim(ctypes.byref(c))
print('claim:', rc, 'idx', c.batch_idx, 'len', c.length, flush=True)
