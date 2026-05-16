worker_func_src='spawn_worker() {
    while ring_claim; do
        if [[ "${RING_POISONED}" == "1" ]]; then
            echo "P"
        else
            if [[ "$REPLY" != "0" ]]; then
                '
        worker_func_src+="${pCode}"'
            fi
        fi
        '"${ring_ack_str}"' || break
        
        # Reset variables natively in Bash so C doesn't have to allocate them
        RING_POISONED=0
        RING_NUM_KILLS=0
        REPLY=0
    done
}'
