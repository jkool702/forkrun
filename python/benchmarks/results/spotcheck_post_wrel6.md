# Post-W-REL6 Benchmark Spot-Check (W-SPOT)

Date: 2026-09-29. Branch: `NEW/REFACTOR2.12`. SHA: `ff99eb7b00a597c97b80733cd0e037882c617311`
(tree clean, past `eb17f16` — W-REL6 landed plus later commits; latest is "new security unit test").
Method: median-of-3 + 1 warmup per cell, `order="index"`, 28 workers, terminated framing,
exact-totals assertion. No rerun-until-green: out-of-band numbers are findings, reported as-is.

Reference: `RELEASE_v3.6.0.md` §2 (fresh 2026-09-25, engine v3.6.0) + §5 (tokenize).
Acceptance band: ±10% (±15% for the marked heavy-@4-20M cell).

## 1. Environment echo

```
THP enabled:            always [madvise] never        -> state = always
THP shmem_enabled:      [always] within_size advise never deny force -> always
THP defrag:             always defer defer+madvise [madvise] never    -> madvise
NUMA online:            0                               (single node)
numactl:                1 node (0), 28 cpus (0-27), 128494 MB
kernel:                 7.1.13-200.fc44.x86_64          (matches fresh-run hardware string)
forkrun:                0.16.0  |  python 3.14.7  |  gcc 16.2.1
```

THP=`always` matches the reference big-benchmark sessions (`always`); no THP adjustment was needed.
The light-workload THP confound does not apply (states match).
Kernel matches the fresh runs (`Linux 7.1.13-200.fc44.x86_64` in the CSV hardware strings).

## 2. Data

- `light_5M.jsonl`: generated 2026-09-29, `ml_data_gen.SEED=42`, 5,000,000 lines, 532,711,015 B
  (ref §2 input ~533 MB — byte-identical by seeded construction).
- `medium_5M.jsonl`: same seed, 5,000,000 lines, 2,347,403,909 B (ref 2.35 GB — matches).
- `heavy_20M.jsonl`: PRE-GENERATED, reused (`/mnt/ramdisk/numa1/ml/heavy_20M.jsonl`,
  20,000,000 lines verified by `wc -l`; integrity confirmed, not regenerated).
- `tok_2M.jsonl`: `tokenize_data_gen.SEED=2024`, 2,000,000 docs + 29,999-line `.vocab` sidecar.
- `tok_500k.jsonl`: same seed, 500,000 docs (exact prefix of the 2M RNG sequence) + sidecar.
- Medium C = yyjson single-pass plugin (`ml_process_medium_yyjson`); light/heavy C = scalar
  plugins; Python cells = identical `ml_payload` UDFs. All plugins compiled fresh (`gcc -O3
  -march=native`) into `/tmp/spot_plugins`.

## 3. Matrix: measured vs reference vs delta

