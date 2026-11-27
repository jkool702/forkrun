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
      [ ] atomic inventory regenerated (actual 43 sites).
- **CK-4:** [ ] required tests pass on final reviewed HEAD; [ ]
      enforceable symbol/source/syscall audit (`di_symbol_audit.py`,
      fail-closed) — `threads_only`.
- **CK-5:** [ ] invariant checking real + enforceable; publication
      checker before admission; propagated; no invalid publish;
      accounting reconciliation; post-join; activation consistent.
- [ ] Placement/physical-NUMA evidence limitations understood
      (fake/local NUMA ≠ physical; mbind syscall ≠ physical placement;
      no physical-NUMA validation claimed).
- [ ] Teardown, artifact preservation, host cleanup ready.
- [ ] No outstanding P1 correctness/readiness findings.
- [ ] No production adoption; production files frozen; no
      MADV_POPULATE_WRITE / prepopulation / per-node memfd / production
      ingest changes; **no rental initiated.**

## Recorded provenance
- Reviewed source SHA: ________________
- Sanitizer-tested SHA: `408283c9df488e5338d911d94b249a35f473aad0`
  (re-verify at review; see SANITIZER_EVIDENCE.md + CLOSEOUT.md)
- Final C-code SHA / final branch HEAD / doc-only commits: see CLOSEOUT.md
- Reviewed plan artifact path: ________________
- Reviewer: ________________  Date: ________________

**Sign-off:** physically signed OFF/ON — all items pass + deferrals
accepted + physical-NUMA evidence collected on rented hardware, rental
authorized. Otherwise: **"not authorized to rent."**

This is a documented gate, not automation. **Do not initiate rental
until independently signed. No physical-NUMA rental was initiated and
no physical-NUMA validation is claimed by this work order.**

---
*WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-7).
UNSIGNED.*
