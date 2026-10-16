# forkrun Streaming Guide

`stream()` is `map()` with the collection removed: results
yield live, while workers are still running. Everything
else — batching, modes, recovery, ordering contract — is
identical.

On memory: what is established is **live delivery and
backpressure** (a slow consumer stops the pipeline instead
of letting a queue grow) and **lower measured parent RSS
than retaining every blob**, for the workload measured
below. What is **not** established is output-size
independence — measured peak RSS growth there is about
half the output bytes, not a constant. See TD-13.

## Basic shape

```python
for blob in forkrun.stream(process, "input.txt", workers=8):
    handle(blob)
```

- `order="none"` (default): completion order (first-finished
  first). Highest throughput, no buffering.
- `order="index"`: input order, via a reassembly buffer. A
  missing batch holds the head of line (inherent — the parent
  can't know a hole is poison until EOF, when leftovers flush
  sorted). **A poisoned/skipped head buffers the whole tail**:
  with a hole at the head, every later batch accumulates in the
  parent until EOF — full-stream buffering, by design for
  ordering (measured: 20.5MB output behind a poisoned head
  peaked 56MB parent RSS). The common case holds only the
  out-of-order depth (workers x in-flight). When buffered bytes
  pass the high-water limit the parent warns once on stderr
  (names the head batch, the buffered total, and the knob);
  the limit is `FORKRUN_REASSEMBLY_LIMIT` bytes when set
  (`0` silences), else the dynamic default of 2x the largest
  batch x 32 in-flight depth allowance.

## Backpressure (why no unbounded queue forms)

The workers signal one 16-byte index per record down a 1MB
pipe. A slow consumer lets the pipe fill; the next signal
write **blocks**, holding that worker's unacked batch; claims
stop across the pipeline. No unbounded queues anywhere —
with one documented exception: `order="index"` behind a
poisoned/skipped head buffers the tail (above), which is
ordering memory, not queueing, and warns at the high-water
limit.

**Correction (WO-PY-REL-1).** This section previously claimed a 10MB
input with 5× amplification and a 1ms/batch consumer "holds parent RSS
flat (measured +0MB)". That was measured with `ru_maxrss` before/after,
which is a process PEAK and therefore cannot attribute memory to a
workload. Re-measured as CURRENT RSS, sampled during consumption, in an
isolated process, the same workload retains about **0.50× the output
bytes** — 24.7 MB for 47.4 MB of output — and that ratio is constant
across output sizes from 47 MB to 380 MB, not a constant number of
bytes.

So the honest statement is: the parent stays flat **relative to a
consumer that retains everything** (which measures ~1.0× output), but it
does **not** stay flat in absolute terms. No unbounded queue is created
and backpressure works as described above; retention still scales with
output at about half the rate. See TD-13 in
`dev/supervisor/TECH_DEBT_REGISTER.md`; reproducing it:

    python3 python/tests/_streaming_rss_probe.py --amp 20
    python3 python/tests/_streaming_rss_probe.py --amp 20 --collect

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
| Parent memory | not output-sized independent (TD-13); lower than retaining every blob, and no queue grows | output-sized |
| Consumer | incremental | whole list |
| Ordering | both orders | both orders |
| Recovery | identical | identical |

Use `stream()` when output is large or the consumer is
incremental; `map()` when you want the whole answer.

Note the two are not interchangeable element-wise: `map()`
defaults to `output="view"` (zero-copy memoryviews) while
`stream()` always yields `bytes` regardless of `output`
(`docs/API.md`), and batch boundaries can differ between
two runs of the same input. Compare joined bytes, not
lists of records.
