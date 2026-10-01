import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
def noop(b): return None
forkrun.map(noop, '/tmp/w21b_small.txt', workers=1, lines=20)
