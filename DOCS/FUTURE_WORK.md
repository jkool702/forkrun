# Complete Future Work Register

## Everything Not Yet Implemented, Organized by Priority and Category

---

## Tier 1: Release Blockers (Required for v3.6.1 Tag)

| # | Item | Status | Effort | Description |
|---|------|--------|--------|-------------|
| 1 | **W-PY29 completion** | In progress | Medium | WorkerTxn bug fixes + adversarial tests (currently being implemented by opencode) |
| 2 | **PyPI release prep** | Not started | Low | manylinux wheel compliance, signing, upload to PyPI, package metadata finalization |
| 3 | **Tag v3.6.1** | Blocked on #1-2 | — | Release tag after W-PY29 + PyPI prep |

---

## Tier 2: Recovery & Fault Tolerance Hardening

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 4 | **Ring slot recycling hardening** | W-PY29 §9 | Medium | Add input byte coordinates to WorkerTxn so recovery is self-contained (doesn't depend on ring slot contents surviving). Currently, if the 1M-slot ring wraps, a recycled slot can false-positive the "ALREADY_DONE" check. |
| 5 | **Streaming Tier-3 recovery** | W-PY28 §9 | High | Extend WorkerTxn recovery to streaming mode (currently materialized `map()` only). Requires the C drain or orderer to handle mid-stream epoch transitions. |
| 6 | **NUMA multi-node Tier-3** | W-PY28 §9 | High | Extend WorkerTxn recovery to multi-node NUMA (currently UMA only). Requires per-node escrow routing during recovery and multi-node ring epoch management. |
| 7 | **Realtime mode exactly-once** | W-PY28 §9 | Medium | Realtime (`-u`) mode currently fails closed on catastrophic death (at-least-once). Achieving exactly-once requires the output to be recallable, which realtime stdout is not. Documented limitation. |
| 8 | **Remove ordered-mode `lseek` in `ring_ack`** | W-PY29 §12 | Low | The existing ordered-path `lseek` at ACK time serves commit accounting for ordered output. Could be replaced with tracked output position (same technique as `worker_output_end`). Separate from WorkerTxn — pre-existing. |

---

## Tier 3: Performance Optimization

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 9 | **C worker loop for spawn mode** | W-PY26 | Medium | Same pattern as `fr_py_worker_plugin_loop` but with `posix_spawnp` instead of C plugin callback. Eliminates Python from the spawn worker loop. |
| 10 | **SIMD-accelerated JSON parsing for C plugin** | W-PY24/25 | High | The C plugin's hand-rolled JSON parser processes ~5× Python's `json.loads` but is not SIMD-vectorized. A SIMD parser (like the engine's scanner) could achieve 10-50× Python. This would close the medium workload gap with Polars. |
| 11 | **OutputBatch (write-in-place)** | v1.3 plan §6 | High | Allow the payload to write directly to the output memfd (zero-copy output). Eliminates the "copy" in copy-on-return. Only needed if a niche shows the output copy dominating. |
| 12 | **NUMA sharding at high worker counts** | W-PY26 investigation | Medium | Use `nodes=@4` (per-node rings) to reduce ring contention at 28+ workers. Tested but not fully documented or optimized. Could improve high-core-count scaling. |
| 13 | **Fixed pipeline overhead reduction** | W-PY27 profiling | Medium | The ~14ms fixed overhead (init, spill, scanner fork, worker forks, collection) dominates short runs. Could be reduced through lazy initialization, pre-forked worker pools, or async scanner startup. |

---

## Tier 4: Stage 3 Completion (Engine Architecture)

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 14 | **Thunk flips (ARGC_ARGV → THUNK)** | v1.3 plan §2.2 | Medium | Migrate ring builtins from ARGC_ARGV to THUNK calling convention. Order: `ring_claim` → `ring_ack` → `ring_call` → `ring_poll`. Per-function commits. Enables typed FFI without argv marshalling. |
| 15 | **Physical `forkrun_core.c` split** | v1.3 plan §1 | Medium | Split the 371KB `forkrun_ring.c` into `forkrun_core.c` (standalone, zero bash linkage) + `forkrun_ring.c` (bash loadable wrapper). Currently unified via textual include. |
| 16 | **Typed `fr_pipeline_config_t`** | v1.3 plan §2.2 | Low | Generate a typed pipeline configuration struct from the IDL schemas (replacing the string-based `ring_init` flag grammar). Generated from the same schemas as the call-schema. |
| 17 | **`ring_init` flag grammar → typed config** | v1.3 plan §2.2 | Low | Replace the string-based flag parser in `ring_init` with a typed configuration struct. One sanctioned string surface eliminated. |

---

## Tier 4b: Cleanroom Launcher — Envelope Widening

CR-FIX1 hardened the UMA C-plugin cleanroom and made its tests
self-contained. These items widen what it can serve. They are listed as
a separate tier because they share one precondition: **each one widens
an accelerator, so none may ship until the one before it is measured and
honest.** Running the cleanroom at `0.17x` startup was worse than not
running it; running a *slower* accelerator across more of the API is
worse still.

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 44 | Re-measure the W-CR6 parent-RSS win | CR-FIX1 | Low | The 2x→10x startup / 1.2-1.5x end-to-end RSS scaling was measured **before** CR-FIX1. The fixed ~100 ms it was trying to amortise is now gone, so the crossover point moves. Any performance claim must state the parent RSS it was measured at, or it is not a claim. |
| 45 | NUMA cleanroom execution | CR-FIX1 §1 | High | `fr_py_init_numa`, `fr_py_numa_ingest`, `fr_py_indexer_numa`, `fr_py_numa_scanner` and `fr_py_fallow_phys` all exist and are already wired in the in-process path — the port is orchestration, not engine work. **Blocked on a correctness prerequisite:** in NUMA the record header's `batch_idx` is a *per-node claim ticket* (`forkrun_ring.c:6364`), not a global sequence, so the launcher's parent-side sort by `batch_idx` is invalid. Requires forking the C orderer *and* teaching `_cleanroom_collect` not to re-sort its output. |
| 46 | Python UDF mode in the launcher | CR-FIX1 §1 | High | `exec` destroys the interpreter object graph, so a UDF cannot be carried across the boundary — but it can be *recreated* on the far side, the way `frun.bash` recreates the shell. Requires embedding CPython in a separately-built helper `.so` (never in the substrate, which stays Python-free), plus a C→Python callback seam and exact `None`/`b""`/`str` return parity. **Supersedes** the "structurally impossible; do not attempt it" ruling in `CLEANROOM_DESIGN.md` §3 and `CLEANROOM_HANDOVER.md` §3. |
| 47 | Spawn-pipe-driven worker spawning | CR-FIX1 §1 | Medium | The launcher forks all workers at t=0 with the spawn pipe disarmed, matching the in-process Python NUMA path. The scanner can already request workers (`forkrun_ring.c:4261`). Doing so in the launcher needs a `poll()` loop over the spawn pipe plus per-worker death pipes, and must reproduce `_spawn_quiescent`'s three conditions before closing the signal spare — getting that wrong is **silent data loss**, not a hang (`MEMORY.md` W-STREAMDRAIN). |
| 48 | Real multi-socket validation | CR-FIX1 | External | Every NUMA claim to date is `numa=fake=N`. `set_mempolicy(MPOL_BIND)` is exercised but physically inert, and all SRAT distances are 10. Needs real multi-socket hardware. Flag it; do not fake a result. |

### Known gaps left by CR-FIX1

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 49 | Opt-in tracing facility not implemented | CR-FIX1-E | Low | The spec exists (`FORKRUN_CLEANROOM_TRACE`, role/pid/event/monotonic-ts records to an inherited memfd) but was deliberately deferred behind the descriptor measurement, which resolved the question by direct experiment instead. Worth building before the next lifecycle investigation. |
| 50 | `test_numa_recovery.py` is unreachable on UMA | CR-FIX1 | Low | Gated on `len(detect_numa_nodes()) >= 2`, so the NUMA crash/respawn lock-ins are skipped on a single-node box. Either boot `numa=fake=N` for the matrix (requires a **reboot**) or mark the cells required-manual in the release gate. |
| 51 | Path-source replay assumes a stable file | CR-FIX1-C | — | A path is replayable by reopening, which assumes its contents do not change during the invocation. Documented as an API assumption rather than solved; do not spool sources to satisfy it. |

---

## Tier 5: Distribution & Platform

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 18 | **manylinux wheel compliance** | W-PY23 plan | Medium | Use `auditwheel` to produce manylinux2014-compliant wheels. Currently `linux_x86_64` (works but less portable). Requires specific glibc pinning. |
| 19 | **aarch64 wheels and CI** | W-PY23 plan | Medium | Build and test aarch64 wheels. Requires either native ARM CI runner or QEMU-based cross-compilation. |
| 20 | **Reproducible build verification** | W-PY23 plan (partially done) | Low | Two-build checksum comparison is designed but not fully automated in CI. The `-ffile-prefix-map` and `--build-id=none` flags are specified but may not be in the final Makefile. |
| 21 | **Code signing** | W-PY23 plan | Low | Sign PyPI artifacts. Requires a signing key and `twine` integration. |
| 22 | **Conda package** | Not yet discussed | Low | Conda-forge distribution for HPC environments. |

---

## Tier 6: Features (Stage 6, Demand-Pulled)

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 23 | **TUI dashboard** | v1.3 plan §6 | Medium | Live telemetry dashboard showing throughput, memory, NUMA topology, fault counts. The C engine already has `ring_tui` (bash frontend uses it). Python frontend needs integration. |
| 24 | **Hardened source-ship** | v1.3 plan §3.5 | Medium | Robust source-code shipping for Python payloads (currently simple-case only). Handles import-time side effects, dependency resolution, and security sandboxing. |
| 25 | **Early-spawn GPU hatch** | v1.3 plan §3.6 | Low | Escape hatch for CUDA-holding parents: spawn workers before CUDA initialization. Currently the CUDA guard refuses (correctly). This would allow an opt-in override with documented risks. |
| 26 | **Halt mechanism** | v1.3 plan §6 | Low | User-initiated pipeline halt (`--halt`). The engine already has `cfg_halt_count` and `cfg_halt_pct` (poison-based halt). A user-facing halt API is needed. |
| 27 | **Resume UX refinements** | W-PY22 | Medium | Checkpoint integration with streaming mode, automatic checkpoint rotation, and cross-epoch result reassembly. |
| 28 | **Parameter sweep expansions** | W-PY20 | Low | Additional sweep modes (grid, random, adaptive). Currently Cartesian product and zip are supported. |

---

## Tier 7: Benchmarking & Validation

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 29 | **F36: non-throughput benchmarks** | Primer findings | Medium | Benchmarks for `-L` (exact lines), `-n` (limit), `-C` (plugin), resume, and retry modes. Currently only throughput modes are benchmarked. |
| 30 | **Polars/DuckDB at 5M+ scale** | W-PY24/25 | Low | Re-run native benchmarks at the same 5M-record scale as the UDF benchmarks for apples-to-apples comparison. |
| 31 | **Ray fault tolerance comparison** | W-PY24 | Low | Side-by-side comparison of forkrun vs Ray for SIGSEGV recovery latency and data completeness at scale. |
| 32 | **Real multi-socket NUMA benchmarks** | W-PY21 | Medium | Run the full benchmark suite on actual multi-socket hardware (currently 14c/28t single-socket). Tests born-local placement and distance-charged stealing. |
| 33 | **aarch64 benchmarks** | W-PY23 plan | Medium | Run the benchmark suite on ARM hardware (Graviton, Ampere). Validates the NEON SIMD path. |
| 34 | **`worker_output_end` microbenchmark** | W-PY29 | Low | Dedicated microbenchmark of the claim→publish→commit cycle with near-empty payload. Verifies the 4-state machine doesn't regress the engine floor. |

---

## Tier 8: Engine Internal Cleanup

| # | Item | Source | Effort | Description |
|---|------|--------|--------|-------------|
| 35 | **Dead code removal** | Primer F24 | Low | Remove `ring_indexer_main`, `ring_fetcher_main` (legacy flat pipeline), `OOM_WAIT_FOR_MEMORY` macro, `evfd_data`/`fd_escrow` statics. Documented as dead but kept. |
| 36 | **`total_lines_consumed` misnomer** | Primer F17 | Trivial | The variable counts batches, not lines. Rename to `total_batches_consumed`. Cosmetic but prevents confusion. |
| 37 | **`poll(-1)` sites** | Primer F18 | Low | Several engine sites use `poll(-1)` (infinite wait) instead of Shape-3 bounded waits. Currently safe but fragile. Convert to bounded polling. |
| 38 | **`resume_jagged[1024]` truncation** | Primer F23a | Low | Array silently truncates under extreme out-of-order depth. Either increase size, make dynamic, or fail loudly. |
| 39 | **Contract registry consolidation** | Primer F4 | Low | The cross-file contracts (H1/M1/H3) are documented in different docs under different names. Consolidate into the Stage 3.0 IDL schemas. |

---

## Tier 9: Security Model (Accepted Residuals — Documented, Not Bugs)

These are documented, accepted limitations of the security model. They are NOT future work unless the threat model changes.

| # | Item | Status |
|---|------|--------|
| 40 | Pre-consent code execution (same-UID file tampering) | Accepted residual |
| 41 | Same-UID hostile content shadowing `read` prompt | Accepted residual |
| 42 | Capture-time `builtin` shadowing forging verified function text | Accepted residual |
| 43 | Fallow-before-checkpoint race (regenerate-from-source semantics) | Accepted residual |

---

## Summary by Estimated Effort

```
TRIVIAL (< 1 hour):
  36. total_lines_consumed rename
  17. ring_init typed config

LOW (< 1 day):
  3. Tag v3.6.1
  7. Realtime exactly-once (documentation only)
  8. Remove ordered-mode lseek
  16. Typed fr_pipeline_config_t
  20. Reproducible build verification
  21. Code signing
  22. Conda package
  25. Early-spawn GPU hatch
  26. Halt mechanism
  28. Parameter sweep expansions
  30. Polars/DuckDB at 5M scale
  31. Ray fault tolerance comparison
  34. worker_output_end microbenchmark
  35. Dead code removal
  37. poll(-1) sites
  38. resume_jagged[1024] truncation
  39. Contract registry consolidation

MEDIUM (1-5 days):
  1. W-PY29 completion (in progress)
  2. PyPI release prep
  4. Ring slot recycling hardening
  9. C worker loop for spawn mode
  12. NUMA sharding at high workers
  13. Fixed overhead reduction
  14. Thunk flips
  15. forkrun_core.c split
  18. manylinux compliance
  19. aarch64 wheels + CI
  23. TUI dashboard
  24. Hardened source-ship
  27. Resume UX refinements
  29. F36 non-throughput benchmarks
  32. Real multi-socket NUMA benchmarks
  33. aarch64 benchmarks

HIGH (> 5 days):
  5. Streaming Tier-3 recovery
  6. NUMA multi-node Tier-3
  10. SIMD JSON parsing for C plugin
  11. OutputBatch write-in-place
```

---

## Recommended Priority for Post-v3.6.1

```
IMMEDIATELY AFTER v3.6.1 TAG:
  → 2. PyPI release (unlocks user adoption)
  → 9. C worker loop for spawn mode (closes remaining throughput gap)
  → 14. Thunk flips (completes Stage 3 architecture)

SHORT-TERM (next sprint):
  → 4. Ring slot recycling hardening (correctness)
  → 5. Streaming Tier-3 (extends recovery to streaming)
  → 12. NUMA sharding (improves high-core scaling)

MEDIUM-TERM (next quarter):
  → 6. NUMA multi-node Tier-3
  → 10. SIMD JSON parsing (closes Polars gap for medium)
  → 23. TUI dashboard
  → 32. Real multi-socket benchmarks

LONGER-TERM (when demand pulls):
  → 11. OutputBatch (if copy cost dominates a niche)
  → 24. Hardened source-ship
  → 18/19. manylinux + aarch64 wheels
```

---

*This is the complete register of all known future work as of the current conversation state. Items are added when identified (falsified hypotheses, external AI reviews, benchmark findings) and removed when completed or explicitly deprioritized. The register should be updated after each work order completes.*
