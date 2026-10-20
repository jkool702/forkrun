# Technical-Debt Register — Python front end vs `frun.bash`

Source of an external architectural audit of the live `NEW/REFACTOR4.2`
branch, re-verified here against the tree before recording. This register
exists so that cleanup is **scheduled against evidence** rather than
issued as another refactoring work order on top of active work.

Per the audit's own closing caveat, and per `EVIDENCE_CHAIN.md`, every
entry below is labelled with how it was established. **A claim carried
over from the review is not the same thing as a claim confirmed against
the code**, and the register keeps those apart deliberately.

## Status vocabulary

The audit's most useful objection was that these documents collapse four
distinct states into one word, "done":

| state | meaning |
|---|---|
| **implemented** | the code exists |
| **verified** | a test exercises the real production route and would fail if it broke |
| **measured** | a number exists, with a stated scope and a stated limit |
| **release-approved** | passed the release gate |

Use these words, not "done". Most entries below are *documented* defects;
two are unverified structural claims that need mapping before anyone acts.

## Register

Findings prefixed `F-` (the parity audit's ids, e.g. `F6`, `F7`) are **not**
`TD-` entries and are tracked in `dev/supervisor/BASH_PY_PARITY_AUDIT.md`,
with their analysis in `dev/supervisor/CLEANROOM_LAUNCH_DECISION.md`. They
are summarised here only so a reader of this register is not misled into
thinking they are untracked:

| id | one-line status |
|---|---|
| F6 | `posix_spawn` **performance gate MET** (−88% to −96% at 1–5 GiB parent RSS); **backend ADOPTED as default (F6 Stage 4); audited independently in Stage 5, which found and fixed a fail-open in the relocation guard and strengthened the low-FD matrix to a multiset check**; **descriptor gate ANSWERED** (F6 Stage 2: 2 launch shapes, 1 `DUP2` action / 0 actions, no `CLOSEFROM` so the 3.10 floor is not a blocker); **launch-semantic equivalence OUTSTANDING** (exit 127 does NOT fall back — 127 absent from `_CR_EXIT_PRE_INGEST`; `posix_spawn` would raise instead); disposition **GO — C1–C5 CLOSED and backend adopted** (`CLEANROOM_FD_CONTRACT.md` §9); failure policy **A** implemented; **default backend is now `posix_spawn`**, `fork()+execv()` retained as private fallback |
| F7 | Wholesale environment inheritance **MEASURED** (all 112 parent vars cross; a malformed `PYTHONHASHSEED` kills the cleanroom child at interpreter init);**desired contract UNDECIDED** — needs a compatibility decision, not more evidence. |

| id | entry | pri | status |
|---|---|---|---|
| TD-01 | Record protocol defined in three independent places | high | **verified** |
| TD-02 | Payload import timing documented backwards | high | **verified** |
| TD-03 | `_api.py` still describes a Stage 0 stub | med | **verified** |
| TD-04 | Environment propagation: explicit in bash, implicit in Python | med | **decided** — `DECISION-04` |
| TD-05 | Retry semantics: `-E` flag has no Python counterpart | med | **decided + boundaries measured** |
| TD-06 | Executor consolidation | med | **audited** — `EXECUTOR_CONSOLIDATION_AUDIT.md` |
| TD-07 | README collapses v0 history into current capability | low | **unverified claim** |
| TD-08 | `Mode` type omitted a shipped, tested mode | med | **verified — FIXED** |
| TD-09 | `poisoned_batches` empty on `orchestrator=False` | high | **verified — FIXED** (WO-PY-REL-1); residual index-width item recorded as TD-12 and TD-09b |
| TD-10 | Class payload silently produced empty results | high | **verified — FIXED** |
| TD-11 | `FORKRUN_NO_UDF` kill switch specified but unimplemented | high | **verified — FIXED** |
| TD-09b | plain **streaming** path left scalar `poisoned` at 0 | high | **verified — FIXED** (two per-executor defects, both mutation-proven; found by WO-PY-REL-1, re-confirmed in the parity audit) |
| TD-12 | poison-index relay truncates u64 `batch_idx` to u32 | medium | **verified — OPEN** (pre-existing, affects cleanroom too) |
| TD-13 | streaming **peak** retention ~0.5x OUTPUT bytes, not a bounded window | high | **PARTIALLY MITIGATED (WO-PY-STREAM-BACKPRESSURE-1), still OPEN**: the worker-completion notification pipe's capacity IS the producer's read-ahead window, and 4KB (256 completions) instead of 1MB (65536) cuts peak retention 24-65% on the **plain** supervision path with no throughput cost — but only where the capacity is below the run's outstanding-notification count (a 16KB pipe measuring identically to 1MB on a 977-batch run), and it does **nothing** on the default reactor path, whose retention is the parent's own parsed-record queue. **Still NOT a byte bound**: one batch can be large, `order="index"` still buffers behind a poisoned head, and the bound is on completions not bytes. The better answer for the default path is the C drain's results pipe (retention FLAT at ~3.5 MB vs the legacy drain's 138 MB) once its 16-19x park defect is fixed |
| TD-14 | `test_spawn_ordered` compared map/stream element-wise | low | **RECLASSIFIED — invalid test expectation, not a product defect** (WO-PY-REL-1 follow-up) |
| TD-15 | Reactor lost the poison notification when the last worker exited | high | **verified — FIXED** (W-PYPOISONDRAIN): the index list could come back empty beside a non-zero `poisoned` count; root-caused to the gap between a round's `select()` and the out-of-band `waitpid(WNOHANG)` exit sweep, reproduced on demand by delaying that sweep (47–58 losses in 60 runs), mutation-proven |

---

### TD-01 — Record protocol defined in three independent places (high)

**Verified.** Three separate definitions of the same wire protocol:

- `python/forkrun/_worker.py:43` — `_HDR = struct.Struct("<QQII")`, the
  authoritative header (batch_idx, len, disposition, reserved).
- `python/forkrun/run.py:82-83` — `_DISP_DATA = 0`, `_DISP_NO_RESULT = 1`,
  commented *"must match FR_DISP\* in \_shim.c"*. **Defines only two of
  the four dispositions.**
- `python/forkrun/_reassembly.py:35-38` — all four
  (`DATA/NO_RESULT/SKIPPED/POISONED = 0/1/2/3`), commented
  *"Duplicated rather than imported to keep this module free of run.py
  imports (it is loaded on every ordered path); test_stage1_reassembly
  pins the two definitions agree."*
- Plus the C side: `FR_DISP_*` in `_shim.c`.

The current defence is **synchronisation by test**. That is a real
defence, and it is how this codebase is supposed to work — but see TD-01b
for the case where exactly that defence did not work.

**The import-cycle constraint is legitimate and must be respected.**
`_reassembly.py` is on the hot ordered path and is deliberately kept free
of `run.py` imports. The fix is therefore *not* "import from run.py"; it
is a dependency-free leaf module that all four sites import, with
`run.py` and `_reassembly.py` keeping their own layering.

#### TD-01b — Why this entry is not theoretical

