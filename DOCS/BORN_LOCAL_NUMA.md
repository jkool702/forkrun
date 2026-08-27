### `BORN_LOCAL_NUMA.md`

# FORKRUN BORN-LOCAL NUMA ARCHITECTURE

This document defines the physical memory-routing architecture of `forkrun`. 

On modern multi-socket HPC systems (e.g., AMD EPYC, Intel Xeon), cross-socket memory access over the Infinity Fabric or QPI link is a primary performance bottleneck. Traditional parallelizers use reactive work-stealing, causing severe cross-socket memory migration. `forkrun` eliminates this via **Born-Local NUMA Placement**, ensuring that data is physically instantiated on the RAM banks of the socket that will process it, and structurally guaranteeing that workers never read across NUMA boundaries.

---

## §1. The Ingress Chunker (Proactive Placement)

The NUMA pipeline begins with a single Ingest process that divides the input stream into chunks (up to 2 MB) and routes them to specific NUMA nodes *before* they are scanned or processed.

### 1.1 The "First-Touch" Allocation
In NUMA mode, the Ingress process bypasses zero-copy `splice()` and explicitly uses standard `read()` and `write()` syscalls. 
Before writing a chunk to the shared `memfd`, the thread calls `set_mempolicy(MPOL_BIND)` to bind itself to a specific physical NUMA node. In Linux, the "First-Touch" memory policy dictates that physical RAM pages are instantiated on the node of the thread that first writes to them. By pinning itself, writing the chunk, and then re-pinning itself to the next node, the Ingress process effectively stripes the `memfd` across the physical topography of the motherboard.

### 1.2 Backpressure & The Geometric Accumulation Ramp
Chunks are not distributed blindly. 
1. **The 1MB Pipe Resize:** If `stdin` is a kernel pipe, `forkrun` expands the kernel pipe buffer to 1 MB to allow massive reads and reduce syscall overhead.
2. **Geometric Accumulation:** To prevent kernel memory-policy thrashing on small pipe reads, the Ingest process buffers data to the current NUMA node before switching. It starts at a 64 KB floor and geometrically doubles (up to 2 MB). This ensures tiny files are perfectly distributed across all sockets, while massive streams pool into deep 2 MB reservoirs.
3. **Starvation Backpressure:** If any other NUMA node completely empties its local queue, the Ingest process cuts the accumulation phase short to immediately feed the starving node.
4. **Dynamic Buffer Scaling:** The Ingest process maintains a "read-ahead" buffer limit. Using a bounded Infinite Impulse Response (IIR) filter, it scales this limit dynamically between 4 and 128 chunks.

---

## §2. The Per-Node Indexer Processes (Boundary Alignment)

Because the Ingress chunker splits data arbitrarily at physical 2 MB byte boundaries, a chunk will almost always split a record (e.g., a line of text) in half. 

To resolve this, each NUMA node has a dedicated Indexer process pinned to its socket. 
1. The Indexer uses SIMD-accelerated `memrchr` to scan backwards from the end of its assigned 2 MB chunk to find the final delimiter.
2. This delimiter becomes the *real* logical end of the chunk. 
3. The *real* logical start of the chunk is simply the real end of the previous chunk.

**The Physics Trade-off:** By doing this, a node's Indexer process must read a few dozen bytes belonging to the adjacent chunk (which physically resides on a different NUMA socket). `forkrun` intentionally trades this microscopic penalty (~100 bytes of cross-socket traffic per 2 MB chunk) for the absolute guarantee that chunk boundaries perfectly align with record delimiters. 

---

## §3. The Per-Node Scanners

Once the Indexers establish the exact logical boundaries, the per-node Scanners (also pinned to their respective sockets) find the internal record boundaries and publish work batches.

Scanners in NUMA mode differ from standard UMA scanners in three ways:
1. **No Tail Cooldown:** NUMA scanners do not artificially ramp down batch sizes at the end of a chunk. They operate at maximum throughput until the chunk boundary is hit, at which point the final partial batch is published as a normal single-slot entry with `FLAG_MAJOR_EOF` set in `minor_ring`. Workers claim it identically to any other slot.
2. **The Scanner Shield:** Scanners are strictly limited in how far they can read ahead of the worker pool. This prevents a fast scanner from blowing out the L2/L3 cache with metadata while workers are still processing older batches.
3. **Topology-Aware Stealing:** If a Scanner runs out of local chunks, it is allowed to steal an unprocessed chunk from another NUMA node. However, to prevent thrashing, it will only steal if the victim node has a backlog exceeding a topological threshold: `1 + (NUMA_distance / 10)`. Under extreme starvation (e.g., EOF is reached and no new data will ever arrive), this threshold collapses to `1`, allowing full cluster drain.

**Distance-charged stealing.** The threshold formula `1 + (distance / 10)` makes the minimum backlog required to steal *directly proportional to the cost of stealing* (farther = more expensive = higher threshold). Steal *propensity* is inversely proportional to cost. On `numa=fake=4` every inter-node distance is 10, so the threshold bottoms out at 2 chunks — fake-NUMA measurements are therefore a worst case. On real 2-socket EPYC, cross-socket distances of 32–40 raise the floor to 4–5 chunks before the dynamic scaling multiplier applies. Stealing permission is priced by the topology itself. (Exception: under global-EOF drain the threshold collapses to 1 so the stream can finish; bounded to end-of-stream.)

---

## §4. The Worker Pools & The Structural Guarantee

Workers are pinned to specific NUMA nodes and consume work exclusively from their local Scanner's ring buffer (or Escrow pipe). 

### 4.1 The `FLAG_MAJOR_EOF` Chunk-End Marker

