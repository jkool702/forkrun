// forkrun_ring.c v8.38
// ======================================================================================
// CHANGES vs v8.37:
// 1. OPTIMIZATION: Reduced memory bandwidth in Scanner Hot Path.
//    - Removed redundant write of 'offset[i]' (Start Offset).
//    - Relies on 'offset[i]' being populated as 'offset[i+1]' by the previous iteration.
//    - Only writes 'offset[i]' if a Flag needs setting (Partial Batch) or in Overwrite Mode (Tail).
// 2. SAFETY: Added 'overwrite' param to SCANNER_FLUSH to handle Tail logic correctly.
// ======================================================================================

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
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
#include <sys/syscall.h>
#include <ctype.h>
#include <sys/socket.h>

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
#ifndef MFD_CLOEXEC
#define MFD_CLOEXEC 0x0001U
#endif
#ifndef MFD_ALLOW_SEALING
#define MFD_ALLOW_SEALING 0x0002U
#endif
#ifndef O_TMPFILE
#define O_TMPFILE 020200000
#endif
#ifndef F_ADD_SEALS
#define F_ADD_SEALS 1033
#endif
#ifndef F_SEAL_SEAL
#define F_SEAL_SEAL 0x0001
#endif
#ifndef F_SEAL_SHRINK
#define F_SEAL_SHRINK 0x0002
#endif
#ifndef F_SEAL_GROW
#define F_SEAL_GROW 0x0004
#endif
#ifndef F_SEAL_WRITE
#define F_SEAL_WRITE 0x0008
#endif
#ifndef F_SETPIPE_SZ
#define F_SETPIPE_SZ 1031
#endif

#define FLAG_PARTIAL_BATCH (1ULL << 63)
#define HUGE_PAGE_SIZE (2 * 1024 * 1024)
#define SCANNER_CHUNK_SIZE (2 * 1024 * 1024)
#define RING_SIZE_LOG2 20
#define RING_SIZE      (1ULL << RING_SIZE_LOG2)
#define RING_MASK      (RING_SIZE - 1)
#define CACHE_LINE     256
#define ALIGNED(x)     __attribute__((aligned(x > CACHE_LINE ? x : CACHE_LINE)))
#define MAX_CHUNK_SIZE (32 * 1024 * 1024)
#define DAMPING_OFFSET 6

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

static int g_debug = 0;

#define SYS_CHK(x) do { \
    if ((long)(x) == -1) { \
        if (g_debug) fprintf(stderr, "forkrun [DEBUG] %s:%d: %s failed: %s\n", __FILE__, __LINE__, #x, strerror(errno)); \
    } \
} while(0)

#define FORKRUN_LOADABLES(X) \
    X(ring_init,            ring_init_main,           "ring_init [FLAGS]",              "Initialize ring with config") \
    X(ring_destroy,         ring_destroy_main,        "ring_destroy",                   "Destroy ring") \
    X(ring_scanner,         ring_scanner_main,        "ring_scanner <fd> [spawn_fd]",   "Run scanner") \
    X(ring_claim,           ring_claim_main,          "ring_claim <OFF> <CNT> [BYTES] [FD]", "Claim batch") \
    X(ring_worker,          ring_worker_main,         "ring_worker [inc|dec]",          "Worker control") \
    X(ring_cleanup_waiter,  ring_cleanup_waiter_main, "ring_cleanup_waiter",            "Cleanup waiter") \
    X(ring_ingest,          ring_ingest_main,         "ring_ingest",                    "Signal ingest") \
    X(ring_fallow,          ring_fallow_main,         "ring_fallow <PIPE> <FILE> [dry]","Logical fallow") \
    X(ring_ack,             ring_ack_main,            "ring_ack <FD> <FD_OUT>",         "Ack batch") \
    X(ring_order,           ring_order_main,          "ring_order <FD> <PFX|memfd>",    "Reorder output") \
    X(ring_copy,            ring_copy_main,           "ring_copy <OUT> <IN>",           "Zero-copy ingest") \
    X(ring_signal,          ring_signal_main,         "ring_signal <FD>",               "Signal eventfd") \
    X(lseek,                lseek_main,               "lseek <FD> <OFF>...",            "Seek fd") \
    X(ring_indexer,         ring_indexer_main,        "ring_indexer",                   "NUMA Indexer") \
    X(ring_fetcher,         ring_fetcher_main,        "ring_fetcher",                   "NUMA Fetcher") \
    X(ring_fallow_phys,     ring_fallow_phys_main,    "ring_fallow_phys",               "Physical fallow") \
    X(ring_memfd_create,    ring_memfd_create_main,   "ring_memfd_create <VAR>",        "Create memfd") \
    X(ring_seal,            ring_seal_main,           "ring_seal <FD>",                 "Seal memfd") \
    X(ring_fcntl,           ring_fcntl_main,          "ring_fcntl <FD> <cmd>",          "File control") \
    X(ring_pipe,            ring_pipe_main,           "ring_pipe <ARR|RD> [WR]",        "Create pipe") \
    X(ring_splice,          ring_splice_main,         "ring_splice <IN> <OUT> <OFF> <LEN> [close]", "Splice data") \
    X(ring_list,            ring_list_main,           "ring_list [VAR]",                "List loadables")

#define X(name, func, usage, doc) static int func(int argc, char **argv);
FORKRUN_LOADABLES(X)
#undef X

static void *xmalloc_aligned(size_t size) {
    void *ptr;
    if (posix_memalign(&ptr, HUGE_PAGE_SIZE, size) != 0) ptr = malloc(size);
    return ptr;
}

static SHELL_VAR *bind_var_or_array(const char *name, char *value, int flags) {
    if (!name) return NULL;
    char *lb = strchr(name, '[');
    if (!lb || name[strlen(name) - 1] != ']') {
        return bind_variable(name, value, flags);
    }
    size_t base_len = (size_t)(lb - name);
    char *base_tmp = (char *) xmalloc(base_len + 1);
    memcpy(base_tmp, name, base_len);
    base_tmp[base_len] = '\0';
    size_t idx_len = strlen(lb + 1) - 1; 
    char *idx_tmp = (char *) xmalloc(idx_len + 1);
    memcpy(idx_tmp, lb + 1, idx_len);
    idx_tmp[idx_len] = '\0';
    char *base_s = savestring(base_tmp);
    char *idx_s  = savestring(idx_tmp);
    char *val_s  = savestring(value); 
    xfree(base_tmp); xfree(idx_tmp);
    SHELL_VAR *var = find_variable(base_s);
    if (!var) {
        var = make_new_array_variable(base_s);
        if (!var) {
            builtin_error("failed to create array: %s", base_s);
            xfree(base_s); xfree(idx_s); xfree(val_s);
            return NULL;
        }
    }
    SHELL_VAR *ret = NULL;
    if (assoc_p(var)) {
        ret = bind_assoc_variable(var, base_s, idx_s, val_s, flags);
    } else if (array_p(var)) {
        char *endp = NULL;
        errno = 0;
        long n = strtol(idx_s, &endp, 10);
        if (endp == idx_s || *endp != '\0' || errno == ERANGE) {
            builtin_error("invalid numeric index for indexed array: %s", idx_s);
        } else {
            ret = bind_array_variable(base_s, (arrayind_t)n, val_s, flags);
        }
    } else {
        builtin_error("%s: not an array", base_s);
    }
    xfree(base_s); xfree(idx_s); xfree(val_s);
    return ret;
}

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

static uint64_t get_llc_size() {
#ifdef _SC_LEVEL3_CACHE_SIZE
    long sz = sysconf(_SC_LEVEL3_CACHE_SIZE);
    if (sz > 0) return (uint64_t)sz;
#endif
    int fd = open("/sys/devices/system/cpu/cpu0/cache/index3/size", O_RDONLY);
    if (fd >= 0) {
        char buf[32];
        ssize_t n = read(fd, buf, sizeof(buf)-1);
        close(fd);
        if (n > 0) {
            buf[n] = '\0';
            uint64_t val = 0;
            char *end;
            val = strtoull(buf, &end, 10);
            if (*end == 'K' || *end == 'k') val *= 1024;
            else if (*end == 'M' || *end == 'm') val *= 1024*1024;
            if (val > 0) return val;
        }
    }
    return get_cache_bytes() * 8;
}

