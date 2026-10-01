import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
def up(b): return bytes(b.data).upper()
open('/tmp/mini.txt','w').write(''.join('line %d\n' % i for i in range(2000)))
print('forkrun:', len(forkrun.map(up, '/tmp/mini.txt', workers=2)), flush=True)
pid = os.fork()
if pid == 0:
    print('plain-fork-child-alive', flush=True)
    os._exit(0)
_, st = os.waitpid(pid, 0)
print('plain fork after map: ok', st)
