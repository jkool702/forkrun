// forkrun_ring.c v6.89
// Architecture: Universal Ingest, Zero-Copy Ring, Escrow Stealing
// Features: Decoupled Fallow, Index-Based Reclamation, Real-Time Ordered Output
// Optimization: Starvation-Aware Flush, Persistent Accumulation State

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif

// Ensure 64-bit file offsets on 32-bit architectures
#ifndef _FILE_OFFSET_BITS
#define _FILE_OFFSET_BITS 64
#endif

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <sys/eventfd.h>
#include <poll.h>
#include <limits.h>
#include <stdbool.h>
#include <inttypes.h>
#include <sched.h>
#include <sys/sendfile.h>
#include <sys/sysinfo.h>
#include <time.h> 

// --- Architecture Specific Pause Logic ---
#if defined(__x86_64__) || defined(__i386__)
  #define cpu_relax() __builtin_ia32_pause()
#elif defined(__aarch64__) || defined(__arm__)
  #define cpu_relax() __asm__ __volatile__("yield" ::: "memory")
#elif defined(__riscv)
  #define cpu_relax() __asm__ __volatile__(".option push; .option arch, +zihintpause; pause; .option pop" ::: "memory")
#elif defined(__powerpc__) || defined(__ppc__) || defined(__PPC__)
  #define cpu_relax() __asm__ __volatile__("or 27,27,27" ::: "memory")
#elif defined(__s390__) || defined(__s390x__)
  #define cpu_relax() __asm__ __volatile__("diag 0,0,0x44" ::: "memory")
#else
  #define cpu_relax() __asm__ __volatile__("" ::: "memory")
#endif

#ifndef FALLOC_FL_KEEP_SIZE
#define FALLOC_FL_KEEP_SIZE 0x01
#endif
#ifndef FALLOC_FL_PUNCH_HOLE
#define FALLOC_FL_PUNCH_HOLE 0x02
#endif

#define FLAG_PARTIAL_BATCH (1ULL << 63)
#define HUGE_PAGE_SIZE (2 * 1024 * 1024) 
#define RING_SIZE_LOG2 20
#define RING_SIZE      (1ULL << RING_SIZE_LOG2)
#define RING_MASK      (RING_SIZE - 1)
#define CACHE_LINE     256
#define ALIGNED(x)     __attribute__((aligned(x > CACHE_LINE ? x : CACHE_LINE)))

#define atomic_load_acquire(ptr)       __atomic_load_n(ptr, __ATOMIC_ACQUIRE)
#define atomic_load_relaxed(ptr)       __atomic_load_n(ptr, __ATOMIC_RELAXED)
#define atomic_store_release(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELEASE)
#define atomic_store_relaxed(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELAXED)
#define atomic_fetch_add(ptr, val)     __atomic_fetch_add(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_fetch_sub(ptr, val)     __atomic_fetch_sub(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_compare_exchange(ptr, exp, des) __atomic_compare_exchange_n(ptr, exp, des, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"
#include "variables.h"

extern void dispose_command(COMMAND *);
extern int execute_command(COMMAND *); 
extern int add_builtin(struct builtin *bp, int keep);

static int ring_init_main(int argc, char **argv);
static int ring_destroy_main(int argc, char **argv);
static int ring_scanner_main(int argc, char **argv);
static int ring_claim_main(int argc, char **argv);
static int ring_worker_main(int argc, char **argv);
static int ring_ingest_main(int argc, char **argv);
static int ring_fallow_main(int argc, char **argv);
static int ring_ack_main(int argc, char **argv);
static int ring_order_main(int argc, char **argv);
static int evfd_copy_main(int argc, char **argv);
static int evfd_signal_main(int argc, char **argv);
static int lseek_main(int argc, char ** argv);

static void *xmalloc_aligned(size_t size) {
    void *ptr;
    if (posix_memalign(&ptr, HUGE_PAGE_SIZE, size) != 0) ptr = xmalloc(size);
    return ptr;
}

// --- Shared State ---
struct SharedState {
    uint64_t read_idx ALIGNED(CACHE_LINE);
    uint64_t active_workers;
    uint64_t total_lines_consumed;
    uint32_t active_waiters; 
    
    uint64_t min_idx; 
    uint8_t  fallow_active;
    char pad0[119]; 

    uint64_t write_idx ALIGNED(CACHE_LINE);
    int64_t  signed_batch_size; 
    uint64_t batch_change_idx;  
    uint8_t  ingest_complete;
    char pad1[128]; 

    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
};

static struct SharedState *state = NULL;
static int evfd_data = -1;
static int evfd_eof  = -1;
static int evfd_ingest_data = -1;
static int evfd_ingest_eof  = -1;
static int fd_escrow[2] = { -1, -1 }; 

// Thread Local Storage
static __thread bool is_waiting_on_ring = false;

struct EscrowPacket { uint64_t idx; uint64_t cnt; };
struct IndexPacket  { uint64_t idx; uint64_t cnt; }; 
struct Interval     { uint64_t s; uint64_t e; struct Interval *next; };

static inline void u64toa(uint64_t value, char* buffer) {
    char temp[24];
    char *p = temp;
    if (value == 0) { *buffer++ = '0'; *buffer = '\0'; return; }
    do { *p++ = (char)(value % 10) + '0'; value /= 10; } while (value > 0);
    int i = 0; while (p > temp) buffer[i++] = *--p;
    buffer[i] = '\0';
}

