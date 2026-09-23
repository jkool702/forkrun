import sys, importlib, time
sys.path.insert(0, 'python')
import forkrun
runmod = importlib.import_module('forkrun.run')
orig_scrub = runmod.scrub_fds
def logged_scrub(keep, quiet=True):
    import os
    try:
        n = orig_scrub(keep, quiet)
    except Exception as e:
        with open('/tmp/keep.log', 'a') as fh:
            fh.write('pid=%d SCRUB RAISED %r keep=%s\n' % (os.getpid(), e, sorted(keep)))
        raise
    with open('/tmp/keep.log', 'a') as fh:
        fh.write('pid=%d closed=%d keep=%s\n' % (os.getpid(), n, sorted(keep)))
    return n
runmod.scrub_fds = logged_scrub
open('/tmp/keep.log','w').close()
def slow(batch):
    time.sleep(0.3)
    return bytes(batch.data)
r = forkrun.map(slow, '/tmp/big.txt', workers=2, streaming=True)
print('batches:', len(r), flush=True)
