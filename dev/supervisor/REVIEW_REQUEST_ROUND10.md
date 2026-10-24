# Round 10 — response to the round-9 review

> **SUPERSEDED — see `REVIEW_REQUEST_ROUND11.md`**, a focused request on
> the C0.5 security surface (`scrub_inherited_path`, `FR_UDF_HOME`),
> which is new product code with no tests.

Branch `NEW/REFACTOR4.2`. Review the **branch head**; `c11de09f` is the
last commit the round-9 request pinned. Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across `c72d27c6..HEAD`.

All four items the reviewer asked me to resolve before closing round 9
are addressed. Every finding was **reproduced before being fixed**, and
two of my own corrections were themselves wrong on the first attempt —
recorded below rather than smoothed over.

---

## 1. Blocking — disposition conflicts: the wiring was incomplete, and my map claim was false

The reviewer is right on both counts, and the second is worse than the
first.

### 1a. The C-drain pump never checked

`_make_results_pump()` drove `add_disposition()` in `_ingest()` and
`final_drain()` at EOF, and consulted `conflicts()` at **neither**. That
pump serves the materialized-stream, ingest-stream, reactor-stream and
NUMA-stream paths. Contradictions there were recorded and ignored.

Now checked at **ingest, before `drain()`** — so a detected
contradiction releases no further output — and again at **EOF**, for a
contradiction whose second outcome arrives in the final chunk.

### 1b. Two more routes also finalised without checking

`_execute_ingest_stream_reactor` and `_execute_numa_stream` each build a
`ReassemblyBuffer` and finalise it. Neither consulted `conflicts()`. Both
now check.

All five sites that construct a `ReassemblyBuffer` are covered:

| site | check |
|---|---|
| `_drain_records` | end of drain (relabelled, see below) |
| `_make_results_pump` | ingest + EOF |
| `_execute_streaming_reactor` | finalisation |
| `_execute_ingest_stream_reactor` | finalisation |
| `_execute_numa_stream` | finalisation |

### 1c. The `map()` claim was wrong

The round-9 response said: *"map() — after final_drain, before the
result is returned."* **There is no such call site.**
`_drain_records()` is called only from `_execute_streaming()` and
`_execute_ingest_stream()`, both generator paths; the single check was
inside it, mislabelled `"map()"`.

And `map()` **never constructs a `ReassemblyBuffer` at all.** Its
`order="index"` path uses the C orderer (`use_orderer`), which merges by
`(major, minor)` and emits only records that exist — so a skipped or
poisoned batch produces no record there, and no contradiction can arise.

So there is no `map()` hook, and claiming one was wrong. Relabelled
`"stream()"`, and the helper's docstring now states plainly that `map()`
has no buffer to refuse and why. The mechanism is documented rather than
papered over.

### 1d. Three production-path tests, each mutation-checked

Not the helper — the pump, over a real pipe:

* contradiction delivered **midstream** while the writer holds the pipe
  open → `ForkrunProtocolError`, offending index named, no further output
  released;
* the EOF variant;
* a **stale payload surfacing only at `final_drain`**.

**Mutation-checked, and the second check found a real gap.** Removing the
ingest check fails the first test. But removing the **EOF** check left
my first EOF test **passing** — it was being caught by the ingest check
and was not testing what it claimed. Replaced with one that constructs
the state only `final_drain` can observe, and that one does fail when
the EOF check is removed.

## 2. Blocking — the `test_reactor` ordering assumption

Confirmed. Neither `map()` call passed `order`, so both used
`order="none"`, where output is **completion order**. My strengthened
assertion read `healthy_recs[0]` as batch 0 and compared
`healthy_recs[1:] == res_recs` — treating a **list position as a batch
identity**, which `order="none"` does not license and which a worker
crash can change.

Fixed by passing `order="index"` explicitly to both runs, so "the first
record is batch 0" is a **promise** rather than an assumption. Four
consecutive runs green.

This makes the test stronger, not weaker: under `order="index"` a
permanently-unrecoverable batch 0 is a hole, so the run completes by
flushing at final drain — the documented behaviour, now actually checked.

## 3. NUMA — narrowed to what is observed

### 3a. Distinct PIDs are not distinct worker slots

`_assert_deaths_occurred` counts pid-named markers. That proves distinct
**processes** died; one slot can die, respawn under a new pid, and die
again. Claim narrowed to "several distinct process generations died and
the run still recovered its expected output". Per-slot identity would
need supervisor instrumentation recording `wid` and generation — which
does not exist.

### 3b. The stale name and claim

`test_respawn_on_correct_node` → **`test_multiple_process_deaths_all_recover`**,
docstring rewritten. The old docstring claimed deaths "across both nodes"
and a respawn "pinned to the wrong node"; neither is observable, for the
reason in 3a.

### 3c. `finally` masking

`_assert_injection_fired` moved **out of** the `finally` in
`test_numa_stream_recovery`, so it cannot replace the original stream
exception with "marker missing".

## 4. Poison test — strengthened, and it had a hidden weakness

### 4a. The content check was vacuous

The payload raised for **every** batch, so the result was empty and
`set(got_lines) <= set(healthy_lines)` was trivially true of the empty
set. It established nothing about surviving content, and an early abort
after the warning would have satisfied it.

