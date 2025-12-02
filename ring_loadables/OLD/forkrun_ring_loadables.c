// forkrun_ring_loadables.c
// Forkrun v5 Ring Buffer Architecture (Final Gold Master + Streaming Patch)
// Features: Zero-Copy, SPMC Ticket Lock, Dynamic Batch Sizing, 16-bit Strides
// Hardening: Adaptive Timeouts, Immediate EOF Clamping, Explicit Memory Ordering
// Streaming: Supports active pipes via ring_ingest signal

// forkrun_ring_loadables.c (v5.2 - Dynamic Spawning & Overflow Protection)

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

// GCC Built-ins for C11 consistency
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
static int ring_scanner_main(int argc, char **argv);
static int ring_claim_main(int argc, char **argv);
static int ring_worker_main(int argc, char **argv);
static int ring_ingest_main(int argc, char **argv);
static int lseek_main(int argc, char ** argv);


// ==============================================================
// ========================= SHARED STATE =======================
// ==============================================================

#define RING_SIZE_LOG2   20
#define RING_SIZE        (1ULL << RING_SIZE_LOG2)
#define RING_MASK        (RING_SIZE - 1)
#define ALIGNED(x) __attribute__((aligned(x)))

struct SharedState {
    // Cache Line 0: Worker-Modified
    uint64_t read_idx ALIGNED(64);
    uint64_t active_workers ALIGNED(64);
    uint8_t  urgent_flag ALIGNED(64);
    uint64_t total_lines_consumed ALIGNED(64);
    char pad0[32];

    // Cache Line 1: Scanner-Modified
    uint64_t write_idx ALIGNED(64);
    int64_t  signed_batch_size ALIGNED(64);
    uint8_t  ingest_complete ALIGNED(64);
    char pad1[48];

    // The Rings (Synchronized via write_idx release-store)
    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
};

