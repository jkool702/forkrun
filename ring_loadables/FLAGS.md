# # # # # FORKRUN V3 FLAGS # # # # #

### DATA PASSING & DELIMITERS

- `<default>`             : Pass arguments fully quoted via cmdline (`"${A[@]}"`). (no flag needed)
- `-U, --unsafe`          : Pass arguments unquoted via cmdline (`${A[*]}`).
- `-s, --stdin`           : Pass data to the worker via its `stdin` (instead of via cmdline arguments).
- `-b, --bytes <N>`       : Byte mode. Split the stream into `N`-byte chunks instead of using delimiters (implies `-s`). Supports standard prefixes (e.g., `-b 1M`).
- `-z, --null`            : Use NULL (`\0`) as the record delimiter instead of newline.
- `-d, --delim <char>`    : Use a custom single-character record delimiter.

### OUTPUT MODES

- `--buffered`            : (DEFAULT) Buffered / "atomic fan-in" mode. Output is stored in a memfd and printed once the whole batch finishes. 
- `-k, --ordered`         : Ordered mode. Same as buffered, but output is printed strictly in input-batch order.
- `-u, --realtime`        : Unbuffered / realtime mode. Workers output directly to `stdout`. (Can cause kernel lock contention on massive streams).
- `-o, --order <mode>`    : Explicitly set the mode (`buffered`, `ordered`, `realtime`).

### WORKER & BATCH SCALING (Dynamic Ranges)

*Syntax note: Options accepting `<init>:<max>` allow you to define the starting value and the upper bound for the dynamic PID controller. Setting `<init>` and `<max>` to `0` or `-1` has special meaning. Examples: `1:0` (DEFAULT) (start at 1, scale to default max) | `0:-1` (start at default max, scale to maximum allowed) | `4:16` (start at 4, scale to max of 16).*

- `-j, -P, --workers <W>` : Set the number of concurrent workers. Supports `<init>:<max>` (e.g., `-j 4:32`). Default max is the number of logical cores.
- `-l, --lines <L>`       : Set the batch size (lines per worker). Supports `<init>:<max>` (e.g., `-l 10:10000`). Default max is 4096.
- `-L, --exact-lines <N>` : Force exactly `N` lines per batch. (Warning: Disables NUMA topological stealing to guarantee exact counts).
- `-t, --timeout <us>`    : Set the maximum wait time (in microseconds) for a partial batch before flushing early.

### STRING SUBSTITUTION

- `-i, --insert`          : Replace `{}` in the command string with the inputs passed on stdin.
- `-I, --insert-id`       : Replace `{ID}` in the command string with `[{NODE_NUM}.]{WORKER_NUM}.{BATCH_NUM}`. `{ID}` is unique per batch, and can be used to redirect output per batch.

### LIMITS & TOPOLOGY

- `-n, --limit <N>`       : Stop processing after exactly `N` records have been claimed.
- `--nodes, --numa <map>` : Control NUMA topology mapping. Nodes that do not exist will be skipped (excluding for `@N`).
  - `auto` (default): Autodetect all physical online nodes.
  - `@N`: Oversubscribe / force `N` logical nodes.
  - `0,1`: Explicitly bind to physical NUMA nodes 0 and 1.
  - `0:3`: Explicitly bind to physical NUMA nodes 0 and 1 and 2 and 3.
- `-N, --dry-run`         : Dry run. Print the generated command strings instead of executing them.
- `-v, --verbose`         : Increase verbosity (prints timing and flag summaries to `stderr`).
- `+v, --no-verbose`      : Decrease verbosity.
