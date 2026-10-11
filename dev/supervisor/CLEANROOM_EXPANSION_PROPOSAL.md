# Proposal — expanding cleanroom exec beyond its current envelope

Covers items **1, 2, 4, 5** of the expansion review, re-sequenced per the
"default is `order='index'`, so ordering is a prerequisite" argument.

**Out of scope by request:** item 3 (`mode="python"` parity), item 6
(NUMA), item 7 (resume/checkpoint). Those are named as dependencies
where they block something here, but not planned.

Status: **proposal**. Nothing in it is implemented.

---

## 0. First: one premise in the discussion does not survive the code

The argument was *"default is `orchestrator=True, order='index'`, so
getting `order='index'` working is REQUIRED to make cleanroom exec work on
the default mode."*

That is **true for streaming and false for `map()`**, and the distinction
matters because it changes what item 5 is for.

| | `order="index"` | evidence |
|---|---|---|
| `map()` / collect | **already served** | oracle R4 admits `index`; `test_order_index_takes_cleanroom_and_matches_in_process` proves the launcher is entered and the parent sorts |
| `stream()` | **declined** | oracle R6, `DECLINE_STREAM_ORDER` |

So ordered `map()` is done. Item 5 is *not* a prerequisite for the
default `map()` path — **`mode="python"` (item 3) is.**

What item 5 *is* a prerequisite for is the honest version of "cleanroom as
the default backend": if the default surface includes `stream()`, then
ordered streaming is required before `Auto` can be the default policy.
That is a real goal, and item 5 is genuinely valuable — but it should be
scheduled as **default-surface breadth**, not as an unblocker.

**Revised dependency picture:**

```
item 5 (ordered stream)  ─┐
item 4 (spawn)           ─┼─→ expand the served envelope
item 2b (splice)         ─┘
item 1 (Auto policy)     ──→ deliver it; full form needs item 3
```

---

## 1. What unblocks everything else: the disposition-aware prefix

Before any stage below, one small change to `ReassemblyBuffer` removes
its single worst documented limitation.

`_reassembly.py` says:

> "Gaps (poisoned/skipped batches never emit signals) do NOT stall
> termination … **Mid-stream head-of-line blocking behind a hole is the
> inherent cost of ordered streaming — documented, not fixed (the parent
> has no poisoned-index channel; only a scalar count).**"

That parenthetical was true when written. It is false now. DECISION-02
P5 emits a `POISONED` and a `SKIPPED` record — on the wire, in order, for
exactly those batches.

So the buffer can advance the prefix over a hole the moment it is told
about it, instead of stalling until EOF. Without this, ordered streaming
inherits a head-of-line stall that a single repeatedly-retried early batch
can hold open for the whole run.

**Change:** `add_disposition(batch_idx, disposition)` alongside `add()`;
`drain()` advances past `SKIPPED`/`POISONED` without yielding a payload.
`DATA`/`NO_RESULT` behave as today.

**Gate:** adversarial tests — delayed early batch, poisoned *first* batch
with later batches complete, `None` first batch, empty `b""` first batch.
Each must show the later batches flowing, not waiting for EOF. Falsifiable
by asserting progress *before* the hole resolves.

**This is the highest-leverage item in the plan.** It is small, and it
converts the ordered-streaming item from "implement a reorder engine" into
"reuse a proven one, correctly".

---

## 2. Item 5 — ordered streaming on the cleanroom path

**Why it's cheaper than it looks:** `ReassemblyBuffer` already ships and
already runs the in-process stream path (`run.py:3889`). The work is
plumbing, not invention.

**Scope**

1. Lift oracle R6 / the `_cleanroom_eligible` decline for
   `stream(order="index")`.
2. Route the launcher's drained records — including control dispositions —
   into `ReassemblyBuffer` on the parent side, exactly as the in-process
   stream path does.
3. Extend the buffer per §1.

**The real design question is boundedness, not sorting.** The review was
right that this is the crux, and right that "just sort" is not the answer:

* If batch *k* is slow or retrying and batches *k+1…* complete, the buffer
  grows without bound.
