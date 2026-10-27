# Round 9 — response to the round-8 review

> **RESPONDED TO — see `REVIEW_REQUEST_ROUND10.md`.** All four items the
> round-9 review asked to be resolved are addressed. Retained as the
> record; note that two claims in §1 here were themselves wrong — the
> `map()` conflict check did not exist, and the round-9 NUMA wording
> still implied distinct worker slots.

Branch `NEW/REFACTOR4.2`. Review the **branch head**; `6284aa67` is the
last commit the round-8 request pinned, and the response commits follow
it. Frozen ring files (`forkrun_ring.c`, `forkrun_substrate.h`,
`substratestubs.c`) untouched across `c72d27c6..HEAD`.

Round-8 findings: **all three blocking grounds addressed**, plus the
follow-ups. Every finding below was **reproduced before being fixed** —
none was taken on faith.

---

## 1. Blocking — `conflicts()`: both halves confirmed and fixed

### 1a. A duplicate after delivery escaped detection AND was emitted

Reproduced exactly as described:

```
drain 1:        [(0, b'FIRST')]
conflicts:      {}
final_drain:    [(0, b'SECOND')]      <- a duplicate
```

`drain()` removes the payload from `_buffer` and advances `_next_idx`,
so by the time a duplicate arrives there is neither a pending DATA nor a
pending terminal marker, and `add()` re-buffered the stale index.
**The buffer published duplicate output through a policy whose entire
stated content is first-wins.** This was a real correctness bug, not a
missing diagnostic.

Fixed with a `_consumed_upto` watermark, advanced at **delivery** —
before the yield, since the consumer holds the payload the moment the
yield returns. Advancing after would leave a window in which a
re-submission looks like new work. Any outcome below the watermark is
recorded as a conflict and refused.

The guard is **repeated in `final_drain()`**, the last gate before a
payload reaches a caller and the exact path the duplicate escaped
through. Belt and braces deliberately: not every route to `final_drain`
goes via `add_disposition`.

### 1b. No production caller consulted `conflicts()`

Confirmed: `conflicts()` was written, documented as "a caller can
refuse the result", and read by nothing in production. The policy was
**record-and-ignore**.

Added `ForkrunProtocolError` (a `RuntimeError` subclass, so existing
`except RuntimeError` callers keep working) carrying `.conflicts`
(batch_idx → descriptions), and a shared `_raise_on_disposition_conflicts()`
now called by **both** consumers:

* `map()` — after `final_drain`, before the result is returned. Nothing
  is handed back.
* `stream()` — at detection, because already-yielded records cannot be
  retracted. The message says so rather than letting a contradictory
  stream complete successfully.

Six new tests, including a regression that legitimate **out-of-order**
arrival (5 before 2) is still buffered and drained in order rather than
flagged.

## 2. Blocking — C0.6 harness: both confirmed and fixed

### 2a. The discard rule was documented but not enforced

`cell()` collected failures and returned whenever *any* trial succeeded —
`if not good`. A configuration requested with 3 trials could publish on
the strength of 1, and the sample count was never shown.

Not hypothetical: the published minimum speedup was **1.05x**, close
enough to parity that the sample it rests on should be the one asked
for. A partial sample is also **biased by construction** — the trials
dropped are the failing ones, so survivors skew favourable.

Now published only if `len(good) == trials`, with the count printed per
row. **Re-measured under the enforced rule: all 56 configurations pass
with full n=3 samples.** The conclusion stands; it now rests on the
data requested.

### 2b. USS was miscalculated; peak RSS was reported as current

`read_mem_self()` ignored `Private_Clean` entirely and accumulated into
a value initialised to **-1** — so the sum started a kilobyte below zero
*and* omitted the whole private-clean category, which is large for a
file-backed library mapped MAP_PRIVATE. It also seeded `rss_kb` from
`ru_maxrss` then overwrote it with the current `Rss:` from
smaps_rollup, so the field documented as peak was **current on every
modern kernel**.

Now sums `Private_Clean + Private_Dirty + Private_Hugetlb` from zero
and reports `parent_rss_cur_kb` and `parent_rss_peak_kb` separately.
Verified: USS 263699 → 263752 kB at the 256 MB point.

Neither defect bears on which candidate is faster. Both mattered for the
memory claims.

**Re-measured:** pre-fork faster on **56/56**; speedup min 1.05x, median
3.77x, max 11.00x, decaying ~3.5x across the parent-RSS axis
(5.69x at 0 MB → 1.59x at 2127 MB). Documented that the decay is
monotonic except at 256 MB, which is within run-to-run noise at 3
trials — the endpoint trend is the claim, not every step.

