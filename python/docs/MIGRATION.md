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
| `-E` / `--retry-nonzero-exit` | `on_error="retry"` (default) | Closest CONCEPTUAL analogue, not literal parity — see below |
| `-C plugin:fn` | `mode="plugin"`, `"path:fn"` | Only dialect-tagged (`forkrun_use_ctx` 1/2) plugins transfer unchanged (v1 frozen ABI); the default v0 path is a one-arg ctx convention, not the bash legacy two-arg form |
| `cmd ...` (per-batch exec) | `mode="spawn"`, `"cmd ..."` | Deliberately different delivery — see below |
| `-b` passthrough | `mode="splice"`, payload `None` | Same kernel passthrough |
| `--resume FILE` | `resume=FILE` (+ `order="index"`; the reactor is the default, `orchestrator=False` rejects) | Same byte-coordinate ledger |
| `-s` / `--stdin` (batch to payload on stdin) | *no direct equivalent for Python callables*; `mode="spawn"` is stdin-oriented by design | Different axis: bash `-s` changes how a worker RECEIVES its batch. `stream()`/`streaming=True` changes how the SOURCE is ingested and results are consumed. Do not translate one to the other |
| (no flag; bash ingests incrementally) | `stream()` / `streaming=True` | Incremental ingest + live results |

## Semantic differences that matter

- **No shell.** `mode="spawn"` takes argv (`["sed", ...]`),
  never a shell string. No globbing, no pipelines, no
  `$VARS` — build those parent-side.
- **`mode="spawn"` is stdin-oriented, on purpose.** Bash
  delivers each claimed batch to the command as ARGV by
  default, and `-s` switches that to stdin. Python spawns
  with `input=batch.data`, so the batch always arrives on
  stdin and argv carries only the command itself. This is a
  reasonable library design (it needs no per-batch argv
  length limit), but it is NOT a reproduction of bash's
  default: `frun grep foo < in` and
  `forkrun.map("grep foo", in)` are different programs. A
  spawn command that reads its input as `$1` will see nothing.
- **`-E` is an analogue, not an equivalence.** Bash enables
  retry of ordinary nonzero exits only under `-E`; without it
  those are treated as continue/ack. Python defaults to
  `on_error="retry"` — a more recovery-oriented library
  default — and applies the policy to every worker failure
  kind (Python exception, spawn nonzero, plugin failure), not
  just a command's exit status. Two consequences: a bare
  `forkrun.map(...)` retries where the equivalent bash
  command would not, and `on_error="fail-fast"` is the way
  to ask for the bash-like stop.
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

## Bash axes with no Python equivalent

Listed explicitly so a translation is never silently lossy. Each is an
ABSENT axis, not a divergence to reconcile:

- **`--halt fail=N` / `--halt fail=N%`** — the engine's emergency abort
  threshold (`cfg_halt_count` / `cfg_halt_pct`) is parsed from the
  substrate's own argv (`--halt=`, including the GNU-Parallel-style
  `now,fail=N` / `soon,fail=N` spellings). The Python frontend's init
  entry point takes only `lines` and `bytes`, so there is NO route to it
  from Python: no argument, and no environment variable either. A Python
  run simply cannot arm the halt threshold. If a workflow depends on it,
  that workflow must stay on the bash frontend; the Python default
  (0 = disabled) is not equivalent to a configured threshold.
- **Delimiter / range selection** (`-L` shapes, custom record
  delimiters, exact line ranges) — the Python API takes `lines=` /
  `bytes=` only. There is no delimiter or range grammar.
- **`-u` realtime output** — bash's byte-level at-least-once transport.
  Python returns framed, reconstructible results; `order="none"` is
  unordered *completion*, not realtime. This is intentional: the
  duplicate/interleaving semantics of `-u` are not worth reproducing in
  an API that returns objects.
- **`-d` / `-z` and the remaining diagnostics switches** — CLI-only
  reporting toggles.

Deliberately NOT parity gaps, kept as-is on purpose:

- **Signal handling** — bash traps HUP/TERM/USR1 into
  abort+checkpoint by default. Python installs nothing by default,
  because a library that silently captures SIGTERM from its host is a
  serious integration hazard (services, event loops). Opt in with
  `signal_policy="checkpoint"`.
- **`nodes=` strictness** — Python rejects some bash NUMA aliases rather
  than silently degrading to UMA, so a test cannot claim topology it
  did not exercise.
- **Checkpoint representation** — a typed byte-coordinate ledger rather
  than bash's command/environment reconstruction. Python never
  re-executes a shell fragment to resume, which is strictly safer.

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
