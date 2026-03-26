# forkrun — NUMA-Aware Contention-Free Streaming Parallelization

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**forkrun is a self-tuning, drop-in replacement for GNU Parallel and `xargs -P` that accelerates shell-based data preparation by 50×–400× on modern CPUs and scales linearly on NUMA architectures.**

**forkrun achieves:**
- **200,000+ batch dispatches/sec** (vs ~500 for GNU Parallel)
- **~95–99% CPU utilization** across all cores (vs ~6% for GNU Parallel)
- **Near-zero cross-socket memory traffic** (NUMA-aware “born-local” design)

forkrun is built for high-frequency, low-latency workloads on deep NUMA hardware — a regime where existing tools leave most cores idle due to IPC overhead and cross-socket data migration.

---

## 🚀 Quick Start (Installation & Usage)

`forkrun` is distributed as a single `bash` file with an embedded, self-extracting compiled C extension. There are no external dependencies (no Perl, no Python). 

Download and source it directly:
```bash
source <(curl -sL https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash)
```
*(Note: Sourcing the script sets up the required C loadable builtins in your shell environment).*

Once sourced, `frun` acts as a drop-in parallelizer:
```bash
frun my_bash_func < inputs.txt             # parallelize custom bash functions natively!
cat file_list | frun -k sed 's/old/new/'   # pipe-based input, ordered output
frun -k sort < records.tsv                 # stdin-passthrough, ordered output
frun -s -I 'gzip -c >{ID}.gz' < raw_logs   # stdin-passthrough, unique output names
```

---

## ⚡ Benchmarks (14-core/28-thread i9-7940x, 100M lines)

| Workload                                      | forkrun                 | GNU Parallel                 | Speedup    | Notes |
|-----------------------------------------------|-------------------------|------------------------------|------------|-------|
| Default (array + fully-quoted args, no-op)    | **24 M lines/s**        | 58 k lines/s                 | **~415×**  | forkrun default mode |
| Ordered output (`-k`, no-op)                  | **24.5 M lines/s**      | 57 k lines/s                 | **~430×**  | ordering is free in forkrun |
| `echo` (line args)                            | **22.6 M lines/s**      | ~55 k lines/s                | **~410×**  | typical shell command |
| `printf '%s\n'` (I/O heavy)                   | **12.8 M lines/s**      | ~58 k lines/s                | **~220×**  | formatting + output |
| `-s` stdin passthrough (no-op)                | **893 M lines/s**       | 6.05 M lines/s (`--pipe`)    | **~148×**  | streaming / splice |
| `-b 524288` byte batches (no-op)              | **1.54 B lines/s**      | 6.02 M lines/s (`--pipe`)    | **~256×**  | kernel-limited |

**Average CPU utilization across ~400 benchmarks**  
- **forkrun:** 95% (27.1 / 28 cores) — *No centralized dispatcher; all 27.1 cores do actual work.*
- **GNU Parallel:** 6% (2.68 / 28 cores) — *1 full core used strictly for dispatching work; 1.68 cores doing actual work.*

---

## 🧠 How It Works: The Physics of forkrun

Traditional tools like GNU Parallel use heavy regex parsing and IPC dispatch loops that bottleneck multi-socket servers. **forkrun** operates completely differently. The pipeline has four stages, each designed to preserve physical locality:

1. **Ingest (Born-Local NUMA):** Data is `splice()`'d from stdin into a shared memfd. This is **PFS-friendly** (avoids Lustre/NFS metadata storms). On multi-socket systems, `set_mempolicy(MPOL_BIND)` places each chunk's pages on a target NUMA node *before any worker touches them*. This placement is driven by real-time backpressure from the per-node indexers, making NUMA distribution completely self-load-balancing.
2. **Index:** Per-node indexers (pinned to their socket) find record boundaries using AVX2/NEON SIMD scanning at memory bandwidth. They dynamically batch based on runtime conditions, then publish offset markers into a per-node lock-free ring buffer.
3. **Claim (Contention-Free):** Workers claim batches via a single `atomic_fetch_add` — no CAS retry loops, no locks, no contention. Overshoots are handled by depositing remainders into an escrow pipe for idle workers to steal.
4. **Reclaim:** A background fallow thread punches holes behind completed work via `fallocate(PUNCH_HOLE)`, bounding memory usage without breaking the offset coordinate system.

**Adaptive tuning** is fully automatic. A PID-based controller discovers the optimal batch size in O(log L) steps and continuously adjusts based on input rate, consumption rate, and worker starvation — with no user `-n` or `-j` configuration required.

---

## 🛠 Requirements & Dependencies

forkrun is designed to run anywhere with zero friction:
*   **Required:** Bash ≥ 4.0 (Bash 5.1+ highly recommended for array performance), Linux Kernel ≥ 3.17 (for `memfd`).

---

## 🛣 Roadmap

forkrun currently guarantees correctness under the assumption that at least one worker per NUMA node remains alive until its assigned work completes — a safe assumption for local shell operations on healthy compute nodes. 

Priorities for the development roadmap include:
- **Failure isolation and per-batch retries** to handle transient worker crashes.
- **Resume-after-interruption** state saving to gracefully handle preempted cluster/Slurm jobs.
- **Deeper integration** with facility workload managers.

*(If forkrun is saving your institution compute-hours, please consider sponsoring its development to accelerate these features!)*

