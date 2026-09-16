# forkrun Changelog

## v3.5.x (unreleased) — precondition-gate engine fixes

Porting-plan preconditions (v1.3 §2.0) that ship unconditionally as bugfixes,
independent of the Python-frontend work:

- **Resume-ledger seqlock fence PAIR:** `TRACK_COMPLETED_BATCH` keeps
  `__atomic_thread_fence(__ATOMIC_RELEASE)` before the second `resume_seq`
  bump. Both readers — the scanner resume snapshot and `ring_dump_resume` —
  now issue `__atomic_thread_fence(__ATOMIC_ACQUIRE)` immediately before
  their closing `resume_seq` loads. The reader fence is the load-bearing
  half: an acquire load cannot prevent itself from being satisfied before
  the RELAXED data loads. The writer RELEASE fence is explicitly
  belt-and-suspenders under C11, because the closing RELEASE RMW already
  orders the preceding RELAXED stores; it remains as toolchain defense and
  to preserve the kernel-analogous publish shape.

- **Kernel-observable indexer death (NUMA):** one liveness pipe per NUMA
  node, created by the orchestrator (not the engine): the indexer child
  inherits the write end, the parent closes its copy at spawn, and the
  reactor polls the read end via `ring_poll`'s new optional 6th argument
  (Bash array name; omitted/empty = old behavior). Indexer SIGKILL/OOM —
  which runs no exit code, so `|| ring_abort` and traps structurally
  cannot catch it — now produces POLLHUP → `INDEXER_DEATH` →
  wait-for-status: clean EOF drain continues; a non-zero status aborts
  ONLY when no abort is already in flight — the classification is
  abort-aware (`ring_abort_reason`). An indexer's non-zero exit is its
  EXPECTED emergency path on any pipeline abort (`ring_indexer_numa`
  returns EXECUTION_FAILURE once it observes the alarm), so re-aborting
  there would print a spurious FATAL on every clean early exit and
  clobber trapped-signal exit codes (SLURM 143/138 → 1). Only an
  alarm-unset non-zero status — a genuine violent death (e.g. SIGKILL),
  which loses chunk-boundary alignment — aborts with reason 2
  (checkpoint + non-zero exit, never a silent clean exit). Test-only
  chaos hook `FORKRUN_TEST_INDEXER_PIDFILE` (same pattern as the fallow
  pidfile) targets one indexer by PID; lock-in tests LA3 (violent death
  → FATAL + checkpoint + non-zero exit) and LA4 (clean `| head` abort →
  exit 0, no spurious FATAL).
  The fork-order constraint at the spawn site is documented: scanner and
  worker forks must come after every indexer write-end is closed in the
  parent, or a later-forked child masks that indexer's death.

- **Single-source packing constants:** `MINOR_BITS`/`MINOR_MASK`/
  `MAJOR_MASK`/`PACK_KEY` now come from `forkrun_substrate.h` (`FR_*`),
  whose static asserts tie `fr_state_t` widths to the frozen plugin-ABI
  packing; the strong tie is enforced by including the frozen
  `ring_loadables/forkrun_plugin.h` before the engine's ctx struct.

- **F30: topology validation & `--nodes=@N` ceiling:** `ring_init` now
  returns `EXECUTION_FAILURE` on invalid topology (e.g. `--nodes=@N`
  exceeding the 512 `meta_ring` capacity). Previously, running on with
  unchecked `ring_init` failure left ring pointers NULL, producing a
  cleanroom SIGSEGV mid-pipeline on `--nodes=@513`. Both `ring_init` and
  `_forkrun_build_numa_map` now enforce early-fatal handling
  (`NORMAL_EXIT_FLAG=true; return 1`) with clean `[ERROR]` messages on
  stderr and no spurious checkpoint emission. Input parsing in
  `_forkrun_build_numa_map`'s `@*` branch is hardened with a bounded digit
  regex (`^[0-9]{1,9}$`), preventing non-numeric or overflow-length
  literals from triggering bash arithmetic errors or causing silent UMA
  degradation. Lock-in test T14 validates `@513`, `@abc`, and
  `@999999999999999999999` rejections in an isolated temporary directory.

