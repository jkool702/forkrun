# Bash ↔ Python comparative audit

**Work order:** Python/Bash parity, source-of-truth audit, duplication
reduction — Phase A.
**Branch:** `NEW/REFACTOR4.2`.
**Method:** read `frun.bash` and the normative `DOCS/` set, then inspect
the Python frontend and its tests. Findings are classified by the
work order's five categories. **No finding below rests on a line number
alone**; each cites a function, file or test, because line numbers move.

**Companion documents, not duplicated here:**
`PORT_AUDIT.md` (the 32-item port matrix, fully dispositioned),
`EXECUTOR_CONSOLIDATION_AUDIT.md` (executor overlap — extended here in
§7), `CLEANROOM_LAUNCH_DECISION.md` (Phase B).

---

## 0. What is normative, and what is history

`DOCS/INVARIANTS.md` is the authority for engine behaviour; §19 is the
Bash↔Python port contract. `EOF_PROTOCOL.md` and
`RESILIENCE_PROTOCOL.md` govern termination and recovery. Where a
document describes a past state rather than the contract, it says so —
`BORN_LOCAL_NUMA.md` §4.1 and §5 both carry explicit HISTORICAL notes,
which is the pattern this audit follows.

---

## 1. Summary of classifications

| # | Area | Finding | Class |
|---|---|---|---|
| F1 | Poison/recovery | Escrow deposit and batch recovery are **parent-side** in both frontends | **Intentional divergence — actually convergence** |
| F2 | Poison stats | Plain *streaming* path reported `poisoned=0` beside a correct index list | **CONFIRMED DEFECT — FIXED (TD-09b)** |
| F3 | Descriptor limit | Claimed the launcher lacked the hard `ulimit -n` | **FALSE POSITIVE — withdrawn**; the C launcher has always raised it |
| F4 | Docs | `DOCS_ALL.md` drifted ~130 lines with a heading-only check passing | **Documentation drift — FIXED** |
| F5 | Docs | Root README version, 4-of-5 mode lists, stale v0.5 module docstring, trap-ACK comments, NUMA test claims | **Documentation drift — FIXED** |
| F6 | Cleanroom launch | `posix_spawn` is the DEFAULT cleanroom launch backend; `fork()+execv()` retained as a private fallback | **DONE — performance gate MET; descriptor gate ANSWERED (Stage 2); launch-semantic equivalence CLOSED (C1–C5); backend ADOPTED as default (Stage 4)** |
| F7 | Cleanroom env | `CLEANROOM_DESIGN.md` says the launcher "must not inherit the parent's environment wholesale"; `os.execv()` inherits it | **OPEN — a stated contract that is not met** |
| F8 | Cleanroom stream | Unreachable iterable producer with live control flow | **Confirmed defect — FIXED** |
| F9 | Trap-ACK grace | Presented as the recovery mechanism; armed only on legacy substrates | **Documentation drift — FIXED** |
| F10 | NUMA tests | Skip decorator claimed physical NUMA; guard returns `True` always | **Documentation drift — FIXED** |
| F11 | Recovery death-class | Bash censuses exit 126/127; Python has no equivalent | **Intentional divergence** |
| F12 | Resume consent | Bash has a 3-layer interactive gate; Python is fail-closed always | **Required capability difference** |
| F13 | Realtime `-u` | Bash-only output mode with at-least-once semantics | **Required capability difference** |
| F14 | NUMA locality | No real multi-socket validation anywhere | **Unresolved — correctly flagged as such** |

---

## 2. Input and batch delivery

**Bash.** Source is always materialised into an anonymous memfd
(`ring_copy`, or `ring_numa_ingest`). There is no direct-to-worker
streaming ingest. Non-seekable inputs are handled *implicitly* — an
`lseek` that fails short-circuits the optional NUMA probe, with no
bash-side branch. Batch boundaries are entirely engine-side; bash only
emits `--lines` / `--bytes` / `--exact-lines` / `--timeout` options.
EOF is signalled explicitly (`ring_copy … && ring_signal || ring_abort`),
so a clean drain is distinguishable from a copy fault.

**Python.** Same engine, same boundary rules. `_api._validate()` enforces
`_reject_iterable_source` ("Python is never an input pump"), rejects
`bool` sources (an `int` subclass that would otherwise be read as fd 1),
and normalises `-L`-over-`-b` to line mode with a `UserWarning` — which
`INVARIANTS.md` §19 requires as Bash `-L`-overrides-`-b` parity.

