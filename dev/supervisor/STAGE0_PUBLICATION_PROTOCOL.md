# Stage 0 — publication/commit protocol design note

**Status: for external review before implementation.**

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

## 3. Candidate protocols

### 3.1 Commit-gated forwarding

The drain buffers records until it can confirm the corresponding
transaction committed.

*Difficulty, and why this is not free:* the drain is a separate process
and would need to observe commit state. The ring clears and reuses
per-worker transaction state, so a transient read is not evidence — the
drain could observe a slot that has already been recycled by the next
batch. This needs either a durable generation/epoch counter per
transaction or an explicit commit notification that the drain
correlates against a `(worker, batch_idx)` it has not yet delivered.

*Cost:* the drain holds forwarded records until commit, reintroducing the
memory question of §2.4 of the proposal. It must be bounded, and the
bounding argument is the same unproven one ordered streaming is waiting
on.

### 3.2 Ack-then-publish, with recovery-driven re-signal

Ack first, then signal. A committed-but-unsignalled batch is found and
re-signalled during recovery.

*Difficulty:* recovery must enumerate committed batches whose records
were never announced. It needs the set of committed-but-unannounced
records to be durable, not reconstructable by scanning (the memfd may be
reused). And re-signal must be idempotent under repeated recovery, or a
batch is delivered twice.

*This is the direction with fewer unsolved questions, but "fewer" is not
"none", and the idempotency requirement is exactly where a naive patch
reintroduces a duplicate.*

### 3.3 Recommendation

**Neither, yet.** §3.1 inherits the unresolved boundedness problem;
§3.2 inherits an idempotency problem of comparable difficulty. The
honest next step is to determine whether either can be made correct
without touching the frozen engine, and to report that before coding.

Per the standing instruction, this goes back to external review. No
implementation begins until one is chosen with its failure cut points
enumerated.

---

## 4. Interim safety policy (review point 1)

The defect is reachable today by ordinary worker death, with `rc=0`.
Withholding `Auto` does not protect users who already select the
cleanroom path explicitly, so **a mitigation is required now**, not after
Stage 0 ships.

Options, in preference order:

**A — Fail closed.** Treat a batch whose recovery changed a
previously-published outcome as a hard failure rather than returning the
stale record. Detectable: recovery knows the batch was retried, and the
consumer can detect that a batch was already delivered. Cost: a rare
legitimate retry becomes a loud failure. Given the defect currently
returns **wrong data with success status**, trading that for a rare loud
failure is clearly correct.

**B — Document and accept.** State the risk in the release notes and
declare it a deliberate decision. Honest, but it leaves a confirmed
wrong-result path available in a shipped executor.

**C — Defer.** Keep `Auto` off and rely on that. **Insufficient** — it
does not address users who already select cleanroom.

**Recommendation: A, implemented as a narrow guard, with B recorded as
the fallback if A proves to require more than a contained change.**
This needs external review before implementation, like §3.

---

## 5. Determinism of the regression test (review point 2)

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

---

## 6. Reproducibility (review point 4)

The pinned base `c72d27c6` predates all Stage 0 artifacts. The exact
tree that produces the evidence is:

* **`0341c9b4`** — `fr_py_maybe_die_after_signal`, both publication-race
  tests, regenerated shim artifacts, ABI pin 53/16.
* Reproduce: `make -f Makefile.substrate python-substrate` then
  `python3 -m unittest test_data_publication_leak` from `python/tests`
  (expects 1 expected failure, suite OK).
* `c72d27c6` is the **defect base** — the commit against which the bug is
  reported, and the last commit without the Stage 0 hooks.

---

## 7. Scope guard

* The ring engine stays frozen unless a source-backed demonstration
  shows no engine-free correction exists.
* Stage 0 does not redesign the drain, only its **publication
  boundary**.
* Research for stages 1/3/4 may proceed in isolated branches; nothing
  may be **integrated or activated** on the current publication
  protocol.