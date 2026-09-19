# Stage 0 report — evidence, not verdict

Hardware: Intel(R) Core(TM) i9-7940X CPU @ 3.10GHz | 28t | 125GB single-socket | localhost.localdomain | 2026-09-18

Engine provenance: 07cba9d W-NIT1: W-RAW/W-STDIN review cleanup 3e41052 W-STDIN: C-plugin stdin delivery (C-side fork in ring_call) fd893a0 W-RAW: C-plugin raw window delivery (FLAG_RAW live) (locally-built v3.5.2-dev blob; CI blobs pending — numbers depend on W-RAW/W-STDIN source)

This harness is the project's evidence layer for the Python frontend (localization, honest claims, positioning). It is not a decision instrument: the proceed decision is unconditional and recorded in docs_port/STAGE0_AMENDMENT.md.

## What was measured

- JSONL ingestion: 1M records, Pool + futures vs three forkrun variants (C-argv copy path, C-raw zero-copy window, bash+python per-batch interpreter cost).

- Per-record transform: calibrated cost sweep 1µs→10ms; Pool chunksizes 1/100/1000 (at 100µs), futures, forkrun C plugin; crossover data in results/crossover.csv.

- Tokenize-to-tensor: 100M int32 tokens; forkrun raw-window sum (substrate ceiling) + separately timed numpy frombuffer+sum (delivery-vs-conversion split).

- TB streaming: pipe-fed multi-GB legs at two sizes per config (frun stdin-drain, GNU parallel --pipe, split+parallel); whole-pipeline RSS sampled; slope = boundedness assertion.

- Fault isolation: segfaulting item (Pool, futures), segfaulting batch (forkrun -E), segfaulting chunk (parallel); per-config tables in stage0_fault_isolation.md.

- FFI boundary: ctypes null-call floor, claim-shaped / claim-ptr calls, 1MiB MAP_SHARED memoryview window, Python 8-arg fixed cost; full numbers in results/ffi_spike.json (probe micro-library — zero engine involvement).

## Per-niche localization

- JSONL (6 rows): argv-vs-raw delta isolates the tokenize/copy cost; bash+python isolates per-batch interpreter cost.
  Closest incumbent race: mp-pool vs forkrun via bash-python ratio=2.11.

- Transform crossover (5 cost points): dispatch dominates at 3 of 5 points; the crossover cost is the Python frontend's per-batch overhead budget (see crossover.csv).

- Tokenize: incumbent 0.0 (incumbent neither torch nor tensorflow importable on this machine); forkrun raw-window 0.265 s; numpy conversion alone 0.246 s.

- Streaming: frun RSS 1241.5→1244.0 MB across 2 input sizes (delta 2.5 MB) — flat: bounded.
  Throughput parity (~1.17 GB/s both configs, both sizes) is a generator ceiling, not an engine comparison: the single-process Python feeder saturates first. The valid streaming findings are boundedness (flat RSS) and byte accountability, not relative throughput.

- FFI boundary (1 row): worst-case claim-shaped 1.717us (claim-ptr 0.483us, null floor 0.179us) vs the ~10-100ms per-batch budget — the call overhead is four orders of magnitude under budget. Any Stage 3 thunk-flip motivation must come from argv parse/tokenize costs, not from call overhead.

## UNMEASURED and why

- tokenize-to-tensor / torch-dataloader: incumbent neither torch nor tensorflow importable on this machine; forkrun raw-window int32 sum (400000000B); numpy frombuffer+sum alone 0.246s — substrate ceiling, Python frontend pending

## What this table does NOT prove

- Adoption fitness, multi-socket scaling, or the Python frontend's eventual performance (it doesn't exist yet; rows say so).

- Generality beyond the stated hardware, incumbents, and inputs.

- That any single number transfers to another machine (hence the mandatory hardware column and the separately-labeled rental day).
