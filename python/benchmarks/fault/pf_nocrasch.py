import sys, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
SRC = '/tmp/mldata/ml_medium.jsonl'
os.environ['FR_FAULT_MARKER'] = '/tmp/pf_marker2'
open('/tmp/pf_marker2', 'w').write('1')  # pre-created: never crashes
res = forkrun.map('/tmp/ml_plugin_fault.so:ml_process_fault', SRC, mode='plugin', workers=8, order='index', on_error='retry', orchestrator=True)
n = sum(1 for b in res for _ in b.split(b'\n') if _.strip())
print('no-crash plugin records:', n)
