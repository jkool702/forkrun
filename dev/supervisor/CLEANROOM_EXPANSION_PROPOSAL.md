# Proposal — expanding cleanroom exec beyond its current envelope

**Revision 3** — consensus with external review, round 2. Supersedes
revisions 1 and 2.

Items **1, 2, 4, 5**, re-sequenced.

**Future work orders (not in this scope, but will be implemented):**
item 3 (`mode="python"` parity), item 6 (NUMA), item 7 (resume). This
document defers them to keep the immediate work order focused, NOT
because they are cancelled. Everything below is written with that in
mind: §5's `Auto` reaches its full default-mode meaning only once item
3 lands, and §8 records what must be revisited when it does.

Base SHA for this revision: **`c72d27c6`** (see §7 — the round-1 review
was inspected against a stale tree).

Status: **proposal**. Nothing here is implemented.

---

## 0. Consensus summary

Round 1 returned **GO WITH AMENDMENTS on the plan, NO-GO on implementing
ordered streaming under the revision-1 boundedness design.** Accepted in
full; see §2.

Round 2 accepted the revision-2 corrections and added a new finding: a
**publication/commit race** in the output-drain protocol, reported as
blocking. That finding was investigated first, as asked.

**Result: the reported failure mode does not reproduce.** The window is
real and was forced open deterministically; the exactly-once invariant
held. Details, and the narrower question that remains open, are in §1.

| round-2 point | disposition |
|---|---|
| §1 terminal record can be published before commit → duplicate/contradictory terminal records | **investigated — not reproduced.** Window forced open; invariant holds. Residual narrower risk recorded in §1.3 |
| §2 stage 1 needs a per-producer coverage contract | **accepted** — §2.5 |
| §3 spawn contract must state the limit of the guarantee | **accepted, Option A** — §3.3 |
| §4 automatic rollout needs a performance gate, not just correctness | **accepted** — §5.2 |
| §5 dependency picture | **accepted** — §6 |

---

## 0a. The publication/commit race — investigated, not reproduced

The round-2 review raised this as a potential **pre-existing
exactly-once weakness**, not merely a gap in the new work:

> `fr_py_emit_disposition()` writes the record and signals; the drain
> forwards and punches independently; a death in that window leaves a
> record published that rollback cannot retract, so the retry produces a
> second, possibly contradictory, terminal outcome for the same batch.

**This was tested before anything else, as instructed.** The result:

### 1.1 The window is real

`fr_py_drain_loop` (`_shim.c:2357`) reads a signal, copies whole records
to `results_fd` and punches the source memfd. It never consults the
worker's ack. So publication genuinely precedes commit. The reviewer is
right about the mechanism.

The existing tests cannot see it, and that part of the review is also
right: `FORKRUN_TEST_DIE_BEFORE_ACK` fires immediately after the signal,
so whether the drain has forwarded yet is a scheduler race. When the
worker usually wins, the record is still in the memfd, the rollback is
clean, and the test passes — **for the wrong reason**.

### 1.2 Forcing the window open

`FORKRUN_TEST_DIE_AFTER_DRAIN_MS` (added in this revision, inert unless
set) delays the kill after the signal so the drain provably forwards
first. Verified by observation, not assumed: the probe
(`python/tests/test_drain_publication_race.py` plus a byte-level dump)
watches the results fd **while the launcher is still running** and sees
24 bytes — exactly one record — already published downstream mid-run.

With that window genuinely open, over 5 batches × repeated death:

* **5 records for 5 batches — no duplicates.**
* **Exactly one terminal outcome per batch — no contradictions.**
* **Stream fully consumed, zero tail** (120 bytes = 5 × 24-byte
  `POISONED` records; the `<QQII` header is 24 bytes, not 16).
* An unfaulted control through the same drain yields 5 clean `DATA`
  records (175 bytes, zero tail).

So the invariant the existing exactly-once tests claim **does hold under
the forced window**. The specific failure mode is not present.

### 1.3 What remains open — narrower, and honestly uncharacterised

