# MOVER_REPORT — F-PY-UMA1b Investigation (W-MOVER)

**Disposition: ENGINE-RESIDENT → invariant closure** (INVARIANTS.md §20).
**Engine diff: empty. Fix requiring engine changes: halted per red lines, reported in §6.**

## 1. Background

F-PY-UMA1 fixed the UMA scanner seeding its base from `lseek(SEEK_CUR)` on
the fork-shared ingress memfd (offsets 72–10120 observed, ~20% of runs;
fix: unconditional base 0, +11/−1). Post-fix probes showed the underlying
position movement still occurring — the unidentified actor (F-PY-UMA1b).
Known-clean at handover: spill `pwrite` discipline, `fr_py_copy_range`
explicit offsets, fallow (hole-punch, not positional), NUMA positional
audit, reverted F-PY-UMA1 instrumentation.

## 2. Phase 0 — Position sentry (env-gated, since reverted)

Parent-side `FORKRUN_DIAG_MOVER=1` snapshots (`os.lseek(fd,0,SEEK_CUR)` —
a query moves nothing) at C0 spill-done / C1 pre-scan-fork / C2
post-scan-fork (4 materialized spill sites) + C3 post-worker-fork /
C4 post-worker-join / C5 pre-destroy (`_execute_locked`), later extended
with fd-layout snapshots, live-leftover checks, and the ingress fd
number, then minimized again (see §5) and finally reverted (diagnostic
scaffolding; the contract test replaces it).

Results across ~10 full-suite runs (each 242 C3 opportunities):
- **C0**: nonzero ~97% (spill residue — sequential `os.write`/`fr_py_spill_sequential`
  leave offset=EOF; expected, pre-reset).
- **C1/C2: always 0** (1000+ samples — the pre-fork reset holds; matches
  the F-PY-UMA1 "parent verified 0" forensics).
- **C3: nonzero ~3% of runs** (7, 7, 5, 5, 7, 8, 9 events across firing runs;
  values 64–20320, **all multiples of 8**).
- **C4/C5**: persist the C3 values (no further resets by design).
- Firing interval: **C2→C3 (worker-fork window)**, with accumulation
  continuing through execution.

## 3. Phase 1 — Identification

### 3.1 Code audit (all clean)

Every steady-state reader verified explicit-offset or fd-disjoint:
spill kernel/`pread`/`pwrite` paths (sequential residue pre-reset only);
`fr_py_scan`/`core_scanner_loop` (single `pread`, pre-flight `pread`);
`do_tokenize` (`pread`); v1 spawn/plugin loops (`splice`/`sendfile` with
explicit offset pointers); ml plugins (`pread(fd_in)`); Python workers
(`mmap` + `fstat` only — no `read`/`pread`/`lseek` on ingress anywhere in
`_worker.py`); reactor/drain/orderer (scrubbed or own fds); checkpoint/
topology/test files (own fds); `fr_py_ingest_done` (pure atomic store);
`worker_coredump_startup` (own `/proc` files + rlimits). Dead code with
positional reads (`ring_fetcher_main`) confirmed unreachable (F24;
zero references in `frun.bash`/twins/Python).

### 3.2 LD_PRELOAD syscall trace (the breakthrough)

Custom interposer (`/tmp/mover_trace.c`, repo-external): libc `read`,
`write`, `pread`, `pwrite`, `sendfile`, `splice`, `copy_file_range`,
`lseek`/`lseek64`, `memfd_create`; logs only memfd targets (readlink);
per-line pid/ppid/comm/fd/args/return/caller-PC/monotonic-ts; later
+ self-identifying `/proc` maps dump (ASLR-proof resolution) and
per-event `evfd_data_arr` capture via `/proc/self/mem` + `nm` math.
Two tracer bugs found and fixed during the hunt (both documented
because they corrupted evidence runs, never the product):
- **fd-reuse hijack**: the log fd, closed by worker `scrub_fds`, was
  reused by memfds — trace text landed inside test memfds
  (test_zero_copy failures). Fixed with dev/ino guard + reopen.
- **`lseek` blind spot**: CPython and the engine resolve `lseek64`'s
  PLT slot, not `lseek`'s — zero lseek lines until `lseek64` was
  interposed. (This initially hid the SET-vs-read distinction.)

Findings (4+ full-suite traced runs, 50–180K memfd lines each):
- **8-byte positional `read()`s on forkrun_ingress memfds, 40K–1.5M
  per run**, return-PC resolved (two independent ASLR slides, same
  file offset `+0x13602`) into `do_lockfree_claim`, disassembled to
  `mov $0x8; call read@plt` — the eventfd-drain
  `sys_read(evfd_data_arr[my_numa_node], &v, 8)` (forkrun_ring.c:6015/6060).
- Mostly `ret=0` (EOF-spin: memfds never EAGAIN, so starved workers
  spin at CPU speed until work appears — bounded, invisible).
  ~178 advancing `ret=8` reads per firing run (~1–2KB), matching the
  C3 magnitudes exactly.
