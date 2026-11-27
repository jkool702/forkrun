#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-6
authoritative regime classifier (one implementation; tests + runtime share it).

Semantics are derived from the ACTUAL C instrumentation in
stage0/dist_ingest/dist_ingest.c (see CK6_REGIME_CLASSIFIER.md). Wait
counters are ACCUMULATED DURATIONS (nanoseconds); they are NOT proof of
temporal co-occurrence, and high-water/final-state backlog metrics are NOT
proof of sustained saturation.

Per-counter semantics (exact):
  consume_wait_ns : consumer thread time blocked on cv_can_pop while the
      queue is EMPTY. Consumer queue-empty wait / UNDERFEEDING. NOT
      evidence that consumers are saturated. NOT consumer-limited.
  publish_wait_ns : ingestor thread time blocked on cv_can_push while the
      queue is FULL. Downstream QUEUE-FULL BACKPRESSURE. NOT proof that
      raw consumer compute throughput is the limiting resource (queue
      capacity, artificial consumer throttles, other downstream conditions
      also produce backpressure).
  read_wait_ns    : time accumulated around di_pread_full — the actual
      timed source-read section, which itself includes input-unchanged
      (fstat) checks, EINTR retry, short-read retry, injected faults, and
      error-path returns. NOT pure kernel read time.
  claim_wait_ns   : time accumulated in the no-progress claim branch:
      fixed 200us no-progress sleep + re-check, when no claim is admitted
      (!can) or no claim is selected (want==0); includes trailing
      no-progress at end-of-input. CLAIM/ADMISSION DELAY; exact cause is
      not separable from this counter alone (see zero-claim split).
  zero_claims     : total zero/denied claims = zero_claims_policy +
      zero_claims_admission (legacy total). AMBIGUOUS unless split.
  zero_claims_policy    : want==0 — POLICY-SELECTED zero claim. NOT
      admission denial.
  zero_claims_admission : want>0 but di_can_admit rejected —
      ADMISSION-DENIED claim.

Normalization: per-node counters are contributed by a single thread
(one ingestor + one consumer per node in the current distributed mode;
in centralized_ingest mode only node 0 has an ingestor; consumers always
one per node). fraction = counter_ns / (run_seconds * 1e9 * threads).
Fractions are NOT guaranteed bounded by 1 across a node (multiple threads
may contribute to a node); they are per-thread wall-time fractions.
Invalid/non-finite/negative inputs, missing/invalid run duration, or
missing/invalid configured max_backlog => INDETERMINATE.

Labels (descriptive; no forced exclusive causal quadrants; a single
observation may support multiple signals):
  consumer-starved | source-read-time | downstream-backpressure |
  claim-admission-delay | balanced | mixed | indeterminate
