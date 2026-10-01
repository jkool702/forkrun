import sys, os, tempfile
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import ray
from ml_payload import process_event_medium
D = tempfile.mkdtemp(prefix='rayfault_')
M = os.path.join(D, 'm')
SRC = '/tmp/mldata/ml_medium.jsonl'
def batch_fn(df):
    import pandas as pd, os as _o, ctypes
    if not _o.path.exists(M):
        open(M, 'w').write('1')
        ctypes.string_at(0)
    out = []
    for text in df['text'].tolist():
        text = (text or '').strip()
        if not text:
            out.append(None); continue
        try:
            r = process_event_medium(text.encode())
            out.append(r.decode() if isinstance(r, bytes) else r)
        except ValueError:
            out.append(None)
    return pd.DataFrame({'result': out})
import os as _os2
ray.init(ignore_reinit_error=True, num_cpus=8, log_to_driver=False, runtime_env={'env_vars': {'PYTHONPATH': '/mnt/ramdisk/forkrun/python/benchmarks'}})
try:
    ds = ray.data.read_text(SRC)
    mapped = ds.map_batches(batch_fn, batch_format='pandas', concurrency=8)
    n = mapped.count()
    print('RAY-FAULT-SURVIVED count=', n, flush=True)
except Exception as e:
    print('RAY-FAULT-DIED', type(e).__name__, str(e)[:200].replace('\n',' '), flush=True)
finally:
    ray.shutdown()
