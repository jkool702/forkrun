// forkrun_ring_loadables.c
// Forkrun v6.10 Ring Buffer Architecture
// Features: Zero-Copy, SPMC Ticket Lock, Quadratic Scaling, Geometric Slow-Start
// Fixes: Livelock (Urgent check removed from hot loop), Syntax Errors (Truncation fixed)

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
#elif defined(__powerpc__) || defined(__ppc__) || defined(__PPC__)
  #define cpu_relax() __asm__ __volatile__("or 27,27,27" ::: "memory")
#elif defined(__s390__) || defined(__s390x__)
  #define cpu_relax() __asm__ __volatile__("niai 14" ::: "memory")
#else
  #define cpu_relax() __asm__ __volatile__("" ::: "memory")
#endif

// GCC Built-ins
#define atomic_load_acquire(ptr)       __atomic_load_n(ptr, __ATOMIC_ACQUIRE)
#define atomic_load_relaxed(ptr)       __atomic_load_n(ptr, __ATOMIC_RELAXED)
#define atomic_store_release(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELEASE)
#define atomic_store_relaxed(ptr, val) __atomic_store_n(ptr, val, __ATOMIC_RELAXED)
#define atomic_fetch_add(ptr, val)     __atomic_fetch_add(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_fetch_sub(ptr, val)     __atomic_fetch_sub(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_exchange(ptr, val)      __atomic_exchange_n(ptr, val, __ATOMIC_ACQ_REL)

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"
#include "variables.h"

extern int add_builtin(struct builtin *bp, int keep);

static int forkrun_ring_builtin(WORD_LIST *list);
static int ring_init_main(int argc, char **argv);
static int ring_destroy_main(int argc, char **argv);
static int ring_scanner_main(int argc, char **argv);
static int ring_claim_main(int argc, char **argv);
static int ring_transfer_main(int argc, char **argv);
static int ring_worker_main(int argc, char **argv);
static int ring_ingest_main(int argc, char **argv);
static int lseek_main(int argc, char ** argv);

// ==============================================================
// ========================= SHARED STATE =======================
// ==============================================================

#define RING_SIZE_LOG2   20
#define RING_SIZE        (1ULL << RING_SIZE_LOG2)
#define RING_MASK        (RING_SIZE - 1)
#define CACHE_LINE_SIZE 256
#define ALIGNED(x) __attribute__((aligned(x > CACHE_LINE_SIZE ? x : CACHE_LINE_SIZE)))

struct SharedState {
    uint64_t read_idx ALIGNED(CACHE_LINE_SIZE);
    uint64_t active_workers;
    uint64_t total_lines_consumed;
    uint8_t  urgent_flag;
    char pad0[32];

    uint64_t write_idx ALIGNED(CACHE_LINE_SIZE);
    int64_t  signed_batch_size;
    uint8_t  ingest_complete;
    char pad1[48];

    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
};

static struct SharedState *state = NULL;
static int evfd_data = -1;
static int evfd_eof  = -1;

// Helper: Fast Integer Square Root (Overshoot Bias)
static inline uint64_t fast_isqrt(uint64_t val) {
    if (val < 2) return val;
    int log2_val = 63 - __builtin_clzll(val);
    int k = (log2_val + 1) >> 1; 
    uint64_t base = 1ULL << k;
    uint64_t remainder = val ^ (1ULL << log2_val);
    return base + (remainder >> (k + 1));
}

// Helper: Try Write to Pipe
static inline void try_write_spawn(int fd, const char *buf, size_t len) {
    struct pollfd pfd = { .fd = fd, .events = POLLOUT };
    if (poll(&pfd, 1, 0) > 0) {
        if (write(fd, buf, len) < 0) { /* ignore */ }
    }
}

// ==============================================================
// =========================== INIT =============================
// ==============================================================

static int ring_init_main(int argc, char **argv) {
    (void)argc; (void)argv;
    if (state != NULL) {
        atomic_store_relaxed(&state->read_idx, 0);
        atomic_store_relaxed(&state->write_idx, 0);
        atomic_store_relaxed(&state->signed_batch_size, 0);
        atomic_store_relaxed(&state->active_workers, 0);
        atomic_store_relaxed(&state->total_lines_consumed, 0);
        atomic_store_relaxed(&state->ingest_complete, 0);
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

    evfd_data = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    evfd_eof  = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);

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
    
    unbind_variable("EVFD_RING_DATA");
    unbind_variable("EVFD_RING_EOF");
    return EXECUTION_SUCCESS;
}

