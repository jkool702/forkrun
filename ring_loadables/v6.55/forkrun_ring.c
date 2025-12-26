// forkrun_ring.c
// Forkrun v6.55 Ring Buffer Architecture
// Features: Escrow Work-Stealing, Cache-Aligned State, Unified Wait Logic
// Optimization: Raw Buffered I/O for Exec, No-Rollback
// Author: jkool702 / Refactored by AI

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

#ifdef _GNU_SOURCE
#undef _GNU_SOURCE
#endif

// --- Architecture Specific Pause Logic ---
#if defined(__x86_64__) || defined(__i386__)
  #define cpu_relax() __builtin_ia32_pause()
#elif defined(__aarch64__)
  #define cpu_relax() __asm__ __volatile__("yield" ::: "memory")
#elif defined(__arm__)
  #define cpu_relax() __asm__ __volatile__("yield" ::: "memory")
#elif defined(__riscv)
  #define cpu_relax() __asm__ __volatile__("pause" ::: "memory")
#else
  #define cpu_relax() __asm__ __volatile__("or 27,27,27" ::: "memory")
#endif

// GCC Built-ins
#define atomic_load_acquire(ptr)       __atomic_load_n(ptr, __ATOMIC_ACQUIRE)
#define atomic_load_relaxed(ptr)       __atomic_load_n(ptr, __ATOMIC_RELAXED)
#define atomic_store_release(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELEASE)
#define atomic_store_relaxed(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELAXED)
#define atomic_fetch_add(ptr, val)     __atomic_fetch_add(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_fetch_sub(ptr, val)     __atomic_fetch_sub(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_exchange(ptr, val)      __atomic_exchange_n(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_compare_exchange(ptr, exp, des) __atomic_compare_exchange_n(ptr, exp, des, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)
#define atomic_thread_fence_release()  __atomic_thread_fence(__ATOMIC_RELEASE)

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"
#include "variables.h"

// External Bash functions
extern void dispose_command(COMMAND *);
extern int execute_command(COMMAND *); 
extern int add_builtin(struct builtin *bp, int keep);

static int forkrun_ring_builtin(WORD_LIST *list);
static int ring_init_main(int argc, char **argv);
static int ring_destroy_main(int argc, char **argv);
static int ring_scanner_main(int argc, char **argv);
static int ring_claim_main(int argc, char **argv);
static int ring_worker_main(int argc, char **argv);
static int ring_ingest_main(int argc, char **argv);
static int ring_exec_main(int argc, char **argv);
static int lseek_main(int argc, char ** argv);

// ==============================================================
// ========================= SHARED STATE =======================
// ==============================================================

#define RING_SIZE_LOG2   20
#define RING_SIZE        (1ULL << RING_SIZE_LOG2)
#define RING_MASK        (RING_SIZE - 1)
#define CACHE_LINE_SIZE 256
#define ALIGNED(x) __attribute__((aligned(x > CACHE_LINE_SIZE ? x : CACHE_LINE_SIZE)))

// Padding to prevent False Sharing between Read (Workers) and Write (Scanner)
struct SharedState {
    // --- WORKER HOT CACHE LINE ---
    uint64_t read_idx ALIGNED(CACHE_LINE_SIZE);
    uint64_t active_workers;
    uint64_t total_lines_consumed;
    uint32_t active_waiters; 
    char pad0[128]; // Explicit padding

    // --- SCANNER HOT CACHE LINE ---
    uint64_t write_idx ALIGNED(CACHE_LINE_SIZE);
    int64_t  signed_batch_size; 
    uint64_t batch_change_idx;  
    uint8_t  ingest_complete;
    char pad1[128]; // Explicit padding

    // --- DATA RINGS ---
    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    int64_t offset_ring[RING_SIZE] ALIGNED(4096);
};

static struct SharedState *state = NULL;
static int evfd_data = -1;
static int evfd_eof  = -1;
static int fd_escrow[2] = { -1, -1 }; // [0]=Read, [1]=Write

struct EscrowPacket {
    uint64_t idx;
    uint64_t cnt;
};

static inline void u64toa(uint64_t value, char* buffer) {
    char temp[24];
    char *p = temp;
    if (value == 0) {
        *buffer++ = '0';
        *buffer = '\0';
        return;
    }
    do {
        *p++ = (char)(value % 10) + '0';
        value /= 10;
    } while (value > 0);
    int i = 0;
    while (p > temp) {
        buffer[i++] = *--p;
    }
    buffer[i] = '\0';
}

