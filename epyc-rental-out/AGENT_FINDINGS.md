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
