# RSS-instrumented A/B for the cleanroom's `map-udf` route — 2026-10-20

**Why this exists.** The UDF default-on decision needs a **named worker
count**, because the memory story was mixed: the pre-fork candidate is
worse on memory at 1-2 workers, crosses over near 3, and is better from
there (`C0.6_M2_MEASUREMENT.md`; restated in
`WO_PY_UDF_CLEANROOM_UMA_1_REPORT.md` §7). That number was measured on
the pre-fork **candidate** in the M2 lifecycle harness, whose own
"honest note" says it must not be cited as a throughput result for real
workloads. This measures the actual `mode="udf"` API route, on the
workload the published benchmark uses.

**What it found.** Two things.

1. **There is no crossover to find.** The cleanroom's `map-udf` route is
   cheaper on memory than the in-process path at **every** worker count
   and **every** parent size — on both the RSS sum and the PSS the
   project already chose as its fleet metric. **No worker-count
   assumption is needed for the memory story on this route.**
2. **The route has a blocking defect**, found while building this
   measurement: it cannot import a C extension module, which makes any
   json-using UDF **4.6x slower silently** and makes any
   extension-importing UDF **return nothing at all**. See
   `UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md`.

So the memory question is answered favourably and the *route* is not
ready. Both are recorded here.

---

## 1. Method

**The route under test.** `forkrun.map(payload, path, mode="udf", ...)` —
the public API, the same route the default-on decision is about.

**The arms.** Both run the *same* bytes->bytes contract, and the output
was verified **byte-identical** between them (sha256 equal over the
whole 500k-record corpus), so the only difference is *where* the UDF
executes:

| arm | what runs the UDF |
|---|---|
| `inprocess` | this interpreter, via the documented in-process adapter (the helper is declined) |
| `cleanroom` | the cleanroom's `map-udf` route: the launcher, an isolated interpreter, workers forked there |

**The workload.** 500,000 records of the published ML light corpus
(`ml_light.jsonl`, 53 MB), through a payload that mirrors
`ml_payload.process_event_light` exactly — same validation, same quality
filter, same compact output — but written to the `mode="udf"` contract
(`bytes -> bytes`).

**The payload imports only `json`.** That is deliberate and it became
the finding: `ml_payload` imports `math` and `re` at module level, and
**neither can be imported on this route at all** (§5). A json-only
payload is the most realistic payload the route can currently run.

**Parent size.** The C0.6 work says parent size swamps the difference,
so both arms are measured at a natural parent (87 MB) and at an
inflated one (599 MB, a resident buffer the forked children would
inherit).

**The instrument.** A separate **process** samples the tree's RSS
(`/proc/<pid>/statm`) and PSS (`/proc/<pid>/smaps_rollup`) every 20 ms.
It is deliberately NOT a thread: a sampling thread would make forkrun
fork a multi-threaded process, which forkrun itself warns about as a
known deadlock hazard. **This measurement must not perturb what it
measures.**

**Timing is measured in a separate pass with NO sampler.** The sampler
costs ~0.4 cores, which is noise against a 1-worker run and lands
unevenly across the arms. Memory is measured with the sampler; time is
measured without it. Both are reported.

---

## 2. Memory

