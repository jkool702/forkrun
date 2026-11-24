#ifndef STAGE0_DIST_INGEST_H
#define STAGE0_DIST_INGEST_H

/*
 * Experimental NUMA distributed-ingestion prototype (isolated).
 *
 * Single common engine with interchangeable claim policies. Regular-file
 * ingestion uses a global FAA byte-range cursor and one exclusive ingestor
 * thread per configured logical node. Not part of production ABI/frozen
 * engine.
 */

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DI_MAX_NODES 64

typedef enum {
    DI_POLICY_CENTRALIZED_CONTROL = 0, /* legacy/external; not run by this engine */
    DI_POLICY_FIXED_FAA = 1,
    DI_POLICY_LOCAL_ADAPTIVE = 2,
    DI_POLICY_RELATIVE_ADAPTIVE = 3,
    /* Section 5: in-engine centralized control baseline. Same engine/consumers/
     * work units/measurement as distributed candidates, but a single ingestor
     * thread reserves/reads and round-robin dispatches chunks to all node queues
     * (centralized scheduling/distribution) instead of one ingestor per node. */
    DI_POLICY_CENTRALIZED_INGEST = 4,
} di_policy_t;

typedef enum {
    DI_ERR_OK = 0,
    DI_ERR_INVAL = -1,
    DI_ERR_IO = -2,
    DI_ERR_NOMEM = -3,
    DI_ERR_STATE = -4,
    DI_ERR_THREAD = -5,
} di_err_t;

/* Consumer behavior for a node (used by experimental measurement). */
typedef enum {
    DI_CONSUMER_EQUAL = 0,
    DI_CONSUMER_SLOW = 1,
    DI_CONSUMER_FAST = 2,
    DI_CONSUMER_STALL = 3,   /* stalls for stall_ms then resumes at base rate */
} di_consumer_mode_t;

typedef struct {
    di_consumer_mode_t mode;
    /* Target consumption rate in bytes/sec; 0 => consume immediately. */
    uint64_t bytes_per_sec;
    /* For STALL: duration of initial stall in milliseconds. */
    uint64_t stall_ms;
} di_consumer_cfg_t;

/* §5.2: per-node ingestor workload controls (disabled by default).
 *
 * mode (per logical node, applied by the ingestor thread/step):
 *   0 = off (default; no artificial delay, zero measured overhead)
 *   1 = delay_per_claim      — sleep `delay_ns` after each successful claim+publish
 *   2 = delay_after_read     — sleep `delay_ns` after read, before publication
 *   3 = stall_then_recover   — sleep `stall_ms` once at ingestor-thread start,
 *                              then ingest resumes normally (recovery)
 *   4 = rate_limit           — throttle the ingest loop so the mean ingest
 *                              rate <= `rate_bps`
 * "The exact phase where delay is applied is explicit in configuration and
 * provenance" (WO §5.2): mode + values are echoed into DIST_RESULT
 * (configuration/provenance) and observed counters (metrics).
 */
typedef struct {
    int mode;
    uint64_t delay_ns;   /* modes 1/2 */
    uint64_t stall_ms;   /* mode 3 */
    uint64_t rate_bps;   /* mode 4 */
} di_ingestor_cfg_t;

