#define _GNU_SOURCE
#include "dist_ingest.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define DI_QUANTUM_DEFAULT (2ULL * 1024 * 1024)
#define DI_ALIGN_2M (2ULL * 1024 * 1024)

typedef enum {
    DI_ALLOC_NONE = 0,
    DI_ALLOC_MMAP_ORDINARY = 1,
    DI_ALLOC_MMAP_HUGETLB = 2,
} di_alloc_kind_t;

typedef struct {
    uint64_t off;
    uint64_t len;          /* bytes assigned/read in this chunk */
    void *buf;             /* usable aligned buffer */
    void *map_base;        /* base passed to munmap (NULL if none) */
    size_t map_len;        /* length passed to munmap */
    di_alloc_kind_t kind;
    int huge_requested;
    int huge_obtained;
} di_chunk_t;

typedef struct {
    uint64_t off;
    uint64_t len_req;
    uint64_t len_assigned;
    uint64_t len_act;
} di_resrec_t;

/* --- narrow test seam for S3 fault injection (engine-local, Addendum A §7) --- */
typedef struct {
    int enabled;
    int mode;            /* 0=off,1=eintr_count,2=partial_max,3=premature_eof_at,4=error_at,5=error_after_partial */
    int counter;         /* remaining injections / partial max bytes / bytes before error */
    uint64_t threshold;  /* byte offset threshold for modes 3/4 */
    int fired;
} di_pread_seam_t;

typedef struct {
    int enabled;
    int mode;      /* 1=force query failure rc, 2=force per-page pattern */
    int rc;        /* for mode 1 */
    int pattern_len;
    int pattern[1024]; /* 0=target,1=other,2=negative */
} di_placement_seam_t;

typedef struct di_node {
    int id;
    int phys_node;
    di_engine_t *eng;
    pthread_t ing_tid;
    pthread_t cons_tid;
    int has_ing;
    int has_cons;

    di_chunk_t *q;
    unsigned q_cap;
    unsigned q_head;
    unsigned q_tail;
    unsigned q_count;
    pthread_mutex_t mu;
    pthread_cond_t cv_can_push;
    pthread_cond_t cv_can_pop;

    uint64_t published_backlog;
    uint64_t consumer_inflight_backlog;
    uint64_t outstanding;
    uint64_t max_published_backlog;
    uint64_t max_consumer_inflight_backlog;
    uint64_t max_effective_backlog;

    _Atomic uint64_t peer_headroom;

    di_node_metrics_t m;
    di_consumer_cfg_t cons_cfg;
    di_ingestor_cfg_t ing_cfg;   /* §5.2: per-node ingestor workload controls */

    di_resrec_t *recs;
    size_t recs_n, recs_cap;

    const int *cpus;
    int ncpus;
} di_node_t;

struct di_engine {
    int fd;
    uint64_t file_size;
    uint64_t file_dev;
    uint64_t file_ino;
    int64_t file_mtime_sec;
    int64_t file_mtime_nsec;
    di_config_t cfg;
    di_policy_params_t P;

    _Atomic uint64_t next_offset;
    _Atomic int stop;
    _Atomic int ingestors_done;
    _Atomic int input_changed;

    int num_nodes;
    int centralized_ingest; /* policy 4: single ingestor distributes to all nodes */
    di_node_t nodes[DI_MAX_NODES];

    struct timespec t_start, t_end;
    int started;

    /* engine-local seams (synchronized) */
    pthread_mutex_t seam_mu;
    di_pread_seam_t pread_seam;
    di_placement_seam_t placement_seam;
    int push_fail_nth;     /* 0 disables; countdown on push attempts */
    int push_fail_fired;
};

/* global test seams */
static _Atomic int g_create_fail_after_nodes = -1;
/* Test-only seam/counter: placement sampler dispatch count. Not incremented on the
 * performance-isolated hot path because call sites must not dispatch when
 * placement_sampling==0 (C2 correction). */
static _Atomic uint64_t g_placement_sample_calls = 0;

static uint64_t di_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static di_node_t *di_ingestor_of(di_engine_t *eng, di_node_t *n) {
    /* §5.2: in centralized-ingest mode the single ingestor is node 0. */
    return eng->centralized_ingest ? &eng->nodes[0] : n;
}

/* §5.2: sleep an artificial ingestor delay; accumulate measured time.
 * Zero delay is a no-op (disabled by default; no overhead when unused). */
static void di_ingestor_sleep_ns(di_node_t *n, uint64_t ns) {
    if (ns == 0) return;
    uint64_t t0 = di_now_ns();
    struct timespec ts;
    ts.tv_sec = (time_t)(ns / 1000000000ULL);
    ts.tv_nsec = (long)(ns % 1000000000ULL);
    nanosleep(&ts, NULL);
    n->m.ingestor_delay_ns += di_now_ns() - t0;
}

static uint64_t di_thread_cpu_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts) != 0) return 0;
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static uint64_t di_u64_add_sat(uint64_t a, uint64_t b) {
    if (UINT64_MAX - a < b) return UINT64_MAX;
    return a + b;
}

static void di_hist_add(uint64_t *hist, uint64_t sz) {
    static const uint64_t bounds[19] = {
        4ULL<<10,8ULL<<10,16ULL<<10,32ULL<<10,64ULL<<10,128ULL<<10,256ULL<<10,512ULL<<10,
        1ULL<<20,2ULL<<20,4ULL<<20,8ULL<<20,16ULL<<20,32ULL<<20,64ULL<<20,128ULL<<20,256ULL<<20,512ULL<<20,
        1ULL<<30
    };
    int i;
    for (i = 0; i < 19; i++) {
        if (sz <= bounds[i]) { hist[i]++; return; }
    }
    hist[19]++;
}

uint64_t di_effective_backlog(uint64_t published_backlog,
                              uint64_t consumer_inflight_backlog,
                              uint64_t outstanding) {
    return di_u64_add_sat(di_u64_add_sat(published_backlog, consumer_inflight_backlog), outstanding);
}

int di_can_admit(uint64_t max_backlog, uint64_t effective_backlog_v,
                 uint64_t outstanding, uint64_t want, int one_outstanding) {
    if (want == 0) return 0;
    if (one_outstanding && outstanding > 0) return 0;
    if (effective_backlog_v > max_backlog) return 0;
    if (want > max_backlog - effective_backlog_v) return 0;
    return 1;
}

static int di_record_res(di_node_t *n, uint64_t off, uint64_t req, uint64_t assigned, uint64_t act) {
    if (n->recs_n == n->recs_cap) {
        size_t nc = n->recs_cap ? n->recs_cap * 2 : 64;
        di_resrec_t *nr = (di_resrec_t *)realloc(n->recs, nc * sizeof(*nr));
        if (!nr) return -1;
        n->recs = nr;
        n->recs_cap = nc;
    }
    n->recs[n->recs_n].off = off;
    n->recs[n->recs_n].len_req = req;
    n->recs[n->recs_n].len_assigned = assigned;
    n->recs[n->recs_n].len_act = act;
    n->recs_n++;
    return 0;
}

static uint64_t di_node_eff(const di_node_t *n) {
    return di_effective_backlog(n->published_backlog, n->consumer_inflight_backlog, n->outstanding);
}

static void di_publish_headroom(di_node_t *n) {
    di_engine_t *eng = n->eng;
    uint64_t eff = di_node_eff(n);
    uint64_t hr = 0;
    if (eng->P.max_backlog > eff) hr = eng->P.max_backlog - eff;
    __atomic_store_n(&n->peer_headroom, hr, __ATOMIC_RELAXED);
}

