# forkrun Configuration

Every knob, what it does, and when to touch it. Defaults are
right for most jobs — the common tuning path is `workers`
first, `lines` second, everything else rarely.

## workers (default: auto)

Number of parallel worker processes. Default is the CPU
count (capped at 64). Rules of thumb:

- CPU-bound Python: `workers = os.cpu_count()`.
- One worker per NUMA node minimum — a node with no worker
  never has its ring claimed (see [NUMA.md](NUMA.md)).
- More workers than ~2× CPUs oversubscribes (measured
  plateau 14→28 on medium Python).

## order: "none" (default) vs "index"

- `"none"`: results in worker-completion order (fastest —
  no reassembly).
- `"index"`: input (byte) order. `map()` sorts parent-side;
  `stream()` reassembles live through a bounded buffer (a
  missing batch briefly holds the head of line — inherent).
  On ordered paths, poisoned batches flush sorted at EOF.

## lines / bytes (default: adaptive)

Batch size, mutually exclusive. The adaptive default already
sits in the sweet spot (measured: `lines=1k–10k`; `lines=100`
loses ~40%, `lines=50k+` loses ~35% to starvation).
`splice` mode takes `bytes=` only.

## on_error: "retry" (default) / "skip" / "fail-fast"

- `"retry"`: failed batch is retried (escrow, kills+1),
  then poison-skipped after the retry limit (default 3,
  via `FORKRUN_RETRY_LIMIT` env). The pipeline continues.
- `"skip"`: failed batches are skipped immediately.
- `"fail-fast"`: first failure aborts the whole run
  (global abort — blocked claimants observe it).

Process death (SIGSEGV/SIGKILL/OOM) always takes the
resurrect path (revert + escrow + respawn) regardless of
`on_error`. Details: [FAULT_TOLERANCE.md](FAULT_TOLERANCE.md).

## nodes: "auto" (default) / 1 / N / "0,1" / "@N"

NUMA topology. `"auto"` follows the boot (single socket →
single ring, unchanged behavior). `1` forces UMA.
`N` takes the first N physical nodes, `"0,1"` names them,
`"@N"` forces N logical nodes (fake multi-node for testing,
like this box's `numa=fake=4`). Full guide:
[NUMA.md](NUMA.md).

## streaming: None (default) / True / False

- `None`: fifo/socket sources stream, files materialize.
- `True`: bounded-ingress streaming ingest (reaper punches
  holes behind the acked prefix) — TB-scale/unbounded
  sources, ~2–3× CPU cost at medium scale for the capability.
- `False`: force the materialized path.

## orchestrator: None (default) / True / False

- `True`: reactor supervision — death pipes, bounded respawn
  (cap 3/slot), trap-ACK confirmation, C orderer for
  `order="index"`. Additive: identical results, stronger
  fault tolerance. Required for `resume=`/`checkpoint_file=`.
- Default/`False`: fork-and-wait (same-process retry covers
  payload errors; process death of a worker is best-effort).

## sink (run() only, default None)

`None` discards results; a callable runs **in the worker**
(zero crossing) as `sink(meta, result)` per batch.

## c_drain / c_worker_loop / c_spawn_loop (all opt-in, default False)

- `c_drain=True`: forked C loop moves result bytes
  (`map`/`stream`). Byte-identical; measured 0.7–1.0× of the
  legacy drain (the parent must parse every record either
  way) — opt in only with a measured reason.
- `c_worker_loop=True`: C worker loop for `map()` +
  `mode="plugin"` (dialect-1/2, UMA, materialized only).
- `c_spawn_loop=True`: C worker loop for `map()` +
  `mode="spawn"` (UMA, materialized only).
- Anything outside each flag's envelope raises loudly —
  never silently falls back.

## resume / checkpoint_file (C-orderer paths only)

`map()`/`stream()` with `orchestrator=True, order="index"`
(UMA, non-splice) accept `resume=<path>` (resume FROM a
checkpoint) and `checkpoint_file=<path>` (publish TO on
abort). Anything else raises `RuntimeError` — a checkpoint
without a tracker would be silent loss, so it is refused.
Checkpoints are byte coordinates; `map()` additionally
preserves committed output in a sidecar. Engine commit is
exactly-once; Python consumption is not (persist consumed
results yourself for end-to-end exactly-once).