**Verdict: intentional divergence, small and justified.** Python's
iterator `stream()` API is explicitly preserved by the work order. The
one asymmetry worth noting is that Python *rejects* iterables loudly
where Bash has no concept of them.

## 3. Worker lifecycle and recovery

**The single most important finding of this audit is that this area has
already converged, and the convergence is deliberate.**

Bash's worker `EXIT` trap is *cleanup-only*:

> W-PY28: cleanup-only EXIT trap. Batch recovery (output revert,
> num_kills increment, escrow deposit) is parent-side now […] Doing it
> here too would double-deposit escrow.

`frun.bash` contains **zero** calls to `ring_escrow_put` — it is exported
as a builtin with no caller. Deposit happens inside
`ring_recover_worker_core`. `RESILIENCE_PROTOCOL.md` §2 (W-PY29) states
the same for Python: "the PARENT recovers on any death."

Death classification is identical: both frontends dispatch on
`ring_recover_worker`'s return code — 0/1/3 respawn, 2 `NORMAL_EXIT` (free
the slot, no respawn), 4 `RACE_DETECTED` → abort, 5 fatal → abort.

**Poison semantics are identical and are engine-owned.** Neither frontend
parses `FORKRUN_RETRY_LIMIT` for policy: bash forwards it and never
branches on it; Python routes it through `_api._resolve_retry_limit()` and
never hardcodes a literal at a worker-init site. Both observe
`RING_POISONED` from the engine and relay a notice.

### F2 — confirmed defect: the plain streaming scalar — FIXED (TD-09b)

`orchestrator=False` + streaming reported `poisoned=0` while reporting
`poisoned_batches=[2, 5]` — two incompatible stories about one run.
Verified identical at `a65aa4ca`, i.e. pre-existing and **not** caused by
the index-list fix that closed TD-09. Recorded as **TD-09b**, now fixed.

