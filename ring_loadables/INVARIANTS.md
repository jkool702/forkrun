FORKRUN INVARIENTS

---

## 1. Slot Ownership & Monotonic Indices

### Invariant

> Each ring slot is claimed exactly once, by at most one worker.

### Enforced by

* `read_idx` advanced **only** via atomic `fetch_add`
* No CAS retry loops on the fast path
* No decrement or rollback logic anywhere

### v9 Code Paths

* Worker claim path:

  * `atomic_fetch_add(read_idx, batch_size)`
* No other code path mutates `read_idx`

### Audit Rule

✅ Any change introducing:

* CAS retries
* conditional claim rollback
* speculative reads of ring slots
  **violates this invariant**

---

## 2. Publish-Before-Claim

### Invariant

> Workers must never observe uninitialized slots.

### Enforced by

* Scanner writes ring slot data **before** advancing `write_idx`
* `write_idx` publish uses **release semantics**
* Workers load `write_idx` with **acquire semantics**

### v9 Code Paths

* Scanner:

  * write slot(s)
  * store batch metadata
  * `atomic_store_release(write_idx)`
* Worker:

  * `atomic_load_acquire(write_idx)`
  * bounds check before read

### Audit Rule

✅ Any reordering of:

* slot writes
* batch metadata writes
* `write_idx` publication
  must preserve release ordering

---

## 3. Batch Atomicity

### Invariant

> A batch is claimed whole or not at all.

### Enforced by

* Workers claim ranges, never individual slots
* No mid-batch visibility checks
* Overshoot handled *after* claim, not during

### v9 Code Paths

* Worker claim:

  * single atomic claim of `batch_size`
* Overshoot logic:

  * executes available subset
  * remainder deferred via escrow

### Audit Rule

❌ Never introduce logic that:

* conditionally claims per-slot
* splits batch claim across multiple atomics


---

### 4. Signed Batch Size Protocol 

#### Meaning of Sign

* `batch_size < 0`
  → **Provisional policy**
  The scanner may continue to change the batch size.

* `batch_size > 0`
  → **Finalized contract**
  The batch size is now fixed and must match stream reality.

---

#### Scanner Responsibilities

* The scanner **may update the batch size at any time**.

* Every scanner publication of batch size **must be negative**:

  ```
  published_batch_size = -abs(actual_batch_size)
  ```

* The scanner **must never publish a positive batch size**.

* The scanner does **not** finalize batches.

The scanner expresses *intent*, not commitment.

---

#### Worker Responsibilities

* Workers observe the published (negative) batch size.

* A worker may finalize a batch **only when**:

  * The number of slots in the stream equals `abs(published_batch_size)`
  * The worker has reached the corresponding position in the claim stream

* Finalization is performed by flipping the sign:

  ```
  -N → +N
  ```

* Workers **must use CAS** when performing this update.

---

#### CAS Requirement (Critical)

CAS is required **not** to prevent races with other workers, but to detect races with the scanner.

Specifically:

* If the CAS succeeds:

  * The batch size observed by the worker is still current
  * Finalization is valid

* If the CAS fails:

  * The scanner has changed batch size again
  * The worker **must not** finalize
  * The worker must re-evaluate under the new policy

This guarantees that **no worker ever finalizes a stale batch size**.

---

#### Forbidden Transitions

The following transitions are illegal:

* Scanner publishing a positive batch size
* Worker changing the magnitude of batch size
* Any positive → negative transition
* Any non-CAS sign flip

---

#### Correctness Guarantee

This protocol guarantees:

* Batch size reflects scanner intent until finalized
* Finalization occurs **exactly once**
* Finalization corresponds to actual stream structure
* Scanner policy changes cannot resurrect stale batch sizes
* Workers never commit to an outdated policy

Performance may vary.
Correctness does not.


## Batch size protocol summary (pre-tail)

* The **scanner is allowed to change the batch size at any time**
* Whenever the scanner publishes a batch size, it **must publish it as negative**
* The **magnitude** reflects the scanner’s *current intended batch size*
* A batch size being **negative means “policy still in flux”**
* A batch size being **positive means “this size is now final and binding”**
* **Only workers** may flip a batch size from negative → positive
* Workers must do so **only when stream reality matches policy**
* Workers **must use CAS**, not to race other workers, but to protect against racing the scanner changing batch size again

