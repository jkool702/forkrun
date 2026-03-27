Hi HN,

Have you ever fired up GNU Parallel on a big machine only to watch it crawl along while barely using more than 2–3 cores? I got tired of that, so I built forkrun.

forkrun is a self-tuning, drop-in replacement for GNU Parallel (and xargs -P) that is specifically designed for high-frequency, low-latency shell workloads on modern and NUMA hardware.

On my 28-core i9-7940x it achieves:
- 200,000+ batch dispatches/sec (vs ~500 for GNU Parallel)
- 95–99% CPU utilization across all cores (vs ~6% for GNU Parallel)
- 0.0–0.2% cross-socket memory traffic (NUMA-aware "born-local" design)

A few of the tricks that make this possible:
- Born-local NUMA: stdin is splice()'d into a shared memfd, then pages are pinned to the correct socket via set_mempolicy(MPOL_BIND) *before* any worker touches them.
- SIMD scanning: per-node indexers use AVX2/NEON to find line boundaries at memory bandwidth and publish offsets into a per-node lock-free ring.
- Lock-free claiming: workers claim batches with a single atomic_fetch_add — no locks, no CAS loops, no contention.
- Memory management: a background thread uses fallocate(PUNCH_HOLE) to reclaim space without breaking the logical offset system.

On 9-year-old consumer hardware it can break 1 billion lines/second in its fastest (-b) mode. In normal streaming workloads it's typically 50×–400× faster than GNU Parallel.

forkrun ships as a single bash file with an embedded, self-extracting C extension — no Perl, no Python, no install. The binary is built in public GitHub Actions so you can trace the base64 blob straight to the CI run.

Trying it is literally two commands:

```bash
. frun.bash
frun shell_func_or_cmd <inputs
```
