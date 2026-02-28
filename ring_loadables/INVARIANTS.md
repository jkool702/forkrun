### `INVARIANTS.md`

# FORKRUN INVARIANTS (v9.8.0-NUMA Golden Master)

These are the rules that **must never be broken**. If they hold, the system is correct regardless of batching heuristics, NUMA count, or workload shape.

---

## 1. Slot Ownership & Monotonic Indices (Global)

**Invariant**  
Each ring slot (per node) is claimed **exactly once**.

**Enforced by**  
`atomic_fetch_add` on the node-local `read_idx`. No CAS retries, no rollbacks.

**NUMA note**  
Each `SharedState` has its own `read_idx` / `write_idx`.

**Audit rule**  
Never introduce per-slot claiming or conditional rollback.

---

## 2. Publish-Before-Claim (Per Node)

**Invariant**  
Workers never observe uninitialized slots.

**Enforced by**  
Scanner writes ring data **then** `atomic_store_release(write_idx)`.  
Workers use `atomic_load_acquire`.

---

## 3. Batch Atomicity

**Invariant**  
A batch is claimed whole or not at all (overshoot handled after claim).

---

## 4. Signed Batch Size Protocol (Legacy Mode Only)

In non-NUMA (`--nodes=1`) mode the original signed-batch-size + CAS finalization protocol still applies exactly as described in earlier versions.

In full NUMA mode (`global_num_nodes > 1`) the protocol is **simplified**:
- Scanner still publishes negative advisory sizes.
- Workers no longer perform the CAS sign-flip (each node’s scanner is authoritative).
- `signed_batch_size` is still used for adaptive control but finalization is implicit.

**Forbidden**  
Never publish a positive batch size from the scanner in any mode.

---

## 5. Tail-Aware Rules (Applies to All Modes)

- Once `tail_idx` is published, the scanner **must not** change batch size.
- All tail batches are self-describing (sign bit + stride metadata).
- Workers at or past `tail_idx` finalize immediately and take exactly one claim (no escrow, no slow path).

---

## 6. NUMA-Specific Invariants (New in v9)

| Invariant                              | Enforced By                              | Why It Matters                     |
|----------------------------------------|------------------------------------------|------------------------------------|
| Data born-local to target node         | `set_mempolicy(MPOL_BIND)` at ingest     | Zero cross-socket traffic          |
| Scanner pinned to its node             | `pin_to_numa_node()` + `getcpu()`        | Locality guarantee                 |
| Per-node escrow                        | `fd_escrow_r/w[N]` array                 | No cross-node contention on steal  |
| Major/minor ordering keys              | `major_ring[]`, `minor_ring[]`           | Correct global reorder in NUMA     |
| Claim pipe back-pressure               | `claim_pipe` + `ring_numa_ingest`        | Prevents unbounded memory growth   |

---

## 7. Escrow Correctness

**Invariant**  
Escrow is advisory. Forward progress never depends on it.

---

## 8. Waiter & Eventfd Accounting

Over-counting waiters is safe. Under-counting is forbidden.  
Eventfds are advisory only — correctness is carried by monotonic indices.

---

## 9. Ordering & Emission

Logical (major/minor) indices define output order in buffered mode.  
Never emit based on completion time.

---

## 10. Checklist Summary (v9.8.0-NUMA)

If every rule above holds, **the system is correct** no matter what you change in:
- adaptive controller
- NUMA topology
- worker spawn policy
- fallow aggressiveness

---

**Mental model reminder**  
> Progress is irreversible. Locality is structural. Contention was designed away.

These invariants are what let forkrun scale to tens of millions of lines per second while staying debuggable and deterministic.
