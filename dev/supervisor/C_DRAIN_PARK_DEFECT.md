# The C drain's stream path is 16–19× slower than the legacy drain, and it is a 100 ms poll interval

**Status:** open defect, fully diagnosed, not fixed.
**Scope:** `python/forkrun/run.py`, `python/forkrun/_reactor.py`.
**Branch / commits measured at:** `NEW/REFACTOR4.4` @ `7fae2c35` (and `8c016b68` — the defect predates all of this work).
**Purpose of this document:** to be handed to a supervisor agent that will
turn it into a work order. It states the defect, the mechanism, the
measurements, the constraints, and the candidate fixes, with the
acceptance criteria implied.

---

## 1. The defect, in one paragraph

`forkrun.stream(..., c_drain=True)` is **16–19× slower** than the same
stream with the legacy Python drain, once the run is large enough. The
cause is a **100 ms poll interval in the reactor's supervision loop**,
entered whenever the C drain's pump has no data ready. In a measured
250 k-line run, **9.72 s of a 10.43 s run (93 %) was spent sleeping in
`select()`**. The C drain is the *correct* mechanism for bounding
streaming memory — its peak retention is flat at ~3.5 MB while the legacy
drain's grows linearly to 138 MB — so this defect makes the right
mechanism unusable at speed, and it is the main reason the Python
frontend cannot bound memory on the default streaming path.

---

## 2. The yardstick: what bash does

The bash frontend is the reference implementation for this repository, and
its orchestrator is a **single `poll()` over a pre-built fd list**:

```bash
# frun.bash:2233
while _fr_build_poll_lists; ring_poll "$fd_spawn_arg" "$_fr_scan_list" \
      "$_fr_work_list" "$_poll_timer_cmd" "$fd_trap_ack_r" "$_fr_indexer_list"; do
```

The engine's `poll()` reports liveness; the orchestrator never decides
*how long* to wait because it is never the thing that has to notice.
`python/forkrun/_reactor.py`'s docstring cites this explicitly as the
good pattern. The 100 ms park below is the divergence from it.

Bash also sizes its one feedback channel deliberately:

```bash
# frun.bash:1730-1731
# B2: Size order ack pipe to 4096 (1 page) for closed hydraulic backpressure
ring_pipe fd_order_r fd_order_w 4096
```

Every other bash pipe (`fd_spawn`, `fd_fallow`, `fd_trap_ack`, the death
pipes, the per-worker pipes) is `ring_pipe` with no size argument — the
engine default `RING_PIPE_CAPACITY:=65536`. Bash has exactly one
deliberately-small channel and it is the feedback one.

---

## 3. The mechanism, source-level

### 3.1 The C drain's pump

`python/forkrun/run.py:5895-5926`, `_make_results_pump()`:

```python
def pump(alive):
    if not st["eof"]:
        try:
            ready, _, _ = _select.select([results_r], [], [], 0)   # ZERO timeout
        except (OSError, ValueError):
            ready = []
        if ready:
            try:
                chunk = os.read(results_r, 65536)                   # ONE 64KB read
            except OSError:
                chunk = b""
            if chunk == b"":
                st["eof"] = True
            else:
                _ingest(chunk)
    if st["pending"]:
        return st["pending"].popleft()
    ...
    return None
```

Three properties matter:

1. The select has a **zero** timeout, so it answers "is there data right
   now", never "wait for data".
2. It reads **65536 bytes per call** — a whole batch is ~230 KB at
   `amp=5`, so it takes ~4 calls to assemble one record.
3. It returns **`None`** whenever the pipe was not ready. `None` is the
   reactor's "nothing complete *yet*, keep polling" signal.

### 3.2 The reactor's park

`python/forkrun/_reactor.py:1232-1243` — the drain burst:

```python
if drain_gen is not None:
    drained_last = False
    for _ in range(DRAIN_BURST):          # DRAIN_BURST = 64  (_reactor.py:91)
        try:
            blob = drain_gen()
        except StopIteration:
            drain_gen = None
            break
        if blob is None:
            break                          # <-- ends the burst
        drained_last = True
        yield blob
```

and `python/forkrun/_reactor.py:1152-1161` — the round's select:

```python
# Adaptive idle: a round that drained results
# re-polls immediately (tight drain loop under load)
# instead of sleeping a full quantum with data
# waiting — otherwise throughput caps at ~10
# blobs/s (one yield per 100ms idle select).
readable, _, _ = _select.select(
    watch, [], [],
    0.0 if drained_last else poll_timeout)     # poll_timeout = 0.1 s
```

