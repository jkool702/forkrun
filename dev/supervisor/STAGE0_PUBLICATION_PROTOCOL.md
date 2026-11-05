# Stage 0 — publication/commit protocol design note

**Status: IMPLEMENTED.** As-built state in §9; the interim-policy
decision in §4 is resolved on evidence in §9.3.

Companion to `CLEANROOM_EXPANSION_PROPOSAL.md` §0a. That section records
the defect; this note is the design work the review asked for before any
code was written.

Evidence: commit **`0341c9b4`**, reproduced by
`python/tests/test_data_publication_leak.py` (marked
`@unittest.expectedFailure` — it flips to unexpected success when fixed).

---

## 1. The defect, precisely

Four operations currently happen with no ordering guarantee between
them:

| # | operation | where | durable? |
|---|---|---|---|
| W | write record to output memfd | `fr_py_emit_record_buf` | yes, in memfd |
| S | signal the drain | `fr_py_emit` | no, pipe |
| A | acknowledge / commit the transaction | `fr_py_ack_direct` | yes |
| F | forward the record downstream | `fr_py_drain_loop` | yes, **irreversible** |

The drain acts on **S alone**. It never consults A, and its per-worker
cursor `offsets[wid]` lives in the drain process where recovery — which
owns the memfd — cannot reach it.

So for any record where the order is `W → S → F → death → rollback`, the
published record belongs to an attempt the engine discarded. Recovery
truncates the memfd to `output_start` and retries; the retry's record is
either suppressed by the stale cursor (smaller record) or silently
overwrites nothing downstream (equal-size record, different content).

Observed: poisoned batches returning `DATA`, `rc=0`.

### 1.1 Why "signal after ack" is not the fix

It inverts the defect rather than removing it. The new window is
`W → A → death → S`: the batch is **committed** but its record was never
signalled, so the drain never forwards it and **the result is silently
lost**. A committed batch must be visible; trading a wrong-result bug for
a missing-result bug is not a fix.

This is why the acceptance criteria need both properties, and why
neither candidate in §3 satisfies them on its own.

---

## 2. Invariants

**S1 — Safety.** No record from an uncommitted attempt is ever visible
through the public API, in any executor.

**S2 — Completeness.** *A run that reports successful completion
delivers every committed record exactly once.* An **aborted** run must
never report success and must never re-execute already-committed work; a
streaming run may already have yielded earlier committed results before a
subsequent fatal error. S2 does not require an aborted or abandoned
consumer to receive everything committed — it requires that failure never
masquerade as success.

**S3 — Consistency.** The record a consumer observes for batch *k* is
the record belonging to the attempt the engine committed for batch *k*.
A poison count and a published `DATA` record for the same batch is a
violation, not a cosmetic disagreement.

**S4 — Non-regression.** A batch that succeeds normally is unaffected;
the common path must not gain a round trip.

S1–S3 are what `test_data_publication_leak.py` currently fails.

---

## 3. Protocol evaluation (review amendment 2)

The review supplied a concrete direction — **write → commit → signal** —
and asked whether it works engine-free. Worked against the source:

### 3.1 The commit linearization point exists and is already durable

**Linearization point: the `TXN_IDLE` release-store inside
`worker_txn_clear()` (`forkrun_ring.c:6504`) — not the successful return
from `fr_py_ack_direct()`.**

That distinction is load-bearing and was previously stated wrong here: a
worker can die *after* the release store but *before* returning to its
caller. That batch is committed and recovery must treat it as such.
Defining the point by the call's return would misclassify exactly the
case the protocol exists to handle.

The ring's ack path:

```
worker_txn_begin_commit()   → TXN_COMMITTING   (before any ack side effect)
  ... fallow/order packets written to their pipes ...
worker_last_cnt = 0
worker_txn_clear()          → TXN_IDLE         ← COMMIT POINT (release store)
return EXECUTION_SUCCESS                       (may never execute)
```

Every ack side effect is already on its pipe at the store. This requires
**no engine change** — it is an existing, already-ordered transition the
shim can observe. `g_state` is `MAP_SHARED` (`forkrun_ring.c:2513`), so
the parent and the drain can read `g_state->worker_txn[wid].state`.

### 3.2 But "signal after ack" alone is NOT sufficient

The drain is **size-driven, not signal-driven**. On any wakeup it does
`fstat` and forwards everything from its cursor to the memfd's **current
size** (`_shim.c:2439`, `size <= offset` is the only bound).

So reordering the signal alone does **not** close the hole: the record
is written *before* the ack, so between write and ack it sits in the
memfd, and **any** queued or stale signal for that worker publishes it —
uncommitted. Moving the signal later narrows the window without closing
it.

### 3.3 The design that does close it: carry the committed frontier

**Signal payload becomes `(wid, committed_offset)` instead of
`(wid, batch_idx)`.** Same 16 bytes, same pipe, no wire growth.

* Worker: write record → `fr_py_ack_direct` → on success, signal
  `(wid, worker_output_end)`, the post-commit frontier.
* Drain: forward `[offsets[wid], committed_offset)` and set
  `offsets[wid] = committed_offset`. **Never reads past a committed
  boundary**, so no wakeup can publish uncommitted bytes.
* One signal per committed batch on the common path — no added round
  trip (S4 preserved).

This is the piece the reviewer's sketch was missing, and it is why the
direction is worth taking rather than deferring again.

### 3.4 Recovery: the IDLE ambiguity is benign

The review asked how recovery distinguishes committed-but-unsignalled
from uncommitted. Source answer: **it cannot, and it does not need to.**

`ring_recover_worker_core` branches on `state`:

| state at death | meaning | action |
|---|---|---|
| `TXN_CLAIMING` | claim in flight; ticket unattributable | **ambiguous — conservative/fatal. Never synthesize a successful publication wakeup.** |
| `TXN_CLAIMED` | batch published, not committed | roll back output to `output_start`; **never wake the drain** |
| `TXN_COMMITTING` | ack in flight, ambiguous | conservative abort (existing behaviour); **never wake the drain** |
| `TXN_IDLE` | committed **or** nothing in flight | drain wakeup is **safe in both cases** |

The `IDLE` case conflates two situations, but **every byte in the memfd
is committed whenever no `CLAIMED`/`COMMITTING` transaction owns it**, so
forwarding to size at `IDLE` cannot publish anything uncommitted. That
benign ambiguity is what makes the recovery path sound without new ring
state.

Answering the reviewer's other audit points:

* **Synthetic wakeup vs queued signals / advanced cursor** — the drain
  already tolerates empty wakeups (`size <= offset → continue`), and
  ordering is preserved because all records carry `batch_idx` and the
  consumer sorts. An out-of-order record is held by `ReassemblyBuffer`,
  never yielded early.
* **Commit succeeds, signal write fails** — state is `IDLE`, so recovery
  takes the "nothing in flight" branch and **does not retry**. The batch
  is committed exactly once. An EPIPE means the parent abandoned the
  stream, already fatal.
* **Respawn / memfd reuse — the cursor is PERSISTENT, not
  generation-reset.** Revision 2 of this note wrongly proposed using
  `WorkerTxn.incarnation` to detect a fresh memfd and reset the cursor.
  **That was incorrect**, and the source says so: `out_fds[i]` is created
  **once** at `forkrun_cleanroom.c:1245` and the *same* fd is passed to
  `spawn_wid()` on every respawn (`:1621`); the drain inherited those same
  descriptors when it was forked. The memfd is **reused across worker
  generations**, so there is no fresh-memfd handoff to detect, and
  resetting the cursor to zero would re-read already-consumed,
  hole-punched records.

  Correct model: a **persistent, monotonically advancing per-worker byte
  cursor** for the lifetime of the reused memfd, with absolute committed
  offsets. A respawned worker appends at the memfd's current end
  (`worker_txn_init_output_cursor` is the only cursor lseek), which is
  exactly the committed frontier, so both sides agree.

  This is sound because of an invariant verified in the source:
  `worker_output_end` advances **only after a complete emit**
  (`forkrun_ring.c:1320`), `txn.output_start` snapshots it at claim
  (`:6461`), and rollback truncates to precisely that value (`:7163`).
  **Rollback therefore never truncates past the committed frontier** —
  which is the precondition the persistent cursor depends on. It should
  be asserted by a test rather than left as a comment.
* **EOF / teardown / abandonment** — a wakeup after drain EOF must not
  resurrect it; wakeups are issued only from the supervise loop while
  the drain is live.

### 3.5 Synthetic wakeup — required in EVERY supervisor path

**Revision 2 of this note treated the IDLE wakeup as if it followed from
the recovery state machine. It does not. The supervisor never sends it.**

Verified: `forkrun_cleanroom.c:1578-1582` calls `p_recover(...)` and then
executes `if (rc == 2) continue;` — and `2` is `NORMAL_EXIT`, returned
when the work has drained. **No synthetic notification is sent on that
path, or on any path.**

That is precisely the completeness case the protocol must close: a worker
commits its final record, dies before signalling, recovery sees an idle /
drained worker, and the supervisor concludes there is nothing to do. The
record stays in the memfd and the drain may never learn it should forward
it.

Required control flow in the supervisor:

1. Observe the worker's death.
2. Run recovery and let any rollback finish.
3. **Capture the stable committed frontier *after* recovery completes.**
4. Issue a synthetic `(wid, committed_offset)` wakeup for every nonfatal
   outcome where that frontier is well-defined — **before** any early
   `continue` that bypasses recovery handling, and **including `rc == 2`**.
5. **Never** synthesize successful publication for ambiguous or fatal
   outcomes (`COMMITTING`, or `rc` in the fatal set).

A normal-exit classification must not silently strand a
committed-but-unsignalled record.

### 3.6 Post-commit notification failure must not re-execute

Verified hazard: every loop treats a nonzero `fr_py_complete` as
`return 1` (`_shim.c:3506`) — the worker exits, supervision recovers, and
the batch is retried. After reordering, a **signal-write failure occurs
post-commit**, so routing it through that generic path would
**re-execute an already-committed batch**. That is a new exactly-once
violation introduced by the fix itself.

Required: a **distinct outcome** for *committed but notification failed*,
distinct from pre-commit execution failure, audited across every
`fr_py_complete()` caller and all eight disposition-emission paths. Its
only permitted responses, following the **actual state-dependent**
recovery behavior — `ring_recover_worker_core` classifies `TXN_IDLE`
differently from `TXN_CLAIMED`, so a nonzero worker exit must not be
assumed to re-execute the same batch:

* trigger recovery notification, where the state shows the batch committed
  and the notification is safely recoverable; or
* abort the run **without claiming successful completion**.

The required outcome is unambiguous regardless of which path the engine
takes: **no duplicate execution of committed work, no false success, and
either successful notification recovery or a fatal run result.** An
abandoned consumer or unrecoverable notification failure must never
become a retry of committed work.

### 3.7 Every emitter that must conform

The review's point that `fr_py_emit_disposition` signals independently is
correct — reordering only `fr_py_complete` would leave dispositions
racing. Full audit of the current signal sites:

| emitter | site | conforms? |
|---|---|---|
| `fr_py_emit` (payload) | `_shim.c:1570`, signals at 1645 | move signal after commit; distinguish post-commit failure |
| `fr_py_emit_disposition` | `_shim.c:801`, signals at 825 | **same**, plus no-retry outcome |
| disposition call sites | `_shim.c:1715, 3244, 3302, 3500, 3554, 3672, 3731` | **must be rewritten — see below** |

#### 3.7.1 The disposition sequence must be changed at every call site

This is **not** inherited. Verified: the disposition sites emit and then
call `fr_py_complete(-1, ...)`, and `fr_py_emit` returns immediately when
`signal_fd < 0` (`_shim.c:1644`) — so the acknowledgement is silent. If
`fr_py_emit_disposition` stops signalling and these calls are left alone,
**POISONED and SKIPPED records are committed but never notified to the
drain**: committed, invisible, silently stranding any consumer waiting on
that batch's terminal outcome.

Every disposition path must therefore be rewritten to:

1. write the complete terminal record into the output memfd, **without
   signalling**;
2. complete the acknowledgement and **reach the commit point**
   (`TXN_IDLE`);
3. send the post-commit notification carrying the committed frontier.

Concretely: route each disposition path through the revised completion
helper **with the real signal descriptor** (which guarantees
write → commit → signal), or call a dedicated post-commit notifier after
acknowledgement. All eight call sites are audited individually; a shared
helper is preferred so a new loop cannot silently reintroduce the
silent-ack pattern.

Tests must prove every committed `POISONED`/`SKIPPED` record remains
observable **exactly once**, and that a death between writing the
disposition and its acknowledgement rolls the record back and retries or
aborts per existing policy.

### 3.8 Engine-free

Every change is in `_shim.c` (emit ordering, signal payload, post-commit
outcome), `forkrun_cleanroom.c` (recovery wakeup in all paths,
frontier capture), and the drain loop. `forkrun_ring.c` is **read but
never modified** — the existing `TXN_IDLE` transition, `output_start`
snapshot and cursor semantics are sufficient. The frozen-engine exemption
is not invoked.

### 3.9 Status

Core direction accepted by review. Recovery wakeup lifecycle (§3.5),
cursor model (§3.4) and the post-commit outcome (§3.6) are now specified
concretely rather than assumed. **Still returns for approval before
implementation.**

## 4. Interim safety policy (review amendment 1)

**Revision 2 — the original Option A was insufficient and is corrected
below.**

The flaw: `stream()` may already have yielded the abandoned attempt's
`DATA` when recovery later detects the conflict. **An exception after a
yield cannot retract a value the application has already observed.** So
post-hoc detection satisfies S1 for materialized results and fails
completely for streaming. Calling that "fail closed" was wrong.

Policy is therefore **per API**:

| API | interim policy |
|---|---|
| materialized `map()` | **fail on any worker death that is recovered and retried** — not merely on a detected contradiction |
| `stream()` | **the cleanroom streaming envelope is disabled** until a commit barrier exists |

**Revision 3 corrects the `map()` guard.** The earlier policy proposed
failing only when a poisoned batch also produced `DATA`. That is **not a
comprehensive detector**: a retry can *succeed* without ever incrementing
the poison count, leaving the abandoned attempt's record visible with no
contradiction to detect. A partial detector is worse than none, because
it looks like a safety measure.

The only sound narrow policy without the commit barrier is to refuse the
materialized result whenever a recovered worker death occurred in that
run. This is viable for `map()` specifically because the collection is
returned only after the run completes, so the whole result can still be
refused — unlike `stream()`, which has already handed values to the
caller.

If that proves too blunt in practice, the alternative is to **disable the
recovery-enabled cleanroom `map()` envelope** — not to narrow the
detector.

Disabling is preferred over post-hoc failure for streaming precisely
because the failure is detected too late to be a safety measure; a loud
error after a wrong value has been handed to the caller is an
availability problem, not a safety one.

**The fallback is no longer "document and accept".** The review is right
that leaving a confirmed wrong-result path available in a shipped
executor is the wrong default. If containment turns out to exceed a
contained change, the decision is to **disable the affected envelope**,
not to accept the risk.

Note the disable applies to the **streaming envelope specifically**. The
materialized `map()` path keeps working with the guard, since a
collection is returned atomically and can still be refused.

---

## 5. Determinism of the regression test

The reviewer is right that `FORKRUN_TEST_DIE_AFTER_SIGNAL` alone does not
prove the drain forwarded before the kill — the signal can be written and
the worker killed first. The current test mitigates this with a sleep,
which is **scheduling-dependent, not deterministic**.

Required: an explicit handshake.

1. Worker emits and signals a nonempty `DATA` record.
2. **The drain confirms it has copied that record downstream and
   advanced its cursor** — a real back-channel, e.g. the drain writes a
   per-`(wid, batch_idx)` ack on a dedicated pipe, or publishes a
   cursor the test polls.
3. Only then may the worker be killed, before acknowledgement.
4. Recovery retries; the batch poisons.
5. Assertions run **through the public API** — for streaming, over the
   values actually yielded by `stream()`, not over an internal results
   descriptor. A record sitting in an internal buffer the consumer never
   sees is not a violation, and one it sees is.

The sleep-based version stays as a cheap broad test; the handshake
version becomes the authoritative regression gate.

### 5.1 Required test matrix

Both safety and completeness, at each cut point: record write, signal,
ack, commit-state publication, notification recovery.

| case | expects |
|---|---|
| death before signal | nothing visible for that batch; retry delivers once |
| death after signal, **before** forward | nothing visible; retry delivers once |
| death after forward, before ack | **no stale record visible** (S1/S3) — currently fails |
| death after ack, before notification | **committed record not lost** (S2) |
| retry with **same size, different content** | committed content visible, not attempt 1's |
| retry with **different size** | committed record visible, no framing corruption |
| repeated recovery | no duplicate delivery |

