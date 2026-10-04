# Cleanroom Integration — Context Handover & Work Order

**For:** a fresh opencode instance with no memory of this work.
**Author:** previous instance. **Date:** 2026-10-04.
**Repo:** `/mnt/ramdisk/forkrun` (git remote `origin`, user `jkool702`).

Read this whole file before touching anything. Most of the value is in the
*gotchas* section — several of them cost hours and will bite you again.

---

## 0. TL;DR

The C cleanroom launcher **works and is verified correct**. It is a standalone
binary, committed and pushed on `NEW/REFACTOR3.5`.

It is **not wired into `forkrun` yet**. That is the remaining work.

Read §6 (gotchas) and §7 (open bugs) before writing anything.

### Every outstanding item

| # | task | status | blocked by | see |
|---|---|---|---|---|
| 1 | 10-site init dedup | **DONE**, committed `44b2128c` | — | §4 A, §5 |
| 2 | Lost-tail truncation, 4 stream/drain tests | **OPEN — highest priority** | needs repro under load | §6.3, §7.1 |
| 3 | `test_c_drain_stream_matches` order-dependence | **OPEN** — passes in suite, fails 5/5 alone | — | §5, §7.5 |
| 4 | Wire launcher into one `map()`+plugin path, flag default **off** | **OPEN — the real work** | 2 | §4 B |
| 5 | Suite green with flag on **and** off | **OPEN** | 4 | §4 B |
| 6 | Flip default to on | **OPEN** — do not skip #5 | 5 | §4 C |
| 7 | Streaming cleanroom support | **OPEN** — hard, see §3 | 4 | §4 C |
| 8 | Benchmark the *integrated* path | **OPEN** | 4 | §4 C |
| 9 | Release bookkeeping → v3.6.1 / `0.17.0` | **OWNER, not you** | — | §7.2 |
| 10 | Real multi-socket NUMA validation | **blocked, needs hardware** | — | §7.3 |

Suggested order: **2 → 4 → 5 → 6**, with 8 after 4. Items 1, 3, 9 are
independent of the cleanroom and can be done at any time.

**Do #2 before #4.** Wiring a cleanroom branch on top of a path that
intermittently loses its tail would make every subsequent measurement
untrustworthy — you would have no way to tell a cleanroom bug from the
pre-existing truncation.

---

## 1. State of the branches

| Branch | Commit | State | Use it for |
|---|---|---|---|
| `NEW/REFACTOR3.5` | `44b2128c` | clean, pushed | **the work happens here** |
| `NEW/REFACTOR3.4` | `ee885122` | clean, pushed | safe fallback; cut the release from here if 3.5 stalls |
| `NEW/REFACTOR3.3` | `6069b2b3` | clean, pushed | obsolete, but harness-isolation commits live here too |

Suite status as of `44b2128c`:

| branch | result | notes |
|---|---|---|
| 3.4 | 668 tests, `failures=1` | release gate only |
| 3.5 | 668 tests, `failures=2` | release gate + `test_c_drain_stream_matches` |

The extra 3.5 failure is **not** from the dedup — see §5. It is an
order-dependence, not a regression.

**`3.4` is shippable today.** If anything in your work becomes unclear, revert to
it and release v3.6.1. Do not let the cleanroom block the release.

### Ramdisk warning — read twice

`/mnt/ramdisk/forkrun` **and** `/tmp` are **ramdisks**. A reboot destroys
uncommitted work with no warning.

**Commit and push after every meaningful step.** Not at the end. Not in batches.
Verify with:

```bash
cd /mnt/ramdisk/forkrun
git status --porcelain          # must be empty
git rev-parse HEAD              # must equal origin
```

---

## 2. What the launcher does

`/mnt/ramdisk/forkrun/forkrun_cleanroom.c` — a single standalone C file. It is
**not** in `Makefile.substrate` (grep returns 0 hits); it is built manually and
is not a build target. Do not assume `make` compiles it.

It owns the entire pipeline, transliterating what Python does:

```
fr_py_init
  → spill source into an ingress memfd (poking evfd_ingest_data per chunk,
    exactly as the Python spill path does)
  → create one output memfd per worker
  → create ONE shared 1 MiB signal pipe for all workers
  → fork: fallow, workers, scanner
  → drain into a result fd
```

