# Cleanroom Expansion Roadmap — `NEW/REFACTOR4.2`

**Purpose.** A reviewable plan for widening the Python cleanroom launcher beyond
the UMA C-plugin envelope it serves today, and for eventually enabling it by
default. Written to be **reviewed and refuted by an external AI before any
implementation begins** — the same three-round consensus process used for
CR-FIX1 is intended to repeat here.

**Supersedes nothing.** `DOCS/FUTURE_WORK.md` Tier 4b is the one-line registry;
this document is the working plan behind those entries.

**Base state:** branch `NEW/REFACTOR4.2`, which carries CR-FIX1 (7 commits on
`NEW/REFACTOR4.1`). All line references are to that state unless stated.
Function names, not line numbers, are the authorities.

---

## 0. How to review this document

Every substantive claim is tagged:

| Tag | Meaning |
|---|---|
| **[V]** | **Verified** — read directly from source or measured. Evidence given. |
| **[H]** | **Hypothesis** — reasoning over verified facts. Not measured. |
| **[M]** | **Needs measurement** — the answer is unknown and must be measured before the dependent work is designed. |

**Reviewers are invited to refute.** Where a claim is wrong, strike it and
replace it; do not design around it. Items marked **[H]** or **[M]** are the
ones most worth attacking, because they are the ones we have not checked.

A plan that cannot be disproven is not a plan.

---

## 1. Where the feature stands after CR-FIX1

| Property | State |
|---|---|
| Serves | `mode="plugin"` (C `.so`, ctx dialect v1/v2), UMA, `orchestrator=True` |
| Declines | `mode="python"` (the **default** mode), spawn, splice, multi-node, `resume=`, `checkpoint_file=`, `orchestrator=False` |
| Gate | `FORKRUN_CLEANROOM`, **default OFF** |
| Tests | 70/70 cleanroom, 0 skips; 738 full suite |
| Measured | startup 1.57×–10.25×, throughput 1.56×–3.78× vs in-process, across 30 MB–2127 MB parent RSS, both THP regimes |

**[V]** The two failure modes CR-FIX1 targeted are fixed and were demonstrated
with before/after controls: fatal teardown used to hang indefinitely on a live
producer (now 0.114 s), and fallback used to be able to return truncated output
with exit 0 (now an explicit error).

**[V]** The fixed ~100 ms overhead was the scanner and spill children not
inheriting the engine descriptors. Removing it moved the crossover below the
floor of any real Python process (≈30 MB, which is interpreter + substrate).

### 1.1 The decision this roadmap is built around

The maintainer's stated intent: **the cleanroom will become the default once it
is ready and bulletproof.** The decision is *tabled*, not made — this roadmap
plans toward it without flipping anything.

**[V]** A useful consequence, which shapes everything below: enabling the gate
today would **not change behaviour for any non-plugin caller**. They hit
`_cleanroom_eligible`, decline, and take the in-process path unchanged. Only
`mode="plugin"` callers would change. So "default on" is not one decision but
three separable ones:

1. enable for `mode="plugin"` — a small, well-tested blast radius;
2. enable for `mode="python"` — the default mode, and the largest user
   population;
3. enable for multi-node — where validation is thinnest.

**They should be made separately, each on its own evidence.** A single "default
on" flag would conflate them.

---

## 2. Standing constraints

Unchanged from CR-FIX1 and **not negotiable**:

* Treat `forkrun_ring.c` as frozen. No engine redesign.
* No `libpython` linkage in the substrate. `libforkrun_python.so` links
  `-ldl -lrt` only, and `-Wl,--no-undefined` plus `ALLOWED_DEPS` enforce that.
  **[V]** The wheel's version-agnostic property depends on this: the substrate
  is `ctypes`-loaded, so one wheel serves every interpreter. A CPython-linked
  substrate would break that and force per-minor wheels.
* `FORKRUN_CLEANROOM` stays opt-in through W-EXP-1 and W-EXP-2.
* Batch counts legitimately vary run-to-run on both paths. This is
  pre-existing and shared. **Do not "fix" it, and do not use blob counts as a
  record-count proxy** — compare joined bytes.

---

## 3. Sequencing and the dependency graph

