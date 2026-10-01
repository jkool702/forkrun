# QEMU aarch64 Test Leg — Operator Runbook

How to run the emulated-aarch64 portion of the release matrix. Written
for a fresh session: follow top to bottom, no prior context needed.
For *what* to run and *why*, see `RELEASE_RUNBOOK.md` §3; this file is
*how* to run it. For results history, see `GATE_v3.5.x.md` §§16–20.

## 0. Scope and limits (read first)

- **Functional correctness only.** `qemu-aarch64-static` user-mode
  emulation does not model weak-memory reordering — the fence pair gets
  functional coverage, not ordering validation (needs ARM silicon).
- **One physical socket.** `--nodes=@N` is software partitioning;
  born-local `MPOL_BIND` realism is limited. NUMA-topology runs still
  require the host booted with `numa=fake=4`; the UMA subset runs
  anytime.
- **Out of scope here:** benchmarks, sanitizer legs, TUI, x86_64 matrix
  (owner's). This leg = unit suites + targeted probes only.
- **Slow.** User-mode emulation runs ~5–15× slower than native. Every
  suite command below needs a generous timeout; do not background them
  (see §4).

## 1. Host prerequisites

```bash
which qemu-aarch64-static podman            # both must exist
ls /proc/sys/fs/binfmt_misc/qemu-aarch64    # binfmt handler registered
cat /sys/kernel/mm/transparent_hugepage/shmem_enabled
# expect: [always] ... (THP-sensitive sweep suite needs shmem=always)
df -h /tmp                                  # need ~3 GB free (copy + logs)
cat /sys/devices/system/node/online         # 0 for UMA; 0-3 for fake=4
```

## 2. Isolated tree copy (never run in the live repo)

The suites write `.forkrun_resume`, TEST_DIRs, and temp files into the
tree, and the owner may be running the x86_64 matrix concurrently in
the live checkout. Always test a copy:

```bash
mkdir -p /tmp/fx/aleg/forkrun
cd /mnt/ramdisk/forkrun   # (or wherever the live checkout is)
tar --exclude=.git -cf - . | (cd /tmp/fx/aleg/forkrun && tar -xf -)
```

To re-sync later, use rsync — **never `rm -rf` the copy**:

```bash
rsync -a --delete --exclude=.git /mnt/ramdisk/forkrun/ /tmp/fx/aleg/forkrun/
```

(`rm` replaces the directory inode and the container's bind mount goes
stale — empty `/src` with no error. rsync preserves it.)

## 3. Container setup

```bash
podman run -d --arch arm64 --name aleg \
    -v /tmp/fx/aleg/forkrun:/src:rw fedora:44 sleep infinity
podman exec aleg dnf install -y -q gcc make file gawk findutils \
    diffutils procps-ng util-linux hostname
```

Notes: binfmt makes `--arch arm64` transparent (verify with
`podman exec aleg uname -m` → `aarch64`). The container does **not**
survive a host reboot — recreate it and reinstall deps after one.
GCC/make are needed because some suites compile at test time; the
blobs under test are the prebuilt shipped ones, not local builds.

## 4. Smoke test (must pass before any suite)

```bash
podman exec aleg bash -c \
  "cd /src && source ./frun.bash && ring_version -a | head -4"
# expect: Version vX.Y.Z, Arch: aarch64 (proves the shipped blob loads)
podman exec aleg bash -c \
  "cd /src && source ./frun.bash && seq 2000 | frun -k printf '%s\n' | wc -l"
# expect: 2000
```

Execution rules for everything below (learned the hard way):

- **Foreground `podman exec` only, one suite per call, big timeout.**
  Backgrounded execs die when the tool call times out, leaving
  half-run suites and orphaned pipelines behind.
- **Redirect to files, read back summaries only:**
  `> /tmp/fx/aleg/<name>.log 2>&1`, then
  `grep -E "^(Total|Passed|Failed|Skipped):"` plus
  `grep -B1 -A3 "✗" | head -60` (the two `run_test_sorted`
  self-test negatives are expected harness output, not failures).
- **Never touch another run's processes.** Identify your own by
  distinctive paths (`/tmp/fx/aleg`, suite TEST_DIRs) before killing
  any leftover; the owner's matrix or diag scripts may share the box.

## 5. Suite sequence and expected counts

Run from the steps below in order (counts are v3.5.1 post-dedup
actuals — record actuals rather than asserting):

```bash
L=/tmp/fx/aleg
podman exec -w /src aleg bash UNIT_TESTS/test_frun.sh \
    > $L/basic.log 2>&1                                  # expect 91/91
for S in D L T M F R; do
  podman exec -w /src -e SECTION=$S aleg \
      bash UNIT_TESTS/test_frun_comprehensive.sh > $L/sec$S.log 2>&1
done
# expect: D 11/11, L 57/57, T 21/21, M 21/21, F 8/8, R 13/13
```

Key first-time-on-leg markers to confirm explicitly in the logs:
LA3/LA4/F15a/F15b (L), T1a-ext/F6/T1i/T14 (T), M16/M20/M21 (M),
F8 (F), R2/R10 (R).

## 6. Targeted probes

```bash
# -L 100 transient watch (documented): all 10 must print 100
podman exec -w /src aleg bash -c "source ./frun.bash && \
  for i in \$(seq 1 10); do \
    seq 100 | frun --nodes=@2 -L 100 -k printf '%s\n' | wc -l; \
  done"
# NUMA telemetry + exactness (fake topology; UMA host: use @2 only)
podman exec -w /src aleg bash -c "source ./frun.bash && \
  seq 50000 | frun --nodes=@4 --stats -k printf '%s\n' 2>&1 | \
  grep -aE 'Node|NUMA' | head -8"
podman exec -w /src aleg bash -c "source ./frun.bash && \
  seq 50000 | frun --nodes=@4 -k printf '%s\n' | wc -l"
# expect: 50000
```

## 7. Failure protocol

- Any red: stop, record the section log path + failing test name +
  `TEST_ERRORS` detail, and report before doing anything else. Do not
  fix product or test code unilaterally — the leg's job is measurement.
- If a run wedges past its budget: capture `ps -e -o
  pid,ppid,stat,wchan:24,comm` (comm, not cmd — cmd spews the whole
  frun body) plus byte counts at two times before killing *your own*
  tree only.
- Disk hygiene: endless-feeder outputs go to `/dev/null` or bounded
  files; remove your `/tmp` diag artifacts the same session (a 15 GB
  runaway once pushed /tmp to quota failure and broke the suite gate).
- Orphan check after killed runs: `ps -e -o pid,etime,cmd | grep` for
  your distinctive paths; reap yours, leave all others.

## 8. Recording results

Append a dated section to `GATE_v3.5.x.md`: topology (UMA vs fake-N),
tree commit, per-section counts, probe outcomes, and any deltas vs the
previous leg. Then commit the log and report. Tear down with
`podman stop aleg` (or leave it up if a re-probe is likely).
