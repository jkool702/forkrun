// forkrun_ring.c v13.0.9-NUMA (Golden Master: Fully Stitched & Hardened)
// ======================================================================================
// ARCHITECTURE OVERVIEW:
//
// 1. Zero-Copy Ingest: Data moved from stdin to memfd via splice/copy_file_range.
// 2. Lock-Free Meta Ring: Ingest publishes chunk coordinates to GlobalState.
// 3. Per-Node Indexers: Find physical boundaries instantly in local memory.
// 4. Unified Scanners: A single core hot-loop handles both UMA and NUMA execution.
// 5. Min-Heap Orderer: Resolves extreme skew with O(log N) sorting.
// ======================================================================================

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#ifndef _FILE_OFFSET_BITS
#define _FILE_OFFSET_BITS 64
#endif

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/mman.h>
#include <sys/sendfile.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysinfo.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

// ==============================================================================
// AVX2 FAST DELIMITER SCANNER
// ==============================================================================

#if defined(__x86_64__) || defined(__i386__)
#pragma GCC push_options
#pragma GCC target("avx2,popcnt")
#include <immintrin.h>

__attribute__((target("avx2,popcnt")))
static inline char *
scan_batch_avx2(char *p, char *end, uint64_t target, char delim)
{
    uint64_t remaining = target;
    const __m256i d_vec = _mm256_set1_epi8(delim);

    while (p + 32 <= end) {
        __m256i v = _mm256_loadu_si256((const __m256i*)p);
        __m256i cmp = _mm256_cmpeq_epi8(v, d_vec);
        uint32_t mask = (uint32_t)_mm256_movemask_epi8(cmp);

        if (!mask) {
            p += 32;
            continue;
        }

        uint32_t hits = (uint32_t)__builtin_popcount(mask);

        if (hits < remaining) {
            remaining -= hits;
            p += 32;
            continue;
        }

        uint32_t to_drop = (uint32_t)(remaining - 1);
        for (uint32_t i = 0; i < to_drop; i++) {
            mask &= mask - 1;
        }

        int exact_idx = __builtin_ctz(mask);
        return p + exact_idx + 1;
    }

    while (p < end) {
        if (*p == delim) {
            remaining--;
            if (remaining == 0) return p + 1;
        }
        p++;
    }

    return NULL;
}
#pragma GCC pop_options
#endif

#if defined(__aarch64__)
#include <arm_neon.h>

static inline char *scan_batch_neon(char *p, char *end, uint64_t target, char delim) {
    uint64_t remaining = target;
    uint8x16_t d_vec = vdupq_n_u8(delim);

    while (p + 16 <= end) {
        uint8x16_t v = vld1q_u8((const uint8_t*)p);
        uint8x16_t cmp = vceqq_u8(v, d_vec);

        uint64_t lo = vgetq_lane_u64(vreinterpretq_u64_u8(cmp), 0);
        uint64_t hi = vgetq_lane_u64(vreinterpretq_u64_u8(cmp), 1);

        if (lo == 0 && hi == 0) {
            p += 16;
            continue;
        }

        uint32_t hits_lo = __builtin_popcountll(lo) / 8;
        if (hits_lo < remaining) {
            remaining -= hits_lo;
        } else {
            uint32_t to_drop = (uint32_t)(remaining - 1);
            for (uint32_t i = 0; i < to_drop; i++) {
                int idx = __builtin_ctzll(lo) / 8;
                lo &= ~(0xFFULL << (idx * 8));
            }
            int exact_idx = __builtin_ctzll(lo) / 8;
            return p + exact_idx + 1;
        }

        uint32_t hits_hi = __builtin_popcountll(hi) / 8;
        if (hits_hi < remaining) {
            remaining -= hits_hi;
        } else {
            uint32_t to_drop = (uint32_t)(remaining - 1);
            for (uint32_t i = 0; i < to_drop; i++) {
                int idx = __builtin_ctzll(hi) / 8;
                hi &= ~(0xFFULL << (idx * 8));
            }
            int exact_idx = __builtin_ctzll(hi) / 8;
            return p + 8 + exact_idx + 1;
        }
        p += 16;
    }

    while (p < end) {
        if (*p == delim) {
            remaining--;
            if (remaining == 0) return p + 1;
        }
        p++;
    }

    return NULL;
}
#endif

static inline char *try_simd_scan(char *p, char *safe_end, uint64_t target, char delim) {
    if (target == 0 || p >= safe_end) return NULL;

#if defined(__x86_64__) || defined(__i386__)
    static int avx2_supported = -1;
    if (__builtin_expect(avx2_supported == -1, 0)) {
        __builtin_cpu_init();
        avx2_supported = __builtin_cpu_supports("avx2") && __builtin_cpu_supports("popcnt");
    }

    if (avx2_supported) {
        return scan_batch_avx2(p, safe_end, target, delim);
    }
#elif defined(__aarch64__)
    return scan_batch_neon(p, safe_end, target, delim);
#endif

    return NULL;
}

// --- Architecture Specific Pause Logic ---
#if defined(__x86_64__) || defined(__i386__)
#define cpu_relax() __builtin_ia32_pause()
#elif defined(__aarch64__) || defined(__arm__)
#define cpu_relax() __asm__ __volatile__("yield" ::: "memory")
#elif defined(__riscv)
#define cpu_relax()                                                            \
  __asm__ __volatile__(                                                        \
      ".option push; .option arch, +zihintpause; pause; .option pop" ::        \
          : "memory")
#elif defined(__powerpc__) || defined(__ppc__) || defined(__PPC__)
#define cpu_relax() __asm__ __volatile__("or 27,27,27" ::: "memory")
#elif defined(__s390__) || defined(__s390x__)
#define cpu_relax() __asm__ __volatile__("diag 0,0,0x44" ::: "memory")
#else
#define cpu_relax() __asm__ __volatile__("" ::: "memory")
#endif

// --- NUMA Syscalls & Constants ---
#ifndef MPOL_DEFAULT
#define MPOL_DEFAULT 0
#endif
#ifndef MPOL_BIND
#define MPOL_BIND 2
#endif

#ifndef __NR_set_mempolicy
#if defined(__x86_64__)
#define __NR_set_mempolicy 238
#elif defined(__aarch64__) || defined(__riscv)
#define __NR_set_mempolicy 237
#elif defined(__powerpc__) || defined(__PPC__)
#define __NR_set_mempolicy 260
#elif defined(__s390x__)
#define __NR_set_mempolicy 276
#else
#define __NR_set_mempolicy 0
#endif
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
#define FLAG_MAJOR_EOF (1U << 31)
#define PACK_KEY(maj, min) (((uint64_t)(maj) << 32) | (min))

#define HUGE_PAGE_SIZE (2 * 1024 * 1024)
#define SCANNER_CHUNK_SIZE (2 * 1024 * 1024)
#define RING_SIZE_LOG2 20
#define RING_SIZE (1ULL << RING_SIZE_LOG2)
#define RING_MASK (RING_SIZE - 1)
#define CACHE_LINE 128 // Safe for all modern architectures
#define ALIGNED(x) __attribute__((aligned(x > CACHE_LINE ? x : CACHE_LINE)))
#define MAX_CHUNK_SIZE (32 * 1024 * 1024)
#define DAMPING_OFFSET 6

#ifndef FORKRUN_RING_VERSION
#define FORKRUN_RING_VERSION "NUMA-v13.0.9-UNIFIED"
#endif

#define atomic_load_acquire(ptr) __atomic_load_n(ptr, __ATOMIC_ACQUIRE)
#define atomic_load_relaxed(ptr) __atomic_load_n(ptr, __ATOMIC_RELAXED)
#define atomic_store_release(ptr, val)                                         \
  __atomic_store_n(ptr, val, __ATOMIC_RELEASE)
#define atomic_store_relaxed(ptr, val)                                         \
  __atomic_store_n(ptr, val, __ATOMIC_RELAXED)
#define atomic_fetch_add(ptr, val)                                             \
  __atomic_fetch_add(ptr, val, __ATOMIC_SEQ_CST)
#define atomic_fetch_sub(ptr, val)                                             \
  __atomic_fetch_sub(ptr, val, __ATOMIC_SEQ_CST)
#define atomic_compare_exchange(ptr, exp, des)                                 \
  __atomic_compare_exchange_n(ptr, exp, des, 0, __ATOMIC_ACQ_REL,              \
                              __ATOMIC_RELAXED)

#ifndef GIT_HASH
#define GIT_HASH "unknown"
#endif
#ifndef BUILD_OS
#define BUILD_OS "unknown"
#endif
#ifndef BUILD_ARCH
#define BUILD_ARCH "unknown"
#endif
#ifndef COMPILER_FLAGS
#define COMPILER_FLAGS "unknown"
#endif

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

// clang-format off
#include "command.h"
#include "shell.h"
#include "variables.h"
#include "builtins.h"
#include "common.h"
#include "xmalloc.h" // MUST precede undefs so xfree(argv) compiles correctly

// PHYSICS FIX: Bash violently hijacks memory allocators via macros in config.h.
// We MUST undefine them here to ensure our C structures strictly use glibc libc allocators.
// Crossing streams causes `invalid chunk size` and `double free` heap detonations.
#undef malloc
#undef free
#undef realloc
#undef calloc
// clang-format on

extern void dispose_command(COMMAND *);
extern int execute_command(COMMAND *);
extern int add_builtin(struct builtin *bp, int keep);

static int g_debug = 0;

#define SYS_CHK(x)                                                             \
  do {                                                                         \
    if ((long)(x) == -1) {                                                     \
      if (g_debug)                                                             \
        fprintf(stderr, "forkrun[DEBUG] %s:%d: %s failed: %s\n", __FILE__,    \
                __LINE__, #x, strerror(errno));                                \
    }                                                                          \
  } while (0)

// ==============================================================================
// PHYSICS FIX: ROBUST IPC IO WRAPPERS
// ==============================================================================

// For IPC Pipes (Order/Fallow/Escrow). Uses poll() to wait for EAGAIN without burning CPU.
static inline ssize_t robust_pipe_read(int fd, void *buf, size_t count, bool exact) {
    char *p = (char *)buf;
    size_t left = count;
    while (left > 0) {
        ssize_t r = read(fd, p, left);
        if (r < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct pollfd pfd = {.fd = fd, .events = POLLIN};
                poll(&pfd, 1, -1);
                continue;
            }
            return (count - left) > 0 ? (ssize_t)(count - left) : -1;
        }
        if (r == 0) return count - left; // EOF
        p += r;
        left -= r;

        // CRITICAL FIX: If exact is false, return immediately after ANY successful
        // read to prevent Fallow/Order threads from deadlocking on partial queues.
        if (!exact) return count - left;
    }
    return count;
}

static inline ssize_t robust_pipe_write(int fd, const void *buf, size_t count) {
    const char *p = (const char *)buf;
    size_t left = count;
    while (left > 0) {
        ssize_t w = write(fd, p, left);
        if (w < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct pollfd pfd = {.fd = fd, .events = POLLOUT};
                poll(&pfd, 1, -1);
                continue;
            }
            return -1;
        }
        p += w;
        left -= w;
    }
    return count;
}

// For EventFDs. Strictly returns -1 EAGAIN if empty so lock-free loops can proceed.
static inline ssize_t sys_read(int fd, void *buf, size_t count) {
    ssize_t r;
    do { r = read(fd, buf, count); } while (r < 0 && errno == EINTR);
    return r;
}

static inline ssize_t sys_write(int fd, const void *buf, size_t count) {
    ssize_t w;
    do { w = write(fd, buf, count); } while (w < 0 && errno == EINTR);
    return w;
}

// RESTORED LOADABLES MACRO
#define FORKRUN_LOADABLES(X)                                                   \
  X(ring_init, ring_init_main, "ring_init [FLAGS]",                            \
    "Initialize ring with config")                                             \
  X(ring_destroy, ring_destroy_main, "ring_destroy", "Destroy ring")           \
  X(ring_scanner, ring_scanner_main, "ring_scanner <fd> [spawn_fd]",           \
    "Run unified legacy scanner")                                              \
  X(ring_numa_ingest, ring_numa_ingest_main,                                   \
    "ring_numa_ingest <infd> <outfd> <nodes> [ordered]",                       \
    "Run NUMA topological ingest")                                             \
  X(ring_indexer_numa, ring_indexer_numa_main,                                 \
    "ring_indexer_numa <memfd> <node_id>", "Run NUMA chunk indexer")           \
  X(ring_numa_scanner, ring_numa_scanner_main,                                 \
    "ring_numa_scanner <memfd> <node_id> <spawn_fd> <nodes>",                  \
    "Run unified NUMA scanner")                                                \
  X(ring_claim, ring_claim_main, "ring_claim [VAR] [FD]", "Claim batch")       \
  X(ring_worker, ring_worker_main, "ring_worker [inc|dec] [FD]",               \
    "Worker control")                                                          \
  X(ring_cleanup_waiter, ring_cleanup_waiter_main, "ring_cleanup_waiter",      \
    "Cleanup waiter")                                                          \
  X(ring_ingest, ring_ingest_main, "ring_ingest", "Signal ingest")             \
  X(ring_fallow, ring_fallow_main, "ring_fallow <PIPE> <FILE> [dry]",          \
    "Logical fallow")                                                          \
  X(ring_ack, ring_ack_main, "ring_ack <FD> <FD_OUT>", "Ack batch")            \
  X(ring_order, ring_order_main, "ring_order <FD> <PFX|memfd> [unordered]",    \
    "Reorder output")                                                          \
  X(ring_copy, ring_copy_main, "ring_copy <OUT> <IN>", "Zero-copy ingest")     \
  X(ring_signal, ring_signal_main, "ring_signal <FD>", "Signal eventfd")       \
  X(lseek, lseek_main, "lseek <FD> <OFF> [WHENCE] [VAR]", "Seek fd")           \
  X(ring_indexer, ring_indexer_main, "ring_indexer", "NUMA Indexer")           \
  X(ring_fetcher, ring_fetcher_main, "ring_fetcher", "NUMA Fetcher")           \
  X(ring_fallow_phys, ring_fallow_phys_main, "ring_fallow_phys",               \
    "Physical fallow")                                                         \
  X(ring_memfd_create, ring_memfd_create_main, "ring_memfd_create <VAR>",      \
    "Create memfd")                                                            \
  X(ring_seal, ring_seal_main, "ring_seal <FD>", "Seal memfd")                 \
  X(ring_fcntl, ring_fcntl_main, "ring_fcntl <FD> <cmd>", "File control")      \
  X(ring_pipe, ring_pipe_main, "ring_pipe <ARR|RD> [WR]", "Create pipe")       \
  X(ring_splice, ring_splice_main,                                             \
    "ring_splice <IN> <OUT> <OFF> <LEN> [close]", "Splice data")               \
  X(ring_version, ring_version_main, "ring_version [-t|-o|-m|-g|-f|-a]",       \
    "Show build metadata")                                                     \
  X(ring_numa_stats, ring_numa_stats_main, "ring_numa_stats", "Print NUMA telemetry") \
  X(ring_list, ring_list_main, "ring_list [VAR]", "List loadables")

#define X(name, func, usage, doc) static int func(int argc, char **argv);
FORKRUN_LOADABLES(X)
#undef X

static inline int auto_detect_numa_node() {
#ifdef __NR_getcpu
  unsigned cpu, node;
  if (syscall(__NR_getcpu, &cpu, &node, NULL) == 0)
    return (int)node;
#endif
  return 0;
}

static int pin_to_numa_node(int node_id) {
  char path[256];
  snprintf(path, sizeof(path), "/sys/devices/system/node/node%d/cpulist",
           node_id);
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return -1;
  char buf[1024] = {0};
  ssize_t n = read(fd, buf, sizeof(buf) - 1);
  close(fd);
  if (n <= 0)
    return -1;

  cpu_set_t cpuset;
  CPU_ZERO(&cpuset);
  char *p = buf;
  while (*p) {
    while (*p && !isdigit(*p))
      p++;
    if (!*p)
      break;
    int start = strtol(p, &p, 10);
    int end = start;
    if (*p == '-') {
      p++;
      end = strtol(p, &p, 10);
    }
    for (int i = start; i <= end; i++) {
      if (i >= 0 && i < CPU_SETSIZE) {
        CPU_SET(i, &cpuset);
      }
    }
    while (*p && *p != ',' && *p != '\n')
      p++;
  }
  return sched_setaffinity(0, sizeof(cpu_set_t), &cpuset);
}

static SHELL_VAR *bind_var_or_array(const char *name, char *value, int flags) {
  if (!name)
    return NULL;
  char *lb = strchr(name, '[');
  if (!lb || name[strlen(name) - 1] != ']')
    return bind_variable(name, value, flags);

  size_t base_len = (size_t)(lb - name);
  char base_tmp[256];
  if (base_len >= sizeof(base_tmp)) return NULL;
  memcpy(base_tmp, name, base_len);
  base_tmp[base_len] = '\0';

  size_t idx_len = strlen(lb + 1) - 1;
  char idx_tmp[256];
  if (idx_len >= sizeof(idx_tmp)) return NULL;
  memcpy(idx_tmp, lb + 1, idx_len);
  idx_tmp[idx_len] = '\0';

  SHELL_VAR *var = find_variable(base_tmp);
  if (!var) {
    var = make_new_array_variable(base_tmp);
    if (!var) return NULL;
  }

  SHELL_VAR *ret = NULL;
  if (assoc_p(var))
    ret = bind_assoc_variable(var, base_tmp, idx_tmp, value, flags);
  else if (array_p(var)) {
    char *endp = NULL;
    errno = 0;
    long n = strtol(idx_tmp, &endp, 10);
    if (endp == idx_tmp || *endp != '\0' || errno == ERANGE) {
    } else
      ret = bind_array_variable(base_tmp, (arrayind_t)n, value, flags);
  }
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
  if (sz <= 0)
    return 512 * 1024;
  return (uint64_t)sz;
}

