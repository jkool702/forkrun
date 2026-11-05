# forkrun — Python frontend performance work

> **Read before changing the Python front end.**
> `dev/supervisor/SSoT.md` is the mandatory **Single Source of Truth**
> policy: one correctness-critical decision, one authoritative
> implementation, any number of consumers. It governs the decisions a
> change introduces, modifies or relies on — it is not a licence to
> audit the tree.
>
> Its worked example (section 11) is the case that motivated it: the
> abort-aware helper-death rule was wired into **2 of the 28** places
> that apply it, because the other 26 copies were *inline* and a
> function-level duplicate scan cannot see them. Two tools make the
> policy actionable:
>
> - `tools/ssot_scan.py` — finds the duplication. It compares statement
>   **blocks**, not function bodies.
> - `python/tests/test_helper_death_excuse.py` — the architecture test
>   that keeps the invariant: every helper-death site routes through
>   the shared decision, and the consult precedes the abort it guards.

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

- **A supervision loop must drain its notification pipe before it
  leaves.** The reactor's `poisoned` scalar comes from the engine and the
  `poisoned_batches` list comes from the trap-ACK pipe, so a notification
  still buffered when the loop ends gives one run two descriptions: a
  non-zero count beside an empty list. The trap-ACK *grace deadline* is
  what keeps the loop alive for the `<wid>` ACK; the poison notification
  arms no deadline, so nothing kept the run alive for it. The window is
  the gap between a round's `select()` and `reap_clean_exits()` — the
  out-of-band `waitpid(WNOHANG)` backstop can observe a worker's exit in
  a round whose `select()` snapshot PREDATES that worker's write, so the
  death arrives via `waitpid` and the notification via the pipe, and the
  loop can terminate in between. It presented as a rare flake (one
  occurrence in a full-suite run; 0/200 standalone). Widening the window
  by delaying the backstop sweep reproduced it on 47-58 runs in 60;
  draining the pipe before the break took it to 0 in 150.
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
- **THE PRE-FLIGHT FIX IS BEHAVIOUR-PRESERVING (measured, not argued).
  It does NOT pick a smaller initial batch.** Instrumented both engines
  (FR_PREFLIGHT_TRACE=1) and ran light/plugin/default/view/pipe three
  times each, interleaved: byte-identical decisions every time --
  `case=A pre_lines=118089 W=27 target_pre=114688 eof=0 L=4096`.
  The reason is structural: the wait only happens when pread returns 0,
  i.e. when no data has landed, which is exactly when no worker can have
  arrived -- so the `active_waiters > 0` bail cannot fire while the
  old code was spinning. Same preads, same order, same count.
- **28 WORKERS IS CORRECT. An earlier "14 beats 28" note here was WRONG
  -- it was measured on light only.** The light sweep (8w755, 14w1167,
  28w1044 MB/s) made 14 look better, but re-running the whole grid at 14
  workers shows 14 is slower in 19 of 21 plugin cells, median +11.3%,
  and the gap WIDENS with workload size:

      light   file +3.4..+7.0%   pipe -7.5..-7.3%  (14w WINS on pipe)
      medium  file +11.8..+15.9% pipe +11.3..+14.1%
      heavy   file +21.7..+21.8% pipe +24.1..+27.6%

  The light-pipe win is a fixed-overhead artifact: a ~0.5s run is
  dominated by spawn cost, which 28 workers pay more of. So per-worker
  MB/s falling from 94 (8w) to 37 (28w) was amortising a fixed cost over
  fewer records, NOT saturation. **Lesson: never draw a scaling
  conclusion from the smallest corpus; it inverts.**

  Re-tested with light at 20M records (2.13GB, ~= medium's 2.35GB, so
  spawn cost is no longer the story). 28w wins 6 of 8 plugin cells, but
  by only 4-7% -- versus 11-28% on the medium/heavy corpora. The 14w
  "win" on light is gone; what remains is 14w ahead on max+pipe only.

  So the margin is corpus-dependent, and the published 5M light column
  is close to its worst case for 28w. light-20M sustains 20M records in
  ~1.9s -- 4x medium's per-record rate, the closest thing here to true
  steady state -- and there 28w's edge is single digits. Re-run the
  competitors at 20M before quoting a steady-state ratio.
- **THE STREAMING-VS-FILE MEDIAN FLIPS SIGN WITH TOPOLOGY (fake-NUMA,
  2026-10-03).** Same 48-cell harness, same corpora: UMA pipe is
  FASTER than file (median -3.6%, 20/24 at parity-or-better); the
  4-node numa=fake=4 boot is marginally SLOWER (median +1.4%, 9/24,
  range -8.0% to +12.1%). File input already engages the multi-node
  ingest/indexer path, so a pipe has less left to win and its per-node
  coordination shows up as a small cost. **Never quote "pipe is N%
  faster than a file" without naming the topology.**
- **Multi-node gains land where there is work, not where there is
  bytes.** On the 4-node boot vs UMA: C-plugin `bytes` +8-9% on heavy
  (a real per-record copy four nodes can share), zero-copy `view` ~+2%
  (nothing left to parallelise). Healthy NUMA shape.
- **The old light C-plugin figure was not reproducible.** It read
  12.33M rec/s; a UMA boot measured 10.2M and the fake-NUMA boot
  10.59M. Two independent boots agreeing against a stale number means
  the stale one was a favourable run, not a regression. The ~0.5s
  light corpus is the most state-sensitive cell in the grid.
