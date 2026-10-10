# Cleanroom Expansion Roadmap — `NEW/REFACTOR4.2`

**Purpose.** A reviewable plan for widening the Python cleanroom launcher beyond
the UMA C-plugin envelope it serves today, and for eventually enabling it by
default. **No implementation begins until this document is accepted**, and the
acceptance that matters is the one that has already happened three times: an
external AI reading the source and refuting what is wrong.

**Supersedes.** The first draft of this document, which carried two `[V]` claims
that were false on first contact. See §12.2 — the correction history is part of
the evidence.

**Base state:** `NEW/REFACTOR4.2`, carrying CR-FIX1 (7 commits on
`NEW/REFACTOR4.1`). Function names are the authorities; line numbers are given
as evidence and may drift.

**Review history: five rounds completed, all amendments accepted.** Round 1
raised ten findings, all accepted. Round 2 accepted all ten, raised one blocking
finding (the node-0 worker assignment), and made one scope correction. Round 3
accepted the clarifications. Rounds 4 and 5 made targeted amendments for internal
consistency — a resolver/coverage mismatch, an M2 import-contract contradiction,
a false "share no code" claim, an incomplete dependency graph, an incomplete
capability set, and four contract-preciseness fixes. No round requested a
redesign; every finding was a correction to something specific.

---

## 0. How to review this document

### 0.1 Tag vocabulary, and a warning about it

| Tag | Meaning |
|---|---|
| **[V]** | **Verified** — evidence given **inline**, as `file:line` or as a measurement |
| **[H]** | **Hypothesis** — reasoning over verified facts, not measured |
| **[M]** | **Needs measurement** — unknown; must be measured before dependent work is designed |

**[V] Every `[V]` tag in the previous draft of this document was wrong on first
contact — twice.** A `[V]` invites agreement where an `[H]` invites checking,
which makes an erroneous `[V]` more dangerous than an admitted guess. So:

* **`[V]` claims here carry inline evidence rather than a reference to one.**
  Reviewers should be able to check each without navigating.
* **Reviewers should spot-check `[V]` claims, not sample them.** The two prior
  errors were found by a reviewer reading code this author had read and
  mis-generalised; neither was found by sampling.
* **A claim that turns out false is a finding about the document, not about the
  reviewer.** Record which tag it carried.

### 0.2 What was wrong before, as a calibration aid

| Claim | Tag | Actual | How found |
|---|---|---|---|
| "workers self-pin from `getcpu()`" (§6.2) | **[V]** | **False.** The C loops hardcode logical node 0 (`_shim.c:2865`, `:3018`). The self-pinning claim is true of bash's `ring_worker inc`, a different entry point | Round 3 reviewer |
| "the ~100 ms is a circular wait on spare pipe write ends" (`_cleanroom_enabled`, pre-CRFIX1) | comment | **Refuted.** Those close only after the supervision loop exits, which happens at `live == 0` | CR-FIX1 measurement |

The common shape: a claim about one code path generalised to a sibling path.

---

## 1. Where the feature stands

| Property | State |
|---|---|
| Serves | `mode="plugin"` (C `.so`, ctx dialect v1/v2), UMA, `orchestrator=True` |
| Declines | `mode="python"` (**the default mode**), spawn, splice, multi-node, `resume=`, `checkpoint_file=`, `orchestrator=False` |
| Gate | `FORKRUN_CLEANROOM`, **default OFF** |
| Tests | 70/70 cleanroom, 0 skips; 738 full suite **[V]** (measured) |
| Measured | startup 1.57×–10.25×, throughput 1.56×–3.78× vs in-process, across 30 MB–2127 MB parent RSS, both THP regimes **[V]** (measured; recorded in `DOCS/CHANGELOG.md`) |

### 1.1 "Default on" is three decisions, not one

**[V]** Enabling the `FORKRUN_CLEANROOM` gate today would change nothing for
any non-plugin caller: they reach `_cleanroom_eligible`, decline, and take the
in-process path unchanged. Verified by predicate inspection — `mode="python"`
declines with *"mode='plugin' only"*, `orchestrator=False` declines, and
`resume=` declines.

So "make it the default" decomposes into three independently-gated decisions:

1. enable for `mode="plugin"` — small, well-tested blast radius;
2. enable for `mode="python"` — the default mode, largest population;
3. enable for multi-node — thinnest validation.

**Each gets its own evidence gate, its own commit, and its own revert.**

---

## 2. Standing constraints

Unchanged and **not negotiable**:

* **The ring engine stays frozen.** `forkrun_ring.c` is not modified. If a
  requirement below can only be met by changing it, the constraint is
  **revisited explicitly** with a source-backed argument — not worked around.
* **The substrate stays free of `libpython`.** `libforkrun_python.so` links
  `-ldl -lrt` only **[V]** (`Makefile.substrate:44` `ALLOWED_DEPS`), enforced by
  `-Wl,--no-undefined` on both the canary (`:91`) and substrate (`:101`) rules.
  **[V]** The wheel's interpreter-independence depends on this: the substrate is
  `ctypes`-loaded, so one wheel serves 3.10–3.14.
* **`ALLOWED_DEPS` is never widened.** It is referenced by two rules, so
  extending it "for a helper" would silently legalise the dependency for the
  zero-bash-linkage artifacts. New build products get their own variable and
  their own gate.
* **The cleanroom stays opt-in** through W-EXP-1 and W-EXP-2.
* **Batch-count variance is valid.** It is pre-existing and shared with the
  in-process path. Validation compares joined bytes or independently known
  record identities, never blob counts.
* **`_shim.c` changes are permitted only to expose an operation that already
  exists**, or to fix a defect in the Python wrapper. W-EXP-2's node-taking
  worker loop qualifies: `fr_py_worker_init` already accepts `node_id`
  (**[V]** `_shim.c:244`) and the Python paths already supply it (**[V]**
  `_worker.py:324`, `_reactor.py:760`).

---

## 3. Sequencing

```
        ┌───────────────────────────────────────────────┐
        │ Phase 0 — contracts, instrumentation, M1/M2    │
        │   (no production behaviour changes)            │
        │   C0.1 capability matrix                       │
        │   C0.2 trace facility                          │
        │   C0.3 UDF eligibility + import contract       │
        │   C0.4 CPython fork-lifecycle prototype        │
        │   C0.5 interpreter matrix gate (3.10-3.14)     │
        │   C0.6 M1/M2 measurement                       │
        │   C0.7 ordered-output certificate (design only)│
        └───────┬───────────────────────────┬───────────┘
                │ gates                     │ gates
   ┌────────────▼────────────┐   ┌──────────▼───────────────┐
   │ W-EXP-1  Python UDF     │   │ W-EXP-2  NUMA             │
   │ (UMA, module refs only) │   │ (needs the live ordered-  │
   └────────────┬────────────┘   │  output fix first)       │
                │                └──────────┬───────────────┘
                └────────┬───────────────────┘
                         │ requires both independently correct
                ┌────────▼────────────┐
                │ W-EXP-1.5 UDF+NUMA │
                └────────┬────────────┘
                         │
                ┌────────▼────────────┐
                │ W-EXP-3  spawn-pipe│   perf only
                └────────┬────────────┘
                         │
                ┌────────▼────────────┐
                │ W-EXP-4  default-on│   3 independent decisions
                └─────────────────────┘
```