The same session that produced this register shipped a **protocol bug in
C that a pinning test could not have caught**: the child-report struct
grew to 48 bytes while its validator still compared a completed read
against `1`, so every child counted as failed and the run reported
"8 of 4 sampled". A second bug had the ack and the report sharing one
pipe while the parent wrote the release to the pipe's *read* end and the
child read its own *write* end — both `EBADF`, both discarded with
`(void)`. The barrier was a no-op for two commits and produced confident,
wrong numbers with no error.

The lesson worth carrying: **a test that pins two constants proves the
constants agree; it proves nothing about whether the code that uses them
is correct.** Consolidation removes the drift *class*, which is worth
having, but it is maintenance value — not a correctness gate. Do not let
this entry be closed on the strength of a green suite.

**Does not establish:** that any current Python disposition value is
actually wrong. Nothing found suggests they are. This is drift exposure,
not a live defect.

---

### TD-02 — Payload import timing documented backwards (high) — FIXED

> **Resolved.** Rewritten in `README.md` and `MODES.md`. Investigating it
> produced a sharper finding than the audit reported: the rule is
> **conditional**, and the docs flattened that to a single unconditional
> claim. See below.

**Verified, and more serious than "stale".**

`python/README.md:78-79` and `python/docs/MODES.md:33-34` both state that
`"pkg.mod:func"` payloads are *"imported post-fork in the worker — keeps
the parent virgin of native imports"*.

The code does the opposite, deliberately. `python/forkrun/_worker.py:125-131`:

> the fork-safety rule (W-REL6-3.1) is about CALL SITE: string specs
> must be resolved in the PARENT before fork … so a child forked from a
> threaded host never imports (frozen import locks in the child deadlock).

The only `importlib.import_module` in the package is the child-side
fallback at `_worker.py:138-140`.

So the public docs describe the **unsafe** variant. Anyone trusting them
could construct a workload that deadlocks a child on a frozen import
lock.

**What the audit did not catch: the rule is conditional.** Tracing the
resolver (`run.py:3025-3057`) shows three distinct outcomes for the *same*
string spec:

| path | where `"pkg.mod:func"` is imported |
|---|---|
| `mode="plugin"`, and `mode="python"` when the helper is absent | **parent**, before fork (W-REL6-3.1) |
| `mode="udf"` / `mode="python"` **with the helper built** | **inside the launcher**, after `exec` |
| `mode="python"`, helper absent (plain wheel install) | falls back to the parent-side rule |

The last row matters more than it looks: **`setup.py` does not ship the
UDF helper**, so the parent-side path is what a plain `pip install`
actually takes — the exact opposite of what the docs promised. Both
branches are deliberate and both are correct for their reason, so the
fix documents the condition rather than picking a side.

**Does not establish:** that any user has been harmed by this.

---

### TD-11 — `FORKRUN_NO_UDF` kill switch specified but unimplemented (high) — FIXED

**Found by working §5.5 criterion by criterion.** Roadmap §5.3 specifies
this switch in detail and §5.5 requires it, but `grep` for
`FORKRUN_NO_UDF` across the whole tree matched **only the roadmap**. It was
never implemented: not in Python, not in C, not in `frun.bash`. The only
related variable in existence is `FORKRUN_NO_V1`.

A kill switch is an operational escape hatch. Its absence means an
operator who discovers a bad UDF-mode interaction in production has no way
to turn the capability off except by removing the helper file or editing
code.

**Why it was missed for so long:** `test_v1_fast.py::test_no_v1_kill_switch`
pinned the `FORKRUN_NO_V1` shape with an exact-dict equality that did not
include `udf`. So the test actively asserted the spec-violating shape — the
missing key was not merely unasserted, it was asserted absent.

**Implemented** at `_udf.helper_path()` — the single point every route
consults, so the capability report and the routing decision cannot
disagree. `v1_available()` gained `udf` in **both** return shapes, with
the value read from `helper_path()` so it cannot drift from routing.

It returns `None` rather than raising, because absence is already a
handled condition meaning "fall back to in-process" — which is precisely
what "forces in-process" requires.

Per the spec it masks **only** `udf` and is explicitly **not** a mirror of
`FORKRUN_NO_V1`: verified that no other capability key changes, and that
real capabilities stay *reported* rather than being lied away. Masking is a
routing decision, not a claim that a symbol is absent.

Five tests cover: masks only `udf`; not a mirror of `FORKRUN_NO_V1`; the
key exists in **both** shapes with matching key sets; `helper_path()`
returns `None` under the switch (the enforcement point itself); and a run
still produces all 8 correct results under the switch — it must **degrade,
never break**, since a kill switch is only safe to set in production if
turning it on cannot lose results.

The pre-existing exact-dict assertion was updated to include `udf`, with a
comment recording that it had been asserting the spec-violating shape.

### TD-10 — A class payload produced silent empty results (high) — FIXED

**Found by working W-EXP-1, not by the audit.** Roadmap §5.5 carries this
as an explicitly unmet acceptance criterion, marked [V]:

> A class reference and other unsupported callable attributes are declined
> pre-consumption by an explicit kind check, not merely undocumented — the
> resolver's `callable()` check at `_worker.py:138` admits classes.

**Confirmed by reproduction.** Both resolution sites admitted classes:
`_worker.py` used `callable(fn)` and `fr_udf.c:643` used
`PyCallable_Check(fn)`. Both are true of a class.

The failure mode was worse than an error: calling a class with a batch
**constructs an instance** and returns it; the instance is not bytes, so
the result was dropped and `map()` returned `[]` — indistinguishable from
"the input matched no records". A wiring mistake reported as an empty
result leaves the user no reason to doubt the data.

**Fixed at both sites** — `inspect.isclass()` in the parent-side resolver,
`PyType_Check()` in the launcher's `fr_udf.c`. Both name the module, the
attribute and the fix. `PyType_Check` was chosen over
`PyType_IsSubtype(fn, &PyType_Type)` so that a metaclass-derived class is
caught too.

**Scope, stated honestly:** the check rejects *classes*. Other
"unsupported callable attributes" from the criterion — a callable
instance with unusual semantics, say — are still accepted, because the
documented payload contract explicitly allows callables and narrowing
further would break working code. The criterion's broader wording is
therefore only partly met, and the narrow reading is deliberate.

`test_class_payload_refusal.py` covers: plain class declined, class with
callable instances declined, non-callable declined, **module-level function
still resolves (negative control)**, **callable instance still accepted
when passed directly** (so the fix does not leak into the callable
payload form), and refusal **before input is consumed** (asserted with a
nonexistent source, so a post-resolution check would fail with a file
error instead).

### TD-09 — `poisoned_batches` is empty on `orchestrator=False` (high) — FIXED

> **Status: FIXED in WO-PY-REL-1.** The mechanism, the verified paths, the
> width handling, the truncation rule and the mutation evidence are in
> §TD-09-FIX below. The original analysis that follows is kept because the
> *wrong* claim in it ("That is engine work, not a stats patch") is what
> sent the work down the wrong path for as long as it stood.

#### TD-09-FIX — mechanism and evidence

**Mechanism.** Reused the existing bounded memfd transport the cleanroom
already uses, wired to the plain path. `fr_py_claim()` in `_shim.c` had
been calling `fr_py_poison_relay()` on the plain path the whole time, on
the same `num_kills == threshold` edge that increments the shared poisoned
count — so the index was relayed correctly and **discarded**, because no
Python code ever created the receiving end. Three missing pieces, all
Python:

1. parent creates the poison stats memfd and writes the v2 header
   (`_PoisonStatsChannel`, `run.py`);
2. parent exports `$FRK_POISON_FD` around the fork, restoring the previous
   value in a `finally` (`_ExportedPoisonFd`) — it is process-global, and a
   stale fd number would make a later run relay into the wrong object;
3. the descriptor is threaded into the four worker keep-sets
   (`extra_keep_fds` through `fork_workers`, `_fork_c_plugin_worker`,
   `_fork_c_spawn_worker`, `_fork_splice_worker`), because `scrub_fds`
   closes everything outside `keep`.

Indices are collected BEFORE `report_poison()`, so a `strict_poison` raise
does not lose them. Truncation is `relayed < poisoned`, identical to the
cleanroom, and is announced by a warning.

**No frozen file was touched.** `_shim.c` was touched, and only to remove
a stale-fd cache — see "the defect the fix exposed" below.

**The defect the fix exposed.** `fr_py_poison_relay()` cached the
transport fd in a `__thread` variable and never re-read it. A Python
parent can call `fr_py_claim()` itself — `test_exactly_once.py` drives a
batch to its retry limit exactly that way — and the first such call with
`$FRK_POISON_FD` unset cached `-1` **permanently in that thread**. Every
worker forked afterwards inherited `-1` through `fork()`, so the relay was
dead for the rest of the process: correct count, permanently empty index
list. That is TD-09 reproduced *by the fix for TD-09*, and it passed in
isolation while failing only in the full suite. The cache is now removed;
`getenv` runs per poisoned batch, which is a terminal event and not a hot
path. This is why the full suite, not the focused suite, is the evidence
that matters here.

**Verified paths.** `map()` materialized, `map()` streaming, and `stream()`
— each for `orchestrator=False` and `True`; the C plugin worker loop and
the spawn worker loop separately, because each builds its own keep-set.
All produce `poisoned=[2,5]` for the 8-record fixture whose records 2 and
5 carry `BOOM`.

**Index width: a real, pre-existing truncation that was NOT widened.**
`fr_py_poison_relay(unsigned int)` is called with
`(uint32_t)batch.batch_idx` while the engine's `batch_idx` is `uint64_t`
(`forkrun_ring.c:1421`). An index ≥ 2^32 is silently truncated. **This
already affected the shipped cleanroom path**; the reactor path is
width-safe because it carries indices as formatted strings over the
trap-ACK pipe. Widening it means changing the shared slot geometry
(`FR_POISON_SLOT_U32`), the launcher's pre-size in `forkrun_cleanroom.c`,
and `_STATS_SLOT_U32` in `run.py` — i.e. relaunching the shipped
`_forkrun_cleanroom` binary and its CI build. Out of scope here; recorded
as **TD-12**. The plain path is now consistent with the cleanroom path and
introduces no new truncation.

**Truncation.** Per-worker, `_STATS_CAPACITY = 1024` indices; the relay
drops silently on overflow, so slot counts are a lower bound.
Completeness is decided by comparing the aggregate against the exact
scalar, never by the list length.

**What failed before the change.**
`test_poison_accounting.py::test_poisoned_batches_empty_on_non_reactor_path_KNOWN_GAP`
— the file's own docstring said to delete that assertion and extend the
reactor coverage when the gap closed, rather than relax it.

**Mutation evidence** (`test_poison_accounting.py`, 17 tests):

| Mutation | Result |
|---|---|
| plain path reports `[]` again | 8 failures |
| one real poison index dropped | 8 failures |
| truncated list marked complete | 2 failures |
| scalar altered with no poison event (map) | 5 failures |
| relay fd not kept (Python worker loop) | 8 failures |
| keep removed from the C plugin loop only | 2 failures |
| keep removed from the spawn loop only | 1 failure |
| streaming index list emptied | 10 failures |

The three keep-set mutations are why the loops are asserted separately: a
fix threaded into one loop passes every other test here.

**Superseded note (TD-09 era):** this entry originally declined to assert
the plain-streaming scalar, which stays 0 while the reactor reports the true
count, deferring it to **TD-09b**. **TD-09b is now FIXED and that scalar is
asserted** on both generator executors. The deferral is history — see
TD-09b for why the defect was two bugs, not one, and why a scalar-only
assertion would have missed the empty-index-list half.

**Does not establish:** anything about poison modes beyond
retry/strict_poison and the skip policy checked in the matrix; the
multi-worker slot aggregation rule is reasoned from the layout, not
exhaustively tested beyond the single-worker truncation case.

#### TD-09 — original analysis (kept; the conclusion was wrong)

**Verified by reproduction, not by reading.** The audit asked whether plain,
reactor and cleanroom execution share poison accounting rules. They do
not. One scenario — 8 batches, one raising, `FORKRUN_RETRY_LIMIT=0` —
run through both supported `orchestrator` settings:

```
orchestrator=False  poisoned=8  total=8  poisoned_batches=[]
orchestrator=True   poisoned=8  total=8  poisoned_batches=[0,1,2,3,4,5,6,7]
```

The **count agrees**; the **indices do not**. `orchestrator` is public
(`_validate_orchestrator`, None/True/False) and defaults to `True`, so two
supported configurations of the same function disagree on a documented
stats key.

**Root cause is structural, not an oversight in the stats code.**
`last_run_stats()` documents `poisoned_batches` as "batch indices". The
plain path sets it nowhere: `_raise_for_poisoned` (`run.py:6288`) writes
only `poisoned`. It cannot do otherwise — that path learns the poisoned
total from `lib.fr_py_poisoned_count()` (`run.py:4908`), a **count**; the
indices are not available to it. The cleanroom paths relay real indices
through a bounded per-worker stats side channel (`run.py:1357`,
`1909`), and the reactor path has its own reporter.

`test_cleanroom.py:980` already asserts that cleanroom indices agree with
the in-process path — but "in-process" there means the **reactor**, the
default. The `orchestrator=False` path was never in that comparison, which
is why this survived.

**Done now:** the `last_run_stats()` docstring states the asymmetry
explicitly instead of promising indices unconditionally, and
`python/tests/test_poison_accounting.py` pins all three behaviours —
count agreement across paths (the portable guarantee), indices populated
on the reactor path, and the known gap on the plain path written as a
*gap* assertion naming TD-09 rather than as correct behaviour.

Mutation-checked: clearing `poisoned_batches` in `_finish_map_stats` fails
2 of the 3. The third still passes under that mutation **by design** — it
pins current state, so it guards against a docstring re-promising
something untrue, not against a regression.

**The gap itself is open.** Closing it needs a C accessor returning
poisoned indices on the non-reactor path (the cleanroom solved the same
problem with a bounded side channel). That is engine work, not a stats
patch, so it is flagged rather than attempted here.

**Does not establish:** anything about the cleanroom paths' correctness —
only that they already agree with the reactor on this scenario. Other
poison modes (`skip`, `strict_poison`, truncated relays) were not compared.

### TD-08 — `Mode` type omitted a shipped, tested mode (medium) — FIXED

**Found while fixing TD-02, not reported by the audit.**
`_api.py:21` declared `Mode = Literal["python", "spawn", "plugin",
"splice"]` while `_api.py:28` validated against `_VALID_MODES`, which also
contains `"udf"`.

