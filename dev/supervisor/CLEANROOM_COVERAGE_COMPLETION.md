# Cleanroom coverage completion plan

**Status: PROPOSAL — for external review. Nothing here is implemented.**
Companion to `CLEANROOM_EXPANSION_ROADMAP.md` (accepted, rounds 1–7), which
defines the envelope, the contracts and the expansion work items W-EXP-1/2/3.

---

## 0. The goal, restated

The intent behind this work is **complete coverage**: the cleanroom launcher
should serve the whole reachable public API, and every refusal should be a
refusal the system can justify rather than a gap nobody has closed yet.

The accepted roadmap does **not** deliver that. It covers
`mode ∈ {plugin→python→spawn}` plus NUMA. It does not address
`orchestrator=False`, `resume`/`checkpoint_file`, `mode="splice"`, or the two
narrowed `stream()` gates. This plan closes all of it.

---

## 1. Measured baseline — reachable API only

The C0.1 capability matrix enumerates 16,128 cells, but two of its axes carry
values the public API **cannot produce**, so it overstates the gap:

| matrix axis value | reachable? | why |
|---|---|---|
| `order` outside `("none","index")` | **no** | `_VALID_ORDERS` rejects it at `_api.py:168`, raising `ValueError` before the envelope is consulted. `DECLINE_ORDER` (224 cells) is a **defensive guard on an internal invariant**, not a user-reachable gap. |
| source `missing` / `dir` / `bogus` | **no** | these are invalid calls. Declining them is correct and permanent. |

Re-enumerated over the reachable surface only — the type surface at
`_api.py:21-31`: `Mode = {python, spawn, plugin, splice}`,
`Order = {none, index}`, `Nodes = int | str | None` (`"@N"`, `"0,1"`, `N`),
`OnError = {retry, fail-fast, skip}` — plus four valid source kinds:

| outcome | cells | % of reachable |
|---|---|---|
| `DECLINE_NODES` (NUMA) | 2048 | **50.0%** |
| `DECLINE_MODE` (`python`/`spawn`/`splice`) | 1536 | **37.5%** |
| `DECLINE_ORCH` (`orchestrator=False`) | 256 | **6.2%** |
| `DECLINE_RESUME` | 192 | **4.7%** |
| `DECLINE_STREAM_ORDER` | 16 | 0.4% |
| `DECLINE_STREAM_POISON` | 8 | 0.2% |
| **SERVED** | **40** | **0.98%** |

**4,096 reachable cells; 40 served.**

---

## 2. Genuine gap vs. correct decline — the distinction this plan turns on

100% is the stated goal, but **100% is not automatically the correct target**.
The envelope's contract is that it must not accept an invocation it cannot
honour; declining is a feature, not only a failure. So each candidate gap is
classified before any work is scheduled:

| candidate | classification | reasoning |
|---|---|---|
| `mode="python"` | **genuine gap** | The *default* mode. A plain `forkrun.map(fn, path)` never reaches the launcher today. This is the single largest gap by real-world frequency. |
| NUMA (`nodes > 1`) | **genuine gap** | Publicly reachable (`nodes="@2"`, `N`, `"0,1"`); `detect_numa_nodes()` returns a real node list on NUMA hardware. Work exists but is unfinished (W-EXP-2). |
| `orchestrator=False` | **genuine gap** | Reachable and meaningful: legacy fork-and-wait/fail-fast is a documented supervision *model*, not an error. |
| `stream(order="index")` | **genuine gap** | Reachable; the stream path declines only because it has no collect step to sort with. |
| `stream(strict_poison=True)` | **genuine gap** | Reachable; `map()` serves it via the counter channel, so the capability already exists and only the streaming path lacks it. |
| `mode="spawn"` | **genuine gap, scope TBD** | Reachable. Dynamic worker spawning. W-EXP-3 exists but is thinly specified. |
| `resume` / `checkpoint_file` | **genuine gap, hardest** | Reachable — but see §5. May require the frozen engine. |
| `mode="splice"` | **CORRECT DECLINE — decide explicitly** | Splice is a kernel passthrough with **no payload hook** (`_api.py:204`): no UDF runs, no sink exists. There may be nothing to accelerate. "Always declines" must become a *recorded decision with a stated reason*, not an accident of never being looked at. |

**Proposed target: 100% of genuine gaps, plus an explicit, reasoned decision
for `splice`.** Not "100% of cells" — that would mean serving invocations the
launcher cannot honour, which the envelope exists to prevent.

---

## 3. Sequencing, and why this order

Ordered by *real-world frequency × feasibility*, not by cell volume. NUMA has
the largest volume but is last-ish because it cannot be validated without
multi-socket hardware.

