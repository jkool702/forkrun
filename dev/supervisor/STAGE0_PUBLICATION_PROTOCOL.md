# Stage 0 — publication/commit protocol design note

**Status: design revision 3 — for external review before implementation.**

Companion to `CLEANROOM_EXPANSION_PROPOSAL.md` §0a. That section records
the defect; this note is the design work the review asked for before any
code is written.

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

**S2 — Completeness.** Every committed batch's record is delivered
exactly once.

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
only permitted responses are:

* trigger recovery notification, when that can be done safely; or
* abort the run **without claiming successful completion**.

An abandoned consumer or an unrecoverable notification failure must
**never** become a retry of committed work. Because the state is already
`TXN_IDLE` when the signal is written, recovery naturally classifies this
as "committed, nothing in flight" and does not re-execute — but the
emitters must not convert it into an error return that the loop turns
into a retry.

### 3.7 Every emitter that must conform

The review's point that `fr_py_emit_disposition` signals independently is
correct — reordering only `fr_py_complete` would leave dispositions
racing. Full audit of the current signal sites:

| emitter | site | conforms? |
|---|---|---|
| `fr_py_emit` (payload) | `_shim.c:1570`, signals at 1645 | move signal after commit; distinguish post-commit failure |
| `fr_py_emit_disposition` | `_shim.c:801`, signals at 825 | **same**, plus no-retry outcome |
| disposition call sites | `_shim.c:1715, 3244, 3302, 3500, 3554, 3672, 3731` | all inherit; each must commit before signalling |

Two signal sites, eight disposition call sites across the four loops. All
must conform or S1 stays false for dispositions — exactly the record
class ordered reassembly depends on.

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
| 10 | respawn reuses `wid` | n/a | fresh memfd | `incarnation` resets cursor | ok |

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