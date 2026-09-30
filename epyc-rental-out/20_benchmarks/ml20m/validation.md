# 43 — ML pipeline @ 20000000 records, forkrun only, 2 NUMA nodes

Topology as measured:
  nodes online `0-1` (2 nodes, shape NPS1)
  node->socket: 0:0 1:1
  SLIT matrix: `0|10 32;1|32 10;`
  intra-socket distance 32 (steal threshold 4) | cross-socket 32 (threshold 4)

Expected valid counts at 20000000 records (RELEASE_v3.6.0.md §2, exact on both UMA and @4 at 4 nodes):
light 20000000 | medium 19991640 | heavy 19991658.

F-NUMA1 is the risk: a stalled node's ChunkMeta slot recycled by a meta-ring lap
makes a run return ~25% of its records with no error. It was found at 4 nodes on
heavy-20M. This box has 2 nodes, so the meta-lifetime bound is
1024 chunks/node vs 512 there — the tightest configuration the
engine has ever run under. Cells reporting no cardinality are failures
(`--require-counts`): an uncheckable rate is an invalid experiment.

**rows examined: 49** | **cells with real loss: 0** | cells with no cardinality (unvalidated): 0  **(treated as FAILURE)**

## ml20m_light.csv  (21 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| serial-light | 20,000,000 | 20,000,000 | 20,000,000 | 133,458 | EXACT |
| pool-light-8w | 20,000,000 | 20,000,000 | 20,000,000 | 835,372 | EXACT |
| executor-light-8w | 20,000,000 | 20,000,000 | 20,000,000 | 840,826 | EXACT |
| forkrun-light-8w | 20,000,000 | 20,000,000 | 20,000,000 | 824,659 | EXACT |
| forkrun-plugin-light-8w | 20,000,000 | 20,000,000 | 20,000,000 | 2,261,409 | EXACT |
| pool-light-16w | 20,000,000 | 20,000,000 | 20,000,000 | 1,491,085 | EXACT |
| executor-light-16w | 20,000,000 | 20,000,000 | 20,000,000 | 1,495,528 | EXACT |
| forkrun-light-16w | 20,000,000 | 20,000,000 | 20,000,000 | 1,355,149 | EXACT |
| forkrun-plugin-light-16w | 20,000,000 | 20,000,000 | 20,000,000 | 2,799,146 | EXACT |
| pool-light-32w | 20,000,000 | 20,000,000 | 20,000,000 | 2,077,116 | EXACT |
| executor-light-32w | 20,000,000 | 20,000,000 | 20,000,000 | 2,147,912 | EXACT |
| forkrun-light-32w | 20,000,000 | 20,000,000 | 20,000,000 | 1,888,177 | EXACT |
| forkrun-plugin-light-32w | 20,000,000 | 20,000,000 | 20,000,000 | 3,013,546 | EXACT |
| pool-light-48w | 20,000,000 | 20,000,000 | 20,000,000 | 2,124,567 | EXACT |
| executor-light-48w | 20,000,000 | 20,000,000 | 20,000,000 | 2,166,157 | EXACT |
| forkrun-light-48w | 20,000,000 | 20,000,000 | 20,000,000 | 1,996,803 | EXACT |
| forkrun-plugin-light-48w | 20,000,000 | 20,000,000 | 20,000,000 | 2,950,928 | EXACT |
| pool-light-96w | 20,000,000 | 20,000,000 | 20,000,000 | 2,224,735 | EXACT |
| executor-light-96w | 20,000,000 | 20,000,000 | 20,000,000 | 2,472,054 | EXACT |
| forkrun-light-96w | 20,000,000 | 20,000,000 | 20,000,000 | 1,643,871 | EXACT |
| forkrun-plugin-light-96w | 20,000,000 | 20,000,000 | 20,000,000 | 2,613,929 | EXACT |

