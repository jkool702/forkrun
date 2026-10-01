# forkrun Fault Tolerance (user guide)

Crash recovery is structural, not a feature flag. Every batch
runs inside a per-worker transaction: the worker publishes at
claim and clears at ack, and the **parent** recovers any death
— including `SIGKILL` and `SIGSEGV`, which run no code.

## What happens automatically

| Failure | Behavior | You do |
|---|---|---|
| Python exception in payload | Batch retried (escrow, kills+1), then poison-skipped after the limit | Nothing |
| Worker SIGSEGV / SIGKILL / OOM | Output reverted, batch re-queued, worker respawned, stream continues | Nothing |
| Spawn command exits non-zero | Same retry path as a Python error | Nothing |
| Payload with side effects (`db.insert`, file writes) | **At-least-once**: the payload may run up to `FORKRUN_RETRY_LIMIT` times per batch (default 3), plus one re-execution per worker-death recovery of its batch | Make payloads idempotent |
| Batch fails every attempt | Poisoned: skipped with a stderr warning, pipeline completes | Inspect the warning |
| `on_error="skip"` | Failed batches skipped immediately | Nothing |
| `on_error="fail-fast"` | First failure aborts the run | Fix the payload |

There is no success-path overhead for any of this (a few
cache-local stores per batch).

## What is NOT covered

- **Payload side effects are at-least-once, not exactly-once.**
  A batch whose payload raises is retried up to `FORKRUN_RETRY_LIMIT`
  times (default 3 — measured: 10 batches with one always-failing
  batch invoke the payload 12 times, the failing batch 3 times), and
  a batch orphaned by a worker death re-executes once on the recovery
  worker. `map(lambda b: db.insert(...))` triple-inserts on a
  transient. For exactly-once side effects, use idempotency keys or
  checkpoint-anchored deduplication.
- **In-worker `sink=` side effects** (the Python realtime
  path): at-least-once — the sink runs before commit, so a
  crash between sink and ack re-runs it. Use the default
  collected paths for exactly-once delivery, and keep sinks
  idempotent.
- **Ambiguous-window deaths** (dying mid-claim or mid-ack):
  the ticket can't be attributed safely, so the run aborts
  loudly instead of risking loss/duplication — then you
  `resume=` from the checkpoint (below).
- **Scanner/indexer death**: the pipeline aborts and writes
  a checkpoint.
- **Input source failure**: the pipeline aborts.

## Retry tuning

```python
forkrun.map(payload, source, on_error="retry")  # default
```

The retry limit defaults to 3 (`FORKRUN_RETRY_LIMIT` env to
change it; `<0` retries forever; `0` poisons immediately).

## Resume after an abort

On abort with `checkpoint_file=`, the parent publishes byte
coordinates of the committed frontier. Resume from them:

```python
# First attempt aborts and writes "run.ckpt"...
forkrun.map(payload, source, orchestrator=True, order="index",
            checkpoint_file="run.ckpt")
# ...resume exactly where it stopped:
forkrun.map(payload, source, orchestrator=True, order="index",
            resume="run.ckpt")
```

Requires the reactor path (the default — `orchestrator=False`
rejects), `order="index"`, single node,
non-splice (the C-orderer paths — anything else raises
`RuntimeError` rather than checkpointing something it can't
track). `map()` preserves already-committed output in a
sidecar, so abort+resume is byte-identical to an
uninterrupted run. For `stream()`, persist what you consume:
engine commit is exactly-once, Python consumption is not.

## Operator signals (D-PORT1): opt-in `signal_policy`

By default forkrun installs **no** signal handlers — a library
must not capture its host's signals. Ctrl-C in a foreground
script raises through as `ForkrunInterrupted` (still a
`KeyboardInterrupt`); anything else keeps its ambient
disposition.

Pass `signal_policy="checkpoint"` (run/map/stream) when you want
Bash-style graceful abort: HUP/TERM handlers are installed for
the run (plus USR1, but only under `FORKRUN_PREEMPT_MODE=1` —
the Bash conditional trap), an operator signal aborts the
engine, the armed W-PY22 checkpoint publishes, and the run
raises `ForkrunTerminated` / `ForkrunPreempted` (Bash 143/138)
*after* teardown. Prior handlers are always restored, even on
failure. SIGINT is never captured.

```python
try:
    forkrun.map(payload, src, order="index", orchestrator=True,
                checkpoint_file="run.ckpt",
                signal_policy="checkpoint")
except forkrun.ForkrunTerminated:
    results = forkrun.map(payload, src, order="index",
                          orchestrator=True, resume="run.ckpt")
```

Without `checkpoint_file=` (or off C-orderer paths) the signal
still aborts and raises — there is just no file to resume from.

## Operational notes

- Deaths are reported on stderr (`N worker death(s)
  recovered via respawn`) — a few per run is routine; a
  storm means your payload is crashing (check it, not
  forkrun).
- The respawn cap (3 per worker slot) bounds genuine crash
  loops into a loud abort instead of an infinite restart
  cycle.
- `KeyboardInterrupt` inside your payload is a payload error
  (retry path), not a global abort. Ctrl-C the parent to
  stop the run.
