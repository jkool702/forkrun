# forkrun — NUMA-Aware Contention-Free Streaming Parallelization for HPC Data Prep

**forkrun is a self-tuning, drop-in replacement for GNU Parallel that accelerates shell-based data preparation by 50×–400× for typical shell builtins (up to ~3300× for external-binary no-op microbenchmarks) on modern CPUs and scales linearly (or better) on NUMA systems like Frontier.**

**forkrun achieves:**

- **200,000+ batch dispatches/sec** (vs ~500 for GNU Parallel)
- **87–99% CPU utilization** across all cores depending on mode and input size (vs ~6% for GNU Parallel) — ~95–99% for sustained default/external modes, ~90% aggregate across mixed benchmarks
- **Born-local NUMA placement**: file ingest measures 0.0–0.2% cross-socket chunks. Under fast-draining *pipe* input, 2–13% of chunks may be stolen — by design (an idle node costs more than a remote chunk). Real multi-socket topologies raise the steal threshold with distance (`1 + distance/10`), so these figures — measured on `numa=fake=4`, where all distances are 10 — are a **worst case**. (The end-of-stream drain collapses the threshold to 1 regardless of distance; this is bounded to EOF.)
- **Automatic recovery and retry** when a worker unexpectedly dies processing a batch

forkrun is built for high-frequency, low-latency workloads on NUMA hardware - a regime where existing tools leave most cores idle.

## The Problem

Data preparation on multi-socket HPC systems like Frontier means running millions of fast shell operations — format conversions, field extractions, validation checks, and file transforms — across inputs ranging from a few records to billions of lines. GNU Parallel and `xargs -P` were designed for long-running jobs, not microsecond-scale operations on NUMA hardware. At scale, their per-item fork overhead, cross-socket data migration, and lock contention become the bottleneck — not the work itself. 

forkrun, in its fastest mode, can distribute **200 000+ batches/sec** on a single node — while **GNU Parallel struggles to break 500**. On Frontier, this potentially reduces the cost of data prep (measured in total node time) from over 50% down to under 10%.

## What forkrun Is

**forkrun** is an **intra-node** drop-in shell parallelizer that replaces `xargs -P` and GNU Parallel for streaming workloads on a single machine. It is easy to use — source the script, and it can immediately parallelize native bash functions or external commands:

```bash
. frun.bash                                # sourcing frun.bash sets up *everything*
frun my_bash_func < inputs.txt             # parallelize custom bash functions!
cat file_list | frun -k sed 's/old/new/'   # pipe-based input, ordered output
frun -k -s sort < records.tsv              # stdin-passthrough, ordered output
frun -s -I 'gzip -c >{ID}.gz' < raw_logs   # stdin-passthrough, unique output names
```

Under the hood, forkrun is a **contention-free *(no userspace locks or CAS retry loops on the fast path — two amortized atomic RMWs per batch (`read_idx` + `total_lines_consumed`), sharded per NUMA node)*, NUMA-aware, dynamically self-tuning parallelization engine** implemented as a set of C loadable bash builtins. It coordinates workers through shared memory and atomic operations — no locks on the fast path, no cross-socket data migration, no per-item fork overhead.

## How It Works

**The data pipeline** has four stages, each designed to preserve locality:
1. **Ingest**: Data is `splice()`'d from stdin into a shared memfd. This is **PFS-friendly**, multiplexing data entirely in kernel space without generating filesystem metadata storms (no `stat()`/`open()` cascades). On multi-socket systems, `set_mempolicy(MPOL_BIND)` places each chunk's pages on a target NUMA node *before any worker touches them*. This placement is driven by real-time backpressure from the per-node indexers, making NUMA distribution completely self-load-balancing. Data is always **born-local**.
2. **Index**: Per-node indexers (pinned to their socket) find record boundaries using AVX2/NEON SIMD scanning at memory bandwidth, dynamically batch based on runtime conditions, then publish offset markers into a per-node lock-free ring buffer.
3. **Claim**: Workers claim batches via a single `atomic_fetch_add` — no CAS retry loops, no locks, no contention. If a worker process crashes, its transaction is safely rolled back and deposited into an escrow pipe for idle workers to steal.
4. **Reclaim**: A background fallow thread punches holes behind completed work via `fallocate(PUNCH_HOLE)`, bounding memory usage without breaking the offset coordinate system.

**Adaptive tuning** is fully automatic. During the Bash fork-latency window a SIMD Pre-Flight Popcount (AVX2/NEON) measures total available lines and computes the globally optimal initial batch size, jumping the scanner directly into PID steady-state before the first worker claims a slot. If data arrives too quickly for the pre-flight scan to complete, the scanner falls back to a geometric ramp that converges in O(log L) steps. Either way the worker fast-path is identical -- a single `atomic_fetch_add` claiming exactly one slot -- with no user `-n` or `-j` configuration required. forkrun runs efficiently whether it has 20 inputs from `ping` running on your laptop, or a billion lines from a file on a ramdisk running on a Frontier node.

