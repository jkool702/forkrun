// forkrun_ring.c v3.3.0
// ======================================================================================
// ARCHITECTURE OVERVIEW:
//
// 1. Zero-Copy Ingest: Data moved from stdin to memfd via
// splice/copy_file_range.
// 2. Lock-Free Meta Ring: Ingest publishes chunk coordinates to GlobalState.
// 3. Per-Node Indexers: Find physical boundaries instantly in local memory.
// 4. Unified Scanners: A single core hot-loop handles both UMA and NUMA
// execution.
// 5. Min-Heap Orderer: Resolves extreme skew with O(log N) sorting.
// ======================================================================================

// PHYSICS PARADIGM OVERVIEW:
//
// forkrun operates as a frictionless, one-way, born-local river of data:
// 1. Ingest (Born-local): Data pages are physically pinned to specific NUMA
// sockets at birth
//    via `set_mempolicy(MPOL_BIND)` driven by backpressure from indexers. This
//    minimizes cross-socket migration and enforces conservation of locality.
// 2. Single-Slot Claiming (Workers): Workers are water wheels that claim exactly 1
//    slot (1 batch) at a time via lock-free `atomic_fetch_add`. The scanner
//    pre-calculates optimal sizes. If a worker process fails mid-execution, its
//    active transaction is rolled back and re-deposited into an escrow pipe
//    for other workers to claim.
// 3. Fallow (Entropy Export): As the workflow unspools, a background fallow
// thread
//    punches holes in the backing memfd via `fallocate(PUNCH_HOLE)` to prevent
//    OOM without breaking the absolute integer offsets.
//
// CRITICAL INVARIANT: The fast path has no locks and no CAS retry loops.


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
#include <dlfcn.h>      // dlopen/dlsym for -C plugin loading
#include <spawn.h>
#include <sys/wait.h>

// ==============================================================================
// AVX2 FAST DELIMITER SCANNER
// ==============================================================================

#if defined(__x86_64__) || defined(__i386__)
#pragma GCC push_options
#pragma GCC target("avx2,popcnt,bmi")
#include <immintrin.h>

// High-throughput AVX2 SIMD scanner. Scans 32 bytes at a time for delimiters.
// Uses `_mm256_movemask_epi8` and `__builtin_popcount` on the bitmask of
// matches to instantly skip ahead by multiple records rather than branching per
// character. If the batch 'target' constraint is met inside the 32-byte vector,
// `__builtin_ctz` finds the exact boundary.
__attribute__((target("avx2,popcnt,bmi"))) static inline char *
scan_batch_avx2(char *p, char *end, uint64_t target, char delim) {
  uint64_t remaining = target;
  const __m256i d_vec = _mm256_set1_epi8(delim);

  while (p + 32 <= end) {
    __m256i v = _mm256_loadu_si256((const __m256i *)p);
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

        /*
        // note: add bmi2 to target
        // We crossed the target in this vector — find exact position
        // O(1) Branchless finding of the N-th set bit
        uint32_t isolated_bit = _pdep_u32(1U << (remaining - 1), mask);
        int exact_idx = __builtin_ctz(isolated_bit);
        */

        // O(N) Fallback for older AMD CPUs without fast PDEP
        uint32_t to_drop = (uint32_t)(remaining - 1);
        for (uint32_t i = 0; i < to_drop; i++) {
            mask &= mask - 1; // BLSR
        }
        int exact_idx = __builtin_ctz(mask); // TZCNT
    return p + exact_idx + 1;
  }

  while (p < end) {
    if (*p == delim) {
      remaining--;
      if (remaining == 0)
        return p + 1;
    }
    p++;
  }

  return NULL;
}

// Pure popcount over a buffer — no position extraction needed.
// Used by the pre-flight scan to count total delimiters at AVX2 speed.
__attribute__((target("avx2,popcnt"))) static inline uint64_t
fast_count_delim_avx2(const char *p, const char *end, char delim) {
  uint64_t count = 0;
  const __m256i d_vec = _mm256_set1_epi8(delim);
  while (p + 32 <= end) {
    __m256i v   = _mm256_loadu_si256((const __m256i *)p);
    __m256i cmp = _mm256_cmpeq_epi8(v, d_vec);
    count += (uint64_t)__builtin_popcount((uint32_t)_mm256_movemask_epi8(cmp));
    p += 32;
  }
  while (p < end) {
    if (*p == delim) count++;
    p++;
  }
  return count;
}
#pragma GCC pop_options
#endif

#if defined(__aarch64__)
#include <arm_neon.h>

// ARM NEON equivalent of the AVX2 scanner. Scans 16 bytes at a time.
static inline char *scan_batch_neon(char *p, char *end, uint64_t target,
                                    char delim) {
  uint64_t remaining = target;
  uint8x16_t d_vec = vdupq_n_u8(delim);

  while (p + 16 <= end) {
    uint8x16_t v = vld1q_u8((const uint8_t *)p);
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
      if (remaining == 0)
        return p + 1;
    }
    p++;
  }

  return NULL;
}

// Pure popcount over a buffer using NEON — no position extraction needed.
static inline uint64_t
fast_count_delim_neon(const char *p, const char *end, char delim) {
  uint64_t count = 0;
  uint8x16_t d_vec = vdupq_n_u8((uint8_t)delim);
  while (p + 16 <= end) {
    uint8x16_t v   = vld1q_u8((const uint8_t *)p);
    uint8x16_t cmp = vceqq_u8(v, d_vec);
    uint64_t lo = vgetq_lane_u64(vreinterpretq_u64_u8(cmp), 0);
    uint64_t hi = vgetq_lane_u64(vreinterpretq_u64_u8(cmp), 1);
    count += (uint64_t)(__builtin_popcountll(lo) / 8);
    count += (uint64_t)(__builtin_popcountll(hi) / 8);
    p += 16;
  }
  while (p < end) {
    if (*p == delim) count++;
    p++;
  }
  return count;
}
#endif

static inline char *try_simd_scan(char *p, char *safe_end, uint64_t target,
                                  char delim) {
  if (target == 0 || p >= safe_end)
    return NULL;

#if defined(__x86_64__) || defined(__i386__)
  static __thread int avx2_supported = -1;
  if (__builtin_expect(avx2_supported == -1, 0)) {
    __builtin_cpu_init();
    avx2_supported =
        __builtin_cpu_supports("avx2") && __builtin_cpu_supports("popcnt");
  }

  if (avx2_supported) {
    return scan_batch_avx2(p, safe_end, target, delim);
  }
#elif defined(__aarch64__)
  return scan_batch_neon(p, safe_end, target, delim);
#endif

  return NULL;
}

// Architecture-dispatched delimiter popcount. O(N) over the buffer, no
// per-delimiter position extraction. Used exclusively by the pre-flight scan.
static inline uint64_t
fast_count_delim(const char *p, const char *end, char delim) {
#if defined(__x86_64__) || defined(__i386__)
  static __thread int avx2_supported = -1;
  if (__builtin_expect(avx2_supported == -1, 0)) {
    __builtin_cpu_init();
    avx2_supported = __builtin_cpu_supports("avx2") &&
                     __builtin_cpu_supports("popcnt");
  }
  if (avx2_supported)
    return fast_count_delim_avx2(p, end, delim);
#elif defined(__aarch64__)
  return fast_count_delim_neon(p, end, delim);
#endif
  uint64_t count = 0;
  while (p < end) {
    if (*p == delim) count++;
    p++;
  }
  return count;
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
#define __NR_set_mempolicy -1
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
#ifndef MFD_HUGETLB
#define MFD_HUGETLB 0x0004U
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

#define MAX_BATCH_LINES  281474976710656ULL
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
#define FORKRUN_RING_VERSION "v3.3.0"
#endif

#define atomic_load_acquire(ptr) __atomic_load_n(ptr, __ATOMIC_ACQUIRE)
#define atomic_load_relaxed(ptr) __atomic_load_n(ptr, __ATOMIC_RELAXED)
#define atomic_store_release(ptr, val)                                         \
  __atomic_store_n(ptr, val, __ATOMIC_RELEASE)
#define atomic_store_relaxed(ptr, val)                                         \
  __atomic_store_n(ptr, val, __ATOMIC_RELAXED)
#define atomic_fetch_add(ptr, val)                                             \
  __atomic_fetch_add(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_fetch_sub(ptr, val)                                             \
  __atomic_fetch_sub(ptr, val, __ATOMIC_ACQ_REL)
#define atomic_compare_exchange(ptr, exp, des)                                 \
  __atomic_compare_exchange_n(ptr, exp, des, 0, __ATOMIC_ACQ_REL,              \
                              __ATOMIC_RELAXED)

// v3.3: Pre-flight popcount optimally skips the geometric ramp-up in the
// common case. The scanner does a pure delimiter count at AVX2 speed before
// committing any ring slots, computes the optimal L = total_lines / W, and
// enters PID steady-state directly. Workers always claim exactly 1 slot.

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
        fprintf(stderr, "forkrun[DEBUG] %s:%d: %s failed: %s\n", __FILE__,     \
                __LINE__, #x, strerror(errno));                                \
    }                                                                          \
  } while (0)

// ==============================================================================
// PHYSICS FIX: ROBUST IPC IO WRAPPERS
// ==============================================================================

// For IPC Pipes (Order/Fallow/Escrow). Uses poll() to wait for EAGAIN without
// burning CPU.
static inline ssize_t robust_pipe_read(int fd, void *buf, size_t count,
                                       bool exact) {
  char *p = (char *)buf;
  size_t left = count;
  while (left > 0) {
    ssize_t r = read(fd, p, left);
    if (r < 0) {
      if (errno == EINTR)
        continue;
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        poll(&pfd, 1, -1);
        continue;
      }
      return (count - left) > 0 ? (ssize_t)(count - left) : -1;
    }
    if (r == 0)
      return count - left; // EOF
    p += r;
    left -= r;

    // CRITICAL FIX: If exact is false, return immediately after ANY successful
    // read to prevent Fallow/Order threads from deadlocking on partial queues.
    if (!exact)
      return count - left;
  }
  return count;
}

static inline ssize_t robust_pipe_write(int fd, const void *buf, size_t count) {
  const char *p = (const char *)buf;
  size_t left = count;
  while (left > 0) {
    ssize_t w = write(fd, p, left);
    if (w < 0) {
      if (errno == EINTR)
        continue;
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

// For EventFDs. Strictly returns -1 EAGAIN if empty so lock-free loops can
// proceed.
static inline ssize_t sys_read(int fd, void *buf, size_t count) {
  ssize_t r;
  do {
    r = read(fd, buf, count);
  } while (r < 0 && errno == EINTR);
  return r;
}

static inline ssize_t sys_write(int fd, const void *buf, size_t count) {
  ssize_t w;
  do {
    w = write(fd, buf, count);
  } while (w < 0 && errno == EINTR);
  return w;
}

static __thread off_t tls_batch_offset = 0;

extern char **environ; // Required for posix_spawnp

// Thread-local arrays to eliminate malloc/free overhead on the hot path
static __thread char *tls_map_buf = NULL;
static __thread size_t tls_map_buf_cap = 0;
static __thread char **tls_argv = NULL;
static __thread size_t tls_argv_cap = 0;

// Shared tokenizer core.
// If `arr` is non-NULL, it populates the Bash array.
// If `arr` is NULL, it populates `tls_argv` starting at `fixed_argc`.
static int do_tokenize(int fd, size_t length, off_t offset, char delim, SHELL_VAR *arr, int fixed_argc, size_t *out_batch_argc) {
    if (length == 0) {
        if (out_batch_argc) *out_batch_argc = 0;
        return EXECUTION_SUCCESS;
    }

    // Shield against integer overflow and POSIX pread limits
    if (length > SSIZE_MAX - 65536) return 254;

    if (length + 1 > tls_map_buf_cap) {
        size_t new_cap = length + 65536; // Add padding to avoid constant reallocs
        char *new_buf = realloc(tls_map_buf, new_cap);
        if (!new_buf) return 254;
        tls_map_buf = new_buf;
        tls_map_buf_cap = new_cap;
    }

    size_t total_read = 0;
    while (total_read < length) {
        ssize_t n = pread(fd, tls_map_buf + total_read, length - total_read, offset + total_read);
        if (n < 0) {
            if (errno == EINTR) continue;
            return 254;
        }
        if (n == 0) break; // EOF reached before expected length
        total_read += n;
    }

    // If we couldn't fulfill the exact claimed length, the batch is broken.
    if (total_read < length) return 254;

    tls_map_buf[total_read] = '\0'; // Safety terminator

    char *ptr = tls_map_buf;
    char *end = tls_map_buf + total_read;
    size_t idx = 0;

    while (ptr < end) {
        // Dynamic capacity doubling for argv mode (prevents segfaults on tiny records)
        if (!arr) {
            if ((size_t)fixed_argc + idx + 2 > tls_argv_cap) {
                tls_argv_cap = tls_argv_cap ? tls_argv_cap * 2 : 1024;
                char **new_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
                if (!new_argv) return 254;
                tls_argv = new_argv;
            }
        }

        char *next = memchr(ptr, delim, end - ptr);
        if (next) {
            *next = '\0'; // Swap delimiter for null terminator
            if (arr) {
                if (!bind_array_element(arr, (arrayind_t)idx, ptr, 0))
                    return 254;
            } else {
                tls_argv[fixed_argc + idx] = ptr;
            }
            idx++;
            ptr = next + 1;
        } else {
            // Trailing data without a delimiter
            if (ptr < end && *ptr != '\0') {
                if (arr) {
                    if (!bind_array_element(arr, (arrayind_t)idx, ptr, 0))
                        return 254;
                } else {
                    tls_argv[fixed_argc + idx] = ptr;
                }
                idx++;
            }
            break;
        }
    }

    if (out_batch_argc) *out_batch_argc = idx;
    return EXECUTION_SUCCESS;
}

// ---------------------------------------------------------
// ring_map: For Bash functions, Builtins, and -U/-i/-I modes
// ---------------------------------------------------------
static int ring_map_main(int argc, char **argv) {
    if (argc < 4) return EXECUTION_FAILURE;

    int fd = atoi(argv[1]);
    size_t length = (size_t)atoll(argv[2]);
    const char *arr_name = argv[3];
    char delim = (argc >= 5) ? argv[4][0] : '\n';

    // Clear the target array safely
    if (find_variable(arr_name)) {
        unbind_variable(arr_name);
    }

    SHELL_VAR *v = make_new_array_variable(arr_name);
    if (!v) return EXECUTION_FAILURE;

    int ret = do_tokenize(fd, length, tls_batch_offset, delim, v, 0, NULL);
    if (ret != EXECUTION_SUCCESS) return 254;
    return EXECUTION_SUCCESS;
}

// Returns 0 (true) if safe to execute directly via posix_spawnp (Binary or Shebang)
// Returns 1 (false) if it is a text script without a shebang (needs Bash AST parsing)
static int ring_is_spawnable_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;

    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) return EXECUTION_FAILURE; // File not found/unreadable -> Let Bash handle it

    unsigned char buf[1024];
    ssize_t n = read(fd, buf, sizeof(buf));
    close(fd);

    if (n <= 0) return EXECUTION_FAILURE;

    // 1. Shebang: The kernel handles this perfectly via binfmt_script
    if (n >= 2 && buf[0] == '#' && buf[1] == '!') return EXECUTION_SUCCESS;

    // 2. Binary Heuristic: Any file containing a NULL byte in the first 1KB is a compiled binary.
    // Text scripts cannot contain NULL bytes. This catches ELF, Mach-O, WASM, etc., instantly.
    for (ssize_t i = 0; i < n; i++) {
        if (buf[i] == '\0') return EXECUTION_SUCCESS;
    }

    // 3. Pure text without a shebang.
    // posix_spawnp might choke or pass it to /bin/sh (breaking Bashisms).
    // Return failure to enforce ring_map fallback!
    return EXECUTION_FAILURE;
}

// ---------------------------------------------------------
// ring_exec: Ultra-fast path for external binaries
// ---------------------------------------------------------
static int ring_exec_main(int argc, char **argv) {
    // Usage: ring_exec <fd> <length> <delim> <cmd> [fixed_args...]
    if (argc < 5) return EXECUTION_FAILURE;

    int fd = atoi(argv[1]);
    size_t length = (size_t)atoll(argv[2]);
    char delim = argv[3][0];

    int fixed_argc = argc - 4;

    // 1. Ensure baseline capacity for fixed arguments
    if (tls_argv_cap < (size_t)(fixed_argc + 1024)) {
        tls_argv_cap = fixed_argc + 1024;
        char **new_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
        if (!new_argv) return EXECUTION_FAILURE;
        tls_argv = new_argv;
    }

    // 2. Load fixed command and args directly from Bash's parsed argv
    for (int i = 0; i < fixed_argc; i++) {
        tls_argv[i] = argv[4 + i];
    }

    // 3. Tokenize batch directly into tls_argv
    size_t batch_argc = 0;
    int ret = do_tokenize(fd, length, tls_batch_offset, delim, NULL, fixed_argc, &batch_argc);
    if (ret != EXECUTION_SUCCESS) return ret;

    // 4. Terminate argv array for execve
    tls_argv[fixed_argc + batch_argc] = NULL;

    // 5. SHIELD AGAINST BASH'S JOB CONTROL (Block SIGCHLD)
    sigset_t set, oset;
    sigemptyset(&set);
    sigaddset(&set, SIGCHLD);
    sigprocmask(SIG_BLOCK, &set, &oset);

    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    if (fd > 2) posix_spawn_file_actions_addclose(&actions, fd);

    // 6. Spawn the child (inherits FDs natively)
    pid_t pid;
    ret = posix_spawnp(&pid, tls_argv[0], &actions, NULL, tls_argv, environ);

    // 7. Wait for the child synchronously
    int status = 0;
    if (ret == 0) {
        while (waitpid(pid, &status, 0) == -1) {
            if (errno != EINTR) {
                ret = -1; // Mark the execution as failed!
                break;
            }
        }
    }

    posix_spawn_file_actions_destroy(&actions);
    // 8. Restore signal mask
    sigprocmask(SIG_SETMASK, &oset, NULL);

    if (ret != 0) return 254; // posix_spawnp failed (EAGAIN/ENOMEM) — Internal Framework Error

    // Return exact status correctness (crucial for -E auto-retry)
    if (WIFEXITED(status)) {
        return (WEXITSTATUS(status) == 0) ? EXECUTION_SUCCESS : WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status); // Standard shell convention for fatal signals
    }
    return EXECUTION_FAILURE;
}

// ---------------------------------------------------------
// ring_exec_splice: Spawn binary and splice data to its stdin
// ---------------------------------------------------------
static int ring_exec_splice_main(int argc, char **argv) {
    // Usage: ring_exec_splice <fd> <length> <cmd> [args...]
    if (argc < 4) return EXECUTION_FAILURE;

    int fd = atoi(argv[1]);
    size_t length = (size_t)atoll(argv[2]);
    int fixed_argc = argc - 3;

    // 1. Load command and args into tls_argv
    if (tls_argv_cap < (size_t)(fixed_argc + 1)) {
        tls_argv_cap = fixed_argc + 1;
        char **new_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
        if (!new_argv) return 254;
        tls_argv = new_argv;
    }
    for (int i = 0; i < fixed_argc; i++) {
        tls_argv[i] = argv[3 + i];
    }
    tls_argv[fixed_argc] = NULL;

    // 2. Create the pipe
    int pfd[2];
    if (pipe(pfd) != 0) return EXECUTION_FAILURE;

    // Optional: Maximize pipe buffer size for throughput
    fcntl(pfd[1], F_SETPIPE_SZ, 1048576);

    // 3. Map pfd[0] to the child's STDIN
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, pfd[0], STDIN_FILENO);
    posix_spawn_file_actions_addclose(&actions, pfd[1]); // Child doesn't need write end
    if (fd > 2) posix_spawn_file_actions_addclose(&actions, fd); // Shield memfd

    // 4. Block SIGCHLD
    sigset_t set, oset;
    sigemptyset(&set);
    sigaddset(&set, SIGCHLD);
    sigprocmask(SIG_BLOCK, &set, &oset);

    // 5. Spawn the child!
    pid_t pid;
    int ret = posix_spawnp(&pid, tls_argv[0], &actions, NULL, tls_argv, environ);

    // 6. Close the read end in the parent (child owns it now)
    close(pfd[0]);
    posix_spawn_file_actions_destroy(&actions);

    // 7. Feed the child concurrently via splice
    if (ret == 0) {
        // IGNORE SIGPIPE so 'head -n' doesn't kill the worker!
        struct sigaction sa_ign, sa_old;
        sa_ign.sa_handler = SIG_IGN;
        sigemptyset(&sa_ign.sa_mask);
        sa_ign.sa_flags = 0;
        sigaction(SIGPIPE, &sa_ign, &sa_old);

        size_t written = 0;
        off_t offset = tls_batch_offset;
        while (written < length) {
            ssize_t s = splice(fd, &offset, pfd[1], NULL, length - written, 0);
            if (s < 0) {
                if (errno == EINTR) continue;
                break; // Broken pipe (EPIPE) or error
            }
            if (s == 0) break;
            written += s;
        }

        // Restore previous SIGPIPE handler
        sigaction(SIGPIPE, &sa_old, NULL);
    }

    // 8. Close the write end to send EOF to the child
    close(pfd[1]);

    // 9. Wait for the child to finish
    int status = 0;
    if (ret == 0) {
        while (waitpid(pid, &status, 0) == -1) {
            if (errno != EINTR) { ret = -1; break; }
        }
    }

    // 10. Restore signal mask
    sigprocmask(SIG_SETMASK, &oset, NULL);

    if (ret != 0) return 254; // posix_spawnp failed (EAGAIN/ENOMEM) — Internal Framework Error

    if (WIFEXITED(status)) return (WEXITSTATUS(status) == 0) ? EXECUTION_SUCCESS : WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return EXECUTION_FAILURE;
}

// ---------------------------------------------------------
// ring_call: Zero-Tax C Plugin Callback Execution
// ---------------------------------------------------------
// Note: ring_call_main has been moved to the bottom of the file to resolve definition ordering.

