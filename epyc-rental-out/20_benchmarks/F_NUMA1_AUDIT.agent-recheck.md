# F-NUMA1 audit — real 2-node topology (AGENT RECHECK 2026-09-30T08:2xZ)

Produced by the UNMODIFIED epyc/validate_cells.py, invoked the way the fixed 41_bench_numa5m.sh now invokes it. The stage's own audit invocation died on an argparse error and never examined a single cell; see AGENT_FINDINGS.md Finding 6. This file does NOT overwrite the stage's artefact.

Topology: 2 nodes, NPS1 (one per socket), SLIT 0|10 32;1|32 10;, cross-socket distance 32 -> steal threshold 4.
META_RING_SIZE=4096 -> 2048/2 = 1024 chunks/node (fake-4 baselines had 512, so this is a LOOSER configuration than where F-NUMA1 was found).

VERDICT: 0 cells lost records across 45 rows.

**rows examined: 45** | **cells with real loss: 0** | cells with no cardinality (unvalidated): 1  **(treated as FAILURE)**

## numa5m_part_a.csv  (38 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| numa-c-light-1-96w | 5,000,000 | 5,000,000 | 5,000,000 | 4,277,328 | EXACT |
| numa-c-light-@2-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,627,138 | EXACT |
| numa-c-light-@4-96w | 5,000,000 | 5,000,000 | 5,000,000 | 4,565,969 | EXACT |
| numa-c-light-auto-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,620,720 | EXACT |
| numa-py-light-1-96w | 5,000,000 | 5,000,000 | 5,000,000 | 2,861,204 | EXACT |
| numa-py-light-auto-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,346,734 | EXACT |
| numa-yyjson-medium-1-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,444,221 | ok(gate,-2108) |
| numa-yyjson-medium-@2-96w | 5,000,000 | 4,997,892 | 4,997,892 | 916,619 | ok(gate,-2108) |
| numa-yyjson-medium-@4-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,447,982 | ok(gate,-2108) |
| numa-yyjson-medium-auto-96w | 5,000,000 | 4,997,892 | 4,997,892 | 956,120 | ok(gate,-2108) |
| numa-py-medium-1-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,080,936 | ok(gate,-2108) |
| numa-py-medium-auto-96w | 5,000,000 | 4,997,892 | 4,997,892 | 642,991 | ok(gate,-2108) |
| numa-c-heavy-1-96w | 5,000,000 | 4,997,982 | 4,997,982 | 796,546 | ok(gate,-2018) |
| numa-c-heavy-@2-96w | 5,000,000 | 4,997,982 | 4,997,982 | 655,517 | ok(gate,-2018) |
| numa-c-heavy-@4-96w | 5,000,000 | 4,997,982 | 4,997,982 | 693,442 | ok(gate,-2018) |
| numa-c-heavy-auto-96w | 5,000,000 | 4,997,982 | 4,997,982 | 574,547 | ok(gate,-2018) |
| numa-py-heavy-1-96w | 5,000,000 | 4,997,982 | 4,997,982 | 267,027 | ok(gate,-2018) |
| numa-py-heavy-auto-96w | 5,000,000 | 4,997,982 | 4,997,982 | 176,826 | ok(gate,-2018) |
| sweep-yyjson-med-1-8w | 1,000,000 | 999,626 | 1,000,000 | 846,939 | ok(gate,-374) |
| sweep-py-med-1-8w | 1,000,000 | 999,626 | 1,000,000 | 369,333 | ok(gate,-374) |
| sweep-yyjson-med-1-16w | 1,000,000 | 999,626 | 1,000,000 | 919,254 | ok(gate,-374) |
| sweep-py-med-1-16w | 1,000,000 | 999,626 | 1,000,000 | 517,461 | ok(gate,-374) |
| sweep-yyjson-med-1-32w | 1,000,000 | 999,626 | 1,000,000 | 574,123 | ok(gate,-374) |
| sweep-py-med-1-32w | 1,000,000 | 999,626 | 1,000,000 | 631,458 | ok(gate,-374) |
| sweep-yyjson-med-1-48w | 1,000,000 | 999,626 | 1,000,000 | 418,301 | ok(gate,-374) |
| sweep-py-med-1-48w | 1,000,000 | 999,626 | 1,000,000 | 468,403 | ok(gate,-374) |
| sweep-yyjson-med-1-96w | 1,000,000 | 999,626 | 1,000,000 | 222,849 | ok(gate,-374) |
| sweep-py-med-1-96w | 1,000,000 | 999,626 | 1,000,000 | 243,294 | ok(gate,-374) |
| sweep-yyjson-med-auto-8w | 1,000,000 | 999,626 | 1,000,000 | 319,978 | ok(gate,-374) |
| sweep-py-med-auto-8w | 1,000,000 | 999,626 | 1,000,000 | 175,874 | ok(gate,-374) |
| sweep-yyjson-med-auto-16w | 1,000,000 | 999,626 | 1,000,000 | 313,002 | ok(gate,-374) |
| sweep-py-med-auto-16w | 1,000,000 | 999,626 | 1,000,000 | 209,913 | ok(gate,-374) |
| sweep-yyjson-med-auto-32w | 1,000,000 | 999,626 | 1,000,000 | 271,593 | ok(gate,-374) |
| sweep-py-med-auto-32w | 1,000,000 | 999,626 | 1,000,000 | 223,183 | ok(gate,-374) |
| sweep-yyjson-med-auto-48w | 1,000,000 | 999,626 | 1,000,000 | 224,743 | ok(gate,-374) |
| sweep-py-med-auto-48w | 1,000,000 | 999,626 | 1,000,000 | 219,362 | ok(gate,-374) |
| sweep-yyjson-med-auto-96w | 1,000,000 | 999,626 | 1,000,000 | 155,056 | ok(gate,-374) |
| sweep-py-med-auto-96w | 1,000,000 | 999,626 | 1,000,000 | 156,834 | ok(gate,-374) |

## numa5m_part_c_heavy.csv  (2 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| executor-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 302,216 | ok(gate,-2018) |
| pool-heavy-96w | 5,000,000 | 4,997,982 | 4,997,982 | 301,013 | ok(gate,-2018) |

## numa5m_part_c_light.csv  (2 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| executor-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,627,731 | EXACT |
| pool-light-96w | 5,000,000 | 5,000,000 | 5,000,000 | 1,432,546 | EXACT |

## numa5m_part_c_medium.csv  (2 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| executor-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 1,143,897 | ok(gate,-2108) |
| pool-medium-96w | 5,000,000 | 4,997,892 | 4,997,892 | 967,614 | ok(gate,-2108) |

## numa5m_part_d.csv  (1 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| stream-numa-mem | ? | ? | ? | 0 | **UNVALIDATED (no count reported)** |

No cell lost records, but **1 cell(s) reported no input/output cardinality** and therefore could not be checked for conservation:
> - `numa5m_part_d.csv` / `stream-numa-mem (no count reported)`

Their throughput numbers are UNVALIDATED: nothing rules out a silent
> record loss in them. Run the cell again in a mode that reports counts.
