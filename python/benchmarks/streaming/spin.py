import sys, time
sys.path.insert(0, 'python')
import forkrun
open('/tmp/big.txt','w').write(''.join('line %06d payload-data here and more padding bytes\n'%i for i in range(3000000)))
t0=time.perf_counter()
r = forkrun.map(lambda b: bytes(b.data).upper(), '/tmp/big.txt', workers=8, streaming=True)
print('done %.2fs batches=%d' % (time.perf_counter()-t0, len(r)), flush=True)
