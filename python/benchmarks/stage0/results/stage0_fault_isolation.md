# Stage 0 fault-isolation tables

Hardware: Intel(R) Core(TM) i9-7940X CPU @ 3.10GHz | 28t | 125GB single-socket | localhost.localdomain | 2026-09-18

Discipline: named configurations, observed behavior only, no generalized claims. Granularity differs by design (item vs batch vs chunk) and is recorded per row.

## multiprocessing.Pool

- fault granularity: item
- elapsed: 150.2 s; rc: n/a
- survived: False
- completed: 0 / 200000
- recovery action: map_async hung > 150.0s (dead worker chunk never resolves); pool terminated
- pool usable after: False (fresh Pool required; faulted pool was terminated, not reused)
- notes: item-granularity fault; compare vs forkrun batch-granularity

## ProcessPoolExecutor

- fault granularity: item
- elapsed: 0.6 s; rc: n/a
- survived: False
- completed: 100000 / 200000
- recovery action: BrokenProcessPool: A process in the process pool was terminated abruptly while the future was running or pending.; executor shut down, unusable after (fresh executor required)
- pool usable after: False
- notes: item-granularity fault; compare vs forkrun batch-granularity

## forkrun-C-segv-plugin

- fault granularity: batch (mark 7)
- elapsed: 3.2 s; rc: 2
- survived: False
- completed: 7000 / 200000
- recovery action: rc=2; FAULT-INJECT seen x3; 'poison' mentions x0; output 7000/200000 lines
- pool usable after: True (no pool object to poison; the aborted run resumes via its checkpoint (--resume))
- notes: batch-granularity fault; compare vs item-granularity incumbents

## gnu-parallel-segv-job

- fault granularity: chunk (5000 lines)
- elapsed: 0.4 s; rc: 0
- survived: True
- completed: 195000 / 200000
- recovery action: parallel rc=0; output 195000/200000 lines; failed chunk dropped, rest completed
- pool usable after: True (parallel is a new process per run)
- notes: chunk-granularity fault