**[V] Workstreams have separate acceptance gates, but they are NOT independent
in code.** The previous revision claimed W-EXP-1, W-EXP-2 and W-EXP-3 "share no
code", which its own later sections contradict:

* §6.3 — W-EXP-2 must add **per-worker death pipes** to the launcher.
* §7 — W-EXP-3 requires `poll()` over the spawn pipe **plus per-worker death
  pipes**, replacing the current blocking `waitpid(-1)` supervision.

Those are shared launcher-supervision infrastructure. **Either the shared
supervision interface is specified and frozen in Phase 0, or one branch is
integrated and rebased before the other.** Which is decided in Phase 0; the
acceptance gates stay separate either way.

#### Hard dependency graph (corrected — the previous list was incomplete)

* **Phase 0** contracts and measurements gate the expansion work they inform.
* **The ordered-output completion defect gates W-EXP-2** (§4.7). It is live in
  shipping code and W-EXP-2 may not proceed on a design that cannot establish
  completeness.
* **The shared launcher-supervision interface gates W-EXP-2 and W-EXP-3**
  (§3, above).
* **W-EXP-1.5 requires W-EXP-1 and W-EXP-2 to have passed independently.**

The W-EXP-1-first preference is a **priority**, not a hard dependency: if
parallel development is used, W-EXP-2 may proceed once the ordered-output item
and the supervision interface are in place.

**Why this priority order.**

* **Phase 0 is contract work**, because every substantive design question
  downstream was answered by a measurement nobody had taken, and CR-FIX1 spent
  three rounds undoing a hypothesis that had hardened into a narrative.
* **W-EXP-1 is prioritised first** on population: `mode="python"` is the
  default and the largest user base. Until it is served, "default on" means an
  accelerator the default path never uses.
* **W-EXP-2 is gated on the live ordered-output fix** (§4.7) because that
  defect is reachable in shipping code today, independently of any cleanroom
  work.
* **W-EXP-3 last** because it is a performance refinement, not a capability, and
  it carries the roadmap's only *silent* failure mode (§7).

**[H] This ordering is a judgement, not a derivation.** A reviewer who believes
breadth-of-blast-radius should precede breadth-of-population should say so.

---

## 4. Phase 0 — contracts, instrumentation, measurement

**No production behaviour changes.** Exit gate: every contract below is
reviewable, and every prototype either passes or is explicitly reported as not
passing. **No throughput claim is required to exit this phase.**

### C0.1 — Capability matrix

Enumerate the full cross-product and record `served / declined / unsupported /
needs-fallback` for each cell: {materialized, streaming} × {path, descriptor} ×
{plugin, python, spawn, splice} × {UMA, NUMA} × `order` × `orchestrator` ×
`strict_poison` × {resume, checkpoint} × {replayable, non-replayable} sources.

The matrix must be **generated from `_cleanroom_eligible()` and the dispatch
sites**, not hand-maintained. It is a deliverable, not an exercise.

> **[V] A generated matrix is documentation, not evidence.** A test that
> regenerates the matrix from the predicate and compares it to the predicate
> proves the generator is deterministic — it cannot show the predicate matches
> the *intended* contract. A predicate that is wrong in both the code and the
> generated table is self-consistent and still wrong.

So: keep a **separate expected-behaviour oracle** — a hand-maintained table of
what each combination *should* do, written from the API contract — and check the
generated matrix against **it**. The oracle is the test; the generator is the
document. Where they disagree, one of them is a bug.

**Acceptance:** matrix published; generated matrix compared against an
independent expected-behaviour table; a test asserts they agree.

### C0.2 — Trace facility

Opt-in via `FORKRUN_CLEANROOM_TRACE`; disabled by default; records to a memfd
allocated in the Python parent and passed as an explicitly inheritable
descriptor.

Minimum viable set: monotonic timestamp, PID, **role**, event, worker
`wid`/`wincarn`, node, result code. **No user payload bytes.**

Minimum events: launcher init boundaries; child fork request and returned pid;
child entry and exit; reap with decoded status; supervisor-loop
entry/exit/abort/respawn; fatal teardown actions; orderer entry/exit and
completion state.

The purpose is specific: **distinguish a worker blocked in the engine's ring
poll from a drain waiting for pipe EOF from a spill child waiting on the input
producer.** That is the question CR-FIX1's diagnosis could not answer without
reverting its own instrumentation.

**Acceptance:** records reconstruct pid/role/fork/reap/abort for a successful
run and an injected-failure run; test parses them; children preserve the fd
without weakening scrubbing; disabled by default and absent from benchmarks.

### C0.3 — UDF eligibility and import contract

**Eligibility for W-EXP-1: module-level functions only.**

A `"pkg.mod:func"` string resolving to a module-level function.

> **[V] Class-qualified references are NOT in the W-EXP-1 contract.** The
> existing shared resolver **[V]** (`_worker.py:136-137`) does
> `mod = importlib.import_module(mod_name)` followed by a single
> `fn = getattr(mod, func_name)`. There is no dotted traversal, so
> `"pkg.mod:Class.method"` looks for a module attribute literally named
> `"Class.method"` and cannot resolve. Claiming `staticmethod`/`classmethod`
> support here would repeat this document's characteristic error — promising
> what the code cannot deliver.
>
> Adding it is a **separate, later** change: it requires extending the
> *shared* resolver, which also changes the in-process path's behaviour from
> `TypeError` to working. That is a shipped-path behaviour change and is
> justified on its own merits, not as cleanroom scope.
>
> Worth recording precisely: `"pkg.mod:Class"` **does** resolve today, because a
> class object is callable — and would be invoked as a *constructor*, not as a
> method. That is a different contract from "reference a method", and is not
> part of W-EXP-1 either.

Explicitly **not** eligible, with a loud observable decline when the cleanroom
was explicitly requested: lambdas, closures, locally-defined functions,
**caller-supplied bound methods**, callable instances carrying mutable state,
class-qualified method references, and functions whose behaviour depends on
caller-side mutation of their module globals.

> **[V] Two different cases, kept distinct.** A *caller-supplied bound method*
> is an object graph crossing `exec` — ineligible for the structural reason
> below. A *classmethod deliberately resolved from an accepted string reference*
> would be a different case entirely, governed by whether the resolver supports
> it. Conflating them would misreport why something declines.

> **[V] Rationale for the structural limit.** `mode="python"` supports an
> arbitrary callable by fork inheritance — the payload is a live `PyObject*` in
> the parent's heap. `exec` cannot carry one. This document's first draft
> promised "the identical UDF runs unchanged on both paths", which is
> unsatisfiable for closures; that acceptance criterion is withdrawn.

