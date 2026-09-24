"""Real-world ML pipeline benchmark — best-of-the-best (W-PY24).

Two questions:
  A. Native engines (Polars, DuckDB) on natively-expressible work.
  B. Python-UDF systems (forkrun, Ray Data, HF Datasets, Pool,
     Executor, serial) on identical arbitrary-Python transformations.

Three variants (light/medium/heavy) locate the crossover. No
throughput winner is assumed — the numbers are what they are.

Usage:
  python3 python/benchmarks/bench_ml_pipeline.py [--records N]
      [--variants light,medium,heavy] [--workers 1,2,4,8,14,28]
      [--trials N] [--no-fault] [--csv PATH] [--tmpdir PATH]

Missing frameworks (ray/polars/duckdb/datasets) skip with a note.
"""

import argparse
import multiprocessing
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # python/ for forkrun

from bench_harness import (BenchContext, cpu_pct_around, format_table,
                           rss_mb, time_it, write_csv)
from ml_data_gen import generate_data

VARIANTS = ("light", "medium", "heavy")
WORKER_SWEEP = [1, 2, 4, 8, 14, 28]


def detect_frameworks():
    """Probe optional frameworks (graceful degradation)."""
    found = {"serial": True, "pool": True, "executor": True,
             "forkrun": True}
    for name, mod in (("ray", "ray"), ("polars", "polars"),
                      ("duckdb", "duckdb"),
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


def count_results(results):
    """Output records across the result shapes each system returns."""
    if results is None:
        return 0
    if isinstance(results, bytes):
        return sum(1 for line in results.split(b"\n") if line.strip())
    if isinstance(results, (str,)):
        return sum(1 for line in results.split("\n") if line.strip())
    if isinstance(results, (list, tuple)):
        total = 0
        for chunk in results:
            if chunk is None:
                continue
            if isinstance(chunk, (bytes, str)):
                total += count_results(chunk)
            elif isinstance(chunk, (list, tuple)):
                total += sum(1 for r in chunk if r)
            else:
                total += 1
        return total
    if isinstance(results, int):
        return results
    return 0


# --- UDF worker entry points (importable, fork/pickle-safe) ---

def _pool_chunk_light(lines):
    from ml_payload import pool_chunk_payload_light
    return pool_chunk_payload_light(lines)


def _pool_chunk_medium(lines):
    from ml_payload import pool_chunk_payload_medium
    return pool_chunk_payload_medium(lines)


def _pool_chunk_heavy(lines):
    from ml_payload import pool_chunk_payload_heavy
    return pool_chunk_payload_heavy(lines)


def _forkrun_light(batch):
    from ml_payload import forkrun_payload_light
    return forkrun_payload_light(batch)


def _forkrun_medium(batch):
    from ml_payload import forkrun_payload_medium
    return forkrun_payload_medium(batch)


def _forkrun_heavy(batch):
    from ml_payload import forkrun_payload_heavy
    return forkrun_payload_heavy(batch)


POOL_PAYLOADS = {"light": _pool_chunk_light, "medium": _pool_chunk_medium,
                 "heavy": _pool_chunk_heavy}
FORKRUN_PAYLOADS = {"light": _forkrun_light, "medium": _forkrun_medium,
                    "heavy": _forkrun_heavy}


def chunk_lines(lines, n_chunks):
    """Split decoded lines into ~n_chunks contiguous chunks."""
    n_chunks = max(1, n_chunks)
    size = max(1, (len(lines) + n_chunks - 1) // n_chunks)
    return [lines[i:i + size] for i in range(0, len(lines), size)]


# --- Competitor implementations ---

def bench_serial(ctx, path, n_records, input_bytes, variant, trials):
    from ml_payload import process_serial
    with open(path, "rb") as fh:
        raw = fh.read().split(b"\n")
    lines = [l for l in raw if l.strip()]

    def run():
        return process_serial(lines, variant)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    out = run()
    n_out = count_results(out)
    ctx.record("serial-%s" % variant, "serial", "udf",
               n_records / t, rss_mb(),
               "out=%d/%d records, %.1fGB in" % (
                   n_out, n_records, input_bytes / 1e9))
    return n_records / t


def bench_pool(ctx, path, n_records, input_bytes, variant, workers,
               trials):
    with open(path, "rb") as fh:
        lines = [l.decode() for l in fh.read().split(b"\n") if l.strip()]
    chunks = chunk_lines(lines, workers * 4)
    payload = POOL_PAYLOADS[variant]

    def run():
        with multiprocessing.Pool(workers) as pool:
            return pool.map(payload, chunks)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    n_out = count_results(run())
    ctx.record("pool-%s-%dw" % (variant, workers), "pool", "udf",
               n_records / t, rss_mb(),
               "out=%d/%d records" % (n_out, n_records))
    return n_records / t


def bench_executor(ctx, path, n_records, input_bytes, variant, workers,
                   trials):
    with open(path, "rb") as fh:
        lines = [l.decode() for l in fh.read().split(b"\n") if l.strip()]
    chunks = chunk_lines(lines, workers * 4)
    payload = POOL_PAYLOADS[variant]

    def run():
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(payload, chunks))

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=1)
    n_out = count_results(run())
    ctx.record("executor-%s-%dw" % (variant, workers), "executor", "udf",
               n_records / t, rss_mb(),
               "out=%d/%d records" % (n_out, n_records))
    return n_records / t


