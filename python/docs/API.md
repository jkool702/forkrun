# forkrun API Reference

All four entry points live at the top level: `forkrun.run`,
`forkrun.map`, `forkrun.stream`, `forkrun.sweep`, plus the
`forkrun.Batch` class. Every keyword below is covered in
[CONFIGURATION.md](CONFIGURATION.md) with tuning advice.

## forkrun.run(payload, source, **kwargs)

Run a payload over a source in parallel. Fire-and-forget:
results are discarded (or consumed by `sink`).

```python
forkrun.run(my_func, "data.txt")                  # Python function
forkrun.run("gzip -c", "data.txt", mode="spawn")  # external command
forkrun.run("./plug.so:fn", "data.txt", mode="plugin")  # C callback
```

Returns `None`. See [MODES.md](MODES.md) for the `mode` variants.

`sink` runs in the worker before commit, so it is at-least-once:
engine output stays exactly-once, but a death between sink and
ack re-runs your side effects — keep sinks idempotent.

Naming: `forkrun.run` is the `run()` function itself, not a
module (the implementation lives in `forkrun/run.py`,
shadowed on purpose) — `import forkrun; forkrun.run(...)`
is the whole call surface.

## forkrun.map(payload, source, **kwargs)

Same as `run()`, but collects and returns every result.

```python
results = forkrun.map(my_func, "data.txt", workers=8, order="index")
```

Returns a **list with one element per batch that emitted
output** (batches returning `None` contribute nothing).
`order="index"` sorts by batch index (input order);
`order="none"` (default) returns worker-completion order.
Empty input returns `[]`.

