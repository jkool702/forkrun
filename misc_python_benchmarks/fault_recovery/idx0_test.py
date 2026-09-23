import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
SRC = '/tmp/mldata/ml_medium.jsonl'
M = '/tmp/idx0_marker'
try: os.unlink(M)
except OSError: pass
def crash0(batch):
    if batch.batch_index == 0 and not os.path.exists(M):
        open(M, 'w').write('1')
        import ctypes
        ctypes.string_at(0)
    data = bytes(batch.data)
    import json
    from ml_payload import process_event_medium
    import sys as _s; _s.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
    out = []
    for line in data.split(b'\n'):
        line = line.strip()
        if not line: continue
        try:
            r = process_event_medium(line)
            if r is not None: out.append(r)
        except ValueError:
            continue
    return b'\n'.join(out) if out else None
res = forkrun.map(crash0, SRC, workers=8, order='index', on_error='retry', orchestrator=True)
n = sum(1 for b in res for _ in b.split(b'\n') if _.strip())
print('idx0-crash survived, records:', n)
