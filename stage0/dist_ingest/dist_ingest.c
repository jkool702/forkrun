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

typedef struct {
    uint64_t off;
    uint64_t len;
    void *buf;
    size_t buf_cap;
} di_chunk_t;

typedef struct {
    /* reservation record for correctness validation */
    uint64_t off;
    uint64_t len_req;
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

    /* accounting (bytes), protected by mu for published/outstanding transitions
     * that cross threads; some counters are node-thread-local then merged. */
    uint64_t published_backlog;
    uint64_t outstanding;
    uint64_t max_published_backlog;
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
    di_config_t cfg;
    di_policy_params_t P;

    _Atomic uint64_t next_offset; /* global FAA cursor (bytes) */
    _Atomic int stop;             /* fatal/error stop */
    _Atomic int ingestors_done;   /* count of ingestors finished */

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

static uint64_t di_min_u64(uint64_t a, uint64_t b) { return a < b ? a : b; }
static uint64_t di_max_u64(uint64_t a, uint64_t b) { return a > b ? a : b; }

static void di_hist_add(uint64_t *hist, uint64_t sz) {
    /* buckets: <=4K,8K,16K,32K,64K,128K,256K,512K,1M,2M,4M,8M,16M,32M,64M,128M,256M,512M,1G,>=2G */
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

uint64_t di_effective_backlog(uint64_t published_backlog, uint64_t outstanding) {
    if (UINT64_MAX - published_backlog < outstanding) return UINT64_MAX;
    return published_backlog + outstanding;
}

int di_can_admit(uint64_t max_backlog, uint64_t effective_backlog_v,
                 uint64_t outstanding, uint64_t want, int one_outstanding) {
    if (want == 0) return 0;
    if (one_outstanding && outstanding > 0) return 0;
    if (effective_backlog_v > max_backlog) return 0;
    if (want > max_backlog - effective_backlog_v) return 0;
    return 1;
}

static int di_record_res(di_node_t *n, uint64_t off, uint64_t req, uint64_t act) {
    if (n->recs_n == n->recs_cap) {
        size_t nc = n->recs_cap ? n->recs_cap * 2 : 64;
        di_resrec_t *nr = (di_resrec_t *)realloc(n->recs, nc * sizeof(*nr));
        if (!nr) return -1;
        n->recs = nr;
        n->recs_cap = nc;
    }
    n->recs[n->recs_n].off = off;
    n->recs[n->recs_n].len_req = req;
    n->recs[n->recs_n].len_act = act;
    n->recs_n++;
    return 0;
}

static void di_publish_headroom(di_node_t *n) {
    di_engine_t *eng = n->eng;
    uint64_t eff = di_effective_backlog(n->published_backlog, n->outstanding);
    uint64_t hr = 0;
    if (eng->P.max_backlog > eff) hr = eng->P.max_backlog - eff;
    __atomic_store_n(&n->peer_headroom, hr, __ATOMIC_RELAXED);
}

static uint64_t di_read_peer_headroom_sum_others(di_engine_t *eng, int self, uint64_t *self_hr_out) {
    uint64_t sum = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        uint64_t hr = __atomic_load_n(&eng->nodes[i].peer_headroom, __ATOMIC_RELAXED);
        if (i == self) {
            if (self_hr_out) *self_hr_out = hr;
        } else {
            /* saturating add */
            if (UINT64_MAX - sum < hr) sum = UINT64_MAX; else sum += hr;
        }
    }
    return sum;
}

static uint64_t di_quanta_for_bytes(uint64_t bytes, uint64_t quantum, int round_mode) {
    if (quantum == 0) return 0;
    uint64_t q = bytes / quantum;
    uint64_t rem = bytes % quantum;
    if (rem == 0) return q;
    if (round_mode == 2) return q + 1; /* ceil */
    if (round_mode == 1) { /* nearest */
        if (rem * 2 >= quantum) return q + 1;
        return q;
    }
    return q; /* floor */
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
            /* single node: behave like local headroom */
            claim_quanta = hr_i / quantum;
        } else {
            /* S_i = sum of other headrooms */
            unsigned __int128 S_i = 0;
            for (int j = 0; j < num_nodes; j++) {
                if (j == node_i) continue;
                S_i += (unsigned __int128)headrooms[j];
            }
            if (S_i == 0) {
                /* peers have no headroom; claim up to local capacity */
                claim_quanta = hr_i / quantum;
            } else {
                /* R_i = K * M_i / S_i (in bytes/headroom units). Convert to quanta:
                 * want_quanta ~= R_i * (1 quantum worth?) better: target_bytes = K*M_i*M? No.
                 * Spec: R_i = M_local/avg(M_nonlocal) = K*M_i/S_i. Claim proportional to R_i in quanta.
                 * One base quantum when comparable (R_i ~ 1). */
                unsigned __int128 numer = (unsigned __int128)K * (unsigned __int128)hr_i;
                /* claim_quanta = round(numer / S_i) */
                unsigned __int128 q = numer / S_i;
                unsigned __int128 rem = numer % S_i;
                int rm = params->relative_rounding;
                if (rm == 2 && rem != 0) q += 1;
                else if (rm == 1 && rem * 2 >= S_i) q += 1;
                /* floor when rm==0 */
                if (q > (unsigned __int128)UINT64_MAX) claim_quanta = UINT64_MAX;
                else claim_quanta = (uint64_t)q;
            }
        }
        if (claim_quanta < params->rel_min_claim) claim_quanta = 0; /* below threshold => reduce/zero */
        uint64_t capq = params->rel_max_claim_quanta;
        if (capq == 0) {
            capq = max_backlog / quantum;
            if (capq == 0) capq = 1;
        }
        if (claim_quanta > capq) claim_quanta = capq;
    } else {
        /* control or unknown: no distributed claim */
        claim_quanta = 0;
    }

    if (claim_quanta == 0) return 0;
    uint64_t want = claim_quanta * quantum;
    /* cap by local headroom and max_reservation/backlog */
    if (want > hr_i) want = (hr_i / quantum) * quantum;
    if (want > max_res) want = (max_res / quantum) * quantum;
    if (want == 0) {
        /* if at least quantum fits, handled above; if hr_i < quantum but >0, allow sub-quantum? no: keep multiples */
        return 0;
    }
    /* effective backlog cap already reflected in hr_i; outstanding constraint handled by caller */
    (void)effective_backlogs;
    return want;
}

