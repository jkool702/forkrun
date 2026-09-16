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