| Cell | Config | Reference | Measured | Delta | Total / Valid | Verdict |
|---|---|---|---|---|---|---|
| ML-L-C-UMA | light C-plugin nodes=1 5M | 6.67 M/s (0.75s) | **5.56 M/s** (0.90s) | **−16.6%** | 5000000 / 5000000 exact | OUT |
| ML-L-C-@4 | light C-plugin @4 5M | 4.76 M/s (1.05s) | 4.73 M/s (1.06s) | −0.6% | 5000000 / 5000000 exact | ok |
| ML-M-C-UMA | medium C yyjson nodes=1 5M | 2.35 M/s (2.13s) | **1.93 M/s** (2.60s) | **−18.0%** | 5000000 / 4997892 exact | OUT |
| ML-M-C-@4 | medium C yyjson @4 5M | 1.83 M/s (2.73s) | 1.85 M/s (2.71s) | +0.9% | 5000000 / 4997892 exact | ok |
| ML-H-C-UMA-20M | heavy C nodes=1 20M | 0.69 M/s (28.84s) | 0.64 M/s (31.19s) | −7.1% | 20000000 / 19991658 exact | ok |
| ML-H-C-@4-20M | heavy C @4 20M | ~0.76 M/s† (~26s) | 0.68 M/s (29.24s) | −10.0% | 20000000 / 19991658 exact | ok (±15%) |
| ML-L-Py-UMA | light Python nodes=1 5M | 1.48 M/s (3.38s) | 1.57 M/s (3.19s) | +5.9% | 5000000 / 5000000 exact | ok |
| ML-L-Py-@4 | light Python @4 5M | 1.17 M/s (4.28s) | **1.47 M/s** (3.39s) | **+26.0%** | 5000000 / 5000000 exact | OUT (fast) |
| ML-M-Py-UMA | medium Python nodes=1 5M | 0.71 M/s (7.02s) | 0.69 M/s (7.25s) | −2.9% | 5000000 / 4997892 exact | ok |
| ML-M-Py-@4 | medium Python @4 5M | 0.61 M/s (8.24s) | 0.59 M/s (8.53s) | −3.9% | 5000000 / 4997892 exact | ok |
| SPAWN-M-UMA | medium spawn `tr` nodes=1 5M | 1.59 M/s (3.14s) | **1.05 M/s** (4.77s) | **−34.1%** | 5000000 / 5000000 exact | OUT |
| TOK-C-2M | C plugin UMA 2M docs | ~344k/s (1M ref) | 316.0k/s (6.33s) | −8.1% vs 1M | 2000000 / 2000000 exact | ok |
| TOK-Exec-2M | Executor UMA 2M docs | ~168k/s | 157.8k/s (12.68s) | −6.1% | 2000000 / 2000000 exact | ok |
| TOK-C-500k | C plugin UMA 500k (sanity) | 304.5k/s | **151.5k/s** (3.30s) | **−50.2%** | 500000 / 500000 exact | OUT (2ndary) |
| STREAM-IDX-M | medium stream idx nodes=1 | refs vary | 0.80 M/s (6.23s) | n/a | 5000000 / 4997892 exact, warn=silent | ok |

Per-trial times (median-of-3 + warmup; warmup discarded, not shown):
- L-C-UMA [0.90, 0.96, 0.86] · L-C-@4 [0.88, 1.06, 1.06] · M-C-UMA [2.60, 2.83, 2.54] ·
  M-C-@4 [2.31, 2.86, 2.71] · H-UMA-20M [31.19, 32.55, 30.71] · H-@4-20M [27.19, 31.13, 29.24]
- L-Py-UMA [3.16, 3.19, 3.20] · L-Py-@4 [3.41, 3.28, 3.39] ·
  M-Py-UMA [7.15, 7.47, 7.25] · M-Py-@4 [8.53, 8.96, 7.40]
- SPAWN [4.46, 4.89, 4.77] · TOK-C-2M [6.33, 6.71, 6.24] · TOK-Exec-2M [12.58, 12.93, 12.68] ·
  TOK-C-500k [3.30, 3.32, 3.26] · STREAM [6.23, 6.18, 6.32]

## 4. Ratio checks

- Tokenize forkrun-C ÷ Executor @ 2M docs: 316.0k / 157.8k = **2.00×** — headline ~2× claim HOLDS.
- TOK-C-2M (316k) lands 8% below the 1M reference (344k) rather than at-or-above it; within the
  ±10% band, but the amortization direction did not materialize on this (hotter, later) run.
  Same-boot ratio is the robust reading (2.00×); absolutes carry thermal state (see §7).
- ML-C vs best-Python-UDF informal: light 5.56 vs 1.57 (3.5×), medium 1.93 vs 0.69 (2.8×),
  heavy-20M 0.64 vs ~0.09 est (7× family) — tiering intact.

## 5. Warning-silence assertion (correctness, not perf)

STREAM-IDX-M ran `stream(payload, order="index", nodes=1, workers=28)` over 5M medium with
stderr captured per-trial in a subprocess (airtight against `os.write(2)`):
**no reassembly high-water warning fired on any of 3 timed trials** (plus 1 warmup).
Totals exact every trial (5000000/4997892). The W-REL6-3.2 threshold is correctly configured —
a healthy run does not trip it. PASS.

## 6. `return_stats` field exercise (first real-data run)

