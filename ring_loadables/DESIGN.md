### `DESIGN.md`

# forkrun Ring Architecture – Design Overview (v9.8.0-NUMA)

## 1. Purpose

forkrun is a zero-copy, contention-free streaming parallelizer that turns a single Bash process into a high-throughput dataflow engine. It is designed for workloads ranging from billions of tiny tasks to a handful of extremely expensive ones, while remaining 100 % compatible with stock Bash.

**Guiding philosophy** (unchanged since day one):

> **Fast path is boring. Slow path is where complexity belongs.**

All coordination happens through shared memory, atomic counters, and kernel primitives (memfd, eventfd, pipes, splice). Locks and polling are deliberately absent from the hot path.

---

## 2. High-Level Model (NUMA-aware)

The system has four cooperating roles:

| Role                  | Responsibility                              | Location                  | Key Primitive          |
|-----------------------|---------------------------------------------|---------------------------|------------------------|
| **NUMA Ingest**       | Zero-copy splice from stdin → memfd         | Single thread             | splice / set_mempolicy |
| **Indexers**          | Find line boundaries, route to correct node | One per node              | pread + newline scan   |
| **Scanners**          | Publish batches into per-node rings         | Pinned per NUMA node      | atomic_store_release   |
| **Workers**           | Claim & execute batches                     | Dynamic pool (any node)   | atomic_fetch_add       |

**Born-local data flow** is the core innovation of v9:
- Data is physically allocated on the target NUMA node at ingest time.
- Scanners run pinned to that node.
- Workers inherit locality via `RING_NODE_ID`.

This eliminates almost all cross-socket traffic on the hot path.

---

## 3. The Per-Node Ring

When `--nodes` > 1 (default = auto-detect), there is **one independent `SharedState` ring per NUMA node**.

Each ring contains:
- `offset_ring[]` – byte offsets into the shared memfd (with sign bit for partial batches)
- `stride_ring[]` – record counts (lines or bytes)
- `major_ring[]` / `minor_ring[]` – ordering keys for NUMA-aware reordering
- `end_ring[]` – end offset for return-bytes mode

**Invariants** (see INVARIANTS.md):
- `write_idx` and `read_idx` are monotonic and node-local.
- Each slot is written exactly once and claimed exactly once.

---

## 4. The NUMA Topology Pipeline

```
stdin
  ↓ splice (ring_numa_ingest)
shared memfd (append-only)
  ↓ IngestPacket → index_pipe
ring_indexer_numa (boundary alignment + node routing)
  ↓ ScannerTask → per-node pipe
ring_numa_scanner[N] (pinned, born-local)
  ↓ publish to per-node ring
Workers (claim from any node)
```

Back-pressure is enforced via the **claim_pipe** (workers signal when they need more work). This creates natural load balancing without a central coordinator.

---

## 5. Claiming Work & Escrow

Workers:
1. Prefer their local node’s ring.
2. Check the **per-node escrow pipe** first (overshoot remainders).
3. Fall back to the ring with a single `atomic_fetch_add`.

Overshoot is expected and handled gracefully:
- Worker processes what exists.
- Remainder goes to escrow.
- Any idle worker (any node) can steal it.

**Escrow is advisory** — correctness never depends on it.

---

## 6. Adaptive Batch Control (still present)

The scanner uses the same three-phase controller as earlier versions (warmup → geometric ramp → PID steady-state), now running independently on each NUMA node. Batch-size changes are published via the `signed_batch_size` field (negative = advisory, positive = finalized by a worker via CAS in legacy mode; simplified in full NUMA mode).

Tail handling is explicit: once `tail_idx` is set, all remaining batches are self-describing (sign bit + stride metadata).

---

## 7. Memory Reclamation (Fallow)

A background thread watches the global minimum claimed offset and uses `fallocate(FALLOC_FL_PUNCH_HOLE)` to reclaim space behind it. Offsets remain valid forever; the file never grows without bound.

---

## 8. Output Ordering

- `--realtime` / `--unbuffered`: direct to stdout (no extra buffering).
- `--ordered` / `--buffered`: per-worker memfd + `ring_order` (NUMA-aware major/minor merging).

The reorder path is the only place that may block; everything else stays lock-free.

---

## 9. Mental Model

Think of forkrun as **a speculative, NUMA-born-local work-stealing engine** where:

- Progress is irreversible (monotonic indices).
- Locality is structural (not just a scheduling hint).
- Contention was eliminated by design, not by clever atomics.

Once you internalize that the **data itself** is born on the correct socket and the rings are partitioned, the rest of the complexity becomes obvious and necessary.

---

## 10. What You Can Change Safely

You may freely tune:
- Batch-size heuristics
- Ramp-up constants
- NUMA node count
- Escrow depth

As long as the invariants in **INVARIANTS.md** hold, correctness is guaranteed.

---

**See also:** `INVARIANTS.md` for the formal never-break list.
