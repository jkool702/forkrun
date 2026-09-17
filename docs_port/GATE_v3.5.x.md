_Pending completion of the leg; appended below when the container finishes._

## 5. Canary false-green fix (found during this gate)

`make -f Makefile.substrate canary CC=aarch64-linux-gnu-gcc` used to print
`canary OK` **without building anything**. Make tracks timestamps, not command
lines: the previous x86-64 objects and `libforkrun.so` were already newer than
their sources, so nothing relinked — while the `canary` target, having no file
of that name, is always "out of date" and so its echo recipe ran regardless.
The artifact on disk stayed x86-64 (mtime unchanged): the check reported success
for a stale, wrong-architecture artifact.

Two defenses now live in `Makefile.substrate`:

1. a **compiler-identity stamp** (`.canary-cc`) as a prerequisite of both
   objects, rewritten only when `$(CC) :: $(CFLAGS)` actually changes — so
   switching compilers forces a full rebuild;
2. an **architecture assertion** in the canary recipe: `file $(OUT)` is printed,
   and a mismatch between `$(CC)` and the artifact's ELF machine is a hard
   failure rather than a success message.

Demonstrated behaviours (all executed):

| Case | Before | Now |
|---|---|---|
| host canary (x86-64) | `canary OK` | rebuilds, prints `canary artifact: ... x86-64`, `canary OK` |
| immediate re-run | `canary OK` | no-op (same BuildID), still `canary OK` |
| `CC=aarch64-linux-gnu-gcc` on this host | **`canary OK` (false green)** | **rc=2, loud failure** (`ctype.h: No such file or directory` — the cross toolchain has no libc headers/sysroot here) |
| switch back to host CC | silent stale artifact | forced rebuild, new BuildID, re-verified `x86-64` |

`OUT ?= libforkrun.so` is now overridable (`OUT=libforkrun.aarch64.so`) so
multi-arch canary runs do not clobber each other — the same confusion that
produced the false green in the first place.

## 6. Documentation arithmetic (DOC-1)

Verified rather than edited:

* the utilization/benchmark figure is `396` consistently in `README.md`,
  `DOCS/FORKRUN_OVERVIEW.md` and `DOCS/DOCS_ALL.md`;
* the test-run claim is internally consistent: `354 avg unit tests + 396
  benchmark runs = 750`, times `(UMA + NUMA)` times `(baseline + TSan +
  ASan/UBSan)` = `4,500`, of which `4,272` successful;
* the current suites measure `test_frun.sh` = **89** and
  `test_frun_comprehensive.sh` = **254** (343 total), with the C-plugin suites
  — `test_all.sh` runs five suites — supplying the rest of the documented ~354
  average. No stale unit-test count was found, and no `316` figure exists
  anywhere in the repo (that was an error in the initial review, not a doc bug).

## 7. What this log does NOT prove

Stated so the log cannot be read as broader than it is:

1. **Emulation, not silicon.** The aarch64 results come from
   `qemu-aarch64-static` user-mode emulation. QEMU does not faithfully model
   weak-memory reordering and serialises many accesses, so these runs show
   *functional* correctness and the absence of architectural regressions — they
   are **not** an empirical validation of either fence's ordering property,
   including the D1 reader-side `__atomic_thread_fence(__ATOMIC_ACQUIRE)`.
   That still requires ARM hardware (or a reordering-aware model); the D1
   writer/reader pair remains static-review-correct plus these functional runs.
2. **One physical NUMA node.** Every "NUMA" cell above is software-partitioned
   via `--nodes=N`. Real multi-socket topology, born-local affinity and
   cross-node escrow behaviour are not covered by this log.
3. **No sanitizers.** TSan/ASan/UBSan legs were not run in this window; they
   remain part of the documented matrix and are required before release.
4. **No TUI leg.** `ring_tui` is not exercised here.
5. **THP sensitivity.** The sweep suite is THP-sensitive by construction (§3);
   the clean result depends on `shmem_enabled=always`.
6. **No performance claims.** Nothing here speaks to throughput, latency or
   utilization.
## 8. F30/T14 round (`--nodes=@N` ceiling; W-D4 invocation fix)

F30: `ring_init` + `_forkrun_build_numa_map` reject `@N > 512` (meta_ring
capacity), non-numeric `@abc`, and overflow literals (bounded digit regex)
with early-fatal `[ERROR]`, non-zero exit, no checkpoint. Lock-in T14 covers
all three in an isolated directory. Verified this round: `@513`/`@abc` both
give rc=1, `[ERROR]: --nodes=@N` on stderr, no `.forkrun_resume` — after W-D4,
which fixed T14 calling bare `frun` (undefined in the suite shell, rc=127
permanent red) by routing all three sub-cases through
`bash -c "source '$FRUN_SOURCE' && frun ..."` in both twins.

