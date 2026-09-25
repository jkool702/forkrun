import os, sys, time, statistics
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
def noop(b): return None
path = '/tmp/w21b_lines.txt'
ts = []
for _ in range(5):
    t0 = time.perf_counter(); forkrun.map(noop, path, workers=8, lines=20); ts.append(time.perf_counter()-t0)
print('median %.1f ms' % (statistics.median(ts)*1000), flush=True)
