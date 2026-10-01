import sys, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python'); sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from tokenize_payload import Tokenizer, batch_payload
import os
os.environ['FORKRUN_VOCAB_PATH'] = '/tmp/tok.jsonl.vocab'
tok = Tokenizer(vocab_path='/tmp/tok.jsonl.vocab')
def py_payload(batch):
    return b'\n'.join(batch_payload([l for l in bytes(batch.data).split(b'\n') if l.strip()], tok)) or None
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line: out.append(json.loads(line))
    return out
py = records(forkrun.map(py_payload, '/tmp/bigdocs2.jsonl', workers=4, order='index'))
pl = records(forkrun.map('/tmp/tokenize_plugin.so:ml_tokenize', '/tmp/bigdocs2.jsonl', mode='plugin', workers=4, order='index'))
print('py:', len(py), 'plugin:', len(pl))
assert len(py) == len(pl)
bad = 0
for a, b in zip(py, pl):
    if set(a.keys()) != set(b.keys()): print('KEYS'); bad += 1; break
    for k in a:
        va, vb = a[k], b[k]
        if k == 'diversity':
            if abs(float(va)-float(vb)) > 1e-9: print('DIV', va, vb); bad += 1; break
        elif va != vb: print('VALUE', k); bad += 1; break
    if bad: break
print('VALIDATION:', 'PASS' if bad == 0 else 'FAIL')