```
              ┌──────────────────────────────────────────────┐
              │ Phase 0 — measurements (no product code)      │
              │   M1 UDF interpreter cost model               │
              │   M2 crossover projection                     │
              └───────────────┬──────────────────────────────┘
                              │ gates
              ┌───────────────▼──────────────┐
              │ W-EXP-1  Python UDF mode     │──┐
              └───────────────┬──────────────┘  │
                              │                 ├──► W-EXP-4  default-on
              ┌───────────────▼──────────────┐  │      (three separable
              │ W-EXP-2  NUMA                │──┘       decisions, §9)
              └───────────────┬──────────────┘
                              │ improves
              ┌───────────────▼──────────────┐
              │ W-EXP-3  spawn-pipe workers  │   (perf only; not a
              └──────────────────────────────┘    capability blocker)
```

**[V]** W-EXP-1, W-EXP-2 and W-EXP-3 are mutually independent. They are ordered
by **value and risk**, not by dependency:

* **W-EXP-1 first** because `mode="python"` is the default and by far the
  largest user population. Until it is served, "default on" means "an
  accelerator nobody's default path uses".
* **W-EXP-2 second** because NUMA is the project's headline feature and has the
  **worst-tested** path — but it is a smaller population than `mode="python"`
  and carries a specific correctness landmine (§6.1) that makes it a poor
  first-thing-to-break.
* **W-EXP-3 last** because it is a **performance refinement, not a capability**.
  Nothing is unavailable without it. It also carries the roadmap's only
  *silent-data-loss* risk (§7).

**[H]** This ordering is a judgement, not a derivation. A reviewer who believes
NUMA should go first (broader blast radius exercised earlier) should say so.

---

## 4. Phase 0 — Measurements that gate everything

**No product code.** These exist because W-EXP-1's viability depends on a
number we have never measured, and designing before measuring it would repeat
the mistake CR-FIX1 spent three rounds undoing — a hypothesis hardened into a
narrative.

### M1 — What does embedding CPython cost?

**[V]** Measured on this box (Python 3.14.7, `PyConfig` with `isolated=1`):

| | wall | RSS |
|---|---|---|
| bare `Py_Initialize` | **11.6–13.6 ms** | 2.5 MB → **8.4 MB** |
| + `import json, os, sys, re` | +6.2 ms | → 10.0 MB |

Cross-check: `python3 -c pass` peaks at 8.4 MB. The embed is honest — it is not
paying for a whole `site` initialization it does not use.

**[V]** Why this matters: the cleanroom's measured startup advantage is
**6.34 ms at a 30 MB parent** (THP off). Adding ~12 ms of interpreter
init and ~6 ms of UDF import puts UDF-mode startup at roughly **18–25 ms
against an in-process 17.4 ms**. In other words:

> **UDF mode is expected to be SLOWER than the in-process path at small parent
> RSS, and much faster at large parent RSS. It will have a crossover that
> plugin mode does not have.**

Projection against the measured CR-FIX1 curves (THP=always):

| parent RSS | in-process | cleanroom UDF (projected) | projected ratio |
|---|---|---|---|
| 30 MB | 17.4 ms | ~18–25 ms | **0.7–1.0×** |
| 554 MB | 200.6 ms | ~45 ms | ~4.5× |
| 2127 MB | 734.8 ms | ~90 ms | ~8.2× |

**[M] Required follow-up measurement — the crossover point.** Sweep ballast at
roughly 64/128/256 MB and find where UDF mode overtakes in-process. Until that
number is measured, **do not claim UDF mode is an accelerator at all sizes.**

### M2 — Pre-fork vs post-fork interpreter initialisation

Two placements, both plausible, with an opposite trade:

| | serial cost | fleet memory |
|---|---|---|
| **Pre-fork** (init in the launcher, workers inherit) | +12 ms on the critical path | **~8 MB total**, COW-shared across all workers |
| **Post-fork** (each worker initialises) | ~0 ms serial; +12 ms per worker, concurrent on 28 cores | **~8 MB × N workers** — not shareable, since no ancestor was initialised |

**[H]** Pre-fork is probably right: 12 ms serial is small against the
660 ms fork tax it avoids at 2 GB, and COW-sharing the interpreter is a
large memory win. But it is unmeasured, and it directly sets the crossover in
M1. **Measure both.**

