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
    // Returning non-zero automatically triggers forkrun's failure/retry resilience machinery!
    return 0; 
}
```

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

If your native C code needs to know *which* batch it is processing, its byte offset in the file, or if it is recovering from a crash, `forkrun` can pass a detailed context struct directly to your function as a 3rd argument. 

Because `forkrun` is a zero-dependency, single-file deployment, we provide two ways to access this struct:

### Option A: The Header File (For structured projects)
Download `forkrun_plugin.h` from the repository and include it in your project.

```c
#include "forkrun_plugin.h"

// 1. Opt-in flag: Tell forkrun to pass the context pointer
int forkrun_use_ctx = 1;

// 2. Define your function with the 3-argument signature
int my_func(int argc, char **argv, const struct forkrun_ctx *ctx) {
    
    printf("Worker %u processing batch %lu\n", ctx->worker_id, ctx->batch_index);
    return 0;
}
```

### Option B: Copy-Paste (For single-file scripts / restricted nodes)
You do not actually *need* the header file. Because C only cares about memory layout, you can simply paste the struct definition directly into the top of your `plugin.c` file. This allows you to write, compile, and run C-plugins on highly restricted HPC login nodes without managing include paths.

```c
#include <stdint.h>
#include <stdio.h>

// 1. Opt-in flag: Tell forkrun we want the context!
int forkrun_use_ctx = 1;

// 2. The Context Struct (Matches forkrun v3.2.1+ layout)
struct forkrun_ctx {
    uint64_t batch_index;       // Global batch sequence number
    uint64_t batch_offset;      // Byte offset in the shared memfd
    uint64_t batch_byte_length; // Length of the current batch in bytes
    uint32_t version;           // Struct version (currently 1)
    uint32_t worker_id;         // Internal Worker ID (0 to N)
    uint32_t node_id;           // NUMA node ID
    uint32_t num_kills;         // Retry count (if batch previously failed)
    uint32_t numa_major;        // NUMA major sequence (0 if UMA)
    uint32_t numa_minor;        // NUMA minor sequence (0 if UMA)
    int32_t  fd_in;             // Read-only file descriptor to the memfd
    char     delimiter;         // The record delimiter character
    char     _pad[3];           // Internal memory alignment padding
};

// 3. Process the data
int my_func(int argc, char **argv, const struct forkrun_ctx *ctx) {
    
    // Safely check ABI version before accessing newer fields
    if (ctx->version >= 1) {
        printf("Worker %u mapping %lu bytes at offset %lu\n", 
               ctx->worker_id, ctx->batch_byte_length, ctx->batch_offset);
    }
    
    return 0;
}
```

---

## §3. How the ABI Trick Works (Under the Hood)

If you are a systems hacker, you might wonder how `forkrun` handles dynamically loading functions that might have 2 arguments OR 3 arguments without corrupting the stack.

`forkrun` uses `dlsym` to inspect the loaded `.so` for the `forkrun_use_ctx` variable. 
* If it finds the flag and it equals `1`, `forkrun` executes the callback using the 3-argument signature, passing the context pointer. 
* If it does not find the flag, it falls back to the standard 2-argument signature.

This guarantees total POSIX compliance and avoids Undefined Behavior, while giving power-users zero-overhead access to `forkrun`'s internal ring metadata. Furthermore, the `_pad[3]` buffer ensures strictly aligned 8-byte memory boundaries regardless of underlying hardware architecture, and the `version` tag allows us to expand the context in future v3.x releases without breaking older plugins.
