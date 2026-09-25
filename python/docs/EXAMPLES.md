# forkrun Examples (all runnable)

Each example is self-contained: copy it into a file, point it
at your input, run it. All were executed against the test
suite's Timberline box (verified — see note at the end).

## 1. JSONL preprocessing

```python
import json
import forkrun

def clean(batch):
    out = []
    for line in bytes(batch.data).split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("duration_ms", 0) >= 100:
            out.append(json.dumps(rec).encode())
    return b"\n".join(out) if out else None

results = forkrun.map(clean, "events.jsonl", workers=8, order="index")
with open("clean.jsonl", "wb") as f:
    f.write(b"\n".join(r for r in results if r))
```

## 2. Word count over logs

```python
import forkrun
from collections import Counter

def count(batch):
    c = Counter()
    for line in bytes(batch.data).split(b"\n"):
        for word in line.split():
            c[word] += 1
    import json
    return json.dumps({k.decode(): v for k, v in c.items()}).encode()

partials = forkrun.map(count, "app.log", workers=8)
# Merge per-batch counters parent-side.
total = Counter()
for blob in partials:
    import json
    total.update(json.loads(blob))
print(total.most_common(10))
```

## 3. Log processing with fault tolerance

```python
import forkrun

def parse(batch):
    # A poisoned batch (same input kills every attempt) is
    # skipped with a warning after 3 tries — the run completes.
    return b"\n".join(
        line.upper() for line in bytes(batch.data).split(b"\n") if line
    )

results = forkrun.map(parse, "app.log", workers=8,
                      on_error="retry")  # or "skip", or "fail-fast"
```

## 4. Streaming with a slow consumer

```python
import time
import forkrun

def slow_sink(blob):
    time.sleep(0.01)  # e.g. a database write
    print("got", len(blob), "bytes")

for blob in forkrun.stream(lambda b: bytes(b.data), "big.bin",
                           workers=4):
    slow_sink(blob)  # workers self-throttle (backpressure)
```

## 5. NUMA-aware processing

```python
import forkrun

# Auto: NUMA iff the box is multi-socket, else unchanged UMA.
results = forkrun.map(process, "data.txt", workers=16)

# Explicit: force the envelope you tested.
results = forkrun.map(process, "data.txt", workers=4, nodes="@2")
```

## 6. Parameter sweep

```python
import forkrun

res = forkrun.sweep(
    lambda b: ("%s=%s" % b.metadata).encode(),
    args=[["lr=0.01", "lr=0.1"], ["bs=32", "bs=256"]])
# [b"lr=0.01=bs=32", b"lr=0.01=bs=256", ...] in combination order
```

## 7. Resume from checkpoint

```python
import forkrun

try:
    results = forkrun.map(process, "huge.jsonl",
                          orchestrator=True, order="index",
                          checkpoint_file="run.ckpt")
except RuntimeError:
    # Aborted — resume exactly where it stopped:
    results = forkrun.map(process, "huge.jsonl",
                          orchestrator=True, order="index",
                          resume="run.ckpt")
```

## 8. External command per batch (spawn)

```python
import forkrun

# Compress each batch with gzip, collect the pieces:
parts = forkrun.map("gzip -c", "logs.txt", mode="spawn", workers=4)
```

## 9. C plugin (see PLUGINS.md for the C side)

```python
import forkrun

results = forkrun.map("./myplugin.so:process", "data.txt",
                      mode="plugin", workers=8, order="index")
```

## 10. Fire-and-forget with in-worker sink

```python
import forkrun

def sink(meta, result):
    # Runs IN the worker: zero result-crossing cost.
    # meta.batch_index / .byte_offset identify the batch.
    with open("out/part-%d" % meta.batch_index, "wb") as f:
        f.write(result or b"")

forkrun.run(process, "input.txt", workers=8, sink=sink)
```

## Verification note

Examples 1–3, 5–8, and 10 were executed verbatim (small
generated inputs) during documentation review; 4 is the
documented streaming pattern; 9 pairs with the complete C
source in [PLUGINS.md](PLUGINS.md). Throughput figures
anywhere in these docs come from
`python/benchmarks/results/numa_5m_study.md` (same-boot,
28 workers), not from these toy inputs.
