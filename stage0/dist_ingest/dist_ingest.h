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
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DI_MAX_NODES 64
#define DI_MAX_CHUNKS 4096

typedef enum {
    DI_POLICY_CENTRALIZED_CONTROL = 0, /* run existing control path externally */
    DI_POLICY_FIXED_FAA = 1,
    DI_POLICY_LOCAL_ADAPTIVE = 2,
    DI_POLICY_RELATIVE_ADAPTIVE = 3,
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
    /* Experiment */
    int one_outstanding_per_node; /* enforced as 1 in prototype */
    int enable_peer_headroom;     /* publish/read advisory headroom */
} di_policy_params_t;

typedef struct {
    int num_nodes;
    di_policy_t policy;
    di_policy_params_t params;
    /* Per-node consumer config (len num_nodes). NULL => equal/fast default. */
    const di_consumer_cfg_t *consumers;
    /* Optional per-logical-node CPU list for affinity: array of arrays.
     * cpu_lists[node] points to cpu_counts[node] ints; may be NULL. */
    const int *const *cpu_lists;
    const int *cpu_counts;
    /* Optional logical->physical node id for reporting/mbind hints. */
    const int *phys_nodes;
} di_config_t;

/* Per-node metrics snapshot (monotonic counters/totals). */
typedef struct {
    uint64_t reservations;            /* successful FAA reservations */
    uint64_t bytes_reserved;          /* sum of requested reservation sizes */
    uint64_t bytes_read;              /* sum of bytes actually read */
    uint64_t bytes_published;
    uint64_t bytes_consumed;
    uint64_t chunks_published;
    uint64_t chunks_consumed;
    uint64_t zero_claims;             /* admission denied / chose zero */
    uint64_t claim_wait_ns;           /* time waiting for capacity/admission */
    uint64_t read_wait_ns;            /* time in read/io */
    uint64_t publish_wait_ns;         /* time waiting to publish (queue full) */
    uint64_t consume_wait_ns;         /* consumer-side wait */
    uint64_t current_published_backlog;
    uint64_t current_outstanding;
    uint64_t current_effective_backlog;
    uint64_t max_effective_backlog;
    uint64_t max_published_backlog;
    uint64_t peer_observe_ns;         /* time spent sampling peer headroom */
    uint64_t peer_observe_count;
    /* Placement/buffer stats (best-effort) */
    uint64_t local_pages;
    uint64_t remote_pages;
    uint64_t unknown_pages;
    uint64_t hugepage_kb;             /* observed where available */
    uint64_t alloc_bytes;
    uint64_t ingest_cpu_ns;           /* per-ingestor thread CPU */
    uint64_t consumer_cpu_ns;         /* per-consumer thread CPU */
    uint64_t res_hist[20];            /* reservation size histogram */
    int last_error;
} di_node_metrics_t;

typedef struct {
    uint64_t total_bytes;
    uint64_t total_reserved;
    uint64_t total_read;
    uint64_t total_published;
    uint64_t total_consumed;
    uint64_t reservations_total;
    uint64_t eof_offset;
    int overlap_detected;
    int duplicate_detected;
    int lost_detected;
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
uint64_t di_effective_backlog(uint64_t published_backlog, uint64_t outstanding);
int di_can_admit(uint64_t max_backlog, uint64_t effective_backlog,
                 uint64_t outstanding, uint64_t want, int one_outstanding);

#ifdef __cplusplus
}
#endif

#endif /* STAGE0_DIST_INGEST_H */
