### `DESIGN.md`

# forkrun Ring Architecture – Design Overview (v9.8.0-NUMA Golden Master)

## 1. Purpose

This document explains the internal architecture of **forkrun**’s ring-based execution engine. It focuses on *why* each mechanism exists, the invariants it maintains, and how the pieces interact under load. It is intended for readers who want to understand or extend the system.

The core goals are:

* Extremely high throughput on streaming workloads
* Minimal overhead on the fast path
* Correctness under bursty, skewed, or adversarial input
* Pure Bash compatibility with optional native accelerators

The guiding philosophy is:

> **Fast path is boring. Slow path is where complexity belongs.**

---

## 2. High-Level Model

forkrun consists of four cooperating roles (three in legacy flat mode, four when NUMA is active):

1. **NUMA Ingest** – Zero-copy splice from stdin into the shared memfd, routing data to the correct socket via `set_mempolicy`.
2. **Indexers / Scanners** – Identify line boundaries and publish availability into per-node rings.
3. **Workers** – Claim batches and execute user commands.
4. **Coordinator State** – Per-node shared-memory rings + global coordination primitives.

All coordination is done through shared memory, atomic operations, and kernel primitives (eventfd + pipes). No locks are taken on the fast path.

When `--nodes=1` (or auto-detected as single node) the system falls back to the classic flat pipeline while preserving every invariant.

---

## 3. The Ring Buffer

### 3.1 What the Ring Represents

The ring does *not* contain data. It contains **offset markers** into an append-only backing file (typically on tmpfs).

Each ring entry represents:

* A boundary where new data becomes visible
* Optionally, a marker that the batch is partial

This allows:

* Zero-copy data sharing
* Arbitrarily large inputs
* Workers to operate independently

### 3.2 Ring Entry Encoding

Each ring slot (`offset_ring`) is an **unsigned** 64-bit value:

* **Low 63 bits**: byte offset in the backing file
* **High bit (bit 63, `FLAG_PARTIAL_BATCH = 1ULL << 63`)**:

  * 0 → complete batch
  * 1 → partial batch (scanner hit EOF or boundary)

This encoding avoids extra metadata, keeps entries atomic, and supports offsets up to 2⁶³ bytes. The high bit is a flag, not an arithmetic sign — readers must mask it before using the offset as an address (`offset & ~FLAG_PARTIAL_BATCH`).

### 3.3 Atomic Invariants

* `write_idx` monotonically increases
* `read_idx` monotonically increases
* Each ring slot is written once, read once
* Readers never observe an uninitialized slot

Memory ordering:

* Scanner publishes ring entries with **release** semantics
* Workers consume them with **acquire** semantics

In NUMA mode each socket has its own independent `SharedState` ring; the invariants hold per node.

---

## 4. Claiming Work

### 4.1 Fast Path Claim

The fast path is intentionally simple:

1. Load `write_idx`
2. Atomically increment `read_idx` by batch size
3. Compute offsets from ring
4. Execute batch

No polling, no blocking, no branching beyond bounds checks.

If sufficient data exists, the worker never sleeps.

### 4.2 Waiting (Case 1)

If `read_idx >= write_idx`, the worker:

* Increments a waiter counter
* Polls an eventfd
* Sleeps until the scanner publishes more data

Wakeups are advisory; spurious wakeups are harmless.

---

## 5. Overshoot and Partial Batches

### 5.1 The Overshoot Problem

A worker may claim more data than currently exists, especially when batch sizes are large or input slows abruptly.

Rather than force all workers to stall, forkrun allows:

* Executing the *available* portion immediately
* Deferring the remainder

### 5.2 Escrow Mechanism

To handle deferred remainders, forkrun introduces **escrow**:

* A non-blocking anonymous pipe (per-node in NUMA mode)
* Entries contain: starting offset + remaining line count

When a worker overshoots:

1. It executes the partial batch
2. Publishes the remainder to escrow
3. Signals availability via `evfd_data`

### 5.3 Escrow Stealing

Idle workers:

* Check escrow before touching the ring
* If work exists, steal it
* Consume *at most* one batch
* Re-publish any leftover

This ensures:

* Only one owner per remainder
* No duplication
* Bounded contention

If escrow is full, the worker simply completes the batch itself. Correctness always wins over optimization.

---

## 6. Eventfd Usage

Eventfds are used strictly as **wake signals**, never as state.

There are multiple eventfds:

* Data availability (per-node)
* Worker spawning
* Overshoot notifications
* EOF signaling

Properties:

* Semaphore mode prevents counter overflow
* Spurious wakeups are allowed
* Missed wakeups are impossible due to monotonic indices

This keeps the design robust and simple.

---

## 7. Scanner Control Logic (Three-Phase Model)

