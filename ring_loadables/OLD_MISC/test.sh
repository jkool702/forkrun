#!/usr/bin/bash

ring_test() {
(
 ring_enable_list=()
 enable -f ./forkrun_ring.so ring_list
 ring_list ring_enable_list
 enable  -f ./forkrun_ring.so "${ring_enable_list[@]}"


    local -ga fd_out args
    local -g pCode
    local -gx order_flag nogen_flag

    nogen_flag=false
    order_flag=false
    while true; do
        case "$1" in
            -o|--order) order_flag=true ;;
            -n|--nogen) nogen_flag=true ;;
            *) break
        esac
        shift 1
    done

    test_type="$1"
    shift 1
    : "${test_type:=0}"
    [[ "${test_type}" == [0-9]* ]] || { printf '\n\nERROR! invalid test type.\n\n' >&2; return 1; }

    case "${test_type}" in
        0|1) pCode="$1"; shift 1 ;;
    esac

    (( $# > 0 )) && args=("$@")

    # Define spawn_worker based on type
    case "${test_type}" in
    0)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            "$pCode" "${args[@]}" "${A[@]}" >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            "$pCode" "${args[@]}" "${A[@]}"
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    1)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    IFS=' '
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            "$pCode" ${args[*]} ${A[*]} >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            "$pCode" ${args[*]} ${A[*]}
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    2)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            : "${args[@]}" "${A[@]}" >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            : "${args[@]}" "${A[@]}"
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    3)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    IFS=' '
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            IFS=$'\n' : ${args[*]} ${A[*]} >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            IFS=$'\n' : ${args[*]} ${A[*]}
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    4)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            printf '%s\n' "${args[@]}" "${A[@]}" >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            printf '%s\n' "${args[@]}" "${A[@]}"
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    5)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        ((ITER++))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            IFS=$'\n' printf '%s\n' ${args[*]} ${A[*]} >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            IFS=$'\n' printf '%s\n' ${args[*]} ${A[*]}
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    7)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        ((total+=CNT))
                        mapfile -t -u $fd_read -n $CNT A
                        if ${order_flag}; then
                            ff "${args[@]}" "${A[@]}" >&${fd_out[$1]}
                            ring_ack $fd_falloc ${fd_out[$1]}
                        else
                            ff "${args[@]}" "${A[@]}"
                            ring_ack $fd_falloc
                        fi
                    done
                    ring_worker dec
                    echo "$total" >./total.${1}
                    printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    8)
        spawn_worker() {
            (
                {
                    ITER=0
                    ring_worker inc
                    while ring_claim OFF CNT $fd_read; do
                        [[ "$CNT" == "0" ]] && break
                        mapfile -t -u $fd_read -n $CNT A
                        ff "${args[@]}" "${A[@]}"
                        ring_ack $fd_falloc
                    done
                    ring_worker dec
                } {fd_read}<"${targetFile0}" 1>&${fd1} 2>&${fd2}
            ) &
            P+=($!)
        }
    ;;
    esac

    [[ $(echo ./total.* ./count.* ./final.* ) ]] && \rm ./total.* ./count.* ./final.* 2>/dev/null

    # Generate Data
    dataN=1000000000
    echo "Generating test data..." >&2
    case "${test_type}" in
        7|8)
            ff() {
                sha1sum "${@}"; sha256sum "${@}"; sha512sum "${@}"; sha224sum "${@}"
                sha384sum "${@}"; md5sum "${@}"; sum -s "${@}"; sum -r "${@}"
                cksum "${@}"; b2sum "${@}"; cksum -a sm3 "${@}"; xxhsum "${@}"; xxhsum -H3 "${@}"
            }
            export -f ff
            targetFile=/mnt/ramdisk/flist
        ;;
        4|5) ${nogen_flag} || { seq $dataN >test.dat; }; targetFile=./test.dat ;;
        *)   ${nogen_flag} || { yes $'\n' | head -n $dataN > test.dat; }; targetFile=./test.dat ;;
    esac

    if ${nogen_flag} && ! [[ -t 0 ]]; then
        targetFile='&0'
        dataN='???'
    else
        [[ -f "$targetFile" ]] && dataN=$(wc -l <"$targetFile")
    fi

    # Initialize Environment
    exec {fd_spawn}<><(:)
    total=0
    P=()
    export nWorkers=1
    export nWorkersMax=$(nproc)

    # 1. Ring Init
    if ${order_flag}; then
        fd_out=()
        exec {fd_order}<><(:)
        export FD_ORDER_PIPE=$fd_order
        # Populates fd_out array with memfds
        ring_init 'fd_out'
    else
        ring_init
    fi

    # 2. Ingest Memfd
    ring_memfd_create ingress_memfd
    targetFile0="/proc/${BASHPID}/fd/${ingress_memfd}"

    echo "Starting copy..." >&2
    echo "Sending stdin to ingress memfd ${ingress_memfd}"  >&2

    # Setup Splicer FDs
    exec {fd_write}>"$targetFile0"
    if ${nogen_flag} && ! [[ -t 0 ]]; then
        exec {fd_stdin}<&0
    else
        exec {fd_stdin}<"$targetFile"
    fi

    # START SPLICER (Fix: Use fd_stdin, NOT ingress_memfd)
    start_time=${EPOCHREALTIME//./}
    (
        ring_copy ${fd_write} ${fd_stdin}
        ring_signal
        printf '\nCOPY HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&$fd2
    ) &
    COPY_PID=$!

    # 3. Start Scanner (Fix: Open fd_scan first)
    exec {fd_scan}<"$targetFile0"
    echo "Starting scanner..." >&2
    (
        ring_scanner ${fd_scan} ${fd_spawn}
        printf '\nSCANNER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&$fd2
    ) &
    SCANNER_PID=$!

    # 4. Start Fallow
    exec {fd_falloc}<><(:)
    echo "Starting fallow..." >&2
    export RING_FALLOC_FLAG=true
    (
        ring_fallow ${fd_falloc} ${fd_write}
        printf '\nFALLOW HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&$fd2
    ) &
    FALLOC_PID=$!

    # 5. Start Orderer (if needed)
    ${order_flag} && {
        echo "Starting order..." >&2
        (
            ring_order $fd_order "memfd" >&${fd1}
            printf '\nORDER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&$fd2
        ) &
        ORDER_PID=$!
    }

    # 6. Consumer Loop
    printf "\nConsuming...\n\n" >&2
    printf 'INITIALLY SPAWNING %s WORKERS\n' $nWorkers >&2
    for (( nn=0; nn<nWorkers; nn++)); do
        spawn_worker "$nn"
    done

    while true; do
        read -r -u $fd_spawn N
        [[ "$N" == 'x' ]] && break
        printf 'SPAWNING %s WORKERS (elapsed time = %s us)\n' $N $(( ${EPOCHREALTIME//./} - start_time )) >&2
        nWorkers0="$nWorkers"
        (( ( nWorkers0 + N ) > nWorkersMax )) && (( N = nWorkersMax - nWorkers0 ))
        (( N > 0 )) && for ((nn=nWorkers0; nn<nWorkers0+N; nn++)); do
            spawn_worker "$nn"
            ((nWorkers++))
        done
    done

    wait "${P[@]}"

    end_time=${EPOCHREALTIME//./}
    elapsed=$(( end_time - start_time ))

    for nn in ./total.*; do
        read -r total0 <$nn
        (( total = total + total0 ))
    done

    printf  '\n\nDone!\n\nTotal Lines Consumed: %s (Expected: %s)\n\nTime: %s us\n\n' "$total" "$dataN" "${elapsed}" >&2

    # Cleanup
    ring_destroy

    kill $COPY_PID $SCANNER_PID $FALLOC_PID $ORDER_PID $(jobs -p) 2>/dev/null
    kill -9 $COPY_PID $SCANNER_PID $FALLOC_PID $ORDER_PID $(jobs -p) 2>/dev/null
    wait $COPY_PID $SCANNER_PID $FALLOC_PID $ORDER_PID $(jobs -p) 2>/dev/null

    exec {fd_spawn}>&-
    exec {fd_scan}>&-
    exec {fd_falloc}>&-
    exec {fd_stdin}>&-
    exec {fd_write}>&-
    exec {ingress_memfd}>&-
    ${order_flag} && exec {fd_order}>&-

    : | cat ./final.* 2>/dev/null
    # \rm -r "$TMPDIR" 2>/dev/null
)  {fd1}>&1 {fd2}>&2
}
