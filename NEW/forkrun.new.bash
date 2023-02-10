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
#   -L <#>    use this flag to define the number of inputs to group together and pass to the worker coprocs. Sending multiple inputs at once 
#              typicallly is faster, though setting this higher than 512 or higher than ( # lines in stdin ) / (# worker coprocs ) tends to make 
#              forkrun slower, not faster. Set this to 0 to have forkrun automatically set and adjust this parameter for you (this is the DEFAULT). 
#              NOTE:  not all functions (e.g., basename) support running multiple inputs at once. To use these fuctions with forkrun you MUST call forkrun with `-L 0`
#
#  -t <path>   use this flag to set the base directory where tmp files containing groups of lines from stdin will be kept. Default is '\tmp'.
#              To speed up parsing stdin, forkrun splits up stdin into groups of $nBatch and saves them to [ram]disk. This path should not include whitespace characters.
#              These temp input files are then deleted according to `--remove-tmp-dir` policy set (see below). Highly reccomend that these be on a tmpfs/ramdisk.
#
#      -k      use this flag to force the output to be given in the same order as arguments were given on stdin.
#              the "cost" of this is a) you wont get any output as the code runs - it will all come at one at the end
#              and b) the code runs slightly slower (10-20%).  This re-calls forkrun with the '-n' flag and then sorts the output
#
#      -n      use this flag to force the output for each input batch to get pre-pended with "<#> $'\t'", where <#> reprenents where that result's input(s) were in 
#              the input queue.  This will be pre-pended once per output group, and output groups will be seperated by NULL characters, allowing the original input order
#              to be recreated easily using null-delimited parsing.  This is used by the '-k' flag to re-order the output to the same order as the inputs
#
#      -0      Assume that individual inputs passed on stdin are delimited by NULL's instead of by newlines. 
#
#      --      use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'.
#              This could be used to ensure a functionName of, say, '-k' is parsed as the functionName, not as a forkrun option flag.
#
#  --remove-   Specify behavior for removing the temporary directory used to store stdin input batches by giving --remove-tmp-dir=VAL. VAL can be:
# tmp-dir=VAL  [   'never'  | 0 ] : never remove the temporary directory
#              [ 'success'  | 1 ] : remove the temporary directory if 'forkrun' finishes normally. This is the DEFAULT.
#              [  'always'  | 2 ] : remove the temporary directory in all situations, even if 'forkrun' did not finish running normally
#              [ 'realtime' | 3 ] : same as [ 'always' | 2 ], but also removes the individual tmp files containing lines from stdin as they are reead and no longer needed
#                                   this lowers memory use (especially if stdin is *really* large) at the cost of increasing (wall-clock) run-time by up to ~5-10%
#
# NOTE: Flags are not case sensitive and can be given in any order, but must all be given before the "functionName" input
#
# # # # # DEPENDENCIES # # # # #
#
# if used without '-k' and with '(-j | -P) <(#>0)>': none. The code uses 100% bash builtins
# if used without '(-j | -P)' or with '(-j | -P) 0': either 'nproc' OR 'grep' + procfs to determine logical core count
# if used with '-k': 'sort' and 'cut' to reorder the output
#
# For all scenarios: either 'split' or { 'tr' and 'sed' }. 'split' is preffered.
#         If 'split' is available, it will be used in splitting the input into batches to send to the worker coprocs.
#         If 'split' is not available, a somewhat slower and less reliable splitting based on 'printf' and 'source' will be used
# 
# For all scenarios: bash 4.0 [or later]

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

    # remove tmpDir if specified
    [[ -n "${4}" ]] && [[ -d "${4]}" ]] && rm -rf "${4}"

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
trap 'exitTrap "${PID0}" "${IFS0}" "${fd_index}" "$( (( ${rmTmpDirFlag} >= 2 ))  && echo "${tmpDir}" || : )"' EXIT HUP TERM INT  

