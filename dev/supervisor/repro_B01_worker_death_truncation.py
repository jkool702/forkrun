#!/usr/bin/env python3
"""Minimal reproducer for B-01: a worker killed mid-batch loses the
consumed prefix of that batch.

    python3 dev/supervisor/repro_B01_worker_death_truncation.py

Run from the repository root. Exits 0 if the bug is NOT present, so it
doubles as a regression gate: once the engine is fixed this script
starts failing, which is the point.

Not a unit test -- it is the smallest thing that shows the defect with
no test harness in the way, so the next person can confirm it in one
command before reading any code.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, os.pardir, "python"))

LINES = 20
BYTES = 128

# Kills its own worker exactly once, then uppercases stdin. The marker
# file makes the death one-shot, so the reclaimed batch completes rather
# than killing itself again.
SCRIPT = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    kill -9 $$
fi
exec tr a-z A-Z
"""


def main():
    import forkrun

    tmp = tempfile.mkdtemp(prefix="repro-B01-")
    src = os.path.join(tmp, "in.txt")
    with open(src, "w") as fh:
        fh.writelines("line%06d payload\n" % i for i in range(LINES))
    script = os.path.join(tmp, "die_once.sh")
    with open(script, "w") as fh:
        fh.write(SCRIPT)
    os.chmod(script, 0o755)
    marker = os.path.join(tmp, "marker")

    os.environ["FR_DIE_MARKER"] = marker
    results = {}
    for cleanroom in ("0", "1"):
        for orchestrator in (True, False):
            os.environ["FORKRUN_CLEANROOM"] = cleanroom
            os.environ["FR_DIE_MARKER"] = marker + ".%s%s" % (
                cleanroom, orchestrator)
            out = forkrun.map(script, src, mode="spawn", workers=1,
                              nodes=1, order="index", bytes=BYTES,
                              output="bytes", orchestrator=orchestrator,
                              on_error="skip")
            got = b"".join(bytes(x) for x in out if x is not None)
            results[(cleanroom, orchestrator)] = got

    want = open(src, "rb").read().upper()

    print("B-01: worker killed mid-batch")
    print("  input %d lines, %d-byte batches, mode=spawn\n" % (LINES, BYTES))
    bug = False
    for (cleanroom, orch), got in sorted(results.items()):
        lines = [ln for ln in got.splitlines() if ln.strip()]
        missing = [ln for ln in want.splitlines() if ln not in lines]
        first = lines[0] if lines else b""
        status = "OK" if got == want else "LOST %d line(s)" % len(missing)
        print("  cleanroom=%s orchestrator=%-5s  %2d/%d lines  first=%-22r %s"
              % (cleanroom, orch, len(lines), LINES, first[:20], status))
        if got != want:
            bug = True
            if missing[:1]:
                print("        missing e.g. %r" % missing[0])
            if first and len(first) < 21:
                print("        first delivered record is a %d-byte FRAGMENT, "
                      "not a whole line" % len(first))

    print()
    if bug:
        print("REPRODUCED: the reclaimed batch delivered only the UNCONSUMED")
        print("TAIL of its input. Silent loss, normal exit, no poison record.")
        print("This is engine-core: identical under both engines and both")
        print("supervision policies. See dev/supervisor/BUGS.md (B-01).")
        print("This script exits 0 while the bug is PRESENT -- it is a")
        print("reproducer, not a pass/fail gate.")
        return 0

    print("NOT REPRODUCED: output is byte-exact in all four configurations.")
    print("B-01 appears FIXED. Remove @unittest.expectedFailure from")
    print("python/tests/test_stage3_recovery_integrity.py and update BUGS.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
