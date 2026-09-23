import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
from forkrun._bindings import load, find_substrate
from forkrun._checkpoint import parse_checkpoint
from forkrun.run import _spill_to_memfd, _open_source

lib = load(find_substrate())
print('init:', lib.fr_py_init(0, 0))
st = parse_checkpoint('/tmp/resume_smoke.ckpt')
print('ckpt:', st)
from forkrun._bindings import FrPyInterval
arr = (FrPyInterval * len(st.jagged))(*[FrPyInterval(s, e) for s, e in st.jagged]) if st.jagged else None
print('set:', lib.fr_py_set_resume_state(st.horizon, st.stdout_bytes, arr, len(st.jagged)))
print('is_resume:', lib.fr_py_is_resume_mode())
src, _ = _open_source('/tmp/res_src.txt')
memfd, size = _spill_to_memfd(src)
print('spilled:', size)
print('ingest_done:', lib.fr_py_ingest_done())
print('scan:', lib.fr_py_scan(memfd))
print('data_ready:', lib.fr_py_data_ready())
print('eof_posted:', lib.fr_py_ingest_eof_posted())
lib.fr_py_destroy()
