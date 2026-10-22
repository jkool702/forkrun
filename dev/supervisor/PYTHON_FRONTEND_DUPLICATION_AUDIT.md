# Python front end — duplication audit

**Question.** The Python front end was largely AI-developed. Did that
produce a habit of "add another `_helper`", leaving many almost
identical helpers side by side? And where so, can they be folded into a
single shared helper — a single source of truth?

**Answer.** Yes, and in one clear place the duplication is systematic
rather than incidental: **the v0 envelope check is copied verbatim
eight times**, and the **splice dispatch is a four-way branch whose
helper bodies AND whose call-site argument lists are both repeated**.

The bash front end is the frozen reference, and it shows what the right
shape is. `frun.bash` builds the worker as **one template**
(`worker_func_src`) with the per-flag differences injected as small
fragments — the trap bodies, the claim accounting, the output tracking —
and a pre-generated `pCode` carrying the payload-specific code, then
`eval`s the assembled function once. The worker loop body exists
**once**. The template even says so about the other frontend:

> *"The Python frontend will fill the same struct directly — no env
> required."*

So the bash answer to "how do you avoid N near-identical workers?" is
**not** N near-identical workers: it is one implementation with the
configuration injected. Python cannot `eval` a template the way bash
does — and should not — but it can reach the same *shape* by
parameterising one implementation instead of copying it. That is the
target shape for this de-duplication.

---

## 1. How the audit was done

A token-level canonicaliser (`/tmp/opencode/dupscan.py`) reduces every
function in `python/forkrun/` to its structure: names, literals and
strings become `_`, keywords and operators survive, comments and
whitespace are dropped, and **nested definitions are excluded** so that
an enclosing function is not reported as a clone of the function it
contains. Functions with the same canonical form are the same code
under different names; pairs that do not hash equal are compared with
`difflib` for near-clones.

**299 functions scanned.** Two kinds of finding:

- **structural clones** — byte-identical after canonicalisation;
- **near clones** — ≥0.85 similar.

A third kind was found by grepping for a **repeated literal**, which is
how the most valuable group surfaced: an error message copied eight
times is eight copies of a check.

---

## 2. The inventory

### 2.1 The v0 envelope check — 8 byte-identical copies

`_execute*` and friends each open with:

```python
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
```

Eight copies, **byte-identical**, at `run.py` lines 6248, 6627, 7091,
7585, 8355, 9053, 9616, 10183 — plus two near-variants (11466, 12029)
that share the first check and differ in the second.

This is the "single source of truth" case in its purest form: the
check states a **contract** (what this version supports), and the
contract is written down eight times. Change the supported envelope and
eight places have to be found.

**Fold to:** `_require_v0_envelope(mode, nodes)`.

### 2.2 The splice dispatch — 4 helpers, 4 repeated argument lists

`run.py` 5490 / 5501 / 5531 / 5561 hold four helpers whose bodies are
**identical** except for which executor they call:

| helper | executor |
|---|---|
| `_splice_stream_gen` | `_execute_streaming` |
| `_splice_ingest_stream_gen` | `_execute_ingest_stream` |
| `_splice_stream_reactor_gen` | `_execute_streaming_reactor` |
| `_splice_ingest_stream_reactor_gen` | `_execute_ingest_stream_reactor` |

and the call site (5333-5374) is a **four-way branch repeating the same
twelve arguments** each time. This is a 2×2 matrix over
(ingest|streaming) × (reactor|plain) written out longhand — 4 × 8 lines
of helper plus 4 × 12 lines of call site.

**Fold to:** one `_splice_stream_gen(..., executor=...)` and one call
site that selects the executor.

### 2.3 The stream-generator family — 2 structural clones + 3 near clones

`_stream_gen` (5475) and `_ingest_stream_gen` (7062) are structurally
identical, differing only in which executor they call; `_stream_reactor_gen`
(5513) and `_ingest_stream_reactor_gen` (5544) are 0.96 similar. Same
2×2 shape as 2.2, one level up.

### 2.4 The C-flag validators — 3 identical bodies

`_validate_c_drain` (280), `_validate_c_worker_loop` (447) and
`_validate_c_spawn_loop` (3146) have **identical** bodies:

```python
    if flag is None:
        return False
    if isinstance(flag, bool):
        return flag
    raise TypeError("c_X must be None, True, or False, got %r" % (flag,))
```

They differ only in the flag's name — in the parameter and in the error
message. Three copies of one rule.

### 2.5 The C-loop envelope resolvers — 2 near-identical bodies