static int di_pin_thread(const int *cpus, int ncpus) {
    if (!cpus || ncpus <= 0) return -1;
#ifdef __linux__
    cpu_set_t set;
    CPU_ZERO(&set);
    for (int i = 0; i < ncpus; i++) {
        if (cpus[i] >= 0 && cpus[i] < CPU_SETSIZE) CPU_SET(cpus[i], &set);
    }
    return pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
#else
    (void)cpus; (void)ncpus; return -1;
#endif
}

static void *di_alloc_local(size_t len, int prefer_huge, int phys_node, int *used_huge) {
    if (used_huge) *used_huge = 0;
    size_t aln = DI_ALIGN_2M;
    size_t cap = (len + aln - 1) & ~(aln - 1);
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
#ifdef MAP_HUGETLB
    void *p = MAP_FAILED;
    if (prefer_huge && cap >= DI_ALIGN_2M) {
        /* best-effort hugepage mapping */
        p = mmap(NULL, cap, PROT_READ | PROT_WRITE,
                 flags | MAP_HUGETLB, -1, 0);
        if (p != MAP_FAILED) {
            if (used_huge) *used_huge = 1;
            goto placed;
        }
    }
    p = mmap(NULL, cap, PROT_READ | PROT_WRITE, flags, -1, 0);
#else
    void *p = mmap(NULL, cap, PROT_READ | PROT_WRITE, flags, -1, 0);
#endif
    if (p == MAP_FAILED) {
        /* fallback aligned alloc */
        void *q = NULL;
        if (posix_memalign(&q, 4096, len) == 0) return q;
        return NULL;
    }
placed:
#ifdef __linux__
    if (phys_node >= 0) {
        unsigned long nodemask = 1UL << (phys_node < (int)(sizeof(unsigned long)*8) ? phys_node : 0);
        /* best-effort mbind */
        (void)mbind(p, cap, MPOL_PREFERRED, &nodemask,
                    sizeof(unsigned long) * 8, 0);
    }
#else
    (void)phys_node;
#endif
    (void)prefer_huge;
    return p;
}

static void di_free_local(void *buf, size_t cap) {
    if (!buf) return;
    size_t aln = DI_ALIGN_2M;
    size_t mcap = (cap + aln - 1) & ~(aln - 1);
    if (munmap(buf, mcap) != 0) {
        free(buf);
    }
}

