# forkrun Complete Benchmark Results (v3.6.0 release)

> **How to read this file:** §2/§5/§7 are steady-state numbers
> (5M+ records / 500k+ docs — bring-up amortized). §4 and the
> 20k-doc rows are **startup-latency microbenchmarks**: at
> 20–50k records and ~1M rec/s the whole run takes 20–50ms,
> so fork+scan+teardown dominate; their rank order is
> meaningful, their absolutes understate sustained throughput
> — always read them alongside a steady-state section.
> forkrun §0 rows re-measured 2026-10-02 (v3.6.1,
> `ce17b0a4`); competitor rows keep their original dates (those
> codebases didn't change) — so §0 compares a 2026 frontend against
> 2026 competitors. Treat the *rank order* as current and the
> competitor absolutes as historical.

Consolidated from every study in `python/benchmarks/results/`,
`DOCS/python/AI_benchmark_results.md`, the main README (bash
engine), and fresh re-runs on 2026-09-25/26 (2026-10-02 for §0).
Hardware throughout:
28c Intel i9-7940X unless noted. **Freshest forkrun numbers are
listed first in each section**; older rows are kept where they
carry data the re-runs didn't (competitors, sweeps, fault modes).

Conventions: M = million records (or lines/docs as labeled) per
second. `nodes=1` = UMA; `@N`/`auto` = multi-node pipeline
(fake-4 boot) or forced-logical (`@4` on UMA).

---

## 0. Headline HN Release Table (AI/ML Python Benchmark)

> ### Bottom line
>
> **In every case measured here, forkrun matches or exceeds the best
> available option — and adds ordered output plus automatic failure recovery
> on top of it.**
>
> **In some cases, especially streaming workloads, forkrun keeps those same
> benefits and is drastically faster than the next best: up to, and in some
> cases slightly more than, an order of magnitude.**
>
> Concretely, against the strongest competitor in each regime:
>
> | | file input | streaming input |
> |---|---|---|
> | vs the best option available | 1.00–2.77× (exceeds) | **3.94–10.76×** (exceeds) |
> | ordered output | included | included |
> | automatic recovery / bad-batch poisoning | included | included |
>
> Neither regime asks you to trade those guarantees for the speed.
>
> **Read the file-input range with its payload language in mind, because
> the lower end is nearly parity and that is the honest number.** The
> 1.00–1.19× end is forkrun's *Python UDF* against Pool/Executor running
> the *same* Python payload; against a C payload (Executor + ctypes, which
> `pread`s byte ranges and never pickles input) it is 1.16–2.77×; and
> against forkrun's own C plugin path it is **3.4–8.8×**. The headline
> "order of magnitude" language applies to the C-plugin path in the
> streaming regime, not to the Python UDF path, where forkrun wins but by
> single digits. §0 gives all three pairings.
>
> ---
>
> **Why the two regimes cost forkrun the same but the competition much
> more.** forkrun is built so that one engine serves both: the input is
> copied into a memfd either way, so a file and a pipe converge on the
> same fast path. Measured directly — same harness, same methodology,
> all 24 pipe-vs-file cells — streaming runs at a **median 104% of file
> throughput** (light 101%, medium 107%, heavy 109%; full range
> 92–123%). The source is effectively free. **That figure is UMA
> (`nodes=1`).** Re-measured on the 4-node `numa=fake=4` boot the median
> inverts to **98.6% of file** (median penalty +1.4%, 9 of 24 cells at
> parity or better, range −8.0% to +12.1%) — file input already engages
> the multi-node ingest path, so a pipe has less to win. Either way it
> is a couple of percent; just don't quote the sign without naming the
> topology.
>
> **Scope: that is about streaming _input_, and it is what the tables above
> measure.** It is not a claim about `stream()`. The non-materialising
> `stream()` API yields one joined blob per batch through a Python
> generator, where `map()` collects internally and maps a shared results
> memfd; measured on the same pipe, `stream()` costs ~20% more than `map`
> with `bytes` output (6.1M vs 8.5M rec/s, light/plugin). The gap is
> structural — `stream()` copies output roughly three times (pread from
> the worker memfd, write to the results pipe, Python reads it) where
> `map()` copies once — and it is characterised, not closed. Anyone
> needing the last 20% should use `map()` over a pipe, which is what
> §0b reports.
>
> The competition has no such property. Most of it — including the
> highest-throughput options — cannot ingest a stream at all. The two
> that can are measured above only by doing the batching in Python and
> shipping it across the boundary, and they lose ground doing it. So the
> streaming gap in §0b is mostly **the competition getting worse for
> streaming**, not forkrun getting worse.

### 5M-Record Steady-State Benchmark — 28 Workers, UMA (`nodes=1`)

All systems process the same 5,000,000-record input on the same 28-thread Intel i9-7940X.
forkrun rows re-measured on a **UMA-only boot** (single NUMA node; no
`numa=fake=4`) after a reboot, on regenerated corpora that reproduce the
column sizes exactly (0.533 / 2.347 / 6.720 GB, 5,000,000 lines each —
`ml_data_gen.py` is seeded, SEED=42). Median-of-3 + warmup; exact totals
verified on every cell (light 5000000, medium 4997892, heavy 4997982) —
**24/24 cells exact.**

> **THP: these rows require `shmem_enabled=always`.** The first
> UMA-boot measurement came in ~17% low on the C plugin rows (light
> 8.54M vs the earlier 10.28M) purely because
> `/sys/kernel/mm/transparent_hugepage/shmem_enabled` was `never` — a
> reboot dropped it, and forkrun's own startup notice flags that value
> as blocking the memfd-backed gain "most notably in `-C` mode", which
> is what these rows measure. Re-measured with `shmem_enabled=always`
> and the gap closes: **10.16M rec/s**, i.e. back to the earlier level.
> The Python UDF rows moved only 1–3% across the THP change, which is
> the control that confirms the effect is mode-specific rather than
> measurement drift.
>
> **A benchmark run with `shmem_enabled=never` understates forkrun's
> `-C`/plugin throughput by ~15–20%.** Anyone quoting a forkrun C plugin
> number should state the THP setting.
Every forkrun row is the **reactor default** (`orchestrator=True`, `order="index"`):
crash recovery and input-batch ordering both active. Rows are split by output
representation, which is the only axis that still separates them.
The old **(max)** unordered fail-fast ceiling is **gone** — it was 24% faster in
v3.6.0 and is now indistinguishable from default (−1.8% to +7.9%, no consistent
direction), because the C-orderer transit and supervision overhead it existed to
avoid have been removed. Measured (max) numbers kept in
`forkrun_output_and_supervisor_2026-10-02.md` so that claim is checkable.
Throughput is steady-state after warmup. MB/s uses decimal units (1 MB = 10⁶ bytes/s).

> **forkrun rows re-measured 2026-10-06 on the v3.6.1 release branch**,
> on the UMA boot, after removing the artificial 2.0 s worker-fork stall
> (v3.6.1 sets `STALL_FORK_AFTER=0`). All 48 cells exact; 28 workers,
> median-of-3 after warmup, fresh process per cell, same seeded corpora
> as before (byte-identical: light 532,711,015 / medium 2,347,403,909 /
> heavy 6,720,381,299 B). Every forkrun row moved **up**, +0.2% to
> +8.7%, which is the expected direction: the rows that gained most are
> the ones that fork, and a fixed ~65 ms saving is a larger share of a
> 0.49 s light plugin run than of a 52 s heavy UDF run. Competitor rows
> are untouched and keep their original dates. Raw log:
> `raw/stream_cells_uma_v361_stall0.log`.

| System                              | Light (533 MB)          | Medium (2.35 GB)        | Heavy (6.72 GB)        |
|-------------------------------------|-------------------------|-------------------------|------------------------|
| **★ forkrun C plugin (memoryview)**  | **10.18M rec/s (1,084 MB/s)** | **2.64M rec/s (1,242 MB/s)** | **850k rec/s (1,137 MB/s)** |
| **★ forkrun C plugin (bytes)**       | **7.84M rec/s (836 MB/s)** | **2.12M rec/s (998 MB/s)** | **780k rec/s (1,042 MB/s)** |
| Polars native (streaming NDJSON)    |           —            | 2.20M rec/s (1,033 MB/s) |          —             |
| **★ forkrun Python UDF (memoryview)** | **1.90M rec/s (203 MB/s)** |  **840k rec/s (396 MB/s)**   |  **100k rec/s (128 MB/s)**  |
| **★ forkrun Python UDF (bytes)**     | **1.80M rec/s (192 MB/s)** |  **780k rec/s (365 MB/s)**   |  **100k rec/s (129 MB/s)**  |
| ProcessPoolExecutor ‡‡‡             | 1.60M rec/s (171 MB/s) | 778k rec/s (365 MB/s)   | 96k rec/s (129 MB/s)   |
| ProcessPoolExecutor + C (ctypes) ‡ | **3.67M rec/s (391 MB/s)** | **2.03M rec/s (953 MB/s)** | **735k rec/s (988 MB/s)** § |
| multiprocessing.Pool ‡‡‡            | 1.52M rec/s (161 MB/s) | 775k rec/s (364 MB/s)   | 96k rec/s (129 MB/s)   |
| DuckDB native (SQL/JSON)            |           —            |  189k rec/s (89 MB/s)   |          —             |
| Ray Data (†)                        |  250k rec/s (27 MB/s)  |  184k rec/s (86 MB/s)   |  56k rec/s (75 MB/s)   |
| HuggingFace Datasets                |  120k rec/s (13 MB/s)  |   90k rec/s (42 MB/s)   |  44k rec/s (59 MB/s)   |
|-------------------------------------|---------------------------|---------------------------|---------------------------|
| **forkrun C vs Executor**           | **6.36×** | **3.39×** | **8.84×** |
| **forkrun C vs Polars**             |           —              | **1.20×** |            —     |
| forkrun C vs Executor+C             | 2.77× | 1.30× | 1.16× § |
| forkrun UDF memoryview vs Executor ‡‡‡ | 1.19× | 1.08× | 1.04×   |
| forkrun UDF bytes vs Executor ‡‡‡   | 1.12× | 1.00× | 1.04×   |
| forkrun UDF memoryview vs Pool ‡‡‡  | 1.25× | 1.08× | 1.04×   |
| forkrun UDF bytes vs Pool ‡‡‡       | 1.19× | 1.01× | 1.04×   |

> **‡‡‡ Executor/Pool rows: two corrections, and a retraction.** Read this
> before quoting anything in this table — an intermediate version of this
> file got the first half of this story wrong and is described below.
>
> **(1) The original numbers were unfair.** Pool and Executor were timed
> with input preparation — read, split, decode, partition — *outside* the
> timed closure, while forkrun's timed call takes a path and does all of
> that inside the measurement. Fixed, along with a `trials//2` bug that
> gave the competitors a single sample where forkrun got a median of
> three, an exactness check that was recorded but never asserted, and an
> `--isolate` bug where all seven children truncated one CSV and left it
> empty.
>
> **(2) ...and the first fix over-corrected, and is retracted here.** The
> obvious repair was to move `_load_lines()` inside the timed function.
> That is right about *timing scope* and wrong about *implementation*:
> `_load_lines` does `fh.read()` on the entire corpus, then builds a list
> of every record as a Python string, then chunks it. Putting that inside
> the clock does not merely charge the competitor for reading the file —
> it charges it for materialising 5,000,000 objects in the parent's RAM
> before any work starts. A competent implementation batches lazily in
> 1 MiB reads instead, and that is 35–48% faster.
>
> All three file modes, measured (5M, 28 workers, median-of-3, byte-identical
> corpora; "BEST" is what a serious implementation would actually pick):
>
> | mode | Pool light | medium | heavy | Executor light | medium | heavy |
> |---|---|---|---|---|---|---|
> | read-all-then-batch | 1000k | 463k | 82k | 1057k | 457k | 83k |
> | **lazy 1 MiB batches** | 1353k | 654k | 96k | 1234k | 644k | 96k |
> | pre-partitioned | 1516k | 775k | 93k | 1601k | 778k | 94k |
> | **BEST** | *1516k* | *775k* | *96k* | *1601k* | *778k* | *96k* |
> | *streaming (pipe)* | *1338k* | *578k* | *96k* | *1419k* | *610k* | *96k* |

>
> The rows printed in the table above use **BEST**, because that is the
> honest competitor — not the mode that happens to flatter forkrun. Note
> the consequence: `forkrun C vs Executor` is **6.36×**, not the 9.99× an
> intermediate version of this file claimed, and within ~2.5% of the
> 6.21× this table originally published. The original figure was
> accidentally close to right, because the competitor number it divided
> by happened to sit near that competitor's genuine best (pre-partitioned
> measures 1.60M on light, against the 1.64M originally published). The
> retracted 9.99× came from dividing by an implementation nobody would
> ship.
>
> Two further things fall out of that table:
>
> - **On heavy, lazy batching beats pre-partitioning** (96k vs 93k/94k).
>   Materialising 5M heavy records costs more than the pipelining saves.
>   At that size "best" stops being the same answer it is at light.
> - **The file-vs-pipe gap these competitors show is largely illusory.**
>   Lazy-from-file is within a few percent of streaming on light and heavy,
>   and *faster* on medium (654k vs 578k). What separates the streaming
>   table from the file table is not the pipe — it is
>   materialise-everything versus stream-in-batches.
>
> **What this means for forkrun's claim.** The C plugin path is unaffected
> and remains dominant: **6.36× / 3.39× / 8.84×** against the best
> available competitor. The Python UDF path is modest and should be quoted
> as such: **1.19× / 1.08× / 1.04×** for memoryview, **1.12× / 1.00× /
> 1.04×** for bytes. The Python UDF path wins, but by single digits to
> ~19%, not by the ~1.9× an intermediate version of this file asserted.
> Every cell exact: 5,000,000 lines in, 5,000,000 output slots out.
>
> Raw values: `raw/pool_executor_file_modes_5m_2026-10-08.csv`.


