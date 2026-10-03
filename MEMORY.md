# forkrun — Python frontend performance work

## Status (2026-10-02)

Branch `NEW/REFACTOR3.2`, built on `NEW/REFACTOR3.0` + `3.1`:

- `68566efd` incremental collect + backlog-gated NUMA fork gate (−42%)
- `f8f21a92` mmap the collect stream (−10% more)
- `da1755a8` drain: no `pop(0)`, per-signal reslicing, per-quantum env
  lookup, throttled reap sweep. `stream(lines=1)` >120 s → 3.35 s
- `23254ae0` scanner `spawn_r`/`spawn_w` wiring (needed a `wid_node`
  invariant fix — scanner requests must allocate from the *requested*
  node's block)
- `3dc2dc68` C-side zero-copy mapping; the default representation is now
  `memoryview` and the frontend version is 0.17.0 (**unreleased** — not
  published until the optimization list is done)

Test baseline: **656 tests**. The pre-existing
`test_release_check_passes` failure is the dirty `tools/build_wheel.sh`
(not mine; not committed).

## The measurement that matters

Box: **i9-7940X, 14c/28t, ONE socket**, 4 logical NUMA nodes all on
CPUs 0-27, L3 19.3 MiB. Workload: 5M records / 386 MB JSONL, echo
payload (`return batch.data`) so numbers isolate movement not UDF.
`min` of 4, paired A/B. **Load matters**: loadavg was 5.6 with two
opencode processes at ~60% CPU; use paired/interleaved A/B or medians
flip sign.

### Running the bash reference

`. /mnt/ramdisk/forkrun/frun.bash` **once, outside the timed region**,
then time only the `frun` call. Two ways to get this wrong, both of
which I did:

- `bash frun.bash -j 28 …` does not run anything — the file only
  *defines* `frun`. It "completes" in 0.08 s and the number is
  meaningless.
- `bash -c ". frun.bash; frun …"` does not inherit the function unless
  `export -f`d, and the `0.00 s` it reports is a command-not-found.

The payload must match the Python side. `f(){ :; }` emits nothing while
`batch.data` echoes 386 MB, so it is not a comparison; `f(){ cat; }`
forks `cat` per batch, so bash pays a cost Python does not.

### Results (min of 3, interleaved, `-j 28`, **10 GB / 7.44M records**)

Benchmark at **≥2 s per run**. See the trap below for why 386 MB is not
enough.

| path | ordered | unordered |
|---|---|---|
| bash (`-k` / `-u`, `-b 4M`, `f(){cat;}`) | **3.91 s** (2556 MB/s) | **3.55 s** (2817 MB/s) |
| Python 0.17.0 `output="view"` (default) | 5.12 s (1955 MB/s) | **3.73 s** (2681 MB/s) |
| Python 0.17.0 `output="bytes"` | 10.16 s (984 MB/s) | 8.46 s (1183 MB/s) |

Zero-copy is worth **2.0–2.3×** over the bytes representation. Against
bash: unordered is at parity (1.05×), ordered is 1.31×.

`orchestrator=False` reaches the same speed (3.96 s unordered) only
because its collect was rerouted through the mapping — it has its own
parse and was a second place `output=` was ignored.

Earlier entries in this file quote bash at 0.23 s and Python at
0.318 s. Those were 386 MB runs; do not mix them with the 10 GB table.

`map()`'s DEFAULT is `order="none"`, not `"index"` — benchmark both.

### Benchmark size is not a detail

At **386 MB** this same comparison said Python *beat* bash
(0.148 s vs 0.181 s). At **10 GB** it does not (3.73 s vs 3.55 s
unordered; 5.12 s vs 3.91 s ordered). The short run flattered Python and
the long one did not.

The mechanism is fixed cost: engine init, forking 28 workers, and
mapping setup are a constant that is a large fraction of a 150 ms run
and ~1% of a 4 s run. Short runs therefore measure startup, and they
happened to favour the side with the cheaper startup. Aim for **≥2 s
per measurement**; if a change claims a speedup below that, re-measure
on a bigger corpus before believing it.

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
- ~~**The 20 ms streaming backpressure sleep is NOT a bug** — fired 0
  times on a healthy pipeline (file or pipe). Genuine rate-limiting.~~
  **WRONG, and expensive.** It fires roughly once per chunk on a
  streamed source under the reactor (`orchestrator=True`): 645 sleeps on
  light-5M = 12.9 s of a 14.65 s wall, 88% of the run. The reader is
  genuinely faster than the writer, so the wait is real — the error was
  not waiting on the fd that signals it. Now a `select()` on the source
  fd with the same 0.02 s timeout: 14.16 s -> 0.74 s. **A "fired zero
  times" claim is only worth as much as the configuration it was
  measured in** — I had checked files and a couple of pipe paths and
  generalised. Check the worst configuration, not a sample.
- **Box is single-socket.** Anything about memory-bandwidth contention
  must be re-measured on the EPYC before shipping.
- **Forcing big batches hurts** — `bytes=1M/4M/16M` all slower than
  auto (0.46 s vs 0.37 s). Batch size is not a lever.
- Test invocation: tests live in `python/tests/`; run
  `cd python && python3 -m unittest discover -s tests -p "test_*.py"`.
  Running `python3 -m unittest test_streaming...` from `python/` gives a
  bogus ModuleNotFoundError that looks like a regression.
- **ROUTE THE UMA SPILL THROUGH `ring_copy_main` -- BUT NOT WITHOUT
  FIXING THE GATE FIRST. Tried; it breaks two streaming tests.**
  The obvious parity fix is right and mostly works: `_shim.c` can reach
  `ring_copy_main` (it textually `#include`s `forkrun_ring.c`, the same
  way `fr_py_numa_ingest` reaches `ring_numa_ingest_main`), so a
  `fr_py_ingest_copy(infd, outfd)` wrapper calling `ring_copy_main(3,
  argv)` -- note argv order is outfd, infd, the OPPOSITE of the NUMA one
  -- gives Python the eventfd signalling for free and drops the
  per-chunk interpreter cost.

  It passes alone and fails in sequence, which is the tell:
  `test_memory_bounded` raises `ingest scanner failed (status 0)` and
  `test_pipe_auto_streams` reports a zombie. Root cause is that
  `ring_copy_main` does two things the Python loop never did: writes
  `evfd_ingest_eof` and sets `state[0].ingest_complete` on the way out
  (forkrun_ring.c ~8414-8418), and writes `evfd_ingest_data` per chunk.
  The Python parent's handshake (`gate_issued` / `check_scanner_death`,
  run.py ~5560-5575) treats the scanner exiting 0 BEFORE the gate is
  issued as a hard failure -- `if kind == "error" or not gate_issued`.
  So making the ingest genuinely faster and properly signalled exposes
  a pre-existing race in the parent, it does not create a new one.

  UPDATE (second attempt): scoping the check on `ingest_done` does
  NOT fix it. `ingest_done` comes off the ingest child's death pipe, so
  it lags: ring_copy_main has already drained the source and set
  `state[0].ingest_complete`, but the parent has not reaped the child
  when the scanner exits, so the "safe" branch never triggers. The
  signal you actually want is `state[0].ingest_complete` -- ring_copy
  writes it the moment the source is drained, which is exactly the
  condition that makes an early scanner exit harmless. There is no
  getter for it (`fr_py_ingest_eof_posted` reads
  `ingest_eof_idx`, a different NUMA field). So the choice is:
  (a) add a `fr_py_ingest_complete()` getter and test that, or
  (b) defer the check -- remember the early exit, re-evaluate after the
  next reactor iteration, raise only if ingest is *still* incomplete,
      which preserves the lost-tail invariant without a new C call.
  (b) is smaller and needs no ABI change. Both were left undone on
  purpose rather than half-validated.

  LANDED THEN REVERTED -- AND IT LOST DATA. Do not redo this casually.
  W-GATE2 did exactly the above (fr_py_ingest_copy + gate relaxation via
  fr_py_ingest_complete) and passed 667 tests, streaming 23/23, the lot.
  The benchmark caught it on the first pipe cell:
  `EXACTNESS FAILURE light/plugin/default/bytes/pipe: 4990161 != 5000000`
  -- 9,839 records silently lost off the end. The whole suite missed it.

  WHY: **`state[0].ingest_complete` does NOT mean "source drained".**
  ring_copy_main writes it (and the 999999 EOF poke) UNCONDITIONALLY on
  the way out of the function, so every `break` in the copy loop --
  emergency_abort, limit_reached_exit, `copied_in_chunk == 0 && st_size
  > off` -- still posts "complete". It means "my loop ended", not "I
  copied everything". Relaxing the gate on it turns a partial copy into
  a silent short read.

  I asserted that flag meant "drained" in a code comment and never
  checked it against the break paths. A docstring saying "ingest_complete
  is the scanner's EOF gate" is not evidence of when it is SET. **A
  correctness check may only be relaxed on a signal whose setting
  condition you have read, not inferred.**

  To actually do this you need a truthful signal first: have
  ring_copy_main publish `total_moved` vs the source size, or make it
  return non-zero unless it drained, and gate on THAT. Until such a flag
  exists, the gate check must stay as strict as it was.

  **So the real fix is the gate race, not the spill.** Order the work:
  (1) make `gate_issued`/scanner-exit handling tolerate a completed
  ingest, (2) THEN route the spill through `ring_copy_main`. Doing it in
  the other order ships a regression. Reverted; tree green.
