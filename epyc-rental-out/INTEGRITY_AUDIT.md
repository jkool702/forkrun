# Integrity audit — 2026-09-30T13:15:21Z

Verifying the manifest written by `epyc/10_setup.sh` at harness start.
Tier 1 = product under test + benchmark sources + validator. Any change
here invalidates the run and is reported as a boundary violation.
Tier 2 = the harness's own stage scripts. The agent is permitted to edit
these, so a change is reported as 'agent-modified harness' — which is
information the operator wants, not a violation.

## Tier 1 — product, benchmarks, validator — **CLEAN** (243 files unchanged)

## Tier 2 — harness stage scripts — **3 of 20 files changed** (agent-modified harness)


      CHANGED  /opt/forkrun/epyc/40_bench_ml5m.sh
      CHANGED  /opt/forkrun/epyc/41_bench_numa5m.sh
      CHANGED  /opt/forkrun/epyc/43_bench_ml20m.sh

## Tier 3 — agent control plane — **CLEAN** (2 files unchanged)

---

**Verdict: the run measured unmodified forkrun.**
The agent did modify harness scripts; see Tier 2 above. The benchmark sources and the validator are untouched, so the measurements stand, but the harness that produced them was changed — check the Tier 2 list before re-running anything.
