import os, sys, subprocess, tempfile
sys.path.insert(0, 'python'); sys.path.insert(0, 'python/tests')
import forkrun
from _helpers import write_lines, assert_no_zombies
# replicate setUpModule gcc prelude
subprocess.run(['gcc','-shared','-fPIC','-O2','-o','/tmp/x.so','python/tests/plugins/test_plugin_v1.c'], check=True)
fd, path = tempfile.mkstemp(suffix='.txt')
os.close(fd)
try:
    write_lines(path, 1500)
    out = list(forkrun.stream('cat', path, mode='spawn', workers=4, order='index'))
    got = b''.join(out)
    exp = open(path,'rb').read()
    if got != exp:
        open('/tmp/got.bin','wb').write(got); open('/tmp/exp.bin','wb').write(exp)
        print('SAVED MISMATCH', len(got), len(exp))
    else:
        print('ok')
finally:
    os.unlink(path)