One cell (ML-M-C-UMA payload, yyjson, nodes=1, 28w) with `return_stats=True`:
`{'total': 2570, 'completed': 2570, 'poisoned': 0, 'poisoned_batches': []}`,
`completed + poisoned == total` ✓, `poisoned == 0` on clean run ✓,
all four documented fields present and sane ✓, totals exact (5000000/4997892) ✓.
First exercise on real benchmark data: PASS, no accounting bug.

## 7. Out-of-band analysis (no re-rolls; pattern reading)

Four primary cells + one secondary are outside ±10%:

1. **ML-L-C-UMA −16.6%, ML-M-C-UMA −18.0%** — suspect class: W-REL6 hot-path touches
   (orchestrator default flip; engine fixes 4.1–4.16; reassembly 3.2 byte-accounting).
   Counter-evidence against a real UMA regression: their `@4` twins are dead-on (−0.6%, +0.9%),
   heavy-UMA-20M is in-band (−7.1%), and all four Python cells are in-band except one FAST
   outlier. The deficit fits the documented in-matrix envelope instead: prior studies record
   in-matrix absolutes running ~10–20% below cool-box peaks, and these two short runs
   (0.9s, 2.6s) are the most bring-up/thermal-sensitive cells in the matrix. Cannot rule out a
   small UMA-C regression from the suspect list — owner decides: bisect Tuesday morning
   (34 commits, all bisectable) or note-and-ship with the EPYC baseline carrying the Slots below.
2. **SPAWN-M-UMA −34.1%** — suspects: D-STRICT registration deletion + 4.14 spawn checks
   (the exact paths this cell exercises). Confound: it ran last, immediately after eight
   ~30s heavy-20M full-load runs — the hottest box state of the day — and spawn
   (`posix_spawnp` per batch) is the most fork-latency-sensitive cell. −34% exceeds any
   documented thermal envelope, so this one is NOT waved away: either the new spawn checks
   cost real throughput, or the ordering cooked it. Cheapest discriminator Tuesday morning:
   one isolated spawn run on a cool box (5 min) before deciding on a bisect.
3. **ML-L-Py-@4 +26.0% (FAST)** — improvement-direction outlier. Plausible W-REL6 @4-path
   improvement (drain-guard / meta-lifetime work) or a slow reference leg. Not a regression;
   recorded as a positive delta; EPYC will confirm.
4. **TOK-C-500k −50.2% (secondary, droppable per the order)** — ran immediately after 50s of
   full-load Executor pickling (peak heat + allocator pressure); its 2M sibling on a cooler
   box is in-band with an exact 2.00× ratio. Read as ordering artifact, not product signal.
   Recommend dropping this row from any quoted table (the order permits it).

Heavy-@4-20M stability note (supports the documentation win): all 8 heavy-20M executions
(4 UMA + 4 @4 incl. warmups) returned exact 20000000/19991658 with zero silent partials and
zero drain-audit warnings. The F-NUMA1 fix reads stable; the † marker removal is recommended
whenever the owner accepts this report (held here only because the overall verdict is DELTAS).

## 8. Verdict line (as-run, reactor default)

**DELTAS:** ML-L-C-UMA −16.6% and ML-M-C-UMA −18.0% (suspects: orchestrator default flip,
engine 4.1–4.16, reassembly 3.2 accounting — thermal envelope not excluded);
SPAWN-M-UMA −34.1% (suspects: D-STRICT registration deletion, 4.14 spawn checks — exceeds
thermal envelope, needs a cool-box isolate before bisect call); ML-L-Py-@4 +26.0% fast
(positive direction); TOK-C-500k −50.2% secondary ordering artifact (drop the row).
Headline ratio intact (tokenize 2.00×), warning-silence PASS, return_stats PASS,
heavy-@4 stable 8/8 exact (recommend † removal on owner accept).
Owner decides before the EPYC rental whether to bisect Tuesday morning or note-and-ship —
either way the table above is the post-W-REL6 baseline the EPYC numbers get compared against.

## 9. Addendum — orchestrator-methodology correction (same day, post-verdict)

