"""W-PY29 focused benchmark: 2 forkrun modes x workers 8/14/28.

ML pipeline: 5M records x (light, medium, heavy), order=index,
  trials=3 + warmup=1 (median reported, same as bench_ml_pipeline).
Tokenize: 500k docs, same worker set, both modes.
Only forkrun numbers (other systems unchanged by W-PY29).
"""
import os
import sys
import tempfile
import time

HERE = "/mnt/ramdisk/forkrun/python/benchmarks"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from bench_harness import BenchContext  # noqa: E402
from ml_data_gen import generate_data  # noqa: E402
from bench_ml_pipeline import (bench_forkrun, bench_forkrun_plugin,  # noqa: E402
                               build_ml_plugin, count_results)
from bench_tokenize import (bench_forkrun as tok_forkrun,  # noqa: E402
                            bench_forkrun_plugin as tok_plugin,
                            build_tokenize_plugin, _avg_tokens)
from tokenize_data_gen import generate_corpus  # noqa: E402

RECORDS = 5_000_000
DOCS = 500_000
WORKERS = [8, 14, 28]
TRIALS = 3

tmpdir = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(
    prefix="fr_w29bench_")
os.makedirs(tmpdir, exist_ok=True)
print("tmpdir:", tmpdir, flush=True)

# ---- ML pipeline ----
for variant in ("light", "medium", "heavy"):
    path = os.path.join(tmpdir, "ml_%s.jsonl" % variant)
    if not os.path.exists(path):
        t0 = time.perf_counter()
        print("generating %s (%d records)..." % (variant, RECORDS),
              flush=True)
        generate_data(path, RECORDS, variant=variant)
        print("  generated %.1fMB in %.0fs"
              % (os.path.getsize(path) / 2**20,
                 time.perf_counter() - t0), flush=True)
    input_bytes = os.path.getsize(path)
    print("--- %s: %d records, %.1fMB ---"
          % (variant, RECORDS, input_bytes / 2**20), flush=True)
    ctx = BenchContext(scale="small", trials=TRIALS)
    plugin_so = build_ml_plugin(variant, tmpdir)
    for workers in WORKERS:
        r = bench_forkrun(ctx, path, RECORDS, input_bytes, variant,
                          workers, TRIALS)
        print("forkrun-python %s %dw: %.0f rec/s" % (variant, workers, r),
              flush=True)
        r = bench_forkrun_plugin(ctx, path, RECORDS, input_bytes,
                                 variant, workers, TRIALS, plugin_so)
        print("forkrun-plugin %s %dw: %.0f rec/s" % (variant, workers, r),
              flush=True)

# ---- Tokenize ----
path = os.path.join(tmpdir, "tok_corpus.jsonl")
if not os.path.exists(path):
    t0 = time.perf_counter()
    print("generating tokenize corpus (%d docs)..." % DOCS, flush=True)
    generate_corpus(path, DOCS, min_words=50, max_words=500)
    print("  generated %.1fMB in %.0fs"
          % (os.path.getsize(path) / 2**20, time.perf_counter() - t0),
          flush=True)
vocab_path = path + ".vocab"
os.environ["FORKRUN_VOCAB_PATH"] = vocab_path
import bench_tokenize as _bt
_bt.VOCAB_PATH["path"] = vocab_path
with open(path, "rb") as fh:
    n_docs = sum(1 for _ in fh)
print("--- tokenize: %d docs, %.1fMB ---"
      % (n_docs, os.path.getsize(path) / 2**20), flush=True)
avg_tok = _avg_tokens(vocab_path, path)
print("avg tokens/doc: %.1f" % avg_tok, flush=True)
ctx = BenchContext(scale="small", trials=TRIALS)
tok_so = build_tokenize_plugin(tmpdir)
for workers in WORKERS:
    r = tok_forkrun(ctx, path, n_docs, workers, TRIALS)
    print("tok-python %dw: %.0f docs/s (%.1fM tok/s)"
          % (workers, r, r * avg_tok / 1e6), flush=True)
    r = tok_plugin(ctx, path, n_docs, workers, TRIALS, tok_so)
    print("tok-plugin %dw: %.0f docs/s (%.1fM tok/s)"
          % (workers, r, r * avg_tok / 1e6), flush=True)
print("DONE", flush=True)