## 9. W-B round (cleanroom pidfile + R2/R10 rewrite)

Pidfile write site placed after trap install; R2/R10 rewritten with bounded
pidfile waits, `--nodes=@2` on both; D6 exit-code preservation locked
(trapped-signal codes survive; no spurious FATAL on clean early exit).
Verified complete per the handoff checklist; no changes in this window.

## 10. F15 round (NUMA steal over-claim orphan)

One-word C fix (`goto unified_scanner_eof` → `continue`: a thief that
over-claims the victim's queue re-checks its own instead of exiting and
orphaning since-published own chunks) with full comment. Lock-in F15a
(conservation matrix {file,pipe}×{@2,@4}×{default,-s}, 50k lines) and F15b
(10× ≥1M-line pipe herd) plus changelog entry, all landed earlier this cycle.
Smoke-verified post-D8 (default-mode NUMA telemetry present, byte-exact).

## 11. D8 round (INDEXER_DEATH fd-2 blackout)

The handler's bare `exec {fd_indexer_death_r[$sID]}<&- 2>/dev/null` persisted
`2>/dev/null` in the main shell, swallowing all post-reactor stderr
(telemetry, verbose, checkpoint hints) while stdout stayed byte-exact and
rc stayed 0 — mode-correlated by the reactor-exit race, introduced by the D6
work (v3.5.0 benchmarks showed default telemetry fine). One-line fix matching
SCAN_DEATH's form in both twins; audit found no other bare-`exec` with a
persistent `2>/dev/null` (remaining instances sit inside process
substitutions). F15a/F15b tightened to require Node frames in every
combo/iteration (special-casing and KNOWN-FLAKE block deleted); changelog
flake-caveat replaced with the D8 entry. Smoke: `--nodes=@2/@4 --stats`
default-mode runs show Node frames, byte-exact, rc=0.

## 12. F29/D9 round (consent-gate integrity + PATH decision + Section T)

W-D mechanism (positional readonly+shift token close, quoteless `_emit_all`
EXIT-trap emission, shape filter, `FORKRUN_TRUST_RESUME` denylist, round-trip
re-render, preview at all three consent sites, ownership gate after
extraction) verified against the handoff checklist. D9: `PATH=/nonexistent`
reverted to `PATH=''` at all four sites per owner determination (red line).
New lock-ins, all passing (SECTION=T 21/21 on the final construction):
T1g (positional forgery fail-closed), T1h (cmdline forgery neutralized,
benign ORIG_ARGS), T1i(i) (plain setup reaches the layer-3 gate, no
overblock), T1i(ii) (escaped substitution stays literal), T1a-ext
(double-forked delayed orphan wins the greedy-anchor race — proven once with
an ORPHAN_WON tripwire — then neutralized; order-independent assertions),
F6 characterize-only probe. F6 result (2026-09-16, bash 5.3.9): marker
PRESENT — empty PATH resolves CWD (`./touch`); `/nonexistent` does not; no
default-PATH fallback (control without wrapper: absent). Contained by design
(restricted mode, wipe, re-render, denylist, no parent-side eval); recorded
in SECURITY.md with the pre-consent same-UID threat boundary. M (24/24,
M20/M21 post-revert) and T2 (16/16) re-verified.

## 13. W-E round (F28 `-L` scan helper)

`fr_simd_available()` + `-L`-only `scan_nth_delim()` added;
`try_simd_scan` byte-identical; handoff inner loop claims need-th delimiters
with `-n` budget clamping, single tail-count, unchanged flush sites. Built
pristine/modified v4 blobs locally with identical flags (local-before matches
the shipped blob size 203912). Before/after on 100M-line seq (889MB,
`--nodes=@2`, x86_64, single runs): -L 1000 file/pipe×default/-k 9.78–9.99s
→ 10.00–10.15s; -L 10000 9.46–9.55s → 9.67–9.78s; interleaved A/B re-runs
indistinguishable (10.02–10.15 vs 10.09–10.18) — perf-neutral; scan is not
binding here (no-op isolation `-L 1000 :` 5.82s vs `-l 1000 :` 5.78s).
Acceptance on the W-E blob: F7 exact, F 7/7, T2 16/16, `-L`+`-n` probes
bit-identical ×4 shapes, new F8 green on both blobs. BORN_LOCAL_NUMA §5
("≈ UMA scan speeds") re-confirmed, unchanged. Blobs NOT committed (CI
rebuilds in W-I). Loose ends observed (pre-existing, both blobs): `-L 100000`
intermittently aborts (worker-139/trap-grace, clean-prefix truncation) on
pristine and W-E alike; one unreproduced `-L 100` short-count transient
(1 of 8); system `sort` segfaults on 889MB here, so content checks used awk
count+sum+min+max.

