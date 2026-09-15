# forkrun Python Frontend — Port Overview & Reference Plan

**Status:** Design reference, **v1.3 — FINAL.** Nine external reviews across three rounds; convergence reached (v1.0 structural findings → v1.1 contract seams → v1.2 sub-clauses → v1.3 wording/decisions). **This is the architecture of record for implementation.** No further revision rounds; the next thing that settles remaining uncertainty is Stage 0. Supersedes v1.2.

---

## 0. Summary & Principles

The port does not port the algorithm — it ports the boundary. forkrun's substrate (FAA claiming, the coordinate plane, born-local NUMA, fallow, escrow/poison resilience, adaptive batching) is language-independent because ownership flows through monotonic coordinates, not language objects. The port makes that latent property structural by extracting the language-independent machine from the bash orchestration, then adding Python as its first new customer. The reactor and worker lifecycle are policy-heavy and data-light — the shape where a high-level frontend is natural.

**The invariant running through the whole design:** *The C substrate owns synchronization and authoritative state; the frontend receives explicit, bounded snapshots or borrowed batch data at defined boundaries — and nothing else.*

**The incremental ladder — the port's central risk-control mechanism:**

```
Bash
 → Bash + explicitly-owned C state        (Stage 1)
 → Bash + standalone C substrate          (canary links)
 → Bash + typed C boundary                (Stage 3, per-function)
 → Bash + Python both drive substrate     (Stage 2/4)
 → Python frontend                        (Stage 4+)
```

**There is never a moment where you have to believe the port.** Each rung: a local invariant, a bounded change, an observable test. The principle applies twice: *runtime — less coordination → more scalability; development — less simultaneous change → more verifiability.*

**Guiding principles:** (1) every step independently shippable, `frun.bash` never broken; (2) verification contracts, not just green matrices — ask what the matrix can see; (3) demand pulls scope; (4) the engine is not being ported; (5) **ownership taxonomy:** C owns mechanism, engine invariants, protocol constants, and default safety limits; the frontend owns user-selected policy, presentation, and orchestration *decisions*; bash owns compatibility presentation.

---

## 1. Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       forkrun_core.c                        │
│  All engine logic. Zero bash linkage — enforced by BUILD:   │
│  libforkrun.so links with strict unresolved-symbol checking │
│  (-Wl,--no-undefined) + explicit allowed-dependency set.    │
│  State: fr_config_t (immutable, fork-inherited, incl.       │
│         protocol constants & safety-limit defaults)         │
│         fr_state_t  (C-authoritative, snapshotted)          │
└───────────────┬─────────────────────────────┬───────────────┘
       ┌────────▼─────────┐         ┌─────────▼──────────┐
       │  bash frontend   │         │  python frontend   │
       │ WORD_LIST→argv→  │         │ Batch object;      │
       │ struct converter │         │ typed structs via  │
       │ ring_ctx syncer  │         │ ctypes — process-  │
       │ (compat surface) │         │ local snapshots    │
       └──────────────────┘         │ only               │
                                    └────────────────────┘
