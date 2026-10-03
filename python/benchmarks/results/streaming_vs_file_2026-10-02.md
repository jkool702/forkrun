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

## Table B — UMA, re-measured on a UMA-only boot

Complete: 48/48 cells, all exact. Taken after a reboot to a single-NUMA-node
boot (`/sys/devices/system/node/online` = `0`). On that boot
`nodes="auto"` resolves to UMA, so these cells were invoked as `auto` and
are labelled UMA; the distinction that made Table A meaningful no longer
exists here.

> **THP confound applies to this table too.** `shmem_enabled` is `never`
> on this boot, which forkrun's startup notice flags as blocking the
> memfd-backed gain "most notably in -C mode" — i.e. the C plugin rows.
> See `RELEASE_v3.6.0.md` §0 for the full note. Re-measure with
> `shmem_enabled=always` before treating these as forkrun's ceiling.

| payload | config | output | Light (533 MB) | Medium (2.35 GB) | Heavy (6.72 GB) |
|---|---|---|---|---|---|
| C plugin | `default` | view | 1.146 s / 4.36M rec/s (+105%) | 5.528 s / 905k rec/s (+153%) | 15.295 s / 327k rec/s (+126%) |
| C plugin | `default` | bytes | 1.242 s / 4.03M rec/s (+74%) | 6.186 s / 808k rec/s (+130%) | 15.744 s / 318k rec/s (+112%) |
| C plugin | `max` | view | 0.747 s / 6.69M rec/s (+37%) | 3.751 s / 1.33M rec/s (+71%) | 9.954 s / 502k rec/s (+49%) |
| C plugin | `max` | bytes | 0.969 s / 5.16M rec/s (+27%) | 4.468 s / 1.12M rec/s (+46%) | 12.050 s / 415k rec/s (+41%) |
| Python UDF | `default` | view | 2.639 s / 1.89M rec/s (−3%) | 5.974 s / 837k rec/s (−5%) | 51.510 s / 97k rec/s (−3%) |
| Python UDF | `default` | bytes | 2.827 s / 1.77M rec/s (−3%) | 6.568 s / 761k rec/s (−4%) | 52.015 s / 96k rec/s (−3%) |
| Python UDF | `max` | view | 2.635 s / 1.90M rec/s (−4%) | 5.670 s / 882k rec/s (−11%) | 51.247 s / 98k rec/s (−4%) |
| Python UDF | `max` | bytes | 2.891 s / 1.73M rec/s (−3%) | 6.962 s / 718k rec/s (−6%) | 53.006 s / 94k rec/s (−3%) |

## What these two tables say together

**The streaming penalty is a UMA-reactor property, not a streaming
property.** On UMA the C plugin's default configuration pays +105% to
+153% for a pipe; on the default 4-node configuration it pays +4% to
+17%. The fail-fast (`max`) configuration pays much less on either
(+27% to +71% UMA, +4% to −13% four-node) — so most of the cost lives in
the reactor's streaming ingest path specifically, not in ingest as such.

**Boot topology is itself a variable, not a label.** The same
`nodes=1` configuration measured +90/+78/+52% on the fake-4 boot and
+105/+153/+126% on the UMA-only boot, and its absolute file throughput
dropped ~20–35% across the reboot. Part of that is the THP confound
above (`shmem_enabled=never` on the new boot); the rest is unattributed.
Neither table should be quoted without its boot mode.

That path had a hard defect, fixed earlier today: it drained to `EAGAIN`
then slept a flat 20 ms, once per chunk. 645 sleeps on light-5M = 12.9 s
of a 14.65 s wall, 88% of the run. It now `select()`s on the source fd
plus the reactor's death/spawn/trap-ACK descriptors in one call. That
alone took UMA + reactor + pipe from 14.16 s to 0.74 s.

**Syscall counts rule out the obvious next hypothesis.** Same workload
over a pipe, reactor vs fail-fast, UMA:

| | `poll` | `pselect6` | `read` |
|---|---|---|---|
| reactor | 29,494,621 | 65,074 | 496,879 |
| fail-fast | 29,470,526 | 65,070 | 497,491 |

Essentially identical, so the residual UMA reactor cost is Python-side
work per quantum, not kernel traffic. Not yet diagnosed.

Separately: **29.5 M `poll()` calls on both paths** is a large number
independent of the streaming question and worth its own look.

**Python UDF is insensitive to the input shape** in both tables (0% to
−9%): it is UDF-bound, so ingest cost is hidden behind per-record Python
work. The C plugin, which is fast enough for ingest to be the
bottleneck, is the only configuration where the input shape shows.

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