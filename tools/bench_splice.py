"""Stage 4 measurement: is cleanroom splice worth integrating?

The design said measure before committing, and that measuring
launcher-splice requires wiring it first. So this answers the question
that decides whether the wiring is worth doing at all:

  Does the C splice loop beat the ordinary in-process path, enough to
  justify integrating it into the launcher?

Reports wall time and PEAK PARENT RSS (ru_maxrss, not current RSS --
current understates a peak). Regressions are reported alongside wins.

Usage: python3 tools/bench_splice.py [trials]
"""

import os
import resource
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "python"))

TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def make_input(nlines, path):
    with open(path, "w") as fh:
        for i in range(nlines):
            fh.write("line %06d %s\n" % (i, "x" * 40))
    return path


def peak_rss_kb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def run_child(code):
    """Run one measurement in a fresh process.

    Peak RSS is only meaningful per-process: the high-water mark never
    decreases, so measuring several variants in one process would report
    the LARGEST run's peak for every later variant.
    """
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        return None, proc.stderr.decode()[-300:]
    out = proc.stdout.decode().strip().splitlines()
    return float(out[-1]), None


BODY = r'''
import os, sys, time, resource
sys.path.insert(0, %(root)r)
import forkrun

path, mode, workers, batch, c_drain = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]),
    sys.argv[5] == "1")

# Only representable, byte-moving paths are compared.
#   splice : the C loop, moving bytes ingress -> output with no invoke
#   spawn  : posix_spawnp a real command (cat / tr), through the launcher
#
# A python-mode lambda is deliberately NOT a baseline: it is not
# exec-representable, so every batch fails and the "result" is a
# poison summary rather than a timing.
# Ordered VALIDATION mode: the same operation under order="index",
# compared BYTE-EXACTLY. The round-8 review is right that the unordered
# runs cannot be validated by concatenation and the histogram is too
# weak; this is where the strong claim lives. It costs one run, not the
# timed sweep, and it is what licenses the tiling check as "sufficient
# for the unordered case".
#
# If this ever fails, the benchmark is not measuring a correct pipeline
# and the timed numbers mean nothing -- so it runs FIRST and aborts.
if mode == "splice":
    payload, kw = None, dict(mode="splice", bytes=batch, c_drain=c_drain)
else:
    # The WHOLE argv vector, not just argv[0]: spawn transports
    # arguments as distinct elements, so passing only "tr" runs a
    # different (failing) command than intended.
    payload = sys.argv[6:]
    kw = dict(mode="spawn", bytes=batch)

# The launcher is forced ON so mode="spawn" genuinely routes through it.
# Without this the benchmark measured the ordinary in-process executor
# while its labels claimed launcher-spawn -- the disconnect the review
# identified between the predicate and the dispatch.
os.environ["FORKRUN_CLEANROOM"] = "1"

want = open(path, "rb").read()


def _records_tile(want, records):
    """Do `records` tile `want` exactly once each, in any order?

    Each record is located in `want` and must appear exactly once (the
    bench input is zero-padded and unique, so a duplicate content match
    means a genuinely duplicated batch). The located spans must then
    cover every offset exactly once.
    """
    spans = []
    for rec in records:
        if not rec:
            continue
        if want.count(rec) != 1:
            return False
        spans.append((want.index(rec), len(rec)))
    spans.sort()
    pos = 0
    for off, ln in spans:
        if off != pos:
            return False
        pos += ln
    return pos == len(want)


def _report_tile_failure(want, records):
    """Name what went wrong, rather than just that something did."""
    missing = []
    seen = []
    pos = 0
    spans = sorted((want.index(r), len(r)) for r in records
                   if r and want.count(r) == 1)
    for off, ln in spans:
        if off != pos:
            missing.append((pos, min(off, len(want))))
            pos = off
        pos += ln
    if pos < len(want):
        missing.append((pos, len(want)))
    sys.stderr.write(
        "OUTPUT NOT A TILING OF THE INPUT: %%d record(s), %%d bytes, "
        "expected %%d.\n"
        "  this means a batch was lost, duplicated, reordered WITHIN "
        "itself,\n  or had its bytes altered -- the byte-histogram check "
        "this replaces\n  could not detect any of those.\n"
        "  first gap: %%r\n" %% (len(records), sum(len(r) for r in records),
                                len(want), missing[:3]))
if payload is not None and payload[0] == "tr":
    # tr a-z A-Z: faithful byte translation, not a targeted replace.
    # An earlier version only uppercased the literal "line", so a correct
    # run "failed" on content the command genuinely changes.
    want = want.translate(bytes.maketrans(
        b"abcdefghijklmnopqrstuvwxyz", b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

ORDERED_VALIDATION = os.environ.get("FORKRUN_BENCH_VALIDATE_ONLY") == "1"

if ORDERED_VALIDATION:
    order = os.environ.get("FORKRUN_BENCH_ORDER", "index")
    out = forkrun.map(payload, path, workers=workers, nodes=1,
                      order=order, output="bytes", **kw)
    recs = [bytes(x) for x in out if x is not None]
    joined = b"".join(recs)
    if joined != want:
        sys.stderr.write(
            "ORDERED VALIDATION FAILED (order=%%r): %%d bytes vs %%d\n"
            "  first difference at offset %%d\n"
            "  The timed sweep below is meaningless if the pipeline is "
            "not\n  correct, so this aborts before measuring.\n"
            %% (order, len(joined), len(want),
               next((i for i, (a, b) in enumerate(zip(joined, want))
                     if a != b), min(len(joined), len(want)))))
        sys.exit(4)
    print("0.0")
    print("validated order=%%s %%d records, %%d bytes exact"
          %% (order, len(recs), len(joined)), file=sys.stderr)
    raise SystemExit(0)

t0 = time.perf_counter()
out = forkrun.map(payload, path, workers=workers, nodes=1,
                  output="bytes", **kw)
records = [bytes(x) for x in out if x is not None]
got = b"".join(records)
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

# OUTPUT INTEGRITY, checked on every trial.
#
# Counting records is not enough: batch grouping varies, so a count
# asserts an implementation detail, and a failed run under skip/poison
# semantics exits 0 having produced nothing at all -- which is how the
# first version of this harness timed runs that returned no output.
#
# RECORD TILING, not concatenation and not a byte histogram.
#
# The round-8 review is right that `sorted(got) == sorted(want)` is a
# byte-value HISTOGRAM: it survives any permutation, including a full
# REVERSAL of the output, so within-batch corruption -- a batch
# assembled backwards -- passes it. Verified:
#
#     sorted(got[::-1]) == sorted(got)      -> True
#
# Two weaker candidates are also wrong here:
#   * concatenation -- with order="none" and >1 worker the batches
#     complete out of order BY DESIGN, so this "fails" a correct run on
#     ordering alone;
#   * line splitting -- splice moves BYTES, and a 32768-byte batch does
#     not align to line boundaries, so it reports 500001 lines where
#     the input has 500000.
#
# What is asserted instead: every emitted record must be a CONTIGUOUS
# slice of the expected output, and those slices must TILE it -- cover
# [0, len(want)) exactly once, with no gap, no overlap and no
# duplication, in whatever order they arrived.
#
# That is strictly stronger than the histogram and keeps the one thing
# the histogram got right: it says nothing about arrival ORDER, which
# order="none" does not promise. It catches a reversed batch, a
# transposed byte pair, a dropped batch and a duplicated one.
if not _records_tile(want, records):
    _report_tile_failure(want, records)
    sys.exit(3)

print("%%.6f" %% dt)
print("bytes=%%d rss_kb=%%d" %% (len(got), rss), file=sys.stderr)
'''

