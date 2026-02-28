### `INVARIANTS.md`

# FORKRUN INVARIANTS (v9.8.0-NUMA Golden Master)

These are the rules that **must never be broken**. If they hold, the system is correct regardless of batching heuristics, NUMA count, or workload shape.

---

## 1. Slot Ownership & Monotonic Indices

**Invariant**  
Each ring slot is claimed exactly once, by at most one worker.

**Enforced by**  
`read_idx` advanced **only** via atomic `fetch_add`. No CAS retry loops on the fast path. No decrement or rollback logic anywhere.

**v9 NUMA note**  
Each `SharedState` (one per node) maintains its own `read_idx` / `write_idx`.

**Audit Rule**  
✅ Any change introducing CAS retries, conditional claim rollback, or speculative reads of ring slots violates this invariant.

---

## 2. Publish-Before-Claim

**Invariant**  
Workers must never observe uninitialized slots.

**Enforced by**  
Scanner writes ring slot data **before** advancing `write_idx`. `write_idx` publish uses **release** semantics. Workers load with **acquire** semantics.

**Audit Rule**  
✅ Any reordering of slot writes, batch metadata writes, or `write_idx` publication must preserve release ordering.

---

## 3. Batch Atomicity

**Invariant**  
A batch is claimed whole or not at all.

**Enforced by**  
Workers claim ranges, never individual slots. Overshoot handled *after* claim, not during.

**Audit Rule**  
❌ Never introduce logic that conditionally claims per-slot or splits batch claim across multiple atomics.

---

## 4. Signed Batch Size Protocol

**Meaning of Sign**  
* `batch_size < 0` → **Provisional policy** (scanner may still change its mind)  
* `batch_size > 0` → **Finalized contract** (matches stream reality)

**Scanner Responsibilities**  
* May update batch size at any time.  
* Must **always** publish negative values (`-abs(N)`).  
* Must never publish a positive batch size.

**Worker Responsibilities**  
* Observe the published (negative) batch size.  
* May finalize **only** when stream count equals `abs(published_batch_size)`.  
* Must use **CAS** to flip `-N → +N`.  
* If CAS fails (scanner changed policy), re-evaluate under new policy.

**Forbidden Transitions**  
* Scanner publishing positive batch size  
* Worker changing magnitude  
* Any positive → negative transition  
* Non-CAS sign flip

**Correctness Guarantee**  
Batch size reflects scanner intent until finalized. Finalization occurs exactly once. Scanner policy changes cannot resurrect stale batch sizes.

---

## 5. Tail-Aware Batch Size Rules

**Definition**  
The tail ramp-down begins at `tail_idx`. Remaining data may not satisfy the current batch size.

**Scanner Responsibilities**  
* Must not publish batch sizes that correspond to tail batches.  
* Once `tail_idx` is established, scanner must not modify batch size.

**Worker Responsibilities at Tail**  
When `read_idx ≥ tail_idx` and `batch_size < 0`:  
1. Finalize immediately (`-N → +N` via CAS).  
2. Bypass all slow paths (no waiting, no escrow).  
3. Process exactly one claim using stride metadata.

**Why This Rule Exists**  
Guarantees exactly one claim per tail batch, no policy leakage, no duplicate claims.

**Forbidden**  
* Scanner publishing after entering tail  
* Workers applying ramp-down logic based on batch size  
* Slow path in tail

**Key Insight**  
Batch size is a *policy*, not a property of the tail. Once the tail begins, policy ends and structure takes over.

---

## 6. Escrow Correctness

**Invariant**  
Escrow is advisory and never required for forward progress.

**Enforced by**  
Escrow stealing is optional. Original worker may always reclaim remainder. Escrow full → self-complete.

**Audit Rule**  
✅ It must always be possible to ignore escrow entirely and still complete all work.

---

## 7. Waiter Accounting

**Invariant**  
Over-counting waiters is safe. Under-counting is forbidden.

**Enforced by**  
Increment before blocking + guaranteed decrement on *all* exits (including traps).

**Audit Rule**  
❌ Never add a wait path without paired increment and guaranteed decrement.

---

## 8. Eventfd Non-Reliance

**Invariant**  
Eventfds are advisory only.

**Enforced by**  
All correctness checks based on indices. Wakeups only gate sleeping, never claiming.

**Audit Rule**  
🚫 Never assume exact wake counts, wake ordering, or wake delivery.

---

## 9. Ordering & Emission

**Invariant**  
Logical indices define output order.

**Enforced by**  
Per-batch logical index + reorder buffer + emit only contiguous prefix.

**Audit Rule**  
❌ Never emit based on completion time.

---

## 10. NUMA-Specific Invariants (v9.8+)

* Data is born-local to its target node (`set_mempolicy` at ingest).  
* Scanner pinned to its node.  
* Per-node escrow pipes.  
* Major/minor ordering keys for correct global reorder.  
* Claim-pipe back-pressure prevents unbounded growth.

---

## 11. Checklist Summary

If all sections above remain true, **v9.8.0-NUMA is correct** — regardless of:
* batching heuristics
* wake frequency
* NUMA placement
* worker churn

**Mental model reminder**  
Progress is irreversible. Locality is structural. Contention was designed away.

---

**See also:** `DESIGN.md` and `PHYSICS.md`