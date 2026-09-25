import sys, time
sys.path.insert(0, "python")
import forkrun
for i in range(200):
    r = forkrun.map(lambda b: bytes(b.data).upper(), "/tmp/big.txt", workers=8, streaming=True)
print("done", flush=True)