static uint64_t get_llc_size() {
#ifdef _SC_LEVEL3_CACHE_SIZE
  long sz = sysconf(_SC_LEVEL3_CACHE_SIZE);
  if (sz > 0)
    return (uint64_t)sz;
#endif
  int fd = open("/sys/devices/system/cpu/cpu0/cache/index3/size", O_RDONLY);
  if (fd >= 0) {
    char buf[32];
    ssize_t n = sys_read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n > 0) {
      buf[n] = '\0';
      char *end;
      uint64_t val = strtoull(buf, &end, 10);
      if (*end == 'K' || *end == 'k')
        val *= 1024;
      else if (*end == 'M' || *end == 'm')
        val *= 1024 * 1024;
      if (val > 0)
        return val;
    }
  }
  return get_cache_bytes() * 8;
}

static uint64_t get_optimal_chunk_size() {
  uint64_t llc = get_llc_size();
  uint64_t target = llc >> 3;
  uint64_t mask = HUGE_PAGE_SIZE - 1;
  target = (target + mask) & ~mask;
  if (target < HUGE_PAGE_SIZE)
    target = HUGE_PAGE_SIZE;
  if (target > MAX_CHUNK_SIZE)
    target = MAX_CHUNK_SIZE;
  return target;
}

static uint64_t get_arg_max_bytes() {
  long sys_arg_max = sysconf(_SC_ARG_MAX);
  if (sys_arg_max <= 0)
    return 2097152;
  size_t env_len = 0;
  extern char **environ;
  for (char **ep = environ; *ep; ++ep)
    env_len += strlen(*ep) + 1;
  if ((long)env_len < sys_arg_max)
    return (uint64_t)((sys_arg_max - (long)env_len) * 15 / 16);
  return 32768;
}

static int xcreate_anon_file(const char *name) {
  const char *force_fallback = get_string_value("FORKRUN_FORCE_FALLBACK");
  bool use_memfd = true;
  if (force_fallback && (strcmp(force_fallback, "1") == 0))
    use_memfd = false;
  if (use_memfd) {
    int fd = syscall(__NR_memfd_create, name, MFD_ALLOW_SEALING);
    if (fd >= 0)
      return fd;
    if (errno == EINVAL) {
      fd = syscall(__NR_memfd_create, name, 0);
      if (fd >= 0)
        return fd;
    }
  }
  int fd = open("/dev/shm", O_TMPFILE | O_RDWR | O_EXCL, 0600);
  if (fd >= 0)
    return fd;
  fd = open("/tmp", O_TMPFILE | O_RDWR | O_EXCL, 0600);
  if (fd >= 0)
    return fd;
  char path[64];
  snprintf(path, sizeof(path), "/dev/shm/forkrun.XXXXXX");
  fd = mkstemp(path);
  if (fd < 0) {
    snprintf(path, sizeof(path), "/tmp/forkrun.XXXXXX");
    fd = mkstemp(path);
  }
  if (fd >= 0)
    unlink(path);
  return fd;
}

static inline void u64toa(uint64_t value, char *buffer) {
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
  while (p > temp)
    buffer[i++] = *--p;
  buffer[i] = '\0';
}

static inline uint64_t get_us_time() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC_COARSE, &ts);
  return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000;
}

static inline uint64_t fast_log2(uint64_t v) {
  if (v < 2)
    return 0;
  return 63 - __builtin_clzll(v);
}

// ==============================================================================
// 2. TLS AND SHARED STATE
// ==============================================================================

static __thread int my_numa_node = -1;
static __thread bool is_waiting_on_ring = false;
static __thread int worker_cached_fd = -1;
static __thread off_t last_ack_offset = 0;
static __thread int ack_cached_target_fd = -1;
static __thread int ack_cached_mode = 0;
static __thread uint64_t worker_last_idx = 0;
static __thread uint64_t worker_last_cnt = 0;
static __thread uint32_t worker_last_major = 0;
static __thread uint32_t worker_last_minor = 0;

static int *evfd_data_arr = NULL;
static int *evfd_eof_arr = NULL;
static int *evfd_indexer_arr = NULL;
static int *evfd_meta_arr = NULL;
static int *fd_escrow_r = NULL;
static int *fd_escrow_w = NULL;

static int evfd_data = -1;
static int evfd_ingest_data = -1;
static int evfd_ingest_eof = -1;
static int evfd_chunk_done = -1;
static int fd_escrow[2] = {-1, -1};

static uint32_t global_num_nodes = 0;
static uint32_t allocated_num_nodes = 0;
static uint32_t *g_logical_to_phys_map = NULL;

struct EscrowPacket {
  uint64_t idx;
  uint64_t cnt;
};
struct IndexPacket {
  uint64_t idx;
  uint64_t cnt;
};
struct Interval {
  uint64_t s;
  uint64_t e;
  struct Interval *next;
};
struct PhysPacket {
  uint64_t off;
  uint64_t len;
};

struct OrderPacket {
  uint32_t major_idx;
  uint32_t minor_idx;
  uint32_t cnt;
  int32_t fd;
  uint64_t off;
  uint64_t len;
};

#define FLAG_META_READY (1ULL << 63)
#define META_RING_SIZE 4096
#define META_RING_MASK (META_RING_SIZE - 1)

struct ChunkMeta {
  uint64_t raw_offset;
  uint64_t raw_length;
  uint32_t target_node;
  uint32_t major_id;
  volatile uint64_t actual_end ALIGNED(CACHE_LINE);
};

struct GlobalState {
  uint64_t ingest_publish_idx ALIGNED(CACHE_LINE);
  uint64_t ingest_eof_idx ALIGNED(CACHE_LINE);
  uint64_t _pad_ingest_waiters[7];
  struct ChunkMeta meta_ring[META_RING_SIZE];
};

struct SharedState {
  uint64_t chunk_queue_head ALIGNED(CACHE_LINE);
  uint8_t _pad_cq_head[CACHE_LINE - sizeof(uint64_t)];

  uint64_t chunk_ready_head ALIGNED(CACHE_LINE);
  uint8_t _pad_cr_head[CACHE_LINE - sizeof(uint64_t)];

  uint64_t chunk_queue_tail ALIGNED(CACHE_LINE);
  uint8_t _pad_cq_tail[CACHE_LINE - sizeof(uint64_t)];

  uint32_t chunk_queue[META_RING_SIZE];

  uint64_t read_idx ALIGNED(CACHE_LINE);
  uint8_t _pad_read_idx[CACHE_LINE - sizeof(uint64_t)];

  uint64_t write_idx ALIGNED(CACHE_LINE);
  uint8_t _pad_write_idx[CACHE_LINE - sizeof(uint64_t)];

  uint64_t total_lines_consumed ALIGNED(CACHE_LINE);
  uint8_t _pad_lines[CACHE_LINE - sizeof(uint64_t)];

  uint32_t active_waiters ALIGNED(CACHE_LINE);
  uint8_t _pad_waiters[CACHE_LINE - sizeof(uint32_t)];

  uint64_t active_workers ALIGNED(CACHE_LINE);
  uint64_t global_scanned;
  uint64_t tail_idx;
  uint8_t scanner_finished;
  uint8_t fallow_active;
  uint8_t ingest_complete;

  uint32_t indexer_waiters ALIGNED(CACHE_LINE);
  uint32_t meta_waiters ALIGNED(CACHE_LINE);
  uint64_t min_idx;

  int64_t signed_batch_size;
  uint64_t batch_change_idx;

  uint64_t cfg_w_start ALIGNED(CACHE_LINE);
  uint64_t cfg_w_max;
  uint64_t cfg_batch_start;
  uint64_t cfg_batch_max;
  uint64_t cfg_limit;
  uint64_t cfg_chunk_bytes;
  uint64_t cfg_line_max;
  int64_t cfg_timeout_us;
  uint8_t mode_byte;
  uint8_t fixed_workers;
  uint8_t fixed_batch;
  uint8_t cfg_return_bytes;
  uint8_t numa_enabled;
  uint8_t exact_lines;

  uint64_t stats_chunks_assigned ALIGNED(CACHE_LINE);
  uint64_t stats_chunks_local;
  uint64_t stats_chunks_stolen;

  uint32_t stride_ring[RING_SIZE] ALIGNED(4096);
  uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
  uint64_t end_ring[RING_SIZE] ALIGNED(4096);
  uint32_t major_ring[RING_SIZE] ALIGNED(4096);
  uint32_t minor_ring[RING_SIZE] ALIGNED(4096);
};

static struct GlobalState *g_state = NULL;
static struct SharedState *state = NULL;

static inline void cleanup_waiter_state() {
  if (is_waiting_on_ring) {
    int node = (my_numa_node == -1) ? 0 : my_numa_node;
    if (state && atomic_load_relaxed(&state[node].active_waiters) > 0) {
      atomic_fetch_sub(&state[node].active_waiters, 1);
    }
    is_waiting_on_ring = false;
  }
}

#define OOM_WAIT_FOR_MEMORY(free_b_var, threshold, si_var, mu_var)             \
  do {                                                                         \
    int _oom_sleep_us = 1000;                                                  \
    int _oom_waited_us = 0;                                                    \
    while ((free_b_var) < (threshold) && _oom_waited_us < 30000000) {          \
      usleep(_oom_sleep_us);                                                   \
      _oom_waited_us += _oom_sleep_us;                                         \
      sysinfo(&(si_var));                                                      \
      (free_b_var) = (uint64_t)(si_var).freeram * (mu_var);                    \
      _oom_sleep_us += _oom_sleep_us >> 1;                                     \
      if (_oom_sleep_us > 100000)                                              \
        _oom_sleep_us = 100000;                                                \
    }                                                                          \
  } while (0)

static int get_cgroup_free_memory(uint64_t *free_mem) {
    char buf[128];
    int fd = open("/sys/fs/cgroup/memory.max", O_RDONLY);
    if (fd >= 0) {
        ssize_t n = sys_read(fd, buf, sizeof(buf) - 1);
        close(fd);
        if (n > 0) {
            buf[n] = '\0';
            if (strncmp(buf, "max", 3) == 0) return -1;
            uint64_t max_val = strtoull(buf, NULL, 10);
            fd = open("/sys/fs/cgroup/memory.current", O_RDONLY);
            if (fd >= 0) {
                n = sys_read(fd, buf, sizeof(buf) - 1);
                close(fd);
                if (n > 0) {
                    buf[n] = '\0';
                    uint64_t cur_val = strtoull(buf, NULL, 10);
                    *free_mem = (max_val > cur_val) ? (max_val - cur_val) : 0;
                    return 0;
                }
            }
        }
    }
    fd = open("/sys/fs/cgroup/memory/memory.limit_in_bytes", O_RDONLY);
    if (fd >= 0) {
        ssize_t n = sys_read(fd, buf, sizeof(buf) - 1);
        close(fd);
        if (n > 0) {
            buf[n] = '\0';
            uint64_t max_val = strtoull(buf, NULL, 10);
            if (max_val > 9000000000000000000ULL) return -1;
            fd = open("/sys/fs/cgroup/memory/memory.usage_in_bytes", O_RDONLY);
            if (fd >= 0) {
                n = sys_read(fd, buf, sizeof(buf) - 1);
                close(fd);
                if (n > 0) {
                    buf[n] = '\0';
                    uint64_t cur_val = strtoull(buf, NULL, 10);
                    *free_mem = (max_val > cur_val) ? (max_val - cur_val) : 0;
                    return 0;
                }
            }
        }
    }
    return -1;
}

static inline void check_memory_pressure(uint64_t *total_moved, uint64_t *next_check, uint64_t oom_threshold) {
  if (*total_moved > *next_check) {
    uint64_t free_b = 0;
    if (get_cgroup_free_memory(&free_b) == 0) {
      if (free_b < oom_threshold && state) {
        int _oom_sleep_us = 1000;
        int _oom_waited_us = 0;
        while (free_b < oom_threshold && _oom_waited_us < 30000000) {
          usleep(_oom_sleep_us);
          _oom_waited_us += _oom_sleep_us;
          get_cgroup_free_memory(&free_b);
          _oom_sleep_us += _oom_sleep_us >> 1;
          if (_oom_sleep_us > 100000) _oom_sleep_us = 100000;
        }
      }
    } else {
      struct sysinfo si;
      if (sysinfo(&si) == 0) {
        uint64_t mu = (uint64_t)si.mem_unit ? si.mem_unit : 1;
        free_b = (uint64_t)si.freeram * mu;
        if (free_b < oom_threshold && state) {
          OOM_WAIT_FOR_MEMORY(free_b, oom_threshold, si, mu);
        }
      }
    }
    *next_check += 16 * 1024 * 1024;
  }
}

#define S_DIS 0
#define S_MIN 1
#define S_DEF 2
#define S_MAX 4
#define S_USER 8

#define SH_W_A 0
#define SH_W_B 4
#define SH_L_A 8
#define SH_L_B 12
#define SH_B_A 16
#define SH_B_B 20
#define SH_STDIN 24
#define SH_BMODE 25

#define M_W_A (0xF << SH_W_A)
#define M_W_B (0xF << SH_W_B)
#define M_L_A (0xF << SH_L_A)
#define M_L_B (0xF << SH_L_B)
#define M_B_A (0xF << SH_B_A)
#define M_B_B (0xF << SH_B_B)
#define M_STDIN (1 << SH_STDIN)
#define M_BMODE (1 << SH_BMODE)

#define M_W_ALL (M_W_A | M_W_B)
#define M_L_ALL (M_L_A | M_L_B)
#define M_B_ALL (M_B_A | M_B_B)

static uint64_t get_v_def(const char *type, bool stdin_mode) {
  if (!strcmp(type, "workers")) return sysconf(_SC_NPROCESSORS_ONLN);
  if (!strcmp(type, "lines")) return 4096;
  if (!strcmp(type, "bytes")) {
    uint64_t l2 = get_cache_bytes();
    if (stdin_mode) return (l2 < (1ULL << 19)) ? l2 : (1ULL << 19);
    uint64_t arg = get_arg_max_bytes();
    return (l2 < arg) ? l2 : arg;
  }
  return 1;
}

static uint64_t get_v_max(const char *type, bool stdin_mode) {
  if (!strcmp(type, "workers")) return sysconf(_SC_NPROCESSORS_ONLN) * 2;
  if (!strcmp(type, "lines")) return 65535;
  if (!strcmp(type, "bytes")) {
    if (stdin_mode) {
      uint64_t l2 = get_cache_bytes();
      return (l2 < (1ULL << 20)) ? l2 : (1ULL << 20);
    } else return get_arg_max_bytes();
  }
  return 1;
}

static uint32_t cfg_state = 0;
static uint64_t user_vals[6] = {0};

static void apply_config(char type, char sub, const char *arg) {
  uint32_t clear_mask = 0;
  uint32_t set_mask = 0;
  int val_code = S_USER;
  uint64_t u_val = 0;

  if (strcmp(arg, "x") == 0) {
    if (type == 1) { clear_mask |= M_L_ALL; set_mask |= M_BMODE; }
    else if (type == 2) { clear_mask |= (M_B_ALL | M_BMODE); }
  } else {
    if (arg[0] == '\0') val_code = S_DEF;
    else if (strcmp(arg, "0") == 0) val_code = S_DEF;
    else if (strcmp(arg, "-0") == 0) val_code = S_MIN;
    else if (strcmp(arg, "+0") == 0) val_code = S_MAX;
    else if (strcmp(arg, "-1") == 0) val_code = S_MAX;
    else {
      val_code = S_USER;
      u_val = (uint64_t)atoll(arg);
      if (u_val < 1) u_val = 1;
    }

    if (type == 1) { cfg_state &= ~M_BMODE; cfg_state &= ~M_B_ALL; }
    if (type == 2) { cfg_state |= M_BMODE; cfg_state |= M_STDIN; cfg_state &= ~M_L_ALL; }
    if (type == 0) clear_mask |= M_W_ALL;
    if (type == 1) clear_mask |= M_L_ALL;
    if (type == 2) clear_mask |= M_B_ALL;

#define APPLY_SLOT(idx_u, sh)                                                  \
  do {                                                                         \
    if (val_code == S_USER) {                                                  \
      user_vals[idx_u] = u_val;                                                \
      set_mask |= (S_USER << sh);                                              \
    } else {                                                                   \
      set_mask |= (val_code << sh);                                            \
    }                                                                          \
  } while (0)

    if (type == 0) {
      if (sub == 0 || sub == 1) { cfg_state &= ~M_W_A; APPLY_SLOT(0, SH_W_A); }
      if (sub == 0 || sub == 2) { cfg_state &= ~M_W_B; APPLY_SLOT(1, SH_W_B); }
    }
    if (type == 1) {
      if (sub == 0 || sub == 1) { cfg_state &= ~M_L_A; APPLY_SLOT(2, SH_L_A); }
      if (sub == 0 || sub == 2) { cfg_state &= ~M_L_B; APPLY_SLOT(3, SH_L_B); }
    }
    if (type == 2) {
      if (sub == 0 || sub == 1) { cfg_state &= ~M_B_A; APPLY_SLOT(4, SH_B_A); }
      if (sub == 0 || sub == 2) { cfg_state &= ~M_B_B; APPLY_SLOT(5, SH_B_B); }
    }
  }
  cfg_state |= set_mask;
}

// ==============================================================================
// 3. LIFECYCLE (Init & Destroy)
// ==============================================================================