// ==============================================================
// ========================= SCANNER ============================
// ==============================================================

static int ring_scanner_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    
    int fd_spawn = -1;
    if (argc >= 3) {
        fd_spawn = atoi(argv[2]);
    }

    struct stat st;
    bool is_regular = (fstat(fd, &st) == 0 && S_ISREG(st.st_mode));

    // --- Configuration ---
    char *tmp;
    char delim = '\n';
    if ((tmp = get_string_value("delimiterVal")) && tmp[0]) delim = tmp[0];
    else if (tmp && !tmp[0]) delim = '\0';

    long nLines = 0;
    if ((tmp = get_string_value("nLines"))) nLines = atol(tmp);
    
    long nLinesMax = 1024;
    if ((tmp = get_string_value("nLinesMax"))) nLinesMax = atol(tmp);
    
    long nPhysicalCores = sysconf(_SC_NPROCESSORS_ONLN);
    long nCPU = nPhysicalCores; 
    long nWorkers = nPhysicalCores; 
    
    if ((tmp = get_string_value("nWorkers"))) nWorkers = atol(tmp);
    
    long nWorkersMax = nCPU * 2;
    if ((tmp = get_string_value("nWorkersMax"))) nWorkersMax = atol(tmp);

    // --- State Setup ---
    uint64_t current_batch = (nLines > 0) ? nLines : 1;
    if (current_batch > (uint64_t)nLinesMax) current_batch = nLinesMax;
    
    int64_t signed_batch = (nLines > 0) ? (int64_t)nLines : -(int64_t)current_batch;
    atomic_store_relaxed(&state->signed_batch_size, signed_batch);

    uint64_t local_write_idx = atomic_load_relaxed(&state->write_idx);
    uint64_t total_scanned = 0;
    uint64_t last_batch_change = 0;
    uint64_t ramp_up_counter = 0;

    const size_t CHUNK = 1024 * 1024 * 4; 
    char *buf = xmalloc(CHUNK);
    
    uint64_t current_file_offset = (uint64_t)lseek(fd, 0, SEEK_CUR);
    uint64_t batch_start = current_file_offset;
    uint64_t scan_head_offset = current_file_offset;
    uint64_t local_count = 0;
    bool first_chunk = true;

    // --- QUADRATIC SCALING MACRO ---
    #define DO_SPAWN_CHECK() do { \
        uint64_t cur_w = atomic_load_relaxed(&state->active_workers); \
        if (cur_w < (uint64_t)nWorkersMax) { \
            uint64_t consumed = atomic_load_relaxed(&state->total_lines_consumed); \
            uint64_t backlog = total_scanned - consumed; \
            uint64_t term = (backlog * (uint64_t)nWorkersMax) / (uint64_t)nLinesMax; \
            uint64_t target_w = fast_isqrt(term); \
            if (target_w > (uint64_t)nWorkersMax) target_w = nWorkersMax; \
            if (target_w < (uint64_t)nWorkers) target_w = nWorkers; \
            if (fd_spawn >= 0 && target_w > cur_w) { \
                uint64_t diff = target_w - cur_w; \
                char sbuf[32]; \
                int len = snprintf(sbuf, sizeof(sbuf), "%lu\n", diff); \
                try_write_spawn(fd_spawn, sbuf, len); \
            } \
            if (nLines == 0) { \
                uint64_t new_batch = (target_w * (uint64_t)nLinesMax) / (uint64_t)nWorkersMax; \
                if (new_batch < 1) new_batch = 1; \
                if (new_batch > current_batch) { \
                    current_batch = new_batch; \
                    int64_t old_s = atomic_load_relaxed(&state->signed_batch_size); \
                    int64_t new_s = (old_s < 0) ? -(int64_t)current_batch : (int64_t)current_batch; \
                    atomic_store_release(&state->signed_batch_size, new_s); \
                    last_batch_change = consumed; \
                } \
            } \
        } \
        if (nLines == 0) { \
            int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size); \
            if (sbatch < 0) { \
                uint64_t consumed = atomic_load_relaxed(&state->total_lines_consumed); \
                if (consumed > last_batch_change + ((uint64_t)nWorkersMax * current_batch * 4)) { \
                    atomic_store_release(&state->signed_batch_size, (int64_t)current_batch); \
                } \
            } \
        } \
    } while(0)

    // FLUSH MACRO
    #define FLUSH_BATCH() do { \
        if (batch_start & 0xFFFF000000000000ULL) { \
             builtin_error("ring_scanner: offset > 256TB"); \
             xfree(buf); return EXECUTION_FAILURE; \
        } \
        uint64_t packed = ((uint64_t)local_count << 48) | batch_start; \
        state->offset_ring[local_write_idx & RING_MASK] = packed; \
        state->stride_ring[local_write_idx & RING_MASK] = (uint16_t)local_count; \
        local_write_idx++; \
        atomic_store_release(&state->write_idx, local_write_idx); \
        if (atomic_exchange(&state->urgent_flag, 0)) { \
            uint64_t one = 1; \
            write(evfd_data, &one, sizeof(one)); \
        } \
        if (nLines == 0 && current_batch < (uint64_t)nLinesMax) { \
             ramp_up_counter++; \
             if (ramp_up_counter >= (uint64_t)nWorkersMax) { \
                 current_batch <<= 1; \
                 if (current_batch > (uint64_t)nLinesMax) current_batch = nLinesMax; \
                 atomic_store_release(&state->signed_batch_size, -(int64_t)current_batch); \
                 ramp_up_counter = 0; \
             } \
        } \
        if ((local_write_idx & 1023) == 0) DO_SPAWN_CHECK(); \
        local_count = 0; \
    } while(0)

    while (1) {
        int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size);
        uint64_t target = (sbatch <= 0) ? current_batch : (uint64_t)llabs(sbatch);

        // Poll Loop with Timeout Flush
        while(1) {
            struct pollfd pfd = { .fd = fd, .events = POLLIN };
            int ret = poll(&pfd, 1, 1); // 1ms timeout
            
            if (ret > 0) break; // Data ready
            
            // Timeout: Flush if pending data exists
            if (local_count > 0) {
                 FLUSH_BATCH();
                 batch_start = scan_head_offset;
            }
            
            if (atomic_load_acquire(&state->ingest_complete)) break; 
            if (ret < 0 && errno != EINTR) break; 
        }

        ssize_t n = read(fd, buf, CHUNK);
        
        if (n < 0) {
            if (errno == EINTR) continue;
            break; 
        }
        
        if (n == 0) {
            if (local_count > 0) {
                FLUSH_BATCH();
                batch_start = scan_head_offset;
            }
            if (is_regular || atomic_load_acquire(&state->ingest_complete)) break;
            usleep(100); 
            continue;
        }

        // --- CALIBRATION (First Chunk) ---
        if (first_chunk && nLines == 0 && n > 0) {
            size_t limit = (n > 65536) ? 65536 : n;
            size_t calib_lines = 0;
            void *p = buf;
            while (1) {
                void *nl = memchr(p, delim, (buf + limit) - (char*)p);
                if (!nl) break;
                calib_lines++;
                p = (char*)nl + 1;
            }
            if (calib_lines > 0) {
                double ratio = (double)n / limit;
                uint64_t total_est = calib_lines * ratio;
                uint64_t ideal = total_est / nWorkers;
                if (ideal < 1) ideal = 1;
                if (ideal > (uint64_t)nLinesMax) ideal = nLinesMax;
                
                current_batch = ideal;
                target = ideal;
                atomic_store_release(&state->signed_batch_size, -(int64_t)current_batch);
            }
            first_chunk = false;
        }

        char *p = buf;
        char *end = buf + n;

        while (p < end) {
            char *nl = memchr(p, delim, end - p);
            
            if (nl) {
                local_count++;
                total_scanned++;
                p = nl + 1;
                
                scan_head_offset = current_file_offset + (uint64_t)((char*)p - buf);

                if (local_count >= target) {
                    // Backpressure check
                    while (local_write_idx - atomic_load_acquire(&state->read_idx) >= RING_SIZE) {
                         // Still check urgency if blocked
                         if (atomic_load_relaxed(&state->urgent_flag)) {
                             if (atomic_exchange(&state->urgent_flag, 0)) {
                                 uint64_t one = 1;
                                 write(evfd_data, &one, sizeof(one));
                             }
                         }
                         usleep(500);
                    }
                    
                    FLUSH_BATCH();
                    batch_start = scan_head_offset;
                }
            } else {
                p = end; 
            }
        }
        current_file_offset += n;
    }

    if (local_count > 0) {
        FLUSH_BATCH();
    }

    // --- SENTINEL ---
    uint64_t sentinel_packed = ((uint64_t)0 << 48) | current_file_offset;
    state->offset_ring[local_write_idx & RING_MASK] = sentinel_packed;
    state->stride_ring[local_write_idx & RING_MASK] = 0;
    local_write_idx++;
    atomic_store_release(&state->write_idx, local_write_idx);

    DO_SPAWN_CHECK();

    if (fd_spawn >= 0) {
        dprintf(fd_spawn, "x\n");
    }

    uint64_t one = 1;
    write(evfd_eof, &one, sizeof(one));
    
    xfree(buf);
    return EXECUTION_SUCCESS;
}

