// ==============================================================================
// 1. INCLUDES, MACROS, TOPOLOGY, AND TLS VARIABLES
// (Replace your existing SharedState pointer and eventfd variables with this)
// ==============================================================================

#include <sys/syscall.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <errno.h>

#ifndef MPOL_DEFAULT
#define MPOL_DEFAULT 0
#endif
#ifndef MPOL_BIND
#define MPOL_BIND 2
#endif

// Architecture-specific syscall numbers for set_mempolicy
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

#define FLAG_MAJOR_EOF (1U << 31)
#define PACK_KEY(maj, min) (((uint64_t)(maj) << 32) | (min))

static inline int auto_detect_numa_node() {
#ifdef __NR_getcpu
    unsigned cpu, node;
    if (syscall(__NR_getcpu, &cpu, &node, NULL) == 0) return (int)node;
#endif
    return 0;
}

// TLS NUMA Thread Affinity Tracking
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

// Global Event FDs & Escrows (Isolated per NUMA node)
static int *evfd_data_arr = NULL;
static int *fd_escrow_r = NULL;
static int *fd_escrow_w = NULL;

static int evfd_data = -1; // Legacy for single-node bash scripts
static int evfd_eof  = -1;
static int evfd_ingest_data = -1;
static int evfd_ingest_eof  = -1;
static int evfd_starve = -1;
static int fd_escrow[2] = { -1, -1 }; // Legacy array

static uint32_t global_num_nodes = 1;

// ==============================================================================
// 2. STRUCTURES
// ==============================================================================

struct IngestPacket {
    uint64_t offset;
    uint64_t length;
    uint32_t node_id;
    uint32_t major_id;
}; 

struct ScannerTask {
    uint32_t major_id;
    uint32_t pad;
    uint64_t start_off;
    uint64_t length;
}; 

struct OrderPacket {
    uint32_t major_idx; 
    uint32_t minor_idx; 
    uint32_t cnt;       
    int32_t  fd;
    uint64_t off;
    uint64_t len;
};

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
    uint64_t cfg_w_start;
    uint64_t cfg_w_max;
    uint64_t cfg_batch_start;
    uint64_t cfg_batch_max;
    uint64_t cfg_limit;
    uint64_t cfg_chunk_bytes;
    uint64_t cfg_line_max;
    int64_t  cfg_timeout_us;
    uint8_t  mode_byte;
    uint8_t  fixed_workers;
    uint8_t  fixed_batch;
    uint8_t  cfg_return_bytes;
    uint8_t  numa_enabled;

    // FULL RING ARRAYS
    uint32_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
    uint64_t end_ring[RING_SIZE] ALIGNED(4096);
    uint32_t major_ring[RING_SIZE] ALIGNED(4096);
    uint32_t minor_ring[RING_SIZE] ALIGNED(4096);
};

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

// ==============================================================================
// 3. CORE LIFECYCLE (Init & Destroy)
// ==============================================================================

