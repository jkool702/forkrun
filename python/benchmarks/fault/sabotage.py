import sys
sys.path.insert(0, 'python')
import forkrun._worker as w
w._cloexec_all = lambda: None  # sabotage
import tempfile, time, os
sys.path.insert(0, 'python/tests')
from _helpers import write_lines
import forkrun
fd, path = tempfile.mkstemp(suffix='.txt'); os.close(fd)
write_lines(path, 20)
t0 = time.monotonic()
out = list(forkrun.stream(['sh','-c','sleep 12 >/dev/null 2>&1 &'], path, mode='spawn', workers=2))
print('elapsed %.1f out=%r' % (time.monotonic()-t0, out))
os.unlink(path)