static inline uint64_t get_us_time() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_COARSE, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000;
}

static inline uint64_t fast_log2(uint64_t v) {
    if (v < 2) return 0;
    return 63 - __builtin_clzll(v);
}

// --- Tuning Helpers ---
static uint64_t get_cache_bytes() {
    long sz = -1;
#ifdef _SC_LEVEL2_CACHE_SIZE
    sz = sysconf(_SC_LEVEL2_CACHE_SIZE);
#endif
    if (sz <= 0) {
#ifdef _SC_LEVEL3_CACHE_SIZE
        sz = sysconf(_SC_LEVEL3_CACHE_SIZE);
#endif
    }
    if (sz <= 0) return 512 * 1024; 
    return (uint64_t)sz;
}

static uint64_t get_arg_max_bytes() {
    long sys_arg_max = sysconf(_SC_ARG_MAX);
    if (sys_arg_max <= 0) return 2097152; 
    size_t env_len = 0;
    extern char **environ;
    for (char **ep = environ; *ep; ++ep) env_len += strlen(*ep) + 1;
    if ((long)env_len < sys_arg_max) return (uint64_t)((sys_arg_max - (long)env_len) * 15 / 16);
    return 32768; 
}

// --- Init/Destroy ---
static int ring_init_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state != NULL) {
        atomic_store_relaxed(&state->read_idx, 0);
        atomic_store_relaxed(&state->write_idx, 0);
        atomic_store_relaxed(&state->ingest_complete, 0);
        atomic_store_relaxed(&state->total_lines_consumed, 0);
        atomic_store_relaxed(&state->min_idx, 0);
        atomic_store_relaxed(&state->fallow_active, 0);
        
        if (fd_escrow[0] >= 0) {
            char dump[1024];
            while(read(fd_escrow[0], dump, sizeof(dump)) > 0) {}
        }
        return EXECUTION_SUCCESS;
    }

    size_t total_size = sizeof(struct SharedState);
    total_size = (total_size + 4095ULL) & ~4095ULL;

    void *p = mmap(NULL, total_size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) { builtin_error("mmap: %s", strerror(errno)); return EXECUTION_FAILURE; }
    state = (struct SharedState *)p;
    memset(p, 0, total_size);

    evfd_data        = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_eof         = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_ingest_data = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK); 
    evfd_ingest_eof  = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    
    if (pipe(fd_escrow) < 0) return EXECUTION_FAILURE;
    fcntl(fd_escrow[0], F_SETFL, O_NONBLOCK); fcntl(fd_escrow[1], F_SETFL, O_NONBLOCK);
    fcntl(fd_escrow[0], F_SETFD, FD_CLOEXEC); fcntl(fd_escrow[1], F_SETFD, FD_CLOEXEC);
    fcntl(fd_escrow[1], F_SETPIPE_SZ, 1048576);

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", evfd_data); bind_variable("EVFD_RING_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_eof);  bind_variable("EVFD_RING_EOF", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_data); bind_variable("EVFD_RING_INGEST_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_eof);  bind_variable("EVFD_RING_INGEST_EOF", buf, 0);

    return EXECUTION_SUCCESS;
}

static int ring_destroy_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state) { munmap(state, sizeof(struct SharedState)); state = NULL; }
    if (evfd_data >= 0) { close(evfd_data); evfd_data = -1; }
    if (evfd_eof >= 0) { close(evfd_eof); evfd_eof = -1; }
    if (evfd_ingest_data >= 0) { close(evfd_ingest_data); evfd_ingest_data = -1; }
    if (evfd_ingest_eof >= 0) { close(evfd_ingest_eof); evfd_ingest_eof = -1; }
    if (fd_escrow[0] >= 0) { close(fd_escrow[0]); close(fd_escrow[1]); fd_escrow[0] = -1; }
    
    unbind_variable("EVFD_RING_DATA"); unbind_variable("EVFD_RING_EOF");
    unbind_variable("EVFD_RING_INGEST_DATA"); unbind_variable("EVFD_RING_INGEST_EOF");
    return EXECUTION_SUCCESS;
}

// --- Scanner ---
#define SCANNER_WAKE() do { if(atomic_load_relaxed(&state->active_waiters)>0) { uint64_t v=1; if(write(evfd_data,&v,8)){}; } } while(0)

#define SCANNER_FLUSH(cnt) do { \
    while(1) { \
        uint64_t limit; \
        if (atomic_load_relaxed(&state->fallow_active)) { \
            limit = atomic_load_acquire(&state->min_idx); \
        } else { \
            limit = atomic_load_acquire(&state->read_idx); \
        } \
        if ((local_write_idx - limit) < RING_SIZE) break; \
        SCANNER_WAKE(); usleep(100); \
    } \
    uint64_t pk = (uint64_t)batch_start; \
    if (cnt != L) pk |= FLAG_PARTIAL_BATCH; \
    state->offset_ring[local_write_idx & RING_MASK] = pk; \
    state->stride_ring[local_write_idx & RING_MASK] = (uint16_t)cnt; \
    local_write_idx++; \
    atomic_store_release(&state->write_idx, local_write_idx); \
    SCANNER_WAKE(); \
} while(0)

