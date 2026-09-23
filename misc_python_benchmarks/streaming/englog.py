import sys, importlib, os
sys.path.insert(0, 'python')
import forkrun
runmod = importlib.import_module('forkrun.run')
orig_snap = runmod.snapshot_fds
calls = [0]
def logged_snap():
    s = orig_snap()
    calls[0] += 1
    with open('/tmp/eng.log', 'a') as fh:
        fh.write('snap#%d pid=%d: %s\n' % (calls[0], os.getpid(), sorted(s)))
    return s
runmod.snapshot_fds = logged_snap
open('/tmp/eng.log','w').close()
open('/tmp/si.txt','w').write('a\nb\n')
def predictive_geo_mean(xs):
    return xs
r = forkrun.map(lambda b: bytes(b.data), '/tmp/si.txt', workers=1, streaming=True)
print('result:', r, flush=True)