`mode="udf"` is not vestigial: it is dispatched at `run.py:746` ("served
wherever `mode="plugin"` is: same launcher"), adapted at `run.py:2952`,
and exercised through the public API by `test_stage0_public_api.py` and
`test_stage0_notify_failure.py`.

This had user-visible teeth because **`py.typed` ships**
(`setup.py:225`): the package advertises typing, so a user running mypy or
pyright against `forkrun.map(..., mode="udf")` got a false type error on a
supported mode — while `pip install` + runtime accepted it. The type and
the runtime disagreed, and only the runtime was tested.

Fixed by adding `"udf"` to the `Literal`. No runtime behaviour changed.

**Does not establish:** that any user hit this, or that the other public
annotations agree with runtime validation. A systematic
annotation-vs-`_VALID_*` comparison across the API was **not** performed.

### TD-03 — `_api.py` describes a Stage 0 stub (medium) — FIXED

> **Resolved.** Replaced with a description of the module's actual
> responsibilities, including the division of labour (this module
> validates public arguments; `run.py` selects strategy;
> `_executor_core.py` implements mechanics) so the boundary stops eroding.

**Verified.** `python/forkrun/_api.py:1` opens *"forkrun Python frontend
— Stage 0 API surface stub (v1.3 §3.0)"* and line 6 says the surface
*"then raises NotImplementedError until Stage 4 wires the substrate."*
The frontend is implemented and shipping; the docstring is a fossil.

---

### TD-04 — Environment propagation: explicit vs implicit (medium) — DECIDED

> **Resolved** in `DECISION-04-environment-and-retry.md`. Python keeps
> inheriting the full environment, deliberately: a library must not rewrite
> its host's environment. The interpreter-level isolation
> (`use_environment=0`, `site_import=0`, `safe_path=1`) is what closes the
> Python-visible surface. The decision also bounds, and records, the part
> isolation cannot reach — `LD_PRELOAD`/`LD_LIBRARY_PATH` are consumed by
> `ld.so` before any `PyConfig` field applies.

**Verified divergence.** Bash manages the cleanroom environment through an
explicit allow-list: `frun.bash:189` builds `FORKRUN_EXTRA_VARS` from a
named set of variables, `frun.bash:193` serialises them, and `frun.bash:451`
documents it as the supported mechanism for propagating e.g. a custom
`PATH`.

Python has **no** equivalent. Workers inherit the parent environment
implicitly; the only environment reads in the package are targeted
(`FORKRUN_RETRY_LIMIT`, `FORKRUN_LIB`, `FORKRUN_NO_V1`,
`FORKRUN_TRUST_RESUME`, `FORKRUN_RSS_WARN_KB`).

Implicit inheritance is defensible for an embedded library — and a library
silently taking ownership of its host's environment is arguably worse. But
it should be a **recorded decision**, not an accident of implementation.
This is most acute where cleanroom execution crosses an `exec` boundary,
which is exactly where bash's explicit list exists.

**Does not establish:** a bug. Records a decision that has not been made.

---

### TD-05 — Retry semantics: `-E` has no Python counterpart (medium)

> **Resolved** in `DECISION-04-environment-and-retry.md` §4.1. The three
> named boundaries are now measured, not asserted: a missing payload
> module fails fast without consuming the retry budget; an unexecutable
> spawn command retries then poisons, matching `-E`; limit 0 poisons on
> first failure. A negative limit is a silent infinite loop — parity with
> bash, but with no warning, left as an open maintainer choice.
>
> One correction recorded there: a first probe appeared to show
> `mode="spawn"` returning `[]` with no error for a nonexistent command.
> That was the **probe's** error — it omitted `return_stats=True`, which
> is where `poisoned=8` and the indices live. Not a defect.

**Verified divergence, and parity is better than it first appears.**
`FORKRUN_RETRY_LIMIT` matches: bash documents default 3 (`frun.bash:448`),
Python sets `DEFAULT_RETRY_LIMIT = 3` (`_api.py:37`) and reads the same
variable.

The real divergence is the `-E / --retry-nonzero-exit` flag
(`frun.bash:417, 516`), default **off**: when active it appends
`|| exit $?`, so *any* nonzero command exit kills the worker and retries
the batch. Python's `on_error` policy is the analogue but is not
optionally absent — nonzero exits always enter the retry/poison path.

Two questions, in order:

1. Is `on_error` the intended Python spelling of `-E`, or is it a
   deliberate *default-on* where bash is default-off? If deliberate, it
   needs a comment saying so — a silent default change across front ends
   is the exact class of thing this register exists to surface.
2. The audit asked specifically about **exit 127** and transient
   failures. Worth checking separately; not done here.

**Does not establish:** that either behaviour is wrong. Records an
unrecorded semantic choice.

---

### TD-06 — Executor consolidation (medium) — AUDITED

> **Mapping complete** in `EXECUTOR_CONSOLIDATION_AUDIT.md`. Headline:
> `12/16` executors adopt the shared core, which is **better** than
> "substantial duplication" implies — but `fork_workers` (4/16) and
> `report_poison` (4/16) are the real gaps, and consolidation tracks
> **age**: the two cleanroom executors are 38% of executor code and adopt
> the least. Still **no refactoring recommended on this evidence**, because
> behavioural equivalence was never tested.

**Originally an unverified claim. Do not act on it yet.**

The audit reports substantial remaining duplication in `run.py` across
materialised input, streaming ingest, blocking collection, generator
streaming, reactor supervision and NUMA, with `_executor_core.py` as the
existing consolidation target (`DEDUP_DESIGN.md`, `EXECUTOR_MANIFEST.md`).

Before anyone refactors, the mapping the audit itself recommends is
required: which helpers each live executor actually calls, and which
implementations are still independently maintained.

The audit's own caution is the important part and should be preserved
verbatim in any work order: **do not merge the plain-waitpid and reactor
paths into one flag-driven function.** They implement different failure
contracts — recovery, death detection, respawn, teardown. A single source
of truth for shared mechanics is desirable; a single implementation of
genuinely different supervision models is not.

**Does not establish:** that the duplication is real, let alone
behaviourally equivalent. Unmeasured.

---

### TD-07 — README collapses v0 history into current capability (low)

**Unverified claim.** The audit reports `python/README.md` mixing
historical v0 limitations with later modes and features, and a roadmap
whose acceptance gates no longer reflect implementation status.

Related to the status-vocabulary problem above. Checked lazily while
fixing TD-02/TD-03 — the payload paragraph was one instance of exactly
this, which is mild corroboration but not verification.

---

## Deliberately left alone

Carried from the audit and agreed with, because each is a real semantic
difference rather than duplication:

| difference | why it stays |
|---|---|
| `Batch` vs bash argument delivery | Python needs an explicit borrowed-memoryview lifetime contract |
| `signal_policy` defaults | a library must not silently seize its host's signal handlers |
| waitpid vs reactor supervision | different failure contracts |
| NUMA vs UMA orchestration | real topology and per-node coordination |
| C fast paths vs Python workers | justified only where throughput or dedup is demonstrated |
| cross-language ABI checks | cannot share definitions, but agreement must be *mechanically* verified |

## Sequencing, and where this fits

This register is **not** on the critical path of the cleanroom expansion.
Phase 0 (C0.1–C0.8) is complete apart from C0.6's fleet-memory item, which
was measured and corrected this session; the next stage is **W-EXP-1**
(`mode="python"`), which per `CLEANROOM_EXPANSION_ROADMAP.md` §C0.8
requires the **packaging decision (§5.4) to be recorded before
implementation begins** — that is the main line's next real step, not
anything here.

Suggested order, cheap first:

1. **TD-02, TD-03** — documentation, minutes of work, real blast radius.
2. **TD-04, TD-05** — record decisions. Both are "write down what was
   already chosen", which is cheap and prevents a future reader from
   assuming it was accidental.
3. **TD-01** — real consolidation, dependency-free leaf module, needs its
   own work order and its own mutation evidence.
4. **TD-06, TD-07** — mapping work, not refactoring.

## What this register does not establish

- That TD-01's duplication has ever produced a wrong result in Python.
- That TD-06's duplication is real, or that any two implementations are
  behaviourally equivalent — equivalence was not tested, only noted as
  needing testing.
- Anything about bash correctness. `frun.bash` is the reference, not a
  verified artefact.
- The audit was a **source and documentation audit of the live branch**,
  not a clean-room build or an execution-path verification. Every entry
  above was re-checked by reading this tree; none was verified by
  executing bash and Python side by side under the same workload.
---

## RESOLVED: `test_slow_consumer_bounds_memory` (RSS high-water mark)

**Closed by WO-PY-REL-1.** The measurement defect is fixed and the test is
now robust; see §TD-13 for what the corrected measurement revealed about
the underlying streaming behaviour. Kept as a record of the defect and of
why it passed 45 runs before failing.

Original entry, for history:

`python/tests/test_streaming.py::test_slow_consumer_bounds_memory`
samples `resource.getrusage(RUSAGE_SELF).ru_maxrss` before and after the
run and asserts the delta is under 60 MB.

`ru_maxrss` is the process's **peak** RSS, a high-water mark that never
decreases. So `after - before` is not "memory this test used" -- it is
"the largest transient allocation observed anywhere in the process
between the two samples". A GC pause, an unrelated import, or another
thread's buffer landing in that window can trip the assertion while the
test's own behaviour is correct.

Observed roughly 1 failure in 45 runs, and not correlated with the
cleanroom default: 0/12 with the default on, 0/12 with
`FORKRUN_CLEANROOM=0`, 0/8 on the pre-WO-CR-ROI-2 `run.py`, 0/20 on HEAD.
It surfaces under load.

**RESOLUTION (WO-PY-REL-1).** Both suggested options were used, because
both were needed: the measurement now runs in an isolated subprocess
(`python/tests/_streaming_rss_probe.py`) sampling **current** RSS from
`/proc/self/statm` inside the consumer loop. The assertion changed from an
absolute peak-delta bound to a RELATIVE comparison against a
collect-all control run in the same test, because the absolute number was
not a property of anything (see §TD-13 for the measurements).

Stability after the fix: **40 consecutive focused runs, 0 failures** — 30
standalone plus 10 launched concurrently with a full-suite run, which is
the load condition that used to trigger it. That is evidence the specific
flakiness mechanism is gone; it is not a proof of immunity to every future
source of memory pressure.

**Does not establish:** that streaming is output-size bounded. It is not;
see TD-13.

---

### TD-09b — plain streaming path left scalar `poisoned` at 0 (high) — FIXED

**Found by WO-PY-REL-1 while testing the index fix, not by looking for
it.** Verified identical at `a65aa4ca`, i.e. **pre-existing and unrelated to
TD-09**.

**Status: FIXED. This was a known CORRECTNESS defect, not intended product
behaviour.** It closed as two independent defects, one per generator
executor, because that is what it turned out to be — the original entry
described a single symptom, and one scalar-only test would have let either
half be "fixed" while the other survived.

Reproduction before the fix, 8 records with `BOOM` at 2 and 5,
`mode="plugin"`, `lines=1`, `FORKRUN_RETRY_LIMIT=1`, `FORKRUN_CLEANROOM=0`:

```
stream() streaming=True  orchestrator=False   out=6  poisoned=0  poisoned_batches=[2, 5]
stream() streaming=False orchestrator=False   out=6  poisoned=2  poisoned_batches=[]
stream() orchestrator=True (both)             out=6  poisoned=2  poisoned_batches=[2, 5]
```

Note the two plain rows skew in **opposite directions** — one publishes a
correct scalar with an empty list, the other an empty scalar with a correct
list.

**Root cause.** Both plain executors that are **generators**
(`_execute_streaming`, `_execute_ingest_stream`) drain results inside an
inner `try/finally`, and the **poison summary sits outside it**. That
`finally` runs when the consumer exhausts or abandons the generator and
calls `_teardown_stream()` → `fr_py_destroy()`, which NULLs `g_state`.
`fr_py_poisoned_count()` then takes its `if (!g_state) return 0;` guard.

1. `_execute_ingest_stream` read the count live in the summary, i.e.
   **after** teardown, so `report_poison` received 0, never reached
   `_raise_for_poisoned()`, and left the scalar unset. The **index list
   survived** because it is read from the poison relay **memfd**, an object
   independent of the engine's shared mapping — which is exactly why the
   two fields could disagree.
2. `_execute_streaming` already had a pre-teardown stash for the scalar,
   but looked its relay channel up as `globals().get("_poison_ch")` while
   `_poison_ch` is a **local** of the forking scope. The lookup always
   yielded `None`, `_collect_plain_poison(None, ...)` returned early
   without touching `_LAST_STATS`, and an **empty index list** was
   published beside a correct scalar. The swallowed `NameError` is why
   this stayed silent.

**Whether the engine was still alive at summary time was a race.**
Instrumenting the accessor with the `fr_py_abort_reason()` sentinel
(`-1` exactly when `g_state` is NULL) showed the engine already destroyed on
the plain path, and identical runs were observed reporting both
`poisoned=0` and `poisoned=2`. A caller could rely on neither. **Do not
re-diagnose this as "usually fine" — the observable value was
timing-dependent.**

**Fix.** Both executors now capture the count before teardown and the
summary uses `max(live_read, stashed)`, reusing the `npois_stashed` idiom
`_execute_streaming` already used; `_execute_streaming` binds its channel
at function scope. No engine, supervision, or ABI change. Three mutations
(ingest stash, stream channel, stream stash) each turn the new tests red.

**Does not establish:** whether the reactor path is itself exact for every
poison policy; only that the two now agree.

---

### TD-12 — poison-index relay truncates u64 `batch_idx` to u32 (medium) — OPEN

**Pre-existing; affects the shipped cleanroom path, not introduced by
WO-PY-REL-1.**

`forkrun_ring.c:1421` declares `uint64_t batch_idx`, and the Python
out-param mirrors it (`_shim.c:87`). But the relay signature is
`fr_py_poison_relay(unsigned int batch_idx)` (`_shim.c:34`), invoked as
`fr_py_poison_relay((uint32_t)batch.batch_idx)` (`_shim.c:447`), and the
slot layout stores indices as `u32`. A batch index ≥ 2^32 is silently
truncated.

The reactor path is width-safe: it formats indices as decimal strings over
the trap-ACK pipe, which Python parses at full width.

Reachability, stated precisely — an earlier version of this entry got
the quantity wrong. `batch_idx` comes from `read_idx`, which is
incremented by `__atomic_fetch_add(..., 1, ...)` for **every batch
claimed** (`forkrun_ring.c:6222`), poisoned or not. So the trigger is not
"2^32 poisoned batches" but "a POISONED batch whose index is ≥ 2^32" —
i.e. roughly 2^32 batches processed in total, of which only that one
needs to be poisoned. The earlier phrasing overstated the requirement by
counting only poisoned batches, which understates the workload and
mislabels the mechanism. Still a very large run; no test constructs it,
so this is a reasoned bound, **not a measured one**.

Fixing it is not a local edit: the slot geometry `FR_POISON_SLOT_U32`, the
launcher's pre-size in `forkrun_cleanroom.c`, the v2 header's stride field,
and `_STATS_SLOT_U32` in `run.py` must all widen together, which means
rebuilding and re-shipping the `_forkrun_cleanroom` binary. That is a
release-level change, not a stats patch, and belongs in its own work
order.

**Does not establish:** that any real workload processes ~2^32 batches in
a single run; no such run was attempted.

---

### TD-13 — streaming peak retention ~0.5x OUTPUT bytes (high) — OPEN, re-diagnosed

**Re-investigated against current source (`357da3d9`..HEAD).** The
0.50x figure REPRODUCES, but the entry above mis-framed it, and the
mechanism question it explicitly left open is now answered.

**Reproduce** (isolated probe, current-RSS sampling inside the consumer
loop, consumer discards every yielded record):

```
python3 python/tests/_streaming_rss_probe.py --amp 5 --lines 400000 --delay 0.001
```

| output | peak growth | ratio |
|---|---|---|
| 23.4 MB | 11.6 MB | 0.519 |
| 47.4 MB | 22.3 MB | 0.493 |
| 94.9 MB | 43.0 MB | 0.476 |

So the core claim **stands**: retention scales with total output rather
than holding to a constant byte budget, and streaming is NOT
output-size independent. A four-fold output range gives a constant ratio,
not a constant number.

**What is now established that was not before.** The original entry said
the probe "cannot by itself separate" live retained objects, drain
buffering, and unreturned pages. It now can, by adding `tracemalloc`, a
live-object census, `gc.collect()`, and `/proc/self/smaps_rollup`:

| quantity | at 98.4 MB output |
|---|---|
| peak RSS growth | 43.1 MB (ratio 0.459) |
| **`tracemalloc` live after full drain** | **23.0 KB** |
| GC-tracked record objects after drain (corroboration only) | 0 |
| RSS growth after drain, pre- and post-`gc.collect()` | unchanged |

**There is no Python-object leak.** After a complete drain, Python holds
~23 KB against a ~43 MB peak. The peak is transient in-flight data, not
retained output.

**WHICH OF THOSE NUMBERS CARRIES THE ARGUMENT — stated so the census is
not over-read.** The load-bearing figure is **`tracemalloc`'s post-drain
live bytes**, because tracemalloc hooks the allocator and counts every
tracked allocation. The live-object census is **corroboration only**:
`gc.get_objects()` returns only objects the CYCLIC collector tracks, and
**not every `bytes`/`bytearray`/`memoryview` is GC-tracked**, so a census
of zero does not by itself prove the absence of every live bytes
allocation. If the two ever disagree, tracemalloc wins. (Correction to an
earlier draft of this entry, which led with the census.)

**Mechanism, source-localized.** `_drain_worker_memfd_terminal()`
(`run.py`) reads *all* new bytes from a worker's output memfd in one
`os.pread`, parses them into a Python list, and `_drain_records()` yields
from that list. The list stays alive for the whole yield loop, so peak
retention is one read's worth of output. Because the workers write into
**memfds with no backpressure**, a slow consumer lets them run arbitrarily
far ahead, and the in-flight window is bounded only by how much has been
produced since the last read — i.e. by output size, not by a window.
Measured directly: the ratio rises with consumer slowness
(0.409 at `--delay 0`, 0.519 at 1 ms, 0.561 at 10 ms).

`order="index"` is worse and by design: at the same 47.4 MB output its
peak ratio is **1.20** versus 0.495 for `order="none"`, because the
reassembly buffer holds out-of-order records behind a hole.

**Post-drain RSS is allocator behaviour, not retention.** Across runs the
final RSS after a complete drain was either baseline + ~45 MB or baseline
+ ~0.3 MB, with identical `tracemalloc` (~23-27 KB) and a zero census in
both. The committed probe therefore reports the resident figure from
`/proc/self/smaps_rollup` rather than `statm`, whose resident numbers the
kernel documents as potentially inaccurate. Freed glibc arenas are sometimes returned and sometimes not. **An RSS
reading after the run is therefore not evidence of a leak**, which is
precisely why this diagnosis used `tracemalloc` and an object census.

**Contract check (D3).** `stream()`'s public docstring and
`PYTHON_BEHAVIOR.md` promise **no** output-size independence and no
bounded-memory guarantee; the only "bounded" claim is the out-of-order
reassembly buffer, and even that is *warned* at a threshold rather than
capped (`_reassembly.py`; its own warning text says a poisoned/skipped
head "buffers the whole tail by design"). **The repo contains no unmet
public promise here.** The old test's claim ("holds only the in-flight
window") was a claim in the *test*, not in the API — already corrected.

**Not fixed here, and why (D4).** The only real fix is backpressure
between workers and the parent — an **engine** change in frozen files.
A parent-side alternative (read a bounded amount per round) would lower
measured parent RSS while leaving the same bytes resident in the memfd:
metric movement, not improvement, and exactly what this register warns
against. No speculative memory-management change was made.

**Follow-up proposal** (separate work order, engine scope): either add a
per-worker output high-water mark that blocks the worker, or reduce worker
read-ahead so a bounded window is real. Either needs a correctness review
of poison/retry interaction — a worker blocked on output can no longer be
reaped promptly.

**Reproduce the retention-vs-leak discrimination — committed, not
scratch.** The discriminating probe lives in the tree:

```
python3 python/tests/_streaming_memory_probe.py --lines 1600000 --delay 0.01
python3 python/tests/_streaming_memory_probe.py --lines 800000 --order index
```

It starts `tracemalloc` BEFORE the workload, drains the stream to
exhaustion while discarding every record, then reports post-drain
`tracemalloc` live bytes, a GC-tracked census (flagged in its own output
as corroboration only), and `/proc/self/smaps_rollup`. It is a diagnostic,
not a test: the leading underscore keeps it out of unittest discovery, so
it cannot make the suite pass or fail. **An earlier draft pointed at a
`/tmp` script for this, which meant the strongest evidence was not
reproducible from the repository; that is fixed.**

**Does not establish:** anything about the cleanroom launcher path (the
probe exercises the in-process generator executors only); and whether the
0.50 ratio is stable across machines or allocator versions.

#### TD-13 follow-up — WO-PY-STREAM-BACKPRESSURE-1: a partial read-ahead bound, NOT a byte bound

**Status: PARTIALLY MITIGATED, still OPEN.** The entry above says the
only real fix is backpressure between workers and the parent and that it
is an engine change in frozen files. A **parent-side** lever exists after
all: the worker-completion notification pipe's capacity *is* the
producer's read-ahead window, and it does not need the engine.

**The mechanism.** A worker that finishes a batch writes one 16-byte
notification; the parent reads them. The pipe holds N notifications, so N
is how many completions may be outstanding before a worker blocks writing
its notification — and a blocked worker cannot claim its next batch. The
per-worker output memfds have no backpressure of their own, so this pipe
is the only thing bounding how far a worker runs ahead of the drain. At
1 MB that bound was 65536 completions — wide enough that it was not a
bound. The public `stream()` paths now ask for 4 KB
(`STREAM_NOTIFY_PIPE_SIZE`, `forkrun/_pipes.py`): 256 completions.

**The 4 KB number is bash's, not a guess.** `frun.bash:1730-1731`:
`ring_pipe fd_order_r fd_order_w 4096`, commented *"B2: Size order ack
pipe to 4096 (1 page) for closed hydraulic backpressure"*. Bash sizes the
orchestrator's feedback channel to one page for exactly this reason.
Every other bash pipe (`fd_spawn`, `fd_fallow`, `fd_trap_ack`, the death
pipes, the per-worker pipes) is `ring_pipe` with no size argument — the
engine default `RING_PIPE_CAPACITY:=65536`. Bash has exactly one
deliberately-small channel and it is the feedback one.

**Measured (4M lines, amp 5, 4 reps, medians, 4M-line corpus = 977
batches; probe `_streaming_rss_probe.py`):**

| path | 1 MiB | 64 KiB | 16 KiB | **4 KiB** |
|---|---|---|---|---|
| plain supervision, peak retention (KB) | 240898 | 239626 | 243936 | **83936** |
| plain supervision, throughput (rec/s) | 3376 | 3445 | 3154 | **4596** |
| reactor supervision, peak retention (KB) | 251266 | 250754 | 250794 | 250332 |
| reactor supervision, throughput (rec/s) | 2080 | 2760 | 2814 | 2784 |

**The threshold is a cliff, and it is arithmetic, not tuning.** A pipe of
S bytes holds S/16 notifications, and it only binds if that is fewer
than the number of outstanding completions. This run produces 977
batches, so 16 KiB (1024 slots) can hold *every* notification of the run
and never blocks — which is why 1 MiB, 64 KiB and 16 KiB measure
identically. Only 4 KiB (256 slots) is below the read-ahead and
actually applies backpressure. **A capacity that is not smaller than the
run's outstanding-notification count does nothing**, so this is a
corpus-sensitive lever, not a universal one.

**What it fixes, and where it does not — and WHY, which is the useful
part.** Bash's backpressure is a CHAIN of three links and the ack pipe is
the LAST one: a slow consumer fills the **stdout pipe**, so `ring_order`
blocks writing stdout, so `ring_order` stops clearing the **ack pipe**,
so the ack pipe fills, so workers block on the ack. The ack pipe is
small (4096, one page) because it only has to *latch* a backpressure the
stdout pipe has already started.

The 4 KiB notification pipe IS that ack pipe. So it can only engage if
the chain upstream of it is closed — and it is closed on exactly one of
the two Python paths:

- **Plain supervision: the chain is closed.** Its drain is a generator
  that YIELDS INSIDE the collection loop (`run.py:5698`), so the next
  notification is not read until the consumer asks for the next record.
  The consumer's slowness stops the drain, the notification pipe fills,
  and the workers block. Measured: peak retention **-24% to -65%**,
  throughput **unchanged** -- no demonstrated penalty. The small-pipe
  arms measured HIGHER in the plain-path cells, which is consistent with
  less read-ahead pressure, but it is NOT characterised well enough to
  call a speedup. First-result latency unchanged.
- **Reactor supervision (the default): the chain is BROKEN AT ITS FIRST
  LINK.** Its drain collects into a `_pending` list and pops one record
  at a time (`run.py:9207`), and the reactor pulls up to `DRAIN_BURST`
  (64) records per round regardless of the consumer. The consumer's
  slowness is absorbed by a **Python list**, not by a pipe: the
  notification pipe never fills, the ack-pipe analogue never engages,
  and the parent's own memory grows instead. Measured: **no change**
  (-0.4% to +3.7%), throughput unchanged.

**The missing piece on the default path is bash's stdout-pipe
analogue** — a bounded transport between the drain and the consumer that
blocks the producer when the consumer falls behind. Making the reactor's
drain consumer-paced like the plain path's is NOT an option:
`DRAIN_BURST` exists to bound death-detection latency, and a fully
consumer-paced drain would starve the supervisor. The C drain's results
pipe already IS that transport (see below), and it is the reason its
retention is flat.

**The threshold is a cliff, and it is arithmetic, not tuning.** A pipe of
S bytes holds S/16 notifications, and it only binds if that is fewer
than the number of outstanding completions. This run produces 977
batches, so 16 KiB (1024 slots) can hold *every* notification of the run
and never blocks — which is why 1 MiB, 64 KiB and 16 KiB measure
identically. Only 4 KiB (256 slots) is below the read-ahead and
actually applies backpressure. **A capacity that is not smaller than the
run's outstanding-notification count does nothing**, so this is a
corpus-sensitive lever, not a universal one.

**This is NOT a hard byte bound, and the caveats above still stand.**
- A single batch can still generate large output: the legacy drain's
  quantum reads one read's worth of output into a Python list, and that
  list stays alive for the whole yield loop.
- `order="index"` can still buffer behind a poisoned or skipped head, by
  design; a smaller notification pipe does not change that (and the
  reassembly buffer is downstream of the notification pipe entirely).
- The bound is on COMPLETIONS, not bytes: 256 completions of a 4 MB
  batch is still 1 GB of in-flight output.

**A better answer for the default path exists and is NOT this.** The
C drain's results pipe is a real backpressure stage, and its retention is
**flat at ~3.5 MB regardless of scale** where the legacy drain's grows
linearly to 138 MB:

| output | legacy drain retention | C drain retention |
|---|---|---|
| 5.4 MB | 8.3 MB | 3.0 MB |
| 29.4 MB | 37.5 MB | 3.5 MB |
| 124.4 MB | 138.3 MB | **3.6 MB** |

The C drain is therefore the right mechanism for the default path — and
it WAS 16-19x SLOWER than the legacy drain there, for a reason that has
nothing to do with memory: its pump read 65536 bytes per call and
returned `None` whenever that did not complete a blob, which ended the
reactor's `DRAIN_BURST`, which left `drained_last` False, which made the
reactor's next `select()` wait the full `poll_timeout` (0.1s).
Instrumented at 250k lines: 162 select calls, **9.72s of a 10.43s run
spent waiting**, 97 calls over 50ms — against 5 select calls and 0.01s
waited for the legacy drain. The reactor's own comment names the cap:
*"otherwise throughput caps at ~10 blobs/s (one yield per 100ms idle
select)"*. Below ~64 blobs (the `DRAIN_BURST` size) the C drain matched
the legacy drain (1.01-1.21x) — which is very likely where the
"0.7-1.0x" figure in `run.py`'s `_validate_c_drain` came from.