static int ring_scanner_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    int fd_spawn = (argc >= 3) ? atoi(argv[2]) : -1;

    // --- Configuration Logic ---
    uint64_t val_l2  = (get_cache_bytes() * 3) >> 2; 
    uint64_t val_arg = (get_arg_max_bytes() * 3) >> 2; 
    
    uint64_t L = 1; 
    uint64_t Lmax = 4096; 
    uint64_t BytesMax = (val_l2 < val_arg) ? val_l2 : val_arg;
    uint64_t W = 1;
    char *tmp_var;
    
    if ((tmp_var = get_string_value("nLinesMax"))) {
        char *endptr;
        long val = strtol(tmp_var, &endptr, 10);
        if (endptr == tmp_var) Lmax = 4096; 
        else if (val <= 0) Lmax = 65535;
        else Lmax = (uint64_t)((val > 65535) ? 65535 : val);
    }

    if ((tmp_var = get_string_value("nBytesMax"))) {
        if (strcmp(tmp_var, "L2") == 0) BytesMax = val_l2;
        else if (strcmp(tmp_var, "ARG_MAX") == 0) BytesMax = val_arg;
        else {
            char *endptr;
            long long val = strtoll(tmp_var, &endptr, 10);
            if (endptr != tmp_var) { 
                if (val <= 0) BytesMax = 0; 
                else BytesMax = (uint64_t)val;
            }
        }
    }

    long nWorkersMax = sysconf(_SC_NPROCESSORS_ONLN); 
    if ((tmp_var = get_string_value("nWorkersMax"))) {
        long val = atol(tmp_var);
        if (val > 0) nWorkersMax = val;
    }
    if (nWorkersMax < 1) nWorkersMax = 1;

    if ((tmp_var = get_string_value("nWorkers"))) {
        long val = atol(tmp_var);
        if (val > 0 && val <= nWorkersMax) W = (uint64_t)val;
    }

    uint64_t W_max_val = (uint64_t)nWorkersMax;
    uint64_t W2 = fast_log2(W_max_val);
    uint64_t L2 = fast_log2(Lmax);
    uint64_t X_const = fast_log2(W2 + L2) * W2;
    if (X_const == 0) X_const = 1;

    uint64_t local_write_idx = 0;
    size_t CHUNK = HUGE_PAGE_SIZE;
    char *buf = xmalloc_aligned(CHUNK);
    char *p = buf, *end = buf;
    
    uint64_t buf_base_offset = lseek(fd, 0, SEEK_CUR);
    uint64_t batch_start = buf_base_offset;
    int status = 0; 

    // --- State Machine ---
    int phase = 0;
    uint64_t batch_counter = 0;
    uint64_t target_count = 0;

    uint64_t last_calc_us = get_us_time();
    uint64_t last_calc_write = 0;
    uint64_t last_calc_read = 0;
    uint64_t stall_counter = 0; 
    
    atomic_store_relaxed(&state->write_idx, 0);
    atomic_store_relaxed(&state->read_idx, 0);
    atomic_store_relaxed(&state->signed_batch_size, (int64_t)L);
    atomic_store_relaxed(&state->active_workers, W);

    bool limit_reached = false;
    uint64_t pending_lines = 0;

    #define SCAN_BATCH(target_L) ({ \
        uint64_t lines_found = 0; \
        limit_reached = false; \
        while (lines_found < (target_L)) { \
            if (p >= end) break; \
            char *nl = memchr(p, '\n', end - p); \
            if (nl) { \
                if (BytesMax > 0 && lines_found > 0) { \
                    uint64_t line_end_offset = buf_base_offset + (uint64_t)((nl + 1) - buf); \
                    uint64_t payload = line_end_offset - batch_start; \
                    uint64_t overhead = (lines_found + 1) * 8; \
                    if ((payload + overhead) > BytesMax) { \
                        limit_reached = true; \
                        break; \
                    } \
                } \
                lines_found++; \
                p = nl + 1; \
            } else { \
                if (status == 1) { \
                    if (p < end) { lines_found++; p = end; } \
                } \
                break; \
            } \
        } \
        lines_found; \
    })

    bool force_refill = false;

    while (status != 1 || p < end) {
        if ((p >= end || force_refill) && status != 1) {
            force_refill = false;
            
            uint64_t curr_off = buf_base_offset + (p - buf);
            if (lseek(fd, (off_t)curr_off, SEEK_SET) < 0) {} 
            ssize_t n = read(fd, buf, CHUNK);
            
            if (n > 0) {
                buf_base_offset = curr_off;
                p = buf; 
                end = buf + n;
                status = 0;
            } else {
                struct pollfd pfds[2] = { 
                    { .fd = evfd_ingest_data, .events = POLLIN }, 
                    { .fd = evfd_ingest_eof,  .events = POLLIN } 
                };
                
                SCANNER_WAKE();
                
                int ret = poll(pfds, 2, 100);
                
                bool d_ready = (ret > 0 && (pfds[0].revents & POLLIN));
                bool e_sig   = (ret > 0 && (pfds[1].revents & POLLIN));
                
                if (d_ready) {
                    uint64_t v; if(read(evfd_ingest_data, &v, 8)){};
                    status = 2; 
                } else if (e_sig) {
                    atomic_store_release(&state->ingest_complete, 1);
                    status = 1;
                } else {
                    if (atomic_load_acquire(&state->ingest_complete)) {
                        status = 1;
                    } else {
                        // poll wait
                    }
                }
                
                if (status == 2) {
                    stall_counter += 10;
                    if (p < end) force_refill = true;
                    continue; 
                }
            }
        }

        uint64_t scan_target = (L > pending_lines) ? (L - pending_lines) : 0;
        if (scan_target == 0 && !limit_reached) scan_target = 1; // Sanity edge case

        uint64_t found = SCAN_BATCH(scan_target);
        pending_lines += found;

        if (pending_lines > 0) {
            bool starvation = (atomic_load_relaxed(&state->active_waiters) > 0);
            
            if (pending_lines >= L || status == 1 || limit_reached || starvation) {
                SCANNER_FLUSH(pending_lines);
                batch_start = buf_base_offset + (uint64_t)(p - buf);
                batch_counter++;
                pending_lines = 0;
                force_refill = false;

                // --- Ramp / PID Logic ---
                target_count = W * 4;
                if (target_count < 4) target_count = 4;

                if (phase == 0) {
                    if (batch_counter >= target_count) {
                        phase = 1;
                        batch_counter = 0;
                    }
                }
                else if (phase == 1) {
                    if (status == 2) phase = 2; 
                    else if (batch_counter >= target_count) {
                        L *= 2;
                        if (L >= Lmax) { L = Lmax; phase = 2; }
                        
                        if (W < W_max_val) {
                                uint64_t l_log = fast_log2(L);
                                uint64_t num = 6 * (W_max_val - W) * L2;
                                uint64_t den = X_const * (L2 + l_log);
                                if (den == 0) den = 1;
                                uint64_t n_spawn = num / den;
                                if (n_spawn < 1) n_spawn = 1;
                                if (n_spawn > (W_max_val - W)) n_spawn = W_max_val - W;
                                if (fd_spawn >= 0) {
                                    dprintf(fd_spawn, "%lu\n", n_spawn);
                                    W += n_spawn;
                                    atomic_store_relaxed(&state->active_workers, W);
                                }
                        }

                        atomic_store_release(&state->batch_change_idx, local_write_idx);
                        atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                        batch_counter = 0;
                    }
                } 
                else { 
                    uint64_t now_us = get_us_time();
                    if (now_us - last_calc_us > 5000) { 
                        uint64_t d_in  = local_write_idx - last_calc_write;
                        uint64_t r_con = atomic_load_relaxed(&state->total_lines_consumed);
                        uint64_t d_out = r_con - last_calc_read;
                        last_calc_write = local_write_idx;
                        last_calc_read  = r_con;
                        last_calc_us    = now_us;

                        if (d_out > 0) {
                            uint64_t rate = d_out / W; if(rate==0) rate=1;
                            uint64_t w_ideal = d_in / rate;
                            if (w_ideal > W_max_val) w_ideal = W_max_val;
                            if (w_ideal > W) {
                                uint64_t grow = (w_ideal - W + 1) / 2;
                                if (fd_spawn >= 0) dprintf(fd_spawn, "%lu\n", grow);
                                W += grow;
                                atomic_store_relaxed(&state->active_workers, W);
                            } 
                        }

                        uint64_t r_idx = atomic_load_relaxed(&state->read_idx);
                        int64_t backlog = (int64_t)local_write_idx - (int64_t)r_idx;
                        if (backlog < 0) backlog = 0;
                        
                        uint64_t l_target = (backlog / W);
                        if (l_target > Lmax) l_target = Lmax;
                        if (l_target < 1) l_target = 1;
                        
                        if (l_target > L) {
                            L = l_target;
                            atomic_store_release(&state->batch_change_idx, local_write_idx);
                            atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                        } else if (l_target < L && stall_counter > 5) {
                            L = (L + l_target) / 2;
                            if (L < 1) L = 1;
                            atomic_store_release(&state->batch_change_idx, local_write_idx);
                            atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                            stall_counter = 0; 
                        }
                    }
                }
                if (pending_lines < L) stall_counter++; else stall_counter = 0;
            } else {
                force_refill = true; 
            }
        } else {
            if (status == 1) break; 
            force_refill = true; 
        }
    }

    uint64_t final_sentinel = buf_base_offset + (uint64_t)(p - buf);
    state->offset_ring[local_write_idx & RING_MASK] = (uint64_t)final_sentinel | FLAG_PARTIAL_BATCH;
    local_write_idx++;
    atomic_store_release(&state->write_idx, local_write_idx);
    
    SCANNER_WAKE();
    if (fd_spawn >= 0) if(write(fd_spawn, "x\n", 2)){};
    
    uint64_t w = 999999; if(write(evfd_eof, &w, 8)){};
    free(buf);
    return EXECUTION_SUCCESS;
}

