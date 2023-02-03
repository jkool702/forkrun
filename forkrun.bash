#!/bin/bash

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
# This makes this parallelization method MUCH faster than forking (for tasks with many short/quick tasks and on x86_64 machines
# with many cores speedup can be >100x). In my testing it was also comparable to, if not faster than, 'xargs -P' and 'parallel'
#
# # # # # FLAGS # # # # #
#
# (-j|-P) <#>  use either of these flags to specify the number of simultanious processes to use at a given time
#              The default if not given is to use the number of logical cpou cores $(nproc). The ' ' can be removed or replaced with '='.
#              i.e., the following all work: '-j <#>', '-P <#>', '-j<#>', '-P<#>, '-j=<#>', '-P=<#>'
#
#   -l <#>     use this flag to define the number of inputs to group together and pass to the worker coprocs. Default is 1.
#              sending multiple inputs at once typicallly is faster, since it reduces the number of individual 'parFunc' calls, but not all
#              functions support multiple inputs at once. NOTE: this should not be set higher than ( # lines input on stdin ) / ( # worker coprocs )
#              RECCOMENDED SETTING: set to ( # lines input on stdin ) / ( 4 * # worker coprocs ) --OR-- set to 512, whichever is LOWER
#
#    -k        use this flag to force the output to be given in the same order as arguments were given on stdin.
#              the "cost" of this is a) you wont get any output as the code runs - it will all come at one at the end
#              and b) the code runs slightly slower (10-20%).  This re-calls forkrun with the '-0' flag and then sorts the output
#
#    -0        use this flag to force the output for each input to be printed on 1 line (newlines are replaced by '\n')
#              and pre-pended with "<#> $'\t'", where <#> reprenenst the order of the input that generated that result.
#              This is used by the '-k' flag to re-order the output to the same order as the inputs
#
#    --     use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'.
#           This could be used to ensure a functionName of, say, '-k' is parsed as the functionName, not as a forkrun option flag.
#
# NOTE: Flags are not case sensitive and can be given in any order, but must all be given before the "functionName" input
#
# # # # # DEPENDENCIES # # # # #
# if used without '-k' and with '(-j | -P) <(#>0)>': none. The code uses 100% bash builtins
# if used without '(-j | -P)' or with '(-j | -P) 0': either 'nproc' OR 'grep' + procfs to determine logical core count
# if used with '-k': 'sort' and 'cut' to reorder the output
# if used with '-l' > 1: 'tr' is used in generative the stdin pre-filter

# enable job control
set -m

# set exit trap to clean up
exitTrap() {
    local FD
    local PID0
    local fd_index

    # get main process PID
    PID0="${1}"
    
    # restore IFS
    export IFS="${2}"

    # get pipe fd's
    fd_index="${3}"

    # shutdown all coprocs
    for FD in "${FD_in[@]}" "${FD_out[@]}"; do
        [[ -e /proc/"${PID0}"/fd/${FD} ]] && printf '\0' >&${FD}
    done
 
    # kill all background jobs
    jobs -rp | xargs -r kill

    # close pipes
    [[ -e /proc/"${PID0}"/fd/"${fd_index}" ]] && exec {fd_index}>&-

    # unset traps
    trap - EXIT HUP TERM INT 
}
trap 'exitTrap "${PID0}" "${IFS0}" "${fd_index}"' EXIT HUP TERM INT  

# make variables local
local -a FD_in
local -a FD_out
local -a pidA
local parFunc
local -i nArgs
local -i nSent
local -i nDone
local -i nProcs
local -i nBatch
local fd_index
local -i workerIndex
local outCur
local PID0
local pCur
local pCur_PID
local stdinReadFlag
local orderedOutFlag
local exportOrderFlag
local IFS0

# record main process PID
PID0=$$

# record IFS, so we can change it back to what itnoriginally was in the exit trap
IFS0="${IFS}"
export IFS=$'\n'

# open anonymous pipe. 
# This is used by the coprocs to indicate that they are done with a task and ready for another.
exec {fd_index}<><(:)