def bench_forkrun(ctx, path, n_records, input_bytes, variant, workers,
                  trials):
    import forkrun
    payload = FORKRUN_PAYLOADS[variant]

    def run():
        return forkrun.map(payload, path, workers=workers,
                           order="index")

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_results(run())
    ctx.record("forkrun-%s-%dw" % (variant, workers), "forkrun", "udf",
               n_records / t, rss_mb(),
               "out=%d/%d records, order=index" % (n_out, n_records))
    return n_records / t


def build_ml_plugin(variant, workdir):
    """Compile the C plugin for one variant (once per benchmark).

    Returns the .so path. Raises RuntimeError when gcc is missing.
    """
    import shutil as _shutil
    if _shutil.which("gcc") is None:
        raise RuntimeError("need gcc to build the ML plugin")
    repo_root = os.path.dirname(os.path.dirname(HERE))
    src = os.path.join(HERE, "plugins", "ml_plugin_%s.c" % variant)
    if not os.path.exists(src):
        raise RuntimeError("missing plugin source: %s" % src)
    so_path = os.path.join(workdir, "ml_plugin_%s.so" % variant)
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(repo_root, "ring_loadables"),
           "-o", so_path, src, "-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("plugin build failed:\n%s"
                           % proc.stderr[-2000:])
    return so_path


def build_yyjson_plugin(workdir):
    """Compile the yyjson medium plugin (W-PY31).

    Same flags as build_ml_plugin, plus yyjson.c (vendored, zero
    deps). Only the medium variant has a yyjson implementation —
    returns None for anything else (caller skips quietly).
    """
    import shutil as _shutil
    if _shutil.which("gcc") is None:
        raise RuntimeError("need gcc to build the yyjson plugin")
    repo_root = os.path.dirname(os.path.dirname(HERE))
    src = os.path.join(HERE, "plugins", "ml_plugin_yyjson.c")
    yjsrc = os.path.join(HERE, "plugins", "yyjson.c")
    if not os.path.exists(src) or not os.path.exists(yjsrc):
        raise RuntimeError("missing yyjson plugin sources")
    so_path = os.path.join(workdir, "ml_plugin_yyjson.so")
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(repo_root, "ring_loadables"),
           "-o", so_path, src, yjsrc, "-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("yyjson plugin build failed:\n%s"
                           % proc.stderr[-2000:])
    return so_path


