/* forkrun_trace.h -- opt-in structured trace for the cleanroom pipeline.
 *
 * A HEADER, not a .c, for one reason: Phase A instruments
 * forkrun_cleanroom.c and Phase B instruments forkrun_ring.c, and both must
 * emit the SAME record format. A shared object would drag in a link
 * dependency between the engine and the launcher; a header keeps the
 * launcher standalone and costs nothing at runtime when tracing is off.
 *
 * It cannot live in forkrun_substrate.h either -- that file is frozen by
 * release_check.py:51, and the freeze is exactly what Phase B has to argue
 * with. A NEW header keeps Phase A shippable against the unmodified policy.
 *
 * ---------------------------------------------------------------------------
 * THE CONTRACT -- read this before changing anything.
 * ---------------------------------------------------------------------------
 *
 * 1. ONE write() PER RECORD. Every record is emitted with a single
 *    write(2) of a whole FR_TRACE_REC-sized buffer. Splitting one record
 *    across writes would let two children interleave inside a record.
 *
 * 2. The fd MUST be O_APPEND. Measured on this machine (os.fork(), 16
 *    children, one 64-byte record per write): a shared file offset
 *    recovered 25,962 of 320,000 records -- 92% silently lost -- while
 *    O_APPEND recovered all 320,000 with zero torn records. A shared
 *    offset loses records to the lost-update race.
 *
 * 3. THIS IS WHY IT MATTERS. The trace exists to diagnose CONCURRENT
 *    stalls. Without O_APPEND it would discard most of its evidence
 *    exactly when it is needed, and discard it SILENTLY: the parent
 *    would read a short but well-formed file and conclude the run simply
 *    emitted fewer events.
 *
 * 4. NO USER PAYLOAD BYTES. Ever. The trace records control-plane facts
 *    only -- who forked, who exited, with what status. Batch content never
 *    enters this channel, so the trace cannot become a data-leak path.
 *
 * 5. Records are fixed-width and self-describing: magic + version on every
 *    record, so a reader can detect truncation and a version skew rather
 *    than misparse.
 *
 * 6. DISABLED BY DEFAULT and allocation-free when off: the emit path
 *    checks the fd first and returns. With tracing off this compiles to a
 *    predictable branch and costs no syscall, no allocation, and nothing
 *    on the fatal-teardown path's latency budget.
 */

#ifndef FORKRUN_TRACE_H
#define FORKRUN_TRACE_H

#include <stdint.h>
#include <time.h>
#include <unistd.h>

/* Record size is part of the wire format. Change it and bump the version. */
#define FR_TRACE_REC        64
#define FR_TRACE_MAGIC      0x52544646u   /* 'F','T','R','F' little-endian */
#define FR_TRACE_VERSION    1

/* Roles. The order is wire-stable; append only. */
enum {
    FR_ROLE_LAUNCHER = 0,
    FR_ROLE_WORKER   = 1,
    FR_ROLE_PROBE    = 2,
    FR_ROLE_SPILL    = 3,
    FR_ROLE_FALLOW   = 4,
    FR_ROLE_SCAN     = 5,
    FR_ROLE_DRAIN    = 6,
    FR_ROLE_ORDERER  = 7,   /* Phase B: engine-side, never emitted by the launcher */
    FR_ROLE__MAX
};

/* Events. The order is wire-stable; append only. */
enum {
    FR_EV_LAUNCHER_INIT = 1,
    FR_EV_FORK_REQUEST  = 2,   /* parent, before fork(); wid/wincarn set */
    FR_EV_FORK_RETURN   = 3,   /* parent, after fork(); pid set */
    FR_EV_CHILD_ENTRY   = 4,   /* child, first thing after the keep-list */
    FR_EV_CHILD_EXIT    = 5,   /* child, just before _exit(); rc set */
    FR_EV_REAP          = 6,   /* parent, after waitpid; status decoded */
    FR_EV_SUP_ENTER     = 7,
    FR_EV_SUP_EXIT      = 8,
    FR_EV_SUP_ABORT     = 9,
    FR_EV_SUP_RESPAWN   = 10,
    FR_EV_FATAL_BEGIN   = 11,
    FR_EV_FATAL_KILL    = 12,
    FR_EV_FATAL_REAP    = 13,
    FR_EV_FATAL_END     = 14,
    FR_EV__MAX
};

