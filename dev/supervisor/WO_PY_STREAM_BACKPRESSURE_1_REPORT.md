# WO-PY-STREAM-BACKPRESSURE-1 — implementation report

**Branch:** `NEW/REFACTOR4.4`
**Start commit:** `8a86ef8f` (the work order named `8c016b68` as the
baseline; the branch had moved two commits — `f50abcdf`, the reactor's
poison-notification fix, and `8a86ef8f`, a session-log archive. Both were
pre-existing user work and were preserved, not reverted.)
**Final commit:** see §8

**Subject:** Bound the Python streaming read-ahead with a small
completion-notification pipe; resolve the `FR_PY_ERR_NOTIFY` (`-4`)
mismatch in the worker.

---

## 1. Verdict

**GO for the plain supervision path, NO BENEFIT on the default reactor
path, and no measurable cost on either.**

- The stream notification pipe now asks for **4 KB** (256 outstanding
  completions) instead of 1 MB (65536) on the five `stream()`-reachable
  executors. `map()`/`run()` are unchanged.
- On **plain supervision** (`orchestrator=False`) this cuts peak
  retention **24–65 %** with throughput equal or better and first-result
  latency unchanged.
- On the **default reactor path** it changes retention by **−0.4 % to
  +3.7 %** — no benefit. Throughput and latency are equal or better.
- It is **not** a byte bound, and it does **not** close TD-13.
- The `-4` mismatch is fixed and the fix is proven by a mutation check.

---

## 2. Changed files

| File | Change |
|---|---|
| `python/forkrun/_pipes.py` | `STREAM_NOTIFY_PIPE_SIZE = 4096`, `make_stream_notify_pipe()`, `stream_notify_pipe_size()`, `last_stream_notify_capacity()`; module docstring rewritten (the old one justified the 1 MB pipe) |
| `python/forkrun/run.py` | the 5 `stream()`-reachable executors use the small pipe; the stale "1MB signal pipe" comment replaced |
| `python/forkrun/_worker.py` | `-4` (`FR_PY_ERR_NOTIFY`) exits the worker instead of entering the `on_error` retry ladder |
| `python/forkrun/_reassembly.py` | stale comment ("caps outstanding completions at 4096") corrected |
| `python/tests/test_streaming_backpressure.py` | **new** — 25 tests |
| `python/tests/_streaming_rss_probe.py` | reports the actual pipe capacity, first-result latency, wall time, throughput; adds `--c-drain` |
| `DOCS/CHANGELOG.md` | new Unreleased section |
| `DOCS/DOCS_ALL.md` | **regenerated** with `tools/gen_docs_all.py` (generated file; never hand-edited) |
| `dev/supervisor/TECH_DEBT_REGISTER.md` | TD-13 updated: partial mitigation, the cliff, the caveats, and the C-drain finding |
| `dev/supervisor/PORT_AUDIT.md` | P11 row updated |
| `MEMORY.md` | engineering-log entry |

**Frozen files untouched** — `git diff --stat forkrun_ring.c
forkrun_substrate.h substratestubs.c` is empty, and their last-touching
commit is not HEAD.

---

## 3. Notification-pipe inventory

`make_pipe()` call sites in `python/forkrun/run.py` (the only
`make_pipe` caller in the package):

