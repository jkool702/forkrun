import sys, importlib
sys.path.insert(0, 'python')
import forkrun
runmod = importlib.import_module('forkrun.run')
orig_scrub = runmod.scrub_fds
def logged_scrub(keep, quiet=True):
    import os
    with open('/tmp/keep.log', 'a') as fh:
        fh.write('pid=%d keep=%s\n' % (os.getpid(), sorted(keep)))
    return orig_scrub(keep, quiet)
runmod.scrub_fds = logged_scrub
open('/tmp/keep.log','w').close()
open('/tmp/si.txt','w').write('a\nb\n')
r = forkrun.map(lambda b: bytes(b.data), '/tmp/si.txt', workers=1, streaming=True)
print('result:', r, flush=True)
