# Review request — C0.7 certificate, wired

Branch `NEW/REFACTOR4.2`, head `3e461fb3`. Round 19's two required
amendments are implemented, both sides of the gate are proven, and the
certificate is **wired and live**.

This is a review of landed, working code rather than a proposal, so you
can react to the implementation rather than to my reasoning about it.

---

## 1. Amendment 1 — the commit sequence

The flush sits in `fr_py_ack_core` after every ack side effect has
succeeded and **immediately before** `worker_txn_clear()` publishes
`TXN_IDLE`:

```c
if (fr_py_txn_pending_data) {
    uint32_t _sn = ...;
    if (_sn < global_num_nodes)
        __atomic_fetch_add(&state[_sn].committed_data_frames,
                           fr_py_txn_pending_data, __ATOMIC_RELAXED);
    fr_py_txn_pending_data = 0;
}
worker_txn_clear(g_fr_config.ring_wid);
```

The comment at that site states the reasoning in both directions: a
death in the gap leaves an ambiguous commit that the engine fails rather
than recovers, which is correct; flushing *after* the IDLE store would
let a death undercount committed output, which is the silent false
success this counter exists to prevent.

Emitters that bump the TLS pending count: `fr_py_emit` (`data != NULL`),
`fr_py_emit_record` (`src_len > 0`), `fr_py_emit_record_buf`
(`disposition == FR_DISP_DATA`). The splice inline `sendfile` path is
deliberately **not** instrumented, because the envelope refuses splice
rather than pretending to count it.

Rollback discards pending in `fr_py_recover_worker`, on the RECOVERED
branch only, under the identical condition as the existing TLS cursor
resync.

## 2. Amendment 2 — the envelope, enforced

`_c07_envelope()` returns False for splice mode, for the Python
`_write_all` fallback, and when `fr_py_ack_direct` is absent (which
*determines* that `_ack()` falls back to `ring_ack_main`). `_c07_evaluate`
warns and returns — it emits **no verdict**, never a passing one. Each
branch names its own cause, asserted to be three distinct strings.

## 3. What the first wiring attempt taught me

I wired it once and reverted, because it failed three ways, each
killing a different scoping strategy. This is the part most worth your
attention, because my first two answers were both wrong:

| failure | measured | why my first fix was insufficient |
|---|---|---|
| module-global accumulation | `collected 282, published 26` | reset per collection — but only fixed *this* shape |
| resume sidecar merge | `collected 40, published 33` | snapshot before the merge — but sidecar frames were committed by *earlier* runs |
| nested `map()` on a shared engine | `collected 24, published 56` | **no observed-side fix can work** — the expected side is cumulative |

The third is the real design constraint. The committed counter belongs to
the **engine**, not to a run, so the fix had to move to the expected
side: capture `_c07_base` after engine init and **before any fork**, and
compare the delta. It is a per-run local on purpose — a module global
*is* the bug, since that is exactly where a nested run would read its
parent's count.

Observed side is `len(records)` from `_iter_records`, which delegates to
`_split_records_views` and therefore yields DATA frames only. Not
`_FRAME_STATS`, which is a module global.

## 4. Proof

**Both sides**, as required:

- *Recovered runs count exactly what was committed* —
  `test_dead_worker_pending_is_destroyed_with_the_process` forks a real
  worker child that writes a DATA frame and `os._exit()`s before the
  ack. Asserts 0 while uncommitted, then exactly 1 after recovery and
  retry. Not 0, not 2.
- *A dropped committed DATA frame fails the certificate* —
  `test_c07_certificate.py`, plus the control that matching counts do
  **not** trip, since otherwise "always raises" satisfies everything.

**Mutation-proven against the original bug.** Reverting `fr_py_emit` to
count at write time (round 18's rejected design) turns the suite red in
three places. Removing the run-scoping baseline turns it red again
(`collected 25, published 50`). Both mutations are the specific mistakes
this work item exists to prevent.

**A real defect surfaced.** `fr_py_txn_pending_data` was thread-local and
survived fork, but `fr_py_init` never reset it — so a fresh generation
could inherit and commit a phantom count. This is the W-PY28 hazard
applied to the counter. It appeared only as an *ordering-dependent*
failure (passed alone, failed after another test), so it is now pinned by
a test that fails without the fix. My first mutation attempt there was a
silent no-op and the test looked vacuous until I targeted the line
directly.

**Sweep:** 24/24 line configurations match exactly across UMA, `@2`, `@4`,
1/2/4 workers, 3 batch sizes. Previously every NUMA configuration was
short by exactly 1 (the EOF sentinel). The 24 RAISEs are bytes-mode
configs that poisoned before this work too; unrelated.

## 5. A defect I introduced and reverted

My first perf comparison ran against `git stash` on an already-clean
tree, so both sides were the same build. Caught by noticing the delta
was implausibly small, then redoing it against a real checkout.

## 6. Contention, measured not assumed

Ordered path, `lines=64`, 200k lines, best-of-3, against the commit
immediately before C0.7:

| workers | pre (rec/s) | post (rec/s) | delta |
|---|---|---|---|
| 1 | 55,765 | 64,822 | +16.2% |
| 2 | 98,312 | 95,449 | −2.9% |
| 4 | 116,891 | 117,686 | +0.7% |
| 8 | 111,114 | 121,268 | +9.1% |

The deltas are incoherent, so they are variance. Had contention bitten,
the high-worker cases would degrade *consistently*; at 8 workers, where
it should be worst, the counter build measured 9% **faster**. Honest
reading: **below the noise floor, not free.** Resolving it properly needs
a tighter loop, more trials, and pinning.

## 7. Open questions for you

1. **Is the delta baseline the right shape, or should the counter be
   reset at run start instead?** A reset would need a new write-side
   export (ABI 55 → 56); the delta needs none. I chose the delta to avoid
   growing the ABI surface, but a reset is arguably more obviously
   correct.
2. **Is refusing splice acceptable indefinitely**, or does splice need
   coverage eventually? Its inline `sendfile` path could be instrumented,
   but it would need a commit flush on a different route.
3. **Is "below the noise floor" sufficient for the performance gate**, or
   do you want the tighter measurement before this is enabled?

## State

`frun.bash`'s embedded blob was regenerated by CI and merged (#584); I
confirmed my local toolchain cannot reproduce it, so that gate is
CI-only for me. 1092 tests, 0 regressions, release gate green.