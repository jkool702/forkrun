# PORT_AUDIT — Differential Frontend Audit (W-PORTAUDIT)

**Work order:** W-PORTAUDIT. **Branch:** `NEW/REFACTOR2.7` (do not push/rebase).
**Engine status:** FROZEN — zero `forkrun_ring.c` / `_shim.c` changes in this audit.
**Target release:** v3.6.0 (Python `0.16.0`). **Date started:** 2026-09-27.
**Benchmark files / PERFORMANCE.md / benchmark sections of DOCS_ALL.md:** OUT OF SCOPE (W-BENCH1).

## 0. Conventions

- Layer taxonomy: **Engine** (shared TU — record, skip), **Bash JIT/codegen**
  (conditional semantic-equivalence check), **Parent orchestration** (HIGH —
  the rewritten layer — the audit set), **Presentation/contract** (medium).
- Status values (exactly one per audit-set item): `PORTED`, `EQUIVALENT`,
  `N/A-BY-DESIGN` (named structural reason required), `MISSING` → `F-PORTn`,
  `UNKNOWN` → differential test per §2.4.
- Matrix is written incrementally; a clean audit with zero new findings is
  a valid outcome.
- Context hygiene: test/benchmark output → files, never streamed;
  commit after every completed step; long legs via `nohup … &`.

## 1. Bash fix inventory (Phase 0)

### 1.1 Engine layer — record, skip (shared TU via `_shim.c` textual include)

| ID | Bash/engine fix (source) | Disposition |
|---|---|---|
| E1 | W-RAW: `FORKRUN_CTX_FLAG_RAW` raw-window delivery (CHANGELOG v3.5.2) | ENGINE — skip (shared TU) |
| E2 | W-STDIN: `-C` + `-s`/`-b` stdin dispatch arm (CHANGELOG v3.5.2) | ENGINE — skip |
| E3 | W-STAGE1: `fr_config_t` boundary load-bearing (CHANGELOG v3.5.2) | ENGINE — skip |
| E4 | F-PY-UMA1: UMA scanner base determinism, `lseek(0)`+base=0 (CHANGELOG v3.6.0 §F-PY-UMA1) | ENGINE — skip; open thread F-PY-UMA1b ("the mover") tracked as P24 |
| E5 | F-NUMA1 engine half: meta-lifetime bound + per-chunk snapshots (CHANGELOG v3.6.0 §F-NUMA1) | ENGINE — skip; parent half is P2 |
| E6 | F31 emit-fallback partial-sendfile resume (CHANGELOG v3.5.1) | ENGINE — skip |
| E7 | v3.5.1 engine batch: seqlock fence pair (D1), NUMA indexer liveness pipe engine side, F30 `ring_init` failure, F15 steal over-claim `goto→continue`, F28 `scan_nth_delim` (`try_simd_scan` untouched) | ENGINE — skip |
| E8 | v3.5.0 engine batch: A1 probe-transfer, A2 fallow-death alarm, A4.8 nodemask double-free, D2 `numa_batch_id`, D3 `cfg_state` order, A4.9 resume snapshot, A4.10 ceiling 512, A4.4 `FD_ORDER_PIPE`, non-EPIPE faults, O_APPEND/sendfile fallback + EPIPE distinction | ENGINE — skip |

### 1.2 Bash JIT / codegen — conditional

| ID | Concern | Action |
|---|---|---|
| J1 | Bash JIT / partial-eval codegen, quoting modes (`-U` forces AST, disables `-X`) | Check semantic equivalents only; Python has no JIT — N/A-BY-DESIGN expected with named reason |
| J2 | `-X` `posix_spawnp` fast path vs Python v1 C spawn loop (`fr_py_exec_spawn`) | Semantic-equivalence check (perf, not correctness) |

### 1.3 Parent orchestration — THE AUDIT SET

