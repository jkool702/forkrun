# NOTE: PRETEND THAT NBASH SUPPORTS FLOATING POINT ARITHMETIC AND DECIMAL VALUES FOR THIS EXAMPLE
# I WILL RE-STRUCTURE THE ARITHMETIC TO MAKE IT WORK WITHOUT NEEDING DECIMALS LATER ON

tStart=${EPOCHREALTIME//./}
nCPU=$(nproc)
pLOAD_target=900000
pLOAD_max=900000
pLOADA0=0

# record initial /proc/stats in stats0

# fork "helper coprocs"

# record /proc/stats again in stats1. 
# pass difference to a function "get_cpu stats1 stats0" to get background cpu usage (pLOAD_bg) and replace stats0=stats1
pLOAD_bg=$(get_cpu stats1 stats0)

# fork N initial "worker coprocs"
for (( kk=0; kk<N; kk++ )); do
    fork_coproc_worker
done

# initialize some values
kkProcs=$N
kkProcs0=0
pAddFlag=true
read -r inLines inTime <"${tmpDir}"/.stdin_lines_time
declare -a lineRate_run lines_runA times_runA
lineRate_run[0]=0


### BEGIN MAIN LOOP
until end_condition; do

    # update cpu utilization 
    mapfile -t pLOADA < <(_forkrun_get_load "${pLOADA0[@]}")

    # if we increased kkProcs on the previous iteration then reset stats
    if ${pAddFlag}; then        
        # reset average per-worker cpu usage for kkProcs workers (pLOAD1) 
        pLOAD1[$kkProcs]=$(( ( pLOADA - pLOAD_bg ) / kkProcs))
        
        # update previous /proc/stats reference point
        pLOADA0=("${pLOADA[@]}")
    
        pAddFlag=false
    else
        # update average per-worker cpu usage  with kkProcs workers (pLOAD1)
        pLOAD1[$kkProcs]=$(( ( ( kkProcs * ${pLOAD1[$kkProcs]} ) + ( pLOADA - pLOAD_bg ) ) / ( 2 * kkProcs ) ))

    fi
        
    # update lineRate_run (how fast we are processing lines at current kkProcs)
    # worker coprocs send data with # lines run and time taken to run those lines to anon pipe fd_runtimes
    read -r -u $fd_runtimes runLines runTime
    runTimeA[$kkProcs]+=$runTime
    runLinesA[$kkProcs]+=$runLines
    while read -r -u $fd_runtimes -t 0.001 runLines runTime; do
        runTimeA[$kkProcs]+=$runTime
        runLinesA[$kkProcs]+=$runLines
    done
    lineRate_run[$kkProcs]=$(( ( kkProcs * runLinesA[$kkProcs] ) / runTimeA[$kkProcs] ))
    

    # update estimates of lineRate_stdin (how fast lines are arriving on stdin) 
    # use average of long-term and short-term estimates of stdin line arrival rates
    # note: line counts/estimates are handled by another helper coproc
    inLines0=$inLines
    inTime0=$inTime
    read -r inLines inTime <"${tmpDir}"/.stdin_lines_time
    lineRate_stdin=$(( ( ( inLines / inTime ) + ( ( inLines - inLines0 ) / ( inTime - inTime0 ) ) ) / 2 ))    

        # dynamically adjust pLOAD_target
    pLOADA=$(( kkProcs * ${pLOAD1[$kkProcs]} ))
    if (( pLOADA > pLOAD_max )); then
        # sysload too high - dont spawn
        continue
    elif (( pLOADA0 > pLOADA )); then
        # adding more workers decreases system load. lower pLOAD_target
        pLOAD_target=$pLOADA
    elif (( pLOADA > pLOAD_target )); then
        # sysload between current and max targets. increase pLOAD_target a bit
        pLOAD_target=$(( ( pLOADA + pLOAD_target + pLOAD_max ) / 3 ))
    fi
    
    # compare data processing rate to data input rate. Dont spawn more workers if either:
    # 1. we are already processing lines faster than they are arriving on stdin, or
    # 2. we are processing lines more slowly than we were before the most recent spawning of additional workers
    { (( lineRate_run[$kkProcs] >= lineRate_stdin )) || (( lineRate_run[$kkProcs] < lineRate_run[$kkProcs0] )); } && continue   
    
    # estimate how many additional workers are needed (at current cpu usage per worker) to hit pLOAD_target    
    nAdd_sysLoad=$(( ( pLOAD_target - pLOADA ) / ${pLOAD1[$kkProcs]} ))
    
    # estimate how many additional workers are needed (at current lineRate_run increase rate) to hit lineRate_stdin    
    nAdd_lineRate=$(( ( 1 - ( lineRate_stdin / lineRate_run ) ) * kkProcs ))
    
    # take the smaller of the two nAdd values
    (( nAdd_sysLoad < nAdd_lineRate )) & nAdd=nAdd_sysLoad || nAdd=nAdd_lineRate
    
    # compare how much our lineRate increased to how much our worker count increased
    # ideally, increasing kkProcs by X% will increase lineRate_run by X%
    # if lineRate_run icreases less than this then e are starting to hit other bottlenecjks and should slow down new coproc spawning
    nAdd=$(( nAdd * ( lineRate_run[$kkProcs] - lineRate_run[$kkProcs0] ) / ( 1 + ( kkProcs - kkProcs0 ) / kkProcs0 ) ))
    
    # about if nAdd is 0 (or is somehow negative)
    (( nAdd <= 0 )) && continue
    
    # fork nAdd additional "worker coprocs"
    for (( kk=0; kk<N; kk++ )); do
        fork_coproc_worker
    done
    
    # update kkProcs
    kkProcs0=${kkProcs}
    kkProcs+=${nAdd}
    
    pAddFlag=true
    
done