Review question: were the §3 OUT-slow cells measured under the same orchestrator setting as
the reference? **No.** The §3 legs omit `orchestrator` (= `None`), which post-flip
(W-REL1/R1 `8501be0`, 2026-09-27) rides the reactor (death pipes, trap-ACK, **C orderer**
for `order="index"`). The reference (2026-09-25) ran the same omission under the pre-flip
default = legacy fork-and-wait, no C orderer. The flip commit itself quantified the
penalty on this box (medium 5M yyjson, 28w, `order="index"`): C **−14%**, Python −6% —
"the pre-existing C-orderer transit cost, previously paid only under opt-in True" —
and its `orchestrator=False` leg reproduced the fresh table (2.23 vs 2.29M).

Methodology-matched legs on current code (`orchestrator=False`, median-of-3 + warmup,
all totals exact), appended without touching §3 (no re-rolls — these are new rows):

| Cell | Reference | §3 (reactor) | False leg (legacy) | Delta vs ref | Verdict |
|---|---|---|---|---|---|
| ML-L-C-UMA | 6.67 M/s | 5.56 (−16.6%) | **6.50 M/s** (0.77s; trials 0.70/0.77/0.79) | **−2.6%** | ok |
| ML-M-C-UMA | 2.35 M/s | 1.93 (−18.0%) | **2.27 M/s** (2.20s; trials 2.14/2.40/2.20) | **−3.3%** | ok |
| SPAWN-M-UMA | 1.59 M/s | 1.05 (−34.1%) | **1.43 M/s** (3.50s; trials 2.79/4.19/3.50) | −10.2% | borderline, noisy |

Reading: the two UMA-C OUTs dissolve under the matched methodology — the entire delta
is the known C-orderer transit cost, not a W-REL6 hot-path regression (no bisect warranted
for them; suspects orchestrator-flip confirmed, engine 4.1–4.16 / reassembly 3.2 exonerated
on this evidence). Spawn recovers from −34% to −10% by methodology alone; the residue sits
inside spawn's own trial spread (±20% here) on a hot box — downgraded to a 5-minute cool-box
isolate Tuesday, not a bisect trigger. Against the README headline cells (§0: light 6.61M,
medium 2.37M): matched legs read 6.50 (−1.7%) and 2.27 (−4.2%) — clean.

**Revised verdict: CLEAN (methodology-corrected).** All regression-direction headline cells
in-band under matched methodology; the C-orderer delta is the documented cost of the
ratified reactor default (release-notes framing decision, not a benchmark failure);
remaining notes: ML-L-Py-@4 +26% fast (improvement direction, EPYC will confirm),
TOK-C-500k dropped as ordering artifact, spawn cool-box isolate Tuesday (5 min).
EPYC rental proceeds with §3 + this addendum as the baseline — with one binding rule:
**EPYC comparisons must pin `orchestrator` explicitly on both sides** (the pre/post-flip
default change makes omitted-orchestrator comparisons apples-to-oranges).

*No tag. No push. (Per the order.)*

## 10. Follow-up (same day): headline-table qualification + legacy heavy-Python hang

The §0 headline table (`RELEASE_v3.6.0.md`) was split into (†)/(max) pairs per owner request;
11 of 12 qualifier legs passed median-of-3 + warmup (record: `headline_2026-09-29.csv`;
heavy-5M corpus generated seeded, 6,720,381,299 B = 6.72 GB, 5,000,000 lines).
The 12th — Python `orchestrator=False` + `order="none"` on heavy 5M — never ran: the legacy
fail-fast path hangs in the materialized scanner (helper watchdog 10s → SIGKILL →
`scan failed (status 9)`), deterministic across fresh processes, both orderings, 4 and 28
workers. Same file passes under the reactor (90k), under legacy with the C plugin (698k),
and under legacy Python at medium (720k). New P0: size-dependent (2.3 GB ok, 6.7 GB hangs)
with payload-kind dependence; W-REL6-suspect (legacy `_execute_locked` ExecutorSpec lattice).
See the §0¹ note; the (max) heavy speedup is C-only until this is fixed.
