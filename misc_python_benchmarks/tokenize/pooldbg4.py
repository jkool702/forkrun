import sys, traceback, multiprocessing
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import bench_tokenize as B
from bench_harness import BenchContext
B.VOCAB_PATH["path"] = "/tmp/tok.jsonl.vocab"
lines = [l.decode() for l in open('/tmp/tok.jsonl','rb').read().split(b'\n') if l.strip()][:2000]
chunks = B.chunk_lines(lines, 8)
def f(chunk):
    try:
        return (len(B._pool_chunk(chunk)), None)
    except BaseException:
        return (0, traceback.format_exc())
if __name__ == '__main__':
    ctx = BenchContext(scale='small', trials=1)
    with multiprocessing.Pool(2) as p:
        for n, tb in p.map(f, chunks[:4]):
            print('n=', n)
            if tb: print(tb[-900:])
