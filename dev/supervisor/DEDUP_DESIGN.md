# W-DEDUP Design Note — Executor Lattice Analysis

**Branch:** NEW/REFACTOR2.9 (from f41045c post-W-REL4).
**Date:** 2026-09-28. **Author:** opencode (W-DEDUP Phase 0).
**Spec:** `dev/supervisor/EXECUTOR_MANIFEST.md` + `executor_manifest.json` +
`test_executor_consistency.py` + `test_invariant_gate.py` (§3/§6/§9).

## 1. The ten executors (measured)

| # | Name | Lines | Ingest | Supervision | API shape |
|---|---|---|---|---|---|
| 1 | `_execute_locked` | 582 | materialized (`_spill_to_memfd` + `_fork_materialized_scanner`) | plain waitpid (`orchestrator=False`) | blocking run/map |
| 2 | `_execute_ingest_locked` | 477 | streaming-ingest (`_new_ingress_memfd` + `_fork_ingest_helpers`) | plain waitpid | blocking run/map |
| 3 | `_execute_streaming` | 372 | materialized | plain waitpid | generator stream |
| 4 | `_execute_ingest_stream` | 517 | streaming-ingest | plain waitpid | generator stream |
| 5 | `_execute_reactor_locked` | 359 | materialized | reactor (`ReactorState`/`reactor_loop`) | blocking run/map |
| 6 | `_execute_streaming_reactor` | 501 | materialized | reactor | generator stream |
| 7 | `_execute_ingest_reactor_locked` | 507 | streaming-ingest | reactor | blocking run/map |
| 8 | `_execute_ingest_stream_reactor` | 1089 | streaming-ingest | reactor | generator stream |
| 9 | `_execute_numa_locked` | 483 | NUMA-unified (ingest owns source; no mat/stream split) | reactor-implied | blocking run/map |
| 10 | `_execute_numa_stream` | 606 | NUMA-unified | reactor-implied | generator stream |

Wrappers `_execute` (24 lines) and `_execute_ingest` (79 lines) are
already thin lock+delegate shells over #1/#2 — the pattern this order
generalizes.

## 2. Axes of variation (verified vs expected)

Expected lattice `{map,run,stream}×{UMA,NUMA}×{materialized,streaming-ingest}
×{plain,reactor}×{c_drain?,spawn-loop?,plugin-loop?}` — verified with
deviations:

- **API shape `{blocking, generator}` → WRAPPER.** All 5 stream paths
  return through `_guarded_gen` (run.py:1302) which holds `_RUN_LOCK` +
  signal guard across generator lifetime. Blocking paths hold `_RUN_LOCK`
  at dispatch (run/map call sites) or inside `_execute`/`_execute_ingest`.
  Same engine contact, different lifetime — thin generator shells, no
  engine logic of their own. `sweep()` delegates to `map()`.
- **Topology `{UMA, NUMA}` → GENUINELY DIFFERENT EXECUTOR (stays separate).**
  NUMA uses `fr_py_init_numa`, `_numa_fork_pipeline` (per-node rings,
  born-local ingest, CPU pinning), `_numa_drain_audit` (F-NUMA1), no
  materialized/streaming split (ingest owns files and pipes uniformly),
  reactor-implied (no plain variant). Collapsing UMA+NUMA into one function
  would need per-line topology branches — costume territory. Two cores:
  `_run_uma_*` and `_run_numa_*`.
- **Ingest `{materialized, streaming-ingest}` → PARAMETER.** Materialized =
  `_spill_to_memfd` + `_fork_materialized_scanner` + `fr_py_ingest_done`;
  streaming = `_new_ingress_memfd` + `_fork_ingest_helpers` (fallow reaper,
  spill pump). Both produce `(memfd, size/engine_fds, helper_pids)` and
  converge before worker fork. One `if ingest ==` branch at setup + one at
  teardown (helper pid set) — 2 conditionals, within budget.
- **Supervision `{plain, reactor}` → MODE (two cores sharing helpers).**
  Plain = fork + `waitpid` join + `failed` list; reactor = `ReactorState` +
  `reactor_loop` + death pipes + respawn cap + trap-ACK + C orderer +
  `require_resume_path`/`resume_begin`. The join/reap/disposition logic is
  genuinely different (~150 lines each), but everything around it (init,
  worker fork dispatch, drain fork, collect, poison summary, teardown arg
  assembly) is identical. Two cores (`_run_uma_plain`, `_run_uma_reactor`)
  sharing 5 helpers — not one function with 10 if-blocks.
