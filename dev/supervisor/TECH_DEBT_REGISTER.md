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

| id | entry | pri | status |
|---|---|---|---|
| TD-01 | Record protocol defined in three independent places | high | **verified** |
| TD-02 | Payload import timing documented backwards | high | **verified** |
| TD-03 | `_api.py` still describes a Stage 0 stub | med | **verified** |
| TD-04 | Environment propagation: explicit in bash, implicit in Python | med | **verified divergence** |
| TD-05 | Retry semantics: `-E` flag has no Python counterpart | med | **verified divergence** |
| TD-06 | Executor consolidation audit not performed | med | **unverified claim** |
| TD-07 | README collapses v0 history into current capability | low | **unverified claim** |

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

### TD-02 — Payload import timing documented backwards (high)

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
lock. This is a two-line documentation fix with real blast radius, and it
is the cheapest high-value item in the register.

**Does not establish:** that any user has been harmed by this.

---

### TD-03 — `_api.py` describes a Stage 0 stub (medium)

**Verified.** `python/forkrun/_api.py:1` opens *"forkrun Python frontend
— Stage 0 API surface stub (v1.3 §3.0)"* and line 6 says the surface
*"then raises NotImplementedError until Stage 4 wires the substrate."*
The frontend is implemented and shipping; the docstring is a fossil.

---

### TD-04 — Environment propagation: explicit vs implicit (medium)

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

### TD-06 — Executor consolidation audit not performed (medium)

**Unverified claim. Do not act on this yet.**

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