This is the answer to `EXECUTOR_CONSOLIDATION_AUDIT.md`'s own suggested
next step ("check whether poison accounting already diverges in observable
behaviour"). It did, and it was a defect rather than a consolidation
blocker.

**Resolved, and larger than the single symptom recorded here.** Root
cause: on the GENERATOR executors (`_execute_streaming`,
`_execute_ingest_stream`) the poison summary sits *outside* the inner
`try/finally`, so it runs after `_teardown_stream()` →
`fr_py_destroy()` has NULLed `g_state` — and `fr_py_poisoned_count()`
returns 0 in that state. The index list survived only because it is read
from the relay memfd, not the engine. The second executor additionally
read its channel via `globals()` and so published an **empty** index list
beside a correct scalar. Engine liveness at summary time was a race:
identical runs reported both 0 and 2. Both executors now stash the count
before teardown; see TD-09b for the full account.

### F11 — intentional: exit-code census

Bash censuses worker exits and maps `_fr_wclaims == 0` → **126**,
all-127 → **127**, else 0. Python raises exceptions instead
(`PYTHON-IS-IMPORTABLE-LIBRARY` is a named N/A in `PORT_AUDIT.md`).
Correct: a library has no process exit code.

## 4. Output behaviour

**Bash** has three regimes — `buffered` (default), `ordered` (`-k`), and
`realtime` (`-u`). Realtime bypasses the orderer entirely: workers inherit
real stdout, which is why resume degrades to at-least-once there and why
`FLAGS.md` warns against it.

**Python** has `order="none"` (default, worker-completion order) and
`order="index"` (input order via the C orderer). `stream()` is a live
generator by default.

**F13 — required capability difference.** `-u` has no Python analogue, and
`INVARIANTS.md` §19 classifies `framed-transport-invariant` as
N/A-BY-DESIGN for that reason. Correct.

**Bash's order-ack pipe is 1 page (4 KiB)** — that sizing is what makes
fan-in a closed hydraulic loop rather than an unbounded queue
(`DESIGN.md` §11, H3). Python's equivalent is the drain, not a pipe.

## 5. NUMA

`_forkrun_build_numa_map()` (bash) and `_numa.build_numa_map` (Python)
implement the same `@N` / `0,1` / `auto` / count grammar, including the
`@N ≤ 512` bound and the small-file UMA downgrade. `INVARIANTS.md` §18
requires worker counts be raised to cover every node, and both do it at a
single normalization point — which is precisely the kind of "structural,
not vibey" N/A that §19 demands before a difference may be called
intentional.

**F14 — unresolved, and correctly flagged.** Every NUMA claim in either
frontend rests on `numa=fake=N`. `FUTURE_WORK.md` #48 says so plainly
("do not fake a result"), and `test_numa_recovery.py` now says the same
("It does NOT cover physical memory locality, cross-socket placement, or
real bandwidth"). The launcher has no NUMA symbol at all, so
`FUTURE_WORK.md` #45 (NUMA cleanroom) is genuinely open.

## 6. Resource lifecycle and the cleanroom

**Descriptor discipline.** Bash closes every inherited end in each child
before the next fork, with documented reasons (fork-order: "a
later-forked child's inherited write end would mask an earlier indexer's
POLLHUP"), and passes worker fds through the **environment** rather than
positional arrays (`D-SEGFIX`: the engine must never walk bash ARRAY
structs). Python uses `scrub_fds(keep)` plus an `extra_keep_fds`
parameter added this cycle. Both honour `INVARIANTS.md` §19's "fd 2 never
redirected or closed".

### F3 — FALSE POSITIVE, withdrawn

I claimed the Python cleanroom launcher did not receive the hard
`ulimit -n` that bash gives it, implemented a fix, and reported it as
fixed. **It was already correct.** `forkrun_cleanroom.c` has
`raise_fd_limit()` (line 461), called from `main()` (line 1727) before
`dlopen()` (line 1729) — ahead of any memfd, pipe or worker — and it is
present identically in the baseline commit.

The failure mode is worth recording. I observed that `run.py` had no
`RLIMIT_NOFILE` reference, read "which the launcher should do too" as an
unmet requirement, and never checked the launcher. The evidence was
consistent with my hypothesis and I never tested it. Checking the place
I expected the defect to be would have refuted it in one command.

The test written to confirm it could not have detected the failure: it
wrapped the launcher in a shell that recorded the limit and then `exec`ed
the real binary, so it measured the limit *before* the C launcher raised
its own. It proved my helper ran, not that anything was broken.

A second, independent reason the change was wrong: the helper did
`import resource` and Python work between `fork()` and `execv()`,
precisely the pre-exec activity worth minimising when forking from a
possibly-multithreaded host.

### F6 — MEASURED (performance gate met); backend still not adopted

Design proposes `posix_spawn`; production uses `fork()+execv()` and
**still does**. No code changed.

**Status, stated in the same four parts everywhere it appears:**

| part | state |
|---|---|
| production backend adopted? | **NO** — `fork()`+`execv()` remains |
| small-parent measurement | **done, and superseded** (see below) |
| parent-RSS sweep | **done** — 0/256 MiB/1/2/5 GiB, RSS verified 100% resident |
| performance gate (§5 condition 1) | **MET** — −88% to −96% launch latency at 1-5 GiB |
| descriptor-equivalence gate (§5 condition 2) | **OUTSTANDING — this is the blocker** |

**The measurement, briefly.** `tools/bench_cleanroom_launch.c` drives the
real launcher in `--fork-only` mode, interleaved A/B, ballast allocated as
resident (touched) memory and verified from `/proc/self/smaps_rollup`
(the kernel's accurate counter; `statm` is kept only as a cross-check and
agrees to 0 KiB): `fork()+execv()` goes 2.8 ms (0 ballast) → 9.6 ms
(256 MiB) → 29.4 ms (1 GiB) → 49.2 ms (2 GiB) → 112.0 ms (5 GiB), while
`posix_spawn` stays flat at 2.7–4.2 ms. So the design's rationale is
empirically confirmed: the `fork()` cost scales with the parent's memory
and `posix_spawn` does not pay it. **Independently reproduced** across two
sweeps; the `fork()` column varies run to run by up to ~25% at 1 GiB, the
`posix_spawn` column does not, and the conclusion holds in both. Full
table, controls, and limits in `CLEANROOM_LAUNCH_DECISION.md` §1.1a.

**Do not read "gate met" as "adopt".** §5's decision rule has two
conditions, and the **descriptor condition is now answered** by F6 Stage 2/3
(`dev/supervisor/CLEANROOM_FD_CONTRACT.md`): two launch shapes, one
`DUP2` action for the materialized route and **no** actions for the
streaming route, neither needing `CLOSEFROM`, so the 3.10 floor is not a
blocker.

**What still gates integration is launch semantics, not descriptors.** A
launcher that cannot be *executed* exits **127** today, and 127 is **not**
in `_CR_EXIT_PRE_INGEST` — so `_cleanroom_may_fallback()` returns False
and the caller gets a **`RuntimeError`; it does NOT fall back**. Only
absence at *preflight* falls back, and that is a different case. Under
`posix_spawn` the same failure raises synchronously in the parent with no
wait status to classify. Recommended policy is **Policy A** (map the
`OSError` onto today's caller-visible result); Policy B (treat it as
pre-ingest) is defensible but unauthorised. Disposition is **GO** — conditions C1–C5 all CLOSED against named evidence in `CLEANROOM_FD_CONTRACT.md` §9, and the ADOPTION decision has since been taken: `posix_spawn` is the default backend, with `fork()+execv()` retained as a private fallback. Stage 4 additionally corrected the C5 closure, which had been recorded as sound on a relocation helper that could still return a descriptor inside the standard-stream gap.

Also found: a **pre-existing** defect where, with fd 2 closed before
allocation, a route descriptor is clobbered by `dup2(errfd, 2)`.
`posix_spawn` behaves identically, so equivalence holds, but the case is
neither verified nor fixed (tracked as C5).

**Equivalence is not isolation.** An unrelated *inheritable* parent
descriptor survives into the launcher under BOTH mechanisms — asserted by
`test_equivalence_is_not_isolation`. Tightening the set is expressible
(with a `POSIX_SPAWN_CLOSE` action) but is a behaviour change, not an
equivalence-preserving optimisation, and it carries an enumeration race a
host-side design cannot avoid.

**Correction to this audit's own earlier entry.** A previous revision said
the gate "does not exist in the tree" and an intermediate one recorded the
gate as **not met** on small-parent data only. Both are superseded. §5
warned in advance that "a sweep at low ballast will report 'no difference'
and is worthless for this decision" — the small-parent sweep hit exactly
that, and the warning was right. The measurement was never wrong; its scope
was, and it was over-read.

### F7 — OPEN: the environment contract is stated and not met (exposure MEASURED; contract UNDECIDED)

`CLEANROOM_DESIGN.md` §"Configuration contract" states:

> The launcher must not inherit the parent's environment wholesale.

Both Python launch sites call `os.execv()`, which inherits everything.
Bash satisfies the contract by construction.

**An earlier draft of this audit rated this "low exposure", on the
argument that the launcher reads exactly one environment variable (a
test-only hook) and all real configuration crosses as argv. That
inference was wrong**, and it is withdrawn:

* `map-spawn` and `map-udf` are **served cleanroom routes**. A spawned
  command and a UDF module are user code and can read the environment.
  What the *launcher* reads says nothing about what the *payload* reads.
* `ld.so` consumes `LD_LIBRARY_PATH` / `LD_PRELOAD` **during `exec`**,
  before `main()` runs. Auditing the launcher's source cannot see that.

So this is a **stated contract the implementation does not meet**, not a
matter of taste. Clearing the environment is not the obvious fix: a
`mode="spawn"` payload plausibly needs `PATH` and a UDF module may need
`PYTHONPATH`. The follow-up must compare Bash, in-process Python, and
cleanroom plugin/spawn behaviour before any contract is chosen. See the
decision report §7.

#### MEASURED (environment-boundary audit) — F7 is confirmed, not inferred

The comparison the entry above asked for has now been run, with a purpose-
built probe plugin that reports the child's environment back through its own
output. It counts **every** variable rather than filtering by prefix, so a
probe-side filter cannot manufacture a "scrubbed" result.

| route | child env count | parent count | crosses wholesale? |
|---|---|---|---|
| `FORKRUN_CLEANROOM=0` (in-process) | 112 | 112 | n/a (same process) |
| `FORKRUN_CLEANROOM=map-plugin` (exec'd launcher) | **113** | 112 | **yes — all 112, plus `FRK_POISON_FD`** |
| `FORKRUN_CLEANROOM=map-spawn` | 112 | 112 | **yes — all 112** |

Present in the cleanroom child and confirmed reachable by payload user code:
`MARKER_FORKRUN_ENVPROBE`, `AWS_SECRET_ACCESS_KEY`, `LD_MARKER_INJECTED`,
`PYTHONHASHSEED`. Nothing is dropped. The +1 on `map-plugin` is the
`setenv("FRK_POISON_FD", ...)` at `forkrun_cleanroom.c:2017`; `map-spawn`
does not carry it, which is itself worth noting but is not a scrubbing
effect.

**One concrete failure, not just a contract mismatch:** a *malformed*
`PYTHONHASHSEED` in the parent kills the cleanroom child at interpreter
init, before a single batch is read:

```
$ PYTHONHASHSEED=py-side FORKRUN_CLEANROOM=map-plugin ... map(...)
Fatal Python error: config_init_hash_seed: PYTHONHASHSEED must be
"random" or an integer in range [0; 4294967295]
```

So wholesale inheritance is already an **availability** exposure, not only a
disclosure one: a value the user never meant as a forkrun setting can decide
whether the cleanroom route runs at all.

**The FD half of that same contract paragraph IS implemented** — `_fd_scrub.scrub_fds` is called on the child paths, and the design's descriptor claims hold. The divergence is **specific to the environment**, which narrows the fix and the review surface considerably.

**Correction to my own first probe.** An initial run appeared to show the
cleanroom child seeing only three variables, which would have meant the
launcher scrubs. That was an artifact: the marker variables had not actually
been exported into that process's environment. Re-run with the markers
genuinely set, the child sees all 112. **Recorded because the wrong reading
was plausible, cheap to reach, and would have closed F7 on a setup bug.**

**Still not established:** what a `mode="spawn"` payload or UDF module
legitimately *needs*. The contract stays OPEN — this measurement establishes
what happens, not what should.

## 7. Source-of-truth and duplication

### F4 — FIXED: `DOCS_ALL.md`

The aggregate had **no generator** and only a heading-presence check.
That check passed while six of sixteen embedded documents were stale:
README missing 47 lines, `RESILIENCE_PROTOCOL` missing 71, plus `FLAGS`,
`MAINTAINERS`, `INVARIANTS`, `FORKRUN_OVERVIEW`. A heading check cannot
see a body rewritten underneath it.

Now `tools/gen_docs_all.py` regenerates it from an explicit ordered list,
is idempotent, and supports `--check`, wired into `release_check.py`.
One 28-line block existed in the aggregate with **no source document** —
regenerating would have deleted it, so it was given a home in
`PYTHON_BEHAVIOR.md` rather than dropped.

### F8 — FIXED: unreachable iterable producer

`_execute_cleanroom_stream()` carried a fork()ed producer that
`_api._reject_iterable_source` makes unreachable, with live waitpid and
teardown entries. Its sibling in `_execute_cleanroom()` had already been
deleted for the same reason. Removed — but the *real* limitation it
documented (a caller-fed pipe dying mid-stream cannot be detected from
in there) was kept, because that limitation survives the branch.

### Executor overlap (`EXECUTOR_CONSOLIDATION_AUDIT.md`, extended)

The six pairs named in the work order were **not** consolidated, and the
audit now records why rather than leaving it as an open suggestion:

| Pair | Shared contract | Why not merged |
|---|---|---|
| `_execute_locked` / `_execute_ingest_locked` | init, plain waitpid supervision, fd teardown | different ingest shapes; `ExecutorSpec` already carries the axis |
| `_execute_streaming` / `_execute_ingest_stream` | reactor ingest, per-quantum supervision | different generator vs blocking drain loops |
| `_execute_reactor_locked` / `_execute_ingest_reactor_locked` | reactor supervision | same argument as above |
| `_execute_streaming_reactor` / `_execute_ingest_stream_reactor` | reactor + drain | ditto |
| `_execute_numa_locked` / `_execute_numa_stream` | NUMA per-node coordination | ditto |
| `_execute_cleanroom` / `_execute_cleanroom_stream` | launcher exec, argv construction, stats read | different source/result transports |

**Already centralised, and correctly so:** `fork_workers`
(`_executor_core.py`) is the single worker-fork dispatch; `report_poison`
is the single scalar poison funnel; `ExecutorSpec` is the single lattice
description. The work order's warning against wrapping a shared helper in
a second local wrapper is the live risk here, not a missing helper.

The consolidation audit's own next step — measure poison parity before
refactoring — was done, and produced F2/TD-09b rather than a refactor.
That is the right outcome: **the investigation found a defect, not a
duplication.**

## 8. Disposition list

### Implemented and verified in this work order

| ID | Change | Proof |
|---|---|---|
| F4 | `DOCS_ALL.md` made reproducible; `--check` wired into the release gate | `test_docs_all_freshness.py`, including a deliberate-drift test that proves the gate goes red |
| F5 | Doc corrections: README version, 4-of-5 mode lists, `udf` documented, duplicate heading, v0.5 module docstring | release gate + `test_doc_accuracy.py` |
| F8 | Unreachable iterable producer and its control flow removed from `_execute_cleanroom_stream`; stale docstrings corrected | cleanroom suites green on all three gate modes |
| F9 | trap-ACK grace labelled legacy at all three sites | existing tests unchanged |
| F10 | NUMA test claims corrected; dead `_has_numa()` removed | `test_numa_recovery.py`, 8 tests |
| F14 | Left correctly flagged as unproven | no change made — this is the honest state |

### Withdrawn

| ID | Was claimed | Now |
|---|---|---|
| F3 | "The launcher did not get the hard `ulimit -n`" — confirmed defect, fixed | **FALSE POSITIVE.** `forkrun_cleanroom.c:461` `raise_fd_limit()`, called from `main()` at `:1727`, present in the baseline. Python-side helper and its tests reverted. |

### Confirmed defects left OPEN

| ID | Defect | Why not fixed here |
|---|---|---|
| **F2 / TD-09b** | `orchestrator=False` + streaming reported `poisoned=0` while reporting a correct, non-empty `poisoned_batches`. Since `total = completed + poisoned`, the headline number was wrong on that path only. | **FIXED.** Pre-existing at `a65aa4ca`, i.e. not introduced by the TD-09 index fix. Root cause was summary-after-teardown on the generator executors, not call-site funnel divergence; the count is now stashed before `fr_py_destroy()` NULLs `g_state`. A second, inverse defect (empty index list, correct scalar) was found in the same change and is covered by the same tests. Mutation-proven. |
| **F7** | `CLEANROOM_DESIGN.md` states the launcher "must not inherit the parent's environment wholesale"; both Python launch sites call `os.execv()`, which inherits it. | Answering it needs a deliberate compatibility decision (Bash reconstructs; clearing outright would break `mode="spawn"` payloads that need `PATH` and UDF modules that need `PYTHONPATH`). Requires comparing four behaviours first — see the decision report §7.4. |

### Intentional divergence retained

F1 (lifecycle/recovery — already converged), F11 (exit-code census),
F12 (resume consent), F13 (realtime `-u`).

### Needs a separate, design-first decision

F6 (`posix_spawn`). The measurement is **done** and met its half of the
gate; what remains is descriptor-set equivalence, which is design work.
See the decision report §8.

---

## 9. Deliberately not done

* **No executor consolidation.** The pairs differ in supervision, failure
  detection, recovery and teardown contracts; the work order forbids
  merging plain and reactor, and the evidence says the other pairs have
  the same property.
* **No indexed-splice unification.** `FUTURE_WORK.md` and the splice
  path keep a dedicated reassembly implementation; forcing it through the
  C orderer would be uniformity for its own sake, and the C interface
  needed to emit splice order packets is not established.
* **No `posix_spawn` implementation** (F6) — its performance evidence now
  exists and is positive, but the descriptor-equivalence gate is open and
  no integration was authorised — and no environment redesign (F7), which
  needs a separate compatibility decision, not evidence.
* **No engine or substrate change.** Frozen files untouched throughout.

## 10. What this audit does NOT establish

* No performance claim. Nothing here was benchmarked; the only
  performance-adjacent statement (the `fork()` cost argument for
  `posix_spawn`) is explicitly unmeasured and the protocol to measure it
  is specified in the decision report §5.
* No physical-NUMA validation (F14).
* No claim that the Bash frontend is correct — it is the *reference*,
  and `frun.bash` has its own documented gaps.
* Not a re-audit of the 32 `PORT_AUDIT.md` items, which are already
  fully dispositioned and green.