**[H]** A third option exists and should be considered rather than dismissed:
`PyConfig` with `site_import=0` and a **pre-import cache** — for example a
pre-warmed `__pycache__` — would reduce the +6.2 ms import cost. Worth one
measurement before committing to the full design.

---

## 5. W-EXP-1 — Python UDF mode

**Goal:** serve `mode="python"`, i.e. `payload` being a Python callable, or a
`"pkg.mod:func"` spec resolved post-fork.

**[V]** This is the default mode and the only thing standing between the
cleanroom and being useful to most callers.

### 5.1 The committed position, and why this supersedes it

`DOCS/CLEANROOM_DESIGN.md` currently records the boundary as *"hard ... not
negotiable — `exec` destroys the Python interpreter's object graph"*, and
`CLEANROOM_HANDOVER.md` says *"Structurally impossible; do not attempt it."*

**That is correct about carrying and incorrect about reachability.** `exec`
destroys the object graph; it does not prevent the far side from **re-creating**
an interpreter and re-importing the module. The repository already does exactly
this for the shell: `frun.bash` `exec -c bash --norc --noprofile` and rebuilds
its world on the far side.

**This item explicitly supersedes that ruling**, and the supersession must land
in `DOCS/CHANGELOG.md` and `CLEANROOM_DESIGN.md` in the same commit as the code,
or the change reads as a rules violation.

### 5.2 The architectural problem, stated precisely

`mode="python"` currently resolves the payload **in the Python parent**
(`_worker.resolve_payload_parent`, called pre-fork precisely so that a child
forked from a threaded host never imports) and passes a live `PyObject*` by
fork inheritance. **[V]** `payload_fn(batch)` has exactly one call site in the
whole tree, inside `_worker._run`, which only executes post-fork.

**[V]** Across `exec` there is no `PyObject*` to carry. What the far side needs
is therefore five seams, **none of which exists today**:

1. CPython linked into something the launcher can load;
2. a C→Python callback seam with GIL and exception marshalling;
3. reconstruction of `sys.path` and the UDF module's transitive imports;
4. a result marshalling path replacing the plugin's stdout capture;
5. a Python-exception → `on_error` taxonomy.

Seam 1 is the one with the packaging consequences. Seams 2–4 are the ones that
determine whether the semantics are identical.

### 5.3 Options

| Option | Shape | Verdict |
|---|---|---|
| **A** | Optional helper `.so` linking CPython, `dlopen`ed by the launcher **only in UDF mode**; substrate and launcher stay Python-free | **Recommended** |
| B | Keep a Python UDF-host process; workers IPC per batch | **Rejected** |
| C | `posix_spawnp` N independent Python bootstraps + a new `fr_py_attach()` | **Held as escape hatch** |
| D | Link `-lpython3` directly into the launcher | **Rejected** |

**Why B is rejected.** The host holds the GIL, so all UDF execution serialises
through one process. That is a centralised dispatcher — the precise architecture
forkrun's entire thesis is against — and it would collapse the CPU-utilisation
result. **[V]** The project's own claim is "no centralized dispatcher; all cores
do actual work when work exists."

**Why C is held rather than dismissed.** It is architecturally the *cleanest*
answer to the RSS problem: `posix_spawnp` uses `CLONE_VM|CLONE_VFORK`, so no
page-table copy of the parent at all, and each worker builds its own
interpreter. **[V]** It is blocked because `fr_py_init` creates the engine state
with `MAP_SHARED|MAP_ANONYMOUS` (`ring_init_main`), which is anonymous and
therefore cannot be re-opened by a sibling process. Making it attachable means
reconstructing `g_state`, `state[]`, all four eventfd arrays,
`global_num_nodes`, `g_logical_to_phys_map` and the steal thresholds — i.e.
making engine initialisation resumable. **[H]** That is an engine-shaped change
of the first order, and it would violate the "ring engine frozen" constraint.
Escalate to it only if A fails.

**Why D is rejected.** **[V]** The substrate and launcher are separate build
products and the launcher is no longer tracked in git (CR-FIX1), which weakens
the old "committed binary" objection — but linking a CPython minor into a
shipped artifact still binds it, and it would drag the requirement into the
`make python-substrate` critical path where a missing `python3-devel` fails
every Python CI job.

### 5.4 Design A, in detail

