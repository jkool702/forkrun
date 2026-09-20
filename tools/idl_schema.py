"""Stage 3.0 IDL schema — single source for the typed-boundary scaffolding.

v1.3 plan section 2.2: three schemas, one generation pipeline. This module
is the call-schema half of that pipeline (call-args direction/optionality;
state-ownership lives in docs_port/OWNERSHIP.md; doc-metadata rides the
usage/doc strings below).

In v3.5.2 this is ANNOTATION-ONLY scaffolding: every loadable is
ARGC_ARGV (current behavior — string argv, no thunk calling). The
convention column exists so Stage 3 flips are per-function commits
(migration order: ring_claim -> ring_ack -> ring_call -> ring_poll);
no function flips here, no fr_call_t yet, no usage-string changes
(tools/gen_idl.py's usage output must match the engine strings exactly).

Conventions for readers:
- SCHEMA maps loadable name -> {convention, usage, doc, fields}.
- usage/doc are copied VERBATIM from FORKRUN_LOADABLES in forkrun_ring.c;
  tools/test_idl.py enforces equality textually (the engine is frozen,
  so the test parses rather than includes).
- fields are (direction, type, name, optional) tuples. Only the four
  migration-order functions carry field lists in v3.5.2 (best-effort,
  documented below); the rest are convention-only until demand pulls them.
- parse_engine_table() is the string-aware FORKRUN_LOADABLES parser shared
  by the generator check and the tests.
"""

from __future__ import annotations

import re

# Calling conventions (mirror fr_convention_t in the generated header).
ARGC_ARGV = "ARGC_ARGV"
THUNK = "THUNK"
BASH_ONLY = "BASH_ONLY"

# Migration order (v1.3 section 5.4). Stage 3 flips in this order.
MIGRATION_ORDER = ("ring_claim", "ring_ack", "ring_call", "ring_poll")

# Field = (direction, type, name, optional).
# direction: IN (argv -> engine) / OUT (engine -> bash bind) / LOCAL
#   (worker-side scratch, e.g. the EXIT-trap escrow gate variable).
# type: I32 / U32 / U64 / U8 / STR / PTR (PTR pairs with a length field).

# ring_claim [VAR] — the v1.3 sketch's own example (OUT binds), plus the
# optional VAR target-name input. Scaffolding-grade types; Stage 3 refines.
_CLAIM_FIELDS = (
    ("IN", "STR", "var_name", True),
    ("OUT", "U32", "REPLY", False),
    ("OUT", "U32", "RING_NUM_KILLS", False),
    ("OUT", "U32", "RING_POISONED", False),
    ("OUT", "U64", "RING_BATCH_IDX", False),
    ("LOCAL", "U64", "FRUN_CLAIM_BYTES", False),
)

# ring_ack <FD> <FD_OUT> — fd_fallow required; fd_target optional
# (argc>=3 else -1: realtime/unordered path skips the order pipe).
_ACK_FIELDS = (
    ("IN", "I32", "fd_fallow", False),
    ("IN", "I32", "fd_target", True),
)

# ring_call <fd> <len> <delim> <so> <fn> [fixed...] — fixed_argc + fixed
# form the PTR+LEN pair the plan requires from v1.
_CALL_FIELDS = (
    ("IN", "I32", "fd", False),
    ("IN", "U64", "length", False),
    ("IN", "U8", "delim", False),
    ("IN", "STR", "so", False),
    ("IN", "STR", "fn", False),
    ("IN", "I32", "fixed_argc", False),
    ("IN", "PTR", "fixed", False),
)

# ring_poll <spawn_fd> <scan_arr> <work_arr> [timer] [trap_ack]
# [indexer_arr] — fd + array-name inputs, trailing three optional.
_POLL_FIELDS = (
    ("IN", "I32", "spawn_fd", False),
    ("IN", "STR", "scan_arr", False),
    ("IN", "STR", "work_arr", False),
    ("IN", "I32", "timer", True),
    ("IN", "I32", "trap_ack", True),
    ("IN", "STR", "indexer_arr", True),
)


def _e(convention, usage, doc, fields=()):
    return {"convention": convention, "usage": usage, "doc": doc,
            "fields": fields}


