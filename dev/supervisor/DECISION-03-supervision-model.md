# DECISION-03 — How does the launcher serve `orchestrator=False`?

**Blocks:** P3 (the supervision-model item in coverage completion).
**Needs:** maintainer + external AI review. Consensus before implementation.
**Status:** open. No code written.

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
