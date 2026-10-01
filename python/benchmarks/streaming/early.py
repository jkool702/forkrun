import sys, time, os
sys.path.insert(0, 'python')
import forkrun
open('/tmp/started2', 'w').write('go')
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/bm.txt', workers=8, streaming=True)
print('batches:', len(r), flush=True)
