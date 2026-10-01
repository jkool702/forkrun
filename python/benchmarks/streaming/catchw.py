import sys, time
sys.path.insert(0, 'python')
import forkrun
def slow(batch):
    time.sleep(0.3)
    return bytes(batch.data)
r = forkrun.map(slow, '/tmp/big.txt', workers=2, streaming=True)
print('done batches=%d' % len(r), flush=True)
