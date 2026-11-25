#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-6 authoritative classifier.

One authoritative regime classifier used by:
  * `run_dist.py` DIST_RESULT ("regime" key)
  * `tests/test_regime_ck6.py` (synthetic vectors)
  * rental decision rule consumers

Consumer-wait semantics (corrected): consume_wait_ns accumulates time
blocked on cv_can_pop because the queue is EMPTY — it is starvation, not
saturation. demand/consumer-limited requires high consume_wait AND
persistently high backlog.
"""
import sys


def classify_metrics(read_wait_ns, publish_wait_ns, consume_wait_ns, backlog,
                     max_backlog, claims_zero, run_seconds=1.0, skew=0.15):
    """Classify a run's telemetry. Returns (regime, evidence dict)."""
    run_s = run_seconds if run_seconds > 0 else 1.0
    rw = read_wait_ns / (run_s * 1e9)
    pw = publish_wait_ns / (run_s * 1e9)
    cw = consume_wait_ns / (run_s * 1e9)
    saturated = backlog >= max_backlog * (1 - skew) if max_backlog else False
    rw_sig = rw > skew
    pw_sig = pw > skew
    cw_sig = cw > skew
    ev = {
        "read_wait_ns": read_wait_ns, "publish_wait_ns": publish_wait_ns,
        "consume_wait_ns": consume_wait_ns, "backlog": backlog,
        "max_backlog": max_backlog, "claims_zero": claims_zero,
        "run_seconds": run_s,
        "wait_fractions": {"read": round(rw, 4), "publish": round(pw, 4),
                           "consume": round(cw, 4)},
    }
    if pw_sig or claims_zero:
        return "admission-limited", ev
    if cw_sig and saturated:
        return "demand/consumer-limited", ev
    if rw_sig and not cw_sig:
        return "source-limited", ev
    if pw_sig and saturated:
        return "admission-limited", ev
    if rw_sig or cw_sig or saturated:
        return "mixed", ev
    return "balanced", ev


if __name__ == "__main__":
    reg, ev = classify_metrics(
        int(sys.argv[1]) if len(sys.argv) > 1 else 0,
        int(sys.argv[2]) if len(sys.argv) > 2 else 0,
        int(sys.argv[3]) if len(sys.argv) > 3 else 0,
        int(sys.argv[4]) if len(sys.argv) > 4 else 0,
        int(sys.argv[5]) if len(sys.argv) > 5 else 0,
        int(sys.argv[6]) if len(sys.argv) > 6 else 0)
    print("regime:", reg)
    print("evidence:", ev)
