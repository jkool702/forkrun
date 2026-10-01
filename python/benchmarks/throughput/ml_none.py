import sys, time, statistics
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_light, forkrun_payload_medium, forkrun_payload_heavy
for variant, payload in (('light', forkrun_payload_light), ('medium', forkrun_payload_medium), ('heavy', forkrun_payload_heavy)):
    path = '/tmp/mldata/ml_%s.jsonl' % variant
    import os
    n = sum(1 for _ in open(path, 'rb'))
    for order in ('index', 'none'):
        ts = []
        for _ in range(3):
            t0 = time.perf_counter()
            res = forkrun.map(payload, path, workers=14, order=order)
            ts.append(time.perf_counter() - t0)
        dt = statistics.median(ts)
        print('forkrun-%s order=%s: %.0f records/s (%d records returned)' % (variant, order, n/dt, len(res)), flush=True)
