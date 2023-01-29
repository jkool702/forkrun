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
# with many cores speedup can be >100x).# In my testing it was also a considerable amount faster than 'parallel' (5-10x) and
# (depending on the machine) between "roughly the same speed" and 4x faster than 'xargs -P'
#
# FLAGS
#
# -j or -P  use either of these flags to specify the number of simultanious processes to use at a given time
#           The default if not given is to use the number of logical cpou cores $(nproc)
#
#    -k     use this flag to force the output to be given in the same order as arguments were given on stdin.
#           the "cost" of this is a) you wont get any output as the code runs - it will all come at one at the end 
#           and b) the code runs slightly slower (10-20%).  This re-calls forkrun with the '-0' flag and then sorts the output
#
#    -0     use this flag to force the output for each input to be printed on 1 line (newlines are replaced by '\n')
#           and pre-pended with "<#> $'\t'", where <#> reprenenst the order of the input that generated that result.
#           THis is used by the '-k' flag to re-order the output to the same order as the inputs
#
#    --     use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'. 
#           This could be used to ensure a functionName of, say, '-k' is parsed as the functionName, not as a forkrun option flag.
# 
# NOTE: Flags are not case sensitive and can be given in any order, but must all be given before the "functionName" input
#
# DEPENDENCIES:
# if used without '-k' and with '(-j | -P) <(#>0)>': none. The code uses 100% bash builtins
# if used without '(-j | -P)' or with '(-j | -P) 0': either 'nproc' OR 'grep' + procfs to determine logical core count
# if used with '-k': 'sort' and 'cut' to reorder the output


# enable job control
set -m

# set exit trap to clean up
exitTrap() {
    local FD
    local fd_coreInd
    
    # restore IFS
    export IFS="${IFS0}"
    shift 1    

    fd_coreInd="$1"
    shift 1

    # shutdown all coprocs
    for FD in "${@}"; do
        [[ -e /proc/$$/fd/${FD} ]] && printf '\0' >&${FD}
    done
    jobs -rp | xargs -r kill

    # close coreInd return pipe
	[[ -e /proc/$$/"${fd_coreInd}" ]] && exec {fd_coreInd}>&-

    # unset traps
    trap - EXIT HUP TERM INT 
}
trap 'exitTrap "${IFS0}" "${fd_coreInd}" "${FD_in[@]}"' EXIT HUP TERM INT  

# make variables local
local -a FD_in
local -a FD_out
local -a pidA
local parFunc
local nArgs
local nProcs
local nSent
local nDone
local nBatch
local nBatchCur
local fd_coreInd
local coreInd
local pCur
local pCur_PID
local stdinReadFlag
local orderedOutFlag
local exportOrderFlag
local IFS0
local outCur

IFS0="${IFS}"

# open anonymous pipe. 
# This is used by the coprocs to indicate that they are done with a task and ready for another.
exec {fd_coreInd}<><(:)

# parse inputs for function name and nProcs
# any initial arguments are rolled into variable $parFuncnProcs=0
orderedOutFlag=false
exportOrderFlag=false
nProcs=0
nBatch=1
while [[ "${1}" =~ ^-+[jpkl0\-].*$ ]]; do
    if [[ "${1,,}" =~ ^-+[jp]$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+[jp]=?[0-9]+$ ]]; then
        nProcs="${1#*[jp]}"
        nProcs="${nProcs#=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+l$ ]] && [[ "${2}" =~ ^(([0-9]+)|(auto([_\-]?strict)?))$ ]]; then
        nBatch="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+l=?(([0-9]+)|(auto([_\-]?strict)?))$ ]]; then
        nBatch="${1#*l}"
        nBatch="${nBatch#=}"
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
    forkrun -j"${nProcs}" -0 -- "${parFunc}" | sort -s -z -n -k 1 -t$'\t' | printf '%b' "$(</dev/stdin)" | cut -d $'\t' -f 2- 
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

source <(cat<<EOF
{ coproc p${kk} {
export IFS=$'\n'
while true; do
    read -r -s -d '' 
    [[ -z \$REPLY ]] && break
    
$(if ${exportOrderFlag}; then
cat<<EOI1
    outCur="\$(printf '\t%s\t' "\${REPLY%%\$'\t'*}"; ${parFunc} \${REPLY#*\$'\t'})"
    printf '%s\n\0' "\${outCur//\$'\n'/\\n}" >&4
EOI1
else
cat<<EOI2
    ${parFunc} \${REPLY} >&4
EOI2
fi)
    printf '${kk}\0' >&\${fd_coreInd}
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
nBatchCur=0 
stdinReadFlag=true

# populate pipe {fd_coreInd} with $nprocs initial indicies - 1 for each coproc
printf '%d\0' "${!FD_in[@]}" >&${fd_coreInd}

# begin parallelization loop
# user requested ordered output
while ${stdinReadFlag} || (( ${nDone} < ${nArgs} )); do
    if ${stdinReadFlag}; then
        # read all inputs that we can from stdin and group into NULL-seperated groups of $nBatch lines
        # each time a worker finishes they send their index back to {fd_coreInd} and are given another input to process
        # if ordering output, pre-pend the input order index (nSent) to each input group sent to the workers
        
        read -d '' coreInd <&${fd_coreInd}
        (( ${nSent} < ${nProcs} )) || ((nDone++))
        
        if [[ ${nBatch} == 1 ]]; then
            
            read -r -s </dev/stdin || { nArgs=${nSent}; stdinReadFlag=false; }
            printf '%s\0' "${REPLY}" >&${FD_in[${coreInd}]}
            ((nSent++))

        else

            nBatchCur=0  
            until [[ ${nBatchCur} == "${nBatch}" ]]; do
                read -r -s </dev/stdin || { { nArgs=${nSent};
                    stdinReadFlag=false;
                        [[ ${nBatch} == 0 ]] || ((nSent++)); 
                    }
                    nArgs=${nSent};
                    stdinReadFlag=false; 
                    break;
                }

                if [[ ${nBatchCur} == 0 ]]; then
                    ${exportOrderFlag} && printf '%s\t%s' "${nSent}" "${REPLY}" >&${FD_in[${coreInd}]} || printf '%s' "${REPLY}" >&${FD_in[${coreInd}]} 
                else
                    printf '\n%s' "${REPLY}" >&${FD_in[${coreInd}]} 
                fi
            
                ((nBatchCur++))
            done

            # indicate all lines of current input group has been sent --> null seperated parsing will group inputs for us
            [[ ${nBatchCur} == 0 ]] || {
                # indicate end of current input batch
                printf '\0' >&${FD_in[${coreInd}]} 
            
                # iterate sent counter
                ((nSent++))
            }

        fi

    else
        # as we recieve the last $nProcs tasks, send a null input to the now finished coproc, causing it to terminate
        read -d '' coreInd <&${fd_coreInd}
        printf '\0' >&${FD_in[$coreInd]}
        ((nDone++))
    fi
done

}
