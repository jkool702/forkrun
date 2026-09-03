# forkrun — NUMA-Aware Contention-Free Streaming Parallelization

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**forkrun is a self-tuning, drop-in replacement for GNU Parallel and `xargs -P` that accelerates shell-based data preparation by 50×–400× for typical shell builtins (up to ~3300× for external-binary no-op microbenchmarks) on modern CPUs and scales linearly on NUMA architectures.**

**forkrun achieves:**
- **200,000+ batch dispatches/sec** (vs ~500 for GNU Parallel)
- **87–99% CPU utilization** across all cores depending on mode and input size (vs ~6% for GNU Parallel) — ~95–99% for sustained default/external modes, ~90% aggregate across ~400 mixed benchmarks, lower for sub-second or byte-mode jobs by design
- **Born-local NUMA placement**: file ingest measures 0.0–0.2% cross-socket chunks. Under fast-draining *pipe* input, 2–13% of chunks may be stolen — by design (an idle node costs more than a remote chunk). Real multi-socket topologies raise the steal threshold with distance (`1 + distance/10`), so these figures — measured on `numa=fake=4`, where all distances are 10 — are a **worst case**. (The end-of-stream drain collapses the threshold to 1 regardless of distance; this is bounded to EOF.)
- **Automatic recovery and retry** when a worker unexpectedly dies processing a batch (v3.1.0+)

forkrun is built for high-frequency, low-latency workloads on deep NUMA hardware — a regime where existing tools leave most cores idle due to IPC overhead and cross-socket data migration.

---

## 🚀 Quick Start (Installation & Usage)

forkrun is distributed as a single `bash` file with an embedded, self-extracting compiled C extension. There are no external dependencies (no Perl, no Python). 

Download and source it directly:
```bash
# Option 1: download and source
wget https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash
source ./frun.bash

# Option 2: source curl stream
source <(curl -sL https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash)
```
*(Note: Sourcing the script sets up the required C loadable builtins in your shell environment).*

Once sourced, `frun` acts as a drop-in parallelizer:
```bash
frun my_bash_func < inputs.txt             # parallelize custom bash functions natively!
cat file_list | frun -k sed 's/old/new/'   # pipe-based input, ordered output
frun -k -s sort < records.tsv              # stdin-passthrough, ordered output
frun -s -I 'gzip -c >{ID}.gz' < raw_logs   # stdin-passthrough, unique output names
```

**Auditable Builds**: the embedded C extension is compiled and injected by a public GitHub Actions workflow; the git history of the base64 blob traces every byte to a specific CI run of `forkrun_ring.c`. (Reproducible builds with published checksums are on the roadmap and would upgrade this to cryptographic attestation.)

---

## ⚡ Benchmarks (14-core/28-thread i9-7940x, 100M+ lines)

| Workload                                        | forkrun                 | GNU Parallel                 | Speedup    | Notes |
|-------------------------------------------------|-------------------------|------------------------------|------------|-------|
| Max batch external binary (`-l 1:-1 /bin/true`) | **191.4 M lines/s**     | ~58 k lines/s                | **~3300×** | Zero-copy `vfork` fast-path |
| Default external binary (`/bin/true`)           | **86.9 M lines/s**      | ~58 k lines/s                | **~1500×** | Bypasses Bash AST entirely |
| Bash Builtin (`:`, fully-quoted args)           | **25.0 M lines/s**      | ~58 k lines/s                | **~430×**  | forkrun standard array mode |
| Ordered output (`-k`, external binary)          | **86.9 M lines/s**      | 57 k lines/s                 | **~1520×** | ordering has zero measurable overhead |
| External `printf '%s\n'` (I/O heavy)            | **52.6 M lines/s**      | ~58 k lines/s                | **~900×**  | formatting + output |
| `-s` stdin passthrough (no-op)                  | **1.04 B lines/s**      | 6.05 M lines/s (`--pipe`)    | **~172×**  | streaming / `splice()` |
| `-b 512k` byte batches (no-op)                  | **2.51 B lines/s**      | 6.02 M lines/s (`--pipe`)    | **~417×**  | kernel-limited |