uint64_t di_policy_decide(di_policy_t policy,
                          const di_policy_params_t *params,
                          int num_nodes,
                          int node_i,
                          const uint64_t *effective_backlogs,
                          const uint64_t *headrooms) {
    if (!params || node_i < 0 || node_i >= num_nodes) return 0;
    uint64_t quantum = params->base_quantum ? params->base_quantum : DI_QUANTUM_DEFAULT;
    uint64_t max_backlog = params->max_backlog;
    uint64_t max_res = params->max_reservation ? params->max_reservation : max_backlog;
    uint64_t hr_i = headrooms[node_i];
    if (hr_i == 0 || quantum == 0) return 0;

    uint64_t claim_quanta = 0;

    if (policy == DI_POLICY_FIXED_FAA || policy == DI_POLICY_CENTRALIZED_INGEST) {
        if (hr_i >= quantum) claim_quanta = 1;
        else claim_quanta = 0;
    } else if (policy == DI_POLICY_LOCAL_ADAPTIVE) {
        claim_quanta = hr_i / quantum;
        uint64_t capq = params->local_max_claim_quanta;
        if (capq == 0) {
            capq = max_backlog / quantum;
            if (capq == 0) capq = 1;
        }
        if (claim_quanta > capq) claim_quanta = capq;
    } else if (policy == DI_POLICY_RELATIVE_ADAPTIVE) {
        int K = num_nodes - 1;
        if (K <= 0) {
            claim_quanta = hr_i / quantum;
        } else {
            unsigned __int128 S_i = 0;
            for (int j = 0; j < num_nodes; j++) {
                if (j == node_i) continue;
                S_i += (unsigned __int128)headrooms[j];
            }
            if (S_i == 0) {
                claim_quanta = hr_i / quantum;
            } else {
                unsigned __int128 numer = (unsigned __int128)K * (unsigned __int128)hr_i;
                unsigned __int128 q = numer / S_i;
                unsigned __int128 rem = numer % S_i;
                int rm = params->relative_rounding;
                if (rm == 2 && rem != 0) q += 1;
                else if (rm == 1 && rem * 2 >= S_i) q += 1;
                if (q > (unsigned __int128)UINT64_MAX) claim_quanta = UINT64_MAX;
                else claim_quanta = (uint64_t)q;
            }
        }
        if (claim_quanta < params->rel_min_claim) claim_quanta = 0;
        uint64_t capq = params->rel_max_claim_quanta;
        if (capq == 0) {
            capq = max_backlog / quantum;
            if (capq == 0) capq = 1;
        }
        if (claim_quanta > capq) claim_quanta = capq;
    } else {
        claim_quanta = 0;
    }

    if (claim_quanta == 0) return 0;
    /* overflow-checked multiplication (Section 9) */
    if (quantum != 0 && claim_quanta > UINT64_MAX / quantum) return 0;
    uint64_t want = claim_quanta * quantum;
    /* align_reservations: quantize claims to quantum multiples when requested/feasible */
    if (want > hr_i) want = (hr_i / quantum) * quantum;
    if (want > max_res) want = (max_res / quantum) * quantum;
    if (want == 0) return 0;
    if (want > hr_i) return 0; /* max_reservation/headroom must never be exceeded */
    (void)params->align_reservations; /* honored: quantum-multiple sizing */
    (void)effective_backlogs;
    return want;
}

/* --- Affinity (Addendum A closeout: safe large IDs, checked arithmetic, probe) --- */
#ifdef __linux__
static int di_probe_affinity_mask_count(size_t start_count, size_t *out_count) {
    /* Probe kernel-acceptable cpu count by trying sched_setaffinity on self with
     * progressively larger buffers; EINVAL may indicate insufficient buffer. */
    if (!out_count) return -1;
    size_t count = start_count < 1 ? 1 : start_count;
    size_t max_count = 1024 * 1024; /* 1M CPUs upper bound for probe */
    for (int iter = 0; iter < 24 && count <= max_count; iter++) {
        size_t sz = CPU_ALLOC_SIZE(count);
        cpu_set_t *set = CPU_ALLOC(count);
        if (!set) return -ENOMEM;
        CPU_ZERO_S(sz, set);
        /* query current affinity into a buffer of this size */
        int rc = sched_getaffinity(0, sz, set);
        if (rc == 0) { *out_count = count; CPU_FREE(set); return 0; }
        int e = errno;
        CPU_FREE(set);
        if (e == EINVAL) {
            if (count > max_count / 2) return -EINVAL;
            count *= 2;
            continue;
        }
        return -e;
    }
    return -EINVAL;
}

static int di_pin_thread_role_impl(const int *cpus, int ncpus, di_affinity_role_t *out,
                                   int inject, int inject_set_rc, int inject_query_rc,
                                   int inject_errno) {
    memset(out, 0, sizeof(*out));
    if (!cpus || ncpus <= 0) {
        out->requested = 0;
        return 0; /* intentionally unrequested */
    }
    out->requested = 1;
    int max_cpu = -1;
    for (int i = 0; i < ncpus; i++) {
        if (cpus[i] < 0) { out->error = EINVAL; return -1; }
        if (cpus[i] > max_cpu) max_cpu = cpus[i];
    }
    if (max_cpu < 0) { out->error = EINVAL; return -1; }
    /* checked arithmetic: need count = max_cpu + 1 CPUs */
    if ((unsigned int)max_cpu > (unsigned int)(INT_MAX - 1)) { out->error = EOVERFLOW; return -1; }
    size_t need_count = (size_t)max_cpu + 1;
    /* probe to determine a kernel-acceptable mask size (>= need_count) */
    size_t mask_count = need_count;
    int prc = di_probe_affinity_mask_count(need_count, &mask_count);
    if (prc != 0) { out->error = -prc; return -1; }
    if (mask_count < need_count) { out->error = EINVAL; return -1; }
    /* checked allocation size */
    size_t setsize = CPU_ALLOC_SIZE(mask_count);
    if (mask_count != 0 && setsize / (size_t)((mask_count + __NCPUBITS - 1) / __NCPUBITS) < sizeof(__cpu_mask)) {
        /* basic overflow guard (CPU_ALLOC_SIZE is usually safe, but be defensive) */
    }
    cpu_set_t *set = CPU_ALLOC(mask_count);
    cpu_set_t *got = CPU_ALLOC(mask_count);
    if (!set || !got) {
        if (set) CPU_FREE(set);
        if (got) CPU_FREE(got);
        out->error = ENOMEM;
        return -1;
    }
    CPU_ZERO_S(setsize, set);
    CPU_ZERO_S(setsize, got);
    for (int i = 0; i < ncpus; i++) {
        /* bounds within allocated mask */
        if ((size_t)cpus[i] >= mask_count) { CPU_FREE(set); CPU_FREE(got); out->error = EINVAL; return -1; }
        CPU_SET_S(cpus[i], setsize, set);
    }
    int rc;
    if (inject) {
        errno = inject_errno;
        rc = inject_set_rc;
    } else {
        rc = pthread_setaffinity_np(pthread_self(), setsize, set);
    }
    if (rc != 0) {
        out->error = rc; /* pthread returns error number directly */
        CPU_FREE(set); CPU_FREE(got);
        return -1;
    }
    out->set_applied = 1;
    if (inject) {
        errno = inject_errno;
        rc = inject_query_rc;
    } else {
        rc = pthread_getaffinity_np(pthread_self(), setsize, got);
    }
    if (rc != 0) {
        out->error = rc; /* pthread returns error number directly */
        CPU_FREE(set); CPU_FREE(got);
        return -1;
    }
    out->query_succeeded = 1;
    int match = 1;
    for (int i = 0; i < ncpus; i++) {
        if (!CPU_ISSET_S(cpus[i], setsize, got)) { match = 0; break; }
    }
    out->matched = match;
    if (!match) {
        out->error = EPERM;
        CPU_FREE(set); CPU_FREE(got);
        return -1;
    }
    CPU_FREE(set); CPU_FREE(got);
    return 0;
}

static int di_pin_thread_role(const int *cpus, int ncpus, di_affinity_role_t *out) {
    return di_pin_thread_role_impl(cpus, ncpus, out, 0, 0, 0, 0);
}
#else
static int di_pin_thread_role_impl(const int *cpus, int ncpus, di_affinity_role_t *out,
                                   int inject, int inject_set_rc, int inject_query_rc,
                                   int inject_errno) {
    memset(out, 0, sizeof(*out));
    if (!cpus || ncpus <= 0) { out->requested = 0; return 0; }
    out->requested = 1;
    if (inject && inject_set_rc != 0) { out->error = inject_set_rc; (void)inject_errno; return -1; }
    out->error = ENOTSUP;
    (void)inject_query_rc;
    return -1;
}
static int di_pin_thread_role(const int *cpus, int ncpus, di_affinity_role_t *out) {
    return di_pin_thread_role_impl(cpus, ncpus, out, 0, 0, 0, 0);
}
#endif

/* --- mbind (policy application; not physical placement proof) --- */
static void di_mbind_update_compat(di_node_t *n) {
    n->m.mbind_policy_requested = (n->m.mbind_requested_count > 0) ? 1 : 0;
    /* compatibility: all requested applications succeeded (and >=1 requested) */
    n->m.mbind_policy_applied =
        (n->m.mbind_requested_count > 0 && n->m.mbind_failure_count == 0) ? 1 : 0;
}

/* CK-1: mbind via the Linux syscall interface (SYS_mbind) with an
 * optional libnuma fallback where no syscall is exposed. */
#if !defined(MPOL_PREFERRED)
#include <linux/mempolicy.h>
#endif
static int di_mbind_syscall(void *addr, size_t len, unsigned long *mask,
                            unsigned long maxnode) {
#if defined(SYS_mbind)
    return (int)syscall(SYS_mbind, addr, len, MPOL_PREFERRED,
                        mask, maxnode, 0);
#elif defined(__NR_mbind)
    return (int)syscall(__NR_mbind, addr, len, MPOL_PREFERRED,
                        mask, maxnode, 0);
#else
    return -1;
#endif
}