# make variables local
local -a FD_in
local -a FD_out
local -a pidA
local -a inAll
local -i nArgs
local -i nSent
local -i nSent0
local -i nSentCur
local -i splitAgainNSent
local -i nDone
local -i nProcs
local -i nBatch
local -i nBatchCur
local -i workerIndex
local fd_index
local parFunc
local IFS0
local sendNext
local splitAgainPrefix
local splitAgainFileNames
local REPLY
local PID0
local pCur
local pCur_PID
local tmpDir
local tmpDirRoot
local stdinReadFlag
local orderedOutFlag
local exportOrderFlag
local haveSplitFlag
local nullDelimiterFlag
local autoBatchFlag
local splitAgainFlag
local -i rmTmpDirFlag
local -f getNextInputFileName

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
nullDelimiterFlag=false
tmpDirRoot='/tmp'
nProcs=0
nBatch=0
rmTmpDirFlag=1
inAll=("${@}")
while [[ "${1,,}" =~ ^-+[jpkltr0\-].*$ ]]; do
    if [[ "${1,,}" =~ ^-+[jp]$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+[jp]=?[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${1#*[jpJP]}"
        nProcs="${nProcs#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+t(mp(-?dir)?)$ ]] && [[ "${2}" =~ ^.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+t(mp(-?dir)?=)=?.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${1#*[tT]}"
        tmpDirRoot="${tmpDirRoot#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+l$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+l=?[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${1#*[lL]}"
        nBatch="${nBatch#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+k$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+n$ ]]; then
        # make output include input sorting order, but dont actually re-sort it. originally used internally with -k to allow for auto output re-sorting
        exportOrderFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+0$ ]]; then
        # items in stdin are seperated by NULLS, not newlines
        nullDelimiterFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+((rm)|(remove))-?tmp(-?dir)?=(([0-3])|(never)|(success)|(always)|(realtime))$ ]]; then
        rmTmpDirFlag="${1##*=}"
        [[ "${rmTmpDirFlag}" == 'never' ]] && rmTmpDirFlag=0
        [[ "${rmTmpDirFlag}" == 'success' ]] && rmTmpDirFlag=1
        [[ "${rmTmpDirFlag}" == 'always' ]] && rmTmpDirFlag=2
        [[ "${rmTmpDirFlag}" == 'realtime' ]] && rmTmpDirFlag=3
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

# check if we are automatically setting nBatch
(( ${nBatch} == 0 )) && { nBatch=512; autoBatchFlag=true; } || autoBatchFlag=false

# return if we dont have anything to parallelize over
[[ -z ${parFunc} ]] && echo 'ERROR: NO FUNCTION SPECIFIED. ABORTING' >&2 && return 1
{ which "${parFunc}" 1>/dev/null 2>/dev/null || declare -F "${parFunc}" 2>/dev/null; } || { echo 'ERROR: THE FUNCTION SPECIFIED IS UNKNOWN / CANNOT BE FOUND. ABORTING' >&2 && return 2; }
[[ -t 0 ]] && echo 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (NOT A PIPE). ABORTING' >&2 && return 3

# if user requested ordered output, re-run the forkrun call trading flag '-k' for flag '-n',
# then sort the output and remove the ordering index. Flag '-n' causes forkrun to do 2 things: 
# a) each "result group" (fron a particular batch of nBatch input lines) is NULL seperated
# b) each result group is pre-pended with the index/order that it was recieved in from stdin.

if ${orderedOutFlag}; then
    forkrun "${inAll[@]//'-k'/'-n'}" | sort -z -n -k1 -t$'\t' | cut -z -d $'\t' -f 2-
    return
fi

