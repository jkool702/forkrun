import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import multiprocessing
import bench_tokenize as B
B.VOCAB_PATH["path"] = "/tmp/tok.jsonl.vocab"
print('parent dict id:', id(B.VOCAB_PATH), B.VOCAB_PATH, flush=True)
def f(x):
    import os
    import bench_tokenize as BB
    return (BB.VOCAB_PATH["path"], id(BB.VOCAB_PATH))
if __name__ == '__main__':
    print('method:', multiprocessing.get_start_method(), flush=True)
    with multiprocessing.Pool(1) as p:
        print('worker sees:', p.map(f, [0]), flush=True)
