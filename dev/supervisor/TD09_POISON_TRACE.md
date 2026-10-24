# WO-PY-REL-1 — Workstream A: TD-09 poison-index trace (Phase A)

Source-backed trace performed **before** any production change, as the work
order requires. Every line reference is against `a65aa4ca`.

## Headline

TD-09 is **not** engine work. The register entry says closing it "needs a C
accessor returning poisoned indices on the non-reactor path … that is engine
work, not a stats patch". That is **wrong**, and this trace shows why.

`fr_py_claim()` in `python/forkrun/_shim.c` — the claim function used by the
**plain in-process worker** — already calls `fr_py_poison_relay()` at
`_shim.c:447`. The index is relayed correctly on `orchestrator=False` today.
The only thing missing is that **no Python code ever sets up the receiving
end**: no memfd is created, `FRK_POISON_FD` is never exported, and the fd is
not in the worker's scrub keep-set.

Measured, not assumed: with a memfd created and the fd forced through
`scrub_fds`, the unmodified plain path wrote
`[0,1,2,3,4,5,6,7]` for the register's own 8-batch scenario. The C side
needed nothing.

## Q1 — Where is a batch known to have crossed the poison threshold?

`_shim.c:432-447`, inside `fr_py_claim()`:

```c
if (limit >= 0 && batch.num_kills >= (uint32_t)limit) {
    uint32_t poison_threshold = (limit > 0) ? (uint32_t)limit : 1;
    poisoned = 1;
    if (batch.num_kills == poison_threshold && g_state) {
        uint32_t total_poisoned = __atomic_add_fetch(&g_state->poisoned_count, 1, ...);
        fr_py_poison_relay((uint32_t)batch.batch_idx);
```

Two properties that matter for this task:

* the threshold test is `>=`, but the relay fires on the `==` edge only, so
  **exactly one relay per poisoned batch** — no per-retry duplication. The
  count increment is on the same `==` edge, so count and index list cannot
  diverge by construction;
* the Python worker sees the same fact independently at `_worker.py:587`
  (`claimed.poisoned`) and has `claimed.batch_idx` at that point.

Because the relay is gated on the `==` edge, "capture the index only when
actually declared poisoned, not on a transient failure whose retry
succeeds" is satisfied by construction — no new predicate is needed.

## Q2 — Which process knows the index at that point?

The worker process (forked child), in `fr_py_claim`. The parent never learns
it from shared memory: only the scalar `g_state->poisoned_count` crosses
(`_shim.c:437`), read via `fr_py_poisoned_count()`
(`_shim.c:589`, called from `_executor_core.report_poison` at line 416).

## Q3 — Is the existing relay callable from the plain worker path?

Yes — it is **already called** from it. `fr_py_claim()` is what
`_worker.py:581` invokes, and it relays at `_shim.c:447`. What the plain
path lacks is the transport setup:

* `FRK_POISON_FD` is set in exactly one place in the tree,
  `forkrun_cleanroom.c:2017` (the launcher). No Python code sets it, so on
  `orchestrator=False` `fr_py_poison_relay()` resolves `g_poison_fd < 0` and
  returns immediately (`_shim.c:56`).
* `_fd_scrub.scrub_fds()` closes every fd not in `keep`, so even with the
  variable exported the fd would be closed in the child before the relay ran.

Both are Python-side. **No change to `_shim.c`, `forkrun_ring.c`, or any
frozen file is required.**

## Q4 — How is the worker ID chosen for the stats slot, per mode?

`g_fr_config.ring_wid` (`_shim.c:56-58`), the engine's worker id, and the
slot is `4 + wid * (FR_POISON_SLOT_U32 + 1)` u32 words. Both parent-side
fork paths number children by loop index `i`, which is the wid handed to
`worker_main`/`fr_py_worker_plugin_loop`. So slot `i` corresponds to child
`i` for every plain-path worker kind. `wid >= 4096` is refused by the relay
(`_shim.c:59`).

The reactor's slot identity is unrelated and is **not** reused: it carries
indices as formatted strings over the trap-ACK pipe
(`_reactor.py:940-944`), parsed back by `run._poison_indices`.

## Q5 — Which descriptors/environment survive fork + scrub?

* **Environment**: inherited across `os.fork()` automatically, provided the
  parent exports it before forking. `scrub_fds` does not touch `environ`.
  So `FRK_POISON_FD` needs a plain `os.environ` set before `_core_fork`, and a
  **restore afterwards** so it cannot leak into later runs or sibling tests.