// RESTORED LOADABLES MACRO
#define FORKRUN_LOADABLES(X)                                                   \
  X(ring_map, ring_map_main, "ring_map <fd> <len> <array> [delim]", "Fast user-space mapfile") \
  X(ring_exec, ring_exec_main, "ring_exec <fd> <len> <delim> <cmd> [args...]", "Ultra-fast execution of external binaries") \
  X(ring_exec_splice, ring_exec_splice_main, "ring_exec_splice <fd> <len> <cmd> [args...]", "Spawn binary and splice to its stdin") \
  X(ring_call, ring_call_main, "ring_call <fd> <len> <delim> <so> <fn>", "Zero-Tax C Plugin Execution") \
  X(ring_is_spawnable, ring_is_spawnable_main, "ring_is_spawnable <file>", "Check if file is binary or has shebang") \
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
  X(ring_claim, ring_claim_main, "ring_claim [VAR]", "Claim batch")            \
  X(ring_worker, ring_worker_main, "ring_worker [inc|dec]",                    \
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
  X(ring_lseek, ring_lseek_main, "ring_lseek <FD> <OFF> [WHENCE] [VAR]", "Seek fd")    \
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
  X(ring_numa_stats, ring_numa_stats_main, "ring_numa_stats",                  \
    "Print NUMA telemetry")                                                    \
  X(ring_list, ring_list_main, "ring_list [VAR]", "List loadables")            \
  X(ring_poll, ring_poll_main, "ring_poll <spawn_fd> <scan_arr> <work_arr>", "Poll FDs") \
  X(ring_revert_output, ring_revert_output_main, "ring_revert_output <fd>", "Revert partial output") \
  X(ring_ack_init, ring_ack_init_main, "ring_ack_init <fd>", "Sync output offset") \
  X(ring_escrow_put, ring_escrow_put_main, "ring_escrow_put <node> <idx> <cnt> <kills>", "Deposit to escrow") \
  X(ring_dump_resume, ring_dump_resume_main, "ring_dump_resume [bytes]", "Dump checkpoint state") \
  X(ring_set_resume, ring_set_resume_main, "ring_set_resume <horizon> [jagged...]", "Set checkpoint state") \
  X(ring_abort, ring_abort_main, "ring_abort", "Trigger global emergency abort") \
  X(ring_tui, ring_tui_main, "ring_tui [expected_bytes] [order_mode]", "Real-Time Telemetry Dashboard")

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
    while (*p && !isdigit((unsigned char)*p))
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
  const char *lb = strchr(name, '[');
  if (!lb || name[strlen(name) - 1] != ']')
    return bind_variable(name, value, flags);

  size_t base_len = (size_t)(lb - name);
  char base_tmp[256];
  if (base_len >= sizeof(base_tmp))
    return NULL;
  memcpy(base_tmp, name, base_len);
  base_tmp[base_len] = '\0';

  size_t idx_len = strlen(lb + 1) - 1;
  char idx_tmp[256];
  if (idx_len >= sizeof(idx_tmp))
    return NULL;
  memcpy(idx_tmp, lb + 1, idx_len);
  idx_tmp[idx_len] = '\0';

  SHELL_VAR *var = find_variable(base_tmp);
  if (!var) {
    var = make_new_array_variable(base_tmp);
    if (!var)
      return NULL;
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
  if ((long)env_len < sys_arg_max) {
    // Subtract an extra 1MB of safety margin to account for bash environment exports
    long safe_margin = sys_arg_max - (long)env_len - 1048576;
    if (safe_margin > 0)
      return (uint64_t)(safe_margin * 15 / 16);
  }
  return 32768;
}

static int xcreate_anon_file(const char *name) {
  const char *force_fallback = get_string_value("FORKRUN_FORCE_FALLBACK");
  bool use_memfd = true;
  if (force_fallback && (strcmp(force_fallback, "1") == 0))
    use_memfd = false;
  if (use_memfd) {
    int fd = -1;
    const char *use_hugetlb = get_string_value("FORKRUN_USE_HUGETLB");
    if (use_hugetlb && strcmp(use_hugetlb, "1") == 0) {
      fd = syscall(__NR_memfd_create, name, MFD_ALLOW_SEALING | MFD_HUGETLB);
    }
    if (fd < 0) {
      fd = syscall(__NR_memfd_create, name, MFD_ALLOW_SEALING);
    }
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
static __thread off_t last_ack_offset = 0;
static __thread int ack_cached_target_fd = -1;
static __thread int ack_cached_mode = 0;
static __thread uint64_t worker_last_idx = 0;
static __thread uint64_t worker_last_cnt = 0;
static __thread uint32_t worker_last_major = 0;
static __thread uint32_t worker_last_minor = 0;
static __thread uint32_t worker_last_num_kills = 0;
static __thread bool tl_drain_escrow = true;


// ------------------------------------------------------------------
// WorkerBatchState: Pure value struct returned by do_lockfree_claim.
// Contains everything ring_claim_main needs to bind Bash variables,
// without any side-effects during the claim itself.
// ------------------------------------------------------------------
struct WorkerBatchState {
    uint64_t idx;
    uint64_t cnt;
    uint32_t num_kills;
    uint64_t offset;
    uint64_t length;
    uint32_t major;
    uint32_t minor;
};

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
static uint8_t g_explicit_pinning = 0; // NEW

// EscrowPacket: Used as an optimistic transaction recovery queue. If a worker
// process fails or is killed mid-execution, its active transaction is
// rolled back and re-deposited into a side-channel pipe (escrow) for other
// idle workers to steal. Because workers claim exactly 1 slot, there are no
// partial remainders.
// NOTE: A given worker can (at any given time) only have a single escrow claim,
// and these claims are inherently rare occurrences (happen only in crashes).
// This means in practice the escrow pipe buffer will NEVER fill up (even if
// its capacity is 64 KB, and especially not at 1 MB).
struct EscrowPacket {
  uint64_t idx;
  uint64_t cnt;
  uint32_t num_kills;
  uint32_t _pad;
};

// IndexPacket: Legacy flat-mode packet for passing physical offsets.
struct IndexPacket {
  uint64_t idx;
  uint64_t cnt;
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
  uint64_t in_off;   // NEW: Absolute input byte start
  uint64_t in_len;   // NEW: Input byte length
};

#define FLAG_META_READY (1ULL << 63)
#define META_RING_SIZE 4096
#define META_RING_MASK (META_RING_SIZE - 1)

// ChunkMeta: Lock-free metadata describing a slice of physical data added by
// ingest. Workers and the global scanner use this to align physical bounds
// without taking locks.
struct ChunkMeta {
  uint64_t raw_offset;
  uint64_t raw_length;
  uint32_t target_node;
  // major_id aligns with chunk boundaries, minor_id will align with individual
  // records.
  uint32_t major_id;
  volatile uint64_t actual_end ALIGNED(CACHE_LINE);
};

struct IntervalNode {
    uint64_t s;
    uint64_t e;
};

// GlobalState: Contains cross-socket coordination for the pipeline,
struct GlobalState {
  uint64_t ingest_publish_idx ALIGNED(CACHE_LINE);
  uint64_t ingest_eof_idx ALIGNED(CACHE_LINE);
  uint64_t _pad_ingest_waiters[7];

  // NEW: Orderer Ledger (The Checkpoint)
  uint8_t is_resume_mode ALIGNED(CACHE_LINE);
  volatile uint32_t resume_seq; // NEW: Seqlock counter
  uint64_t resume_horizon;
  uint64_t resume_stdout_bytes;
  uint64_t fallow_horizon_bytes; // NEW: Fallback for realtime mode
  uint32_t resume_jagged_count;
  struct IntervalNode resume_jagged[1024];

  uint32_t poisoned_count ALIGNED(CACHE_LINE);

  struct ChunkMeta meta_ring[META_RING_SIZE];
};

// SharedState: Per-NUMA-socket lock-free ring and state counters.
// This enforces "Conservation of Momentum" - each socket manages its own data
// river. Workers on node i read from state[i]. Variables are CACHE_LINE aligned
// to prevent false-sharing ping-pong between cores on the fast path.
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
  uint8_t emergency_abort;
  // v3.3: set to 1 (release) by ring_escrow_put_main whenever a packet is
  // deposited; cleared to 0 (release) by the first worker that drains the
  // pipe to EAGAIN.  Workers check this with a relaxed acquire on every
  // dlc_restart_loop iteration to re-arm tl_drain_escrow — zero syscall cost
  // on the hot path (stays 0 in cache for 99.9% of the run).
  uint8_t escrow_pending;

  uint32_t indexer_waiters ALIGNED(CACHE_LINE);
  uint32_t meta_waiters ALIGNED(CACHE_LINE);
  uint64_t min_idx;

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
  uint8_t numa_enabled;
  uint8_t exact_lines;
  uint8_t cfg_delim; // Record delimiter character (default '\n')

  uint64_t current_batch_size ALIGNED(CACHE_LINE);
  uint64_t uma_ingest_offset ALIGNED(CACHE_LINE);
  uint64_t total_lines_scanned ALIGNED(CACHE_LINE);

  uint64_t stats_chunks_assigned ALIGNED(CACHE_LINE);
  uint64_t stats_chunks_processed;
  uint64_t stats_chunks_i_stole;
  uint64_t stats_chunks_stolen_from_me;

  uint64_t current_stall_meter ALIGNED(CACHE_LINE);
  uint64_t current_starve_meter;

  uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
  uint64_t end_ring[RING_SIZE] ALIGNED(4096);
  uint32_t major_ring[RING_SIZE] ALIGNED(4096);
  uint32_t minor_ring[RING_SIZE] ALIGNED(4096);

  // NEW: Dynamic Topology-Aware Steal Thresholds
  uint8_t steal_threshold[1024] ALIGNED(CACHE_LINE);
  uint8_t base_steal_threshold[1024]; // Stores baseline invariants
  uint32_t chunk_buffer_limit; // Dynamic limit (Ingest -> Scanner)
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

// EMERGENCY SHUTDOWN: Global fire alarm sentry.
// Any thread (Worker or Orderer) can call this to trigger an immediate system-wide
// abort. It atomically flips emergency_abort to 1 (CAS ensures we only blast once),
// then blasts ALL EOF eventfds to wake every sleeping poll across the engine.
// Data eventfds are left untouched to preserve the conservation laws of the ring.
static inline void pull_fire_alarm() {
    if (!state) return;
    // CAS: Only the first caller blasts the eventfds
    uint8_t expected = 0;
    if (__atomic_compare_exchange_n(&state[0].emergency_abort, &expected, 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_RELAXED)) {
        uint64_t blast = 999999;
        for (uint32_t n = 0; n < allocated_num_nodes; n++) {
            if (evfd_eof_arr && evfd_eof_arr[n] >= 0) sys_write(evfd_eof_arr[n], &blast, 8);
        }
        if (evfd_ingest_eof >= 0) sys_write(evfd_ingest_eof, &blast, 8);
        if (evfd_chunk_done >= 0) sys_write(evfd_chunk_done, &blast, 8); // Wake up Ingest
    }
}

#define OOM_WAIT_FOR_MEMORY(free_b_var, threshold, si_var, mu_var)             \
  do {                                                                         \
    int _oom_sleep_us = 1000;                                                  \
    int _oom_waited_us = 0;                                                    \
    while ((free_b_var) < (threshold) && _oom_waited_us < 30000000) {          \
      if (state && atomic_load_relaxed(&state[0].emergency_abort)) break;      \
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
      if (strncmp(buf, "max", 3) == 0)
        return -1;
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
      if (max_val > 9000000000000000000ULL)
        return -1;
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

// ==============================================================================
// OOM PROTECTION AND MEMORY SENSING
// ==============================================================================

// Helper to get available memory (accounting for reclaimable cache like memfd)
static inline uint64_t get_mem_available(struct sysinfo *si) {
    uint64_t mem_avail = 0;
    int fd = open("/proc/meminfo", O_RDONLY);
    if (fd >= 0) {
        char buf[1024];
        ssize_t n = sys_read(fd, buf, sizeof(buf) - 1);
        close(fd);
        if (n > 0) {
            buf[n] = '\0';
            char *p = strstr(buf, "MemAvailable:");
            if (p) {
                p += 13;
                while (*p == ' ' || *p == '\t') p++;
                mem_avail = strtoull(p, NULL, 10) * 1024ULL; // KB to Bytes
            }
        }
    }
    if (mem_avail > 0) return mem_avail;

    // Fallback for very old kernels without MemAvailable exposed
    uint64_t mu = (uint64_t)si->mem_unit ? si->mem_unit : 1;
    return ((uint64_t)si->freeram + (uint64_t)si->bufferram) * mu;
}

static inline void check_memory_pressure(uint64_t *total_moved,
                                         uint64_t *next_check,
                                         uint64_t oom_threshold) {
  if (*total_moved > *next_check) {
    uint64_t free_b = 0;
    if (get_cgroup_free_memory(&free_b) == 0) {
      if (free_b < oom_threshold && state) {
        int _oom_sleep_us = 1000;
        int _oom_waited_us = 0;
        while (free_b < oom_threshold && _oom_waited_us < 30000000) {
          if (atomic_load_relaxed(&state[0].emergency_abort)) break;
          usleep(_oom_sleep_us);
          _oom_waited_us += _oom_sleep_us;
          get_cgroup_free_memory(&free_b);
          _oom_sleep_us += _oom_sleep_us >> 1;
          if (_oom_sleep_us > 100000)
            _oom_sleep_us = 100000;
        }
      }
    } else {
      struct sysinfo si;
      if (sysinfo(&si) == 0) {
        free_b = get_mem_available(&si);
        if (free_b < oom_threshold && state) {
          int _oom_sleep_us = 1000;
          int _oom_waited_us = 0;
          while (free_b < oom_threshold && _oom_waited_us < 30000000) {
            if (atomic_load_relaxed(&state[0].emergency_abort)) break;
            usleep(_oom_sleep_us);
            _oom_waited_us += _oom_sleep_us;
            sysinfo(&si);
            free_b = get_mem_available(&si);
            _oom_sleep_us += _oom_sleep_us >> 1;
            if (_oom_sleep_us > 100000)
              _oom_sleep_us = 100000;
          }
        }
      }
    }
    // PHYSICS FIX: properly track next check boundary to prevent check spamming
    *next_check = *total_moved + 16 * 1024 * 1024;
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
  if (!strcmp(type, "workers"))
    return sysconf(_SC_NPROCESSORS_ONLN);
  if (!strcmp(type, "lines"))
    return 4096;
  if (!strcmp(type, "bytes")) {
    uint64_t l2 = get_cache_bytes();
    if (stdin_mode)
      return (l2 < (1ULL << 19)) ? l2 : (1ULL << 19);
    uint64_t arg = get_arg_max_bytes();
    return (l2 < arg) ? l2 : arg;
  }
  return 1;
}

static uint64_t get_v_max(const char *type, bool stdin_mode) {
  if (!strcmp(type, "workers"))
    return sysconf(_SC_NPROCESSORS_ONLN) * 2;
  if (!strcmp(type, "lines"))
    return 65536;
  if (!strcmp(type, "bytes")) {
    if (stdin_mode) {
      uint64_t l2 = get_cache_bytes();
      return (l2 < (1ULL << 20)) ? l2 : (1ULL << 20);
    } else
      return get_arg_max_bytes();
  }
  return 1;
}

static uint32_t cfg_state = 0;
static uint64_t user_vals[6] = {0};

static void apply_config(char type, char sub, const char *arg) {
  uint32_t set_mask = 0;
  int val_code = S_USER;
  uint64_t u_val = 0;

  if (strcmp(arg, "x") == 0) {
    if (type == 1) {
      set_mask |= M_BMODE;
    } else if (type == 2) {
    }
  } else {
    if (arg[0] == '\0')
      val_code = S_DEF;
    else if (strcmp(arg, "0") == 0)
      val_code = S_DEF;
    else if (strcmp(arg, "-0") == 0)
      val_code = S_MIN;
    else if (strcmp(arg, "+0") == 0)
      val_code = S_MAX;
    else if (strcmp(arg, "-1") == 0)
      val_code = S_MAX;
    else {
      val_code = S_USER;
      u_val = (uint64_t)atoll(arg);
      if (u_val < 1)
        u_val = 1;
    }

    if (type == 1) {
      cfg_state &= ~M_BMODE;
      cfg_state &= ~M_B_ALL;
    }
    if (type == 2) {
      cfg_state |= M_BMODE;
      cfg_state |= M_STDIN;
      cfg_state &= ~M_L_ALL;
    }

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
      if (sub == 0 || sub == 1) {
        cfg_state &= ~M_W_A;
        APPLY_SLOT(0, SH_W_A);
      }
      if (sub == 0 || sub == 2) {
        cfg_state &= ~M_W_B;
        APPLY_SLOT(1, SH_W_B);
      }
    }
    if (type == 1) {
      if (sub == 0 || sub == 1) {
        cfg_state &= ~M_L_A;
        APPLY_SLOT(2, SH_L_A);
      }
      if (sub == 0 || sub == 2) {
        cfg_state &= ~M_L_B;
        APPLY_SLOT(3, SH_L_B);
      }
    }
    if (type == 2) {
      if (sub == 0 || sub == 1) {
        cfg_state &= ~M_B_A;
        APPLY_SLOT(4, SH_B_A);
      }
      if (sub == 0 || sub == 2) {
        cfg_state &= ~M_B_B;
        APPLY_SLOT(5, SH_B_B);
      }
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
  } else
    g_debug = 0;

  global_num_nodes = 0;
  g_explicit_pinning = 0; // NEW
  for (int i = 1; i < argc; i++) {
    if (strncmp(argv[i], "--numa-map=", 11) == 0) {
      g_explicit_pinning = 1; // NEW
      global_num_nodes = 1;
      for (const char *c = argv[i] + 11; *c; c++)
        if (*c == ',')
          global_num_nodes++;

      if (g_logical_to_phys_map)
        free(g_logical_to_phys_map);
      g_logical_to_phys_map = malloc(global_num_nodes * sizeof(uint32_t));
      if (!g_logical_to_phys_map)
        return EXECUTION_FAILURE;
      const char *p = argv[i] + 11;
      for (uint32_t j = 0; j < global_num_nodes; j++) {
        g_logical_to_phys_map[j] = (uint32_t)strtoul(p, (char **)&p, 10);
        if (*p == ',')
          p++;
      }
    }
  }

  if (global_num_nodes == 0 || g_logical_to_phys_map == NULL) {
    global_num_nodes = 1;
    if (g_logical_to_phys_map)
      free(g_logical_to_phys_map);
    g_logical_to_phys_map = malloc(sizeof(uint32_t));
    if (!g_logical_to_phys_map)
      return EXECUTION_FAILURE;
    g_logical_to_phys_map[0] = 0;
  }

  // CRITICAL FIX: Prevent buffer overflow in steal_threshold arrays
  if (global_num_nodes > 1024) {
    builtin_error("forkrun: global_num_nodes exceeds maximum limit of 1024");
    if (g_logical_to_phys_map) {
      free(g_logical_to_phys_map);
      g_logical_to_phys_map = NULL;
    }
    return EXECUTION_FAILURE;
  }

  char node_buf[32];
  snprintf(node_buf, sizeof(node_buf), "%u", global_num_nodes);
  bind_variable("FORKRUN_NUM_NODES", node_buf, 0);

  if (g_state != NULL) {
    if (global_num_nodes != allocated_num_nodes && global_num_nodes != 0) {
      builtin_error(
          "forkrun: cannot change --nodes without calling ring_destroy first");
      return EXECUTION_FAILURE;
    }
    atomic_store_relaxed(&g_state->ingest_publish_idx, 0);
    atomic_store_relaxed(&g_state->ingest_eof_idx, ~(uint64_t)0);

    // PHYSICS FIX: Comprehensively drain all eventfds to prevent false EOFs
    // and spurious wakeups from previous invocations.
    uint64_t _drain;
    while (sys_read(evfd_ingest_eof, &_drain, 8) > 0) {
    }
    while (sys_read(evfd_ingest_data, &_drain, 8) > 0) {
    }
    while (sys_read(evfd_chunk_done, &_drain, 8) > 0) {
    }

    for (uint32_t n = 0; n < global_num_nodes; n++) {
      if (evfd_eof_arr && evfd_eof_arr[n] >= 0)
        while (sys_read(evfd_eof_arr[n], &_drain, 8) > 0) {
        }
      if (evfd_data_arr && evfd_data_arr[n] >= 0)
        while (sys_read(evfd_data_arr[n], &_drain, 8) > 0) {
        }
      if (evfd_indexer_arr && evfd_indexer_arr[n] >= 0)
        while (sys_read(evfd_indexer_arr[n], &_drain, 8) > 0) {
        }
      if (evfd_meta_arr && evfd_meta_arr[n] >= 0)
        while (sys_read(evfd_meta_arr[n], &_drain, 8) > 0) {
        }

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
      atomic_store_relaxed(&state[n].emergency_abort, 0);
      atomic_store_relaxed(&state[n].escrow_pending, 0);
      atomic_store_relaxed(&state[n].tail_idx, 0);
      atomic_store_relaxed(&state[n].scanner_finished, 0);
      atomic_store_relaxed(&state[n].stats_chunks_assigned, 0);
      atomic_store_relaxed(&state[n].stats_chunks_processed, 0);
      atomic_store_relaxed(&state[n].stats_chunks_i_stole, 0);
      atomic_store_relaxed(&state[n].stats_chunks_stolen_from_me, 0);

      // Reset waiters to prevent spurious initial early flushes
      atomic_store_relaxed(&state[n].active_waiters, 0);
      atomic_store_relaxed(&state[n].indexer_waiters, 0);
      atomic_store_relaxed(&state[n].meta_waiters, 0);

      // Reset PID Controller / Flow State
      atomic_store_relaxed(&state[n].active_workers, 0); // Rely on Bash 'ring_worker inc'
      atomic_store_relaxed(&state[n].current_batch_size, 0);
      atomic_store_relaxed(&state[n].uma_ingest_offset, 0);
      atomic_store_relaxed(&state[n].total_lines_scanned, 0);

      state[n].offset_ring[0] = 0;
      if (fd_escrow_r && fd_escrow_r[n] >= 0) {
        char dump[1024];
        while (sys_read(fd_escrow_r[n], dump, sizeof(dump)) > 0) {
        }
      }
    }
    return EXECUTION_SUCCESS;
  }

  allocated_num_nodes = global_num_nodes;

  // --- PHYSICS FIX: Force g_state size to pad out to a 4K boundary ---
  long pg_sz = sysconf(_SC_PAGESIZE);
  uint64_t align_sz = (pg_sz > 0) ? (uint64_t)pg_sz : 4096ULL;

  size_t global_size = (sizeof(struct GlobalState) + align_sz - 1) & ~(align_sz - 1);

  size_t total_size =
      global_size + (sizeof(struct SharedState) * global_num_nodes);
  total_size = (total_size + align_sz - 1) & ~(align_sz - 1);

  void *p = mmap(NULL, total_size, PROT_READ | PROT_WRITE,
                 MAP_SHARED | MAP_ANONYMOUS, -1, 0);
  if (p == MAP_FAILED) {
    builtin_error("mmap: %s", strerror(errno));
    return EXECUTION_FAILURE;
  }

  g_state = (struct GlobalState *)p;
  // Step exactly 'global_size' bytes forward so state stays 4096-aligned
  state = (struct SharedState *)((char *)p + global_size);
  memset(p, 0, total_size);
  atomic_store_relaxed(&g_state->ingest_eof_idx, ~(uint64_t)0);

  // Config register: 0xBBLLWW where BB=bytes, LL=lines, WW=workers
  // Each pair is (upper nibble = max policy, lower nibble = start policy)
  // Nibble codes: 0=disabled 1=literal-1 2=default-max 3=hard-max 8=user-val
  cfg_state =
      0x202121; // DEFAULT: bytes=off/def, lines=1..4096, workers=1..$nproc
  int stdin_explicit = -1;
  const char *out_array_name = NULL;
  uint64_t parsed_limit = 0;
  int64_t parsed_timeout = -1;
  uint8_t parsed_exact_lines = 0;
  uint8_t parsed_delim = '\n';

  for (int i = 1; i < argc; i++) {
    const char *arg = argv[i];
    if (strncmp(arg, "--workers=", 10) == 0)
      apply_config(0, 0, arg + 10);
    else if (strncmp(arg, "--workers0=", 11) == 0)
      apply_config(0, 1, arg + 11);
    else if (strncmp(arg, "--workers-max=", 14) == 0)
      apply_config(0, 2, arg + 14);
    else if (strncmp(arg, "--lines=", 8) == 0)
      apply_config(1, 0, arg + 8);
    else if (strncmp(arg, "--lines0=", 9) == 0)
      apply_config(1, 1, arg + 9);
    else if (strncmp(arg, "--lines-max=", 12) == 0)
      apply_config(1, 2, arg + 12);
    else if (strncmp(arg, "--bytes=", 8) == 0)
      apply_config(2, 0, arg + 8);
    else if (strncmp(arg, "--bytes0=", 9) == 0)
      apply_config(2, 1, arg + 9);
    else if (strncmp(arg, "--bytes-max=", 12) == 0)
      apply_config(2, 2, arg + 12);
    else if (strncmp(arg, "--limit=", 8) == 0)
      parsed_limit = (uint64_t)atoll(arg + 8);
    else if (strncmp(arg, "--timeout=", 10) == 0)
      parsed_timeout = atoll(arg + 10);
    else if (strncmp(arg, "--greedy", 8) == 0)
      parsed_timeout = 0;
    else if (strncmp(arg, "--exact-lines", 13) == 0)
      parsed_exact_lines = 1;
    else if (strncmp(arg, "--out=", 6) == 0)
      out_array_name = arg + 6;
    else if (strncmp(arg, "--stdin", 7) == 0)
      stdin_explicit = 1;
    else if (strncmp(arg, "--no-stdin", 10) == 0)
      stdin_explicit = 0;
    else if (strncmp(arg, "--delim=", 8) == 0)
      parsed_delim = (uint8_t)arg[8];
    else if (strncmp(arg, "--nodes=", 8) != 0 &&
             strncmp(arg, "--numa-map=", 11) != 0 && arg[0] != '-')
      out_array_name = arg;
  }

  if (stdin_explicit != -1) {
    if (stdin_explicit)
      cfg_state |= M_STDIN;
    else
      cfg_state &= ~M_STDIN;
  } else {
    if (cfg_state & M_BMODE)
      cfg_state |= M_STDIN;
    else
      cfg_state &= ~M_STDIN;
  }

  bool stdin_mode = (cfg_state & M_STDIN);
  bool byte_mode = (cfg_state & M_BMODE);

  uint64_t vals[6], defs[6], maxs[6];
  defs[0] = get_v_def("workers", false);
  maxs[0] = get_v_max("workers", false);
  defs[1] = defs[0];
  maxs[1] = maxs[0];
  defs[2] = get_v_def("lines", false);
  maxs[2] = get_v_max("lines", false);
  defs[3] = defs[2];
  maxs[3] = maxs[2];
  defs[4] = get_v_def("bytes", stdin_mode);
  maxs[4] = get_v_max("bytes", stdin_mode);
  defs[5] = defs[4];
  maxs[5] = maxs[4];

  for (int i = 0; i < 6; i++) {
    int code = (cfg_state >> (i * 4)) & 0xF;
    if (code == S_USER)
      vals[i] = user_vals[i];
    else if (code == S_MIN)
      vals[i] = 1;
    else if (code == S_DEF)
      vals[i] = defs[i];
    else if (code == S_MAX)
      vals[i] = maxs[i];
    else if (code == S_DIS)
      vals[i] = 0;
    else
      vals[i] = 1;
  }

  if (vals[0] > maxs[0])
    vals[0] = maxs[0];
  if (vals[1] > maxs[1])
    vals[1] = maxs[1];
  if (vals[0] > vals[1])
    vals[0] = vals[1];
  if (vals[0] == 0)
    vals[0] = 1;
  if (vals[2] > maxs[2])
    vals[2] = maxs[2];
  if (vals[3] > maxs[3])
    vals[3] = maxs[3];
  if (vals[2] > vals[3])
    vals[2] = vals[3];
  if (vals[4] > maxs[4])
    vals[4] = maxs[4];
  if (vals[5] > maxs[5])
    vals[5] = maxs[5];
  if (vals[4] > vals[5])
    vals[4] = vals[5];

  for (uint32_t n = 0; n < global_num_nodes; n++) {
    uint64_t w_start_balanced = vals[0] / global_num_nodes;
    if (w_start_balanced < 1)
      w_start_balanced = 1;
    uint64_t w_max_balanced = vals[1] / global_num_nodes;
    if (w_max_balanced < 1)
      w_max_balanced = 1;

    state[n].cfg_w_start = w_start_balanced;
    state[n].cfg_w_max = w_max_balanced;
    state[n].mode_byte = byte_mode ? 1 : 0;
    state[n].numa_enabled = (global_num_nodes > 1) ? 1 : 0;
    state[n].exact_lines = parsed_exact_lines;
    state[n].cfg_delim = parsed_delim;
    state[n].cfg_limit = parsed_limit;
    state[n].cfg_timeout_us = parsed_timeout;
    atomic_store_relaxed(&state[n].chunk_buffer_limit, 4); // Default to 3 chunks active (limit = 4)

    if (byte_mode) {
      state[n].cfg_batch_start = vals[4];
      state[n].cfg_batch_max = (vals[5] > MAX_BATCH_LINES) ? MAX_BATCH_LINES : vals[5];
      state[n].cfg_chunk_bytes = vals[5];
      state[n].cfg_line_max = vals[5];
    } else {
      state[n].cfg_batch_start = vals[2];
      state[n].cfg_batch_max = (vals[3] > MAX_BATCH_LINES) ? MAX_BATCH_LINES : vals[3];
      int bb_code = (cfg_state >> SH_B_B) & 0xF;
      if (bb_code != S_DIS)
        state[n].cfg_line_max = vals[5];
      else
        state[n].cfg_line_max = maxs[4];
    }

    state[n].fixed_workers = (state[n].cfg_w_start == state[n].cfg_w_max);
    state[n].fixed_batch = (state[n].cfg_batch_start == state[n].cfg_batch_max);
    // memset already zeroed escrow_pending; explicit store for documentation.
    atomic_store_relaxed(&state[n].escrow_pending, 0);

    // Dynamic Topology-Aware Steal Thresholds from ACPI SRAT Table
    uint32_t phys_n = g_logical_to_phys_map ? g_logical_to_phys_map[n] : 0;
    char dist_path[256];
    snprintf(dist_path, sizeof(dist_path),
             "/sys/devices/system/node/node%u/distance", phys_n);
    int dist_fd = open(dist_path, O_RDONLY);
    char dist_buf[4096] = {0};
    if (dist_fd >= 0) {
      sys_read(dist_fd, dist_buf, sizeof(dist_buf) - 1);
      close(dist_fd);
    }

    for (uint32_t i = 0; i < global_num_nodes; i++) {
      uint32_t phys_i = g_logical_to_phys_map ? g_logical_to_phys_map[i] : 0;
      int dist = (n == i) ? 10 : 20;

      if (dist_buf[0] != '\0') {
        const char *p = dist_buf;
        for (uint32_t skip = 0; skip < phys_i && *p; skip++) {
          while (*p && !isspace((unsigned char)*p))
            p++;
          while (*p && isspace((unsigned char)*p))
            p++;
        }
        if (*p && isdigit((unsigned char)*p))
          dist = atoi(p);
      }

      // Physics Formula: 1 + (dist / 10)
      int thresh = 1 + (dist / 10);

      if (thresh < 2)
        thresh = 2;
      state[n].steal_threshold[i] = (uint8_t)thresh;
      state[n].base_steal_threshold[i] = (uint8_t)thresh; // Lock baseline
    }
  }

  evfd_data_arr = calloc(global_num_nodes, sizeof(int));
  evfd_eof_arr = calloc(global_num_nodes, sizeof(int));
  evfd_indexer_arr = calloc(global_num_nodes, sizeof(int));
  evfd_meta_arr = calloc(global_num_nodes, sizeof(int));
  fd_escrow_r = calloc(global_num_nodes, sizeof(int));
  fd_escrow_w = calloc(global_num_nodes, sizeof(int));

  if (!evfd_data_arr || !evfd_eof_arr || !evfd_indexer_arr || !evfd_meta_arr ||
      !fd_escrow_r || !fd_escrow_w) {
    builtin_error("forkrun: malloc failed during ring_init");
    return EXECUTION_FAILURE;
  }

  for (uint32_t i = 0; i < global_num_nodes; i++) {
    evfd_data_arr[i] = -1;
    evfd_eof_arr[i] = -1;
    evfd_indexer_arr[i] = -1;
    evfd_meta_arr[i] = -1;
    fd_escrow_r[i] = -1;
    fd_escrow_w[i] = -1;
  }

  for (uint32_t n = 0; n < global_num_nodes; n++) {
    evfd_data_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_eof_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    evfd_indexer_arr[n] =
        eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);
    evfd_meta_arr[n] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);

    if (evfd_data_arr[n] < 0 || evfd_eof_arr[n] < 0 ||
        evfd_indexer_arr[n] < 0 || evfd_meta_arr[n] < 0) {
        builtin_error("forkrun: eventfd creation failed (FD limit reached?)");
        ring_destroy_main(0, NULL);
        return EXECUTION_FAILURE;
    }

    int pfd[2];
    if (pipe(pfd) == 0) {
      fcntl(pfd[0], F_SETFL, O_NONBLOCK);
      fcntl(pfd[1], F_SETFL, O_NONBLOCK);
      fcntl(pfd[0], F_SETFD, FD_CLOEXEC);
      fcntl(pfd[1], F_SETFD, FD_CLOEXEC);
      fcntl(pfd[1], F_SETPIPE_SZ, 1048576);
      fd_escrow_r[n] = pfd[0];
      fd_escrow_w[n] = pfd[1];
    } else {
      fd_escrow_r[n] = -1;
      fd_escrow_w[n] = -1;
    }
  }

  evfd_ingest_data = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  evfd_ingest_eof = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  evfd_chunk_done = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK | EFD_SEMAPHORE);

  if (evfd_ingest_data < 0 || evfd_ingest_eof < 0 || evfd_chunk_done < 0) {
      builtin_error("forkrun: eventfd creation failed");
      ring_destroy_main(0, NULL);
      return EXECUTION_FAILURE;
  }

  evfd_data = evfd_data_arr[0];
  fd_escrow[0] = fd_escrow_r[0];
  fd_escrow[1] = fd_escrow_w[0];

  char buf[32];
  snprintf(buf, sizeof(buf), "%d", evfd_data_arr[0]);
  bind_variable("EVFD_RING_DATA", buf, 0);
  snprintf(buf, sizeof(buf), "%d", evfd_ingest_data);
  bind_variable("EVFD_RING_INGEST_DATA", buf, 0);
  snprintf(buf, sizeof(buf), "%d", evfd_ingest_eof);
  bind_variable("EVFD_RING_INGEST_EOF", buf, 0);

  if (out_array_name) {
    SHELL_VAR *v = find_variable(out_array_name);
    if (v && !array_p(v)) {
      unbind_variable(out_array_name);
      v = NULL;
    }
    if (!v)
      v = make_new_array_variable(out_array_name);
    if (!v) {
      ring_destroy_main(0, NULL);
      return EXECUTION_FAILURE;
    }

    // Calculate true total max workers across all nodes to prevent out-of-bounds
    uint64_t actual_total_w_max = 0;
    for (uint32_t n = 0; n < global_num_nodes; n++) {
        uint64_t w_max_balanced = vals[1] / global_num_nodes;
        if (w_max_balanced < 1) w_max_balanced = 1;
        actual_total_w_max += w_max_balanced;
    }

    int *created_fds = malloc(sizeof(int) * actual_total_w_max);
    if (!created_fds) {
      ring_destroy_main(0, NULL);
      return EXECUTION_FAILURE;
    }
    int created_cnt = 0;
    int failure = 0;
    for (uint64_t i = 0; i < actual_total_w_max; i++) {
      int fd = xcreate_anon_file("forkrun_out");
      if (fd >= 0) {
        created_fds[created_cnt++] = fd;
        char val[32];
        snprintf(val, sizeof(val), "%d", fd);
        bind_array_element(v, i, val, 0);
      } else {
        failure = 1;
        break;
      }
    }
    if (failure) {
      for (int k = 0; k < created_cnt; k++)
        close(created_fds[k]);
      free(created_fds);
      ring_destroy_main(0, NULL);
      return EXECUTION_FAILURE;
    }
    free(created_fds);
  }

  int probe_fd[2];
  int pipe_cap = 65536;
  if (pipe(probe_fd) == 0) {
    int ret = fcntl(probe_fd[1], F_SETPIPE_SZ, 1048576);
    if (ret >= 0)
      pipe_cap = ret;
    else {
      ret = fcntl(probe_fd[1], F_GETPIPE_SZ);
      if (ret > 0)
        pipe_cap = ret;
    }
    close(probe_fd[0]);
    close(probe_fd[1]);
  }

  char var_buf[64];
  snprintf(var_buf, sizeof(var_buf), "%d", pipe_cap);
  bind_variable("RING_PIPE_CAPACITY", var_buf, 0);
  snprintf(var_buf, sizeof(var_buf), "%lu", state[0].cfg_line_max);
  bind_variable("RING_BYTES_MAX", var_buf, 0);

  return EXECUTION_SUCCESS;
}

static int ring_destroy_main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  if (g_state) {
    long pg_sz = sysconf(_SC_PAGESIZE);
    uint64_t align_sz = (pg_sz > 0) ? (uint64_t)pg_sz : 4096ULL;
    size_t global_size = (sizeof(struct GlobalState) + align_sz - 1) & ~(align_sz - 1);
    size_t total_size =
        global_size + (sizeof(struct SharedState) * allocated_num_nodes);
    total_size = (total_size + align_sz - 1) & ~(align_sz - 1);
    munmap(g_state, total_size);
    g_state = NULL;
    state = NULL;
  }
  if (evfd_data_arr) {
    for (uint32_t n = 0; n < allocated_num_nodes; n++) {
      if (evfd_data_arr[n] >= 0)
        close(evfd_data_arr[n]);
      if (evfd_eof_arr && evfd_eof_arr[n] >= 0)
        close(evfd_eof_arr[n]);
      if (evfd_indexer_arr && evfd_indexer_arr[n] >= 0)
        close(evfd_indexer_arr[n]);
      if (evfd_meta_arr && evfd_meta_arr[n] >= 0)
        close(evfd_meta_arr[n]);
      if (fd_escrow_r && fd_escrow_r[n] >= 0)
        close(fd_escrow_r[n]);
      if (fd_escrow_w && fd_escrow_w[n] >= 0)
        close(fd_escrow_w[n]);
    }
    free(evfd_data_arr);
    evfd_data_arr = NULL;
    if (evfd_eof_arr) {
      free(evfd_eof_arr);
      evfd_eof_arr = NULL;
    }
    if (evfd_indexer_arr) {
      free(evfd_indexer_arr);
      evfd_indexer_arr = NULL;
    }
    if (evfd_meta_arr) {
      free(evfd_meta_arr);
      evfd_meta_arr = NULL;
    }
    free(fd_escrow_r);
    fd_escrow_r = NULL;
    free(fd_escrow_w);
    fd_escrow_w = NULL;
  }
  if (g_logical_to_phys_map) {
    free(g_logical_to_phys_map);
    g_logical_to_phys_map = NULL;
  }
  if (evfd_ingest_data >= 0) {
    close(evfd_ingest_data);
    evfd_ingest_data = -1;
  }
  if (evfd_ingest_eof >= 0) {
    close(evfd_ingest_eof);
    evfd_ingest_eof = -1;
  }
  if (evfd_chunk_done >= 0) {
    close(evfd_chunk_done);
    evfd_chunk_done = -1;
  }
  unbind_variable("EVFD_RING_DATA");
  unbind_variable("EVFD_RING_INGEST_DATA");
  unbind_variable("EVFD_RING_INGEST_EOF");
  return EXECUTION_SUCCESS;
}

// ==============================================================================
// 4. NUMA INGEST
// ==============================================================================

// NUMA Ingest (Born-local): Reads data from stdin and splices it into a shared
// memfd. It applies `set_mempolicy(MPOL_BIND)` to physically place the data
// pages on a specific NUMA node *before* any worker touches them, thus
// enforcing "Conservation of Locality" and preventing cross-socket memory
// traffic. The target node is selected based on indexer backpressure (self
// load-balancing).

static int ring_numa_ingest_main(int argc, char **argv) {
  if (argc < 4)
    return EXECUTION_FAILURE;
  int infd = atoi(argv[1]);
  int outfd = atoi(argv[2]);
  int num_nodes = atoi(argv[3]);
  if (num_nodes < 1)
    num_nodes = 1;
  if (num_nodes > 1024)
    num_nodes = 1024;

  uint64_t chunk_size = 2 * 1024 * 1024ULL;

  // PHYSICS FIX: Small File NUMA Starvation Prevention
  // If the input is a regular file, scale the chunk size down to ensure every
  // NUMA socket receives at least 2 chunks during initial distribution.
  struct stat st;
  if (fstat(infd, &st) == 0) {
      if (S_ISFIFO(st.st_mode)) {
          fcntl(infd, F_SETPIPE_SZ, 1048576); // Expand pipe to 1MB
      } else if (S_ISREG(st.st_mode) && st.st_size > 0) {
          uint64_t ideal = (uint64_t)st.st_size / (uint64_t)(num_nodes * 2);
          if (ideal < chunk_size) {
              uint64_t p2 = 1ULL << fast_log2(ideal);
              chunk_size = (p2 < 4096) ? 4096 : p2;
          }
      }
  }

  if (state[0].mode_byte) {
    uint64_t L = state[0].cfg_batch_start;
    if (L > 0) {
      uint64_t mult = (chunk_size + L - 1) / L;
      chunk_size = mult * L;
    }
  }

  // --- OOM Protection Initialization ---
  uint64_t oom_threshold = 134217728;
  long threshold_div = 128;
  const char *s_div = get_string_value("RING_INGEST_DIVISOR");
  if (s_div) {
    long v = atol(s_div);
    if (v > 0)
      threshold_div = v;
  }
  struct sysinfo si_init;
  if (sysinfo(&si_init) == 0) {
    uint64_t mu = (uint64_t)si_init.mem_unit ? si_init.mem_unit : 1;
    oom_threshold = ((uint64_t)si_init.totalram * mu) / (uint64_t)threshold_div;
  }
  uint64_t total_moved = 0;
  uint64_t next_check = 16 * 1024 * 1024;
  // -------------------------------------

  uint64_t current_offset = 0;
  uint32_t current_major = 0;
  int last_target = -1;
  bool limit_reached_exit = false;

  // PHYSICS FIX: Geometric Accumulation Ramp
  uint64_t accum_target = (65536 > chunk_size) ? chunk_size : 65536; // Start at 64 KB floor (or chunk_size if smaller)
  uint32_t accum_count = 0;
  uint64_t bytes_to_current_node = 0;

  unsigned long test_mask = 1UL;
  bool numa_enabled =
      (syscall(__NR_set_mempolicy, MPOL_BIND, &test_mask, 64) == 0);
  if (numa_enabled)
    syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);

#define BITS_PER_LONG (sizeof(unsigned long) * 8)
  uint32_t max_phys_id = 0;
  if (g_logical_to_phys_map) {
    for (int i = 0; i < num_nodes; i++)
      if (g_logical_to_phys_map[i] > max_phys_id)
        max_phys_id = g_logical_to_phys_map[i];
  }
  int mask_words = (max_phys_id / BITS_PER_LONG) + 1;
  unsigned long *nodemask = malloc(mask_words * sizeof(unsigned long));
  if (!nodemask)
    return EXECUTION_FAILURE;

  enum {
    TM_UNKNOWN = 0,
    TM_COPY_FILE_RANGE,
    TM_SENDFILE,
    TM_READ_WRITE
  } transfer_method = TM_UNKNOWN;
  char *bounce_buf = NULL;
  uint64_t one = 1;

  for (int i = 0; i < num_nodes * 2; i++) {
    sys_write(evfd_chunk_done, &one, 8);
  }

#define NUMA_CHECK_SCANNERS_DONE() do { \
  if (atomic_load_relaxed(&state[0].emergency_abort)) { \
    limit_reached_exit = true; \
    goto ingest_done; \
  } \
  if (state[0].cfg_limit > 0) { \
    bool _all_done = true; \
    for (int _i = 0; _i < num_nodes; _i++) { \
      if (!atomic_load_acquire(&state[_i].scanner_finished)) { \
        _all_done = false; \
        break; \
      } \
    } \
    if (_all_done) { \
      limit_reached_exit = true; \
      goto ingest_done; \
    } \
  } \
} while(0)

  uint64_t last_global_stolen = 0;
  uint32_t current_buffer_limit = 4; // 3 chunks ahead
  uint32_t I_meter = 50;

  while (1) {
    NUMA_CHECK_SCANNERS_DONE();
    check_memory_pressure(&total_moved, &next_check, oom_threshold);

    bool need_new_target = false;
    if (last_target == -1) {
        need_new_target = true;
    } else if (bytes_to_current_node >= accum_target) {
        need_new_target = true;
    } else if (bytes_to_current_node >= 65536) {
        // Starvation Backpressure: if any OTHER node is empty, switch early
        for (int i = 0; i < num_nodes; i++) {
            if (i == last_target) continue;
            uint64_t h = atomic_load_relaxed(&state[i].chunk_queue_head);
            uint64_t t = atomic_load_relaxed(&state[i].chunk_queue_tail);
            if (h == t) {
                need_new_target = true;
                break;
            }
        }
    }

    int target_node = last_target;
    if (need_new_target) {
        int min_backlog = INT_MAX;
        for (int i = 0; i < num_nodes; i++) {
          int check = (last_target + 1 + i) % num_nodes;
          uint64_t h = atomic_load_relaxed(&state[check].chunk_queue_head);
          uint64_t t = atomic_load_relaxed(&state[check].chunk_queue_tail);
          int bl = (int)(h - t);
          if (bl < min_backlog) {
            min_backlog = bl;
            target_node = check;
          }
        }

        if (last_target != -1) {
            accum_count++;
            // Geometric Double: After N chunks, double the accumulation target
            if (accum_count >= (uint32_t)num_nodes) {
                accum_target *= 2;
                if (accum_target > chunk_size) accum_target = chunk_size;
                accum_count = 0;
            }
        }
        bytes_to_current_node = 0;
    }

    // DYNAMIC LIMIT GATING
    while (1) {
      uint64_t h = atomic_load_relaxed(&state[target_node].chunk_queue_head);
      uint64_t t = atomic_load_acquire(&state[target_node].chunk_queue_tail);
      if ((int64_t)(h - t) < current_buffer_limit)
        break;

      NUMA_CHECK_SCANNERS_DONE();

      struct pollfd pfd = {.fd = evfd_chunk_done, .events = POLLIN};
      if (poll(&pfd, 1, -1) > 0) {
        uint64_t v;
        sys_read(evfd_chunk_done, &v, 8);
      }
    }

    // INFINITE EVENT-DRIVEN INGEST GATE
    struct pollfd pfds_gate[2] = {
        {.fd = infd, .events = POLLIN},
        {.fd = evfd_chunk_done, .events = POLLIN}
    };
    int p_res = poll(pfds_gate, 2, -1);
    if (p_res < 0) {
        if (errno != EINTR && errno != EAGAIN) break;
        continue;
    }

    if (pfds_gate[1].revents & POLLIN) {
        uint64_t dummy;
        sys_read(evfd_chunk_done, &dummy, 8);
    }

    NUMA_CHECK_SCANNERS_DONE();

    if (!(pfds_gate[0].revents & (POLLIN | POLLHUP | POLLERR))) {
        continue;
    }

    // PHYSICS FIX: Only execute heavy NUMA lock syscalls if the target actually changed
    if (target_node != last_target && numa_enabled && num_nodes > 1) {
        uint32_t target_phys =
            g_logical_to_phys_map ? g_logical_to_phys_map[target_node] : 0;
        if (target_phys < mask_words * BITS_PER_LONG) {
          memset(nodemask, 0, mask_words * sizeof(unsigned long));
          nodemask[target_phys / BITS_PER_LONG] |=
              (1UL << (target_phys % BITS_PER_LONG));
          syscall(__NR_set_mempolicy, MPOL_BIND, nodemask,
                  mask_words * BITS_PER_LONG);
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
          if (n >= 0) {
            transfer_method = TM_COPY_FILE_RANGE;
          } else {
            n = sendfile(outfd, infd, NULL, chunk_size);
            if (n >= 0) {
              transfer_method = TM_SENDFILE;
            }
          }
        }
        if (n < 0) {
          transfer_method = TM_READ_WRITE;
        }
      }
      if (transfer_method == TM_READ_WRITE && !bounce_buf) {
        bounce_buf = mmap(NULL, chunk_size, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (bounce_buf == MAP_FAILED) {
          bounce_buf = NULL; // Prevent invalid munmap in ingest_done
          free(nodemask);
          builtin_error("forkrun: mmap failed for ingest bounce buffer (OOM)");
          limit_reached_exit = true;
          goto ingest_done;
        }
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
      case TM_READ_WRITE: {
        ssize_t r = read(infd, bounce_buf, chunk_size);
        if (r < 0) {
          if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
             n = -1;
             break;
          }
          n = -1;
          break;
        }
        if (r == 0) {
          n = 0;
          break;
        }

        size_t written = 0;
        bool inner_fatal = false;
        while (written < (size_t)r) {
          ssize_t w = write(outfd, bounce_buf + written, r - written);
          if (w <= 0) {
            if (w < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
              if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct pollfd pfds_out[2] = {
                    {.fd = outfd, .events = POLLOUT},
                    {.fd = evfd_chunk_done, .events = POLLIN}
                };
                int p_out_res = poll(pfds_out, 2, -1);
                if (p_out_res < 0) {
                    if (errno == EINTR || errno == EAGAIN) continue;
                    if (errno == ENOMEM) {
                        usleep(10000); // Wait for memory, do NOT break loop
                        continue;
                    }
                    inner_fatal = true; // Hard unrecoverable error
                    break;
                }
                if (p_out_res > 0 && (pfds_out[1].revents & POLLIN)) {
                  uint64_t dummy;
                  sys_read(evfd_chunk_done, &dummy, 8);
                  NUMA_CHECK_SCANNERS_DONE();
                }
              } else {
                usleep(10);
              }
              continue;
            }
            if (w < 0 && (errno == ENOSPC || errno == ENOMEM)) {
              usleep(10000); // Wait for fallow
              continue;
            }
            inner_fatal = true;
            break;
          }
          written += w;
        }

        if (inner_fatal) {
            n = -1;
            errno = EIO; // Override errno so the outer loop doesn't mistakenly retry and overwrite bounce_buf
        } else {
            n = r;
        }
      } break;
      default:
        break;
      }
    }

    if (n < 0) {
      if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
      if (errno == ENOSPC || errno == ENOMEM) {
        usleep(10000); // Catch ENOSPC on sendfile/copy_file_range
        continue;
      }
      break; // Safe hard exit
    }
    if (n == 0)
      break;

    struct ChunkMeta *meta =
        &g_state->meta_ring[current_major & META_RING_MASK];
    meta->raw_offset = current_offset;
    meta->raw_length = n;
    meta->target_node = target_node;
    meta->major_id = current_major;
    atomic_store_relaxed(&meta->actual_end, 0);

    struct SharedState *t_state = &state[target_node];
    uint64_t q_idx = atomic_load_relaxed(&t_state->chunk_queue_head);
    t_state->chunk_queue[q_idx & META_RING_MASK] = current_major;

    __atomic_store_n(&t_state->chunk_queue_head, q_idx + 1, __ATOMIC_RELEASE);
    __atomic_store_n(&g_state->ingest_publish_idx, current_major + 1,
                     __ATOMIC_RELEASE);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);

    __atomic_fetch_add(&t_state->stats_chunks_assigned, 1, __ATOMIC_RELAXED);

    uint64_t w = atomic_load_relaxed(&t_state->indexer_waiters);
    if (w > 0) {
      sys_write(evfd_indexer_arr[target_node], &w, 8);
    }

    last_target = target_node;
    current_offset += n;
    current_major++;
    total_moved += n;
    bytes_to_current_node += n;

    // TELEMETRY & AUTO-TUNING (Per-chunk evaluation)
    if (!state[0].mode_byte) {
        uint64_t current_global_stolen = 0;
        for (int i = 0; i < num_nodes; i++) {
            current_global_stolen += atomic_load_relaxed(&state[i].stats_chunks_i_stole);
        }

        // S is 1 if any node stole a chunk since the last loop, 0 otherwise.
        uint64_t S = (current_global_stolen > last_global_stolen) ? 1 : 0;
        uint64_t Si = current_global_stolen - last_global_stolen - S;
        last_global_stolen = current_global_stolen;

        // =========================================================================
        // 1. CALCULATE DYNAMIC BOUNDARIES & STEP RESOLUTION (4 -> 16 BASELINE)
        // =========================================================================
        uint64_t total_batches = 0;
        uint64_t total_workers = 0;
        for (uint32_t i = 0; i < (uint32_t)num_nodes; i++) {
            total_batches += atomic_load_relaxed(&state[i].write_idx);
            total_workers += atomic_load_relaxed(&state[i].active_workers);
        }

        uint64_t avg_worker_cnt = total_workers / num_nodes;
        if (avg_worker_cnt < 1) avg_worker_cnt = 1;

        uint32_t min_buf = 4; // Baseline floor

        if (total_batches > 0) {
            uint64_t num = current_offset * avg_worker_cnt;
            uint64_t den = chunk_size * total_batches * 2;
            if (den > 0) {
                uint64_t dyn_min = num / den;
                if (dyn_min < 4) dyn_min = 4;
                min_buf = (uint32_t)dyn_min;
            }
        }

        uint32_t step = min_buf / 8;
        if (step < 1) step = 1;

        uint32_t bound_a = 4 * min_buf;
        uint32_t bound_b = min_buf + (12 * step);
        uint32_t max_buf = (bound_a < bound_b) ? bound_a : bound_b;
        if (max_buf > 128) max_buf = 128; // Safely absorb smaller 64KB metadata entries

        // Instantaneous safety clamp to keep current_buffer_limit in-bounds during transition
        if (current_buffer_limit < min_buf) {
            current_buffer_limit = min_buf;
            atomic_store_relaxed(&state[0].chunk_buffer_limit, current_buffer_limit);
        } else if (current_buffer_limit > max_buf) {
            current_buffer_limit = max_buf;
            atomic_store_relaxed(&state[0].chunk_buffer_limit, current_buffer_limit);
        }

        // Dynamic Stealing Threshold Scaling (Born-Local Preservation)
        uint32_t scale_factor = (min_buf > 4) ? min_buf : 4;
        for (uint32_t n = 0; n < (uint32_t)num_nodes; n++) {
            for (uint32_t i = 0; i < (uint32_t)num_nodes; i++) {
                uint32_t base = state[n].base_steal_threshold[i];
                // Dynamic formula: (max(4, min_buf) * base_threshold) / 4
                uint32_t dynamic_thresh = (scale_factor * base) / 4;
                if (dynamic_thresh < 1) dynamic_thresh = 1;
                if (dynamic_thresh > 255) dynamic_thresh = 255; // CRITICAL FIX: Prevent uint8_t wrap-around
                // Store with relaxed release semantics
                __atomic_store_n(&state[n].steal_threshold[i], (uint8_t)dynamic_thresh, __ATOMIC_RELAXED);
            }
        }

        // =========================================================================
        // 2. DYNAMICALLY ALIGNED IIR FILTER UPDATES (INVARIANTS PRESERVED)
        // =========================================================================
        if (current_buffer_limit >= max_buf) {
            // Dynamic Ceiling: Steady state max is strictly 75. Physically impossible to exceed 75.
            I_meter = ((I_meter * 31) + (75 * S)) >> 5;
        } else {
            // Dynamic Floor: If at floor, inject 15 to lock steady state min to 15. Physically impossible to drop below 15.
            uint64_t add0 = (current_buffer_limit <= min_buf) ? 15 : 0;

            uint64_t Si_clamped = (Si > 10) ? 10 : Si;
            uint64_t add1 = (1ULL << (Si_clamped + 1)) - 1;

            I_meter = ((I_meter * 31) + add0 * (1 - S) + S * (1000ULL + ((1000ULL * add1) >> Si_clamped))) >> 5;
        }

        // PHYSICS FIX: Is the buffer actually the bottleneck?
        // Check if the node we just wrote to is actually at/near the current buffer capacity.
        uint64_t current_tail = atomic_load_relaxed(&state[last_target].chunk_queue_tail);
        uint64_t current_depth = (current_major) - current_tail; // current_major was just incremented

        // We consider it "saturated" if the queue depth is at least (limit - 1)
        bool is_buffer_saturated = (current_depth >= current_buffer_limit - 1);

        // =========================================================================
        // 3. APPLY ADJUSTMENTS
        // =========================================================================
        if (I_meter < 15 && current_buffer_limit > min_buf) {
            if (current_buffer_limit >= min_buf + step) {
                current_buffer_limit -= step;
            } else {
                current_buffer_limit = min_buf;
            }
            atomic_store_relaxed(&state[0].chunk_buffer_limit, current_buffer_limit);
            I_meter = 50; // Reset
        } else if (I_meter > 75 && current_buffer_limit < max_buf && is_buffer_saturated) {
            if (current_buffer_limit + step <= max_buf) {
                current_buffer_limit += step;
            } else {
                current_buffer_limit = max_buf;
            }
            atomic_store_relaxed(&state[0].chunk_buffer_limit, current_buffer_limit);
            I_meter = 50; // Reset
        }
    }
  }