- Per-event array capture: **`evfd_data_arr[slot]` names the ingress
  fd in the reading children** while the parent layout verifies
  pristine (eventfds low, ingress high) — the slot↔ingress aliasing.
- `lseek64` audit over a full run: **zero anomalous SETs** (all resets
  to 0 or CUR queries). `write`/`splice`/`sendfile` on ingress: only
  spill (pre-reset) and next-run spillover in wide windows.
- Reader pids cluster as forked sibling pairs (`python3`, non-exec'd),
  consistent with workers.

### 3.3 Ruled out (with method)

- Spill residue (C1 always 0 post-reset).
- Scanner/pre-flight/tokenize/C-loops/plugins (all pread/explicit).
- Python workers (mmap/fstat only — no fd reads at all).
- Harness/test files (own descriptions; distinct memfd names).
- Dead `ring_fetcher_main` (unreachable).
- NUMA ingest probe (source-side; NUMA scanners never query).
- Leaked long-lived workers (no >5s processes except legitimate
  nested packaging drivers).
- Cyclic-GC-delayed teardown (events persist with `gc.disable()`).
- fd-pressure layouts (0/160 in forced high/low reproducer).
- OOB indexing (no bad-index evidence; neighbors don't match).
- Re-init without destroy (discipline verified: destroy always runs;
  re-init path is consistent by construction).

### 3.4 Residual thread (escalated, not guessed)

The aliasing *origin* — why `evfd_data_arr[slot]` holds the ingress
number in those forked children while the parent verifies pristine —
is **not identified**. Parent-side array reads correct mid-run
(`/proc/self/mem` probe); init/destroy discipline verified sound
(all _execute paths init→spill→fork→join→destroy; re-init path
consistent); no test/harness fd closes by number found. Leading
unconfirmed shapes: stale slot inherited across an undetected
teardown gap; heap-adjacency coincidence (weak). The movement
mechanism itself is fully proven; the origin needs either an
engine-side fd-identity check (sees both sides) or a luckier
tracer run, both beyond this order's red lines.

## 4. Phase 2 — Closure

**Invariant closure** (order §4, fully legitimate): INVARIANTS.md §20
(+ DOCS_ALL mirror): the ingress file offset is undefined and must
never be read or relied upon; explicit offsets / mmap windows only;
one-line pointers at both ingress creation sites. The already-shipped
base-0 fix is promoted from workaround to contract — it holds
*regardless of what moves the offset*, which covers both the named
mechanism and the residual origin thread.

**Halted engine fix (reported, not implemented):** validate fd identity
in the claim path (e.g., record `st_dev`/`st_ino` of eventfds at init
and re-validate before the drain read; or a creation-generation
counter) — owner decision, needs engine changes.

**Lock-in** (`python/tests/test_mover.py`, same commit): dirtied
mid-line offset at scanner entry → still byte-exact (python +
spawn); ten sequential in-process maps head-exact (F-PY-UMA1
forensic-loop shape). 10/10 green.

## 5. Verification (W-MOVER gates §5)

- Invariant test ×10: PASS (10/10).
- Forensic loop: 10 sequential maps × 10 runs = 100 sequential maps,
  all head-exact (inside the lock-in runs above).
- Full suite ×3 + `make check`: in §7 legs 1/4 below.
- Engine diff: empty (`forkrun_ring.c`, `forkrun_substrate.h`,
  `substratestubs.c` untouched; `_shim.c` untouched — the D-PORT2
  accessor predates this order).
- Perf: syscall-neutral (no product code changed; sentry reverted).

## 6. Incidents during the hunt (all dispositioned)

1. Tracer fd-reuse hijack (above) — fixed, evidence runs re-taken.
2. Tracer `lseek` blind spot (above) — fixed.
3. Tracer/sentry timing perturbation on kill-window/parity tests
   (`test_three_workers_killed`, `test_c_drain_identical`,
   `test_numa_recovery` once, `test_release_check_passes` cascade):
   each green untraced/un-gated (3–6/6); dispositioned as
   measurement perturbation, not product.
4. **Observer effect (major finding):** heavy instrumentation
   (tracer, bloated sentry) *suppresses* the race — 6 consecutive
   quiet runs vs 3/3 firing sentry-only runs. Itself evidence of a
   tight early-run starvation-timing window, consistent with the
   spin-loop dynamics (§3.2). Minimal sentry restored firing
   immediately (9 events).

## 7. Evidence locations

- Sentry/trace logs: `/tmp/mover_*.log` (ephemeral; this report is
  the durable record).
- Tracer source: `/tmp/mover_trace.c` (+ `/tmp/mover_trace.so` builds).
- Reproducers: `/tmp/mover_repro*.py`, `/tmp/mover_probe.py`,
  `/tmp/mover_catch*.py`, `/tmp/mover_heap.py` (all negative-result
  recorded above).
- Lock-in: `python/tests/test_mover.py`.
