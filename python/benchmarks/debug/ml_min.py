import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun, multiprocessing
def up(b): return bytes(b.data).upper()
open('/tmp/mini.txt','w').write(''.join('line %d\n' % i for i in range(2000)))
print('forkrun:', len(forkrun.map(up, '/tmp/mini.txt', workers=2)), flush=True)
def sq(x): return x*x
with multiprocessing.Pool(2) as p:
    print('pool:', p.map(sq, range(10)), flush=True)
print('DONE')
