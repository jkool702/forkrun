import sys, time, os, importlib
sys.path.insert(0, 'python')
import forkrun
wmod = importlib.import_module('forkrun._worker')
orig_coerce = wmod._coerce_result
def timed_coerce(ret):
    # marker: called inside worker per batch; log claim-to-here via side channel is complex.
    return orig_coerce(ret)
# Simpler: measure in payload wrapper (payload time) vs total wall.
# Instead, time the whole map and subtract payload sum + parent costs.
t0=time.perf_counter()
open('/tmp/blat.log','w').close()
def timed(batch):
    t0b = time.perf_counter()
    r = bytes(batch.data).upper()
    dt = time.perf_counter() - t0b
    with open('/tmp/blat.log','a') as fh:
        fh.write('%.6f\n' % dt)
    return r
r = forkrun.map(timed, '/tmp/bm.txt', workers=1, streaming=True)
dt = time.perf_counter()-t0
import statistics
dts = sorted(float(x)*1e6 for x in open('/tmp/blat.log'))
print('wall=%.3f payload_sum=%.3f batches=%d' % (dt, sum(dts)/1e6, len(r)), flush=True)
