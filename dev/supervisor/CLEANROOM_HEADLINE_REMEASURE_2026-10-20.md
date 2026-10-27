# Cleanroom headline re-measurement — 2026-10-20

**Question.** Has the recent cleanroom work moved the published headline
benchmark numbers in `python/benchmarks/results/RELEASE_v3.6.0.md` §0?

**Short answer.** **Yes — the C-plugin row moved, upward, by about 30%.**
Against the published 48-cell grid log (same harness, same corpora, same
cells), the forkrun C-plugin row went from 1,084 MB/s to 1,392 MB/s on
light 5M (**+28.4%**), 1,241 MB/s to 1,641 MB/s on medium 5M (**+32.2%**)
and 1,135 MB/s to 1,423 MB/s on light 20M (**+25.4%**).

**The Python-UDF row did not move at all** (−2.7% to −4.7%, inside the
box's day-to-day drift; the paired same-session effect is +0.1% to
+0.2%). It *cannot* move on the current benchmark, because that row
measures the in-process `mode="python"` route with a live callable, and
the cleanroom's `map-udf` route has a different calling contract
(`bytes -> bytes`, not `Batch -> list`). §5.

The movement is **entirely** the cleanroom: the published-era commit and
today's cleanroom-off build measure the same (§4.4), so the notification
pipe and the C-drain fix are neutral on these cells.

Everything below was measured on this box, UMA (`nodes=1`), 28 workers,
one process per cell, median of 3 trials per cell, 3 interleaved reps per
arm. Raw data and drivers: `/tmp/opencode/stream_cells_ab.json`,
`/tmp/opencode/stream_cells_20m.json`, `/tmp/opencode/oldbuild_ab.json`.

---

## 1. Why bytes/s, not records/s

The three variants differ in **record size**, not in work per byte:

| variant | records | bytes | bytes/record |
|---|---|---|---|
| light | 5,000,000 | 532,711,015 | 106.54 |
| medium | 4,997,892 | 2,347,403,909 | 469.64 |
| heavy | 4,997,982 | 6,720,381,299 | 1344.07 |

So records/s varies about **10x** across the three variants
(10.59M -> 1.05M in the published table) while throughput in bytes/s is
nearly flat (1,129 / 1,509 / 1,414 MB/s). A records/s column therefore
compares light against heavy and calls the result a regression. The
published table already reports both, for this reason.

