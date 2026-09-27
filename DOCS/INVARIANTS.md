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
Workers claim exactly 1 slot (1 batch) at a time. Atomicity is enforced upstream by the Scanner, which pre-calculates and bounds the line/byte offsets for the batch within that single slot before publishing.

**Audit Rule**  
❌ Never introduce logic that conditionally claims per-slot or splits batch claim across multiple atomics.

---

## 4. Single-Slot Claim Invariant

**Invariant**  
Workers always claim exactly 1 ring slot via a single `atomic_fetch_add`. The Scanner is solely responsible for determining the batch size (`L`) and publishing the byte/line boundaries for that batch into the slot before advancing `write_idx`.

**Enforced by**  
The worker fast path is unconditional:
```c
my_read_idx = __atomic_fetch_add(&local_state->read_idx, 1, __ATOMIC_SEQ_CST);
claim_count = 1;
```
No CAS retry loops. No sign-bit checks. No speculative multi-slot arithmetic. The Scanner changes the *contents* of slots (larger or smaller batches); workers never see the policy, only the slot.

**The Fallback Guarantee**  
Even when the Pre-Flight Popcount is interrupted by an early worker spawn — causing the Scanner to fall back to the Phase 1 Geometric Ramp-Up — the worker hot-path is identical. The Scanner publishes larger batches into single slots. Workers remain completely oblivious.

**Audit Rule**  
❌ Never introduce logic where a worker claims more than 1 slot in a single atomic operation.  
❌ Never introduce CAS retry loops on `read_idx`.  
❌ Never route workers through different code paths based on a sign bit or advisory batch-size value.

---

## 5. Tail-Aware Drain Rules

**Definition**  
The tail begins when the scanner approaches EOF. Remaining data may not cleanly fill the current batch size `L`.

**Scanner Responsibilities**  
When the tail is reached, the scanner publishes the final partial batch as a normal single-slot claim bounded by the EOF/chunk boundaries and sets `FLAG_MAJOR_EOF` in `minor_ring` (NUMA mode) or relies on `scanner_finished` / `write_idx` reaching EOF (UMA mode). The scanner stops changing batch-size policy once the tail begins.

**Worker Responsibilities at Tail**  
Workers do nothing differently. They claim exactly 1 slot. Because the scanner has already bounded the slot to the exact remaining bytes/lines, the worker processes it and moves on. There is no overshoot to correct at the tail boundary — a single-slot claim never reaches past what the scanner has published.

**Key Insight**  
Batch size is a *policy*, not a property of the tail. Once the tail begins, policy ends and structure takes over. The single-slot claim invariant (§4) eliminates the tail-overshoot problem entirely.

**Audit Rule**  
❌ Never introduce logic that forces workers to finalize or roll back a multi-slot claim at the tail.  
❌ Scanner must not publish batch-size changes after entering the tail.

---

## 6. Escrow Correctness

**Invariant**  
Escrow is advisory and never required for forward progress.

**Enforced by**  
Escrow is strictly a fault-tolerance channel for crashed workers. Because workers claim exactly 1 slot, there are no partial remainders to subdivide or reclaim. Escrow stealing is optional but critical for recovery.

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

## 11. Gate Publication & Producer Wakeup Invariant

**Invariant**
Any process publishing gate-resolving state (`actual_end`, `cum_lines`, `write_idx`) must execute a `SEQ_CST` memory barrier and issue `sys_write` to the corresponding metadata/data eventfd whenever waiters are present (`meta_waiters > 0` or `active_waiters > 0`).

**Enforced by**
All publication sites in `forkrun_ring.c` issue release stores followed by an explicit `__atomic_thread_fence(__ATOMIC_SEQ_CST)` before checking waiter counters and waking sleeping threads.

**Audit Rule**
❌ Never remove or conditionally optimize away eventfd wakeups on gate-resolving state publications.

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

## 13. No Sole-Path Data Movement

**Invariant**
Every byte-mover (`sendfile`, `copy_file_range`, `splice`, `write`) must have a fallback
path that is exercised by the test matrix, not merely present in the code.

