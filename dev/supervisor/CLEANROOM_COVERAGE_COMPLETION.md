# Cleanroom coverage completion plan

**Status: PROPOSAL — amendments from external review round 1 applied.
Nothing here is implemented.**
Companion to `CLEANROOM_EXPANSION_ROADMAP.md` (accepted, rounds 1–7), which
defines the envelope, the contracts and the expansion work items W-EXP-1/2/3.

> **Amendment log.** Review round 1 returned *GO WITH AMENDMENTS* with seven
> required corrections. **Three of them refute errors in the previous draft of
> this document**, each confirmed by direct test rather than accepted on
> authority:
>
> | # | previous claim | verified finding |
> |---|---|---|
> | A | "`stream()` already does parent-side reassembly via `batch_idx`" | **Wrong.** The *cleanroom* stream path yields records as they arrive — its docstring reads "The parent only ever DRAINS". The in-process path reassembles; the cleanroom one does not. This conflation was mine. |
> | A | "the streaming path merely discards the poison count" | **Wrong.** The cleanroom stream argv passes **no `--stats-fd`** at all (`run.py:1515`). The channel must be wired and consumed, not forwarded. |
> | B | certificate = `emitted_records == published_slots` | **Wrong.** A UDF returning `None` for half the batches yields **0 records against 100 published slots** — not drift, collapse. Payload-record count is not the order-packet count. |
> | D | "`PyConfig` is in the limited API as of 3.10" | **Wrong.** Compiling with `-DPy_LIMITED_API=0x030A0000` fails: `unknown type name 'PyConfig'`. The abi3 premise did not survive one compiler invocation. |
>
> The remaining corrections (reachability wording, oracle methodology,
> frequency language, shim policy, P7 proof obligation) are accepted as stated.

---

## 0. The goal, restated — and the end state

The intent is **complete coverage**: the cleanroom launcher should serve the
whole reachable public API, and every refusal should be one the system can
justify rather than a gap nobody closed.

The accepted roadmap does **not** deliver that. It covers
`mode ∈ {plugin→python→spawn}` plus NUMA, and does not address
`orchestrator=False`, `resume`/`checkpoint_file`, `mode="splice"`, or the two
narrowed `stream()` gates. This plan closes all of it.

**The end state, stated so the sequencing can be judged against it.** In the
bash front end the exec cleanroom is the **only** path — there is no option to
turn it off, only overrides for injecting bash variables/functions into it.
The Python side should end up the same way. That is **not** this plan's
deliverable: the deliverable is that coverage is as complete as feasible, and
that each capability becomes **default where it is available and where both
performance and correctness are proven** — independently, per capability, so
one unproven axis never holds back another.

---

## 1. Measured baseline — valid workload configurations

The C0.1 capability matrix enumerates 60,480 cells, but its axes carry values
that do not correspond to valid workloads. Two different corrections apply,
and conflating them was the previous draft's error:

> **WO-CM1 supersedes the counts below.** The matrix was rebuilt from the
> public entry points rather than from the predicate alone, and the headline
> numbers in this section predate that work. Three facts changed:
>
> 1. `run()` is now a first-class entry point, and it has **no cleanroom
>    branch at all** -- it is never launcher-served, for any mode.
> 2. The predicate is **unreachable** for most of the grid: `map()` consults
>    it only for modes `(plugin, udf, spawn)`, `stream()` only for
>    `(plugin, udf)` and only when the call is actually streaming, and both
>    bypass it entirely for `num_nodes > 1`.
> 3. The denominator is now stated over **public-VALID** cells
>    (17,280 of 60,480). The old figure divided by a grid that was 62%
>    configurations no public call could make.
>
> **WO-CM1-R1 corrected the inventory again.** The first WO-CM1 pass
> generated 60,480 rows for only 40,320 distinct configurations: it
> normalised the inapplicable `streaming` value for map/run *after*
> expanding the Cartesian product, counting every map/run cell twice.
> Public validity was also too weak — it did not model argument
> applicability or entry-point refusals — so the "public-valid"
> denominator was overstated even then.
>
> Current figures, all from the generated matrix (`--check` verified):
>
> | Measure | Value |
> |---|---:|
> | Rows enumerated (all distinct) | 40,320 |
> | Public-VALID | 6,624 |
> | Predicate accepts (of valid) | 288 |
> | **Launcher selected (of valid)** | **168 (2.54%)** |
>
> The historical counts below are retained only to show what changed.