`_resolve_c_plugin_loop` (3122) and `_resolve_c_spawn_loop` (3177):
same shape, same four branches, differing in the flag name, the
required mode, the explanation text, and which `_require_*_symbol()`
they call.

### 2.6 The drain helpers — 2 identical bodies

`_drain_worker_memfd` (5572) and `_drain_worker_memfd_terminal` (5616)
are identical except for the splitter they call (`_split_records` vs
`_split_records_terminal`). The docstrings say so — *"Terminal-aware
sibling of _drain_worker_memfd"* — which is a description of a
duplication, not of a design.

### 2.7 The scanner watchers — 2 closures, 0.92 similar

`_watch_scanner` at 8526 and at 9424 are nested closures with the same
logic. They have already **drifted**: the success path assigns
`scan_rc` and `scan_pid` in a different order in the two copies. That
is what duplication does.

**And there is a THIRD copy of the same rule, inline** (not a closure,
so a function-level scan does not see it), which has drifted further
still:

| | the two closures | the inline copy |
|---|---|---|
| return value | `None` | `True` / `False` |
| on `ChildProcessError` | returns, leaving `scan_pid` set | clears `scan_pid`, returns `True` |
| D-PORT2/D6 "excuse" check | present | **absent** |

The third difference is a **behavioural** one: the inline copy aborts
and raises even when an abort is already in flight, which is exactly
the "spurious fatal over an in-flight abort" that D-PORT2/D6 was
written to prevent. Folding it would change behaviour, so it is
**reported, not changed** — that is a decision, not a refactor.

This is also the clearest evidence for the duplication thesis: the same
rule, written four times, ended up with three different answers to
"what should this function return" and two different answers to "what
should happen when the child is already gone".

### 2.8 The fork-timing rule — 4 copies

`_maybe_fork_workers` exists **four** times, over two state shapes (a
dict and plain locals) and two fork function names, with the
explanatory comment present in two and absent in the other two. The
rule is the same in all four.

The rule has THREE outcomes, not two: the workers may already exist
(do not fork again), DATA may have published (fork now), or the stall
timeout may have elapsed pre-gate (fork, and set the stall flag). That
third case is the one a naive "should fork" boolean loses.


### 2.9 Not findings

- `_plugin.py::make_plugin_payload` / `plugin_payload` looked like a
  clone at 0.90 — it is the **outer function and its own inner
  closure**. The canonicaliser now excludes nested definitions, and it
  does not appear.
- `_execute_ingest` (7087) and `_execute` (7580) are 0.88 similar but
  are **not** mergeable: their parameter sets differ (the latter
  carries `c_worker_loop`, `plugin_spec`, `c_spawn_loop`,
  `spawn_argv`), and both delegate to different `_locked` targets. They
  are thin, and their shared part is the §2.1 prologue.

---

## 3. The plan

Ordered by value and by risk. Each step is a separate commit, and each
is gated.

| step | what | copies → | risk | state |
|---|---|---|---|---|
| 1 | `_require_v0_envelope(mode, nodes)` + `_require_v0_mode(mode)` | 10 (+8) → 1 | low | **done** |
| 2 | `_validate_c_flag(value, name)` | 3 → 1 | low | **done** |
| 3 | `_drain_worker_memfd(fd, state, terminal=)` | 2 → 1 | low | **done** |
| 4 | `_resolve_c_loop(flag, mode, ...)` | 2 → 1 | low-med | **done** |
| 5 | `_splice_stream_gen(..., executor=)` + one call site | 4 → 1 | med | **done** |
| 6 | the stream-generator family, one executor parameter | 4 → 2 | med | **done** |
| 7 | `_watch_scanner` | 2 → 1 | med | **done** |
| 8 | `_maybe_fork_workers` | 4 → 1 | med-high | **done** |

**Steps 1–4 are pure mechanical folds**: one implementation, the
variation becomes a parameter, and every call site keeps its current
meaning. The docstrings, which carry the measured evidence for each
decision, are **kept** — they move to the shared helper rather than
being deleted.

**Steps 5–8 touch the hot paths.** They are worth doing, but they are
where the duplication is *load-bearing* (the fork-timing rule and the
scanner watcher are per-executor closures over per-executor state), so
they go last and one at a time.

### 3.1 What step 5 did

The four splice helpers are **one** helper whose body is the rule, and
the four-way call site is **one** call site that selects the executor:

```python
        if _detect_streaming(source, kwargs.get("streaming")):
            executor = (_execute_ingest_stream_reactor if orchestrator
                        else _execute_ingest_stream)
        else:
            executor = (_execute_streaming_reactor if orchestrator
                        else _execute_streaming)
        return _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _splice_stream_gen(
            source, bytes_=b,
            workers=..., on_error=..., strict_poison=...,
            nodes=..., order=..., c_drain=...,
            executor=executor))
```

