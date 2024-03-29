#!/bin/bash 

forkrun() {
## Efficiently parallelize a loop / run many tasks in parallel using bash coprocs
#
# USAGE:   printf '%s\n' "${args}" | forkrun [flags] [--] parFunc [args0]
# 
# RESULT:  forkrun will run `$parFunc $args0 ${individual line from $args) in parallel for each line in $args
#
# EXAMPLE: find ./ -type f | forkrun sha256sum
#
# Usage:   Usage is vitruallu identical as running a loop in parallel using xargs -P or  parallel (using stdin):
#          source this file, then pass inputs to parallelize over on stdin and pass function name and initial arguments as function inputs.
#
# HOW IT WORKS: For each simultanious process requested, a coproc is forked off. Data are then piped in/out of these coprocs.
# Importantly, this means that you dont need to fork anything after the initial coprocs are set up...the same coprocs are piped new data instead.
# This makes this parallelization method MUCH faster than forking (for tasks with many short/quick tasks and on x86_64 machines
# with many cores speedup can be >100x). In my testing / on my hardware it is also faster than both 'xargs -P' and 'parallel -m'
#
# NO FUNCTION MODE: forkrun supports an additional mode of operation where "parFunc" and "args0" are not given as function inputs, but instead are integrated into each line of "$args".
#                   In this mode, each line passed on stin will be run as-is (by saving groups of 512 lines to tmp files and then sourcing them). This allows you to easily run multiple 
#                   different functions in paralel and still utalize forkrun's very quick and efficient parallelization method. This mode has a few limitations/considerations:
#                       1. The following flags are not supported and, if given, will be ignored: '-i', '-id', '-s' and '-l 1'
#                       2. Lines from stdin will be "space-split" when run. Typically, forkrun splits stdin on newlines (or nulls, if -0z flag is given), allowing (for example)
#                          paths that include a space (' ') character to work without needing any quoting. in "no function" mode however, the function and initial args are included in 
#                          each line on stdin, so they must be space-split to run. Solution is to either quote things containing spaces or easpace the space characters ('\ '). Example:
#
#                   printf '%s\n' 'sha256sum "/some/path/with space character"' 'sha512sum "/some/other/path/with space characters"' | forkrun
#
# DEBUG MODE: pass 'DEBUG=<FLAGS>' before forkrun to run forkrun with `set <FLAGS>`. example: `find ./ -type f | DEBUG='-xv' forkrun` will run forkrun with `set -xv` set.
#
# # # # # # # # # # FLAGS # # # # # # # # # #
#
# Most of the xargs functionality and much of the "standard" parallel functionality (including some functionality not present in xargs) 
# has been implemented in forkrun. Where possible, flags are the same as the analagous xargs / parallel flags, or as "common" shell flags.
#
# (-j|-p) <#>  Num Cores. Use either of these flags to specify the number of simultanious processes to use at a given time. The DEFAULT is to use the number of logical cpu cores
# --procs=<#>  (requires either `nproc` or grep + access to procfs). If logic core count can not be determined, the DEFAULT is 8.
#
#    -l <#>    Num lines (from stdin) per function call. Use this flag to define the number of inputs to group together and pass to the worker coprocs.
# --lines=#>   Sending multiple inputs at once typicallly is faster, though setting this higher than 512 or higher than ( # lines in stdin ) / ( # worker coprocs )
#              tends to make forkrun slower, not faster. Set this to 0 (or dont set it at all) to have forkrun automatically set and adjust this parameter for you (DEFAULT). 
#              NOTE:  not all functions (e.g., basename) support running multiple inputs at once. To use these fuctions with forkrun you MUST call forkrun with `-l 1`. Otherwise, use the default.
#
#      -i      Substitute {}. Use this flag to insert the argument passed via stdin in a specific spot in the function call indicated by '{}'. '{}' will be replaced with the current input anywhere it appears.
#   --insert   Example: the standard forkrun usage, where the input is tacked on to the end of the function + args string, is roughly the same as `echo inputs | forkrun -I -- func arg1 ... arg N '{}'`
#              Note: the entire group of inputs will be inserted at every {}. Depending on your specific usage, you may need to use `-l 1` to make this work right.
#
#     -id      Substitute {id}. In addition to what flag `'-i' does (replacing {} with stdin), if '{ID}' is present in the fuction's "$args0" (given as forkrun function inputs),
# --insert-id  it will be substituted for the unique ID of the coproc worker that is currently running. This is similiar to xargs' `--process-slot-var` option.
#              The original intent of this flag is (when combined with the '-u' flag) to allow one to send each coproc worker's output to different places. 
#              EXAMPLE:  seq 1 1000 | forkrun -id -u -- printf '%s\n' {}  '>>.out.{ID}'      (note: flag '-i' is implied and automatically set by flag '-id')
#
#     -u       Unescape quoted redirects, pipes, and logical comparrisons. forkrun typically runs the initial function arguments ($args0) through `printf '%q'` prior to embedding them into the coprocs. 
#  --unescape  This results in quoted pipes ('|'), redirects ('>', '>>') and logical comparrisons ('&&', '||') being escaped and treated as literal characters. Passing forkrun the '-u' flag
#              makes forkrun unescape any '|', '>' or '&&' characters (which also unescapes '||' and '>>', but not '&'). This allows one to make the coprocs run (and parallelize), for example, piped commands. 
#              EXAMPLE:  seq 1 1000 | forkrun -id -u -- printf '%s\n' {}  '>>.out.{ID}'
#
#      -k      Sorted output. Use this flag to force the output to be given in the same order as arguments were given on stdin. The "cost" of this is that a) you wont get 
#    --keep    any output as the code runs - it will all come at one at the end; and b) the code runs slightly slower (typically 5-10%).  Behavior varies based on the -l flag 
# --keep-order -l>1 (default): This will overwrite the split-generated files containing stdin with what will be stdout. forkrun then cat's these all after everything is done running.
#              -l=1: This re-calls forkrun with the '-n' flag and then sorts the output. NOTE: SORTING MAY NOT ALWAYS BE CORRECT (and the function you are parallelizing can NOT produces any NULL characters) WHEN -L == 1. use flag '-ks' with '-l=1' if this is unacceptable. 
#
#    -ks       Use flag '-ks' or '--keep-order-strict' to force correct ordering in the case where -l=1 at the expense of slower run time. With MANY lines input of stdin slowdown may be considerable. NOTE: if -l>1 then '-ks' is identical to '-k'.
#
#      -n      Output with ordering info. Use this flag to force the output for each input batch to get pre-pended with "$'\034'<#>$'\034'", where <#> reprenents where that result's input(s) were in 
#  --number    the input queue. Note: $'\034' is the ASCII field seperator. This will be pre-pended once per output group, and output groups will be seperated by NULL characters, allowing the original  
#--line-number input order to be recreated easily using null-delimited parsing (e.g., with 'sort -z' and 'cut -z').  This is used by the '-k' flag (when -l=1) to re-order the output to the same order as the inputs
#
#  -t <path>   Set tmpdir root. Use this flag to set the base directory where tmp files containing groups of lines from stdin will be kept. Default is '\tmp'.
# --tmp=<path> To speed up parsing stdin, forkrun splits up stdin into groups of $nBatch and saves them to [ram]disk. This path should not include whitespace characters.
#              These temp input files are then deleted according to `--remove-tmp-dir` policy set (see below). Highly reccomend that this dir be on a tmpfs/ramdisk.
#
#   -d <#>     Set tmpdir deletion behavior. Specify behavior for deleting the temporary directory used to store stdin input batches. <#> must be 0, 1, 2, or 3. These respesent:
# --delete=<#> [ 0 ] : Never remove the temporary directory
#              [ 1 ] : Remove the temporary directory if 'forkrun' finishes normally. This is normally the DEFAULT.
#              [ 2 ] : Remove the temporary directory in all situations, even if 'forkrun' did not finish running normally.
#              [ 3 ] : Same as [ 'always' | 2 ], but also removes the individual tmp files containing lines from stdin as they are reead and no longer needed.
#                      This lowers memory use (especially if stdin is *really* large) at the cost of increasing (wall-clock) run-time by ~5-10%.
#                      This is the DEFAULT if forkrun is able to detect that the system has (in total) less than 8 gb of memory/RAM.
#              NOTE: when -l>1 and -k flags are given, the split-generated input files are overwritten by the output (which is cat-ed after everything else finishes). In this situation, the original inputs will always be lost
#                    and the -d flag contorls whether of not the output text (saves in files) is deleted. Also, in this case -d 3 cannot be specified / will be ignored.
#
#     -w       Wait for slow stdin. wait indefinately for the files generated by split (containing lines from stdin) to appear in $tmpDir. Normally, forkrun will wait ~5-10 seconds (up to 4096 `sleep 0.001s` calls)
#   --wait     for `split` to output its first file. This is done to avoid a situation where there is an error somewhere in the pipe feeding forkrun (perhaps die to a typo), which causes forkrun
#              to stall and become unresponsive while waiting for input on stdin. However, if the pipe feeding forkrun is giving data slowly and during this period has not provided 512 inputs (or EOF)
#              to split this could cause forkrun to exit prematurely. give the `-w` flag to prevent this and have forkrun wait indefinately for the 1st split file. Note: has no effect if `-l=1`
#
#   (-0|-z)    Null seperated stdin. Assume that individual inputs passed on stdin are delimited by NULL's instead of by newlines. Note: that NULL-seperted inputs will be passed as-is to the function
#   --null     being parallelized, so ensure that it supports and expects NULL-seperated inputs, not newline seperated ones. this note does not apply if you pass forkrun `-l 1`.  
#              Notes: 1) 'split' must be available to use this flag. 2) this flag doesnt work if `-l 1` is set. 3) To avoid command substitution removing the null bytes,
#              when this flag is used the inputs will be passed to the function being parallelized via stdin, not via function inputs. i.e., this implies flag '-s'
#              
#
# (-s|--stdin) Pipe inputs to parFunc stdin. Input will be passed to the function being parallelized (parFunc) via stdin instead of via function arguments. Normally, forkrun passes inputs to parFunc via
#    --pipe    export IFS=$'\n' && ${parFunc} $(<filePath)  --OR--   ${parFunc} ${lineFromStdin}.      When '-s' is specified, inputs are instead passed via stdin. i.e.,
#              export IFS=$'\n' && ${parFunc} <filePath     --OR--   ${parFunc} <(echo ${lineFromStdin})
#
# (-v|--verbose) Increase verbosity. Currently, the only effect this has is that after parsing the forkrun options all the variables associated with forkrun options are printed to stderr.
#
# (-h|-?|--help) Display this help.
#
#      --      Denote last forkrun option. Use this flag to indicate that all remaining arguments are the 'functionName' and 'initialArgs'. Forkrun, by default, assumes "parFunc" is the 1st argument that
#               does not begin with '-' is the function name and all remaining arguments are its initialArgs. Using '--' would allow you to parallelize a function that has a '-' as its first character.
#
#
# NOTES: Flags must be given seperately ('-i' '-s', not '-is'). Flags are NOT case sensitive and can be given in any order, but must all be given before the "functionName" input. 
#        For options that require an argument ( -[jpltd] ): in "short" versionsm, the ' ' can be removed or replaced with '='. e.g., to set -j|-p, the following all work: '-j' '<#>', '-p' '<#>', '-j<#>', '-p<#>, '-j=<#>', '-p=<#>' 
#        Any of the above with an upper-case flag (-J|-P) will work as well. However, quoting 2 inputs/flags together with a space in between (e.g., '-j <#>') will NOT work.
#        For long versions of flags: either the '=' or 2 seperate arguments is required. e.g., '--lines=0' and '--lines' '0' work, but '--lines0' will NOT will work (even though '-L0' works)
#
#
# # # # # # # # # # DEPENDENCIES # # # # # # # # # #
#
# Where possible, forkrun uses bash builtins, making it have minimal dependencies. There are, however a handful of required external software packages.
# NOTE: Items prefaced with '(*)' require the "full" [GNU coreutils] version....The busybox version is insufficient. On items prefaced with (x) either the full or busybox version will work.
#
# FOR ALL FUNCTIONALITY: bash 4.0 (or later) 
#    full (gnu coreutil) versions of: split, sort and cut 
#    full or busybox versions of:     which, wc, cat, mktemp, sleep, (nproc|grep)
#
# # # GENERAL DEPENDENCIES # # #
# (*) Bash 4.0+ (this is when coprocs were introduced)
# (x) wc
#
# # # FOR BATCH SIZE (-l) GREATER THAN 1 # # #
# (*) split
# (x) cat
# (x) mktemp
# (x) sleep
#
# # # FOR ORDERED OUTPUT (-k) (ONLY WHEN BATCH SIZE (-l) EQUALS 1) # # #
# (*) sort
# (*) cut
#
# # # FOR DETERMINING LOGICAL CORE COUNT # # #
# (x) nproc --OR-- (x) grep + access to procfs (also for determining total system memory)
# 
#
# # # # # # # # # # KNOWN ISSUES / BUGS / UNEXPECTED BEHAVIOR # # # # # # # # # #
#
# ISSUE: when running <...> | fokrun echo, forkrun does not produce output like what `seq 1 12` would give (1 value per line). Instead, you will get something like:
#        1 2 3 4 
#        5 6 7 8 
#        9 10 11 12
#
# CAUSE: `echo` seemingly does not respect IFS=$'\n': setting IFS=$'\n' and giving it a newline-seperated list of things to echo
#        results in everything on the same line and space seperated (instead of everything newline-seperated on its own line)
#
# WORKAROUND: use <...> | forkrun printf '%s\n' 
#
# 
# ISSUE: in some situations, using the '-k' flag n combination with the '-l=1' flag *may* result in sorting not being correct
#
# CAUSE: I believe this is due to things getting send to stdout at the *exact* same time and getting the indexes jumbled up
#
# WORKAROUND: instead of flag '-k' ('--keep-order') use flag '-ks' ('--keep-order-strict'). This will force 100% correct ordering at the expense of speed
#

######################################################
# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #
######################################################


##########################################################################################################
# # # # # # # # # # SECTION 1 -- DEFINE: LOCAL VARIABLES, SET OPTIONS, EXIT TRAPS, ... # # # # # # # # # #
##########################################################################################################

# enable job control
set -m
[[ -n ${DEBUG} ]] && set "${DEBUG}"

# enable extglob
shopt -s extglob

# set exit trap to clean up
trap 'exitTrap; return' EXIT HUP TERM QUIT 

# enable line-by-line time profiling
# timeProfileFlag=true
#[[ -n ${timeProfileFlag} ]] && ${timeProfileFlag} && { [[ -f /usr/local/bin/addTimeProfile ]] || source <(curl https://raw.githubusercontent.com/jkool702/timeprofile/main/setup.bash); } && source /usr/local/bin/addTimeProfile

# define exitTrap
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
    jobs -rp | while read -r pidK; do
        kill "${pidK}" 2>/dev/null
    done

    # close pipes
    ! [[ -e /proc/"${PID0}"/fd/"${fd_index}" ]] || exec {fd_index}>&-

    # unset traps
    trap - EXIT HUP TERM QUIT DEBUG
    return
}

