import os, sys
sys.path.insert(0, 'python')
import forkrun
from forkrun._bindings import load
lib = load()
lib.fr_py_init(0, 0)
open('/tmp/q.txt','w').write('a\nb\nc\n')
# replicate locked ingest topology minimally via real functions is complex;
# instead: drive map() and inspect worker status via monkeypatched waitpid
import forkrun.run as runmod
orig_waitpid = os.waitpid
statuses = []
def spy_waitpid(pid, opts):
    r = orig_waitpid(pid, opts)
    if opts == 0:
        statuses.append((pid, r[1]))
    return r
os.waitpid = spy_waitpid
try:
    forkrun.map(lambda b: bytes(b.data), '/tmp/q.txt', workers=1, streaming=True)
except Exception as e:
    print('RAISED:', repr(e))
finally:
    os.waitpid = orig_waitpid
for pid, st in statuses:
    if os.WIFEXITED(st): print('pid', pid, 'exit', os.WEXITSTATUS(st))
    elif os.WIFSIGNALED(st): print('pid', pid, 'SIGNAL', os.WTERMSIG(st))
    else: print('pid', pid, 'raw', st)
