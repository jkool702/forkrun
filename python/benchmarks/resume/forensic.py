import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
from collections import Counter
SRC = '/tmp/for_src.txt'
with open(SRC, 'w') as fh:
    for i in range(20000):
        fh.write('line %05d\n' % i)
CNT = '/tmp/for.cnt'; CK = '/tmp/for.ckpt'
for f in (CNT, CK, CK + '.coll'):
    try: os.unlink(f)
    except OSError: pass
def flaky(batch):
    with open(CNT, 'ab') as fh: fh.write(b'x')
    try: c = os.path.getsize(CNT)
    except OSError: c = 0
    if c >= 8: raise RuntimeError('abort')
    return bytes(batch.data).upper()
try:
    forkrun.map(flaky, SRC, workers=2, orchestrator=True, order='index', on_error='fail-fast', checkpoint_file=CK)
except RuntimeError as e:
    print('aborted')
print(open(CK).read())
def lines_list(blob):
    out = []
    for line in blob.split(b'\n'):
        if line.startswith(b'LINE '):
            try: out.append(int(line[5:]))
            except ValueError: pass
    return out
with open(CK + '.coll', 'rb') as fh:
    side = lines_list(fh.read())
print('sidecar: n=%d unique=%d min=%d max=%d' % (len(side), len(set(side)), min(side), max(side)))
cs = Counter(side)
print('sidecar dupes:', [(l, c) for l, c in cs.items() if c > 1][:10])
res = forkrun.map(lambda b: bytes(b.data).upper(), SRC, workers=4, orchestrator=True, order='index', resume=CK)
flat = b''.join(res)
rl = lines_list(flat)
print('resumed: n=%d unique=%d' % (len(rl), len(set(rl))))
cr = Counter(rl)
print('resumed dupes:', [(l, c) for l, c in cr.items() if c > 1][:10])
print('sidecar missing from resumed:', sorted(set(side) - set(rl))[:10])
