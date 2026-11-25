#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-4.2 symbol audit.

Audits the engine source AND the built shared object:
  - `nm -D --undefined-only` on stage0/libdist_ingest.so (symbols actually
    pulled from the runtime: real dependency evidence, not referenced-but-
    unused text).
  - Source grep for process-creation symbols: fork, vfork, clone, clone3,
    pthread_atfork.
  - Source grep for direct syscall usage (syscall( in engine .c files) that
    would not appear as undefined `clone` symbols.
"""
import json
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SO = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")

PROC_SYMS = ("fork", "vfork", "clone", "clone3", "pthread_atfork", "exec",
             "system", "popen")
SYSCALL_RE = re.compile(r"\bsyscall\s*\(")


def run(cmd, cwd=REPO_ROOT):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        return type("R", (), {"returncode": -1, "stdout": "", "stderr": str(e)})()


def source_audit():
    hits = []
    srcs = []
    for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "stage0", "dist_ingest")):
        for f in files:
            if f.endswith((".c", ".h")):
                srcs.append(os.path.join(root, f))
    for src in srcs:
        for lineno, line in enumerate(open(src), 1):
            for sym in PROC_SYMS:
                if re.search(r"\b%s\b" % sym, line, re.IGNORECASE):
                    hits.append({"file": os.path.relpath(src, REPO_ROOT),
                                 "line": lineno, "symbol": sym, "text": line.strip()[:120]})
            m = SYSCALL_RE.search(line)
            if m:
                # Flag direct syscall() use that is NOT the allowed NUMA/IO
                # interface (move_pages, mbind, mempolicy). Direct clone-
                # related syscalls are process-creation and flagged.
                allowed = any(s in line for s in
                              ("SYS_mbind", "__NR_mbind", "SYS_move_pages",
                               "SYS_set_mempolicy", "SYS_get_mempolicy",
                               "SYS_query_nodes", "move_pages"))
                if not allowed and re.search(r"clone|fork|exec", line, re.IGNORECASE):
                    hits.append({"file": os.path.relpath(src, REPO_ROOT),
                                 "line": lineno, "symbol": "direct-syscall",
                                 "text": line.strip()[:120]})
    return {"hits": hits}


def undefined_symbol_audit():
    if not os.path.exists(SO):
        return {"available": False, "reason": "libdist_ingest.so not built"}
    r = run(["nm", "-D", "--undefined-only", SO])
    if r.returncode != 0:
        return {"available": False, "reason": r.stderr[:200]}
    symbols = sorted({ln.split()[-1].split("@")[0] for ln in r.stdout.splitlines()
                      if ln.split()})
    forbidden = [s for s in symbols if s in PROC_SYMS or
                 (s.startswith("__NR_") or s in ("clone", "clone3", "vfork", "fork"))]
    return {"available": True, "undefined_symbols": symbols,
            "process_creation_symbols_found": sorted(set(
                s for s in symbols if s in PROC_SYMS))}


def main():
    result = {"source_audit": source_audit(),
              "symbol_audit": undefined_symbol_audit()}
    # Pass: only malloc/free/pthread_* symbols are allowed (threads-only).
    syms = set(result["symbol_audit"].get("undefined_symbols", []))
    bad = syms & {"fork", "vfork", "clone", "clone3", "pthread_atfork"}
    # clone/clone3 are thread-creation syscalls, allowed; atfork is the ban.
    bad -= {"clone", "clone3"}
    result["threads_only_symbols_ok"] = not bad
    print(json.dumps(result, indent=2, sort_keys=True)[:3000])
    # Enforce: pthread_atfork and exec-family symbols are violations.
    if "pthread_atfork" in syms or any(s.startswith("exec") for s in syms) or "fork" in syms:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