---

## 5. Tail-Aware Batch Size Rules

### Definition: Tail Ramp-Down

The **tail ramp-down** is the region of the stream beginning at `tail_idx`, where:

* The scanner no longer guarantees full batches
* Remaining data may not satisfy the current batch size
* Partial records may exist

Slots at or beyond `tail_idx` are **structurally different** from normal batches.

---

## Scanner Responsibilities (Tail Boundary)

The scanner **must not publish batch sizes that correspond to tail ramp-down batches**.

Specifically:

* The **final published batch size** must correspond to:

  * the **last full batch entirely before `tail_idx`**
* Once `tail_idx` is established:

  * The scanner **must not** publish new batch sizes
  * The scanner **must not** modify batch size magnitude
* All tail batches are implicitly **policy-frozen**

The scanner’s responsibility ends at defining the boundary.

---

## Representation of Tail Batches

For batches at or beyond `tail_idx`:

* The scanner writes ring entries with:

  * **sign bit set** in the first offset

    * indicating: *“partial batch — consult stride ring”*
* No batch size policy applies
* The true batch size must be derived from:

  * stride metadata
  * or actual observed offsets

These batches are structurally self-describing.

---

## Worker Responsibilities at the Tail

When a worker observes:

```
published_batch_size < 0
AND
read_idx >= tail_idx
```

the worker **must**:

1. **Finalize the batch size immediately**

   * Flip the published batch size from negative → positive
   * This must be done using CAS

2. **Bypass all slow paths**

   * No waiting
   * No escrow
   * No speculative aggregation

3. **Process exactly one claim for this batch**

   * Derive the true record count from stride metadata
   * Treat the batch as final and immutable

---

## Why This Rule Exists (Correctness)

This rule guarantees all of the following:

* **Exactly one claim per tail batch**
* No worker ever waits on tail availability
* No batch size policy leaks into the tail
* No worker attempts to aggregate partial data
* No scanner/worker race can produce duplicate tail claims

The CAS sign flip here serves a **serialization role**, not a contention role:
it ensures only one worker finalizes the tail transition.

---

## Forbidden Tail Behaviors

The following are illegal:

* Scanner publishing batch sizes after entering the tail
* Workers applying ramp-down logic based on batch size
* Workers taking slow paths when `read_idx >= tail_idx`
* Aggregating tail batches as if they were full

---

## Combined Guarantee

With these rules enforced:

* All **pre-tail batches** obey batch size policy
* All **tail batches** are single-claim, self-describing
* No partial batch is ever processed twice
* No batch size ambiguity exists at EOF

The tail is **not a degenerate case** — it is a formally distinct phase.

---

## Key Insight 

> Batch size is a **policy**, not a property of the tail.
> Once the tail begins, policy ends and structure takes over.

---

## 6. Escrow Correctness

### Invariant

> Escrow is advisory and never required for forward progress.

### Enforced by

* Escrow stealing is optional
* Original worker may always reclaim remainder
* Escrow full → self-complete

### v9 Code Paths

* Overshoot publish
* Escrow steal attempt
* Fallback path

### Audit Rule

✅ It must always be possible to:

* ignore escrow entirely
* still complete all work

---

## 7. Waiter Accounting

### Invariant

> Over-counting waiters is safe. Under-counting is forbidden.

### Enforced by

* Increment before blocking
* Decrement via guaranteed cleanup
* Exit-trap based recovery

### v9 Code Paths

* Worker wait entry
* Exit / RETURN trap builtin

### Audit Rule

❌ Never add a wait path without:

* paired increment
* guaranteed decrement on *all* exits

---

## 8. Eventfd Non-Reliance

### Invariant

> Eventfds are advisory only.

### Enforced by

* All correctness checks based on indices
* Wakeups only gate sleeping, never claiming

### v9 Code Paths

* Worker sleep loop
* Scanner wake logic

### Audit Rule

🚫 Never assume:

* exact wake counts
* wake ordering
* wake delivery

---

## 9. Ordering & Emission

### Invariant

> Logical indices define output order.

### Enforced by

* Per-batch logical index
* Reorder buffer
* Emit only contiguous prefix

### v9 Code Paths

* Worker completion publish
* Aggregator emission loop