CODE = BODY % {"root": os.path.join(_ROOT, "python")}


def validate_ordered(path, mode, workers, lines, c_drain, cmd=None):
    """One byte-exact ORDERED run, before any timing is taken.

    The tiled check in the timed path proves completeness and
    within-record integrity while allowing arbitrary batch ORDER. That
    is the right invariant for order="none", but it is weaker than an
    exact comparison -- so this runs the same operation under
    order="index" and requires byte equality.

    If this fails the pipeline is not correct and every timing below is
    meaningless, so it aborts the benchmark rather than producing
    numbers. The round-8 review asked for exactly this: an ordered
    validation run for the strong claim, with the weaker invariant
    confined to the unordered timed runs.
    """
    env = dict(os.environ, FORKRUN_BENCH_VALIDATE_ONLY="1",
               FORKRUN_BENCH_ORDER="index")
    argv_extra = [path, mode, str(workers), str(lines),
                  "1" if c_drain else "0"]
    if cmd:
        argv_extra.extend(cmd.split())
    proc = subprocess.run([sys.executable, "-c", CODE] + argv_extra,
                          capture_output=True, timeout=900, env=env)
    if proc.returncode != 0:
        return proc.stderr.decode()[-400:]
    return None


def measure(path, mode, workers, lines, c_drain, cmd=None):
    times = []
    last_err = None
    last_meta = None
    for _ in range(TRIALS):
        argv_extra = [path, mode, str(workers), str(lines),
                      "1" if c_drain else "0"]
        if cmd:
            argv_extra.extend(cmd.split())
        proc = subprocess.run(
            [sys.executable, "-c", CODE] + argv_extra,
            capture_output=True, timeout=600)
        if proc.returncode != 0:
            last_err = proc.stderr.decode()[-200:]
            continue
        if proc.returncode != 0 or not proc.stdout.strip():
            last_err = (proc.stderr.decode()[-200:]
                        or "trial exited %d with no timing" % proc.returncode)
            return None, None, last_err
        times.append(float(proc.stdout.decode().strip()))
        last_meta = proc.stderr.decode().strip()
    if not times:
        return None, None, last_err
    # A median over the trials that happened to succeed is exactly the
    # shape of a benchmark that flatters the thing being measured. Any
    # failed trial discards the whole configuration.
    if len(times) != TRIALS:
        return None, None, ("only %d/%d trials succeeded -- %s"
                            % (len(times), TRIALS, last_err or ""))
    times.sort()
    return times[len(times) // 2], last_meta, None


def main():
    tmp = tempfile.mkdtemp()
    print("Stage 4 -- cleanroom splice measurement")
    print("median of %d trials; RSS is peak parent (ru_maxrss)\n" % TRIALS)

    # Ordered validation FIRST, before a single timing is taken.
    _probe = os.path.join(tmp, "validate.txt")
    with open(_probe, "w") as _fh:
        _fh.writelines("line %06d %s\n" % (i, "x" * 40) for i in range(2000))
    _err = validate_ordered(_probe, "splice", 4, 2000, True)
    if _err:
        print("ORDERED VALIDATION FAILED -- the pipeline is not correct, "
              "so\nno timing below means anything.\n%s" % _err,
              file=sys.stderr)
        return 4
    print("ordered validation (order='index', byte-exact): PASS")

    VARIANTS = [
        ("splice+c_drain", "splice", True, None),
        ("splice+py_drain", "splice", False, None),
        ("spawn cat       ", "spawn", False, "cat"),
        ("spawn tr        ", "spawn", False, "tr a-z A-Z"),
    ]

    rows = []
    for nlines in (50_000, 500_000):
        path = make_input(nlines, os.path.join(tmp, "in_%d.txt" % nlines))
        mb = os.path.getsize(path) / 1e6
        for workers in (1, 4):
            print("  %7d lines (%.1f MB) w=%d"
                  % (nlines, mb, workers))
            for label, mode, c_drain, cmd in VARIANTS:
                med, meta, err = measure(path, mode, workers, 32768,
                                         c_drain, cmd)
                rows.append((nlines, workers, label, med))
                print("      %s  %s"
                      % (label,
                         ("%8.4fs  %s" % (med, meta)) if med
                         else ("FAILED %s" % (err or "")[:80])))
            print()

    print("--- vs spawn cat (a real byte copy), same config ---")
    for nlines in (50_000, 500_000):
        for workers in (1, 4):
            base = next((m for n, w, l, m in rows
                         if n == nlines and w == workers
                         and l.startswith("spawn cat")), None)
            if not base:
                continue
            for n, w, l, m in rows:
                if n != nlines or w != workers or l.startswith("spawn cat"):
                    continue
                if not m:
                    continue
                print("  %7d lines w=%d  %s  %5.2fx  %s"
                      % (nlines, workers, l, base / m,
                         "faster" if base / m > 1.05 else
                         ("slower" if base / m < 0.95 else "~same")))


if __name__ == "__main__":
    main()
