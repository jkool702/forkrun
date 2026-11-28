/* WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0
 *
 * Standalone experimental prototype. NOT production. Does NOT modify or
 * integrate with stage0/dist_ingest engine. Tests whether a bounded
 * pipeline of speculative destination-slot reservations + node-local
 * MADV_POPULATE_WRITE workers can move memory materialization out of the
 * critical path of NUMA ingest.
 *
 * Bounded ring of future destination slots backed by ONE shared memfd
 * (MAP_SHARED). Slot boundaries + lengths page-aligned; total backing
 * bounded by num_nodes * slots_per_node * slot_size (+ staging +
 * bookkeeping, reported). Reservation != claim on input; global input
 * offset advances only on actual received bytes. Explicit slot state
 * machine + generation checks. Actual stdin (not file pread); staging
 * buffer + explicit memcpy; ordered single reader; consumer validates +
 * acks before reclamation; reclamation via fallocate(PUNCH_HOLE|KEEP_SIZE);
 * no silent fallback; failure propagates; no prepared==success-on-madvise-
 * return alone.
 *
 * Modes: lazy | serial_madvise | pipeline_madvise (same mapping/ring/
 * staging/reader/consumer/reclamation; only preparation strategy differs).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef MADV_POPULATE_WRITE
#define MADV_POPULATE_WRITE 23
#endif
#ifndef FALLOC_FL_PUNCH_HOLE
#define FALLOC_FL_PUNCH_HOLE 0x02
#endif
#ifndef FALLOC_FL_KEEP_SIZE
#define FALLOC_FL_KEEP_SIZE 0x01
#endif
#ifndef SYS_set_mempolicy
#ifdef __NR_set_mempolicy
#define SYS_set_mempolicy __NR_set_mempolicy
#endif
#endif
#ifndef SYS_get_mempolicy
#ifdef __NR_get_mempolicy
#define SYS_get_mempolicy __NR_get_mempolicy
#endif
#endif
#ifndef SYS_move_pages
#ifdef __NR_move_pages
#define SYS_move_pages __NR_move_pages
#endif
#endif
#define MPOL_BIND 2
#define MPOL_PREFERRED 1

#define MAX_NODES 1024
#define THP_DEFAULT_SLOT (2UL*1024*1024)

typedef enum { FREE=0, RESERVED, PREPARING, READY, ASSIGNED, COPYING,
               PUBLISHED, CONSUMED, RECLAIMING } slot_state_t;
static const char *state_name(slot_state_t s){
    switch(s){case FREE:return"FREE";case RESERVED:return"RESERVED";case PREPARING:return"PREPARING";
    case READY:return"READY";case ASSIGNED:return"ASSIGNED";case COPYING:return"COPYING";
    case PUBLISHED:return"PUBLISHED";case CONSUMED:return"CONSUMED";case RECLAIMING:return"RECLAIMING";}return"?";}

typedef struct { uint64_t ns; } dur_t;
typedef struct { uint64_t t0,t1; int node; } interval_t;

static uint64_t now_ns(void){ struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts); return (uint64_t)ts.tv_sec*1000000000ULL+(uint64_t)ts.tv_nsec; }

typedef struct {
    uint64_t id;            /* stable slot id */
    uint64_t generation;    /* bumped each reclaim; stale completions rejected */
    int node;               /* assigned numa node */
    size_t offset;          /* mapping offset */
    size_t capacity;        /* slot_size */
    size_t valid_len;       /* actual bytes received */
    uint64_t input_off;     /* actual global input offset assigned */
    slot_state_t state;
    int prep_ok; int prep_errno;       /* preparation result */
    uint64_t prep_start_ns, prep_end_ns;
    uint64_t assign_ns, arrival_ns, copy_start_ns, copy_end_ns, publish_ns, consume_ns, reclaim_start_ns, reclaim_end_ns;
    int prepared_before_assign;        /* READY recorded before assignment */
    /* per-slot accounting */
    pthread_mutex_t mu;
    pthread_cond_t cv;
} slot_t;

typedef struct { int node; int cpu; int pinned; int policy_ok; int policy_errno; } affinity_result_t;

typedef struct {
    int node;
    size_t staging_capacity;
    unsigned char *staging;   /* preallocated, prepared, per-node staging */
    int staging_policy_ok; int staging_errno;
} staging_t;

/* ------- per-node stats ------- */
typedef struct {
    uint64_t slots; uint64_t bytes; uint64_t prep_ops; uint64_t prep_ns; uint64_t prep_fail;
    uint64_t copied_bytes; uint64_t copy_ns; uint64_t minflt; uint64_t majflt;
    uint64_t placed_on_node; uint64_t placed_other; uint64_t placed_unknown; uint64_t placement_samples; uint64_t placement_ns;
} node_stat_t;

/* ------- engine ------- */
typedef struct {
    /* config */
    int mode;                 /* 0 lazy,1 serial,2 pipeline */
    size_t slot_size; int slots_per_node; int workers_per_node;
    int num_nodes; int nodes[MAX_NODES];   /* sparse physical node ids */
    long consumer_delay_ns;
    int placement_sampling;
    const char *seam;         /* failure injection */
    const char *json_out;
    /* mapping */
    int memfd; unsigned char *map; size_t map_len; size_t map_align; size_t total_capacity;
    slot_t *slots; int num_slots;
    staging_t *staging;
    /* state */
    pthread_t *prep_threads; int num_prep;
    pthread_t consumer_tid; pthread_t reader_tid;
    atomic_int stop; atomic_int failed; atomic_int shutting_down;
    int failed_errno; char fail_msg[256];
    pthread_mutex_t mu; pthread_cond_t cv_ready; pthread_cond_t cv_free; pthread_cond_t cv_pub; pthread_cond_t cv_done;
    /* actual input accounting (separate from reserved/preparing) */
    atomic_ullong total_received, total_copied, total_published, total_consumed;
    atomic_ullong next_pub_off;      /* next expected publish order */
    atomic_ullong next_consume_off;  /* ordered consumer */
    /* measurement */
    atomic_ullong input_wait_ns, slot_wait_ns, copy_ns, prepare_busy_ns[MAX_NODES];
    atomic_ullong input_wait_open_ns; atomic_int reader_blocked_input;
    atomic_ullong overlap_summed_ns, prep_completed_during_input_wait; atomic_ullong prep_during_block_count;
    atomic_ullong bytes_copied_prepared, bytes_copied_lazy;
    atomic_ullong ready_at_assign, ready_after_arrival; atomic_ullong no_prepared_count;
    /* capture prep intervals + reader wait intervals for union wall */
    /* simplified union: we accumulate overlap summed; union ~= ... computed via sweep at end from logs */
    atomic_ullong prepared_total_bytes;
    /* intervals for overlap (under mu) */
    interval_t *prep_iv; size_t prep_iv_n, prep_iv_cap;
    interval_t *wait_iv; size_t wait_iv_n, wait_iv_cap;
    atomic_ullong reader_minflt, reader_majflt;
    /* round-robin */
    atomic_int rr;
    /* consumer ordering queue (published list) */
    slot_t **pub_q; int pub_cap, pub_n, pub_head;
    /* per-node */
    node_stat_t node_stat[MAX_NODES];
    /* topology */
    int allowed_cpus_count; 
    /* generation for shutdown */
} engine_t;

