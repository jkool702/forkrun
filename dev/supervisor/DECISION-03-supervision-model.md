# DECISION-03 — How does the launcher serve `orchestrator=False`?

**Blocks:** P3 (the supervision-model item in coverage completion).
**Needs:** maintainer + external AI review. Consensus before implementation.
**Status: DECIDED — GO WITH AMENDMENTS.** Option B as written is superseded:
shared lifecycle layer with **distinct worker-exit policies**, plus a hard
prerequisite on the failure/fallback contract that did not previously exist.
See §7.

> **Amendment log.** Review round 1 found (a) a concurrency claim in this
> brief that is **false**, (b) a **live defect** in the fallback contract that
> is a prerequisite for widening eligibility at all, and (c) a better
> architecture than the one recommended here. All three accepted. Details and
> evidence in §7.

---

## 1. The question

The cleanroom launcher **supervises unconditionally**. W-CR4 gave it death
pipes, `ring_recover_worker` by wid, respawn on the same wid, and trap-ACK
confirmation — there is no flag to disable any of it.

So `_cleanroom_eligible` declines `orchestrator=False`
(`run.py:698-702`), and such a call falls back to the in-process path.

**Question:** should the launcher serve `orchestrator=False`, and if so, how —
a mode flag on the existing supervisor, or a separate supervision path?

---

## 2. What the two models actually are today

Measured from the dispatch in `run.py:2809-2835`, not from the docstring.

| | `orchestrator=True` | `orchestrator=False` |
|---|---|---|
| entry point | `_execute_reactor_locked` | `_execute` / `_execute_ingest` |
| imports `_reactor.py` | yes | **no** — "never imports this module" (`_reactor.py:22`) |
| holds `_RUN_LOCK` | **yes** (`run.py:2812`, `2825`) | **no** (`run.py:2832`) |
| worker death | recover by wid, respawn; raise if unrecoverable | no recovery attempt; raise |
| raise on failure | `ForkrunWorkerFailure` via `_reactor_failure_check` (`run.py:5699`) | `ForkrunWorkerFailure` via `_raise_worker_failure` (`run.py:5731`) |

Two things follow that are easy to miss:

1. **It is already a separate code path, not a flag.** The docstring is
   explicit: `orchestrator=False` "never imports this module". So P3 is not
   about *introducing* a mode — it is about giving the launcher a second one
   matching an existing one.

2. **The models differ in more than error handling: they differ in
   concurrency.** `_RUN_LOCK` serialises forkrun calls. The reactor takes it;
   the legacy path does not. A caller running two `forkrun.map()` calls
   concurrently gets serialisation under `orchestrator=True` and none under
   `False`. **Any launcher-side mode must reproduce that difference or
   deliberately change it** — it is observable, and it is not mentioned in
   either the docstring or the decline reason.

Both paths raise the **same exception type** with the same message shape, so
the observable difference on failure is *whether recovery was attempted*,
not the exception.

---

## 3. Why declining is currently correct

`test_cleanroom.py:554` pins it end to end:

> `orchestrator=False must NOT be silently upgraded to recovery.` … a caller
> who explicitly asked for legacy fail-fast supervision would get
> worker-death **RECOVERY** instead — a different answer, not merely a slower
> one — and could not tell from the result.

The test asserts the call warns, the launcher is **not** taken, and the bytes
are still correct.

**Note for implementation:** this test encodes the decline as *correct*. P3
does not merely add a capability — it **changes an asserted behaviour**, and
that test must be rewritten deliberately rather than incidentally.

---

## 4. Options

### Option A — A mode flag on the existing supervision loop

One loop, branching on `supervise ? recover : fail_fast`.

* **For:** smallest change; shares reap, decode and teardown.
* **Against:** the two models differ in *kind*, not just degree — one
  recovers and respawns, the other never does. A single flag threaded through
  a recovery loop is exactly the shape where one missed branch silently
  upgrades a fail-fast caller to recovery, which is the precise failure
  `test_cleanroom.py:554` exists to prevent. I would not trust a test suite
  to catch that on every future edit.

### Option B — A separate supervision path in the launcher

The launcher grows a second loop that waits, and on any abnormal worker exit
tears down and fails. No `ring_recover_worker`, no respawn.