- **W-DRAINHOLE: punching the output memfd is a NO-OP for speed. Do not
  retry.** The idea was sound and the code is bash-parity (ring_order
  holes the output memfd after moving a chunk; the Python drain now does
  too, safe because it copies into results_fd so the consumer never
  references the range). But a back-to-back interleaved A/B -- two
  prebuilt .so files swapped between runs, 12 samples each -- came out
  median +0.8%, faster in 2 of 4 paired reps. Neutral.
  **Therefore the 15ms/64KB preads are NOT reclaim churn.** Kept for
  parity and because it is correctness-neutral, not for speed. The
  stream() gap is instead structural: stream copies output ~3x (pread
  into a buffer, write to results_fd, Python reads the pipe) where map
  copies it once (fault + build the object). Closing that needs the
  consumer to map the worker memfd directly, which forces a decision
  about backpressure semantics -- a product call, not just engineering.

  THAT DECISION IS NOW MADE (owner, 2026-10-03): bash answers "yes, with
  some small lag", and the chain is worth copying verbatim --

      slow consumer -> stdout blocks -> ring_order blocks
                    -> ack pipe fills -> workers block on ack

  So backpressure is the CORRECT semantics, not a regression to avoid,
  and design (b) (zero-copy views over the worker memfd + window
  backpressure) is unblocked. "Small lag" is the buffering already in
  the pipe/memfd, which absorbs bursts before workers feel anything.

  WORTH CHECKING while that work is scoped: bash stalls workers via the
  ack pipe, but the Python drain has no equivalent -- if the Python
  consumer stalls, fr_py_write_full blocks on results_fd and the worker
  output memfds simply GROW (a memfd does not push back). So the Python
  streaming path may have no backpressure at all, where bash has always
  had it. `test_slow_consumer_bounds_memory` passes, so something bounds
  it today, but confirm the mechanism before assuming the two sides agree.
- **fork() COST SCALES WITH PARENT RSS. MEASURED: 0.27ms/fork from a
  clean parent, 45.3ms/fork from a 5GB one -- 7.5ms vs 1274ms for 28
  forks.** The page table is copied per child. This is the single
  largest performance defect found in this project and it is
  architectural, not a bug.
  - The Python frontend dlopens the substrate into the USER's process,
    so workers fork from whatever that process holds. `frun` does NOT
    have this problem: it deliberately `exec -c "$BASH" --norc
    --noprofile` into a cleanroom BEFORE calling ring_init, so it
    forks from a fresh small shell. (It re-opens its memfds by path --
    `/proc/$BASHPID/fd/N` -- rather than passing fd numbers.)
  - Consequence: ~1.27s of pure fork tax per forkrun call from a
    bloated parent. On light/5M (0.49s run) that alone would be 2.6x;
    on heavy (~5s) it is ~20%. It is a FIXED per-invocation cost, so
    it masquerades as noise on long runs and dominates short ones.
  - It corrupted the published headline table: `bench_ml_pipeline` runs
    every framework in ONE process, so by the time forkrun runs the
    parent is at 3.5-5.5GB. forkrun-plugin reported 6.3M rec/s
    in-sequence vs 12.7M from the IDENTICAL function standalone -- a
    2x error, of which fork cost explains 78% (1.27s of a 1.62s gap).
  - Fixed in the harness by `--isolate` (one subprocess per system).
    A `--settle` sleep does NOT help: sleep cannot reduce RSS.
- **CLEANROOM: ALWAYS-ON. The "~350MB crossover" I recorded earlier was
  WRONG -- an artefact of the PoC's fixed cost.** Re-derived with the
  launcher's real fixed cost:
    - in-process 28 forks: 8.5ms @0MB -> 1774.4ms @5GB (slope 0.353ms/MB)
    - cleanroom 28 forks: 1.9ms FLAT, launcher RSS steady at 2.7MB
    - launcher fixed cost: ~3ms (bare exec 0.4ms + dlopen ~1ms +
      fr_py_init ~1ms). NOT the ~120-129ms I first measured -- that
      figure was dominated by the PoC doing a SYNCHRONOUS whole-corpus
      ingest, which the integrated launcher overlaps with the scan.
  Crossover is therefore NEGATIVE (-10MB): the cleanroom is ahead at
  every realistic parent size, because even at 0MB its forks are 4.4x
  cheaper (0.068 vs 0.30 ms/fork) and a Python process with forkrun
  loaded is already ~17-20MB. **Default-on with an opt-out is correct;
  do not implement an RSS threshold.**
