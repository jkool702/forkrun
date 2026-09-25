"""NUMA steady-state benchmarks at 5M records, fake-4 topology (W-PY35).

Question: "How much does the NUMA pipeline cost in software
overhead, measured at steady state?" Fake NUMA (numa=fake=4) gives
the worst case: full NUMA software cost (N scanners, N indexers,
per-node rings, cross-node coordination) with zero hardware
benefit (one socket). On real multi-socket, born-local memory
would offset this cost.

Matrix (same boot, same payloads as the UMA 5M reference in
DOCS/python/AI_benchmark_results.md):
  Part A: ML light/medium/heavy, forkrun C plugin + Python UDF,
          nodes {1, @2, auto}, 28 workers; + 1M worker sweep.
  Part B: tokenize 500k docs (C plugin + Python + Executor);
          spawn 1M medium `tr` (Python loop + C-loop gate probe).
  Part C: Pool/Executor on light/medium/heavy, 28 workers.
  Part D: streaming + NUMA + slow consumer memory boundedness.

Throughput is computed on ACTUAL completed work (not nominal
input): rows covering fewer nodes than workers (sweep workers <
nodes) come back INCOMPLETE by topology design (an unworked
node's born-local ring is never claimed — RESILIENCE_PROTOCOL
§7.3) and are flagged as such instead of silently reporting a
nominal rate.

Usage:
  python3 python/benchmarks/bench_numa_5m.py [--records N]
      [--variants light,medium,heavy] [--workers 28]
      [--sweep-workers 1,2,4,8,14,28] [--trials N]
      [--nodes 1,@2,auto] [--parts a,b,c,d] [--csv PATH]
      [--tmpdir PATH]

No engine or library code is touched from here.
"""

import argparse
import multiprocessing
import os
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

import forkrun  # noqa: E402
from bench_harness import (BenchContext, format_table, rss_mb, time_it,
                           write_csv)  # noqa: E402
from bench_ml_pipeline import (FORKRUN_PAYLOADS, POOL_PAYLOADS,
                               build_ml_plugin, build_yyjson_plugin,
                               chunk_lines, count_results)  # noqa: E402
from ml_data_gen import generate_data  # noqa: E402

VARIANTS = ("light", "medium", "heavy")


def _count_lines(blobs):
    """Decoded output lines across forkrun result blobs."""
    total = 0
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, (bytes, bytearray)):
            total += b.count(b"\n")
        elif isinstance(b, str):
            total += b.count("\n")
        elif isinstance(b, (list, tuple)):
            total += _count_lines(b)
    return total


_REF_COUNTS = {}


def bench_forkrun_numa(ctx, path, n_records, payload, mode, workers,
                       trials, nodes, tag):
    """forkrun.map with an explicit nodes topology (order=index).

    Rate is computed on actual output lines. ML payloads filter
    records by design (medium quality gates), so completeness is
    judged against the nodes=1 reference for the same
    (tag, workers) — not the nominal input count. Shortfalls vs
    the reference are flagged INCOMPLETE (topology coverage, not
    a crash — see module doc).
    """
    def run():
        return forkrun.map(payload, path, mode=mode, workers=workers,
                           order="index", nodes=nodes)

    t, _ = time_it(run, trials=trials, warmup=1)
    out = run()
    n_out = _count_lines(out)
    key = (tag, workers)
    if nodes == 1 and key not in _REF_COUNTS:
        _REF_COUNTS[key] = n_out
    ref = _REF_COUNTS.get(key, n_records)
    # Completeness is thresholded, not exact: worker output memfds
    # do not newline-terminate blobs, so a naive whole-stream line
    # count merges one junction pair per blob boundary (W-PY35
    # finding — record multisets verified exactly equal regardless).
    # Genuine topology shortfall (unworked nodes) is 25%+, two
    # orders above the junction noise (<0.1%), so 1% separates them.
    complete = (n_out >= 0.99 * ref)
    rate = n_out / t if t > 0 else 0.0
    ctx.record("%s-%s-%dw" % (tag, nodes, workers), "forkrun-numa",
               mode, rate, rss_mb(),
               "out=%d/%d%s, order=index" % (
                   n_out, n_records,
                   "" if complete else " INCOMPLETE"))
    return rate


def bench_competitor(ctx, path, variant, workers, trials, system):
    """Pool / Executor on the same boot (NUMA-unaware baseline)."""
    with open(path, "rb") as fh:
        lines = [l.decode() for l in fh.read().split(b"\n") if l.strip()]
    n_records = len(lines)
    chunks = chunk_lines(lines, workers * 4)
    payload = POOL_PAYLOADS[variant]

    def run():
        if system == "pool":
            with multiprocessing.Pool(workers) as pool:
                return pool.map(payload, chunks)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(payload, chunks))

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_results(run())
    ctx.record("%s-%s-%dw" % (system, variant, workers), system, "udf",
               n_records / t if t > 0 else 0.0, rss_mb(),
               "out=%d/%d records" % (n_out, n_records))
    return n_records / t if t > 0 else 0.0


