# FORKRUN_SUPERVISOR_PRIMER.md

**Purpose:** Transfer of supervisory context to a successor AI instance. This document encodes the technical understanding, review posture, and operational discipline accumulated across a full four-part project review (v3.5.0 baseline) plus multi-round AI-guided implementation of v3.5.1 and the Stage-1 port preconditions. The successor's job: continue guiding the v1.3 Python-frontend port and its supporting bugfix releases with the same rigor, the same red lines, and the same relationship to the project owner.

**How to use this document:** Read it fully before the first interaction with the owner. Sections 1–5 are the technical substrate you must hold in your head to review code. Sections 6–10 are the operational protocol you must follow to review diffs, write work orders, and manage AI-implemented changes. The owner will hand you diffs; you respond with verified-complete lists, new findings, and work orders. Never fabricate continuity — everything you need is here.

---

## 1. Engine Physics

### 1.1 The Universal Coordinate Plane

All forkrun subsystems communicate by passing 64-bit integer byte offsets into an append-only shared memfd. No subsystem maintains its own numbering. This is the single most load-bearing design decision in the codebase:

- **Ingest** writes raw bytes at monotonically increasing offsets, publishing `ChunkMeta` entries (raw_offset, raw_length, target_node, major_id) to a metadata ring.
- **Indexers** (NUMA, one per node) find the last delimiter in each chunk via backward `memrchr`, publishing `actual_end` (the real logical boundary) with `FLAG_META_READY` (bit 63).
- **Scanners** (one per node, NUMA; one total, UMA) consume chunk metadata, find internal record boundaries via AVX2/NEON SIMD, and publish ring slots `[offset_ring[slot], end_ring[slot])`.
- **Workers** claim ring slots via a single `atomic_fetch_add` on `read_idx`, receiving a byte range.
- **Orderer** merges out-of-order completions via a min-heap keyed by `(major, minor)` packed keys.
- **Fallow** punches holes (`fallocate(PUNCH_HOLE | KEEP_SIZE)`) behind the consumption horizon — physical memory is reclaimed but the coordinate grid is preserved.
- **Resume** is set-membership over coordinates: horizon + jagged intervals on the byte plane.

The invariant: a coordinate names the same bytes forever. Checkpoints are trivially resumable because the coordinate system survives every crash.

### 1.2 FAA Claiming (Consensus-Free)

The fast path is two amortized atomic RMWs per batch:
1. `read_idx = __atomic_fetch_add(&local_state->read_idx, 1, __ATOMIC_SEQ_CST)` — claims exactly one ring slot.
2. `__atomic_fetch_add(&local_state->total_lines_consumed, 1, __ATOMIC_SEQ_CST)` — accounting (note: counts *batches*, not lines — the name is a misnomer; F17).

No CAS retry loops. No locks. No rollback. The scanner is the sole determiner of batch size; workers are oblivious to policy.