// ==============================================================
// =========================== CLAIM ============================
// ==============================================================

static int ring_claim_main(int argc, char **argv) {
    if (argc < 3 || argc > 4) return EXECUTION_FAILURE;
    const char *var_offset = argv[1];
    const char *var_count  = argv[2];
    int seek_fd = -1;
    if (argc == 4) seek_fd = atoi(argv[3]);

    uint64_t w_idx = atomic_load_acquire(&state->write_idx);
    uint64_t r_idx_snapshot = atomic_load_acquire(&state->read_idx);

    int spin_count = 0;
    int poll_timeout = 0; 

    while (r_idx_snapshot >= w_idx) {
        if (spin_count < 1000) {
            cpu_relax();
            spin_count++;
            w_idx = atomic_load_acquire(&state->write_idx);
            if (r_idx_snapshot < w_idx) break;
            continue;
        }
        atomic_store_release(&state->urgent_flag, 1);
        struct pollfd pfds[2] = { {.fd = evfd_data, .events = POLLIN}, {.fd = evfd_eof, .events = POLLIN} };
        if (poll_timeout == 0) poll_timeout = 1; else if (poll_timeout < 20) poll_timeout = 20;
        poll(pfds, 2, poll_timeout); 
        if (pfds[1].revents & POLLIN) {
            w_idx = atomic_load_acquire(&state->write_idx);
            if (r_idx_snapshot >= w_idx) {
                bind_variable(var_offset, "0", 0); bind_variable(var_count, "0", 0); return 1; 
            }
        }
        if (pfds[0].revents & POLLIN) { uint64_t v; read(evfd_data, &v, sizeof(v)); (void)v; }
        w_idx = atomic_load_acquire(&state->write_idx);
        r_idx_snapshot = atomic_load_acquire(&state->read_idx);
    }

    int64_t sbatch = atomic_load_acquire(&state->signed_batch_size);
    uint64_t slots_to_claim = 1;

    if (sbatch > 0) {
        slots_to_claim = 1;
    } else {
        uint64_t target = (uint64_t)llabs(sbatch);
        uint16_t stride_val = state->stride_ring[r_idx_snapshot & RING_MASK];
        uint64_t lines_per_slot = (stride_val == 0) ? 1 : stride_val;
        
        uint64_t guess = (target + lines_per_slot - 1) / lines_per_slot;
        
        uint64_t avail = w_idx - r_idx_snapshot;
        uint64_t workers = atomic_load_relaxed(&state->active_workers);
        if (workers == 0) workers = 1;
        uint64_t fair_share = avail / workers;
        if (fair_share < 1) fair_share = 1;
        
        slots_to_claim = (guess < fair_share) ? guess : fair_share;
        if (slots_to_claim > workers) slots_to_claim = workers; // Clamp to ramp-up plateau
        if (slots_to_claim > 1024) slots_to_claim = 1024; 
    }

    uint64_t my_start, my_end;
    while (1) {
        if (r_idx_snapshot >= w_idx) {
             w_idx = atomic_load_acquire(&state->write_idx);
             if (r_idx_snapshot >= w_idx) {
                 cpu_relax();
                 struct pollfd peof = { .fd = evfd_eof, .events = POLLIN };
                 if (poll(&peof, 1, 0) > 0) {
                     bind_variable(var_offset, "0", 0); bind_variable(var_count, "0", 0); return 1;
                 }
                 continue;
             }
        }
        my_start = atomic_fetch_add(&state->read_idx, slots_to_claim);
        my_end = my_start + slots_to_claim;
        break;
    }

    if (my_end > w_idx) {
        struct pollfd peof = { .fd = evfd_eof, .events = POLLIN };
        if (poll(&peof, 1, 0) > 0) {
            uint64_t w_now = atomic_load_acquire(&state->write_idx);
            if (my_end > w_now) my_end = w_now;
            if (my_start >= my_end) {
                bind_variable(var_offset, "0", 0); bind_variable(var_count, "0", 0); return 1;
            }
        }
    }

    uint64_t total_lines = 0;
    uint64_t start_byte = 0;
    bool first = true;
    uint64_t w_latest = atomic_load_acquire(&state->write_idx);
    bool fast_iterate = (w_latest > my_end);

    for (uint64_t i = my_start; i < my_end; i++) {
        if (!fast_iterate) {
            while (i >= w_idx) {
                uint64_t fresh_w = atomic_load_acquire(&state->write_idx);
                if (fresh_w > w_idx) {
                    w_idx = fresh_w;
                    if (i < w_idx) break;
                }
                struct pollfd pfd = { .fd = evfd_eof, .events = POLLIN };
                if (poll(&pfd, 1, 0) > 0) goto report; 
                cpu_relax();
            }
        }

        if (slots_to_claim == 1) {
            uint64_t packed = state->offset_ring[i & RING_MASK];
            start_byte = packed & 0xFFFFFFFFFFFFULL;
            total_lines = packed >> 48;
        } else {
            if (first) {
                uint64_t packed = state->offset_ring[i & RING_MASK];
                start_byte = packed & 0xFFFFFFFFFFFFULL;
                first = false;
            }
            total_lines += state->stride_ring[i & RING_MASK];
        }
    }

report:
    atomic_fetch_add(&state->total_lines_consumed, total_lines);

    char buf[32];
    snprintf(buf, sizeof(buf), "%" PRIu64, start_byte);
    bind_variable(var_offset, buf, 0);
    snprintf(buf, sizeof(buf), "%" PRIu64, total_lines);
    bind_variable(var_count, buf, 0);

    if (seek_fd >= 0 && total_lines > 0) {
        lseek(seek_fd, (off_t)start_byte, SEEK_SET);
    }

    return 0;
}