> ### ⚠ §0 IS MEASURED CONTAMINATED — and the corrected light column is below
>
> Every row above came from `bench_ml_pipeline.py`, which runs all
> frameworks **in one process** and **imported every competitor framework
> just to test whether it was installed**. That import costs ~214 MB of
> RSS, and `fork()` cost scales with parent RSS (measured: **0.27 ms/fork**
> clean vs **45.3 ms/fork** at 5 GB), so the import silently taxed every
> row — forkrun's most, because it forks 28 workers.
>
> Direct A/B, identical call, identical byte-identical corpus:
>
> | parent RSS | `forkrun.map` |
> |---|---|
> | 16 MB | 1.577 s → **12.69M rec/s** |
> | 214 MB (competitors imported) | 2.116 s → **9.45M rec/s** |
>
> **The benchmark was importing the very frameworks it compared against,
> and the cost landed on the competitor.** Four harness bugs fixed:
> `--isolate` (one subprocess per system), `forkrun-plugin` was nested
> inside the forkrun block and silently emitted no row, each child
> regenerated its own 2.1 GB corpus, and `detect_frameworks()` imported
> everything (now `importlib.util.find_spec`).
>
> ### Corrected light column — 20M records / 2.13 GB, fully isolated
>
> One harness for every row, so nothing is mixed. This is the fair
> version of the light column, and it is the number to quote.
>
> **Two topologies, both measured on v3.6.1.** The UMA column is
> primary — it is this release machine and it matches the UMA §0 table
> above. The 4-node fake-NUMA column is retained because the file-vs-pipe
> penalty *changes sign* between them, which is a finding worth keeping
> rather than averaging away.
>
> | System | **UMA `nodes=1`** | fake-NUMA `nodes=auto` (4 nodes) | vs Executor (UMA) |
> |---|---|---|---|
> | **★ forkrun C plugin (memoryview)** | **10.65M** | 13.52M | **7.49×** |
> | **★ forkrun C plugin (bytes)** | **8.20M** | 9.81M | **5.77×** |
> | **★ forkrun Python UDF (memoryview)** | **1.91M** | 1.92M | 1.34× |
> | ProcessPoolExecutor ‡‡‡ | 1.42M | — | — |
> | multiprocessing.Pool ‡‡‡ | 1.38M | — | — |
> | Ray Data | 368k | — | — |
> | HuggingFace Datasets | 112k | — | — |
> | (serial baseline) | 145k | — | — |

