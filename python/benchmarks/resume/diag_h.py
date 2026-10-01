import sys, ctypes, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
from forkrun._bindings import load, find_substrate, FrPyBatch
from forkrun.run import _spill_to_memfd, _open_source

H = int(sys.argv[1])
lib = load(find_substrate())
lib.fr_py_init(0, 0)
print('set:', lib.fr_py_set_resume_state(H, 0, None, 0))
src, _ = _open_source('/tmp/res_src.txt')
memfd, size = _spill_to_memfd(src)
os.lseek(memfd, 0, os.SEEK_SET)
lib.fr_py_ingest_done()
lib.fr_py_scan(memfd)
lib.fr_py_worker_init(0, -1, 0, 3, 0)
n = 0; total = 0; first = None; last = None
while True:
    c = FrPyBatch()
    rc = lib.fr_py_claim(ctypes.byref(c))
    if rc == 2: break
    if rc != 0: print('FAIL'); break
    if c.length:
        total += c.length
        if first is None: first = c.offset
        last = c.offset + c.length
    lib.fr_py_ack(-1, -1)
    n += 1
    if n > 500: break
print('horizon', H, '-> batches', n, 'payload bytes', total, 'first', first, 'last', last)
lib.fr_py_destroy()