// --- Claim ---
static int ring_claim_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    const char *v_off = argv[1];
    const char *v_cnt = argv[2];
    int fd_read = (argc == 4) ? atoi(argv[3]) : -1;

    uint64_t my_read_idx;
    uint64_t claim_count = 1;
    int spin = 0;

    while (1) {
        struct EscrowPacket ep;
        if (fd_escrow[0] >= 0 && read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
            my_read_idx = ep.idx;
            claim_count = ep.cnt;
            break; 
        }

        uint64_t w_snap = atomic_load_acquire(&state->write_idx);
        uint64_t r_curr = atomic_load_relaxed(&state->read_idx);

        if (r_curr >= w_snap) {
            if (spin < 100) { cpu_relax(); spin++; continue; }
            
            atomic_fetch_add(&state->active_waiters, 1);
            is_waiting_on_ring = true;
            
            if (evfd_ingest_data >= 0) {
                uint64_t v = 1;
                if(write(evfd_ingest_data, &v, 8)){};
            }
            
            struct pollfd pfds[3] = { 
                { .fd = evfd_data, .events = POLLIN }, 
                { .fd = evfd_eof,  .events = POLLIN },
                { .fd = fd_escrow[0], .events = POLLIN }
            };

            while (1) {
                int ret = poll(pfds, 3, -1);
                if (ret < 0) { if (errno==EINTR) continue; break; }
                
                if (pfds[2].revents & POLLIN) { 
                    if (read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
                        my_read_idx = ep.idx; claim_count = ep.cnt;
                        atomic_fetch_sub(&state->active_waiters, 1);
                        is_waiting_on_ring = false;
                        goto verify_claim;
                    }
                }
                if (pfds[0].revents) { uint64_t v; if(read(evfd_data, &v, 8)){}; break; }
                if (pfds[1].revents) { 
                    if (atomic_load_acquire(&state->write_idx) <= atomic_load_relaxed(&state->read_idx)) {
                        if (read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
                             my_read_idx = ep.idx; claim_count = ep.cnt;
                             atomic_fetch_sub(&state->active_waiters, 1);
                             is_waiting_on_ring = false;
                             goto verify_claim;
                        }
                        atomic_fetch_sub(&state->active_waiters, 1);
                        is_waiting_on_ring = false;
                        bind_variable(v_cnt, "0", 0); return 1; 
                    }
                    break; 
                }
            }
            atomic_fetch_sub(&state->active_waiters, 1);
            is_waiting_on_ring = false;
            spin = 0; continue;
        }

        int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size); 
        claim_count = 1;
        if (sbatch < 0) {
            uint64_t Ib = atomic_load_acquire(&state->batch_change_idx); (void)Ib;
            uint16_t L0 = state->stride_ring[r_curr & RING_MASK];
            if (L0 == 0) L0 = 1;
            uint64_t Wmax = atomic_load_relaxed(&state->active_workers); 
            if (Wmax == 0) Wmax = 1;
            uint64_t B = ((uint64_t)(-sbatch)) / L0;
            if (B > Wmax) B = Wmax;
            if (B < 1) B = 1;
            claim_count = B;
            
            if (claim_count > 64) claim_count = 64;
        }
        if (r_curr + claim_count > w_snap) claim_count = w_snap - r_curr;
        if (claim_count < 1) claim_count = 1;

        my_read_idx = atomic_fetch_add(&state->read_idx, claim_count);
        
        if (sbatch < 0) {
            uint64_t Ib = atomic_load_relaxed(&state->batch_change_idx);
            if (my_read_idx > Ib) {
                 int64_t target = -sbatch;
                 atomic_compare_exchange(&state->signed_batch_size, &sbatch, target);
            }
        }
        break;
    }

