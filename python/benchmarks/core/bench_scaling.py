"""Scaling diagnostics — W-PY26.a (diagnostic experiments FIRST).

Goal: empirically locate the 4-8w peak / 14-28w degradation before
changing any library code. All experiments are worker sweeps over
the SAME input; only the collection/worker path varies.

Experiments (run selectively via --experiments):
  exp1: eliminate result data (C null plugin + Python None payload).
        If the cliff remains -> parent/result path EXONERATED.
  exp2: order="none" vs order="index" (materialized, parent-side
        collect + final Python sort for index).
  exp3: existing C orderer (orchestrator=True, order="index",
        non-splice). Uses the already-implemented fr_py_orderer.
  exp5: perf stat command printer (cache contention / ctx switches).

Experiment 4 (Python loop vs C worker loop) lives here too but
requires Part 2/3 (fr_py_worker_plugin_loop + c_worker_loop=True);
it skips cleanly with a note when the symbol/flag is absent.

Usage:
  python3 python/benchmarks/bench_scaling.py [--records N]
      [--workers 1,2,4,8,14,28] [--trials N] [--csv PATH]
      [--tmpdir PATH] [--experiments exp1,exp2,exp3,exp4]
      [--variant light]

Missing gcc (null-plugin build) skips exp1-C with a note; the
Python-None arm always runs.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # benchmarks/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # python/ for forkrun

from bench_harness import (BenchContext, format_table, rss_mb, time_it,
                           write_csv)
from ml.ml_data_gen import generate_data

WORKER_SWEEP = [1, 2, 4, 8, 14, 28]

NULL_PLUGIN_SRC = r"""
#include "forkrun_plugin.h"
#include <stddef.h>
#include <stdint.h>

/* Dialect 2 + RAW: touch every input byte (same input cost as a real
 * plugin — defeats page-fault/DCE differences) but emit NOTHING. */
int forkrun_use_ctx = (int)(FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW);