static uint64_t get_optimal_chunk_size() {
    uint64_t llc = get_llc_size();
    uint64_t target = llc >> 3; 
    uint64_t mask = HUGE_PAGE_SIZE - 1;
    target = (target + mask) & ~mask;
    if (target < HUGE_PAGE_SIZE) target = HUGE_PAGE_SIZE;
    if (target > MAX_CHUNK_SIZE) target = MAX_CHUNK_SIZE;
    return target;
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

static int xcreate_anon_file(const char *name) {
    const char *force_fallback = get_string_value("FORKRUN_FORCE_FALLBACK");
    bool use_memfd = true;
    if (force_fallback && (strcmp(force_fallback, "1") == 0)) use_memfd = false;
    if (use_memfd) {
        int fd = syscall(__NR_memfd_create, name, MFD_ALLOW_SEALING);
        if (fd >= 0) return fd;
        if (errno == EINVAL) {
            fd = syscall(__NR_memfd_create, name, 0);
            if (fd >= 0) return fd;
        }
    }
    int fd = open("/dev/shm", O_TMPFILE | O_RDWR | O_EXCL, 0600);
    if (fd >= 0) return fd;
    fd = open("/tmp", O_TMPFILE | O_RDWR | O_EXCL, 0600);
    if (fd >= 0) return fd;
    char path[64];
    snprintf(path, sizeof(path), "/dev/shm/forkrun.XXXXXX");
    fd = mkstemp(path);
    if (fd < 0) {
        snprintf(path, sizeof(path), "/tmp/forkrun.XXXXXX");
        fd = mkstemp(path);
    }
    if (fd >= 0) unlink(path); 
    return fd;
}

// --- SHARED STATE & CONFIG ---
struct SharedState {
    uint64_t read_idx ALIGNED(CACHE_LINE);
    uint64_t active_workers;
    uint64_t total_lines_consumed;
    uint32_t active_waiters;
    uint64_t min_idx;
    uint8_t  fallow_active;
    uint8_t  scanner_finished;
    uint64_t tail_idx;
    uint64_t write_idx ALIGNED(CACHE_LINE);
    int64_t  signed_batch_size;
    uint64_t batch_change_idx;
    uint8_t  ingest_complete;
    
    // RUNTIME CONFIGURATION
    uint64_t cfg_w_start;      // --workers0
    uint64_t cfg_w_max;        // --workers-max
    uint64_t cfg_batch_start;  // --lines0 or --bytes0
    uint64_t cfg_batch_max;    // --lines-max or --bytes-max
    uint64_t cfg_limit;        // --limit (Total Items)
    uint64_t cfg_chunk_bytes;  // --bytes (if in byte mode)
    uint64_t cfg_line_max;     // --bytes-max (if in line mode)
    int64_t  cfg_timeout_us;   // --timeout
    uint8_t  mode_byte;        // 1=Byte, 0=Line
    uint8_t  fixed_workers;    // 1=Static W
    uint8_t  fixed_batch;      // 1=Static Batch
    
    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
};

static struct SharedState *state = NULL;
static int evfd_data = -1;
static int evfd_eof  = -1;
static int evfd_ingest_data = -1;
static int evfd_ingest_eof  = -1;
static int fd_escrow[2] = { -1, -1 };
static int evfd_starve = -1;

static __thread bool is_waiting_on_ring = false;
static __thread off_t last_ack_offset = 0; 
static __thread int ack_cached_target_fd = -1;
static __thread int ack_cached_mode = 0; 

struct EscrowPacket { uint64_t idx; uint64_t cnt; };
struct IndexPacket  { uint64_t idx; uint64_t cnt; }; 
struct Interval     { uint64_t s; uint64_t e; struct Interval *next; };
struct PhysPacket   { uint64_t off; uint64_t len; }; 
struct OrderPacket  { uint64_t idx; uint64_t cnt; int32_t fd; uint32_t pad; uint64_t off; uint64_t len; };

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

static inline void cleanup_waiter_state() {
    if (is_waiting_on_ring) {
        if (state && atomic_load_relaxed(&state->active_waiters) > 0) {
            atomic_fetch_sub(&state->active_waiters, 1);
        }
        is_waiting_on_ring = false;
    }
}

// --- INIT: CONFIG PARSING ---
static int ring_init_main(int argc, char **argv) {
    const char *dbg_env = get_string_value("FORKRUN_DEBUG");
    if (dbg_env && (strcmp(dbg_env, "1") == 0 || strcmp(dbg_env, "true") == 0)) {
        g_debug = 1;
        fprintf(stderr, "forkrun [DEBUG] Enabled\n");
    } else {
        g_debug = 0;
    }
    
    if (state != NULL) {
        atomic_store_relaxed(&state->read_idx, 0);
        atomic_store_relaxed(&state->write_idx, 0);
        atomic_store_relaxed(&state->ingest_complete, 0);
        atomic_store_relaxed(&state->total_lines_consumed, 0);
        atomic_store_relaxed(&state->min_idx, 0);
        atomic_store_relaxed(&state->fallow_active, 0);
        atomic_store_relaxed(&state->tail_idx, 0);
        atomic_store_relaxed(&state->scanner_finished, 0);
        
        // Ensure offset[0] is zeroed on reset (though usually assumed)
        state->offset_ring[0] = 0;
        
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
    memset(p, 0, total_size); // Implicitly sets offset_ring[0] = 0

    // --- DEFAULTS ---
    long nproc = sysconf(_SC_NPROCESSORS_ONLN);
    if (nproc < 1) nproc = 1;
    
    char *tv;
    uint64_t env_w_max = nproc;
    uint64_t env_w_start = 1;
    uint64_t env_l_max = 4096;
    uint64_t env_b_max = 0; 
    
    if ((tv=get_string_value("nWorkersMax"))) { long v=atol(tv); if(v>0) env_w_max=v; }
    if ((tv=get_string_value("nWorkers"))) { long v=atol(tv); if(v>0) env_w_start=v; }
    if ((tv=get_string_value("nLinesMax"))) { long v=atol(tv); if(v>0) env_l_max=v; }
    
    uint64_t val_l2 = (get_cache_bytes() * 3) >> 2; 
    uint64_t val_arg = (get_arg_max_bytes() * 3) >> 2; 
    uint64_t def_bytes = (val_l2 < val_arg) ? val_l2 : val_arg;
    if ((tv=get_string_value("nBytesMax"))) {
        if (!strcmp(tv,"L2")) env_b_max=val_l2;
        else if (!strcmp(tv,"ARG_MAX")) env_b_max=val_arg;
        else { long long v=atoll(tv); if(v>0) env_b_max=v; }
    } else {
        env_b_max = def_bytes;
    }

    state->cfg_w_max = env_w_max;
    state->cfg_w_start = env_w_start;
    state->cfg_batch_max = env_l_max;
    state->cfg_batch_start = 1;
    state->cfg_line_max = env_b_max;
    state->cfg_limit = 0; // Infinite
    state->cfg_timeout_us = 0; // Default greedy
    state->mode_byte = 0; 

    // --- FLAG PARSING ---
    const char *out_array_name = NULL;
    int64_t lines_arg = -1;
    int64_t bytes_arg = -1;

    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "--workers-max=", 14) == 0) {
            long v = atol(argv[i]+14); if(v>0) state->cfg_w_max = v;
        } else if (strncmp(argv[i], "--workers0=", 11) == 0) {
            long v = atol(argv[i]+11); if(v>0) state->cfg_w_start = v;
        } else if (strncmp(argv[i], "--workers=", 10) == 0) {
            long v = atol(argv[i]+10); 
            if(v>0) { state->cfg_w_start = v; state->cfg_w_max = v; }
        } else if (strncmp(argv[i], "--lines-max=", 12) == 0) {
            long v = atol(argv[i]+12); if(v>0) state->cfg_batch_max = v;
        } else if (strncmp(argv[i], "--lines0=", 9) == 0) {
            long v = atol(argv[i]+9); if(v>0) state->cfg_batch_start = v;
        } else if (strncmp(argv[i], "--lines=", 8) == 0) {
            lines_arg = atoll(argv[i]+8);
            if (lines_arg > 0) { state->cfg_batch_start=lines_arg; state->cfg_batch_max=lines_arg; }
        } else if (strncmp(argv[i], "--bytes-max=", 12) == 0) {
            long v = atol(argv[i]+12); if(v>0) { state->cfg_line_max=v; state->cfg_chunk_bytes=v; }
        } else if (strncmp(argv[i], "--bytes0=", 9) == 0) {
            long v = atol(argv[i]+9); if(v>0) { state->cfg_batch_start=v; }
        } else if (strncmp(argv[i], "--bytes=", 8) == 0) {
            bytes_arg = atoll(argv[i]+8);
        } else if (strncmp(argv[i], "--limit=", 8) == 0) {
            state->cfg_limit = (uint64_t)atoll(argv[i]+8);
        } else if (strncmp(argv[i], "--timeout=", 10) == 0) {
            state->cfg_timeout_us = atoll(argv[i]+10);
        } else if (strncmp(argv[i], "--greedy", 8) == 0) {
            state->cfg_timeout_us = 0;
        } else if (strncmp(argv[i], "--out=", 6) == 0) {
            out_array_name = argv[i]+6;
        } else if (argv[i][0] != '-') {
            out_array_name = argv[i];
        }
    }

    if (lines_arg == 0 || (lines_arg < 0 && bytes_arg > 0)) {
        state->mode_byte = 1;
        if (bytes_arg > 0) {
            state->cfg_batch_start = bytes_arg;
            state->cfg_batch_max = bytes_arg;
        } else {
            state->cfg_batch_start = env_b_max; 
            state->cfg_batch_max = env_b_max;
        }
        state->cfg_chunk_bytes = state->cfg_batch_max;
        bool timeout_set = false;
        for(int i=1;i<argc;i++) if(strncmp(argv[i],"--timeout",9)==0) timeout_set=true;
        if (!timeout_set) state->cfg_timeout_us = -1;
    } else {
        state->mode_byte = 0;
    }

    state->fixed_workers = (state->cfg_w_start == state->cfg_w_max);
    state->fixed_batch = (state->cfg_batch_start == state->cfg_batch_max);

    if (state->mode_byte) {
        atomic_store_relaxed(&state->signed_batch_size, 1);
    } else {
        atomic_store_relaxed(&state->signed_batch_size, (int64_t)state->cfg_batch_start);
    }

    evfd_data = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
    evfd_eof = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
    evfd_ingest_data = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK);
    evfd_ingest_eof = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
    evfd_starve = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK);
    
    if (pipe(fd_escrow) < 0) return EXECUTION_FAILURE;
    fcntl(fd_escrow[0], F_SETFL, O_NONBLOCK); fcntl(fd_escrow[1], F_SETFL, O_NONBLOCK);
    fcntl(fd_escrow[0], F_SETFD, FD_CLOEXEC); fcntl(fd_escrow[1], F_SETFD, FD_CLOEXEC);
    fcntl(fd_escrow[1], F_SETPIPE_SZ, 1048576);

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", evfd_data); bind_variable("EVFD_RING_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_eof);  bind_variable("EVFD_RING_EOF", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_data); bind_variable("EVFD_RING_INGEST_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_eof);  bind_variable("EVFD_RING_INGEST_EOF", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_starve);      bind_variable("EVFD_RING_STARVE", buf, 0);

    if (out_array_name) {
        SHELL_VAR *v = find_variable(out_array_name);
        if (v && !array_p(v)) { unbind_variable(out_array_name); v = NULL; }
        if (!v) v = make_new_array_variable(out_array_name);
        if (!v) return EXECUTION_FAILURE;
        
        int *created_fds = xmalloc(sizeof(int) * state->cfg_w_max);
        int created_cnt = 0;
        int failure = 0;
        for (long i = 0; i < (long)state->cfg_w_max; i++) {
             int fd = xcreate_anon_file("forkrun_out");
             if (fd >= 0) {
                 created_fds[created_cnt++] = fd;
                 char val[32]; snprintf(val, sizeof(val), "%d", fd);
                 bind_array_element(v, i, val, 0); 
             } else { failure = 1; break; }
        }
        if (failure) { for(int k=0; k<created_cnt; k++) close(created_fds[k]); xfree(created_fds); return EXECUTION_FAILURE; }
        xfree(created_fds);
    }
    return EXECUTION_SUCCESS;
}