#### Three categories, because not every restriction is detectable

**[V] Narrowing the documented contract does not stop the implementation
accepting what is outside it.** The resolver performs only a `callable()` check
(**[V]** `_worker.py:138`), and a class object *is* callable — so
`"pkg.mod:Class"` passes today's check and would be invoked as a constructor.
W-EXP-1 needs an **explicit preflight kind check** on the resolved object, not a
documented intention.

| # | Category | Who is responsible | Contract |
|---|---|---|---|
| **1** | **Structurally ineligible references** — lambdas, closures, bound-method objects, **classes**, callable instances | **Implementation detects and declines**, before input consumption | A preflight check on the resolved object's kind; a test proving a class reference and other unsupported callable attributes are declined pre-consumption |
| **2** | **Supported references with semantic preconditions** — importable module-level functions | **Caller**, and documented as a limitation | The caller must not rely on state the cleanroom process cannot inherit. **These are generally not detectable** and are not promised an observable decline |
| **3** | **Parity fixtures** — deterministic, replay-safe UDFs | **Tests** | Byte-identical output across both paths, as an acceptance criterion for these fixtures |

> **[V] Category 2 cannot be reduced to category 1.** Whether a function depends
> on caller-mutated globals, process-local state, a caller-seeded random
> generator, or the environment is **not a decidable property of an importable
> reference**. A module-level UDF returning `os.getpid()` is structurally
> perfect and will legitimately differ between paths; one using caller-seeded
> randomness can diverge after a fresh import. **Promising automatic detection
> here would be the same class of error as promising byte-identity for every
> module-level function.** Document these as limitations; do not fake a
> detector for them.

**What "parity" therefore means.** Byte-identical output is required for
**category 3** fixtures, and is the acceptance criterion for W-EXP-1's
deterministic corpus. It is **not** claimed for every module-level function.
The supported contract defines equivalence as *byte-identical for deterministic,
replay-safe UDFs*; category-2 behaviour is a caller obligation with a
documented failure mode.

> **This closes the M2 question's first half.** The post-fork candidate cannot
> be treated as a faster implementation of the pre-fork candidate until the
> category-2 behavioural contract is established — because per-worker imports
> can differ observably from one parent import, and neither is required to
> reproduce caller-process state.

#### Import contract — defined per candidate, not once

**[V] The previous revision's single contract was internally inconsistent.** It
required the UDF to be resolved once in the launcher, while M2's post-fork
candidate requires each worker to initialise its own interpreter. Those cannot
both hold.

| | **Pre-fork candidate** | **Post-fork candidate** |
|---|---|---|
| Before consuming input | validate **and resolve** the UDF in the launcher | validate the reference, then pass a **readiness barrier** |
| Actual module import | **once**, in the launcher | **once per worker process** |
| Fork lifecycle | CPython fork hooks where applicable | interpreter initialised *after* the worker fork |
| Startup failure | refuse before source consumption | refuse before source consumption; **no ingest until the worker readiness barrier passes** |
| Import side effects | occur once, before worker forks | **may occur independently in multiple workers** |

**The rule shared by both: no source bytes are consumed until the selected
architecture has resolved its startup requirements.** For the post-fork
candidate this means an explicit readiness barrier — not a promise that workers
eventually report status — before the spill or ingest path begins.

**[M] Open question, settled in M2, not assumed here.** Whether the post-fork
candidate can honour the *same* supported-UDF contract is unknown. Repeated
per-worker imports can have observably different effects from one parent
import, and module initialisation can depend on process-specific state. If
they are not equivalent, post-fork is **a different execution contract**, not a
faster variant of the same one, and the roadmap must say so. **Timing results
from the two candidates must not be compared as if semantic equivalence had
already been established.**

> **[V] Do not probe-then-import.** A disposable probe followed by the real
> import performs the import **twice**, and module imports can have observable
> side effects — so merely requesting the accelerator would change behaviour. A
> separate probe may exist as an opt-in diagnostic with that consequence stated.

Requirements in **both** candidates: bounded startup deadline so a hanging
import cannot hang the API call; readiness/refusal reported to the supervising
parent; **no automatic fallback after a startup failure**, because falling back
would re-enter the same unsafe path.

> **[V] Pre-fork thread detection is a PRE-FORK-candidate requirement only.**
> The previous revision listed it under "both candidates", which is wrong: in
> the post-fork candidate the launcher forks its workers **before** any worker
> initialises Python or imports the UDF, so there is no launcher-side UDF import
> whose resulting threads could need detecting before those forks. The
> post-fork candidate's equivalent obligation is the **worker-side
> initialisation/readiness contract**, not a pre-fork scan.

| | Pre-fork candidate | Post-fork candidate |
|---|---|---|
| Import-time thread detection | **required**, before the launcher forks its pipeline | **not applicable** — no launcher-side UDF import precedes the forks |
| Equivalent obligation | — | worker-side init + readiness barrier before any ingest |

> **[V] Thread detection must not equate "no Python-managed threads" with "no
> threads".** A native extension can start OS threads that never appear in
> `threading.enumerate()`. Either specify an OS-level check (`/proc/self/task`
> count versus a pre-import baseline) or document explicitly which cases the
> detector cannot rule out. A detector that reports "no threads" from
> `threading.enumerate()` alone is unsound. **[V] And the lifecycle prototype
> and its acceptance tests must exercise the candidate actually being
> evaluated** — a pre-fork hook test proves nothing about post-fork.

### C0.4 — CPython fork-lifecycle prototype

**[V] The hook requirement is scoped by whether an initialised interpreter
exists at that fork — which differs by candidate.**

| | Pre-fork candidate | Post-fork candidate |
|---|---|---|
| Launcher forks | an initialised interpreter is live in the launcher | **no initialised interpreter exists in the launcher** |
| `PyOS_BeforeFork()` / `PyOS_AfterFork_Parent()` | required, in the main thread of the main interpreter | **not applicable** — there is no interpreter to prepare |
| `PyOS_AfterFork_Child()` | required **only** for a child that will re-enter Python | required in each worker, **after** its own `fork()`, once it initialises |
| Pairing | the parent hook is required whether `fork()` succeeds **or fails** | same, for any post-fork initialisation path |

**[V] A helper that executes only C and immediately `_exit()`s is not a Python
worker.** Treating all five launcher fork sites symmetrically would be wrong: it
adds hook cost to roles that never touch the Python API — and in the post-fork
candidate it would add hooks around forks for which no interpreter exists.

Inventory every `fork()` in `forkrun_cleanroom.c`; classify each role as
Python-using or not **per candidate**; specify the hook pair per site **and per
candidate**; pair correctly on the fork-failure path as well as success.

Prototype against a minimal embedding **before** integrating the pipeline.
**Prototype the candidate under evaluation, not a generic hybrid.**

**Acceptance:** prototype passes on the matrix in C0.5; a thread-starting import
is detected before the launcher forks its pipeline; no fork site is unclassified.

