#!/bin/bash

forkrun_coproc() {
## Efficiently runs many tasks in parallel using coprocs
#
# USAGE is the same as the running a loop in parallel using xargs -P /  parallel.
# source this file, then pass inputs to parallelize over on stdin, 
# and pass function name and initial arguments as function inputs. 
#
# printf '%s\n' "${inArgs}" | forkrun_coproc [(-j|-P) <#>] functionName (initialArgs)
# example :    find ./ -type f | forkrun_coproc sha256sum
# 
# use -j or -P to specify the number of simultanious processes to use at a given time
# default if not given is to use the number of logical cpou cores $(nproc)
# 
# For each simultanious porocess requested, a coproc is forked off. Data are then piped in/out of these coprocs.
# Importantly, this means that you dont need to fork anything after the initial coprocs are set up.
# This makes this parallelization method MUCH faster than forking (especially for tasks with many short/quick tasks).
# In my testing it was also a considerable amount faster than xargs -P or parallel.

# enable job control
set -m

# set exit trap to clean up
exitTrap() (
    exec {fd_coreInd}>&-
    jobs -rp | xargs -r kill
    trap - EXIT ERR HUP TERM INT RETURN 
)
trap 'exitTrap' EXIT ERR HUP TERM INT RETURN 

# make variables local
local -a FD_in
local -a FD_out
local -a pidA
local tmpPipe
local parFunc
local nArgs
local nProcs
local nSent
local nDone
local fd_coreInd
local inArgCur
local stdinReadFlag

# open anonymous pipe. 
# This is used by the coprocs to indicate that they are done with a task and ready for another.
tmpPipe="$(mktemp -u)"
mkfifo "${tmpPipe}"
exec {fd_coreInd}<>"${tmpPipe}"
rm -f "${tmpPipe}"

# parse inputs for function name and nProcs
# any initial arguments are rolled into variable $parFunc
nProcs=0
if [[ "${1,,}" =~ -+[jp]$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
    nProcs="${2}"
    shift 2
    parFunc="${*}"
elif [[ "${1,,}" =~ -+[jp]=?[0-9]+$ ]]; then
    nProcs="${1#*[jp]}"
    nProcs="${nProcs#=}"
    shift 1
    parFunc="${*}"
else
    parFunc="${*}"
fi
(( ${nProcs} == 0 )) && nProcs=$(which nproc 2>/dev/null 1>/dev/null && nproc || grep -cE '^processor.*: ' /proc/cpuinfo)

# return if we dont have anything to parallelize over
[[ -z ${parFunc} ]] && echo 'no function specified. aborting' >&2 && return 1
[[ -t 0 ]] && echo 'no input arguments given on stdin. aborting' >&2 && return 2

# fork off $nProcs coprocs and record FDs / PIDs for them
# unfortunately this requires a source <(...) [or eval <...>] call to do dynamically...
# without this the coproc index "$kk" doesnt get properly applied in the loop.
# after each worker finishes its current task, it sends its index to pipe {fd_coreInd} to recieve another task
# when finished it will be send a null input, causing it to break its 'while true' loop and terminate
for kk in $(seq 0 $(( ${nProcs} - 1 ))); do

source <(cat<<EOF
{ coproc p${kk} {
while true; do
    read -r -d ''
    [[ -z \$REPLY ]] && break
    ${parFunc} "\$REPLY" >&4
    printf '%s\0' "${kk}" >&\${fd_coreInd}
done
}
} 4>&1
EOF
)
    local -n pCur=p${kk}
    FD_in+=("${pCur[1]}")
    FD_out+=("${pCur[0]}")
    local +n pCur
    local -n pCur_PID=p${kk}_PID
    pidA+=("$pCur_PID")
    local +n pCur_PID

done

# set initial vlues for the loop
nSent=0
nDone=0
stdinReadFlag=true

# populate pipe {fd_coreInd} with $nprocs initial indicies - 1 for each coproc
printf '%s\0' "${!FD_in[@]}" >&${fd_coreInd}

# begin parallelization loop
while { ${stdinReadFlag} || (( ${nDone} < ${nArgs} )); }; do
    if ${stdinReadFlag}; then
		# read all inputs that we can from stdin
		# the first $nProcs get sent to the workers
		# after this, each time a worker finishes they send their index 
		# back to {fd_coreInd} and are given another input to process
        while read -r inArgCur </dev/stdin; do
            read -d '' <&${fd_coreInd}
            printf '%s\0' "${inArgCur}" >&${FD_in[$REPLY]}
            ((nSent++))
            (( ${nSent} > ${nProcs} )) && ((nDone++))
           done
		   
		   # we have read all of stdin. We now know how many total inputs there are
		   # all tasks have been sent out, but there are still $nProcs tasks processing - 1 for each coproc
           nArgs=${nSent}
           stdinReadFlag=false
    else
		# as we recieve the last $nProcs tasks, send a null input to the now finished coproc, causing it to terminate
        read -d '' <&${fd_coreInd}
        printf '\0' >&${FD_in[$REPLY]}
        ((nDone++))
    fi
done

}
