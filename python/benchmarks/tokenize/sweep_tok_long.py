import os, sys, tempfile
sys.path.insert(0, 'python/benchmarks'); sys.path.insert(0, 'python')
from bench_harness import time_it
from tokenize_data_gen import generate_corpus
from bench_tokenize import build_tokenize_plugin
import forkrun
tmp = tempfile.mkdtemp(prefix='fr_tokonly_')
path = os.path.join(tmp, 'corpus.jsonl')
N = 180000
print('generating %d docs...' % N, flush=True)
corpus, vocab = generate_corpus(path, N)
os.environ['FORKRUN_VOCAB_PATH'] = vocab
so = build_tokenize_plugin(tmp)
plug = '%s:ml_tokenize' % so
print('bytes: %d vocab: %s' % (os.path.getsize(path), vocab), flush=True)
for w in [4,8,14,28]:
    def run():
        return forkrun.map(plug, path, mode='plugin', workers=w, order='index')
    t, trials = time_it(run, trials=3, warmup=1)
    n_out = sum(1 for r in run() if r)
    print('plug %2dw: %.3fs -> %.0f docs/s out=%d/%d | %s' % (w, t, N/t, n_out, N, ' '.join('%.3f' % s for s in trials)), flush=True)