* **For:** the two models cannot be confused, because they share no loop. The
  property "fail-fast never recovers" is structural rather than a branch.
* **Against:** duplicates the reap/decode/teardown logic that both paths need.
  The duplication is the risk — CR-FIX1-B's bounded teardown is subtle and
  exists because the naive version hung.

### Option C — Keep declining, and say so

Record `orchestrator=False` as a **correct decline**.

* **For:** zero risk; honest.
* **Against:** 6.2% of valid configurations, and `orchestrator=False` is a
  documented model, not an invalid combination. Declining it is a real gap
  against the coverage goal.

### Option D — Serve it, and normalise the concurrency difference away

Take `_RUN_LOCK` for both models when the launcher is used.

* **For:** simpler contract.
* **Against:** it **changes** `orchestrator=False` behaviour for callers who
  rely on concurrent calls not serialising. Silently removing a capability is
  worse than declining the acceleration. If this is wanted it must be a
  separate, announced decision — not a side effect of P3.

---

## 5. Recommendation

**Option B — a separate supervision path — with Option A's shared teardown
extracted so the duplication is of the *loop*, not of the *cleanup*.**

Reasoning:

1. **The failure this must prevent is a single missed branch.** "Fail-fast
   silently upgraded to recovery" is undetectable from results — that is the
   whole argument in `test_cleanroom.py:554`. Structural separation is the
   only thing that makes it permanently true rather than true-until-the-next-
   edit.

2. **The duplication is smaller than it looks.** Reap, status decode and
   bounded teardown can be factored out and *shared*; what must not be shared
   is the decision to recover. So: one teardown routine, two loops, one of
   which never calls `ring_recover_worker`.

3. **Option A's cost is not code, it is assurance.** It would need a test that
   proves no future edit can route a fail-fast call into recovery. That test
   is possible but is exactly the kind of invariant this codebase has had
   trouble keeping — §3's own test exists because a previous version got it
   wrong.

4. **The `_RUN_LOCK` difference must be handled explicitly either way.** If
   the launcher path takes the lock under both models, that is Option D and
   needs its own decision. My inclination is that the parent-side lock
   behaviour should follow the **model**, not the launcher, so
   `orchestrator=False` keeps its current concurrency semantics — but that is
   a question, not something I would settle here.

---

## 6. Questions for reviewers

1. **Is Option B's duplication worth it versus Option A's assurance risk?**
   The shared-teardown factoring is the crux: can reap/decode/teardown be
   factored so the *only* difference is whether recovery is attempted?
2. **Is there a third structure** — for example, one loop parameterised by a
   *policy object* rather than a boolean, so "recover" is a capability the
   fail-fast path simply does not have?
3. **The `_RUN_LOCK` difference.** Should launcher-served
   `orchestrator=False` keep today's non-serialising behaviour (my
   inclination), or is normalising it (Option D) acceptable? I flag this
   because it is a real behavioural difference that neither the docstring nor
   the decline reason mentions.
4. **`on_error` interaction.** `on_error` is the *payload* policy
   (`retry`/`fail-fast`/`skip`) and is orthogonal to the supervision model.
   `orchestrator=False` + `on_error="retry"` must still retry a failing batch
   inside the worker without that counting as a worker death. Is that
   distinction already reliable in the legacy path, or does it need work?
5. **Should P3 be sequenced before or after P1?** It is smaller and
   self-contained, but it touches the same supervisor that P5 (NUMA) also
   touches, and the coverage plan already requires the shared
   supervision interface to be specified before both begin.

---

## 7. Amendments from review round 1

### 7.1 RETRACTED — the `_RUN_LOCK` claim was wrong

This brief asserted that `orchestrator=True` takes `_RUN_LOCK` and
`orchestrator=False` does not, making concurrency part of the difference
between the models. **That is false.** Both take it:

| | takes `_RUN_LOCK` |
|---|---|
| `_execute_reactor_locked` (dispatch site, `run.py:2825`) | yes |
| `_execute` → `_execute_locked` (`run.py:5204-5205`) | **yes — the callee locks** |
| `_execute_ingest` (`run.py:4735`) | **yes** |

