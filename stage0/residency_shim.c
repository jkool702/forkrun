/* Stage 0 residency + policy shim.
 *
 * ctypes' libc.syscall() varargs marshalling was unreliable for the
 * move_pages call shape (pointer tail args through a variadic
 * prototype), and this glibc exports no move_pages name at all; the
 * C probe works:
 *   syscall(SYS_move_pages, 0, 1, pages, NULL, status, 0)
 * set_mempolicy/get_mempolicy additionally live in libnuma, not libc.
 * One shim with typed prototypes serves the whole ablation.
 */

#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sched.h>
#include <unistd.h>
#include <errno.h>
#include <numaif.h> /* set_mempolicy lives in libnuma, not libc */

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

/* Typed wrappers (the caller asserts presence; these fail loudly at
 * load time if the toolchain lacks them). */
int stage0_sched_setaffinity(long pid, unsigned long size,
                             const void *mask)
{
    return sched_setaffinity((pid_t)pid, (size_t)size,
                             (const cpu_set_t *)mask);
}

int stage0_set_mempolicy(int mode, unsigned long size,
                         const void *nodes)
{
    return set_mempolicy(mode, (const unsigned long *)nodes, size);
}
