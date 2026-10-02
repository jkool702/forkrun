# forkrun — Python frontend performance work

## Status (2026-10-02)

Branch `NEW/REFACTOR3.0`. Two commits on top of `b52dd2da`:

- `68566efd` incremental collect + backlog-gated NUMA fork gate (−42%)
- `f8f21a92` mmap the collect stream (−10% more)

Test baseline to compare against: **644 tests, 1 failure** —
`test_release_check_passes`, which requires a clean git tree.
`tools/build_wheel.sh` was already dirty at session start (not mine);
that is what makes it red.

## The measurement that matters

Box: **i9-7940X, 14c/28t, ONE socket**, 4 logical NUMA nodes all on
CPUs 0-27, L3 19.3 MiB. Workload: 5M records / 386 MB JSONL, echo
payload (`return batch.data`) so numbers isolate movement not UDF.
`min` of 4, paired A/B. **Load matters**: loadavg was 5.6 with two
opencode processes at ~60% CPU; use paired/interleaved A/B or medians
flip sign.

| cell | bash | HEAD | NEW | gap was → now |
|---|---|---|---|---|
| `map(order=index)` nodes=auto | 0.23 s | 0.667 s | **0.318 s** | 2.90× → **1.39×** |
| `map(order=none)` nodes=auto | 0.23 s | 0.358 s | **0.305 s** | 1.56× → **1.33×** |

`map()`'s DEFAULT is `order="none"`, not `"index"` — benchmark both.

## What was actually wrong (both in the single-threaded parent)

1. **Collect copied the stream twice.** `_read_fd_all()` listed every
   chunk then `b"".join`'d — a second full copy of the whole ordered
   result stream — before parsing anything. `b"".join` alone was 155 ms
   of a 638 ms run. Fixed with `_iter_records()` (chunked, carries only
   the straddling tail) which also mmaps the collection file and parses
   out of the mapping.

2. **NUMA fork gate slept a fixed 50 ms every run.** 50.00 ms of a
   137 ms run = 24-37% of wall, even when the publish landed in 1 ms.
   Replaced with a readiness ramp; supervision deliberately left on the
   50 ms cadence (running `reactor_poll_once`'s O(N) waitpid sweep on
   every fast poll cost +8.8% at 48w, +24% at 96w).

   A flat ramp still regressed +34% at 96w: forking the whole `-j`
   complement against a barely-filled ring makes every worker spin
   (`forkrun_ring.c:6121`, `cpu_relax` ×100) and steals cores from the
   ingest threads. Publish rate ≈13 batches/ms; a first-publish gate saw
   46 batches at 96w = 0.5/worker. So the gate waits on a per-worker
   **backlog floor**.

## Traps hit (do not repeat)

- **`fr_py_data_ready_node` is consume-once.** It walks `write_idx`
  forward from a private hwm. A caller that polls it and then decides
  "below floor" has already destroyed the evidence — the floor becomes
  unreachable and the gate deadlocks into a false *"no published
  batches"* error. That is why `fr_py_backlog_node` was added
  (non-destructive `write_idx - read_idx`, `_shim.c`). Any level test
  needs a level gauge.
- **The engine's `evfd_data_arr` is useless before workers exist** — it
  is only written when `active_waiters > 0` (`forkrun_ring.c:3810`), so
  it cannot wake the fork gate.
- **`bytes(whole_mapping)` before slicing is WORSE than reading**
  (0.513 s vs 0.367 s). Parse from the memoryview and wrap per record.
- **Overlapping the ordered collect with the reactor backfired**
  (0.367 → 0.72-0.80 s; worker phase 106 ms → 500 ms) — done on the
  reactor's own thread it stops servicing workers, and the parent
  competes with them for memory bandwidth. Reverted. A dedicated reader
  *thread* was never tried; on multi-socket EPYC the bandwidth argument
  may invert, so re-measure there before concluding.
- **Microbenchmarks on zero-filled memfds lie** — `bytes(mv[a:b])`
  measured 1712 GB/s (shared zero pages, no real copy). Real collect is
  2.5 GB/s and is already at the `list[bytes]` floor.
