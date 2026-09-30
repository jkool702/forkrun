
## Cross-check: the 10x byte-exactness gate from FAKE4_REVERIFY.md §5

```bash
# heavy-5000000, the workload F-NUMA1 was originally found on
FORKRUN_DIAG_NUMA1=1 python3 - <<'PY'
import forkrun, os
p = os.path.join("//numa5", "ml_heavy_5000000.jsonl")
out = forkrun.map(lambda b: b, p, workers=96, order="index",
                  nodes="auto", mode="splice")
print("blobs:", len(out))
PY
```

The FAKE4_REVERIFY.md §5 protocol is 10 consecutive trials of exactly this cell
on both topologies, checking that orderer recv == emitted, heap_left == 0, and
that zero drain-audit warnings appear. If the audit above flagged anything, run
this ten times and report the divergence.