### Audit Rule

❌ Never emit based on completion time

---

## Checklist Summary

If all sections above remain true, **v9 is correct** — regardless of:

* batching heuristics
* wake frequency
* NUMA placement
* worker churn

---

# 2. “Why This Works” README (Outsider-Facing)

This is the document that lets smart people *get it* without watering it down.

You can use this as `README.md` or `WHY_IT_WORKS.md`.

---

## Why forkrun Works (Without Locks, Polling, or Luck)

forkrun is a streaming parallel execution engine designed around one principle:

> **Correctness comes from monotonic progress, not synchronization.**

Most parallel systems rely on:

* locks
* condition variables
* global coordination
* polling loops

forkrun deliberately avoids all of these on the fast path.

---

## The Core Insight

Instead of asking:

> “Is it safe to do this now?”

forkrun asks:

> “Has progress advanced far enough that this must already be safe?”

That shift enables a radically simpler design.

---

## Monotonic Indices Replace Locks

forkrun has only two global facts that matter:

* `write_idx` — how much work exists
* `read_idx` — how much work has been claimed

Both:

* only move forward
* never roll back
* are updated atomically

If `read_idx < write_idx`, work exists.
If not, it doesn’t.

No locks are needed to protect that truth.

---

## Why Workers Don’t Coordinate

Workers never talk to each other.

They:

1. Atomically claim a range
2. Process it
3. Publish results

If a worker is slow, fast workers simply claim more work.
If a worker disappears, its unfinished work is abandoned — but progress continues.

This is intentional.

---

## Why Eventfds Don’t Affect Correctness

Eventfds are used only to answer:

> “Should I sleep or check again?”

They are *never* used to answer:

> “Is work available?”

That question is answered solely by monotonic indices.

This means:

* missed wakeups are harmless
* spurious wakeups are harmless
* wake ordering does not matter

---

## Overshoot Is a Feature, Not a Bug

forkrun allows workers to optimistically claim more work than currently exists.

Why?

Because blocking *before* claiming work creates contention.
Blocking *after* claiming work does not.

If a worker overshoots:

* it processes what exists
* defers the rest via escrow
* or finishes it later itself

Correctness is never at risk.

---

## Why Partial Records Never Leak

The scanner explicitly marks incomplete boundaries using `tail_idx`.

Workers are forbidden from aggregating data beyond that point.

This ensures:

* no partial lines
* no split records
* no EOF ambiguity

Even under extreme interleaving.

---

## Why Performance Scales

The fast path:

* is O(1)
* contains no syscalls
* contains no branches dependent on other workers
* contains no shared locks

Contention simply does not exist where throughput matters.

---

## What Can Change Without Breaking Correctness

You may freely change:

* batching heuristics
* ramp-up logic
* wake strategies
* NUMA placement
* worker counts

As long as:

* monotonic indices remain monotonic
* publish-before-claim holds
* tail rules are respected

---

## What Must Never Change

If any of the following break, correctness breaks:

* Slots claimed more than once
* `read_idx` or `write_idx` going backward
* Workers observing uninitialized slots
* Aggregating beyond `tail_idx`
* Depending on eventfds for correctness

Everything else is negotiable.

---

## Mental Model

Think of forkrun as:

> A speculative execution engine where **progress is irreversible**, and correctness emerges from that irreversibility.

Once progress moves forward, the past is immutable — and that makes the system safe.

---

## Final Note

forkrun is fast not because it is clever,
but because it is **strict about what matters** and **indifferent to everything else**.

-------------------------------------------------------------------------------------

# SUMMARY CHART

---

# Batch-Related Invariants — Formal Summary Table (v9+)

### Legend

* **S** = Scanner
* **W** = Worker
* **CAS** = compare-and-swap
* **R/A** = release / acquire semantics

---

## 1. Batch Size State Machine

