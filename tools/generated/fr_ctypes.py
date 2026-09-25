"""Generated ctypes mirror of the call-schema (v3.5.2 scaffolding).

GENERATED FILE — do not edit. Regenerate with:
  python3 tools/gen_idl.py
Single source: tools/idl_schema.py.

Nothing consumes this yet (Stage 4 wires the substrate).
"""

from __future__ import annotations

import ctypes

# Convention tags (mirror fr_convention_t).
ARGC_ARGV = "ARGC_ARGV"
THUNK = "THUNK"
BASH_ONLY = "BASH_ONLY"

# Scalar type map for field descriptors.
_CTYPE = {
    "I32": ctypes.c_int32,
    "U32": ctypes.c_uint32,
    "U64": ctypes.c_uint64,
    "U8": ctypes.c_uint8,
    "STR": ctypes.c_char_p,
    "PTR": ctypes.c_void_p,
}


def field_ctype(ftype):
    """Map a schema scalar type to its ctypes type."""
    return _CTYPE[ftype]


# Per-loadable calling convention (all ARGC_ARGV in v3.5.2).
CONVENTIONS = {
    "ring_abort": ARGC_ARGV,
    "ring_abort_reason": ARGC_ARGV,
    "ring_ack": ARGC_ARGV,
    "ring_ack_init": ARGC_ARGV,
    "ring_call": ARGC_ARGV,
    "ring_claim": ARGC_ARGV,
    "ring_cleanup_waiter": ARGC_ARGV,
    "ring_copy": ARGC_ARGV,
    "ring_destroy": ARGC_ARGV,
    "ring_dump_resume": ARGC_ARGV,
    "ring_escrow_put": ARGC_ARGV,
    "ring_exec": ARGC_ARGV,
    "ring_exec_splice": ARGC_ARGV,
    "ring_fallow": ARGC_ARGV,
    "ring_fallow_phys": ARGC_ARGV,
    "ring_fcntl": ARGC_ARGV,
    "ring_fetcher": ARGC_ARGV,
    "ring_indexer": ARGC_ARGV,
    "ring_indexer_numa": ARGC_ARGV,
    "ring_ingest": ARGC_ARGV,
    "ring_init": ARGC_ARGV,
    "ring_is_spawnable": ARGC_ARGV,
    "ring_list": ARGC_ARGV,
    "ring_lseek": ARGC_ARGV,
    "ring_map": ARGC_ARGV,
    "ring_memfd_create": ARGC_ARGV,
    "ring_numa_ingest": ARGC_ARGV,
    "ring_numa_scanner": ARGC_ARGV,
    "ring_numa_stats": ARGC_ARGV,
    "ring_order": ARGC_ARGV,
    "ring_pipe": ARGC_ARGV,
    "ring_poll": ARGC_ARGV,
    "ring_recover_worker": ARGC_ARGV,
    "ring_revert_output": ARGC_ARGV,
    "ring_scanner": ARGC_ARGV,
    "ring_seal": ARGC_ARGV,
    "ring_set_resume": ARGC_ARGV,
    "ring_signal": ARGC_ARGV,
    "ring_splice": ARGC_ARGV,
    "ring_tui": ARGC_ARGV,
    "ring_version": ARGC_ARGV,
    "ring_worker": ARGC_ARGV,
}


# Per-function field lists: [(direction, type, name, optional)].
# Only migration-order functions carry fields in v3.5.2.
FIELDS = {
    "ring_ack": [
        ("IN", "I32", "fd_fallow", False),
        ("IN", "I32", "fd_target", True),
    ],
    "ring_call": [
        ("IN", "I32", "fd", False),
        ("IN", "U64", "length", False),
        ("IN", "U8", "delim", False),
        ("IN", "STR", "so", False),
        ("IN", "STR", "fn", False),
        ("IN", "I32", "fixed_argc", False),
        ("IN", "PTR", "fixed", False),
    ],
    "ring_claim": [
        ("IN", "STR", "var_name", True),
        ("OUT", "U32", "REPLY", False),
        ("OUT", "U32", "RING_NUM_KILLS", False),
        ("OUT", "U32", "RING_POISONED", False),
        ("OUT", "U64", "RING_BATCH_IDX", False),
        ("LOCAL", "U64", "FRUN_CLAIM_BYTES", False),
    ],
    "ring_poll": [
        ("IN", "I32", "spawn_fd", False),
        ("IN", "STR", "scan_arr", False),
        ("IN", "STR", "work_arr", False),
        ("IN", "I32", "timer", True),
        ("IN", "I32", "trap_ack", True),
        ("IN", "STR", "indexer_arr", True),
    ],
}


