import sys, time
sys.path.insert(0, 'python')
import forkrun
t0=time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=1, streaming=True)
dt = time.perf_counter()-t0
print('wall=%.3f batches=%d' % (dt, len(r)), flush=True)