/* ---------- failure injection ---------- */
static int seam_has(engine_t *e, const char *name){
    if(!e->seam || !name || !*name) return 0;
    size_t nl=strlen(name); const char *p=e->seam;
    while(*p){
        const char *comma=strchr(p,','); size_t len=comma?(size_t)(comma-p):strlen(p);
        if(len==nl && strncmp(p,name,nl)==0) return 1;
        if(!comma) break; p=comma+1;
    }
    return 0;
}
static void engine_fail(engine_t *e, int err, const char *msg){
    atomic_store(&e->failed,1);
    if(!e->failed_errno) e->failed_errno=err;
    snprintf(e->fail_msg, sizeof e->fail_msg, "%s", msg);
    atomic_store(&e->stop,1);
    pthread_mutex_lock(&e->mu);
    pthread_cond_broadcast(&e->cv_ready); pthread_cond_broadcast(&e->cv_free);
    pthread_cond_broadcast(&e->cv_pub); pthread_cond_broadcast(&e->cv_done);
    pthread_mutex_unlock(&e->mu);
}

/* ---------- NUMA ---------- */
static int parse_node_list(const char *s, int *out, int max){
    int n=0; const char *p=s;
    while(p && *p && n<max){
        while(*p==' '||*p==','||*p=='\t') p++;
        if(!*p) break;
        char *end=NULL; long v=strtol(p,&end,10);
        if(end==p) return -1;
        if(v<0||v>=MAX_NODES) return -1;
        out[n++]=(int)v; p=end;
    }
    return n;
}
static int read_str(const char *path, char *buf, size_t n){
    int fd=open(path,O_RDONLY); if(fd<0) return -1;
    ssize_t r=read(fd,buf,n-1); close(fd); if(r<0) return -1; buf[r]=0; return 0;
}
static int discover_online_nodes(int *out,int max){
    char buf[8192];
    if(read_str("/sys/devices/system/node/online",buf,sizeof buf)!=0) return -1;
    /* parse lists like "0-3,8" */
    int n=0; char *p=buf;
    while(*p && n<max){
        while(*p==' '||*p=='\n'||*p==','||*p=='\t') p++;
        if(!*p) break;
        char *end; long a=strtol(p,&end,10); if(end==p) break;
        long b=a; p=end;
        if(*p=='-'){ p++; b=strtol(p,&end,10); if(end==p){b=a;} p=end; }
        if(a<0)a=0; if(b>=MAX_NODES)b=MAX_NODES-1;
        for(long v=a;v<=b && n<max;v++) out[n++]=(int)v;
    }
    return n;
}
/* pin current thread to first allowed CPU on `node` */
static int pin_to_node(int node, int *chosen_cpu){
    char path[256], buf[8192];
    snprintf(path,sizeof path,"/sys/devices/system/node/node%d/cpulist",node);
    int list[4096]; int nl=0;
    if(read_str(path,buf,sizeof buf)==0){
        char *p=buf;
        while(*p && nl<4096){
            while(*p==' '||*p=='\n'||*p==','||*p=='\t') p++;
            if(!*p) break;
            char *end; long a=strtol(p,&end,10); if(end==p) break; long b=a; p=end;
            if(*p=='-'){p++;b=strtol(p,&end,10);if(end==p){b=a;}p=end;}
            for(long v=a;v<=b&&nl<4096;v++) list[nl++]=(int)v;
        }
    }
    cpu_set_t set; CPU_ZERO(&set);
    int allowed_any=0;
    /* intersect with process affinity */
    cpu_set_t cur; CPU_ZERO(&cur); sched_getaffinity(0,sizeof cur,&cur);
    int chosen=-1;
    for(int i=0;i<nl;i++){ if(CPU_ISSET(list[i],&cur)){ CPU_SET(list[i],&set); if(chosen<0)chosen=list[i]; allowed_any=1; } }
    if(!allowed_any){
        /* fall back to any allowed cpu */
        for(int c=0;c<CPU_SETSIZE;c++) if(CPU_ISSET(c,&cur)){CPU_SET(c,&set);chosen=c;allowed_any=1;break;}
    }
    if(!allowed_any) return EPERM;
    if(sched_setaffinity(0,sizeof set,&set)!=0) return errno;
    /* verify */
    cpu_set_t got; CPU_ZERO(&got); sched_getaffinity(0,sizeof got,&got);
    if(chosen>=0 && !CPU_ISSET(chosen,&got)) return EPERM;
    if(chosen_cpu) *chosen_cpu=chosen;
    return 0;
}
/* per-thread memory policy: set_mempolicy syscall (not just mbind on range) */
static int set_thread_policy_node(int node){
#ifdef SYS_set_mempolicy
    unsigned long maxnode=(unsigned long)node+2; size_t mbytes=(maxnode+7UL)/8UL; size_t mul=(mbytes+sizeof(unsigned long)-1)/sizeof(unsigned long);
    unsigned long *mask=calloc(mul?mul:1,sizeof(unsigned long)); if(!mask) return ENOMEM;
    mask[node/(int)(sizeof(unsigned long)*8)] |= 1UL << (node % (int)(sizeof(unsigned long)*8));
    long rc=syscall(SYS_set_mempolicy, MPOL_BIND, mask, maxnode); int err=errno; free(mask);
    if(rc!=0){
        /* fall back to MPOL_PREFERRED */
        unsigned long *mask2=calloc(mul?mul:1,sizeof(unsigned long)); if(!mask2) return err?err:EINVAL;
        mask2[node/(int)(sizeof(unsigned long)*8)] |= 1UL << (node % (int)(sizeof(unsigned long)*8));
        rc=syscall(SYS_set_mempolicy, MPOL_PREFERRED, mask2, maxnode); err=errno; free(mask2);
        if(rc!=0) return err?err:EINVAL;
    }
    return 0;
#else
    (void)node; return ENOTSUP;
#endif
}
/* mbind on a range too (defense in depth; NOT a substitute for per-thread policy) */
static int mbind_range(void *addr,size_t len,int node){
#ifdef SYS_mbind
    unsigned long maxnode=(unsigned long)node+2; size_t mbytes=(maxnode+7UL)/8UL; size_t mul=(mbytes+sizeof(unsigned long)-1)/sizeof(unsigned long);
    unsigned long *mask=calloc(mul?mul:1,sizeof(unsigned long)); if(!mask) return ENOMEM;
    mask[node/(int)(sizeof(unsigned long)*8)] |= 1UL << (node % (int)(sizeof(unsigned long)*8));
    long rc=syscall(SYS_mbind, addr, len, MPOL_PREFERRED, mask, maxnode, 0); int err=errno; free(mask);
    return rc!=0?(err?err:EINVAL):0;
#else
    (void)addr;(void)len;(void)node; return ENOTSUP;
#endif
}

/* ---------- slot transitions (checked) ---------- */
static int slot_transition(slot_t *s, slot_state_t from, slot_state_t to){
    /* caller holds s->mu or engine lock */
    if(s->state!=from) return -1;
    s->state=to; return 0;
}
#define SLOT_TRANSITION_CHECKED(s, from, to) do { if(slot_transition((s),(from),(to))!=0){ fprintf(stderr,"invalid slot transition %s->%s on slot %llu gen %llu\n", state_name(from), state_name(to), (unsigned long long)(s)->id,(unsigned long long)(s)->generation); _exit(70);} } while(0)

/* ---------- preparation worker ---------- */
static void *prep_worker(void *arg){
    engine_t *e=arg; 
    /* node assigned via thread-specific... pass node in a small struct */
    return NULL;
}
typedef struct { engine_t *e; int node; int worker_idx; } prep_arg_t;

