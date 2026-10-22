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

**Status: PARTIAL** — the ORCHESTRATION is complete and verified; the
per-minor RELEASE ARTIFACTS for 5 of the 6 minors are not.

The reviewer is right to keep these apart. The deliverables, and where
each stands:

| deliverable | state |
|---|---|
| canonical matrix + interpreter-selection logic | **done** — one list (`tools/wheel_matrix.py`), one interpreter lookup, free-threaded refused |
| honest detection of a missing interpreter/artifact | **done** — reported `not-built` with the reason; `--strict` fails the build |
| end-to-end wheel for CPython 3.14 | **done** — built, installed in isolation, imported, smoke-tested (substrate + launcher + the 3.14 helper) |
| end-to-end per-minor release wheels for 3.10-3.13, 3.15 | **NOT done** — no interpreter with an embeddable libpython is available here |
| shared-libpython build compatible with the manylinux floor | **NOT done** — this is the remaining work, specified below |
| free-threaded wheels | out of scope by the current decision (setup.py declines a free-threaded helper; the matrix refuses that interpreter) — explicitly not claimed |

### THE REMAINING BUILD WORK, SPECIFIED

The per-minor release wheel needs a CPython that (a) has a
**shared** libpython to embed, and (b) is built against the manylinux
image's glibc, so the wheel's floor is honest. The image's
`/opt/python/cp3XX-cp3XX` interpreters are built with a STATIC
libpython and the static archives are stripped, so neither (a) nor the
reuse path exists.

The remaining step, in the container:

1. build CPython with `--enable-shared` inside the manylinux image
   (the image's own build deps: libffi-devel, openssl-devel,
   zlib-devel, and a compiler), installed under a distinct prefix so
   it cannot be confused with the static interpreters;
2. point `wheel_matrix.interpreter_for_minor` at that prefix (a
   parameter, not a second hard-coded list);
3. the helper then links that interpreter's libpython, and the wheel
   is genuinely `manylinux_2_28` — auditwheel will confirm the floor
   rather than the build script asserting it.

Until that exists, the per-minor wheels for those minors are
**BLOCKED on a missing build input**, not merely untested, and this
tracker says so.

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
- [x] Adoption is inside the protected region; no interruption window
- [x] SIGINT deferral restored correctly in parent AND child
- [x] An in-flight exception is not replaced by a deferred interrupt
- [x] A deferred interrupt is not swallowed
- [x] Cleanup bounded; all owned children reconciled
- [x] No inappropriate shared registry/lock state between parent and child
- [x] Failure paths do not leave the logging fork lock or engine session lock held
- [x] Behaviour in the actual threaded contexts
- [x] Review `test_teardown_interrupt.py`, the lifecycle-helper tests, the resume/SIGINT tests
- [x] Run the targeted tests in FRESH subprocesses, repeatedly (timing-sensitive)
- [x] Full-suite verification (cleanroom off/on), each run recorded independently
- [x] If a gate hangs: capture a live traceback BEFORE killing, identify the blocking operation, preserve the evidence

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
- [x] Run under ordinary conditions — the paired measurement was run under
  ordinary conditions, under an ALTERNATING order (6 paired rounds), under
  16 CPU burners and under 20 GB of memory pressure, so the "one
  controlled loaded run" is covered several times over
- [x] Measurement-validity assessment — recorded in the audit: the ratio is
  0.39-0.50 in every controlled condition, with identical output bytes and
  sample counts in both arms; the producer-run-ahead explanation for the
  one 0.82 reading remains a HYPOTHESIS and is kept separate from the
  claim. No fix was needed, and none was made

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

## G2. RESOLVED: the suite-order failures were a real production bug

**Status: RESOLVED** — root-caused, fixed, and covered by a
mutation-checked regression test.

Both failures are in tests that patch a MODULE ATTRIBUTE
(`os.stat` in `test_checkpoint_gate.py`, `os.write` in
`test_fault.py`). In both, the patch silently does not take effect
after the patch has been applied, so the test sees the REAL function.

| fact | evidence |
|---|---|
| Both pass in isolation | `python3 -m unittest tests.test_checkpoint_gate.TestCheckpointGate.test_foreign_uid_refused_without_trust` → OK |
| Both fail as a pair with `test_capability_dispatch` | 28 tests, 0.27s → FAIL (a fast, deterministic reproduction) |
| The pair PASSES with the previous commit's `run.py` | reverting `python/forkrun/run.py` → OK; restoring it → FAIL |
| The patch is not applied | instrumenting the gate: `os.stat` inside the `with mock.patch("os.stat", ...)` block is `<built-in function stat>`, and the `os` module is the SAME object (`id()` equal) the gate uses |
| The previous commit's full suite passes | `git checkout 8ac54de1` → 1489 tests OK, in the same tree with the same built artifacts |
| The product is NOT implicated | the checkpoint gate's own unit test passes; `forkrun/_checkpoint.py` is untouched by this session's changes |

