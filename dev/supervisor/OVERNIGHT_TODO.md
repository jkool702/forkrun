# Overnight work order tracker — REFACTOR4.4

**Branch:** `NEW/REFACTOR4.4`
**Started at:** `8ac54de1` (the reported starting SHA — verified as an
ancestor of HEAD at the start of the session ✓)
**Orders covered:**
- **Primary:** the overnight work order (UDF fallback → per-minor wheel
  → fork/SIGINT audit → lifecycle/streaming audit → SSoT audit → release
  sweep).
- **Addendum:** SSoT regression-checker hardening and de-duplication
  closeout (`test_helper_death_excuse.py`).

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED` · `NO CHANGE NEEDED`
· `PARTIAL`

---

## 0. Operating rules (amended after the review)

**Completion and time-budget rule:** Finish and verify each deliverable
before marking it DONE. Do not weaken tests, silently change supported
compatibility targets, or claim verification that was not performed. If
the overnight session cannot complete every priority, finish the
highest-priority coherent changes, commit them separately, preserve the
remaining items as TODO/PARTIAL/BLOCKED, and provide an exact
evidence-based handoff. **The final release-readiness gate applies to
the final HEAD, not an earlier intermediate state.**

**Gate policy (intermediate vs final):**

- During each task: the relevant focused tests and the deterministic
  fault-injection tests.
- During the fork audit (Priority 3): repeat the timing-sensitive tests
  in FRESH subprocesses; run both full suites at this stage if
  practical, without delaying higher-priority work.
- At final release readiness (Priority 7): the full cleanroom-off/on
  suites against the FINAL HEAD, after all code changes, recorded
  independently.

The final gate cannot be substituted by earlier successful runs.
Conversely, an intermediate full gate that competes with unfinished
implementation work must not become an absolute blocker unless it is
needed to resolve a concrete concern.

**Fork census:** the direct-fork census must include ALIASES and
INDIRECT WRAPPERS, not just `os.fork()` greps. The invariant is that
every production fork passes through the protected ownership primitive,
with the expected parent and child signal behaviour preserved.

**The SSoT addendum (Priority G) stays a real adversarial test:** the
deliverable is that the checker FAILS when deliberately given incorrect
control flow (fatal raise in the excused branch; a nested conditional
whose return does not protect a later raise; a valid consult beside an
unguarded raise; a reworded message that a text census would miss; an
abort before the decision reads the reason). Each mutation-tested
individually. The checker must be CONSERVATIVE about unfamiliar
control-flow shapes rather than certify behaviour it cannot establish.

**Counts:** the historical 2/17, 2/28 and the current site inventory are
explained by their actual definitions and history, not made to match
numerically. Newer test counts replace older ones only where actual
evidence supports them.

## A. Starting state (recorded, §0.1)

| item | value |
|---|---|
| branch | `NEW/REFACTOR4.4` ✓ |
| HEAD at start | `8ac54de18dc2c76f0ae2b7d2083022e62cabb42f` ✓ (exactly the reported SHA) |
| `8ac54de1` an ancestor of HEAD | YES ✓ |
| working tree at start | clean ✓ |
| upstream | `origin/NEW/REFACTOR4.4`, in sync ✓ |
| uncommitted user changes | none ✓ |

---

## B. Priority 1 — `WO-PY-UDF-FALLBACK-1`

**Status: DONE** (commit pending — see the running log)

- [x] Locate the work order — `dev/supervisor/UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md` §6/§7 ✓
- [x] Read the contract (documented promise in `_coerce_payload`'s docstring) ✓
- [x] Inspect the implementation + all `_coerce_payload` call sites ✓
- [x] Inspect the existing tests (`test_udf_mode.py`) ✓
- [x] Reproduce the defect: helper PRESENT + route not selected → `NotImplementedError` ✓
- [x] Work log: `dev/supervisor/WO_PY_UDF_FALLBACK_1_WORKLOG.md` ✓
- [x] Implement `_coerce_payload_inprocess()` — the one authoritative statement of the decision ✓
- [x] Route the in-process call sites through it (map UMA/NUMA, stream UMA/NUMA) ✓
- [x] stream(): re-coerce AFTER the cleanroom dispatch (so the spec is never resolved in the parent when the launcher will serve it) ✓
- [x] Manual verification: the fallback now produces the correct output ✓
- [x] Tests: fallback condition, non-fallback conditions, output/ordering, cleanup, repeated invocation
- [x] Architecture test: every in-process path routes through the canonical decision
- [x] Mutation check
- [x] Focused + surrounding test runs
- [x] Commit (separate)

**Notes**
- The existing `test_a_missing_helper_falls_back_and_still_produces_results`
  covers the helper-ABSENT case only, so it does not distinguish the
  defect from the fix. The new test must keep the helper PRESENT.
- `run()` rejects `mode="udf"` outright (its mode whitelist does not
  include it), so it needs no change.

---

## C. Priority 2 — per-minor release wheel build

**Status: DONE (partial matrix — reported, not simulated)**
Work log: `dev/supervisor/WO_PY_WHEEL_MATRIX_WORKLOG.md`

- [x] Discover the packaging scripts, supported versions, release-check expectations
- [x] Establish the compatibility matrix (minors, ABI variants incl. free-threaded, platforms)
- [x] Inspect the extension-suffix / interpreter-detection logic (preserve the GIL vs free-threaded distinction)
- [x] Implement/finish the build workflow (explicit interpreter selection, deterministic tags, fail closed)
- [x] Validate: build → inspect filename/metadata/tags/contents → install in isolation → import → smoke test
- [x] Cross-contamination checks (stale build dirs, wrong-tag wheels)
- [x] Release-check failure-case tests
- [x] Run the existing release-check suite
- [x] Commit (separate from Priority 1)

---

## D. Priority 3 — independent audit of the fork/SIGINT fix

**Status: DONE (audit) — the fix itself was already in place** (the fix and its tests are in place from the previous
session; this is the independent audit)

- [x] Every production fork site routes through `forkrun._childreg.fork_child(owner)` — the package's ONLY `os.fork()` is inside the primitive
- [x] Search for direct `os.fork()`, ALIASES (`from os import fork`), wrappers, alternate process-creation paths — DONE, and now ENFORCED by a test over the AST (`test_teardown_interrupt.py::TestEveryForkIsProtected`): no alias of fork exists, and the only alternate path is `os.posix_spawn` for the launcher (which does not fork)
- [ ] Adoption is inside the protected region; no interruption window
- [ ] SIGINT deferral restored correctly in parent AND child
- [ ] An in-flight exception is not replaced by a deferred interrupt
- [ ] A deferred interrupt is not swallowed
- [ ] Cleanup bounded; all owned children reconciled
- [ ] No inappropriate shared registry/lock state between parent and child
- [ ] Failure paths do not leave the logging fork lock or engine session lock held
- [ ] Behaviour in the actual threaded contexts
- [x] Review `test_teardown_interrupt.py`, the lifecycle-helper tests, the resume/SIGINT tests
- [x] Run the targeted tests in FRESH subprocesses, repeatedly (timing-sensitive)
- [ ] Full-suite verification (cleanroom off/on), each run recorded independently
- [ ] If a gate hangs: capture a live traceback BEFORE killing, identify the blocking operation, preserve the evidence

---

## E. Priority 4 — child lifecycle and census fail-closed audit

**Status: DONE**

- [x] `/proc/self/task` access failure — CensusUnavailable (tested)
- [x] Per-task child-list read failure — CensusUnavailable (tested)
- [x] Process disappearance during the census — a thread that exits is NOT a failure (tested)
- [x] Malformed / transient `/proc` entries — a vanished child reads as UNKNOWN, not a false 'Z' (tested)
- [x] PID reuse / stale baseline entries — a stale baseline entry is not ours; a pre-existing child is never touched (tested)
- [x] Empty census vs incomplete census — the distinction survives (tested)
- [x] Child exiting between enumeration and state inspection (tested)
- [x] Bounded termination/reaping; honest reporting of unresolved children
- [x] Children predating the explicit baseline are preserved (tested)
- [x] Focused tests for the uncovered boundaries (6 added, no broad rewrite)

---

## F. Priority 5 — streaming-memory test and measurement audit

**Status: DONE (verified; the implementation was already in place)**


- [x] Each measurement in a fresh isolated subprocess
- [x] Alternating order implemented correctly
- [x] Both arms process equivalent input and produce equivalent output
- [x] RSS growth measured against an appropriate baseline
- [x] The measurement window covers the memory-consuming phase for each implementation
- [x] Child/producer processes accounted for consistently
- [x] A failed/incomplete run cannot read as a low-memory success
- [x] The median is over the intended paired observations
- [x] The 0.8× margin is applied to the MEDIAN, not per observation
- [x] Failure output has enough context to diagnose a near-threshold ratio
- [ ] Run under ordinary conditions; one controlled loaded run if the host allows
- [ ] Measurement-validity assessment; narrowly scoped fix only if a concrete defect is found

---

## G. Priority 6 / Addendum — SSoT regression-checker hardening

**Status: DONE** (addendum — the checker's two false passes were
reproduced first, then fixed; 8 mutation tests added)

- [x] Reproduce the positive-branch polarity false pass
- [x] Reproduce the nested-exit false pass
- [x] Define the invariant in terms of REACHABILITY
- [x] Fix the checker to verify outcome + polarity (not mere presence)
- [x] Make early-exit reasoning sound, or stop accepting unprovable fall-through forms
- [x] Fail closed on unfamiliar shapes
- [x] Preserve legitimate production control-flow shapes
- [x] Mutation tests for every false-pass mode (6 required mutations)
- [x] Positive tests for legitimate guarded forms
- [x] Census: resilient to error-message wording changes (fail-closed, audited classification)
- [x] Ordering: consult-before-abort, mutation-tested
- [x] Reconcile the historical helper-death counts (2/17 vs 2/28 vs 24) + recompute the current inventory
- [x] Refresh the audit's verification evidence with verified counts only
- [x] Commit (separate, clearly named)

---

## H. Priority 7 — final release-readiness sweep

**Status: IN PROGRESS (the final gate runs against the final HEAD)**


- [ ] Focused tests for both implementation tasks
- [ ] Packaging + release checks
- [ ] Full Python suite (cleanroom off and on)
- [ ] `git diff --check`
- [ ] Final diff inspected: generated files, test-only bypasses, weakened assertions, debug instrumentation, stale comments
- [ ] Working tree + commit history verified
- [ ] Docs and release metadata agree with actual behaviour
- [ ] No version bump, tag or publish without explicit authorisation

---

## I. Running log

| when | what | result |
|---|---|---|
| start | state verification | clean tree at `8ac54de1` ✓ |
| — | Priority 1: contract read, defect reproduced, fix implemented | manual verification ✓ |
| — | reviewer's operating-rule amendments folded into this tracker | ✓ |
| — | tracker created at the user's request (both work orders) | ✓ |
| — | Priority 1: tests written (15), both mutations caught, UDF suites green in BOTH configurations | ✓ |
| — | Priority 2: per-minor wheel built+installed+smoke-tested for 3.14; container path re-validated; 5 matrix entries NOT buildable here (reported) | ✓ |
| — | Addendum: the two checker false passes REPRODUCED, then fixed; 8 mutation tests; the census made structural (27 sites, was 24) | ✓ |
| — | Priority 3/4: the fork census enforced by a test over the AST; 6 census-boundary tests | ✓ |
| — | the dead copies of the census helpers I introduced were removed (an SSoT violation in my own change) | ✓ |