# NOTE: usage/doc verbatim from FORKRUN_LOADABLES (forkrun_ring.c).
SCHEMA = {
    "ring_map": _e(ARGC_ARGV, "ring_map <fd> <len> <array> [delim]",
                   "Fast user-space mapfile"),
    "ring_exec": _e(ARGC_ARGV,
                    "ring_exec <fd> <len> <delim> <cmd> [args...]",
                    "Ultra-fast execution of external binaries"),
    "ring_exec_splice": _e(ARGC_ARGV,
                           "ring_exec_splice <fd> <len> <cmd> [args...]",
                           "Spawn binary and splice to its stdin"),
    "ring_call": _e(ARGC_ARGV, "ring_call <fd> <len> <delim> <so> <fn>",
                    "Zero-Tax C Plugin Execution", _CALL_FIELDS),
    "ring_is_spawnable": _e(ARGC_ARGV, "ring_is_spawnable <file>",
                            "Check if file is binary or has shebang"),
    "ring_init": _e(ARGC_ARGV, "ring_init [FLAGS]",
                    "Initialize ring with config"),
    "ring_destroy": _e(ARGC_ARGV, "ring_destroy", "Destroy ring"),
    "ring_scanner": _e(ARGC_ARGV, "ring_scanner <fd> [spawn_fd]",
                       "Run unified legacy scanner"),
    "ring_numa_ingest": _e(ARGC_ARGV,
                           "ring_numa_ingest <infd> <outfd> <nodes> [ordered]",
                           "Run NUMA topological ingest"),
    "ring_indexer_numa": _e(ARGC_ARGV, "ring_indexer_numa <memfd> <node_id>",
                            "Run NUMA chunk indexer"),
    "ring_numa_scanner": _e(
        ARGC_ARGV, "ring_numa_scanner <memfd> <node_id> <spawn_fd> <nodes>",
        "Run unified NUMA scanner"),
    "ring_claim": _e(ARGC_ARGV, "ring_claim [VAR]", "Claim batch",
                    _CLAIM_FIELDS),
    "ring_worker": _e(ARGC_ARGV, "ring_worker [inc|dec]", "Worker control"),
    "ring_cleanup_waiter": _e(ARGC_ARGV, "ring_cleanup_waiter",
                              "Cleanup waiter"),
    "ring_ingest": _e(ARGC_ARGV, "ring_ingest", "Signal ingest"),
    "ring_fallow": _e(ARGC_ARGV, "ring_fallow <PIPE> <FILE> [dry]",
                      "Logical fallow"),
    "ring_ack": _e(ARGC_ARGV, "ring_ack <FD> <FD_OUT>", "Ack batch",
                  _ACK_FIELDS),
    "ring_order": _e(ARGC_ARGV, "ring_order <FD> <PFX|memfd> [unordered]",
                    "Reorder output"),
    "ring_copy": _e(ARGC_ARGV, "ring_copy <OUT> <IN>", "Zero-copy ingest"),
    "ring_signal": _e(ARGC_ARGV, "ring_signal <FD>", "Signal eventfd"),
    "ring_lseek": _e(ARGC_ARGV, "ring_lseek <FD> <OFF> [WHENCE] [VAR]",
                    "Seek fd"),
    "ring_indexer": _e(ARGC_ARGV, "ring_indexer", "NUMA Indexer"),
    "ring_fetcher": _e(ARGC_ARGV, "ring_fetcher", "NUMA Fetcher"),
    "ring_fallow_phys": _e(ARGC_ARGV, "ring_fallow_phys", "Physical fallow"),
    "ring_memfd_create": _e(ARGC_ARGV, "ring_memfd_create <VAR>",
                            "Create memfd"),
    "ring_seal": _e(ARGC_ARGV, "ring_seal <FD>", "Seal memfd"),
    "ring_fcntl": _e(ARGC_ARGV, "ring_fcntl <FD> <cmd>", "File control"),
    "ring_pipe": _e(ARGC_ARGV, "ring_pipe <ARR|RD> [WR]", "Create pipe"),
    "ring_splice": _e(ARGC_ARGV, "ring_splice <IN> <OUT> <OFF> <LEN> [close]",
                    "Splice data"),
    "ring_version": _e(ARGC_ARGV, "ring_version [-t|-o|-m|-g|-f|-a]",
                      "Show build metadata"),
    "ring_numa_stats": _e(ARGC_ARGV, "ring_numa_stats", "Print NUMA telemetry"),
    "ring_list": _e(ARGC_ARGV, "ring_list [VAR]", "List loadables"),
    "ring_poll": _e(
        ARGC_ARGV,
        "ring_poll <spawn_fd> <scan_arr> <work_arr> [timer] [trap_ack] [indexer_arr]",
        "Poll FDs", _POLL_FIELDS),
    "ring_revert_output": _e(ARGC_ARGV, "ring_revert_output <fd>",
                           "Revert partial output"),
    "ring_ack_init": _e(ARGC_ARGV, "ring_ack_init <fd>", "Sync output offset"),
    "ring_escrow_put": _e(ARGC_ARGV,
                          "ring_escrow_put <node> <idx> <cnt> <kills>",
                          "Deposit to escrow"),
    "ring_dump_resume": _e(ARGC_ARGV, "ring_dump_resume [bytes]",
                         "Dump checkpoint state"),
    "ring_set_resume": _e(ARGC_ARGV, "ring_set_resume <horizon> [jagged...]",
                        "Set checkpoint state"),
    "ring_abort": _e(ARGC_ARGV, "ring_abort", "Trigger global emergency abort"),
    "ring_abort_reason": _e(ARGC_ARGV, "ring_abort_reason [VAR]",
                          "Query abort reason (0=unset 1=sigpipe 2=fault)"),
    "ring_tui": _e(ARGC_ARGV, "ring_tui [expected_bytes] [order_mode]",
                   "Real-Time Telemetry Dashboard"),
}