The same-size/different-content row is called out by the reviewer and is
currently unmeasured; the mechanism predicts stale content survives.

### 5.2 Required failure-cut matrix

Each row states the expected outcome on all four axes the review asked
for. "Public API" means what `stream()`/`map()` hands the caller.

| # | cut point | safety | completeness | public API | run status |
|---|---|---|---|---|---|
| 1 | death during record write (partial) | no partial record | retried | nothing yielded | ok |
| 2 | death after full write, before ack | not published | retried | nothing yielded | ok |
| 3 | death after `TXN_IDLE` store, before signal | n/a | synthetic wakeup incl. `rc == 2` (§3.5) | value yielded once | ok |
| 3b | same, input queue already drained | n/a | `rc == 2` must still wake | value yielded once | ok |
| 4 | death during ack (`COMMITTING`) | not published | conservative abort | nothing yielded | per policy |
| 5 | signal write fails after commit | n/a | **no retry** (§3.6 distinct outcome) | — | recovery-notify or abort |
| 6 | rollback truncates memfd under drain | not published | retried | nothing yielded | ok |
| 7 | same-size retry, different content | not published | committed content wins | committed content once | ok |
| 8 | different-size retry | not published | committed record wins | committed record once | ok |
| 9 | repeated recovery | not published | delivered once | exactly once | ok |
| 10 | **respawn reuses `wid` *and its memfd*** | n/a | absolute cursor retained; append at committed frontier | never reset or replay consumed bytes | ok |

Rows 7–9 are the cases the current source is predicted to fail, and which
`test_data_publication_leak.py` already exposes on row 7/8.

The handshake in §5 is **required** for rows 3 and 6 — both are "the
drain must have forwarded before the worker dies" scenarios.

---

## 6. Reproducibility

The pinned base `c72d27c6` predates all Stage 0 artifacts. Exact trees:

* **defect base `c72d27c6`** — the commit the bug is reported against,
  and the last commit without the Stage 0 hooks.
* **evidence `0341c9b4`** — `fr_py_maybe_die_after_signal`, both
  publication-race tests, regenerated shim artifacts, ABI pin 53/16.
* **this note `2f616450`** — first design revision.
* **design revision 2** — the commit adding this section (protocol
  evaluation, interim-policy correction, failure-cut matrix).

**All are now pushed to `origin/NEW/REFACTOR4.2`.** The previous review
could not resolve `0341c9b4` because it was unpushed at the time; that is
fixed, and the SHAs above are directly fetchable.

Reproduce:

```
make -f Makefile.substrate python-substrate
cd python/tests
python3 -m unittest test_data_publication_leak   # 1 expected failure
python3 -m unittest test_drain_publication_race  # passes
```

---

## 7. Strengthened acceptance gate (review amendment 3)

**S4 is demoted from invariant to performance objective.** It should be
preserved where practical, but it must not veto a necessary
synchronisation step if no equally safe alternative exists.

**S1–S3 remain correctness requirements.** Stages may be researched in
isolated branches in parallel, but nothing may be **integrated or
activated** on the current publication protocol.

## 8. Scope guard

* The ring engine stays frozen unless a source-backed demonstration
  shows no engine-free correction exists.
* Stage 0 does not redesign the drain, only its **publication
  boundary**.
* Research for stages 1/3/4 may proceed in isolated branches; nothing
  may be **integrated or activated** on the current publication
  protocol.
---

## 8a. Stage 1 — terminal-aware reassembly (as-built)

Stage 1 makes ordered reassembly aware of every batch's TERMINAL outcome
rather than only the ones that produced a payload. **It changes no
eligibility decision**: `stream(order="index")` remains declined, and
Stage 0's publication protocol is still its precondition. A test asserts
the decline is still present so a future change cannot quietly enable it.

What landed:

* `ReassemblyBuffer.add_disposition(batch_idx, disposition, payload)` —
  all four dispositions advance the contiguous prefix; only `DATA`
  yields. `NO_RESULT` / `SKIPPED` / `POISONED` are retained distinctly,
  not collapsed, because poison accounting and the skip distinction are
  exactly what a consumer needs.
* `drain()` now walks terminal markers as well as payloads, so a
  terminal batch no longer strands everything behind it — and does so
  **promptly**, not at finalisation.
* `unresolved_gaps(upto)` — for protocols that emit an authoritative
  terminal record per batch, an uncovered index is a completeness
  failure rather than something `final_drain()` should sort over.
* `run._split_records_terminal()` — a **separate** parser.
  `_split_records()` is deliberately left filtering control records: its
  callers must not receive a spurious `b""` for a batch that produced
  nothing, and a test pins that so "unifying" the two breaks loudly.

### Producer coverage is not uniform, and that is recorded

The gap check is only meaningful where a producer actually emits terminal
records:

| producer | terminal dispositions |
|---|---|
| plugin / udf / spawn loops | `SKIPPED`, `POISONED` |
| splice loop | `POISONED` (no `on_error=skip` arm) |

`splice`'s DATA disposition is set explicitly inline, so it appears in
the loop body too. The contract is asserted **against the source**, not
against this table — two earlier audits were wrong precisely because a
hand-written enumeration was trusted.

`test_stage1_reassembly.py` (16 tests) pins buffer semantics, the
`b""`-is-DATA distinction, never-yielding-out-of-order, prompt
advancement, gap detection, parser separation, the producer contract,
and that the ordered-streaming decline is intact.

---

## 8b. Stage 3 — spawn in the launcher (plumbing landed, envelope still declined)

