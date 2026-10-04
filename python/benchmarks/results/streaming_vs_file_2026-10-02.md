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
| C plugin | `default` | view | 0.488 s (+3.4%) | 1.641 s (+5.5%) | 4.841 s (+1.9%) |
| C plugin | `default` | bytes | 0.622 s (+3.4%) | 2.060 s (+4.3%) | 5.516 s (−1.0%) |
| C plugin | `max` | view | 0.481 s (+3.8%) | 1.611 s (+5.0%) | 4.835 s (+2.2%) |
| C plugin | `max` | bytes | 0.681 s (+12.1%) | 2.087 s (−0.6%) | 5.584 s (+2.9%) |
| Python UDF | `default` | view | 2.689 s (+2.0%) | 5.788 s (+2.6%) | 50.000 s (−2.9%) |
| Python UDF | `default` | bytes | 2.811 s (+0.2%) | 6.050 s (−0.7%) | 51.423 s (−1.1%) |
| Python UDF | `max` | view | 2.687 s (−0.8%) | 5.689 s (+1.0%) | 51.526 s (+0.4%) |
| Python UDF | `max` | bytes | 2.817 s (−7.2%) | 6.168 s (−8.0%) | 51.645 s (−1.2%) |

**Streaming costs 0–17% on the default configuration**, and four of the
eight rows are faster over a pipe than from a file. `default` and `max`
are indistinguishable here, as they are on files.

All 48 cells complete, 48/48 exact against the release record totals.

## Table B-UMA — the pipe columns quoted by §0b of the release table

Preserved deliberately. §0b (`RELEASE_v3.6.0.md`) quotes forkrun's
streaming rows from the **UMA** pipe columns, because its competitor rows
(executor/pool) were measured on UMA and that is the only like-for-like
pairing. Table B below is now the 4-node `numa=fake=4` measurement, so
without this table §0b's citation would not resolve to its own figures.

Measured 2026-10-03 on a UMA-only boot, `shmem_enabled=always`, 48/48
cells exact. Median **−3.6%** vs file (20 of 24 cells at parity or
better) — the opposite sign to the 4-node Table B, for the reason
recorded there.

| payload | config | output | Light (533 MB) | Medium (2.35 GB) | Heavy (6.72 GB) |
|---|---|---|---|---|---|
| C plugin | `default` | view | 0.514 s (−4.0%) | 1.606 s (−15.0%) | 4.856 s (−18.6%) |
| C plugin | `default` | bytes | 0.663 s (−2.2%) | 2.039 s (−12.5%) | 5.444 s (−17.5%) |
| C plugin | `max` | view | 0.515 s (+5.3%) | 1.781 s (−6.4%) | 5.071 s (−13.9%) |
| C plugin | `max` | bytes | 0.704 s (+3.4%) | 2.969 s (+7.3%) | 6.638 s (−12.1%) |
| Python UDF | `default` | view | 2.560 s (−3.6%) | 5.659 s (−7.7%) | 51.704 s (−3.0%) |
| Python UDF | `default` | bytes | 2.758 s (−1.4%) | 6.041 s (−7.2%) | 52.701 s (−2.3%) |
| Python UDF | `max` | view | 2.607 s (−2.3%) | 5.641 s (−6.3%) | 51.020 s (−4.0%) |
| Python UDF | `max` | bytes | 2.814 s (−1.5%) | 6.852 s (−3.9%) | 53.609 s (−1.1%) |

---

## Table B — 4-node `numa=fake=4` (`nodes="auto"`), re-measured 2026-10-03

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

Across all 24 pipe-vs-file cells, streaming runs at a **median 104% of file
throughput** (light 101%, medium 107%, heavy 109%; range 92–123%). The memfd
copy makes the input source effectively free for forkrun, so it does not pay a
streaming penalty at all. The competition does: most of it cannot ingest a pipe
in the first place.

**Streaming input costs about 1% on this topology.** 48/48 cells exact,
re-measured 2026-10-03 on a fresh `numa=fake=4` boot (`nodes="auto"`,
4 nodes, `shmem_enabled=always`). 9 of 24 cells come in at or below file
time, median penalty **+1.4%**, range −8.0% to +12.1%.

**The sign of that median flips with topology.** On UMA
(`cells_pf.log`) pipe was *faster* than file — median −3.6%, 20 of 24 at
parity-or-better. On the 4-node fake-NUMA boot it is marginally
*slower*, +1.4%. Either way the cost is a couple of percent, but a
"pipe is 4% faster than a file" claim is UMA-specific and should not be
quoted without saying so. The most likely reason: file input already
engages the multi-node ingest/indexer path, so a pipe has less
left to win and its per-node coordination shows up as a small cost.

> **This grid does not measure the pre-flight fix.** Its pipe sources
> deliver at full speed, so the pre-flight has almost nothing to wait
> for and the usleep never fired often enough to show. The per-cell
> deltas between grid runs here are noise — do not read them as
> signal. See the slow-producer measurement below, which is the case
> that change is actually for.

## Why the streaming comparison is forkrun + C plugin vs executor/pool

Not forkrun + C plugin vs executor + ctypes. That row cannot exist on a
stream, and the reason is worth stating because it is the substance of the
5–11× result rather than a detail.

`bench_exectypes.py` enforces that no pickled input crosses the Executor
boundary: workers `pread` assigned byte ranges from the input **file**, and
only `(offset, length)` ints and a path are sent. On a pipe there is nothing
to seek and nothing to range-index, so executor+ctypes loses exactly the
property that made it a fair §0 competitor and collapses back into the same
pickled-batch shape as executor+UDF.

forkrun has no such constraint because its batching happens in C, outside
Python: the engine scans the shared ingress memfd and forms batches, a plugin
reads its own range by offset, and nothing per-batch crosses a Python
boundary. That is also why forkrun can run a C plugin against input that does
not exist in full beforehand.

## The pre-flight spin, measured on the case it targets (W-PREFLIGHT)

The pre-flight scan counts input lines to size its initial batch. When
`pread` returns 0 with ingest not yet complete it means "wait for more",
and it did that with `usleep(100)` — ~10k wakes in 5 s, where Bash's
`ring_copy` slept 78 times because it signals `evfd_ingest_data` per
chunk. A/B on a deliberately slow pipe (2500 lines at 3 ms, 4 workers),
same workload, engine rebuilt both ways:

| | context switches | child CPU | records |
|---|---|---|---|
| before (`usleep` spin) | 13,222 | 0.14 s | 2500/2500 |
| **after** (poll on eventfd) | **453** | **0.07 s** | 2500/2500 |

**29× fewer wakeups, half the CPU**, with exact record counts both
ways. That is the whole claim; the throughput grid above is unaffected
by design, which is the point.

Semantics are unchanged: the pre-flight still only waits for more
input, and only `ingest_complete` ends it. `pre_lines` still counts
real bytes. The signal is a new `fr_py_ingest_data_post()` that asserts
only "bytes were just written" — it deliberately never touches
`state[0].ingest_complete`, because that flag means "the copy loop
ended", not "the input drained" (see the W-GATE2 postmortem in
MEMORY.md, which lost 9,839 records by trusting it).

