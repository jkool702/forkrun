import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
SRC = '/tmp/for2_src.txt'
with open(SRC, 'w') as fh:
    for i in range(20000):
        fh.write('line %05d\n' % i)
CNT = '/tmp/for2.cnt'; CK = '/tmp/for2.ckpt'
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
except RuntimeError:
    print('aborted')
print(open(CK).read().strip())