- **F15: NUMA steal over-claim orphaned the thief's own chunks at EOF:**
  in `core_scanner_loop`'s NUMA claim section, a scanner that over-claimed
  the victim's published chunks exited outright
  (`goto unified_scanner_eof`) — safe only when over-claiming one's OWN
  queue. A thief entered the steal branch because its own queue was empty;
  chunks published/indexed to the thief's own queue since (indexer lag;
  ingest's min-backlog routing feeds empty nodes) were then orphaned — no
  process would ever scan them. Manifestations: successor-chunk waiters
  hung (`WAIT_FOR_META_READY` has no EOF escape), ordered mode silently
  truncated, `-L` hung at the handoff gate. One-word fix (`goto` →
  `continue` plus a rewritten comment): re-check the own queue instead;
  termination routes through the Instant NUMA Tear-down path
  (`global_eof` && own publish-head exhausted), which converges at global
  EOF. The own-scanner over-claim case reaches the identical clean exit, so
  the change is strictly safe. Lock-in tests F15a (permanent
  chunk-conservation assertion: Σ`assigned` == Σ`processed` and
  Σ`I stole` == Σ`stolen from me` from the per-node `--stats` telemetry,
  across {file, pipe} × {@2, @4} × {default, `-s`}) and F15b (EOF-herd
  stress: 10× ≥1M-line fast-draining pipe runs, byte-exact + conservation
  each iteration). Post-reactor stderr is required to carry Node frames in
  every combo/iteration (D8 below closed the fd-2 poisoning that used to
  swallow it) — rc==0 + byte-exact stay unconditional, and every F15
  manifestation breaks one of those two deterministically.

- **D8: INDEXER_DEATH handler permanently redirected fd 2 to /dev/null:**
  the handler ran `exec {fd_indexer_death_r[$sID]}<&- 2>/dev/null` as a
  bare `exec` (no command words), so the `2>/dev/null` persisted in the
  main shell for the rest of the run — the `wait`, `ring_numa_stats`
  telemetry, verbose output, and EXIT-trap checkpoint hints all vanished
  while stdout stayed byte-exact and rc stayed 0. Mode-correlated (~90%
  default vs ~0% `-s`) because the poisoning requires the reactor loop to
  still be polling when the indexer POLLHUP arrives — a drain-timing race
  (indexer fds are deliberately not in `core_cnt`). Introduced by the D6
  indexer work this cycle (v3.5.0's 396-run benchmark suite showed
  default-mode telemetry fine), so the earlier "pre-existing flake"
  attribution was wrong. One-line fix matching SCAN_DEATH's close form
  (`exec {fd_indexer_death_r[$sID]}<&-`); F15a/F15b tightened to require
  Node frames in every combo/iteration. User-facing impact: on NUMA aborts
  in default mode the checkpoint-hint messages could be silently lost.

- **F29: resume consent-gate integrity (informed consent):** forkrun is an
  engine for running arbitrary code by design; what F29 closed was code
  executing without ever appearing in a preview, and forged data executing
  while the preview showed the file's benign text. Three components: (A)
  positional token close + EXIT-trap emission — frame tokens arrive
  positionally, are bound to readonly names and shifted away on entry, and
  emission goes only through a trap installed after wipe/verification, so
  early-exit forgeries emit token-less output the parent rejects (T1g); the
  quoteless-`_emit_all` invariant keeps the `-c` script's positionals
  unscrambled. (B) Ownership gate relocated after extraction + preview helper
  at all three consent sites — prompts preview extracted values (what will
  RUN), never raw file text. (C) Parent-side re-render — declare-only shape
  filter (double-dash-permitting) + round-trip `declare -p` re-render in a
  PATH-dead restricted shell + denylist (`FORKRUN_TRUST_RESUME` et al):
  unescaped substitutions execute only in-sandbox and the parent evals just
  the neutralized form (T1b/T1h/T1a-ext); plain setup declares pass through
  to the layer-3 gate (T1i). Token secrecy is not a security property. M20 /
  M21 / T7 re-verified byte-exact after the `PATH=''` revert (D9). Lock-in:
  T1a-ext/T1g/T1h/T1i (+T1a/T1b/T1d/T1f); F6 characterize-only probe
  (CWD-planted `touch` executes in-sandbox on bash 5.3 — contained, see
  SECURITY.md). `PATH=''` retained per owner determination.

