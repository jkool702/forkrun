# forkrun NUMA Guide

forkrun can run one ring per NUMA node (born-local ingest,
per-node scanners, CPU pinning) instead of a single global
ring. This matters on real multi-socket hardware and is
irrelevant-to-slightly-negative everywhere else.

## When to use it

| Hardware | Recommendation |
|---|---|
| Single socket (any core count) | Don't. `nodes=1` (or default `"auto"`, which detects it). UMA is simpler and slightly faster — no cross-node coordination to pay for. |
| Fake NUMA (`numa=fake=N`, testing) | `nodes="@2"` for topology tests. Expect UMA ≈ NUMA (measured: medium 2.3M UMA vs 2.1M NUMA — the gap is pipeline shape, not memory). |
| Real multi-socket | `nodes="auto"`. Born-local memory should win (reduced cross-socket traffic); measure your workload. |

## Enabling it

```python
forkrun.map(func, "data.txt", workers=8)              # auto: NUMA iff multi-socket
forkrun.map(func, "data.txt", workers=8, nodes=1)     # force UMA
forkrun.map(func, "data.txt", workers=8, nodes="@2")  # force 2 logical nodes
```

Forms: `1` (UMA), `N` (first N physical nodes), `"0,1"`
(explicit physicals), `"@N"` (N logical nodes cycling
physicals — the testing shape).

## The two rules

1. **Workers must cover every node** (`workers >= nodes`).
   Rings are born-local and workers claim locally; a node
   with no worker never has its ring claimed, and its share
   is silently lost. Size the pool to the topology.
2. **`nodes="auto"` follows the boot.** Booted with
   `numa=fake=N`, auto resolves to N nodes and every call
   takes the NUMA pipeline. Single-node-authored scripts
   must pass `nodes=1` explicitly under fake NUMA.

## What changes technically

- Per-node rings batch **independently**: batch counts and
  boundaries differ run to run. Compare byte content (or
  ordered reconstruction), never batch counts.
- Crash recovery is per-node and fully covered: the parent
  reads the dead worker's transaction, deposits to that
  node's escrow pipe, and respawns pinned to that node
  (verified: streaming + NUMA + crash, all green).
- `resume=`/`checkpoint_file=` are UMA-only (multi-node
  raises `RuntimeError` — a global frontier can't be drawn
  across rings safely).

## What to expect

Same-boot measured (28 workers, 5M records, fake-4 — the
worst case for NUMA, zero hardware benefit): light 5.6M vs
5.8M UMA, medium 2.1M vs 2.3M, heavy 710k vs 710k. The
mechanism (profiled): UMA serializes spill+scan before
forking; NUMA overlaps ingest/scan with compute. On real
multi-socket, add born-local memory wins on top.
