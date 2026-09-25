"""LLM training-data tokenization benchmark — the unambiguous niche (W-PY25).

Workload: JSONL documents -> whitespace tokenize -> 30k vocab hash
lookup -> sub-word splitting -> stats -> quality filter. Per-token
branching + hash lookup + variable-length output + document control
flow: genuinely inexpressible as Polars/DuckDB native expressions,
so native engines compete ONLY via their Python-UDF mechanism
(Pandas/pandas-batches here), where the optimizer cannot help.

Systems: serial, Pool, Executor, HF Datasets, Ray Data, forkrun
Python, forkrun C plugin (frozen ABI), Polars map_batches. Same
tokenizer rules + vocabulary + filters everywhere (validated).

Fairness notes: every worker loads the .vocab file once on first
use (no parent-preload advantage for fork systems); the C plugin
loads it once per worker process too. All timed end to end
including worker startup.

Usage:
  python3 python/benchmarks/bench_tokenize.py [--docs N]
      [--workers 1,2,4,8,14,28] [--trials N] [--csv PATH]
      [--tmpdir PATH] [--no-polars]
"""

import argparse
import multiprocessing
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # benchmarks/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # python/ for forkrun

from bench_harness import (BenchContext, format_table, rss_mb, time_it,
                           write_csv)
from tokenize_data_gen import generate_corpus
from tokenize_payload import (Tokenizer, batch_payload,
                              get_tokenizer)

WORKER_SWEEP = [1, 2, 4, 8, 14, 28]
VOCAB_PATH = {"path": None}


def detect_frameworks():
    """Probe optional frameworks (graceful degradation)."""
    found = {"serial": True, "pool": True, "executor": True,
             "forkrun": True, "polars": True}
    for name, mod in (("ray", "ray"), ("duckdb", "duckdb"),
                      ("hf_datasets", "datasets")):
        try:
            __import__(mod)
            found[name] = True
        except ImportError:
            found[name] = False
    try:
        import forkrun  # noqa: F401
    except ImportError:
        found["forkrun"] = False
    try:
        import polars  # noqa: F401
    except ImportError:
        found["polars"] = False
    return found


def framework_versions(found):
    """Version strings for the report metadata."""
    versions = {"python": sys.version.split()[0]}
    for name, mod in (("ray", "ray"), ("polars", "polars"),
                      ("duckdb", "duckdb"), ("datasets", "datasets"),
                      ("pyarrow", "pyarrow")):
        if name == "datasets" and not found.get("hf_datasets"):
            versions["datasets"] = "missing"
            continue
        try:
            versions[name] = __import__(mod).__version__
        except (ImportError, AttributeError):
            versions[name] = "missing"
    try:
        import forkrun
        versions["forkrun"] = forkrun.__version__
    except ImportError:
        versions["forkrun"] = "missing"
    return versions


# --- Worker entry points (fork/pickle-safe; vocab lazy-loads) ---

def _worker_tok():
    global _WT
    try:
        return _WT
    except NameError:
        # Module globals ride fork inheritance, but forkserver/spawn
        # workers may not see them — the env var always survives
        # (set in main before any worker exists).
        path = VOCAB_PATH["path"] or os.environ.get("FORKRUN_VOCAB_PATH")
        _WT = Tokenizer(vocab_path=path)
        return _WT


def _init_worker(vocab_path):
    """Explicit worker init (correct under fork/spawn/forkserver)."""
    global _WT
    from tokenize_payload import Tokenizer as _Tok
    _WT = _Tok(vocab_path=vocab_path)


def _pool_chunk(lines):
    tok = _worker_tok()
    return [r.decode() if isinstance(r, bytes) else r
            for r in batch_payload(lines, tok)]


def _forkrun_batch(batch):
    tok = _worker_tok()
    data = bytes(batch.data)
    out = batch_payload(
        [l for l in data.split(b"\n") if l.strip()], tok)
    return b"\n".join(out) if out else None


