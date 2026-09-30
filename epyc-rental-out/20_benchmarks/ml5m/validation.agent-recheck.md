# 40 ML pipeline @ 5000000 records (AGENT RECHECK 2026-09-30T08:2xZ)

Produced by the UNMODIFIED epyc/validate_cells.py, invoked the way the fixed 40_bench_ml5m.sh now invokes it. The stage's own invocation died on an argparse error; see AGENT_FINDINGS.md Finding 6.

NOTE on the two flagged cells: both are in ml5m_fault.csv, which is the medium corpus regenerated with malformed_pct=5.0. DROP_FRACTION has no entry for the fault corpus, so the validator expects 5,000,000 valid and flags the ~4.6% that the payload legitimately dropped as malformed input. This matches the injected 5% malformed rate and is NOT silent loss.

**rows examined: 89** | **cells with real loss: 2** | cells with no cardinality (unvalidated): 2

## ml5m_fault.csv  (4 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| forkrun-fault-96w | 5,000,000 | 4,771,285 | 5,000,000 | 0 | **LOSS(4.6%)** |
| pool-fault-96w | ? | ? | ? | 0 | (no count reported) |
| ray-fault-96w | ? | ? | ? | 0 | (no count reported) |
| plugin-fault-96w | 5,000,000 | 4,771,285 | 5,000,000 | 0 | **LOSS(4.6%)** |

## ml5m_heavy.csv  (26 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| serial-heavy | 5,000,000 | 4,997,982 | 4,997,982 | 7,179 | ok(gate,-2018) |
| pool-heavy-8w | 5,000,000 | 4,997,982 | 4,997,982 | 53,358 | ok(gate,-2018) |
| executor-heavy-8w | 5,000,000 | 4,997,982 | 4,997,982 | 53,342 | ok(gate,-2018) |
| hf-datasets-heavy-8w | 5,000,000 | 4,997,982 | 4,997,982 | 29,427 | ok(gate,-2018) |
| forkrun-heavy-8w | 5,000,000 | 4,997,982 | 4,997,982 | 27,243 | ok(gate,-2018) |
| forkrun-plugin-heavy-8w | 5,000,000 | 4,997,982 | 4,997,982 | 153,245 | ok(gate,-2018) |
| pool-heavy-16w | 5,000,000 | 4,997,982 | 4,997,982 | 102,702 | ok(gate,-2018) |
| executor-heavy-16w | 5,000,000 | 4,997,982 | 4,997,982 | 102,284 | ok(gate,-2018) |
| hf-datasets-heavy-16w | 5,000,000 | 4,997,982 | 4,997,982 | 36,915 | ok(gate,-2018) |
| forkrun-heavy-16w | 5,000,000 | 4,997,982 | 4,997,982 | 50,737 | ok(gate,-2018) |
| forkrun-plugin-heavy-16w | 5,000,000 | 4,997,982 | 4,997,982 | 223,150 | ok(gate,-2018) |
| pool-heavy-32w | 5,000,000 | 4,997,982 | 4,997,982 | 184,154 | ok(gate,-2018) |
| executor-heavy-32w | 5,000,000 | 4,997,982 | 4,997,982 | 182,713 | ok(gate,-2018) |
| hf-datasets-heavy-32w | 5,000,000 | 4,997,982 | 4,997,982 | 43,628 | ok(gate,-2018) |
| forkrun-heavy-32w | 5,000,000 | 4,997,982 | 4,997,982 | 83,789 | ok(gate,-2018) |
| forkrun-plugin-heavy-32w | 5,000,000 | 4,997,982 | 4,997,982 | 228,568 | ok(gate,-2018) |
| pool-heavy-48w | 5,000,000 | 4,997,982 | 4,997,982 | 224,388 | ok(gate,-2018) |
| executor-heavy-48w | 5,000,000 | 4,997,982 | 4,997,982 | 209,116 | ok(gate,-2018) |
| hf-datasets-heavy-48w | 5,000,000 | 4,997,982 | 4,997,982 | 41,437 | ok(gate,-2018) |
| forkrun-heavy-48w | 5,000,000 | 4,997,982 | 4,997,982 | 99,587 | ok(gate,-2018) |
| forkrun-plugin-heavy-48w | 5,000,000 | 4,997,982 | 4,997,982 | 206,620 | ok(gate,-2018) |
| pool-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 298,275 | ok(gate,-2018) |
| executor-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 302,638 | ok(gate,-2018) |
| hf-datasets-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 32,936 | ok(gate,-2018) |
| forkrun-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 86,040 | ok(gate,-2018) |
| forkrun-plugin-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 112,007 | ok(gate,-2018) |

