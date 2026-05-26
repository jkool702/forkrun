### `INVARIANTS.md`

# FORKRUN INVARIANTS

These are the rules that **must never be broken**. If they hold, the system is correct regardless of batching heuristics, NUMA count, or workload shape.

---

## 1. Slot Ownership & Monotonic Indices

**Invariant**  
Each ring slot is claimed exactly once, by at most one worker.

**Enforced by**  
`read_idx` advanced **only** via atomic `fetch_add`. No CAS retry loops on the fast path. No decrement or rollback logic anywhere.

**NUMA note**  
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

## 4. Signed Batch Size Protocol (Hysteresis & Fast-Path Routing)

**Meaning of Sign**  
* `batch_size < 0` → **Catch-Up / Speculative Mode**. The scanner has geometrically ramped the target batch size (≥ 2x). Workers must speculatively claim multiple older, smaller slots to quickly reach the new magnitude.
* `batch_size > 0` → **Steady-State / Fast-Path Mode**. The scanner is shrinking the batch size or making PID micro-adjustments (< 2x growth). Workers stay on the lock-free fast path and claim exactly 1 slot.

**Scanner Responsibilities**  
* May update batch size at any time.  
* Must publish a **negative** value (`-N`) ONLY if the new target is at least double the absolute value of the current batch size (`N >= 2 * current`).  
* Must publish a **positive** value (`+N`) for all other adjustments (shrinking, or growing by less than 2x). This introduces hysteresis, shielding workers from PID jitter.

**Worker Responsibilities**  
* Observe the published batch size.  
* If positive (`> 0`): Bypass all speculative arithmetic and claim exactly 1 ring slot.
* If negative (`< 0`): Enter the speculative slow path to calculate how many older slots satisfy the new magnitude. 
* Must use **CAS** to flip `-N → +N` (finalization) once their `read_idx` successfully crosses the `batch_change_idx` boundary where the new size was published. 

**Forbidden Transitions**  
* Worker changing the magnitude.  
* Any positive → negative transition initiated by a worker.  
* Non-CAS sign flip by workers (except during explicit Tail Override).

**Correctness Guarantee**  
Because a worker cannot claim "half a slot," forcing workers into speculative arithmetic when a batch shrinks or slightly grows is a waste of CPU cycles. The signed protocol mathematically guarantees that workers only pay the slow-path cost when a massive geometric ramp actually necessitates combining multiple slots.

---

## 5. Tail-Aware Batch Size Rules

**Definition**  
The tail ramp-down begins at `tail_idx` (EOF). Remaining data may not cleanly satisfy the current batch size.

**Scanner Responsibilities**  
* Must not publish batch sizes that correspond to tail batches.  
* When the tail is reached, the scanner must force the batch size to **positive** (`+N`) so that workers naturally downshift to claiming 1 slot at a time without overshooting.

**Worker Responsibilities at Tail**  
When `read_idx >= tail_idx` and `batch_size < 0` (e.g., catching a race condition before the scanner's EOF force-flip):  
1. Finalize immediately (`-N → +N` via CAS).  
2. Bypass all slow paths (no waiting, no escrow).  
3. Process exactly one claim using stride metadata.

**Why This Rule Exists**  
Guarantees exactly one claim per tail batch, prevents policy leakage, eliminates duplicate claims, and perfectly drains the ring without unnecessary escrow bouncing.

**Forbidden**  
* Scanner publishing batch changes after entering the tail.  
* Workers applying speculative multi-claim logic in the tail.

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

## 10. NUMA-Specific Invariants

* Data is born-local to its target node (`set_mempolicy` at ingest).  
* Scanner pinned to its node.  
* Per-node escrow pipes.  
* Major/minor ordering keys for correct global reorder.  
* Claim-pipe back-pressure prevents unbounded growth.

---

## 12. Meter-Based Early Flush Protocol

**Purpose**
When stdin is arriving slowly and workers are idle, the scanner may flush a partial batch early to reduce latency. This must not trigger spuriously or degrade throughput under normal load.

**The Two Meters**

| Meter | Signal | Grows when | Decays when |
|---|---|---|---|
| `stall_meter` | Input stall | Read returns no new data | Read returns new data |
| `starve_meter` | Worker starvation | `active_waiters > 0` | No workers waiting |

Both use the same EWMA kernel and threshold (`W + DAMPING_OFFSET - 3`).

**Invariant: Both meters must be saturated to trigger early flush.**

Neither meter alone is sufficient:

* `stall_meter` saturated, `starve_meter` not → no idle workers; no point flushing early
* `starve_meter` saturated, `stall_meter` not → data is available; flushing smaller batches increases scanner overhead and makes starvation worse
* Both saturated → sustained stall AND sustained starvation; early flush reduces latency at no throughput cost

**Invariant: Meters update at observation time, not flush time.**

`stall_meter` is updated when the stall is detected (read returns no new data). `starve_meter` is updated at the natural per-iteration or per-task observation point. Updating only at flush time would make the meters track flush frequency rather than system state, creating a circular dependency.

**Invariant: The stall signal is captured before flush, not re-evaluated at flush.**

The `experienced_stall` flag is set at stall detection, and cleared after it is consumed by `ADAPTIVE_FLOW_CONTROL`. This ensures the signal is correctly scoped to the interval between flushes, even if `status` has changed by the time the flush occurs.

**Invariant: `ADAPTIVE_FLOW_CONTROL` resets both meters to zero when it shrinks L.**

When sustained stall+starve causes a batch-size reduction, the meters are zeroed so the next growth cycle starts from a clean baseline. The meters are owned by the scanner; nothing else resets them.

**Audit Rule**
❌ Never trigger an early partial flush based on either meter alone, or on raw (unsmoothed) live reads of `active_waiters` or `status`.
❌ Never update meters inside `ADAPTIVE_FLOW_CONTROL` — they must be updated at their observation points so they reflect ongoing system state independently of flush frequency.

---

## 13. Checklist Summary

If all sections above remain true, **forkrun is correct** — regardless of:
* batching heuristics
* wake frequency
* NUMA placement
* worker churn
* input arrival rate (trickle or burst)

**Mental model reminder**  
Progress is irreversible. Locality is structural. Contention was designed away.

---

**See also:** `DESIGN.md` and `PHYSICS.md`
