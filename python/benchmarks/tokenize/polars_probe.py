import sys, os, time, json
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
import polars as pl
from tokenize_payload import Tokenizer, MIN_TOKENS, MAX_TOKENS, MIN_DIVERSITY
tok = Tokenizer(vocab_path='/tmp/tok.jsonl.vocab')
OUT_SCHEMA = {'doc_id': pl.Int64, 'n_tokens': pl.Int64, 'n_unique': pl.Int64,
              'diversity': pl.Float64, 'tokens': pl.List(pl.Int64)}
def batch_tokenize(df):
    doc_ids, nts, nus, divs, tokss = [], [], [], [], []
    for doc_id, text in zip(df['doc_id'].to_list(), df['text'].to_list()):
        toks = tok.tokenize(text or '')
        n, u = len(toks), len(set(toks))
        div = u / n if n else 0.0
        if MIN_TOKENS <= n <= MAX_TOKENS and div >= MIN_DIVERSITY:
            doc_ids.append(doc_id); nts.append(n); nus.append(u)
            divs.append(round(div, 4)); tokss.append(toks)
        else:
            doc_ids.append(None); nts.append(None); nus.append(None)
            divs.append(None); tokss.append(None)
    return pl.DataFrame({'doc_id': doc_ids, 'n_tokens': nts, 'n_unique': nus,
                         'diversity': divs, 'tokens': tokss}, schema=OUT_SCHEMA)
t0 = time.perf_counter()
out = pl.scan_ndjson('/tmp/tok.jsonl').select('doc_id', 'text').map_batches(batch_tokenize, schema=OUT_SCHEMA).collect()
dt = time.perf_counter() - t0
kept = out.drop_nulls()
print('rows:', len(out), 'kept:', len(kept), 'time: %.2fs rate: %.0f docs/s' % (dt, 3000/dt))