ingest_done:
  if (bounce_buf)
    munmap(bounce_buf, chunk_size);
  if (numa_enabled)
    syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);
  free(nodemask);
#undef NUMA_CHECK_SCANNERS_DONE

  if (limit_reached_exit) {
    __atomic_store_n(&g_state->ingest_eof_idx, current_major, __ATOMIC_RELEASE);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    uint64_t v = 999999;
    sys_write(evfd_ingest_eof, &v, 8);
    return EXECUTION_SUCCESS;
  }

  int target_node_eof = last_target == -1 ? 0 : (last_target + 1) % num_nodes;
  while (1) {
    uint64_t h = atomic_load_relaxed(&state[target_node_eof].chunk_queue_head);
    uint64_t t = atomic_load_acquire(&state[target_node_eof].chunk_queue_tail);
    if ((int64_t)(h - t) < 4)
      break;
    struct pollfd pfd = {.fd = evfd_chunk_done, .events = POLLIN};
    if (poll(&pfd, 1, 10) > 0) {
      uint64_t v;
      sys_read(evfd_chunk_done, &v, 8);
    }
    // Add emergency check to ensure we don't stall in flush at EOF if SIGPIPE happened
    if (atomic_load_relaxed(&state[0].emergency_abort)) break;
  }

  struct ChunkMeta *meta_eof = &g_state->meta_ring[current_major & META_RING_MASK];
  meta_eof->raw_offset = current_offset;
  meta_eof->raw_length = 0;
  meta_eof->target_node = target_node_eof;
  meta_eof->major_id = current_major;
  atomic_store_relaxed(&meta_eof->actual_end, 0);

  struct SharedState *t_state_eof = &state[target_node_eof];
  uint64_t q_idx_eof = atomic_load_relaxed(&t_state_eof->chunk_queue_head);
  t_state_eof->chunk_queue[q_idx_eof & META_RING_MASK] = current_major;

  __atomic_store_n(&t_state_eof->chunk_queue_head, q_idx_eof + 1, __ATOMIC_RELEASE);
  __atomic_store_n(&g_state->ingest_publish_idx, current_major + 1,
                   __ATOMIC_RELEASE);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);

  __atomic_fetch_add(&t_state_eof->stats_chunks_assigned, 1, __ATOMIC_RELAXED);

  uint64_t w_eof = atomic_load_relaxed(&t_state_eof->indexer_waiters);
  if (w_eof > 0) {
    uint64_t v = w_eof;
    sys_write(evfd_indexer_arr[target_node_eof], &v, 8);
  }
  current_major++;

  __atomic_store_n(&g_state->ingest_eof_idx, current_major, __ATOMIC_RELEASE);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);
  uint64_t v_eof = 999999;
  sys_write(evfd_ingest_eof, &v_eof, 8);
  return EXECUTION_SUCCESS;
}


// NUMA Indexer: One indexer is pinned to each NUMA socket. It reads the raw
// chunks written by ingest and coordinates the metadata boundary alignments
// (major/minor IDs). It acts as the bridge between the single global memfd and
// the per-socket lock-free rings.
static int ring_indexer_numa_main(int argc, char **argv) {
  if (argc < 3)
    return EXECUTION_FAILURE;
  int memfd = atoi(argv[1]);
  int my_node_id = atoi(argv[2]);

  int phys_node = g_logical_to_phys_map ? g_logical_to_phys_map[my_node_id] : 0;
  if (pin_to_numa_node(phys_node) != 0 && g_debug) {
    fprintf(stderr,
            "forkrun [DEBUG] Failed to pin indexer %d to phys node %d\n",
            my_node_id, phys_node);
  }

  struct SharedState *t_state = &state[my_node_id];
  uint64_t my_idx = 0;
  char tail_buf[65536];
  int spin = 0;
  bool byte_mode = t_state->mode_byte;

  while (1) {
    if (atomic_load_relaxed(&state[0].emergency_abort)) {
      return EXECUTION_FAILURE;
    }
    while (atomic_load_acquire(&t_state->chunk_queue_head) <= my_idx) {
      if (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0) {
        if (atomic_load_acquire(&t_state->chunk_queue_head) <= my_idx)
          return EXECUTION_SUCCESS;
      }
      if (spin < 100) {
        cpu_relax();
        spin++;
        continue;
      }

      __atomic_fetch_add(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST);
      if (atomic_load_acquire(&t_state->chunk_queue_head) > my_idx) {
        __atomic_fetch_sub(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST);
        break;
      }
      struct pollfd pfds[2] = {
          {.fd = evfd_indexer_arr[my_node_id], .events = POLLIN},
          {.fd = evfd_ingest_eof, .events = POLLIN}};
      poll(pfds, 2, -1);

      if (atomic_load_relaxed(&state[0].emergency_abort)) {
        __atomic_fetch_sub(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST);
        return EXECUTION_FAILURE;
      }

      bool data_fired = (pfds[0].revents & POLLIN) != 0;
      bool eof_fired = (pfds[1].revents & POLLIN) != 0;

      // RULE: 1. Check local work. consume & loop
      if (data_fired) {
        uint64_t v;
        sys_read(evfd_indexer_arr[my_node_id], &v, 8);
      }
      // RULE: 3. EOF evfd. Handled by outer loop Condition 1 check.
      else if (eof_fired) {
          // Do nothing. Outer loop checks g_state->ingest_eof_idx != ~(uint64_t)0
      }
      __atomic_fetch_sub(&t_state->indexer_waiters, 1, __ATOMIC_SEQ_CST);
      spin = 0;
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
        uint64_t window_size =
            (search_end - meta->raw_offset > sizeof(tail_buf))
                ? sizeof(tail_buf)
                : (search_end - meta->raw_offset);
        uint64_t window_start = search_end - window_size;
        ssize_t n;
        do {
          n = pread(memfd, tail_buf, window_size, window_start);
        } while (n < 0 && errno == EINTR);
        if (n > 0) {
          char *nl = memrchr(tail_buf, t_state->cfg_delim, n);
          if (nl) {
            actual_end = window_start + (nl - tail_buf) + 1;
            break;
          }
        } else if (n < 0 && errno == EAGAIN)
          continue;
        else
          break;
        search_end = window_start;
      }
      if (search_end <= meta->raw_offset)
        actual_end = meta->raw_offset;
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
#define UNIFIED_ADAPTIVE_COMMIT(force)                                         \
  do {                                                                         \
    if (local_scan_idx > local_write_idx) {                                    \
      uint64_t W_curr = atomic_load_relaxed(&local_state->active_workers);     \
      if (W_curr < 1)                                                          \
        W_curr = 1;                                                            \
      if (force || atomic_load_relaxed(&local_state->active_waiters) > 0) {    \
        atomic_store_release(&local_state->write_idx, local_scan_idx);         \
        local_write_idx = local_scan_idx;                                      \
        __atomic_thread_fence(__ATOMIC_SEQ_CST);                               \
        uint32_t aw = atomic_load_acquire(&local_state->active_waiters);       \
        if (aw > 0) {                                                          \
          uint64_t v = aw;                                                     \
          sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8);           \
        }                                                                      \
      } else {                                                                 \
        uint64_t r_idx = atomic_load_relaxed(&local_state->read_idx);          \
        uint64_t pending =                                                     \
            (local_scan_idx > r_idx) ? (local_scan_idx - r_idx) : 0;           \
        uint64_t current_buffer = local_scan_idx - local_write_idx;            \
        uint64_t target_buffer = 0;                                            \
        if (pending >= 10 * W_curr)                                            \
          target_buffer = (W_curr << 2);                                       \
        else if (pending > (W_curr << 1)) {                                    \
          uint64_t linear = pending >> 1;                                      \
          uint64_t intermediate =                                              \
              (linear < current_buffer) ? linear : current_buffer;             \
          if (intermediate > W_curr)                                           \
            target_buffer = intermediate - W_curr;                             \
        }                                                                      \
        uint64_t target_w = (local_scan_idx > target_buffer)                   \
                                ? (local_scan_idx - target_buffer)             \
                                : 0;                                           \
        if (target_w > local_write_idx) {                                      \
          atomic_store_release(&local_state->write_idx, target_w);             \
          local_write_idx = target_w;                                          \
          __atomic_thread_fence(__ATOMIC_SEQ_CST);                             \
          uint32_t aw = atomic_load_acquire(&local_state->active_waiters);     \
          if (aw > 0) {                                                        \
            uint64_t v = aw;                                                   \
            sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8);         \
          }                                                                    \
        }                                                                      \
      }                                                                        \
    }                                                                          \
    if (force) {                                                               \
      uint32_t aw = atomic_load_acquire(&local_state->active_waiters);         \
      if (aw > 0 &&                                                            \
          local_write_idx > atomic_load_relaxed(&local_state->read_idx)) {     \
        uint64_t v = aw;                                                       \
        sys_write(evfd_data_arr[is_numa ? my_node_id : 0], &v, 8);             \
      }                                                                        \
    }                                                                          \
  } while (0)

/*
 * WRAP-AROUND SHIELD LOGIC:
 * Calculates physical wrap-around distance. Yield the scanner if:
 * 1. Slot-based wrap-around shield boundary is hit (applies to BOTH UMA and NUMA)
 * 2. Chunk-based memory shield boundary is hit (applies ONLY to NUMA)
 */