static int ring_init_main(int argc, char **argv) {
  const char *dbg_env = get_string_value("FORKRUN_DEBUG");
  if (dbg_env && (strcmp(dbg_env, "1") == 0 || strcmp(dbg_env, "true") == 0)) {
    g_debug = 1;
    fprintf(stderr, "forkrun[DEBUG] Enabled\n");
  } else g_debug = 0;

  global_num_nodes = 0;
  for (int i = 1; i < argc; i++) {
    if (strncmp(argv[i], "--numa-map=", 11) == 0) {
      global_num_nodes = 1;
      for (const char *c = argv[i] + 11; *c; c++)
        if (*c == ',') global_num_nodes++;

      if (g_logical_to_phys_map) free(g_logical_to_phys_map);
      g_logical_to_phys_map = malloc(global_num_nodes * sizeof(uint32_t));
      if (!g_logical_to_phys_map) return EXECUTION_FAILURE;
      const char *p = argv[i] + 11;
      for (uint32_t j = 0; j < global_num_nodes; j++) {
        g_logical_to_phys_map[j] = (uint32_t)strtoul(p, (char **)&p, 10);
        if (*p == ',') p++;
      }
    }
  }

  if (global_num_nodes == 0 || g_logical_to_phys_map == NULL) {
    global_num_nodes = 1;
    if (g_logical_to_phys_map) free(g_logical_to_phys_map);
    g_logical_to_phys_map = malloc(sizeof(uint32_t));
    if (!g_logical_to_phys_map) return EXECUTION_FAILURE;
    g_logical_to_phys_map[0] = 0;
  }

  char node_buf[32];
  snprintf(node_buf, sizeof(node_buf), "%u", global_num_nodes);
  bind_variable("FORKRUN_NUM_NODES", node_buf, 0);

  if (g_state != NULL) {
    if (global_num_nodes != allocated_num_nodes && global_num_nodes != 0) {
      builtin_error("forkrun: cannot change --nodes without calling ring_destroy first");
      return EXECUTION_FAILURE;
    }
    atomic_store_relaxed(&g_state->ingest_publish_idx, 0);
    atomic_store_relaxed(&g_state->ingest_eof_idx, ~(uint64_t)0);

    // Drain stale eventfds to prevent false EOFs
    uint64_t _drain;
    sys_read(evfd_ingest_eof, &_drain, 8);
    sys_read(evfd_ingest_data, &_drain, 8);

    for (uint32_t n = 0; n < global_num_nodes; n++) {
      atomic_store_relaxed(&state[n].chunk_queue_head, 0);
      atomic_store_relaxed(&state[n].chunk_ready_head, 0);
      atomic_store_relaxed(&state[n].chunk_queue_tail, 0);
      atomic_store_relaxed(&state[n].read_idx, 0);
      atomic_store_relaxed(&state[n].write_idx, 0);
      atomic_store_relaxed(&state[n].ingest_complete, 0);
      atomic_store_relaxed(&state[n].total_lines_consumed, 0);
      atomic_store_relaxed(&state[n].global_scanned, 0);
      atomic_store_relaxed(&state[n].min_idx, 0);
      atomic_store_relaxed(&state[n].fallow_active, 0);
      atomic_store_relaxed(&state[n].tail_idx, 0);
      atomic_store_relaxed(&state[n].scanner_finished, 0);
      atomic_store_relaxed(&state[n].stats_chunks_assigned, 0);
      atomic_store_relaxed(&state[n].stats_chunks_local, 0);
      atomic_store_relaxed(&state[n].stats_chunks_stolen, 0);

      // Reset waiters to prevent spurious initial early flushes
      atomic_store_relaxed(&state[n].active_waiters, 0);
      atomic_store_relaxed(&state[n].indexer_waiters, 0);
      atomic_store_relaxed(&state[n].meta_waiters, 0);

      state[n].offset_ring[0] = 0;
      if (fd_escrow_r && fd_escrow_r[n] >= 0) {
        char dump[1024];
        while (sys_read(fd_escrow_r[n], dump, sizeof(dump)) > 0) {}
      }
    }
    return EXECUTION_SUCCESS;
  }

  allocated_num_nodes = global_num_nodes;
  size_t total_size = sizeof(struct GlobalState) + sizeof(struct SharedState) * global_num_nodes;
  total_size = (total_size + 4095ULL) & ~4095ULL;
  void *p = mmap(NULL, total_size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
  if (p == MAP_FAILED) {
    builtin_error("mmap: %s", strerror(errno));
    return EXECUTION_FAILURE;
  }

  g_state = (struct GlobalState *)p;
  state = (struct SharedState *)(g_state + 1);
  memset(p, 0, total_size);
  atomic_store_relaxed(&g_state->ingest_eof_idx, ~(uint64_t)0);

  cfg_state = 0x202121;
  int stdin_explicit = -1;
  const char *out_array_name = NULL;
  uint64_t parsed_limit = 0;
  int64_t parsed_timeout = -1;
  uint8_t parsed_return_bytes = 0;
  uint8_t parsed_exact_lines = 0;

  for (int i = 1; i < argc; i++) {
    const char *arg = argv[i];
    if (strncmp(arg, "--workers=", 10) == 0) apply_config(0, 0, arg + 10);
    else if (strncmp(arg, "--workers0=", 11) == 0) apply_config(0, 1, arg + 11);
    else if (strncmp(arg, "--workers-max=", 14) == 0) apply_config(0, 2, arg + 14);
    else if (strncmp(arg, "--lines=", 8) == 0) apply_config(1, 0, arg + 8);
    else if (strncmp(arg, "--lines0=", 9) == 0) apply_config(1, 1, arg + 9);
    else if (strncmp(arg, "--lines-max=", 12) == 0) apply_config(1, 2, arg + 12);
    else if (strncmp(arg, "--bytes=", 8) == 0) apply_config(2, 0, arg + 8);
    else if (strncmp(arg, "--bytes0=", 9) == 0) apply_config(2, 1, arg + 9);
    else if (strncmp(arg, "--bytes-max=", 12) == 0) apply_config(2, 2, arg + 12);
    else if (strncmp(arg, "--limit=", 8) == 0) parsed_limit = (uint64_t)atoll(arg + 8);
    else if (strncmp(arg, "--timeout=", 10) == 0) parsed_timeout = atoll(arg + 10);
    else if (strncmp(arg, "--greedy", 8) == 0) parsed_timeout = 0;
    else if (strncmp(arg, "--return-bytes", 14) == 0) parsed_return_bytes = 1;
    else if (strncmp(arg, "--exact-lines", 13) == 0) parsed_exact_lines = 1;
    else if (strncmp(arg, "--out=", 6) == 0) out_array_name = arg + 6;
    else if (strncmp(arg, "--stdin", 7) == 0) stdin_explicit = 1;
    else if (strncmp(arg, "--no-stdin", 10) == 0) stdin_explicit = 0;
    else if (strncmp(arg, "--nodes=", 8) != 0 && strncmp(arg, "--numa-map=", 11) != 0 && arg[0] != '-')
      out_array_name = arg;
  }

  if (stdin_explicit != -1) {
    if (stdin_explicit) cfg_state |= M_STDIN;
    else cfg_state &= ~M_STDIN;
  } else {
    if (cfg_state & M_BMODE) cfg_state |= M_STDIN;
    else cfg_state &= ~M_STDIN;
  }

  bool stdin_mode = (cfg_state & M_STDIN);
  bool byte_mode = (cfg_state & M_BMODE);

  uint64_t vals[6], defs[6], maxs[6];
  defs[0] = get_v_def("workers", false); maxs[0] = get_v_max("workers", false);
  defs[1] = defs[0]; maxs[1] = maxs[0];
  defs[2] = get_v_def("lines", false); maxs[2] = get_v_max("lines", false);
  defs[3] = defs[2]; maxs[3] = maxs[2];
  defs[4] = get_v_def("bytes", stdin_mode); maxs[4] = get_v_max("bytes", stdin_mode);
  defs[5] = defs[4]; maxs[5] = maxs[4];

  for (int i = 0; i < 6; i++) {
    int code = (cfg_state >> (i * 4)) & 0xF;
    if (code == S_USER) vals[i] = user_vals[i];
    else if (code == S_MIN) vals[i] = 1;
    else if (code == S_DEF) vals[i] = defs[i];
    else if (code == S_MAX) vals[i] = maxs[i];
    else if (code == S_DIS) vals[i] = 0;
    else vals[i] = 1;
  }

  if (vals[0] > maxs[0]) vals[0] = maxs[0];
  if (vals[1] > maxs[1]) vals[1] = maxs[1];
  if (vals[0] > vals[1]) vals[0] = vals[1];
  if (vals[0] == 0) vals[0] = 1;
  if (vals[2] > maxs[2]) vals[2] = maxs[2];
  if (vals[3] > maxs[3]) vals[3] = maxs[3];
  if (vals[2] > vals[3]) vals[2] = vals[3];
  if (vals[4] > maxs[4]) vals[4] = maxs[4];
  if (vals[5] > maxs[5]) vals[5] = maxs[5];
  if (vals[4] > vals[5]) vals[4] = vals[5];

  for (uint32_t n = 0; n < global_num_nodes; n++) {
    uint64_t w_start_balanced = vals[0] / global_num_nodes;
    if (w_start_balanced < 1) w_start_balanced = 1;
    uint64_t w_max_balanced = vals[1] / global_num_nodes;
    if (w_max_balanced < 1) w_max_balanced = 1;

    state[n].cfg_w_start = w_start_balanced;
    state[n].cfg_w_max = w_max_balanced;
    state[n].mode_byte = byte_mode ? 1 : 0;
    state[n].numa_enabled = (global_num_nodes > 1) ? 1 : 0;
    state[n].exact_lines = parsed_exact_lines;
    state[n].cfg_limit = parsed_limit;
    state[n].cfg_timeout_us = parsed_timeout;
    state[n].cfg_return_bytes = parsed_return_bytes;

    if (byte_mode) {
      state[n].cfg_batch_start = vals[4];
      state[n].cfg_batch_max = vals[5];
      state[n].cfg_chunk_bytes = vals[5];
      state[n].cfg_line_max = vals[5];
      if (state[n].cfg_return_bytes == 0) state[n].cfg_return_bytes = 1;
    } else {
      state[n].cfg_batch_start = vals[2];
      state[n].cfg_batch_max = vals[3];
      int bb_code = (cfg_state >> SH_B_B) & 0xF;
      if (bb_code != S_DIS) state[n].cfg_line_max = vals[5];
      else state[n].cfg_line_max = maxs[4];
    }

    state[n].fixed_workers = (state[n].cfg_w_start == state[n].cfg_w_max);
    state[n].fixed_batch = (state[n].cfg_batch_start == state[n].cfg_batch_max);

    if (byte_mode) atomic_store_relaxed(&state[n].signed_batch_size, 1);
    else atomic_store_relaxed(&state[n].signed_batch_size, (int64_t)state[n].cfg_batch_start);
  }

  evfd_data_arr = malloc(global_num_nodes * sizeof(int));
  evfd_eof_arr = malloc(global_num_nodes * sizeof(int));
  evfd_indexer_arr = malloc(global_num_nodes * sizeof(int));
  evfd_meta_arr = malloc(global_num_nodes * sizeof(int));
  fd_escrow_r = malloc(global_num_nodes * sizeof(int));
  fd_escrow_w = malloc(global_num_nodes * sizeof(int));

  if (!evfd_data_arr || !evfd_eof_arr || !evfd_indexer_arr || !evfd_meta_arr || !fd_escrow_r || !fd_escrow_w) {
      builtin_error("forkrun: malloc failed during ring_init");
      return EXECUTION_FAILURE;
  }

  for (uint32_t n = 0; n < global_num_nodes; n++) {
    evfd_data_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_eof_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    evfd_indexer_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_meta_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    int pfd[2];
    if (pipe(pfd) == 0) {
      fcntl(pfd[0], F_SETFL, O_NONBLOCK); fcntl(pfd[1], F_SETFL, O_NONBLOCK);
      fcntl(pfd[0], F_SETFD, FD_CLOEXEC); fcntl(pfd[1], F_SETFD, FD_CLOEXEC);
      fcntl(pfd[1], F_SETPIPE_SZ, 1048576);
      fd_escrow_r[n] = pfd[0]; fd_escrow_w[n] = pfd[1];
    } else {
      fd_escrow_r[n] = -1; fd_escrow_w[n] = -1;
    }
  }

  evfd_ingest_data = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  evfd_ingest_eof = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  evfd_chunk_done = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);

  evfd_data = evfd_data_arr[0];
  fd_escrow[0] = fd_escrow_r[0]; fd_escrow[1] = fd_escrow_w[0];

  char buf[32];
  snprintf(buf, sizeof(buf), "%d", evfd_data_arr[0]); bind_variable("EVFD_RING_DATA", buf, 0);
  snprintf(buf, sizeof(buf), "%d", evfd_ingest_data); bind_variable("EVFD_RING_INGEST_DATA", buf, 0);
  snprintf(buf, sizeof(buf), "%d", evfd_ingest_eof); bind_variable("EVFD_RING_INGEST_EOF", buf, 0);

  if (out_array_name) {
    SHELL_VAR *v = find_variable(out_array_name);
    if (v && !array_p(v)) { unbind_variable(out_array_name); v = NULL; }
    if (!v) v = make_new_array_variable(out_array_name);
    if (!v) return EXECUTION_FAILURE;

    int *created_fds = malloc(sizeof(int) * vals[1]);
    if (!created_fds) return EXECUTION_FAILURE;
    int created_cnt = 0;
    int failure = 0;
    for (uint64_t i = 0; i < vals[1]; i++) {
      int fd = xcreate_anon_file("forkrun_out");
      if (fd >= 0) {
        created_fds[created_cnt++] = fd;
        char val[32]; snprintf(val, sizeof(val), "%d", fd);
        bind_array_element(v, i, val, 0);
      } else { failure = 1; break; }
    }
    if (failure) {
      for (int k = 0; k < created_cnt; k++) close(created_fds[k]);
      free(created_fds); return EXECUTION_FAILURE;
    }
    free(created_fds);
  }

  int probe_fd[2]; int pipe_cap = 65536;
  if (pipe(probe_fd) == 0) {
    int ret = fcntl(probe_fd[1], F_SETPIPE_SZ, 1048576);
    if (ret >= 0) pipe_cap = ret;
    else { ret = fcntl(probe_fd[1], F_GETPIPE_SZ); if (ret > 0) pipe_cap = ret; }
    close(probe_fd[0]); close(probe_fd[1]);
  }

  char var_buf[64];
  snprintf(var_buf, sizeof(var_buf), "%d", pipe_cap); bind_variable("RING_PIPE_CAPACITY", var_buf, 0);
  snprintf(var_buf, sizeof(var_buf), "%lu", state[0].cfg_line_max); bind_variable("RING_BYTES_MAX", var_buf, 0);

  return EXECUTION_SUCCESS;
}

static int ring_destroy_main(int argc, char **argv) {
  (void)argc; (void)argv;
  if (g_state) {
    size_t total_size = sizeof(struct GlobalState) + sizeof(struct SharedState) * allocated_num_nodes;
    total_size = (total_size + 4095ULL) & ~4095ULL;
    munmap(g_state, total_size); g_state = NULL; state = NULL;
  }
  if (evfd_data_arr) {
    for (uint32_t n = 0; n < allocated_num_nodes; n++) {
      if (evfd_data_arr[n] >= 0) close(evfd_data_arr[n]);
      if (evfd_eof_arr && evfd_eof_arr[n] >= 0) close(evfd_eof_arr[n]);
      if (evfd_indexer_arr && evfd_indexer_arr[n] >= 0) close(evfd_indexer_arr[n]);
      if (evfd_meta_arr && evfd_meta_arr[n] >= 0) close(evfd_meta_arr[n]);
      if (fd_escrow_r && fd_escrow_r[n] >= 0) close(fd_escrow_r[n]);
      if (fd_escrow_w && fd_escrow_w[n] >= 0) close(fd_escrow_w[n]);
    }
    free(evfd_data_arr); evfd_data_arr = NULL;
    if (evfd_eof_arr) { free(evfd_eof_arr); evfd_eof_arr = NULL; }
    if (evfd_indexer_arr) { free(evfd_indexer_arr); evfd_indexer_arr = NULL; }
    if (evfd_meta_arr) { free(evfd_meta_arr); evfd_meta_arr = NULL; }
    free(fd_escrow_r); fd_escrow_r = NULL;
    free(fd_escrow_w); fd_escrow_w = NULL;
  }
  if (g_logical_to_phys_map) { free(g_logical_to_phys_map); g_logical_to_phys_map = NULL; }
  if (evfd_ingest_data >= 0) { close(evfd_ingest_data); evfd_ingest_data = -1; }
  if (evfd_ingest_eof >= 0) { close(evfd_ingest_eof); evfd_ingest_eof = -1; }
  if (evfd_chunk_done >= 0) { close(evfd_chunk_done); evfd_chunk_done = -1; }
  unbind_variable("EVFD_RING_DATA");
  unbind_variable("EVFD_RING_INGEST_DATA"); unbind_variable("EVFD_RING_INGEST_EOF");
  return EXECUTION_SUCCESS;
}

// ==============================================================================
// 4. NUMA INGEST
// ==============================================================================

static int ring_numa_ingest_main(int argc, char **argv) {
  if (argc < 4) return EXECUTION_FAILURE;
  int infd = atoi(argv[1]); int outfd = atoi(argv[2]); int num_nodes = atoi(argv[3]);
  if (num_nodes < 1) num_nodes = 1;
  if (num_nodes > 1024) num_nodes = 1024;

  uint64_t chunk_size = 2 * 1024 * 1024ULL; // Default 2MB THP slice

  // PHYSICS FIX: Resonance Alignment. In byte mode, chunks must perfectly fit the
  // requested batch size to prevent tearing records across NUMA sockets.
  if (state[0].mode_byte) {
      uint64_t L = state[0].cfg_batch_start;
      if (L > 0) {
          uint64_t mult = (chunk_size + L - 1) / L; // Ceil division
          chunk_size = mult * L;
      }
  }

  uint64_t current_offset = 0; uint32_t current_major = 0;
  int last_target = -1;

  unsigned long test_mask = 1UL;
  bool numa_enabled = (syscall(__NR_set_mempolicy, MPOL_BIND, &test_mask, 64) == 0);
  if (numa_enabled) syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);