static int ring_destroy_main(int argc, char **argv) {
    if (state) { munmap(state, sizeof(struct SharedState)); state = NULL; }
    if (evfd_data >= 0) { close(evfd_data); evfd_data = -1; }
    if (evfd_eof >= 0) { close(evfd_eof); evfd_eof = -1; }
    if (evfd_ingest_data >= 0) { close(evfd_ingest_data); evfd_ingest_data = -1; }
    if (evfd_ingest_eof >= 0) { close(evfd_ingest_eof); evfd_ingest_eof = -1; }
    if (evfd_starve >= 0) { close(evfd_starve); evfd_starve = -1; }
    if (fd_escrow[0] >= 0) { close(fd_escrow[0]); close(fd_escrow[1]); fd_escrow[0] = -1; }
    unbind_variable("EVFD_RING_DATA"); unbind_variable("EVFD_RING_EOF");
    unbind_variable("EVFD_RING_INGEST_DATA"); unbind_variable("EVFD_RING_INGEST_EOF");
    unbind_variable("EVFD_RING_STARVE");
    return EXECUTION_SUCCESS;
}

#define SCANNER_WAKE() do { if(atomic_load_acquire(&state->active_waiters)>0) { uint64_t v=1; SYS_CHK(write(evfd_data,&v,8)); } } while(0)
static uint64_t local_scan_idx = 0;   
static uint64_t local_write_idx = 0;  

static inline void scanner_adaptive_commit(bool force) {
    if (local_scan_idx > local_write_idx) {
        uint64_t W = atomic_load_relaxed(&state->active_workers);
        if (W < 1) W = 1;
        if (force || atomic_load_relaxed(&state->active_waiters) > 0) {
            atomic_store_release(&state->write_idx, local_scan_idx);
            local_write_idx = local_scan_idx;
            SCANNER_WAKE();
            return;
        }
        uint64_t r_idx = atomic_load_relaxed(&state->read_idx);
        uint64_t pending = local_scan_idx - r_idx; 
        uint64_t current_buffer = local_scan_idx - local_write_idx;
        uint64_t target_buffer = 0;
        if (pending >= 10 * W) {
            target_buffer = (W << 2); 
        } else if (pending > (W << 1)) {
            uint64_t linear = pending >> 1;
            uint64_t intermediate = (linear < current_buffer) ? linear : current_buffer;
            if (intermediate > W) target_buffer = intermediate - W;
            else target_buffer = 0;
        } 
        uint64_t target = local_scan_idx - target_buffer;
        if (target > local_write_idx) {
            atomic_store_release(&state->write_idx, target);
            local_write_idx = target;
            SCANNER_WAKE();
        }
    }
}

// Updated SCANNER_FLUSH with Implicit Start optimization + Overwrite Mode
#define SCANNER_FLUSH(cnt, overwrite) do { \
    while(1) { \
        uint64_t limit; \
        if (atomic_load_relaxed(&state->fallow_active)) limit = atomic_load_acquire(&state->min_idx); \
        else limit = atomic_load_acquire(&state->read_idx); \
        if ((local_scan_idx - limit) < RING_SIZE) break; \
        scanner_adaptive_commit(true); \
        usleep(100); \
    } \
    uint64_t pk = (uint64_t)batch_start; \
    if (cnt != L) pk |= FLAG_PARTIAL_BATCH; \
    state->stride_ring[local_scan_idx & RING_MASK] = (uint16_t)cnt; \
    uint64_t next_pk = current_p_offset; \
    state->offset_ring[(local_scan_idx + 1) & RING_MASK] = next_pk; \
    if ((pk & FLAG_PARTIAL_BATCH) || (overwrite)) { \
        state->offset_ring[local_scan_idx & RING_MASK] = pk; \
    } \
    local_scan_idx++; \
    scanner_adaptive_commit(false); \
} while(0)

