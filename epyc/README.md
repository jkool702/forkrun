# epyc/ — real-NUMA validation harness for forkrun

Pre-scripted, resumable, deadline-aware runner for a rented bare-metal
2× AMD EPYC box. Installs and verifies forkrun (bash + Python frontends),
generates every benchmark input, runs every unit-test suite, and re-runs every
benchmark in the repo — bash side and Python side, including the competing
frameworks.

Built for the question `RELEASE_v3.6.0.md` §6 leaves open:

> *"Real multi-socket hardware (where born-local placement pays) remains
> unmeasured — the standing prediction is NUMA at parity-or-better there,
> unproven."*

---

## Quick start

**1. Stage the checkout on the rental** (from your lab machine):

```bash
rsync -a --delete --exclude '.git' anthony@<lab>:/mnt/ramdisk/forkrun/ root@<rental>:/opt/forkrun/
```

**2. Run everything** — pick one:

```bash
# unattended: the harness alone, resumable, deadline-aware
nohup bash epyc/run_all.sh --hours 12 > /var/log/epyc.log 2>&1 &

# overnight: an opencode agent supervises and self-triages stage failures
nohup bash epyc/55_agent_supervise.sh --hours 12 > /var/log/epyc-agent.log 2>&1 &
```

**3. Collect:**

```bash
rsync -avz root@<rental>:/opt/forkrun/epyc-rental-out ./epyc-results
```

`--hours 12` is a soft wall-clock cut-off. Stages are ordered most-valuable-first,
and a stage is **skipped with a recorded reason** rather than started when its
estimate exceeds the remaining budget. The run is resumable: re-running picks up
at the first stage without a `.done` marker.

---

## The agent supervisor (`55_agent_supervise.sh`)

`run_all.sh` stays the orchestrator. The supervisor does **not** reimplement its
ordering, deadline logic or resume behaviour — it runs it, and consults an
opencode instance **only when a stage fails**. The agent is the exception handler,
never the sequencer.

```bash
bash epyc/55_agent_supervise.sh --hours 12       # overnight, self-triage
bash epyc/55_agent_supervise.sh --hours 12 --no-agent
bash epyc/55_agent_supervise.sh --hours 12 --max-triage 5
```

* One session is opened on the first triage and **continued** for the rest of
  the night, so the agent remembers what it already tried instead of
  rediscovering the same dead end every twenty minutes.
* Budget: `--max-triage N` total consultations (default 3), and at most one fix
  attempt per stage. The caps exist because a 6-hour retry loop on a metered
  rental is the single most expensive failure mode available.
* Degrades safely. No opencode, no auth, or a model that is not in the catalogue
  → it runs the harness unattended and says so.

### Three independent layers of authority

The risk is not that the agent is incompetent; it is that a well-meaning agent
"fixes" a failure by weakening the very check that would have caught the headline
finding. So the boundary is declared in three places, and **one of them can fail
without corrupting the experiment**:

| layer | file | what it does |
|---|---|---|
| 1. Instruction | `epyc/AGENT_PROMPT.md` | the operating brief: mission, authority, a 3-level decision procedure, stop conditions, and budget discipline |
| 2. Mechanism | `epyc/opencode.json` | opencode permission rules: `edit` denied on the validator, the product, `python/benchmarks/**` and the stage markers; `bash` denied for `rm` on evidence, `git push/reset/checkout`, and all network tools; `external_directory: deny` |
| 3. Evidence | `epyc/INTEGRITY.sha256` → `INTEGRITY_AUDIT.md` | SHA-256 of every integrity-critical file, written by `10_setup.sh` and re-verified by `90_collect.sh` |

Layer 3 is the one that actually holds. `90_collect.sh` writes
`INTEGRITY_AUDIT.md` with one of two verdicts:

* **"the run measured unmodified forkrun"** — quote the numbers.
* **"INTEGRITY VIOLATION"** — a Tier-1 or Tier-3 file changed during the run.
  **Do not publish any number from it** without a re-run on a clean checkout.