## Benchmarks (14-core/28-thread i9-7940x, 100 M lines)


> **Note on benchmark basis:** headline throughputs above are *conservative* 100M-line measurements. Top modes (`-s`, `-b`, external-binary) are limited by a ~30 ms fixed pipeline bring-up cost; ≥1B-line runs remove this fixed cost and show 30–50% higher peak rates. The 50×–400× range quoted in the intro is the typical shell-builtin range; microbenchmark extremes (`/bin/true`, `-l 1:-1`) reach ~1500–3300× due to GNU Parallel's per-item Perl fork overhead.

| Workload                                      | forkrun                 | GNU Parallel                 | Speedup    | Notes |
|-----------------------------------------------|-------------------------|------------------------------|------------|-------|
| Default (array + fully-quoted args, no-op)    | **25.0 M lines/s**      | 58 k lines/s                 | **~430×**  | forkrun default mode |
| Ordered output (`-k`, no-op)                  | **24.5 M lines/s**      | 57 k lines/s                 | **~430×**  | no measurable overhead |
| `echo` (line args)                            | **22.6 M lines/s**      | ~55 k lines/s                | **~410×**  | typical shell command |
| `printf '%s\n'` (I/O heavy)                   | **12.8 M lines/s**      | ~58 k lines/s                | **~220×**  | formatting + output |
| `-s` stdin passthrough (no-op)                | **1.04 B lines/s**      | 6.05 M lines/s (`--pipe`)    | **~172×**  | streaming / splice |
| `-b 512k` byte batches (no-op)                | **2.51 B lines/s**      | 6.02 M lines/s (`--pipe`)    | **~417×**  | kernel-limited |

<small>NOTE: All benchmarks run on single-socket UMA hardware with emulated NUMA (booted with `numa=fake=4` to emulate 4 nodes). On real multi-socket NUMA hardware, forkrun is expected to scale linearly (or better).</small>

**Test Coverage & Validation**
- forkrun has been rigorously validated with **4,272 successful test runs**: (316 unit tests + 396 benchmark runs) × (UMA + NUMA) × (baseline + TSan + ASan/UBSan) = 4,272

**Batch distribution rate**
- forkrun default mode: **~10 000 – 12 000 batches/sec**
- forkrun `-s` mode: **> 200 000 batches/sec (UMA) / > 100 000 batches/sec (NUMA)**
- GNU Parallel (current tool): **~470 batches/sec**

(Default-mode rate implies a settled average batch of roughly 2,000–2,500 lines; `-X` mode telemetry confirms the controller saturates at Lmax = 4096.)

**Average CPU utilization across ~400 benchmarks (mix-dependent)**
- forkrun:      ~90% aggregate across 400 mixed runs (27.1 / 28 cores in steady-state default mode = 95%; 27.6/28 = 98.6% for sustained default tests; `-U` unsafe mode hits 27.1+/28; `-b 512k` on 100 MB intentionally ~2.6/28)  (no centralized dispatcher - all cores doing work when work exists)
- GNU Parallel:  6%  (2.68 / 28 cores)  (1 full core used strictly for dispatching work - 1.68 cores doing actual work)

Utilization also scales *down* correctly: `-b 512k` on a 100 MB input sustains ~2.6/28 cores because the engine declines to spawn a full worker pool for a sub-second job — the same auto-tuning that saturates 27/28 cores on billion-line streams.

**Comparison of forkrun Modes**
- **`-s` mode** is the headline: data flows memfd → kernel pipe → command stdin via `splice()`, entirely in kernel space. Bash never touches the data bytes — only the claim/dispatch coordination runs in userspace.
- **`-b` mode**: allows for distributing batches of constant byte size without needing to scan for delimiters. Performance approaching kernel limits on memory movement.
- **`-k` mode (Ordered output)**: has no measurable overhead in our benchmarks. Tests indicate that ordering adds under 2% to the runtime, whereas strict ordering brutally penalizes traditional tools.
- **`-u` mode (Realtime output)**: **WARNING: AVOID UNLESS ABSOLUTELY NECESSARY.** Yields ~0 performance gain over `--buffered` while risking severe I/O slowdowns, hopelessly scrambled output (byte-level interleaving), and duplicate lines on crash recovery. Use *only* for commands with guaranteed atomic writes where immediate terminal feedback is mandatory.
- **CPU utilization**: avg 27.1 / 28 cores (95.2%) sustained across all modes for ~400 tests. "Default" mode tests saturate on avg 27.6 / 28 cores (98.6%).
- **Born-local NUMA placement**: file ingest measures 0.0–0.2% cross-socket chunks. Under fast-draining *pipe* input, 2–13% of chunks may be stolen — by design (an idle node costs more than a remote chunk). Real multi-socket topologies raise the steal threshold with distance (`1 + distance/10`), so these figures — measured on `numa=fake=4`, where all distances are 10 — are a **worst case**. (The end-of-stream drain collapses the threshold to 1 regardless of distance; this is bounded to EOF.)
- **File vs pipe input**: zero measurable difference — the ingest pipeline handles both identically.