**ROOT CAUSE** (established): `forkrun/_worker.py::resolve_payload_parent`
implements the freshness rule by dropping the leaf module from
`sys.modules` and re-importing it -- which produces a NEW MODULE
OBJECT. For a user module that is the point. For a BUILT-IN, FROZEN
or EXTENSION module it is a defect: `os` is FROZEN, so re-importing
it hands the process a different `os` while every module imported
earlier (including `forkrun._checkpoint`) still holds the old one.
A patch applied to the current `os` is then invisible to the code
under test.

**What exposed it:** the `mode="udf"` fallback resolves the spec in
the PARENT (that is the documented fallback), and the capability
matrix's UDF cell uses the spec `"os:getcwd"` -- so the fallback
started dropping and re-importing `os`. Two unrelated tests that
patch `os.stat` / `os.write` then failed, for reasons that had
nothing to do with their own code.

**The fix:** the drop is now limited to SOURCE modules
(`_is_source_module`). A built-in is never "rewritten between calls",
so the freshness rule has nothing to do there -- and replacing a
frozen module object was never intended. The process no longer ends
up with two `os` objects.

**The regression test** (in `test_udf_fallback.py`) asserts that
resolving a spec does not replace the `os` module object, and that
the freshness rule still works for a user module. Mutation-checked:
removing the source-module guard makes the first fail.

## H. Priority 7 — final release-readiness sweep

**Status: DONE** — the final gate is GREEN in BOTH configurations, on
the final HEAD:

| configuration | tests | result |
|---|---|---|
| cleanroom off | 1540 | **OK** (2 skipped) |
| cleanroom on | 1547 | **OK** (1 skipped) |

`git diff --check` clean; the tree clean; nothing running afterwards.


- [x] Focused tests for both implementation tasks
- [x] Packaging + release checks
- [x] Full Python suite (cleanroom off and on)
- [x] `git diff --check`
- [x] Final diff inspected: generated files, test-only bypasses, weakened assertions, debug instrumentation, stale comments
- [x] Working tree + commit history verified
- [x] Docs and release metadata agree with actual behaviour
- [x] No version bump, tag or publish without explicit authorisation
- [x] The gate is GREEN in both configurations on the final HEAD (see the
  table above)

---

## I0. Residual concerns (final)

1. **The per-minor release wheels for 3.10-3.13 and 3.15 are BLOCKED
   on a missing build input** — a CPython with a shared libpython
   inside the manylinux image (§C specifies the step). The
   orchestration is done and verified; the artifacts are not.
2. **The host-built wheel is not a valid manylinux_2_39 artifact**:
   auditwheel refused to repair it ("too-recent versioned symbols"),
   i.e. the binary needs a newer glibc than the tag claims. That is
   why the release path must be the container — and why the remaining
   work above has to build the interpreter there too, rather than
   reusing the host's.
3. **The streaming producer-run-ahead explanation remains a
   hypothesis.** The measurements are solid (0.39-0.50 across
   alternating order, CPU load and memory pressure); the mechanism for
   the one 0.82 reading is not established. The documentation keeps
   the claim and the theory separate.
4. **The addendum's "a consult in an unrelated sibling branch cannot
   justify an abort in another branch" case is enforced for the
   RAISE; the abort half rests on the same-block rule.**
5. The `setup.py` classifiers now say 3.10-3.15 (they stopped at
   3.13) — they describe the SOURCE install's support target; the
   per-minor WHEELS for five of those minors do not exist yet (1).

## I. Running log

**Commit count (housekeeping).** The count moved as the session added
its fix commits, and the reports disagreed with each other (nine in the
morning report, seven in the reviewer's GitHub comparison, eight in the
first tracker revision). The authoritative figure is
`git rev-list --count 8ac54de1..HEAD`, and the tracker now states the
count that command returns at the time of reading it.

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
| — | the two suite-order failures were ROOT-CAUSED: a FROZEN module object was being replaced by the freshness rule | ✓ |
| — | FINAL GATE on the final HEAD: 1540 OK cleanroom-off, 1547 OK cleanroom-on | ✓ |
