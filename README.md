# forkrun — NUMA-Aware Contention-Free Streaming Parallelization

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**forkrun is a self-tuning, drop-in replacement for GNU Parallel and `xargs -P` that accelerates shell-based data preparation by 50×–400× on modern CPUs and scales linearly on NUMA architectures.**

**forkrun achieves:**
- **200,000+ batch dispatches/sec** (vs ~500 for GNU Parallel)
- **~95–99% CPU utilization** across all cores (vs ~6% for GNU Parallel)
- **Near-zero cross-socket memory traffic** (NUMA-aware “born-local” design)
- **Automatic recovery and retry** when a worker unexpectedly dies processing a batch (v3.1.0+)
- **Seamless HPC Cluster Preemption** via automatic SLURM `SIGTERM`/`SIGUSR1` checkpointing (v3.4.0+)
- **Cartesian Parameter Sweeps** (`:::`) and Live TUI Telemetry (v3.4.0+)

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

**Verifiable Builds**: The embedded C-extension is compiled and injected transparently via GitHub Actions. You can trace the git blame of the Base64 blob directly to the public CI workflow run that compiled forkrun_ring.c, guaranteeing the binary contains no hidden malicious code.

---

## 🆕 What's New in v3.4.0
 
**v3.4.0** extends forkrun from a single-node accelerator into a facility-ready tool for long-running, cluster-scheduled, parameter-sweep workloads:
 
- **Live TUI dashboard** (`--tui`) — a 4 FPS terminal telemetry view showing per-node CPU/queue saturation, a live memory oscilloscope, and bottleneck heuristics, so you can watch NUMA balance and throughput in real time instead of guessing from `top`.
- **SLURM preemption support** — forkrun detects SLURM jobs automatically and cleanly checkpoints on `SIGTERM`/`SIGUSR1` (the standard preemption and pre-kill-warning signals), so a preempted or requeued job resumes exactly where it left off instead of restarting from scratch.
- **`--halt` failure-threshold auto-abort** — stop a pipeline automatically once too many batches fail, using the same `now,fail=N` / `fail=N%` syntax as GNU Parallel, so a bad input file or broken command doesn't silently burn through an entire allocation before anyone notices.
- **GNU Parallel-compatible parameter sweeps** (`:::`, `::::`, `--link`) — run a command across the cartesian product (or zipped pairing) of multiple input lists directly, with `{1}`, `{2}`, ... placeholders, without needing a separate driver script.
- **Every abnormal exit now checkpoints.** In addition to SLURM signals, forkrun now traps `SIGINT` (Ctrl+C), `SIGHUP` (dropped terminal/SSH session), and `SIGQUIT`, and always writes a `.forkrun_resume` file before exiting — so interactive runs are just as resumable as scheduled ones.

![forkrun TUI demo](https://raw.githubusercontent.com/jkool702/forkrun/refs/heads/NEW/TUI/DOCS/TUI/forkrun_demo.gif)

---

## ⚡ Benchmarks (14-core/28-thread i9-7940x, 100M+ lines)

| Workload                                        | forkrun                 | GNU Parallel                 | Speedup    | Notes |
|-------------------------------------------------|-------------------------|------------------------------|------------|-------|
| Max batch external binary (`-l 1:-1 /bin/true`) | **191.4 M lines/s**     | ~58 k lines/s                | **~3300×** | Zero-copy `vfork` fast-path |
| Default external binary (`/bin/true`)           | **86.9 M lines/s**      | ~58 k lines/s                | **~1500×** | Bypasses Bash AST entirely |
| Bash Builtin (`:`, fully-quoted args)           | **25.0 M lines/s**      | ~58 k lines/s                | **~430×**  | forkrun standard array mode |
| Ordered output (`-k`, external binary)          | **86.9 M lines/s**      | 57 k lines/s                 | **~1520×** | no measurable overhead |
| External `printf '%s\n'` (I/O heavy)            | **52.6 M lines/s**      | ~58 k lines/s                | **~900×**  | formatting + output |
| `-s` stdin passthrough (no-op)                  | **1.04 B lines/s**      | 6.05 M lines/s (`--pipe`)    | **~172×**  | streaming / `splice()` |
| `-b 512k` byte batches (no-op)                  | **2.51 B lines/s**      | 6.02 M lines/s (`--pipe`)    | **~417×**  | kernel-limited |

**Average CPU utilization across ~400 benchmarks**  
- **forkrun:** 97% (27.1 / 28 cores) — *No centralized dispatcher; all 27.1 cores do actual work.*
- **GNU Parallel:** 6% (2.68 / 28 cores) — *1 full core used strictly for dispatching work; 1.68 cores doing actual work.*

---

## 🧠 How It Works: The Physics of forkrun

Traditional tools like GNU Parallel use heavy regex parsing and IPC dispatch loops that bottleneck multi-socket servers. **forkrun** operates completely differently. The pipeline has four stages, each designed to preserve physical locality:

1. **Ingest (Born-Local NUMA):** Data is `splice()`'d from stdin into a shared memfd. This is **PFS-friendly** (avoids Lustre/NFS metadata storms). On multi-socket systems, `set_mempolicy(MPOL_BIND)` places each chunk's pages on a target NUMA node *before any worker touches them*. This placement is driven by real-time backpressure from the per-node indexers, making NUMA distribution completely self-load-balancing.
2. **Index:** Per-node indexers (pinned to their socket) find record boundaries using AVX2/NEON SIMD scanning at memory bandwidth. They dynamically batch based on runtime conditions, then publish offset markers into a per-node lock-free ring buffer.
3. **Claim (Contention-Free):** Workers claim batches via a single `atomic_fetch_add` — no CAS retry loops, no locks, no contention. If a worker process crashes, its transaction is safely rolled back and deposited into an escrow pipe for idle workers to steal.
4. **Reclaim:** A background fallow thread punches holes behind completed work via `fallocate(PUNCH_HOLE)`, bounding memory usage without breaking the offset coordinate system.

**Adaptive tuning** is fully automatic. A Pre-Flight AVX2/NEON SIMD popcount computes the globally optimal batch size during fork latency, instantly entering PID steady-state. If a worker spawns before the scan completes, a geometric fallback converges in O(log L) steps. Either way the worker fast-path is a single `atomic_fetch_add` with no user `-n` or `-j` configuration required.

---

## 🛠 Requirements & Dependencies

forkrun is designed to run anywhere with zero friction:
*   **Required:** Bash ≥ 4.0 (Bash 5.1+ highly recommended for array performance), Linux Kernel ≥ 3.17 (for `memfd`).

---

## 🏛️ Legacy Version (v2)

With the release of v3.0.0, `forkrun` has transitioned to a high-performance C-ring architecture (`frun.bash`). The older v2, pure-Bash coproc-based version (`forkrun.bash`) remains available in the `legacy/` directory. While v3 (`frun.bash`) is highly recommended for all modern workloads, v2 (`forkrun.bash`) remains as an alternate fully-functional high-performance bash stream parallelizer. forkrun v1 is not recommended for use.

---

## 🛣 Roadmap

forkrun currently guarantees correctness under the assumption that at least one worker per NUMA node remains alive until its assigned work completes — a safe assumption for local shell operations on healthy compute nodes. 

Priorities for the development roadmap include:
- **Enhanced checkpoint portability** and cluster-level resume support (e.g., seamless Slurm integration for preempted multi-node jobs).
- **Deeper integration** with facility workload managers.

*(If forkrun is saving your institution compute-hours, please consider sponsoring its development to accelerate these features!)*
