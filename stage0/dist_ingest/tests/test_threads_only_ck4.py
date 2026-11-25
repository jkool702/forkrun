#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-4 guard test.

The experimental dist_ingest engine must remain threads-only: no fork(),
exec*, system, popen, socket/bind/listen — any process-creation syscall in
the engine is a CK-4 regression.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
C_FILES = [os.path.join(ROOT, "stage0", "dist_ingest", "dist_ingest.c"),
           os.path.join(ROOT, "stage0", "dist_ingest", "dist_ingest.h")]

FORBIDDEN = re.compile(r"\bfork\b|\bexec[lvp]*\b|\bsystem\b|\bpopen\b|"
                       r"\bsocket\b|\bconnect\b|\baccept\b|\bbind\b|\blisten\b|\bselect\b",
                       re.IGNORECASE)


class TestThreadsOnly(unittest.TestCase):
    def test_no_process_creation_or_network_symbols(self):
        for path in C_FILES:
            with open(path) as f:
                text = f.read()
            hits = [l for l in text.splitlines()
                    if FORBIDDEN.search(l) and not l.strip().startswith("*")
                    and "//" not in l.split("fork")[0][:1]]
            self.assertFalse(hits, "%s contains process/network symbols: %s"
                             % (path, hits[:3]))


if __name__ == "__main__":
    unittest.main()