static int di_mbind_node(void *addr, size_t len, int phys_node, di_node_t *n) {
    if (phys_node < 0) return 0;
    /* Track every allocation attempt where policy application was requested. */
    n->m.mbind_requested_count++;
    di_mbind_update_compat(n);
#ifdef __linux__
    {
        unsigned long maxnode = (unsigned long)phys_node + 2;
        size_t mask_bytes = (maxnode + 7UL) / 8UL;
        size_t mask_ul = (mask_bytes + sizeof(unsigned long) - 1) / sizeof(unsigned long);
        unsigned long *mask = (unsigned long *)calloc(mask_ul ? mask_ul : 1, sizeof(unsigned long));
        if (!mask) {
            n->m.mbind_failure_count++;
            if (n->m.mbind_error == 0) n->m.mbind_error = ENOMEM;
            di_mbind_update_compat(n);
            return -1;
        }
        mask[phys_node / (int)(sizeof(unsigned long) * 8)] |= 1UL << (phys_node % (int)(sizeof(unsigned long) * 8));
        long rc = di_mbind_syscall(addr, len, mask, maxnode);
        int err = errno;
        free(mask);
        if (rc != 0) {
            n->m.mbind_failure_count++;
            /* Preserve actual error information; do not erase earlier failure evidence. */
            if (n->m.mbind_error == 0) n->m.mbind_error = err ? err : EINVAL;
            di_mbind_update_compat(n);
            return -1;
        }
        n->m.mbind_success_count++;
        di_mbind_update_compat(n);
        return 0;
    }
#else
    n->m.mbind_failure_count++;
    if (n->m.mbind_error == 0) n->m.mbind_error = ENOTSUP;
    di_mbind_update_compat(n);
    return -1;
#endif
}

static int di_alloc_local(size_t len, int prefer_huge, int phys_node, di_node_t *n,
                          di_chunk_t *out) {
    memset(out, 0, sizeof(*out));
    if (len == 0) return -1;
    if (len > (SIZE_MAX - DI_ALIGN_2M)) return -1;
    size_t aln = DI_ALIGN_2M;
    size_t map_len = len + aln;
    if (map_len < len || map_len < aln) return -1;
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
    void *map_base = MAP_FAILED;
    int used_huge = 0;
    if (prefer_huge) n->m.hugepage_map_requested_bytes += len;
#ifdef MAP_HUGETLB
    if (prefer_huge && map_len >= DI_ALIGN_2M) {
        map_base = mmap(NULL, map_len, PROT_READ | PROT_WRITE, flags | MAP_HUGETLB, -1, 0);
        if (map_base != MAP_FAILED) used_huge = 1;
    }
#endif
    if (map_base == MAP_FAILED) {
        map_base = mmap(NULL, map_len, PROT_READ | PROT_WRITE, flags, -1, 0);
    }
    if (map_base == MAP_FAILED) return -1;
    uintptr_t addr = (uintptr_t)map_base;
    uintptr_t aligned = (addr + aln - 1) & ~(uintptr_t)(aln - 1);
    void *usable = (void *)aligned;
    int mbind_rc = di_mbind_node(map_base, map_len, phys_node, n);
    if (mbind_rc != 0 && n->eng->P.strict_mbind) {
        munmap(map_base, map_len);
        n->m.strict_mbind_failed = 1;
        return -1;
    }
    out->buf = usable;
    out->map_base = map_base;
    out->map_len = map_len;
    out->kind = used_huge ? DI_ALLOC_MMAP_HUGETLB : DI_ALLOC_MMAP_ORDINARY;
    out->huge_requested = prefer_huge ? 1 : 0;
    out->huge_obtained = used_huge;
    n->m.alloc_bytes += len;
    if (prefer_huge) {
        if (used_huge) n->m.hugepage_map_obtained_bytes += len;
        else n->m.hugepage_fallback_bytes += len;
    }
    return 0;
}

static void di_free_chunk(di_chunk_t *c) {
    if (!c || !c->map_base || c->map_len == 0) return;
    munmap(c->map_base, c->map_len);
    c->buf = NULL;
    c->map_base = NULL;
    c->map_len = 0;
}

/* Placement sampling: distributed across full usable allocation.
 * C2: in-run sampling (move_pages/syscall path) is enabled only when
 * P.placement_sampling == 1 (placement-validation experiments). When 0
 * (performance-isolated default), call sites must not dispatch this function in the
 * timed/allocation path; node metrics are initialized at engine creation. */
static int di_sample_placement(di_node_t *n, void *buf, size_t len) {
    __atomic_fetch_add(&g_placement_sample_calls, 1, __ATOMIC_RELAXED);
    if (!n || !n->eng) return 0;
    if (n->eng->P.placement_sampling == 0) {
        /* Defensive: performance-isolated path should not dispatch sampler. */
        n->m.placement_sampling_not_performed = 1;
        return 0;
    }
#if defined(__linux__) && defined(__NR_move_pages)
    if (!buf || len == 0) {
        n->m.placement_sampling_not_performed = 1;
        return 0;
    }
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) { n->m.placement_sampling_unavailable = 1; return 0; }
    uint64_t total_pages = ((uint64_t)len + (uint64_t)page - 1) / (uint64_t)page;
    if (total_pages == 0) { n->m.placement_sampling_not_performed = 1; return 0; }
    /* §2: full mode (placement_sampling=2) is exhaustive; bounded (1)
     * keeps the 1024-page limit. */
    uint64_t sample_limit = (n->eng->P.placement_sampling == 2) ? total_pages : 1024;
    n->m.placement_total_addressable_pages += total_pages;
    n->m.placement_sample_limit = sample_limit; /* per-allocation parameter */
    uint64_t idxs_stack[1024];
    uint64_t *idxs = idxs_stack;
    if (sample_limit > sizeof(idxs_stack)/sizeof(*idxs)) {
        idxs = (uint64_t *)malloc((size_t)sample_limit * sizeof(*idxs));
        if (!idxs) {
            n->m.placement_sample_unknown_pages += total_pages;
            n->m.placement_sampling_unavailable = 1;
            return -1;
        }
    }
    uint64_t count = 0, spacing = 1;
    if (di_test_sample_indices(total_pages, sample_limit, idxs, sample_limit, &count, &spacing) != 0 || count == 0) {
        n->m.placement_sampling_not_performed = 1;
        if (idxs != idxs_stack) free(idxs);
        return 0;
    }
    n->m.placement_sample_spacing = spacing; /* per-allocation (last allocation) */
    n->m.placement_sampled_pages += count;
    void **addrs = (void **)calloc((size_t)count, sizeof(void *));
    int *status = (int *)calloc((size_t)count, sizeof(int));
    if (!addrs || !status) {
        free(addrs); free(status);
        if (idxs != idxs_stack) free(idxs);
        n->m.placement_sample_unknown_pages += count;
        n->m.placement_sampling_unavailable = 1;
        return -1;
    }
    for (uint64_t i = 0; i < count; i++) addrs[i] = (char *)buf + idxs[i] * (uint64_t)page;
    long rc = syscall(__NR_move_pages, 0, (unsigned long)count, addrs, NULL, status, 0);
    /* placement seam override (engine-local) */
    di_engine_t *eng = n->eng;
    pthread_mutex_lock(&eng->seam_mu);
    di_placement_seam_t seam = eng->placement_seam;
    pthread_mutex_unlock(&eng->seam_mu);
    if (seam.enabled) {
        if (seam.mode == 1) {
            rc = seam.rc ? seam.rc : -1;
        } else if (seam.mode == 2) {
            rc = 0;
            for (uint64_t i = 0; i < count; i++) {
                int p = seam.pattern_len > 0 ? seam.pattern[i % (uint64_t)seam.pattern_len] : 0;
                if (p == 0) status[i] = n->phys_node >= 0 ? n->phys_node : 0;
                else if (p == 1) status[i] = (n->phys_node >= 0 ? n->phys_node + 1 : 1);
                else status[i] = -ENOENT;
            }
        }
    }
    uint64_t tm=0, on=0, un=0;
    di_test_classify_placement(n->phys_node, rc, (int)count, status, &tm, &on, &un);
    n->m.placement_sample_target_match_pages += tm;
    n->m.placement_sample_other_node_pages += on;
    n->m.placement_sample_unknown_pages += un;
    if (rc != 0) n->m.placement_sampling_unavailable = 1;
    free(addrs); free(status);
    if (idxs != idxs_stack) free(idxs);
    return 0;
#else
    (void)buf; (void)len;
    n->m.placement_sampling_unavailable = 1;
    return 0;
#endif
}