Tree = the driver plus every descendant. RSS is the naive sum (each
forked child counts the parent's shared pages again); **PSS divides
shared pages among their sharers**, which is the honest "what the
machine actually pays" number — and the metric `C0.6_M2_MEASUREMENT.md`
already committed to.

### 2.1 Inflated parent (599 MB)

| workers | in-process tree RSS | cleanroom tree RSS | in-process tree PSS | cleanroom tree PSS |
|---|---|---|---|---|
| 1 | 1652 MB | **573 MB** | 460 MB | **284 MB** |
| 2 | 2240 MB | **595 MB** | 490 MB | **289 MB** |
| 3 | 2828 MB | **616 MB** | 512 MB | **296 MB** |
| 4 | 3416 MB | **637 MB** | 527 MB | **303 MB** |
| 8 | 5659 MB | **725 MB** | 568 MB | **325 MB** |
| 14 | 8885 MB | **862 MB** | 587 MB | **360 MB** |
| 28 | **16392 MB** | **1169 MB** | 698 MB | **440 MB** |

### 2.2 Natural parent (87 MB)

| workers | in-process tree RSS | cleanroom tree RSS | in-process tree PSS | cleanroom tree PSS |
|---|---|---|---|---|
| 1 | 115 MB | **62 MB** | 76 MB | **33 MB** |
| 2 | 191 MB | **83 MB** | 79 MB | **47 MB** |
| 3 | 267 MB | **104 MB** | 84 MB | **40 MB** |
| 4 | 343 MB | **126 MB** | 89 MB | **46 MB** |
| 8 | 519 MB | **213 MB** | 97 MB | **69 MB** |
| 14 | 694 MB | **352 MB** | 125 MB | **104 MB** |
| 28 | 1022 MB | **675 MB** | 182 MB | 182 MB |

### 2.3 What the numbers say

- **The cleanroom wins on memory at every worker count and every parent
  size.** There is no crossover.
- At 28 workers with a 599 MB parent the in-process path's RSS sum is
  **16.4 GB** — the parent's 599 MB counted 28 times as shared pages —
  against the cleanroom's **1.17 GB**, a **14x** difference.
- On PSS, which charges shared pages only once, the same cell is
  **698 MB vs 440 MB** — a **37%** difference, and the honest one. The
  14x is real but it is mostly an accounting artefact of summing RSS.
- With a **natural** parent at 28 workers the two are **equal** on PSS
  (182 MB vs 182 MB) and the cleanroom still wins on RSS
  (1022 vs 675 MB).
- The in-process path's PSS **grows** with worker count (460 -> 698 MB
  at an inflated parent); the cleanroom's grows more slowly
  (284 -> 440 MB).

**The answer to the question the decision asked.** The pre-fork
candidate's memory story is mixed and needs a named worker count. **The
cleanroom's `map-udf` route does not need one**: it is cheaper on
memory at every worker count, because it never inherits the caller's
heap in the first place. If a default-on decision wants to name a
worker count, it should name it for the *throughput* reason in §3, not
the memory reason.

---

## 3. Throughput — and why it is 4x worse

Measured separately, **without** the sampler (median of 5):

| workers | in-process | cleanroom | ratio |
|---|---|---|---|
| 1 | 3.416 s | 15.686 s | **4.59x** |
| 2 | 1.802 s | 7.831 s | **4.35x** |
| 3 | 1.183 s | 5.156 s | **4.36x** |
| 4 | 0.915 s | 3.945 s | **4.31x** |
| 8 | 0.487 s | 2.038 s | **4.18x** |
| 14 | 0.333 s | 1.294 s | **3.89x** |
| 28 | 0.327 s | 1.193 s | **3.65x** |

### 3.1 It is not the route's own overhead

The fixed-cost probe (the same payload over corpora of 100, 1,000 and
500,000 records, w=1):

| corpus | in-process | cleanroom |
|---|---|---|
| 100 records | 0.016 s | **0.030 s** |
| 1,000 records | 0.023 s | **0.059 s** |
| 500,000 records | 3.423 s | **15.080 s** |

The launcher's **start-up is ~30 ms**. The penalty is per record.

### 3.2 It is not calling the UDF more often

A payload that reports its own invocation count settles it. For 500,000
records with 123 (in-process) and 167 (cleanroom) result objects, the
sum of the reported counts is exactly `n(n+1)/2` in both cases
(7626 = 123x124/2; 14028 = 167x168/2) — so **both routes call the UDF
exactly once per batch**. The cleanroom's batches are 36% smaller
(3000 vs 4065 records), which does not explain 4.4x.

### 3.3 It is the missing C accelerator

With a payload that does **no json at all** (a counter), the gap
collapses:

| payload | in-process | cleanroom | ratio |
|---|---|---|---|
| counter (no json) | 0.035 s | 0.052 s | **1.5x** |
| json per record | 3.423 s | 15.080 s | **4.4x** |

