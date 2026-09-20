# forkrun Changelog

## v3.5.11 (unreleased)

### Python frontend: reactor orchestration (W-PY19)

- **New opt-in `orchestrator=True`** on `run`/`map`/`stream`
  (default `None` = current fork-and-wait behavior, unchanged):
  workers are supervised by a Python reactor (`_reactor.py`) with
  per-worker death pipes (kernel-observable exit, SIGKILL-safe),
  bounded respawn (default cap 3 per slot — crash loops terminate),
  trap-ACK confirmation over a dedicated pipe (3s protocol grace —
  graceful-failure ACKs pair over a signed deaths-minus-ACKs
  balance, so pipelined death/ACK orderings never orphan a grace
  into a false catastrophic), poison `P:idx:kills` notifications,
  and the C orderer for `order="index"`.
- **New shim entry points** (shim only, engine frozen):
  `fr_py_set_order_pipe` (worker-local order-pipe fd for ordered
  acks), `fr_py_scan_with_spawn` (scanner spawn-request pipe),
  `fr_py_orderer` (runs the engine's `ring_order_main` in a forked
  child over the workers' own output memfds — the keyed-record
  framing is unchanged, only the ordering moves from Python
  reassembly into C).
- **Semantics**: healthy-path results are byte-identical to
  `orchestrator=False` (map/run/stream × none/index, splice,
  streaming ingest). A segfaulted worker is respawned and the
  pipeline completes minus the crashed batch (best-effort: a death
  that runs no code leaves no escrow deposit — documented, never
  silent; a stderr recovery note names the wid). Unconfirmed death
  raises `RuntimeError` after the grace; cap-reached deaths raise
  `RuntimeError` immediately. Ingest fork timing stays
  publish-gated (pre-flight bail avoidance); scanner spawn requests
  are mechanism-tested while auto-fork stays disarmed.
- Python `0.9.0` → `0.10.0`. 241 tests green (215 + 26
  `test_reactor.py`); engine frozen (zero `forkrun_ring.c`
  changes).

## v3.5.10 (unreleased)

### Python frontend: zero-copy ingest + raw window (W-PY18 addendum)

- **`fr_py_copy_range`** (shim only): single-shot kernel copy with
  explicit offsets (copy_file_range → sendfile → -1). Drives
  `_spill_to_memfd`; exotic pairs fall back to the original
  sequential loop byte-exact (pipes verified). Measured 130MB spill:
  29ms kernel (4.5 GB/s) vs 33ms userspace — ~20% faster spill, ~3%
  end to end. Never touches fd positions (W-PY16 SEEK_CUR lesson).
- **`fr_py_get_raw_window`**: borrowed MAP_SHARED pointer into the
  ingress memfd (the engine's TLS-cached mapping — the FLAG_RAW
  mechanism v1 plugins already use internally). Readback-exact,
  NULL on bad input; documented lifetime (until remap/exit).
- Splice-loop Part 3 (`fr_py_splice_batch` standalone): not added —
  the loop covers it via sendfile + emit_record fallback (no orphan
  API without a caller).
- Python `0.8.0` → `0.9.0`. 215 tests green (206 + 9
  `test_zero_copy.py`); engine frozen (zero `forkrun_ring.c`
  changes).

## v3.5.9 (unreleased)

### Python frontend: splice passthrough mode (W-PY18)

- **New `mode="splice"`** (payload None, `bytes=N` default 512KB):
  workers run `fr_py_worker_splice_loop` (shim only — claim →
  sendfile → signal → ack, zero Python per batch; framing identical
  so the parent parses untouched). Works over map/stream ×
  materialized/streaming-ingest (bash -s shape: pipe in, live out).
  Strict validation (non-None payload, `lines=`, `run()`, `sink`
  all rejected — an ignored payload would drop user code).
- **Measured, not 2B**: byte+Python 214M vs lines 161M at 10M lines
  (+33%); splice ≈ Python passthrough (56–61M medium, 84M stream —
  both parent-bound: spill/scan/Python-parse). Ceiling analysis:
  sendfile ~4GB/s + parent parse ~3GB/s cap this box at ~230M for
  map(); 2B needs ~26GB/s end to end. Full numbers + model:
  `python/benchmarks/results/splice_study.md`.