**Artifact.** `python/forkrun/_forkrun_udf.so`, built **only if `python3-config`
is present**, and **not** a prerequisite of `python-substrate`.

**[V]** `python3-devel` is already promised in `pyproject.toml:9` and
`INSTALLATION.md:10` but **installed in none of the six CI `dnf install` lines**.
Option A's optionality is therefore load-bearing, not cosmetic.

**Discovery.** The launcher already reads `/proc/self/status`
(`rss_kb`), so `/proc` is idiomatic here. It locates the helper relative to
`/proc/self/exe` — **not** `argv[0]`, which `execv` can rewrite.

**Lifecycle.** `Py_Initialize` (with `PyConfig`: `isolated=1`,
`site_import=0`, `install_signal_handlers=0`) and the UDF import happen **once
in the launcher, before any fork** — subject to the M2 measurement. The
launcher is single-threaded pre-fork by construction, so this is the same
posture the in-process reactor already takes when it forks from a live Python
parent.

**`sys.path` reconstruction.** The launcher sits in the package directory, so
the package root is `dirname(dirname(/proc/self/exe))`. Derive it; do not accept
an arbitrary path from the caller.

**The `Batch` object must be the same type as the in-process path.**
**[V]** `_worker.py` builds `Batch.from_window(...)` and hands *that* to the
payload. If the launcher constructs anything else, **the same UDF works on one
path and fails on the other** — the worst possible outcome for an API. The
helper must import `forkrun._batch` and construct the identical type.

**Result semantics — bit-exact parity, non-negotiable.** **[V]**

| return | behaviour |
|---|---|
| `None` | **no record emitted** (`data=NULL` skips the `writev`; signal still sent) |
| `b""` | **one empty record** — header written with `len == 0` |
| `b`/`memoryview` | one framed record |
| `str` | encoded, then framed |
| raises | mapped to the existing `on_error` taxonomy, never a silent drop |

**GIL.** Acquire once around the whole worker loop, not per batch: each worker is
single-threaded post-fork, so the per-call cost would be pure overhead.

**Exit.** Workers `_exit()`, so no `Py_Finalize`. The launcher returns from
`main` and the process exits.

**Kill switch.** Add `"udf"` to `_bindings.v1_available()` and a
`FORKRUN_NO_UDF` mirror of `FORKRUN_NO_V1`. **[V]** `FORKRUN_NO_V1` already
forces every capability `False`, which is the established idiom.

**Absent-helper behaviour.** The launcher exits with a distinct code (79 is
taken by the probe; **79 must not be reused** — a probe failure suppresses
fallback, an absent helper must *not*, since the in-process path is perfectly
correct for Python UDFs). Python warns and takes the in-process path, mirroring
the exit-78 refusal precedent.

### 5.5 Packaging — the two decisions that must be made explicitly

1. **Should the helper ship in the wheel?** **[V]** The substrate ships
   because it is Python-version-agnostic. A CPython-linked helper is **not**:
   it binds one minor. **[V]** `tools/build_wheel.sh` hardcodes the glob
   `forkrun-*-none-*.whl`, so switching to a `cp3XX` ABI tag breaks the release
   build outright, and `auditwheel repair` may **vendor** `libpython3.X.so` into
   the wheel with an RPATH — which would load a private copy of libpython.
   **[V]** This is unverified: `auditwheel` is not installed here. **Resolve it
   before shipping the binary.** Interim recommendation: ship the *source* in
   the sdist only, so `pip install` from sdist builds it when `python3-config`
   exists, and `FORKRUN_NO_UDF`/the capability probe degrade gracefully.
2. **`ALLOWED_DEPS` must not be widened.** **[V]** It is referenced by both the
   canary rule and the substrate rule, so adding `-lpython3` "for the helper"
   would silently legalise libpython for the zero-bash-linkage artifacts. Use a
   separate variable.

### 5.6 Acceptance criteria

* [ ] A `map()`/`stream()` call with a callable and with a `"pkg.mod:func"`
      spec returns **byte-identical** output to the in-process path, on the same
      fixture corpus.
* [ ] `None` / `b""` / `str` parity pinned by dedicated tests — these are the
      three the engine deliberately distinguishes.
* [ ] A UDF raising an exception produces the same `on_error` behaviour on both
      paths, for all three policies.
