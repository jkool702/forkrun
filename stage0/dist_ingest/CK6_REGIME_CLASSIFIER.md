# CK-6: regime classifier + property documentation — experimental dist_ingest

## 9.1 Actual metric semantics (from the C instrumentation)

Read directly from `stage0/dist_ingest/dist_ingest.c`. These are NOT
interchangeable measurements. Wait counters are **accumulated durations
(ns)**; accumulated totals are **not proof of temporal co-occurrence**;
backlog fields are **final-state + observed high-water**, not sustained
occupancy.

- `consume_wait_ns` — consumer thread time blocked on `cv_can_pop` while
  the queue is **EMPTY**. Consumer queue-empty wait / **starvation /
  underfeeding**. **NOT evidence consumers are saturated. NOT
  consumer-limited.** (`di_queue_pop`.)
- `publish_wait_ns` — ingestor thread time blocked on `cv_can_push` while
  the queue is **FULL**. **Downstream queue-full backpressure.** NOT proof
  that raw consumer compute throughput is the limiting resource (queue
  capacity, artificial consumer throttles, other downstream conditions
  also produce backpressure). (`di_queue_push`.)
- `read_wait_ns` — time accumulated around `di_pread_full` (the actual
  timed source-read section), which itself includes input-unchanged
  (`fstat`) checks, `EINTR` retry, short-read retry, injected faults, and
  error-path returns. **Not pure kernel read time.**
- `claim_wait_ns` — time accumulated in the no-progress claim branch:
  fixed 200us no-progress sleep + re-check, when no claim is admitted
  (`!can`) or no claim is selected (`want==0`); includes trailing
  no-progress at end-of-input. **Claim/admission delay; exact sub-cause
  not separable from this counter alone.**
- `zero_claims` — total zero/denied claims = `zero_claims_policy` +
  `zero_claims_admission` (legacy total). **Ambiguous until split.**
  `zero_claims_policy`: `want==0` — **policy-selected zero claim, NOT
  admission denial.** `zero_claims_admission`: `want>0` but
  `di_can_admit` rejected — **admission-denied claim.** (split added
  without changing production ABI; experimental struct only; one
  increment in the existing branch; no hot-path cost.)

## 9.2 Normalization & denominators

Accumulated durations potentially across multiple threads. Per-node
counters are contributed by a **single thread per role** in the current
**one-ingestor + one-consumer-per-node** distributed mode (in
`centralized_ingest`, only node 0 has an ingestor; consumers always one
per node). Per-node fraction:

```
fraction = counter_ns / (run_seconds * 1e9 * contributing_threads)
```
`run_seconds` = actual `DIST_RESULT.wall_seconds`; `contributing_threads`
= `ingestor_threads` (read/publish/claim) or `consumer_threads`
(consume); documented in evidence (`denominator_*`). Fractions are
per-thread wall-time fractions and are **not guaranteed bounded by 1**
across a node. **Reject or mark indeterminate: non-finite values,
negative values, missing/invalid run duration, missing configuration,
invalid maximum-backlog** (`max_backlog` configured capacity finite >0;
never substitute a high-water mark).

## 9.3 Classifier (authoritative: `tools/regime_classify.py::classify_metrics`)

One authoritative implementation; `run_dist._regime_classify` calls it;
tests call it. Per-node `DIST_RESULT.regime` contains:

`regime` label + `evidence`: raw values; `run_seconds`; thread counts;
`denominator_ns_per_thread`/`denominator_consumer_ns`/
`denominator_ingestor_ns`; `wait_fractions` + `*_wait_fraction`;
`max_backlog`/`max_backlog_configured`; observed backlog with precise
meaning (`backlog_final_effective`, `max_effective_backlog_observed`
=observed high-water NOT capacity NOT sustained, `max_published_backlog_
observed`, `backlog_observed`); claim breakdown; `signals`; `threshold`;
`limitations`; `valid`/`validation_errors`. Node-level
`max_backlog_configured` also emitted. `regime="indeterminate"` +
`error` on invalid input or **classifier import/execution failure**
(never silently replaced with apparently-valid measurements).

**Corrected inputs (CK-6.2):** `run_seconds` = actual `res.wall_seconds`
(NOT hardcoded 1.0); `max_backlog` = actual configured
`params.max_backlog` (engine-effective; NOT `max_published_backlog` /
`max_effective_backlog` high-water marks; observed high-water reported
separately, labeled, and **not** used as capacity; **not** substituting
final-state `current_published_backlog`). Claim/admission info correctly
identified (split). No `consumer-limited` claim (not establishable);
sustained-occupancy claims deferred (only final + high-water counters
exist; direct wait measurement used instead).

### Labels (descriptive; no forced exclusive causal quadrants; a single
### observation may support multiple signals; `mixed`/`indeterminate`)

| signal (measured) | defensible interpretation | label |
|---|---|---|
| high `consume_wait_ns` frac | consumer queue-empty wait / underfed | `consumer-starved` |
| high `read_wait_ns` frac | significant time in source-read op | `source-read-time` |
| high `publish_wait_ns` frac | ingestor blocked by full-queue backpressure | `downstream-backpressure` |
| high `claim_wait_ns` frac / high admission-denied zero-claim frac | claim/admission delay | `claim-admission-delay` |
| no strong signal | balanced / low-wait | `balanced` |
| several strong signals | mixed | `mixed` |
| inadequate/contradictory/invalid | indeterminate | `indeterminate` |

Policy-selected zero claims (`zero_claims_policy`) are **not** admission
denial. `zero_claims` alone is ambiguous. Threshold: documented `skew`
(default 0.15) on normalized per-thread wait fractions.

## 9.4 CK-6.5 pairing & decision-rule integrity

Inspect `report_dist.py`. **Pair identity** = invariant conditions shared
by baseline & candidate; candidate label SELECTS arms, NOT in pair key.
Pair key (`PAIR_KEY_FIELDS`): scenario, topology mapping (`mapping_id`),
workload (`workload_id`), parameter set (`parameter_set_id`),
trial/repetition id, **node + physical/logical node identity**
(`node`, `requested_physical_node`), consumer kernel, trial_class,
placement_sampling, cache_precondition_policy (relevant operating
conditions; additional unrecorded conditions noted as a limitation).
**Not** `candidate`.

**Performance = duration-normalized** per-node `bytes_consumed /
wall_seconds` (NOT raw consumed bytes when durations differ). Invalid/
incorrect/incomplete trials excluded; **`performance_measurement`
(`v_perf`) must be explicitly `true` for BOTH arms; `false` AND `unknown`
are excluded; repetition `v_perf_headline=false` excludes.** **Campaign
drift (invalidated/failed/unavailable/unreadable) SUPPRESSES paired
performance comparison** (same as headline medians). `report_dist.py`
emits a **paired, regime-grouped** report (`emit_paired_regime_report`):
baseline `centralized_ingest`, pairs per regime, median paired
duration-normalized improvement; insufficient pairs => inconclusive.

**Automated regime-based DECISION-making is DEFERRED.** The legacy
**15% improvement threshold is NOT retained as an evidence-based
guarantee** (no traceable derivation from actual repeatability data +
valid comparison method). Previously documented pairing including
`candidate` and raw consumed-bytes medians was defective. What must be
added before a decision-grade comparison: pre-registered paired
protocol, adequate repetitions + repeatability/tolerance bounds, complete
pair-identity fields in artifacts, per-node duration-normalized
throughput, regime assignment for both arms, and a justified numeric
threshold. Rental gate reflects deferral.

---

*Regenerated WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-6).*