#define BITS_PER_LONG (sizeof(unsigned long) * 8)
  uint32_t max_phys_id = 0;
  if (g_logical_to_phys_map) {
    for (int i = 0; i < num_nodes; i++)
      if (g_logical_to_phys_map[i] > max_phys_id) max_phys_id = g_logical_to_phys_map[i];
  }
  int mask_words = (max_phys_id / BITS_PER_LONG) + 1;
  unsigned long *nodemask = malloc(mask_words * sizeof(unsigned long));
  if (!nodemask) return EXECUTION_FAILURE;

  enum { TM_UNKNOWN = 0, TM_COPY_FILE_RANGE, TM_SENDFILE, TM_READ_WRITE } transfer_method = TM_UNKNOWN;
  char *bounce_buf = NULL;
  uint64_t one = 1;

  for (int i = 0; i < num_nodes * 2; i++) {
    sys_write(evfd_chunk_done, &one, 8);
  }

  while (1) {
    int target_node = 0;
    int min_backlog = INT_MAX;
    for (int i = 0; i < num_nodes; i++) {
      int check = (last_target + 1 + i) % num_nodes;
      uint64_t h = atomic_load_relaxed(&state[check].chunk_queue_head);
      uint64_t t = atomic_load_relaxed(&state[check].chunk_queue_tail);
      int bl = (int)(h - t);
      if (bl < min_backlog) { min_backlog = bl; target_node = check; }
    }

    while (1) {
      uint64_t h = atomic_load_relaxed(&state[target_node].chunk_queue_head);
      uint64_t t = atomic_load_acquire(&state[target_node].chunk_queue_tail);
      if ((int64_t)(h - t) < 4) break;

      struct pollfd pfd = {.fd = evfd_chunk_done, .events = POLLIN};
      if (poll(&pfd, 1, 100) > 0) {
          uint64_t v;
          sys_read(evfd_chunk_done, &v, 8);
      }
    }

    if (numa_enabled && num_nodes > 1) {
      uint32_t target_phys = g_logical_to_phys_map ? g_logical_to_phys_map[target_node] : 0;
      if (target_phys < mask_words * BITS_PER_LONG) {
        memset(nodemask, 0, mask_words * sizeof(unsigned long));
        nodemask[target_phys / BITS_PER_LONG] |= (1UL << (target_phys % BITS_PER_LONG));
        syscall(__NR_set_mempolicy, MPOL_BIND, nodemask, mask_words * BITS_PER_LONG);
      }
    }

    ssize_t n = -1;

    if (transfer_method == TM_UNKNOWN) {
      if (numa_enabled && num_nodes > 1) {
          transfer_method = TM_READ_WRITE;
      } else {
          loff_t in_off = lseek(infd, 0, SEEK_CUR);
          if (in_off != (loff_t)-1) {
            n = copy_file_range(infd, NULL, outfd, NULL, chunk_size, 0);
            if (n >= 0) { transfer_method = TM_COPY_FILE_RANGE; }
            else {
              n = sendfile(outfd, infd, NULL, chunk_size);
              if (n >= 0) { transfer_method = TM_SENDFILE; }
            }
          }
          if (n < 0) {
            transfer_method = TM_READ_WRITE;
          }
      }
      if (transfer_method == TM_READ_WRITE && !bounce_buf) {
          bounce_buf = mmap(NULL, chunk_size, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
          if (bounce_buf == MAP_FAILED) return EXECUTION_FAILURE;
      }
    }

    if (transfer_method != TM_UNKNOWN) {
      switch (transfer_method) {
        case TM_COPY_FILE_RANGE:
          n = copy_file_range(infd, NULL, outfd, NULL, chunk_size, 0);
          break;
        case TM_SENDFILE:
          n = sendfile(outfd, infd, NULL, chunk_size);
          break;
        case TM_READ_WRITE:
          {
            ssize_t r = read(infd, bounce_buf, chunk_size);
            if (r < 0) {
                if (errno == EINTR) continue;
                if (errno == EAGAIN) {
                    struct pollfd pfd = {.fd = infd, .events = POLLIN};
                    poll(&pfd, 1, -1);
                    continue;
                }
                n = -1; break;
            }
            if (r == 0) { n = 0; break; }

            size_t written = 0;
            while (written < (size_t)r) {
                ssize_t w = write(outfd, bounce_buf + written, r - written);
                if (w <= 0) {
                    if (w < 0 && (errno == EINTR || errno == EAGAIN)) {
                        if (errno == EAGAIN) {
                            struct pollfd pfd = {.fd = outfd, .events = POLLOUT};
                            poll(&pfd, 1, -1);
                        } else usleep(10);
                        continue;
                    }
                    break;
                }
                written += w;
            }
            if (written == (size_t)r) n = r;
            else n = -1;
          }
          break;
        default: break;
      }
    }

    if (n < 0) {
        if (errno == EINTR) continue;
        if (errno == EAGAIN) {
            struct pollfd pfd = {.fd = infd, .events = POLLIN};
            poll(&pfd, 1, -1);
            continue;
        }
        break;
    }
    if (n == 0) break;

    struct ChunkMeta *meta = &g_state->meta_ring[current_major & META_RING_MASK];
    meta->raw_offset = current_offset; meta->raw_length = n;
    meta->target_node = target_node; meta->major_id = current_major;
    atomic_store_relaxed(&meta->actual_end, 0);

    struct SharedState *t_state = &state[target_node];
    uint64_t q_idx = atomic_load_relaxed(&t_state->chunk_queue_head);
    t_state->chunk_queue[q_idx & META_RING_MASK] = current_major;

    __atomic_store_n(&t_state->chunk_queue_head, q_idx + 1, __ATOMIC_RELEASE);
    __atomic_store_n(&g_state->ingest_publish_idx, current_major + 1, __ATOMIC_RELEASE);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);

    __atomic_fetch_add(&t_state->stats_chunks_assigned, 1, __ATOMIC_RELAXED);

    uint64_t w = atomic_load_relaxed(&t_state->indexer_waiters);
    if (w > 0) {
      sys_write(evfd_indexer_arr[target_node], &w, 8);
    }

    last_target = target_node; current_offset += n; current_major++;
  }

  if (bounce_buf) munmap(bounce_buf, chunk_size);
  if (numa_enabled) syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);
  free(nodemask);

  __atomic_store_n(&g_state->ingest_eof_idx, current_major, __ATOMIC_RELEASE);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);
  uint64_t v = 999999;
  sys_write(evfd_ingest_eof, &v, 8);
  return EXECUTION_SUCCESS;
}

static int ring_indexer_numa_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int memfd = atoi(argv[1]); int my_node_id = atoi(argv[2]);

  int phys_node = g_logical_to_phys_map ? g_logical_to_phys_map[my_node_id] : 0;
  if (pin_to_numa_node(phys_node) != 0 && g_debug) {
    fprintf(stderr, "forkrun [DEBUG] Failed to pin indexer %d to phys node %d\n", my_node_id, phys_node);
  }

  struct SharedState *t_state = &state[my_node_id];
  uint64_t my_idx = 0; char tail_buf[65536]; int spin = 0;
  bool byte_mode = t_state->mode_byte;

  while (1) {
    while (atomic_load_acquire(&t_state->chunk_queue_head) <= my_idx) {
      if (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0) {
        if (atomic_load_acquire(&t_state->chunk_queue_head) <= my_idx) return EXECUTION_SUCCESS;
      }
      if (spin < 100) { cpu_relax(); spin++; continue; }

      __atomic_fetch_add(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST);
      if (atomic_load_acquire(&t_state->chunk_queue_head) > my_idx) {
        __atomic_fetch_sub(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST); break;
      }
      struct pollfd pfds[2] = {{.fd = evfd_indexer_arr[my_node_id], .events = POLLIN}, {.fd = evfd_ingest_eof, .events = POLLIN}};
      poll(pfds, 2, -1);
      if (pfds[0].revents & POLLIN) { uint64_t v; sys_read(evfd_indexer_arr[my_node_id], &v, 8); }
      if (pfds[1].revents & POLLIN) { }
      __atomic_fetch_sub(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST); spin = 0;
    }
    spin = 0;

    uint32_t major_id = t_state->chunk_queue[my_idx & META_RING_MASK];
    struct ChunkMeta *meta = &g_state->meta_ring[major_id & META_RING_MASK];
    uint64_t chunk_end = meta->raw_offset + meta->raw_length;
    uint64_t actual_end = chunk_end;

    // PHYSICS FIX: Bypass delimiter search in byte mode!
    if (!byte_mode) {
        uint64_t search_end = chunk_end;
        while (search_end > meta->raw_offset) {
          uint64_t window_size = (search_end - meta->raw_offset > sizeof(tail_buf)) ? sizeof(tail_buf) : (search_end - meta->raw_offset);
          uint64_t window_start = search_end - window_size;
          ssize_t n;
          do { n = pread(memfd, tail_buf, window_size, window_start); } while (n < 0 && errno == EINTR);
          if (n > 0) {
            char *nl = memrchr(tail_buf, '\n', n);
            if (nl) { actual_end = window_start + (nl - tail_buf) + 1; break; }
          } else if (n < 0 && errno == EAGAIN) continue;
          else break;
          search_end = window_start;
        }
        if (search_end <= meta->raw_offset) actual_end = meta->raw_offset;
    }

    // 1. Mark meta ready
    atomic_store_release(&meta->actual_end, actual_end | FLAG_META_READY);
    // 2. Put it on the Scanner's Ready Shelf
    __atomic_store_n(&t_state->chunk_ready_head, my_idx + 1, __ATOMIC_RELEASE);

    __atomic_thread_fence(__ATOMIC_SEQ_CST);

    // 3. Exact Ticket Dispensing (Wakes all waiting scanners)
    uint32_t mw = atomic_load_relaxed(&t_state->meta_waiters);
    if (mw > 0) {
        uint64_t v = mw;
        sys_write(evfd_meta_arr[my_node_id], &v, 8);
    }
    my_idx++;
  }
}

// ==============================================================================
// 5. UNIFIED SCANNER LOOP
// ==============================================================================
#define UNIFIED_ADAPTIVE_COMMIT(force) \
  do { \
    if (local_scan_idx > local_write_idx) { \
      uint64_t W_curr = atomic_load_relaxed(&local_state->active_workers); \
      if (W_curr < 1) W_curr = 1; \
      if (force || atomic_load_relaxed(&local_state->active_waiters) > 0) { \
        atomic_store_release(&local_state->write_idx, local_scan_idx); \
        local_write_idx = local_scan_idx; \
        __atomic_thread_fence(__ATOMIC_SEQ_CST); \
        uint32_t aw = atomic_load_acquire(&local_state->active_waiters); \
        if (aw > 0) { \
          uint64_t v = aw; \
          sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8); \
        } \
      } else { \
        uint64_t r_idx = atomic_load_relaxed(&local_state->read_idx); \
        uint64_t pending = (local_scan_idx > r_idx) ? (local_scan_idx - r_idx) : 0; \
        uint64_t current_buffer = local_scan_idx - local_write_idx; \
        uint64_t target_buffer = 0; \
        if (pending >= 10 * W_curr) target_buffer = (W_curr << 2); \
        else if (pending > (W_curr << 1)) { \
          uint64_t linear = pending >> 1; \
          uint64_t intermediate = (linear < current_buffer) ? linear : current_buffer; \
          if (intermediate > W_curr) target_buffer = intermediate - W_curr; \
        } \
        uint64_t target_w = (local_scan_idx > target_buffer) ? (local_scan_idx - target_buffer) : 0; \
        if (target_w > local_write_idx) { \
          atomic_store_release(&local_state->write_idx, target_w); \
          local_write_idx = target_w; \
          __atomic_thread_fence(__ATOMIC_SEQ_CST); \
          uint32_t aw = atomic_load_acquire(&local_state->active_waiters); \
          if (aw > 0) { \
            uint64_t v = aw; \
            sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8); \
          } \
        } \
      } \
    } \
    if (force) { \
      uint32_t aw = atomic_load_acquire(&local_state->active_waiters); \
      if (aw > 0 && local_write_idx > atomic_load_relaxed(&local_state->read_idx)) { \
        uint64_t v = aw; \
        sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8); \
      } \
    } \
  } while (0)

