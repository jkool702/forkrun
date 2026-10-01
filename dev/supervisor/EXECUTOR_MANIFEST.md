# Executor Consistency Manifest (W-REL3a)

**Scope:** the ten blocking executors in `python/forkrun/run.py` —
every init→teardown lifecycle in the Python frontend. The `*_gen`
wrappers are thin generator shells (no engine contact of their own);
`sweep()` delegates to `map()`. Line anchors as of `f6bde00`;
the checker (`python/tests/test_executor_consistency.py`) verifies
behavior, never lines.

**Why this exists:** the P1–P5/B1/C4 findings of this cycle share one
root cause — ten near-identical executors, where executor #N forgot
something executor #1 remembered. They stay uncollapsed until v3.7
(W-REL4 #2, owner-ratified). Until then this manifest + checker is
the tripwire: the next copy-paste miss fails CI with the executor
and invariant named. This file is also W-REL4's design document
(the enumeration the collapse starts from).

## The ten executors

| # | Executor (entry line) | Paths served |
|---|---|---|
| 1 | `_execute_locked` (3214) | run/map, UMA, materialized, fork-and-wait (`orchestrator=False`) |
| 2 | `_execute_ingest_locked` (2713, via `_execute_ingest` 2634) | run/map, UMA, streaming-ingest, fork-and-wait (`orchestrator=False`) |
| 3 | `_execute_streaming` (1745, generator) | stream, UMA, materialized, fork-and-wait (`orchestrator=False`); splice-capable |
| 4 | `_execute_ingest_stream` (2117, generator) | stream, UMA, streaming-ingest, fork-and-wait (`orchestrator=False`); splice-capable |
| 5 | `_execute_reactor_locked` (3796) | run/map, UMA, materialized, reactor (**default** post-R1); orderer/c_drain/c_worker_loop/c_spawn_loop; resume-capable |
| 6 | `_execute_streaming_reactor` (4155, generator) | stream, UMA, materialized, reactor (**default**); orderer/c_drain; resume-capable |
| 7 | `_execute_ingest_reactor_locked` (4656) | run/map, UMA, streaming-ingest, reactor (**default**); orderer/c_drain; resume-capable |
| 8 | `_execute_ingest_stream_reactor` (5163, generator) | stream, UMA, streaming-ingest, reactor (**default**); orderer/c_drain; resume-capable |
| 9 | `_execute_numa_locked` (6252) | run/map, NUMA (detected multi-node or `@N`), reactor-implied; orderer/c_drain; splice forwarded |
| 10 | `_execute_numa_stream` (6735, generator) | stream, NUMA, reactor-implied; orderer/c_drain |

All stream paths (3, 4, 6, 8, 10) return through `_guarded_gen`
(1302). All map/run dispatches validate via `_api._validate`
before branching.

## The eight invariants (checklist)

Each row is a defect that already happened, generalized.

| ID | Invariant | Origin |
|---|---|---|
| I1 | API-entry guards: CUDA hazard check reached (directly or via the hoisted `_api.py` call) | P3 |
| I2 | Locking: `_RUN_LOCK` (RLock) held across the whole executor, including generator lifetimes | P1 |
| I3 | fd hygiene: teardown closes the full fd set (union audit; ≥1-missing is a finding unless explained) | P2 |
| I4 | Escrow discipline: deposit return honored (R14a retry + loud path) at every reached deposit site | C4a |
| I5 | Resume gating: `resume=`/checkpoint fully supported or loud-refused, never silently truncated | P4 |
| I6 | Output-write failure: rollback (`ftruncate` pattern) on every emit path | P5 |
| I7 | EOF/termination: completion via drain-audit / join verification, never liveness-only | F-NUMA1 |
| I8 | Teardown completeness: teardown on success AND failure/abandon paths | P2 (+2-fd class) |

## Per-executor status

Notation: ✅ covered (mechanism), ➖ intentional deviation (reason),
🔗 evidence linked (no duplicate probe).

### I1 — API-entry guards
✅ all ten: single call at the end of `_api._validate`, reached by
every run/map/stream dispatch (sweep delegates to map). No
per-executor calls remain (R9 deleted all six). Probe: mocked live
context → refusal on all ten routings.

### I2 — Locking
- ✅ 1, 2: `with _RUN_LOCK` inside `_execute_ingest` (2644) /
  `_execute` (3201) wrappers.
- ✅ 5, 7, 9: `with _RUN_LOCK` at every run/map dispatch site
  (run: 851/870/889; map: 990/1012/1034/1067/1115).
- ✅ 3, 4, 6, 8, 10: held by `_guarded_gen` (1322) across the full
  generator lifetime (lazy first-`next()`, finally on abandon).
  Different mechanism by sync/async shape — noted, not a deviation.
- Probe: acquire/release counters around minimal jobs (exhaust +
  abandon); RLock reentrancy pinned by `test_stream_lock.py`.

### I3 — fd hygiene (union audit)
Union of close sets: out_fds, memfd, src_fd, signal_r/w, fallow_r/w,
spawn_r/w, order_r/w, trap_r/w, coll_fd, results_fd, death pipes,
scanner death pipes, helper pids reaped.
- ✅ 1: inline finally (3490–3520) — no fallow/spawn/order machinery
  exists here (➖ N/A: nothing to close).
- ✅ 2: `_teardown_stream` (fallow_w param closed).
- ✅ 3, 4: `_teardown_stream` on exhaust + abandon + pre-fork cover.
- ✅ 5, 6, 8, 9, 10: `_teardown_reactor` (tuple + state-parked
  spawn_r/fallow_w, R11).
- ✅ 7: `_teardown_reactor` + state-parked spawn (disarmed, R1),
  fallow_w, and scan_death_r (R11 follow-on).
- ➖ run() `collect=False` paths create no out_fds/orderer (discard
  mode needs no orderer — nothing to close).
- ➖ splice fork-and-wait workers (executor 3/4 splice arms) own no
  escrow pipe relationship beyond the shared keep set (fail-loud
  on nonzero exit — see I4).

### I4 — Escrow discipline
- ✅ all Python-worker paths (every executor): shared `_run` —
  `_escrow_deposit_retry` + `_deposit_or_loud_skip` (R14a).
- ✅ reactor C-loop child-mains (splice/plugin/spawn): loud wrapper
  (R14a).
- ➖ `_fork_splice_worker` (executors 3/4 splice arms, fork-and-wait):
  NO deposit on failure — intentional: nonzero exit fails the run
  loudly via the failed-check (no silent continuation, no
  respawn to continue toward). Fail-loud vs deposit-and-continue
  is the documented fork-and-wait contract; changing it would be a
  behavior change (out of scope pre-release).
- Probe: injected deposit failure → loud path (R14a lock-in linked;
  checker runs one default-executor instance).

### I5 — Resume gating
- ✅ 5, 6, 7, 8: supported (reactor + `order="index"` + UMA +
  collect + non-splice); `require_resume_path` gates in wrappers
  before dispatch; `resume_begin` inside post-init.
- ➖ 1, 2, 3, 4: loud-refused at the wrapper gate
  (`orchestrator=False` fails `require_resume_path`).
- ➖ 9, 10: loud-refused (per-node rings unsafe in v3.6.0).
- ➖ splice arms: loud-refused (no OrderPackets, no tracker).
- ➖ `run()`: unconditionally refused (no C orderer).
- ➖ `FORKRUN_NO_V1=1`: loud-refused naming the incompatibility
  (R12 — masks the orderer/resume symbols).
- Probe: refused combos raise (fast, no engine); supported
  roundtrip linked to `test_resume.py`; 15→12 canary = R12 lock-in.

### I6 — Output-write failure rollback
- ✅ v0 Python emit (all executors via shared `_run`):
  pre-record `lseek(END)` + `ftruncate` on `OSError` (R13).
- ✅ C emit/spawn/plugin loops: in-shim `payload_error`
  truncation (pre-existing).
- ➖ splice passthrough arms: N/A — byte windows, no framed
  records; nothing to roll back.
- Probe: R13 lock-in linked (injected ENOSPC → byte-exact).

### I7 — EOF/termination
- ✅ 9, 10: `_numa_drain_audit` per completion (F-NUMA1 guard
  family) — 🔗 `test_numa_drain_guard.py` (no duplicate probe).
- ✅ 1–8: join/drain verification per path (worker waitpid joins,
  scanner blocking joins, drain/orderer rc checks, `_drain_records`
  EOF rule, reactor `failure_check` + poison summary) — 🔗 full
  suite byte-exactness (no duplicate probe).
- No liveness-only completion anywhere (audit 2026-09-28).

### I8 — Teardown completeness
- ✅ 1: single `try/finally` (3252/3449).
- ✅ 2: nested `try/finally` (spill/gate/teardown).
- ✅ 3, 4: inner `try/finally` (exhaustion + `GeneratorExit`) +
  outer pre-fork cover.
- ✅ 5, 6, 7, 8, 9, 10: `try/finally` → `_teardown_reactor`
  (abort choreography in `except` first where armed).
- Probe: fd-baseline assertions per executor, success + injected
  failure (+ abandon for generators).

## §4 cross-check report (W-REL2 fix sites × siblings, 2026-09-28)

Method: every R9–R14a/b pattern grep-verified across all ten
executors (evidence lines in the rows above).

- R9 (CUDA): hoist covers all ten by construction (single
  `_validate` call; zero per-path calls remain — grep-verified).
- R10 (lock): dispatch sites (run 851/870/889, map
  990/1012/1034/1067/1115) + `_guarded_gen` (all 8 stream()
  returns route through it — grep-verified). No executor missed.
- R11 (fd closes): `_teardown_stream` (fallow_w param) +
  `_teardown_reactor` (tuple + state-parked spares) cover all
  callers (6 + 4 sites respectively). Sibling found DURING R11
  itself (scan_death_r) already fixed there.
- R13 (ftruncate): single shared v0 site + in-shim C sites —
  no per-executor copies exist to miss.
- R14a (deposit): all six call sites route through the two
  helpers (only remaining direct `fr_py_escrow_deposit`
  references are inside the helpers + tests). Sibling reviewed:
  `_fork_splice_worker` non-deposit is intentional fail-loud
  (recorded above as I4 deviation, not a finding).
- R14b (shim): single site by construction.
- **Findings fixed: none. None-found with the grep evidence
  above** (one intentional deviation recorded, zero behavior
  changes — this order ships no product diff).

## Evidence map (checker ↔ existing tests, no duplication)

| Checker probe | New assertions | Linked (not duplicated) |
|---|---|---|
| lock | acquire/release counts per executor | reentrancy → `test_stream_lock.py` |
| fd/teardown | baseline assertions per executor | R11 lock-in |
| CUDA | refusal on all ten routings | R9 stream lock-in |
| resume | refused-combos raise | roundtrip → `test_resume.py`; canary → R12 lock-in |
| deposit | one loud-path instance (default) | ×10 → `test_escrow_refused.py` |
| EOF | drain-guard link only | `test_numa_drain_guard.py` |
| manifest | evidence-column populated | this file |

## W-DEDUP addendum (2026-09-28, branch NEW/REFACTOR2.9)

Consolidation landed per `DEDUP_DESIGN.md` (costume-detection PASS):
**3 cores + 10 thin wrappers + 6 shared helpers**, not 1 + 10 if-blocks.

- New module `python/forkrun/_executor_core.py`: `ExecutorSpec`,
  `fork_workers` (single splice/c_plugin/c_spawn/python dispatch),
  `collect_records` (drain-vs-direct + order), `report_poison`,
  `init_engine` (UMA vs NUMA selection), `teardown_union` (union fd set,
  1 supervision branch). Cycle-safe via `sys.modules["forkrun.run"]`
  lazy binding.
- Ported (behavior-preserving, same names/signatures/probe points):
  #1 `_execute_locked` (fork+collect+poison to core),
  #2 `_execute_ingest_locked` (fork+collect+poison to core),
  #3 `_execute_streaming` (fork to core; live-drain + stashed poison stay
  generator-local by shape),
  #4 `_execute_ingest_stream` (fork to core; same shape note).