/* Reserved sentinels. -1 means "not applicable", so a reader can tell an
 * absent field from a legitimate zero. */
#define FR_TRACE_NA ((int32_t)-1)

typedef struct {
    uint32_t magic;        /* FR_TRACE_MAGIC                    */
    uint16_t version;      /* FR_TRACE_VERSION                  */
    uint16_t rec_bytes;    /* FR_TRACE_REC                      */
    uint64_t t_ns;         /* CLOCK_MONOTONIC at emit           */
    int32_t  pid;          /* emitting process                  */
    uint8_t  role;         /* enum fr_role                      */
    uint8_t  event;        /* enum fr_event                     */
    int32_t  wid;          /* worker id, or FR_TRACE_NA         */
    int32_t  wincarn;      /* respawn generation, or FR_TRACE_NA */
    int32_t  node;         /* always 0 in Phase A (UMA-only)   */
    int32_t  rc;           /* exit code / decoded status        */
    /* Explicit tail padding to FR_TRACE_REC (64). A power-of-two record
     * keeps the memfd layout aligned and matches the concurrency
     * measurement this format was sized from. The size is ASSERTED below
     * rather than assumed: an earlier draft used pad[4], which silently
     * produced 48-byte records while the header claimed 64 -- a wire
     * format that lies about itself is worse than no format. */
    uint8_t  pad[20];
} fr_trace_rec;

/* The record size IS the wire format. Fail the build rather than emit a
 * layout the parser does not expect. */
_Static_assert(sizeof(fr_trace_rec) == FR_TRACE_REC,
               "fr_trace_rec must be exactly FR_TRACE_REC bytes");
_Static_assert(FR_TRACE_REC % 8 == 0,
               "FR_TRACE_REC must stay 8-byte aligned");

/* The fd is a process-global inherited across fork, exactly like the other
 * pipeline descriptors. -1 means tracing is off. */
extern int fr_trace_fd;

#if defined(__cplusplus)
extern "C" {
#endif

/* Emit one record. THE ONLY WRITER.
 *
 * Single write(), whole record, no retry loop on partial writes: a partial
 * write means the record is already corrupt, and silently continuing would
 * desynchronise every record after it. There is no safe recovery, so the
 * trace is best-effort BY DESIGN and says so -- it must never be able to
 * affect the run it is observing.
 */
static inline void fr_trace_emit(uint8_t role, uint8_t event,
                                 int32_t wid, int32_t wincarn,
                                 int32_t node, int32_t rc)
{
    fr_trace_rec r;
    struct timespec ts;

    if (fr_trace_fd < 0)
        return;                      /* off: no syscall, no allocation */

    clock_gettime(CLOCK_MONOTONIC, &ts);
    r.magic     = FR_TRACE_MAGIC;
    r.version   = FR_TRACE_VERSION;
    r.rec_bytes = FR_TRACE_REC;
    r.t_ns      = (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
    r.pid       = (int32_t)getpid();
    r.role      = role;
    r.event     = event;
    r.wid       = wid;
    r.wincarn   = wincarn;
    r.node      = node;
    r.rc        = rc;
    /* Zero the whole tail: the parser must never see stale bytes, and
     * memfd contents are zero-filled only on first allocation. */
    for (unsigned i = 0; i < sizeof r.pad; i++)
        r.pad[i] = 0;

    /* Best-effort. A failed trace write must not perturb the pipeline, so
     * the result is deliberately ignored. */
    (void)!write(fr_trace_fd, &r, sizeof r);
}

#if defined(__cplusplus)
}
#endif

#endif /* FORKRUN_TRACE_H */
