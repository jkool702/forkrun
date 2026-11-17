# Phase 4 — Pipe ingestion (experimental, file-first)

**Status:** explicitly out of the initial physical-NUMA bake-off for distributed candidates.

## Decision

The distributed FAA byte-offset reservation model implemented in `dist_ingest.c` is defined for **seekable regular files** (`pread` at FAA-reserved offsets). It is **not** applied to pipes.

- Kernel pipe reads must remain serialized unless a genuinely correct lock-free/ordered alternative is demonstrated.
- A single serialized reader can, in principle, hand completed byte ranges/buffers to NUMA-local publication paths, but preserving required ordering, EOF/backpressure, exact-once accounting, and local placement without regressing the file path requires a dedicated adapter and additional correctness proofs.

## Implemented now

- File ingestion: global FAA cursor + `pread` + per-node local buffers + per-node queues/consumers. Fully exercised by tests and the dist campaign.
- `stage0/run_case.py` / dist runner: dist candidates accept file inputs; pipe `source_kind` is not routed to dist candidates.

## Remaining work for safe pipe support

1. **Serialized pipe reader:** one thread performs blocking/ready reads from the pipe into staging buffers (or directly into node-targeted buffers) and assigns monotonically increasing logical offsets/ranges.
2. **Handoff to per-node paths:** transfer ownership of filled ranges to per-node publication queues with NUMA-aware placement (copy or direct placement) while bounding total in-flight memory (backpressure).
3. **Ordering semantics:** define whether publication/consumption preserves read order globally, per-node, or is unordered for measurement; ensure downstream comparison uses the same contract.
4. **EOF and short reads:** propagate EOF only after the final range is published and accounted; handle partial reads and pipe closure/errors.
5. **Correctness:** no loss/duplication, exact byte accounting, no stranded reservations/ranges on shutdown.
6. **Integration:** add a pipe adapter mode to the common engine (or a parallel adapter sharing accounting/metrics) selected explicitly; extend runner/campaign/report and tests (including stalls/slow consumers on pipes).

## Bake-off scope

Until the above is implemented and validated, pipe workloads are **excluded** from the distributed-candidate comparative bake-off. The existing centralized control may still be measured on pipes via standard Stage 0 specs, but results must not be compared as equivalent to dist file-ingestion candidates.