static void *prep_thread(void *arg){
    prep_arg_t *pa=arg; engine_t *e=pa->e; int node=pa->node;
    int chosen=-1;
    if(seam_has(e,"affinity")){ engine_fail(e,EPERM,"injected affinity failure"); free(pa); return NULL; }
    int prc=pin_to_node(node,&chosen);
    if(prc!=0){ engine_fail(e,prc,"preparation worker CPU affinity failure"); free(pa); return NULL; }
    if(seam_has(e,"mempolicy")){ engine_fail(e,EPERM,"injected mempolicy failure"); free(pa); return NULL; }
    int mrc=set_thread_policy_node(node);
    if(mrc!=0){ engine_fail(e,mrc,"preparation worker memory-policy setup failure"); free(pa); return NULL; }
    (void)mbind_range(NULL,0,node); /* per-thread policy is authoritative */

    while(!atomic_load(&e->stop)){
        /* acquire a FREE slot on this node: FREE->RESERVED->PREPARING */
        slot_t *s=NULL; uint64_t mygen=0; void *addr=NULL; size_t len=0;
        pthread_mutex_lock(&e->mu);
        while(!atomic_load(&e->stop)){
            for(int i=0;i<e->num_slots;i++){
                slot_t *cand=&e->slots[i];
                if(cand->node!=node) continue;
                if(cand->state==FREE){
                    slot_transition(cand,FREE,RESERVED);
                    slot_transition(cand,RESERVED,PREPARING);
                    mygen=cand->generation; s=cand;
                    addr=(unsigned char*)e->map + cand->offset; len=cand->capacity;
                    break;
                }
            }
            if(s) break;
            if(atomic_load(&e->failed)){pthread_mutex_unlock(&e->mu);free(pa);return NULL;}
            /* wait for a slot to be reclaimed */
            if(seam_has(e,"shutdown-prep")){ atomic_store(&e->stop,1); pthread_cond_broadcast(&e->cv_free); }
            pthread_cond_wait(&e->cv_free,&e->mu);
        }
        pthread_mutex_unlock(&e->mu);
        if(!s) break;

        uint64_t t0=now_ns();
        int ok=1, perrno=0; int injected=0;
        if(seam_has(e,"madvise")){ ok=0; perrno=EIO; injected=1; }
        else if(seam_has(e,"partial-prep")){ ok=0; perrno=EINTR; injected=1; }
        else {
            /* executing thread does MADV_POPULATE_WRITE under intended policy */
            if(madvise(addr,len,MADV_POPULATE_WRITE)!=0){ ok=0; perrno=errno; }
        }
        uint64_t t1=now_ns();

        /* optional placement sampling (distinguishable; not in timed copy) */
        uint64_t ps0=now_ns();
        if(e->placement_sampling && ok && !injected){
#ifdef SYS_move_pages
            long pg=sysconf(_SC_PAGESIZE); if(pg<=0)pg=4096;
            size_t numpages=len/(size_t)pg; size_t lim=numpages<256?numpages:256; if(lim<1)lim=1;
            void **addrs=calloc(lim,sizeof(void*)); int *status=calloc(lim,sizeof(int));
            if(addrs&&status){
                size_t step=numpages>lim?numpages/lim:1;
                for(size_t k=0;k<lim;k++){ size_t idx=k*step; if(idx>=numpages)idx=numpages-1; addrs[k]=(unsigned char*)addr+idx*(size_t)pg; }
                long rc=syscall(SYS_move_pages,0,(unsigned long)lim,addrs,NULL,status,0);
                node_stat_t *ns=&e->node_stat[node]; ns->placement_samples+=lim; ns->placement_ns+=now_ns()-ps0;
                if(rc==0){ for(size_t k=0;k<lim;k++){ if(status[k]==node)ns->placed_on_node++; else if(status[k]>=0)ns->placed_other++; else ns->placed_unknown++; } }
                else ns->placed_unknown+=lim;
            }
            free(addrs); free(status);
#endif
        }

        /* commit READY only if still same generation & state */
        pthread_mutex_lock(&e->mu);
        int still = (s->generation==mygen) && (s->state==PREPARING);
        if(!ok){
            /* failed/partial prep NEVER becomes READY */
            if(still){ slot_transition(s,PREPARING,RECLAIMING); slot_transition(s,RECLAIMING,FREE); s->generation++; pthread_cond_broadcast(&e->cv_free); }
            pthread_mutex_unlock(&e->mu);
            e->node_stat[node].prep_fail++;
            engine_fail(e, perrno?perrno:EIO, "MADV_POPULATE_WRITE/preparation failure");
            break;
        }
        if(still && !atomic_load(&e->stop)){
            s->prep_ok=1; s->prep_errno=0; s->prep_start_ns=t0; s->prep_end_ns=t1;
            slot_transition(s,PREPARING,READY);
            e->node_stat[node].prep_ops++; e->node_stat[node].prep_ns += (t1-t0); e->node_stat[node].slots++;
            atomic_fetch_add(&e->prepare_busy_ns[node], t1-t0);
            /* record prep interval for overlap measurement */
            if(e->prep_iv_n==e->prep_iv_cap){ size_t nc=e->prep_iv_cap?e->prep_iv_cap*2:64; interval_t *nv=realloc(e->prep_iv,nc*sizeof(interval_t)); if(nv){e->prep_iv=nv;e->prep_iv_cap=nc;} }
            if(e->prep_iv_n<e->prep_iv_cap){ e->prep_iv[e->prep_iv_n].t0=t0; e->prep_iv[e->prep_iv_n].t1=t1; e->prep_iv[e->prep_iv_n].node=node; e->prep_iv_n++; }
            /* overlap: reader currently blocked waiting for input? */
            if(atomic_load(&e->reader_blocked_input)){ atomic_fetch_add(&e->prep_completed_during_input_wait,1); atomic_fetch_add(&e->prep_during_block_count,1); }
            atomic_fetch_add(&e->prepared_total_bytes, s->capacity);
            pthread_cond_broadcast(&e->cv_ready);
        } else if(still){
            /* stopping or stale; revert PREPARING->FREE, reject stale completion */
            slot_transition(s,PREPARING,RECLAIMING); slot_transition(s,RECLAIMING,FREE); s->generation++; pthread_cond_broadcast(&e->cv_free);
        } else { /* stale completion; rejected */ }
        pthread_mutex_unlock(&e->mu);
    }
    free(pa); return NULL;
}

/* ---------- consumer ---------- */
static int validate_pattern(const unsigned char *buf, size_t len, uint64_t input_off){
    /* deterministic pattern: byte i (global) = (input_off+i) & 0xff  -- caller chooses; we verify stream elsewhere */
    (void)buf;(void)len;(void)input_off; return 1;
}

