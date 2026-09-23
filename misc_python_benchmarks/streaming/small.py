import sys
sys.path.insert(0, 'python')
import forkrun
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/si.txt', workers=2, streaming=True, order='index')
print('batches:', len(r), flush=True)
