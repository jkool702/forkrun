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

#ifdef __linux__
#include <numaif.h>
#endif

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
    /* reservation record for correctness validation */
    uint64_t off;
    uint64_t len_req;
    uint64_t len_assigned;
    uint64_t len_act;
} di_resrec_t;

typedef struct di_node {
    int id;
    int phys_node;
    di_engine_t *eng;
    pthread_t ing_tid;
    pthread_t cons_tid;
    int has_ing;
    int has_cons;

    /* queue of published chunks (consumer drains) */
    di_chunk_t *q;
    unsigned q_cap;
    unsigned q_head; /* next pop */
    unsigned q_tail; /* next push */
    unsigned q_count;
    pthread_mutex_t mu;
    pthread_cond_t cv_can_push; /* space/backlog released */
    pthread_cond_t cv_can_pop;  /* data available */

    /* accounting (bytes), protected by mu */
    uint64_t published_backlog;
    uint64_t consumer_inflight_backlog;
    uint64_t outstanding;
    uint64_t max_published_backlog;
    uint64_t max_consumer_inflight_backlog;
    uint64_t max_effective_backlog;

    /* advisory headroom published for peers (atomic, bytes) */
    _Atomic uint64_t peer_headroom;

    di_node_metrics_t m;
    di_consumer_cfg_t cons_cfg;

    /* reservation records */
    di_resrec_t *recs;
    size_t recs_n, recs_cap;

    /* affinity */
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

    _Atomic uint64_t next_offset; /* global FAA cursor (bytes) */
    _Atomic int stop;             /* fatal/error stop */
    _Atomic int ingestors_done;   /* count of ingestors finished */
    _Atomic int input_changed;

    int num_nodes;
    di_node_t nodes[DI_MAX_NODES];

    struct timespec t_start, t_end;
    int started;
};

static uint64_t di_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
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

    if (policy == DI_POLICY_FIXED_FAA) {
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
    uint64_t want = claim_quanta * quantum;
    if (want > hr_i) want = (hr_i / quantum) * quantum;
    if (want > max_res) want = (max_res / quantum) * quantum;
    if (want == 0) return 0;
    (void)effective_backlogs;
    return want;
}

static int di_pin_thread(const int *cpus, int ncpus, di_node_t *n) {
    if (!cpus || ncpus <= 0) {
        n->m.affinity_requested = 0;
        return 0;
    }
    n->m.affinity_requested = 1;
#ifdef __linux__
    cpu_set_t set;
    CPU_ZERO(&set);
    int any = 0;
    for (int i = 0; i < ncpus; i++) {
        if (cpus[i] >= 0 && cpus[i] < CPU_SETSIZE) { CPU_SET(cpus[i], &set); any = 1; }
    }
    if (!any) { n->m.affinity_error = EINVAL; return -1; }
    int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    if (rc != 0) { n->m.affinity_error = rc; return -1; }
    n->m.affinity_applied = 1;
    /* verify effective affinity */
    cpu_set_t got;
    CPU_ZERO(&got);
    if (pthread_getaffinity_np(pthread_self(), sizeof(got), &got) != 0) {
        n->m.affinity_error = errno ? errno : EINVAL;
        return -1;
    }
    for (int i = 0; i < ncpus; i++) {
        if (cpus[i] >= 0 && cpus[i] < CPU_SETSIZE && !CPU_ISSET(cpus[i], &got)) {
            n->m.affinity_error = EPERM;
            return -1;
        }
    }
    n->m.affinity_verified = 1;
    return 0;
#else
    n->m.affinity_error = ENOTSUP;
    return -1;
#endif
}

static int di_mbind_node(void *addr, size_t len, int phys_node, di_node_t *n) {
    n->m.mbind_requested = (phys_node >= 0);
    if (phys_node < 0) return 0;
#ifdef __linux__
    unsigned long maxnode = (unsigned long)phys_node + 2;
    size_t mask_bytes = (maxnode + 7UL) / 8UL;
    /* round up to unsigned long */
    size_t mask_ul = (mask_bytes + sizeof(unsigned long) - 1) / sizeof(unsigned long);
    unsigned long *mask = (unsigned long *)calloc(mask_ul ? mask_ul : 1, sizeof(unsigned long));
    if (!mask) { n->m.mbind_error = ENOMEM; return -1; }
    mask[phys_node / (int)(sizeof(unsigned long) * 8)] |= 1UL << (phys_node % (int)(sizeof(unsigned long) * 8));
    long rc = mbind(addr, len, MPOL_PREFERRED, mask, maxnode, 0);
    int err = errno;
    free(mask);
    if (rc != 0) { n->m.mbind_error = err ? err : EINVAL; return -1; }
    n->m.mbind_applied = 1;
    return 0;
#else
    n->m.mbind_error = ENOTSUP;
    return -1;
#endif
}

