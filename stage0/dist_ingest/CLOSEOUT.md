# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — Closeout

**Status:** complete (no rental). **Corrections-4 base SHA:** a1db06a0.
**Final SHA:** 766025bd2b07b57ba1b7e19e02e24a56a13b0d37. **Clean tree: yes.**

## Checkpoints

- CK-1: 72f170da — portable mbind build + preflight (tools/di_preflight.py,
  tests/test_preflight_ck1.py)
- CK-2: 6135e6c4 — LIVENESS.md + fault-injection termination tests
- CK-3: 7c6ab6be (+ a73f8ba9) — ATOMIC_SEMANTICS.md + tools/di_sanitizer_harness.sh
- CK-4: d64f91a1 — FORK_AUDIT.md + tests/test_threads_only_ck4.py
- CK-5: 5224a54e — invariant assertions (DI_INVARIANT_ASSERT mode),
  CK5_INVARIANTS.md
- CK-6: 766025bd — regime classifier tests, CK6_REGIME_CLASSIFIER.md

## Suites (final SHA 766025bd)

- `discover -s stage0/dist_ingest/tests`: **271 OK**
- Sanitizer harnesses (tools/di_sanitizer_harness.sh): asan-ubsan and tsan
  — source_sha 6135e6c4 — **265 tests, 0 findings both**

## Verification summary

Preflight exit 0 (CK-1); LIVENESS.md audit complete (CK-2); atomic table
(37 __atomic_* sites) recorded (CK-3); sanitizer harnesses reproducible and
run at asserted SHA (CK-3); fork audit = 0 process-creation symbols (CK-4);
invariant build passes; CK-5 post-join `outstanding==0` assertion implemented;
CK-6 classifier tests pass.

## Rental gate

`stage0/dist_ingest/RENTAL_PLAN_REVIEW.md` — unsigned (intended per WO §10.2;
do not rent).

---
*Closeout by WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1.*