# make variables local
local -a FD_in inAll parFunc
local -i nSent0 nSentCur splitAgainNSent splitAgainNLines splitAgainNFiles nFinal nProcs nBatch nBatchCur workerIndex rmTmpDirFlag
local fd_index IFS0 sendNext sendNext0 indexNext splitAgainPrefix splitAgainFileNames REPLY REPLYstr REPLYindexStr PID0 tmpDir tmpDirRoot timeoutCount orderedOutFlag strictOrderedOutFlag exportOrderFlag nullDelimiterFlag substituteStringFlag substituteStringIDFlag pipeFlag verboseFlag waitFlag noFuncFlag haveSplitFlag batchFlag stdinReadFlag autoBatchFlag splitAgainFlag unescapeFlag getInputFileName getNextInputFileName

#local -i nArgs
#local -i nSent
#local -i nDone
#local -a FD_out
#local -a pidA
#local pCur
#local pCur_PID

# record main process PID
PID0=$$

# record IFS, so we can change it back to what it originally was in the exit trap
IFS0="${IFS}"
export IFS=$'\n'

# open anonymous pipe. 
# This is used by the coprocs to indicate that they are done with a task and ready for another.
exec {fd_index}<><(:)


################################################################################
# # # # # # # # # # SECTION 2 -- PARSE FORKRUN FLAGS/OPTIONS # # # # # # # # # #
################################################################################