static int di_alloc_local(size_t len, int prefer_huge, int phys_node, di_node_t *n,
                          di_chunk_t *out) {
    memset(out, 0, sizeof(*out));
    if (len == 0) return -1;
    size_t aln = DI_ALIGN_2M;
    /* over-allocate to guarantee 2MiB-aligned usable buffer */
    size_t map_len = len + aln;
    if (map_len < len) return -1; /* overflow */
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
    void *map_base = MAP_FAILED;
    int used_huge = 0;
    if (prefer_huge) n->m.hugepage_map_requested_bytes += len;
#ifdef MAP_HUGETLB
    if (prefer_huge && map_len >= DI_ALIGN_2M) {
        map_base = mmap(NULL, map_len, PROT_READ | PROT_WRITE, flags | MAP_HUGETLB, -1, 0);
        if (map_base != MAP_FAILED) {
            used_huge = 1;
        }
    }
#endif
    if (map_base == MAP_FAILED) {
        map_base = mmap(NULL, map_len, PROT_READ | PROT_WRITE, flags, -1, 0);
    }
    if (map_base == MAP_FAILED) {
        return -1;
    }
    uintptr_t addr = (uintptr_t)map_base;
    uintptr_t aligned = (addr + aln - 1) & ~(uintptr_t)(aln - 1);
    void *usable = (void *)aligned;
    /* apply mbind to full mapping */
    int mbind_rc = di_mbind_node(map_base, map_len, phys_node, n);
    if (mbind_rc != 0 && n->eng->P.strict_mbind) {
        munmap(map_base, map_len);
        n->m.placement_strict_failed = 1;
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
    /* observed hugepage backing not reliably available; leave 0 */
    (void)usable;
    return 0;
}

static void di_free_chunk(di_chunk_t *c) {
    if (!c || !c->map_base || c->map_len == 0) return;
    munmap(c->map_base, c->map_len);
    c->buf = NULL;
    c->map_base = NULL;
    c->map_len = 0;
}

static int di_sample_placement(di_node_t *n, void *buf, size_t len) {
#if defined(__linux__) && defined(__NR_move_pages)
    if (!buf || len == 0) return 0;
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return 0;
    size_t total_pages = (len + (size_t)page - 1) / (size_t)page;
    size_t sample_cap = 1024;
    size_t pages = total_pages < sample_cap ? total_pages : sample_cap;
    n->m.placement_samples += pages;
    n->m.placement_sample_cap = sample_cap;
    void **addrs = (void **)calloc(pages, sizeof(void *));
    int *status = (int *)calloc(pages, sizeof(int));
    if (!addrs || !status) { free(addrs); free(status); n->m.unknown_pages += pages; return -1; }
    for (size_t i = 0; i < pages; i++) addrs[i] = (char *)buf + i * (size_t)page;
    long rc = syscall(__NR_move_pages, 0, (unsigned long)pages, addrs, NULL, status, 0);
    if (rc == 0) {
        for (size_t i = 0; i < pages; i++) {
            if (n->phys_node >= 0 && status[i] == n->phys_node) n->m.local_pages++;
            else if (status[i] >= 0) n->m.remote_pages++;
            else n->m.unknown_pages++; /* negative => unknown/permission denied etc */
        }
    } else {
        n->m.unknown_pages += pages;
    }
    free(addrs); free(status);
#else
    (void)n; (void)buf; (void)len;
#endif
    return 0;
}

/* --- narrow test seam for S3 fault injection (no effect unless enabled) --- */
typedef struct {
    int enabled;
    int mode;            /* 0=off,1=eintr_count,2=partial_max,3=premature_eof_at,4=error_at */
    int counter;         /* remaining injections / partial max bytes */
    uint64_t threshold;  /* byte offset threshold for modes 3/4 */
    int fired;
} di_test_pread_seam_t;
static di_test_pread_seam_t g_pread_seam = {0,0,0,0,0};

int di_test_set_pread_seam(int mode, int counter, uint64_t threshold) {
    g_pread_seam.enabled = (mode != 0);
    g_pread_seam.mode = mode;
    g_pread_seam.counter = counter;
    g_pread_seam.threshold = threshold;
    g_pread_seam.fired = 0;
    return 0;
}
int di_test_pread_seam_fired(void) { return g_pread_seam.fired; }

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

/* Robust positioned read: fill [off, off+len) unless genuine EOF/error. */
static ssize_t di_pread_full(di_engine_t *eng, void *buf, size_t len, uint64_t off) {
    size_t done = 0;
    while (done < len) {
        if (di_check_input_unchanged(eng) != 0) {
            __atomic_store_n(&eng->input_changed, 1, __ATOMIC_RELEASE);
            errno = EIO;
            return -1;
        }
        if (off + done > (uint64_t)LLONG_MAX) { errno = EOVERFLOW; return -1; }
        size_t want = len - done;
        /* fault injection seam */
        int inject_eintr = 0;
        if (g_pread_seam.enabled) {
            if (g_pread_seam.mode == 1 && g_pread_seam.counter > 0) {
                g_pread_seam.counter--; g_pread_seam.fired = 1; inject_eintr = 1;
            }
        }
        ssize_t rr;
        if (inject_eintr) {
            errno = EINTR;
            rr = -1;
        } else {
            rr = pread(eng->fd, (char *)buf + done, want, (off_t)(off + done));
        }
        if (g_pread_seam.enabled && rr >= 0) {
            if (g_pread_seam.mode == 2 && g_pread_seam.counter > 0 && rr > 0) { /* partial max */
                size_t cap = (size_t)g_pread_seam.counter;
                if ((size_t)rr > cap) { rr = (ssize_t)cap; g_pread_seam.fired = 1; }
            } else if (g_pread_seam.mode == 3 && (off + done) >= g_pread_seam.threshold) { /* premature EOF */
                rr = 0; g_pread_seam.fired = 1;
            } else if (g_pread_seam.mode == 4 && (off + done) >= g_pread_seam.threshold) { /* error */
                errno = EIO; rr = -1; g_pread_seam.fired = 1;
            }
        }
        if (rr < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (rr == 0) {
            break; /* EOF */
        }
        done += (size_t)rr;
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
    n->q[n->q_tail] = c;
    n->q_tail = (n->q_tail + 1) % n->q_cap;
    n->q_count++;
    /* accounting: move outstanding -> published */
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
            return 0; /* empty & done */
        }
        uint64_t t0 = di_now_ns();
        pthread_cond_wait(&n->cv_can_pop, &n->mu);
        n->m.consume_wait_ns += di_now_ns() - t0;
    }
    *out = n->q[n->q_head];
    n->q_head = (n->q_head + 1) % n->q_cap;
    n->q_count--;
    /* move published -> consumer inflight (no headroom change) */
    if (n->published_backlog >= out->len) n->published_backlog -= out->len; else n->published_backlog = 0;
    n->consumer_inflight_backlog = di_u64_add_sat(n->consumer_inflight_backlog, out->len);
    if (n->consumer_inflight_backlog > n->max_consumer_inflight_backlog)
        n->max_consumer_inflight_backlog = n->consumer_inflight_backlog;
    /* effective unchanged, but republish headroom for consistency */
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
    if (ing_done) *ing_done = 0;
    return 1;
}

static void di_consume_complete(di_node_t *n, uint64_t len) {
    pthread_mutex_lock(&n->mu);
    if (n->consumer_inflight_backlog >= len) n->consumer_inflight_backlog -= len; else n->consumer_inflight_backlog = 0;
    /* headroom increases now */
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
}

static void di_consume_chunk(di_node_t *n, di_chunk_t *c) {
    di_consumer_cfg_t *cc = &n->cons_cfg;
    /* STALL initial sleep is handled once at consumer thread start */
    uint64_t bps = cc->bytes_per_sec;
    if (cc->mode == DI_CONSUMER_FAST || bps == 0) {
        /* immediate */
    } else {
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

static void *di_consumer_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    /* affinity */
    int pin_rc = di_pin_thread(n->cpus, n->ncpus, n);
    if (pin_rc != 0 && n->eng->P.strict_affinity) {
        n->m.placement_strict_failed = 1;
        di_engine_stop(n->eng);
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

static void di_engine_stop(di_engine_t *eng) {
    __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE);
    /* wake all */
    for (int i = 0; i < eng->num_nodes; i++) {
        pthread_mutex_lock(&eng->nodes[i].mu);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_pop);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_push);
        pthread_mutex_unlock(&eng->nodes[i].mu);
    }
}

static void *di_ingestor_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    di_engine_t *eng = n->eng;
    int pin_rc = di_pin_thread(n->cpus, n->ncpus, n);
    if (pin_rc != 0 && eng->P.strict_affinity) {
        n->m.placement_strict_failed = 1;
        di_engine_stop(eng);
    }
    uint64_t c0 = di_thread_cpu_ns();

    for (;;) {
        if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) break;

        /* snapshot accounting for admission/policy */
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
            headrooms[n->id] = hr_i;
            effs[n->id] = eff;
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
            uint64_t t0w = di_now_ns();
            struct timespec ts; ts.tv_sec=0; ts.tv_nsec=200000; /* 0.2ms */
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
        /* admit */
        n->outstanding = di_u64_add_sat(n->outstanding, want);
        eff = di_node_eff(n);
        if (eff > n->max_effective_backlog) n->max_effective_backlog = eff;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);

        /* FAA reserve */
        uint64_t start = __atomic_fetch_add(&eng->next_offset, want, __ATOMIC_ACQ_REL);
        if (start >= eng->file_size) {
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }
        uint64_t req_len = want;
        uint64_t avail = (eng->file_size > start) ? (eng->file_size - start) : 0;
        uint64_t assigned = req_len < avail ? req_len : avail;
        /* bytes beyond EOF in reservation are not real input; reduce outstanding for excess now */
        if (assigned < want) {
            pthread_mutex_lock(&n->mu);
            uint64_t delta = want - assigned;
            if (n->outstanding >= delta) n->outstanding -= delta; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
        }
        if (assigned == 0) {
            /* nothing to read */
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }

        di_chunk_t c;
        if (di_alloc_local((size_t)assigned, eng->P.prefer_hugepage, n->phys_node, n, &c) != 0) {
            n->m.last_error = DI_ERR_NOMEM;
            di_engine_stop(eng);
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= assigned) n->outstanding -= assigned; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
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
            break;
        }
        uint64_t act = (uint64_t)rr;
        /* if we couldn't fill assigned bytes, input must have ended/changed unexpectedly
           unless it's genuine EOF at file_size boundary - but assigned was capped to file_size-start */
        if (act < assigned) {
            /* premature EOF / truncation relative to captured file */
            __atomic_store_n(&eng->input_changed, 1, __ATOMIC_RELEASE);
            n->m.last_error = DI_ERR_IO;
            di_free_chunk(&c);
            di_engine_stop(eng);
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= assigned) n->outstanding -= assigned; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }

        n->m.reservations++;
        n->m.bytes_reserved_req += req_len;
        n->m.bytes_assigned += assigned;
        n->m.bytes_read += act;
        di_hist_add(n->m.res_hist, req_len);
        di_record_res(n, start, req_len, assigned, act);
        di_sample_placement(n, c.buf, act);

        c.off = start; c.len = act;
        if (di_queue_push(n, c) != 0) {
            /* publication failed (stopped) - rollback outstanding for this chunk was moved in push? no, push failed before move */
            di_free_chunk(&c);
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= act) n->outstanding -= act; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_cond_broadcast(&n->cv_can_push);
            pthread_mutex_unlock(&n->mu);
            break;
        }
    }

    n->m.ingest_cpu_ns = di_thread_cpu_ns() - c0;
    __atomic_fetch_add(&eng->ingestors_done, 1, __ATOMIC_ACQ_REL);
    /* wake consumers to notice completion (do not force stop on clean path) */
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
    di_engine_t *eng = (di_engine_t *)calloc(1, sizeof(*eng));
    if (!eng) return NULL;
    eng->fd = fd;
    eng->file_size = file_size;
    eng->cfg = *cfg;
    eng->num_nodes = cfg->num_nodes;
    eng->P = cfg->params;
    if (eng->P.base_quantum == 0) eng->P.base_quantum = DI_QUANTUM_DEFAULT;
    if (eng->P.max_backlog == 0) eng->P.max_backlog = 64ULL * eng->P.base_quantum;
    if (eng->P.max_reservation == 0) eng->P.max_reservation = eng->P.max_backlog;
    eng->P.one_outstanding_per_node = 1; /* enforced */
    if (!eng->P.enable_peer_headroom) eng->P.enable_peer_headroom = 1;

    /* capture file identity for immutability checks */
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

    int ok_nodes = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        memset(n, 0, sizeof(*n));
        n->id = i;
        n->eng = eng;
        n->phys_node = (cfg->phys_nodes ? cfg->phys_nodes[i] : -1);
        n->cpus = (cfg->cpu_lists ? cfg->cpu_lists[i] : NULL);
        n->ncpus = (cfg->cpu_counts ? cfg->cpu_counts[i] : 0);
        n->q_cap = 1024;
        n->q = (di_chunk_t *)calloc(n->q_cap, sizeof(di_chunk_t));
        if (!n->q) {
            /* cleanup partial: destroy nodes [0..i-1] */
            for (int j = 0; j < i; j++) {
                di_node_t *pj = &eng->nodes[j];
                free(pj->q); pj->q = NULL;
                pthread_mutex_destroy(&pj->mu);
                pthread_cond_destroy(&pj->cv_can_push);
                pthread_cond_destroy(&pj->cv_can_pop);
            }
            free(eng);
            return NULL;
        }
        pthread_mutex_init(&n->mu, NULL);
        pthread_cond_init(&n->cv_can_push, NULL);
        pthread_cond_init(&n->cv_can_pop, NULL);
        __atomic_store_n(&n->peer_headroom, eng->P.max_backlog, __ATOMIC_RELAXED);
        if (cfg->consumers) n->cons_cfg = cfg->consumers[i];
        else { n->cons_cfg.mode = DI_CONSUMER_FAST; n->cons_cfg.bytes_per_sec = 0; n->cons_cfg.stall_ms = 0; }
        ok_nodes++;
    }
    (void)ok_nodes;
    return eng;
}