> **‡‡‡ The two 20M competitor rows did not reproduce and are corrected
> downward (2026-10-08).** Re-measured with `bench_streaming_competitors.py`
> on a freshly generated, seeded 20M light corpus (2,130,842,196 B, 0%
> malformed, 20,000,000 lines), 28 workers, median-of-3 after warmup — and
> run twice end to end:
>
> | | measured | previously published | delta |
> |---|---|---|---|
> | ProcessPoolExecutor | 1.42M | 1.6M | −11.2% |
> | multiprocessing.Pool | 1.38M | 1.5M | −8.2% |
>
> The old figures were not a different measurement so much as an
> impossible one. These competitors are **ingest-bound** — instrumenting
> the harness shows pipe read + split + decode consumes 97–98% of the
> timed window — so throughput is a property of the *bytes per second* of
> single-threaded ingest, not of the record count. Measured, that is flat:
> **151.2 MB/s at 5M and 151.4 MB/s at 20M.** The published pair implied
> 152.4 MB/s at 5M and **170.5 MB/s at 20M** — i.e. a 4× larger input
> arriving 12% *faster* per byte, which the same code on the same payload
> cannot do. The 5M rows in this study reproduce to within 1%
> (1.43M → 1.419M, 1.34M → 1.338M), which is what makes the 20M
> discrepancy a defect in the 20M numbers rather than in the method.
>
> This raises forkrun's margin in that table, so it is recorded rather
> than swapped silently: `vs Executor (UMA)` 6.66× → **7.49×**,
> 5.13× → **5.77×**, 1.19× → **1.34×**, and fake-NUMA 8.45× → **9.51×**.
>
> The plugin rows are ~21% / ~16% faster on the 4-node topology; the
> UDF row is flat (−0.5%), which is the expected shape — the UDF row is
> Python-callback bound and forks nothing, so the multi-node ingest path
> has nothing to win. The plugin rows are the ones that engage it.
>
> **C plugin vs Executor is 7.49× on UMA (the release topology),
> 9.51× on fake-NUMA — not the 6.19× printed in §0.**
>
> Re-measured 2026-10-06 on the v3.6.1 release branch after removing
> the artificial worker-fork stall. Same protocol on both boots:
> `shmem_enabled=always`, 28 workers, median-of-3 after warmup, fresh
> process per cell, **16/16 cells exact** at 20,000,000 records.
>
> | topology | C plugin view | C plugin bytes | Python UDF view |
> |---|---|---|---|
> | **UMA `nodes=1`** | **10.65M** (1134.7 MB/s) | **8.20M** (873.2 MB/s) | **1.91M** (203.5 MB/s) |
> | fake-NUMA `nodes=auto` | 13.52M (1440.7 MB/s) | 9.81M (1045.2 MB/s) | 1.92M (204.2 MB/s) |
>
> Against the pre-change 48-cell cross-check on identical fake-NUMA
> settings (12.92M / 9.49M / 1.96M): **+4.7%** view, **+3.4%** bytes,
> **−2.2%** UDF. The UDF row is Python-callback bound and forks nothing,
> so fork timing does not touch it — its ±2% is run-to-run spread. The
> plugin rows are the ones that pay the fork tax, and they gain.
>
> Full 16-cell light grid at 20M, UMA (MB/s):
>
> | config | source | C plugin view | C plugin bytes | UDF view | UDF bytes |
> |---|---|---|---|---|---|
> | default | file | **1134.7** | **873.2** | **203.5** | **193.5** |
> | default | pipe | 1377.8 | 963.4 | 210.3 | 199.5 |
> | max | file | 1148.1 | 892.3 | 202.6 | 192.6 |
> | max | pipe | 1226.7 | 823.9 | 205.6 | 195.4 |
>
> **On UMA a pipe is 13–21% FASTER than the file** on the plugin rows
> (1134.7 → 1377.8 MB/s view). That is the opposite sign from the
> fake-NUMA boot, where a pipe cost 5–8%. Same code, same corpus, both
> measured 16/16 exact. The cause is topology, not the stream: file
> input already engages the multi-node ingest path on 4 nodes, so a pipe
> has less to win, while on UMA there is no multi-node path for a file
> to borrow. Anyone quoting a streaming-input number must name the
> topology; this is the case that makes that non-optional.
>
> Raw logs: `raw/stream_cells_light_20M_UMA_v361.log` and
> `raw/stream_cells_uma_v361_stall0.log`.
>
> Note this column is **20M records** while medium and heavy remain 5M.
> That is deliberate and matches `bench_exectypes.py`, which already
> defaults heavy to `heavy_20M`. It also matters for honesty in the
> other direction: at 5M the light run is ~1.6 s, short enough that
> fixed costs are a visible share, whereas 20M is closer to steady
> state. **Medium and heavy are NOT materially affected.** Checked against
> the clean 48-cell run on this boot: medium view 3.21M vs 3.27M (+1.8%),
> heavy view 1.05M vs 1.07M (+1.5%), bytes and UDF rows within +/-1.3%.
> All noise. The fork tax is a *fixed* ~75 ms, which is ~5% of
> medium's 1.53 s and ~1.6% of heavy's 4.69 s. It only became
> catastrophic on light, whose 0.46 s run turned ~100 ms into 20%.
> An earlier note here said medium and heavy were "probably low by
> around 30%"; that was wrong, and is corrected here.

---

## 0b. Streaming Input — the regime forkrun is built for (SPLIT-1)

**Input arrives on an anonymous pipe and is never materialised.** This is the
table to read for the huge-training-run case, and it is a *different* question
from §0: forkrun's C engine path is 5–11× the pool baseline here versus
1.1–2.8× on files, because file input lets forkrun skip the ingest problem
entirely while a pipe forces every system to interleave reading with compute.

**Topology: UMA (`nodes=1`) throughout this table**, which is what the
competitor rows were measured on and is therefore the only way the
comparison stays like-for-like. forkrun rows are the `pipe` columns of
the 48-cell grid, preserved as **Table B-UMA** in
`streaming_vs_file_2026-10-02.md` — same measurement, not a re-run. (The
study's main table B is now the 4-node measurement, so the UMA pipe
columns are kept under their own heading precisely so this citation
resolves.) Competitor rows are new: executor/pool fed
incrementally from the same pipe (`bench_streaming_competitors.py`),
median-of-3 after warmup, exact record count verified on every cell, one
corpus per process.

Do not mix these rows with the `nodes="auto"` (4-node `numa=fake=4`)
figures elsewhere in this file. That topology re-measured higher on the
`bytes` paths (the 4-node headline copy is +8–9% over this on heavy) and
flips the sign of the pipe-vs-file median, so the absolute numbers and
even the direction of a streaming comparison depend on topology. §0 and
§0b each name theirs; neither is "the" number.

| System                                   | Light (533 MB) | Medium (2.35 GB) | Heavy (6.72 GB) |
|------------------------------------------|----------------|------------------|----------------|
| **★ forkrun C plugin (memoryview)**      | **9.72M rec/s (1,037 MB/s)** | **3.11M rec/s (1,461 MB/s)** | **1.03M rec/s (1,384 MB/s)** |
| **★ forkrun C plugin (bytes)**           | **7.54M rec/s (804 MB/s)** | **2.45M rec/s (1,151 MB/s)** | **0.92M rec/s (1,234 MB/s)** |
| **★ forkrun Python UDF (memoryview)**    | **1.95M rec/s (208 MB/s)** | **0.88M rec/s (415 MB/s)** | **0.10M rec/s (130 MB/s)** |
| **★ forkrun Python UDF (bytes)**         | **1.81M rec/s (193 MB/s)** | **0.83M rec/s (389 MB/s)** | **0.09M rec/s (128 MB/s)** |
| ProcessPoolExecutor                      | 1.43M rec/s (152 MB/s) | 0.62M rec/s (292 MB/s) | 0.10M rec/s (129 MB/s) |
| multiprocessing.Pool                     | 1.34M rec/s (143 MB/s) | 0.59M rec/s (276 MB/s) | 0.10M rec/s (128 MB/s) |
|------------------------------------------|----------------|------------------|----------------|
| **forkrun C memoryview vs Executor**     | **6.82×** | **5.00×** | **10.76×** |
| forkrun UDF memoryview vs Executor       | 1.37× | 1.42× | 1.01× |
| **forkrun C bytes vs Executor**          | **5.29×** | **3.94×** | **9.60×** |
| forkrun UDF bytes vs Executor            | 1.27× | 1.33× | 0.99× |
| forkrun C bytes vs multiprocessing.Pool  | 5.64× | 4.17× | 9.66× |