static int ring_init_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state != NULL) {
        // Soft reset
        atomic_store_relaxed(&state->read_idx, 0);
        atomic_store_relaxed(&state->write_idx, 0);
        atomic_store_relaxed(&state->signed_batch_size, 0);
        atomic_store_relaxed(&state->active_workers, 0);
        atomic_store_relaxed(&state->total_lines_consumed, 0);
        atomic_store_relaxed(&state->active_waiters, 0);
        atomic_store_relaxed(&state->batch_change_idx, 0);
        atomic_store_relaxed(&state->ingest_complete, 0);
        
        // Flush escrow
        if (fd_escrow[0] >= 0) {
            char dump[1024];
            while(read(fd_escrow[0], dump, sizeof(dump)) > 0) {}
        }
        return EXECUTION_SUCCESS;
    }

    size_t total_size = sizeof(struct SharedState);
    total_size = (total_size + 4095ULL) & ~4095ULL;

    void *p = mmap(NULL, total_size, PROT_READ | PROT_WRITE,
                   MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        builtin_error("ring_init: mmap failed: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }

    state = (struct SharedState *)p;
    memset(p, 0, total_size);

    evfd_data = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_eof  = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    
    // Create Escrow Pipe
    if (pipe(fd_escrow) < 0) {
        builtin_error("ring_init: pipe failed");
        return EXECUTION_FAILURE;
    }
    // Set nonblock/cloexec
    fcntl(fd_escrow[0], F_SETFL, O_NONBLOCK);
    fcntl(fd_escrow[1], F_SETFL, O_NONBLOCK);
    fcntl(fd_escrow[0], F_SETFD, FD_CLOEXEC);
    fcntl(fd_escrow[1], F_SETFD, FD_CLOEXEC);

    if (evfd_data < 0 || evfd_eof < 0) {
        builtin_error("ring_init: eventfd failed");
        return EXECUTION_FAILURE;
    }

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", evfd_data);
    bind_variable("EVFD_RING_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_eof);
    bind_variable("EVFD_RING_EOF", buf, 0);

    return EXECUTION_SUCCESS;
}

static int ring_destroy_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state) {
        size_t total_size = sizeof(struct SharedState);
        total_size = (total_size + 4095ULL) & ~4095ULL;
        munmap(state, total_size);
        state = NULL;
    }
    if (evfd_data >= 0) { close(evfd_data); evfd_data = -1; }
    if (evfd_eof >= 0)  { close(evfd_eof);  evfd_eof = -1; }
    if (fd_escrow[0] >= 0) { close(fd_escrow[0]); fd_escrow[0] = -1; }
    if (fd_escrow[1] >= 0) { close(fd_escrow[1]); fd_escrow[1] = -1; }
    
    unbind_variable("EVFD_RING_DATA");
    unbind_variable("EVFD_RING_EOF");
    return EXECUTION_SUCCESS;
}

#define SCANNER_WAKE_WORKERS() do { \
    if (atomic_load_relaxed(&state->active_waiters) > 0) { \
        uint64_t one = 1; \
        write(evfd_data, &one, sizeof(one)); \
    } \
} while(0)

#define SCANNER_SAFETY_PULSE() SCANNER_WAKE_WORKERS()

#define SCANNER_FLUSH(cnt) do { \
    if (batch_start & 0xFFFF000000000000ULL) { \
         builtin_error("ring_scanner: offset > 256TB"); \
         xfree(buf); return EXECUTION_FAILURE; \
    } \
    while (1) { \
        uint64_t r = atomic_load_acquire(&state->read_idx); \
        int64_t used = (int64_t)local_write_idx - (int64_t)r; \
        if (used < 0) used = 0; \
        if ((uint64_t)used < RING_SIZE) break; \
        SCANNER_WAKE_WORKERS(); \
        usleep(100); \
    } \
    int64_t packed = (int64_t)batch_start; \
    if (cnt != L) packed |= (int64_t)(1ULL << 63); \
    state->offset_ring[local_write_idx & RING_MASK] = packed; \
    state->stride_ring[local_write_idx & RING_MASK] = (uint16_t)(cnt); \
    local_write_idx++; \
    atomic_store_release(&state->write_idx, local_write_idx); \
    SCANNER_WAKE_WORKERS(); \
    if ((local_write_idx & 63) == 0) SCANNER_SAFETY_PULSE(); \
} while(0)

