import sys, os, resource
sys.path.insert(0, 'python')
import forkrun
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    chunk = b'x' * 999 + b'\n'
    for _ in range(1024 * 1024):  # 1GB
        os.write(w, chunk)
    os.close(w)
    os._exit(0)
os.close(w)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
def count(batch):
    return None
forkrun.run(count, r, workers=4, streaming=True)
os.close(r)
_, st = os.waitpid(pid, 0)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print('writer_exit=%d growth_mb=%.1f' % (os.WEXITSTATUS(st), (after - before) / 1024.0), flush=True)
