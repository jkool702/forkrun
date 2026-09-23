import sys, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_heavy
path = sys.argv[1]
so = '/tmp/ml_plugin_heavy.so'
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
py = records(forkrun.map(forkrun_payload_heavy, path, workers=4, order='index'))
pl = records(forkrun.map('%s:ml_process_heavy' % so, path, mode='plugin', workers=4, order='index'))
print('py records:', len(py), 'plugin records:', len(pl))
assert len(py) == len(pl), 'COUNT MISMATCH'
bad = 0; fh_skip = 0
for a, b in zip(py, pl):
    ka, kb = set(a.keys()), set(b.keys())
    if ka != kb:
        print('KEYS', ka ^ kb); bad += 1
        if bad > 4: break
        continue
    for k in a:
        if k in ('rv_fh', 'sq_fh'):
            fh_skip += 1
            continue  # SipHash-randomized vs FNV: incomparable by design
        va, vb = a[k], b[k]
        if isinstance(va, float) or isinstance(vb, float):
            denom = max(1.0, abs(float(va)), abs(float(vb)))
            if abs(float(va) - float(vb)) / denom > 1e-9:
                print('FLOAT', k, va, vb); bad += 1; break
        elif va != vb:
            print('VALUE', k, repr(va)[:60], repr(vb)[:60]); bad += 1; break
    if bad > 4: break
print('value mismatches:', bad, '(fh fields excluded: %d)' % fh_skip)
print('VALIDATION:', 'PASS' if bad == 0 else 'FAIL')