To ensure workers and the ordering subsystem can detect the end of each NUMA chunk, the Scanner sets bit 31 (`FLAG_MAJOR_EOF = 1U << 31`) in the `minor_ring` entry of the **last batch in every chunk**. The `minor_ring` field otherwise holds the batch's within-chunk sequence number (bits 30–0), used by `ring_order` for global merge ordering.

The old `stride_ring` / `FLAG_CHUNK_BOUNDARY` mechanism (which embedded line counts and a boundary flag in a 16-bit field) has been replaced by the `offset_ring` + `end_ring` pair (explicit start/end byte offsets) and `FLAG_MAJOR_EOF` in `minor_ring`. The Scanner now fully determines all batch boundaries before publishing to the ring, so workers never need to detect a boundary mid-claim.

When a worker executes its lock-free claim (`atomic_fetch_add` of exactly 1), it receives a single ring slot covering a byte range `[offset_ring[slot], end_ring[slot])`. A slot marked with `FLAG_MAJOR_EOF` is processed identically to any other slot — the flag is only consumed by the `ring_order` output-ordering thread to advance its major sequence counter.

### 4.2 The Ultimate Structural Guarantee
Because:
1. Indexers perfectly align chunk boundaries with record delimiters.
2. Scanners bound every batch within a single chunk and mark the final batch with `FLAG_MAJOR_EOF` in `minor_ring`.
3. Workers claim exactly one slot at a time; a single-slot claim by definition cannot span two chunks.

...`forkrun` provides a **mathematical, structural guarantee that no worker will ever receive a batch that spans two non-contiguous chunks.**

Because chunks are guaranteed to be isolated to a single physical NUMA socket via the Ingress process's `MPOL_BIND` First-Touch allocation, **a worker will never execute a memory read that physically crosses a NUMA boundary** (unless explicitly stealing due to starvation). 

---

## §5. Exact Batch Sizing (`-L`) & The Scanner-Handoff Chain (v3.5.0+)

Prior to v3.5.0, guaranteeing exactly *N* lines per batch (`-L`) in NUMA mode required automatically demoting the pipeline to UMA. Because the Ingress process carves memory by physical byte sizes (2 MB) rather than line counts, chunks almost never contain an integer multiple of *N* lines.

In **v3.5.0+**, `forkrun` provides **Native NUMA support for `-L`** via the **Scanner-Handoff Chain**:

### 5.1 The Scanner-Handoff Mechanism
1. **Indexer Bypass:** The per-node Indexer skips delimiter alignment. The per-node Scanners assume direct ownership of chunk boundaries (`actual_end`) and cumulative line tracking (`cum_lines`).
2. **Serialized Scan Gate:** Because an exact batch boundary is a global sequence invariant, scanning is serialized across NUMA sockets. Scanner $M+1$ waits for Scanner $M$ to publish both its boundary and cumulative line count.
3. **The Uniform Handoff:** 
   - Every scanner scans its own born-local chunk *completely* from `raw_start` to `raw_end` (zero rescanning of bytes).
   - If a chunk ends with an incomplete batch of $k < L$ lines, the scanner publishes `actual_end = batch_start` (the byte offset where the open batch originated, which may point into an earlier chunk) and `cum_lines`.
   - Scanner $M+1$ begins counting delimiters in its own chunk, seeded with `lines_in_batch = cum_lines % L`.
   - When the $L$-th line is reached in chunk $M+1$, it publishes a batch covering `[batch_start, current_delim_end)`.
4. **The -L Locality Tax:** The worker that claims a boundary-straddling batch will read the initial $k$ lines across the NUMA interconnect. We trade a microscopic cross-socket read (at most $L-1$ lines per 2 MB chunk) to preserve exact batch sizing without abandoning NUMA topology.

*(Note: Multi-parameter sweeps `:::` still run under UMA, as they require $L=1$ where the flat pipeline is naturally optimal).*

---

## §6. Deterministic Stream Prefix Limiting (`-n`) (v3.5.0+)

In a multi-socket topology, chunks are striped round-robin across nodes (Node 0 owns chunks 0, 2, 4; Node 1 owns 1, 3, 5). 

### 6.1 The Pre-v3.5.0 Pitfall: "First Encountered" vs. "True Stream Prefix"
Traditional parallelizers with loose atomic counters suffer from spatial race conditions: a fast scanner on Node 1 processing chunk 1 could claim records before Node 0 finished scanning chunk 0. When the limit $N$ was reached, the output contained an arbitrary sample of $N$ lines from across the cluster—violating true stream-order prefix semantics, and often over-delivering due to atomic commit lag.

### 6.2 The v3.5.0 Cumulative Line Count Chain
In `forkrun` v3.5.0+, `-n N` is guaranteed to return **strictly the first $N$ records of the original input stream**:

1. **Sequential Cumulative Handoff:** Scanner $M$ receives the exact total line count `prev_cum` through chunk $M-1$.
2. **Exact Delimiter Clamping:** When chunk $M$ observes `prev_cum + local_lines >= N`, it clamps the batch to exactly:
   $$\text{allowed} = N - \text{prev\_cum}$$
   The SIMD scanner rewinds in-buffer to the exact terminating delimiter of the $\text{allowed}$-th line, commits the batch, and halts.
3. **Cutoff Propagation:** Chunk $M$ publishes `limit_cutoff_major = M + 1`.
4. **Clean Skip Cascade:** All subsequent chunks ($M+1, M+2, \dots$) observe that their major ID is past the cutoff and skip scanning entirely without blocking or waiting on dead predecessor scanners.

**Run-length dependence of steal rate.** The 0.0–0.2% file-input cross-socket figure holds for meaningful run lengths (≥ a few hundred chunks). Micro-runs of ~50 chunks can show a single-steal 2.0% startup transient from initial load-balancing; this is expected and amortizes to <0.2% on longer streams.
