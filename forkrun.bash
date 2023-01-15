#!/bin/bash -x

forkrun() {
## Efficiently runs many tasks in parallel using coprocs
#
# USAGE: printf '%s\n' "${inArgs}" | forkrun_coproc [(-j|-P) <#>] [-k] functionName (initialArgs)
# EXAMPLE:    find ./ -type f | forkrun_coproc sha256sum
#
# Usage is the same as the running a loop in parallel using xargs -P /  parallel.
# source this file, then pass inputs to parallelize over on stdin, 
# and pass function name and initial arguments as function inputs. 
#
# For each simultanious porocess requested, a coproc is forked off. Data are then piped in/out of these coprocs.
# Importantly, this means that you dont need to fork anything after the initial coprocs are set up.
# This makes this parallelization method MUCH faster than forking (especially for tasks with many short/quick tasks).
# In my testing it was also a considerable amount faster than xargs -P or parallel.
#
# FLAGS
#
# -j or -P  use either of these flags to specify the number of simultanious processes to use at a given time
# 			The default if not given is to use the number of logical cpou cores $(nproc)
#
#   -k 		use this flag to force the output to be given in the same order as arguments were given on stdin.
#           the "cost" of this is a) you wont get any output as the code runs - it will all come at one at the end 
# 			and b) the code runs slightly slower (5-10%).  This internally uses an additional "hidden" flag: -0.
#
#   -- 		Use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'. 
# 			This could be used to ensure a functionName of, say, '-k' is parsed as the functionName, not as a forkrun option flag.
# 
# NOTE: Flags are not case sensitive and can be given in any order, but must all be given before the "functionName" input


# enable job control
set -m

# set exit trap to clean up
exitTrap() (
    source <(find /proc/{$$,self}/fd | xargs -l1 basename | grep -E '^[0-9]+$' | sort -u | grep -vE '^((0)|(1)|(2)|(3)|(255))$' | awk '{ printf "exec %s>&-\n",$0 }')
    jobs -rp | xargs -r kill
    exec {fd_coreInd}>&-
    trap - EXIT HUP TERM INT RETURN 
    kill $$
    return
)
trap 'exitTrap' EXIT HUP TERM INT RETURN 

# make variables local
local -a FD_in
local -a FD_out
local -a pidA
local parFunc
local nArgs
local nProcs
local nSent
local nDone
local fd_coreInd
local inArgCur
local pCur
local pCur_PID
local stdinReadFlag
local orderedOutFlag
local exportOrderFlag

# open anonymous pipe. 
# This is used by the coprocs to indicate that they are done with a task and ready for another.
exec {fd_coreInd}<><(:)

# parse inputs for function name and nProcs
# any initial arguments are rolled into variable $parFuncnProcs=0
orderedOutFlag=false
exportOrderFlag=false
nProcs=0
while [[ "${1}" =~ ^-+[jpk0\-].*$ ]]; do
    if [[ "${1,,}" =~ ^-+[jp]$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+[jp]=?[0-9]+$ ]]; then
        nProcs="${1#*[jp]}"
        nProcs="${nProcs#=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+k$ ]]; then
		# user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1}" =~ ^-+0$ ]]; then
		# sore will output sorting order with output to allow for auto output re-sorting
        exportOrderFlag=true
        shift 1    
    elif [[ "${1}" == '--' ]]; then
		# stop processing forkrun options
        shift 1
        break
    fi
done
# all remaining inputs are functionName / initialArgs
parFunc="${*}"

# default nProcs is # logical cpu cores
(( ${nProcs} == 0 )) && nProcs=$(which nproc 2>/dev/null 1>/dev/null && nproc || grep -cE '^processor.*: ' /proc/cpuinfo)


# return if we dont have anything to parallelize over
[[ -z ${parFunc} ]] && echo 'NO FUNCTION SPECIFIED. ABORTING' >&2 && return 1
[[ -t 0 ]] && echo 'NO INPUT ARGUMENTS GIVEN ON STDIN. ABORTING' >&2 && return 2

# if user requested ordered output, re-run the forkrun call trading flag '-k' for flag '-0',
# then sort the output and remove the ordering index. Flag '-0' causes forkrun to do 2 things: 
# a) results for a given input have newlines replaced with '\n' (so each result takes 1 line), and 
# b) each result line is pre-pended with the index/order that it was recieved in from stdin.
if ${orderedOutFlag}; then
    forkrun -j"$(( ${nProcs} - 1 ))" -0 "${parFunc}" | sort -n -k 1 -t $'\t' | printf '%b' "$(</dev/stdin)" | cut -d $'\t' -f 2- 
    return
fi

# fork off $nProcs coprocs and record FDs / PIDs for them
#
# unfortunately this requires a source <(...) [or eval <...>] call to do dynamically...
# without this the coproc index "$kk" doesnt get properly applied in the loop.
# after each worker finishes its current task, it sends its index to pipe {fd_coreInd} to recieve another task
# when finished it will be send a null input, causing it to break its 'while true' loop and terminate
#
# if ordered output is requested, the input order inde is prepended to the argument piped to the worker, 
# where it is removed and then pre-pended onto the result from running the argument through the function
for kk in $(seq 0 $(( ${nProcs} - 1 ))); do

if ${exportOrderFlag}; then

source <(cat<<EOF
{ coproc p${kk} {
    local outCur
while true; do
    read -r -d '' 
    [[ -z \$REPLY ]] && break
    
        outCur="\$(printf '%s\t' "\${REPLY%%,*}"; ${parFunc} "\${REPLY#*,}")"
        printf '%s\n' "\${outCur//$'\n'/\\n}" >&4
    
    printf '%d\0' "${kk}" >&\${fd_coreInd}
done
} 
} 4>&1
EOF
)

else

source <(cat<<EOF
{ coproc p${kk} {
while true; do
    read -r -d ''
    [[ -z \$REPLY ]] && break
    ${parFunc} "\$REPLY" >&4
    printf '%d\0' "${kk}" >&\${fd_coreInd}
done
} 
} 4>&1
EOF
)

fi
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
printf '%d\0' "${!FD_in[@]}" >&${fd_coreInd}

# begin parallelization loop
if ${exportOrderFlag}; then

# user requested ordered output
while { ${stdinReadFlag} || (( ${nDone} < ${nArgs} )); }; do
    if ${stdinReadFlag}; then
        # read all inputs that we can from stdin
        # the first $nProcs get sent to the workers
        # after this, each time a worker finishes they send their index 
        # back to {fd_coreInd} and are given another input to process
		# pre-pend the input order index (nSent) to each input sent to the workers
        while read -r inArgCur </dev/stdin; do
            read -d '' <&${fd_coreInd}
            printf '%d,%s\0' "${nSent}" "${inArgCur}" >&${FD_in[$REPLY]}
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

else

# no ordered output
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

fi
}

# Note: this is the same as forkrun_coproc.bash except the funbction name is shortened to just 'forkrun'