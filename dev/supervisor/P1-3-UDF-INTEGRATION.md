# P1-3 — UDF helper integration: where does the interpreter live?

Status: **design brief, for review.** Nothing implemented.
Predecessor: DECISION-01 §9 (helper exists, C0.4 answered).
Branch: `NEW/REFACTOR4.2`.

## 1. The question

`fr_udf.c` builds and is measured. What is not decided is *where the
interpreter gets initialised and where the per-batch UDF call site lives*.

This is not a free choice: the answer determines whether workers pay an
interpreter start each, and it interacts with both supervision policies.

## 2. Constraints that already bind

**(a) The helper cannot be loaded into a process that has Python.**
DECISION-01 §9.2 — `fr_udf_init` calls `Py_InitializeFromConfig`; doing
that in a live interpreter is undefined and core-dumps in practice. So the
host must be a process with no interpreter. The launcher qualifies; the
Python parent does not.

**(b) Pre-fork is measured and works** (DECISION-01 §9.3): a forked child
inherits the interpreter and runs the UDF correctly, 4–8× faster than
post-fork. This is safe only because the launcher is single-threaded at
the fork.

**(c) The codebase already has a precedent, and states the rule.**
`forkrun_cleanroom.c` `spawn_wid`:

> Takes the pointer the parent already resolved: dlopen after fork is a
> classic post-fork hazard.

and `g_poison_stats_fd`:

> Set once in `main()` before any fork so it is inherited.

So the existing design already resolves "dlopen pre-fork, inherit" for
both the substrate handle and the poison relay. The UDF helper is a third
instance of a pattern the launcher is built around.

**(d) `forkrun_cleanroom.c` is NOT frozen.** The freeze list is
`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`. The launcher
is modifiable — provided the engine is not touched, which this does not
require.

## 3. Options

**Option A — launcher-owned, pre-fork (recommended).**
`main()` resolves and `dlopen`s the helper, calls `fr_udf_init` once,
*before any fork*. The handle and init state are inherited by every
worker. The per-batch call lives in the worker path
(`fr_py_worker_plugin_loop`, which the cleanroom already runs per worker).

*Satisfies (a) — launcher has no interpreter. (b) — pre-fork. (c) —
identical to the existing pattern for the substrate and poison relay.*

**Option B — shim-owned lazy init (`_shim.c` dlopens on first use).**
Simpler: no launcher changes. But first use happens *inside a worker*,
after fork. That is post-fork by construction — the 4–8× slower path, per
worker, forever. Directly contradicts (c).

**Option C — run.py-owned, path passed down.**
The parent resolves nothing; it hands the helper path to the launcher via
argv/env, launcher does A. Functionally A with extra plumbing, and it
puts an interpreter concern in the process that must not have one.
Rejected: adds a channel for no behaviour change.

## 4. Recommendation — Option A

Three reasons, in order of weight:

1. **It is the only option that gets the measured win.** B is post-fork by
   construction. C is A with a needless channel.
2. **It follows a rule the launcher already documents and enforces.**
   Introducing a second, different dlopen discipline for the third
   handle would be the inconsistency, not Option A.
3. **It needs no engine change**, so the freeze holds.

## 5. Where the genuine open choice remains

Option A settles *where init happens*. Two things it does **not** settle,
and which should be decided with evidence rather than assumed:

* **The per-batch call site.** `fr_py_worker_plugin_loop` is the natural
  home, but it is a *plugin* loop (built for C plugins, with its own
  `forkrun_use_ctx` handshake at `forkrun_ring.c:9741`). Is the Python UDF
  a plugin that happens to embed an interpreter, or a distinct path? This
  affects whether the existing plugin dlopen machinery is reused or
  bypassed. **This is the part worth review.**
* **Interaction with supervision.** Under `recover`, a worker that dies
  mid-UDF is respawned; under `fail-fast` the run aborts. A UDF has
  Python-level state and can leave imported modules half-initialised.
  *RESOLVED by measurement — see §5.1.*

### 5.1 Respawn inheritance — MEASURED, and the answer is reassuring

`fr_udf_fork --respawn` dirties interpreter state in one generation, kills
it without cleanup, then forks the next generation and asks whether the
state survived.

**Result: CLEAN.** A respawned generation does **not** inherit the dead
generation's interpreter state. Under pre-fork each generation is a fresh
fork of the launcher, which still holds the *pristine* pre-fork
interpreter, so the dirt dies with the child that made it.

This was worth measuring rather than arguing, because the failure would be
silent and shared: two batches observing each other's mutated module
globals, non-deterministically, only on the recovery path.

**The probe carries its own negative control** (`--control`), and this is
the part that makes the CLEAN verdict mean anything: it dirties and checks
in a *single* process, where the state certainly survives, and must
report DIRTY. A probe capable of only ever answering CLEAN would pass the
respawn test forever while detecting nothing. Both directions are pinned
by tests, and the DIRTY side is mutation-checked.

Two bugs surfaced while building it, both mine and both the kind that
produce a confident wrong answer:

* The respawn branch ran *after* `fr_udf_finalize()`, so every call
  returned "not initialized" and the probe reported **INCONCLUSIVE** —
  which looks like "no evidence" rather than like "the harness is
  broken".
* Children inherited the parent's unflushed `stdout` buffer, and a child
  that finalises Python flushes stdio on the way out. Each child
  re-printed the header, making one run look like four.

## 6. What "done" means for P1-3

* A UDF that resolves, runs, and emits through the existing record path,
  under **both** `--supervise recover` and `--supervise fail-fast`.
* A UDF returning `None` → `NO_RESULT`; `b""` → empty `DATA` (DECISION-02).
* A UDF that raises → worker death, handled by the normal supervision
  path, not by new special-casing.
* A respawn test that proves a fresh generation does not inherit dirty
  interpreter state.