/* forkrun_shim.h — W-DEDUP R-D8 ABI gate (signatures only).
 *
 * GENERATED FILE — do not edit. Regenerate with:
 *   python3 tools/gen_shim.py
 * Single source: python/forkrun/_shim.c (the fr_py_*
 * definitions). CI enforces `gen_shim.py --check`
 * (committed output must match).
 *
 * Scope: declarations, argument types, return types only.
 * No semantic contracts (see test_invariant_gate.py §3/§6/§9).
 * Extern entries are the dlsym-visible ABI surface (45);
 * static entries are internal (listed with linkage in
 * shim_signatures.json, omitted here).
 *
 * Header hygiene (substrate rules): self-contained (no includes
 * beyond <stdint.h>, include-guarded, FTM-independent,
 * order-independent (alphabetical within linkage class).
 */
#ifndef FORKRUN_SHIM_H
#define FORKRUN_SHIM_H

#include <stdint.h>

/* Opaque forward decls for struct out-params (defined in _shim.c).
 * The header carries signatures, not layouts — ctypes binds
 * layouts positionally in _bindings.py (checked by
 * test_shim_abi.py against shim_signatures.json). */
typedef struct fr_py_batch fr_py_batch_t;
typedef struct fr_py_record_desc fr_py_record_desc_t;
typedef struct FrPyInterval FrPyInterval_t;

int fr_py_abort(void);
int fr_py_abort_reason(void);
int fr_py_ack(int fallow_fd, int target_fd);
int fr_py_ack_direct(int fallow_fd, int target_fd);
int fr_py_ack_init(int fd);
uint64_t fr_py_backlog_node(int node);
int fr_py_claim(fr_py_batch_t *out);
int fr_py_complete(int signal_fd, uint64_t wid, uint64_t batch_idx, int fallow_fd, int out_fd, const char *data, uint64_t data_len);
int64_t fr_py_copy_range(int src_fd, uint64_t src_off, int dst_fd, uint64_t dst_off, uint64_t length);
uint64_t fr_py_data_ready(void);
uint64_t fr_py_data_ready_node(int node);
int fr_py_destroy(void);
int fr_py_diag_node(int node, uint64_t *out);
int fr_py_drain_loop(int signal_r, const int *out_fds, int num_workers, int results_fd, int drain_mode);
int fr_py_emit(int out_fd, int signal_fd, uint64_t wid, uint64_t batch_idx, const char *data, uint64_t data_len);
int fr_py_escrow_deposit(unsigned int kills);
int fr_py_exec_spawn(char **argv, int argc, uint64_t in_off, uint64_t in_len, int ingress_fd, int out_fd, uint64_t batch_idx);
int fr_py_fallow_loop(int pipe_r, int memfd);
int fr_py_fallow_phys(int fd_in, int fd_file);
void * fr_py_get_raw_window(int fd, uint64_t offset, uint64_t length);
int fr_py_indexer_numa(int memfd, int node_id);
int fr_py_ingest_data_post(void);
int fr_py_ingest_done(void);
int fr_py_ingest_eof_posted(void);
int fr_py_init(int lines, int bytes);
int fr_py_init_numa(int lines, int bytes, int num_nodes, const char *numa_map);
int fr_py_is_resume_mode(void);
int fr_py_map_readonly(int fd, uint64_t length, uint64_t *out_addr);
int fr_py_numa_ingest(int infd, int outfd, int num_nodes);
int fr_py_numa_scanner(int memfd, int node_id, int fd_spawn, int num_nodes);
int fr_py_orderer(int order_pipe_r, int output_fd, int unordered_mode, int numa_mode);
int fr_py_output_advanced(uint64_t nbytes);
int64_t fr_py_parse_descriptors(const char *input, uint64_t input_len, struct fr_py_record_desc *descriptors, uint64_t max_descriptors);
int fr_py_plugin_call(const char *path, const char *func_name, int ingress_fd, int out_fd, uint64_t batch_off, uint64_t batch_len, uint64_t batch_idx, uint32_t line_count, uint32_t num_kills, int wid, int wincarn);
unsigned int fr_py_poisoned_count(void);
int fr_py_recover_worker(int wid, int incarnation, int output_fd, int exit_code);
int fr_py_resume_snapshot(uint64_t *horizon, uint64_t *stdout_bytes, struct FrPyInterval *jagged, uint32_t *count_out, uint32_t max_jagged);
int fr_py_scan(int fd);
int fr_py_scan_with_spawn(int fd, int spawn_w);
int fr_py_set_order_pipe(int fd);
int fr_py_set_output_fd(int fd);
int fr_py_set_resume_state(uint64_t horizon, uint64_t stdout_bytes, const struct FrPyInterval *jagged, uint32_t jagged_count);
int64_t fr_py_spill_sequential(int src_fd, int dst_fd, uint64_t max_bytes);
void fr_py_unmap(uint64_t addr, uint64_t length);
const char * fr_py_version(void);
int fr_py_worker_init(int wid, int node_id, int wincarn, int retry_limit, int debug);
int fr_py_worker_plugin_loop(int wid, const char *path, const char *func_name, int ingress_fd, int out_fd, int signal_fd, int fallow_fd, int order_fd, int trap_ack_fd, int wincarn, int retry_limit, int on_error);
int fr_py_worker_spawn_loop(int wid, char **argv, int argc, int ingress_fd, int out_fd, int signal_fd, int fallow_fd, int order_fd, int trap_ack_fd, int wincarn, int retry_limit, int on_error);
int fr_py_worker_splice_loop(int wid, int ingress_fd, int out_fd, int signal_fd, int fallow_fd);

#endif /* FORKRUN_SHIM_H */