static int ring_scanner_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    int fd_spawn = (argc >= 3) ? atoi(argv[2]) : -1;
    
    // LOAD CONFIG
    uint64_t L = state->cfg_batch_start;
    uint64_t Lmax = state->cfg_batch_max;
    uint64_t W = state->cfg_w_start;
    uint64_t W_max_val = state->cfg_w_max;
    uint64_t BytesMax = state->cfg_line_max;
    uint64_t limit_items = state->cfg_limit;
    int64_t  timeout_us = state->cfg_timeout_us;
    bool     byte_mode = state->mode_byte;
    bool     fixed_batch = state->fixed_batch;
    bool     fixed_workers = state->fixed_workers;

    // Constants for PID
    uint64_t W2 = fast_log2(W_max_val);
    uint64_t L2 = fast_log2(Lmax);
    uint64_t X_const = fast_log2(W2 + L2) * W2;
    if (X_const == 0) X_const = 1;
    
    local_scan_idx = 0;
    local_write_idx = 0;
    size_t chunk_sz = get_optimal_chunk_size();
    char *buf = xmalloc_aligned(chunk_sz);
    char *p = buf, *end = buf;
    
    uint64_t buf_base_offset = lseek(fd, 0, SEEK_CUR);
    uint64_t batch_start = buf_base_offset;
    int status = 0; 
    
    int phase = 0;
    uint64_t batch_counter = 0;
    uint64_t target_count = 0;
    uint64_t last_calc_us = get_us_time();
    uint64_t last_calc_write = 0;
    uint64_t last_calc_read = 0;
    uint64_t starve_meter = 0; 
    uint64_t stall_meter = 0;
    uint64_t batches_since_calc = 0;
    uint64_t total_scanned = 0;
    uint64_t first_wait_ts = 0;

    atomic_store_relaxed(&state->write_idx, 0);
    atomic_store_relaxed(&state->read_idx, 0);
    atomic_store_relaxed(&state->tail_idx, 0);
    atomic_store_relaxed(&state->active_workers, W);

    bool limit_reached = false;
    uint64_t pending_lines = 0;
    bool force_refill = false;

    // Initial Spawn
    if (fd_spawn >= 0 && W > 0) {
        char sbuf[64];
        int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", W);
        if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
    }

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

    while (status != 1 || p < end) {
        // --- 1. REFILL ---
        if ((p >= end || force_refill) && status != 1) {
            force_refill = false;
            uint64_t current_p_offset = buf_base_offset + (p - buf);
            if (lseek(fd, (off_t)current_p_offset, SEEK_SET) < 0) {} 
            ssize_t n = read(fd, buf, chunk_sz);
            if (n > 0) {
                buf_base_offset = current_p_offset;
                p = buf; end = buf + n;
                status = 0;
            } else {
                struct pollfd pfds[2] = { { .fd = evfd_ingest_data, .events = POLLIN }, { .fd = evfd_ingest_eof,  .events = POLLIN } };
                if (poll(pfds, 2, 0) > 0) {
                    if (pfds[1].revents & POLLIN) atomic_store_release(&state->ingest_complete, 1);
                }
                if (atomic_load_acquire(&state->ingest_complete)) status = 1;
                
                if (status != 1) {
                    bool starving = (atomic_load_relaxed(&state->active_waiters) > 0);
                    scanner_adaptive_commit(starving);
                    SCANNER_WAKE();
                    
                    int poll_timeout = 100;
                    if (starving && timeout_us >= 0) {
                        if (first_wait_ts == 0) first_wait_ts = get_us_time();
                        uint64_t now = get_us_time();
                        if (timeout_us == 0 || (now - first_wait_ts >= (uint64_t)timeout_us)) {
                            poll_timeout = 0;
                        } else {
                            uint64_t rem = (timeout_us - (now - first_wait_ts)) / 1000;
                            poll_timeout = (rem > 100) ? 100 : (int)rem;
                        }
                    } else {
                        first_wait_ts = 0;
                    }

                    int ret = poll(pfds, 2, poll_timeout);
                    if (ret > 0) {
                        if (pfds[0].revents & POLLIN) {
                            uint64_t v; if(read(evfd_ingest_data, &v, 8)){};
                            status = 2; 
                        }
                        if (pfds[1].revents & POLLIN) {
                            atomic_store_release(&state->ingest_complete, 1);
                            status = 1;
                        }
                    }
                }
                if (status == 2) {
                    uint64_t xLim = W + DAMPING_OFFSET;
                    stall_meter = (stall_meter + xLim) >> 1; 
                    if (p < end) force_refill = true;
                    continue; 
                }
            }
        }

        // --- 2. SCANNING ---
        bool flush = false;
        
        if (byte_mode) {
            uint64_t avail = (uint64_t)(end - p);
            uint64_t take = 0;
            
            if (limit_items > 0 && total_scanned >= limit_items) { status=1; break; }

            if (avail >= L) {
                take = L;
                flush = true;
                first_wait_ts = 0;
            } else if (avail > 0) {
                if (status == 1) {
                    take = avail; flush = true;
                } else if (atomic_load_relaxed(&state->active_waiters) > 0) {
                    if (timeout_us == 0) {
                        take = avail; flush = true;
                    } else if (timeout_us > 0) {
                        if (first_wait_ts > 0 && (get_us_time() - first_wait_ts >= (uint64_t)timeout_us)) {
                            take = avail; flush = true; first_wait_ts = 0;
                        }
                    }
                }
            }
            
            if (flush) {
                uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf) + take;
                SCANNER_FLUSH(1, false);
                p += take;
                batch_start += take;
                total_scanned++;
                pending_lines = 0;
            } else {
                force_refill = true;
            }

        } else {
            uint64_t scan_target = (L > pending_lines) ? (L - pending_lines) : 0;
            if (limit_items > 0) {
                uint64_t rem = limit_items - total_scanned;
                if (scan_target > rem) scan_target = rem;
                if (rem == 0) { status = 1; scan_target = 0; }
            }
            if (scan_target == 0 && !limit_reached && status != 1) scan_target = 1;
            
            uint64_t found = SCAN_BATCH(scan_target);
            pending_lines += found;
            total_scanned += found;
            
            if (limit_items > 0 && total_scanned >= limit_items) status = 1;
            
            if (pending_lines > 0) {
                bool starvation = (atomic_load_relaxed(&state->active_waiters) > 0);
                if (pending_lines >= L || status == 1 || limit_reached) {
                    flush = true;
                } else if (starvation) {
                    if (timeout_us == 0) flush = true;
                    else if (timeout_us > 0 && first_wait_ts > 0 && (get_us_time() - first_wait_ts >= (uint64_t)timeout_us)) {
                        flush = true;
                    }
                }
                
                if (flush) {
                    uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                    SCANNER_FLUSH(pending_lines, false);
                    batch_start = current_p_offset;
                    pending_lines = 0;
                    first_wait_ts = 0;
                } else {
                    force_refill = true;
                }
            } else {
                force_refill = true;
            }
        }

        // --- 3. ADAPTATION ---
        if (flush) {
            batch_counter++;
            batches_since_calc++;
            
            bool starvation = (atomic_load_relaxed(&state->active_waiters) > 0);
            uint64_t xLim = W + DAMPING_OFFSET;
            if (starvation) starve_meter = (starve_meter + xLim) >> 1;
            else starve_meter >>= 1;
            stall_meter >>= 1; 
            
            target_count = W * 4; if (target_count < 4) target_count = 4;

            if (!fixed_batch && !byte_mode) {
                if (phase == 0) {
                    if (batch_counter >= target_count) { phase = 1; batch_counter = 0; }
                } else if (phase == 1) {
                    if (status == 2) phase = 2; 
                    else if (batch_counter >= target_count) {
                        L *= 2;
                        if (L >= Lmax) { L = Lmax; phase = 2; }
                        atomic_store_release(&state->batch_change_idx, local_scan_idx);
                        atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                        batch_counter = 0;
                    }
                }
            }

            uint64_t now_us = get_us_time();
            if (now_us - last_calc_us > 5000 || batches_since_calc >= W) {
                uint64_t d_in  = local_write_idx - last_calc_write;
                uint64_t r_con = atomic_load_relaxed(&state->total_lines_consumed);
                uint64_t d_out = r_con - last_calc_read;
                last_calc_write = local_write_idx;
                last_calc_read  = r_con;
                last_calc_us    = now_us;
                batches_since_calc = 0;
                
                if (!fixed_workers && W < W_max_val) {
                    uint64_t r_idx = atomic_load_relaxed(&state->read_idx);
                    uint64_t backlog = local_scan_idx - r_idx;
                    bool spawn = false;
                    uint64_t grow = 0;

                    if (fixed_batch) {
                        if (backlog > W && starvation == 0) spawn = true; 
                    } else {
                        if (d_out > 0) {
                            uint64_t rate = d_out / W; if(rate==0) rate=1;
                            uint64_t w_ideal = d_in / rate;
                            if (w_ideal > W) spawn = true;
                        }
                    }

                    if (spawn) {
                        grow = 1; 
                        if (!fixed_batch) grow = (W + 1) / 2;
                        if (W + grow > W_max_val) grow = W_max_val - W;
                        
                        if (grow > 0 && fd_spawn >= 0) {
                            char sbuf[64];
                            int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", grow);
                            if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
                            W += grow;
                            atomic_store_relaxed(&state->active_workers, W);
                        }
                    }
                }

                if (!fixed_batch && !byte_mode && phase == 2) {
                    uint64_t r_idx = atomic_load_relaxed(&state->read_idx);
                    int64_t backlog = (int64_t)local_write_idx - (int64_t)r_idx;
                    if (backlog < 0) backlog = 0;
                    uint64_t l_target = (backlog / W);
                    if (l_target > Lmax) l_target = Lmax;
                    if (l_target < 1) l_target = 1;
                    
                    if (l_target > L) {
                        L = l_target;
                        atomic_store_release(&state->batch_change_idx, local_scan_idx);
                        atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                    } else if (l_target < L && starve_meter >= (xLim - 3)) {
                        L = (L + l_target) / 2;
                        if (L < 1) L = 1;
                        atomic_store_release(&state->batch_change_idx, local_scan_idx);
                        atomic_store_release(&state->signed_batch_size, -(int64_t)L);
                        starve_meter = 0; 
                    }
                }
            }
        }
    }

    if (!byte_mode) {
        uint64_t L_tail = pending_lines;
        char *p_scan = p;
        while(p_scan < end) {
            char *nl = memchr(p_scan, '\n', end - p_scan);
            if (nl) { L_tail++; p_scan = nl + 1; }
            else { if (p_scan < end) L_tail++; break; }
        }
        if (local_scan_idx > local_write_idx) {
            for (uint64_t i = local_write_idx; i < local_scan_idx; i++) L_tail += state->stride_ring[i & RING_MASK];
        }
        if (fd_spawn >= 0) {
            uint64_t W_curr = atomic_load_relaxed(&state->active_workers);
            if (W_curr < W_max_val) {
                uint64_t r_idx = atomic_load_relaxed(&state->read_idx);
                uint64_t backlog = 0;
                if (local_scan_idx > r_idx) backlog = local_scan_idx - r_idx;
                uint64_t W_target = (backlog > W_max_val) ? W_max_val : backlog;
                if (W_target > W_curr) {
                    uint64_t needed = W_target - W_curr;
                    if (needed > 0) {
                        char sbuf[64];
                        int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", needed);
                        if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
                        W += needed;
                        atomic_store_relaxed(&state->active_workers, W);
                    }
                }
            }
        }
        uint64_t tail_start_offset;
        if (local_scan_idx > local_write_idx) tail_start_offset = state->offset_ring[local_write_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
        else tail_start_offset = batch_start;
        local_scan_idx = local_write_idx;
        int64_t buf_rel = (int64_t)tail_start_offset - (int64_t)buf_base_offset;
        if (buf_rel >= 0 && buf_rel < (int64_t)chunk_sz) {
             p = buf + buf_rel;
             batch_start = tail_start_offset;
        } else {
             lseek(fd, (off_t)tail_start_offset, SEEK_SET);
             buf_base_offset = tail_start_offset;
             batch_start = tail_start_offset;
             ssize_t n = read(fd, buf, chunk_sz);
             p = buf;
             end = buf + (n > 0 ? n : 0);
        }
        uint64_t R = 1;
        if (L > 0) {
            uint64_t inner_log = fast_log2(2 + L);
            R = fast_log2(2 + inner_log);
        }
        if (R < 1) R = 1;
        uint64_t L_tail_done = 0;
        atomic_store_release(&state->tail_idx, local_write_idx);
        
        while (L_tail_done < L_tail) {
            uint64_t target = 0;
            if (L_tail > 0) target = (L * (L_tail - L_tail_done)) / L_tail;
            uint64_t min_batch = L / R; 
            if (min_batch < 1) min_batch = 1;
            if (target < min_batch) target = min_batch;
            
            uint64_t lines_found = 0;
            while (lines_found < target && (lines_found + L_tail_done) < L_tail) {
                if (p >= end) {
                    uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                    lseek(fd, (off_t)current_p_offset, SEEK_SET);
                    ssize_t n = read(fd, buf, chunk_sz);
                    if (n > 0) { buf_base_offset = current_p_offset; p = buf; end = buf + n; }
                    else break; 
                }
                char *nl = memchr(p, '\n', end - p);
                if (nl) { lines_found++; p = nl + 1; }
                else {
                    uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                    lseek(fd, (off_t)current_p_offset, SEEK_SET);
                    ssize_t n = read(fd, buf, chunk_sz);
                    if (n > 0) { buf_base_offset = current_p_offset; p = buf; end = buf + n; }
                    else { p = end; break; }
                }
            }
            if (lines_found < target && (lines_found + L_tail_done) < L_tail) {
                 if (p >= end) {
                     uint64_t remainder = L_tail - L_tail_done - lines_found;
                     lines_found += remainder;
                 }
            }
            if (lines_found > 0) {
                uint64_t pk = (uint64_t)batch_start;
                if (lines_found != L) pk |= FLAG_PARTIAL_BATCH;
                while(1) {
                     uint64_t limit;
                     if (atomic_load_relaxed(&state->fallow_active)) limit = atomic_load_acquire(&state->min_idx); 
                     else limit = atomic_load_acquire(&state->read_idx); 
                     if ((local_scan_idx - limit) < RING_SIZE) break;
                     SCANNER_WAKE(); usleep(100);
                }
                uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                // Force Overwrite Mode for Tail
                SCANNER_FLUSH(lines_found, true);
                batch_start = current_p_offset;
                L_tail_done += lines_found;
            } else break; 
        }
    }

    uint64_t final_sentinel = buf_base_offset + (uint64_t)(p - buf);
    state->offset_ring[local_scan_idx & RING_MASK] = (uint64_t)final_sentinel | FLAG_PARTIAL_BATCH;
    local_scan_idx++;
    atomic_store_release(&state->write_idx, local_scan_idx);
    atomic_store_release(&state->scanner_finished, 1);
    SCANNER_WAKE();
    if (fd_spawn >= 0) SYS_CHK(write(fd_spawn, "x\n", 2));
    uint64_t eof_sig = 999999; SYS_CHK(write(evfd_eof, &eof_sig, 8));
    free(buf);
    return EXECUTION_SUCCESS;
}

