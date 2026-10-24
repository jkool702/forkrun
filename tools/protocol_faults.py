"""Fault injection for the child-memory protocol.

The round-11 review asked for exactly this:

> The best test is a protocol-focused harness that deliberately injects
> short reads, interrupted system calls, a missing child, a duplicate
> report, a truncated record, and a child exit before the barrier. Each
> must fail explicitly, not yield a plausible-looking memory figure.

That request was made after two protocol bugs shipped in this file. The
second one -- both ends of the barrier pipe used backwards, with EBADF
discarded by `(void)` -- produced confident, wrong numbers and no error
at all. So "it did not crash" is exactly the wrong bar here.

Each mode below drives `fr_udf_fork` with one fault forced and asserts
the driver either reports the fault or discards the sample. The default
is that a fault must be **visible**: a run that produces a plausible
fleet figure while a fault is active is the failure this file exists to
catch.

Usage: python3 tools/protocol_faults.py [--driver PATH]
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DRIVER = os.path.join(_ROOT, "python", "forkrun", "fr_udf_fork")

UDF_SRC = '''\
_TOUCHED = [False]
def up(b):
    return b.upper()
def touch(b):
    _TOUCHED[0] = True
    return b"y"
def is_touched(b):
    return b"yes" if _TOUCHED[0] else b"no"
'''

# (mode, env, must-show regex or None, must-NOT-show regex or None)
#
# "must show None" means the fault is expected to be SILENT but the run
# must still be refused -- the integrity counters are the mechanism.
MODES = [
    # A child that never reaches the barrier: its ack never arrives, so
    # the barrier is incomplete and the PSS divisor for everyone else is
    # wrong. Must be counted, not absorbed.
    ("FR_FAULT_NO_ACK", "no-ack", r"no barrier ack", None),

    # A child that dies before writing its report. Must not hang the
    # parent -- EOF has to be reachable -- and must be counted.
    ("FR_FAULT_DIE_BEFORE_REPORT", "die-before-report", r"BAD REPORT|no barrier ack", None),

    # A report carrying the wrong version: rejected by identity, not
    # parsed anyway.
    ("FR_FAULT_BAD_VERSION", "bad-version", r"BAD REPORT", None),

    # A report carrying the wrong pid: the report exists but is not from
    # the child being waited for.
    ("FR_FAULT_BAD_PID", "bad-pid", r"BAD REPORT", None),

    # A truncated record: the child writes half a struct. read_all must
    # treat the short tail as an error, not as a report.
    ("FR_FAULT_TRUNCATED", "truncated", r"BAD REPORT", None),

    # A duplicated report: the child writes its struct twice. The second
    # must not be counted, and the extra bytes must not be mistaken for
    # the next child's record.
    ("FR_FAULT_DUPLICATE", "duplicate",
     r"trailing byte|BAD REPORT|no barrier ack", None),

    # A child that exits before the barrier releases at all.
    ("FR_FAULT_EXIT_BEFORE_BARRIER", "exit-before-barrier",
     r"no barrier ack|BAD REPORT", None),

    # A failure to release: the gate write fails.
    ("FR_FAULT_RELEASE_FAIL", "release-fail", r"RELEASE FAILED|BAD REPORT|no barrier ack", None),
]


def make_root():
    d = tempfile.mkdtemp(prefix="protofault-")
    with open(os.path.join(d, "myudf.py"), "w") as fh:
        fh.write(UDF_SRC)
    return d


def run(driver, root, env_extra, timeout=120):
    env = dict(os.environ)
    env.update(env_extra)
    try:
        p = subprocess.run([driver, root, "myudf:up", "3", "20"],
                           capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return None, "", "TIMED OUT -- the parent blocked"
    return p.returncode, p.stdout.decode(errors="replace"), \
        p.stderr.decode(errors="replace")


def check(driver, root):
    """Baseline first: with no fault, the run must be clean.

    Without this, a harness where the driver is simply broken in every
    mode would 'pass' every fault assertion.
    """
    rc, out, err = run(driver, root, {})
    problems = []
    if rc is None:
        return ["baseline: the driver hangs with NO fault injected"], []
    if rc != 0:
        problems.append("baseline: driver exited %d" % rc)
    if "integrity: 0 missing ack(s), 0 failed release(s), 0 bad report(s)" \
            not in out:
        problems.append("baseline: integrity line missing or non-zero")
    if "VERDICT" not in out:
        problems.append("baseline: no verdict")
    return problems, [("baseline", out, err)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default=DEFAULT_DRIVER)
    args = ap.parse_args()
    driver = args.driver

    if not os.path.exists(driver):
        print("driver not built: make -f Makefile.substrate udf-fork",
              file=sys.stderr)
        return 2

    root = make_root()
    print("protocol fault injection")
    print("  driver: %s" % driver)
    print("  baseline: a clean run must be clean, or nothing below means "
          "anything\n")

    failures, _ = check(driver, root)
    for f in failures:
        print("  FAIL %s" % f)

    print("\n  %-28s %-10s %s" % ("fault", "result", "detail"))
    print("  " + "-" * 74)

    for var, label, must_show, must_not in MODES:
        rc, out, err = run(driver, root, {var: "1"})
        if rc is None:
            print("  %-28s %-10s %s" % (label, "HUNG",
                                         "parent blocked; a fault must never "
                                         "hang the run"))
            failures.append("%s: hung" % label)
            continue
        blob = out + err
        if must_show and not re.search(must_show, blob):
            print("  %-28s %-10s %s" % (label, "UNREPORTED",
                                         "expected /%s/ but the fault was "
                                         "not surfaced" % must_show))
            failures.append("%s: fault not reported" % label)
            continue
        # The real test: a fault that is reported must ALSO stop the
        # figure being presented as trustworthy.
        m = re.search(r"integrity: (\d+) missing ack\(s\), (\d+) failed "
                      r"release\(s\), (\d+) bad report\(s\)", out)
        counted = 0
        if m:
            counted = int(m.group(1)) + int(m.group(2)) + int(m.group(3))
        if counted == 0 and rc == 0 and "fleet memory" in out:
            print("  %-28s %-10s %s" % (label, "UNCLEAR",
                                         "fleet figure printed with zero "
                                         "integrity faults counted"))
            failures.append("%s: fault neither counted nor fatal" % label)
            continue
        print("  %-28s %-10s %d integrity fault(s) counted"
              % (label, "OK", counted))

    print()
    if failures:
        print("FAILED: %d problem(s)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("PASS: every injected fault was reported or invalidated the "
          "sample.\nNo fault produced a plausible fleet figure while "
          "silently\nabsorbing the error -- which is how the shipped bug "
          "behaved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())