**Enforced by**
The orderer's emit path falls back from `sendfile` to `read`/`write` on *any* failure
(`O_APPEND` → `EINVAL`, partial sends, environment-specific `EINVAL`). `ring_copy`'s
cascade (`copy_file_range` → `sendfile` → `read`/`write`) is the canonical form. `FORKRUN_DISABLE_MEMPOLY`
is the pattern for per-mover forced-fallback test hooks.

**Origin**
`sendfile` + `O_APPEND` returned `EINVAL`; the failure was classified as "downstream
closed" → clean exit 0 → every `frun ... >> log` silently produced zero output.
The fallback existed elsewhere in the codebase for years but was never exercised.

**Audit Rule**
❌ Any `sendfile`/`splice`/`copy_file_range` call site whose failure mode
terminates the operation rather than degrading. A zero-copy path that cannot fail
on *some* supported kernel/filesystem/fd-configuration does not exist. An
unexercised fallback is a comment, not a fallback.

**Companion rule — failures must be loud before they can be silent.** `EPIPE` means
"downstream closed" (the only clean-exit condition); everything else is an internal
fault (checkpoint + non-zero exit). Any error path that can produce a successful-
looking exit from a failed operation is a taxonomy bug independent of the operation.

---

## 14. Gates Inspect Text, Never Live State

**Invariant**
A security gate must make its decision from *serialized text*, never from state
derived from executing the text it is gating. The layer-3 resume gate previews
content built from raw strings; function definitions cross only after the gate's
decision. (The frame-split emission exists to make this true: variables and
function text are separate token-bounded frames.)

**Origin**
The pre-split design eval'd functions before the gate ran, so the gate's own
`printf -v` preview could execute the very functions it was asking the user about.

**Audit Rule**
❌ Any gate whose preview/decision commands can be shadowed by content the gate
has already imported into scope. If the gate needs functions to make its decision,
the design is wrong — the decision must be derivable from text.

---

## 15. Sanitize by Construction, Not by Clearing

**Invariant**
A hostile environment must be *constructed* (execve-time `env -i` + explicit
values), never assumed to result from clearing or assigning. Shell-level
assignment can be vetoed (restricted mode: `PATH` is readonly); environment
clearing can be defeated by the target's re-seeding defaults (unset `PATH` →
bash's compiled-in default). The construction layer is below the shell's opinion.

**Origin**
Three successive "sanitizations," each falsified by a twenty-second probe:
`PATH=''` prefix (cleared by `exec -c`), unset `PATH` (bash re-seeds defaults),
in-sandbox `PATH=/nonexistent` (readonly under `--restricted`). The fourth —
`env -i` at exec time — holds because it operates where the shell cannot veto it.

**Audit Rule**
❌ Any security property that depends on a variable surviving an `exec -c`, or
on "unset" meaning "unsearchable." Verify each sanitization mechanism empirically,
per mechanism, with a probe — and make the adversarial tests (T1b/T1d/T1f) the
permanent runtime tripwire.

---

## 16. Scanner Base Determinism (F-PY-UMA1)

**Invariant**
The scanner's coordinate base (`buf_base_offset`, hence the first
published window) must be deterministic — byte 0 — regardless of
the fork-shared file offset it inherits.

**Origin**
The UMA scanner seeded its base from `lseek(SEEK_CUR)` on the
fork-shared ingress memfd. Under sequential in-process runs that
offset was observed nonzero (72–10120 in 15 caught instances),
silently dropping the `[0, K)` head with torn seams — while the
parent had verified offset 0 pre-fork. Forcing the base to 0
eliminated all failures (0/48 forensic iters, 9–10/10 gates).

**Enforced by**
Explicit `lseek(fd, 0, SEEK_SET)` + `buf_base_offset = 0` at
scanner entry (NUMA already hardcoded 0). All callers start at
byte 0 by contract (materialized callers lseek first; streaming
helpers fork pre-spill), so the reset changes no legitimate path.

**Audit Rule**
❌ Any coordinate seed read from shared mutable file state
(SEEK_CUR, unanchored offsets) instead of an explicit reset.
The query-then-trust pattern is the violation, however small
the window between query and use.

---

## 17. NUMA ChunkMeta Lifetime (F-NUMA1)

