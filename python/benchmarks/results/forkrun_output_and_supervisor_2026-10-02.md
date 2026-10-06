# forkrun output representation + supervisor cost — v3.6.1 re-measurement

Re-measurement of the `RELEASE_v3.6.0.md` §0 forkrun rows after the
v3.6.1 parent-side work (incremental collect, backlog-gated fork,
per-quantum env lookup, zero-copy result mapping).

- **Date:** 2026-10-02
- **Box:** Intel i9-7940X, 14c/28t, ONE socket, 4 logical NUMA nodes
  on CPUs 0-27, L3 19.3 MiB. 125 GB RAM.
- **Method:** 28 workers, `nodes=1` (UMA), median of 3 after 1 warmup.
  Every cell exactness-checked with `count_results()` on the measured
  output against the release table's totals (light 5000000,
  medium 4997892, heavy 4997982). **24/24 exact.**
- **Corpora:** `light_5M.jsonl` (0.53 GB) and `medium_5M.jsonl`
  (2.35 GB) as generated; `heavy_5M.jsonl` reconstructed as the first
  5,000,000 lines of `heavy_20M.jsonl` (6.72 GB) — the file backing the
  old Heavy column, confirmed byte-exact by prefix comparison of
  `heavy_1M.jsonl`.
- **Supersedes** the four forkrun rows in `RELEASE_v3.6.0.md` §0.

## Grid: 2 payloads × 2 supervisors × 2 output representations

- **default** = `orchestrator=True, order="index"` — reactor
  supervision + C orderer. Recovers from worker death.
- **max** = `orchestrator=False, order="none"` — legacy fail-fast,
  unordered, no recovery.

## Result: the (max) ceiling no longer exists

Wall seconds, and how much slower (max) is than default:

| corpus | payload | output | default | max | max delta |
|---|---|---|---|---|---|
| light | C plugin | bytes | 0.706 | 0.750 | +6.2% |
| light | C plugin | view | 0.486 | 0.492 | +1.1% |
| light | Python UDF | bytes | 2.969 | 2.950 | −0.6% |
| light | Python UDF | view | 2.728 | 2.748 | +0.7% |
| medium | C plugin | bytes | 2.700 | 2.913 | +7.9% |
| medium | C plugin | view | 1.985 | 1.976 | −0.5% |
| medium | Python UDF | bytes | 6.827 | 7.008 | +2.7% |
| medium | Python UDF | view | 6.259 | 6.147 | −1.8% |
| heavy | C plugin | bytes | 7.138 | 7.444 | +4.3% |
| heavy | C plugin | view | 6.423 | 6.349 | −1.2% |
| heavy | Python UDF | bytes | 53.887 | 54.616 | +1.4% |
| heavy | Python UDF | view | 53.317 | 53.303 | −0.0% |

The deltas span −1.8% to +7.9% with **no consistent direction**. In the
v3.6.0 table (max) was **24% faster** than (†) on light
(6.70M vs 5.38M rec/s). It is now indistinguishable from default, and
slightly slower in 7 of 12 cells.

That is the point of this wave: the C-orderer transit and supervision
overhead that the default configuration used to pay have been removed,
so ordering + crash recovery are now effectively free. The headline
table therefore carries only the **default** rows — recovery and
ordering on. These (max) numbers are kept here so the claim is
checkable rather than asserted.

Do not read the light rows as precise: they are 0.49–0.75 s, where
fixed costs (engine init, forking 28 workers, mapping setup) are a
visible fraction of wall. Medium (2–7 s) and heavy (6–54 s) are the
trustworthy cells. See "Benchmark size is not a detail" in the repo's
`MEMORY.md`.

## Result: zero-copy is worth 1.01×–1.45× on UDF-bound workloads

Speedup of `output="view"` over `output="bytes"`, default config:

| corpus | C plugin | Python UDF |
|---|---|---|
| light | 1.45× | 1.09× |
| medium | 1.36× | 1.09× |
| heavy | 1.11× | 1.01× |

Smaller than the **2.0–2.3×** measured on a pure-echo workload (see
`MEMORY.md`). Expected, and worth stating plainly: these payloads do
real per-record work (JSON parse, field extract, filter), so result
collection is a smaller share of wall than when the payload just
echoes. The gain scales with how collection-bound the workload is, and
these cells are UDF-bound. The C plugin gains more than the Python UDF
for the same reason — less competing work per record.

## Raw data

`remeasure_results.json` — one object per cell: variant, payload,
config, output, seconds, rec_per_s, mb_per_s, out_records, expect, ok.

Reproduce with `remeasure.py` in this directory (needs the ML plugins
built by `bench_ml_pipeline.build_ml_plugin`).