## v3.5.0 — 2026-09-03

The headline of this release is a fully-rearchitected resume subsystem: NUMA-native
exact-line batching, a hardened multi-layer resume sandbox that has now been validated
under adversarial attack, atomic checkpoint publication, and coordinated signal-driven
shutdown. It also fixes a serious pre-existing bug where ordered/buffered output could
be silently lost when appending.

### Highlights

- **Plugin context ABI v2 frozen at 128 bytes (append-only):** new `batch_lines`,
  `struct_size`, `worker_incarn`, `flags_granted`; `forkrun_use_ctx` now encodes
  a dialect byte plus optional behavior-flag bits with engine-side grant negotiation
  (no flags granted in 3.5.0 — the machinery is frozen; first flag,
  `FORKRUN_CTX_FLAG_RAW`, planned for 3.5.1). UMA `numa_batch_id` is derived from
  the 64-bit claim index and is globally unique (equals `batch_index`).
- **`-L` (exact lines) is now NUMA-native.** The Scanner-Handoff Chain serializes
  scanning across nodes via the cumulative line-count chain, preserving exact batch
  boundaries without demoting the pipeline to UMA. A batch may straddle a NUMA chunk
  boundary (1..L−1 lines of cross-socket read per boundary — the price of exactness).
  Deterministic `-n` is likewise now exact on NUMA via the same chain.
- **Resume files are now defended in depth** — see SECURITY.md for the full model:
  ownership/permission gate → restricted, PATH-dead sandbox with function wipe and
  split-frame emission → interactive authorization for functions/setup/custom vars.
  Every adversarial test in the suite (hostile substitutions, function shadows, output
  injection, frame forgery) executes against a live sandbox and is rejected.
- **`>>` append redirect no longer silently discards output.** A pre-existing bug:
  `sendfile()` returns EINVAL on O_APPEND output files, and the orderer classified
  the failure as "downstream closed" — clean exit 0, zero output, no error. All
  orderer emit paths now fall back from sendfile to read/write on any failure
  (O_APPEND, partial sends, environment-specific EINVAL), with EPIPE properly
  distinguished as the only clean-exit condition.
- **Checkpoints are published atomically** (temp + rename): a crash mid-write or a
  racing reader sees either the old complete checkpoint or the new one, never a torn
  fragment. Failed checkpoint generation leaves the previous checkpoint untouched.
- **External signals now coordinate shutdown.** SIGTERM/SIGUSR1 (SLURM preemption)
  and friends route through the reactor's abort path — fd choreography, worker
  reaping, frozen ledger — *before* the checkpoint is written, instead of exiting
  from the signal handler mid-flight. A trapped signal can never be downgraded to a
  silent clean exit by a concurrent SIGPIPE.

### Bug Fixes

- **C engine:**
  - NUMA ingest probe-transfer data loss: when `set_mempolicy` is unavailable
    (containers, non-NUMA kernels) with forced multi-node, the transfer-method probe
    moved data without accounting it — files ≥ chunk size lost their tail; files
    smaller than a chunk produced zero output. Both exited success. (A1)
  - Fallow-death silent truncation: a killed fallow process caused every worker's
    next ack to fail with exit 0 — no escrow, no respawn, no checkpoint, silently
    truncated output. Ack pipe failures now fire the global alarm (reason 2), and
    the fallow subprocess aborts the pipeline on abnormal exit. (A2)
  - `ring_numa_ingest` double-free of `nodemask` on the OOM path. (A4.8)
  - v2 plugin ABI: `numa_batch_id` is now globally unique on UMA as documented;
    derived from the authoritative 64-bit claim index, guaranteeing strict
    monotonicity past the 2^22 threshold (previously every UMA batch reported
    the same key 0:0). (D2)
  - Plugin context `cfg_state[4]` byte order aligned: fixed an inverted extraction
    where bytes and workers were transposed. Now strictly `[0]=cfg_w`, `[1]=cfg_l`,
    `[2]=cfg_b`, `[3]=flags`. (D3)
  - Scanner-side resume snapshot: Seqlock-consistent frozen copy of resume intervals
    prevents tearing and shared-cache read contention. (A4.9)
  - Topology ceiling: `--nodes=@N` capped at 512 (previously accepted up to 1024)
    to preserve `meta_ring` bounds. (A4.10)
  - Orderer: `FD_ORDER_PIPE` missing during an ordered ack now fails loudly with
    the alarm instead of hanging the pipeline. (A4.4)
  - Non-EPIPE orderer write failures are now internal faults (checkpoint + non-zero
    exit) rather than silent clean exits.
