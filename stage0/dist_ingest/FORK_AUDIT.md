# Fork audit — experimental distributed-ingest engine (CK-4, enforceable)

The experimental engine is **threads-only**: it spawns and joins worker
and consumer threads via `pthread_create`/`pthread_join`. `pthread_create`
is NOT process creation. The engine makes **no fork(), vfork(), exec*,
pthread_atfork(), system(), popen(), posix_spawn*, clone, clone3**, no
direct process-creation syscall, no inline syscall assembly, no
unrecognized `syscall()` usage, and no socket APIs. Single-process
memory-fence/IO engine.

## Audit coverage (`tools/di_symbol_audit.py`, fail-closed, exit nonzero)

1. **Source-level process-creation references** throughout experimental
   engine C + header sources (`stage0/dist_ingest/**/*.c,*.h`). C/C++
   comments and string literals are stripped; prohibited word-boundary
   constructs rejected. Required sources must exist + be inspectable.
2. **Direct syscall() audit**: EVERY `syscall(` call site, including
   multiline calls and aliases/macros (`#define X SYS_clone` +
   `syscall(X,...)`; macro alias chains). First argument extracted
   (balanced parens) + resolved; must match explicit allowlist. Direct
   clone/clone3 rejected. Unknown/ambiguous/numeric/expression syscall
   args reported + FAIL. `syscall` in comments/strings not counted.
   **Inline syscall assembly** (`asm`/`__asm__` containing `syscall`,
   `sysenter`, `int $0x80`) rejected.
   **Explicit syscall allowlist** (actual permitted NUMA/I/O syscalls
   used by this engine): `SYS_mbind`/`__NR_mbind` (memory policy),
   `SYS_move_pages`/`__NR_move_pages` (placement observation). Nothing
   else. (No `set_mempolicy`/`get_mempolicy` calls are made.)
3. **Undefined dynamic symbols** from the actual built
   `stage0/libdist_ingest.so` via `nm -D --undefined-only`. Rejects
   undefined prohibited symbols. A direct `clone`/`clone3` import is NOT
   automatically allowed merely because pthread uses it inside libc
   elsewhere. `nm` unavailable, `nm` fails, shared object missing =>
   FAIL. `threads_only_symbols_ok=true` ONLY if the scan ran + clean.

## Prohibited (rejected, source + undefined symbol)

`fork`, `vfork`, `pthread_atfork`, `system`, `popen`, `posix_spawn*`,
exec family (`execve`, `execveat`, `execl`, `execle`, `execlp`, `execv`,
`execvp`, `execvpe`, `execvP`, `fexecve`, bare `exec`), `clone`,
`clone3`, `__clone`, `__clone3`, `SYS_clone`, `SYS_clone3`, `__NR_clone`,
`__NR_clone3`, direct process-creation syscalls. `pthread_create`/
`pthread_join` allowed. `syscall(SYS_mbind...)`/`syscall(SYS_move_pages...)`
allowed.

## Exit behavior

Nonzero if: required source files cannot be inspected; shared object
missing; `nm` unavailable or fails; prohibited construct found; prohibited
undefined symbol found; a direct `syscall` cannot be classified against
the allowlist. The computed `bad` set is honored (not ignored).

## Regression

`tests/test_threads_only_ck4.py` + `tests/test_symbol_audit_ck4.py`:
clean source+symbol audit; synthetic fork/vfork/exec/clone/clone3/
atfork/system/popen/posix_spawn; multiline + alias/macro + unknown +
numeric + expression syscall args; inline-asm; forbidden undefined
symbol; missing shared object; missing/failing `nm`; main nonzero.

## Limitations

Static textual source scan (comments/strings stripped; shallow `#define`
alias resolution; not a full C preprocessor/type analysis). Does not
prove no process creation at runtime via dynamically loaded plugins. No
`libnuma` fallback. Historical textual-grep claims superseded.

---
*WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-4).*
