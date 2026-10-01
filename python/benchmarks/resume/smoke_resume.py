import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun

SRC = '/tmp/res_src.txt'
with open(SRC, 'w') as fh:
    for i in range(20000):
        fh.write('line %05d\n' % i)

FAIL_AT = 'line 19000\n'

def flaky(batch):
    data = bytes(batch.data)
    if FAIL_AT.encode() in data:
        raise RuntimeError('synthetic abort')
    return data.upper()

CKPT = '/tmp/resume_smoke.ckpt'
for f in (CKPT, CKPT + '.coll'):
    import os
    try: os.unlink(f)
    except OSError: pass

try:
    forkrun.map(flaky, SRC, workers=4, orchestrator=True, order='index',
                on_error='fail-fast', checkpoint_file=CKPT)
    print('FIRST RUN COMPLETED (unexpected)')
except RuntimeError as e:
    print('first run aborted:', str(e)[:60])

import os
print('checkpoint exists:', os.path.exists(CKPT))
if os.path.exists(CKPT):
    print(open(CKPT).read()[:300])
print('sidecar exists:', os.path.exists(CKPT + '.coll'))
