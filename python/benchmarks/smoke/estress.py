import os, sys, subprocess, tempfile
sys.path.insert(0, 'python'); sys.path.insert(0, 'python/tests')
import forkrun
from _helpers import write_lines
subprocess.run(['gcc','-shared','-fPIC','-O2','-o','/tmp/x.so','python/tests/plugins/test_plugin_v1.c'], check=True)
fd, path = tempfile.mkstemp(suffix='.txt'); os.close(fd)
write_lines(path, 1500)
exp = open(path,'rb').read()
ok = True
out = list(forkrun.stream(lambda b: bytes(b.data).upper(), path, workers=4, order='index'))
if b''.join(out) != exp.upper(): print('STREAM MISMATCH'); ok = False
out = forkrun.map(lambda b: bytes(b.data).upper(), path, workers=4, order='index')
if b''.join(out) != exp.upper(): print('MAP MISMATCH'); ok = False
out = forkrun.map('cat', path, mode='spawn', workers=4, order='index')
if b''.join(out) != exp: print('SPAWN MISMATCH'); ok = False
print('ok' if ok else 'BAD')
os.unlink(path)
