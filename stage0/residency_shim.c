/* Stage 0 instrumentation shim.
 *
 * ctypes' libc.syscall() varargs marshalling was unreliable for the
 * move_pages call shape (pointer tail args through a variadic
 * prototype), and this glibc exports no move_pages name at all. The
 * C probe works and is kept next to this file. set_mempolicy lives in
 * libnuma, not libc; sched APIs take cpu_set_t whose word-size
 * assumption (8-byte masks) broke on modern kernels — so affinity
 * takes an explicit int array instead of a raw mask.
 */

#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sched.h>
#include <unistd.h>
#include <errno.h>
#include <numaif.h> /* set_mempolicy lives in libnuma, not libc */
#include <string.h>

/* Query the NUMA node of each page in addrs[0..count).
 *
 * addrs[i] must be page-aligned (the caller supplies per-page starts).
 * status[i] receives the node index on success (or -1 for failure).
 * Returns 0 on success, or -1 with errno set (EPERM/ENOSYS/EINVAL ->
 * "method unavailable", handled by the caller).
 */
int stage0_query_nodes(const void *const addrs[], int status[], long count)
{
    return (int)syscall(SYS_move_pages, 0, count,
                        addrs, NULL, status, 0);
}

/* sched_getcpu() (per-thread CPU of the calling thread). */
int stage0_sched_getcpu(void)
{
    return sched_getcpu();
}

/* mincore(): residency bits for [addr, addr+len) into vec (1 byte/page).
 * Returns 0 on success. */
int stage0_mincore(void *addr, size_t len, void *vec)
{
    return mincore(addr, len, (unsigned char *)vec);
}

/* Affinity from an explicit CPU list. Returns 0 on success, -1 on
 * error (errno preserved). Avoids raw-mask word-size assumptions. */
int stage0_apply_affinity(const int cpus[], long ncpus)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    for (long i = 0; i < ncpus; i++) {
        if (cpus[i] >= 0)
            CPU_SET(cpus[i], &set);
    }
    return sched_setaffinity(0, sizeof(set), &set);
}

/* Capture the calling thread's effective affinity as a cpu list.
 * out receives up to max entries; returns the count, or -1 on error.
 * sized via CPU_ALLOC to avoid the 8-byte-mask assumption. */
int stage0_get_affinity(int out[], long max)
{
    size_t size = CPU_ALLOC_SIZE(1 << 14);
    cpu_set_t *set = CPU_ALLOC(1 << 14);
    if (!set)
        return -1;
    int rc = sched_getaffinity(0, size, set);
    if (rc != 0) {
        CPU_FREE(set);
        return -1;
    }
    int n = 0;
    for (int cpu = 0; cpu < (1 << 14) && n < max; cpu++) {
        if (CPU_ISSET(cpu, set))
            out[n++] = cpu;
    }
    CPU_FREE(set);
    return n;
}

int stage0_set_mempolicy(int mode, unsigned long size,
                         const void *nodes)
{
    return set_mempolicy(mode, (const unsigned long *)nodes, size);
}

int stage0_get_mempolicy(int *mode, unsigned long *mask,
                         unsigned long size)
{
    return get_mempolicy(mode, mask, size, NULL, 0);
}
