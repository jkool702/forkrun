import sys, time, statistics
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from ml_payload import forkrun_payload_medium, pool_chunk_payload_medium
import multiprocessing
path = '/tmp/mldata/ml_medium.jsonl'
n = sum(1 for _ in open(path, 'rb'))
lines = [l.decode() for l in open(path,'rb').read().split(b'\n') if l.strip()]
chunks = [lines[i:i+2000] for i in range(0, len(lines), 2000)]
def t_forkrun():
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        forkrun.map(forkrun_payload_medium, path, workers=14, order='index')
        ts.append(time.perf_counter()-t0)
    return n/statistics.median(ts)
def t_pool():
    ts = []
    for _ in range(2):
        t0 = time.perf_counter()
        with multiprocessing.Pool(14) as p:
            p.map(pool_chunk_payload_medium, chunks)
        ts.append(time.perf_counter()-t0)
    return n/statistics.median(ts)
def main():
    print('forkrun-first: %.0f' % t_forkrun(), flush=True)
    print('pool-second: %.0f' % t_pool(), flush=True)
    print('pool-first: %.0f' % t_pool(), flush=True)
    print('forkrun-second: %.0f' % t_forkrun(), flush=True)
if __name__ == '__main__':
    main()