// ==============================================================
// ========================== TRANSFER ==========================
// ==============================================================

static char *ring_transfer_doc[] = {
    "Zero-copy splice of a batch from Source FD to Dest FD.",
    "Usage: ring_transfer <SRC_FD> <DST_FD>",
    "Returns 0 on success, 1 on EOF.",
    NULL
};

static int ring_transfer_main(int argc, char **argv) {
    if (argc != 3) return EXECUTION_FAILURE;
    int src_fd = atoi(argv[1]);
    int dst_fd = atoi(argv[2]);

    uint64_t w_idx = atomic_load_acquire(&state->write_idx);
    uint64_t r_idx_snapshot = atomic_load_acquire(&state->read_idx);

    int spin_count = 0;
    int poll_timeout = 0;
    while (r_idx_snapshot >= w_idx) {
        if (spin_count < 1000) {
            cpu_relax(); spin_count++;
            w_idx = atomic_load_acquire(&state->write_idx);
            if (r_idx_snapshot < w_idx) break;
            continue;
        }
        atomic_store_release(&state->urgent_flag, 1);
        struct pollfd pfds[2] = { {.fd=evfd_data, .events=POLLIN}, {.fd=evfd_eof, .events=POLLIN} };
        poll(pfds, 2, (poll_timeout < 20 ? ++poll_timeout : 20));
        if (pfds[1].revents & POLLIN) {
             w_idx = atomic_load_acquire(&state->write_idx);
             if (r_idx_snapshot >= w_idx) return 1; 
        }
        if (pfds[0].revents) { uint64_t v; read(evfd_data, &v, sizeof(v)); (void)v; }
        w_idx = atomic_load_acquire(&state->write_idx);
        r_idx_snapshot = atomic_load_acquire(&state->read_idx);
    }

    int64_t sbatch = atomic_load_acquire(&state->signed_batch_size);
    uint64_t slots = 1;
    if (sbatch <= 0) {
        uint64_t target = (uint64_t)llabs(sbatch);
        uint16_t stride = state->stride_ring[r_idx_snapshot & RING_MASK];
        uint64_t lines = (stride == 0) ? 1 : stride;
        uint64_t guess = (target + lines - 1) / lines;
        uint64_t avail = w_idx - r_idx_snapshot;
        uint64_t workers = atomic_load_relaxed(&state->active_workers);
        if (workers == 0) workers = 1;
        uint64_t fair = avail / workers;
        if (fair < 1) fair = 1;
        slots = (guess < fair) ? guess : fair;
        if (slots > workers) slots = workers;
        if (slots > 1024) slots = 1024;
    }

    uint64_t my_start, my_end;
    while(1) {
        if (r_idx_snapshot >= w_idx) {
             w_idx = atomic_load_acquire(&state->write_idx);
             if (r_idx_snapshot >= w_idx) {
                 cpu_relax();
                 struct pollfd peof = { .fd = evfd_eof, .events = POLLIN };
                 if (poll(&peof, 1, 0) > 0) return 1;
                 continue;
             }
        }
        my_start = atomic_fetch_add(&state->read_idx, slots);
        my_end = my_start + slots;
        break;
    }

    if (my_end > w_idx) {
        struct pollfd peof = { .fd = evfd_eof, .events = POLLIN };
        if (poll(&peof, 1, 0) > 0) {
            uint64_t w_now = atomic_load_acquire(&state->write_idx);
            if (my_end > w_now) my_end = w_now;
            if (my_start >= my_end) return 1;
        }
    }

    uint64_t total_lines = 0;
    uint64_t w_latest = atomic_load_acquire(&state->write_idx);
    bool fast_iterate = (w_latest > my_end);

    for (uint64_t i = my_start; i < my_end; i++) {
        uint64_t next_idx = i + 1;
        if (!fast_iterate) {
            while (next_idx >= w_idx) {
                 uint64_t fresh_w = atomic_load_acquire(&state->write_idx);
                 if (fresh_w > w_idx) {
                     w_idx = fresh_w;
                     if (next_idx < w_idx) break;
                 }
                 struct pollfd pfd = { .fd = evfd_eof, .events = POLLIN };
                 if (poll(&pfd, 1, 0) > 0) {
                     w_idx = atomic_load_acquire(&state->write_idx);
                     if (next_idx >= w_idx) return 1; 
                     break;
                 }
                 cpu_relax();
            }
        }

        uint64_t packed_start = state->offset_ring[i & RING_MASK];
        uint64_t packed_end   = state->offset_ring[next_idx & RING_MASK];
        
        uint64_t start_byte = packed_start & 0xFFFFFFFFFFFFULL;
        uint64_t end_byte   = packed_end & 0xFFFFFFFFFFFFULL;
        uint64_t length     = end_byte - start_byte;
        uint64_t lines      = packed_start >> 48;

        if (lines == 0) continue; 

        loff_t offset_in = (loff_t)start_byte;
        size_t remaining = length;
        
        while (remaining > 0) {
            size_t chunk = (remaining > 2147483647) ? 2147483647 : remaining;
            ssize_t ret = splice(src_fd, &offset_in, dst_fd, NULL, chunk, 
                                 SPLICE_F_MOVE | SPLICE_F_MORE);
            if (ret < 0) {
                if (errno == EINTR || errno == EAGAIN) continue;
                break; 
            }
            if (ret == 0) break; 
            remaining -= ret;
        }
        total_lines += lines;
    }

    atomic_fetch_add(&state->total_lines_consumed, total_lines);
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

static char * lseek_doc[] = {
    "",
    "USAGE: lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",
    "",
    "Move the given file descriptor <FD> by <OFFSET> bytes.",
    "",
    "- SEEK_TYPE (optional): SEEK_SET, SEEK_CUR (default), SEEK_END",
    "- VAR (optional): If given, store new file offset in variable VAR.",
    "- If VAR is empty (''), enable quiet mode (no output).",
    "",
    "Returns new offset or stores it.",
    NULL
};

static int lseek_main(int argc, char ** argv) {
    if (argc < 3 || argc > 5) {
        builtin_error("lseek: incorrect number of arguments");
        return EXECUTION_FAILURE;
    }
    int fd = atoi(argv[1]);
    if (fd < 0) {
        builtin_error("lseek: invalid file descriptor '%s'", argv[1]);
        return EXECUTION_FAILURE;
    }
    errno = 0;
    off_t offset = atoll(argv[2]);
    if (errno == ERANGE) {
        builtin_error("lseek: offset out of range '%s'", argv[2]);
        return EXECUTION_FAILURE;
    }
    int whence = SEEK_CUR;
    int quiet = 0;
    char * varname = NULL;
    if (argc > 3) {
        if (strcmp(argv[3], "SEEK_SET") == 0) whence = SEEK_SET;
        else if (strcmp(argv[3], "SEEK_END") == 0) whence = SEEK_END;
        else if (argv[3][0] != '\0') {
            varname = argv[3];
        }
        if (argc == 5) {
            if (argv[4][0] == '\0') quiet = 1;
            else varname = argv[4];
        }
    }
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t) - 1) {
        builtin_error("lseek: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    if (varname) {
        char buf_off[32];
        snprintf(buf_off, sizeof(buf_off), "%lld", (long long) new_offset);
        bind_variable(varname, buf_off, 0);
    } else if (!quiet) {
        printf("%lld\n", (long long) new_offset);
    }
    return EXECUTION_SUCCESS;
}

