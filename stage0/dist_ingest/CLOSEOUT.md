# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — Closeout

**Base (corrections-4):** `a1db06a0`
**Final SHA:** `3a92373f644a6a0152abb1a3019250986bf8ce07` (working tree clean)
**Status:** all 7 checkpoints complete; no rental.

## Checkpoints (one per commit)

| CK | Subject | Commit |
|---|---|---|
| CK-1 | Build portability + preflight honesty | `72f170da` |
| CK-2 | Liveness audit + fault-injection termination | `6135e6c4` |
| CK-3 | Atomic semantics + sanitizer harnesses | `7c6ab6be` |
| CK-3 fix | Preflight accepts sanitizer-runtime builds | `a73f8ba9` |
| CK-4 | Threads-only invariant + fork audit | `d64f91a1` |
| CK-5 | Invariant assertions (deadlock fix) + tests | `85f83c9e` |
| CK-3/6/2/4 review fixes | Deadlock, classifier semantics, fail-closed preflight, symbol audit, sanitizer rerun | `fc49efb9` |
| CK-6 | Regime classifier (authoritative) + DIST_RESULT regime | `766025bd` |
| CK-6/3 fixes | DIST_RESULT regime + harness robustness | `48354ae0`, `21fc710e` |
| CK-7 | Rental plan gate + closeout | `b7cb81dc` |
| CK-3 | Atomic inventory + sanitizer evidence at `21fc710e` | `3a92373f` |

### Archival of pre-review closeout history

Archived to `stage0/dist_ingest/CLOSEOUT_HISTORY.md` (original 444-line
history preserved).

## Suites (final SHA 3a92373f)

- `discover -s stage0/dist_ingest/tests`: **276 OK**
- Sanitizer harnesses (`tools/di_sanitizer_harness.sh`): ASan+UBSan (276,
  0 findings) + TSan (276, 0 findings) at `21fc710e`
- Symbol audit (`tools/di_symbol_audit.py`): `threads_only_symbols_ok=true`

## Rental gate

`stage0/dist_ingest/RENTAL_PLAN_REVIEW.md` — unsigned (not authorized).

---
*Closeout by WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 (corrections per
external review of b7cb81dc).*