* **Descriptor**: does **not** survive by default. `scrub_fds`
  (`_fd_scrub.py`) keeps `keep ∪ {0,1,2}` and closes the rest. The keep set is
  built independently in four places: `fork_workers`'s python branch
  (`_executor_core.py:114-121`), `_fork_c_plugin_worker`
  (`_worker.py:1022`), `_fork_c_spawn_worker` (`_worker.py:1092`), and the
  splice fork. The fd therefore must be **threaded explicitly** into those
  keep sets.

Chosen: explicit plumbing of one optional `extra_keep_fds` argument, rather
than teaching `scrub_fds` to honour `FRK_POISON_FD`. Env-driven scrubbing
would make the keep-set depend on ambient process state that must not leak,
and the failure mode of getting it wrong is a silently closed stats fd.

## Q6 — What bounds the indices, and how does the parent detect incompleteness?

`_STATS_CAPACITY = _STATS_SLOT_U32 - 1 = 1024` indices per worker slot
(`run.py:1679-1682`). The relay **drops silently** when the slot is full
(`_shim.c:64-65`, `if (n >= FR_POISON_SLOT_U32) return;`), so the slot count
is a lower bound on that worker's poisons.

Completeness is therefore a comparison against the exact scalar:
`truncated = relayed < poisoned`, which is precisely what the cleanroom
already does (`run.py:1649`, `_trunc = nrelayed < npois`) and warns about
(`run.py:1650-1658`). The same rule applies here, and it is what makes a
truncated list never look complete.

Aggregation: `relayed = Σ slot counts`, indices sorted+deduped when
assembled (`run.py` already does this for the reactor via `_poison_indices`).

## Q7 — Are index widths consistent end-to-end?

**No. There is a real 32-bit truncation, and it is pre-existing and shared.**

* Engine: `struct WorkerBatchState { uint64_t batch_idx; ... }`
  (`forkrun_ring.c:1421`), and the Python out-param is `uint64_t batch_idx`
  (`_shim.c:87`).
* Relay: `fr_py_poison_relay(unsigned int batch_idx)` (`_shim.c:34`) called as
  `fr_py_poison_relay((uint32_t)batch.batch_idx)` (`_shim.c:447`). **A u64
  index ≥ 2^32 is silently truncated to 32 bits.**
* Python `P:` channel (reactor): formatted with `%d` from a Python int —
  width-safe.

So the **cleanroom path has the same truncation today**, and the reactor does
not. This work does **not** widen the relay: doing so means changing the
shared slot geometry (`FR_POISON_SLOT_U32`), the launcher's pre-size in
`forkrun_cleanroom.c`, and `_STATS_SLOT_U32` here, i.e. a relaunch of the
shipped `_forkrun_cleanroom` binary and its CI build — a blast radius well
beyond this task, and one that would silently alter a shipped artifact's
stats layout.

Reachability, stated precisely: `batch_idx` comes from `read_idx`, which
increments for **every batch claimed** (`forkrun_ring.c:6222`), so the
trigger is a POISONED batch whose index is ≥ 2^32 — roughly 2^32 batches
processed in total, of which only that one need be poisoned. (A first
draft of this note said "≥ 2^32 distinct poisoned batches", which
mislabelled the quantity; corrected here and in the register.) Recorded
as a residual finding rather than silently inherited.

The plain path is now **consistent with the cleanroom path**, which is the
contract C3 asks for, and it does not introduce a new truncation.

## Decision for Phase B

Reuse the existing bounded memfd transport on the plain path:

1. parent creates the stats memfd and pre-sizes it to
   `header + workers * _STATS_SLOT_U32 * 4`;
2. parent writes the v2 header (`version=2`, poisoned placeholder, workers,
   stride) **before** forking;
3. parent exports `FRK_POISON_FD`, restoring the previous value afterwards;
4. the fd is threaded into the worker keep-sets;
5. after the join, the parent writes the **true** poisoned count (from
   `fr_py_poisoned_count()`) into the header and reuses
   `_read_cleanroom_stats()`, so the plain path returns the same
   `(poisoned, indices, relayed)` triple the cleanroom already produces;
6. `_LAST_STATS["poisoned_batches"]` / `["poisoned_batches_truncated"]` are
   set **before** `report_poison()`, so `strict_poison` still raises with
   inspectable post-exception stats.

Rejected alternatives:

* **reactor `P:` pipe on the plain path** — needs the same keep-set plumbing,
  plus the parent must drain the pipe during the waitpid loop or a worker
  blocks once the 64 KB pipe fills (~5.9k poison lines). Touching that loop is
  the supervision change the work order forbids.
* **new unbounded event queue / per-batch Python work** — explicitly excluded
  by the work order, and unnecessary: the relay costs nothing on a successful
  batch.

## No frozen file is touched

`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c` are untouched.
`_shim.c` is **not** required at all — its relay already runs.
