# Handover — fresh coordinating instance (post-tonight W-REL5)

## Where things stand

- **Merged tree:** branch `wrel5-alpha` (worktree `/mnt/ramdisk/forkrun-alpha`;
  main checkout `/mnt/ramdisk/forkrun` is at `NEW/REFACTOR2.9` post-G0 and
  was NEVER touched tonight — verify with `git status` before anything).
  Tonight merged: Track-α W-REL5-B + Track-β W-REL5-A, E-docs subset,
  BASHCOMPAT Phase 0 (diagnosis only). Beta branch `wrel5-beta`
  (`/mnt/ramdisk/forkrun-beta`) is fully merged — do not use further.
- **Verification state:** serial matrix green on the merged tree (full
  suite 605×3, bash 92+264 foreground, referees 30/30, release_check
  17/17, C-diff empty, 1M-line perf band held). Two coordinator fix
  commits on top of the merge (B4 2ms quantum; DOCS_ALL B-mirror).
  Morning report: `dev/supervisor/WREL5_MORNING_REPORT.md` (this dir).
- **NEVER merged/pushed to release:** no tag, no main push. `wrel5-alpha`
  push to origin is permitted (working branch) but was NOT done tonight —
  decide with the owner (pre-merge CI on the branch needs the TEMP-filter
  trick from the G0 report if reused).

## Remaining sequence (serial, in order — dependency graph is law)

1. Serial full matrix on merged tree — DONE (above). Re-run only if the
   tree moves.
2. **W-REL5-C** (depends on B: file overlap + C9 builds on B5, C2/C6
   build on B2). Python robustness wave — NOT started.
3. **E-python subset** (E5/E6/E7/E15 — conflicted with B pre-merge, now
   clear). Do NOT touch anything else from E (done).
4. **W-BASHCOMPAT fix phase** — BLOCKED on owner calls (see below).
   Depends on A landed; fold blob rebuild into D's cycle (ONE blob
   cycle total). Read `dev/supervisor/BASHCOMPAT_DIAGNOSIS.md` first —
   Phase 0 refutes the 5.3-`enable` framing; proximate killer is the
   0.9MB single-line `declare` death + a latent `-e` landmine.
5. **W-REL5-D LAST** (carries BASHCOMPAT engine shims + own sites; one
   blob cycle + full matrix).
6. F2–F6 → merge to main → tag prep (owner ratifies the tag).

## Sub-agent orchestration rules (carry forward verbatim)

- One git worktree + one branch per track; sub-agents verify
  toplevel/branch before first edit; touching another worktree = protocol
  violation = invalid diff, re-dispatch.
- Narrow context per agent: its work order + worktree/branch + the shared
  constraints block; nothing about other tracks.
- Shared constraints block (prepend to EVERY dispatch): worktree-only;
  commit per item; bite-then-green on behavioral change; red lines §7.1
  (no CAS loops, no fence changes, no scanner-macro restructuring, no
  `PATH=''`, `-c` sandbox quote-free, canary stub list shrink-only,
  twins lockstep); CHANGELOG/DOCS_ALL append-only under the wave's own
  heading; overnight gates = bites + targeted tests + fast referees only
  (test_executor_consistency, test_invariant_gate, test_doc_accuracy,
  test_shim_abi); NO full suites / bash 92-264 / heavy NUMA by sub-agents;
  flake registry first (C-drain framing header, reactor-ingest multiset,
  T10b, M8 HUP-window, bench denominator-noise), never rerun-until-green;
  new-failure signature = STOP item + write up; halt-and-report on spec
  collision; completion report (per-item table, bites, files, gates,
  incidents, SHA).
- Parallelism rule: concurrent iff file surfaces disjoint. C vs anything
  python-side = serial. E-python vs B/C = serial after them.
- Serial gates are coordinator-only: full suites, bash suites, heavy NUMA,
  release_check. No product decisions (owner decides). No tag, no release
  push. Halt-and-report is success.

## R5.x rules that persist

- R5.3 C-diff audit on every merge (tonight: empty; D will touch C —
  enumerated list + one blob cycle).
- R5.4 perf band on ingest-touching changes (tonight: B4 quantum lesson —
  20ms poll quantum cost +40ms systematic on ms-scale paths; keep quanta
  ≤2ms or use instant-wakeup primitives; verify with
  test_c_drain_not_slower + 1M band).
- R5.5 no rerun-until-green (kept tonight: deterministic sets cited).
- R5.6 no renames (`forkrun.run` stays a function).

## Pending owner ratifications (get before dispatching fix phases)

1. B1 `sink=` REJECT. 2. Bash floor 4.4. 3. BASHCOMPAT targeting
   (declare-line/`-e` vs 5.3-framing vs both) + A1
   cloexec-with-passthrough design. 4. Tag path (owner executes).

## Known sharp edges (learned tonight, don't relearn)

- `gh workflow run --ref` resolves workflow FILES against main: branch-only
  workflow files 404. Branch CI needs either a (possibly unmergeable) PR
  or a TEMP push-filter commit (revert after green).
- Draft PR from a diverged branch schedules NO pull_request runs when
  unmergeable (mergeable=false) — observed, mechanism inferred.
- GitHub runner timing: 4-vCPU CI boxes flip batch-geometry/timing tests
  that are green on 28-thread iron (v0 poison, resume ×7, sigint,
  numa-fault, doc-accuracy claims) — environmental, proven via taskset;
  full-size-box evidence is the release signal.
- Fedora-minimal lacks `cmp` (diffutils) — pinned in python-check.yml.
  Sanitizer legacy quoting bug fixed (`\$NF`).
- Ubuntu runners carry bash 5.2: native bash smoke cannot pass until the
  compat fix (declare-line/`-e` per Phase 0, not `enable`).
- `test_c_drain_not_slower` is a load-bearing micro-gate (2× on ~10ms
  inputs) — any join/poll-quantum change trips it fast; keep it in the
  loop for C/D waves touching reactor/teardown paths.