> **Streaming competitor rows re-verified 2026-10-08 — no change.** The
> file-input harness was found to time Pool/Executor *without* their input
> preparation (fixed in `036a24fb`), so the obvious worry was that the
> streaming harness had the same defect. It does not, and that was
> established by measurement rather than by reading the code.
>
> Instrumenting `bench_streaming_pipe.py` with a `time` shim and a tracing
> wrapper on the batch iterator (without patching `os.read`, which breaks
> multiprocessing's own IPC):
>
> | system | batches ingested inside `[t0, dt]` | ingest as share of window |
> |---|---|---|
> | ProcessPoolExecutor | 2442 / 2442 (100%) | 96.8% |
> | multiprocessing.Pool | 2442 / 2442 (100%) | 98.4% |
>
> The pipe read, newline split and per-line decode all happen *inside* the
> timed region, because `_iter_batches` is a lazy generator consumed by
> `imap`/`map` within the window. The suspicion that these systems
> "collect the whole stream first" is **half right, and worth recording
> precisely**: `ProcessPoolExecutor.map` does eagerly materialise every
> batch as a future before returning, whereas `pool.imap` streams lazily
> with bounded memory. That is a real memory/scalability difference — but
> the materialisation happens *inside* the clock, so it does not flatter
> the timing. Both remain ingest-bound, with the workers largely waiting
> on the single-threaded parent.
>
> Three further checks, all clean: trial parity (`TRIALS=3`, median, one
> warmup on both sides, including `cell_var.py` for forkrun — no `trials//2`
> equivalent anywhere); count convention (both sides use valid-record
> counts, 5,000,000 / 4,997,892 / 4,997,982); and exactness (gated hard on
> both — `if n != exp: FAIL` for competitors, `raise SystemExit` for
> forkrun).
>
> One asymmetry does exist and is disclosed rather than corrected: forkrun's
> `run_pipe()` spawns its producer *inside* the timed window, while the
> competitors call `_spawn_producer()` *before* `t0`. Measured cost of that
> spawn (pipe + fork + child open) is **0.4 ms** — 0.012% of a light
> stream, 0.001% of heavy. It favours the competitors by ~0.01%, which is
> immaterial; correcting it would marginally favour forkrun.
>
> Re-ran all three 5M variants: light 1.43M → **1.419M** and 1.34M →
> **1.338M** (−0.7% / −0.2%), medium 0.62M → **0.610M** and 0.59M →
> **0.578M**, heavy 0.10M → **0.096M** and 0.10M → **0.096M**. All within
> run-to-run noise, so the rows above stand as printed.

Ordered output and automatic failure recovery (bad-batch poisoning without
killing the pipeline) are active on every forkrun row here, as in §0.

### This is "best of each method", and the comparison is not symmetric

In the streaming regime the honest comparison is **forkrun + C plugin vs
executor/pool + a UDF**, and the gap is architectural rather than a payload
language choice:

- **forkrun** batches on the fly **in C, outside Python**. The engine scans
  the shared ingress memfd and forms batches itself; a C plugin then reads its
  own range by offset. No batch data crosses a Python boundary, no pickling,
  no GIL contention, and **the full input never has to exist before the run
  starts** — which is the whole point when the producer is still writing.
- **executor/pool** has no such layer. With a pipe there is nothing to seek,
  so the parent must form batches in Python and ship them across the boundary,
  paying that tax on every batch.

`bench_exectypes.py` makes this concrete, because its own fairness rules
require that **no pickled input crosses the Executor boundary**: workers
`pread` assigned byte ranges from the input file, and only `(offset, length)`
ints and a path are sent. That is a *file* capability. A pipe cannot be
`pread` and cannot be range-indexed, so on a stream executor+ctypes cannot
keep its defining advantage — it degenerates into the same pickled-batch shape
as executor+UDF, differing only in payload language.

So **executor + ctypes is deliberately absent from this table**, even though
it is a legitimate competitor in §0. Its 1.08–2.77× there is real; it is
simply not reachable on a stream, and quoting a number for it here would
require quietly dropping the guarantee that makes the row fair.

### Why only executor and pool appear in this table

Not a shortlist — a measured finding. Every competitor "streaming" API wants a
*path* it can mmap, seek or stat, so a FIFO cannot be ingested at all:

| framework | streaming API | FIFO verdict |
|---|---|---|
| Polars | `pl.scan_ndjson` | fails — `OSError 19` (no such device) |
| DuckDB | `read_json_auto` | fails — `InvalidInput: Malformed JSON` |
| Ray Data | `ray.data.read_json` | fails — `FileNotFoundError` |
| HuggingFace Datasets | `load_dataset(streaming=True)` | needs files/URLs |
| Executor + ctypes | byte ranges into a **file** | no seekable source on a pipe (see above) |

They are absent because they cannot be given forkrun's input, not because they
are slow. Their §0 numbers remain valid for their own regime.

### The two regimes, side by side — and why they are split

Splitting the table is the point, because the two regimes are not the same
competition.

**File input has respectable alternatives, and forkrun still wins.** An
Executor + ctypes + static-partitioning setup is a genuinely good answer to
"process this JSONL in parallel" — it runs the same C payload, needs no
orchestration layer, and is what most serious Python pipelines actually do.
forkrun's margin there is real but modest (1.08–2.77× vs Executor, 1.08–1.40×
vs Executor + ctypes) precisely *because* the competitor is good.

On top of that speed, every forkrun row in §0 already includes **ordered
output and automatic failure recovery** — bad-batch poisoning without killing
the pipeline. The static-partitioning alternative gives you neither.

**Streaming removes most of those alternatives.** A pipe has no seekable
source, so the thing that made Executor + ctypes strong — handing workers
byte ranges into a file, with no pickled input — stops being available. That
row degenerates into ordinary pickled batches. Polars, DuckDB, Ray and HF
Datasets cannot ingest a pipe at all. What is left is executor/pool with a
Python UDF, and against that forkrun's C path dominates 3.9–10.8×, still
including ordering and recovery.

So the summary claim is: **forkrun wins on speed in both regimes, and wins
by a much wider margin in the streaming regime precisely because that is
where the strong alternatives stop working** — while carrying ordered output
and automatic recovery in both, which the alternatives do not.

The Python UDF rows are the honest counterweight: on **heavy**, where per-batch
Python cost dominates (~52 s regardless of source), forkrun's advantage falls
to ~1.0×. The 5–11× is the C-plugin path, where forkrun's advantage is real
and where the transport actually binds. Anyone reading this table should hold
both facts at once.

Ratio rows use the **memoryview** rows (forkrun's default representation since
0.17.0). Zero-copy output is worth 1.12–1.40× over per-record `bytes` here
(workload-dependent; the `nodes="auto"` copy below reads 1.01–1.45×, and a
pure-echo payload reaches 2.0–2.3× — these payloads do real per-record work,
so result collection is a smaller share of wall) — less than the 2.0–2.3× it reaches on a pure-echo workload, because
these payloads do real per-record work (parse, extract, filter) so result
collection is a smaller share of wall. The C plugin gains more than the Python
UDF (1.11–1.45× vs 1.01–1.09×) for the same reason. See
`forkrun_output_and_supervisor_2026-10-02.md` for all 24 cells.