// ==============================================================
// =================== REGISTER BUILTINS ========================
// ==============================================================

struct builtin ring_init_struct     = { "ring_init",    forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_init", 0 };
struct builtin ring_destroy_struct  = { "ring_destroy", forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_destroy", 0 };
struct builtin ring_scanner_struct  = { "ring_scanner", forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_scanner <fd> [spawn_fd]", 0 };
struct builtin ring_claim_struct    = { "ring_claim",   forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_claim <OFF> <CNT> [FD]", 0 };
struct builtin ring_transfer_struct = { "ring_transfer",forkrun_ring_builtin, BUILTIN_ENABLED, ring_transfer_doc, "ring_transfer <SRC> <DST>", 0 };
struct builtin ring_worker_struct   = { "ring_worker",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_worker [inc|dec]", 0 };
struct builtin ring_ingest_struct   = { "ring_ingest",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_ingest", 0 };
struct builtin lseek_struct         = { "lseek",        forkrun_ring_builtin, BUILTIN_ENABLED, lseek_doc, "lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]", 0 };

// ==============================================================
// ========================== DISPATCHER ========================
// ==============================================================

static int forkrun_ring_builtin(WORD_LIST *list) {
    int argc;
    char **argv = make_builtin_argv(list, &argc);
    if (argc < 1) return EXECUTION_FAILURE;
    int ret = EXECUTION_FAILURE;
    if      (strcmp(argv[0], "ring_init") == 0)    ret = ring_init_main(argc, argv);
    else if (strcmp(argv[0], "ring_destroy") == 0) ret = ring_destroy_main(argc, argv);
    else if (strcmp(argv[0], "ring_scanner") == 0) ret = ring_scanner_main(argc, argv);
    else if (strcmp(argv[0], "ring_claim") == 0)   ret = ring_claim_main(argc, argv);
    else if (strcmp(argv[0], "ring_transfer") == 0)ret = ring_transfer_main(argc, argv);
    else if (strcmp(argv[0], "ring_worker") == 0)  ret = ring_worker_main(argc, argv);
    else if (strcmp(argv[0], "ring_ingest") == 0)  ret = ring_ingest_main(argc, argv);
    else if (strcmp(argv[0], "lseek") == 0)        ret = lseek_main(argc, argv);
    xfree(argv);
    return ret;
}

int setup_builtin_forkrun_ring(void) {
    add_builtin(&ring_init_struct , 1);
    add_builtin(&ring_destroy_struct , 1);
    add_builtin(&ring_scanner_struct , 1);
    add_builtin(&ring_claim_struct , 1);
    add_builtin(&ring_transfer_struct , 1);
    add_builtin(&ring_worker_struct , 1);
    add_builtin(&ring_ingest_struct , 1);
    add_builtin(&lseek_struct , 1);
    return 0;
}