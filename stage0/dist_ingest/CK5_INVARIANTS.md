# CK-5 invariants — experimental distributed-ingest engine

Codified invariants. **Actual checks + activation + failure semantics
match the executable.**

## Activation contract (one explicit, internally consistent contract)

`di_invariants_on(eng)` is the SINGLE activation decision:

```c
#if defined(DI_INVARIANT_ASSERT)
    return 1;                 /* compile-time mode FORCES checking ON */
#else
    return eng && eng->P.invariant_asserts;   /* runtime flag */
#endif
```

- **Runtime `P.invariant_asserts`** activates invariant checking in an
  ordinary build.
- A build compiled with **`-DDI_INVARIANT_ASSERT`** forces checking on,
  regardless of the runtime flag.
- **Both modes run the SAME underlying checks.** No unconditional
  `|| 1`, no compiled-out ordinary-build path. Post-join reconciliation
  applies to both modes. Off by default in performance-run builds.

Tests exercise BOTH activation paths (ordinary + `DI_INVARIANT_ASSERT`
build; runtime flag on/off).

## 8.1 Materialize-before-blocking invariant (CK-5.1 publication checker)

**Statement:** a producer must not block on publication admission while
holding a reservation whose data has not yet been materialized.
Claim → allocate → `di_pread_full` → `di_queue_push`; publication
admission only after the read has completed. `di_chunk_t.materialized`
is set to 1 only after `di_pread_full` returned exactly `len` bytes.

**`di_invariant_publish_check(n, c)`** runs **BEFORE the producer enters
or waits on publication admission** (before the `cv_can_push` wait) and
before any queue/accounting mutation; **caller holds `n->mu`; it does
NOT relock the mutex**; reads `n->outstanding` directly (not atomic).
Returns meaningful status **0 / -1; return value is propagated**.
Establishes + verifies, at minimum:

1. valid backing buffer — `c->buf` non-NULL; `c->map_base` non-NULL;
   `c->map_len>0`; `buf` inside `[map_base, map_base+map_len)`;
   `len <= remaining mapping`;
2. valid **nonzero** length `c->len > 0`;
3. materialization completed (`c->materialized`) before admission;
   `off + len` no overflow;
4. outstanding reservation/accounting valid for the chunk:
   `c->len <= n->outstanding`; accounting identity holds; no recorded
   accounting violation; `effective <= max_backlog` (overflow-safe);
5. on violation: **invalid chunk NOT published/committed** (no queue
   mutation; no accounting mutation); **reservation rollback** preserved
   (caller `di_outstanding_sub_locked`, rolls back; buffer ownership
   unchanged); **`di_engine_stop`** error/stop path; no deadlock;
   threads still joined.

**Ownership:** `di_queue_push` takes `di_chunk_t` by value; the checker
never frees; caller retains `map_base`. **Narrow test seam**
(`di_test_set_publish_seam`, modes null-buf/zero-len/unmaterialized)
corrupts a by-value copy for validation; the underlying allocation is
preserved and caller still owns/frees it; no test leak.

## 8.2 In-flight accounting invariant (CK-5.3)

```
effective_backlog = published_backlog + consumer_inflight_backlog + outstanding
```

**`outstanding` and `published_backlog` are protected by `n->mu`; NOT
atomic.** Accurate update points (caller holds `n->mu`):

- `outstanding`: += want at admission (overflow-checked; no silent
  saturation); -= delta when assigned<want; -= rollback on
  start-past-EOF / assigned==0 / alloc-fail / read-fail / short-read /
  push-fail; -= c.len when published; rolled back fully. **checked
  subtraction `di_outstanding_sub_locked`; underflow NOT silently
  clamped; records `n->accounting_violation`.**
- `published_backlog`: += len at publish (checked); -= len at pop
  (checked). `consumer_inflight_backlog`: += len at pop; -= len at
  consume-complete (checked). No `di_u64_add_sat` silent clamping on
  accounting-critical paths (advisory `di_effective_backlog` still
  saturates for headroom reads only).
- `max_*`, `n->m.*`, accounting read under `n->mu`.

**Invariant checks at safe synchronization boundaries**
(`di_accounting_check_locked`, caller holds `n->mu`; active when
`di_invariants_on`; same checks both modes; not atomic access):
identity holds; **overflow-safe arithmetic (__int128 accumulate)**; no
silent saturation/clamping; `effective <= max_backlog`; no recorded
violation. Checked at claim / publish(committed) / pop /
consume-complete / rollback / post-join. Admission `di_can_admit`
overflow-safe. Not silently clamping to make assertions pass.

**Post-join (CK-5.3, ALWAYS, after ALL worker threads joined; normal
completion AND injected-failure paths):** per node verify
`outstanding==0`, `published_backlog==0`, `consumer_inflight_backlog==0`,
no recorded accounting violation, accounting check. Verified reserved
bytes/outstanding reconciled. **Preserve original engine error** (rc
already set kept); **report additional accounting/invariant failure
accurately** (stderr + `di_result_t.invariant_failed` +
`di_result_t.accounting_failed` + node `accounting_violation`); rc set
`DI_ERR_INVARIANT` iff rc was clear.

## Failure semantics
- Invalid chunk → not published; reservation rolled back; ownership
  preserved; **explicit engine-level `invariant_failed`** (`_Atomic int`,
  set RELEASE on violation, read ACQUIRE post-join); `di_engine_stop`;
  threads joined; `di_result_t.invariant_failed=1`; **`di_run` returns
  `DI_ERR_INVARIANT` (-6) when no earlier engine error exists**; a
  generic `DI_ERR_STATE` stop mapping does NOT override the precise
  invariant reason; original error preserved. (P1 correction.)
- Accounting violation → recorded (not clamped); reported; rc.
- Normal completion → success `outstanding==0`.
- `DI_ERR_INVARIANT = -6`.

## 8.3 Relative-adaptive policy law (existing; documented by type)
`r = D_local / D̄_nonlocal`, integer quanta, rounding 0=floor/1=nearest/
2=ceil; tie tests in `test_dist_ingest.py`.

## 8.4 Claim/publication granularity (prototype vs intended)
Prototype: one claim = one buffer = one read = one queue entry.
Intended later: batch claims + per-chunk publication
(`DESIGN_NOTES_DEFERRED.md`).

## 8.5 DIST_RESULT classification
`DIST_RESULT` includes `comparability` + per-node CK-5/CK-6 fields
(`accounting_violation`, `accounting_failed`, `invariant_failed`).

## CK-2 fault-injection interaction
Invalid-publication, push-fail, pread, alloc, thread-create injected
faults all reconcile accounting + join (see LIVENESS.md, CK-2).

---
*WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-5).*