#define UNIFIED_SCANNER_FLUSH(_cnt_val, _stride_val, _is_last, _maj_id, _minor_val, _batch_end_offset, _do_fencepost, _overwrite) \
  do { \
    while (1) { \
      uint64_t limit; \
      uint64_t uma_max_ahead = W_max_val * 64; \
      if (uma_max_ahead < 1024) uma_max_ahead = 1024; \
      if (!is_numa && atomic_load_relaxed(&local_state->fallow_active)) { \
        uint64_t r = atomic_load_acquire(&local_state->read_idx); \
        uint64_t m = atomic_load_acquire(&local_state->min_idx); \
        limit = (r > m + uma_max_ahead) ? r - uma_max_ahead : m; \
      } else { \
        limit = atomic_load_acquire(&local_state->read_idx); \
      } \
      bool limit_lines = (!is_numa) && (local_scan_idx > limit) && ((local_scan_idx - limit) >= uma_max_ahead); \
      bool limit_chunks = is_numa && (cb_head >= 3) && (limit < chunk_bounds[(cb_head - 3) & 3]); \
      if (!limit_lines && !limit_chunks) break; \
      if (atomic_load_relaxed(&local_state->active_workers) == 0) break; \
      UNIFIED_ADAPTIVE_COMMIT(true); \
      if (fd_spawn >= 0 && W < W_max_val) { \
          uint64_t _r_idx = atomic_load_relaxed(&local_state->read_idx); \
          uint64_t backlog = (local_scan_idx > _r_idx) ? local_scan_idx - _r_idx : 0; \
          uint64_t W_target = (backlog > W_max_val) ? W_max_val : backlog; \
          if (W_target > W) { \
              uint64_t needed = W_target - W; \
              char sbuf[64]; int slen; \
              if (is_numa) slen = snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, needed); \
              else slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", needed); \
              if (slen > 0) robust_pipe_write(fd_spawn, sbuf, slen); \
              W += needed; atomic_store_relaxed(&local_state->active_workers, W); \
          } \
      } \
      usleep(100); \
    } \
    uint64_t pk = (uint64_t)batch_start; \
    if ((_cnt_val) != L || (is_numa && (_is_last))) pk |= FLAG_PARTIAL_BATCH; \
    if (is_numa) { \
        local_state->stride_ring[local_scan_idx & RING_MASK] = (uint32_t)(_stride_val); \
        local_state->offset_ring[local_scan_idx & RING_MASK] = pk; \
        local_state->end_ring[local_scan_idx & RING_MASK] = (_batch_end_offset); \
        local_state->major_ring[local_scan_idx & RING_MASK] = (_maj_id); \
        local_state->minor_ring[local_scan_idx & RING_MASK] = (_minor_val) | ((_is_last) ? FLAG_MAJOR_EOF : 0); \
    } else { \
        if (!byte_mode) local_state->stride_ring[local_scan_idx & RING_MASK] = (uint32_t)(_cnt_val); \
        if (_do_fencepost) { \
            local_state->offset_ring[(local_scan_idx + 1) & RING_MASK] = (_batch_end_offset); \
            if ((pk & FLAG_PARTIAL_BATCH) || (_overwrite)) { \
                local_state->offset_ring[local_scan_idx & RING_MASK] = pk; \
            } \
        } else { \
            local_state->offset_ring[local_scan_idx & RING_MASK] = pk; \
        } \
    } \
    local_scan_idx++; \
    UNIFIED_ADAPTIVE_COMMIT(false); \
  } while (0)

#define ADAPTIVE_FLOW_CONTROL(state_ptr, is_stalled, _node_id_arg)             \
  do {                                                                         \
    batch_counter++; batches_since_calc++; uint64_t _tc = W * 4;               \
    if (_tc < 4) _tc = 4;                                                      \
    if (!fixed_batch && !byte_mode) {                                          \
      if (phase == 0) { if (batch_counter >= _tc) { phase = 1; batch_counter = 0; } } \
      else if (phase == 1) {                                                   \
        if (is_stalled) phase = 2;                                             \
        else if (batch_counter >= _tc) {                                       \
          L *= 2; if (L >= Lmax) { L = Lmax; phase = 2; }                      \
          if (W < W_max_val && !fixed_workers) {                               \
            uint64_t _l_log = fast_log2(L); uint64_t _den = X_const * (L2 + _l_log); \
            if (_den == 0) _den = 1;                                           \
            uint64_t _n_spawn = (6 * (W_max_val - W) * L2) / _den;             \
            if (_n_spawn < 1) _n_spawn = 1;                                    \
            if (_n_spawn > (W_max_val - W)) _n_spawn = W_max_val - W;          \
            if (fd_spawn >= 0) {                                               \
              char _sbuf[64]; int _slen;                                       \
              if ((int)(_node_id_arg) >= 0) _slen = snprintf(_sbuf, sizeof(_sbuf), "%d:%lu\n", (int)(_node_id_arg), _n_spawn); \
              else _slen = snprintf(_sbuf, sizeof(_sbuf), "%lu\n", _n_spawn);  \
              if (_slen > 0) robust_pipe_write(fd_spawn, _sbuf, _slen);        \
              W += _n_spawn; atomic_store_relaxed(&(state_ptr)->active_workers, W); \
            }                                                                  \
          }                                                                    \
          atomic_store_release(&(state_ptr)->batch_change_idx, local_scan_idx); \
          atomic_store_release(&(state_ptr)->signed_batch_size, -(int64_t)L);  \
          batch_counter = 0;                                                   \
        }                                                                      \
      }                                                                        \
    }                                                                          \
    uint64_t _now_us = get_us_time();                                          \
    if (_now_us - last_calc_us > 5000 || batches_since_calc >= W) {            \
      uint64_t _d_in = local_write_idx - last_calc_write;                      \
      uint64_t _r_con = atomic_load_relaxed(&(state_ptr)->total_lines_consumed); \
      uint64_t _d_out = _r_con - last_calc_read;                               \
      last_calc_write = local_write_idx; last_calc_read = _r_con; last_calc_us = _now_us; batches_since_calc = 0; \
      if (!fixed_workers && W < W_max_val) {                                   \
        uint64_t _backlog = local_scan_idx - atomic_load_relaxed(&(state_ptr)->read_idx); \
        bool _no_starve = (atomic_load_relaxed(&(state_ptr)->active_waiters) == 0); \
        bool _spawn = false;                                                   \
        if (fixed_batch || byte_mode) { if ((_backlog > W || byte_mode) && _no_starve) _spawn = true; } \
        else {                                                                 \
          if (_d_out > 0) { uint64_t _rate = _d_out / W; if (_rate == 0) _rate = 1; if ((_d_in / _rate) > W) _spawn = true; } \
          else if (_backlog > (W * 4) && _no_starve) { _spawn = true; }        \
        }                                                                      \
        if (_spawn && phase != 1) {                                            \
          uint64_t _grow = fixed_batch ? 1 : ((W + 1) / 2);                    \
          if (byte_mode) _grow = W_max_val - W;                                \
          if (W + _grow > W_max_val) _grow = W_max_val - W;                    \
          if (_grow > 0 && fd_spawn >= 0) {                                    \
            char _sbuf[64]; int _slen;                                         \
            if ((int)(_node_id_arg) >= 0) _slen = snprintf(_sbuf, sizeof(_sbuf), "%d:%lu\n", (int)(_node_id_arg), _grow); \
            else _slen = snprintf(_sbuf, sizeof(_sbuf), "%lu\n", _grow);       \
            if (_slen > 0) robust_pipe_write(fd_spawn, _sbuf, _slen);          \
            W += _grow; atomic_store_relaxed(&(state_ptr)->active_workers, W); \
          }                                                                    \
        }                                                                      \
      }                                                                        \
      if (!fixed_batch && !byte_mode && phase == 2) {                          \
        int64_t _pending_slots = (int64_t)local_write_idx - (int64_t)atomic_load_relaxed(&(state_ptr)->read_idx); \
        if (_pending_slots < 0) _pending_slots = 0;                            \
        int64_t _bl = _pending_slots * (int64_t)L;                             \
        uint64_t _l_target = (uint64_t)_bl / W;                                \
        if (_l_target > Lmax) _l_target = Lmax;                                \
        if (_l_target < 1) _l_target = 1;                                      \
        if (_l_target > L) {                                                   \
          L = _l_target;                                                       \
          atomic_store_release(&(state_ptr)->batch_change_idx, local_scan_idx); \
          atomic_store_release(&(state_ptr)->signed_batch_size, -(int64_t)L);  \
        } else if (_l_target < L && starve_meter >= (W + DAMPING_OFFSET - 3) && stall_meter >= (W + DAMPING_OFFSET - 3)) { \
          L = (L + _l_target) / 2; if (L < 1) L = 1;                           \
          atomic_store_release(&(state_ptr)->batch_change_idx, local_scan_idx); \
          atomic_store_release(&(state_ptr)->signed_batch_size, -(int64_t)L);  \
          starve_meter = 0; stall_meter = 0;                                   \
        }                                                                      \
      }                                                                        \
    }                                                                          \
  } while (0)

// The Core Unified Scanner Function
static inline __attribute__((always_inline)) int
core_scanner_loop(int fd_or_memfd, int my_node_id, int fd_spawn, int num_nodes, const bool is_numa)
{
    struct SharedState *local_state = is_numa ? &state[my_node_id] : &state[0];

    uint64_t L = local_state->cfg_batch_start;
    uint64_t Lmax = local_state->cfg_batch_max;
    uint64_t W = local_state->cfg_w_start;
    uint64_t W_max_val = local_state->cfg_w_max;
    uint64_t BytesMax = local_state->cfg_line_max;
    int64_t timeout_us = local_state->cfg_timeout_us;
    bool byte_mode = local_state->mode_byte;
    bool fixed_batch = local_state->fixed_batch;
    bool fixed_workers = local_state->fixed_workers;
    bool return_bytes = local_state->cfg_return_bytes;
    bool exact_lines = local_state->exact_lines;

    uint64_t W2 = fast_log2(W_max_val);
    uint64_t L2 = fast_log2(Lmax);
    uint64_t X_const = fast_log2(W2 + L2) * W2;
    if (X_const == 0) X_const = 1;

    uint64_t local_scan_idx = 0;
    uint64_t local_write_idx = 0;

    size_t chunk_sz = get_optimal_chunk_size();

    if (byte_mode && L > 0) {
        uint64_t mult = (chunk_sz + L - 1) / L;
        chunk_sz = mult * L;
    }

    char *buf = mmap(NULL, chunk_sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (buf == MAP_FAILED) return EXECUTION_FAILURE;

    char *p = buf, *end = buf;

    uint64_t buf_base_offset = is_numa ? 0 : lseek(fd_or_memfd, 0, SEEK_CUR);
    uint64_t batch_start = buf_base_offset;

    int phase = 0;
    uint64_t batch_counter = 0;
    uint64_t last_calc_us = get_us_time();
    uint64_t last_calc_write = 0;
    uint64_t last_calc_read = 0;
    uint64_t starve_meter = 0;
    uint64_t stall_meter = 0;
    uint64_t batches_since_calc = 0;

    uint64_t total_scanned = 0;
    uint64_t first_wait_ts = 0;
    uint64_t limit_items = local_state->cfg_limit;

    uint64_t chunk_bounds[4] = {0};
    uint32_t cb_head = 0;

    atomic_store_relaxed(&local_state->write_idx, 0);
    atomic_store_relaxed(&local_state->read_idx, 0);
    if (!is_numa) atomic_store_relaxed(&local_state->tail_idx, 0);
    atomic_store_relaxed(&local_state->active_workers, W);

    if (fd_spawn >= 0 && W > 0) {
        char sbuf[64]; int slen;
        if (is_numa) slen = snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, W);
        else slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", W);
        if (slen > 0) robust_pipe_write(fd_spawn, sbuf, slen);
    }

    bool experienced_stall = false;
    uint64_t pending_lines = 0;

    int status = 0;
    bool force_refill = false;

    while (1) {
        uint64_t chunk_end = ~(uint64_t)0;
        uint64_t current_p_offset;
        struct ChunkMeta *meta = NULL;
        uint32_t minor_idx = 0;
        bool chunk_eof_flushed = false;

        // =========================================================
        // 1. ACQUISITION PHASE
        // =========================================================
        if (is_numa) {
            int steal_target = my_node_id;
            struct SharedState *t_state = &state[my_node_id];

            uint64_t my_tail = atomic_load_relaxed(&t_state->chunk_queue_tail);
            uint64_t my_head = atomic_load_acquire(&t_state->chunk_ready_head);

            if (my_tail >= my_head) {
                bool is_eof = (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0);
                bool workers_starved = (atomic_load_relaxed(&local_state->read_idx) == atomic_load_relaxed(&local_state->write_idx));

                int required_bl = (is_eof && workers_starved) ? 1 : 2;
                int max_bl = 0, best_ready_bl = 0, ready_target = -1, fallback_target = -1;

                for (int i = 0; i < num_nodes; i++) {
                    uint64_t h = atomic_load_acquire(&state[i].chunk_ready_head);
                    uint64_t t = atomic_load_relaxed(&state[i].chunk_queue_tail);
                    if (h > t) {
                        int bl = (int)(h - t);
                        if (bl > max_bl) { max_bl = bl; fallback_target = i; }

                        bool ready = true;
                        if (atomic_load_acquire(&state[i].write_idx) == 0) ready = false;
                        if (ready && bl > best_ready_bl) { best_ready_bl = bl; ready_target = i; }
                    }
                }

                if (max_bl == 0) {
                    uint64_t eof_target = atomic_load_acquire(&g_state->ingest_eof_idx);
                    if (eof_target != ~(uint64_t)0) {
                        uint64_t total_claimed = 0;
                        for (int i = 0; i < num_nodes; i++) {
                            total_claimed += atomic_load_acquire(&state[i].chunk_queue_tail);
                        }
                        if (total_claimed >= eof_target) {
                            goto unified_scanner_eof;
                        }
                    }
                } else {
                    if (ready_target != -1 && best_ready_bl >= required_bl) steal_target = ready_target;
                    else if (fallback_target != -1 && max_bl >= required_bl) steal_target = fallback_target;
                }

                // FIXED NUMA LATENCY BUBBLE: Don't claim an empty local queue
                if (steal_target == my_node_id) {
                    cpu_relax();
                    continue;
                }
                t_state = &state[steal_target];
            }

            uint64_t claim_idx = __atomic_fetch_add(&t_state->chunk_queue_tail, 1, __ATOMIC_SEQ_CST);

            uint64_t _one = 1;
            sys_write(evfd_chunk_done, &_one, 8);

            int meta_spin = 0;
            while (atomic_load_acquire(&t_state->chunk_ready_head) <= claim_idx) {
                if (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0) {
                    if (atomic_load_acquire(&t_state->chunk_queue_head) <= claim_idx) break;
                }

                if (atomic_load_acquire(&t_state->chunk_queue_head) <= claim_idx) {
                    experienced_stall = true;
                }

                if (meta_spin < 10000) { cpu_relax(); meta_spin++; }
                else {
                    __atomic_fetch_add(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
                    if (atomic_load_acquire(&t_state->chunk_ready_head) > claim_idx) {
                        __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST); break;
                    }
                    struct pollfd pfd = {.fd = evfd_meta_arr[steal_target], .events = POLLIN};
                    poll(&pfd, 1, 10);
                    if (pfd.revents & POLLIN) { uint64_t v; sys_read(evfd_meta_arr[steal_target], &v, 8); }
                    __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
                    meta_spin = 0;
                }
            }

            if (atomic_load_acquire(&t_state->chunk_ready_head) <= claim_idx) {
                __atomic_fetch_sub(&t_state->chunk_queue_tail, 1, __ATOMIC_SEQ_CST);
                continue;
            }

            if (steal_target == my_node_id) {
                __atomic_fetch_add(&t_state->stats_chunks_local, 1, __ATOMIC_RELAXED);
            } else {
                __atomic_fetch_add(&t_state->stats_chunks_stolen, 1, __ATOMIC_RELAXED);
            }

            uint32_t current_major = t_state->chunk_queue[claim_idx & META_RING_MASK];
            meta = &g_state->meta_ring[current_major & META_RING_MASK];

            uint64_t act_end_flag = atomic_load_acquire(&meta->actual_end);
            uint64_t actual_end = act_end_flag & ~FLAG_META_READY;

            uint64_t actual_start = 0;
            if (current_major > 0) {
                struct ChunkMeta *prev_meta = &g_state->meta_ring[(current_major - 1) & META_RING_MASK];
                uint64_t prev_act_end; int _pe_spin = 0;
                while (!((prev_act_end = atomic_load_acquire(&prev_meta->actual_end)) & FLAG_META_READY)) {
                    if (_pe_spin < 10000) {
                        cpu_relax(); _pe_spin++;
                    } else {
                        uint32_t tnode = prev_meta->target_node;
                        __atomic_fetch_add(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
                        if (atomic_load_acquire(&prev_meta->actual_end) & FLAG_META_READY) {
                            __atomic_fetch_sub(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
                            break;
                        }
                        struct pollfd pfd = {.fd = evfd_meta_arr[tnode], .events = POLLIN};
                        poll(&pfd, 1, 10);
                        if (pfd.revents & POLLIN) { uint64_t v; sys_read(evfd_meta_arr[tnode], &v, 8); }
                        __atomic_fetch_sub(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
                        _pe_spin = 0;
                    }
                }
                actual_start = prev_act_end & ~FLAG_META_READY;
            }

            if (actual_start >= actual_end) {
                UNIFIED_SCANNER_FLUSH(0, 0, true, meta->major_id, 0, actual_start, false, false);
                if (is_numa) {
                    chunk_bounds[cb_head & 3] = local_scan_idx;
                    cb_head++;
                }
                UNIFIED_ADAPTIVE_COMMIT(true);
                continue;
            }

            chunk_end = actual_end;
            current_p_offset = actual_start;
            batch_start = current_p_offset;
            buf_base_offset = current_p_offset;
            p = buf; end = buf;

        } else {
            if (status == 1 && p >= end) break;
            current_p_offset = buf_base_offset + (uint64_t)(p - buf);
        }

        bool current_stall = experienced_stall;
        experienced_stall = false;

        {
            uint64_t _xLim = W + DAMPING_OFFSET;
            if (current_stall || (!is_numa && atomic_load_relaxed(&local_state->active_waiters) > 0))
                stall_meter = (stall_meter + _xLim) >> 1;
            else stall_meter >>= 1;

            if (atomic_load_relaxed(&local_state->active_waiters) > 0)
                starve_meter = (starve_meter + _xLim) >> 1;
            else starve_meter >>= 1;
        }

        // =========================================================
        // 2. INNER SCAN LOOP (Shared Hot Path)
        // =========================================================
        while ((is_numa && current_p_offset < chunk_end) || (!is_numa && (status != 1 || p < end))) {

            if (!is_numa && (p >= end || force_refill) && status != 1) {
                force_refill = false;
                uint64_t prev_avail = (p < end) ? (uint64_t)(end - p) : 0;
                current_p_offset = buf_base_offset + (uint64_t)(p - buf);

                ssize_t n;
                do { n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset); } while (n < 0 && errno == EINTR);

                if (n > 0 && (uint64_t)n > prev_avail) {
                    buf_base_offset = current_p_offset; p = buf; end = buf + n; status = 0; stall_meter >>= 1;
                } else {
                    if (n > 0) { buf_base_offset = current_p_offset; p = buf; end = buf + n; }

                    if (!atomic_load_acquire(&local_state->ingest_complete)) {
                        struct pollfd pfds[2] = {{.fd = evfd_ingest_data, .events = POLLIN}, {.fd = evfd_ingest_eof, .events = POLLIN}};
                        if (poll(pfds, 2, 0) > 0) {
                            if (pfds[1].revents & POLLIN) atomic_store_release(&local_state->ingest_complete, 1);
                        }
                    }
                    if (atomic_load_acquire(&local_state->ingest_complete)) {
                        if (n == 0 || (n > 0 && (uint64_t)n <= prev_avail)) status = 1;
                    } else {
                        status = 0;
                        bool starving = (atomic_load_relaxed(&local_state->active_waiters) > 0);
                        UNIFIED_ADAPTIVE_COMMIT(starving);

                        int poll_timeout = 100;
                        if (starving && timeout_us >= 0) {
                            if (first_wait_ts == 0) first_wait_ts = get_us_time();
                            uint64_t now = get_us_time();
                            if (timeout_us == 0 || (now - first_wait_ts >= (uint64_t)timeout_us)) poll_timeout = 0;
                            else {
                                uint64_t rem = (timeout_us - (now - first_wait_ts)) / 1000;
                                poll_timeout = (rem > 100) ? 100 : (int)rem;
                            }
                        } else first_wait_ts = 0;

                        struct pollfd pfds[2] = {{.fd = evfd_ingest_data, .events = POLLIN}, {.fd = evfd_ingest_eof, .events = POLLIN}};
                        if (poll(pfds, 2, poll_timeout) > 0) {
                            if (pfds[0].revents & POLLIN) { uint64_t v; sys_read(evfd_ingest_data, &v, 8); }
                            if (pfds[1].revents & POLLIN) atomic_store_release(&local_state->ingest_complete, 1);
                        }
                        current_stall = true;
                        stall_meter = (stall_meter + (W + DAMPING_OFFSET)) >> 1;
                        if (p < end) force_refill = true;
                        continue;
                    }
                }
            }

            bool flush = false;
            bool limit_reached = false;

            if (byte_mode) {
                uint64_t avail = is_numa ? (chunk_end - current_p_offset) : (uint64_t)(end - p);
                uint64_t take = 0;

                if (limit_items > 0) {
                    if (!is_numa && total_scanned >= limit_items) { status = 1; break; }
                    if (is_numa) {
                        uint64_t prev = __atomic_fetch_add(&state[0].global_scanned, (avail >= L ? L : avail), __ATOMIC_SEQ_CST);
                        if (prev >= limit_items) break;
                    }
                }

                if (avail >= L) {
                    take = L; flush = true; first_wait_ts = 0;
                } else if (avail > 0) {
                    if ((!is_numa && status == 1) || is_numa) {
                        take = avail; flush = true;
                    } else if (atomic_load_relaxed(&local_state->active_waiters) > 0) {
                        if (timeout_us == 0) { take = avail; flush = true; }
                        else if (timeout_us > 0 && first_wait_ts > 0 && (get_us_time() - first_wait_ts >= (uint64_t)timeout_us)) {
                            take = avail; flush = true; first_wait_ts = 0;
                        }
                    }
                }

                if (flush) {
                    current_p_offset = is_numa ? (current_p_offset + take) : (buf_base_offset + (uint64_t)(p - buf) + take);
                    if (!is_numa) pending_lines = 0;

                    bool is_last = is_numa ? (current_p_offset >= chunk_end) : false;
                    uint32_t stride = is_numa ? (uint32_t)(current_p_offset - batch_start) : 1;
                    uint32_t cv = is_numa ? take : 1;

                    UNIFIED_SCANNER_FLUSH(cv, stride, is_last, is_numa ? meta->major_id : 0, minor_idx, current_p_offset, true, false);
                    if (is_last) chunk_eof_flushed = true;
                    if (is_numa) {
                        minor_idx++;
                        if (is_last) {
                            chunk_bounds[cb_head & 3] = local_scan_idx;
                            cb_head++;
                        }
                    }

                    p += take; batch_start += is_numa ? take : current_p_offset - batch_start;
                    total_scanned += is_numa ? take : 1;
                    pending_lines = 0;
                } else {
                    if (!is_numa) force_refill = true;
                }
            } else {
                uint64_t scan_target = (L > pending_lines) ? (L - pending_lines) : 0;
                if (limit_items > 0) {
                    uint64_t current_global = is_numa ? atomic_load_relaxed(&state[0].global_scanned) : total_scanned;
                    if (current_global >= limit_items) { if (!is_numa) status = 1; break; }
                    uint64_t rem = limit_items - current_global;
                    if (scan_target > rem) scan_target = rem;
                    if (!is_numa && rem == 0) { status = 1; scan_target = 0; }
                }
                if (scan_target == 0 && !limit_reached && (!is_numa ? status != 1 : true)) scan_target = 1;

                uint64_t lines_found = 0;
                char delim = '\n';

                char *safe_end = end;
                if (BytesMax > 0) {
                    uint64_t max_overhead = (scan_target + 1) * 8;
                    if (BytesMax <= max_overhead) safe_end = p;
                    else {
                        uint64_t max_payload = BytesMax - max_overhead;
                        uint64_t current_payload = (buf_base_offset + (p - buf)) - batch_start;
                        if (current_payload >= max_payload) safe_end = p;
                        else if (max_payload - current_payload < (uint64_t)(end - p)) {
                            safe_end = p + (max_payload - current_payload);
                        }
                    }
                }

                char *simd_res = try_simd_scan(p, safe_end, scan_target, delim);
                if (simd_res) {
                    lines_found = scan_target;
                    p = simd_res;
                } else {
                    while (lines_found < scan_target) {
                        if (p >= end) {
                            if (is_numa) {
                                uint64_t read_start = buf_base_offset + (p - buf);
                                size_t to_read = chunk_sz;
                                if (read_start + to_read > chunk_end) to_read = chunk_end - read_start;
                                if (to_read > 0) {
                                    ssize_t n;
                                    do { n = pread(fd_or_memfd, buf, to_read, read_start); } while (n < 0 && errno == EINTR);
                                    if (n > 0) { buf_base_offset = read_start; p = buf; end = buf + n; }
                                    else { chunk_end = buf_base_offset + (end - buf); break; }
                                } else break;
                            } else {
                                break;
                            }
                        }

                        char *nl = memchr(p, delim, end - p);
                        if (nl) {
                            if (BytesMax > 0 && lines_found > 0) {
                                uint64_t line_end_offset = buf_base_offset + (uint64_t)((nl + 1) - buf);
                                uint64_t payload = line_end_offset - batch_start;
                                uint64_t overhead = (lines_found + 1) * 8;
                                if ((payload + overhead) > BytesMax) { limit_reached = true; break; }
                            }
                            lines_found++;
                            p = nl + 1;
                        } else {
                            if (is_numa) {
                                uint64_t curr_pos = buf_base_offset + (end - buf);
                                if (curr_pos >= chunk_end) { lines_found++; p = end; break; }
                                else p = end;
                            } else {
                                if (status == 1 && p < end) { lines_found++; p = end; }
                                break;
                            }
                        }
                    }
                }

                if (is_numa && limit_items > 0 && lines_found > 0) {
                    uint64_t prev = __atomic_fetch_add(&state[0].global_scanned, lines_found, __ATOMIC_SEQ_CST);
                    if (prev >= limit_items) { lines_found = 0; limit_reached = true; break; }
                    else if (prev + lines_found >= limit_items) limit_reached = true;
                }

                pending_lines += lines_found;
                total_scanned += lines_found;
                current_p_offset = buf_base_offset + (p - buf);

                if (!is_numa && limit_items > 0 && total_scanned >= limit_items) status = 1;

                if (pending_lines > 0) {
                    if (pending_lines >= L || limit_reached || (is_numa && current_p_offset >= chunk_end) || (!is_numa && status == 1)) {
                        flush = true;
                    } else if (starve_meter >= (W + DAMPING_OFFSET - 3)) {
                        bool trigger = (stall_meter >= (W + DAMPING_OFFSET - 3));
                        if (trigger && !exact_lines) {
                            if (timeout_us == 0) flush = true;
                            else if (timeout_us > 0) {
                                if (first_wait_ts == 0) first_wait_ts = get_us_time();
                                if (get_us_time() - first_wait_ts >= (uint64_t)timeout_us) flush = true;
                            }
                        }
                    }
                    if (flush) first_wait_ts = 0;
                } else if (!is_numa) force_refill = true;

                if (flush) {
                    bool is_last = is_numa ? (current_p_offset >= chunk_end || limit_reached) : false;
                    uint32_t stride = is_numa ? (return_bytes ? (uint32_t)(current_p_offset - batch_start) : (uint32_t)pending_lines) : 0;

                    UNIFIED_SCANNER_FLUSH(pending_lines, stride, is_last, is_numa ? meta->major_id : 0, minor_idx, current_p_offset, return_bytes, false);
                    if (is_last) chunk_eof_flushed = true;
                    if (is_numa) {
                        minor_idx++;
                        if (is_last) {
                            chunk_bounds[cb_head & 3] = local_scan_idx;
                            cb_head++;
                        }
                    }
                    batch_start = current_p_offset;
                    pending_lines = 0;

                    int node_arg = is_numa ? my_node_id : -1;
                    ADAPTIVE_FLOW_CONTROL(local_state, current_stall, node_arg);
                } else if (!is_numa) force_refill = true;
            }
            if (limit_reached) break;
        }

        if (is_numa && !chunk_eof_flushed) {
            uint32_t stride = return_bytes ? (uint32_t)(current_p_offset - batch_start) : (uint32_t)pending_lines;
            UNIFIED_SCANNER_FLUSH(pending_lines, stride, true, meta->major_id, minor_idx, current_p_offset, return_bytes, false);
            minor_idx++;
            chunk_bounds[cb_head & 3] = local_scan_idx;
            cb_head++;
            batch_start = current_p_offset;
            pending_lines = 0;
        }

        if (is_numa) {
            UNIFIED_ADAPTIVE_COMMIT(true);
            if (limit_items > 0 && atomic_load_relaxed(&state[0].global_scanned) >= limit_items) break;
        }
    }

unified_scanner_eof:
    // =========================================================
    // 3. FINALIZATION (NUMA Finish vs UMA Tail Re-batching)
    // =========================================================

    if (is_numa) {
        if (!byte_mode && !fixed_batch) {
            atomic_store_release(&local_state->signed_batch_size, -(int64_t)Lmax);
        }
        atomic_store_release(&local_state->write_idx, local_scan_idx);
        atomic_store_release(&local_state->scanner_finished, 1);

        // NEW STANDING WAVE EOF SIGNAL (NUMA)
        uint64_t blast = 1;
        sys_write(evfd_eof_arr[my_node_id], &blast, 8);
    } else {
        if (!byte_mode) {
            uint64_t L_tail = pending_lines;
            char *p_scan = p; char delim = '\n';
            while (p_scan < end) {
                char *nl = memchr(p_scan, delim, end - p_scan);
                if (nl) { L_tail++; p_scan = nl + 1; }
                else { if (p_scan < end) L_tail++; break; }
            }
            if (local_scan_idx > local_write_idx) {
                for (uint64_t i = local_write_idx; i < local_scan_idx; i++) L_tail += state[0].stride_ring[i & RING_MASK];
            }

            uint64_t tail_start_offset = (local_scan_idx > local_write_idx) ? (state[0].offset_ring[local_write_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH) : batch_start;
            local_scan_idx = local_write_idx;
            int64_t buf_rel = (int64_t)tail_start_offset - (int64_t)buf_base_offset;
            if (buf_rel >= 0 && buf_rel < (int64_t)chunk_sz) { p = buf + buf_rel; batch_start = tail_start_offset; }
            else {
                buf_base_offset = tail_start_offset; batch_start = tail_start_offset;
                ssize_t n;
                do { n = pread(fd_or_memfd, buf, chunk_sz, (off_t)tail_start_offset); } while (n < 0 && errno == EINTR);
                p = buf; end = buf + (n > 0 ? n : 0);
            }
            uint64_t R = 1;
            if (L > 0) { uint64_t inner_log = fast_log2(2 + L); R = fast_log2(2 + inner_log); }
            if (R < 1) R = 1;
            uint64_t L_tail_done = 0;
            atomic_store_release(&state[0].tail_idx, local_write_idx);

            while (L_tail_done < L_tail) {
                uint64_t target = (L_tail > 0) ? (L * (L_tail - L_tail_done)) / L_tail : 0;
                uint64_t min_batch = L / R; if (min_batch < 1) min_batch = 1;
                if (target < min_batch) target = min_batch;

                uint64_t lines_found = 0;
                while (lines_found < target && (lines_found + L_tail_done) < L_tail) {
                    if (p >= end) {
                        uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                        ssize_t n;
                        do { n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset); } while (n < 0 && errno == EINTR);
                        if (n > 0) { buf_base_offset = current_p_offset; p = buf; end = buf + n; }
                        else break;
                    }
                    char *nl = memchr(p, delim, end - p);
                    if (nl) { lines_found++; p = nl + 1; }
                    else {
                        uint64_t current_p_offset = buf_base_offset + (uint64_t)(end - buf);
                        ssize_t n;
                        do { n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset); } while (n < 0 && errno == EINTR);
                        if (n > 0) { buf_base_offset = current_p_offset; p = buf; end = buf + n; }
                        else { p = end; break; }
                    }
                }
                if (lines_found < target && (lines_found + L_tail_done) < L_tail) {
                    if (p >= end) { uint64_t remainder = L_tail - L_tail_done - lines_found; lines_found += remainder; }
                }
                if (lines_found > 0) {
                    uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
                    UNIFIED_SCANNER_FLUSH(lines_found, 0, false, 0, 0, current_p_offset, true, true);
                    batch_start = current_p_offset; L_tail_done += lines_found;
                } else break;
            }
        }

        uint64_t final_sentinel = buf_base_offset + (uint64_t)(p - buf);
        local_state->offset_ring[local_scan_idx & RING_MASK] = (uint64_t)final_sentinel | FLAG_PARTIAL_BATCH;
        local_state->offset_ring[(local_scan_idx + 1) & RING_MASK] = (uint64_t)final_sentinel;
        local_scan_idx++;

        atomic_store_release(&local_state->write_idx, local_scan_idx);
        atomic_store_release(&local_state->scanner_finished, 1);

        // NEW STANDING WAVE EOF SIGNAL (UMA)
        uint64_t blast = 1;
        sys_write(evfd_eof_arr[0], &blast, 8);
    }

    if (fd_spawn >= 0) {
        uint64_t W_curr = atomic_load_relaxed(&local_state->active_workers);
        if (W_curr < W_max_val) {
            uint64_t r_idx = atomic_load_relaxed(&local_state->read_idx);
            uint64_t backlog = (local_scan_idx > r_idx) ? local_scan_idx - r_idx : 0;
            uint64_t W_target = (backlog > W_max_val) ? W_max_val : backlog;
            if (W_target > W_curr) {
                uint64_t needed = W_target - W_curr;
                if (needed > 0) {
                    char sbuf[64]; int slen;
                    if (is_numa) slen = snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, needed);
                    else slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", needed);
                    if (slen > 0) robust_pipe_write(fd_spawn, sbuf, slen);
                    W += needed; atomic_store_relaxed(&local_state->active_workers, W);
                }
            }
        }
        robust_pipe_write(fd_spawn, "x\n", 2);
    }

    munmap(buf, chunk_sz);
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// 6. SCANNER WRAPPER ENTRY POINTS
// ==============================================================================

static int ring_scanner_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    int fd_spawn = (argc >= 3) ? atoi(argv[2]) : -1;
    // Call Unified Loop with is_numa = false
    return core_scanner_loop(fd, 0, fd_spawn, 1, false);
}

static int ring_numa_scanner_main(int argc, char **argv) {
    if (argc < 5) return EXECUTION_FAILURE;
    int memfd = atoi(argv[1]);
    int my_node_id = atoi(argv[2]);
    int fd_spawn = atoi(argv[3]);
    int num_nodes = atoi(argv[4]);
    // Call Unified Loop with is_numa = true
    return core_scanner_loop(memfd, my_node_id, fd_spawn, num_nodes, true);
}

// ==============================================================================
// 7. CONSUMERS (Claim, Ack, Order)
// ==============================================================================

static int ring_claim_main(int argc, char **argv) {
  const char *v_target = "REPLY";
  int fd_read = -1;

  if (argc >= 4 && isdigit(argv[argc - 1][0]) && !isdigit(argv[argc - 2][0])) {
    v_target = argv[2];
    fd_read = atoi(argv[3]);
  } else if (argc >= 2) {
    if (isdigit(argv[1][0])) {
      fd_read = atoi(argv[1]);
    } else {
      v_target = argv[1];
      if (argc >= 3)
        fd_read = atoi(argv[2]);
    }
  }

  if (my_numa_node == -1) {
    const char *s_node = get_string_value("RING_NODE_ID");
    if (s_node) {
      my_numa_node = atoi(s_node);
    } else {
      int phys = auto_detect_numa_node();
      my_numa_node = 0;
      bool found = false;
      if (g_logical_to_phys_map) {
        for (uint32_t i = 0; i < global_num_nodes; i++) {
          if (g_logical_to_phys_map[i] == (uint32_t)phys) {
            my_numa_node = i;
            found = true;
            break;
          }
        }
      }
      if (!found && g_debug && global_num_nodes > 1) {
        fprintf(stderr,
                "forkrun[DEBUG] Worker on unmapped physical node %d, "
                "defaulting to logical 0\n",
                phys);
      }
    }
    if (my_numa_node >= (int)global_num_nodes)
      my_numa_node = 0;
  }
  struct SharedState *local_state = &state[my_numa_node];

  uint64_t my_read_idx;
  uint64_t claim_count = 1;
  int spin = 0;

  if (fd_read < 0)
    fd_read = worker_cached_fd;

restart_loop:
  while (1) {
    // 1. Ring check FIRST
    uint64_t w_snap = atomic_load_acquire(&local_state->write_idx);
    uint64_t r_curr = atomic_load_relaxed(&local_state->read_idx);

    if (r_curr < w_snap) {
      int64_t sbatch = atomic_load_relaxed(&local_state->signed_batch_size);
      claim_count = 1;
      if (sbatch < 0) {
        uint64_t t_start = atomic_load_acquire(&local_state->tail_idx);
        if (t_start != 0 && r_curr >= t_start) {
          claim_count = 1;
          if (sbatch < 0) {
            int64_t abs_L = -sbatch;
            atomic_store_relaxed(&local_state->signed_batch_size, abs_L);
          }
        } else {
          if (local_state->cfg_return_bytes) {
              claim_count = 1;
          } else {
              uint32_t L0 = local_state->stride_ring[r_curr & RING_MASK];
              if (L0 == 0)
                L0 = 1;
              uint64_t Wmax = atomic_load_relaxed(&local_state->active_workers);
              if (Wmax == 0)
                Wmax = 1;
              uint64_t B = ((uint64_t)(-sbatch)) / L0;
              if (B > Wmax)
                B = Wmax;
              if (B < 1)
                B = 1;
              claim_count = B;
              if (claim_count > 64)
                claim_count = 64;
          }
        }
      }

      if (r_curr + claim_count > w_snap)
        claim_count = w_snap - r_curr;

      if (claim_count > 1) {
        uint64_t safe_count = 1;
        for (uint64_t i = 0; i < claim_count; i++) {
          if (local_state->offset_ring[(r_curr + i) & RING_MASK] &
              FLAG_PARTIAL_BATCH) {
            safe_count = i + 1;
            break;
          }
        }
        claim_count = safe_count;
      }

      my_read_idx = __atomic_fetch_add(&local_state->read_idx, claim_count, __ATOMIC_SEQ_CST);

      if (!local_state->numa_enabled) {
        int64_t sbatch_check =
            atomic_load_relaxed(&local_state->signed_batch_size);
        if (sbatch_check < 0) {
          uint64_t Ib = atomic_load_relaxed(&local_state->batch_change_idx);
          if (my_read_idx > Ib) {
            int64_t target = -sbatch_check;
            atomic_compare_exchange(&local_state->signed_batch_size,
                                    &sbatch_check, target);
          }
        }
      }
      break;
    }

    // 2. Escrow check SECOND - only reached when ring is apparently empty
    if (fd_escrow_r && fd_escrow_r[my_numa_node] >= 0) {
      struct EscrowPacket ep;
      ssize_t er;
      do { er = read(fd_escrow_r[my_numa_node], &ep, sizeof(ep)); } while (er < 0 && errno == EINTR);
      if (er == sizeof(ep)) {
        my_read_idx = ep.idx;
        claim_count = ep.cnt;
        break;
      }
    }

    // 3. Scanner finished check THIRD
    if (atomic_load_acquire(&local_state->scanner_finished)) {
      if (__atomic_fetch_sub(&local_state->active_workers, 1, __ATOMIC_SEQ_CST) == 1)
        return 2;
      bind_var_or_array(v_target, "0", 0);
      return 1;
    }

    // 4. Spin
    if (spin < 100) {
      cpu_relax();
      spin++;
      continue;
    }

    // 5. Poll
    __atomic_fetch_add(&local_state->active_waiters, 1, __ATOMIC_SEQ_CST);
    is_waiting_on_ring = true;

    // NUMA-isolated EOF standing wave polling
    struct pollfd pfds[2] = {
        {.fd = evfd_data_arr[my_numa_node], .events = POLLIN},
        {.fd = evfd_eof_arr[my_numa_node], .events = POLLIN}};

    while (1) {
      // Pre-check: ring data may have arrived since we last looked
      if (atomic_load_acquire(&local_state->write_idx) >
          atomic_load_relaxed(&local_state->read_idx))
        break;

      poll(pfds, 2, -1);

      bool data_fired = (pfds[0].revents & POLLIN) != 0;
      bool eof_fired  = (pfds[1].revents & POLLIN) != 0;

      if (data_fired) {
        uint64_t v;
        sys_read(evfd_data_arr[my_numa_node], &v, 8); // consume exactly 1 token
      }

      // NEVER read evfd_eof_arr here! Just break and let loop evaluate state.
      if (data_fired || eof_fired) break; // restart_loop handles priority ordering
    }

    cleanup_waiter_state();
    spin = 0;
  }

  uint64_t w_curr = atomic_load_acquire(&local_state->write_idx);
  if (my_read_idx + claim_count > w_curr) {
    if (atomic_load_acquire(&local_state->scanner_finished)) {
      int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
      if (diff < 0)
        diff = 0;
      claim_count = (uint64_t)diff;

      if (local_state->cfg_return_bytes && claim_count > 1) {
          claim_count = 1;
      }

      if (claim_count == 0) {
        spin = 0;
        goto restart_loop;
      }
    } else {
      __atomic_fetch_add(&local_state->active_waiters, 1, __ATOMIC_SEQ_CST);
      is_waiting_on_ring = true;
      while (1) {
        w_curr = atomic_load_acquire(&local_state->write_idx);
        if (w_curr > my_read_idx) {
          uint64_t avail = w_curr - my_read_idx;
          if (avail < claim_count) {
            struct EscrowPacket ep = {.idx = my_read_idx + avail,
                                      .cnt = claim_count - avail};
            ssize_t ew;
            do { ew = write(fd_escrow_w[my_numa_node], &ep, sizeof(ep)); } while (ew < 0 && errno == EINTR);
            if (ew == sizeof(ep)) {
              claim_count = avail;
              uint64_t one = 1;
              sys_write(evfd_data_arr[my_numa_node], &one, 8);
              break;
            }
          } else {
            break;
          }
        }
        if (atomic_load_acquire(&local_state->scanner_finished)) {
          int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
          if (diff < 0)
            diff = 0;
          claim_count = (uint64_t)diff;

          if (local_state->cfg_return_bytes && claim_count > 1) {
              claim_count = 1;
          }

          break;
        }

        // NUMA-isolated EOF standing wave polling
        struct pollfd pfds[2] = {
            {.fd = evfd_data_arr[my_numa_node], .events = POLLIN},
            {.fd = evfd_eof_arr[my_numa_node], .events = POLLIN}};

        poll(pfds, 2, -1);

        bool data_fired = (pfds[0].revents & POLLIN) != 0;
        if (data_fired) {
            uint64_t v;
            sys_read(evfd_data_arr[my_numa_node], &v, 8);
        }
        // NEVER read evfd_eof_arr here! Just loop back to top to re-evaluate w_curr
      }
      cleanup_waiter_state();
      if (claim_count == 0) {
        spin = 0;
        goto restart_loop;
      }
    }
  }

  uint64_t final_val = 0;

  if (local_state->cfg_return_bytes) {
    if (local_state->numa_enabled) {
      uint64_t start = local_state->offset_ring[my_read_idx & RING_MASK] &
                       ~FLAG_PARTIAL_BATCH;
      uint64_t end =
          local_state->end_ring[(my_read_idx + claim_count - 1) & RING_MASK];
      final_val = end - start;
    } else {
      uint64_t start = local_state->offset_ring[my_read_idx & RING_MASK] &
                       ~FLAG_PARTIAL_BATCH;
      uint64_t end =
          local_state->offset_ring[(my_read_idx + claim_count) & RING_MASK] &
          ~FLAG_PARTIAL_BATCH;
      final_val = end - start;
    }
  } else {
    if (claim_count == 1)
      final_val = local_state->stride_ring[my_read_idx & RING_MASK];
    else
      for (uint64_t i = 0; i < claim_count; i++)
        final_val += local_state->stride_ring[(my_read_idx + i) & RING_MASK];
  }

  __atomic_fetch_add(&local_state->total_lines_consumed,
                   (local_state->cfg_return_bytes) ? claim_count : final_val, __ATOMIC_SEQ_CST);

  worker_last_idx = my_read_idx;
  worker_last_cnt = claim_count;

  char buf[64];
  u64toa(final_val, buf);
  bind_var_or_array(v_target, buf, 0);

  u64toa(my_read_idx, buf);
  bind_variable("RING_BATCH_IDX", buf, 0);
  u64toa(claim_count, buf);
  bind_variable("RING_BATCH_SLOTS", buf, 0);

  if (local_state->numa_enabled) {
    worker_last_major = local_state->major_ring[my_read_idx & RING_MASK];
    worker_last_minor =
        local_state->minor_ring[my_read_idx & RING_MASK] & ~FLAG_MAJOR_EOF;

    if (local_state->minor_ring[(my_read_idx + claim_count - 1) & RING_MASK] &
        FLAG_MAJOR_EOF) {
      worker_last_minor |= FLAG_MAJOR_EOF;
    }

    sprintf(buf, "%u", worker_last_major);
    bind_variable("RING_MAJOR", buf, 0);
    sprintf(buf, "%u", worker_last_minor & ~FLAG_MAJOR_EOF);
    bind_variable("RING_MINOR", buf, 0);
  }

  if (fd_read >= 0) {
    uint64_t start_offset =
        local_state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
    if (lseek(fd_read, (off_t)start_offset, SEEK_SET) == (off_t)-1) {
      if (g_debug)
        fprintf(stderr, "forkrun [DEBUG] ring_claim lseek failed: %s\n",
                strerror(errno));
    }
  }
  return 0;
}

static int ring_ack_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  int fd_fallow = atoi(argv[1]);
  int fd_target = (argc >= 3) ? atoi(argv[2]) : -1;

  struct OrderPacket op = {0};

  struct SharedState *local_state =
      (my_numa_node != -1 && my_numa_node < (int)global_num_nodes)
          ? &state[my_numa_node]
          : &state[0];

  uint64_t my_idx;
  if (worker_last_cnt > 0) {
    my_idx = worker_last_idx;
    if (local_state && local_state->numa_enabled) {
      op.major_idx = worker_last_major; op.minor_idx = worker_last_minor; op.cnt = worker_last_cnt;
    } else {
      op.major_idx = (uint32_t)worker_last_idx; op.minor_idx = 0; op.cnt = worker_last_cnt;
    }
  } else {
    op.cnt = (uint32_t)atoi(get_string_value("RING_BATCH_SLOTS"));
    if (local_state && local_state->numa_enabled) {
      op.major_idx = (uint32_t)atoi(get_string_value("RING_MAJOR"));
      op.minor_idx = (uint32_t)atoi(get_string_value("RING_MINOR"));
      my_idx = (uint64_t)atoll(get_string_value("RING_BATCH_IDX"));
    } else {
      op.major_idx = (uint32_t)atoi(get_string_value("RING_BATCH_IDX"));
      op.minor_idx = 0; my_idx = op.major_idx;
    }
  }

  if (fd_fallow > 0) {
    if (local_state && local_state->numa_enabled) {
      uint64_t start = local_state->offset_ring[my_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
      uint64_t end = local_state->end_ring[(my_idx + op.cnt - 1) & RING_MASK];
      struct PhysPacket pp = {.off = start, .len = end - start};
      robust_pipe_write(fd_fallow, &pp, sizeof(pp));
    } else {
      struct IndexPacket ip = {.idx = op.major_idx, .cnt = op.cnt};
      robust_pipe_write(fd_fallow, &ip, sizeof(ip));
    }
  }

  if (fd_target > 0) {
    if (fd_target != ack_cached_target_fd) {
      ack_cached_target_fd = fd_target; struct stat st;
      ack_cached_mode = (fstat(fd_target, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 2;
    }
    if (ack_cached_mode == 1) {
      const char *s_order_pipe = get_string_value("FD_ORDER_PIPE");
      if (s_order_pipe) {
        int fd_pipe = atoi(s_order_pipe);
        off_t curr = lseek(fd_target, 0, SEEK_CUR);
        if (curr == (off_t)-1) return EXECUTION_FAILURE;
        op.fd = fd_target; op.off = (uint64_t)last_ack_offset; op.len = (uint64_t)(curr - last_ack_offset);
        robust_pipe_write(fd_pipe, &op, sizeof(op));
        last_ack_offset = curr;
      }
    } else robust_pipe_write(fd_target, &op, sizeof(op));
  }
  return EXECUTION_SUCCESS;
}

// --- MIN-HEAP ORDERING ---
struct HeapNode {
  uint64_t key;
  struct OrderPacket pkt;
};

static void heap_push(struct HeapNode **heap_ptr, int *sz, int *cap, uint64_t key, struct OrderPacket pkt) {
  if (*sz >= *cap) {
    *cap = (*cap) * 2;
    *heap_ptr = realloc(*heap_ptr, (*cap) * sizeof(struct HeapNode));
  }
  struct HeapNode *heap = *heap_ptr;
  int i = (*sz)++;
  while (i > 0) {
    int p = (i - 1) / 2;
    if (heap[p].key <= key) break;
    heap[i] = heap[p]; i = p;
  }
  heap[i].key = key; heap[i].pkt = pkt;
}

static void heap_pop(struct HeapNode *heap, int *sz, struct HeapNode *out) {
  *out = heap[0]; struct HeapNode tmp = heap[--(*sz)]; int i = 0;
  while (i * 2 + 1 < *sz) {
    int child = i * 2 + 1;
    if (child + 1 < *sz && heap[child + 1].key < heap[child].key) child++;
    if (tmp.key <= heap[child].key) break;
    heap[i] = heap[child]; i = child;
  }
  heap[i] = tmp;
}

static ssize_t robust_sendfile(int out_fd, int in_fd, off_t *offset, size_t count) {
  size_t total = 0; int retries = 0;
  while (total < count) {
    ssize_t s = sendfile(out_fd, in_fd, offset, count - total);
    if (s < 0) { if (errno == EINTR || errno == EAGAIN) { usleep(10); continue; } return total > 0 ? (ssize_t)total : -1; }
    if (s == 0) { if (retries++ < 100) { usleep(10); continue; } break; }
    retries = 0; total += s;
  }
  return (ssize_t)total;
}

static int ring_copy_chunk(int fd_in, int fd_out, off_t off, size_t len) {
  const size_t BUF_SIZE = 65536; char *buf = malloc(BUF_SIZE); size_t total_read = 0; int retries = 0;
  while (total_read < len) {
    size_t to_read = (len - total_read > BUF_SIZE) ? BUF_SIZE : (len - total_read);
    ssize_t r = pread(fd_in, buf, to_read, off + total_read);
    if (r < 0) { if (errno == EINTR || errno == EAGAIN) { usleep(10); continue; } free(buf); return -1; }
    if (r == 0) { if (retries++ < 100) { usleep(10); continue; } break; }
    retries = 0; char *write_ptr = buf; size_t to_write = r;
    while (to_write > 0) {
      ssize_t w = write(fd_out, write_ptr, to_write);
      if (w < 0) { if (errno == EINTR || errno == EAGAIN) { usleep(10); continue; } free(buf); return -1; }
      write_ptr += w; to_write -= w;
    }
    total_read += r;
  }
  free(buf); return (total_read == len) ? 0 : -1;
}

static int ring_order_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]); bool memfd_mode = (strcmp(argv[2], "memfd") == 0); const char *prefix = argv[2];
  bool unordered_mode = false; bool numa_mode = (global_num_nodes > 1);
  for (int i = 3; i < argc; i++) {
    if (strcmp(argv[i], "unordered") == 0) unordered_mode = true;
    if (strcmp(argv[i], "numa") == 0) numa_mode = true;
  }

  bool use_zerocopy = false; struct stat st_out;
  if (fstat(1, &st_out) == 0 && S_ISREG(st_out.st_mode)) use_zerocopy = true;

  int heap_cap = 262144;
  struct HeapNode *heap = malloc(heap_cap * sizeof(struct HeapNode));
  if (!heap) {
      builtin_error("forkrun: malloc failed during ring_order");
      return EXECUTION_FAILURE;
  }
  int heap_sz = 0;

  uint32_t expected_major = 0; uint32_t expected_minor = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct OrderPacket);

  while (1) {
    ssize_t n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break; // EOF or error
    buffered += n_read;

    size_t count = buffered / pkt_sz;
    struct OrderPacket *ops = (struct OrderPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct OrderPacket *op = &ops[i];
      uint32_t actual_minor = op->minor_idx & ~FLAG_MAJOR_EOF;
      uint64_t op_key = numa_mode ? PACK_KEY(op->major_idx, actual_minor) : op->major_idx;

      if (!unordered_mode) heap_push(&heap, &heap_sz, &heap_cap, op_key, *op);
      else {
        if (memfd_mode) {
          off_t offset = (off_t)op->off;
          if (use_zerocopy) robust_sendfile(1, op->fd, &offset, op->len); else ring_copy_chunk(op->fd, 1, offset, op->len);
          off_t aligned_start = (op->off / 4096) * 4096; off_t punch_len = (op->off - aligned_start) + op->len;
          fallocate(op->fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, aligned_start, punch_len);
        } else {
          char path[256];
          if (numa_mode) snprintf(path, sizeof(path), "%s.%u.%u", prefix, op->major_idx, actual_minor);
          else snprintf(path, sizeof(path), "%s.%u", prefix, op->major_idx);
          int fd_file = open(path, O_RDONLY);
          if (fd_file >= 0) {
            off_t offset = 0; struct stat st;
            if (fstat(fd_file, &st) == 0 && st.st_size > 0) robust_sendfile(1, fd_file, &offset, st.st_size);
            close(fd_file); unlink(path);
          }
        }
      }

      if (!unordered_mode) {
        while (heap_sz > 0) {
          uint64_t expected_key = numa_mode ? PACK_KEY(expected_major, expected_minor) : expected_major;
          if (heap[0].key != expected_key) break;
          struct HeapNode top; heap_pop(heap, &heap_sz, &top);
          if (memfd_mode) {
            off_t offset = (off_t)top.pkt.off;
            if (use_zerocopy) robust_sendfile(1, top.pkt.fd, &offset, top.pkt.len); else ring_copy_chunk(top.pkt.fd, 1, offset, top.pkt.len);
            off_t aligned_start = (top.pkt.off / 4096) * 4096; off_t punch_len = (top.pkt.off - aligned_start) + top.pkt.len;
            fallocate(top.pkt.fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, aligned_start, punch_len);
          } else {
            char path[256];
            if (numa_mode) snprintf(path, sizeof(path), "%s.%u.%u", prefix, top.pkt.major_idx, (top.pkt.minor_idx & ~FLAG_MAJOR_EOF));
            else snprintf(path, sizeof(path), "%s.%u", prefix, top.pkt.major_idx);
            int fd_file = open(path, O_RDONLY);
            if (fd_file >= 0) {
              off_t offset = 0; struct stat st;
              if (fstat(fd_file, &st) == 0 && st.st_size > 0) robust_sendfile(1, fd_file, &offset, st.st_size);
              close(fd_file); unlink(path);
            }
          }
          if (numa_mode) {
            expected_minor += top.pkt.cnt;
            if (top.pkt.minor_idx & FLAG_MAJOR_EOF) { expected_major++; expected_minor = 0; }
          } else expected_major += top.pkt.cnt;
        }
      }
    }

    size_t consumed = count * pkt_sz;
    if (consumed < buffered) {
        memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    }
    buffered -= consumed;
  }
  free(heap); return EXECUTION_SUCCESS;
}

// ==============================================================================
// 8. UTILITY LOADABLES
// ==============================================================================

static int ring_worker_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  if (my_numa_node == -1) {
    const char *s_node = get_string_value("RING_NODE_ID");
    if (s_node) my_numa_node = atoi(s_node);
    else {
      int phys = auto_detect_numa_node(); my_numa_node = 0;
      if (g_logical_to_phys_map) {
        for (uint32_t i = 0; i < global_num_nodes; i++) { if (g_logical_to_phys_map[i] == (uint32_t)phys) { my_numa_node = i; break; } }
      }
    }
    if (my_numa_node >= (int)global_num_nodes) my_numa_node = 0;
  }
  int node = my_numa_node;

  if (!strcmp(argv[1], "inc")) {
    if (global_num_nodes > 1 && g_logical_to_phys_map) {
      if (pin_to_numa_node(g_logical_to_phys_map[node]) != 0 && g_debug) {}
    }
    __atomic_fetch_add(&state[node].active_workers, 1, __ATOMIC_SEQ_CST);
    if (argc >= 3 && isdigit(argv[2][0])) worker_cached_fd = atoi(argv[2]);
  } else if (!strcmp(argv[1], "dec")) {
    cleanup_waiter_state();
    __atomic_fetch_sub(&state[node].active_workers, 1, __ATOMIC_SEQ_CST);
    worker_cached_fd = -1;
  }
  return EXECUTION_SUCCESS;
}

