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
    os.write(memfd, ch)
lib.fr_py_ingest_done()
wpid, st = os.waitpid(spid, os.WNOHANG)
print('scanner immediate reap: wpid=%d' % wpid, flush=True)
time.sleep(1.0)
wpid, st = os.waitpid(spid, os.WNOHANG)
print('scanner after 1s: wpid=%d status=%r' % (wpid, st if wpid else None), flush=True)
print('proc state:', open('/proc/%d/status' % spid).read().split('State:')[1].split('\n')[0] if os.path.exists('/proc/%d' % spid) else 'GONE', flush=True)
