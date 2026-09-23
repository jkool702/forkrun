import sys, traceback, multiprocessing
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import bench_tokenize as B
B.VOCAB_PATH["path"] = "/tmp/tok.jsonl.vocab"
def f(lines):
    try:
        return (len(B._pool_chunk(lines)), None)
    except BaseException:
        return (0, traceback.format_exc())
if __name__ == '__main__':
    lines = [l.decode() for l in open('/tmp/tok.jsonl','rb').read().split(b'\n') if l.strip()][:500]
    with multiprocessing.Pool(2) as p:
        for n, tb in p.map(f, [lines[:250], lines[250:]]):
            print('n=', n)
            if tb: print(tb[-800:])
