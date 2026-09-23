5M RECORDS, STEADY STATE (best of 8/14/28 workers, W-PY29):

┌────────────────────────────────────────────────────────────────────┐
│  ML PIPELINE (sustained throughput, records/sec)                   │
├──────────────────────┬──────────┬──────────┬───────────────────────┤
│ System               │ Light    │ Medium   │ Heavy                 │
│                      │ (508MB)  │ (2.2GB)  │ (6.4GB)               │
├──────────────────────┼──────────┼──────────┼───────────────────────┤
│ forkrun C plugin     │ 6,490k   │ 1,622k   │ 611k                  │
│ Executor             │ 1,641k   │   797k   │  94k                  │
│ Pool                 │ 1,598k   │   757k   │  94k                  │
│ forkrun Python       │ 1,611k   │   652k   │  89k                  │
│ Ray                  │   250k   │   184k   │  56k                  │
│ HF Datasets          │   120k   │    90k   │  44k                  │
├──────────────────────┼──────────┼──────────┼───────────────────────┤
│ forkrun C advantage  │  4.0×    │  2.0×    │  6.5×                 │
└──────────────────────┴──────────┴──────────┴───────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│  TOKENIZE (500k docs, sustained)                                   │
├──────────────────────┬──────────────────────┬──────────────────────┤
│ System               │ Docs/sec             │ Tokens/sec           │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ forkrun C plugin     │ 346,055              │ 97.7M                │
│ Executor             │ 167,156              │ 47.2M                │
│ Pool                 │ 160,907              │ 45.4M                │
│ forkrun Python       │ 146,025              │ 41.2M                │
│ HF Datasets          │  51,025              │ 14.4M                │
│ Ray                  │  32,096              │  9.1M                │
│ Polars UDF           │  15,382              │  4.3M                │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ forkrun C advantage  │ 2.1×                 │ 2.1×                 │
└──────────────────────┴──────────────────────┴──────────────────────┘

FORKRUN C PLUGIN WINS ALL FOUR UDF WORKLOADS OUTRIGHT.
NO SCALING DEFECTS. NO CLIFFS. NO DIPS.

W-PY29 note: forkrun rows re-measured post-hardening (median of 3,
order=index, workers 8/14/28 on the same 28c box class; per-worker
table below). Non-forkrun rows unchanged (W-PY29 touches only the
forkrun engine/worker paths). The C-plugin gains (light +20%,
tokenize +35%) are consistent with the per-batch lseek removal on
the claim path; Python rows are within run variance (light -3%,
medium -3%, heavy identical, tokenize +9%).

Per-worker W-PY29 numbers (records/sec, 5M records):

| Mode            │ Light 8w │ Light 14w │ Light 28w │
│ forkrun Python  │   974k   │  1,591k   │  1,611k   │
│ forkrun C       │ 3,891k   │  6,299k   │  6,490k   │

| Mode            │ Med 8w │ Med 14w │ Med 28w │ Heavy 8w │ Heavy 14w │ Heavy 28w │
│ forkrun Python  │  418k  │   630k  │   652k  │   51k    │    83k    │    89k    │
│ forkrun C       │  983k  │ 1,322k  │ 1,622k  │  359k    │   516k    │   611k    |

Per-worker tokenize (500k docs, 282.2 avg tok/doc):

| Mode            │ 8w docs/s │ 14w docs/s │ 28w docs/s │ 28w tok/s │
│ forkrun Python  │   85,742  │   135,524  │   146,025  │   41.2M   │
│ forkrun C       │  212,805  │   304,696  │   346,055  │   97.7M   │
