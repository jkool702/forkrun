### `RESILIENCE_PROTOCOL.md`

# FORKRUN RESILIENCE PROTOCOL

This document defines the formal mechanisms by which `forkrun` guarantees **Exactly-Once delivery semantics** and **automatic self-healing** across transient, persistent, and catastrophic failures. 

Unlike traditional HPC resilience models (e.g., Checkpoint/Restart or Write-Ahead Logs) that impose a constant and significant performance tax, `forkrun` utilizes **Optimistic Execution**. The hot path contains zero state-saving overhead. Failure detection is delegated entirely to the Linux kernel's file-descriptor management and hardware interrupts, ensuring the cost of resilience is strictly zero until a fault physically occurs.

---

## §1. Failure Detection: The "Death Pipe" Reactor

To detect worker deaths instantly and reliably—even uncatchable signals like `SIGKILL` (OOM killer) or `SIGSEGV` (Segmentation Fault)—`forkrun` leverages the Linux kernel's native process teardown physics.

1. **The Death Pipe:** Immediately before spawning a worker, the orchestrator opens an anonymous pipe. The parent process holds the read end, and the child process (worker) inherits the write end. The parent immediately closes its copy of the write end.
2. **The Kernel Trigger:** If the worker process dies by *any* means, the kernel physically destroys its task struct and decrements the reference counts on its open file descriptors. The write end of the pipe is destroyed. 
3. **The `POLLHUP` Event:** This kernel-level teardown instantly triggers a `POLLHUP` event on the parent's read end.
4. **The `ring_poll` Reactor:** The orchestrator's `ring_poll` event multiplexer catches this `POLLHUP`, instantly notifying the Bash parent that a specific Worker ID (`wID`) has died.

This guarantees absolute, immediate failure detection without requiring the orchestrator to actively ping or `wait()` on worker PIDs in a polling loop.

---

## §2. Transient Failure: Parent-Side Transaction Recovery (W-PY29)

Every batch runs inside a per-worker transaction record (`WorkerTxn`,
one 128B cache line per worker in MAP_SHARED `GlobalState`). The
worker publishes at claim and clears at ack; the PARENT recovers on
any death. The worker's EXIT trap is cleanup-only (it must never
escrow — that would double-deposit).

### 2.1 The 4-State Machine

```
                    claim
IDLE ─────────────→ CLAIMING ────── claim failed (EOF/abort) ─────→ IDLE
                       │                      (only legal backward edge)
                       │ successful publication (release store, LAST)
                       ▼
                    CLAIMED
                       │
                       │ begin ack side effects
                       ▼
                 COMMITTING
                       │
                       │ all ack side effects complete
                       ▼
                     IDLE
```

Happy-path cost is four cache-local release stores (~2ns total). No
CAS, no fences beyond the publish/clear release-acquire pair, no
syscalls on the claim path.

### 2.2 Output Rollback Without lseek

Each worker holds a TLS `worker_output_end` cursor: the byte position
right after the most recently completed batch. It is initialized once
per worker (fresh or respawned) from the output fd's live position
(the only cursor `lseek`), snapshotted as `output_start` at claim,
and advanced only after a COMPLETE emit succeeds — never during
partial emission. Recovery truncates regular files to `output_start`
(`ftruncate` + `lseek`); pipes are at-least-once (guarded by
`S_ISREG`, never grown).

### 2.3 The Escrow Deposit (Parent-Side)

Recovery deposits the orphan batch metadata into the lock-free Escrow
side-channel with `num_kills + 1`, routed to the dead worker's NUMA
node (locality survives death). The first idle worker re-claims it
(Escrow Priority Inversion); the poison threshold converts loops
into skips (§3). Both reactors call recovery for EVERY death,
including exit 0 — the C state machine classifies:

| State + death | Decision |
|---|---|
| `IDLE` + exit 0, or error at EOF | NORMAL_EXIT (free slot) |
| `IDLE` + error mid-stream | NO_BATCH (respawn, nothing lost) |
| `CLAIMING` + any death | RACE → abort/resume (ticket unattributable) |
| `CLAIMED`, already committed | ALREADY_DONE (clear, respawn/free) |
| `CLAIMED`, orphan, error exit | RECOVERED (revert + escrow + respawn) |
| `CLAIMED`, orphan, exit 0 | FATAL (worker bug — abort) |
| `COMMITTING` + any death | RACE → abort/resume (commit ambiguous) |

---

## §3. Persistent Failure: The Poison Pill

If a specific batch of data is fundamentally malformed, it will persistently kill any worker that attempts to process it. To prevent an infinite death-loop, `forkrun` implements a Poison Pill threshold.

