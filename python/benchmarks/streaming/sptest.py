import sys
sys.path.insert(0, 'python')
import forkrun
r = forkrun.map(None, '/tmp/t10M.txt', mode='splice', bytes=512*1024, workers=4)
print('batches:', len(r), flush=True)