* Simply withholding the drain until *k* arrives converts that into a
  pipeline stall instead.

So the proposal is:

* **Bounded by a byte budget, enforced by backpressure, not by dropping.**
  When the buffer exceeds its budget the parent stops reading the signal
  pipe. That is the existing mechanism — the 16-byte keyed signal pipe
  caps outstanding un-drained completions — so backpressure propagates to
  the workers through signalling, and memory is bounded by construction.
* **Progress argument:** every non-`DATA` batch advances the prefix; a
  `POISONED` batch therefore *cannot* stall indefinitely. The only
  unbounded wait is a genuinely live `DATA` batch, which is bounded by the
  engine's retry limit (poison converts it to `POISONED`).
* **`reassembly_limit`** becomes the enforced cap, not a diagnostic. That
  is a behaviour change to the in-process path too, and should be made
  deliberately and separately.

**Definition of done**

* `stream(order="index")` enters the cleanroom, and the in-process
  results are byte-identical to `mode="none"` reordered.
* Tests: delayed first batch, poisoned first batch, `None` first batch,
  empty first batch, slow consumer (proves backpressure, not unbounded
  growth), retry-then-succeed.
* RSS under a skewed-arrival adversarial run stays within budget.
* Declining loudly remains available if any of the above is not met.

**Risk: moderate.** The backpressure argument is the deliverable, not the
code. If it can't be made, the decline should stand — shipping ordered
streaming with an unbounded buffer would be worse than not shipping it.

---

## 3. Item 4 — `mode="spawn"` in the launcher

`fr_py_worker_spawn_loop` already exists and is parity-tested. The
launcher selects only the plugin and UDF loops. The work is *lifecycle
ownership*, not the loop.

**Why it is more than a fourth function pointer:** spawn runs a **child
process per batch**. Three things the plugin and UDF loops do not have to
reason about:

1. **Command transport.** `spawn_wid` passes `(path, func)` as
   fork-inherited strings. Spawn needs `argv[]` and `argc`. They must
   cross `exec` unambiguously — argv with embedded newlines/NULs is the
   obvious hazard.
2. **Subprocess ownership on worker death.** If a worker is SIGKILLed
   mid-batch, its spawned child is orphaned and keeps running. The
   launcher must reap or signal the whole process group, or a killed
   worker leaks live subprocesses. **This is the main correctness risk in
   this item** and it has no analogue in the other two modes.
3. **Payload failure vs worker death.** Spawn has a genuine
   infrastructure-failure category (`rc < 0` from `fr_py_exec_spawn`: pipe,
   spawn, wait, output) that the other loops do not — already pinned by
   `test_spawn_is_the_only_mode_that_separates_infra_failure`. That
   distinction must survive the move into the launcher's supervision.

**Scope**

1. `--spawn-argv` transport through the launcher, validated before `exec`.
2. Process-group setup for workers; kill/reap the group on abort, respawn
   and fail-fast paths.
3. Select `fr_py_worker_spawn_loop` in the launcher, reusing `spawn_wid`
   unchanged (same signature).
4. Parity tests stay the invariant for the shared lifecycle — the spawn
   loop must not diverge.

**Definition of done**

* Spawn is launcher-served, both supervision policies.
* No orphaned child survives a worker death: test asserts the child is
  gone by PID after the launcher aborts.
* Infra failure still reaches `on_error`, not the death path.
* The parity test still passes unmodified.

---

## 4. Item 2b — measure `splice` before implementing it

`fr_py_worker_splice_loop` exists and is excluded from parity by design
(it moves bytes rather than invoking user code). Measurement first,
implementation only if the numbers justify it.

**Measure:** cleanroom vs in-process wall time and peak parent RSS across
input sizes and worker counts, for the byte-batch path specifically.
Report the break-even point, not a single ratio.

**Decision rule:** implement only if the cleanroom wins at the sizes
callers actually use. A win confined to large inputs is still a win, but
it changes the priority and should be recorded as such.

**Explicitly out of scope:** end-to-end exactly-once for splice. It moves
bytes, has no per-batch subprocess, and is excluded from parity by
design. The launcher's existing generic machinery (drain, framing,
supervision) applies without mode-specific work.