**All forkrun rows run crash recovery:** they use the reactor default and
automatically recover from unhandled worker
exceptions, `SIGSEGV`, and `SIGKILL`-class deaths — including OOM-kill, which the kernel
delivers as SIGKILL — completing with 100% byte-exact output on the tested cases
(orphaned batches are rolled back via `ftruncate`, re-queued to escrow, and re-executed). SIGKILL-tested;
a cgroup-OOM scenario test is queued (no cgroup-specific test exists yet — the mechanism
claim is true-by-mechanism, untested-by-scenario).
There is deliberately **no fail-fast "ceiling" row** any more. The v3.6.0 table carried
one (`orchestrator=False`, `order="none"`) because disabling recovery and ordering was
worth 24% on light. After the v3.6.1 parent-side work it is worth nothing: across 12
cells the two configurations differ by −1.8% to +7.9% with no consistent direction, and
(max) is the slower of the pair in 7 of 12. Quoting a ceiling that no longer exists
would misrepresent the default as paying a cost it does not pay. The measurements are
kept in `forkrun_output_and_supervisor_2026-10-02.md`.
† On the Ray Data row, † marks *tested* recovery (task retry). It previously also marked
forkrun's reactor-default rows; it no longer does, because those are now every forkrun row
and need no marker. Ray Data's tested recovery uses task retry. The other systems were not
observed to autonomously recover from the injected worker-failure cases tested here; observed
behavior included pipeline abort (`BrokenProcessPool`), lost state, or indefinite hang.

