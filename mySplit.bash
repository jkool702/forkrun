#!/usr/bin/env bash

# check for cat. if missing define a usable replacement using bash builtins
type -a cat &>/dev/null || {
cat() {
    if  [[ -t 0 ]] && [[ $# == 0 ]]; then
        # no input
        return
    elif [[ $# == 0 ]]; then
        # only stdin
        printf '%s\n' "$(</proc/self/fd/0)"
    elif [[ -t 0 ]]; then
        # only function inputs
        source <(printf 'echo '; printf '"$(<"%s")" ' "$@"; printf '\n')
    else
        # both stdin and function inputs. fork printing stdin to allow for printing both in parallel.
        printf '%s\n' "$(</proc/self/fd/0)" &
        source <(printf 'echo '; printf '"$(<"%s")" ' "$@"; printf '\n')
    fi
}
}

# check for mktemp. if missing define a usable replacement using bash builtins
type -a mktemp &>/dev/null || {
mktemp () (
    local p d f
    set -C
    umask 177
    while [[ "${1}" == -@([pd]) ]]; do
        [[ "${1}" == '-p' ]] && p="$2"
        [[ "${1}" == '-d' ]] && d="$2"
        shift 2
    done
    [[ "$d" == *XXXXXX* ]] || d=''
    : "${p:=/dev/shm}" "${d:=.mySplit.XXXXXX}"

    f="${p}/${d//XXXXXX/$(printf '%06x' ${RANDOM}${RANDOM:1})}"
    until mkdir "$f"; do
        f="${p}/${d//XXXXXX/$(printf '%06x' ${RANDOM}${RANDOM:1})}"
    done 2>/dev/null
    echo "$f"
)
}

shopt -s extglob

mySplit() {
## Efficiently parallelize a loop / run many tasks in parallel *extremely* fast using bash coprocs
#
# USAGE: printf '%s\n' "${args[@]}" | mySplit [-flags] [--] parFunc ["${args0[@]}"]
#
#      Usage is vitrually identical to parallelizing a loop by using `xargs -P` or `parallel -m`:
#          -->  Pass newline-separated (or null-separated with `-z` flag) inputs to parallelize over on stdin.
#          -->  Provide function/script/binary to parallelize and initial args as function inputs.
#      `mySplit` will then call the function/script/binary in parallel on several coproc "workers" (default is to use $(nproc) workers)
#       Each time a worker runs the function/script/binary it will use the initial args and N lines from stdin (default: `N` is between 1-512 lines and is automatically dynamically adjusted)
#          --> i.e., it will run (in parallel on each "worker"):     parFunc "${args0[@]}" "${args[@]:m:N}"    # m = number of lines from stdin already processed
#       `parFunc` can be an executable binary or bash script, a bash builtin, a declared bash function / alias, or *omitted entirely* (*requires -N [-NO-FUNC] flag. See flag descriptions below for more info.*)
#
# EXAMPLE CODE:
#      # get sha256sum of all files under ${PWD}
#      find ./ -type f | mySplit sha256sum
#
# HOW IT WORKS:
#      The coproc code is dynamically generated based on passed mySplit options, then K coprocs (plus some "helper function" coprocs) are forked off.
#      These coprocs will groups on lines from stdin using a shared fd and run them through the specified function in parallel.
#      Importantly, this means that you dont need to fork anything after the initial coprocs are set up...the same coprocs are active for the duration of mySplit, and are continuously piped new data to run.
#      This is MUCH faster than the traditional "forking each call" in bash (esp. for many fast tasks)...On my hardware `mySplit` is 1x-2x faster than `xargs -P $(nproc) -d $'\n'`  and 3x-8x faster than `parallel -m`.
#
# REQUIRED DEPENDENCIES:
#      Bash 4+                      : This is when coprocs were introduced. WARNING: running this code on bash 4.x  *should* work, but is largely untested. Bah 5.1+ is prefferable has undergone much more testing.
#      `rm`  and  `mkdir`           : Required for various tasks, and doesnt have an obvious pure-bash implementation. Either the GNU version or the Busybox version is sufficient.
#
# OPTIONAL DEPENDENCIES (to provide enhanced functionality):
#      Bash 5.1+                    : Bash arrays got a fairly major overhaul here, and in particular the mapfile command (which is used extensively to read data from the tmpfile containing stdin) 
#                                     got a major speedup here. Bash versions 4.0 - 5.0 *should* still work, but will be (perhaps considerably) slower.
#     `fallocate` -AND- kernel 3.5+ : Required to remove already-read data from in-memory tmpfile. Without both of these stdin will accumulate in the tmpfile and won't be cleared until mySplit is finished and returns 
#                                     (which, especially if stdin is being fed by a long-running process, could eventually result in very high memory use).
#     `inotifywait`                 : Required to efficiently wait for stdin if it is arriving much slower than the coprocs are capable of processing it (e.g. `ping 1.1.1.1 | mySplit). 
#                                     Without this the coprocs will non-stop try to read data from stdin, causing unnecessarily high CPU usage. It also enables the real-time printing (and then freeing from memory) 
#                                     outputs when "ordered output" mode is being used (flags `-k` or `-n`) (otherwise all output is saved on in memory and printed at the end after mySplit has finished running).
#
# # # # # # # # # # # # FLAGS # # # # # # # # # # # #
#
# GENERAL NOTES:
#      1. Flags are matched using extglob and have a degree of "fuzzy" matching. As such, the "short" flag options must be given separately (use `-a -b`, not `-ab`). Only the most common invocations are shown below. 
#         Refer to the code for exact extglob match criteria. Example of "fuzziness" in matching: both the short and long flags may use either 1 or 2 leading dashes ('-'). NOTE: Flags ARE case-sensitive.
#      2. All mySplit flags must be given before the name or (and arguments for) whatever you are parallelizing. By default, mySplit assumes that `parFunc` is the first input that does NOT begin with a '-' or '+'. 
#         To stop option parsing sooner, add a '--' after the last mySplit flag. Note: this will only stop option parsing sooner...mySplit will always stop at the first argument that does not begin with a '-' or '+'.
#
# FLAGS WITH ARGUMENTS:
#     SYNTAX NOTE: Arguments for flags may be passed with a (breaking or non-breaking) space ' ', equal sign ('='), or no separator (''), between the flag and the argument. i.e., the following all work:
#                  -A Val   |   '-A Val'   |   -A=Val   |   -AVal   |   --A_long Val   |   '--A_long Val'   |   --A_long=Val   |   --A_longVal
#
# ----------------------------------------------------------
#
# -j | -P | --nprocs : sets the number of worker coprocs to use
#    ---->  default  : number of logical CPU cores ($(nproc))
#    
# ----------------------------------------------------------
# 
# -t | --tmp[dir]    : sets the root directory for where the tmpfiles used by mySplit are created.
#    ---->  default  : /dev/shm ; or (if unavailable) /tmp ; or (if unavailable) ${PWD}
#    
#    NOTE: unless running on an extremely memory-constrained system, having this tmp directory on a ramdisk (e.g., a tmpfs) will greatly improve performance
# 
# ----------------------------------------------------------
# 
# -l | --nlines      : sets the number or lines to pass coprocs to use for each function call to this constant value, disabling the automatic dynamic batch size logic.
#    ---->  default  : n/a (by default automatic dynamic batch size adjustment is enabled)
# 
# -L | --NLINES      : sets the number or lines to pass coprocs to initially use for each function call, while keeping the automatic dynamic batch size logic enabled. 
#    ---->  default  : 1
#             
# 	NOTE  : the automatic dynamic batch size logic will only ever maintain or increase batch size...it will never decrease batch size.
#    
# ----------------------------------------------------------
#    
# FLAGS WITHOUT ARGUMENTS:
#     SYNTAX NOTE: These flags serve to enable various optional subroutines. All flags (short or long) may use either 1 or 2 leading dashes ('-f' or '--f' or '-flag' or '--flag' all work) to enable these.
#                  To instead disable these optional subroutines, replace the leading '-' or '--' with a leading '+' or '++' or '+-'. If a flag is given multiple times, the last one is used.
#                  Unless otherwise noted, all of  the following flags are, by default, in the "disabled" state
#    
#     COMING SOON

############################ BEGIN FUNCTION ############################

    trap - EXIT

    shopt -s extglob

    # make all variables local
    local tmpDir fPath outStr exitTrapStr exitTrapStr_kill nOrder coprocSrcCode outCur tmpDirRoot inotifyFlag fallocateFlag nLinesAutoFlag substituteStringFlag substituteStringIDFlag nOrderFlag nullDelimiterFlag subshellRunFlag stdinRunFlag pipeReadFlag rmTmpDirFlag verboseFlag exportOrderFlag noFuncFlag unescapeFlag optParseFlag continueFlag fd_continue fd_inotify fd_inotify0 fd_inotify1 fd_inotify10 fd_inotify2 fd_inotify20 fd_nAuto fd_nAuto0 fd_nOrder fd_read fd_write fd_stdout fd_stdin fd_stderr pWrite_PID pNotify_PID pNotify0_PID pOrder_PID pAuto_PID fd_read_pos fd_read_pos_old fd_write_pos
    local -i nLines nLinesCur nLinesNew nLinesMax nCur nNew nRead nProcs nWait v9 kkMax kkCur kk
    local -a A p_PID runCmd outA
    
    # # # # # PARSE OPTIONS # # # # #

    # check inputs and set defaults if needed
    [[ $# == 0 ]] && optParseFlag=false || optParseFlag=true
    while ${optParseFlag} && (( $# > 0  )) && [[ "$1" == [-+]* ]]; do
        case "${1}" in

            -?(-)j?([= ])|-?(-)P?([= ])|-?(-)?(n)proc?(s)?([= ]))
                nProcs="${2}"
                shift 1
            ;;

            -?(-)j?([= ])*@([[:graph:]])*|-?(-)P?([= ])*@([[:graph:]])*|-?(-)?(n)proc?(s)?([= ])*@([[:graph:]])*)
                nProcs="${1##@(-?(-)j?([= ])|-?(-)P?([= ])|-?(-)?(n)proc?(s)?([= ]))}"
            ;;

            -?(-)?(n)l?(ine?(s)))
                nLines="${2}"
                nLinesAutoFlag=false
                shift 1
            ;;

            -?(-)?(n)l?(ine?(s))?([= ])*@([[:graph:]])*)
                nLines="${1##@(-?(-)?(n)l?(ine?(s))?([= ]))}"
                nLinesAutoFlag=false
            ;;

            -?(-)?(N)L?(INE?(S)))
                nLines="${2}"
                nLinesAutoFlag=true
                shift 1
            ;;

            -?(-)?(N)L?(INE?(S))?([= ])*@([[:graph:]])*)
                nLines="${1##@(-?(-)?(N)L?(INE?(S))?([= ]))}"
                nLinesAutoFlag=true
            ;;

            -?(-)t?(mp?(?(-)dir)))
                tmpDirRoot="${2}"
                shift 1
            ;;

            -?(-)t?(mp?(?(-)dir))?([= ])*@([[:graph:]])*)
                tmpDirRoot="${1##@(-?(-)t?(mp?(?(-)dir))?([= ]))}"
            ;;

            -?(-)i?(nsert))
                substituteStringFlag=true
            ;;

            -?(-)I?(D)|-?(-)INSERT?(?(-)ID))
                substituteStringIDFlag=true
            ;;

            -?(-)k?(eep?(?(-)order)))
                nOrderFlag=true
            ;;

            -?(-)0|-?(-)z?(ero)|-?(-)null)
                nullDelimiterFlag=true
            ;;

            -?(-)s?(ub)?(?(-)shell)?(?(-)run))
                subshellRunFlag=true
            ;;

            -?(-)S?(TDIN)?(?(-)RUN))
                stdinRunFlag=true
            ;;

            -?(-)p?(ipe)?(?(-)read))
                pipeReadFlag=true
            ;;

            -?(-)d?(elete))
                rmTmpDirFlag=true
            ;;

            -?(-)v?(erbose))
                verboseFlag=true
            ;;

             -?(-)n?(umber)?(-)?(line?(s)))
                exportOrderFlag=true
            ;;

            -?(-)N?(O)?(?(-)F?(UNC)))
                noFuncFlag=true
            ;;

            -?(-)u?(nescape))
                unescapeFlag=true
            ;;

            -?(-)h?(elp)|-?(-)usage|-?(-)\?)
                : #displayHelp (TBD)
            ;;

            +?([-+])i?(nsert))
                substituteStringFlag=false
            ;;

            +?(-)I?(D)|+?(-)INSERT?(?(-)ID))
                substituteStringIDFlag=false
            ;;

            +?([-+])k?(eep?(?(-)order)))
                nOrderFlag=false
            ;;

            +?([-+])0|+?([-+])z|+?([-+])null)
                nullDelimiterFlag=false
            ;;

            +?([+-])s?(ub)?(?(-)shell)?(?(-)run))
                subshellRunFlag=false
            ;;

            +?([-+])S?(TDIN)?(?(-)RUN))
                stdinRunFlag=false
            ;;

            +?([-+])p?(ipe)?(?(-)read))
                pipeReadFlag=false
            ;;

            +?([-+])d?(elete))
                rmTmpDirFlag=false
            ;;

            +?([-+])v?(erbose))
                verboseFlag=false
            ;;

            +?([-+])n?(umber)?(-)?(line?(s)))
                exportOrderFlag=false
            ;;

            +?([-+])N?(O)?(?(-)F?(UNC)))
                noFuncFlag=false
            ;;

            +?([-+])u?(nescape))
                unescapeFlag=false
            ;;

            --)
                optParseFlag=false
            ;;

            @([-+])?([-+])*@([[:graph:]])*)
                printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$1" >&2
            ;;

            *)
                optParseFlag=false
                break
            ;;

        esac

        shift 1
        [[ ${#} == 0 ]] && optParseFlag=false

    done

    # # # # # SETUP TMPDIR # # # # #

    [[ ${tmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && tmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && tmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && tmpDirRoot='/tmp'; } || tmpDirRoot="$(pwd)"
    [[ -d "${tmpDirRoot}" ]] || mkdir -p "${tmpDirRoot}"

    tmpDir="$(mktemp -p "${tmpDirRoot}" -d .mySplit.XXXXXX)"
    fPath="${tmpDir}"/.stdin

    mkdir -p "${tmpDir}"/.run
    : >"${fPath}"

    # # # # # BEGIN MAIN SUBSHELL # # # # #
    
    # several file descriptors are opened for use by things running in this subshell. See clkosing `)` near the end of this function.
    (
    
        # # # # # INITIAL SETUP # # # # #

        LC_ALL=C
        LANG=C
        IFS=
        umask 177

        shopt -s nullglob

        # dynamically set defaults for a few flags

        # determine what mySplit is using lines on stdin for
        [[ ${FORCE} ]] && runCmd=("${@}") || runCmd=("${@//$'\r'/}")
        : "${noFuncFlag:=false}"
        (( ${#runCmd[@]} > 0 )) || ${noFuncFlag} || runCmd=(printf '%s\n')
        (( ${#runCmd[@]} > 0 )) && noFuncFlag=false

        # set batch size
        { [[ ${nLines} ]]  && (( ${nLines} > 0 )) && : "${nLinesAutoFlag:=false}"; } || : "${nLinesAutoFlag:=true}"
        { [[ -z ${nLines} ]] || [[ ${nLines} == 0 ]]; } && nLines=1

        # set number of coproc workers
        { [[ ${nProcs} ]]  && (( ${nProcs} > 0 )); } || nProcs=$({ type -a nproc &>/dev/null && nproc; } || { type -a grep &>/dev/null && grep -cE '^processor.*: ' /proc/cpuinfo; } || { mapfile -t tmpA  </proc/cpuinfo && tmpA=("${tmpA[@]//processor*/$'\034'}") && tmpA=("${tmpA[@]//!($'\034')/}") && tmpA=("${tmpA[@]//$'\034'/1}") && tmpA="${tmpA[*]}" && tmpA="${tmpA// /}" && echo ${#tmpA}; } || printf '8')

        # if reading 1 line at a time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # check for inotifywait
        type -a inotifywait &>/dev/null && : "${inotifyFlag:=true}" || : "${inotifyFlag:=false}"

        # check for fallocate
        type -a fallocate &>/dev/null && : "${fallocateFlag:=true}" || : "${fallocateFlag:=false}"

        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmTmpDirFlag:=true}" "${nLinesMax:=512}" "${nullDelimiterFlag:=false}" "${subshellRunFlag:=false}" "${stdinRunFlag:=false}" "${pipeReadFlag:=false}" "${substituteStringFlag:=false}" "${substituteStringIDFlag:=false}" "${exportOrderFlag:=false}" "${verboseFlag:=false}" "${unescapeFlag:=false}"

        # check for conflict in flags that were  defined on the commandline when mySplit was called
        ${pipeReadFlag} && ${nLinesAutoFlag} && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }

        # require -k to use -n
        ${exportOrderFlag} && nOrderFlag=true

        # modify runCmd if '-i' '-I' or '-u' flags are set
        if ${unescapeFlag}; then
            ${substituteStringFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'{}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'{ID}'/'{<#>}'}")
            }
        else
            mapfile -t runCmd < <(printf '%q\n' "${runCmd[@]}")
            ${substituteStringFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'\{\}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'\{ID\}'/'{<#>}'}")
            }
        fi

        nLinesCur=${nLines}

        mkdir -p "${tmpDir}"/.run

        # if keeping tmpDir print its location to stderr
        ${rmTmpDirFlag} || ${verboseFlag} || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}

        ${verboseFlag} && {
            printf '\n\n-------------------INFO-------------------\n\nCOMMAND TO PARALLELIZE: %s\n' "$(printf '%s ' "${runCmd[@]}")"
            ${noFuncFlag} && echo '(no function mode enabled: commands should be included in stdin)' || printf 'tmpdir: %s\n' "${tmpDir}"
            printf '(-j|-P) using %s coproc workers\n' ${nProcs}
            ${inotifyFlag} && echo 'using inotify'
            ${fallocateFlag} && echo 'using fallocate'
            ${nLinesAutoFlag} && echo '(-N) automatically adjusting batch size (lines per function call)'
            ${nOrderFlag} && echo '(-k) ordering output the same as the input'
            ${exportOrderFlag} && echo '(-n) output lines will be numbered (`grep -n` style)'
            ${substituteStringFlag} && echo '(-i) replacing {} with lines from stdin'
            ${substituteStringFlag} && echo '(-I) replacing {ID} with coproc worker ID'
            ${unescapeFlag} && echo '(-u) not escaping special characters in ${runCmd}'
            ${pipeReadFlag} && echo '(-p) worker coprocs will read directly from stdin pipe, not from a tmpfile'
            ${nullDelimiterFlag} && echo '(-0|-z) stdin will be parsed using nulls as delimiter (instead of newlines)'
            ${rmTmpDirFlag} || printf '(-r) tmpdir (%s) will NOT be automaticvally removed\n' "${tmpDir}"
            ${subshellRunFlag} && echo '(-s) coproc workers will run each group of N lines in a subshell'
            ${stdinRunFlag} && echo '(-S) coproc workers will pass lines to the command being parallelized via the command'"'"'s stdin'
            printf '\n------------------------------------------\n\n'
        } >&${fd_stderr}
        
        # # # # # FORK "HELPER" PROCESSES # # # # #   

        # start building exit trap string
        exitTrapStr=': >"'"${tmpDir}"'"/.done;
: >"'"${tmpDir}"'"/.quit;
[[ -z $(echo "'"${tmpDir}"'"/.run/p*) ]] || kill $(cat "'"${tmpDir}"'"/.run/p*); '$'\n'

       ${pipeReadFlag} && {
            # '.done'  file makes no sense when reading from a pipe
            : >"${tmpDir}"/.done
        } || {
            # spawn a coproc to write stdin to a tmpfile
            # After we are done reading all of stdin indicate this by touching .done
            { coproc pWrite {
                cat <&${fd_stdin} >&${fd_write}
                : >"${tmpDir}"/.done
                ${inotifyFlag} && {
                    { source /proc/self/fd/0 >&${fd_inotify1}; }<<<"printf '%.0s\n' {0..${nProcs}}"
                } {fd_inotify1}>&${fd_inotify}
                ${verboseFlag} && printf '\nINFO: pWrite has finished - all of stdin has been saved to the tmpfile at %s\n' "${fPath}" >&${fd_stderr}
              }
            }
            exitTrapStr_kill+='kill -9 '"${pWrite_PID}"' 2>/dev/null; '$'\n'
        }

        # setup+fork inotifywait (if available)
        ${inotifyFlag} && {
            {
                # initially add 1 newline for each coproc to fd_inotify
                { source /proc/self/fd/0 >&${fd_inotify1}; }<<<"printf '%.0s\n' {0..${nProcs}}"

                # run inotifywait
                inotifywait -q -m --format '' "${fPath}" >&${fd_inotify1} &

                pNotify_PID=${!}
            } 2>/dev/null {fd_inotify1}>&${fd_inotify}


            exitTrapStr+='( printf '"'"'\n'"'"' >&${fd_inotify2}; ) {fd_inotify2}>&'"${fd_inotify}"'; '$'\n'
            ${nOrderFlag} && exitTrapStr+=': >"'"${tmpDir}"'"/.out/.quit; '$'\n'
            exitTrapStr_kill+='kill -9 '"${pNotify_PID}"' 2>/dev/null; '$'\n'
        }

        # setup (ordered) output. This uses the same naming scheme as `split -d` to ensure a simple `cat /path/*` always orders things correctly.
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'

            printf '%s\n' {10..89} {9000..9899} >&${fd_nOrder}

            # monitor ${tmpDir}/.out for new files if we have inotifywait
            ${inotifyFlag} && {
                {
                    inotifywait -q -m -e close_write --format '%f' -r "${tmpDir}"/.out >&${fd_inotify10} &

                    pNotify0_PID=${!}
                } 2>/dev/null {fd_inotify10}>&${fd_inotify0}

                exitTrapStr+='( printf '"'"'\n'"'"' >&${fd_inotify20}; ) {fd_inotify20}>&'"${fd_inotify0}"'; '$'\n'
                exitTrapStr_kill+='kill -9 '"${pNotify0_PID}"' 2>/dev/null; '$'\n'
            }

            # fork coproc to populate a pipe (fd_nOrder) with ordered output file name indicies for the worker copropcs to use
            { coproc pOrder {

                # generate enough nOrder indices (~10000) to fill up 64 kb pipe buffer
                # start at 10 so that bash wont try to treat x0_ as an octal
                printf '%s\n' {990000..998999} >&${fd_nOrder}

                # now that pipe buffer is full, add additional indices 1000 at a time (as needed)
                v9='99'
                kkMax='8'
                until [[ -f "${tmpDir}"/.quit ]]; do
                    v9="${v9}9"
                    kkMax="${kkMax}9"

                    for (( kk=0 ; kk<=kkMax ; kk++ )); do
                        kkCur="$(printf '%0.'"${#kkMax}"'d' "$kk")"
                        { source /proc/self/fd/0 >&${fd_nOrder}; }<<<"printf '%s\n' {${v9}${kkCur}000..${v9}${kkCur}999}"
                    done
                done

              }
            } 2>/dev/null

            exitTrapStr_kill+='kill -9 '"${pOrder_PID}"' 2>/dev/null; '$'\n'
        else
            outStr='>&'"${fd_stdout}";
        fi

        # setup automatic dynamic nLines adjustment and/or fallocate pre-truncation of (already processed) stdin
        if ${nLinesAutoFlag} || ${fallocateFlag}; then

            printf '%s\n' ${nLines} >"${tmpDir}"/.nLines

            # LOGIC FOR DYNAMICALLY SETTING 'nLines':
            # The avg_bytes_per_line is estimated by looking at the byte offset position of fd_read and having each coproc keep track of how many lines it has read
            # the new "proposed" 'nLines' is determined by estimating the average bytes per line, then taking the averge of the "current nLines" and "(numbedr unread bytes) / ( (avg bytes per line) * (nProcs) )"
            # --> if proposed new 'nLines' is greater than current 'nLines' then use it (use case: stdin is arriving fairly fast, increase 'nLines' to match the rate lines are coming in on stdin)
            # --> if proposed new 'nLines' is less than or equal to current 'nLines' ignore it (i.e., nLines can only ever increase...it will never decrease)
            # --> if the new 'nLines' is greater than or equal to 'nLinesMax' or the .quit file has appeared, then break after the current iteratrion is finished
            { coproc pAuto {

                ${fallocateFlag} && {
                    nWait=$(( 8 + ( ${nProcs} / 2 ) ))
                    fd_read_pos_old=0
                }
                ${nLinesAutoFlag} && nRead=0

                while ${fallocateFlag} || ${nLinesAutoFlag}; do

                    read -u ${fd_nAuto} -t 0.1

                    case ${REPLY} in
                        0)
                            nLinesAutoFlag=false
                            fallocateFlag=false
                            break
                        ;;

                        '')
                            nLinesAutoFlag=false
                        ;;
                    esac

                    read fd_read_pos </proc/self/fdinfo/${fd_read}
                    fd_read_pos=${fd_read_pos##*$'\t'}

                    if ${nLinesAutoFlag}; then

                        read fd_write_pos </proc/self/fdinfo/${fd_write}
                        fd_write_pos=${fd_write_pos##*$'\t'}

                        nRead+=${REPLY}

                        nLinesNew=$(( 1 + ( ${nLinesCur} + ( ( 1 + ${nRead} ) * ( ${fd_write_pos} - ${fd_read_pos} ) ) / ( ${nProcs} * ( 1 + ${fd_read_pos} ) ) ) ))

                        (( ${nLinesNew} > ${nLinesCur} )) && {

                            (( ${nLinesNew} >= ${nLinesMax} )) && { nLinesNew=${nLinesMax}; nLinesAutoFlag=false; }

                            printf '%s\n' ${nLinesNew} >"${tmpDir}"/.nLines

                            # verbose output
                            ${verboseFlag} && printf '\nCHANGING nLines from %s to %s!!!  --  ( nRead = %s ; write pos = %s ; read pos = %s )\n' ${nLinesCur} ${nLinesNew} ${nRead} ${fd_write_pos} ${fd_read_pos} >&2

                            nLinesCur=${nLinesNew}
                        }
                    fi

                    if ${fallocateFlag}; then
                        case ${nWait} in
                            0)
                                fd_read_pos=$(( 4096 * ( ${fd_read_pos} / 4096 ) ))
                                (( ${fd_read_pos} > ${fd_read_pos_old} )) && {
                                    fallocate -p -o ${fd_read_pos_old} -l $(( ${fd_read_pos} - ${fd_read_pos_old} )) "${fPath}"
                                    ${verboseFlag} && echo "Truncating $(( ${fd_read_pos} - ${fd_read_pos_old} )) bytes off the start of the file" >&2
                                    fd_read_pos_old=${fd_read_pos}
                                }
                                nWait=$(( 4 + ( ${nProcs} / 4 ) ))
                            ;;
                            *)
                                ((nWait--))
                            ;;
                        esac
                    fi

                    [[ -f "${tmpDir}"/.quit ]] && {
                        nLinesAutoFlag=false
                        fallocateFlag=false
                    }

                done

              } 2>&${fd_stderr}
            } 2>/dev/null

            exitTrapStr+='( printf '"'"'0\n'"'"' >&${fd_nAuto0}; ) {fd_nAuto0}>&'"${fd_nAuto}"'; '$'\n'
            exitTrapStr_kill+='kill -9 '"${pAuto_PID}"' 2>/dev/null; '$'\n'

        fi

        # set EXIT trap (dynamically determined based on which option flags were active)

        ${rmTmpDirFlag} && exitTrapStr_kill+='\rm -rf "'"${tmpDir}"'" 2>/dev/null; '$'\n'

        trap "${exitTrapStr}"$'\n'"${exitTrapStr_kill}" EXIT
        
        # # # # # DYNAMICALLY GENERATE COPROC SOURCE CODE # # # # #

        # populate {fd_continue} with an initial '\n'
        # {fd_continue} will act as an exclusive read lock (so lines from stdin are read atomically):
        #     when there is a '\n' the pipe buffer then nothing has a read lock
        #     a process reads 1 byte from {fd_continue} to get the read lock, and
        #     when that process writes a '\n' back to the pipe it releases the read lock

        # spawn $nProcs coprocs
        # on each loop, they will read {fd_continue}, which blocks them until they have exclusive read access
        # they then read N lines with mapfile and send \n to {fd_continue} (so the next coproc can start to read)
        # if the read array is empty the coproc will either continue or break, depending on if end conditions are met
        # finally it will do something with the data.
        #
        # NOTE: All coprocs share the same fd_read file descriptor ( accomplished via `( <...>; coproc p0 ...; <...> ;  coproc pN ...; ) {fd_read}<><(:)` )
        #       This has the benefit of keeping the coprocs in sync with each other - when one reads data the fd_read used by *all* of them is advanced.

        # generate coproc source code template (which, in turn, allows you to then spawn many coprocs very quickly)
        # this contains the code for the coprocs but has the worker ID ($kk) replaced with '%s' and '%' replaced with '%%'
        # the individual coproc's codes are then generated via source<<<"${coprocSrcCode//'{<#>}'/${kk}}"

        coprocSrcCode="""
{ coproc p{<#>} {
LC_ALL=C
LANG=C
IFS=
trap - EXIT
echo \"\${BASH_PID}\" >\"${tmpDir}\"/.run/p{<#>}
trap '\\rm -f \"${tmpDir}\"/.run/p{<#>}' EXIT
while true; do
$(${nLinesAutoFlag} && echo """
    \${nLinesAutoFlag} && read <\"${tmpDir}\"/.nLines && [[ -z \${REPLY//[0-9]/} ]] && nLinesCur=\${REPLY}
 """)
    read -u ${fd_continue}
    mapfile -n \${nLinesCur} -u $(${pipeReadFlag} && printf '%s ' ${fd_stdin} || printf '%s ' ${fd_read}; { ${pipeReadFlag} || ${nullDelimiterFlag}; } && printf '%s ' '-t'; ${nullDelimiterFlag} && printf '%s ' '-d '"''") A
$(${pipeReadFlag} || ${nullDelimiterFlag} || echo """
    [[ \${#A[@]} == 0 ]] || {
        [[ \"\${A[-1]: -1}\" == \$'\\n' ]] || {
            $(${verboseFlag} && echo """echo \"Partial read at: \${A[-1]}\" >&${fd_stderr}""")
            until read -r -u ${fd_read}; do A[-1]+=\"\${REPLY}\"; done
            A[-1]+=\"\${REPLY}\"\$'\\n'
            $(${verboseFlag} && echo """echo \"partial read fixed to: \${A[-1]}\" >&${fd_stderr}; echo >&${fd_stderr}""")
        }
"""
${nOrderFlag} && echo """
        read -u ${fd_nOrder} nOrder
"""
${pipeReadFlag} || ${nullDelimiterFlag} || echo """
    }
""")
    printf '\\n' >&${fd_continue};
    [[ \${#A[@]} == 0 ]] && {
        if [[ -f \"${tmpDir}\"/.done ]]; then
$(${nLinesAutoFlag} && echo """
            printf '\\n' >&\${fd_nAuto0}
""")
            [[ -f \"${tmpDir}\"/.quit ]] || : >\"${tmpDir}\"/.quit
$(${nOrderFlag} && echo """
            : >\"${tmpDir}\"/.out/.quit{<#>}
""")
            break
$(${inotifyFlag} && echo """
        else
            read -u ${fd_inotify} -t 0.1
""")
        fi
        continue
    }
$(${nLinesAutoFlag} && { printf '%s' """
    \${nLinesAutoFlag} && {
        printf '%s\\n' \${#A[@]} >&\${fd_nAuto0}
        (( \${nLinesCur} < ${nLinesMax} )) || nLinesAutoFlag=false
    }"""
    ${fallocateFlag} && printf '%s' ' || ' || echo
}
${fallocateFlag} && echo """printf '\\n' >&\${fd_nAuto0}
"""
${pipeReadFlag} || ${nullDelimiterFlag} || echo """
        { [[ \"\${A[*]##*\$'\\n'}\" ]] || [[ -z \${A[0]} ]]; } && {
            $(${verboseFlag} && echo """echo \"FIXING SPLIT READ\" >&${fd_stderr}""")
            A[-1]=\"\${A[-1]%\$'\\n'}\"
            IFS=
            mapfile A <<<\"\${A[*]}\"
        }
"""
${subshellRunFlag} && echo '(' || echo '{'
${exportOrderFlag} && echo 'printf '"'"'\034%s\035'"'"' "${nOrder}"'
)
    ${runCmd[@]} $(if ${stdinRunFlag}; then printf '<<<%s' "\"\${A[@]%\$'\\n'}\""; elif ! ${substituteStringFlag}; then printf '%s' "\"\${A[@]%\$'\\n'}\""; fi) $(${verboseFlag} && echo """ || {
        {
            printf '\\n\\n----------------------------------------------\\n\\n'
            echo 'ERROR DURING \"${runCmd[*]}\" CALL'
            declare -p A nLinesCur nLinesAutoFlag
            echo 'fd_read:'
            cat /proc/self/fdinfo/${fd_read}
            echo 'fd_write:'
            cat /proc/self/fdinfo/${fd_write}
            echo
        } >&${fd_stderr}
    }""")
$(${subshellRunFlag} && printf '%s' ')' || printf '%s' '}') ${outStr}
done
} 2>&${fd_stderr} {fd_nAuto0}>&${fd_nAuto}
} 2>/dev/null
p_PID+=(\${p{<#>}_PID})
"""

        # # # # # FORK COPROC "WORKERS" # # # # #

        printf '\n' >&${fd_continue};

        # source the coproc code for each coproc worker
        for (( kk=0 ; kk<${nProcs} ; kk++ )); do
            [[ -f "${tmpDir}"/.quit ]] && break
            source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/${kk}}"
        done
        
        # # # # # WAIT FOR THEM TO FINISH # # # # #
          #   #   PRINT OUTPUT IF ORDERED   #   #

        if ${nOrderFlag}; then
            outCur=10

            ${inotifyFlag} && {

                while true; do

                    read -r -u ${fd_inotify0}

                    [[ ${REPLY} == *\/x+([0-9]) ]] && outA[${REPLY%%*x}]=1

                    while [[ ${outA[${outCur}]} == 1 ]]; do

                        cat "${tmpDir}"/.out/x${outCur}
                        \rm  -f "${tmpDir}"/.out/x${outCur}
                        ((outCur++))
                        [[ "${outCur}" == +(9)+(0) ]] && outCur="${outCur}00"
                    done

                    [[ -f "${tmpDir}"/.quit ]] && break
                done
            }

            wait "${p_PID[@]}"

            [[ -f "${tmpDir}"/.out/x${outCur} ]] && cat "${tmpDir}"/.out/x*

        else

            # wait for everything to finish
            wait "${p_PID[@]}"

        fi

        # print final nLines count
        ${nLinesAutoFlag} && ${verboseFlag} && printf 'nLines (final) = %s   (max = %s)\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}" >&${fd_stderr}

    # open anonymous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_inotify}<><(:) {fd_inotify0}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>"${fPath}" {fd_stdout}>&1 {fd_stdin}<&0 {fd_stderr}>&2

}
