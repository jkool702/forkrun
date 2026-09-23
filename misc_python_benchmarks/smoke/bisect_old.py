import sys
sys.path.insert(0, 'python')
import forkrun
open('/tmp/bi.txt','w').write(''.join('line %d\n'%i for i in range(200)))
open('/tmp/sink.out','wb').close()
def up(batch):
    return bytes(batch.data).upper()
def sink(meta, result):
    with open('/tmp/sink.out','ab') as fh:
        fh.write(b'B%d:' % meta.batch_index)
        fh.write(result)
try:
    r = forkrun.map(up, '/tmp/bi.txt', workers=1, streaming=True, order='index')
    print('map returned %d records' % len(r))
except Exception as e:
    print('map raised: %r' % e)
import os
print('sink bytes:', os.path.getsize('/tmp/sink.out'))