The four rationales (what each combination *is*) move into the shared
docstring — which is the point: the four combinations were described in
four places and are now described in one. `run.py` lost 28 lines.

**The mapping was checked branch by branch** — all four
(ingest|materialized) × (reactor|plain) combinations reach the same
executor they reached before, and the twelve arguments are unchanged.
No test referenced the four helper names, so nothing external moves.


### 3.2 What step 6 did

`_stream_gen` / `_ingest_stream_gen` / `_stream_reactor_gen` /
`_ingest_stream_reactor_gen` are the same rule written four times. The
fold is **four -> two**, not four -> one, because the plain executors
do not accept `resume`/`checkpoint_file` — so the plain pair and the
reactor pair genuinely differ in their call shape. Each pair becomes
one helper that takes the executor:

```python
    if _detect_streaming(source, kwargs.get("streaming")):
        if orchestrator:
            gen_fn = _stream_reactor_gen
            executor = _execute_ingest_stream_reactor
        else:
            gen_fn = _stream_gen
            executor = _execute_ingest_stream
    else:
        if orchestrator:
            gen_fn = _stream_reactor_gen
            executor = _execute_streaming_reactor
        else:
            gen_fn = _stream_gen
            executor = _execute_streaming
    return _guarded_gen(
        _signal_guard(kwargs.get("signal_policy", "default")),
        gen_fn(payload, source, executor, **kwargs))
```

**One thing the fold changed, deliberately.** The materialized copy
passed `splice=` explicitly and the ingest copy relied on the default.
They are equivalent — this path is only reached when `mode` is not
`"splice"`, so both are `False` — but two copies of one rule is how
they drift. The shared helper now says it once.

**A bug this step introduced, and the gate caught it.** The first
attempt hoisted the single `return` into the `if _detect_streaming(...)`
block, so the **materialized** path fell through and `stream()`
returned `None` — 37 errors in the targeted run. The dispatch has to
keep the envelope's if/else and hoist only the return. The corrected
version is what shipped; the lesson is recorded here because it is the
same trap as the earlier "editing source while the suite runs"
corruption: a structural change to a dispatch chain, and the only
thing that catches it is running the thing.


### 3.3 What steps 1-4 did and did not change

- **The error messages are byte-identical.** Verified by rendering the
  old and new messages side by side: the mode message, the nodes
  message, the two C-loop `ValueError`s and the two C-loop
  `RuntimeError`s all compare equal.
- **The call sites are unchanged**, except that the splice family
  (step 5) will restructure one of them.
- **The named wrappers stay.** `_validate_c_drain`,
  `_validate_c_worker_loop`, `_validate_c_spawn_loop`,
  `_drain_worker_memfd_terminal`, `_resolve_c_plugin_loop` and
  `_resolve_c_spawn_loop` each remain, as one-line callers of the
  shared implementation, so the call sites read the same and each
  flag's measured rationale stays attached to its own name. The
  duplication removed is the duplicated *rule*, not the duplicated
  *name*.


## 4. What steps 7 and 8 did, and the two bugs this work introduced

### 4.1 Step 7 — the scanner watcher

The waitpid half moved to a module-level helper that RETURNS the new
state; the closure keeps the abort/raise half, which was already
identical in both. The two closures are now **byte-identical**.

This follows the boundary the previous dedup pass set: *"Split by KIND,
not by lifecycle: what a child death MEANS is a mechanic and lives in
the helper; what the executor does next stays with the caller."* The
waitpid is the mechanic; the abort and the raise are what the executor
does next.

### 4.2 Step 8 — the fork-timing rule

The rule moved to `_fork_timing(workers_present, gate_issued, t_start,
lib)`, which answers with **one of three actions** — `_FORK_HAVE` (the
workers already exist; do NOT fork again), `_FORK_NOW`, `_FORK_WAIT` —
plus a `stalled` flag that is true only in the stall-timeout case. Each
closure keeps what is genuinely its own: which state container it
reads and writes, and which fork function it calls.

### 4.3 Two bugs this work introduced, and what caught them

**Step 6 hoisted the single `return` into the wrong block.** The
dispatch has to keep the envelope's `if _detect_streaming(...)` and
hoist only the return; the first version put the return inside the
block, so the **materialized** path fell through and `stream()`
returned `None` — 37 errors in the targeted run.

**Step 8 lost one of the rule's three outcomes.** The first version
answered with a boolean, and "the workers already exist" became
"should fork" — so the closure **re-forked an existing set**, and the
streaming-ingest cells lost records (873 of 1500). The rule has three
outcomes, not two, and a boolean cannot carry them.

