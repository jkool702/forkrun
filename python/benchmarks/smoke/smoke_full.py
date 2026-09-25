import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
res = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/res_src.txt', workers=4, orchestrator=True, order='index')
open('/tmp/full_out.bin','wb').write(b''.join(res))
print('full records:', len(res))
