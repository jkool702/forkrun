# Atomic semantics inventory — experimental distributed-ingest engine (regenerated)

**Source of truth:** actual `__atomic_*` call sites in
`stage0/dist_ingest/dist_ingest.c` at the final C SHA. Regenerated
systematically with `tools/di_atomic_inventory.py`. **Count is actual,
not conceptual; NOT required to be 37.** Production ABI unaffected (this
is the experimental engine; no frozen production file).

**Atomic inventory: 43 `__atomic_*` call sites** (17 store_n + 23
load_n + 3 fetch_add). **NOT atomic (mutex-protected):** `n->outstanding`,
`n->published_backlog`, `n->consumer_inflight_backlog`,
`n->accounting_violation`, `n->max_*`, queue fields, `n->m.*`, seams;
see "Mutex-protected state". A release store does **not** synchronize
directly with a relaxed load — see per-object sync below.

## Per-object synchronization (writers / readers / ordering / why sufficient)

### `eng->next_offset` — `_Atomic uint64_t` — CORRECTNESS-CRITICAL accounting
- writers: di_create init store 0 RELAXED; **di_ingest_step `__atomic_fetch_add(..., want, __ATOMIC_ACQ_REL)`** (claim frontier).
- readers: di_ingest_step (ACQUIRE work-availability checks; RELAXED overflow pre-check; centralized loop), di_ingestor_thread (ACQUIRE end-of-input), di_run (ACQUIRE eof_offset), di_global_offset (ACQUIRE).
- **order is __ATOMIC_ACQ_REL on the FAA, NOT RELAXED** (prior doc was wrong). Reservation (`n->outstanding`) accounting is separate + under `n->mu`. ACQ_REL FAA + acquire reads order the claim; per-node backlog under mutex; total correctness cross-checked at end (overlap/lost/dup + total_consumed==file_size).
- NOTE: actual FAA memory order in source is **ACQ_REL**.

