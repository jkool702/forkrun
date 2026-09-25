import sys, os, time
sys.path.insert(0, 'python')
import forkrun
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    for i in range(12):
        os.write(w, ('line %d\n' % i).encode())
        time.sleep(0.5)
    os.close(w)
    os._exit(0)
os.close(w)
open('/tmp/started3','w').write('go')
r2 = forkrun.map(lambda b: bytes(b.data), r, workers=2, streaming=True, order='index')
print('batches:', len(r2), flush=True)
os.close(r)
os.waitpid(pid, 0)