static struct SharedState *state = NULL;
static int evfd_data = -1;
static int evfd_eof  = -1;

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
    
    // Optional spawn FD
    int fd_spawn = -1;
    if (argc >= 3) fd_spawn = atoi(argv[2]);

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
    
    // Fix: Distinct variables for Physical CPU count vs Configured Workers
    long nPhysicalCores = sysconf(_SC_NPROCESSORS_ONLN);
    long nCPU = nPhysicalCores; 
    long nWorkers = nPhysicalCores; // Default to physical count
    
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

    const size_t CHUNK = 1024 * 1024 * 4; 
    char *buf = xmalloc(CHUNK);
    
    uint64_t current_file_offset = (uint64_t)lseek(fd, 0, SEEK_CUR);
    uint64_t batch_start = current_file_offset;
    uint64_t local_count = 0;

    // --- Helper Macro for Spawning Logic ---
    #define DO_SPAWN_CHECK() do { \
        if (fd_spawn >= 0) { \
            uint64_t cur_w = atomic_load_relaxed(&state->active_workers); \
            if (cur_w < (uint64_t)nWorkersMax) { \
                uint64_t backlog = local_write_idx - atomic_load_relaxed(&state->read_idx); \
                uint64_t X = 4; \
                if (cur_w < (uint64_t)nCPU) { \
                    X = 4 + (2 * ((uint64_t)nCPU - cur_w)) / (uint64_t)nCPU; \
                } else { \
                    uint64_t range = (uint64_t)nWorkersMax - (uint64_t)nCPU; \
                    if (range > 0) X = 1 + ((uint64_t)nWorkersMax - cur_w) / range; \
                    else X = 1; \
                } \
                uint64_t w_new = (X * (1 + (uint64_t)nWorkersMax) * backlog) >> 20; \
                if (w_new > (uint64_t)nWorkersMax) w_new = nWorkersMax; \
                if (w_new > cur_w) { \
                    uint64_t diff = w_new - cur_w; \
                    dprintf(fd_spawn, "%lu\n", diff); \
                } \
            } \
        } \
    } while(0)

    while (1) {
        int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size);
        uint64_t target = (sbatch <= 0) ? current_batch : (uint64_t)llabs(sbatch);

        ssize_t n = read(fd, buf, CHUNK);
        
        if (n < 0) {
            if (errno == EINTR) continue;
            break; 
        }
        
        if (n == 0) {
            if (is_regular || atomic_load_acquire(&state->ingest_complete)) break;
            usleep(100); 
            continue;
        }

        char *p = buf;
        char *end = buf + n;

        while (p < end) {
            char *nl = memchr(p, delim, end - p);
            
            if (nl) {
                local_count++;
                total_scanned++;
                p = nl + 1;

                if (local_count >= target || atomic_load_relaxed(&state->urgent_flag)) {
                    
                    // Overflow Backpressure
                    while (local_write_idx - atomic_load_acquire(&state->read_idx) >= RING_SIZE) {
                        usleep(500); 
                    }

                    // 48-bit Offset Check
                    if (batch_start & 0xFFFF000000000000ULL) {
                         builtin_error("ring_scanner: offset > 256TB");
                         xfree(buf);
                         return EXECUTION_FAILURE;
                    }
                    
                    uint64_t packed = ((uint64_t)local_count << 48) | batch_start;
                    state->offset_ring[local_write_idx & RING_MASK] = packed;
                    state->stride_ring[local_write_idx & RING_MASK] = (uint16_t)local_count;

                    local_write_idx++;
                    atomic_store_release(&state->write_idx, local_write_idx);

                    if (atomic_exchange(&state->urgent_flag, 0)) {
                        uint64_t one = 1;
                        write(evfd_data, &one, sizeof(one));
                    }

                    // Check spawn logic every 1024 batches
                    if ((local_write_idx & 1023) == 0) {
                        DO_SPAWN_CHECK();
                    }

                    // Dynamic Batch Logic
                    if (nLines == 0 && current_batch < (uint64_t)nLinesMax) {
                        uint64_t consumed = atomic_load_relaxed(&state->total_lines_consumed);
                        uint64_t backlog = total_scanned - consumed;
                        
                        // Use nWorkers (configured) for calculation
                        if (backlog > (uint64_t)nWorkers * current_batch * 2) {
                             uint64_t ideal = backlog / nWorkers;
                             if (ideal > current_batch) {
                                 // Explicit cast
                                 current_batch = (ideal > (uint64_t)nLinesMax) ? (uint64_t)nLinesMax : ideal;
                                 last_batch_change = consumed;
                                 atomic_store_release(&state->signed_batch_size, -(int64_t)current_batch);
                             }
                        }
                        
                        if (sbatch < 0 && consumed > last_batch_change + (nWorkers*current_batch*4)) {
                             atomic_store_release(&state->signed_batch_size, (int64_t)current_batch);
                        }
                    }

                    local_count = 0;
                    batch_start = current_file_offset + (uint64_t)(p - buf);
                }
            } else {
                p = end; 
            }
        }
        current_file_offset += n;
    }

    if (local_count > 0) {
        uint64_t packed = ((uint64_t)local_count << 48) | batch_start;
        state->offset_ring[local_write_idx & RING_MASK] = packed;
        state->stride_ring[local_write_idx & RING_MASK] = (uint16_t)local_count;
        local_write_idx++;
        atomic_store_release(&state->write_idx, local_write_idx);
    }

    // --- FINAL FLUSH & SIGNAL ---
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
    if (argc != 3) return EXECUTION_FAILURE;
    const char *var_offset = argv[1];
    const char *var_count  = argv[2];

    uint64_t w_idx = atomic_load_acquire(&state->write_idx);
    uint64_t r_idx_snapshot = atomic_load_acquire(&state->read_idx);

    // --- 1. Adaptive Wait Phase (Unchanged) ---
    int spin_count = 0;
    int poll_timeout = 0; 

    while (r_idx_snapshot >= w_idx) {
        if (spin_count < 1000) {
            __builtin_ia32_pause();
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

    // --- 2. Calculate Claim (Unchanged) ---
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
        if (slots_to_claim > 1024) slots_to_claim = 1024; 
    }

    // --- 3. Reservation (Unchanged) ---
    uint64_t my_start, my_end;
    while (1) {
        if (r_idx_snapshot >= w_idx) {
             w_idx = atomic_load_acquire(&state->write_idx);
             if (r_idx_snapshot >= w_idx) {
                 __builtin_ia32_pause();
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

    // --- 3.5. EOF Clamping (Unchanged) ---
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

    // --- 4. Unified Processing (FIXED) ---
    uint64_t total_lines = 0;
    uint64_t start_byte = 0;

    // 4a. Wait for the FIRST slot (with Stale Data Protection)
    while (my_start >= w_idx) {
        // FIX: Refresh w_idx BEFORE checking EOF. 
        // This ensures we see late-arriving data even if EOF is set.
        uint64_t fresh_w = atomic_load_acquire(&state->write_idx);
        if (fresh_w > w_idx) {
            w_idx = fresh_w;
            if (my_start < w_idx) break; // Data arrived!
        }

        struct pollfd pfd = { .fd = evfd_eof, .events = POLLIN };
        if (poll(&pfd, 1, 0) > 0) {
             bind_variable(var_offset, "0", 0); bind_variable(var_count, "0", 0); return 1;
        }
        __builtin_ia32_pause();
    }

    // 4b. Get Start Byte and Initial Count
    uint64_t packed = state->offset_ring[my_start & RING_MASK];
    start_byte = packed & 0xFFFFFFFFFFFFULL;

    if (slots_to_claim == 1) {
        total_lines = packed >> 48;
    } else {
        total_lines = state->stride_ring[my_start & RING_MASK];

        for (uint64_t i = my_start + 1; i < my_end; i++) {
            // Barrier for subsequent slots
            while (i >= w_idx) {
                // Same Fix here: Refresh before Abort
                uint64_t fresh_w = atomic_load_acquire(&state->write_idx);
                if (fresh_w > w_idx) {
                    w_idx = fresh_w;
                    if (i < w_idx) break;
                }

                struct pollfd pfd = { .fd = evfd_eof, .events = POLLIN };
                if (poll(&pfd, 1, 0) > 0) goto report; 
                __builtin_ia32_pause();
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
struct builtin ring_claim_struct    = { "ring_claim",   forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_claim <OFF> <CNT>", 0 };
struct builtin ring_worker_struct   = { "ring_worker",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_worker [inc|dec]", 0 };
struct builtin ring_ingest_struct   = { "ring_ingest",  forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "ring_ingest", 0 };
struct builtin lseek_struct         = { "lseek",        forkrun_ring_builtin, BUILTIN_ENABLED, NULL, "lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]", 0 };

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
    add_builtin(&ring_worker_struct , 1);
    add_builtin(&ring_ingest_struct , 1);
    add_builtin(&lseek_struct , 1);
    return 0;
}