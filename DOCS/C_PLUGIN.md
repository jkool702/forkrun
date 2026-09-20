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
* **Version 2 (`forkrun_use_ctx = 2`, v3.5.0+):** High-precision packed context (128-byte frozen layout). Replaces major/minor with a 64-bit `numa_batch_id` union (`(major << 22) | minor`), preserving full 42-bit major chunk sequence numbers for billion-record runs. Globally unique on both UMA and NUMA; on UMA it equals `batch_index` exactly (derived from the 64-bit claim index).

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

---

## §4. Raw Window Delivery (`FLAG_RAW`, v3.5.2+)

The third delivery mode for C plugins (`-C`). Instead of tokenized argv
strings, the plugin receives a borrowed, zero-copy pointer to the batch's
bytes in shared memory, plus the byte length — no tokenization, no copy.
It is the C-tier analogue of the Python frontend's `Batch.data` contract
(the same borrowed-window lifetime, the same stability guarantee, the same
absolute plane coordinates).

**Precedence (binding):** if the plugin declares `FLAG_RAW`, raw window
delivery overrides everything — argv tokenization, stdin delivery, the
user's `-s`/`-b` flags. The plugin's ABI opt-in is authoritative over the
user's CLI presentation choice.

### The contract

- `ctx->reserved[0]` is `data` when `FLAG_RAW` is granted: a borrowed
  `const void *` to `[batch_offset, batch_offset + batch_byte_length)`.
  Zero when the flag is not granted. `reserved[1..5]` remain zero.
- **Borrowed:** valid for the duration of the callback only. Do not store
  the pointer across batches.
- **Stable during the callback:** the window's bytes are immutable while
  your function runs (see the stability note below).
- **Address not stable across calls:** the engine may `mremap` its
  persistent view as the stream grows, so the pointer value for two
  batches may differ even for adjacent offsets. Only offset+length
  identity is stable — never compare pointers across batches.
- **`fd_in` escape hatch:** `fd_in` remains populated. Plugins that prefer
  `pread` (or their own `mmap` with page-aligned arithmetic) can ignore
  `data` and use `batch_offset`/`batch_byte_length`/`fd_in` directly.
- **argv still valid:** `argc`/`argv` contain ONLY the fixed arguments
  (`frun -C plug.so:fn --mode fast` → `argc=2`, `argv={"--mode","fast"}`).
  No batch data is tokenized into argv in raw mode.
- **Metadata still populated:** `batch_offset`, `batch_byte_length`,
  `batch_lines`, and `delimiter` are valid in raw mode. `batch_lines`
  counts delimiter-terminated records (`wc -l` semantics); `0` means
  undefined (`-b` byte mode). Scan for `ctx->delimiter` to split records.
- **Raw requires v2:** a v1 plugin (`forkrun_use_ctx = 1 | FLAG_RAW`) gets
  the flag masked to zero, argv delivery, and a dlopen-time warning on
  stderr. Use `forkrun_use_ctx = 2 | FLAG_RAW`.
- **Old-engine compatibility:** a v2 plugin requesting `FLAG_RAW` on a
  pre-v3.5.2 engine gets `flags_granted = 0` and argv delivery (the
  existing negotiation contract — unknown flags are simply ungranted).
  Always check the grant and implement the argv fallback.

### The negotiation pattern

```c
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>  /* write */
#include "forkrun_plugin.h"

/* Request dialect 2 + raw window delivery. */
int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

static const void *raw_data(const struct forkrun_ctx *ctx) {
    return (const void *)(uintptr_t)ctx->reserved[0];
}

int my_raw_fn(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx->version >= 2 && (ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) {
        /* Raw path: borrowed window, zero-copy. */
        const char *data = (const char *)raw_data(ctx);
        size_t len = (size_t)ctx->batch_byte_length;
        size_t off = 0;
        while (off < len) {
            ssize_t w = write(STDOUT_FILENO, data + off, len - off);
            if (w < 0) return 1;
            off += (size_t)w;
        }
        (void)argc; (void)argv;  /* fixed args available but unused here */
        return 0;
    }
    /* Fallback path: pre-v3.5.2 engine (or flag ungranted) — argv. */
    for (int i = 0; i < argc; i++) {
        size_t n = strlen(argv[i]);
        size_t off = 0;
        while (off < n) {
            ssize_t w = write(STDOUT_FILENO, argv[i] + off, n - off);
            if (w < 0) return 1;
            off += (size_t)w;
        }
        if (write(STDOUT_FILENO, "\n", 1) != 1) return 1;
    }
    return 0;
}
```

Compile and run as usual:

```bash
gcc -O3 -shared -fPIC plugin_raw.c -o plugin_raw.so
frun -k -C ./plugin_raw.so:my_raw_fn < massive_dataset.txt
```

(`-k` orders the per-batch windows back into input order for byte-exact
output. Without `-k`, windows are still individually exact but may
interleave.)

### Why the window is safe (mmap-stability note)

The engine holds a persistent `MAP_SHARED`/`PROT_READ` mmap of the ingress
memfd in each worker (lazily mapped on the first raw batch, grown with
`mremap` as the stream grows, never unmapped per batch). The borrowed
pointer is `base + batch_offset`. The window is stable during the callback
because (a) ingest is append-only past the window's end, (b) tokenization
never writes the shared memfd (all tokenize paths use private `pread`
buffers), and (c) fallow punches holes only *behind the acked contiguous
prefix* — this batch is unacked, therefore its pages are intact. This is
the same guarantee the Python frontend's `Batch.data` relies on; the C
tier proves it first.

---

## §5. Stdin Delivery (`-s`/`-b` with `-C`, v3.5.2+)

The second v3.5.2 delivery mode for C plugins. When the user passes `-s`
(or `-b`, which implies stdin) with `-C`, and the plugin has NOT declared
`FLAG_RAW`, the batch data is delivered on the plugin's stdin (fd 0) as a
byte stream terminated by EOF. This is the C-plugin analogue of external
`-s` mode — with the spawn amputated: no `posix_spawnp` per batch, just an
in-process callback whose fd 0 the engine feeds before/during the call.

**Precedence:** `FLAG_RAW` (checked first) > stdin mode > argv tokenize.
A raw plugin invoked with `-s` receives the window, never a stdin feed.

### The contract

- Read fd 0 until EOF (v1 style), or read exactly
  `ctx->batch_byte_length` bytes (v2 style). Both patterns below.
- **Partial consumption is tolerated:** a plugin may read a prefix and
  return (like `head` with external `-s`). The unconsumed remainder is
  discarded; the next batch starts clean — no drift, no corruption.
- **The ctx is unchanged:** `batch_offset`, `batch_byte_length`,
  `batch_lines`, `delimiter`, and `fd_in` are populated exactly as in argv
  mode. Stdin mode is purely a delivery convention.
- **`-b` composes:** byte-mode chunks travel through a byte-transparent
  pipe — no NUL truncation, no delimiter scanning. (This closes the gap
  that made `-C` + `-b` + argv broken: argv strings cannot hold NULs.)
- **argv still valid:** `argc`/`argv` contain ONLY the fixed arguments.
  No batch data is tokenized into argv in stdin mode.

### The v2 pattern (length-bounded read)

```c
#include <stdint.h>
#include <unistd.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2;

int my_stdin_fn(int argc, char **argv, const struct forkrun_ctx *ctx) {
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) {
            /* EOF before expected length = infrastructure failure
             * (feeder died mid-batch). Return non-zero so the batch is
             * retried through the existing escrow machinery. */
            return 1;
        }
        /* ... process buf[0..n) ... */
        got += (size_t)n;
    }
    return 0;
}
```

### The v1 pattern (read-to-EOF loop)

```c
#include <unistd.h>

int my_stdin_v1_fn(int argc, char **argv) {
    char buf[65536];
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) break;  /* EOF: end of this batch */
        /* ... process buf[0..n) ... */
    }
    return 0;
}
```

Run it:

```bash
frun -k -C ./plugin_stdin.so:my_stdin_fn -s < massive_dataset.txt
frun -k -C ./plugin_stdin.so:my_stdin_fn -b 4M < binary_blob
```

### How it works (implementation note)

One function, internal dispatch: the bash JIT exports `FORKRUN_C_STDIN=1`
for `-C` + (`-s` | `-b`) — the entire bash-side change — and `ring_call`
reads it as ambient state (`ring_call`'s CLI surface is frozen). Tier split
mirrors external `-s`: small batches (fitting the granted pipe capacity
minus margin) are spliced synchronously with no fork; large batches fork a
SIGCHLD-shielded feeder child (the `ring_exec` pattern verbatim) that
splices concurrently while the parent runs the callback, then `waitpid`.
The child `_exit`s (never returns into bash), ignores SIGPIPE (reader
death reads as EPIPE, not a signal), and scrubs the fork-order mask-hazard
fds (death-pipe write end, trap-ack, fallow). All failure semantics come
from process lifecycle: child death reads as EOF (short read → non-zero
return → escrow/retry), worker death orphaning the child EPIPE-exits it
while the death pipe fires unmasked.
