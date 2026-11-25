# Deferred design notes — experimental dist_ingest

Documentation only. No deferred architecture is implemented by this WO.

## Pipe adapter (deferred)

Current settled design:
- Serialized single reader per input stream.
- Monotonic logical ranges.
- `cum_bytes` as the authoritative physical offset.
- No FAA-based file-style claiming for pipes.
- Chunk-size info advisory, not a global consensus protocol.
- Reader publishes the completed range boundary + data-readiness as separate
  concepts.
- At most one outstanding chunk per ingestor.
- Materialize-before-blocking carried into the pipe design (CK-5).

Remaining questions:
- Destination 2 MiB realignment vs accepting/quantifying misalignment.
- Publication and major-ID lifetime contracts.
- Single EOF representation.
- Sparse-memfd write/readiness semantics.
- Backpressure and shard rotation.
- Startup/failure policy.
- Recovery requirements (if any).

## Stage-2 scheduling (deferred)

Self-claim vs manager-assignment as the intended A/B variable — both arms
use the same controller class.

## Reclamation

Ordering of window-retirement vs reclamation-frontier advancement (deferred).

## Runtime discipline (agreed)

- In-process sync: futex/condvar mechanisms.
- Cross-process: eventfd-style notification.
- No hot-path stdio.
- Signal handlers async-signal-safe.
- Manager placement decisions set once.

---
*Written by WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 (CK-7).*
