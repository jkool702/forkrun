# Ownership inventory (v1.3 §2.1 — every mutable value gets one owner).
#
# Format: name | owner | direction | timing
#   owner: C-config (immutable fork-inherited) | C-state (authoritative,
#     snapshotted) | bash-surface (compat presentation) | frontend-policy
#   direction: C->FE (snapshot/out-param) | FE->C (spawn/init only) | local
#   timing: spawn | claim | trap | reactor-event | init
#
# | name                | owner        | direction | timing        | notes                                   |
# |---------------------|--------------|-----------|---------------|-----------------------------------------|
# | RING_WID            | C-config     | FE->C     | spawn         | fr_config_t.ring_wid; WID slot          |
# | RING_NODE_ID        | C-config     | FE->C     | spawn         | fr_config_t.ring_node_id; my_numa_node  |
# | RING_WINCARN        | C-config     | FE->C     | spawn         | fr_config_t.ring_wincarn; W_INCARN      |
# | retry_limit         | C-config*    | FE->C     | spawn/init    | default 3; frontend overrides at spawn  |
# | trap_ack_grace_ms   | C-config     | —         | reactor-event | PROTOCOL CONSTANT (3000); respawn       |
# |                     |              |           |               | itself is frontend policy               |
# | respawn_cap         | C-config     | FE->C     | spawn         | safety default; frontend policy decides |
# | spawn_ceiling       | C-config     | FE->C     | spawn         | safety default; nproc-derived           |
# | batch_idx           | C-state      | C->FE     | claim         | fr_state_t; WorkerBatchState.idx        |
# | major               | C-state      | C->FE     | claim         | 64-bit; 42-bit majors (ABI freeze)      |
# | minor               | C-state      | C->FE     | claim         | within-chunk seq                        |
# | slots               | C-state      | C->FE     | claim         | always 1 (single-slot invariant)        |
# | num_kills           | C-state      | C->FE     | claim/trap    | RING_NUM_KILLS on recycled batches only |
# | poisoned            | C-state      | C->FE     | claim         | RING_POISONED at retry limit            |
# | REPLY               | bash-surface | C->bash   | claim         | byte-length bind; C->bash compat only   |
# | RING_BATCH_IDX      | bash-surface | C->bash   | claim         | recycled batches only (H1)              |
# | FRUN_CLAIM_BYTES    | bash-surface | local     | claim/exit    | EXIT-trap escrow gate (claim-active)    |
#
# Standing rules: no fr_get_state() — state travels with the claim. Workers
# never read fr_state_t on any hot path. Reactor reads are typed struct
# reads at event frequency only. Frontends never raw-read mutable
# coordination words (claim counters, escrow slots, poison flags) from
# MAP_SHARED — the fences live in C. Payload-byte window reads are
# explicitly sanctioned (Batch.data MAP_SHARED view by design).
