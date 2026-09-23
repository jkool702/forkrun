import sys, ctypes
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
from forkrun._bindings import load, find_substrate, FrPyBatch
from forkrun._checkpoint import parse_checkpoint
from forkrun.run import _spill_to_memfd, _open_source
from forkrun._bindings import FrPyInterval

lib = load(find_substrate())
lib.fr_py_init(0, 0)
st = parse_checkpoint('/tmp/resume_smoke.ckpt')
arr = None
lib.fr_py_set_resume_state(st.horizon, st.stdout_bytes, arr, 0)
lib.fr_py_worker_init(0, -1, 0, 3, 0)
src, _ = _open_source('/tmp/res_src.txt')
memfd, size = _spill_to_memfd(src)
lib.fr_py_ingest_done()
print('scan:', lib.fr_py_scan(memfd))
n = 0
while True:
    c = FrPyBatch()
    rc = lib.fr_py_claim(ctypes.byref(c))
    if rc == 2:
        print('EOF after', n, 'claims')
        break
    if rc != 0:
        print('FAIL rc', rc); break
    print('claim', n, 'idx', c.batch_idx, 'off', c.offset, 'len', c.length, 'lines', c.lines, 'kills', c.num_kills, 'poison', c.poisoned)
    lib.fr_py_ack(-1, -1)
    n += 1
    if n > 10: print('...'); break
lib.fr_py_destroy()
