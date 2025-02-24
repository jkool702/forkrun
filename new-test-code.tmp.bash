# NOTE: PRETEND THAT NBASH SUPPORTS FLOATING POINT ARITHMETIC AND DECIMAL VALUES FOR THIS EXAMPLE
# I WILL RE-STRUCTURE THE ARITHMETIC TO MAKE IT WORK WITHOUT NEEDING DECIMALS LATER ON

tStart=${EPOCHREALTIME//./}
nCPU=$(nproc)
sysLoadTarget=90
sysLoadTargetMax=90
sysLoadLast=0

# record initial /proc/stats in stats0

# fork "helper coprocs"

# record /proc/stats again in stats1. 
# pass difference to a function "get_cpu stats1 stats0" to get background cpu usage (cpu_bg) and replace stats0=stats1
cpu_bg=$(get_cpu stats1 stats0)

# fork N initial "worker coprocs"
for (( kk=0; kk<N; kk++ )); do
    fork_coproc_worker
done

# initialize some values
kkProcs=$N
kkProcs0=0
kkProcsUpdateFlag=true
linesCur0=$(( lines_read_from_tmpfile + estimated_unread_lines_in_tmpfile ))
tLast=${EPOCHREALTIME//./}
declare -a lineRate_run lines_runA times_runA
lineRate_run[0]=0


### BEGIN MAIN LOOP
until end_condition; do

    # update cpu utilization 
    # record /proc/stats again in stats1. 
    # if we increased kkProcs on the previous iteration then reset stats
    if ${kkProcsUpdateFlag}; then
        # replace stats0=stats1 
        
        # reset average per-worker cpu usage (cpu_worker) with kkProcs workers 
        cpu_worker=$(( ( $(get_cpu stats1 stats0) - cpu_bg ) / kkProcs))
    
        kkProcsUpdateFlag=false
    else
        # update average per-worker cpu usage (cpu_worker) with kkProcs workers 
        cpu_worker=$(( ( cpu_worker + ( ( $(get_cpu stats1 stats0) - cpu_bg ) / kkProcs) ) ) / 2 ))
    fi
        
    # update estimates of lineRate_stdin (how fast lines are arriving on stdin) 
    # use average of long-term and short-term estimates of stdin line arrival rates
    # note: line counts/estimates are handled by another helper coproc
    linesCur=$(( lines_read_from_tmpfile + estimated_unread_lines_in_tmpfile ))
    tCur=${EPOCHREALTIME//./}
    lineRate_stdin=$(( ( ( linesCur / ( tCur - tStart ) ) + ( ( linesCur - linesCur0 ) / ( tCur - tlast ) ) ) / 2 ))    
    linesCur0=$linesCur
    tLast=$tCur
    
    # update lineRate_run (how fast we are processing lines at current kkProcs)
    # worker coprocs send data with # lines run and time taken to run those lines to anon pipe fd_runtimes
    read -r -u $fd_runtimes run_lines run_time
    run_timeA[$kkProcs]+=$run_time
    run_linesA[$kkProcs]+=$run_lines
    while read -r -u $fd_runtimes -t 0.001 run_lines run_time; do
        run_timeA[$kkProcs]+=$run_time
        run_linesA[$kkProcs]+=$run_lines
    done
    lineRate_run[$kkProcs]=$(( ( kkProcs * run_linesA[$kkProcs] ) / run_timeA[$kkProcs] ))
    
    # dynamically adjust sysLoadTarget
    sysLoadCur=$((kkProcs * cpu_worker))
    if (( sysLoadCur > sysLoadTargetMax )); then
        # sysload too high - dont spawn
        continue
    elif (( sysLoadLast > sysLoadCur )); then
        # adding more workers decreases system load. lower sysLoadTarget
        sysLoadTarget=$sysLoadCur
    elif (( sysLoadCur > sysLoadTarget ))
        # sysload between current and max targets. increase sysLoadTarget a bit
        sysLoadTarget=$(( ( sysLoadCur + sysLoadTarget + sysLoadTargetMax ) / 3 ))
    fi
    
    # compare data processing rate to data input rate. Dont spawn more workers if either:
    # 1. we are already processing lines faster than they are arriving on stdin, or
    # 2. we are processing lines more slowly than we were before the most recent spawning of additional workers
    { (( lineRate_run[$kkProcs] >= lineRate_stdin )) || (( lineRate_run[$kkProcs] < lineRate_run[$kkProcs0] )); } && continue   
    
    # estimate how many additional workers are needed (at current cpu usage per worker) to hit sysLoadTarget    
    nAdd_sysLoad=$(( ( sysLoadTarget - sysLoadCur ) / cpu_worker ))
    
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
    
    kkProcsUpdateFlag=true
    
done