static int ring_scanner_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    int fd_spawn = -1;
    if (argc >= 3) fd_spawn = atoi(argv[2]);

    long nWorkersMax = sysconf(_SC_NPROCESSORS_ONLN); 
    if (nWorkersMax < 1) nWorkersMax = 1;

    struct stat st;
    bool is_regular = (fstat(fd, &st) == 0 && S_ISREG(st.st_mode));

    // --- State Setup ---
    uint64_t L = 1;          
    uint64_t Lmax = 65535;   
    
    char *tmp_var;
    if ((tmp_var = get_string_value("nLinesMax"))) {
        long user_lmax = atol(tmp_var);
        if (user_lmax > 0 && user_lmax < 65535) Lmax = (uint64_t)user_lmax;
    }

    uint64_t BytesMax = 0;
    if ((tmp_var = get_string_value("nBytesMax"))) {
        if (strcmp(tmp_var, "ARG_MAX") == 0) {
            long sys_arg_max = sysconf(_SC_ARG_MAX);
            if (sys_arg_max > 0) {
                size_t env_len = 0;
                extern char **environ;
                for (char **ep = environ; *ep; ++ep) {
                    env_len += strlen(*ep) + 1;
                }
                if ((long)env_len < sys_arg_max) {
                    BytesMax = (uint64_t)((sys_arg_max - (long)env_len) * 15 / 16);
                }
            }
        } else {
            long long user_bmax = atoll(tmp_var);
            if (user_bmax > 0) BytesMax = (uint64_t)user_bmax;
        }
    }

    uint64_t W = 1;          
    uint64_t Ns = 0;         
    uint64_t local_write_idx = 0;

    atomic_store_relaxed(&state->write_idx, 0);
    atomic_store_relaxed(&state->read_idx, 0);
    atomic_store_relaxed(&state->signed_batch_size, (int64_t)L);
    atomic_store_relaxed(&state->active_workers, 0); 
    atomic_store_relaxed(&state->batch_change_idx, 0);
    atomic_store_relaxed(&state->total_lines_consumed, 0);
    atomic_store_relaxed(&state->active_waiters, 0);

    const size_t CHUNK = 1024 * 1024 * 4; 
    char *buf = xmalloc(CHUNK);
    char *p = buf;
    char *end = buf;
    
    uint64_t buf_base_offset = (uint64_t)lseek(fd, 0, SEEK_CUR);
    uint64_t batch_start = buf_base_offset;

    #define STATUS_OK 0
    #define STATUS_EOF 1
    #define STATUS_STALL 2

    int refill_status = STATUS_OK;
    
    #define REFILL_BUFFER() ({ \
        refill_status = STATUS_OK; \
        uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf); \
        if (lseek(fd, (off_t)current_p_offset, SEEK_SET) < 0) { \
             if (errno != ESPIPE) { } \
        } \
        ssize_t n = read(fd, buf, CHUNK); \
        if (n > 0) { \
            buf_base_offset = current_p_offset; \
            p = buf; \
            end = buf + n; \
        } else if (n < 0) { \
            if (errno == EINTR) { /* retry */ } \
            else refill_status = STATUS_EOF; \
        } else { \
            if (is_regular || atomic_load_acquire(&state->ingest_complete)) { \
                refill_status = STATUS_EOF; \
            } else { \
                refill_status = STATUS_STALL; \
            } \
        } \
        refill_status; \
    })

    #define SCAN_BATCH(target_L) ({ \
        uint64_t lines_found = 0; \
        while (lines_found < (target_L)) { \
            if (p >= end) { \
                 int status = REFILL_BUFFER(); \
                 if (status == STATUS_STALL) break; \
                 if (status == STATUS_EOF && p >= end) break; \
            } \
            char *nl = memchr(p, '\n', end - p); \
            if (nl) { \
                if (BytesMax > 0 && lines_found > 0) { \
                    uint64_t line_end_offset = buf_base_offset + (uint64_t)((nl + 1) - buf); \
                    uint64_t payload = line_end_offset - batch_start; \
                    uint64_t overhead = (lines_found + 1) * 8; \
                    if ((payload + overhead) > BytesMax) break; \
                } \
                lines_found++; \
                Ns++; \
                p = nl + 1; \
            } else { \
                if (refill_status == STATUS_EOF) { \
                    if (p < end) { lines_found++; Ns++; p = end; } \
                    break; \
                } \
                int status = REFILL_BUFFER(); \
                if (status == STATUS_STALL) break; \
            } \
        } \
        lines_found; \
    })

    // Phase 1: Geometric Ramp-up
    int startup_retries = 0;
    while (L < Lmax) {
        for (uint64_t G = 0; G < (uint64_t)nWorkersMax; G++) {
             uint64_t cnt = SCAN_BATCH(L);
             if (cnt > 0) {
                 SCANNER_FLUSH(cnt);
                 batch_start = buf_base_offset + (uint64_t)(p - buf);
                 startup_retries = 0; 
             }
             
             if (refill_status == STATUS_EOF) goto finish_phase_1;
             
             if (refill_status == STATUS_STALL) {
                 SCANNER_WAKE_WORKERS();
                 if (cnt == 0 && startup_retries < 20) {
                     usleep(500);
                     startup_retries++;
                     G--;
                     continue;
                 }
                 if (cnt > 0 && cnt >= (L >> 2)) continue; 
                 goto finish_phase_1; 
             }
        }
        L *= 2;
        if (L >= Lmax) { L = Lmax; break; }
    }
    finish_phase_1:

    atomic_store_release(&state->batch_change_idx, local_write_idx);
    atomic_store_release(&state->signed_batch_size, -(int64_t)L);

    uint64_t saturation_point = 2048;
    if (saturation_point > Lmax) saturation_point = Lmax;
    uint64_t target_W = 1 + ((L * ((uint64_t)nWorkersMax - 1)) / saturation_point);
    
    uint64_t w_backlog = (Ns > 0) ? (1 + (Ns / 16)) : 1;
    if (w_backlog > target_W) target_W = w_backlog;
    if (target_W > (uint64_t)nWorkersMax) target_W = nWorkersMax;
    
    if (fd_spawn >= 0 && target_W > W) {
        dprintf(fd_spawn, "%lu\n", target_W - W);
        W = target_W;
        atomic_store_relaxed(&state->active_workers, W);
    }

    uint16_t stall_meter = 0; 
    uint64_t last_Ns = Ns;
    uint64_t last_Nw = atomic_load_relaxed(&state->total_lines_consumed);

    while (refill_status != STATUS_EOF) {
        uint64_t G0 = W; 
        if (G0 < 1) G0 = 1;

        for (uint64_t G = 0; G < G0; G++) {
            uint64_t cnt = SCAN_BATCH(L);
            if (cnt > 0) {
                SCANNER_FLUSH(cnt);
                batch_start = buf_base_offset + (uint64_t)(p - buf);
            }
            
            if (cnt < L) stall_meter = (stall_meter + 31) >> 1;
            else stall_meter >>= 1;

            if (refill_status == STATUS_EOF) goto finish_phase_2;
            
            if (refill_status == STATUS_STALL) {
                 SCANNER_WAKE_WORKERS();
                 usleep(500); 
                 if (cnt == 0) G--; 
            }
        }

        uint64_t curr_Nw = atomic_load_relaxed(&state->total_lines_consumed);
        uint64_t backlog = (Ns > curr_Nw) ? (Ns - curr_Nw) : 0;
        
        uint64_t L_target = (W > 0) ? (backlog / W) : backlog;
        if (L_target > Lmax) L_target = Lmax;
        if (L_target < 1) L_target = 1;
        
        bool update_L = false;
        if (L_target > L) {
            L = L_target; 
            update_L = true;
        } else if (L_target < L && stall_meter >= 29) {
            L = (L + L_target) / 2;
            update_L = true;
        }
        
        if (update_L) {
            atomic_store_release(&state->batch_change_idx, local_write_idx);
            atomic_store_release(&state->signed_batch_size, -(int64_t)L);
        }

        uint64_t dNs = Ns - last_Ns;
        uint64_t dNw = curr_Nw - last_Nw;
        uint64_t W_calc = W;

        if (dNw > 0) {
            W_calc = (W * dNs) / dNw;
        } else if (dNs > 0) {
            W_calc = W * 2;
        }
        
        uint64_t W_new = (W + W_calc) / 2;
        if (W_new > (uint64_t)nWorkersMax) W_new = nWorkersMax;
        if (W_new < 1) W_new = 1;

        if (W_new > W && fd_spawn >= 0) {
             dprintf(fd_spawn, "%lu\n", W_new - W);
             W = W_new;
             atomic_store_relaxed(&state->active_workers, W);
        }
        
        last_Ns = Ns;
        last_Nw = curr_Nw;
    }
    finish_phase_2:

    uint64_t final_sentinel_offset = buf_base_offset + (uint64_t)(p - buf);
    state->offset_ring[local_write_idx & RING_MASK] = (int64_t)final_sentinel_offset | (int64_t)(1ULL << 63);
    state->stride_ring[local_write_idx & RING_MASK] = 0;
    local_write_idx++;
    atomic_store_release(&state->write_idx, local_write_idx);

    SCANNER_WAKE_WORKERS();
    SCANNER_SAFETY_PULSE(); 
    if (fd_spawn >= 0) {
        if (write(fd_spawn, "x\n", 2) < 0) { /* ignore */ }
    }

    uint64_t wakes = atomic_load_relaxed(&state->active_workers) + 
                     atomic_load_relaxed(&state->active_waiters) + 128;
    write(evfd_eof, &wakes, sizeof(wakes));
    
    xfree(buf);
    return EXECUTION_SUCCESS;
}

