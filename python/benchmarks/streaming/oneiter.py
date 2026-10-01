import sys, os; sys.path.insert(0, 'python')
import forkrun
def up(b):
    return bytes(b.data).upper()
a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True))
print('done', len(a), flush=True)
