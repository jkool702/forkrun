TITLE: Show HN: forkrun – NUMA-aware shell parallelizer (50×–400× faster than GNU Parallel)

Hi HN,

Have you ever run GNU Parallel on a many-core machine and seen one core pegged while the rest sit mostly idle?

I hit that wall...so I built forkrun.

forkrun is a self-tuning, drop-in replacement for GNU Parallel (and xargs -P) that is specifically designed for high-frequency, low-latency shell workloads on modern and NUMA hardware (e.g., log processing, text transforms, data prep pipelines).

On my 28-core i9-7940x it achieves:
- 200,000+ batch dispatches/sec (vs ~500 for GNU Parallel)
- ~95–99% CPU utilization across all cores (vs ~6% for GNU Parallel)
- Typically 50×–400× faster on real workloads

These benchmarks are intentionally worst-case (near-zero work per task), where dispatch overhead dominates. This is exactly the regime where GNU Parallel and similar tools struggle — and where forkrun is designed to perform.

A few of the techniques that make this possible:
- Born-local NUMA: stdin is splice()'d into a shared memfd, then pages are placed on the target socket via set_mempolicy(MPOL_BIND) before any worker touches them
- SIMD scanning: per-node indexers use AVX2/NEON to find line boundaries at memory bandwidth and publish offsets into per-node lock-free rings
- Lock-free claiming: workers claim batches with a single atomic_fetch_add — no locks, no CAS retry loops; contention is reduced to a single atomic on one cache line
- Memory management: a background thread uses fallocate(PUNCH_HOLE) to reclaim space without breaking the logical offset system

…and that’s just the surface. The implementation uses many additional systems-level techniques (phase-aware tail handling, adaptive batching, early-flush detection, etc.) to eliminate overhead at every stage.

In its fastest (-b) mode (fixed-size batches, minimal processing), it can exceed 1B lines/sec. In typical streaming workloads it's 50×–400× faster than GNU Parallel.

forkrun ships as a single bash file with an embedded, self-extracting C extension — no Perl, no Python, no install, full native support for parallelizing arbitrary shell functions. The binary is built in public GitHub Actions so you can trace it back to CI (see the GitHub "Blame" on the line containing the base64 embeddings).

- Benchmarking scripts and raw results: https://github.com/jkool702/forkrun/blob/main/BENCHMARKS
- Architecture deep-dive: https://github.com/jkool702/forkrun/blob/main/DOCS
- Repo: https://github.com/jkool702/forkrun

Trying it is literally two commands:

    . frun.bash    # OR  `. <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash)`
    frun shell_func_or_cmd < inputs

Happy to answer questions.
