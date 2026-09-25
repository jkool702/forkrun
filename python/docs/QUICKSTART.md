# forkrun Quick Start (5 minutes)

Parallel data processing in Python, without the multiprocessing
puzzle. `forkrun` splits your input into batches, runs your
function on each batch in parallel worker processes, and collects
the results — no pickling, no queues, no GIL battles.

## Install

```bash
pip install forkrun
```

Linux only (the engine uses `memfd_create`, `splice`, and
`fallocate`). Needs `gcc` + `make` at install time to build the
C substrate. Details: [INSTALLATION.md](INSTALLATION.md).

## Your first parallel job

```python
import forkrun

def process(batch):
    # batch.data is a memoryview over shared memory — borrowed.
    # Use it inside this function; don't save it.
    # batch.line_count tells you how many lines are in this batch.
    n = batch.line_count or 0
    return b"batch of %d lines" % n

results = forkrun.map(process, "input.txt", workers=8)
print(f"Processed {len(results)} batches")
```

That's it. `forkrun.map` returns one result per batch (here, in
worker-completion order). Return `None` from your function to
emit nothing for a batch.

## Your first streaming job

`map` waits for everything, then returns. `stream` yields each
result the moment its worker finishes — while other workers are
still running:

```python
for result in forkrun.stream(process, "input.txt", workers=8):
    handle(result)  # called live, not at the end
```

Same payload, same guarantees. Memory stays flat no matter how
large the output is (details: [STREAMING.md](STREAMING.md)).

## Your first fault-tolerant job

```python
# If a worker crashes (SIGSEGV, OOM-killer, stray SIGKILL),
# the batch is retried automatically on a respawned worker.
# Your code doesn't change at all.
results = forkrun.map(process, "input.txt", workers=8)
```

Python exceptions inside your function ride the same path:
the batch is retried (up to a limit), then skipped with a
warning — the pipeline keeps going. Details:
[FAULT_TOLERANCE.md](FAULT_TOLERANCE.md).

## Three rules that prevent 90% of confusion

1. **`batch.data` is borrowed.** It's a `memoryview` into shared
   memory, valid only during your function call. Need it later?
   Call `batch.copy()` first. Need to split lines? Convert
   first — `memoryview` has no `.split`:
   `for line in bytes(batch.data).split(b"\n"):`.
2. **One result per batch.** Your function runs once per batch
   and returns one value (`bytes`, `str`, `memoryview`, or
   `None`). forkrun handles the fan-out/fan-in.
3. **Workers are single-threaded.** Don't spawn threads inside
   your function; return bytes and parallelize in the parent.

## Next steps

- [MODES.md](MODES.md) — `python`/`spawn`/`plugin`/`splice`: run
  CLI tools and C callbacks, not just Python functions.
- [EXAMPLES.md](EXAMPLES.md) — 10+ runnable recipes (JSONL
  cleaning, log processing, tokenization, sweeps, resume).
- [CONFIGURATION.md](CONFIGURATION.md) — every knob
  (`workers`, `order`, `lines`, `nodes`, `on_error`, …).
- [API.md](API.md) — complete function reference.
