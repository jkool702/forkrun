# Rental-Readiness Summary — distributed-ingest experiment
## WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-AND-EXPERIMENT-COMPLETION-1

Status: corrections-3 ready; rehearsal rehearsal complete on the corrected
commit. Host note: this is the rehearsal-preparation readiness doc —
physical-NUMA validation is a rental requirement, not a rehearsal
deliverable.

Rehearsal rehearsal (§11): `epyc/rehearsal_rehearsal_45.sh` — run from the
clean checkout of the corrected commit (worktree at `8d08c90e…`; branch tip
`52030231` — same code, readiness updates). Artifacts under
`/tmp/opencode/epyc-reh3/out`. Provenance reconciled: campaign `source_sha` ==
`env-before.json` git.head_sha == `8d08c90e…`, `git.dirty == false`,
`drift_assessment=valid`. All PASS: 45-stage rehearsal; plan-only rehearsal
(topology discovery + mapping-matrix generation + mapping compatibility
validation); parameter sweep plan generation (sweep_axes + parameter_sets);
rehearsal campaign (asymmetric-ingestor scenarios + paired placement
experiments + repeated passes + randomized candidate order; per-trial
provenance: mapping_provenance + duration_qualification + ingestor_controls
recorded); artifact collection/indexing (`90_collect`).

## 1. Final branch and HEAD
- Branch: `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-3` (corrections-3).
- Rehearsaled corrected commit (rehearsal rehearsal ran on it): `8d08c90e99e9ebbbda60dfffafc3d579d0613202` (branch tip: `52030231` — same code, readiness updates).

## 2. All checkpoint commit SHAs
- corrections-1: `deecdc64` (WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-1 tip: `81da9e63`), `3e6a924e`, `81da9e63`.
- corrections-2: `3e6a924e` (C4/C5 corrections-2 — wrong-node placement, backlog line, manifest contract).
- corrections-3 (rehearsaled, final tip): `8d08c90e99e9ebbbda60dfffafc3d579d0613202` — per-node ingestor workload controls (§5.2), placement_sampling=full (§2), sanitizer evidence, rehearsal rehearsal.

## 3. Changed files (corrections-3 vs corrections-2 tip)
`stage0/dist_ingest/dist_ingest.{c,h}` (§5.2 engine: `di_ingestor_cfg_t`, `di_node.ing_cfg`, `di_ingestor_sleep_ns`, ingest-path delay hooks, §2 `placement_sampling=2`),
`stage0/dist_ingest/run_dist.py` (DiIngestorCfg/DiConfig.ingestors, `--ingestor-*-per-node`, placement-sampling full, provenance),
`stage0/dist_ingest/run_dist_campaign.sh` (`--placement-experiments off|paired|full`, scenario-line `pn` field + 4 asymmetric-ingestor scenarios),
`stage0/run_case.py` (spec plumbing),
`stage0/dist_ingest/SANITIZER_EVIDENCE.md` (new),
`stage0/dist_ingest/tests/test_{dist_ingest,benchmark_semantics,addendum_a,corrections_s2_s4,corrections_s3}.py` (§5.2 + §2 tests, mirror struct updates),
`epyc/rehearsal_rehearsal_45.sh` (new — §11 rehearsal rehearsal).

## 4. Frozen production files untouched
`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` —
untouched by corrections-3 (and all earlier corrections). Experimental
`dist_ingest.c`/`dist_ingest.h` changes are WO-permitted (master WO §0.1).

## 5. Topology-discovery capabilities
- `stage0/dist_ingest/topology.py` (from C1): online sparse node IDs,
  allowed mem/CPU/cpuset, per-node CPU lists + capacity/available memory,
  node→socket/package, complete ordered NUMA distance matrix + nearest
  intra/cross-socket distances, core/thread counts; unknown facts
  explicitly marked. `run_dist.resolve_topology()` consumes it;
  `discover_topology_inventory()` provides the inventory.