- Deviations from sketches: reused `fr_py_claim/ack/escrow/emit`
  (the sketched do_ack_* don't exist); `sendfile` not `splice(2)`
  (no staging pipe; emit_record fallback); payload-accept-anything
  rejected as a footgun.
- Python `0.7.0` → `0.8.0`. 206 tests green (192 + 14
  `test_splice_mode.py`); engine frozen (zero `forkrun_ring.c`
  changes).

## v3.5.8 (unreleased)

### Python frontend: batch-size amortization study (W-PY17)

- **The amortization hypothesis is mostly wrong** (measured, not
  hoped): per-batch cost is ~10ns/line at EVERY size (it scales with
  bytes — no fixed overhead exists to amortize). Forced large batches
  peak at ~96M lines/s (8 workers) / 116M (1 worker) for no-op, not
  the hypothesized 1-2B. New `bench_batch_size.py` (8 sweep entries
  in run_all.py + standalone) with exact batch counts (b'' probes,
  never n/lines estimates).
- **Sweet spot lines=1k–10k** (adaptive already chooses inside it):
  lines=100 loses ~40%, lines=50k+ loses ~35% (starvation: 20 batches
  ÷ 8 workers). Upper/sum gain +4–9% at 10k; JSONL regresses −26%
  at 10k (payload-bound — tune the payload). Streaming +13% at 10k.
  Single worker beats eight for no-op (116M vs 96M — claim contention
  binds, not dispatch). Engine byte-clamps 100k-line requests (21
  batches, not 10). Memory flat 76–80MB across the 100× range.
- Full tables + guidance:
  `python/benchmarks/results/batch_size_study.md`; README documents
  the `lines=` knob and the new `streaming=` parameter.
- Benchmarks + docs only (zero library/engine changes).
  Python `0.6.0` → `0.7.0`. 192 tests green; engine frozen.

## v3.5.7 (unreleased)

### Python frontend: streaming ingest + fd scrubbing (W-PY16 + addendum)

- **Streaming ingest** (`streaming=None/True/False`; fifo/socket
  auto-stream): parent spills in 1MB chunks while a forked scanner
  publishes concurrently and a forked reaper (`fr_py_fallow_loop` →
  the engine's own `ring_fallow_main`, zero engine changes) punches
  holes behind the contiguous acked prefix. Workers fork on first
  DATA publish (new `fr_py_data_ready` query) — never during
  pre-flight — and grow their MAP_SHARED view geometrically
  (zero-copy kept); acks carry the fallow write end. Stall timeout
  (2s) forks workers for slow-source pipelining; empty input skips
  workers; scanner/reaper deaths abort loudly (never silent loss).
- **Measured: 1GB via pipe with 0.2MB parent RSS growth**
  (requirement was <200MB); byte-exact vs materialized across
  python/spawn/plugin modes × map/run/stream; bytes-mode wide lines
  exact. Medium-scale throughput is ~2-3× more CPU than materialized
  (bimodal; under investigation as perf follow-up — capability, not
  speed, is this order's deliverable).
- **FD scrubbing** (`_fd_scrub.py`, all forks): children keep engine
  fds (escrow/eventfds — closing them breaks retry and spins claims)
  + job fds + 0/1/2. forkrun now runs inside event-loop hosts
  (opencode/Jupyter/asyncio): covered by subprocess event-loop tests.
- **Two engine findings documented in code**: (1) the scanner seeds
  its base with `lseek(SEEK_CUR)` on a fork-shared offset — the spill
  uses `pwrite` so the base stays 0; (2) pre-flight bails on waiting
  workers into a phase-1 that publishes nothing for completed input.
- Deliberate non-additions: no `fr_py_ingest_begin/chunk/end` (per-
  chunk scan calls would reset publish state); no signal-carried
  length; GIL already released by CDLL.
- Python `0.5.1` → `0.6.0`. 192 tests green (175 + 10
  `test_streaming_ingest.py` + 7 `test_fd_scrub.py`); engine frozen
  (zero `forkrun_ring.c` changes).

## v3.5.6 (unreleased)

### Python frontend: pipe capacity optimization (W-PY15)

- **Signal pipe 64KB → 1MB** (`forkrun/_pipes.py`, used by
  `_execute_streaming`): 65536 outstanding 16B batch signals vs 4096 —
  workers run further ahead of a moderately slow consumer before
  backpressure stalls them. Best-effort `F_SETPIPE_SZ` with silent
  fallback; fds stay non-inheritable (spawn hygiene preserved).
- **Spawn stdin/stdout already 1MB** (set in `fr_py_exec_spawn` since
  W-PY13) — verified by inspection, covered by a 3MB single-batch
  pump test; no C change in this order.
- **Untouched by design:** engine ack pipe (H3 4KB backpressure
  invariant), escrow/death pipes, `forkrun_ring.c` (frozen).
- Python `0.5.0` → `0.5.1`. 175 tests green (166 + 9 new
  `test_pipes.py`); new `stream_slow_consumer` benchmark row.

## v3.5.5 (unreleased)

### Python frontend: C-level output emit (W-PY14)

- **New `fr_py_emit`** (shim only): one C call per batch writes the
  16-byte header + payload via `writev` (zero-copy for `bytes` returns)
  plus the 16-byte signal; `signal_fd=-1` skips the signal (map/run),
  `out_fd=-1` skips output (discard). Exact v0 semantics preserved
  (`None` = no record, `b""` = empty record; output failure rides
  escrow like a Python write error, signal failure stays fatal).
- **Measured ≈ v0 (±noise), NOT the 63M→100M target — documented, not
  claimed.** Upper map: 26.1M (emit) vs 23.7M (v0) adaptive; 18.6M vs
  18.4M at lines=100 (i9-7940X). Cause: the remaining cost is
  payload-side copies (`bytes(data).upper()`), not output syscalls, and
  map/run already skipped signals since W-PY7 — the real saving is one
  syscall per batch. Kept as permanent infra (fewer syscalls, exact
  semantics); the 100M+ transform goal needs payload-side copies gone
  (write-in-place `OutputBatch`, Stage 6+). New `emit_upper` benchmark
  records the A/B permanently.
- Python `0.4.0` → `0.5.0`. 166 tests green (150 + 16 new
  `test_v1_emit.py`); engine frozen (zero `forkrun_ring.c` changes).

## v3.5.4 (unreleased)

### Python frontend: v1 spawn & plugin fast paths (W-PY13)

- **Spawn v1** (`fr_py_exec_spawn`): C-level `posix_spawnp` + concurrent
  poll pump — zero-copy splice ingress memfd → stdin, stdout staged to a
  reused capture memfd then framed once. 2.1× at small batches (1.05M vs
  0.49M lines/s, lines=100); parity at adaptive batching (~24M both —
  command-bound). Missing command exits 127 (shell convention, retryable).
- **Plugin v1** (`fr_py_plugin_call`): C-level dispatch through the FROZEN
  128B `forkrun_ctx` (dialect from the plugin's `forkrun_use_ctx`, filled
  exactly like `ring_call`) — **bash `-C` plugins run from Python
  unchanged**. Throughput ≈ v0 on transform micro-benchmarks (0.8–1×);
  wins are unification + zero-copy input + no per-batch input copy.
- **Selection is automatic with v0 fallback** (symbol probe +
  parent-side `forkrun_use_ctx` probe — the 72B v0 convention is never
  misdispatched; `FORKRUN_NO_V1=1` forces v0). Caught in development: an
  in-place header backfill that the concurrent streaming reader could
  observe mid-write (whole-batch loss) — fixed by append-once framing;
  every byte visible in an output memfd is final.
- Python `0.3.0` → `0.4.0`. 150 tests green (129 existing + 21 new
  `test_v1_fast.py`); engine frozen (zero `forkrun_ring.c` changes).

## v3.5.3 — 2026-09-20

### Python frontend: benchmark publication (W-PY11, W-PY12, measurement-only)

- **182M lines/s** no-op at 10M lines (bring-up amortized; 102M at 1M).
  Claim/ack via ctypes bypasses bash variable binding.
- **6.4× faster than serial Python** on transforms (63M vs 9.8M);
  **21.5× over multiprocessing.Pool** at large scale (zero-copy fork
  inheritance vs pickle/IPC).
- **3.6M JSONL records/s**, 31M filter, 50M aggregation — production
  data-prep rates, stable across scales.
- **1.8× faster streaming than collection** at 10M (pipelining
  discovered benefit; 1.4× at 1M); ordered-vs-unordered 1.34x.
- **Flat RSS** across 8× stream growth (no output); 39–175MB observed
  on fixed 50MB slow-consumer output (variance disclosed in
  `python/benchmarks/results/large.md`, under investigation).
- **14–15M lines/s spawn mode** (adaptive batching amortizes
  subprocess); 43–54M plugin ctypes callbacks.
- Attributable CPU% per headline row (children-CPU method — system-wide
  /proc/stat rejected as noise on shared boxes); v0.5 reads
  overhead-bound at 10M (parent collect serial), documented honestly.
- New: `python/benchmarks/run_all.py` (table + CSV, --scale/--trials/
  --filter/--list), `make bench[-small|-large|-csv]`, CPU% column,
  `python/benchmarks/results/large.{md,csv}`, README side-by-side
  tables + "What These Benchmarks Do NOT Measure".
- Python `0.2.0` → `0.3.0`. 121 tests green; engine frozen (zero C
  changes since v3.5.2). Tag message ready (owner creates the tag).

## v3.5.2 (unreleased)

- **W-RAW: C-plugin raw window delivery (`FORKRUN_CTX_FLAG_RAW` live):**
  `ENGINE_KNOWN_FLAGS` is now `FORKRUN_CTX_FLAG_RAW` (was `0u`); the
  `fr_ctx_engine_known_flags_matches_v2_grant_semantics` tripwire asserts
  the new known set. `ring_call` dispatches raw-first: when the plugin's
  `forkrun_use_ctx` grants `FLAG_RAW` (v2 only), the engine skips
  `do_tokenize` entirely, passes only fixed args in `argv`
  (`argc = fixed_argc`), and publishes the borrowed zero-copy window in
  `ctx->reserved[0]` (`const void *data` over
  `[batch_offset, batch_offset + batch_byte_length)`). The engine holds a
  persistent per-worker `MAP_SHARED`/`PROT_READ` mmap of the ingress memfd
  (lazy-map on first raw batch, `mremap` growth to
  `max(need*2, file size)`, never unmapped per batch). Precedence is
  binding: raw overrides argv tokenization, stdin delivery, and the user's
  `-s`/`-b` flags (W-STDIN's stdin-feed arm is marked and falls through to
  argv). Raw requires v2 — a v1 plugin requesting the flag gets the grant
  masked to zero, argv delivery, and a dlopen-time warning. Pre-v3.5.2
  engines grant nothing, so plugins must check
  `ctx->flags_granted & FORKRUN_CTX_FLAG_RAW` and fall back to argv.
  Window contract: borrowed (callback duration only), stable-during-callback
  (append-only ingest, private `pread` tokenize buffers, fallow punches only
  behind the acked prefix), address-not-stable across calls, `fd_in` escape
  hatch retained. Docs: `C_PLUGIN.md` §4 (contract, negotiation pattern,
  complete example, stability note); lock-in tests T-RAW-1..7
  (`UNIT_TESTS/test_c_plugins_raw.sh`). No changes to `try_simd_scan`, the
  fences, or the scanner macros.

- **W-STDIN: C-plugin stdin delivery (`-s`/`-b` with `-C`):** the bash JIT
  exports `FORKRUN_C_STDIN=1` for `-C` + (`-s` | `-b`) — the entire
  bash-side change, riding the existing `FORKRUN_EXTRA_VARS` cleanroom
  transport — and `ring_call` fills the dispatch arm W-RAW established:
  `FLAG_RAW` > stdin mode > argv tokenize. In stdin mode tokenization is
  skipped (`argv` = fixed args only) and the batch is spliced onto the
  plugin's fd 0 as an EOF-terminated byte stream. Tier split mirrors
  external `-s`: fitting batches are fed synchronously (no fork); larger
  batches fork a SIGCHLD-shielded feeder child (the `ring_exec` pattern
  verbatim: block around fork, own `waitpid`, restore after) that splices
  concurrently while the parent runs the callback. The child `_exit`s
  (never returns into bash), ignores SIGPIPE, and scrubs the fork-order
  mask-hazard fds (death-pipe write end via the `fd_worker_w` array walk,
  `FD_TRAP_ACK_W`, `fd_fallow_w`) — targeted close, no new bash protocol,
  no `/proc` opens. Failure semantics from process lifecycle: feeder death
  reads as EOF (length-checking plugins fail into escrow/retry; a 0-return
  with a dead feeder is failed by the parent rather than risk short output
  with rc 0; partial-consumption EPIPE `_exit(0)` is never flagged);
  worker death orphaning the child EPIPE-exits it while the death pipe
  fires unmasked. The ctx is unchanged (offset/length/lines/delimiter/fd_in
  populated; v2 length-bounded reads, v1 read-to-EOF); `-b` composes as a
  byte-transparent pipe (no NUL truncation). The old "`-s`/`-b` ignored in
  `-C` mode" warning is removed; `--help` `-C` line documents the new
  semantics. Docs: `C_PLUGIN.md` §5 (contract, v2/v1 patterns,
  implementation note); lock-in tests T-STDIN-1..9
  (`UNIT_TESTS/test_c_plugins_stdin.sh`). No new loadables, no persistent
  processes; the `/proc`-based persistent feeder stays deferred in
  `docs_port/`.

- **W-STAGE1: the substrate's config boundary goes load-bearing:**
  `fr_config_t` (declared in v3.5.1) is now consumed: `ring_worker inc`
  snapshots the bash-surface transport (`RING_WID`, `RING_NODE_ID`,
  `RING_WINCARN`, `FORKRUN_RETRY_LIMIT`, `FD_ORDER_PIPE`, `FORKRUN_DEBUG`)
  into a worker-local struct once per worker — no config-sync verb; the
  Python frontend will fill the same struct via ctypes and fork-inherit it
  as plain memory. Consumers: claim node init + poison threshold (the
  per-claim env read leaves the hot retry path), ack order-pipe, call ctx
  identity; `FORKRUN_C_STDIN` and the feeder-scrub reads stay env (mode
  signaling, not config — taxonomy comments). `WorkerBatchState` fields
  renamed to the `fr_state_t` identity
  (`batch_idx`/`slots`/`num_kills`/`poisoned`, decided at the poison
  branch) with per-field width tripwires beside the substrate asserts
  (whole-struct sizeof is wrong by design: the claim struct also carries
  the payload window). One bash comment (config-injection point, both
  twins). Lock-in T-CONFIG-1..4
  (`UNIT_TESTS/test_c_plugins_config.sh`); basic 91/91, all C-plugin
  suites, T-RAW, T-STDIN green with zero behavior change.

- **P1 residual #5 (docs only):** pre-consent process termination named in
  `SECURITY.md` (+ twin): sandbox extraction precedes the ownership gate
  (F29-B ordering — prompts preview extracted values), so a hostile
  checkpoint can terminate the calling shell before the consent prompt
  fires. Within the documented same-UID tampering boundary (residual #1);
  the sandbox contains the code's effects, not process-signal effects.
  Accepted; no code change (the ordering is load-bearing).

- **Stage 3.0 IDL scaffolding (annotation-only, zero runtime code):**
  `tools/idl_schema.py` (single source: 41/41 loadables, all `ARGC_ARGV`;
  field lists with direction/optionality/PTR+LEN for the migration-order
  four: claim, ack, call, poll), `tools/gen_idl.py` emitting
  `forkrun_callschema.h` (convention companion table + field hooks) plus a
  generated ctypes mirror and usage table; `tools/test_idl.py` (10 tests:
  standalone/order-independent compile, name coverage, byte-exact
  usage/doc equality against the frozen engine table, `--check`
  freshness, ctypes self-consistency); `.github/workflows/idl-check.yml`
  runs both. No `fr_call_t`, no thunk flips (Stage 3 per-function
  commits in v3.5.3+), no usage-string changes.

- **Stage 2 ctypes spike (measurement, zero engine code):**
  `benchmarks/python/ffi_spike.py` against a probe micro-library (not the
  engine): null-call floor 0.179us, claim-shaped 1.717us, claim-ptr
  0.483us, 1MiB MAP_SHARED memoryview 0.207us, Python 8-arg fixed cost
  0.050us (i9-7940X, best-of-7). New `ffi-boundary` row in the Stage 0
  table (+ `results/ffi_spike.json`, report narrative): call overhead is
  four orders of magnitude under the ~10-100ms per-batch budget — Stage 3
  thunk motivation must come from argv parse costs, not call overhead.

- **W-PY1: first working Python frontend (Stage 4 Phase 1 v0, no engine
  changes):** `forkrun.run/map/stream` execute over the C substrate via
  ctypes with no bash in the path. New files only:
  `python/forkrun/_shim.c` (textually includes `forkrun_ring.c` — same TU,
  so statics/TLS are visible — adding non-static `fr_py_*` entry points:
  version/init/destroy/ingest-done/scan/worker-init/claim/ack/escrow/
  abort/poisoned-count; the claim wrapper republishes TLS and decides
  poison exactly like `ring_claim_main`, minus bash binding),
  `python/forkrun/_bindings.py` (loader + `FrPyBatch`), `run.py` (parent:
  init/spill-source-to-memfd/ingest-done/scan/fork/wait),
  `_worker.py` (forked claim/Batch/payload/invalidate/ack loop, `os._exit`
  only, escrow retry / skip / fail-fast), `batch.py` lifetime + lazy
  absolute offsets, `tests/test_v0.py` (15 engine tests). Parent scans
  synchronously before forking (ingest_complete is the scanner's EOF gate —
  set it before scan, not after); workers mmap the memfd whole for
  zero-copy `Batch.data`; `ack(-1,-1)` is a no-op disarm; zero-length EOF
  sentinel slots are skipped like bash (`REPLY != 0`); same-process escrow
  retry preserves bash `-E` counting without a respawn manager. v0 is
  single-node UMA with materialized (bounded) input; spawn/plugin modes,
  multi-node, ordered emitter, resume are staged `NotImplementedError`s.
  Build: `make -f Makefile.substrate python-substrate`
  (`python/forkrun/libforkrun_python.so`, gitignored); CI:
  `.github/workflows/python-check.yml` (fedora + bash-devel, like the
  canary). `Makefile.substrate check` still runs canary + `python/tests`.

- **W-PY2: Python v0 refinements (Python-only, C frozen):** four supervisor
  findings closed. F-PY1 (flush-before-ack): every worker ack funnels
  through `_ack()` (thread-guard + stdout/stderr flush + ack), so
  payload `print()` output survives `os._exit()`; lock-in
  `test_flush_before_ack` (fd-redirected capture). F-PY3 (offset scan):
  `_scan_offsets` uses `find()`-based C-speed search instead of the
  per-byte loop — 24x on a 1MB batch (84ms → 4ms, i9-7940X); lock-in
  `test_offset_scan_performance` (<100ms + absolute-coordinate checks).
  F-PY2 (single-threaded contract): documented in the worker docstring +
  `threading.active_count()` warning at ack (checked, not prevented);
  lock-in `test_thread_warning_and_quiet`. API polish:
  `forkrun.__version__ = "0.2.0"`, `forkrun.__engine_version__`
  (ring_version at import, `"unknown"` when unbuilt), README upgrade path
  (emitter/ordered/NUMA/resume). 6 new tests (flush, perf, thread
  warn+quiet, single-line, lines=500 granularity regression, version):
  36 green. F-PY4 (harness error-class overlap) accepted as-is.

- **W-PY3: result-crossing emitter (§3.9b v0.5, Python-only, C frozen):**
  per-worker output memfds carrying keyed records
  (`batch_idx`/`length` u64 LE + payload bytes) via copy-on-return; the
  parent preads them after waitpid and reassembles over `batch_index`
  (`map(order="index")` sorts; the C orderer is skipped by design). Two
  work-order corrections: output memfds are parent-created PRE-FORK (a
  post-fork child fd is invisible to the parent — the order's worker-side
  creation is unimplementable), and `map()` keeps memfd collection (the
  order's sink-append sketch reintroduces the fork-closure bug: worker-side
  appends never reach the parent list). No new C functions were needed —
  Python writes inherited memfds natively, so the order's `fr_py_output_*`
  API dissolved into ~40 lines of Python. Files are gone (tmpfs memfds,
  tmp-file fallback where unavailable); no Python pipe/queue carries
  payload bytes (purity test extended). 7 new tests (basic, ordered keys,
  None-return, RSS-output-sized boundedness, emitter-vs-sink parity,
  record framing, 4x large output): 43 green. v0.5 drains post-completion
  (bounded by OUTPUT size); true PIPE streaming is v1.

- **W-PY4: fault suites + robustness characterization (Python-only, C
  frozen):** L-series (`tests/test_fault.py`): segfault kills the worker
  without a deposit — survivors drain the rest, parent raises
  `RuntimeError`, no zombies; mixed-fault survivor output is an exact
  input prefix; `MemoryError`/`ValueError` ride the escrow path (poison
  summary on stderr); in-payload `KeyboardInterrupt` retries (once-flag,
  byte-exact). G/Q-series (`tests/test_concurrent.py`): sequential and
  thread-concurrent runs correct via a process-wide `_RUN_LOCK` (engine
  globals are process-wide; parent threads serialize, worker payloads stay
  single-threaded); fd counts stable over 10 runs. Numpy Layer 3
  (`tests/test_numpy_ub.py`): Layer 1 raises; cross-batch live export
  reads intact in v0 (mmap held, no fallow) — recorded as measurement,
  warning text updated, never a contract. RSS (`tests/test_rss.py`,
  subprocess-per-size peaks): parent flat across 4x stream with no output,
  output-sized under `map`. Daemon (`tests/test_daemon.py`):
  double-forked self-terminating daemon survives without blocking
  `waitpid`; inherits the full fd set in v0 (recorded baseline, no
  scrubbing yet). Harness self-test (`tests/test_harness.py`): framing
  codec incl. truncated-tail drops, fd-count helper. 21 new tests:
  64 green.

- **W-PY6: true streaming emitter v1 (Stage 5 Phase 1, Python-only, C
  frozen):** `stream()` yields WHILE workers run. After each memfd record
  the worker emits a 16-byte `(wid, batch_idx)` signal (indices only —
  pipe never carries payload bytes); the parent `select()`s, `pread()`s
  new bytes incrementally (never `read`/`lseek`: the fd description is
  shared with the writing child), and yields in completion order. Slow
  consumer fills the pipe → workers block in the signal write holding
  unacked batches → claims stop (backpressure); abandoning the generator
  EPIPEs blocked writers and reaps everything (verified ECHILD, no
  leaks). `map()` stays on the v0.5 post-completion drain, `run()`
  needs no drain; no `streaming=` param was added (`run`'s
  discard/worker-sink semantics have nothing to stream). 6 tests
  (incremental first-yield, line-multiset exactness, empty, None-return,
   50MB-output slow-consumer parent peak <60MB, streaming within 2.5x of
   collect): 77 green.

- **W-PY7: ordered streaming (Stage 5 Phase 2, Python-only, C frozen):**
  `stream(order="index")` reassembles parent-side over the records'
  batch_idx keys (`_reassembly.py`: add/drain/final_drain + max_size
  diagnostic; drain loop gains order/stats, still yielding blobs).
  Two deviations: no `advance_past_gap` — the parent has no
  poisoned-index channel (only a scalar count), and EOF-anchored final
  flush sorted already skips holes with zero stall risk, subsuming it;
  and no hard `(workers×2)+1` cap — a poisoned head-of-line legitimately
  buffers everything after it, so any cap risks data loss (max_size is
  diagnostic, not a limit). 10 tests: buffer mechanics (ordered add,
  hole-skip final drain, diagnostics), in-sequence/unique indices,
  unordered regression, ordered==map byte equality, idx-gated-sleep
  bound (max ≥3, < total), deterministic poison hole (lines=500 fixed →
  exactly batch 50 of 100; yields all-but-50, max ≥49), empty,
  single-batch: 87 green.

- **W-PY8: Mode 2 spawn — external binaries (Stage 5 Phase 3,
  Python-only, C frozen):** `mode="spawn"` executes a command per batch
  (str split on whitespace, or list argv) via Python `subprocess`
  (`_spawn.py`: batch bytes on stdin, stdout captured, 30s timeout;
  non-zero/timeout/not-found → `SpawnError` → escrow/retry/poison).
  Dispatch coerces eagerly in `run`/`map`/`stream` (spawn+callable raises
  `ValueError` on call, preserving eager validation) and normalizes to
  the engine path — claim/ack/emitter/reassembly never branch on mode.
  Stdin-pipe input transport is inherent to exec and explicitly
  sanctioned; the §3.9 rule governs results (unchanged memfd path).
  v0 overhead ~1-5ms/batch documented (C `posix_spawnp` fast path is v1;
  `frun -X` for peak). 12 tests (validation incl. `_spawn` hygiene,
  cat/gzip/sed-list, mixed grep continuation, not-found poison,
  stdout-only, empty, stream, ordered==map): 99 green.

- **W-PY9: Mode 3 plugin — C callbacks (Stage 5 Phase 4, Python-only, C
  frozen):** `mode="plugin"` takes `"path:function"`, dlopens pre-fork
  and calls per batch through ctypes (`_plugin.py`: explicit in/out
  buffers, lazily allocated 1MB output buffer reused per worker,
  non-zero → `PluginError` → escrow/retry/poison). ABI honesty: the v0
  struct is a deliberately separate Python-side convention
  (`fr_py_plugin_ctx`, 72B, explicit pad) — NOT the frozen 128-byte
  engine ABI, whose argv/stdout mechanism belongs to `ring_call`;
  reimplementing it in Python would duplicate C-owned mechanism. Pinned
  two-sided (C `_Static_assert`s + exact ctypes offsets, incl. the
  `n > out_len` strictness edge). Two findings while implementing: the
  order's sketch mismatches the frozen header field-for-field, and its
  oversize test is unreachable — engine byte batches clamp to
  min(L2, 1MB), so the -2 arm is defense-in-depth (boundary test locks
  1MB-exact success instead). 14 tests (loading ×4, layout pin, basic,
  batch_idx identity, poison, validation ×2, empty, stream, ordered==map,
  1MB boundary): 113 green. v1 unifies via `ring_call`; zero-copy input
  and dialect negotiation ride along.

- **W-PY11: Python benchmark suite (measurement-only, no lib/engine
  changes):** `python/benchmarks/` (harness + throughput/memory/fault/
  baselines/niches + `run_all.py` CLI with --scale/--trials/--filter/
  --list/--csv) plus `make bench[-small|-large|-csv]` targets. Corrects
  five sketch bugs (missing imports incl. a `run_all` NameError, empty
  table crash, deprecated `mktemp`, `memoryview.split`, loop-closure
  batch-size leak) and right-sizes the mp baseline to small scale.
  Harness unit-tested (`tests/test_bench.py`, engine-free). First
  numbers, medium/1M (i9-7940X 28c, median of 5): no-op 102M/s all
  paths, upper 52M, sum 45M, plugin 43M, spawn cat/tr ~14.6M (batches
  amortize subprocess — 100x over the sketch's guess), stream 0.70x
  of map (faster, no collect), ordered 1.01x, 4.6x vs serial / 12.6x
  vs Pool, JSONL 3.4M, RSS flat +0MB (1→8MB), slow-consumer 61MB peak
  on 50MB output. Fault inversion documented: faulty runs score higher
  lines/s because poisoned batches skip payload work. 8 harness tests:
  126 green.

- **W-PY10: Python packaging (Python-only, no engine/library changes):**
  `pyproject.toml` + `setup.py` (`pip install .` / `pip wheel .`), no
  `src/` restructure (`package_dir={"": "python"}`, tests never ship),
  version single-sourced from `__version__` (0.2.0), build_py compiles
  the substrate via `Makefile.substrate` (single flag source; gcc
  fallback), Linux-only fail-fast import (plan §4), no PyPI upload.
  Two corrections: the order's `src/` move is churn without function,
  and its `0.1.0` contradicts the shipped `0.2.0`. 5 tests (Linux
  import, faked-platform guard refusal, setup.py--version parity,
  in-place .so, full wheel→isolated-target→subprocess-run cycle):
  118 green.

- **W-PY5: spawn-time CUDA hazard guard (Stage 4 final item, Python-only,
  C frozen):** `python/forkrun/_cuda_guard.py` (tri-state detection:
  `dlopen(RTLD_NOLOAD)` + `cuCtxGetCurrent` primary — refuses only on a
  live context so torch-importing-but-virgin scripts pass untaxed;
  `/proc/self/maps` fallback consulted ONLY when the primary is
  inconclusive, never overriding a definitive answer), enforced in
  `_execute()` before engine contact or fork with an actionable refusal
  (names the fix: spawn before CUDA init; early-spawn is Stage 6+, not
  advertised as available). Two corrections while implementing: the
  order's `ctypes.RTLD_NOLOAD` does not exist (it lives on `os`), and its
  fallback reading would over-refuse virgin scripts. 7 contract tests
  (clean import, actionable message, tri-state precedence lock-in via
  mock, virgin-torch and live-CUDA subprocess drivers, simulated-hazard
  run refusal, real-run integration): Stage 4 complete.

## v3.5.1 — 2026-09-17

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

- **W-B: cleanroom test determinism (pidfile + R2/R10):** the chaos pidfile
  (`FORKRUN_TEST_INDEXER_PIDFILE`, same pattern as the fallow pidfile) is
  written after trap install so signal tests target the right process;
  R2/R10 rewritten with bounded pidfile waits on `--nodes=@2`; D6
  exit-code preservation locked (trapped-signal codes survive, no spurious
  FATAL on clean early exit). Lock-in: LA3 (violent indexer death) / LA4
  (clean `| head` abort) plus the R2/R10 signal tests.

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
  SECURITY.md). `PATH=''` retained per owner determination at the time —
  superseded by D10 below, which closes F6 by construction.

- **D10: dead-PATH construction for both restricted shells:** POSIX PATH search
  treats an empty component as the current working directory, so `PATH=''`
  is NOT a dead PATH (F6 probe: a CWD-planted binary executed under `PATH=''`;
  no default-PATH fallback). Both restricted shells (the extraction sandbox
  and the re-render shell) now run with `PATH` at a freshly-created,
  immediately-deleted mktemp directory: it cannot contain an executable and
  its random name cannot be pre-created or guessed (mktemp creates it 0700;
  only mktemp failure is fatal — an empty name would silently restore CWD
  semantics — and aborts before either shell runs). F6 is upgraded from a
  characterize-only probe to a hard assertion (marker absent = PASS); the
  sandbox's remaining pre-consent execution surface is pure builtins
  (DoS-only). See SECURITY.md Layer 2.

- **F31: emit fallback resumes after a partial sendfile (v3.5.0 review
  finding, still present):** `forkrun_emit_with_fallback` fell through to
  a full-range `ring_copy_chunk(off, len)` after ANY non-EPIPE sendfile
  outcome — including a positive-short partial, which re-emitted the
  already-written `[off, off+s)` prefix (duplicated bytes in that batch's
  output). Pre-existing since the v3.4.3 O_APPEND fallback with an exotic
  trigger (short-positive followed by a hard error in the same batch);
  ordering and the resume ledger are untouched (duplication is
  content-within-one-batch; `TRACK_COMPLETED_BATCH` tracks declared
  length). Fix: on `s > 0` resume the copy at `(off+s, len-s)`; on `s < 0`
  non-EPIPE keep the full-range copy (`robust_sendfile` returns -1 only
  with zero progress, so it is exact — this differs from the review
  sketch, whose resume arithmetic is only valid for `s > 0`). Verified by
  an LD_PRELOAD sendfile-interposition harness against the exact TU
  (old: +64 duplicated bytes; fixed: byte-exact; hard-fail-first: exact
  in both) plus the basic suite 89/89 on a locally built v4 blob.
  Engine change — blobs rebuilt via CI; the owner matrix must be re-run
  before tag.

- **W-LA3: LA3 violent-death test redesign (sleep-operand root cause):**
  LA3 wedged on every budget — not an engine hang but 84-minute payloads:
  line-args mode runs `sleep 0.01 ${lines}`, and GNU sleep SUMS operands
  (batch 1 ≈ 5050 s; ≈ 3,970 CPU-years total). The same root cause explains
  the emulated abort-hang (teardown waits on in-flight payloads — benign,
  pre-existing, now documented) and why R2/R10/LA4 always passed (`-s` /
  `printf` payloads). No engine defect found anywhere in the chain.
  Redesign, test-side only, both twins: `printf` payload, endless
  SIGPIPE-clean feeder (indexers exit status-0 at ingest EOF, so finite
  input lets them die before the kill), liveness-gated kill (kill -0
  before, death-verified after), five-fact failure capture
  (rc/live/sent/dead/fatal/gen/cp/tmp). Verified 3× standalone plus full
  Section L 57/57 on x86_64. Also fixed in this round: NEW-D1 (F8 now
  `--nodes=@2`, forced-count NUMA arms, still green).

- **F28: `-L` scan loop off memchr-per-line (SIMD skip-ahead, perf-neutral):**
  the `-L` Scanner-Handoff Chain loop walked one `memchr` per line on the
  serialized scanner. New `-L`-only helper `scan_nth_delim()` jumps straight
  to the need-th delimiter (`try_simd_scan` skip-ahead on SIMD arches, exact
  memchr-per-line fallback elsewhere); the loop claims `need = L -
  lines_in_batch` clamped by the `-n` budget, tail-counts stragglers once
  with `fast_count_delim`, and flushes via the unchanged
  `UNIFIED_SCANNER_FLUSH` sites (`counted` still counts every delimiter in
  `[raw_start, raw_end)` exactly once; `is_last` still `bnd >= raw_end`; no
  `BytesMax` capping — exact lines cannot be byte-capped). `try_simd_scan`
  is byte-identical (its NULL-means-unsupported-or-not-found contract is
  load-bearing for the normal scanner). Measured before/after on 100M-line
  `seq` input (889MB, `--nodes=@2` to hit the handoff path, x86_64_v4,
  single runs): -L 1000 file/pipe x default/-k 9.78–9.99s before vs
  10.00–10.15s after; -L 10000 9.46–9.55s before vs 9.67–9.78s after;
  interleaved A/B re-runs (L1000 file default x3 each) 10.02–10.15s vs
  10.09–10.18s — noise, no systematic gap. Verdict: scan is not the binding
  constraint here (no-op-payload isolation: `-L 1000 :` 5.82s vs `-l 1000 :`
  5.78s; ingest/payload dominate), so the change is a structural
  call-amortization win that does not move end-to-end on this box.
  BORN_LOCAL_NUMA §5's "≈ UMA scan speeds" claim re-confirmed, no update.
  Acceptance: F7 carry-math exact, T9/T10 `-n`-clamp unchanged, new F8
  (`-L`+`-n` clamp L=4/7/100 x n=37) green on both blobs, `-L`+`-n` probes
  bit-identical across 4 shapes. Notes: initial UMA befores measured the
  wrong path (handoff requires `is_numa`) and are superseded; `-L 100000`
  is pre-existing-unstable on BOTH blobs (intermittent worker-139/trap-grace
  aborts with clean-prefix truncation, rare count anomalies) — out of scope;
  one unreproduced `-L 100` short-count transient (99 lines, 1 of 8 runs,
  rc=0) on the pre-W-E tree; system `sort` segfaults on 889MB here, so
  content checks used awk count+sum+min+max instead.

- **New/changed tests this release:** T14 (F30 ceiling; invocation fixed by
  W-D4), F15a/F15b (conservation + herd; Node-frame presence tightened by
  D8), T1g/T1h/T1i(i/ii)/T1a-ext (token-knowledge forgeries, F29), F6
  (characterize-only CWD probe), F8 (`-L`+`-n` clamp, F28). Deduplicated:
  simple M17/M20/M21 removed (diagnostic variants kept), both T10b_diag
  blocks removed (diagnostics folded into T10b's failure path).

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

### Invariants (new in this release — see INVARIANTS.md §11, §13–15)

- Gate publication & producer wakeup invariant.
- No sole-path data movement: every zero-copy syscall has an exercised fallback.
- Gates inspect text, never live state derived from executing that text.
- Sanitize by construction (`env -i` + explicit values), not by clearing.