# parse inputs, set forkrun flags and options (using defaults when needed)
# note: any initial arguments (args0) are rolled into variable $parFunc
orderedOutFlag=false
strictOrderedOutFlag=false
exportOrderFlag=false
nullDelimiterFlag=false
substituteStringFlag=false
substituteStringIDFlag=false
pipeFlag=false
verboseFlag=false
waitFlag=false
noFuncFlag=false
tmpDirRoot='/tmp'
nProcs=0
nBatch=0
[[ -f /proc/meminfo ]] && (( $(grep 'MemTotal' /proc/meminfo | grep -oE '[0-9]+') < 8388608 )) && rmTmpDirFlag=3 || rmTmpDirFlag=1
inAll=("${@}")

while [[ "${1,,}" =~ ^-+.+$ ]]; do
    if [[ "${1,,}" =~ ^-+(j|(n?procs?)?))$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
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
    elif [[ "${1,,}" =~ ^-+i(nsert-?i)?d?$ ]]; then
        # specify location to insert inputs with {} 
        substituteStringFlag=true
        substituteStringIDFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+k(eep(-?order)?)?$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+((ks)|(keep(-?order)?-?strict))$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        strictOrderedOutFlag=true
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
    elif [[ "${1,,}" =~ ^-+u(nescape)?$ ]]; then
        # unescape '|' '>' '>>' '||' and '&&' in args0
        unescapeFlag=true
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
        helpText="$(<"${BASH_SOURCE[0]}")" || helpText="$(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)"
        helpText="${helpText%%'# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #'*}"
        printf '%s\n' "${helpText//$'\n''#'/$'\n'}"
        return    
    elif [[ "${1,,}" =~ ^-+v(erbose)?$ ]]; then
        # increase verbosity
        verboseFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+w(ait)?$ ]]; then
        # wait indefinately for split to output a file
        waitFlag=true
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

