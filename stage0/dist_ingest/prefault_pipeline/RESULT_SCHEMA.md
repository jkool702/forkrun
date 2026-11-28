# Machine-readable result schema (prefault pipeline)

## Per-run JSON (C `--json-out` + campaign `run_*.json`)
`mode`, `rc`, `failed`, `failed_errno`, `fail_msg`;
`slot_size`, `slots_per_node`, `num_nodes`, `num_slots`, `total_reserved_capacity`, `map_len`, `map_base_alignment`, `page_size`, `memfd`, `nodes[]`;
`total_received`, `total_copied`, `total_published`, `total_consumed`, `total_reserved`, `reserved_preparing_capacity`;
`wall_seconds`, `effective_ingest_bytes_per_sec`, `slots_completed`;
`input_wait_ns`, `slot_wait_ns`, `copy_ns`, `preparation_worker_busy_ns`, `overlap_summed_worker_ns`, `overlap_union_wall_ns`, `wait_union_ns`, `prep_union_ns`, `prep_completed_during_input_wait`, `reader_no_prepared_count`;
`prepared_total_bytes`, `prepared_destination_bytes`, `prepared_ratio`, `bytes_copied_lazy`, `bytes_copied_prepared`, `ready_at_assign`, `ready_after_arrival`;
`copy_minor_faults`, `copy_major_faults`;
`per_node[]`: `{node,slots,bytes,prep_ops,prep_ns,prep_fail,prep_throughput_bps,prepared_busy_ns,copied_bytes,copy_ns,copy_minflt,copy_majflt,placement_samples,placed_on_node,placed_other,placed_unknown,placement_ns}`;
`total_prep_ns`, `total_prep_ops`, `total_prep_fail`, `slots_free`, `slots_ready`, `num_slots`.

Accounting identities: `total_received==total_copied==total_published==total_consumed`; reserved separate; prepared only after successful `MADV_POPULATE_WRITE`. No premature reuse; no stale gen; no publish before copy; reclamation verified; slots accounted at shutdown.

## Campaign JSON (`campaign.json`)
`schema`, `bin`, `config`, `total_bytes`, `ring_capacity`, `min_generations`, `reps`, `seed`, `order`, `commands[]`, `cells[]{schedule,reps,runs[]{cmd,cmd_str,returncode,wall_seconds,stderr,result,feeder,mode,rep,schedule}}`. Raw per-run JSON + stderr retained. No improvement threshold. Fake-NUMA ≠ physical.