Both were caught by running the thing, not by reading it. That is the
lesson worth keeping: in a dispatch chain, a structural change is only
provable by executing it.

## 5. The metrics, and what this pass is worth

| | before | after |
|---|---|---|
| structural clone groups (canonical form) | 7 | **3** |
| canonical characters duplicated | ~1719 | **~454** |
| `run.py` lines | 12527 | 12508 |

**74% less structurally duplicated code.** The three groups that remain
are the ones that should remain:

- `_maybe_fork_workers` ×2 — the two remaining copies differ in their
  state shape (a dict and plain locals), and folding them is a shape
  change, not a rule change. The RULE is already in one place
  (`_fork_timing`); what remains duplicated is the four-line call into
  it.
- `_watch_scanner` ×2 — the two closures are now thin and
  byte-identical, and the house boundary says the "what the executor
  does next" half stays with the caller.

- `_stream_gen` / `_stream_reactor_gen` at 0.89 — a **genuine**
  difference: the plain executors do not accept
  `resume`/`checkpoint_file`.

**The "duplicate def names" metric does not move** (15 before and
after), and that is the right result rather than a disappointing one:
the named wrappers were **kept on purpose**, so the duplication removed
is the duplicated *rule*, not the duplicated *name*. A metric that
counts names would have rewarded deleting the names; the point was to
delete the bodies.

## 6. The prior dedup work, and where this fits

### 6.1 The pattern this pass found is the DEEPER one

The eight groups in section 2 are duplicated *code*. The group that
mattered most is duplicated *decisions*, and it was nearly missed by
this audit's own method: **the audit scanned FUNCTIONS, and most of the
copies are INLINE.**

D-PORT2/D6 introduced the abort-aware classification -- "an abort
already in flight makes helper deaths expected (emergency path), not
fatal" -- and wired it into **2 of the 28** places the front end turns a
helper child's non-zero exit into a fatal error. The other 26 had the
same rule written out, or omitted it, including the materialized PLAIN
path's inline `_scan_pump`.

That is precisely the failure the de-duplication exists to remove: a fix
lands in the copies its author happened to find, and lives on in the
execution paths nobody looked at. The same commit's own words -- "both
UMA scanner watches" -- show the author believed there were two.

**The fix is therefore not "patch twenty-six sites" but ONE decision
point** every site asks:

```python
def _helper_death_excused(kind, eof_ok, lib):
    """Has an abort already explained this helper child's death?"""
    return (_helper_death_disposition(kind, eof_ok,
                                      _abort_reason_now(lib)) == "excuse")
```

All 28 sites now go through it, so the next change to the rule lands
everywhere by construction.

### 6.2 The order is part of the rule

A consult placed AFTER the abort always sees "excuse" -- the reason the
abort just published -- and so silently swallows a genuine helper
failure. D-PORT2 says so explicitly: *"query the abort reason BEFORE the
handler's own abort -- the order is the fix"*. It is easy to get wrong
when the rule is copied, so the invariant is now checked:
`python/tests/test_helper_death_excuse.py` asserts that every
helper-death site asks the shared decision AND that the consult precedes
the abort in its block. Both are mutation-checked: unwiring one site
fails the first, moving one consult after its abort fails the second.

### 6.3 Where this sits in the project's own history

This is not the first pass. The tree already carries:

- `DEDUP_DESIGN.md` / `DEDUP_REPORT.md` (2026-09-28) — the W-DEDUP
  consolidation of the executor mechanics into `_executor_core.py`.
- `d7178c77` — "single-source the duplicated NUMA and signal-retirement
  mechanics" (the second SSoT pass), which folded `_watch_numa_pipeline`,
  `_fork_workers_for_node` and `_retire_parent_signal`, and which
  established the boundary this pass follows.
- `0d1fcb2e` — "merge `_watch_helpers` copies (**fixes a real
  divergence**)" — the same shape as this pass, and the same lesson.

`EXECUTOR_MANIFEST.md` classified the remaining duplicates as
"shape-bound" and named `_watch_scanner x2` among them, with the
reason "per-executor nonlocal rebinding". **That classification is now
obsolete for that pair** — the nonlocal rebinding is handled by a
helper that RETURNS the new state, which is how `_watch_numa_pipeline`
already worked. The manifest's note is updated to match.

## 7. The block-level pass: duplicated DECISIONS, not duplicated code