- **The scanner pre-flight polls a 100 us sleep, and on the PYTHON
  streaming path the eventfd it should be waiting on is never
  signalled.** `forkrun_ring.c:4406` does `usleep(100)` when the
  pre-flight line-counting scan finds no data yet. There IS poll-based
  logic for exactly this (`forkrun_ring.c:5285`) on `evfd_ingest_data` /
  `evfd_ingest_eof` — but it passes **timeout 0**, so it never waits.
  `evfd_ingest_data` is written only by the C materialized copy
  (`forkrun_ring.c:8279`); the Python spill (`_ingest_copy_loop`, plain
  `os.read`/`os.pwrite`) never signals it, so on that path the poll
  always returns 0 and every wait falls through to the sleep. Bash does
  not have this because its `ring_copy` writes the eventfd. With a slow
  producer this spins ~10k times in 5 s. **Unfixed** — it needs the
  eventfd exposed to the spill (or a shim signal call), which is an ABI
  change and wants daylight. Found by external review.
- **`snapshot_fds()` returned phantom fds.** `os.listdir("/proc/self/fd")`
  opens its own transient dir descriptor and that NUMBER is in the
  listing, so `engine_fds = snapshot_fds() - pre_fds` could subtract a
  REAL engine fd out of the set (phantom N in pre_fds, engine's first
  fd allocated as N). Workers then inherit the engine's memfd/eventfd
  where poll never blocks. Reproduced: pre_fds=[0,1,2,3,4] with 4 a
  phantom, engine opens 4 and 5, computed engine_fds=[5,6] — 4 dropped.
  **A number that a set-difference uses as an identity must be
  validated, not assumed.** Fixed by re-checking each with fstat.
