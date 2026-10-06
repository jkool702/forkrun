# forkrun v3.6.1 — release notes

**Python frontend 0.16.0 → 0.17.0.** Engine tag `v3.6.1`.
Released 2026-10-06. 167 commits, 53 files, +9,125 / −929.

Verified on a UMA boot (single NUMA node, `shmem_enabled=always`):

| suite | result |
|---|---|
| Python suite, `FORKRUN_CLEANROOM` unset | **726 passing**, 7 skipped |
| Python suite, `FORKRUN_CLEANROOM=1` | **726 passing**, 7 skipped |
| Bash `test_c_plugins.sh` / `test_frun.sh` | **96/96** |
| Bash `test_frun_comprehensive.sh` | **264/264** |
| Bash `test_frun_security.sh` | **101/101** |
| `python/release_check.py` | **21/21 green** |

The 7 skips are the tests that require multi-node NUMA.

---

## ⚠ Breaking change: `map()` now returns `memoryview`, not `bytes`

`output="view"` is now the **default**. Results are zero-copy
`memoryview` slices over the mapped result stream instead of `bytes`
copies — 2.0–2.3× faster on the collect path, with no per-record
allocation.

This will break code that assumes `bytes`.

```python
out = forkrun.map(fn, path)          # memoryview records in 0.17.0
```

**What still works unchanged:** `len()`, slicing, iteration,
`.tobytes()`, `.hex()`, `bytes(rec)`, `==` against `bytes` in both
directions, writing to a file object, and the buffer protocol
(`socket.send`, `mmap.write`, …).

**What needs a change:** `x in rec` and `isinstance(rec, bytes)` — the
first raises `NotImplementedError: memoryview: unsupported format <B`,
and the second silently returns `False` where it used to return `True`.
Both are fixed by `forkrun.materialize(rec)` or `output="bytes"`.

**Escape hatches, in order of preference:**

```python
forkrun.map(fn, path, output="bytes")        # per-cell: go back to copies
rec = forkrun.materialize(rec)                # per-record: copy one record
```

Prefer `output="bytes"` over sprinkling `materialize()` — it is faster
than copying selectively. Reach for `materialize()` only when a few
records must outlive the mapping.

### One thing to know about views

Lifetime is **per result stream, not per record**. One surviving view
keeps the whole mapping resident:

```python
big  = forkrun.map(fn, path, output="view")   # maps the full result
keep = [r for r in big if r["uid"] == 7]      # still maps ALL of it
```

Filter with `materialize()` on what you keep if you are filtering a
large stream. This is inherent to zero-copy, not a leak — the
alternative is the copy `output="bytes"` always performs.

---

## Performance

**Workers no longer wait on an artificial 2.0 s timer.** The parent now
forks workers as soon as its own setup is done, using only the natural
latency the scanner already gets. When the pre-flight scan is cut short
(an early worker arrives), the geometric batch ramp resumes from where it
was and doubles from there, so it converges without the delay.

Every measured row improved; the rows that gained most are the ones that
fork, which is what you would expect from removing fixed startup cost.

| workload (5M, UMA, file) | v3.6.0 | v3.6.1 | |
|---|---|---|---|
| light, C plugin, view | 10.16M rec/s | **10.18M** | +0.2% |
| light, C plugin, bytes | 7.26M | **7.84M** | +8.0% |
| medium, C plugin, bytes | 1.95M | **2.12M** | +8.7% |
| heavy, C plugin, view | 797k | **850k** | +6.6% |
| small input (2,816 lines) | 0.108 s | **0.026 s** | **4×** |

The small-input case is the headline: a fixed wait dominated the whole
run, so removing it is worth 4× there. There is a cliff at zero — any
delay of 50 ms or more costs the full amount, so this is not a tunable
dial you want halfway.

Full 48-cell matrix in `python/benchmarks/results/RELEASE_v3.6.0.md` §0;
raw logs under `python/benchmarks/results/raw/`.

### A benchmark caveat that is not a footnote

**The file-vs-pipe result flips sign with NUMA topology.** On UMA a pipe
is 13–21% *faster* than a file on the C-plugin rows; on a 4-node
`numa=fake=4` boot a pipe *costs* 5–8%. Same code, same corpus, both
16/16 cells exact. File input already engages the multi-node ingest path
on 4 nodes, leaving a pipe less to win; on UMA there is no such path for
a file to borrow.

If you are quoting or relying on a streaming-input number, name the
topology. The tables carry both.

---

## Correctness

**`poisoned_batches` is now actually populated.** The cleanroom
reported how many batches poisoned but not *which*, so the index list
came back empty whenever poison happened — the same silent gap the
count was added to close. Each worker now relays its poisoned batch
indices over the stats channel.

Because that relay is bounded, a short list is no longer
indistinguishable from a complete one:

- `stats["poisoned_batches_truncated"]` is new — `True` when the list is
  knowingly incomplete.
- `map()` warns once when it is set, naming how many indices are missing.
- `poisoned` itself is always exact either way.
- The flag is always `False` on the in-process path, which keeps every
  index.

**Cleanroom collector, one implementation.** It used a second,
hand-copied result collector built on stdlib `mmap`, which holds a
descriptor for the life of the mapping — contradicting the invariant the
API docs already state. It now uses the same mapping helper as the
in-process path, which also prefaults and requests hugepages. The two
parse loops are collapsed into one.

**A torn final record is no longer accepted as a clean end of stream.**
The cleanroom collector returned normally on a short trailing payload,
so truncated output looked well-formed and was merely short. It now
warns. It deliberately does not raise: a worker killed mid-record
legitimately leaves a torn tail that `strict_poison` and the poison counts
already report.

**`c_drain` could corrupt a stream (opt-in path).** On a mid-record
`pread` error the drain resumed without advancing its cursor, but the
bytes already copied had been *punched* out of the worker memfd — so the
next signal re-read the record header from a hole and re-emitted the
record as a zero-length one. Two further paths could strand a worker
while still reporting success. All three now fail the drain explicitly.

---

## Internal

- The pre-flight scan no longer spin-sleeps while waiting for ingest;
  it blocks on the ingest eventfd with a 2 ms bound.
- `malloc_trim` removed before fan-out — it broke worker-death recovery.
- Quadratic and per-record parent work removed from the drain path.
- `ring_loadables` embedded blobs refreshed.
- Bash test suites now pin `forkrun v3.6.1` and are part of the release
  gate. **Run `UNIT_TESTS/test_all.sh` in the foreground** — a
  backgrounded shell inherits SIGINT-ignored and the M1a test reports a
  false failure (see `UNIT_TESTS/test_frun_comprehensive.sh:2011`).

---

## Upgrade notes

1. **Read the breaking-change section above first.** If your code does
   `isinstance(rec, bytes)` or `x in rec`, it needs `output="bytes"` or
   `materialize()`.
2. `stats` gained one key, `poisoned_batches_truncated`. Code that
   compares the stats dict for exact equality will need updating.
3. The cleanroom remains **opt-in** (`FORKRUN_CLEANROOM=1`) and is still
   a beta: narrower envelope than the default path (plugin mode, single
   node, `order="index"` for `map()`). Nothing changes for you unless
   you turned it on.
4. No engine-level breaking changes. Bash frontend users need no action;
   `frun -V` reports `forkrun v3.6.1`.

Full detail, including the pre-flight and stall investigations with
measurements, is in `DOCS/CHANGELOG.md`.