| case | status | why |
|---|---|---|
| `order` outside `("none","index")` | **Unreachable.** Excluded from the denominator entirely. | `_VALID_ORDERS` rejects it at `_api.py:168` with `ValueError` before the envelope is consulted. `DECLINE_ORDER`'s 224 cells guard an internal invariant, not a path. |
| source `missing` / `dir` / `bogus` | **Reachable, but invalid workloads.** Excluded from the coverage denominator; **retained as negative-input / error-conformance cases.** | These *are* reachable: a path-like string passes `_validate()`'s type check and `_cleanroom_eligible()` then rejects it on resource validity. They are error behaviour, not capability gaps, and must keep their own coverage. |

Re-enumerated over **valid workload configurations** — the type surface at
`_api.py:21-31` (`Mode = {python, spawn, plugin, splice}`,
`Order = {none, index}`, `Nodes = int | str | None`, `OnError = {retry,
fail-fast, skip}`) plus four valid source kinds:

| outcome | cells | % of valid configs |
|---|---|---|
| `DECLINE_NODES` (NUMA) | 2048 | **50.0%** |
| `DECLINE_MODE` (`python`/`spawn`/`splice`) | 1536 | **37.5%** |
| `DECLINE_ORCH` (`orchestrator=False`) | 256 | **6.2%** |
| `DECLINE_RESUME` | 192 | **4.7%** |
| `DECLINE_STREAM_ORDER` | 16 | 0.4% |
| `DECLINE_STREAM_POISON` | 8 | 0.2% |
| **SERVED** | **40** | **0.98%** |

**4,096 valid configurations; 40 served.** *(historical — WO-CM1
replaced this denominator; see the note above.)*

**These percentages are refusal-category shares, not usage frequencies.**
There is no production telemetry here. "P1 first" is a **prioritisation
judgement** — `mode="python"` is the documented default, so it is the most
likely to be encountered — not a measured ordering. Nothing downstream should
read these numbers as demand data.

---

## 2. Genuine gap vs. correct decline

100% of cells is **not** the right target: the envelope exists to avoid
accepting invocations it cannot honour, so declining is a feature. Each
candidate is classified before any work is scheduled.

| candidate | classification | reasoning |
|---|---|---|
| `mode="python"` | **genuine gap** | The default mode. A plain `forkrun.map(fn, path)` never reaches the launcher. Largest gap by likelihood of being encountered. |
| NUMA (`nodes > 1`) | **genuine gap** | Publicly reachable; `detect_numa_nodes()` returns a real node list on NUMA hardware. |
| `orchestrator=False` | **genuine gap** | A documented supervision *model*, not an error. |
| `stream(order="index")` | **genuine gap** | Reachable; declined only for want of a mechanism — see P2, which is **not** small. |
| `stream(strict_poison=True)` | **genuine gap** | Reachable; requires wiring a channel the cleanroom stream path does not have. |
| `mode="spawn"` | **genuine gap, scope TBD** | Reachable. W-EXP-3 is thinly specified. |
| `resume` / `checkpoint_file` | **genuine gap, hardest** | Reachable. May require the frozen engine — see §5. |
| `mode="splice"` | **DISPOSITION PENDING MEASUREMENT** | Previously called a correct decline. That was premature: the argument covered only the missing *Python payload hook*, and ignored that the cleanroom's other benefit — **not forking workers from an enormous Python parent** — may still apply to a C-only mode. Measure startup and throughput across representative parent RSS sizes (the existing results span ~30 MB to >2 GB). If negligible, or outside the feature's purpose, record the refusal **with that evidence**. |

**Proposed target: 100% of genuine gaps, plus an evidence-backed disposition
for `splice`.**

---

## 3. Sequencing

Ordered by practical value and feasibility, not cell volume.

| # | item | volume | frozen engine? | why here |
|---|---|---|---|---|
| **P1** | `mode="python"` (UDF) | 37.5% | no | Default mode; developable and validatable on ordinary hardware; unblocks the packaging decision (§6). |
| **P2** | `stream` parity | 0.6% | no | Small in volume, **not** small in design — see below. |
| **P3** | `orchestrator=False` | 6.2% | no | Self-contained in `forkrun_cleanroom.c`. |
| **P4** | `mode="spawn"` | 12.5%¹ | no | Depends on P1's worker plumbing being generalised. |
| **P5** | NUMA | 50.0% | no² | Largest volume, but fake NUMA does not prove physical placement, locality, or distance-scaled stealing. Later for **validation** reasons. |
| **P6** | `mode="splice"` | 12.5%¹ | no | Measurement + decision, not necessarily implementation. |
| **P7** | `resume` / `checkpoint_file` | 4.7% | **possibly** | See §5. Last, so the freeze decision rests on its own evidence. |

