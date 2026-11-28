# WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0 — closeout

**Standalone experimental prototype; NOT production; NOT merged to main;
no rental; no physical-NUMA claim; Gate 1 unaffected (unsigned); no
existing engine/production/frozen file modified.**

## Provenance
- Base `767994fad45e4a9f6f8bed8fe8b69ac0c6355bd5`; branch `WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0`. Final HEAD + clean tree in terminal report; sanitizer-tested source SHA see SANITIZER_EVIDENCE.
- Only new files under `stage0/dist_ingest/prefault_pipeline/`. CK-4 audit scope: prototype not linked into `libdist_ingest.so`, separately sanitized; `di_symbol_audit` skips it. `di_symbol_audit` `SYS_set_mempolicy`... not added to engine allowlist (prototype not scanned).

## Functional correctness (separate from performance)
- ordered single stdin reader; explicit memcpy staging→prepared dest; no read-into-dest; no direct-read substitution; partial reads; EINTR; empty/partial-final; empty not published; exactly-once; totals reconcile received==copied==published==consumed; no dup/gap/overlap; no stale-gen; no publish-before-copy; no recycle-before-consumer+reclaim; reclamation verified (PUNCH_HOLE+KEEP_SIZE; no silent fallback); slot accounting at shutdown; all threads join; no deadlock; invalid transitions fail; failed prep never READY; failure propagates. 39 tests + ASan/UBSan + TSan + LSan smoke. Same consumer + reclamation across A/B/C.

## Preparation/overlap evidence (fake-NUMA; see sample_campaign)
Pipeline emits real measured overlap (summed worker-time + union wall +
wait/prep unions + prep-completed-while-blocked + no-prepared + slot-wait
vs input-wait + copy faults + prepared coverage + `move_pages` placement).
`madvise==0` not treated as proof. Prepared ratio 1.0 in serial+pipeline,
0 in lazy on valid runs. No threshold; performance NOT claimed on fake NUMA.

## Fake-NUMA placement limitations
This host is fake/local NUMA (no physical locality guarantees); `MPOL_
BIND/PREFERRED` syscall success ≠ physical placement; `move_pages` shows
where pages currently are (unavailable→unknown); shmem THP + actual
placement NOT established; no physical-NUMA claim. 

## Unresolved / physical-NUMA rental questions
1. Does `MADV_POPULATE_WRITE` actually place memfd/shmem pages on intended node (physical move_pages)? 
2. Can multiple prep workers populate disjoint slots concurrently (scale)? 
3. Does preparation overlap stdin waiting on real producers? 
4. Does ring keep enough prepared lookahead (no reader starvation)? 
5. Fewer copy-path page-materialization faults? 
6. Effective e2e throughput vs lazy + serial_madvise? 
7. Continuous vs bursty/irregular benefit? 
8. Does preparation itself become limiting stage? 
9. Best slot depth + worker count (memory/contention balance)? 
Also: shmem THP interaction; `set_mempolicy`+`mbind` effectiveness on real sparse-NUMA; PUNCH_HOLE placement semantics on rented kernel; staging policy. 

## Rental readiness
Prototype ready to be included in planned physical-NUMA rental campaign
(README rental commands; runtime-only params; no source changes; no
production adoption; no improvement threshold on fake NUMA). NOT proven
on real NUMA; NOT approved for production; **Gate 1 remains unsigned; no
rental authorized.**
