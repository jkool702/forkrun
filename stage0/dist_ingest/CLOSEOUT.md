# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — Closeout

**Work order:** CK-5→CK-1→CK-6→CK-2→CK-4→CK-3→CK-7 corrective pass.
**Base:** `66efac3ebaed84a4265f9c3c82686961ed7fb42a`
(branch `WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-IMPL`).
**Working branch:** `WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2`.
**No rental. No production adoption. No physical-NUMA validation. Frozen
production files untouched. Not merged to main. No MADV_POPULATE_WRITE /
prepopulation-window / per-node-memfd / production-ingest changes.**

## Identities (distinct; CK-7.1; no self-referential commit hash)

- **Sanitizer-tested source SHA:** `408283c9df488e5338d911d94b249a35f473aad0`
  (clean tree; ASan+UBSan + TSan; see SANITIZER_EVIDENCE.md). NOT
  claimed as final branch HEAD.
- **Final C-code SHA:** last commit touching
  `stage0/dist_ingest/dist_ingest.c` = `a6ba01a0ccfb3ba51d8fd3af11ae7d87f0fb3213`;
  `dist_ingest.h` = `6a0d6cd47eb4cb632f6086578681ab8109c41098`. C
  unchanged afterward; sanitizer-tested C == final C.
- **Final branch HEAD:** actual `git rev-parse HEAD` in terminal
  closeout report (not requiring a commit to contain its own hash).
- **Subsequent documentation-only commits:** listed in terminal report;
  this commit and later doc-only commits do not change C/sanitizer
  evidence.

## Checkpoints

| CK | status | summary |
|---|---|---|
| CK-5 | PASS | real invariant checking + enforceable; publication checker pre-admission; propagated; no invalid publish; materialized flag; checked arithmetic; no silent clamping; post-join reconciliation (normal+injected); original error preserved; extra reported; tests both activation + malformed; CK5_INVARIANTS |
| CK-1 | PASS | mandatory preflight fail-closed (clean rc + artifact absent + fresh build + exists + produced-by-this-build; no stale; no sanitizer exception); isolated DI_OUTPUT; accurate env (shmem THP + per-size; global vs shmem; swap vs active pswpin/pswpout; actual compiler/cmd/flags; optional consequences; no stale libnuma); tests; JSON=console |
| CK-6 | PASS | corrected classifier semantics; actual C instrumentation; no consumer-limited; starvation/backpressure/read/claim; zero-claim split; normalization + denominators; validation→indeterminate; actual wall + configured max_backlog (no hardcoded 1.0; no high-water-as-cap); not swallowed; DIST_RESULT evidence; pairing key (no candidate); duration-normalized; paired regime-grouped report; **automated regime decision DEFERRED; 15% not guarantee**; same classifier; tests |
| CK-2 | PASS | queue-push injection fired + result + join + reconcile; pread immediate/after-partial/premature-EOF + no rate-limit-after-error + rollback + join; alloc-fail + thread-create-fail + partial-init; proven; accounting; prompt bound; LIVENESS accurate + sleep bounds; no heartbeat |
| CK-4 | PASS | enforceable source + syscall + undefined-symbol audit; fail-closed; allowlist; unknown→review; multiline+alias; inline-asm; clone/clone3; nm; pthread_create ok; bad honored; threads_only honest; FORK_AUDIT; tests |
| CK-3 | PASS | atomic inventory regenerated actual (43); all sites; corrected next_offset ACQ_REL / outstanding+published not atomic / peer_headroom / stop / ingestors_done / input_changed / test atomics; mutex inventory; sanitizer harness fail-closed; instrumentation; artifact unchanged; LSan honesty; ASan+UBSan+TSan rerun final C; logs+results retained; SANITIZER_EVIDENCE; **LSan not validated (full suite); separate smoke; not proof** |
| CK-7 | PASS | identities; history archive corrected + full preservation; rental gate unsigned + accurate; provenance |

## Validation (see terminal report for exact commands/results)

- `python3 -m unittest discover -s stage0/dist_ingest/tests`
- `python3 -m unittest stage0.tests.test_stage0`
- `python3 -m unittest python.tests.test_numa_drain_guard`
- `python3 -m unittest python.tests.test_numa`
- preflight (`tools/di_preflight.py`) normal + deliberate-failure;
  JSON=console; stale-artifact + broken-compiler fail-closed
- `python3 tools/di_symbol_audit.py` rc matches results
- invariant runtime + compile-time tests; valid + injected invalid
- sanitizer harness asan-ubsan + tsan final C; nonzero on REVIEW_REQUIRED;
  retained logs/results
- repo integrity: clean; pushed; frozen files untouched; no main merge;
  no rental; no physical-NUMA claim; no MADV_POPULATE_WRITE

## Historical archive
Full previous artifacts preserved in `CLOSEOUT_HISTORY.md`; corrected
"444-line" claim; git intact.

## Rental gate
`RENTAL_PLAN_REVIEW.md` — **UNSIGNED; not authorized to rent.**
Automated regime-based decision-making DEFERRED. LSan not validated
(full suite). Physical-NUMA evidence not collected.

---
*Closeout WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2.*
