import sys, os, signal
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun, threading
def up(b): return bytes(b.data).upper()
open('/tmp/mini.txt','w').write(''.join('line %d\n' % i for i in range(2000)))
def state(tag):
    print(tag, 'fds=%d threads=%d sigchld=%s sigpipe=%s' % (
        len(os.listdir('/proc/self/fd')), threading.active_count(),
        signal.getsignal(signal.SIGCHLD), signal.getsignal(signal.SIGPIPE)), flush=True)
state('before')
print('forkrun:', len(forkrun.map(up, '/tmp/mini.txt', workers=2)), flush=True)
state('after-map')
import multiprocessing
print('start-method:', multiprocessing.get_start_method(), flush=True)
state('after-import-mp')
