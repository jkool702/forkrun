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
if payload is not None and payload[0] == "tr":
    # tr a-z A-Z: faithful byte translation, not a targeted replace.
    # An earlier version only uppercased the literal "line", so a correct
    # run "failed" on content the command genuinely changes.
    want = want.translate(bytes.maketrans(
        b"abcdefghijklmnopqrstuvwxyz", b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

t0 = time.perf_counter()
out = forkrun.map(payload, path, workers=workers, nodes=1,
                  output="bytes", **kw)
got = b"".join(bytes(x) for x in out if x is not None)
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

# OUTPUT INTEGRITY, checked on every trial.
#
# Counting records is not enough: batch grouping varies, so a count
# asserts an implementation detail, and a failed run under skip/poison
# semantics exits 0 having produced nothing at all -- which is how the
# first version of this harness timed runs that returned no output.
#
# Compared as a BYTE MULTISET, not concatenated and not line-wise.
#
# Both simpler invariants are wrong here:
#   * concatenation -- with order="none" and >1 worker the batches
#     complete out of order by design, so this "fails" a correct run on
#     ordering alone;
#   * line splitting -- splice moves BYTES, and a 32768-byte batch does
#     not align to line boundaries, so it reports 500001 lines where
#     the input has 500000.
#
# The multiset answers only what this benchmark should care about: every
# byte arrived, and no byte was invented. Ordering is a separate promise,
# covered by the order="index" suites, and is NOT claimed here.
if sorted(got) != sorted(want):
    from collections import Counter
    cg, cw = Counter(got), Counter(want)
    diff = (cw - cg) or (cg - cw)
    sys.stderr.write("OUTPUT MISMATCH: %%d bytes got vs %%d want; "
                     "first differing byte 0x%%02x (%%d vs %%d)\n"
                     %% (len(got), len(want),
                        min(diff) if diff else 0,
                        diff.get(min(diff), 0) if diff else 0,
                        cw.get(min(diff), 0) if diff else 0))
    sys.exit(3)

print("%%.6f" %% dt)
print("bytes=%%d rss_kb=%%d" %% (len(got), rss), file=sys.stderr)
'''

CODE = BODY % {"root": os.path.join(_ROOT, "python")}


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