### C0.5 — Interpreter matrix gate

**Minimum gate: 3.10, 3.11, 3.12, 3.13 (the current CI matrix), plus 3.14.**

> **[V] 3.14 is required because the M1 cost measurements were taken on 3.14.7**
> `python_requires=">=3.10"` **[V]** (`setup.py:233`) sets no upper bound, so
> shipping on 3.10–3.13 evidence alone would leave a material gap between
> declared compatibility and tested behaviour.
>
> **[V] CI currently tests 3.10–3.13 only.** Either add 3.14 to the matrix or
> revise the project's supported-version policy explicitly. Default-on must not
> infer 3.14 compatibility from 3.10–3.13 results.

**Free-threaded CPython is out of scope** for the initial gate and the roadmap
says so explicitly.

Per-minor fork-lifecycle tests: successful UDF execution after the hooks;
failure and cleanup around each fork site; an import that starts a background
thread; a worker exiting abnormally during startup; UDF import failure; a
bounded import hang; repeated invocations to catch stale interpreter state and
thread/resource leakage.

**This gate blocks W-EXP-1 implementation, not W-EXP-1 design.**

### C0.6 — M1/M2 measurement

**M1 is a retained datum, not a projection.** Bare `Py_Initialize` with
`PyConfig{isolated=1, install_signal_handlers=0, user_site_directory=0}`:

| | wall | RSS |
|---|---|---|
| bare `Py_Initialize` | **11.6–13.6 ms** **[V]** (measured) | 2.5 MB → **8.4 MB** |
| + `import json, os, sys, re` | +6.2 ms **[V]** (measured) | → 10.0 MB |

Cross-check: `python3 -c pass` peaks at 8.4 MB **[V]** (measured), so the embed
is not paying for a `site` initialisation it does not use.

> **[V] The 6.2 ms import increment is a floor, not an estimate.** It was measured
> on four stdlib modules. It is **withdrawn as decision evidence**: the previous
> draft's projected crossover rows added it to measured cleanroom startup and
> published ratios. Those rows are deleted. Crossover discovery happens in M2.

**M2 compares two co-equal candidates.** The previous draft called pre-fork
"probably right"; that preference is **withdrawn** — it rested on an untested
memory argument while paying an undesigned fork-lifecycle cost.

> **[H] The memory column below is a qualitative expectation, not a
> measurement.** Pre-fork COW sharing depends on *which* pages workers dirty —
> a worker writing its output dirties shared pages, and the saving is smaller
> than "the interpreter is shared" suggests. Post-fork processes still share
> file-backed library and code pages, so "~8 MB × N" overstates it too. Both
> arrows are directionally right and numerically unverified. **Measured PSS/USS
> establishes the actual fleet-memory curve; these rows do not.**

| | serial cost | fleet memory **[H]** | fork-time interpreter state |
|---|---|---|---|
| **Pre-fork** (init in launcher, workers inherit) | **bare interpreter-init component only:** +11.6–13.6 ms **[V]** measured — **not** the complete pre-fork startup cost | lower — one interpreter shared, COW, reduced by worker-dirtied pages | live interpreter and possibly threads at every launcher fork |
| **Post-fork** (each worker initialises) | ~0 ms serial; concurrent across workers | higher — per-worker private pages, still sharing file-backed code and libraries | none |

> **[V] The pre-fork row is one component, not the total.** It measures
> `Py_Initialize` alone. It **excludes** UDF import and its dependencies, runtime
> environment resolution, and the rest of the integrated startup path — all of
> which are measured in M2. The withdrawn projection error came from adding a
> component to measured startup and presenting the sum as a measurement;
> **the label must keep that distinction visible**, because startup crossover is
> exactly where the earlier draft overreached.

Semantic non-equivalence is possible and is tracked as **[M]** in C0.3: per-worker
imports can differ observably from one parent import. **M2 measures both and
reports the contract each satisfies, not just the timings.**

Measure on the C0.5 matrix, with **the same UDF and dependency set**, across
representative worker counts: complete API-entry-to-return wall time; time to
first completed result; throughput on light/medium/heavy UDFs; peak RSS **and
PSS/USS**; THP on and off; parent RSS at 30/64/128/256/554/2127 MB.

**Do not use the four-module stdlib import as a proxy for a user's UDF.** Use
representative dependency sets — pure-Python and native-extension — and publish
crossover as a distribution, not one row.

**Acceptance:** measured curves published with exact configuration, parent RSS,
THP state and interpreter version. Any crossover stated as a range.

### C0.7 — Ordered-output completion certificate (design only)

**This is a live defect in shipping code and is tracked as a separate work
item.** Phase 0 records the design contract; the implementation, fault-injection
tests and review belong to that item.

The design must specify: the terminal ordering key/count; exactly how it proves
no packet is missing; and how it is obtained **without changing the frozen
engine** — or, if it cannot be, an explicit argument for revisiting that
constraint.

> **[V] The exposure, verified.** `ring_order_main` frees its heaps and returns
> `EXECUTION_SUCCESS` at EOF (`forkrun_ring.c:7834`). The `heap_left`
> diagnostic is gated behind `FORKRUN_DIAG_NUMA1=1`, so **with the diagnostic
> off a residual heap at EOF produces no signal and exit 0**.
> `_numa_drain_audit` **[V]** (`run.py:8386`) compares per-node `write_idx`
> against `read_idx` plus chunk state — a claim/drain audit that cannot
> distinguish "every batch was claimed" from "every OrderPacket reached the
> orderer". Collection deliberately does not sort when the orderer ran, so there
> is no second line of defence.
>
> Consequence: `map(..., nodes="@2", order="index")` **today** has no gate on
> ordered-output completeness beyond a proxy for it.

Required fault injection, each ending in loud nonzero failure — never a warning
plus partial data, never exit 0: an interior `(major, minor)` packet missing
with later packets present; **the final expected packet missing**; an
order-pipe writer dying before its final packet; the orderer dying or reporting
an emit failure; per-node ring counters complete while ordered output is not.

> **[V] "Successful drain plus empty heap" is not a certificate.** A missing
> *terminal* packet leaves nothing in the heap to expose the gap.

### C0.8 — Phase 0 exit gate

- Capability matrix published and checked against the independent
  expected-behaviour oracle (**C0.1**).
- Trace facility working and documented.
- UDF eligibility and import contracts documented **per M2 candidate**
  (**C0.3**), with the three categories separated and the decline observable
  for category 1.
- Fork-lifecycle prototype passing for **the candidate to be evaluated**, or
  reported as not passing (**C0.4**).
- Interpreter matrix decision recorded (add 3.14, or revise the policy).
- M1/M2 curves published; crossover stated as a range or "not yet observed".
- Ordered-output certificate designed, implementation tracked separately.

**And two decisions that are prerequisites, not conclusions:**

- **The shared launcher-supervision interface (§3) must be specified, and its
  integration strategy recorded, before W-EXP-2 or W-EXP-3 begins.** Either it
  is frozen in Phase 0, or one branch is designated for integration and rebased
  before the other. Starting either workstream without this recorded is how two
  branches end up rewriting the same supervisor.