### 3.3 The chain that produces the 100 ms park

```
the results pipe is momentarily empty
  -> the pump's zero-timeout select says "not ready"
  -> the pump returns None
  -> the DRAIN_BURST breaks, so drained_last stays False
  -> the NEXT round's select waits the full poll_timeout (0.1 s)
  -> the next round finally finds the data
```

The cost per "round that did not drain" is **100 ms of pure sleeping**.
The reactor's own comment names the resulting cap: *"otherwise throughput
caps at ~10 blobs/s (one yield per 100ms idle select)"*.

### 3.4 Why the legacy drain does not park

The legacy drain's generator (`run.py:5666-5702`) **yields inside the
collection loop**:

```python
for _bidx, _disp, _blob in _drain_worker_memfd_terminal(
        out_fds[wid], per_worker[wid]):
    if reassembly is None:
        if _disp == _DISP_DATA:
            yield _blob                     # <-- yields INSIDE the loop
```

It is **consumer-paced**, and its data source is the worker's memfd,
which is *always* pollable — it `pread`s unconditionally and yields
whatever is there. So a round that yields a record sets `drained_last =
True`, and the next round's select keeps its 0 timeout. The legacy path
never parks.

The C drain cannot be consumer-paced in the same way: its data source is
the **results pipe**, so it must wait for that pipe. The C drain's
results pipe is created at `run.py:349` with `make_pipe()` — 1 MiB
(`_pipes.py:48`).

---

## 4. The evidence

### 4.1 Scale sweep (the cliff)

`python/tests/_streaming_rss_probe.py --amp 5 --delay 0.01 --order none
--orchestrator 1 --workers 4`, with and without `--c-drain`:

| lines | output | blobs | legacy | c_drain | ratio | legacy growth | c_drain growth |
|---|---|---|---|---|---|---|---|
| 5,000 | 0.24 MB | 40 | 0.42 s | 0.42 s | 1.01× | 2,556 KB | 2,788 KB |
| 25,000 | 1.32 MB | 49 | 0.51 s | 0.52 s | 1.02× | 3,828 KB | 3,496 KB |
| 100,000 | 5.44 MB | 49 | 0.52 s | 0.62 s | **1.21×** | 8,312 KB | 2,980 KB |
| 250,000 | 14.44 MB | 62 | 0.65 s | **10.43 s** | **15.96×** | 17,640 KB | 3,588 KB |
| 500,000 | 29.44 MB | 123 | 1.29 s | 21.94 s | 16.99× | 37,472 KB | 3,508 KB |
| 1,000,000 | 59.44 MB | 245 | 2.56 s | 44.68 s | 17.43× | 74,600 KB | 3,560 KB |
| 2,000,000 | 124.44 MB | 489 | 5.11 s | 97.88 s | **19.19×** | 138,256 KB | **3,604 KB** |

**The cliff is at ~50–64 blobs — the `DRAIN_BURST` size.** Below it, one
reactor round drains everything and the run never needs a second round,
so it never parks: the C drain matches the legacy drain at 1.01–1.21×.
That is very likely where the *"0.7–1.0× of the legacy Python drain"*
figure in `run.py`'s `_validate_c_drain` docstring was measured. Above
the cliff, the cost is ~0.17–0.20 s **per blob**, regardless of blob size
or corpus size.

**The retention columns are the other half of the story:** the C drain's
peak retention is **flat at ~3.5 MB** while the legacy drain's grows
linearly to 138 MB. The C drain is doing exactly what it was designed to
do.

### 4.2 The park, instrumented

`python/forkrun/_reactor.py`'s select was temporarily instrumented to
time itself, at 250 k lines, `delay=0.01`:

| | select calls | total time waiting in `select()` | calls over 50 ms |
|---|---|---|---|
| `c_drain=True` | 162 | **9.72 s of a 10.43 s run (93 %)** | 97 |
| legacy drain | **5** | 0.01 s | 0 |

Mean wait per select: 0.0600 s (C drain) vs 0.0011 s (legacy).

### 4.3 It is NOT caused by the notification-pipe work

The C drain's slowness predates it and is independent of it:

| notification pipe capacity | c_drain wall (2 M lines) |
|---|---|
| 1 MiB (the pre-change value) | 98.5 s |
| 4 KiB (the current value) | 98.3 s |

---

## 5. Why this matters beyond the slowness

The C drain is the **stdout-pipe analogue** in bash's backpressure chain.
Bash's chain is:

