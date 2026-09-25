import os, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load, get
import forkrun
lib = load()
_orig_claim = lib.fr_py_claim
_orig_ack = lib.fr_py_ack
def claimounters(claimed):
    import ctypes
    rc = _orig_claim(claimed)
    return rc
lib.fr_py_claim = claimounters
# count via file (stderr interleaves badly across processes; use atomic append)
def logged_claim(claimed):
    rc = _orig_claim(claimed)
    with open('/tmp/claims.log', 'a') as fh:
        fh.write('pid=%d rc=%d idx=%d len=%d\n' % (os.getpid(), rc, claimed.batch_idx, claimed.length))
    return rc
def logged_ack(a, b):
    rc = _orig_ack(a, b)
    with open('/tmp/claims.log', 'a') as fh:
        fh.write('pid=%d ack(%d,%d)=%d\n' % (os.getpid(), a, b, rc))
    return rc
lib.fr_py_claim = logged_claim
lib.fr_py_ack = logged_ack
open('/tmp/claims.log','w').close()
open('/tmp/q.txt','w').write('a\nb\nc\n')
try:
    r = forkrun.map(lambda b: bytes(b.data), '/tmp/q.txt', workers=1, streaming=True)
    print('RESULT:', r)
except Exception as e:
    print('RAISED:', repr(e))