- **Bash wrapper:**
  - `-L` validation: ranges (`-L 5:10`), zero (incl. `0k`), and negatives are
    rejected as errors instead of silently breaking the exact-lines contract.
    `-L` combined with `-b` emits an override warning (line mode wins, stdin
    delivery preserved). (W3)
  - `-E` appendage hardening: the error-check flag is now explicitly initialized;
    previously the appendage relied on unset-variable semantics that a future
    quoting change could silently invert. (W1)
  - `+s -b -X` no longer runs the command on empty input: the mis-generated
    zero-argument spawn path is removed; byte data is delivered as arguments. (W5)
  - Checkpoint filename quoting: `--checkpoint-file` with spaces/specials now
    writes the correct file (dynamic trap-time reference instead of an embedded
    %-quoted literal). (W4)
  - Permission gate: the group/world-writable check used `0o022` (invalid bash
    octal) — the soft reject silently never fired. Now `8#022`, verified.
  - Early fatal errors (bad `-C` invocation, etc.) no longer write spurious
    "Pipeline aborted" checkpoints.
- **Resume sandbox:**
  - The sandbox never executed under `--restricted` (output redirection in its
    first line was prohibited; `source` with a slash path was prohibited). Rewritten:
    content passed by value, builtins only, environment *constructed* via
    `env -i` (an empty PATH is not a dead PATH — bash re-seeds defaults; the
    environment must be built, not cleared).
  - Function definitions cross in a separate token frame and are eval'd only after
    the interactive authorization gate passes. The gate's own preview commands run
    with no resume-supplied functions in scope.
  - Resume of an already-complete stream is a clean no-op; a stale horizon
    (beyond EOF) fails loudly.

### Performance

- Order-pipe backpressure: the worker→orderer ack pipe is sized to one page (4 KiB),
  closing the hydraulic loop (slow stdout → orderer blocks → acks block → workers
  stop claiming → scanner/ingest yield) with bounded in-flight output state.
- A forced-path regression test (`FORKRUN_DISABLE_MEMPOLY=1`) now covers the NUMA
  ingest fallback; per-mover fallback coverage is a standing suite category.

### Known Issues

- `-C` + `-s`/`-b`: stdin/stdin-chunk delivery to C plugins is not yet implemented;
  the flags are ignored with a warning. Access batch data via `forkrun_ctx`
  (`batch_offset`/`batch_byte_length`/`fd_in`) in the meantime; full support is
  planned for v3.5.1. `-i`/`-I` with `-C` DO work (substitutions arrive as fixed
  plugin arguments).
- Interactive resume prompts wait 60 s for input when a TTY is present but
  unattended (test runs from a terminal). This is the documented fail-closed
  default; tests should run with detached stdin.
- Sanitizer note (unchanged): TSan observes intra-process races only; forkrun's
  coordination is cross-process on MAP_SHARED memory and is validated by the
  invariant set + full matrix, not TSan.

### Invariants (new in this release — see INVARIANTS.md §11, §14–16)

- Gate publication & producer wakeup invariant.
- No sole-path data movement: every zero-copy syscall has an exercised fallback.
- Gates inspect text, never live state derived from executing that text.
- Sanitize by construction (`env -i` + explicit values), not by clearing.
