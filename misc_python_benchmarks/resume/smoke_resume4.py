import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
def upper(batch):
    return bytes(batch.data).upper()
res = forkrun.map(upper, '/tmp/res_src.txt', workers=4, orchestrator=True, order='index', resume='/tmp/resume_smoke.ckpt')
print('records:', len(res))
for r in res:
    print(len(r), r[:40])