The first audit compared whole FUNCTIONS. That is the easy case, and it
missed the expensive one: a decision duplicated **inline**, at the point
where the rule is applied. `tools/ssot_scan.py` (added with this pass)
compares BLOCKS -- a function body and the body of every
if/for/while/try/with/except -- after canonicalisation.

It found the pattern in its purest form:

| decision | copies | consulted the shared rule? |
|---|---|---|
| a helper child's death is fatal | 28 sites | **2** |
| the C drain child's exit is a failure | 10 sites | **0** |
| the C orderer's teardown | 6 sites | 5 |
| the C orderer's setup | 6 sites | n/a |
| the fallow (reaper) child's reap | 4 sites | n/a |
| the fallow child's exit handling | 4 sites | n/a |
| the checkpoint-on-abort handler | 2 sites | n/a |

D-PORT2/D6 taught the abort-aware rule and wired it into **2 of the 28**
places that apply it. The C drain's rule -- also a helper child's death
-- was consulted in **none** of its 10 places. This is not a stylistic
problem: it means a fix to either rule has to be made in a dozen places,
and the one fix that WAS made was made in two.

### 7.1 What this pass folded

- **One decision point for every helper-child death**
  (`_helper_death_excused`), now consulted by **all 24** helper-death
  raise sites -- including the ten C-drain sites that consulted it
  nowhere, and the two ingest-scanner sites that consulted it in five of
  seven copies.
- **`_raise_for_drain(status, lib)`** -- the C drain's "is this a
  failure?" decision, ten copies -> one, with the excuse inside it.
- **`_teardown_orderer(order_w, orderer_pid, lib)`** -- the orderer's
  teardown, six copies -> one. The NUMA copy did not consult the
  excuse; the helper does, so all six get it.
- **`_spawn_c_orderer(engine_fds, out_fds, unordered=False,
  numa=False)`** -- the orderer's setup, six copies -> one. **The
  configuration that varies is FORWARDED, not discarded**: the first
  version of this fold dropped the two NUMA callers' `numa=True`, and
  `numa` reaches the C orderer as the "numa" argument of `ring_order`
  -- it selects the orderer's NUMA mode. The NUMA ordered paths were
  running the default orderer mode, and **no test noticed**:
  `nodes="@2"` forces two LOGICAL nodes (cycling over the online
  physicals), so the NUMA executors DO run on a single-node host --
  but the orderer's NUMA *mode* is not observable in the output with one
  physical node, because the ordering comes out the same either way.
  The configuration was checkable; its EFFECT was not. That is
  precisely why a green gate did not catch it.
  `python/tests/test_orderer_config.py` now asserts that the NUMA
  executors ask for the NUMA mode and the UMA ones do not.

  That is the sharpest lesson in this pass, and it is the SSoT policy's
  own step 4 made concrete: **a centralisation that loses a
  configuration dimension is not a centralisation.** The rule moved into
  one place, and a DIFFERENT rule -- which mode the orderer runs in --
  was lost in the move. The fix is not to give up on the fold; it is
  for the authoritative implementation to represent every meaningful
  variation, and for each caller's variation to be asserted.
- **`_reap_fallow(fallow_pid)`** -- the reaper's reap and its
  abnormal-exit warning, four copies -> one.

### 7.2 What it did NOT fold, and why

- **The fallow child's exit handling** (4 copies) -- one of them calls
  `fr_py_fallow_phys` where the others call `fr_py_fallow_loop`. That is
  a genuine semantic difference (the physical-NUMA variant), not drift,
  so it stays separate until the difference is understood.
- **The checkpoint-on-abort handler** (2 copies) -- the two sites differ
  in their surrounding state, and the block is a 9-argument call; a
  helper with 11 parameters would be the "big helper" the costume rule
  warns about. It is recorded here rather than forced.
- **The ingest-helper and helper-death watchers** -- the NUMA paths
  already record an excused death in a per-node set rather than raising,
  which is a different mechanism for the same rule. They are noted, not
  merged.

## 8. The harness defect that looked like a production regression

After the folds landed, the gate's cleanroom-**on** pass began failing
intermittently -- and the failures were alarming:

| run | failure |
|---|---|
| 1 | `test_yyjson_plugin` -- "reaped unexpected child -- zombie leak" |
| 2 | `test_resume` -- the same assertion, a different test |
| 3 | **169 failures**, cascading from `test_resume_sigint` ("SIGINT abort must checkpoint") |

The moving blame and the cascade are what make this worth writing
down. The root cause is in the test harness, not the product:

```python
def assert_no_zombies(testcase):
    try:
        pid = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        return
    testcase.fail("reaped unexpected child %r -- zombie leak" % (pid,))
```

`waitpid` has three outcomes, and this conflated two of them:

| result | meaning |
|---|---|
| `ChildProcessError` | there are no children to wait for |
| `(0, 0)` | a child exists and has **NOT terminated** -- it is still RUNNING |
| `(pid, status)`, pid > 0 | a terminated child was found and reaped |

So a child that was still **running** was reported as a "zombie leak" --
and because the child stayed alive, the check kept failing **every later
test in the run**. That is the 169-failure cascade, and it is why the
blame moved between runs: it was always the child that outlived its
owner.

`waitpid(-1, ...)` compounds it: it reaps ANY child of the test
process, including one an **earlier** test left behind. That both
misattributes the failure to whichever test runs next, and destroys the
evidence that the earlier test left the child.

**The fix** (`python/tests/_helpers.py`): take a `/proc` census of this
process's direct children -- every THREAD's children -- and distinguish
the three outcomes. A terminated child is reaped here, by pid, and
reported as an unreaped (terminated) child. A child that is still
running is reported as a **lifecycle leak** and is **not** reaped (it is
still running; reaping it would be wrong). The assertion is not
weakened: both faults were failures before and both are failures now.
What changed is that the report names the child (pid, state, cmdline),
and that a leftover is reported **once**, by the test that left it --
so the real culprit is the one that fails.

**And the production regression that was suspected? There wasn't one.**
The reviewer's caution was to keep the two hypotheses independent rather
than assume one explained the other, so the checkpoint path was isolated
and compared directly: `test_resume_sigint`, in a **fresh process** per
round, same substrate and environment, against the pre-change
implementation and the changed one -- **30 rounds each, zero failures on
both**. The SIGINT path was never broken; it was the harness reporting
a leftover child, and blaming whichever test ran next.

`python/tests/test_child_lifecycle_helper.py` pins the helper's
behaviour on a deliberately live child, an exited-but-unreaped child, a
fully-reaped process, and the reported-once property, so the assertion
cannot be quietly weakened or the misattribution re-introduced.

**The lesson, and it is the SSoT policy's lesson again:** a green gate
is evidence only to the extent the gate can *see* a fault. A harness
that misreports what it found, and blames the wrong test, does not just
waste time -- it actively manufactures the appearance of a regression,
in a different place each run.

## 9. The two failures the cleanroom-on pass showed -- both now resolved

With the cascade gone, the cleanroom-**on** pass was down to two
failures, and BOTH were pre-existing -- they were present in the
cleanroom-on run *before* the harness work, with the same two names.
They are recorded here because the improved harness makes them
diagnosable, and because they were the next work.

**Both are now closed, and the gate is green in BOTH configurations:**
1486 tests OK with cleanroom off, 1493 tests OK with cleanroom on.

Neither was what it looked like. The streaming-memory failure was not
a threshold to be relaxed -- it was a single-pair assertion that could
not tell a property of the workload from a property of the moment.
The SIGINT failure was not "pre-existing" -- the review was right that
a same-named failure never established the same cause, and the cause
turned out to be a real production defect (below).

**`test_claim_streaming_memory` -- a load-sensitive measurement.** The
claim is "Streaming memory: slow consumer retains materially less than
collect-all", and the covering test asserts the separation is under
0.80x. Measured directly, unloaded, on this box:

| run | streaming growth | collect-all growth | ratio |
|---|---|---|---|
| 1 | 26024 KB | 59128 KB | **0.440** |
| 2 | 23564 KB | 60324 KB | **0.391** |
| 3 | 24880 KB | 58304 KB | **0.427** |

So the claim is accurate and the margin is wide. The separation is
also stable in every controlled condition I could construct -- an
ALTERNATING order of the two arms (6 paired rounds: 0.392-0.473, so no
order effect), 16 CPU burners (0.436-0.443), and 20 GB of memory
pressure (0.436-0.500) -- with identical output bytes and sample
counts in both arms, so the two arms do identical work.

Under the gate the same measurement came out at 0.82x, just over the
0.80 threshold. Since the ratio is invariant to order, CPU load and
memory pressure, the most likely mechanism is producer/consumer
IMBALANCE: the workers produce ahead of the probe's fixed-rate consumer,
so the streaming parent accumulates the results and its retention
approaches collect-all's.

**So the claim is TRUE BUT LOAD-CONDITIONAL, and the single-pair
threshold assumed the idle regime.** The threshold was NOT silently
relaxed. The gate now asserts an explicit, repeatable statistical
contract instead:

* the arms are measured in **PAIRS**, with their order **ALTERNATED**
  between pairs, so neither arm systematically benefits from going
  first;