**Invariant**
A `ChunkMeta` slot must not be recycled (overwritten by chunk
`major + META_RING_SIZE`) while any indexer or scanner can still
read it. Concretely: the ingest publish frontier stays within
`META_RING_SIZE/2` of the oldest unread chunk on any node with
unfinished work, and every scanner reads a chunk's descriptor
exactly once (snapshot at claim+ready) and never re-dereferences
`meta->` for the same chunk.

**Origin**
Heavy-20M C-plugin runs under forced-logical `@4` completed
cleanly (exit 0, no warnings) with ~22–31% of records missing —
almost always a whole orderer-key suffix from one gap major. Key
forensics: every failing run showed ack keys duplicated at exactly
`gap + META_RING_SIZE` (ten events across runs, plus hidden
downstream gaps at the same offset), each dup pair spanning two
nodes. A stalled node's claimed-but-unread chunks let the global
publish frontier lap it by a full meta ring: its slot (same slot
mod 4096) was recycled before it was read, so batches were stamped
with a future major. The dup keys sat in the C orderer's heap
behind the gap; at pipe EOF the leftovers were freed with rc 0 —
silent tail loss. Per-node queue caps cannot prevent this (they
bound unclaimed depth, not claimed-unread lag, and the indexer can
race thousands of chunks ahead of its shield-stalled scanner).
Reproducer shape: sequential in-process maps (or one map from a
~20GB parent — retained output slows helper startup into the same
skew), never fresh-small processes.

**Enforced by**
(1) `indexer_major` + `scan_claim_major` per-node progress
markers (relaxed stores; published per consumed chunk / per
successful claim) and the ingest lifetime bound
(`ring_numa_ingest_main`): stall publish while
`frontier - min(marker) >= META_RING_SIZE/2` over nodes with
`head > ready`. Indexer progress alone is insufficient (observed:
nine consecutive +4096-stale first-reads on a node whose indexer
had moved on) — the scanner marker is load-bearing. Nodes with
empty queues don't pin; EOF bypasses; staleness stalls more, never
less. (2) Per-chunk meta snapshot in indexer and scanner: copy
`(major_id, raw_offset, raw_length[, target_node])` to stack
locals at the gated point and use locals thereafter. Publication
writes (`actual_end`, `cum_lines`) still go through `meta` (own
slot, indexer-pinned while unread).

**Audit Rule**
❌ Any `meta->` read past the claim+ready snapshot point for the
same chunk (per-flush `major_id`, search-window bounds,
EOF-sentinel range). ❌ Any publish path that lets the global
major frontier exceed the oldest unread chunk's generation window.
New readers of `ChunkMeta` must either snapshot or prove their
window is pinned by the lifetime bound.

---

## 18. Per-Node Worker Coverage (F-NUMA2)

**Invariant**
On multi-node topologies the parent must guarantee ≥ 1 worker
per node before ingest begins; worker counts below the node
count are raised, not honored.

**Origin**
User-supplied `workers < nodes` left born-local rings permanently
unworked (workers claim locally only; stealing covers orphans,
not healthy-but-unassigned rings). The F-NUMA1 drain guard made
the resulting shortfall loud (RuntimeError at completion), but
loud failure is still failure for a configuration the parent
could have satisfied. Correctness of exactly-once delivery
dominates the user's worker-count lower bound: nobody asks for
fewer workers *because* they want stranded data.

**Enforced by**
Single normalization point
(`_resolve_workers_numa(workers, num_nodes)`): `max(workers,
num_nodes)` on multi-node topologies with one `UserWarning`
(requested vs effective); UMA exempt; idempotent (effective
counts pass through silently, so downstream re-resolution never
double-warns). Per-node distribution is round-robin from node 0,
so `workers >= nodes` covers all nodes by construction. The
F-NUMA1 drain guard stays as the backstop for genuine runtime
anomalies.

**Audit Rule**
❌ Any NUMA executor path that forks workers from a raw user
count without passing through the normalization point. ❌ Any
conditional bump (input-size heuristics, "looks unneeded") —
the invariant is unconditional on multi-node topologies.

---

## 19. Frontend Port Guarantees (W-PORTAUDIT)