static int ring_cleanup_waiter_main(int argc, char **argv) {
  (void)argc; (void)argv; cleanup_waiter_state(); return EXECUTION_SUCCESS;
}
static int ring_ingest_main(int argc, char **argv) {
  (void)argc; (void)argv; if (state) atomic_store_release(&state[0].ingest_complete, 1); return EXECUTION_SUCCESS;
}
static int lseek_main(int argc, char **argv) {
  if (argc < 3 || argc > 5) return EXECUTION_FAILURE;
  int fd = atoi(argv[1]); off_t off = atoll(argv[2]); int whence = SEEK_CUR;
  if (argc > 3) { if (!strcmp(argv[3], "SEEK_SET")) whence = SEEK_SET; else if (!strcmp(argv[3], "SEEK_END")) whence = SEEK_END; }
  off_t no = lseek(fd, off, whence);
  if (no == -1) return EXECUTION_FAILURE;
  if (argc >= 4 && argv[argc - 1][0]) {
    char buf[32]; snprintf(buf, 32, "%lld", (long long)no); bind_var_or_array(argv[argc - 1], buf, 0);
  } else printf("%lld\n", (long long)no);
  return EXECUTION_SUCCESS;
}

static int ring_memfd_create_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  int fd = xcreate_anon_file("forkrun_input");
  if (fd < 0) { builtin_error("memfd_create failed: %s", strerror(errno)); return EXECUTION_FAILURE; }
  char val[32]; snprintf(val, sizeof(val), "%d", fd); bind_var_or_array(argv[1], val, 0);
  return EXECUTION_SUCCESS;
}