int ml_null_touch(int argc, char **argv, const struct forkrun_ctx *ctx) {
    const volatile unsigned char *p;
    unsigned long long acc = 0;
    uint64_t n, i;
    (void)argc; (void)argv;
    if (!ctx) return -1;
    if (ctx->batch_byte_length == 0) return 0;
    if (ctx->version < 2) return -1;
    p = (const volatile unsigned char *)(uintptr_t)ctx->reserved[0];
    if (!p) return -1;
    n = ctx->batch_byte_length;
    for (i = 0; i < n; i++) acc += p[i];
    /* Sink the accumulator without output: return nonzero iff the
     * input was all zeros AND nonempty would be observable — instead
     * just keep acc live via a dummy condition that never fires. */
    if (acc == (unsigned long long)-1) return 1;
    return 0;
}
"""


def build_null_plugin(workdir):
    """Compile the null-touch plugin once. Raises RuntimeError."""
    if shutil.which("gcc") is None:
        raise RuntimeError("need gcc to build the null plugin")
    repo_root = os.path.dirname(os.path.dirname(HERE))
    src = os.path.join(workdir, "ml_null_plugin.c")
    so_path = os.path.join(workdir, "ml_null_plugin.so")
    with open(src, "w") as fh:
        fh.write(NULL_PLUGIN_SRC)
    cmd = ["gcc", "-O3", "-shared", "-fPIC",
           "-I", os.path.join(repo_root, "ring_loadables"),
           "-o", so_path, src]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("null plugin build failed:\n%s"
                           % proc.stderr[-2000:])
    return so_path


def _parse_int_list(s):
    return [int(x) for x in s.split(",") if x.strip()]


def experiment_no_output(ctx, path, n_records, workers_list, trials,
                         null_so):
    """Exp1: result data eliminated (null C plugin + Python None)."""
    import forkrun

    # Arm A: C null plugin (computes/touches, emits nothing).
    if null_so is not None:
        payload = "%s:ml_null_touch" % null_so
        for w in workers_list:
            def run():
                return forkrun.map(payload, path, mode="plugin",
                                   workers=w, order="none")
            t, _ = time_it(run, trials=trials, warmup=1)
            n_out = sum(1 for r in run() if r)
            ctx.record("exp1-null-plugin-%dw" % w, "plugin-null",
                       "no-output", n_records / t, rss_mb(),
                       "out=%d/%d (expect 0)" % (n_out, n_records))
    else:
        ctx.record("exp1-null-plugin-skipped", "plugin-null",
                   "no-output", 0, rss_mb(), "gcc missing")

    # Arm B: Python payload returning None (no output bytes staged).
    def py_none(batch):
        # Touch the input like a real payload (no DCE/play-fair gap).
        data = bytes(batch.data)
        acc = 0
        for b in data[::64]:
            acc += b
        if acc == -1:
            return b"x"
        return None

    for w in workers_list:
        def run():
            return forkrun.map(py_none, path, workers=w, order="none")
        t, _ = time_it(run, trials=trials, warmup=1)
        n_out = sum(1 for r in run() if r)
        ctx.record("exp1-py-none-%dw" % w, "python-none",
                   "no-output", n_records / t, rss_mb(),
                   "out=%d/%d (expect 0)" % (n_out, n_records))


def experiment_order_mode(ctx, path, n_records, workers_list, trials):
    """Exp2: order=none vs order=index (same parent-side collect)."""
    import forkrun

    def py_touch(batch):
        data = bytes(batch.data)
        return b"%d:%d" % (batch.batch_index, len(data))

    for mode in ("none", "index"):
        for w in workers_list:
            def run():
                return forkrun.map(py_touch, path, workers=w,
                                   order=mode)
            t, _ = time_it(run, trials=trials, warmup=1)
            n_out = len(run())
            ctx.record("exp2-py-%s-%dw" % (mode, w), "python",
                       "order-%s" % mode, n_records / t, rss_mb(),
                       "out=%d/%d" % (n_out, n_records))


def experiment_c_orderer(ctx, path, n_records, workers_list, trials,
                         null_so):
    """Exp3: existing C orderer (orchestrator=True, order=index)."""
    import forkrun

    # Python payload under the reactor (C orderer active).
    def py_touch(batch):
        data = bytes(batch.data)
        return b"%d:%d" % (batch.batch_index, len(data))

    for w in workers_list:
        try:
            def run():
                return forkrun.map(py_touch, path, workers=w,
                                   order="index", orchestrator=True)
        except Exception as exc:  # pragma: no cover - surface only
            ctx.record("exp3-reactor-%dw" % w, "reactor",
                       "c-orderer", 0, rss_mb(), "failed: %s" % exc)
            continue
        try:
            t, _ = time_it(run, trials=trials, warmup=1)
            n_out = len(run())
            ctx.record("exp3-reactor-%dw" % w, "reactor",
                       "c-orderer", n_records / t, rss_mb(),
                       "out=%d/%d" % (n_out, n_records))
        except Exception as exc:
            ctx.record("exp3-reactor-%dw" % w, "reactor",
                       "c-orderer", 0, rss_mb(), "failed: %s" % exc)

    # Null plugin under the reactor (ordered, zero output bytes).
    if null_so is not None:
        payload = "%s:ml_null_touch" % null_so
        for w in workers_list:
            try:
                def run():
                    return forkrun.map(payload, path, mode="plugin",
                                       workers=w, order="index",
                                       orchestrator=True)
                t, _ = time_it(run, trials=trials, warmup=1)
                n_out = sum(1 for r in run() if r)
                ctx.record("exp3-null-reactor-%dw" % w, "reactor-null",
                           "c-orderer", n_records / t, rss_mb(),
                           "out=%d/%d" % (n_out, n_records))
            except Exception as exc:
                ctx.record("exp3-null-reactor-%dw" % w, "reactor-null",
                           "c-orderer", 0, rss_mb(),
                           "failed: %s" % exc)


def experiment_worker_loop(ctx, path, n_records, workers_list, trials,
                           null_so):
    """Exp4: Python worker loop vs C worker loop (needs Part 2/3)."""
    import forkrun

    try:
        from forkrun._bindings import get as _get
        lib = _get()
        has_loop = hasattr(lib, "fr_py_worker_plugin_loop")
    except Exception:
        has_loop = False
    if not has_loop or null_so is None:
        ctx.record("exp4-c-loop-skipped", "c-loop", "scaling",
                   0, rss_mb(),
                   "fr_py_worker_plugin_loop absent or no gcc")
        return

    payload = "%s:ml_null_touch" % null_so
    # Arm A: current Python worker loop (c_worker_loop=False default).
    for w in workers_list:
        def run():
            return forkrun.map(payload, path, mode="plugin",
                               workers=w, order="none")
        t, _ = time_it(run, trials=trials, warmup=1)
        ctx.record("exp4-py-loop-%dw" % w, "py-loop", "scaling",
                   n_records / t, rss_mb(), "")
    # Arm B: C worker loop.
    for w in workers_list:
        try:
            def run():
                return forkrun.map(payload, path, mode="plugin",
                                   workers=w, order="none",
                                   c_worker_loop=True)
            t, _ = time_it(run, trials=trials, warmup=1)
            ctx.record("exp4-c-loop-%dw" % w, "c-loop", "scaling",
                       n_records / t, rss_mb(), "")
        except TypeError as exc:
            ctx.record("exp4-c-loop-%dw" % w, "c-loop", "scaling",
                       0, rss_mb(), "no c_worker_loop flag: %s" % exc)
            break
        except Exception as exc:
            ctx.record("exp4-c-loop-%dw" % w, "c-loop", "scaling",
                       0, rss_mb(), "failed: %s" % exc)


def print_perf_commands(workers_list):
    print("\nExp5: perf stat profiling commands (run manually):")
    print("  (cycles, ctx-switches, migrations, cache-misses per "
          "worker count)")
    for w in workers_list:
        print("  perf stat -e cycles,instructions,context-switches,"
              "cpu-migrations,cache-misses,L1-dcache-load-misses,"
              "LLC-load-misses python3 python/benchmarks/bench_scaling.py"
              " --experiments exp2 --workers %d" % w)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", type=int, default=20000)
    ap.add_argument("--workers", default=",".join(map(str, WORKER_SWEEP)))
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--tmpdir", default=None)
    ap.add_argument("--experiments", default="exp1,exp2,exp3",
                    help="comma list of exp1,exp2,exp3,exp4")
    ap.add_argument("--variant", default="light")
    args = ap.parse_args()

    workers_list = _parse_int_list(args.workers)
    wanted = [e.strip() for e in args.experiments.split(",") if e.strip()]

    tmpdir = args.tmpdir or tempfile.mkdtemp(prefix="fr_scaling_")
    os.makedirs(tmpdir, exist_ok=True)
    ctx = BenchContext(scale="small", trials=args.trials)

    path = os.path.join(tmpdir, "scaling_%s.jsonl" % args.variant)
    if not os.path.exists(path):
        print("generating %d %s records -> %s ..."
              % (args.records, args.variant, path))
        generate_data(path, args.records, variant=args.variant)
    n_records = args.records

    try:
        null_so = build_null_plugin(tmpdir)
    except Exception as exc:
        print("null plugin build skipped: %s" % str(exc)[:200])
        null_so = None

    if "exp1" in wanted:
        experiment_no_output(ctx, path, n_records, workers_list,
                             args.trials, null_so)
    if "exp2" in wanted:
        experiment_order_mode(ctx, path, n_records, workers_list,
                              args.trials)
    if "exp3" in wanted:
        experiment_c_orderer(ctx, path, n_records, workers_list,
                             args.trials, null_so)
    if "exp4" in wanted:
        experiment_worker_loop(ctx, path, n_records, workers_list,
                               args.trials, null_so)

    print(format_table(ctx.results))
    if args.csv:
        write_csv(ctx.results, args.csv)
        print("wrote %s" % args.csv)
    print_perf_commands(workers_list)

    if args.tmpdir is None:
        # Ephemeral tmpdir: keep the input + .so for inspection.
        print("artifacts kept in %s" % tmpdir)
    ctx.cleanup()


if __name__ == "__main__":
    main()
