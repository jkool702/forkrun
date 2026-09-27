# dev/tools — release-forensics utilities (v3.6.0 cycle)

Two tools preserved from the W-MOVER / §7 verification work. Neither
ships; neither runs unless invoked. See `../supervisor/MOVER_REPORT.md`
and `../supervisor/RELEASE_VERIFICATION.md` for the evidence they produced.

## `numa_quads.py` — heavy-20M EPYC-preview trio gate

Sequential in-process quads (`@4` ×4, `auto` ×4, `nodes=1` ×2 over
`ml_plugin_heavy`, workers=28, `order="index"`), each byte-exact
(hash+len+lines over ordered output) vs the `nodes=1` reference, with
zero drain-audit warnings and `FORKRUN_DIAG_NUMA1` telemetry recorded.
Exit 0 + `ALL-EXACT` means the gate passes. Re-run as-is on EPYC
(`auto` follows the boot topology there).

Setup: build `/tmp/ml_heavy.so` and generate `/tmp/heavy20m.jsonl`
(20M records, ~26.9GB — generate in parallel chunks if slow), or point
`FORKRUN_QUADS_INPUT` / `FORKRUN_QUADS_PLUGIN` elsewhere.
v3.6.0 record: 10/10 exact, ~26–33s per run, per-node `write==read`.

## `mover_trace.c` — LD_PRELOAD memfd syscall tracer

Interposes libc `read`/`write`/`pread`/`pwrite`/`sendfile`/`splice`/
`copy_file_range`/`lseek`/`lseek64`/`memfd_create`; logs only fds
whose `/proc/self/fd` target is a memfd (caller PC, pid/ppid/comm,
fd, args, return, monotonic timestamps), plus self-identifying
`/proc` maps lines (ASLR-proof `addr2line`) and bounded per-event
`evfd_data_arr` capture via `/proc/self/mem` + `nm` offsets.

Build: `gcc -O1 -fPIC -shared -o /tmp/mover_trace.so mover_trace.c -ldl`
(with `-DEVFD_ARR_OFF=0x… -DNNODES_OFF=0x…` from `nm` for the array
capture; plain build traces without it).
Run: `MOVER_TRACE=1 MOVER_TRACE_FILE=/tmp/m.log LD_PRELOAD=/tmp/mover_trace.so …`

Known caveats (learned the hard way, documented so the next hunt
doesn't relearn them): the tracer perturbs timing-sensitive tests
(kill-window/adversarial/parity suites flake under it — verify clean
without it); heavy tracing *suppresses* tight races; CPython calls
`lseek64`, not `lseek`; the log fd must be dev/ino-guarded or worker
`scrub_fds` + fd reuse hijacks it into memfds. What it proved:
8-byte `do_lockfree_claim` eventfd-drain reads landing on
`forkrun_ingress` (F-PY-UMA1b mechanism).
