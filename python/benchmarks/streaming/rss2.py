import sys, os
sys.path.insert(0, 'python')
import forkrun
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
forkrun.run(count, r, workers=2, streaming=True)
os.close(r)
_, st = os.waitpid(pid, 0)
print('bytes=%d writer_exit=%d' % (n[0], os.WEXITSTATUS(st)), flush=True)
