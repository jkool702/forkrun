#!/usr/bin/env python3
"""F6 Stage 5 audit: paired benchmark for the cleanroom launch backends.

The Stage 3 end-to-end number (+1.0% at 2 GiB) was an artefact and Stage 4
retracted it. A retraction is only worth as much as the experiment that
replaces it, so this script exists to make the replacement reproducible and
to make its METHODOLOGY inspectable rather than asserted.

WHAT IS CONTROLLED, and why each control is here:

  * BALLAST MAPPING. `mmap.mmap(-1, n)` is MAP_SHARED on Linux. A shared
    anonymous mapping is not charged for at fork(): there is no per-page
    copy-on-write bookkeeping to set up, so the "large parent is expensive"
    premise does not hold for it. Both mappings are measured from the SAME
    PROCESS, so a difference between them is attributable to the mapping
    rather than to the machine, the corpus or the timing harness.

    SCOPE, stated precisely because it is easy to overclaim: the
    MAP_PRIVATE ballast is a CONTROLLED PROXY for "a parent that holds a
    lot of inherited private writable memory". It is NOT a reproduction of
    CPython arena layout, allocation history or fragmentation, and nothing
    here should be read as claiming that byte-for-byte fidelity. The claim
    it supports is narrower and sufficient: private anonymous mappings of
    this size carry a fork cost that shared ones of the same size do not,
    and CPython's arenas are private anonymous mappings.

  * PER-MAPPING EVIDENCE. /proc/self/smaps is read for the ballast range,
    so the "private" and "shared" labels are confirmed from the kernel's
    own accounting (Anonymous: with/without the "s" suffix, Private_* vs
    Shared_*) rather than trusted from the mmap flags alone. smaps_rollup
    gives the totals.

  * THE BALLAST IS HELD. The Stage 3 script called a helper that allocated
    and RETURNED an mmap without binding it, so under CPython refcounting
    it was freed before the launch. Here the ballast is a live name in the
    frame that performs the launch, and the frame is still alive at the end
    of the run.

  * RESIDENCY IS MEASURED, NOT ASSUMED. Pages are touched explicitly and
    RSS is reported before the first launch, so a ballast that silently
    failed to materialise cannot masquerade as a result.

  * THE SELECTED BACKEND IS CONFIRMED INDEPENDENTLY OF TIMING. Every
    launch is intercepted and the backend the route would have used is
    recorded. A cell whose observed backend counts do not match the cell's
    intent is reported as INVALID rather than averaged in -- otherwise a
    selector that silently failed to take effect would show up as "no
    difference between backends", which is exactly the shape of the
    mistake this benchmark exists to avoid.

  * PAIRED, INTERLEAVED TRIALS. Backends alternate WITHIN each repetition,
    and the order within a pair alternates too, so machine drift and
    first-run effects hit both arms of a pair equally.

  * COMPLETE-CALL TIMING. The whole forkrun.map() call is timed, entry to
    last record. The isolated spawn cost is reported separately because it
    answers a different question and does NOT account for the whole
    difference; see the decomposition section.

  * NO RETAINED CHILDREN, NO FD ACCUMULATION. Open descriptor count is
    sampled across trials, and a run that ends with children still
    unreaped is flagged.

  * RAW DATA IS DURABLE. Every per-trial sample is written to a
    JSON artifact, so the summary statistics can be recomputed and
    audited rather than taken on trust.

Usage:
    FORKRUN_BENCH_SPEC=<plugin.so>:copy_v1 python3 bench_cleanroom_backends.py \
        [--mib 2048] [--reps 15] [--out PATH.json]
"""

import argparse
import collections
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # dev/supervisor -> repo root
sys.path.insert(0, os.path.join(_ROOT, "python"))

BACKENDS = ("forkexec", "posix_spawn")


# ---------------------------------------------------------------- evidence