#define UNIFIED_SCANNER_FLUSH(_is_last, _maj_id, _minor_val,                   \
                              _batch_end_offset, _out_skipped)                 \
  do {                                                                         \
    _out_skipped = false;                                                      \
    if (__builtin_expect(g_state->is_resume_mode, 0)) {                        \
        uint64_t _s_byte = batch_start;                                        \
        uint64_t _e_byte = _batch_end_offset;                                  \
        if (_s_byte >= g_state->resume_horizon) {                              \
            for (uint32_t _i = 0; _i < g_state->resume_jagged_count; _i++) {   \
                if (_s_byte >= g_state->resume_jagged[_i].s && _e_byte <= g_state->resume_jagged[_i].e) { \
                    _out_skipped = true; break;                                \
                }                                                              \
            }                                                                  \
        } else if (_e_byte <= g_state->resume_horizon) {                       \
            _out_skipped = true;                                               \
        }                                                                      \
        if (_out_skipped) break;                                               \
    }                                                                          \
    while (1) {                                                                \
      if (atomic_load_relaxed(&state[0].emergency_abort)) goto unified_scanner_eof; \
      uint64_t limit;                                                          \
      uint64_t uma_max_ahead = W_max_val * 64;                                 \
      if (uma_max_ahead < 1024)                                                \
        uma_max_ahead = 1024;                                                  \
      if (!is_numa && atomic_load_relaxed(&local_state->fallow_active)) {      \
        uint64_t r = atomic_load_acquire(&local_state->read_idx);              \
        uint64_t m = atomic_load_acquire(&local_state->min_idx);               \
        limit = (r > m + uma_max_ahead) ? r - uma_max_ahead : m;               \
      } else {                                                                 \
        limit = atomic_load_acquire(&local_state->read_idx);                   \
      }                                                                        \
      uint64_t max_ahead = is_numa ? (RING_SIZE / 2) : uma_max_ahead;          \
                                                                               \
      bool limit_lines = (local_scan_idx > limit) &&                           \
                         ((local_scan_idx - limit) >= max_ahead);              \
                                                                               \
      uint32_t dyn_limit = atomic_load_relaxed(&state[0].chunk_buffer_limit);  \
      if (dyn_limit < 4) dyn_limit = 4;                                        \
      if (dyn_limit > 16) dyn_limit = 16;                                      \
      uint32_t scanner_shield = dyn_limit - 1;                                 \
                                                                               \
      bool limit_chunks = is_numa && (cb_head >= scanner_shield) &&            \
                      (limit < chunk_bounds[(cb_head - scanner_shield) & 15]); \
                                                                               \
      if (!limit_lines && !limit_chunks)                                       \
        break;                                                                 \
      if (atomic_load_relaxed(&local_state->active_workers) == 0)              \
        break;                                                                 \
      UNIFIED_ADAPTIVE_COMMIT(true);                                           \
      if (fd_spawn >= 0 && W < W_max_val) {                                    \
        uint64_t _r_idx = atomic_load_relaxed(&local_state->read_idx);         \
        uint64_t backlog =                                                     \
            (local_scan_idx > _r_idx) ? local_scan_idx - _r_idx : 0;           \
        uint64_t W_target = (backlog > W_max_val) ? W_max_val : backlog;       \
        if (W_target > W) {                                                    \
          uint64_t needed = W_target - W;                                      \
          char sbuf[64];                                                       \
          int slen;                                                            \
          if (is_numa)                                                         \
            slen =                                                             \
                snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, needed);  \
          else                                                                 \
            slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", needed);              \
          if (slen > 0)                                                        \
            robust_pipe_write(fd_spawn, sbuf, slen);                           \
          W += needed;                                                         \
        }                                                                      \
      }                                                                        \
      usleep(100);                                                             \
    }                                                                          \
    uint64_t pk = (uint64_t)batch_start;                                       \
    if (is_numa) {                                                             \
      local_state->offset_ring[local_scan_idx & RING_MASK] = pk;               \
      local_state->end_ring[local_scan_idx & RING_MASK] = (_batch_end_offset); \
      local_state->major_ring[local_scan_idx & RING_MASK] = (_maj_id);         \
      local_state->minor_ring[local_scan_idx & RING_MASK] =                    \
          (_minor_val) | ((_is_last) ? FLAG_MAJOR_EOF : 0);                    \
    } else {                                                                   \
      local_state->offset_ring[local_scan_idx & RING_MASK] = pk;               \
      local_state->end_ring[local_scan_idx & RING_MASK] = (_batch_end_offset); \
    }                                                                          \
    local_scan_idx++;                                                          \
    UNIFIED_ADAPTIVE_COMMIT(false);                                            \
  } while (0)

// v3.3: ADAPTIVE_FLOW_CONTROL still runs the phase==1 geometric ramp for L and
// worker spawning, but only when the pre-flight scan didn't complete (e.g.
// byte_mode, exact_lines, or fixed_batch). In the common case phase is already
// 2 when the scanner loop starts so this macro reduces to the PID steady-state
// block only. ring_pow2 recording is removed — workers always claim 1 slot.
#define ADAPTIVE_FLOW_CONTROL(state_ptr, is_stalled, _node_id_arg)             \
  do {                                                                         \
    batch_counter++;                                                           \
    batches_since_calc++;                                                      \
    uint64_t _tc = W * 4;                                                      \
    if (_tc < 4)                                                               \
      _tc = 4;                                                                 \
    if (!fixed_batch && !byte_mode) {                                          \
      if (phase == 0) {                                                        \
        if (batch_counter >= _tc) {                                            \
          phase = 1;                                                           \
          batch_counter = 0;                                                   \
        }                                                                      \
      } else if (phase == 1) {                                                 \
        if (is_stalled)                                                        \
          phase = 2;                                                           \
        else if (batch_counter >= _tc) {                                       \
          L *= 2;                                                              \
          if (L >= Lmax) {                                                     \
            L = Lmax;                                                          \
            phase = 2;                                                         \
          }                                                                    \
          if (W < W_max_val && !fixed_workers) {                               \
            uint64_t _l_log = fast_log2(L);                                    \
            uint64_t _den = X_const * (L2 + _l_log);                           \
            if (_den == 0)                                                     \
              _den = 1;                                                        \
            uint64_t _n_spawn = (6 * (W_max_val - W) * L2) / _den;             \
            if (_n_spawn < 1)                                                  \
              _n_spawn = 1;                                                    \
            if (_n_spawn > (W_max_val - W))                                    \
              _n_spawn = W_max_val - W;                                        \
            if (fd_spawn >= 0) {                                               \
              char _sbuf[64];                                                  \
              int _slen;                                                       \
              if ((int)(_node_id_arg) >= 0)                                    \
                _slen = snprintf(_sbuf, sizeof(_sbuf), "%d:%lu\n",             \
                                 (int)(_node_id_arg), _n_spawn);               \
              else                                                             \
                _slen = snprintf(_sbuf, sizeof(_sbuf), "%lu\n", _n_spawn);     \
              if (_slen > 0)                                                   \
                robust_pipe_write(fd_spawn, _sbuf, _slen);                     \
              W += _n_spawn;                                                   \
            }                                                                  \
          }                                                                    \
          batch_counter = 0;                                                   \
        }                                                                      \
      }                                                                        \
    }                                                                          \
    uint64_t _now_us = get_us_time();                                          \
    if (_now_us - last_calc_us > 5000 || batches_since_calc >= W) {            \
      uint64_t _d_in = local_write_idx - last_calc_write;                      \
      uint64_t _r_con =                                                        \
          atomic_load_relaxed(&(state_ptr)->total_lines_consumed);             \
      uint64_t _d_out = _r_con - last_calc_read;                               \
      last_calc_write = local_write_idx;                                       \
      last_calc_read = _r_con;                                                 \
      last_calc_us = _now_us;                                                  \
      batches_since_calc = 0;                                                  \
      if (!fixed_workers && W < W_max_val) {                                   \
        uint64_t _backlog =                                                    \
            local_scan_idx - atomic_load_relaxed(&(state_ptr)->read_idx);      \
        bool _no_starve =                                                      \
            (atomic_load_relaxed(&(state_ptr)->active_waiters) == 0);          \
        bool _spawn = false;                                                   \
        if (fixed_batch || byte_mode) {                                        \
          if ((_backlog > W || byte_mode) && _no_starve)                       \
            _spawn = true;                                                     \
        } else {                                                               \
          if (_d_out > 0) {                                                    \
            uint64_t _rate = _d_out / W;                                       \
            if (_rate == 0)                                                    \
              _rate = 1;                                                       \
            if ((_d_in / _rate) > W)                                           \
              _spawn = true;                                                   \
          } else if (_backlog > (W * 4) && _no_starve) {                       \
            _spawn = true;                                                     \
          }                                                                    \
        }                                                                      \
        if (_spawn && phase != 1) {                                            \
          uint64_t _grow = fixed_batch ? 1 : ((W + 1) / 2);                    \
          if (byte_mode)                                                       \
            _grow = W_max_val - W;                                             \
          if (W + _grow > W_max_val)                                           \
            _grow = W_max_val - W;                                             \
          if (_grow > 0 && fd_spawn >= 0) {                                    \
            char _sbuf[64];                                                    \
            int _slen;                                                         \
            if ((int)(_node_id_arg) >= 0)                                      \
              _slen = snprintf(_sbuf, sizeof(_sbuf), "%d:%lu\n",               \
                               (int)(_node_id_arg), _grow);                    \
            else                                                               \
              _slen = snprintf(_sbuf, sizeof(_sbuf), "%lu\n", _grow);          \
            if (_slen > 0)                                                     \
              robust_pipe_write(fd_spawn, _sbuf, _slen);                       \
            W += _grow;                                                        \
          }                                                                    \
        }                                                                      \
      }                                                                        \
      if (!fixed_batch && !byte_mode && phase == 2) {                          \
        int64_t _pending_slots =                                               \
            (int64_t)local_write_idx -                                         \
            (int64_t)atomic_load_relaxed(&(state_ptr)->read_idx);              \
        if (_pending_slots < 0)                                                \
          _pending_slots = 0;                                                  \
        int64_t _bl = _pending_slots * (int64_t)L;                             \
        uint64_t _l_target = (uint64_t)_bl / W;                                \
        if (_l_target > Lmax)                                                  \
          _l_target = Lmax;                                                    \
        if (_l_target < 1)                                                     \
          _l_target = 1;                                                       \
        if (_l_target > L) {                                                   \
          L = _l_target;                                                       \
        } else if (_l_target < L &&                                            \
                   starve_meter >= (W + DAMPING_OFFSET - 3) &&                 \
                   stall_meter >= (W + DAMPING_OFFSET - 3)) {                  \
          L = (L + _l_target) / 2;                                             \
          if (L < 1)                                                           \
            L = 1;                                                             \
          starve_meter = 0;                                                    \
          stall_meter = 0;                                                     \
        }                                                                      \
      }                                                                        \
    }                                                                          \
  } while (0)

// The Core Unified Scanner Function: This is the "PID-controlled source" of the
// river. It uses SIMD instructions to find record delimiters at memory
// bandwidth. It employs a 3-phase flow controller (Warmup -> Geometric Ramp ->
// PID Steady-state) to dynamically adapt the batch size based on input stall
// rate and worker starvation. It handles both legacy flat pipelines (UMA) and
// deep NUMA topologies.
static inline __attribute__((always_inline)) int
core_scanner_loop(int fd_or_memfd, int my_node_id, int fd_spawn, int num_nodes, const bool is_numa) {
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
  bool exact_lines = local_state->exact_lines;
  char delim = (char)local_state->cfg_delim;

  uint64_t W2 = fast_log2(W_max_val);
  uint64_t L2 = fast_log2(Lmax);
  uint64_t X_const = fast_log2(W2 + L2) * W2;
  if (X_const == 0)
    X_const = 1;

  uint64_t local_scan_idx = 0;
  uint64_t local_write_idx = 0;

  size_t chunk_sz = get_optimal_chunk_size();

  // PHYSICS FIX: Align flat-mode buffer exactly to byte sizes to prevent internal shifting.
  if (byte_mode && L > 0) {
    uint64_t mult = (chunk_sz + L - 1) / L;
    chunk_sz = mult * L;
  }

  // PHYSICS FIX: mmap completely sidesteps bash_malloc intercepts!
  char *buf = mmap(NULL, chunk_sz, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (buf == MAP_FAILED)
    return EXECUTION_FAILURE;

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

  uint64_t chunk_bounds[16] = {0};
  uint32_t cb_head = 0;

  atomic_store_relaxed(&local_state->write_idx, 0);
  atomic_store_relaxed(&local_state->read_idx, 0);
  if (!is_numa)
    atomic_store_relaxed(&local_state->tail_idx, 0);

  // ---- NEW: Pin scanner ----
  if (g_logical_to_phys_map) {
    if (is_numa && (uint32_t)my_node_id < global_num_nodes) {
      pin_to_numa_node(g_logical_to_phys_map[my_node_id]);
    } else if (!is_numa && g_explicit_pinning) {
      pin_to_numa_node(g_logical_to_phys_map[0]);
    }
  }
  // --------------------------

  if (fd_spawn >= 0 && W > 0) {
    char sbuf[64];
    int slen;
    if (is_numa)
      slen = snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, W);
    else
      slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", W);
    if (slen > 0)
      robust_pipe_write(fd_spawn, sbuf, slen);
  }

  bool experienced_stall = false;
  uint64_t pending_lines = 0;

  // -----------------------------------------------------------------
  // PHASE 1 (v3.3): PRE-FLIGHT POPCOUNT — Latency Hiding
  // -----------------------------------------------------------------
  // During the Bash fork latency (workers spinning up), do a pure
  // delimiter popcount at AVX2 speed to learn the total line count.
  // This lets us compute the optimal L = total_lines / W before we
  // write a single ring slot, eliminating the geometric ramp-up
  // entirely and letting workers always claim exactly 1 batch.
  //
  // We also simulate the original control-theory spawning formula so
  // that Bash receives fd_spawn requests at the same smoothly-
  // decelerating rate as before — no fork storms.
  //
  // Fallback: skip if exact_lines, byte_mode, or fixed_batch are set,
  // or if the first worker arrives before we finish scanning.
  if (!exact_lines && !byte_mode && !fixed_batch) {
    uint64_t pre_lines      = 0;
    uint64_t pre_offset     = buf_base_offset;
    uint64_t target_pre     = W_max_val * Lmax;

    // Physical byte ceiling: stop scanning once we have covered enough bytes
    // to fill W_max batches at the byte-based maximum batch size.  Two limits
    // are considered and the tighter one wins:
    //   • ARG_MAX / max_bytes limit  →  BytesMax * W_max_val
    //   • NUMA chunk-size limit      →  chunk_sz  * W_max_val  (NUMA only)
    // Initialise to UINT64_MAX so the check is a no-op when neither applies.
    uint64_t target_pre_bytes = ~(uint64_t)0;
    if (BytesMax > 0) {
        target_pre_bytes = BytesMax * W_max_val;
    }
    if (is_numa) {
        uint64_t numa_byte_max = chunk_sz * W_max_val;
        if (numa_byte_max < target_pre_bytes) {
            target_pre_bytes = numa_byte_max;
        }
    }

    uint64_t sim_W          = W;
    uint64_t sim_L          = (L > 0) ? L : 1;
    uint64_t sim_lines_base = 0; // lines_accum at start of current L level
    bool hit_real_eof       = false;

    while (pre_lines < target_pre && (pre_offset - buf_base_offset) < target_pre_bytes) {
        // EMERGENCY BYPASS FIX: Prevent infinite hang if downstream pipe breaks
        if (atomic_load_relaxed(&state[0].emergency_abort)) {
            goto unified_scanner_eof;
        }

      // BAIL: first worker arrived — stop scanning and let the ring fill
      if (atomic_load_relaxed(&local_state->active_waiters) > 0)
        break;

      // PHYSICS FIX: Correct EOF detection for NUMA vs UMA topologies
      bool ingest_done;
      if (is_numa) {
          ingest_done = (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0);
      } else {
          ingest_done = atomic_load_acquire(&local_state->ingest_complete);
      }

      ssize_t n;
      do {
        n = pread(fd_or_memfd, buf, chunk_sz, (off_t)pre_offset);
      } while (n < 0 && errno == EINTR);

      if (n < 0) {
        break; // Hard error (e.g. EIO, EBADF) — abort pre-flight safely
      } else if (n > 0) {
        pre_lines   += fast_count_delim(buf, buf + (size_t)n, delim);
        pre_offset  += (uint64_t)n;

        // Simulate the geometric spawn curve using the exact same formula
        // as ADAPTIVE_FLOW_CONTROL phase==1, translated from batches to lines.
        while (sim_W < W_max_val && sim_L < Lmax && !fixed_workers) {
          uint64_t _tc          = sim_W * 4;
          if (_tc < 4) _tc      = 4;
          uint64_t lines_needed = _tc * sim_L;

          if (pre_lines - sim_lines_base >= lines_needed) {
            sim_lines_base += lines_needed;
            sim_L          *= 2;
            if (sim_L >= Lmax)
              sim_L = Lmax;

            // Exact reuse of original spawn formula
            uint64_t _l_log  = fast_log2(sim_L);
            uint64_t _den    = X_const * (L2 + _l_log);
            if (_den == 0) _den = 1;
            uint64_t _n_spawn = (6 * (W_max_val - sim_W) * L2) / _den;
            if (_n_spawn < 1)              _n_spawn = 1;
            if (_n_spawn > W_max_val - sim_W) _n_spawn = W_max_val - sim_W;

            if (fd_spawn >= 0) {
              char _sbuf[64];
              int  _slen;
              if (is_numa)
                _slen = snprintf(_sbuf, sizeof(_sbuf), "%d:%lu\n",
                                 my_node_id, _n_spawn);
              else
                _slen = snprintf(_sbuf, sizeof(_sbuf), "%lu\n", _n_spawn);
              if (_slen > 0)
                robust_pipe_write(fd_spawn, _sbuf, _slen);
            }
            sim_W += _n_spawn;
          } else {
            break; // not enough lines yet for the next geometric step
          }
        }
      } else if (n == 0 && ingest_done) {
        hit_real_eof = true;
        break; // reached real EOF — pre_lines is the exact total line count
      } else {
        usleep(100);
      }
    }

    // Transition (v3.3): Commit simulation results to live execution state.
    W = (sim_W > 0) ? sim_W : 1;

    if (pre_lines >= target_pre || hit_real_eof) {
      // CASE A: Pre-flight completed OR reached real EOF of a small/medium file.
      // In both cases pre_lines is an exact (or sufficient) total line count,
      // so we can compute the globally optimal L and jump straight to PID.
      if (pre_lines > 0 && W > 0) {
        uint64_t optimal_L = pre_lines / W;
        L = (optimal_L > 0) ? (1ULL << fast_log2(optimal_L)) : 1;
      } else {
        L = 1;
      }
      phase = 2; // skip geometric ramp-up entirely
    } else {
      // CASE B: Pre-flight was cut short before the line target was reached.
      // This happens either because a worker arrived early, or because we hit
      // the physical byte/chunk ceiling (target_pre_bytes) before accumulating
      // W_max*Lmax lines — i.e. the data is wide-lined and each batch is
      // already byte-limited rather than line-limited.
      // In both cases we don't have enough line-count data to compute the
      // globally optimal L, so hot-swap sim_L (the batch size the simulation
      // had reached) into the live scanner state and resume the geometric
      // doubling phase from there.
      // ADAPTIVE_FLOW_CONTROL will continue doubling L → Lmax at the same
      // exponential rate as a normal ramp-up, while workers remain on the
      // claim_count=1 fast path, completely oblivious to the phase.
      L = sim_L;
      phase = 1; // resume geometric ramp-up from the simulation's checkpoint
    }

    if (L > Lmax) L = Lmax;
    if (L < 1)    L = 1;
  }
  // -----------------------------------------------------------------

  int status = 0;
  bool force_refill = false;

  while (1) {
    // EMERGENCY BYPASS: If someone pulled the fire alarm, kill the Scanner instantly.
    if (atomic_load_relaxed(&state[0].emergency_abort)) {
        goto unified_scanner_eof;
    }

    uint64_t chunk_end = ~(uint64_t)0;
    uint64_t current_p_offset;
    struct ChunkMeta *meta = NULL;
    uint32_t minor_idx = 0;
    bool chunk_eof_flushed = false;

    if (is_numa) {
      int steal_target = my_node_id;
      struct SharedState *t_state = &state[my_node_id];

      uint64_t my_tail = atomic_load_relaxed(&t_state->chunk_queue_tail);
      uint64_t my_head = atomic_load_acquire(&t_state->chunk_ready_head);
      bool global_eof =
          (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0);

      if (my_tail >= my_head) {
        bool workers_starved = (atomic_load_relaxed(&local_state->read_idx) ==
                                atomic_load_relaxed(&local_state->write_idx));
        bool local_exhausted =
            (my_tail >= atomic_load_acquire(&t_state->chunk_queue_head));

        bool extreme_starvation =
            (global_eof && local_exhausted && workers_starved);

        int max_bl = 0, best_ready_bl = 0, ready_target = -1,
            fallback_target = -1;
        bool any_valid_backlog = false;

        for (int i = 0; i < num_nodes; i++) {
          if (i == my_node_id)
            continue;

          uint64_t h = atomic_load_acquire(&state[i].chunk_ready_head);
          uint64_t t = atomic_load_relaxed(&state[i].chunk_queue_tail);

          if (h > t) {
            int bl = (int)(h - t);
            int required_bl =
                extreme_starvation ? 1 : local_state->steal_threshold[i];

            if (bl >= required_bl) {
              any_valid_backlog = true;
              if (bl > max_bl) {
                max_bl = bl;
                fallback_target = i;
              }

              bool ready = true;
              if (atomic_load_acquire(&state[i].write_idx) == 0)
                ready = false;
              if (ready && bl > best_ready_bl) {
                best_ready_bl = bl;
                ready_target = i;
              }
            }
          }
        }

        if (!any_valid_backlog) {
          // --- PHYSICS FIX: Instant NUMA Tear-down ---
          if (global_eof && local_exhausted) {
            goto unified_scanner_eof;
          }
        } else {
          if (ready_target != -1)
            steal_target = ready_target;
          else if (fallback_target != -1)
            steal_target = fallback_target;
        }

        // FIXED NUMA LATENCY BUBBLE: Don't claim an empty local queue
        // If completely starved, yield to the OS to prevent 100% CPU spinning.
        if (steal_target == my_node_id) {
          int _starve_spin = 0;
          int max_spin = global_eof ? 10 : 1000;
          // Spin briefly to handle micro-stalls without OS context-switching
          while (atomic_load_acquire(&t_state->chunk_ready_head) <= my_tail &&
                 _starve_spin < max_spin) {
            cpu_relax();
            _starve_spin++;
          }

          // If STILL starved after spinning, yield the CPU
          if (atomic_load_acquire(&t_state->chunk_ready_head) <= my_tail) {
            __atomic_fetch_add(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);

            // Double check to prevent race conditions before sleeping
            if (atomic_load_acquire(&t_state->chunk_ready_head) <= my_tail) {
              struct pollfd pfds[2] = {
                  {.fd = evfd_meta_arr[my_node_id], .events = POLLIN},
                  {.fd = evfd_ingest_eof, .events = POLLIN}};
              poll(pfds, 2, -1);
              if (atomic_load_relaxed(&state[0].emergency_abort)) {
                  __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
                  goto unified_scanner_eof;
              }
              if (pfds[0].revents & POLLIN) {
                uint64_t v;
                sys_read(evfd_meta_arr[my_node_id], &v, 8);
              }
            }
            __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
          }
          continue;
        }

        t_state = &state[steal_target];
      }

      uint64_t claim_idx =
          __atomic_fetch_add(&t_state->chunk_queue_tail, 1, __ATOMIC_SEQ_CST);

      uint64_t _one = 1;
      sys_write(evfd_chunk_done, &_one, 8);

      int meta_spin = 0;
      int max_meta_spin = global_eof ? 10 : 10000;
      while (atomic_load_acquire(&t_state->chunk_ready_head) <= claim_idx) {
        if (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0) {
          if (atomic_load_acquire(&t_state->chunk_queue_head) <= claim_idx)
            break;
        }

        if (atomic_load_acquire(&t_state->chunk_queue_head) <= claim_idx) {
          experienced_stall = true;
        }

        if (meta_spin < max_meta_spin) {
          cpu_relax();
          meta_spin++;
        } else {
          __atomic_fetch_add(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
          if (atomic_load_acquire(&t_state->chunk_ready_head) > claim_idx) {
            __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
            break;
          }
          struct pollfd pfds[2] = {
              {.fd = evfd_meta_arr[steal_target], .events = POLLIN},
              {.fd = evfd_ingest_eof, .events = POLLIN}};
          poll(pfds, 2, -1);
          if (atomic_load_relaxed(&state[0].emergency_abort)) {
              __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
              goto unified_scanner_eof;
          }
          if (pfds[0].revents & POLLIN) {
            uint64_t v;
            sys_read(evfd_meta_arr[steal_target], &v, 8);
          }
          __atomic_fetch_sub(&t_state->meta_waiters, 1, __ATOMIC_SEQ_CST);
          meta_spin = 0;
        }
      }

      if (atomic_load_acquire(&t_state->chunk_ready_head) <= claim_idx) {
        // We reached EOF and the claimed chunk does not exist. Safe to exit.
        goto unified_scanner_eof;
      }

      // PHYSICS FIX: Double-entry chunk accounting.
      __atomic_fetch_add(&state[my_node_id].stats_chunks_processed, 1,
                         __ATOMIC_RELAXED);
      if (steal_target != my_node_id) {
        __atomic_fetch_add(&state[my_node_id].stats_chunks_i_stole, 1,
                           __ATOMIC_RELAXED);
        __atomic_fetch_add(&state[steal_target].stats_chunks_stolen_from_me, 1,
                           __ATOMIC_RELAXED);
      }

      uint32_t current_major = t_state->chunk_queue[claim_idx & META_RING_MASK];
      meta = &g_state->meta_ring[current_major & META_RING_MASK];

      uint64_t act_end_flag = atomic_load_acquire(&meta->actual_end);
      uint64_t actual_end = act_end_flag & ~FLAG_META_READY;

      uint64_t actual_start = 0;
      if (current_major > 0) {
        struct ChunkMeta *prev_meta =
            &g_state->meta_ring[(current_major - 1) & META_RING_MASK];
        uint64_t prev_act_end;
        int _pe_spin = 0;
        while (!((prev_act_end = atomic_load_acquire(&prev_meta->actual_end)) &
                 FLAG_META_READY)) {
          if (_pe_spin < 10000) {
            cpu_relax();
            _pe_spin++;
          } else {
            uint32_t tnode = prev_meta->target_node;
            __atomic_fetch_add(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
            if (atomic_load_acquire(&prev_meta->actual_end) & FLAG_META_READY) {
              __atomic_fetch_sub(&state[tnode].meta_waiters, 1,
                                 __ATOMIC_SEQ_CST);
              break;
            }
            struct pollfd pfds[2] = {
                {.fd = evfd_meta_arr[tnode], .events = POLLIN},
                {.fd = evfd_ingest_eof, .events = POLLIN}};
            poll(pfds, 2, -1);
            if (atomic_load_relaxed(&state[0].emergency_abort)) {
                __atomic_fetch_sub(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
                goto unified_scanner_eof;
            }
            if (pfds[0].revents & POLLIN) {
              uint64_t v;
              sys_read(evfd_meta_arr[tnode], &v, 8);
            }
            __atomic_fetch_sub(&state[tnode].meta_waiters, 1, __ATOMIC_SEQ_CST);
            _pe_spin = 0;
          }
        }
        actual_start = prev_act_end & ~FLAG_META_READY;
      }

      if (actual_start >= actual_end) {
        batch_start = actual_start;
        bool _skipped = false;
        UNIFIED_SCANNER_FLUSH(true, meta->major_id, 0, actual_start,
                              _skipped);
        if (is_numa) {
          if (!_skipped) {
            chunk_bounds[cb_head & 15] = local_scan_idx;
            cb_head++;
          }
        }
        if (!_skipped) UNIFIED_ADAPTIVE_COMMIT(true);
        continue;
      }

      chunk_end = actual_end;
      current_p_offset = actual_start;
      batch_start = current_p_offset;
      buf_base_offset = current_p_offset;
      p = buf;
      end = buf;

    } else {
      if (status == 1 && p >= end)
        break;
      current_p_offset = buf_base_offset + (uint64_t)(p - buf);
    }

    bool current_stall = experienced_stall;
    experienced_stall = false;

    {
      uint64_t _xLim = W + DAMPING_OFFSET;
      if (current_stall ||
          (!is_numa && atomic_load_relaxed(&local_state->active_waiters) > 0))
        stall_meter = (stall_meter + _xLim) >> 1;
      else
        stall_meter >>= 1;

      if (atomic_load_relaxed(&local_state->active_waiters) > 0)
        starve_meter = (starve_meter + _xLim) >> 1;
      else
        starve_meter >>= 1;

      atomic_store_relaxed(&local_state->current_stall_meter, stall_meter);
      atomic_store_relaxed(&local_state->current_starve_meter, starve_meter);
    }

    while ((is_numa && current_p_offset < chunk_end) ||
           (!is_numa && (status != 1 || p < end))) {

      if (!is_numa && (p >= end || force_refill) && status != 1) {
        force_refill = false;
        uint64_t prev_avail = (p < end) ? (uint64_t)(end - p) : 0;
        current_p_offset = buf_base_offset + (uint64_t)(p - buf);

        // WORMHOLE FIX 4: UMA EOF Race Shield
        // Capture ingest_complete BEFORE pread. If it becomes complete
        // after pread returns 0, we must loop to verify no final bytes slipped in.
        bool was_complete = atomic_load_acquire(&local_state->ingest_complete);

        ssize_t n;
        do {
          if (atomic_load_relaxed(&state[0].emergency_abort)) goto unified_scanner_eof;
          n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset);
        } while (n < 0 && errno == EINTR);

        if (n > 0 && (uint64_t)n > prev_avail) {
          buf_base_offset = current_p_offset;
          p = buf;
          end = buf + n;
          status = 0;
          stall_meter >>= 1;
        } else {
          if (n > 0) {
            buf_base_offset = current_p_offset;
            p = buf;
            end = buf + n;
          }

          if (was_complete) {
            // It was complete BEFORE pread. 'n' is absolute truth.
            if (n == 0 || (n > 0 && (uint64_t)n <= prev_avail))
                status = 1;
          } else {
            // Check if it became complete in the background
            if (!atomic_load_acquire(&local_state->ingest_complete)) {
              struct pollfd pfds[2] = {{.fd = evfd_ingest_data, .events = POLLIN},
                                       {.fd = evfd_ingest_eof, .events = POLLIN}};
              if (poll(pfds, 2, 0) > 0) {
                if (pfds[1].revents & POLLIN)
                  atomic_store_release(&local_state->ingest_complete, 1);
              }
            }

            if (atomic_load_acquire(&local_state->ingest_complete)) {
              // It became complete AFTER our pread. We cannot trust 'n'.
              // We must loop around and pread one last time.
              force_refill = true;
              continue;
            } else {
              // Still not complete. Go into wait routine.
              status = 0;
              bool starving =
                  (atomic_load_relaxed(&local_state->active_waiters) > 0);
              UNIFIED_ADAPTIVE_COMMIT(starving);

              int poll_timeout = 100;
              if (starving && timeout_us >= 0) {
                if (first_wait_ts == 0)
                  first_wait_ts = get_us_time();
                uint64_t now = get_us_time();
                if (timeout_us == 0 ||
                    (now - first_wait_ts >= (uint64_t)timeout_us))
                  poll_timeout = 0;
                else {
                  uint64_t rem = (timeout_us - (now - first_wait_ts)) / 1000;
                  poll_timeout = (rem > 100) ? 100 : (int)rem;
                }
              } else
                first_wait_ts = 0;

              struct pollfd pfds[2] = {{.fd = evfd_ingest_data, .events = POLLIN},
                                       {.fd = evfd_ingest_eof, .events = POLLIN}};
              if (poll(pfds, 2, poll_timeout) > 0) {
                // EMERGENCY BYPASS
                if (atomic_load_relaxed(&state[0].emergency_abort)) {
                    goto unified_scanner_eof;
                }
                bool data_fired = (pfds[0].revents & POLLIN) != 0;
                bool eof_fired = (pfds[1].revents & POLLIN) != 0;

                // RULE: 1. check if local work evfd was non-zero. consume & loop
                if (data_fired) {
                  uint64_t v;
                  sys_read(evfd_ingest_data, &v, 8);
                }
                // RULE: 3. check EOF evfd ONLY if work evfd is zero
                else if (eof_fired) {
                  atomic_store_release(&local_state->ingest_complete, 1);
                }
              }
              current_stall = true;
              stall_meter = (stall_meter + (W + DAMPING_OFFSET)) >> 1;
              if (p < end)
                force_refill = true;
              continue;
            }
          }
        }
      }

      bool flush = false;
      bool limit_reached = false;
      bool force_flush_bytes = false; // WORMHOLE FIX 8

      if (byte_mode) {
        uint64_t avail =
            is_numa ? (chunk_end - current_p_offset) : (uint64_t)(end - p);
        uint64_t take = 0;

        if (limit_items > 0) {
          if (!is_numa && total_scanned >= limit_items) {
            status = 1;
            break;
          }
          if (is_numa) {
            uint64_t prev = __atomic_fetch_add(&state[0].global_scanned, (avail >= L ? L : avail), __ATOMIC_SEQ_CST);
            if (prev >= limit_items) break;
          }
        }

        if (avail >= L) {
          take = L;
          flush = true;
          first_wait_ts = 0;
        } else if (avail > 0) {
          if ((!is_numa && status == 1) || is_numa) {
            take = avail;
            flush = true;
          } else if (atomic_load_relaxed(&local_state->active_waiters) > 0) {
            if (timeout_us == 0) {
              take = avail;
              flush = true;
            } else if (timeout_us > 0 && first_wait_ts > 0 &&
                       (get_us_time() - first_wait_ts >=
                        (uint64_t)timeout_us)) {
              take = avail;
              flush = true;
              first_wait_ts = 0;
            }
          }
        }

        if (flush) {
          current_p_offset =
              is_numa ? (current_p_offset + take)
                      : (buf_base_offset + (uint64_t)(p - buf) + take);
          if (!is_numa)
            pending_lines = 0;

          bool is_last = is_numa ? (current_p_offset >= chunk_end) : false;
          bool _skipped = false;
          UNIFIED_SCANNER_FLUSH(is_last,
                                is_numa ? meta->major_id : 0, minor_idx,
                                current_p_offset, _skipped);
          if (is_last)
            chunk_eof_flushed = true;
          if (is_numa) {
            minor_idx++;
            if (is_last && !_skipped) {
              chunk_bounds[cb_head & 15] = local_scan_idx;
              cb_head++;
            }
          }

          p += take;
          batch_start += is_numa ? take : current_p_offset - batch_start;
          total_scanned += is_numa ? take : 1;
          pending_lines = 0;
        } else {
          if (!is_numa)
            force_refill = true;
        }
      } else {
        uint64_t scan_target = (L > pending_lines) ? (L - pending_lines) : 0;
        if (limit_items > 0) {
          uint64_t current_global =
              is_numa ? atomic_load_relaxed(&state[0].global_scanned)
                      : total_scanned;
          if (current_global >= limit_items) {
            if (!is_numa)
              status = 1;
            break;
          }
          uint64_t rem = limit_items - current_global;
          if (scan_target > rem)
            scan_target = rem;
          if (!is_numa && rem == 0) {
            status = 1;
            scan_target = 0;
          }
        }
        if (scan_target == 0 && !limit_reached &&
            (!is_numa ? status != 1 : true))
          scan_target = 1;

        uint64_t lines_found = 0;

        char *safe_end = end;
        if (BytesMax > 0) {
          uint64_t max_overhead = (scan_target + 1) * 8;
          if (BytesMax <= max_overhead)
            safe_end = p;
          else {
            uint64_t max_payload = BytesMax - max_overhead;
            uint64_t current_payload =
                (buf_base_offset + (p - buf)) - batch_start;
            if (current_payload >= max_payload)
              safe_end = p;
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
            if (atomic_load_relaxed(&state[0].emergency_abort)) goto unified_scanner_eof;
            if (p >= end) {
              if (is_numa) {
                uint64_t read_start = buf_base_offset + (p - buf);
                size_t to_read = chunk_sz;
                if (read_start + to_read > chunk_end)
                  to_read = chunk_end - read_start;
                if (to_read > 0) {
                  ssize_t n;
                  do {
                    if (atomic_load_relaxed(&state[0].emergency_abort)) goto unified_scanner_eof;
                    n = pread(fd_or_memfd, buf, to_read, read_start);
                  } while (n < 0 && errno == EINTR);
                  if (n > 0) {
                    buf_base_offset = read_start;
                    p = buf;
                    end = buf + n;
                  } else {
                    chunk_end = buf_base_offset + (end - buf);
                    break;
                  }
                } else
                  break;
              } else {
                break;
              }
            }

            char *nl = memchr(p, delim, end - p);
            if (nl) {
              if (BytesMax > 0 && lines_found > 0) {
                uint64_t line_end_offset =
                    buf_base_offset + (uint64_t)((nl + 1) - buf);
                uint64_t payload = line_end_offset - batch_start;
                uint64_t overhead = (lines_found + 1) * 8;
                if ((payload + overhead) > BytesMax) {
                  // WORMHOLE FIX 8: The BytesMax Continuation
                  // Do NOT set limit_reached (which triggers global EOF).
                  // Instead, force a flush so the scanner continues processing the rest of the chunk.
                  force_flush_bytes = true;
                  break;
                }
              }
              lines_found++;
              p = nl + 1;
            } else {
              if (is_numa) {
                uint64_t curr_pos = buf_base_offset + (end - buf);
                if (curr_pos >= chunk_end) {
                  lines_found++;
                  p = end;
                  break;
                } else
                  p = end;
              } else {
                if (status == 1 && p < end) {
                  lines_found++;
                  p = end;
                }
                break;
              }
            }
          }
        }

        if (is_numa && limit_items > 0 && lines_found > 0) {
          uint64_t prev = __atomic_fetch_add(&state[0].global_scanned,
                                             lines_found, __ATOMIC_SEQ_CST);
          if (prev >= limit_items) {
            lines_found = 0;
            limit_reached = true;
            break;
          } else if (prev + lines_found >= limit_items)
            limit_reached = true;
        }

        pending_lines += lines_found;
        total_scanned += lines_found;
        atomic_store_relaxed(&local_state->total_lines_scanned, total_scanned);
        current_p_offset = buf_base_offset + (p - buf);

        if (!is_numa && limit_items > 0 && total_scanned >= limit_items)
          status = 1;

        if (pending_lines > 0) {
          if (pending_lines >= L || limit_reached || force_flush_bytes ||
              (is_numa && current_p_offset >= chunk_end) ||
              (!is_numa && status == 1)) {
            flush = true;
          } else if (starve_meter >= (W + DAMPING_OFFSET - 3)) {
            bool trigger = (stall_meter >= (W + DAMPING_OFFSET - 3));
            if (trigger && !exact_lines) {
              if (timeout_us == 0)
                flush = true;
              else if (timeout_us > 0) {
                if (first_wait_ts == 0)
                  first_wait_ts = get_us_time();
                if (get_us_time() - first_wait_ts >= (uint64_t)timeout_us)
                  flush = true;
              }
            }
          }
          if (flush)
            first_wait_ts = 0;
        } else if (!is_numa)
          force_refill = true;

        if (flush) {
          // WORMHOLE FIX 8: Ensure a force_flush_bytes doesn't accidentally trigger a FLAG_MAJOR_EOF chunk end
          bool is_last = is_numa
                             ? (current_p_offset >= chunk_end || limit_reached)
                             : false;
          bool _skipped = false;
          UNIFIED_SCANNER_FLUSH(is_last,
                                is_numa ? meta->major_id : 0, minor_idx,
                                current_p_offset, _skipped);
          if (is_last)
            chunk_eof_flushed = true;
          if (is_numa) {
            minor_idx++;
            if (is_last && !_skipped) {
              chunk_bounds[cb_head & 15] = local_scan_idx;
              cb_head++;
            }
          }
          batch_start = current_p_offset;
          pending_lines = 0;

          if (!_skipped) {
            int node_arg = is_numa ? my_node_id : -1;
            atomic_store_relaxed(&local_state->current_batch_size, L);
            ADAPTIVE_FLOW_CONTROL(local_state, current_stall, node_arg);
          }
        } else if (!is_numa)
          force_refill = true;
      }
      if (limit_reached)
        break;
    }

    if (is_numa && !chunk_eof_flushed) {
      bool _skipped = false;
      UNIFIED_SCANNER_FLUSH(true, meta->major_id,
                            minor_idx, current_p_offset, _skipped);
      minor_idx++;
      if (!_skipped) {
        chunk_bounds[cb_head & 15] = local_scan_idx;
        cb_head++;
      }
      batch_start = current_p_offset;
      pending_lines = 0;
    }

    if (is_numa) {
      UNIFIED_ADAPTIVE_COMMIT(true);
    }

    // CRITICAL FIX: Universal limit break for both UMA and NUMA
    if (limit_items > 0) {
      uint64_t current_global = is_numa ? atomic_load_relaxed(&state[0].global_scanned) : total_scanned;
      if (current_global >= limit_items) break;
    }
  }

unified_scanner_eof:
  // =========================================================
  // 3. FINALIZATION (NUMA Finish vs UMA Tail Re-batching)
  // =========================================================

  if (fd_spawn >= 0) {
    uint64_t W_curr = atomic_load_relaxed(&local_state->active_workers);
    if (W_curr < W_max_val) {
      uint64_t r_idx = atomic_load_relaxed(&local_state->read_idx);
      uint64_t backlog = (local_scan_idx > r_idx) ? local_scan_idx - r_idx : 0;
      uint64_t W_target = (backlog > W_max_val) ? W_max_val : backlog;
      if (W_target > W_curr) {
        uint64_t needed = W_target - W_curr;
        if (needed > 0) {
          char sbuf[64];
          int slen;
          if (is_numa)
            slen = snprintf(sbuf, sizeof(sbuf), "%d:%lu\n", my_node_id, needed);
          else
            slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", needed);
          if (slen > 0)
            robust_pipe_write(fd_spawn, sbuf, slen);
          W += needed;
        }
      }
    }
  }

  if (is_numa) {
    // v3.3.0+: No PUBLISH_BATCH_SIZE needed at EOF. Workers always claim exactly
    // 1 slot (single atomic_fetch_add); once write_idx stops advancing they
    // observe read_idx >= write_idx and proceed to the EOF condition check.
    atomic_store_release(&local_state->write_idx, local_scan_idx);
    atomic_store_release(&local_state->scanner_finished, 1);

    // RULE: Set EOF evfd ONLY after scanner is fully finished
    uint64_t blast = 999999;
    sys_write(evfd_eof_arr[my_node_id], &blast, 8);

    if (fd_spawn >= 0) { /* Sentinel write removed */ }
  } else {
    // --- PHYSICS FIX: Prevent UMA ghost batches violating exact limit ---
    bool limit_hit = (limit_items > 0 && total_scanned >= limit_items);

    if (!byte_mode && !limit_hit && !atomic_load_relaxed(&state[0].emergency_abort)) {
      // v3.3.0 tail: Force-commit all locally-written ring slots before computing
      // L_tail, ensuring local_write_idx == local_scan_idx here so that only
      // pending_lines and the current read buffer need to be counted below.
      atomic_store_release(&local_state->write_idx, local_scan_idx);
      local_write_idx = local_scan_idx;
      __atomic_thread_fence(__ATOMIC_SEQ_CST);
      uint32_t _aw_tail = atomic_load_acquire(&local_state->active_waiters);
      if (_aw_tail > 0) {
        uint64_t _v_tail = _aw_tail;
        sys_write(evfd_eof_arr[0], &_v_tail, 8);
      }

      // L_tail = lines pending in current batch (not yet in a ring slot)
      //        + lines remaining in the current read buffer (not yet scanned)
      // Lines in already-committed ring slots are counted separately by workers.
      uint64_t L_tail = pending_lines;
      char *p_scan = p;

      while (p_scan < end) {
        char *nl = memchr(p_scan, delim, end - p_scan);
        if (nl) {
          L_tail++;
          p_scan = nl + 1;
        } else {
          if (p_scan < end)
            L_tail++;
          break;
        }
      }
      // No uncommitted slots to count: force-commit above guarantees
      // local_write_idx == local_scan_idx before this point.

      uint64_t tail_start_offset =
          (local_scan_idx > local_write_idx)
              ? state[0].offset_ring[local_write_idx & RING_MASK]
              : batch_start;
      local_scan_idx = local_write_idx;
      int64_t buf_rel = (int64_t)tail_start_offset - (int64_t)buf_base_offset;
      if (buf_rel >= 0 && buf_rel < (int64_t)chunk_sz) {
        p = buf + buf_rel;
        batch_start = tail_start_offset;
      } else {
        buf_base_offset = tail_start_offset;
        batch_start = tail_start_offset;
        ssize_t n;
        do {
          n = pread(fd_or_memfd, buf, chunk_sz, (off_t)tail_start_offset);
        } while (n < 0 && errno == EINTR);
        p = buf;
        end = buf + (n > 0 ? n : 0);
      }
      uint64_t R = 1;
      if (L > 0) {
        uint64_t inner_log = fast_log2(2 + L);
        R = fast_log2(2 + inner_log);
      }
      if (R < 1)
        R = 1;
      uint64_t L_tail_done = 0;
      atomic_store_release(&state[0].tail_idx, local_write_idx);

      while (L_tail_done < L_tail) {
        uint64_t target =
            (L_tail > 0) ? (L * (L_tail - L_tail_done)) / L_tail : 0;
        uint64_t min_batch = L / R;
        if (min_batch < 1)
          min_batch = 1;
        if (target < min_batch)
          target = min_batch;
        if (target > L_tail - L_tail_done)
          target = L_tail - L_tail_done; // PHYSICS FIX: Prevent UMA ghost batches at EOF

        uint64_t lines_found = 0;
        while (lines_found < target && (lines_found + L_tail_done) < L_tail) {
          if (atomic_load_relaxed(&state[0].emergency_abort)) goto tail_abort;

          char *safe_end = end;
          if (BytesMax > 0) {
            uint64_t max_overhead = (target + 1) * 8;

            if (BytesMax <= max_overhead) {
              uint64_t max_possible_target = (BytesMax > 16) ? (BytesMax - 1) / 8 - 1 : 1;
              target = max_possible_target > 0 ? max_possible_target : 1;
              max_overhead = (target + 1) * 8;
            }

            if (BytesMax <= max_overhead) {
              target = 1;
              // Allow safe_end = end so memchr finds the next delimiter
            } else {
              uint64_t max_payload = BytesMax - max_overhead;
              uint64_t current_payload =
                  (buf_base_offset + (p - buf)) - batch_start;
              if (current_payload >= max_payload)
                safe_end = p;
              else if (max_payload - current_payload < (uint64_t)(end - p)) {
                safe_end = p + (max_payload - current_payload);
              }
            }
          }

          if (p >= safe_end) {
            if (p >= end) {
              uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
              ssize_t n;
              do {
                n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset);
              } while (n < 0 && errno == EINTR);
              if (n > 0) {
                buf_base_offset = current_p_offset;
                p = buf;
                end = buf + n;
                continue; // Re-evaluate safe_end with the new buffer
              } else
                break;
            } else {
              // We reached safe_end before end of buffer. Force early flush.
              break;
            }
          }

          char *nl = memchr(p, delim, safe_end - p);
          if (nl) {
            lines_found++;
            p = nl + 1;
          } else {
            if (safe_end < end) {
              // We hit safe_end. Force early flush.
              break;
            }
            uint64_t current_p_offset = buf_base_offset + (uint64_t)(end - buf);
            ssize_t n;
            do {
              n = pread(fd_or_memfd, buf, chunk_sz, (off_t)current_p_offset);
            } while (n < 0 && errno == EINTR);
            if (n > 0) {
              buf_base_offset = current_p_offset;
              p = buf;
              end = buf + n;
            } else {
              p = end;
              break;
            }
          }
        }
        if (lines_found < target && (lines_found + L_tail_done) < L_tail) {
          if (p >= end) {
            uint64_t remainder = L_tail - L_tail_done - lines_found;
            lines_found += remainder;
          }
        }
        if (lines_found > 0) {
          uint64_t current_p_offset = buf_base_offset + (uint64_t)(p - buf);
          bool _skipped = false;
          UNIFIED_SCANNER_FLUSH(false, 0, 0, current_p_offset,
                                _skipped);
          batch_start = current_p_offset;
          L_tail_done += lines_found;
        } else
          break;
      }
    }

tail_abort:
    uint64_t final_sentinel = buf_base_offset + (uint64_t)(p - buf);
    local_state->offset_ring[local_scan_idx & RING_MASK] =
        (uint64_t)final_sentinel;
    local_state->end_ring[local_scan_idx & RING_MASK] =
        (uint64_t)final_sentinel;
    local_scan_idx++;

    atomic_store_release(&local_state->write_idx, local_scan_idx);
    atomic_store_release(&local_state->scanner_finished, 1);

    // RULE: Blast wakeups universally to prevent lost wakeups at EOF
    uint64_t blast = 999999;
    sys_write(evfd_eof_arr[0], &blast, 8);

    if (fd_spawn >= 0) { /* Sentinel write removed */ }
  }

  munmap(buf, chunk_sz);
  return EXECUTION_SUCCESS;
}

// ==============================================================================
// 6. SCANNER WRAPPER ENTRY POINTS
// ==============================================================================

static int ring_scanner_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  int fd = atoi(argv[1]);
  int fd_spawn = (argc >= 3) ? atoi(argv[2]) : -1;
  // Call Unified Loop with is_numa = false
  return core_scanner_loop(fd, 0, fd_spawn, 1, false);
}

static int ring_numa_scanner_main(int argc, char **argv) {
  if (argc < 5)
    return EXECUTION_FAILURE;
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

// ------------------------------------------------------------------
// do_lockfree_claim: Pure side-effect-free batch claim helper.
// Populates `out` with batch metadata without touching any Bash
// variables. ring_claim_main is the only caller and handles all
// variable binding after the fact.
//
// Returns:
//   0               = success, `out` is populated
//   1               = no data available (non-blocking mode only)
//   2               = EOF — all data consumed, terminate worker
//   EXECUTION_FAILURE = emergency abort or fatal error
//
// Precondition: my_numa_node must be initialized by the caller.
// ------------------------------------------------------------------
static int do_lockfree_claim(struct WorkerBatchState *out, bool blocking) {
  if (atomic_load_relaxed(&state[0].emergency_abort))
    return EXECUTION_FAILURE;

  struct SharedState *local_state = &state[my_numa_node];

  uint64_t my_read_idx;
  uint32_t current_kills = 0;
  int spin = 0;

dlc_restart_loop:

  // Re-arm tl_drain_escrow if ring_escrow_put_main has deposited since we
  // last drained.  Costs one relaxed load (≤1 cycle, stays in local cache).
  // PHYSICS FIX: Test-and-Test-and-Set prevents RMW cache-line ping-pong.
  if (__builtin_expect(__atomic_load_n(&local_state->escrow_pending, __ATOMIC_ACQUIRE), 0)) {
    if (__atomic_exchange_n(&local_state->escrow_pending, 0, __ATOMIC_ACQ_REL))
        tl_drain_escrow = true;
}

  // Escrow continuous drain: vacuums the pipe completely before touching the
  // lock-free ring. tl_drain_escrow stays true as long as packets keep
  // arriving; only snaps false on EAGAIN (pipe empty). This enforces the
  // Priority Inversion invariant more aggressively than the old one-shot flag.
  if (tl_drain_escrow && fd_escrow_r && fd_escrow_r[my_numa_node] >= 0) {
    struct EscrowPacket ep;
    ssize_t er;
    do {
      er = read(fd_escrow_r[my_numa_node], &ep, sizeof(ep));
    } while (er < 0 && errno == EINTR);
    if (er == sizeof(ep)) {
      my_read_idx   = ep.idx;
      current_kills = ep.num_kills;
      // Do NOT clear tl_drain_escrow here — keep draining until pipe is empty.
      goto dlc_evaluate_claim;
    } else if (er < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      // Pipe fully drained. Snap back to zero-overhead fast path.
      tl_drain_escrow = false;
    }
  }

  while (1) {
    // 1. Ring check (Local Work)
    uint64_t w_snap = atomic_load_acquire(&local_state->write_idx);
    uint64_t r_curr = atomic_load_relaxed(&local_state->read_idx);

    if (r_curr < w_snap) {
      // v3.3: THE FAST PATH — always claim exactly 1 slot.
      // Pre-flight popcount ensures L is already optimal when the first worker
      // arrives, so no geometric ramp-up is needed here. Zero state machine,
      // zero TLS cursor, zero speculative splitting.
      my_read_idx = __atomic_fetch_add(&local_state->read_idx, 1,
                                       __ATOMIC_SEQ_CST);
      break;
    }

    // 2. Escrow check (Non-Local Work)
    if (fd_escrow_r && fd_escrow_r[my_numa_node] >= 0) {
      struct EscrowPacket ep;
      ssize_t er;
      do {
        er = read(fd_escrow_r[my_numa_node], &ep, sizeof(ep));
      } while (er < 0 && errno == EINTR);
      if (er == sizeof(ep)) {
        my_read_idx   = ep.idx;
        current_kills = ep.num_kills;
        break;
      }
    }

    // 3. Scanner finished check (The 3 Sequential Conditions for EOF)
    if (atomic_load_acquire(&local_state->scanner_finished)) {
      if (atomic_load_acquire(&local_state->read_idx) <
          atomic_load_acquire(&local_state->write_idx)) {
        continue;
      }
      if (fd_escrow_r && fd_escrow_r[my_numa_node] >= 0) {
        struct pollfd pfd = {.fd = fd_escrow_r[my_numa_node], .events = POLLIN};
        if (poll(&pfd, 1, 0) > 0 && (pfd.revents & POLLIN)) {
          continue;
        }
      }
      // All 3 physical conditions met in order. Consensus achieved. Terminate.
      return 2;
    }

    // Non-blocking mode: return immediately if no data is available now.
    if (!blocking) return 1;

    // 4. Spin
    if (spin < 100) {
      cpu_relax();
      spin++;
      continue;
    }

    // 5. Poll (3-way simultaneous: local data evfd, escrow pipe, EOF evfd)
    __atomic_fetch_add(&local_state->active_waiters, 1, __ATOMIC_SEQ_CST);
    is_waiting_on_ring = true;

    struct pollfd pfds[3] = {
        {.fd = evfd_data_arr[my_numa_node], .events = POLLIN},
        {.fd = (fd_escrow_r && fd_escrow_r[my_numa_node] >= 0) ? fd_escrow_r[my_numa_node] : -1, .events = POLLIN},
        {.fd = evfd_eof_arr[my_numa_node], .events = POLLIN}
    };

    while (1) {
      if (atomic_load_acquire(&local_state->write_idx) >
          atomic_load_relaxed(&local_state->read_idx))
        break;

      if (atomic_load_acquire(&local_state->scanner_finished))
        break;

      poll(pfds, 3, -1);

      if (atomic_load_relaxed(&state[0].emergency_abort)) {
        cleanup_waiter_state();
        return EXECUTION_FAILURE;
      }

      bool data_fired   = (pfds[0].revents & POLLIN) != 0;
      bool escrow_fired = (pfds[1].fd >= 0 && (pfds[1].revents & POLLIN) != 0);
      bool eof_fired    = (pfds[2].revents & POLLIN) != 0;

      // Strict priority: data > escrow > EOF
      if (data_fired) {
        uint64_t v;
        sys_read(pfds[0].fd, &v, 8);
        continue;
      } else if (escrow_fired) {
        break; // outer loop section 2 will read the packet
      } else if (eof_fired && !data_fired && !escrow_fired) {
        break; // outer loop section 3 will confirm EOF
      }
    }

    cleanup_waiter_state();
    spin = 0;
  }

dlc_evaluate_claim:
  {
    uint64_t w_curr = atomic_load_acquire(&local_state->write_idx);
    if (my_read_idx >= w_curr) {
      // Overshot: the ring advanced past us (scanner hasn't filled this slot yet,
      // or we raced with EOF). Wait for the slot to be committed.
      if (atomic_load_acquire(&local_state->scanner_finished)) {
        // Scanner done and we overshot → nothing left for us.
        spin = 0;
        goto dlc_restart_loop;
      }
      // Scanner still running — wait for write_idx to cover our slot.
      __atomic_fetch_add(&local_state->active_waiters, 1, __ATOMIC_SEQ_CST);
      is_waiting_on_ring = true;
      while (1) {
        w_curr = atomic_load_acquire(&local_state->write_idx);
        if (w_curr > my_read_idx)
          break; // slot is ready
        if (atomic_load_acquire(&local_state->scanner_finished)) {
          w_curr = atomic_load_acquire(&local_state->write_idx);
          break;
        }
        struct pollfd pfds[2] = {
            {.fd = evfd_data_arr[my_numa_node],  .events = POLLIN},
            {.fd = evfd_eof_arr[my_numa_node],   .events = POLLIN}};
        poll(pfds, 2, -1);
        if (atomic_load_relaxed(&state[0].emergency_abort)) {
          cleanup_waiter_state();
          return EXECUTION_FAILURE;
        }
        if (pfds[0].revents & POLLIN) {
          uint64_t v;
          sys_read(evfd_data_arr[my_numa_node], &v, 8);
        }
      }
      cleanup_waiter_state();
      if (my_read_idx >= w_curr) {
        // Still overshot after waiting — EOF consumed us
        spin = 0;
        goto dlc_restart_loop;
      }
    }
  }

  // Populate output struct
  uint64_t start = local_state->offset_ring[my_read_idx & RING_MASK];
  uint64_t end   = local_state->end_ring[my_read_idx & RING_MASK];

  __atomic_fetch_add(&local_state->total_lines_consumed, 1, __ATOMIC_SEQ_CST);

  out->idx       = my_read_idx;
  out->cnt       = 1;
  out->num_kills = current_kills;
  out->offset    = start;
  out->length    = end - start;

  if (local_state->numa_enabled) {
    out->major = local_state->major_ring[my_read_idx & RING_MASK];
    out->minor = local_state->minor_ring[my_read_idx & RING_MASK] & ~FLAG_MAJOR_EOF;
    if (local_state->minor_ring[my_read_idx & RING_MASK] & FLAG_MAJOR_EOF)
      out->minor |= FLAG_MAJOR_EOF;
  } else {
    out->major = 0;
    out->minor = 0;
  }

  return 0;
}

// Workers Claiming Data (Water Wheels):
// The fast path is a single lock-free `atomic_fetch_add` to claim exactly 1
// slot (1 batch) of records. There are NO CAS retry loops on the fast path. If
// a worker process fails mid-execution, its active transaction is rolled back
// and re-deposited into an escrow pipe for other idle workers to steal. Escrow
// is an optimistic transaction recovery queue; forward progress is guaranteed
// by strictly monotonic indices.
//
// This function is now a thin wrapper: do_lockfree_claim handles all ring
// physics, and this function handles NUMA init, the SIGPIPE shield, and all
// Bash variable bindings.
static int ring_claim_main(int argc, char **argv) {
  const char *v_target = "REPLY";

  if (argc >= 2) {
    v_target = argv[1];
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

  // --- UNIVERSAL SIGPIPE / TEARDOWN SHIELD ---
  if (state) {
      // 1. Did someone else pull the fire alarm? (e.g., ring_order, or Fallow dying)
      if (atomic_load_relaxed(&state[0].emergency_abort)) {
          return EXECUTION_FAILURE;
      }

      // 2. Sentry duty: Check if stdout is broken (Crucial for -u realtime mode)
      // We only poll every 64 claims to ensure absolute zero overhead on the fast path.
      static __thread int claim_calls = 0;
      if ((claim_calls++ & 63) == 0) {
          struct pollfd pfd_stdout = {.fd = 1, .events = POLLOUT};
          if (poll(&pfd_stdout, 1, 0) > 0 && (pfd_stdout.revents & (POLLERR | POLLHUP))) {
              // The downstream pipe was cut (e.g., head -n 5). Pull the fire alarm!
              pull_fire_alarm();
              return EXECUTION_FAILURE;
          }
      }
  }
  // -------------------------------------------

  struct WorkerBatchState batch;
  int rc = do_lockfree_claim(&batch, true);
  if (rc != 0) return rc;

  // --- Publish metadata to TLS globals ---
  worker_last_idx       = batch.idx;
  worker_last_cnt       = batch.cnt;
  worker_last_num_kills = batch.num_kills;
  worker_last_major     = batch.major;
  worker_last_minor     = batch.minor;
  tls_batch_offset      = (off_t)batch.offset;

  // --- Bind the byte-length to the target Bash variable ---
  char buf[64];
  u64toa(batch.length, buf);
  bind_var_or_array(v_target, buf, 0);

  // --- Export retry/poison metadata only for recycled (escrow) batches ---
  // For fresh batches (num_kills == 0) these variables retain their previous
  // values; the Bash layer only inspects them after a non-zero retry count.
  if (batch.num_kills > 0) {
    snprintf(buf, sizeof(buf), "%u", batch.num_kills);
    bind_variable("RING_NUM_KILLS", buf, 0);

    u64toa(batch.idx, buf);
    bind_variable("RING_BATCH_IDX", buf, 0);

    int limit = 3; // Default to 3 retries
    const char *s_lim = get_string_value("FORKRUN_RETRY_LIMIT");
    if (s_lim) limit = atoi(s_lim);

    // limit < 0  → infinite retries (never poison)
    // limit >= 0 → poison when kill count reaches the limit
    if (limit >= 0 && batch.num_kills >= (uint32_t)limit) {
      bind_variable("RING_POISONED", "1", 0);

      // CRITICAL FIX: Increment the global counter exactly ONCE upon crossing the threshold
      if (batch.num_kills == (uint32_t)limit && g_state) {
          __atomic_add_fetch(&g_state->poisoned_count, 1, __ATOMIC_RELAXED);
      }
    } else {
      bind_variable("RING_POISONED", "0", 0);
    }
  }

  return 0;
}

// Worker Acknowledgment:
// When a worker finishes processing a batch, it sends an acknowledgment packet
// to the fallow pipe (legacy) or directly updates output tracking. This signal
// is what allows the system to later garbage-collect the processed data.
static int ring_ack_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  int fd_fallow = atoi(argv[1]);
  int fd_target = (argc >= 3) ? atoi(argv[2]) : -1;

  struct sigaction sa_ign, sa_old;
  sa_ign.sa_handler = SIG_IGN;
  sigemptyset(&sa_ign.sa_mask);
  sa_ign.sa_flags = 0;
  sigaction(SIGPIPE, &sa_ign, &sa_old);

  struct OrderPacket op = {0};

  struct SharedState *local_state =
      (my_numa_node != -1 && my_numa_node < (int)global_num_nodes)
          ? &state[my_numa_node]
          : &state[0];

  uint64_t my_idx;
  if (worker_last_cnt > 0) {
    my_idx = worker_last_idx;
    if (local_state && local_state->numa_enabled) {
      op.major_idx = worker_last_major;
      op.minor_idx = worker_last_minor;
      op.cnt = worker_last_cnt;
    } else {
      op.major_idx = (uint32_t)worker_last_idx;
      op.minor_idx = 0;
      op.cnt = worker_last_cnt;
    }
  } else {
    op.cnt = (uint32_t)atoi(get_string_value("RING_BATCH_SLOTS"));
    if (local_state && local_state->numa_enabled) {
      op.major_idx = (uint32_t)atoi(get_string_value("RING_MAJOR"));
      op.minor_idx = (uint32_t)atoi(get_string_value("RING_MINOR"));
      my_idx = (uint64_t)atoll(get_string_value("RING_BATCH_IDX"));
    } else {
      op.major_idx = (uint32_t)atoi(get_string_value("RING_BATCH_IDX"));
      op.minor_idx = 0;
      my_idx = op.major_idx;
    }
  }

  if (fd_fallow > 0) {
    if (local_state && local_state->numa_enabled) {
      uint64_t start =
          local_state->offset_ring[my_idx & RING_MASK];
      uint64_t end = local_state->end_ring[(my_idx + op.cnt - 1) & RING_MASK];
      struct PhysPacket pp = {.off = start, .len = end - start};
      if (robust_pipe_write(fd_fallow, &pp, sizeof(pp)) < 0) {
          sigaction(SIGPIPE, &sa_old, NULL);
          return EXECUTION_FAILURE;
      }
    } else {
      struct IndexPacket ip = {.idx = op.major_idx, .cnt = op.cnt};
      if (robust_pipe_write(fd_fallow, &ip, sizeof(ip)) < 0) {
          sigaction(SIGPIPE, &sa_old, NULL);
          return EXECUTION_FAILURE;
      }
    }
  }

  uint64_t in_start = local_state->offset_ring[my_idx & RING_MASK];
  uint64_t in_end = local_state->end_ring[(my_idx + op.cnt - 1) & RING_MASK];
  op.in_off = in_start;
  op.in_len = in_end - in_start;

  if (fd_target > 0) {
    if (fd_target != ack_cached_target_fd) {
      ack_cached_target_fd = fd_target;
      struct stat st;
      ack_cached_mode =
          (fstat(fd_target, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 2;
    }
    if (ack_cached_mode == 1) {
      const char *s_order_pipe = get_string_value("FD_ORDER_PIPE");
      if (s_order_pipe) {
        int fd_pipe = atoi(s_order_pipe);
        off_t curr = lseek(fd_target, 0, SEEK_CUR);
        if (curr == (off_t)-1) {
          sigaction(SIGPIPE, &sa_old, NULL);
          return EXECUTION_FAILURE;
        }
        op.fd = fd_target;
        op.off = (uint64_t)last_ack_offset;
        op.len = (uint64_t)(curr - last_ack_offset);
        if (robust_pipe_write(fd_pipe, &op, sizeof(op)) < 0) {
            sigaction(SIGPIPE, &sa_old, NULL);
            return EXECUTION_FAILURE;
        }
        last_ack_offset = curr;
      }
    } else {
      if (robust_pipe_write(fd_target, &op, sizeof(op)) < 0) {
          sigaction(SIGPIPE, &sa_old, NULL);
          return EXECUTION_FAILURE;
      }
    }
  }

  sigaction(SIGPIPE, &sa_old, NULL);
  return EXECUTION_SUCCESS;
}

// --- MIN-HEAP ORDERING ---
// Min-Heap logic for Output Ordering:
// Workers finish out of order depending on the data size and OS scheduling.
// To guarantee strict output ordering, packets are inserted into a min-heap
// keyed by their logical sequence number. The orderer thread continuously pops
// the heap as the next expected sequence number arrives.
struct HeapNode {
  uint64_t key;
  struct OrderPacket pkt;
};

static void heap_push(struct HeapNode **heap_ptr, int *sz, int *cap,
                      uint64_t key, struct OrderPacket pkt) {
  if (*sz >= *cap) {
    int new_cap = (*cap) * 2;
    void *new_ptr = realloc(*heap_ptr, new_cap * sizeof(struct HeapNode));
    if (!new_ptr) { pull_fire_alarm(); return; } // Drop on OOM to prevent segfault
    *cap = new_cap;
    *heap_ptr = new_ptr;
  }
  struct HeapNode *heap = *heap_ptr;
  int i = (*sz)++;
  while (i > 0) {
    int p = (i - 1) / 2;
    if (heap[p].key <= key)
      break;
    heap[i] = heap[p];
    i = p;
  }
  heap[i].key = key;
  heap[i].pkt = pkt;
}

static void heap_pop(struct HeapNode *heap, int *sz, struct HeapNode *out) {
  *out = heap[0];
  struct HeapNode tmp = heap[--(*sz)];
  int i = 0;
  while (i * 2 + 1 < *sz) {
    int child = i * 2 + 1;
    if (child + 1 < *sz && heap[child + 1].key < heap[child].key)
      child++;
    if (tmp.key <= heap[child].key)
      break;
    heap[i] = heap[child];
    i = child;
  }
  heap[i] = tmp;
}

static ssize_t robust_sendfile(int out_fd, int in_fd, off_t *offset,
                               size_t count) {
  size_t total = 0;
  int retries = 0;
  while (total < count) {
    ssize_t s = sendfile(out_fd, in_fd, offset, count - total);
    if (s < 0) {
      if (errno == EINTR || errno == EAGAIN) {
        usleep(10);
        continue;
      }
      return total > 0 ? (ssize_t)total : -1;
    }
    if (s == 0) {
      if (retries++ < 100) {
        usleep(10);
        continue;
      }
      break;
    }
    retries = 0;
    total += s;
  }
  return (ssize_t)total;
}

#define BUF_SIZE 65536
static int ring_copy_chunk(int fd_in, int fd_out, off_t off, size_t len) {
  char buf[BUF_SIZE];
  size_t total_read = 0;
  int retries = 0;
  while (total_read < len) {
    size_t to_read =
        (len - total_read > BUF_SIZE) ? BUF_SIZE : (len - total_read);
    ssize_t r = pread(fd_in, buf, to_read, off + total_read);
    if (r < 0) {
      if (errno == EINTR || errno == EAGAIN) {
        usleep(10);
        continue;
      }
      return -1;
    }
    if (r == 0) {
      if (retries++ < 100) {
        usleep(10);
        continue;
      }
      break;
    }
    retries = 0;
    char *write_ptr = buf;
    size_t to_write = r;
    while (to_write > 0) {
      ssize_t w = write(fd_out, write_ptr, to_write);
      if (w < 0) {
        if (errno == EINTR || errno == EAGAIN) {
          usleep(10);
          continue;
        }
        return -1;
      }
      write_ptr += w;
      to_write -= w;
    }
    total_read += r;
  }
  return (total_read == len) ? 0 : -1;
}

// ==============================================================================
// INTERVAL MIN-HEAP (O(log N) out-of-order sequence assembly)
// ==============================================================================

static inline void interval_heap_push(struct IntervalNode **heap_ptr, int *sz, int *cap, uint64_t s, uint64_t e) {
    if (*sz >= *cap) {
        int new_cap = (*cap) * 2;
        void *new_ptr = realloc(*heap_ptr, new_cap * sizeof(struct IntervalNode));
        if (!new_ptr) { pull_fire_alarm(); return; } // Drop on OOM to prevent segfault
        *cap = new_cap;
        *heap_ptr = new_ptr;
    }
    struct IntervalNode *heap = *heap_ptr;
    int i = (*sz)++;
    while (i > 0) {
        int p = (i - 1) / 2;
        if (heap[p].s <= s) break;
        heap[i] = heap[p];
        i = p;
    }
    heap[i].s = s;
    heap[i].e = e;
}

static inline void interval_heap_pop(struct IntervalNode *heap, int *sz, struct IntervalNode *out) {
    *out = heap[0];
    struct IntervalNode tmp = heap[--(*sz)];
    int i = 0;
    while (i * 2 + 1 < *sz) {
        int child = i * 2 + 1;
        if (child + 1 < *sz && heap[child + 1].s < heap[child].s) child++;
        if (tmp.s <= heap[child].s) break;
        heap[i] = heap[child];
        i = child;
    }
    heap[i] = tmp;
}


// ==============================================================================
// OUTPUT ORDERING ENGINE (The "Lorentz Transformation" for data streams)
// ==============================================================================

// Receives out-of-order data segments from workers via the order pipe.
// Uses a min-heap to buffer them and emits contiguous prefixes to stdout.
// This is the only place in the fast path where workers might block (if the
// pipe fills).

struct OrderFdState {
    struct IntervalNode *heap;
    int heap_sz;
    int heap_cap;
    uint64_t limit;
    off_t last_punched;
};

static inline void safe_hole_punch(int p_fd, off_t p_off, size_t p_len, struct OrderFdState **fd_states_ptr, int *fd_states_cap_ptr) {
    if (p_fd < 0) return;

    struct OrderFdState *fd_states = *fd_states_ptr;
    int fd_states_cap = *fd_states_cap_ptr;

    if (p_fd >= fd_states_cap) {
        int new_cap = p_fd + 128;
        struct OrderFdState *new_states = realloc(fd_states, new_cap * sizeof(struct OrderFdState));
        if (!new_states) return;
        memset(&new_states[fd_states_cap], 0, (new_cap - fd_states_cap) * sizeof(struct OrderFdState));
        *fd_states_ptr = new_states;
        *fd_states_cap_ptr = new_cap;
        fd_states = new_states;
    }

    struct OrderFdState *fs = &fd_states[p_fd];

    if (fs->heap_cap == 0) {
        fs->heap_cap = 64;
        fs->heap = malloc(fs->heap_cap * sizeof(struct IntervalNode));
    }

    if ((uint64_t)p_off <= fs->limit) {
        uint64_t new_end = (uint64_t)p_off + p_len;
        if (new_end > fs->limit) fs->limit = new_end;

        while (fs->heap_sz > 0 && fs->heap[0].s <= fs->limit) {
            struct IntervalNode top;
            interval_heap_pop(fs->heap, &fs->heap_sz, &top);
            if (top.e > fs->limit) fs->limit = top.e;
        }

        off_t aligned = (off_t)((fs->limit / 4096ULL) * 4096ULL);
        if (aligned > fs->last_punched) {
            fallocate(p_fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, fs->last_punched, aligned - fs->last_punched);
            fs->last_punched = aligned;
        }
    } else {
        interval_heap_push(&fs->heap, &fs->heap_sz, &fs->heap_cap, (uint64_t)p_off, (uint64_t)p_off + p_len);
    }
}

static int ring_order_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]);
  bool memfd_mode = (strcmp(argv[2], "memfd") == 0);
  const char *prefix = argv[2];
  bool unordered_mode = false;
  bool numa_mode = (global_num_nodes > 1);
  for (int i = 3; i < argc; i++) {
    if (strcmp(argv[i], "unordered") == 0) unordered_mode = true;
    if (strcmp(argv[i], "numa") == 0) numa_mode = true;
  }

  bool use_zerocopy = false;
  struct stat st_out;
  if (fstat(1, &st_out) == 0 && S_ISREG(st_out.st_mode)) use_zerocopy = true;

  int heap_cap = 1024;
  struct HeapNode *heap = malloc(heap_cap * sizeof(struct HeapNode));
  if (!heap) return EXECUTION_FAILURE;
  int heap_sz = 0;

  int fd_states_cap = 256;
  struct OrderFdState *fd_states = calloc(fd_states_cap, sizeof(struct OrderFdState));
  if (!fd_states) { free(heap); return EXECUTION_FAILURE; }

  uint32_t expected_major = 0, expected_minor = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct OrderPacket);

  bool stdout_broken = false;
  struct sigaction sa_ign, sa_old;
  sa_ign.sa_handler = SIG_IGN;
  sigemptyset(&sa_ign.sa_mask);
  sa_ign.sa_flags = 0;
  sigaction(SIGPIPE, &sa_ign, &sa_old);

  // NEW: Sync flag for Ordered Resume
  bool resume_synced = true;
  if (g_state && g_state->is_resume_mode) {
      resume_synced = false;
  }

  int tracker_cap = 1024;
  int tracker_sz = 0;
  struct IntervalNode *tracker_heap = malloc(tracker_cap * sizeof(struct IntervalNode));
  uint64_t tracker_horizon = 0;
  uint64_t tracker_bytes = 0;

  // NEW: Macro to absorb a successfully written batch into the Ledger
  #define TRACK_COMPLETED_BATCH(_op) do { \
      tracker_bytes += (_op).len; \
      uint64_t _s = (_op).in_off; \
      uint64_t _e = (_op).in_off + (_op).in_len; \
      if (_s <= tracker_horizon) { \
          if (_e > tracker_horizon) tracker_horizon = _e; \
          while (tracker_sz > 0 && tracker_heap[0].s <= tracker_horizon) { \
              struct IntervalNode top; \
              interval_heap_pop(tracker_heap, &tracker_sz, &top); \
              if (top.e > tracker_horizon) tracker_horizon = top.e; \
          } \
      } else { \
          interval_heap_push(&tracker_heap, &tracker_sz, &tracker_cap, _s, _e); \
      } \
      if (g_state) { \
          __atomic_add_fetch(&g_state->resume_seq, 1, __ATOMIC_ACQ_REL); \
          g_state->resume_horizon = tracker_horizon; \
          g_state->resume_stdout_bytes = tracker_bytes; \
          g_state->resume_jagged_count = (tracker_sz < 1024) ? tracker_sz : 1024; \
          for(uint32_t _i=0; _i<g_state->resume_jagged_count; _i++) g_state->resume_jagged[_i] = tracker_heap[_i]; \
          __atomic_add_fetch(&g_state->resume_seq, 1, __ATOMIC_RELEASE); \
      } \
  } while(0)

  while (1) {
    ssize_t n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break;

    buffered += n_read;

    size_t count = buffered / pkt_sz;
    struct OrderPacket *ops = (struct OrderPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct OrderPacket *op = &ops[i];
      uint32_t actual_minor = op->minor_idx & ~FLAG_MAJOR_EOF;
      uint64_t op_key = numa_mode ? PACK_KEY(op->major_idx, actual_minor) : op->major_idx;

      if (!unordered_mode) {
        heap_push(&heap, &heap_sz, &heap_cap, op_key, *op);

        // NEW: Dynamic Sequence Bootstrapping!
        // If we are resuming, wait for the packet that perfectly aligns with the horizon
        if (__builtin_expect(!resume_synced, 0)) {
            if (op->in_off == g_state->resume_horizon) {
                expected_major = op->major_idx;
                expected_minor = actual_minor;
                resume_synced = true;
            }
        }
      } else {
        if (memfd_mode) {
          off_t offset = (off_t)op->off;
          if (use_zerocopy) {
            if (robust_sendfile(1, op->fd, &offset, op->len) < 0) stdout_broken = true;
          } else {
            if (ring_copy_chunk(op->fd, 1, offset, op->len) < 0) stdout_broken = true;
          }
          if (stdout_broken) {
              pull_fire_alarm();
              break;
          }
          safe_hole_punch(op->fd, op->off, op->len, &fd_states, &fd_states_cap);
          TRACK_COMPLETED_BATCH(*op);

        } else {
          char path[256];
          if (numa_mode)
            snprintf(path, sizeof(path), "%s.%u.%u", prefix, op->major_idx,
                     actual_minor);
          else
            snprintf(path, sizeof(path), "%s.%u", prefix, op->major_idx);
          int fd_file = open(path, O_RDONLY);
          if (fd_file >= 0) {
            off_t offset = 0;
            struct stat st;
            if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
              if (robust_sendfile(1, fd_file, &offset, st.st_size) < 0) stdout_broken = true;
            }
            close(fd_file);
            unlink(path);
            if (stdout_broken) { pull_fire_alarm(); break; }
            TRACK_COMPLETED_BATCH(*op);
          }
        }
      }

      if (!unordered_mode && !stdout_broken && resume_synced) {
        while (heap_sz > 0) {
          uint64_t expected_key = numa_mode ? PACK_KEY(expected_major, expected_minor) : expected_major;
          if (heap[0].key != expected_key) break;
          struct HeapNode top;
          heap_pop(heap, &heap_sz, &top);
          if (memfd_mode) {
            off_t offset = (off_t)top.pkt.off;
            if (use_zerocopy) {
              if (robust_sendfile(1, top.pkt.fd, &offset, top.pkt.len) < 0) stdout_broken = true;
            } else {
              if (ring_copy_chunk(top.pkt.fd, 1, offset, top.pkt.len) < 0) stdout_broken = true;
            }
            if (stdout_broken) {
                pull_fire_alarm();
                break;
            }
            safe_hole_punch(top.pkt.fd, top.pkt.off, top.pkt.len, &fd_states, &fd_states_cap);
            TRACK_COMPLETED_BATCH(top.pkt);

          } else {
            char path[256];
            if (numa_mode)
              snprintf(path, sizeof(path), "%s.%u.%u", prefix,
                       top.pkt.major_idx,
                       (top.pkt.minor_idx & ~FLAG_MAJOR_EOF));
            else
              snprintf(path, sizeof(path), "%s.%u", prefix, top.pkt.major_idx);
            int fd_file = open(path, O_RDONLY);
            if (fd_file >= 0) {
              off_t offset = 0;
              struct stat st;
              if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                if (robust_sendfile(1, fd_file, &offset, st.st_size) < 0) stdout_broken = true;
              }
              close(fd_file);
              unlink(path);
              if (stdout_broken) { pull_fire_alarm(); break; }
              TRACK_COMPLETED_BATCH(top.pkt);
            }
          }
          if (numa_mode) {
            expected_minor += top.pkt.cnt;
            if (top.pkt.minor_idx & FLAG_MAJOR_EOF) { expected_major++; expected_minor = 0; }
          } else { expected_major += top.pkt.cnt; }
        }
      }
    }

    if (stdout_broken) {
        pull_fire_alarm();
        break; // Break outer read loop on SIGPIPE
    }

    size_t consumed = count * pkt_sz;
    if (consumed < buffered) memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    buffered -= consumed;
  }

  for (int i = 0; i < fd_states_cap; i++) {
      if (fd_states[i].heap) free(fd_states[i].heap);
  }
  free(fd_states);
  free(heap);
  free(tracker_heap);
  sigaction(SIGPIPE, &sa_old, NULL);
  return EXECUTION_SUCCESS;
}