static int ring_claim_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    const char *var_offset = argv[1];
    const char *var_count  = argv[2];
    int fd_read = (argc == 4) ? atoi(argv[3]) : -1;

    uint64_t my_read_idx;
    uint64_t claim_count = 1;
    int spin_count = 0;

    // ==========================================================
    // STEP 1: ACQUIRE A RESERVATION (TICKET)
    // ==========================================================
    while (1) {
        // Priority 1: Check Escrow Pipe for stolen work
        struct EscrowPacket ep;
        // Non-blocking read. If empty, returns -1 (EAGAIN)
        if (fd_escrow[0] >= 0 && read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
            my_read_idx = ep.idx;
            claim_count = ep.cnt;
            // Proceed to Step 2 (Verification)
            break; 
        }

        // Priority 2: Check Global Ring
        uint64_t w_snap = atomic_load_acquire(&state->write_idx);
        uint64_t r_curr = atomic_load_relaxed(&state->read_idx);

        if (r_curr >= w_snap) {
            // RING EMPTY OR CONTENTION -> WAIT STATE
            
            if (spin_count < 100) { 
                cpu_relax();
                spin_count++;
                continue;
            }

            atomic_fetch_add(&state->active_waiters, 1);
            
            struct pollfd pfds[3] = { 
                { .fd = evfd_data, .events = POLLIN }, 
                { .fd = evfd_eof,  .events = POLLIN },
                { .fd = fd_escrow[0], .events = POLLIN }
            };

            while (1) {
                // Wait for signal
                int ret = poll(pfds, 3, -1); // Indefinite wait

                if (ret < 0) { if (errno == EINTR) continue; break; }

                // Check Escrow (Higher Priority)
                if (pfds[2].revents & POLLIN) {
                    if (read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
                        my_read_idx = ep.idx;
                        claim_count = ep.cnt;
                        atomic_fetch_sub(&state->active_waiters, 1);
                        goto verify_claim; // JUMP OUT
                    }
                }

                // Check Data Signal
                if (pfds[0].revents & POLLIN) {
                    uint64_t v; 
                    read(evfd_data, &v, sizeof(v)); // Clear signal
                    // Loop back to try atomic claim or escrow again
                    break;
                }

                // Check EOF
                if (pfds[1].revents & POLLIN) {
                    // One last check: is there data?
                    if (atomic_load_acquire(&state->write_idx) <= atomic_load_relaxed(&state->read_idx)) {
                         // Double check escrow before dying
                         if (read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
                             my_read_idx = ep.idx;
                             claim_count = ep.cnt;
                             atomic_fetch_sub(&state->active_waiters, 1);
                             goto verify_claim;
                         }
                         atomic_fetch_sub(&state->active_waiters, 1);
                         bind_variable(var_count, "0", 0); 
                         return 1; // CLEAN EXIT
                    }
                    break; 
                }
            }
            atomic_fetch_sub(&state->active_waiters, 1);
            spin_count = 0;
            continue; // Retry loop
        }

        // --- CALCULATE BATCH SIZE (Ticket Lock Logic) ---
        int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size); 
        claim_count = 1;

        if (sbatch < 0) {
            // Adaptive mode
            uint64_t L_target = (uint64_t)(-sbatch);
            uint64_t Ib = atomic_load_acquire(&state->batch_change_idx);
            
            // If we are past the change point, use new size
            // Note: Simplification here, we don't strictly enforce mixed batches within a claim
            
            uint16_t L0 = state->stride_ring[r_curr & RING_MASK];
            if (L0 == 0) L0 = 1;
            uint64_t Wmax = atomic_load_relaxed(&state->active_workers); 
            if (Wmax == 0) Wmax = 1;
            uint64_t B = L_target / L0;
            if (B > Wmax) B = Wmax;
            if (B < 1) B = 1;
            claim_count = B;
        }

        // Clamp to available (Prevent standard overshoot if data exists)
        if (r_curr + claim_count > w_snap) {
            claim_count = w_snap - r_curr;
        }
        if (claim_count < 1) claim_count = 1; 

        // Atomic Claim
        my_read_idx = atomic_fetch_add(&state->read_idx, claim_count);

        // Check if we raced and the batch changed size retroactively? 
        // (Minor edge case logic from v6.53 preserved)
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
    // ==========================================================
    // STEP 2: VERIFY DATA AVAILABILITY & OVERSHOOT HANDLING
    // ==========================================================
    // We possess 'my_read_idx' with length 'claim_count'. 
    // This is ours. No one else can take it.
    // However, the Scanner may not have written it yet.

    uint64_t w_fresh = atomic_load_acquire(&state->write_idx);
        
    if (my_read_idx + claim_count > w_fresh) {
         // OVERSHOOT DETECTED
         atomic_fetch_add(&state->active_waiters, 1);
         
         while (1) {
             uint64_t w_curr = atomic_load_acquire(&state->write_idx);

             // A: SOME DATA IS READY (Work Stealing Opportunity)
             if (w_curr > my_read_idx) {
                 uint64_t avail = w_curr - my_read_idx;
                 
                 // If we have LESS than we claimed
                 if (avail < claim_count) {
                     uint64_t remain = claim_count - avail;
                     
                     // 1. Escrow the remainder
                     struct EscrowPacket ep;
                     ep.idx = my_read_idx + avail;
                     ep.cnt = remain;
                     write(fd_escrow[1], &ep, sizeof(ep));
                     
                     // 2. Adjust our local claim
                     claim_count = avail;

                     // 3. Wake others (Pipe is readable, but pulse evfd for good measure)
                     uint64_t one = 1;
                     write(evfd_data, &one, sizeof(one));
                 }
                 // If avail >= claim_count, we are good.
                 break; // Proceed to processing
             }

             // B: NO DATA READY (Wait)
             struct pollfd pfds[2] = { 
                { .fd = evfd_data, .events = POLLIN }, 
                { .fd = evfd_eof,  .events = POLLIN } 
             };
             
             int ret = poll(pfds, 2, -1);
             
             if (ret > 0 && (pfds[0].revents & POLLIN)) {
                 uint64_t v; read(evfd_data, &v, sizeof(v));
                 // Loop back and check w_curr
             }

             if (pfds[1].revents & POLLIN) {
                  // EOF Handling
                  uint64_t w_final = atomic_load_acquire(&state->write_idx);
                  if (w_final <= my_read_idx) {
                      // Phantom claim (Scanner died before filling our reservation)
                      atomic_fetch_sub(&state->active_waiters, 1);
                      bind_variable(var_count, "0", 0);
                      return 1;
                  }
                  if (w_final < my_read_idx + claim_count) {
                      claim_count = w_final - my_read_idx;
                  }
                  break; 
             }
         }
         atomic_fetch_sub(&state->active_waiters, 1);
    }

    // ==========================================================
    // STEP 3: PROCESS BATCH
    // ==========================================================
    uint64_t final_lines = 0;
    uint64_t final_offset = 0;

    int64_t packed_val = state->offset_ring[my_read_idx & RING_MASK];
    final_offset = (uint64_t)(packed_val & ~(1ULL << 63));

    // Calculate line count
    if (claim_count == 1) {
        int64_t sbatch_now = atomic_load_relaxed(&state->signed_batch_size);
        if (sbatch_now > 0 && packed_val >= 0) {
            final_lines = (uint64_t)sbatch_now;
        } else {
            final_lines = state->stride_ring[my_read_idx & RING_MASK];
        }
    } else {
        for (uint64_t i = 0; i < claim_count; i++) {
             final_lines += state->stride_ring[(my_read_idx + i) & RING_MASK];
        }
    }

    atomic_fetch_add(&state->total_lines_consumed, final_lines);

    char buf[64];
    u64toa(final_offset, buf);
    bind_variable(var_offset, buf, 0);
    u64toa(final_lines, buf);
    bind_variable(var_count, buf, 0);

    if (fd_read >= 0 && final_lines > 0) {
        lseek(fd_read, (off_t)final_offset, SEEK_SET);
    }
    return 0;
}

