# W-REL5-E-PYTHON Completion Report — Python Surface Truthfulness

**Branch:** `NEW/REFACTOR2.9` (main checkout, serial phase, off C-head
`0aa2af5`). 7 commits. **Gates:** bites per item, referees 30/30,
`test_wrel5e` 5/5, full suite 621×3 green, `release_check` 17/17
(check count unchanged), perf band held, C-diff empty. No tag, no
release push.

## Per-item table

| Item | Change | Evidence | Files |
|---|---|---|---|
| E5 | `RunConfig` dropped from `__all__` (class stays for the seam); `signal_policy: Any→Optional[str]`; `bytes` kept + shadowing note | import raises ×5; seam-intact control; no docs referenced it (no row owed) | `__init__.py`, `_api.py`, `test_wrel5e.py` |
| E6 | 4 signatures annotated (post-B1 exact); `Mode/Order/OnError/Nodes` wired; `py.typed` packaged (wheel proof) | pre-grep bare defs; `get_type_hints` resolves all four; mypy absent (noted, non-gating); B1 tests untouched-green | `run.py`, `py.typed`, `setup.py`, `MANIFEST.in` |
| E7 | dupe `_watch_live` + dupe mode-check + inner import deleted; `rc==127` kept deliberately; 10 memfd fallbacks + 2 `_tmp_hold` lists deleted; bash guard → unconditional restore (twins identical, syntax + probe green) | per-symbol grep (refcounts → deleted); order cited six, same class found in ten — corrected count, same proof | `run.py`, `frun.bash` + nob64 twin |
| E15 | full close-audit: all sites classify safe; zero changes required | order_w-None probe ×5; fd stability 10 loops; 6-path open-audit script | `test_wrel5e.py` only |

## Grep-evidence summary (E7)

`def _watch_live` 2→1 (identical bodies); `v0 supports mode` 6 pairs→5
(all single); `from ._numa import wid_to_node` 3→2 (inner shadow);
`rc==127`: 0 in run.py, 2 defensive child terminators kept;
`except AttributeError` memfd fallbacks 10→0 (+2 list initializers);
`_tmp_hold` refs 4→0; no test mocked memfd away; bash guard: 2 repo
callers, both `$()` subshells (inert) → unconditional restore.

## Dispositions

- `bytes` field: KEPT + comment (rename churned constructor + seam
  asserts for zero function; shadowing contained via `bytes_`).
- Wrapper/entry value-guards: KEPT (B1 covers names only; fail-closed
  backstops stay).
- `rc==127`: KEPT (fork-discipline safety nets, not dead code).
- Fallback count 6→10: corrected, same class/proof.
- mypy --strict: infeasible (not installed); get_type_hints smoke instead.
- Stale `session-ses_f1c5.md` (untracked Sept-27 session note) moved
  out of tree (was the sole release_check FAIL).

## Deferred to 3.6.1 (explicit)

Internal annotations (E6 scope edge); producing a real `RunConfig`
(API design, not hygiene); `py.typed` consumer-side validation.

## Incidents

1. C4-test dest-suffix bug pattern avoided by construction (new tests
   only). 2. No-op edit mangled a test line — reverted, verified.
3. Missing `tempfile` import in new test file — fixed on first run.
4. Perf trial 589 vs 636 band edge — box noise (spread 589–763 over
   6 trials, overlapping); E7 removed unreachable code only.
5. No flake-registry hits; no new-failure signatures.