# begin main function
{

# prepare temp directory to store split stdin
mkdir -p "${tmpDirRoot}"
tmpDir="$(mktemp -d -p "${tmpDirRoot%/}" -t '.forkrun.XXXXXXXXX')"
which split 1>/dev/null 2>/dev/null && haveSplitFlag=true || haveSplitFlag=false

# split up input into files, each of which contains $nBatch lines
# and define function for getting the next file name
{
if ${haveSplitFlag}; then
    # split into files, each containing a batch of $nBatch lines from stdin, using 'split'
    {
    if ${nullDelimiterFlag}; then 
        {
            split -t '\0' -d -l "${nBatch}" - "${tmpDir}"'/x' <&4  
        } 4<&5 &
    else 
        {
            split -d -l "${nBatch}" - "${tmpDir}"'/x' <&4 
        } 4<&5 &
    fi
    } 5<&6
#split -l "${nBatch}" -d - "${tmpDir}"/x </dev/stdin --verbose | wc -l &

getNextInputFileName() {
    # 'split' names the output files in a really annoying way. it goes
    # x00 --> x89 (90 vals), then x9000 --> x9899 (900 vals), then x990000 -->998999 (9000 vals), etc
    # this function transforms a simple count (0, 1, 2, 3, ...) into thew `x___` names used by split
 
    local x; 
    local x0; 
    local exp;
    local prefix;
    
    prefix="$1"
    shift 1
    
    for x0 in "$@"; do 
        x=$x0; 
        exp=1;  
        printf '%s' "${prefix}"
        while true; do
            (( x >= ( 9 * ( 10 ** exp ) )  )) && { x=$(( x - ( 9 * ( 10 ** exp ) ) )) && ((exp++)) && printf '%d' '9'; } || { printf '%0.'$(( 1 + exp ))'d\n' "$x" && break; }
        done
    done
}

else
    # split into files by using printf + sed + source.
    # use printf + sed to transform input into repeated blocks of the following form: printf '%s\n' ''' ${in1//'/'"'"'} ... ${inN//'/'"'"'} ''' > ${tmpDir}/in${kk}; ((kk++))
    # then use 'source' to execute this entire input, which will issue the commands needed to write each batch of N inputs to $tmpDir
    # Note: using ''' <...> ''' + encasing all single quotes in stdin by double quotes ('"'"') *should* prevent any of the file names from being executed as code unintentionally in normal usage, but might be exploitable. If you dont have `split` perhaps dont run forkrun as root...
    {
    source <(export IFS=$'\n' && printf 'printf '"'"'%%s'"'"' '"\'\'\'"'\n'"$(export IFS=$'\n' && printf '%%s\\n=%.0s' $(seq 1 ${nBatch}) | tr -d '=')\'\'\'"' > ${tmpDir}/x${kk}\n((kk++))\n' $(sed -E s/"'"/"'"'"'"'"'"'"'"/g </dev/stdin) ) &
    } 0<&6
getNextInputFileName() {
    # files with stdin  batches are named sensibly. Add prefix 'x' and printf it out
    local x
    printf 'x%s\n' "${@}"
}

fi
} 6<&0

# fork off $nProcs coprocs and record FDs / PIDs for them
#
# unfortunately this requires a source <(...) [or eval <...>] call to do dynamically...
# without this the coproc index "$kk" doesnt get properly applied in the loop.
# after each worker finishes its current task, it sends its index to pipe {fd_index} to recieve another task
# specifically, the coproc will recieve the file name of the file (under $tmpDir) to read to get the next batch of lines from stdin.
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
    {
    printf '%s\\t%s\\n\\0' "\${REPLY#x}" "\$(export IFS=\$'\\n' && ${parFunc} \$(<"${tmpDir}/\${REPLY}"))"
    } >&8
EOI1
else
cat<<EOI2
    { 
    export IFS=\$'\\n' && ${parFunc} \$(<"${tmpDir}/\${REPLY}")
    } >&8
EOI2
fi)
    printf '%s\\0' ${kk} >&\${fd_index}
$( (( ${rmTmpDirFlag} >= 3 )) && cat<<EOI3
rm -rf "${tmpDir}/\${REPLY}"
EOI3
)
done
} 7<&0
} 8>&9
EOI0
)
    # record PIDs and i/o pipe file descriptors in indexed arrays
    local -n pCur="p${kk}"
    FD_in[${kk}]="${pCur[1]}"
    FD_out[${kk}]="${pCur[0]}"
    local +n pCur
    local -n pCur_PID="p${kk}_PID"
    pidA[${kk}]="$pCur_PID"
    local +n pCur_PID

done



# begin parallelization loop

# set initial vlues for the loop
nSent=0
nDone=0
nSent0=0
nSentCur=0
stdinReadFlag=true
splitAgainFlag=false

# populate pipe {fd_index} with $nprocs initial indicies - 1 for each coproc
printf '%d\0' "${!FD_in[@]}" >&${fd_index}  

# get next file name to send based on nSent
if ${autoBatchFlag}; then

    if [[ -f "${tmpDir}/$(getNextInputFileName 'x' $(( $nProcs - 1 )))" ]]; then
        sendNext="x00"
        
    else
        [[ -f "${tmpDir}/x00" ]] || inotifywait "${tmpDir}/x00"
        splitAgainFlag=true
        nSentCur=0
        splitAgainPrefix='x00_x'
        splitAgainFileNames="$(for nn in $( getNextInputFileName 'x' $( seq 0 $(( ${nProcs} - 1 )) ) ); do
            [[ -f "${tmpDir}/${nn}" ]] && printf '%s\n' "${tmpDir}/${nn}" || break
        done)"
        splitAgainNSent="$(echo "${splitAgainFileNames}" | wc -l)"
        nBatchCur=$(( 1 + ( ( $(IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l) - 1 ) / ${nProcs} ) )) 
        { 
            export IFS=$'\n' && cat -s ${splitAgainFileNames}
        } | {
            if ${nullDelimiterFlag}; then
        split -l "${nBatchCur}" -t '\0' -d - "${tmpDir}/${splitAgainPrefix}"
            else
        split -l "${nBatchCur}" -d - "${tmpDir}/${splitAgainPrefix}"    
            fi
        }
        sendNext="$( getNextInputFileName "${splitAgainPrefix}" "${nSentCur}" )"
    fi
          
