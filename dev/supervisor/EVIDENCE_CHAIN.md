# The evidence chain — what every significant claim must show

Adopted from the round-9 review, which argued that five rounds of "the
assertion passed but the intended condition was never established" call
for a process change rather than more tests. This is that change.

The question a test must answer is not "does it pass?" but:

> **What specific incorrect implementation would make this test fail?**

If that has no answer, the test is decoration. Every significant
correctness claim in this project should be able to walk these six steps
and name its evidence.

---

## The six steps

### 1. Contract
Name the normative rule, and where bash provides the reference
mechanism, the relevant bash implementation.

*Example:* batch atomicity is `RESILIENCE_PROTOCOL.md` §2.2 (rollback via
the transaction cursor) and §5.2 (mode-dependent delivery guarantees).
The `frun.bash` reclaim path is the reference.

**Why this step exists.** Every false alarm in this project came from
asserting something the contract does not say, or asserting something it
does say without reading it: B-01 (byte-exactness asserted under
`skip`, which drops the failed batch by contract), the recovery test
(order="none" joined bytes), the parity test (argv[0] assumed relative).
Three of five rounds.

### 2. Route
Show the test reaches the intended **production route**, not a
predicate, a wrapper, or a plausible output.

*Example:* `TestParityIsNotVacuous` counts calls into
`_execute_cleanroom` **and asserts `served: out is not None`** — because
the dispatch site is `if out is not None:`, so a recorded call proves the
wrapper was reached, not that the launcher served the run.

**Why.** Two rounds in a row shipped a fix whose test passed because the
output was right, produced by the wrong engine.

### 3. Event
Assert the intended event actually happened — a worker death, a
successful launcher service, a poison notification, a logical-node
recovery — rather than that the run completed.

*Example:* the NUMA integration tests assert the `.dead` marker exists.
If the injection stops firing, the "crash" run is a healthy run and every
output comparison passes.

**Why.** A run that completes is compatible with a run in which nothing
happened.

### 4. Invariant
Assert the promised semantics, and only those:
ordered output **only** where ordering is promised, full byte coverage
for copy workloads, policy-correct omissions for `skip`/poison.

*Example:* the Stage 4 harness checks **record tiling** — every record a
contiguous slice, the slices covering the output exactly once — because
`sorted(got) == sorted(want)` is a byte histogram and passes a reversed
output. Tiling deliberately asserts nothing about arrival order, which
`order="none"` does not promise.

**Why.** "Stronger-sounding assertion on an unstated assumption" has
appeared in three separate rounds, including twice in round 9 itself.

### 5. Negative control
Where practical, deliberately remove or bypass the mechanism and show
the test fails.

*Example:* reverting the results pump to DATA-only parsing makes the
Stage 1 integration test error. Silencing `_worker.py`'s poison warning
makes the poison test fail.

**Why.** Only a mutation distinguishes "this test covers the mechanism"
from "this test covers something nearby".

**And the trap.** A negative control that does not fail is ambiguous, and
the ambiguity usually means the mutation missed. In round 9 the poison
test "passed" under three successive mutations — two of which targeted
`forkrun/_shim.c` while the test exercises `mode="python"`, whose warning
comes from `_worker.py`. The conclusion "this assertion cannot fail" was
wrong; the conclusion "this assertion cannot fail **against the shim**"
was true and much less alarming. Before concluding a test is vacuous,
confirm the mutation reached the code the test runs.

### 6. Report scope
State what remains unproven, explicitly — especially where a
forced-logical test is not a physical-NUMA test, or a benchmark
invariant is weaker than exactly-once record publication.

*Examples, all currently live:*
- Forced-logical NUMA coverage is not physical-locality coverage.
- `_records_tile()` **ignores empty records**, so it proves byte-stream
  integrity, **not** exact batch count or batch-level exactly-once.
- C0.6 covers CPython 3.14.7 only; the children��� fleet PSS/USS is
  unmeasured.
- "Do not wire splice into the launcher" is a scope decision; no
  launcher-splice integration was benchmarked.

**Why.** An unstated limitation is discovered by a reviewer as a defect,
which costs the credibility the claim was borrowing.

---

## Applying it

For a new significant claim, the review request should carry these six
lines. It is deliberately short: the point is not more process, it is
making the *gap between the assertion and the guarantee* visible while
the gap is still cheap to close.

A claim that cannot complete step 5 (no practical negative control) is
not disqualified — it says so at step 6 instead.

## Status of the existing claims

| claim | 1 contract | 2 route | 3 event | 4 invariant | 5 negative | 6 scope |
|---|---|---|---|---|---|---|
| engine parity (launcher vs in-process) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Stage 4 tiling invariant | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (empty records) |
| poison notification + selective skip | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| batch atomicity across worker death | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| spawn-streaming recovery | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| NUMA forced-logical recovery | ✓ | ✓ | ✓ | — | — | ✓ (physical NUMA open) |
| NUMA worker-slot/node identity | — | — | — | — | — | ✓ (claim narrowed) |
| C0.6 pre-fork lifecycle | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (3.14.7 only) |
| capability matrix vs oracle | ✓ | ✓ | — | ✓ | ✓ | ✓ (not spec-independent) |
| disposition-conflict refusal | ✓ | ✓ | ✓ | ✓ | ✓ | — |

The two partial rows are the honest ones. NUMA worker-slot identity has
**no** instrumentation to build step 3 on, so the claim was narrowed
rather than asserted. NUMA recovery has no practical negative control
without engine changes to the frozen ring.