## 3. Blocking — NUMA non-vacuity

### 3a. Fault-injection assertions added (5 tests)

Five integration tests installed a self-killing payload and compared
output against a healthy run **without asserting the injection fired**.
If it stopped firing, the "crash" run was a healthy run and every
comparison passed for the wrong reason.

Added `_assert_injection_fired()` and `_assert_deaths_occurred()`.

**A process note worth the reviewer's attention:** my first attempt used
`addCleanup`, which runs *after* the test's own
`finally: rmtree(plugin_dir)` — so the marker directory was already gone
and the assertion failed. That briefly looked like the reviewer's
hypothesis confirmed (injection never fires). **It does fire** —
verified directly. The defect being fixed is the missing *proof*, not a
broken injection. Assertions are now inline, immediately after the run.

`_assert_deaths_occurred` checks **distinct** deaths, not just a count:
one worker dying twice satisfies a bare count without exercising the
escrow routing a second *worker's* death does.

### 3b. Tautology removed

`assertEqual(wid_to_node(4, 2), wid_to_node(4, 2))` claimed "a respawned
wid keeps its node", but `wid_to_node` is **pure** — calling it twice
with the same arguments returns the same list regardless of runtime
behaviour. It asserted that Python can call a function twice. Removed,
with a comment naming where the property is actually established:
`test_respawn_on_correct_node`, which observes a real replacement.

### 3c. One claim narrowed to what is checkable

`test_respawn_on_correct_node` is named for node placement, but a
payload inside a worker has no access to its node — `Batch` exposes
neither node nor wid, and under forced-logical there is no physical
binding to observe. The test now claims "several distinct workers died
and all their work was recovered", and says so, rather than asserting
per-node attribution it cannot make.

## 4. Stage 4 — the histogram was not an integrity check

Confirmed, and it is real:

```
sorted(got[::-1]) == sorted(want)   -> True
```

`sorted(got) == sorted(want)` compares the **frequency of each byte
value**. It is a histogram, so it survives any permutation including a
full reversal — a batch assembled backwards passes it.

Replaced with **record tiling**: every emitted record must be a
contiguous slice of the expected output, and those slices must cover
`[0, len(want))` exactly once — no gap, no overlap, no duplication, in
whatever order they arrived. Verified to accept a correct out-of-order
tiling and to reject a reversed batch (which the histogram accepted), a
dropped batch and a duplicated batch.

Added a byte-exact **ordered validation run** (`order="index"`) that
executes before any timing and **aborts the benchmark** if the pipeline
is not correct. The strong claim lives there; tiling is the
order-appropriate weaker form for the unordered timed runs. That split
is the reviewer's recommendation.

Pinned with ten tests (`test_bench_integrity.py`) so it cannot weaken
back.

### Framing corrected

Agreed and fixed. The recommendation read as though the measurement had
tested launcher-splice and rejected it. It did not. What was measured is
that a direct byte-moving path beats invoking a **no-op** command
(`spawn cat`) by ~10x. That supports keeping the loop; it says nothing
about a launcher-splice integration, because none exists and none was
benchmarked.

Restated as a **scope and maintenance decision**, with the two things
the measurement does support named, plus the instruction that if
launcher-splice is ever wanted it must be prototyped and measured under
the workload that motivates it.

Also corrected: `PARITY_WITH_BASH.md` claimed §7.3.3 "independently
confirms" the Stage 4 decision. **Withdrawn** — §7.3.3 says compare line
multisets or joined bytes across NUMA runs; it says nothing about a
byte-value histogram, and would never have sanctioned one.

## 5. Oracle — agreed, and now stated precisely

The oracle is **implementation-independent, not specification-
independent.** Its rules live in a separate module with per-rule links
to the normative documentation, which makes 20160/20160 agreement real
evidence against drift, missing restrictions and precedence
regressions. But both encodings were authored in the same project from
the same reading, so **a mistaken contract produces perfect
agreement.**

It is a differential conformance test against the eligibility contract,
not a proof that the contract captures every user-facing requirement.
The complementary safeguard is a separate review of the contract itself
— which is what the public-dispatch and parity tests serve, and why
they are a complement rather than a redundancy.

## 6. Parity — confirmed, and fixed

`TestParityIsNotVacuous` recorded that `_execute_cleanroom` was
**called** and asserted the list was nonempty. But:

```python
out = _execute_cleanroom(...)
if out is not None:
    return _map_return(out, return_stats)
```

A `None` return — launcher unavailable, or a failure the policy allows
falling back from — silently continues to the in-process executor, and
**every output-parity assertion downstream passes while comparing two
in-process runs.** Recording the call proved the wrapper was *reached*,
not that the launcher *served* the run.