I have **not** produced a full mechanistic proof of *why* it holds. The
most likely mechanism is that the drain's per-worker cursor
`offsets[wid]` (`_shim.c:2400,2519`) is monotonic and never rewound, so
a retry that rewrites the same byte range after rollback produces no
new forwarded bytes. That is consistent with the observation, but I did
not verify it end to end.

One genuinely untested case remains, and it is the one worth closing
before dispositions are treated as an authoritative ordered protocol:

> **If a retry produces a record of a DIFFERENT SIZE than the attempt
> already forwarded** — e.g. attempt 1 forwarded `DATA` (24+len bytes)
> and the retry ends `POISONED` (24 bytes, zero payload) — then the
> committed outcome and the published outcome may disagree. Not a
> duplicate, but an ordered consumer could advance a batch on a `DATA`
> the transaction later poisoned.

The current producer paths emit exactly one record per batch
(`fr_py_complete` with `data == NULL` emits nothing), so this did not
trigger here. It is a **Stage-1 test obligation**, not a known bug, and
it must not be silently assumed away by anyone reading §1.2 as "the
protocol is proven".

**Definition of done for this item:** a documented mechanism (or an
engine-free protocol change) plus a test that forces the differing-size
retry. Until then, dispositions are "observed correct under forced
window", not "proven consistent with the commit point".

---

`order="index"` is **already served** for `map()`: oracle R4 admits it
and `test_order_index_takes_cleanroom_and_matches_in_process` proves the
launcher is entered and the parent sorts. Only `stream()` declines it
(R6).

So ordered streaming is default-surface **breadth**, not a prerequisite
for the default `map()` path. **`mode="python"` (item 3) is the blocker
there**, and is out of scope here.

---

## 2. Ordered streaming (`item 5`) — DECLINE STANDS

**`stream(order="index")` remains declined.** Revision 1 proposed
implementing it; that proposal is withdrawn.

### 2.1 Why the revision-1 boundedness argument was wrong

It claimed: *"the 16-byte keyed signal pipe caps outstanding un-drained
completions … so memory is bounded by construction"*, and *"every
non-`DATA` batch advances the prefix; the only unbounded wait is a
genuinely live `DATA` batch, which is bounded by the engine's retry
limit."*

Both halves fail.

**It is a count bound, not a byte bound.** A signal names a worker and a
batch; the payload it announces is arbitrarily large. The current parser
also retains an incomplete framed record in `tail` until the advertised
length is available, so one large result can exceed any budget before it
is ever a buffer entry. `reassembly_limit` was a *diagnostic*, not an
enforced cap.

**And stopping the read can deadlock the batch that would unblock the
prefix.** One precision the review did not have, and which sharpens its
finding rather than softening it:

* `map()` uses a **memfd** for results (`run.py:1039`) — writes never
  block, so none of this applies. That is exactly why `map(order="index")`
  needs none of this machinery today.
* `stream()` uses a **pipe** (`run.py:1621`) — and that is the path under
  dispute.

So on the streaming path: parent stops reading → the C drain blocks
writing → the drain stops consuming worker signals → the signal pipe
fills → workers block announcing completions → the missing head batch's
terminal record cannot reach the buffer → the prefix cannot advance while
the parent waits for it to. A cycle with the head batch inside it.

**And the retry limit does not bound it.** The retry limit bounds
retries *after a failure*. A hung or long-running invocation is not
bounded by it. The claim that a live `DATA` batch is bounded was simply
false.

### 2.2 What must be built first regardless

`ReassemblyBuffer` documents mid-stream head-of-line blocking as inherent
because *"the parent has no poisoned-index channel; only a scalar
count"*. That is no longer true — P5 emits `POISONED` and `SKIPPED` on
the wire. But the fix is **larger than revision 1 assumed**, and this is
verified, not hypothetical:

* `_split_records` / `_split_records_views` (`run.py:2629,2661`) filter
  every non-`DATA` record. So does the cleanroom stream loop
  (`run.py:1706`) and `_cleanroom_collect` (`run.py:1514`).
* Therefore a batch returning `None`, skipped, or poisoned is **invisible**
  to the buffer and reads as a hole. Adding `SKIPPED`/`POISONED` to the
  wire did not fix ordered streaming — it made the records *available*
  and the pipeline then discards them.