def bench_forkrun_yyjson(ctx, path, n_records, input_bytes, variant,
                         workers, trials, plugin_so):
    """forkrun mode="plugin" with yyjson SIMD parsing (W-PY31).

    Byte-identical output to bench_forkrun_plugin (locked in by
    python/tests/test_yyjson_plugin.py); the only difference is the
    JSON parse core. Counts validated here.
    """
    import forkrun
    payload = "%s:ml_process_medium_yyjson" % plugin_so

    def run():
        return forkrun.map(payload, path, mode="plugin",
                           workers=workers, order="index")

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_results(run())
    ctx.record("forkrun-yyjson-%s-%dw" % (variant, workers), "plugin",
               "c-callback-yyjson", n_records / t, rss_mb(),
               "out=%d/%d records, frozen ABI" % (n_out, n_records))
    return n_records / t


def bench_forkrun_plugin(ctx, path, n_records, input_bytes, variant,
                         workers, trials, plugin_so):
    """forkrun mode="plugin": same logical workload, C callback.

    Zero Python per batch (C worker loop + C payload via the frozen
    ABI); output validated by counts here, by JSON-value equality
    offline (floats epsilon-compared, heavy `fh` excluded —
    SipHash-vs-FNV by design).
    """
    import forkrun
    payload = "%s:ml_process_%s" % (plugin_so, variant)

    def run():
        return forkrun.map(payload, path, mode="plugin",
                           workers=workers, order="index")

    t, _ = time_it(run, trials=trials, warmup=1)
    n_out = count_results(run())
    ctx.record("forkrun-plugin-%s-%dw" % (variant, workers), "plugin",
               "c-callback", n_records / t, rss_mb(),
               "out=%d/%d records, frozen ABI" % (n_out, n_records))
    return n_records / t


