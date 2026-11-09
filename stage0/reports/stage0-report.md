# Stage 0 rehearsal report (fake NUMA — NOT real-NUMA evidence)

## Verdict (spec §8)

**INVALID INCOMPLETE CAMPAIGN (spec §8 verdict must not classify: expected trials/cases missing or failed)**

Completeness: INCOMPLETE CAMPAIGN — fail-probe: 3/3 trials incomplete or failed; timeout-probe: 3/3 trials incomplete or failed
(No Go/No-Go classification is permitted while the campaign is incomplete.)

Named ingest-thread (fr-ingest) CPU basis: file-light20m-n4-w14: 0.19 cores; file-light20m-n4-w14-plugin: 0.72 cores; file-light20m-n4-w4: 0.17 cores; pipe-light20m-n4-w14: 0.22 cores; plugin-light60m-n4-w14: 0.86 cores

Completeness check failed; report what is missing instead of a Go/No-Go.

## Baseline cases (median of trials)

| case | spec | trials ok | rec/s (median) | spread % | wall s | tree cores |
|---|---|---|---|---|---|---|
| fail-probe | w4 n@4 udf | 0/3 | - | - | - | - |
| file-light20m-n1-w14 | w14 n1 udf | 3/3 | 5450271 | 6.6 | 3.77 | 1.18 |
| file-light20m-n4-w14 | w14 n@4 udf | 3/3 | 5579723 | 10.9 | 3.66 | 1.76 |
| file-light20m-n4-w14-plugin | w14 n@4 plugin | 3/3 | 27202450 | 15.3 | 0.80 | 6.92 |
| file-light20m-n4-w4 | w4 n@4 udf | 3/3 | 5527706 | 1.7 | 3.70 | 1.36 |
| file-light5m-n1-w14 | w14 n1 udf | 3/3 | 5491395 | 3.5 | 0.98 | 1.01 |
| file-light5m-n4-w14 | w14 n@4 udf | 3/3 | 5749035 | 11.0 | 0.94 | 1.45 |
| file-light5m-n4-w14-plugin | w14 n@4 plugin | 3/3 | 16005031 | 6.5 | 0.37 | 3.26 |
| file-light5m-n4-w4 | w4 n@4 udf | 3/3 | 5644017 | 2.8 | 0.96 | 1.17 |
| pipe-light20m-n4-w14 | w14 n@4 udf | 3/3 | 5433874 | 1.3 | 3.76 | 1.78 |
| plugin-light60m-n4-w14 | w14 n@4 plugin | 3/3 | 29755815 | 2.1 | 2.08 | 8.13 |
| smoke-light-100k-n4 | w4 n@4 udf | 3/3 | 2344036 | 22.8 | 0.10 | 0.50 |
| timeout-probe | w4 n@4 udf | 0/3 | - | - | - | - |

## 2×2 affinity/policy ablation (spec §6)

| cell | affinity (cpu, set_rc) | policy (node, set_rc) | pages by node | unknown |
|---|---|---|---|---|
| A/map-fault | cpu=default rc=0 | node=None rc=0 | {'0': 2048} | 0 |
| A/write-path | cpu=default rc=0 | node=None rc=0 | {} | 0 |
| B/map-fault | cpu=0 rc=0 | node=None rc=0 | {'0': 2048} | 0 |
| B/write-path | cpu=0 rc=0 | node=None rc=0 | {} | 0 |
| C/map-fault | cpu=default rc=0 | node=2 rc=0 | {'2': 2048} | 0 |
| C/write-path | cpu=default rc=0 | node=2 rc=0 | {} | 0 |
| D/map-fault | cpu=0 rc=0 | node=1 rc=0 | {'1': 2048} | 0 |
| D/write-path | cpu=0 rc=0 | node=1 rc=0 | {} | 0 |

map-fault form: task memory policy decides placement (cell C/D land 2048/2048 pages on the bound node; cell D pinned-2/bound-1 allocates on node 1; cell B pinned-2/default allocates on node 0). Write-path form: mincore confirms all pages resident, but per-node attribution is Weak via process-level accounting on this box — see raw JSON numastat_delta_mb; the write-path node claim is NOT established here and must not be generalized from the map-fault result.

## Provenance

- git: NEW/REFACTOR5.0 @ ebfbd345f6ab23a32bc12d74e1b00c100dcf1498 (dirty=True)
- kernel: 7.1.10-200.numa_emu.fc44.x86_64 | cmdline fake-numa: numa=fake=4
- shmem THP: [always] within_size advise never deny force
- build hashes: frun.bash=fdf5fcf30905, _forkrun_cleanroom=7d0644fc39bb, _fr_udf.cpython-314-x86_64-linux-gnu.so=9c69deeb8176, libforkrun_python.so=134ba3f70897

## One-page decision summary

Is the central ingest the limiter? NOT DECIDABLE on this box (spec §8 maps this to Inconclusive): whole-tree CPU peaks in the 1-7 core range depending on config (highest in the C-plugin and pipe cells, where C-level work and `cat` feeding dominate), but no ingest-THREAD attribution or scanner-queue occupancy telemetry exists in this harness, so the serial-ingest bottleneck hypothesis cannot be confirmed or denied here. The first-order screen that §7.1 asks for — one ingest thread at ~1 core while workers idle — needs the least-invasive ring diagnostic (§4.3) that this rehearsal identified but did not add (observational-only, no scheduling change).
Is placement born-local? The 2x2 ablation answers the MECHANISM question on fake NUMA (cells C/D land 2048/2048 pages on the bound node; cell D shows task policy, not affinity, decides placement). This validates the instrumentation, not real-hardware residency.
What remains: (1) rental execution of this exact campaign on real multi-node hardware (recipe below); (2) engine-side instrumentation for ingest-thread CPU and scanner-queue occupancy during that rental; (3) the plugin cell needs a bigger corpus (it finishes in <1s at 20M and is build-verify-only today).