import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun, json
from ml_payload import forkrun_payload_medium
SRC = '/tmp/mldata/ml_medium.jsonl'
CNT = '/tmp/fpf.cnt'; M = '/tmp/fpf.mk'
for f in (CNT, M):
    try: os.unlink(f)
    except OSError: pass
def payload(batch):
    with open(CNT, 'ab') as fh: fh.write(b'x')
    try: c = os.path.getsize(CNT)
    except OSError: c = 0
    if c >= 5:
        try:
            fd = os.open(M, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError:
            return forkrun_payload_medium(batch)
        import ctypes
        ctypes.string_at(0)
    return forkrun_payload_medium(batch)
res = forkrun.map(payload, SRC, workers=8, order='index', on_error='retry', orchestrator=True)
lines = []
for b in res:
    for line in b.split(b'\n'):
        line = line.strip()
        if line:
            lines.append(json.loads(line)['eid'])
print('n=%d first=%s last=%s contiguous-prefix=%s' % (
    len(lines), lines[0] if lines else None, lines[-1] if lines else None,
    all(lines[i] <= lines[i+1] for i in range(len(lines)-1))))
import re
nums = []
for e in lines:
    m = re.search(r'evt_([0-9a-f]+)', e)
    nums.append(m.group(1) if m else '?')
print('sample eids:', lines[:3], '...', lines[-3:] if len(lines) > 3 else '')
