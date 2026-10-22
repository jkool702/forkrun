# forkrun Execution Modes

Five ways to say "what runs per batch". Same fan-out,
same batching, same recovery — only the per-batch executor
changes.

The five are exactly `_VALID_MODES` in `python/forkrun/_api.py`:
`python`, `spawn`, `plugin`, `splice`, `udf`. This file previously
enumerated only four; `udf` was reachable and tested but absent from
the list, which is the same class of drift the doc-accuracy gate exists
to catch. `udf` is documented in its own section below because its
payload form, helper requirement and route set all differ.

## mode="python" (default)

Your payload is a Python function. Use it for custom logic:
parsing, validation, feature extraction, filtering.

```python
import json

def clean(batch):
    out = []
    for line in bytes(batch.data).split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # malformed rides the retry path, then poisons
        if rec.get("duration_ms", 0) >= 100:
            out.append(json.dumps(rec).encode())
    return b"\n".join(out) if out else None

forkrun.map(clean, "events.jsonl", workers=8, order="index")
```

- Payload forms: a callable (fork-inherited, never pickled)
  or `"pkg.mod:func"`. A string spec is resolved in the **parent** on this
  path, before any fork: a child forked from a threaded host must not
  import, because frozen import locks in the child deadlock. The cleanroom
  UDF path (`mode="udf"`, or `mode="python"` with the helper built) is the
  exception — there the spec is resolved inside the launcher after `exec`.
  See `_worker.py` and `_udf.py`.
- Throughput (28 workers, 5M records): ~1.6M/s light,
  ~700k/s medium. An earlier version of this file called that "at parity
  with `ProcessPoolExecutor`", which is now wrong in the other
  direction: with static file partitioning -- the standard Python idiom
  -- medium `ProcessPoolExecutor` measures 778k and
  `multiprocessing.Pool` 775k, so forkrun's Python UDF path leads by
  ~1.00-1.19x. Batching on the fly would narrow that further and is
  available to them; it is not quoted because forkrun does it
  automatically. See `python/benchmarks/results/RELEASE_v3.6.0.md`
  section 0.

## mode="udf"

A Python callable **referenced by module**, executed by an interpreter
that lives *inside the cleanroom launcher* rather than in your process.

### Why it is not the same as `mode="python"`

These are two different calling conventions that share a language:

| | `mode="python"` | `mode="udf"` |
|---|---|---|
| Payload | callable, **or** `"pkg.mod:func"` | `"pkg.mod:func"` **only** |
| What the payload receives | a `forkrun.Batch` (data **plus** offsets, line counts, metadata) | a single `bytes` object |
| What it may return | bytes / memoryview / str / None | `bytes` or `None` |
| Where the callable is resolved | in **your** process, before any fork | inside the launcher, **after** `exec` |

A `mode="udf"` function therefore has no access to `Batch` fields, and a
`mode="python"` function must not assume it receives raw bytes. Passing a
callable to `mode="udf"` raises `ValueError` rather than being coerced.

### Requirements and limits

- **A version-matched helper `.so` is required for the isolated path.**
  Whenever the isolated path is not selected for the call — the helper
  is not built for this minor, **or** the cleanroom is off (the
  default), **or** the call is not one the launcher serves — `mode="udf"`
  still works, but it degrades: the spec is resolved in your process and
  the callable runs in-process through the `mode="python"` worker,
  wrapped by an adapter that restores the bytes-in /
  bytes-or-None-out contract. The adapter exists because a bare fallback
  would silently hand a `Batch` to a function written for `bytes` —
  every batch would raise, retry and poison, and the caller would see
  an empty result with no error naming the cause.

  The helper's existence is not what decides this. The **route
  selection** does: a helper built for this minor says the isolated
  path is *possible*, not that it was *chosen*. When the two were
  conflated, `mode="udf"` raised `NotImplementedError` in the default
  configuration — a fallback that raises is not a fallback.