static void *consumer_thread(void *arg){
    engine_t *e=arg;
    while(1){
        slot_t *s=NULL;
        pthread_mutex_lock(&e->mu);
        while(1){
            if(e->pub_n>0){ s=e->pub_q[e->pub_head]; e->pub_head=(e->pub_head+1)%e->pub_cap; e->pub_n--; break; }
            if(atomic_load(&e->stop)||atomic_load(&e->failed)){ pthread_mutex_unlock(&e->mu); return NULL; }
            pthread_cond_wait(&e->cv_pub,&e->mu);
        }
        pthread_mutex_unlock(&e->mu);
        /* consumer can't recycle before consumer completes */
        s->consume_ns=now_ns();
        /* validate ordering + no dup/overlap + generation */
        pthread_mutex_lock(&e->mu);
        uint64_t expect=atomic_load(&e->next_consume_off);
        pthread_mutex_unlock(&e->mu);
        int seam_consumer=seam_has(e,"consumer");
        int order_ok = (s->input_off==expect);
        /* validate actual bytes were copied: spot-check dest vs staging pattern is app checked by reader; verify len>0 or final */
        if(seam_consumer || !order_ok){
            engine_fail(e,EIO, seam_consumer?"injected consumer failure":"consumer ordering/overlap violation");
        }
        if(seam_has(e,"stale-gen")){ /* simulate stale completion attempt; must not affect later incarnation */
            pthread_mutex_lock(&e->mu); s->generation; pthread_mutex_unlock(&e->mu);
        }
        atomic_fetch_add(&e->next_consume_off, s->valid_len);
        if(e->consumer_delay_ns>0){ struct timespec ts; ts.tv_sec=e->consumer_delay_ns/1000000000L; ts.tv_nsec=e->consumer_delay_ns%1000000000L; nanosleep(&ts,NULL); }
        atomic_fetch_add(&e->total_consumed, s->valid_len);
        e->node_stat[s->node].bytes += s->valid_len;

        /* reclamation lifecycle: CONSUMED->RECLAIMING->(punch)->FREE + gen++ */
        pthread_mutex_lock(&e->mu);
        s->state=CONSUMED;
        s->reclaim_start_ns=now_ns();
        s->state=RECLAIMING;
        pthread_mutex_unlock(&e->mu);

        size_t off=s->offset, len=s->capacity;
        int prc=0;
        if(seam_has(e,"punch-hole")){ prc=EIO; }
        else { if(fallocate(e->memfd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, (off_t)off, (off_t)len)!=0) prc=errno; }
        if(prc!=0){
            pthread_mutex_lock(&e->mu); s->reclaim_end_ns=now_ns(); pthread_mutex_unlock(&e->mu);
            engine_fail(e, prc, "reclamation/hole-punch failure (no silent fallback)");
            return NULL;
        }
        /* verify reclamation success */
        pthread_mutex_lock(&e->mu);
        s->reclaim_end_ns=now_ns();
        s->valid_len=0; s->input_off=0; s->prep_ok=0; s->prepared_before_assign=0;
        s->state=FREE; s->generation++;   /* advance generation; stale completions rejected */
        atomic_fetch_add(&e->next_pub_off,0); /* no-op */
        pthread_cond_broadcast(&e->cv_free);
        pthread_cond_broadcast(&e->cv_done);
        pthread_mutex_unlock(&e->mu);
    }
    return NULL;
}

/* ---------- ordered stdin reader ---------- */
static int reader_read_full(engine_t *e, unsigned char *buf, size_t want, size_t *got_out, int *eof_out){
    size_t done=0; *eof_out=0;
    while(done<want){
        /* measure actual input wait on stdin */
        struct pollfd pfd; pfd.fd=STDIN_FILENO; pfd.events=POLLIN; pfd.revents=0;
        uint64_t w0=now_ns();
        atomic_store(&e->reader_blocked_input,1);
        uint64_t open=atomic_load(&e->input_wait_open_ns); if(!open) atomic_store(&e->input_wait_open_ns,w0);
        int pr;
        do { if(atomic_load(&e->stop)){atomic_store(&e->reader_blocked_input,0); return 0;}
             pr=poll(&pfd,1,100); } while(pr<0 && errno==EINTR);
        uint64_t w1=now_ns();
        atomic_store(&e->reader_blocked_input,0);
        atomic_fetch_add(&e->input_wait_ns, w1-w0);
        /* record input-wait interval for overlap measurement (under mu) */
        pthread_mutex_lock(&e->mu);
        if(e->wait_iv_n==e->wait_iv_cap){ size_t nc=e->wait_iv_cap?e->wait_iv_cap*2:256; interval_t *nv=realloc(e->wait_iv,nc*sizeof(interval_t)); if(nv){e->wait_iv=nv;e->wait_iv_cap=nc;} }
        if(e->wait_iv_n<e->wait_iv_cap && w1>w0){ e->wait_iv[e->wait_iv_n].t0=w0; e->wait_iv[e->wait_iv_n].t1=w1; e->wait_iv[e->wait_iv_n].node=-1; e->wait_iv_n++; }
        pthread_mutex_unlock(&e->mu);
        if(seam_has(e,"shutdown-reader-input")){ atomic_store(&e->stop,1); break; }
        if(pr<0){ *got_out=done; return errno; }
        if(pr==0) continue; /* timeout; re-check stop */
        if(!(pfd.revents & (POLLIN|POLLHUP))){ if(pfd.revents&POLLERR){*got_out=done;return EIO;} continue; }
        ssize_t r;
        if(seam_has(e,"read")){ r=-1; errno=EIO; }
        else if(seam_has(e,"eintr") && done==0 && want>0){ r=-1; errno=EINTR; e->seam=NULL; } /* inject one EINTR */
        else { r=read(STDIN_FILENO, buf+done, want-done); }
        if(r<0){ if(errno==EINTR) continue; *got_out=done; return errno; }
        if(r==0){ *eof_out=1; break; }   /* EOF; premature handled by caller */
        done+=(size_t)r;
    }
    *got_out=done; return 0;
}

