# DECISION-02 — How does `stream(order="index")` know a batch produced nothing?

**Blocks:** P2 (the `stream()` half of coverage completion).
**Needs:** maintainer + external AI review. Consensus before implementation.
**Status:** open. No code written.

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

`python/forkrun/_shim.c:574-575`, in `fr_py_emit_record`:

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

### 2.3 The parsers already tolerate a zero-length frame

`_split_records_views` (`run.py:2460-2476`) does:

```python
idx, ln = _HDR.unpack_from(view, off)
...
records.append((idx, view[off:off + ln]))
```

For `ln == 0` this appends `(idx, <empty>)`. **No parser change is needed to
accept empty frames.** That makes one option much cheaper than expected.

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

## 4. Recommendation

**Option B, gated to the ordered-streaming path — and only because it is the
same fix C0.7 needs.**

The reasoning:

1. **Options A and C both fail on cost, not correctness.** A gives up
   streaming entirely, which is the feature. C adds a channel to deliver
   information that Option B puts in a field the format already has.

2. **B is cheap in the one place I expected it to be expensive.** The
   parsers already accept `len == 0` (§2.3). The cost is not mechanical; it
   is the semantic change to `map()`.

3. **The semantic change is arguably a fix, not a break.** Today a
   successfully-completed-but-empty batch is invisible. That is why my
   §5a certificate was wrong when I first wrote it: *the system cannot tell
   a correct run from a lossy one.* Making completion explicit removes an
   ambiguity the API currently hides. But I hold this loosely — it is
   observable, and whether to gate it is a real question, not a formality.

4. **It unblocks P5.** C0.7's certificate and this are one requirement. A
   solution that serves streaming but leaves the certificate unable to
   distinguish completed-empty from missing has solved half of a problem the
   plan treats as one.

**What would change this:** if the compatibility analysis shows that gating
B produces a runtime-selected dual format that is worse than the ambiguity it
fixes, then **Option A plus reclassifying `stream(order="index")` as a
correct decline** is the honest, cheaper answer — and the coverage plan
should say so rather than leaving it listed as a gap.

---

## 5. Questions for reviewers

1. **Is B's `map()` semantic change acceptable, gated or not?** My instinct is
   that ungated is a genuine improvement (it removes a hidden ambiguity) and
   gated is a compatibility dodge that leaves two runtime-selected formats.
   I would like that challenged.
2. **Is the "same fix as C0.7" claim correct**, or does the certificate need
   something the streaming path does not — for example per-node attribution
   that only the engine has?
3. **Does Option C really require engine changes?** If per-batch completion
   is reachable from the launcher or shim without touching frozen code, C
   becomes more attractive than I have assessed, because it avoids the
   compatibility question entirely.
4. **Is Option A + reclassification the better answer** on the grounds that
   streaming and total order are in genuine tension, and adding a
   completion signal to the wire format is a larger architectural change than
   this coverage gap warrants?
5. `on_error="skip"` and poisoned batches also complete without output. Do
   they belong in the same frame contract, and does treating them as
   "completed-empty" weaken the poison accounting that `strict_poison` (§P2
   strict-poison half) depends on?
