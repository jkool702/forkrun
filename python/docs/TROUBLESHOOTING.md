# forkrun Troubleshooting

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

Concurrent `run()`/`map()` calls from threads are supported
(serialized internally), and you will see CPython's
`DeprecationWarning: ... multi-threaded, use of fork() ...`
when workers fork — that warning is expected noise, not a
failure. One real caveat: pass payloads as **callables**,
not `"pkg.mod:func"` strings, from threaded parents. A
string spec makes the forked worker `import` the module, and
if another thread holds the import lock at fork time the
child can deadlock. (Single-threaded parents are unaffected
— the import happens post-fork with no contention.)

## `CUDA ... refusing to fork`

A live CUDA context exists in the parent. Fork would
corrupt driver state, so forkrun refuses. Fix: spawn
workers *before* initializing CUDA (GPU work belongs in
the parent/consumer). Importing torch alone is fine — the
guard fires on live contexts, not loaded libraries.

## Resume complaints

- `resume=`/`checkpoint_file=` outside
  `orchestrator=True, order="index"`, UMA, non-splice
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