static int ring_seal_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  if (fcntl(atoi(argv[1]), F_ADD_SEALS, F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE) == -1) return EXECUTION_FAILURE;
  return EXECUTION_SUCCESS;
}

static int ring_fcntl_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd = atoi(argv[1]); const char *cmd = argv[2];
  if (strcmp(cmd, "shutdown_w") == 0) shutdown(fd, SHUT_WR);
  else if (strcmp(cmd, "shutdown_r") == 0) shutdown(fd, SHUT_RD);
  else if (strcmp(cmd, "shutdown_rw") == 0) shutdown(fd, SHUT_RDWR);
  else if (strcmp(cmd, "close") == 0) close(fd);
  else { builtin_error("unknown command: %s", cmd); return EXECUTION_FAILURE; }
  return EXECUTION_SUCCESS;
}

static int ring_pipe_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  int pfd[2]; if (pipe(pfd) < 0) { builtin_error("pipe failed: %s", strerror(errno)); return EXECUTION_FAILURE; }
  fcntl(pfd[1], F_SETPIPE_SZ, 1048576);

  // PHYSICS FIX: Get the ACTUAL size granted by the kernel and export it dynamically
  int pipe_cap = 65536;
  int ret = fcntl(pfd[1], F_GETPIPE_SZ);
  if (ret > 0) pipe_cap = ret;

  char buf[32];
  snprintf(buf, sizeof(buf), "%d", pipe_cap);
  bind_variable("RING_PIPE_CAPACITY_CUR", buf, 0);

  if (argc == 2) {
    const char *arr_name = argv[1]; SHELL_VAR *v = find_variable(arr_name);
    if (v && !array_p(v)) { unbind_variable(arr_name); v = NULL; }
    if (!v) v = make_new_array_variable(arr_name);
    if (!v) { close(pfd[0]); close(pfd[1]); return EXECUTION_FAILURE; }
    snprintf(buf, sizeof(buf), "%d", pfd[0]); bind_array_element(v, 0, buf, 0);
    snprintf(buf, sizeof(buf), "%d", pfd[1]); bind_array_element(v, 1, buf, 0);
  } else {
    snprintf(buf, sizeof(buf), "%d", pfd[0]); bind_var_or_array(argv[1], buf, 0);
    snprintf(buf, sizeof(buf), "%d", pfd[1]); bind_var_or_array(argv[2], buf, 0);
  }
  return EXECUTION_SUCCESS;
}

