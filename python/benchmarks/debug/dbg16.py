import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load, FrPyBatch
from forkrun.run import (_close_all_except, _new_ingress_memfd,
                         _new_output_memfds)
lib = load()
lib.fr_py_init(0, 0)
src = os.open('/tmp/q.txt', os.O_RDONLY)
memfd, _hold = _new_ingress_memfd()
os.lseek(memfd, 0, 0)
out_fds, _oh = _new_output_memfds(1)
spid = os.fork()
if spid == 0:
    _close_all_except({memfd})
    rc = lib.fr_py_scan(memfd)
    os._exit(0 if rc == 0 else 5)
while True:
    ch = os.read(src, 1 << 20)
    if not ch: break
    n = os.write(memfd, ch)
    print('spilled %d bytes' % n, flush=True)
lib.fr_py_ingest_done()
print('gate set', flush=True)
_, st = os.waitpid(spid, 0)
print('scanner exit:', os.WEXITSTATUS(st) if os.WIFEXITED(st) else st, flush=True)
print('memfd size now:', os.fstat(memfd).st_size, flush=True)
