# Integrity audit — 2026-09-30T15:17:27Z

Verifying the manifest written by `epyc/10_setup.sh` at harness start.
Tier 1 = product under test + benchmark sources + validator. Any change
here invalidates the run and is reported as a boundary violation.
Tier 2 = the harness's own stage scripts. The agent is permitted to edit
these, so a change is reported as 'agent-modified harness' — which is
information the operator wants, not a violation.

## Tier 1 — product, benchmarks, validator — **2 of 243 files changed** (VIOLATION)


      CHANGED  /opt/forkrun/python/benchmarks/ml/bench_ml_pipeline.py
      CHANGED  /opt/forkrun/BENCHMARKS/run_benchmark.bash

> ## These results are not trustworthy as published
>
> A file that the supervising agent was explicitly forbidden to modify has
> changed during the run. The run may still be internally consistent, but it is
> no longer a measurement of unmodified forkrun.
>
> Do not quote any number from this run without first establishing what changed
> and why. Re-run the affected stages on a clean checkout.

## Tier 2 — harness stage scripts — **5 of 20 files changed** (agent-modified harness)


      CHANGED  /opt/forkrun/epyc/40_bench_ml5m.sh
      CHANGED  /opt/forkrun/epyc/41_bench_numa5m.sh
      CHANGED  /opt/forkrun/epyc/43_bench_ml20m.sh
      CHANGED  /opt/forkrun/epyc/44_bench_headline.sh
      CHANGED  /opt/forkrun/epyc/50_bench_bash.sh

## Tier 3 — agent control plane — **CLEAN** (2 files unchanged)

---

**Verdict: INTEGRITY VIOLATION.** Tier 1 or Tier 3 changed during the run.
Numbers from this run must not be published without a full re-run on a
clean checkout.