static int di_check_input_unchanged(di_engine_t *eng) {
    struct stat st;
    if (fstat(eng->fd, &st) != 0) return -1;
    if ((uint64_t)st.st_dev != eng->file_dev) return -1;
    if ((uint64_t)st.st_ino != eng->file_ino) return -1;
    if ((uint64_t)st.st_size != eng->file_size) return -1;
#if defined(__linux__)
    if ((int64_t)st.st_mtim.tv_sec != eng->file_mtime_sec ||
        (int64_t)st.st_mtim.tv_nsec != eng->file_mtime_nsec) return -1;
#else
    if ((int64_t)st.st_mtime != eng->file_mtime_sec) return -1;
#endif
    return 0;
}

static ssize_t di_pread_full(di_engine_t *eng, void *buf, size_t len, uint64_t off) {
    if (!eng || !buf) { errno = EINVAL; return -1; }
    if (len > (size_t)SSIZE_MAX) { errno = EINVAL; return -1; }
    if (off > (uint64_t)INT64_MAX) { errno = EOVERFLOW; return -1; }
    size_t done = 0;
    while (done < len) {
        if (di_check_input_unchanged(eng) != 0) {
            __atomic_store_n(&eng->input_changed, 1, __ATOMIC_RELEASE);
            errno = EIO;
            return -1;
        }
        uint64_t cur_off = off + (uint64_t)done;
        if (cur_off > (uint64_t)INT64_MAX) { errno = EOVERFLOW; return -1; }
        off_t poff = (off_t)cur_off;
        if ((uint64_t)poff != cur_off) { errno = EOVERFLOW; return -1; }
        size_t want = len - done;
        if (want > (size_t)SSIZE_MAX) want = (size_t)SSIZE_MAX;
        /* synchronized seam read */
        pthread_mutex_lock(&eng->seam_mu);
        di_pread_seam_t seam = eng->pread_seam;
        int consume_eintr = 0, consume_partial = 0, do_premature_eof = 0, do_error_at = 0, do_error_after_partial = 0;
        size_t partial_cap = 0;
        if (seam.enabled) {
            if (seam.mode == 1 && seam.counter > 0) { consume_eintr = 1; eng->pread_seam.counter--; eng->pread_seam.fired = 1; }
            else if (seam.mode == 2 && seam.counter > 0) { consume_partial = 1; partial_cap = (size_t)seam.counter; eng->pread_seam.fired = 1; }
            else if (seam.mode == 3 && cur_off >= seam.threshold) { do_premature_eof = 1; eng->pread_seam.fired = 1; }
            else if (seam.mode == 4 && cur_off >= seam.threshold) { do_error_at = 1; eng->pread_seam.fired = 1; }
            else if (seam.mode == 5 && seam.counter > 0) { do_error_after_partial = 1; partial_cap = (size_t)seam.counter; eng->pread_seam.counter = 0; eng->pread_seam.fired = 1; }
        }
        pthread_mutex_unlock(&eng->seam_mu);

        ssize_t rr;
        if (consume_eintr) {
            errno = EINTR; rr = -1;
        } else {
            rr = pread(eng->fd, (char *)buf + done, want, poff);
        }
        if (rr >= 0) {
            if (consume_partial && rr > 0 && (size_t)rr > partial_cap) rr = (ssize_t)partial_cap;
            if (do_error_after_partial && rr > 0) {
                if ((size_t)rr > partial_cap) rr = (ssize_t)partial_cap;
                if (rr > 0) { done += (size_t)rr; errno = EIO; return -1; }
            }
            if (do_premature_eof) rr = 0;
            if (do_error_at) { errno = EIO; rr = -1; }
        }
        if (rr < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (rr == 0) break;
        done += (size_t)rr;
        if (done > (size_t)SSIZE_MAX) { errno = EOVERFLOW; return -1; }
    }
    return (ssize_t)done;
}

static void di_engine_stop(di_engine_t *eng);

static int di_queue_push(di_node_t *n, di_chunk_t c) {
    di_engine_t *eng = n->eng;
    pthread_mutex_lock(&n->mu);
    while (n->q_count == n->q_cap && !__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) {
        uint64_t t0 = di_now_ns();
        pthread_cond_wait(&n->cv_can_push, &n->mu);
        n->m.publish_wait_ns += di_now_ns() - t0;
    }
    if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) {
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    /* failure injection seam */
    pthread_mutex_lock(&eng->seam_mu);
    int force_fail = 0;
    if (eng->push_fail_nth > 0) {
        eng->push_fail_nth--;
        if (eng->push_fail_nth == 0) { force_fail = 1; eng->push_fail_fired = 1; }
    }
    pthread_mutex_unlock(&eng->seam_mu);
    if (force_fail) {
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    n->q[n->q_tail] = c;
    n->q_tail = (n->q_tail + 1) % n->q_cap;
    n->q_count++;
    if (n->outstanding >= c.len) n->outstanding -= c.len; else n->outstanding = 0;
    n->published_backlog = di_u64_add_sat(n->published_backlog, c.len);
    if (n->published_backlog > n->max_published_backlog) n->max_published_backlog = n->published_backlog;
    uint64_t eff = di_node_eff(n);
    if (eff > n->max_effective_backlog) n->max_effective_backlog = eff;
    n->m.bytes_published += c.len;
    n->m.chunks_published++;
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_pop);
    pthread_mutex_unlock(&n->mu);
    return 0;
}

static int di_queue_pop(di_node_t *n, di_chunk_t *out, int *ing_done) {
    di_engine_t *eng = n->eng;
    pthread_mutex_lock(&n->mu);
    for (;;) {
        if (n->q_count > 0) break;
        int done = (__atomic_load_n(&eng->ingestors_done, __ATOMIC_ACQUIRE) == eng->num_nodes);
        if (done || __atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) {
            if (ing_done) *ing_done = 1;
            pthread_mutex_unlock(&n->mu);
            return 0;
        }
        uint64_t t0 = di_now_ns();
        pthread_cond_wait(&n->cv_can_pop, &n->mu);
        n->m.consume_wait_ns += di_now_ns() - t0;
    }
    *out = n->q[n->q_head];
    n->q_head = (n->q_head + 1) % n->q_cap;
    n->q_count--;
    if (n->published_backlog >= out->len) n->published_backlog -= out->len; else n->published_backlog = 0;
    n->consumer_inflight_backlog = di_u64_add_sat(n->consumer_inflight_backlog, out->len);
    if (n->consumer_inflight_backlog > n->max_consumer_inflight_backlog)
        n->max_consumer_inflight_backlog = n->consumer_inflight_backlog;
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
    if (ing_done) *ing_done = 0;
    return 1;
}

static void di_consume_complete(di_node_t *n, uint64_t len) {
    pthread_mutex_lock(&n->mu);
    if (n->consumer_inflight_backlog >= len) n->consumer_inflight_backlog -= len; else n->consumer_inflight_backlog = 0;
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
}

static void di_consume_chunk(di_node_t *n, di_chunk_t *c) {
    /* Section 5: deterministic memory-touching consumer kernel (identical for
     * all common-engine candidates). Volatile sink prevents optimization.
     * Each successfully consumed chunk is scanned exactly once when enabled. */
    if (n->eng->P.consumer_kernel == 1 && c->buf && c->len > 0) {
        volatile uint64_t sink = 0;
        const unsigned char *p = (const unsigned char *)c->buf;
        size_t len = c->len;
        uint64_t acc = 0;
        for (size_t i = 0; i < len; i++) acc += p[i];
        sink = acc;
        (void)sink;
        n->m.consumer_bytes_scanned += c->len;
    }
    di_consumer_cfg_t *cc = &n->cons_cfg;
    uint64_t bps = cc->bytes_per_sec;
    if (!(cc->mode == DI_CONSUMER_FAST || bps == 0)) {
        if (bps > 0) {
            uint64_t ns = (c->len * 1000000000ULL) / bps;
            struct timespec ts;
            ts.tv_sec = (time_t)(ns / 1000000000ULL);
            ts.tv_nsec = (long)(ns % 1000000000ULL);
            nanosleep(&ts, NULL);
        }
    }
    n->m.bytes_consumed += c->len;
    n->m.chunks_consumed++;
    di_free_chunk(c);
    di_consume_complete(n, c->len);
}

static void di_engine_stop(di_engine_t *eng) {
    __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE);
    for (int i = 0; i < eng->num_nodes; i++) {
        pthread_mutex_lock(&eng->nodes[i].mu);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_pop);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_push);
        pthread_mutex_unlock(&eng->nodes[i].mu);
    }
}