Stage 3's integration is in place. **The spawn envelope remains
declined**, because activation is gated on lifecycle tests that do not
exist yet, and activating before them is exactly the mistake this plan
keeps warning about.

**Mode-specific worker descriptor.** `fr_py_worker_spawn_loop` takes
`(wid, char **argv, int argc, …)`; plugin and UDF take
`(wid, const char *, const char *, …)`. Same arity, incompatible types at
positions 2–3. The launcher previously carried one callback type, so
serving spawn through it meant a cast that would pass a `char**` and an
`int` where two `const char*` are expected. It now carries a
`worker_desc` naming the mode and that mode's own arguments, and
`fr_run_worker()` dispatches through each loop's real prototype. `spawn`
is resolved as `fn_worker_spawn_loop`, never as the plugin callback.

**Command transport.** Arguments stay distinct argv elements — no
shell-word parsing, and no newline-delimited encoding, since a newline
is a legal character inside a single argument. NUL is rejected in
`run.py`, at the point user input becomes an argv element, before the
launcher starts and before the source is read. It *cannot* be rejected in
C: a C string is NUL-terminated by definition, so an embedded NUL would
have been truncated before the launcher saw it. Re-checking it in C would
be theatre, and the code says so.

**Process ownership (Option A).** Workers `setpgid(0, 0)`, so pgid ==
worker pid and `kill_worker_group()` can signal a whole worker
generation's descendants. Applied only to worker slots: the spill,
scanner, fallow and drain children are not group leaders, so signalling
`-pid` for one would target whatever unrelated group carries that id.
That is why it is a separate function rather than a flag on
`kill_slot()`.

The documented boundary — descendants that `setsid()` away are **outside**
the guarantee — is stated in the code but **not yet tested**, which is
the main reason the envelope stays declined.

### Lifecycle: the first diagnosis was wrong

The gate initially failed and I concluded the launcher "never notices the
worker's death" — that no respawn occurred at all. **That was wrong**, and
the reviewer is what corrected it.

The supervisor's `waitpid(-1, &st, 0)` does observe the death. The group
signal was a silent **no-op**: the supervision loop set `pids[wid] = -1`
the moment it reaped the worker, *before* calling
`kill_worker_group(&pids[wid])`, and the helper took the slot **pointer**
and refused to act on a non-positive value. Both the fail-fast and
recovery branches were affected.

Fixed by taking the pid **by value**, which makes the ordering mistake
impossible rather than merely unlikely, plus a regression test that
asserts no call site passes a slot pointer. The lifecycle test then
passed as an *unexpected success* of its `expectedFailure` marker.

Worth keeping in the record because the wrong conclusion was the
plausible one: "the child survived" reads like "the supervisor never
noticed", and acting on it would have meant redesigning supervision that
was working.

### Stage 1 is now wired to production

The first delivery was scaffolding: `add_disposition`,
`_split_records_terminal` and `unresolved_gaps` had **no production
callers**, so control records were still discarded before the buffer saw
them and a `SKIPPED`/`POISONED`/`NO_RESULT` batch still read as a hole
until `final_drain()`. The completion claim was not supported.

All seven ordered drain sites now use `_drain_worker_memfd_terminal()` and
`add_disposition()`. The DATA-only helpers remain for callers that must
not see control records at all.

`unresolved_gaps()` stays **diagnostic-only**, and the reason is a real
producer asymmetry the reviewer surfaced: ordinary Python-mode payloads
pass `data=NULL` to `fr_py_emit()`, which writes **no record at all** for
a `None` result. So a `None` batch is a genuine hole, not a marker that
can be skipped, and enforcing the gap check unconditionally would report
false completeness failures. An earlier comment here claimed the C
emitter supplies a `NO_RESULT` record for that case; it does not, and the
comment is corrected.

### What the lifecycle tests found (superseded)

The original finding, retained for the record:

Spawn now runs end-to-end through the launcher, and two of the three
gates hold:

* the **escaping-descendant boundary** passes — a child that `setsid()`s
  away survives, exactly as Option A promises, so the limit is pinned
  rather than implied;
* the **mode is genuinely served** (a sanity test, so the others cannot
  pass on a path that never ran).

The third fails, and the cause is **larger than the process group**:

> Killing a worker that is blocked mid-batch produces **no respawn at
> all** across a 5-second observation window. The launcher never reaches
> the code that would signal the group, because its supervision loop does
> not appear to cover a worker that is still executing when it dies.

So the orphan is not reachable until *something notices the death* — and
nothing does. Group-kill has been wired into both the supervision path
and the fail-fast path, but neither is entered. That test is marked
`expectedFailure` so it flips to unexpected success when fixed.

This is why the envelope stays declined, and it is a bigger finding than
the item-4 risk the design anticipated: the design worried about a
SIGKILLed worker orphaning a child, and the real gap is that such a
worker may not be observed as having died at all.

Still owed before activation: in-group descendant cleanup on worker
death (blocked above), cleanup after recovery/respawn and at launcher
teardown, the infrastructure-vs-command failure distinction, and parity
against the in-process spawn loop.

### Two mistakes worth recording

Both were mine, both were caught by tests within minutes, and both are
the kind a passing suite would have hidden:

* A local `spawn_argv = None` in `map()` **shadowed** the new parameter
  of the same name, so every cleanroom call raised `UnboundLocalError`.
  Renamed the local to `c_spawn_argv`. The follow-on mistake was worse:
  a blind `sed` rename left `if spawn_argv is None:` pointing at a name
  that no longer existed, and — because the suite was already red — the
  real signal got lost among 34 unrelated-looking errors.
