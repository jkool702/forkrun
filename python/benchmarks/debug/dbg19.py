import os, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load
import forkrun, forkrun.run as runmod
lib = load()
def log(msg):
    with open('/tmp/t.log', 'a') as fh:
        fh.write('parent: %s\n' % msg)
orig_dr = lib.fr_py_data_ready
def logged_dr():
    v = orig_dr()
    return v
lib.fr_py_data_ready = logged_dr
orig_fork = os.fork
forks = [0]
def logged_fork():
    pid = orig_fork()
    if pid != 0:
        forks[0] += 1
        log('fork #%d -> %d' % (forks[0], pid))
    return pid
os.fork = logged_fork
orig_claim = lib.fr_py_claim
def logged_claim(c):
    r = orig_claim(c)
    with open('/tmp/t.log', 'a') as fh:
        fh.write('pid=%d claim rc=%d idx=%d len=%d\n' % (os.getpid(), r, c.batch_idx, c.length))
    return r
lib.fr_py_claim = logged_claim
open('/tmp/t.log','w').close()
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    chunk = b'x' * 999 + b'\n'
    for i in range(3000):
        os.write(w, chunk)
    os.close(w)
    os._exit(0)
os.close(w)
n = [0]
def count(batch):
    n[0] += batch.byte_length
    return None
try:
    forkrun.run(count, r, workers=2, streaming=True)
    log('run returned bytes=%d' % n[0])
except Exception as e:
    log('run raised %r' % e)
os.close(r)
os.waitpid(pid, 0)
