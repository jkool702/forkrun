/* forkrun_callschema.h — Stage 3.0 call-schema (v1.3 section 2.2).
 *
 * GENERATED FILE — do not edit. Regenerate with:
 *   python3 tools/gen_idl.py
 * Single source: tools/idl_schema.py. CI enforces
 * `gen_idl.py --check` (committed output must match).
 *
 * ANNOTATION-ONLY in v3.5.2: every loadable is ARGC_ARGV
 * (current string-argv behavior). The convention column exists
 * so Stage 3 flips are per-function commits (migration order:
 * ring_claim -> ring_ack -> ring_call -> ring_poll). No thunk
 * calling, no fr_call_t, no usage-string changes here.
 *
 * Companion to FORKRUN_LOADABLES in forkrun_ring.c (which is
 * frozen and carries no convention column): the schema test
 * (tools/test_idl.py) enforces name-for-name coverage and
 * usage/doc equality textually instead.
 *
 * Header hygiene (substrate rules): self-contained (no includes),
 * include-guarded, FTM-independent, order-independent.
 */
#ifndef FORKRUN_CALLSCHEMA_H
#define FORKRUN_CALLSCHEMA_H

/* Calling convention per loadable (Stage 3 flips THUNK). */
typedef enum fr_convention {
    FR_CONV_ARGC_ARGV = 0,
    FR_CONV_THUNK = 1,
    FR_CONV_BASH_ONLY = 2
} fr_convention_t;

/* Companion table: X(name, convention). Scaffolding-grade: the
 * field lists below (FR_FIELDS_<name>, FR_F no-ops until Stage 3
 * gives them meaning) carry direction/optionality/PTR+LEN for the
 * migration-order functions only. */
#define FORKRUN_CALL_SCHEMA(X) \
    X(ring_abort, FR_CONV_ARGC_ARGV) \
    X(ring_abort_reason, FR_CONV_ARGC_ARGV) \
    X(ring_ack, FR_CONV_ARGC_ARGV) \
    X(ring_ack_init, FR_CONV_ARGC_ARGV) \
    X(ring_call, FR_CONV_ARGC_ARGV) \
    X(ring_claim, FR_CONV_ARGC_ARGV) \
    X(ring_cleanup_waiter, FR_CONV_ARGC_ARGV) \
    X(ring_copy, FR_CONV_ARGC_ARGV) \
    X(ring_destroy, FR_CONV_ARGC_ARGV) \
    X(ring_dump_resume, FR_CONV_ARGC_ARGV) \
    X(ring_escrow_put, FR_CONV_ARGC_ARGV) \
    X(ring_exec, FR_CONV_ARGC_ARGV) \
    X(ring_exec_splice, FR_CONV_ARGC_ARGV) \
    X(ring_fallow, FR_CONV_ARGC_ARGV) \
    X(ring_fallow_phys, FR_CONV_ARGC_ARGV) \
    X(ring_fcntl, FR_CONV_ARGC_ARGV) \
    X(ring_fetcher, FR_CONV_ARGC_ARGV) \
    X(ring_indexer, FR_CONV_ARGC_ARGV) \
    X(ring_indexer_numa, FR_CONV_ARGC_ARGV) \
    X(ring_ingest, FR_CONV_ARGC_ARGV) \
    X(ring_init, FR_CONV_ARGC_ARGV) \
    X(ring_is_spawnable, FR_CONV_ARGC_ARGV) \
    X(ring_list, FR_CONV_ARGC_ARGV) \
    X(ring_lseek, FR_CONV_ARGC_ARGV) \
    X(ring_map, FR_CONV_ARGC_ARGV) \
    X(ring_memfd_create, FR_CONV_ARGC_ARGV) \
    X(ring_numa_ingest, FR_CONV_ARGC_ARGV) \
    X(ring_numa_scanner, FR_CONV_ARGC_ARGV) \
    X(ring_numa_stats, FR_CONV_ARGC_ARGV) \
    X(ring_order, FR_CONV_ARGC_ARGV) \
    X(ring_pipe, FR_CONV_ARGC_ARGV) \
    X(ring_poll, FR_CONV_ARGC_ARGV) \
    X(ring_revert_output, FR_CONV_ARGC_ARGV) \
    X(ring_scanner, FR_CONV_ARGC_ARGV) \
    X(ring_seal, FR_CONV_ARGC_ARGV) \
    X(ring_set_resume, FR_CONV_ARGC_ARGV) \
    X(ring_signal, FR_CONV_ARGC_ARGV) \
    X(ring_splice, FR_CONV_ARGC_ARGV) \
    X(ring_tui, FR_CONV_ARGC_ARGV) \
    X(ring_version, FR_CONV_ARGC_ARGV) \
    X(ring_worker, FR_CONV_ARGC_ARGV)

/* Field-descriptor hook: no-op until Stage 3. */
#define FR_F(dir, type, name, opt)

/* ring_ack ring_ack <FD> <FD_OUT> */
#define FR_NFIELDS_ring_ack 2
#define FR_FIELDS_ring_ack \
    FR_F(IN, I32, fd_fallow, 0) \
    FR_F(IN, I32, fd_target, 1)

/* ring_call ring_call <fd> <len> <delim> <so> <fn> */
#define FR_NFIELDS_ring_call 7
#define FR_FIELDS_ring_call \
    FR_F(IN, I32, fd, 0) \
    FR_F(IN, U64, length, 0) \
    FR_F(IN, U8, delim, 0) \
    FR_F(IN, STR, so, 0) \
    FR_F(IN, STR, fn, 0) \
    FR_F(IN, I32, fixed_argc, 0) \
    FR_F(IN, PTR, fixed, 0)

/* ring_claim ring_claim [VAR] */
#define FR_NFIELDS_ring_claim 6
#define FR_FIELDS_ring_claim \
    FR_F(IN, STR, var_name, 1) \
    FR_F(OUT, U32, REPLY, 0) \
    FR_F(OUT, U32, RING_NUM_KILLS, 0) \
    FR_F(OUT, U32, RING_POISONED, 0) \
    FR_F(OUT, U64, RING_BATCH_IDX, 0) \
    FR_F(LOCAL, U64, FRUN_CLAIM_BYTES, 0)

/* ring_poll ring_poll <spawn_fd> <scan_arr> <work_arr> [timer] [trap_ack] [indexer_arr] */
#define FR_NFIELDS_ring_poll 6
#define FR_FIELDS_ring_poll \
    FR_F(IN, I32, spawn_fd, 0) \
    FR_F(IN, STR, scan_arr, 0) \
    FR_F(IN, STR, work_arr, 0) \
    FR_F(IN, I32, timer, 1) \
    FR_F(IN, I32, trap_ack, 1) \
    FR_F(IN, STR, indexer_arr, 1)

#endif /* FORKRUN_CALLSCHEMA_H */