static int ring_worker_main(int argc, char **argv) {
    if (argc != 2) return EXECUTION_FAILURE;
    if (strcmp(argv[1], "inc") == 0) {
        atomic_fetch_add(&state->active_workers, 1);
    } else if (strcmp(argv[1], "dec") == 0) {
        atomic_fetch_sub(&state->active_workers, 1);
    } else {
        return EXECUTION_FAILURE;
    }
    return EXECUTION_SUCCESS;
}

static int ring_ingest_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state) atomic_store_release(&state->ingest_complete, 1);
    return EXECUTION_SUCCESS;
}

static char * lseek_doc[] = { "Usage: lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]", NULL };

static int lseek_main(int argc, char ** argv) {
    if (argc < 3 || argc > 5) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    if (fd < 0) return EXECUTION_FAILURE;
    off_t offset = atoll(argv[2]);
    int whence = SEEK_CUR;
    char * varname = NULL;
    int quiet = 0;

    if (argc > 3) {
        if (strcmp(argv[3], "SEEK_SET") == 0) whence = SEEK_SET;
        else if (strcmp(argv[3], "SEEK_END") == 0) whence = SEEK_END;
        else if (argv[3][0] != '\0') varname = argv[3];
        if (argc == 5) {
            if (argv[4][0] == '\0') quiet = 1;
            else varname = argv[4];
        }
    }
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t)-1) return EXECUTION_FAILURE;
    if (varname) {
        char buf[32];
        snprintf(buf, sizeof(buf), "%lld", (long long)new_offset);
        bind_variable(varname, buf, 0);
    } else if (!quiet) {
        printf("%lld\n", (long long)new_offset);
    }
    return EXECUTION_SUCCESS;
}

