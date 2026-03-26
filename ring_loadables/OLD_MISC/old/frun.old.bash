
frun() {

    local TMPDIR

    mkdir -p /dev/shm/.forkrun
    TMPDIR="$(mktemp -d -p  /dev/shm/.forkrun -t forkrun.XXXXXXXX)"
    : > ${TMPDIR}/stdin

    (
    enable -f forkrun_ring.so ring_init ring_scanner ring_claim ring_worker ring_exec ring_destroy ring_fallow ring_ingest evfd_copy evfd_signal lseek


if [[ "$1" == '--ring_exec' ]]; then

shift 1
ring_exec_flag=true

spawn_worker() {
  local ITER CNT total fd1 fd2 id
  id="$1"
  shift 1
  {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${id}
                echo "$CNT" >> ./count.${id}
                ((ITER++))
                ring_exec $fd_read $CNT "${@}"
            done
            ring_worker dec  # de-register worker
            #exec {fd_count}>&-
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${id}

        } {fd_read}<${TMPDIR}/stdin 1>&${fd1} 2>&${fd2}
    ) &
    P+=($!)
  } {fd1}>&1 {fd2}>&2
  exec {fd1}>&- {fd2}>&-
}

else

ring_exec_flag=false

spawn_worker() {
  local ITER CNT total fd1 fd2 id
  id="$1"
  shift 1
  {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${id}
                echo "$CNT" >> ./count.${id}
                ((ITER++))
   #             mapfile -t -u $fd_read A
    #            "$@" "${A[@]}"
            done
            ring_worker dec  # de-register worker
            #exec {fd_count}>&-
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${id}

        } {fd_read}<${TMPDIR}/stdin 1>&${fd1} 2>&${fd2}
    ) &
    P+=($!)
  } {fd1}>&1 {fd2}>&2
  exec {fd1}>&- {fd2}>&-
}

fi

total=0
P=()

export nWorkers=1
export nWorkersMax=$(( $(nproc) ))
#export nBytesMax=ARG_MAX
#export nLinesMax=4096
start_time=${EPOCHREALTIME//./}

    ring_init

    (
        evfd_copy ${fd_write} ${fd_stdin}
        evfd_signal
    ) &
    SPLICE_PID=$!

    ${ring_exec_flag} && {
    export FD_RING_FALLOC="${fd_falloc}"
    ( ring_fallow ${fd_falloc} ${fd_write} ) &
    FALLOC_PID=$!
    }

    ( ring_scanner ${fd_scan} ${fd_spawn} ) &
    SCANNER_PID=$!


for (( nn=0; nn<nWorkers; nn++)); do
    spawn_worker "$nn" "$@"
done

while true; do
    read -r -u $fd_spawn N
    [[ "$N" == 'x' ]] && { printf '\nSCANNER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&2; break; }
    echo "spawning $N workers" >&2
    nWorkers0="$nWorkers"
    (( ( nWorkers0 + N ) > nWorkersMax )) && (( N = nWorkersMax - nWorkers0 ))
    (( N > 0 )) && for ((nn=nWorkers0; nn<nWorkers0+N; nn++)); do
        spawn_worker "$nn" "$@"
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

echo "Done." >&2
echo "Total Lines Consumed: $total" >&2
echo "Time: ${elapsed} us" >&2

# Cleanup
ring_destroy
for p in $SCANNER_PID $SPLICE_PID $FALLOC_PID; do
[[ $p ]] || continue
kill $p 2>/dev/null
wait $p 2>/dev/null
done

exec {fd_spawn}>&- {fd_scan}>&- {fd_stdin}>&- {fd_write}>&- {fd_falloc}>&-

    ) {fd_scan}<"${TMPDIR}/stdin" {fd_write}>"${TMPDIR}/stdin" {fd_stdin}<&0 {fd_spawn}<><(:) {fd_falloc}<><(:)
}
