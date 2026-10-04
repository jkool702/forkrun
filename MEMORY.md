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