- **The packaging path (§5.4) must be chosen before W-EXP-1 implementation
  begins**: source-only optional prototype, interpreter-specific release
  wheels, or abandoning the CPython-linked helper for the bootstrap design.
  **[V]** It does not force an `auditwheel` investigation if the choice is
  source-only for the prototype — but it must be a **recorded decision**, not an
  unresolved option that slips past Phase 0.

---

## 5. W-EXP-1 — Python UDF mode (UMA, module references only)

**Goal:** serve `mode="python"` with a module function reference.

### 5.1 The constraint that decides the design

**[V]** `mode="python"` resolves its payload in the Python parent
(`resolve_payload_parent`, called pre-fork) and passes a live `PyObject*` by
fork inheritance. `exec` destroys that graph.

**[V] This supersedes the committed ruling.** `DOCS/CLEANROOM_DESIGN.md`
currently records the boundary as *"hard ... not negotiable"*, and
`CLEANROOM_HANDOVER.md` says *"Structurally impossible; do not attempt it."*
That is correct about **carrying** and incorrect about **reachability**: `exec`
prevents transporting an object graph; it does not prevent the far side from
**re-creating** an interpreter and re-importing the module. The repository
already does exactly this for the shell — `frun.bash` `exec -c bash --norc
--noprofile` and rebuilds its world.

The supersession lands in `DOCS/CHANGELOG.md` and `CLEANROOM_DESIGN.md` in the
same commit as the code, or the change reads as a rules violation.

### 5.2 Options

| Option | Shape | Verdict |
|---|---|---|
| **A** | Optional helper `.so` linking CPython, `dlopen`ed by the launcher **only in UDF mode**; substrate and launcher stay Python-free | **Recommended** |
| B | Python UDF-host process; workers IPC per batch | **Rejected** |
| C | `posix_spawnp` N independent Python bootstraps + attachable engine | **Escape hatch** |
| D | Link `-lpython3` into the launcher | **Rejected** |

**B:** the host holds the GIL, so UDF execution serialises through one process
— a centralised dispatcher, the architecture forkrun's thesis is against, and
it would collapse the CPU-utilisation result.

**C, escape hatch:** **[V]** `fr_py_init` creates engine state with
`MAP_SHARED|MAP_ANONYMOUS` — inherited by `fork()`, but not a re-openable
artifact for unrelated processes. Making it attachable means reconstructing
`g_state`, `state[]`, all four eventfd arrays, `global_num_nodes`,
`g_logical_to_phys_map` and the steal thresholds. That violates the frozen-engine
constraint and is a different project. Retained as fallback only.

> **[V] C is not the same as post-fork initialisation.** Post-fork inside an
> ordinary forked worker needs neither `posix_spawn` nor engine attachment — the
> worker inherits already-initialised shared state, then initialises its own
> interpreter. It is a **live M2 candidate** (C0.6), not an escape hatch. The
> previous draft conflated them.

**D:** binds a CPython minor into a shipped artifact and drags the requirement
into the `make python-substrate` critical path, where a missing `python3-devel`
would fail every Python CI job.

### 5.3 Design A

**Artifact.** `python/forkrun/_forkrun_udf.so`, built **only if `python3-config`
is present**, and **not** a prerequisite of `python-substrate`.

> **[V] `python3-devel` is promised in `pyproject.toml:9` and
> `python/docs/INSTALLATION.md:10` but installed in none of the six CI `dnf
> install` lines.** Optionality is load-bearing, not cosmetic.

> **[V] Presence of `python3-config` is not sufficient — its version must
> match.** Multiple Python installations coexist in most environments, and
> **[V]** `tools/build_wheel.sh` deliberately builds with
> `/opt/python/cp31X-cp31X` interpreters rather than the system one. A helper
> compiled against whichever `python3-config` happens to be first on `PATH`
> would bind the wrong minor. The build must resolve and verify the intended
> interpreter explicitly (version probe, not name), and the helper must record
> the minor it was built against for the runtime check in §5.5.

**Discovery.** Via `/proc/self/exe` — **[V]** not `argv[0]`, which `execv` can
rewrite. The launcher already reads `/proc/self/status` (`rss_kb`), so `/proc`
is idiomatic here.

**Reuse `_worker` over a second Python loop in C.**

> **[V]** `_worker.py` already owns the `Batch` type, the borrowed-memoryview
> lifetime, `invalidate()` rules, `_coerce_result()` return conversion, output
> framing, and the retry/skip/fail-fast path. A C batch loop would duplicate
> exactly the semantics most likely to drift, and would require the launcher to
> construct a `Batch` — which, if it were a different type, would mean the same
> UDF working on one path and failing on the other.

**Runtime environment — declared, not discovered.**

> **[V] `PyConfig{isolated=1}` plus one package-root insertion does not give
> third-party import support.** `isolated` ignores `PYTHONPATH` and the user
> site directory; `site_import=0` removes `site`'s path handling. A UDF may need
> a virtualenv, site-packages, an editable install, a `.pth` file,
> `sitecustomize`, or a project `sys.path`.

Decide and document one of: (a) an isolated embedded interpreter with an
explicit, validated list of stdlib and permitted dependency roots passed by the
caller; or (b) a more conventional configuration with a documented
environment/`sys.path` handoff. Either way, `PyConfig.home`, prefix/executable
handling, venv paths and native-extension search paths get specific tests —
**from an installed package, not a source checkout.**

**Return contract — bit-exact parity, non-negotiable. [V]**

| return | behaviour |
|---|---|
| `None` | **no record emitted** — `data=NULL` skips the write; signal still sent |
| `b""` | **one empty record** — header written with `len == 0` |
| `bytes` / `bytearray` / `memoryview` | one framed record |
| `str` | UTF-8 encoded, then framed |
| raises | the existing `on_error` taxonomy, never a silent drop |

A UDF exception is **not** a transport failure. Sentinel/EOF batches are
filtered before the UDF is invoked, so `None` never means EOF.

**Kill switch.** `FORKRUN_NO_UDF` masks **only** the `udf` capability, and
`udf` appears in **every** `v1_available()` return shape — including the
`FORKRUN_NO_V1` branch, which returns all-present capabilities as `False`.

> **[V]** `v1_available()` **[V]** (`_bindings.py:460-500`) has a dictionary
> contract with two return shapes. `FORKRUN_NO_UDF` must not be a "mirror of
> `FORKRUN_NO_V1`" in the sense of forcing everything `False`.

**Absent helper.** A distinct exit code — **not 79**, which means "the probe
failed and fallback is unsafe" — so Python warns and takes the in-process path,
mirroring the exit-78 refusal precedent. The in-process path is correct for
Python UDFs; refusal is about capability, not safety.

### 5.4 Packaging — decided before implementation

**Do not ship a CPython-linked helper under an ABI-independent wheel tag.**