Required:

* A **dedicated terminal-record parser** carrying `(batch_idx,
  disposition, payload)`, rather than changing `_split_records` globally —
  its filtering is load-bearing for several other callers.
* `add_disposition(batch_idx, disposition)`; **all four** dispositions
  advance the contiguous prefix, only `DATA` yields a payload. `b""` must
  be recorded as a real empty `DATA`, not treated as absence.
* **Finalization contract:** after a successful run, an unresolved gap
  inside the emitted index range is a protocol failure, not something to
  paper over with `final_drain()` sorting the remainder. Legacy paths
  that genuinely lack terminal records keep today's behaviour until their
  protocol is upgraded.

This is worth doing on its own merits — it is the precondition for any
ordered path — but it does **not** by itself justify lifting the decline.

### 2.3 Test invariants (corrected — revision 1 had these wrong)

Revision 1 said later batches should flow *"before the hole resolves"*,
which contradicts strict index ordering. Correct invariants:

1. A later batch is **never** yielded out of order while an earlier index
   is unresolved.
2. On the head's `DATA`, yield it, then drain the contiguous prefix.
3. On the head's `NO_RESULT`/`SKIPPED`/`POISONED`, advance without
   yielding, then drain the newly contiguous prefix.
4. Advancement happens **promptly**, not at EOF.
5. No deadlock when the budget is reached.

Ordering, advancement-after-terminal, progress-after-head-resolution and
budget-reached-no-deadlock are four separate assertions.

### 2.4 What would unlock it

A design note plus an adversarial prototype, proving **both** properties:

* *Byte-boundedness* — accounting for max record size, parser-tail
  memory, buffered out-of-order payloads, and the transport.
* *Liveness* — the earliest unresolved batch can always publish its
  terminal record even at the budget limit.

Candidate directions: spooling out-of-order results to a temp file
(bounds RAM, **not** total temporary storage — must be stated), or an
explicit credit/window protocol guaranteeing the head can publish.

If neither holds, the decline is the correct permanent answer. A soft
warning is not an enforced cap, and dropping a result to honour a memory
threshold would be worse than not shipping the feature.

### 2.5 Producer-coverage contract (round-2 §2)

Adding a terminal-aware parser does **not** give every producer a
complete terminal history. The guarantee must be stated per producer,
not merely per consumer implementation:

* Audit every record reader that feeds ordered streaming:
  `_drain_records()`, `_make_results_pump()`, the cleanroom stream
  parser, and `_cleanroom_collect`.
* For each producer mode, record which of `DATA` / `NO_RESULT` /
  `SKIPPED` / `POISONED` are **guaranteed** to be emitted. The ordinary
  Python worker path acknowledges poisoned batches silently, and
  `on_error="skip"` acknowledges without a `SKIPPED` record in some
  paths; the C loops differ again.
* Where a producer cannot distinguish "legitimately produced no output"
  from "record missing", the unresolved-gap-is-a-protocol-error rule
  **must not** be applied to it. Legacy paths keep today's finalisation
  behaviour until their protocol is explicitly upgraded.

Stage 1's acceptance is therefore per-protocol, not global: *all four
dispositions advance the contiguous prefix, only `DATA` yields, and a
genuine `b""` is `DATA` — never conflated with `NO_RESULT`* — for the
protocols that actually provide them.

---

## 3. Spawn in the launcher (`item 4`) — design corrected

`fr_py_worker_spawn_loop` already exists and is parity-tested. The
integration is not a function-pointer substitution.

### 3.1 The signature claim was wrong

Verified:

```
fr_py_worker_plugin_loop  arity=12  (int wid, const char*, const char*, int×9)
fr_py_worker_udf_loop     arity=12  (int wid, const char*, const char*, int×9)
fr_py_worker_spawn_loop   arity=12  (int wid, char **argv, int,       int×8)
```

Same arity, **incompatible types** at positions 2–3. Revision 1 said
"reusing `spawn_wid` unchanged (same signature)"; that was wrong, and the
parity test missed it because it checked arity and stripped signatures.

