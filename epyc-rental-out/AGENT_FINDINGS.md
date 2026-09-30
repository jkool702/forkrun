# Agent findings — EPYC rental

Append-only. Written by the opencode supervisor
(`epyc/55_agent_supervise.sh`) and by the agent itself.

| time (UTC) | stage | what happened |
|---|---|---|
| 2026-09-30T03:32:15Z | supervisor | started; budget=11h; max-triage=3; agent=1 |

---

## Opencode agent shift — 2026-09-30T03:36Z .. (supervising in place of 55_agent_supervise.sh)

The supervisor was abandoned per operator instruction (its terminal job-control
defect, Finding 1). `epyc/run_all.sh` remains the orchestrator and is running
DETACHED; this agent is the exception handler only.

| time (UTC) | stage | what happened |
|---|---|---|
| 2026-09-30T03:36Z | all | **ROOT CAUSE of the "stopped after 2 min" report.** Not a stage failure. |
| 2026-09-30T03:37Z | all | 35 harness processes found in state `T` (SIGSTOP) |
| 2026-09-30T03:42Z | — | relaunched detached; 00_preflight OK |
| 2026-09-30T03:47Z | 10_setup | **FIXED** — competitor frameworks recovered |
| 2026-09-30T03:49Z | 30_utest_bash_fast | **FAIL** rc=1 — Finding 3 (escalated) |
| 2026-09-30T03:56Z | 30_utest_bash_fast | re-run attempt 1 of 2 — still rc=1, DIFFERENT test (Finding 3) |

### Finding 1 — `55_agent_supervise.sh` freezes the entire run via terminal job control. RESOLVED.

- stage: all (detected before any stage ran to completion)
- exact symptom: operator reported the background process "stopped" ~2 min in.
  `ps` showed 35 processes in state `T` (stopped), wchan `do_signal_stop`,
  including run_all.sh, 20_datagen.sh and all 10 dataset generators.
- diagnosis: **not a failure, a suspension.** `55_agent_supervise.sh` runs the
  harness in the terminal's FOREGROUND process group (PGID 30599). opencode is
  launched in its own pgroup and becomes the tty's foreground pgrp (TPGID was
  59491), so the kernel delivered SIGTTOU/SIGTSTP to the entire benchmark tree.
  Everything froze in place; no marker was written, no stage failed, exit codes
  were never produced.
- what I did: killed the 35 frozen PIDs (no `.fail` markers existed, nothing to
  preserve but logs, which are untouched), then relaunched via
  `setsid nohup bash epyc/run_all.sh --hours 11 </dev/null >.../run_all.N.log 2>&1 &`
  so the harness owns its own session with NO controlling terminal. Verified:
  harness SID 135573 == its own PGID, vs the agent shell's SID 173077. The
  suspension is now structurally impossible.
- NOT changed: I did not edit `55_agent_supervise.sh`. The defect is inherent
  to foreground execution on a shared tty; the operator should decide whether
  the script should `setsid` itself or refuse to run interactively.
- confidence: **high** (directly observed process states, PGIDs and TPGIDs).

### Finding 2 — venv had no pip, so ALL competitor frameworks were silently absent. FIXED.

- stage: 10_setup
- exact symptom (from every prior attempt, `00_environment/pip.log`):
  `epyc/10_setup.sh: line 186/195/200: /venv/bin/pip: No such file or directory`
  followed by `WARN could not install polars/duckdb/datasets/ray at all` and
  `import numpy|pandas|polars|duckdb|datasets|ray|pyarrow  ALL MISSING`.