static bool is_variable_name(const char *s) {
    if (!s || !*s) return false;
    if (isdigit(s[0])) return false; 
    return true;
}

static int ring_claim_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    const char *v_off = argv[1];
    const char *v_cnt = argv[2];
    const char *v_bytes = NULL;
    int fd_read = -1;

    if (argc >= 4) {
        if (is_variable_name(argv[3])) {
            v_bytes = argv[3];
            if (argc >= 5) fd_read = atoi(argv[4]);
        } else {
            fd_read = atoi(argv[3]);
        }
    }

    uint64_t my_read_idx;
    uint64_t claim_count = 1;
    int spin = 0;
    
restart_loop:
    while (1) {
        struct EscrowPacket ep;
        if (fd_escrow[0] >= 0 && read(fd_escrow[0], &ep, sizeof(ep)) == sizeof(ep)) {
            my_read_idx = ep.idx;
            claim_count = ep.cnt;
            break; 
        }
        uint64_t w_snap = atomic_load_acquire(&state->write_idx);
        uint64_t r_curr = atomic_load_relaxed(&state->read_idx);
        if (r_curr < w_snap) {
            int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size); 
            claim_count = 1;
            if (sbatch < 0) {
                uint64_t t_start = atomic_load_acquire(&state->tail_idx);
                if (t_start != 0 && r_curr >= t_start) {
                     claim_count = 1;
                     if (sbatch < 0) {
                         int64_t abs_L = -sbatch;
                         atomic_store_relaxed(&state->signed_batch_size, abs_L);
                     }
                } 
                else {
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
            }
            if (r_curr + claim_count > w_snap) claim_count = w_snap - r_curr;
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
        if (atomic_load_acquire(&state->scanner_finished)) {
            if (atomic_fetch_sub(&state->active_workers, 1) == 1) {
                 return 2; 
            }
            bind_var_or_array(v_cnt, "0", 0);
            return 1;
        }
        if (spin < 100) { cpu_relax(); spin++; continue; }
        atomic_fetch_add(&state->active_waiters, 1);
        is_waiting_on_ring = true;
        struct pollfd pfds[3] = { 
            { .fd = evfd_data, .events = POLLIN }, 
            { .fd = evfd_eof,  .events = POLLIN }, 
            { .fd = fd_escrow[0], .events = POLLIN } 
        };
        while(1) {
             if (atomic_load_acquire(&state->write_idx) > atomic_load_relaxed(&state->read_idx)) break;
             poll(pfds, 3, -1);
             if (pfds[2].revents & POLLIN) break; 
             if (pfds[0].revents) { uint64_t v; if(read(evfd_data, &v, 8)){}; break; }
             if (pfds[1].revents) break; 
        }
        cleanup_waiter_state();
        spin = 0;
    }

    uint64_t w_curr = atomic_load_acquire(&state->write_idx);
    if (my_read_idx + claim_count > w_curr) {
         if (atomic_load_acquire(&state->scanner_finished)) {
             int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
             if (diff < 0) diff = 0;
             claim_count = (uint64_t)diff;
             if (claim_count == 0) { spin = 0; goto restart_loop; }
         } 
         else {
             atomic_fetch_add(&state->active_waiters, 1);
             is_waiting_on_ring = true;
             while (1) {
                 w_curr = atomic_load_acquire(&state->write_idx);
                 if (w_curr > my_read_idx) {
                     uint64_t avail = w_curr - my_read_idx;
                     if (avail < claim_count) {
                         struct EscrowPacket ep = { .idx = my_read_idx + avail, .cnt = claim_count - avail };
                         if (write(fd_escrow[1], &ep, sizeof(ep)) == sizeof(ep)) {
                             claim_count = avail;
                             uint64_t one=1; SYS_CHK(write(evfd_data, &one, 8));
                             break;
                         }
                     } else { break; }
                 }
                 if (atomic_load_acquire(&state->scanner_finished)) {
                     int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
                     if (diff < 0) diff = 0;
                     claim_count = (uint64_t)diff;
                     break;
                 }
                 struct pollfd pfds[2] = { { .fd = evfd_data, .events = POLLIN }, { .fd = evfd_eof, .events = POLLIN } };
                 poll(pfds, 2, -1);
                 if (pfds[0].revents) { uint64_t v; if(read(evfd_data, &v, 8)){}; }
                 if (pfds[1].revents) break; 
             }
             cleanup_waiter_state();
             if (claim_count == 0) { spin = 0; goto restart_loop; }
         }
    }

    uint64_t final_lines = 0;
    uint64_t final_offset = state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
    uint64_t final_bytes = 0;

    if (claim_count == 1) {
        int64_t sbatch_now = atomic_load_relaxed(&state->signed_batch_size);
        uint64_t tail_start = atomic_load_acquire(&state->tail_idx);
        bool in_tail = (tail_start != 0 && my_read_idx >= tail_start);
        if (!in_tail && sbatch_now > 0 && !(state->offset_ring[my_read_idx & RING_MASK] & FLAG_PARTIAL_BATCH)) {
            final_lines = sbatch_now;
        } else {
            final_lines = state->stride_ring[my_read_idx & RING_MASK];
        }
        uint64_t end_off = state->offset_ring[(my_read_idx + 1) & RING_MASK] & ~FLAG_PARTIAL_BATCH;
        final_bytes = end_off - final_offset;
    } else {
        for (uint64_t i = 0; i < claim_count; i++) {
            final_lines += state->stride_ring[(my_read_idx + i) & RING_MASK];
        }
        uint64_t start = state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
        uint64_t end   = state->offset_ring[(my_read_idx + claim_count) & RING_MASK] & ~FLAG_PARTIAL_BATCH;
        final_bytes = end - start;
    }
    
    atomic_fetch_add(&state->total_lines_consumed, final_lines);
    
    char buf[64];
    u64toa(final_offset, buf); bind_var_or_array(v_off, buf, 0);
    u64toa(final_lines, buf); bind_var_or_array(v_cnt, buf, 0);
    if (v_bytes) { u64toa(final_bytes, buf); bind_var_or_array(v_bytes, buf, 0); }

    u64toa(my_read_idx, buf); bind_variable("RING_BATCH_IDX", buf, 0);
    u64toa(claim_count, buf); bind_variable("RING_BATCH_SLOTS", buf, 0);
    
    if (fd_read >= 0 && final_lines > 0) {
        if (lseek(fd_read, (off_t)final_offset, SEEK_SET) == (off_t)-1) {
            if (g_debug) fprintf(stderr, "forkrun [DEBUG] ring_claim lseek failed: %s\n", strerror(errno));
        }
    }
    return 0;
}

