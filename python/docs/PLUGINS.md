# Writing C Plugins for forkrun

A plugin is a `.so` exporting `int fn(int argc, char **argv,
const struct forkrun_ctx *ctx)` (dialect 1/2 — the frozen
128B ABI shared with bash `-C`). The engine maps your input
window, you write results to stdout, the shim stages and
frames them. Zero Python per batch.

## Minimal plugin

```c
// myplugin.c — uppercase passthrough. Include the REAL frozen
// header (ring_loadables/forkrun_plugin.h) — never redeclare
// the struct by hand; field order is load-bearing.
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "forkrun_plugin.h"

// Opt into the frozen ctx ABI (dialect 1).
int forkrun_use_ctx = 1;

static int upper_one(int fd_in, unsigned long long off,
                     unsigned long long len) {
    char buf[1 << 20];
    unsigned long long left = len;
    while (left > 0) {
        unsigned long long want = left > sizeof(buf) ? sizeof(buf) : left;
        ssize_t n = pread(fd_in, buf, want, (off_t)(off + len - left));
        if (n <= 0) return -1;
        for (ssize_t i = 0; i < n; i++)
            if (buf[i] >= 'a' && buf[i] <= 'z') buf[i] -= 32;
        if (fwrite(buf, 1, (size_t)n, stdout) != (size_t)n) return -1;
        left -= (uint64_t)n;
    }
    return 0;
}

int process(int argc, char **argv,
            const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!ctx) return 1;
    return upper_one(ctx->fd_in, ctx->batch_offset,
                     ctx->batch_byte_length);
}
```

Build and run (`-I` points at the repo's `ring_loadables/`):

```bash
gcc -O3 -shared -fPIC -I ring_loadables/ -o myplugin.so myplugin.c
python3 -c "
import forkrun
print(len(forkrun.map('./myplugin.so:process', 'data.txt',
                      mode='plugin', workers=8, order='index')))"
```

## The context fields you'll actually use

| Field | Meaning |
|---|---|
| `fd_in` | Input fd — `pread` any byte range |
| `batch_offset` / `batch_byte_length` | Your byte window |
| `batch_index` | Global ordering key |
| `batch_lines` | Line count (0 in byte mode) |
| `num_kills` | How many times this batch died before (retry count) |
| `worker_id` / `node_id` | Where you're running |
| `flags_granted` | Capability flags (dialect 2) |
| `reserved[0]` | Borrowed window pointer (RAW delivery, when granted) |

## Conventions that keep you safe

- **Read via `pread`, write via `stdout`.** Never `lseek`
  `fd_in`; never write anywhere else.
- **Return 0 on success.** Non-zero rides retry-then-poison
  like a Python exception (truncated like `ring_call`:
  nonzero → `& 0xFF`, never silent 0).
- **No `forkrun_use_ctx` export** means the legacy 72B
  two-arg convention — still supported (parent probes,
  never guesses), but new code should opt into the ctx.
- **Keep it pure-batch:** no threads, no retained state
  across calls (workers may be respawned; the engine may
  re-execute your batch after a crash — exactly-once
  *delivery* is the framework's job, idempotent *execution*
  is yours to respect).

## When not to write C

The Python loop does ~700k medium records/s at 28 workers;
the C plugin does ~2.3M. If your bottleneck is downstream
I/O, parsing in pandas, or anything that isn't per-byte
tight loops, stay in Python — the plugin wins only where
per-record CPU dominates.
