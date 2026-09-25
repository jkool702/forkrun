import os, ctypes, time, sys
sys.path.insert(0, 'python')
from forkrun._bindings import load, FrPyBatch
from forkrun.run import (_close_all_except, _new_ingress_memfd,
                         _new_output_memfds, _fork_ingest_helpers)
lib = load()
lib.fr_py_init(0, 0)
src = os.open('/tmp/q.txt', os.O_RDONLY)
memfd, _hold = _new_ingress_memfd()
os.lseek(memfd, 0, 0)
out_fds, _oh = _new_output_memfds(1)
fr, fw = os.pipe()
fpid, spid = _fork_ingest_helpers(lib, memfd, fr, fw)
wpid = os.fork()
if wpid == 0:
    _close_all_except({memfd, fw, out_fds[0]})
    lib.fr_py_worker_init(0, 0, 0, 3, 0)
    for _ in range(5):
        c = FrPyBatch(); r = lib.fr_py_claim(ctypes.byref(c))
        sys.stderr.write('claim %d idx %d len %d\n' % (r, c.batch_idx, c.length))
        if r != 0: break
        a = lib.fr_py_ack(fw, -1)
        sys.stderr.write('ack %d\n' % a)
    os._exit(0)
os.close(fr); os.close(fw)
while True:
    ch = os.read(src, 1 << 20)
    if not ch: break
    os.write(memfd, ch)
lib.fr_py_ingest_done()
_, st = os.waitpid(wpid, 0)
print('worker exit:', os.WEXITSTATUS(st) if os.WIFEXITED(st) else st, flush=True)
