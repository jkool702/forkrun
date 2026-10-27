# Stage 0–3 as-built — review request

Branch `NEW/REFACTOR4.2`, head **`3eff9218`**. Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across the whole range `c72d27c6..HEAD`.

**938 tests, 1 expected failure, 0 unexpected failures.**
`python/release_check.py` → `ALL CHECKS PASSED` on a clean tree.

---

## 1. What to review, in priority order

| # | commit | what |
|---|---|---|
| 1 | **`3eff9218`** | spawn served by the launcher; **lifecycle gates exposed a supervision gap** (§4) |
| 2 | `1b95f6a8` | Stage 3 plumbing: worker descriptor, argv transport, process groups |
| 3 | `4228b6b7` | Stage 1: terminal-aware parsing and reassembly |
| 4 | `0edd7475` | your round-5 items, all three (§2) |
| 5 | `a8ca3697` | Python `_HDR.size` frontier fix; fail-closed synthetic wakeup |

Reproduce:

```
make -f Makefile.substrate python-substrate
cd python/tests
python3 -m unittest test_stage3_lifecycle test_stage3_spawn_launcher
python3 -m unittest test_stage1_reassembly
python3 -m unittest test_stage0_publication test_stage0_matrix \
  test_stage0_public_api test_stage0_notify_failure
python3 -m unittest discover -s . -p "test_*.py"    # ~260s
```

---

## 2. Your round-5 items — all three closed

**Partial-record cleanup.** Your finding was right and the fix is
narrower than the bug: `_rollback_partial_record()` raises
`_UnrecoverableOutput` when the boundary was never established or the
truncation itself fails, and the failure path intercepts it **before**
the `on_error` ladder and exits the worker, handing the decision to
parent-side recovery. The bare `except Exception: pass` around the
frontier advance is gone for the same reason.

**The `None` claim.** You were right and I was wrong. The block is
guarded by `if blob is not None`, so `len(None)` was unreachable. The
real defect was and remains the 8-byte undercount. The expression is now
plain `len(blob)`, and the correction is recorded in the test docstring
and commit message rather than left standing.

**Test scope.** Stated accurately: `FORKRUN_TEST_BREAK_DRAIN_WAKEUP`
sets `spare_sig = -1`, so that test exercises the helper's
invalid-descriptor rejection, not a real `EPIPE`.

---

## 3. Stage 1 — terminal-aware reassembly (`4228b6b7`)

`add_disposition(batch_idx, disposition, payload)`: all four dispositions
advance the contiguous prefix; only `DATA` yields. `drain()` walks
terminal markers as well as payloads, so a terminal batch no longer
strands everything behind it — promptly, not at finalisation.
`unresolved_gaps(upto)` reports uncovered indices.

`run._split_records_terminal()` is a **separate** parser.
`_split_records()` is deliberately left filtering control records, because
its callers must not receive a spurious `b""` for a batch that produced
nothing. Both are pinned so a future "unification" breaks loudly.

**Producer coverage is not uniform**, and the unresolved-gap check is
only meaningful where terminal records actually exist:

| producer | terminal dispositions |
|---|---|
| plugin / udf / spawn loops | `SKIPPED`, `POISONED` |
| splice loop | `POISONED` only (no `on_error=skip` arm) |

The contract is asserted **against the source**, not a table — two earlier
audits were wrong exactly that way. Writing the test immediately caught
that splice's `DATA` disposition *is* set inline, which my expected set
had omitted.

**No eligibility changed.** `stream(order="index")` remains declined,
pinned by a test that matches the actual `if streaming: if order !=
"none": return False` structure rather than a keyword a comment could
satisfy.

---

## 4. Stage 3 — and the finding that matters (`3eff9218`)

Spawn now runs end-to-end through the launcher: `tr a-z A-Z` yields one
DATA record per batch. Two bugs surfaced en route — the plugin
capability probe was guarded on "not a UDF", so a spawn invocation fell
through into `dlopen(NULL)`; and my argv collector never
NULL-terminated, which its own validator requires.

**The lifecycle gates are where I need you to look.**

Two of three hold:

