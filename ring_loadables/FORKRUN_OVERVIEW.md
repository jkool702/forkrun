# forkrun — NUMA-Aware Contention-Free Streaming Parallelization for HPC Data Prep

## The Problem

Data preparation on multi-socket HPC systems like Frontier means running millions of fast shell operations — format conversions, field extraction, validation checks, file transforms — across inputs that range from a few records to billions of lines. GNU Parallel and `xargs -P` were designed for long-running jobs, not microsecond-scale operations on NUMA hardware. At scale, their per-item fork overhead, cross-socket data migration, and lock contention become the bottleneck — not the work itself.

## What forkrun Is

**forkrun** is an **intra-node** drop-in shell parallelizer that replaces `xargs -P` and GNU Parallel for streaming workloads on a single machine. It is incredibly easy to use—simply source the script, and it can immediately parallelize native bash functions or external commands:

```bash
. frun.bash                         # sourcing frun.bash sets up *everything* needed to use `frun`
frun my_bash_func < inputs.txt      # parallelize custom bash functions!
cat data | frun sed 's/old/new/'    # pipe-based input
frun -k sort < records.tsv          # ordered output
frun -s gzip < raw_logs             # stdin-passthrough mode
```

Under the hood, forkrun is a **contention-free, NUMA-aware parallelization engine** implemented as a set of C loadable bash builtins. It coordinates workers through shared memory and atomic operations — no locks on the fast path, no cross-socket data migration, no per-item fork overhead.

## How It Works

**The data pipeline** has four stages, each designed to preserve locality:
1. **Ingest**: Data is `splice()`'d from stdin into a shared memfd. This is **PFS-friendly**, multiplexing data entirely in kernel space without generating filesystem metadata storms (no `stat()`/`open()` cascades). On multi-socket systems, `set_mempolicy(MPOL_BIND)` places each chunk's pages on a target NUMA node *before any worker touches them*. This placement is driven by real-time backpressure from the per-node indexers, making NUMA distribution completely self-load-balancing. Data is always **born-local**.
2. **Index**: Per-node indexers (pinned to their socket) find record boundaries using AVX2/NEON SIMD scanning at memory bandwidth, then publish offset markers into a per-node lock-free ring buffer.
3. **Claim**: Workers claim batches via a single `atomic_fetch_add` — no CAS retry loops, no locks, no contention. Overshoots are handled by depositing remainders into an escrow pipe for idle workers to steal.
4. **Reclaim**: A background fallow thread punches holes behind completed work via `fallocate(PUNCH_HOLE)`, bounding memory usage without breaking the offset coordinate system.

**Adaptive tuning** is fully automatic. A three-phase controller (warmup → geometric ramp → PID steady-state) discovers the optimal batch size in O(log L) steps and continuously adjusts based on input rate, consumption rate, and worker starvation — with no user configuration required. forkrun runs efficiently whether it has 20 inputs from `ping` running on your laptop, or a billion lines from a file on a ramdisk running on a Frontier node.

## Benchmarks (28-core i9-7940x system, 100M lines)

| Workload | forkrun | GNU Parallel | Speedup |
|----------|---------|-------------|---------|
| `-s` stdin passthrough (100M lines, 1-byte avg, 100 MB) | **0.109 s** (~917M lines/s) | ~10M lines/s | **~90x** |
| `-s` stdin passthrough (100M lines, 9-byte avg, 888 MB) | **0.430 s** (~2.07 GB/s) | ~100 MB/s | **~20x** |
| `-b 512k` byte-based processing (100M lines, 1-byte avg, 100 MB) | **0.064 s** (~1.56B lines/s) | ~10M lines/s | **~150x** |
| `echo` (line args) | **4.4 s** (~22M lines/s) | ~200+ s | **~50×** |
| `printf %s\n` (I/O heavy) | **7.7 s** | ~350+ s | **~45×** |
| Ordered output (`-k echo`) | **4.4 s** | ~220+ s | **~50×** |

NOTE: These expected speedups are based onbenchmarks run on a UMA system. On Frontier's NUMA architecture, **the expected speedup is more** than what is shown in the above table.

**`-s` mode** is the headline: data flows memfd → kernel pipe → command stdin via `splice()`, entirely in kernel space. Bash never touches the data bytes — only the claim/dispatch coordination runs in userspace.
**`-b` mode**: allows for distributing batches of constant byte size without needing to scan for delimiters. Performance approaching kernel limits on memory movement.
**`-k` mode (Ordered output)**: Has virtually zero cost. As the benchmarks show, `frun -k echo` takes exactly the same time as unordered `frun echo` (`4.4 s`), whereas strict ordering brutally penalizes traditional tools.
**CPU utilization**: 27.5 / 28 cores (98.2%) sustained across all modes. Median test shows 4:1 ratio of user:sys time.
**Cross-socket traffic (NUMA, 4 nodes)**: 0.0–0.2% of chunks — born-local placement works and cross-node traffic is virtually eliminated.
**File vs pipe input**: zero measurable difference — the ingest pipeline handles both identically.

## Key Design Properties

- **Contention-free**: The fast path is intentionally boring and excessively fast (a single atomic increment with no locks or CAS retry loops). All algorithmic complexity is shifted to the slow path to ensure graceful degradation, meaning contention is structurally eliminated rather than reactively avoided.
- **Born-local NUMA**: Data is placed on the correct socket at ingest time via `set_mempolicy`. Scanners and workers are pinned. Cross-socket traffic is a measured 0.0–0.2%.
- **Zero-copy data path**: `splice()`, `copy_file_range()`, and `sendfile()` move data without userspace copies. Workers read directly from the backing memfd.
- **Self-tuning**: Automatic worker scaling, adaptive batch sizing, and early partial flush for low-latency trickle inputs. No manual `-n` or `-j` tuning required.
- **Single-file deployment**: Ships as one bash file with an embedded loadable `.so`. Zero external dependencies — no Perl (unlike GNU Parallel) and no Python, making it perfect for lightweight containerized deployments. Requires only bash ≥ 4 and a Linux kernel ≥ 3.17.

## Why It Matters for Frontier Data Prep

Frontier's compute nodes rely on a single customized 64-core AMD EPYC "Trento" CPU configured with 4 NUMA domains (NPS4). Data prep workflows that run millions of fast shell transforms hit exactly the failure mode that forkrun was designed for: **high-frequency, low-latency operations on deep NUMA topologies**. GNU Parallel's per-item Perl initialization overhead and NUMA-oblivious scheduling leave most cores idle on this workload shape. forkrun keeps them saturated with node-local data, and has the potential to drastically reduce the total time spent in data prep.

## Contact / Source

Anthony Barone
anthonywbarone@gmail.com
https://github.com/jkool702/forkrun