**The "consensus-free" framing** (owner's term, verified correct): Herlihy's result gives fetch-and-add a consensus number of exactly 2. forkrun doesn't care because slot assignment is not a consensus problem — the scanner pre-partitioned the work, every partition is acceptable, and the FAA is used in "unique-ticket mode" where linearizability of the counter (guaranteed for any n) is sufficient. The two "elections" that exist (escrow TATAS re-arm, fire-alarm CAS) are degenerate — all candidates propose the same commutative action, so first-wins is safe.

### 1.3 Memory Fences: Why They Live Strictly in C

The §11 publication protocol (INVARIANTS.md): every gate-resolving state publication (`actual_end`, `cum_lines`, `write_idx`) executes release-store → `__atomic_thread_fence(__ATOMIC_SEQ_CST)` → waiter-count check → eventfd write. These are indivisible triples. An AI implementer will see "redundant fence" and simplify it away — this is the single most common review hazard.

**The seqlock fence pair (D1, v3.5.1):** The resume ledger (`TRACK_COMPLETED_BATCH` in `ring_order`) publishes via: `bump(seq, ACQ_REL)` → RELAXED data stores → `fence(RELEASE)` → `bump(seq, RELEASE)`. Readers (scanner snapshot, `ring_dump_resume`) use: `ACQUIRE seq1` → RELAXED data loads → **`fence(ACQUIRE)`** → `ACQUIRE seq2`, retry while odd/mismatched. The reader's ACQUIRE fence is load-bearing: an acquire load cannot prevent *itself* from being satisfied before prior RELAXED loads (window c), so without the fence, a torn snapshot is accepted on weakly-ordered arches. The writer's RELEASE fence is belt-and-suspenders under C11 (the closing RELEASE RMW already orders the stores). Both fences exist in the current tree with comments explaining exactly this — do not remove either.

**Why frontends never touch coordination words:** Python (Stage 4+) will never raw-read claim counters, escrow slots, or poison flags from MAP_SHARED. The fences live in C. Frontends receive: (a) claim out-params (typed struct), (b) event-frequency snapshots, (c) the payload-byte window (explicitly sanctioned — `Batch.data` is a MAP_SHARED view by design, safe per the mmap stability guarantee: fallow punches only behind the acked contiguous prefix).

### 1.4 Born-Local NUMA

Data pages are physically allocated on the consuming socket at ingest time via `set_mempolicy(MPOL_BIND)`, driven by per-node indexer backpressure (self-load-balancing). Cross-socket traffic is measured 0.0–0.2% (file input, ≥ hundreds of chunks). Stealing is distance-charged (`1 + distance/10`), collapsing to 1 at global-EOF drain.

**The `-L` Scanner-Handoff Chain (v3.5.0):** Exact-line batches across NUMA nodes require serialization of scanning via the `cum_lines` chain. Each scanner counts its own chunk's delimiters, publishes `cum_lines` (cumulative through this chunk) and `actual_end` (start of the open batch) with both ready flags set. The successor seeds `pending = cum_lines mod L` — derived, never transferred. A batch may straddle a chunk boundary (1..L−1 lines of cross-socket read per boundary — the price of exactness). Scanning throughput is single-scanner-bound; worker execution remains fully parallel.

### 1.5 Resilience Model

- **Death pipes:** every scanner and indexer holds the write end of a pipe; the parent polls the read end via `ring_poll`. POLLHUP = kernel-level death detection (works for SIGKILL/OOM that run no exit code).
- **Escrow:** failed workers deposit their batch metadata (idx, cnt, num_kills) into a per-node pipe; idle workers steal from escrow before the ring. The `escrow_pending` flag (TATAS re-arm) makes this zero-cost on the hot path.
- **Poison:** after `FORKRUN_RETRY_LIMIT` failures (default 3), a batch is skipped; pipeline exits with code 3.
- **Trap-ACK:** dying workers write their wID to a trap-ack pipe; the parent waits up to 3s (protocol constant, not policy) for confirmation before declaring catastrophic failure.
- **Checkpoint:** at abort, the orderer's seqlock-protected ledger is dumped to `.forkrun_resume` (horizon + jagged intervals + stdout bytes + environment declarations).

### 1.6 Performance Envelope (empirically verified, 14c/28t i9-7940x)

- Default mode (quoted args via cmdline): 25M lines/s (mapfile/array-expansion-bound).
- `-X` (posix_spawnp fast path): 87M lines/s default; 191M at `-l 1:-1`.
- `-s` (splice to stdin): ~1B lines/s on 1-byte lines.
- `-b 512k` (raw byte chunks): 2.5 GB/s steady state; 1TB in ~6.5 min, <1GB peak RSS.
- THP `always` adds 50–60% to `-s`/`-b`/`-C` top end.
- `-U` (unsafe/unquoted): 75M lines/s; forces bash AST (disables `-X`).
- NUMA pipeline costs ~0.45% wall time over UMA on single-socket hardware.
- Startup bring-up: ~30ms; sub-second jobs correctly under-spawn by design.

---

## 2. Boundary Philosophy (v1.3 Port Plan)

### 2.1 The Taxonomy

- **C owns:** mechanism, engine invariants, protocol constants (the 3s trap-ACK grace, `FR_MAX_POLL_WORKERS`), default safety limits.
- **Frontend owns:** user-selected policy, presentation, orchestration *decisions* (whether to respawn, how to render output, what to expose).
- **Bash owns:** compatibility presentation (the JIT/partial-eval codegen, the `frun()` orchestrator function).

### 2.2 The Incremental Ladder

```
Bash → Bash + C-owned state (Stage 1) → canary links → typed boundary (Stage 3)
     → Bash + Python both drive substrate → Python frontend (Stage 4+)
```

Each rung: a local invariant, a bounded change, an observable test. There is never a moment where you have to believe the port.

### 2.3 Standing Rules (binding on all future work)

1. Fork before threads; no parent-side native-library initialization.
2. `os._exit()` in Python workers; mechanism processes (fallow, orderer) fork before workers.
3. v0 Python workers are single-threaded.
4. Bytes/memoryview default; decode opt-in. Module-path payloads blessed (fork-safety mechanism). Never pickle.
5. CPU-only default + spawn-time CUDA hazard refusal.
6. Python never raw-reads coordination words from MAP_SHARED.
7. No worker hot-path `fr_state_t` reads; no `fr_get_state()` — state travels with the claim.
8. Views die at payload return; `batch.copy()` for persistence.
9. Source ∈ {path, fd, pipe} — Python is never an input pump (an iterator would make the interpreter part of the ingestion datapath).
10. No Python IPC for payload bytes; the C emitter handles result transport (pipe destination for closed-loop backpressure).
11. Wrapper flushes payload-facing streams before ack.
12. Protocol constants from the store, never hardcoded in frontends.

### 2.4 The Canary Build

`Makefile.substrate` compiles `forkrun_ring.c` against stub bash symbols (`substratestubs.c`) with `-Wl,--no-undefined` + explicit allowed deps (`-ldl -lrt`). CI fails if the engine gains a new bash-internal dependency. The stub list is the frozen closure: shrinking is progress; growing needs justification. The CCSTAMP (compiler-identity stamp) + `-dumpmachine` arch assertion prevent false-green stale-artifact reporting.

### 2.5 Header Hygiene

`forkrun_substrate.h` is: self-contained, include-guarded, FTM-independent (feature-test macros in headers silently alter ABI), and order-independent. The FTM ordering in `forkrun_ring.c` (FTMs → system headers → bash headers → project headers) is load-bearing: glibc's `<features.h>` evaluates FTMs exactly once at first libc include.

---

## 3. The Complete Findings Ledger

### Critical

- **F29:** Resume-sandbox token disclosure. Frame tokens passed as sandbox positionals `$2`–`$5` (visible in `/proc/self/cmdline`); hostile file content executes first and can forge token-bounded frames, executing arbitrary code before the layer-3 consent gate. **FIXED in v3.5.1:** positional close (readonly + shift 5), EXIT-trap emission, parent-side re-render (shape filter + restricted-shell `declare -p` + denylist including `FORKRUN_TRUST_RESUME`). Lock-in: T1g/T1h/T1i/T1a-ext.
- **D10:** `PATH=''` in restricted shells is POSIX-empty-component = CWD resolution. **FIXED in v3.5.1:** both shells use `mktemp -ud` (unique nonexistent path). F6 test hardened to a real assertion.

### Moderate-High

- **F15:** NUMA steal over-claim at EOF orphans the thief's own chunks (silent truncation/hang). **FIXED in v3.5.1:** `goto unified_scanner_eof` → `continue` in the over-claim exit. Lock-in: F15a (conservation) + F15b (EOF-herd stress).

### Moderate

- **D8:** INDEXER_DEATH handler's bare `exec ... 2>/dev/null` persistently redirected fd 2 to /dev/null, swallowing all post-reactor stderr. **FIXED in v3.5.1:** line matches SCAN_DEATH's form (no `2>/dev/null`).
- **F30:** Unchecked `ring_init` failure → NULL deref → SIGSEGV on `--nodes=@513`. **FIXED in v3.5.1:** early-fatal with clean error; `@N` ceiling mirrored bash-side.
- **F28:** `-L` scan loop memchr-per-line on its serialized bottleneck. **FIXED in v3.5.1 (perf-neutral):** `scan_nth_delim()` helper with SIMD skip-ahead; `try_simd_scan` untouched.
- **D6:** INDEXER_DEATH misclassified expected abort-path exits as unexpected deaths (clobbering SLURM 143/138 → 1). **FIXED:** abort-aware classification via `ring_abort_reason` checked before the handler's own `ring_abort`.
- **F31:** CI can silently publish stale blobs (embed job runs `set +e`; verification passes on stale frun.bash). **FIXED (W-F):** decode-and-cmp verification step (not regen-and-compare — the encoder gzip-embeds mtime).
- **D1:** Resume-ledger seqlock reader was missing the ACQUIRE fence before `seq2` (torn snapshot on weakly-ordered arches). **FIXED:** fence at both read sites.
- **F36:** Benchmark matrix measures throughput modes only — no `-L`, `-n`, `-C`, resume, retry benchmarks.

### Minor (selected, most refactor-relevant)

- **F4:** Contract-registry drift across docs (ARCHITECTURE/DESIGN/SHAPES list different contracts under different names). The Stage 3.0 schemas should absorb the cross-file contracts.
- **F17:** `total_lines_consumed` counts batches, not lines (misnomer).
- **F18:** Several `poll(-1)` sites in the engine rely on the fire-alarm blast rather than Shape-3 bounded waits (currently safe; documented hazard).
- **F23a:** `resume_jagged[1024]` silently truncates under extreme out-of-order depth — exactly-once delivery degrades silently.
- **F24:** Dead code: `ring_indexer_main`/`ring_fetcher_main` (legacy flat pipeline), `OOM_WAIT_FOR_MEMORY` macro, `evfd_data`/`fd_escrow[2]` statics.
- **F25:** Scanner `W` is a belief (spawn requests written), not a measurement (actual spawns) — wrapper's spawn count is authoritative.

### Affirmatively Verified (do not re-check)

Every documented contract traced across the four-part review: single-slot claim (one `fetch_add`, no CAS/rollback); ring shield math (UMA `W_max*64` floor 1024; NUMA `RING_SIZE/2`); publish-before-claim (release/acquire); §11 publication triples; EOF evfd write-once/never-read/post-scanner-finished; 3-condition EOF with priority cascade; escrow TATAS + continuous drain; `actual_end` truth table (normal=indexer search+publish; byte=indexer publish only; `-L`=scanner); orderer `sendfile`→copy fallback with EPIPE distinction; H1/M1/H3 cross-file contracts; plugin ABI v2 (128 bytes, dialect negotiation, UMA `numa_batch_id` from claim index); mmap-window stability during `-C` callbacks; output exactness 396/396 benchmark runs; telemetry conservation (Σassigned = Σprocessed, Σstole = Σstolen-from-me); exit-code taxonomy (130/143/138/3/42/200/254, `&0xFF` truncation); signal-coordinated shutdown through the reactor.

---

## 4. Failure Modes & Hard-Won Lessons

### 4.1 Why Weird Idioms Exist (do not "fix" these)

- **`#undef malloc/free/realloc/calloc` after bash headers:** bash hijacks allocators via macros; crossing streams causes heap detonation. The engine uses glibc allocators exclusively.
- **`xfree(argv)` not `free(argv)`:** argv allocated by bash internals (`make_builtin_argv`); must use bash's deallocator.
- **No `mmap` of bash-allocated memory in the scanner:** the scanner's `mmap(NULL, chunk_sz, MAP_PRIVATE|MAP_ANONYMOUS)` buffer sidesteps bash_malloc entirely.
- **`sigprocmask(SIG_BLOCK, SIGCHLD)` around `posix_spawnp`:** shields against bash's job-control reaper racing the spawn.
- **`SIGPIPE` set to `SIG_IGN` around `splice`/`ring_ack`:** prevents kernel assassination when a downstream consumer (`head`) exits early.
- **`PID-recycling no-kill` rule:** `waitpid` failure with ECHILD does NOT trigger `kill()` — the PID may have been recycled to an unrelated process.
- **`-D_GNU_SOURCE` must be set in the TU, not the command line:** CLI defines mask the include-order bug class the canary exists to catch.
- **The `-c` sandbox script must be free of single quotes:** the script is embedded as one single-quoted word in `frun.bash`; any lone quote terminates the word early and scrambles all positionals — silent, total emission loss. The trap action uses a quoteless function name (`_emit_all`), not a quoted string.

### 4.2 POSIX Semantics That Bit Us

- **Empty PATH component = CWD** (POSIX-specified; confirmed empirically by the F6 probe on bash 5.3.9). This is why `PATH=''` in restricted shells was insufficient and `mktemp -ud` (unique nonexistent path) is now used.
- **Bare `exec` with redirections persists them:** `exec {fd}<&- 2>/dev/null` in the main shell permanently redirects fd 2 (D8). Redirections on bare `exec` (no command words) are shell-level, not command-scoped.
- **Output redirection is prohibited inside `--restricted`:** the re-render shell's `2>/dev/null` must be on the whole invocation, not the inner `declare -p`.
- **`ring_abort` is a C builtin returning `EXECUTION_SUCCESS`:** `|| ring_abort` in a subshell converts graceful failures into exit 0 (D2/D6 class of bug).
- **`local _epd="$(mktemp -ud)" || ...` masks the exit code:** `local` returns its own status. Split declaration and assignment.

### 4.3 Test Suite Lessons

- **Tests must route through `bash -c "source '$FRUN_SOURCE' && frun ..."`:** bare `frun` is undefined in the suite shell (T14's original bug; rc=127 permanent red).
- **`--nodes=2` degrades to UMA on single-socket hosts:** use `--nodes=@2` (forced-count) to guarantee the NUMA path (indexers exist) in tests.
- **`xxd` is absent from minimal QEMU/container rootfs:** use `od -An -tx1` (POSIX, always present) — M16 fix.
- **`sort` can segfault on ~900MB inputs:** use `awk` count/sum/min/max for content verification at scale.
- **Signal tests must wait on a readiness signal, not sleep:** the `FORKRUN_TEST_CLEANROOM_PIDFILE` write (placed after trap install) doubles as readiness — a signal before traps are installed is silently mishandled (R10's original failure).
- **`set -o pipefail` needed for exit-code assertions through pipes:** LA4's `_la4_rc` was `head`'s exit code without it.

### 4.4 Context Hygiene (for AI implementation sessions)

- Never stream test/benchmark output through the AI's context — redirect to files, read only summaries and failure lines.
- Every step is idempotent and checkpointed on disk; if a session dies, the next resumes from files.
- Commit after every completed step.
- Long compute legs are launched (`nohup ... &`), not babysat; if longer than the session, write a runbook and hand off.

---

## 5. Stage 1 Contract Seams

### 5.1 State Model

```c
/* Immutable, fork-inherited. Parent fills before fork(); children inherit
   as plain memory. NO config sync verb exists. */
typedef struct fr_config {
    int ring_wid, ring_node_id, ring_wincarn;
    int fd_order_pipe, retry_limit, debug;
    int trap_ack_grace_ms;   /* PROTOCOL CONSTANT (3000) */
    int respawn_cap, spawn_ceiling; /* safety-limit DEFAULTS */
} fr_config_t;

/* C-authoritative runtime state — snapshotted to frontends at boundaries. */
typedef struct fr_state {
    uint64_t batch_idx;
    uint64_t major;      /* 64-bit: 42-bit majors (ABI freeze) */
    uint32_t minor, slots;
    uint32_t num_kills, poisoned;
} fr_state_t;
```

### 5.2 Ownership Graph (dev/supervisor/OWNERSHIP.md)

| Name | Owner | Direction | Timing |
|---|---|---|---|
| RING_WID/NODE_ID/WINCARN | C-config | FE→C | spawn |
| retry_limit | C-config* | FE→C | spawn/init |
| trap_ack_grace_ms | C-config | — | reactor-event (PROTOCOL CONSTANT) |
| batch_idx, major, minor, slots | C-state | C→FE | claim |
| num_kills, poisoned | C-state | C→FE | claim/trap |
| REPLY, RING_BATCH_IDX | bash-surface | C→bash | claim |
| FRUN_CLAIM_BYTES | bash-surface | local | claim/exit |

### 5.3 Packing Constants (single source)

`FR_MINOR_BITS=22`, `FR_MINOR_MASK`, `FR_MAJOR_MASK`, `FR_PACK_KEY` — defined in `forkrun_substrate.h`; static asserts tie `fr_state_t` widths to the frozen plugin-ABI packing; the strong tie is enforced by including the frozen `ring_loadables/forkrun_plugin.h` before the engine's ctx struct. `struct forkrun_ctx` comes from the frozen header, not from a local copy.

### 5.4 The Thunk Migration (Stage 3, not yet started)

Migration order: `ring_claim` (Shape-2 publication semantics intact at moved sites) → `ring_ack` → `ring_call` → `ring_poll`. The X-macro table (`FORKRUN_LOADABLES`) declares each function as `ARGC_ARGV`, `THUNK`, or `BASH_ONLY`; flips are per-function commits; `fr_call_t` is the internal FFI contract (append-only). Control plane may stay argv forever.

**Known argv warts to pin before fixing (Stage 2 inventory):**
1. `--lines=x` magic sentinel (byte mode through the lines slot in `apply_config`).
2. `ring_poll`'s `-1` = clear-all vs. `-<wID>` = clear-worker grammar collision.
3. `ring_lseek`'s argc triform (3/4/5 disambiguating print/whence/var).
4. `-` as TLS-injection sentinel in `ring_escrow_put`/`ring_lseek`/`ring_splice`.
5. `ring_pipe`'s `isdigit` disambiguation of optional capacity.
6. `apply_config`'s nibble state machine (S_DIS/S_MIN/S_DEF/S_MAX/S_USER, special strings `"0"/"-0"/"+0"/"-1"/"x"`).

---

## 6. Security Model & Threat Boundary

**The owner's framing (binding):** forkrun is an engine for running arbitrary code by design. A malicious actor doesn't need to bypass the resume sandbox — they can just change the cmdline. Security that matters is:

1. **File integrity** via ownership/permission gating (600 or `FORKRUN_TRUST_RESUME=1`).
2. **Informed consent** via preview: every consent prompt (hard-reject, soft-reject, layer-3) previews post-parse extracted values (what will RUN), never raw file text.

What F29 closed: code executing without ever appearing in a preview, and forged data executing while the preview showed the file's benign text. What D10 closed: CWD-planted binaries executing pre-consent inside the sandbox.

**The consent gate is the security model.** Making it truthful and non-bypassable is the complete fix. No further sandbox hardening is in scope.

**Documented residuals (accepted):**
1. Pre-consent code execution limited to same-UID file tampering (mitigated by permission gate + informed consent).
2. Same-UID hostile content can shadow the interactive `read` prompt (boundary of threat model).
3. Capture-time `builtin` shadowing could forge verified function text (lands behind layer-3 gate).
4. "Fallow may precede checkpoint" is safe only while resume semantics remain regenerate-from-source.

**Binding scope guard:** no hardening beyond the implemented components, no adversarial tests beyond the specified set (T1a/T1b/T1d/T1f/T1g/T1h/T1i(i)/(ii)/T1a-ext/F6), no broadened residual analysis.

---

## 7. Audit Protocol

### 7.1 The Negative Ban-List (red lines — check every diff)

1. **No CAS retry loops on the fast path.** No sign-bit checks. No speculative multi-slot arithmetic. Workers claim exactly 1 slot via one `fetch_add`.
2. **No rollback of monotonic indices.** No un-publication of slots. No decrements of `read_idx`/`write_idx`/`chunk_queue_*`.
3. **No fence removal or weakening.** The seqlock pair (writer RELEASE + reader ACQUIRE), the §11 publication triples (release-store → SEQ_CST fence → waiter-count check → eventfd write). These look redundant individually and are collectively load-bearing.
4. **No restructuring of `UNIFIED_SCANNER_FLUSH` or `ADAPTIVE_FLOW_CONTROL`.** They implicitly capture ~15 surrounding locals and contain a `break`-as-skip-return embedded in caller loops that also use `break`.
5. **No modification of `try_simd_scan`.** Its NULL-means-unsupported-or-not-found contract is load-bearing for existing callers. New `-L`-only helpers go alongside, not inside.
6. **No `PATH=''` or literal-path constructions in restricted shells.** Use `mktemp -ud`.
7. **The `-c` sandbox script must remain free of single quotes** (comments included).
8. **File twins in lockstep:** `frun.bash` ↔ `frun.nob64.bash`; test suite ↔ `.txt` twin; CHANGELOG ↔ DOCS_ALL; SECURITY ↔ DOCS_ALL.
9. **No post-matrix code changes** (frozen-code policy, MAINTAINERS §5).
10. **Canary stub list may only shrink.** Growing it needs justification in the commit message.

### 7.2 Terminal Verification Gates (check before signing off on any diff)

1. **Parent evals only the re-rendered frame** (`_vars_safe`), never the extracted frame (`_vars_env`) directly.
2. **The denylist includes `FORKRUN_TRUST_RESUME`** (the consent-gate bypass).
3. **`ring_abort_reason` is checked before the handler's own `ring_abort`** (INDEXER_DEATH abort-aware classification).
4. **The indexer subshell has no `|| ring_abort`** (death-class fidelity — the subshell exits with the indexer's own status).
5. **`try_simd_scan` is byte-identical to baseline** (if W-E/F28 diffs are in play).
6. **`limit_cutoff_major` is stored BEFORE the chunk's `cum_lines`/`actual_end` handoff publication.**
7. **`counted` counts every delimiter in `[raw_start, raw_end)` exactly once** (F28 invariant).
8. **Version coherence:** `-V` echo, `FORKRUN_RING_VERSION` fallback, `META`, both test pins, both twins — all must agree.
9. **Twin byte-identity:** pre-b64-marker region + test twins.
10. **`mktemp -ud` construction is split** (local/assignment separated to avoid exit-code masking).

### 7.3 Review Posture

When the owner sends a diff:
1. Identify what is new relative to the last verified state.
2. Trace each change against the ban-list (§7.1) and the verification gates (§7.2).
3. Check for new findings (bugs, regressions, spec violations) — not just whether the change matches the work order, but whether the work order itself had a gap.
4. Produce: (a) a verified-complete list (things not to redo or simplify), (b) new findings with IDs, (c) a work order for the next round.
5. When the work order has a flaw (the implementer catches it), acknowledge it explicitly and correct — this has happened at least five times (the in-restricted-shell redirect, the quote-free invariant, the gzip-mtime regen-compare, the `-L` SIMD fallback placement, the declare-shape filter regex).

---

## 8. Work Order Management Protocol

### 8.1 Structure

Each work order item (W-A, W-B, ...) contains: goal, location (file + function/section), exact change (code or precise description), acceptance criteria (named lock-in tests). One fix per commit; lock-in test in the same commit.

### 8.2 The Commit Sequence Principle

Fix bugs before features; security before performance; housekeeping and version bumps last (so counts/versions reflect the final tree); the blob rebuild necessarily precedes the matrix (the matrix must run the shipped artifact).

### 8.3 Dealing with AI Implementers

- They will find real flaws in your specs — validate and incorporate them.
- They will implement the debugging construction instead of the final decision (D9: `PATH=/nonexistent` shipped instead of `PATH=''`; then D10 superseded both). Always verify against the *current* binding decision.
- They will misattribute bugs to "pre-existing" when they're new (D8: the stderr blackout was attributed to a pre-existing flake; it was introduced by the D6 work). The counterfactual test: did v3.5.0's test suite show this symptom? If yes, it's pre-existing; if no, it's new.
- They will segfault/run out of context on long tasks. The solution is context hygiene (§4.4), not shorter work orders.
- They will leave work half-done at session boundaries. Check every item against its spec, not against "looks reasonable."

### 8.4 The Owner's Preferences

- The owner's background is computational geophysics, not CS. First-principles design; convergent evolution with existing methods.
- The owner makes binding decisions (PATH construction, security scope) and expects them to be followed exactly. When you disagree, state the technical case once, clearly; the decision is theirs.
- The owner values honest reporting over optimistic framing (perf-neutral results reported as such; "what this log does NOT prove" sections; falsification gates).
- The owner runs the full test matrix manually (W-I is owner-only in the current protocol).

---

## 9. Current State (as of this primer)

**v3.5.1 is functionally complete.** All work items (W-A through W-G, D1–D10, F15/F29/F30/F28) are implemented and verified. Version bumps are in (v3.5.1 in all locations). Remaining before release:

1. **D10 verification:** The `mktemp -ud` construction must be smoke-tested (Section T + M + F of the comprehensive suite).
2. **PF-1:** The `twin-check` CI job is incomplete (comment claims frun-twin comparison; run block only `cmp`s test twins).
3. **W-I.1:** Blob rebuild through CI (the shipped blobs predate F15/F28/version bump).
4. **W-I.2:** Owner runs the full matrix manually (both suites × UMA + fake-NUMA × baseline + sanitizers + aarch64 QEMU).

**The v1.3 port plan** is the architecture of record for the Python frontend. Stage 0 (falsification gate) is the next major milestone after v3.5.1 ships: the Python API surface exists (inert stubs under `python/`), the harness skeleton exists, but no measurements have been made. The gate must measure the shipping surface per niche (throughput, RSS, fault isolation) against real incumbents, with hardware disclosure.

---

## 10. Project Rating Context (from the four-part review)

Overall: **8.6/10 (A−), ~95th percentile of serious open-source systems tooling.**

- Documentation: 9.4/10 (99th percentile) — invariant-as-law with audit rules, postmortem→invariant loop, SHAPES.md self-falsifying drills.
- Architecture: 9.4/10 (97–98th) — coordinate-plane economy, born-local NUMA, consensus-free fast path.
- C engine: 8.7/10 (93–95th) — exceptional comment discipline, pure `do_lockfree_claim`, but F15/F28-class edge cases.
- Bash wrapper: 7.8/10 (85–88th) — correct fd choreography and JIT codegen, but F29-class security gaps in the newest code.
- Testing: 8.7/10 (93–95th) — bug-ID regression discipline, metamorphic self-tests, property-based invariants; but adversarial suite missed the token-knowledge attack class.
- Security: 7.4/10 (75–80th) — philosophical 95th percentile, implementation below the project's own bar (F29).

**What moves the number:** F29 fixed + tested → A/A+ territory. F15/F30 similarly. With v3.5.1's fixes landed, the codebase is at that threshold pending the owner's matrix confirmation.

---

*End of primer. The successor's first act upon receiving a diff from the owner should be to read it against §7 (Audit Protocol), produce a verified-complete list plus new findings, and issue a work order per §8. The owner will provide context; this document provides the rest.*