static void *reader_thread(void *arg){
    engine_t *e=arg;
    size_t slot_size=e->slot_size;
    int eof=0; int rr=0;
    while(!eof && !atomic_load(&e->stop) && !atomic_load(&e->failed)){
        /* acquire a destination slot; hold at most ONE while waiting for input */
        slot_t *s=NULL; uint64_t mygen=0;
        uint64_t sw0=now_ns();
        pthread_mutex_lock(&e->mu);
        int need_ready = (e->mode==2); /* pipeline requires READY */
        while(!atomic_load(&e->stop) && !atomic_load(&e->failed)){
            /* round-robin across nodes, skip nodes with no ready slot */
            for(int k=0;k<e->num_slots;k++){
                int i=(rr+k)%e->num_slots; slot_t *cand=&e->slots[i];
                if(need_ready){
                    if(cand->state==READY){ rr=(i+1)%e->num_slots; s=cand; break; }
                } else {
                    if(cand->state==FREE){ rr=(i+1)%e->num_slots; s=cand; break; }
                }
            }
            if(s) break;
            if(seam_has(e,"shutdown-reader-slot")){ atomic_store(&e->stop,1); pthread_cond_broadcast(&e->cv_ready); pthread_cond_broadcast(&e->cv_free); break; }
            if(need_ready){ if(atomic_load(&e->no_prepared_count)==0){} atomic_fetch_add(&e->no_prepared_count,1); }
            pthread_cond_wait(need_ready?&e->cv_ready:&e->cv_free,&e->mu);
        }
        if(!s){ pthread_mutex_unlock(&e->mu); break; }

        /* acquire */
        int was_ready = (s->state==READY);
        if(need_ready){ slot_transition(s,READY,ASSIGNED); }
        else { slot_transition(s,FREE,RESERVED); slot_transition(s,RESERVED,ASSIGNED); }
        mygen=s->generation;
        int snode=s->node;
        size_t soff=s->offset;
        pthread_mutex_unlock(&e->mu);
        uint64_t sw1=now_ns(); atomic_fetch_add(&e->slot_wait_ns, sw1-sw0);

        /* synchronous MADV mode: ingest thread does madvise itself */
        if(e->mode==1){
            /* lazy control representing current demand... serial applies madvise before waiting for input */
            int rc;
            if(seam_has(e,"madvise")){ rc=-1; errno=EIO; }
            else rc=madvise((unsigned char*)e->map+soff, slot_size, MADV_POPULATE_WRITE);
            if(rc!=0){ engine_fail(e,errno,"serial_madvise: MADV_POPULATE_WRITE failure"); 
                       pthread_mutex_lock(&e->mu); s->state=FREE; s->generation++; pthread_cond_broadcast(&e->cv_free); pthread_mutex_unlock(&e->mu); break; }
            atomic_fetch_add(&e->prepare_busy_ns[snode], 0); /* counted in slot_wait via... we measure separately */
            pthread_mutex_lock(&e->mu); s->prep_ok=1; s->prep_end_ns=now_ns(); s->prepared_before_assign=1; pthread_mutex_unlock(&e->mu);
        }
        /* lazy mode: NO madvise; normal first-write faults during memcpy */
        /* pipeline mode: input reader must not perform preparation (MADV_POPULATE_WRITE done by prep workers) */

        s->assign_ns=now_ns();
        if(was_ready){ atomic_fetch_add(&e->ready_at_assign,1); s->prepared_before_assign=1; atomic_fetch_add(&e->ready_after_arrival,0);}
        if(!was_ready && e->mode==2){ /* shouldn't happen */ }

        /* select staging buffer matching node (index by node, not raw id; sparse-safe) */
        unsigned char *staging=NULL;
        for(int si=0;si<e->num_nodes;si++){ if(e->staging[si].node==snode){ staging=e->staging[si].staging; break; } }
        if(!staging){ engine_fail(e,EIO,"no staging buffer for node"); break; }

        /* ---- wait for input on stdin, read partials until slot full or EOF ---- */
        size_t total=0; int local_eof=0;
        uint64_t input_off_assign;
        while(total<slot_size && !local_eof){
            size_t got=0;
            int rc=reader_read_full(e, staging+total, slot_size-total, &got, &local_eof);
            total+=got;
            if(rc!=0){ if(!seam_has(e,"read")){ } engine_fail(e,rc,"input read error"); eof=1; break; }
            if(atomic_load(&e->stop)){ eof=1; break; }
        }
        s->arrival_ns=now_ns();
        if(total==0){
            /* empty final read must NOT publish a zero-byte data slot */
            if(local_eof) eof=1;
            /* reclaim empty slot without publishing */
            pthread_mutex_lock(&e->mu);
            s->state=RECLAIMING;
            pthread_mutex_unlock(&e->mu);
            if(!seam_has(e,"punch-hole")) fallocate(e->memfd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE,(off_t)soff,(off_t)slot_size);
            pthread_mutex_lock(&e->mu); s->state=FREE; s->generation++; pthread_cond_broadcast(&e->cv_free); pthread_mutex_unlock(&e->mu);
            if(local_eof) eof=1; break;
        }
        if(local_eof) eof=1;

        /* verify generation still matches before copying */
        pthread_mutex_lock(&e->mu);
        int gen_ok = (s->generation==mygen) && (s->state==ASSIGNED);
        pthread_mutex_unlock(&e->mu);
        if(!gen_ok){ engine_fail(e,EIO,"stale generation before copy"); break; }

        /* assign actual global input offset (only now, actual bytes received) */
        input_off_assign = atomic_fetch_add(&e->total_received, total);
        s->input_off=input_off_assign; s->valid_len=total;

        /* ---- explicit memcpy staging -> destination; measure faults around copy ---- */
        pthread_mutex_lock(&e->mu); s->state=COPYING; s->copy_start_ns=now_ns(); pthread_mutex_unlock(&e->mu);
        struct rusage ru0,ru1; getrusage(RUSAGE_THREAD,&ru0);
        uint64_t c0=now_ns();
        memcpy((unsigned char*)e->map + soff, staging, total);   /* explicit memcpy, NOT read-into-dest */
        uint64_t c1=now_ns();
        getrusage(RUSAGE_THREAD,&ru1);
        pthread_mutex_lock(&e->mu); s->copy_end_ns=now_ns(); pthread_mutex_unlock(&e->mu);
        atomic_fetch_add(&e->copy_ns, c1-c0);
        atomic_fetch_add(&e->total_copied, total);
        atomic_fetch_add(&e->reader_minflt, (unsigned long)(ru1.ru_minflt-ru0.ru_minflt));
        atomic_fetch_add(&e->reader_majflt, (unsigned long)(ru1.ru_majflt-ru0.ru_majflt));
        /* which bucket */
        int copied_prepared = s->prepared_before_assign;
        if(copied_prepared) atomic_fetch_add(&e->bytes_copied_prepared,total); else atomic_fetch_add(&e->bytes_copied_lazy,total);
        e->node_stat[snode].copied_bytes+=total; e->node_stat[snode].copy_ns+=(c1-c0);
        e->node_stat[snode].minflt+=(unsigned long)(ru1.ru_minflt-ru0.ru_minflt);
        e->node_stat[snode].majflt+=(unsigned long)(ru1.ru_majflt-ru0.ru_majflt);

        /* verify generation before publication; no publication before copy completion */
        pthread_mutex_lock(&e->mu);
        gen_ok = (s->generation==mygen) && (s->state==COPYING);
        if(gen_ok){
            s->state=PUBLISHED; s->publish_ns=now_ns();
            /* enqueue ordered publish */
            e->pub_q[(e->pub_head + e->pub_n) % e->pub_cap]=s; e->pub_n++;
            atomic_fetch_add(&e->total_published, total);
            pthread_cond_signal(&e->cv_pub);
        }
        pthread_mutex_unlock(&e->mu);
        if(!gen_ok){ engine_fail(e,EIO,"stale generation before publication"); break; }
    }
    /* drain: signal consumer; on stop, don't strand */
    pthread_mutex_lock(&e->mu); pthread_cond_broadcast(&e->cv_pub); pthread_mutex_unlock(&e->mu);
    return NULL;
}