static int ring_init_main(int argc, char **argv) {
    const char *dbg_env = get_string_value("FORKRUN_DEBUG");
    if (dbg_env && (strcmp(dbg_env, "1") == 0 || strcmp(dbg_env, "true") == 0)) {
        g_debug = 1;
        fprintf(stderr, "forkrun [DEBUG] Enabled\n");
    } else g_debug = 0;
    
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "--nodes=", 8) == 0) {
            global_num_nodes = (uint32_t)atoi(argv[i] + 8);
            if (global_num_nodes < 1) global_num_nodes = 1;
        }
    }

    if (state != NULL) {
        for (uint32_t n = 0; n < global_num_nodes; n++) {
            atomic_store_relaxed(&state[n].read_idx, 0);
            atomic_store_relaxed(&state[n].write_idx, 0);
            atomic_store_relaxed(&state[n].ingest_complete, 0);
            atomic_store_relaxed(&state[n].total_lines_consumed, 0);
            atomic_store_relaxed(&state[n].min_idx, 0);
            atomic_store_relaxed(&state[n].fallow_active, 0);
            atomic_store_relaxed(&state[n].tail_idx, 0);
            atomic_store_relaxed(&state[n].scanner_finished, 0);
            state[n].offset_ring[0] = 0;
            
            // Drain local escrows
            if (fd_escrow_r && fd_escrow_r[n] >= 0) {
                char dump[1024]; while(read(fd_escrow_r[n], dump, sizeof(dump)) > 0) {}
            }
        }
        return EXECUTION_SUCCESS;
    }

    size_t total_size = sizeof(struct SharedState) * global_num_nodes;
    total_size = (total_size + 4095ULL) & ~4095ULL;
    void *p = mmap(NULL, total_size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) { builtin_error("mmap: %s", strerror(errno)); return EXECUTION_FAILURE; }
    state = (struct SharedState *)p;
    memset(p, 0, total_size);

    cfg_state = 0x202121; 
    int stdin_explicit = -1; 
    const char *out_array_name = NULL;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strncmp(arg, "--workers=", 10) == 0)      apply_config(0, 0, arg+10);
        else if (strncmp(arg, "--workers0=", 11) == 0) apply_config(0, 1, arg+11);
        else if (strncmp(arg, "--workers-max=", 14) == 0) apply_config(0, 2, arg+14);
        else if (strncmp(arg, "--lines=", 8) == 0)     apply_config(1, 0, arg+8);
        else if (strncmp(arg, "--lines0=", 9) == 0)    apply_config(1, 1, arg+9);
        else if (strncmp(arg, "--lines-max=", 12) == 0) apply_config(1, 2, arg+12);
        else if (strncmp(arg, "--bytes=", 8) == 0)     apply_config(2, 0, arg+8);
        else if (strncmp(arg, "--bytes0=", 9) == 0)    apply_config(2, 1, arg+9);
        else if (strncmp(arg, "--bytes-max=", 12) == 0) apply_config(2, 2, arg+12);
        else if (strncmp(arg, "--out=", 6) == 0)       out_array_name = arg+6;
        else if (strncmp(arg, "--stdin", 7) == 0)      stdin_explicit = 1;
        else if (strncmp(arg, "--no-stdin", 10) == 0)  stdin_explicit = 0;
        else if (strncmp(arg, "--nodes=", 8) != 0 && arg[0] != '-') out_array_name = arg;
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
    defs[1] = defs[0];                     maxs[1] = maxs[0];
    defs[2] = get_v_def("lines", false);   maxs[2] = get_v_max("lines", false);
    defs[3] = defs[2];                     maxs[3] = maxs[2];
    defs[4] = get_v_def("bytes", stdin_mode); maxs[4] = get_v_max("bytes", stdin_mode);
    defs[5] = defs[4];                        maxs[5] = maxs[4];

    for (int i=0; i<6; i++) {
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
        state[n].cfg_w_start = vals[0];
        state[n].cfg_w_max   = vals[1];
        state[n].mode_byte   = byte_mode ? 1 : 0;
        state[n].numa_enabled = (global_num_nodes > 1) ? 1 : 0;
        
        if (byte_mode) {
            state[n].cfg_batch_start = vals[4];
            state[n].cfg_batch_max   = vals[5];
            state[n].cfg_chunk_bytes = vals[5];
            state[n].cfg_line_max    = vals[5];
            if (state[n].cfg_return_bytes == 0) state[n].cfg_return_bytes = 1;
        } else {
            state[n].cfg_batch_start = vals[2];
            state[n].cfg_batch_max   = vals[3];
            int bb_code = (cfg_state >> SH_B_B) & 0xF;
            if (bb_code != S_DIS) state[n].cfg_line_max = vals[5];
            else state[n].cfg_line_max = maxs[4]; 
        }

        state[n].fixed_workers = (state[n].cfg_w_start == state[n].cfg_w_max);
        state[n].fixed_batch   = (state[n].cfg_batch_start == state[n].cfg_batch_max);
        
        if (byte_mode) atomic_store_relaxed(&state[n].signed_batch_size, 1);
        else atomic_store_relaxed(&state[n].signed_batch_size, (int64_t)state[n].cfg_batch_start);
    }

    // Allocate Isolated Event FDs and Escrow Pipes
    evfd_data_arr = xmalloc(global_num_nodes * sizeof(int));
    fd_escrow_r   = xmalloc(global_num_nodes * sizeof(int));
    fd_escrow_w   = xmalloc(global_num_nodes * sizeof(int));

    for (uint32_t n = 0; n < global_num_nodes; n++) {
        evfd_data_arr[n] = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
        int pfd[2];
        if (pipe(pfd) == 0) {
            fcntl(pfd[0], F_SETFL, O_NONBLOCK); fcntl(pfd[1], F_SETFL, O_NONBLOCK);
            fcntl(pfd[0], F_SETFD, FD_CLOEXEC); fcntl(pfd[1], F_SETFD, FD_CLOEXEC);
            fcntl(pfd[1], F_SETPIPE_SZ, 1048576);
            fd_escrow_r[n] = pfd[0];
            fd_escrow_w[n] = pfd[1];
        }
    }

    evfd_eof = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
    evfd_ingest_data = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK);
    evfd_ingest_eof = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK|EFD_SEMAPHORE);
    evfd_starve = eventfd(0, EFD_CLOEXEC|EFD_NONBLOCK);
    
    // Bind legacy variables for single-node mode bash scripts
    evfd_data = evfd_data_arr[0];
    fd_escrow[0] = fd_escrow_r[0];
    fd_escrow[1] = fd_escrow_w[0];

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", evfd_data_arr[0]); bind_variable("EVFD_RING_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_eof);  bind_variable("EVFD_RING_EOF", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_data); bind_variable("EVFD_RING_INGEST_DATA", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_ingest_eof);  bind_variable("EVFD_RING_INGEST_EOF", buf, 0);
    snprintf(buf, sizeof(buf), "%d", evfd_starve);      bind_variable("EVFD_RING_STARVE", buf, 0);

    if (out_array_name) {
        SHELL_VAR *v = find_variable(out_array_name);
        if (v && !array_p(v)) { unbind_variable(out_array_name); v = NULL; }
        if (!v) v = make_new_array_variable(out_array_name);
        if (!v) return EXECUTION_FAILURE;
        
        int *created_fds = xmalloc(sizeof(int) * state[0].cfg_w_max);
        int created_cnt = 0;
        int failure = 0;
        for (uint64_t i = 0; i < state[0].cfg_w_max; i++) {
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

    int probe_fd[2];
    int pipe_cap = 65536; 
    if (pipe(probe_fd) == 0) {
        int ret = fcntl(probe_fd[1], F_SETPIPE_SZ, 1048576);
        if (ret >= 0) pipe_cap = ret;
        else {
            ret = fcntl(probe_fd[1], F_GETPIPE_SZ);
            if (ret > 0) pipe_cap = ret;
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
    (void)argc; (void)argv;
    if (state) { munmap(state, sizeof(struct SharedState) * global_num_nodes); state = NULL; }
    if (evfd_data_arr) {
        for (uint32_t n = 0; n < global_num_nodes; n++) {
            if (evfd_data_arr[n] >= 0) close(evfd_data_arr[n]);
            if (fd_escrow_r && fd_escrow_r[n] >= 0) close(fd_escrow_r[n]);
            if (fd_escrow_w && fd_escrow_w[n] >= 0) close(fd_escrow_w[n]);
        }
        xfree(evfd_data_arr); evfd_data_arr = NULL;
        xfree(fd_escrow_r); fd_escrow_r = NULL;
        xfree(fd_escrow_w); fd_escrow_w = NULL;
    }
    if (evfd_eof >= 0) { close(evfd_eof); evfd_eof = -1; }
    if (evfd_ingest_data >= 0) { close(evfd_ingest_data); evfd_ingest_data = -1; }
    if (evfd_ingest_eof >= 0) { close(evfd_ingest_eof); evfd_ingest_eof = -1; }
    if (evfd_starve >= 0) { close(evfd_starve); evfd_starve = -1; }
    unbind_variable("EVFD_RING_DATA"); unbind_variable("EVFD_RING_EOF");
    unbind_variable("EVFD_RING_INGEST_DATA"); unbind_variable("EVFD_RING_INGEST_EOF");
    unbind_variable("EVFD_RING_STARVE");
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// 4. NEW NUMA LOADABLES
// ==============================================================================

static int ring_numa_ingest_main(int argc, char **argv) {
    if (argc < 6) {
        builtin_error("ring_numa_ingest: insufficient arguments");
        return EXECUTION_FAILURE;
    }

    int infd        = atoi(argv[1]);
    int outfd       = atoi(argv[2]);
    int index_pipe  = atoi(argv[3]);
    int claim_pipe  = atoi(argv[4]);
    int num_nodes   = atoi(argv[5]);
    bool ordered_mode = (argc > 6 && strcmp(argv[6], "1") == 0);

    if (num_nodes < 1) num_nodes = 1;
    if (num_nodes > 1024) num_nodes = 1024;

    fcntl(claim_pipe, F_SETFL, fcntl(claim_pipe, F_GETFL) | O_NONBLOCK);

    uint64_t chunk_size = 4 * 1024 * 1024ULL;
    uint64_t max_chunk  = ordered_mode ? (16ULL * 1024 * 1024) : (128ULL * 1024 * 1024);

    uint64_t current_offset = 0;
    uint32_t current_major  = 0;
    int consecutive_full    = 0;

    int chunks_emitted = 0;
    int warmup_cycles  = 3 * num_nodes;
    int last_target    = -1;
    int *backlogs      = xmalloc(num_nodes * sizeof(int));
    if (!backlogs) return EXECUTION_FAILURE;
    memset(backlogs, 0, num_nodes * sizeof(int));

    unsigned long test_mask = 1UL;
    bool numa_enabled = (syscall(__NR_set_mempolicy, MPOL_BIND, &test_mask, 64) == 0);
    if (!numa_enabled) num_nodes = 1;

    int mask_words = (num_nodes + 63) / 64;
    unsigned long *nodemask = xmalloc(mask_words * sizeof(unsigned long));

    while (1) {
        uint32_t claimed_node;
        while (read(claim_pipe, &claimed_node, sizeof(claimed_node)) == sizeof(claimed_node)) {
            if (claimed_node < (uint32_t)num_nodes && backlogs[claimed_node] > 0)
                backlogs[claimed_node]--;
        }

        int target_node = 0;
        if (chunks_emitted < warmup_cycles) {
            target_node = chunks_emitted % num_nodes;
        } else {
            int min_backlog = INT_MAX;
            for (int i = 0; i < num_nodes; i++) {
                int check = (last_target + 1 + i) % num_nodes;
                if (backlogs[check] < min_backlog) {
                    min_backlog = backlogs[check];
                    target_node = check;
                }
            }
        }

        if (numa_enabled && num_nodes > 1) {
            memset(nodemask, 0, mask_words * sizeof(unsigned long));
            nodemask[target_node / 64] |= (1UL << (target_node % 64));
            syscall(__NR_set_mempolicy, MPOL_BIND, nodemask, num_nodes + 1);
        }

        chunk_size &= ~4095ULL;
        if (chunk_size == 0) chunk_size = 4096;

        ssize_t n = splice(infd, NULL, outfd, NULL, chunk_size, SPLICE_F_MOVE | SPLICE_F_MORE);
        if (n <= 0) break;

        struct IngestPacket pkt = {
            .offset   = current_offset,
            .length   = (uint64_t)n,
            .node_id  = target_node,
            .major_id = current_major
        };

        if (write(index_pipe, &pkt, sizeof(pkt)) != sizeof(pkt)) break;

        backlogs[target_node]++;
        last_target = target_node;
        chunks_emitted++;
        current_offset += n;
        current_major++;

        if ((uint64_t)n == chunk_size) {
            consecutive_full++;
            if (consecutive_full >= 4 && chunk_size < max_chunk) {
                chunk_size *= 2;
                consecutive_full = 0;
            }
        } else {
            chunk_size = 4 * 1024 * 1024ULL;
            consecutive_full = 0;
        }
    }

    if (numa_enabled) syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0);
    xfree(nodemask);
    xfree(backlogs);

    struct IngestPacket sentinel = { .offset = current_offset, .length = 0, .node_id = 0, .major_id = UINT32_MAX };
    write(index_pipe, &sentinel, sizeof(sentinel));

    return EXECUTION_SUCCESS;
}

static int ring_indexer_numa_main(int argc, char **argv) {
    if (argc < 4) {
        builtin_error("ring_indexer_numa: insufficient arguments");
        return EXECUTION_FAILURE;
    }

    int memfd       = atoi(argv[1]);
    int index_pipe  = atoi(argv[2]);

    int num_node_pipes = argc - 3;
    if (num_node_pipes < 1) return EXECUTION_FAILURE;

    int *node_pipes = xmalloc(num_node_pipes * sizeof(int));
    for (int i = 0; i < num_node_pipes; i++) {
        node_pipes[i] = atoi(argv[3 + i]);
    }

    struct IngestPacket pkt;
    char tail_buf[65536];
    uint64_t actual_start = 0;
    uint32_t last_major_seen = 0;

    while (read(index_pipe, &pkt, sizeof(pkt)) == sizeof(pkt)) {
        if (pkt.major_id == UINT32_MAX) break;

        uint64_t chunk_end = pkt.offset + pkt.length;
        uint64_t actual_end = chunk_end;
        bool found_newline = false;

        uint64_t scan_start = (chunk_end > sizeof(tail_buf)) ? (chunk_end - sizeof(tail_buf)) : actual_start;
        if (scan_start < actual_start) scan_start = actual_start;

        size_t to_read = chunk_end - scan_start;
        if (to_read > 0) {
            ssize_t n = pread(memfd, tail_buf, to_read, scan_start);
            if (n > 0) {
                char *nl = memrchr(tail_buf, '\n', n);
                if (nl) {
                    actual_end = scan_start + (nl - tail_buf) + 1;
                    found_newline = true;
                }
            } else if (n < 0 && g_debug) {
                fprintf(stderr, "forkrun [DEBUG] indexer pread failed: %s\n", strerror(errno));
            }
        }

        struct ScannerTask task = {
            .major_id = pkt.major_id,
            .pad = 0,
            .start_off = actual_start,
            .length = 0
        };

        if (found_newline) {
            task.length = actual_end - actual_start;
            actual_start = actual_end;
        }

        int target = node_pipes[pkt.node_id % num_node_pipes];
        if (write(target, &task, sizeof(task)) != sizeof(task)) break;

        last_major_seen = pkt.major_id;
    }

    if (pkt.major_id == UINT32_MAX && actual_start < pkt.offset) {
        struct ScannerTask final_task = {
            .major_id = last_major_seen + 1,
            .pad = 0,
            .start_off = actual_start,
            .length = pkt.offset - actual_start
        };
        write(node_pipes[0], &final_task, sizeof(final_task));
    }

    xfree(node_pipes);
    return EXECUTION_SUCCESS;
}

static int ring_numa_scanner_main(int argc, char **argv) {
    if (argc < 7) return EXECUTION_FAILURE;

    int memfd      = atoi(argv[1]);
    int my_node_id = atoi(argv[2]);
    int claim_pipe = atoi(argv[3]);
    int fd_spawn   = atoi(argv[4]); 
    int num_nodes  = atoi(argv[5]);

    int *node_pipes = xmalloc(num_nodes * sizeof(int));
    for (int i = 0; i < num_nodes; i++) node_pipes[i] = atoi(argv[6 + i]);

    struct SharedState *local_state = &state[my_node_id];

    uint64_t L = local_state->cfg_batch_start;
    uint64_t Lmax = local_state->cfg_batch_max;
    uint64_t W = local_state->cfg_w_start;
    uint64_t W_max_val = local_state->cfg_w_max;
    uint64_t BytesMax = local_state->cfg_line_max;
    int64_t  timeout_us = local_state->cfg_timeout_us;
    bool     byte_mode = local_state->mode_byte;
    bool     fixed_batch = local_state->fixed_batch;
    bool     fixed_workers = local_state->fixed_workers;
    bool     return_bytes = local_state->cfg_return_bytes; 

    uint64_t W2 = fast_log2(W_max_val);
    uint64_t L2 = fast_log2(Lmax);
    uint64_t X_const = fast_log2(W2 + L2) * W2;
    if (X_const == 0) X_const = 1;
    
    uint64_t local_scan_idx = 0;
    uint64_t local_write_idx = 0;
    
    size_t chunk_sz = get_optimal_chunk_size();
    char *buf = xmalloc_aligned(chunk_sz);
    char *p = buf, *end = buf;
    
    int phase = 0;
    uint64_t batch_counter = 0;
    uint64_t target_count = 0;
    uint64_t last_calc_us = get_us_time();
    uint64_t last_calc_write = 0;
    uint64_t last_calc_read = 0;
    uint64_t starve_meter = 0; 
    uint64_t stall_meter = 0;
    uint64_t batches_since_calc = 0;

    atomic_store_relaxed(&local_state->write_idx, 0);
    atomic_store_relaxed(&local_state->read_idx, 0);
    atomic_store_relaxed(&local_state->active_workers, W);

    if (fd_spawn >= 0 && W > 0) {
        char sbuf[64];
        int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", W);
        if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
    }

    #define LOCAL_SCANNER_WAKE() do { \
        if(atomic_load_acquire(&local_state->active_waiters) > 0) { \
            uint64_t v=1; SYS_CHK(write(evfd_data_arr[my_node_id], &v, 8)); \
        } \
    } while(0)

    #define NUMA_ADAPTIVE_COMMIT(force) do { \
        if (local_scan_idx > local_write_idx) { \
            uint64_t W_curr = atomic_load_relaxed(&local_state->active_workers); \
            if (W_curr < 1) W_curr = 1; \
            if (force || atomic_load_relaxed(&local_state->active_waiters) > 0) { \
                atomic_store_release(&local_state->write_idx, local_scan_idx); \
                local_write_idx = local_scan_idx; \
                LOCAL_SCANNER_WAKE(); \
            } else { \
                uint64_t r_idx = atomic_load_relaxed(&local_state->read_idx); \
                uint64_t pending = local_scan_idx - r_idx; \
                uint64_t current_buffer = local_scan_idx - local_write_idx; \
                uint64_t target_buffer = 0; \
                if (pending >= 10 * W_curr) target_buffer = (W_curr << 2); \
                else if (pending > (W_curr << 1)) { \
                    uint64_t linear = pending >> 1; \
                    uint64_t intermediate = (linear < current_buffer) ? linear : current_buffer; \
                    if (intermediate > W_curr) target_buffer = intermediate - W_curr; \
                } \
                uint64_t target_w = local_scan_idx - target_buffer; \
                if (target_w > local_write_idx) { \
                    atomic_store_release(&local_state->write_idx, target_w); \
                    local_write_idx = target_w; \
                    LOCAL_SCANNER_WAKE(); \
                } \
            } \
        } \
    } while(0)

    #define NUMA_SCANNER_FLUSH(cnt_val, stride_val, is_last_in_chunk, maj_id, min_idx, batch_start_off, batch_end_off) do { \
        while(1) { \
            uint64_t limit = atomic_load_acquire(&local_state->read_idx); \
            if ((local_scan_idx - limit) < RING_SIZE) break; \
            NUMA_ADAPTIVE_COMMIT(true); \
            usleep(100); \
        } \
        uint64_t pk = (uint64_t)(batch_start_off); \
        if ((cnt_val) != L || (is_last_in_chunk)) pk |= FLAG_PARTIAL_BATCH; \
        \
        local_state->stride_ring[local_scan_idx & RING_MASK] = (uint32_t)(stride_val); \
        local_state->offset_ring[local_scan_idx & RING_MASK] = pk; \
        local_state->end_ring[local_scan_idx & RING_MASK]    = (uint64_t)(batch_end_off); \
        local_state->major_ring[local_scan_idx & RING_MASK]  = (maj_id); \
        local_state->minor_ring[local_scan_idx & RING_MASK]  = (min_idx) | ((is_last_in_chunk) ? FLAG_MAJOR_EOF : 0); \
        \
        local_scan_idx++; \
        NUMA_ADAPTIVE_COMMIT(false); \
    } while(0)

    int active_pipe_idx = my_node_id; 
    int pipes_tried = 0;
    int home_poll_count = 0;
    bool pipe_stalled = false;

    while (pipes_tried < num_nodes) {
        int current_pipe = node_pipes[active_pipe_idx];
        struct ScannerTask task;
        
        struct pollfd pfd = { .fd = current_pipe, .events = POLLIN };
        if (active_pipe_idx != my_node_id) {
            if (poll(&pfd, 1, 0) <= 0) { 
                active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
                pipes_tried++;
                continue;
            }
            pipe_stalled = false;
        } else {
            int timeout = (10 << home_poll_count);
            if (timeout > 1000) timeout = 1000;
            if (poll(&pfd, 1, timeout) <= 0) {
                home_poll_count++;
                active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
                pipes_tried++;
                pipe_stalled = true;
                continue;
            }
            home_poll_count = 0;
            pipe_stalled = false;
        }

        ssize_t r = read(current_pipe, &task, sizeof(task));
        
        if (r == sizeof(task)) {
            pipes_tried = 0; 
            write(claim_pipe, &active_pipe_idx, sizeof(active_pipe_idx));

            if (task.length == 0) {
                NUMA_SCANNER_FLUSH(0, 0, true, task.major_id, 0, task.start_off, task.start_off);
                NUMA_ADAPTIVE_COMMIT(true);
                continue;
            }

            uint64_t chunk_end = task.start_off + task.length;
            uint64_t current_p_offset = task.start_off;
            uint32_t minor_idx = 0;
            uint64_t pending_lines = 0;
            uint64_t batch_start = current_p_offset;
            
            uint64_t buf_base_offset = current_p_offset;
            p = buf; end = buf;

            while (current_p_offset < chunk_end) {
                bool flush = false;
                
                if (byte_mode) {
                    uint64_t avail = chunk_end - current_p_offset;
                    uint64_t take = (avail >= L) ? L : avail;
                    current_p_offset += take;
                    pending_lines = take;
                    flush = true;
                } else {
                    uint64_t scan_target = (L > pending_lines) ? (L - pending_lines) : 1;
                    uint64_t lines_found = 0;
                    
                    while (lines_found < scan_target) {
                        if (p >= end) {
                            uint64_t read_start = buf_base_offset + (p - buf);
                            size_t to_read = chunk_sz;
                            if (read_start + to_read > chunk_end) to_read = chunk_end - read_start;
                            if (to_read > 0) {
                                ssize_t n = pread(memfd, buf, to_read, read_start);
                                if (n > 0) { buf_base_offset = read_start; p = buf; end = buf + n; }
                                else if (n < 0 && errno == EINTR) continue;
                                else break; 
                            } else break;
                        }
                        
                        char *nl = memchr(p, '\n', end - p);
                        if (nl) { lines_found++; p = nl + 1; }
                        else { lines_found++; p = end; } 
                    }
                    
                    pending_lines += lines_found;
                    current_p_offset = buf_base_offset + (p - buf);
                    
                    if (pending_lines >= L || current_p_offset >= chunk_end) flush = true;
                    else if (pipe_stalled && atomic_load_relaxed(&local_state->active_waiters) > 0) flush = true;
                }

                if (flush) {
                    bool is_last = (current_p_offset >= chunk_end);
                    uint32_t stride = (return_bytes) ? (current_p_offset - batch_start) : pending_lines;
                    
                    NUMA_SCANNER_FLUSH(pending_lines, stride, is_last, task.major_id, minor_idx, batch_start, current_p_offset);
                    minor_idx++;
                    batch_start = current_p_offset;
                    pending_lines = 0;

                    batch_counter++;
                    batches_since_calc++;
                    
                    bool starvation = (atomic_load_relaxed(&local_state->active_waiters) > 0);
                    uint64_t xLim = W + DAMPING_OFFSET;
                    if (starvation) starve_meter = (starve_meter + xLim) >> 1;
                    else starve_meter >>= 1;
                    stall_meter >>= 1; 

                    uint64_t tc = W * 4; if (tc < 4) tc = 4;

                    if (!fixed_batch && !byte_mode) {
                        if (phase == 0) {
                            if (batch_counter >= tc) { phase = 1; batch_counter = 0; }
                        } else if (phase == 1) {
                            if (pipe_stalled) phase = 2; 
                            else if (batch_counter >= tc) {
                                L *= 2;
                                if (L >= Lmax) { L = Lmax; phase = 2; }
                                
                                if (W < W_max_val && !fixed_workers) {
                                    uint64_t l_log = fast_log2(L);
                                    uint64_t n_spawn = (6 * (W_max_val - W) * L2) / (X_const * (L2 + l_log));
                                    if (n_spawn < 1) n_spawn = 1;
                                    if (n_spawn > (W_max_val - W)) n_spawn = W_max_val - W;
                                    if (fd_spawn >= 0) {
                                        char sbuf[64]; int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", n_spawn);
                                        if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
                                        W += n_spawn;
                                        atomic_store_relaxed(&local_state->active_workers, W);
                                    }
                                }
                                atomic_store_release(&local_state->batch_change_idx, local_scan_idx);
                                atomic_store_release(&local_state->signed_batch_size, -(int64_t)L);
                                batch_counter = 0;
                            }
                        }
                    }

                    uint64_t now_us = get_us_time();
                    if (now_us - last_calc_us > 5000 || batches_since_calc >= W) {
                        uint64_t d_in  = local_write_idx - last_calc_write;
                        uint64_t r_con = atomic_load_relaxed(&local_state->total_lines_consumed);
                        uint64_t d_out = r_con - last_calc_read;
                        last_calc_write = local_write_idx; last_calc_read  = r_con; last_calc_us = now_us;
                        batches_since_calc = 0;
                        
                        if (!fixed_workers && W < W_max_val) {
                            uint64_t backlog = local_scan_idx - atomic_load_relaxed(&local_state->read_idx);
                            bool spawn = false;
                            if (fixed_batch) { if (backlog > W && !starvation) spawn = true; } 
                            else {
                                if (d_out > 0) {
                                    uint64_t rate = d_out / W; if(rate==0) rate=1;
                                    if ((d_in / rate) > W) spawn = true;
                                } else if (backlog > (W * 4) && !starvation) spawn = true;
                            }
                            if (spawn && phase != 1) {
                                uint64_t grow = fixed_batch ? 1 : ((W + 1) / 2);
                                if (W + grow > W_max_val) grow = W_max_val - W;
                                if (grow > 0 && fd_spawn >= 0) {
                                    char sbuf[64]; int slen = snprintf(sbuf, sizeof(sbuf), "%lu\n", grow);
                                    if (slen > 0) SYS_CHK(write(fd_spawn, sbuf, slen));
                                    W += grow;
                                    atomic_store_relaxed(&local_state->active_workers, W);
                                }
                            }
                        }

                        if (!fixed_batch && !byte_mode && phase == 2) {
                            int64_t backlog = (int64_t)local_write_idx - (int64_t)atomic_load_relaxed(&local_state->read_idx);
                            if (backlog < 0) backlog = 0;
                            uint64_t l_target = (backlog / W);
                            if (l_target > Lmax) l_target = Lmax;
                            if (l_target < 1) l_target = 1;
                            
                            if (l_target > L) {
                                L = l_target;
                                atomic_store_release(&local_state->batch_change_idx, local_scan_idx);
                                atomic_store_release(&local_state->signed_batch_size, -(int64_t)L);
                            } else if (l_target < L && starve_meter >= (xLim - 3)) {
                                L = (L + l_target) / 2; if (L < 1) L = 1;
                                atomic_store_release(&local_state->batch_change_idx, local_scan_idx);
                                atomic_store_release(&local_state->signed_batch_size, -(int64_t)L);
                                starve_meter = 0; stall_meter = 0;
                            }
                        }
                    }
                }
            }
            NUMA_ADAPTIVE_COMMIT(true);
        } else {
            active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
            pipes_tried++;
        }
    }

    atomic_store_release(&local_state->write_idx, local_scan_idx);
    atomic_store_release(&local_state->scanner_finished, 1);
    LOCAL_SCANNER_WAKE(); 
    if (fd_spawn >= 0) SYS_CHK(write(fd_spawn, "x\n", 2));
    
    xfree(buf);
    xfree(node_pipes);
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// 5. UPDATED CONSUMER LOADABLES (Claim, Ack, Order)
// ==============================================================================

static int ring_claim_main(int argc, char **argv) {
    const char *v_target = "REPLY";
    int fd_read = -1;

    if (argc >= 4 && isdigit(argv[argc-1][0]) && !isdigit(argv[argc-2][0])) {
        v_target = argv[2];
        fd_read = atoi(argv[3]);
    } else if (argc >= 2) {
        if (isdigit(argv[1][0])) {
            fd_read = atoi(argv[1]);
        } else {
            v_target = argv[1]; 
            if (argc >= 3) fd_read = atoi(argv[2]);
        }
    }

    if (my_numa_node == -1) {
        const char *s_node = get_string_value("RING_NODE_ID");
        my_numa_node = s_node ? atoi(s_node) : auto_detect_numa_node();
        if (my_numa_node >= (int)global_num_nodes) my_numa_node = 0;
    }
    struct SharedState *local_state = &state[my_numa_node];

    uint64_t my_read_idx;
    uint64_t claim_count = 1;
    int spin = 0;
    
    if (fd_read < 0) fd_read = worker_cached_fd;
    
restart_loop:
    while (1) {
        struct EscrowPacket ep;
        if (fd_escrow_r && fd_escrow_r[my_numa_node] >= 0 && 
            read(fd_escrow_r[my_numa_node], &ep, sizeof(ep)) == sizeof(ep)) {
            my_read_idx = ep.idx;
            claim_count = ep.cnt;
            break; 
        }
        
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
                    uint32_t L0 = local_state->stride_ring[r_curr & RING_MASK];
                    if (L0 == 0) L0 = 1;
                    uint64_t Wmax = atomic_load_relaxed(&local_state->active_workers); 
                    if (Wmax == 0) Wmax = 1;
                    uint64_t B = ((uint64_t)(-sbatch)) / L0;
                    if (B > Wmax) B = Wmax;
                    if (B < 1) B = 1;
                    claim_count = B;
                    if (claim_count > 64) claim_count = 64;
                }
            }
            
            if (r_curr + claim_count > w_snap) claim_count = w_snap - r_curr;
            
            if (claim_count > 1) {
                uint64_t safe_count = 1;
                for (uint64_t i = 0; i < claim_count; i++) {
                    if (local_state->offset_ring[(r_curr + i) & RING_MASK] & FLAG_PARTIAL_BATCH) {
                        safe_count = i + 1; 
                        break;
                    }
                }
                claim_count = safe_count;
            }

            my_read_idx = atomic_fetch_add(&local_state->read_idx, claim_count);
            
            if (!local_state->numa_enabled) {
                int64_t sbatch_check = atomic_load_relaxed(&local_state->signed_batch_size);
                if (sbatch_check < 0) {
                    uint64_t Ib = atomic_load_relaxed(&local_state->batch_change_idx);
                    if (my_read_idx > Ib) {
                         int64_t target = -sbatch_check;
                         atomic_compare_exchange(&local_state->signed_batch_size, &sbatch_check, target);
                    }
                }
            }
            break;
        }
        
        if (atomic_load_acquire(&local_state->scanner_finished)) {
            if (atomic_fetch_sub(&local_state->active_workers, 1) == 1) return 2; 
            bind_var_or_array(v_target, "0", 0);
            return 1;
        }
        
        if (spin < 100) { cpu_relax(); spin++; continue; }
        
        atomic_fetch_add(&local_state->active_waiters, 1);
        is_waiting_on_ring = true;
        
        struct pollfd pfds[3] = { 
            { .fd = evfd_data_arr[my_numa_node], .events = POLLIN }, 
            { .fd = evfd_eof,  .events = POLLIN }, 
            { .fd = fd_escrow_r[my_numa_node], .events = POLLIN } 
        };
        
        while(1) {
             if (atomic_load_acquire(&local_state->write_idx) > atomic_load_relaxed(&local_state->read_idx)) break;
             poll(pfds, 3, -1);
             if (pfds[2].revents & POLLIN) break; 
             if (pfds[0].revents) { uint64_t v; if(read(evfd_data_arr[my_numa_node], &v, 8)){}; break; }
             if (pfds[1].revents) break; 
        }
        cleanup_waiter_state();
        spin = 0;
    }

    uint64_t w_curr = atomic_load_acquire(&local_state->write_idx);
    if (!local_state->numa_enabled && my_read_idx + claim_count > w_curr) {
         if (atomic_load_acquire(&local_state->scanner_finished)) {
             int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
             if (diff < 0) diff = 0;
             claim_count = (uint64_t)diff;
             if (claim_count == 0) { spin = 0; goto restart_loop; }
         } else {
             atomic_fetch_add(&local_state->active_waiters, 1);
             is_waiting_on_ring = true;
             while (1) {
                 w_curr = atomic_load_acquire(&local_state->write_idx);
                 if (w_curr > my_read_idx) {
                     uint64_t avail = w_curr - my_read_idx;
                     if (avail < claim_count) {
                         struct EscrowPacket ep = { .idx = my_read_idx + avail, .cnt = claim_count - avail };
                         if (write(fd_escrow_w[my_numa_node], &ep, sizeof(ep)) == sizeof(ep)) {
                             claim_count = avail;
                             uint64_t one=1; SYS_CHK(write(evfd_data_arr[my_numa_node], &one, 8));
                             break;
                         }
                     } else { break; }
                 }
                 if (atomic_load_acquire(&local_state->scanner_finished)) {
                     int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
                     if (diff < 0) diff = 0;
                     claim_count = (uint64_t)diff;
                     break;
                 }
                 struct pollfd pfds[2] = { { .fd = evfd_data_arr[my_numa_node], .events = POLLIN }, { .fd = evfd_eof, .events = POLLIN } };
                 poll(pfds, 2, -1);
                 if (pfds[0].revents) { uint64_t v; if(read(evfd_data_arr[my_numa_node], &v, 8)){}; }
                 if (pfds[1].revents) break; 
             }
             cleanup_waiter_state();
             if (claim_count == 0) { spin = 0; goto restart_loop; }
         }
    }

    uint64_t final_val = 0;

    if (local_state->cfg_return_bytes) {
        if (local_state->numa_enabled) {
            uint64_t start = local_state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
            uint64_t end   = local_state->end_ring[(my_read_idx + claim_count - 1) & RING_MASK];
            final_val = end - start;
        } else {
            uint64_t start = local_state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
            uint64_t end = local_state->offset_ring[(my_read_idx + claim_count) & RING_MASK] & ~FLAG_PARTIAL_BATCH;
            final_val = end - start;
        }
    } else {
        if (claim_count == 1) final_val = local_state->stride_ring[my_read_idx & RING_MASK];
        else for (uint64_t i = 0; i < claim_count; i++) final_val += local_state->stride_ring[(my_read_idx + i) & RING_MASK];
    }
    
    atomic_fetch_add(&local_state->total_lines_consumed, (local_state->cfg_return_bytes) ? claim_count : final_val);

    worker_last_idx = my_read_idx;
    worker_last_cnt = claim_count;
    
    char buf[64];
    u64toa(final_val, buf); bind_var_or_array(v_target, buf, 0);
    
    u64toa(my_read_idx, buf); bind_variable("RING_BATCH_IDX", buf, 0);
    u64toa(claim_count, buf); bind_variable("RING_BATCH_SLOTS", buf, 0);

    if (local_state->numa_enabled) {
        worker_last_major = local_state->major_ring[my_read_idx & RING_MASK];
        worker_last_minor = local_state->minor_ring[my_read_idx & RING_MASK] & ~FLAG_MAJOR_EOF; 
        
        if (local_state->minor_ring[(my_read_idx + claim_count - 1) & RING_MASK] & FLAG_MAJOR_EOF) {
            worker_last_minor |= FLAG_MAJOR_EOF;
        }
        
        sprintf(buf, "%u", worker_last_major); 
        bind_variable("RING_MAJOR", buf, 0);
        sprintf(buf, "%u", worker_last_minor & ~FLAG_MAJOR_EOF); 
        bind_variable("RING_MINOR", buf, 0);
    }
    
    if (fd_read >= 0) {
        uint64_t start_offset = local_state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
        if (lseek(fd_read, (off_t)start_offset, SEEK_SET) == (off_t)-1) {
            if (g_debug) fprintf(stderr, "forkrun [DEBUG] ring_claim lseek failed: %s\n", strerror(errno));
        }
    }
    return 0;
}

