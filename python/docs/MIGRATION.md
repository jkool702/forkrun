# forkrun Migration Guide (bash → Python)

You know `frun`. The Python frontend is the same engine
with a different steering wheel — concepts transfer
almost 1:1.

## Flag → parameter map

| bash | Python | Notes |
|---|---|---|
| (input argv/stdin) | `source=` (path, fd, pipe) | No shell word-splitting; pass fds directly |
| `-w N` / `-j N` | `workers=N` | Same worker pool idea |
| `-k` (keep order) | `order="index"` | Default `"none"` = completion order |
| `-l N` | `lines=N` | Mutually exclusive with `-b`/`bytes=` |
| `-b N` | `bytes=N` | splice mode takes `bytes=` only |
| `-E` (retry) | `on_error="retry"` (default) | `"skip"` / `"fail-fast"` likewise |
| `-C plugin:fn` | `mode="plugin"`, `"path:fn"` | Same frozen ABI — a bash `-C` plugin works unchanged |
| `cmd ...` (per-batch exec) | `mode="spawn"`, `"cmd ..."` | Same stdin/stdout contract |
| `-b` passthrough | `mode="splice"`, payload `None` | Same kernel passthrough |
| `--resume FILE` | `resume=FILE` (+ `orchestrator=True, order="index"`) | Same byte-coordinate ledger |
| `-s` (streaming) | `stream()` / `streaming=True` | Live drain instead of collect |

## Semantic differences that matter

- **No shell.** `mode="spawn"` takes argv (`["sed", ...]`),
  never a shell string. No globbing, no pipelines, no
  `$VARS` — build those parent-side.
- **Payloads return bytes.** Bash emits stdout; Python
  returns `bytes`/`str`/`None` per batch. `None` = no
  record (there is no empty-stdout ambiguity).
- **Batch, not line.** Your function sees a `Batch`
  (many lines), not one line at a time. Loop inside.
- **Ordering is explicit.** Bash `-k` ≈ `order="index"`;
  default Python order is completion order (faster).
- **Errors are values first.** A Python exception retries
  like a nonzero exit; process death respawns like the
  bash EXIT trap with the reactor on.
- **Functions, not programs.** `run`/`map`/`stream` compose
  in-process (results are Python objects, not stdout text).

## Minimal translation

```bash
# bash
frun -w 8 -k -l 1000 -- myfunc < input.txt > out.txt
```

```python
# Python
import forkrun
results = forkrun.map(myfunc, "input.txt",
                      workers=8, order="index", lines=1000)
with open("out.txt", "wb") as f:
    f.write(b"".join(results))
```