```

**Build targets:** `forkrun_ring.so` (existing product); `libforkrun.so` (standalone canary, link-checked); Python wheels (Linux wheels for the architectures the standalone core supports and the chosen Python build/packaging system can reliably handle — x86_64 + aarch64 as initial targets; "manylinux" naming is a packaging decision, not an architectural commitment; tied to reproducible-builds/signing before first PyPI release).

**Load-bearing inherited facts:** argc/argv uniformity; `do_lockfree_claim`'s pure core; plugin ABI v2 as the Python-facing data contract; the mmap stability guarantee as the delivery contract (bounded at invalidation, §3.5); process-level resilience inherited whole.

---

## 2. Stage 0 — Falsification Gate

**The question:** *Is there a compelling performance / resource / fault-isolation niche conventional Python parallelism does not fill?*

**Prerequisite (new in v1.3):** the v0 public API surface exists before the benchmark, because the gate must measure the shipping surface — including how `source=` and `sink=` plumb — or it validates an API that won't ship. The API sketch (§3.0) is part of this spec; the Stage 0 harness builds against it.

**Multi-axis, per-niche, published table:**
- **Throughput per niche** (JSONL ingestion, tokenize-to-tensor, per-record transform, TB streaming), gated per niche; 3–5× = strong-win threshold, not minimum viability.
- **Peak RSS vs stream size** — first-class.
- **Fault isolation — empirical, incumbent-specific:** named configurations under a worker-segfault workload; document pool usability / completed work / batch continuity versus forkrun. No generalized claims.
- **Injection harness:** payload SIGSEGVs on a marked record (ctypes null-deref or corrupt archive); assertions on run completion, poison summary, output completeness minus the quarantined batch.
- **Hardware disclosure column:** the TB-streaming row is bandwidth-bound; run it on the rented-EPYC day or label the hardware.
- **Baselines:** real incumbents per niche; naive multiprocessing as a context row only.

**Exit:** compelling niche → proceed (noting which); nothing anywhere → stop.

---

## 2.0 Preconditions / Portability-Correctness Gate

**Scope discipline:** engine fixes limited to what Stage 1 builds state-ownership on — the resume-ledger fence pair and the indexer-death escape. Not a general bug waystation.

- **Indexer-death fix must be kernel-observable:** SIGKILL/OOM runs no code; `|| ring_abort` and traps structurally cannot be the mechanism. Shape-3-consistent design: an indexer death pipe mirroring `fd_scan_death_*` (kernel teardown → POLLHUP → reactor → alarm).
- **These fixes ship unconditionally as v3.5.x bugfixes** — the port's first commits improve the product even if the port dies.
- **Housekeeping fold-in:** v3.5.x doc-arithmetic drift, test dedup, CI verify step — release hygiene in this commit window, explicitly non-engine. Dead artifacts pruned during the grep inventory; deliberately-kept symbols stay documented.
- **aarch64 matrix leg** (qemu): unit suite + targeted `-n`/`-L`/resume stress, once per stage thereafter.

---

## 2.1 Stage 1 — Store/State Refactor

**State model (v1.2 widths, retained):**

```c
/* Immutable, fork-inherited. Parent fills before os.fork(); children inherit
   as plain memory. Python has NO config sync verb. Contains protocol
   constants and safety-limit DEFAULTS — both reactors read them; neither
   hardcodes them. The 3s trap-ACK grace is a protocol constant; whether a
   given invocation respawns is frontend policy. */
typedef struct fr_config {
    int ring_wid, ring_node_id, ring_wincarn;
    int fd_order_pipe, retry_limit, debug;
    int trap_ack_grace_ms;   /* protocol constant */
    int respawn_cap, spawn_ceiling; /* safety-limit defaults */
} fr_config_t;

/* C-authoritative runtime state — snapshotted to frontends at boundaries. */
typedef struct fr_state {
    uint64_t batch_idx;
    uint64_t major;        /* 64-bit: 42-bit majors. v1.1's uint32_t
                              reintroduced the truncation the v3.5.0 ABI
                              freeze eliminated. */
    uint32_t minor, slots;
    uint32_t num_kills, poisoned;
} fr_state_t;
/* static_assert: fr_state_t widths tied to plugin-ABI packing constants —
   two views of one coordinate system must never disagree. */