typedef struct {
    /* Reservation / chunk sizing */
    uint64_t base_quantum;        /* default 2 MiB */
    uint64_t max_reservation;     /* cap per claim (bytes), 0 => max_backlog */
    uint64_t max_backlog;         /* per-node admission limit (bytes) */
    /* Relative policy tuning */
    uint64_t rel_min_claim;       /* quanta, default 0 */
    uint64_t rel_max_claim_quanta;/* cap in quanta, 0 => derived from caps */
    /* rounding: 0=floor, 1=nearest, 2=ceil (applied to M_i/avg in quanta-space) */
    int relative_rounding;
    /* Local adaptive: max quanta per claim (0 => derived) */
    uint64_t local_max_claim_quanta;
    /* Alignment / placement */
    int align_reservations;       /* align FAA offsets to quantum when feasible */
    int prefer_hugepage;          /* best-effort hints/alloc alignment */
    /* Placement/affinity strictness */
    int strict_affinity;          /* fail if either required thread role cannot be set/verified */
    int strict_mbind;             /* fail if memory policy application (mbind) cannot be established */
    /* Experiment */
    int one_outstanding_per_node; /* enforced as 1 in prototype */
    int enable_peer_headroom;     /* publish/read advisory headroom */
    /* Section 5: deterministic consumer kernel for common-engine comparability.
     * 0=none (rate-limit/stall only), 1=full byte-scan sum (memory-touch).
     * Runner/campaign default: 1 (full_byte_scan). At the C API level a
     * zero-initialized field means 0 (none); callers must set explicitly. */
    int consumer_kernel;
    /* Checkpoint 2: placement sampling mode (measurement integrity).
     * 0=off (no in-run move_pages sampling; performance-isolated default for
     *   timed measurement trials - placement observation not performed).
     * 1=on  (in-run move_pages sampling for placement-validation experiments;
     *   incurs treatment-dependent overhead in the timed path and must not be
     *   mixed with performance-comparison headline statistics).
     * 2=full (exhaustive sampling for diagnostics; NOT a clean performance
     *   measurement; bounded-1024 behavior of mode 1 not applied). */
    int placement_sampling;
} di_policy_params_t;

typedef struct {
    int num_nodes;
    di_policy_t policy;
    di_policy_params_t params;
    /* Per-node consumer config (len num_nodes). NULL => equal/fast default. */
    const di_consumer_cfg_t *consumers;
    /* Per-node ingestor workload controls (len num_nodes). NULL => off. */
    const di_ingestor_cfg_t *ingestors;
    /* Optional per-logical-node CPU list for affinity: array of arrays.
     * cpu_lists[node] points to cpu_counts[node] ints; may be NULL. */
    const int *const *cpu_lists;
    const int *cpu_counts;
    /* Optional logical->physical node id for reporting/mbind hints. */
    const int *phys_nodes;
} di_config_t;

/* Per-role CPU affinity result (Addendum A §2,§3). */
typedef struct {
    int requested;        /* affinity was requested for this role */
    int set_applied;      /* pthread_setaffinity_np succeeded */
    int query_succeeded;  /* pthread_getaffinity_np succeeded */
    int matched;          /* queried affinity matched requested CPU set */
    int error;            /* actual pthread/set/query error code (0 if none) */
    int strict_failed;    /* this role failed under strict affinity */
} di_affinity_role_t;