## 6. Mapping profiles + exact selection rules
- Profiles: `auto` (legacy default), `cross_socket_spread` (spread across
  as many sockets as possible), `intra_socket` (socket-qualified concrete
  variants), `all_nodes` (all usable nodes when counts match), `explicit`
  (user-supplied list), plus `matrix`/`all` campaign aliases for per-scenario
  profile expansion. `phys_nodes` backward-compatible explicit override.
- Selection rules (C1): `cross_socket_spread` uses socket membership, not
  numeric IDs; `intra_socket` needs a socket-qualified variant; `all_nodes`
  requires the requested count to match usable count; unsupported mappings
  are reported with reasons, never silently substituted.
- Mapping identity is part of case identity and reporting (intra/cross-socket
  cannot be mixed into one summary).

## 7. Placement-sampling modes + overhead separation (C2 + corrections-3 §2)
- `off` (0): performance-isolated; no in-run `move_pages`; `performance_measurement=true`.
- `on` (1): bounded in-run sampling for placement-validation; timing tainted,
  distinct trial_class, excluded from performance headlines.
- `full` (2, new): exhaustive sampling for diagnostics; also not a clean
  performance measurement; campaign `--placement-experiments off|paired|full`.
- Separation: performance trials are `placement_sampling=off`; paired
  placement-validation experiments are linked and distinct.

## 8. Repeated-pass + duration qualification (C3)
`--min-duration-seconds N` — per-pass qualification via `_dist_pass_qualified`
(C3-correction-2); repetition via pass-count cap + `min_duration_repetition_budget_s`;
`duration_qualification`/`duration_aggregate` recorded per trial.

## 9. Cache-preconditioning semantics (C3)
`--cache-precondition-policy` = `best_effort_os_cache` (default), `warm_repeat`,
`drop_caches_if_privileged`; recorded factually per trial (requested/achieved/
privileged/fallback); no claimed cold-cache control unless it actually succeeded;
`drop_caches_if_privileged` is not a "cold" guarantee. Preconditioning is per-pass
(outside the timed interval).

## 10. Parameter sweep matrix (C3)
`--sweep-base-quantum`, `--sweep-max-backlog`, `--sweep-max-reservation` (explicit
enumerable parameter sets — each is a distinct attributable `pset_id`).

## 11. New workload scenarios (C3 + WO §5)
Campaign scenarios: `equal`, `slow_one`, `fast_one`, `asymmetric`, `stall_recover`,
`slow_ingestor_one`, `slow_ingestor_stall_recover`, `slow_ingestor_fast_consumer`,
`slow_ingestor_slow_consumer`, `nodes2`, `nodes8`, `large_seq`, `small`, `tiny`,
`boundary`, `backpressure`, `medium_seq`, `chunkstress`, `boundary_small_backlog`.
Boundary-correctness matrix: `test_small_files_and_boundaries`, `test_empty_file`
(existing engine tests).

## 12. Environment + binary provenance (C4.3/C4.4/C4.5)
`stage0/env_capture.py` (git state, build hashes, topology, kernel/env facts);
`stage0/env_drift.py` (critical-field drift incl. `cpu_extra.numa_scan_delay`);
`stage0/dist_ingest/run_dist_campaign.sh` records `binary_provenance`
(`libdist_ingest.sha256` + `python-substrate.sha256` per trial).

## 13. Hardware-calibration utility (C4.6 + corrections-1/2)
`stage0/numa_calibrate.py` — local/remote read+copy calibration; local dst on
the node; remote copy dst on the pair node (corrections-2); per-measurement
affinity/placement evidence with wrong-node/missing/unsuccessful placement
invalidating results (corrections-2); placement validation of every buffer.

## 14. EPYC orchestration integration (C5 + corrections-1/2)
`epyc/45_bench_dist_ingest.sh` (campaign + calibration + reports + manifest),
`epyc/run_all.sh` (stage list + 41 in the full selection), `epyc/run_all.sh`
resume markers, `epyc/RENTAL_DAY_WORKFLOW.md` (step 7 documents
`--placement-experiments paired`; 41 in the full shortcut), `epyc/55_agent_supervise.sh`
+ permissions/prompt, result collection/indexing (`epyc/90_collect.sh`).

