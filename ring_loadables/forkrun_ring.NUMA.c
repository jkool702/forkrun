// ==============================================================================
// 1. INCLUDES, MACROS, AND TLS VARIABLES
// (Add these near the top of your file, with the other includes/macros)
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

// TLS OPTIMIZATION: Cache claim metadata to avoid C->Bash->C roundtrip in ring_ack
static __thread uint64_t worker_last_idx = 0;
static __thread uint64_t worker_last_cnt = 0;
static __thread uint32_t worker_last_major = 0; // NEW FOR NUMA
static __thread uint32_t worker_last_minor = 0; // NEW FOR NUMA

// ==============================================================================
// 2. UPDATED STRUCTURES
// (Replace your existing SharedState and OrderPacket, and add the new ones)
// ==============================================================================

struct IngestPacket {
    uint64_t offset;
    uint64_t length;
    uint32_t node_id;
    uint32_t major_id;
}; // 24 bytes

struct ScannerTask {
    uint32_t major_id;
    uint32_t pad;
    uint64_t start_off;
    uint64_t length;
}; // 24 bytes

struct OrderPacket {
    uint32_t major_idx; // Chunk identifier (or legacy absolute idx)
    uint32_t minor_idx; // Batch within chunk + FLAG_MAJOR_EOF
    uint32_t cnt;       // Number of ring slots claimed
    int32_t  fd;
    uint64_t off;
    uint64_t len;
}; // 32 bytes

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
    
    // RING ARRAYS
    uint16_t stride_ring[RING_SIZE] ALIGNED(4096);
    uint64_t offset_ring[RING_SIZE] ALIGNED(4096);
    
    // NUMA EXTENSIONS
    uint64_t end_ring[RING_SIZE] ALIGNED(4096);
    uint32_t major_ring[RING_SIZE] ALIGNED(4096);
    uint32_t minor_ring[RING_SIZE] ALIGNED(4096);
    uint32_t numa_enabled;
};

// ==============================================================================
// 3. NEW NUMA LOADABLES
// (Add these to your file. Don't forget to add them to FORKRUN_LOADABLES(X)!)
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

    // Make claim pipe non-blocking
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
    memset(backlogs, 0, num_nodes * sizeof(int));

    // NUMA availability check
    unsigned long test_mask = 1UL;
    bool numa_enabled = (syscall(__NR_set_mempolicy, MPOL_BIND, &test_mask, 64) == 0);
    if (numa_enabled) {
        syscall(__NR_set_mempolicy, MPOL_DEFAULT, NULL, 0); // Reset after check
    } else {
        num_nodes = 1;
    }

    int mask_words = (num_nodes + 63) / 64;
    unsigned long *nodemask = xmalloc(mask_words * sizeof(unsigned long));

    while (1) {
        // Drain feedback
        uint32_t claimed_node;
        while (read(claim_pipe, &claimed_node, sizeof(claimed_node)) == sizeof(claimed_node)) {
            if (claimed_node < (uint32_t)num_nodes && backlogs[claimed_node] > 0)
                backlogs[claimed_node]--;
        }

        // Choose target
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

        // Membind
        if (numa_enabled && num_nodes > 1) {
            memset(nodemask, 0, mask_words * sizeof(unsigned long));
            nodemask[target_node / 64] |= (1UL << (target_node % 64));

            if (syscall(__NR_set_mempolicy, MPOL_BIND, nodemask, mask_words * 64) < 0) {
                backlogs[target_node] += 10000; // Penalize offline node
                continue;
            }
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

    // Sentinel EOF
    struct IngestPacket sentinel = { .offset = current_offset, .length = 0, .node_id = 0, .major_id = UINT32_MAX };
    write(index_pipe, &sentinel, sizeof(sentinel));

    return EXECUTION_SUCCESS;
}

static int ring_indexer_numa_main(int argc, char **argv) {
    if (argc < 4) return EXECUTION_FAILURE;

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

        // O(1) Tail Scan: Only look at the final 64KB
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

        struct ScannerTask task = { .major_id = pkt.major_id, .start_off = actual_start, .pad = 0 };

        if (found_newline) {
            task.length = actual_end - actual_start;
            actual_start = actual_end; 
        } else {
            task.length = 0; // Roll data forward, maintain ordering index
        }

        int target = node_pipes[pkt.node_id % num_node_pipes];
        if (write(target, &task, sizeof(task)) != sizeof(task)) break;
        
        last_major_seen = pkt.major_id;
    }

    // Trailing data fix
    if (pkt.major_id == UINT32_MAX && actual_start < pkt.offset) {
        struct ScannerTask final_task = {
            .major_id  = last_major_seen + 1,
            .start_off = actual_start,
            .length    = pkt.offset - actual_start,
            .pad       = 0
        };
        write(node_pipes[0], &final_task, sizeof(final_task));
    }

    xfree(node_pipes);
    return EXECUTION_SUCCESS;
}