# Usage/doc strings (outputs of the pipeline, not inputs).
USAGE = {
    "ring_abort": 'ring_abort',
    "ring_abort_reason": 'ring_abort_reason [VAR]',
    "ring_ack": 'ring_ack <FD> <FD_OUT>',
    "ring_ack_init": 'ring_ack_init <fd>',
    "ring_call": 'ring_call <fd> <len> <delim> <so> <fn>',
    "ring_claim": 'ring_claim [VAR]',
    "ring_cleanup_waiter": 'ring_cleanup_waiter',
    "ring_copy": 'ring_copy <OUT> <IN>',
    "ring_destroy": 'ring_destroy',
    "ring_dump_resume": 'ring_dump_resume [bytes]',
    "ring_escrow_put": 'ring_escrow_put <node> <idx> <cnt> <kills>',
    "ring_exec": 'ring_exec <fd> <len> <delim> <cmd> [args...]',
    "ring_exec_splice": 'ring_exec_splice <fd> <len> <cmd> [args...]',
    "ring_fallow": 'ring_fallow <PIPE> <FILE> [dry]',
    "ring_fallow_phys": 'ring_fallow_phys',
    "ring_fcntl": 'ring_fcntl <FD> <cmd>',
    "ring_fetcher": 'ring_fetcher',
    "ring_indexer": 'ring_indexer',
    "ring_indexer_numa": 'ring_indexer_numa <memfd> <node_id>',
    "ring_ingest": 'ring_ingest',
    "ring_init": 'ring_init [FLAGS]',
    "ring_is_spawnable": 'ring_is_spawnable <file>',
    "ring_list": 'ring_list [VAR]',
    "ring_lseek": 'ring_lseek <FD> <OFF> [WHENCE] [VAR]',
    "ring_map": 'ring_map <fd> <len> <array> [delim]',
    "ring_memfd_create": 'ring_memfd_create <VAR>',
    "ring_numa_ingest": 'ring_numa_ingest <infd> <outfd> <nodes> [ordered]',
    "ring_numa_scanner": 'ring_numa_scanner <memfd> <node_id> <spawn_fd> <nodes>',
    "ring_numa_stats": 'ring_numa_stats',
    "ring_order": 'ring_order <FD> <PFX|memfd> [unordered]',
    "ring_pipe": 'ring_pipe <ARR|RD> [WR]',
    "ring_poll": 'ring_poll <spawn_fd> <scan_arr> <work_arr> [timer] [trap_ack] [indexer_arr]',
    "ring_recover_worker": 'ring_recover_worker <wid> <incarn> [output_fd] [exit_code]',
    "ring_revert_output": 'ring_revert_output <fd>',
    "ring_scanner": 'ring_scanner <fd> [spawn_fd]',
    "ring_seal": 'ring_seal <FD>',
    "ring_set_resume": 'ring_set_resume <horizon> [jagged...]',
    "ring_signal": 'ring_signal <FD>',
    "ring_splice": 'ring_splice <IN> <OUT> <OFF> <LEN> [close]',
    "ring_tui": 'ring_tui [expected_bytes] [order_mode]',
    "ring_version": 'ring_version [-t|-o|-m|-g|-f|-a]',
    "ring_worker": 'ring_worker [inc|dec]',
}
DOC = {
    "ring_abort": 'Trigger global emergency abort',
    "ring_abort_reason": 'Query abort reason (0=unset 1=sigpipe 2=fault)',
    "ring_ack": 'Ack batch',
    "ring_ack_init": 'Sync output offset',
    "ring_call": 'Zero-Tax C Plugin Execution',
    "ring_claim": 'Claim batch',
    "ring_cleanup_waiter": 'Cleanup waiter',
    "ring_copy": 'Zero-copy ingest',
    "ring_destroy": 'Destroy ring',
    "ring_dump_resume": 'Dump checkpoint state',
    "ring_escrow_put": 'Deposit to escrow',
    "ring_exec": 'Ultra-fast execution of external binaries',
    "ring_exec_splice": 'Spawn binary and splice to its stdin',
    "ring_fallow": 'Logical fallow',
    "ring_fallow_phys": 'Physical fallow',
    "ring_fcntl": 'File control',
    "ring_fetcher": 'NUMA Fetcher',
    "ring_indexer": 'NUMA Indexer',
    "ring_indexer_numa": 'Run NUMA chunk indexer',
    "ring_ingest": 'Signal ingest',
    "ring_init": 'Initialize ring with config',
    "ring_is_spawnable": 'Check if file is binary or has shebang',
    "ring_list": 'List loadables',
    "ring_lseek": 'Seek fd',
    "ring_map": 'Fast user-space mapfile',
    "ring_memfd_create": 'Create memfd',
    "ring_numa_ingest": 'Run NUMA topological ingest',
    "ring_numa_scanner": 'Run unified NUMA scanner',
    "ring_numa_stats": 'Print NUMA telemetry',
    "ring_order": 'Reorder output',
    "ring_pipe": 'Create pipe',
    "ring_poll": 'Poll FDs',
    "ring_recover_worker": "Recover dead worker's in-flight batch",
    "ring_revert_output": 'Revert partial output',
    "ring_scanner": 'Run unified legacy scanner',
    "ring_seal": 'Seal memfd',
    "ring_set_resume": 'Set checkpoint state',
    "ring_signal": 'Signal eventfd',
    "ring_splice": 'Splice data',
    "ring_tui": 'Real-Time Telemetry Dashboard',
    "ring_version": 'Show build metadata',
    "ring_worker": 'Worker control',
}

__all__ = ["ARGC_ARGV", "THUNK", "BASH_ONLY", "field_ctype",
           "CONVENTIONS", "FIELDS", "USAGE", "DOC"]
