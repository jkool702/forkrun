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

## 3b. Round 8: two review items completed, and a new engine bug found

The round-7 handoff listed two items as outstanding — **recovery output
integrity** and **in-process/cleanroom parity**. Both are now done, and
implementing them exposed a serious engine-level defect.

### Parity (`python/tests/test_stage3_parity.py`)

Asserts the launcher and the in-process executor produce identical bytes,
across argv shapes, worker counts, and both fresh interpreters and one
shared one. Determinism is asserted *before* parity on purpose: without
it a mismatch has two possible causes and the failure names the wrong one.

The first version of this file passed `"cat"` with `mode="plugin"` and
got 33 subTest errors, because plugin takes a `path:function` spec and is
not a shell command.

### A guard that immediately earned its keep

`TestParityIsNotVacuous` counts calls into `_execute_cleanroom` and
asserts the cleanroom arm reaches it. It failed on the first run — and
found that **public `map(mode="spawn")` still did not reach the
launcher.** Two stacked causes:

1. `_c_spawn_spec` reads the argv off the *function*, but the call site
   passed the `(fn, engine_mode)` tuple, so `getattr` returned `None`,
   the launcher branch was dead code, and every public spawn call fell
   through in-process.
2. With the branch live, the launcher still died at exit 127. The cause
   was `--plugin None --func None` being sent for spawn — the launcher
   `dlopen`ed the literal string `"None"` and died in the spill child.

Note the shape: round 7 shipped a fix and a test
(`test_map_spawn_routes_through_the_launcher`) that passed, because the
test could only observe that the *output* was right. Both rounds in a row
the failure mode was the same — correct results from the wrong engine.

**Also required a rebuild.** `fr_py_worker_spawn_loop` was not exported
from a stale `libforkrun_python.so`, so the launcher could not resolve
its spawn worker at all. Artifacts are gitignored, so a stale build is an
ordinary state, not an anomaly.

### B-01: silent data loss on worker death — `dev/supervisor/BUGS.md`

The recovery integrity test found a bug worth more than the test.

A worker SIGKILLed mid-batch causes that batch's **consumed prefix to be
lost**. The batch is reclaimed and redelivered, but the redelivery
begins partway through, so only the unconsumed tail is processed. At 20
lines / 128-byte batches the run returns **14 of 20 lines and exits
cleanly** — no error, no poison record. The first record delivered is
the 4-byte fragment `LOAD`.

It is **engine-core**, not cleanroom: identical under both
`FORKRUN_CLEANROOM` settings and both supervision policies.

The two integrity tests are landed as `@unittest.expectedFailure` — green,
self-documenting, and they flip to **unexpected success** the moment the
bug is fixed. The cause is **not established** and `BUGS.md` says so
explicitly, with the candidate mechanisms listed as hypotheses. The fix
is expected in frozen `forkrun_ring.c`, so it is a maintainer decision,
not something to patch opportunistically.

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
