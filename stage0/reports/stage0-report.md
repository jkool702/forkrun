# Stage 0 rehearsal report (fake NUMA — NOT real-NUMA evidence)

## Verdict (spec §8)

**INCONCLUSIVE for real-NUMA benefit (required by spec §8: fake-NUMA evidence cannot establish the gate; rental campaign needed)**

- Whole-tree CPU: 1.16-7.32 core-equivalents (child process tree, sampled concurrently). Whether the single centralized ingest THREAD saturates ~1 core while workers idle cannot be attributed from here: no per-thread role tagging or queue-empty telemetry exists in the harness (spec §4.2/§4.3 gap).
  NOTE: upper-stage numbers that bundle 'ingest+' compute' into one tree total; the ingest-only rate is NOT isolated in these cells.
- Startup-dominated cells (<2s wall; the campaign's own 2-second rule flags these as bring-up-dominated, not steady-state: file-light20m-n4-w14-plugin)
- Downstream-demand (spec §3 queue-nonempty-interval method) is NOT AVAILABLE in this harness: no scanner-queue occupancy telemetry is exposed; the least-invasive ring diagnostic for isolating ingest vs starvation is deferred to the rental/instrumentation phase. Without it, ingest-limited vs downstream-limited attribution of idle time is an inference, not a measurement.

## Baseline cases (median of trials)

| case | spec | trials ok | rec/s (median) | spread % | wall s | tree cores |
|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | w14 n1 udf | 3/3 | 5603025 | 2.2 | 3.65 | 1.16 |
| file-light20m-n4-w14 | w14 n@4 udf | 3/3 | 5967069 | 4.4 | 3.42 | 1.84 |
| file-light20m-n4-w14-plugin | w14 n@4 plugin | 3/3 | 26963126 | 24.2 | 0.81 | 7.32 |
| file-light20m-n4-w4 | w4 n@4 udf | 3/3 | 5448008 | 8.5 | 3.75 | 1.43 |
| pipe-light20m-n4-w14 | w14 n@4 udf | 3/3 | 5643890 | 8.0 | 3.62 | 1.82 |

## 2×2 affinity/policy ablation (spec §6)

| cell | affinity (cpu, set_rc) | policy (node, set_rc) | pages by node | unknown |
|---|---|---|---|---|
| A | cpu=None rc=None | node=None rc=None | {'0': 2048} | 0 |
| B | cpu=7 rc=0 | node=None rc=0 | {'0': 2048} | 0 |
| C | cpu=None rc=None | node=2 rc=0 | {'2': 2048} | 0 |
| D | cpu=14 rc=0 | node=1 rc=0 | {'1': 2048} | 0 |

Finding: cell D (pinned node X, bound node Y) allocates on Y →
task memory policy decides placement; CPU affinity does not.

## Provenance

- git: NEW/REFACTOR5.0 @ 06937795edd6efe8a7dfab5737dea25e0ce1fe2e (dirty=True)
- kernel: 7.1.10-200.numa_emu.fc44.x86_64 | cmdline fake-numa: numa=fake=4
- shmem THP: [always] within_size advise never deny force
- build hashes: frun.bash=fdf5fcf30905, _forkrun_cleanroom=7d0644fc39bb, _fr_udf.cpython-314-x86_64-linux-gnu.so=9c69deeb8176, libforkrun_python.so=2e8563091075

## One-page decision summary

Is the central ingest the limiter? NOT DECIDABLE on this box (spec §8 maps this to Inconclusive): whole-tree CPU peaks in the 1-7 core range depending on config (highest in the C-plugin and pipe cells, where C-level work and `cat` feeding dominate), but no ingest-THREAD attribution or scanner-queue occupancy telemetry exists in this harness, so the serial-ingest bottleneck hypothesis cannot be confirmed or denied here. The first-order screen that §7.1 asks for — one ingest thread at ~1 core while workers idle — needs the least-invasive ring diagnostic (§4.3) that this rehearsal identified but did not add (observational-only, no scheduling change).
Is placement born-local? The 2x2 ablation answers the MECHANISM question on fake NUMA (cells C/D land 2048/2048 pages on the bound node; cell D shows task policy, not affinity, decides placement). This validates the instrumentation, not real-hardware residency.
What remains: (1) rental execution of this exact campaign on real multi-node hardware (recipe below); (2) engine-side instrumentation for ingest-thread CPU and scanner-queue occupancy during that rental; (3) the plugin cell needs a bigger corpus (it finishes in <1s at 20M and is build-verify-only today).