static int di_sample_placement(di_node_t *n, void *buf, size_t len) {
#if defined(__linux__) && defined(__NR_move_pages)
    if (!buf || len == 0) return 0;
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return 0;
    size_t pages = (len + (size_t)page - 1) / (size_t)page;
    if (pages > 1024) pages = 1024; /* sample cap */
    void **addrs = (void **)calloc(pages, sizeof(void *));
    int *status = (int *)calloc(pages, sizeof(int));
    if (!addrs || !status) { free(addrs); free(status); return -1; }
    for (size_t i = 0; i < pages; i++) addrs[i] = (char *)buf + i * (size_t)page;
    long rc = syscall(__NR_move_pages, 0, (unsigned long)pages, addrs, NULL, status, 0);
    if (rc == 0) {
        for (size_t i = 0; i < pages; i++) {
            if (status[i] == n->phys_node) n->m.local_pages++;
            else if (status[i] >= 0) n->m.remote_pages++;
            else n->m.unknown_pages++;
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
    n->published_backlog += c.len;
    if (n->published_backlog > n->max_published_backlog) n->max_published_backlog = n->published_backlog;
    uint64_t eff = di_effective_backlog(n->published_backlog, n->outstanding);
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
    if (n->published_backlog >= out->len) n->published_backlog -= out->len; else n->published_backlog = 0;
    di_publish_headroom(n);
    pthread_cond_signal(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
    if (ing_done) *ing_done = 0;
    return 1;
}

static void di_consume_chunk(di_node_t *n, di_chunk_t *c) {
    di_consumer_cfg_t *cc = &n->cons_cfg;
    /* stall once at beginning if configured */
    if (cc->mode == DI_CONSUMER_STALL && cc->stall_ms > 0) {
        /* handled per-consumer start via one-shot in thread; approximate here by sleeping if bytes_per_sec==0 marker not needed */
    }
    uint64_t bps = cc->bytes_per_sec;
    if (cc->mode == DI_CONSUMER_FAST || bps == 0) {
        /* immediate */
    } else {
        /* simulate rate: sleep proportional to chunk size */
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
    di_free_local(c->buf, c->buf_cap);
    c->buf = NULL;
}

static void *di_consumer_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    di_engine_t *eng = n->eng;
    (void)eng;
    di_pin_thread(n->cpus, n->ncpus);
    uint64_t c0 = di_thread_cpu_ns();
    /* initial stall */
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

static void *di_ingestor_thread(void *arg) {
    di_node_t *n = (di_node_t *)arg;
    di_engine_t *eng = n->eng;
    di_pin_thread(n->cpus, n->ncpus);
    uint64_t c0 = di_thread_cpu_ns();
    (void)eng->P.base_quantum;

    for (;;) {
        if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED)) break;

        /* snapshot accounting for admission/policy */
        pthread_mutex_lock(&n->mu);
        uint64_t published = n->published_backlog;
        uint64_t outstanding = n->outstanding;
        pthread_mutex_unlock(&n->mu);
        uint64_t eff = di_effective_backlog(published, outstanding);
        uint64_t hr_i = (eng->P.max_backlog > eff) ? (eng->P.max_backlog - eff) : 0;

        /* gather peer headrooms (advisory) for relative policy */
        uint64_t want = 0;
        if (eng->cfg.policy == DI_POLICY_RELATIVE_ADAPTIVE && eng->P.enable_peer_headroom) {
            uint64_t t0p = di_now_ns();
            uint64_t headrooms[DI_MAX_NODES];
            uint64_t effs[DI_MAX_NODES];
            for (int i = 0; i < eng->num_nodes; i++) {
                headrooms[i] = __atomic_load_n(&eng->nodes[i].peer_headroom, __ATOMIC_RELAXED);
                effs[i] = (eng->P.max_backlog > headrooms[i]) ? (eng->P.max_backlog - headrooms[i]) : eng->P.max_backlog;
            }
            /* ensure our local view is consistent/authoritative for self */
            headrooms[n->id] = hr_i;
            effs[n->id] = eff;
            want = di_policy_decide(eng->cfg.policy, &eng->P, eng->num_nodes, n->id, effs, headrooms);
            n->m.peer_observe_ns += di_now_ns() - t0p;
            n->m.peer_observe_count++;
        } else if (eng->cfg.policy == DI_POLICY_RELATIVE_ADAPTIVE) {
            /* no peer observation enabled: fall back to local snapshot as best-effort */
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

        /* enforce admission and one-outstanding with authoritative local state */
        pthread_mutex_lock(&n->mu);
        published = n->published_backlog; outstanding = n->outstanding; eff = di_effective_backlog(published, outstanding);
        int can = di_can_admit(eng->P.max_backlog, eff, outstanding, want, eng->P.one_outstanding_per_node);
        if (!can || want == 0) {
            n->m.zero_claims++;
            pthread_mutex_unlock(&n->mu);
            /* backoff briefly: wait for capacity if outstanding present or no headroom */
            uint64_t t0w = di_now_ns();
            struct timespec ts; ts.tv_sec=0; ts.tv_nsec=200000; /* 0.2ms */
            nanosleep(&ts,NULL);
            n->m.claim_wait_ns += di_now_ns() - t0w;
            /* termination: nothing left globally and cannot admit */
            uint64_t go = __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE);
            if (go >= eng->file_size) {
                /* if we have outstanding somehow, keep going; else done */
                pthread_mutex_lock(&n->mu);
                int outst = (n->outstanding > 0);
                pthread_mutex_unlock(&n->mu);
                if (!outst) break;
            }
            continue;
        }
        /* admit: account outstanding BEFORE reserving range visibility issues? do atomically w.r.t. policy */
        n->outstanding += want;
        eff = di_effective_backlog(n->published_backlog, n->outstanding);
        if (eff > n->max_effective_backlog) n->max_effective_backlog = eff;
        di_publish_headroom(n);
        pthread_mutex_unlock(&n->mu);

        /* FAA reserve */
        uint64_t start = __atomic_fetch_add(&eng->next_offset, want, __ATOMIC_ACQ_REL);
        if (start >= eng->file_size) {
            /* undo outstanding */
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }
        uint64_t req_len = want;
        uint64_t avail = eng->file_size - start;
        uint64_t to_read = req_len < avail ? req_len : avail;

        /* allocate local destination */
        int used_huge = 0;
        void *buf = di_alloc_local(to_read, eng->P.prefer_hugepage, n->phys_node, &used_huge);
        if (!buf) {
            n->m.last_error = DI_ERR_NOMEM;
            __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE);
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }
        n->m.alloc_bytes += to_read;
        if (used_huge) n->m.hugepage_kb += (to_read + 1023) / 1024;

        /* read */
        uint64_t t0r = di_now_ns();
        ssize_t rr = pread(eng->fd, buf, (size_t)to_read, (off_t)start);
        n->m.read_wait_ns += di_now_ns() - t0r;
        if (rr < 0) {
            if (errno == EINTR) { /* retry once simple */ rr = pread(eng->fd, buf, (size_t)to_read, (off_t)start); }
        }
        if (rr < 0) {
            n->m.last_error = DI_ERR_IO;
            di_free_local(buf, to_read);
            __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE);
            pthread_mutex_lock(&n->mu);
            if (n->outstanding >= want) n->outstanding -= want; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
            break;
        }
        uint64_t act = (uint64_t)rr;

        /* adjust outstanding if short (EOF/short read): reserved want, actually act */
        if (act < want) {
            pthread_mutex_lock(&n->mu);
            uint64_t delta = want - act;
            if (n->outstanding >= delta) n->outstanding -= delta; else n->outstanding = 0;
            di_publish_headroom(n);
            pthread_mutex_unlock(&n->mu);
        }

        n->m.reservations++;
        n->m.bytes_reserved += req_len;
        n->m.bytes_read += act;
        di_hist_add(n->m.res_hist, req_len);
        di_record_res(n, start, req_len, act);
        di_sample_placement(n, buf, act);

        if (act == 0) {
            di_free_local(buf, to_read);
            /* nothing to publish; outstanding already adjusted */
            break;
        }

        di_chunk_t c;
        c.off = start; c.len = act; c.buf = buf; c.buf_cap = to_read;
        if (di_queue_push(n, c) != 0) {
            di_free_local(buf, to_read);
            break;
        }

        /* if we hit EOF (partial), loop will observe next_offset/file_size and exit */
        if (start + act >= eng->file_size) {
            /* ensure others see EOF; some reservations may have gone past but will undo */
        }
    }

    n->m.ingest_cpu_ns = di_thread_cpu_ns() - c0;
    __atomic_fetch_add(&eng->ingestors_done, 1, __ATOMIC_ACQ_REL);
    /* wake consumers in case they are waiting */
    pthread_mutex_lock(&n->mu);
    pthread_cond_broadcast(&n->cv_can_pop);
    pthread_cond_broadcast(&n->cv_can_push);
    pthread_mutex_unlock(&n->mu);
    /* also wake other nodes' consumers not needed; their own ingestors will finish */
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

    __atomic_store_n(&eng->next_offset, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&eng->stop, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&eng->ingestors_done, 0, __ATOMIC_RELAXED);

    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        n->id = i;
        n->eng = eng;
        n->phys_node = (cfg->phys_nodes ? cfg->phys_nodes[i] : -1);
        n->cpus = (cfg->cpu_lists ? cfg->cpu_lists[i] : NULL);
        n->ncpus = (cfg->cpu_counts ? cfg->cpu_counts[i] : 0);
        n->q_cap = 1024;
        n->q = (di_chunk_t *)calloc(n->q_cap, sizeof(di_chunk_t));
        pthread_mutex_init(&n->mu, NULL);
        pthread_cond_init(&n->cv_can_push, NULL);
        pthread_cond_init(&n->cv_can_pop, NULL);
        __atomic_store_n(&n->peer_headroom, eng->P.max_backlog, __ATOMIC_RELAXED);
        if (cfg->consumers) n->cons_cfg = cfg->consumers[i];
        else { n->cons_cfg.mode = DI_CONSUMER_FAST; n->cons_cfg.bytes_per_sec = 0; n->cons_cfg.stall_ms = 0; }
        if (!n->q) { /* cleanup partial */ }
    }
    return eng;
}