**[FIXED — WO-PY-CDRAIN-REACTOR-WAKEUP-1.]** The park is gone. The
reactor now SELECTS on the results pipe (an `ExtraWatch` holder the
reactor wakes on but never reads — the pump keeps sole ownership of the
read side, and the holder is disarmed at EOF so a readable-EOF pipe
cannot spin the reactor), and the pump consumes everything already
available instead of one chunk per call.

| | before | after |
|---|---|---|
| C/legacy wall at 250k lines | 15.96x | **1.02x** |
| C/legacy wall at 2M lines | 19.19x | **1.02x** |
| select() calls / time waited (250k) | 162 calls / 9.72s | **6 calls / 0.003s** |
| C drain peak retention, 124MB output | 3.6 MB (flat) | **4.4 MB (flat)** |

Correctness: 14/14 configurations byte-identical to the legacy drain.
First-result latency and death-detection latency unchanged or better.
The results-pipe and notification-pipe capacities were NOT changed, and
the frozen files are untouched.

**The bound is part of the fix, not an optimisation of it.** Implementing
the two steps literally — read until EAGAIN, unbounded — queued the run's
whole output in the parent's `pending` deque and took the C drain's peak
retention from a flat 3.5MB to ~18MB, for NO wall-time gain (the wakeup
had already removed the park). The pump therefore bounds its read-ahead
by the bytes it has parsed but not yet handed to the consumer
(`pending_bytes` against a 256KB budget), so the read-ahead is bounded by
the consumer's pace rather than by the pipe.