- Not ported (already single-sourced, documented as justified):
  #5-#8 reactor join/disposition (shared `ReactorState`/`reactor_loop` in
  `_reactor.py`; orderer/resume/c-loop variants are parameters),
  #9-#10 NUMA pipeline (shared `_numa_fork_pipeline` +
  `_numa_drain_audit`; topology is a genuinely different executor).
- R-D8 ABI gate: `tools/gen_shim.py` + `forkrun_shim.h` (45 extern decls)
  + `tools/generated/shim_signatures.json` (56 entries with linkage) +
  `test_shim_abi.py` (5/5) + `shim-check.yml` CI. Triple agreement:
  JSON externs == `_bindings` bound == `.so` exports (45/45/45).
- Deviations re-justified: every prior deviation is now either a named
  parameter (`escrow_fail_loud`, `signal_r_to_close`, `fallow_w`,
  `collect=False` no-orderer) or a still-declared shape deviation
  (generator stashed-poison, NUMA unified ingest, reactor-implied
  supervision). Zero behavior changes (smoke: 6 UMA paths byte-identical;
  routing + ABI gates green).
- `executor_manifest.json`: unchanged (10 names, 8 invariants each —
  probes still hit the same entry points, now executing consolidated
  code; evidence column remains accurate).

| Checker probe | New assertions | Linked (not duplicated) |
|---|---|---|
| ABI (R-D8) | exports == table == bindings; arity; order | `test_shim_abi.py` (signatures only) |

