# Run Manifest — forkrun ML Headliner Refresh (UMA, v3.6.2)

## Measurement source SHA

The corrected runs were executed on a working tree based on commit
`cfb517413d2881f5907ee74decb79d5d7407155a` with the benchmark-harness
fixes (native-gating + actual-input MB/s) applied as uncommitted changes.
Those fixes are now captured in commit `b26690c26c289f0a967c46035da3e8b341ce8c61`,
which is the closest clean source revision. The uncommitted-during-run caveat
means the measurement source is best described as `cfb51741` + harness patch
(now `b26690c2`).

## Environment

- Topology: UMA, single NUMA node (node0, CPUs 0-27)
- CPU: Intel Core i9-7940X @ 3.10 GHz, 28 logical CPUs
- Kernel: 7.1.13-200.fc44.x86_64
- Python: 3.14.8
- forkrun: 0.18.0 (engine v3.6.2)
- THP shmem_enabled: [always] within_size advise never deny force
- Date: 2026-10-27

## Commands and artifacts

| Workload | Records | System | Command | CSV | Log | Input bytes | rec/s | MB/s (actual) | Exit | Count check |
|---|---|---|---|---|---|---|---|---|---|---|
| Light 20M | 20,000,000 | forkrun | `python3 python/benchmarks/ml/bench_ml_pipeline.py --records 20000000 --variants light --workers 28 --trials 3 --only-system forkrun --csv ...20m_light_corrected.csv` | ml_headline_uma_v362_20m_light_corrected.csv | .log | 2,130,842,196 | 1,808,750 | 192.7 | 0 | 20000000/20000000 |
| Light 20M | 20,000,000 | forkrun-plugin | `... --only-system forkrun-plugin ...20m_light_plugin_corrected.csv` | ml_headline_uma_v362_20m_light_plugin_corrected.csv | .log | 2,130,842,196 | 13,589,659 | 1447.9 | 0 | 20000000/20000000 |
| Medium 5M | 5,000,000 | forkrun | `... --records 5000000 --variants medium --workers 28 --trials 3 --only-system forkrun ...5m_medium_corrected.csv` | ml_headline_uma_v362_5m_medium_corrected.csv | .log | 2,347,403,909 | 815,568 | 382.9 | 0 | 4997892/5000000 |
| Medium 5M | 5,000,000 | forkrun-plugin | `... --only-system forkrun-plugin ...5m_medium_plugin_corrected.csv` | ml_headline_uma_v362_5m_medium_plugin_corrected.csv | .log | 2,347,403,909 | 3,444,909 | 1617.3 | 0 | 4997892/5000000 |
| Heavy 5M | 5,000,000 | forkrun | `... --variants heavy ...5m_heavy_corrected.csv` | ml_headline_uma_v362_5m_heavy_corrected.csv | .log | 6,720,381,299 | 93,006 | 125.0 | 0 | 4997982/5000000 |
| Heavy 5M | 5,000,000 | forkrun-plugin | `... --only-system forkrun-plugin ...5m_heavy_plugin_corrected.csv` | ml_headline_uma_v362_5m_heavy_plugin_corrected.csv | .log | 6,720,381,299 | 1,069,556 | 1437.6 | 0 | 4997982/5000000 |

Statistic: median of 3 trials after 1 warmup (harness default). Fresh process per run (no --isolate needed for single-system runs; no competitor imports). Workers: 28. THP: always.

## YYJSON result

The medium plugin run also produced `forkrun-yyjson-medium-28w`: 5,744,813 rec/s (2,623 MB/s). This corresponds to an existing comparable row in the study document but is outside the canonical headliner table (which uses the standard C plugin). Not promoted to the headline table.

## Superseded artifacts

Initial (non-isolated, combined medium+heavy) run artifacts retained as historical evidence:
- `ml_headline_uma_v362_5m.csv` / `.log` (medium+heavy in one process, with native benchmarks)
- `ml_headline_uma_v362_5m_plugin.csv` / `.log`
- `ml_headline_uma_v362_20m_light.csv` / `.log`
- `ml_headline_uma_v362_20m_light_plugin.csv` / `.log`

Authoritative corrected artifacts (isolated per variant) are the `*_corrected.csv` / `*_corrected.log` files listed above.

## Remaining release gates (unchanged)

- Full documented matrix (MAINTAINERS §5) — NOT RUN
- Benchmark suite (bash) — NOT RUN
- MAINTAINERS §5 policy conflict — UNRESOLVED
- Python 3.11 `test_batch_idx_is_not_globally_unique` — OPEN