### `C_PLUGIN.md`

# NATIVE C PLUGINS: "Zero-Tax" Execution (v3.2.1+)

For workloads where absolute maximum throughput is required, `forkrun` can bypass both the Bash AST and external `vfork`/`exec` overhead entirely by loading a native C function and executing it directly inside the persistent worker threads.

We call this **"Zero-Tax" Execution**. It is the fastest possible way to process data in `forkrun`.

When you run an external binary (e.g., `frun -X /bin/my_tool`), the OS still has to `posix_spawnp` a new process for *every single batch*. While `forkrun` makes this incredibly fast, process creation still has a physical limit in the Linux kernel. With the `-C` flag, your C function is loaded via `dlopen`. When a batch is claimed, the worker simply invokes a function pointer. **Process creation overhead drops to literally zero.**

---

## §1. The Basic Interface: Drop-In Replacement

To make porting existing tools as simple as possible, `forkrun` expects your C callback to use the standard POSIX `main`-style signature.

### 1. Write the Plugin (`plugin.c`)
Here is a minimal example. You can literally rename `main` to `my_plugin` in existing C utilities, and they will immediately scale across 64+ cores with zero IPC overhead.

```c
#include <stdio.h>

// Standard signature - acts exactly like a normal CLI program
int my_plugin(int argc, char **argv) {
    // Process each item in the batch
    for (int i = 0; i < argc; i++) {
        // Your blazing-fast data transform here
    }
    
    // Return 0 on success. 
    // Returning 200 (or returning any non-zero code while the -E flag is active) automatically triggers forkrun's resilience machinery.
    // Return code 201 is RESERVED (planned v3.5.1): permanent skip — poison this batch immediately, no retry. Do not use yet.
    return 0; 
}
```

### Plugin Return Codes

| Return | Meaning |
|---|---|
| `0` | Success |
| `1`–`199` | Failure — retried while `-E` is active; poisoned after `FORKRUN_RETRY_LIMIT` |
| `200` | Explicit retry request (always retried regardless of `-E`) |
| `201` | *Reserved (planned v3.5.1)*: Permanent skip (poison immediately, never retry) |
| `137` / `139` | SIGKILL-class / SIGSEGV-class fatal failure (always retried) |
| `254` | Internal engine error |
| `≥ 256` | Truncated to low 8 bits (`256`→`1`, `257`→`1`) |

### 2. Compile as a Shared Library
Compile your C file into an optimized, position-independent shared object (`.so`):

```bash
gcc -O3 -shared -fPIC plugin.c -o plugin.so
```

### 3. Execute with forkrun
Use the `-C` flag and pass the path to your shared object. Append `:function_name` so `forkrun` knows which symbol to load.

```bash
# Syntax: frun -C /path/to/plugin.so:<function_name> < inputs

# Example:
frun -C ./plugin.so:my_plugin < massive_dataset.txt
```

---

## §2. Advanced Usage: The Execution Context

`forkrun` supports two context ABI versions:

* **Version 1 (`forkrun_use_ctx = 1`):** Standard context struct with separate 32-bit `numa_major` and `numa_minor` fields.
* **Version 2 (`forkrun_use_ctx = 2`, v3.5.0+):** High-precision packed context (128-byte frozen cache-aligned layout). Replaces major/minor with a 64-bit `numa_batch_id` union (`(major << 22) | minor`), preserving full 42-bit major chunk sequence numbers for billion-record runs. Globally unique on both UMA and NUMA; on UMA it equals `batch_index` exactly (derived from the 64-bit claim index).

```c
#include <stdint.h>
#include <stdio.h>

// Opt-in flag: 1 = legacy 32-bit fields, 2 = v3.5+ packed 64-bit batch ID
int forkrun_use_ctx = 2;

struct forkrun_ctx {
    uint64_t batch_index;       // Global batch sequence number
    uint64_t batch_offset;      // Byte offset in the shared memfd
    uint64_t batch_byte_length; // Length of the current batch in bytes
    uint32_t version;           // Struct version (1 or 2)
    uint32_t worker_id;         // Internal Worker ID (0 to N)
    uint32_t node_id;           // NUMA node ID
    uint32_t num_kills;         // Retry count (if batch previously failed)
    union {
        uint64_t numa_batch_id; // Version 2: packed (42-bit major << 22 | 22-bit minor)
        struct {
            uint32_t numa_major; // Version 1: truncated 32-bit major
            uint32_t numa_minor; // Version 1: 32-bit minor
        };
    };
    int32_t  fd_in;             // Read-only file descriptor to the memfd
    char     delimiter;         // The record delimiter character
    uint8_t  cfg_state[4];      // Global config state: [0]=cfg_w, [1]=cfg_l, [2]=cfg_b, [3]=flags (SH_STDIN, SH_BMODE)
    /* ---- v2 extension zone (append-only forever) ---- */
    uint32_t batch_lines;       // Records in batch; 0 = undefined (-b byte mode)
    uint32_t struct_size;       // sizeof(struct) as built by THIS engine
    uint32_t worker_incarn;     // Respawn generation of this worker
    uint32_t flags_granted;     // Behavior flags negotiated; dialect >= 2 only
    uint32_t reserved32;        // Alignment padding (zero)
    uint64_t reserved[6];       // Future extension fields (zero in v2)
};

int my_func(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx->version >= 2) {
        uint64_t major = ctx->numa_batch_id >> 22;
        uint32_t minor = ctx->numa_batch_id & 0x3FFFFF;
        printf("Worker %u on Node %u (Major %lu, Minor %u)\n", 
               ctx->worker_id, ctx->node_id, major, minor);
    }
    return 0;
}
```