## 14. W-G round (dedup + docs + twin check)

Deleted the earlier simple copies of M17/M20/M21 (diagnostic variants kept),
both always-green T10b_diag blocks (diagnostics folded into T10b's failure
path; single DEBUG-on T10b kept), and M20's stray debug lines — 6 test-count
reduction, in both twins. Reconciled three pre-existing test-twin drifts
toward the newer variant (T1f shadow/grep, T13 killer fraction); test twins
now byte-identical. Docs: INVARIANTS §14–17 → §13–16 with the v3.5.0
changelog ref updated to current numbering (convention: historical entries
track current section numbers); F3 total-vs-useful labeling; F38 ≥1B-line
run-length qualifiers. CI: new `twin-check` job (frun lockstep modulo the
single blob line — a literal cmp would false-fail by construction — plus
literal test-twin cmp).

## 15. What this log does NOT prove (appendix, kept current)

Items 1–6 above still hold (qemu-not-silicon, one NUMA node, no sanitizers
in this window, no TUI, THP sensitivity, no performance claims beyond §13's
single-box table). Additionally: (a) W-E before/after is one box, one arch
(x86_64_v4), single runs plus one interleaved triple — a structural-neutral
reading, not a cross-platform performance claim; the `-L 100000`
instability note in §13 is observational (n≈12 across both blobs), not a
root-caused finding. (b) D10's F6 closure is bash-5.3.9-verified plus POSIX-reasoned (an
empty PATH component means CWD by specification, so no bash version
resolves a deleted directory); the hard F6 assertion re-verifies it on
every Section-T run. (c) Test-count arithmetic for
the release matrix belongs to W-I; §14's dedup changed comprehensive-suite
totals (see the W-I reconciliation).

## 16. D10 + PF-1 + W-I.1 blob rebuild (final-prep state)

D10 (dead-PATH construction, both restricted shells, both frun twins;
F6 characterize-only → hard assertion; SECURITY/CHANGELOG + DOCS_ALL
twins in lockstep): SECTION=T 21/21 (T1a/b/d/f/g/h/i, T1a-ext, F6-hard
green), SECTION=M 21/21 (M20/M21 green), SECTION=F 8/8 (F8 green).

PF-1: `twin-check` now compares the frun twins' pre-b64-marker region
(`cmp <(awk '/_BASE64_START_/{exit} ...')`, robust to multi-line payload
drift) plus the byte-identical test-twin cmp; verified locally.

Canary-in-CI fix (first live runs): run 35172127607 showed VERIFY 7/7
OK but the new canary step failed — `apt-get install libbash-dev`
(no such package on ubuntu runners; `config.h` missing). Per owner
direction (Fedora for everything) the step now runs
`make -f Makefile.substrate canary` in `fedora:latest` docker with
`dnf install bash-devel` (commits ce06110, 56584e6).

W-I.1 rebuild: run 35173548966 (manual dispatch of the fixed workflow)
conclusion success — VERIFY-OK for all 7 keys (x86_64_v2/v3/v4,
aarch64, ppc64le, s390x, riscv64; no WARNs), `canary OK: libforkrun.so
links with no undefined symbols`, auto-PR #534 (frun.bash + 7 blobs;
pre-marker region verified identical, D10 intact). The 56584e6 push had
also auto-triggered duplicate run 35173547278 (success, PR #535).
Merged #534 (merge commit 7e5d014; x86-64 blobs 203912 → 208008 bytes
with F28 + v3.5.1); closed #533 as stale (blobs predated F28 and the
version bump) and #535 as a duplicate of #534.

Post-pull smoke (minutes only, all green): `ring_version -a` →
v3.5.1 (x86-64-v4, Fedora GCC 16.2.1, built Sep 17 02:14 UTC);
`frun -V` → v3.5.1; `test_frun.sh` 89/89; `seq 10000 | frun -k
printf '%s\n' | wc -l` → 10000; local canary OK; python unittests 14 OK.

