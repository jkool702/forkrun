# P1-3 — UDF helper integration: where does the interpreter live?

Status: **design brief, for review.** Nothing implemented.
Predecessor: DECISION-01 §9 (helper exists, C0.4 answered).
Branch: `NEW/REFACTOR4.2`.

## 1. The question

`fr_udf.c` builds and is measured. What is not decided is *where the
interpreter gets initialised and where the per-batch UDF call site lives*.

This is not a free choice: the answer determines whether workers pay an
interpreter start each, and it interacts with both supervision policies.

## 2. Constraints that already bind

**(a) The helper cannot be loaded into a process that has Python.**
DECISION-01 §9.2 — `fr_udf_init` calls `Py_InitializeFromConfig`; doing
that in a live interpreter is undefined and core-dumps in practice. So the
host must be a process with no interpreter. The launcher qualifies; the
Python parent does not.

**(b) Pre-fork is measured and works** (DECISION-01 §9.3): a forked child
inherits the interpreter and runs the UDF correctly, 4–8× faster than
post-fork. This is safe only because the launcher is single-threaded at
the fork.

**(c) The codebase already has a precedent, and states the rule.**
`forkrun_cleanroom.c` `spawn_wid`:

> Takes the pointer the parent already resolved: dlopen after fork is a
> classic post-fork hazard.

and `g_poison_stats_fd`:

> Set once in `main()` before any fork so it is inherited.

So the existing design already resolves "dlopen pre-fork, inherit" for
both the substrate handle and the poison relay. The UDF helper is a third
instance of a pattern the launcher is built around.

**(d) `forkrun_cleanroom.c` is NOT frozen.** The freeze list is
`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`. The launcher
is modifiable — provided the engine is not touched, which this does not
require.

## 3. Options

**Option A — launcher-owned, pre-fork (recommended).**
`main()` resolves and `dlopen`s the helper, calls `fr_udf_init` once,
*before any fork*. The handle and init state are inherited by every
worker. The per-batch call lives in the worker path
(`fr_py_worker_plugin_loop`, which the cleanroom already runs per worker).

*Satisfies (a) — launcher has no interpreter. (b) — pre-fork. (c) —
identical to the existing pattern for the substrate and poison relay.*

**Option B — shim-owned lazy init (`_shim.c` dlopens on first use).**
Simpler: no launcher changes. But first use happens *inside a worker*,
after fork. That is post-fork by construction — the 4–8× slower path, per
worker, forever. Directly contradicts (c).

**Option C — run.py-owned, path passed down.**
The parent resolves nothing; it hands the helper path to the launcher via
argv/env, launcher does A. Functionally A with extra plumbing, and it
puts an interpreter concern in the process that must not have one.
Rejected: adds a channel for no behaviour change.

## 4. Recommendation — Option A

Three reasons, in order of weight:

1. **It is the only option that gets the measured win.** B is post-fork by
   construction. C is A with a needless channel.
2. **It follows a rule the launcher already documents and enforces.**
   Introducing a second, different dlopen discipline for the third
   handle would be the inconsistency, not Option A.
3. **It needs no engine change**, so the freeze holds.

## 5. Where the genuine open choice remains

Option A settles *where init happens*. Two things it does **not** settle,
and which should be decided with evidence rather than assumed:

