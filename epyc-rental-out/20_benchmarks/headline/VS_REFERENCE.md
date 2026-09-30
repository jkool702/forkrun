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
| C-true-idx-light | 1 | 5,379,033 | 2,250,730 | 0.42x | EXACT |
| Py-true-idx-light | 1 | 1,564,332 | 2,335,279 | 1.49x | EXACT |
| C-false-none-light | 1 | 6,698,406 | 2,675,460 | 0.40x | EXACT |
| Py-false-none-light | 1 | 1,646,618 | 3,117,791 | 1.89x | EXACT |
| C-true-idx-medium | 1 | 1,905,259 | 646,715 | 0.34x | ok(quality-gate,-2108) |
| Py-true-idx-medium | 1 | 672,001 | 630,469 | 0.94x | ok(quality-gate,-2108) |
| C-false-none-medium | 1 | 2,335,586 | 777,642 | 0.33x | ok(quality-gate,-2108) |
| Py-false-none-medium | 1 | 719,797 | 461,880 | 0.64x | ok(quality-gate,-2108) |
| C-true-idx-heavy | 1 | 634,056 | 420,798 | 0.66x | ok(quality-gate,-2018) |
| Py-true-idx-heavy | 1 | 89,679 | 248,960 | 2.78x | ok(quality-gate,-2018) |
| C-false-none-heavy | 1 | 698,235 | 496,953 | 0.71x | ok(quality-gate,-2018) |
| Py-false-none-heavy | 1 | 90,661 | 270,995 | 2.99x | ok(quality-gate,-2018) |
| C-true-idx-light | auto | 5,379,033 | 262,525 | 0.05x | EXACT |
| Py-true-idx-light | auto | 1,564,332 | 303,675 | 0.19x | EXACT |
| C-false-none-light | auto | 6,698,406 | 293,635 | 0.04x | EXACT |
| Py-false-none-light | auto | 1,646,618 | 269,097 | 0.16x | EXACT |
| C-true-idx-medium | auto | 1,905,259 | 248,115 | 0.13x | ok(quality-gate,-2108) |
| Py-true-idx-medium | auto | 672,001 | 276,941 | 0.41x | ok(quality-gate,-2108) |
| C-false-none-medium | auto | 2,335,586 | 285,387 | 0.12x | ok(quality-gate,-2108) |
| Py-false-none-medium | auto | 719,797 | 266,311 | 0.37x | ok(quality-gate,-2108) |
| C-true-idx-heavy | auto | 634,056 | 274,848 | 0.43x | ok(quality-gate,-2018) |
| Py-true-idx-heavy | auto | 89,679 | 124,081 | 1.38x | ok(quality-gate,-2018) |
| C-false-none-heavy | auto | 698,235 | 315,950 | 0.45x | ok(quality-gate,-2018) |
| Py-false-none-heavy | auto | 90,661 | 123,835 | 1.37x | ok(quality-gate,-2018) |

Reference `valid` counts (the quality-gate split): light 5000000, medium 4997892, heavy 4997982.
Any row whose verdict is not EXACT/ok(quality-gate) is a correctness finding, not a perf result.
