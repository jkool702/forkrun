import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun

SRC = '/tmp/res_src.txt'
SEEN = []
def upper(batch):
    data = bytes(batch.data)
    SEEN.append((batch.byte_offset, batch.byte_offset + batch.byte_length))
    return data.upper()

CKPT = '/tmp/resume_smoke.ckpt'
res = forkrun.map(upper, SRC, workers=4, orchestrator=True, order='index',
                  resume=CKPT)
flat = b''.join(res)
expect = open(SRC, 'rb').read().upper()
print('resumed records:', len(res), 'complete:', flat == expect)
print('sidecar consumed:', __import__('os').path.exists(CKPT + '.coll') == False)
# byte ranges processed during resume should avoid committed prefix [0,208384)
import re
ckpt_horizon = 208384
overlap = [iv for iv in SEEN if iv[0] < ckpt_horizon]
print('resume processed %d ranges, %d overlap committed prefix' % (len(SEEN), len(overlap)))
