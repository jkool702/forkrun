# W-BASHCOMPAT Fix Phase — Completion Report

**Branch:** `NEW/REFACTOR2.9` (single line again; transient `wrel5-*`
worktrees collapsed post-G0). 7 commits on C-head `d9210e3`. No tag,
no release push. Phase 0 diagnosis (`BASHCOMPAT_DIAGNOSIS.md`) is the
binding context; floor **4.4 ratified**; this order supersedes the
original fix-phase assumptions wherever they conflict.

## What Phase 0 got right/wrong (evidence update)

- CONFIRMED: 0.9MB single-line declare dies pre-`enable` (CI shape);
  `rm`-on-memfd `-e` death (reproduced locally 5.2+5.3).
- NEW (found during implementation): a SECOND `-e` death behind the
  first — bare `read -r -d ''` returns 1 on valid NUL-less payloads
  (proven by xtrace after fixing `rm`). Both closed.
- CONTRADICTED: Phase 0's "frun -k workload green on 4.4–5.1". Worker
  execution segfaults on ≤5.1 (core+strace: NULL+0x11 in shell-exec
  state; reproduced on pristine `main:frun.bash` and `a435d97` —
  fully wave-independent). 5.2.21 (extracted, exact CI build) and
  source-built 5.2.0 both run workers green, so the extracted-binary
  methodology is validated and the failure is version-intrinsic, not
  libc-mismatch. **Floor implication for the owner:** bootstrap is
  4.4-clean, but *workers* need 5.2+ pending a dedicated
  worker-runtime investigation. The §4 matrix below is shaped by
  this: full runs where workers run, bootstrap-only elsewhere.

## Per-item table

| Item | Change | Bite / proof |
|---|---|---|
| BC-1 | `declare -A b64=()` + 32KiB appends (max line 32,798B), START..END markers; `_forkrun_b64_emit_chunked` (read-N streaming; fold version was lossy — read strips delimiters — killed with proof); both emitters chunked + tail-preserving; runtime backup = sed region-copy (~5ms) + helper fallback | values byte-identical 7/7 md5; emitter re-run reproduces payload region; twin derivation byte-identical |
| BC-2 | `rm`→`\|\| true`; NUL-read→`\|\| [[ -n out ]]` (EOF-empty stays fail-closed); no-e behavior identical | source-under-`-e` + ring_version: pre rc=1, post rc=0 (5.2.21, 5.3.9) |
| BC-3 | README matrix (bootstrap ×10 everywhere; suites 5.2/5.3; ≤5.1 worker finding stated) + DOCS_ALL mirror; floor was already 4.4 | — |
| BC-4 | `bashcompat-smoke.yml`: 5 legs (full round-trip 5.2/5.3; bootstrap-only 4.4–5.1 with finding cited) + `canary-versions` job | YAML valid; inner commands proven locally (50/50 matrix) |
| BC-5 | 19 stubs annotated (14× since-4.4, 5× unexported markers); `check_canary_versions.py` (`nm -D` for stripped .so — plain `nm` false-greens); `make canary-versions` | green on 8 artifacts (12 stub-matches/prebuilt); post-floor + bare fixtures fail correctly |
| BC-6 | blob-build image documented (no image change — zero blob-cycle risk) + toolchain versions recorded in build logs | — |

## Gate table

| Gate | Result |
|---|---|
| Bootstrap+smoke ×10/version (local) | 50/50 (runs on 5.2/5.3; bootstrap-only 4.4/5.0/5.1) |
| Bash suites 5.2 + 5.3 foreground | 92+264 green on both, zero failures (re-run on final tree) |
| Perf | bring-up 0.12→0.07s; 34MB splice pre/post equal (~0.04–0.05s), byte-exact |
| Canary + versions | both green (annotations are comments) |
| Twins | pre-marker identical; nob64 derived byte-identical via guarded `remove_` |
| Blob size | +4,411B code (+0.42%), +0 payload bytes |
| C-diff | `forkrun_ring.c` untouched (stubs comments + make target are the deliverable) |
| Branch CI (`bashcompat-smoke`) | fedora-5.3 + canary green; ubuntu legs amber-by-design (see below) |

## CI saga + the glibc wall (post-report addendum — READ THIS FIRST)

First CI runs were red for reasons that redefined the project's compat
story. Debugging (TEMP `ENABLE-DIAG` capture, since reverted) proved
two ubuntu-container failure modes, both environmental/toolchain:

1. `/dev/shm` is **noexec** there (`failed to map segment from shared
   object` on the bootloader tmpfile).
2. **Bigger: the shipped x86-64 blobs need `GLIBC_ABI_GNU2_TLS`**
   (gcc-16 TLSDESC codegen; absent on glibc ≤2.39 — Ubuntu ≤24.04,
   Debian 12, RHEL ≤9), so `enable` fails independent of bash version.
   Non-x86 prebuilts don't carry it. The local python substrate
   carries it too (same toolchain). Proven avoidable: a trivial
   `__thread` probe needs it at `-O1`/`-O3`/default **and** with
   `-ftls-model=global-dynamic`, but **`-mtls-dialect=gnu` drops it
   at both opt levels** — the D-wave rebuild item is therefore
   concrete, not exploratory.

Consequences applied in-tree: `bashcompat-smoke.yml` ubuntu legs are
`allow-fail: true` amber (scaffolding kept; fedora leg binds) with
the cause + D-wave item cited in comments; README matrix carries the
two-axis reality (bash findings hold on new glibc; old glibc loads
nothing yet). A ` $()`-wrapped `enable` probe (my own TEMP diagnostic)
silently neutered bootstraps CI-wide for one cycle — caught by the
all-legs-fail signature, fixed to file capture, reverted after use.

8. **CI rescope** (ubuntu legs amber w/ cause cited; fedora binds).

## Incidents + dispositions

1. **Tree corruption via `remove_frun_base64.bash` self-invoke tail**
   (sourcing the file with empty `$@` ran the in-place branch on
   `./frun.bash` — payload stripped, ~200 lines lost). Recovered
   from git (`checkout HEAD --`, byte-identity re-proven); tail
   guarded to execution-only. Lesson recorded in the script.
2. **Fold-streaming emitter data loss** (read strips delimiters —
   newlines lost). Killed with proof; read-N version proven
   byte-identical. Lesson: line-oriented tools can't round-trip
   newline-bearing values.
3. **`nm` without `-D` false-greens on stripped .so** (empty static
   symtabs). Fixed in checker (dynamic for .so, plain for .o).
4. **My probe bugs** (awk END-exit firing on function-body marker
   text; md5-via-`$()` stripping trailing newlines; matrix `cat`
   invocation feeding filenames). Each caught by cross-checks;
   substring emitter retained where it was already proven.
5. **Branch detour** (`NEW/REFACTOR2.10` appeared with the BC base;
   no remote trace — all-local activity). Merged back via
   fast-forward (all history contained), branch deleted, single
   2.9 line restored per standing instruction.
6. **My own `pkill -f` killed the tool shell** (pattern matched
   itself). Session recovered; using exact-match kills since.
7. No flake-registry hits (M8/T10b absent from all runs above).

## Deferred / follow-ups (owner calls)

- Worker-runtime ≤5.1 segfault: needs its own wave (determine the
  crashing construct; floor 4.4 currently means load-only there).
- `mmap`/TAIL-shape: none. Digest pin for blob-build image (BC-6
  documents; full pin in D's cycle if wanted).
- D-wave carries any engine shims (none needed — halt tripwire
  never fired; C-diff clean).
