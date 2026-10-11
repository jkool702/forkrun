# Proposal — expanding cleanroom exec beyond its current envelope

**Revision 2** — consensus with external review. Supersedes revision 1.

Items **1, 2, 4, 5**, re-sequenced. Out of scope by request: item 3
(`mode="python"` parity), item 6 (NUMA), item 7 (resume).

Base SHA for this revision: **`c72d27c6`** (see §7 — the review was
inspected against a stale tree).

Status: **proposal**. Nothing here is implemented.

---

## 0. Consensus summary

The review returned **GO WITH AMENDMENTS on the plan, NO-GO on
implementing ordered streaming under the revision-1 boundedness design.**

That is accepted in full. One claim was added on our side: the review's
deadlock chain applies to **streaming specifically**, and that precision
is what makes the finding decisive rather than merely cautionary — see
§2.1.

| review point | disposition |
|---|---|
| §1 all four dispositions must reach the buffer; don't rewrite `_split_records` globally; gaps are a protocol failure | **accepted** — §2.2 |
| §2 signal-pipe argument proves neither byte-boundedness nor liveness | **accepted** — §2.1, and the decline **stands** |
| §3 ordered-stream test invariants were wrong | **accepted** — §2.3; this was my error |
| §4 spawn is not signature-compatible; `spawn_wid` cannot be reused unchanged | **accepted** — §3.1; my "same signature" claim was wrong |
| §5 splice measurement is circular without a prototype; exactly-once is in scope | **accepted** — §4 |
| §6 decouple map Auto from stream ordering; `FORKRUN_CLEANROOM=1` must not acquire `required` semantics | **accepted** — §5.3 |
| §7 strict-poison decline still present | **resolved** — §7 |

---

## 1. The dependency correction stands

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

### 3.3 Process ownership — the real risk

A SIGKILLed spawn worker orphans its child. Process-group signalling is
necessary but **not sufficient**: the launcher has no `waitpid()`
ownership of grandchildren, so a subreaper arrangement or an explicit
reaping design may be required. Scope the guarantee explicitly — including
what happens to a command that deliberately detaches into its own session.

Cover: worker death mid-batch, recovery and respawn, fail-fast abort, and
**launcher teardown/parent abandonment** — not just the normal path.

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

## 9. Not established by this proposal

* Whether `Auto` is safe for every source kind — the matrix declines
  iterables and several descriptor shapes; the fallback contract applies
  to all of them.
* Anything about NUMA or resume. Both stay declines.
* That ordered streaming is worth shipping if §2.4 cannot be made
  rigorous. The decline is then the correct permanent answer.