¹ per-mode share of the 37.5% `DECLINE_MODE` block.
² **for the certificate**, see §5a.

---

## 4. Items P1–P4, P6

### P1 — `mode="python"`, UMA

Serve the default mode. A CPython-linked helper `.so`, `dlopen`ed by the
launcher **only in UDF mode**; substrate and launcher stay Python-free. All of
W-EXP-1 stands: module-level functions only, `__name__`/`__qualname__ ==
attr_name`, aliased re-exports rejected, per-candidate import contract,
`--caller-minor` handoff, module-scope compile.

**Blocked on §6**: packaging feasibility must be established before P1
implementation, not assumed.

### P2 — `stream()` parity — **re-specified; larger than previously stated**

The previous draft called this "small, and `map()` already proves both
mechanisms". That was wrong on both counts, and the corrections matter because
naively porting `map()`'s solutions would silently change streaming semantics.

**`stream(order="index")`.** The cleanroom stream path today only *drains*:
results are yielded as they arrive, unsorted and unreconstructed. Two options:

* **Final parent-side sort** — correct ordering, but buffers the entire
  result and delays all output until completion. That destroys streaming's
  latency *and* memory characteristics. Acceptable **only** if that change is
  explicit and stated.
* **Incremental reassembly** — emit a contiguous ordered prefix as it becomes
  available. This is the option that preserves streaming, and it is the harder
  one: the parent must know **when a batch is legitimately complete with no
  output**. Otherwise "no record" is ambiguous between *this batch produced
  nothing* and *this batch has not arrived yet* — and choosing wrongly either
  stalls forever or emits out of order.

**No-output batches are real, not hypothetical.** Measured: a UDF returning
`None` for half its batches produced **0 records against 100 published slots**
(`total=0, completed=0, poisoned=0` — not poisoned-and-skipped; simply absent).
Any incremental scheme must therefore carry explicit completion information
per batch, and must give **poisoned batches and `on_error="skip"` the same
explicit treatment** — a skipped batch is complete-with-no-output, not
missing.

**`stream(strict_poison=True)`.** The cleanroom stream argv passes **no
`--stats-fd`** (`run.py:1515`). This is not a dropped return value. P2 must:
add the statistics descriptor to the streaming launch contract; read it when
the launcher completes; and enforce strict-poison **without disguising a
launcher failure as a normal EOF** — the poison count and the launcher's exit
status are independent facts and conflating them would convert a crash into
silent truncation, which is the exact failure class CR-FIX1-G removed.

**`stream` may therefore turn out to require a protocol change, not just
parent-side code.** That is a scope increase over the previous draft and is
accepted.

### P3 — `orchestrator=False` — separate supervision path, with a contract

The launcher supervises unconditionally (W-CR4 added death pipes, respawn,
trap-ACK). Declining `orchestrator=False` is currently correct: silently
supervising hands a caller who asked for fail-fast a repaired run they cannot
detect.

Design: a **separate code path**, not a flag inside the existing supervisor.
A flag is one missed branch away from applying recovery to a caller who
declined it.

**Required before implementation — an explicit behavioural contract** covering:
worker death, exit status, retries, skipped batches, and cleanup. Tests must
**pin the requested supervision model**, not merely demonstrate that the
launcher returns an error.

**`orchestrator` and `on_error` are different axes and must not be conflated.**
`orchestrator` selects the *supervision model* (recovery-by-wid vs
fail-fast). `on_error` selects the *payload error policy*
(`retry` / `fail-fast` / `skip`). A `orchestrator=False` run may still use
`on_error="retry"`, and an `orchestrator=True` run may still use
`on_error="fail-fast"`. Naming both "fail-fast" is how they get accidentally
merged.

### P4 — `mode="spawn"`

Unchanged in intent; scope still needs specifying. Depends on P1's worker
plumbing being generalised rather than duplicated.

### P6 — `mode="splice"` — measure, then decide

Per §2: measure startup and throughput across representative parent RSS sizes
before recording any refusal.

---