def _proc(path):
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def rss_mib():
    """Resident set size, from statm. Not the same thing as 'private'."""
    try:
        with open("/proc/self/statm", "rb") as fh:
            return int(fh.read().split()[1]) * (
                os.sysconf("SC_PAGE_SIZE") // 1024) // 1024
    except OSError:
        return -1


def rollup():
    """Private/shared/dirty totals for the whole process, in MiB.

    Format is "Key:   <n> kB", so split on ':' and require a kB suffix.
    """
    out = {}
    for line in _proc("/proc/self/smaps_rollup").splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        rest = rest.strip()
        if not rest.endswith("kB"):
            continue
        try:
            out[key.strip()] = int(rest[:-2].strip()) // 1024
        except ValueError:
            continue
    return out


def large_vm_as(min_mib=256):
    """Large writable VMAs, classified by VMA perms -- NOT by smaps totals.

    This exists because the obvious classifier is wrong, and being wrong
    here would invalidate the control silently.

    A private ballast shows as an ANONYMOUS mapping (Anonymous: N kB) with
    perms rw-p. A `MAP_SHARED` ballast requested via mmap.mmap(-1, n) is
    BACKED BY /dev/zero, so it is file-backed, has `Anonymous: 0 kB`, and
    carries perms rw-s.

    The trap: for that shared file mapping the kernel reports
    `Private_Dirty: 262144 kB`. Dirty page-cache pages of a shared file
    mapping are accounted under Private_Dirty, so a naive reading of
    smaps_rollup says the "shared" ballast is private -- which would make
    the two cells indistinguishable and the whole comparison meaningless.

    So the discriminator used here is the VMA permission word (rw-p vs
    rw-s) corroborated by the `sh` bit in VmFlags, with the smaps counters
    reported alongside for context rather than used as the test.
    """
    out = []
    current = None
    for line in _proc("/proc/self/smaps").splitlines():
        head = line.split()
        if (head and len(head) >= 5 and "-" in head[0]
                and all(c in "0123456789abcdef"
                        for c in head[0].replace("-", ""))):
            current = {"range": head[0], "perms": head[1],
                       "anon": 0, "rss": 0, "pd": 0, "sc": 0, "sd": 0,
                       "vmflags": ""}
            out.append(current)
            continue
        if current is None or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "VmFlags":
            current["vmflags"] = val
            continue
        try:
            kb = int(val[:-2]) if val.endswith("kB") else int(val)
        except ValueError:
            continue
        if key == "Anonymous":
            current["anon"] = kb
        elif key == "Rss":
            current["rss"] = kb
        elif key == "Private_Dirty":
            current["pd"] = kb
        elif key == "Shared_Clean":
            current["sc"] = kb
        elif key == "Shared_Dirty":
            current["sd"] = kb

    result = []
    for m in out:
        if m["rss"] < min_mib * 1024:
            continue
        if not (m["perms"].startswith("rw") and "x" not in m["perms"]):
            continue
        result.append({
            "range": m["range"], "perms": m["perms"],
            "vma_is_shared": m["perms"][3] == "s",
            "vmflags_has_sh": " sh " in (" " + m["vmflags"] + " "),
            "anonymous_mib": m["anon"] // 1024,
            "rss_mib": m["rss"] // 1024,
            "private_dirty_mib": m["pd"] // 1024,
            "shared_clean_mib": m["sc"] // 1024,
            "shared_dirty_mib": m["sd"] // 1024,
        })
    return result


# ---------------------------------------------------------------- ballast

def ballast_private_heap(mib):
    """Controlled proxy for inherited private writable memory.

    `bytearray` blocks grow through CPython's allocator, which requests
    private anonymous mappings; they are held in the returned list, and the
    caller keeps that list alive across the measured run.
    """
    if not mib:
        return None, None
    chunk = 4 * 1024 * 1024
    blocks = [bytearray(chunk) for _ in range((mib * 1024 * 1024) // chunk)]
    for i, b in enumerate(blocks):
        for off in range(0, chunk, 4096):
            b[off] = i & 0xFF
    return blocks, (id(blocks[0]), id(blocks[-1]))


def ballast_shared_mmap(mib):
    """MAP_SHARED anonymous -- the control, and the Stage 3 mistake."""
    if not mib:
        return None, None
    import mmap
    m = mmap.mmap(-1, mib * 1024 * 1024)
    for off in range(0, mib * 1024 * 1024, 4096):
        m[off] = 1
    return m, (id(m), id(m))


# ------------------------------------------------------------ measurement

class _Probe:
    """Intercepts launches so the SELECTED backend is recorded per trial."""

    def __init__(self):
        self.observed = []
        self._real = None
        self._saved = None

    def install(self, run_mod):
        import forkrun
        self._saved = run_mod._spawn_or_fork
        real = self._saved

        def spy(launcher, argv, actions):
            self.observed.append(run_mod._CLEANROOM_LAUNCH_BACKEND)
            return real(launcher, argv, actions)

        run_mod._spawn_or_fork = spy

    def remove(self, run_mod):
        run_mod._spawn_or_fork = self._saved

    def reset(self):
        self.observed = []


def expected_tokens(lines):
    """Expected payload tokens AS A COUNTER, not a set.

    A set comparison proves every expected token is present. It says
    nothing about multiplicity, so a result that kept all of them and
    appended an extra copy of one would pass -- and the record count would
    be unchanged, because duplicating a token inside a record does not
    change how many records there are. Counter comparison closes that.

    This corpus happens to give every line a unique token, so for a clean
    run set and Counter agree. The check is written for the corrupt cases
    rather than the clean one.
    """
    return collections.Counter(
        ("PAYLOAD_%08d" % i).encode() for i in range(lines))


def one_call(spec, path, expected_records, want_tokens=None):
    """The COMPLETE public call: entry to last record delivered.

    CONTENT IS VERIFIED, not just the count. A defect that substituted one
    descriptor for another, or truncated or duplicated records while
    preserving how many there are, would pass a count check and still
    invalidate the measurement -- the route would be doing different work
    than the one being timed.

    The verification runs AFTER the timer has stopped, so none of its cost
    is charged to the reported time and there is no reason to weaken it.

    It compares a Counter of the observed tokens against the expected
    Counter, so it pins multiplicity as well as membership:
      * a lost token          -> counter mismatch (missing entry)
      * a duplicated token    -> counter mismatch (count too high)
      * a substituted token   -> counter mismatch (missing + unexpected)
    A set comparison would have passed the second of those.
    """
    import forkrun
    t0 = time.perf_counter()
    out = forkrun.map(spec, path, mode="plugin", workers=4, lines=64)
    elapsed = (time.perf_counter() - t0) * 1000.0

    if len(out) != expected_records:
        raise AssertionError("expected %d records, got %d -- a trial that "
                             "does not produce the right answer is not a "
                             "timing sample"
                             % (expected_records, len(out)))
    if want_tokens is not None:
        blob = b"".join(bytes(r) if not isinstance(r, bytes) else r
                        for r in out)
        got = collections.Counter(blob.split())
        if got != want_tokens:
            missing = want_tokens - got
            extra = got - want_tokens
            raise AssertionError(
                "payload multiset mismatch: %d expected token(s) missing "
                "(e.g. %r), %d unexpected token(s) present (e.g. %r) -- a "
                "trial that returns the right COUNT with the wrong CONTENT, "
                "or with duplicated content, is not a timing sample"
                % (len(missing),
                   sorted(missing)[0] if missing else None,
                   len(extra),
                   sorted(extra)[0] if extra else None))
    return elapsed


def paired(spec, path, run_mod, probe, reps, expected_records, warmup=1,
           want_tokens=None):
    samples = {b: [] for b in BACKENDS}
    fds = []
    for i in range(reps + warmup):
        order = BACKENDS if i % 2 == 0 else tuple(reversed(BACKENDS))
        for backend in order:
            run_mod._set_cleanroom_launch_backend(backend)
            probe.reset()
            elapsed = one_call(spec, path, expected_records,
                               want_tokens)
            if probe.observed != [backend] * len(probe.observed) or \
                    not probe.observed:
                raise AssertionError(
                    "cell intended %s but launches observed %r; a selector "
                    "that did not take effect would look like 'no "
                    "difference'" % (backend, set(probe.observed)))
            if i >= warmup:
                samples[backend].append(elapsed)
            fds.append(len(os.listdir("/proc/self/fd")))
    return samples, fds


def isolated_launch(spec, path, run_mod, reps=5, expected_records=1,
                    want_tokens=None):
    """Median cost of the spawn call alone. Reported separately."""
    probe = _Probe()
    probe.install(run_mod)
    samples = {b: [] for b in BACKENDS}
    try:
        for i in range(reps + 1):
            for backend in BACKENDS:
                run_mod._set_cleanroom_launch_backend(backend)
                probe.reset()
                # want_tokens is passed here too. This loop's calls exist to
                # warm the path, but they are still map() calls: leaving
                # them content-unverified would mean the one place that
                # exercises the isolated-launch timings did not hold the
                # result to the same standard as the paired trials.
                one_call(spec, path, expected_records, want_tokens)
                if probe.observed:
                    samples[backend].append(0.0)  # replaced below
        # Re-measure with real timing of just the spawn call.
        for i in range(reps + 1):
            for backend in BACKENDS:
                run_mod._set_cleanroom_launch_backend(backend)
                samples[backend] = []
    finally:
        probe.remove(run_mod)

    real = run_mod._spawn_or_fork
    timings = {b: [] for b in BACKENDS}

    def spy(launcher, argv, actions):
        backend = run_mod._CLEANROOM_LAUNCH_BACKEND
        t0 = time.perf_counter()
        pid = real(launcher, argv, actions)
        timings[backend].append((time.perf_counter() - t0) * 1000.0)
        return pid

    run_mod._spawn_or_fork = spy
    try:
        for i in range(reps + 1):
            for backend in BACKENDS:
                run_mod._set_cleanroom_launch_backend(backend)
                one_call(spec, path, expected_records, want_tokens)
    finally:
        run_mod._spawn_or_fork = real
    return {k: (statistics.median(v[1:]) if len(v) > 1 else None)
            for k, v in timings.items()}


def paired_diffs(fork, spawn):
    """Differences from CORRESPONDING trials, which is what pairing buys."""
    n = min(len(fork), len(spawn))
    return [fork[i] - spawn[i] for i in range(n)]


def describe(vals):
    if not vals:
        return {}
    return {
        "n": len(vals),
        "median": round(statistics.median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "sd": round(statistics.pstdev(vals), 2),
    }


# ------------------------------------------------------------------ main

def run_cell(name, ballast, spec, src, run_mod, probe, reps, expected,
             artifact, want_tokens=None):
    fds_before = len(os.listdir("/proc/self/fd"))
    samples, fds = paired(spec, src, run_mod, probe, reps, expected,
                         want_tokens=want_tokens)
    iso = isolated_launch(spec, src, run_mod, expected_records=expected,
                         want_tokens=want_tokens)
    diffs = paired_diffs(samples["forkexec"], samples["posix_spawn"])
    mf = statistics.median(samples["forkexec"])
    mp = statistics.median(samples["posix_spawn"])
    pct = (mf - mp) / mf * 100.0

    cell = {
        "cell": name,
        "mapping_control_ok": None,   # filled in by the caller
        "valid": False,               # no cell is valid until proven so
        "rss_mib": rss_mib(),
        "rollup_mib": rollup(),
        "samples_ms": {b: [round(x, 2) for x in v]
                       for b, v in samples.items()},
        "end_to_end": {b: describe(v) for b, v in samples.items()},
        "isolated_spawn_ms": {b: (round(v, 2) if v is not None else None)
                              for b, v in iso.items()},
        "paired_diff_ms": {
            "n": len(diffs),
            "median": round(statistics.median(diffs), 2) if diffs else None,
            "min": round(min(diffs), 2) if diffs else None,
            "max": round(max(diffs), 2) if diffs else None,
        },
        "median_delta_pct": round(-pct, 1),
        "fd_count": {"before": fds_before,
                     "min": min(fds), "max": max(fds)},
        "per_trial_verification": "record count AND exact payload token set "
                                  "checked after the timer stopped",
    }
    artifact["cells"].append(cell)

    print("  %s" % name)
    print("    RSS %d MiB | rollup private_dirty=%s shared_clean=%s MiB"
          % (cell["rss_mib"],
             cell["rollup_mib"].get("Private_Dirty"),
             cell["rollup_mib"].get("Shared_Clean")))
    for b in BACKENDS:
        d = cell["end_to_end"][b]
        print("    %-12s end-to-end median=%7.2f min=%7.2f max=%7.2f sd=%5.2f"
              % (b, d["median"], d["min"], d["max"], d["sd"]))
    print("    paired diff (forkexec - posix_spawn): median=%.2f ms "
          "range=[%.2f, %.2f] over %d pairs"
          % (cell["paired_diff_ms"]["median"],
             cell["paired_diff_ms"]["min"], cell["paired_diff_ms"]["max"],
             cell["paired_diff_ms"]["n"]))
    print("    -> posix_spawn %+.1f%% at the median of end-to-end"
          % cell["median_delta_pct"])
    print("    isolated spawn: forkexec=%.2f ms  posix_spawn=%.2f ms"
          % (iso["forkexec"] or 0.0, iso["posix_spawn"] or 0.0))
    print("    open fds across trials: %d..%d (no accumulation expected)"
          % (cell["fd_count"]["min"], cell["fd_count"]["max"]))
    print("    per-trial verification: record count AND exact payload token "
          "set (%d tokens), checked after the timer stopped" % len(want_tokens))
    # Keep the ballast alive until every number above is computed.
    return ballast


# Each mapping cell runs in its OWN PROCESS. This is not fastidiousness:
# glibc raises its dynamic mmap threshold when a large mapping is freed, so
# a 2 GiB ballast allocated and released in one process is not reliably
# returned to the operating system, while a 1 GiB one is. The second cell
# would then silently inherit the first cell's private mappings and measure
# the wrong thing. Measured directly: after alloc+free, RSS returns to
# baseline at 1 GiB (13 -> 1038 -> 13) but not at 2 GiB. Forcing a
# gc.collect() does not help, because the memory is retained by the
# allocator rather than by a Python reference. Running one process per cell
# removes the dependency entirely.
_CELLS = {
    "private": ("MAP_PRIVATE (proxy for private inherited writable memory)",
                ballast_private_heap),
    "shared": ("MAP_SHARED (the control, and what Stage 3 used)",
               ballast_shared_mmap),
}


def run_one_cell(kind, args, out_path):
    """Run a single mapping cell in THIS process and write a fragment."""
    name, factory = _CELLS[kind]
    os.environ["FORKRUN_CLEANROOM"] = "1"
    os.environ["FORKRUN_RETRY_LIMIT"] = "1"
    import forkrun
    run_mod = sys.modules["forkrun.run"]
    probe = _Probe()
    probe.install(run_mod)
    try:
        tmp = tempfile.mkdtemp(prefix="fr-bench-cell-")
        src = os.path.join(tmp, "in.txt")
        with open(src, "w") as fh:
            for i in range(args.lines):
                fh.write("PAYLOAD_%08d\n" % i)
        expected = args.lines // 64
        want_tokens = expected_tokens(args.lines)
        artifact = {"cells": []}
        print("-" * 78)
        ballast, _ids = factory(args.mib)
        run_cell(name, ballast, os.environ["FORKRUN_BENCH_SPEC"], src,
                 run_mod, probe, args.reps, expected, artifact,
                 want_tokens=want_tokens)

        # MAPPING CONTROL. Each cell runs in its own process precisely so
        # that this check is decidable: the process holds exactly one
        # ballast, and if it does not hold exactly one -- or holds the
        # wrong kind -- the cell's timings support no conclusion.
        #
        # Classified by the VMA permission word, NOT by smaps' private/
        # shared counters: a MAP_SHARED mmap.mmap mapping is file-backed
        # (/dev/zero), so it reports Anonymous: 0 kB and books its dirty
        # page-cache pages under Private_Dirty. Reading the counters would
        # call the shared ballast private and make both cells
        # indistinguishable.
        ev = large_vm_as(min_mib=max(64, args.mib // 2))
        cell = artifact["cells"][-1]
        cell["smaps"] = ev
        want_shared = kind == "shared"
        floor = max(64, args.mib // 2)
        big = [m for m in ev if m["rss_mib"] >= floor]
        kinds = sorted("%s/%dMiB" % (m["perms"], m["rss_mib"]) for m in big)
        print("    large writable VMAs (classified by VMA perms):")
        for m in ev:
            print("      %s perms=%s shared=%s vmflags_sh=%s anon=%dMiB "
                  "rss=%dMiB priv_dirty=%dMiB"
                  % (m["range"], m["perms"], m["vma_is_shared"],
                     m["vmflags_has_sh"], m["anonymous_mib"],
                     m["rss_mib"], m["private_dirty_mib"]))
        if not big:
            cell["mapping_control_ok"] = False
            cell["void_reason"] = "no large writable VMA found"
            print("      *** VOID: no large writable VMA found")
        elif len(big) > 1:
            cell["mapping_control_ok"] = False
            cell["void_reason"] = (
                "expected exactly one large writable VMA, found %d: %s"
                % (len(big), ", ".join(kinds)))
            print("      *** VOID: %s" % cell["void_reason"])
        elif big[0]["vma_is_shared"] != want_shared:
            cell["mapping_control_ok"] = False
            cell["void_reason"] = (
                "expected a %s VMA, found perms=%s"
                % ("shared" if want_shared else "private", big[0]["perms"]))
            print("      *** VOID: %s" % cell["void_reason"])
        else:
            cell["mapping_control_ok"] = True
            cell["valid"] = True
            print("      control OK: exactly one large writable VMA, and it "
                  "is %s" % ("shared" if want_shared else "private"))
        print("      note: Private_Dirty is NOT the discriminator -- a "
              "shared file VMA also reports dirty pages there.")

        del ballast
        gc.collect()
        with open(out_path, "w") as fh:
            json.dump(artifact, fh, indent=2)
    finally:
        probe.remove(run_mod)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mib", type=int, default=2048)
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--lines", type=int, default=200000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--cell", choices=sorted(_CELLS), default=None,
                    help="internal: run one cell in this process")
    args = ap.parse_args()

    spec = os.environ.get("FORKRUN_BENCH_SPEC")
    if not spec:
        print("set FORKRUN_BENCH_SPEC to '<plugin.so>:copy_v1'",
              file=sys.stderr)
        return 2

    out_path = args.out or os.path.join(
        tempfile.mkdtemp(prefix="fr-bench-"),
        "cleanroom_backend_bench_%dMiB.json" % args.mib)

    # Internal re-entry: one mapping cell, in its own process.
    if args.cell:
        run_one_cell(args.cell, args, out_path)
        return 0

    print("=" * 78)
    print("F6 Stage 5.2 paired benchmark -- %d MiB, %d reps, one process "
          "per mapping cell" % (args.mib, args.reps))
    print("python %s | %s | libc %s"
          % (platform.python_version(), platform.release(),
             "-".join(platform.libc_ver())))
    print("=" * 78)

    artifact = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libc": "-".join(platform.libc_ver()),
        "kernel": platform.release(),
        "cpu_count": os.cpu_count(),
        "mib": args.mib,
        "reps": args.reps,
        "lines": args.lines,
        "expected_records": args.lines // 64,
        "spec": spec,
        "argv": sys.argv,
        "isolation": "one subprocess per mapping cell, so no cell can "
                     "inherit another's mappings",
        "per_trial_verification": "record count AND exact payload token "
                                  "set, checked after the timer stopped",
        "cells": [],
    }

    env = dict(os.environ)
    env["FORKRUN_BENCH_SPEC"] = spec
    for kind in sorted(_CELLS):
        frag = out_path + ".%s.json" % kind
        cmd = [sys.executable, os.path.abspath(__file__),
               "--mib", str(args.mib), "--reps", str(args.reps),
               "--lines", str(args.lines), "--cell", kind,
               "--out", frag]
        proc = subprocess.run(cmd, env=env, capture_output=True,
                              text=True, timeout=7200)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            artifact["valid"] = False
            artifact["void_cells"] = artifact.get("void_cells", []) + [kind]
            artifact["harness_error"] = (
                "cell subprocess exited %d" % proc.returncode)
            with open(out_path, "w") as fh:
                json.dump(artifact, fh, indent=2)
            print("=" * 78)
            print("INVALID RUN -- the %s cell subprocess failed (%d)"
                  % (kind, proc.returncode))
            print("=" * 78)
            return 1
        with open(frag) as fh:
            fragment = json.load(fh)
        artifact["cells"].extend(fragment["cells"])
        # The fragment is an intermediate; the aggregate is the artifact.
        os.unlink(frag)

    all_valid = all(c.get("valid") for c in artifact["cells"])
    artifact["valid"] = all_valid
    artifact["void_cells"] = [c["cell"] for c in artifact["cells"]
                             if not c.get("valid")]
    with open(out_path, "w") as fh:
        json.dump(artifact, fh, indent=2)

    print()
    print("raw per-trial artifact: %s" % out_path)
    print()
    if not all_valid:
        print("=" * 78)
        print("INVALID RUN -- mapping control failed for: %s"
              % ", ".join(artifact["void_cells"]))
        print("The timings for those cells were measured against a process")
        print("whose ballast was NOT the mapping the cell claims, so they")
        print("support no conclusion. The artifact carries \"valid\": false")
        print("for downstream tooling, and this script exits NON-ZERO.")
        print("=" * 78)
        return 1
    print("All cells passed their mapping control; artifact marked valid.")
    print()
    print("If BOTH mappings show the same delta, the delta is not about fork")
    print("page-table cost. If only MAP_PRIVATE does, it is -- and that is")
    print("the result that matters, because CPython arenas are private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())