* the **escaping-descendant boundary** passes — a child that `setsid()`s
  away survives, exactly as Option A promises, so the limit is now
  pinned by a test rather than asserted in a comment;
* a **sanity test** confirms the mode is genuinely served, so the others
  cannot pass on a path that never ran.

The third fails, and **not because of the process group**:

> Killing a worker that is blocked mid-batch produces **no respawn at
> all** across a 5-second observation window. The launcher never reaches
> the code that would signal the group.

Group-kill is wired into both the supervision and fail-fast paths — and
neither is entered. The orphan is unreachable until something notices
the death, and nothing does.

This is larger than the risk item 4 anticipated. The design worried that
"a SIGKILLed worker orphans its child"; the finding is that such a worker
may not be **observed as having died at all**. No amount of process-group
work fixes that alone, and I would expect it to affect the plugin and
UDF modes too, not just spawn — which is why the envelope stays declined
and the test is `expectedFailure`.

**Questions I'd like answered:**

1. Is the supervision gap a real defect, or an artefact of my test
   (e.g. a run phase where the launcher is legitimately not polling)?
2. If real, is it scoped to mid-batch worker death, or does it also
   affect death during ingestion/scanner phases?
3. Does it need a supervisor redesign (poll throughout), or can the
   existing loop be reached earlier?

---

## 5. Test-scope caveats I am not papering over

Three places where a green check means less than it appears to. Please
push on any of these:

1. **`test_stage0_spawn_frontier.py` does not observe the frontier.**
   `worker_output_end` is worker-local TLS with no accessor, and I
   verified by reverting the fix that these tests still pass. The
   guarantee rests on the advance being *centralised in the framer* plus
   the launcher-backed suites that do observe rollback. A true
   end-to-end spawn-rollback test needs the C spawn loop under
   supervision with a real drain; the launcher serves plugin and UDF
   only.

2. **The unordered Python-fallback test is gated and skipped.** A direct
   python-mode `map()` invocation poisons every batch in this environment
   for reasons unrelated to the frontier — it reproduces identically
   with the fix reverted. What is asserted unconditionally is the defect
   itself: the advance is derived from `_HDR.size` and the stale literal
   is gone.

3. **`FORKRUN_TEST_NOTIFY_FAIL_ONCE` returns before attempting the
   write.** The separate real-write test closes the worker's own signal
   fd so a genuine `EBADF` occurs, but `out_fd < 0` and `lseek` failure
   are not driven through a live launcher.

---

## 6. Two mistakes worth your attention

Both mine, both caught by tests within minutes, both the shape a green
suite hides — recorded because they may recur in review:

* A local `spawn_argv = None` in `map()` **shadowed** a new parameter of
  the same name, breaking every cleanroom call with `UnboundLocalError`.
  The follow-on was worse: a blind `sed` rename left a stale reference,
  and because the suite was already red, the real signal was buried among
  34 unrelated-looking errors.
* I concluded that fail-closed-on-wakeup "aborts legitimate runs" and
  **reverted a correct fix** on that basis. The failures were a cwd
  artefact (plugin fixtures resolved from the wrong directory) plus a
  stale build. Had I shipped the revert, a real completeness hole would
  have stayed open behind a "known limitation" note.

Also: I ran the suite with `timeout 3000`, which is fifty minutes. A
deadlock sits there looking like progress; the suite takes ~260s, so
anything past a few minutes is a real stall.

---

## 7. Not done

* **Stage 2** (bounded/live ordered streaming) — untouched; the decline
  stands and its design note is unopened.
* **Stage 4** (splice measurement) — not started. The circularity concern
  stands: measuring cleanroom splice requires wiring it first.
* **Stage 5** (`auto`/`off`/`required`) — untouched; `Auto` remains off.
* Items **3** (`mode="python"` parity), **6** (NUMA) and **7** (resume)
  remain deferred future work orders, not cancelled.

## 8. Design documents

* `dev/supervisor/CLEANROOM_EXPANSION_PROPOSAL.md` — roadmap, §0a the
  defect
* `dev/supervisor/STAGE0_PUBLICATION_PROTOCOL.md` — §8a Stage 1,
  §8b Stage 3, §9 as-built, §9.3a why fail-closed is safe