* **The per-batch call site.** Now much better constrained by the code
  itself: there are four worker loops (`splice`, `plugin`, `spawn`, plus
  `fallow`), all identical in shape — claim → invoke → `fr_py_complete` /
  `fr_py_escrow_deposit` / `fr_py_abort` — differing **only** in the invoke
  step. A UDF therefore looks like a fifth loop by the codebase's own
  convention, not a special case. Routed for external review as
  `P1-3-EXTERNAL-REVIEW.md`, together with the one genuine tension:
  the plugin loop deliberately dlopens **post-fork** ("a parent-handle
  pointer would dangle on dlclose and entangle refcounts across fork"),
  which sits against the measured 4–8× win for pre-fork init.
* **Interaction with supervision.** Under `recover`, a worker that dies
  mid-UDF is respawned; under `fail-fast` the run aborts. A UDF has
  Python-level state and can leave imported modules half-initialised.
  *RESOLVED by measurement — see §5.1.*

### 5.1 Respawn inheritance — MEASURED, and the answer is reassuring

`fr_udf_fork --respawn` dirties interpreter state in one generation, kills
it without cleanup, then forks the next generation and asks whether the
state survived.

**Result: CLEAN.** A respawned generation does **not** inherit the dead
generation's interpreter state. Under pre-fork each generation is a fresh
fork of the launcher, which still holds the *pristine* pre-fork
interpreter, so the dirt dies with the child that made it.

This was worth measuring rather than arguing, because the failure would be
silent and shared: two batches observing each other's mutated module
globals, non-deterministically, only on the recovery path.

**The probe carries its own negative control** (`--control`), and this is
the part that makes the CLEAN verdict mean anything: it dirties and checks
in a *single* process, where the state certainly survives, and must
report DIRTY. A probe capable of only ever answering CLEAN would pass the
respawn test forever while detecting nothing. Both directions are pinned
by tests, and the DIRTY side is mutation-checked.

Two bugs surfaced while building it, both mine and both the kind that
produce a confident wrong answer:

* The respawn branch ran *after* `fr_udf_finalize()`, so every call
  returned "not initialized" and the probe reported **INCONCLUSIVE** —
  which looks like "no evidence" rather than like "the harness is
  broken".
* Children inherited the parent's unflushed `stdout` buffer, and a child
  that finalises Python flushes stdio on the way out. Each child
  re-printed the header, making one run look like four.

## 6. What "done" means for P1-3

* A UDF that resolves, runs, and emits through the existing record path,
  under **both** `--supervise recover` and `--supervise fail-fast`.
* A UDF returning `None` → `NO_RESULT`; `b""` → empty `DATA` (DECISION-02).
* A UDF that raises → worker death, handled by the normal supervision
  path, not by new special-casing.
* A respawn test that proves a fresh generation does not inherit dirty
  interpreter state.
---

## 10. External review outcome: GO WITH AMENDMENTS — accepted, with one correction

Reviewed against `P1-3-EXTERNAL-REVIEW.md`. Verdict: Option A, dedicated
fifth loop, pre-fork init — **conditional on integrating CPython's fork
lifecycle hooks**. That condition was real and we had missed it.

### 10.1 Accepted amendments

1. **CPython fork hooks are now implemented** (`fr_udf_before_fork`,
   `fr_udf_after_fork_parent`, `fr_udf_after_fork_child`), fail closed,
   and are centralised in ONE `udf_fork()` helper in the driver so no call
   site can omit them.
2. **`HAVE_FORK` guard** — the hooks live behind CPython's own conditional.
   They do **not** degrade to no-ops when absent; they return
   `FR_UDF_ERR` and `fr_udf_fork_hooks_available()` reports the fact.
3. **A raising UDF is a batch-level payload failure**, routed to the
   existing `on_error` policy (retry/escrow → skip → fail-fast), *not* a
   worker death. `fr_udf_call` already cleared the pending exception via
   `PyErr_Print`; this is now stated as a contract.
4. **Buffer ownership** — `fr_udf_free()` already existed and is now
   documented as mandatory, not optional.
5. **Parent must not import or invoke the UDF** — user-module state stays
   worker-local.
6. **State model documented** — module globals persist across batches
   within a worker; a respawned generation starts clean and may repeat
   module-import side effects.
7. **DECISION-02 limitation preserved and stated** — a `None` result
   acks without a data record, so the ordered parent cannot infer
   completion. No completion-coverage claim until dispositions land.

### 10.2 Two findings from implementing the amendment

**The first hook wiring aborted every pre-fork child.**
`PyMutex_Unlock: unlocking mutex that is not locked`, SIGABRT. Cause was
ours: `udf_fork()` ran the parent hook in *both* processes, so the child
unlocked the mutex that `PyOS_AfterFork_Child()` owns. Found by the hooks,
not by inspection — and a reminder that the reviewer's caution ("the
implementation that earned those measurements may not be the one that
should ship") was aimed at exactly this class of thing.

**The hooks are not load-bearing *here*, and we are not going to claim
they are.**

> **Correction (external review, second pass).** An earlier draft of this
> paragraph justified the hooks partly by "a UDF that spawns a thread".
> That was wrong and overstated. A UDF spawning threads inside its own
> worker child happens strictly *after* the fork, so it cannot make the
> launcher multithreaded and is irrelevant to the precondition. The
> precondition is precise and narrow: **at the moment the launcher calls
> `fork()`, the launcher process itself has exactly one thread.** Threads
> created later, inside a worker, do not bear on it. `fr_udf_fork --hooks` deliberately violates the choreography
and reports the outcome. On this single-threaded, contention-free machine
the unhooked child **survives**. So on this configuration the hooks change
no observable behaviour; they protect cases this harness never creates
another thread existing in the LAUNCHER at fork time. They stay because
CPython documents them as mandatory for this embedding pattern — not
because a test here proves it. Recorded rather than buried, because
"we added the hooks and it fixed a bug" would be false.

### 10.3 Re-measured with hooks (reviewer required this)

| children | post-fork | pre-fork | speedup | failures |
|---|---|---|---|---|
| 1 | 0.0118 s | 0.0010 s | 11.29× | 0 |
| 2 | 0.0099 s | 0.0012 s | 8.22× | 0 |
| 4 | 0.0097 s | 0.0014 s | 6.93× | 0 |
| 8 | 0.0123 s | 0.0018 s | 6.81× | 0 |

Respawn probe: still CLEAN. Negative control: still detects dirt. The
reviewer asked for these to be re-run against the hook-aware build; they
are, and the result strengthened rather than weakened.

### 10.4 Still not done

No launcher or shim integration code. `fr_py_worker_udf_loop` does not
exist yet. Parity tests for shared lifecycle behaviour (required by the
reviewer once the loop is written) are not written, because there is no
loop to test. Conditions of approval therefore remain **open**.

---

## 11. External review, confirmation pass — closed with two corrections

Answers received on `P1-3-CONFIRMATION.md`. The design was **not**
reopened. Two items required action; both are done.

### 11.1 Confirmed as-is

Our reading that the SIGABRT was *our* wiring error rather than evidence
the earlier hookless measurements were invalidated: **accepted**. The
new hook-enabled table is the result to report for the implementation
being considered.

### 11.2 CORRECTION 1 — the fork-time precondition was stated wrongly

We had justified the hooks partly by "a UDF that spawns a thread". That
was wrong and overstated: a UDF spawning threads inside its own worker
child happens strictly *after* the fork, so it cannot make the launcher
multithreaded.

The precondition is now stated precisely in `fr_udf.h` and here:

> **At the moment the launcher calls `fork()`, the launcher process has
> exactly one thread.**

Threads created later, inside a worker, do not bear on it. Corrected in
both places.

### 11.3 CORRECTION 2 — `PyErr_Print()` was a real bug, not just noise

The review flagged that `PyErr_Print()` **exits the process for
`SystemExit`** rather than returning. Confirmed on our own code before
changing anything: a UDF calling `sys.exit(3)` terminated the entire
helper with exit code 3.

The consequence was worse than a noisy traceback. A `SystemExit` is an
ordinary batch-level payload failure — the kind `on_error` exists to
handle — but it was becoming a **worker death**, so the batch was lost
and retry/skip/fail-fast were all bypassed, because the process was gone
before any of them could run. One line of user code in a UDF could
silently convert a recoverable batch error into a fatal worker loss.

Replaced with structured extraction (`take_exception`):
extract → clear → one-line diagnostic; full traceback opt-in via
`FR_UDF_TRACEBACK=1`. Version-compatible across the 3.10–3.15 target:
`PyErr_GetRaisedException()` on 3.12+, `PyErr_Fetch()` below that (it is
deprecated since 3.12).

The diagnostic includes the **exception type**, because
`str(SystemExit(3))` is just `"3"` — without the type,
`udf raised: 3` says nothing about what happened:

```
udf raised: SystemExit: 3
```

Both directions are mutation-checked: restoring `PyErr_Print()` fails
`test_systemexit_is_a_batch_error_not_a_worker_death` and
`test_exception_diagnostic_names_the_type`.

### 11.4 Speedup scope, as instructed

Reported as: **6.8–11.3× measured on CPython 3.14.7, single-threaded
launcher, hooks enabled.** Other minor versions and multithreaded-fork
scenarios remain unverified, and the 3.10–3.15 matrix stays deferred.

### 11.5 Approval status

Still **OPEN**, unchanged: no `fr_py_worker_udf_loop`, no launcher
integration, no parity tests across the existing loops. Those remain
conditions, not partial credit.

---

## 12. P1-3 implementation status (in progress)

### 12.1 Landed

**The fifth loop** (`_shim.c`):
- `fr_py_worker_udf_loop` — same lifecycle as the other four modes,
  reusing `fr_py_claim` / `fr_py_complete` / `fr_py_escrow_deposit` /
  `fr_py_abort`. No new retry, ack, or poison policy.
- `fr_py_udf_invoke` — the invoke body: batch window → `fr_udf_call` →
  framed result.
- `fr_py_emit_record_buf` — frames an **in-memory** payload with an
  **explicit** disposition. Required because `fr_py_emit_record` takes
  its payload from an fd *and* infers NO_RESULT from `src_len == 0`;
  using it here would have collapsed `None` and `b""` — the exact
  conflation DECISION-02 exists to remove, reintroduced through the
  back door of a helper nobody had looked at.
- `fr_py_udf_bind` — the launcher hands over `fr_udf_call`/`fr_udf_free`
  so the shim never links libpython.

Its signature is **identical** to `fr_py_worker_plugin_loop`, with
`path`/`func_name` reinterpreted as `module`/`attr`. `spawn_wid` needed
no new parameter, and the respawn path is untouched.

**The launcher** (`forkrun_cleanroom.c`):
- `--udf-helper`, `--udf`, `--udf-attr`, `--udf-roots`.
- `setup_udf_helper()` — disposable-subprocess probe, then dlopen, then
  `fr_udf_init` **before any fork**, then bind.
- `fr_fork()` — the single fork site. All six launcher forks route
  through it, so no individual call site can forget the choreography.
- The plugin probe is skipped in UDF mode (it tests the C plugin ABI,
  which a UDF has no concept of).

### 12.2 The guard the launcher needed, and did not have before

CR-FIX1-F documents the launcher dying with **SIGSEGV** during the first
worker fork because `dlopen` runs ELF constructors and one started a
thread — which breaks the single-threaded-fork precondition that the
entire pre-fork design rests on.

So loading the helper is guarded twice: a disposable probe subprocess
first, and then, **after loading for real, the launcher reads its own
thread count from `/proc/self/status` and refuses to continue unless it
is exactly 1.** An unreadable count is treated as unsafe, not safe.

This is the one place where loading the helper could have quietly broken
the property the whole design depends on.

### 12.3 NOT yet verified — stated plainly

**The UDF path has not been run end-to-end.** The loop, the launcher
wiring and all the guards are written; the suite is green; but no run has
taken a batch through `fr_py_worker_udf_loop` and produced a result.

The blocker is not the code but the harness: invoking the launcher by
hand does not reproduce the descriptor setup `run.py` performs (result
fd flags, `pass_fds`, stats memfd), and a hand-rolled invocation failed
on the *plugin* path too — at HEAD, before any of this — which is how it
was confirmed to be a harness problem rather than a regression.

So the next step is wiring UDF mode into `run.py` and testing through
the real path, rather than continuing to fight a synthetic one.

**Parity tests (the reviewer's standing condition) are now written** --
see section 13.

### 12.4 Verified so far

* Full suite: 840 passing, 7 skipped, 1 known failure (tag v3.6.1).
* No regression in any existing mode (cleanroom 75/75).
* ABI surface 50→52 extern, 11→13 static — additive only, justified in
  `test_shim_abi.py`.
* Refusals fire and are clean: `--udf` without `--udf-helper`, an
  unloadable helper, and `--plugin` with `--udf` together.

---

## 13. Parity across the worker loops — the reviewer's standing condition

The review approved the fifth loop on this condition:

> "If the fifth loop copies the whole existing state machine, every future
> fix to poison handling, transaction completion, or acknowledgement
> ordering has another place to land. I would require parity tests for all
> shared lifecycle behavior."

**`python/tests/test_loop_parity.py`** implements it mechanically rather
than behaviourally, and that choice matters. A behavioural test has to be
re-derived per mode and can be satisfied by loops that are wrong in the
*same* way everywhere. Comparing the lifecycle **source** across modes
catches the actual failure mode: a fix applied to four loops and
forgotten in the fifth.

Mutation-checked for exactly that: changing the UDF loop's poison trap
(`claimed.num_kills` → `claimed.num_kills + 1`) while leaving the other
loops alone fails `test_every_mode_shares_one_lifecycle`. That is the
reviewer's scenario, reproduced and caught.

### 13.1 What is compared

The poison-skip branch, the zero-length sentinel branch, and the whole
`on_error` ladder — skip, fail-fast, escrow with `kills+1` and no ack.
Byte-identical across the three payload-failure modes after normalizing
the per-mode differences (invoke call, plugin-only `ensure`, argument
guard spelling, `sizeof` parens, comments).

Also asserted directly, not just implicitly: signal-`EPIPE` is fatal in
every mode, and `wincarn` is threaded through every `fr_py_worker_init`
— the latter is load-bearing, not diagnostic, because the engine
refuses to reclaim a batch whose incarnation does not match the one
passed to recovery.

### 13.2 Two real divergences, pinned rather than hidden

A parity test that quietly normalizes away a semantic difference stops
protecting anything, because the next reader cannot tell which
normalizations were cosmetic and which were load-bearing. Both
divergences therefore get their own test.

**spawn separates infrastructure failure from payload failure.**
`fr_py_exec_spawn` reports `rc < 0` for a pipe/spawn/wait/output
failure, and spawn treats it as fatal rather than feeding it to
`on_error`. That is correct: a spawn that never happened is not a
payload error, and routing it to `on_error="skip"` would silently drop
the batch. The plugin and UDF invokes have no such category. Pinned by
`test_spawn_is_the_only_mode_that_separates_infra_failure`, so a mode
gaining or losing that guard is noticed.

**splice is excluded from parity by design.** It does not invoke user
code — it moves bytes out of the ingress spool — so its retry rule is
"always", not the `on_error` ladder. The plugin loop's own comment says
so. `TestSpliceIsExcludedOnPurpose` asserts that reason still holds, so
if splice ever adopts the ladder the exclusion stops hiding a real
difference.

### 13.3 A correction I made mid-way

I initially asserted that all three modes take the same parameter types.
They do not, at the front: spawn takes `(argv, argc)` where plugin takes
`(path, func_name)` and UDF `(module, attr)`. The counts match, the
leading types do not. What actually must agree is the **transport
tail** from `ingress_fd` onward, because `spawn_wid` passes one
positional argument list to whichever loop it was handed. That is now
what the test asserts.

### 13.4 Status

The review's conditions for P1-3 are now **met**: fifth loop, pre-fork
initialisation with CPython fork hooks, structured exceptions, parent
purity, and parity tests across all shared lifecycle behaviour.

P5 remains open: `SKIPPED`/`POISONED` dispositions and the
exactly-once proof.

---

## 14. Spawn-mode exactly-once: attempted, and why it cannot discriminate

The reviewer's condition was parity tests; DECISION-02 section 7 wanted a
launcher-level exactly-once run. Both are done for the loops the
launcher serves. Spawn is not one of them, so this records what
attempting it actually showed.

### 14.1 The hook relocation (kept)

The injection hook moved from `fr_py_complete` (gated on
`signal_fd >= 0`) to each loop's **success site**. That gate was wrong:
the in-process `map()` executor runs the signal pipe **disarmed** (`-1`)
on the success path too, because there is no drain there. So the gate
fired under the launcher and never for a plain `map()` call. Placing it
structurally at the success site means one hook per loop
(`splice`, `plugin`, `udf`, `spawn`) and, as a bonus, keeps the loop
bodies textually equal — which is what the parity test exists to
preserve.

With it, `map(mode="spawn", c_spawn_loop=True)` under repeated death
really does die: batches poison, and the run still completes.

### 14.2 Why it cannot prove anything

Through `map()` the test is **not discriminating**. With the cursor fix
in place a faulted run returns 0 records; with the fix removed it also
returns 0. A test that passes either way proves nothing, and the
earlier launcher test was accepted only because it demonstrably
separated the two cases (5 records vs 0).

The reason is structural, not a tuning problem: `map()` parses the
result and returns only `DATA`. Leaked orphans are exactly the records
the in-process collect does not surface, so a leak is invisible through
this API by construction.

Making it discriminate needs a **direct driver**: fork the spawn worker
via `_fork_c_spawn_worker`, recover it in the parent, respawn, and parse
`out_fd` itself — a mini-supervisor in the test. That is a real harness,
and it would cover the spawn-specific invoke (`fr_py_exec_spawn`'s
`posix_spawnp` plus capture-memfd staging) under death, which nothing
else does today.

### 14.3 Status

* **Proven:** engine primitives under repeated death; the shared
  lifecycle (parity); end-to-end exactly-once for the plugin and UDF
  loops through a real exec'd launcher.
* **Not proven, not claimed:** an end-to-end exactly-once run for
  `spawn`. Its lifecycle is asserted identical to plugin/UDF and its
  primitives are proven; its per-batch subprocess invoke under death is
  uncovered.
* **Splice:** no end-to-end exactly-once run is proposed. It moves
  bytes rather than invoking user code, has no per-batch subprocess, and
  is excluded from parity by design.
