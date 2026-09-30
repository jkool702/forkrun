# 42 — tokenize @ 2000000 docs, 8 systems

Every system should complete the full corpus. The recorded 2M
spot-check (spotcheck_post_wrel6.md) had plugin 2000000/2000000 and executor
2000000/2000000, with plugin output exact-JSON-equal to the Python UDF.
Tokenize has no quality gate, so the expected count equals the corpus size.

**rows examined: 27** | **cells with real loss: 0** | cells with no cardinality (unvalidated): 0

## tokenize_2000000.csv  (27 rows)

| cell | total | valid | expected | rate | verdict |
|---|---:|---:|---:|---:|---|
| tok-serial | 2,000,000 | 2,000,000 | 2,000,000 | 12,642 | EXACT |
| tok-pool-8w | 2,000,000 | 2,000,000 | 2,000,000 | 79,765 | EXACT |
| tok-executor-8w | 2,000,000 | 2,000,000 | 2,000,000 | 80,363 | EXACT |
| tok-hf-8w | 2,000,000 | 2,000,000 | 2,000,000 | 36,283 | EXACT |
| tok-forkrun-8w | 2,000,000 | 2,000,000 | 2,000,000 | 41,460 | EXACT |
| tok-plugin-8w | 2,000,000 | 2,000,000 | 2,000,000 | 83,100 | EXACT |
| tok-pool-16w | 2,000,000 | 2,000,000 | 2,000,000 | 142,776 | EXACT |
| tok-executor-16w | 2,000,000 | 2,000,000 | 2,000,000 | 140,394 | EXACT |
| tok-hf-16w | 2,000,000 | 2,000,000 | 2,000,000 | 37,166 | EXACT |
| tok-forkrun-16w | 2,000,000 | 2,000,000 | 2,000,000 | 61,174 | EXACT |
| tok-plugin-16w | 2,000,000 | 2,000,000 | 2,000,000 | 98,613 | EXACT |
| tok-pool-32w | 2,000,000 | 2,000,000 | 2,000,000 | 221,133 | EXACT |
| tok-executor-32w | 2,000,000 | 2,000,000 | 2,000,000 | 279,570 | EXACT |
| tok-hf-32w | 2,000,000 | 2,000,000 | 2,000,000 | 34,659 | EXACT |
| tok-forkrun-32w | 2,000,000 | 2,000,000 | 2,000,000 | 69,903 | EXACT |
| tok-plugin-32w | 2,000,000 | 2,000,000 | 2,000,000 | 89,253 | EXACT |
| tok-pool-48w | 2,000,000 | 2,000,000 | 2,000,000 | 240,533 | EXACT |
| tok-executor-48w | 2,000,000 | 2,000,000 | 2,000,000 | 297,142 | EXACT |
| tok-hf-48w | 2,000,000 | 2,000,000 | 2,000,000 | 35,352 | EXACT |
| tok-forkrun-48w | 2,000,000 | 2,000,000 | 2,000,000 | 78,745 | EXACT |
| tok-plugin-48w | 2,000,000 | 2,000,000 | 2,000,000 | 93,738 | EXACT |
| tok-pool-96w | 2,000,000 | 2,000,000 | 2,000,000 | 271,914 | EXACT |
| tok-executor-96w | 2,000,000 | 2,000,000 | 2,000,000 | 357,869 | EXACT |
| tok-hf-96w | 2,000,000 | 2,000,000 | 2,000,000 | 22,732 | EXACT |
| tok-forkrun-96w | 2,000,000 | 2,000,000 | 2,000,000 | 37,784 | EXACT |
| tok-plugin-96w | 2,000,000 | 2,000,000 | 2,000,000 | 36,304 | EXACT |
| tok-polars | 2,000,000 | 2,000,000 | 2,000,000 | 14,275 | EXACT |

All cells with reported counts returned within the documented
quality-gate drop. No silent loss detected.