static int ring_ack_main(int argc, char **argv) {
    if (argc < 2) return EXECUTION_FAILURE;
    int fd_fallow = atoi(argv[1]);
    int fd_target = (argc >= 3) ? atoi(argv[2]) : -1;
    
    struct OrderPacket op;
    op.pad = 0;

    if (worker_last_cnt > 0) {
        if (state && global_num_nodes > 1) {
            op.major_idx = worker_last_major;
            op.minor_idx = worker_last_minor; 
            op.cnt       = worker_last_cnt;
        } else {
            op.major_idx = (uint32_t)worker_last_idx;
            op.minor_idx = 0;
            op.cnt       = worker_last_cnt;
        }
    } else {
        op.cnt = (uint32_t)atoi(get_string_value("RING_BATCH_SLOTS"));
        if (state && global_num_nodes > 1) {
            op.major_idx = (uint32_t)atoi(get_string_value("RING_MAJOR"));
            op.minor_idx = (uint32_t)atoi(get_string_value("RING_MINOR")); 
        } else {
            op.major_idx = (uint32_t)atoi(get_string_value("RING_BATCH_IDX"));
            op.minor_idx = 0;
        }
    }

    if (fd_fallow > 0) SYS_CHK(write(fd_fallow, &op, sizeof(op)));
    
    if (fd_target > 0) {
        if (fd_target != ack_cached_target_fd) {
            ack_cached_target_fd = fd_target;
            struct stat st;
            ack_cached_mode = (fstat(fd_target, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 2;
        }
        
        if (ack_cached_mode == 1) {
            const char *s_order_pipe = get_string_value("FD_ORDER_PIPE");
            if (s_order_pipe) {
                int fd_pipe = atoi(s_order_pipe);
                off_t curr = lseek(fd_target, 0, SEEK_CUR);
                if (curr == (off_t)-1) return EXECUTION_FAILURE;
                
                op.fd  = fd_target;
                op.off = (uint64_t)last_ack_offset;
                op.len = (uint64_t)(curr - last_ack_offset);
                SYS_CHK(write(fd_pipe, &op, sizeof(op)));
                last_ack_offset = curr;
            }
        } else {
            SYS_CHK(write(fd_target, &op, sizeof(op)));
        }
    }
    return EXECUTION_SUCCESS;
}

struct BufferedPacket { struct OrderPacket pkt; struct BufferedPacket *next; };

static int ring_order_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    bool memfd_mode = (strcmp(argv[2], "memfd") == 0);
    const char *prefix = argv[2]; 
    
    bool unordered_mode = false;
    bool numa_mode = false;
    for (int i = 3; i < argc; i++) {
        if (strcmp(argv[i], "unordered") == 0) unordered_mode = true;
        if (strcmp(argv[i], "numa") == 0) numa_mode = true;
    }

    bool use_zerocopy = false;
    struct stat st_out;
    if (fstat(1, &st_out) == 0 && S_ISREG(st_out.st_mode)) use_zerocopy = true;

    struct BufferedPacket *head = NULL;
    uint32_t expected_major = 0;
    uint32_t expected_minor = 0;
    struct OrderPacket ops[64];
    ssize_t n_read;
    
    while ((n_read = read(fd_in, ops, sizeof(ops))) > 0) {
        int count = n_read / sizeof(struct OrderPacket);
        for (int i = 0; i < count; i++) {
            struct OrderPacket *op = &ops[i];
            
            bool is_chunk_eof = (op->minor_idx & FLAG_MAJOR_EOF);
            uint32_t actual_minor = op->minor_idx & ~FLAG_MAJOR_EOF;

            bool is_expected = false;
            if (numa_mode) {
                is_expected = (op->major_idx == expected_major && actual_minor == expected_minor);
            } else {
                is_expected = (op->major_idx == expected_major);
            }

            if (unordered_mode || is_expected) {
                if (memfd_mode) {
                    off_t offset = (off_t)op->off;
                    if (use_zerocopy) sendfile(1, op->fd, &offset, op->len);
                    else ring_copy_chunk(op->fd, 1, offset, op->len);
                    
                    off_t aligned_start = (op->off / 4096) * 4096;
                    fallocate(op->fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, op->len);
                } else {
                    char path[256];
                    if (numa_mode) snprintf(path, sizeof(path), "%s.%u.%u", prefix, op->major_idx, actual_minor); 
                    else snprintf(path, sizeof(path), "%s.%u", prefix, op->major_idx); 
                    
                    int fd_file = open(path, O_RDONLY);
                    if (fd_file >= 0) {
                        off_t offset = 0; struct stat st;
                        if (fstat(fd_file, &st) == 0 && st.st_size > 0) {
                            sendfile(1, fd_file, &offset, st.st_size);
                        }
                        close(fd_file); unlink(path);
                    }
                }
                
                if (!unordered_mode) {
                    if (numa_mode) {
                        expected_minor += op->cnt; 
                        if (is_chunk_eof) { expected_major++; expected_minor = 0; }
                    } else {
                        expected_major += op->cnt; 
                    }
                    
                    while (head) {
                        bool drain_match = false;
                        if (numa_mode) {
                            uint32_t head_minor = head->pkt.minor_idx & ~FLAG_MAJOR_EOF;
                            drain_match = (head->pkt.major_idx == expected_major && head_minor == expected_minor);
                        } else {
                            drain_match = (head->pkt.major_idx == expected_major);
                        }

                        if (!drain_match) break;

                        struct BufferedPacket *tmp = head;
                        if (memfd_mode) {
                            off_t offset = (off_t)tmp->pkt.off;
                            if (use_zerocopy) sendfile(1, tmp->pkt.fd, &offset, tmp->pkt.len);
                            else ring_copy_chunk(tmp->pkt.fd, 1, offset, tmp->pkt.len);
                            
                            off_t aligned_start = (tmp->pkt.off / 4096) * 4096;
                            fallocate(tmp->pkt.fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, tmp->pkt.len);
                        }
                        
                        if (numa_mode) {
                            expected_minor += tmp->pkt.cnt; 
                            if (tmp->pkt.minor_idx & FLAG_MAJOR_EOF) { expected_major++; expected_minor = 0; }
                        } else {
                            expected_major += tmp->pkt.cnt;
                        }
                        
                        head = tmp->next;
                        xfree(tmp); 
                    }
                }
            } else {
                struct BufferedPacket *n = xmalloc(sizeof(struct BufferedPacket));
                n->pkt = *op;
                struct BufferedPacket **curr = &head;
                
                uint64_t n_key = numa_mode ? PACK_KEY(op->major_idx, actual_minor) : op->major_idx;
                
                while (*curr) {
                    uint32_t c_minor = (*curr)->pkt.minor_idx & ~FLAG_MAJOR_EOF;
                    uint64_t c_key = numa_mode ? PACK_KEY((*curr)->pkt.major_idx, c_minor) : (*curr)->pkt.major_idx;
                    if (c_key >= n_key) break;
                    curr = &((*curr)->next);
                }
                n->next = *curr;
                *curr = n;
            }
        }
    }
    
    while (head) { struct BufferedPacket *tmp = head; head = head->next; xfree(tmp); }
    return EXECUTION_SUCCESS;
}
