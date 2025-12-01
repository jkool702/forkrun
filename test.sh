#!/usr/bin/bash

enable -f ./forkrun_ring.so ring_init ring_scanner ring_claim ring_worker lseek

spawn_worker() {
    (
        {
            ring_worker inc  # Register ourselves as 1 worker
            while ring_claim OFF CNT; do
                [[ "$CNT" == "0" ]] && break
                ((total+=CNT))
                #lseek $fd_read $OFF SEEK_SET ''
                #mapfile -t -u $fd_read -n $CNT A
                #: "${A[@]}"
            done
            ring_worker dec  # de-register worker
            echo "$total" >./total.${1}
        } {fd_read}<test.dat
    ) &
    P+=($!)
}

dataN=1000000000

echo "Generating test data..."
yes $'\n' | head -n $dataN > test.dat

\rm ./total.*

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
    [[ "$N" == 'x' ]] && break
    nWorkers0="$nWorkers"
    (( nWorkersMax0 = ( nWorkers0 + N ) > nWorkersMax ? nWorkersMax : nWorkers0 + N ))
    (( N > 0 )) && for ((nn=nWorkers0; nn<nWorkersMax0; nn++)); do
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
kill $SCANNER_PID 2>/dev/null
wait $SCANNER_PID 2>/dev/null

exec {fd_spawn}>&- 
exec {fd_scan}>&-