| # | item | volume | needs frozen engine? | why here |
|---|---|---|---|---|
| **P1** | `mode="python"` (UDF) | 37.5% | no | The default mode. Highest frequency of any item; also unblocks the packaging decision (§6). |
| **P2** | `stream` parity (index + strict_poison) | 0.6% | no | Small, and `map()` already proves both mechanisms. Cheap confidence. |
| **P3** | `orchestrator=False` | 6.2% | no | A launcher flag plus a second supervision loop. Self-contained in `forkrun_cleanroom.c`. |
| **P4** | `mode="spawn"` | 12.5%¹ | no | Depends on P1's worker plumbing being generalised. |
| **P5** | NUMA | 50.0% | no¹ | Largest volume; needs node-taking loops (`_shim.c`, unfrozen) and multi-node validation. |
| **P6** | `mode="splice"` | 12.5%¹ | no | Decision + record, not necessarily implementation. |
| **P7** | `resume` / `checkpoint_file` | 4.7% | **LIKELY** | See §5. Deliberately last. |

¹ per-mode share of the 37.5% `DECLINE_MODE` block.

---

## 4. Items P1–P3, P6 (engine-free)

### P1 — `mode="python"`, UMA

Serve the default mode. Requires a CPython-linked helper `.so`, `dlopen`ed by
the launcher **only in UDF mode**; substrate and launcher stay Python-free
(standing constraint §2). Everything in W-EXP-1 stands: module-level functions
only, `__name__`/`__qualname__ == attr_name`, aliased re-exports rejected,
per-candidate import contract, `--caller-minor` handoff, module-scope compile.

*Not a re-plan of W-EXP-1 — this is the item that makes it reachable.*

### P2 — `stream()` parity

Two narrow declines, both already solved for `map()`:
* `order="index"` — needs a collect/sort step. The roadmap notes the launcher
  avoids the C orderer **for memory reasons**; P2 must not reintroduce that
  cost, so the sort is parent-side (as `stream()` already does for
  `order="none"` via `batch_idx` reassembly), not an orderer.
* `strict_poison` — the counter channel already carries `[version][poisoned]`
  to the parent; the streaming path simply discards it. Thread it to the
  caller instead.

### P3 — `orchestrator=False`

The launcher supervises unconditionally (W-CR4 added death pipes, respawn and
trap-ACK). Serving the legacy model means giving it a **non-supervised mode**:
plain fork-and-wait, fail-fast, no `ring_recover_worker`. Declining it today is
correct because "silently supervising anyway" hands a caller who asked for
fail-fast a repaired run they cannot detect.

**Open design question:** a flag on the existing supervisor, or a genuinely
separate code path? The second is safer (no risk of the flag being ignored in
one branch) and is what this plan assumes.

### P6 — `mode="splice"`

Decide and record. Proposed disposition: **remain declined, with the reason
stated** — a passthrough with no payload hook has no per-batch work to place
off the caller's thread, so acceleration would be the ordinary reactor wearing
a different name. If the reviewer disagrees, this becomes an implementation
item like P4.

---

## 5. P7 — resume/checkpoint: the one item that may need the frozen engine

**This is the item most likely to force the freeze decision, and it is
deliberately scheduled last so that decision is made on its own evidence
rather than as a side effect of P1.**

Current state, verified:

* Resume is **not greenfield.** `python/forkrun/_resume.py` implements it for
  in-process C-orderer paths: path gating, resume-begin, abort choreography
  with bounded waits, and a fail-closed sidecar for already-committed output.
* It carries a stated semantic contract: **engine commit is exactly-once**
  (the C orderer's committed output frontier, byte coordinates, surviving
  abort+resume without duplication); **Python consumption is not** (a crash
  between commit and observation skips bytes the caller never received).
* `require_resume_path` (`_resume.py:72`) permits resume only for
  `num_nodes == 1`, `order == "index"`, non-splice, collect paths.
* **`forkrun_cleanroom.c` contains zero references to resume.** The launcher
  has no resume support at all.

**The obstacle.** The exactly-once frontier is owned by the engine:
`TRACK_COMPLETED_BATCH` in `ring_order_main` — inside `forkrun_ring.c`, which
`release_check.py:51` freezes.

**The candidate engine-free route.** The cleanroom runs **no C orderer**;
`order="index"` is satisfied by sorting in Python. So the cleanroom's resume
semantics would be defined by a **launcher-owned ledger** rather than the
orderer's, and `forkrun_cleanroom.c` is unfrozen. The launcher knows exactly
what it emitted and in what order, so an equivalent "committed output
frontier" is expressible.

**Why this is not simply "do it":** it would produce **two resume contracts** —
the orderer's and the launcher's — that must be observably equivalent or the
same public API means different things depending on which path served it.
That is a correctness surface, not a plumbing detail.

**Questions for review, to be answered before P7 starts:**
1. Is a launcher-owned ledger *provably* equivalent to the orderer's, or only
   similar? What would "provably" require?
