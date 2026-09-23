import sys, os, resource, time
sys.path.insert(0, 'python')
import forkrun
open('/tmp/sink.out','wb').close()
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    chunk = b'x' * 999 + b'\n'
    for _ in range(1024 * 1024):
        os.write(w, chunk)
    os.close(w)
    os._exit(0)
os.close(w)
t0 = time.perf_counter()
def count(batch):
    return b''
def sink(meta, result):
    with open('/tmp/sink.out','ab') as fh:
        fh.write(b'%d\n' % meta.batch_index)
forkrun.run(count, r, workers=4, streaming=True, sink=sink)
os.close(r)
os.waitpid(pid, 0)
dt = time.perf_counter() - t0
n = sum(1 for _ in open('/tmp/sink.out','rb'))
print('batches=%d time=%.1fs rate=%.1f lines/s' % (n, dt, 1024*1024/dt), flush=True)