## 5. P7 — resume/checkpoint

Current state, verified:

* **Not greenfield.** `python/forkrun/_resume.py` implements resume for
  in-process C-orderer paths: path gating, resume-begin, abort choreography
  with bounded waits, fail-closed sidecar for already-committed output.
* **Stated contract:** engine commit is exactly-once (the C orderer's
  committed output frontier, byte coordinates, surviving abort+resume without
  duplication); **Python consumption is not**.
* `require_resume_path` (`_resume.py:72`) permits resume only for
  `num_nodes == 1`, `order == "index"`, non-splice, collect paths.
* **`forkrun_cleanroom.c` contains zero references to resume.**

**The obstacle.** The frontier is owned by `TRACK_COMPLETED_BATCH` in
`ring_order_main` — inside frozen `forkrun_ring.c`.

**The candidate engine-free route.** The cleanroom runs no C orderer, so its
resume semantics could be defined by a **launcher-owned ledger**, and
`forkrun_cleanroom.c` is unfrozen.

**But the previous draft's justification does not hold.** It said "the
launcher knows exactly what it emitted and in what order". Knowing output
records and their order is **not** the same as knowing which *input byte
ranges* are durably committed. Those are different pieces of state, and the
gap between them is exactly where resume goes wrong.

**Required before implementation — a feasibility prototype** must establish
all of:

1. Each committed batch maps to the same **byte-coordinate frontier and jagged
   intervals** the existing checkpoint format uses.
2. Complete records are distinguished from **partial writes and worker
   deaths**.
3. `None` output, `skip`, `poison`, and `retry` are each handled **without
   advancing the frontier incorrectly**.
4. The ledger and the committed-output sidecar survive each crash window the
   current implementation supports.
5. Checkpoints and resumed output are **observably equivalent** to the
   in-process path, by direct comparison.

This is a **proof obligation**, not an implementation commitment. Do not
implement the ledger or advertise cleanroom resume until equivalence is
demonstrated. **If it cannot be established without changing the frozen
engine, keeping resume in-process-only is a justified final decision** — not a
failure of the plan.

---

## 5a. P5 — the ordered-output certificate must be re-derived

The C0.7 design proposed `emitted_records == published_slots` with `write_idx`
from `fr_py_diag_node`. **That certificate is wrong as stated**, and the
measurement above is why.

The correct unit is **order packets**, not payload records: an order packet
certifies a batch's completion *even when its payload is empty*. The design
must therefore specify:

* the **one-order-packet-per-batch** completion contract;
* how `None` output, `skip`, `poison`, and `retry` each appear — all of them
  **completed-but-empty**, never silently absent;
* that the certificate verifies the **expected key sequence**, not equal
  totals. **A missing packet and a duplicate packet have the same total**, so
  a count comparison cannot distinguish them and would pass a corrupted run.

The underlying premise is sound and was measured: the orderer does **not**
coalesce — the *scanner* does. Emitted-record count tracked `ceil(n/lines)`
exactly across `lines=1/10/100`. That is why one record per published slot is
the right shape; only the *observability* of that count was wrong.

**P5 stays blocked** until the certificate proves completeness against the key
sequence — with the frozen engine untouched, or with the freeze explicitly
revisited.

---

## 6. Packaging — abi3 is an experiment, not the plan

**The previous premise was false and is retracted.** It rested on `PyConfig`
being in the limited API as of 3.10. Compiling with
`-DPy_LIMITED_API=0x030A0000` fails outright:

```
error: unknown type name 'PyConfig'
```

`PyConfig` is **not** part of the limited API. PEP 741's opaque
initialisation API (`PyInitConfig`, new in 3.14) does not retroactively make
the older structure API available under a 3.10 `abi3` target. Listing
`PyConfig` among "stable symbols" was not a basis for anything.

**Therefore:**

* **`abi3` is an experiment.** Before it can be the packaging path, a
  prototype must compile under the **minimum** limited-API target and
  demonstrate the required **isolated initialisation** semantics using only
  Stable-ABI surface. That is genuinely hard: the obvious isolation levers
  (`Py_SetProgramName`, `PySys_SetArgv`) are deprecated and removed in 3.13+.
* **If it fails: interpreter-specific wheels.** Do not weaken the runtime
  contract to make a tag fit.

