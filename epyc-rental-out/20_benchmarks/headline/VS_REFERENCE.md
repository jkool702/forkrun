# headline grid vs python/benchmarks/results/headline_2026-09-29.csv

Reference: 28c Intel i9-7940X, **UMA (1 node)**, 28 workers, median-of-3+warmup,
bench_ml_pipeline.py harness, engine v3.6.0. Every published number in
RELEASE_v3.6.0.md derives from that box.

This run: 48 physical cores / 96 threads, **2 NUMA nodes**,
96 workers, AMD EPYC 7443 24-Core Processor, python 3.14.4, gcc 15.

> **The percentages below are NOT a regression measurement.** Eight axes
> differ at once: socket count, NUMA node count, SLIT distance structure
> (uniform 10 there; 32 intra-socket / 32 cross-socket here),
> physical cores (14 -> 48), logical CPUs (28 -> 96),
> worker count (28 -> 96), userland (Fedora 7.1 kernel / glibc 2.43 /
> python 3.14 vs Ubuntu 26.04), and SMT behaviour. Read them as
> *what this hardware does*, then compare against your own re-run of the
> reference config on this box (`EPYC_WORKERS_MAX=28`, nodes=1).

| cell | nodes | ref rec/s (28w UMA) | this rec/s | ratio | verdict |
|---|---:|---:|---:|---:|---|
| C-true-idx-light | 1 | 5,379,033 | 2,106,054 | 0.39x | EXACT |
| Py-true-idx-light | 1 | 1,564,332 | 2,377,911 | 1.52x | EXACT |
| C-false-none-light | 1 | 6,698,406 | 2,307,216 | 0.34x | EXACT |
| Py-false-none-light | 1 | 1,646,618 | 2,867,389 | 1.74x | EXACT |
| C-true-idx-medium | 1 | 1,905,259 | 676,273 | 0.35x | ok(quality-gate,-2108) |
| Py-true-idx-medium | 1 | 672,001 | 677,840 | 1.01x | ok(quality-gate,-2108) |
| C-false-none-medium | 1 | 2,335,586 | 728,874 | 0.31x | ok(quality-gate,-2108) |
| Py-false-none-medium | 1 | 719,797 | 844,573 | 1.17x | ok(quality-gate,-2108) |
| C-true-idx-heavy | 1 | 634,056 | 393,118 | 0.62x | ok(quality-gate,-2018) |
| Py-true-idx-heavy | 1 | 89,679 | 247,552 | 2.76x | ok(quality-gate,-2018) |
| C-false-none-heavy | 1 | 698,235 | 495,506 | 0.71x | ok(quality-gate,-2018) |
| Py-false-none-heavy | 1 | 90,661 | 277,322 | 3.06x | ok(quality-gate,-2018) |
| C-true-idx-light | @4 | 5,379,033 | 474,793 | 0.09x | EXACT |
| Py-true-idx-light | @4 | 1,564,332 | 506,150 | 0.32x | EXACT |
| C-false-none-light | @4 | 6,698,406 | 434,867 | 0.06x | EXACT |
| Py-false-none-light | @4 | 1,646,618 | 520,053 | 0.32x | EXACT |
| C-true-idx-medium | @4 | 1,905,259 | 464,042 | 0.24x | ok(quality-gate,-2108) |
| Py-true-idx-medium | @4 | 672,001 | 460,722 | 0.69x | ok(quality-gate,-2108) |
| C-false-none-medium | @4 | 2,335,586 | 509,846 | 0.22x | ok(quality-gate,-2108) |
| Py-false-none-medium | @4 | 719,797 | 548,339 | 0.76x | ok(quality-gate,-2108) |
| C-true-idx-heavy | @4 | 634,056 | 464,736 | 0.73x | ok(quality-gate,-2018) |
| Py-true-idx-heavy | @4 | 89,679 | 203,033 | 2.26x | ok(quality-gate,-2018) |
| C-false-none-heavy | @4 | 698,235 | 496,909 | 0.71x | ok(quality-gate,-2018) |
| Py-false-none-heavy | @4 | 90,661 | 208,211 | 2.30x | ok(quality-gate,-2018) |
| C-true-idx-light | auto | 5,379,033 | 349,504 | 0.06x | EXACT |
| Py-true-idx-light | auto | 1,564,332 | 350,289 | 0.22x | EXACT |
| C-false-none-light | auto | 6,698,406 | 318,955 | 0.05x | EXACT |
| Py-false-none-light | auto | 1,646,618 | 342,506 | 0.21x | EXACT |
| C-true-idx-medium | auto | 1,905,259 | 307,099 | 0.16x | ok(quality-gate,-2108) |
| Py-true-idx-medium | auto | 672,001 | 339,301 | 0.50x | ok(quality-gate,-2108) |
| C-false-none-medium | auto | 2,335,586 | 349,735 | 0.15x | ok(quality-gate,-2108) |
| Py-false-none-medium | auto | 719,797 | 361,439 | 0.50x | ok(quality-gate,-2108) |
| C-true-idx-heavy | auto | 634,056 | 320,779 | 0.51x | ok(quality-gate,-2018) |
| Py-true-idx-heavy | auto | 89,679 | 125,983 | 1.40x | ok(quality-gate,-2018) |
| C-false-none-heavy | auto | 698,235 | 364,732 | 0.52x | ok(quality-gate,-2018) |
| Py-false-none-heavy | auto | 90,661 | 130,136 | 1.44x | ok(quality-gate,-2018) |

Reference `valid` counts (the quality-gate split): light 5000000, medium 4997892, heavy 4997982.
Any row whose verdict is not EXACT/ok(quality-gate) is a correctness finding, not a perf result.