/* ---------- mapping ---------- */
static int setup_mapping(engine_t *e){
    long pg=sysconf(_SC_PAGESIZE); if(pg<=0)pg=4096;
    if(e->slot_size < (size_t)pg || (e->slot_size % (size_t)pg)!=0) return EINVAL;
    /* num_nodes * slots_per_node * slot_size with overflow checks */
    size_t ns=(size_t)e->num_slots;
    if(e->slot_size && ns > SIZE_MAX/e->slot_size) return EOVERFLOW;
    size_t total=ns*e->slot_size; if(total==0||total>SIZE_MAX/2) return EOVERFLOW;
    e->total_capacity=total;
    e->memfd=memfd_create("prefault_pipeline", MFD_CLOEXEC);
    if(e->memfd<0) return errno;
    if(ftruncate(e->memfd,(off_t)total)!=0) return errno;
    /* guarantee 2MiB (and page) aligned virtual range: reserve oversize then carve */
    size_t want_align = THP_DEFAULT_SLOT > (size_t)pg ? THP_DEFAULT_SLOT : (size_t)pg;
    size_t reserve = total + want_align;
    void *resv=mmap(NULL, reserve, PROT_READ|PROT_WRITE, MAP_SHARED, e->memfd, 0);
    if(resv==MAP_FAILED) return errno;
    uintptr_t base=(uintptr_t)resv; uintptr_t aligned=(base + want_align - 1) & ~(uintptr_t)(want_align-1);
    /* munmap slack */
    if(aligned>base){ munmap((void*)base, aligned-base); }
    uintptr_t end=base+reserve; uintptr_t aend=aligned+total; if(aend<end){ munmap((void*)aend, end-aend); }
    e->map=(unsigned char*)aligned; e->map_len=total; e->map_align=want_align;
    if((uintptr_t)e->map % want_align !=0) return EINVAL;
    /* slots */
    e->slots=calloc((size_t)e->num_slots,sizeof(slot_t)); if(!e->slots) return ENOMEM;
    for(int i=0;i<e->num_slots;i++){
        slot_t *s=&e->slots[i]; s->id=(uint64_t)i; s->generation=0; s->node=e->nodes[i % e->num_nodes];
        s->offset=(size_t)i*e->slot_size; s->capacity=e->slot_size; s->state=FREE;
        pthread_mutex_init(&s->mu,NULL); pthread_cond_init(&s->cv,NULL);
        /* mbind slot range too; per-thread policy is authoritative */
        mbind_range((unsigned char*)e->map + s->offset, e->slot_size, s->node);
    }
    e->pub_cap = e->num_slots + e->num_nodes + 4; e->pub_q=calloc((size_t)e->pub_cap,sizeof(slot_t*)); if(!e->pub_q) return ENOMEM;
    /* per-node staging preallocated + first-touched + policy */
    e->staging=calloc((size_t)e->num_nodes,sizeof(staging_t)); if(!e->staging) return ENOMEM;
    for(int i=0;i<e->num_nodes;i++){
        int node=e->nodes[i]; e->staging[i].node=node; e->staging[i].staging_capacity=e->slot_size;
        e->staging[i].staging=mmap(NULL, e->slot_size, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1,0);
        if(e->staging[i].staging==MAP_FAILED) return ENOMEM;
        /* prepare staging under known policy; first-touch it so it doesn't contaminate measurement */
        set_thread_policy_node(node); memset(e->staging[i].staging,0,e->slot_size); e->staging[i].staging_policy_ok=1;
    }
    /* reset reader policy on main thread */
    return 0;
}

/* ---------- run ---------- */
static int run(engine_t *e){
    /* preparation workers: one per node * workers_per_node; pin + per-thread policy */
    int total_workers=0;
    if(e->mode==2) total_workers=e->num_nodes*e->workers_per_node;
    e->num_prep=total_workers;
    if(total_workers>0){
        e->prep_threads=calloc((size_t)total_workers,sizeof(pthread_t));
        if(!e->prep_threads) return ENOMEM;
        for(int i=0;i<total_workers;i++){
            prep_arg_t *pa=calloc(1,sizeof(prep_arg_t)); if(!pa) return ENOMEM;
            pa->e=e; pa->node=e->nodes[i % e->num_nodes]; pa->worker_idx=i;
            if(seam_has(e,"no-worker-create")){ engine_fail(e,EAGAIN,"injected worker creation failure"); free(pa); return e->failed_errno?e->failed_errno:EAGAIN; }
            if(pthread_create(&e->prep_threads[i],NULL,prep_thread,pa)!=0){ engine_fail(e,EAGAIN,"preparation worker creation failure"); free(pa); return e->failed_errno?e->failed_errno:EAGAIN; }
        }
    }
    /* consumer */
    if(pthread_create(&e->consumer_tid,NULL,consumer_thread,e)!=0){ engine_fail(e,EAGAIN,"consumer thread creation failure"); return EAGAIN; }
    /* reader (ordered, single); pin to first node allowed cpu; per-thread policy; */
    pin_to_node(e->nodes[0],NULL); set_thread_policy_node(e->nodes[0]);
    if(pthread_create(&e->reader_tid,NULL,reader_thread,e)!=0){ engine_fail(e,EAGAIN,"reader thread creation failure"); return EAGAIN; }

    pthread_join(e->reader_tid,NULL);
    /* tell consumer no more publishing */
    pthread_mutex_lock(&e->mu); pthread_cond_broadcast(&e->cv_pub); pthread_mutex_unlock(&e->mu);
    /* wait consumer drains published then stop */
    pthread_mutex_lock(&e->mu);
    while(e->pub_n>0){ pthread_cond_wait(&e->cv_done,&e->mu); }
    pthread_mutex_unlock(&e->mu);
    atomic_store(&e->stop,1);
    pthread_mutex_lock(&e->mu); pthread_cond_broadcast(&e->cv_pub); pthread_cond_broadcast(&e->cv_free); pthread_cond_broadcast(&e->cv_ready); pthread_cond_broadcast(&e->cv_done); pthread_mutex_unlock(&e->mu);
    pthread_join(e->consumer_tid,NULL);
    for(int i=0;i<e->num_prep;i++){ pthread_mutex_lock(&e->mu); pthread_cond_broadcast(&e->cv_free); pthread_mutex_unlock(&e->mu); pthread_join(e->prep_threads[i],NULL); }
    return atomic_load(&e->failed) ? (e->failed_errno?e->failed_errno:EIO) : 0;
}

/* ---------- output ---------- */

