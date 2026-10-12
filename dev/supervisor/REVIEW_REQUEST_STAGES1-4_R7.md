# Review request — round 7: response to the Stage 1–4 review

Branch `NEW/REFACTOR4.2`, head **`a258defe`**. Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across `c72d27c6..HEAD`.

**958 tests, 0 failures, 9 skipped.**
`python/release_check.py` → `ALL CHECKS PASSED` on a clean tree.

---

## 1. The headline finding, confirmed

The review was right, and it was larger than reported.

> `mode="spawn"` is not routed through the launcher by the public `map()`
> API.

`_cleanroom_eligible` admitted spawn, but the `map()` gate condition
never tested for it, so the eligibility verdict was computed and then
thrown away. Every public `map(mode="spawn")` call fell through to the
ordinary in-process executor.

Two consequences, both now fixed:

* **The benchmark was measuring the wrong thing.** Stage 4 compared
  in-process splice against ordinary in-process spawn, while labelling
  the baseline "launcher-spawn". The rows were not wrong arithmetic —
  they were a comparison against the wrong control.
* **A live product bug.** Wiring the dispatch exposed
  `AttributeError: 'list' object has no attribute 'rpartition'` at
  `run.py:3390`. The plugin-spec parse ran unconditionally, but a spawn
  payload is an ARGV **list**; only `plugin` and `udf` carry a
  `"path:function"` spec.

That second one is the more important finding. The public spawn path was
**broken for every caller** — not merely slower — while the capability
matrix and the Stage 3 launcher tests were both green. The tests agreed
with the oracle because both were exercising the in-process path that
`mode="spawn"` was actually taking. This is recorded in
`STAGE0_PUBLICATION_PROTOCOL.md` as the argument for validating bytes
rather than counts.

## 2. Findings addressed

| # | review finding | fix | evidence |
|---|---|---|---|
| 1 | spawn not dispatched from public API | gate includes spawn; argv extracted, validated, passed through | `test_stage3_public_dispatch.py` (5 tests) |
| 2 | `stream(mode="spawn")` undefined | declines explicitly, falls back in-process, reason pinned in oracle | oracle agrees on all 20160 cells |
| 3 | Stage 4 timed wrong baseline | harness forces `FORKRUN_CLEANROOM=1`; ratios rebuilt | §3 |
| 4 | benchmark output never validated | byte-multiset check on every trial; failed/empty trial discards the config | harness |
| 5 | matrix ceiling does not detect a lost guard | 5% → 2%, with the arithmetic asserted | `test_capability_matrix.py` |
| 6 | contradictory terminal outcomes silently absorbed | recorded, exposed via `conflicts()` | `test_stage1_reassembly.py` (5 new) |
| 7 | setsid test did not kill the worker | worker killed before asserting escape survival | `test_stage3_lifecycle.py` |
| 8 | teardown test had no signal handler | live SIGTERM; handler kills worker groups | `test_stage3_lifecycle.py` |

## 3. Stage 4, corrected

Every trial now validates its own output; any failure discards the whole
configuration rather than contributing a median.

| input | workers | splice+c_drain | splice+py_drain | spawn cat | ratio |
|---|---|---|---|---|---|
| 2.6 MB | 1 | 0.0137s | 0.0119s | 0.0650s | 4.7x / 5.5x |
| 2.6 MB | 4 | 0.0289s | 0.0270s | 0.0650s | 2.2x / 2.4x |
| 26.5 MB | 1 | 0.0596s | 0.0564s | 0.5801s | 9.7x / 10.3x |
| 26.5 MB | 4 | 0.0558s | 0.0469s | 0.1841s | 3.3x / 3.9x |

The ratio came **down** from the previously reported 11.7x. That is the
correct direction: the old baseline was an in-process run that was faster
than a real launcher, so it flattered splice. The conclusion is
unchanged — retain the loop, do not wire it into the launcher — but it
now rests on the right measurement.

Peak parent RSS is flat (~94–95 MB) across all variants, so the gain is
throughput, not memory.

## 4. Invariant chosen for benchmark output, and why

Output is compared as a **byte multiset**. Both simpler invariants are
wrong here, and finding out why was most of the work:

* **Concatenation** — with `order="none"` and >1 worker, batches
  complete out of order by design. This "fails" a correct 26.5 MB run on
  ordering alone, and would teach us to distrust a correct pipeline.
* **Line splitting** — splice moves *bytes*, and a 32768-byte batch does
  not align to line boundaries. It reported 500001 lines where the input
  has 500000.

The multiset asks only what a throughput benchmark should ask: every byte
arrived, none invented. **Ordering is a separate promise**, covered by
the `order="index"` suites, and is not claimed by this harness.

## 5. A note on the meta-finding

Two of the fixes this round were tests that could not fail:

* the mutation test intended to justify the 2% ceiling patched
  `_cleanroom_eligible` and the patch **silently did not take** — it
  measured the unmutated matrix and passed for the wrong reason. It is
  now a direct arithmetic assertion, with the failure recorded;
* the original teardown test sent SIGTERM to a launcher with **no signal
  handler**, so it exercised nothing.

Both were green before this round. The general rule this suggests, and
the reason the byte-level validation matters more than its own bugfix: a
suite that agrees with an oracle built from the same assumption is one
assumption from being wrong. The oracle-agreement test is still worth
having, but it cannot be the only thing watching.

## 6. Still open (unchanged, not regressed)

* **Ordered streaming** declined — bounded-memory/liveness design absent.
* **`Auto` rollout** gated on per-envelope correctness + performance.
* **Full default `Auto`** blocked on `mode="python"` parity (item 3).
* **Automatic UDF routing** gated on CPython 3.10–3.15; only 3.14.7 proven.
* **NUMA (6) and resume (7)** future work; NUMA needs suitable hardware.

## 7. What I would most like challenged

1. Is the byte-multiset invariant sufficient for a Stage 4 verdict, or
   does a go/no-go here need ordering evidence as well? I argued no, on
   the grounds that the harness does not claim ordering — but a reviewer
   may reasonably say a throughput number on unvalidated ordering is not
   a decision.
2. `conflicts()` records contradictions rather than raising. The caller
   is a streaming loop that has already consumed real input, so raising
   converts a protocol defect into a lost run. Is "record and let the
   caller refuse" the right boundary, or should the default be fail-closed?
3. The oracle now agrees on 20160/20160 cells. Is a generated oracle built
   from the documented contract a genuine second opinion, or an elaborate
   restatement of the same reading?