def _ray_batch(df):
    import pandas as pd
    tok = _worker_tok()
    nts, nus, divs, tokss = [], [], [], []
    # NOTE: read_text yields a single "text" column (no doc_id);
    # counting uses non-null rows, like the W-PY24 adapter.
    for text in df["text"].tolist():
        toks = tok.tokenize(text or "")
        n, u = len(toks), len(set(toks))
        div = u / n if n else 0.0
        from tokenize_payload import (MAX_TOKENS, MIN_DIVERSITY,
                                      MIN_TOKENS)
        if MIN_TOKENS <= n <= MAX_TOKENS and div >= MIN_DIVERSITY:
            nts.append(n)
            nus.append(u)
            divs.append(round(div, 4))
            tokss.append(toks)
        else:
            nts.append(None)
            nus.append(None)
            divs.append(None)
            tokss.append(None)
    return pd.DataFrame({"n_tokens": nts, "n_unique": nus,
                         "diversity": divs, "tokens": tokss})


def count_blobs(results):
    """Output docs across result shapes."""
    if results is None:
        return 0
    if isinstance(results, bytes):
        return sum(1 for l in results.split(b"\n") if l.strip())
    if isinstance(results, str):
        return sum(1 for l in results.split("\n") if l.strip())
    if isinstance(results, int):
        return results
    total = 0
    for chunk in results:
        if chunk is None:
            continue
        if isinstance(chunk, (bytes, str)):
            total += count_blobs(chunk)
        elif isinstance(chunk, (list, tuple)):
            total += sum(1 for r in chunk if r)
        else:
            total += 1
    return total


def chunk_lines(lines, n_chunks):
    """Split decoded lines into ~n_chunks contiguous chunks."""
    n_chunks = max(1, n_chunks)
    size = max(1, (len(lines) + n_chunks - 1) // n_chunks)
    return [lines[i:i + size] for i in range(0, len(lines), size)]


# --- Competitors ---

def bench_serial(ctx, lines, n_docs, trials):
    tok = Tokenizer(vocab_path=VOCAB_PATH["path"])

    def run():
        return batch_payload(lines, tok)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    n_out = len(run())
    ctx.record("tok-serial", "serial", "tokenize", n_docs / t,
               rss_mb(), "out=%d/%d docs" % (n_out, n_docs))
    return n_docs / t


def bench_pool(ctx, lines, n_docs, workers, trials):
    chunks = chunk_lines(lines, workers * 4)

    def run():
        with multiprocessing.Pool(
                workers, initializer=_init_worker,
                initargs=(VOCAB_PATH["path"],)) as pool:
            return pool.map(_pool_chunk, chunks)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    n_out = count_blobs(run())
    ctx.record("tok-pool-%dw" % workers, "pool", "tokenize",
               n_docs / t, rss_mb(),
               "out=%d/%d docs" % (n_out, n_docs))
    return n_docs / t


def bench_executor(ctx, lines, n_docs, workers, trials):
    chunks = chunk_lines(lines, workers * 4)

    def run():
        with ProcessPoolExecutor(
                max_workers=workers, initializer=_init_worker,
                initargs=(VOCAB_PATH["path"],)) as ex:
            return list(ex.map(_pool_chunk, chunks))

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    n_out = count_blobs(run())
    ctx.record("tok-executor-%dw" % workers, "executor", "tokenize",
               n_docs / t, rss_mb(),
               "out=%d/%d docs" % (n_out, n_docs))
    return n_docs / t


def bench_forkrun(ctx, path, n_docs, workers, trials):
    import forkrun

    def run():
        return forkrun.map(_forkrun_batch, path, workers=workers,
                           order="index")

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_blobs(run())
    ctx.record("tok-forkrun-%dw" % workers, "forkrun", "tokenize",
               n_docs / t, rss_mb(),
               "out=%d/%d docs, order=index" % (n_out, n_docs))
    return n_docs / t


def bench_forkrun_plugin(ctx, path, n_docs, workers, trials,
                         plugin_so):
    import forkrun

    def run():
        return forkrun.map("%s:ml_tokenize" % plugin_so, path,
                           mode="plugin", workers=workers,
                           order="index")

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_blobs(run())
    ctx.record("tok-plugin-%dw" % workers, "plugin", "tokenize",
               n_docs / t, rss_mb(),
               "out=%d/%d docs, frozen ABI" % (n_out, n_docs))
    return n_docs / t


def bench_hf_datasets(ctx, path, n_docs, workers, trials):
    from datasets import Dataset
    ds = Dataset.from_text(path)

    def batch_fn(batch):
        tok = _worker_tok()
        out = []
        for text in batch["text"]:
            text = (text or "").strip()
            if not text:
                out.append(None)
                continue
            toks = tok.tokenize(text)
            n, u = len(toks), len(set(toks))
            div = u / n if n else 0.0
            from tokenize_payload import (MAX_TOKENS, MIN_DIVERSITY,
                                          MIN_TOKENS)
            if MIN_TOKENS <= n <= MAX_TOKENS and div >= MIN_DIVERSITY:
                out.append("%d" % n)
            else:
                out.append(None)
        return {"kept": out}

    def run():
        mapped = ds.map(batch_fn, batched=True, batch_size=1000,
                        num_proc=workers, load_from_cache_file=False,
                        keep_in_memory=True)
        return sum(1 for r in mapped["kept"] if r)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=0)
    n_out = run()
    ctx.record("tok-hf-%dw" % workers, "hf_datasets", "tokenize",
               n_docs / t, rss_mb(),
               "out=%d/%d docs, batched=1000" % (n_out, n_docs))
    return n_docs / t