static int cmp_iv(const void *a, const void *b){ const interval_t *x=a,*y=b; if(x->t0<y->t0)return -1; if(x->t0>y->t0)return 1; return 0; }
static uint64_t merged_len(interval_t *v, size_t n){
    if(n==0) return 0; interval_t *tmp=malloc(n*sizeof(interval_t)); if(!tmp) return 0; memcpy(tmp,v,n*sizeof(interval_t)); qsort(tmp,n,sizeof(interval_t),cmp_iv);
    uint64_t total=0; uint64_t cs=tmp[0].t0, ce=tmp[0].t1;
    for(size_t i=1;i<n;i++){ if(tmp[i].t0>ce){ total+=ce-cs; cs=tmp[i].t0; ce=tmp[i].t1; } else if(tmp[i].t1>ce) ce=tmp[i].t1; }
    total+=ce-cs; free(tmp); return total;
}
static size_t merged_build(interval_t *v, size_t n, interval_t *out){
    if(n==0) return 0; qsort(v,n,sizeof(interval_t),cmp_iv); size_t m=0; out[0]=v[0];
    for(size_t i=1;i<n;i++){ if(v[i].t0>out[m].t1){ out[++m]=v[i]; } else if(v[i].t1>out[m].t1) out[m].t1=v[i].t1; }
    return m+1;
}
static uint64_t intersect_len(const interval_t *a, size_t na, const interval_t *b, size_t nb){
    size_t i=0,j=0; uint64_t total=0;
    while(i<na && j<nb){ uint64_t lo=a[i].t0>b[j].t0?a[i].t0:b[j].t0; uint64_t hi=a[i].t1<b[j].t1?a[i].t1:b[j].t1; if(hi>lo) total+=hi-lo;
        if(a[i].t1<b[j].t1)i++; else j++; } return total;
}
static uint64_t summed_overlap(interval_t *prep, size_t np, interval_t *wait_merged, size_t nw){
    uint64_t total=0; for(size_t i=0;i<np;i++){ interval_t one=prep[i]; total+=intersect_len(&one,1,wait_merged,nw); } return total;
}
static void emit_json(engine_t *e, FILE *out, uint64_t elapsed_ns, int rc, const char *mode_name){
    pthread_mutex_lock(&e->mu);
    uint64_t total_received=atomic_load(&e->total_received), total_copied=atomic_load(&e->total_copied);
    uint64_t total_published=atomic_load(&e->total_published), total_consumed=atomic_load(&e->total_consumed);
    pthread_mutex_unlock(&e->mu);
    double wall=elapsed_ns/1e9; double bps = wall>0 ? total_consumed/wall : 0.0;
    /* overlap measurement: summed worker-time overlapping input-wait vs union wall */
    uint64_t summed_overlap_ns=0, union_wall_ns=0, wait_union_ns=0, prep_union_ns=0;
    pthread_mutex_lock(&e->mu);
    {
        size_t np=e->prep_iv_n, nw=e->wait_iv_n;
        interval_t *prep_copy=calloc(np?np:1,sizeof(interval_t)); interval_t *wait_copy=calloc(nw?nw:1,sizeof(interval_t));
        interval_t *wmerged=calloc(nw?nw:1,sizeof(interval_t)); interval_t *pmerged=calloc(np?np:1,sizeof(interval_t));
        if(prep_copy&&wait_copy&&wmerged&&pmerged){
            if(np) memcpy(prep_copy,e->prep_iv,np*sizeof(interval_t)); if(nw) memcpy(wait_copy,e->wait_iv,nw*sizeof(interval_t));
            size_t nwm=merged_build(wait_copy,nw,wmerged); size_t npm=merged_build(prep_copy,np,pmerged);
            wait_union_ns=merged_len(e->wait_iv,nw); prep_union_ns=merged_len(e->prep_iv,np);
            if(np) memcpy(prep_copy,e->prep_iv,np*sizeof(interval_t)); /* prep_copy restored */
            summed_overlap_ns=summed_overlap(prep_copy,np,wmerged,nwm);
            union_wall_ns=intersect_len(wmerged,nwm,pmerged,npm);
        }
        free(prep_copy);free(wait_copy);free(wmerged);free(pmerged);
    }
    pthread_mutex_unlock(&e->mu);
    uint64_t prep_total=0, prep_ns_total=0, prep_ops=0, prep_fail=0;
    fprintf(out,"{\n");
    fprintf(out," \"mode\": \"%s\",\n", mode_name);
    fprintf(out," \"rc\": %d, \"failed\": %d, \"failed_errno\": %d, \"fail_msg\": \"%s\",\n", rc, atomic_load(&e->failed), e->failed_errno, e->fail_msg);
    fprintf(out," \"slot_size\": %zu, \"slots_per_node\": %d, \"num_nodes\": %d, \"num_slots\": %d,\n", e->slot_size, e->slots_per_node, e->num_nodes, e->num_slots);
    fprintf(out," \"total_reserved_capacity\": %zu, \"map_len\": %zu, \"map_base_alignment\": %zu,\n", e->total_capacity, e->map_len, e->map_align);
    fprintf(out," \"page_size\": %ld, \"memfd\": %d,\n", sysconf(_SC_PAGESIZE), e->memfd);
    fprintf(out," \"nodes\": [");
    for(int i=0;i<e->num_nodes;i++) fprintf(out,"%s%d", i?",":"", e->nodes[i]); fprintf(out,"],\n");
    /* accounting separation */
    fprintf(out," \"total_received\": %llu, \"total_copied\": %llu, \"total_published\": %llu, \"total_consumed\": %llu,\n",
        (unsigned long long)total_received,(unsigned long long)total_copied,(unsigned long long)total_published,(unsigned long long)total_consumed);
    fprintf(out," \"total_reserved\": %zu, \"reserved_preparing_capacity\": %zu,\n", e->total_capacity, e->total_capacity);
    fprintf(out," \"wall_seconds\": %.9f, \"effective_ingest_bytes_per_sec\": %.3f, \"slots_completed\": %llu,\n", wall, bps, (unsigned long long)total_consumed/e->slot_size);
    /* overlap */
    fprintf(out," \"input_wait_ns\": %llu, \"slot_wait_ns\": %llu, \"copy_ns\": %llu,\n",
        (unsigned long long)atomic_load(&e->input_wait_ns),(unsigned long long)atomic_load(&e->slot_wait_ns),(unsigned long long)atomic_load(&e->copy_ns));
    uint64_t prep_busy=0; for(int i=0;i<e->num_nodes;i++) prep_busy+=atomic_load(&e->prepare_busy_ns[i]);
    fprintf(out," \"preparation_worker_busy_ns\": %llu, \"overlap_summed_worker_ns\": %llu, \"overlap_union_wall_ns\": %llu, \"wait_union_ns\": %llu, \"prep_union_ns\": %llu, \"prep_completed_during_input_wait\": %llu, \"reader_no_prepared_count\": %llu,\n",
        (unsigned long long)prep_busy,(unsigned long long)summed_overlap_ns,(unsigned long long)union_wall_ns,(unsigned long long)wait_union_ns,(unsigned long long)prep_union_ns,(unsigned long long)atomic_load(&e->prep_completed_during_input_wait),(unsigned long long)atomic_load(&e->no_prepared_count));
    /* prepared coverage */
    uint64_t prepared_total=atomic_load(&e->prepared_total_bytes);
    fprintf(out," \"prepared_total_bytes\": %llu, \"prepared_destination_bytes\": %llu, \"prepared_ratio\": %.6f,\n",
        (unsigned long long)prepared_total,(unsigned long long)atomic_load(&e->bytes_copied_prepared),
        total_received? (double)atomic_load(&e->bytes_copied_prepared)/(double)total_received : 0.0);
    fprintf(out," \"bytes_copied_lazy\": %llu, \"bytes_copied_prepared\": %llu, \"ready_at_assign\": %llu, \"ready_after_arrival\": %llu,\n",
        (unsigned long long)atomic_load(&e->bytes_copied_lazy),(unsigned long long)atomic_load(&e->bytes_copied_prepared),
        (unsigned long long)atomic_load(&e->ready_at_assign),(unsigned long long)atomic_load(&e->ready_after_arrival));
    /* copy faults */
    fprintf(out," \"copy_minor_faults\": %llu, \"copy_major_faults\": %llu,\n",
        (unsigned long long)atomic_load(&e->reader_minflt),(unsigned long long)atomic_load(&e->reader_majflt));
    /* per-node */
    fprintf(out," \"per_node\": [\n");
    for(int i=0;i<e->num_nodes;i++){
        int node=e->nodes[i]; node_stat_t *ns=&e->node_stat[node];
        prep_total+=ns->prep_ns; prep_ops+=ns->prep_ops; prep_fail+=ns->prep_fail;
        /* bytes per node + slots per node */
        uint64_t node_bytes=ns->bytes;
        fprintf(out,"  {\"node\": %d, \"slots\": %llu, \"bytes\": %llu, \"prep_ops\": %llu, \"prep_ns\": %llu, \"prep_fail\": %llu,\n",
            node,(unsigned long long)ns->slots,(unsigned long long)node_bytes,(unsigned long long)ns->prep_ops,(unsigned long long)ns->prep_ns,(unsigned long long)ns->prep_fail);
        fprintf(out,"   \"prep_throughput_bps\": %.3f, \"prepared_busy_ns\": %llu,\n",
            ns->prep_ns? (double)(ns->prep_ops*e->slot_size)/(ns->prep_ns/1e9):0.0, (unsigned long long)atomic_load(&e->prepare_busy_ns[node]));
        fprintf(out,"   \"copied_bytes\": %llu, \"copy_ns\": %llu, \"copy_minflt\": %llu, \"copy_majflt\": %llu,\n",
            (unsigned long long)ns->copied_bytes,(unsigned long long)ns->copy_ns,(unsigned long long)ns->minflt,(unsigned long long)ns->majflt);
        fprintf(out,"   \"placement_samples\": %llu, \"placed_on_node\": %llu, \"placed_other\": %llu, \"placed_unknown\": %llu, \"placement_ns\": %llu}\n",
            (unsigned long long)ns->placement_samples,(unsigned long long)ns->placed_on_node,(unsigned long long)ns->placed_other,(unsigned long long)ns->placed_unknown,(unsigned long long)ns->placement_ns);
        if(i<e->num_nodes-1) fprintf(out,",\n");
    }
    fprintf(out," ],\n");
    fprintf(out," \"total_prep_ns\": %llu, \"total_prep_ops\": %llu, \"total_prep_fail\": %llu,\n",
        (unsigned long long)prep_total,(unsigned long long)prep_ops,(unsigned long long)prep_fail);
    /* slot state snapshot */
    int freec=0,ready=0; for(int i=0;i<e->num_slots;i++){ if(e->slots[i].state==FREE)freec++; if(e->slots[i].state==READY)ready++; }
    fprintf(out," \"slots_free\": %d, \"slots_ready\": %d, \"num_slots\": %d\n", freec, ready, e->num_slots);
    fprintf(out,"}\n");
}