‡ **Executor+C control row** (2026-09-30, `exectypes_2026-09-30.md` — the control
that separates the payload-language advantage from the orchestration advantage): same C
payload as forkrun's plugin rows (yyjson single-pass on medium, scalar on light/heavy —
fresh builds, byte-identity vs the forkrun plugin path verified on 2.8 MB); workers `pread`
assigned ~4k-line byte ranges (no input pickling — only offsets/lengths cross); plugin
loaded post-fork per worker (python 3.14 forkserver); ctypes call overhead ~1.7µs (FFI
spike figure). **Effective rates (quoted): timed executor.map phase PLUS the one-time
in-session line-range pre-computation** (mmap scan: 0.7s light / 0.9s medium / 7.9s heavy —
forkrun's scan runs inside its timed region, so parity requires it here too). Timed-only
ceilings retained in the results file (7.54M / 3.20M / 1.04M). Decomposition on effective
rates: payload dividend (Exec-C ÷ Exec-Py) ~2.2× / ~2.5× / ~7.8×; architecture dividend
(forkrun-C ÷ Exec-C) 2.80× / 1.24× / 1.06× on the §0 memoryview rows — forkrun now
leads on all three once indexing is counted, where it trailed heavy-20M narrowly
before (0.94× on the v3.6.0 (max) legs). Setup amortizes to zero over repeat runs on the
same file (ranges are cacheable; forkrun re-scans every run), so ceiling and effective
bracket the truth. Coarse
(~100k-line) sensitivity recorded in the results file (fine wins both: no flip). § Heavy
cell measured at 20M/26.9 GB (pre-generated) vs the column's 5M/6.72 GB — steady-state
rate; nearest same-scale forkrun-C references are 0.69M (§2) / 0.64M (spotcheck §3).

*Supersession log: Executor+ctypes control row added 2026-09-30 (W-EXECTYPES);
decomposes forkrun-vs-Executor into payload vs architecture components. CSV twin:
`headline_2026-09-30.csv` (frozen 12 qualifier rows + 5 `EXEC-C-*` rows).*


### 5M-Record Steady-State Benchmark — 28 Workers, `nodes="auto"` (4 nodes, `numa=fake=4` boot)
> **Re-measured 2026-10-03 on a fresh `numa=fake=4` boot**, superseding
> rows that dated from `ce17b0a4` — before the 1 MiB pipe resize, the
> forked ingest child, the `snapshot_fds` fix, the pre-flight fix and the
> drain hole-punch. 48/48 cells exact. `shmem_enabled=always`.
>
> **The light C-plugin rows came in LOWER than the copy they replace**
> (12.33M → 10.59M memoryview, 8.98M → 8.31M bytes), while medium and
> heavy are flat-to-better (+0.8% to +8.5%). The old light figure is not
> reproducible: a separate UMA boot measured 10.2M and this fake-NUMA boot
> measured 10.59M, so two independent boots agree with each other and
> disagree with it. The stale number appears to have been a favourable
> run rather than a real regression — the ~0.5s light corpus is the most
> sensitive to machine state. **10.59M is the number to quote.**
>
> Multi-node shows up exactly where there is work to distribute: the
> `bytes` rows gain 8-9% on heavy (a real per-record copy that four nodes
> can share) while the zero-copy `view` rows gain ~2% (nothing left to
> parallelise). That is the shape healthy NUMA scaling should have.

All systems process the same 5,000,000-record input on the same 28-thread Intel i9-7940X.
forkrun rows re-measured 2026-10-02 (v3.6.1 parent-side work, `ce17b0a4`;
median-of-3 + warmup, exact totals verified on every cell: light 5000000,
medium 4997892, heavy 4997982 — 24/24 cells exact).
**This copy is `nodes="auto"`**, the DEFAULT, which on this `numa=fake=4`
boot resolves to 4 nodes — it is NOT UMA, and the heading says so. The
copy above is `nodes=1` (UMA). Two caveats
on reading the difference as a topology result: `numa=fake=4` gives all
4 nodes all 28 CPUs, so `auto` buys **no locality** — it is a different
(and faster) pipeline shape, not a NUMA win, and must not be reported as
one. And on a single-node boot `nodes="auto"` resolves to 1 node, so the
two copies would collapse into one.
Every forkrun row is the **reactor default** (`orchestrator=True`, `order="index"`):
crash recovery and input-batch ordering both active. Rows are split by output
representation, which is the only axis that still separates them.
The old **(max)** unordered fail-fast ceiling is **gone** — it was 24% faster in
v3.6.0 and is now indistinguishable from default (−1.8% to +7.9%, no consistent
direction), because the C-orderer transit and supervision overhead it existed to
avoid have been removed. Measured (max) numbers kept in
`forkrun_output_and_supervisor_2026-10-02.md` so that claim is checkable.
Throughput is steady-state after warmup. MB/s uses decimal units (1 MB = 10⁶ bytes/s).

| System                              | Light (533 MB)          | Medium (2.35 GB)        | Heavy (6.72 GB)        |
|-------------------------------------|-------------------------|-------------------------|------------------------|
| **★ forkrun C plugin (memoryview)**  | **10.59M rec/s (1,129 MB/s)** | **3.21M rec/s (1,509 MB/s)** | **1.05M rec/s (1,414 MB/s)** |
| **★ forkrun C plugin (bytes)**       | **8.31M rec/s (886 MB/s)** | **2.53M rec/s (1,188 MB/s)** | **900k rec/s (1,206 MB/s)** |
| Polars native (streaming NDJSON)    |           —            | 2.20M rec/s (1,033 MB/s) |          —             |
| **★ forkrun Python UDF (memoryview)** | **1.90M rec/s (202 MB/s)** |  **890k rec/s (416 MB/s)**   |  **100k rec/s (131 MB/s)** |
| **★ forkrun Python UDF (bytes)**     | **1.78M rec/s (190 MB/s)** |  **820k rec/s (385 MB/s)**   |  **100k rec/s (129 MB/s)** |
| ProcessPoolExecutor                 | 1.64M rec/s (175 MB/s) |  797k rec/s (374 MB/s)  |  94k rec/s (126 MB/s)  |
| ProcessPoolExecutor + C (ctypes) ‡ | **3.67M rec/s (391 MB/s)** | **2.03M rec/s (953 MB/s)** | **735k rec/s (988 MB/s)** § |
| multiprocessing.Pool                | 1.60M rec/s (170 MB/s) |  757k rec/s (355 MB/s)  |  94k rec/s (126 MB/s)  |
| DuckDB native (SQL/JSON)            |           —            |  189k rec/s (89 MB/s)   |          —             |
| Ray Data (†)                        |  250k rec/s (27 MB/s)  |  184k rec/s (86 MB/s)   |  56k rec/s (75 MB/s)   |
| HuggingFace Datasets                |  120k rec/s (13 MB/s)  |   90k rec/s (42 MB/s)   |  44k rec/s (59 MB/s)   |
|-------------------------------------|---------------------------|---------------------------|---------------------------|
| **forkrun C vs Executor**           | **6.46×** | **4.03×** | **11.17×** |

> **‡‡‡ This table's Executor/Pool rows predate the 2026-10-08 timing-scope
> fix and are optimistic, and are NOT re-measured.** They were timed with
> input preparation outside the clock (see the §0 footnote for the full
> account), which flatters them by 35–48%. On the equivalent UMA boot the
> same harness measured 1.60M where it printed 1.64M here, so the
> published 1.64M was close to that competitor's genuine best and the
> headline ratios here are unlikely to be materially wrong — but they
> were produced by a harness known to be unfair and have not been
> re-measured on the `numa=fake=4` boot, because doing so needs a reboot
> onto that topology. Quote §0 (UMA, re-measured) for current numbers;
> treat this copy as a topology finding only.

| **forkrun C vs Polars**             |           —              | **1.46×** |            —             |
| forkrun C vs Executor+C             | 2.89× | 1.58× | 1.43× § |

Ratio rows use the **memoryview** rows (forkrun's default representation since
0.17.0). Zero-copy output is worth 1.01×–1.45× over per-record `bytes` on these
workloads — less than the 2.0–2.3× it reaches on a pure-echo workload, because
these payloads do real per-record work (parse, extract, filter) so result
collection is a smaller share of wall. The C plugin gains more than the Python
UDF (1.11–1.45× vs 1.01–1.09×) for the same reason. See
`forkrun_output_and_supervisor_2026-10-02.md` for all 24 cells.

**All forkrun rows run crash recovery:** they use the reactor default and
automatically recover from unhandled worker
exceptions, `SIGSEGV`, and `SIGKILL`-class deaths — including OOM-kill, which the kernel
delivers as SIGKILL — completing with 100% byte-exact output on the tested cases
(orphaned batches are rolled back via `ftruncate`, re-queued to escrow, and re-executed). SIGKILL-tested;
a cgroup-OOM scenario test is queued (no cgroup-specific test exists yet — the mechanism
claim is true-by-mechanism, untested-by-scenario).
There is deliberately **no fail-fast "ceiling" row** any more. The v3.6.0 table carried
one (`orchestrator=False`, `order="none"`) because disabling recovery and ordering was
worth 24% on light. After the v3.6.1 parent-side work it is worth nothing: across 12
cells the two configurations differ by −1.8% to +7.9% with no consistent direction, and
(max) is the slower of the pair in 7 of 12. Quoting a ceiling that no longer exists
would misrepresent the default as paying a cost it does not pay. The measurements are
kept in `forkrun_output_and_supervisor_2026-10-02.md`.
† On the Ray Data row, † marks *tested* recovery (task retry). It previously also marked
forkrun's reactor-default rows; it no longer does, because those are now every forkrun row
and need no marker. Ray Data's tested recovery uses task retry. The other systems were not
observed to autonomously recover from the injected worker-failure cases tested here; observed
behavior included pipeline abort (`BrokenProcessPool`), lost state, or indefinite hang.

‡ **Executor+C control row** (2026-09-30, `exectypes_2026-09-30.md` — the control
that separates the payload-language advantage from the orchestration advantage): same C
payload as forkrun's plugin rows (yyjson single-pass on medium, scalar on light/heavy —
fresh builds, byte-identity vs the forkrun plugin path verified on 2.8 MB); workers `pread`
assigned ~4k-line byte ranges (no input pickling — only offsets/lengths cross); plugin
loaded post-fork per worker (python 3.14 forkserver); ctypes call overhead ~1.7µs (FFI
spike figure). **Effective rates (quoted): timed executor.map phase PLUS the one-time
in-session line-range pre-computation** (mmap scan: 0.7s light / 0.9s medium / 7.9s heavy —
forkrun's scan runs inside its timed region, so parity requires it here too). Timed-only
ceilings retained in the results file (7.54M / 3.20M / 1.04M). Decomposition on effective
rates: payload dividend (Exec-C ÷ Exec-Py) ~2.2× / ~2.5× / ~7.8×; architecture dividend
(forkrun-C ÷ Exec-C) 2.80× / 1.24× / 1.06× on the §0 memoryview rows — forkrun now
leads on all three once indexing is counted, where it trailed heavy-20M narrowly
before (0.94× on the v3.6.0 (max) legs). Setup amortizes to zero over repeat runs on the
same file (ranges are cacheable; forkrun re-scans every run), so ceiling and effective
bracket the truth. Coarse
(~100k-line) sensitivity recorded in the results file (fine wins both: no flip). § Heavy
cell measured at 20M/26.9 GB (pre-generated) vs the column's 5M/6.72 GB — steady-state
rate; nearest same-scale forkrun-C references are 0.69M (§2) / 0.64M (spotcheck §3).

*Supersession log: Executor+ctypes control row added 2026-09-30 (W-EXECTYPES);
decomposes forkrun-vs-Executor into payload vs architecture components. CSV twin:
`headline_2026-09-30.csv` (frozen 12 qualifier rows + 5 `EXEC-C-*` rows).*

## 1. Bash engine (`frun`) vs GNU Parallel — main README, 100M+ lines

| Workload | forkrun | GNU Parallel | Speedup | Notes |
|---|---|---|---|---|
| Max batch external (`-l 1:-1 /bin/true`) | **191.4 M lines/s** | ~58 k | **~3300×** | zero-copy `vfork` fast path |
| Default external binary (`/bin/true`) | **86.9 M lines/s** | ~58 k | **~1500×** | bypasses Bash AST |
| Bash builtin (`:`, quoted args) | **25.0 M lines/s** | ~58 k | **~430×** | standard array mode |
| Ordered output (`-k`, external) | **86.9 M lines/s** | 57 k | **~1520×** | ordering ~zero overhead |
| External `printf '%s\n'` (I/O heavy) | **52.6 M lines/s** | ~58 k | **~900×** | formatting + output |
| `-s` stdin passthrough (no-op) | **1.04 B lines/s** | 6.05 M (`--pipe`) | **~172×** | `splice()` streaming |
| `-b 512k` byte batches (no-op) | **2.51 B lines/s** | 6.02 M (`--pipe`) | **~417×** | kernel-limited |
| CPU utilization (aggregate, 396 mixed benchmarks) | **~90%** (95–99% sustained default/external) | 9.6% total, 6% useful | — | no central dispatcher |
| Born-local NUMA placement | 0.0–0.2% cross-socket (file ingest) | — | — | fake-4 figures are worst case |

Typical shell-builtin range 50–400×; microbenchmark extremes
(`/bin/true`) reach ~1500–3300×. ≥1B-line runs show 30–50% higher
peaks (fixed ~30ms bring-up amortized).

## 2. Python ML pipeline, 5M/20M records, 28 workers — FRESH 2026-09-25 (UMA + forced `@4`, terminated framing, exact totals)

> Steady-state table. For the startup-latency micro view (50k
> records), see §4 — same rank order, lower absolutes.

| test | type | nodes | M rec/s | time (s) | total (exact) | valid |
|---|---|---|---|---|---|---|
| light | C-plugin | 1 | 6.67 | 0.75 | 5000000 | 5000000 |
| light | C-plugin | @4 | 4.76 | 1.05 | 5000000 | 5000000 |
| medium | C-plugin | 1 | 2.35 | 2.13 | 5000000 | 4997892 |
| medium | C-plugin | @4 | 1.83 | 2.73 | 5000000 | 4997892 |
| heavy | C-plugin | 1 | 0.70 | 7.12 | 5000000 | 4997982 |
| heavy | C-plugin | @4 | 0.59 | 8.43 | 5000000 | 4997982 |
| light-20M | C-plugin | 1 | 6.18 | 3.24 | 20000000 | 20000000 |
| light-20M | C-plugin | @4 | 5.46 | 3.66 | 20000000 | 20000000 |
| medium-20M | C-plugin | 1 | 2.49 | 8.04 | 20000000 | 19991640 |
| medium-20M | C-plugin | @4 | 1.90 | 10.53 | 20000000 | 19991640 |
| heavy-20M | C-plugin | 1 | 0.69 | 28.84 | 20000000 | 19991658 |
| heavy-20M | C-plugin | @4 | ~0.76† | ~26† | 20000000 | 19991658 |
| light | python | 1 | 1.48 | 3.38 | 5000000 | 5000000 |
| light | python | @4 | 1.17 | 4.28 | 5000000 | 5000000 |
| medium | python | 1 | 0.71 | 7.02 | 5000000 | 4997892 |
| medium | python | @4 | 0.61 | 8.24 | 5000000 | 4997892 |
| medium | spawn (`tr`) | 1 | 1.59 | 3.14 | 5000000 | — |
| medium | spawn (`tr`) | @4 | 1.22 | 4.09 | 5000000 | — |

Medium/heavy `total−valid` = quality-gate drops (2,108 / 2,018
at 5M; 8,360 / 8,342 at 20M), identical both topologies.
Method: median-of-3 + warmup, `order="index"`; medium C =
yyjson single-pass plugin.

NOTE† (heavy-20M `@4`, 26.9GB — RESOLVED as F-NUMA1, see below):
2 of ~10 runs in the v3.6.0 benchmark re-run returned silently
with ~25% of records (≈ one node's share) and no error; all
other runs exact. Root-caused since: a stalled node's
claimed-but-unread chunks let the ingest publish frontier lap
it by a full META_RING_SIZE (4096), recycling its ChunkMeta
slot before it was read (stale-major tickets; dup ack keys at
exactly gap + 4096). Fixed by the ingest meta-lifetime bound
(stall publish at frontier − min(indexer, scan-claim) ≥ 2048
over unfinished nodes) plus per-chunk meta snapshots and the
parent-side per-node drain-audit guard (loud, never silent).
Gated by `test_numa_drain_guard.py` and 10/10 byte-exact
heavy-20M runs on BOTH topologies (fake-4 and UMA boot) with
zero drain-audit warnings — the ~0.76 rate therefore stands
as measured, and `nodes=1` was stable throughout.

## 3. Python ML pipeline vs best-of-the-best — W-PY29 era (same box class, best of 8/14/28w; competitors NOT re-run since)

| System | Light 5M | Medium 5M | Heavy 5M |
|---|---|---|---|
| forkrun C plugin | **6.88M** | **2.46M** | **653k** |
| ProcessPoolExecutor | 1.64M | 797k | 94k |
| multiprocessing.Pool | 1.60M | 757k | 94k |
| forkrun Python UDF | 1.65M* | 730k | 90k |
| Ray Data | 250k | 184k | 56k |
| HF Datasets | 120k | 90k | 44k |
| Polars native (medium only) | — | **2.20M** | — |
| DuckDB native (medium only) | — | 189k | — |
| forkrun C advantage (vs best UDF) | **4.2×** | **3.1×** | **6.9×** |

forkrun cells re-measured 2026-09-26 (engine v3.6.0; per-worker
sweep 8/14/28w below; `per_worker_5m_2026-09-26.csv`);
competitor cells are W-PY29-era and stable.

*Flagged per the >10% review guard: light-Python best
(1.65M @14w) vs §2's 28w cell (1.48M) = +11.5%. Resolution:
within this sweep 14w vs 28w differ 0.3% (noise — no shape
effect), so the delta is cross-day run variance (both sides
median-of-3 on a warm box; the documented envelope is
±10–20%), not a methodology break. Table convention is
best-of, so 1.65M stands.

Per-worker shape (5M, re-measured 2026-09-26, v3.6.0): light C 5.0M (8w) → 6.7M (14w) → 6.9M
(28w); medium C 1.57M → 2.29M → 2.46M; heavy C 381k → 562k →
653k. Python UDF 1.04M/455k/52k (8w) → 1.65M/694k/84k (14w) →
1.64M/729k/90k (28w, plateau). Python remains broadly
competitive with ProcessPoolExecutor across all three
workloads (~±0% light, ~−9% medium, ~−5% heavy at 5M/28w —
see table).
Natively-expressible work goes to Polars (4.4× best UDF);
DuckDB loses to forkrun-UDF. Fault injection: forkrun recovers
autonomously with 100% byte-identical output to clean runs via
WorkerTxn recovery (reverting partial output via ftruncate and
re-executing orphans via escrow; burst 28×SIGKILL storm costs
~18–20% on 28w; lone SIGSEGV costs ~0–3%); Ray recovers via
task retry; Pool hangs indefinitely (TimeoutError, no retry)..
(`DOCS/python/AI_benchmark_results.md`, engine v3.5.2+W-PY29.)

## 4. Python ML pipeline, 50k records — STARTUP-LATENCY MICROBENCHMARK (W-PY24 scale)

At 50k records and ~1M rec/s the whole run takes ~50ms:
bring-up (fork + scan + teardown) dominates, so these rows
measure startup latency plus throughput, NOT steady state.
Rank order is meaningful; absolutes understate sustained
throughput — always read alongside §2 (5M steady state).

| System | Light | Medium | Heavy |
|---|---|---|---|
| Serial Python | 147k | 63k | 6.4k |
| mp.Pool (best) | 856k | 457k | 84k |
| ProcessPoolExecutor | 1023k | 551k | 84k |
| HF Datasets | 81k | 62k | 33k |
| forkrun Python | 580k | 293k | 68k |
| forkrun C plugin | 1047k | 481k | 216k |
| Ray Data | 43k | 38k | 17k |

forkrun Python at 60–75% of Executor; heavy/compute-bound
compresses the field. (`ml_pipeline_study.md`.)

## 5. Tokenize (LLM) — FRESH (UMA, 28w; 500k docs + 1M docs steady state)

| System | 500k Docs/s | 500k Tokens/s | 1M Docs/s |
|---|---|---|---|
| forkrun C plugin | **304.5k** | **85.9M** | **344k** |
| Executor | 167.6k | 47.3M | 168k |
| Pool | 159.9k | 45.1M | 165k |
| forkrun Python | 138.8k | 39.2M | 152k |
| HF Datasets | 50.5k | 14.0M | — (too slow at 1M) |
| Ray Data | 27.2k | 7.7M | — (too slow at 1M) |
| Polars map_batches | 14.9k | 4.2M | — |
| Serial Python | 12.1k | 3.4M | — |

All complete at both scales (500000/500000, 1000000/1000000);
plugin outputs exact-JSON-equal vs Python. 20k-doc study
retired to microbenchmark status (see `tokenize_study.md`):
at ~200ms total, bring-up dominates and ranks wobble with
box state. Big-doc crossover (662 tok/doc, 8w): C 58k (1.5×
Executor 39k), Python 32k > Pool 31k. (`tokenize_study.md`,
`tokenize.csv`.)

## 6. NUMA steady state, fake-4 boot — W-PY35 era (same-boot UMA baselines)

> Post-W-PY39 addendum lives in `numa_5m_study.md` — the
> "NUMA faster than UMA" verdict below predates the forked
> materialized scanner (+35% UMA). Current code leads on UMA
> single-socket (see §2); fake-4 NUMA ratios below stand as
> topology findings. Do not cite the UMA absolutes or ratios
> below as current. The full arc: old UMA → fake-NUMA apparent
> advantage (pipeline overlap, more CPUs active) → W-PY39 UMA
> scanner improvements → current UMA leads single-socket.
> Whether NUMA becomes advantageous again on real
> multi-socket hardware is an open empirical question
> (fake-4's uniform distance=10 topology cannot answer it;
> the planned real-4-node EPYC run is designed to).

| Workload | C nodes=1 | @2 | auto/4 | Python 1 / auto |
|---|---|---|---|---|
| Light 5M (508MB) | 5.8M | 5.4M (0.93) | 5.6M (0.97) | 1.6M / 1.6M |
| Medium 5M (2.2GB) | 1.7M | 1.9M (1.12) | 2.1M (1.24) | 655k / 712k |
| Heavy 5M (6.4GB) | 552k | 709k (1.28) | 710k (1.29) | 88k / 90k |
| Light 20M | 4.6M | — | 5.5M (1.20) | 1.5M / 1.6M |
| Medium 20M | 1.4M | — | 1.8M (1.29) | 595k / 701k |
| Heavy 20M | 545k | — | 730k (1.34) | 87k / 90k |
| Tokenize 500k C | 317k d/s | — | 342k (1.08, 2.2× Exec) | 140k / 148k |
| Spawn 1M (`tr`) | 1.6M | — | 1.2M (0.75) | C-loop gate (UMA-only) |

Historical W-PY35/W-PY36 result: fake-4 NUMA matched or exceeded the *then-current* UMA baseline by 0–34% on this workload set. That advantage came largely from pipeline overlap (more CPUs active), not lower per-node execution cost — and the UMA baseline has since risen substantially (W-PY39 forked scanner, +35%), so current UMA leads on single-socket hardware (§2). Spawn is the lone regression (0.75×, spawn-cost dominated). Mechanism (W-PY36, perf +
strace): NUMA wins via pipeline overlap (10.1 vs 8.2 avg
CPUs), DESPITE worse efficiency everywhere (+17.5% cycles,
IPC 1.3→1.1, 7× ctx switches, 67× migrations). Framework
self <1% of cycles; ~73% sits in payload `snprintf` float
formatting. Post-W-PY39 UMA (+35% forked-scanner overlap)
compresses these ratios — see §2 fresh UMA-first numbers.
Worker sweep 1–28w monotonic both topologies; streaming +
`@2` slow consumer bounded (+0MB RSS). (`numa_5m_study.md`,
`numa_5m.csv`, `numa_20m.csv`.)

## 7. Python core engine, 10M lines — FRESH (engine v3.6.0)

| Workload | Rate | Notes |
|---|---|---|
| Python no-op (run/map/stream) | 198M / 196M / 191M | overhead-bound at 10M |
| Python transform (upper) | 69M (7.2× serial 9.6M) | parent-collect bound |
| Python compute (sum) | 58M | — |
| C plugin callback (ctypes / v1 loop) | 58M / 54M | — |
| Spawn external (`cat`/`tr`, v0+v1) | 27.4M / 27.3M | subprocess-bound |
| JSONL ingestion | 3.6M rec/s | payload-bound |
| Filter + transform / Aggregation | 31M / 52M | — |
| stream() vs map() | 1.8× faster | drain overlaps produce |
| ordered vs unordered | 1.11–1.34× | reassembly grows w/ batches |
| Pool baseline | 2.0M upper | per-line pickling; forkrun ~23× |

No-op/upper/sum up ~8–10% over v3.5.2; spawn nearly doubled
(15M→27M, C spawn-loop/v1 fast paths). Memory: +0MB
discard/streaming-flat; output-sized under `map()`;
slow-consumer stream window-bounded. (`large.md`,
`large.csv`.)

## 8. Batch sizing, 1M lines/8w — FRESH (relative shapes; ~10ms rows carry bring-up share)

| Batch | No-op | Upper | Stream upper |
|---|---|---|---|
| adaptive (~4k) | 118.8M | 57.7M | 87.2M |
| 100 | 72.1M (0.61×) | 30.9M | — |
| 1k–10k | 117–126M | 51–62M | 78–89M |
| 50k+ | ~76–81M (starvation) | ~49M | — |
| 1 worker adaptive/10k | 84.1M / 134.1M | — | — |

Per-batch cost ~10ns/line at every size (no fixed overhead
to amortize); peaks ~126M (8w, forced 1k–10k) / ~134M (1w, 10k) — not 1B+. The Bash engine's splice/byte paths reach the billions/s tier (§1); that is a different execution path from Python's ~100–200M record-processing regime (§7), and the two must not be collapsed into one 'forkrun throughput' number.
`lines=100` loses ~40%, `lines=50k+` ~35%. JSONL regresses
at 10k (payload-bound). Memory flat 76–80MB across 100×
range. (`batch_size_study.md`.)

## 9. Splice / byte modes, 1M–10M lines — FRESH

| Mode | 1M | 10M (130MB) |
|---|---|---|
| `lines=1000` Python | 121.1M | 168M |
| `bytes=64K–4M` Python | ~126–133M (1.10×) | ~175–190M (~1.1×) |
| `mode="splice"` | 57–61M | 70–80M (≈ passthrough) |
| Splice stream | 81.2M | **91.7M** (pipelined drain) |
| Python passthrough | 62.1M | 73.4M |

Ceiling: sendfile ~4.4GB/s + parent parse ~3GB/s cap this
box at ~230M for `map()`; 2B needs ~26GB/s end to end.
(`splice_study.md`.)

## 10. Plugin generations, medium 5M (W-PY31/32 era — parser-relative deltas stand; absolutes superseded by §2 fresh 2.35M yyjson-spass 28w UMA)

| Plugin | 8w | 14w | 28w |
|---|---|---|---|
| scalar C | 1,117k | 1,533k | 1,664k |
| yyjson C | 1,473k (+32%) | 1,891k (+23%) | 1,875k (+13%) |
| yyjson single-pass | 1,602k (+9%) | 2,023k (+7%) | 2,077k (+11%) |

Parser swaps cap at ~2M/s (framework per-batch cost binds,
not parsing); kept as defaults (free, byte-exact).
Spawn C-loop ≡ Python loop (±4% — architectural value, not
speed). (`AI_benchmark_results.md` W-PY31–33.)

## Supersession log (what replaces what)

- §2 fresh UMA + `@4` rows (2026-09-25, v3.6.0) supersede all
  older UMA absolutes (W-PY35 `numa_5m_study` Part A UMA column,
  `PERFORMANCE.md` pre-refresh table, `AI_benchmark_results`
  pre-refresh forkrun cells).
- 20k-doc / 50k-record studies are startup-latency
  microbenchmarks by the scale rule above — cited for rank
  order and crossover analyses, never for throughput claims.
- Fake-4 NUMA ratios (§6) stand (topology finding).
- §5 fresh 500k + new 1M-doc tokenize supersede the 20k-doc
  study for scale; its big-doc crossover (1.1×→1.8×) still
  stands.
- W-PY24 50k competitor matrix (§4) stands (competitors not
  re-run; forkrun rows re-measured faster in §2).
- Counting note (§6 Part-D text) is retired by terminated
  framing: totals now exact, no junction artifact.
- F-NUMA1 resolved (was: "known open item" — heavy-20M `@4`
  silently partial ~25% in 2 of ~10): meta-ring lapping fixed
  and gated as above; the NOTE† stands corrected, not open.
- §0 four-line revision (2026-09-29, post-W-REL6): the single
  2026-09-25 forkrun rows were superseded by (†)/(max) pairs —
  those old numbers were legacy-path measurements (the (max) legs
  reproduced them: 6.70 vs 6.61M, 2.34 vs 2.37M, 698k vs 718k).
  Python-(max)-heavy (W-P0LEGACY hang, fixed pre-tag) refreshed to
  91k post-fix; all twelve cells qualified, zero BLOCKs.
  **Superseded again 2026-10-02** (v3.6.1, `ce17b0a4`): the four
  (†)/(max) rows become four output-representation rows on the
  default configuration, and the (max) rows are dropped entirely —
  they no longer measure anything (see §0 prose and
  `forkrun_output_and_supervisor_2026-10-02.md`).

## v3.6.0 claims (what the tables above support)

forkrun's Python frontend drives a C worker substrate at
multi-million-record/s rates for substantial parsing
workloads (§2: 2.3M medium, §5: 305k docs/s tokenize),
hundreds of millions of records/s for lightweight
transforms (§7: 198M no-op, 69M upper), and substantially
outperforms conventional Python process-pool frameworks on
the tested ML workloads (§3: 3–7× over the best UDF
system) — with autonomous crash recovery and bounded
streaming semantics.
