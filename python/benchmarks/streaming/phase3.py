import sys, time
sys.path.insert(0, 'python')
import forkrun
open('/tmp/started4','w').write('go')
t0=time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
print('done %.3fs batches=%d' % (time.perf_counter()-t0, len(r)), flush=True)