**So:** an explicit mode-specific worker descriptor carrying the correct
arguments and dispatching the right loop. No cast that disguises the
mismatch.

### 3.2 Command transport

* Preserve arguments as distinct argv elements — no shell-word parsing,
  no ambiguous newline encoding. (Newlines are legal inside an argv
  element; only NUL is not representable in POSIX argv, so reject NUL.)
* Validate the command vector and its limits **before** launching the
  cleanroom or reading any source bytes.

### 3.3 Process ownership — Option A (managed process group)

Round 2 asked for the guarantee's limit to be stated rather than
implied. **Option A is selected**, and the reviewer is right that it is
the honest, smaller contract:

> Cleanup is guaranteed for the command and for descendants that remain
> in the **managed process group** of the worker generation that owns
> them. A descendant that deliberately daemonises, calls `setsid`, or
> otherwise escapes into its own session or process group is **outside
> the guarantee**.

Rationale: a subreaper adopts orphans and makes them waitable, but does
not guarantee they are *killed*, and no amount of group signalling
reaches a process that has left the group. Promising universal
descendant cleanup would require an external supervisor — a materially
larger commitment than the accidental-orphan case item 4 actually
addresses.

The boundary is **tested, not implied**: one test with a child that
stays in the group (must be gone by PID) and one that `setsid`s away
(must be *documented* as surviving, so a future regression that starts
killing it, or loses it silently, is visible).

Covered events for in-group cleanup: worker death mid-batch, recovery
and respawn, fail-fast abort, and launcher teardown / parent
abandonment.

**Definition of done:** a known long-lived child is gone by PID after each
of those four events; infrastructure failure still reaches `on_error` and
not the death path; the parity test still passes unmodified.

---

## 4. Splice (`item 2b`) — prototype, then measure

The measurement plan was circular: it asked for cleanroom-vs-in-process
splice performance before the launcher dispatches
`fr_py_worker_splice_loop` at all.

**Bounded prototype first** — expose the existing loop through the
launcher on a scratch branch with the minimum hooks to produce valid
benchmark numbers. Then measure wall time and peak parent RSS across
input sizes and worker counts, and report the break-even point rather
than a ratio. Implement only if the numbers justify it.

**Withdrawing an earlier claim:** exactly-once is **not** out of scope.
Splice has no external command to orphan, but it still emits output
records under worker supervision; a death around publication/ack must not
produce duplicates, stale output, or missing output. The invariant
applies.

`fr_py_worker_splice_loop` is also not signature-compatible with the
launcher callback (arity 5). The launcher's generic spill, drain,
framing and supervision code is reusable; that is not the same as
"no mode-specific work".

---

## 5. Automatic backend selection (`item 1`)

Users stop setting `FORKRUN_CLEANROOM=1`.

**Scope limit, unchanged and explicit:** full `Auto` for the *default* path
needs item 3. This delivers the already-served envelope — plugin, UDF,
`map()` including `order="index"`, both supervision policies — and must
not imply the default mode is covered.

### 5.1 Three policies

| policy | behaviour |
|---|---|
| `auto` (default) | cleanroom when it can honour the call, else in-process |
| `off` | force in-process; diagnosis and rollback |
| `required` | demand cleanroom and **error** if unsupported — never silently fall back |

`required` is what makes this safe to ship: it turns "unsupported" from a
silent behaviour change into a loud one.

### 5.2 Staging decoupled from streaming

Revision 1 tied Stage B to item 5. That was wrong:

* **Policy foundation + Stage A** (plugin/UDF) — independent of ordered
  streaming. Gate: identical results to in-process across the corpus.
  UDF restricted to **verified** CPython minors.
* **Map envelope Auto** (incl. `order="index"`, strict-poison where
  supported) — **independent of stage 2**, because map ordering already
  works.
* **Stream envelope index-order Auto** — depends on §2.
* **Spawn Auto** — depends on §3, and only for the envelope actually
  implemented and tested. Do not imply streaming spawn if only
  materialized `map()` was integrated.

### 5.2 Evidence gate: correctness **and** performance

Byte-identity against the in-process path is necessary but not
sufficient to justify making the cleanroom automatic. Each envelope
needs both:

* **Plugin Auto** — may reuse existing cleanroom benchmark evidence,
  provided it corresponds to the pinned release candidate and the exact
  served envelope. Re-measure if either moves.
* **UDF Auto** — needs its own correctness *and* performance evidence
  for **every CPython minor** proposed as verified. A minor is not
  enabled merely because the generic launcher works on it.
* **What to measure** — the user-visible path: startup, end-to-end wall
  time, and representative parent RSS/workload sizes. **Regressions are
  reported, not just wins.**

Existing measurements may satisfy this; the point is that the gate must
say what counts as adequate evidence rather than naming byte-identity as
the sole criterion. A new benchmark campaign is only required where
adequate evidence does not already exist.

### 5.3 Backward compatibility

`FORKRUN_CLEANROOM=1` must **not** silently acquire `required`
semantics — it previously permitted safe fallback. Spell that out and
test it.

Contract under **any** policy: never replay a source or user payload
after an uncertain or potentially post-ingest failure. The fallback
contract is more load-bearing once `Auto` is the default.

---

## 6. Revised sequencing

| # | Stage | Gate to proceed |
|---|---|---|
| 1 | Terminal-record parser + disposition-aware `ReassemblyBuffer` (§2.2) | all four dispositions advance the prefix; gaps detectable |
| 2 | **Design note + prototype** for bounded, live ordered streaming (§2.4) | both properties proven; **decline stands until then** |
| 3 | Spawn integration (§3) | no orphaned children on death, respawn, fail-fast, teardown |
| 4 | Splice prototype → measure (§4) | measurement, then a go/no-go decision |
| 5 | `auto`/`off`/`required` (§5) | per-envelope gates; map Auto not blocked by 1–2 |

Stages 1, 3 and 4 are independent and can run in parallel. Stage 5's map
Auto does not wait on 1 or 2. Stage 2 gates only ordered streaming, and
may never conclude "ship it".

---

## 7. Source-version discrepancy — resolved

The review reported the `stream(strict_poison=True)` decline still
present in `_cleanroom_eligible()`, while revision 1 cited `c72d27c6` as
removing it.

Verified against the pushed branch: `git show
origin/NEW/REFACTOR4.2:python/forkrun/run.py` contains **zero**
occurrences of that refusal string, and no mutation marker. HEAD is
`c72d27c6`. The reviewed tree predated the push; the fix and its
launcher-entry test are both present.

---

## 8. Carried forward

* **`_RUN_LOCK` under `orchestrator=False`** — the dispatch holds it, the
  legacy path does not. Required policy review *before* `Auto` multiplies
  the paths that take it.
* **CPython matrix** — helper verified on 3.14.7 only. `Auto` must key
  the UDF route on a *verified* minor. A release gate on stage 5.
* **Non-representable callables** — a closure cannot cross `exec`. Belongs
  to item 3's contract, but `Auto` must reject **before input is
  consumed**.
* **Differing-size retry** — the untested case in §1.3. A Stage-1 test
  obligation.

## 8a. Deferred to future work orders — explicitly still wanted

These are out of scope for *this* work order, not cancelled:

* **Item 3 — `mode="python"` parity.** The largest remaining capability
  gap, and the one that makes `Auto` meaningful for the *default* path.
  When it lands, revisit §5: the policy surface, the representable-
  callable rejection rule, and the default-mode claims all change.
* **Item 6 — NUMA.** A socket-topology claim that needs hardware this
  environment does not have. The decline stays correct until measured.
* **Item 7 — resume.** Recovery is currently per-run; durable resume
  needs its own transaction model.

Ordering consequences for the present work: `Auto` must not *claim*
default-mode coverage it does not have (§5), and `stream(order="index")`
must not become load-bearing for anything the other two depend on (§2).

## 9. Not established by this proposal

* Whether `Auto` is safe for every source kind — the matrix declines
  iterables and several descriptor shapes; the fallback contract applies
  to all of them.
* Anything about NUMA or resume. Both stay declines.
* That ordered streaming is worth shipping if §2.4 cannot be made
  rigorous. The decline is then the correct permanent answer.