> **[V]** The substrate ships as `py3-none` because it is `ctypes`-loaded and
> interpreter-agnostic. A helper linked to the **builder's** `libpython3.X` is
> not version-agnostic merely because the substrate remains so — and building it
> from the sdist does not make the resulting wheel honest, because the binary
> still carries the builder's minor while the tag claims otherwise.

Three options, to be chosen:

1. **Source-only prototype.** Helper source in the sdist; built locally as an
   explicitly optional capability; **not advertised as present in the generic
   wheel.** A locally built wheel must not be mislabelled as reusable across
   minors.
2. **Release support.** Interpreter-specific wheels per supported minor, with a
   truthful ABI tag, and `tools/build_wheel.sh` **[V]** adjusted — it currently
   globs `forkrun-*-none-*.whl` at line 143, which rejects a `cp3XX` tag
   outright.
3. **Abandon Option A** for the per-worker bootstrap design (Option C), accepting
   its cost.

> **[V] Unresolved:** `auditwheel repair` may vendor `libpython3.X.so` into the
> wheel with an RPATH, loading a private copy. `auditwheel` is not installed on
> the measurement machine, so this is **unverified**. Inspect real
> `auditwheel show` and `repair` output before shipping any binary. The docs
> establish what `repair` may do, not what this artifact will contain.

### 5.5 Acceptance criteria

* [ ] Every eligible module reference produces **byte-identical** output to the
      in-process path on the same corpus.
* [ ] `None` / `b""` / `bytes` / `bytearray` / `memoryview` / `str` / invalid
      return pinned by tests.
* [ ] The `Batch` delivered is the exact `forkrun._batch.Batch`; borrowed
      memoryview lifetime and `.invalidate()` behaviour match.
* [ ] Ineligible callables are detected **before input is consumed**, decline
      to in-process, and the decline is observable when the cleanroom was
      explicitly requested.
* [ ] **A class reference and other unsupported callable attributes are declined
      pre-consumption by an explicit kind check**, not merely undocumented
      (**[V]** the resolver's `callable()` check at `_worker.py:138` admits
      classes).
* [ ] **A caller/helper CPython-minor mismatch is refused safely before input
      consumption**, with the refusal observable. A helper built for 3.12 must
      not be driven by a 3.14 caller.
* [ ] A UDF raising an exception matches the in-process `on_error` behaviour for
      all three policies.
* [ ] UDFs with a third-party pure-Python dependency and a native-extension
      dependency both work, tested **from an installed package**.
* [ ] Import failure is distinguished from an exception raised during batch
      execution; a bounded import hang terminates.
* [ ] Import-time threading is detected before the launcher forks.
* [ ] No duplicate side-effecting import occurs in the default protocol.
* [ ] No `-lpython3` in the substrate link line; canary green.
* [ ] Missing `python3-devel` degrades to in-process with a warning; no CI job
      fails.
* [ ] `FORKRUN_NO_UDF=1` forces in-process and masks nothing else.
* [ ] Worker SIGKILL / respawn, parent abandonment, poison counts, strict
      poison, and no surviving descendants — all tested with byte-completeness.
* [ ] Non-replayable sources are **not** blindly retried after possible
      consumption.
* [ ] C0.5 matrix green.
* [ ] Measured crossover published, including the RSS at which UDF mode is
      **slower** than in-process. **No claim of uniform superiority.**

---

## 6. W-EXP-2 — NUMA

**Blocked on the separate ordered-output work item (C0.7).**

### 6.1 The ordering constraint

**[V] In NUMA the record header's `batch_idx` is not a global sequence.**
`do_lockfree_claim` sets `out->batch_idx = my_read_idx`, where `my_read_idx` is
`atomic_fetch_add` on `state[my_numa_node].read_idx` — a **per-node** counter.
Each node has an independent `SharedState` with its own ring.

Therefore: two nodes routinely emit the same `batch_idx`; it has no
relationship to input order; and `_cleanroom_collect`'s sort
(**[V]** `run.py:1278`) is **invalid** for NUMA.

**[V]** The global key is `FR_PACK_KEY(major, minor)` — 42-bit major ‖ 22-bit
minor. `major_ring[i]` is the ingest's global chunk id, `minor` the within-chunk
counter, and exactly one scanner claims each chunk, so the pair is unique by
construction. The C orderer already consumes that key and emits only on an
exact expected-key match.

**Two changes, both mandatory:**

1. **Fork the C orderer** and route its output to a distinct ordered result fd.
2. **Suppress the collector's sort selectively** — via an explicit
   `already_ordered` signal, **not** by removing the sort. Removing it globally
   would break currently supported UMA `order="index"` calls, which are covered
   by passing tests.

**A third hazard, from the separate work item:** the orderer is *stricter than a
sort*. It emits only on exact `(major, minor)` sequence and **[V]** returns
success with a residual heap at EOF (`forkrun_ring.c:7834`). W-EXP-2 requires
**both** the per-node drain audit and the ordered-output completion
certificate — they detect different loss modes.

### 6.2 Worker-to-node assignment — the correction

> **[V] The C plugin and spawn worker loops select logical node 0
> unconditionally.**
> `fr_py_worker_plugin_loop` calls `fr_py_worker_init(wid, 0, ...)`
> **[V]** (`_shim.c:2865`); `fr_py_worker_spawn_loop` does the same
> **[V]** (`_shim.c:3018`). **[V]** `fr_py_worker_init` **[V]** (`_shim.c:244`)
> uses that argument to set `g_fr_config.ring_node_id`, assign
> `my_numa_node`, pin to `g_logical_to_phys_map[my_numa_node]`, and increment
> `state[my_numa_node].active_workers`. Neither loop has a node parameter.

A worker in that state claims against **node 0's ring** regardless of where it
was placed. Scheduling it onto a schedule does not fix this.

**The previous draft of this document claimed the loop "self-pins from
`getcpu()`". That was `[V]`-tagged and false.** Self-pinning is true of the
bash `ring_worker inc` loadable, a different entry point. See §0.2.

> **[V] This is a port constraint, not a live defect.** Both C loops are
> UMA-gated in-process — `c_worker_loop` **[V]** (`run.py:1535`) and
> `c_spawn_loop` **[V]** (`run.py:1588`) both raise for `num_nodes != 1`. The
> NUMA executor is reactor-based and takes the arm that supplies the real node:
> `worker_main_with_death_pipe` → **[V]** `_worker.py:324`.
> Measured with `FORKRUN_DIAG_NUMA1=1`, `nodes="@4"`, `workers=8`: every node's
> ring fully drained (`write == read`, `tail_empty=1`), wids partitioned
> `[0,1] [2,3] [4,5] [6,7]`, full 5,000,000 bytes returned.

**Required mechanism.** The launcher must supply each worker's logical node.
A new node-taking shim entry point is the expected shape — it *exposes an
operation that already exists*: **[V]** `fr_py_worker_init` already accepts
`node_id`, and the Python paths already supply it (**[V]** `_worker.py:324`,
`_reactor.py:760`). **No engine change.** The entry point carries an explicit
capability contract.