/* Per-node metrics snapshot (monotonic counters/totals). */
typedef struct {
    uint64_t reservations;            /* successful FAA reservations */
    uint64_t bytes_reserved_req;      /* sum of requested reservation sizes */
    uint64_t bytes_assigned;          /* sum of bytes assigned to in-file ranges */
    uint64_t bytes_read;              /* sum of bytes actually read */
    uint64_t bytes_published;
    uint64_t bytes_consumed;
    uint64_t consumer_bytes_scanned;  /* bytes touched by consumer kernel (proof of execution) */
    uint64_t chunks_published;
    uint64_t chunks_consumed;
    uint64_t zero_claims;             /* admission denied / chose zero */
    uint64_t claim_wait_ns;           /* time waiting for capacity/admission */
    uint64_t read_wait_ns;            /* time in read/io */
    uint64_t publish_wait_ns;         /* time waiting to publish (queue full) */
    uint64_t consume_wait_ns;         /* consumer-side wait */
    uint64_t current_published_backlog;
    uint64_t current_consumer_inflight_backlog;
    uint64_t current_outstanding;
    uint64_t current_effective_backlog;
    uint64_t max_published_backlog;
    uint64_t max_consumer_inflight_backlog;
    uint64_t max_effective_backlog;
    uint64_t peer_observe_ns;         /* time spent sampling peer headroom */
    uint64_t peer_observe_count;
    /* Observed placement sampling (independent of mbind syscall result) */
    uint64_t placement_total_addressable_pages;
    uint64_t placement_sampled_pages;
    uint64_t placement_sample_limit;
    uint64_t placement_sample_spacing;          /* stride in pages (1 => contiguous) */
    uint64_t placement_sample_target_match_pages; /* observed on preferred/target phys node */
    uint64_t placement_sample_other_node_pages;   /* observed on a different node */
    uint64_t placement_sample_unknown_pages;      /* unknown/unqueryable per-page */
    int placement_sampling_unavailable;           /* sampling not performed/unavailable */
    int placement_sampling_not_performed;         /* no eligible pages sampled yet */
    /* Hugepage reporting (distinguish requested/obtained/fallback/observed) */
    uint64_t hugepage_map_requested_bytes;
    uint64_t hugepage_map_obtained_bytes;
    uint64_t hugepage_fallback_bytes;
    uint64_t hugepage_observed_kb;    /* observed where available, else 0 */
    uint64_t alloc_bytes;
    uint64_t ingest_cpu_ns;           /* per-ingestor thread CPU */
    uint64_t consumer_cpu_ns;         /* per-consumer thread CPU */
    uint64_t res_hist[20];            /* reservation size histogram */
    /* Affinity (per-role, no shared concurrent writes) */
    di_affinity_role_t affinity_ingestor;
    di_affinity_role_t affinity_consumer;
    /* §5.2: ingestor workload control evidence (observed, per node). */
    int ingestor_mode;                 /* observed/requested mode (0=off) */
    uint64_t ingestor_delay_ns;        /* cumulative sleep (modes 1/2) */
    uint64_t ingestor_stall_fired;     /* mode 3: initial stall fired (1/0) */
    uint64_t ingestor_rate_throttled_ns; /* mode 4: cumulative throttle sleep */
    /* Memory-policy application (syscall result; NOT physical placement proof) */
    int mbind_policy_requested;       /* compatibility: any application requested */
    int mbind_policy_applied;         /* compatibility: all requested applications succeeded (and >=1 requested) */
    int mbind_error;                  /* last/representative actual mbind error if any failed */
    uint64_t mbind_requested_count;   /* policy applications requested (all allocation attempts) */
    uint64_t mbind_success_count;     /* policy applications succeeded */
    uint64_t mbind_failure_count;     /* policy applications failed */
    int strict_mbind_failed;          /* strict enforcement of successful policy application failed */
    int strict_affinity_failed;       /* aggregate: required role failed under strict affinity (run enforcement) */
    int last_error;
} di_node_metrics_t;

typedef struct {
    uint64_t total_bytes;
    uint64_t total_reserved_req;
    uint64_t total_assigned;
    uint64_t total_read;
    uint64_t total_published;
    uint64_t total_consumed;
    uint64_t total_consumer_bytes_scanned;
    uint64_t reservations_total;
    uint64_t eof_offset;
    int overlap_detected;
    int duplicate_detected;
    int lost_detected;
    int input_changed;                /* file mutated/truncated during run */
    double wall_seconds;
    uint64_t ingest_cpu_ns;           /* sum over ingestor threads */
    uint64_t consumer_cpu_ns;
    int num_nodes;
    di_policy_t policy;
    di_node_metrics_t nodes[DI_MAX_NODES];
    /* Reservation size histogram (log2-ish buckets, bytes): <=4K,8K,...,>=256M */
    uint64_t res_hist[20];
} di_result_t;

/* Opaque engine handle. */
typedef struct di_engine di_engine_t;

/* Create/destroy. cfg->num_nodes must be in [1, DI_MAX_NODES]. */
di_engine_t *di_create(int fd, uint64_t file_size, const di_config_t *cfg);
void di_destroy(di_engine_t *eng);

/* Run ingestion+consumption to completion (file fully accounted for or error).
 * Fills result (zeroed on entry). Returns 0 on success, negative di_err_t on
 * fatal setup/runtime failure (result may still contain partial metrics). */
int di_run(di_engine_t *eng, di_result_t *result);

