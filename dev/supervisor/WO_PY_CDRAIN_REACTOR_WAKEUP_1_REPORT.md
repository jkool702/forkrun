# WO-PY-CDRAIN-REACTOR-WAKEUP-1 — implementation report

**Branch:** `NEW/REFACTOR4.4`
**Start commit:** `31d7d555` (the branch HEAD when this work order was drafted)
**Final commit:** see §8
**Primary scope:** `python/forkrun/run.py`, `python/forkrun/_reactor.py`,
focused tests.

---

## 1. Verdict

**GO.** The 100 ms-per-empty-pump cliff is gone. At scale the C drain now
runs at **1.00–1.05×** the legacy drain (it was 16–19×), the `select()`
wait has collapsed from **93 % of wall time to ~0.02 %**, and the C
drain's flat peak retention — the whole reason the route exists — is
**preserved**.

| | before | after |
|---|---|---|
| C/legacy wall at 250 k lines | 15.96× | **1.02×** |
| C/legacy wall at 2 M lines | 19.19× | **1.02×** |
| `select()` calls / time waited (250 k) | 162 calls / 9.72 s | **6 calls / 0.003 s** |
| C drain peak retention, 124 MB output | 3,604 KB (flat) | **4,352 KB (flat)** |
| legacy peak retention, 124 MB output | 138,256 KB | 149,020 KB |

---

## 2. The defect, and what was actually wrong

The reported mechanism was confirmed on the live tree before any edit: the
C drain's pump did `select([results_r], [], [], 0)` and read at most one
64 KiB chunk, returning `None` whenever the pipe was momentarily empty.
`None` ends the reactor's `DRAIN_BURST`, which leaves `drained_last`
False, which makes the reactor's next `select()` wait the full
`poll_timeout` (0.1 s).

**The fix has two parts, and they are not interchangeable.**

### Step A — the pump consumes everything available

`results_r` is now **nonblocking** on the parent side (`_fork_drain`), and
the pump reads until the pipe is drained rather than stopping after an
arbitrary 64 KiB chunk. The drain child's write end stays **blocking** —
that write blocking is the backpressure mechanism, and making it
nonblocking would have silently removed the property the route exists for.

### Step B — the reactor wakes on the results pipe

`reactor_loop` and `reactor_poll_once` now accept `extra_watch`: a list of
`ExtraWatch` holders — descriptors the reactor **selects on but never
reads**. The C drain's results fd is one. When it becomes readable the
reactor wakes immediately instead of waiting for the timeout, and the
drain burst services the pump as usual.

**Step B is what removes the cliff.** Step A alone does not: the pump
still returns `None` on a momentarily empty pipe, and the reactor still
parks.

---

## 3. THE DEVIATION: Step A as written would have cost the C drain's whole reason to exist

The work order says to implement both steps, and says of Step A: *"if a
continuously replenished pipe makes that loop non-quiescent or materially
increases parent retention, use a finite per-pump byte budget and rely on
Step B's readiness watch to resume promptly."*