def c_unquote(lit):
    """Unquote a C string literal (handles standard backslash escapes)."""
    lit = lit.strip()
    assert lit.startswith('"') and lit.endswith('"'), lit
    out = []
    i = 1
    end = len(lit) - 1
    while i < end:
        c = lit[i]
        if c == "\\" and i + 1 < end:
            nxt = lit[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                        '"': '"', "0": "\0"}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_engine_table(path):
    """Parse FORKRUN_LOADABLES from the engine source.

    Returns a list of (name, func, usage, doc) with C quoting removed.
    String-aware: quoted regions (with backslash escapes) never affect
    paren/comma structure, so usage/doc text containing parens — e.g.
    ring_abort_reason's "(0=unset 1=sigpipe 2=fault)" — parses correctly.
    Multi-line X() entries and backslash continuations are handled.
    """
    with open(path) as fh:
        src = fh.read()
    m = re.search(r"#define FORKRUN_LOADABLES\(X\)", src)
    if not m:
        raise ValueError("FORKRUN_LOADABLES table not found in %s" % path)
    i = m.end()
    n = len(src)

    def skip_ws(j):
        while j < n and src[j] in " \t\n":
            j += 1
        return j

    def skip_cont(j):
        j = skip_ws(j)
        if j < n and src[j] == "\\":
            j = skip_ws(j + 1)
        return j

    i = skip_cont(i)
    entries = []
    while True:
        if not src.startswith("X(", i):
            raise ValueError("expected X( at offset %d: %r" % (i, src[i:i+24]))
        i += 2
        args = []
        cur = []
        in_str = False
        esc = False
        depth = 0
        while True:
            c = src[i]
            if in_str:
                cur.append(c)
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                i += 1
            elif c == '"':
                in_str = True
                cur.append(c)
                i += 1
            elif c == "(":
                depth += 1
                cur.append(c)
                i += 1
            elif c == ")":
                if depth == 0:
                    args.append("".join(cur).strip())
                    i += 1
                    break
                depth -= 1
                cur.append(c)
                i += 1
            elif c == "," and depth == 0:
                args.append("".join(cur).strip())
                cur = []
                i += 1
            else:
                cur.append(c)
                i += 1
        if len(args) != 4:
            raise ValueError("X() entry has %d args: %r" % (len(args), args))
        # Line continuations may sit between the comma and the literal on
        # multi-line entries; drop them before unquoting.
        name, func, usage, doc = (re.sub(r"\\\n\s*", "", a).strip()
                                  for a in args)
        entries.append((name, func, c_unquote(usage), c_unquote(doc)))
        i = skip_ws(i)
        if i < n and src[i] == "\\":
            i = skip_cont(i)
            continue
        break
    return entries