1. **The Threshold Evaluation:** When a worker claims a batch from the Escrow pipe, it reads the `num_kills` counter. 
2. **The Poison Declaration:** If `num_kills` exceeds the user-defined `FORKRUN_RETRY_LIMIT` (default: 3), the worker sets a `RING_POISONED` flag.
3. **The Safe Skip:** The worker skips processing the batch entirely. It acknowledges (`ring_ack`) the batch to ensure global pipeline ordering continues, prints a warning to `stderr`, and alerts the orchestrator.
4. **The Global State:** The orchestrator records the poisoned batch index and alters the final pipeline exit code to `3` to explicitly notify the user of partial data loss. 

### 3.1 Final-Attempt Coredumps (W-PY30)

Coredumps are disabled by default on every worker (soft
`RLIMIT_CORE` 0 at startup; the generous hard limit is preserved so
re-enabling needs no privilege). They are armed for exactly one
batch execution: the final allowed escrow attempt — the running
attempt with `num_kills + 1 == RETRY_LIMIT`, whose failure poisons
the batch. Success, poison-skip, and soft-fail (escrow deposit)
paths disarm, so the enabled limit never leaks into later batches.
A death in the armed window produces exactly one core per poisoned
batch; batches the auto-retry saves never dump. `coredump_filter`
is pinned to `0x31` (anonymous-private + ELF headers + hugetlb-private) so the dump
excludes the multi-GB shared ingress arenas. Accepted cost: the
dump delays death-pipe visibility on final-attempt crashes — but
that batch is being poisoned regardless, so the latency never
delays a save. 

---

## §4. Catastrophic Failure: Conservative Abort + Seqlock Ledger

A `CLAIMING` or `COMMITTING` death (§2.3, RACE) cannot be recovered
locally: the ticket is unattributable (claim race) or the commit is
ambiguous (ack race — re-execution could double-emit). The reactor
aborts the run and the Seqlock ledger below carries the resume.

### 4.1 No Grace Period

There is no trap-ACK wait and no timeout: recovery runs
synchronously in the death handler (revert + escrow deposit are a few
microseconds), so every death is classified the moment the death pipe
fires. `TRAP_ACK` carries poison-skip notices only.

### 4.2 The Seqlock Ledger
The `ring_order` thread acts as a deterministic observer. As batches successfully complete, `ring_order` merges them. Because batches finish out of order, the leading edge of completed work is "jagged." 
`ring_order` maintains a strict, Seqlock-protected ledger (`g_state`) containing:
* A continuous `resume_horizon` (the absolute input byte offset where all prior data is guaranteed perfectly sequential and complete).
* An array of `IntervalNodes` describing the "jagged edge" of out-of-order completed batches ahead of the horizon.
* The exact byte count successfully written to standard out.

### 4.3 Checkpoint Generation & Resumption
Upon `ring_abort`, the orchestrator dumps this Seqlock ledger into a physical `.forkrun_resume` file, along with the original CLI arguments and exported functions/variables. 

When the user restarts the pipeline with `--resume .forkrun_resume`:
1. The user truncates their output file to the exact safe byte count specified in the crash message.
2. `forkrun` reads the jagged-edge ledger.
3. As the scanner processes the input stream, it physically bypasses all byte offsets contained within the `resume_horizon` and the `resume_jagged` intervals, passing only uncompleted data to the workers.

---

## §5. Execution & Delivery Guarantees

Because of the architectural separation of payload execution (Workers) and sequential observation (`ring_order`), `forkrun` guarantees distinct semantics for both *execution* (how many times a command runs) and *delivery* (how output is committed).

### 5.1 Execution Guarantees
The engine guarantees **Bounded At-Least-Once Execution** by default. 
* A batch is executed until it either succeeds or exceeds the `FORKRUN_RETRY_LIMIT` (default: 3). 
* Reaching the poison threshold explicitly fulfills the pipeline's execution contract for that batch. The orchestrator permanently acknowledges it and moves the global index forward.
* **Configurable Exactly-Once Execution:** Users can enforce strict exactly-once execution (no retries) by setting `FORKRUN_RETRY_LIMIT=0`. In this configuration, a failed batch is immediately poisoned, and no payload will ever be run on the same data twice.
* **Unbounded Execution:** Setting `FORKRUN_RETRY_LIMIT < 0` disables the poison pill, ensuring infinite retries until the batch succeeds.

### 5.2 Output Delivery Guarantees
*Preconditions:* output must go to a seekable file (truncation is impossible on pipes/terminals — those downgrade to at-least-once); the user must truncate to the byte count in the crash message before resuming; and the orchestrator must survive long enough to write the checkpoint (SIGKILL to `frun` itself yields no checkpoint — SIGTERM/SIGINT/SIGHUP and SLURM USR1 with `FORKRUN_PREEMPT_MODE` are trapped and checkpointed).

* **Ordered (`-k`) & Buffered (`--buffered`) Modes: EXACTLY-ONCE DELIVERY.**
  Because partial output is physically reverted (`ftruncate` to the
  transaction cursor) by parent-side recovery on any crash, and
  because ambiguous-window crashes abort into a mathematically
  absolute byte-coordinate resumption, surviving data is guaranteed
  to be committed to the final output stream exactly once. 