static int ring_splice_main(int argc, char **argv) {
  if (argc < 5) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]); int fd_out = atoi(argv[2]); off_t off = 0; off_t *p_off = NULL;
  if (argv[3][0] != '\0') { off_t parsed = (off_t)atoll(argv[3]); if (parsed != -1) { off = parsed; p_off = &off; } }
  size_t len = (size_t)atoll(argv[4]); bool close_out = (argc > 5 && strcmp(argv[5], "close") == 0);
  fcntl(fd_out, F_SETPIPE_SZ, 1048576); size_t written = 0;

  // PHYSICS FIX: Shield the worker process from kernel assassination if the command exits early.
  void (*old_handler)(int) = signal(SIGPIPE, SIG_IGN);

  while (written < len) {
    ssize_t s = splice(fd_in, p_off, fd_out, NULL, len - written, SPLICE_F_MOVE | SPLICE_F_MORE);
    if (s < 0) {
        if (errno == EINTR) continue;
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            struct pollfd pfd = {.fd = fd_out, .events = POLLOUT};
            poll(&pfd, 1, -1);
            continue;
        }
        if (errno == EPIPE) {
            if (close_out) close(fd_out);
            signal(SIGPIPE, old_handler);
            return EXECUTION_SUCCESS;
        }
        if (close_out) close(fd_out);
        builtin_error("splice failed: %s", strerror(errno));
        signal(SIGPIPE, old_handler);
        return EXECUTION_FAILURE;
    }
    if (s == 0) break;
    written += s;
  }
  if (close_out) close(fd_out);
  signal(SIGPIPE, old_handler);
  return EXECUTION_SUCCESS;
}

static int ring_indexer_main(int argc, char **argv) {
  if (argc < 4) return EXECUTION_FAILURE;
  int fd_data = atoi(argv[1]); int fd_pipe = atoi(argv[2]); int fd_sig = atoi(argv[3]);
  size_t chunk_target = get_optimal_chunk_size() * 2; uint64_t current_pos = 0; char tail_buf[65536];
  struct pollfd pfds[1] = {{.fd = fd_sig, .events = POLLIN}};
  while (1) {
    struct stat st; if (fstat(fd_data, &st) < 0) break;
    uint64_t available = (uint64_t)st.st_size;
    while (available >= current_pos + chunk_target) {
      uint64_t scan_end = current_pos + chunk_target;
      size_t scan_sz = (sizeof(tail_buf) < chunk_target) ? sizeof(tail_buf) : chunk_target;
      ssize_t n = pread(fd_data, tail_buf, scan_sz, scan_end - scan_sz);
      if (n > 0) {
        char *nl = memrchr(tail_buf, '\n', n);
        if (nl) {
          uint64_t actual_end = (scan_end - scan_sz) + (nl - tail_buf) + 1;
          struct PhysPacket pp = {.off = current_pos, .len = actual_end - current_pos};
          if (robust_pipe_write(fd_pipe, &pp, sizeof(pp)) < 0) return EXECUTION_FAILURE;
          current_pos = actual_end; continue;
        }
      }
      struct PhysPacket pp = {.off = current_pos, .len = chunk_target};
      if (robust_pipe_write(fd_pipe, &pp, sizeof(pp)) < 0) return EXECUTION_FAILURE;
      current_pos += chunk_target;
    }
    if (poll(pfds, 1, 100) > 0) { uint64_t v; if (sys_read(fd_sig, &v, 8) > 0) break; }
  }
  return EXECUTION_SUCCESS;
}

static int ring_fetcher_main(int argc, char **argv) {
  if (argc < 6) return EXECUTION_FAILURE;
  int fd_pipe = atoi(argv[1]); int fd_global = atoi(argv[2]); int fd_local = atoi(argv[3]);
  int fd_local_sig = atoi(argv[4]); int fd_global_ack = atoi(argv[5]); int fd_token_in = (argc > 6) ? atoi(argv[6]) : -1;
  struct PhysPacket pp;
  while (1) {
    if (fd_token_in >= 0) { char t; if (sys_read(fd_token_in, &t, 1) <= 0) break; }
    if (robust_pipe_read(fd_pipe, &pp, sizeof(pp), true) <= 0) break;
    loff_t off_in = (loff_t)pp.off; loff_t off_out = lseek(fd_local, 0, SEEK_END);
    ssize_t ret = copy_file_range(fd_global, &off_in, fd_local, &off_out, pp.len, 0);
    if (ret < 0) {
      char *buf = malloc(65536); uint64_t copied = 0; lseek(fd_global, pp.off, SEEK_SET); lseek(fd_local, 0, SEEK_END);
      while (copied < pp.len) {
        size_t to_read = (pp.len - copied > 65536) ? 65536 : (pp.len - copied);
        ssize_t r = sys_read(fd_global, buf, to_read);
        if (r <= 0) { break; }
        char *wptr = buf; ssize_t wleft = r;
        while (wleft > 0) {
          ssize_t w = sys_write(fd_local, wptr, wleft);
          if (w <= 0) { break; }
          wptr += w; wleft -= w;
        }
        copied += r;
      }
      free(buf);
    }
    uint64_t one = 1; sys_write(fd_local_sig, &one, 8); robust_pipe_write(fd_global_ack, &pp, sizeof(pp));
  }
  return EXECUTION_SUCCESS;
}

static int ring_fallow_phys_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]); int fd_file = atoi(argv[2]);
  struct Interval *head = NULL; uint64_t limit = 0;
  off_t last_punched = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct PhysPacket);

  while (1) {
    ssize_t n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break;
    buffered += n_read;

    size_t count = buffered / pkt_sz;
    struct PhysPacket *ops = (struct PhysPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct PhysPacket *pp = &ops[i];
      if (pp->off == limit) {
        limit += pp->len;
        while (head && head->s == limit) { struct Interval *tmp = head; limit = tmp->e; head = tmp->next; free(tmp); }
        off_t aligned = (off_t)((limit / 4096) * 4096);
        if (aligned > last_punched) {
            fallocate(fd_file, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, last_punched, aligned - last_punched);
            last_punched = aligned;
        }
      } else if (pp->off > limit) {
        struct Interval *n = malloc(sizeof(struct Interval)); n->s = pp->off; n->e = pp->off + pp->len;
        struct Interval **curr = &head; while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
        n->next = *curr; *curr = n;
      }
    }

    size_t consumed = count * pkt_sz;
    if (consumed < buffered) {
        memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    }
    buffered -= consumed;
  }
  while (head) { struct Interval *tmp = head; head = head->next; free(tmp); }
  return EXECUTION_SUCCESS;
}

static int ring_copy_main(int argc, char **argv) {
  if (argc < 2) return EXECUTION_FAILURE;
  int outfd = atoi(argv[1]); int infd = (argc == 3) ? atoi(argv[2]) : 0;
  size_t chunk = get_optimal_chunk_size(); struct stat st; uint64_t oom_threshold = 134217728;
  long threshold_div = 128; const char *s_div = get_string_value("RING_INGEST_DIVISOR");
  if (s_div) { long v = atol(s_div); if (v > 0) threshold_div = v; }
  struct sysinfo si_init;
  if (sysinfo(&si_init) == 0) {
    uint64_t mu = (uint64_t)si_init.mem_unit ? si_init.mem_unit : 1;
    oom_threshold = ((uint64_t)si_init.totalram * mu) / (uint64_t)threshold_div;
  }
  uint64_t total_moved = 0; uint64_t next_check = 16 * 1024 * 1024;
  off_t off = 0;
  bool use_bounce = true;

  if (fstat(infd, &st) == 0 && S_ISREG(st.st_mode)) {
    if (st.st_size == 0) {
        // Let it fall through to read/write. Some special files (like /proc)
        // report size 0 but have streaming content.
    } else {
        while (off < st.st_size) {
          check_memory_pressure(&total_moved, &next_check, oom_threshold);
          loff_t current_off = off; size_t to_copy = (size_t)(st.st_size - off); if (to_copy > chunk) to_copy = chunk;
          size_t copied_in_chunk = 0;
          while (copied_in_chunk < to_copy) {
            ssize_t n = copy_file_range(infd, &current_off, outfd, NULL, to_copy - copied_in_chunk, 0);
            if (n < 0) { if (errno == EINTR) continue; if (errno == EXDEV || errno == EINVAL || errno == ENOSYS || errno == EOPNOTSUPP) break; goto err_out; }
            if (n == 0) break;
            copied_in_chunk += n;
          }
          if (copied_in_chunk == 0 && (st.st_size - off > 0)) break;
          off += copied_in_chunk;
          if (evfd_ingest_data >= 0) { uint64_t v = 1; sys_write(evfd_ingest_data, &v, 8); }
          total_moved += copied_in_chunk;
        }
        while (off < st.st_size) {
          check_memory_pressure(&total_moved, &next_check, oom_threshold);
          ssize_t n = sendfile(outfd, infd, &off, chunk);
          if (n < 0) { if (errno == EINTR) continue; break; }
          if (n == 0) break;
          if (evfd_ingest_data >= 0) { uint64_t v = 1; sys_write(evfd_ingest_data, &v, 8); }
          total_moved += n;
        }
        if (off >= st.st_size) use_bounce = false;
    }
  }

  if (use_bounce) {
    char *bounce_buf = mmap(NULL, chunk, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    if (bounce_buf == MAP_FAILED) goto err_out;

    while (1) {
      ssize_t r = read(infd, bounce_buf, chunk);
      if (r < 0) {
          if (errno == EINTR) continue;
          if (errno == EAGAIN) {
              struct pollfd pfd = {.fd = infd, .events = POLLIN};
              poll(&pfd, 1, -1);
              continue;
          }
          break;
      }
      if (r == 0) break;

      size_t written = 0;
      while (written < (size_t)r) {
          ssize_t w = write(outfd, bounce_buf + written, r - written);
          if (w <= 0) {
              if (w < 0 && (errno == EINTR || errno == EAGAIN)) {
                  if (errno == EAGAIN) {
                      struct pollfd pfd = {.fd = outfd, .events = POLLOUT};
                      poll(&pfd, 1, -1);
                  } else usleep(10);
                  continue;
              }
              break;
          }
          written += w;
      }
      if (written < (size_t)r) break;

      if (evfd_ingest_data >= 0) { uint64_t v = 1; sys_write(evfd_ingest_data, &v, 8); }
      total_moved += written; check_memory_pressure(&total_moved, &next_check, oom_threshold);
    }
    munmap(bounce_buf, chunk);
  }

  if (evfd_ingest_eof >= 0) { uint64_t val = 999999; sys_write(evfd_ingest_eof, &val, 8); }
  return EXECUTION_SUCCESS;

err_out:
  if (evfd_ingest_eof >= 0) { uint64_t val = 999999; sys_write(evfd_ingest_eof, &val, 8); }
  return EXECUTION_FAILURE;
}

static int ring_signal_main(int argc, char **argv) {
  int fd = evfd_ingest_eof; if (argc >= 2) fd = atoi(argv[1]);
  uint64_t val = 1; SYS_CHK(write(fd, &val, 8)); return EXECUTION_SUCCESS;
}

static int ring_fallow_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]); int fd_file = atoi(argv[2]); bool dry_run = (argc > 3 && strcmp(argv[3], "dry") == 0);
  if (state) atomic_store_release(&state[0].fallow_active, 1);
  struct Interval *head = NULL; uint64_t next_idx = 0;
  off_t last_punched = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct IndexPacket);

  while (1) {
    ssize_t n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break;
    buffered += n_read;

    size_t count = buffered / pkt_sz;
    struct IndexPacket *ops = (struct IndexPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct IndexPacket *ip = &ops[i];
      if (ip->idx == next_idx) {
        next_idx += ip->cnt;
        while (head && head->s == next_idx) { struct Interval *tmp = head; next_idx = tmp->e; head = tmp->next; free(tmp); }
        if (state) atomic_store_release(&state[0].min_idx, next_idx);
        if (!dry_run) {
          uint64_t byte_limit = state[0].offset_ring[next_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
          off_t aligned = (off_t)((byte_limit / 4096) * 4096);
          if (aligned > last_punched) {
            fallocate(fd_file, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, last_punched, aligned - last_punched);
            last_punched = aligned;
          }
        }
      } else if (ip->idx > next_idx) {
        struct Interval *n = malloc(sizeof(struct Interval)); n->s = ip->idx; n->e = ip->idx + ip->cnt;
        struct Interval **curr = &head; while (*curr && (*curr)->s < n->s) curr = &((*curr)->next);
        n->next = *curr; *curr = n;
      }
    }

    size_t consumed = count * pkt_sz;
    if (consumed < buffered) {
        memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    }
    buffered -= consumed;
  }
  while (head) { struct Interval *tmp = head; head = head->next; free(tmp); }
  return EXECUTION_SUCCESS;
}

static int ring_version_main(int argc, char **argv) {
  bool show_all = false;
  if (argc == 1) { printf("%s\n", FORKRUN_RING_VERSION); return EXECUTION_SUCCESS; }
  for (int i = 1; i < argc; i++) {
    const char *arg = argv[i];
    if (strcmp(arg, "-a") == 0 || strcmp(arg, "--all") == 0) { show_all = true; break; }
    if (strcmp(arg, "-t") == 0) printf("%s %s\n", __DATE__, __TIME__);
    else if (strcmp(arg, "-o") == 0) printf("%s\n", BUILD_OS);
    else if (strcmp(arg, "-m") == 0) printf("%s\n", BUILD_ARCH);
    else if (strcmp(arg, "-g") == 0) printf("%s\n", __VERSION__);
    else if (strcmp(arg, "-f") == 0) printf("%s\n", COMPILER_FLAGS);
    else if (strcmp(arg, "-h") == 0) printf("%s\n", GIT_HASH);
  }
  if (show_all) {
    printf("Version:  %s\n", FORKRUN_RING_VERSION); printf("Built:    %s %s\n", __DATE__, __TIME__);
    printf("OS:       %s\n", BUILD_OS); printf("Arch:     %s\n", BUILD_ARCH);
    printf("Compiler: %s\n", __VERSION__); printf("Flags:    %s\n", COMPILER_FLAGS);
    printf("Git Hash: %s\n", GIT_HASH);
  }
  return EXECUTION_SUCCESS;
}

// --- NEW FUNCTION: NUMA TELEMETRY ---
static int ring_numa_stats_main(int argc, char **argv) {
  (void)argc; (void)argv;
  if (!g_state || !state) return EXECUTION_FAILURE;

  uint64_t total_assigned = 0;
  uint64_t total_stolen = 0;
  uint64_t total_local = 0;

  fprintf(stderr, "\n=========================================\n");
  fprintf(stderr, "NUMA TELEMETRY (CHUNKS)\n");
  fprintf(stderr, "=========================================\n");
  for (uint32_t n = 0; n < global_num_nodes; n++) {
      uint64_t assigned = atomic_load_relaxed(&state[n].stats_chunks_assigned);
      uint64_t local = atomic_load_relaxed(&state[n].stats_chunks_local);
      uint64_t stolen = atomic_load_relaxed(&state[n].stats_chunks_stolen);
      uint32_t phys = g_logical_to_phys_map ? g_logical_to_phys_map[n] : 0;

      total_assigned += assigned;
      total_local += local;
      total_stolen += stolen;

      fprintf(stderr, "Node %u (Phys %u): %lu assigned | %lu processed local | %lu stolen\n",
              n, phys, assigned, local, stolen);
  }
  fprintf(stderr, "-----------------------------------------\n");
  uint64_t total_processed = total_local + total_stolen;
  double stolen_pct = total_processed > 0 ? (100.0 * (double)total_stolen / (double)total_processed) : 0.0;
  fprintf(stderr, "Total Cross-Socket Traffic: %lu chunks (%.1f%%)\n", total_stolen, stolen_pct);
  fprintf(stderr, "=========================================\n\n");

  return EXECUTION_SUCCESS;
}

#define DEFINE_DISPATCHER_X(name, func, usage, doc)                            \
  static int dispatch_##name(WORD_LIST *list) {                                \
    int argc; char **argv = make_builtin_argv(list, &argc); int ret = EXECUTION_FAILURE; \
    if (argv[0]) ret = func(argc, argv);                                       \
    xfree(argv); return ret;                                                   \
  }
FORKRUN_LOADABLES(DEFINE_DISPATCHER_X)
#undef DEFINE_DISPATCHER_X

#define DEFINE_STRUCT_X(name, func, usage, doc)                                \
  static char *name##_doc[] = {doc, usage, NULL};                              \
  struct builtin name##_struct = { #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0 };
FORKRUN_LOADABLES(DEFINE_STRUCT_X)
#undef DEFINE_STRUCT_X

static int ring_list_main(int argc, char **argv) {
  if (argc >= 2) {
    const char *var_name = argv[1]; SHELL_VAR *v = find_variable(var_name);
    if (v && !array_p(v)) { unbind_variable(var_name); v = NULL; }
    if (!v) v = make_new_array_variable(var_name);
    if (!v) return EXECUTION_FAILURE;
    int i = 0;
#define ADD_TO_ARR(name, ...) if (strcmp(#name, "ring_list") != 0) bind_array_element(v, i++, #name, 0);
    FORKRUN_LOADABLES(ADD_TO_ARR)
#undef ADD_TO_ARR
  } else {
#define PRINT_NAME(name, ...) if (strcmp(#name, "ring_list") != 0) printf("%s\n", #name);
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