The Bash and Python frontends share the engine (one TU) but not
the orchestration layer. Every parent-side guarantee below was
once Bash-only, lost or thinned in the Python port, and is now
locked in Python by the differential audit (`dev/supervisor/
PORT_AUDIT.md`: 32 items, 11 PORTED / 8 EQUIVALENT /
7 N/A-BY-DESIGN / 6 fixed / 3 deferred). The audit's standing
rule: **F-NUMA2 was also "different architecture" until it
wasn't** — N/A claims require a named structural reason, never
a vibe.

**Invariant (drain-before-complete)**
Before declaring NUMA completion the parent verifies per-node
drain (`read_idx >= write_idx` on every node); with full worker
coverage any other unclaimed tail raises `RuntimeError` naming
node and indices, with under-coverage it warns once and returns
the partial output. `read_idx > write_idx` (claim overshoot) is
benign and never fires. (EOF_PROTOCOL §7; F-NUMA1 parent half.)

**Invariant (poison-threshold fidelity)**
The engine's poison threshold is whatever `FORKRUN_RETRY_LIMIT`
says: `<0` never poisons, `0` poisons on first failure
(exactly-once), `N` poisons after `N` executions (default 3).
The Python parent passes the resolved value at every worker-init
site through the single point `_resolve_retry_limit()` — never a
hardcoded constant. Unparseable values fail closed (`ValueError`).
(F-PORT1.)

**Invariant (checkpoint ownership gate)**
A checkpoint from a foreign UID is never resumed silently; a
group/world-writable checkpoint is never resumed silently (the
Bash soft-reject is fail-closed in Python: there is no
interactive preview surface, so the TTY-less rule applies
always). `FORKRUN_TRUST_RESUME=1` bypasses both with a recorded
warning — same name/semantics as Bash. Parsing stays strict
regardless: the typed byte-coordinate ledger carries no code, so
there is no consent-gate surface to port (P15 N/A-BY-DESIGN).
(F-PORT2.)

**Invariant (batch-size line-wins)**
`lines=` + `bytes=` warns once (`UserWarning`) and line mode
wins with stdin delivery preserved (Bash `-L`-overrides-`-b`
parity) — never a silent pick, never a hard error. Zero/negative
values stay rejected. (F-PORT3.)

**Invariant (execution-environment pinning)**
Spawned commands are resolved at build time against the *system*
default `PATH` (`os.defpath`), never the caller's inherited
`PATH` — a CWD-planted binary must not execute (D10-class).
Unresolvable bare names keep their spelling so missing commands
still fail lazily at payload time (`SpawnError` → escrow →
poison). Slash-paths are realpath-normalized, never PATH-searched.
Plugin paths must contain `/` (absolute or explicit relative;
bare filenames resolve via CWD/`LD_LIBRARY_PATH`) and are
realpath-normalized. (F-PORT4.)

**Invariant (release version coherence)**
`release_check.py` verifies the *engine*, not just the package:
`META` names the release, the tree-built substrate reports it
(stale/unbuilt `"unknown"` fails), and the wheel-embedded `.so`
reports it by the same read path. (F-PORT5.)

**Standing guarantees (re-verified, no change needed)**
fd hygiene at every fork site (blanket `scrub_fds` + targeted
closes; fd 2 never redirected/closed — P5/P6); EOF 3-condition
order (`C1→C2→C3`, `continue`-not-`break`) on every completion
path (P21); PID-recycling no-kill (`ECHILD` ⇒ no `kill` — P23);
order/ack backpressure preserved with the signal pipe as a
separate wakeup channel (P11); empty input never forks a worker
(P19); degenerate edges byte-exact (empty/single/no-trailing-NL/
NUL/huge-line — F-PORT6); stale-horizon resume fails loud and
complete-stream resume is a clean no-op (P16).

**Structural N/A (named reasons, not gaps)**
No JIT/codegen surface (`NO-CODEGEN-IN-PYTHON`); no realtime
`-u` path (`framed-transport-invariant` — workers never write
stdout directly); exit codes are exceptions, not process exits
(`PYTHON-IS-IMPORTABLE-LIBRARY` — full taxonomy parity deferred
as D-PORT3); checkpoint filenames need no quoting layer
(`no-shell-interpolation`); non-NUMA paths have no indexer
process (`no-indexer-process`); materialized inputs need no
fallow (bounded by contract).

