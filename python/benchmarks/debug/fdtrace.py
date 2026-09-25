import sys, os, importlib; sys.path.insert(0, 'python')
RM = importlib.import_module('forkrun.run')
of = RM._fork_drain
def lf(signal_r, out_fds, workers, mode='memfd'):
    import fcntl
    print('FORKDRAIN-IN sig=%d mode=%s' % (signal_r, mode), flush=True)
    pid, res = of(signal_r, out_fds, workers, mode=mode)
    print('FORKDRAIN-OUT pid=%d res=%d' % (pid, res), flush=True)
    return pid, res
RM._fork_drain = lf
omp = RM._make_results_pump
def lmp(results_r, order='none', stats=None):
    print('PUMP-MADE fd=%d order=%s' % (results_r, order), flush=True)
    return omp(results_r, order=order, stats=stats)
RM._make_results_pump = lmp
import forkrun
def up(b):
    return bytes(b.data).upper()
a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True))
print('done', len(a), flush=True)