- **NEVER let exactness accounting run inside a timed region.** I put
  `count_results()` inside the clock for the streaming benchmark and it
  made forkrun look 3x slower than it is (3.17M vs the grid's 7.5M).
  count_results parses every output byte in Python; that is harness work,
  not system work. Time with a cheap consumer, verify exactness in a
  separate untimed pass.
- **Two more measurement traps from the same investigation:**
  * `map()` and `stream()` are NOT the same measurement. Over the same
    pipe, same plugin, warm: map bytes 7.68M, map view 9.72M, stream
    bare-drain 6.14M. So stream() really is ~20% slower than map() --
    it hands you one item per batch through a Python generator instead
    of collecting internally. Do not attribute that gap to the input
    source; it is an output-representation effect.
  * Running forkrun's big ingress memfd and later benchmarks in the
    SAME process sequence starves the page cache: one combined run
    decayed ~2.5x from first corpus to last with every row falling
    together. One corpus per process, competitors measured without
    forkrun in the same run.
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

- **Python front end changes must follow `dev/supervisor/SSoT.md`** (the
  Single Source of Truth policy). Before writing decision logic, search
  for an existing authoritative implementation — with
  `tools/ssot_scan.py`, which compares statement BLOCKS, because
  inline duplication is invisible to a function-level scan. Where
  copies have drifted, the divergence is the defect: resolve it, say
  which behaviour won, and test it. The report must name the
  authoritative implementation, its consumers, and the tests actually
  run.
- **A critical section is a decision too** (SSoT.md 4.2). Whoever
  acquires a resource must acquire it ATOMICALLY with the resource,
  and the release must survive the interruption that would abandon it:
  defer the interruption across the section (never swallow it), and do
  not let it replace an exception that is already propagating. One
  authoritative registry for acquisitions
  (`python/forkrun/_childreg.py`), one authoritative primitive for
  deferring interrupts (`python/forkrun/_signals.py::defer_interrupts`).
  A forked child that is not adopted at the fork is invisible to the
  teardown — it is never reaped, and it becomes a zombie.
- `forkrun_ring.c` is UNMODIFIED by the shim by design (`_shim.c`
  `#include`s it). Prefer shim-side additions.
- ABI surface is locked in `python/tests/test_shim_abi.py`
  (`extern=46, static=11` now). Bump + justify + run
  `python3 tools/gen_shim.py` then `tools/gen_shim.py --check`.
- Changelog is mirrored as a twin into `DOCS/DOCS_ALL.md` — update both.
- `python/forkrun/libforkrun_python.so` is a build artifact; rebuild with
  `make -f Makefile.substrate python-substrate`. Build is
  byte-reproducible.

## W-STREAMDRAIN: streaming c_drain wid collision -> silent record loss (2026-10-04)

**Symptom.** `forkrun.stream(..., c_drain=True)` intermittently returns
SHORT output (~5-10% of runs, load-dependent), silently: no exception,
no stderr, no drain-audit failure. `test_c_drain_stream_matches`
(and the four other load-sensitive stream/drain tests) fail this way.
Loss is always a contiguous TAIL of the output.

**Not the C drain.** Instrumented `fr_py_drain_loop`: on a failing run it
exits `rc=0` having copied 16508 bytes with NO memfd left undrained
(`DRAIN_UNDRAINED` silent). The drain does its job correctly.

**Not the workers.** Instrumented the claim loop: every run claims
`bytes=18890` and emits `emitted=18890` (delta=0) — INCLUDING failing
runs. Workers deliver 100% of what they claim.

**Not map() / not the engine.** `map()` 30/30 clean; `c_drain=False`
25/25 clean; both share the same ring/claim/emit core. Only
`c_drain=True` streaming loses data, so the defect is in the streaming
supervision layer, not `forkrun_ring.c` (frozen).

**ROOT CAUSE: duplicate worker `wid` in the streaming NUMA spawn path.**
Worker diagnostics on a failing run:

    wid=2 outfd=35 claims=2 bytes=4092
    wid=3 outfd=36 claims=6 bytes=12288
    wid=0 outfd=33 claims=4 bytes=2510
    wid=3 outfd=36 claims=0 bytes=0     <-- wid=3 a SECOND time
    (wid=1 / outfd=34 never ran at all)

`out_fds` is allocated one-per-wid up front (`_new_output_memfds`), and
the C drain indexes it as `out_fds[wid]` for `wid < workers`. When the
reactor spawns two processes under the same wid, they share one output
memfd while another wid's memfd is never drained -- so bytes are written
into a memfd the drain never accounts for, and the totals come up short.
A corroborating signal appears in the existing NUMA diagnostic:
`workers=4 nodes=4` yet `forked=[0, 2, 3]` with `wids=[1]` unforked.

**Suspect code.** `ReactorState.spawn_worker` / `_reactor.py` wid
selection under W-PYSPAWNWIRE (wid->node binding). The comment there
already records the class of bug: "picking min(wid_free) regardless
would put a worker in a ring that disagrees with wid_node -- which is
the mapping the NUMA drain audit verifies against (it reported a
covered node with published-but-unclaimed batches)". The audit's
`te != 1` vacuity exemption lets a bad slot pass unnoticed.

**Why the audit never fires.** `_numa_drain_audit` checks
`write_idx > read_idx`. The colliding worker's slot is still *claimed*
(it ran, it acked), so drain looks complete while its OUTPUT went to a
memfd indexed under a different wid. Drain completeness and output
completeness are not the same invariant -- §7 of EOF_PROTOCOL.md only
verifies the former.

**Repro (intermittent; run in a loop).**

    for i in $(seq 1 25); do python3 -c "
    import sys,tempfile,os; sys.path.insert(0,'python'); sys.path.insert(0,'python/tests')
    import forkrun; from _helpers import write_lines
    fd,p=tempfile.mkstemp(suffix='.txt'); os.close(fd); write_lines(p,2000,fmt='line %d\n')
    n=sum(len(bytes(b)) for b in forkrun.stream(lambda b: bytes(b.data).upper(),p,workers=4,c_drain=True,nodes=4))
    print('OK' if n==18890 else 'SHORT %d'%n)"; done

**Method note.** Two dead ends worth not repeating: (1) running a single
test as `python3 -m unittest test_c_drain...` from `python/` fails with
ImportError -- run it from `python/tests/`, or you are measuring the
wrong thing; (2) GC is NOT implicated (`gc.disable()` still fails
3/40). A `sort | uniq -c` leading number is a run frequency, not a
worker count.

### W-STREAMDRAIN RESOLUTION (branch NEW/REFACTOR3.6)

**Two independent bugs, same symptom.** Fixing only the first took
600 runs from 591/600 to... nothing; it took 591/600 -> and the residual
was the second bug. Both were required.

**Bug 1 — premature signal-pipe EOF (`ec293c1f`, run.py).** The parent
dropped its spare signal write end gated on worker liveness ALONE.
Workers fork incrementally as the scan advances, so "no live worker" is
briefly true while the scanner still has another to fork; the false EOF
killed the drain child. Fixed by `_spawn_quiescent()`: scanners reaped
(C1) AND no live worker (C2) AND the spawn pipe empty. The spawn-pipe
term is load-bearing — scanners exit AFTER writing requests.
Applied at all four in-loop spare-drop sites.

**Bug 2 — the C drain emitted PARTIAL records (`a5799f91`, _shim.c).**
`fr_py_drain_loop` copied the raw byte range `[offset, size)`, where
`size` is an fstat snapshot of a memfd still being appended to, so the
range could end MID-RECORD. The drain concatenates every worker's bytes
into ONE stream, so a partial record from worker A followed by worker
B's bytes is unrecoverable — the shared parser reads B's header as A's
payload continuation, desyncs permanently, and strands the rest as an
unparseable tail. This is also why `c_drain=False` failed: the same
partial-record desync happens in the Python drain whenever a worker's
byte range is cut mid-record.

    before:  DRAIN_EXIT drained_total=19402 | PUMP_STOP recs=20 tail=7328
    after:   DRAIN_EXIT drained_total=19402 | PUMP_STOP recs=32 tail=0

**Both fixes together: 600/600 exact** (100 runs x 6 configs: nodes
1/2/4/8 x workers 2/4/8 x c_drain on/off). Suite 668 tests, failures=1
(release gate only).

**Generalisable lesson.** "The producer emitted everything" and "the
consumer received everything" are different claims, and neither
implies the other. For this bug: workers emitted 18890/18890 bytes, the
drain copied all 19402 bytes including framing, the pump ingested all
19402 bytes — and 40% of the output was still lost, purely to framing.
Measure the LAST stage before blaming the first.

### W-CR1 cleanroom integration: DONE (branch NEW/REFACTOR3.6)

Status: launcher built + shipped, wired into `map()`, **676 tests pass
with `FORKRUN_CLEANROOM` both 0 and 1** (the one failure is the
pre-existing release gate). Opt-IN, not default-on.

> **Count as of the W-CR1 milestone on `NEW/REFACTOR3.6`, not current.**
> For the v3.6.1 release the figure is **726 passing in each mode**
> (cleanroom 0 and cleanroom 1) on the UMA boot, `skipped=7` — the
> skips are the tests that require multi-node NUMA. Bash: 96 + 264 +
> 101 = **461/461**. `release_check` is **21/21 green** once the release
> heading is finalized.

Four attempts were needed. The first three failed in ways worth
remembering, because each failure mode is invisible to the obvious test:

1. **Hook never fired.** Gated on `mode == "plugin"` AFTER
   `_coerce_payload`, which normalizes plugin -> python (plugin-ness
   rides the payload marker, not the mode). Dead code. The smoke test
   "passed" because BOTH flag settings ran the in-process path -- equal
   totals are exactly what a dead hook produces. **A test that cannot
   distinguish "worked" from "never ran" is not a test.**
2. **`res_fd` closed in the parent** right after fork, then handed to the
   collector that fstats it. Only `src_fd` is the child's alone.
3. **Envelope wrong in both directions.** Too strict (demanded a
   dialect-1/2 frozen-ABI plugin -- that is a constraint of the C *worker
   loop*; the launcher serves v0 plugins fine) then too loose (let
   `order="index"` and `on_error="fail-fast"` through, and since the
   launcher SUCCEEDS on those with wrong semantics, a fail-safe on
   launcher exit never fired).
4. **The exec probe hung the whole suite.** It spied on `os.execv` and
   wrote a marker file from INSIDE the forked child. Forking a
   multi-threaded process and then doing Python work in the child is the
   documented deadlock hazard -- the same one Python 3.12+ warns about at
   every `os.fork()` in run.py. Parent sat in `ThreadHandle_join` while
   every worker thread blocked on an RLock futex. Bisected by removing
   the file: suite back to 232s. **Nothing in a forked child may touch
   Python in a test probe.**

**The envelope** (what the launcher can HONOUR, not merely accept):
materialized file + `mode='plugin'` + UMA + `order='none'` + not
`strict_poison` + **`orchestrator=False`**. The last is load-bearing: the
launcher has no death pipes/respawn/trap-ACK, so a dead worker loses its
batch, and `map()` defaults `orchestrator=True`. Outside the envelope it
WARNS and falls through to the in-process path -- never raises (breaking
a working call to advertise an experimental accelerator is worse), never
silent.

`on_error` and the retry limit are TRANSPORTED (`--on-error`,
`--retry`), not refused -- the launcher already takes both and
`_ON_ERROR_CODES` is the same table the C worker loop uses.

Still open: default-on flip (needs retry/poison parity proven), streaming
cleanroom, and a real end-to-end benchmark of the INTEGRATED path. The
standalone launcher's numbers (2.49ms spawn at 28 workers, 2.7MB RSS) are
not end-to-end results and must not go in the release tables.

### W-CR1 final state: default ON, 2.06x startup, 1.034x throughput

`python/benchmarks/bench_cleanroom.py` — the first end-to-end numbers
for the cleanroom path. Paired interleaved A/B, exact output byte
counts asserted on every pass (a mismatch aborts rather than reporting
a throughput number for wrong output), warmup discarded, medians.
28 workers, UMA, orchestrator=False, `ml_process_light`.

| regime | in-process | cleanroom | ratio |
|---|---|---|---|
| startup, 2000 records, n=20 | 18.06 ms | 8.75 ms | **2.06x faster** |
| throughput, light_5M, n=9 | 677.3 ms | 655.3 ms | **1.034x faster** |

**Default is OFF, and that is deliberate — it was briefly ON
(`5ae0b0a0`) and reversed.** Two reasons, the second decisive:

1. It cannot be reached by default callers. The envelope excludes
   `orchestrator=True`, which is `map()`'s DEFAULT, so a plain
   `forkrun.map(...)` never took the cleanroom even while nominally
   "on". The flag mostly advertised an optimization ordinary calls
   declined.
2. It costs something real. The launcher runs no supervisor: no death
   pipes, no respawn, no trap-ACK, so a dead worker loses its batch.
   Defaulting it ON would mean **defaulting crash recovery OFF** for
   every caller who did not ask for that.

Orchestrator keeps the default. The cleanroom is opt-in
(`FORKRUN_CLEANROOM=1`) for callers who knowingly want the speed and
accept the supervision model it has today. The "can we have both?"
question has the answer "not until W-CR4 lands" — see below.

Correctness parity was established independently of the default
 — correctness was established first (16 tests,
including `TestCleanroomFaultParity`). What blocked it was a 9%
throughput deficit, and the fix was to fork the launcher's spill so it
overlaps the scan (W-CR2 below). That single change took throughput
0.911x -> 1.034x and startup 1.91x -> 2.06x, and made the launcher
genuinely streaming as a side effect.

`_cleanroom_explicit()` exists because default-on and `map()`'s
`orchestrator=True` default collide: orchestrator=True is outside the
envelope, so warning on every fallback would fire on nearly every
ordinary `map()` call. A default-on feature must be quiet when it does
not apply and loud when a request is declined.

`FORKRUN_CLEANROOM=0` forces the in-process path everywhere.

Suite: 684 tests, `failures=1` (release gate only) both with no env var
and with `=0`.

### W-CR2: fork the spill (one change, three payoffs)

The launcher used to spill inline — read the whole source into its
ingress memfd, then scan. That meant it could not be live (a streaming
source stalled until producer EOF), and it cost a full extra pass over
the corpus, which is exactly the throughput deficit above. The in-process
path overlaps spill with scan via a forked UMA ingest child; the
launcher now forks its spill child the same way. The engine's documented
ingest->scanner EOF protocol (EOF_PROTOCOL.md §5) handles the tail. The
spill child is joined LAST and its failure is fatal — if it died early
the scanner saw a truncated corpus, and silently returning short output
is the bug class this project refuses.

Streaming verified live against a pipe source: first result at 3.2 ms,
not buffered to EOF.

### W-CR3: streaming cleanroom wired (branch NEW/REFACTOR3.7)

`stream()` now routes descriptor sources to the launcher. `stream()`
sources are descriptors only (it rejects iterables), so the launcher
reads `--src` exactly as Bash's `-s` shape does and nothing is pumped.
The forked-producer path is kept for a descriptor-less source because
it costs nothing and is the only way an iterable could ever work.

**The parent only ever DRAINS**, which is what makes it deadlock-free:
the launcher may block writing results, the spill child may block
reading the source, the producer may block on a full pipe — all relieved
because the parent never stops reading until EOF. Verified before any
wiring on a 200k-record pipe (first result 2.8 ms) and on a
deliberately slow producer (2.9 ms), neither deadlocking.

Teardown is explicit, not best-effort: on abandonment both children are
KILLED before the fds close, so an early `break` cannot leave the
launcher writing into a closed pipe or the producer blocked forever.
There is a test for exactly that.

4 streaming tests: byte-exact vs in-process, liveness under a slow
producer, early-abandonment teardown, fallback outside the envelope.
Suite: **688 tests, `failures=1`** (release gate only) both with the
cleanroom at its default and with `FORKRUN_CLEANROOM=0`.

### W-CR3 side-finding: None and b"" are different

While fixing `test_none_and_empty_output_parity` (which compared blob
LISTS across runs — batch counts are race-dependent, so that assertion
demanded stability that does not exist; it failed ~1 run in 8 under
load and 12/12 alone), an intermediate attempt asserted
`len(new_none) == len(new_empty)` and failed 8/8.

**That assertion was wrong, not the code.** A `None` payload emits NO
record at all (`len == 0`); a `b""` payload emits one empty record per
batch. The engine preserves that distinction deliberately. Worth
remembering before "fixing" it the other way.

### W-CR2 re-validation on branch 3.7: 1000/1000 exact

The gap flagged before pre-tag: the W-CR2 forked-spill change lives in
the LAUNCHER, but the original 600-run validation ran `stream()` with
the default `orchestrator=True`, which is OUTSIDE the cleanroom
envelope and therefore never touched the launcher. So the pre-3.7
evidence said nothing about the code W-CR2 actually changed.

Re-ran both families, 100 runs per config
(`python/benchmarks/tail_loss/validate_100x.sh`):

| family | configs | result |
|---|---|---|
| in-process streaming (regression) | w4n1, w4n4, w2n4, w8n4, cd0 x2 | **600/600** |
| cleanroom streaming (launcher, W-CR2 path) | w2/w4/w8/w16, nodes=1 | **400/400** |

**Two false starts worth recording**, both caught by a probe rather than
by a passing test:

1. The first attempt added a `stream_cr` mode to the old harness — which
   used a PYTHON UDF and a TEMP FILE. A Python UDF fails the envelope's
   `mode="plugin"` gate, and a regular file is not a streaming source so
   it never reached the hook AT ALL. It would have "passed" 100/100
   while testing nothing. Same failure mode as the dead map() hook.
2. The corrected version still didn't fire, because it passed
   `nodes=4` and the envelope is UMA-only.

The probe (`PROBE=1`, a parent-side spy on
`_execute_cleanroom_stream` that reports whether it was entered, and
exits 2 if not) is what caught both. **A validation config must be able
to fail when the code under test does not run** — otherwise it is
decorative. Same lesson as the dead hook, the res_fd close, and the
exec probe that hung the suite.


### W-CR5: process-death semantics of the cleanroom fallback (P0)

The cleanroom's failure mode is WHOLE-JOB, and external review is right
that "double the work" understates it. A worker that dies makes the
launcher exit non-zero; Python warns and re-runs the entire input in
process. For any plugin with side effects that is **at-least-once
execution** — not a retry of the failed batch, a replay of everything
that already succeeded. The reactor path instead recovers the single
dead worker/batch, so the two paths differ in exactly this respect.

This is now TESTED rather than implied. New fixtures in
`tests/plugins/test_plugin_v1.c` (note: distinct from `always_fail_v1`,
which merely RETURNS 42 and so only exercises retry/poison):

  die_once_v1    appends a marker, then SIGKILLs itself exactly once
  die_always_v1  SIGKILLs on every call
  count_only_v1  pure side effect, never dies

`TestCleanroomProcessDeath` pins both halves:
  - a worker death still returns correct bytes (the rerun saves it)
  - a death causes strictly more invocations than a clean run, i.e.
    at-least-once is real and observable

**A methodology trap worth recording.** The first version compared a
cleanroom run against an in-process run and saw 27 vs 50 invocations,
then nearly concluded "the cleanroom under-executes". That gap is
BATCHING, not duplication: the launcher spills and scans in its own
process, so its batch boundaries differ from the in-process path and
invocation counts are not comparable across paths. The correct
measurement compares WITHIN one path — same arm, with and without a
death. Comparing counts across the two execution models measures batch
shape and will mislead you.


### W-CR6: parent-RSS is the dimension that matters (P1)

The earlier integrated numbers (2.06x startup, 1.034x throughput) were
measured in a ~29 MB benchmark parent, and the unimpressive throughput
figure was an artefact of that, not a ceiling. `--ballast-mb` now grows
the PARENT before running, which is the whole premise of the cleanroom:
workers must not fork from a large address space.

28 workers, UMA, orchestrator=False, paired, exact counts asserted.

| corpus | parent RSS | startup | end-to-end |
|---|---|---|---|
| medium_5M | 29 MB | 2.00x | 1.01x |
| medium_5M | 2.1 GB | 10.26x | 1.18x |
| light_5M | 2.1 GB | 10.76x | **1.51x** |
| heavy_1M | 2.1 GB | 10.54x | **1.56x** |

**The benefit scales with parent address-space size**, which is exactly
what the architecture claims and what a small benchmark parent cannot
show. Startup goes 2x -> ~10x; end-to-end goes ~1.0x -> 1.2-1.6x.

Practical read: in a small script the cleanroom buys little on
throughput; in a real service (a web worker, a notebook, anything with
a loaded parent) it is a 1.2-1.6x end-to-end win, not a rounding error.
Any future cleanroom performance claim should state the parent RSS it
was measured at, or it is not a claim.


### Streaming latency: 24x on first result

200k records through a pipe, 28 workers, paired, 5 runs, median:

| path | first result | bytes |
|---|---|---|
| in-process stream (orchestrator=True) | 269.5 ms | 200000 |
| cleanroom stream (orchestrator=False) | **11.1 ms** | 200000 |

**24x lower time-to-first-result**, which is the metric that matters for
the interactive/latency-sensitive case a stream exists to serve; the
throughput story is the 1.2-1.6x above. The cleanroom's spilled+overlapped
scan (W-CR2) is what makes this possible -- an inline spill would have to
reach producer EOF before scanning anything.

Note this benchmark tripped the new threaded-fork detection on its own:
the producer is a thread, so the harness is exactly the shape the warning
describes. Detection working unprompted is the intended behaviour.


### Post-review status (branch NEW/REFACTOR3.7)

Addressed from the external review, in its priority order:

| # | item | status |
|---|---|---|
| 2 | return_stats silently wrong under cleanroom | **FIXED** `6c923e2b` -- declined in the envelope |
| 3 | fork() from a threaded host | **MITIGATED** `526ede03` -- warns once, fatal under env var, installed at the _RUN_LOCK choke point |
| 1 | worker death untested / whole-job rerun | **TESTED + PINNED** `104fc551` -- at-least-once made observable |
| 4 | spill failure strands the launcher | **FIXED** `8dfd8ace` -- spill now calls fr_py_abort |
| 8 | abandonment leaks the subtree | **FIXED** `8dfd8ace` -- PR_SET_PDEATHSIG in every child |
| 6 | benchmark base too narrow | **DONE** `36431490`, `757a7eb3` -- parent RSS + streaming latency |
| 7 | _RUN_LOCK serializes jobs | architectural, untouched (correctly) |
| 5 | real NUMA | needs hardware |

Suite: **690 tests, `failures=1`** (release gate only) both at the
default and with `FORKRUN_CLEANROOM=1`.

Two findings from this round worth more than the fixes:

- The abandonment test PASSED BECAUSE OF THE BUG. It asserted the
  producer completes; the producer completed only because the orphaned
  spill child kept draining its pipe. A test whose assertion is
  satisfied by a leak is worse than no test.
- Comparing invocation counts ACROSS the two execution models measures
  batch shape, not semantics (27 vs 50 was batching). At-least-once
  had to be measured within one path.

### W-PY-STREAM-BACKPRESSURE-1: the notification pipe is a window, and a cliff

**The mechanism, which was not obvious from the name.** The
worker-completion notification pipe's capacity IS the producer's
read-ahead window. A worker that finishes a batch writes one 16-byte
notification; the parent reads them. The pipe holds N notifications, so
N is how many completions may be outstanding before a worker blocks
writing its notification — and a blocked worker cannot claim its next
batch. The per-worker output memfds have no backpressure of their own
(a memfd does not push back), so this pipe was the ONLY thing bounding
how far a worker ran ahead of the drain. At 1MB that bound was 65536
completions: wide enough that it was not a bound.

**The cliff is arithmetic, and it will bite anyone who tunes this.** A
pipe of S bytes holds S/16 notifications, and it only binds if that is
fewer than the outstanding completions. On a 977-batch run, 16KB (1024
slots) can hold EVERY notification of the run and never blocks — so
1MB, 64KB and 16KB measured IDENTICALLY, and only 4KB (256 slots)
applied any backpressure. **A capacity not below the run's
outstanding-notification count does nothing at all.** Before measuring
this, I calibrated with a 400k-line corpus: 98 batches — fewer than the
256 slots of a 4KB pipe — so the experiment would have shown nothing
however the code was written. **Size the corpus so the mechanism can
fire before running the A/B.**

**Path dependence, measured (4M lines, amp 5, 4 reps, medians).**
Plain supervision (`orchestrator=False`): peak retention -24% to -65%,
throughput unchanged (no demonstrated penalty), first-result latency
unchanged. Reactor
supervision (the DEFAULT): retention -0.4% to +3.7%, throughput and
latency unchanged. The reactor drains the notification pipe
eagerly (up to `DRAIN_BURST` completions per round), so it never falls
behind at the NOTIFICATION level; its retention is the parent's own
parsed-record queue, and the workers' read-ahead is bounded by
something else there. **So the lever helps the path where the drain is
the bottleneck and does nothing on the default path.**

**A near-miss I have to record, because it nearly produced a wrong
conclusion.** An early 5-rep A/B showed the small pipe *reducing*
throughput 33% in one cell, and I reported it as a fast-consumer
regression. With 4 reps and four capacity arms it reversed: 1MB is the
SLOWEST arm (2080 rec/s vs 2784 for 4KB), and the cell's first-result
latency is BIMODAL in every arm (0.014s or 0.15-0.40s — the reactor's
poll quanta). Medians over 5 reps landed on different sides of that
bimodality in the two arms. **A 33% "regression" that reverses with
more reps and more arms was a bimodality artifact, and reporting it
would have been a wrong conclusion.** The repo's own rule — interleave,
alternate the A/B order, take medians — is what caught it.

**The `-4` contract, and the test that is not vacuous.**
`fr_py_notify_committed()` returns `FR_PY_ERR_NOTIFY` (-4) for
"committed but not notified" — explicitly not a retryable payload
error. The Python worker special-cased `-2`/`-3` but let `-4` fall into
the generic output-error path, which reaches the `on_error` ladder's
**retry** branch: that branch re-arms the batch for a same-process
re-claim, i.e. it retries work whose commit already happened. The
shipped C worker treats ANY nonzero `fr_py_complete` rc as fatal for
exactly this reason.

**THE MUTATION CHECK EARNED ITS KEEP.** The obvious assertion — "no
duplicate batch execution" — is VACUOUS: with the fix reverted there is
still no duplicate, because the engine does not re-offer an
already-committed batch. A test that cannot fail is worse than no test.
The discriminating observable is WHICH function deposited the escrow:
`_deposit_or_loud_skip` (the failure ladder — the bug) versus
`_escrow_deposit_exit_loud` (the exit path — correct). The caller's
frame name separates them exactly, and the worker is a forked child, so
a spy installed in the parent is inherited. Reverting the fix fails
exactly that test.

**And the consequence, stated rather than hidden:** a worker that exits
on -4 makes the parent respawn it, and the per-process fault hook fires
again in the new process, so the run can reach the respawn cap and fail
CLOSED. That is the correct behaviour for a genuinely lost notification
(the parent is gone), but it means an injected fault ends the run
instead of completing it. Measured, not assumed.

**C DRAIN IS 16-19x SLOWER ON THE STREAM PATH, AND IT IS NOT MY
CHANGE.** Pre-existing (98.5s at 1MB vs 98.3s at 4KB). It has a sharp
cliff at ~64 blobs — the reactor's `DRAIN_BURST` size — below which it
matches the legacy drain (1.01-1.21x, which is very likely where the
"0.7-1.0x" figure in `_validate_c_drain` came from). Above it, 16-19x.
Instrumented: 162 select calls, **9.72s of a 10.43s run spent WAITING
in `select()`** (93%), 97 calls over 50ms, against 5 calls and 0.01s
for the legacy drain. The mechanism: the C drain's pump reads 65536
bytes per call and returns None whenever that does not complete a blob,
which ends the `DRAIN_BURST`, which leaves `drained_last` False, which
makes the reactor's next `select()` wait the FULL `poll_timeout` (0.1s).
The legacy drain does not park because its data source is the worker's
memfd, which is ALWAYS pollable — it preads unconditionally and yields
whatever is there. The reactor's own comment names the cap: *"otherwise
throughput caps at ~10 blobs/s (one yield per 100ms idle select)"*.

**Why that matters more than the slowness: the C drain's peak
retention is FLAT at ~3.5 MB regardless of scale, where the legacy
drain's grows linearly to 138 MB.** So the C drain is the RIGHT
mechanism for the default path's memory problem, and it is broken by a
100ms park. Fixing the park (drain the results pipe fully per call;
and/or put `results_r` in the reactor's watch set for an event-based
wakeup) is worth more than shrinking the notification pipe.

**The backpressure CHAIN, which is the thing to remember.** Bash's
backpressure is three links and the ack pipe is the LAST: a slow
consumer fills the **stdout pipe**, so `ring_order` blocks writing
stdout, so `ring_order` stops clearing the **ack pipe**, so the ack
pipe fills, so workers block on the ack. The ack pipe is small (4096,
one page, `frun.bash:1730` — *"Size order ack pipe to 4096 (1 page) for
closed hydraulic backpressure"*) because it only has to LATCH a
backpressure the stdout pipe has already started.

The 4KB notification pipe IS that ack pipe, so it can only engage if
the chain upstream of it is closed — and it is closed on exactly ONE of
the two Python paths:

- **Plain supervision: closed.** Its drain YIELDS INSIDE the collection
  loop (`run.py:5698`), so it is CONSUMER-PACED: the next notification
  is not read until the consumer asks for the next record. The
  consumer's slowness stops the drain, the pipe fills, the workers
  block. Retention -24% to -65%.
- **Reactor supervision (the default): BROKEN AT THE FIRST LINK.** Its
  drain collects into a `_pending` list and pops one at a time
  (`run.py:9207`), and the reactor pulls up to `DRAIN_BURST` (64)
  records per round regardless of the consumer. The consumer's slowness
  is absorbed by a PYTHON LIST, not by a pipe, so the notification pipe
  never fills and the ack-pipe analogue never engages. Retention
  unchanged.

**So the missing piece on the default path is bash's STDOUT-PIPE
analogue** — a bounded transport between the drain and the consumer that
blocks the producer. Making the reactor's drain consumer-paced is NOT
the answer: `DRAIN_BURST` exists to bound death-detection latency, and a
consumer-paced drain would starve the supervisor. **The C drain's
results pipe IS that transport** (which is why its retention is flat at
3.5 MB while the legacy drain's grows to 138 MB) and it is the 100ms
park that makes it unusable at speed.

**Lesson worth keeping: a backpressure mechanism is a CHAIN, and you can
shrink any one link to no effect.** The first measurement of this work
("4KB did nothing on the default path") looked like a failed
experiment. It was not: it was the chain telling us which link was
missing, and it pointed at a 100ms park in the reactor's poll loop that
nobody was looking for. **When a backpressure lever does nothing, find
the missing link before tuning the one you can see.**

**A REVIEWER FOUND A REAL GAP, AND THE FIX FOR IT FOUND A REAL TRADE.**
The `-4` tests asserted that the failure ladder was not entered, that
there was no duplicate execution, and that the run terminated. They did
NOT assert what the CALLER observed -- "the worker exited" is not "the
caller got complete output or a visible failure". Two further tests now
cover both permitted outcomes, at two corpus sizes: a ONE-batch run
completes (the live silent-truncation check), and an EIGHT-batch run
fails closed. A test that only exercised the failing branch would leave
the truncation check as dead code -- and the first attempt at this
assertion did exactly that.

**And the new test is discriminating: it FAILS when the `-4` fix is
reverted.** Measured at the 8-batch corpus:

  * fix reverted: the run **SUCCEEDS** -- 4 records, 56 bytes, all 8
    lines delivered, no duplicate execution. It reports success after a
    committed-but-unnotified batch.
  * fix present: the run **fails closed** (ForkrunWorkerFailure).

**So the fix trades "continue, correctly, BY LUCK" for "fail closed, BY
CONTRACT", and the contract is the reason to take it.** The reverted
path happens to deliver complete output only because the engine does
not re-offer an already-committed batch -- exactly the behaviour the C
code says not to rely on ("a caller that retries on those would
re-execute committed work"). The reverted path also re-arms an
already-committed batch in the escrow slot and reports a misleading
error ("output write failed on batch N" for a batch whose output WAS
written and committed).

**Lesson worth keeping: a test that asserts an intermediate property
is not a test of the contract.** The ladder-entry assertion proved the
MECHANISM; only an outcome assertion proves what the user gets. Ask
what the CALLER can observe, not only what the implementation did.

**THE C DRAIN'S 100ms PARK, AND THE BOUND THAT IS PART OF THE FIX
(WO-PY-CDRAIN-REACTOR-WAKEUP-1).** The reactor now SELECTS on the C
drain's results pipe -- an `ExtraWatch` holder it wakes on but NEVER
reads (the pump keeps sole ownership of the read side, and the holder is
DISARMED at EOF so a readable-EOF pipe cannot spin the reactor) -- and the
pump consumes everything already available instead of one 64 KiB chunk
per call. The cliff is gone: **16-19x -> 1.00-1.05x** at scale, and the
`select()` wait collapsed from **9.72s of a 10.43s run (93%)** to
**0.003s over 6 calls**.

**THE PART THAT IS EASY TO GET WRONG: Step A UNBOUNDED THROWS AWAY THE
WHOLE POINT OF THE C DRAIN.** Read-until-EAGAIN, as the work order's
first implementation suggests, queues the run's whole output in the
parent's `pending` deque: the C drain's peak retention went from a flat
**3.5MB to ~18MB** -- and the wall time did NOT improve (5.60s vs
5.62s), because the WAKEUP had already removed the park. So the
implementing the two steps literally would have shipped a 5x regression
in the only property that makes the C drain worth using.

**The bound that fixes it: the pump tracks the bytes it has PARSED BUT
NOT YET HANDED TO THE CONSUMER, and stops reading when that exceeds a
budget (256KB).** So the read-ahead is bounded by the CONSUMER'S PACE,
not by the pipe. The pipe's capacity is no longer the bound -- which is
the point: the C drain's advantage was never "the pipe is small", it is
"the producer cannot get ahead of the consumer", and a PIPE cannot
express that. A BUDGET CAN.

**Two more things the measurements corrected, both against my own
first guess:** the residual ~100ms in the fast-consumer cells was NOT a
termination-path sleep (`term_sleeps=0` in every cell) and NOT a select
park -- it is noise on 0.02-0.19s runs, far below this repo's own "~2s
per measurement" rule, and it did not reproduce under instrumentation.
And the `order="index"` rows are a CORRECTNESS arm, not a performance
one: the C drain is not used with the orderer at all
(`use_drain = ... and not use_orderer`), so both arms measure the same
path there.