```
slow consumer
  -> the stdout pipe fills and freezes
  -> ring_order blocks writing stdout
  -> ring_order stops clearing the ack pipe
  -> the ack pipe fills
  -> workers block on the ack
```

The ack pipe is the *last* link and is small (4096). It only has to
**latch** a backpressure the stdout pipe has already started.

In the Python frontend:

- The **plain** supervision path (`orchestrator=False`) closes the chain:
  its drain yields inside the collection loop, so the consumer's slowness
  stops the drain, the notification pipe fills, and the workers block.
- The **reactor** path (the default) **breaks the chain at the first
  link**: its drain collects into a `_pending` list and pops one record
  at a time (`run.py:9207-9208`), and the reactor pulls up to `DRAIN_BURST`
  (64) records per round regardless of the consumer. The consumer's
  slowness is absorbed by a **Python list**, not by a pipe. The
  notification pipe never fills, the ack-pipe analogue never engages,
  and the parent's own memory grows instead (measured: 250 MB of parent
  retention on a 254 MB output).
- The **C drain's results pipe is the missing stdout-pipe analogue** — a
  real pipe between the drain and the consumer that blocks the producer.
  It is the only mechanism on the default path that produces a *flat*
  retention curve, and it is broken by the park.

**So this defect is the blocker on bounding streaming memory on the
default path.** Fixing it may make the notification-pipe sizing change
unnecessary there (see §8).

---

## 6. Candidate fixes

All three are agreed in principle. **(1) is the precondition that makes
(3) cheap**; (3) is the idiomatic forkrun way and should be implemented
even if (1)+(2) turn out to suffice, unless it measurably hurts.

### (1) Drain the results pipe fully per pump call

Set the results-pipe read end `O_NONBLOCK` and loop `read(65536)` until
`EAGAIN`, ingesting every chunk, before returning one pending record.

- Why it helps: a "drained" round then genuinely drains, so
  `drained_last` stays `True` and the reactor's next select keeps its
  0 timeout. The burst is no longer broken by a momentarily-empty pipe.
- Size: a dozen lines, local to `_make_results_pump` plus a
  non-blocking flag on the read end.
- Risk: low. The read end is the parent's and only the pump reads it.
  The framing/partial-record handling (`st["tail"]`) already tolerates
  arbitrary chunk boundaries.

### (2) Adaptive backoff instead of an immediate give-up

When the pipe is momentarily empty, spin on a short doubling ramp before
returning `None` — the idiom the NUMA fork gate already uses
(`run.py:169` `_GATE_POLL_MIN_S = 0.0005`, used at `run.py:11510`).

- Why it helps: covers the case where the drain child is momentarily
  behind, without ending the burst.
- Size: small — a ramp constant plus a loop.
- Risk: low, but the budget must be short. The pump runs inside a
  reactor round, so a long spin would delay death detection.

### (3) Put `results_r` in the reactor's watch set (the event-based wakeup)

The reactor's select currently watches only death, spawn and trap-ACK
pipes. Adding the results fd means the reactor wakes exactly when the
drain child writes, and the 100 ms park disappears from the data path.

- Why it helps: this is bash's mechanism (`frun.bash:2233` — one
  `ring_poll` over a pre-built fd list; the engine's poll reports
  liveness).
- Size: **medium**. The results fd currently lives inside a closure
  (`_make_results_pump` returns a `pump` function) and the reactor does
  not know it exists. It needs an "extra watch fds" parameter threaded
  through `reactor_loop` (`_reactor.py:1096`) and `reactor_poll_once`
  (`_reactor.py:1339`), plus the coupling that "results fd readable" means
  "run the drain burst". The NUMA and streaming-ingest executors drive
  the reactor through `reactor_poll_once`, so both entry points need it.
- Risk: medium. Watch points:
  - **Wakeup count.** Today the reactor's rounds are death-driven; they
    would become data-driven, so there will be more rounds.
  - **Reap-sweep cost.** More rounds means more `reap_clean_exits()`
    sweeps. It is already throttled to 2 ms
    (`_REAP_SWEEP_INTERVAL_S`, `_reactor.py:102`), so it is bounded, but
    the syscall count will rise.
  - **Ordering between (1) and (3).** (3) alone wakes the reactor per
    64 KB chunk — ~3,900 wakeups for a 254 MB output. (1) makes the data
    arrive in far fewer, larger chunks, so the wakeup count drops by the
    same factor. **Implement (1) first.** (1) and (3) are synergistic,
    not alternatives.

