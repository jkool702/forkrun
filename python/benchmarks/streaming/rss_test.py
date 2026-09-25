import sys, os, resource
sys.path.insert(0, 'python')
import forkrun
# generate 300MB via pipe (writer child), stream it
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    chunk = b'x' * 999 + b'\n'  # 1KB lines
    for _ in range(300 * 1024):
        os.write(w, chunk)
    os.close(w)
    os._exit(0)
os.close(w)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
n = [0]
def count(batch):
    n[0] += batch.byte_length
    return None
forkrun.run(count, r, workers=4, streaming=True)
os.close(r)
os.waitpid(pid, 0)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print('bytes=%d growth_mb=%.1f' % (n[0], (after - before) / 1024.0), flush=True)