## ml5m_light.csv  (26 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| serial-light | 5,000,000 | 5,000,000 | 5,000,000 | 134,604 | EXACT |
| pool-light-8w | 5,000,000 | 5,000,000 | 5,000,000 | 871,234 | EXACT |
| executor-light-8w | 5,000,000 | 5,000,000 | 5,000,000 | 865,520 | EXACT |
| hf-datasets-light-8w | 5,000,000 | 5,000,000 | 5,000,000 | 96,759 | EXACT |
| forkrun-light-8w | 5,000,000 | 5,000,000 | 5,000,000 | 427,729 | EXACT |
| forkrun-plugin-light-8w | 5,000,000 | 5,000,000 | 5,000,000 | 1,126,168 | EXACT |
| pool-light-16w | 5,000,000 | 5,000,000 | 5,000,000 | 1,453,437 | EXACT |
| executor-light-16w | 5,000,000 | 5,000,000 | 5,000,000 | 1,522,956 | EXACT |
| hf-datasets-light-16w | 5,000,000 | 5,000,000 | 5,000,000 | 103,546 | EXACT |
| forkrun-light-16w | 5,000,000 | 5,000,000 | 5,000,000 | 665,075 | EXACT |
| forkrun-plugin-light-16w | 5,000,000 | 5,000,000 | 5,000,000 | 1,287,577 | EXACT |
| pool-light-32w | 5,000,000 | 5,000,000 | 5,000,000 | 1,839,515 | EXACT |
| executor-light-32w | 5,000,000 | 5,000,000 | 5,000,000 | 2,049,357 | EXACT |
| hf-datasets-light-32w | 5,000,000 | 5,000,000 | 5,000,000 | 105,487 | EXACT |
| forkrun-light-32w | 5,000,000 | 5,000,000 | 5,000,000 | 820,906 | EXACT |
| forkrun-plugin-light-32w | 5,000,000 | 5,000,000 | 5,000,000 | 1,177,857 | EXACT |
| pool-light-48w | 5,000,000 | 5,000,000 | 5,000,000 | 1,752,707 | EXACT |
| executor-light-48w | 5,000,000 | 5,000,000 | 5,000,000 | 2,278,994 | EXACT |
| hf-datasets-light-48w | 5,000,000 | 5,000,000 | 5,000,000 | 85,842 | EXACT |
| forkrun-light-48w | 5,000,000 | 5,000,000 | 5,000,000 | 814,111 | EXACT |
| forkrun-plugin-light-48w | 5,000,000 | 5,000,000 | 5,000,000 | 975,916 | EXACT |
| pool-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,984,173 | EXACT |
| executor-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 2,475,833 | EXACT |
| hf-datasets-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 96,149 | EXACT |
| forkrun-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 635,822 | EXACT |
| forkrun-plugin-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 644,197 | EXACT |

## ml5m_medium.csv  (33 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| serial-medium | 5,000,000 | 4,997,892 | 4,997,892 | 63,851 | ok(gate,-2108) |
| pool-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 397,152 | ok(gate,-2108) |
| executor-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 402,305 | ok(gate,-2108) |
| hf-datasets-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 69,766 | ok(gate,-2108) |
| forkrun-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 211,754 | ok(gate,-2108) |
| forkrun-plugin-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 446,227 | ok(gate,-2108) |
| forkrun-yyjson-medium-8w | 5,000,000 | 4,997,892 | 4,997,892 | 591,897 | ok(gate,-2108) |
| pool-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 666,144 | ok(gate,-2108) |
| executor-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 584,376 | ok(gate,-2108) |
| hf-datasets-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 76,935 | ok(gate,-2108) |
| forkrun-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 328,828 | ok(gate,-2108) |
| forkrun-plugin-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 568,023 | ok(gate,-2108) |
| forkrun-yyjson-medium-16w | 5,000,000 | 4,997,892 | 4,997,892 | 671,635 | ok(gate,-2108) |
| pool-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 711,011 | ok(gate,-2108) |
| executor-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 993,233 | ok(gate,-2108) |
| hf-datasets-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 79,874 | ok(gate,-2108) |
| forkrun-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 418,757 | ok(gate,-2108) |
| forkrun-plugin-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 591,133 | ok(gate,-2108) |
| forkrun-yyjson-medium-32w | 5,000,000 | 4,997,892 | 4,997,892 | 648,785 | ok(gate,-2108) |
| pool-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 1,000,329 | ok(gate,-2108) |
| executor-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 989,220 | ok(gate,-2108) |
| hf-datasets-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 75,919 | ok(gate,-2108) |
| forkrun-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 432,968 | ok(gate,-2108) |
| forkrun-plugin-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 529,800 | ok(gate,-2108) |
| forkrun-yyjson-medium-48w | 5,000,000 | 4,997,892 | 4,997,892 | 529,050 | ok(gate,-2108) |
| pool-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,093,875 | ok(gate,-2108) |
| executor-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,199,491 | ok(gate,-2108) |
| hf-datasets-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 68,655 | ok(gate,-2108) |
| forkrun-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 344,082 | ok(gate,-2108) |
| forkrun-plugin-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 330,713 | ok(gate,-2108) |
| forkrun-yyjson-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 324,622 | ok(gate,-2108) |
| polars-native | 5,000,000 | 4,997,892 | 5,000,000 | 3,904,436 | ok(gate,-2108) |
| duckdb-native | 5,000,000 | 4,997,892 | 5,000,000 | 397,027 | ok(gate,-2108) |

> ## Do not trust the throughput numbers in this run
> At least one cell returned fewer records than it consumed. That is the
> F-NUMA1 signature (a stalled node's ChunkMeta slot recycled by a meta-ring
> lap), not a slow run. Re-run the affected cell in isolation before quoting
> any rate, and report it upstream — this is a product finding.
> - `ml5m_fault.csv` / `forkrun-fault-96w`: LOSS(4.6%)
> - `ml5m_fault.csv` / `plugin-fault-96w`: LOSS(4.6%)
