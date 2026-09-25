import os, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load
import forkrun
lib = load()
_orig_done = lib.fr_py_ingest_done
_orig_scan = lib.fr_py_scan
def logged_done():
    # find memfd size: scan /proc/self/fd for memfd_create inodes is hard;
    # instead report via run.py internals is skipped — just log the call
    with open('/tmp/claims.log', 'a') as fh:
        fh.write('parent: ingest_done called\n')
    return _orig_done()
lib.fr_py_ingest_done = logged_done
open('/tmp/claims.log','w').close()
open('/tmp/q.txt','w').write('a\nb\nc\n')
# also log os.write targets by wrapping in run module namespace
import forkrun.run as runmod
_orig_write = os.write
def logged_write(fd, data):
    n = _orig_write(fd, data)
    try:
        name = os.readlink('/proc/self/fd/%d' % fd)
    except OSError:
        name = '?'
    with open('/tmp/claims.log', 'a') as fh:
        fh.write('parent: write fd=%d(%s) req=%d wrote=%d\n' % (fd, name, len(data), n))
    return n
os.write = logged_write
try:
    r = forkrun.map(lambda b: bytes(b.data), '/tmp/q.txt', workers=1, streaming=True)
    print('RESULT:', r)
except Exception as e:
    print('RAISED:', repr(e))
finally:
    os.write = _orig_write