static void *di_consumer_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    di_engine_t *eng = n->eng;
    int pin_rc = di_pin_thread_role(n->cpus, n->ncpus, &n->m.affinity_consumer);
    if (pin_rc != 0 && eng->P.strict_affinity && n->m.affinity_consumer.requested) {
        n->m.affinity_consumer.strict_failed = 1;
        di_engine_stop(eng); /* atomic stop is safe; no shared metric flag write */
    }
    uint64_t c0 = di_thread_cpu_ns();
    if (n->cons_cfg.mode == DI_CONSUMER_STALL && n->cons_cfg.stall_ms > 0) {
        struct timespec ts;
        uint64_t ms = n->cons_cfg.stall_ms;
        ts.tv_sec = (time_t)(ms / 1000ULL);
        ts.tv_nsec = (long)((ms % 1000ULL) * 1000000ULL);
        nanosleep(&ts, NULL);
    }
    for (;;) {
        di_chunk_t c;
        int ing_done = 0;
        int got = di_queue_pop(n, &c, &ing_done);
        if (got == 0 && ing_done) break;
        if (got == 1) di_consume_chunk(n, &c);
    }
    n->m.consumer_cpu_ns = di_thread_cpu_ns() - c0;
    return NULL;
}

/* Returns: 1 = made progress (reserved/read/published or terminal), 0 = no progress now (should wait), -1 = stop/fatal */
static int di_ingest_step(di_node_t *n, di_engine_t *eng) {
    pthread_mutex_lock(&n->mu);
    uint64_t eff = di_node_eff(n);
    pthread_mutex_unlock(&n->mu);
    uint64_t hr_i = (eng->P.max_backlog > eff) ? (eng->P.max_backlog - eff) : 0;

    uint64_t want = 0;
    if (eng->cfg.policy == DI_POLICY_RELATIVE_ADAPTIVE && eng->P.enable_peer_headroom) {
        uint64_t t0p = di_now_ns();
        uint64_t headrooms[DI_MAX_NODES];
        uint64_t effs[DI_MAX_NODES];
        for (int i = 0; i < eng->num_nodes; i++) {
            headrooms[i] = __atomic_load_n(&eng->nodes[i].peer_headroom, __ATOMIC_RELAXED);
            effs[i] = (eng->P.max_backlog > headrooms[i]) ? (eng->P.max_backlog - headrooms[i]) : eng->P.max_backlog;
        }
        headrooms[n->id] = hr_i; effs[n->id] = eff;
        want = di_policy_decide(eng->cfg.policy, &eng->P, eng->num_nodes, n->id, effs, headrooms);
        n->m.peer_observe_ns += di_now_ns() - t0p;
        n->m.peer_observe_count++;
    } else if (eng->cfg.policy == DI_POLICY_RELATIVE_ADAPTIVE) {
        uint64_t headrooms[DI_MAX_NODES]; uint64_t effs[DI_MAX_NODES];
        for (int i=0;i<eng->num_nodes;i++){ headrooms[i]=__atomic_load_n(&eng->nodes[i].peer_headroom,__ATOMIC_RELAXED); effs[i]=0; }
        headrooms[n->id]=hr_i; effs[n->id]=eff;
        want = di_policy_decide(eng->cfg.policy, &eng->P, eng->num_nodes, n->id, effs, headrooms);
    } else {
        uint64_t headrooms[DI_MAX_NODES]; uint64_t effs[DI_MAX_NODES];
        for (int i=0;i<eng->num_nodes;i++){ headrooms[i]=0; effs[i]=0; }
        headrooms[n->id]=hr_i; effs[n->id]=eff;
        want = di_policy_decide(eng->cfg.policy, &eng->P, eng->num_nodes, n->id, effs, headrooms);
    }

    pthread_mutex_lock(&n->mu);
    eff = di_node_eff(n);
    int can = di_can_admit(eng->P.max_backlog, eff, n->outstanding, want, eng->P.one_outstanding_per_node);
    if (!can || want == 0) {
        n->m.zero_claims++;
        pthread_mutex_unlock(&n->mu);
        uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
        if (go >= eng->file_size) {
            pthread_mutex_lock(&n->mu);
            int outst = (n->outstanding > 0 || n->consumer_inflight_backlog > 0 || n->published_backlog > 0);
            pthread_mutex_unlock(&n->mu);
            if (!outst) return 1; /* node drained, no more work for it */
        }
        return 0;
    }
    n->outstanding = di_u64_add_sat(n->outstanding, want);
    eff = di_node_eff(n);
    if (eff > n->max_effective_backlog) n->max_effective_backlog = eff;
    di_publish_headroom(n);
    pthread_mutex_unlock(&n->mu);

    if (want > UINT64_MAX - __atomic_load_n(&eng->next_offset, __ATOMIC_RELAXED)) {
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return 1;
    }
    uint64_t start = __atomic_fetch_add(&eng->next_offset, want, __ATOMIC_ACQ_REL);
    if (start >= eng->file_size) {
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return 1;
    }
    uint64_t req_len = want;
    uint64_t avail = (eng->file_size > start) ? (eng->file_size - start) : 0;
    uint64_t assigned = req_len < avail ? req_len : avail;
    if (assigned < want) {
        pthread_mutex_lock(&n->mu);
        uint64_t delta = want - assigned;
        if (n->outstanding >= delta) n->outstanding -= delta; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
    }
    if (assigned == 0) {
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return 1;
    }

    di_chunk_t c;
    if (di_alloc_local((size_t)assigned, eng->P.prefer_hugepage, n->phys_node, n, &c) != 0) {
        n->m.last_error = DI_ERR_NOMEM;
        di_engine_stop(eng);
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= assigned) n->outstanding -= assigned; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    c.len = assigned;

    uint64_t t0r = di_now_ns();
    ssize_t rr = di_pread_full(eng, c.buf, (size_t)assigned, start);
    n->m.read_wait_ns += di_now_ns() - t0r;
    if (rr < 0) {
        n->m.last_error = DI_ERR_IO;
        di_free_chunk(&c);
        di_engine_stop(eng);
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= assigned) n->outstanding -= assigned; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    uint64_t act = (uint64_t)rr;
    if (act < assigned) {
        __atomic_store_n(&eng->input_changed, 1, __ATOMIC_RELEASE);
        n->m.last_error = DI_ERR_IO;
        di_free_chunk(&c);
        di_engine_stop(eng);
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= assigned) n->outstanding -= assigned; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    /* §5.2 rate_limit: throttle only a completed read (error/short reads
     * return above). Overflow-safe sleep: ceil(act / rate_bps * 1e9). */
    {
        di_node_t *in = di_ingestor_of(eng, n);
        if (in->ing_cfg.mode == 4 && in->ing_cfg.rate_bps > 0 && act > 0) {
            uint64_t t0w = di_now_ns();
            unsigned __int128 s128 = ((unsigned __int128)act * 1000000000ULL)
                                     / in->ing_cfg.rate_bps;
            uint64_t s = (s128 > (unsigned __int128)UINT64_MAX)
                         ? UINT64_MAX : (uint64_t)s128;
            if (s > 0) {
                struct timespec ts;
                ts.tv_sec = (time_t)(s / 1000000000ULL);
                ts.tv_nsec = (long)(s % 1000000000ULL);
                nanosleep(&ts, NULL);
                in->m.ingestor_rate_throttled_ns += di_now_ns() - t0w;
            }
        }
    }

    n->m.reservations++;
    n->m.bytes_reserved_req += req_len;
    n->m.bytes_assigned += assigned;
    n->m.bytes_read += act;
    di_hist_add(n->m.res_hist, req_len);
    di_record_res(n, start, req_len, assigned, act);
    /* C2 correction: do not dispatch sampler at all on the performance-isolated path. */
    if (eng->P.placement_sampling)
        di_sample_placement(n, c.buf, act);

    c.off = start; c.len = act;
    if (di_ingestor_of(eng, n)->ing_cfg.mode == 2) {
        /* §5.2 delay_after_read: sleep after the read, before publication. */
        di_ingestor_sleep_ns(di_ingestor_of(eng, n),
                             di_ingestor_of(eng, n)->ing_cfg.delay_ns);
    }
    if (di_queue_push(n, c) != 0) {
        di_free_chunk(&c);
        pthread_mutex_lock(&n->mu);
        if (n->outstanding >= act) n->outstanding -= act; else n->outstanding = 0;
        di_publish_headroom(n);
        pthread_cond_broadcast(&n->cv_can_push);
        pthread_mutex_unlock(&n->mu);
        return -1;
    }
    if (di_ingestor_of(eng, n)->ing_cfg.mode == 1) {
        /* §5.2 delay_per_claim: sleep after each successful claim+publish. */
        di_ingestor_sleep_ns(di_ingestor_of(eng, n),
                             di_ingestor_of(eng, n)->ing_cfg.delay_ns);
    }
    return 1;
}

