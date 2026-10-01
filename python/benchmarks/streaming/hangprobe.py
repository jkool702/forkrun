import sys, os, time, faulthandler; sys.path.insert(0, 'python')
faulthandler.dump_traceback_later(50, exit=True)
import forkrun
def up(b):
    return bytes(b.data).upper()
for i in range(12):
    t0 = time.monotonic()
    try:
        a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True, ))
    except Exception as e:
        print(i, 'EXC', e, flush=True); break
    dt = time.monotonic() - t0
    print(i, 'ok', len(a), '%.1fs' % dt, flush=True)
    assert len(a) == 18, (i, len(a))
