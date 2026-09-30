# Executor + C (ctypes) Control Row (W-EXECTYPES)

Date: 2026-09-30. Branch: `NEW/REFACTOR2.12`. SHA: `8f7550a4` (tree clean
apart from untracked `epyc-rental-out/`). Harness:
`python/benchmarks/ml/bench_exectypes.py` (new, benchmark-suite only —
zero product changes). Method: median-of-3 + 1 warmup per cell, 28 workers,
exact-totals assertion. No rerun-until-green: numbers reported as measured.
**forkrun's rows were not re-run** (frozen references cited verbatim below).

## 1. Environment echo

```
THP enabled: [always] madvise never          -> always
THP shmem:   [always] within_size advise ... -> always
THP defrag:  always defer defer+madvise [madvise] never -> madvise
NUMA online: 0-3                              (fake-4 boot, same as reference)
CPU: Intel(R) Core(TM) i9-7940X CPU @ 3.10GHz (28 logical)
kernel: 7.1.10-200.numa_emu.fc44.x86_64 | python: 3.14.7 | gcc: 16
forkrun: 0.16.0 | SHA: 8f7550a4
```

THP `always` matches the reference sessions; no adjustment needed. Kernel
differs in build tag from the spotcheck echo (`7.1.13-200.fc44` vs
`7.1.10-200.numa_emu.fc44` here) — same 7.1 family, noted, not investigated.

## 2. Method (fairness rules, all asserted)

ProcessPoolExecutor over the SAME `.so` + entry point the forkrun C-plugin
rows load (fresh `gcc -O3 -march=native` builds): light `ml_process_light`,
medium `ml_process_medium_yyjson`, heavy `ml_process_heavy`. Workers `pread`
line-aligned byte ranges from the input file (fd opened once per worker,
cached); only `(offset, length)` ints + paths cross the Executor boundary
(no pickled input — asserted); output bytes return via pickle (output must
cross somehow; forkrun transports output too). ctypes `CDLL` loads
worker-side post-fork, lazily, cached — the parent never touches the `.so`
(asserted: parent handle `None` post-run; every task-running worker's pid ==
its plugin-load marker pid). The dialect-2 ctx is built by hand
(`flags_granted=0`), so the plugin takes its documented `pread(fd_in)`
fallback — the same `process()` core the forkrun rows call.

Sanity (`--sanity`, all green): task-type gate (40 tasks, ints/strs/bools
only), lazy-load gate (11 task workers, marker set == task set exactly),
parent-clean gate, totals+framing gate (40,000 segments), JSON
well-formedness gate, and **forkrun-byte-identity**: 2,812,436 output bytes
bit-identical to `forkrun.map(mode="plugin")` over the same input bytes.

Interpreter note: python 3.14 defaults to **forkserver** — workers spawn
fresh and re-import the harness module (strengthens the post-fork-load
guarantee; same default the frozen Executor-Python rows ran under).

Chunking: primary ("fine") = ~4,096-line ranges — deliberately matched to
forkrun's default batch (`get_v_def("lines") → 4096` in `forkrun_ring.c`,
verified in code, not by re-running). Secondary ("coarse") = ~100k-line
ranges. Range pre-computation (mmap scan) is setup, untimed, reported below.

## 3. Cells (all totals exact)

| Cell | Scale | Granularity | Median (trials) | Rate | Total | Setup | Peak RSS |
|---|---|---|---|---|---|---|---|
| EXECTYPES-LIGHT | 5M light (533 MB) | fine, 1221 ranges | 0.663s (0.688, 0.623, 0.663) | **7.54M/s** (804 MB/s) | 5000000/5000000 | 0.7s | 529 MB |
| EXECTYPES-LIGHT-COARSE | same | coarse, 50 ranges | 0.701s (0.670, 0.702, 0.701) | 7.13M/s | 5000000/5000000 | 0.6s | 533 MB |
| EXECTYPES-MEDIUM | 5M medium (2.35 GB) | fine, 1221 ranges | 1.563s (1.600, 1.525, 1.563) | **3.20M/s** (1502 MB/s) | 5000000/5000000 | 0.9s | 2.26 GB |
| EXECTYPES-MEDIUM-COARSE | same | coarse, 50 ranges | 2.047s (2.041, 2.082, 2.047) | 2.44M/s | 5000000/5000000 | 0.9s | 2.27 GB |
| EXECTYPES-HEAVY | 20M heavy (26.9 GB) | fine, 4883 ranges | 19.312s (19.429, 19.312, 19.281) | **1.04M/s** (1392 MB/s) | 20000000/20000000 | 7.9s | 25.7 GB |

