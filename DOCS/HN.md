TITLE: Show HN: forkrun – NUMA-aware shell parallelizer that breaks 1B lines/sec on 9-year-old consumer hardware

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

…and that's just the high-level view. The real implementation has about 20 more layers of careful systems trickery — phase-aware tail handling, dual-meter early-flush detection, signed batch-size finalization protocols, and more. The goal was to eliminate every source of overhead and contention, not just the obvious ones. On 9-year-old consumer hardware (my i9-7940x) it can break 1.5 billion lines/second in its fastest (-b) mode. In normal streaming workloads it's typically 50×–400× faster than GNU Parallel.

forkrun ships as a single bash file with an embedded, self-extracting C extension — no Perl, no Python, no install. The binary is built in public GitHub Actions so you can trace the base64 blob straight to the CI run.

- Benchmarking scripts and raw results: https://github.com/jkool702/forkrun/blob/main/BENCHMARKS
- Architecture deep-dive: https://github.com/jkool702/forkrun/blob/main/DOCS
- Repo: https://github.com/jkool702/forkrun

Trying it is literally two commands:

    . frun.bash
    frun shell_func_or_cmd <inputs

Happy to answer questions.