static int ring_fallow_phys_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]);
  int fd_file = atoi(argv[2]);
  if (state) atomic_store_release(&state[0].fallow_active, 1);

  int heap_cap = 1024;
  int heap_sz = 0;
  struct IntervalNode *heap = malloc(heap_cap * sizeof(struct IntervalNode));
  uint64_t limit = 0;
  off_t last_punched = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct PhysPacket);
  ssize_t n_read = 0;

  while (1) {
    n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break;
    buffered += n_read;
    size_t count = buffered / pkt_sz;
    struct PhysPacket *ops = (struct PhysPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct PhysPacket *pp = &ops[i];
      if (pp->off <= limit) {
        uint64_t new_end = pp->off + pp->len;
        if (new_end > limit) limit = new_end;

        while (heap_sz > 0 && heap[0].s <= limit) {
          struct IntervalNode top;
          interval_heap_pop(heap, &heap_sz, &top);
          if (top.e > limit) limit = top.e;
        }
        off_t aligned = (off_t)((limit / 4096ULL) * 4096ULL);
        if (aligned > last_punched) {
          fallocate(fd_file, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, last_punched, aligned - last_punched);
          last_punched = aligned;
        }
      } else {
        interval_heap_push(&heap, &heap_sz, &heap_cap, pp->off, pp->off + pp->len);
      }
      if (g_state) g_state->fallow_horizon_bytes = limit;
    }
    size_t consumed = count * pkt_sz;
    if (consumed < buffered) memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    buffered -= consumed;
  }

  free(heap);
  if (state) atomic_store_release(&state[0].fallow_active, 0);

  // PHYSICS FIX: Only pull the fire alarm if Fallow died abnormally
  if (n_read < 0) pull_fire_alarm();

  return EXECUTION_SUCCESS;
}

