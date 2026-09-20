# forkrun Python frontend — v0.5.1 (W-PY15)

Minimum viable `forkrun.run()` over the C substrate via ctypes. No bash in
the path: Python drives the engine (claim → payload → ack) directly.

`forkrun.__version__` is `"0.5.1"`; `forkrun.__engine_version__` reports the
substrate build (e.g. `"v3.5.2"`, `"unknown"` when the `.so` isn't built).

## Build

```bash
make -f Makefile.substrate python-substrate
# Output: python/forkrun/libforkrun_python.so (gitignored)
```

The `.so` is built from `python/forkrun/_shim.c`, which textually includes
`forkrun_ring.c` (same TU, so the engine's statics/TLS are visible) and adds
non-static `fr_py_*` entry points. `forkrun_ring.c` itself is unmodified.

## Install (W-PY10)

```bash
pip install .            # builds the substrate, installs the wheel
```

- No `src/` move: `package_dir={"": "python"}` maps `python/forkrun/`
  to the wheel top-level; tests never ship (no `__init__.py` under
  `python/tests/`). Version single-sources from `__version__`.
- System build deps: `gcc make bash-devel` (Fedora; same rule as the
  canary — Debian has no bash-headers package). `setup.py` drives
  `Makefile.substrate` (single source of flags) with a documented
  gcc fallback.
- Linux-only: import raises `ImportError` off Linux (plan §4).
- No PyPI upload in this work order — local wheel (`pip wheel .`)
  only; reproducible-builds/signing gate the first PyPI release.

## Use

```python
import forkrun

def upper(batch):                      # batch: Batch (borrowed memoryview)
    return bytes(batch.data).upper()

forkrun.run(upper, "inputs.txt", workers=4)              # fire-and-forget
forkrun.run(upper, "inputs.txt", sink=on_batch)          # payload-side sink
results = forkrun.map(upper, "inputs.txt",               # batch-granular,
                      workers=4, order="index")          # ordered by batch_index
for r in forkrun.stream(upper, "inputs.txt"): ...        # TRUE v1 streaming:
                                                         # yields while workers run
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

- **Ordered streaming:** `stream()` yields completion order, or
  `batch_index` sequence with `order="index"` (parent-side reassembly;
  landed W-PY7).
- **Spawn/plugin v1 fast paths (W-PY13, landed):** C-level dispatch with
  v0 fallback — see Modes. Remaining: NUMA multi-node.
- **Resume UX, halt, TUI:** Stage 6 (demand-pulled).

## Modes

- `mode="python"` (default): payload is `"pkg.mod:func"` (imported
  post-fork in the worker) or a callable (fork-inherited, never pickled).
  Receives a `Batch`, returns `bytes`/`memoryview`/`str`/`None`.
  Output crosses via `fr_py_emit` (W-PY14): one C call writes the
  header + body with `writev` (zero-copy for `bytes` returns) and the
  signal; `None` emits no record, `b""` emits an empty one. Falls back
  to Python writes under `FORKRUN_NO_V1=1`.
- `mode="spawn"` (W-PY8, v1 in W-PY13): payload is a COMMAND (`str`
  split on whitespace, or `list` argv — use list form for anything
  quoting would be needed for). Each batch is spliced zero-copy from the
  ingress memfd to the command's stdin; stdout captured as the result.
  Non-zero exit / spawn failure → `SpawnError` → escrow → retry → poison
  (bash `-E` semantics); missing command exits 127 (shell convention,
  retryable — v0 parity). v1 dispatches in C (`fr_py_exec_spawn`:
  `posix_spawnp` + concurrent poll pump, ~10µs overhead vs v0's ~350µs
  `subprocess`); v0 remains as fallback (pre-v1 `.so`,
  `FORKRUN_NO_V1=1`, `sink=` present, or discard mode). Measured
  (i9-7940X): 2.1× at small batches (1.05M vs 0.49M lines/s,
  `lines=100`); parity at adaptive batching (~24M both — command-bound).
  v1 has no per-batch timeout (waits like bash `-X`; v0 keeps its 30s).
- `mode="plugin"`: payload is `"path:function"` (C `.so` entry point).
  v1 (W-PY13) dispatches in C (`fr_py_plugin_call`) through the FROZEN
  engine ABI (`forkrun_ctx`, 128B, dialect negotiated from the plugin's
  `forkrun_use_ctx` exactly like `ring_call`): the plugin reads the
  input window zero-copy (RAW borrowed window or `pread` on `fd_in`)
  and writes stdout, which the shim stages and frames. **A bash `-C`
  plugin works from Python unchanged and vice versa** (ABI unification).
  v0 (72B `fr_py_plugin_ctx` ctypes convention) remains for plugins
  WITHOUT a `forkrun_use_ctx` export — selected by parent-side probe,
  never guessed. Measured: transform throughput ≈ v0 (0.8–1× on the
  uppercase micro-bench — the capture staging costs what ctypes saves);
  v1's wins are unification + zero-copy input + no per-batch input
  allocation. Non-zero return → escrow → retry → poison, like all
  payload errors.

```python
forkrun.map("./myplugin.so:process", "data.txt", mode="plugin")
```

```python
forkrun.map("gzip -c", "logs.txt", mode="spawn")
forkrun.map(["sed", "s/old/new/"], "data.txt", mode="spawn")
```

## CUDA Policy (v0, W-PY5)

Python workers are **CPU-only by default**. forkrun refuses to fork if a
live CUDA context exists in the parent (fork would corrupt driver state).

- **Importing torch is fine** — the guard (`dlopen(RTLD_NOLOAD)` +
  `cuCtxGetCurrent`, `/proc/self/maps` fallback only when inconclusive)
  fires on live contexts, not loaded libraries, so CUDA-virgin scripts
  pass untaxed.
- **Initializing CUDA before `run()` is refused** with an actionable
  error naming the fix (spawn workers first, then init CUDA; GPU work
  belongs in the parent/consumer).
- Over-refusal is the safe direction; under-refusal causes UB. An
  early-spawn escape hatch is demand-pulled Stage 6+, not a v0 feature.

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

## Result crossing (emitter, §3.9b v0.5 → v1)

- The parent creates one **output memfd per worker pre-fork** (a memfd
  created post-fork would exist only in the child's fd table); workers
  inherit them and write keyed records
  (`batch_idx u64 LE, length u64 LE, payload bytes`) via copy-on-return.
- The emitter **transports, it does not order**: `map(order="index")`
  reassembles parent-side over `batch_index` keys. No Python pipe/queue
  ever carries payload bytes; no pickle.
- **v1 streaming** (`stream()`): after each record the worker emits a
  16-byte `(wid, batch_idx)` signal (indices only) down a pipe; the parent
  `select()`s, `pread()`s the new bytes incrementally, and yields while
  workers run. A slow consumer fills the pipe → workers block in the
  signal write holding unacked batches → claims stop (backpressure).
  `map()` stays on the v0.5 post-completion drain; `run()` (discard /
  worker-side sink) needs no drain at all.
- **Pipe capacities (W-PY15):** the streaming signal pipe is 1MB
  (65536 outstanding 16B signals vs 4096 at the 64KB default), and the
  spawn stdin/stdout pipes are 1MB (batch-sized transfers without
  intermediate blocking) — all best-effort via `F_SETPIPE_SZ` with
  silent fallback (`forkrun/_pipes.py`). The engine ack pipe stays 4KB
  by design (H3 backpressure invariant); escrow/death pipes untouched.
- **Ordered streaming** (`stream(order="index")`): parent-side reassembly
  over `batch_idx` keys (bounded out-of-order buffer; poisoned-batch holes
  flush sorted at EOF — brief head-of-line blocking behind a hole is
  inherent). `order="none"` (default) yields completion order.
- **C-level emit (W-PY14):** `fr_py_emit` replaces header pack + two
  writes + signal pack/write with one call (`writev`, zero-copy `bytes`).
  Measured ≈ v0 (±noise) — the remaining cost is payload-side copies
  (`bytes(data).upper()`), not output syscalls; `map()`/`run()` already
  skipped signals since W-PY7, so the only real saving is one syscall
  per batch. Kept as permanent infra (fewer syscalls, exact v0
  semantics incl. `None`-vs-`b""`).

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
