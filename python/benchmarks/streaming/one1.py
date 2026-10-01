import sys
sys.path.insert(0, 'python')
import forkrun
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=1, streaming=True)
print('batches:', len(r), flush=True)