// ==============================================================================
// 8. UTILITY LOADABLES
// ==============================================================================

static int ring_worker_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  if (my_numa_node == -1) {
    const char *s_node = get_string_value("RING_NODE_ID");
    if (s_node)
      my_numa_node = atoi(s_node);
    else {
      int phys = auto_detect_numa_node();
      my_numa_node = 0;
      if (g_logical_to_phys_map) {
        for (uint32_t i = 0; i < global_num_nodes; i++) {
          if (g_logical_to_phys_map[i] == (uint32_t)phys) {
            my_numa_node = i;
            break;
          }
        }
      }
    }
    if (my_numa_node >= (int)global_num_nodes)
      my_numa_node = 0;
  }
  int node = my_numa_node;

  if (!strcmp(argv[1], "inc")) {
    // CHANGED: Trigger pinning for explicit map even if nodes == 1
    if ((global_num_nodes > 1 || g_explicit_pinning) && g_logical_to_phys_map) {
      if (pin_to_numa_node(g_logical_to_phys_map[node]) != 0 && g_debug) {
      }
    }
    __atomic_fetch_add(&state[node].active_workers, 1, __ATOMIC_SEQ_CST);
  } else if (!strcmp(argv[1], "dec")) {
    cleanup_waiter_state();
    __atomic_fetch_sub(&state[node].active_workers, 1, __ATOMIC_SEQ_CST);
  }
  return EXECUTION_SUCCESS;
}

static int ring_cleanup_waiter_main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  cleanup_waiter_state();
  return EXECUTION_SUCCESS;
}
static int ring_ingest_main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  if (state)
    atomic_store_release(&state[0].ingest_complete, 1);
  return EXECUTION_SUCCESS;
}
static int ring_lseek_main(int argc, char **argv) {
  if (argc < 3 || argc > 5)
    return EXECUTION_FAILURE;
  int fd = atoi(argv[1]);

  // ZERO-OVERHEAD TLS INJECTION: Support '-' to auto-grab the batch offset
  off_t off;
  if (argv[2][0] == '-' && argv[2][1] == '\0') {
    off = tls_batch_offset;
  } else {
    off = atoll(argv[2]);
  }

  int whence = SEEK_CUR;
  if (argc > 3) {
    if (!strcmp(argv[3], "SEEK_SET"))
      whence = SEEK_SET;
    else if (!strcmp(argv[3], "SEEK_END"))
      whence = SEEK_END;
  }
  off_t no = lseek(fd, off, whence);
  if (no == -1)
    return EXECUTION_FAILURE;
  if (argc >= 4 && argv[argc - 1][0]) {
    char buf[32];
    snprintf(buf, 32, "%lld", (long long)no);
    bind_var_or_array(argv[argc - 1], buf, 0);
  } else if (argc < 4) {
    printf("%lld\n", (long long)no);
  }
  return EXECUTION_SUCCESS;
}

static int ring_memfd_create_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  int fd = xcreate_anon_file("forkrun_input");
  if (fd < 0) {
    builtin_error("memfd_create failed: %s", strerror(errno));
    return EXECUTION_FAILURE;
  }
  char val[32];
  snprintf(val, sizeof(val), "%d", fd);
  bind_var_or_array(argv[1], val, 0);
  return EXECUTION_SUCCESS;
}

static int ring_seal_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  if (fcntl(atoi(argv[1]), F_ADD_SEALS,
            F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE) == -1)
    return EXECUTION_FAILURE;
  return EXECUTION_SUCCESS;
}

static int ring_fcntl_main(int argc, char **argv) {
  if (argc < 3)
    return EXECUTION_FAILURE;
  int fd = atoi(argv[1]);
  const char *cmd = argv[2];
  if (strcmp(cmd, "shutdown_w") == 0)
    shutdown(fd, SHUT_WR);
  else if (strcmp(cmd, "shutdown_r") == 0)
    shutdown(fd, SHUT_RD);
  else if (strcmp(cmd, "shutdown_rw") == 0)
    shutdown(fd, SHUT_RDWR);
  else if (strcmp(cmd, "close") == 0)
    close(fd);
  else {
    builtin_error("unknown command: %s", cmd);
    return EXECUTION_FAILURE;
  }
  return EXECUTION_SUCCESS;
}

static int ring_pipe_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  int pfd[2];
  if (pipe(pfd) < 0) {
    builtin_error("pipe failed: %s", strerror(errno));
    return EXECUTION_FAILURE;
  }
  fcntl(pfd[1], F_SETPIPE_SZ, 1048576);

  // PHYSICS FIX: Get the ACTUAL size granted by the kernel and export it
  // dynamically
  int pipe_cap = 65536;
  int ret = fcntl(pfd[1], F_GETPIPE_SZ);
  if (ret > 0)
    pipe_cap = ret;

  char buf[32];
  snprintf(buf, sizeof(buf), "%d", pipe_cap);
  bind_variable("RING_PIPE_CAPACITY_CUR", buf, 0);

  if (argc == 2) {
    const char *arr_name = argv[1];
    SHELL_VAR *v = find_variable(arr_name);
    if (v && !array_p(v)) {
      unbind_variable(arr_name);
      v = NULL;
    }
    if (!v)
      v = make_new_array_variable(arr_name);
    if (!v) {
      close(pfd[0]);
      close(pfd[1]);
      return EXECUTION_FAILURE;
    }
    snprintf(buf, sizeof(buf), "%d", pfd[0]);
    bind_array_element(v, 0, buf, 0);
    snprintf(buf, sizeof(buf), "%d", pfd[1]);
    bind_array_element(v, 1, buf, 0);
  } else {
    snprintf(buf, sizeof(buf), "%d", pfd[0]);
    bind_var_or_array(argv[1], buf, 0);
    snprintf(buf, sizeof(buf), "%d", pfd[1]);
    bind_var_or_array(argv[2], buf, 0);
  }
  return EXECUTION_SUCCESS;
}

static int ring_splice_main(int argc, char **argv) {
  if (argc < 5)
    return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]);
  int fd_out = atoi(argv[2]);
  off_t off = 0;
  off_t *p_off = NULL;
  if (argv[3][0] != '\0') {
    if (argv[3][0] == '-' && argv[3][1] == '\0') {
      p_off = &tls_batch_offset;
    } else {
      off_t parsed = (off_t)atoll(argv[3]);
      if (parsed != -1) {
        off = parsed;
        p_off = &off;
      }
    }
  }
  size_t len = (size_t)atoll(argv[4]);
  bool close_out = (argc > 5 && strcmp(argv[5], "close") == 0);
  fcntl(fd_out, F_SETPIPE_SZ, 1048576);
  size_t written = 0;

  // PHYSICS FIX: Shield the worker process from kernel assassination if the
  // command exits early.
  struct sigaction sa_ign, sa_old;
  sa_ign.sa_handler = SIG_IGN;
  sigemptyset(&sa_ign.sa_mask);
  sa_ign.sa_flags = 0;
  sigaction(SIGPIPE, &sa_ign, &sa_old);

  while (written < len) {
    // PHYSICS FIX: Removed SPLICE_F_MOVE and SPLICE_F_MORE.
    // SPLICE_F_MOVE attempts to detach pages from the tmpfs page cache.
    // When ring_fallow concurrently calls fallocate(PUNCH_HOLE) on the same
    // memfd, it causes a catastrophic kernel-level lock inversion / deadlock on
    // the inode/page locks.
    ssize_t s = splice(fd_in, p_off, fd_out, NULL, len - written, 0);

    if (s < 0) {
      if (errno == EINTR)
        continue;
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        struct pollfd pfd = {.fd = fd_out, .events = POLLOUT};
        poll(&pfd, 1, -1);
        continue;
      }
      if (errno == EPIPE) {
        if (close_out)
          close(fd_out);
        sigaction(SIGPIPE, &sa_old, NULL);
        return EXECUTION_SUCCESS;
      }
      if (errno == ENOSPC || errno == ENOMEM) {
        usleep(10000); // 10ms wait for fallow to punch holes
        continue;
      }
      if (close_out)
        close(fd_out);
      builtin_error("splice failed: %s", strerror(errno));
      sigaction(SIGPIPE, &sa_old, NULL);
      return EXECUTION_FAILURE;
    }
    if (s == 0)
      break;
    written += s;
  }
  if (close_out)
    close(fd_out);
  sigaction(SIGPIPE, &sa_old, NULL);
  return EXECUTION_SUCCESS;
}

static int ring_indexer_main(int argc, char **argv) {
  if (argc < 4)
    return EXECUTION_FAILURE;
  int fd_data = atoi(argv[1]);
  int fd_pipe = atoi(argv[2]);
  int fd_sig = atoi(argv[3]);
  size_t chunk_target = get_optimal_chunk_size() * 2;
  uint64_t current_pos = 0;
  char tail_buf[65536];
  struct pollfd pfds[1] = {{.fd = fd_sig, .events = POLLIN}};
  while (1) {
    struct stat st;
    if (fstat(fd_data, &st) < 0)
      break;
    uint64_t available = (uint64_t)st.st_size;
    while (available >= current_pos + chunk_target) {
      uint64_t scan_end = current_pos + chunk_target;
      size_t scan_sz =
          (sizeof(tail_buf) < chunk_target) ? sizeof(tail_buf) : chunk_target;
      ssize_t n = pread(fd_data, tail_buf, scan_sz, scan_end - scan_sz);
      if (n > 0) {
        char *nl = memrchr(tail_buf, state[0].cfg_delim, n);
        if (nl) {
          uint64_t actual_end = (scan_end - scan_sz) + (nl - tail_buf) + 1;
          struct PhysPacket pp = {.off = current_pos,
                                  .len = actual_end - current_pos};
          if (robust_pipe_write(fd_pipe, &pp, sizeof(pp)) < 0)
            return EXECUTION_FAILURE;
          current_pos = actual_end;
          continue;
        }
      }
      struct PhysPacket pp = {.off = current_pos, .len = chunk_target};
      if (robust_pipe_write(fd_pipe, &pp, sizeof(pp)) < 0)
        return EXECUTION_FAILURE;
      current_pos += chunk_target;
    }

    // PHYSICS FIX: 10ms instead of 100ms stat fallback
    if (poll(pfds, 1, 10) > 0) {
      uint64_t v;
      if (sys_read(fd_sig, &v, 8) > 0) {
        // WORMHOLE FIX 5: Legacy Indexer EOF Race Shield
        // Ensure we process any final bytes written between our last stat and this signal.
        if (fstat(fd_data, &st) == 0) {
          uint64_t final_avail = (uint64_t)st.st_size;
          if (final_avail > current_pos) {
            struct PhysPacket pp = {.off = current_pos, .len = final_avail - current_pos};
            robust_pipe_write(fd_pipe, &pp, sizeof(pp));
          }
        }
        break;
      }
    }
  }
  return EXECUTION_SUCCESS;
}

