import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
from forkrun._checkpoint import parse_checkpoint
SRC = '/tmp/st_src.txt'
with open(SRC, 'w') as fh:
    for i in range(20000):
        fh.write('line %05d\n' % i)
CK = '/tmp/st.ckpt'
import os
for f in (CK, CK + '.coll'):
    try: os.unlink(f)
    except OSError: pass
gen = forkrun.stream(lambda b: bytes(b.data).upper(), SRC, workers=4, orchestrator=True, order='index', checkpoint_file=CK)
seen = []
try:
    for i, blob in enumerate(gen):
        seen.append(blob)
        if i >= 19: break
finally:
    gen.close()
st = parse_checkpoint(CK)
print('consumed blobs:', len(seen), 'horizon:', st.horizon, 'jagged:', len(st.jagged))
res = list(forkrun.stream(lambda b: bytes(b.data).upper(), SRC, workers=4, orchestrator=True, order='index', resume=CK))
print('resumed blobs:', len(res))
