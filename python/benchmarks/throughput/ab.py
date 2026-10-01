import sys, time, os
sys.path.insert(0, 'python')
mode = sys.argv[1]
if mode == 'v0': os.environ['FORKRUN_NO_V1'] = '1'
import forkrun
lines = int(sys.argv[2])
best = 0
for t in range(3):
    t0=time.perf_counter()
    forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, lines=lines)
    dt=time.perf_counter()-t0
    best = max(best, 400000/dt)
print('%s lines=%s: %.1f' % (mode, lines, best))