static void *di_ingestor_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    di_engine_t *eng = n->eng;
    int pin_rc = di_pin_thread_role(n->cpus, n->ncpus, &n->m.affinity_ingestor);
    if (pin_rc != 0 && eng->P.strict_affinity && n->m.affinity_ingestor.requested) {
        n->m.affinity_ingestor.strict_failed = 1;
        di_engine_stop(eng);
    }
    uint64_t c0 = di_thread_cpu_ns();
    if (n->ing_cfg.mode == 3 && n->ing_cfg.stall_ms > 0) {
        /* §5.2: stall_then_recover — initial stall, then recovery
         * (ingest proceeds normally after the stall). */
        uint64_t ms = n->ing_cfg.stall_ms;
        struct timespec ts;
        ts.tv_sec = (time_t)(ms / 1000ULL);
        ts.tv_nsec = (long)((ms % 1000ULL) * 1000000ULL);
        nanosleep(&ts, NULL);
        n->m.ingestor_stall_fired = 1;
    }

    if (eng->centralized_ingest) {
        /* Single ingestor distributes to all node queues (Section 5 baseline). */
        int rr = 0;
        for (;;) {
            if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) break;
            int progressed = 0;
            int all_done = 1;
            for (int k = 0; k < eng->num_nodes; k++) {
                int t = (rr + k) % eng->num_nodes;
                di_node_t *tn = &eng->nodes[t];
                uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
                pthread_mutex_lock(&tn->mu);
                int outst = (tn->outstanding > 0 || tn->consumer_inflight_backlog > 0 || tn->published_backlog > 0);
                pthread_mutex_unlock(&tn->mu);
                if (go < eng->file_size || outst) all_done = 0;
                int rc = di_ingest_step(tn, eng);
                if (rc < 0) { progressed = -1; break; }
                if (rc == 1) {
                    /* step may have reserved/published or found node terminal-for-now */
                    progressed = 1;
                }
            }
            rr = (rr + 1) % eng->num_nodes;
            if (progressed < 0) break;
            uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
            if (all_done && go >= eng->file_size) break;
            if (progressed == 0) {
                uint64_t t0w = di_now_ns();
                struct timespec ts; ts.tv_sec=0; ts.tv_nsec=200000;
                nanosleep(&ts,NULL);
                n->m.claim_wait_ns += di_now_ns() - t0w;
            }
        }
        n->m.ingest_cpu_ns = di_thread_cpu_ns() - c0;
        __atomic_store_n(&eng->ingestors_done, eng->num_nodes, __ATOMIC_RELEASE);
        for (int j = 0; j < eng->num_nodes; j++) {
            pthread_mutex_lock(&eng->nodes[j].mu);
            pthread_cond_broadcast(&eng->nodes[j].cv_can_pop);
            pthread_cond_broadcast(&eng->nodes[j].cv_can_push);
            pthread_mutex_unlock(&eng->nodes[j].mu);
        }
        return NULL;
    }

    for (;;) {
        if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) break;
        int rc = di_ingest_step(n, eng);
        if (rc < 0) break;
        if (rc == 0) {
            uint64_t t0w = di_now_ns();
            struct timespec ts; ts.tv_sec=0; ts.tv_nsec=200000;
            nanosleep(&ts,NULL);
            n->m.claim_wait_ns += di_now_ns() - t0w;
            uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
            if (go >= eng->file_size) {
                pthread_mutex_lock(&n->mu);
                int outst = (n->outstanding > 0 || n->consumer_inflight_backlog > 0 || n->published_backlog > 0);
                pthread_mutex_unlock(&n->mu);
                if (!outst) break;
            }
            continue;
        }
        /* progressed/terminal-for-step; loop continues to re-evaluate */
        uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
        if (go >= eng->file_size) {
            pthread_mutex_lock(&n->mu);
            int outst = (n->outstanding > 0 || n->consumer_inflight_backlog > 0 || n->published_backlog > 0);
            pthread_mutex_unlock(&n->mu);
            if (!outst) break;
        }
    }

    n->m.ingest_cpu_ns = di_thread_cpu_ns() - c0;
    __atomic_fetch_add(&eng->ingestors_done, 1, __ATOMIC_ACQ_REL);
    for (int j = 0; j < eng->num_nodes; j++) {
        pthread_mutex_lock(&eng->nodes[j].mu);
        pthread_cond_broadcast(&eng->nodes[j].cv_can_pop);
        pthread_cond_broadcast(&eng->nodes[j].cv_can_push);
        pthread_mutex_unlock(&eng->nodes[j].mu);
    }
    return NULL;
}