**Resolved by W-PORTDEFER (no deferred items remain)**
D-PORT3 cause-fidelity taxonomy (`exceptions.py`: signal classes
with `signo`/`bash_code`, opt-in `strict_poison` for exit-3
fidelity, 128+signo worker-death transport, mapping table in
TROUBLESHOOTING.md); D-PORT1 opt-in `signal_policy="checkpoint"`
(HUP/TERM + USR1-iff-PREEMPT for one run, restoration invariant,
Bash signal-wins precedence); D-PORT2 `fr_py_abort_reason()`
shim accessor (sanctioned additive read-only entry — engine
still frozen) with record/excuse/fatal wiring in all NUMA
watches, UMA scanner watches, and NUMA joins.

**Audit Rule**
❌ Any new worker-init call site that passes a literal retry
limit instead of `_resolve_retry_limit()`. ❌ Any resume path
that stats-or-parses before the ownership gate, or honors a new
bypass env name beside `FORKRUN_TRUST_RESUME`. ❌ Any executor
lookup (`spawn`/`plugin`/future) that searches the caller's
`PATH`/CWD. ❌ Any "different architecture" N/A without a named
structural reason and a PORT_AUDIT entry.

---

## 20. Ingress Memfd Position Is Undefined (F-PY-UMA1b)

**Invariant**
The file offset of the ingress memfd is not maintained by any
forkrun contract and must never be read or relied upon. All
access uses explicit offsets (`pread`/`pwrite`, offset-bearing
`sendfile`/`splice`/`copy_file_range`, `mmap` windows). Any new
code touching the ingress fd must follow this discipline —
positional `read`/`write`/offset-less syscalls on it are a
contract violation even when they appear to work.

**Origin**
F-PY-UMA1: the UMA scanner seeded its coordinate base from
`lseek(SEEK_CUR)` on the fork-shared ingress memfd and silently
dropped `[0, K)` whenever the position was nonzero (fixed by
unconditional base 0). W-MOVER then proved a live offset-mover
still exists on the current tree: 8-byte positional reads on the
shared ingress from `do_lockfree_claim`'s eventfd-drain path
(`sys_read(evfd_data_arr[my_numa_node], &v, 8)`), traced via
LD_PRELOAD (40K–1.5M per suite run, mostly EOF-spin, some
advancing), return-PC resolved into `do_lockfree_claim`,
per-event array capture showing the slot naming the ingress fd.
Parent-side sentry (1000+ samples): pre-fork always 0, movement
in worker-fork through teardown windows, always multiples of 8.
Harmless post-F-PY-UMA1 (nothing reads position; stray packets
are validated away; suite green) but real — and a latent hazard
to any future positional consumer. The fd-aliasing origin
(slot↔ingress number collision in forked children while the
parent layout verifies pristine) is carried as an explicit
residual; the engine-side hardening (fd-identity validation in
the claim path) needs engine changes and is halted per red
lines for owner decision. The scanner-side contract — never
read the position — holds regardless of what moves it.

**Enforced by**
Scanner base hardcoded 0 (`core_scanner_loop` entry re-establishes
it instead of querying); pre-fork `lseek(0)` at every materialized
spill site; the spill/chunk/scan/emit/plugin/tokenize paths all
use explicit offsets (audited); lock-in `test_mover.py`
(position-independence under a deliberately dirtied offset +
ten-sequential-maps head exactness).

**Audit Rule**
❌ Any `read`/`write`/`sendfile`/`splice` on the ingress fd
without an explicit offset argument. ❌ Any `lseek(SEEK_CUR)`
query of the ingress offset outside narrowly-scoped,
env-gated diagnostics. ❌ Any new consumer of ingress bytes
that is not `pread`/explicit-offset/`mmap`-window based.

---

## 21. Checklist Summary

If sections §1–21 above remain true, **forkrun is correct** — regardless of:
* batching heuristics (Pre-Flight Popcount, Geometric Fallback, or PID Steady-State)
* wake frequency
* NUMA placement
* worker churn
* input arrival rate (trickle or burst)

**Mental model reminder**  
Progress is irreversible. Locality is structural. Contention was designed away. Workers always claim exactly one slot. Gates read text. Data movers degrade. Environments are built, not cleared.

---

**See also:** `DESIGN.md` and `PHYSICS.md`
