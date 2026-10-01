import sys, ctypes
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
from forkrun._bindings import load, find_substrate, FrPyBatch
from forkrun.run import _spill_to_memfd, _open_source
lib = load(find_substrate())
lib.fr_py_init(0, 0)
print('is_resume (fresh):', lib.fr_py_is_resume_mode())
src, _ = _open_source('/tmp/res_src.txt')
memfd, size = _spill_to_memfd(src)
lib.fr_py_ingest_done()
print('scan:', lib.fr_py_scan(memfd))
lib.fr_py_worker_init(0, -1, 0, 3, 0)
n = 0; total = 0
while True:
    c = FrPyBatch()
    rc = lib.fr_py_claim(ctypes.byref(c))
    if rc == 2: break
    if rc != 0: print('FAIL rc', rc); break
    total += c.length
    lib.fr_py_ack(-1, -1)
    n += 1
    if n > 500: break
print('baseline -> batches', n, 'payload bytes', total)
lib.fr_py_destroy()
