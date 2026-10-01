# Python benchmark — large scale (10M lines, median of 5)

Command: `python3 python/benchmarks/run_all.py --scale large --trials 5
--csv python/benchmarks/results/large.csv`
Hardware: 28c Intel(R) Core(TM) i9-7940X CPU @ Linux 7.1.13-200.fc44.x86_64
Engine: v3.6.0. Date: 2026-09-25. Full table: `large.csv` (this file
narrates; the CSV is the record). Previous revision (engine v3.5.2,
2026-09-19) is superseded below — notably spawn ~15M→~27M (C
spawn-loop/v1 fast paths landed since) and no-op/upper +8–10%
(W-PY39 forked-scanner overlap, W-PY21-B datapath consolidation).

## Peak rates (10M lines)

| Workload | Lines/s | Scale delta vs 1M |
|---|---|---|
| Python no-op (run/map/stream) | 198M / 196M / 191M | up from ~119–133M medium (bring-up amortized) |
| Python upper / sum | 69M / 58M | up from 58M / 49M medium |
| Plugin upper (ctypes / v1 loop) | 58M / 54M | up from 43M |
| Spawn cat / tr (v0 and v1 loops) | 27.4M / 27.3M (v1: 27.5M / 27.1M) | up from 14.6M — v1 C loop at parity |
| stream vs map | 123M (~0.64x map-headline) | drain overlaps produce |
| ordered vs unordered (stream) | 87.4M (1.11x) | reassembly costs grow with batch count |
| lines=100 / 1000 / adaptive (upper) | 36M / 70M / 79M | batch-size sweep |
| Serial upper / mp.Pool | 9.6M / 2.0M* | *Pool at small scale (per-line pickling) |
| forkrun vs baselines | 8.0x serial, 23.4x Pool | Pool leg ran at large scale here (single trial) |
| JSONL / filter / aggregation | 3.6M / 31M / 52M | payload-bound, stable across scales |

## CPU utilization (attributable: self+children CPU over wall × cores)

| Workload | CPU% | Reading |
|---|---|---|
| no-op map | 15% | overhead-bound: fixed costs dominate at 10M |
| upper / sum | 8% / 24% | parent-side collect is the serial bottleneck (v0.5) |
| spawn cat | 26% | subprocess latency, not CPU |
| plugin | 13% | ctypes dispatch, overhead-bound |
| stream | 11% | drain loop, overhead-bound |
| JSONL | 27% | highest: json.loads burns CPU per record |

Interpretation (not a disclaimer dodge): at 10M lines the v0.5 pipeline
is still bring-up/overhead-bound — 2442 batches finish in ~0.15s, so
fork/scan/parse fixed costs dominate wall time and machine utilization
reads low. Steady-state compute saturation needs larger streams (the
bash notes say the same about 100M vs 1B). The v1 streaming path moves
collection off the critical path; re-measure there.

## Memory

- RSS flat (no output, 1→8MB stream): **+0MB** — both scales.
- RSS output-sized (map, 1→4MB): **+0MB** at MB granularity.
- Slow-consumer stream (fixed 50MB output): 39–61MB typical across
  repeat runs, **175MB max observed once** (large-suite run). Same
  workload, same binary. Variance is under investigation (leading
  hypothesis: glibc arena retention of transient drain buffers;
  `MALLOC_ARENA_MAX=4` trends lower). Reported as a range, not a point:
  bounded by the in-flight window in all observations, never by stream
  size — but the spread means the peak number is not yet fully
  characterized. Do not quote a single value.
- In-process Peak RSS rows in the table (174MB→1227MB) are cumulative
  artifacts of one long harness process, not per-benchmark evidence;
  the subprocess-isolated legs above are the clean numbers.

## Fault inversion (reminder)

10%-failure runs score *higher* lines/s than healthy (87M vs 81M):
poisoned batches skip payload work while the metric counts input
lines. Read as "no collapse under faults," never as "faults are
faster." 100% poison completes at 188M (nearly no payload work at all).