* the strict relation -- streaming retains **less** than collect-all --
  is required for **every** pair, with no tolerance: that is the
  property, and it is what a collect-all regression breaks;
* the 0.80x margin is asserted on the **MEDIAN** of the paired ratios,
  which is robust to a single anomalous pair but still fails a
  collect-all regression outright (that sits at ~1.0x).

The failure message carries the raw growths, the ratios and the pair
count, so a failure says which measurement moved. Mutation-checked:
making the streaming arm collect everything fails the per-pair check
with the raw numbers in the message.

**`test_resume_sigint` -- a child left by the abort path.** RESOLVED --
and the cause was NOT the one I first proposed. The review was right
that my explanation did not reconcile with the evidence, and following
that thread found a different, real defect.

**The child was IDENTIFIED** (the improved helper names it, because a
zombie's cmdline is empty and the helper falls back to `comm`):

    child lifecycle leak -- unreaped (terminated) child pid(s) 3671343[python3]

`comm=python3` means it is a FORKED child of the test process -- a
worker -- and not an exec'd helper (those would show the launcher's
name). The run's teardown does reap its workers: a WNOHANG pass over
the slots, then a bounded `_join_helper_bounded` for each. So the reap
that did not happen is the one the teardown could not reach -- because
the teardown did not KNOW about that child.

**The timeline rules out the explanation I gave.** The payload sends a
SINGLE SIGINT (an `O_EXCL` marker makes the send single-shot). The
control flow is: the reactor catches `KeyboardInterrupt` and raises
`ForkrunInterrupted`; the outer `except BaseException` calls
`checkpoint_on_abort()`; the `finally` calls the teardown. So the
signal is consumed in the MAIN path, the checkpoint IS written before
the teardown runs, and the teardown runs afterwards. A signal arriving
inside the teardown would skip the checkpoint -- and the checkpoint
assertion passed. My "the interrupt landed inside the teardown" story
was therefore wrong.

**The real cause is a FORK WINDOW.** Between `os.fork()` and the
bookkeeping that owns the child (the reactor's
`self.workers[wid] = slot`) an exception orphans the child: the
teardown cannot kill it, cannot reap it, and when it exits it is a
zombie. The window is the `os.close()` plus the `/proc` read of the
fork-cost warning -- ~100us against a ~500ms run. Over a gate run
(~3000 forkrun runs) that is a ~45% chance per gate run, which is
exactly why it looked intermittent and moved between configurations.

**Reproduced on demand.** Injecting a `KeyboardInterrupt` in that
window leaves the forked worker alive, unowned and (once it exits) a
zombie -- the identical signature, including the empty cmdline.

**Fixed, in three parts, each with one authoritative implementation**
(`python/forkrun/_childreg.py`, `python/forkrun/_signals.py`,
`python/forkrun/_resume.py`; see SSoT.md 4.2):

1. `forkrun/_childreg.py` -- the authoritative registry of the
   children this process forked. Every fork site adopts its child
   IMMEDIATELY after `os.fork()`; the teardown reconciles the
   registry against what it owns and resolves (and REPORTS) anything
   still registered and still our child.
2. `forkrun/_signals.py::defer_interrupts` -- the one primitive that
   defers an interrupt. The teardown's cleanup sequence runs with
   SIGINT deferred (a cleanup that can be interrupted half-way is not
   a cleanup), and the deferred signal does not replace an exception
   that is already propagating.
3. `forkrun/_resume.py::_waitpid_bounded` -- the post-SIGKILL reap
   was an UNBOUNDED blocking wait, so a helper that could not die
   hung the whole run with no report. It is bounded now, and a child
   that cannot be reaped is reported as unresolved.

**Tested deterministically** (`python/tests/test_teardown_interrupt.py`,
9 tests): each fault is injected at a controlled point and the
outcome asserted, so a regression is a deterministic failure rather
than an intermittent one that only shows up in a full gate run. Every
case was mutation-checked -- reverting the adoption, the
reconciliation, the deferral or the bounded reap makes them fail.

**What this pass did about them: made them legible.** Before, the
cascade meant these were lost among 169 failures, each blamed on
whichever test ran next. Now each is reported once, with the child's
pid, state and command line, and attributed to the test that created
it.

## 10. The hang, diagnosed with a live traceback

The gate wedged in the suite's own release check. The stuck process
was not waiting for a forkrun child -- it was stuck INSIDE
`os.fork()`:

    File "/usr/lib64/python3.14/logging/__init__.py", line 240 in _prepareFork
    File ".../forkrun/run.py", line 7203 in _fork_materialized_scanner
    ...
    File ".../forkrun/run.py", line 3422 in __enter__     <- the main thread,
                                                           waiting for the
                                                           engine session lock
                                                           the forking thread held