- **`-L` mode (Exact batch sizing)**: Guarantees exactly $N$ lines per batch. In NUMA mode (v3.5.0+), this uses the **Scanner-Handoff Chain**: scanning is serialized across node scanners via cumulative line tracking, and batches that straddle a 2 MB chunk boundary pull their initial lines across the socket. Throughput is single-scanner bound ($\approx$ UMA scan speeds), but exactness is preserved without demoting the entire pipeline.

## Key Design Properties

- **Deterministic Stream Prefixes (`-n`)**: Setting `-n N` mathematically guarantees that strictly the first $N$ records of the input stream are processed in exact linear order across all NUMA nodes, with zero spatial races, zero overshoot, and clean skip propagation for remaining chunks.

- **Contention-free**: The fast path is intentionally boring and excessively fast (two amortized atomic RMWs (`read_idx` + `total_lines_consumed`) with no locks or CAS retry loops). All algorithmic complexity is shifted to the slow path to ensure graceful degradation, meaning contention is structurally eliminated rather than reactively avoided.
- **Born-local NUMA**: Data is placed on the correct socket at ingest time via `set_mempolicy` using real-time backpressure (self load-balancing). Scanners and workers are pinned. Cross-socket traffic is a measured 0.0–0.2%. Stealing is permitted only when local work is exhausted.
- **Zero-copy data path**: `splice()`, `copy_file_range()`, and `sendfile()` move data without userspace copies. Scanner publishes byte-offsets and line counts. Workers read directly from the backing memfd.
- **Self-tuning**: Automatic worker scaling, adaptive batch sizing, and early partial flush for low-latency trickle inputs. No manual `-n` or `-j` tuning required.
- **Fault-tolerant & Self-healing**: Built-in automatic recovery for unexpectedly killed workers (e.g., OOM kills, segfaults). `forkrun` automatically traps the failure, isolates and discards corrupted partial output, safely respawns the worker, and re-dispatches the poisoned batch without deadlocking the pipeline.
- **Single-file deployment**: Ships as one bash file with an embedded loadable `.so`. Zero external dependencies beyond a handful of standard Linux utilities (e.g., sed, base64, gzip, rm, cat) — no heavy runtimes like Perl (unlike GNU Parallel) or Python, making it perfect for lightweight containerized deployments. Requires only a Linux kernel ≥ 3.17 and Bash ≥ 4.0 (Bash ≥ 5.1 recommended for array performance). Kernels ≥ 4.5 additionally enable the `copy_file_range` fast path; older kernels automatically fall back to `sendfile`/read-write with no functional difference.
- **Auditable Builds**: the embedded C extension is compiled and injected by a public GitHub Actions workflow; the git history of the base64 blob traces every byte to a specific CI run of `forkrun_ring.c`. (Reproducible builds with published checksums are on the roadmap and would upgrade this to cryptographic attestation.)

## Why It Matters for Frontier: Data Prep

forkrun targets a known inefficiency in HPC workflows: underutilized CPUs during data preparation.

Frontier's compute nodes rely on customized 64-core AMD EPYC "Trento" CPUs configured with 4 NUMA domains (NPS4). Data prep workflows that run millions of fast shell transforms hit exactly the failure mode that forkrun was designed for: **high-frequency, low-latency operations on deep NUMA topologies**. 

GNU Parallel's per-item Perl initialization overhead and NUMA-oblivious scheduling leave most cores idle on this workload shape. forkrun keeps them saturated with node-local data. On systems like Frontier, where data prep can dominate runtime, this represents a **significant opportunity for reclaiming compute capacity**.

## Current Limitations & Roadmap for Resilience

While `forkrun` features robust intra-node fault tolerance (automatically recovering from individual worker crashes and preemptions without data loss), transitioning it into a hardened, facility-wide utility requires advancing its multi-node cluster capabilities. Priorities for the development roadmap include:

- **Enhanced checkpoint portability** and cluster-level resume support (e.g., seamless Slurm integration for preempted multi-node jobs).
- **Deeper integration** with facility workload managers to dynamically expand or contract resource usage.

Executing this roadmap, hardening the codebase for Exascale production environments, and providing dedicated facility support is the primary focus for proposed collaboration and funding with ORNL.

## Next steps / Contact / Source

forkrun is open source (MIT License). Drop `frun.bash` on a Frontier login node and run `. frun.bash && frun -s : < 1B_line_file` side-by-side with your current Parallel pipeline. I’m happy to assist remotely or on-site. I live in Dandridge, TN (~1 hour away from ORNL) and am available for an on-site demo with minimal notice.

Let's work together to get Frontier spending **more time doing science** and less time "waiting for data".

### **Anthony Barone**  
BSc Geophysics (UC Berkeley) • MSc Geophysics (UT Austin — advised by Mrinal Sen)
Dandridge, TN (1 hour from ORNL) • anthonywbarone@gmail.com • (858) 735-2342
https://github.com/jkool702/forkrun • Background: Computational Geophysics & Inverse Theory