Tier 2 (the harness's own stage scripts) is deliberately *editable* — a bug in
the harness is exactly the shallow problem the agent should fix — but any change
is listed separately, so "the agent modified the harness" is visible without
invalidating the measurements.

Verified behaviours of layer 3: widening `LOSS_TOLERANCE` in the validator,
deleting a Tier-1 file, and rewriting `opencode.json` to grant itself write
access are each detected and reported.

### The agent's authority, in one line

It may fix a missing package, rebuild a wiped substrate, re-run a stage, and
edit its own harness. It may **not** touch the validator, the product, the
benchmark sources, the stage markers, the evidence, or any gate — and it may not
set `EPYC_NUMA_ACK`. A finding is a successful outcome; a green log obtained by
relaxing a check is a failed run.

### Model

Defaults to `opencode/space-bunny-free`, the only space/bunny model in the
current catalogue — there is no `space-bunny-alpha-max` in `opencode models`.
`10_setup.sh` verifies the model actually exists before the run starts, so a
catalogue change is caught in setup rather than at the first triage.
Override with `EPYC_AGENT_MODEL=opencode/<id>`, or skip the agent entirely with
`EPYC_SKIP_AGENT=1`.

Authentication is the one thing that must be done interactively, once:

```bash
opencode auth login
```

Without it the harness still runs; it just will not self-triage.

### Useful variations

```bash
bash epyc/run_all.sh --list                        # stages in execution order
bash epyc/run_all.sh --only 41_bench_numa5m       # just the real-NUMA study
bash epyc/run_all.sh --from 40_bench_ml5m         # resume from here
bash epyc/run_all.sh --skip 60_utest_bash_full    # drop the 2-hour suite
bash epyc/run_all.sh --hours 12                    # or --hours 0.75, --minutes 45
bash epyc/run_all.sh --deadline 2026-09-30T18:00:00Z
EPYC_NUMA_ACK=1 bash epyc/run_all.sh --hours 12    # accept an unexpected NUMA topology
```

### Pre-flight check before you pay for anything

`00_preflight.sh` runs first and **aborts** on a fake topology, a hypervisor, a
throttled cgroup, glibc < 2.38, or bash < 4.4. Run it standalone and read the
transcript before committing rental hours:

```bash
bash epyc/00_preflight.sh
# -> epyc-rental-out/00_environment/PREFLIGHT.txt
```

It also tells you whether the box booted with the 8 NUMA nodes you expect, and
warns (without aborting) if it did not.

---

## Stages

| # | stage | what it does | est |
|---|---|---|---|
| 00 | `00_preflight` | topology/NUMA/THP/toolchain detection, go-no-go gates, writes `env/epyc.env` | 2 m |
| 10 | `10_setup` | apt, THP=`always`, `numa_balancing=0`, venv, pinned competitors, build substrate, verify **both** frontends end-to-end | 20 m |
| — | `20_datagen` | **runs in the background** under the test stages: 5M + 20M ML corpora, 2M-doc tokenize corpus, stage0 inputs, bash benchmark inputs, sha256 manifest | 40 m |
| 30 | `30_utest_bash_fast` | `test_frun.sh`, `test_frun_security.sh`, all 6 C-plugin suites | 20 m |
| 31 | `31_utest_python` | 644-test Python suite **×2** (flake discrimination) + IDL/shim freshness | 15 m |
| 40 | `40_bench_ml5m` | **AI/ML @ 5M — all competing systems** (Pool, Executor, HF Datasets, Ray, Polars, DuckDB, serial) | 2.5–3.5 h |
| 41 | `41_bench_numa5m` | **the real-NUMA experiment**: `nodes=1,@2,@4,auto` × worker sweep + F-NUMA1 audit | 45 m |
| 42 | `42_bench_tokenize` | LLM tokenize @ 2M docs, 8 systems | 2.5–3.5 h |
| 43 | `43_bench_ml20m` | AI/ML @ 20M, forkrun only, + F-NUMA1 audit at 8 nodes | 1.5–2.5 h |
| 44 | `44_bench_headline` | (†)/(max) pinned grid, cell-for-cell vs `headline_2026-09-29.csv` | 20 m |
| 50 | `50_bench_bash` | `run_benchmark.bash` + GNU Parallel + xargs baselines + 9 targeted sweeps | 1.5 h |
| 51 | `51_bench_core` | `run_all.py --scale large` (10M lines, median of 5) | 30 m |
| 60 | `60_utest_bash_full` | `test_frun_comprehensive.sh` — 264 tests, un-timeboxed | 1–1.5 h |
| 90 | `90_collect` | `ENVIRONMENT.md`, `DEVIATIONS.md`, `RUN_REPORT.txt`, sha256 manifest | 5 m |

Ordering rationale: **41 and 43 can only ever be measured on this box**, so they
go first. 50 and 51 reproduce artifacts that already exist for the i9-7940X, so
they are the right things to sacrifice when the clock wins. 60 is the longest
and least performance-critical, so it goes last — and doubles as a
"the box was still healthy at hour N" signal.

---

## Results you get

```
epyc-rental-out/
├── ENVIRONMENT.md              every version, knob and topology fact
├── DEVIATIONS.md               the 10 axes that differ from every published number
├── INTEGRITY_AUDIT.md          ★ did anything the agent was forbidden to touch change?
├── INTEGRITY.sha256            the manifest itself, written at setup
├── RUN_REPORT.txt              per-stage pass/fail + wall clock
├── AGENT_FINDINGS.md           append-only supervisor + agent log
├── TEST_TALLIES.txt            self-reported suite tallies
├── 00_environment/             preflight transcript, pip versions, tuning, agent state
├── 02_build/                   canary + substrate + both-frontend smoke tests
├── 03_datagen/DATA_MANIFEST.txt  line counts + sha256 for all 56 GB
├── 05_agent/                   triage prompts (the exact brief sent) + agent transcripts
├── 10_utests/{bash_fast,python,bash_full}/
├── 20_benchmarks/
│   ├── F_NUMA1_AUDIT.md        ★ did any cell silently lose records?
│   ├── headline/               (†)/(max) grid + diff vs the published CSV
│   ├── ml5m/  ml20m/  tokenize/  core/  numa5m/
│   └── bash/                   benchmark.out.txt + SUMMARY.txt (incl. steal %)
└── MANIFEST.sha256
```

### The one number to look at first

`20_benchmarks/F_NUMA1_AUDIT.md`. On a topology with more nodes than ever before
tested, a cell that returns fewer records than it consumed is **data loss**, not
a slow run — that is the F-NUMA1 signature, and it is the most valuable thing
this rental can produce. The audit flags any such cell loudly and invalidates
the run's throughput numbers. It also runs with `--require-counts`: a NUMA
throughput cell that reports no input/output cardinality at all is a **failure**,
because nothing would rule out a silent loss inside it.

---

## Reading the NUMA node variants

`41_bench_numa5m` sweeps `--nodes 1,@2,@4,auto`. This is **not** "1 vs 2 vs 4 vs
8 nodes" — `_numa.py:119-136` maps `@N` to `[online[i % len(online)] for i in
range(N)]`, so under Linux's socket-ordered node ids on a 2-socket NPS4 box:

| spec | selects | locality level |
|---|---|---|
| `1` | one logical node | UMA — no NUMA pipeline at all |
| `@2` | physicals 0,1 | **both inside socket 0** |
| `@4` | physicals 0,1,2,3 | **all four CCDs of socket 0, still one socket** |
| `auto` | physicals 0–7 | spans both sockets |

The ladder is therefore UMA → 2 intra-socket nodes → 4 intra-socket nodes → both
sockets, and the informative result is **where the curve bends**: how much
locality benefit exists before you pay the socket hop. Read `@2`/`@4` as
*intra-socket*, never as a socket count.

### Distance is a matrix, not a number

forkrun charges a steal threshold for **every (source, dest) node pair**
(`forkrun_ring.c:2711`, `thresh = 1 + dist/10`, floored at 2). On 2-socket NPS4
that means:

| pair | SLIT distance | steal threshold |
|---|---|---|
| self | 10 | — |
| sibling CCD, same socket | 12 | 2 |
| other socket | 32 | 4 |

The reference box's `numa=fake=4` had a **uniform** distance of 10, charging
every pair 2. So the README's "fake-NUMA is a worst case" claim does not transfer
cleanly: fake-4 was pessimistic for cross-socket stealing *and* optimistic for
intra-socket stealing at the same time. The harness records the full SLIT matrix
in `ENVIRONMENT.md` and reports intra/cross separately rather than collapsing
them into one number.

### Topology sanity gate

`00_preflight.sh` records the topology as an explicit experimental condition and
prints a pass/fail against the expected `2S/NPS4` shape (2+ sockets, ≥4 nodes,
cross-socket distance ≥30). It is not fatal — a 2-node box is still real
multi-socket NUMA, just a weaker version of the experiment — but stages **41 and
43 refuse to run** on an unexpected topology unless you set `EPYC_NUMA_ACK=1`.
Better to decide that in minute one than to discover it in the write-up.

---

## Environment: Ubuntu 26.04 (Resolute)

| | reference lab box | Ubuntu 24.04 (CI) | **Ubuntu 26.04 (this)** |
|---|---|---|---|
| bash | 5.3.9 | 5.2.21 | **5.3** |
| glibc | 2.43 | 2.39 | **2.43** |
| python3 | 3.14.7 | 3.12.3 | **3.14.3** |
| gcc | 16.2 | 14 | 15.2 |
| kernel | 7.1.x | 6.8 | 7.0 |

26.04 matches the reference box on glibc exactly and on Python minor version, so
it is a *better* target than 24.04. The only genuinely new behaviour is Python
3.14's `forkserver` default for `multiprocessing` — the reference box also runs
3.14, so baselines are consistent, and the harness records the start method.

### bash headers

`pyproject.toml` claims bash headers are not packaged on Debian/Ubuntu. **That is
wrong for the header set the engine actually needs.** `apt install bash-builtins`
ships all seven of `shell.h`, `builtins.h`, `variables.h`, `command.h`,
`xmalloc.h`, `config.h`, `builtins/common.h` under `/usr/include/bash/`. So the
Python substrate builds natively — no Fedora container, no Docker, no wheel
download. `10_setup.sh` hard-fails if any header is missing.

---

## Deliberate deviations

All recorded in `DEVIATIONS.md` at run time. The load-bearing ones:

1. **Benchmark worker cap raised 8 → 96.** Ten modules in
   `python/benchmarks/{core,ml}/` hardcode `min(8, os.cpu_count())`. On a
   96-thread box that silently measures 8-way parallelism. Rewritten to honour
   `$FORKRUN_BENCH_WORKERS_MAX`; the exact patch is recorded.
2. **Ray + HF Datasets omitted from the 20M stage** (kept at 5M). Matches the
   repo's own convention. Blocked via `blockmods/sitecustomize.py` so the
   absence is *recorded*, not silently missing from a CSV.
3. **Separate `--tmpdir` per ML scale.** `bench_ml_pipeline.py` reuses
   `<tmpdir>/ml_<variant>.jsonl` on existence alone and the filename has no
   record count — a 5M dir reused for 20M silently reports 4×-inflated rates.
   Every stage asserts the line count before running.
4. **NUMA worker sweeps start at the node count.** `workers < nodes` returns
   INCOMPLETE and is pathologically slow (an unworked node's born-local ring is
   never claimed).
5. **The bash matrix runs unmodified**, single-shot, as the repo ships it. It has
   no warmup, no repetition and no outlier rejection — indicative numbers, not
   defensible ones. The Python suite is median-of-5 and is the defensible one.

---

## Knobs

All optional, set in the environment or override in `epyc/env/epyc.env` after
`00_preflight.sh`:

| var | default | meaning |
|---|---|---|
| `EPYC_OUT` | `<repo>/epyc-rental-out` | results directory |
| `EPYC_DATA` | largest filesystem | datasets + venv + tmp |
| `EPYC_WORKERS_MAX` | `nproc` | the "all logical cores" cell point |
| `EPYC_SWEEP_FAST` | `8,16,32,48,96` | sweep for expensive competitor matrices |
| `EPYC_SWEEP_FULL` | `8,12,16,24,32,48,64,96` | sweep for forkrun-only legs |
| `EPYC_SWEEP_NUMA` | `8,16,32,48,96` | `bench_numa_5m` scaling sweep |
| `EPYC_TRIALS` | 3 | trials per benchmark leg |
| `EPYC_TOKENIZE_DOCS` | 2000000 | tokenize corpus size |
| `EPYC_ML20_VARIANTS` | `light medium heavy` | which 20M variants to run |
| `EPYC_CORE_SCALE` | `large` | `run_all.py --scale` (small/medium/large) |
| `EPYC_BASH_BENCH_REDUCED` | 0 | 1 = 33-shape bash matrix (396 cases, matches the committed reference) |
| `EPYC_BENCH_WORKERS_MAX` | `= nproc` | the patched benchmark worker cap |
| `EPYC_NUMA_ACK` | 0 | 1 = run stages 41/43 even if the topology isn't the expected 2S/NPS4 shape |
| `EPYC_TOPOLOGY_EXPECTED` | `2S/NPS4` | what the sanity gate checks the box against |
| `EPYC_AGENT_MODEL` | `opencode/space-bunny-free` | model for the overnight supervisor |
| `EPYC_SKIP_AGENT` | 0 | 1 = do not install/configure opencode at all |
| `EPYC_MAX_TRIAGE` | 3 | default total agent consultations per night |
| `EPYC_AGENT_TIMEOUT` | 1800 | seconds allowed for one agent consultation |
| `EPYC_AGENT_EVIDENCE_LINES` | 120 | log lines inlined into a triage prompt |

---

## Notes

- **Everything needs root**: THP, `numa_balancing`, the governor, and the apt
  install. Cherry Servers bare metal ships unrestricted root.
- **Do not change the BIOS mid-run.** NPS mode changes the node count, which
  changes `nodes=auto`, the steal threshold, and the F-NUMA1 risk. If you flip
  NPS1→NPS4 in the KVM, re-run `41_bench_numa5m.sh` and `43_bench_ml20m.sh`.
- **Data is ~56 GB** (5M set 12 GB + 20M set 38 GB + tokenize 3.9 GB + bash
  inputs 1.2 GB + stage0 0.6 GB), hardlinked where the same bytes are needed
  under two names. Peak RSS is ~60 GB on the 20M Pool/Executor legs, which read
  the whole corpus into a Python list before chunking.
- **If a stage fails, the run continues.** A failed benchmark is recorded and
  stepped over; the collect stage still produces a full report of what completed.
  Only `00_preflight` and `10_setup` abort the run, because nothing after them is
  meaningful without a working forkrun.
