# DECISION-02 — How does `stream(order="index")` know a batch produced nothing?

**Blocks:** P2 (the `stream()` half of coverage completion).
**Needs:** maintainer + external AI review. Consensus before implementation.
**Status: DECIDED — GO WITH AMENDMENTS. Option B as originally specified is
WITHDRAWN.** Replaced by an explicit typed terminal-disposition protocol.
See §6.

> **Amendment log.** External review round 1 returned *GO WITH AMENDMENTS* and
> **refuted the recommendation**. I had proposed emitting a zero-length frame
> for every empty batch, on the evidence that the parsers already tolerate
> `len == 0`. That evidence was real but did not support the conclusion: the
> codebase **already uses `len == 0` to mean something**, so a zero-length
> frame is not free — it is *taken*. Details in §6. This was the same error
> shape as the abi3 `PyConfig` claim: a true fact generalised one step too
> far without checking what else already depended on it.

---

## 1. The question

`stream()` in the cleanroom currently **only drains**: it launches, then
yields result records as they arrive — unsorted, unreconstructed. That is
deliberate and documented ("The parent only ever DRAINS"), and it is what
makes the path deadlock-free.

`order="index"` is declined, because there is no mechanism to reorder.

To serve it *without destroying streaming*, the parent must release an
ordered prefix as it becomes available. That requires it to know, at any
moment, **which batch indices are still legitimately outstanding**. And
here is the problem:

> If batch 5 has not produced a record, is that because **it produced
> nothing**, or because **it has not arrived yet**?

Wait for 5 and the stream stalls forever if 5 was legitimately empty. Don't
wait and the output is out of order.

**The question is how the parent learns the answer.**

---

## 2. Established facts

### 2.1 Empty batches emit *no frame at all*

`python/forkrun/_shim.c:575-576`, in `fr_py_emit_record`:

```c
if (src_len == 0)
    return 0; /* v0 parity: empty output emits no record (None). */
```

Not a zero-length frame — **nothing**. The parent's view of an empty batch is
indistinguishable from its view of a batch that has not arrived. The ambiguity
is structural in the wire format, not an oversight in the streaming code.

### 2.2 It is reachable, and it is not exotic

Measured: a UDF returning `None` for half its batches, 1000 lines at
`lines=10`, in-process with `order="index"`:

```
published_slots=100   emitted_records=0   total=0 completed=0 poisoned=0
```

`poisoned=0` matters: these batches were **not** skipped as failures. They
completed successfully and produced nothing. Returning `None` is ordinary
Python.

### 2.3 The parsers tolerate a zero-length frame — and that is a TRAP, not a
### permission

`_split_records_views` (`run.py:2451-2476`) appends `(idx, view[off:off+ln])`
unconditionally, so `ln == 0` parses without complaint.

**This is why Option B fails.** Mechanical tolerance is not semantic safety,
because `len == 0` **already carries meaning** on this wire format:

`fr_py_emit` (`_shim.c:1297-1309`), the v0-parity direct-write path:

```
 * - data == NULL   -> no record (payload returned None), signal only.
 * - data != NULL, len == 0 -> header with len 0 IS written
 *   (payload returned b"" - v0 emits an empty record; None-vs-b"" preserved).
```

And that distinction is **tested**: `test_v1_emit.py:100`,
`test_emit_empty_bytes_writes_empty_record`, asserts `fr_py_emit(out, w, 1,
9, b"", 0)` writes a 16-byte frame whose header unpacks to `(9, 0)`.

So the wire format already encodes:

| UDF returns | wire representation |
|---|---|
| `b""` | a frame with `len == 0` |
| `None` | **no frame at all** |

Emitting a zero-length frame for empty batches would therefore **collapse a
tested distinction**: `None` and `b""` become indistinguishable. Every parser
would still parse it; every parser would also now be *wrong*.

### 2.4 This is the same problem C0.7 has

The C0.7 completion certificate needs "one order packet per published batch,
including batches whose payload is empty" — precisely to distinguish
completed-empty from missing. **The P2 streaming fix and the P5 certificate
fix are the same underlying requirement.** Any solution here should be chosen
with that reuse in mind.

---

## 3. Options

### Option A — Buffer everything, sort at end

Parent accumulates all records, sorts by `batch_idx` at EOF, then yields.

* **For:** trivially correct; no format change; no new channel.
* **Against:** no output is delivered until the run completes, and memory
  holds the entire result. **`stream()` becomes `map()` with extra steps.**
  This is not "serving `order='index'`"; it is declining it while doing more
  work. If this option is chosen, the honest classification of
  `stream(order="index")` is **correct decline**, not a gap.

### Option B — Emit a zero-length frame for every completed batch

Change `fr_py_emit_record` to write the header with `len == 0` instead of
returning early. Every published batch then has exactly one frame, and the
parent releases the ordered prefix as soon as the next index arrives.

