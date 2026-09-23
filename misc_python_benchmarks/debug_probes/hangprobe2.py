import sys, os, time, importlib; sys.path.insert(0, 'python')
RM = importlib.import_module('forkrun.run')
t0 = [time.monotonic()]
of = RM._fork_drain
def lf(signal_r, out_fds, workers, mode='memfd'):
    print('DRAINFORK sig=%d nout=%d mode=%s t=%.2f' % (signal_r, len(out_fds), mode, time.monotonic()-t0[0]), flush=True)
    return of(signal_r, out_fds, workers, mode=mode)
RM._fork_drain = lf
import forkrun._reactor as R
o = R.ReactorState.spawn_worker
def ls(self, wid=None, node=0):
    print('FORK wid=%s node=%s t=%.2f' % (wid, node, time.monotonic()-t0[0]), flush=True)
    return o(self, wid=wid, node=node)
R.ReactorState.spawn_worker = ls
from forkrun._bindings import get
lib = get()
or0 = lib.fr_py_data_ready_node
def lr(n):
    r = or0(n)
    if r: print('READY n=%d r=%d t=%.2f' % (n, r, time.monotonic()-t0[0]), flush=True)
    return r
lib.fr_py_data_ready_node = lr
import forkrun
def up(b):
    return bytes(b.data).upper()
a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True))
print('done', len(a), flush=True)