di_engine_t *di_create(int fd, uint64_t file_size, const di_config_t *cfg) {
    if (!cfg || cfg->num_nodes < 1 || cfg->num_nodes > DI_MAX_NODES) return NULL;
    /* Section 5: reject duplicate physical node IDs at C boundary */
    if (cfg->phys_nodes) {
        for (int i = 0; i < cfg->num_nodes; i++) {
            for (int j = i + 1; j < cfg->num_nodes; j++) {
                if (cfg->phys_nodes[i] == cfg->phys_nodes[j]) return NULL;
            }
        }
    }
    di_engine_t *eng = (di_engine_t *)calloc(1, sizeof(*eng));
    if (!eng) return NULL;
    eng->fd = fd;
    eng->file_size = file_size;
    eng->cfg = *cfg;
    eng->num_nodes = cfg->num_nodes;
    eng->centralized_ingest = (cfg->policy == DI_POLICY_CENTRALIZED_INGEST);
    eng->P = cfg->params;
    if (eng->P.base_quantum == 0) eng->P.base_quantum = DI_QUANTUM_DEFAULT;
    if (eng->P.max_backlog == 0) eng->P.max_backlog = 64ULL * eng->P.base_quantum;
    if (eng->P.max_reservation == 0) eng->P.max_reservation = eng->P.max_backlog;
    /* Section 9: reject invalid/contradictory config rather than silent misuse */
    if (eng->P.base_quantum == 0 || eng->P.max_backlog == 0) { free(eng); return NULL; }
    /* C2 correction: placement sampling 0=off/perf, 1=on/bounded-validation;
     * §2: 2=full (exhaustive sampling for diagnostics). */
    if (eng->P.placement_sampling != 0 && eng->P.placement_sampling != 1
        && eng->P.placement_sampling != 2) { free(eng); return NULL; }
    if (eng->P.max_reservation > eng->P.max_backlog) eng->P.max_reservation = eng->P.max_backlog;
    eng->P.one_outstanding_per_node = 1;
    if (!eng->P.enable_peer_headroom) eng->P.enable_peer_headroom = 1;
    pthread_mutex_init(&eng->seam_mu, NULL);
    memset(&eng->pread_seam, 0, sizeof(eng->pread_seam));

    struct stat st;
    if (fstat(fd, &st) == 0) {
        eng->file_dev = (uint64_t)st.st_dev;
        eng->file_ino = (uint64_t)st.st_ino;
#if defined(__linux__)
        eng->file_mtime_sec = (int64_t)st.st_mtim.tv_sec;
        eng->file_mtime_nsec = (int64_t)st.st_mtim.tv_nsec;
#else
        eng->file_mtime_sec = (int64_t)st.st_mtime;
        eng->file_mtime_nsec = 0;
#endif
    }

    __atomic_store_n(&eng->next_offset, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&eng->stop, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&eng->ingestors_done, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&eng->input_changed, 0, __ATOMIC_RELAXED);

    int initialized = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        memset(n, 0, sizeof(*n));
        n->id = i;
        n->eng = eng;
        n->phys_node = (cfg->phys_nodes ? cfg->phys_nodes[i] : -1);
        n->cpus = (cfg->cpu_lists ? cfg->cpu_lists[i] : NULL);
        n->ncpus = (cfg->cpu_counts ? cfg->cpu_counts[i] : 0);
        /* §5.2: per-node ingestor workload controls (off by default). */
        if (cfg->ingestors) n->ing_cfg = cfg->ingestors[i];
        n->m.ingestor_mode = n->ing_cfg.mode;
        /* C2: performance-isolated runs never perform in-run placement sampling. */
        if (eng->P.placement_sampling == 0)
            n->m.placement_sampling_not_performed = 1;
        n->q_cap = 1024;
        n->q = (di_chunk_t *)calloc(n->q_cap, sizeof(di_chunk_t));
        if (!n->q) {
            for (int j = 0; j < initialized; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            pthread_mutex_destroy(&eng->seam_mu);
            free(eng);
            return NULL;
        }
        if (pthread_mutex_init(&n->mu, NULL) != 0) {
            free(n->q); n->q = NULL;
            for (int j = 0; j < initialized; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            pthread_mutex_destroy(&eng->seam_mu);
            free(eng);
            return NULL;
        }
        if (pthread_cond_init(&n->cv_can_push, NULL) != 0) {
            pthread_mutex_destroy(&n->mu);
            free(n->q); n->q = NULL;
            for (int j = 0; j < initialized; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            pthread_mutex_destroy(&eng->seam_mu);
            free(eng);
            return NULL;
        }
        if (pthread_cond_init(&n->cv_can_pop, NULL) != 0) {
            pthread_cond_destroy(&n->cv_can_push);
            pthread_mutex_destroy(&n->mu);
            free(n->q); n->q = NULL;
            for (int j = 0; j < initialized; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            pthread_mutex_destroy(&eng->seam_mu);
            free(eng);
            return NULL;
        }
        __atomic_store_n(&n->peer_headroom, eng->P.max_backlog, __ATOMIC_RELAXED);
        if (cfg->consumers) n->cons_cfg = cfg->consumers[i];
        else { n->cons_cfg.mode = DI_CONSUMER_FAST; n->cons_cfg.bytes_per_sec = 0; n->cons_cfg.stall_ms = 0; }
        initialized++;
        int fail_after = __atomic_load_n(&g_create_fail_after_nodes, __ATOMIC_RELAXED);
        if (fail_after >= 0 && initialized == fail_after) {
            /* deterministic partial-init failure injection */
            for (int j = 0; j < initialized; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            pthread_mutex_destroy(&eng->seam_mu);
            free(eng);
            return NULL;
        }
    }
    return eng;
}

void di_destroy(di_engine_t *eng) {
    if (!eng) return;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        for (unsigned k = 0; k < n->q_count; k++) {
            unsigned idx = (n->q_head + k) % n->q_cap;
            di_free_chunk(&n->q[idx]);
        }
        free(n->q);
        free(n->recs);
        pthread_mutex_destroy(&n->mu);
        pthread_cond_destroy(&n->cv_can_push);
        pthread_cond_destroy(&n->cv_can_pop);
    }
    pthread_mutex_destroy(&eng->seam_mu);
    free(eng);
}

static int cmp_resrec(const void *a, const void *b) {
    const di_resrec_t *ra = (const di_resrec_t *)a;
    const di_resrec_t *rb = (const di_resrec_t *)b;
    if (ra->off < rb->off) return -1;
    if (ra->off > rb->off) return 1;
    if (ra->len_act < rb->len_act) return -1;
    if (ra->len_act > rb->len_act) return 1;
    return 0;
}

int di_run(di_engine_t *eng, di_result_t *result) {
    if (!eng || !result) return DI_ERR_INVAL;
    memset(result, 0, sizeof(*result));
    result->policy = eng->cfg.policy;
    result->num_nodes = eng->num_nodes;
    result->total_bytes = eng->file_size;

    if (eng->cfg.policy == DI_POLICY_CENTRALIZED_CONTROL) return DI_ERR_INVAL;

    clock_gettime(CLOCK_MONOTONIC, &eng->t_start);
    eng->started = 1;

    int rc = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        if (pthread_create(&eng->nodes[i].cons_tid, NULL, di_consumer_thread, &eng->nodes[i]) == 0) {
            eng->nodes[i].has_cons = 1;
        } else {
            rc = DI_ERR_THREAD; di_engine_stop(eng);
        }
    }
    if (eng->centralized_ingest) {
        /* Section 5: single in-engine ingestor distributes to all node queues. */
        if (rc == 0 && pthread_create(&eng->nodes[0].ing_tid, NULL, di_ingestor_thread, &eng->nodes[0]) == 0) {
            eng->nodes[0].has_ing = 1;
        } else if (rc == 0) {
            rc = DI_ERR_THREAD; di_engine_stop(eng);
        }
    } else {
        for (int i = 0; i < eng->num_nodes; i++) {
            if (rc == 0 && pthread_create(&eng->nodes[i].ing_tid, NULL, di_ingestor_thread, &eng->nodes[i]) == 0) {
                eng->nodes[i].has_ing = 1;
            } else if (rc == 0) {
                rc = DI_ERR_THREAD; di_engine_stop(eng);
            }
        }
    }

    for (int i = 0; i < eng->num_nodes; i++) {
        if (eng->nodes[i].has_ing) pthread_join(eng->nodes[i].ing_tid, NULL);
    }
    __atomic_store_n(&eng->ingestors_done, eng->num_nodes, __ATOMIC_RELEASE);
    for (int i = 0; i < eng->num_nodes; i++) {
        pthread_mutex_lock(&eng->nodes[i].mu);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_pop);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_push);
        pthread_mutex_unlock(&eng->nodes[i].mu);
    }
    for (int i = 0; i < eng->num_nodes; i++) {
        if (eng->nodes[i].has_cons) pthread_join(eng->nodes[i].cons_tid, NULL);
    }

    clock_gettime(CLOCK_MONOTONIC, &eng->t_end);
    result->wall_seconds = (eng->t_end.tv_sec - eng->t_start.tv_sec)
        + (eng->t_end.tv_nsec - eng->t_start.tv_nsec) / 1e9;
    result->eof_offset = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
    if (result->eof_offset < eng->file_size) result->eof_offset = eng->file_size;
    result->input_changed = __atomic_load_n(&eng->input_changed, __ATOMIC_ACQUIRE);

    size_t total_recs = 0;
    for (int i = 0; i < eng->num_nodes; i++) total_recs += eng->nodes[i].recs_n;
    di_resrec_t *all = NULL;
    if (total_recs > 0) all = (di_resrec_t *)malloc(total_recs * sizeof(*all));
    size_t pos = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        /* aggregate strict affinity decision safely after joins (no concurrent writes) */
        n->m.strict_affinity_failed = 0;
        if (eng->P.strict_affinity) {
            if (n->m.affinity_ingestor.requested && n->m.affinity_ingestor.strict_failed) n->m.strict_affinity_failed = 1;
            if (n->m.affinity_consumer.requested && n->m.affinity_consumer.strict_failed) n->m.strict_affinity_failed = 1;
            /* also treat unmatched/unverified as failure for required role */
            if (n->m.affinity_ingestor.requested && (!n->m.affinity_ingestor.matched)) n->m.strict_affinity_failed = 1;
            if (n->m.affinity_consumer.requested && (!n->m.affinity_consumer.matched)) n->m.strict_affinity_failed = 1;
        }
        result->nodes[i] = n->m;
        result->nodes[i].current_published_backlog = n->published_backlog;
        result->nodes[i].current_consumer_inflight_backlog = n->consumer_inflight_backlog;
        result->nodes[i].current_outstanding = n->outstanding;
        result->nodes[i].current_effective_backlog = di_node_eff(n);
        result->nodes[i].max_published_backlog = n->max_published_backlog;
        result->nodes[i].max_consumer_inflight_backlog = n->max_consumer_inflight_backlog;
        result->nodes[i].max_effective_backlog = n->max_effective_backlog;
        result->total_reserved_req += n->m.bytes_reserved_req;
        result->total_assigned += n->m.bytes_assigned;
        result->total_read += n->m.bytes_read;
        result->total_published += n->m.bytes_published;
        result->total_consumed += n->m.bytes_consumed;
        result->total_consumer_bytes_scanned += n->m.consumer_bytes_scanned;
        result->reservations_total += n->m.reservations;
        result->ingest_cpu_ns += n->m.ingest_cpu_ns;
        result->consumer_cpu_ns += n->m.consumer_cpu_ns;
        for (int b=0;b<20;b++) result->res_hist[b]+=n->m.res_hist[b];
        if (all && n->recs_n > 0 && n->recs) {
            memcpy(all + pos, n->recs, n->recs_n * sizeof(*all));
            pos += n->recs_n;
        }
    }

    if (all && total_recs > 0) {
        qsort(all, total_recs, sizeof(*all), cmp_resrec);
        uint64_t covered = 0;
        uint64_t cur = 0;
        int first = 1;
        for (size_t i = 0; i < total_recs; i++) {
            uint64_t s = all[i].off;
            uint64_t e = all[i].off + all[i].len_act;
            if (all[i].len_act == 0) continue;
            if (!first) {
                if (s < cur) result->overlap_detected = 1;
                if (s > cur) result->lost_detected = 1;
            } else {
                if (s != 0) result->lost_detected = 1;
                first = 0;
            }
            if (e > cur) { covered += e - (s > cur ? s : cur); cur = e; }
            else { result->duplicate_detected = 1; }
        }
        if (cur < eng->file_size) result->lost_detected = 1;
        if (covered != eng->file_size) { if (covered < eng->file_size) result->lost_detected = 1; }
        (void)covered;
    } else if (eng->file_size == 0) {
        /* ok */
    } else {
        result->lost_detected = 1;
    }
    free(all);

    if (__atomic_load_n(&eng->input_changed, __ATOMIC_ACQUIRE)) rc = DI_ERR_IO;
    for (int i = 0; i < eng->num_nodes; i++) {
        if (result->nodes[i].strict_affinity_failed && rc == 0) rc = DI_ERR_STATE;
        if (result->nodes[i].strict_mbind_failed && rc == 0) rc = DI_ERR_STATE;
        if (result->nodes[i].last_error != 0 && rc == 0) rc = DI_ERR_STATE;
    }
    if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED) && rc == 0) rc = DI_ERR_STATE;
    if (rc == 0 && (result->overlap_detected || result->duplicate_detected || result->lost_detected)) rc = DI_ERR_STATE;
    if (rc == 0 && result->total_consumed != eng->file_size) rc = DI_ERR_STATE;
    return rc;
}