| Property            | Allowed Actor | Condition                                                   | Operation                       | Atomic Requirement | Forbidden           | Correctness Guarantee                 |
| ------------------- | ------------- | ----------------------------------------------------------- | ------------------------------- | ------------------ | ------------------- | ------------------------------------- |
| Publish batch size  | S             | Anytime before tail                                         | `batch_size = -abs(N)`          | Store (R)          | Publishing positive | Policy is advisory, mutable           |
| Change batch size   | S             | Policy change                                               | Update magnitude, keep negative | Store (R)          | Flipping sign       | Policy evolution is monotonic in time |
| Finalize batch size | W             | `read_idx < tail_idx` AND stream count == `abs(batch_size)` | `-N → +N`                       | **CAS**            | Non-CAS flip        | Prevents stale policy commit          |
| Reject stale policy | W             | CAS fails                                                   | Re-read batch size              | Load (A)           | Proceeding anyway   | No resurrection of old policy         |
| Tail finalization   | W             | `read_idx ≥ tail_idx` AND `batch_size < 0`                  | `-N → +N`                       | **CAS**            | Slow path           | Exactly one tail claim                |

---

## 2. Scanner Batch Publication Rules

| Rule             | Applies To       | Allowed                            | Forbidden            | Reason              |
| ---------------- | ---------------- | ---------------------------------- | -------------------- | ------------------- |
| Pre-tail batches | `idx < tail_idx` | Publish/update negative batch size | Publishing positive  | Workers finalize    |
| Tail ramp-down   | `idx ≥ tail_idx` | **No batch size publication**      | Any size change      | Tail is structural  |
| Final batch size | Last full batch  | Publish once, negative             | Modifying after tail | Policy ends at tail |

---

## 3. Worker Claim Behavior

| Scenario                   | Worker Action         | Atomic Rule       | Slow Path Allowed | Escrow Allowed | Guarantee         |
| -------------------------- | --------------------- | ----------------- | ----------------- | -------------- | ----------------- |
| Full batch, policy stable  | Claim normally        | `fetch_add`       | No                | Yes            | High throughput   |
| Full batch, policy changed | Retry policy          | CAS fail → reload | No                | Yes            | No stale commit   |
| Overshoot pre-tail         | Partial exec + escrow | None              | Yes               | Yes            | Latency smoothing |
| Tail batch                 | Single claim only     | **CAS finalize**  | **No**            | **No**         | Exactly-once      |

---

## 4. Tail Structural Rules

| Property         | Definition      | Enforced By     | Forbidden                | Guarantee              |
| ---------------- | --------------- | --------------- | ------------------------ | ---------------------- |
| Tail boundary    | `tail_idx`      | Scanner (R)     | Workers aggregating past | No partial records     |
| Tail batches     | Self-describing | Offset sign bit | Batch-size inference     | Structural correctness |
| Tail claim count | Exactly one     | Worker CAS      | Multiple claims          | No duplication         |

---

## 5. Offset Encoding Invariants (Batch-Relevant)

| Field           | Meaning              | Written By | Read By | Immutable When | Purpose             |
| --------------- | -------------------- | ---------- | ------- | -------------- | ------------------- |
| Offset value    | Byte offset          | S          | W       | After publish  | Zero-copy access    |
| Offset sign bit | Partial batch marker | S          | W       | Always         | Tail detection      |
| Stride metadata | True record count    | S          | W       | After tail     | Correct tail sizing |

---

## 6. Atomicity & Ordering Summary

| Variable     | Writer                 | Reader | Ordering   | Why                    |
| ------------ | ---------------------- | ------ | ---------- | ---------------------- |
| `batch_size` | S (neg), W (sign flip) | W      | R/A + CAS  | Time-consistent policy |
| `write_idx`  | S                      | W      | R/A        | Publish-before-claim   |
| `read_idx`   | W                      | W      | Atomic RMW | Unique ownership       |
| `tail_idx`   | S                      | W      | R/A        | Structural boundary    |

---

## 7. Forbidden Transitions (Batch Domain)

| Transition                      | Reason                            |
| ------------------------------- | --------------------------------- |
| S publishes positive batch size | Breaks finalization contract      |
| W modifies magnitude            | Violates policy ownership         |
| Any positive → negative         | Resurrects stale policy           |
| Batch size update after tail    | Tail is structural, not policy    |
| Slow path in tail               | Risks duplicate or blocked claims |

---

## 8. Global Batch Correctness Guarantees

If all rules in this table hold:

* Each batch is finalized **exactly once**
* No stale batch size can be committed
* Tail batches are single-claim and self-describing
* No partial data leaks
* Policy changes cannot race correctness

**Batch behavior is correct by construction.**

---