| ID | Bash behavior / fix (source) | Python home (suspect) | Status |
|---|---|---|---|
| P1 | Workers cover every NUMA node, `workers≥nodes` enforced w/ UserWarning (F-NUMA2/W-NUMA2; RESILIENCE §7.3.1; INVARIANTS §18; `run.py:_resolve_workers_numa`) | `run.py:650`, `_numa.py:187` | PORTED (reference; lock-in `test_numa_bump.py`) |
| P2 | Per-node drain audit before declaring NUMA completion, coverage-dependent disposition raise-vs-warn (F-NUMA1; EOF_PROTOCOL §7; `_numa_drain_audit`) | `run.py:_execute_numa_locked`, `_execute_numa_stream` | PORTED (reference; lock-in `test_numa_drain_guard.py`; overshoot benign `read>write` never fires) |
| P3 | Exit-code taxonomy: 130 SIGINT-foreground-only, 138 SIGUSR1-under-PREEMPT_MODE, 143, 3 poison, 42, 200/254, `&0xFF` truncation (primer §3 affirmed; D6) | `_reactor.py`, `_worker.py` (`os._exit` codes), `run.py` teardown | UNKNOWN — seed target #2 |
| P4 | Signal choreography: SIGTERM/SIGPIPE/SIGHUP/SIGUSR1+PREEMPT_MODE via reactor abort path; trapped signal never downgraded by concurrent SIGPIPE (v3.5.0 highlights) | `_reactor.py`, `run.py` abort paths | UNKNOWN — seed target #4 |
| P5 | fd hygiene at EVERY fork site: targeted closes per site (death-pipe ends, `FD_TRAP_ACK_W`, `fd_fallow_w`; W-STDIN feeder scrub) vs blanket scrub | `_fd_scrub.py`, `run.py` fork sites (~15× `os.fork`), `_reactor.py:198,994,1025`, `_worker.py:725,794` | UNKNOWN — seed target #6 |
| P6 | D8-class stderr persistence: no path durably redirects/closes fd 2; daemonized helpers inherit good fds | `_fd_scrub.py` (keeps 0/1/2), `_reactor.py`, `run.py` drain/orderer children | UNKNOWN — seed target #3 |
| P7 | INDEXER_DEATH abort-aware classification: `ring_abort_reason` checked before own `ring_abort`; no `|| ring_abort` in indexer subshell; no spurious FATAL on clean `| head` abort (D6; LA4) | `_reactor.py` death-pipe handlers, scanner/indexer child mains | UNKNOWN |
| P8 | Trap-ACK 3s grace + catastrophic declaration; no-grace RACE abort (RESILIENCE §2.3/§4.1) | `_reactor.py:428,715,896` | UNKNOWN |
| P9 | Escrow drain + fd teardown: no orphaned packets or held fds after run teardown; escrow TATAS + continuous drain (EOF §4) | `run.py:_teardown_stream`, `_reactor.py`, engine escrow pipes | UNKNOWN — seed target #9 |
| P10 | Poison threshold + exit-3 + `FORKRUN_RETRY_LIMIT` semantics (`-E` analogue: retry/skip/fail-fast; 0=exactly-once, <0=unbounded; RESILIENCE §3/§5) | `_worker.py` escrow retry, `run.py` poison summary, `_api.py:on_error` | UNKNOWN |
| P11 | Order-pipe backpressure 4KiB hydraulic loop (H3); Python signal pipe 1MB vs ack pipe 4KB (`_pipes.py`) | `_pipes.py`, `run.py:_drain_records`, `_reassembly.py` | UNKNOWN |
| P12 | Checkpoint atomic publish (tmp→fsync→chmod 600→rename); no spurious checkpoints on early fatal (v3.5.0 W4-adjacent; W-PY22) | `_resume.py:_write_file_atomic`, `checkpoint_on_abort` | UNKNOWN |
| P13 | Checkpoint filename quoting: spaces/specials write the correct file (v3.5.0 W4) | `_api.py:_validate_resume_path`, `_resume.py:resolve_checkpoint_dest` | UNKNOWN |
| P14 | Permission gate `8#022` (was `0o022` silent-never-fire) + `FORKRUN_TRUST_RESUME` denylist (v3.5.0; F29) | `_checkpoint.py:check_checkpoint_safety`, `_resume.py:resume_begin` | UNKNOWN |
| P15 | Resume consent-gate semantics (F29/D10): preview extracted values (never raw text); PATH-dead `mktemp -ud` restricted shells; quoteless `-c`; shape filter + `declare -p` re-render + denylist; token secrecy is NOT a property | `_checkpoint.py`, `_resume.py` (Python: parse+safety, no eval of hostile content pre-consent?) | UNKNOWN — seed target #7 |
| P16 | Stale horizon fail-loud + complete-stream clean no-op resume (v3.5.0 resume) | `_checkpoint.py:parse_checkpoint`, `_resume.py` | UNKNOWN |
| P17 | Topology validation: `--nodes=@N` ceiling + bounded-digit `@*` regex, early-fatal clean `[ERROR]` no checkpoint (F30) | `_numa.py`, `_api.py` nodes validation | UNKNOWN |
| P18 | `-L` validation: ranges/zero/negatives rejected; `-L`+`-b` override warning line-wins (v3.5.0 W3) | `_api.py` lines/bytes validation | UNKNOWN |
| P19 | Empty-input behavior: no command run on empty input (v3.5.0 W5) | `run.py` spill/scan paths, `_worker.py` EOF sentinel skip | UNKNOWN |
| P20 | `-E` appendage explicit init (v3.5.0 W1) | `_api.py:on_error` default handling | UNKNOWN |
| P21 | EOF 3-condition adherence (C1→C2→C3 strict order, `continue`-not-`break`) on EVERY Python completion/exit path (EOF_PROTOCOL §§1–6) | `run.py:_drain_records`, `_teardown_stream`, `_reactor.py:reactor_loop`, stream abandon/EPIPE paths | UNKNOWN |
| P22 | Fork ordering: indexer write-ends closed in parent before scanner/worker forks (else death masked) (v3.5.1 indexer work) | `run.py` NUMA fork sequence, `_reactor.py` spawn sites | UNKNOWN |
| P23 | PID-recycling no-kill rule: `waitpid` ECHILD ⇒ no `kill()` (primer §4.1) | `_resume.py:_waitpid_bounded`, `run.py` reaps, `_reactor.py` reaps | UNKNOWN |
| P24 | The mover (F-PY-UMA1b): positional ops (`read`/`lseek`/offset-less `sendfile`/`splice`) on the ingress memfd in BOTH frontends | `run.py` spill/scan (`fr_py_copy_range` explicit offsets; `pread`/`pwrite` fallback), `frun.bash` ingest | UNKNOWN — seed target #5 |
| P25 | Hostile-PATH handling in spawn/plugin subprocess paths (D10/PATH) | `_spawn.py` (`subprocess.run` + v1 `fr_py_exec_spawn`/`posix_spawnp`), `_plugin.py` dlopen | UNKNOWN — seed target #1 |
| P26 | Version/substrate coherence: wheel-vs-local engine drift; `-V`/VERSION/META/pins/twins; `release_check.py` gaps | `__init__.py:__engine_version__`, `_bindings.py:find_substrate/load`, `release_check.py` | UNKNOWN — seed target #8 |
| P27 | Degenerate-input edge parity: empty stdin, single line, no trailing newline, NUL-laden, huge single record (Bash T/M-series vs Python tests) | `python/tests/` vs `UNIT_TESTS/` edge lists | UNKNOWN — seed target #10 |
| P28 | Delivery semantics: ordered/buffered EXACTLY-ONCE (ftruncate revert + byte-coordinate resume) vs realtime `-u` AT-LEAST-ONCE (RESILIENCE §5.2) | `run.py` map/stream collect paths; Python has no `-u` realtime path? | UNKNOWN |
| P29 | Fallow punch-behind-acked-horizon (bounded RSS, coordinates preserved) | `run.py` streaming ingest (`fr_py_fallow_loop`), materialized (no fallow — observation not contract) | UNKNOWN |
| P30 | Pre-consent process-signal effects documented residual (P1 residual #5, v3.5.2 docs-only) | Python checkpoint parse path (no sandbox exec — confirm no signal surface) | UNKNOWN |

### 1.4 Presentation / contract

| ID | Concern | Status |
|---|---|---|
| C1 | Flag/help-text parity (`--nodes`, `--help` `-C` line, `-L`/`-b` wording) | PENDING |
| C2 | Stderr message shapes (`[WARN]` poison summary, checkpoint hints — D8-adjacent) | PENDING |

## 2. Seed-target cross-reference (work order §2.3 — must go beyond)

1. D10/PATH → P25. 2. Exit codes → P3. 3. stderr → P6. 4. Signals → P4
   (+ operator-HUP→checkpoint: Bash-side; Python equivalent or honest
   "not supported"?). 5. Mover → P24. 6. fd inheritance → P5.
7. Sandbox semantics → P15. 8. Version coherence → P26. 9. Escrow/fd
   teardown → P9. 10. Degenerate inputs → P27.

## 3. Findings ledger

| Finding | Audit item | Severity | Disposition |
|---|---|---|---|
| *(none yet — matrix in progress)* | | | |

## 4. Coverage statement (draft — final in completion report)

- Inventoried: CHANGELOG v3.5.0–v3.6.0 behavioral entries + primer §3
  ledger (D1–D10, F-series) + work-order seed list. `git log -p frun.bash`
  archaeology (30-min timebox) PENDING.
- Skipped with reason: Engine-layer items E1–E8 (shared TU — carried
  automatically); benchmark files/results + PERFORMANCE.md + benchmark
  DOCS_ALL sections (W-BENCH1 territory); residual known flakes
  (C-drain framing header, reactor-ingest multiset, T10b, M1a).
- Matrix status: P1–P2 PORTED (reference); P3–P30 + C1–C2 PENDING audit.

## 5. Verification log

| Gate | Status |
|---|---|
| Full Python suite green ×3 | NOT RUN |
| Targeted tests green ×10 (touched paths) | NOT RUN |
| `make -f Makefile.substrate check` | NOT RUN |
| Engine untouched (`git diff -- forkrun_ring.c python/forkrun/_shim.c` empty) | HELD (no code changes yet) |
| New findings carry changelog + lock-in test | N/A yet |
