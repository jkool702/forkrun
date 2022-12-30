#!/bin/bash 

forkrun() {

    #trap 'sleep 0.1s' DEBUG
    
    local nn
    local -i kk
    local -i maxParallelThreads
    local -i numActiveJobs
    local -a inArgs
    local verboseFlag
    local parser_rmNextFlag
    local parFunc
        
    # parse inputs
    
    for nn in "${@}"; do
        inArgs[${#inArgs[@]}]="${nn}"
    done

    verboseFlag=false
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
        elif [[ "${inArgs[${kk}],,}" =~ ^-+p(ar(allel)?)?(\-?t(hreads)?)?=[0-9]*[1-9]+[0-9]*$ ]]; then
            maxParallelThreads=${inArgs[${kk}]##*=}
            unset "inArgs[${kk}]"
        elif { [[ "${inArgs[${kk}],,}" =~ ^-+p(ar(allel)?)?(\-?t(hreads)?)?$ ]] && [[ ${inArgs[$(( ${kk} + 1 ))]} =~ ^[0-9]*[1-9]+[0-9]*$ ]]; }; then
            maxParallelThreads=${inArgs[$(( ${kk} + 1 ))]}
            unset "inArgs[${kk}]"
            parser_rmNextFlag=true
        elif [[ "${inArgs[${kk}],,}" =~ ^-+v(erbose)?$ ]]; then
            verboseFlag=true
            unset "inArgs[${kk}]"
        elif [[ "${inArgs[${kk}]}" == '--' ]]; then
            unset "inArgs[${kk}]"
            break
        fi
    done
    
    sleep 0.1s
    
    mapfile -t inArgs < <(printf '%s\n' "${inArgs[@]}" | grep -E '^.+$')

    [[ -z ${parFunc} ]] && (( $# > 0 )) && parFunc="${inArgs[0]}" && inArgs[0]='' && mapfile -t inArgs < <(printf '%s\n' "${inArgs[@]}" | grep -E '^.+$')
    
    if declare -F "${parFunc}"; then
        parFunc="$(declare -F "${parFunc}")"
    elif which "${parFunc}" 2>/dev/null 1>/dev/null; then
        parFunc="$(which "${parFunc}")"
    else
        echo "could not find ${parFunc} - it is not a declared function or along your current path. Aborting" >&2 && return 1
    fi
    
    ${verboseFlag} && echo "Function to run in parallel: ${parFunc}" >&2 && sleep 2
    
    [[ -z ${maxParallelThreads} ]] && maxParallelThreads=$(which nproc 2>/dev/null && nproc || grep -cE '^processor.* [0-9]+$' /proc/cpuinfo) 
    ${verboseFlag} && echo "Number of simultanious forked processees: ${maxParallelThreads}" >&2
    
    for kk in ${!inArgs[@]}; do
        "${parFunc}" "${inArgs[${kk}]}" | printf '%s %q\n' "${kk}" "$(</dev/stdin)" &
        numActiveJobs=$(jobs -rp | wc -l)
        (( ${numActiveJobs} >= ${maxParallelThreads} )) && wait -nf 
        ${verboseFlag} && echo "$(( ${kk} +1 )) started jobs; $(( ${kk} + 1 - ${numActiveJobs} )) finished jobs; ${numActiveJobs} active jobs" >&2
        (( ${kk} == ( ${#inArgs[@]} - 1 ) )) && { ${verboseFlag} && echo "waiting for final jobs to finish" >&2 || true; } && wait -f 
    done | sort -V -i -k 1 | sed -E s/'^[0-9]+ '// | sed -E s/'\$'"'"'\\t'"'"/'\\t'/g | printf '%b\n' "$(</dev/stdin)" | sed -E s/'\\(.)'/'\1'/g
    
    return 0
 }   