def bench_hf_datasets(ctx, path, n_records, input_bytes, variant,
                      workers, trials):
    from datasets import Dataset
    from ml_payload import (process_event_heavy, process_event_light,
                            process_event_medium)
    fn = {"light": process_event_light, "medium": process_event_medium,
          "heavy": process_event_heavy}[variant]
    ds = Dataset.from_text(path)
    n_text = len(ds)

    def batch_fn(batch):
        out = []
        for line in batch["text"]:
            line = line.strip()
            if not line:
                out.append(None)
                continue
            try:
                r = fn(line.encode())
                out.append(r.decode() if isinstance(r, bytes) else r)
            except ValueError:
                out.append(None)
        return {"result": out}

    def run():
        mapped = ds.map(batch_fn, batched=True, batch_size=1000,
                        num_proc=workers, load_from_cache_file=False,
                        keep_in_memory=True)
        return sum(1 for r in mapped["result"] if r)

    t, _ = time_it(run, trials=max(1, trials // 2), warmup=0)
    n_out = run()
    ctx.record("hf-datasets-%s-%dw" % (variant, workers), "hf_datasets",
               "udf", n_records / t, rss_mb(),
               "out=%d/%d of %d text rows, batched=1000"
               % (n_out, n_records, n_text))
    return n_records / t


class RayBench:
    """Ray Data harness with one init (startup cost reported once)."""

    def __init__(self, cpus):
        import ray
        t0 = time.perf_counter()
        # Workers are fresh processes: ship the benchmark dir on
        # PYTHONPATH so task code imports ml_payload normally
        # (instead of depending on cloudpickle global capture).
        py_path = HERE + os.pathsep + os.environ.get("PYTHONPATH", "")
        ray.init(ignore_reinit_error=True, num_cpus=cpus,
                 log_to_driver=False,
                 runtime_env={"env_vars": {"PYTHONPATH": py_path}})
        self.startup_s = time.perf_counter() - t0
        self.ray = ray

    def run_variant(self, ctx, path, n_records, input_bytes, variant,
                    workers, trials):
        from ml_payload import (process_event_heavy, process_event_light,
                                process_event_medium)
        fn = {"light": process_event_light,
              "medium": process_event_medium,
              "heavy": process_event_heavy}[variant]

        def batch_fn(df):
            import pandas as pd
            texts = df["text"].tolist()
            out = []
            for text in texts:
                text = (text or "").strip()
                if not text:
                    out.append(None)
                    continue
                try:
                    r = fn(text.encode())
                    out.append(r.decode() if isinstance(r, bytes)
                               else r)
                except ValueError:
                    out.append(None)
            return pd.DataFrame({"result": out})

        def run():
            ds = self.ray.data.read_text(path)
            mapped = ds.map_batches(batch_fn, batch_format="pandas",
                                    concurrency=workers)
            # count() executes the lazy pipeline end to end.
            return mapped.count()

        t, _ = time_it(run, trials=max(1, trials // 2), warmup=0)
        n_out = run()
        ctx.record("ray-%s-%dw" % (variant, workers), "ray", "udf",
                   n_records / t, rss_mb(),
                   "out=%d/%d records, pandas batches, startup=%.0fs"
                   % (n_out, n_records, self.startup_s))
        return n_records / t

    def shutdown(self):
        self.ray.shutdown()


def bench_native(ctx, path, n_records, input_bytes, variant, trials):
    """Polars/DuckDB native expressions (medium variant only)."""
    if variant != "medium":
        return {}
    rates = {}
    try:
        from ml_native import polars_medium

        def run_pl():
            return polars_medium(path)

        t, _ = time_it(run_pl, trials=trials, warmup=1)
        n_out = len(run_pl())
        ctx.record("polars-native", "polars", "native",
                   n_records / t, rss_mb(),
                   "out=%d rows, lazy/streaming NDJSON" % n_out)
        rates["polars"] = n_records / t
    except ImportError:
        pass
    try:
        from ml_native import duckdb_medium

        def run_dd():
            return duckdb_medium(path)

        t, _ = time_it(run_dd, trials=trials, warmup=1)
        n_out = len(run_dd())
        ctx.record("duckdb-native", "duckdb", "native",
                   n_records / t, rss_mb(),
                   "out=%d rows, SQL/JSON" % n_out)
        rates["duckdb"] = n_records / t
    except ImportError:
        pass
    return rates


# --- Fault injection ("crash once") ---

def bench_fault(ctx, path, n_records, workers):
    """Crash-once fault injection: recovery semantics, not poisoning.

    Deterministic targeting (small batch indices ALWAYS execute in
    the first wave — never a vacuous no-fault run):
    - SIGSEGV once at batch idx 5 (worker death; recovery comes
      from respawn, not escrow — signal death skips finally).
    - RuntimeError once each at idx 6..10 (escrow retry in-worker).
    - 5% malformed lines (data quality, payload-handled).
    Marker files prove every fault fired (fail-closed benchmark).

    Honest semantics (measured): the dead batch is LOST (no escrow
    across signal death) and the C orderer stalls at the head hole —
    the pipeline SURVIVES (exit 0, no hang) with output truncated
    to the clean prefix before the hole. Transient faults recover
    completely via escrow retry.
    """
    import forkrun
    crash_dir = tempfile.mkdtemp(prefix="fr_fault_once_")
    crash_idx = {5}
    transient_idx = {6, 7, 8, 9, 10}

    def fault_payload(batch):
        import ctypes
        import os as _o
        idx = batch.batch_index
        if idx in crash_idx:
            marker = os.path.join(crash_dir, "crash_%d" % idx)
            if not _o.path.exists(marker):
                with open(marker, "w") as fh:
                    fh.write("1")
                ctypes.string_at(0)  # SIGSEGV, first attempt only
        if idx in transient_idx:
            marker = os.path.join(crash_dir, "trans_%d" % idx)
            if not _o.path.exists(marker):
                with open(marker, "w") as fh:
                    fh.write("1")
                raise RuntimeError("transient batch %d" % idx)
        from ml_payload import forkrun_payload_medium
        return forkrun_payload_medium(batch)

    outcome, n_out, note = "died", 0, ""
    try:
        results = forkrun.map(fault_payload, path, workers=workers,
                              order="index", on_error="retry",
                              orchestrator=True)
        n_out = count_results(results)
        # Non-vacuity: every fault must have fired.
        fired_crash = sum(
            1 for i in crash_idx
            if os.path.exists(os.path.join(crash_dir, "crash_%d" % i)))
        fired_trans = sum(
            1 for i in transient_idx
            if os.path.exists(os.path.join(crash_dir, "trans_%d" % i)))
        assert fired_crash == len(crash_idx), \
            "crash never fired (vacuous fault test)"
        assert fired_trans == len(transient_idx), \
            "transients never fired (vacuous fault test)"
        outcome = "survived"
        note = ("crash-once SIGSEGV@idx5 + transient x5 all fired; "
                "orchestrator respawn; output truncated at hole")
    except (RuntimeError, AssertionError, Exception) as exc:  # noqa: BLE001
        note = "died: %s" % str(exc)[:100]
    finally:
        shutil.rmtree(crash_dir, ignore_errors=True)
    ctx.record("forkrun-fault-%dw" % workers, "forkrun", "fault", 0,
               rss_mb(), "%s, out=%d records; %s"
               % (outcome, n_out, note))
    return outcome, n_out


def bench_ray_fault(ctx, path, n_records, workers):
    """Ray Data under SIGSEGV: crash-once via marker, count recovery."""
    try:
        import ray
    except ImportError:
        return None
    from ml_payload import process_event_medium
    crash_dir = tempfile.mkdtemp(prefix="fr_rayfault_")
    marker = os.path.join(crash_dir, "m")

    def batch_fn(df):
        import pandas as pd
        import os as _o
        import ctypes
        if not _o.path.exists(marker):
            with open(marker, "w") as fh:
                fh.write("1")
            ctypes.string_at(0)  # SIGSEGV, first attempt only
        out = []
        for text in df["text"].tolist():
            text = (text or "").strip()
            if not text:
                out.append(None)
                continue
            try:
                r = process_event_medium(text.encode())
                out.append(r.decode() if isinstance(r, bytes) else r)
            except ValueError:
                out.append(None)
        return pd.DataFrame({"result": out})

    outcome, n_out, note = "died", 0, ""
    try:
        py_path = HERE + os.pathsep + os.environ.get("PYTHONPATH", "")
        ray.init(ignore_reinit_error=True, num_cpus=workers,
                 log_to_driver=False,
                 runtime_env={"env_vars": {"PYTHONPATH": py_path}})
        try:
            ds = ray.data.read_text(path)
            mapped = ds.map_batches(batch_fn, batch_format="pandas",
                                    concurrency=workers)
            n_out = mapped.count()
            outcome = "survived"
            note = "crash-once SIGSEGV, task retry"
        finally:
            ray.shutdown()
    except Exception as exc:  # noqa: BLE001
        note = "died: %s" % str(exc)[:150].replace("\n", " ")
    finally:
        shutil.rmtree(crash_dir, ignore_errors=True)
    ctx.record("ray-fault-%dw" % workers, "ray", "fault", 0,
               rss_mb(), "%s, count=%d; %s" % (outcome, n_out, note))
    return outcome


def bench_plugin_fault(ctx, path, n_records, workers, plugin_dir):
    """forkrun mode="plugin" under SIGSEGV (crash-once at idx 5).

    Builds the fault plugin (ml_plugin_fault.c = medium logic +
    crash-once prologue), crashes batch idx 5 once via FR_FAULT_IDX,
    and reports survival + output. Same hole semantics as the
    Python path: the dead batch is lost, output truncates there.
    Marker assertion keeps it non-vacuous.
    """
    import forkrun
    src = os.path.join(HERE, "plugins", "ml_plugin_fault.c")
    so_path = os.path.join(plugin_dir, "ml_plugin_fault.so")
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(os.path.dirname(os.path.dirname(HERE)),
                              "ring_loadables"),
           "-o", so_path, src, "-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        ctx.record("plugin-fault-%dw" % workers, "plugin", "fault",
                   0, rss_mb(),
                   "build failed: %s" % proc.stderr[-200:])
        return None
    marker = os.path.join(plugin_dir, "fault_marker")
    old_marker = os.environ.get("FR_FAULT_MARKER")
    old_idx = os.environ.get("FR_FAULT_IDX")
    os.environ["FR_FAULT_MARKER"] = marker
    os.environ["FR_FAULT_IDX"] = "5"
    outcome, n_out, note = "died", 0, ""
    try:
        results = forkrun.map(
            "%s:ml_process_fault" % so_path, path, mode="plugin",
            workers=workers, order="index", on_error="retry",
            orchestrator=True)
        n_out = count_results(results)
        assert os.path.exists(marker), \
            "plugin crash never fired (vacuous fault test)"
        outcome = "survived"
        note = ("crash-once SIGSEGV@idx5 fired; orchestrator "
                "respawn; output truncated at hole")
    except (RuntimeError, AssertionError, Exception) as exc:  # noqa: BLE001
        note = "died: %s" % str(exc)[:100]
    finally:
        if old_marker is None:
            os.environ.pop("FR_FAULT_MARKER", None)
        else:
            os.environ["FR_FAULT_MARKER"] = old_marker
        if old_idx is None:
            os.environ.pop("FR_FAULT_IDX", None)
        else:
            os.environ["FR_FAULT_IDX"] = old_idx
    ctx.record("plugin-fault-%dw" % workers, "plugin", "fault", 0,
               rss_mb(), "%s, out=%d records; %s"
               % (outcome, n_out, note))
    return outcome


def bench_pool_fault(ctx, path, n_records, workers, variant="medium"):
    """Pool under SIGSEGV: documents no-retry behavior (subprocess)."""
    crash_dir = tempfile.mkdtemp(prefix="fr_poolfault_")
    driver = "\n".join([
        "import multiprocessing, os, sys, tempfile",
        "sys.path.insert(0, %r)" % HERE,
        "from ml_payload import pool_chunk_payload_medium",
        "import ctypes",
        "d = %r" % crash_dir,
        "crashed = {'n': 0}",
        "def fn(lines):",
        "    import os as _o",
        "    m = os.path.join(d, 'm')",
        "    out = pool_chunk_payload_medium(lines)",
        "    if not _o.path.exists(m):",
        "        open(m, 'w').write('1')",
        "        ctypes.string_at(0)",
        "    return out",
        "lines = [l.decode() for l in open(%r, 'rb').read().split(b'\\n') if l.strip()]" % path,
        "chunks = [lines[i:i+2000] for i in range(0, len(lines), 2000)]",
        "print('chunks', len(chunks), flush=True)",
        "pool = multiprocessing.Pool(%d)" % workers,
        "try:",
        "    res = pool.map_async(fn, chunks).get(timeout=120)",
        "    print('POOL-SURVIVED', sum(len(r) for r in res))",
        "except Exception as e:",
        "    print('POOL-DIED', type(e).__name__, str(e)[:120])",
    ])
    try:
        proc = subprocess.run([sys.executable, "-c", driver],
                              capture_output=True, text=True, timeout=300)
        survived = "POOL-SURVIVED" in proc.stdout
        # Last meaningful line (tracebacks go to stderr; keep it short).
        tail = [l for l in proc.stdout.split("\n") if l.strip()]
        detail = tail[-1][:160] if tail else \
            proc.stderr.strip().split("\n")[-1][:160]
        ctx.record("pool-fault-%dw" % workers, "pool", "fault", 0,
                   rss_mb(), "survived=%s; %s" % (survived, detail))
        return survived
    finally:
        shutil.rmtree(crash_dir, ignore_errors=True)


# --- Driver ---

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="forkrun ML pipeline benchmark (best-of-the-best)")
    parser.add_argument("--records", type=int, default=50000,
                        help="input records per variant (default 50000)")
    parser.add_argument("--variants", default="light,medium,heavy",
                        help="comma list from light,medium,heavy")
    parser.add_argument("--workers", default="1,2,4,8,14,28",
                        help="worker sweep (default full sweep)")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--malformed", type=float, default=0.0,
                        help="malformed %% for throughput files")
    parser.add_argument("--no-fault", action="store_true")
    parser.add_argument("--fault-only", action="store_true",
                        help="run only the fault-injection section")
    parser.add_argument("--fault-workers", type=int, default=8)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--tmpdir", default=None)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    for v in variants:
        if v not in VARIANTS:
            raise ValueError("unknown variant %r" % v)
    sweep = [int(w) for w in args.workers.split(",") if w.strip()]
    found = detect_frameworks()
    versions = framework_versions(found)

    print("forkrun ML pipeline benchmark — %d records/variant"
          % args.records)
    print("Hardware: %s" %
          __import__("bench_harness").BenchContext(
              scale="small").hardware)
    print("Versions: %s" % versions)
    print("Frameworks: %s"
          % {k: v for k, v in found.items()})
    print("Worker sweep: %s (best reported per system)" % sweep,
          flush=True)

    tmpdir = args.tmpdir or tempfile.mkdtemp(prefix="fr_mlbench_")
    os.makedirs(tmpdir, exist_ok=True)
    ctx = BenchContext(scale="small", trials=args.trials)
    best = {}

    def note_best(system, variant, rate):
        key = (system, variant)
        if key not in best or rate > best[key][0]:
            best[key] = (rate, None)

    try:
        if not args.fault_only:
            for variant in variants:
                base = len(ctx.results)
                path = os.path.join(tmpdir, "ml_%s.jsonl" % variant)
                if not os.path.exists(path):
                    print("generating %s (%d records)..."
                          % (variant, args.records), flush=True)
                    generate_data(path, args.records, variant=variant,
                                  malformed_pct=args.malformed)
                input_bytes = os.path.getsize(path)
                print("--- %s: %d records, %.1fMB ---"
                      % (variant, args.records, input_bytes / 2**20),
                      flush=True)

                # C plugin .so (once per variant; skipped if unbuildable).
                plugin_so = None
                if found["forkrun"]:
                    try:
                        plugin_so = build_ml_plugin(variant, tmpdir)
                    except Exception as exc:  # noqa: BLE001
                        print("plugin build skipped (%s): %s"
                              % (variant, str(exc)[:150]), flush=True)

                # yyjson medium plugin (W-PY31; medium only).
                yyjson_so = None
                if found["forkrun"] and variant == "medium":
                    try:
                        yyjson_so = build_yyjson_plugin(tmpdir)
                    except Exception as exc:  # noqa: BLE001
                        print("yyjson build skipped (%s): %s"
                              % (variant, str(exc)[:150]), flush=True)

                if found["serial"]:
                    r = bench_serial(ctx, path, args.records,
                                     input_bytes, variant, args.trials)
                    note_best("serial", variant, r)
                for workers in sweep:
                    if found["pool"]:
                        r = bench_pool(ctx, path, args.records,
                                       input_bytes, variant, workers,
                                       args.trials)
                        note_best("pool", variant, r)
                    if found["executor"]:
                        r = bench_executor(ctx, path, args.records,
                                           input_bytes, variant, workers,
                                           args.trials)
                        note_best("executor", variant, r)
                    if found["hf_datasets"]:
                        try:
                            r = bench_hf_datasets(
                                ctx, path, args.records, input_bytes,
                                variant, workers, args.trials)
                            note_best("hf_datasets", variant, r)
                        except Exception as exc:  # noqa: BLE001
                            print("hf_datasets failed (w=%d): %s"
                                  % (workers, str(exc)[:120]),
                                  flush=True)
                    if found["forkrun"]:
                        r = bench_forkrun(ctx, path, args.records,
                                          input_bytes, variant, workers,
                                          args.trials)
                        note_best("forkrun", variant, r)
                        if plugin_so is not None:
                            try:
                                r = bench_forkrun_plugin(
                                    ctx, path, args.records, input_bytes,
                                    variant, workers, args.trials,
                                    plugin_so)
                                note_best("forkrun-plugin", variant, r)
                            except Exception as exc:  # noqa: BLE001
                                print("forkrun-plugin failed (%s, w=%d): %s"
                                      % (variant, workers,
                                         str(exc)[:150]),
                                      flush=True)
                        if yyjson_so is not None:
                            try:
                                r = bench_forkrun_yyjson(
                                    ctx, path, args.records, input_bytes,
                                    variant, workers, args.trials,
                                    yyjson_so)
                                note_best("forkrun-yyjson", variant, r)
                            except Exception as exc:  # noqa: BLE001
                                print("forkrun-yyjson failed (%s, w=%d): %s"
                                      % (variant, workers,
                                         str(exc)[:150]),
                                      flush=True)
                if found["ray"]:
                    try:
                        rb = RayBench(cpus=max(sweep))
                        for workers in sweep:
                            r = rb.run_variant(
                                ctx, path, args.records, input_bytes,
                                variant, workers, args.trials)
                            note_best("ray", variant, r)
                        rb.shutdown()
                    except Exception as exc:  # noqa: BLE001
                        print("ray failed: %s" % str(exc)[:200],
                              flush=True)
                bench_native(ctx, path, args.records, input_bytes,
                             variant, args.trials)
                # Incremental table: results survive later crashes.
                print("--- %s results (this variant) ---" % variant)
                print(format_table(ctx.results[base:]), flush=True)

        if not args.no_fault:
            fault_path = os.path.join(tmpdir, "ml_fault.jsonl")
            if not os.path.exists(fault_path):
                print("generating fault data (%d records, 5%% "
                      "malformed)..." % args.records, flush=True)
                generate_data(fault_path, args.records,
                              variant="medium", malformed_pct=5.0)
            print("--- fault injection (crash-once) ---", flush=True)
            if found["forkrun"]:
                bench_fault(ctx, fault_path, args.records,
                            args.fault_workers)
            if found["pool"]:
                bench_pool_fault(ctx, fault_path, args.records,
                                 args.fault_workers)
            if found["ray"]:
                try:
                    bench_ray_fault(ctx, fault_path, args.records,
                                    args.fault_workers)
                except Exception as exc:  # noqa: BLE001
                    print("ray fault failed: %s" % str(exc)[:200],
                          flush=True)
            if found["forkrun"]:
                try:
                    bench_plugin_fault(ctx, fault_path, args.records,
                                       args.fault_workers, tmpdir)
                except Exception as exc:  # noqa: BLE001
                    print("plugin fault failed: %s" % str(exc)[:200],
                          flush=True)
    finally:
        if not args.tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(format_table(ctx.results))
    print()
    print("BEST (worker sweep):")
    for (system, variant), (rate, _) in sorted(best.items()):
        print("  %-12s %-6s %10.0f records/s (%5.1f MB/s input)" % (
            system, variant, rate,
            rate * _avg_bytes(variant) / 1e6))
    print()
    print("NOTES:")
    print("- Worker sweep %s; each system's best rate shown above."
          % sweep)
    print("- UDF systems run the IDENTICAL Python transformation "
          "(ml_payload.py); only batching/transport/scheduling differ.")
    print("- Native systems (Polars/DuckDB) use their own expression "
          "language (medium variant only); the heavy UDF cannot be "
          "expressed natively, which is the point of the comparison.")
    print("- forkrun uses order=index (validated counts); Pool/Executor "
          "chunk into workers*4 line-chunks (pickled); Ray uses pandas "
          "batches via read_text; HF Datasets uses from_text + "
          "batched map (batch_size=1000, in-memory).")
    print("- Fault injection is crash-once (file markers): first "
          "attempt crashes, retry succeeds. forkrun recovers via "
          "orchestrator respawn; Pool has no retry (documented).")
    print("- RSS is parent-process peak (ru_maxrss); worker/subprocess "
          "memory is not attributed per system.")
    if args.csv:
        write_csv(ctx.results, args.csv)
        print("CSV: %s" % args.csv)
    return 0


def _avg_bytes(variant):
    return {"light": 120, "medium": 460, "heavy": 1300}[variant]


if __name__ == "__main__":
    sys.exit(main())
