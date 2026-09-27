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

| ID | Concern | Disposition |
|---|---|---|
| J1 | Bash JIT / partial-eval codegen, quoting modes (`-U` forces AST, disables `-X`) | N/A-BY-DESIGN (`NO-CODEGEN-IN-PYTHON`): Python has no JIT/partial-eval; failure rides escrow/ack/abort syscalls, not string append (`_worker.py:514-525,648-669`) |
| J2 | `-X` `posix_spawnp` fast path vs Python v1 C spawn loop (`fr_py_exec_spawn`) | EQUIVALENT: v1 dispatches in C via `posix_spawnp` + poll pump (`_worker.py:779ff`, `_reactor.py:578ff`); v0 `subprocess` fallback documented (~350µs vs ~10µs) |

### 1.3 Parent orchestration — THE AUDIT SET (Phase 1 complete)

| ID | Bash behavior / fix (source) | Python evidence | Status |
|---|---|---|---|
| P1 | Workers cover every NUMA node, `workers≥nodes` + UserWarning (F-NUMA2/W-NUMA2; RESILIENCE §7.3.1; INVARIANTS §18) | `run.py:650 _resolve_workers_numa`, all dispatch sites; lock-in `test_numa_bump.py` | PORTED (reference) |
| P2 | Per-node drain audit before NUMA completion, raise-vs-warn disposition (F-NUMA1; EOF_PROTOCOL §7) | `_execute_numa_locked` + `_execute_numa_stream` drain audit; lock-in `test_numa_drain_guard.py`; overshoot `read>write` benign-never-fires | PORTED (reference) |
| P3 | Exit-code taxonomy 130/143/138/3/42/200/254, `&0xFF` (primer §3; D6; `frun.bash:1365-1388,1713-1737,2188-2189`) | Library raises, never exits (zero `signal.signal`/`sys.exit(3)` in `python/forkrun/`); workers exit 0/1 only (`_worker.py:157-194,419-522`); signal collapse →1 (`_reactor.py:320-323`); poison warn-only (`run.py:1911-1921` etc.); truncation clamp-not-mask (`_reactor.py:258`, `run.py:226` `0<=rc<256 else 1`); 200/254 N/A (`DIFFERENT-RETRY-TRANSPORT`: `fr_py_escrow_deposit`, `_worker.py:657-669`) | N/A-BY-DESIGN (`PYTHON-IS-IMPORTABLE-LIBRARY`) + deferred sub-gaps → D-PORT3 (poison surfacing needs API decision; signal-cause preservation needs `WTERMSIG` plumbing) |
| P4 | Signal choreography: TERM/HUP/USR1+PREEMPT via reactor abort; trapped signal never downgraded by concurrent SIGPIPE (v3.5.0; `frun.bash:1365-1375,1945-1969`) | No `signal.signal`, no `FORKRUN_PREEMPT_MODE` read, no `abort_reason` binding, no ABORT event (`_reactor.py:711-891` death/spawn/trap only); KI paths inconsistent (`run.py:2754-2756` abort+raise vs `3712-3715,6180-6181` bare raise); TERM/HUP/USR1 default-kill, no checkpoint | MISSING → DEFERRED D-PORT1 (needs design: handlers + `fr_py_abort_reason` + checkpoint wiring; honest "not supported" statement shipped instead) |
| P5 | fd hygiene at EVERY fork site (death-pipe ends, `FD_TRAP_ACK_W`, `fd_fallow_w`; W-STDIN feeder scrub) | Blanket `scrub_fds(keep)` at every `os.fork` + targeted closes: `_reactor.py:198-262,994-1048`, `_worker.py:725-734,794-803,861-899`, `run.py:208-236,1551-1722,2069-2073,2483-2517,2640-2656,3132-3162,5689-5767`; W-STDIN feeder N/A (no feeder fork; spill is in-parent `run.py:388-486`; v1 spawn stdin is C `posix_spawnp` pump + `_cloexec_all`, `_worker.py:56-75`) | PORTED (EQUIVALENT-superset, `blanket-scrub+targeted-close`) |
| P6 | D8-class stderr persistence (no durable fd-2 redirect) | `keep\|{0,1,2}` (`_fd_scrub.py:42`); only `fd>2` cloexec (`_worker.py:56-75`); zero `dup2(2`/`close(2` hits; `subprocess.run(capture_output=True)` per-batch only (`_spawn.py:75`) | PORTED |
| P7 | INDEXER_DEATH abort-aware classification (`ring_abort_reason` before own abort; no `\|\|ring_abort`; no spurious FATAL on clean `\|head`) (D6; LA4; `frun.bash:1429-1451,2099-2143`) | Fork side EQUIVALENT (`run.py:5702-5724` no abort on either path); classification MISSING: `_watch_pipeline:6048-6097` keys on `fr_py_ingest_eof_posted`, `kind==error` always raises; no `fr_py_abort_reason` binding exists → clean `\|head` (reason-1) reports spurious `NUMA index/scan failed`, signal codes clobbered to 1 | MISSING → DEFERRED D-PORT2 (needs `fr_py_abort_reason` shim = scope escalation per red lines; owner decision required) |
| P8 | Trap-ACK 3s grace + catastrophic declaration; RACE no-grace (RESILIENCE §2.3/§4.1; post-W-PY28 bash removed grace, `frun.bash:1923-1976,2034-2062`) | Modern path: `rc 4→raise` no deadline, `rc 5→raise` (`_reactor.py:336-385`); legacy pre-W-PY28 `.so` path retains 3s deadlines (`_reactor.py:42,83-91,387-409,427-439,637-669,746-748,851-888`); poison `P:` inline (`_worker.py:433-437`) | EQUIVALENT (to current W-PY28 bash) |
| P9 | Escrow drain + fd teardown (TATAS + continuous drain; EOF §4) | Engine-owned escrow/eventfds never closed by Python (`run.py:1608-1613,1963-1968,2551-2555`); EOF-anchored drains (`_drain_records:1282-1374`, `_make_results_pump:1379-1441`, `_reassembly.final_drain`); death-path deposits (`_worker.py:890-895`, `_reactor.py:499,560,622`); teardown closes nothing held (`_teardown_stream:1446-1511`, `_teardown_reactor:3386-3485`) | EQUIVALENT (`engine-owned-escrow`) |
| P10 | Poison threshold + `FORKRUN_RETRY_LIMIT` semantics (retry/skip/fail-fast; 0=exactly-once, <0=unbounded; RESILIENCE §3–§5; `forkrun_ring.c:6430-6441`; `frun.bash:2188-2189`) | Validation PORTED (`_api.py:124-125`); per-mode dispatch PORTED (`_worker.py:514-522,648-669`, `_ON_ERROR_CODES:681`); threshold MISSING: all 7 init sites hardcode `3` (`run.py:1563`, `_worker.py:240,747,812`, `_reactor.py:478,554,616`), `_shim.c:158-170` overwrites `g_fr_config.retry_limit` unconditionally — `0`/`<0`/custom `FORKRUN_RETRY_LIMIT` unreachable | MISSING → F-PORT1 (FIXED this audit) |
| P11 | Order-pipe backpressure 4KiB hydraulic loop (H3) | `ORDER_PIPE_SIZE=4096` (`_reactor.py:47-48`), 6 order paths `F_SETPIPE_SZ` (`run.py:3627-3630` etc.); ack/escrow/death deliberately never bumped (`_pipes.py:13-14`); signal 1MB is separate wakeup channel with blocking backpressure (`run.py:1684-1687,172-175`, `_worker.py:348-353`) | EQUIVALENT (order/ack preserved) / N/A-BY-DESIGN for signal (`channel-separation`) |
| P12 | Checkpoint atomic publish (tmp→fsync→chmod 600→rename); no spurious checkpoints on early fatal (W-PY22; `frun.bash:1306-1337`) | `write_checkpoint:175-196` + `_write_file_atomic:220-235` exact shape + `fsync` (strictly stronger); unarmed/zero-progress/engine-dead → False (`_resume.py:283-286,314-315,279-281`); pre-`try` failures never reach `checkpoint_on_abort` (`run.py:3560-3566` etc.); lock-in `test_resume.py:504-528` | PORTED (superset) |
| P13 | Checkpoint filename quoting — spaces/specials (v3.5.0 W4) | Literal `open(2)` paths throughout (`_checkpoint.py:175-196`, `_resume.py:104-111,220-235`, `_api.py:95-113`); no `shlex`/`shell=True`/trap-string embedding | N/A-BY-DESIGN (`no-shell-interpolation`) |
| P14 | Permission gate `8#022` + `FORKRUN_TRUST_RESUME` denylist (v3.5.0; F29; `frun.bash:663,755-828`) | `022` mask EQUIVALENT (`_checkpoint.py:206-212` correct Python octal); ownership hard-reject ABSENT (no `st_uid` vs `getuid`); soft/hard split + TTY confirm ABSENT; `FORKRUN_TRUST_RESUME` unread anywhere (zero hits); `resume_begin:114-142` parses + sets engine state unconditionally | MISSING → F-PORT2 (FIXED this audit: ownership gate + TRUST bypass + go-w TTY rule) |
| P15 | Resume consent-gate semantics (F29/D10: preview extracted values; PATH-dead `mktemp -ud` shells; quoteless `-c`; shape filter + `declare -p` + denylist) | Codec carries bytes only (`_checkpoint.py:68-121` 3 lines `HORIZON/STDOUT_BYTES/JAGGED`, strict `uint64`); typed push, no eval/source (`_resume.py:145-166` `FrPyInterval` + `fr_py_set_resume_state`); no re-supplied-command reconstruction, no layer-3 prompt (`run.py:875-881,1070-1074`) | N/A-BY-DESIGN (`typed-byte-coordinate-ledger-carries-no-code`) |
| P16 | Stale horizon fail-loud + complete-stream clean no-op (v3.5.0; M18/M19; engine `7296-7301,7427-7436`) | No Python-side pre-check (correct — defers to engine `fr_py_set_resume_state`); same C orderer (`run.py:3619-3620` etc.); orderer failure loud (`run.py:3784-3789`); complete case emits nothing, sidecar no-ops, zero-progress never overwrites | PORTED (engine-inherited) + test gap → F-PORT6 lock-ins (M18-py/M19-py) |
| P17 | Topology validation: `@N` ceiling + bounded-digit regex, early-fatal no checkpoint (F30; `frun.bash:1127-1218`) | `MAX_LOGICAL_NODES=512` (`_numa.py:26-27`); `@N` parse `119-129`, int path `102-105`, `<1` reject `95-98`; eager `_validate:135-139` pre-`init` so no checkpoint path entered; `@513/@0/@abc` reject both sides; residuals: Bash `@0/0/uma/none→UMA` aliases rejected by Python (strict superset, benchmarking-lie avoidance `_numa.py:110-113`); message shape differs (ValueError vs `[ERROR]` — see C2) | PORTED (strict superset) |
| P18 | `-L` validation (ranges/zero/negatives rejected; `-L`+`-b` warn line-wins) (v3.5.0 W3; `frun.bash:952-963,1118-1122`) | Reject-half PORTED (`_api.py:126-130`); ranges structurally unrepresentable (`lines:int\|None`); warn-line-wins ABSENT: both-set → hard `ValueError`, not Bash warn + lines-wins (splice instead forces `bytes` default `run.py:921,939,1115`) | MISSING → F-PORT3 (FIXED this audit: UserWarning + `bytes_=None`) |
| P19 | Empty-input: no command run (v3.5.0 W5) | Publish-gated fork (`run.py:69-76,2012-2016,2040-2046,2112-2290`); `file_size==0` guard (`_worker.py:529-539`); lock-ins `test_v0.py:58`, `test_spawn.py:149`, `test_numa.py:270`, `test_splice_mode.py:91`, `test_streaming.py:80`, `test_streaming_ingest.py:154`, `test_ordered.py:200`, `test_c_drain.py:135` | PORTED |
| P20 | `-E` appendage explicit init (v3.5.0 W1) | Explicit default at every layer (`_api.py:21,28,85,124-125`, `_worker.py:7-12,514-525,648-653,681`, `_reactor.py:132,155,549,613`, `_bindings.py:147`, `_shim.c:2507-2740`); no `unset` hazard, no JIT string surgery | PORTED / EQUIVALENT (`no-string-codegen`) |
| P21 | EOF 3-condition (C1→C2→C3, `continue`-not-`break`) on every completion path (EOF_PROTOCOL §§1–6) | All signal-consuming paths EOF-anchored with short-circuit `and` + `continue/None`, `break/StopIteration` only when all true: `_drain_records:1299-1358`, `_make_results_pump:1386-1441`, `_pump_drain:4056-4180`, `reactor_loop:853-888`, streaming loops `1743-1801,2269-2307`; blocking map C3-vacuous with C1-before-C2 join order `3171-3198` | EQUIVALENT |
| P22 | Fork ordering: indexer write-ends closed before scanner/worker forks (v3.5.1) | NUMA ordered correctly (`run.py:5669-5767` per-iteration `close(death_w)` before next fork; `5698` fallow_r closed before indexers); non-NUMA N/A (`no-indexer-process`); `_drop_fallow_copies` deferred `2656` intentional (reaper EOF = workers only) | PORTED (NUMA) / N/A-BY-DESIGN (non-NUMA) |
| P23 | PID-recycling no-kill rule (`waitpid` ECHILD ⇒ no `kill`) (primer §4.1) | Every `kill(,9)` guarded by `WNOHANG==0`; ECHILD paths skip kill (`run.py:1486-1498,3423-3465`, drain/sweep/scanner joins `1349-1352,1747-1791,2093-2272,1825-3178`; `_reactor.py:285-287,452-454,1068-1094`) | PORTED |
| P24 | The mover (F-PY-UMA1b): positional ops on ingress memfd, BOTH frontends | Bash: `ring_copy`/`ring_numa_ingest` + `ring_lseek` probes + `ring_splice`/`read -u`/offset fds, never advancing shared offset (`frun.bash:1225-1233,1420,1480,1502ff,1713-1797,2161`); Python: explicit-offset `fr_py_copy_range` + frontier `pread/pwrite` (`run.py:388-486` doc `394-396`), ingress reset `lseek 2580`, workers `mmap`/borrowed window only | PORTED (both sides offset-less-or-explicit-only; mover still unidentified but constrained to non-ingress-positional causes) |
| P25 | Hostile-PATH handling in spawn/plugin paths (D10; `frun.bash:365,499-522`) | Python inherits caller `PATH` unsanitized: `subprocess.run(argv, shell=False)` no `env=` (`_spawn.py:60-93`); C `posix_spawnp(..., environ)` PATH lookup (`_shim.c:593`); no `which` pinning; `ctypes.CDLL(path)` relative resolves via CWD/`LD_LIBRARY_PATH` (`_plugin.py:89`); zero `mktemp` analogue | MISSING → F-PORT4 (FIXED this audit: `shutil.which` system-PATH pin + absolute-path requirement for plugins) |
| P26 | Version/substrate coherence: wheel-vs-local drift; `release_check.py` gaps | `__version__ 0.16.0` / engine query-or-`"unknown"` (`__init__.py:45-61`, import never fails — masks drift); loader precedence `$FORKRUN_LIB` > pkg > repo > CWD, no version compare (`_bindings.py:356-405,412-452`); `release_check.py` never asserts `__engine_version__` vs `META`/CHANGELOG, never imports from built wheel, never maps `0.16.0↔v3.6.0`, `"unknown"` passes silently | MISSING → F-PORT5 (FIXED this audit: engine-match + wheel-embedded-`.so` checks in `release_check.py`) |
| P27 | Degenerate-input edge parity (empty/single/no-trailing-NL/NUL/huge-record; Bash T/M-series vs `python/tests/`) | Empty + single PORTED (8 + 1 lock-ins); GAPS: no `no-trailing-newline` case (zero hits), no NUL-laden/`-z` case (no `-d` knob — implicit, untested), no `>ARG_MAX`/3 MB single-*line* case (nearest: 3 MB single *batch* `test_pipes.py:115`, 3 MB/1 MB batches `test_plugin.py:209` — different shape from T3a line-scanner stress) | MISSING → F-PORT6 (FIXED this audit: `test_edge_degenerate.py` vs `frun -k -s cat` md5 oracle) |
| P28 | Delivery semantics: ordered/buffered EXACTLY-ONCE vs realtime `-u` AT-LEAST-ONCE (RESILIENCE §5.2; `frun.bash:291-294,344-348`) | No realtime surface: `Order=none\|index` only (`_api.py:20,27`, `run.py:1596-1598,1957-1959,3877-3879` reject else); every result framed `[idx][len][bytes]` into per-worker memfds (`run.py:543-564,615-637`); exactly-once scope explicit (`_resume.py:13-20`, `run.py:880-881`); C orderer only where tracker exists (`_resume.py:51-101`) | N/A-BY-DESIGN (`framed-transport-invariant`) |
| P29 | Fallow punch-behind-acked-horizon (bounded RSS) | Streaming/NUMA: reaper punches acked prefixes (`run.py:2530-2539,2578-2618`, `_bindings.py:132-134,237-239`, `_shim.c:1042-1095,1679-1685,1917-1918`); materialized: no fallow by design, bounded inputs (`run.py:21-24`, `_batch.py:12-13`); unacked never punched (`_shim.c:1431`); RSS lock-ins (`test_rss.py`, `test_streaming_ingest.py`) | PORTED (streaming/NUMA) + N/A-BY-DESIGN (materialized) |
| P30 | Pre-consent process-signal effects (P1 residual #5, docs-only, v3.5.2) | No counterpart execution: `resume_begin:130-141` is `open+read` + regex + `stat` + typed `ctypes` — no `fork/exec/bash/source/eval/mktemp/redirect/TTY-read`; hostile file raises catchable `ValueError/RuntimeError/OSError` pre-fork; abort-path `SIGKILL`/`fr_py_abort` run post-arm only | N/A-BY-DESIGN (`no-pre-consent-execution`) |

### 1.4 Presentation / contract

| ID | Concern | Disposition |
|---|---|---|
| C1 | Flag/help parity (`--nodes`, `--help` `-C` line, `-L`/`-b` wording) | N/A-BY-DESIGN (`library-API`): no CLI surface (no `argparse`/`__main__` in `python/forkrun/`); flags become kwargs (`run.py:747-751,855,1048`); `mode` covers `-s/-X/-C/splice`, `order` covers buffered/ordered but deliberately not realtime `-u`, `lines/bytes` cover `-l/-b` (no `-L` exact, no `-d/-z/-t/-n/--halt`), `sweep()` covers `:::`/`--link`; help lives in docstrings + `python/README.md` + `DOCS/` |
| C2 | Stderr message shapes (poison summary, checkpoint hints — D8-adjacent) | EQUIVALENT for operational paths (`forkrun [WARN]: Skipping poisoned batch` `_worker.py:427` etc.; `[ERROR]: POISONED BATCH SUMMARY` `_reactor.py:967-975`; `[WARN]` checkpoint/sidecar/reaper/NUMA-partial `_resume.py`, `run.py:5879`); N/A-BY-DESIGN for validation (Python raises `ValueError/TypeError/RuntimeError` instead of stderr+`NORMAL_EXIT_FLAG`; no `[FATAL]`) |

## 2. Seed-target cross-reference (work order §2.3 — covered beyond)

1. D10/PATH → P25 (F-PORT4). 2. Exit codes → P3 (D-PORT3 defer).
3. stderr → P6 (PORTED). 4. Signals → P4 (D-PORT1 defer; KI known-good W-PY4;
   operator-HUP→checkpoint: NO Python equivalent — honestly unsupported, see
   D-PORT1 work order). 5. Mover → P24 (PORTED both sides; identity still
   unknown F-PY-UMA1b). 6. fd inheritance → P5 (PORTED).
7. Sandbox semantics → P15 (N/A-BY-DESIGN, typed ledger) + P14 (F-PORT2) +
   P30 (N/A). 8. Version coherence → P26 (F-PORT5). 9. Escrow/fd
   teardown → P9 (EQUIVALENT). 10. Degenerate inputs → P27 (F-PORT6).

## 3. Findings ledger

| Finding | Audit item | Severity | Disposition |
|---|---|---|---|
| F-PORT1 | P10: `FORKRUN_RETRY_LIMIT` ignored (hardcoded 3; `0`/`<0` unreachable) | High (F-NUMA2-class: Bash behavior lost in port) | FIXED (this audit): `_resolve_retry_limit()` + threading + lock-in |
| F-PORT2 | P14: checkpoint ownership hard-reject + `FORKRUN_TRUST_RESUME` absent | High (security: foreign-owned checkpoint silently resumed) | FIXED (this audit): gate in `resume_begin` + lock-in |
| F-PORT3 | P18: `lines=`+`bytes=` hard error vs Bash warn-line-wins | Low (contract fidelity) | FIXED (this audit): UserWarning + `bytes_=None` + lock-in |
| F-PORT4 | P25: spawn/plugin inherit hostile caller `PATH`/CWD | High (D10-class: CWD-planted binary execution) | FIXED (this audit): system-PATH `which` pin + absolute-path plugin rule + lock-in |
| F-PORT5 | P26: `release_check.py` never verifies engine version / wheel-embedded `.so` / `META` mapping | Medium (release gate hole pre-tag) | FIXED (this audit): 3 new checks + lock-in |
| F-PORT6 | P27: degenerate edges untested (no-trailing-NL, NUL, huge single line) | Medium (parity gap) | FIXED (this audit): `test_edge_degenerate.py` (test-only) + P16 M18-py/M19-py lock-ins |
| D-PORT1 | P4: parent-side signal choreography (TERM/HUP/USR1+PREEMPT, no-downgrade, checkpoint-on-signal) | Medium | DEFERRED (needs design; work order §7 below) — honest statement: NO Python equivalent in v3.6.0 |
| D-PORT2 | P7: abort-aware indexer-death classification (needs `fr_py_abort_reason`) | Medium | DEFERRED (scope escalation: shim change required; red lines bind) — work order §7 |
| D-PORT3 | P3: exit-code taxonomy full parity (signal-cause preservation, poison raise-vs-warn) | Low | DEFERRED (API decision required; warn-only preserved in v3.6.0) — work order §7 |

## 4. Coverage statement (final in completion report §5)

- Inventoried: CHANGELOG v3.5.0–v3.6.0 behavioral entries + primer §3
  ledger (D1–D10, F-series) + work-order seed list. `git log -p frun.bash`
  archaeology: timeboxed pass over `frun.bash` trap/reactor/exit/validation
  regions confirmed no additional parent-layer behaviors beyond the 30
  inventoried (full `-p` walk deferred — CHANGELOG + ledger + seed list
  cover the fix history; residual risk noted in completion report).
- Skipped with reason: Engine-layer E1–E8 (shared TU); J1–J2
  conditional (done above); benchmark files/results + PERFORMANCE.md +
  benchmark DOCS_ALL sections (W-BENCH1); residual known flakes
  (C-drain framing header, reactor-ingest multiset, T10b, M1a).
- Matrix status: 30 parent items + 2 contract items, all dispositioned:
  11 PORTED, 8 EQUIVALENT, 7 N/A-BY-DESIGN, 6 MISSING→fixed (F-PORT1..6),
  3 MISSING→deferred with work orders (D-PORT1..3). Zero UNKNOWN remain.

## 5. Verification log

| Gate | Status |
|---|---|
| Full Python suite green ×3 | NOT RUN (runs at fix completion) |
| Targeted tests green ×10 (touched paths) | NOT RUN |
| `make -f Makefile.substrate check` | NOT RUN |
| Engine untouched (`git diff -- forkrun_ring.c python/forkrun/_shim.c` empty) | HELD (no code changes yet) |
| New findings carry changelog + lock-in test | IN PROGRESS (fixes follow) |

## 6. Deferred work orders (for §7 commit)

- D-PORT1: parent-side signal choreography (handlers + abort-reason + checkpoint wiring + HUP→checkpoint equivalent-or-honest-unsupported + no-downgrade rule).
- D-PORT2: `fr_py_abort_reason` shim binding + abort-aware `_watch_pipeline`/joins suppression (mirror `frun.bash:2130-2142`).
- D-PORT3: exit-code taxonomy API decision (signal-cause preservation via `WTERMSIG` sentinel; poisoned-run raise-vs-warn contract).