- **THE PRE-FLIGHT GRID DOES NOT MEASURE THE PRE-FLIGHT FIX.** Its pipe
  sources deliver at full speed, so the pre-flight has nothing to wait
  for and the usleep barely fires; per-cell deltas between grid runs
  there are noise (the post-fix run swung +7.5pp on light/plugin/
  default/view while file-source time for that cell did not move). The
  A/B that means anything is on a deliberately slow producer -- 2500
  lines at 3ms: 13,222 -> 453 ctxsw, 0.14s -> 0.07s CPU. **Benchmark the
  case a change targets, not the case that is convenient to run.**
- **`ctypes.c_char` gives a `memoryview` of format `<c`, and CPython
  refuses to compare that against `bytes`** — `view == b"..."` is
  silently `False`. `c_ubyte` gives `<B` and compares equal both ways.
  Found by writing a test that compares a record to an expected value,
  not by reading the docs. A wrong answer, not an error.
- **A keyword flag threaded through N dispatch sites is only correct at
  the ones you edited.** `output="bytes"` was silently ignored on every
  streaming-ingest (pipe) path: the flag reached the call, and four
  executors (`_execute`, `_execute_locked`, `_execute_ingest`,
  `_execute_ingest_locked`) had no parameter to receive it. It typechecked
  and looked right. Audit *callee signatures*, not call sites — an AST
  pass comparing every kwarg against the callee's signature catches all
  of it at once.
  **Fixed structurally, not just patched.** `map()`/`run()` dispatched at
  14 sites re-typing 159 shared keywords; they now build one `base` dict
  per entry point and splat it (159 -> 55 hand-written). The failure mode
  inverts: a forgotten site now raises `TypeError` instead of silently
  taking the callee's default. Pinned by
  `tests/test_dispatch_single_source.py`. **When adding a parameter,
  edit the bundle — never a site.**
- **A guard test that only understands one spelling of the thing it
  guards is not a guard.** The dispatch-invariant detector first matched
  only dict literals (`base = {...}`), not `dict(...)` calls — so the
  day I wrote the bundle as `dict(...)`, the test quietly stopped
  checking anything and still passed. It also first compared every site
  against *every* bundle in the function, which false-positived on keys
  that exist only in a variant. Write the detector to survive the
  reformatting you will inevitably do next.
- **`stream()` cannot be zero-copy.** It drains records live out of a
  results pipe / worker memfd, so there is no finished collection file to
  map. It yields `bytes` and always did. Do not try to force views here;
  document it instead.
- **A hardcoded version literal in a check will rot silently.**
  `release_check.PY_VERSION` stayed `0.16.0` after the bump, so the wheel
  built as 0.17.0 while every artifact glob looked for 0.16.0 and the gate
  reported `expected exactly one fresh wheel, found []` — a symptom three
  steps from the cause. It is single-sourced now, with a test pinning it.
- **A benchmark under ~2 s measures startup, not work.** See "Benchmark
  size is not a detail" above. This one produced a confidently wrong
  conclusion in both directions on this project: a 386 MB run said Python
  beat bash, the 10 GB run said it does not.

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