Every primitive it needs **already existed in C** in
`python/forkrun/_shim.c` (`fr_py_init`, `fr_py_scan`, `fr_py_ingest_data_post`,
`fr_py_worker_plugin_loop`, `fr_py_fallow_loop`, `fr_py_drain_loop`). Python was
doing nothing but `fork` + `scrub_fds` + call + `_exit`.

**This is why it worked quickly.** It was a transliteration, not a redesign.
Keep that framing: if you find yourself inventing new orchestration logic, you
have probably misunderstood the existing Python path.

### Verified results

Output size vs. the in-process reference (5M-line corpus, `ml_process_light`):

| workers | launcher bytes | vs reference |
|---|---|---|
| 4 | 351,592,343 | +20,240 (0.006%) |
| 8 | 351,592,343 | +20,240 |
| 28 | 351,592,343 | +20,240 |

Stable across worker counts, `bad=0` on every child (fallow, each worker,
scanner, drain).

Startup cost:

| workers | launcher | in-process @ 5 GB parent RSS |
|---|---|---|
| 4 | 0.39 ms | — |
| 8 | 0.65 ms | 1774 ms |
| 28 | **2.49 ms** | — |

Launcher RSS steady at **2.7 MB**. Against the in-process path: 8.5 ms at 0 MB
parent RSS, 1774 ms at 5 GB.

Build and run it like this:

```bash
SO=$(python3 -c "import sys;sys.path.insert(0,'/mnt/ramdisk/forkrun/python');\
from forkrun._bindings import find_substrate;print(find_substrate())")
gcc -O2 -o /tmp/opencode/fr_cr /mnt/ramdisk/forkrun/forkrun_cleanroom.c \
    -ldl -lpthread
/tmp/opencode/fr_cr --so "$SO" \
  --plugin /tmp/opencode/mlbench/ml_plugin_light.so --func ml_process_light \
  --workers 8 --lines 0 --src 0 --result 1 --verbose \
  0</mnt/ramdisk/numa1/ml/light_5M.jsonl > /tmp/opencode/o.bin
```

---

## 3. Scope limits (deliberate, not oversights)

The launcher covers **materialized file input + C plugin only**. It does *not*
yet handle:

- **Streaming input.** Needs the ingest child *and* the reactor's incremental
  spawn (`_reactor.py` spawns workers as the scan advances; a forked launcher
  cannot do that — the whole point of exec is that you no longer share the
  parent's Python state).
- **Python UDF callables.** A UDF is a live Python closure. Crossing `exec`
  destroys it. Structurally impossible; do not attempt it. Coverage stays
  materialized + C plugin.
- **Fault injection / poison retry.** The test suite drives hooks through the
  Python path that the launcher does not yet implement.

---

## 4. Work order

### Task A — land the init dedup (mostly done, verify it)

`python/forkrun/run.py` had the idiom

```python
pre_fds = snapshot_fds()
lib = load()
_core_init_engine(lib, lines=lines or 0, bytes_=bytes_ or 0, spec=_spec)
engine_fds = snapshot_fds() - pre_fds
```

repeated verbatim at **10 sites** (8 UMA, 2 NUMA — the NUMA two add
`num_nodes=num_nodes, numa_map=numa_map`).

**This is a correctness fix, not tidiness.** `engine_fds` is the keep-set every
child scrubs to. A site computing it differently leaks descriptors into that
one path's workers and nowhere else — invisible to the entire rest of the suite,
because no other path is wrong.

The replacement `_init_engine_and_fds(*, lines, bytes_, spec, num_nodes=None,
numa_map=None)` was written, verified, and **committed in `44b2128c`**.

Status at handover: syntax OK, smoke test byte-identical to HEAD, suite
`failures=2` — both understood (§5). **Task A is effectively done**; your only
job here is to confirm it, not to write it.

### Task B — wire the launcher in (the real work)

**Do one path, not eleven.** Start with the *materialized `map()` + C plugin*
path, which the launcher already fully covers.

- Add `FORKRUN_CLEANROOM` env flag, default **off** for now.
- Build the launcher as part of the normal build (`Makefile.substrate`), or
  ship it as a prebuilt in the wheel. Decide, and write down why.
- Route the chosen path through the launcher; leave the other 9 alone.
- **Pass `--lines 0`** to mean engine default. See §6.1 — this is the single
  most expensive mistake available to you.
- Run the **full suite twice**: flag on, flag off. Both must be green.
- Only after that, flip the default to on and re-run.

### Task C — then, and only then

- Streaming support (hard — see §3).
- Default-on flip.
- Benchmark the integrated path, not the standalone binary. The numbers in §2
  are launcher-vs-in-process microbenchmarks and are **not** end-to-end numbers.
  Do not put them in the release tables.
- Update `DOCS/CLEANROOM_DESIGN.md` to point at the working implementation.

---

## 5. Working-tree state at handover

| item | state |
|---|---|
| `python/forkrun/run.py` | **committed** `44b2128c` — the 10-site dedup, +46/−60 |
| `forkrun_cleanroom.c` | committed `1b0d7192`, pushed |
| `DOCS/CLEANROOM_HANDOVER.md` | this file, committed `44b2128c` |
| working tree | **clean** |

Full suite over the dedup: **668 tests, `failures=2`**
(`test_release_check_passes` + `test_c_drain_stream_matches`).

`test_c_drain_stream_matches` is **not** a regression from the dedup — verified
by stashing it and running 5x both ways: **F F F F / F F F F**, identical.
But note the odd shape: it **passes inside the full suite and fails 5/5
standalone**. That is an order-dependence, not a load flake, and it is a
separate smell worth chasing. Confirm the baseline yourself before you start.

---

## 6. Gotchas — these cost real time

### 6.1 `--lines 1` does NOT mean "lines mode"

It means **one line per batch**.

The launcher was initially hardcoded to `--lines 1`. On a 5M-line corpus that is
5M batches, producing **exactly 80,000,000 bytes** of framing overhead. The
symptom — output 431,572,103 bytes vs. a reference of 351,572,103 — looked
exactly like catastrophic data corruption or an fd leak, and sent me hunting
for both.

The tell was that the excess was a suspiciously **round 80 million** and scaled
linearly with worker count. Framing overhead, not duplicated records.

Python passes `lines=lines or 0` — **0 for engine default**. Sweeping the value:

| `--lines` | bytes |
|---|---|
| 1 | 431,572,103 |
| 64 | 352,822,103 |
| 1024 | 351,650,231 |
| 4096 | 351,591,639 |
| 0 (default) | 351,592,343 |

**Always pass `--lines 0`.**

### 6.2 Children MUST scrub fds

Python's fork helpers call `scrub_fds(keep)` in **every** child. The launcher
initially skipped it, so each worker inherited every other worker's `out_fd` and
the shared signal write end.

Fixed with `scrub_closem_others()`. This is also a genuine fd-leak fix — do not
regress it.

### 6.3 The lost-tail signature

Four tests intermittently **truncate the tail** of their output under load:

- `test_none_and_empty_output_parity`
- `test_spawn_v1_stream_ordered`
- `test_c_drain_identical`
- `test_reactor_stream_drain_parity`

Note `test_c_drain_identical` flaked once *immediately after* a revert, which
made it look like the revert broke something.

**This is the same signature as the W-GATE2 data-loss incident** that was
reverted in `b845a96b`. It is unresolved and it is a **live correctness risk**.
Do not paper over it, do not add retries, and do not call it flaky without
understanding it. Get a repro under load before you touch anything else.

### 6.4 Benchmark harness contamination — already fixed, don't reintroduce

Importing the competitor frameworks in-process cost ~214 MB parent RSS and
**~34%** of forkrun's measured throughput. Fixed by: `--isolate`, per-system
child processes, a shared pre-generated corpus, and lazy framework detection.

If you benchmark, run systems sequentially with exact record checks. Note that
the forkrun medium/heavy cells differ from clean cell results by only ~±2%, so
earlier "probably low by 30%" claims about *those* rows were wrong and the
docs were corrected. §0's light column was the one that was genuinely wrong and
is now corrected.

---

## 7. Open issues

### 7.1 The four load-sensitive tests (§6.3)

**Highest priority.** Unresolved lost-tail behaviour.

### 7.2 Release bookkeeping — owner action, not yours

These still read v3.6.0 and block `test_release_check_passes`:

| file | current |
|---|---|
| `/mnt/ramdisk/forkrun/META` | `VERSION: v3.6.0` |
| `/mnt/ramdisk/forkrun/python/release_check.py` | `PROJECT_VERSION = "v3.6.0"` |
| `/mnt/ramdisk/forkrun/DOCS/CHANGELOG.md` | `## v3.6.1 — unreleased` |

Bump to v3.6.1 / `0.17.0` to clear the gate.

### 7.3 Real NUMA

Fake NUMA (`0-3`) is currently booted. **Multi-socket validation needs real
hardware** — flag it, do not fake a result.

### 7.4 Do not reintroduce W-GATE2

`b845a96b` reverted an unsafe `ring_copy_main` / relaxed gate. Do not treat
`ingest_complete` as a truthful drain signal.

### 7.5 `test_c_drain_stream_matches` — ROOT CAUSED, see MEMORY.md `W-STREAMDRAIN`

**CORRECTION.** An earlier version of this section claimed the test was
"order-dependent: passes in the suite, fails 5/5 standalone." **That was
wrong**, and the reason is worth keeping: running a single test as
`python3 -m unittest test_c_drain.TestCDrainStream...` from `python/`
fails with `ModuleNotFoundError` — the 5/5 "failures" were measuring an
**ImportError**, not the test. Run single tests from `python/tests/`, or
cd there; the test passes standalone.

The test genuinely fails ~5-10% of runs under suite load, for the same
root cause as §6.3: a duplicate worker `wid` in the streaming NUMA spawn
path. Two processes share one output memfd (`out_fds[wid]`) while another
wid's memfd is never drained — emitted, acked, and never delivered.

Confirmed by measurement, not inference:
- `fr_py_drain_loop` exits `rc=0` with **nothing undrained** — drain is fine
- workers claim `18890` and emit `18890` **in failing runs too** (delta=0)
- `map()` 30/30 clean; `c_drain=False` 25/25 clean — streaming-only
- `gc.disable()` still fails 3/40 — **GC is not implicated**
- scanner `total_scanned` always sums to 2000 — publication is complete

Dead ends: GC, drain-side loss, scanner under-publication, and the
frozen engine core are all excluded. Don't re-tread them.

Repro loop and full evidence: `MEMORY.md`, section `W-STREAMDRAIN`.

---

## 8. Useful commands

```bash
# full suite (takes ~465s)
cd /mnt/ramdisk/forkrun/python
python3 -m unittest discover -s tests -p "test_*.py"

# run it detached so a tool timeout can't kill it
setsid nohup bash -c 'python3 -m unittest discover -s tests -p "test_*.py" \
  > /tmp/opencode/suite.txt 2>&1; echo DONE >> /tmp/opencode/suite.txt' \
  </dev/null >/dev/null 2>&1 & disown

# locate the substrate
python3 -c "import sys;sys.path.insert(0,'/mnt/ramdisk/forkrun/python');\
from forkrun._bindings import find_substrate;print(find_substrate())"
```

---

## 9. Design reference

`/mnt/ramdisk/forkrun/DOCS/CLEANROOM_DESIGN.md` — architecture, fd contract,
risks, and the `frun.bash` reference implementation.

The Bash reference execs **before** `ring_init`, passes loadables and state via
fds/memfds, and sets `_FR_IN_CLEANROOM=1`. The C launcher should match its
semantics. Bash is the specification, not the launcher.

`/mnt/ramdisk/forkrun/MEMORY.md` — measurements, rejected approaches,
corrections, and open risks accumulated over this project.

---

## 10. Judgement calls you should re-check

These were my calls; you have different information and may disagree:

- **Not wiring the launcher into all 11/10 sites at once.** Adding a cleanroom
  branch to every executor path at the same time is the "half-moved pipeline"
  anti-pattern, and it is exactly how a default-on flag ships with unverified
  fault-tolerance behaviour. One path, proven, then widen.
- **The 20,240-byte (0.006%) residual is treated as correct.** Output is
  byte-stable across 4/8/28 workers and `bad=0` on all children. I believe it is
  per-batch framing from marginally different batch boundaries between the
  launcher and in-process paths. **I did not prove that.** If you need exact
  equality, this is the first thing to chase — compare record counts, not byte
  counts, and look at the tail.
- **Default-on was not adopted** despite the user clearly preferring it. Correct
  behaviour under fault injection is unverified on the cleanroom path.