- **`{c_drain?, c_worker_loop?, c_spawn_loop?, splice?, collect?, order?}`
  → PARAMETERS.** Already boolean flags on every executor signature;
  dispatch is 3 one-line branches in the worker-fork loop (splice /
  c_plugin / c_spawn / python) + `use_drain = bool(c_drain) and collect`.
  Single implementations in the core.

## 3. Costume-detection result: PASS (2 cores + 1 NUMA, not 1 + 10 ifs)

Per-function conditional budget (≤3):

- `_core_fork_workers`: 3 branches (splice / c_plugin / c_spawn / else
  python) — this is a dispatch table, not mode logic; alternatives
  (strategy map) add indirection without removing branches. PASS.
- `_core_setup_ingress`: 1 branch (materialized vs streaming-ingest). PASS.
- `_core_join_plain` / `_core_join_reactor`: 0 cross-mode branches (separate
  functions by supervision mode). PASS.
- `_core_collect`: 2 branches (drain vs direct; order index vs none). PASS.
- `_core_teardown`: 0 branches — union fd set closed unconditionally
  (close of never-opened fd is a guarded no-op); supervision-specific pid
  sets passed as parameters. PASS.

Honest count: **3 cores** (`uma_plain`, `uma_reactor`, `numa`) + **10 thin
wrappers** (same names, ~8 lines each, preserving behavioral-probe
patch points) + **6 shared helpers**. Wrappers are justified (API-shape +
  dispatch-site lock placement differ), cores are justified (supervision and
  topology differ), everything else is a parameter. No function exceeds 3
  mode-conditionals.

## 4. What the core makes impossible-by-construction

- I1 (CUDA/validation): single `_validate` call at `run/map/stream` dispatch
  (already hoisted, R9); core asserts `validated=True` token — no
  per-executor memory required.
- I2 (RLock): one wrapper per API shape (`_blocking_locked` context,
  `_guarded_gen` for generators); executors never touch `_RUN_LOCK` directly.
- I3/I8 (fd hygiene + teardown): single `_core_teardown` context manager over
  the union fd set (`out_fds, memfd, src_fd, signal_r/w, fallow_r/w,
  spawn_r/w, order_r/w, trap_r/w, coll_fd, results_fd, death pipes, scanner
  death pipes, helper pids`); executors narrow only via explicit
  `deviation=` parameter recorded in the manifest.
- I4 (escrow): single `_core_fork_workers` + shared `_run` deposit helpers
  (`_escrow_deposit_retry`, `_deposit_or_loud_skip`); splice fail-loud
  deviation is a named parameter (`escrow_fail_loud=True` on fork-and-wait
  splice arms).
- I5 (resume): single `require_resume_path` gate + `resume_begin` in
  reactor cores; plain/NUMA/splice/run paths pass `resume_supported=False`
  and refuse loudly — never silently truncate.
- I6 (rollback): single v0 emit site + in-shim C sites; splice N/A is a
  named deviation.
- I7 (EOF): plain cores use join/drain verification, NUMA cores use
  `_numa_drain_audit`, reactor cores use `failure_check` + poison summary —
  all via single `_core_join_*` implementations, never liveness-only.

## 5. R-D8 (ABI gate) placement

`_shim.c` carries 54 `fr_py_*` definitions; `_bindings.py` binds 45 (11
internal helpers unbound: `write_all`, `emit_record`, `nonblock`,
`cap_rewind`, `plugin_cache_reset/ensure/invoke`, `data_hwm_reset`,
`read_full/write_full`, `ack_core`; 2 bound-but-not-defined-in-shim-regex
`get_raw_window`/`version` are defined with pointer returns the naive regex
missed — the generator uses a robust multi-line parser). The generator
(`tools/gen_shim.py`, mirroring `gen_idl.py` + `--check`) parses the C
source as single-source, emits `forkrun_shim.h` (declarations) +
`tools/generated/shim_signatures.json` (name → {return, args} for the
ctypes cross-check), and `test_shim_abi.py` diffs live bindings against
the table. Signatures only — no semantic contracts (invariant gate's
territory).