**What this does NOT do:** it does not make the C drain the default, and
it does not establish a constant-byte bound for any streaming path. The
C drain's retention is flat because its results pipe bounds the
read-ahead, and that bound is 1MB of *queued output*, not a byte budget
for a single record. `order="index"` is not served by the C drain at all
(`use_drain = ... and not use_orderer`), so its retention is the legacy
path's and is unaffected. See `dev/supervisor/WO_PY_CDRAIN_REACTOR_WAKEUP_1_REPORT.md`.

**Reproduce (committed probes, no scratch):**

```
# capacity A/B, actual capacity recorded per run:
FORKRUN_STREAM_NOTIFY_PIPE_SIZE=1048576 python3 python/tests/_streaming_rss_probe.py \
    --lines 4000000 --amp 5 --delay 0.01 --order none --orchestrator 0
python3 python/tests/_streaming_rss_probe.py \
    --lines 4000000 --amp 5 --delay 0.01 --order none --orchestrator 0
# C drain vs legacy, across scale:
python3 python/tests/_streaming_rss_probe.py --lines 250000 --amp 5 \
    --delay 0.01 --orchestrator 1 --c-drain
```

---


### TD-14 — `test_spawn_ordered` compared two paths element-wise (low) — RECLASSIFIED

**First reported as a verified public-API inconsistency. That was wrong,
and external review caught it. Correcting the record.**