## 15. Test/sanitizer results (corrections-3)
- `python3 -m unittest discover -s stage0/dist_ingest/tests` — **254 OK**
  (asan2/tsan2 re-runs) — 254 tests.
- `python3 -m unittest stage0.tests.test_stage0` — 101 OK (16s).
- `python3 -m unittest python.tests.test_numa_drain_guard` — 7 OK.
- `python3 -m unittest python.tests.test_numa` — 36 OK (skipped=1).
- New: `TestIngestorWorkloadControls` (6 engine tests) + campaign-wiring tests.
- Sanitizers: `stage0/dist_ingest/SANITIZER_EVIDENCE.md` —
  ASan+UBSan: 254 tests OK, 0 reports. TSan: 254 tests OK, 0 warnings.

## 16. Local/fake-NUMA limitations
Rehearsal host: fake-NUMA (`numa=fake=4`, single socket). Dist-ingest
measurements are single-socket/fake; none are physical-NUMA validation.
Placement validation is observable (all_sampled_on_target), not proof.

## 17. Exact one-command rental invocation
```
bash epyc/run_all.sh --only 00_preflight,10_setup,41_bench_numa5m,45_bench_dist_ingest
```
(WO 9.5 step 2's F-NUMA1 topology sanity gate + step 5's production-reference
measurements are expected to have been completed first.)

## 18. Expected artifact locations
- 45 stage: `$EPYC_OUT/21_bench_dist_ingest/` — `dist_ingest_campaign/`
  (`campaign-manifest.json`, `report.md`, `cases/<case>/trial<N>/manifest.json`,
  `env/{env-before,env-after,drift-report,binary-provenance}.json`, `env/build/`),
  `dist_ingest_campaign.log`, `numa_calibration.{json,log}`,
  `dist_ingest_report.md` + `dist_ingest_report.log`.
- Campaign-level: `env/drift-report.json` (valid on a clean rental),
  `env/env-before.json` / `env/env-after.json`.
- Production reference: `20_benchmarks/numa5m/*` (stage 41).

## 19. Unsupported or optional features
- Placement-validation campaigns (paired) — `--placement-experiments paired`;
  `full` mode is diagnostics-only.
- Pipe ingestion — out of scope (WO 0.2: "Do not expand pipe ingestion").
- Production-worker integration — out of scope (WO 0.2).
- Fake-NUMA claiming to be physical — explicitly rejected everywhere
  (`numa=fake=4` is never a physical-NUMA evidence source).

## 20. Remaining known limitations
- No physical rental has been run yet; corrections-3 ready.
- The §11 rehearsal rehearsal and the §5/§2/§4 rehearsal verifications were
  conducted on the rehearsal host (fake-NUMA), not on physical rental hardware.
- Placement-validation campaigns (§2) and telemetry (§7–8) validated at the
  rehearsal-workflow level only (fake-NUMA); they exercise the campaign
  mechanics on a rented box without proving physical behavior.
- The §5.3 "per-node ingestor delays" apply to consumer/ingestor workloads
  (dist_ingest engine); the centralized baseline uses node 0's control.
- TSan/ASan evidence is for `dist_ingest.c`; production substrate
  (`forkrun_ring.c`) sanitizers remain on the forkrun production evidence path
  (`dev/supervisor/SANITIZER_EVIDENCE.md`).
- The rehearsal rehearsal of corrections-3 ran from the clean worktree
  `8d08c90e…` (the final tip).

## Cross-references
- `epyc/RENTAL_READINESS.md` — rehearsal-status doc (rehearsal-host view).
- `stage0/dist_ingest/CLOSEOUT.md` — closeout history through corrections-3.
- `epyc/RENTAL_DAY_WORKFLOW.md` — the documented rental procedure (step 7: `--placement-experiments paired`).
- `dev/supervisor/SANITIZER_EVIDENCE.md` — production (forkrun) sanitizer evidence.
