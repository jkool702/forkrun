import sys, time, statistics, os
sys.path.insert(0, '/mnt/ramdisk/forkrun/python'); sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import forkrun
from tokenize_payload import Tokenizer, batch_payload
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
os.environ['FORKRUN_VOCAB_PATH'] = '/tmp/tok.jsonl.vocab'
tok = Tokenizer(vocab_path='/tmp/tok.jsonl.vocab')
def py_batch(batch):
    return b'\n'.join(batch_payload([l for l in bytes(batch.data).split(b'\n') if l.strip()], tok)) or None
def pool_chunk(lines):
    t = Tokenizer(vocab_path='/tmp/tok.jsonl.vocab')
    return [r.decode() for r in batch_payload(lines, t)]
path = '/tmp/bigdocs2.jsonl'
n = sum(1 for _ in open(path, 'rb'))
lines = [l.decode() for l in open(path,'rb').read().split(b'\n') if l.strip()]
chunks = [lines[i:i+200] for i in range(0, len(lines), 200)]
def t_serial():
    t0=time.perf_counter(); r=batch_payload(lines, tok); print('  serial kept:', len(r), flush=True); return n/(time.perf_counter()-t0)
def t_exec(w):
    def run():
        with ProcessPoolExecutor(max_workers=w) as ex: return list(ex.map(pool_chunk, chunks))
    t0=time.perf_counter(); r=run(); ts=[time.perf_counter()-t0]
    t0=time.perf_counter(); r=run(); ts.append(time.perf_counter()-t0)
    print('  exec kept:', sum(len(x) for x in r), flush=True); return n/statistics.median(ts)
def t_fr(w, plugin=False):
    def run():
        if plugin: return forkrun.map('/tmp/tokenize_plugin.so:ml_tokenize', path, mode='plugin', workers=w, order='index')
        return forkrun.map(py_batch, path, workers=w, order='index')
    outs = []
    ts = []
    for _ in range(2):
        t0=time.perf_counter(); r=run(); ts.append(time.perf_counter()-t0); outs.append(sum(1 for b in r for _ in b.split(b'\n') if _.strip()))
    print('  fr kept:', outs, flush=True); return n/statistics.median(ts)
def main():
    print('serial: %.0f' % t_serial(), flush=True)
    print('exec-8: %.0f' % t_exec(8), flush=True)
    print('fr-py-8: %.0f' % t_fr(8), flush=True)
    print('fr-plug-8: %.0f' % t_fr(8, True), flush=True)
if __name__ == '__main__':
    main()