verify_claim:;
    if (my_read_idx + claim_count > atomic_load_acquire(&state->write_idx)) {
         atomic_fetch_add(&state->active_waiters, 1);
         is_waiting_on_ring = true;
         while (1) {
             uint64_t w_curr = atomic_load_acquire(&state->write_idx);
             if (w_curr > my_read_idx) {
                 uint64_t avail = w_curr - my_read_idx;
                 if (avail < claim_count) {
                     struct EscrowPacket ep = { .idx = my_read_idx + avail, .cnt = claim_count - avail };
                     if (write(fd_escrow[1], &ep, sizeof(ep)) == sizeof(ep)) {
                         claim_count = avail;
                         uint64_t one=1; if(write(evfd_data, &one, 8)){};
                     }
                 }
                 break; 
             }
             
             struct pollfd pfds[2] = { { .fd = evfd_data, .events = POLLIN }, { .fd = evfd_eof, .events = POLLIN } };
             poll(pfds, 2, -1);
             if (pfds[0].revents) { uint64_t v; if(read(evfd_data, &v, 8)){}; }
             if (pfds[1].revents) {
                  uint64_t w_final = atomic_load_acquire(&state->write_idx);
                  if (w_final <= my_read_idx) {
                      atomic_fetch_sub(&state->active_waiters, 1);
                      bind_variable(v_cnt, "0", 0); return 1;
                  }
                  if (w_final < my_read_idx + claim_count) claim_count = w_final - my_read_idx;
                  break; 
             }
         }
         atomic_fetch_sub(&state->active_waiters, 1);
         is_waiting_on_ring = false;
    }

    uint64_t final_lines = 0;
    uint64_t final_offset = state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;

    if (claim_count == 1) {
        int64_t sbatch_now = atomic_load_relaxed(&state->signed_batch_size);
        if (sbatch_now > 0 && !(state->offset_ring[my_read_idx & RING_MASK] & FLAG_PARTIAL_BATCH)) {
            final_lines = sbatch_now;
        } else {
            final_lines = state->stride_ring[my_read_idx & RING_MASK];
        }
    } else {
        for (uint64_t i = 0; i < claim_count; i++) final_lines += state->stride_ring[(my_read_idx + i) & RING_MASK];
    }

    atomic_fetch_add(&state->total_lines_consumed, final_lines);
    char buf[64];
    u64toa(final_offset, buf); bind_variable(v_off, buf, 0);
    u64toa(final_lines, buf); bind_variable(v_cnt, buf, 0);
    
    u64toa(my_read_idx, buf); bind_variable("RING_BATCH_IDX", buf, 0);
    u64toa(claim_count, buf); bind_variable("RING_BATCH_SLOTS", buf, 0);

    if (fd_read >= 0 && final_lines > 0) lseek(fd_read, (off_t)final_offset, SEEK_SET);
    return 0;
}

