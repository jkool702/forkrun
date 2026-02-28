// forkrun_ring.c v6.68
// Architecture: Universal Ingest, Zero-Copy Ring, Escrow Stealing, Interval GC
// Features: Dynamic Scaling (PID+Ramp), Thread-Local Safety, Fast Quoting
// Status: GOLD MASTER

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
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
#include <time.h>

// --- Constants & Macros ---
#if defined(__x86_64__) || defined(__i386__)
  #define cpu_relax() __builtin_ia32_pause()
#else
  #define cpu_relax() __asm__ __volatile__("yield" ::: "memory")
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
static int ring_exec_main(int argc, char **argv);
static int ring_fallow_main(int argc, char **argv);
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
    char pad0[128];

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

// Thread Local Storage for Safety
static __thread bool is_waiting_on_ring = false;

struct EscrowPacket { uint64_t idx; uint64_t cnt; };
struct RangePacket  { uint64_t start; uint64_t end; };

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

// --- Init/Destroy ---
static int ring_init_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state != NULL) {
        atomic_store_relaxed(&state->read_idx, 0);
        atomic_store_relaxed(&state->write_idx, 0);
        atomic_store_relaxed(&state->ingest_complete, 0);
        atomic_store_relaxed(&state->total_lines_consumed, 0);
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
        uint64_t r = atomic_load_acquire(&state->read_idx); \
        if ((local_write_idx - r) < RING_SIZE) break; \
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

    uint64_t L = 1, Lmax = 65535, BytesMax = 0;
    uint64_t W = 1;
    char *tmp_var;

    if ((tmp_var = get_string_value("nLinesMax"))) Lmax = atol(tmp_var);
    if ((tmp_var = get_string_value("nBytesMax"))) BytesMax = atoll(tmp_var);

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
    uint64_t X_const = 1 + fast_log2(W2 + L2) * W2;
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

    uint64_t last_gc_idx = 0;

    atomic_store_relaxed(&state->write_idx, 0);
    atomic_store_relaxed(&state->read_idx, 0);
    atomic_store_relaxed(&state->signed_batch_size, (int64_t)L);
    atomic_store_relaxed(&state->active_workers, W);

    #define SCAN_BATCH(target_L) ({ \
        uint64_t lines_found = 0; \
        while (lines_found < (target_L)) { \
            if (p >= end) break; \
            char *nl = memchr(p, '\n', end - p); \
            if (nl) { \
                if (BytesMax > 0 && lines_found > 0) { \
                    uint64_t line_end_offset = buf_base_offset + (uint64_t)((nl + 1) - buf); \
                    uint64_t payload = line_end_offset - batch_start; \
                    uint64_t overhead = (lines_found + 1) * 8; \
                    if ((payload + overhead) > BytesMax) break; \
                } \
                lines_found++; \
                p = nl + 1; \
            } else { break; } \
        } \
        lines_found; \
    })

    while (status != 1) {
        // GC
        uint64_t r_curr = atomic_load_relaxed(&state->read_idx);
        if (r_curr > last_gc_idx + 2048) {
            uint64_t packed = state->offset_ring[r_curr & RING_MASK];
            uint64_t safe_off = (uint64_t)(packed & ~FLAG_PARTIAL_BATCH);
            if (safe_off > 0) {
                if(fallocate(fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, 0, (off_t)safe_off)){};
                last_gc_idx = r_curr;
            }
        }

        // Refill
        if (p >= end) {
            uint64_t curr_off = buf_base_offset + (p - buf);
            if (lseek(fd, (off_t)curr_off, SEEK_SET) < 0) {}
            ssize_t n = read(fd, buf, CHUNK);

            if (n > 0) {
                buf_base_offset = curr_off;
                p = buf; end = buf + n;
                status = 0;
            } else {
                struct pollfd pfds[2] = {
                    { .fd = evfd_ingest_data, .events = POLLIN },
                    { .fd = evfd_ingest_eof,  .events = POLLIN }
                };

                SCANNER_WAKE();
                int ret = poll(pfds, 2, 0);

                bool d_ready = (ret > 0 && (pfds[0].revents & POLLIN));
                bool e_sig   = (ret > 0 && (pfds[1].revents & POLLIN));

                if (d_ready) {
                    uint64_t v; if(read(evfd_ingest_data, &v, 8)){};
                    status = 2;
                } else if (e_sig) {
                    atomic_store_release(&state->ingest_complete, 1);
                    status = 1;
                } else {
                    if (atomic_load_acquire(&state->ingest_complete)) status = 1;
                    else {
                        int timeout = (phase == 0) ? 100 : 100;
                        ret = poll(pfds, 2, timeout);
                        if (ret > 0 && (pfds[0].revents & POLLIN)) {
                             uint64_t v; if(read(evfd_ingest_data, &v, 8)){}; status = 2;
                        } else if (ret > 0 && (pfds[1].revents & POLLIN)) {
                             status = 1; atomic_store_release(&state->ingest_complete, 1);
                        } else {
                             if (atomic_load_acquire(&state->ingest_complete)) status = 1;
                             else status = 2;
                        }
                    }
                }

                if (status == 2) {
                    if (p < end) break;
                    stall_counter += 10;
                    continue;
                }
                if (status == 1 && p >= end) break;
            }
        }

        uint64_t lines = SCAN_BATCH(L);

        if (lines == L || (status == 1 && lines > 0) || (status == 2 && lines > 0)) {
            SCANNER_FLUSH(lines);
            batch_start = buf_base_offset + (uint64_t)(p - buf);
            batch_counter++;

            target_count = W * 4;
            if (target_count < 4) target_count = 4;

            if (phase == 0) {
                if (batch_counter >= target_count) {
                    phase = 1;
                    batch_counter = 0;
                }
            }
            else if (phase == 1) {
                if (status == 2) {
                    phase = 2;
                }
                else if (batch_counter >= target_count) {
                    L *= 2;

                    if (W < W_max_val) {
                        uint64_t l_log = fast_log2(L);
                        uint64_t num = 4 * (W_max_val - W) * L2;
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

                    if (L >= Lmax) {
                        L = Lmax;
                        phase = 2;
                        if (W < W_max_val && fd_spawn >= 0) {
                            dprintf(fd_spawn, "%lu\n", W_max_val - W);
                            W = W_max_val;
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
                        uint64_t rate_per_worker = d_out / W;
                        if (rate_per_worker == 0) rate_per_worker = 1;
                        uint64_t w_ideal = d_in / rate_per_worker;
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

                    uint64_t l_target = (uint64_t)backlog / W;
                    if (l_target > Lmax) l_target = Lmax;
                    if (l_target < 1) l_target = 1;

                    bool update_l = false;

                    if (l_target > L) {
                        L = l_target;
                        update_l = true;
                    } else if (l_target < L) {
                        uint32_t waiters = atomic_load_relaxed(&state->active_waiters);
                        if (waiters > 0 && stall_counter > 5) {
                            L = (L + l_target) / 2;
                            if (L < 1) L = 1;
                            update_l = true;
                            stall_counter = 0;
                        }
                    }
                    if (update_l) {
                        atomic_store_release(&state->batch_change_idx, local_write_idx);
                        atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                    }
                }
            }
            if (lines < L) stall_counter++; else stall_counter = 0;
        } else {
            if (status == 1) break;
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
    if (fd_read >= 0 && final_lines > 0) lseek(fd_read, (off_t)final_offset, SEEK_SET);
    return 0;
}

// --- Exec (Fast Quoter Helper) ---
static WORD_DESC* make_quoted_wd(char *str) {
    size_t len = strlen(str);
    bool has_single = false;
    if (len == 0) {
        WORD_DESC *w = make_bare_word("''");
        w->flags |= W_QUOTED; return w;
    }
    for (size_t i=0; i<len; i++) { if (str[i] == '\'') { has_single = true; break; } }

    if (!has_single) {
        char *q = xmalloc(len + 3);
        q[0] = '\''; memcpy(q+1, str, len); q[len+1] = '\''; q[len+2] = '\0';
        WORD_DESC *w = make_bare_word(q); free(q);
        w->flags |= W_QUOTED; return w;
    } else {
        size_t cap = len + 16;
        char *q = xmalloc(cap);
        size_t idx = 0;
        q[idx++] = '\'';
        for (size_t i=0; i<len; i++) {
            if (idx + 4 >= cap) { cap *= 2; q = xrealloc(q, cap); }
            if (str[i] == '\'') {
                q[idx++] = '\''; q[idx++] = '\\'; q[idx++] = '\''; q[idx++] = '\'';
            } else {
                q[idx++] = str[i];
            }
        }
        q[idx++] = '\''; q[idx] = '\0';
        WORD_DESC *w = make_bare_word(q); free(q);
        w->flags |= W_QUOTED; return w;
    }
}

static int ring_exec_main(int argc, char **argv) {
    if (argc < 4) { builtin_error("ring_exec usage"); return EXECUTION_FAILURE; }
    int fd = atoi(argv[1]);
    uint64_t count = atoll(argv[2]);
    if (count == 0) return EXECUTION_SUCCESS;

    off_t start_pos = lseek(fd, 0, SEEK_CUR);

    int static_argc = argc - 3;
    WORD_LIST *head = NULL, *tail = NULL;
    for (int i = 0; i < static_argc; i++) {
        WORD_DESC *wd = make_bare_word(argv[3 + i]);
        WORD_LIST *wl = make_word_list(wd, NULL);
        if (!head) head = wl; else tail->next = wl;
        tail = wl;
    }

    size_t buf_size = 65536;
    char *buf = xmalloc(buf_size);
    ssize_t n_read;
    uint64_t lines_found = 0;
    char *partial = NULL;
    size_t partial_len = 0;

    while (lines_found < count) {
        n_read = read(fd, buf, buf_size);
        if (n_read < 0 && errno == EINTR) continue;
        if (n_read <= 0) break;
        char *p = buf, *end = buf + n_read, *line_start = p;
        while (p < end && lines_found < count) {
            char *nl = memchr(p, '\n', end - p);
            if (nl) {
                *nl = '\0';
                WORD_DESC *wd;
                if (partial) {
                    size_t frag_len = nl - line_start;
                    char *full = xmalloc(partial_len + frag_len + 1);
                    memcpy(full, partial, partial_len);
                    memcpy(full + partial_len, line_start, frag_len);
                    full[partial_len + frag_len] = '\0';
                    wd = make_quoted_wd(full);
                    free(full); free(partial); partial = NULL; partial_len = 0;
                } else {
                    wd = make_quoted_wd(line_start);
                }
                WORD_LIST *wl = make_word_list(wd, NULL);
                if (!head) head = wl; else tail->next = wl;
                tail = wl;
                lines_found++;
                line_start = nl + 1; p = nl + 1;
            } else p = end;
        }
        if (line_start < end && lines_found < count) {
            size_t len = end - line_start;
            if (partial) {
                partial = xrealloc(partial, partial_len + len);
                memcpy(partial + partial_len, line_start, len);
                partial_len += len;
            } else {
                partial = xmalloc(len);
                memcpy(partial, line_start, len);
                partial_len = len;
            }
        }
    }
    if (partial) {
        if (lines_found < count) {
            char *fin = xrealloc(partial, partial_len + 1); fin[partial_len] = '\0';
            WORD_DESC *wd = make_quoted_wd(fin); free(fin);
            WORD_LIST *wl = make_word_list(wd, NULL);
            if (!head) head = wl; else tail->next = wl;
        } else free(partial);
    }
    free(buf);

    if (!head) return EXECUTION_SUCCESS;
    COMMAND *cmd = xmalloc(sizeof(COMMAND)); memset(cmd, 0, sizeof(COMMAND));
    cmd->type = cm_simple;
    SIMPLE_COM *sc = xmalloc(sizeof(SIMPLE_COM)); memset(sc, 0, sizeof(SIMPLE_COM));
    sc->words = head;
    cmd->value.Simple = sc;
    int result = execute_command(cmd);
    dispose_command(cmd);

    const char *s_fd = get_string_value("FD_RING_FALLOC");
    if (s_fd) {
        int fd_f = atoi(s_fd);
        off_t end_pos = lseek(fd, 0, SEEK_CUR);
        if (fd_f > 0 && end_pos > start_pos) {
            struct RangePacket rp = { .start = (uint64_t)start_pos, .end = (uint64_t)end_pos };
            if(write(fd_f, &rp, sizeof(rp))){};
        }
    }
    return result;
}

// --- Evfd Copy/Signal ---
static int evfd_copy_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int outfd = atoi(argv[1]);
    int infd  = (argc == 3) ? atoi(argv[2]) : 0;
    size_t chunk = HUGE_PAGE_SIZE;
    struct stat st;
    if (fstat(infd, &st) == 0 && S_ISREG(st.st_mode)) {
        off_t off = 0;
        while(1) {
            ssize_t n = sendfile(outfd, infd, &off, chunk);
            if (n <= 0) break;
            if (evfd_ingest_data >= 0) { uint64_t v=1; if(write(evfd_ingest_data, &v, 8)){}; }
        }
    } else {
        ssize_t n = splice(infd, NULL, outfd, NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
        if (n >= 0) {
            do {
                if (n > 0 && evfd_ingest_data >= 0) { uint64_t v=1; if(write(evfd_ingest_data, &v, 8)){}; }
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

// --- Fallow ---
struct Interval { uint64_t s; uint64_t e; struct Interval *next; };
static int ring_fallow_main(int argc, char **argv) {
    if (argc != 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    int fd_file = atoi(argv[2]);
    struct Interval *head = NULL;
    uint64_t limit = 0;
    struct RangePacket rp;
    while (read(fd_in, &rp, sizeof(rp)) == sizeof(rp)) {
        if (rp.start == limit) {
            limit = rp.end;
            while (head && head->s == limit) {
                struct Interval *tmp = head; limit = tmp->e; head = tmp->next; free(tmp);
            }
            off_t aligned = (off_t)((limit / 4096) * 4096);
            if (aligned > 0) if(fallocate(fd_file, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, 0, aligned)){};
        } else if (rp.start > limit) {
            struct Interval *n = xmalloc(sizeof(struct Interval));
            n->s = rp.start; n->e = rp.end;
            struct Interval **curr = &head;
            while (*curr && (*curr)->s < rp.start) curr = &((*curr)->next);
            n->next = *curr; *curr = n;
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

static int forkrun_ring_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int ret = EXECUTION_FAILURE;
    if (!argv[0]) return ret;
    if (!strcmp(argv[0], "ring_init")) ret = ring_init_main(argc, argv);
    else if (!strcmp(argv[0], "ring_destroy")) ret = ring_destroy_main(argc, argv);
    else if (!strcmp(argv[0], "ring_scanner")) ret = ring_scanner_main(argc, argv);
    else if (!strcmp(argv[0], "ring_claim")) ret = ring_claim_main(argc, argv);
    else if (!strcmp(argv[0], "ring_worker")) ret = ring_worker_main(argc, argv);
    else if (!strcmp(argv[0], "ring_ingest")) ret = ring_ingest_main(argc, argv);
    else if (!strcmp(argv[0], "ring_exec")) ret = ring_exec_main(argc, argv);
    else if (!strcmp(argv[0], "ring_fallow")) ret = ring_fallow_main(argc, argv);
    else if (!strcmp(argv[0], "evfd_copy")) ret = evfd_copy_main(argc, argv);
    else if (!strcmp(argv[0], "evfd_signal")) ret = evfd_signal_main(argc, argv);
    else if (!strcmp(argv[0], "lseek")) ret = lseek_main(argc, argv);
    xfree(argv);
    return ret;
}

struct builtin ring_init_struct     = { "ring_init",    forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_init", 0 };
struct builtin ring_destroy_struct  = { "ring_destroy", forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_destroy", 0 };
struct builtin ring_scanner_struct  = { "ring_scanner", forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_scanner <fd> [spawn_fd]", 0 };
struct builtin ring_claim_struct    = { "ring_claim",   forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_claim <OFF> <CNT> [FD]", 0 };
struct builtin ring_worker_struct   = { "ring_worker",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_worker [inc|dec]", 0 };
struct builtin ring_ingest_struct   = { "ring_ingest",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_ingest", 0 };
struct builtin ring_exec_struct     = { "ring_exec",    forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_exec <FD> <CNT> <CMD>...", 0 };
struct builtin ring_fallow_struct   = { "ring_fallow",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_fallow <PIPE> <FILE>", 0 };
struct builtin evfd_copy_struct     = { "evfd_copy",    forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "evfd_copy <OUT> <IN>", 0 };
struct builtin evfd_signal_struct   = { "evfd_signal",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "evfd_signal <FD>", 0 };
struct builtin lseek_struct         = { "lseek",        forkrun_ring_builtin, BUILTIN_ENABLED, lseek_doc, "lseek <FD> <OFF>...", 0 };

int setup_builtin_forkrun_ring(void) {
    add_builtin(&ring_init_struct, 1); add_builtin(&ring_destroy_struct, 1);
    add_builtin(&ring_scanner_struct, 1); add_builtin(&ring_claim_struct, 1);
    add_builtin(&ring_worker_struct, 1); add_builtin(&ring_ingest_struct, 1);
    add_builtin(&ring_exec_struct, 1); add_builtin(&ring_fallow_struct, 1);
    add_builtin(&evfd_copy_struct, 1); add_builtin(&evfd_signal_struct, 1);
    add_builtin(&lseek_struct, 1);
    return 0;
}