Each element is a **`memoryview` over a read-only mapping** of the
result stream (`output="view"`, the default since 0.17.0) — no copy
is made per record. See [Result representation](#result-representation).

## forkrun.stream(payload, source, **kwargs)

A generator that yields each result the moment its worker
produces it — while other workers are still running.

```python
for blob in forkrun.stream(my_func, "data.txt", workers=8):
    handle(blob)   # live, bounded memory
```

Yields in completion order (`order="none"`) or input order
(`order="index"`, via a bounded reassembly buffer — a missing
batch briefly holds the head of line, by design). Validates
eagerly on call (bad arguments raise before the first
`next()`). Abandoning the generator (close/GC/exception)
tears down workers safely.

**Records are always `bytes` here**, even though the default
representation for `map()` is a view: records are drained live out of
a results pipe or worker memfd as they arrive, so there is no finished
collection file to map. Zero-copy is a `map()`-only property.
`output=` is accepted and validated so all three entry points share one
surface; it does not change what `stream()` yields.

## Result representation

`output=` selects the representation of each result record.

| value | element type | cost |
| --- | --- | --- |
| `"view"` (default) | `memoryview` | a slice; no copy |
| `"bytes"` | `bytes` | a `pread`, an allocation, and a copy per record |

A view is backed by a read-only `mmap` of the result stream, unmapped
by a `weakref.finalize` attached to the ctypes array each
`memoryview` references. Slices keep that array alive, so the mapping
cannot be torn down while any view is reachable. No descriptor is held
(`mmap.mmap(fd, ...)` would dups one).

**Lifetime is per-result-stream, not per-record.** One surviving view
keeps the *whole* mapping resident, so filtering a large result down to
a handful of records can hold gigabytes:

```python
big = forkrun.map(..., output="view")        # maps the full result
keep = [r for r in big if r["uid"] == 7]     # maps it ALL still
```

Use `forkrun.materialize()` on the records you intend to keep, and drop
the rest, if you are filtering a large stream. This is inherent to
zero-copy — the alternative is the copy `output="bytes"` always
performs — not a leak, and it is the trade the default makes.

### What works on a view

`len()`, slicing, `==` against `bytes` (both directions),
`.tobytes()`, `.hex()`, `bytes(rec)`, and the buffer protocol
(`socket.send`, `write`, `mmap.write`, …).

Note that slicing a view yields another **view**, not `bytes`:

```python
rec[:4] == b"line"        # False — rec[:4] is a memoryview
bytes(rec[:4]) == b"line"  # True
```

### What does not

`memoryview` is a buffer, not a `str`/`bytes`. These need
`forkrun.materialize(rec)` or `bytes(rec)`:

```python
rec.split(b"\n")     rec.splitlines()     rec.decode()
rec.startswith(b"x")  b"x" in rec        sorted([rec, ...])
```

The raised types are CPython's, not ours: `AttributeError` for the
missing methods, `NotImplementedError` for `in` (which rejects any
`memoryview`). `rec * 3` raises `TypeError`.

### Opting out

```python
records = forkrun.map(f, src, output="bytes")   # per call

for rec in forkrun.map(f, src):
    row = forkrun.materialize(rec)              # per record
```

`forkrun.materialize(rec)` returns `bytes`, copying only if `rec` is
already a view; it is a no-op for `bytes`, `bytearray` and `str`.

Any other `output` value raises `ValueError`.

## forkrun.sweep(payload, source=None, *, args=None, args_from=None, link=False, **kwargs)

## forkrun.sweep(payload, source=None, *, args=None, args_from=None, link=False, **kwargs)

Run the payload once per argument combination. Each batch's
`.metadata` carries its sweep tuple; results return in
combination order.

```python
res = forkrun.sweep(
    lambda b: ("%s=%s" % b.metadata).encode(),
    args=[["a", "b"], ["1", "2"]])
# [b"a=1", b"a=2", b"b=1", b"b=2"]  (Cartesian; link=True zips)
```

- `args`: list of lists (one per dimension).
- `args_from`: list of file paths (one dimension per file,
  one value per line).
- `link=True`: zip dimensions pairwise (shortest wins) instead
  of Cartesian product.
- `source=`: every combination processes the full source.
- Remaining kwargs (`workers`, `on_error`, `lines`, …)
  forward to the underlying `map` call(s).

## class forkrun.Batch

One batch of work, passed to your payload function. The
`data` window is borrowed shared memory — valid during the
call only.

| Member | Type | Description |
|---|---|---|
| `data` | `memoryview` | Batch bytes (borrowed — `copy()` to keep) |
| `batch_index` | `int` | Global ordering key (execution identity) |
| `byte_offset` | `int` | Absolute byte coordinate of the window |
| `byte_length` | `int` | Window length in bytes |
| `line_count` | `int` or `None` | Lines in the batch (`None` in byte mode) |
| `metadata` | tuple or `None` | Sweep tuple (only under `sweep()`) |
| `copy()` | → `bytes` | Persistent copy of `data` |
| `invalidate()` | → `None` | Release views (the worker calls this for you) |

Your payload returns `bytes`, `bytearray`/`memoryview`,
`str` (UTF-8 encoded), or `None` (emit nothing). Anything
else raises `TypeError`.

## Common keyword parameters

| Parameter | Type | Default | Where |
|---|---|---|---|
| `mode` | `str` | `"python"` | all — `"python"`, `"spawn"`, `"plugin"`, `"splice"` |
| `workers` | `int` | auto (CPU count, capped) | all |
| `order` | `str` | `"none"` | `map`/`stream` — or `"index"` for input order |
| `lines` / `bytes` | `int` | adaptive | all — batch size (mutually exclusive) |
| `sink` | callable or `None` | `None` | `run` — process results inside the worker |
| `on_error` | `str` | `"retry"` | all — `"retry"`, `"skip"`, `"fail-fast"` |
| `nodes` | `str`/`int` | `"auto"` | all — `"auto"`, `1`, `N`, `"0,1"`, `"@N"` |
| `streaming` | `bool`/`None` | `None` (auto) | all — force streaming ingest or materialized |
| `output` | `str` | `"view"` | all — `"view"` (zero-copy views) or `"bytes"`; `stream()` always yields `bytes` regardless |
| `orchestrator` | `bool`/`None` | `None` (= reactor) | all — `None`/`True` = death-pipe supervision + respawn (worker death recovers); `False` = fail-fast fork-and-wait |
| `c_drain` | `bool`/`None` | `False` | `map`/`stream` — forked C result collection (opt-in) |
| `c_worker_loop` | `bool` | `False` | `map` + `mode="plugin"` — C worker loop (opt-in) |
| `c_spawn_loop` | `bool` | `False` | `map` + `mode="spawn"` — C worker loop (opt-in) |
| `resume` | path/`None` | `None` | `map`/`stream` — resume from checkpoint (C-orderer paths only) |
| `checkpoint_file` | path/`None` | `None` | `map`/`stream` — publish checkpoint on abort |

Details, constraints, and when to touch each one:
[CONFIGURATION.md](CONFIGURATION.md).