"""
import math

# descriptive, non-causal labels
REGIMES = (
    "consumer-starved",
    "source-read-time",
    "downstream-backpressure",
    "claim-admission-delay",
    "balanced",
    "mixed",
    "indeterminate",
)

DEFAULT_SKEW = 0.15


def _finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonneg_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _invalid(reason, ev):
    ev = dict(ev)
    ev["valid"] = False
    ev.setdefault("validation_errors", []).append(reason)
    return ("indeterminate", ev)


def classify_metrics(read_wait_ns, publish_wait_ns, consume_wait_ns,
                     max_backlog, run_seconds,
                     claim_wait_ns=0, backlog=0,
                     claims_zero=0, claims_zero_policy=0, claims_zero_admission=None,
                     reservations=0,
                     consumer_threads=1, ingestor_threads=1,
                     backlog_final_effective=None, backlog_max_effective_observed=None,
                     max_published_backlog_observed=None,
                     skew=DEFAULT_SKEW, **_ignored):
    """Authoritative classification. Returns (regime, evidence)."""
    ev = {
        "valid": True, "validation_errors": [],
        # raw measurement values
        "read_wait_ns": read_wait_ns, "publish_wait_ns": publish_wait_ns,
        "consume_wait_ns": consume_wait_ns, "claim_wait_ns": claim_wait_ns,
        "claims_zero": claims_zero, "claims_zero_policy": claims_zero_policy,
        "claims_zero_admission": claims_zero_admission,
        "reservations": reservations,
        # denominators
        "run_seconds": run_seconds,
        "consumer_threads": consumer_threads, "ingestor_threads": ingestor_threads,
        "denominator_ns_per_thread": None,
        # configured backlog limit + observed (NOT substituted for capacity)
        "max_backlog": max_backlog, "max_backlog_configured": max_backlog,
        # observed backlog with precise meaning (no sustained-occupancy claim)
        "backlog_observed": backlog,
        "backlog_observed_meaning": "caller-supplied observed backlog snapshot (bytes)",
        "backlog_final_effective": backlog_final_effective,
        "backlog_final_effective_meaning":
            "final current_effective_backlog at end (often 0 after draining); not saturation",
        "max_effective_backlog_observed": backlog_max_effective_observed,
        "max_effective_backlog_observed_meaning":
            "observed high-water mark; NOT configured capacity; NOT proof of sustained saturation",
        "max_published_backlog_observed": max_published_backlog_observed,
        "max_published_backlog_observed_meaning":
            "observed high-water mark; NOT configured capacity",
        "threshold": skew,
    }

    # --- validation: finite, nonnegative, valid duration, valid max_backlog ---
    nums = {"read_wait_ns": read_wait_ns, "publish_wait_ns": publish_wait_ns,
            "consume_wait_ns": consume_wait_ns, "claim_wait_ns": claim_wait_ns,
            "backlog": backlog}
    for k, v in nums.items():
        if not _finite_number(v):
            return _invalid("%s not a finite number: %r" % (k, v), ev)
        if v < 0:
            return _invalid("%s negative: %r" % (k, v), ev)
    for k, v in (("claims_zero", claims_zero), ("claims_zero_policy", claims_zero_policy),
                 ("reservations", reservations)):
        if not _nonneg_int(v):
            return _invalid("%s invalid (nonneg int required): %r" % (k, v), ev)
    if claims_zero_admission is not None and not _nonneg_int(claims_zero_admission):
        return _invalid("claims_zero_admission invalid: %r" % (claims_zero_admission,), ev)
    if not _finite_number(run_seconds) or run_seconds <= 0:
        return _invalid("run_seconds invalid (finite >0 required): %r" % (run_seconds,), ev)
    if not _finite_number(max_backlog) or max_backlog <= 0:
        return _invalid("max_backlog invalid (configured capacity, finite >0 required): %r" % (max_backlog,), ev)
    if not isinstance(consumer_threads, int) or consumer_threads < 1:
        return _invalid("consumer_threads invalid: %r" % (consumer_threads,), ev)
    if not isinstance(ingestor_threads, int) or ingestor_threads < 1:
        return _invalid("ingestor_threads invalid: %r" % (ingestor_threads,), ev)
    if not _finite_number(skew) or skew < 0:
        return _invalid("skew invalid: %r" % (skew,), ev)
    # consistency: policy + admission cannot exceed total
    cp = claims_zero_policy or 0
    ca = claims_zero_admission if claims_zero_admission is not None else None
    if ca is not None and cp + ca > claims_zero:
        return _invalid("claims_zero_policy + claims_zero_admission (%d) > claims_zero (%d)"
                        % (cp + ca, claims_zero), ev)

    # --- normalization: per-thread wall-time fractions ---
    ns_per = float(run_seconds) * 1e9
    denom_consumer = ns_per * consumer_threads
    denom_ingestor = ns_per * ingestor_threads
    ev["denominator_ns_per_thread"] = ns_per
    ev["denominator_consumer_ns"] = denom_consumer
    ev["denominator_ingestor_ns"] = denom_ingestor
    rw = read_wait_ns / denom_ingestor
    pw = publish_wait_ns / denom_ingestor
    cw = consume_wait_ns / denom_consumer
    clw = claim_wait_ns / denom_ingestor
    total_attempts = claims_zero + reservations
    admission_zero_frac = (ca / total_attempts) if (ca is not None and total_attempts > 0) else None
    ev["wait_fractions"] = {"read": round(rw, 6), "publish": round(pw, 6),
                            "consume": round(cw, 6), "claim": round(clw, 6)}
    ev["read_wait_fraction"] = round(rw, 6)
    ev["publish_wait_fraction"] = round(pw, 6)
    ev["consume_wait_fraction"] = round(cw, 6)
    ev["claim_wait_fraction"] = round(clw, 6)
    ev["admission_denied_zero_claim_fraction"] = (round(admission_zero_frac, 6)
                                                  if admission_zero_frac is not None else None)
    ev["total_claim_attempts"] = total_attempts
    ev["claims_zero_policy_fraction"] = round(cp / total_attempts, 6) if total_attempts > 0 else None

    # --- signals (a single observation may support multiple) ---
    signals = {
        "consumer-starved": cw > skew,
        "source-read-time": rw > skew,
        "downstream-backpressure": pw > skew,
        "claim-admission-delay": (clw > skew) or (
            admission_zero_frac is not None and admission_zero_frac > skew),
    }
    ev["signals"] = signals
    ev["limitations"] = [
        "accumulated durations, not temporal co-occurrence proof",
        "no consumer-limited claim: high consume_wait means underfeeding, not saturation",
        "publish_wait = queue-full backpressure, not proof of raw consumer-throughput limit",
        "high-water/final backlog != sustained occupancy; max_backlog is configured capacity",
        "claim_wait exact sub-cause not separable; zero-claim split available",
        "single-thread-per-role per-node denominators; aggregate not assumed bounded",
        "fractions are per-thread wall-time fractions; not guaranteed bounded by 1",
    ]
    strong = [k for k, v in signals.items() if v]
    if not strong:
        regime = "balanced"
    elif len(strong) == 1:
        regime = strong[0]
    else:
        regime = "mixed"
    ev["regime"] = regime
    return regime, ev


if __name__ == "__main__":
    import sys
    # argv: read publish consume claim backlog max_backlog claims_zero run_seconds
    a = [int(x) for x in sys.argv[1:8]]
    reg, ev = classify_metrics(
        read_wait_ns=a[0] if len(a) > 0 else 0,
        publish_wait_ns=a[1] if len(a) > 1 else 0,
        consume_wait_ns=a[2] if len(a) > 2 else 0,
        claim_wait_ns=a[3] if len(a) > 3 else 0,
        backlog=a[4] if len(a) > 4 else 0,
        max_backlog=a[5] if len(a) > 5 else 1,
        claims_zero=a[6] if len(a) > 6 else 0,
        run_seconds=float(a[7]) if len(a) > 7 else 1.0)
    print("regime:", reg)
    print("evidence:", ev)