* [ ] The identical UDF runs unchanged on **both** paths — proving the `Batch`
      type is genuinely shared, not duck-typed.
* [ ] A UDF that imports a third-party package works in the cleanroom.
* [ ] `sys.path` reconstruction is tested from an installed wheel, not only a
      source checkout.
* [ ] No `-lpython3` anywhere in the substrate's link line; canary still green.
* [ ] Missing `python3-devel` degrades to in-process with a warning; it does not
      fail any CI job.
* [ ] M1/M2 measured and the **crossover published**, including the RSS at which
      UDF mode is slower than in-process.
* [ ] `FORKRUN_NO_UDF=1` forces the in-process path cleanly.

### 5.7 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Interpreter init erases the startup advantage at small RSS | **High, and measured — it is real** | Publish the crossover; do not claim uniformity |
| Semantics drift between the two paths | **High** | §5.4 parity table, pinned by tests |
| `Batch` type divergence | High | Test the *same* UDF on both paths |
| Wheel/auditwheel vendoring of libpython | Medium | Resolve before shipping the binary; ship source only until then |
| Import cost for heavy UDFs | Medium | Pre-import cache experiment (M2) |
| Interpreter RSS at fork time eroding the RSS win | Medium | M2; expect ~6 MB, negligible vs a multi-GB parent |

---

## 6. W-EXP-2 — NUMA

**[V]** This is the smaller port. All five substrate symbols exist, are
validated, and are already wired into the in-process path:
`fr_py_init_numa`, `fr_py_numa_ingest`, `fr_py_indexer_numa`,
`fr_py_numa_scanner`, `fr_py_fallow_phys`. The work is **orchestration, not
engine work**.

### 6.1 The correctness landmine — read this first

**[V]** In NUMA mode the value written into the record header is **not** a
global sequence number. `do_lockfree_claim` sets
`out->batch_idx = my_read_idx`, where `my_read_idx` comes from
`atomic_fetch_add` on `state[my_numa_node].read_idx` — a **per-node** counter.
Each node has an independent `SharedState` with its own ring.

**[V]** Therefore:

* two nodes routinely emit the **same** `batch_idx`;
* it has **no** relationship to input order;
* `_cleanroom_collect` sorts by `batch_idx` when `order="index"` — which is
  **invalid** for NUMA.

**[V]** The real global order key is `FR_PACK_KEY(major, minor)` — a 42-bit
major ‖ 22-bit minor packing. `major_ring[i]` is the ingest's global chunk id
and `minor` is the within-chunk batch counter; exactly one scanner claims each
chunk, so the pair is globally unique by construction. The C orderer already
consumes exactly that key.

**Consequence: forking a C orderer is mandatory, and `_cleanroom_collect` must
stop sorting its output.** Doing one without the other yields correct framing
with garbage order — silent, and it would pass a naive test.

**[V]** A further hazard: `ring_order_main` in NUMA mode is *stricter than a
sort*. It emits only on an exact `(major, minor)` sequence and **never flushes
the residual heap at EOF**. A gap silently drops the tail with exit 0.
The launcher should therefore pair the orderer with the existing
`_numa_drain_audit`, not with exit status.

### 6.2 Other design points

* **Topology parsing must not be reimplemented.** **[V]** `_numa.build_numa_map`
  has a deliberate loud `ValueError` when `nodes > len(online)` — *"silently
  running UMA after nodes=4 was requested would be a benchmarking lie"*. Have
  Python resolve the spec and pass `--nodes`/`--numa-map` explicitly; the
  launcher validates only the range [1, 512].
* **Fork order:** fallow → N indexers → N scanners → ingest. **[V]** This is the
  *reverse* of bash's order and matches the in-process Python path. It satisfies
  the constraint that scanner/worker forks follow closure of every indexer
  death-pipe write end.
* **NUMA ingest replaces the spill child**, not supplements it. Never fork both.
* **Worker→node assignment is a scheduling property, not a correctness one.**
  **[V]** `fr_py_worker_plugin_loop` takes no node argument; workers self-pin
  from `getcpu()`. So round-robin the initial spawn and record the mapping.