* `from forkrun import run` yields the exported **function**, not the
  module. Attribute lookups then fail with a confusing
  `AttributeError`. Needed `importlib.import_module("forkrun.run")`.

Practical note: I ran the suite with `timeout 3000`, which is fifty
minutes. A deadlock would have sat there looking like progress. The
suite takes ~230s, so anything past a few minutes is a real stall — use
a few hundred seconds, and bisect per file when it wedges.

---

## 8c. Stage 4 — splice measurement: GO

`tools/bench_splice.py`. Median of 3 trials, peak parent RSS
(`ru_maxrss`, not current RSS — current understates a peak, and the
high-water mark never decreases, so every variant runs in a fresh
process). Only representable, byte-moving paths are compared: the C
splice loop, and `spawn cat` / `spawn tr` through the launcher. A
python-mode lambda is deliberately **not** a baseline — it is not
exec-representable, so it poisons every batch and times a failure.

**Every trial validates its own output** and the harness discards the
whole configuration if any trial fails or returns nothing. A median over
the trials that happened to succeed is exactly the shape of a benchmark
that flatters the thing being measured.

| input | workers | splice+c_drain | splice+py_drain | spawn cat | ratio |
|---|---|---|---|---|---|
| 2.6 MB | 1 | 0.0137s | 0.0119s | 0.0650s | **4.7x / 5.5x** |
| 2.6 MB | 4 | 0.0289s | 0.0270s | 0.0650s | **2.2x / 2.4x** |
| 26.5 MB | 1 | 0.0596s | 0.0564s | 0.5801s | **9.7x / 10.3x** |
| 26.5 MB | 4 | 0.0558s | 0.0469s | 0.1841s | **3.3x / 3.9x** |

**Peak parent RSS is essentially flat across all variants** — the
26.5 MB run peaks around 94–95 MB whichever path moves the bytes, so the
gain is throughput, not memory.

Two findings worth stating plainly:

* **The advantage is largest exactly where it matters least**: ~10x on
  the biggest, single-worker case. But that case is also the slowest
  absolute (0.58s for a plain byte copy), so the user-visible saving is
  ~0.5s. Where a real call would actually wait — a command doing work,
  not `cat` — the margin is unknown.
* **`spawn tr` is ~1.00x of `spawn cat`** at every size, i.e. the
  transform is free next to the copy. So the dominant cost is *moving
  bytes across the process boundary at all*, not the work done on them.
  That is precisely the cost splice removes, and it is why the ratio is
  so large.

**Recommendation: retain the C splice loop, and do NOT wire it into the
launcher — as a scope and maintenance decision, not as a measured
rejection.**

**Framing corrected (round-8 review).** An earlier version of this
section presented the recommendation as though the measurement had
tested launcher-splice and found it wanting. It did not. What was
measured is that a direct byte-moving path beats invoking a no-op
command (`spawn cat`) by ~10x. That establishes the value of the
in-process splice loop. It says nothing about a launcher-splice
integration, because that integration does not exist and was never
benchmarked.

So the decision rests on two things the measurement does support:

1. The loop is worth keeping — decisively, and it is already available.
2. Building a third launcher mode would add mode-specific dispatch and
   supervision work to capture a path with no identified user. That is a
   complexity argument, and complexity arguments are what scope
   decisions are made of.

**If launcher-splice is ever wanted, it must be prototyped and measured
against `spawn cat` under the workload that motivates it.** Recommending
it against a number that measured something else is how the earlier
version of this section overreached.

The win is also specific: it is against a no-op command. For a command
that does real work, the user-visible benefit is unknown and this
measurement cannot bound it.

Caveat, stated because it bounds the result: this compares in-process
splice against launcher-spawn. It does **not** compare against a
launcher-splice integration, which does not exist. If that is built
later, it must be measured against `spawn cat` before retention.

### What the integrity check changed (round 8)

The first corrected version validated output as a byte-value HISTOGRAM,
`sorted(got) == sorted(want)`. That is not an integrity check: it
survives a full reversal of the output, so a batch assembled backwards
passes it.

The check is now **record tiling** — every emitted record must be a
contiguous slice of the expected output, and those slices must cover
`[0, len(want))` exactly once, in whatever order they arrived. That
rejects a reversed batch, a dropped batch and a duplicated batch, while
still asserting nothing about arrival order, which `order="none"` does
not promise.

Stronger still, a byte-exact **ordered validation run** (`order="index"`)
executes before any timing is taken and aborts the benchmark if the
pipeline is not correct. So the strong claim lives in the ordered run
and the order-appropriate weaker form is confined to the unordered timed
runs.

**What tiling does NOT prove, stated because it is easy to over-read:**
empty records are ignored, so this is **byte-stream integrity** — every
input byte delivered exactly once, none invented, none reordered within
a record. It is **not** an exact emitted-record count and **not**
batch-level exactly-once evidence. For the operations measured here
(`splice`, `cat`, `tr` — all one-to-one byte maps) that is precisely the
right invariant; a deduplicating or overlapping workload would need a
different oracle rather than a weakened one.

### What the corrected measurement changed

The first version of this benchmark was not measuring what its labels
claimed, and the table above was rebuilt rather than adjusted:

* **The spawn rows were not launcher-spawn at all.** `mode="spawn"` did
  not route through the launcher, so the comparison was in-process splice
  against ordinary in-process spawn. The harness now sets
  `FORKRUN_CLEANROOM=1` explicitly, and the spawn rows are measured
  against the real launcher. The ratios came down slightly because the
  baseline got slower, which is the correct direction: the earlier
  numbers flattered splice by understating the thing it beat.
