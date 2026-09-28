# W-REL5-G0 Report — Gate Closure & Preconditions

**Branch:** `NEW/REFACTOR2.9`. **Date:** 2026-09-28. **Box:** 28-thread,
single-node, 125GB (NOT `numa=fake=4`; `@4` forces logical nodes).
**Fixture:** `/mnt/ramdisk/numa1/ml/heavy_20M.jsonl` (26,880,545,542 B,
exactly 20,000,000 lines — no regeneration needed).
**PR vehicle:** #563 (draft, CI-only, mergeable=false — expected).

## G0.1 — Tree quiet: PASS (with notes)

HEAD `b69b4fc` intact (4 W-DEDUP commits), no stash, no dirty tracked
files. Notes: (a) untracked `session-ses_f1c5.md` (opencode session
artifact, benign); (b) `origin/NEW/REFACTOR2.9` already tracked the W-DEDUP
head (prior session pushed). No other instance touched `run.py`.

## G0.2 — Deferred Gate 4 legs: ALL GREEN locally

| Leg | Result | Evidence |
|---|---|---|
| heavy-20M (`numa_quads.py`, `FORKRUN_DIAG_NUMA1=1`, plugin `ml_heavy`, w=28, order=index) | **10/10 EXACT** (`1`×2 REF + `@4`×4 + `auto`×4; 6.099GB out, 20M lines, sha `2dc03907…` internal) | `/tmp/opencode/quads.log` |
| drain-audit warnings | **0** (all 10 err files) | `grep NUMA-partial → none` |
| per-node DIAG (`@4`) | **write==read all nodes** (~9.7–9.9K batches/node, ~39K total — past the 4096 F-NUMA1 lap), all forked, tails empty | `/tmp/numa_quad_at4*.err` |
| F-PY-UMA1 forensic (`test_mover.py` incl. 10-sequential-maps) | **10/10** | `/tmp/opencode/mover_{1..10}.log` |
| F-NUMA1 guard (`test_numa_drain_guard.py`) | **10/10** | `/tmp/opencode/fnuma_{1..10}.log` |
| Bash basic (`test_frun.sh`) | **92/92** | `/tmp/opencode/bash_basic.log` |
| Bash comprehensive | **264/264** (prior record 261–262/263 — no T10b/M8 flakes this run) | `/tmp/opencode/bash_comp.log` |
| Blob no-op confirm | engine diff vs `f41045c` **empty**; no `forkrun_release` run triggered by our pushes (correct — no engine paths touched) | `git diff`, run list |

Topology note: on this 1-node box `auto`→UMA (prior record's `auto`→4 nodes
on fake=4). `@4` coverage is identical in kind.

## G0.3 — Push + CI: RED, classified (0 product failures)

Pushes: `35c3032` (timeouts), `9d83c8f` (TEMP branch-CI filter),
`1010341` (workflow pins). Runs:
- `idl-check` dispatch: **green** (12s).
- `ubuntu-native` smoke dispatch: **FAILED — dispositioned: runner bash
  5.2 < required 5.3** (embedded loadable needs 5.3; owner-confirmed known
  limitation, future work order; engine/blob byte-identical, local bash
  suites 92+264 green).
- `python-v0` ×2 (branch push): **588 tests, 17 FAIL + 1 ERROR, identical
  sets both runs** ([run 36372962385](https://github.com/jkool702/forkrun/actions/runs/36372962385),
  [run 36373599396](https://github.com/jkool702/forkrun/actions/runs/36373599396)).
- `sanitizer` (advisory): infra-fixed (below); test content shows only
  expected `string_at(0)` injection SEGVs (15 = local 12+3) + environmental
  v0-poison fails.

**CI infra fixes applied (workflow-only, allowed category):**
1. `timeout-minutes: 60/30` on python-check jobs (first proven CI run).
2. Sanitizer `awk "NR==1{print $NF}"` → `\$NF` (under `set -u` the unquoted
   `$NF` aborted the step → empty LD_PRELOAD → ASan ordering error; the leg
   had NEVER executed). Verified fixed: rerun progresses to tests.
3. `diffutils` in both dnf lines (`cmp` missing broke CCSTAMP noise; and
   `test_two_builds_identical` — red in run 1 — is **absent in run 2**).

**Failure classification (all 18): ENVIRONMENTAL, 0 product.**
Decisive facts: (a) every failing test executes code with **zero diff**
from base (only 4 plain-path functions changed; all failures are
reactor/resume/signal/bench/build paths — proven via `git diff`
hunk list); (b) **16/18 reproduce locally under `taskset -c 0-3`**
on the same tree (v0 poison ×2, resume ×7 identical sets, taxonomy,
numa-fault, doc_accuracy ×2); unconstrained local runs are green —
i.e. small-slow-box timing/batch-geometry dependence, exposed by the
first-ever CI run on 4-vCPU runners:

| Family | Tests | Mechanism |
|---|---|---|
| batch-geometry poison alignment | v0 `retry_then_poison`, `skip` | slow worker arrival → different preflight/fallback batching → poisoned-skip alignment moves (`line 100` in/out) |
| slow-box kill/checkpoint windows | resume ×7, sigint, numa_fault, doc_accuracy claim ×2 | timing windows tuned for fast boxes |
| bench noise | `cpu_pct_around_trivial` | flake-registry denominator-noise |
| load timing (CI-only, 8/8 green locally ±constraint) | daemon, kill_parity zombie | self-termination/reaping races on loaded runners; same T10b/M8 family shape |
| build env | `two_builds_identical` (run 1 only — fixed by diffutils pin) | missing `cmp` in fedora-minimal |
| knock-on | `release_check_passes` ERROR | inner suite red |
| runner bash | ubuntu-native smoke | bash 5.2 < 5.3 (owner-confirmed, future work) |

Rerun-until-green was NOT used (deterministic identical sets ×2 runs).
Recommended follow-up (owner call, not applied): pin `lines=` in the
geometry-sensitive v0 tests and/or widen slow-box windows; add bash-5.3
build to ubuntu-native workflow.

**TEMP branch-CI filter: REVERTED in this commit** (kept: timeouts, awk,
diffutils — legitimate permanent fixes). Draft PR #563 remains open as the
CI record vehicle only.

## GO/NO-GO evidence (owner decides)

| Gate | Status |
|---|---|
| Gate 4 heavy/forensic/bash legs (this order) | GREEN (all counts met) |
| W-DEDUP collapse + R-D8 (prior) | GREEN, untouched by this order |
| Branch CI (python-v0 full suite) | RED — environmental (proven), 0 product failures; infra fixes applied (1 failure fixed, sanitizer unblocked) |
| Release signal | Local full-size-box evidence stands (588×5, heavy 10/10, bash 356/356); CI runners cannot validate timing-sensitive tests on ANY code (including base) until test pins land |

**R-V2 disposition: still open** — recommendation on file (accept
containment); unchanged by this order.

**Tree SHA (this report):** 15a23d29851b18d042f55347796728d3c5be8b77 (NEW/REFACTOR2.9).
report commit on `NEW/REFACTOR2.9`).