## ml20m_medium.csv  (28 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| serial-medium | 20,000,000 | 19,991,640 | 19,991,568 | 62,807 | ok(gate,-8360) |
| pool-medium-8w | 20,000,000 | 19,991,640 | 19,991,568 | 392,904 | ok(gate,-8360) |
| executor-medium-8w | 20,000,000 | 19,991,640 | 19,991,568 | 399,954 | ok(gate,-8360) |
| forkrun-medium-8w | 20,000,000 | 19,991,640 | 19,991,568 | 384,398 | ok(gate,-8360) |
| forkrun-plugin-medium-8w | 20,000,000 | 19,991,640 | 19,991,568 | 796,358 | ok(gate,-8360) |
| forkrun-yyjson-medium-8w | 20,000,000 | 19,991,640 | 19,991,568 | 1,033,192 | ok(gate,-8360) |
| pool-medium-16w | 20,000,000 | 19,991,640 | 19,991,568 | 698,102 | ok(gate,-8360) |
| executor-medium-16w | 20,000,000 | 19,991,640 | 19,991,568 | 715,018 | ok(gate,-8360) |
| forkrun-medium-16w | 20,000,000 | 19,991,640 | 19,991,568 | 464,053 | ok(gate,-8360) |
| forkrun-plugin-medium-16w | 20,000,000 | 19,991,640 | 19,991,568 | 844,600 | ok(gate,-8360) |
| forkrun-yyjson-medium-16w | 20,000,000 | 19,991,640 | 19,991,568 | 1,072,190 | ok(gate,-8360) |
| pool-medium-32w | 20,000,000 | 19,991,640 | 19,991,568 | 783,319 | ok(gate,-8360) |
| executor-medium-32w | 20,000,000 | 19,991,640 | 19,991,568 | 832,768 | ok(gate,-8360) |
| forkrun-medium-32w | 20,000,000 | 19,991,640 | 19,991,568 | 589,670 | ok(gate,-8360) |
| forkrun-plugin-medium-32w | 20,000,000 | 19,991,640 | 19,991,568 | 913,897 | ok(gate,-8360) |
| forkrun-yyjson-medium-32w | 20,000,000 | 19,991,640 | 19,991,568 | 995,397 | ok(gate,-8360) |
| pool-medium-48w | 20,000,000 | 19,991,640 | 19,991,568 | 738,387 | ok(gate,-8360) |
| executor-medium-48w | 20,000,000 | 19,991,640 | 19,991,568 | 776,604 | ok(gate,-8360) |
| forkrun-medium-48w | 20,000,000 | 19,991,640 | 19,991,568 | 601,236 | ok(gate,-8360) |
| forkrun-plugin-medium-48w | 20,000,000 | 19,991,640 | 19,991,568 | 856,186 | ok(gate,-8360) |
| forkrun-yyjson-medium-48w | 20,000,000 | 19,991,640 | 19,991,568 | 854,908 | ok(gate,-8360) |
| pool-medium-96w | 20,000,000 | 19,991,640 | 19,991,568 | 997,257 | ok(gate,-8360) |
| executor-medium-96w | 20,000,000 | 19,991,640 | 19,991,568 | 1,022,117 | ok(gate,-8360) |
| forkrun-medium-96w | 20,000,000 | 19,991,640 | 19,991,568 | 485,940 | ok(gate,-8360) |
| forkrun-plugin-medium-96w | 20,000,000 | 19,991,640 | 19,991,568 | 638,450 | ok(gate,-8360) |
| forkrun-yyjson-medium-96w | 20,000,000 | 19,991,640 | 19,991,568 | 583,030 | ok(gate,-8360) |
| polars-native | 20,000,000 | 19,991,640 | 20,000,000 | 3,333,774 | ok(gate,-8360) |
| duckdb-native | 20,000,000 | 19,991,640 | 20,000,000 | 430,938 | ok(gate,-8360) |

All cells with reported counts returned within the documented
quality-gate drop. No silent loss detected.