Original claim: under `FORKRUN_CLEANROOM=1`, `map(spawn)` returns
memoryviews while `stream(spawn)` returns bytes, therefore the public API
is inconsistent.

It is not. `python/docs/API.md` documents this, in the `output` row:

> `"view"` (zero-copy views) or `"bytes"`; `stream()` always yields
> `bytes` regardless

So `map()` defaulting to views while `stream()` always yields bytes is the
**documented, intended** contract, not a divergence. There is a second,
independent reason the element-wise expectation was never sound: batch
boundaries are not guaranteed identical between two runs of the same
input — this repo records that blob-count variance is valid and shared
with the in-process path, which is why the working rule elsewhere is to
compare JOINED bytes.

Measured before the test was changed, under `FORKRUN_CLEANROOM=1`:

```
element-wise list equality   -> False
joined bytes stream == map   -> True
joined bytes == input file   -> True (both paths)
```

The output was correct in every configuration; only the assertion was
wrong. `test_spawn.py::test_spawn_ordered` now compares joined bytes and
checks both paths against the input file as an independent reference, and
passes under `FORKRUN_CLEANROOM` unset, `off` and `1`.

**Kept as a low-priority entry** rather than deleted, because the
underlying question is worth one line of memory: if two public entry
points are meant to be drop-in replacements, a caller who writes
`assertEqual(stream(a), b(a))` gets a confusing failure. Nothing in the
documented contract promises element-level interchangeability, so this is
a documentation/ergonomics consideration, not a defect. If that is ever
wanted it is a deliberate API decision, not a bug fix.