---

## 7. What to measure (the acceptance shape)

**Primary:** the C drain's wall time vs the legacy drain's, across the
scale range in §4.1, with the ratio expected to fall from ~19× to
~1.0–1.2×. The cliff at ~64 blobs should disappear.

**Also report:**

| quantity | why |
|---|---|
| select call count, and total time waiting in `select()` | the direct measure of the park; the legacy drain's figures are 5 calls / 0.01 s |
| calls to `reap_clean_exits()` | the cost of (3)'s extra rounds |
| throughput (records/s) and first-result latency | the guard against (3) regressing the fast path |
| **death-detection latency** | (3) changes the round cadence; a worker killed mid-run must still be noticed promptly. **Measure it — do not assume it.** |
| peak retention | must stay flat (~3.5 MB). If a fix costs memory, that defeats the purpose of the C drain |
| output correctness, byte-exact | an unchanged gate |

**Beware the bimodality.** The reactor's first-result latency is
**bimodal** (≈0.02 s or ≈0.15–0.40 s — the poll quanta) and the
throughput cells are noisy at the ±25 % level. Use ≥5 reps, medians, and
**alternate the A/B order**; a 33 % "regression" observed in this area
reversed completely with more reps and more arms.

---

## 8. Scope boundaries

**In scope:** `python/forkrun/run.py` (`_make_results_pump`, `_fork_drain`),
`python/forkrun/_reactor.py` (`reactor_loop`, `reactor_poll_once`, the
watch set). Tests.

**Out of scope:**

- `forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c` — **frozen**.
- The bash frontend — the reference, read-only.
- The engine's `fr_py_drain_loop` — it is not the problem; the problem is
  the parent's poll cadence.
- The C drain's **results pipe capacity** (1 MiB, `run.py:349`). It is a
  separate backpressure stage and changing it would confound the
  measurement.
- The notification-pipe sizing work (`STREAM_NOTIFY_PIPE_SIZE`,
  `WO-PY-STREAM-BACKPRESSURE-1`) — separate concern. **But see below.**

**Relationship to the notification-pipe work.** The 4 KiB notification
pipe is bash's *ack-pipe* analogue — the **last** link — and it can only
engage if the chain upstream of it is closed. The plain path's chain is
closed; the reactor path's is not, and the C drain's results pipe is the
missing stdout-pipe analogue. **So if this defect is fixed, the C drain
may deliver a flat ~3.5 MB retention on the default path, and the
notification-pipe sizing may become unnecessary there.** Decide
afterwards whether to keep the 4 KiB default or revisit it. Do not
couple the two changes.

**And do NOT assume that fixing this makes the 4 KiB notification pipe
redundant.** The two stages constrain different parts of the pipeline:
the results pipe is the DOWNSTREAM transport (drain -> consumer), and
the notification pipe still bounds how far the workers get ahead while
the drain is blocked. A fixed C drain may well remove the need for the
small notification pipe on some route -- but that has to be decided
from a fresh measurement, not from expectation.

---

## 9. Reproduction

All commands are committed probes; there is no scratch script.

```bash
cd /mnt/ramdisk/forkrun

# the cliff: legacy vs c_drain, by scale
for n in 100000 250000 500000 2000000; do
  python3 python/tests/_streaming_rss_probe.py --lines $n --amp 5 \
      --delay 0.01 --order none --orchestrator 1 --workers 4
  python3 python/tests/_streaming_rss_probe.py --lines $n --amp 5 \
      --delay 0.01 --order none --orchestrator 1 --workers 4 --c-drain
done

# the park itself: instrument _reactor.py's select to time itself, or
# use strace -c / perf to count futex+select time.
```

---

## 10. What is NOT claimed

- No claim that the C drain is faster than the legacy drain after the
  fix. The C drain adds a full extra transit of the output bytes
  (out memfd → results → parent, vs pread direct), and
  `_validate_c_drain`'s docstring already records a measured 0.7–1.0×
  for the legacy drain at the scales it was measured at. The target is
  **parity with the legacy drain at scale**, not a speedup.
- No claim about physical NUMA. This is a single-node box; the
  multi-node envelope is a separate concern.
- No claim that the notification-pipe change is superseded — only that
  the C drain is the better mechanism *if* it works.
- The retention figures are the committed probe's **current**-RSS
  sampling (`/proc/self/statm`), not `ru_maxrss` deltas. Do not infer
  memory behaviour from `ru_maxrss`.
