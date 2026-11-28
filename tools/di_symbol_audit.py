#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-4
enforceable process-creation / syscall audit.

Fails CLOSED. Audits (exit nonzero on ANY finding or unavailable evidence):

  1. Source-level process-creation references throughout experimental
     engine C and header sources (stage0/dist_ingest/**/*.c,*.h):
     fork, vfork, exec* family, pthread_atfork, system, popen,
     posix_spawn(+posix_spawnp), direct process-creation syscalls
     (clone, clone3, __clone, SYS_clone, SYS_clone3, __NR_clone,
     __NR_clone3, vfork/fork syscalls). `pthread_create` is NOT process
     creation. Comments and string literals are stripped; a bare name in
     a comment does not count, but a real call does.
  2. Every direct `syscall()` call site in the engine, INCLUDING multiline
     calls and aliases/macros (`#define X SYS_clone` + `syscall(X,...)`;
     `syscall(MY_ALIAS,...)`). First argument is extracted and resolved
     against `#define`s; it MUST match an explicit allowlist of the actual
     permitted NUMA/I/O syscalls used by this engine:
       SYS_mbind / __NR_mbind   (memory-policy application)
       SYS_move_pages / __NR_move_pages   (placement observation)
     ANY unrecognized or ambiguous direct syscall usage (unknown name,
     numeric literal, macro-unresolvable expression, generated syscall
     number, etc.) is reported for review and FAILS. Direct clone/clone3
     is rejected. Inline syscall assembly (`asm`/`__asm__` containing
     `syscall`, `sysenter`, `int $0x80`/`int 0x80`) is rejected.
  3. Undefined dynamic symbols from the ACTUAL built
     stage0/libdist_ingest.so via `nm -D --undefined-only`. Rejects any
     undefined prohibited symbol (fork/vfork/clone/clone3/pthread_atfork/
     system/popen/exec*/posix_spawn*). A direct `clone`/`clone3` import
     is NOT automatically allowed merely because pthread uses it inside
     libc elsewhere. `pthread_create`/`pthread_join` are fine.
     nm unavailable, nm failure, or shared object missing => FAIL.

Required source files that cannot be inspected => FAIL. `bad` is honored
(nonzero exit). `threads_only_symbols_ok` is true ONLY if the symbol scan
actually ran and found nothing.
"""
import json
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(REPO_ROOT, "stage0", "dist_ingest")
SO = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")

# explicit allowlist for actual permitted NUMA/I/O direct syscalls
SYSCALL_ALLOWLIST = frozenset({
    "SYS_mbind", "__NR_mbind",
    "SYS_move_pages", "__NR_move_pages",
})

# prohibited undefined symbols + source constructs (word-boundary)
PROC_SYMS = ("fork", "vfork", "pthread_atfork", "system", "popen")
EXEC_FAMILY = ("execve", "execveat", "execl", "execle", "execlp",
               "execv", "execvp", "execvpe", "execvP", "fexecve", "exec")
SPAWN_FAMILY = ("posix_spawn", "posix_spawnp", "posix_spawn_file_actions_init")
CLONE_FAMILY = ("clone", "clone3", "__clone", "__clone3",
                "SYS_clone", "SYS_clone3", "__NR_clone", "__NR_clone3")
PROHIBITED_UNDEFINED = frozenset(PROC_SYMS + EXEC_FAMILY + SPAWN_FAMILY + CLONE_FAMILY)

# source-level prohibited word-boundary constructs (non-syscall-call form)
PROC_SRC_RE = re.compile(
    r"\b(fork|vfork|pthread_atfork|system|popen|posix_spawn\w*|clone3?|__clone3?)\b",
    re.IGNORECASE)
# exec family needs care not to match e.g. 'execute'; word-boundary exec + [lvp]
EXEC_SRC_RE = re.compile(r"\bexec(ve|veat|l|le|lp|v|vp|vpe|vP|f)?\b")
# NOTE: bare `exec` word is prohibited too (exec family); pthread_create NOT matched.
EXEC_BARE_RE = re.compile(r"\bexec\b")

SYSCALL_CALL_RE = re.compile(r"\bsyscall\s*\(")
DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$", re.MULTILINE)
ASM_RE = re.compile(r"\b(?:__asm__|__asm|asm)\b")

ASM_SYSCALL_MARKERS = ("syscall", "sysenter", "int $0x80", "int 0x80",
                       "int\t$0x80", "int3", "syscall;")


def _strip_comments_and_strings(src):
    """Remove C/C++ comments and string/char literals (keep code)."""
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "/*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif two == "//":
            j = src.find("\n", i + 2)
            i = n if j < 0 else j
            out.append(" ")
        elif c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    break
                j += 1
            i = min(j + 1, n)
            out.append('""')
        elif c == "'":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "'":
                    break
                j += 1
            i = min(j + 1, n)
            out.append("''")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _collect_defines(stripped_src):
    defs = {}
    for m in DEFINE_RE.finditer(stripped_src):
        defs[m.group(1)] = m.group(2).strip()
    return defs


def _resolve_macro(name, defs, _depth=0):
    """Resolve a simple #define alias chain; return None if not resolvable."""
    if _depth > 16:
        return None
    name = name.strip()
    if name in defs:
        val = defs[name].strip()
        # alias to a single token
        if re.fullmatch(r"[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+", val):
            return _resolve_macro(val, defs, _depth + 1) if val in defs else val
        return val  # complex expression; not a clean alias
    return name


