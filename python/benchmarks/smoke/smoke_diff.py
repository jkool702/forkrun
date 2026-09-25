import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
# fresh full run for reference
full = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/res_src.txt', workers=4, orchestrator=True, order='index')
print('full records:', len(full))
# aborted+resumed union: re-run the cycle in-process sequentially is impossible (engine lock ok sequential)
