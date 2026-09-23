import sys
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import multiprocessing
print('fresh:', multiprocessing.get_start_method(), flush=True)
import bench_tokenize
print('after bench import:', multiprocessing.get_start_method(), flush=True)
from bench_harness import BenchContext
from tokenize_data_gen import generate_corpus
print('after bench imports:', multiprocessing.get_start_method(), flush=True)