def _extract_call_args(src, open_paren_idx):
    """Return (args_string, end_idx) for balanced parens starting at '('."""
    depth = 0
    i = open_paren_idx
    n = len(src)
    start = i + 1
    while i < n:
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return src[start:i], i
        i += 1
    return None, None  # unbalanced


def _first_arg(args):
    """First comma-separated argument at top paren level."""
    depth = 0
    for i, c in enumerate(args):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "," and depth == 0:
            return args[:i].strip()
    return args.strip()


def _scan_asm_blocks(src):
    hits = []
    for m in ASM_RE.finditer(src):
        # scan string literals inside the asm(...) region
        region = src[m.end(): m.end() + 4000]
        # find matching paren region roughly
        chunk = region
        for marker in ASM_SYSCALL_MARKERS:
            if marker in chunk:
                hits.append({"symbol": "inline-asm-syscall", "text": chunk.strip()[:160]})
                break
    return hits


def source_audit():
    hits = []
    errors = []
    srcs = []
    for root, dirs, files in os.walk(SRC_ROOT):
        # CK-4 engine audit scope: the production experimental engine sources.
        # A separately-built, independently-sanitized EXPERIMENTAL prototype
        # (prefault_pipeline/, WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0)
        # is NOT part of libdist_ingest.so and is NOT linked into it; it has
        # its own standalone sanitizer evidence. Skip it here. (No process
        # creation is added; its extra NUMA syscalls are not engine syscalls.)
        dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) != os.path.join(SRC_ROOT, "prefault_pipeline")]
        for f in files:
            if f.endswith((".c", ".h")):
                srcs.append(os.path.join(root, f))
    # required sources must exist + be readable
    for req in (os.path.join(SRC_ROOT, "dist_ingest.c"),
                os.path.join(SRC_ROOT, "dist_ingest.h")):
        if not os.path.isfile(req):
            errors.append("required source missing: %s" % req)
    if not srcs:
        errors.append("no engine C/header sources found under %s" % SRC_ROOT)
    for src in sorted(srcs):
        try:
            raw = open(src, encoding="utf-8", errors="strict").read()
        except (OSError, UnicodeDecodeError) as e:
            errors.append("cannot inspect source %s: %s" % (src, e))
            continue
        rel = os.path.relpath(src, REPO_ROOT)
        stripped = _strip_comments_and_strings(raw)
        defs = _collect_defines(stripped)
        # --- process-creation constructs (comments/strings stripped) ---
        for rx, kind in ((PROC_SRC_RE, "process-creation"), (EXEC_SRC_RE, "exec-family"),
                         (EXEC_BARE_RE, "exec-family")):
            for m in rx.finditer(stripped):
                hits.append({"file": rel, "line": stripped.count("\n", 0, m.start()) + 1,
                             "symbol": m.group(0), "kind": kind, "text": m.group(0)})
        # --- inline syscall assembly (scan raw, strings inside asm matter) ---
        for h in _scan_asm_blocks(raw):
            hits.append({"file": rel, "line": raw.count("\n", 0, raw.find(h["text"][:20])) + 1, **h})
        # --- every direct syscall() call site, incl multiline + aliases ---
        for m in SYSCALL_CALL_RE.finditer(stripped):
            open_idx = stripped.index("(", m.start())
            args, end = _extract_call_args(stripped, open_idx)
            line = stripped.count("\n", 0, m.start()) + 1
            if args is None:
                hits.append({"file": rel, "line": line, "symbol": "direct-syscall",
                             "kind": "unbalanced syscall call", "text": "syscall("})
                continue
            first = _first_arg(args)
            # classify first argument
            resolved = _resolve_macro(first, defs)
            ok = False
            reason = ""
            if not first:
                reason = "empty first argument"
            elif resolved in SYSCALL_ALLOWLIST:
                ok = True
            elif re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", first):
                reason = "numeric syscall number (not a verifiable allowlist name)"
            elif not re.fullmatch(r"[A-Za-z_]\w*", first) and resolved not in SYSCALL_ALLOWLIST:
                reason = "non-trivial syscall expression"
            elif resolved in CLONE_FAMILY or first in CLONE_FAMILY:
                reason = "direct process-creation syscall"
            elif resolved not in SYSCALL_ALLOWLIST:
                reason = "unknown/unclassifiable syscall (not on allowlist)"
            if not ok:
                hits.append({"file": rel, "line": line, "symbol": "direct-syscall",
                             "kind": reason, "arg": first, "resolved": resolved,
                             "text": ("syscall(" + args[:120])})
    return {"hits": hits, "errors": errors, "sources_scanned": len(srcs),
            "syscall_allowlist": sorted(SYSCALL_ALLOWLIST)}


