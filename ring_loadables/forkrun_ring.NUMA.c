#include <sys/syscall.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>
#include <stdbool.h>
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


// ==============================================================================
// 1. INGEST: Born-Local Allocation & Feedback Routing
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

            // Passing mask_words * 64 is the exact bit capacity allocated
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


// ==============================================================================
// 2. INDEXER: The O(1) Boundary Router
// ==============================================================================
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


// ==============================================================================
// 3. SCANNER: The NUMA-Local Dispatcher & Stealer
// ==============================================================================
static inline void emit_batch(uint64_t start, uint64_t end, uint32_t major, uint32_t minor, bool is_last) {
    uint64_t idx = atomic_fetch_add(&state->write_idx, 1);
    
    state->offset_ring[idx & RING_MASK] = start;
    state->offset_ring[(idx + 1) & RING_MASK] = end;
    state->major_ring[idx & RING_MASK] = major;
    state->minor_ring[idx & RING_MASK] = minor | (is_last ? FLAG_MAJOR_EOF : 0);
}

static int ring_numa_scanner_main(int argc, char **argv) {
    if (argc < 6) return EXECUTION_FAILURE;

    int memfd      = atoi(argv[1]);
    int my_node_id = atoi(argv[2]);
    int claim_pipe = atoi(argv[3]);
    int num_nodes  = atoi(argv[4]);

    int *node_pipes = xmalloc(num_nodes * sizeof(int));
    for (int i = 0; i < num_nodes; i++) {
        node_pipes[i] = atoi(argv[5 + i]);
    }

    uint64_t target_lines = state->cfg_batch_start; 
    bool byte_mode = state->mode_byte;
    char *buf = xmalloc_aligned(get_optimal_chunk_size());

    int active_pipe_idx = my_node_id; 
    int pipes_tried = 0;

    while (pipes_tried < num_nodes) {
        int current_pipe = node_pipes[active_pipe_idx];
        struct ScannerTask task;
        
        // Polling logic: Wait 10ms for home node, 0ms (instant) for steal attempts
        struct pollfd pfd = { .fd = current_pipe, .events = POLLIN };
        int timeout_ms = (active_pipe_idx == my_node_id) ? 10 : 0;
        
        if (poll(&pfd, 1, timeout_ms) <= 0) {
            active_pipe_idx = (active_pipe_idx + 1) % num_nodes;
            pipes_tried++;
            continue;
        }

        ssize_t r = read(current_pipe, &task, sizeof(task));
        
        if (r == sizeof(task)) {
            pipes_tried = 0; // Reset Steal Counter
            write(claim_pipe, &active_pipe_idx, sizeof(active_pipe_idx));

            uint64_t chunk_end = task.start_off + task.length;
            uint64_t current_off = task.start_off;
            uint32_t minor_idx = 0;

            if (task.length == 0) {
                emit_batch(current_off, current_off, task.major_id, 0, true);
                SCANNER_WAKE();
                continue;
            }

            int batches_this_chunk = 0;

            while (current_off < chunk_end) {
                uint64_t batch_end = current_off;
                
                if (byte_mode) {
                    batch_end += target_lines; 
                    if (batch_end > chunk_end) batch_end = chunk_end;
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
                }

                bool is_last = (batch_end >= chunk_end);
                emit_batch(current_off, batch_end, task.major_id, minor_idx++, is_last);
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

    // Signal completion so workers can break the wait loop
    atomic_store_release(&state->scanner_finished, 1);
    SCANNER_WAKE();
    
    xfree(buf);
    xfree(node_pipes);
    return EXECUTION_SUCCESS;
}

// ==============================================================================
// 4. RING_ORDER: The Major/Minor Sorter
// ==============================================================================
struct BufferedPacket { struct OrderPacket pkt; struct BufferedPacket *next; };

static int ring_order_main(int argc, char **argv) {
    if (argc < 3) return EXECUTION_FAILURE;
    int fd_in = atoi(argv[1]);
    bool memfd_mode = (strcmp(argv[2], "memfd") == 0);
    const char *prefix = argv[2]; 
    bool unordered_mode = (argc > 3 && strcmp(argv[3], "unordered") == 0);

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
            
            if (unordered_mode || (op->major_idx == expected_major && op->minor_idx == expected_minor)) {
                
                // Process Immediately
                if (memfd_mode) {
                    off_t offset = (off_t)op->off;
                    if (use_zerocopy) sendfile(1, op->fd, &offset, op->len);
                    else ring_copy_chunk(op->fd, 1, offset, op->len);
                    
                    off_t aligned_start = (op->off / 4096) * 4096;
                    fallocate(op->fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, op->len);
                } else {
                    char path[256];
                    snprintf(path, sizeof(path), "%s.%u.%u", prefix, op->major_idx, op->minor_idx); 
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
                    uint32_t raw_cnt = op->cnt & ~FLAG_MAJOR_EOF;
                    expected_minor += raw_cnt;
                    
                    if (op->cnt & FLAG_MAJOR_EOF) {
                        expected_major++;
                        expected_minor = 0;
                    }
                    
                    // Drain loop
                    while (head && head->pkt.major_idx == expected_major && head->pkt.minor_idx == expected_minor) {
                        struct BufferedPacket *tmp = head;
                        
                        if (memfd_mode) {
                            off_t offset = (off_t)tmp->pkt.off;
                            if (use_zerocopy) sendfile(1, tmp->pkt.fd, &offset, tmp->pkt.len);
                            else ring_copy_chunk(tmp->pkt.fd, 1, offset, tmp->pkt.len);
                            
                            off_t aligned_start = (tmp->pkt.off / 4096) * 4096;
                            fallocate(tmp->pkt.fd, FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE, aligned_start, tmp->pkt.len);
                        }
                        
                        raw_cnt = tmp->pkt.cnt & ~FLAG_MAJOR_EOF;
                        expected_minor += raw_cnt;
                        
                        if (tmp->pkt.cnt & FLAG_MAJOR_EOF) {
                            expected_major++;
                            expected_minor = 0;
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
                
                uint64_t n_key = PACK_KEY(n->pkt.major_idx, n->pkt.minor_idx);
                
                while (*curr) {
                    uint64_t c_key = PACK_KEY((*curr)->pkt.major_idx, (*curr)->pkt.minor_idx);
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