* **Death pipes.** **[V]** bash and `_reactor.py` both watch scanner and indexer
  deaths via `ring_poll` types 1 and 4; the launcher has no death pipes and
  identifies children by matching `pids[]`. They must be added.
  **[V]** The `INDEXER_DEATH` handler must check `abort_reason == 0` *before*
  treating a non-zero status as a fault — the indexer returns failure on any
  `emergency_abort`, so classifying that as a death prints a spurious FATAL on
  every clean early exit and clobbers SLURM exit codes (143→1).

### 6.3 Acceptance criteria

* [ ] `nodes="@2"` and `nodes="@4"` produce output byte-identical to the
      in-process path, for `order in ("none", "index")`.
* [ ] **`order="index"` on NUMA reconstructs input order byte-exactly.** This is
      the single highest-value test in this item: it is where §6.1 bites, and
      where a silent tail-drop would hide.
* [ ] A forced `(major, minor)` gap is detected (drain audit), not silently
      dropped.
* [ ] SIGKILL of an indexer, of a scanner, and of the ingest child each
      terminates the run with failure and leaves no descendants.
* [ ] Per-node worker pinning observed, and the mapping is stable across
      respawns.
* [ ] `nodes=1` behaviour is bit-identical to the current implementation.

### 6.4 The validation gap that limits this item

**[V]** `test_numa_recovery.py` is gated on `len(detect_numa_nodes()) >= 2` and
is **skipped entirely on a UMA box** — which is where this work will be done
absent a reboot. **[V]** Under `numa=fake=N`, `set_mempolicy(MPOL_BIND)` is
exercised but **physically inert**, and every SRAT distance is 10 so the
distance-scaled steal thresholds are uniform.

**[H]** So the honest position is: NUMA cleanroom coverage will be
*logic-correct* under fake-NUMA and **completely unvalidated** for placement
and stealing. That is a reason to ship it as an opt-in that is narrower than
the rest of the roadmap, not a reason to skip it.

---

## 7. W-EXP-3 — Spawn-pipe-driven incremental workers

**[V]** Not a capability blocker. **[V]** The engine publishes into per-node
rings regardless of worker existence — the publish wait explicitly *bails out*
when `active_workers == 0`, and EOF finalisation is unconditional. "Spawn all N
at t=0, pinned round-robin" is correct and is what the launcher does today.

**[V]** What it costs: workers are born against a barely-filled ring, spin, and
steal cores the ingest needs. `_reactor.py` records **+34% wall** for exactly
that shape.

**[V]** Implementing it requires: arming the pipe via `fr_py_scan_with_spawn`;
**inverting the fork order** so the scanner precedes the workers; replacing the
blocking `waitpid(-1)` with a `poll()` over the spawn pipe **plus per-worker
death pipes** (which do not exist yet); and reproducing `_spawn_quiescent`'s
three conditions — scanner reaped **and** no live worker **and spawn pipe
empty** — before closing the signal spare.

**[V]** The third condition is the dangerous one. `MEMORY.md` records it as
load-bearing: *"scanners exit AFTER writing requests"*. Getting it wrong is
**silent data loss, not a hang** — 4092 of 18890 bytes dropped in 5–10% of
streaming runs, with no exception and a clean drain-side exit.

**[V]** Reassuringly, `fr_py_drain_loop` already tolerates late workers: it is
purely signal-driven and only indexes `out_fds[wid]` when a signal for that wid
arrives, and all memfds are created up front.

**Decision:** defer this until W-EXP-1 and W-EXP-2 land and are measured. It is
the only item whose failure mode is silent rather than loud.

---

## 8. Standing gaps, independent of the expansion

| Item | Source | Why it matters |
|---|---|---|
| Opt-in trace facility | CR-FIX1-E | Deferred behind the descriptor measurement, which resolved the question by direct experiment. The *next* lifecycle investigation should not have to reinvent instrumentation. Minimum viable: monotonic ts, pid, role, event, to an inherited memfd. |
| `test_numa_recovery.py` unreachable on UMA | CR-FIX1 | The NUMA crash/respawn lock-ins are skipped in the default environment. Either boot `numa=fake=N` for the matrix (**requires a reboot**) or mark the cells required-manual in the release gate. Silent skipping of a crash test is a coverage lie. |
| Path-source replay assumes a stable file | CR-FIX1-C | A path is replayable by reopening, which assumes contents do not change mid-invocation. Documented as an API assumption; explicitly *not* solved by spooling. |
| W-CR6 RSS curve | CR-FIX1 | **Re-measured and recorded.** No longer open. |

