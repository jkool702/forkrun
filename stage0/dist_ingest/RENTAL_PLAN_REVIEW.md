# RENTAL_PLAN_REVIEW — pre-rental gate (UNSIGNED)

Formal review gate (CK-7.3). **The physical-NUMA rental must NOT proceed
until this is signed off by an independent reviewer.** This document is
not authorization; it is a checklist. **Not signed.**

## Checklist (Pass / Fail / Not-Applicable + reviewer/date per item)

- [ ] Every scenario has a valid mapping.
- [ ] Mappings are topology-appropriate.
- [ ] Every scenario has an expected duration + timeout.
- [ ] Candidate coverage is explicit.
- [ ] Candidate roles declared in manifests (`local_adaptive` =
      `pathology_control_max_backlog_cap_only`).
- [ ] `local_adaptive` identified as pathology/control arm.
- **CK-6:** [ ] regime classifier semantics fixed + tested
      (consumer-starved ≠ consumer-limited; publish=backpressure;
      read/claim semantics; mixed/indeterminate; corrected inputs;
      evidence/denominators); [ ] **paired regime-grouped report
      implemented** (`report_dist.emit_paired_regime_report`;
      candidate NOT in pair key; duration-normalized; invalid excluded);
      [ ] **automated regime-based DECISION-making DEFERRED**; [ ]
      **15% improvement threshold NOT retained** as evidence-based
      guarantee. Before a decision-grade comparison: pre-registered
      paired protocol + adequate repetitions + repeatability/tolerance +
      complete pair-identity fields + per-node duration-normalized
      throughput + both-arm regime + justified threshold. **Not passed.**
- **CK-2:** [ ] watchdog/timeout bounds documented (LIVENESS.md;
      precise intentional-sleep max shutdown + stop; no heartbeat);
      [ ] failure-injection evidence (queue-push/pread/alloc/thread-
      create; injection fired; reconciliation; joins; prompt).
- **CK-1:** [ ] build portability demonstrated on clean image
      (mandatory fail-closed preflight; isolated builds; accurate env;
      no stale-artifact acceptance); [ ] optional build capabilities +
      consequences explicit.
- **CK-3:** [ ] sanitizer viability + modes recorded
      (SANITIZER_EVIDENCE.md; ASan+UBSan + TSan on final C; harness
      fail-closed; artifact unchanged; **LSan NOT validated for full
      suite; separate standalone LSan smoke; not proof no leaks**);
      [ ] atomic inventory regenerated (actual 47 sites).
- **CK-4:** [ ] required tests pass on final reviewed HEAD; [ ]
      enforceable symbol/source/syscall audit (`di_symbol_audit.py`,
      fail-closed) — `threads_only`.
- **CK-5:** [ ] invariant checking real + enforceable; publication
      checker before admission; propagated; no invalid publish;
      accounting reconciliation; post-join; activation consistent.
- [ ] Placement/physical-NUMA evidence **limitations** understood (physical evidence NOT required pre-rental; collected at Gate 2)
      (fake/local NUMA ≠ physical; mbind syscall ≠ physical placement;
      no physical-NUMA validation claimed).
- [ ] Teardown, artifact preservation, host cleanup ready.
- [ ] No outstanding P1 correctness/readiness findings.
- [ ] No production adoption; production files frozen; no
      MADV_POPULATE_WRITE / prepopulation / per-node memfd / production
      ingest changes; **no rental initiated.**

## Recorded provenance
- Reviewed source SHA: ________________
- Sanitizer-tested SHA: `00b06bc311e0c5bb4eb0e2f7bc79660e7ccce652`
  (re-verify at review; see SANITIZER_EVIDENCE.md + CLOSEOUT.md)
- Final C-code SHA / final branch HEAD / doc-only commits: see CLOSEOUT.md
- Reviewed plan artifact path: ________________
- Reviewer: ________________  Date: ________________

## Two distinct gates (no circular authorization) (P1 correction)

### Gate 1 — PRE-RENTAL authorization (this gate)
Independent sign-off of: experimental **plan**, readiness, test
integrity, sanitizer/invariant/classifier evidence, **cleanup +
teardown + artifact preservation + host-cleanup readiness**, pairing
contract, explicit **accepted limitations + deferrals**, no outstanding
P1. **Does NOT require physical-NUMA evidence** (which can only be
collected after rental). **This is the only gate that authorizes
rental.**

**Pre-rental sign-off:** physically signed by independent reviewer —
all Gate-1 items pass + deferrals accepted → **pre-rental rental
authorized.** Otherwise: **"not authorized to rent."** (Currently
UNSIGNED.)

### Gate 2 — POST-RENTAL validation (separate; does NOT authorize rental)
After rental, evaluate ACTUAL **physical-NUMA** evidence: real physical
placement (move_pages on hardware), memory locality, throughput/scaling,
ambiguity resolution, then approve **any production adoption** or
further expansion. **Production adoption requires Gate 2 + separate
authorization; never implied by Gate 1.** Physical-NUMA evidence is
NOT claimed in this work order.

This is a documented gate, not automation. **Do not initiate rental
until Gate 1 independently signed. No physical-NUMA rental was
initiated and no physical-NUMA validation is claimed by this work
order.** No production adoption. No merge to main.

---
*WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-7).
UNSIGNED.*