def bench_tokenize_numa(ctx, path, n_docs, workers, trials, nodes,
                        tag, plugin_so=None, vocab_path=None):
    """Tokenize 500k docs with an explicit topology."""
    if vocab_path:
        os.environ["FORKRUN_VOCAB_PATH"] = vocab_path
        try:
            import bench_tokenize as _bt
            _bt.VOCAB_PATH["path"] = vocab_path
        except ImportError:
            pass
    if plugin_so is not None:
        from bench_tokenize import build_tokenize_plugin  # noqa: F401
        payload, mode = ("%s:ml_tokenize" % plugin_so), "plugin"
    else:
        from bench_tokenize import _forkrun_batch
        payload, mode = _forkrun_batch, "python"

    def run():
        return forkrun.map(payload, path, mode=mode, workers=workers,
                           order="index", nodes=nodes)

    t, _ = time_it(run, trials=trials, warmup=1)
    out = run()
    # One JSON line per doc, no trailing newline: docs = newlines + 1
    # per non-empty blob (count_blobs in bench_tokenize.py equivalent).
    n_out = 0
    for b in out:
        if not b:
            continue
        if isinstance(b, str):
            b = b.encode()
        n_out += b.count(b"\n") + 1
    rate = n_docs / t if t > 0 else 0.0
    ctx.record("%s-tok-%s-%dw" % (tag, nodes, workers),
               "forkrun-numa", mode, rate, rss_mb(),
               "out=%d/%d docs" % (n_out, n_docs))
    return rate


def bench_spawn_numa(ctx, path, n_records, workers, trials, nodes,
                     c_loop=False):
    """Spawn `tr` with an explicit topology.

    c_loop=True on a multi-node topology raises loudly (the C
    spawn loop is UMA-only by gate) — the probe records the gate
    message instead of a rate.
    """
    if c_loop:
        def run():
            return forkrun.map("tr a-z A-Z", path, mode="spawn",
                               workers=workers, order="index",
                               nodes=nodes, c_spawn_loop=True)
        label = "spawn-cloop-%s-%dw" % (nodes, workers)
    else:
        def run():
            return forkrun.map("tr a-z A-Z", path, mode="spawn",
                               workers=workers, order="index",
                               nodes=nodes)
        label = "spawn-pyloop-%s-%dw" % (nodes, workers)
    try:
        t, _ = time_it(run, trials=trials, warmup=1)
    except (ValueError, RuntimeError) as exc:
        ctx.record(label, "forkrun-numa", "spawn", 0.0, rss_mb(),
                   "gate: %s" % str(exc)[:120])
        return 0.0
    out = run()
    n_out = _count_lines(out)
    rate = n_out / t if t > 0 else 0.0
    ctx.record(label, "forkrun-numa", "spawn", rate, rss_mb(),
               "out=%d/%d lines%s" % (
                   n_out, n_records,
                   "" if n_out == n_records else " INCOMPLETE"))
    return rate


def bench_stream_numa_memory(n_records=200000):
    """Streaming + NUMA + slow consumer: bounded RSS + complete.

    Small standalone check (not a ctx row — returns a dict).
    """
    import resource
    import tempfile as _tf
    fd, path = _tf.mkstemp(suffix=".txt")
    os.close(fd)
    with open(path, "w") as fh:
        for i in range(n_records):
            fh.write("line %06d\n" % i)

    def amplify(batch):
        return bytes(batch.data) * 5

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    n = 0
    total_lines = 0
    for blob in forkrun.stream(amplify, path, workers=4, nodes="@2"):
        n += 1
        total_lines += blob.count(b"\n")
        time.sleep(0.001)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    os.unlink(path)
    # 5x amplification: each input line yields 5 output lines.
    expected = 5 * n_records
    return {"batches": n, "lines": total_lines,
            "expected": expected,
            "complete": total_lines == expected,
            "rss_delta_mb": (after - before) / 1024.0}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="forkrun NUMA 5M steady-state benchmarks (W-PY35)")
    p.add_argument("--records", type=int, default=5_000_000)
    p.add_argument("--variants", default="light,medium,heavy")
    p.add_argument("--workers", default="28")
    p.add_argument("--sweep-workers", default="1,2,4,8,14,28")
    p.add_argument("--trials", type=int, default=2)
    p.add_argument("--nodes", default="1,@2,auto")
    p.add_argument("--parts", default="a,b,c,d")
    p.add_argument("--docs", type=int, default=500_000)
    p.add_argument("--csv", default=None)
    p.add_argument("--tmpdir", default=None)
    return p.parse_args(argv)