*(Item 2a — `stream(strict_poison=True)` — is already closed in `c72d27c6`:*
*capability was implemented by P2, the eligibility gate was stale, both are*
*now fixed, and the test asserts the launcher is entered rather than just*
*that the call raises.)*

---

## 5. Item 1 — automatic backend selection

**Deliverable:** users stop setting `FORKRUN_CLEANROOM=1`.

**One important scope limit up front:** full `Auto` for the *default* path
requires `mode="python"` (item 3, out of scope here). This stage can make
cleanroom automatic **for the envelope that is already served** — plugin
and UDF, `map()` and `stream()`, both supervision policies, ordered `map()`
— and must not imply the default mode is covered.

**Replace the boolean with three policies**, as the review argues:

| policy | behaviour |
|---|---|
| `auto` (default) | use cleanroom when it can honour the call; otherwise the in-process backend |
| `off` | force in-process; diagnosis and rollback |
| `required` | demand cleanroom and **error** if unsupported — never silently fall back |

The `required` policy is what makes this safe to ship: it is the escape
hatch for anyone who needs to *prove* a call ran cleanroomed, and it
turns "unsupported" from a silent behaviour change into a loud one.

**Staged rollout, each stage independently gated by evidence:**

* **Stage A** — `auto` for plugin and UDF. Measure that results are
  identical to in-process across the existing corpus before defaulting.
* **Stage B** — `auto` for the `map()` envelope including `order="index"`
  and `strict_poison`, once item 5 is in. **This is the stage that
  actually changes what most callers get**, subject to item 3 for
  `mode="python"`.
* **Stage C** — `auto` for spawn, once item 4 is in.

**Fallback safety must be proven, not assumed.** The existing rule —
only confirmed pre-execution launcher failures may fall back — gets a
harder test now that a run may fall back from a *successful-looking*
launcher. Specifically: a launcher that consumed input, or that may have
executed user code, must not fall back to re-running in-process. This is
the CR-FIX1 replay contract and `Auto` puts more weight on it.

**Kill switch:** `off` must be honoured for every stage, and a run that
falls back must say so, once, with the reason — never silently.

---

## 6. Sequencing

| # | Stage | Item | Gate to proceed |
|---|---|---|---|
| 1 | Disposition-aware `ReassemblyBuffer` | §1 | holes no longer stall the prefix |
| 2 | Ordered streaming | 5 | backpressure argument + adversarial tests |
| 3 | Spawn in the launcher | 4 | no orphaned children on worker death |
| 4 | Splice measurement | 2b | measure; implement only if justified |
| 5 | `auto`/`off`/`required` policies | 1 | per-envelope stage gates; replay contract proven |

Stages 3 and 4 are independent of 1–2 and can run in parallel. Stage 5's
Stage B depends on stage 2.

**Sequence 1–2 → 3 → 5 is the path to the biggest user-visible change
within this scope.** Stage 4 is a decision, not a commitment.

---

## 7. Carried-forward items (not planned here)

* **`_RUN_LOCK` under `orchestrator=False`.** The Python dispatch holds
  it around the cleanroom call; the legacy path does not acquire it. That
  concurrency difference is currently incidental. It should be declared
  intentional or removed before `Auto` multiplies the paths that take it.
* **CPython matrix.** The UDF helper is verified on 3.14.7 only. `Auto`
  must key the UDF route on a *verified* minor, or it will offer a helper
  built against an untested interpreter. This is a release gate on stage
  5, not a research item.
* **Non-representable callables.** A closure cannot cross `exec`. This
  belongs to item 3's contract, but `Auto` must reject before input is
  consumed — never discover it mid-run.

## 8. What this proposal does not establish

* Whether `Auto` is safe for every source kind. The matrix declines
  iterables and several descriptor shapes; `Auto` inherits those
  refusals and the fallback contract applies to all of them.
* Anything about NUMA or resume. Both stay declines.
* That ordered streaming is worth shipping if the backpressure argument
  cannot be made rigorous. In that case the decline stands.