| Line | Executor | Reached from | Pipe role | Capacity requested | Capacity measured |
|---|---|---|---|---|---|
| 349 | `_fork_drain` | `_fork_drain` | C-drain **results** pipe (map/run: memfd; stream: pipe) | 1 MiB | 1 MiB — **unchanged by design** (separate backpressure stage) |
| 6218 | `_execute_streaming` | `stream()`, `stream()` splice | worker-completion notification | **4 KiB** | **4096** |
| 6550 | `_execute_ingest_stream` | `stream()` streaming input, splice | worker-completion notification | **4 KiB** | **4096** |
| 8981 | `_execute_streaming_reactor` | `stream()` reactor, splice | worker-completion notification | **4 KiB** | **4096** |
| 10089 | `_execute_ingest_stream_reactor` | `stream()` reactor + streaming input | worker-completion notification | **4 KiB** | **4096** |
| 11900 | `_execute_numa_stream` | `stream()` NUMA | worker-completion notification | **4 KiB** | **4096** |
| 7087 | `_execute_ingest_locked` | `map()`/`run()` only | worker-completion notification | 1 MiB | 1 MiB — **unchanged** |
| 7527 | `_execute_locked` | `map()`/`run()` only | worker-completion notification | 1 MiB | 1 MiB — **unchanged** |
| 8351 | `_execute_reactor_locked` | `map()`/`run()` only | worker-completion notification | 1 MiB | 1 MiB — **unchanged** |
| 9552 | `_execute_ingest_reactor_locked` | `map()`/`run()` only | worker-completion notification | 1 MiB | 1 MiB — **unchanged** |
| 11371 | `_execute_numa_locked` | `map()`/`run()` only | worker-completion notification | 1 MiB | 1 MiB — **unchanged** |

Deliberately **not** touched (all `os.pipe()`, 64 KiB default, and none of
them a worker-completion notification): order pipes, trap-ACK pipes,
fallow pipes, spawn pipes, death pipes, ingest-death pipes.
`make_pipe()`'s general default stays 1 MiB.

**The NUMA row is a logical-`@N` envelope only.** This host has one NUMA
node; no physical multi-node claim is made anywhere in this work.

---

## 4. The `-4` contract fix

`fr_py_notify_committed()` defines `FR_PY_ERR_NOTIFY` (`-4`) as
**committed but not notified** — "NEVER a plain retry". The Python worker
loop special-cased `-2` and `-3` only, so `-4` fell into the generic
output-error path and reached the `on_error` ladder's **retry** branch,
which re-arms the batch for a same-process re-claim — a retry of work
whose commit had already happened. The shipped C worker loop treats
*any* nonzero `fr_py_complete` rc as fatal; the Python loop now does too.

**The fix is observable and was mutation-checked.** The escrow deposit
is reached from two places, and the caller's frame separates them
exactly:

| | which function deposited the escrow | failure ladder entered? |
|---|---|---|
| fix present | `_escrow_deposit_exit_loud` (exit path) | **no** |
| fix reverted | `_deposit_or_loud_skip` (the retry branch) | **yes** |

Reverting the fix fails `test_notify_failure_does_not_enter_the_failure_ladder`
and nothing else.

**A near-vacuous test, and what it took to make it real.** The obvious
assertion — "no duplicate batch execution" — is **vacuous**: with the
fix reverted there is still no duplicate, because the engine does not
re-offer an already-committed batch. The test that replaced it asserts
the contract directly (the failure ladder is not entered), plus no
duplicate and no stuck process, and it fails when the fix is removed.

**Measured consequence, stated not hidden.** A worker that exits on `-4`
makes the parent respawn it, and the per-process fault hook fires again
in the new process; the run can therefore reach the respawn cap and fail
**closed** (`ForkrunWorkerFailure`) rather than completing. That is the
correct behaviour for a genuinely lost notification (the parent is gone,
`EPIPE`), but it means an *injected* fault ends the run. The test
asserts "terminated, did not hang", not "succeeded", and says so.

---

## 5. Test results

`python3 -m unittest test_streaming_backpressure` — **25 tests, OK**.

| area | covered |
|---|---|
| capacity | the requested size is the named constant; the created pipe grants it (measured with `F_GETPIPE_SZ`); plain, reactor, ordered-reactor and streaming-ingest executors all create a 4 KiB pipe; `map()` creates none; the measurement override works, falls back on garbage, and the default is unambiguous when absent |
| output correctness | fast and slow consumers, `order="none"` and `order="index"`, `orchestrator=False` and `True`, regular-file and FIFO input, `c_drain=False` and `True`, amplifying payload |
| abandonment | generator closed mid-stream, and mid-stream after a slow consumer; teardown bounded; no zombies |
| `-4` | the failure ladder is not entered; no duplicate batch execution; no stuck process |