* **Timing runs that produced no output.** Output is now validated on
  every trial as a **byte multiset**. Concatenated bytes are the wrong
  invariant (with `order="none"` and >1 worker batches complete out of
  order by design) and so is line splitting (splice moves bytes, and a
  32768-byte batch does not align to line boundaries — it reported
  500001 lines where the input has 500000). The multiset asks only what
  this benchmark should care about: every byte arrived, none invented.
  Ordering is a separate promise covered by the `order="index"` suites
  and is **not** claimed here.

### Second benchmarking mistake worth recording

Finding the first one (below) led to a second, which is the more useful
of the pair. Validating output exposed a **real product bug**: the public
`map()` spawn path raised `AttributeError` inside the plugin-spec parse
(`raw_payload.rpartition(":")`) because a spawn payload is an ARGV LIST.
The plugin and udf modes carry a `"path:function"` spec; spawn does not.
The parse now runs only for the modes that have one. That bug would have
been invisible to a harness that only counted records — and it was
present while the matrix and the spawn tests were already green, which
is the clearest argument in this whole document for checking bytes
rather than counts.

The mutated-guard test makes the same argument in miniature. A first
version tried to demonstrate the 2% matrix ceiling by monkeypatching
`_cleanroom_eligible`; the patch silently did not take, so the test
"passed" while measuring the UNMUTATED matrix. It is now a direct
assertion of the arithmetic, with the failure mode recorded, because a
test that cannot fail is worse than no test.

### A benchmarking mistake worth recording

The first run passed only `tr` to the spawn path, omitting `a-z A-Z`.
Spawn transports arguments as distinct argv elements, so it faithfully ran
a different, failing command — and the harness reported poison
summaries while still printing timings. Comparing timings of FAILED runs
is the exact shape of a measurement that looks fine and means nothing.
Every row above now asserts the delivered record count.

---

## 9. As-built

Implementation: **`06235e11`** and the follow-up test commits on
`origin/NEW/REFACTOR4.2`.

### 9.1 What landed

| item | status |
|---|---|
| signal payload → `(wid, committed_offset)` | done, 16 bytes unchanged |
| `fr_py_emit` / `fr_py_emit_disposition` no longer signal | done |
| `fr_py_complete` orders write → commit → notify | done |
| drain forwards `[cursor, committed_offset)` | done |
| all seven disposition call sites commit *and* notify | done — see below |
| zero-length sentinel stays ack-silent | done — it writes no record |
| `FR_PY_ERR_NOTIFY` (-4), distinct from pre-commit codes | done, exported |
| synthetic recovery wakeup, `rc` 0/1/2 only | done, before any early `continue` |
| failed synthetic wakeup fails the run closed | done, returns status and aborts |
| persistent cursor, no respawn reset | done (no code needed — it was already correct) |

**Two emitters beyond the design's list.** The `fr_py_emit` /
`fr_py_emit_disposition` audit was incomplete in practice:

* **Splice** hand-rolled its own signal carrying the *batch index*,
  written before the ack. Same race, and once the drain switched to
  frontier semantics it forwarded almost nothing — the C drain began
  returning an empty stream. Caught by a failing test, not by review,
  because splice calls neither emitter.
* The **six worker-loop disposition sites** all committed through
  `fr_py_complete(-1, …)`, verified to return immediately when
  `signal_fd < 0`. Left alone, `POISONED`/`SKIPPED` would have been
  committed and never announced.
* A **fifth output writer**: the legacy direct-write path in
  `_worker.py` advanced the frontier by a hardcoded `16 + len(blob)` while
  `_HDR` is a **24-byte** `<QQII>` header — 8 bytes short per record,
  accumulating until recovery truncated into committed output. It was
  masked in `order="index"` coverage because ordered-ACK processing
  resynchronises the cursor to the true file end; unordered runs had no
  such correction. Now derived from `_HDR.size`, which also fixed a
  silent skip: `len(blob)` raised on `None`, swallowed by the bare
  `except`, so `NO_RESULT` batches advanced nothing at all.
* A **fourth output writer**: `fr_py_exec_spawn()` advanced the frontier
  only `if (cap_len > 0)`, while `fr_py_emit_record()` always writes a
  header. Two sites in that one function were wrong in opposite ways —
  one emitted a zero-payload `NO_RESULT` record without advancing, so
  recovery truncated to a stale `output_start` and destroyed an
  already-committed record; the other skipped the emit entirely, so a
  successful command with empty stdout produced **no terminal record at
  all**. The advance is now **centralised inside the framer**, so no
  caller can omit one it no longer performs.
* The **splice POISONED branch** was missed by that scan *twice*: once
  when the splice conversion was lost to a truncation-and-restore, and
  once because the branch uses `fr_py_ack` rather than
  `fr_py_complete(-1, …)`, so a scan keyed on the completion helper never
  saw it. It shipped committing a `POISONED` record without notifying
  the drain. Fixed, and all seven sites are now asserted to notify.

An emitter audit is only as good as the set it enumerates. "Every caller
of the two known entry points" is weaker than "every site that writes to
an output memfd" — and the spawn defect was worse than a missing
notification: it was a **wrong frontier**, which corrupts rollback rather
than merely losing a wakeup.

**Coverage limit stated plainly.** `test_stage0_spawn_frontier.py` proves
the silent-command record exists and is framed. It does **not** observe
the frontier itself: `worker_output_end` is worker-local TLS with no
accessor, and reverting the advance leaves those tests passing. The
advance is guaranteed structurally (centralised in the framer) and
behaviourally by the launcher-backed suites that do observe rollback. A
true end-to-end spawn-rollback test needs the C spawn loop under
supervision with a real drain; the launcher serves plugin and UDF only,
so that harness does not exist yet.

### 9.2 Test evidence

`test_stage0_publication.py` splits the two properties, which one
combined assertion could not distinguish:

