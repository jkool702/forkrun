import sys, time, os
sys.path.insert(0, 'python')
import forkrun
open('/tmp/blat.log','w').close()
def timed(batch):
    t0 = time.perf_counter()
    r = bytes(batch.data).upper()
    dt = time.perf_counter() - t0
    with open('/tmp/blat.log','a') as fh:
        fh.write('%.6f %d\n' % (dt, len(r)))
    return r
r = forkrun.map(timed, '/tmp/bm.txt', workers=1, streaming=True)
print('batches:', len(r), flush=True)