```

**Ownership graph (every mutable value gets one authoritative owner):** the inventory table with owner/direction/timing columns, per v1.2 — `RING_WID`/node/incarn (C config, spawn), retry/grace/caps (C config defaults, overridable at spawn), `batch_idx`/`major/minor/slots` (C state, claim snapshot), `num_kills`/`poisoned` (C state, claim/trap), `REPLY` (bash output surface, C→bash bind).

**Categories A–D, migration mechanics, same-commit ritual removal:** unchanged from v1.1/v1.2.

**Standing rules (updated):** no `fr_get_state()` — state travels with the claim; own, don't query. Workers never read `fr_state_t` on any hot path — the claim out-param is the worker's only state channel. Reactor state reads: typed struct reads at event frequency only. **Python never raw-reads mutable coordination words (claim counters, escrow slots, poison flags) from MAP_SHARED — the fences live in C. This rule governs coordination words only, never the payload-byte window, which Python reads directly per §3.5 — `batch.data` is a MAP_SHARED view by design and is sanctioned.**

---

## 2.2 Stage 3.0 — The Typed IDL Prerequisite

Usage strings are prose; codegen over prose inherits the ambiguities whose fossils the Stage-2 spike inventories. **Three schemas, one generation pipeline** (not one mega-schema — call-args, state-ownership, and doc-metadata are different kinds of objects):

```c
/* call-schema: direction, optionality, and PTR+LEN from v1 (the migration
   order's own first functions need them: ring_claim's VAR out-param,
   ring_lseek's whence/var/print triform, ring_poll's fd-array+count). */
X(ring_call, ring_call_main, THUNK,
  FR_CALL_FIELDS(
      IN_I32(fd), IN_U64(length), IN_U8(delim),
      IN_STR(so), IN_STR(fn),
      IN_I32(fixed_argc), IN_PTR(fixed) /* PTR+LEN pair */))
```

Generated from the schemas: C parse code, `fr_call_t`, ctypes definitions, the key table, **and the usage/doc strings** (usage strings become outputs, never inputs). CI checks generated artifacts match committed ones. One sanctioned string surface: `ring_init`'s flag grammar (called once, FLAGS.md-documented), optionally replaced later by a typed `fr_pipeline_config_t` generated from the same schemas — string parser generated from it too.

**Thunk mechanics (retained):** one entry point per function, X-table declared (`ARGC_ARGV`/`THUNK`/`BASH_ONLY`); flips are per-function commits; control plane may stay argv forever; `fr_call_t` is internal FFI contract, append-only regardless.

**Flip parity — parser-level golden fixtures:** argv→`fr_call_t` field dumps (where divergence actually lives); behavior covered by the existing matrix; any behavioral fixtures are per-topology.

**Migration order:** `ring_claim` (Shape-2 publication semantics intact at moved sites) → `ring_ack` → `ring_call` → `ring_poll`.

---

## 3. The Python Frontend

### 3.0 The v0 Public API (new in v1.3 — exists before Stage 0)

```python
forkrun.run(
    payload,                 # "pkg.mod:func" (blessed) | callable (simple-case
                             #   source-ship) | "plugin.so:fn" (mode 3)
    source,                  # path | fd | pipe/socket  (iterables REJECTED — §3.5)
    *,
    mode="python",           # "python" | "spawn" (external) | "plugin"
    sink=None,               # None → built-in emitter (§3.9b); callable →
                             #   on_batch(batch_meta, result) payload-side
    order="none",            # "none" (default) | "index" (parent reassembly)
    lines=None, bytes=None,  # batching controls (-l / -b analogues)
    workers=None, nodes="auto",
    on_error="retry",        # bash -E analogue: retry-then-poison (default)
)
# Convenience wrappers (thin, over run()): forkrun.map(...), forkrun.stream(...)
```

Stage 0 benchmarks measure *this* surface. Signature details may evolve; the surface's shape (source/sink/mode plumbing) is what the gate validates.

### 3.1 Access tiers
python-compat (ctypes argv spike — measured, not final), python-fast (thunks; extension-module/Cython decided by profiling), plugin (`-C`).

### 3.2 Process model
One worker process per parallel Python execution context. `os.fork()` before any threads in the parent. **No native-library initialization in the parent before fork** — workers import payload dependencies post-fork. `os._exit()` in workers. **Fork order (new):** the orchestrator forks fallow and orderer as *mechanism* processes (C protocol-constant consumers, not Python policy) before worker forks — fd-inheritance tables depend on this order. **v0 workers are single-threaded (new):** payload-spawned threads sit outside the borrowed-lifetime contract and are documented as unsupported. CLOEXEC doesn't survive fork: documented helper + tests (§3.7).

### 3.3 Worker loop
Strategy-injected payload; no per-batch reset ritual. **Invalidation kills the data views, not the batch metadata (clarified v1.3):** the loop retains the in-flight `Batch` reference after view invalidation so the `finally` path deposits the escrow packet with live coordinates and kill count. **Payload exceptions follow bash `-E` semantics exactly** — deposit + trap-ACK + non-zero exit → respawn → retry → poison at limit; non-divergence between frontends is the contract.

### 3.5 Mode 1 — The `Batch` Object

```python
class Batch:
    batch_index: int            # global ordering key
    byte_offset: int; byte_length: int
    line_count: Optional[int]   # None = undefined (-b byte mode). The C ABI
                                # layer keeps its 0-means-undefined convention;
                                # the Python wrapper maps 0 → None. One
                                # sentinel per language layer.
    data: memoryview            # borrowed
    offsets: memoryview         # borrowed; LAZY; ABSOLUTE plane coordinates
                                # (one-currency rule; relative slicing is a
                                # helper). Buffer lifetime tied to Batch
                                # invalidation (release-before-realloc).
    def copy(self) -> bytes: ...