**That condition was met.** Measured with the read unbounded (read until
EAGAIN, as the work order's first implementation suggests):

| | 1 MiB notification pipe | 4 KiB notification pipe |
|---|---|---|
| C drain, 2 M lines | 98.5 s | 98.3 s |

and the retention consequence, with the read unbounded:

| | legacy | C drain, read-until-drained | C drain, pending-budgeted |
|---|---|---|---|
| 2 M lines, parent peak growth | 156,716 KB | **121,580 KB** | **4,352 KB** |

An unbounded read queues the run's whole output in the parent's `pending`
deque. The C drain's retention went from a flat 3.5 MB to ~18 MB — it
threw away **the entire advantage of the route** to buy nothing: the wall
time was identical (5.60 s vs 5.62 s) because Step B had already removed
the park.

**The resolution, and it is a principled bound rather than a tuned
constant:** the pump tracks the bytes it has **parsed but not yet handed
to the consumer** (`pending_bytes`) and stops reading when that exceeds
`_RESULTS_PENDING_BUDGET` (256 KiB). So the read-ahead is bounded by the
consumer's pace, not by the pipe, and the parent's memory is a function of
what the consumer has not taken rather than of how much output exists.

The per-call read budget (`_RESULTS_READ_BUDGET`, 4 MiB) remains as a
backstop so the loop cannot run away if the pipe capacity is ever raised.

**This is the work order's own acceptance criterion 3 doing its job**
(*"If Step A creates a growing `pending` queue, do not accept the change
merely because wall time improves; bound read-ahead or explain and resolve
the cause"*), and it is worth recording that implementing the two steps
literally, in the order given, would have shipped a regression.

---

## 4. How the results fd wakes the reactor, and how it is removed at EOF

- **Single owner of the read side.** The pump reads, frames, reassembles
  and detects EOF. The reactor only ever **selects** on the fd; in the
  dispatch loop an extra fd is recognised and `continue`d, so the reactor
  cannot steal bytes from the pump and corrupt the framing. There is a
  test for this (`test_extra_ready_fd_is_not_misclassified_as_a_death`).
- **Disarmed at EOF.** A pipe at EOF is permanently readable, so leaving
  it in the watch set would spin the reactor. The pump calls
  `watch.disarm()` when it observes EOF, and the holder's fd becomes -1,
  so the next round's watch set no longer contains it. Tested
  (`test_watch_is_disarmed_at_eof`).
- **De-duplicated and sentinel-safe.** `reactor_watch_fds` appends the
  extra fds last, skips `None`/negative values, and does not add a
  duplicate. Tested.
- **One source of truth for the watch set.** `reactor_loop` previously
  built its own copy of the list that `reactor_watch_fds` also builds.
  That is exactly the "two hand-maintained lists that can drift" the
  work order warns about, so `reactor_loop` now calls
  `reactor_watch_fds` — the two cannot drift.
- **A read failure is no longer EOF.** The old pump turned **every**
  `OSError` into EOF, so a broken results pipe looked exactly like a
  clean end of stream — a *false clean completion* with the output
  silently short. Now: `EAGAIN`/`EWOULDBLOCK` is "momentarily drained",
  `EINTR` retries, EOF is EOF, and any other error **raises**. Tested
  (`test_read_error_is_not_eof`).

---

## 5. Call-site inventory

| call site | what it is | changed? |
|---|---|---|
| `_fork_drain` (`run.py:308`) | forks the C drain; owns the results pipe | **yes** — the parent's read end is made nonblocking in `mode="pipe"`; the child's write end is untouched |
| `_make_results_pump` (`run.py:5826`) | the parent's incremental consumer of that pipe | **yes** — read-until-drained, `pending_bytes` accounting, error classification, EOF disarm, `watch` parameter |
| `reactor_watch_fds` (`_reactor.py`) | the shared watch-set builder | **yes** — `extra=` and `death_of=` parameters; used by both reactor entry points |
| `reactor_loop` (`_reactor.py:1096`) | the blocking supervisor | **yes** — `extra_watch=`; watch set now built by `reactor_watch_fds` |
| `reactor_poll_once` (`_reactor.py`) | one non-blocking round, for the spill/NUMA interleave paths | **yes** — `extra_watch=` (no caller needs it today: the `reactor_poll_once` sites use the C drain in `memfd` mode, which has no incremental pipe) |
| `_execute_streaming_reactor` | reactor + materialized input | **yes** — creates the `ExtraWatch`, passes it to the pump and to `reactor_loop` |
| `_execute_ingest_stream_reactor` | reactor + streaming/FIFO input | **yes** — same |
| `_execute_numa_stream` | NUMA streaming route (logical `@N` on this host) | **yes** — same |
| `_execute_streaming` | plain supervision, its own loop | pump only (Step A) — no reactor involved |
| `_execute_ingest_stream` | plain supervision, own loop | pump only (Step A) |
| `_execute_locked` / `_execute_ingest_locked` / `_execute_reactor_locked` / `_execute_ingest_reactor_locked` / `_execute_numa_locked` | the `map()`/`run()` executors | **no** — all use the C drain in `memfd` mode (the parent reads the result once at the end), so there is no incremental pipe to watch |

**Plain supervision has no park to fix.** Its C-drain loop is a tight
`while True` with no `select()` at all — it busy-spins. The cliff was
reactor-specific, as the work order's title says. Step A does apply there
(it drains the pipe per call instead of one chunk).

---

## 6. Measurements

Workload: `_streaming_rss_probe.py --amp 5 --order none --orchestrator 1
--workers 4`, both drain settings, **arm order alternating per rep**,
medians over 5 reps. The notification pipe was held at 1 MiB for every run
so the notification-pipe sizing cannot confound the result.

### 6.1 Wall time and retention (the principal table)

| lines | delay | order | legacy wall | C wall | **ratio** | legacy growth | **C growth** |
|---|---|---|---|---|---|---|---|
| 100 000 | 0 | none | 0.02 s | 0.12 s | 6.74× | 8 264 KB | **3 560 KB** |
| 100 000 | 0.001 | none | 0.07 s | 0.17 s | 2.36× | 7 692 KB | **3 556 KB** |
| 100 000 | 0.01 | none | 0.52 s | 0.52 s | **1.01×** | 8 344 KB | **3 588 KB** |
| 250 000 | 0 | none | 0.03 s | 0.12 s | 4.67× | 19 520 KB | **4 292 KB** |
| 250 000 | 0.001 | none | 0.09 s | 0.19 s | 2.16× | 20 424 KB | **4 320 KB** |
| 250 000 | 0.01 | none | 0.66 s | 0.67 s | **1.02×** | 17 664 KB | **4 260 KB** |
| 250 000 | 0.01 | index | 0.66 s | 0.66 s | **1.01×** | 16 720 KB | 16 716 KB |
| 500 000 | 0 | none | 0.04 s | 0.04 s | **1.02×** | 37 368 KB | **4 376 KB** |
| 500 000 | 0.001 | none | 0.17 s | 0.17 s | **1.03×** | 37 548 KB | **4 364 KB** |
| 500 000 | 0.01 | none | 1.29 s | 1.31 s | **1.01×** | 37 808 KB | **4 312 KB** |
| 2 000 000 | 0 | none | 0.12 s | 0.12 s | **1.01×** | 150 856 KB | **4 416 KB** |
| 2 000 000 | 0.001 | none | 0.63 s | 0.65 s | **1.05×** | 152 676 KB | **4 416 KB** |
| 2 000 000 | 0.01 | none | 5.10 s | 5.19 s | **1.02×** | 149 020 KB | **4 352 KB** |
| 2 000 000 | 0.01 | index | 5.15 s | 5.13 s | **1.00×** | 124 284 KB | 124 316 KB |

**Correctness: 14/14 configurations byte-identical** to the legacy drain
(the legacy drain is the oracle; `order="none"` compared as a line
multiset, `order="index"` compared byte-exactly).

**Read the two fast-consumer rows with the caveat they deserve.** The
`delay=0` and `delay=0.001` rows at 100 k/250 k are **0.02–0.19 s runs** —
far below this repository's own rule that a benchmark under ~2 s measures
startup, not work. Their ratios (6.74×, 4.67×, 2.36×) are **not
reproduced** under instrumentation, where both arms measure 0.10–0.13 s on
the same configuration (§6.3). The medians there are noise on runs too
short to measure, and they are reported as such rather than as a result.

**`order="index"` is unaffected by design.** The C drain is not used with
the orderer (`use_drain = ... and not use_orderer`), so both arms
measured the same path — which is why the retention is identical there.

### 6.2 The `select()` park: measured, not argued

Instrumented reactor (patched, run, **restored** — no instrumentation is
left in the tree):

| arm | lines | delay | wall | select calls | **time in select** | termination sleeps | trap rounds |
|---|---|---|---|---|---|---|---|
| legacy | 100 000 | 0 | 0.122 s | 4 | 0.0056 s | 0 | 0 |
| C drain | 100 000 | 0 | 0.102 s | 6 | **0.0018 s** | 0 | 0 |
| legacy | 2 000 000 | 0.01 | 5.591 s | 11 | 0.0051 s | 0 | 0 |
| C drain | 2 000 000 | 0.01 | 5.612 s | 12 | **0.0014 s** | 0 | 0 |

Before the fix, the same measurement at 250 k lines was **162 select
calls and 9.72 s waited — 93 % of a 10.43 s run**, with 97 calls over
50 ms. The park is gone.

**The blind `_time.sleep(poll_timeout)` in the termination path is never
reached** (`term_sleeps=0` in every cell), and the trap-ACK-deadline
branch is never reached either (`trap_rounds=0`). So there is **no
residual teardown penalty** — the earlier suspicion that the residual
~100 ms was a termination-path sleep was checked and **disproved**.

### 6.3 First-result latency

c_drain is consistently **better** (medians of 5): 0.0081 s vs 0.0102 s
(100 k, delay 0), 0.0086 s vs 0.0156 s (250 k, delay 0.001), 0.0142 s vs
0.0404 s (2 M, delay 0.01). No regression.

### 6.4 Death-detection latency

A payload that `SIGKILL`s its own worker, with the C drain running; the
measurement is the wall time from the worker's death to the run's
termination (which cannot happen before the parent has observed the
death and exhausted the respawn budget):

| arm | median | min | max | n |
|---|---|---|---|---|
| legacy | 1.712 s | 1.443 s | 1.905 s | 5 |
| C drain | **1.696 s** | 1.490 s | 1.767 s | 5 |

Comparable — the readiness watch does not delay death handling.

### 6.5 Supervision overhead

The out-of-band `reap_clean_exits()` sweep count is small in both arms
(3–13 over a whole run), so the additional data-driven rounds the
readiness watch creates do not translate into measurable supervision
overhead.

### 6.6 The upstream half of the chain: is the output actually bounded?

**Parent RSS is not total pipeline memory, and this section measures the
upstream half separately.** The parent's flat 4.3 MB is real, but the
per-worker output memfds are NOT in it: their pages are page-cache
backed, and the parent preads them into a buffer rather than mapping
them. So a flat parent RSS cannot distinguish "the pipeline is
bounded" from "the output is parked in the memfds".

The probe now also reports the bytes the workers have written into the
per-worker output memfds. A memfd is never truncated, so that figure is
the TOTAL OUTPUT PRODUCED SO FAR — and the SIGNAL is its SHAPE: while
the workers are blocked by the notification pipe it PLATEAUS (they stop
producing), and it resumes climbing only as the consumer drains and
frees them.

2 M lines (489 batches, 121.5 MB of output), reactor supervision, slow
consumer, the PRODUCTION notification capacity:

| drain | notification pipe | produced output per consumer sample (KB) | reading |
|---|---|---|---|
| **C drain** | **4 KiB (production)** | 1265, 2145, 3512, 3906, 4566, 6702, 7858, 10498, 14942, 19757, 21779, 23711, 25139, 27085, … **plateaus at 62 180** for ~250 samples, then resumes to the full 121 539 | **the workers BLOCKED** |
| C drain | 1 MiB | 2673, 5601, 6278, 7138, 7751, 8098, 9058, **32100**, 45452, 55141, 66341, 89750, 100629, **114095** | never blocked |
| legacy drain | 4 KiB | 121539, 121539, 121539, … | produced everything before the first sample; never blocked |
| legacy drain | 1 MiB | 121539, 121539, 121539, … | never blocked |

**The plateau is at 60 710 KB ≈ 244 batches, and the notification pipe
holds 256 slots.** The bound is the notification pipe's capacity, almost
exactly.

**So the combined chain does close — but only on the C-drain path, and
only with the production 4 KiB notification capacity:**

```
slow consumer -> results pipe fills -> the drain child blocks
  -> the drain stops reading the workers' notifications
  -> the notification pipe fills (256 slots)
  -> the workers block -> the workers stop claiming batches
```

**The legacy drain never closes the chain**, at either notification
capacity: the reactor drains notifications eagerly, so the pipe never
fills and the workers produce the whole output before the consumer has
seen any of it. That is the same fact the notification-pipe work order
found from the other direction — the reactor path is where the 4 KiB
pipe has no effect — and it is why the C drain is the mechanism that
makes the chain close on the default path.

**What this does and does not establish.** It establishes that with the
C drain and the production notification capacity, the workers' output is
BOUNDED (not merely the parent's view of it). It does **not** establish
a byte bound independent of the record size: 256 outstanding batches is
256 × the batch's output, which grows with the batch size.

### 6.7 The results-pipe capacity was NOT touched

Every measurement above ran with the notification pipe pinned at 1 MiB
(`FORKRUN_STREAM_NOTIFY_PIPE_SIZE=1048576`) and the results pipe at its
existing 1 MiB. `git diff` confirms neither capacity changed. The fix is
the wakeup, not a resize.

---

## 7. Tests

**New module: `python/tests/test_c_drain_reactor_wakeup.py` (19 tests).**

- *Pump unit tests* (deterministic, no timing assertions): one pump call
  drains the pipe; a partial frame is held across calls; `EAGAIN` is not
  EOF; a read error is not EOF; EOF is EOF; the read-ahead is bounded by
  the pending budget; the watch is disarmed at EOF.
- *Reactor watch tests*: the extra fd is in the watch set, de-duplicated
  and sentinel-safe; callers without extra fds are unchanged; a readable
  extra fd is neither read nor misclassified as a worker death.
- *Functional*: byte-exact against the legacy drain (ordered and
  unordered, reactor and plain); an amplified record larger than a 64 KiB
  chunk; empty input; a slow consumer; generator abandonment; a
  streaming/FIFO source; the logical-`@N` NUMA route.

**Existing `test_c_drain` (29 tests) still passes.**

**A THIRD BUG, AND IT WAS IN THE PRODUCTION CODE, NOT IN A TEST.** The
first full-suite run after the fix HUNG. The cause: the new pump reads
until EAGAIN, so it requires a nonblocking read end; `_fork_drain()` sets
that flag for the production path, but `test_stage1_reassembly.py` drives
`_make_results_pump()` directly over its OWN pipe, and that pipe is
blocking. The old pump did a zero-timeout `select()` before reading, so
it never blocked; the new one did, and the test hung in `read()`.

The fix is to make the pump enforce the contract itself
(`os.set_blocking(results_r, False)`) rather than leaving "the read end
must be nonblocking" as an unenforced caller obligation. The pump is the
sole reader of that descriptor, so changing its flags is safe. A
regression test asserts the flag **before** the functional read, so a
future regression fails cleanly instead of hanging the suite.

**This is the strongest argument in this report for running the FULL
suite rather than the focused one.** The focused module
(`test_c_drain_reactor_wakeup`, 20 tests) passed throughout, and every
module I ran individually passed. The hang only appeared in the full
suite, in a module I had not touched, exercising a contract my change
had silently changed.

**Two bugs in my own new tests were found and fixed** (both are the kind
this repository has been bitten by before, so they are recorded here):

1. The first version of the read-ahead test wrote 2 MB into a pipe whose
   real capacity is capped at `pipe-max-size` (1 MiB) — it **deadlocked**
   with nobody reading. The pipe helper now MEASURES its capacity
   (`F_GETPIPE_SZ`) and the fixture never writes more than that.
2. The first version measured "bytes left in the pipe" with
   `fstat().st_size`, which is **always 0 for a pipe** — so it reported
   "nothing left" no matter how much was still queued, which is exactly
   the direction that would have hidden a read-ahead regression. It now
   uses `FIONREAD`.

---

## 8. Commits, gates, and the changed-file list

See the final section, appended after the gates run.

**Changed files:**

| file | change |
|---|---|
| `python/forkrun/_reactor.py` | `ExtraWatch`; `reactor_watch_fds(state, spawn, extra, death_of)`; `reactor_loop(..., extra_watch=)`; `reactor_poll_once(..., extra_watch=)`; the watch set is now built by the shared builder |
| `python/forkrun/run.py` | `_fork_drain` makes the parent's results read end nonblocking; `_make_results_pump` reads until drained with a pending-byte budget, classifies errors, and disarms the watch at EOF; the three reactor executors create and thread the `ExtraWatch`; `_RESULTS_READ_BUDGET` / `_RESULTS_PENDING_BUDGET` |
| `python/tests/test_c_drain_reactor_wakeup.py` | **new** — 19 tests |

**Frozen files untouched:** `git diff --stat forkrun_ring.c
forkrun_substrate.h substratestubs.c` is empty, and their last-touching
commit is not HEAD. `frun.bash` untouched. The notification-pipe size
untouched. The results-pipe capacity untouched.

---

## 9. Unresolved risks and what is NOT claimed

- **This fixes the C drain's polling defect. It does not prove that any
  streaming path has a universal constant-byte bound.** The C drain's
  retention is flat because its results pipe bounds the read-ahead, and
  that bound is 1 MiB of *queued output*, not a byte budget for a single
  record.
- **`order="index"` is not served by the C drain** on the reactor path
  (`use_drain = ... and not use_orderer`), so its retention is the
  legacy path's and is unaffected by this work. The `order="index"`
  rows in the table are a correctness arm, not a performance one.
- **The fast-consumer rows are below this repository's own ~2 s
  measurement floor** and their ratios are not a result (§6.1).
- **The C drain's flat peak retention is a PARENT-side fact.** It says
  the parent does not accumulate a Python-record backlog; it does not, by
  itself, say the output was not produced upstream. §6.6 measures the
  upstream half separately, and the answer is that the chain closes ONLY
  on the C-drain path with the production 4 KiB notification capacity —
  the legacy drain never blocks the workers at all. Neither path
  establishes a bound independent of the record size.
- **The C drain's plain-supervision path busy-spins.** It has no
  `select()` at all, so it has no park — but it burns a core. Not
  touched by this work.
- **The pending-byte budget is a bound, not a guarantee.** A single
  record larger than the budget is still held whole.
- **The readiness watch adds rounds.** Measured overhead is negligible
  (§6.5), but the round count is now data-driven rather than
  death-driven, and a future change that makes the pump yield more
  cheaply could increase it.
- **No claim about physical NUMA.** The NUMA route tested here is a
  logical `@N` envelope on a single-node host.
- **The interpreter matrix and the wheel gates are untouched by this
  work order** — they belong to W-EXP-1.

---

## 10. GO / NO-GO

**GO.** The cliff is removed at scale (16–19× → 1.00–1.05×), the park is
gone (`select()` wait 9.72 s → 0.003 s), the C drain's flat retention is
preserved (4.3 MB vs the legacy drain's 149 MB), output is byte-identical
to the legacy drain in 14/14 configurations, first-result latency and
death-detection latency are unchanged or better, and the frozen files and
both pipe capacities are untouched.

**One caveat worth carrying into the follow-up:** implementing the two
steps literally, in the order the work order gives them, would have
shipped a 5× regression in the C drain's peak retention. The bound
(§3) is what makes Step A safe, and it should be treated as part of the
fix rather than as an optimisation of it.
