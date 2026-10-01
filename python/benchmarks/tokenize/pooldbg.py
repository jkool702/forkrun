import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import multiprocessing
import bench_tokenize as B
B.VOCAB_PATH["path"] = "/tmp/tok.jsonl.vocab"
def f(lines):
    import os
    return (B.VOCAB_PATH["path"], os.getpid())
if __name__ == '__main__':
    with multiprocessing.Pool(2) as p:
        print(p.map(f, [[], []]), flush=True)
