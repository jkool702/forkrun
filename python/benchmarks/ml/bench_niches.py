"""Stage 0 niche benchmarks: real data-prep workloads (W-PY11).

The use cases that motivated the port: JSONL ingestion, filter+transform,
aggregation. NOTE: batch.data is a memoryview — it has no .split(), so
payloads copy to bytes first (stated v0 cost; the copy is part of the
measured path, honestly).
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from bench_harness import (BenchContext, SCALES, cpu_pct_around, rss_mb, time_it)  # noqa: E402


def _nworkers():
    return min(8, os.cpu_count() or 4)


def _generate_jsonl(n):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="fr_bench_js_")
    with os.fdopen(fd, "w") as fh:
        for i in range(n):
            fh.write(json.dumps({"id": i, "value": i * 2,
                                 "tag": "x" * 10}) + "\n")
    return path


def _generate_numeric(n):
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="fr_bench_num_")
    with os.fdopen(fd, "w") as fh:
        for i in range(n):
            fh.write("%d\n" % (i * 7))
    return path


def _parse_jsonl(path):
    def parse(batch):
        count = 0
        for line in bytes(batch.data).split(b"\n"):
            if line:
                try:
                    json.loads(line)
                    count += 1
                except ValueError:
                    pass
        return str(count).encode()
    return forkrun.map(parse, path, workers=_nworkers())


def _filter_transform(path):
    def filt(batch):
        kept = [ln.upper() for ln in bytes(batch.data).split(b"\n")
                if b"line 0" in ln]
        return b"\n".join(kept)
    return forkrun.map(filt, path, workers=_nworkers())


def _aggregate(path):
    def agg(batch):
        total = 0
        for line in bytes(batch.data).split(b"\n"):
            if line:
                try:
                    total += int(line)
                except ValueError:
                    pass
        return str(total).encode()
    return forkrun.map(agg, path, workers=_nworkers())


def bench_jsonl_ingest(ctx):
    n = SCALES[ctx.scale]
    path = _generate_jsonl(n)
    ctx._tmp.append(path)
    t, _ = time_it(lambda: _parse_jsonl(path), trials=ctx.trials)
    ctx.record("JSONL ingestion", "python", "map", n / t, rss_mb(),
               "json.loads per record",
               cpu_pct=cpu_pct_around(lambda: _parse_jsonl(path)))


def bench_transform_filter(ctx):
    path = ctx.input_path()
    n = SCALES[ctx.scale]
    t, _ = time_it(lambda: _filter_transform(path), trials=ctx.trials)
    ctx.record("Filter + transform", "python", "map", n / t, rss_mb(),
               "grep-like + upper per batch")


def bench_aggregation(ctx):
    n = SCALES[ctx.scale]
    path = _generate_numeric(n)
    ctx._tmp.append(path)
    t, _ = time_it(lambda: _aggregate(path), trials=ctx.trials)
    ctx.record("Aggregation (sum)", "python", "map", n / t, rss_mb(),
               "int parse + sum per batch")