void di_destroy(di_engine_t *eng) {
    if (!eng) return;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        /* free any leftover queued chunks */
        for (unsigned k = 0; k < n->q_count; k++) {
            unsigned idx = (n->q_head + k) % n->q_cap;
            if (n->q[idx].buf) di_free_local(n->q[idx].buf, n->q[idx].buf_cap);
        }
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

    /* control policy is handled externally */
    if (eng->cfg.policy == DI_POLICY_CENTRALIZED_CONTROL) {
        return DI_ERR_INVAL;
    }

    clock_gettime(CLOCK_MONOTONIC, &eng->t_start);
    eng->started = 1;

    int rc = 0;
    /* start consumers then ingestors */
    for (int i = 0; i < eng->num_nodes; i++) {
        if (pthread_create(&eng->nodes[i].cons_tid, NULL, di_consumer_thread, &eng->nodes[i]) == 0)
            eng->nodes[i].has_cons = 1;
        else { rc = DI_ERR_THREAD; __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE); }
    }
    for (int i = 0; i < eng->num_nodes; i++) {
        if (rc == 0 && pthread_create(&eng->nodes[i].ing_tid, NULL, di_ingestor_thread, &eng->nodes[i]) == 0)
            eng->nodes[i].has_ing = 1;
        else if (rc == 0) { rc = DI_ERR_THREAD; __atomic_store_n(&eng->stop, 1, __ATOMIC_RELEASE); }
    }

    for (int i = 0; i < eng->num_nodes; i++) {
        if (eng->nodes[i].has_ing) pthread_join(eng->nodes[i].ing_tid, NULL);
    }
    /* ensure all ingestors marked done and wake consumers */
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

    /* aggregate metrics and correctness */
    size_t total_recs = 0;
    for (int i = 0; i < eng->num_nodes; i++) total_recs += eng->nodes[i].recs_n;
    di_resrec_t *all = NULL;
    if (total_recs > 0) all = (di_resrec_t *)malloc(total_recs * sizeof(*all));
    size_t pos = 0;
    for (int i = 0; i < eng->num_nodes; i++) {
        di_node_t *n = &eng->nodes[i];
        result->nodes[i] = n->m;
        result->nodes[i].current_published_backlog = n->published_backlog;
        result->nodes[i].current_outstanding = n->outstanding;
        result->nodes[i].current_effective_backlog = di_effective_backlog(n->published_backlog, n->outstanding);
        result->nodes[i].max_published_backlog = n->max_published_backlog;
        result->nodes[i].max_effective_backlog = n->max_effective_backlog;
        result->total_reserved += n->m.bytes_reserved;
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

    /* correctness: no overlap, no loss/dup over [0,file_size) based on actual read ranges */
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
                if (s > cur) result->lost_detected = 1; /* gap */
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

    if (__atomic_load_n(&eng->stop, __ATOMIC_RELAXED) && rc == 0) rc = DI_ERR_STATE;
    return rc;
}

uint64_t di_global_offset(const di_engine_t *eng) { return eng ? __atomic_load_n(&eng->next_offset, __ATOMIC_ACQUIRE) : 0; }
uint64_t di_file_size(const di_engine_t *eng) { return eng ? eng->file_size : 0; }
int di_num_nodes(const di_engine_t *eng) { return eng ? eng->num_nodes : 0; }
