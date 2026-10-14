# Round 17 — review the Option 1 implementation plan BEFORE touching the ring

Branch `NEW/REFACTOR4.2`. Review the **branch head** (`c1e7814b`; the
correspondence sweep referenced below is now pushed and was 404 when you
last looked).

**1065 tests, 0 unexpected failures, 2 skipped.** Release gate green.
`forkrun_ring.c` untouched.

**Short request, and time-sensitive.** The user is offline, so this is
the last chance to change the plan before it gets implemented. Nothing
below is written yet.

You authorized Option 1 with a narrowly scoped frozen-ring exception. I
accept that and I am **not** re-litigating it. What I want reviewed is
the plan, because it contains one non-obvious inference that is expensive
to undo after it is in C.

---

## 1. The decision I want checked

The sweep falsified Option 2, and the reason matters for where the counter
goes. I originally thought the extra slot was a frame the framer
*discards*; `filtered == 0` in every configuration disproved that. And
`write_idx` is **not a publication count at all** — it is the scanner's
cursor, advanced by `UNIFIED_ADAPTIVE_COMMIT` (`forkrun_ring.c:3837`) to
`local_scan_idx`.

So my plan:

> Increment the new counter at the **packet-write site in the worker
> loop**, where a frame is actually emitted — **not** where `write_idx`
> advances.

**Rationale:** incrementing at the cursor would reproduce exactly the
off-by-one the sweep found. The two are different points, and only the
packet-write site corresponds 1:1 with what the parent observes.

**Question 1: is that the right site?** I have traced the path but not
yet located the write itself:

| stage | location |
|---|---|
| scanner advances `write_idx` | `UNIFIED_ADAPTIVE_COMMIT`, ring:3837 |
| worker order-pipe write end | `fr_py_set_order_pipe`, shim:2280 (set once, `_reactor.py:765`) |
| orderer reads packets | `ring_order_main` `fd_in`, ring:7487 |

If the correct increment point is somewhere else, or if there is more than
one emission path, I would rather find that out now.

## 2. Narrowness — is this the right shape of exception?

My plan adds **one field** to `SharedState` and **one increment**, and
**no new ring function**. `_shim.c` textually includes `forkrun_ring.c`
and already reads `state[node].write_idx` directly, so it can read the new
field with **zero ABI change** and without touching an existing field's
meaning.

**Question 2:** is a bare struct field the narrowest acceptable form, or
does the accessor you described ("a narrowly scoped accessor or diagnostic
snapshot") imply a real function is expected? I chose the field because
it changes no interface at all, but it does put a new member in a frozen
struct.

## 3. Ordering — the point you specifically flagged

You warned that *"the counter and `write_idx` must have well-defined
publication and snapshot ordering"*, or a snapshot taken with a publisher
live could report a false discrepancy on healthy output.

Plan: `__atomic_store_release` on increment, `__atomic_load_acquire` on
snapshot, matching how `write_idx` is already ordered in the same file.

**Question 3:** is matching `write_idx`'s ordering sufficient, or does the
snapshot need a stronger guarantee — e.g. reading after a barrier that
proves publication has *drained*, not merely that writes are visible?
Those are different claims and I am not certain which one the certificate
needs.

## 4. The UMA gap, as you framed it

You said not to leave this as a NUMA-only patch, and that the certificate
must not claim to cover a path with no authoritative expected count.

Current state: `_numa_drain_audit` is called from two NUMA sites only, so
UMA `order="index"` has **no** expected side at all — the sweep could not
even compare it (`published = "-"`).

Plan: read the same counter for UMA (node 0) from a new site on the UMA
ordered path.

**Question 4:** does UMA publication differ materially enough that the
counter's meaning would not carry over — in which case that difference
needs documenting and testing rather than assuming a common invariant?

## 5. Naming

Your rename, adopted: the design's `expected_records` / `actual_records`
became `expected_slots` / `observed_frames`, and with this change
`expected_data_slots` / `observed_frames`. The distinction between "slots
the scanner passed" and "frames the parent observed" is the entire
finding, and the names should not blur it.

## 6. What I will do after this, in order

1. Locate the packet-write site and confirm per-node reachability.
2. One `SharedState` field, one increment, no new ring function.
3. Release/acquire ordering per §3.
4. Extend the expected side to UMA; re-run the sweep expecting
   `expected_data_slots == observed_frames` everywhere.
5. Fault injections: interior frame, final frame, orderer death, transport
   and emission failure — each must fail loudly, never exit 0.
6. Healthy-case coverage: EOF, empty tails, one node, multiple nodes,
   UMA `order="index"`.

NUMA stays opt-in throughout, and multi-socket validation remains a gate
I cannot satisfy here — `nodes="@N"` is logical, so nothing about real
placement or locality is established by any of the above.

## 7. Honest status

- The sweep is committed and runnable; the measurements above are its
  output, not assertions.
- `observed_frames` counting is implemented and inert (populated, read by
  no production path).
- `_ordered_completeness_certificate()` exists and is **deliberately not
  wired**, because wiring it against `write_idx` fails healthy runs.
- **No ring change exists yet.** This request is to agree the plan before
  there is one.