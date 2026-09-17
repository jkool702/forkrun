# forkrun v3.5.1 — Release Runbook (owner's manual matrix)

Frozen code: `NEW/REFACTOR_7` @ 7e5d014 (blob merge) plus the W-I.2 docs
in this directory. No product-code changes during the matrix — any
post-run code change invalidates the full matrix and requires a complete
re-run (MAINTAINERS §5 Matrix Policy Rule). Any red anywhere: report
before tagging. **The owner executes the tag.**

Context hygiene for every suite run: redirect output to files
(`> /tmp/frun_smoke/<name>.log 2>&1`), read back only summary lines
(`grep -E "^(Total|Passed|Failed|Skipped):"`) and failure context
(`grep -B1 -A3 "✗" | head -60`).

## 1. Baselines, both topologies

Boot default (UMA), then reboot with `numa=fake=4` (reboot required
between topologies). All suite runs from the repo root.

```bash
bash UNIT_TESTS/test_frun.sh
bash UNIT_TESTS/test_frun_comprehensive.sh
```

Expected counts: basic **89** (`test_frun.sh` verified 89/89 post-pull);
comprehensive **≈260 post-dedup** — record actuals rather than asserting
a number, and flag any FAIL with the test name.

Benchmarks from **inside** `BENCHMARKS/` (multi-GB temp files `f1`–`f4`
are git-ignored there; running elsewhere pollutes the tree):

```bash
cd BENCHMARKS
./run_benchmark.bash
```

Capture the trailing summary.

Spot-checks (documented `-L 100` transient watch):

```bash
for i in {1..10}; do seq 100 | frun --nodes=@2 -L 100 -k printf '%s\n' | wc -l; done
```

All 10 must print 100. If the documented `-L 100` transient
reproduces, it gets a Known Issues line, not a fix (frozen code).
`-L 100000` instability is already documented as observational
(GATE §13) — same treatment.

## 2. Sanitizer legs (per MAINTAINERS §5)

For each of `TESTING/TSAN` and `TESTING/ASAN+UBSAN`:

1. Checkout the testing branch, copy the final (frozen) `forkrun_ring.c`
   in, push, merge the CI PR, pull.
2. Apply the documented gotchas before running:
   - Remove `-c` from the cleanroom `exec` in `frun.bash`
     (`exec -c "${BASH:-bash}" ...` → `exec "${BASH:-bash}" ...`;
     otherwise sanitizer env vars are silently cleared).
   - TSan: `LD_PRELOAD=$(ldconfig -p | grep libtsan | awk 'NR==1{print $NF}')`
   - ASan/UBSan: `ASAN_OPTIONS=detect_leaks=0` plus the asan preload:
     `ASAN_OPTIONS=detect_leaks=0 LD_PRELOAD=$(ldconfig -p | grep libasan | awk 'NR==1{print $NF}') "${BASH:-bash}" ./test_frun.sh`
3. Run both suites at the branch's reduced sizes (sanitizer branches
   use smaller benchmark files by construction).

Scope note (MAINTAINERS §5): TSan observes races within a single
process only; forkrun's coordination is cross-process on shared
`MAP_ANONYMOUS`. Sanitizers validate intra-process threading and memory
hygiene; the cross-process ordering protocol is guaranteed by
INVARIANTS.md and exercised by the stress matrix.

## 3. aarch64 QEMU leg

Rebuild the shipped aarch64 blob path under `qemu-aarch64-static`,
then `test_frun.sh` (expect 89/89) + `SECTION=D`, `SECTION=L`,
`SECTION=T` + the targeted NUMA/`-L`/`-n`/resume probes.

Expected deltas vs. the last (stale) leg: M16 and R2/R10 now pass;
LA3/LA4/T14/F15a/F15b/F8 and the new Section-T battery run for the
first time on the leg. QEMU is functional-correctness only for the
fence pair (it does not model weak-memory reordering) — see GATE §7.

## 4. Twin checks

The PF-1 commands, locally (also green as CI job `twin-check`,
run 35174209682):

```bash
echo "frun twins in lockstep (pre-b64-marker region)"
cmp <(awk '/_BASE64_START_/{exit} {print}' frun.bash) \
    <(awk '/_BASE64_START_/{exit} {print}' ring_loadables/frun.nob64.bash)
echo "test twins byte-identical"
cmp UNIT_TESTS/test_frun_comprehensive.sh UNIT_TESTS/test_frun_comprehensive.sh.txt
```

Note: the sibling `sh-checker` (shellcheck/shfmt) job is red, but it
has been failing on `main` since July 2026 — pre-existing lint noise
across untouched files (BENCHMARKS, LEGACY, PaSh), with zero new
findings from the v3.5.1 work (differential shellcheck: SC2016 count
identical pre/post D10, findings only shifted with the insertion).
Not a release gate; do not fix under frozen code.

## 5. Reconciliation + tag

1. Record post-dedup counts (basic + comprehensive actuals per
   topology × baseline/TSan/ASan) and restate the test-count basis
   honestly in the GATE log — the old "~354 avg" basis changed with
   the W-G dedup; state the new basis rather than editing history.
2. Refresh the GATE "does NOT prove" appendix (§15): existing items
   hold (qemu≠silicon for the fences, one physical NUMA node,
   sanitizer scope, no TUI leg, THP sensitivity); W-E perf stays
   single-box/single-arch; D10's F6 closure is bash-5.3.9-verified
   plus POSIX-reasoned (already recorded in §15(b)).
3. Prepare a tag message summarizing the CHANGELOG and matrix counts.
4. **The owner executes the tag.** Any red anywhere: report to the
   owner before tagging.

Blob provenance for the tag message: release run 35173548966
(conclusion success) — VERIFY-OK all 7 arch keys, canary OK in
`fedora:latest` docker — merged as #534 (merge 7e5d014; x86-64 blobs
203912 → 208008 bytes). Stale #533 (pre-F28 blobs) and duplicate #535
closed. Post-pull smoke: `ring_version -a` v3.5.1, `frun -V` v3.5.1,
`test_frun.sh` 89/89, 10k-line sanity pipeline exact, local canary OK,
python unittests 14 OK.
