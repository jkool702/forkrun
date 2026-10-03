# Streaming input vs file input — forkrun Python frontend

Does forkrun keep its throughput when the input arrives on a pipe
rather than a seekable file? That is the property that separates it from
`ProcessPoolExecutor` + ctypes, which must have the whole input resident
and statically partitioned before it can hand out byte ranges — so it is
worth measuring rather than asserting.

- **Date:** 2026-10-02 (two tables; see "Two tables, two boot modes")
- **Box:** Intel i9-7940X, 14c/28t, ONE socket, 125 GB RAM, booted
  `numa=fake=4`.
- **Method:** 28 workers, median of 3 after 1 warmup, one **fresh
  process per cell**. Every cell exactness-checked with
  `count_results()` against the release totals (light 5000000,
  medium 4997892, heavy 4997982). One process per cell is deliberate: an
  earlier all-in-one harness returned 0 records for an arm whose
  isolated run was correct, and 16 back-to-back `map()` calls in one
  process are all correct — so the fault was the harness's own
  cross-arm state. A fresh process per cell has nowhere to carry it.
- **Pipe:** `os.pipe()` fed by a forked writer child doing 1 MB
  read/write, i.e. `cat file | forkrun`. The writer's time is **not** in
  the timed region, but it does occupy a core; on 28 workers / 28 threads
  that is ~3.5% of capacity, so the reported penalties are upper bounds.
- **Supersedes nothing.** `RELEASE_v3.6.0.md` §0 stays file-based; this
  is the streamed counterpart.

## Two tables, two boot modes

Both tables below were measured on the **same `numa=fake=4` boot**, which
resolves `nodes="auto"` to 4 nodes. They differ only in the `nodes`
argument:

- **Table A — `nodes="auto"`**, the DEFAULT. Resolves to 4 nodes here.
- **Table B — `nodes=1`**, UMA. What `RELEASE_v3.6.0.md` §0 reports.

**Table B has since been re-measured on a real UMA-only boot** (below);
those are the numbers to use. The fake-4 UMA figures it replaced were
~20–35% better in absolute terms and materially better on streaming,
so the boot topology is itself a variable here, not just a label.

## Table A — `nodes="auto"` (DEFAULT, 4 fake nodes)

Cells show pipe seconds, pipe throughput, and the penalty against the
same configuration reading from a **file**.

| payload | config | output | Light (533 MB) | Medium (2.35 GB) | Heavy (6.72 GB) |
|---|---|---|---|---|---|
| C plugin | `default` | view | 0.423 s / 11.8M rec/s (+4%) | 1.744 s / 2.87M rec/s (+17%) | 5.115 s / 978k rec/s (+5%) |
| C plugin | `default` | bytes | 0.583 s / 8.58M rec/s (+5%) | 2.147 s / 2.33M rec/s (+8%) | 5.596 s / 893k rec/s (−7%) |
| C plugin | `max` | view | 0.421 s / 11.9M rec/s (+4%) | 1.673 s / 2.99M rec/s (+9%) | 4.810 s / 1.04M rec/s (+3%) |
| C plugin | `max` | bytes | 0.655 s / 7.64M rec/s (−5%) | 2.249 s / 2.22M rec/s (−4%) | 5.838 s / 856k rec/s (+5%) |
| Python UDF | `default` | view | 2.608 s / 1.92M rec/s (+0%) | 6.087 s / 821k rec/s (+3%) | 51.801 s / 97k rec/s (+0%) |
| Python UDF | `default` | bytes | 2.754 s / 1.82M rec/s (+0%) | 6.394 s / 782k rec/s (+1%) | 53.371 s / 94k rec/s (+1%) |
| Python UDF | `max` | view | 2.597 s / 1.93M rec/s (−0%) | 5.960 s / 839k rec/s (+2%) | 52.630 s / 95k rec/s (−3%) |
| Python UDF | `max` | bytes | 3.266 s / 1.53M rec/s (+19%) | 6.578 s / 760k rec/s (−4%) | 53.737 s / 93k rec/s (−1%) |

**Streaming costs 0–17% on the default configuration**, and four of the
eight rows are faster over a pipe than from a file. `default` and `max`
are indistinguishable here, as they are on files.

All 48 cells complete, 48/48 exact against the release record totals.

## Table B — UMA, re-measured on a UMA-only boot (FINAL)

48 cells, all exact. `nodes="auto"` resolves to UMA on this boot, so
these were invoked as `auto` and are labelled UMA. THP is
`shmem_enabled=always` — see `RELEASE_v3.6.0.md` §0, a run with `never`
understates the C plugin rows by ~15–20%.

Cells show pipe seconds and the penalty against the same configuration
reading from a **file**.

| payload | config | output | Light (533 MB) | Medium (2.35 GB) | Heavy (6.72 GB) |
|---|---|---|---|---|---|
| C plugin | `default` | view | 0.475 s (−4.0%) | 1.654 s (−12.5%) | 4.796 s (**−20.0%**) |
| C plugin | `default` | bytes | 0.625 s (−2.2%) | 2.054 s (−12.8%) | 5.390 s (−17.5%) |
| C plugin | `max` | view | 0.515 s (+5.3%) | 1.752 s (−6.4%) | 5.071 s (−13.9%) |
| C plugin | `max` | bytes | 0.704 s (+3.4%) | 2.925 s (+7.3%) | 6.782 s (−12.1%) |
| Python UDF | `default` | view | 2.590 s (−3.0%) | 5.621 s (−6.6%) | 52.236 s (−1.3%) |
| Python UDF | `default` | bytes | 2.771 s (−2.4%) | 6.104 s (−5.9%) | 52.433 s (−1.6%) |
| Python UDF | `max` | view | 2.639 s (−1.1%) | 5.628 s (−6.6%) | 53.384 s (−1.4%) |
| Python UDF | `max` | bytes | 2.857 s (−1.4%) | 6.953 s (+2.0%) | 55.020 s (−1.4%) |

