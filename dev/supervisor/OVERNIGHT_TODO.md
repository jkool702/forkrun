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

**Status: TODO**

- [ ] Discover the packaging scripts, supported versions, release-check expectations
- [ ] Establish the compatibility matrix (minors, ABI variants incl. free-threaded, platforms)
- [ ] Inspect the extension-suffix / interpreter-detection logic (preserve the GIL vs free-threaded distinction)
- [ ] Implement/finish the build workflow (explicit interpreter selection, deterministic tags, fail closed)
- [ ] Validate: build → inspect filename/metadata/tags/contents → install in isolation → import → smoke test
- [ ] Cross-contamination checks (stale build dirs, wrong-tag wheels)
- [ ] Release-check failure-case tests
- [ ] Run the existing release-check suite
- [ ] Commit (separate from Priority 1)

---

## D. Priority 3 — independent audit of the fork/SIGINT fix

**Status: TODO** (the fix and its tests are in place from the previous
session; this is the independent audit)

- [ ] Every production fork site routes through `forkrun._childreg.fork_child(owner)`
- [ ] Search for direct `os.fork()`, ALIASES (`from os import fork`), wrappers, alternate process-creation paths (posix_spawn, subprocess, multiprocessing) — and classify every legitimate exception explicitly
- [ ] Adoption is inside the protected region; no interruption window
- [ ] SIGINT deferral restored correctly in parent AND child
- [ ] An in-flight exception is not replaced by a deferred interrupt
- [ ] A deferred interrupt is not swallowed
- [ ] Cleanup bounded; all owned children reconciled
- [ ] No inappropriate shared registry/lock state between parent and child
- [ ] Failure paths do not leave the logging fork lock or engine session lock held
- [ ] Behaviour in the actual threaded contexts
- [ ] Review `test_teardown_interrupt.py`, the lifecycle-helper tests, the resume/SIGINT tests
- [ ] Run the targeted tests in FRESH subprocesses, repeatedly (timing-sensitive)
- [ ] Full-suite verification (cleanroom off/on), each run recorded independently
- [ ] If a gate hangs: capture a live traceback BEFORE killing, identify the blocking operation, preserve the evidence

---

## E. Priority 4 — child lifecycle and census fail-closed audit

**Status: TODO**

- [ ] `/proc/self/task` access failure
- [ ] Per-task child-list read failure
- [ ] Process disappearance during the census
- [ ] Malformed / transient `/proc` entries
- [ ] PID reuse / stale baseline entries (to the extent claimed)
- [ ] Empty census vs incomplete census (the distinction must survive)
- [ ] Child exiting between enumeration and state inspection
- [ ] Bounded termination/reaping; honest reporting of unresolved children
- [ ] Children predating the explicit baseline are preserved
- [ ] Focused tests for any uncovered boundary (no broad rewrite)

---

## F. Priority 5 — streaming-memory test and measurement audit

**Status: TODO**

- [ ] Each measurement in a fresh isolated subprocess
- [ ] Alternating order implemented correctly
- [ ] Both arms process equivalent input and produce equivalent output
- [ ] RSS growth measured against an appropriate baseline
- [ ] The measurement window covers the memory-consuming phase for each implementation
- [ ] Child/producer processes accounted for consistently
- [ ] A failed/incomplete run cannot read as a low-memory success
- [ ] The median is over the intended paired observations
- [ ] The 0.8× margin is applied to the MEDIAN, not per observation
- [ ] Failure output has enough context to diagnose a near-threshold ratio
- [ ] Run under ordinary conditions; one controlled loaded run if the host allows
- [ ] Measurement-validity assessment; narrowly scoped fix only if a concrete defect is found

---

## G. Priority 6 / Addendum — SSoT regression-checker hardening

**Status: TODO** (this is the addendum; see §G detail below)

- [ ] Reproduce the positive-branch polarity false pass
- [ ] Reproduce the nested-exit false pass
- [ ] Define the invariant in terms of REACHABILITY
- [ ] Fix the checker to verify outcome + polarity (not mere presence)
- [ ] Make early-exit reasoning sound, or stop accepting unprovable fall-through forms
- [ ] Fail closed on unfamiliar shapes
- [ ] Preserve legitimate production control-flow shapes
- [ ] Mutation tests for every false-pass mode (6 required mutations)
- [ ] Positive tests for legitimate guarded forms
- [ ] Census: resilient to error-message wording changes (fail-closed, audited classification)
- [ ] Ordering: consult-before-abort, mutation-tested
- [ ] Reconcile the historical helper-death counts (2/17 vs 2/28 vs 24) + recompute the current inventory
- [ ] Refresh the audit's verification evidence with verified counts only
- [ ] Commit (separate, clearly named)

---

## H. Priority 7 — final release-readiness sweep

**Status: TODO**

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