> **Note on benchmark basis:** headline throughputs above are *conservative* 100M-line measurements. Top modes (`-s`, `-b`, external-binary) are limited by a ~30 ms fixed pipeline bring-up cost; ≥1B-line runs remove this fixed cost and show 30–50% higher peak rates. The 50×–400× range quoted in the intro is the typical shell-builtin range; microbenchmark extremes (`/bin/true`, `-l 1:-1`) reach ~1500–3300× due to GNU Parallel's per-item Perl fork overhead.

**Average CPU utilization across ~400 benchmarks (mix-dependent)**  
- **forkrun:** ~90% aggregate (27.1 / 28 cores in steady-state default mode = 97%; 27.6/28 = 98.6% for default-mode sustained runs; `-U` unsafe runs hit 27.1+/28; `-b 512k` on 100 MB intentionally ~2.6/28) — *No centralized dispatcher; all cores do actual work when work exists.*
- **GNU Parallel:** 6% (2.68 / 28 cores) — *1 full core used strictly for dispatching work; 1.68 cores doing actual work.*

---

## 🧠 How It Works: The Physics of forkrun

Traditional tools like GNU Parallel use heavy regex parsing and IPC dispatch loops that bottleneck multi-socket servers. **forkrun** operates completely differently. The pipeline has four stages, each designed to preserve physical locality:

1. **Ingest (Born-Local NUMA):** Data is `splice()`'d from stdin into a shared memfd. This is **PFS-friendly** (avoids Lustre/NFS metadata storms). On multi-socket systems, `set_mempolicy(MPOL_BIND)` places each chunk's pages on a target NUMA node *before any worker touches them*. This placement is driven by real-time backpressure from the per-node indexers, making NUMA distribution completely self-load-balancing.
2. **Index:** Per-node indexers (pinned to their socket) find record boundaries using AVX2/NEON SIMD scanning at memory bandwidth. They dynamically batch based on runtime conditions, then publish offset markers into a per-node lock-free ring buffer.
3. **Claim (contention-free *(no userspace locks or CAS retry loops on the fast path — two amortized atomic RMWs per batch (`read_idx` + `total_lines_consumed`), sharded per NUMA node)*):** Workers claim batches via a single `atomic_fetch_add` — no CAS retry loops, no locks, no contention. If a worker process crashes, its transaction is safely rolled back and deposited into an escrow pipe for idle workers to steal.
4. **Reclaim:** A background fallow thread punches holes behind completed work via `fallocate(PUNCH_HOLE)`, bounding memory usage without breaking the offset coordinate system.

**Adaptive tuning** is fully automatic. A Pre-Flight AVX2/NEON SIMD popcount computes the globally optimal batch size during fork latency, instantly entering PID steady-state. If a worker spawns before the scan completes, a geometric fallback converges in O(log L) steps. Either way the worker fast-path is a single `atomic_fetch_add` with no user `-n` or `-j` configuration required.

---

## 🛠 Requirements & Dependencies

forkrun is designed to run anywhere with zero friction:
*   **Required:** Bash ≥ 4.0 (Bash 5.1+ highly recommended for array performance), Linux Kernel ≥ 3.17 (for `memfd`). Kernels ≥ 4.5 additionally enable the `copy_file_range` fast path; older kernels automatically fall back to `sendfile`/read-write with no functional difference.

---

## 🏛️ Legacy Version (v2)

With the release of v3.0.0, `forkrun` has transitioned to a high-performance C-ring architecture (`frun.bash`). The older v2, pure-Bash coproc-based version (`forkrun.bash`) remains available in the `legacy/` directory. While v3 (`frun.bash`) is highly recommended for all modern workloads, v2 (`forkrun.bash`) remains as an alternate fully-functional high-performance bash stream parallelizer. forkrun v1 is not recommended for use.

---

## 🛣 Roadmap

forkrun features robust intra-node fault tolerance and preemption recovery (automatically trapping worker failures and Slurm signals to generate exactly-once checkpoints).

Priorities for the development roadmap include:
- **Cluster-level multi-node resume support** across distributed compute fabrics.
- **Deeper integration** with facility workload managers for dynamic resource elasticity.

*(If forkrun is saving your institution compute-hours, please consider sponsoring its development to accelerate these features!)*
