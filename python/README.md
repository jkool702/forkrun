# forkrun Python frontend — v0.2 (W-PY2)

Minimum viable `forkrun.run()` over the C substrate via ctypes. No bash in
the path: Python drives the engine (claim → payload → ack) directly.

`forkrun.__version__` is `"0.2.0"`; `forkrun.__engine_version__` reports the
substrate build (e.g. `"v3.5.2"`, `"unknown"` when the `.so` isn't built).

## Build

```bash
make -f Makefile.substrate python-substrate
# Output: python/forkrun/libforkrun_python.so (gitignored)
```

The `.so` is built from `python/forkrun/_shim.c`, which textually includes
`forkrun_ring.c` (same TU, so the engine's statics/TLS are visible) and adds
non-static `fr_py_*` entry points. `forkrun_ring.c` itself is unmodified.

## Use

```python
import forkrun

def upper(batch):                      # batch: Batch (borrowed memoryview)
    return bytes(batch.data).upper()

forkrun.run(upper, "inputs.txt", workers=4)              # fire-and-forget
forkrun.run(upper, "inputs.txt", sink=on_batch)          # payload-side sink
results = forkrun.map(upper, "inputs.txt",               # batch-granular,
                      workers=4, order="index")          # ordered by batch_index
for r in forkrun.stream(upper, "inputs.txt"): ...        # v0: over collected
```

- `payload`: `"pkg.mod:func"` (imported post-fork in the worker — keeps the
  parent virgin of native imports) or a callable (fork-inherited, never
  pickled). Receives a `Batch`, returns `bytes`/`memoryview`/`str`/`None`.
- `source`: path | fd | pipe/socket object. v0.5 **materializes** the input
  into an ingress memfd and mmaps it whole: bounded inputs only.
- `Batch.data`: borrowed `memoryview` (zero-copy MAP_SHARED window). Valid
  during the payload call only; `batch.copy()` persists. `line_count` is
  `None` in byte mode. `offsets` are lazy absolute plane coordinates.
- `on_error`: `"retry"` (escrow retry then poison-skip, bash `-E` analogue),
  `"skip"`, `"fail-fast"` (global abort, workers exit non-zero).
- Modes `spawn`/`plugin`, multi-node, ordered emitter pipe, resume: not in
  v0 (`NotImplementedError`).
- Workers are single-threaded by contract: payloads must not spawn threads
  (a `RuntimeWarning` fires at ack if they do); return bytes and
  parallelize in the parent instead.

## Upgrade path (v0 → v1)

- **True PIPE streaming (v1 emitter):** v0.5 drains output memfds after
  workers complete; v1 drains while they run, closing the hydraulic
  backpressure loop (parent reads slowly → pipe fills → acks block →
  workers stall → ingest yields).
- **Ordered output:** parent-side reassembly over `batch_index` exists in
  `map(order="index")`; the C orderer path lands with the emitter.
- **NUMA multi-node / spawn / plugin modes:** Stage 5 (API already accepts
  the surface; execution stages `NotImplementedError`).
- **Resume UX, halt, TUI:** Stage 6 (demand-pulled).

## Robustness (W-PY4 characterization)

- **Faults:** Python exceptions → escrow retry → poison-skip, pipeline
  continues. True process death (segfault) kills the worker without a
  deposit: survivors drain the rest, the parent raises `RuntimeError`
  (no reactor/respawn in v0), no zombies. `KeyboardInterrupt` inside a
  payload is a payload error (retry path), not a global abort.
- **Reuse:** sequential and thread-concurrent `run()` calls in one process
  are correct (a process-wide lock serializes engine access; fd counts
  stable across 10 runs).
- **Layer 3 (numpy past invalidation):** measured intact for the run's
  duration (worker mmap held, no fallow) — an observation, not a contract.
  v1 fallow/windowing may zero it; never depend on intactness.
- **RSS:** parent peak is flat across 4x stream growth with no output
  collection, and output-sized under `map` (collect-all); constant-memory
  PIPE drain is v1.
- **Daemon payloads:** double-forked daemons survive without blocking
  `waitpid`, but inherit the full worker fd set in v0 (no scrubbing yet —
  recorded baseline for v1).

## Result crossing (emitter, §3.9b v0.5)

- The parent creates one **output memfd per worker pre-fork** (a memfd
  created post-fork would exist only in the child's fd table); workers
  inherit them and write keyed records
  (`batch_idx u64 LE, length u64 LE, payload bytes`) via copy-on-return.
- The emitter **transports, it does not order**: `map(order="index")`
  reassembles parent-side over `batch_index` keys. No Python pipe/queue
  ever carries payload bytes; no pickle.
- v0.5 drains after workers complete (bounded by OUTPUT size). True PIPE
  streaming — parent drains while workers run, closing the hydraulic
  backpressure loop — is v1.

## Layout

- `forkrun/__init__.py` — `run() / map() / stream()` (§3.0) + `Batch`.
- `forkrun/_api.py` — signature validation incl. source/sink plumbing.
- `forkrun/_batch.py` — `Batch` (§3.5) with claim→invalidate→ack lifetime.
- `forkrun/_bindings.py` — ctypes loader + `FrPyBatch` + `fr_py_*` signatures.
- `forkrun/_shim.c` — Python-facing C entry points (new file; engine frozen).
- `forkrun/run.py` — parent orchestration (init/spill/scan/fork/wait).
- `forkrun/_worker.py` — forked claim/payload/ack loop (`os._exit` only).
- `stage0_harness.py` — table schema + surface check.
- `tests/test_api_surface.py` — engine-free validation tests.
- `tests/test_v0.py` — v0 engine tests (need the built `.so`).

## Key contracts (v1.3)

- `source ∈ {path, fd, pipe/socket}` — iterables/generators rejected;
  Python is never an input pump.
- `sink=None` → discard (v0); callable → payload-side sink in the worker.
- `mode="python"`, `order ∈ {none, index}` (`map` reorders parent-side).
- Fork before threads; `os._exit()` in workers; bytes/memoryview default;
  never pickle; no bash subprocess.
