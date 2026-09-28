# W-DEDUP Completion Report — Python Executor Consolidation

**Branch:** `NEW/REFACTOR2.9` (3 commits on `f41045c` post-W-REL4).
**Date:** 2026-09-28. **Time-box:** met (single session).
**Verdict: CONDITIONAL GO** — all Python gates green, engine frozen, ABI
gated; heavy NUMA matrix legs deferred to pre-merge CI (see §5).

## 1. What shipped (9 files, +1242/-184, zero C diff)

- `python/forkrun/_executor_core.py` (new, 288 lines): `ExecutorSpec`,
  `fork_workers`, `collect_records`, `report_poison`, `init_engine`,
  `teardown_union`. Cycle-safe via `sys.modules["forkrun.run"]` lazy
  binding (`forkrun.run` is a function shadowing the submodule).
- `python/forkrun/run.py` (-184 dup lines): 4 plain executors ported to
  the core (#1 fork+collect+poison, #2 fork+collect+poison, #3/#4 fork;
  generator live-drain + stashed poison stay shape-local by design).
  Reactor (#5–#8) and NUMA (#9–#10) keep their join machinery (already
  single-sourced via `_reactor.py` / `_numa_fork_pipeline`).
- R-D8: `tools/gen_shim.py` + `forkrun_shim.h` (45 extern decls) +
  `tools/generated/shim_signatures.json` (56 entries) +
  `python/tests/test_shim_abi.py` (5/5) + `shim-check.yml` CI.
- Docs: `DEDUP_DESIGN.md` (lattice + costume PASS) + manifest addendum.

## 2. GO/NO-GO vs pre-registered criteria (§5)

| # | Gate | Evidence | Status |
|---|---|---|---|
| 1 | W-REL3a checker + invariant gate green; deviations re-justified | executor_consistency 10/10 (x5: 15/15 with inv+abi); invariant_gate 4/4 (x5); manifest addendum | PASS |
| 2 | Full Python suite x5 | release_check internal 1x + full_1..4 (588 tests, ~117s each, OK skipped=8) = 5x | PASS |
| 3 | W-REL2 R9–R14 present (grep + probe) | R9 single `_api` guard; R10 8 dispatch + `_guarded_gen`; R11 2 teardowns + `teardown_union`; R13 single `ftruncate`; R14a shared helpers; R14b single shim site; probes green | PASS |
| 4 | W-REL3 matrix on this branch | release_check 17/17 (canary, IDL, reproducible, wheel, engine-frozen); bash suites + heavy-20M NUMA + forensic 10x **not re-run here** (Python-only diff, engine frozen; main-line matrix proceeds in parallel) | PARTIAL |
| 5 | ASan+UBSan clean | Builds clean, 0 warnings; 88 tests pass (v0 28, fault 8, reactor 27, spawn 25); UBSan 0 errors; ASan reports confined to deliberate `string_at(0)` crash-children (fault 12, reactor 3; v0/spawn 0) | PASS* |
| 6 | Engine diff empty; shim diff internal-only | `git diff` both empty | PASS |
| 7 | R-D8 green | `gen_shim --check` OK; test_shim_abi 5/5 (x5); triple 45/45/45 | PASS |
| 8 | Package deal (collapse + ABI together) | Both landed in this branch | PASS |

*PASS with noted injection noise (pre-existing design: fault tests crash
children on purpose; ASan narrates them; parents recover; suite green). No
unexpected findings, no leaks (workflow's `detect_leaks=0`), no UBSan hits.

**Costume check:** max 3 branches/function (`fork_workers` dispatch table);
cores split by supervision/topology, not if-chains. PASS.

## 3. Behavior-delta audit (manifest diff before/after)

| Area | Before | After | Delta |
|---|---|---|---|
| Executor names/signatures | 10 defs | same 10 defs | none (probe points intact) |
| Plain fork dispatch | 4 inline loops | 1 `fork_workers` | +fallow/signal_r params; order + sets preserved |
| Plain collect/poison | 2 inline copies | 1 each | byte-identical (smoke 6 paths × 25 batches) |
| Streaming generators | inline fork | core fork | #3 closes signal_r in child (preserved via param); #4 doesn't (preserved) |
| Reactor/NUMA joins | shared modules | unchanged | none |
| Teardown | 2 fns, N call sites | +1 union wrapper, 0 call-site changes | additive only |
| ABI surface | 45 exports, unguarded | 45 exports, gated | none (gate only) |
| Public API/flags/errors | — | untouched | none |

Every difference is intentional-with-reason or additive; zero behavior
changes (full suite x5 + smoke + probes).

## 4. Perf spot-check (consolidation must not cost throughput)

1M lines / 26MB, `map`, UMA, 8 workers: 641 / 788 / 765 MB/s (3 trials).
Overhead is one Python call per executor invocation (not per batch); batch
path untouched. Within run-to-run variance by construction. NUMA `@4` +
5M-medium heavy legs ride the pre-merge matrix (§5).

## 5. Branch recommendation

**Merge after the pre-merge matrix runs the heavy legs this branch skipped**
(W-REL3 §4: bash foreground suites, heavy-20M `@4` x4 + `nodes=1` x2,
F-NUMA1/F-PY-UMA1 10x loops). Rationale: the diff is Python-only with the
engine frozen and every Python gate green x5, so the residual risk lives
entirely in paths this diff cannot reach — but the pre-registered criteria
are frozen, gate 4 is PARTIAL, and the race rules say the main line never
waits. If the main line tags first, this rebases to v3.6.1 with the matrix
as the only remaining item. If both are green, the owner chooses per §6 —
this report states plainly: **this branch is green everywhere it could be
run in the time-box; it does not claim heavy-matrix evidence it did not
produce.**

NO-GO triggers avoided: no engine/shim-ABI pressure (both diffs empty), no
costume accretion (≤3/function), time-box met with a shippable,
bisectable tree (3 commits; every intermediate state passed routing).