class RayTokBench:
    """Ray harness, one init (startup reported once)."""

    def __init__(self, cpus):
        import ray
        t0 = time.perf_counter()
        py_path = HERE + os.pathsep + os.environ.get("PYTHONPATH", "")
        ray.init(ignore_reinit_error=True, num_cpus=cpus,
                 log_to_driver=False,
                 runtime_env={"env_vars": {
                     "PYTHONPATH": py_path,
                     "FORKRUN_VOCAB_PATH": VOCAB_PATH["path"] or "",
                 }})
        self.startup_s = time.perf_counter() - t0
        self.ray = ray

    def run(self, ctx, path, n_docs, workers, trials):
        def go():
            ds = self.ray.data.read_text(path)
            mapped = ds.map_batches(_ray_batch, batch_format="pandas",
                                    concurrency=workers)
            return mapped.count()

        t, _ = time_it(go, trials=max(1, trials // 2), warmup=0)
        n_out = go()
        ctx.record("tok-ray-%dw" % workers, "ray", "tokenize",
                   n_docs / t, rss_mb(),
                   "count=%d/%d rows, startup=%.0fs"
                   % (n_out, n_docs, self.startup_s))
        return n_docs / t

    def shutdown(self):
        self.ray.shutdown()


def bench_polars(ctx, path, n_docs, trials):
    """Polars map_batches (its documented arbitrary-Python mechanism).

    Single measurement at default threads: the UDF is opaque to the
    optimizer and runs serially here (verified: POLARS_MAX_THREADS=1
    matches default), so a thread sweep is theater.
    """
    import polars as pl
    schema = {"doc_id": pl.Int64, "n_tokens": pl.Int64,
              "n_unique": pl.Int64, "diversity": pl.Float64,
              "tokens": pl.List(pl.Int64)}

    def batch_tokenize(df):
        from tokenize_payload import (MAX_TOKENS, MIN_DIVERSITY,
                                      MIN_TOKENS)
        tok = _worker_tok()
        doc_ids, nts, nus, divs, tokss = [], [], [], [], []
        for doc_id, text in zip(df["doc_id"].to_list(),
                                df["text"].to_list()):
            toks = tok.tokenize(text or "")
            n, u = len(toks), len(set(toks))
            div = u / n if n else 0.0
            if MIN_TOKENS <= n <= MAX_TOKENS and div >= MIN_DIVERSITY:
                doc_ids.append(doc_id)
                nts.append(n)
                nus.append(u)
                divs.append(round(div, 4))
                tokss.append(toks)
            else:
                doc_ids.append(None)
                nts.append(None)
                nus.append(None)
                divs.append(None)
                tokss.append(None)
        return pl.DataFrame(
            {"doc_id": doc_ids, "n_tokens": nts, "n_unique": nus,
             "diversity": divs, "tokens": tokss}, schema=schema)

    def run():
        out = (pl.scan_ndjson(path)
               .select("doc_id", "text")
               .map_batches(batch_tokenize, schema=schema)
               .collect())
        return out.drop_nulls()

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = len(run())
    ctx.record("tok-polars", "polars", "tokenize-udf",
               n_docs / t, rss_mb(),
               "out=%d docs, map_batches (serial UDF)" % n_out)
    return n_docs / t


def build_tokenize_plugin(workdir):
    """Compile tokenize_plugin.c once (raises when gcc is missing)."""
    import shutil as _shutil
    if _shutil.which("gcc") is None:
        raise RuntimeError("need gcc for the tokenize plugin")
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    src = os.path.join(os.path.dirname(HERE), "ml", "plugins", "tokenize_plugin.c")
    so_path = os.path.join(workdir, "tokenize_plugin.so")
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(repo_root, "ring_loadables"),
           "-o", so_path, src, "-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("plugin build failed:\n%s"
                           % proc.stderr[-2000:])
    return so_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="forkrun LLM tokenization benchmark")
    parser.add_argument("--docs", type=int, default=20000)
    parser.add_argument("--min-words", type=int, default=50,
                        help="min words per doc (default 50)")
    parser.add_argument("--max-words", type=int, default=500,
                        help="max words per doc (default 500)")
    parser.add_argument("--workers", default="1,2,4,8,14,28")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--tmpdir", default=None)
    parser.add_argument("--no-polars", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sweep = [int(w) for w in args.workers.split(",") if w.strip()]
    found = detect_frameworks()
    versions = framework_versions(found)
    print("forkrun tokenize benchmark — %d docs" % args.docs)
    print("Versions: %s" % versions)
    print("Worker sweep: %s (best reported per system)" % sweep,
          flush=True)

    tmpdir = args.tmpdir or tempfile.mkdtemp(prefix="fr_tokbench_")
    os.makedirs(tmpdir, exist_ok=True)
    ctx = BenchContext(scale="small", trials=args.trials)
    best = {}

    def note_best(system, rate):
        if system not in best or rate > best[system][0]:
            best[system] = (rate, None)

    try:
        path = os.path.join(tmpdir, "tok_corpus.jsonl")
        if not os.path.exists(path):
            from tokenize_data_gen import generate_corpus
            print("generating corpus (%d docs, %d-%d words)..."
                  % (args.docs, args.min_words, args.max_words),
                  flush=True)
            generate_corpus(path, args.docs,
                            min_words=args.min_words,
                            max_words=args.max_words)
        vocab_path = path + ".vocab"
        VOCAB_PATH["path"] = vocab_path
        os.environ["FORKRUN_VOCAB_PATH"] = vocab_path
        input_bytes = os.path.getsize(path)
        with open(path, "rb") as fh:
            n_docs = sum(1 for _ in fh)
        print("--- %d docs, %.1fMB ---"
              % (n_docs, input_bytes / 2**20), flush=True)

        # avg tokens/doc for the secondary metric (500-doc sample).
        avg_tok = _avg_tokens(vocab_path, path)

        plugin_so = None
        if found["forkrun"]:
            try:
                plugin_so = build_tokenize_plugin(tmpdir)
            except Exception as exc:  # noqa: BLE001
                print("plugin build skipped: %s" % str(exc)[:150],
                      flush=True)

        if found["serial"]:
            with open(path, "rb") as fh:
                lines = [l.decode() for l in fh.read().split(b"\n")
                         if l.strip()]
            r = bench_serial(ctx, lines, n_docs, args.trials)
            note_best("serial", r)
        for workers in sweep:
            if found["pool"]:
                with open(path, "rb") as fh:
                    lines = [l.decode()
                             for l in fh.read().split(b"\n")
                             if l.strip()]
                r = bench_pool(ctx, lines, n_docs, workers,
                               args.trials)
                note_best("pool", r)
            if found["executor"]:
                with open(path, "rb") as fh:
                    lines = [l.decode()
                             for l in fh.read().split(b"\n")
                             if l.strip()]
                r = bench_executor(ctx, lines, n_docs, workers,
                                   args.trials)
                note_best("executor", r)
            if found["hf_datasets"]:
                try:
                    r = bench_hf_datasets(ctx, path, n_docs, workers,
                                          args.trials)
                    note_best("hf_datasets", r)
                except Exception as exc:  # noqa: BLE001
                    print("hf_datasets failed (w=%d): %s"
                          % (workers, str(exc)[:120]), flush=True)
            if found["forkrun"]:
                r = bench_forkrun(ctx, path, n_docs, workers,
                                  args.trials)
                note_best("forkrun", r)
                if plugin_so is not None:
                    try:
                        r = bench_forkrun_plugin(
                            ctx, path, n_docs, workers, args.trials,
                            plugin_so)
                        note_best("forkrun-plugin", r)
                    except Exception as exc:  # noqa: BLE001
                        print("forkrun-plugin failed (w=%d): %s"
                              % (workers, str(exc)[:150]), flush=True)
        if found["ray"]:
            try:
                rb = RayTokBench(cpus=max(sweep))
                for workers in sweep:
                    r = rb.run(ctx, path, n_docs, workers,
                               args.trials)
                    note_best("ray", r)
                rb.shutdown()
            except Exception as exc:  # noqa: BLE001
                print("ray failed: %s" % str(exc)[:200], flush=True)
        if found["polars"] and not args.no_polars:
            try:
                r = bench_polars(ctx, path, n_docs, args.trials)
                note_best("polars-udf", r)
            except Exception as exc:  # noqa: BLE001
                print("polars failed: %s" % str(exc)[:200],
                      flush=True)
    finally:
        if not args.tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(format_table(ctx.results))
    print()
    print("BEST (worker sweep, docs/s + tokens/s @ %.0f tok/doc):"
          % avg_tok)
    for system, (rate, _) in sorted(best.items()):
        print("  %-14s %10.0f docs/s  %8.1fM tokens/s" % (
            system, rate, rate * avg_tok / 1e6))
    print()
    print("NOTES:")
    print("- Same tokenizer rules + vocabulary + filters everywhere; "
          "C plugin validated by exact JSON equality vs Python.")
    print("- forkrun uses order=index; Pool/Executor chunk decoded "
          "lines (pickled); Ray/HF read_text/from_text; Polars is "
          "map_batches (serial Python UDF — the optimizer cannot "
          "help opaque code).")
    print("- Every worker loads the .vocab file once on first use "
          "(symmetric cold-start, amortized).")
    print("- RSS is parent-process peak (ru_maxrss).")
    if args.csv:
        write_csv(ctx.results, args.csv)
        print("CSV: %s" % args.csv)
    return 0


def _avg_tokens(vocab_path, path):
    """Mean tokens/doc over a 500-doc sample (secondary metric)."""
    from tokenize_payload import Tokenizer
    tok = Tokenizer(vocab_path=vocab_path)
    total, n = 0, 0
    with open(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            import json
            try:
                text = json.loads(line).get("text", "")
            except ValueError:
                continue
            total += len(tok.tokenize(text))
            n += 1
            if n >= 500:
                break
    return total / n if n else 0.0


if __name__ == "__main__":
    sys.exit(main())
