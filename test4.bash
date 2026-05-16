worker_func_src='spawn_worker() {
    while ring_claim; do
        if [[ "${RING_POISONED:-0}" == "1" ]]; then
            echo "P"
        else
            if [[ "$REPLY" != "0" ]]; then
                '
        worker_func_src+="${pCode}"'
            fi
        fi
        '"${ring_ack_str}"' || break
        
        # Clear the active claim flag so a sleep-death doesnt duplicate it
        RING_BATCH_SLOTS=0
    done
}'
