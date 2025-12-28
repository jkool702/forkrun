#!/usr/bin/bash

ring_test() (

 enable -f /mnt/ramdisk/forkrun/ring_loadables/forkrun_ring.so ring_init ring_scanner ring_claim ring_worker ring_destroy ring_ingest ring_order lseek

case "$1" in

0)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;
1)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
		:
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;

2)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
                (( ${#A[@]} == CNT )) || echo "ERROR on iteration $ITER: expected $CNT values, got ${#A[@]} values" >&2
                : "${A[@]}"
                ${RING_FALLOC_FLAG} && ring_ack $fd_falloc
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;

3)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            IFS=' '
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
                (( ${#A[@]} == CNT )) || echo "ERROR on iteration $ITER: expected $CNT values, got ${#A[@]} values" >&2
                 IFS=' ' : ${A[*]}
                  ${RING_FALLOC_FLAG} && ring_ack $fd_falloc
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;

4)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
                (( ${#A[@]} == CNT )) || echo "ERROR on iteration $ITER: expected $CNT values, got ${#A[@]} values" >&2
                printf '%s\n' "${A[@]}" >>./count.out.${1}
                 ${RING_FALLOC_FLAG} && ring_ack $fd_falloc
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;

5)
spawn_worker() {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
		echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
                (( ${#A[@]} == CNT )) || echo "ERROR on iteration $ITER: expected $CNT values, got ${#A[@]} values" >&2
		IFS=' '
                printf '%s\n' ${A[*]@Q}
                 ${RING_FALLOC_FLAG} && ring_ack $fd_falloc
            done | wc -l >>./count.out.${1}
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;


7)

spawn_worker() {
  {
    (
        {
            ITER=0
            ring_worker inc  # Register ourselves as 1 worker
            exec {fd_count}<><(:)
            #{ cat <&$fd_count | wc -l > ./count.final.${1} } &
            while ring_claim OFF CNT $fd_read; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                echo "$total" >./total.${1}
                echo "$CNT" >> ./count.${1}
                ((ITER++))
                mapfile -t -u $fd_read -n $CNT A
                ff "${A[@]}"
                 ${RING_FALLOC_FLAG} && ring_ack $fd_falloc
            done
            ring_worker dec  # de-register worker
            #exec {fd_count}>&-
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}

        } {fd_read}</mnt/ramdisk/flist 1>&${fd1} 2>&${fd2}
    ) &
    P+=($!)
  } {fd1}>&1 {fd2}>&2
}
;;


esac



[[ $(echo ./total.* ./count.* ./final.* ) ]] && \rm ./total.* ./count.* ./final.*


dataN=1000000000

echo "Generating test data..." >&2
case "$1" in
	7|8)
        dataN="$(wc -l /mnt/ramdisk/flist)"
	    exec {fd_scan}</mnt/ramdisk/flist

ff() {
sha1sum "${@}"
sha256sum "${@}"
sha512sum "${@}"
sha224sum "${@}"
sha384sum "${@}"
md5sum "${@}"
sum -s "${@}"
sum -r "${@}"
cksum "${@}"
b2sum "${@}"
cksum -a sm3 "${@}"
xxhsum "${@}"
xxhsum -H3 "${@}"
}
        export -f ff
    ;;
	4|5)
	#	seq $dataN >test.dat
        exec {fd_scan}<test.dat
	;;
	*)
		yes $'\n' | head -n $dataN > test.dat
        exec {fd_scan}<test.dat
	;;
esac


exec {fd_spawn}<><(:)
total=0
P=()

export nWorkers=1
export nWorkersMax=$(( $(nproc) ))
#export nBytesMax=ARG_MAX
#export nLinesMax=4096
#export nBatchMax=4096

start_time=${EPOCHREALTIME//./}

ring_init
if enable -f forkrun_ring.so evfd_copy evfd_signal; then
echo "Starting splicer..." >&2
    mkdir -p /dev/shm/.forkrun
    TMPDIR="$(mktemp -d -p  /dev/shm/.forkrun -t forkrun.XXXXXXXX)"
    : > ${TMPDIR}/stdin
    echo "Sending stdin to ${TMPDIR}/stdin" >&2
    exec {fd_scan}>&-
    {
    (
        evfd_copy ${fd_write} ${fd_stdin}
        evfd_signal
         printf '\nSPLICER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&$fd2
    ) &
    } {fd_scan}<"${TMPDIR}/stdin" {fd_write}>"${TMPDIR}/stdin" {fd_stdin}<test.dat {fd2}>&2
    SPLICE_PID=$!
fi

echo "Starting scanner..." >&2
( ring_scanner ${fd_scan} ${fd_spawn} ) &
SCANNER_PID=$!

if  enable -f forkrun_ring.so ring_fallow ring_ack; then
exec {fd_falloc}<><(:)
echo "Starting falloc..." >&2
    export RING_FALLOC_FLAG=true
    ( ring_fallow ${fd_falloc} ${fd_write} ) &
    FALLOC_PID=$!
else
    export RING_FALLOC_FLAG=false
fi

# 4. Consumer Loop
printf "\nConsuming...\n\n" >&2


sleep 0.1s
for (( nn=0; nn<nWorkers; nn++)); do
    spawn_worker "$nn"
done

while true; do
    read -r -u $fd_spawn N
    [[ "$N" == 'x' ]] && { printf '\nSCANNER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )) >&2; break; }
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
for p in $SPLICE_PID $SCANNER_PID $FALLOC_PID; do
kill $p 2>/dev/null
wait $p 2>/dev/null
done

exec {fd_spawn}>&- 
exec {fd_scan}>&-
${RING_FALLOC_FLAG} && exec {fd_falloc}>&-

cat ./final.*
)

