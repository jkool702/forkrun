import sys
sys.path.insert(0, 'python')
import forkrun
open('/tmp/diag.txt','w').write(''.join('line %d\n'%i for i in range(1500)))
exp = open('/tmp/diag.txt','rb').read()
out = list(forkrun.stream('cat', '/tmp/diag.txt', mode='spawn', workers=4, order='index'))
got = b''.join(out)
if got != exp:
    open('/tmp/got.bin','wb').write(got)
    open('/tmp/exp.bin','wb').write(exp)
    print('SAVED MISMATCH', len(got), len(exp))
else:
    print('ok')