**Assignment must be stable across respawn** — same `wid`, same node,
`wincarn` advancing as the engine's recovery protocol expects.

**Acceptance verifies both** the logical ring each worker claims from **and**
its observed CPU affinity. **Affinity alone cannot prove ring assignment**: a
worker correctly pinned to physical node 1 while claiming node 0's ring would
look right under affinity checks and be wrong under ring checks.

### 6.3 Other design points

* **Topology resolution is not reimplemented.** **[V]**
  `_numa.build_numa_map()` has a deliberate loud `ValueError` when
  `nodes > len(online)` — *"silently running UMA after nodes=4 was requested
  would be a benchmarking lie"*. Python resolves and passes an explicit
  validated map; the launcher validates only the range.
* **Fork order:** fallow → N indexers → N scanners → ingest. **[V]** Reverse of
  bash's order, matching the in-process Python path. Satisfies the constraint
  that scanner/worker forks follow closure of every indexer death-pipe write
  end.
* **NUMA ingest replaces the spill child**, not supplements it. Never both.
* **Death pipes must be added.** The launcher has none; it identifies children by
  matching `pids[]`. bash and `_reactor.py` both watch scanner and indexer
  deaths via `ring_poll` types 1 and 4.
* **[V] The `INDEXER_DEATH` handler must check `abort_reason == 0` before
  treating a non-zero status as a fault** — the indexer returns failure on any
  `emergency_abort`, so classifying that as a death prints a spurious FATAL on
  every clean early exit and clobbers SLURM exit codes (143→1).

### 6.4 Worker spawning — measured, not mirrored

**Neither eager spawning nor mirroring the existing fork gate is presumed
correct.**

**[V]** Two separate properties, often conflated: the engine can publish
without workers (so eager spawn is *safe*), and that says nothing about startup
performance or node coverage. The `+34%` figure that motivates the gate was
**[V]** measured on the Python NUMA path, whose dynamics differ — separate
ingest process, self-pinning workers.

Required:

1. Explicit `wid → logical node` assignment, stable across respawn.
2. **Measurement** comparing eager with publication-gated spawning under
   equivalent workloads.
3. Evidence that the chosen policy preserves correctness, per-node progress and
   fault recovery — **independently of its throughput**.
4. The decision recorded as a **performance** choice, not a correctness
   dependency. **A performance experiment must not gate a correctness phase.**

### 6.5 Acceptance criteria

* [ ] `nodes="@2"` and `nodes="@4"` byte-identical to the in-process path, for
      `order in ("none", "index")`.
* [ ] **`order="index"` on NUMA reconstructs input order byte-exactly.** The
      single highest-value test in this item — it is where §6.1 bites and where
      a silent tail-drop would hide.
* [ ] A forced `(major, minor)` gap and a forced missing **terminal** packet
      each fail loudly, via the completion certificate and independently of the
      drain audit.
* [ ] Every worker's **logical ring** and **observed affinity** are both
      verified, across respawn.
* [ ] SIGKILL of ingest, each indexer, scanner, fallow and orderer each terminate
      with failure and leave no descendants.
* [ ] `nodes=1` behaviour bit-identical to today.
* [ ] `order="index"` **UMA** still parent-side sorts — a regression test, since
      the collector change is the risky part.
* [ ] Capability probe refuses the cleanroom **before input consumption** when
      any required symbol is absent, including the node-taking worker loop —
      with a test for the missing-symbol case (§6.6).

### 6.6 Capability surface

**[V]** `v1_available()["numa"]` **[V]** (`_bindings.py:486`) requires **seven**
symbols. The first draft listed five and omitted two.

```
fr_py_init_numa       _shim.c:1735      fr_py_fallow_phys      _shim.c:1847
fr_py_numa_ingest     _shim.c:1775      fr_py_data_ready_node _shim.c:1955
fr_py_indexer_numa    _shim.c:1796      fr_py_ingest_eof_posted _shim.c:1989
fr_py_numa_scanner    _shim.c:1820
```

**And an eighth, which W-EXP-2 introduces.**

> **[V] The seven-symbol check is a snapshot of today's substrate, and becomes
> insufficient the moment W-EXP-2 lands.** The node-taking worker loop (§6.2)
> does not exist yet; a stale or mismatched substrate would pass all seven
> checks and then fail — after the launcher has begun work and possibly consumed
> input.

Required: a **separate `numa_plugin_loop` capability** covering the node-taking
entry point, gated by the same refuse-before-consumption rule.

**Rule: the launcher's capability probe is derived from what it calls, never
hand-maintained.** If the design uses per-node spawn gating, backlog snapshots,
a drain audit or a node-taking worker loop, those are declared required
capabilities too. **A capability set that has not been re-derived when the call
set changes is a stale gate.**

### 6.7 The validation gap

**[V]** `test_numa_recovery.py` is gated on `len(detect_numa_nodes()) >= 2` and
is skipped entirely on a UMA box. **[V]** Under `numa=fake=N`, `set_mempolicy`
is exercised but **physically inert**, and every SRAT distance is 10, so
distance-scaled stealing is untested.

**[H]** So NUMA cleanroom coverage will be logic-correct under fake-NUMA and
**completely unvalidated** for placement and stealing. That argues for shipping
it narrower than the rest of the roadmap, not for skipping it.

---

## 7. W-EXP-3 — Spawn-pipe-driven incremental workers

**[V] Not a capability blocker.** The engine publishes into per-node rings
regardless of worker existence — the publish wait explicitly *bails out* when
`active_workers == 0`, and EOF finalisation is unconditional.

**[V] What it costs:** workers are born against a barely-filled ring, spin, and
steal cores the ingest needs. **[V]** The `+34%` figure is measured on the
Python NUMA path.

**[V] What implementing it requires:** arming the pipe via
`fr_py_scan_with_spawn`; **inverting the fork order**; replacing the blocking
`waitpid(-1)` with a `poll()` over the spawn pipe **plus per-worker death
pipes** (which do not exist); and reproducing `_spawn_quiescent`'s three
conditions — **scanner reaped AND no live worker AND spawn pipe empty** — before
closing the signal spare.

> **[V] The third condition is load-bearing and its failure mode is SILENT DATA
> LOSS, not a hang**: 4092 of 18890 bytes dropped in 5–10% of streaming runs,
> with no exception and a clean drain-side exit. Scanners exit **after** writing
> requests.

**[V]** Reassuringly, `fr_py_drain_loop` already tolerates late workers — purely
signal-driven, indexing `out_fds[wid]` only when a signal for that wid arrives.

**"Performance only" is true only after the quiescence conditions are proven not
to lose results.** Fault injection required around every close/reap transition:
partial pipe reads, scanner death after writing the final request, duplicate
spawn requests, worker death during the spawn ramp, early consumer abandonment.

**Acceptance compares joined bytes and independently known record identities, not
blob counts.** Publish the measured benefit against the all-workers-at-start
baseline and retain a kill switch.

