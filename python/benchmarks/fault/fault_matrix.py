import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_medium
SRC = '/tmp/mldata/ml_medium.jsonl'
WHICH, K = sys.argv[1], int(sys.argv[2])
CNT = '/tmp/fm_%s_%d.cnt' % (WHICH, K)
M = '/tmp/fm_%s_%d.mk' % (WHICH, K)
for f in (CNT, M):
    try: os.unlink(f)
    except OSError: pass
def payload(batch):
    with open(CNT, 'ab') as fh: fh.write(b'x')
    try: c = os.path.getsize(CNT)
    except OSError: c = 0
    if c >= K:
        try:
            fd = os.open(M, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError:
            return forkrun_payload_medium(batch)
        if WHICH == 'plugin':
            pass  # plugin path below uses C plugin; placeholder
        import ctypes
        ctypes.string_at(0)
    return forkrun_payload_medium(batch)
if WHICH == 'plugin':
    print('use plugin runner')
else:
    res = forkrun.map(payload, SRC, workers=8, order='index', on_error='retry', orchestrator=True)
    n = sum(1 for b in res for _ in b.split(b'\n') if _.strip())
    print('%s crash-at-%d: records %d' % (WHICH, K, n), flush=True)