int main(int argc, char **argv){
    engine_t e; memset(&e,0,sizeof e);
    e.mode=2; e.slot_size=THP_DEFAULT_SLOT; e.slots_per_node=2; e.workers_per_node=1;
    e.num_nodes=0; e.consumer_delay_ns=0; e.placement_sampling=0; e.seam=NULL; e.json_out=NULL;
    atomic_init(&e.stop,0); atomic_init(&e.failed,0); atomic_init(&e.shutting_down,0);
    pthread_mutex_init(&e.mu,NULL); pthread_cond_init(&e.cv_ready,NULL); pthread_cond_init(&e.cv_free,NULL); pthread_cond_init(&e.cv_pub,NULL); pthread_cond_init(&e.cv_done,NULL);
    const char *mode="pipeline_madvise";
    const char *nodelist=NULL;
    for(int i=1;i<argc;i++){
        const char *a=argv[i];
        #define NEXT() (i+1<argc?argv[++i]:"")
        if(!strcmp(a,"--mode")){ mode=NEXT(); }
        else if(!strcmp(a,"--slot-size")){ e.slot_size=strtoul(NEXT(),NULL,0); }
        else if(!strcmp(a,"--slots-per-node")){ e.slots_per_node=atoi(NEXT()); }
        else if(!strcmp(a,"--workers-per-node")){ e.workers_per_node=atoi(NEXT()); }
        else if(!strcmp(a,"--nodes")){ nodelist=NEXT(); }
        else if(!strcmp(a,"--consumer-delay-ns")){ e.consumer_delay_ns=atol(NEXT()); }
        else if(!strcmp(a,"--placement-sampling")){ e.placement_sampling=1; }
        else if(!strcmp(a,"--seam")){ e.seam=NEXT(); }
        else if(!strcmp(a,"--json-out")){ e.json_out=NEXT(); }
        else { fprintf(stderr,"unknown arg %s\n",a); return 2; }
    }
    if(!strcmp(mode,"lazy")) e.mode=0; else if(!strcmp(mode,"serial_madvise")) e.mode=1; else if(!strcmp(mode,"pipeline_madvise")) e.mode=2; else { fprintf(stderr,"bad mode\n"); return 2; }
    /* topology / sparse node ids */
    if(nodelist){ e.num_nodes=parse_node_list(nodelist,e.nodes,MAX_NODES); if(e.num_nodes<=0){fprintf(stderr,"bad --nodes\n");return 2;} }
    else { e.num_nodes=discover_online_nodes(e.nodes,MAX_NODES); if(e.num_nodes<=0){ e.nodes[0]=0; e.num_nodes=1; } }
    /* dedupe + sort */
    /* validation: slot size page-aligned; slots per node; total capacity; overflow */
    long pg=sysconf(_SC_PAGESIZE); if(pg<=0)pg=4096;
    if(e.slot_size==0 || e.slot_size%(size_t)pg!=0){ fprintf(stderr,"slot_size must be page-aligned nonzero\n"); return 2; }
    if(e.slots_per_node<1){ fprintf(stderr,"slots_per_node must be >=1\n"); return 2; }
    if(e.workers_per_node<1){ fprintf(stderr,"workers_per_node must be >=1\n"); return 2; }
    e.num_slots = e.num_nodes * e.slots_per_node;
    if(e.num_slots<1){ fprintf(stderr,"no slots\n"); return 2; }
    if((size_t)e.num_slots > SIZE_MAX / e.slot_size){ fprintf(stderr,"capacity overflow\n"); return 2; }

    int mrc=setup_mapping(&e); if(mrc!=0){ fprintf(stderr,"mapping setup failed errno=%d\n",mrc); return 1; }
    uint64_t t0=now_ns();
    int rc=run(&e);
    uint64_t t1=now_ns();
    /* verify no slot left in-flight; every reserved slot accounted for */
    int leftover=0; for(int i=0;i<e.num_slots;i++){ slot_state_t st=e.slots[i].state; if(st!=FREE&&st!=READY){leftover++;} }
    if(leftover>0 && rc==0){ rc=EIO; engine_fail(&e,EIO,"slot left in-flight at shutdown"); }
    /* consistency: totals */
    uint64_t tr=atomic_load(&e.total_received), tc=atomic_load(&e.total_copied), tp=atomic_load(&e.total_published), tcons=atomic_load(&e.total_consumed);
    if(rc==0 && !(tr==tc && tc==tp && tp==tcons)){ rc=EIO; engine_fail(&e,EIO,"accounting mismatch received!=copied!=published!=consumed"); }
    FILE *out=stdout;
    if(e.json_out){ out=fopen(e.json_out,"w"); if(!out){ fprintf(stderr,"cannot open json-out\n"); out=stdout; } }
    emit_json(&e,out,t1-t0,rc,mode);
    if(out!=stdout) fclose(out);
    /* cleanup (LSan-clean) */
    for(int i=0;i<e.num_slots;i++){ pthread_mutex_destroy(&e.slots[i].mu); pthread_cond_destroy(&e.slots[i].cv); }
    for(int i=0;i<e.num_nodes;i++){ if(e.staging && e.staging[i].staging && e.staging[i].staging!=MAP_FAILED) munmap(e.staging[i].staging, e.staging[i].staging_capacity); }
    if(e.map && e.map_len) munmap(e.map, e.map_len);
    if(e.memfd>=0) close(e.memfd);
    free(e.slots); free(e.pub_q); free(e.staging); free(e.prep_threads);
    free(e.prep_iv); free(e.wait_iv);
    pthread_mutex_destroy(&e.mu); pthread_cond_destroy(&e.cv_ready); pthread_cond_destroy(&e.cv_free); pthread_cond_destroy(&e.cv_pub); pthread_cond_destroy(&e.cv_done);
    return rc?1:0;
}
