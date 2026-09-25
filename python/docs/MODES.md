# forkrun Execution Modes

Four ways to say "what runs per batch". Same fan-out,
same batching, same recovery — only the per-batch executor
changes.

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
  or `"pkg.mod:func"` (imported post-fork in the worker,
  keeping the parent free of native imports).
- Throughput (28 workers, 5M records): ~1.6M/s light,
  ~700k/s medium — at parity with `ProcessPoolExecutor`.

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

- Frozen ABI (`struct forkrun_ctx`, 128B): the plugin reads
  the input window zero-copy and writes stdout, which the
  shim stages and frames. A bash `-C` plugin works from
  Python unchanged and vice versa.
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
