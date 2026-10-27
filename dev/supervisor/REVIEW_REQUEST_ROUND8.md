# External review request — round 8

> **RESPONDED TO — see `REVIEW_REQUEST_ROUND9.md`.** All three blocking
> grounds were reproduced and fixed, along with the follow-ups.
> Retained as the record of the request; the open-item table in §5 is
> superseded by round 9's §8.

Branch `NEW/REFACTOR4.2`. Review the **branch head** — this file is
added by the commit immediately after `9e4a599e`, so pin the head rather
than a SHA from this paragraph if you want the request itself in your
checkout. `9e4a599e` is the last commit that changes tested code.

Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across `c72d27c6..HEAD`.

**980 tests, 0 unexpected failures, 2 skipped, 0 expected failures.**
`python/release_check.py` → `ALL CHECKS PASSED` on a clean tree.
`UNIT_TESTS/test_frun.sh` → **96/96** (the bash-side suite; not re-run in
full because `frun.bash` and `forkrun_ring.c` are untouched across this
work, which is the exemption in `MAINTAINERS.md` §5's matrix policy rule).

Since `036668ea` (the round-7 request): **13 commits, 28 files, +4031/−501.**

Supersedes `REVIEW_REQUEST_STAGES1-4_R7.md` (retained, and marked, as
the record of what was claimed at the time).

---

## 1. Read this first: the standing constraint

Set by the maintainer mid-session and now governing all Python work:

> the bash front end is the official "approved" way to do things. the
> python front end development should be, in general, "as close to parity
> with how the bash front end works as is possible". Try not to re-invent
> the wheel in python

So a Python feature is **done when it delegates to the same mechanism
bash uses**, not when it produces the same answer. Audit and findings in
`PARITY_WITH_BASH.md`. The good pattern is already in place —
`_shim.c` reuses `do_lockfree_claim` / `ring_recover_worker_core` /
`ring_order_main` rather than forking them — and the one real divergence
(the splice path orders with a Python `ReassemblyBuffer`, because splice
emits no OrderPackets) costs **nothing measurable**: −0.4% at 8 workers,
−1.8% at 32. It is left open deliberately; see §5.

## 2. Three blockers closed since round 7

Requested as prerequisites to this review, so they are not
"discoveries" for the reviewer.

### 2.1 C0.6 — M1/M2 curves published (`C0.6_M2_MEASUREMENT.md`)

Pre-fork faster on **56/56** configurations; **crossover not yet
observed**. Margin decays monotonically with parent RSS at fork
(6.86x at 0 MB → 1.82x at 2127 MB), so the crossover is a *parent-size*
question, not a worker-count one. Single interpreter (**3.14.7**), so
the C0.5 matrix is incomplete and the result is a single-interpreter one.

Two harness defects found before any number was trustworthy:

* `fr_udf_fork`'s **default** run emitted `VERDICT: pre-fork DOES NOT
  WORK -- post-fork is the only option` when **both** arms had failed
  (the default spec `myudf:up` does not exist). A confident
  architectural conclusion from two failing runs. Any failure in either
  arm now suppresses the comparison.
* The parent-RSS knob **measured nothing** — the store loop into a
  malloc'd buffer is dead code at `-O2`, so pages were never resident.
  Reported 6 MB when asked for 256 MB. Fixed with `volatile`.

### 2.2 `RESILIENCE_PROTOCOL.md` §7.4 — recovery in `mode="spawn"` streaming

Previously listed as explicitly NOT covered. Four tests added: unordered,
ordered, two worker counts, and two deaths (the first time the escrow
kill counter is exercised).

### 2.3 NUMA validation

`numa=fake=4` turned out to be unnecessary — the project already uses
forced-logical nodes, and `test_numa_bump.py` states that forced-logical
`@4` exercises "real per-node machinery on any" host.

But `test_numa_recovery.py` gated all 7 Tier-3 tests on
`len(detect_numa_nodes()) >= 2` — **physical** hardware — while the tests
use forced-logical `nodes="@2"` and contain no `mbind`, no
`sched_setaffinity`, and no other placement call. `detect_numa_nodes`
appeared nowhere in that file except inside the guard.

So the suite verifying escrow routing by `txn->node`, per-node rings and
respawn node stability **skipped on every UMA machine including CI** —
7 tests of dead coverage in the one area where silent loss is a
*documented* property of born-local topology. All 7 now run and pass.
Suite skips 9 → 2.

## 3. Other fixes this round

* **Spawn still was not reaching the launcher** (`9adaa691`). My round-7
  fix shipped with a test that passed, because the test could only observe
  that the *output* was right. Two stacked causes: `_c_spawn_spec` reads
  argv off the function but the call site passed the `(fn, mode)` tuple,
  so the launcher branch was dead code; and once live, `--plugin None
  --func None` was sent for spawn, so the launcher `dlopen`ed the literal
  string `"None"`. `TestParityIsNotVacuous` counts calls into
  `_execute_cleanroom` and failed on its first run, which is how this was
  found.
* **Launcher failures now say why** (`bc41b78c`). A stale substrate —
  an *ordinary* state, both artifacts are gitignored — produced
  `exit 127 (unknown exit code 127)` while the real cause
  (`missing fr_py_worker_spawn_loop`) went to the inherited fd 2. Now
  captured to a memfd and folded into the message.
* **`add_disposition` docstring/code divergence** (`46cb467e`). The
  docstring said "the FIRST outcome is kept"; three of four contradiction
  branches did, the fourth called `add()`, which overwrites. Fixed to
  first-wins.
* **Pre-existing flake** (`7a8912b5`). `test_sigkill_during_stream`
  asserted `len(res) == len(healthy)` — a blob count — which
  `_helpers.lines_of` explicitly documents as forbidden ("batch
  boundaries are an implementation detail… never blob identity"). Failed
  ~1 run in 12 at HEAD. 20/20 green after.
* **Doc supersession landed** (`bc41b78c`).
  `CLEANROOM_HANDOVER.md` said Python UDFs were "Structurally impossible;
  do not attempt it" — which is exactly what the roadmap makes the next
  work item. Now carries the carrying-vs-reachability distinction.
* **`DOCS_ALL.md` drift** (`6abb49ef`). The embedded changelog recorded a
  "bounded 50 ms" wait where CHANGELOG says **2 ms**. The gate only
  checks headings are *present*, so text aging behind its own headings
  passes.

## 4. A retracted false alarm, and why it is retained

`BUGS.md` records **B-01** as filed and retracted the same day. I reported
silent data loss on worker death at high severity. It was a test
asserting byte-exactness under `on_error="skip"`, which drops the failed
batch **by contract**. The engine was correct.

It is retained rather than deleted because the process failure was mine
and expensive: I asserted a contract without stating the policy, treated
a plausible number ("14 of 20 lines") as a diagnosis when it was exactly
what skip means, built three candidate mechanisms in the ring to explain
a behaviour with no unexplained component, and reported it before reading
`frun.bash`, which was in the repository root the whole time.

## 5. Open items — stated, not hidden

These are known. Please challenge them rather than rediscover them.

| # | item | status |
|---|---|---|
| 1 | **C0.5 matrix** — 3.10–3.15 | only 3.14.7 installed; 3.14/3.15 never exercised |
| 2 | **C0.6 fleet memory** — children's PSS/USS | parent PSS/USS measured only; children unmeasured |
| 3 | **Physical NUMA** — locality, cross-socket, bandwidth | needs real hardware or `numa=fake=N` boot; forced-logical covers bookkeeping, not placement |
| 4 | **Two orderers** — splice uses Python `ReassemblyBuffer` | measured cost ≈ 0; kept for now. Causes `map(order="index")` to serve while `stream(order="index")` declines |
| 5 | **Ordered streaming** | declined — bounded-memory/liveness design absent |
| 6 | **`Auto` rollout / `mode="python"` parity** | W-EXP-1, gated on C0.6 + the packaging decision |
| 7 | **Truncated-tail wording** in `_make_results_pump` | docstring says "never user data"; too strong for pipes (`RESILIENCE` §2.2: pipes downgrade to at-least-once). Pre-existing; flagged, not touched |
| 8 | **`test_reactor.py:198,367`** | same blob-count shape as the flake fixed in §3. Not touched — different semantics |
| 9 | **Sanitizer matrix** | TSan/ASan/UBSan not run for this work |
| 10 | **CPython UDF auto-routing** | gated on the C0.5 matrix |

## 6. What I most want challenged

1. **Is `conflicts()` the right boundary?** It records a contradictory
   terminal outcome and keeps the first rather than raising, on the
   grounds that the caller is a streaming loop that has already consumed
   real input, so raising converts a protocol defect into a lost run. The
   alternative is fail-closed. I chose record-and-let-the-caller-refuse.
   Is that defensible?
2. **Is the benchmark byte-multiset invariant sufficient for a Stage 4
   verdict?** I argued no ordering evidence is needed because the harness
   does not claim ordering. A reviewer may reasonably say a throughput
   number on unvalidated ordering is not a decision.
3. **Is the oracle independent?** `test_capability_matrix` agrees on
   20160/20160 cells. Precisely: the oracle is **implementation-
   independent, not specification-independent.** Its rules are a second
   encoding of the same documented contract, authored in the same
   project. A mistaken contract produces perfect agreement. So it is a
   differential conformance test against the eligibility contract, not a
   proof that the contract captures every user-facing requirement — and
   the complementary safeguard is a separate review of the contract
   itself, which cell-count agreement cannot provide.
4. **Is the relaxed NUMA guard a loss of rigour?** I enabled 7 tests on
   UMA by relaxing a physical-hardware guard over forced-logical
   coverage. My reasoning is that `test_numa_bump.py` already establishes
   the mechanism is host-independent — but a reviewer could argue I
   weakened a guard to make tests pass.
5. **Stage 4's go/no-go itself.** Retain the splice loop, do not wire it
   into the launcher. This is a judgement call resting on a measured ~10x
   against `spawn cat`, and I would most like it challenged on the
   grounds that the win may be irrelevant to real workloads.

## 7. Where to look first

* `PARITY_WITH_BASH.md` — the standing constraint, the DOCS index that
  would have prevented the B-01 episode, and the NUMA status.
* `C0.6_M2_MEASUREMENT.md` — the curves, and the two harness defects.
* `BUGS.md` — the retraction, kept as a record.
* `python/tests/test_stage3_parity.py` — `TestParityIsNotVacuous` is the
  pattern I would most like applied elsewhere.
* `python/tests/test_stage3_recovery_integrity.py` — per-policy batch
  atomicity, including the three wrong assertions that preceded it.