else
    [ -f "${tmpDir}/x00" ]] || inotifywait "${tmpDir}/x00"
    sendNext="x00"   
fi



# begin main loop. Listin on pipe {fd_index} for workers to send their unique ID, indicating they are free. 
# Respond with the file name of the file containing $nBatch lines from stdin. Repeat until all of stdin has been processed.
while ${stdinReadFlag} || (( ${nDone} < ${nArgs} )); do

    # read {fd_index} (sent by worker coprocs) to trigger sending the next input
    read -r -d '' workerIndex <&${fd_index}            
    (( ${nSent} < ${nProcs} )) || ((nDone++))

    if ${stdinReadFlag}; then
        # still distributing stdin - send next file name (containing next group of inputs) to worker coproc
        printf '%s\0' "${sendNext}" >&${FD_in[${workerIndex}]}
        ((nSent++))
        ${splitAgainFlag} && ((nSentCur++)) || ((nSent0++))

        # get next file name to send based on nSent
        if ${autoBatchFlag}; then
          
            if ${splitAgainFlag} && (( ${nSentCur} == ${nProcs} )); then
                nSentCur=''
                splitAgainPrefix=''
                splitAgainFileNames=''
                nBatchCur=''
                splitAgainFlag=false
                nSent0=$(( ${nSent0} + ${splitAgainNSent} ))
                splitAgainNSent=''
            fi
                      
            if ${splitAgainFlag}; then
                sendNext="$(getNextInputFileName "${splitAgainPrefix}" "${nSentCur}")"

            elif [[ -f "${tmpDir}/$(getNextInputFileName 'x' $(( $nSent0 + $nProcs - 1 )))" ]]; then
                sendNext="$(getNextInputFileName 'x' "${nSent0}")"
                
            elif ! [[ -f "${tmpDir}/$(getNextInputFileName 'x' "${nSent0}")" ]]; then
                stdinReadFlag=false
                nArgs=${nSent}
            
            else
                splitAgainFlag=true
                nSentCur=0
                splitAgainPrefix="$(getNextInputFileName 'x' "${nSent0}")"'_x'
                splitAgainFileNames="$(for nn in $( getNextInputFileName 'x' $( seq ${nSent0} $(( ${nSent0} + ${nProcs} - 1 )) ) ); do
                    [[ -f "${tmpDir}/${nn}" ]] && printf '%s\n' "${tmpDir}/${nn}" || break
                done)"
                splitAgainNSent="$(echo "${splitAgainFileNames}" | wc -l)"
                 nBatchCur=$(( 1 + ( ( $(IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l) - 1 ) / ${nProcs} ) )) 
                { 
                    export IFS=$'\n' && cat -s ${splitAgainFileNames}
                } | {
                    if ${nullDelimiterFlag}; then
                        split -l "${nBatchCur}" -t '\0' -d - "${tmpDir}/${splitAgainPrefix}"
                    else
                        split -l "${nBatchCur}" -d - "${tmpDir}/${splitAgainPrefix}"            
                    fi
                }

                sendNext="$( getNextInputFileName "${splitAgainPrefix}" "${nSentCur}" )"
            fi

            (( ${nSent0} >= ${nProcs} )) && autoBatchFlag=false
          
        else
          
            sendNext="$(getNextInputFileName 'x' "${nSent}")"
        
            # if there isnt another file to read then trigger stop condition
            [[ -f "${tmpDir}/${sendNext}" ]] || { 
                stdinReadFlag=false
                nArgs=${nSent}
            }
        fi
        
    else              

        # we are done reading input files containing batches of lines from stdin. as each worker coproc finishes running its last task, send it '\0' to cause it to shutdown   
        printf '\0' >&${FD_in[${workerIndex}]}
        
    fi

done


} 6<&0 9>&1

(( ${rmTmpDirFlag} >= 1 )) && [[ -n ${tmpDir} ]] && [[ -d "${tmpDir}" ]] && rm -rf "${tmpDir}"

}