void di_destroy(di_engine_t *eng) {
    if (!eng) return;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        /* free any leftover queued chunks */
        for (unsigned k = 0; k < n->q_count; k++) {
            unsigned idx = (n->q_head + k) % n->q_cap;
            di_free_chunk(&n->q[idx]);
        }
        /* if any consumer inflight chunks remain (shouldn't in normal destroy after run), cannot reach them here
           because they were popped; normal lifecycle frees on consume. */
        free(n->q);
        free(n->recs);
        pthread_mutex_destroy(&n->mu);
        pthread_cond_destroy(&n->cv_can_push);
        pthread_cond_destroy(&n->cv_can_pop);
    }
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

    if (eng->cfg.policy == DI_POLICY_CENTRALIZED_CONTROL) {
        return DI_ERR_INVAL;
    }

    clock_gettime(CLOCK_MONOTONIC, &eng->t_start);
    eng->started = 1;

    int rc = 0;
    int created_cons = 0, created_ing = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        if (pthread_create(&eng->nodes[i].cons_tid, NULL, di_consumer_thread, &eng->nodes[i]) == 0) {
            eng->nodes[i].has_cons = 1; created_cons++;
        } else {
            rc = DI_ERR_THREAD; di_engine_stop(eng);
        }
    }
    for (int i = 0; i < eng->num_nodes; i++) {
        if (rc == 0 && pthread_create(&eng->nodes[i].ing_tid, NULL, di_ingestor_thread, &eng->nodes[i]) == 0) {
            eng->nodes[i].has_ing = 1; created_ing++;
        } else if (rc == 0) {
            rc = DI_ERR_THREAD; di_engine_stop(eng);
        }
    }

    /* join ingestors */
    for (int i = 0; i < eng->num_nodes; i++) {
        if (eng->nodes[i].has_ing) pthread_join(eng->nodes[i].ing_tid, NULL);
    }
    __atomic_store_n(&eng->ingestors_done, eng->num_nodes, __ATOMIC_RELEASE);
    /* wake consumers */
    for (int i = 0; i < eng->num_nodes; i++) {
        pthread_mutex_lock(&eng->nodes[i].mu);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_pop);
        pthread_cond_broadcast(&eng->nodes[i].cv_can_push);
        pthread_mutex_unlock(&eng->nodes[i].mu);
    }
    for (int i = 0; i < eng->num_nodes; i++) {
        if (eng->nodes[i].has_cons) pthread_join(eng->nodes[i].cons_tid, NULL);
    }
    (void)created_cons; (void)created_ing;

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
        result->reservations_total += n->m.reservations;
        result->ingest_cpu_ns += n->m.ingest_cpu_ns;
        result->consumer_cpu_ns += n->m.consumer_cpu_ns;
        for (int b=0;b<20;b++) result->res_hist[b]+=n->m.res_hist[b];
        if (all) {
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
        if (covered != eng->file_size) {
            if (covered < eng->file_size) result->lost_detected = 1;
        }
        (void)covered;
    } else if (eng->file_size == 0) {
        /* ok */
    } else {
        result->lost_detected = 1;
    }
    free(all);

    if (__atomic_load_n(&eng->input_changed, __ATOMIC_ACQUIRE)) rc = DI_ERR_IO;
    /* if any node had placement strict failure or last_error indicating fatal issue, treat as error */
    for (int i = 0; i < eng->num_nodes; i++) {
        if (result->nodes[i].placement_strict_failed && rc == 0) rc = DI_ERR_STATE;
        if (result->nodes[i].last_error != 0 && rc == 0) rc = DI_ERR_STATE;
    }
    /* stop requested due to fatal error paths */
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
