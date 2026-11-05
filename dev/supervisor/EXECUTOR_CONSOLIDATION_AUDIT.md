# TD-06 — Executor consolidation audit

**Status: AUDIT COMPLETE (mapping only). No refactoring performed and none
recommended on this evidence alone.**

Requested by the external parity audit, which claimed "substantial
remaining duplication" across `run.py`'s execution paths and asked for the
mapping to be traced before recommending consolidation. That mapping is
this document.

## Method, and a warning about it

Static analysis of `run.py`: locate every top-level `_execute*` function,
then search each function body for calls into `_executor_core`.

**The naive version of this analysis is wrong, and was wrong twice before
it was right.** `_executor_core`'s members are imported under local
aliases — `fork_workers as _core_fork`, `report_poison as _core_poison`,
`flush_stdio as _flush_stdio` — and several are reached through
function-local imports. A first pass, matching bare names, concluded that
`fork_workers` and `init_engine` were called by *no* executor and that
`report_poison` and `flush_stdio` were dead exports. All four statements
were false. The numbers below come from resolving the aliases from the
import statements themselves.

Recorded because it is the obvious way to do this analysis and it silently
produces confident nonsense. Any future tooling here should resolve
imports, not grep names.

## The map

16 executors, 9232 lines in `run.py`. Adoption of `_executor_core`:

| executor | lines | shared core used |
|---|---|---|
| `_execute_cleanroom` | 622 | **NONE** |
| `_execute_cleanroom_stream` | 2901 | init_engine |
| `_execute_streaming` | 336 | ExecutorSpec, flush_stdio, fork_workers, init_engine, report_poison |
| `_execute_ingest_stream` | 431 | ExecutorSpec, flush_stdio, fork_workers, init_engine, report_poison |
| `_execute_ingest` | 79 | none (thin wrapper) |
| `_execute_ingest_locked` | 389 | ExecutorSpec, collect_records, flush_stdio, fork_workers, init_engine, report_poison |
| `_execute` | 24 | none (lock-holding dispatcher) |
| `_execute_locked` | 689 | ExecutorSpec, collect_records, flush_stdio, fork_workers, init_engine, report_poison |
| `_execute_reactor_locked` | 616 | ExecutorSpec, collect_records, flush_stdio, init_engine |
| `_execute_streaming_reactor` | 537 | ExecutorSpec, flush_stdio, init_engine |
| `_execute_ingest_reactor_locked` | 554 | ExecutorSpec, collect_records, flush_stdio, init_engine |
| `_execute_ingest_stream_reactor` | 616 | ExecutorSpec, flush_stdio, init_engine |
| `_execute_sweep_standalone` | 54 | none (special case) |
| `_execute_sweep_with_source` | 378 | flush_stdio |
| `_execute_numa_locked` | 500 | ExecutorSpec, collect_records, init_engine |
| `_execute_numa_stream` | 506 | ExecutorSpec, init_engine |

Per-helper adoption:

| helper | adopted by |
|---|---|
| `init_engine` | 11/16 |
| `ExecutorSpec` | 10/16 |
| `flush_stdio` | 9/16 |
| `collect_records` | 5/16 |
| **`fork_workers`** | **4/16** |
| **`report_poison`** | **4/16** |

`12/16` executors adopt at least one shared mechanic. Nothing exported by
`_executor_core` is dead — every one is called somewhere.

## What this refines in the audit's claim

The audit said "substantial duplication remains" and was **directionally
right but imprecise**, in ways that matter for what to do next.

**Justified differences, which must not be "fixed":**

- `collect_records` is absent from the six streaming/ingest-stream
  executors because those *cannot* collect — they yield records live. That
  is a contract difference, not debt.
- `_execute` (24 lines) and `_execute_sweep_standalone` (54) are thin
  dispatchers/special cases. Folding them toward the core would be
  pointless.
- NUMA executors legitimately diverge on topology and per-node
  coordination, as the audit itself said in its "leave alone" table.

**The genuine gaps, ranked:**

1. **`fork_workers` — 4/16.** Worker forking is the most fundamental
   mechanic in the system and it is hand-rolled in twelve executors. This
   is the largest real consolidation opportunity, and it is where drift
   would be most damaging.
2. **`report_poison` — 4/16.** This substantiates the audit's point 6
   exactly: there is **no single implementation of poison accounting**.
   Plain, reactor and cleanroom execution each report independently. The
   audit's phrasing — "verify that plain execution, reactor execution, and
   cleanroom execution share the same accounting rules" — cannot be
   answered affirmatively from the code today. There is nothing to share
   *with*.

**The structural observation, which is the real finding:**

