import sys, importlib, faulthandler
sys.path.insert(0, 'python')
import forkrun
wmod = importlib.import_module('forkrun._worker')
orig_run = wmod._run
def wrapped(*a, **k):
    faulthandler.dump_traceback_later(0.06, exit=True)
    try:
        return orig_run(*a, **k)
    finally:
        faulthandler.cancel_dump_traceback_later()
wmod._run = wrapped
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
print('batches:', len(r), flush=True)
