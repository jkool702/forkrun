# forkrun Troubleshooting

## Bash exit code ↔ Python exception (D-PORT3 mapping table)

A Python library's contract is *exceptions*, not process exit
status — so parity with the Bash taxonomy means **cause
fidelity, not number fidelity**. All five live in
`forkrun.exceptions` (also re-exported at `forkrun.*`):

| Bash code | Python exception | Cause | Remedy |
|---|---|---|---|
| 130 (SIGINT, foreground-only) | `ForkrunInterrupted` (also a `KeyboardInterrupt`) | Ctrl-C / SIGINT in the parent | Re-run; resume from the checkpoint when `checkpoint_file=` was armed |
| 138 (SIGUSR1 under `FORKRUN_PREEMPT_MODE=1`) | `ForkrunPreempted` | Scheduler preemption notice | Checkpoint-and-requeue like any preemption; only raised under the opt-in `signal_policy="checkpoint"` when preemption mode is armed |
| 143 (SIGTERM; HUP aborts) | `ForkrunTerminated` | Operator/overlord TERM or HUP | Resume from the published checkpoint (raised *after* teardown + checkpoint) |
| 3 (poison-skip) | `ForkrunPoisonSkip` (`.count`) | Batches crossed the retry limit | Fix the payload/input and re-run the offending batches; raised only under opt-in `strict_poison=True` — the default stays warn-and-partial |
| 1 (faults), 42, 200/254 | plain `RuntimeError` (etc.) | Claim race, orphan-revert failure, trap-ACK timeout, worker crash, spawn/plugin errors | Read the message: it names the wid/batch/pipe; no signal cause exists to preserve |

`on_error` governs *payload* errors (retry/skip/fail-fast), not
pipeline aborts — aborts always raise, never return partial
results silently. Catching `RuntimeError` still catches
everything (all taxonomy classes derive from it, and
`ForkrunInterrupted` additionally satisfies
`except KeyboardInterrupt`).

## Empty results (`[]` or fewer lines than input)

Almost always one of these:

1. **Payload returned `None`.** `None` means "emit nothing"
   (by design). Return `b""` for an explicitly empty record.
2. **Payload raised on every batch.** Exceptions ride
   retry-then-poison: after the limit the batch is skipped
   with a stderr warning. Read stderr — the warning names
   the batch. Common cause: calling `.split()` on
   `batch.data` (it's a `memoryview` — convert first:
   `bytes(batch.data).split(b"\n")`).
3. **Workers < NUMA nodes.** Under `numa=fake=N` (or real
   multi-socket), `nodes="auto"` fans out to N rings and an
   unworked node's share is silently lost. Either pass
   `nodes=1` or size `workers >= nodes`.

## `RuntimeError: needs the NUMA substrate`

Multi-node requested but the loaded `.so` predates it:
rebuild (`make -f Makefile.substrate python-substrate`).
Under `FORKRUN_NO_V1=1` (which masks all fast-path
symbols), multi-node is refused for the same reason — pass
`nodes=1`.

## `RuntimeError: c_*_loop ... UMA-only / map()-only`

The C worker loops are envelope-gated on purpose
(`map()` + matching mode + UMA + materialized input).
Anything else raises loudly instead of silently running
slower. Use the default Python loop (same results).

## Hangs

- **Consumer never drains:** `stream()` backpressures by
  design — a consumer that stops reading stalls workers
  forever. Drain or abandon (close) the generator.
- **A worker runs forever:** your payload never returned
  (infinite loop). forkrun has no per-batch timeout (like
  bash `-X`) — Ctrl-C the parent; teardown kills strays.
- **Zero batches, workers idle:** input was empty (both
  memfds empty → instant EOF, `[]`). Check the source.

## Zombies / leaked processes

forkrun reaps every child before returning (abandon-safe
teardowns). If your monitor shows strays: you are looking
at a *daemon your payload forked* (supported — double-fork
and detach), or at another forkrun call still running in
the same process (calls serialize on a process-wide lock).

## Calling from threaded parents

**Read this before assuming a threaded host is fine. It is not.**

What is true: concurrent `run()`/`map()` calls are serialized
internally by `_RUN_LOCK`, so two forkrun invocations will not
interleave. That is all "supported" means here — it is a lock
around forkrun's own state, **not** a guarantee that forking a
multi-threaded process is safe.

What is not true: that arbitrary threaded-parent usage is
supported. `fork()` gives the child only the calling thread. Any
lock another thread held at that instant — the import lock, a
logging lock, an allocator lock, your own mutex — stays held
forever in the child, which then hangs. CPython warns about this
(`DeprecationWarning: ... multi-threaded, use of fork() ...`),
and that warning is **not** expected noise: it is the accurate
signal that this hazard applies to your program.

Practical guidance:

- **Single-threaded parent: fully supported.** No caveat.
- **Threaded parent: you own the risk.** forkrun warns once when
  it detects multiple threads. Set
  `FORKRUN_REQUIRE_SINGLE_THREADED=1` to make that condition
  FATAL instead of a warning, which is what you want in CI or in
  a service where a silent deadlock is worse than a refusal.
- **Pass payloads as callables**, not `"pkg.mod:func"` strings,
  from threaded parents. A string spec makes the forked worker
  `import` the module, and if another thread holds the import lock
  at fork time the child deadlocks on it.

If you need forkrun inside a threaded host, the robust shape is
to run it in a dedicated single-threaded process (a subprocess or
a dedicated worker thread that owns its own event loop) rather
than relying on the internal lock.

## `CUDA ... refusing to fork`

A live CUDA context exists in the parent. Fork would
corrupt driver state, so forkrun refuses. Fix: spawn
workers *before* initializing CUDA (GPU work belongs in
the parent/consumer). Importing torch alone is fine — the
guard fires on live contexts, not loaded libraries.

## Resume complaints

- `resume=`/`checkpoint_file=` with `orchestrator=False`
  (or outside `order="index"`, UMA, non-splice)
  raises `RuntimeError` — checkpoints need the C-orderer
  tracker; anything else would be silent loss.
- A stale horizon (checkpoint past EOF) fails loudly;
  resuming an already-complete stream is a clean no-op.

## Slow jobs

See [PERFORMANCE.md](PERFORMANCE.md) first. The usual
suspects, in order: payload-bound (profile it — the
framework owns <1% of cycles), `lines=100`-scale batching
(~40% loss vs adaptive), oversubscription past ~2× CPUs,
`streaming=True` on files that fit in memory anyway
(~2–3× CPU for the capability).

## Still stuck?

Reduce to the minimal reproducer (100 lines, `workers=1`,
`nodes=1`, `order="index"`, byte-compare against the
input) and check which of the above it violates. Nine
times out of ten it's the `memoryview` conversion or the
nodes/workers coverage rule.