* **For:** makes the stream genuinely incremental; **parsers need no change**
  (§2.3); it is exactly the C0.7 "one packet per batch" contract, so **P5's
  certificate gets stronger for free**.
* **Against — and this is serious:** it changes what `map()` returns for every
  user whose UDF yields nothing. Today `len(out)` counts only non-empty
  results; afterwards it would count empty ones. That is an **observable
  breaking change to the public API**, and §2.2 shows users are relying on
  the current count (my own certificate attempt was broken by it).
* **Mitigation:** gate it behind a flag set only for the ordered-streaming
  path, leaving `map()` untouched. That keeps the wire format
  path-dependent, which is itself a smell — two formats, selected at runtime.
* **Blast radius:** `_shim.c` is engine-affecting under the coverage plan's
  §7 policy, so this needs the invariant-plus-test treatment.

### Option C — A separate per-batch completion channel

The launcher writes a completion ledger (every batch index that finished,
output or not) to a side channel. The parent consults it to decide when to
advance the ordered prefix. Record semantics are untouched.

* **For:** no change to what any user receives; `map()` is unaffected.
* **Against:** a new channel with its own framing, versioning and lifetime.
  **And the launcher does not currently know per-batch completion** — that
  state lives in the engine's ring, so producing the ledger likely requires
  engine or shim changes anyway. It may be *more* work than B, not less.

### Option D — Timeout or heuristic

Assume a batch that hasn't arrived within N seconds produced nothing.

* **For:** trivial.
* **Against:** unsound. It converts a stall into *silent reordering* under
  load — the exact failure class this project has spent CR-FIX1 removing. I
  would not implement this in any form.

---

## 4. Recommendation — WITHDRAWN

The recommendation below was **withdrawn by external review round 1**. It is
kept only so the reasoning's failure is visible, not to be re-derived.

> ~~**Option B, gated to the ordered-streaming path — and only because it is
> the same fix C0.7 needs.**~~
>
> The load-bearing claim was: *"B is cheap in the one place I expected it to
> be expensive. The parsers already accept `len == 0` (§2.3)."*
>
> That is where it fails. The parsers accept `len == 0` **because `len == 0`
> already has a meaning** — a real `b""` result (§2.3). Mechanical tolerance
> was evidence of an existing convention, not of available capacity. The
> correct acceptance criterion was never "the parser accepts it" but "the
> consumer can tell a control disposition from an empty data result", and
> Option B failed that test.

---

## 5. Decision — explicit typed terminal dispositions

**Agreed.** The ordered-streaming path needs an authoritative completion
signal, and that signal must be **typed**, because the wire format already
uses an untyped `len == 0` to mean "a real empty result".

### 5.1 The disposition set

Every published batch reaches exactly one terminal disposition:

| disposition | meaning to the ordering layer | meaning to the caller |
|---|---|---|
| `DATA` | completed; advance the prefix | yield payload (may legitimately be zero bytes) |
| `NO_RESULT` | completed; advance the prefix | yield nothing |
| `SKIPPED` | terminal skip disposition | yield nothing; skip semantics preserved |
| `POISONED` | terminal poisoned state | yield nothing; poison accounting preserved |

The ordering layer consumes dispositions in `batch_idx` order: it yields only
`DATA`, advances past `NO_RESULT` without waiting for EOF, and advances past
`SKIPPED`/`POISONED` **without converting those outcomes into successes**.

`map()` filters control dispositions and returns exactly today's result list.
**`None` remains distinct from an empty bytes result.**

### 5.2 Binding conditions

* **Exactly one final disposition per batch.** It is a terminal outcome, not an
  attempt. It must be emitted only when the batch will not be retried, and
  integrated with the existing output transaction and recovery semantics, so
  that worker death, retries, respawn, partial writes and rollback can neither
  duplicate nor lose one.
* **The consumer must identify the type explicitly.** Parser tolerance is not
  the acceptance criterion; being able to *tell* a control disposition from an
  empty data result is.
* **Prefer the existing framed result channel** with a tagged header, provided
  that introduces no ambiguous framing and does not compromise backpressure.
  A separate ledger (Option C) remains the fallback and must handle the case
  where a completion arrives before its data record has drained.
* **Poison accounting is unchanged.** The ordering layer may advance past a
  poisoned batch; it must never reinterpret poison as successful empty output.
  *A missing payload implies neither success nor poison.*

### 5.3 Scope boundary with P5

Shared invariant: **every published batch reaches exactly one authoritative
terminal disposition, including those with no output.**

P5's certificate must **independently** prove that every published batch is
accounted for exactly once, with whatever per-node and sequence identity its
scope requires. **P5 is not solved by P2 seeing markers.** The claim does not
carry across.

### 5.4 Decision boundary