# parse inputs for function name and nProcs
# any initial arguments are rolled into variable $parFunc
orderedOutFlag=false
exportOrderFlag=false
nProcs=0
nBatch=1
while [[ "${1,,}" =~ ^-+[jpkl0\-].*$ ]]; do
    if [[ "${1,,}" =~ ^-+[jp]$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+[jp]=?[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${1#*[jpJP]}"
        nProcs="${nProcs#=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+l$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+l=?[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${1#*[lL]}"
        nBatch="${nBatch#=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+k$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1}" =~ ^-+0$ ]]; then
        # make output include input sorting order. Used internally with -k to allow for auto output re-sorting
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
[[ -z ${parFunc} ]] && echo 'ERROR: NO FUNCTION SPECIFIED. ABORTING' >&2 && return 1
[[ -t 0 ]] && echo 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (NOT A PIPE). ABORTING' >&2 && return 2

# if user requested ordered output, re-run the forkrun call trading flag '-k' for flag '-0',
# then sort the output and remove the ordering index. Flag '-0' causes forkrun to do 2 things: 
# a) results for a given input have newlines replaced with '\n' (so each result takes 1 line), and 
# b) each result line is pre-pended with the index/order that it was recieved in from stdin.
if ${orderedOutFlag}; then
    forkrun -j"${nProcs}" -l"${nBatch}" -0 -- "${parFunc}" | sort -z -n -k1 -t$'\t' | cut -z -d $'\t' -f 2- 
    return
fi

# if nBatch > 1 --> pre-process stdin and add NULL characters every $nBatch lines
# this allows for easier (loop-free) reading of individual batches of input lines via read -r -d ''
{
    export IFS=$'\n' && printf "$(export IFS=$'\n' && printf '%%s\\n=%.0s' $(seq 1 ${nBatch}) | tr -d '=')"'\0' $(</dev/fd/4) >&5 &
} 4<&0 5>&1 | {

# fork off $nProcs coprocs and record FDs / PIDs for them
#
# unfortunately this requires a source <(...) [or eval <...>] call to do dynamically...
# without this the coproc index "$kk" doesnt get properly applied in the loop.
# after each worker finishes its current task, it sends its index to pipe {fd_index} to recieve another task
# when finished it will be send a null input, causing it to break its 'while true' loop and terminate
#
# if ordered output is requested, the input order inde is prepended to the argument piped to the worker, 
# where it is removed and then pre-pended onto the result from running the argument through the function

    for kk in $(seq 0 $(( ${nProcs} - 1 ))); do

source <(cat<<EOI0 
{ coproc p${kk} {
trap - EXIT HUP TERM INT 
export IFS=\$'\\n'
while true; do 
    read -r -d '' -u 7
    [[ -z \${REPLY} ]] && break
    
$(if ${exportOrderFlag}; then
cat<<EOI1 
    printf '%d\\t%s\\n\\0' "\${REPLY%%\$'\\t'*}" "\$(export IFS=\$'\\n' && ${parFunc} \${REPLY#*\$'\\t'})" >&8
EOI1
else
cat<<EOI2
    { 
        export IFS=\$'\\n' && ${parFunc} \${REPLY}
    } >&8
EOI2
fi)
    printf '%d\\0' ${kk} >&\${fd_index}
done
} 7<&0
} 8>&9
EOI0
)
    # record PIDs and i/o file descriptors in indexed arrays
    local -n pCur="p${kk}"
    FD_in[$kk]="${pCur[1]}"
    FD_out[$kk]="${pCur[0]}"
    local +n pCur
    local -n pCur_PID="p${kk}_PID"
    pidA[$kk]="$pCur_PID"
    local +n pCur_PID

done

# begin parallelization loop

# set initial vlues for the loop
nSent=0
nDone=0
stdinReadFlag=true

# populate pipe {fd_index} with $nprocs initial indicies - 1 for each coproc
printf '%d\0' "${!FD_in[@]}" >&${fd_index}  

# read 1st input group. note that each input read will be for sending to a worker coproc the following iteration
# this potentially allows for faster response since the main thread doesnt have to wait to read an input before sending it to the worker coproc
read -r -d '' -u 6 && [[ -n $REPLY ]] || { echo 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (EMPTY PIPE). ABORTING' >&2 && return 3; }

while ${stdinReadFlag} || (( ${nDone} < ${nArgs} )); do

    # read {fd_index} to trigger sending the next input
    read -d '' workerIndex <&${fd_index}            
    (( ${nSent} < ${nProcs} )) || ((nDone++))
    
    if ${stdinReadFlag}; then
    # reading stdin

        # send already-read input to workers
         if ${exportOrderFlag}; then
            # sorting output. pre-pend data sent with index describing position in input list
           printf '%d\t%s\0' "${nSent}" "${REPLY}" >&${FD_in[${workerIndex}]}
        else
            # not sorting output. Just send input lines as-is
           printf '%s\0' "${REPLY}" >&${FD_in[${workerIndex}]}
        fi
        ((nSent++))

        # read next input. this will be send to a worker next iteration
        read -r -d '' -u 6 && [[ -n ${REPLY} ]] || { nArgs=${nSent}; stdinReadFlag=false; }
        
    else
        # we are done reading inputs from stdin. as each worker coproc finishes running its last task, send it '\0' to cause it to shutdown   
        printf '\0' >&${FD_in[${workerIndex}]}
        
    fi
        
done

} 6<&0 9>&1

}
