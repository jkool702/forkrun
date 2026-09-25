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
| Batch fails every attempt | Poisoned: skipped with a stderr warning, pipeline completes | Inspect the warning |
| `on_error="skip"` | Failed batches skipped immediately | Nothing |
| `on_error="fail-fast"` | First failure aborts the run | Fix the payload |

There is no success-path overhead for any of this (a few
cache-local stores per batch).

## What is NOT covered

- **Realtime output** (workers writing stdout directly):
  at-least-once — a crash can duplicate. Use the default
  collected paths for exactly-once delivery.
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

Requires `orchestrator=True, order="index"`, single node,
non-splice (the C-orderer paths — anything else raises
`RuntimeError` rather than checkpointing something it can't
track). `map()` preserves already-committed output in a
sidecar, so abort+resume is byte-identical to an
uninterrupted run. For `stream()`, persist what you consume:
engine commit is exactly-once, Python consumption is not.

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