The scanner operates in a three-phase control loop (restored and formalized in v6.63 and still present in v9.8):

### Phase 0: Warmup (Fairness & Producer Startup)

* Batch size `L = 1`
* Exactly ~N batches are emitted (N ≈ number of workers)
* Intent: Ensure every worker receives work early. Prevent large initial batches from being monopolized by the first worker.

### Phase 1: Geometric Ramp-Up (Fast Discovery)

* Batch size doubles geometrically (`L *= 2`)
* Each size is held for a fixed number of batches
* Ramp halts immediately on input stall
* O(log L) convergence, no oscillation, scanner-only logic

### Phase 2: PID-like Steady State (Adaptive Equilibrium)

Scanner periodically measures:
* Input publish rate
* Consumption rate
* Backlog depth
* Active worker count

Batch size is adjusted conservatively toward a target. Adjustments are slow to avoid oscillation.

**Signed batch size protocol** (see INVARIANTS.md for full formal rules):
* Scanner always publishes negative values (`-abs(N)`)
* Only workers may flip to positive via CAS (finalization)
* In full NUMA mode the protocol is simplified but the negative-advisory rule remains

**Tail ramp-down** is a distinct phase: once `tail_idx` is published the scanner stops changing batch size and all remaining batches become self-describing (sign bit + stride metadata).

### Phase 2b: Early Partial Flush (Low-Latency Trickle Mode)

Under normal load the scanner accumulates a full batch of `L` lines before publishing. However, when stdin is arriving slowly *and* workers are sitting idle, holding a partial batch in the scanner adds latency without benefit. The scanner detects this condition and flushes early.

**The two signals:**

* `stall_meter` — exponential moving average of input-stall events. It grows each time a read attempt on the backing file returns no new data (stdin is not delivering), and decays each time a read succeeds. It reflects the *sustained* rate of input stalls.
* `starve_meter` — exponential moving average of worker-starvation events. It grows each time `active_waiters > 0` is observed at the natural meter-update point, and decays otherwise. It reflects whether workers have been *sustainedly* idle.

**Why both are required:**

* Stall only (no starve): workers are keeping up with or ahead of stdin — there is no idle worker waiting for the partial batch. No benefit to flushing early.
* Starve only (no stall): data is available in the backing file but workers are consuming faster than the scanner can scan. Flushing smaller partial batches increases the scanner's per-line overhead and makes this situation worse, not better.
* Both saturated: stdin is arriving slowly AND workers are idle. Flushing the partial batch reduces latency at no throughput cost.

**Implementation detail:**

Both meters use the same EWMA kernel (`meter = (meter + xLim) >> 1` to grow, `meter >>= 1` to decay) with threshold `xLim - 3 = W + DAMPING_OFFSET - 3`. Meters update at their natural observation points on every loop iteration — not at flush time — so they track ongoing system state independently of flush frequency. The stall signal is captured into an `experienced_stall` flag at detection time and passed to the control macro at flush time, ensuring the signal is correctly scoped to the interval between flushes.

---

## 8. NUMA Topology Pipeline (v9.8+)

When multiple NUMA nodes are present:

```
stdin
  ↓ ring_numa_ingest (splice + set_mempolicy)
shared memfd
  ↓ index_pipe
ring_indexer_numa (boundary alignment + node routing)
  ↓ per-node pipes
ring_numa_scanner[N] (pinned to node)
  ↓ publish to per-node ring
Workers (claim from local ring or escrow)
```

Data is **born-local** at ingest time. Scanners are pinned. Workers inherit locality via `RING_NODE_ID`. Cross-socket traffic is minimized to the claim-pipe back-pressure and occasional escrow steals.

---

## 9. Memory Reclamation (Fallowing)

The backing file grows monotonically.

A background GC process:

* Observes the minimum active offset
* Punches holes behind it using `fallocate(PUNCH_HOLE)`

This:
* Preserves offsets
* Avoids fragmentation
* Requires no coordination with workers

---

## 10. Output Ordering

* `--realtime` / `--unbuffered`: direct to stdout
* `--ordered` / `--buffered`: per-worker memfd + `ring_order` (NUMA-aware major/minor merging using the ordering keys published by scanners)

The reorder path is the only place that may block.

---

## 11. Design Summary & Mental Model

Key properties of the architecture:

* Lock-free fast path
* Explicit slow paths
* Monotonic indices instead of condition variables
* Advisory wakeups
* Opportunistic load balancing
* Born-local NUMA data flow

**Mental model** (from PHYSICS.md):

> A speculative, cooperative work-stealing engine where correctness is enforced by monotonic progress, not locks — and where data is physically born on the correct socket.

Once that model clicks, the rest of the design follows naturally.

**See also:** `INVARIANTS.md` (the formal never-break list) and `PHYSICS.md` (the geophysics perspective).