Each entry now carries `served: out is not None` and the cleanroom arm
asserts it for every batch.

Added `test_spawn_cases_carry_the_expected_argv`, because output parity
alone cannot distinguish `tr a-z A-Z` from a command that uppercased by
some other route. It compares `argv[1:]` exactly and `argv[0]` by
basename — the launcher receives an **absolute** argv[0], which is
correct and necessary, because the child scrubs its environment and a
bare `cat` would have no PATH. Writing the assertion without accounting
for that made it fail on a correct run, which is how the resolution
behaviour got pinned down.

**`spawn-sh-argv` fixed.** It was `"sh -c wc\ -c"` with `expected=None`:
`str.split()` does no shell parsing (`make_spawn_payload` documents
this), so it rendered as `['sh','-c','wc\\','-c']` — a different
command — and with no expected output and `on_error="skip"` it passed by
producing nothing at all. Now a **list** payload
`["sh","-c","tr a-z A-Z"]` with a real checkable expectation, and every
launcher case carries some positive success condition.

## 7. Follow-ups done

**Stage 1 results-pipe integration test.** The existing
`test_ordered_results_pipe_advances_past_a_terminal_before_eof` drives
`_split_records_terminal()` and `ReassemblyBuffer` directly — proving the
primitives work, not that the *wiring* calling them does. The round-7
pump change was never exercised. New test drives `_make_results_pump`
over a real pipe and asserts batch 1 is emitted past batch 0's terminal
outcome **while the writer still holds the pipe open**.

**Mutation-checked:** reverting the pump to DATA-only parsing makes it
ERROR; restoring makes it pass. It has teeth.

**`test_reactor.py:198`** — `assertEqual(len(res), len(healthy) - 1)` says
one blob is missing but not *which*; a run that dropped batch 500 and
kept batch 0 passes identically. Now asserts content: exactly the first
healthy record is absent, every other record arrives byte-identical and
in order.

**`test_reactor.py:367`** — `assertLess(len(res), len(healthy))` also
satisfies any truncation, lost batch or early exit, and never checks the
user was **told**. A silently-skipping poison pill would pass. Now
asserts the poison warning reaches fd 2 (captured by redirecting fd 2 to
a memfd, so a stray `UserWarning` cannot satisfy it and C-level writes
are covered), and that surviving content is the healthy content minus
whole records — dropped, never altered.

**Truncated-tail wording** corrected as suggested. The
`_make_results_pump` docstring said "never user data"; too strong, since
RESILIENCE §2.2 states rollback is guarded by `S_ISREG` and pipes
downgrade to at-least-once. Restated as what is true: the tail is
dropped because it is an incomplete **frame**, not because it is
provably not user data. Runtime behaviour unchanged; the *claim* was what
was wrong.

## 8. Still open — unchanged

| # | item | status |
|---|---|---|
| 1 | C0.5 matrix (3.10–3.15) | only 3.14.7 installed |
| 2 | C0.6 children's PSS/USS | parent now correct; children unmeasured |
| 3 | Physical NUMA | needs real hardware or `numa=fake=N` boot |
| 4 | Two orderers (splice uses Python `ReassemblyBuffer`) | ~0 measured cost; causes `map(order="index")` to serve while `stream(order="index")` declines |
| 5 | Ordered streaming | declined; bounded-memory/liveness design absent |
| 6 | `Auto` / `mode="python"` parity | W-EXP-1, gated on C0.6 + packaging |
| 7 | Sanitizer matrix | not run for this work |
| 8 | UDF auto-routing | gated on the C0.5 matrix |

Item 4 remains the largest standing deviation from the parity-with-bash
principle. The near-zero measured cost does not resolve the maintenance
and semantics divergence; it only means there is no urgency.

## 9. What I would most like challenged now

1. **The streaming conflict boundary.** Records already yielded cannot
   be retracted, so `stream()` raises at detection and says so. Is
   raising mid-stream better than collecting and failing at the end, or
   worse?
2. **Tiling vs histogram as the Stage 4 invariant.** Tiling is strictly
   stronger and order-free. Is there a workload where it is *too*
   strict — legitimate deduplication or overlapping batches?
3. **Relaxing the NUMA guard.** Still the change most open to challenge:
   I removed a physical-hardware guard over forced-logical tests. My
   reasoning is that `test_numa_bump.py` already establishes the
   mechanism is host-independent. A reviewer could argue I weakened a
   guard until tests ran.
4. **Whether the round-8 findings suggest a process change rather than
   more tests.** Five rounds, five defects, and every one was an
   assertion that could not fail. Adding a tenth test does not address
   that; the only thing that did was checking the specification.