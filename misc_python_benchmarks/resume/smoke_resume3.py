import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun._resume as R
_orig_begin = R.resume_begin
def _dbg_begin(lib, resume_path, **kw):
    print('BEGIN resume=%r kw=%r' % (resume_path, kw), flush=True)
    st = _orig_begin(lib, resume_path, **kw)
    print('BEGIN state=%r is_resume=%d' % (st, lib.fr_py_is_resume_mode()), flush=True)
    return st
R.resume_begin = _dbg_begin
import forkrun
SEEN = []
def upper(batch):
    SEEN.append((batch.byte_offset, batch.byte_offset + batch.byte_length))
    return bytes(batch.data).upper()
res = forkrun.map(upper, '/tmp/res_src.txt', workers=4, orchestrator=True, order='index', resume='/tmp/resume_smoke.ckpt')
print('records:', len(res), 'ranges seen:', len(SEEN), flush=True)
