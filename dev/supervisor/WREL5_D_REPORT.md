# W-REL5-D Completion Report — C Engine Hardening, Blob Cycle, ≤5.1 Segfault

**Branch:** `NEW/REFACTOR2.11`. **Status:** code complete, matrix running.
No tag, no release-branch push (owner tags after F2–F6 + tag prep).

## 1. C-diff audit (R5.3 — per commit, `*.c`/`*.h` only)

Base `0300611` (merge #568). Every C-touching commit stays inside the
enumerated D1–D15 + D-TLS/D-STRICT/D-SEGFIX surface; the only generated
files are the mechanical IDL regen (`forkrun_callschema.h`,
`tools/generated/{fr_ctypes,usage_table}.json` — ring_poll renames).

| Commit | C files | Within surface |
|---|---|---|
| 76bbbd2 D-README | — | docs only |
| 98fce81 D-SEGFIX | `forkrun_ring.c` (pair parser, scrub env), `forkrun_callschema.h` (regen) | §1 sites, named in message |
| 760452d D-STRICT | `forkrun_ring.c` (-8), `substratestubs.c` (-1) | deletions only |
| 7880d88 D-TLS | — | workflow flags only |
| 1213ec3 D1–D3 | `forkrun_ring.c`, `_shim.c` (D2 twin) | D1, D2, D3 |
| 3447fe2 D4–D7 | `forkrun_ring.c`, `_shim.c` | D4, D5, D6, D7 |
| 78b2ee7 D8–D11 | `forkrun_ring.c`, `_shim.c` | D8, D9, D10, D11 |
| eb4135b D12 | `_shim.c` | D12 (header regen no-op, `--check` clean) |
| b3e7153 D14–D15 | `forkrun_ring.c`, `_shim.c` (comment) | D14, D15 |
| 69ad9f6 D-LEGS | — | workflow only |
| a0e0422 D2-coherence + D11-revert | `forkrun_ring.c`, `_shim.c` | D2 sites; D11 removal |
| 5fb28fd suite revert | — | tests only |
| a6ab408 changelog | — | docs only |

Non-`*.c`/`*.h` product changes: `frun.bash` (pair lists, `FD_WORKER_W`
export — D-SEGFIX call sites), `frun.nob64.bash` twin (regenerated),
`tools/idl_schema.py` (contract rename), `bashcompat-smoke.yml`
(D-LEGS), `tools/check_canary_versions.py` (doc example), matrices.

## 2. D-SEGFIX disposition — ROOT CAUSED AND FIXED (no parking)

- **Bite (pre-fix, deterministic):** `printf "" | frun -k -j1 -l1 echo`
  under source-built bash 5.1.0 → SIGSEGV every run (also 4.4/5.0/5.1
  extracted). Payload/order/input-size independent (`:` , unordered,
  empty all crash); `enable -f` + `ring_version` alone green.
- **Mechanism chain:** strace (first `ring_poll` never returns;
  `SEGV_MAPERR si_addr=0x11` in a forked pipeline subshell) →
  termsig re-raise identified (bash `termsig_handler` runs the EXIT
  trap = FATAL+checkpoint, then `kill(getpid(), SEGV)`) → fault RIP
  inside the `.so` text (memfd-backed mapping) → v4 disasm at
  file-offset `0x24a21`: `mov 0x10(%rax),%r15` with `rax=1` →
  `struct array` layout drift 5.1→5.2 (`head` 24→16, `num_elements`
  int→int64). The new-header engine read offset-16 = the small int
  `num_elements` as a pointer. `SHELL_VAR`, `array_element`,
  `bind_*` API all verified stable — only `ARRAY` internals moved.
- **W-MAPAPI correction:** H2/binding/struct-builtin/registration
  exonerations stand but were insufficient (the toy binds, never
  iterates). H1-class confirmed for `struct array`.
- **Fix:** frontend flattens fd watch-arrays to `"id:fd"` pair lists;
  `ring_poll_main` parses pairs (fail-safe, `max_poll` drop-tail);
  feeder scrub reads `FD_WORKER_W` from environ. Zero ARRAY-struct
  reads remain (3 sites). Subscripted `find_variable("name[i]")`
  probed NULL on 5.1.0 AND 5.3 (toy) — no in-engine alternative.
- **Green:** 200-line byte-exact round-trips on
  4.4.20/5.0.17/5.1.0/5.1.16/5.2.0/5.2.21/5.3.9; 8/8 battery; zero
  new cores. Floor back to bash ≥4.4 (ships in the blob cycle).
- **D2-coherence follow-up (spec bug in the order, caught by gates):**
  bare offset-reset broke respawn-onto-same-file (init syncs offset
  but left cached fd → spurious change → zeroing → duplicates:
  invariant-gate §6/§9 + bash poison suites). Fix: init adopts the
  trio (offset+fd+mode).

## 3. D-TLS evidence

- `readelf -V`: shipped x86-64 v2/v3/v4 carry `GLIBC_ABI_GNU2_TLS`;
  non-x86 verified clean (untouched).
- Local gcc-16 proof: requirement present without flag, absent with
  `-mtls-dialect=gnu`; U-set otherwise unchanged (one new
  `__tls_get_addr@GLIBC_2.3` ref, harmless); size −288B (−0.13%,
  TLS sequences only; source-identical).
- Floor stays glibc **2.38** via `__isoc23_strto*` (gcc-16 C23
  aliasing) — unblocks ≥2.38 (Ubuntu 24.04+, Fedora, Arch);
  Debian 12 (2.36)/RHEL ≤9 need a `-std=gnu17` follow-up (3.6.1).
- Workflow: flag on the x86-64 triple build only. Functional 7/7
  legs green on the flagged test blob.

## 4. Perf deltas

- 1M heavy-UDF A/B (1.34GB `heavy_1M.jsonl`, Python upper, UMA 28w,
  order=index, same box back-to-back): current 529/537/556 MB/s vs
  pristine 555/553/548 (medians ~537 vs ~553, ~3% — run-to-run noise
  on a payload-bound workload; warmup visible in-run). No perf
  sacrifice from the hot-path-adjacent changes (pair parser, ack
  trio, hook paths net-untouched). (Method note: the B3/B5 636–781
  band is a lighter workload; A/B parity on identical work is the
  binding comparison.)
- heavy-20M within variance: quads below (26–30s/run, same as the
  established 26–28s).
- Bring-up unchanged post-D-STRICT: registration path was never
  called (Exp 3) — validated by bootstrap timing in suites.

## 5. Matrix results

- Python suite ×3 (final tree, clean signal mask): **621/621 OK
  (8 skipped) ×3**. (Earlier background runs on mixed tree states
  discarded uncounted; two taxonomy/doc failures in nohup-poisoned
  runs traced to the harness, §6.)
- Bash suites foreground (segtest = tree code + all-wave v4 engine,
  clean mask): test_frun.sh (92) ALL PASS on 5.2.0 + 5.3.9;
  test_frun_comprehensive.sh (264) ALL PASS, Skipped 0, on both.
- Compat legs (D-LEGS): validated locally (7-leg battery green:
  4.4/5.0/5.1.0/5.1.16/5.2.0/5.2.21/5.3 round-trips byte-exact);
  CI legs run at merge/cycle (docker unavailable here).
- Heavy NUMA (26.9GB `heavy_20M.jsonl` pregen, C plugin, w=28,
  order=index, `FORKRUN_DIAG_NUMA1=1`): **QUADS-EXACT 6/6** (ref×2 +
  @4×4, joined-bytes sha `2dc0390764ea` — matches the G0 reference;
  per-node drains write==read, zero guard trips).
- F-PY-UMA1 (`test_mover.py` ×10) + F-NUMA1 (`test_numa_drain_guard.py`
  ×10): 20/20 OK.
- Referee gates: executor-consistency + invariant-gate +
  doc-accuracy + shim-ABI **30/30 green** (final tree); checker
  (in-suite), canary + canary-versions + IDL green.
- `release_check.py` 17/17: PENDING (runs after this report
  commits — the tree-clean gate needs it committed).
- Twins lockstep: nob64 regenerated (43 code lines, 0 b64);
  CHANGELOG/DOCS_ALL mirror appended (twins check in gate).
- Sanitizers: DEFERRED to the very end per owner (not this wave).

## 6. Known-flake dispositions

- Registry cited before anything called new (C-drain framing,
  reactor-ingest multiset, T10b, M8, bench noise). No registry
  signature observed.
- Two genuinely-new signatures caught and FIXED (not flakes):
  invariant-gate §6/§9 (D2-coherence) and bash poison duplicates
  (same root, engine side). Both reproduced deterministically
  (2/2 isolation, 8/8 `-j1`) and verified fixed (125-combo green,
  `-j1` ×5, full `test_frun.sh` ×2).
- One D11-shaped combination failure analyzed to a flawed premise
  (see §7), reverted, verified (125-combo green).
- **Harness artifact (nohup signal-mask poisoning — caught
  mid-matrix):** background launches via `nohup(1)` bequeath
  `SigIgn=0x7` (HUP/INT/QUIT) to the whole subtree. That invalidated
  two classes of background results: bash T12 HUP waits hung 40+ min
  (`wait` on a trap-deaf pipeline; `do_wait` + `poll` wchans), and
  `test_taxonomy.test_death_cause_mapping` failed (self-kill with
  TERM/INT ignored → exit 42, `WIFSIGNALED` false — also poisoning
  the derived doc-accuracy claim). It is NOT product code (no wave
  item touches signal disposition), NOT a suite bug (8/8 green
  foreground; `signals`+`taxonomy` pair green), and NOT the earlier
  "pre-existing" call (both trees' background runs were equally
  poisoned — that control was void). Fix: `/tmp/clean_run.py`
  launcher (Python resets HUP/INT/QUIT/TERM to `SIG_DFL` pre-exec;
  verified 0x0 under `nohup`); all background matrix legs
  relaunched through it. Standing rule: signal-sensitive suites
  never run under bare `nohup`.

## 7. Deferred-and-why

- **D13** (`%lu`→`PRIu64`): registered, untouched — pairs with the
  post-tag sanitizer legs (LP64-correct today).
- **D11** (hook master switch): HALT-AND-REPORT. Uncached-master
  saves nothing (1 getenv either way); caching OFF poisons
  cross-module runs (proven: 4 adversarial failures in combo, green
  alone); caching ON saves nothing (specifics still fresh);
  compile-out breaks default-build suites. Guarded cost (~150ns
  per claim+commit vs microsecond batch work) is negligible.
  Hooks stay as W-PY29 wrote them.
- **D14 mechanism**: declined with analysis (mincore TOCTOU, mlock
  ineffective, SIGBUS-handler too risky); comment carries the
  invariant argument + contract rule.
- **D-SEGFIX parking**: NOT USED (landed). 4.4 worker cores beyond
  round-trips: suites run 5.2/5.3 only (stated in matrix).

## 8. What this does NOT prove

- Non-x86 blobs in the cycle (built by CI; local audit x86-only).
- CI-leg behavior (no docker here; leg logic validated locally).
- 4.4/5.0/5.1 full SUITES (round-trips only by design; D-LEGS 5.1
  leg is the permanent guard).
- Post-cycle tree-blob equivalence (freshness gate runs in CI;
  local analog FRESH-OK on all three x86 variants).

## 9. Halt-and-report log

1. D4 sketch (`if (niov == 1) break;`) would regress `b""` emits
   (outer loop writev-len-0 → n==0 → -1); implemented `niov = 0`
   instead (test_v1_emit 16/16).
2. D11 premise falsified (see §7); reverted, verified.
3. D2 prescription incomplete (see §2); completed via trio.
4. UBI8 leg cannot go green in-cycle (2.38 floor > 2.28);
   documented amber-with-cause, not skipped.