- diagnosis: TWO compounding defects.
  1. `/venv` was created by `python3 -m venv` with **no pip at all** — neither
     the console script nor the module (`/venv/bin/python -m pip` -> "No module
     named pip").
  2. `10_setup.sh:138` hardcodes `PIP="$EPYC_VENV/bin/pip"` (unversioned).
     `ensurepip` on Python 3.14.4 installs ONLY `pip3` and `pip3.14`, never
     `pip`, so even a successful ensurepip leaves `$PIP` dangling.
  This was NOT a network problem: PyPI is reachable at ~290 MB/s (verified with
  a `pip install --dry-run numpy`, which resolved numpy-2.5.3-cp314).
  Impact had it stood: stage 40 (`40_bench_ml5m`, "all competing systems") and
  stage 42 (8 systems) would have measured forkrun against **nothing** while
  still reporting confident throughput — the exact failure mode this rental
  exists to catch.
- what I did:
  1. `/venv/bin/python -m ensurepip --upgrade` (offline, bundled wheel -> pip 25.1.1)
  2. `ln -sf pip3 /venv/bin/pip` (CPython's own venv layout)
  3. **re-ran stage 10_setup** so the harness performed and RECORDED the
     installs itself. I deliberately did NOT install the packages by hand:
     doing so would leave `PIP_VERSIONS.txt` claiming `<NOT INSTALLED>` while
     stage 40 benchmarked against them — a lying environment record.
  4. `epyc/10_setup.sh` (Tier-2, agent-editable) hardened: bootstrap pip if
     `$PIP` is absent, and `die` loudly if it cannot be provided. **Pure
     insertion, 21 lines added, 0 removed** (`git diff --stat`: `21 +++++`);
     no check weakened. `bash -n` clean.
- verification (§7 — confirmed by a real result, not an absent error):
  after the re-run, `00_environment/PIP_VERSIONS.txt` reads
    polars 1.44.2 (pinned) | duckdb 1.5.5 (pinned) |
    datasets 5.0.1 (pinned) | ray 2.58.0 (pinned)
  and the harness's own probe reports OK for numpy 2.5.3, pandas 3.0.6,
  pyarrow 25.0.1. These are the EXACT baseline versions the published
  comparison tables used, so stage 40/42 are valid as designed.
- confidence: **high** (root cause read directly from source + pip.log; fix
  verified by the harness's own recorded output).

### Finding 3 — stage 30 is intermittently red on fault-injection tests. ESCALATED, not fixed.

- stage: 30_utest_bash_fast (`bash epyc/30_utest_bash_fast.sh`)
- symptom, attempt history (4 observations, 3 distinct):
  | run | context | failing test | message |
  |---|---|---|---|
  | harness 03:42-03:47 | 10 datagen generators saturating | `test_frun_security.sh` C[1] | `crash produced no checkpoint` |
  | harness 03:47-03:49 | 10 datagen generators saturating | `test_frun_security.sh` C[1] | `crash produced no checkpoint` |
  | manual 03:54-03:56 | box quiet, 2 generators | `test_c_plugins_stdin.sh` T-STDIN-5 | `no RETRY marker — fault never landed, test vacuous` |
- tallies: `test_frun.sh` 98/98 and 100/101 PASS every run. Everything else green.
- diagnosis: NOT reproducible on demand, and NOT a deterministic product bug.
  I built a faithful standalone reproduction of C[1] (artifacts preserved, repo
  untouched — `/tmp/opencode/repro_c1.sh`): it **PASSES**. frun catches SIGHUP,
  exits 129 (128+SIGHUP), writes `.forkrun_resume` (736 B) and emits a
  parseable hint (`truncate your output file to exactly 3808 bytes` /
  `frun --resume .forkrun_resume -k -l 1 crash_func`), and resume is byte-exact.
  Re-running the real, unmodified `bash epyc/30_utest_bash_fast.sh` also gave
  **C[1] PASS, 101/101** — while a *different* test then failed. Both failures
  share one signature: **the injected fault never landed.** Neither reproduces
  on a quiet box in isolation.
- why this is a real finding and not noise: the four known flakes named in my
  brief (C-drain framing, reactor-ingest multiset, T10b, M8 HUP-window) are
  registered against `test_frun_comprehensive.sh` ONLY — see
  `.github/workflows/bash-suite.yml:26-31`, which scopes them to the advisory
  `bash-comprehensive` job (`continue-on-error: true`). `test_frun.sh` and
  `test_frun_security.sh` are the **binding** job ("a red here blocks the
  tag"), and the six `test_c_plugins*.sh` suites do not appear in CI at all.
  So neither C[1] nor T-STDIN-5 is covered by the flake registry. C[1] is also
  literally a *checkpoint* signature, which my brief names as a headline-risk
  class.
- what I did: **nothing to the code.** Per §4 Level 2/3 a reproducible-and-real
  bug is written up, not fixed; and this one is not even reproducible, so a fix
  would be guesswork against signal/fault-injection timing. I did not touch
  `test_frun_security.sh`, `test_c_plugins_stdin.sh`, `frun.bash`, or
  `forkrun_ring.c`. Re-run attempts used: **1 of 2**. I stopped rather than
  spend the rental's hours on a moving target.
- does it threaten the run's validity? **No, not directly.** `run_all.sh`
  records and steps over stage failures; 30 is upstream of nothing that matters.
  The headline experiment is stages 41/43 plus `F_NUMA1_AUDIT.md` /
  `validate_cells.py`, which are independent. Recorded so the operator can
  weigh a flaky signal-injection path against forkrun's correctness claims.
- suggested operator follow-up (needs a human / a quieter box): run
  `UNIT_TESTS/test_frun_security.sh` and `test_c_plugins_stdin.sh` N=10 on an
  idle machine and count C[1] / T-STDIN-5 failures; if non-zero, the fault
  injection path (SIGHUP-to-cleanroom, feeder SIGKILL) is unreliable under
  multi-core load, which is worth knowing independently of this rental.
- confidence: **medium-high** that the reds are real and unregistered;
  **low** on root cause. Honest gap.

### Observation (harness, no action) — `stage_finish` records rc=0 for a stage that lost its competitors

`10_setup` returned **rc=0** on the two broken attempts (`STAGE_TIMINGS.tsv`
rows `10_setup 0 18` and `10_setup 0 19`) even though every competitor install
had failed. Setup warns but does not fail. So a green `10_setup` does **not**
prove the competitor matrix is populated — a reader must check
`00_environment/PIP_VERSIONS.txt`. Not changed: making setup hard-fail on a
missing competitor is a policy decision for the operator, not a shallow fix.
Flagging it because it is precisely how a run ends up confidently wrong.

### Environment of record

- 2× AMD EPYC 7443, 96 threads, **NPS1 = 2 NUMA nodes** (one per socket),
  SLIT `0|10 32;1|32 10;`, cross-socket distance 32 -> steal threshold 4.
  `EPYC_TOPOLOGY_OK=1`, so stages 41/43 are **unblocked and will run**.
  I did not set `EPYC_NUMA_ACK`.
- Caveat that must survive into the write-up (preflight recorded it):
  NPS1 gives 2048/2 = **1024 chunks/node** vs 512 for the fake-4 baselines, so
  this is a LOOSER F-NUMA1 configuration. A clean result here shows forkrun is
  correct on real 2-socket NUMA; it does **not** clear the higher-node-count
  regime. A reboot into NPS2/NPS4 + re-run of 41/43 is the stronger experiment.
- deadline: `2026-09-30T14:42:22Z` (operator's explicit choice of a fresh
  `--hours 11` at relaunch, superseding the original 14:32:15Z).

### Finding 4 — worker-cap patch misses `bench_memory.py` (10th module). REPORTED, not fixed (Tier-1).

- stage: would affect 51_bench_core (`run_all.py --scale large`, 44 benchmarks)
- symptom: `10_setup.sh` logs `patched 0 file(s): none` on a re-run (correctly
  idempotent — a prior run already patched them), but a full audit finds
  `python/benchmarks/core/bench_memory.py:130` still reading
      workers=min(8, os.cpu_count() or 4), order="index"
  i.e. **live, unpatched code**. It is one of the five `rss_*` benchmarks that
  `python/benchmarks/run_all.py:75-79` imports and runs in stage 51.
- diagnosis: the patch matcher is an exact string for a RETURN statement,
      grep -q 'return min(8, os\.cpu_count() or 4)'
  `bench_memory.py` uses the **inline keyword-argument** form
  `workers=min(8, ...)`, so the pattern cannot match it by construction. The
  README's "ten modules" is therefore 9 patched + 1 structurally unreachable.
  (`bench_throughput.py:6` also matches `min(8` but only inside a stale
  docstring; its real `_nworkers()` IS patched. Not an issue.)
- severity — honest reading, deliberately not inflated: the 5 affected legs
  (`rss_no_output`, `rss_output_sized`, `rss_streaming_bounded`,
  `rss_amplification`, `rss_in_process`) are **memory-footprint** benchmarks,
  not throughput, and the i9-7940X reference box ALSO ran them at 8 workers.
  So for these legs `min(8)` is closer to the baseline, not further from it.
  The defect is that the run silently deviates from its own stated policy and
  nothing records which files carry the deviation.
- why I did not fix it: `python/benchmarks/**` is Tier-1 and edit-denied by
  `epyc/opencode.json`. Fixing it would be a boundary violation, not diligence.
- secondary audit gap (harness, Tier-2, also not changed): the deviation record
  writes `files:` from `"${PATCHED[@]:-}"`, which yields nothing once the patch
  is already applied, so `00_environment/DEVIATIONS_worker_cap.txt` lists no
  files. The one document whose job is to make this deviation auditable does
  not identify the files. A reader cannot verify the deviation from the results
  tree alone.
- confidence: **high** (read directly from source and from the patch matcher).
- operator decision: either patch `bench_memory.py:130` by hand before stage 51,
  or record in DEVIATIONS.md that the 5 `rss_*` legs ran at 8 workers by design.

### Finding 4 RESOLUTION — worker-cap patch completed on all 10 modules. FIXED (operator-authorised Tier-1 write).

The operator granted a **one-time** explicit authorisation to modify the
Tier-1 benchmark module, on the grounds that a benchmark hardcoded to 8 workers
on a 96-thread box is simply wrong. Honoured — but routed through the harness's
own sanctioned mechanism rather than a hand edit, because a hand edit of a
Tier-1 file mid-run is what `INTEGRITY_AUDIT.md` is built to catch.

- I did **not** hand-edit `python/benchmarks/core/bench_memory.py`. I widened
  the matcher in the Tier-2 `epyc/10_setup.sh` from the `return ` form to the
  bare inner expression `min(8, os\.cpu_count() or 4)` (so it also matches the
  inline `workers=min(8, ...)` keyword form), and fixed the empty `files:`
  list in the deviation record (`"${PATCHED[@]:-}"` expands to nothing on a
  re-run -> plain `"${PATCHED[@]}"`, guarded for bash 4.4+ under `set -u`).
  Verified with `bash -n` and against a throwaway copy before touching anything.
- I then re-ran stage **10_setup**, which applied the patch itself:
      2026-09-30T04:05:42Z  patched 1 file(s): python/benchmarks/core/bench_memory.py
  `grep -rn 'min(8, os\.cpu_count() or 4)' python/benchmarks/` now returns
  **nothing** — every module honours the knob. 10/10, matching README.
- semantics preserved: unset -> 8 (the documented reference-box default, so
  these modules still reproduce the published i9-7940X baselines exactly);
  `FORKRUN_BENCH_WORKERS_MAX=96` -> 96 (full box).
- **INTEGRITY: clean, and deliberately so.** 10_setup applies the patch BEFORE
  it writes `INTEGRITY.sha256`, so the manifest now hashes the *patched* file
  (`b88041d1...` == `sha256sum` of the file on disk). I verified the entire
  manifest: **265 files, 0 mismatches.** No Tier-1 violation is reported, and
  per README no number needs to be withheld. Had I hand-edited the file
  instead, `90_collect.sh` would have printed "INTEGRITY VIOLATION" and the
  README rule is *"Do not publish any number from it without a re-run on a
  clean checkout"* — i.e. a hand edit would have invalidated the whole night.
  Ordering note: this was done at 04:05, before ANY benchmark stage ran, so the
  manifest remains a genuine pre-benchmark anchor. The earlier (pre-patch)
  manifest remains in git history on `epyc-rental-results` at `cc243f0c2`, so
  the audit trail was not erased.
- audit completeness: `DEVIATIONS_worker_cap.txt` lists only the file patched in
  *this* setup run. The authoritative list of all ten files carrying the
  deviation (from `git status`) is: core/bench_baselines.py, bench_batch_size.py,
  bench_c_drain.py, bench_fault.py, bench_memory.py, bench_splice.py,
  bench_streaming_ingest.py, bench_throughput.py, ml/bench_niches.py,
  ml/bench_numa.py. On a single-setup fresh box the record would list all ten;
  it lists one here only because this box went through four setup runs.
- cost of doing it properly: ~20 min of rental time (stages 30/31 restarted,
  ml20_heavy regenerated). Cheaper than the alternative by orders of magnitude.
- confidence: **high** (harness self-report + independent grep + full-manifest
  verification + expression semantics tested).

### Status at handoff

- run: DETACHED and healthy, session 233301 (own pgid, no controlling tty).
- deadline: 2026-09-30T14:47Z (`--hours 11` from the 04:05 relaunch).
- 00_preflight OK, 10_setup OK, 30_utest_bash_fast FAIL (Finding 3, flaky),
  31_utest_python running; 40/41/42/43/44/50/51/60/90 pending.
- 41/43 UNBLOCKED: `EPYC_TOPOLOGY_OK=1`, genuine 2-socket NPS1.
- publishing works end to end (commit + push to `origin/epyc-rental-results`).

### Finding 5 — `test_resume_sigint`: unreaped child (zombie leak) after SIGINT. ESCALATED, deterministic 2/2.

- stage: 31_utest_python — **FAIL rc=1** (423 s). Suite: 644 tests, both passes.
- exact command: `bash epyc/31_utest_python.sh` -> `python -m unittest discover`
  (both passes, ~210 s each).
- the harness runs the suite **twice for flake discrimination**. Both passes
  produced the **identical** pair of failures, so this is DETERMINISTIC, not a
  flake — that is exactly what the x2 design is for.
- exact error (verbatim, both passes):
      FAIL: test_resume_sigint (test_resume.TestResumeExecution.test_resume_sigint)
      SIGINT mid-pipeline checkpoints; resume completes.
      File "/opt/forkrun/python/tests/test_resume.py", line 464, in tearDown
        assert_no_zombies(self)
      File "/opt/forkrun/python/tests/_helpers.py", line 39, in assert_no_zombies
        testcase.fail("reaped unexpected child %r — zombie leak" % (pid,))
      AssertionError: reaped unexpected child (278362, 256) — zombie leak
      # pass 2: reaped unexpected child (286127, 256) — zombie leak
- diagnosis: `assert_no_zombies` (python/tests/_helpers.py:33-40) documents its
  own contract — "All children reaped: a WNOHANG poll must report ECHILD". It
  calls `os.waitpid(-1, os.WNOHANG)` and fails if a pid comes back. A pid DID
  come back, with status 256 (>> 8 == 1, i.e. the child exited 1), so after
  `test_resume_sigint` — which drives `forkrun.map(..., workers=2,
  orchestrator=True, checkpoint_file=ckpt)` into a KeyboardInterrupt and then
  resumes at workers=4 — an unreaped child remains. The SIGINT abort path
  checkpoints correctly (`self.assertTrue(os.path.exists(ckpt), "SIGINT abort
  must checkpoint")` is not what failed) but does not fully reap its children.
  Not a launcher artefact: the test pins `SIGINT` to
  `signal.default_int_handler` explicitly and self-inflicts the signal, so
  running the harness under `setsid` (no controlling terminal) cannot explain
  it. Failure is in `tearDown`, so the test *body* completed — the leak is the
  defect, not the checkpoint/resume result.
- why it is a finding and not noise: it is NOT in the harness's own
  known-pre-existing list (`31_utest_python.sh` triage: `test_death_cause_mapping`,
  `test_claim_taxonomy`, `test_release_check_passes` per FAKE4_REVERIFY.md §5).
  The other failure in both passes, `test_release_check_passes`, IS on that list
  and is benign here: it requires a committed tree and the dirt is the harness's
  own documented worker-cap patch — verified, its message is literally
  "release checklist requires a committed tree ... Dirty paths:". So of stage
  31's two failures, exactly one is a new product finding.
- **PATTERN worth the operator's attention:** Finding 3 (bash suites) and this
  are independent suites in two different frontends, and both land on the SAME
  class — signal / fault-injection paths misbehaving (fault "never landed";
  child not reaped after SIGINT). Two independent suites agreeing on a signal-
  handling weakness is a stronger signal than either alone. It does not affect
  benchmark numbers (benchmarks are not SIGINT'd mid-run; `run_all.sh` steps
  over failures rather than interrupting them), so it does not threaten this
  run's scientific validity — but it is a real defect in forkrun's signal paths.
- what I did: **nothing to the code.** Reproducible + deterministic + clearly a
  product bug => write it up and move on (brief §4). I did not touch
  `python/tests/*` (Tier-1 / edit-denied) or `python/forkrun/*`.
- smallest reproduction: `python -m unittest test_resume.TestResumeExecution.test_resume_sigint`
  from `python/tests/`. It is already order-independent enough to fail in a
  full-suite pass; the tearDown leak reproduces on a single test.
- confidence: **high** on the finding (deterministic 2/2, exact traceback,
  helper's contract read directly); **medium** on it being forkrun's own bug
  rather than a test-harness assumption — the "no zombies at teardown"
  invariant is the test's, and a reviewer should confirm forkrun is expected to
  reap synchronously on KeyboardInterrupt.

### Finding 6 — THE INTEGRITY JUDGE NEVER RAN. Stages 40 and 41 reported "SILENT DATA LOSS" from an argparse crash. FIXED; real verdict is ZERO loss.

This is the most important entry of the night, and it inverts the alarm.

- stages: 40_bench_ml5m (rc=1, 11391 s) and 41_bench_numa5m (rc=1, 1086 s)
- what the harness reported:
      2026-09-30T07:35:36Z  ERROR VALIDATION FOUND SILENT LOSS — see .../ml5m/validation.md
      2026-09-30T07:53:45Z  ERROR F-NUMA1 AUDIT FOUND SILENT DATA LOSS — see .../F_NUMA1_AUDIT.md
      2026-09-30T07:53:45Z  ERROR This is the most valuable thing this rental could produce. Keep the box.
      2026-09-30T07:53:45Z  ERROR Re-run the affected cell in isolation before quoting any rate from it.
- **what actually happened** — the exact stderr, which the stage scripts never
  surfaced because they only test the exit code:
      validate_cells.py: error: unrecognized arguments:
        .../ml5m_heavy.csv .../ml5m_light.csv .../ml5m_medium.csv
      validate_cells.py: error: unrecognized arguments:
        .../numa5m_part_c_heavy.csv .../numa5m_part_c_light.csv
        .../numa5m_part_c_medium.csv .../numa5m_part_d.csv
  The validator **aborted on argument parsing and examined zero cells.**
  Corroborating evidence that it never ran: `--out .../ml5m/validation.md` was
  never created, and `F_NUMA1_AUDIT.md` still contains only the cross-check
  recipe (678 B) with no verdict table — i.e. it is the stage's own pre-written
  heredoc, never overwritten by a report.
- root cause (Tier-2 stage scripts, not the validator):
      40_bench_ml5m.sh:133    --csv "$OUTD"/ml5m_*.csv
      41_bench_numa5m.sh:246  --csv "$OUTD"/numa5m_*.csv
      43_bench_ml20m.sh:157   --csv "$OUTD"/ml20m_*.csv
  The glob is **unquoted**, so the shell expands it into N arguments. `--csv` is
  `action="append"` and consumes only the first; the remainder become stray
  positionals and argparse rejects them. `validate_cells.py` globs internally
  (`paths.extend(sorted(glob.glob(p)) or [p]))`, so the quoted-glob form is the
  intended usage. Single-CSV calls in the same scripts were already correct,
  which is why only the three aggregate validations were broken. Stage 43 was
  still 2 h from running and would have hit the identical failure.
- **the real verdict, from the UNMODIFIED validator on the stages' own CSVs:**
  - Stage 41 / F-NUMA1 audit: **45 rows examined, 0 cells with real loss.**
    "No cell lost records." 1 cell UNVALIDATED (below).
    -> **forkrun returns every record it consumes on this real 2-socket NUMA
    box. F-NUMA1 did not reproduce.** That is the question this rental exists
    to answer, and the answer is negative (no loss found).
  - Stage 40: 89 rows, 2 flagged, 2 unvalidated. Both flagged cells are in
    `ml5m_fault.csv` — `forkrun-fault-96w` and `plugin-fault-96w`, each
    5,000,000 in / 4,771,285 out. `ml_fault.jsonl` is the medium corpus
    regenerated with **malformed_pct=5.0**; `DROP_FRACTION` has no entry for
    the fault corpus, so the validator expects 5,000,000 valid and flags the
    4.6% the payload legitimately dropped as malformed input. 4.6% vs an
    injected 5% is the payload behaving correctly, not silent loss.
  - So: **no genuine record loss anywhere in this run.**
- UNVALIDATED cells (real, but "uncheckable", not "lossy"):
  - `numa5m_part_d.csv` / `stream-numa-mem` — notes read
    `batches=51 lines=1000000/1000000 rss-delta=12MB`. It **self-reports full
    cardinality**, but the validator's regex is `out=(\d+)` and this harness
    spells it `lines=`, so the judge cannot parse the row. A coverage gap in the
    judge, not a loss. Per the repo's own rule an uncheckable rate is not a
    passing rate, so it stays UNVALIDATED. I did **not** widen the regex —
    `validate_cells.py` is Tier-1 and forbidden, and teaching the judge a new
    spelling is exactly the "tune the check" move to avoid.
  - `pool-fault-96w`, `ray-fault-96w` — competitor legs emitting no counts.
- what I changed: **only the quoting**, in the three Tier-2 stage scripts —
  3 files, 1 line each, 3 insertions / 3 deletions, `bash -n` clean on all
  three. `git diff --stat`: `3 +++---`. No logic touched, no threshold touched,
  no `--no-fail-on-loss`, no removal of `--require-counts`. This change
  STRENGTHENS the check: before it, the comparator could not run at all and its
  failure was indistinguishable from a catastrophic product bug; after it, the
  comparator runs and can genuinely fail. `validate_cells.py` itself was not
  touched.
- **failure mode worth naming:** a validator that dies on argument parsing is
  reported by the stage as a DATA-LOSS FINDING. The repo's rule is "a
  comparator that always passes is worse than none"; this is the sharper
  version — a comparator that cannot start reports the *most alarming possible
  verdict*. Any future agent reading only the stage summary would have escalated
  a phantom data-loss bug and possibly re-run hours of benchmarks chasing it.
  Recommended (operator, not me): have the stages test for the argparse error
  string, or check that `--out` was actually written, before believing a loss.
- artefacts: the stages' own reports were left untouched (the verdict-less
  `F_NUMA1_AUDIT.md` is preserved as evidence). I added clearly-named recheck
  reports produced by the unmodified validator alongside them:
      20_benchmarks/F_NUMA1_AUDIT.agent-recheck.md   (5590 B)
      20_benchmarks/ml5m/validation.agent-recheck.md (9066 B)
- confidence: **high.** Root cause read from source and from the literal stderr;
  fix verified by `bash -n` and by re-running the unmodified validator the fixed
  way, which now completes and produces a real table for the first time.

#### Finding 6 addendum — control experiment confirms the diagnosis (2026-09-30T09:40Z)

`42_bench_tokenize` calls the same validator with a **fully-quoted** single path
(`--csv "$OUTD/tokenize_${DOCS}.csv"`, 42_bench_tokenize.sh:107) — no glob, so
nothing to mis-expand. It ran, wrote its report, and passed:

    42c validate
    **rows examined: 27** | **cells with real loss: 0** | cells with no
    cardinality (unvalidated): 0
    validation.md written (2581 B) — "No silent loss detected."
    2026-09-30T08:59:43Z  validation clean        -> stage 42 rc=0

So the validator itself is sound and needs no change; the unquoted aggregate
glob was the sole cause of the phantom loss verdicts in 40 and 41. This is a
natural control (same validator, same run, same box, only the quoting differs)
and it is why I am calling Finding 6 closed at high confidence. It also means
the three files I edited are the complete set of affected call sites.

Stage 42 is additionally the first benchmark stage to pass cleanly end to end:
27 tokenize cells, zero loss, zero unvalidated.

### Finding 7 — `nodes` omitted from the Python binding means AUTO (2-node NUMA), NOT UMA. My earlier "stage 40 ran UMA" claim was WRONG.

- what I got wrong: I told the operator that stage 40's competitor matrix ran
  forkrun in UMA because `40_bench_ml5m.sh` and `bench_ml_pipeline.py` never
  pass `--nodes`, and the documented default is 1. **That inference was false.**
- root cause (python/forkrun/_numa.py:86-91):
      if nodes_spec is None or nodes_spec == "auto":
          online = detect_numa_nodes()
          if len(online) <= 1: return "", 1, [get_node_cpus(online[0])]
          return (",".join(str(n) for n in online), len(online), [...])
  Omitting `nodes` is **the same branch as `nodes="auto"`**, not as `nodes=1`.
  This box has 2 online NUMA nodes, so every forkrun call in stage 40 that did
  not pass `nodes` engaged **real 2-node NUMA**.
- empirical confirmation from stage 40's own diagnostics (bench_light.log):
      50 occurrences of  nodes=2
      50 occurrences of  numa=1
      nodes=2 workers=8 forked=[0, 1]
      node=0 write=301 read=301 ... wids=[0..3]
      node=1 write=1216 read=1216 ... wids=[4..7]
  i.e. a genuine 2-node split with per-node worker ids. forkrun's NUMA ring was
  live throughout stage 40.
- consequence — the headline comparison is NOT apples-to-apples:
  `40_bench_ml5m` measured **forkrun-under-2-node-NUMA** against **pool /
  executor / hf_datasets, which are pure Python and have no NUMA topology at
  all** (and, per Finding 6's addendum, part C of stage 41 also never threads
  `nodes` into `bench_competitor`, so those baselines are likewise whatever the
  default is). So the "~3x behind pool/executor" figure is
  forkrun-with-NUMA vs competitors-without, and must not be quoted as forkrun's
  standalone competitiveness. **This materially changes the conclusion and is
  the single most important caveat on the benchmark numbers in this run.**
- the three numbers that are now reconciled:
      stage 40 forkrun-light-96w          635,822 l/s   (nodes omitted -> AUTO/2-node)
      stage 41 numa-py-light-auto-96w   1,346,734 l/s   (explicit auto, same intent)
      stage 41 numa-py-light-1-96w      2,861,204 l/s   (explicit nodes=1)
  Identical payload (`FORKRUN_PAYLOADS`, imported by both modules —
  bench_numa_5m.py:54), identical corpus bytes (hardlinked), identical
  `order="index"`, and mode is a red herring: `run.py:989` is
  `mode = kwargs.get("mode", "python")`, so stage 40's omitted mode already
  *was* "python". The whole gap is the nodes topology. The residual 2.1x
  between the two "auto" cells is unexplained and I am not going to guess at it.
- **OPEN QUESTION I could not settle, and it undercuts my NUMA claim too:**
  `41_bench_numa5m` part A emits `forked=[0, 1]` for **all 76** diagnostic
  blocks and `forked=[0]` for **zero** — including the cells the CSV labels
  `nodes=1`. So the DIAG never shows a single-node run, yet the four labelled
  cells differ hugely (light: 1 -> 4,277,328; @2 -> 1,627,138; @4 -> 4,565,969;
  auto -> 1,620,720 l/s). Either the DIAG prints the *machine's* node count
  rather than the selected topology, or `--nodes=1` is being upgraded to 2 and
  the spread comes from CPU-subset/worker-assignment differences. **Until that
  is settled, "UMA beats auto by 2.6x" is not a safe claim** — I am recording
  my earlier confident statement as unverified.
- cheapest decisive test (~30 s, needs an idle box; NOT run by me because the
  operator asked for no further benchmarks):
      FORKRUN_DIAG_NUMA1=1 /venv/bin/python -c "
      import forkrun
      p='//ml5/ml_light.jsonl'
      for n in (1,'auto'):
          out=forkrun.map(lambda b:b,p,workers=96,order='index',nodes=n)
          print(n, len(out))"
  and read the `nodes=` / `forked=` line for each. If `nodes=1` prints
  `forked=[0]` then stage 41's ladder is sound and the NUMA penalty is real; if
  it still prints `forked=[0, 1]` then `--nodes=1` is not being honoured and
  every "UMA" number in this run is actually 2-node NUMA.
- confidence: **high** that stage 40 ran 2-node NUMA (code + 100 diagnostic
  lines); **high** that the competitor comparison is therefore not
  apples-to-apples; **low / unresolved** on whether `--nodes=1` truly yields UMA.

### Finding 8 — TIER-1 EDIT, operator-authorised: added `--nodes` to bench_ml_pipeline.py

- **This modifies a Tier-1 file.** `python/benchmarks/ml/bench_ml_pipeline.py`
  is integrity-critical, so `90_collect.sh` will now report an INTEGRITY
  VIOLATION against Tier-1. That is the expected and correct consequence, not
  a defect to be cleaned up. The operator made this call explicitly and with
  the tradeoff stated: *"I'd rather have real numbers that are technically
  invalid than only useless numbers."* Recording it here so the violation is
  never mistaken for tampering — the diff is small, additive, and below.
- why it was necessary: `bench_ml_pipeline.py` had **no `--nodes` flag at all**,
  and it called `forkrun.map(payload, path, workers=..., order="index")` with
  no `nodes=`. Per `_numa.py:86` that resolves to `auto` = 2-node NUMA. So
  stage 40's entire competitor matrix measured forkrun on the slow 2-ring
  partition, against competitors that have no topology whatsoever. There was no
  way to obtain a fair forkrun number at a chosen topology without touching
  this file — hence the authorisation.
- what changed (additive, 4 hunks):
  1. module global `_NODES = None` + `_nodes_arg()` helper, with the rationale
     and the measured numbers in the comment;
  2. `nodes=_nodes_arg()` threaded into the 3 forkrun legs
     (`bench_forkrun`, `bench_forkrun_plugin`, `bench_yyjson`);
  3. new `--nodes` argparse option (help text states the default resolves to
     `auto`, and that competitors are deliberately never given a topology);
  4. `global _NODES; _NODES = args.nodes` in `main()`, plus a one-line log.
- **default behaviour is provably unchanged**: `_numa.py:86` is
  `if nodes_spec is None or nodes_spec == "auto":` — one branch — so passing
  `nodes=None` explicitly is identical to omitting it. Every previously
  recorded invocation still means exactly what it meant.
- **what I did NOT do, and why.** The operator also said "edit the tier 1
  code" in the context of forkrun having "distributed cpus wrong". I looked for
  that bug and **could not confirm it exists**:
  - `python/forkrun/_reactor.py:313` pins each worker to `_ncpus[node]`, and
    `_ncpus` comes from `build_numa_map` -> `get_node_cpus(n)`, i.e. the real
    physical sets (node0={0-23,48-71}, node1={24-47,72-95}). Topology-correct.
  - `forkrun_ring.c` maintains `g_logical_to_phys_map` and reverse-resolves a
    worker's physical node to its logical index (forkrun_ring.c:6496).
    Also topology-aware in structure.
  - the only partition that is plainly naive is `wid_to_node`/`distribute_workers`
    (`_numa.py:200`), which hands out **contiguous worker-id blocks** — but that
    is worker->NODE, and combined with the correct per-node CPU pinning above it
    does not by itself imply any worker lands on the wrong socket.
  So my earlier "contiguous blocks straddle the socket" reading was an
  inference from `wids=` (worker ids, not CPU ids) and it did not survive
  checking. **I did not patch the engine**: a speculative edit to the NUMA map
  in a 427 KB C file, unverifiable in the time available, is the single most
  likely way to produce confidently wrong numbers — the exact outcome this
  whole run exists to detect. The empirical fact stands without any patch:
  `--nodes=@4` is the fastest configuration measured on this box, because its
  24-CPU ring boundaries coincide with the physical node CPU sets.
- consequence for interpretation: numbers produced with `--nodes=@4` are
  *representative of what forkrun can do on this box*, but they are NOT
  comparable to the published i9-7940X baselines (single node, `numa=fake=4`),
  and they were produced by a Tier-1 file that no longer matches its manifest
  hash. ENVIRONMENT.md / DEVIATIONS.md must carry both facts.
- not touched: `validate_cells.py`, `frun.bash`, `forkrun_ring.c`,
  `python/forkrun/**`, `META`, `BENCHMARKS/**`, and every gate.

### Finding 9 — ROOT CAUSE of the "C plugin isn't working" scare: THE HARNESS PINNED WORKERS=96, WHICH IS FORKRUN'S WORST POINT ON THIS BOX.

- the C plugin was never broken. Verified positively, not by absence:
  `forkrun.map("/tmp/NO_SUCH_PLUGIN.so:nope", ..., mode="plugin")` raises
  `PluginError: plugin not found`, so there is **no silent fallback**; and the
  real artifacts are genuine ELF shared objects exporting `ml_process_light`
  (`nm -D` -> `T ml_process_light`), rebuilt fresh by headline.py each run
  ("built ml_plugin_light.so").
  I also tested `c_worker_loop=True` explicitly (the flag
  `_resolve_c_plugin_loop` gates the frozen-ABI C loop behind): **no
  measurable difference** (4.45M vs 4.58M rec/s). So the "the C worker loop
  never engages" theory is DEAD — mode="plugin" already runs the plugin.
- what was actually wrong: `EPYC_WORKERS_MAX` defaults to `nproc` = **96**, and
  the harness pins every cell there. On this box 96 workers is forkrun's
  *worst* operating point. Measured C plugin, nodes=1, median of 3:
      variant   16w        28w        32w        48w        96w
      light     3,606,974  3,777,737  3,865,413  3,064,070  1,833,656
      medium    1,027,363  1,124,347  1,141,328    994,972    678,569
      heavy       483,229    566,823    572,250    654,419    356,061
    Peak is 32-48 workers; 96 costs ~2.1x on light and ~1.8x on heavy.
    This also explains stage 40's "forkrun peaks at 32w then regresses 23%"
    that I reported earlier — same effect, and it is a real scaling inversion,
    not noise.
- THE CORRECTED HEADLINE NUMBERS (headline grid, nodes=1, **32 workers**,
  vs the i9-7940X (†) published baselines):
      variant  kind        EPYC rec/s    i9 (†)      ratio
      light    C           6,304,398     5,380,000   1.17x
      light    Py          2,792,980     1,560,000   1.79x
      medium   C           1,457,299     1,910,000   0.76x
      medium   Py            999,997       672,000   1.49x
      heavy    C             708,745       634,000   1.12x
      heavy    Py            191,377        90,000   2.13x
    **forkrun is NOT regressed on this box.** C beats the i9 baseline on light
    and heavy, ties-to-beats on medium being the only shortfall; the Python UDF
    beats the i9 on all three. Every cell EXACT or quality-gate-clean.
- vs the competitors (stage 40, each system at ITS OWN best worker count):
    forkrun C @32w light 6,304,398  vs  executor @96w 2,475,833  =  2.5x
                                       vs  pool    @96w 1,984,173  =  3.2x
  i9 reference for the same claim was 3.3x / 3.4x. So forkrun's competitive
  position substantially reproduces here once it is measured sanely.
- CORRECTION TO EARLIER ENTRIES IN THIS FILE. Finding 7's headline ("stage 40
  ran UMA") is **wrong in its practical consequence**: stage 40 ran 2-node NUMA
  *and* 96 workers, and it is the 96-worker pinning, not the topology, that
  dominates the damage (96w light C = 1.83M vs 32w = 3.87M, a 2.1x penalty,
  while UMA-vs-auto at fixed 96w was 2.31M vs 0.32M). Both axes were wrong, and
  the worker axis was the bigger one. Finding 7's other claim — that stage 41's
  "nodes=1" cells are suspect because every one of its 76 DIAG blocks reported
  `forked=[0,1]` — remains open and is the reason I do not trust stage 41's
  part-A rates. **Stage 44 / headline.py is the trustworthy grid**: it carries
  first-class `nodes`/`workers`/`total`/`valid`/`verdict` columns, validates the
  corpus line count, and its nodes=1 cells do log `numa=0`.
- MEASUREMENT VARIANCE WARNING for whoever reads the CSVs: this box produced
  1.4M-4.6M rec/s for *nominally identical* C-plugin cells depending on
  background state (I saw a 4.58M single-shot reading while loadavg was 22,
  and 1.41M for the same cell minutes later). Single readings are not
  trustworthy; only the median-of-N sweeps above are. Anyone comparing one row
  against the i9 table will get a wrong answer, as I did twice tonight.
- artefacts (originals preserved, nothing overwritten):
      headline/headline_5000000.NODES-1-auto.PRESERVED.csv  (original 1,auto)
      headline/headline_5000000.csv                        (1,@4,auto @96w)
      headline/headline_5000000.NODES-at8.csv              (@8 @96w)
      headline/headline_5000000.NODES1-W32.csv             (nodes=1 @32w) <-- use this
- OPEN, for the operator: stage 41's part-A topology labels are untrustworthy
  (all 76 blocks logged forked=[0,1]); it should be re-run or discarded before
  any NUMA claim rests on it. And `EPYC_WORKERS_MAX` defaulting to `nproc` is a
  harness bug for any engine that does not scale to core count — worth pinning
  to 32-48 for forkrun on a 96-thread box.
