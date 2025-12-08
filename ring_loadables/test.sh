#!/usr/bin/bash

ring_test() (

	(( $(enable -p | grep -F 'enable ring' | wc -l) >= 6 )) ||  enable -f forkrun_ring.so ring_init ring_scanner ring_claim ring_worker ring_destroy ring_transfer lseek

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
                : "${A[@]}"
            done
            ring_worker dec  # de-register worker
	    echo "$total" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<test.dat
    ) &
    P+=($!)
}
;;

*)
exec {fd_splice}<><(:)
cat test.dat >&${fd_splice} &
spawn_worker() {
    (
        {
            ITER=0
            Pcur=$BASHPID
            ring_worker inc  # Register ourselves as 1 worker
            while ring_transfer $fd_read 1; do
                ((ITER++))
                echo "$ITER" >./count.${1}
            done
            ring_worker dec  # de-register worker
	    echo "$ITER" >./total.${1}
            printf 'TOTAL=%s    ITER=%s    AVG=%s\n' "$total" "$ITER" "$((total/ITER))" >./final.${1}
            
        } {fd_read}<&${fd_splice}
    ) &
    P+=($!)
}
;;

esac

dataN=1000000000

echo "Generating test data..."
yes $'\n' | head -n $dataN > test.dat

\rm ./total.* ./count.* ./final.*

exec {fd_scan}<test.dat
exec {fd_spawn}<><(:)

ring_init

echo "Starting scanner..."
( ring_scanner ${fd_scan} ${fd_spawn} ) &
SCANNER_PID=$!

# 4. Consumer Loop
echo "Consuming..."
total=0
P=()
export nWorkers=1
export nWorkersMax=$(( 1 * $(nproc) ))

start_time=${EPOCHREALTIME//./}

for (( nn=0; nn<nWorkers; nn++)); do
    spawn_worker "$nn"
done

while true; do
    read -r -u $fd_spawn N
    [[ "$N" == 'x' ]] && { printf '\nSCANNER HIT EOF\nelapsed time = %s us\n' $(( ${EPOCHREALTIME//./} - start_time )); break; }
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

echo "Done."
echo "Total Lines Consumed: $total (Expected: $dataN)"
echo "Time: ${elapsed}us"

# Cleanup
ring_destroy
kill $SCANNER_PID 2>/dev/null
wait $SCANNER_PID 2>/dev/null

exec {fd_spawn}>&- 
exec {fd_scan}>&-

cat ./final.*
)

