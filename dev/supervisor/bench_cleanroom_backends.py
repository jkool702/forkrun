#!/usr/bin/env python3
"""F6 Stage 4 audit: paired benchmark, MAP_PRIVATE vs MAP_SHARED ballast.

The Stage 3 end-to-end number (+1.0% at 2 GiB) was an artefact and Stage 4
retracted it, but a retraction is only worth as much as the experiment that
replaces it. This script exists so the replacement is reproducible and so
its methodology is visible rather than asserted.

WHAT IS BEING CONTROLLED, and why each control is here:

  * BALLAST MAPPING. `mmap.mmap(-1, n)` is MAP_SHARED on Linux. A shared
    anonymous mapping is NOT charged for at fork(): there is no per-page
    copy-on-write bookkeeping to set up, so the "large parent is expensive"
    premise simply does not hold for it. CPython's own arenas are
    MAP_PRIVATE, which is why a real growing process pays the tax. Both
    are measured here, from the same process, to show the difference is the
    mapping and not the measurement.

  * THE BALLAST IS HELD. The Stage 3 script called a helper that allocated
    and then RETURNED the mmap without binding it, so under CPython
    refcounting it was freed before the launch. Here the ballast is a live
    name in the frame that performs the launch.

  * RSS IS MEASURED, NOT ASSUMED. Stated before the first launch, so a
    ballast that silently failed to materialise cannot masquerade as a
    result.

  * PAIRED, INTERLEAVED TRIALS. Backends alternate WITHIN each repetition
    rather than running all of A then all of B, so any drift in machine
    load hits both arms of a pair equally. Order within a pair is
    alternated as well, which controls for a first-run/second-run effect.

  * COMPLETE-CALL TIMING. The whole `forkrun.map()` call is timed, from
    entry to the last record delivered -- not the isolated spawn syscall.
    The isolated number and the end-to-end number answer different
    questions and are reported separately.

  * WARMUP DISCARDED, AND DISCLOSED. The first repetition per backend is
    dropped, and the raw per-repetition samples are printed so the spread
    is inspectable rather than summarised away.
"""

import os
import statistics
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # dev/supervisor -> repo root
sys.path.insert(0, os.path.join(_ROOT, "python"))


def _rss_mib():
    with open("/proc/self/statm", "rb") as fh:
        return int(fh.read().split()[1]) * (
            os.sysconf("SC_PAGE_SIZE") // 1024) // 1024


def ballast_private_heap(mib):
    """CPython-arena-like: MAP_PRIVATE anonymous, touched, and HELD."""
    if not mib:
        return None
    chunk = 4 * 1024 * 1024
    blocks = [bytearray(chunk) for _ in range((mib * 1024 * 1024) // chunk)]
    for i, b in enumerate(blocks):
        for off in range(0, chunk, 4096):
            b[off] = i & 0xFF
    return blocks


def ballast_shared_mmap(mib):
    """MAP_SHARED anonymous -- the Stage 3 mistake."""
    if not mib:
        return None
    import mmap
    m = mmap.mmap(-1, mib * 1024 * 1024)
    for off in range(0, mib * 1024 * 1024, 4096):
        m[off] = 1
    return m


def one_call(spec, path):
    import forkrun
    t0 = time.perf_counter()
    out = forkrun.map(spec, path, mode="plugin", workers=4, lines=64)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert len(out) == 3125, "unexpected record count %d" % len(out)
    return elapsed


def isolated_launch(spec, path, reps=7):
    """Median cost of _spawn_or_fork alone, in the same process."""
    import forkrun
    R = sys.modules["forkrun.run"]
    samples = {"forkexec": [], "posix_spawn": []}
    real = R._spawn_or_fork

    def timed(launcher, argv, actions):
        backend = R._CLEANROOM_LAUNCH_BACKEND
        t0 = time.perf_counter()
        pid = real(launcher, argv, actions)
        samples[backend].append((time.perf_counter() - t0) * 1000.0)
        return pid

    R._spawn_or_fork = timed
    try:
        for _ in range(reps):
            for backend in ("forkexec", "posix_spawn"):
                R._set_cleanroom_launch_backend(backend)
                one_call(spec, path)
    finally:
        R._spawn_or_fork = real
        R._set_cleanroom_launch_backend("posix_spawn")
    return {k: statistics.median(v[1:]) if len(v) > 1 else None
            for k, v in samples.items()}


def paired(spec, path, reps=9):
    samples = {"forkexec": [], "posix_spawn": []}
    for i in range(reps):
        order = (("forkexec", "posix_spawn") if i % 2 == 0
                 else ("posix_spawn", "forkexec"))
        for backend in order:
            import forkrun
            R = sys.modules["forkrun.run"]
            R._set_cleanroom_launch_backend(backend)
            samples[backend].append(one_call(spec, path))
    return samples


def report(label, samples):
    f = samples["forkexec"][1:]
    p = samples["posix_spawn"][1:]
    mf, mp = statistics.median(f), statistics.median(p)
    print("  %s" % label)
    for name, vals in (("forkexec   ", f), ("posix_spawn", p)):
        print("    %s n=%d median=%7.2f ms  min=%7.2f  max=%7.2f  sd=%5.2f"
              % (name, len(vals), statistics.median(vals), min(vals),
                 max(vals), statistics.pstdev(vals)))
    delta = (mf - mp) / mf * 100.0
    print("    -> posix_spawn is %.1f%% faster at the median"
          % (-delta if delta else 0.0))


def main():
    mib = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 9

    import forkrun
    R = sys.modules["forkrun.run"]
    R._set_cleanroom_launch_backend("posix_spawn")
    os.environ["FORKRUN_CLEANROOM"] = "1"
    os.environ["FORKRUN_RETRY_LIMIT"] = "1"

    tmp = tempfile.mkdtemp(prefix="fr-bench-")
    src = os.path.join(tmp, "in.txt")
    with open(src, "w") as fh:
        for i in range(200000):
            fh.write("PAYLOAD_%08d\n" % i)
    spec = os.environ.get("FORKRUN_BENCH_SPEC")
    if not spec:
        print("set FORKRUN_BENCH_SPEC to '<plugin.so>:copy_v1'", file=sys.stderr)
        return 2

    print("=" * 72)
    print("MAP_PRIVATE ballast (what a real growing CPython process has)")
    print("=" * 72)
    heap = ballast_private_heap(mib)
    print("  RSS before launching: %d MiB (requested %d MiB)"
          % (_rss_mib(), mib))
    report("complete forkrun.map() call, paired+interleaved, %d reps" % reps,
           paired(spec, src, reps))
    iso = isolated_launch(spec, src)
    print("  isolated _spawn_or_fork only:")
    for k, v in iso.items():
        print("    %-12s %s" % (k, "%.2f ms" % v if v is not None else "n/a"))
    del heap

    print()
    print("=" * 72)
    print("MAP_SHARED ballast (MAP_SHARED anonymous -- NOT what CPython uses)")
    print("=" * 72)
    shared = ballast_shared_mmap(mib)
    print("  RSS before launching: %d MiB (requested %d MiB)"
          % (_rss_mib(), mib))
    report("complete forkrun.map() call, paired+interleaved, %d reps" % reps,
           paired(spec, src, reps))
    iso = isolated_launch(spec, src)
    print("  isolated _spawn_or_fork only:")
    for k, v in iso.items():
        print("    %-12s %s" % (k, "%.2f ms" % v if v is not None else "n/a"))
    del shared
    print()
    print("If both ballast types show the same delta, the delta is NOT about")
    print("fork page-table cost. If only MAP_PRIVATE does, it is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())