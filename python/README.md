# forkrun Python frontend — Stage 0 (v1.3 plan)

This directory holds the **shipping API surface** the Stage 0
falsification gate measures, plus the harness skeleton.

## Layout

- `forkrun/__init__.py` — `run() / map() / stream()` (§3.0). Validates,
  then raises `NotImplementedError` until Stage 4 wires the substrate.
- `forkrun/_api.py` — signature validation incl. source/sink plumbing.
- `forkrun/_batch.py` — `Batch` shape stub (§3.5) with the
  claim→invalidate→ack lifetime enforced for direct views.
- `stage0_harness.py` — table schema + surface check. Run:
  `python3 python/stage0_harness.py python/stage0_table.csv`
- `tests/test_api_surface.py` — validation-only tests. Run:
  `python3 -m unittest discover -s python/tests -v`

## Key contracts (v1.3)

- `source ∈ {path, fd, pipe/socket}` — iterables/generators rejected;
  Python is never an input pump (reason stated in the TypeError).
- `sink=None` → built-in emitter (Stage 4); callable → payload-side sink.
- `mode ∈ {python, spawn, plugin}`, `order ∈ {none, index}`.
- `Batch.line_count`: `None` = undefined (`-b` byte mode); the C ABI
  keeps 0-means-undefined, the wrapper maps 0 → None.
- No engine changes in Stage 0. First code is the benchmark, not Python.