// --- Ring Ack (Supports Multicast & Optional Fallow) ---
static int ring_ack_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    
    int fd_fallow = -1;
    if (argv[1][0] != '\0') fd_fallow = atoi(argv[1]);
    
    int fd_order  = (argc >= 3) ? atoi(argv[2]) : -1;
    
    const char *s_idx = get_string_value("RING_BATCH_IDX");
    const char *s_cnt = get_string_value("RING_BATCH_SLOTS");
    
    if (s_idx && s_cnt) {
        struct IndexPacket ip = { 
            .idx = (uint64_t)atoll(s_idx), 
            .cnt = (uint64_t)atoll(s_cnt) 
        };
        
        if (fd_fallow > 0) {
            if (write(fd_fallow, &ip, sizeof(ip)) != sizeof(ip)) return EXECUTION_FAILURE;
        }
        
        if (fd_order > 0) {
            if (write(fd_order, &ip, sizeof(ip)) != sizeof(ip)) { /* ignore error */ }
        }
    }
    return EXECUTION_SUCCESS;
}

// --- Ring Order (Output Consumer) ---
static int ring_order_main(int argc, char **argv) {
    if (argc < 3) {
        builtin_error("usage: ring_order <FD_IN> <DIR_PREFIX>");
        return EXECUTION_FAILURE;
    }
    
    int fd_in = atoi(argv[1]);
    const char *prefix = argv[2];
    
    struct Interval *head = NULL;
    uint64_t next_idx = 0;
    struct IndexPacket ip;
    char path[256];
    
    while (read(fd_in, &ip, sizeof(ip)) == sizeof(ip)) {
        if (ip.idx == next_idx) {
            snprintf(path, sizeof(path), "%s.%lu", prefix, ip.idx);
            int fd_file = open(path, O_RDONLY);
            if (fd_file >= 0) {
                off_t offset = 0;
                struct stat st;
                if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                    ssize_t sent = 0;
                    while (offset < st.st_size) {
                        sent = sendfile(1, fd_file, &offset, st.st_size - offset);
                        if (sent < 0) {
                            if (errno == EINTR) continue;
                            if (errno == EINVAL || errno == ENOSYS || errno == ENOTSOCK || errno == EBADF) {
                                char buf[32768];
                                ssize_t n;
                                lseek(fd_file, offset, SEEK_SET);
                                while ((n = read(fd_file, buf, sizeof(buf))) > 0) {
                                    write(1, buf, n);
                                }
                            }
                            break; 
                        }
                    }
                }
                close(fd_file);
                unlink(path);
            }
            
            next_idx += ip.cnt;
            
            while (head && head->s == next_idx) {
                struct Interval *tmp = head;
                snprintf(path, sizeof(path), "%s.%lu", prefix, tmp->s);
                fd_file = open(path, O_RDONLY);
                if (fd_file >= 0) {
                    off_t offset = 0;
                    struct stat st;
                    if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                        ssize_t sent = 0;
                        while (offset < st.st_size) {
                            sent = sendfile(1, fd_file, &offset, st.st_size - offset);
                            if (sent < 0) {
                                if (errno == EINTR) continue;
                                if (errno == EINVAL || errno == ENOSYS || errno == ENOTSOCK || errno == EBADF) {
                                    char buf[32768];
                                    ssize_t n;
                                    lseek(fd_file, offset, SEEK_SET);
                                    while ((n = read(fd_file, buf, sizeof(buf))) > 0) {
                                        write(1, buf, n);
                                    }
                                }
                                break; 
                            }
                        }
                    }
                    close(fd_file);
                    unlink(path);
                }
                
                next_idx = tmp->e; 
                head = tmp->next;
                free(tmp);
            }
        } else {
            struct Interval *n = xmalloc(sizeof(struct Interval));
            n->s = ip.idx; 
            n->e = ip.idx + ip.cnt; 
            struct Interval **curr = &head;
            while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
            n->next = *curr;
            *curr = n;
        }
    }
    return EXECUTION_SUCCESS;
}

