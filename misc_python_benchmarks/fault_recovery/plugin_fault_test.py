import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
SRC = '/tmp/mldata/ml_medium.jsonl'
CK = '/tmp/pf.ckpt'
for f in (CK, CK + '.coll'):
    try: os.unlink(f)
    except OSError: pass
os.environ['FR_FAULT_MARKER'] = '/tmp/pf_marker'
try: os.unlink('/tmp/pf_marker')
except OSError: pass
res = forkrun.map('/tmp/ml_plugin_fault.so:ml_process_fault', SRC, mode='plugin', workers=8, order='index', on_error='retry', orchestrator=True)
n = sum(1 for b in res for _ in b.split(b'\n') if _.strip())
print('plugin-fault survived, records:', n)
print('marker exists:', os.path.exists('/tmp/pf_marker'))