---

## 8. W-EXP-4 — Default-on, three independent decisions

**[V] Plugin default-on does not technically depend on W-EXP-1 or W-EXP-2.**
The previous draft said "eligible once W-EXP-1/2 are done", which contradicted
its own separability argument. Corrected: separability implies by definition
that plugin need not wait. Deferring anyway is a **risk-tolerance choice, not a
dependency**, and will be written as one.

### Decision 1 — plugin envelope

* **Evidence gate:** correctness and fault-injection coverage; both gate
  states (`FORKRUN_CLEANROOM` unset and `=1`); installed-package behaviour;
  measured performance with stated parent RSS and THP; explicit rollback.
* **Status: evidence already in hand.** 70/70 cleanroom tests with zero skips;
  738 full suite; CR-FIX1 correctness fixes demonstrated with before/after
  controls; the RSS curve published in `DOCS/CHANGELOG.md`.
* **Residual obligation:** batch-count variance becomes visible with two code
  paths serving one call. **[V]** Pre-existing and documented — a documentation
  obligation, not a blocker.
* **Must not** be gated on UDF or NUMA evidence.
* Lands as its own revertible commit. `FORKRUN_CLEANROOM=0` remains the global
  rollback.

### Decision 2 — Python UDF envelope

* **Evidence gate:** §5.5 in full, plus the published crossover.
* **If the measured crossover sits above typical caller RSS**, this is a
  high-RSS optimisation. Then either leave opt-in, or adopt a **documented,
  measured RSS-based selection policy** — an explicit policy decision, not one
  smuggled in via a default.

### Decision 3 — multi-node envelope

* **Evidence gate:** §6.5, plus **real multi-socket hardware**.
* **[H]** This is the decision most likely to be wrong if made now. Fake-NUMA
  validates logical plumbing only; it does not validate physical placement,
  remote memory, or distance-scaled stealing. Cheapest thing that would make it
  defensible is real hardware — not more fake-NUMA tests.

---

## 9. Standing gaps

| Item | Source | Why it matters |
|---|---|---|
| `test_numa_recovery.py` unreachable on UMA | CR-FIX1 | NUMA crash/respawn lock-ins are skipped in the default environment. Boot `numa=fake=N` for the matrix (**requires a reboot**) or mark the cells required-manual. Silent skipping of a crash test is a coverage lie. |
| Path-source replay assumes a stable file | CR-FIX1-C | A path is replayable by reopening, which assumes contents do not change mid-invocation. Documented as an API assumption; explicitly not solved by spooling. |
| Fleet memory sharing unmeasured | C0.6 | Pre-fork vs post-fork differ by ~8 MB × N. Needs PSS/USS, not peak RSS. |
| Free-threaded CPython | C0.5 | Out of scope for the initial gate; stated, not silently ignored. |

**Closed:** the W-CR6 RSS curve — re-measured in both THP regimes and recorded
in `DOCS/CHANGELOG.md` and `_cleanroom_enabled`.

---

## 10. Exit criteria

* [ ] W-EXP-1 shipped: §5.5 complete, crossover published.
* [ ] W-EXP-2 shipped: §6.5 complete, dependent ordered-output item closed,
      validation gap stated plainly.
* [ ] W-EXP-1.5 (UDF + NUMA) proven — cross-product tests across
      `nodes ∈ {1, @2, @4}` × `order` × `on_error` × respawn × strict poison ×
      non-replayable sources. **Success in W-EXP-1 plus W-EXP-2 does not
      imply the combination works.**
* [ ] W-EXP-3 shipped or explicitly deferred with a measured cost.
* [ ] The three default-on decisions made separately, each with its own commit
      and revert.
* [ ] Capability predicate widened only for combinations that have tests.
* [ ] `FORKRUN_CLEANROOM` semantics and the kill switch documented where users
      read them.
* [ ] `DOCS/FUTURE_WORK.md` Tier 4b emptied or rewritten to reflect reality.

---

## 11. What this roadmap does not establish

* **Only C0.6 M1 and the CR-FIX1 figures are measured.** W-EXP-1's viability
  depends on M2, which does not exist yet. **No crossover is claimed.**
* **[V] No multi-socket hardware was used.** Every NUMA statement here is
  `numa=fake=N`, where mempolicy is inert and all SRAT distances are 10.
* **[V] `auditwheel`'s treatment of `libpython` is unverified** — not installed
  on the measurement machine. §5.4 depends on the answer.
* **[H] The W-EXP-1 → W-EXP-2 ordering is a judgement**, not a derivation.
* **No sub-interpreter or free-threading behaviour has been considered** beyond
  stating free-threading is out of scope.
* **The interpreter matrix is a gap in this document's own confidence:** the
  M1 numbers come from one interpreter (3.14.7) on one machine. Whether
  `Py_Initialize` cost varies materially across 3.10–3.13 is unmeasured, and
  C0.6 is what settles it.
* **The UDF eligibility contract will reject natural code.** `map(lambda b:
  b.data, path)` declines. That is a correctness cost, recorded so it is not
  rediscovered as a bug.

---

## 12. Review checklist

### 12.1 For the reviewer

1. **Spot-check `[V]` claims, do not sample.** Each carries inline evidence.
   Two `[V]` claims in the previous draft were false on first contact; both were
   found by a reviewer reading code the author had read and mis-generalised.
2. **Attack §6.2 hardest.** Worker-to-node assignment is the item where being
   wrong produces *silently wrong placement* — correct output on a
   single-socket box, wrong on real hardware.
3. **Confirm §6.1's collector change is selective.** A global sort removal would
   break supported UMA `order="index"`.
4. **Disagree with §3's ordering** if breadth should precede population.
5. **Answer §5.4.** Whether the helper ships in a wheel is a maintainer
   decision with real consequences, and `auditwheel` behaviour is unknown.
6. **Confirm §12.2** — whether recording the two false `[V]` claims is useful
   calibration or noise.

### 12.2 Correction history, retained deliberately

| Claim | Tag | Actual | Found by |
|---|---|---|---|
| "workers self-pin from `getcpu()`" | **[V]** | False. C loops hardcode node 0 (`_shim.c:2865`, `:3018`); self-pinning is true of `ring_worker inc`, a different entry point | Round 3 |
| "~100 ms circular wait on spare pipe write ends" | comment | Refuted. Those close only after the supervision loop exits, at `live == 0` | CR-FIX1 |
| "all five NUMA symbols exist" | implied | Seven. `v1_available()` requires `fr_py_data_ready_node` and `fr_py_ingest_eof_posted` too | Round 1 |
| "identical UDF runs unchanged on both paths" | acceptance criterion | Unsatisfiable for closures | Round 1 |

The shared shape: a claim about one code path generalised to a sibling path.
Every `[V]` in this revision is scoped to the specific function it names.

*Reviewers: quote `file:line` or measurement output when refuting. A claim
rejected without evidence will simply be re-derived.*