static inline void emit_batch(uint64_t start, uint64_t end, uint32_t major, uint32_t minor, bool is_last, uint16_t stride) {
    uint64_t idx = atomic_fetch_add(&state->write_idx, 1);
    
    state->offset_ring[idx & RING_MASK] = start;
    state->end_ring[idx & RING_MASK]    = end;
    state->stride_ring[idx & RING_MASK] = stride;
    state->major_ring[idx & RING_MASK]  = major;
    state->minor_ring[idx & RING_MASK]  = minor | (is_last ? FLAG_MAJOR_EOF : 0);
}

static int ring_numa_scanner_main(int argc, char **argv) {
    if (argc < 6) return EXECUTION_FAILURE;

    int memfd      = atoi(argv[1]);
    int my_node_id = atoi(argv[2]);
    int claim_pipe = atoi(argv[3]);
    int num_nodes  = atoi(argv[4]);

    int *node_pipes = xmalloc(num_nodes * sizeof(int));
    for (int i = 0; i < num_nodes; i++) node_pipes[i] = atoi(argv[5 + i]);

    uint64_t target_lines = state->cfg_batch_start; 
    bool byte_mode = state->mode_byte;
    char *buf = xmalloc_aligned(get_optimal_chunk_size());

    int active_pipe_idx = my_node_id; 
    int pipes_tried = 0;
    int home_poll_count = 0;

    // Signal to claim_main that we are using NUMA independent-slot layout
    state->numa_enabled = 1;

    while (pipes_tried < num_nodes) {
        int current_pipe = node_pipes[active_pipe_idx];
        struct ScannerTask task;
        
        // Non-blocking / Exponential Backoff Polling
        struct pollfd pfd = { .fd = current_pipe, .events = POLLIN };
        if (active_pipe_idx != my_node_id) {
            if (poll(&pfd, 1, 0) <= 0) { // Instant timeout for stealing
                active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
                pipes_tried++;
                continue;
            }
        } else {
            int timeout = (10 << home_poll_count);
            if (timeout > 1000) timeout = 1000;
            if (poll(&pfd, 1, timeout) <= 0) {
                home_poll_count++;
                active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
                pipes_tried++;
                continue;
            }
            home_poll_count = 0;
        }

        ssize_t r = read(current_pipe, &task, sizeof(task));
        
        if (r == sizeof(task)) {
            pipes_tried = 0; 
            write(claim_pipe, &active_pipe_idx, sizeof(active_pipe_idx));

            uint64_t chunk_end = task.start_off + task.length;
            uint64_t current_off = task.start_off;
            uint32_t minor_idx = 0;

            if (task.length == 0) {
                emit_batch(current_off, current_off, task.major_id, 0, true, 0);
                SCANNER_WAKE();
                continue;
            }

            int batches_this_chunk = 0;

            while (current_off < chunk_end) {
                uint64_t batch_end = current_off;
                uint16_t stride = 0;
                
                if (byte_mode) {
                    batch_end += target_lines; 
                    if (batch_end > chunk_end) batch_end = chunk_end;
                    stride = batch_end - current_off;
                } else {
                    size_t to_read = (chunk_end - current_off > get_optimal_chunk_size()) 
                                   ? get_optimal_chunk_size() : (chunk_end - current_off);
                    pread(memfd, buf, to_read, current_off);
                    
                    uint64_t lines_found = 0;
                    char *p = buf, *end = buf + to_read;
                    while (lines_found < target_lines && p < end) {
                        char *nl = memchr(p, '\n', end - p);
                        if (nl) { lines_found++; p = nl + 1; }
                        else { p = end; break; }
                    }
                    batch_end = current_off + (p - buf);
                    stride = lines_found;
                }

                bool is_last = (batch_end >= chunk_end);
                emit_batch(current_off, batch_end, task.major_id, minor_idx++, is_last, stride);
                current_off = batch_end;
                
                if (++batches_this_chunk >= 4) {
                    SCANNER_WAKE();
                    batches_this_chunk = 0;
                }
            }
            SCANNER_WAKE();

        } else {
            active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
            pipes_tried++;
        }
    }

    atomic_store_release(&state->scanner_finished, 1);
    SCANNER_WAKE(); // Wake workers so they can exit gracefully
    
    xfree(buf);
    xfree(node_pipes);
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// 4. UPDATED EXISTING LOADABLES
// (Replace your full ring_claim_main, ring_ack_main, and ring_order_main)
// ==============================================================================

static int ring_claim_main(int argc, char **argv) {
    const char *v_target = "REPLY";
    int fd_read = -1;

    // Arg parsing: [VAR] [FD] | [OFF] [VAR] [FD]
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

    uint64_t my_read_idx;
    uint64_t claim_count = 1;
    int spin = 0;
    
    if (fd_read < 0) fd_read = worker_cached_fd;
    
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
            if (state->numa_enabled) {
                // NUMA mode implies independent slot processing
                claim_count = 1;
            } else {
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
                    } else {
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
            }
            if (r_curr + claim_count > w_snap) claim_count = w_snap - r_curr;
            my_read_idx = atomic_fetch_add(&state->read_idx, claim_count);
            
            if (!state->numa_enabled) {
                int64_t sbatch = atomic_load_relaxed(&state->signed_batch_size);
                if (sbatch < 0) {
                    uint64_t Ib = atomic_load_relaxed(&state->batch_change_idx);
                    if (my_read_idx > Ib) {
                         int64_t target = -sbatch;
                         atomic_compare_exchange(&state->signed_batch_size, &sbatch, target);
                    }
                }
            }
            break;
        }
        
        if (atomic_load_acquire(&state->scanner_finished)) {
            if (atomic_fetch_sub(&state->active_workers, 1) == 1) return 2; 
            bind_var_or_array(v_target, "0", 0);
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
    if (!state->numa_enabled && my_read_idx + claim_count > w_curr) {
         if (atomic_load_acquire(&state->scanner_finished)) {
             int64_t diff = (int64_t)w_curr - (int64_t)my_read_idx;
             if (diff < 0) diff = 0;
             claim_count = (uint64_t)diff;
             if (claim_count == 0) { spin = 0; goto restart_loop; }
         } else {
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

    uint64_t final_val = 0;

    if (state->numa_enabled) {
        claim_count = 1; 
        if (state->cfg_return_bytes) {
            uint64_t start = state->offset_ring[my_read_idx & RING_MASK];
            uint64_t end   = state->end_ring[my_read_idx & RING_MASK];
            final_val = end - start;
        } else {
            final_val = state->stride_ring[my_read_idx & RING_MASK];
        }
    } else {
        // Legacy Mode
        if (state->cfg_return_bytes) {
            uint64_t start = state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
            uint64_t end = state->offset_ring[(my_read_idx + claim_count) & RING_MASK] & ~FLAG_PARTIAL_BATCH;
            final_val = end - start;
        } else {
            if (claim_count == 1) final_val = state->stride_ring[my_read_idx & RING_MASK];
            else for (uint64_t i = 0; i < claim_count; i++) final_val += state->stride_ring[(my_read_idx + i) & RING_MASK];
        }
    }
    
    atomic_fetch_add(&state->total_lines_consumed, (state->cfg_return_bytes) ? claim_count : final_val);

    worker_last_idx = my_read_idx;
    worker_last_cnt = claim_count;
    
    char buf[64];
    u64toa(final_val, buf); bind_var_or_array(v_target, buf, 0);
    
    u64toa(my_read_idx, buf); bind_variable("RING_BATCH_IDX", buf, 0);
    u64toa(claim_count, buf); bind_variable("RING_BATCH_SLOTS", buf, 0);

    if (state->numa_enabled) {
        worker_last_major = state->major_ring[my_read_idx & RING_MASK];
        worker_last_minor = state->minor_ring[my_read_idx & RING_MASK];
        
        sprintf(buf, "%u", worker_last_major); 
        bind_variable("RING_MAJOR", buf, 0);
        sprintf(buf, "%u", worker_last_minor & ~FLAG_MAJOR_EOF); 
        bind_variable("RING_MINOR", buf, 0);
    }
    
    if (fd_read >= 0) {
        uint64_t start_offset = state->offset_ring[my_read_idx & RING_MASK] & ~FLAG_PARTIAL_BATCH;
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
        if (state && state->numa_enabled) {
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
        if (state && state->numa_enabled) {
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
                // Process Immediately
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
                
                // Advance State & Drain Buffer
                if (!unordered_mode) {
                    if (numa_mode) {
                        expected_minor++;
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
                            expected_minor++;
                            if (tmp->pkt.minor_idx & FLAG_MAJOR_EOF) { expected_major++; expected_minor = 0; }
                        } else {
                            expected_major += tmp->pkt.cnt;
                        }
                        
                        head = tmp->next;
                        xfree(tmp); 
                    }
                }
            } else {
                // Buffer out-of-order packet
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