**Two comparison rules had to be learned the hard way, and the tests
encode them:**

- `order="none"` delivers the same **lines** in completion order, not
  the file's byte order — so it is compared as a line multiset.
  `order="index"` is byte-exact against the file.
- The amplifying payload repeats the **blob**, so within a batch the
  lines interleave (`a,b,a,b,…`); the stable statement is the multiset
  (each line five times) and the total byte count, not a byte string.

**Mutation checks (both required by the repo's own rule that a
validation must be able to fail):**

| mutation | result |
|---|---|
| `-4` fix reverted | exactly 1 test fails (`..._does_not_enter_the_failure_ladder`) |
| pipe capacity reverted to 1 MiB | 4 tests fail (the capacity assertions) |

`test_stage0_notify_failure.py` (the pre-existing cleanroom-path test
for the same contract) still passes.

---

## 6. Measurements

All figures: `_streaming_rss_probe.py`, amp 5, 4 workers, 1 node,
`--delay` is the consumer's per-record sleep. The probe samples **current**
RSS (`/proc/self/statm`) inside the consumer loop; `ru_maxrss` deltas
are not used. Arms alternate A,B / B,A per rep. Medians over 4–5 reps.
The **actual** pipe capacity is recorded per run (`F_GETPIPE_SZ`):
`A_1MiB` → 1048576, `B_4KiB` → 4096.

### 6.1 Capacity sweep — 4 M lines (977 batches), 4 reps, medians

| path | metric | 1 MiB | 64 KiB | 16 KiB | **4 KiB** |
|---|---|---|---|---|---|
| plain, `order="index"` | peak retention (KB) | 240898 | 239626 | 243936 | **83936** |
| plain, `order="none"` | peak retention (KB) | 119678 | 120332 | 124456 | **59528** |
| plain, `order="index"` | throughput (rec/s) | 3376 | 3445 | 3154 | **4596** |
| plain, `order="none"` | throughput (rec/s) | 4620 | 4371 | 4652 | **5360** |
| reactor, `order="index"` | peak retention (KB) | 251266 | 250754 | 250794 | 250332 |
| reactor, `order="none"` | peak retention (KB) | 250984 | 250996 | 250976 | 256932 |
| reactor, `order="index"` | throughput (rec/s) | 2080 | 2760 | 2814 | 2784 |
| reactor, `order="none"` | throughput (rec/s) | 3386 | 3433 | 3341 | 3865 |

Slow-consumer rows (delay 0.01) are consumer-bound and identical across
every arm: 94.4–96.4 rec/s for all four capacities. The consumer sleeps
0.01 s × 977 records = 9.77 s, so the run is ~10.1 s regardless of the
pipe.

### 6.2 The threshold is a cliff, and it is arithmetic

A pipe of S bytes holds S/16 notifications and only binds if that is
fewer than the outstanding completions. This run produces **977**
batches, so **16 KiB (1024 slots) can hold every notification of the run
and never blocks** — which is exactly why 1 MiB, 64 KiB and 16 KiB
measure identically. Only 4 KiB (256 slots) is below the read-ahead and
applies backpressure. **A capacity not below the run's
outstanding-notification count does nothing at all.**

### 6.3 A near-miss recorded, because it nearly produced a wrong conclusion

