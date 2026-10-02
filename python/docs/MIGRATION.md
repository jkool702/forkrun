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
| `-C plugin:fn` | `mode="plugin"`, `"path:fn"` | Only dialect-tagged (`forkrun_use_ctx` 1/2) plugins transfer unchanged (v1 frozen ABI); the default v0 path is a one-arg ctx convention, not the bash legacy two-arg form |
| `cmd ...` (per-batch exec) | `mode="spawn"`, `"cmd ..."` | Same stdin/stdout contract |
| `-b` passthrough | `mode="splice"`, payload `None` | Same kernel passthrough |
| `--resume FILE` | `resume=FILE` (+ `order="index"`; the reactor is the default, `orchestrator=False` rejects) | Same byte-coordinate ledger |
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
- **Signals are opt-in.** Bash traps HUP/TERM/USR1 into
  abort+checkpoint by default; Python installs nothing by
  default (host-safe). Pass `signal_policy="checkpoint"` for
  the Bash behavior, and expect `ForkrunTerminated` /
  `ForkrunPreempted` / `ForkrunInterrupted` (Bash 143/138/130)
  instead of exit codes — see the mapping table in
  TROUBLESHOOTING.md.

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

## Python 0.16 → 0.17

One breaking change: **`map()` results are `memoryview` instead of
`bytes`.** Nothing else about the API moved.

```python
# 0.16 — worked
for rec in forkrun.map(f, src):
    if rec.startswith(b"ERROR"): ...

# 0.17 — AttributeError: 'memoryview' object has no attribute 'startswith'
for rec in forkrun.map(f, src):
    if bytes(rec).startswith(b"ERROR"): ...

# 0.17 — or keep the old objects
for rec in forkrun.map(f, src, output="bytes"):
    if rec.startswith(b"ERROR"): ...
```

Unaffected: `len()`, slicing, `==` against `bytes`, `.tobytes()`,
`.hex()`, `b"".join(results)`, `f.write(...)`, and any socket/file
`send`/`write`. Those all accept a buffer.

Affected: `.split`, `.splitlines`, `.decode`, `.startswith`, `in`,
`sorted()`, and arithmetic. Fix with `forkrun.materialize(rec)` or
`bytes(rec)` on the affected record, or `output="bytes"` on the call.

Two things that did **not** change:

- `stream()` still yields `bytes`. It drains records live, so there is
  no finished file to map.
- Payload-side `Batch.data` was already a borrowed `memoryview` and is
  unaffected.
