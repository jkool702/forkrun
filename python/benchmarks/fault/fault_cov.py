import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_medium
SRC = '/tmp/mldata/ml_medium.jsonl'
GT = '/tmp/gt_medium.bin'
if not os.path.exists(GT):
    res = forkrun.map(forkrun_payload_medium, SRC, workers=8, order='index')
    open(GT, 'wb').write(b'\n'.join(res))
    print('ground truth saved:', len(res), 'batches')
def lines(blob):
    return [l for l in blob.split(b'\n') if l.strip()]
gt = lines(open(GT, 'rb').read())
print('GT records:', len(gt))
CNT = '/tmp/fc2.cnt'; M = '/tmp/fc2.mk'
for f in (CNT, M):
    try: os.unlink(f)
    except OSError: pass
def payload(batch):
    with open(CNT, 'ab') as fh: fh.write(b'x')
    try: c = os.path.getsize(CNT)
    except OSError: c = 0
    if c >= 5:
        try:
            fd = os.open(M, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError:
            return forkrun_payload_medium(batch)
        import ctypes
        ctypes.string_at(0)
    return forkrun_payload_medium(batch)
res = forkrun.map(payload, SRC, workers=8, order='index', on_error='retry', orchestrator=True)
out = []
for b in res:
    out.extend(lines(b))
print('crashed output records:', len(out))
# prefix? scattered? duplicates?
prefix = sum(1 for a, b in zip(out, gt) if a == b)
print('longest common prefix with GT:', prefix)
from collections import Counter
co, cg = Counter(out), Counter(gt)
print('out multiset ⊆ GT:', not (co - cg))
print('GT missing from out:', sum((cg - co).values()))
print('out-of-order (in GT but misplaced):', len(out) - prefix if len(out) == len(set(map(bytes, out))) else 'dupes present')