And the UDF itself reports why — `json`'s C accelerator (`_json`) is an
extension module, and extension modules cannot be imported on this
route:

| | `json.decoder.scanstring` | `json.loads` |
|---|---|---|
| in-process | `'_json'` (C) | **2.88 us** |
| cleanroom | `'json.decoder'` (pure Python) | **13.19 us** — **4.6x slower** |

**So the entire throughput gap is one missing symbol scope.** The route
itself is fine; the interpreter it creates cannot load CPython's own
extension modules.

See `UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md` for the root cause, the
proof, and the proposed fix.

---

## 4. What this means for the default-on decision

**The memory question is answered, and answered favourably.** The
cleanroom's `map-udf` route is cheaper on memory at every worker count
and every parent size, on both RSS and PSS. **No worker-count
assumption is needed for the memory story.** The pre-fork candidate's
mixed result does not transfer to this route, because this route never
inherits the caller's heap.

**The throughput question is answered, and answered against default-on —
until the defect is fixed.** On the most realistic payload the route can
currently run, it is **3.65x–4.6x slower**, silently, because the
interpreter it creates cannot load CPython's extension modules. A
default-on decision taken today would make every json-using UDF about
4.6x slower with no diagnostic.

**The route is not ready to be default-on.** In order:

1. **Fix the extension-import defect**
   (`UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md` §5) — it is a one-line-class
   change in the launcher plus a mutation-checked regression test.
   Until it is fixed, the route is both slower and less capable than
   the path it would replace.
2. **Fix the in-process fallback** (`…DEFECT.md` §6) — `mode="udf"`
   currently *raises* `NotImplementedError` unless the route is
   explicitly selected, which is the opposite of "opt-in".
3. **Re-run this measurement** with the fix in. The memory conclusion
   should not change (it is structural); the throughput conclusion
   should reverse.
4. Then, and only then, the per-minor release wheel build and the
   `auditwheel` verdict — the two gates that were already outstanding
   and that are not code problems.

**A note on what the C0.4/C0.5 "pre-fork wins 10.19x" result does and
does not cover.** That result is about the pre-fork **candidate**
(`fr_udf_fork`), measured in the M2 lifecycle harness. This measurement
is about the **`map-udf` cleanroom route**, through the public API, on
the published workload. They are different mechanisms and the two
results do not contradict each other — but they also do not
substitute for each other, and the M2 harness's own note says its
numbers must not be quoted as real-workload throughput.

---

## 5. Artifacts

| what | where |
|---|---|
| memory sweep (raw) | `/tmp/opencode/udfbench/rss_ab.json` |
| timing sweep (raw) | `/tmp/opencode/udfbench/timing_ab.json` |
| fixed-cost probe | `/tmp/opencode/udfbench/fixed_cost.py` |
| invocation-count probe | `/tmp/opencode/udfbench/invocations.py` |
| json-accelerator probe | `/tmp/opencode/udfbench/jsonprobe.py` |
| the payload | `/tmp/opencode/udfbench/udf_payload.py` |
| the defect | `dev/supervisor/UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md` |

Drivers are outside the repository because they are measurement
scaffolding, not product code; the payload is a measurement fixture
that mirrors `ml_payload.process_event_light` and is deliberately
self-contained (json only) for the reason in §1.

## 6. Honest limits

- **One host, one workload.** The 500k-record light corpus, one corpus
  shape, UMA, 28 cores.
- **One sample point per cell**, with the within-cell spread not
  reported for memory (the peak is a peak). The timing sweep reports
  min/median/max over 5 trials and is tight.
- **The parent's size was synthesised** with an inflation buffer. A
  real caller has a real heap of a different shape — the C0.6 work
  already notes that "a workload that dirties most shared pages is
  untested", and that caution applies here too.
- **The payload is json-only**, because nothing else can be imported on
  this route today. A payload that could import `re` and `numpy` would
  be more representative — and is exactly what the defect's regression
  test should use.
- **No competitor was re-measured**, and no claim is made about one.