## W-REL6 addendum (Wave 5: seam USED + measured consolidation)

ExecutorSpec/init_engine/teardown_union no longer exist-but-unused:
every core function accepts `spec=` (explicit overrides), all ten
executors construct one spec (lattice + call flags) and thread it
through init/fork/collect; init bodies (10 sites) route via
init_engine (NUMA message + NULL-map convention preserved
call-site-exact).

Consolidated this wave (zero behavior change, gated per step):
- 2 legacy poison scalar sites -> core report_poison (npois override
  preserves the streaming pre-teardown stash; WARN text identical).
- 7 spare-managers -> _close_spare_fd (no-reset copies proven
  post-use; guards stay at call sites; one nonlocal added).
- _watch_live + waitpid _watch_helpers -> _watch_helper_deaths.
- NUMA twins _parse_quantum/_poll_ingest/_all_helpers_done ->
  _parse_drain_quantum/_poll_ingest_once/_pipeline_quiescent
  (shells inlined at call sites).
- frun.bash verbose toc()/tStart block deleted (never called).

Metrics (c2edb53 -> wave end): run.py 7470 -> 7431 lines;
duplicate def names 13 -> 10; 30-line clone groups 45 -> 21;
core call sites 16 -> ~60.

Costume verdict (STOP with evidence — driver-merge NOT attempted):
merging the ten executors into shared drivers fails the <=3
mode-conditional budget on inspection. A UMA-plain pair driver
(#1+#2) alone needs setup-ingest, fork-timing, join, teardown and
spill-pump branches (5); full coverage adds supervision, shape/
lifetime, NUMA topology and orderer/c-loop envelopes. The remaining
dup names are all shape-bound: per-executor nonlocal rebinding
(_watch_scanner x2, identical bodies), different machinery per
shape (_pump_drain 130/82/72 lines; reactor death-pipe watchers),
or behavioral deltas (_drop_parent_signal spare arm, _fork_node
drop call). The checker probes the ten entry points by name
(test_executor_consistency.py) and executor_manifest.json enumerates
ten — a driver-merge would redesign checker+manifest+probes, i.e.
W-REL4 #2 scope, not this order. The executors share everything
shareable through the core; their sequencing is the executor.