> Consolidation in this file tracks **age**, not necessity. The ten older
> executors all adopt `init_engine` and `ExecutorSpec`. The two cleanroom
> executors — 3523 lines, **38% of all executor code**, and the newest code
> in the file — adopt the least: `_execute_cleanroom` uses **nothing** from
> the shared core, and `_execute_cleanroom_stream` (the single largest
> executor at 2901 lines) uses only `init_engine`.

New code is not inheriting the existing abstraction. That is how the debt
accumulated, and it is why the audit's instinct that duplication "remains"
was correct even though the overall adoption rate is better than
"substantial" implies.

## What this does NOT establish

- **No behavioural equivalence was tested.** This is a map of which
  executor calls which helper. Two hand-rolled `fork_workers` sites might
  be identical, or might differ in a way that matters. Nothing here says
  they behave the same.
- **Duplication is not yet shown to be a defect.** Twelve call sites of
  similar worker-forking code is evidence of an opportunity; whether
  consolidating them would change behaviour is untested.
- **The audit's caution stands and is unaddressed:** do not merge the
  plain-waitpid and reactor paths into one flag-driven function. They
  implement different failure contracts — recovery, death detection,
  respawn, teardown. This audit does not evaluate whether the *reactor*
  vs *plain* fork sites are genuinely different contracts or merely
  similar code; that is the question any consolidation work order must
  answer first.
- This counts **call sites**, not semantics. A helper called once from a
  loop covering three executors would under-count; a helper called in a
  branch covering one path would over-count.

## Suggested next step

Not a refactor. Two cheap things first:

1. **Characterise the 12 `fork_workers` call sites** — determine how many
   are genuinely the same operation and how many encode different
   supervision contracts. Without that, "consolidate" is a guess.
2. **Check whether poison accounting already diverges in observable
   behaviour**, by testing one poison scenario through plain, reactor and
   cleanroom paths and comparing the reported counts. If they already
   differ, that is a defect worth its own register entry, and it would be
   found by reading rather than by refactoring.

Both are investigation, not change, and both are cheap relative to a
consolidation that turns out to be wrong.

---

## Addendum — Phase D of the parity work order

The "Suggested next step" above asked two questions. Both are now
answered, and the second produced a defect rather than a refactor.

### 1. Characterising the fork_workers call sites — DONE

`_executor_core.fork_workers()` is already the single worker-fork
dispatch, and the twelve call sites are differentiated by an explicit
`ExecutorSpec` lattice (`topology`, `ingest`, `supervision`, `shape`)
plus per-path flags, not by ad-hoc branching. Three worker kinds exist
(python, c-plugin loop, spawn loop), each with its own fd keep-set.

The six executor pairs are characterised in
`dev/supervisor/BASH_PY_PARITY_AUDIT.md` §7. **None was consolidated**:
each pair differs in supervision model, failure detection, recovery or
teardown contract, which is the property DECISION-03 and the work order
both protect.

One concrete finding from that characterisation, and it is the kind that
only shows up when you look at all three keep-sets together: the
poison-index stats descriptor has to be threaded into **four** separate
scrub keep-sets. A fix applied to one of them passes every test written
against the other. The three per-loop mutations that prove this are in
`python/tests/test_poison_accounting.py`.

### 2. Does poison accounting already diverge? — YES. TD-09b. (NOW FIXED)

**This was a defect, and it was found by running the measurement this
document asked for rather than by refactoring.**

`orchestrator=False` with a streaming source reported `poisoned=0` while
reporting the correct `poisoned_batches` list — two incompatible accounts
of one run. Since `total = completed + poisoned`, the headline number was
wrong on that path only.

Verified identical at `a65aa4ca`, i.e. pre-existing and not introduced by
the TD-09 index fix. Recorded as **TD-09b** in `TECH_DEBT_REGISTER.md`;
**TD-09b is now FIXED**.

**Correction to the reasoning below, now that it has been fixed.** The
divergence was *not* "one of four call sites forgetting to write
`_LAST_STATS`". The actual cause was an **ordering** defect, not a
funnel-routing one: on the generator executors the poison summary runs
*after* the inner `finally` calls `_teardown_stream()` →
`fr_py_destroy()`, so the count was read from a NULL `g_state` and came
back 0. The same change also uncovered an inverse defect (correct scalar,
**empty** index list) where a `globals()` lookup missed a function-scope
local. Routing the result through the shared funnel would **not** have
fixed either, because both paths already called `report_poison`.

**Consequence for consolidation:** the answer to "is poison reporting
common?" is *yes*, and the divergence was in **lifecycle ordering**, not
in where each path writes the result. Every route already funnels through
`report_poison`; what differed was whether the engine was still alive at
the moment of the call. This weakens the "consolidate the call sites"
argument and strengthens the case for leaving the executors separate while
sharing the ordering discipline.