**Does not establish:** anything about spawn correctness beyond the byte
equality this test now checks.

---

### TD-15 — The reactor lost the poison notification when the last worker exited (high) — FIXED

**Symptom.** A reactor-path run reported a non-zero `poisoned` count beside
an **empty** `poisoned_batches` list. The two fields are read from
different places — the scalar from the engine, the index list from the
trap-ACK pipe the worker writes its `P:<idx>:<kills>` notification to — so
an empty list beside a non-zero count means one run was being described
two ways at once. That is the exact shape TD-09 was about, on a different
path and by a different mechanism, and it is why
`test_poison_accounting.assertContractHolds` treats a complete list as
having one index per poisoned batch.

**How it was found.** One occurrence, in `test_fault.test_map_return_stats`
inside a full-suite run. It did not reproduce standalone (0/200 runs), did
not reproduce in a 570-test prefix of the suite, and did not reproduce in a
second full-suite run. The lesson from the repo's own history applies: an
order-dependent, load-sensitive failure is a defect to root-cause, not to
call flaky.

**Root cause.** The reactor's termination branch breaks out when no worker
is alive and no trap-ACK grace deadline is outstanding. The grace deadline
is what keeps the loop alive to poll for the `<wid>` graceful-failure ACK;
the poison notification arms **no** deadline, so nothing kept the run alive
on its behalf.

The window in which it could be lost is the gap between a round's
`select()` and the out-of-band exit sweep. The death pipe is the primary
death detector, but `reap_clean_exits()` is a `waitpid(WNOHANG)` backstop
that can observe a worker's exit in a round whose `select()` snapshot
*predates* that worker's write. The parent then learns of the death
through `waitpid` while the notification arrives through the pipe, and the
loop reaches its termination branch in between.

**Proof, not inference.** Delaying the backstop sweep by 2 ms widens
exactly that gap and nothing else. With the fix absent the notification was
lost on **47–58 runs in 60** across the worker and line-batch combinations
tried; with the fix in place, **0 in 150**.

**Fix (W-PYPOISONDRAIN).** The supervision loop drains the trap-ACK pipe
before it leaves. The drain cannot block: readability is checked with a
zero-timeout `select()` first, and a read is issued only when there is
something to take.

**Coverage.** `test_poison_accounting.TestPoisonNotificationSurvivesTeardown`
widens the window deliberately and asserts the count and the list describe
the same run; a companion test asserts the widener is actually in force, so
the regression cannot go vacuously green if the sweep stops being called.

**A detail worth recording, because it cost a test rewrite.** The first
version of the regression test used the module's plugin fixture and the
mutant **survived** it: the C plugin loop's notification write and its exit
are far enough apart that the widened window still does not straddle them.
The in-process payload loop (`mode="python"`) writes the notification and
reaches its exit immediately afterwards, which is the shape that puts the
write next to the exit. The fixture is now chosen on that measurement, not
on convenience.

**Does not establish:** anything about the plugin path being immune — it was
simply not observed to lose under this delay. The two mechanisms share the
pipe and the termination path, so the fix covers both; the plugin path's
wider window is a statement about this fixture, not a guarantee.
