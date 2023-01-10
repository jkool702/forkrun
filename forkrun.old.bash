#!/bin/bash 

forkrun() {
## RUNS ALL GIVEN INPUTS THROUGH A SPECIFIED FUNCTION/SCRIPT IN PARALLEL BY FORKING THEM OFF IN A LOOP
#
# USAGE: forkrun [-v|--verbose] [-d|--debug] [-P <#>|--parallel[-threads]=<#>] [--] funcName in1 in2 in3 ...
#        forkrun [-v|--verbose] [-d|--debug] [-P <#>|--parallel[-threads]=<#>] (-f funcName|--function[-name]=funcName) [--] in1 in2 in3 ...
#        forkrun  in1 in2 in3 ... [-v|--verbose] [-d|--debug] [-P <#>|--parallel[-threads]=<#>] (-f funcName|--function[-name]=funcName)
#
# OPTIONS:
#
# -f <...> | --function[-name]=<...> : sets the name/path of the function/script to run in parallel using different input args
#                                      if omitted, it is assumed that the 1st non-forkrun-option argument is the function/script name:
#                                      The following will be used (in decreasing prefferance) to ID the scpeified function/script:
#                                      1. declare -f <...>      2. which <...>      3. [[ -f <...> ]] && file <...> | grep executable
#                                      
#
# -P <#> | --parallel[-threads]=<#> :  sets the number of simultanious forks to use. if omitted, use the number of logical processor cores (nproc)
#                                      if set to '0', use the number of logical processor cores and force each task to run only on a single core via taskset
#
# -v | --verbose : increase verbosity
#
# -d | --debug   : increase verbosity even more and slow down execution by adding a "sleep 0.1s" before each command (via a debug trap). Implies -v.
#
# -- : all inputs after the '--' will be treated as function inputs to parallelize over. They wont be analysed, and wont set forkrun options even if they match one of the above options.
#      note: if you have A LOT of inputs to parallelize over then using '--' might significantly speed up the "options processing" part of this function.
#
# NOTE: options will attempt to be matched with somewhat "fuzzy" matching. They are case insensitive, and both short and long options can use the others notation. 
#       example: '--p=<#>' and '-PaRaLlEl <#>' both will set the '-P' paramater described above.

    # declare local variables
    
    local nn
    local -i kk
    local -i maxParallelThreads
    local -i numActiveJobs
    local -a inArgs
    local verboseFlag
    local tasksetFlag
    local parser_rmNextFlag
    local parFunc
    local fifoPipe
    local debugFlag
    local nArgs
  
      
    # load all inputs into a bash array
    for nn in "${@}"; do
        inArgs[${#inArgs[@]}]="${nn}"
    done

    # parse inputs
    verboseFlag=false
    debugFlag=false
    parser_rmNextFlag=false
    for kk in ${!inArgs[@]}; do
        if { [[ -z "${inArgs[${kk}]}" ]] || ${parser_rmNextFlag}; }; then
            unset "inArgs[${kk}]"
            parser_rmNextFlag=false
        elif [[ "${inArgs[${kk}],,}" =~ ^-+f(unc)?(\-?n(ame)?)?=.+$ ]]; then
            parFunc="${inArgs[${kk}]##*=}"
            unset "inArgs[${kk}]"
        elif { [[ "${inArgs[${kk}],,}" =~ ^-+f(unc)?(\-?n(ame)?)?$ ]] && [[ ${inArgs[$(( ${kk} + 1 ))],,} =~ ^.+$ ]]; }; then
            parFunc="${inArgs[$(( ${kk} + 1 ))]}"
            unset "inArgs[${kk}]"
            parser_rmNextFlag=true
        elif [[ "${inArgs[${kk}],,}" =~ ^-+p(ar(allel)?)?(\-?t(hreads)?)?=[0-9]+$ ]]; then
            maxParallelThreads=${inArgs[${kk}]##*=}
            unset "inArgs[${kk}]"
        elif { [[ "${inArgs[${kk}],,}" =~ ^-+p(ar(allel)?)?(\-?t(hreads)?)?$ ]] && [[ ${inArgs[$(( ${kk} + 1 ))]} =~ ^[0-9]+$ ]]; }; then
            maxParallelThreads=${inArgs[$(( ${kk} + 1 ))]}
            unset "inArgs[${kk}]"
            parser_rmNextFlag=true
        elif [[ "${inArgs[${kk}],,}" =~ ^-+v(erbose)?$ ]]; then
            verboseFlag=true
            unset "inArgs[${kk}]"
        elif [[ "${inArgs[${kk}],,}" =~ ^-+d(ebug)?$ ]]; then
            debugFlag=true
            unset "inArgs[${kk}]"
        elif [[ "${inArgs[${kk}]}" == '--' ]]; then
            unset "inArgs[${kk}]"
            break
        fi
    done
    
	# setup debug flag
    ${debugFlag} && set -x && trap 'sleep 0.1s' DEBUG
    ${debugFlag} && verboseFlag=true 

    # squeeze out emptry indicies in inArgs
    mapfile -t inArgs < <(printf '%s\n' "${inArgs[@]}" | grep -E '^.+$')

    # set funcName to 1st element in inArgs if not yet set, than validate it
    [[ -z ${parFunc} ]] && (( $# > 0 )) && parFunc="${inArgs[0]}" && inArgs[0]='' && mapfile -t inArgs < <(printf '%s\n' "${inArgs[@]}" | grep -E '^.+$')
    if declare -F "${parFunc}"; then
        parFunc="$(declare -F "${parFunc}")"
    elif which "${parFunc}" 2>/dev/null 1>/dev/null; then
        parFunc="$(which "${parFunc}")"
    elif [[ -f "${parFunc}" ]] && file "${parFunc}" | grep -qi 'executable'; then
        parFunc="$(realpath "${parFunc}")"
    else
        echo "could not find ${parFunc} - it is not a declared function or along your current path. Aborting" >&2 && return 1
    fi
    
    ${verboseFlag} && echo "Function to run in parallel: ${parFunc}" >&2 && sleep 1
    nArgs=${#inArgs[@]}
   
    # set maxParallelThreads and determine if using taskset
    (( ${maxParallelThreads} == 0 )) && tasksetFlag=true || tasksetFlag=false
    { [[ -z ${maxParallelThreads} ]] || (( ${maxParallelThreads} == 0 )); } && maxParallelThreads=$(which nproc 2>/dev/null && nproc || grep -cE '^processor.* [0-9]+$' /proc/cpuinfo)
    ${verboseFlag} && echo "Number of simultanious forked processees: ${maxParallelThreads} ($(${tasksetFlag} || echo 'no ')taskset)" >&2 && sleep 1
    
    if ${tasksetFlag}; then
    
        # setup for using taskset
    
        # open anonymous pipe to pipe "free" CPU ID's from (finished) forked process back to forking loop
        fifoPipe='/tmp/.forkrun.fifo.pipe'
        [[ -p "${fifoPipe}" ]] || mkfifo "${fifoPipe}"    
        exec 3<>"${fifoPipe}"
        rm "${fifoPipe}"
        
        # setup function wrapper to run funcName with the taskset CPU depetmined by reading from the pipe and a trap that pipes back the CPU number when finished
        # this allows each taskset forked process to select a not-currently-in-use (by forkrun) CPU to use
        runParFunc() {
            read CPU <&3
            trap 'echo '"${CPU}"' >&3; trap - RETURN ERR' RETURN ERR
            ${verboseFlag} && echo "running job on CPU #${CPU}" >&2
            taskset -c "${CPU}" "${parFunc}" "${inArgs[${1}]}" | printf '%s %q\n' "${1}" "$(</dev/stdin)"
        }
    
        # prime the pipe with $maxParallelThreads processor ID's to use
        printf '%d\n' $(seq 0 $(( ${maxParallelThreads} - 1 ))) >&3
        
    fi    
     
    # Loop over inputs
    
    for kk in ${!inArgs[@]}; do
    # run function forked. Use printf to squash iots output into 1 line and prepend the input index
        if ${tasksetFlag}; then
            runParFunc ${kk} &
        else
            "${parFunc}" "${inArgs[${kk}]}" | printf '%s %q\n' "${kk}" "$(</dev/stdin)" &
        fi
        
        # get number of current active jobs and wait for 1 to finish if it is >= ${maxParallelThreads}
        numActiveJobs=$(jobs -rp | wc -l)
        (( ${numActiveJobs} >= ${maxParallelThreads} )) && wait -nf 
        
        # add status indicator outpout to stderr if in verbose mode
        ${verboseFlag} && echo "$(( ${kk} +1 )) started jobs; $(( ${kk} + 1 - ${numActiveJobs} )) finished jobs; ${numActiveJobs} active jobs" >&2
        
        # on last loop iteration wait for all remaining processes to finish
        (( ${kk} == ( ${nArgs} - 1 ) )) && { ${verboseFlag} && echo "waiting for final jobs to finish" >&2 || true; } && wait -f 
        
        # finish loop. Take combined output and sort it by the prepended order index, then remove this and expand it back to its original form. This ensures that the output ordering is the same as the input ordering
    done  | sort -V -i -k 1 | sed -E s/'^[0-9]+ '// | sed -E s/'\$'"'"'\\t'"'"/'\\t'/g | printf '%b\n' "$(</dev/stdin)" | sed -E s/'\\(.)'/'\1'/g
    
    # clean up, if needed
    ${tasksetFlag} && 3>&-
    ${debugFlag} && set +x && trap - DEBUG
    
    return 0
 }  