```

**Borrowed-lifetime contract — layered:**

```
claim() → Batch valid → payload(batch) → [invalidate views at return] → ack()
```

- **Layer 1 — enforced (direct views):** at invalidation the frontend releases the owned views; post-release direct access raises an exception (observed: `ValueError` on `memoryview` — documented behavior, not contract; the contract is the lifetime).
- **Layer 2 — enforced (timing):** invalidation at payload return; stashed views fail at first post-return access.
- **Layer 3 — unenforceable, UB-by-contract:** exported buffers (`np.frombuffer`) hold their own references; past invalidation, fallow may PUNCH_HOLE: silent zeros or SIGBUS. Stage 4 test characterizes actual behavior; warning text written from the measurement.
- **Layer 4 — sanctioned persistence:** `batch.copy()`.

**Offsets:** `fr_batch_offsets` is a non-mutating scan (the borrowed window's immutability is load-bearing — never NUL-swap the shared memfd); lazy materialization; fused-vs-second-pass measured in Stage 4. "Zero-copy" = payload bytes; offsets metadata may copy.

**Code crossing:** module path blessed **because it is the fork-safety mechanism** — module-path strings keep the parent virgin of native threadpool imports; the worker imports post-fork (the Fork Memory Paradox, stated in-plan and in user docs). Source-ship: simple-case v0 placeholder, documented caveats. Pickle: never. AOT/`-C`: migration story.

**Ingestion sources:** `source ∈ {path, fd, pipe/socket}`. Iterables/generators **rejected in v0, with the reason stated**: an iterator would make the Python interpreter part of the ingestion datapath, destroying the engine's ability to maintain bounded, kernel-fed streaming independently of Python scheduling. Python never an input pump.

**Error crossing:** process-level machinery inherited whole; traceback capture in the wrapper; fault isolation is a first-class Stage 0 measurement.

### 3.6 GPU/CUDA policy

**v0 Python-native workers are CPU-only by default; GPU-holding workers are an explicit advanced mode outside the normal v0 contract.** GPU transfer happens in the parent/consumer (the `DataLoader` mental model: swap-in, not restructure).

**Spawn-time guard — conservative CUDA-fork hazard detection (reworded v1.3; precise mechanism updated):** primary check `dlopen("libcuda.so.1", RTLD_NOLOAD)` + `cuCtxGetCurrent` (definitive, cheap, refuses only on a live context — doesn't tax torch-importing-but-CUDA-virgin scripts); `/proc/self/maps` libcuda scan as fallback where dlopen is unavailable. Over-refusal remains in the safe direction; the heuristic's limits are documented. **The test asserts the user-visible contract — hazard detected → clean refusal → actionable message naming the fix (spawn before importing torch) — not the detection mechanism**, keeping the heuristic replaceable. Test (b): early-spawn escape hatch (demand-pulled, inverted check at the early-spawn point).

### 3.7 Reactor
Python owns policy *decisions*; C owns mechanism, engine invariants, and protocol constants (§2.1 taxonomy). L-section fault suite ported as Python tests at Stage 4. **Parity additions (v1.3):** G/Q-series ports (sequential and concurrent invocations in one process), a Section-K-analogue harness self-test, and the **payload-forks-daemon test** — where the documented fd-cleanup helper explicitly covers death-pipe and trap-ack fds (CLOEXEC won't save you without exec). `os.waitpid` explicitly; ECHILD lesson carried; bounded-poll discipline.

### 3.8 Signals & recovery
Unchanged: `try/finally` (never `atexit`), signal mapping, trap-ACK verbatim, death-pipe for what the interpreter misses, native traceback capture.

### 3.9 Result-crossing contract

Three mechanisms (decided in v1.2; v1.3 closes the two remaining seams):

- **(a) Payload-side sink — v0 default where applicable.** The payload callable IS the sink; zero crossing cost.
- **(b) The C unordered emitter — built-in bytes-to-parent.** Per-worker output memfds → ack packets → kernel-assisted drain → **destination is a PIPE (decided v1.3):** the closed hydraulic loop extends to the parent for free — parent reads slowly → pipe fills → orderer blocks → acks block → workers stop claiming → ingest yields. The TB-streaming niche keeps its defining property on the built-in path. Parent-side collect-all is a bounded convenience, same rule as scatter-to-dict. **Output-side API (decided v1.3): copy-on-return for v0** — payload returns `bytes`/`ndarray`/None; the wrapper copies into the per-worker output memfd; the copy is stated, measured in Stage 4, and honest about its cost. Rationale: input is the TB-scale side where zero-copy is the differentiator; output in the lead use case is a small processed artifact per batch where a copy is noise. **Write-in-place output (`OutputBatch`) is demand-pulled Stage 6+** — if a niche shows the copy dominating, it gets its own lifetime-contracted subsection (inheriting every Batch problem in the harder, write direction).
- **(c) Python pipe/queue IPC for payload bytes: forbidden.**

**The emitter's contract, stated (v1.3):** the emitter transports completed batch results; it does not make Python responsible for engine output ordering. `batch_index` = execution identity / ordering key; C emitter = transport; Python parent = optional consumer-side reassembly. Skipping the C orderer in v0 is safe *because* ordering is a parent-side choice over a keyed transport — not a disabled correctness component. The tracker runs in this path, so the resume ledger is maintained (resume *UX* remains Stage 6).

**Flush-before-ack (new standing rule):** the wrapper flushes all payload-facing buffered streams between payload return and `fr_ack` — an ack before flush emits a short range and the ledger records a lie.

**Stage 4 RSS verification test (new):** long-running payload with intentionally delayed consumer; measure RSS vs stream size; assert no linear accumulation. Stage 0 measures the engine's end-to-end boundedness; Stage 4 verifies the *frontend* didn't break it — a Python wrapper can reintroduce buffering even when the C engine is perfectly bounded.

---

## 4. Platform & Distribution
Linux-only, fail-fast import off-Linux (stated scope). Linux wheels for archs the standalone core supports and the chosen build system reliably packages (x86_64 + aarch64 initial); tied to reproducible-builds/signing before first PyPI release.

---

## 5. Stage Sequence

- **Stage 0** — falsification gate. **Prerequisite: the §3.0 API surface exists** (the gate measures the shipping surface). Per-niche, multi-axis, hardware-labeled, injection-harnessed, incumbent-specific.
- **Preconditions gate** — fence pair + kernel-observable indexer escape (ship unconditionally as v3.5.x); housekeeping fold-in; dead-artifact pruning; aarch64 leg established.
- **Stage 1** — store refactor (fixed `fr_state_t`; ownership graph; config-via-fork; protocol constants in store; link-checked canary in CI).
- **Stage 2** — ctypes spike (measured FFI cost; argv-wart inventory, labeled scaffolding).
- **Stage 3.0** — typed IDL, three schemas, one pipeline (direction/optionality/PTR+LEN from v1); CI artifact checks.
- **Stage 3** — thunk flips (parser-level golden fixtures; Shape-2 semantics preserved).
- **Stage 4** — Python v0 (Batch object; §3.0 API; sink-first + pipe-destination emitter with copy-on-return; spawn-time CUDA guard with refusal-contract test; L+G+Q fault suites; K-analogue self-test; payload-daemon test; numpy-past-invalidation characterization; delayed-consumer RSS test; module-path payloads + simple-case source-ship).
- **Stage 5** — modes 2 & 3; ordered output.
- **Stage 6** — demand-pulled: resume UX, halt, TUI, sweeps, hardened source-ship, early-spawn GPU hatch, `OutputBatch` write-in-place (if a niche demands it).

---

## 6. Standing Rules & Risk Register

**Rules (cumulative, final):** fork before threads; no parent-side native-library initialization (worker-side imports post-fork); `os._exit()` in workers; **fork order: mechanism processes before workers**; v0 workers single-threaded; bytes/memoryview default, decode opt-in; module-path blessed (the why documented); never pickle; CPU-only default + spawn-time hazard refusal (detection is a documented, replaceable heuristic); Python never raw-reads **coordination words** from MAP_SHARED (payload-byte window explicitly sanctioned); no worker hot-path `fr_state_t` reads; no `fr_get_state()`; views die at payload return (enforced where Python allows, UB-by-contract where it doesn't); `batch.copy()` for persistence; source ∈ {path, fd, pipe} — Python never an input pump (reason stated in-plan); no Python IPC for payload bytes; **wrapper flushes payload-facing streams before ack**; protocol constants from the store; flag-gates-a-reserved-slot for new plugin mechanisms.

**Risk register:** v1.2's plus: output-copy cost (measured Stage 4; `OutputBatch` demand-pulled); emitter parent-side boundedness (pipe destination — closed); numpy-export-past-invalidation (characterized, UB-documented); API-surface/benchmark divergence (§3.0 prerequisite — closed).

---

## 7. Documentation & Contract Prose
Frontend-neutral rewrites in Stage 1; key-table header as single source. **Exit-status parity table** (130/143/138/3/42/200/254, `&0xFF` map) — both frontends agree by table.

---

## 8. Not Ported & The Meta-Result

Unchanged: the engine (95% of value, 0% of port); the bash JIT; `ring_map`; bash's in-runtime builtin calls.

**The meta-result:** the port's primary product is a language-independent substrate made *structural* rather than latent; Python is its first customer. The process mirrors the runtime: ownership established once, verified in small bounded steps — consensus eliminated at runtime, large-scale uncertainty eliminated in development.

**And the closing note for this document (v1.3, final):** the next thing that settles remaining uncertainty is not another revision — it's Stage 0. The first code written for this port should not be Python code at all, but the benchmark that determines whether Python deserves to be the next customer of the machine that v3.5.0 just finished turning into a clean substrate. The three artifacts that follow this document, in order: **the Stage 0 published table** (per-niche gates, hardware column, injection results — the last place an overclaim can enter the public record), **the preconditions commit pair** (fences + indexer death pipe, with the first aarch64 leg log), and **the IDL/key-table header**. When those exist, this plan has done its job, and the repo takes over.

---

*Design lineage, final form: every load-bearing boundary extends a structure that existed for unrelated reasons — argc/argv (WORD_LIST avoidance), `do_lockfree_claim` (auditability), the plugin ABI's negotiation machinery (frozen "for changes you can't predict"), the mmap guarantee (documented for `-C`; now the Python delivery contract). Three review rounds took the plan from architecture → contracts → sub-clauses → decisions, converging exactly where a healthy process should: at the point where further review generates hypothetical edge cases faster than real findings. The plan is specification-complete. Preserve the property through implementation: every commit should leave behind the boundary the next stage wants to find.*
