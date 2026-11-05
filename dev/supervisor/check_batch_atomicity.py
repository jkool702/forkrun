#!/usr/bin/env python3
"""Check batch atomicity across a worker death, per failure policy.

    python3 dev/supervisor/check_batch_atomicity.py

Prints what the engine actually does and whether it matches the contract
`frun.bash` implements: a batch is ATOMIC, its partial output is rolled
back out of the output memfd, and the batch is re-run IN FULL.

    retry   the batch is re-run in full      -> byte-exact output
    skip    the batch yields no result       -> exactly one batch absent,
                                               remainder contiguous

This exists because a suite run under `on_error="skip"` was once read as
silent data loss (see BUGS.md). The loss was the contract. Printing both
policies side by side makes that visible in one command, which is cheaper
than deriving it from a single failing assertion.

Exits 0 if the engine matches the contract, 1 if it does not.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, os.pardir, "python"))

LINES = 20
BATCH_BYTES = 128
UPPER = bytes.maketrans(b"abcdefghijklmnopqrstuvwxyz",
                        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ")
PARTIAL = b"PARTIALJUNKTHATWASROLLBACK"

# Emits partial output and THEN dies. The partial bytes are the probe: if
# any survive, a caller can observe torn batch output.
PROBE = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    printf '%s'
    kill -9 $$
fi
exec tr a-z A-Z
""" % PARTIAL.decode()


def skipped_batches(want, got, batch):
    """Offsets of whole input batches absent from `got`, plus a flag for
    whether `got` is fully accounted for.

    `got` must be walkable by taking input batches in order and deciding
    for each whether it appears or was dropped. Deliberately does not
    assume HOW MANY batches are dropped: with one worker that is one,
    but a death among several workers can take more than one batch with
    it. The final window is clamped because it is ragged.
    """
    gi = 0
    skipped = []
    pos = 0
    while pos < len(want):
        end = min(pos + batch, len(want))
        if got[gi:gi + (end - pos)] == want[pos:end]:
            gi += end - pos
        else:
            skipped.append(pos)
        pos = end
    return skipped, gi == len(got)


def main():
    import forkrun

    tmp = tempfile.mkdtemp(prefix="check-atomicity-")
    src = os.path.join(tmp, "in.txt")
    with open(src, "w") as fh:
        fh.writelines("line%06d payload\n" % i for i in range(LINES))
    probe = os.path.join(tmp, "probe.sh")
    with open(probe, "w") as fh:
        fh.write(PROBE)
    os.chmod(probe, 0o755)

    data = open(src, "rb").read()
    want = data.translate(UPPER)

    print("batch atomicity across a worker death")
    print("  %d lines, %d-byte batches, probe emits %d partial bytes "
          "before dying\n" % (LINES, BATCH_BYTES, len(PARTIAL)))

    ok = True
    for on_error in ("retry", "skip"):
        for workers in (1, 2):
            os.environ["FR_DIE_MARKER"] = os.path.join(
                tmp, "marker.%s.%d" % (on_error, workers))
            os.environ["FORKRUN_CLEANROOM"] = "1"
            recs = [bytes(x) for x in forkrun.map(
                probe, src, mode="spawn", workers=workers, nodes=1,
                order="index", bytes=BATCH_BYTES, output="bytes",
                orchestrator=True, on_error=on_error) if x is not None]
            got = b"".join(recs)

            died = os.path.exists(os.environ["FR_DIE_MARKER"])
            leaked = PARTIAL in got

            if on_error == "retry":
                verdict = "exact" if got == want else "MISMATCH"
                good = got == want
            else:
                skipped, consumed = skipped_batches(want, got, BATCH_BYTES)
                verdict = ("contiguous remainder, %d batch(es) dropped%s"
                           % (len(skipped),
                              "" if consumed else " [UNACCOUNTED BYTES]"))
                good = bool(skipped) and consumed

            if not died or leaked or not good:
                ok = False
            print("  on_error=%-5s workers=%d  records=%-16s partial_leaked="
                  "%-5s  %s%s"
                  % (on_error, workers,
                     str([len(r) for r in recs])[:16], str(leaked), verdict,
                     "" if died else "   [NO DEATH OCCURRED]"))

    print()
    if ok:
        print("CONFORMS: the batch was re-run in full or dropped whole,")
        print("partial output was rolled back in both policies, and the")
        print("remainder is contiguous. See dev/supervisor/BUGS.md for the")
        print("false alarm this replaced.")
        return 0
    print("VIOLATION: batch atomicity does not hold. See the rows above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
