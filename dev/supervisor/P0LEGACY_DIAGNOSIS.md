# P0LEGACY Diagnosis — legacy scanner-join watchdog misfire (NOT a deadlock)

Date: 2026-09-29. Tree: `ff99eb7` (`NEW/REFACTOR2.12`).
Reproducer: `forkrun.map(FORKRUN_PAYLOADS["heavy"], heavy_5M.jsonl,
workers=4, order="none", nodes=1, orchestrator=False)`.

## 1. Bite evidence (canonical failing run, watchdog extended to 90s)

```
BITE2 start
BITE2 scanner_pid=1895167 parent=1895165
... (worker traceback below, dumped live via SIGUSR1/faulthandler) ...
forkrun [WARN]: helper 'scanner' (pid 1895167) did not exit within 90.0s (SIGKILL issued); continuing.
BITE2 FAIL RuntimeError: forkrun: scan failed (status 9)
```

With the stock 10s bound the sequence is identical at ~10s. Deterministic across fresh
processes, both orderings, 4 and 28 workers (3/3 this session plus the 2 headline
qualification failures).

## 2. WHERE it hangs (the whole diagnosis)

- **Scanner** (forked child in `lib.fr_py_scan` → `core_scanner_loop`): `S` state,
  `wchan=hrtimer_nanosleep`, ~3% CPU. gdb: `fr_py_scan → usleep → nanosleep`.
  strace fingerprint: tight loop of `clock_nanosleep({tv_nsec=100000})` with NO other
  syscalls — `usleep(100)` at `ring_loadables/forkrun_ring.c:3944`, the publish
  backpressure gate: parks while `local_scan_idx - read_idx >= uma_max_ahead`
  (`= W*64`, min 1024; escape only when no workers are active).
- **Workers** (all 4, `R` @ ~100%): Python stack via SIGUSR1 shows them INSIDE the
  payload — `ml_payload.py:132 _tokenize_and_hash ← process_event_heavy ←
  _forkrun_batch` — i.e. healthy drain + real compute, not stuck.
- **Parent**: asleep in the bounded scanner join (`run.py:3266`).

So nothing is deadlocked and nothing spins pathologically: the pipeline is progressing
exactly as designed, with the scanner parked by backpressure and the workers draining.
The scanner's lifetime under backpressure is ≈ the full run time (heavy-Python 4w ≈
200s+, 28w ≈ 55s). The defect is purely orchestration-side: the legacy parent joins the
scanner FIRST with a 10s deadline (`_HELPER_JOIN_TIMEOUT`, W-REL5-B4), so **any legacy
run with wall time > ~10s is killed**. Survivors (medium/light/C-plugin legs, all ≤8.5s)
pass only because they fit inside the deadline — the threshold is wall-clock, not
workload-specific.

## 3. Why the reactor survives (same engine, same park)

The reactor joins workers first and the scanner as a backstop (`run.py:2083-2090`,
relying on the engine invariant "workers cannot EOF without a clean scanner finish"):
by join time the scanner has necessarily exited, so the bound never fires. The legacy
`_execute_locked` inverts this order (scanner first, `run.py:3259-3281`) — the comment
there cites crash-safety (fail fast on scanner death instead of stranding workers in
claim), which the fix must preserve.

## 4. Timeline = culprit (no bisect needed)

- 2026-09-25/26: path qualifies at ~95k (scanner join unbounded).
- 2026-09-28: `fce8651` W-REL5-B4 bounds ALL helper joins at 10s with SIGKILL.
- 2026-09-29: deterministic failure on any legacy run >10s wall.

Hypothesis verdicts: **H1 selected but refined** — backpressure park is real, but the
fault is the deadline applied to a by-design run-lifetime helper, not a deadlock
(no H1-style drain fix needed; nothing is stuck). **H2/H3 rejected** — no wiring or
missing-equivalence defect; W-REL6's ExecutorSpec lattice is exonerated. **H4 rejected** —
the path passed at full 5M scale pre-B4. Bisection skipped per the order (stack + code +
timeline conclusive); the single candidate commit is `fce8651`.

Engine boundary: the hang is NOT inside `forkrun_ring.c` logic — the engine scanner
behaves identically under the reactor (passes). No engine change needed or proposed.

## 6. Addendum — pre-flight race makes the medium reproducer flaky (pinned)

While building the lock-in, identical pre-fix runs of medium-5M/Python/legacy/2w both
died at 10.5s AND passed in 40s: the batch count itself depends on the pre-flight
CASE-A/B race (worker arrival timing vs line target). CASE A (undisturbed pre-flight)
computes a huge optimal L → few batches → no park → passes; CASE B (early arrival, or
the heavy wide-line byte ceiling) ramps from small L → thousands of batches → park →
watchdog. Heavy is reliably CASE B (wide lines hit `target_pre_bytes`), hence 3/3
deterministic failures there. The lock-in pins `lines=1000` (5000 batches, race
independent): pre-fix FAIL re-verified deterministic with the pin. Lesson for EPYC:
batch counts — and therefore park behavior — are timing-sensitive; compare batch counts
(`blobs=`) alongside rates when runs diverge.

## 5. Fix direction (Phase 2)

Reorder the legacy `_execute_locked` teardown to the reactor pattern: reap workers first
(unbounded — the run IS the wait) while watching the scanner with WNOHANG (fail fast on
nonzero scanner exit, preserving the crash-safety the current order cites), then backstop
`_join_helper_bounded(scan_pid, "scanner")` (already-exited by the invariant — bound
never fires). No new mode branches, no engine diff, B4 bound retained everywhere.