**A contract conflict to resolve.** The accepted roadmap requires refusing a
caller/helper CPython-minor mismatch. That is correct for a minor-specific
helper and **defeats the purpose of `abi3`** if applied unchanged to a helper
that genuinely supports several minors. The runtime check must follow the
selected model: **exact minor matching** for per-minor helpers, or **genuine
ABI-compatibility checking** for a proven stable-ABI helper.

**The build workflow does not yet run the claimed matrix.** `3.15.0` shipped
2026-10-09, but `tools/build_wheel.sh:91-96` still selects from a hardcoded
newest-first list of `cp314 / cp313 / cp312` with the comment "3.15 is an rc in
this image — skip". So 3.15 is not exercised. **Prerequisite: add `cp315` to
the candidate list and refresh the build image.** Note this becomes
*load-bearing* only once a CPython-linked helper exists — today the wheel
build's interpreter is irrelevant because the substrate is ctypes-loaded and
interpreter-agnostic.

---

## 7. Freeze policy — `_shim.c` is engine-affecting

`python/forkrun/_shim.c:36` does `#include "../../forkrun_ring.c"`: the shim
**compiles the engine translation unit directly**. `forkrun_ring.c` stays
byte-identical, so `check_engine_frozen` passes, while unfrozen shim edits can
still change engine behaviour.

Unchanged bytes in `forkrun_ring.c` therefore **do not** prove that a
`_shim.c` change is engine-behaviour-preserving.

**Policy — stronger than a commit-message convention.** Every `_shim.c`
change must state, in the change itself:

1. **which existing engine operation it exposes**;
2. **what engine behaviour must remain invariant**; and
3. **what test demonstrates that invariant**.

For P5 specifically, the new node-taking entry points must be **additive
wrappers around the existing node-aware operation**, not incidental
behaviour changes reaching the engine through the shared translation unit.

This is a review requirement, not an argument that P5 is impossible. If a hard
boundary is preferred instead, the alternative is extending `FROZEN_FILES` to
`_shim.c`, at the cost of P5.

*Verified:* `_shim.c` contains **no** `Python.h` include (an apparent hit is
the comment "Python had", matched by a regex whose `.` acted as a wildcard).
The shim is ctypes-facing and interpreter-agnostic, which is what makes §6's
constraint real.

---

## 8. Sequencing constraints

* The **shared launcher-supervision interface** (roadmap §3) must be specified
  before **both** P3 and P5 begin — they each touch supervision.
* The **ordered-output certificate** (§5a) must be correct before P5 declares
  NUMA ordering complete.
* Interpreter matrix is **3.10–3.15**, and must exist in the build/test
  workflow (§6), not only on paper.
* Every item keeps its own opt-in envelope until its own **independent**
  default-on gate passes. Coverage is not default-on.
* **The oracle must not define correctness by first-decline-reason.** A
  configuration may have several unsupported properties; if the matrix records
  only whichever reason `_cleanroom_eligible()` returns first, then reordering
  the predicate **shifts the reported categories without improving coverage**.
  The oracle establishes the *intended status* per configuration; decline
  reasons are explanatory output, not the definition.

---

## 9. What "done" means

* Every **genuine gap** in §2 is served, or carries a recorded, evidenced
  refusal.
* `mode="splice"` has an explicit disposition backed by measurement.
* The regenerated capability matrix shows only *justified* declines, with the
  independent oracle in `tools/capability_oracle.py` extended to match —
  "justified" meaning "agreed with a table written from the contract", and
  **not** meaning "agreed with the predicate's own reason ordering".
* Negative-input cases (missing path, directory, bad type) retain their own
  error-conformance coverage, separate from the capability denominator.
* P7 either ships engine-free with equivalence demonstrated, or produces the
  explicit argument for revisiting the freeze.

---

## 10. Carried-forward questions

Amendment round 1 answered the previous six. Remaining, for the next round:

1. **Is P2's incremental reassembly feasible at all**, or does honest
   streaming ordering require accepting whole-result buffering? The
   no-output-batch ambiguity may force the latter.
2. **Should `orchestrator=False` be its own launcher binary or mode?** A flag
   is smaller; a separate path is safer. This plan assumes the latter.
3. **Is `splice` measurement cheap enough to do early** rather than at P6? If
   the answer is "splice should stay declined", that is worth knowing before
   P1 rather than after.
4. Does the §5a order-packet certificate remain engine-free once poison/skip
   and duplicate-detection are handled — or does *that* requirement, rather
   than resume, become the first genuine need to revisit the freeze?