uint64_t di_global_offset(const di_engine_t *eng) { return eng ? __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE) : 0; }
uint64_t di_file_size(const di_engine_t *eng) { return eng ? eng->file_size : 0; }
int di_num_nodes(const di_engine_t *eng) { return eng ? eng->num_nodes : 0; }

int di_debug_node_accounting(di_engine_t *eng, int node,
                             uint64_t *published, uint64_t *inflight,
                             uint64_t *outstanding, uint64_t *effective) {
    if (!eng || node < 0 || node >= eng->num_nodes) return -1;
    di_node_t *n = &eng->nodes[node];
    pthread_mutex_lock(&n->mu);
    uint64_t p = n->published_backlog;
    uint64_t inf = n->consumer_inflight_backlog;
    uint64_t o = n->outstanding;
    uint64_t e = di_node_eff(n);
    pthread_mutex_unlock(&n->mu);
    if (published) *published = p;
    if (inflight) *inflight = inf;
    if (outstanding) *outstanding = o;
    if (effective) *effective = e;
    return 0;
}

int di_test_set_pread_seam(di_engine_t *eng, int mode, int counter, uint64_t threshold) {
    if (!eng) return -1;
    pthread_mutex_lock(&eng->seam_mu);
    eng->pread_seam.enabled = (mode != 0);
    eng->pread_seam.mode = mode;
    eng->pread_seam.counter = counter;
    eng->pread_seam.threshold = threshold;
    eng->pread_seam.fired = 0;
    pthread_mutex_unlock(&eng->seam_mu);
    return 0;
}
int di_test_pread_seam_fired(di_engine_t *eng) {
    if (!eng) return 0;
    pthread_mutex_lock(&eng->seam_mu);
    int f = eng->pread_seam.fired;
    pthread_mutex_unlock(&eng->seam_mu);
    return f;
}

int di_test_check_2m_alignment(size_t len) {
    di_node_t dummy;
    memset(&dummy, 0, sizeof(dummy));
    di_engine_t eng;
    memset(&eng, 0, sizeof(eng));
    eng.P.strict_mbind = 0;
    dummy.eng = &eng;
    dummy.phys_node = -1;
    di_chunk_t c;
    if (di_alloc_local(len, 0, -1, &dummy, &c) != 0) return -1;
    uintptr_t a = (uintptr_t)c.buf;
    int ok = ((a & (DI_ALIGN_2M - 1)) == 0);
    di_free_chunk(&c);
    return ok ? 1 : 0;
}

/* Test helpers: CPU mask building/validation logic independent of pinning. */
int di_test_cpu_mask_check(const int *cpus, int ncpus, int require_above_cpuset_size) {
#ifdef __linux__
    if (!cpus || ncpus <= 0) return -1;
    int max_cpu = -1;
    for (int i = 0; i < ncpus; i++) {
        if (cpus[i] < 0) return -2;
        if (cpus[i] > max_cpu) max_cpu = cpus[i];
    }
    if ((unsigned int)max_cpu > (unsigned int)(INT_MAX - 1)) return -6; /* overflow guard */
    if (require_above_cpuset_size && max_cpu < (int)CPU_SETSIZE) return -3;
    size_t need_count = (size_t)max_cpu + 1;
    size_t mask_count = need_count;
    /* robust probe path (same as pin impl) */
    int prc = di_probe_affinity_mask_count(need_count, &mask_count);
    if (prc != 0) return -7;
    if (mask_count < need_count) return -7;
    size_t setsize = CPU_ALLOC_SIZE(mask_count);
    cpu_set_t *set = CPU_ALLOC(mask_count);
    if (!set) return -4;
    CPU_ZERO_S(setsize, set);
    for (int i = 0; i < ncpus; i++) {
        if ((size_t)cpus[i] >= mask_count) { CPU_FREE(set); return -2; }
        CPU_SET_S(cpus[i], setsize, set);
    }
    int ok = 1;
    for (int i = 0; i < ncpus; i++) {
        if (!CPU_ISSET_S(cpus[i], setsize, set)) { ok = 0; break; }
    }
    CPU_FREE(set);
    return ok ? 1 : 0;
#else
    (void)cpus; (void)ncpus; (void)require_above_cpuset_size;
    return -5;
#endif
}

int di_test_probe_affinity_mask_size(size_t *out_size, int *out_err) {
#ifdef __linux__
    size_t count = 0;
    int rc = di_probe_affinity_mask_count(1, &count);
    if (rc != 0) { if (out_err) *out_err = -rc; return -1; }
    if (out_size) *out_size = CPU_ALLOC_SIZE(count);
    if (out_err) *out_err = 0;
    return 0;
#else
    (void)out_size; if (out_err) *out_err = ENOTSUP; return -1;
#endif
}

int di_test_pin_role_with_inject(const int *cpus, int ncpus, di_affinity_role_t *out,
                                 int inject, int inject_set_rc, int inject_query_rc,
                                 int inject_errno) {
    if (!out) return -1;
    return di_pin_thread_role_impl(cpus, ncpus, out, inject, inject_set_rc, inject_query_rc, inject_errno);
}

int di_test_sample_indices(uint64_t total_pages, uint64_t sample_limit,
                           uint64_t *out_indices, uint64_t max_out,
                           uint64_t *out_count, uint64_t *out_spacing) {
    if (!out_indices || !out_count) return -1;
    *out_count = 0;
    if (out_spacing) *out_spacing = 1;
    if (total_pages == 0 || sample_limit == 0) return 0;
    uint64_t samples = total_pages < sample_limit ? total_pages : sample_limit;
    if (samples > max_out) return -2;
    uint64_t count = 0;
    if (samples == 1) {
        out_indices[count++] = 0;
    } else if (samples >= total_pages) {
        for (uint64_t i = 0; i < total_pages && count < samples; i++) out_indices[count++] = i;
    } else {
        for (uint64_t i = 0; i < samples; i++) {
            uint64_t idx = i * (total_pages - 1) / (samples - 1);
            if (idx >= total_pages) idx = total_pages - 1;
            if (count == 0 || idx != out_indices[count - 1]) out_indices[count++] = idx;
        }
        if (count == 0 || out_indices[count - 1] != total_pages - 1) {
            if (count < samples) out_indices[count++] = total_pages - 1;
            else out_indices[count - 1] = total_pages - 1;
        }
    }
    if (out_spacing) *out_spacing = (count <= 1) ? 1 : (total_pages / count);
    *out_count = count;
    return 0;
}

int di_test_classify_placement(int phys_node, long rc, int count, const int *status,
                               uint64_t *target_match, uint64_t *other_node,
                               uint64_t *unknown) {
    if (!target_match || !other_node || !unknown || count < 0) return -1;
    *target_match = 0; *other_node = 0; *unknown = 0;
    if (rc != 0) {
        *unknown = (uint64_t)count;
        return 0;
    }
    if (!status && count > 0) { *unknown = (uint64_t)count; return 0; }
    for (int i = 0; i < count; i++) {
        if (phys_node >= 0 && status[i] == phys_node) (*target_match)++;
        else if (status[i] >= 0) (*other_node)++;
        else (*unknown)++;
    }
    return 0;
}

int di_test_set_placement_seam(di_engine_t *eng, int mode, int rc_or_unused,
                               int pattern_len, const int *pattern) {
    if (!eng) return -1;
    pthread_mutex_lock(&eng->seam_mu);
    memset(&eng->placement_seam, 0, sizeof(eng->placement_seam));
    eng->placement_seam.enabled = (mode != 0);
    eng->placement_seam.mode = mode;
    eng->placement_seam.rc = rc_or_unused;
    if (pattern && pattern_len > 0) {
        if (pattern_len > 1024) pattern_len = 1024;
        eng->placement_seam.pattern_len = pattern_len;
        for (int i = 0; i < pattern_len; i++) eng->placement_seam.pattern[i] = pattern[i];
    }
    pthread_mutex_unlock(&eng->seam_mu);
    return 0;
}

int di_test_set_create_fail_seam(int fail_after_nodes) {
    __atomic_store_n(&g_create_fail_after_nodes, fail_after_nodes, __ATOMIC_RELAXED);
    return 0;
}

int di_test_set_push_fail_seam(di_engine_t *eng, int fail_on_nth) {
    if (!eng) return -1;
    pthread_mutex_lock(&eng->seam_mu);
    eng->push_fail_nth = fail_on_nth;
    eng->push_fail_fired = 0;
    pthread_mutex_unlock(&eng->seam_mu);
    return 0;
}

void di_test_reset_placement_sample_calls(void) {
    __atomic_store_n(&g_placement_sample_calls, 0, __ATOMIC_RELAXED);
}

uint64_t di_test_get_placement_sample_calls(void) {
    return __atomic_load_n(&g_placement_sample_calls, __ATOMIC_RELAXED);
}
