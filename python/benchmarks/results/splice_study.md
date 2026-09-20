# Splice Study: Byte Mode + C-Loop Passthrough (W-PY18)

Command: `python3 python/benchmarks/run_all.py --scale medium --trials 3
--filter "splice,bytes_mode"` (plus 10M-line probes below).
Hardware: 28c Intel i9-7940X. Engine v3.5.2. Date: 2026-09-20.

## Verdict up front

Byte mode helps modestly (+9–33%); the C splice loop ties Python
passthrough. The 2B target is unreachable on this hardware: the parent
(spill/scan/parse in Python) caps map() at ~230M lines/s, and sendfile
memfd→memfd runs ~4GB/s (~300M lines/s ceiling for data movement).
Splice ships as correct, useful passthrough infra — not as a 2B
breakthrough. All numbers below, no exceptions.

## Part 1: bytes=N vs lines=N (Python workers, no new code)

### 1M lines (medium)

| Mode              | Lines/s | vs lines=1000 |
|-------------------|---------|---------------|
| lines=1000        | 99.3M   | baseline      |
| bytes=64KB        | 108.8M  | 1.10×         |
| bytes=256KB       | 108.7M  | 1.09×         |
| bytes=512KB       | 107.3M  | 1.08×         |
| bytes=1MB         | 108.9M  | 1.10×         |
| bytes=4MB         | 108.1M  | 1.09×         |

Flat across 64× size range: byte-batch count doesn't matter at 1M
lines (fixed bring-up dominates).

### 10M lines (130MB, large)

| Mode              | Lines/s | vs lines=1000 |
|-------------------|---------|---------------|
| lines=1000        | 161M    | baseline      |
| bytes=64–4096KB   | ~209–218M | ~1.33×      |

Byte mode helps (+33%) — boundary detection costs real money at
scale, but removing it only buys a third, not 10×. Worker dispatch
binds next.

## Part 2: mode="splice" vs Python passthrough (same bytes moved)

### 1M lines (medium)

| Mode                    | Lines/s | Notes              |
|-------------------------|---------|--------------------|
| Python passthrough      | 50.3M   | bytes(data)/batch  |
| Splice 64KB             | 52.6M   |                    |
| Splice 512KB            | 56.2M   |                    |
| Splice 1024KB           | 54.1M   |                    |
| Splice 512KB (stream)   | 59.7M   | pipelined drain    |

### 10M lines

| Mode                    | Lines/s |
|-------------------------|---------|
| Python passthrough      | 61M     |
| Splice 64–1024KB        | 54–61M  |
| Splice stream           | 84M     |

Splice ≈ Python passthrough (both parent-bound: spill + scan +
Python-side record parse). Stream-splice leads (84M) by pipelining
the drain. The C loop's per-batch cost is real but invisible under
the parent — measured, not assumed.

## Why not 2B: the ceiling analysis (10M-line probes)

| Phase (130MB round trip) | Time   |
|--------------------------|--------|
| spill (parent pwrite)    | ~34ms  |
| scan (byte-mode publish) | ~11ms  |
| sendfile 130MB @ ~4GB/s  | ~29ms  |
| parent parse 130MB       | ~15ms  |
| fork/teardown/misc       | ~10ms  |
| worker claim/signal/ack  | ~1ms   |

sendfile memfd→memfd runs ~4.4GB/s here (512KB/116µs), not 20GB/s:
~300M lines/s ceiling for movement alone. Parent Python parse
(~3GB/s) caps map() at ~230M regardless of worker speed. 2B would
need ~26GB/s end to end — beyond this box's tmpfs+Python shape.
bash's 2.51B rides a different machine/profile (no Python parent,
stdout streaming, no collect-parse).

## Corrected performance model (measured)

| Mode | 10M-line rate | Binds on |
|------|---------------|----------|
| lines=N + Python | ~161M | scan (boundaries) + dispatch |
| bytes=N + Python | ~214M | worker dispatch (claim/ack loop) |
| mode="splice" | ~60M* | parent spill/scan/parse (same as above) |
| splice stream | ~84M | drain pipelining helps |
| Python passthrough | ~61M | same parent bound |

(*) splice moves full bytes out (130MB); no-op comparisons are
apples-to-oranges — passthrough is the honest baseline.

## API (shipped)

```python
# Kernel passthrough: claim→sendfile→signal→ack, zero Python/batch
results = forkrun.map(None, "input.bin", mode="splice", bytes=512*1024)

# Live byte-windows as they arrive
for chunk in forkrun.stream(None, "input.bin", mode="splice",
                            bytes=512*1024):
    process(chunk)

# Unbounded ingest + passthrough (bash -s shape)
results = forkrun.map(None, pipe, mode="splice", bytes=512*1024)
```

Rules (validated eagerly): payload must be None (an ignored payload
would silently drop user code); `lines=` rejected (boundaries never
detected; default `bytes=` is 512KB); `run()` rejected (passthrough
produces output — use map/stream); retry-always on output failure
(`on_error` not consulted, documented).

## Deviations from the W-PY18 sketches (all load-bearing)

- `do_ack_current_batch` / `do_ack_with_fallow` don't exist — the
  loop reuses `fr_py_claim` (TLS + poison counting), `fr_py_ack`,
  `fr_py_escrow_deposit`, `fr_py_emit_record`.
- `sendfile` instead of `splice(2)`: file→file needs no staging
  pipe; `fr_py_emit_record` fallback covers exotic kernels.
- Payload-accept-anything rejected: `mode="splice"` + non-None
  payload is a `ValueError` (silent ignore would drop user code —
  the same strictness as spawn/plugin validation).

## Addendum: zero-copy ingest + raw window (measured)

- `fr_py_copy_range` (copy_file_range → sendfile → -1) with
  explicit offsets both sides drives `_spill_to_memfd`; pipes and
  exotic pairs fall back to the original sequential loop byte-exact.
  Measured 130MB spill: 29ms kernel (4.5 GB/s) vs 33ms userspace
  (~4.0 GB/s) — ~20% faster spill, ~3% end-to-end (spill is a fifth
  of map time). No `os.read`/`os.write` on the fast path; the
  fallback keeps them for portability (stated, not hidden).
- `fr_py_get_raw_window` exposes the engine's TLS-cached ingress
  mapping as a borrowed pointer (the FLAG_RAW mechanism the v1
  plugin path already uses internally). Tested readback-exact;
  NULL on bad fd / zero length. Lifetime: until worker remap/exit;
  unacked windows are never punched.