* **Realtime (`-u`) Mode: AT-LEAST-ONCE DELIVERY (NOT RECOMMENDED).**
  Workers write directly to `stdout`, so `forkrun` cannot recall bytes on a crash (resuming produces duplicates). Furthermore, realtime mode risks severely scrambled output (byte interleaving) and kernel lock contention. Use `--buffered` or `-k` instead.

---

## §6. Security Sandbox & Provenance Model

Because resume files dictate commands and environment restoration, `forkrun` enforces a strict 3-layer security model to prevent code execution vulnerabilities when resuming in shared cluster scratch directories:

1. **Layer 1 (Provenance & Permission Gate):** UID ownership and permission check (`8#022`).
2. **Layer 2 (Restricted Subshell Sandbox):** `env -i PATH='' bash --restricted` execution, function wiping, and round-trip variable serialization verification.
3. **Layer 3 (Authorization Decision Gate):** Double-token frame split; custom setup commands and functions are evaluated only after interactive user authorization.

See [`SECURITY.md`](SECURITY.md) for the complete security specification.

---

## §7. Verified Envelopes: Streaming + NUMA Tier-3 Recovery (W-PY34)

§2–§4 describe the mechanism. This section records where recovery
is *verified by test* (not just designed), and the topology
preconditions the verification rests on. Verification order: no
engine or recovery-code changes were needed — the WorkerTxn
architecture covered streaming and multi-node NUMA as designed.

### 7.1 Streaming recovery (UMA) — `python/tests/test_streaming_recovery.py`

Worker death DURING an active `stream()` drain recovers exactly
like death during `map()`: the reactor's death-pipe handler calls
`fr_py_recover_worker()` synchronously inside `reactor_loop`
(between drain bursts — `DRAIN_BURST` bounds detection latency),
the orphan batch is reverted + escrowed, the respawned generation
re-processes it, and the drain loop yields it. The other workers
never pause. Verified (all with `orchestrator=True`, `nodes=1`):

- SIGSEGV / SIGKILL mid-stream, `order="none"` and
  `order="index"`: stream continues, output complete, recovered
  batch exactly once (Counter equality, plus a blob-uniqueness
  gate against double-emit).
- Two simultaneous deaths at different batches: both recovered.
- Ordered streaming: the reassembly buffer holds the gap; the
  late batch lands in its correct position (byte-exact
  reconstruction).
- Slow consumer + crash: recovery completes with bounded parent
  memory (streaming holds only the in-flight window).

### 7.2 NUMA recovery (`nodes="@2"`) — `python/tests/test_numa_recovery.py`

Cross-node recovery works because every routing decision keys off
the dead worker's node (`txn->node`), never the parent's:

- Crash under `@2`: parent on node 0 reads `WorkerTxn[wid]` from
  MAP_SHARED `GlobalState`, deposits to `fd_escrow_w[1]`, respawns
  pinned to node 1 (`fr_py_worker_init(wid, node, ...)`); the new
  generation claims from node 1's escrow. Output byte-exact vs a
  healthy `@2` run (SIGSEGV and SIGKILL, map and stream).
- Respawn node stability is structural: `wid_to_node` assigns
  contiguous per-node blocks once per run, so a respawned wid
  reuses its node's memfd, ring, and escrow pipe (locked in by
  unit test).
- Combined streaming + NUMA + crash (both orders): stream
  continues, complete output, exact order for `order="index"`.

### 7.3 Topology preconditions (read before operating NUMA)

1. **Workers must cover every node** (`workers >= nodes`).
   Rings are born-local and workers claim locally only (stealing
   is scanner-side); a node with no worker never has its ring
   claimed, and its share of the input is silently lost. The
   reactor does not (and cannot cheaply) rebalance this — size
   the pool to the topology.
2. **`nodes="auto"` follows the boot topology.** Booted with
   `numa=fake=N`, auto resolves to N nodes and every call takes
   the NUMA pipeline. Single-node-authored tests and scripts
   (workers < N, UMA batching assumptions) must pass `nodes=1`
   explicitly under fake NUMA. This is an operating fact, not a
   recovery bug: the W-PY34 suites pin `nodes=1` (streaming) and
   `nodes="@2"` (NUMA) for exactly this reason.
3. **NUMA batch granularity varies run to run** (per-node rings
   batch independently, and a crash shifts timing). Correctness
   comparisons across NUMA runs must be over line multisets or
   joined bytes — never over blob identity. (UMA batching is
   deterministic: single ring, pre-fork scan.)

### 7.4 Explicitly NOT covered

- Recovery in `mode="spawn"` / `mode="plugin"` streaming
  executors (same WorkerTxn mechanism, no Tier-3 tests written).
- Realtime (`-u`) delivery (at-least-once by physics, §5.2).
- Scheduling work onto unworked nodes (see 7.3.1 — documented
  constraint, not a tested path).

