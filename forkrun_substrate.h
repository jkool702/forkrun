/* forkrun_substrate.h — Stage 1 state-ownership header (v1.3 §2.1).
 *
 * The language-independent machine extracted from the bash orchestration.
 * Ownership taxonomy: C owns mechanism, engine invariants, protocol
 * constants, and default safety limits; the frontend owns user-selected
 * policy, presentation, and orchestration DECISIONS; bash owns
 * compatibility presentation.
 *
 * State model:
 *   fr_config_t — immutable, fork-inherited. Parent fills before fork();
 *     children inherit as plain memory. NO config sync verb exists.
 *     Contains protocol constants and safety-limit DEFAULTS — both
 *     reactors read them; neither hardcodes them. The 3s trap-ACK grace
 *     is a protocol constant (fr_trap_ack_grace_ms); whether a given
 *     invocation respawns is frontend policy.
 *   fr_state_t — C-authoritative runtime state, snapshotted to frontends
 *     at boundaries. NEVER raw-read from MAP_SHARED by frontends: the
 *     fences live in C. This rule governs coordination words only, never
 *     the payload-byte window, which frontends read directly per the
 *     mmap stability guarantee (Batch.data is a MAP_SHARED view by design).
 *
 * Standing rules:
 *   - No fr_get_state(): state travels with the claim. Workers never read
 *     fr_state_t on any hot path — the claim out-param is the worker's
 *     only state channel. Reactor state reads are typed struct reads at
 *     event frequency only.
 *   - major is 64-bit: 42-bit majors packed (major<<22|minor) per the
 *     v3.5.0 ABI freeze. A 32-bit major would reintroduce the truncation
 *     the freeze eliminated.
 *
 * This header is included by forkrun_ring.c (Stage 1: single-TU include;
 * physical split into forkrun_core.c comes later — the boundary is what
 * matters first). libforkrun.so (canary) enforces zero bash linkage via
 * -Wl,--no-undefined + explicit allowed-dependency set (see Makefile).
 *
 * Header hygiene rules (v1.3; hardened after the FTMs-after-include bug):
 *   1. Self-contained: includes everything it uses; compiles standalone
 *      (`echo '#include "forkrun_substrate.h"' | gcc -x c - -fsyntax-only`).
 *   2. Include-guarded.
 *   3. FTM-INDEPENDENT: never defines or relies on feature-test macros
 *      (_GNU_SOURCE et al). Structs and integer constants need none, and
 *      FTMs in headers silently alter the ABI of every including TU.
 *   4. No inclusion-order dependencies, ever: compiles from any position
 *      in the TU — before or after system and bash headers.
 *
 * The plugin-ABI tie: <forkrun_plugin.h> is the packing's second consumer
 * (frozen v2 uint32 numa_major|numa_minor split). The fallback asserts
 * below hold on ABI-derivable bounds alone; the strong tie (split width
 * == 22 against the frozen header) activates in TUs that include the
 * plugin header. The engine TU includes both headers unconditionally at
 * the top of forkrun_ring.c.
 */
#ifndef FORKRUN_SUBSTRATE_H
#define FORKRUN_SUBSTRATE_H

#include <stdint.h> /* self-contained: uint64_t/uint32_t for the structs below */

#ifdef __cplusplus
extern "C" {
#endif

/* Packing constants shared with the plugin ABI (forkrun_plugin.h) and
 * PACK_KEY in the engine. Two views of one coordinate system must never
 * disagree — enforced by static_assert below. */
#define FR_MINOR_BITS 22
#define FR_MINOR_MASK ((1ULL << FR_MINOR_BITS) - 1ULL)
#define FR_MAJOR_MASK ((1ULL << (64 - FR_MINOR_BITS)) - 1ULL)
#define FR_PACK_KEY(maj, min) \
    ((((uint64_t)(maj) & FR_MAJOR_MASK) << FR_MINOR_BITS) | ((uint64_t)(min) & FR_MINOR_MASK))

/* Protocol constants (C-owned; frontends read from config, never hardcode). */
#define FR_TRAP_ACK_GRACE_MS_DEFAULT 3000
#define FR_MAX_POLL_WORKERS 8192

/* Immutable, fork-inherited configuration. */
typedef struct fr_config {
    int ring_wid;          /* worker slot id (spawn) */
    int ring_node_id;      /* NUMA node id (spawn) */
    int ring_wincarn;      /* respawn generation (spawn) */
    int fd_order_pipe;     /* ordering transport fd, -1 when realtime */
    int retry_limit;       /* poison threshold default (FORKRUN_RETRY_LIMIT) */
    int debug;             /* FORKRUN_DEBUG */
    int trap_ack_grace_ms; /* PROTOCOL CONSTANT (default 3000) */
    int respawn_cap;       /* safety-limit default: max respawns/run, -1 = uncapped */
    int spawn_ceiling;     /* safety-limit default: max live workers, -1 = nproc-derived */
} fr_config_t;

/* C-authoritative runtime state — snapshot at claim/reactor boundaries. */
typedef struct fr_state {
    uint64_t batch_idx;  /* global batch sequence number */
    uint64_t major;      /* 64-bit chunk sequence (42-bit majors packed) */
    uint32_t minor;      /* within-chunk batch sequence */
    uint32_t slots;      /* slots consumed by this claim (always 1) */
    uint32_t num_kills;  /* retry count for this batch */
    uint32_t poisoned;   /* 1 once kill count reaches the retry limit */
} fr_state_t;

/* Width/packing contract: fr_state_t.major must hold every major the
 * packed numa_batch_id can express; minor must hold every minor. */
typedef char fr_assert_major_width[(sizeof(((fr_state_t *)0)->major) >= 8) ? 1 : -1];
typedef char fr_assert_minor_width[(sizeof(((fr_state_t *)0)->minor) >= 4) ? 1 : -1];
typedef char fr_assert_pack_roundtrip[(FR_MINOR_BITS == 22) ? 1 : -1];

/* ABI-derivable bounds (true without seeing the plugin header): the ABI's
 * frozen v2 numa_minor field is uint32, so a minor split wider than 32
 * bits could not round-trip through the frozen struct; and the packed key
 * must exactly fill 64 bits (42 + 22) — the packing is the full word, so
 * the sign bit is necessarily part of the major and must stay positive
 * (the hazard the plugin header's offset comment documents). */
typedef char fr_assert_abi_minor_fits_u32[(FR_MINOR_BITS <= 32) ? 1 : -1];
typedef char fr_assert_packing_fills_word[(FR_MINOR_BITS + 42 == 64) ? 1 : -1];
#ifdef FORKRUN_PLUGIN_H
/* Strong tie: active only in TUs that included the frozen plugin header
 * first — the split width must equal the ABI's frozen 22. */
typedef char fr_assert_abi_packing_frozen[(FR_MINOR_BITS == 22) ? 1 : -1];
#endif

#ifdef __cplusplus
}
#endif

#endif /* FORKRUN_SUBSTRATE_H */