static int ring_ack_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd_fallow = atoi(argv[1]);
    int fd_target = (argc >= 3) ? atoi(argv[2]) : -1;
    struct IndexPacket ip;
    const char *s_idx = get_string_value("RING_BATCH_IDX");
    const char *s_cnt = get_string_value("RING_BATCH_SLOTS");
    if (!s_idx || !s_cnt) return EXECUTION_SUCCESS;
    ip.idx = (uint64_t)atoll(s_idx);
    ip.cnt = (uint64_t)atoll(s_cnt);
    if (fd_fallow > 0) SYS_CHK(write(fd_fallow, &ip, sizeof(ip)));
    if (fd_target > 0) {
        if (fd_target != ack_cached_target_fd) {
            ack_cached_target_fd = fd_target;
            struct stat st;
            if (fstat(fd_target, &st) == 0 && S_ISREG(st.st_mode)) {
                ack_cached_mode = 1; 
            } else {
                ack_cached_mode = 2; 
            }
        }
        if (ack_cached_mode == 1) {
            const char *s_order_pipe = get_string_value("FD_ORDER_PIPE");
            if (s_order_pipe) {
                int fd_pipe = atoi(s_order_pipe);
                off_t curr = lseek(fd_target, 0, SEEK_CUR);
                if (curr == (off_t)-1) {
                    if (g_debug) fprintf(stderr, "forkrun [DEBUG] ring_ack lseek failed: %s\n", strerror(errno));
                    return EXECUTION_FAILURE;
                }
                uint64_t len = (uint64_t)(curr - last_ack_offset);
                struct OrderPacket op;
                op.idx = ip.idx;
                op.cnt = ip.cnt;
                op.fd  = fd_target;
                op.off = (uint64_t)last_ack_offset;
                op.len = len;
                op.pad = 0;
                SYS_CHK(write(fd_pipe, &op, sizeof(op)));
                last_ack_offset = curr;
            }
        } else {
            SYS_CHK(write(fd_target, &ip, sizeof(ip)));
        }
    }
    return EXECUTION_SUCCESS;
}

static int ring_copy_chunk(int fd_in, int fd_out, off_t off, size_t len) {
    const size_t BUF_SIZE = 65536;
    char *buf = xmalloc(BUF_SIZE); 
    size_t total_read = 0;
    while (total_read < len) {
        size_t to_read = (len - total_read > BUF_SIZE) ? BUF_SIZE : (len - total_read);
        ssize_t r = pread(fd_in, buf, to_read, off + total_read);
        if (r < 0) { if (errno == EINTR) continue; free(buf); return -1; }
        if (r == 0) break; 
        char *write_ptr = buf;
        size_t to_write = r;
        while (to_write > 0) {
            ssize_t w = write(fd_out, write_ptr, to_write);
            if (w < 0) { if (errno == EINTR) continue; free(buf); return -1; }
            write_ptr += w;
            to_write -= w;
        }
        total_read += r;
    }
    free(buf);
    return (total_read == len) ? 0 : -1;
}

struct BufferedPacket { struct OrderPacket pkt; struct BufferedPacket *next; };

static int ring_order_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    bool memfd_mode = (strcmp(argv[2], "memfd") == 0);
    const char *prefix = argv[2]; 

    bool use_zerocopy = false;
    struct stat st_out;
    if (fstat(1, &st_out) == 0 && S_ISREG(st_out.st_mode)) {
        use_zerocopy = true;
    }

    if (!memfd_mode) {
        struct Interval *head = NULL;
        uint64_t next_idx = 0;
        struct IndexPacket ip;
        char path[256];
        while (read(fd_in, &ip, sizeof(ip)) == sizeof(ip)) {
            if (ip.idx == next_idx) {
                snprintf(path, sizeof(path), "%s.%lu", prefix, ip.idx);
                int fd_file = open(path, O_RDONLY);
                if (fd_file >= 0) {
                    off_t offset = 0; struct stat st;
                    if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                        while (offset < st.st_size) {
                            ssize_t sent = sendfile(1, fd_file, &offset, st.st_size - offset);
                            if (sent < 0) {
                                if (errno == EINTR) continue;
                                if (errno == EINVAL || errno == ENOSYS || errno == ENOTSOCK || errno == EBADF) {
                                    char buf[32768]; ssize_t n; lseek(fd_file, offset, SEEK_SET);
                                    while ((n = read(fd_file, buf, sizeof(buf))) > 0) write(1, buf, n);
                                }
                                break; 
                            }
                        }
                    }
                    close(fd_file); unlink(path);
                }
                next_idx += ip.cnt;
                while (head && head->s == next_idx) {
                    struct Interval *tmp = head;
                    snprintf(path, sizeof(path), "%s.%lu", prefix, tmp->s);
                    fd_file = open(path, O_RDONLY);
                    if (fd_file >= 0) {
                        off_t offset = 0; struct stat st;
                        if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                            while (offset < st.st_size) {
                                ssize_t sent = sendfile(1, fd_file, &offset, st.st_size - offset);
                                if (sent < 0) {
                                    if (errno == EINTR) continue;
                                    if (errno == EINVAL || errno == ENOSYS || errno == ENOTSOCK || errno == EBADF) {
                                        char buf[32768]; ssize_t n; lseek(fd_file, offset, SEEK_SET);
                                        while ((n = read(fd_file, buf, sizeof(buf))) > 0) write(1, buf, n);
                                    }
                                    break; 
                                }
                            }
                        }
                        close(fd_file); unlink(path);
                    }
                    next_idx = tmp->e; head = tmp->next; free(tmp);
                }
            } else {
                struct Interval *n = xmalloc(sizeof(struct Interval));
                n->s = ip.idx; n->e = ip.idx + ip.cnt;
                struct Interval **curr = &head;
                while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
                n->next = *curr; *curr = n;
            }
        }
    } else {
        struct BufferedPacket *head = NULL;
        uint64_t next_idx = 0;
        struct OrderPacket ops[64];
        struct pollfd pfd;
        pfd.fd = fd_in;
        pfd.events = POLLIN; 

        while(1) {
            int ret = poll(&pfd, 1, -1);
            if (ret < 0) { if (errno == EINTR) continue; break; }
            if (pfd.revents & (POLLIN | POLLHUP | POLLERR)) {
                ssize_t n_read = read(fd_in, ops, sizeof(ops));
                if (n_read == 0) break;
                if (n_read < 0) { if (errno == EAGAIN || errno == EINTR) continue; break; }
                int count = n_read / sizeof(struct OrderPacket);
                for (int i = 0; i < count; i++) {
                    struct OrderPacket *op = &ops[i];
                    if (op->idx == next_idx) {
                        off_t offset = (off_t)op->off;
                        
                        if (use_zerocopy) {
                            sendfile(1, op->fd, &offset, op->len);
                        } else {
                            ring_copy_chunk(op->fd, 1, offset, op->len);
                        }
                        
                        off_t aligned_start = (op->off / 4096) * 4096;
                        off_t aligned_len = (op->off + op->len) - aligned_start;
                        fallocate(op->fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, aligned_len);
                        
                        next_idx += op->cnt;
                        while (head && head->pkt.idx == next_idx) {
                            struct BufferedPacket *tmp = head;
                            offset = (off_t)tmp->pkt.off;
                            
                            if (use_zerocopy) sendfile(1, tmp->pkt.fd, &offset, tmp->pkt.len);
                            else ring_copy_chunk(tmp->pkt.fd, 1, offset, tmp->pkt.len);
                            
                            aligned_start = (tmp->pkt.off / 4096) * 4096;
                            aligned_len = (tmp->pkt.off + tmp->pkt.len) - aligned_start;
                            fallocate(tmp->pkt.fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, aligned_len);
                            
                            next_idx += tmp->pkt.cnt;
                            head = tmp->next;
                            xfree(tmp); 
                        }
                    } else {
                        struct BufferedPacket *n = xmalloc(sizeof(struct BufferedPacket));
                        n->pkt = *op;
                        struct BufferedPacket **curr = &head;
                        while (*curr && (*curr)->pkt.idx < op->idx) curr = &((*curr)->next);
                        n->next = *curr;
                        *curr = n;
                    }
                }
            }
        }
        while (head) { struct BufferedPacket *tmp = head; head = head->next; xfree(tmp); }
    }
    return EXECUTION_SUCCESS;
}