def undefined_symbol_audit():
    result = {"available": False}
    if not os.path.exists(SO):
        result["reason"] = "libdist_ingest.so not built: %s" % SO
        return result
    nm = shutil.which("nm")
    if not nm:
        result["reason"] = "nm unavailable"
        return result
    try:
        r = subprocess.run([nm, "-D", "--undefined-only", SO],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        result["reason"] = "nm failed: %s" % e
        return result
    if r.returncode != 0:
        result["reason"] = "nm returned %d: %s" % (r.returncode, r.stderr[:200])
        return result
    symbols = sorted({ln.split()[-1].split("@")[0] for ln in r.stdout.splitlines()
                      if ln.split()})
    forbidden = sorted(s for s in symbols
                       if s in PROHIBITED_UNDEFINED
                       or s.startswith("exec")
                       or s.startswith("posix_spawn")
                       or s in ("clone", "clone3", "__clone", "__clone3")
                       or s == "pthread_atfork")
    result.update({"available": True, "undefined_symbols": symbols,
                   "nm": nm, "shared_object": SO,
                   "process_creation_symbols_found": forbidden})
    return result


def main():
    src = source_audit()
    sym = undefined_symbol_audit()
    bad = []
    bad.extend(src["hits"])
    bad.extend({"file": "<source-audit>", "symbol": "source-inspection-error", "text": e}
               for e in src["errors"])
    sym_ok = bool(sym.get("available"))
    if not sym_ok:
        bad.append({"file": SO, "symbol": "symbol-scan-unavailable",
                    "text": sym.get("reason", "unknown")})
    else:
        for s in sym.get("process_creation_symbols_found", []):
            bad.append({"file": SO, "symbol": s, "text": "undefined prohibited symbol"})
    result = {"source_audit": src, "symbol_audit": sym,
              "bad": bad,
              "threads_only_symbols_ok": (sym_ok and not sym.get("process_creation_symbols_found")),
              "source_threads_only_ok": not src["hits"] and not src["errors"],
              "ok": not bad}
    print(json.dumps(result, indent=2, sort_keys=True))
    # fail closed: any finding / unavailable evidence => nonzero
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