CI confirmation of PF-1: `twin-check` green on run 35174209682
(manual `sh-format.yml` dispatch of the merged state). The sibling
`sh-checker` job is red there, but it has failed on `main` since July
2026 — pre-existing lint noise; differential shellcheck shows zero new
findings from the v3.5.1 work (SC2016 count identical pre/post D10).
Release runbook: `docs_port/RELEASE_RUNBOOK.md` (owner's manual matrix).

## 17. F31 — emit fallback resumes after partial sendfile (v3.5.1)

A v3.5.0-review finding, confirmed still present: after a
positive-short sendfile, `forkrun_emit_with_fallback` fell through to a
full-range `ring_copy_chunk(off, len)`, duplicating the emitted prefix.
Pre-existing (v3.4.3 O_APPEND fallback), exotic trigger, ordering and
ledger untouched. Fix (commit 8265251, one function): resume at
`(off+s, len-s)` on `s > 0`; keep the full-range copy on `s < 0`
non-EPIPE (`robust_sendfile` returns -1 only with zero progress — the
review sketch's resume arithmetic is valid for `s > 0` only).

Verification, all green: LD_PRELOAD sendfile/sendfile64-interposition
harness against the exact TU (glibc routes sendfile→sendfile64; both
symbols interposed) — old code +64 duplicated bytes (bug reproduced),
fixed code byte-exact, hard-fail-first exact in both; basic suite 89/89
on a locally built v4 blob (CI-identical flags, 208008 bytes); CI
rebuild run 35175902953 success (VERIFY-OK all 7 keys, canary OK),
auto-PR #537 merged (merge e862a59); post-pull smoke: local v4
decode-and-cmp OK, `ring_version -a`/`frun -V` v3.5.1 (built Sep 17
02:51 UTC), `test_frun.sh` 89/89, 10k sanity exact, canary OK, python
14 OK. Intermediate owner-merged PR #536 (run 35175093479, pre-F31
blobs) superseded by #537 as the shipped-blob source.

**Engine change: the owner matrix must be re-run before tag**
(MAINTAINERS §5 Matrix Policy Rule) — the §16 smoke results predate
this fix.

## 18. Test-findings round (NEW-D1 + W-LA3; no engine changes)

NEW-D1 closed: F8 now `--nodes=@2` (forced-count NUMA arms, both test
twins), still green — the F28 clamp coverage is real, not vacuous.

W-LA3: LA3's every-budget wedge was 84-minute payloads, not an engine
hang — line-args mode runs `sleep 0.01 ${lines}` and GNU sleep SUMS
operands (batch 1 ≈ 5050 s; ≈ 3,970 CPU-years total). Consequences,
all verified: Bug Z dissolves (healthy pipeline doing requested work;
0-bytes-ever is the only consistent signature); the emulated abort-hang
dissolves into teardown bounded by in-flight payload duration (benign,
pre-existing, now a documented characteristic — R2/R10 abort fast only
because their payloads are 0.1 s); the §3 orderer/fallow loose end
resolves present (census: 28 workers + anon_pipe_read pair + timer;
indexers/scanners healthily exited post-ingest); no engine defect found
anywhere in the violent-death chain. Redesign, test-side only, both
twins: `printf` payload, endless SIGPIPE-clean feeder, liveness-gated
kill, five-fact failure capture. Acceptance: 3× standalone green plus
full Section L 57/57 on x86_64 (LA3 in-suite green, incl. LA4/F15a/F15b).

Hygiene incident: /tmp filled to 81% (a 15 GB census out.txt of mine
plus pre-existing W-E artifacts), making the suite gate FATAL on
here-docs ("Disk quota exceeded") until cleaned. Rule going forward:
endless-feeder outputs go to /dev/null or bounded files, and diag
artifacts are removed the same session. My /tmp/la3_* files are gone;
wE_* and the previous session's /tmp/la3dbg left untouched. The three
Sep-16 orphaned `seq 500000`s (PIDs verified pre-kill) were reaped.

Parked (non-release): the `.txt`-twin triplication decision (reference
snapshot vs twin-check membership); NEW-D2/D3 folded into Stage 1 /
convenience per the audit. aarch64 leg resumes after LA3 green with a
re-synced copy (banked: basic 89/89, D 11/11, L-minus-LA3).

## 19. Signal-state init race (R2/R10 exit=1 on the aarch64 leg)

The emulated Section R failed exactly R2/R10 with exit=1/cp=yes (trap
ran, checkpoint published, wrong code). Root cause: the reactor's
`local _ret_val=0; local _fr_signalled=""` ran ~500 lines AFTER the
pidfile readiness write, so a signal landing in the spawn window had
its trap-recorded values reset before the ABORT case read them —
falling into the reason≠1 arm (exit 1). Deterministic where the spawn
window spans seconds (emulation), rare natively (millisecond window),
which is the whole arch split. Fix, both frun twins, no blob impact:
initialize the two locals immediately before the pidfile write (with a
do-not-move-back comment at the old site). Verified: x86_64 Section R
13/13 unchanged, emulated Section R 11/13 → **13/13** (R2/R10 at
138/143), `-L 100` spot-check 10×100 on aarch64. Full aarch64 UMA leg
now green: basic 89/89, D 11/11, L 57/57 (LA3 in-suite), T 21/21,
M 21/21, F 8/8, R 13/13. NUMA-topology portion still waits on the
`numa=fake=4` reboot.
