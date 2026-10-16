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
| F2 | Poison stats | Plain *streaming* path reports `poisoned=0` beside a correct index list | **Confirmed defect (TD-09b)** |
| F3 | Descriptor limit | Python cleanroom launcher did not get the hard `ulimit -n` bash gets | **Confirmed defect — FIXED** |
| F4 | Docs | `DOCS_ALL.md` drifted ~130 lines with a heading-only check passing | **Documentation drift — FIXED** |
| F5 | Docs | Root README version, 4-of-5 mode lists, stale v0.5 module docstring, trap-ACK comments, NUMA test claims | **Documentation drift — FIXED** |
| F6 | Cleanroom launch | Design proposes `posix_spawn`; implementation uses `fork()+execv()` | **Unresolved — decision report, no change** |
| F7 | Cleanroom env | Python inherits the whole environment; bash reconstructs | **Unresolved — low exposure today, see §6** |
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

### F2 — confirmed defect: the plain streaming scalar

`orchestrator=False` + streaming reports `poisoned=0` while reporting
`poisoned_batches=[2, 5]` — two incompatible stories about one run.
Verified identical at `a65aa4ca`, i.e. pre-existing and **not** caused by
the index-list fix that closed TD-09. Recorded as **TD-09b**.

This is the answer to `EXECUTOR_CONSOLIDATION_AUDIT.md`'s own suggested
next step ("check whether poison accounting already diverges in observable
behaviour"). It does, and it is a defect rather than a consolidation
blocker.

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

### F3 — confirmed defect, FIXED

`CLEANROOM_DESIGN.md` requires the launcher to get the hard `ulimit -n`;
`frun.bash` does it; Python did not. See
`CLEANROOM_LAUNCH_DECISION.md` §6.

### F6 — unresolved: `posix_spawn`

Design proposes it; implementation uses `fork()+execv()`. The design's
own delivery plan gates integration on a **measured PoC that does not
exist in the tree**. Full analysis and recommendation in
`CLEANROOM_LAUNCH_DECISION.md`. No code changed.

### F7 — unresolved: environment contract

Bash reconstructs (`--norc --noprofile`, explicit `LC_ALL=C`, `set +m`,
`shopt -s extglob`). Python inherits everything via `os.execv()`.

Measured exposure is small and worth stating precisely: the launcher
reads **exactly one** environment variable,
`FORKRUN_TEST_BREAK_DRAIN_WAKEUP`, a test-only hook. All real
configuration crosses as argv. So today's safety is **accidental, not
designed** — a caller's stray `FORKRUN_*` cannot affect the launcher
because it reads none. The first `getenv` added to the launcher would
silently change that. Recommendation in the decision report §7:
document the contract now, before it becomes load-bearing.

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

## 8. Deliberately not done

* **No executor consolidation.** The pairs differ in supervision, failure
  detection, recovery and teardown contracts; the work order forbids
  merging plain and reactor, and the evidence says the other pairs have
  the same property.
* **No indexed-splice unification.** `FUTURE_WORK.md` and the splice
  path keep a dedicated reassembly implementation; forcing it through the
  C orderer would be uniformity for its own sake, and the C interface
  needed to emit splice order packets is not established.
* **No `posix_spawn` implementation** (F6) and no environment redesign
  (F7) — both need the decision report's evidence first.
* **No engine or substrate change.** Frozen files untouched throughout.

## 9. What this audit does NOT establish

* No performance claim. Nothing here was benchmarked; the only
  performance-adjacent statement (the `fork()` cost argument for
  `posix_spawn`) is explicitly unmeasured and the protocol to measure it
  is specified in the decision report §5.
* No physical-NUMA validation (F14).
* No claim that the Bash frontend is correct — it is the *reference*,
  and `frun.bash` has its own documented gaps.
* Not a re-audit of the 32 `PORT_AUDIT.md` items, which are already
  fully dispositioned and green.