### `eng->stop` — `_Atomic int` — CORRECTNESS-CRITICAL lifecycle
- writers: di_create store 0 RELAXED; **di_engine_stop store 1 __ATOMIC_RELEASE**; (no reset).
- readers: di_queue_push, di_queue_pop, di_ingest_step, di_ingestor_thread, di_run — **all __ATOMIC_RELAXED**.
- **Actual synchronization:** the RELEASE store alone does NOT synchronize with RELAXED loads. di_engine_stop stores stop (release) **then**, per node, locks `n->mu` + broadcasts both cvs + unlocks. A condvar waiter, woken, **re-acquires `n->mu`** (synchronizes-with di_engine_stop's unlock) + re-checks stop + also inspects queue state. Loop-top RELAXED loads are best-effort (stop is monotonic 0→1; threads re-check under mutex / re-loop; correctness also rests on condvar broadcast + mutex + drain-then-join + no publication after stop, NOT on store/load ordering). di_run after joining re-checks stop RELAXED.
- advisory correctness layering; no atomic-only correctness claim.

### `eng->ingestors_done` — `_Atomic int` — CORRECTNESS-CRITICAL completion
- writers: di_create store 0 RELAXED; di_ingestor_thread (distributed) **__atomic_fetch_add(+1, __ATOMIC_ACQ_REL)**; di_ingestor_thread (centralized) store num_nodes __ATOMIC_RELEASE; di_run store num_nodes __ATOMIC_RELEASE after joining ingestors.
- readers: di_queue_pop **__ATOMIC_ACQUIRE** (== num_nodes).
- **order:** RELEASE store / ACQ_REL fetch_add + ACQUIRE read pairs producer-done with consumer observation; per-node mu + condvar broadcast wake; consumer drains queue before terminal return. Final unconditional di_run store after ingestor joins also releases.

### `eng->input_changed` — `_Atomic int` — CORRECTNESS-CRITICAL integrity
- writers: di_create store 0 RELAXED; di_pread_full store 1 __ATOMIC_RELEASE (input mutated/truncated); di_ingest_step store 1 __ATOMIC_RELEASE (premature EOF/short read).
- readers: di_run **__ATOMIC_ACQUIRE** (result->input_changed + rc=DI_ERR_IO check), after threads joined.
- **order:** RELEASE store + ACQUIRE read + pthread_join happens-before; sticky 0→1.

### `n->peer_headroom` — `_Atomic uint64_t` — ADVISORY (not correctness-critical)
- writers: di_create store max_backlog RELAXED; di_publish_headroom store RELAXED (called under n->mu but atomic RELAXED).
- readers: di_ingest_step (**RELAXED** reads of OTHER nodes' peer_headroom for adaptive policy).
- **order:** advisory hint only. A claim is always re-checked under n->mu via di_can_admit; peer staleness cannot over-admit. **atomic field; not omitted.**

### test-only atomics — ADVISORY (not correctness-critical; no hot-path effect when unused)
- `g_placement_sample_calls` (`_Atomic uint64_t`): fetch_add RELAXED; store 0 RELAXED; load RELAXED. test counter.
- `g_create_fail_after_nodes` (`_Atomic int`): store RELAXED; load RELAXED. fault-injection seam.
- `eng->thread_create_fail_nth`, `eng->thread_create_fail_fired` (`_Atomic int`): store/load RELAXED. fault-injection seam. (push_fail_* / alloc_fail_* / publish_seam_* are **mutex-protected**, NOT atomic.)

## Mutex-protected state (NOT atomic; synchronize via n->mu / seam_mu)

**n->mu** protects: `n->published_backlog`, `n->consumer_inflight_backlog`, **`n->outstanding`**, `n->accounting_violation`, `n->max_published_backlog`, `n->max_consumer_inflight_backlog`, `n->max_effective_backlog`, queue (`q`,`q_head`,`q_tail`,`q_count`,`q_cap`), `cv_can_push`,`cv_can_pop`, and the cases of `n->m.*` written under it. **`n->published_backlog` and `n->outstanding` are mutex-protected, NOT atomic.**
**seam_mu** protects: `pread_seam`, `placement_seam`, `push_fail_nth`,`push_fail_fired`, `alloc_fail_nth`,`alloc_fail_fired`, `publish_seam`,`publish_seam_fired`.
**n->m.* metrics** (not atomic): disjoint per-role fields; some under n->mu; **read after `pthread_join`** (happens-before); never read concurrently with writes in-engine.
**condvars** `cv_can_push`/`cv_can_pop` + n->mu: blocking; woken + re-checked; di_engine_stop broadcasts.

## Ordering sufficiency summary
- Claim frontier: ACQ_REL FAA + ACQUIRE reads + per-node mu reservation.
- Accounting identity effective=published+inflight+outstanding: under n->mu, checked, overflow-safe (CK-5); NOT atomic; NOT silently clamped.
- Stop/completion/input-changed: release/acquire + mutex + condvar + broadcast + join; relaxed loads safe (monotonic + re-check + no post-stop publish); **release does not alone synchronize relaxed**.
- Advisory atomics: RELAXED sufficient.

## Call-site table (every actual __atomic_* operation; generated)
TOTAL __atomic_* call sites: 43

| # | line | op | object | order | enclosing fn |
|---|---|---|---|---|---|
| 1 | 240 | store_n | `&n->peer_headroom` | RELAXED | di_publish_headroom |
| 2 | 755 | fetch_add | `&g_placement_sample_calls` | RELAXED | di_sample_placement |
| 3 | 861 | store_n | `&eng->input_changed` | RELEASE | di_pread_full |
| 4 | 944 | load_n | `&eng->stop` | RELAXED | di_queue_push |
| 5 | 949 | load_n | `&eng->stop` | RELAXED | di_queue_push |
| 6 | 999 | load_n | `&eng->ingestors_done` | ACQUIRE | di_queue_pop |
| 7 | 1000 | load_n | `&eng->stop` | RELAXED | di_queue_pop |
| 8 | 1086 | store_n | `&eng->stop` | RELEASE | di_engine_stop |
| 9 | 1135 | load_n | `&eng->nodes[i].peer_headroom` | RELAXED | di_ingest_step |
| 10 | 1144 | load_n | `&eng->nodes[i].peer_headroom` | RELAXED | di_ingest_step |
| 11 | 1166 | load_n | `&eng->next_offset` | ACQUIRE | di_ingest_step |
| 12 | 1190 | load_n | `&eng->next_offset` | RELAXED | di_ingest_step |
| 13 | 1199 | fetch_add | `&eng->next_offset` | ACQ_REL | di_ingest_step |
| 14 | 1262 | store_n | `&eng->input_changed` | RELEASE | di_ingest_step |
| 15 | 1353 | load_n | `&eng->stop` | RELAXED | di_ingestor_thread |
| 16 | 1359 | load_n | `&eng->next_offset` | ACQUIRE | di_ingestor_thread |
| 17 | 1373 | load_n | `&eng->next_offset` | ACQUIRE | di_ingestor_thread |
| 18 | 1383 | store_n | `&eng->ingestors_done` | RELEASE | di_ingestor_thread |
| 19 | 1394 | load_n | `&eng->stop` | RELAXED | di_ingestor_thread |
| 20 | 1402 | load_n | `&eng->next_offset` | ACQUIRE | di_ingestor_thread |
| 21 | 1412 | load_n | `&eng->next_offset` | ACQUIRE | di_ingestor_thread |
| 22 | 1422 | fetch_add | `&eng->ingestors_done` | ACQ_REL | di_ingestor_thread |
| 23 | 1478 | store_n | `&eng->next_offset` | RELAXED | di_create |
| 24 | 1479 | store_n | `&eng->stop` | RELAXED | di_create |
| 25 | 1480 | store_n | `&eng->ingestors_done` | RELAXED | di_create |
| 26 | 1481 | store_n | `&eng->input_changed` | RELAXED | di_create |
| 27 | 1554 | store_n | `&n->peer_headroom` | RELAXED | di_create |
| 28 | 1558 | load_n | `&g_create_fail_after_nodes` | RELAXED | di_create |
| 29 | 1609 | load_n | `&eng->thread_create_fail_nth` | RELAXED | cmp_resrec |
| 30 | 1612 | store_n | `&eng->thread_create_fail_nth` | RELAXED | cmp_resrec |
| 31 | 1614 | store_n | `&eng->thread_create_fail_fired` | RELAXED | cmp_resrec |
| 32 | 1661 | store_n | `&eng->ingestors_done` | RELEASE | di_run |
| 33 | 1712 | load_n | `&eng->next_offset` | ACQUIRE | di_run |
| 34 | 1714 | load_n | `&eng->input_changed` | ACQUIRE | di_run |
| 35 | 1787 | load_n | `&eng->input_changed` | ACQUIRE | di_run |
| 36 | 1793 | load_n | `&eng->stop` | RELAXED | di_run |
| 37 | 1799 | load_n | `&eng->next_offset` | ACQUIRE | di_run |
| 38 | 1979 | store_n | `&g_create_fail_after_nodes` | RELAXED | di_test_set_create_fail_seam |
| 39 | 2019 | store_n | `&eng->thread_create_fail_nth` | RELAXED | di_test_set_thread_create_fail_seam |
| 40 | 2020 | store_n | `&eng->thread_create_fail_fired` | RELAXED | di_test_set_thread_create_fail_seam |
| 41 | 2026 | load_n | `&eng->thread_create_fail_fired` | RELAXED | di_test_thread_create_fail_fired |
| 42 | 2047 | store_n | `&g_placement_sample_calls` | RELAXED | di_test_reset_placement_sample_calls |
| 43 | 2051 | load_n | `&g_placement_sample_calls` | RELAXED | di_test_get_placement_sample_calls |

---
*Regenerated WO-...-FINAL-CORRECTIONS-2 (CK-3). fn column best-effort;
authoritative = source line + object + op + order.*