# check that we dont have both -n and -k. If so, -k supercedes -n
if ${orderedOutFlag} && ${exportOrderFlag}; then
    exportOrderFlag=false
    inAll=("${inAll[@]//'-n'/}")
    printf '%s\n' "WARNING: BOTH '-k' and '-n' FLAGS WERE PASSED TO FORKRUN. THESE FLAGS ARE MUTUALLY EXCLUSIVE." "'-k' SUPERCEDES '-n'. IGNORING '-n' FLAG." >&2
fi

# return if we dont have anything to parallelize over
(( ${#} == 0 )) && { printf '%s\n' 'NOTICE: NO FUNCTION SPECIFIED. COMMANDS PASSED ON STDIN WILL BE DIRECTLY EXECUTED.' >&2; noFuncFlag=true; } || { type -a "${1%%[ $'\n'$'\t']*}" 1>/dev/null 2>/dev/null || declare -F "${1%%[ $'\n'$'\t']*}" 2>/dev/null; } || { printf '%s ' 'ERROR: THE FUNCTION SPECIFIED IS UNKNOWN / CANNOT BE FOUND. ABORTING' $'\n''FUNCTION SPECIFIED: ' "${@}" $'\n' >&2 && return 1; }
[[ -t 0 ]] && printf '%s\n' 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (NOT A PIPE). ABORTING' >&2 && return 2

# check if we are automatically setting nBatch
(( ${nBatch} == 0 )) && { nBatch=512; autoBatchFlag=true; } || autoBatchFlag=false
(( ${nBatch} == 1 )) && ! ${strictOrderedOutFlag} && { batchFlag=false; rmTmpDirFlag=0; nullDelimiterFlag=false; waitFlag=false; } || batchFlag=true

${orderedOutFlag} && ! ${batchFlag} && printf '%s\n' '' 'WARNING: SORTED OUTPUT (-k) IS NOT GUARANTEED WHEN ONE-LINE-AT-A-TIME MODE (-l = 1) IS USED' 'TO GUARANTEE SORTRED OUTPUT (AT THE EXPENSE OF SLOWER RUN TIME) USE FLAG '"'"'-ks'"'"' instead of flag '"'"'-k'"'" '' >&2

# if user requested ordered output, re-run the forkrun call trading flag '-k' for flag '-n',
# then sort the output and remove the ordering index. Flag '-n' causes forkrun to do 2 things: 
# a) each "result group" (fron a particular batch of nBatch input lines) is NULL seperated
# b) each result group is pre-pended with the index/order that it was recieved in from stdin.
if ${orderedOutFlag} && ! ${batchFlag}; then
    #local outAll
    #printf '%s' "$(forkrun "${inAll[@]//'-k'/'-n'}" | LC_ALL=C sort -z -n -k2 -t$'\034' | cut -d$'\034' --output-delimiter=$'\n' -f 3-)" | sed -E s/'[^[:print:]]+'/'\n'/
    printf '%s\n' "$(forkrun "${inAll[@]//'-k'/'-n'}" | LC_ALL=C sort -z -d -k2 -t$'\034' | cut -f 3- --output-delimiter=$'\n' -d$'\034' -z)"
    return
fi

# finish parsing args

# default nProcs is number of logical cpu cores
(( ${nProcs} == 0 )) && nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '8')

# check if we have split
type -a split 1>/dev/null 2>/dev/null && haveSplitFlag=true || { haveSplitFlag=false; batchFlag=false; }
${haveSplitFlag} || { autoBatchFlag=false; nullDelimiterFlag=false; }

${noFuncFlag} && { ${batchFlag} || { batchFlag=true; nBatch=512; printf '%s\n' 'WARNING: ONE-LINE-AT-A-TIME MODE (-l 1) IS NOT AVAILABLE' 'WHEN NO FUNCTION IS PROVIDED. DISABLING THIS FLAG.' '(IN THIS USE CASE IT REALLY GIVES NO BENEFIT AND SLOWS THINGS DOWN ANYWAYS)' >&2; }; }

# prepare temp directory to store split stdin
mkdir -p "${tmpDirRoot}"
tmpDir="$(mktemp -d -p "${tmpDirRoot%/}" -t '.forkrun.XXXXXX')"
touch "${tmpDir}"/xAll

# if (( nBatch > 1 )) then split up input into files undert $tmpDir, each of which contains $nBatch lines and define a function for getting the next file name
# do this as early as possible so it can work in the background while the script sets itself up
#${batchFlag} && ${haveSplitFlag} && {
if ${batchFlag}; then
    # split into files, each containing a batch of $nBatch lines from stdin, using 'split'

    if ${nullDelimiterFlag}; then 
        {
            # split NULL-seperated stdin
            split -t '\0' -d -l "${nBatch}" - "${tmpDir}"'/x' <&4  
        } 4<&0 &
    else 
        {
            # split newline-seperated stdin
            split -d -l "${nBatch}" - "${tmpDir}"'/x' <&4 
        } 4<&0 &
    fi
 
else
    # not batching. Save stdin to a tmpfile
    {
        cat <&4 >"${tmpDir}"/xAll
    } 4<&0 &
fi

# incorporate string to get input into the function string
${substituteStringFlag} && ! [[ "${*}" == *'{}'* ]] && printf '%s\n' "WARNING: {} NOT FOUND IN FUNCTION STRING OR INITIAL ARGS. LINES FROM STDIN WILL NOT BE PASSED TO THE FUNCTION' 'THE FUNCTION AND ANY INITIAL ARGS WILL BE RUN (WITHOUT ANY OF THE ARGS FROM STDIN) ONCE FOR EACH LINE IN STDIN' 'IF THIS BEHAVIOR IS UNDESIRED, RE-RUN FORKRUN WITHOUT THE '-i' FLAG" >&2

# generate strings that will be used by the coprocs (when they are sourced later on) to actually call the function being parallelized with $nBatch input lines from stdin
# The function + initial args given as forkrun function inputs need to be `printf '%q'` quoted, but the command that gets the lines from stdin out of the file generated by split needs to be unquoted
if ${noFuncFlag}; then
    mapfile -t parFunc < <(printf '%q\n' "source")
    ! ${substituteStringFlag} && ! ${substituteStringIDFlag} || { substituteStringFlag=false; substituteStringIDFlag=false; printf '%s\n' 'WARNING: STRING SUBSTITUTION (-i | -id) NOT AVAILABLE' 'WHEN NO FUNCTION IS PROVIDED. DISABLING THESE FLAGS.' >&2; }
    ! ${pipeFlag} || { pipeFlag=false; printf '%s\n' 'WARNING: INPUT PIPING (-s) NOT AVAILABLE' 'WHEN NO FUNCTION IS PROVIDED. DISABLING THIS FLAG.' >&2; }    
else
    # modify parfunc if '-i' '-id' or '-u' flags are set
    mapfile -t parFunc < <(printf '%q\n' "${@}")
    ${substituteStringFlag} && {     
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\{\}'/'{}'}") 
    } && ${substituteStringIDFlag} && { 
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\{ID\}'/'${kk}'}") 
    }
    ${unescapeFlag} && {
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\>'/'>'}") 
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\<'/'<'}") 
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\|'/'|'}")
        mapfile -t parFunc < <(printf '%s\n' "${parFunc[@]//'\&\&'/'&&'}")
    }
fi

# if verboseFlag is set, print theparameters we just parsed to srderr
${verboseFlag} && {
printf '%s\n' '' "DONE PARSING INPUTS! Selected forkrun options:" ''
printf '%s\n' "parFunc = $(printf '%s ' "${parFunc[@]}")" "nProcs = ${nProcs}" "nBatch = ${nBatch}" "tmpDirRoot = ${tmpDirRoot}" "rmTmpDirFlag = ${rmTmpDirFlag}"
${orderedOutFlag} && printf '%s\n' "orderedOutFlag = true" || printf '%s\n' "orderedOutFlag = false"
${exportOrderFlag} && printf '%s\n' "exportOrderFlag = true" || printf '%s\n' "exportOrderFlag = false"
${haveSplitFlag} && printf '%s\n' "haveSplitFlag = true" || printf '%s\n' "haveSplitFlag = false"
${nullDelimiterFlag} && printf '%s\n' "nullDelimiterFlag = true" || printf '%s\n' "nullDelimiterFlag = false"
${autoBatchFlag} && printf '%s\n' "autoBatchFlag = true" || printf '%s\n' "autoBatchFlag = false"
${substituteStringFlag} && printf '%s\n' "substituteStringFlag = true" || printf '%s\n' "substituteStringFlag = false"
${substituteStringIDFlag} && printf '%s\n' "substituteStringIDFlag = true" || printf '%s\n' "substituteStringIDFlag = false"
${batchFlag} && printf '%s\n' "batchFlag = true" || printf '%s\n' "batchFlag = false"
${pipeFlag} && printf '%s\n' "pipeFlag = true" || printf '%s\n' "pipeFlag = false"
#${verboseFlag} && printf '%s\n' "veboseFlag = true" || printf '%s\n' "veboseFlag = false"
printf '\n'
} >&2


################################################################################
# # # # # # # # # # SECTION 3 -- DEFINE SUPPORTING FUNCTIONS # # # # # # # # # #
################################################################################
{


#else
 # use printf + sed to transform input into repeated blocks of the following form: printf '%s\n' ''' ${in1//'/'"'"'} ... ${inN//'/'"'"'} ''' > ${tmpDir}/in${kk}; ((kk++))
    # then use 'source' to execute this entire input, which will issue the commands needed to write each batch of N inputs to $tmpDir
    # Note: using ''' <...> ''' + encasing all single quotes in stdin by double quotes ('"'"') *should* prevent any of the file names from being executed as code unintentionally in normal usage, but might be exploitable. If you dont have `split` perhaps dont run forkrun as root...
 #   {
  #      source <(printf '%s\n' 'kk=0'; export IFS=$'\n' && printf 'printf '"'"'%%s'"'"' '"\'\'\'"'\n'"$(export IFS=$'\n' && printf '%%s\\n%.0s' $(seq 1 ${nBatch}))\'\'\'"' > ${tmpDir}/x${kk}\n((kk++))\n' $(sed -E s/"'"/"'"'"'"'"'"'"'"/g </dev/stdin) ) &
   # } 0<&6


getNextInputFileName() {
    ## get the name of the next file generated by split.
    # input 1 is prefix. input 2 is current split-generated file name.
    # this is faster than the (more general) getInputFileName, but only will provide the immediate next file name.

    local x
    local x_prefix

    x_prefix="${1}"
    [[ ${2:${#x_prefix}:1} == 0 ]] && x_prefix+='0'
    
    x="${2:${#x_prefix}}"
    
    [[ "$x" == '9' ]] && x_prefix="${x_prefix:0:-1}"

    if [[ "${x}" =~ ^9*89+$ ]]; then
        ((x++))
        x+='00'
    else
        ((x++))
    fi

    printf '%s%s' "${x_prefix}" "${x}"
}

getInputFileName() {
    ## transform simple count of sent files into file names used by `split -d`
    # `split -d` names the output files in an "unusual"  way to try and ensure output will always sort correctly. it goes:
    # x00 --> x89 (90 vals), then x9000 --> x9899 (900 vals), then x990000 -->998999 (9000 vals), etc
    #
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


#################################################################
# # # # # # # # # # SECTION 4 -- FORK COPROCS # # # # # # # # # #
#################################################################

# fork off $nProcs coprocs and record FDs / PIDs for them
#
# unfortunately this requires a source <(...) [or eval <...>] call to do dynamically... without this the coproc index "$kk" doesnt get properly applied in the loop.
# as such, the below code does not directly spawn the worker coprocs. Rather, it generates code which, when sourced, will spawn the required coprocs, and then sources this code.
#
# for nBatch == 1 : the coproc will recieve/read the line from stdin to run (and if needed ordering index) in the REPLY read from the input pipe.
# for nBatch > 1  : the coproc will recieve/read the file name of the file (under $tmpDir) to read to get the next batch of lines from the REPLY read from the input pipe.
#                   If needed, the file name is used as the ordering index.
#
# The coproc will then run the group of $nBatch line(s) though the function
# if ordered output (-n) is requested, the output will have the ordering index (plus a $'\t') pre-pended to each output from running each group of nBatch lines, and each group will be NULL-seperated.
# 
# after each worker finishes its current task, it sends its index to pipe {fd_index} to recieve another task. 
# when all tasks are finished (i.e., everything has been run), each coproc worker will be send a null input, causing it to break its 'while true' loop and terminate

# set a a string for how we will pass inputs to the function we are parallelizing. This string will be used in the coproc code that is generated and sourced below
if ${batchFlag}; then
    # REPLY is file name in $tmpDir containing lines from stdin. cat the file using '$(<file)' or (if pipeFlag is set) pass it directly using '<file'
    if ${noFuncFlag}; then
        REPLYstr='"'"${tmpDir}"'/${REPLY}"'
    elif ${pipeFlag}; then 
        REPLYstr='<"'"${tmpDir}"'/${REPLY}"'
    else        
        REPLYstr='$(<"'"${tmpDir}"'/${REPLY}")'
    fi

    # define string that will generate index representing input order
    ${exportOrderFlag} && REPLYindexStr='${REPLY#x}'

else
    # not using batching --> REPLY is a line from stdin
    if ${exportOrderFlag}; then
        # REPLY has been pre-pended with input order index. Remove it
        REPLYstr='${REPLY#*$'"'"'\t'"'"'}'

        # define string that will generate index representing input order
        REPLYindexStr='${REPLY%%$'"'"'\t'"'"'*}'
    else
        # REPLY contains just a line from stdin. Use it as-is
        REPLYstr='${REPLY}'
    fi
    # if pipeFlag is set pass this to stdin instead of giving it as a function input
    ${pipeFlag} && REPLYstr='<('"${REPLYstr}"')'
fi

${substituteStringFlag} && parFunc=("${parFunc[@]//'{}'/"${REPLYstr}"}") || parFunc+=("${REPLYstr}")

# generate source code (to be sourced) for coproc workers. Note that:
# 1) the "structure of" / "template used to generate" the coprocs will vary between several possibilities depending on which forkrun options/flags are set
# 2) the function + initial args (passed as forkrun function inputs) will be "hard-coded" in the code for each coproc
for kk in $(seq 0 $(( ${nProcs} - 1 ))); do

source <(cat<<EOI0
{ coproc p${kk} {
trap - EXIT HUP TERM INT 
set -f +B
$([[ -n ${DEBUG} ]] && printf '%s\n' 'set '"${DEBUG}")
export IFS=\$'\\n'

while true; do 
    read -r -d '' -u 7
    [[ -z \${REPLY} ]] && break

$(if ${exportOrderFlag}; then
cat<<EOI1
    {
        printf '\\034%s\\034%s\\n\\0' "${REPLYindexStr}" "\$(export IFS=\$'\\n' && $(printf '%s ' "${parFunc[@]}"))"
    } >&8
EOI1
else
cat<<EOI2
    { 
    export IFS=\$'\\n' && $(printf '%s ' "${parFunc[@]}") $(${orderedOutFlag} && ${batchFlag} && printf '%s\n' '> "'"${tmpDir}"'/${REPLY}"')
    } >&8
EOI2
fi)
    printf '%s\\0' ${kk} >&\${fd_index}
$( (( ${rmTmpDirFlag} >= 3 )) && ! { ${orderedOutFlag} && ${batchFlag}; } && cat<<EOI3
    rm -f "${tmpDir}/\${REPLY}"
EOI3
)
done
} 7<&0
} 8>&9
FD_in[${kk}]="\${p${kk}[1]}"
EOI0
)
    # record PIDs and i/o pipe file descriptors in indexed arrays (OLD -- NOT USED)
    #local -n pCur="p${kk}"
    #FD_in[${kk}]="${pCur[1]}"
    #FD_out[${kk}]="${pCur[0]}"
    #local +n pCur
    #local -n pCur_PID="p${kk}_PID"
    #pidA[${kk}]="$pCur_PID"
    #local +n pCur_PID

done


##############################################################################
# # # # # # # # # # SECTION 5 -- MAIN PARALLELIZATION LOOP # # # # # # # # # #
##############################################################################

# set initial vlues for the loop
#nSent=0
#nDone=0
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

    if [[ -f "${tmpDir}/$(getInputFileName 'x' $(( ${nProcs} - 1 )))" ]]; then
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
            ${waitFlag} || timeoutCount=4096
            until [[ -f "${tmpDir}/x00" ]]; do 
                sleep 0.001s
            if ! ${waitFlag}; then
                    ((timeoutCount--))
                    (( ${timeoutCount} == 0 )) && printf '%s\n' 'ERROR: NO FILES CONTAINING LINES FROM STDIN HAVE APPEARED ON '"$tmpDir" 'THIS LIKELY MEANS THERE WAS AN ERROR SOMEWHERE IN THE PIPE FEEDING FORKRUN' 'ABORTING TO AVOID GETTING STUCK IN AN INFINITE WAIT LOOP' 'TO FORCE FORKRUN TO WAIT INDEFINATELY FOR AN INPUT, PASS IT FLAG '"'"'-w'"'" && return 3
                fi
            done
        }

        # set flag and initial paramaters for dealing with the re-split files
        splitAgainFlag=true
        nSentCur=0
        sendNext0='x00'
        splitAgainPrefix="x00_x"


        # determine how many files we actually have available. Should be somewhere between 1 and $(( $nProcs - 1 ))
        splitAgainFileNames="$(kk=1; while [[ -f "${tmpDir}/${sendNext0}" ]] && (( ${kk} < ${nProcs} )); do
            printf '%s\n' "${tmpDir}/${sendNext0}" 
            sendNext0="$(getNextInputFileName 'x' "${sendNext0}")"
            ((kk++))
        done)"
        sendNext0="${splitAgainFileNames##*$'\n'}"
        sendNext0="${sendNext0##*/}"


        # record how many files we will be re-combining and re-splitting to figure out how many lines to put in each re-split file to split them evenly.
        splitAgainNSent="$(printf '%s\n' "${splitAgainFileNames}" | wc -l)"
        splitAgainNLines="$(export IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l)"
        (( ${splitAgainNLines} < ${nProcs} )) && splitAgainNFiles="${splitAgainNLines}" || splitAgainNFiles="${nProcs}"

        nBatchCur=$(( 1 + ( ( ${splitAgainNLines} - 1 ) / ${nProcs} ) )) 

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
        sendNext="x00_x00"

     # remove original files that went into splitAgain files is -d=3 or we are ordering output(to prevent inxcluding them in the output)
    { (( ${rmTmpDirFlag} == 3 )) || ${orderedOutFlag}; } && {
            export IFS=$'\n' && rm -f ${splitAgainFileNames}
        }
    fi

elif ${batchFlag}; then
    # using batching but not re-splitting. wait for 1st file (x00) to appear then continue
    [[ -f "${tmpDir}/x00" ]] || {
        ${waitFlag} || timeoutCount=4096
        until [[ -f "${tmpDir}/x00" ]]; do 
            sleep 0.001s
        if ! ${waitFlag}; then
                ((timeoutCount--))
                (( ${timeoutCount} == 0 )) && printf '%s\n' 'ERROR: NO FILES CONTAINING LINES FROM STDIN HAVE APPEARED ON '"$tmpDir" 'THIS LIKELY MEANS THERE WAS AN ERROR SOMEWHERE IN THE PIPE FEEDING FORKRUN' 'ABORTING TO AVOID GETTING STUCK IN AN INFINITE WAIT LOOP' 'TO FORCE FORKRUN TO WAIT INDEFINATELY FOR AN INPUT, PASS IT FLAG '"'"'-w'"'" && return 3
            fi
        done
    }
    sendNext='x00'  
else
    # not using batching. read 1 line from stdion and store it
    indexNext='x00'
    read -r -u 6 sendNext
    [[ -n "${sendNext}" ]] || { printf '%s\n' 'ERROR: NO INPUT ARGUMENTS GIVEN ON STDIN (EMPTY PIPE). ABORTING' >&2 && return 3; }
fi


# begin main loop. Listen on pipe {fd_index} for workers to send their unique ID, indicating they are free. 
# Respond with the file name of the file containing $nBatch lines from stdin. Repeat until all of stdin has been processed.
#while ${stdinReadFlag} || (( ${nFinal} > 0 )) || (( ${nDone} < ${nArgs} )); do
while ${stdinReadFlag} || (( ${nFinal} > 0 )); do

    # read {fd_index} (sent by worker coprocs) to trigger sending the next input
    read -r -d '' workerIndex <&${fd_index}            
    #(( ${nSent} < ${nProcs} )) || ((nDone++))

    if ${stdinReadFlag}; then
        # still distributing stdin - send next file name (containing next group of inputs) to worker coproc

        if ${batchFlag}; then
            # using batching. Deal with file names in $tmpDir

            # send filename to worker and iterate counters
            printf '%s\0' "${sendNext}" >&${FD_in[${workerIndex}]}
            #((nSent++))
            ${splitAgainFlag} && ((nSentCur++)) || ((nSent0++))

            # get next file name to send based on $nSent0 (and, if working of a batch of re-split files, on $nSentCur)
            if ${autoBatchFlag}; then

                if ${splitAgainFlag} && (( ${nSentCur} == ${splitAgainNFiles} )); then
                    # we just sent to last file from a re-split group. Turn off splitAgainFlag, clear splitAgain parameters
                    # and advance nSent0 by number of (split-generated) files that originally went in to the resplit group of files
                    nSentCur=0
                    splitAgainPrefix=''
                    splitAgainFileNames=''
                    nBatchCur=0
                    splitAgainFlag=false
                    nSent0=$(( ${nSent0} + ${splitAgainNSent} ))
                    splitAgainNSent=0
                    splitAgainNLines=0
                    splitAgainNFiles=0
                    sendNext="${sendNext0}"    
                fi

                if ${splitAgainFlag}; then
                    # we are still working through the current set of re-split files. next file name is in re-split file group
                    # naming convention for resplit file group is: x$(indexOfFirstFileThatWentINtoResplitGroup}_x${indexInResplitGroup}
                    # e.g., the 1st group of resplit files will have names x00_x00, x00_x01, ..., x00_x$(getNextInputFileName '' ${nProcs})
                    sendNext="$(getNextInputFileName "${splitAgainPrefix}" "${sendNext}")"

                elif [[ -f "${tmpDir}/$(getInputFileName 'x' $(( ${nSent0} + ${nProcs} - 1 )))" ]]; then
                    # Check if there are $nProcs not-yet-read stdin files generated by split available. 
                    # If so then we have at least enough inputs to do 1+ set of $nBatch inputs on each coproc worker, 
                    # so we dont need to adjust nBatch anymore --> turn off autoBatchFlag
                    sendNext="$(getNextInputFileName 'x' "${sendNext}")"
                    autoBatchFlag=false

                elif ! [[ -f "$(getNextInputFileName 'x' "${sendNext}")" ]]; then
                    # the next file with stdin lines doesnt exist. trigger stop condition
                    stdinReadFlag=false
                    autoBatchFlag=false
                    sendNext=''
                    #nArgs=${nSent}

                else
                    # we have more than 1 but less than $nProcs available files with lines from stdin in $tmpDir. Re-split them into $nProcs files.
                    # set flag and initial paramaters for dealing with the re-split files
                    splitAgainFlag=true
                    nSentCur=0

                    # determine how many files we actually have available. Should be somewhere between 1 and $(( $nProcs - 1 ))
                    sendNext0="${sendNext}"
                    splitAgainPrefix="${sendNext0}_x"

                    # determine how many files we actually have available. Should be somewhere between 1 and $(( $nProcs - 1 ))
                    splitAgainFileNames="$(kk=1; while [[ -f "${tmpDir}/${sendNext0}" ]] && (( ${kk} < ${nProcs} )); do
                        printf '%s\n' "${tmpDir}/${sendNext0}" 
                        sendNext0="$(getNextInputFileName 'x' "${sendNext0}")"
                        ((kk++))
                    done)"

                    sendNext0="${splitAgainFileNames##*$'\n'}"
                    sendNext0="${sendNext0##*/}"

                    # record how many files we will be re-combining and re-splitting to figure out how many lines to put in each re-split file to split them evenly.
                    splitAgainNSent="$(printf '%s\n' "${splitAgainFileNames}" | wc -l)"
                    splitAgainNLines="$(export IFS=$'\n' && cat -s ${splitAgainFileNames} | wc -l)"
                    (( ${splitAgainNLines} < ${nProcs} )) && splitAgainNFiles="${splitAgainNLines}" || splitAgainNFiles="${nProcs}"

                    nBatchCur=$(( 1 + ( ( ${splitAgainNLines} - 1 ) / ${nProcs} ) )) 

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

                    # generate name of 1st file in current group
                    sendNext="${splitAgainPrefix}00" 

            # remove original files that went into splitAgain files is -d=3 or we are ordering output(to prevent inxcluding them in the output)
            { (( ${rmTmpDirFlag} == 3 )) || ${orderedOutFlag}; }  && {
                        export IFS=$'\n' && rm -f ${splitAgainFileNames}
                    }

                fi

            else
                # dont check how many files we have since we arent re-splitting. Just get the next file name to send.
                sendNext="$(getNextInputFileName 'x' "${sendNext}")"

            fi

            # if there isnt another file to read (i.e., $sendNext doesnt exist) then trigger stop condition
            [[ -f "${tmpDir}/${sendNext}" ]] || { 
                stdinReadFlag=false
                #nArgs=${nSent}
            }

        else 
            # not using batching. send lines from stdin. pre-pend $nSent (which gives input ordering) if exportOrderFLag is set

            if ${exportOrderFlag}; then
                # sorting output. pre-pend data sent with index describing input ordering to the line from stdin that is being sent
                printf '%s\t%s\0' "${indexNext}" "${sendNext}" >&${FD_in[${workerIndex}]}

               # get next ordering index
               indexNext="$(getNextInputFileName 'x' "${indexNext}")"
            else
                # not sorting output. Just send input lines as-is
                printf '%s\0' "${sendNext}" >&${FD_in[${workerIndex}]}
            fi
            #((nSent0++))

            # read next line from stdin to send. If read fails or is empty trigger stop contition
            read -r -u 6 sendNext && [[ -n ${sendNext} ]] || stdinReadFlag=false; 

        fi

    else              
        # all of stdin has been sent off to workers. As each worker coproc finishes its final task, send it a NULL to cause it to break its 'while true' loop and terminate.

        # iterate counters
        #(( ${nSent} < ${nProcs} )) && ((nDone++))
        ((nFinal--))

        # send the (now fully finished) worker coproc '\0' to cause it to shutdown   
        printf '\0' >&${FD_in[${workerIndex}]}

    fi

done


} 6<"${tmpDir}"/xAll 9>&1

${orderedOutFlag} && ${batchFlag} && cat "${tmpDir}"/x*

# remove tmpDir, unless (( rmTmpDirFlag == 0 ))
if (( ${rmTmpDirFlag} >= 1 )); then
    [[ -n ${tmpDir} ]] && [[ -d "${tmpDir}" ]] && rm -rf "${tmpDir}"
elif ${batchFlag}; then
    printf '%s\n' '' "TEMP DIR CONTAINING INPUTS HAS NOT BEEN REMOVED" "PATH: ${tmpDir}" '' >&2
fi
}