An earlier 5-rep A/B showed the small pipe *reducing* throughput 33 % in
one cell, and it was reported as a fast-consumer regression. With 4 reps
and four arms it **reversed**: 1 MiB is the *slowest* arm. The cell's
first-result latency is **bimodal in every arm** (0.014 s or 0.15–0.40 s
— the reactor's poll quanta), and 5-rep medians landed on opposite sides
of that bimodality in the two arms. A 33 % "regression" that reverses
with more reps and more arms was a bimodality artifact.

### 6.4 C drain, separately

`c_drain=True` uses a **separate** results pipe (unchanged, 1 MiB). It
is **16–19× slower** than the legacy drain on the stream path above
~64 blobs, and this is **pre-existing** (98.5 s at 1 MiB vs 98.3 s at
4 KiB). Root cause, instrumented: the pump reads 65536 bytes per call
and returns `None` whenever that does not complete a blob, which ends
the reactor's `DRAIN_BURST`, which leaves `drained_last` False, which
makes the reactor's next `select()` wait the **full `poll_timeout`
(0.1 s)**.

| 250 k lines | select calls | total time waiting in `select()` | calls over 50 ms |
|---|---|---|---|
| `c_drain=True` | 162 | **9.72 s of a 10.43 s run (93 %)** | 97 |
| legacy drain | **5** | 0.01 s | 0 |

The reactor's own comment names the cap: *"otherwise throughput caps at
~10 blobs/s (one yield per 100ms idle select)"*. Below ~64 blobs
(`DRAIN_BURST`) the C drain matches the legacy drain (1.01–1.21×) —
likely where the "0.7–1.0×" figure in `_validate_c_drain` came from.

**But the C drain's peak retention is flat at ~3.5 MB regardless of
scale, where the legacy drain's grows linearly to 138 MB:**

| output | legacy drain | C drain |
|---|---|---|
| 5.4 MB | 8.3 MB | 3.0 MB |
| 29.4 MB | 37.5 MB | 3.5 MB |
| 124.4 MB | 138.3 MB | **3.6 MB** |

So the C drain is the **right** mechanism for the default path's memory
problem and is currently unusable because of a 100 ms poll interval.
Fixing it is a **separate work order** (this one forbids redesigning the
C drain and the output transport), and it may make this change
unnecessary on the default path.

---

## 7. Limitations — what is NOT claimed

- **Not a hard byte bound.** A single batch can still generate large
  output (the legacy drain's quantum holds one read's worth of output in
  a Python list for the whole yield loop).
- **The bound is on completions, not bytes**: 256 completions of a 4 MB
  batch is still 1 GB in flight.
- **`order="index"` can still buffer behind a poisoned or skipped head**,
  by design; the reassembly buffer is downstream of the notification
  pipe and is unaffected by its size.
- **No benefit on the default reactor path** (§1, §6.1).
- **The lever is corpus-sensitive** (§6.2): a capacity not below the
  run's outstanding-notification count does nothing.
- **No physical NUMA validation.** The NUMA row in §3 is a logical-`@N`
  envelope on a single-node host.
- **Not a claim that the reactor's own retention is fixed.** It is not.
- **The `-4` fix does not make a lost notification deliverable.** The
  in-process parent has no synthetic recovery wakeup (the C cleanroom
  launcher has one); delivery after a lost notification depends on a
  later notification carrying a frontier that covers the committed bytes.

---

## 8. Commits, gates, and reproduction

See the final section of this document after the gates have run.

**Reproduction commands** (committed probes, no scratch):

```bash
# capacity A/B, actual capacity recorded per run
FORKRUN_STREAM_NOTIFY_PIPE_SIZE=1048576 \
  python3 python/tests/_streaming_rss_probe.py --lines 4000000 --amp 5 \
    --delay 0.01 --order none --orchestrator 0
python3 python/tests/_streaming_rss_probe.py --lines 4000000 --amp 5 \
  --delay 0.01 --order none --orchestrator 0

# C drain vs legacy, across scale
python3 python/tests/_streaming_rss_probe.py --lines 250000 --amp 5 \
  --delay 0.01 --orchestrator 1 --c-drain

# focused tests
cd python/tests && python3 -m unittest test_streaming_backpressure
```