### Option B: Copy-Paste (For single-file scripts / restricted nodes)
You do not actually *need* the header file. Because C only cares about memory layout, you can simply paste the struct definition directly into the top of your `plugin.c` file. This allows you to write, compile, and run C-plugins on highly restricted HPC login nodes without managing include paths.

```c
#include <stdint.h>
#include <stdio.h>

// 1. Opt-in flag: 2 = v3.5.0+ packed 64-bit batch ID, 1 = legacy 32-bit fields
int forkrun_use_ctx = 2;

// 2. The Context Struct (Matches forkrun v3.5.0+ layout, 128 bytes aligned)
struct forkrun_ctx {
    uint64_t batch_index;       // Global batch sequence number
    uint64_t batch_offset;      // Byte offset in the shared memfd
    uint64_t batch_byte_length; // Length of the current batch in bytes
    uint32_t version;           // Struct version (1 or 2)
    uint32_t worker_id;         // Internal Worker ID (0 to N)
    uint32_t node_id;           // NUMA node ID
    uint32_t num_kills;         // Retry count (if batch previously failed)
    union {
        uint64_t numa_batch_id; // Version 2: packed (42-bit major << 22 | 22-bit minor)
        struct {
            uint32_t numa_major; // Version 1: truncated 32-bit major
            uint32_t numa_minor; // Version 1: 32-bit minor
        };
    };
    int32_t  fd_in;             // Read-only file descriptor to the memfd
    char     delimiter;         // The record delimiter character
    uint8_t  cfg_state[4];      // Global configuration state: [0]=cfg_w, [1]=cfg_l, [2]=cfg_b, [3]=flags
    uint32_t batch_lines;       // Records in batch; 0 = undefined (-b byte mode)
    uint32_t struct_size;       // sizeof(struct) as built by THIS engine
    uint32_t worker_incarn;     // Respawn generation of this worker
    uint32_t flags_granted;     // Behavior flags negotiated; dialect >= 2 only
    uint32_t reserved32;        // Alignment padding (zero)
    uint64_t reserved[6];       // Future extension fields (zero in v2)
};

// 3. Process the data
int my_func(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx->version >= 2) {
        printf("Worker %u mapping %lu bytes at offset %lu (Batch ID: %lu)\n", 
               ctx->worker_id, ctx->batch_byte_length, ctx->batch_offset, ctx->numa_batch_id);
    }
    
    return 0;
}
```

---

## §3. How the ABI Trick Works (Under the Hood)

If you are a systems hacker, you might wonder how `forkrun` handles dynamically loading functions that might have 2 arguments OR 3 arguments without corrupting the stack.

`forkrun` uses `dlsym` to inspect the loaded `.so` for the `forkrun_use_ctx` variable. 
* If it finds the flag and its dialect byte equals `1` or `2`, `forkrun` executes the callback using the 3-argument signature, passing the context pointer. 
* If it does not find the flag (or the dialect is unknown), it falls back to the standard 2-argument signature.
* Plugins test `ctx->version >= 2`, never `== 2`.
* Unknown flags on a known dialect are simply ungranted (`(ctx->flags_granted & FLAG) == 0`); they never trigger legacy fallback.
* Slices into `cfg_state[4]` are: `[0]=cfg_w`, `[1]=cfg_l`, `[2]=cfg_b`, and `[3]=flags (SH_STDIN, SH_BMODE)`.
* `batch_lines` counts delimiter-terminated records (`wc -l` semantics). A final unterminated record may be delivered by the tokenizer as one additional record beyond this count. `0` = undefined (`-b` byte mode).
* Guard tail-field reads with `ctx->struct_size >= offsetof(struct forkrun_ctx, field) + sizeof(field)`; the engine's value is authoritative for what is populated—never compare it to your own `sizeof`.

Calling a 2-argument function through a 3-argument function pointer call site is technically Undefined Behavior by strict ISO C, but is reliable on all supported hardware ABIs (surplus register arguments like RDX or X2 are simply ignored by the callee) — relying on the exact same platform calling-convention invariant as `main(int, char **, char **[])`.

### Zero-Copy Memory Stability (`mmap`)
During the callback invocation, the byte window `[batch_offset, batch_offset + batch_byte_length)` in the shared `memfd` (`fd_in`) is immutable and guaranteed stable. Background fallow hole-punching operates strictly behind the acknowledged consumption horizon, and a worker's batch is acknowledged only *after* the callback returns. Native C plugins and Python/ctypes bindings may therefore safely `mmap` that page-aligned window from `fd_in` and zero-copy read directly (the Apache Arrow / NumPy `frombuffer` pattern).

Note that `mmap` offsets must be page-aligned (`sysconf(_SC_PAGESIZE)`), so consumers must map the *containing* page-aligned window of an unaligned `batch_offset` and adjust their internal pointer accordingly.

*Warning:* Only map within your batch's active byte window; regions behind the fallow horizon may already be hole-punched (reading them yields zeroes).