Now fails only **even** batch indices, so real output survives. The test
asserts surviving content is a proper subset of healthy, is non-empty,
and that **more than 40% survived** — a token remnant, which is the
early-abort shape, now fails.

### 4b. The notification assertion had a subtler problem

`assertIn("poison", stderr)` passed with **every** "Skipping poisoned
batch" message silenced — because the run also prints `N poisoned
batch(es) skipped` and a POISONED BATCH SUMMARY. The assertion was
satisfiable without the notification it was about.

Now pinned by regex to `\[WARN\]: Skipping poisoned batch \d+`.

### 4c. Two of my own mutations were wrong

Worth recording, because I initially read them as "the assertion cannot
fail":

1. Silencing one of four `fprintf` sites in `_shim.c` — no effect; other
   sites still emitted.
2. Silencing **all four** — still no effect, because this test runs
   `mode="python"` and the message comes from **`_worker.py:549`**, not
   the C shim. I concluded the assertion was weak. The assertion was
   fine; the mutation targeted the wrong implementation.
3. Mutating the actual emitter fails the test, as it should.

The lesson is the mirror of the ones already recorded: **before
concluding a test cannot fail, confirm the mutation reached the code the
test exercises.** The honest conclusion was "cannot fail *against the
shim*", which is much less alarming and more actionable than "vacuous".

## 5. Process — the reviewer's recommendation adopted

`dev/supervisor/EVIDENCE_CHAIN.md`. Six steps every significant claim
must walk: **Contract → Route → Event → Invariant → Negative control →
Report scope**, answering *"what specific incorrect implementation would
make this test fail?"*

I agree this is a process change rather than more tests, and I think it
is the most valuable thing in this round. The document includes a status
table that is honest about two partial rows: NUMA worker-slot identity
has no instrumentation for step 3 (claim narrowed instead of asserted),
and NUMA recovery has no practical negative control without touching the
frozen ring.

It also records the mutation trap from §4c, since that failure mode will
otherwise recur: *a negative control that does not fail usually means the
mutation missed.*

## 6. Accepted, with one scope note added

Stage 4 tiling and the no-wire scope decision are accepted. The scope
caveat the reviewer asked to be stated precisely is now in
`_records_tile()`'s docstring and in `STAGE0_PUBLICATION_PROTOCOL.md`:

> empty records are ignored, so this is **byte-stream integrity** — not
> an exact emitted-record count, and **not** batch-level exactly-once
> evidence. For `splice`/`cat`/`tr` (one-to-one byte maps) that is
> precisely the right invariant; a deduplicating or overlapping workload
> needs a different oracle rather than a weakened one.

C0.6 and the oracle framing are accepted as they stand.

## 7. Still open — unchanged

| # | item | status |
|---|---|---|
| 1 | C0.5 matrix (3.10–3.15) | only 3.14.7 installed |
| 2 | C0.6 children's PSS/USS | parent metrics now correct; children unmeasured |
| 3 | Physical NUMA (locality, cross-socket, bandwidth) | needs real hardware or `numa=fake=N` boot |
| 4 | Two orderers (splice uses Python `ReassemblyBuffer`) | ~0 measured cost; causes `map(order="index")` to serve while `stream(order="index")` declines |
| 5 | Ordered streaming | declined; bounded-memory/liveness design absent |
| 6 | `Auto` / `mode="python"` parity | W-EXP-1, gated on C0.6 + packaging |
| 7 | Sanitizer matrix | not run for this work |
| 8 | UDF auto-routing | gated on the C0.5 matrix |
| 9 | NUMA worker-slot/node instrumentation | new; would need supervisor support |

Item 4 remains the largest standing deviation from parity-with-bash.
The near-zero measured cost does not resolve the maintenance and
semantics divergence; it means there is no urgency.

## 8. Verification of this response

| | |
|---|---|
| Python suite | **1002 tests**, 0 unexpected failures, 2 skipped |
| `UNIT_TESTS/test_frun.sh` | 96/96 |
| `python/release_check.py` | ALL CHECKS PASSED, clean tree |
| Frozen ring | untouched across `c72d27c6..HEAD` |
| NUMA suites | 54 green |
| Mutation checks added this round | 3 (results-pump ingest, results-pump EOF, poison emitter) |

## 9. What I would most like challenged

1. **Is `ForkrunProtocolError` the right failure mode for `map()`-like
   collected results — given `map()` has no buffer and so no check?** I
   believe the answer is yes (map uses the C orderer, which cannot
   contradict itself), but that is an argument, not a demonstration.
2. **Is raising mid-stream better than failing at EOF for the reactor
   paths?** I implemented the reviewer's advice (raise at detection). For
   a long-running stream, an immediate abort on an internal invariant may
   be worse than finishing and reporting. I have not argued this
   through.
3. **Does the evidence chain actually scale?** Six steps per claim is
   real friction. If it slows the work enough that claims stop being
   written down, it has failed.
4. **The two-orderer deviation (item 4).** Six rounds have left it open on
   the grounds that cost is ~0. Is that the right call, or is deferring a
   known parity violation repeatedly the wrong default?