// Optimized ring_exec: Raw buffering, no stdio, no rollback
static int ring_exec_main(int argc, char **argv) {
    if (argc < 4) {
        builtin_error("ring_exec: usage: ring_exec <FD> <COUNT> <COMMAND> [args...]");
        return EXECUTION_FAILURE;
    }

    int fd = atoi(argv[1]);
    uint64_t count = (uint64_t)atoll(argv[2]);

    if (count == 0) return EXECUTION_SUCCESS;

    // --- 1. Setup Static Args (Command + Initial Args) ---
    int static_argc = argc - 3;
    
    WORD_LIST *head = NULL;
    WORD_LIST *tail = NULL;

    // Add Command and Static Args to WORD_LIST
    for (int i = 0; i < static_argc; i++) {
        WORD_DESC *wd = make_bare_word(argv[3 + i]);
        WORD_LIST *wl = make_word_list(wd, NULL);
        if (!head) head = wl;
        else tail->next = wl;
        tail = wl;
    }

    // --- 2. Buffered Read & Parse ---
    size_t buf_size = 65536; // 64KB chunks
    char *buf = xmalloc(buf_size);
    ssize_t n_read;
    uint64_t lines_found = 0;
    
    char *partial = NULL;
    size_t partial_len = 0;

    while (lines_found < count) {
        n_read = read(fd, buf, buf_size);
        if (n_read < 0 && errno == EINTR) continue;
        if (n_read <= 0) break; // EOF or Error

        char *p = buf;
        char *end = buf + n_read;
        char *line_start = p;

        while (p < end && lines_found < count) {
            // Fast scan for newline
            char *nl = memchr(p, '\n', end - p);
            
            if (nl) {
                // Found a line
                *nl = '\0'; 
                
                WORD_DESC *wd;
                if (partial) {
                    size_t frag_len = nl - line_start;
                    char *full_line = xmalloc(partial_len + frag_len + 1);
                    memcpy(full_line, partial, partial_len);
                    memcpy(full_line + partial_len, line_start, frag_len);
                    full_line[partial_len + frag_len] = '\0';
                    
                    wd = make_bare_word(full_line);
                    free(full_line);
                    
                    free(partial);
                    partial = NULL;
                    partial_len = 0;
                } else {
                    wd = make_bare_word(line_start);
                }

                wd->flags |= W_QUOTED; 
                WORD_LIST *wl = make_word_list(wd, NULL);
                if (!head) head = wl;
                else tail->next = wl;
                tail = wl;

                lines_found++;
                line_start = nl + 1;
                p = nl + 1;
            } else {
                p = end;
            }
        }

        // Handle leftovers in buffer
        if (line_start < end) {
            // If we finished count, we ignore the rest (No rollback needed)
            if (lines_found < count) {
                // We ran out of buffer but need more lines. 
                // Save the partial line.
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
    }

    // If we hit EOF with a partial line, treat it as the final argument
    if (partial && lines_found < count) {
        // Null terminate and add
        char *final_s = xrealloc(partial, partial_len + 1);
        final_s[partial_len] = '\0';
        WORD_DESC *wd = make_bare_word(final_s);
        wd->flags |= W_QUOTED;
        WORD_LIST *wl = make_word_list(wd, NULL);
        if (!head) head = wl;
        else tail->next = wl;
        free(final_s);
    } else if (partial) {
        free(partial);
    }
    
    free(buf);

    if (!head) return EXECUTION_SUCCESS; // Nothing to run

    // --- 3. Execute ---
    COMMAND *cmd = (COMMAND *)xmalloc(sizeof(COMMAND));
    memset(cmd, 0, sizeof(COMMAND));
    cmd->type = cm_simple;
    
    SIMPLE_COM *sc = (SIMPLE_COM *)xmalloc(sizeof(SIMPLE_COM));
    memset(sc, 0, sizeof(SIMPLE_COM));
    sc->words = head;
    
    cmd->value.Simple = sc;

    int result = execute_command(cmd);
    
    dispose_command(cmd);
    return result;
}

static int forkrun_ring_builtin(WORD_LIST *list) {
    int argc;
    char **argv = make_builtin_argv(list, &argc);
    if (argc < 1) return EXECUTION_FAILURE;
    int ret = EXECUTION_FAILURE;
    if      (strcmp(argv[0], "ring_init") == 0)    ret = ring_init_main(argc, argv);
    else if (strcmp(argv[0], "ring_destroy") == 0) ret = ring_destroy_main(argc, argv);
    else if (strcmp(argv[0], "ring_scanner") == 0) ret = ring_scanner_main(argc, argv);
    else if (strcmp(argv[0], "ring_claim") == 0)   ret = ring_claim_main(argc, argv);
    else if (strcmp(argv[0], "ring_worker") == 0)  ret = ring_worker_main(argc, argv);
    else if (strcmp(argv[0], "ring_ingest") == 0)  ret = ring_ingest_main(argc, argv);
    else if (strcmp(argv[0], "ring_exec") == 0)    ret = ring_exec_main(argc, argv);
    else if (strcmp(argv[0], "lseek") == 0)        ret = lseek_main(argc, argv);
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
struct builtin lseek_struct         = { "lseek",        forkrun_ring_builtin, BUILTIN_ENABLED, lseek_doc, "lseek <FD> <OFFSET>...", 0 };

int setup_builtin_forkrun_ring(void) {
    add_builtin(&ring_init_struct, 1);
    add_builtin(&ring_destroy_struct, 1);
    add_builtin(&ring_scanner_struct, 1);
    add_builtin(&ring_claim_struct, 1);
    add_builtin(&ring_worker_struct, 1);
    add_builtin(&ring_ingest_struct, 1);
    add_builtin(&ring_exec_struct, 1);
    add_builtin(&lseek_struct, 1);
    return 0;
}