Proceed with the typed disposition protocol if it can satisfy 5.2 and be
shared cleanly with P5. If the required changes prove disproportionate to the
value of the acceleration, **Option A is the honest alternative**: keep
declining `stream(order="index")` and classify it as a **correct decline**,
recorded as such rather than left as an unresolved gap. What must not happen
is the untyped shortcut being adopted in order to claim coverage.

### 5.5 A discrepancy this surfaced — not part of the decision

The two emit paths **already disagree** about the zero-length case:

| path | zero-length behaviour |
|---|---|
| `fr_py_emit` (direct write, `_shim.c:1297-1309`) | writes a `len == 0` header — empty result preserved |
| `fr_py_emit_record` (memfd copy, `_shim.c:575-576`) | `return 0` — **no record at all** |

`fr_py_emit_record`'s comment claims "v0 parity", but v0 parity per
`fr_py_emit`'s documentation and `test_v1_emit.py:100` is that a zero-length
payload *does* produce a record.

`fr_py_emit_record` receives only a `src_len` copied out of a memfd, so it
**cannot distinguish an empty result from no output** — the information is
gone before it is called. Whether that is a latent bug or an accepted
limitation of the memfd path is **not established here**, and is recorded as
an open question rather than a finding. It matters because the typed
disposition protocol has to preserve whatever distinction the direct path
already makes.

**Open question for the next round:** should the memfd path gain the ability
to express a zero-length result, and does that change belong in this work or
in a separate item?

---

## 6. P5b — the exactly-once proof, and what it found

DECISION-02 section 5.2 binds the design on one point: *"worker death,
retries, respawn, partial writes and rollback can neither duplicate nor
lose one."* That is a claim about failure behaviour, so
`python/tests/test_exactly_once.py` establishes it by driving the fault
sequences and parsing the actual output stream, rather than trusting
return codes.

**The invariant:** for every batch that reached a terminal state, the
stream contains *exactly one* record with that `batch_idx`. Zero is a
lost disposition; two is a duplicated one — and a duplicate is worse than
a loss, because it shifts every subsequent batch by one position.

### 6.1 A real, pre-existing bug the proof was built to find

Driving four deaths in one worker session produced:

```
FINAL batch ids: [0, 1, 2, 2, 3, 4, 4, 5]
```

Duplicates at 2 and 4. **Only the first recovery in a worker session
rolled anything back.** Every later one returned `RECOVERED` while
leaving its orphan in the stream.

Root cause: `ring_recover_worker_core` truncates the output fd back to
`txn->output_start` but does not move the TLS `worker_output_end` cursor
— which is what the *next* claim snapshots as the new batch's rollback
frontier. After a truncation that cursor is stale: it still holds the
pre-truncation position, so the next batch's `output_start` points past
the real end of the file, and the engine's own "never grow a file by
truncating" guard (`st_size >= output_start`) then **refuses** the
rollback. The guard that exists to prevent data loss was silently
preventing data recovery, and reporting success while doing it.

**Pre-existing, not introduced here.** Verified by stashing every change
in this series, rebuilding the substrate, and re-running the same probe at
HEAD: identical `[0, 1, 2, 2, 3, 4, 4, 5]`.

### 6.2 Where it is fixed, and why there

In `fr_py_recover_worker` (`_shim.c`), which re-syncs the cursor on the
`rc == 0` path only. Two reasons for not putting it in the engine:

* `forkrun_ring.c` is **frozen**; the fix is not worth a freeze-policy
  exception for.
* `_shim.c` textually includes it, so the translation unit can see the
  TLS cursor directly. The change is a cursor resync — it does not touch
  the engine's state machine or its recovery *decisions*, only the
  cursor's agreement with the file it describes.

Resyncing only on `RECOVERED` is deliberate: any other return means the
engine declined to roll back, and moving the cursor then would assert an
end-of-output position that does not exist.

Result after the fix: `[0, 1, 2, 3, 4, 5]`.

### 6.3 Coverage

Retry-then-succeed, five consecutive retries, death-then-rollback, death
*after* commit, respawn onto a new generation, and a mixed six-batch run
combining all three outcome kinds in one stream — each asserting
exactly-once. `SKIPPED` and `POISONED` are covered by the same invariant,
using the real exported emitter so the frontier advance is genuinely
exercised.

Mutation-checked: removing the cursor resync fails both
`test_a_SECOND_death_in_the_same_session_still_rolls_back` and
`test_one_record_per_batch_across_every_outcome`.

### 6.4 What this does not yet establish

Exactly-once for the **stream** and **spawn** modes in situ. The engine
primitives are shared and proven here, and the plugin/UDF loops are
covered structurally by the parity test, but no test drives a real
launcher run into multiple deaths and then inspects the stream. That is
the remaining gap, and it is an integration gap rather than a protocol
one.