- **Routes**: served wherever `mode="plugin"` is served — the same
  launcher and the same envelopes. Selectable as the `map-udf` and
  `stream-udf` routes. `stream(spawn)`-style unavailability does not
  apply, but neither does `splice`-style availability: `stream(udf)`
  requires `order="none"`, and `stream(udf, order="index")` declines and
  falls back in-process.
- **Not served** in the plain non-cleanroom worker loop as a distinct
  mode; there it is the in-process degradation above — which is a
  working call, not an error.

Implementation: `python/forkrun/_udf.py`, `fr_udf.c`,
`fr_udf_helper.c`, `fr_udf_fork.c`. Tests: `test_udf_mode.py`,
`test_udf_helper.py`, `test_udf_exactly_once.py`,
`test_udf_stream_liveness.py`, `test_udf_version_barrier.py`.


## mode="spawn"

Your payload is an external command. Use it for existing CLI
tools — `gzip`, `sed`, `tr`, `grep`, your own binaries.

```python
forkrun.map("gzip -c", "logs.txt", mode="spawn")
forkrun.map(["sed", "s/old/new/"], "data.txt", mode="spawn")
```

- `str` is split on whitespace; use the `list` form whenever
  quoting would matter.
- Batch bytes go to the command's stdin; stdout is captured
  as the result. Non-zero exit rides retry-then-poison like
  any payload error (missing commands exit 127, same path).
- `c_spawn_loop=True` (opt-in, `map()` only, UMA only) runs
  the claim→spawn→ack loop in C. Measured at parity with the
  Python loop (±4%) — its value is architectural uniformity
  (one engine-owned recovery path), not speed.

## mode="plugin"

Your payload is a C function in a `.so`. Use it for maximum
throughput when you can write C.

```python
forkrun.map("./myplugin.so:process", "data.txt", mode="plugin")
```

- Two conventions, not one: the default v0 Python path calls
  a one-arg entry point, `int process(struct fr_py_plugin_ctx
  *ctx)` (72B Python-side buffers, return code captured —
  NOT the frozen engine ABI). Only dialect-tagged plugins
  (`forkrun_use_ctx` 1/2) dispatch through the C-level v1 path
  on the frozen ABI (`struct forkrun_ctx`, 128B: the plugin
  reads the input window zero-copy and writes stdout, which
  the shim stages and frames) — and only those work from both
  bash `-C` and Python unchanged. An untagged legacy two-arg
  bash plugin called through v0 would receive the ctx pointer
  as `argc` and garbage as `argv`; the parent probes the tag
  and never guesses. See [PLUGINS.md](PLUGINS.md).
- Throughput (28 workers, 5M): 5.5M/s light, 2.3M/s medium
  (yyjson single-pass), 710k/s heavy — 2–7× the Python loop.
- `c_worker_loop=True` (opt-in, `map()` only, dialect-1/2
  plugins, UMA only) moves the whole worker loop into C.
- Writing one: [PLUGINS.md](PLUGINS.md).

## mode="splice"

Kernel passthrough — no computation, just data movement.
Use it to split/parallelize I/O at memory bandwidth.

```python
forkrun.map(None, "input.bin", mode="splice", bytes=512*1024)
for chunk in forkrun.stream(None, "input.bin", mode="splice"):
    process(chunk)  # raw byte-windows as they arrive
```

- Payload must be `None`; byte batching only (`bytes=N`,
  default 512KB — `lines=` is rejected, boundaries are never
  detected); `run()` is rejected (passthrough produces
  output — use `map()`/`stream()`).
- Workers run the claim→sendfile→ack loop with zero Python
  per batch.

## Choosing

| Situation | Mode |
|---|---|
| Custom Python logic | `python` |
| Existing CLI tool or binary | `spawn` |
| Hot loop worth writing in C | `plugin` |
| Just moving bytes | `splice` |
| Per-batch Python overhead matters | `plugin` + `c_worker_loop`, or `spawn` + `c_spawn_loop` |

Throughput expectations (honest, same-boot measured):
[PERFORMANCE.md](PERFORMANCE.md).