The dispatch sites for the legacy path do not lock, which is what I read —
but the callee they invoke does. **The two models do not differ in
concurrency semantics**, and **Option D is withdrawn** as a live decision.

*Why it matters beyond this brief:* I asserted it from a partial read, having
checked the call site without following the call. That is the fourth instance
of this shape in this work (cf. `PyConfig`, `len == 0`, the flaky test), and
the consistent fix is to treat "I read the call site" as insufficient evidence
about a callee's behaviour.

### 7.2 ACCEPTED — and promoted to a hard prerequisite: no fallback after user code may have run

This is the serious finding, and it is **not created by P3 — it exists today**.

`_execute_cleanroom` treats a nonzero launcher exit as "accelerator
unavailable", warns, returns `None`, and the caller continues into the
in-process path. Whether that is safe is decided by:

```python
replayable  = pre_ingest or _source_is_reopenable(source)   # run.py:1057
may_fallback = replayable and not forbidden                  # run.py:1058
```

with `_CR_EXIT_PRE_INGEST = {64, 69, 71, 78}` (`run.py:812`) and
`_CR_EXIT_NO_FALLBACK = {79}` (`run.py:822`). Exit **1** ("runtime
worker/helper failure") is in **neither** set, and
`_source_is_reopenable` returns `True` for any path source (`run.py:901`).

So for a **path source** and a **runtime worker failure**:

| | value |
|---|---|
| `pre_ingest` | `False` (1 not in PRE_INGEST) |
| `_source_is_reopenable(path)` | `True` |
| `may_fallback` | **True** → the whole workload reruns in-process |

**The `or` conflates two different questions.** "Can the input be re-read?"
and "has anything already happened that must not be repeated?" are not the
same. Re-readable input makes replay *possible*; it says nothing about
**user-code side effects** that already occurred. A run that executed half
its batches and then lost a worker is restarted from batch zero.

**Evidence status — read this honestly.** The above is **code reading, not a
demonstration.** I attempted to show it empirically using the fixture's
`FORKRUN_TEST_SIDE_EFFECT_FILE` counter with `die_always_v1`, and the result
was **confounded**: the recovering supervisor's respawn multiplies execution
far more than any fallback would, so the measurement could not separate them.
I am therefore claiming the defect on the logic, which is sound, and **not**
claiming to have observed it fire. Establishing that belongs with the fix.

**Required outcome contract, and it must fail closed:**

| launcher outcome | may fall back? |
|---|---|
| confirmed decline / failure **before any worker could execute user code** | **yes** |
| failure **after execution may have begun** | **no — propagate to the caller** |
| missing or ambiguous final status after execution started | **no — fail closed** |

"After execution may have begun" is a property the launcher must *report*,
not something the parent infers from an exit code. This is a prerequisite for
**any** widening of cleanroom eligibility, not only for P3.

### 7.3 ACCEPTED — shared lifecycle, distinct policies (supersedes Option B)

Two fully independent supervision loops duplicate exactly the machinery
CR-FIX1 existed to get right. Preferred structure:

* **Shared lifecycle layer** — `waitpid`, child classification, status
  decoding, helper-death handling, live-worker tracking, bounded teardown.
* **Recovering policy** — invokes recovery for eligible deaths, classifies the
  result, respawns when allowed.
* **Fail-fast policy** — never recovers, never respawns.

The `ring_recover_worker` / `p_recover` capability lives **only** in the
recovering handler; the fail-fast handler should not even *receive* a recovery
callback, so the property is structural rather than a branch someone must not
miss. A regression test asserts recovery was never invoked under fail-fast.

Option B (two loops) remains an acceptable fallback if this separation proves
awkward — but the reap/cleanup machinery must not be duplicated merely to
separate the policy.

### 7.4 DECIDED — (b) "no recovery, immediate abort"

The maintainer's proposal was (b), on the grounds that (a) is already
covered: *"if you want 'don't retry but finish the pipeline' semantics that's
already provided by orchestrator=true and setting the max retry count to 0
... Given that is already possible, I don't see much use for option (a)."*

**The premise is verified, but it does not transfer** — and the difference
matters for how this is recorded.

*Verified:* `orchestrator=True` with `FORKRUN_RETRY_LIMIT=0` **completes the
pipeline** — measured: 20 batches poisoned and skipped, no exception raised.
So "don't retry a batch, but finish" is genuinely already available, and the
"bonus of not permanently losing workers" is real.

*Why it does not transfer:* `FORKRUN_RETRY_LIMIT` governs **batch** retries.
`respawn_cap` governs **worker** respawns. They are different knobs
(`forkrun_cleanroom.c:590`, `_reactor.py:144`). `orchestrator=False` is about
**worker death**, which retry_limit does not govern. Mapping the three
semantics:

| semantics | available today |
|---|---|
| don't retry a **batch**, finish the pipeline | `orchestrator=True` + `FORKRUN_RETRY_LIMIT=0` |
| don't respawn a dead **worker**, abort | `orchestrator=True` + `respawn_cap=0` (cap reached → no respawn → abort) |
| don't respawn a dead **worker**, but **keep going** | **nothing** |

So (a) is the one option not already provided. Recording it as "already
covered by retry=0" would be wrong reasoning that misleads later readers.

**Decision: (b).** The reasoning is not "(a) is useless" but that (a)'s
residual meaning is narrow — *"a worker died; do not re-execute its in-flight
work on a replacement, but finish the rest"* — and (b) is the safe choice for
side-effecting payloads, since aborting executes no further user code at all.
A caller wanting maximum throughput at the cost of a permanently smaller
worker pool has no option; that is an acceptable gap, and adding (a) later
is additive rather than a semantic change to (b).

**CLOSED: (a) is not being built.** The maintainer's assessment is that
"don't respawn a dead worker but keep going" has little practical use: most
of what it would do is already available via `orchestrator=True` plus
`FORKRUN_RETRY_LIMIT=0`, and the genuinely distinct part is narrow. If it is
ever wanted it must arrive as an explicit opt-in flag, never as a default,
and **it is not on the roadmap**. Recorded so the question is closed rather
than perpetually open.

### 7.4a ACCEPTED — the failure semantics must be specified, not inherited

The in-process executor records worker failures while reaping and raises
**after** its collection phase; it does not necessarily abort every remaining
worker on the first observed death.

**`orchestrator=False` must be specified as one of:**

* **"no recovery"** — dead workers are not recovered or respawned, but the run
  continues to completion and raises at the end; or
* **"no recovery, immediate abort"** — the first worker death tears the run
  down at once.

These are **observably different** for payloads with side effects, and the
launcher must not drift from whichever is chosen.

### 7.5 ACCEPTED — `on_error` stays orthogonal, and needs cross-tests

Batch-level `retry` / `skip` / `fail-fast` remains a worker/engine
responsibility. A payload failure retried inside the worker must **not**
surface as a supervisor-level worker death. A worker that actually dies must
not be transparently recovered under fail-fast.

Required matrix: **both supervision modes × all three `on_error` values ×
injected worker deaths.** Assertions must cover not just returned bytes and
exception type, but: whether recovery ran, whether fallback occurred, and
**whether already-executed user code ran a second time**. An intentional
engine abort from `on_error="fail-fast"` must not be misclassified as a worker
crash.

### 7.6 ACCEPTED — sequencing

The shared supervision contract and the execution-outcome contract (§7.2) must
be specified **before** P1 or P3 implementation, as the coverage plan already
requires. P3 settles before P5 reuses the interface. P1's packaging and
initialisation probes may proceed independently, but **P1's launcher
integration must not assume supervision is unconditionally recovery-based.**

---

## 8. Revised recommendation

1. **Fix the failure/fallback contract first** (§7.2). It gates all eligibility
   widening, and it is a live defect independent of P3.
2. **Then P3** as a fail-fast *policy* over the shared lifecycle layer (§7.3),
   with the "no recovery" vs "immediate abort" question answered explicitly
   (§7.4).
3. **Do not** re-introduce a concurrency difference — there isn't one (§7.1).
4. Sequence P1's launcher integration after both, and keep P1 and P3 in
   separate reviewable changes (§7.6).

**Until (1) lands, retain the correct decline.** Enabling fail-fast while a
nonzero exit can still trigger a blind in-process replay would trade a
correct refusal for a silent one.
