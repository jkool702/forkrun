worker_func_src='spawn_worker() {
(
  LC_ALL=C
  set +m
  export RING_NODE_ID="$2"
  export RING_WID="$3"
  export FD_TRAP_ACK_W="$4"
  
  _ring_registered=false
  
  trap '"'"'
    status=$?
    ${_ring_registered} && { ring_worker dec; ring_cleanup_waiter; }
    
    if (( status != 0 && RING_BATCH_SLOTS > 0 )); then
        (( RING_NUM_KILLS++ ))'
        [[ "$order_mode" != "realtime" ]] && worker_func_src+='
        [[ -n "${fd_out[$RING_WID]:-}" ]] && ring_revert_output "${fd_out[$RING_WID]}"
        '
        worker_func_src+='
        ring_escrow_put "$RING_NODE_ID" "$RING_BATCH_IDX" "$RING_BATCH_SLOTS" "$RING_NUM_KILLS"
    fi
    
    # Notify parent that the trap successfully fired
    if (( status != 0 )); then
        echo "$RING_WID" >&"${FD_TRAP_ACK_W}" 2>/dev/null
    fi
    exit $status
  '"'"' EXIT

  trap '"'"'ring_abort
  kill -INT '"${BASHPID}'"' INT

  {
    ID="$1" # ID is passed purely for user payload compatibility/insertion
    RING_BATCH_SLOTS=0
    RING_NUM_KILLS=0
    '
   [[ "$order_mode" != "realtime" ]] && worker_func_src+='
    # Initialize the output tracking for this specific worker slot
    [[ -n "${fd_out[$RING_WID]:-}" ]] && ring_ack_init "${fd_out[$RING_WID]}"
    '
        ${insert_id_flag:-false} && worker_func_src+='W_BATCH=0
    '
        worker_func_src+='shift 4
    ring_worker inc
    _ring_registered=true
    while ring_claim; do
        if [[ "${RING_POISONED:-0}" == "1" ]]; then
            echo "forkrun [WARN]: Skipping poisoned batch $RING_BATCH_IDX (killed ${RING_NUM_KILLS:-?} times)." >&2
            echo "P:${RING_BATCH_IDX}:${RING_NUM_KILLS:-?}" >&"${FD_TRAP_ACK_W}" 2>/dev/null
        else
            if [[ "$REPLY" != "0" ]]; then
                '
        ${insert_id_flag:-false} && worker_func_src+='((W_BATCH++))
                '
        worker_func_src+="${pCode}"'
            fi
        fi
        '"${ring_ack_str}"' || break
        
        # Clear the active claim flag so a sleep-death doesnt duplicate it
        RING_BATCH_SLOTS=0
    done
  } {fd_read}<"/proc/self/fd/'"${ingress_memfd}"'" 1>&${fd1} 2>&${fd2}
) &
P[$3]=$!
W_NODE[$3]=$2
}'
