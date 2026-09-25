import sys, traceback
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import multiprocessing
import bench_tokenize as B
B.VOCAB_PATH["path"] = "/tmp/tok.jsonl.vocab"
def f(lines):
    try:
        return B._pool_chunk(lines)
    except BaseException:
        return traceback.format_exc()
if __name__ == '__main__':
    with multiprocessing.Pool(2) as p:
        for r in p.map(f, [['hello world this is a test of the tokenizer with many words to exceed twenty tokens minimum threshold yes indeed']]):
            print(r[:600], flush=True)
