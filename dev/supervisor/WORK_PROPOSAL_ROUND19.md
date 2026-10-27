# Work proposal — commit-scoped frame accounting, plus two hygiene items

Branch `NEW/REFACTOR4.2`, head `158e818a`. Ring still untouched.

Round 18 returned a **blocker**, not a plan revision: counting at
`fr_py_emit` counts *written* frames, and a written frame can be rolled
back before its batch commits. This proposes the commit-scoped design
that resolves it, and bundles two ring-free items already landed.

---

## 1. The blocker, restated with the engine's own terms

`forkrun_ring.c:7163`, `ring_revert_output`, Case 2b "THE ORPHAN":

```c
/* 1. Roll back partial output. ... */
(void)ftruncate(output_fd, (off_t)txn->output_start);
```

A batch that was **claimed but not ACKed** and whose worker died has its
output truncated, then retried. `_worker.py:427` names the ordering:
`_commit` is "Output + signal + ack" — the ack is the commit.

Measured on the current tree, not argued (`test_c07_fault_injection.py`):

| deaths | successful `fr_py_emit` calls | committed records |
| ------ | ----------------------------- | ----------------- |
| 1      | 2                             | 1                 |
| 3      | 4                             | 1                 |

The gap grows with deaths, so a constant calibration cannot absorb it.

---

## 2. Proposed design: pending-per-transaction, flushed at commit

The shared counter moves **only at the commit point**. Nothing increments
it while a transaction is merely live.

**a. TLS pending counter** (`_shim.c`, beside the existing
`static __thread int fr_py_txn_out_fd` at `:110`):

```c
static __thread uint64_t fr_py_txn_pending_data = 0;
```

TLS per worker, so concurrent workers never contend. Mirrors existing
per-worker txn state, so no new synchronization concept is introduced.

**b. DATA emitters increment the TLS pending count, not the shared
field.** Three call sites, all shim-internal:

- `fr_py_emit` — one DATA frame per call when `data != NULL`.
- `fr_py_emit_record_buf` — when `disposition == FR_DISP_DATA`.
- `fr_py_emit_record` — when `src_len > 0` (its capture-with-output case;
  `src_len == 0` yields NO_RESULT and must never count).

**c. Commit flushes it.** At `worker_txn_clear` (`_shim.c:3155`,
`worker_txn_clear -> TXN_IDLE`, the documented commit linearization
point):

```c
if (fr_py_txn_pending_data) {
    __atomic_fetch_add(&shared->committed_data_frames,
                       fr_py_txn_pending_data, __ATOMIC_RELAXED);
    fr_py_txn_pending_data = 0;
}
```

`__atomic_fetch_add`, not a store — multiple workers per node, as
round 17 required.

**d. Rollback discards it.** In `fr_py_recover_worker` (`:3529`), on the
**RECOVERED branch only** — the same branch that already re-syncs the
TLS output cursor:

```c
if (rc == 0 && output_fd >= 0) {
    (void)worker_txn_init_output_cursor(output_fd);
    fr_py_txn_pending_data = 0;   /* uncommitted: never counted */
}
```

Condition identical to the existing cursor resync, so the two cannot
disagree about whether a truncation happened.

**Why this is exactly-once.** The shared counter is touched on exactly
one path — commit. A rolled-back attempt leaves `pending` non-zero but
never added it; recovery clears it; the retry accumulates afresh and adds
once at ITS commit. Death between write and ack therefore contributes
zero, and the committed value is the only one that lands.

**What I think this gets right that the emit-count did not:** the count
is now defined against the commit point rather than the write, so it
cannot disagree with what the parent collects even across repeated
deaths.

---

## 3. Execution envelope — where I want to be challenged

Three questions, and I have an answer for each but would rather be told
I am wrong than agree later.

**3a. Python fallback is NOT covered, and must fail closed.**
`_worker.py:767` writes the frame with Python's `_write_all` when
`FORKRUN_NO_V1=1`, bypassing C entirely. A C counter cannot see it.
Proposal: when the selected worker path is the fallback, the certificate
reports **"envelope not covered"** and does not claim completeness. I
prefer fail-closed refusal over routing the count through ctypes, because
the fallback is a compatibility path and the whole point of the
certificate is to be trustworthy when it says OK.

**3b. `ring_ack_main` stays uninstrumented.** It is the non-Python worker
path. The Python certificate's envelope will say so explicitly rather
than leave it implicit.

**3c. `fr_py_emit_record`'s NO_RESULT records are load-bearing, not
noise.** Per the investigation (below) they are the terminal record that
stops an ordered consumer waiting forever on a completed-but-silent
batch. They must never count toward completeness, and the filter in the
parent is what enforces that.

---

## 4. `fr_py_emit_record` investigation — the question round 18 asked

**Answer: no defect, no behaviour change.** It is `static`, with exactly
two callers, both **stdout-capture** paths. For a spawned child, "wrote
nothing to stdout" and "produced no result" genuinely coincide. Both call
sites say why the record matters:

> "cap_len == 0 is a real completed batch with no output, and it gets a
> NO_RESULT terminal record — without one, an ordered consumer waits
> forever on a batch that has finished."

UDF results deliberately bypass it: `fr_py_emit_record_buf` takes an
explicit disposition from the helper's return code, because inferring
from length is the conflation DECISION-02 exists to remove.

The only real defect was the **comment**, whose final clause reads as if
this function emits empty DATA frames. It cannot — it has nothing to
infer from. Fixed comment-only.

---

## 5. Bundled and already landed (`158e818a`)

**5a. Test suite no longer depends on CWD.** `test_cleanroom.py` used a
repo-root-relative `"python/tests/plugins/..."` in two places, so running
from `python/` gave two spurious ERRORs. I hit this twice and
misdiagnosed it as a product regression both times. Now built from the
absolute `PLUGINS_DIR`; verified 1069 tests identical from both
directories.

**5b. All eight helper symbols are ownership-checked.**
`forkrun_cleanroom.c` resolved seven `fr_udf_*` symbols plus
`fr_udf_last_error` through bare `sym()` (dlsym) while `sym_owned_by()`
existed and was used only for the version stamp. All eight now go through
`sym_owned_by`. Signatures unchanged; exposure was a dependency exporting
a same-named symbol, and the helper is hand-buildable.

**Left alone deliberately:** the `fr_py_*` substrate symbols at `:1732+`
still use `sym()`. Same class, different family — its own change rather
than widening this one.

---

## 6. What I would do next, pending approval

1. TLS pending counter + the three emitter increments.
2. Commit flush at `worker_txn_clear`; rollback discard in
   `fr_py_recover_worker`.
3. One `SharedState` field at the **end** of the struct — still the only
   ring change, now holding *committed* frames.
4. Quiescence-gated shim accessor; wire the certificate.
5. Extend the harness I already built: assert the counter reads **1** for
   the 1-death and 3-death cases, where today it would read 2 and 4.
6. Negative control: assert fail-closed on the Python fallback path.

Then, and only then, the `frun.bash` base64 blob regeneration via CI
branch/PR, `UNIT_TESTS/test_frun.sh`, and the Bash benchmark.

## Not asking about

NUMA stays opt-in until the certificate passes its gates and real
multi-socket validation exists. Round 18's Q1/Q2 remain open; this
proposal does not presume their answers beyond §3.