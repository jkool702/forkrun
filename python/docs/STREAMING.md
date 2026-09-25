# forkrun Streaming Guide

`stream()` is `map()` with the collection removed: results
yield live, while workers are still running, with bounded
memory. Everything else — batching, modes, recovery,
ordering contract — is identical.

## Basic shape

```python
for blob in forkrun.stream(process, "input.txt", workers=8):
    handle(blob)
```

- `order="none"` (default): completion order (first-finished
  first). Highest throughput, no buffering.
- `order="index"`: input order, via a bounded reassembly
  buffer. A missing batch briefly holds the head of line
  (inherent — the parent can't know a hole is poison until
  EOF, when leftovers flush sorted).

## Backpressure (how memory stays flat)

The workers signal one 16-byte index per record down a 1MB
pipe. A slow consumer lets the pipe fill; the next signal
write **blocks**, holding that worker's unacked batch; claims
stop across the pipeline. No unbounded queues anywhere:
a 10MB input with 5× amplification and a 1ms/batch consumer
holds parent RSS flat (measured +0MB).

Consequences worth knowing:

- A consumer that never drains will stall workers
  indefinitely — that's the design, not a hang. Drain or
  abandon (closing the generator tears everything down).
- `map()` has no backpressure question (it collects
  everything by definition — output-sized parent memory).

## Streaming sources

```python
# Pipes/sockets stream automatically (can't pre-stat a size):
forkrun.stream(process, fifo_fd, workers=8)
# Files materialize by default; force streaming ingest:
forkrun.stream(process, "huge.bin", workers=8, streaming=True)
```

`streaming=True` spills in chunks while a forked scanner
publishes concurrently and a reaper hole-punches acked
prefixes (bounded ingress — TB-scale/unbounded inputs).
~2–3× CPU cost at medium scale for the capability; byte-exact
vs materialized.

## Streaming + crash recovery

Worker death mid-stream recovers exactly like mid-`map`:
the reactor reverts, re-queues, and respawns synchronously
between drain bursts while the other workers keep producing.
The recovered batch arrives late but — under `order="index"`
— in its correct position. Verified across unordered,
ordered, multi-death, SIGKILL, and NUMA topologies.

## Streaming vs map — choosing

| | `stream()` | `map()` |
|---|---|---|
| First result | immediately | at the end |
| Parent memory | flat | output-sized |
| Consumer | incremental | whole list |
| Ordering | both orders | both orders |
| Recovery | identical | identical |

Use `stream()` when output is large or the consumer is
incremental; `map()` when you want the whole answer.