static int ring_copy_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int outfd = atoi(argv[1]);
    int infd  = (argc == 3) ? atoi(argv[2]) : 0;
    size_t chunk = get_optimal_chunk_size();
    struct stat st;
    uint64_t oom_threshold = 134217728; 
    long threshold_div = 128;
    const char *s_div = get_string_value("RING_INGEST_DIVISOR");
    if (s_div) { long v = atol(s_div); if (v > 0) threshold_div = v; }
    struct sysinfo si_init;
    if (sysinfo(&si_init) == 0) {
        uint64_t mu = (uint64_t)si_init.mem_unit ? si_init.mem_unit : 1;
        uint64_t total = (uint64_t)si_init.totalram * mu;
        uint64_t t = total / (uint64_t)threshold_div;
        if (t > oom_threshold) oom_threshold = t;
    }
    uint64_t total_moved = 0;
    uint64_t next_check = 16 * 1024 * 1024;
    
    if (fstat(infd, &st) == 0 && S_ISREG(st.st_mode)) {
        off_t off = 0;
        while (off < st.st_size) {
             if (total_moved > next_check) {
                struct sysinfo si;
                if (sysinfo(&si) == 0) {
                    uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                    uint64_t free_b = (uint64_t)si.freeram * mu;
                    if (free_b < oom_threshold) {
                        if (state && atomic_load_relaxed(&state->fallow_active)) {
                            int r = 0;
                            while (free_b < oom_threshold && r < 10000) { usleep(100); sysinfo(&si); free_b = (uint64_t)si.freeram * mu; r++; }
                        }
                    }
                }
                next_check += 16 * 1024 * 1024;
            }
             loff_t current_off = off;
             size_t to_copy = (size_t)(st.st_size - off);
             if (to_copy > chunk) to_copy = chunk;
             size_t copied_in_chunk = 0;
             while (copied_in_chunk < to_copy) {
                 ssize_t n = copy_file_range(infd, &current_off, outfd, NULL, to_copy - copied_in_chunk, 0);
                 if (n < 0) { 
                     if (errno == EINTR) continue;
                     if (errno == EXDEV || errno == EINVAL || errno == ENOSYS || errno == EOPNOTSUPP) break; 
                     return EXECUTION_FAILURE; 
                 }
                 if (n == 0) break; 
                 copied_in_chunk += n;
             }
             if (copied_in_chunk == 0 && (st.st_size - off > 0)) break; 
             off += copied_in_chunk;
             if (evfd_ingest_data >= 0) { uint64_t v=1; SYS_CHK(write(evfd_ingest_data, &v, 8)); }
             total_moved += copied_in_chunk;
        }
        while(off < st.st_size) {
            if (total_moved > next_check) {
                struct sysinfo si;
                if (sysinfo(&si) == 0) {
                    uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                    uint64_t free_b = (uint64_t)si.freeram * mu;
                    if (free_b < oom_threshold) {
                        if (state && atomic_load_relaxed(&state->fallow_active)) {
                            int r = 0;
                            while (free_b < oom_threshold && r < 10000) { usleep(100); sysinfo(&si); free_b = (uint64_t)si.freeram * mu; r++; }
                        }
                    }
                }
                next_check += 16 * 1024 * 1024;
            }
            ssize_t n = sendfile(outfd, infd, &off, chunk);
            if (n < 0) { if (errno == EINTR) continue; break; }
            if (n == 0) break;
            if (evfd_ingest_data >= 0) { uint64_t v=1; SYS_CHK(write(evfd_ingest_data, &v, 8)); }
            total_moved += n;
        }
        if (off < st.st_size) {
            int pfd[2];
            if (pipe(pfd) == 0) {
                fcntl(pfd[1], F_SETPIPE_SZ, 1048576); 
                while (off < st.st_size) {
                    if (total_moved > next_check) {
                        struct sysinfo si;
                        if (sysinfo(&si) == 0) {
                            uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                            uint64_t free_b = (uint64_t)si.freeram * mu;
                            if (free_b < oom_threshold) {
                                if (state && atomic_load_relaxed(&state->fallow_active)) {
                                    int r = 0;
                                    while (free_b < oom_threshold && r < 10000) { usleep(100); sysinfo(&si); free_b = (uint64_t)si.freeram * mu; r++; }
                                }
                            }
                        }
                        next_check += 16 * 1024 * 1024;
                    }
                    ssize_t s1 = splice(infd, &off, pfd[1], NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
                    if (s1 <= 0) break; 
                    size_t written = 0;
                    while (written < (size_t)s1) {
                        ssize_t s2 = splice(pfd[0], NULL, outfd, NULL, s1 - written, SPLICE_F_MOVE|SPLICE_F_MORE);
                        if (s2 <= 0) break;
                        written += s2;
                    }
                    if (evfd_ingest_data >= 0) { uint64_t v=1; SYS_CHK(write(evfd_ingest_data, &v, 8)); }
                    total_moved += written;
                }
                close(pfd[0]); close(pfd[1]);
            }
        }
    } else {
        ssize_t n = splice(infd, NULL, outfd, NULL, chunk, SPLICE_F_MOVE|SPLICE_F_MORE);
        if (n >= 0) {
            do {
                if (n > 0 && evfd_ingest_data >= 0) { uint64_t v=1; SYS_CHK(write(evfd_ingest_data, &v, 8)); }
                total_moved += n;
                if (total_moved > next_check) {
                    struct sysinfo si;
                    if (sysinfo(&si) == 0) {
                        uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                        uint64_t free_b = (uint64_t)si.freeram * mu;
                        if (free_b < oom_threshold) {
                            if (state && atomic_load_relaxed(&state->fallow_active)) {
                                int r = 0;
                                while (free_b < oom_threshold && r < 10000) { usleep(100); sysinfo(&si); free_b = (uint64_t)si.freeram * mu; r++; }
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
                if (evfd_ingest_data >= 0) { uint64_t v=1; SYS_CHK(write(evfd_ingest_data, &v, 8)); }
                total_moved += n;
                if (total_moved > next_check) {
                    struct sysinfo si;
                    if (sysinfo(&si) == 0) {
                        uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
                        uint64_t free_b = (uint64_t)si.freeram * mu;
                        if (free_b < oom_threshold) { 
                            if (state && atomic_load_relaxed(&state->fallow_active)) {
                                int r = 0;
                                while (free_b < oom_threshold && r < 10000) { usleep(100); sysinfo(&si); free_b = (uint64_t)si.freeram * mu; r++; }
                            }
                        }
                    }
                    next_check += 16 * 1024 * 1024;
                }
            }
            close(pipefd[0]); close(pipefd[1]);
        }
    }
    if (evfd_ingest_eof >= 0) {
        uint64_t val = 1;
        write(evfd_ingest_eof, &val, 8);
    }
    return EXECUTION_SUCCESS;
}

static int ring_signal_main(int argc, char **argv) {
    int fd = evfd_ingest_eof; 
    if (argc >= 2) fd = atoi(argv[1]);
    uint64_t val = 1;
    SYS_CHK(write(fd, &val, 8));
    return EXECUTION_SUCCESS;
}

static int ring_fallow_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    int fd_file = atoi(argv[2]);
    bool dry_run = (argc > 3 && strcmp(argv[3], "dry") == 0);
    if (state) atomic_store_release(&state->fallow_active, 1);
    struct Interval *head = NULL;
    uint64_t next_idx = 0; 
    struct IndexPacket ops[64];
    struct pollfd pfd;
    pfd.fd = fd_in;
    pfd.events = POLLIN; 
    while (1) {
        int ret = poll(&pfd, 1, -1);
        if (ret < 0) { if (errno == EINTR) continue; break; }
        if (pfd.revents & (POLLIN | POLLHUP | POLLERR)) {
            ssize_t n_read = read(fd_in, ops, sizeof(ops));
            if (n_read == 0) break;
            if (n_read < 0) { if (errno == EAGAIN || errno == EINTR) continue; break; }
            int count = n_read / sizeof(struct IndexPacket);
            for (int i=0; i<count; i++) {
                struct IndexPacket *ip = &ops[i];
                if (ip->idx == next_idx) {
                    next_idx += ip->cnt;
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
                        if (aligned > 0) fallocate(fd_file, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, 0, aligned);
                    }
                } else if (ip->idx > next_idx) {
                    struct Interval *n = xmalloc(sizeof(struct Interval));
                    n->s = ip->idx; n->e = ip->idx + ip->cnt;
                    struct Interval **curr = &head;
                    while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
                    n->next = *curr; *curr = n;
                }
            }
        }
    }
    while(head) { struct Interval *tmp = head; head = head->next; free(tmp); }
    return EXECUTION_SUCCESS;
}

static int ring_ingest_main(int argc, char **argv) { (void)argc; (void)argv; if (state) atomic_store_release(&state->ingest_complete, 1); return EXECUTION_SUCCESS; }
static int ring_worker_main(int argc, char **argv) {
    if (argc!=2) return EXECUTION_FAILURE;
    if (!strcmp(argv[1],"inc")) atomic_fetch_add(&state->active_workers,1);
    else if (!strcmp(argv[1],"dec")) { cleanup_waiter_state(); atomic_fetch_sub(&state->active_workers, 1); }
    return EXECUTION_SUCCESS;
}
static int ring_cleanup_waiter_main(int argc, char **argv) { (void)argc; (void)argv; cleanup_waiter_state(); return EXECUTION_SUCCESS; }
static int lseek_main(int argc, char ** argv) { if (argc < 3 || argc > 5) return EXECUTION_FAILURE; int fd = atoi(argv[1]); off_t off = atoll(argv[2]); int whence = SEEK_CUR; if (argc > 3) { if (!strcmp(argv[3], "SEEK_SET")) whence = SEEK_SET; else if (!strcmp(argv[3], "SEEK_END")) whence = SEEK_END; } off_t no = lseek(fd, off, whence); if (no == -1) return EXECUTION_FAILURE; if (argc >= 4 && argv[argc-1][0]) { char buf[32]; snprintf(buf,32,"%lld",(long long)no); bind_var_or_array(argv[argc-1], buf, 0); } else printf("%lld\n", (long long)no); return EXECUTION_SUCCESS; }

static int ring_memfd_create_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    const char *var_name = argv[1];
    int fd = xcreate_anon_file("forkrun_input");
    if (fd < 0) { builtin_error("memfd_create failed: %s", strerror(errno)); return EXECUTION_FAILURE; }
    char val[32]; snprintf(val, sizeof(val), "%d", fd); bind_var_or_array(var_name, val, 0);
    return EXECUTION_SUCCESS;
}

static int ring_seal_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    int seals = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
    if (fcntl(fd, F_ADD_SEALS, seals) == -1) { if (g_debug) fprintf(stderr, "forkrun [DEBUG] ring_seal failed: %s\n", strerror(errno)); return EXECUTION_FAILURE; }
    return EXECUTION_SUCCESS;
}

