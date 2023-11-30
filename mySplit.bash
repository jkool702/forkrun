#!/usr/bin/env bash

shopt -s extglob

mySplit() (
## Efficiently parallelize a loop / run many tasks in parallel using bash coprocs
## NOTE: mySplit is an (in-development) re-write of forkrun that is faster, more efficient, and is less dependent on external dependencies
#
# USAGE:   printf '%s\n' "${args}" | mySplit [flags] [--] parFunc [args0]
#
#          Usage is vitrually identical to parallelizing a loop using `xargs -P` or  `parallel -m`:
#          source this file, then pass (newline-seperated) inputs to parallelize over on stdin and pass function name and initial arguments as function inputs.
#
# RESULT:  mySplit will run `parFunc [args0] ${line(s)} in parallel for each line (or group of N lines) that are given on stdin.
#
# EXAMPLE: find ./ -type f | mySplit sha256sum
#
# HOW IT WORKS: coproc code is dynamically generated based on passed mySplit options, then N coprocs are forked off. These coprocs will groups on lines from stdin using a shared fd and run them through the specified function in parallel.
#          Importantly, this means that you dont need to fork anything after the initial coprocs are set up...the same coprocs are active for the duration of mySplit, and are continuously piped new data to run.
#          This parallelization method is MUCH faster than traditional forking (esp. for many quick-to-run tasks)...On my hardware mySplit is 50-70% faster than  'xargs -P'  and 3x-5x faster than 'parallel -m'
#        { [[ \"\${A[*]##*\$'\\n'}\" ]] || [[ -z \${A[0]} ]]; } && {

# ONLY REQUIRED DEPENDENCY:   Bash 4+ (This is when coprocs were introduced)
#
# OPTIONAL DEPENDENCIES (to provide enhanced functionality):
#       Bash 5.1+                      : Bash arrays got a fairly major overhaul here, and in particular the mapfile command (which is used extensively to read data from the tmpfile containing stdin) got a major speedup here. Bash versions 4.x and 5.0 *should* still work, but will be (perhaps consideraably) slower.
#      `fallocate` --AND-- kernel 3.5+ : required to remove already-read data from in-memory tmpfile. Without both of these stdin will accumulate in the tmpfile and wont be cleared until mySplit is finished and returns (which, especially if stdin is being fed by a long-running process, could eventually result in very high memory use)
#      `inotifywait`                   : required to efficiently wait for stdin if it is arriving much slower than the coprocs are capable of processing it (e.g. `ping 1.1.1.1 | mySplit). Without this the coprocs will non-stop try to read data from stdin, causing unnecessairly high CPU usage.
#
# FLAGS: TBD
#
# <WORK IN PROGRESS>

############################ BEGIN FUNCTION ############################

    : "${LC_ALL:=C}" "${LANG:=C}"
    IFS=
    trap - EXIT INT TERM HUP QUIT

    shopt -s extglob
#    shopt -s varredir_close

    # make vars local
    local tmpDir fPath outStr exitTrapStr nOrder coprocSrcCode outCur tmpDirRoot a1 a2 inotifyFlag fallocateFlag nLinesAutoFlag substituteStringFlag substituteStringIDFlag nOrderFlag nullDelimiterFlag subshellRunFlag stdinRunFlag pipeReadFlag rmTmpDirFlag verboseFlag exportOrderFlag noFuncFlag unescapeFlag optParseFlag continueFlag fd_continue fd_inotify fd_inotify0 fd_inotify1 fd_inotify10 fd_nAuto fd_nOrder fd_read fd_write fd_stdout fd_stdin fd_stderr pWrite_PID pNotify_PID pNotify0_PID pNotify1_PID pNotify10_PID pOrder_PID pOrder1_PID pAuto_PID fd_read_pos fd_read_pos_old fd_write_pos
    local -i nLines nLinesCur nLinesNew nLinesMax nCur nRead nProcs nWait v9 kkMax kkCur kk
    local -a A Acur p_PID runCmd

    # check inputs and set defaults if needed
    [[ $# == 0 ]] && optParseFlag=false || optParseFlag=true
    while ${optParseFlag} && (( $# > 0  )) && [[ "$1" == [-+]* ]]; do
        case "${1}" in

            -?(-)j|-?(-)?(n)p?(roc?(s)))
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
                [[ -d ${tmpDirRoot} ]] || mkdir -p "${tmpDirRoot}"
                shift 1
            ;;

            -?(-)t?(mp?(?(-)dir))?([= ])*@([[:graph:]])*)
                tmpDirRoot="${1##@(-?(-)t?(mp?(?(-)dir))?([= ]))}"
                [[ -d ${tmpDirRoot} ]] || mkdir -p "${tmpDirRoot}"
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

            -?(-)P?(IPE)?(?(-)READ))
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

            +?([-+])P?(IPE)?(?(-)READ))
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

    # determine what mySplit is using lines on stdin for
    [[ ${FORCE} ]] && runCmd=("${@}") || runCmd=("${@//$'\r'/}")
    (( ${#runCmd[@]} > 0 )) || ${noFuncFlag} || runCmd=(printf '%s\n')

    # setup tmpdir
    [[ ${tmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && tmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && tmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && tmpDirRoot='/tmp'; } || tmpDirRoot="$(pwd)"
    tmpDir="$(mktemp -p "${tmpDirRoot}" -d .mySplit.XXXXXX)"
    fPath="${tmpDir}"/.stdin
    : >"${fPath}"


    {

        # dynamically set defaults for a few flags

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

        # require -k to use -n
        ${exportOrderFlag} && nOrderFlag=true

        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmTmpDirFlag:=true}" "${nLinesMax:=512}" "${nullDelimiterFlag:=false}" "${subshellRunFlag:=false}" "${stdinRunFlag:=false}" "${pipeReadFlag:=false}" "${substituteStringFlag:=false}" "${substituteStringIDFlag:=false}" "${exportOrderFlag:=false}" "${verboseFlag:=false}" "${noFuncFlag:=false}" "${unescapeFlag:=false}"

        # check for conflict in flags that were  defined on the commandline when mySplit was called
        ${pipeReadFlag} && ${nLinesAutoFlag} && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }

        # modify runCmd if '-i' '-I' or '-u' flags are set
        if ${unescapeFlag}; then
            ${substituteStringFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'{}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'{ID}'/'{<#>}'}")
            }
        else
            mapfile -t runCmd < <(printf '%q\n' "${@}")
            ${substituteStringFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'\{\}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                mapfile -t runCmd < <(printf '%s\n' "${runCmd[@]//'\{ID\}'/'{<#>}'}")
            }
        fi

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

        # if keeping tmpDir print its location to stderr
        ${rmTmpDirFlag} || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}

        # start building exit trap string
        : >"${tmpDir}"/.pid.kill

        ${verboseFlag} && {
            ${inotifyFlag} && echo 'using inotify'
            ${fallocateFlag} && echo 'using fallocate'
            ${nLinesAutoFlag} && echo 'automatically adjusting batch size (num lines per function call)'
            ${nOrderFlag} && echo 'ordering output the same as the input'
        } >&${fd_stderr}


        # spawn a coproc to write stdin to a tmpfile
        # After we are done reading all of stdin indicate this by touching .done
        if ${pipeReadFlag}; then
            : >"${tmpDir}"/.done
        else
            coproc pWrite {
                cat <&${fd_stdin} >&${fd_write}
                : >"${tmpDir}"/.done
                ${inotifyFlag} && {
                    { source /proc/self/fd/0 >&${fd_inotify0}; }<<<"printf '%.0s\n' {0..${nProcs}}"
                } {fd_inotify0}>&${fd_inotify}
                ${verboseFlag} && printf '\nINFO: pWrite has finished - all of stdin has been saved to the tmpfile at %s\n' "${fPath}" >&2
            } 2>&${fd_stderr}
            echo "${pWrite_PID}" >>"${tmpDir}"/.pid.kill
        fi

        # setup+fork inotifywait (if available)
        if ${inotifyFlag}; then
            {
                # initially add 1 newline for each coproc to fd_inotify
                { source /proc/self/fd/0 >&${fd_inotify0}; }<<<"printf '%.0s\n' {0..${nProcs}}"

                # run inotifywait
                inotifywait -q -m --format '' "${fPath}" >&${fd_inotify0} &
            } 2>/dev/null {fd_inotify0}>&${fd_inotify}

            pNotify_PID=${!}

#            exitTrapStr+='[[ -f "'"${fPath}"'" ]] && \rm -f "'"${fPath}"'"; '
            echo "${pNotify_PID}" >>"${tmpDir}"/.pid.kill
        fi

# setup (ordered) output. This uses the same naming scheme as `split -d` to ensure a simple `cat /path/*` always orders things correctly.
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'

            printf '%s\n' {10..89} >&${fd_nOrder}

            { coproc pOrder {

                printf '%s\n' {9000..9899} >&${fd_nOrder}

                # monitor ${tmpDir}/.out for new files if we have inotifywait
                ${inotifyFlag} && {
                    inotifywait -q -m -e create --format '' -r "${tmpDir}"/.out >&${fd_inotify10} &
                    pNotify1_PID=$!
                    echo ${pNotify1_PID} >>"${tmpDir}"/.pid.kill
                } 2>/dev/null


                # fork nested coproc to print outputs (in order) and then clear them in realtime as they show up in ${tmpDir}/.out
                { coproc pOrder1 {

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

                echo "${pOrder1_PID}" >>"${tmpDir}"/.pid.kill

                shopt -s extglob
                outCur=10
                continueFlag=true
                ${exportOrderFlag} && nCur=1
                
                if ${inotifyFlag}; then
                    trap 'continueFlag=false; echo >&'"${fd_inotify10}" USR1
                else
                    trap 'continueFlag=false' USR1
                fi

                while ${continueFlag}; do
                    # check if the next output file that needs to be printed is available (using inotifywait if possible)
                    ${inotifyFlag} && {
                        [[ -f "${tmpDir}"/.out/x${outCur} ]] || read -u ${fd_inotify1}
                    }

                    # at least 1 output file can be printed...do so and then delete it. repeat this for as long as the next (in order) output file is ready.
                    while [[ -f "${tmpDir}"/.out/x${outCur} ]]; do
                        if ${exportOrderFlag}; then
                            mapfile -t Acur <"${tmpDir}"/.out/x${outCur}
                            printf "$({ source /proc/self/fd/0; }<<<"printf '%s: %%s\n' {${nCur}..$(( ${nCur} + ${Acur[@]} - 1 ))}")" $(<"${Acur[@]}") >&${fd_stdout}
                            nCur=$(( ${nCur} + ${#Acur[@]} ))
                        else
                            echo "$(<"${tmpDir}"/.out/x${outCur}?(.+([0-9])))" >&${fd_stdout}
                        fi
                        \rm -f "${tmpDir}"/.out/x${outCur}?(.+([0-9]))
                        ((outCur++))
                        [[ "${outCur}" == +(9)+(0) ]] && outCur="${outCur}00"
                        [[ -f "${tmpDir}"/.quit ]] && break
                    done
                    ${exportOrderFlag} || {
                        [[ -f "${tmpDir}"/.quit ]] && continueFlag=false
                    }
                done

                kill -9 "${pNotify1_PID}" "${pOrder1_PID}" 2>/dev/null

              }  {fd_inotify10}>&${fd_inotify1}
            } 2>/dev/null

            exitTrapStr+='kill -USR1 '"${pOrder_PID}"' 2>/dev/null; wait '"${pOrder_PID}"'; '
        else

            outStr='>&'"${fd_stdout}";
        fi

        # setup nLinesAuto and/or fallocate truncation
        nLinesCur=${nLines}
        if ${nLinesAutoFlag} || ${fallocateFlag}; then

            # setup nLines indicator
            printf '%s\n' ${nLines} >"${tmpDir}"/.nLines

            # LOGIC FOR DYNAMICALLY SETTING 'nLines':
            # The avg_bytes_per_line is estimated by looking at the byte offset position of fd_read and having each coproc keep track of how many lines it has read
            # the new "proposed" 'nLines' is determined by estimating the average bytes per line, then taking the averge of the "current nLines" and "(numbedr unread bytes) / ( (avg bytes per line) * (nProcs) )"
            # --> if proposed new 'nLines' is greater than current 'nLines' then use it (use case: stdin is arriving fairly fast, increase 'nLines' to match the rate lines are coming in on stdin)
            # --> if proposed new 'nLines' is less than or equal to current 'nLines' ignore it (i.e., nLines can only ever increase...it will never decrease)
            # --> if the new 'nLines' is greater than or equal to 'nLinesMax' or the .quit file has appeared, then break after the current iteratrion is finished
            { coproc pAuto {
                trap 'nLinesAutoFlag=false; fallocateFlag=false; echo >&'"${fd_nAuto}" USR1

                ${fallocateFlag} && {
                    nWait=${nProcs}
                    fd_read_pos_old=0
                }
                ${nLinesAutoFlag} && nRead=0

                while ${fallocateFlag} || ${nLinesAutoFlag}; do

                    read -u ${fd_nAuto} -t 1
                    [[ ${REPLY} == 0 ]] && break
                    { [[ -z ${REPLY} ]] || [[ -f "${tmpDir}"/.quit ]]; } && nLinesAutoFlag=false

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
                                    fd_read_pos_old=${fd_read_pos}
                                }
                                nWait=${nProcs}
                            ;;
                            *)
                                ((nWait--))
                            ;;
                        esac
                    fi
                    [[ -f "${tmpDir}"/.quit ]] && fallocateFlag=false
                done

              } 2>&${fd_stderr}
            } 2>/dev/null

            exitTrapStr+='kill -USR1 '"${pAuto_PID}"' 2>/dev/null; '
            echo "${pAuto_PID}" >>"${tmpDir}"/.pid.kill

        fi

        # set EXIT trap (dynamically determined based on which option flags were active)
        exitTrapStr=': >"'"${tmpDir}"'"/.quit;
        : >"'"${tmpDir}"'"/.out.quit;
        '"${exitTrapStr}"'
         mapfile -t pidKill <"'"${tmpDir}"'"/.pid.kill;
         kill "${pidKill[@]}" 2>/dev/null;
         kill -9 "${pidKill[@]}" 2>/dev/null; '

        ${nOrderFlag} && exitTrapStr+='wait '${pOrder_PID}'; '
        ${rmTmpDirFlag} && exitTrapStr+='\rm -rf "'"${tmpDir}"'" 2>/dev/null; '
        trap "${exitTrapStr%'; '}" EXIT INT TERM HUP QUIT


        # populate {fd_continue} with an initial '\n'
        # {fd_continue} will act as an exclusive read lock (so lines from stdin are read atomically):
        #     when there is a '\n' the pipe buffer then nothing has a read lock
        #     a process reads 1 byte from {fd_continue} to get the read lock, and
        #     when that process writes a '\n' back to the pipe it releases the read lock
        printf '\n' >&${fd_continue};

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
: \"\${LC_ALL:=C}\" \"\${LANG:=C}\"
IFS=
trap - EXIT INT TERM HUP QUIT
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
            printf '0\\n' >&\${fd_nAuto0}
""")
            [[ -f \"${tmpDir}\"/.quit ]] || : >\"${tmpDir}\"/.quit
$(${nOrderFlag} && echo """
            : >\"${tmpDir}\"/.out/.quit{<#>}
""")
            break
$(${inotifyFlag} && echo """
        else
            read -u ${fd_inotify} -t 1
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
            mapfile A <<<\"\${A[*]}\"
        }
"""
${subshellRunFlag} && echo '(' || echo '{'
)
    ${runCmd[@]} $(${substituteStringFlag} || printf '%s' "\"\${A[@]%\$'\\n'}\"") $(${verboseFlag} && echo """ || {
        {
            printf '\\n\\n----------------------------------------------\\n\\n'
            echo 'ERROR DURING \"${runCmd[*]}\" CALL'
            declare -p A nLinesCur nLinesAutoFlag
            echo 'fd_read:'
            cat /proc/self/fdinfo/${fd_read}
            echo 'fd_write:'
            cat /proc/self/fdinfo/${fd_write}
            echo
        } >&2
    }""")
$(${subshellRunFlag} && printf '%s' ')' || printf '%s' '}') ${outStr}
done
} 2>&${fd_stderr} {fd_nAuto0}>&${fd_nAuto}
} 2>/dev/null
p_PID+=(\${p{<#>}_PID})
"""

#
#        { [[ \"\${A[*]##*\$'\\n'}\" ]] || [[ -z \${A[0]} ]]; } && {
#        printf -v a1 '%s' \"\${A[*]//*\$'\\n'/\$'\\034'}\"
#        printf -v a2 '%s\\034' \"\${A[@]##*}\"
#        [[ \"\${a1}\" == \"\${a2}\"  ]] || [[ \${A[0]} ]] || {
#

        # source the coproc code for each coproc worker
        for (( kk=0 ; kk<${nProcs} ; kk++ )); do
            [[ -f "${tmpDir}"/.quit ]] && break
            source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/${kk}}"
        done

        # wait for everything to finish
        wait "${p_PID[@]}"

        # print output if using ordered output
        ${nOrderFlag} &&{
            #wait ${pOrder_PID}
            cat "${tmpDir}"/.out/x* >&${fd_stdout}
        }

        # print final nLines count
        ${nLinesAutoFlag} && ${verboseFlag} && printf 'nLines (final) = %s   (max = %s)\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}" >&${fd_stderr}

    # open anonymous pipes + other misc file descriptors for the above code block
    } {fd_continue}<><(:) {fd_inotify}<><(:) {fd_inotify1}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>"${fPath}" {fd_stdout}>&1 {fd_stdin}<&0 {fd_stderr}>&2

)
