import sys, os; sys.path.insert(0, 'python')
import forkrun.run as RM
orig_loop = None
import forkrun._reactor as R
olog = R.reactor_loop
def logged_loop(state, drain_gen=None, poll_timeout=0.1, service=None):
    import time
    t0 = time.monotonic()
    n = [0]
    orig_gen = drain_gen
    def counted():
        n[0] += 1
        try:
            return orig_gen()
        except StopIteration:
            print('PUMP-Stop t=%.2f rounds=%d' % (time.monotonic()-t0, n[0]), flush=True)
            raise
    try:
        for x in olog(state, drain_gen=counted if orig_gen else None, poll_timeout=poll_timeout, service=service):
            yield x
    finally:
        print('LOOP-END t=%.2f rounds=%d live=%s forked-state' % (time.monotonic()-t0, n[0], [ (w, s.alive) for w, s in state.workers.items()]), flush=True)
R.reactor_loop = logged_loop
import forkrun
def up(b):
    return bytes(b.data).upper()
for i in range(6):
    try:
        a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True))
        print(i, 'ok', len(a), flush=True)
    except Exception as e:
        print(i, 'EXC', type(e).__name__, str(e)[:60], flush=True)