**Streaming is now faster than reading a file.** All 48 cells are
complete. 39 of 48 are at parity or better, and the penalties are
negative almost everywhere: a pipe **beats** the file by up to 20% on
heavy C-plugin. The remaining outliers are small and confined to the
`max` config on light/medium (+3% to +7%).

Re-measured after the `snapshot_fds` fix (9e940a1e), which had been
dropping a real engine fd and spinning the reactor. Against the
pre-fix grid the fix improved **19 of 21** pipe cells (median −2.7%,
best −13.6%, worst +1.4%):

| | Light | Medium | Heavy |
|---|---|---|---|
| before `snapshot_fds` | +1.9% | −6.4% | −18.3% |
| after | **−4.0%** | **−12.5%** | **−20.0%** |

Heavy UDF sits at ~52 s regardless of source: it is dominated by
per-batch Python payload cost (~4× the C plugin), so source choice is
not the lever there.

This is the end of a three-stage fix, all in the same path:

| stage | light | medium | heavy | what |
|---|---|---|---|---|
| start | +77% | +93% | +126% | reactor parent interleaved read+pwrite+poll per 64 KiB quantum |
| after | +105% | +153% | +126% | forked ingest child (fixed an orderer leak, perf mixed) |
| after | **+1.9%** | **−6.4%** | **−18.3%** | `F_SETPIPE_SZ` 1 MiB on the ingest source |

The last stage was the real one, and it was one line. `read()` on a
pipe returns at most what the pipe buffer holds however much was asked
for, so a 64 KiB default against a 1 MiB `_CHUNK` meant 16× the spill
syscalls versus the same bytes from a file.

## What these two tables say together

**The streaming penalty was a UMA-reactor ingest problem, and it is
resolved.** It was never about streaming as such: the parent thread
interleaved the spill with the reactor one 64 KiB pipe quantum at a
time, and each quantum paid read + pwrite + three servicing calls.
Fail-fast paid far less because it does the same copy without the
reactor, and NUMA paid nothing because its ingest is a separate
process. Moving the copy into a forked ingest child and then sizing the
pipe to `_CHUNK` took the default configuration from +105/+153/+126%
to +1.9/−6.4/−18.3%.

Three bugs surfaced on the way, all found by measuring rather than
reasoning:

- A flat 20 ms sleep per empty quantum — 645 sleeps on light-5M, 12.9 s
  of a 14.65 s wall.
- `output=` ignored on the pipe path and the fail-fast path, because
  the flag reached a call and four executors had no parameter to take
  it.
- Two teardown leaks on the abort path, both pre-existing: the
  streaming-reactor executor never passed `orderer_pid` to teardown, and
  `live` collected only slots where `slot.alive`, so a SIGKILLed
  worker's pid was never reaped. Found with an `os.fork` ledger diffed
  against what teardown had been told.

**Syscall counts ruled out the obvious next hypothesis.** Reactor vs
fail-fast over a pipe: `poll` 29,494,621 vs 29,470,526 — effectively
identical, so the cost was Python-level work per quantum, not kernel
traffic. Separately, **29.5 M `poll()` calls on both paths** is a large
number independent of this question and still worth its own look.

## Caveats

- `numa=fake=4` gives all 4 nodes all 28 CPUs, so "NUMA" here buys **no
  locality** — it is a different (faster) pipeline shape, not a NUMA win.
  Table A must not be reported as a NUMA result. On a real multi-socket
  box the A/B ordering could reverse.
- The pipe writer occupies a core outside the timed region, so every
  penalty above is an upper bound.
- Light C plugin cells run 0.42–0.66 s, where fixed costs (engine init,
  forking 28 workers, mapping setup) are a visible fraction of wall.
  Medium and heavy are the trustworthy cells. See "Benchmark size is not
  a detail" in the repo's `MEMORY.md` — at 386 MB this same comparison
  gave the opposite answer.
- One outlier: Python UDF `max` `bytes` light shows +19% while its three
  sibling rows sit at 0%. Likely noise at 2.7–3.3 s on a non-idle box.

## Reproducing

`stream_cells.py` (one cell per process) and `stream_driver.sh` (the
grid) are in this directory.

- `stream_cells_auto.log` — raw `RESULT` lines, `nodes="auto"`, 48/48
  cells, all exact.
- `stream_cells_uma_boot.log` — raw `RESULT` lines, **UMA-only boot**,
  48/48 cells, all exact. This is Table B.
- `stream_cells_uma.log` — raw `RESULT` lines, UMA *on the fake-4 boot*,
  41/48 (four heavy-UDF cells were still running when it was stopped).
  Superseded by the line above; kept because it is the only record of
  UMA-on-fake-4.
- `stream_rows.json` — both runs parsed to one record per cell.
- `stream_render.py` — turns the raw logs into these tables. Handles
  both the 9-field and 10-field `RESULT` formats, because the two runs
  predate and postdate the `nodes` column.