/* Accessors for tests/instrumentation. */
uint64_t di_global_offset(const di_engine_t *eng);
uint64_t di_file_size(const di_engine_t *eng);
int di_num_nodes(const di_engine_t *eng);
/* Debug/test snapshot: returns 0 on success. */
int di_debug_node_accounting(di_engine_t *eng, int node,
                             uint64_t *published, uint64_t *inflight,
                             uint64_t *outstanding, uint64_t *effective);
/* Narrow test seams (validation only). Engine-local and synchronized where noted. */
int di_test_set_pread_seam(di_engine_t *eng, int mode, int counter, uint64_t threshold);
int di_test_pread_seam_fired(di_engine_t *eng);
int di_test_check_2m_alignment(size_t len); /* returns 1 if usable buffer 2MiB-aligned */

/* CPU mask build/verify helpers (independent of pinning a real thread). */
int di_test_cpu_mask_check(const int *cpus, int ncpus, int require_above_cpuset_size);
/* Probe kernel affinity mask size (bytes) for current thread. Returns size on
 * success, negative on error (error code in *out_err if non-NULL). */
int di_test_probe_affinity_mask_size(size_t *out_size, int *out_err);
/* Pin-thread role helper with injected pthread return/errno for testability.
 * If inject_set_rc/query_rc != 0 behavior is simulated: inject_set_rc is used as
 * pthread_setaffinity_np return (0 => proceed to query), inject_query_rc as
 * pthread_getaffinity_np return, inject_errno sets errno around calls. Pass
 * inject=0 to use real pthread calls. */
int di_test_pin_role_with_inject(const int *cpus, int ncpus, di_affinity_role_t *out,
                                 int inject, int inject_set_rc, int inject_query_rc,
                                 int inject_errno);

/* Placement sampling helpers. */
int di_test_sample_indices(uint64_t total_pages, uint64_t sample_limit,
                           uint64_t *out_indices, uint64_t max_out,
                           uint64_t *out_count, uint64_t *out_spacing);
/* Classification helper: applies move_pages-like result classification into the
 * provided counters (all must be non-NULL). status array has count entries
 * (per-page node id or negative). rc is move_pages return (0=per-page, <0=query
 * failure). Returns 0 on success. */
int di_test_classify_placement(int phys_node, long rc, int count, const int *status,
                               uint64_t *target_match, uint64_t *other_node,
                               uint64_t *unknown);
/* Engine-local placement seam: override move_pages classification for next
 * sampling calls (0=off). mode: 1=force query failure rc, 2=force per-page
 * statuses from pattern (0=target,1=other,2=negative). */
int di_test_set_placement_seam(di_engine_t *eng, int mode, int rc_or_unused,
                               int pattern_len, const int *pattern);

/* Failure-injection seams. */
int di_test_set_create_fail_seam(int fail_after_nodes); /* -1 disables */
int di_test_set_push_fail_seam(di_engine_t *eng, int fail_on_nth); /* 0 disables */
/* C2 test seam: placement sampler dispatch count (incremented only when sampler is invoked). */
void di_test_reset_placement_sample_calls(void);
uint64_t di_test_get_placement_sample_calls(void);

/* Policy decision (exposed for unit tests). Computes claim bytes for node i
 * given per-node effective backlogs/headrooms (bytes). headrooms[i] is the
 * advisory/effective headroom for node i (max_backlog - effective_backlog_i),
 * as known to the caller. For relative policy, uses all nodes' headrooms.
 * Returns claim size in bytes (multiple of base_quantum except possibly 0),
 * capped by per-node available capacity and max_reservation. */
uint64_t di_policy_decide(di_policy_t policy,
                          const di_policy_params_t *params,
                          int num_nodes,
                          int node_i,
                          const uint64_t *effective_backlogs,
                          const uint64_t *headrooms);

/* Accounting helpers (exposed for unit tests). */
uint64_t di_effective_backlog(uint64_t published_backlog,
                              uint64_t consumer_inflight_backlog,
                              uint64_t outstanding);
int di_can_admit(uint64_t max_backlog, uint64_t effective_backlog,
                 uint64_t outstanding, uint64_t want, int one_outstanding);

#ifdef __cplusplus
}
#endif

#endif /* STAGE0_DIST_INGEST_H */