The published MB/s column is **input** bytes/s; its own arithmetic
confirms it (1,129 MB/s / 10.59M rec/s = 106.6 B/record, which is the
light corpus's bytes/record). MB/s here is decimal (1 MB = 10^6 B), as
the published table states.

**Consequence for this study:** the same byte scale is compared against
the same byte scale. The 20M-light corpus was regenerated at
**2,130,842,196 bytes** — byte-identical to the published "corrected
light column" corpus — which puts it within 10% of medium-5M's
2.35 GB, so light-20M and medium-5M are comparable in bytes.

---

## 2. Method

The harness is the repository's own: `python/benchmarks/results/stream_cells.py`
— **one cell per process**, which the harness's docstring calls the reason
its numbers are trustworthy ("An earlier all-in-one harness returned 0
records for an arm whose isolated run was correct"). Each cell ends in an
**exactness guard**: it exits non-zero if the record count is not exactly
the expected count.

Three arms, all the same build and the same corpora, interleaved per rep:

| arm | `FORKRUN_CLEANROOM` | what it selects |
|---|---|---|
| `A_inprocess` | `0` | no cleanroom route — everything in-process |
| `B_default` | unset | today's default: the `map-plugin` route, on the cleanroom |
| `C_all_routes` | `1` | every eligible route, including the new `map-udf` |

`A_inprocess` is the configuration the published table measured.

**B and C must agree on every plugin cell, and they do.** The route
selector narrows and never widens (`forkrun/run.py::_cleanroom_route_enabled`):
with `FORKRUN_CLEANROOM=1` the selector is the legacy "every served
route" (`routes is None -> return True`), and unset selects the default
`("map-plugin",)`. For a `map(mode="plugin")` call both arms therefore
enable the *identical* route, so any difference between them is
measurement noise. The data agrees to within 0.2% on the medium cell.

---

## 3. The noise floor, measured

Spread across the 3 reps of each cell (max-min over the median):

| cell | A | B | C |
|---|---|---|---|
| light plugin | **29%** | **51%** | 2% |
| medium plugin | 1% | 0% | 0% |
| light udf | 1% | 1% | 1% |
| medium udf | 2% | 0% | 1% |

The **light-5M cell is unusable** for anything but a large effect: it
runs in 0.38–0.78 s, which is spawn-cost dominated — the harness's own
docstring says so ("the lightest published corpus is ~0.5s, which is
dominated by spawn cost and INVERTS worker-scaling conclusions"). Its
51% spread is larger than the effect being asked about.

The **medium cell is the reliable one** (0–1% spread), and the 20M
light cell is the steady-state light measurement.

---

## 4. Results

Median MB/s (input bytes/s) over 3 interleaved reps; `rec/s` is derived
from the corpus's actual bytes/record; **vs pub** is against the
published §0 number for the same cell.

### 4.1 The C-plugin row (the cleanroom-eligible route)

| arm | variant | corpus | MB/s | rec/s | spread | vs published |
|---|---|---|---|---|---|---|
| A in-process | light | 5M | 1078 | 10.12M | 29% | −4.5% |
| **B default** | light | 5M | **1392** | **13.07M** | 51% | **+23.3%** |
| C all routes | light | 5M | 1394 | 13.08M | 2% | +23.5% |
| A in-process | medium | 5M | 1231 | 2.62M | 1% | −18.4% |
| **B default** | medium | 5M | **1641** | **3.49M** | 0% | **+8.7%** |
| C all routes | medium | 5M | 1638 | 3.49M | 0% | +8.6% |
| A in-process | light | 20M | 1088 | 10.21M | 4% | — |
| **B default** | light | 20M | **1423** | **13.35M** | 5% | **+25.4%** |
| C all routes | light | 20M | 1435 | 13.46M | 3% | — |

The 20M row's "+25.4%" is against the published **corrected light
column** (10.65M rec/s, UMA, on the byte-identical 2,130,842,196 B
corpus). The 5M-light row's spread (29–51%) makes it indicative only;
the **medium cell (0–1% spread)** and the **20M cell (3–5% spread)** are
the trustworthy ones, and they agree: **+30.7% and +33.3%**.

**Provenance caveat, stated because it cuts in the conservative
direction.** The published 20M column's forkrun rows came from the
48-cell grid **over a pipe** ("forkrun's streaming numbers come from the
48-cell grid (map over a pipe)", `ml/bench_streaming_competitors.py`),
and this study measured the **file** cells. The grid's own pipe-vs-file
figure is "median 104% of file" — the pipe is a few percent *faster* —
so comparing a file number against a published pipe number understates
the improvement. The published §0 5M rows are file rows from
`bench_ml_pipeline.py`; the cells here are file rows from
`stream_cells.py`; §4.4 measures that harness pair directly.

### 4.2 The Python-UDF row (the control)

| arm | variant | corpus | MB/s | rec/s | spread | vs published |
|---|---|---|---|---|---|---|
| A in-process | light | 5M | 194 | 1.82M | 1% | −4.1% |
| **B default** | light | 5M | **197** | **1.85M** | 1% | −2.5% |
| C all routes | light | 5M | 196 | 1.84M | 1% | −3.0% |
| A in-process | medium | 5M | 380 | 0.81M | 2% | −8.6% |
| **B default** | medium | 5M | **381** | **0.81M** | 0% | −8.5% |
| C all routes | medium | 5M | 381 | 0.81M | 1% | −8.4% |
| A in-process | light | 20M | 194 | 1.82M | 0% | — |
| **B default** | light | 20M | **194** | **1.82M** | 0% | **−4.7%** |
| C all routes | light | 20M | 191 | 1.79M | 0% | — |

**The UDF row does not move: +0.1% to +0.2% in the paired measurement,
and −2.5% to −8.5% against the published numbers** (drift, not effect —
the paired A→B delta is the effect, and it is zero).

### 4.3 The effect, isolated

| cell | A → B (the cleanroom default-on) | B → C (must agree) | published → A (everything else) | published → B (end to end) |
|---|---|---|---|---|
| light 5M plugin | **+29.1%** | +0.1% | −4.5% | +23.3% |
| medium 5M plugin | **+33.3%** | −0.2% | −18.4% | +8.7% |
| light 20M plugin | **+30.7%** | +0.8% | — | +25.4% |
| light 5M udf | +1.7% | −0.6% | −4.1% | −2.5% |
| medium 5M udf | +0.2% | +0.1% | −8.6% | −8.5% |
| light 20M udf | +0.1% | −1.7% | — | −4.7% |

**B → C agrees to within 1% everywhere**, which is the arithmetic
confirmation that the two arms select the identical route for a plugin
map — the 2x gap in the first rep of the light-5M cell was noise, as the
51% spread of that cell predicted.

### 4.4 The published-era build, in the same harness and session

`ce17b0a4` (the commit the published §0 table was measured at) built in
a detached worktree, its substrate compiled, and measured through the
**same** cell harness, interleaved with HEAD's A and B arms. The
workload is identical — `git diff ce17b0a4 HEAD` over
`benchmarks/ml/plugins/` and `ml_payload.py` is **empty**, so only
forkrun differs.

| cell | old `ce17b0a4` | A in-process (HEAD, cleanroom off) | B default (HEAD, cleanroom on) |
|---|---|---|---|
| light plugin, 5M | 1038 / 1043 / 1036 MB/s | 1038 / 1052 / 1033 MB/s | **1362 / 1360 / 1353 MB/s** |
| medium plugin, 5M | 1164 / 1198 / 1203 MB/s | 1193 / 1182 / 1181 MB/s | **1537 / 1561 / 1535 MB/s** |

Medians: light 1038 → 1038 → **1360**; medium 1198 → 1182 → **1537**.

**old ≈ A (0.0% on light, −1.3% on medium).** So the post-2026-10-02
work that was *not* the cleanroom — the 4 KiB notification pipe, the
C-drain reactor fix — is **neutral** on these cells. It neither helped
nor hurt.

**A → B is the cleanroom, and it is the whole movement: +31.0% (light),
+30.1% (medium).** Equivalently old → B: +31.0% and +28.3%.

That is the cleanest statement of the result available, because it holds
the harness, the corpora, the machine and the session fixed and changes
only the code.

**But the cell harness and the published harness disagree on the same
commit.** The old build gives 1198 MB/s on medium here; the published
§0 says 1509 MB/s for the same commit, corpus and plugin. §4.5
resolves that.

### 4.5 The published baseline, in the same harness

The published headline has **two methodologies**, and they are not the
same numbers:

| published source | harness | light | medium |
|---|---|---|---|
| §0 table (2026-10-02, `ce17b0a4`) | `bench_ml_pipeline.py` | 1,129 MB/s (10.59M rec/s) | 1,509 MB/s (3.21M rec/s) |
| 48-cell grid (`results/raw/stream_cells_uma_v361_stall0.log`) | `stream_cells.py` | **1,084.29 MB/s** (10.18M rec/s) | **1,241.49 MB/s** (2.64M rec/s) |
| 20M corrected light column (`results/raw/stream_cells_light_20M_UMA_v361.log`) | `stream_cells.py` | **1,134.68 MB/s** (10.65M rec/s) | — |

The grid logs are the raw measurement behind the published grid, and
they are **the same harness and the same corpora this study used**. The
published-era commit re-measured today reproduces them within 4%:

| grid cell | published grid | old build, today | delta |
|---|---|---|---|
| light plugin 5M file | 1084.29 MB/s | 1038 MB/s | −4.3% |
| medium plugin 5M file | 1241.49 MB/s | 1198 MB/s | −3.5% |

So the box is within ~4% of its 2026-10-08 state, and the grid is the
sound baseline.

**The §0 table's own numbers are not reproducible today in their own
methodology.** `bench_ml_pipeline.py` at `ce17b0a4`, its own
`bench_forkrun_plugin` row, in a fresh process, on the published commit,
on this box, today: **1055 MB/s light, 1199 MB/s medium** — against the
published 1129 / 1509 (**−6.5% and −20.5%**). The same harness run in
its full published configuration (all rows in order, plugin row last)
gives **1027 MB/s** on medium, because the rows before it leave a fat
parent behind.

**Two lessons, both actionable:**

1. **The §0 table's absolute numbers and the grid's absolute numbers
   differ by 4% (light) and 22% (medium) for the same day, the same
   commit and the same workload.** §0 quotes the `bench_ml_pipeline`
   numbers; the grid quotes the `stream_cells` numbers. **A delta
   quoted across the two is a methodology delta, not a code delta.**
2. **A published number measured on a different day is not a baseline.**
   The only sound baseline is the published COMMIT, re-measured in the
   same session as the candidate — which is exactly what §4.4 did, and
   what the grid log provides.

**Session-to-session spread.** The same arm (B default, medium plugin)
measured **1641 MB/s** in the 5M A/B run and **1537 MB/s** in the
old-build run — a **6.3%** session offset, on top of the 0–1.7%
within-session spread. Even a single-session comparison carries a few
percent of session noise even when every cell is tight.

---

## 5. The Python-UDF row cannot move — and why

Two independent reasons, both structural, not incidental:

**(a) The benchmark's UDF row is not on a cleanroom route.**
`bench_ml_pipeline.py::bench_forkrun` calls
`forkrun.map(payload, path, workers=..., order="index")` with
`payload = FORKRUN_PAYLOADS[variant]` — a **live Python callable**, and
no `mode=`. The cleanroom's route identifier is derived from the *raw*
mode (`_cleanroom_route_for`: `map-plugin` / `map-udf` / `map-spawn` /
`stream-plugin` / `stream-udf`), and a live callable under the default
`mode="python"` resolves to **no route at all**. The cleanroom cannot
serve it, so it cannot move it.

**(b) The two routes have different calling contracts.**
The cleanroom's `mode="udf"` route hands the callable **one `bytes`
object** and requires **bytes** back:

```c
/* python/forkrun/fr_udf.c :: fr_udf_call */
PyObject *arg = PyBytes_FromStringAndSize(input, len);
PyObject *res = PyObject_CallFunctionObjArgs(cached_fn, arg, NULL);
...
if (!PyBytes_Check(res)) { set_error("%s returned %s, not bytes", ...); }
```

The in-process `mode="python"` executor instead hands it a
`forkrun._batch.Batch` (offsets, line counts, metadata as well as data).
The benchmark's payload is written to the **Batch** contract:

```python
# python/benchmarks/ml/ml_payload.py
def forkrun_payload_light(batch):
    return _forkrun_batch(bytes(batch.data), process_event_light)
```

So re-expressing the published row as `mode="udf"` is **not a drop-in** —
it needs a different payload function, one that takes bytes and returns
bytes. The repository already documents this trap, and the trap is
nasty: under the default `on_error="retry"` a contract mismatch produces
**an empty result and no exception** (the cause is visible only through
`forkrun.last_run_stats()["poisoned"]`).

> `python/tests/test_udf_mode.py::test_the_fallback_adapts_the_differing_udf_contracts`
> — *"a mode='udf' callable handed a Batch raises AttributeError on
> b.upper(), every batch retries and poisons, and the caller sees an empty
> result with nothing naming the cause. That is exactly what happened
> before the adapter."*

**So the actionable gap is on the benchmark side, not the product side:**
the published table has no row that exercises the cleanroom's `map-udf`
route, because the benchmark's only Python-UDF row uses the other
contract.

---

## 6. What this means for the published table

### 6.1 The C-plugin row has moved, upward — by about 30%

**The primary comparison is against the published grid log**, because it
is the same harness, the same corpora and the same cells (§4.5):

| cell (file source, `view` output) | published grid | today (B default) | delta |
|---|---|---|---|
| light plugin, 5M | 1,084.29 MB/s (10.18M rec/s) | **1,392 MB/s (13.07M rec/s)** | **+28.4%** |
| medium plugin, 5M | 1,241.49 MB/s (2.64M rec/s) | **1,641 MB/s (3.49M rec/s)** | **+32.2%** |
| light plugin, 20M | 1,134.68 MB/s (10.65M rec/s) | **1,423 MB/s (13.35M rec/s)** | **+25.4%** |

**And the same-harness code comparison agrees** (§4.4), because it holds
everything fixed except the code:

| | light 5M | medium 5M |
|---|---|---|
| published-era build `ce17b0a4`, today | 1038 MB/s | 1198 MB/s |
| today's HEAD, cleanroom off | 1038 MB/s | 1182 MB/s |
| **today's HEAD, cleanroom on (today's default)** | **1360 MB/s** | **1537 MB/s** |
| **the cleanroom's contribution** | **+31.0%** | **+30.1%** |

The published-era build and today's cleanroom-off build are
**indistinguishable** (0.0% / −1.3%), so the post-2026-10-02 work that
was *not* the cleanroom — the 4 KiB notification pipe, the C-drain
reactor fix — is **neutral** on these cells. **The cleanroom is the whole
movement, and it is worth about +30%.**

The old build also reproduces the published grid within 4% (§4.5), so
this is a code movement, not a machine movement.

### 6.1a The §0 table's own numbers move less — and that is a methodology artefact

The §0 table quotes the `bench_ml_pipeline.py` methodology, not the grid
(§4.5). Against the §0 table's own numbers:

| published §0 cell | published | today (B default) | delta |
|---|---|---|---|
| light, 5M | 1,129 MB/s (10.59M rec/s) | 1,360–1,392 MB/s (12.8–13.1M rec/s) | +20.5% to +23.3% |
| medium, 5M | 1,509 MB/s (3.21M rec/s) | 1,537–1,641 MB/s (3.27–3.49M rec/s) | +1.9% to +8.7% |
| light, 20M (corrected column) | 10.65M rec/s | 13.35M rec/s | +25.4% |

**The §0 table's absolute numbers are not reproducible today in their own
methodology**: the published commit, published harness, published corpus
and published plugin give 1055 / 1199 MB/s today where the §0 table says
1129 / 1509 MB/s (**−6.5% and −20.5%**). And the §0 numbers and the grid
numbers differ from each other by 4% (light) and 22% (medium) **for the
same day, same commit, same workload**.

**So the against-§0 delta understates the code movement, and the number
that survives both corrections is the same-harness one: the cleanroom is
worth about +30%.**

**Which number should be quoted?** The grid one, because it has a raw
log, a known harness and a baseline that reproduces. The §0 table
should be re-measured wholesale — §6.6 — before any of its absolute
values are quoted again.

### 6.2 The Python-UDF row has not moved

Against the same published grid log:

| cell (file source, `view` output) | published grid | today (B default) | delta | paired A→B |
|---|---|---|---|---|
| light udf, 5M | 202.53 MB/s (1.90M rec/s) | 197 MB/s (1.85M rec/s) | **-2.7%** | **+1.7%** |
| medium udf, 5M | 395.53 MB/s (842k rec/s) | 381 MB/s (811k rec/s) | **-3.7%** | **+0.2%** |
| light udf, 20M | 203.48 MB/s (1.91M rec/s) | 194 MB/s (1.82M rec/s) | **-4.7%** | **+0.1%** |

**The plugin row moved +25% to +32% on the same day, the same harness,
the same corpora and the same cells. The UDF row did not move at all.**
The paired effect is zero, which is the correct result: this row is not
on a cleanroom route (section 5). The small negative delta against the
published grid is within the box's own ~4% day-to-day drift, and the
paired comparison, which is drift-free, shows no movement.

### 6.3 The ratio rows are stale too — and are NOT claimed here

§0's ratio rows ("forkrun C vs Executor 6.46× / 4.03× / 11.17×") are
computed from the forkrun rows and the competitor rows. If forkrun is
25–32% faster and the competitors were not re-measured, those ratios are
now understated — **but no new ratio is claimed here, because no
competitor row was re-measured.** That is a separate job.

### 6.4 The actionable gap is on the benchmark side

The published table has **no row that exercises the cleanroom's
`map-udf` route**, and it cannot have one until the benchmark gains a
payload written to the `mode="udf"` contract (`bytes -> bytes`). The
current UDF row uses the `mode="python"` contract (`Batch -> list`), so
it is structurally outside the cleanroom.

**Proposed work order (not started, deliberately):** add a
`forkrun-udf-<variant>-<w>` row to `bench_ml_pipeline.py` that calls
`forkrun.map("ml_payload:forkrun_payload_<variant>_udf", path,
mode="udf", ...)`, with a new `ml_payload` function implementing the
bytes->bytes contract. That row would be the first published number
produced by the cleanroom's UDF route, and it would also let the table
show the `map-plugin` / `map-udf` pair side by side.

### 6.5 Standing measurement rules this study established

1. **Quote bytes/s.** Records/s varies 10x across light/medium/heavy
   because the records differ in size, not in work.
2. **Do not use the light-5M cell for a question smaller than 2x.** Its
   measured noise floor is 29–51%. The medium-5M cell (0–1%) and the
   20M-light cell (3–5%) are the ones to trust.
3. **Quote the paired A→B delta, not the against-published delta**, when
   attributing an effect. The against-published delta carries 18 days of
   drift; the paired one does not.
4. **Baseline against the published COMMIT, re-measured in the same
   session.** A published number measured on a different day is not a
   baseline — the box drifts ~4% day to day, and the §0 table and the
   48-cell grid disagree by 4% (light) and 22% (medium) for the *same*
   day because they are different harnesses. Where a raw log exists
   (`results/raw/stream_cells_uma_v361_stall0.log`), use it: it is the
   same harness and the same corpora, and it reproduces within 4%.
5. **One benchmark at a time.** The old-build comparison here was
   deliberately chained behind the others rather than run alongside them.
   (One round of this study's runs *was* contaminated by two drivers
   racing; the affected data was discarded and re-measured. See the
   git history of this document.)

### 6.6 What is NOT claimed

- No competitor row was re-measured, so no new ratio is claimed (§6.3).
- The heavy variant was not run (the UDF heavy cells dominate runtime
  and the user skips them); the published heavy column is unexamined.
- The `nodes="auto"` / `numa=fake=4` topology was not re-measured: it
  needs a reboot. The published 20M column shows fake-NUMA ahead of UMA
  (13.52M vs 10.65M rec/s), and today's UMA measurement (13.35M) is now
  at the old fake-NUMA figure — so whether fake-NUMA is still ahead is
  an **open question**, and it is the most interesting follow-up this
  study produced.
- The old-build comparison's scope and result are in §4.4.
- Nothing here changes the product's behaviour. The UDF cleanroom route
  stays **opt-in**, and the default-on decision remains uncommitted and
  blocked on the per-minor release wheel build and the auditwheel
  verdict, exactly as recorded in
  `dev/supervisor/WO_PY_UDF_CLEANROOM_UMA_1_REPORT.md` §7.


---

## 7. Follow-up work orders proposed by this study (none started)

Each is deliberately **not** started here: they are measurement or
benchmark changes, and this document is a measurement record.

**WO-BENCH-REMEASURE-1 — re-measure §0 wholesale, in one session,
against the published commit.**
The §0 table's absolute numbers are not reproducible today in their own
methodology (−6.5% light, −20.5% medium for the published commit), and
they disagree with the 48-cell grid's numbers by 4% and 22% for the same
day. The re-measurement must run the published commit and today's HEAD
in the same session, with the competitor rows, so that every published
row has a same-session baseline.

**WO-BENCH-UDF-ROW-1 — add a `mode="udf"` row to the ML benchmark.**
Write a `ml_payload` function to the `bytes -> bytes` contract and add a
`forkrun-udf-<variant>-<w>` row using
`forkrun.map("ml_payload:<fn>", path, mode="udf", ...)`. That is the
only way the published table can carry a number produced by the
cleanroom's UDF route. The trap to avoid: a `mode="python"`-contract
payload under `mode="udf"` yields an **empty result and no exception**
under the default `on_error="retry"`; the cause appears only in
`forkrun.last_run_stats()["poisoned"]`.

**WO-BENCH-NUMA-1 — re-measure on the `numa=fake=4` boot.**
The published 20M column has fake-NUMA ahead of UMA (13.52M vs 10.65M
rec/s). Today's UMA measurement is 13.35M rec/s, i.e. UMA has caught up
to the old fake-NUMA figure. Whether fake-NUMA is still ahead, and by
how much, is now an open question — and it needs a reboot, so it is the
user's call, not the agent's. This is the most interesting follow-up
this study produced.

**Note on the medium/heavy columns.** The heavy variant was not run: the
UDF heavy cells dominate the grid's runtime and are routinely skipped.
The published heavy column is therefore unexamined here.
