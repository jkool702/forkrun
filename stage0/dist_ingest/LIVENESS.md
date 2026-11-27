# Liveness audit — experimental distributed-ingest engine (`stage0/dist_ingest/`)

Audit of every potentially-blocking wait in `dist_ingest.c`. All threads
are created and joined by `di_run` (NOT `di_destroy`). Stop is a single
`eng->stop` atomic + `di_engine_stop()` which broadcasts BOTH condition
variables on every node. No child processes are spawned (pure-thread
engine); no always-on global heartbeat or generic watchdog is added.

## Wait inventory (accurate to actual source)

| Location | Wait | Predicate that permits progress | Normal wake/progress source | Stop behavior | Failure behavior | Boundedness |
|---|---|---|---|---|---|---|
| `di_queue_push` — `pthread_cond_wait(cv_can_push)` | Queue-full wait | `q_count < q_cap` OR `stop` | consumer pop OR `di_engine_stop` broadcast | exits wait; returns -1 | returns -1 on stop / injected push failure / invariant violation | bounded by queue capacity + stop broadcast |
| `di_queue_pop` — `pthread_cond_wait(cv_can_pop)` | Queue-empty wait | `q_count > 0` OR `stop` OR `ingestors_done==num_nodes` | producer push / `di_ingestor_thread` broadcast / `di_engine_stop` / end-of-input | exits wait; `ing_done=1`, returns 0 | returns `ing_done=1` on stop | bounded by producer + stop broadcast; consumer drains queued chunks first |
| `di_ingestor_thread` — `nanosleep` claim no-progress (200us) | claim/admission poll sleep | next loop re-check | clock (NOT interruptible; not woken by `stop`) | `stop` checked at loop top; sleep completes (max 200us) | rc<0 breaks | **max shutdown delay 200us** |
| `di_ingestor_thread` — `nanosleep` `stall_then_recover` (mode 3, `stall_ms`) | one-time initial stall | none (time) | clock (NOT interruptible) | completes then checks `stop` | n/a | **max shutdown delay `stall_ms` ms** |
| `di_ingestor_thread` — `nanosleep` `rate_limit` (mode 4, computed `act*1e9/rate_bps`) | throttle after completed read | none (time) | clock (NOT interruptible) | completes then checks `stop` | only applied on a successful full read; NOT applied after error/short read | **max shutdown delay = one computed sleep** = `act*1e9/rate_bps` ns (unbounded by engine; `rate_bps` configured; `act<=max_reservation`) |
| `di_ingestor_thread` — `nanosleep` `delay_per_claim`/`delay_after_read` (modes 1/2, `delay_ns`) | artificial ingestor delay | none (time) | clock (NOT interruptible) | completes then checks `stop` | not applied on error paths | **max shutdown delay `delay_ns` ns** |
| `di_consumer_thread` — `nanosleep` consumer rate-limit (`len*1e9/bytes_per_sec`) | consumer pacing | none (time) | clock (NOT interruptible) | completes; queue pop re-checks `stop` | n/a | **max shutdown delay = one computed sleep** `len*1e9/bytes_per_sec` ns (`bytes_per_sec` configured; `len<=max_reservation`); not applied for `DI_CONSUMER_FAST`/`bytes_per_sec==0` |
| `di_consumer_thread` — `nanosleep` `DI_CONSUMER_STALL` (`stall_ms`) | one-time consumer stall | none (time) | clock (NOT interruptible) | completes; queue pop re-checks `stop` | n/a | **max shutdown delay `stall_ms` ms** |
| `di_pread_full` — `pread` retry on `EINTR` + short-read retry | blocking file read; retry `EINTR`; retry short reads until `len` or EOF | `done < len` progress OR `rr==0` EOF OR error | read syscall | re-checks input-unchanged each iter; not `stop`-woken | **-1 on error; short read returns `done`; `di_ingest_step` treats `act<assigned` as `DI_ERR_IO`; NO inappropriate rate-limit after error** | OS-bounded; not engine-timed; no app-level timeout (outer runner boundary) |
| `di_run` — `pthread_join` (ingestor + consumer) | thread join | thread exit | threads check `stop`, wake on broadcasts, drain queue | `di_engine_stop` first, then join | threads still joined on error/thread-creation failure | bounded by above sleeps + OS read bound; **stop is not a kill; sleeps are not interrupted** |
| `di_alloc_local` | no retry loop | n/a | n/a | n/a | hugepage attempt then ordinary `mmap` once; **-1 on allocation failure; no unbounded retry; no clock bound needed** | bounded (single attempt + single fallback) |

## Intentional sleeps & actual maximum shutdown delay

`nanosleep` is a single, NON-interruptible call (no `EINTR` re-loop; `stop`
not signalled to it; not woken by `di_engine_stop`). `di_engine_stop` does
NOT interrupt sleeps; a thread in a sleep completes it, then re-checks
`stop`. Condition-variable waits ARE woken by `di_engine_stop` broadcasts
(max wakeup latency ~0 once `stop` is set + mutex acquired). `pthread_join`
then waits for threads to finish. Per-sleep bound at shutdown:

- claim no-progress: **200us**;
- `stall_then_recover` / consumer `DI_CONSUMER_STALL`: `stall_ms` ms;
- ingestor `delay_per_claim`/`delay_after_read`: `delay_ns` ns;
- ingestor `rate_limit`: one `act*1e9/rate_bps` ns (not error-path);
- consumer rate-limit: one `len*1e9/bytes_per_sec` ns;
- `pread` retry: OS-bounded (no app timeout).

Worst-case added shutdown delay = max in-flight sleep + `pread` return +
re-check + join. Sleeps are configured (bounded by config); not claimed
"bounded" without stating the bound and that they are not interrupted.
No global heartbeat/watchdog.

## Wake-all abort guarantee

`di_engine_stop()` sets `eng->stop=1` (RELEASE) then per node locks
`n->mu` + broadcasts BOTH `cv_can_pop` + `cv_can_push`. Blocked producers
and consumers wake + re-check. Ingestor/consumer loops check `stop`.
Already-created threads are JOINED in `di_run`. On thread-creation
failure, already-created threads are still joined. On injected faults
(pread/push/alloc/thread-create/invariant), `di_engine_stop` + join;
outstanding reservations rolled back; accounting reconciled (CK-5).

## Thread-creation failure (CK-2.3)

`di_run` creates consumer + ingestor threads via `di_try_pthread_create`.
A failure (real or injected `di_test_set_thread_create_fail_seam`) sets
`rc=DI_ERR_THREAD`, `di_engine_stop`, and **already-created threads are
still joined**; no thread-create means no thread to join. `di_create`
partial-init (`di_test_set_create_fail_seam`, real `pthread_mutex_init`/
`pthread_cond_init`/alloc failure) cleans up already-initialized nodes +
returns NULL; no threads created yet at that point.

## No child processes

Engine is pure-thread; no fork/exec; no orphans/zombies. See
`FORK_AUDIT.md`. Authoritative outer boundary is a process-group-aware
runner timeout (not an in-engine global heartbeat).

---
*WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 (CK-2). Audit
corrected against actual source (no retry loop in di_alloc_local; correct
function names; pthread_join in di_run; precise sleep bounds; no heartbeat).*
