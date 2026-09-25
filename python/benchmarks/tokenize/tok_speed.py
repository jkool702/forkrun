import sys, time, statistics, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python'); sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from tokenize_payload import Tokenizer, batch_payload
os.environ['FORKRUN_VOCAB_PATH'] = '/tmp/tok.jsonl.vocab'
tok = Tokenizer(vocab_path='/tmp/tok.jsonl.vocab')
def py_payload(batch):
    return b'\n'.join(batch_payload([l for l in bytes(batch.data).split(b'\n') if l.strip()], tok)) or None
for label, fn in (('python', lambda: forkrun.map(py_payload, '/tmp/tok.jsonl', workers=8, order='index')),
                  ('plugin', lambda: forkrun.map('/tmp/tokenize_plugin.so:ml_tokenize', '/tmp/tok.jsonl', mode='plugin', workers=8, order='index'))):
    ts = []
    for _ in range(3):
        t0 = time.perf_counter(); r = fn(); ts.append(time.perf_counter()-t0)
    print('%s: %d docs %.0f docs/s' % (label, len(r), 3000/statistics.median(ts)), flush=True)