static int ring_fcntl_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    const char *cmd = argv[2];
    if (strcmp(cmd, "shutdown_w") == 0) shutdown(fd, SHUT_WR);
    else if (strcmp(cmd, "shutdown_r") == 0) shutdown(fd, SHUT_RD);
    else if (strcmp(cmd, "shutdown_rw") == 0) shutdown(fd, SHUT_RDWR);
    else if (strcmp(cmd, "close") == 0) close(fd);
    else { builtin_error("unknown command: %s", cmd); return EXECUTION_FAILURE; }
    return EXECUTION_SUCCESS;
}

static int ring_pipe_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int pfd[2];
    if (pipe(pfd) < 0) { builtin_error("pipe failed: %s", strerror(errno)); return EXECUTION_FAILURE; }
    fcntl(pfd[1], F_SETPIPE_SZ, 1048576); 
    char buf[32];
    if (argc == 2) {
        const char *arr_name = argv[1];
        snprintf(buf, sizeof(buf), "%d", pfd[0]);
        if (bind_array_variable((char*)arr_name, 0, buf, 0) == NULL) { 
            close(pfd[0]); close(pfd[1]); return EXECUTION_FAILURE; 
        }
        snprintf(buf, sizeof(buf), "%d", pfd[1]);
        if (bind_array_variable((char*)arr_name, 1, buf, 0) == NULL) {
            close(pfd[0]); close(pfd[1]); return EXECUTION_FAILURE;
        }
    } else {
        snprintf(buf, sizeof(buf), "%d", pfd[0]); bind_var_or_array(argv[1], buf, 0);
        snprintf(buf, sizeof(buf), "%d", pfd[1]); bind_var_or_array(argv[2], buf, 0);
    }
    return EXECUTION_SUCCESS;
}

static int ring_splice_main(int argc, char **argv) {
    if (argc < 5) return EXECUTION_FAILURE;
    int fd_in  = atoi(argv[1]); 
    int fd_out = atoi(argv[2]); 
    off_t off  = (off_t)atoll(argv[3]);
    size_t len = (size_t)atoll(argv[4]);
    bool close_out = (argc > 5 && strcmp(argv[5], "close") == 0);
    
    // OPTIMIZATION: Attempt to expand pipe buffer to 1MB.
    // If fd_out is a regular file/socket, this fails harmlessly.
    // If it's a pipe (even a standard Bash pipe), it accelerates throughput.
    fcntl(fd_out, F_SETPIPE_SZ, 1048576);

    size_t written = 0;
    while (written < len) {
        ssize_t s = splice(fd_in, &off, fd_out, NULL, len - written, SPLICE_F_MOVE|SPLICE_F_MORE);
        if (s < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) continue; 
            if (close_out) close(fd_out);
            builtin_error("splice failed: %s", strerror(errno));
            return EXECUTION_FAILURE;
        }
        if (s == 0) break; 
        written += s;
    }
    
    if (close_out) close(fd_out);
    return EXECUTION_SUCCESS;
}

static int ring_indexer_main(int argc, char **argv) {
    if (argc < 4) return EXECUTION_FAILURE;
    int fd_data = atoi(argv[1]);
    int fd_pipe = atoi(argv[2]); 
    int fd_sig  = atoi(argv[3]); 
    size_t chunk_target = get_optimal_chunk_size() * 2; 
    uint64_t current_pos = 0;
    char tail_buf[65536]; 
    struct pollfd pfds[1] = { { .fd = fd_sig, .events = POLLIN } };
    while (1) {
        struct stat st;
        if (fstat(fd_data, &st) < 0) break;
        uint64_t available = (uint64_t)st.st_size;
        while (available >= current_pos + chunk_target) {
            uint64_t scan_end = current_pos + chunk_target;
            size_t scan_sz = (sizeof(tail_buf) < chunk_target) ? sizeof(tail_buf) : chunk_target;
            ssize_t n = pread(fd_data, tail_buf, scan_sz, scan_end - scan_sz);
            if (n > 0) {
                char *nl = memrchr(tail_buf, '\n', n);
                if (nl) {
                    uint64_t actual_end = (scan_end - scan_sz) + (nl - tail_buf) + 1;
                    struct PhysPacket pp = { .off = current_pos, .len = actual_end - current_pos };
                    if (write(fd_pipe, &pp, sizeof(pp)) != sizeof(pp)) return EXECUTION_FAILURE;
                    current_pos = actual_end;
                    continue; 
                }
            }
            struct PhysPacket pp = { .off = current_pos, .len = chunk_target };
            if (write(fd_pipe, &pp, sizeof(pp)) != sizeof(pp)) return EXECUTION_FAILURE;
            current_pos += chunk_target;
        }
        if (poll(pfds, 1, 100) > 0) { uint64_t v; if(read(fd_sig, &v, 8)){}; }
    }
    return EXECUTION_SUCCESS;
}
static int ring_fetcher_main(int argc, char **argv) {
    if (argc < 6) return EXECUTION_FAILURE;
    int fd_pipe      = atoi(argv[1]); 
    int fd_global    = atoi(argv[2]); 
    int fd_local     = atoi(argv[3]); 
    int fd_local_sig = atoi(argv[4]); 
    int fd_global_ack= atoi(argv[5]); 
    int fd_token_in  = (argc > 6) ? atoi(argv[6]) : -1; 
    struct PhysPacket pp;
    while (1) {
        if (fd_token_in >= 0) { char t; if (read(fd_token_in, &t, 1) <= 0) break; }
        if (read(fd_pipe, &pp, sizeof(pp)) != sizeof(pp)) break;
        loff_t off_in = (loff_t)pp.off;
        loff_t off_out = lseek(fd_local, 0, SEEK_END);
        ssize_t ret = copy_file_range(fd_global, &off_in, fd_local, &off_out, pp.len, 0);
        if (ret < 0) {
            char *buf = xmalloc(65536);
            uint64_t copied = 0;
            lseek(fd_global, pp.off, SEEK_SET);
            lseek(fd_local, 0, SEEK_END);
            while (copied < pp.len) {
                size_t to_read = (pp.len - copied > 65536) ? 65536 : (pp.len - copied);
                read(fd_global, buf, to_read);
                write(fd_local, buf, to_read);
                copied += to_read;
            }
            xfree(buf);
        }
        uint64_t one = 1; SYS_CHK(write(fd_local_sig, &one, 8));
        SYS_CHK(write(fd_global_ack, &pp, sizeof(pp)));
    }
    return EXECUTION_SUCCESS;
}
static int ring_fallow_phys_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    int fd_file = atoi(argv[2]);
    struct Interval *head = NULL;
    uint64_t limit = 0; 
    struct PhysPacket ops[64];
    ssize_t n_read;
    while ((n_read = read(fd_in, ops, sizeof(ops))) > 0) {
        int count = n_read / sizeof(struct PhysPacket);
        for (int i=0; i<count; i++) {
            struct PhysPacket *pp = &ops[i];
            if (pp->off == limit) {
                limit += pp->len;
                while (head && head->s == limit) {
                    struct Interval *tmp = head;
                    limit = tmp->e;
                    head = tmp->next;
                    free(tmp);
                }
                off_t aligned = (off_t)((limit / 4096) * 4096);
                if (aligned > 0) fallocate(fd_file, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, 0, aligned);
            } else if (pp->off > limit) {
                struct Interval *n = xmalloc(sizeof(struct Interval));
                n->s = pp->off; n->e = pp->off + pp->len;
                struct Interval **curr = &head;
                while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
                n->next = *curr; *curr = n;
            }
        }
    }
    return EXECUTION_SUCCESS;
}

#define DEFINE_DISPATCHER_X(name, func, usage, doc) \
static int dispatch_##name(WORD_LIST *list) { \
    int argc; \
    char **argv = make_builtin_argv(list, &argc); \
    int ret = EXECUTION_FAILURE; \
    if (argv[0]) ret = func(argc, argv); \
    xfree(argv); \
    return ret; \
}
FORKRUN_LOADABLES(DEFINE_DISPATCHER_X)
#undef DEFINE_DISPATCHER_X

#define DEFINE_STRUCT_X(name, func, usage, doc) \
static char *name##_doc[] = { doc, usage, NULL }; \
struct builtin name##_struct = { #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0 };
FORKRUN_LOADABLES(DEFINE_STRUCT_X)
#undef DEFINE_STRUCT_X

static int ring_list_main(int argc, char **argv) {
    if (argc >= 2) {
        const char *var_name = argv[1];
        SHELL_VAR *v = find_variable(var_name);
        if (v && !array_p(v)) { unbind_variable(var_name); v = NULL; }
        if (!v) v = make_new_array_variable(var_name);
        if (!v) return EXECUTION_FAILURE;
        int i = 0;
        #define ADD_TO_ARR(name, ...) \
            if (strcmp(#name, "ring_list") != 0) \
                bind_array_element(v, i++, #name, 0);
        FORKRUN_LOADABLES(ADD_TO_ARR)
        #undef ADD_TO_ARR
    } else {
        #define PRINT_NAME(name, ...) \
            if (strcmp(#name, "ring_list") != 0) \
                printf("%s\n", #name);
        FORKRUN_LOADABLES(PRINT_NAME)
        #undef PRINT_NAME
    }
    return EXECUTION_SUCCESS;
}

int setup_builtin_forkrun_ring(void) {
    #define REGISTER_X(name, func, usage, doc) add_builtin(&name##_struct, 1);
    FORKRUN_LOADABLES(REGISTER_X)
    #undef REGISTER_X
    return 0;
}
