import sys, json, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python'); sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from tokenize_payload import Tokenizer, batch_payload
os.environ['FORKRUN_VOCAB_PATH'] = sys.argv[2] + '.vocab'
path, so = sys.argv[1], '/tmp/tokenize_plugin.so'
tok = Tokenizer(vocab_path=sys.argv[2] + '.vocab')
def records(blobs):
    out = []
    for b in blobs:
        for line in b.split(b'\n'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
def py_payload(batch):
    return b'\n'.join(batch_payload([l for l in bytes(batch.data).split(b'\n') if l.strip()], tok)) or None
py = records(forkrun.map(py_payload, path, workers=4, order='index'))
pl = records(forkrun.map('%s:ml_tokenize' % so, path, mode='plugin', workers=4, order='index'))
print('py docs:', len(py), 'plugin docs:', len(pl))
assert len(py) == len(pl), 'COUNT MISMATCH'
bad = 0
for a, b in zip(py, pl):
    if set(a.keys()) != set(b.keys()):
        print('KEYS', set(a.keys()) ^ set(b.keys())); bad += 1
        if bad > 3: break
        continue
    for k in a:
        va, vb = a[k], b[k]
        if k == 'diversity':
            if abs(float(va) - float(vb)) > 1e-9:
                print('DIV', va, vb); bad += 1; break
        elif va != vb:
            sa, sb = repr(va)[:80], repr(vb)[:80]
            print('VALUE', k, sa, sb); bad += 1; break
    if bad > 3: break
print('mismatches:', bad)
print('VALIDATION:', 'PASS' if bad == 0 else 'FAIL')
