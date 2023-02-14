#!/bin/bash

forkrun() {
## Efficiently runs many tasks in parallel using coprocs
#
# USAGE: printf '%s\n' "${inArgs}" | forkrun [(-j|-p) <#>] [-l <#>] [-i] [-k] [-n] [(-z|-0)] [-t <path>] [-d (0|1|2|3)] functionName [functionInitialArgs]
# EXAMPLE:    find ./ -type f | forkrun sha256sum
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
#
# # # # # # # # # # FLAGS # # # # # # # # # #
#
# Most of the xargs functionality and much of the "standard" parallel functionality has been implemented in forkrun. Where possible, flags are the same as the analagous xargs / parallel flags.
#
# (-j|-p) <#>  Use either of these flags to specify the number of simultanious processes to use at a given time
# --procs=<#>  The default if not given is to use the number of logical cpu cores $(nproc). 
#
#   -l <#>     Use this flag to define the number of inputs to group together and pass to the worker coprocs. Sending multiple inputs at once 
# --lines=#>  typicallly is faster, though setting this higher than 512 or higher than ( # lines in stdin ) / ( # worker coprocs ) tends to make 
#              forkrun slower, not faster. Set this to 0 (or dont set it at all) to have forkrun automatically set and adjust this parameter for you (this is the DEFAULT). 
#              NOTE:  not all functions (e.g., basename) support running multiple inputs at once. To use these fuctions with forkrun you MUST call forkrun with `-l 1`. Otherwise, use the default.
#
#      -i      Use this flag to insert the argument passed via stdin in a specific spot in the function call indicated by '{}'. '{}' will be replaced with the current input wherever it appears.
#   --insert   Example: the standard forkrun usage, where the input is tacked on to the end of the function + args string, is the same as `echo inputs | forkrun -I -- func arg1 ... arg N '{}'`
#              Note: the entire group of inputs will be inserted at every {}. You may need to use `-l 1` to make this work right.
#
#      -k      Use this flag to force the output to be given in the same order as arguments were given on stdin. The "cost" of this is 
#    --keep    a) you wont get any output as the code runs - it will all come at one at the endand b) the code runs slightly slower (~10%).  This re-calls forkrun with the 
# --keep-order '-n' flag and then sorts the output. NOTE: if you use the `-k` (or `-n`) flags, the function you are parallelizing can NOT produces any NULL characters in its output.
#
#      -n      Use this flag to force the output for each input batch to get pre-pended with "<#> $'\t'", where <#> reprenents where that result's input(s) were in 
#  --number    the input queue.  This will be pre-pended once per output group, and output groups will be seperated by NULL characters, allowing the original input order
#--line-number to be recreated easily using null-delimited parsing (e.g., with 'sort -z' and 'cut -z').  This is used by the '-k' flag to re-order the output to the same order as the inputs
#
#  -t <path>   Use this flag to set the base directory where tmp files containing groups of lines from stdin will be kept. Default is '\tmp'.
# --tmp=<path> To speed up parsing stdin, forkrun splits up stdin into groups of $nBatch and saves them to [ram]disk. This path should not include whitespace characters.
#              These temp input files are then deleted according to `--remove-tmp-dir` policy set (see below). Highly reccomend that these be on a tmpfs/ramdisk.
#
#   -d <#>     Specify behavior for deleting the temporary directory used to store stdin input batches. <#> must be 0, 1, 2, or 3. These respesent:
# --delete=<#> [ 0 ] : never remove the temporary directory
#              [ 1 ] : remove the temporary directory if 'forkrun' finishes normally. This is the DEFAULT.
#              [ 2 ] : remove the temporary directory in all situations, even if 'forkrun' did not finish running normally
#              [ 3 ] : same as [ 'always' | 2 ], but also removes the individual tmp files containing lines from stdin as they are reead and no longer needed
#                      This lowers memory use (especially if stdin is *really* large) at the cost of increasing (wall-clock) run-time by ~5-10%
#
#   (-0|-z)    Assume that individual inputs passed on stdin are delimited by NULL's instead of by newlines. Note: that NULL-seperted inputs will be passed as-is to the function
#    --null    being parallelized, so ensure that it supports and expects NULL-seperated inputs, not newline seperated ones. this note does not apply if you pass forkrun `-l 1`.  
#              Notes: 1) 'split' must be available to use this flag. 2) this flag doesnt work if `-l 1` is set. 3) To avoid command substitution removing the null bytes,
#              when this flag is used the inputs will be passed to the function being parallelized via stdin, not via function inputs. i.e., this implies flag '-s'
#              
#
# (-s|--stdin) Input will be passed to the function being pasrallelized (parFunc) via stdin instead of via function arguments. Normally, forkrun passes inputs to parFunc via
#    --pipe    export IFS=$'\n' && ${parFunc} $(<filePath)  --OR--   ${parfunc} ${lineFromStdin}.      When '-s' is specified, inputs are instead passed via stdin. i.e.,
#              export IFS=$'\n' && ${parFunc} <filePath     --OR--   ${parfunc} <(echo ${lineFromStdin})
#
# (-v|--verbose) Increase verbosity. Currently, the only effect this has is that after parsing the forkrun options all the variables associated with forkrun options are printed to stderr.
#
# (-h|-?|--help) Display this help.
#
#      --      Use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'. Forkrun, by default, assumes the 1st rgument that does not begin with '-' 
#              is the function name and all remaining arguments are its initialArgs. Using '--' would allow you to parallelize a function that has a '-' as its first character.
#
#
# NOTE: Flags are NOT case sensitive and can be given in any order, but must all be given before the "functionName" input. For options that require an argument ( -[jpltd] ),
#       For short versions of flags: the ' ' can be removed or replaced with '='. e.g., to set -j|-p, the following all work: '-j' '<#>', '-p' '<#>', '-j<#>', '-p<#>, '-j=<#>', '-p=<#>' 
#       Any of the above with an upper-case (-j|-p) will work al well. However, quoting 2 inputs together with a space in between (e.g., '-j <#>') will not work.
#       For long versions of flags: either the '=' or 2 seperate arguments is required. e.g., '--lines=0' and '--lines' '0' work, but '--lines0' will NOT will work
#
#
# # # # # # # # # # DEPENDENCIES # # # # # # # # # #
#
# Where possible, forkrun uses bash builtins, making it have minimal dependencies. There are, however a handful of required external software packages.
# NOTE: Items prefaced with '(*)' require the "full" [GNU coreutils] version....The busybox version is insufficient. On items prefaced with (x) either the full or busybox version will work.
#
# # # GENERAL DEPOENDENCIES # # #
# (*) Bash 4.0+ (this is when coprocs were introduced)
# (x) which  (for determining available binaries and chjoosing which code paths to take)
#
# # # FOR ORDERED OUTPUT (-k) # # #
# (*) sort
# (*) cut
#
# # # WHEN (-j|-p) NOT GIVEN # # #
# (x) nproc --OR-- (x) grep + access to procfs (for determining number of logical CPU cores)
#
# # # FOR BATCH SIZE (-l) GREATER THAN 1 # # #
# (*) split
# (x) cat
# (x) mktemp
# (*) inotifywait --OR-- (x) sleep
#
# NOTE: if (*) split is unavailable, there is an alternate code path. This alternate path depends on: tr, seq, and (*) sed. 
#       However, it is slower and neither automatic batching (-l=0) nor NULL-seperated input processing (-0|-z) will work.

# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #

# enable job control
set -m

# set exit trap to clean up
exitTrap() {

    # restore IFS
    export IFS="${IFS0}"

    # remove tmpDir if specified
    (( ${rmTmpDirFlag} >= 2 )) && [[ -d "${tmpDir}" ]] && rm -rf "${tmpDir}"

    # shutdown all coprocs
    for FD in "${FD_in[@]}"; do
        [[ -e /proc/"${PID0}"/fd/${FD} ]] && printf '\0' >&${FD}
    done
 
    # kill all background jobs
    jobs -rp | xargs -r kill

    # close pipes
    [[ -e /proc/"${PID0}"/fd/"${fd_index}" ]] && exec {fd_index}>&- || :

    # unset traps
    trap - EXIT HUP TERM INT QUIT

    return
}
trap 'exitTrap; return' EXIT HUP TERM INT QUIT

# make variables local
local -a FD_in
#local -a FD_out
#local -a pidA
local -a inAll
local -i nArgs
local -i nSent
local -i nSent0
local -i nSentCur
local -i splitAgainNSent
local -i nDone
local -i nFinal
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
local REPLYstr
local PID0
#local pCur
#local pCur_PID
local tmpDir
local tmpDirRoot
local stdinReadFlag
local orderedOutFlag
local exportOrderFlag
local haveSplitFlag
local nullDelimiterFlag
local autoBatchFlag
local splitAgainFlag
local substituteStringFlag
local batchFlag
local pipeFlag
local verboseFlag
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
substituteStringFlag=false
pipeFlag=false
verboseFlag=false
tmpDirRoot='/tmp'
nProcs=0
nBatch=0
rmTmpDirFlag=1
inAll=("${@}")
while [[ "${1,,}" =~ ^-+.+$ ]]; do
    if [[ "${1,,}" =~ ^-+((j)|(p(rocs)?))$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+((j)|(p(rocs)?))=?[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${1#*[jpJP]}"
        nProcs="${nProcs#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+l(ines)?$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+l(ines)?=?[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${1#*[lL]}"
        nBatch="${nBatch#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+i(nsert)?$ ]]; then
        # specify location to insert inputs with {} 
        substituteStringFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+k(eep(-?order)?)?$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+n(umber(-?lines)?)?$ ]]; then
        # make output include input sorting order, but dont actually re-sort it. 
        # used internally with -k to allow for auto output re-sorting
        exportOrderFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+(([0z])|(null))$ ]]; then
        # items in stdin are seperated by NULLS, not newlines
        nullDelimiterFlag=true
        pipeFlag=true
        shift 1      
    elif [[ "${1,,}" =~ ^-+((s(tdin)?)|(pipe))$ ]]; then
        # items in stdin are seperated by NULLS, not newlines
        pipeFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+t(mp)?$ ]] && [[ "${2}" =~ ^.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+t(mp)?=?.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${1#*[tT]}"
        tmpDirRoot="${tmpDirRoot#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+d(elete)?$ ]] && [[ "${2}" =~ ^[0-3]$ ]]; then
        # set policy to remove temp files containing data from stdin
         rmTmpDirFlag="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+d(elete)?=?[0-3]$ ]]; then
        # set policy to remove temp files containing data from stdin
        rmTmpDirFlag="${1#**[dD]}"
        rmTmpDirFlag="${1#*=}"
        shift 1    
    elif [[ "${1,,}" =~ ^-+[\?h](elp)?$ ]]; then
        # display help
        local helpText
        helpText="$(<"${BASH_SOURCE[0]}")"
        printf '%s\n' "${helpText%%'# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #'*}"
        return    
    elif [[ "${1,,}" =~ ^-+v(erbose)?$ ]]; then
        # increase verbosity
        verboseFlag=true
        shift 1
    elif [[ "${1}" == '--' ]]; then
        # stop processing forkrun options
        shift 1
        break
    else
        # ignore unrecognized input
        printf '%s\n' "WARNING: INPUT '${1}' NOT RECOGNIZED AS A FORKRUN OPTION. IGNORING THIS INPUT." >&2
        shift 1
    fi
done
# all remaining inputs are functionName / initialArgs
${substituteStringFlag} && parFunc="$(printf '%s ' "${@}")" || parFunc="$(printf '%s ' "${@}" '{}')" 

# default nProcs is # logical cpu cores
(( ${nProcs} == 0 )) && nProcs=$(which nproc 2>/dev/null 1>/dev/null && nproc || grep -cE '^processor.*: ' /proc/cpuinfo)

# check if we are automatically setting nBatch
(( ${nBatch} == 0 )) && { nBatch=512; autoBatchFlag=true; } || autoBatchFlag=false
(( ${nBatch} == 1 )) && { batchFlag=false; rmTmpDirFlag=0; nullDelimiterFlag=false; } || batchFlag=true

# check if we have split
which split 1>/dev/null 2>/dev/null && haveSplitFlag=true || haveSplitFlag=false
${haveSplitFlag} || { autoBatchFlag=false; nullDelimiterFlag=false; }

# check that we dont have both -n and -k. If so, -k supercedes -n
if ${orderedOutFlag} && ${exportOrderFlag}; then
    exportOrderFlag=false
    printf '%s\n' "WARNING: BOTH '-k' and '-n' FLAGS WERE PASSED TO FORKRUN. THESE FLAGS ARE MUTUALLY EXCLUSIVE." "'-k' SUPERCEDES '-n'. IGNORING '-n' FLAG." >&2
fi

# return if we dont have anything to parallelize over
[[ -z ${parFunc%% *} ]] && printf '%s\n' 'NOTICE: NO FUNCTION SPECIFIED. COMMANDS PASSED ON STDIN WILL BE DIRECTLY EXECUTED.' >&2 || { which "${parFunc%% *}" 1>/dev/null 2>/dev/null || declare -F "${parFunc}" 2>/dev/null; } || { printf '%s\n' 'ERROR: THE FUNCTION SPECIFIED IS UNKNOWN / CANNOT BE FOUND. ABORTING' 'FUNCTION SPECIFIED: '"${parFunc}" >&2 && return 1; }
[[ -t 0 ]] && printf '%s\n' 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (NOT A PIPE). ABORTING' >&2 && return 2

# if user requested ordered output, re-run the forkrun call trading flag '-k' for flag '-n',
# then sort the output and remove the ordering index. Flag '-n' causes forkrun to do 2 things: 
# a) each "result group" (fron a particular batch of nBatch input lines) is NULL seperated
# b) each result group is pre-pended with the index/order that it was recieved in from stdin.
if ${orderedOutFlag}; then
    forkrun "${inAll[@]//'-k'/'-n'}" | sort -z -n -k1 -t$'\t' | cut -z -d $'\t' -f 2-
    return
fi

# incorporate string to get input into the function string
${substituteStringFlag} && ! [[ "${parFunc}" == *{}* ]] && substituteStringFlag=false && printf '%s\n' "WARNING: {} NOT FOUND IN FUNCTION STRING OR ARGS. TURNING OFF '-i' FLAG" &&  parFunc="$(printf '%s ' "${@}" '{}')" 

# if verboseFlag is set, print theparameters we just parsed to srderr
${verboseFlag} && {
printf '%s\n' '' "DONE PARSING INPUTS! Selected forkrun options:" ''
printf '%s\n' "parFunc = ${parFunc}" "nProcs = ${nProcs}" "nBatch = ${nBatch}" "parFunc = ${parFunc}" "tmpDir = ${tmpDir}" "rmTmpDirFlag = ${rmTmpDirFlag}"
${orderedOutFlag} && printf '%s\n' "orderedOutFlag = true" || printf '%s\n' "orderedOutFlag = false"
${exportOrderFlag} && printf '%s\n' "exportOrderFlag = true" || printf '%s\n' "exportOrderFlag = false"
${haveSplitFlag} && printf '%s\n' "haveSplitFlag = true" || printf '%s\n' "haveSplitFlag = false"
${nullDelimiterFlag} && printf '%s\n' "nullDelimiterFlag = true" || printf '%s\n' "nullDelimiterFlag = false"
${autoBatchFlag} && printf '%s\n' "autoBatchFlag = true" || printf '%s\n' "autoBatchFlag = false"
${substituteStringFlag} && printf '%s\n' "substituteStringFlag = true" || printf '%s\n' "substituteStringFlag = false"
${batchFlag} && printf '%s\n' "batchFlag = true" || printf '%s\n' "batchFlag = false"
${pipeFlag} && printf '%s\n' "pipeFlag = true" || printf '%s\n' "pipeFlag = false"
${veboseFlag} && printf '%s\n' "veboseFlag = true" || printf '%s\n' "veboseFlag = false"
printf '\n'
} >&2

# # # # # BEGIN MAIN FUNCTION # # # # #
{

# if (( nBatch > 1 )) then split up input into files undert $tmpDir, each of which contains $nBatch lines and define a function for getting the next file name
${batchFlag} && {

# prepare temp directory to store split stdin
mkdir -p "${tmpDirRoot}"
tmpDir="$(mktemp -d -p "${tmpDirRoot%/}" -t '.forkrun.XXXXXXXXX')"

if ${haveSplitFlag}; then
    # split into files, each containing a batch of $nBatch lines from stdin, using 'split'
    {
    if ${nullDelimiterFlag}; then 
        {
            # split NULL-seperated stdin
            split -t '\0' -d -l "${nBatch}" - "${tmpDir}"'/x' <&4  
        } 4<&5 &
    else 
        {
            # split newline-seperated stdin
            split -d -l "${nBatch}" - "${tmpDir}"'/x' <&4 
        } 4<&5 &
    fi
    } 5<&6

getNextInputFileName() {
    # 'split' names the output files in a somewhat annoying way (to try and ensure output will always sort correctly). it goes (with '-d' flag):
    # x00 --> x89 (90 vals), then x9000 --> x9899 (900 vals), then x990000 -->998999 (9000 vals), etc
    # this function transforms a simple count (0, 1, 2, 3, ...) into the `x___` names used by split
 
    local x; 
    local x0; 
    local exp;
    local prefix;
    
    prefix="${1}"
    shift 1
    
    for x0 in "${@}"; do 
        x=${x0}; 
        exp=1;  
        printf '%s' "${prefix}"
        while true; do
            (( ${x} >= ( 9 * ( 10 ** ${exp} ) )  )) && { x=$(( ${x} - ( 9 * ( 10 ** ${exp} ) ) )) && ((exp++)) && printf '%d' '9'; } || { printf '%0.'$(( 1 + ${exp} ))'d\n' "${x}" && break; }
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

# set a a string for how we will pass inputs to the function we are parallelizing. This string will be used in the coproc code that is generated and sourced below
if ${batchFlag}; then
    # REPLY is file name in $tmpDir containing lines from stdin. cat the file using $(<file)
    if ${pipeFlag}; then 
        REPLYstr='<"'"${tmpDir}"'/${REPLY}"'
    else        
        REPLYstr='$(<"'"${tmpDir}"'/${REPLY}")'
    fi
else
    # not using batching --> REPLY is a line from stdin
    if ${exportOrderFlag}; then
        # REPLY has been pre-pended with input order index. Remove it
        REPLYstr='${REPLY#*$'"'"'\t'"'"'}'
    else
        # REPLY contains just a line from stdin. Use it as-is
        REPLYstr='${REPLY}'
    fi
    ${pipeFlag} && REPLYstr='<(printf '%s' '"${REPLYstr}"')'
fi

parFunc="${parFunc//'{}'/"${REPLYstr}"}"


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

# generate source code (to be sourced) for coproc workers
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
        printf '%s\\t%s\\n\\0' "\${REPLY$( (( ${nBatch} == 1 )) && printf '%s' '%%$'"'"'\t'"'"'*' || printf '%s' '#x' )}" "\$(export IFS=\$'\\n' && ${parFunc})"
    } >&8
EOI1
else
cat<<EOI2
    { 
        export IFS=\$'\\n' && ${parFunc}
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
FD_in[${kk}]="\${p${kk}[1]}"
EOI0
)
    # record PIDs and i/o pipe file descriptors in indexed arrays (OLD)
    #local -n pCur="p${kk}"
    #FD_in[${kk}]="${pCur[1]}"
    #FD_out[${kk}]="${pCur[0]}"
    #local +n pCur
    #local -n pCur_PID="p${kk}_PID"
    #pidA[${kk}]="$pCur_PID"
    #local +n pCur_PID

done

# begin parallelization loop

# set initial vlues for the loop
nSent=0
nDone=0
nSent0=0
nSentCur=0
nFinal=${nProcs}
stdinReadFlag=true
splitAgainFlag=false

# populate pipe {fd_index} with $nprocs initial indicies - 1 for each coproc
printf '%d\0' "${!FD_in[@]}" >&${fd_index}  

# get next file name to send based on nSent
if ${autoBatchFlag}; then
    # when forkrun starts: automatically re-split available input files into $nProcs equal files if there arent enough to fully saturate $nProcs coprocs with 1+ round of $nBatch inputs

    if [[ -f "${tmpDir}/$(getNextInputFileName 'x' $(( ${nProcs} - 1 )))" ]]; then
        # Check if there are $nProcs not-yet-read stdin files generated by split available. 
        # If so then we have at least enough inputs to do 1+ set of $nBatch inputs on each coproc worker, 
        # so we dont need to adjust nBatch anymore --> turn off autoBatchFlag
        sendNext="x00"
        autoBatchFlag=false
        
    else
        # we dont (yet) have $nProcs files containing stdin ready to go. This indicates either we dont have that many inputs, or they are comming in on stdin slowly.
        # take the inputs we do already have saved in files and re-split them into $nProcs new files. A flag gets set to indicate we must deal with these before going back to normal operation.

        # ensure we have at least the 1st file (x00) before continuing
        [[ -f "${tmpDir}/x00" ]] || {
            which inotifywait 1>/dev/null 2>/dev/null && inotifywait "${tmpDir}/x00" || until [[ -f "${tmpDir}/x00" ]]; do sleep 0.0001s; done
        }

        # set flag and initial [aramaters for dealing with the re-split files
        splitAgainFlag=true
        nSentCur=0
        splitAgainPrefix='x00_x'

        # determine how many files we actually have available. Should be somewhere between 1 and $(( $nProcs - 1 ))
        splitAgainFileNames="$(for nn in $(getNextInputFileName 'x' $(seq 0 $(( ${nProcs} - 1 )))); do
            [[ -f "${tmpDir}/${nn}" ]] && printf '%s\n' "${tmpDir}/${nn}" || break
        done)"

        # record how many files we will be re-combining and re-splitting to figure out how many lines to put in each resplit file to split them evenly.
        splitAgainNSent="$(printf '%s\n' "${splitAgainFileNames}" | wc -l)"
        nBatchCur=$(( 1 + ( ( $(IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l) - 1 ) / ${nProcs} ) )) 

        # recombine (with cat -s to suppress long series of blanks) and then re-split into files with equal number of lines
        { 
            export IFS=$'\n' && cat -s ${splitAgainFileNames}
        } | {
            if ${nullDelimiterFlag}; then
                # split NULL-seperated
        split -l "${nBatchCur}" -t '\0' -d - "${tmpDir}/${splitAgainPrefix}"
            else
                # split newline-seperated
        split -l "${nBatchCur}" -d - "${tmpDir}/${splitAgainPrefix}"    
            fi
        }
        sendNext="$(getNextInputFileName "${splitAgainPrefix}" "${nSentCur}")"
    fi
          
elif ${batchFlag}; then
    # using batching but not re-splitting. wait for 1st file (x00) to appear then continue
    [[ -f "${tmpDir}/x00" ]] || {
        which inotifywait 1>/dev/null 2>/dev/null && inotifywait "${tmpDir}/x00" || until [[ -f "${tmpDir}/x00" ]]; do sleep 0.0001s; done
    }
    sendNext="x00"   

else
    # not using batching. reasd 1 line from stdion and store it
    read -r sendNext
    [[ -n "${sendNext}" ]] || { printf '%s\n' 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (EMPTY PIPE). ABORTING' >&2 && return 3; }
fi


# begin main loop. Listin on pipe {fd_index} for workers to send their unique ID, indicating they are free. 
# Respond with the file name of the file containing $nBatch lines from stdin. Repeat until all of stdin has been processed.
while ${stdinReadFlag} || { (( ${nFinal} > 0 )) && (( ${nDone} < ${nArgs} )); }; do

    # read {fd_index} (sent by worker coprocs) to trigger sending the next input
    read -r -d '' workerIndex <&${fd_index}            
    (( ${nSent} < ${nProcs} )) || ((nDone++))

    if ${stdinReadFlag}; then
        # still distributing stdin - send next file name (containing next group of inputs) to worker coproc

        if ${batchFlag}; then
            # using batching. Deal with file names in $tmpDir
            
            # send filename to worker and iterate counters
            printf '%s\0' "${sendNext}" >&${FD_in[${workerIndex}]}
            ((nSent++))
            ${splitAgainFlag} && ((nSentCur++)) || ((nSent0++))
    
            # get next file name to send based on nSent
            if ${autoBatchFlag}; then
              
                if ${splitAgainFlag} && (( ${nSentCur} == ${nProcs} )); then
                    # we just sent to last file from a re-split group. Turn off splitAgainFlag, clear splitAgain parameters
                    # and advance nSent0 by number of files that originally went in to the resplit d
                    nSentCur=0
                    splitAgainPrefix=''
                    splitAgainFileNames=''
                    nBatchCur=0
                    splitAgainFlag=false
                    nSent0=$(( ${nSent0} + ${splitAgainNSent} ))
                    splitAgainNSent=0
                fi
                          
                if ${splitAgainFlag}; then
                    # we are still working through the current set of re-split files. next file name is in re-split file group
                    sendNext="$(getNextInputFileName "${splitAgainPrefix}" "${nSentCur}")"
    
                elif [[ -f "${tmpDir}/$(getNextInputFileName 'x' $(( ${nSent0} + ${nProcs} - 1 )))" ]]; then
                    # Check if there are $nProcs not-yet-read stdin files generated by split available. 
                    # If so then we have at least enough inputs to do 1+ set of $nBatch inputs on each coproc worker, 
                    # so we dont need to adjust nBatch anymore --> turn off autoBatchFlag
                    sendNext="$(getNextInputFileName 'x' "${nSent0}")"
                    autoBatchFlag=false
                    
                elif ! [[ -f "${tmpDir}/$(getNextInputFileName 'x' "${nSent0}")" ]]; then
                    # the next file with stdin lines doesnt exist. trigger stop condition
                    stdinReadFlag=false
                    nArgs=${nSent}
                
                else
                    # we have >1 but <$nProcs available files with lines from stdin under $tmpDir. Re-split them into $nProcs files.
                    # set flag and initial [aramaters for dealing with the re-split files
        
                    splitAgainFlag=true
                    nSentCur=0

                    # determine how many files we actually have available. Should be somewhere between 1 and $(( $nProcs - 1 ))
                    splitAgainPrefix="$(getNextInputFileName 'x' "${nSent0}")"'_x'
                    splitAgainFileNames="$(for nn in $(getNextInputFileName 'x' $(seq ${nSent0} $(( ${nSent0} + ${nProcs} - 1 )))); do
                        [[ -f "${tmpDir}/${nn}" ]] && printf '%s\n' "${tmpDir}/${nn}" || break
                    done)"

                    # record how many files we will be re-combining and re-splitting to figure out how many lines to put iun each resplit file to split them evenly.
                    splitAgainNSent="$(printf '%s\n' "${splitAgainFileNames}" | wc -l)"
                    nBatchCur=$(( 1 + ( ( $(IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l) - 1 ) / ${nProcs} ) )) 

                    # recombine (with cat -s to suppress long series of blanks) and then re-split into files with equal number of lines
                    { 
                        export IFS=$'\n' && cat -s ${splitAgainFileNames}
                    } | {
                        if ${nullDelimiterFlag}; then
                            # split NULL-seperated
                            split -l "${nBatchCur}" -t '\0' -d - "${tmpDir}/${splitAgainPrefix}"
                        else
                            # split newline-seperated
                            split -l "${nBatchCur}" -d - "${tmpDir}/${splitAgainPrefix}"            
                        fi
                    }
    
                    sendNext="$(getNextInputFileName "${splitAgainPrefix}" "${nSentCur}")"
                fi
    
            else
                # dont check how many files we have since we arent re-splitting. Just get the next file name to send.
                sendNext="$(getNextInputFileName 'x' "${nSent}")"

            fi
                        
            # if there isnt another file to read then trigger stop condition
            [[ -f "${tmpDir}/${sendNext}" ]] || { 
                stdinReadFlag=false
                nArgs=${nSent}
            }
           
        else 
            # not using batching. send lines from stdin. pre-pend $nSent (which gives input ordering) if exportOrderFLag is set
            
            if ${exportOrderFlag}; then
                # sorting output. pre-pend data sent with index describing position in input list
                printf '%d\t%s\0' "${nSent}" "${sendNext}" >&${FD_in[${workerIndex}]}

            else
                # not sorting output. Just send input lines as-is
                printf '%s\0' "${sendNext}" >&${FD_in[${workerIndex}]}
            fi
            ((nSent++))
			
			# read next line from stdin to send. If read fails or is empty trigger stop contition
            read -r -u 6 sendNext && [[ -n ${sendNext} ]] || { 
                nArgs=${nSent}; 
                stdinReadFlag=false; 
            }

        fi
        
    else              
        (( ${nSent} < ${nProcs} )) && ((nDone++))
        ((nFinal--))
		
        # we are done reading input files containing batches of lines from stdin. as each worker coproc finishes running its last task, send it '\0' to cause it to shutdown   
        printf '\0' >&${FD_in[${workerIndex}]}
        
    fi

done


} 6<&0 9>&1

# remove tmpDir, unless (( rmTmpDirFlag == 0 ))
if (( ${rmTmpDirFlag} >= 1 )); then
    [[ -n ${tmpDir} ]] && [[ -d "${tmpDir}" ]] && rm -rf "${tmpDir}"
elif ${batchFlag}; then
    printf 's\n' '' "TEMP DIR CONTAINING INPUTS HAS NOT BEEN REMOVED" "PATH: ${tmpDir}" '' >&2
fi
}
