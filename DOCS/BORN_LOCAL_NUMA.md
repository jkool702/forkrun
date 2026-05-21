### `BORN_LOCAL_NUMA.md`

# FORKRUN BORN-LOCAL NUMA ARCHITECTURE (v3.2.1)

This document defines the physical memory-routing architecture of `forkrun`. 

On modern multi-socket HPC systems (e.g., AMD EPYC, Intel Xeon), cross-socket memory access over the Infinity Fabric or QPI link is a primary performance bottleneck. Traditional parallelizers use reactive work-stealing, causing severe cross-socket memory migration. `forkrun` eliminates this via **Born-Local NUMA Placement**, ensuring that data is physically instantiated on the RAM banks of the socket that will process it, and structurally guaranteeing that workers never read across NUMA boundaries.

---

## §1. The Ingress Chunker (Proactive Placement)

The NUMA pipeline begins with a single Ingest thread that divides the input stream into chunks (up to 2 MB) and routes them to specific NUMA nodes *before* they are scanned or processed.

### 1.1 The "First-Touch" Allocation
In NUMA mode, the Ingress thread bypasses zero-copy `splice()` and explicitly uses standard `read()` and `write()` syscalls. 
Before writing a chunk to the shared `memfd`, the thread calls `set_mempolicy(MPOL_BIND)` to bind itself to a specific physical NUMA node. In Linux, the "First-Touch" memory policy dictates that physical RAM pages are instantiated on the node of the thread that first writes to them. By pinning itself, writing the chunk, and then re-pinning itself to the next node, the Ingress thread effectively stripes the `memfd` across the physical topography of the motherboard.

### 1.2 Backpressure & The IIR-Smoothed Adaptive Buffer Controller
Chunks are not distributed blindly. 
1. **Initial State:** The Ingress thread distributes an initial buffer of 3 chunks per node.
2. **Backpressure Routing:** Subsequent chunks are routed dynamically to the node with the lowest current backlog (`chunk_queue_head - chunk_queue_tail`).
3. **Dynamic Buffer Scaling:** The Ingress thread maintains a "read-ahead" buffer limit per node (starting at 3 chunks). It continuously monitors global cross-socket steal rates. Using a bounded Infinite Impulse Response (IIR) filter, it scales this buffer limit dynamically between 3 and 12 chunks. If steal rates rise, the buffer expands; if workers are keeping up locally, the buffer shrinks to reduce memory pressure and cache eviction.

---

## §2. The Per-Node Indexers (Boundary Alignment)

Because the Ingress chunker splits data arbitrarily at physical 2 MB byte boundaries, a chunk will almost always split a record (e.g., a line of text) in half. 

To resolve this, each NUMA node has a dedicated Indexer thread pinned to its socket. 
1. The Indexer uses SIMD-accelerated `memrchr` to scan backwards from the end of its assigned 2 MB chunk to find the final delimiter.
2. This delimiter becomes the *real* logical end of the chunk. 
3. The *real* logical start of the chunk is simply the real end of the previous chunk.

**The Physics Trade-off:** By doing this, a node's Indexer must read a few dozen bytes belonging to the adjacent chunk (which physically resides on a different NUMA socket). `forkrun` intentionally trades this microscopic penalty (~100 bytes of cross-socket traffic per 2 MB chunk) for the absolute guarantee that chunk boundaries perfectly align with record delimiters. 

---

## §3. The Per-Node Scanners

Once the Indexers establish the exact logical boundaries, the per-node Scanners (also pinned to their respective sockets) find the internal record boundaries and publish work batches.

Scanners in NUMA mode differ from standard UMA scanners in three ways:
1. **No Tail Cooldown:** NUMA scanners do not artificially ramp down batch sizes at the end of a chunk. They operate at maximum throughput until the chunk boundary is hit.
2. **The Scanner Shield:** Scanners are strictly limited in how far they can read ahead of the worker pool. This prevents a fast scanner from blowing out the L2/L3 cache with metadata while workers are still processing older batches.
3. **Topology-Aware Stealing:** If a Scanner runs out of local chunks, it is allowed to steal an unprocessed chunk from another NUMA node. However, to prevent thrashing, it will only steal if the victim node has a backlog exceeding a topological threshold: `1 + (NUMA_distance / 10)`. Under extreme starvation (e.g., EOF is reached and no new data will ever arrive), this threshold collapses to `1`, allowing full cluster drain.

---

## §4. The Worker Pools & The Structural Guarantee

Workers are pinned to specific NUMA nodes and consume work exclusively from their local Scanner's ring buffer (or Escrow pipe). 

### 4.1 The `FLAG_CHUNK_BOUNDARY` Barrier
To ensure workers never cross a chunk boundary, the Scanner applies a `FLAG_CHUNK_BOUNDARY` bitmask to the stride (line count) entry of the final batch in every chunk. 

When a worker executes a lock-free claim (`atomic_fetch_add`), it may speculatively claim multiple batches. However, as it resolves the pointers for its claim, it checks for the `FLAG_CHUNK_BOUNDARY` bit in the `stride_ring`. If it detects this flag mid-claim, it immediately truncates its batch exactly at the boundary, processing the contiguous data and depositing the remaining claimed slots into the Escrow pipe.

### 4.2 The Ultimate Structural Guarantee
Because:
1. Indexers perfectly align chunk boundaries with record delimiters.
2. Scanners cap chunks with the `FLAG_CHUNK_BOUNDARY` barrier.
3. Workers are forbidden from claiming data across a `FLAG_CHUNK_BOUNDARY` barrier.

...`forkrun` provides a **mathematical, structural guarantee that no worker will ever receive a batch that spans two non-contiguous chunks.** 

Because chunks are guaranteed to be isolated to a single physical NUMA socket via the Ingress thread's `MPOL_BIND` First-Touch allocation, **a worker will never execute a memory read that physically crosses a NUMA boundary** (unless explicitly stealing due to starvation). 

---

## §5. Architectural Trade-offs: Exact Batch Sizing (`-L`)

This architecture enforces one strict limitation: **`forkrun` cannot guarantee exactly *N* lines per batch in NUMA mode.**

Because the Ingress chunker carves the stream based on physical byte sizes (2 MB) rather than logical line counts, a chunk will contain an arbitrary number of lines. Guaranteeing exactly *N* lines per batch would require every chunk to magically contain an integer multiple of *N* lines. 

If a worker is assigned to process exactly *N* lines, but reaches the `FLAG_CHUNK_BOUNDARY` boundary after *M* lines (where $M < N$), fulfilling the exact-batch contract would require the worker to reach across the chunk boundary to pull the remaining $N - M$ lines from the next chunk. This next chunk physically resides on a different NUMA socket. Doing so would violate the Born-Local structural guarantee and trigger heavy cross-socket memory traffic.

**The Resolution:** 
If a user's workload strictly requires exactly *N* lines per batch (`-L` flag), `forkrun` automatically demotes the pipeline to the traditional UMA (Uniform Memory Access) architecture. While UMA mode still benefits from the ultra-fast C-ring and zero-copy `posix_spawnp` execution paths, it will incur the standard cross-socket memory migration tax inherent to all traditional shell parallelizers. 