---

## 9. W-EXP-4 — Default-on, as three separate decisions

**[V]** Enabling the single `FORKRUN_CLEANROOM` gate today would change nothing
for non-plugin callers. The roadmap therefore decomposes "make it the default"
into three independently-gated flips:

### Decision 1 — plugin mode

* **Evidence required:** the measured RSS curve (done), CR-FIX1 correctness
  fixes (done), 70/70 tests (done).
* **Residual risk:** batch-count variance becomes visible with two code paths
  serving one call. **[V]** This is pre-existing and documented; it is a
  documentation obligation, not a blocker.
* **Recommendation:** eligible once W-EXP-1/2 are done and this is landed as its
  own commit, so it can be reverted alone.
* **Kill switch:** `FORKRUN_CLEANROOM=0` already exists and is the whole switch.

### Decision 2 — Python UDF mode

* **Evidence required:** §5.6 in full, **plus a published crossover**. If the
  crossover sits above the RSS of the typical caller, this is a
  high-RSS-only optimisation and should be enabled **conditionally on parent
  RSS** rather than globally — a policy decision the maintainer should make
  explicitly, not one to smuggle in via a default.

### Decision 3 — multi-node

* **Evidence required:** §6.3, **plus** real multi-socket hardware. **[V]**
  Until that exists, this flip should be opt-in and stated as unvalidated for
  placement and stealing.

**[H]** Decision 3 is the one most likely to be wrong if made now, and the
cheapest thing that would make it defensible is real hardware — not more fake-
NUMA tests.

---

## 10. Exit criteria for the roadmap

* [ ] W-EXP-1 shipped, with §5.6 complete and the crossover published.
* [ ] W-EXP-2 shipped, with §6.3 complete, and its validation gap stated
      plainly rather than papered over.
* [ ] W-EXP-3 either shipped or explicitly deferred with a measured cost.
* [ ] The trace facility exists and is documented.
* [ ] The four envelopes are decided separately, each with its own commit and
      its own revert.
* [ ] `FORKRUN_CLEANROOM` semantics, and the kill switch, are documented
      somewhere a user will read them.
* [ ] `DOCS/FUTURE_WORK.md` Tier 4b is emptied or rewritten to reflect reality.

---

## 11. What this roadmap does not establish

* **Nothing here is measured except M1 and the CR-FIX1 figures.** W-EXP-1's
  viability rests on a projection from M1 plus a measured curve. That
  projection is the single largest uncertainty in this document, and it is why
  M1 is Phase 0 rather than a footnote.
* **[V] No multi-socket hardware was used.** Every NUMA statement here is
  `numa=fake=N`, where mempolicy is inert and all distances are 10.
* **[V] `auditwheel`'s treatment of `libpython` is unverified** — it is not
  installed on this machine. §5.5 depends on the answer.
* **[H] The W-EXP-1 → W-EXP-2 → W-EXP-3 ordering is a judgement**, not a
  derivation. The only hard dependency in the graph is M1/M2 → W-EXP-1.
* **No sub-interpreter, no free-threading, no Python 3.13+ JIT interaction has
  been considered.** A beta-test model such as 3.14 may behave differently under
  `fork()` from what 3.10–3.13 do, and the CI matrix covers 3.10–3.13 only.
* **The relative priority of W-EXP-1 and W-EXP-2 is contestable.** If a
  reviewer believes breadth-of-blast-radius should come before
  breadth-of-population, §3 should be re-argued.

---

## 12. Review checklist for the external reviewer

1. **Refute or confirm** each **[V]** claim by reading the cited code. If a
   `[V]` is wrong, that is the most valuable finding you can produce.
2. **Attack the [H] claims in §4 and §5.3.** They are where the design rests and
   they have not been checked.
3. **Check §6.1 hardest.** It is the one item where being wrong produces
   *silently wrong output* rather than a crash or a refusal.
4. **Disagree with §3's ordering** if you think breadth should precede
   population.
5. **Answer §5.5(1).** Whether the helper should ship in the wheel is a
   maintainer decision with real consequences, and the `auditwheel` behaviour
   is currently unknown.

*Reviewers: please quote `file:line` or measurement output when refuting. A
claim rejected without evidence will simply be re-derived.*