// --- Evfd Copy/Signal (Ingest Splicer with OOM Backpressure) ---
static int evfd_copy_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int outfd = atoi(argv[1]);
    int infd  = (argc == 3) ? atoi(argv[2]) : 0;
    size_t chunk = HUGE_PAGE_SIZE; 
    struct stat st;
    
    // Calculate dynamic OOM threshold (max(128MB, TotalRAM/128))
    uint64_t oom_threshold = 134217728; // Default 128MB
    struct sysinfo si_init;
    if (sysinfo(&si_init) == 0) {
        uint64_t mu = (uint64_t)si_init.mem_unit ? si_init.mem_unit : 1;
        uint64_t total = (uint64_t)si_init.totalram * mu;
        uint64_t t = total / 128;
        if (t > oom_threshold) oom_threshold = t;
    }

    uint64_t total_moved = 0;
    uint64_t next_check = 16 * 1024 * 1024;
    
    if (fstat(infd, &st) == 0 && S_ISREG(st.st_mode)) {
        off_t off = 0;
        while(1) {
            ssize_t n = sendfile(outfd, infd, &off, chunk);
            if (n <= 0) break;
            if (evfd_ingest_data >= 0) { uint64_t v=1; if(write(evfd_ingest_data, &v, 8)){}; }
            
            // Check OOM
            total_moved += n;
            if (total_moved > next_check) {
                struct sysinfo si;
                if (sysinfo(&si) == 0) {
                    uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                    uint64_t free_b = (uint64_t)si.freeram * mu;
                    if (free_b < oom_threshold) {
                        if (state && atomic_load_relaxed(&state->fallow_active)) {
                            int r = 0;
                            while (free_b < oom_threshold && r < 10000) {
                                usleep(100);
                                sysinfo(&si);
                                free_b = (uint64_t)si.freeram * mu;
                                r++;
                            }
                        }
                    }
                }
                next_check += 16 * 1024 * 1024;
            }
        }
    } else {
        ssize_t n = splice(infd, NULL, outfd, NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
        if (n >= 0) {
            do {
                if (n > 0 && evfd_ingest_data >= 0) { uint64_t v=1; if(write(evfd_ingest_data, &v, 8)){}; }
                
                // Check OOM
                total_moved += n;
                if (total_moved > next_check) {
                    struct sysinfo si;
                    if (sysinfo(&si) == 0) {
                        uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                        uint64_t free_b = (uint64_t)si.freeram * mu;
                        if (free_b < oom_threshold) {
                            if (state && atomic_load_relaxed(&state->fallow_active)) {
                                int r = 0;
                                while (free_b < oom_threshold && r < 10000) {
                                    usleep(100);
                                    sysinfo(&si);
                                    free_b = (uint64_t)si.freeram * mu;
                                    r++;
                                }
                            }
                        }
                    }
                    next_check += 16 * 1024 * 1024;
                }
                
                n = splice(infd, NULL, outfd, NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
            } while (n > 0);
        } else if (errno == EINVAL) {
            int pipefd[2];
            if (pipe(pipefd) < 0) return EXECUTION_FAILURE;
            fcntl(pipefd[1], F_SETPIPE_SZ, 1048576); 
            while(1) {
                ssize_t n = splice(infd, NULL, pipefd[1], NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
                if (n <= 0) break;
                ssize_t m = splice(pipefd[0], NULL, outfd, NULL, n, SPLICE_F_MOVE|SPLICE_F_MORE);
                if (m <= 0) break;
                if (evfd_ingest_data >= 0) { uint64_t v=1; if(write(evfd_ingest_data, &v, 8)){}; }
                
                // Check OOM
                total_moved += n;
                if (total_moved > next_check) {
                    struct sysinfo si;
                    if (sysinfo(&si) == 0) {
                        uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                        uint64_t free_b = (uint64_t)si.freeram * mu;
                        if (free_b < oom_threshold) { 
                            if (state && atomic_load_relaxed(&state->fallow_active)) {
                                int r = 0;
                                while (free_b < oom_threshold && r < 10000) {
                                    usleep(100);
                                    sysinfo(&si);
                                    free_b = (uint64_t)si.freeram * mu;
                                    r++;
                                }
                            }
                        }
                    }
                    next_check += 16 * 1024 * 1024;
                }
            }
            close(pipefd[0]); close(pipefd[1]);
        }
    }
    return EXECUTION_SUCCESS;
}

static int evfd_signal_main(int argc, char **argv) {
    int fd = evfd_ingest_eof; 
    if (argc >= 2) fd = atoi(argv[1]);
    uint64_t val = 1;
    if(write(fd, &val, 8)){};
    return EXECUTION_SUCCESS;
}

// --- Fallow (Index-Aware + Dry Run Support) ---
static int ring_fallow_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    int fd_file = atoi(argv[2]);
    bool dry_run = (argc > 3 && strcmp(argv[3], "dry") == 0);
    
    if (state) atomic_store_release(&state->fallow_active, 1);

    struct Interval *head = NULL;
    uint64_t next_idx = 0; 
    
    struct IndexPacket ip;
    while (read(fd_in, &ip, sizeof(ip)) == sizeof(ip)) {
        if (ip.idx == next_idx) {
            next_idx += ip.cnt;
            while (head && head->s == next_idx) {
                struct Interval *tmp = head;
                next_idx = tmp->e;
                head = tmp->next;
                free(tmp);
            }
            if (state) atomic_store_release(&state->min_idx, next_idx);
            
            if (!dry_run) {
                uint64_t byte_limit = state->offset_ring[next_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
                off_t aligned = (off_t)((byte_limit / 4096) * 4096);
                if (aligned > 0) {
                    fallocate(fd_file, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, 0, aligned);
                }
            }
        } else if (ip.idx > next_idx) {
            struct Interval *n = xmalloc(sizeof(struct Interval));
            n->s = ip.idx;
            n->e = ip.idx + ip.cnt;
            struct Interval **curr = &head;
            while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
            n->next = *curr;
            *curr = n;
        }
    }
    return EXECUTION_SUCCESS;
}

static int ring_ingest_main(int argc, char **argv) { (void)argc; (void)argv; if (state) atomic_store_release(&state->ingest_complete, 1); return EXECUTION_SUCCESS; }
static int ring_worker_main(int argc, char **argv) {
    if (argc!=2) return EXECUTION_FAILURE;
    if (!strcmp(argv[1],"inc")) atomic_fetch_add(&state->active_workers,1);
    else if (!strcmp(argv[1],"dec")) {
        if (is_waiting_on_ring) { atomic_fetch_sub(&state->active_waiters, 1); is_waiting_on_ring = false; }
        atomic_fetch_sub(&state->active_workers, 1);
    }
    return EXECUTION_SUCCESS;
}
static char * lseek_doc[] = { "Usage: lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]", NULL };
static int lseek_main(int argc, char ** argv) { if (argc < 3 || argc > 5) return EXECUTION_FAILURE; int fd = atoi(argv[1]); off_t off = atoll(argv[2]); int whence = SEEK_CUR; if (argc > 3) { if (!strcmp(argv[3], "SEEK_SET")) whence = SEEK_SET; else if (!strcmp(argv[3], "SEEK_END")) whence = SEEK_END; } off_t no = lseek(fd, off, whence); if (no == -1) return EXECUTION_FAILURE; if (argc >= 4 && argv[argc-1][0]) { char buf[32]; snprintf(buf,32,"%lld",(long long)no); bind_variable(argv[argc-1], buf, 0); } else printf("%lld\n", (long long)no); return EXECUTION_SUCCESS; }

// --- BOILERPLATE MACRO ---
#define DEFINE_DISPATCHER(func_name, main_func) \
static int func_name(WORD_LIST *list) { \
    int argc; \
    char **argv = make_builtin_argv(list, &argc); \
    int ret = EXECUTION_FAILURE; \
    if (argv[0]) ret = main_func(argc, argv); \
    xfree(argv); \
    return ret; \
}

DEFINE_DISPATCHER(dispatch_ring_init,    ring_init_main)
DEFINE_DISPATCHER(dispatch_ring_destroy, ring_destroy_main)
DEFINE_DISPATCHER(dispatch_ring_scanner, ring_scanner_main)
DEFINE_DISPATCHER(dispatch_ring_claim,   ring_claim_main)
DEFINE_DISPATCHER(dispatch_ring_worker,  ring_worker_main)
DEFINE_DISPATCHER(dispatch_ring_ingest,  ring_ingest_main)
DEFINE_DISPATCHER(dispatch_ring_fallow,  ring_fallow_main)
DEFINE_DISPATCHER(dispatch_ring_ack,     ring_ack_main)
DEFINE_DISPATCHER(dispatch_ring_order,   ring_order_main)
DEFINE_DISPATCHER(dispatch_evfd_copy,    evfd_copy_main)
DEFINE_DISPATCHER(dispatch_evfd_signal,  evfd_signal_main)
DEFINE_DISPATCHER(dispatch_lseek,        lseek_main)

struct builtin ring_init_struct     = { "ring_init",    dispatch_ring_init,    BUILTIN_ENABLED, NULL, "ring_init", 0 };
struct builtin ring_destroy_struct  = { "ring_destroy", dispatch_ring_destroy, BUILTIN_ENABLED, NULL, "ring_destroy", 0 };
struct builtin ring_scanner_struct  = { "ring_scanner", dispatch_ring_scanner, BUILTIN_ENABLED, NULL, "ring_scanner <fd> [spawn_fd]", 0 };
struct builtin ring_claim_struct    = { "ring_claim",   dispatch_ring_claim,   BUILTIN_ENABLED, NULL, "ring_claim <OFF> <CNT> [FD]", 0 };
struct builtin ring_worker_struct   = { "ring_worker",  dispatch_ring_worker,  BUILTIN_ENABLED, NULL, "ring_worker [inc|dec]", 0 };
struct builtin ring_ingest_struct   = { "ring_ingest",  dispatch_ring_ingest,  BUILTIN_ENABLED, NULL, "ring_ingest", 0 };
struct builtin ring_fallow_struct   = { "ring_fallow",  dispatch_ring_fallow,  BUILTIN_ENABLED, NULL, "ring_fallow <PIPE> <FILE> [dry]", 0 };
struct builtin ring_ack_struct      = { "ring_ack",     dispatch_ring_ack,     BUILTIN_ENABLED, NULL, "ring_ack <FD>", 0 };
struct builtin ring_order_struct    = { "ring_order",   dispatch_ring_order,   BUILTIN_ENABLED, NULL, "ring_order <FD> <PFX>", 0 };
struct builtin evfd_copy_struct     = { "evfd_copy",    dispatch_evfd_copy,    BUILTIN_ENABLED, NULL, "evfd_copy <OUT> <IN>", 0 };
struct builtin evfd_signal_struct   = { "evfd_signal",  dispatch_evfd_signal,  BUILTIN_ENABLED, NULL, "evfd_signal <FD>", 0 };
struct builtin lseek_struct         = { "lseek",        dispatch_lseek,        BUILTIN_ENABLED, lseek_doc, "lseek <FD> <OFF>...", 0 };

int setup_builtin_forkrun_ring(void) {
    add_builtin(&ring_init_struct, 1);
    add_builtin(&ring_destroy_struct, 1);
    add_builtin(&ring_scanner_struct, 1);
    add_builtin(&ring_claim_struct, 1);
    add_builtin(&ring_worker_struct, 1);
    add_builtin(&ring_ingest_struct, 1);
    add_builtin(&ring_fallow_struct, 1);
    add_builtin(&ring_ack_struct, 1);
    add_builtin(&ring_order_struct, 1);
    add_builtin(&evfd_copy_struct, 1);
    add_builtin(&evfd_signal_struct, 1);
    add_builtin(&lseek_struct, 1);
    return 0;
}