Frozen forkrun references (cited, not re-measured): C(max) light 6.70M,
medium 2.34M (`headline_2026-09-29.csv`); C(†) light 5.38M, medium 1.91M
(same); heavy-20M C UMA 0.69M (`RELEASE_v3.6.0.md` §2) / 0.64M (spotcheck
§3, reactor/`order="index"`). Executor-Python frozen: light 1.64M, medium
797k, heavy 94k (5M scale).

Heavy RSS note: 25.7 GB parent peak is `executor.map`-iterator buffering of
completed out-of-order output blobs (heavy output ≈ 0.5–1 KB/record × 20M
records must all cross to the parent). Inherent to the design (output must
cross), included in the timed path on both sides; box has 128 GB, no swap
pressure, trials tight (±0.4%).

## 4. Decomposition (the analysis this row exists for)

| Workload | Payload dividend (Exec-C ÷ Exec-Py) | Architecture dividend (forkrun-C(max) ÷ Exec-C) |
|---|---|---|
| Light | 7.54 ÷ 1.64 = **4.6×** | 6.70 ÷ 7.54 = **0.89×** (Executor wins) |
| Medium | 3.20 ÷ 0.797 = **4.0×** | 2.34 ÷ 3.20 = **0.73×** (Executor wins) |
| Heavy | 1.04 ÷ 0.094 = **~11×** (scale-mismatched: Py row at 5M, C row at 20M — steady-state rates, read with care) | 0.69 ÷ 1.04 = **~0.66×** (Executor wins; vs 0.64 spotcheck leg 0.62×) |

Against the (†) reactor rows the architecture leg reads 0.71× / 0.60× /
~0.62× — same direction, wider (the C-orderer transit is paid only on the
forkrun side, as documented).

**Pre-registered-outcome honesty note:** the order expected Exec-C "likely
between Executor-Python and forkrun-C on light" with "a real chance it wins
the light cell". It won **all three** primary cells at matched granularity —
light by 13% over (max), medium by 37%, heavy-20M by ~50% over the closest
same-scale forkrun-C reference. No re-rolls were performed; the table ships
these numbers. The coarse-sensitivity guess also resolved opposite to the
pre-registration: fine beats coarse on both workloads (light 7.54 vs 7.13,
medium 3.20 vs 2.44) — no flip; 50 coarse tasks over 28 workers leave a
28+22 wave with tail-straggler loss, which swamps any dispatch amortization.

Reading: at 4k-line granularity with a C payload, per-unit orchestration
cost decides the race, and `executor.map`'s per-future dispatch is cheaper
than forkrun's per-batch claim/ack/framing/collection machinery. forkrun's
measured advantages stand where they were measured (zero-copy delivery
without pre-chunking, crash recovery, ordering, NUMA placement) — none of
those are exercised by this control, by design.

## 5. What this does NOT prove

- The row measures a *reasonable* Executor-ctypes configuration (two
  granularities), not an exhaustively tuned one — in either direction.
- Output transport asymmetry is real (pickle-back vs memfd/orderer) and
  favors neither side uniformly; it is part of each system's honest path.
- Heavy payload dividend mixes scales (5M vs 20M); the ~11× is indicative,
  not metrological.
- Nothing here touches forkrun's Python-UDF rows (1.39–2.11× over the i9 in
  the EPYC table) — the control decomposes only the C-plugin comparison.
- Same-boot caveat: Exec-C ran 2026-09-30; frozen rows are 2026-09-25/29.
  Thermal state is the known absolute-carrier (spotcheck §7); ratios across
  the freeze boundary carry that uncertainty. A same-boot re-measurement of
  one forkrun-C leg would tighten this and is explicitly NOT done here (rows
  frozen by order).

## 6. Table + CSV updates

- `RELEASE_v3.6.0.md` §0: new row "ProcessPoolExecutor + C (ctypes) ‡"
  adjacent to the Executor row (7.54M / 3.20M / 1.04M† Sole-source
  20M-scale heavy cell), footnote ‡ with the one-paragraph methodology, and
  a third speedup row "forkrun C(max) vs Executor+C: 0.89× · 0.73× · ~0.66×".
- `results/headline_2026-09-30.csv`: successor twin — the frozen 12
  qualifier rows verbatim + 5 `EXEC-C-*` rows (`orchestrator`/`order` blank:
  not applicable to the Executor path). Supersession line in §0.
- Full per-trial logs: `/tmp/exectypes/light_medium.log`,
  `/tmp/exectypes/heavy.log` (box-local; numbers transcribed above).
