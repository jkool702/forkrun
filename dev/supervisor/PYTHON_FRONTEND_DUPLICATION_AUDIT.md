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

### 2.8 The fork-timing rule — 3 closures

`_maybe_fork_workers` at 6773, 7301 and 10356 implement the same
fork-timing rule (first data publish, or the stall timeout pre-gate),
capturing different state (`state`/`gate` dicts in two, plain locals in
one) and calling differently-named fork functions.

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
| 5 | `_splice_stream_gen(..., executor=)` + one call site | 4 → 1 | med | pending |
| 6 | the stream-generator family, one executor parameter | 4 → 2 | med | pending |
| 7 | `_watch_scanner` | 2 → 1 | med | pending |
| 8 | `_maybe_fork_workers` | 3 → 1 | med-high | pending |

**Steps 1–4 are pure mechanical folds**: one implementation, the
variation becomes a parameter, and every call site keeps its current
meaning. The docstrings, which carry the measured evidence for each
decision, are **kept** — they move to the shared helper rather than
being deleted.

**Steps 5–8 touch the hot paths.** They are worth doing, but they are
where the duplication is *load-bearing* (the fork-timing rule and the
scanner watcher are per-executor closures over per-executor state), so
they go last and one at a time.

### 3.1 What steps 1–4 did and did not change

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


## 4. What is deliberately NOT changed

- **The bash frontend.** It is the frozen reference and its
  template-plus-fragments shape is the target, not the thing to fix.
- **The substrate, the launcher and the C engine.** Out of scope: this
  is a Python front end audit.
- **`_execute` / `_execute_ingest`.** Different parameter sets, different
  locked targets; their shared prologue is folded in step 1.
- **The `unlock`/lock structure.** 15 `with _RUN_LOCK:` sites are the
  concurrency contract, not duplication.