2. If it cannot be equivalent, is a second documented contract acceptable, or
   must resume stay in-process-only?
3. Only if the answer to (2) is "must be equivalent" **and** (1) is "no" does
   the frozen engine become unavoidable — and that is the explicit argument
   §5 of C0.7 demands before the freeze is revisited.

---

## 6. Packaging — a decision to record before P1

The substrate ships interpreter-agnostic because it is `ctypes`-loaded.
`forkrun_cleanroom.c` and `_shim.c` do not include `Python.h`. A helper linked
to the **builder's** `libpython3.X` is therefore not version-agnostic, and
building it from the sdist does not make the wheel honest — the binary still
carries the builder's minor under a tag claiming otherwise.

**Proposed: build the helper against the CPython stable ABI (PEP 384).**
One wheel, tag `cp310-abi3-<platform>`, covering 3.10–3.15, installable with
no compiler, and the tag states its own constraint truthfully — which is the
exact failure the per-minor and source-only options exist to avoid.

Feasibility rests on the helper being **new code with no legacy constraints**,
needing only `PyConfig`, `Py_Initialize`, `PyImport_ImportModule`,
`PyObject_Call`, `PyBytes_AsStringAndSize`, `Py_DecRef` — all in the limited
API as of 3.10.

**Not yet proven.** No abi3 helper has been built. The C0.4 prototype is what
would demonstrate it; if it fails, the fallback is per-minor wheels.

---

## 7. A note on where the freeze is porous

`python/forkrun/_shim.c:36` does:

```c
#include "../../forkrun_ring.c"
```

The shim **compiles the engine translation unit directly**. `forkrun_ring.c`
stays byte-identical — so `check_engine_frozen` (which watches only that file's
git status and history) passes — while `_shim.c`, being unfrozen, can still
change engine *behaviour*.

This matters for P5. The NUMA node-taking worker loops are planned for
`_shim.c` precisely because it is unfrozen, and on the evidence above that is
legitimate rather than a loophole **only if** the change is additive and
engine-behaviour-preserving. It is not self-policing: nothing stops a later
edit from altering engine semantics through the include.

**Recommendation:** treat `_shim.c` changes as engine changes for *review*
purposes even where the freeze permits them, and say so in the commit message.
If the reviewer prefers a hard boundary, the alternative is to extend
`FROZEN_FILES` to include `_shim.c` — at the cost of P5.

*Verified while writing this:* `_shim.c` contains **no** `Python.h` include
(an apparent hit is the comment "Python had", matched by a regex where `.`
acted as a wildcard). The shim is ctypes-facing and interpreter-agnostic, which
is what makes §6's packaging constraint real.

---

## 8. Sequencing constraints carried forward

* The **shared launcher-supervision interface** (roadmap §3) must be specified
  before P3 and P5 both begin — they both touch supervision. Starting them
  without it recorded is how two branches end up rewriting the same supervisor.
* The **ordered-output completion certificate** (C0.7, designed) must be in
  place before P5 declares NUMA ordering complete. Its design needs **no engine
  change**: `emitted_records == published_slots`, with `write_idx` from the
  existing `fr_py_diag_node`.
* Interpreter matrix is **3.10–3.15** (3.15.0 released 2026-10-09).
* Every item keeps its own opt-in envelope until its own independent default-on
  gate passes. Coverage is not default-on.

---

## 9. What "done" means for this plan

* Every **genuine gap** in §2 is served, or has a recorded, reasoned refusal.
* `mode="splice"` has an explicit recorded disposition.
* The capability matrix, regenerated, shows only *justified* declines — and
  the independent oracle in `tools/capability_oracle.py` is extended to match,
  so "justified" means "agreed with a table written from the contract".
* P7 either ships engine-free, or produces the explicit argument for revisiting
  the freeze that the roadmap requires before the engine is touched.

---

## 10. Questions for the reviewer

1. **Is the genuine-gap / correct-decline split in §2 right?** Specifically:
   is `mode="splice"` correctly a permanent decline, and is 100%-of-genuine-
   gaps the right target rather than 100%-of-cells?
2. **Is P1-before-P5 the right order?** The argument is frequency (the default
   mode) over volume (NUMA). If NUMA's 50% should dominate, say so.
3. **Is a launcher-owned resume ledger (§5) a sound idea to even prototype,**
   or should P7 be scoped from the outset as "resume stays in-process unless the
   freeze is revisited"?
4. **Is the abi3 packaging proposal (§6) sound**, and is its risk properly
   bounded by falling back to per-minor wheels?
5. **Is P3's "separate supervision code path, not a flag" the right call?**
6. Anything in §1's reachability analysis that is wrong — particularly whether
   `order` outside `("none","index")` or the invalid-source rows can in fact be
   reached and should be counted as gaps.
