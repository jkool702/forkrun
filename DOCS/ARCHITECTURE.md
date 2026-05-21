# forkrun Architecture

**High-performance, NUMA-aware, resilient stream parallelization for Linux.**

forkrun is a specialized dataflow engine designed from the ground up for **maximum single-node throughput** on massive streaming workloads, while maintaining strong correctness and resilience guarantees.

## Design Philosophy

> **"Make the fast path boring. Put complexity only where it is required."**

forkrun achieves extreme performance by:
- Eliminating unnecessary work on the happy path
- Treating data locality and monotonic progress as first-class invariants
- Using optimistic execution with cheap recovery instead of heavy coordination
- Leveraging physical hardware constraints (NUMA, cache hierarchy, memory bandwidth)

## Core Architecture Diagram

```mermaid
flowchart TD
    Input[Input Stream\nstdin or file] 
    --> Ingest[Ingress Thread\nsplice / write + MPOL_BIND]

    Ingest --> Memfd[(Shared memfd\nBorn-Local Pages)]

    Memfd --> Indexer[Per-Node Indexer\nSIMD Boundary Alignment]
    Indexer --> Scanner[Per-Node Scanners\nAVX2 / NEON Batching]

    Scanner --> Ring[Lock-Free Ring Buffer\nPer-NUMA Node]
    Ring --> Workers[Worker Threads\nPinned to Node]

    Workers --> Backend1[Bash Builtins / Functions\nring_map]
    Workers --> Backend2[External Binaries / -X\nring_exec + posix_spawnp]
    Workers --> Backend3[C Plugin Callback / -C\nZero-Tax Execution]

    Backend1 & Backend2 & Backend3 --> Output[Output Handler\nOrdered / Buffered / Realtime]
    Output --> Checkpoint[Seqlock Ledger\n.forkrun_resume]

    Ring -.-> Escrow[Escrow Pipe\nOvershoot / Work Stealing]
    Workers -.-> DeathPipe[Death Pipe + POLLHUP\nZero-Cost Failure Detection]

    classDef core fill:#1e3a8a,stroke:#60a5fa,color:white
    classDef memory fill:#065f46,stroke:#34d399,color:white
    classDef path fill:#701a75,stroke:#f472b6,color:white
    classDef output fill:#4338ca,stroke:#a5b4fc,color:white

    class Ingest,Indexer,Scanner,Ring core
    class Memfd memory
    class Workers,Backend1,Backend2,Backend3 path
    class Output,Checkpoint output
```

---

## Major Subsystems

### 1. Born-Local NUMA Pipeline
Proactive data placement ensures that data is physically allocated on the NUMA node that will consume it. This eliminates the vast majority of cross-socket memory traffic that plagues traditional tools.

→ [`BORN_LOCAL_NUMA.md`](BORN_LOCAL_NUMA.md)

### 2. Lock-Free Ring Buffer Core
A carefully designed single-producer, multi-consumer ring per NUMA node with monotonic indices and minimal synchronization.

→ [`DESIGN.md`](DESIGN.md) and [`INVARIANTS.md`](INVARIANTS.md)

### 3. Adaptive Intelligent Batching
A multi-phase controller (warmup → geometric ramp → steady-state) that dynamically tunes batch sizes based on real-time system behavior.

→ [`PHYSICS.md`](PHYSICS.md)

### 4. Resilience & Exactly-Once Protocol
Optimistic execution with near-zero happy-path overhead, instant failure detection via Death Pipe, per-worker recovery, and resume capability.

→ [`RESILIENCE_PROTOCOL.md`](RESILIENCE_PROTOCOL.md) and [`EOF_PROTOCOL.md`](EOF_PROTOCOL.md)

### 5. Execution Backends

| Backend                  | Speed                  | Use Case                          |
|--------------------------|------------------------|-----------------------------------|
| Bash builtins/functions  | Very Fast              | General shell usage               |
| `posix_spawnp` (`-X`)    | Significantly Faster   | External binaries                 |
| C Plugin (`-C`)          | **Fastest**            | Maximum performance callbacks     |

## Documentation Map

- [`FORKRUN_OVERVIEW.md`](FORKRUN_OVERVIEW.md) — High-level introduction and benchmarks
- [`ECONOMIC_IMPACT.md`](ECONOMIC_IMPACT.md) — Value proposition for HPC centers
- [`DESIGN.md`](DESIGN.md) — Engineering blueprint
- [`PHYSICS.md`](PHYSICS.md) — Intuitive mental model
- [`BORN_LOCAL_NUMA.md`](BORN_LOCAL_NUMA.md) — NUMA architecture
- [`RESILIENCE_PROTOCOL.md`](RESILIENCE_PROTOCOL.md) — Failure handling & guarantees
- [`INVARIANTS.md`](INVARIANTS.md) — Formal rules that must never be broken
- [`FLAGS.md`](FLAGS.md) — Command-line reference
- [`EOF_PROTOCOL.md`](EOF_PROTOCOL.md) — End-of-file and stream termination

---
