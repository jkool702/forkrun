# FD-Array Recycle Audit + R-V2 Decision (W-REL4)

**Verdict: HALT AND REPORT — sketch not implemented.** The invariant
closure (INVARIANTS §20) remains adequate. No engine changes, no blob
cycle. This file is the durable record of the audit and the reasoning.

## 1. Inventory (all engine fd arrays held across fork)

| Array | Contents | Created | Closed |
|---|---|---|---|
| `evfd_data_arr[]` | per-node eventfd (claim wakeups; the mover's proven read site via `do_lockfree_claim`) | `ring_init_main` (~2669) | `ring_destroy_main` (~2827) |
| `evfd_eof_arr[]` | per-node EOF eventfd | same | same |
| `evfd_indexer_arr[]` | per-node indexer eventfds | same | same |
| `evfd_meta_arr[]` | per-node meta eventfds | same | same |
| `fd_escrow_r/w[]` | per-node escrow pipes | same (pipe pair per node) | same |
| scalars | `evfd_ingest_data/eof`, `evfd_chunk_done`, `evfd_data` (= copy of `arr[0]`, ~2720) | same region | same region |
| `fd_states[]` | orderer-local per-fd emit state, indexed BY fd number, grown dynamically | per orderer run | per orderer run |

Out of scope (no array staleness): `fd_order_pipe` (config scalar,
set per worker), death pipes (bash-owned; Python `death_r` closed in
teardown — R11), per-run order pipes (created + closed symmetrically
per run), `EVFD_RING_*` bash variables (bound once, no readers found
in `frun.bash` — legacy/unused).

Close discipline verified sound: every array has init-time creation
with failure rollback (`ring_destroy_main` on partial failure) and
teardown-time close + free + NULL. No mid-run closes of array fds
found (consistent with the W-MOVER audit).

## 2. Why the sketched dup-hold does not close the proven mechanism

The MOVER-proven mechanism is **number recycling inside a forked
child's private fd table**: the child closes number N (closer
unidentified — the residual), reopens (memfd/pipe gets N), then the
claim path reads `evfd_data_arr[slot] == N` (inherited snapshot) and
hits the wrong file.

A `dup()` held anywhere — parent table, array-adjacent slot, or
child table — does not pin a *number*. Number allocation is
per-table lowest-free at `open()`/`pipe()`/`eventfd()` time and is
utterly indifferent to how many references the underlying file
description holds elsewhere. Concretely, for each placement:

- Extra ref in the parent table: child closes N, child reopens get
  N anyway. No effect.
- Dup number stored in the array (replacing the original): the test
  in the order ("close that fd externally, reopen, array still
  hits the eventfd") fails by construction — the array number now
  names the new file. No effect.
- Extra ref in the child table: same-table close still frees the
  number for the child's next open. No effect.

Related dead ends checked: `dup2`-over (closes the target
regardless of references — a dup would not help there either);
`fd_states[]` (orderer-local, no cross-fork staleness).

## 3. What would actually close it

- **fd-identity validation at the claim path** (record `st_dev`/
  `st_ino` of each array fd at init; re-validate before the drain
  read; abort loudly on mismatch): converts silent corruption to
  loud abort. This is the W-MOVER-halted engine fix — still the
  right shape, still needs engine changes + owner decision.
- **Child keep-set discipline for array fds**: never close a number
  held in an array snapshot. Requires identifying the closer —
  the unknown origin this order could not resolve either.
- **Re-resolve post-fork**: children re-derive array fds from a
  trusted source instead of trusting inherited numbers.

## 4. Secondary findings (no action)

- The order's lock-in as specified is unimplementable without new
  bindings (`evfd_data_arr` is a C static; `_shim.c` untouched per
  the order's own gates forbids the accessor) and its success
  criterion contradicts Unix number-allocation semantics (above).
- fd consumption note for any future dup scheme: 6 held fds/node
  today; doubling to 12 makes `@512` forced-logical need 6144 fds
  (past default `ulimit -n`; frun's nofile boosting already covers
  the current 3072 — proportional, but must be accounted).

## 5. Recommendation

Keep INVARIANTS §20 (position-undefined contract — the scanner
never reads positionally, proven by `test_mover.py` 10/10 and the
forensic loop). File the identity-validation fix as W-REL4-backlog
(owner decision, engine change + blob cycle). Do not implement the
dup sketch: it spends fds and review trust without closing the
proven mechanism.