static int ring_fetcher_main(int argc, char **argv) {
  if (argc < 6)
    return EXECUTION_FAILURE;
  int fd_pipe = atoi(argv[1]);
  int fd_global = atoi(argv[2]);
  int fd_local = atoi(argv[3]);
  int fd_local_sig = atoi(argv[4]);
  int fd_global_ack = atoi(argv[5]);
  int fd_token_in = (argc > 6) ? atoi(argv[6]) : -1;
  struct PhysPacket pp;
  while (1) {
    if (fd_token_in >= 0) {
      char t;
      if (sys_read(fd_token_in, &t, 1) <= 0)
        break;
    }
    if (robust_pipe_read(fd_pipe, &pp, sizeof(pp), true) <= 0)
      break;
    loff_t off_in = (loff_t)pp.off;
    loff_t off_out = lseek(fd_local, 0, SEEK_END);
    ssize_t ret =
        copy_file_range(fd_global, &off_in, fd_local, &off_out, pp.len, 0);
    if (ret < 0) {
      char *buf = malloc(65536);
      uint64_t copied = 0;
      lseek(fd_global, pp.off, SEEK_SET);
      lseek(fd_local, 0, SEEK_END);
      while (copied < pp.len) {
        size_t to_read = (pp.len - copied > 65536) ? 65536 : (pp.len - copied);
        ssize_t r = sys_read(fd_global, buf, to_read);
        if (r <= 0) {
          break;
        }
        char *wptr = buf;
        ssize_t wleft = r;
        while (wleft > 0) {
          ssize_t w = sys_write(fd_local, wptr, wleft);
          if (w <= 0) {
            break;
          }
          wptr += w;
          wleft -= w;
        }
        copied += r;
      }
      free(buf);
    }
    uint64_t one = 1;
    sys_write(fd_local_sig, &one, 8);
    robust_pipe_write(fd_global_ack, &pp, sizeof(pp));
  }
  return EXECUTION_SUCCESS;
}

// ==============================================================================
// ZERO COPY INGEST (UMA / Flat Mode)
// ==============================================================================

static int ring_copy_main(int argc, char **argv) {
  if (argc < 2)
    return EXECUTION_FAILURE;
  int outfd = atoi(argv[1]);
  int infd = (argc == 3) ? atoi(argv[2]) : 0;
  size_t chunk = get_optimal_chunk_size();
  struct stat st;
  uint64_t oom_threshold = 134217728;
  long threshold_div = 128;
  const char *s_div = get_string_value("RING_INGEST_DIVISOR");
  if (s_div) {
    long v = atol(s_div);
    if (v > 0)
      threshold_div = v;
  }
  struct sysinfo si_init;
  if (sysinfo(&si_init) == 0) {
    uint64_t mu = (uint64_t)si_init.mem_unit ? si_init.mem_unit : 1;
    oom_threshold = ((uint64_t)si_init.totalram * mu) / (uint64_t)threshold_div;
  }
  uint64_t total_moved = 0;
  uint64_t next_check = 16 * 1024 * 1024;
  off_t off = 0;
  bool use_bounce = true;
  bool limit_reached_exit = false;

  if (g_explicit_pinning && g_logical_to_phys_map) {
    uint32_t target_phys = g_logical_to_phys_map[0];
    int mask_words = (target_phys / (sizeof(unsigned long) * 8)) + 1;
    unsigned long *nodemask = calloc(mask_words, sizeof(unsigned long));
    if (nodemask) {
      nodemask[target_phys / (sizeof(unsigned long) * 8)] |=
          (1UL << (target_phys % (sizeof(unsigned long) * 8)));
      syscall(__NR_set_mempolicy, MPOL_BIND, nodemask,
              mask_words * sizeof(unsigned long) * 8);
      free(nodemask);
    }
  }

  if (fstat(infd, &st) == 0) {
    if (S_ISFIFO(st.st_mode)) {
      fcntl(infd, F_SETPIPE_SZ, 1048576); // Expand pipe to 1MB
    }
    if (S_ISREG(st.st_mode) && st.st_size > 0) {
      while (off < st.st_size) {
        // EMERGENCY BYPASS: Check fire alarm before scanner_finished
        if (state && atomic_load_relaxed(&state[0].emergency_abort)) {
            limit_reached_exit = true;
            off = st.st_size;
            use_bounce = false;
            break;
        }
        if (state[0].cfg_limit > 0 && atomic_load_acquire(&state[0].scanner_finished)) {
            limit_reached_exit = true;
            off = st.st_size;
            use_bounce = false;
            break;
        }
        check_memory_pressure(&total_moved, &next_check, oom_threshold);
        loff_t current_off = off;
        size_t to_copy = (size_t)(st.st_size - off);
        if (to_copy > chunk)
          to_copy = chunk;
        size_t copied_in_chunk = 0;
        while (copied_in_chunk < to_copy) {
          if (atomic_load_acquire(&state[0].scanner_finished)) {
              limit_reached_exit = true;
              break;
          }
          ssize_t n = copy_file_range(infd, &current_off, outfd, NULL,
                                      to_copy - copied_in_chunk, 0);
          if (n < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
              continue;
            if (errno == ENOSPC || errno == ENOMEM) {
              usleep(10000);
              continue;
            }
            if (errno == EXDEV || errno == EINVAL || errno == ENOSYS ||
                errno == EOPNOTSUPP)
              break;
            goto err_out;
          }
          if (n == 0)
            break;
          copied_in_chunk += n;
        }
        if (copied_in_chunk == 0 && (st.st_size - off > 0))
          break;
        off += copied_in_chunk;
        if (evfd_ingest_data >= 0) {
          uint64_t v = 1;
          sys_write(evfd_ingest_data, &v, 8);
        }
        total_moved += copied_in_chunk;
      atomic_store_relaxed(&state[0].uma_ingest_offset, total_moved);
      }
      while (off < st.st_size && !limit_reached_exit) {
        if (state && atomic_load_relaxed(&state[0].emergency_abort)) {
            limit_reached_exit = true;
            use_bounce = false;
            break;
        }
        if (state[0].cfg_limit > 0 && atomic_load_acquire(&state[0].scanner_finished)) {
            limit_reached_exit = true;
            use_bounce = false;
            break;
        }
        check_memory_pressure(&total_moved, &next_check, oom_threshold);
        ssize_t n = sendfile(outfd, infd, &off, chunk);
        if (n < 0) {
          if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
            continue;
          if (errno == ENOSPC || errno == ENOMEM) {
            usleep(10000);
            continue;
          }
          break;
        }
        if (n == 0)
          break;
        if (evfd_ingest_data >= 0) {
          uint64_t v = 1;
          sys_write(evfd_ingest_data, &v, 8);
        }
        total_moved += n;
        atomic_store_relaxed(&state[0].uma_ingest_offset, total_moved);
      }
      if (off >= st.st_size)
        use_bounce = false;
    }
  }

  if (use_bounce && !limit_reached_exit) {
    char *bounce_buf = mmap(NULL, chunk, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (bounce_buf == MAP_FAILED)
      goto err_out;

    while (1) {
      // EMERGENCY BYPASS: Check fire alarm before scanner_finished
      if (state && atomic_load_relaxed(&state[0].emergency_abort)) break;
      if (state[0].cfg_limit > 0 && atomic_load_acquire(&state[0].scanner_finished)) break;

      struct pollfd pfd_in = {.fd = infd, .events = POLLIN};
      int p_res = poll(&pfd_in, 1, 10);
      if (p_res <= 0) {
          if (p_res < 0 && errno != EINTR && errno != EAGAIN) break;
          if (atomic_load_acquire(&state[0].scanner_finished)) {
              limit_reached_exit = true;
              break;
          }
          continue;
      }

      if (!(pfd_in.revents & (POLLIN | POLLHUP | POLLERR))) {
          continue;
      }

      ssize_t r = read(infd, bounce_buf, chunk);
      if (r < 0) {
        if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
          continue;
        break;
      }
      if (r == 0)
        break;

      size_t written = 0;
      bool inner_fatal = false;
      while (written < (size_t)r) {
        ssize_t w = write(outfd, bounce_buf + written, r - written);
        if (w <= 0) {
          if (w < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
              struct pollfd pfd_out = {.fd = outfd, .events = POLLOUT};
              int p_out_res = poll(&pfd_out, 1, 10);
              if (p_out_res < 0) {
                  if (errno == EINTR || errno == EAGAIN) continue;
                  if (errno == ENOMEM) {
                      usleep(10000); // Do NOT break on ENOMEM
                      continue;
                  }
                  inner_fatal = true; // Hard unrecoverable error
                  break;
              }
              if (atomic_load_acquire(&state[0].scanner_finished)) {
                 limit_reached_exit = true;
                 break;
              }
            } else {
              usleep(10);
            }
            continue;
          }
          if (w < 0 && (errno == ENOSPC || errno == ENOMEM)) {
            usleep(10000);
            continue;
          }
          inner_fatal = true; // Hard unrecoverable error
          break;
        }
        written += w;
      }
      if (limit_reached_exit || inner_fatal)
        break;

      if (evfd_ingest_data >= 0) {
        uint64_t v = 1;
        sys_write(evfd_ingest_data, &v, 8);
      }
      total_moved += written;
      atomic_store_relaxed(&state[0].uma_ingest_offset, total_moved);
      check_memory_pressure(&total_moved, &next_check, oom_threshold);
    }
    munmap(bounce_buf, chunk);
  }

  if (evfd_ingest_eof >= 0) {
    uint64_t val = 999999;
    sys_write(evfd_ingest_eof, &val, 8);
  }
  if (state) atomic_store_release(&state[0].ingest_complete, 1);
  if (g_explicit_pinning) {
    syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);
  }
  return EXECUTION_SUCCESS;

err_out:
  if (evfd_ingest_eof >= 0) {
    uint64_t val = 999999;
    sys_write(evfd_ingest_eof, &val, 8);
  }
  if (state) atomic_store_release(&state[0].ingest_complete, 1);
  if (g_explicit_pinning) {
    syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);
  }
  return EXECUTION_FAILURE;
}

static int ring_signal_main(int argc, char **argv) {
  int fd = evfd_ingest_eof;
  if (argc >= 2)
    fd = atoi(argv[1]);
  uint64_t val = 1;
  SYS_CHK(write(fd, &val, 8));
  return EXECUTION_SUCCESS;
}

// Memory Reclamation (Entropy Export / Fallow):
// The `ring_fallow` thread continuously monitors which offsets have been
// universally processed and acknowledged across all workers. It then punches
// holes in the backing memfd via `fallocate(FALLOC_FL_PUNCH_HOLE)`. This frees
// physical memory back to the OS without breaking the absolute integer scale of
// the offset coordinates.
static int ring_fallow_main(int argc, char **argv) {
  if (argc < 3) return EXECUTION_FAILURE;
  int fd_in = atoi(argv[1]);
  int fd_file = atoi(argv[2]);
  bool dry_run = (argc > 3 && strcmp(argv[3], "dry") == 0);
  if (state) atomic_store_release(&state[0].fallow_active, 1);

  int heap_cap = 1024;
  int heap_sz = 0;
  struct IntervalNode *heap = malloc(heap_cap * sizeof(struct IntervalNode));
  uint64_t next_idx = 0;
  off_t last_punched = 0;

  char pkt_buf[4096];
  size_t buffered = 0;
  size_t pkt_sz = sizeof(struct IndexPacket);
  ssize_t n_read = 0;

  while (1) {
    n_read = robust_pipe_read(fd_in, pkt_buf + buffered, sizeof(pkt_buf) - buffered, false);
    if (n_read <= 0) break; // Workers dead or normal EOF
    buffered += n_read;

    size_t count = buffered / pkt_sz;
    struct IndexPacket *ops = (struct IndexPacket *)pkt_buf;

    for (size_t i = 0; i < count; i++) {
      struct IndexPacket *ip = &ops[i];
      if (ip->idx <= next_idx) {
        uint64_t new_end = ip->idx + ip->cnt;
        if (new_end > next_idx) next_idx = new_end;

        while (heap_sz > 0 && heap[0].s <= next_idx) {
          struct IntervalNode top;
          interval_heap_pop(heap, &heap_sz, &top);
          if (top.e > next_idx) next_idx = top.e;
        }

        if (state) atomic_store_release(&state[0].min_idx, next_idx);
        if (!dry_run) {
          uint64_t byte_limit = state[0].offset_ring[next_idx & RING_MASK];
          if (g_state) g_state->fallow_horizon_bytes = byte_limit;
          off_t aligned = (off_t)((byte_limit / 4096ULL) * 4096ULL);
          if (aligned > last_punched) {
            fallocate(fd_file, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, last_punched, aligned - last_punched);
            last_punched = aligned;
          }
        }
      } else {
        interval_heap_push(&heap, &heap_sz, &heap_cap, ip->idx, ip->idx + ip->cnt);
      }
    }

    size_t consumed = count * pkt_sz;
    if (consumed < buffered) memmove(pkt_buf, pkt_buf + consumed, buffered - consumed);
    buffered -= consumed;
  }

  free(heap);
  if (state) atomic_store_release(&state[0].fallow_active, 0);

  // PHYSICS FIX: Only pull the fire alarm if Fallow died abnormally (e.g. SIGPIPE)
  // If it exited cleanly (n_read == 0), the pipeline completed successfully!
  if (n_read < 0) pull_fire_alarm();

  return EXECUTION_SUCCESS;
}

// ==============================================================================
// TRANSACTION ROLLBACK: Erase partial output from a corrupted batch
// ==============================================================================
static int ring_revert_output_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    if (fd >= 0) {
        if (ftruncate(fd, last_ack_offset) == -1) return EXECUTION_FAILURE;
        if (lseek(fd, last_ack_offset, SEEK_SET) == (off_t)-1) return EXECUTION_FAILURE;
    }
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// ACK SYNC: Synchronize output offset for a fresh worker taking over a slot
// ==============================================================================
static int ring_ack_init_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd = atoi(argv[1]);
    if (fd >= 0) {
        last_ack_offset = lseek(fd, 0, SEEK_CUR);
    }
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// ESCROW RECOVERY: Explicitly deposit a failed batch into the escrow channel
// ==============================================================================
static int ring_escrow_put_main(int argc, char **argv) {
    if (argc < 5) return EXECUTION_FAILURE;
    int node = atoi(argv[1]);
    uint64_t idx;
    if (argv[2][0] == '-' && argv[2][1] == '\0') idx = worker_last_idx;
    else idx = strtoull(argv[2], NULL, 10);

    uint64_t cnt;
    if (argv[3][0] == '-' && argv[3][1] == '\0') cnt = worker_last_cnt;
    else cnt = strtoull(argv[3], NULL, 10);
    uint32_t kills = (uint32_t)atoi(argv[4]);

    if (node < 0 || node >= (int)global_num_nodes) node = 0;

    struct EscrowPacket ep = { .idx = idx, .cnt = cnt, .num_kills = kills };

    if (fd_escrow_w && fd_escrow_w[node] >= 0) {
        if (robust_pipe_write(fd_escrow_w[node], &ep, sizeof(ep)) == sizeof(ep)) {
            // Signal workers to re-arm tl_drain_escrow on their next iteration.
            __atomic_store_n(&state[node].escrow_pending, 1, __ATOMIC_RELEASE);
            return EXECUTION_SUCCESS;
        }
        return EXECUTION_FAILURE;
    }
    return EXECUTION_SUCCESS;
}


// Qsort helper for the exporter
static int cmp_interval(const void *a, const void *b) {
    uint64_t sa = ((struct IntervalNode *)a)->s;
    uint64_t sb = ((struct IntervalNode *)b)->s;
    return (sa < sb) ? -1 : ((sa > sb) ? 1 : 0);
}

static int ring_dump_resume_main(int argc, char **argv) {
    if (!g_state) return EXECUTION_FAILURE;

    // NEW: Safe Seqlock read into local variables
    uint32_t seq1, seq2;
    uint64_t snap_horizon, snap_bytes;
    uint32_t snap_count;
    struct IntervalNode snap_jagged[1024];

    do {
        seq1 = __atomic_load_n(&g_state->resume_seq, __ATOMIC_ACQUIRE);
        snap_horizon = g_state->resume_horizon;
        snap_bytes = g_state->resume_stdout_bytes;
        snap_count = atomic_load_relaxed(&g_state->resume_jagged_count);
        for (uint32_t i = 0; i < snap_count; i++) snap_jagged[i] = g_state->resume_jagged[i];
        seq2 = __atomic_load_n(&g_state->resume_seq, __ATOMIC_ACQUIRE);
    } while (seq1 != seq2 || (seq1 & 1));

    if (argc >= 2 && strcmp(argv[1], "bytes") == 0) {
        printf("%llu\n", (unsigned long long)snap_bytes);
        return EXECUTION_SUCCESS;
    }

    uint64_t horiz = snap_horizon;
    if (horiz == 0 && g_state->fallow_horizon_bytes > 0) {
        horiz = g_state->fallow_horizon_bytes; // Fallback for -u mode!
    }

    printf("FORKRUN_RESUME_HORIZON=%llu\n", (unsigned long long)horiz);
    printf("FORKRUN_RESUME_STDOUT_BYTES=%llu\n", (unsigned long long)snap_bytes);

    // Sort the jagged edge
    int n = snap_count;
    struct IntervalNode sorted[1024];
    for (int i = 0; i < n; i++) sorted[i] = snap_jagged[i];
    qsort(sorted, n, sizeof(struct IntervalNode), cmp_interval);

    // NEW: Collapse continuous/overlapping intervals
    struct IntervalNode collapsed[1024];
    int c_idx = 0;
    if (n > 0) {
        collapsed[0] = sorted[0];
        for (int i = 1; i < n; i++) {
            if (sorted[i].s <= collapsed[c_idx].e) { // Contiguous or overlapping
                if (sorted[i].e > collapsed[c_idx].e) {
                    collapsed[c_idx].e = sorted[i].e;
                }
            } else {
                c_idx++;
                collapsed[c_idx] = sorted[i];
            }
        }
        c_idx++; // Convert index to count
    }

    printf("FORKRUN_RESUME_JAGGED=(");
    for (int i = 0; i < c_idx; i++) {
        printf("\"%llu:%llu\" ", (unsigned long long)collapsed[i].s, (unsigned long long)collapsed[i].e);
    }
    printf(")\n");
    return EXECUTION_SUCCESS;
}

static int ring_set_resume_main(int argc, char **argv) {
    if (!g_state || argc < 2) return EXECUTION_FAILURE;
    g_state->is_resume_mode = 1;
    g_state->resume_horizon = strtoull(argv[1], NULL, 10);
    g_state->resume_jagged_count = 0;

    for (int i = 2; i < argc && g_state->resume_jagged_count < 1024; i++) {
        char *colon = strchr(argv[i], ':');
        if (colon) {
            *colon = '\0';
            g_state->resume_jagged[g_state->resume_jagged_count].s = strtoull(argv[i], NULL, 10);
            g_state->resume_jagged[g_state->resume_jagged_count].e = strtoull(colon + 1, NULL, 10);
            g_state->resume_jagged_count++;
        }
    }
    return EXECUTION_SUCCESS;
}

// Emergency Abort Trigger
static int ring_abort_main(int argc, char **argv) {
    (void)argc; (void)argv;
    pull_fire_alarm();
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// EVENT MULTIPLEXER (The "Death Pipe" Reactor)
// ==============================================================================
#ifndef element_forw
#define element_forw(a) ((a)->next)
#define element_index(a) ((a)->ind)
#define element_value(a) ((a)->value)
#endif

struct PollMeta {
    arrayind_t id;
    int type; // 0 = spawn, 1 = scanner, 2 = worker, 3 = trap_ack
};

static uint64_t g_poll_deadline_ms = 0;

static inline uint64_t get_mono_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)ts.tv_nsec / 1000000ULL;
}

static int ring_poll_main(int argc, char **argv) {
    if (argc < 4) return EXECUTION_FAILURE;
    int fd_spawn_r = atoi(argv[1]);
    const char *scan_arr_name = argv[2];
    const char *work_arr_name = argv[3];

    // Optional 4th arg: timer command.
    if (argc >= 5 && argv[4][0] != '\0') {
        int timer_arg = atoi(argv[4]);
        if (timer_arg > 0) {
            g_poll_deadline_ms = get_mono_ms() + (uint64_t)timer_arg;
        } else if (timer_arg < 0) {
            g_poll_deadline_ms = 0;
        }
    }

    // Optional 5th arg: trap ack pipe
    int fd_trap_ack_r = (argc >= 6 && argv[5][0] != '\0') ? atoi(argv[5]) : -1;

    int max_poll = 8192;
    struct pollfd *pfds = malloc(max_poll * sizeof(struct pollfd));
    if (!pfds) return EXECUTION_FAILURE;
    struct PollMeta *meta = malloc(max_poll * sizeof(struct PollMeta));
    if (!meta) { free(pfds); return EXECUTION_FAILURE; }

    int p_cnt = 0;
    int core_cnt = 0; // Tracks FDs that keep the loop alive

    // 1. Load the Spawn Pipe
    if (fd_spawn_r >= 0) {
        pfds[p_cnt].fd = fd_spawn_r;
        pfds[p_cnt].events = POLLIN;
        meta[p_cnt].id = -1;
        meta[p_cnt].type = 0;
        p_cnt++;
        core_cnt++;
    }

    // 2. Load the Trap Ack Pipe
    if (fd_trap_ack_r >= 0) {
        pfds[p_cnt].fd = fd_trap_ack_r;
        pfds[p_cnt].events = POLLIN;
        meta[p_cnt].id = -1;
        meta[p_cnt].type = 3;
        p_cnt++;
        // Do NOT increment core_cnt. Trap ack pipe alone shouldn't prevent shutdown.
    }

    // Helper macro to load Bash arrays dynamically
    #define LOAD_ARRAY(arr_name, type_val) \
        do { \
            SHELL_VAR *v = find_variable(arr_name); \
            if (v && array_p(v)) { \
                ARRAY *arr = array_cell(v); \
                if (arr) { \
                    ARRAY_ELEMENT *ae; \
                    for (ae = element_forw(arr->head); ae != arr->head; ae = element_forw(ae)) { \
                        if (p_cnt >= max_poll) break; \
                        char *val = element_value(ae); \
                        if (val && val[0]) { \
                            pfds[p_cnt].fd = atoi(val); \
                            pfds[p_cnt].events = POLLHUP | POLLIN | POLLERR; \
                            meta[p_cnt].id = element_index(ae); \
                            meta[p_cnt].type = type_val; \
                            p_cnt++; \
                            core_cnt++; \
                        } \
                    } \
                } \
            } \
        } while(0)

    // 3. Load Scanner and Worker Death Pipes
    LOAD_ARRAY(scan_arr_name, 1);
    LOAD_ARRAY(work_arr_name, 2);

    // If there is no core infrastructure left to poll, exit
    if (core_cnt == 0 && g_poll_deadline_ms == 0) {
        free(pfds); free(meta);
        return EXECUTION_FAILURE;
    }

    int r;
    do {
        if (state && atomic_load_relaxed(&state[0].emergency_abort)) {
            free(pfds); free(meta);
            return EXECUTION_FAILURE;
        }

        int timeout_this_iter = 100; // 100ms default for fire alarm checks
        if (g_poll_deadline_ms > 0) {
            uint64_t now_ms = get_mono_ms();
            if (now_ms >= g_poll_deadline_ms) {
                g_poll_deadline_ms = 0;
                bind_variable("POLL_EVENT", "TIMEOUT", 0);
                free(pfds); free(meta);
                return EXECUTION_SUCCESS;
            }
            uint64_t remaining_ms = g_poll_deadline_ms - now_ms;
            timeout_this_iter = (remaining_ms < 100) ? (int)remaining_ms : 100;
            if (timeout_this_iter < 1) timeout_this_iter = 1;
        }

        r = poll(pfds, p_cnt, timeout_this_iter);
    } while (r == 0 || (r < 0 && errno == EINTR));

    if (r < 0) {
        free(pfds); free(meta);
        return EXECUTION_FAILURE;
    }

    // 4. Process the Events
    for (int i = 0; i < p_cnt; i++) {
        if (pfds[i].revents & (POLLIN | POLLHUP | POLLERR)) {
            if (meta[i].type == 0 || meta[i].type == 3) {
                // --- SPAWN or TRAP_ACK PIPE (1-byte robust read) ---
                char buf[64];
                int len = 0;
                bool eof = false;
                while (len < (int)sizeof(buf) - 1) {
                    char c;
                    ssize_t n = read(pfds[i].fd, &c, 1);
                    if (n > 0) {
                        if (c == '\n') break;
                        buf[len++] = c;
                    } else if (n == 0) {
                        eof = true;
                        break;
                    } else {
                        if (errno == EINTR) continue;
                        break; // EAGAIN or error
                    }
                }
                buf[len] = '\0';

                if (len > 0) {
                    if (meta[i].type == 0) {
                        char *colon = strchr(buf, ':');
                        int node = 0, count = 0;
                        if (colon) {
                            *colon = '\0';
                            node = atoi(buf);
                            count = atoi(colon + 1);
                        } else {
                            count = atoi(buf);
                        }
                        bind_variable("POLL_EVENT", "SPAWN", 0);
                        char arg_buf[32];
                        snprintf(arg_buf, sizeof(arg_buf), "%d", count);
                        bind_variable("POLL_ARG1", arg_buf, 0);
                        snprintf(arg_buf, sizeof(arg_buf), "%d", node);
                        bind_variable("POLL_ARG2", arg_buf, 0);
                    } else {
                        bind_variable("POLL_EVENT", "TRAP_ACK", 0);
                        bind_variable("POLL_ARG1", buf, 0);
                    }
                    free(pfds); free(meta);
                    return EXECUTION_SUCCESS;
                } else if (eof || (pfds[i].revents & POLLHUP)) {
                    bind_variable("POLL_EVENT", "EOF", 0);
                    free(pfds); free(meta);
                    return EXECUTION_SUCCESS;
                } else {
                    bind_variable("POLL_EVENT", "IGNORE", 0);
                    free(pfds); free(meta);
                    return EXECUTION_SUCCESS;
                }
            } else {
                // --- DEATH PIPES (Scanner or Worker) ---
                bind_variable("POLL_EVENT", meta[i].type == 1 ? "SCAN_DEATH" : "WORKER_DEATH", 0);
                char arg_buf[32];
                snprintf(arg_buf, sizeof(arg_buf), "%lld", (long long)meta[i].id);
                bind_variable("POLL_ARG1", arg_buf, 0);

                free(pfds); free(meta);
                return EXECUTION_SUCCESS;
            }
        }
    }

    bind_variable("POLL_EVENT", "IGNORE", 0);
    free(pfds); free(meta);
    return EXECUTION_SUCCESS;
}
#undef LOAD_ARRAY

static int ring_version_main(int argc, char **argv) {
  bool show_all = false;
  if (argc == 1) {
    printf("%s\n", FORKRUN_RING_VERSION);
    return EXECUTION_SUCCESS;
  }
  for (int i = 1; i < argc; i++) {
    const char *arg = argv[i];
    if (strcmp(arg, "-a") == 0 || strcmp(arg, "--all") == 0) {
      show_all = true;
      break;
    }
    if (strcmp(arg, "-t") == 0)
      printf("%s %s\n", __DATE__, __TIME__);
    else if (strcmp(arg, "-o") == 0)
      printf("%s\n", BUILD_OS);
    else if (strcmp(arg, "-m") == 0)
      printf("%s\n", BUILD_ARCH);
    else if (strcmp(arg, "-g") == 0)
      printf("%s\n", __VERSION__);
    else if (strcmp(arg, "-f") == 0)
      printf("%s\n", COMPILER_FLAGS);
    else if (strcmp(arg, "-h") == 0)
      printf("%s\n", GIT_HASH);
  }
  if (show_all) {
    printf("Version:  %s\n", FORKRUN_RING_VERSION);
    printf("Built:    %s %s\n", __DATE__, __TIME__);
    printf("OS:       %s\n", BUILD_OS);
    printf("Arch:     %s\n", BUILD_ARCH);
    printf("Compiler: %s\n", __VERSION__);
    printf("Flags:    %s\n", COMPILER_FLAGS);
    printf("Git Hash: %s\n", GIT_HASH);
  }
  return EXECUTION_SUCCESS;
}

// --- NEW FUNCTION: NUMA TELEMETRY ---
static int ring_numa_stats_main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  if (!g_state || !state)
    return EXECUTION_FAILURE;

  uint64_t total_processed = 0;
  uint64_t total_stolen = 0;

  fprintf(
      stderr,
      "\n=================================================================\n");
  fprintf(stderr, "NUMA TELEMETRY (CHUNKS)\n");
  fprintf(
      stderr,
      "=================================================================\n");
  for (uint32_t n = 0; n < global_num_nodes; n++) {
    uint64_t assigned = atomic_load_relaxed(&state[n].stats_chunks_assigned);
    uint64_t processed = atomic_load_relaxed(&state[n].stats_chunks_processed);
    uint64_t i_stole = atomic_load_relaxed(&state[n].stats_chunks_i_stole);
    uint64_t stolen_from_me =
        atomic_load_relaxed(&state[n].stats_chunks_stolen_from_me);
    uint32_t phys = g_logical_to_phys_map ? g_logical_to_phys_map[n] : 0;

    total_processed += processed;
    total_stolen += i_stole;

    fprintf(stderr,
            "Node %u (Phys %u): %lu assigned | %lu processed | %lu I stole | "
            "%lu stolen from me\n",
            n, phys, assigned, processed, i_stole, stolen_from_me);
  }
  fprintf(
      stderr,
      "-----------------------------------------------------------------\n");
  double stolen_pct =
      total_processed > 0
          ? (100.0 * (double)total_stolen / (double)total_processed)
          : 0.0;
  fprintf(stderr, "Total Cross-Socket Traffic: %lu chunks (%.1f%%)\n",
          total_stolen, stolen_pct);
  fprintf(
      stderr,
      "=================================================================\n\n");

  return EXECUTION_SUCCESS;
}