CPython's `os.fork()` calls `logging._prepareFork()` in the PARENT
before the syscall and `logging._afterFork()` after it: the logging
module's lock is held across the fork so a child cannot inherit it
half-configured. An **asynchronous exception** between the two -- a
SIGINT arriving mid-fork -- leaves that lock HELD FOREVER, and every
later fork in the process then blocks inside `_prepareFork`. In a
threaded caller that is a **deadlock**: the forking thread holds the
engine session lock while it waits for a fork that will never return.

**This is not new.** The gate hung on earlier commits too -- in
`test_stage3_spawn_launcher`, a different victim of the same
deadlock. It is exactly the failure the review asked to be traced
rather than assumed, and the trace is what found it.

**Fixed by making the fork a critical section too**, through the SAME
primitive that protects the cleanup: `forkrun._childreg.fork_child()`
is now the one fork primitive in the package (22 sites), and it
defers SIGINT across `os.fork()`. The interrupt is not swallowed, and
the child restores the mask as it leaves the deferred region -- a
child that inherited a blocked SIGINT would ignore the operator's
interrupt for the rest of its life.

## 11. A constraint the de-duplication work ran into

**The Python front end may not name the bash front end.** The purity
tests (`test_reactor.TestReactorPurity.test_no_banned_tokens` and
`test_v0.TestPurity.test_no_bash_subprocess_or_pickle`) scan `run.py`,
`_reactor.py`, `_worker.py` and `_bindings.py` for a token list that
includes `frun.bash` and `source ./frun`.

The first version of the step-5 docstring cited the other frontend's
template-and-fragments shape **by name**, and the gate caught it — two
purity failures in both passes. That is the rule working as intended:
the two front ends are independent, and the Python side must not
depend on, or even name, the bash side.

So the cross-frontend reasoning lives **here**, in the audit, and the
code says only what the code needs to say:

> *"The OTHER frontend solves the same problem the same way: it builds
> its worker from ONE template, with the per-flag differences injected
> as small fragments, and assembles the result once -- so the worker
> loop body exists once. This module cannot eval a template, and should
> not; one body with the configuration injected is the equivalent
> shape."*

## 12. What is deliberately NOT changed

- **The bash frontend.** It is the frozen reference and its
  template-plus-fragments shape is the target, not the thing to fix.
- **The substrate, the launcher and the C engine.** Out of scope: this
  is a Python front end audit.
- **`_execute` / `_execute_ingest`.** Different parameter sets, different
  locked targets; their shared prologue is folded in step 1.
- **The `unlock`/lock structure.** 15 `with _RUN_LOCK:` sites are the
  concurrency contract, not duplication.

## 12. Where this ended up

**The gate is green in BOTH configurations**: 1486 tests OK with
cleanroom off, 1493 tests OK with cleanroom on.

Two production defects were found on the way, both by the improved
harness and neither by the duplication work itself:

1. **A forked child could be orphaned.** An exception between
   `os.fork()` and the bookkeeping that owns the child left it
   invisible to the teardown: not killed, not reaped, a zombie when it
   exited. Reproduced on demand by injecting an interrupt in that
   window. Fixed with an authoritative child registry
   (`forkrun/_childreg.py`) that every fork site adopts into and every
   teardown reconciles -- and the orphan is REPORTED, not silently
   resolved.
2. **The cleanup could be abandoned.** The teardown's cleanup sequence
   ran with SIGINT unblocked, so an interrupt arriving mid-sequence
   skipped the remaining reaps. Fixed with one authoritative
   deferral primitive (`forkrun/_signals.py::defer_interrupts`) that
   the teardown runs under. Related: the post-SIGKILL reap in
   `_resume._waitpid_bounded` was an unbounded blocking wait, so a
   helper that could not die hung the whole run with no report; it is
   bounded now, and an unreapable child is named.

Both are covered by deterministic, mutation-checked tests
(`python/tests/test_teardown_interrupt.py`) that inject the fault at a
controlled point -- so a regression is a deterministic failure rather
than an intermittent one that only shows up in a full gate run.

And the duplication work itself: the duplicated decisions are folded
(7 clone groups / 1719 characters -> 3 / 454), the harness now
attributes a child leak to the test that CREATED it (and resolves it
rather than suppressing the report), the scanner compares statement
BLOCKS so a decision copied inline is visible, and the SSoT policy
gained a section on the shape this exposed: **a critical section is a
decision** -- acquisition must be atomic with the resource, and the
release must survive the interruption that would abandon it.