- **Microbenchmarks under inflate.** Raw C `fork()` is 43 µs; python
  `os.fork()` 165 µs baseline and 315–974 µs in a real run (bash clone:
  61 µs). Forks are serial in the parent.
- **`fr_py_data_ready`/`FORKRUN_C_PARSE=1`/`c_drain=True` are not wins
  here** — all within noise. `c_drain` is disabled for `order="index"`
  anyway (`use_drain = ... and not use_orderer`).
- **The 20 ms streaming backpressure sleep is NOT a bug** — fired 0
  times on a healthy pipeline (file or pipe). Genuine rate-limiting.
- **Box is single-socket.** Anything about memory-bandwidth contention
  must be re-measured on the EPYC before shipping.
- **Forcing big batches hurts** — `bytes=1M/4M/16M` all slower than
  auto (0.46 s vs 0.37 s). Batch size is not a lever.
- Test invocation: tests live in `python/tests/`; run
  `cd python && python3 -m unittest discover -s tests -p "test_*.py"`.
  Running `python3 -m unittest test_streaming...` from `python/` gives a
  bogus ModuleNotFoundError that looks like a regression.

## Rule I broke, and the correction

I put "make the `nodes=1` spill cheaper" on the open list. It failed the
task's own test: the goal is to make the Python front end behave like the
bash front end, and bash materialises stdin into a memfd exactly the same
way. Making that change would have moved Python *away* from bash. So:

**A measured cost is not a licence to change behaviour. The test is
whether bash handles it differently.** Only then is it a divergence.
Several items here are "Python pays a cost bash does not" and belong on
the list; "both pay it" does not.

## Still open (ranked)

1. **`os.fork()` per worker**: 315 µs @28w → 974 µs @96w, fully serial
   in the parent; 93 ms = 51% of wall at w=96 nodes=auto. A worker
   **farm** (fork a few helpers from a small address space, or fork
   from a lean helper process) is the structural fix. bash has no
   equivalent problem.
2. ~~**`nodes=1` serial spill**~~ — **STRUCK, do not pursue.** I had
   listed "pass the seekable file straight to the scanner instead of
   copying to a memfd". Wrong on three counts, corrected by the user:
   (a) bash does the identical copy — `ring_memfd_create ingress_memfd`
   (frun.bash:1483) then `ring_copy ${fd_write} ${fd0}` (frun.bash:1705)
   — so it is PARITY, not a divergence, and the whole task is to reduce
   divergence; (b) N workers reading disjoint slices of a real file is a
   terrible access pattern off a ramdisk; (c) the memfd + fallow is what
   bounds parent memory. Measuring a cost is not grounds for changing
   behaviour — the test is whether bash does it differently.
3. **No backlog-driven spawn in the NUMA path.** bash's scanner requests
   workers only when `scan_idx - read_idx` exceeds the live count
   (`forkrun_ring.c:3925-3942`); python forks the whole complement up
   front and never arms `spawn_r`. This is *the* structural reason
   python doesn't scale like bash, and it subsumes item 1's blast radius.
4. **`_time.sleep(0.005)` death-confirm spin** (`_reactor.py:416`), up
   to 100 wakeups per death. bash needs zero.
5. Instance A's **double 1 ms C retry budget** —
   `robust_sendfile` (`forkrun_ring.c:7134`) and `ring_copy_chunk`
   (`:7196`) each retry 100×10 µs and both can fire per boundary.
   Pure C, no collision with the python work.

## Reporting rules for this repo

- `forkrun_ring.c` is UNMODIFIED by the shim by design (`_shim.c`
  `#include`s it). Prefer shim-side additions.
- ABI surface is locked in `python/tests/test_shim_abi.py`
  (`extern=46, static=11` now). Bump + justify + run
  `python3 tools/gen_shim.py` then `tools/gen_shim.py --check`.
- Changelog is mirrored as a twin into `DOCS/DOCS_ALL.md` — update both.
- `python/forkrun/libforkrun_python.so` is a build artifact; rebuild with
  `make -f Makefile.substrate python-substrate`. Build is
  byte-reproducible.