#define DEFINE_DISPATCHER_X(name, func, usage, doc)                            \
  static int dispatch_##name(WORD_LIST *list) {                                \
    int argc;                                                                  \
    char **argv = make_builtin_argv(list, &argc);                              \
    int ret = EXECUTION_FAILURE;                                               \
    if (argv[0])                                                               \
      ret = func(argc, argv);                                                  \
    /* PHYSICS FIX: argv is allocated by Bash internals, MUST use xfree! */    \
    xfree(argv);                                                               \
    return ret;                                                                \
  }
FORKRUN_LOADABLES(DEFINE_DISPATCHER_X)
#undef DEFINE_DISPATCHER_X

#define DEFINE_STRUCT_X(name, func, usage, doc)                                \
  static char *name##_doc[] = {doc, usage, NULL};                              \
  struct builtin name##_struct = {                                             \
      #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0};
FORKRUN_LOADABLES(DEFINE_STRUCT_X)
#undef DEFINE_STRUCT_X

// ---------------------------------------------------------
// ring_call: Zero-Tax C Plugin Callback Execution
// ---------------------------------------------------------

struct forkrun_ctx {
    uint64_t batch_index;       // global batch sequence number
    uint64_t batch_offset;      // byte offset in input stream
    uint64_t batch_byte_length; // length of current batch in bytes
    uint32_t version;           // struct version, currently 1
    uint32_t worker_id;         // RING_WID
    uint32_t node_id;           // NUMA node
    uint32_t num_kills;         // retry count for this batch
    uint32_t numa_major;        // NUMA major sequence (0 if not NUMA)
    uint32_t numa_minor;        // NUMA minor sequence (0 if not NUMA)
    int32_t  fd_in;             // input file descriptor
    char     delimiter;         // batch delimiter
    uint8_t  cfg_state[3];      // global configuration state
};

// Define the user's expected function signatures
typedef int (*forkrun_cb_t)(int argc, char **argv);
typedef int (*forkrun_cb_ctx_t)(int argc, char **argv, void *ctx);

// Cache the loaded plugin per-worker in Thread-Local Storage
static __thread void *tls_dl_handle = NULL;
static __thread forkrun_cb_t tls_callback = NULL;
static __thread forkrun_cb_ctx_t tls_callback_ctx = NULL;
static __thread int tls_use_ctx = 0;
static __thread int tls_numa_enabled = 0;
static __thread struct forkrun_ctx tls_fctx;

// ---------------------------------------------------------
// ring_call: Zero-Tax C Plugin Callback Execution
// ---------------------------------------------------------
// NOTE FOR PLUGIN AUTHORS:
// The `argv` array and the string pointers it contains are backed by
// Thread-Local Storage. They are ONLY valid for the duration of the
// function call. Do not store these pointers across batches!
static int ring_call_main(int argc, char **argv) {
    // Usage: ring_call <fd> <length> <delim> <plugin.so> <func_name>
    if (argc < 6) return EXECUTION_FAILURE;

    int fd = atoi(argv[1]);
    size_t length = (size_t)atoll(argv[2]);
    char delim = argv[3][0];
    const char *plugin_path = argv[4];
    const char *func_name = argv[5];

    // 1. Lazy-load the plugin (Only happens on the first batch for this worker)
    if (!tls_dl_handle) {
        tls_dl_handle = dlopen(plugin_path, RTLD_NOW | RTLD_LOCAL);
        if (!tls_dl_handle) {
            fprintf(stderr, "forkrun [ERROR]: dlopen failed: %s\n", dlerror());
            return EXECUTION_FAILURE;
        }

        int *has_ctx = (int *)dlsym(tls_dl_handle, "forkrun_use_ctx");
        if (has_ctx && *has_ctx == 1) {
            tls_use_ctx = 1;
            tls_callback_ctx = (forkrun_cb_ctx_t)dlsym(tls_dl_handle, func_name);
            if (!tls_callback_ctx) {
                fprintf(stderr, "forkrun [ERROR]: dlsym failed: %s\n", dlerror());
                dlclose(tls_dl_handle);
                tls_dl_handle = NULL;
                return EXECUTION_FAILURE;
            }
            tls_fctx.version = 1;
            const char *wid_str = get_string_value("RING_WID");
            tls_fctx.worker_id = wid_str ? atoi(wid_str) : 0;
            tls_fctx.node_id = (uint32_t)(my_numa_node >= 0 ? my_numa_node : 0);
            tls_fctx.fd_in = fd;
            tls_fctx.delimiter = delim;
            tls_fctx.cfg_state[0] = (cfg_state >> 16) & 0xFF;
            tls_fctx.cfg_state[1] = (cfg_state >> 8) & 0xFF;
            tls_fctx.cfg_state[2] = cfg_state & 0xFF;
            tls_numa_enabled = (state && state[0].numa_enabled) ? 1 : 0;
        } else {
            tls_use_ctx = 0;
            tls_callback = (forkrun_cb_t)dlsym(tls_dl_handle, func_name);
            if (!tls_callback) {
                fprintf(stderr, "forkrun [ERROR]: dlsym failed: %s\n", dlerror());
                dlclose(tls_dl_handle);
                tls_dl_handle = NULL;
                return EXECUTION_FAILURE;
            }
        }
    }

    // 2. Tokenize the batch directly into tls_argv (starting at index 0)
    size_t batch_argc = 0;
    int ret = do_tokenize(fd, length, tls_batch_offset, delim, NULL, 0, &batch_argc);
    if (ret != EXECUTION_SUCCESS) return ret;

    // 3. Ensure capacity and terminate argv array (standard C convention)
    if (batch_argc + 1 > tls_argv_cap) {
        tls_argv_cap = tls_argv_cap ? tls_argv_cap * 2 : 1024;
        char **new_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
        if (!new_argv) return 254;
        tls_argv = new_argv;
    }
    tls_argv[batch_argc] = NULL;

    // 4. THE ZERO-TAX UTOPIA: Execute the user's C code natively!

    // PHYSICS FIX: Shield the C-Plugin against Bash's SIGCHLD reaper
    sigset_t set, oset;
    sigemptyset(&set);
    sigaddset(&set, SIGCHLD);
    sigprocmask(SIG_BLOCK, &set, &oset);

    int cb_ret;
    if (tls_use_ctx) {
        tls_fctx.batch_index = worker_last_idx;
        tls_fctx.batch_offset = (uint64_t)tls_batch_offset;
        tls_fctx.num_kills = worker_last_num_kills;
        tls_fctx.batch_byte_length = (uint64_t)length;
        if (tls_numa_enabled) {
            tls_fctx.numa_major = worker_last_major;
            tls_fctx.numa_minor = worker_last_minor;
        } else {
            tls_fctx.numa_major = 0;
            tls_fctx.numa_minor = 0;
        }
        cb_ret = tls_callback_ctx((int)batch_argc, tls_argv, &tls_fctx);
    } else {
        cb_ret = tls_callback((int)batch_argc, tls_argv);
    }

    sigprocmask(SIG_SETMASK, &oset, NULL);

    // If the plugin returns 0, it's a success. Otherwise, pass the failure code back.
    return (cb_ret == 0) ? EXECUTION_SUCCESS : cb_ret;
}

static int ring_list_main(int argc, char **argv) {
  if (argc >= 2) {
    const char *var_name = argv[1];
    SHELL_VAR *v = find_variable(var_name);
    if (v && !array_p(v)) {
      unbind_variable(var_name);
      v = NULL;
    }
    if (!v)
      v = make_new_array_variable(var_name);
    if (!v)
      return EXECUTION_FAILURE;
    int i = 0;
#define ADD_TO_ARR(name, ...)                                                  \
  if (strcmp(#name, "ring_list") != 0)                                         \
    bind_array_element(v, i++, #name, 0);
    FORKRUN_LOADABLES(ADD_TO_ARR)
#undef ADD_TO_ARR
  } else {
#define PRINT_NAME(name, ...)                                                  \
  if (strcmp(#name, "ring_list") != 0)                                         \
    printf("%s\n", #name);
    FORKRUN_LOADABLES(PRINT_NAME)
#undef PRINT_NAME
  }
  return EXECUTION_SUCCESS;
}

// ==============================================================================
// 9. LIVE TELEMETRY DASHBOARD (TUI)
// ==============================================================================
#include <sys/ioctl.h>
#include <termios.h>

static volatile sig_atomic_t tui_exit = 0;
static void tui_sig_handler(int sig) {
    (void)sig;
    tui_exit = 1;
}

static void format_commas(uint64_t n, char *out) {
    char buf[64];
    snprintf(buf, sizeof(buf), "%llu", (unsigned long long)n);
    int len = strlen(buf);
    int out_idx = 0;
    for (int i = 0; i < len; i++) {
        if (i > 0 && (len - i) % 3 == 0) out[out_idx++] = ',';
        out[out_idx++] = buf[i];
    }
    out[out_idx] = '\0';
}

static void format_bytes(double bytes, char *out) {
    if (bytes >= 1073741824.0)      snprintf(out, 32, "%.1f GB", bytes / 1073741824.0);
    else if (bytes >= 1048576.0)    snprintf(out, 32, "%.1f MB", bytes / 1048576.0);
    else if (bytes >= 1024.0)       snprintf(out, 32, "%.1f KB", bytes / 1024.0);
    else                            snprintf(out, 32, "%.0f B",  bytes);
}

static void format_rate(double rate, const char *suffix, char *out) {
    if (rate >= 1e9)        snprintf(out, 32, "%.1f B %s", rate / 1e9,  suffix);
    else if (rate >= 1e6)   snprintf(out, 32, "%.1f M %s", rate / 1e6,  suffix);
    else if (rate >= 1e3)   snprintf(out, 32, "%.1f K %s", rate / 1e3,  suffix);
    else                    snprintf(out, 32, "%.0f %s",   rate,         suffix);
}

static void tui_print_sep(FILE *tty, const char *title) {
    fprintf(tty, " \xe2\x94\x9c\xe2\x94\x80 %s ", title);
    int title_len = (int)strlen(title);
    // 1(space) + 1(├) + 1(─) + 1(space) + title_len + 1(space) + N(─) + 1(┤) = 80
    for (int i = 0; i < 74 - title_len; i++) fputs("\xe2\x94\x80", tty);
    fprintf(tty, "\xe2\x94\xa4\n");
}

static int tui_get_node_cpus(int phys_node, uint8_t *cpu_map, int max_cpus) {
    char path[256];
    snprintf(path, sizeof(path), "/sys/devices/system/node/node%d/cpulist", phys_node);
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    char buf[1024] = {0};
    ssize_t n = sys_read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;

    char *p = buf;
    while (*p) {
        while (*p && !isdigit((unsigned char)*p)) p++;
        if (!*p) break;
        int start = strtol(p, &p, 10);
        int end = start;
        if (*p == '-') {
            p++;
            end = strtol(p, &p, 10);
        }
        int limit = end < max_cpus ? end : max_cpus - 1;
        for (int i = start; i <= limit; i++) {
            if (i >= 0) cpu_map[i] = 1;
        }
        while (*p && *p != ',' && *p != '\n') p++;
    }
    return 0;
}

static int ring_tui_main(int argc, char **argv) {
    if (!g_state || !state) return EXECUTION_FAILURE;

    uint64_t expected_total_bytes = 0;
    if (argc > 1) expected_total_bytes = strtoull(argv[1], NULL, 10);
    const char *order_mode_str = (argc > 2) ? argv[2] : "Ordered";

    int tty_fd = open("/dev/tty", O_WRONLY);
    if (tty_fd < 0) return EXECUTION_FAILURE;
    FILE *tty = fdopen(tty_fd, "w");
    if (!tty) { close(tty_fd); return EXECUTION_FAILURE; }

    struct sigaction sa, old_int, old_term;
    sa.sa_handler = tui_sig_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT,  &sa, &old_int);
    sigaction(SIGTERM, &sa, &old_term);

    fprintf(tty, "\033[?1049h\033[?25l"); // Alt screen, hide cursor

    uint64_t start_time = get_us_time();
    uint64_t last_time  = start_time;
    uint64_t last_lines = 0, last_bytes = 0, last_batches = 0;

    // --- CPU Tracker State ---
    struct CpuStat {
        uint64_t active;
        uint64_t total;
    };
    struct CpuStat prev_cpu[1024];
    memset(prev_cpu, 0, sizeof(prev_cpu));

    uint8_t node_cpu_map[1024][1024];
    memset(node_cpu_map, 0, sizeof(node_cpu_map));
    int cpus_per_node[1024];
    memset(cpus_per_node, 0, sizeof(cpus_per_node));

    // Map physical CPU cores to their NUMA nodes for localized utilization tracking
    if (global_num_nodes <= 1024) {
        for (uint32_t i = 0; i < global_num_nodes; i++) {
            uint32_t phys = g_logical_to_phys_map ? g_logical_to_phys_map[i] : 0;
            if (tui_get_node_cpus(phys, node_cpu_map[i], 1024) == 0) {
                for (int c = 0; c < 1024; c++) {
                    if (node_cpu_map[i][c]) cpus_per_node[i]++;
                }
            }
        }
    }

    char str_throughput[32], str_bandwidth[32], str_batch_rate[32];
    char str_fallowed[32],   str_in_use[64],    str_total[32];
    char str_finished[32],   str_remaining[32];

    while (!tui_exit && !atomic_load_relaxed(&state[0].emergency_abort)) {
        uint64_t now       = get_us_time();
        double   delta_sec = (now - last_time) / 1000000.0;
        if (delta_sec < 0.001) delta_sec = 0.001;

        bool is_numa = state[0].numa_enabled;
        bool is_eof = is_numa ?
            (atomic_load_acquire(&g_state->ingest_eof_idx) != ~(uint64_t)0) :
            atomic_load_acquire(&state[0].ingest_complete);

        // cur_lines  = lines scanned (from scanner, for throughput display)
        // cur_batches = lines consumed by workers (proxy for completed batch count)
        uint64_t cur_lines = 0, cur_batches = 0;
        int      total_q   = 0, total_escrow = 0;
        for (uint32_t i = 0; i < global_num_nodes; i++) {
            cur_lines   += atomic_load_relaxed(&state[i].total_lines_scanned);
            cur_batches += atomic_load_relaxed(&state[i].total_lines_consumed);

            uint64_t head = atomic_load_relaxed(&state[i].chunk_queue_head);
            uint64_t tail = atomic_load_relaxed(&state[i].chunk_queue_tail);
            total_q      += (head > tail) ? (int)(head - tail) : 0;
            total_escrow += atomic_load_relaxed(&state[i].escrow_pending);
        }

        // Memory footprint: fallowed = reclaimed, read_offset = consumed by workers,
        // ingest_off = total bytes written into the memfd so far (NUMA) or
        // total bytes read from stdin so far (UMA).
        uint64_t fallowed    = g_state->fallow_horizon_bytes;
        uint64_t read_offset = state[0].offset_ring[atomic_load_relaxed(&state[0].read_idx) & RING_MASK];
        uint64_t ingest_off  = 0;

        if (is_numa) {
            uint64_t current_pub = atomic_load_relaxed(&g_state->ingest_publish_idx);
            if (current_pub > 0) {
                ingest_off = g_state->meta_ring[(current_pub - 1) & META_RING_MASK].raw_offset +
                             g_state->meta_ring[(current_pub - 1) & META_RING_MASK].raw_length;
            }
        } else {
            ingest_off = atomic_load_relaxed(&state[0].uma_ingest_offset);
        }

        // Sanity clamps for out-of-order atomics
        if (read_offset < fallowed)    read_offset = fallowed;
        if (ingest_off  < read_offset) ingest_off  = read_offset;

        double lines_ps   = (cur_lines   > last_lines)   ? (cur_lines   - last_lines)   / delta_sec : 0;
        double bytes_ps   = (read_offset > last_bytes)   ? (read_offset - last_bytes)   / delta_sec : 0;
        double batches_ps = (cur_batches > last_batches) ? (cur_batches - last_batches) / delta_sec : 0;

        format_rate(lines_ps,   "lines/s", str_throughput);
        format_rate(bytes_ps,   "B/s",     str_bandwidth);
        format_commas((uint64_t)batches_ps, str_batch_rate);
        snprintf(str_batch_rate + strlen(str_batch_rate),
                 (int)(32 - strlen(str_batch_rate)), " batches/s");

        uint64_t elapsed_sec   = (now - start_time) / 1000000;
        uint64_t active_bytes  = read_offset - fallowed;
        uint64_t waiting_bytes = ingest_off - read_offset; // ingested but not yet consumed

        char b_f[16], b_a[16], b_w[16];
        format_bytes((double)fallowed,       b_f);
        format_bytes((double)active_bytes,   b_a);
        format_bytes((double)waiting_bytes,  b_w);
        format_bytes((double)ingest_off,     str_total);

        char total_label[32];
        snprintf(total_label, sizeof(total_label), "%s Total", str_total);
        snprintf(str_fallowed, sizeof(str_fallowed), "%s Freed", b_f);

        char b_inuse[16];
        format_bytes((double)(active_bytes + waiting_bytes), b_inuse);
        snprintf(str_in_use, sizeof(str_in_use),
                 "%s In Use (%s Act, %s Wait)", b_inuse, b_a, b_w);

        // Progress & ETA
        double progress_pct = 0.0;
        char   str_eta[32]  = "--:--:--";
        if (expected_total_bytes > 0 && ingest_off > 0) {
            progress_pct = ((double)read_offset / expected_total_bytes) * 100.0;
            if (progress_pct > 100.0) progress_pct = 100.0;
            if (bytes_ps > 0) {
                uint64_t eta_sec = (uint64_t)((expected_total_bytes - read_offset) / bytes_ps);
                snprintf(str_eta, sizeof(str_eta), "%02llu:%02llu:%02llu",
                         (unsigned long long)(eta_sec / 3600),
                         (unsigned long long)((eta_sec % 3600) / 60),
                         (unsigned long long)(eta_sec % 60));
            }
        }
        int p_filled = (int)((progress_pct / 100.0) * 46);

        // Read raw Hardware CPU stats from /proc/stat
        struct CpuStat cur_cpu[1024];
        memset(cur_cpu, 0, sizeof(cur_cpu));
        int max_cpu_seen = -1;

        int stat_fd = open("/proc/stat", O_RDONLY);
        if (stat_fd >= 0) {
            size_t stat_buf_sz = 131072; // 128KB easily supports 1024+ CPUs
            char *stat_buf = malloc(stat_buf_sz);
            if (stat_buf) {
                size_t total_read = 0;
                while (total_read < stat_buf_sz - 1) {
                    ssize_t n = sys_read(stat_fd, stat_buf + total_read, stat_buf_sz - 1 - total_read);
                    if (n <= 0) break;
                    total_read += n;
                }
                stat_buf[total_read] = '\0';

                char *line = stat_buf;
                while (line && *line) {
                    if (strncmp(line, "cpu", 3) == 0 && isdigit((unsigned char)line[3])) {
                        int cpu_id = atoi(line + 3);
                        if (cpu_id >= 0 && cpu_id < 1024) {
                            if (cpu_id > max_cpu_seen) max_cpu_seen = cpu_id;
                            unsigned long long user = 0, nice = 0, sys = 0, idle = 0;
                            unsigned long long iowait = 0, irq = 0, softirq = 0, steal = 0;
                            char *p = line;
                            while (*p && !isspace((unsigned char)*p)) p++;
                            sscanf(p, "%llu %llu %llu %llu %llu %llu %llu %llu",
                                   &user, &nice, &sys, &idle, &iowait, &irq, &softirq, &steal);
                            cur_cpu[cpu_id].active = (uint64_t)(user + nice + sys + irq + softirq + steal);
                            cur_cpu[cpu_id].total  = cur_cpu[cpu_id].active + (uint64_t)(idle + iowait);
                        }
                    }
                    line = strchr(line, '\n');
                    if (line) line++;
                }
                free(stat_buf);
            }
            close(stat_fd);
        }

        bool is_io_bound = false;
        bool is_scanner_bound = false;
        for (uint32_t i = 0; i < global_num_nodes; i++) {
            uint64_t w = atomic_load_relaxed(&state[i].active_workers);
            uint64_t thresh = (w + DAMPING_OFFSET >= 3) ? (w + DAMPING_OFFSET - 3) : 0;
            uint64_t st = atomic_load_relaxed(&state[i].current_stall_meter);
            uint64_t sv = atomic_load_relaxed(&state[i].current_starve_meter);
            if (st >= thresh) {
                if (sv >= thresh) is_io_bound = true;
                else is_scanner_bound = true;
            }
        }

        const char *bottleneck = "NONE";
        if (atomic_load_relaxed(&g_state->resume_jagged_count) > 500) {
            bottleneck = "Output-Bound";
        } else if (!is_eof) {
            // Strictly require an empty wait buffer to declare IO starvation
            if (total_q == 0 && waiting_bytes < 65536 && is_io_bound) {
                bottleneck = "IO-Bound";
            } else if (is_scanner_bound) {
                bottleneck = "Scanner-Bound";
            }
        }

        // ================= RENDERING =================
        // tui_print_sep computes separator fill dynamically from the title
        // length, so every horizontal rule lands flush at column 80
        // regardless of section-title length.
        char mode_str[32];
        if (is_numa) snprintf(mode_str, sizeof(mode_str), "NUMA (%u Nodes)", global_num_nodes);
        else         snprintf(mode_str, sizeof(mode_str), "UMA (Flat)");

        fprintf(tty, "\033[H");

        fprintf(tty, " \xe2\x94\x8c\xe2\x94\x80 forkrun ");
        fprintf(tty, "%s ", FORKRUN_RING_VERSION);
        int top_len = 12 + (int)strlen(FORKRUN_RING_VERSION);
        for (int i = 0; i < 78 - top_len; i++) fputs("\xe2\x94\x80", tty);
        fprintf(tty, "\xe2\x94\x90\n");

        fprintf(tty, " \xe2\x94\x82 MODE: %-18s \xe2\x94\x82 OUTPUT: %-10s \xe2\x94\x82 STREAM: %-15s     \xe2\x94\x82\n",
                mode_str, order_mode_str, is_eof ? "[   EOF   ]" : "[ RUNNING ]");

        tui_print_sep(tty, "Global Stream Metrics");

        fprintf(tty, " \xe2\x94\x82 THROUGHPUT: %-17s\xe2\x94\x82 %-20s\xe2\x94\x82 %-22s \xe2\x94\x82\n",
                str_throughput, str_bandwidth, str_batch_rate);

        fprintf(tty, " \xe2\x94\x82 PROGRESS:   [");
        for (int i = 0; i < 46; i++) fputs((i < p_filled) ? "\xe2\x96\x88" : "\xe2\x96\x91", tty);
        fprintf(tty, "] %5.1f%%         \xe2\x94\x82\n", progress_pct);

        fprintf(tty, " \xe2\x94\x82 TIME:       %02llu:%02llu:%02llu elapsed \xe2\x94\x82 ETA: %-13s \xe2\x94\x82 BOTTLENECK: %-12s\xe2\x94\x82\n",
                (unsigned long long)(elapsed_sec / 3600), (unsigned long long)((elapsed_sec % 3600) / 60),
                (unsigned long long)(elapsed_sec % 60), str_eta, bottleneck);

        tui_print_sep(tty, "Memory & Entropy (memfd)");

        // Physical memory oscilloscope bar:
        //   [spaces = fallowed/reclaimed][░ = active/in-use][█ = waiting/ingested-not-consumed]
        int BAR_W  = 46;
        int c_free = (ingest_off > 0) ? (int)((fallowed * BAR_W) / ingest_off) : 0;
        int c_act  = (ingest_off > 0) ? (int)((active_bytes * BAR_W) / ingest_off) : 0;

        // Ensure "Active" isn't swallowed entirely by rounding if > 0
        if (active_bytes > 0 && c_act == 0) c_act = 1;

        int c_map  = BAR_W - c_free - c_act;
        if (c_map < 0) {
            if (c_free > 0) c_free--; else c_act--;
            c_map = 0;
        }

        fprintf(tty, " \xe2\x94\x82 FOOTPRINT:  [");
        for (int i = 0; i < c_free; i++) fputc(' ', tty);
        for (int i = 0; i < c_act;  i++) fputs("\xe2\x96\x91", tty); // Active -> ░
        for (int i = 0; i < c_map;  i++) fputs("\xe2\x96\x88", tty); // Waiting -> █
        fprintf(tty, "] %-15s\xe2\x94\x82\n", total_label);

        fprintf(tty, " \xe2\x94\x82 STATUS:     %-17s\xe2\x94\x82 %-45s\xe2\x94\x82\n", str_fallowed, str_in_use);

        tui_print_sep(tty, "CPU Saturation & NUMA Topology");

        // Base CPU% on logical cores (hyperthreads), not physical cores --
        // a worker count above the physical core count is expected and
        // correct on HT/SMT systems, so it must not read as >100%.
        int logical_cores_per_node = (int)sysconf(_SC_NPROCESSORS_ONLN) / (global_num_nodes > 0 ? (int)global_num_nodes : 1);
        if (logical_cores_per_node < 1) logical_cores_per_node = 1;

        for (uint32_t i = 0; i < global_num_nodes; i++) {
            uint64_t w = atomic_load_relaxed(&state[i].active_workers);

            int pct = 0;
            uint64_t delta_active = 0;
            uint64_t delta_total = 0;
            bool has_cpu_stats = false;

            // Map the parsed hardware stats directly to the underlying physical NUMA node
            if (cpus_per_node[i] > 0) {
                for (int c = 0; c <= max_cpu_seen; c++) {
                    if (node_cpu_map[i][c] && cur_cpu[c].total > prev_cpu[c].total) {
                        delta_active += (cur_cpu[c].active - prev_cpu[c].active);
                        delta_total  += (cur_cpu[c].total - prev_cpu[c].total);
                        has_cpu_stats = true;
                    }
                }
            } else if (global_num_nodes == 1 && max_cpu_seen >= 0) {
                // Flat UMA fallback: aggregate all cores
                for (int c = 0; c <= max_cpu_seen; c++) {
                    if (cur_cpu[c].total > prev_cpu[c].total) {
                        delta_active += (cur_cpu[c].active - prev_cpu[c].active);
                        delta_total  += (cur_cpu[c].total - prev_cpu[c].total);
                        has_cpu_stats = true;
                    }
                }
            }

            if (has_cpu_stats && delta_total > 0) {
                pct = (int)((delta_active * 100) / delta_total);
            } else {
                // Final fallback if hardware stats failed parsing
                pct = (int)((w * 100) / logical_cores_per_node);
            }

            if (pct > 100) pct = 100;
            int b_fill = (pct * 20) / 100;

            uint64_t h = atomic_load_relaxed(&state[i].chunk_queue_head);
            uint64_t t = atomic_load_relaxed(&state[i].chunk_queue_tail);
            int q = (h > t) ? (int)(h - t) : 0;

            fprintf(tty, " \xe2\x94\x82 NODE %-2u CPU:%3d%% [", i, pct);
            for (int k = 0; k < 20; k++) fputs((k < b_fill) ? "\xe2\x96\x88" : "\xe2\x96\x91", tty);
            fprintf(tty, "] W:%3llu/%-3d \xe2\x94\x82 Q: %-5d \xe2\x94\x82 Stolen: %-5llu\xe2\x94\x82\n",
                    (unsigned long long)w, logical_cores_per_node, q,
                    (unsigned long long)atomic_load_relaxed(&state[i].stats_chunks_i_stole));
        }

        // Commit CPU hardware stats for the next loop's delta
        memcpy(prev_cpu, cur_cpu, sizeof(prev_cpu));

        tui_print_sep(tty, "Physics Engine & Batching");

        format_commas(cur_batches, str_finished);
        uint64_t current_L = atomic_load_relaxed(&state[0].current_batch_size);
        if (expected_total_bytes > 0 && cur_batches > 0) {
            uint64_t avg_bytes_per_batch = read_offset / cur_batches;
            if (avg_bytes_per_batch == 0) avg_bytes_per_batch = 1;
            uint64_t est_rem = (expected_total_bytes > read_offset) ?
                (expected_total_bytes - read_offset) / avg_bytes_per_batch : 0;
            char tmp_rem[32];
            format_commas(est_rem, tmp_rem);
            snprintf(str_remaining, sizeof(str_remaining), "~%s", tmp_rem);
        } else {
            snprintf(str_remaining, sizeof(str_remaining), "Unknown    ");
        }

        fprintf(tty, " \xe2\x94\x82 BATCH SIZE: %-16llu \xe2\x94\x82 FINISHED: %-10s\xe2\x94\x82 REMAINING: %-11s \xe2\x94\x82\n",
                (unsigned long long)current_L, str_finished, str_remaining);

        tui_print_sep(tty, "Fault Tolerance & Output Ordering");

        fprintf(tty, " \xe2\x94\x82 ESCROW QUEUE: %-14d \xe2\x94\x82 POISONED: %-10u\xe2\x94\x82 OUTPUT SKEW: %-10u\xe2\x94\x82\n",
                total_escrow,
                __atomic_load_n(&g_state->poisoned_count, __ATOMIC_RELAXED),
                atomic_load_relaxed(&g_state->resume_jagged_count));

        fprintf(tty, " \xe2\x94\x94");
        for (int i = 0; i < 77; i++) fputs("\xe2\x94\x80", tty);
        fprintf(tty, "\xe2\x94\x98\n");
        fflush(tty);

        // All-done check: EOF signalled + all scanners finished + ring drained
        bool all_done = is_eof;
        for (uint32_t i = 0; i < global_num_nodes && all_done; i++) {
            if (!atomic_load_acquire(&state[i].scanner_finished) ||
                (atomic_load_relaxed(&state[i].read_idx) <
                 atomic_load_relaxed(&state[i].write_idx))) {
                all_done = false;
            }
        }
        if (all_done) break;

        last_time    = now;
        last_lines   = cur_lines;
        last_bytes   = read_offset;
        last_batches = cur_batches;

        usleep(250000); // 4 FPS
    }

    // Restore screen and cursor
    fprintf(tty, "\033[?1049l\033[?25h");
    fclose(tty);
    sigaction(SIGINT,  &old_int,  NULL);
    sigaction(SIGTERM, &old_term, NULL);
    return EXECUTION_SUCCESS;
}

int setup_builtin_forkrun_ring(void) {
#define REGISTER_X(name, func, usage, doc) add_builtin(&name##_struct, 1);
  FORKRUN_LOADABLES(REGISTER_X)
#undef REGISTER_X
  return 0;
}