def _parse_nodes(s):
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok) if tok.lstrip("-").isdigit() else tok)
    return out


def main(argv=None):
    args = parse_args(argv)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    for v in variants:
        if v not in VARIANTS:
            raise ValueError("unknown variant %r" % v)
    workers_list = [int(w) for w in args.workers.split(",") if w.strip()]
    sweep = [int(w) for w in args.sweep_workers.split(",") if w.strip()]
    nodes_list = _parse_nodes(args.nodes)
    parts = {p.strip() for p in args.parts.split(",") if p.strip()}

    tmpdir = args.tmpdir or tempfile.mkdtemp(prefix="fr_numa5m_")
    os.makedirs(tmpdir, exist_ok=True)
    ctx = BenchContext(scale="small", trials=args.trials)
    print("forkrun NUMA steady-state: %d records/variant, workers=%s"
          % (args.records, workers_list), flush=True)
    print("Hardware: %s" % ctx.hardware, flush=True)
    print("Nodes under test: %s" % (nodes_list,), flush=True)
    try:
        with open("/sys/devices/system/node/online") as fh:
            print("NUMA online: %s" % fh.read().strip(), flush=True)
    except OSError:
        pass

    paths = {}
    try:
        # --- data + plugins (once) ---
        for variant in variants:
            path = os.path.join(tmpdir, "ml_%s_%d.jsonl"
                                % (variant, args.records))
            if not os.path.exists(path):
                print("generating %s (%d records)..."
                      % (variant, args.records), flush=True)
                generate_data(path, args.records, variant=variant)
            else:
                print("reusing %s (%.1fGB)" % (
                    path, os.path.getsize(path) / 2**30), flush=True)
            paths[variant] = path
        plugin_sos = {}
        for variant in variants:
            try:
                plugin_sos[variant] = build_ml_plugin(variant, tmpdir)
            except Exception as exc:  # noqa: BLE001
                print("plugin build skipped (%s): %s"
                      % (variant, str(exc)[:150]), flush=True)
        yyjson_so = None
        if "medium" in variants:
            try:
                from bench_ml_pipeline import build_yyjson_plugin
                yyjson_so = build_yyjson_plugin(tmpdir)
            except Exception as exc:  # noqa: BLE001
                print("yyjson build skipped: %s" % str(exc)[:150],
                      flush=True)

        # --- Part A: ML pipeline UMA vs NUMA ---
        if "a" in parts:
            for variant in variants:
                path = paths[variant]
                base = len(ctx.results)
                print("--- A: %s %d records ---"
                      % (variant, args.records), flush=True)
                for nodes in nodes_list:
                    for workers in workers_list:
                        if variant == "medium" and yyjson_so:
                            bench_forkrun_numa(
                                ctx, path, args.records,
                                "%s:ml_process_medium_yyjson" % yyjson_so,
                                "plugin", workers, args.trials, nodes,
                                "numa-yyjson-%s" % variant)
                        else:
                            so = plugin_sos.get(variant)
                            if so:
                                bench_forkrun_numa(
                                    ctx, path, args.records,
                                    "%s:ml_process_%s" % (so, variant),
                                    "plugin", workers, args.trials,
                                    nodes, "numa-c-%s" % variant)
                # Python UDF: UMA + full-NUMA only (time-bounded).
                full_numa = nodes_list[-1]
                for nodes in dict.fromkeys([1, full_numa]):
                    for workers in workers_list:
                        bench_forkrun_numa(
                            ctx, path, args.records,
                            FORKRUN_PAYLOADS[variant], "python",
                            workers, args.trials, nodes,
                            "numa-py-%s" % variant)
                print(format_table(ctx.results[base:]), flush=True)

            # Worker sweep on 1M medium (fast): C + Python, UMA + auto.
            # UMA first: it sets the reference counts filtering-aware
            # completeness is judged against (see bench_forkrun_numa).
            sweep_path = os.path.join(tmpdir, "ml_medium_1M.jsonl")
            if not os.path.exists(sweep_path):
                print("generating 1M medium sweep file...", flush=True)
                generate_data(sweep_path, 1_000_000, variant="medium")
            base = len(ctx.results)
            print("--- A sweep: 1M medium, nodes auto + UMA ---",
                  flush=True)
            for nodes in dict.fromkeys([1, "auto"]):
                for workers in sweep:
                    if yyjson_so:
                        bench_forkrun_numa(
                            ctx, sweep_path, 1_000_000,
                            "%s:ml_process_medium_yyjson" % yyjson_so,
                            "plugin", workers, args.trials, nodes,
                            "sweep-yyjson-med")
                    bench_forkrun_numa(
                        ctx, sweep_path, 1_000_000,
                        FORKRUN_PAYLOADS["medium"], "python",
                        workers, args.trials, nodes,
                        "sweep-py-med")
            print(format_table(ctx.results[base:]), flush=True)

        # --- Part B: tokenize + spawn ---
        if "b" in parts:
            from tokenize_data_gen import generate_corpus
            tok_path = os.path.join(tmpdir, "tok_%d.jsonl" % args.docs)
            vocab_path = tok_path + ".vocab"
            if not os.path.exists(tok_path):
                print("generating tokenize corpus (%d docs)..."
                      % args.docs, flush=True)
                generate_corpus(tok_path, args.docs)
            else:
                print("reusing tokenize corpus (%.1fGB)" % (
                    os.path.getsize(tok_path) / 2**30), flush=True)
            base = len(ctx.results)
            print("--- B: tokenize %d docs ---" % args.docs, flush=True)
            try:
                from bench_tokenize import build_tokenize_plugin
                tok_so = build_tokenize_plugin(tmpdir)
            except Exception as exc:  # noqa: BLE001
                print("tokenize plugin skipped: %s" % str(exc)[:150],
                      flush=True)
                tok_so = None
            workers = max(workers_list)
            for nodes in dict.fromkeys([1, nodes_list[-1]]):
                if tok_so:
                    bench_tokenize_numa(
                        ctx, tok_path, args.docs, workers, args.trials,
                        nodes, "numa", plugin_so=tok_so,
                        vocab_path=vocab_path
                        if os.path.exists(vocab_path) else None)
                bench_tokenize_numa(
                    ctx, tok_path, args.docs, workers, args.trials,
                    nodes, "numa-py", vocab_path=vocab_path
                    if os.path.exists(vocab_path) else None)
            print(format_table(ctx.results[base:]), flush=True)

            spawn_path = os.path.join(tmpdir, "spawn_1M.jsonl")
            if not os.path.exists(spawn_path):
                print("generating 1M medium spawn file...", flush=True)
                generate_data(spawn_path, 1_000_000, variant="medium")
            base = len(ctx.results)
            print("--- B: spawn tr 1M medium ---", flush=True)
            for workers in workers_list:
                for nodes in dict.fromkeys([1, nodes_list[-1]]):
                    bench_spawn_numa(ctx, spawn_path, 1_000_000,
                                     workers, args.trials, nodes,
                                     c_loop=False)
            # C-loop gate probe: UMA row + NUMA gate message.
            bench_spawn_numa(ctx, spawn_path, 1_000_000,
                             max(workers_list), args.trials, 1,
                             c_loop=True)
            bench_spawn_numa(ctx, spawn_path, 1_000_000,
                             max(workers_list), args.trials,
                             nodes_list[-1], c_loop=True)
            print(format_table(ctx.results[base:]), flush=True)

        # --- Part C: competitors on the same boot ---
        if "c" in parts:
            base = len(ctx.results)
            print("--- C: Pool/Executor same boot ---", flush=True)
            for variant in variants:
                for workers in workers_list:
                    bench_competitor(ctx, paths[variant], variant,
                                     workers, args.trials, "executor")
                    bench_competitor(ctx, paths[variant], variant,
                                     workers, args.trials, "pool")
            print(format_table(ctx.results[base:]), flush=True)

        # --- Part D: streaming + NUMA memory ---
        if "d" in parts:
            print("--- D: streaming+NUMA slow-consumer memory ---",
                  flush=True)
            mem = bench_stream_numa_memory()
            ctx.record("stream-numa-mem", "forkrun-numa", "stream", 0,
                       rss_mb(),
                       "batches=%d lines=%d/%d%s rss-delta=%.0fMB" % (
                           mem["batches"], mem["lines"],
                           mem["expected"],
                           "" if mem["complete"] else " INCOMPLETE",
                           mem["rss_delta_mb"]))
            print("memory check: %s" % mem, flush=True)
    finally:
        if not args.tmpdir:
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(format_table(ctx.results))
    medians = {}
    for r in ctx.results:
        medians.setdefault(r.name, []).append(r.lines_per_s)
    print()
    print("MEDIANS:")
    for name, vals in sorted(medians.items()):
        print("  %-28s %12.0f records/s" % (
            name, statistics.median(vals)))
    if args.csv:
        write_csv(ctx.results, args.csv)
        print("CSV: %s" % args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