| fault | stream | property |
|---|---|---|
| after write, before commit | `POISONED` | safety |
| after commit, before notify | `DATA` | completeness |

`test_stage0_matrix.py` covers the retry-content rows, with a
per-attempt varying payload so they are not vacuous:

* same size, different content — stale bytes would survive a size-keyed cursor
* different size — suppression / framing corruption
* repeated recovery — delivered exactly once
* drained queue with no later generation — the `rc == 2` stranding case
* rollback frontier — stream exactly consumed, no batch left waiting

`test_stage0_public_api.py` asserts the same properties **through
`stream()` and `map()`**, not an internal descriptor, because the review
was explicit that "visible" means what the caller sees.

`test_stage0_matrix.py` also covers the complementary content case: with
a one-shot, cross-generation death (`FORKRUN_TEST_DIE_BEFORE_ACK_ONCE`),
attempt 1 dies before commit and attempt 2 succeeds with different
bytes. Exactly one extra invocation is counted, and the abandoned first
attempt's payload is asserted never to appear — for both same-sized and
differing-sized payloads. The per-process attempt counter resets on
respawn, so it could never produce a *successful* retry; that gap is why
the earlier version of these tests only covered the poison case.

The lost-notification test's handshake is **non-publishing**: the worker
wakes the drain with frontier 0, which excludes the record just
committed, waits for confirmation that the drain is alive, and only then
dies. No notification carrying that record's bytes is ever sent before
the death, so the synthetic recovery wakeup is the *only* path that can
deliver it. The earlier version published the record's real frontier,
which proved an ordinary notification works — the opposite of the
property under test — and a lost-notification test that sends the
notification cannot fail when the notification is lost.

`test_stage0_notify_failure.py` closes the last asserted-but-untested
link. `FR_PY_ERR_NOTIFY` is returned when the commit succeeded but the
drain was never notified, and every worker loop treats a nonzero return
as "worker died" — so recovery has to classify that death as IDLE and
decline to retry. **Measured: 5 injected post-commit notification
failures across 5 respawned generations, and every batch still executed
exactly once and was delivered.** The injection writes a marker the test
asserts, because a duplicate-execution assertion also holds trivially in
a run where nothing was injected.

**The handshake.** The sleep-based window was rejected as vacuous, so the
drain now publishes `(worker, cursor)` on a FIFO for every wakeup it
processes — including ones that legitimately forward nothing — and the
worker blocks until it sees its own before dying. A handshake that never
completes exits **97** rather than falling through, and the tests assert
`rc != 97`. Without that assertion the tests could pass while proving
nothing, which is how the original round-3 experiment reached a wrong
conclusion.

### 9.3 Interim policy — resolved on evidence, not assumed

The review required a fail-closed mitigation while the defect existed.
It is **not** implemented, because the evidence says it would now be a
regression rather than a mitigation:

* The guard was to refuse a materialized `map()` on *any* recovered
  worker death. Recovery is now **normal operation** — the public-API
  tests exercise deaths-and-recovery and the caller receives correct
  results. The guard would reject those legitimate runs.
* The streaming disable existed because a post-hoc exception cannot
  retract an already-yielded value. With publication strictly post-commit,
  every yielded value belongs to a committed batch, and the
  public-API tests confirm it.

So the interim restriction set is unchanged from the proposal and does
**not** need the blunt guard:

* `Auto` stays off.
* `stream(order="index")` stays declined.
* Cleanroom: `map(plugin)` is default-on; `udf`, `spawn` and both stream
  routes stay opt-in behind `FORKRUN_CLEANROOM` (`04485e52`).

If external review rejects the protocol, the containment to fall back on
is to **disable the affected envelope**, not to narrow the detector.

### 9.3a Why fail-closed on the synthetic wakeup is safe

Making `fr_wake_drain_committed()` fail-closed initially looked unsafe: a
synthetic wakeup that hits `EPIPE` cannot, by itself, distinguish "the
drain finished after consuming everything" from "the drain never saw
these bytes". Aborting on it appeared to risk failing legitimate runs.

It does not, and the reason is structural: **`spare_sig` stays open for
the whole supervision loop** — "spare closed LAST ... keeps the drain
alive across respawns" — so the signal pipe cannot reach EOF while the
supervisor is supervising, and the drain cannot have exited. The write
therefore cannot fail because the drain is gone.

Verified directly rather than assumed: instrumented runs of both a clean
launcher run and one with injected worker deaths reported no wakeup
failure at all.

> An earlier conclusion in this work stated that fail-closed "aborts
> legitimate runs", based on 58 failing tests. That was **wrong** — the
> failures were a cwd artifact (plugin fixtures resolved from the wrong
> directory) plus a stale build. The correction matters because the
> "obvious" conclusion here was to fall back to best-effort and document a
> limitation, which would have left a real completeness hole in place.

`FORKRUN_TEST_BREAK_DRAIN_WAKEUP` closes the spare just before recovery
so the undeliverable case can be tested: the run must exit non-zero and
must not present a short stream as complete.

### 9.4 Still open

* Ordered streaming (stage 2) — untouched, still declined.
* The CPython matrix and the remaining expansion stages — untouched.
* `FORKRUN_TEST_NOTIFY_FAIL_ONCE` makes `fr_py_notify_committed` return
  -4 without attempting the write. It therefore proves the CALLER
  handles the code correctly, but not that a real signal-write failure
  (EPIPE/EBADF) routes to it. Covering that needs a signal fd that fails
  only at the post-commit moment, which a closing reader cannot provide —
  if the read end goes, the drain stops publishing and the run is
  aborting regardless. Left as a known limit rather than papered over.
