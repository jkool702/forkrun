#!/usr/bin/env bash
# shellcheck disable=SC2004,SC2015,SC2016,SC2028,SC2162 source=/dev/null

shopt -s extglob

forkrun() {
## Efficiently parallelize a loop / run many tasks in parallel *extremely* fast using bash coprocs
#
# USAGE: printf '%s\n' "${args[@]}" | forkrun [-flags] [--] parFunc ["${args0[@]}"]
#
# LIST OF FLAGS: [-j|-P <#>] [-t <path>] ( [-l <#>] | [-L <#[,#]>]] ) ( [-b <#>] | [-B <#>[,<#>]] ) [-d <char>] [-i] [-I] [-k] [-n] [-z|-0] [-s] [-S] [-p] [-D] [-N] [-u] [-v] [-h|-?]
#
# For help / usage info, call forkrun with one of the following flags:
#
# --usage              :  display brief usage info
# -? | -h | --help     :  dispay standard help (includes brief descriptions + short names for flags)
# --help=s[hort]       :  more detailed variant of '--usage'
# --help=f[lags]       :  display detailed info about flags (longer descriptions, short + long names)
# --help=a[ll]         :  display all help (includes detailed descriptions for flags)
#
# NOTE: the `?` may need too be escaped for `-?` to trigger the help (i.e., use `forkrun '-?'` or `forkrun -\?`)

############################ BEGIN FUNCTION ############################

    trap - EXIT INT TERM HUP

    shopt -s extglob

    # make all variables local
    local  tmpDir fPath outStr delimiterVal delimiterReadStr delimiterRemoveStr exitTrapStr exitTrapStr_kill nLines0 nOrder nBytes tTimeout coprocSrcCode outCur tmpDirRoot returnVal tmpVar t0 trailingNullFlag inotifyFlag fallocateFlag nLinesAutoFlag substituteStringFlag substituteStringIDFlag nOrderFlag readBytesFlag readBytesExactFlag readBytesProg nullDelimiterFlag subshellRunFlag stdinRunFlag pipeReadFlag rmTmpDirFlag exportOrderFlag noFuncFlag unescapeFlag optParseFlag continueFlag doneIndicatorFlag FORCE_allowCarriageReturnsFlag fd_continue fd_inotify fd_inotify0 fd_nAuto fd_nAuto0 fd_nOrder fd_nOrder0 fd_read fd_write fd_stdout fd_stdin fd_stderr pWrite_PID pNotify_PID pOrder_PID pAuto_PID fd_read_pos fd_read_pos_old fd_write_pos DEBUG_FORKRUN
    local -i nLines nLinesCur nLinesNew nLinesMax nRead nProcs nWait nOrder0 nBytesRead v9 kkMax kkCur kk verboseLevel
    local -a A p_PID runCmd outHave

    # # # # # PARSE OPTIONS # # # # #

    : "${verboseLevel:=0}" "${returnVal:=0}"

    # check inputs and set defaults if needed
    [[ $# == 0 ]] && optParseFlag=false || optParseFlag=true
    while ${optParseFlag} && (( $# > 0  )) && [[ "$1" == [-+]* ]]; do
        case "${1}" in

            -?(-)@([jP]|?(n)[Pp]roc?(s)?)?(?([= ])+([0-9])))
                if [[ "${1}" == -?(-)@([jP]|?(n)[Pp]roc?(s)?)?([= ])+([0-9]) ]]; then
                    nProcs="${1##@(-?(-)@([jP]|?(n)[Pp]roc?(s)?)?([= ]))}"
                elif [[ "${1}" == -?(-)@([jP]|?(n)[Pp]roc?(s)?) ]] && [[ "$2" == +([0-9]) ]]; then
                    nProcs="${2}"
                    shift 1
                fi
            ;;

            -?(-)?(n)l?(ine?(s))?(?([= ])+([0-9])))
                if [[ "${1}" == -?(-)?(n)l?(ine?(s))?([= ])+([0-9]) ]]; then
                    nLines="${1##@(-?(-)?(n)l?(ine?(s))?([= ]))}"
                    nLinesAutoFlag=false
                elif [[ "${1}" == -?(-)?(n)l?(ine?(s)) ]] && [[ "$2" == +([0-9]) ]]; then
                    nLines="${2}"
                    nLinesAutoFlag=false
                    shift 1
                fi
            ;;

            -?(-)?(N)L?(INE?(S))?(?([= ])+([0-9])?(,+([0-9]))))
                if [[ "${1}" == -?(-)?(N)L?(INE?(S))?([= ])+([0-9])?(,+([0-9])) ]]; then
                    nLines0="${1##@(-?(-)?(N)L?(INE?(S))?([= ]))}"
                    nLinesAutoFlag=true
                elif [[ "${1}" == -?(-)?(N)L?(INE?(S)) ]] && [[ "$2" == +([0-9])?(,+([0-9])) ]]; then
                    nLines0="${2}"
                    nLinesAutoFlag=true
                    shift 1
                else
                    continue
                fi
                if [[ "${nLines0}" == +([0-9])','+([0-9]) ]]; then
                    nLinesMax="${nLines0##*,}"
                    nLines="${nLines0%%,*}"
                else
                    nLines="${nLines0}"
                fi
            ;;

            -?(-)b?(yte?(s))?(?([= ])+([0-9])?([KkMmGgTtPp])?(i)?([Bb])))
                if [[ "${1}" == -?(-)b?(yte?(s))?([= ])+([0-9])?([KkMmGgTtPp])?(i)?([Bb]) ]]; then
                    nBytes="${1##@(+([0-9])?([KkMmGgTtPp])?(i)?([Bb]))}"
                    readBytesFlag=true
                    readBytesExactFlag=false
                elif [[ "${1}" == -?(-)b?(yte?(s)) ]] && [[ "$2" == +([0-9])?([KkMmGgTtPp])?(i)?([Bb]) ]]; then
                    nBytes="${2}"
                    readBytesFlag=true
                    readBytesExactFlag=false
                    shift 1
                fi
            ;;

            -?(-)B?(YTE?(S))?(?([= ])+([0-9])?([KkMmGgTtPp])?(i)?([Bb])?(,+([0-9])?(.+([0-9])))))
                if [[ "${1}" == -?(-)B?(YTE?(S))?([= ])+([0-9])?([KkMmGgTtPp])?(i)?([Bb])?(,+([0-9])?(.+([0-9]))) ]]; then
                    nBytes="${1##@(+([0-9])?([KkMmGgTtPp])?(i)?([Bb])?(,+([0-9])?(.+([0-9]))))}"
                    readBytesFlag=true
                    readBytesExactFlag=true
                elif [[ "${1}" == -?(-)B?(YTE?(S)) ]] && [[ "$2" == +([0-9])?([KkMmGgTtPp])?(i)?([Bb])?(,+([0-9])?(.+([0-9]))) ]]; then
                    nBytes="${2}"
                    readBytesFlag=true
                    readBytesExactFlag=true
                    shift 1
                fi
            ;;

            -?(-)t?(mp?(?(-)dir))?(?([= ])*@([[:graph:]])*))
                if [[ "${1}" == -?(-)t?(mp?(?(-)dir))?([= ])*@([[:graph:]])* ]]; then
                    tmpDirRoot="${1##@(-?(-)t?(mp?(?(-)dir))?([= ]))}"
                    mkdir -p "${tmpDirRoot}"
                elif [[ "${1}" == -?(-)t?(mp?(?(-)dir)) ]] && [[ "$2" == *@([[:graph:]])* ]]; then
                    tmpDirRoot="${2}"
                    mkdir -p "${tmpDirRoot}"
                    shift 1
                fi
            ;;

            -?(-)d?(elim?(iter))?(?([= ])@([[:graph:]])*))
                if [[ "${1}" == -?(-)d?(elim?(iter))?([= ])@([[:graph:]])* ]]; then
                    delimiterVal="${1##@(-?(-)d?(elim?(iter))?([= ]))}"
                    (( ${#delimiterVal} > 1 )) && printf '\nWARNING: the delimiter must be a single character, and a multi-character string was given. Only using the 1st character.\n\n' >&2
                    (( ${#delimiterVal} == 0 )) && nullDelimiterFlag=true || delimiterVal="${delimiterVal:0:1}"
                elif [[ "${1}" == -?(-)d?(elim?(iter)) ]] && [[ "$2" == @([[:graph:]])* ]]; then
                    (( ${#2} > 1 )) && printf '\nWARNING: the delimiter must be a single character, and a multi-character string was given. Only using the 1st character.\n\n' >&2
                    (( ${#2} == 0 )) && nullDelimiterFlag=true || delimiterVal="${2:0:1}"
                    shift 1
                fi
            ;;

            [+-]?([+-])i?(nsert))
                [[ "${1:0:1}" == '-' ]] && substituteStringFlag=true || substituteStringFlag=false
            ;;

            [+-]?([+-])@(I?(D)|INSERT?(?(-)ID)))
                [[ "${1:0:1}" == '-' ]] && substituteStringIDFlag=true || substituteStringIDFlag=false
            ;;

            [+-]?([+-])k?(eep?(?(-)order)))
                [[ "${1:0:1}" == '-' ]] && nOrderFlag=true || nOrderFlag=false
            ;;

            [+-]?([+-])@(0|z?(ero)|null))
                [[ "${1:0:1}" == '-' ]] && nullDelimiterFlag=true || nullDelimiterFlag=false
            ;;

            [+-]?([+-])s?(ub)?(?(-)shell)?(?(-)run))
                [[ "${1:0:1}" == '-' ]] && subshellRunFlag=true || subshellRunFlag=false
            ;;

            [+-]?([+-])@(S|[Ss]tdin?(?(-)run)))
                [[ "${1:0:1}" == '-' ]] && stdinRunFlag=true || stdinRunFlag=false
            ;;

            [+-]?([+-])p?(ipe)?(?(-)read))
                [[ "${1:0:1}" == '-' ]] && pipeReadFlag=true || pipeReadFlag=false
            ;;

            [+-]?([+-])@(D|[Dd]elete))
                [[ "${1:0:1}" == '-' ]] && rmTmpDirFlag=true || rmTmpDirFlag=false
            ;;

            [+-]?([+-])n?(umber)?(-)?(line?(s)))
                [[ "${1:0:1}" == '-' ]] && exportOrderFlag=true || exportOrderFlag=false
            ;;

            [+-]?([+-])@(N?(O)|[Nn][Oo]?(-)func))
                [[ "${1:0:1}" == '-' ]] && noFuncFlag=true || noFuncFlag=false
            ;;

            [+-]?([+-])u?(nescape))
                [[ "${1:0:1}" == '-' ]] && unescapeFlag=true || unescapeFlag=false
            ;;

            [+-]?([+-])@(+(v)|verbose))
                case "${1}" in
                    [+-]?([+-])verbose)
                        [[ "${1:0:1}" == '-' ]] && ((verboseLevel++)) || ((verboseLevel--))
                    ;;
                    [+-]?([+-])+(v))
                       tmpVar="${1##+([+-])}"
                       [[ "${1:0:1}" == '-' ]] && verboseLevel=$(( ${verboseLevel} + ${#tmpVar} )) || verboseLevel=$(( ${verboseLevel} - ${#tmpVar} )) 
                       unset tmpVar
                    ;;
                esac
            ;;
            
            -?(-)help?(=@(a?(ll)|f?(lag?(s))|s?(hort)))|-?(-)usage|-?(-)[h?])
                forkrun_displayHelp "${1}"
                return 0
            ;;

            --)
                optParseFlag=false
            ;;

            @([-+])?([-+])*@([[:graph:]])*)
                printf '\nERROR: FLAG "%s" NOT RECOGNIZED. ABORTING.\n\nNOTE: If this flag was intended for the code being parallelized: then:\n1. ensure all flags for forkrun come first\n2. pass '"'"'--'"'"' to denote where forkrun flag parsing should stop.\n\nUSAGE INFO:' "$1" >&2

                forkrun_displayHelp --usage
                returnVal=1
                return 1
            ;;

            *)
                optParseFlag=false
                break
            ;;

        esac

        shift 1
        [[ ${#} == 0 ]] && optParseFlag=false

    done

    [ -t 0 ] && {
        printf '\n\nERROR: STDIN is a terminal. \n\nforkrun requires STDIN to be a pipe \n(containing the inputs to parallelize over); e.g.: \n\nprintf '"'"'%%s\\n'"'"' "${args[@]}" | forkrun parFunc \n\nABORTING! \n\n'
        returnVal=1
        return 1
    }
    

    # # # # # SETUP TMPDIR # # # # #

    [[ ${tmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && tmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && tmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && tmpDirRoot='/tmp'; } || tmpDirRoot="$(pwd)"

    tmpDir="$(mktemp -p "${tmpDirRoot}" -d .forkrun.XXXXXX)"
    fPath="${tmpDir}"/.stdin

    mkdir -p "${tmpDir}"/.run
    : >"${fPath}"

    # # # # # BEGIN MAIN SUBSHELL # # # # #

    # several file descriptors are opened for use by things running in this subshell. See closing`)` near the end of this function.
    (

        # implement DEBUG functionality if DEBUG set as an environment variable
        [[ ${DEBUG_FORKRUN} ]] && { source /proc/self/fd/0; } <<<"${DEBUG_FORKRUN}"

        # NOTE: this DEBUG is an intentionally undocumented "easter egg". Using this with zero understanding of the forkrun source code is dangerous, so you have to actually browse through the source to find its documentation
        #
        # USAGE:    `printf '%s\n' "${args@]}" | DEBUG_FORKRUN="${cmdStr}" forkrun [...]`
        #
        # EFFECT:  `${cmdStr}` will be sourced at the start of forkrun's main subshell (so as to not have any effect the parent/caller shell after forkrun is finished running)
        #
        # INTENDED PURPOSE: to allow someone (with working knowledge of forkrun's code) to overwrite automatically set variables with custom values, set custom shopt/set flags, implement a "run-once setup script" that must be run from within forkrun's main subshell, etc.
        #
        # EXAMPLE 1:  DEBUG_FORKRUN='set -xv'             -->    enable debug output to stderr as forkrun runs;   
        # EXAMPLE 2:  DEBUG_FORKRUN='inotifyFlag=false'   -->    prevent using inotifywait, even if the inotifywait binary is available.
        
        # # # # # INITIAL SETUP # # # # #

        export LC_ALL=C
        export LANG=C
        export IFS=
        #umask 177

        shopt -s nullglob

        # dynamically set defaults for a few flags
        : "${noFuncFlag:=false}" "${FORCE_allowCarriageReturnsFlag:=false}" "${readBytesFlag:=false}" "${readBytesExactFlag:=false}" "${nullDelimiterFlag:=false}"

        # determine what forkrun is using lines on stdin for
        if ${FORCE_allowCarriageReturnsFlag}; then
            # NOTE: allowing carriage returns in parFunC (or its initial args) is DANGEROUS. Dont do this unless you know what you are doing.
            # As such, `FORCE_allowCarriageReturnsFlag` can only be enabled (set to `true`) using the DEBUG_FORKRUN environment variable
            runCmd=("${@}") 
        else
            runCmd=("${@//$'\r'/}")
        fi
        (( ${#runCmd[@]} > 0 )) || ${noFuncFlag} || runCmd=(printf '%s\n')
        (( ${#runCmd[@]} > 0 )) && noFuncFlag=false
        ${noFuncFlag} && runCmd=('source' '/proc/self/fd/0')
        hash "${runCmd[0]}"

        # setup byte reading if passed -b or -B
        
        if ${readBytesFlag}; then
            # turn off nLinesAuto
            nLinesAutoFlag=false

            # turn on passing data via stdin (to prevent mangling NULL's in binary data) by default when byte splitting
            : "${stdinRunFlag:=true}"

            # parse read size (in bytes)
            nBytes="${nBytes,,}"
            nBytes="${nBytes//' '/}"

            [[ "${nBytes}" == +([0-9])?([KkMmGgTtPp])?(i)?([Bb]),+([0-9])?(.+([0-9])) ]] && {
                tTimeout="${nBytes##*,}"
                [[ "${tTimeout}" == +([0-9]).*([0-9]) ]] && { tTimeout="${tTimeout%%.*}"; ((tTimeout++)); }
                nBytes="${nBytes%,*}"
            }

            nBytes="${nBytes%b}"
            [[ "${nBytes}" == +([0-9])@([kmgtp])?(i) ]] && {
                local -A nBytesParser=([k]=1 [m]=2 [g]=3 [t]=4 [p]=5)

                if [[ ${nBytes: -1:1} == 'i' ]]; then
                    nBytes="$(( ${nBytes%[kmgtp]i} * ( 1024 ** ${nBytesParser[${nBytes: -2:1}]} ) ))"
                else
                    nBytes="$(( ${nBytes%[kmgtp]} * ( 1000 ** ${nBytesParser[${nBytes: -1:1}]} ) ))"
                fi
            }

            # make sure nBytes is only digits
            [[ "${nBytes//[0-9]/}" ]] && (( ${verboseLevel} >= 0 )) && { 
                printf '\nERROR: the byte count passed to the ( -b | -B ) flag did not parse correctly. \nThis must consist solely of numbers, optionally followed by a standard si prefix. \nVALID EXAMPLES:  4  8b  16k  32mb  64G  128TB  256PiB \nNOTE: the count is always in bytes, never in bits, regardless of the case of the (optional) trailing "b" / "B"\n\n' >&${fd_stderr}; 
                returnVal=1
                return 1
            }

            # check for incompatible flags
            { ${nullDelimiterFlag} || [[ ${delimiterVal} ]] || [[ ${delimiterRemoveStr} ]]; } && (( ${verboseLevel} >= 0 )) && {
                (( ${verboseLevel} >= 0 )) && printf '\nWARNING: The flag to use a null or a custom delimiter (-z | -0 | -d <delim> ) and the flag to read by byte count ( -b | -B ) were both passed.\nThere are no delimiters required when reading by bytes, so the delimiter flag will be unset and ignored\n\n' >&${fd_stderr}; 
                nullDelimiterFlag=false
                unset delimiterVal delimiterRemoveStr
            }

            # check for GNU dd or (if unavailable) check for head (either GNU or busybox)
            [[ ${readBytesProg} ]] || {
                if type -p dd &>/dev/null && dd --version | grep -qF 'coreutils'; then
                    readBytesProg='dd'
                elif type -p head &>/dev/null; then
                    readBytesProg='head'
                else
                    readBytesProg='bash'
                    (( ${verboseLevel} >= 0 )) && printf '\nWARNING: neither "dd (GNU)" nor "head" are available. The `read` builtin will be used by the worker coprocs to read data. forkrun will run considerably slower. \n\n' >&${fd_stderr}; 
                fi
            }
            ${stdinRunFlag} || (( ${verboseLevel} < 0 )) || printf '\nWARNING: data will be passed to coprocs via bash variables, which will drop NULLs and will probably mangle binary data (text data should still work). \nIt is not recommended to use the `+S` flag to prevent passing data to the coprocs stdin\n\n' >&${fd_stderr}; 

            # TEMP FIX - force readBytesExactFlag if using bash and stdinRunFlag. Otherwise it gets stuck somewhere :/
            [[ ${readBytesProg} == 'bash' ]] && ${stdinRunFlag} && readBytesExactFlag=true

            # read from pipe for -B if using dd/head. also dont need inotifywait
            if ${readBytesExactFlag} && ! { [[ ${readBytesProg} == 'bash' ]] && ${stdinRunFlag}; }; then  
                pipeReadFlag=true
                inotifyFlag=false
            else
                pipeReadFlag=false
            fi

             [[ ${readBytesProg} == 'bash' ]] || hash "${readBytesProg}"

        else
            # set batch size
            { [[ ${nLines} ]]  && (( ${nLines} > 0 )) && : "${nLinesAutoFlag:=false}"; } || : "${nLinesAutoFlag:=true}"
            { [[ -z ${nLines} ]] || [[ ${nLines} == 0 ]]; } && nLines=1
        fi

        # set number of coproc workers
        { [[ ${nProcs} ]]  && (( ${nProcs} > 0 )); } || nProcs=$({ type -a nproc &>/dev/null && nproc; } || { type -a grep &>/dev/null && grep -cE '^processor.*: ' /proc/cpuinfo; } || { mapfile -t tmpA  </proc/cpuinfo && tmpA=("${tmpA[@]//processor*/$'\034'}") && tmpA=("${tmpA[@]//!($'\034')/}") && tmpA=("${tmpA[@]//$'\034'/1}") && tmpA="${tmpA[*]}" && tmpA="${tmpA// /}" && echo ${#tmpA}; } || printf '8')

        # if reading 1 line at a time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmTmpDirFlag:=true}" "${nLinesMax:=512}" "${subshellRunFlag:=false}" "${pipeReadFlag:=false}" "${substituteStringFlag:=false}" "${substituteStringIDFlag:=false}" "${exportOrderFlag:=false}" "${unescapeFlag:=false}" "${stdinRunFlag:=false}" 
        doneIndicatorFlag=false

        # check for inotifywait
        type -a inotifywait &>/dev/null && ! ${pipeReadFlag} && : "${inotifyFlag:=true}" || : "${inotifyFlag:=false}"

        # check for fallocate
        type -a fallocate &>/dev/null && ! ${pipeReadFlag} && : "${fallocateFlag:=true}" || : "${fallocateFlag:=false}"

        # check for conflict in flags that were  defined on the commandline when forkrun was called
        ${pipeReadFlag} && ${nLinesAutoFlag} && (( ${verboseLevel} >= 0 )) && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }

        # require -k to use -n
        ${exportOrderFlag} && nOrderFlag=true

        # setup delimiter
        ${readBytesFlag} || {
            if ${nullDelimiterFlag}; then
                delimiterReadStr="-d ''"
            elif [[ -z ${delimiterVal} ]]; then
                delimiterVal='$'"'"'\n'"'"
                ${noFuncFlag} || delimiterRemoveStr='%$'"'"'\n'"'"
            else
                delimiterVal="$(printf '%q' "${delimiterVal}")"
                 ${noFuncFlag} && delimiterRemoveStr='//'"{delimiterVal}"'/\$'"'"'\n'"'" || delimiterRemoveStr="%${delimiterVal}"
                delimiterReadStr="-d ${delimiterVal}"
            fi
        }

        # modify runCmd if '-i' '-I' or '-u' flags are set
        if ${unescapeFlag}; then
            ${substituteStringFlag} && {
                runCmd=("${runCmd[@]//'{}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                runCmd=("${runCmd[@]//'{ID}'/'{<#>}'}")
                ${nOrderFlag} && runCmd=("${runCmd[@]//'{IND}'/'${nOrder0}'}")
            }
        else
            mapfile -t runCmd < <(printf '%q\n' "${runCmd[@]}")
            ${substituteStringFlag} && {
                runCmd=("${runCmd[@]//'\{\}'/'"${A[@]%$'"'"'\n'"'"'}"'}")
            }
            ${substituteStringIDFlag} && {
                runCmd=("${runCmd[@]//'\{ID\}'/'{<#>}'}")
                ${nOrderFlag} && runCmd=("${runCmd[@]//'\{IND\}'/'${nOrder0}'}")
            }
        fi

        nLinesCur=${nLines}

        mkdir -p "${tmpDir}"/.run

        # if keeping tmpDir print its location to stderr
        ${rmTmpDirFlag} || (( ${verboseLevel} <= 0 )) || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}

        (( ${verboseLevel} > 0 )) && {
            printf '\n\n------------------- FLAGS INFO -------------------\n\nCOMMAND TO PARALLELIZE: %s\n' "$(printf '%s ' "${runCmd[@]}")"
            ${inotifyFlag} && echo 'using inotify to efficiently wait for slow inputs on stdin'
            ${fallocateFlag} && echo 'using fallocate to shrink the tmpfile containing stdin as forkrun runs'
            printf '(-j|-P) using %s coproc workers\n' ${nProcs}
            ${nLinesAutoFlag} && printf '(-L) automatically adjusting batch size (lines per function call). initial = %s line(s). maximum = %s line(s).\n' "${nLines}" "${nLinesMax}"
            printf '(-t) forkrun tmpdir will be under %s\n' "${tmpDirRoot}"
            ${readBytesFlag} && printf '(-%s) data will be read in chunks of %s %s bytes using %s\n' "$(${readBytesExactFlag} && echo 'B' || echo 'b')" "$(${readBytesExactFlag} && echo 'exactly' || echo 'up to')" "${nBytes}" "${readBytesProg}"
            ${nOrderFlag} && echo '(-k) output will be ordered the same as if the inputs were run sequentially'
            ${exportOrderFlag} && echo '(-n) output batches will be numbered (index is per-batch, denoted using \\034<IND>:\\035\\n)'
            ${substituteStringFlag} && echo '(-i) replacing {} with lines from stdin'
            ${substituteStringIDFlag} && printf '%s %s\n' '(-I) replacing {ID} with coproc worker ID' "$(${nOrderFlag} && echo 'and replacing {IND} with output order INDex')"
            ${unescapeFlag} && echo '(-u) not escaping special characters in ${runCmd}'
            ${pipeReadFlag} && echo '(-p) worker coprocs will read directly from stdin pipe, not from a tmpfile'
            if ${nullDelimiterFlag}; then
                echo '((-0|-z)|(-d)) stdin will be parsed using nulls as delimiter (instead of newlines)'
            else
                printf '(%s) delimiter: %q\n' "$([[ "${delimiterVal}" == '$'"'"'\n'"'" ]] && echo '--' || echo '-d')" "${delimiterVal}"
            fi
            ${rmTmpDirFlag} || printf '(-r) tmpdir (%s) will NOT be automatically removed\n' "${tmpDir}"
            ${subshellRunFlag} && echo '(-s) coproc workers will run each group of N lines in a subshell'
            ${stdinRunFlag} && echo '(-S) coproc workers will pass lines to the command being parallelized via the command'"'"'s stdin'
            ${noFuncFlag} && echo '(-N) no function mode enabled: commands should be included in stdin' || printf 'tmpdir: %s\n' "${tmpDir}"
            echo "(-v) Verbosity Level: ${verboseLevel}"
            printf '\n------------------------------------------\n\n'
        } >&${fd_stderr}

        # # # # # FORK "HELPER" PROCESSES # # # # #

        # start building exit trap string
        exitTrapStr=': >"'"${tmpDir}"'"/.done;
: >"'"${tmpDir}"'"/.quit;
[[ -z $(echo "'"${tmpDir}"'"/.run/p*) ]] || kill $(cat "'"${tmpDir}"'"/.run/p* 2>/dev/null) 2>/dev/null; '$'\n'

       ${pipeReadFlag} && {
            # '.done'  file makes no sense when reading from a pipe
            : >"${tmpDir}"/.done
        } || {
            # spawn a coproc to write stdin to a tmpfile
            # After we are done reading all of stdin indicate this by touching .done
            { coproc pWrite {
                cat <&${fd_stdin} >&${fd_write}
                : >"${tmpDir}"/.done
                (( ${verboseLevel} > 1 )) && printf '\nINFO: pWrite has finished - all of stdin has been saved to the tmpfile at %s\n' "${fPath}" >&${fd_stderr}
                ${inotifyFlag} && {
                    for (( kk=0 ; kk<=nProcs ; kk++ )); do
                        : >&${fd_write}
                    done
                }
              }
            }
            exitTrapStr_kill+='kill -9 '"${pWrite_PID}"' 2>/dev/null; '$'\n'
        }

        # setup (ordered) output. This uses the same naming scheme as `split -d` to ensure a simple `cat /path/*` always orders things correctly.
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'

            printf '%s\n' {10..89} >&${fd_nOrder}

            # fork coproc to populate a pipe (fd_nOrder) with ordered output file name indicies for the worker copropcs to use
            { coproc pOrder {

                # generate enough nOrder indices (~10000) to fill up 64 kb pipe buffer
                # start at 10 so that bash wont try to treat x0_ as an octal
                printf '%s\n' {9000..9899} {990000..998999} >&${fd_nOrder}

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
                    nWait=$(( 16 + ( ${nProcs} / 2 ) ))
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
                            (( ${verboseLevel} > 2 )) && printf '\nCHANGING nLines from %s to %s!!!  --  ( nRead = %s ; write pos = %s ; read pos = %s )\n' ${nLinesCur} ${nLinesNew} ${nRead} ${fd_write_pos} ${fd_read_pos} >&${fd_stderr}

                            nLinesCur=${nLinesNew}
                        }
                    fi

                    if ${fallocateFlag}; then
                        case ${nWait} in
                            0)
                                fd_read_pos=$(( 4096 * ( ${fd_read_pos} / 4096 ) ))
                                (( ${fd_read_pos} > ${fd_read_pos_old} )) && {
                                    fallocate -p -o ${fd_read_pos_old} -l $(( ${fd_read_pos} - ${fd_read_pos_old} )) "${fPath}"
                                    (( ${verboseLevel} > 2 )) && echo "Truncating $(( ${fd_read_pos} - ${fd_read_pos_old} )) bytes off the start of the tmp file storing stdin" >&${fd_stderr}
                                    fd_read_pos_old=${fd_read_pos}
                                }
                                nWait=$(( 16 + ( ${nProcs} / 2 ) ))
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

        # setup+fork inotifywait (if available)
        ${inotifyFlag} && {
            {
                # initially add 1 newline for each coproc to fd_inotify
                { source /proc/self/fd/0 >&${fd_inotify0}; }<<<"printf '%.0s\n' {0..${nProcs}}"

                # run inotifywait
                inotifywait -q -m --format '' "${fPath}" >&${fd_inotify0} &

                pNotify_PID=${!}
            } 2>/dev/null {fd_inotify0}>&${fd_inotify}


            exitTrapStr+=': > "'"${tmpDir}"'"/.stdin; '$'\n'
            ${nOrderFlag} && exitTrapStr+=': >"'"${tmpDir}"'"/.out/.quit; '$'\n'
            exitTrapStr_kill+='kill -9 '"${pNotify_PID}"' 2>/dev/null; '$'\n'
        }

        # set EXIT trap (dynamically determined based on which option flags were active)

        ${rmTmpDirFlag} && exitTrapStr_kill+='\rm -rf "'"${tmpDir}"'" 2>/dev/null; '$'\n'

        trap "${exitTrapStr}"$'\n'"${exitTrapStr_kill}"$'\n''return ${returnVal}' EXIT
        trap 'kill "${p_PID[@]}" 2>/dev/null'$'\n''returnVal=1'$'\n''return 1' INT TERM HUP

        (( ${verboseLevel} > 1 )) && printf '\n\nALL HELPER COPROCS FORKED\n\n' >&${fd_stderr}
        (( ${verboseLevel} > 3 )) && printf '\n\nEXIT TRAP:\n\n%s\n\n' "${exitTrapStr}" >&${fd_stderr}


        # # # # # DYNAMICALLY GENERATE COPROC SOURCE CODE # # # # #

        # Due to how the coproc code is dynamically generated and sourced, it cannot directly contain comments. A very brief overview of their function is below.
        #
        # on each loop, they will acquire a read lock by read {fd_continue}, which blocks them until they have exclusive read access
        # they then read N lines with mapfile and check/fix a partial read (or read N bytes with $readBytesProg) and (if -k/-n) read the output order from {fd_nOrder}
        # they then release the read lock by sending \n to {fd_continue} (so the next coproc can start to read)
        # if no data was read, the coproc will either wait/continue or break, depending on if end conditions are met
        # finally (assuming it read data) it will run it through whatever is being parallelized. If -k/-n write [x]$nOrder to {fd_nOrder0} to indicate that index has run / was empty
        #
        # NOTE: All coprocs share the same {fd_read} file descriptor ( defined just after the end of the main forkrun subshell )
        #       This has the benefit of keeping the coprocs in sync with each other - when one reads data the {fd_read} used by *all* of them is advanced.

        # generate coproc source code template (which, in turn, allows you to then spawn many coprocs very quickly and have many "code branch selection" decisions already resolved)
        # this contains the code for the coprocs but has the worker ID represented using {<#>}. coprocs will be sourced via source<<<"${coprocSrcCode//'{<#>}'/${kk}}"
        #
        # NOTE: because the (uncommented) coproc code generation dynamically adapts to all of forkrun's possible options, this part is...well...hard to follow. 
        # To see the resulting coproc code for a given set of forkrun options, run:   `echo | forkrun -vvvv <FLAGS> :`

        coprocSrcCode="$( echo """
{ coproc p{<#>} {
LC_ALL=C
LANG=C
IFS=
export LC_ALL LANG IFS
trap - EXIT
echo \"\${BASH_PID}\" >\"${tmpDir}\"/.run/p{<#>}
trap '\\rm -f \"${tmpDir}\"/.run/p{<#>}' EXIT
while true; do"""
${nLinesAutoFlag} && echo "\${nLinesAutoFlag} && read <\"${tmpDir}\"/.nLines && [[ \${REPLY} == +([0-9]) ]] && nLinesCur=\${REPLY}"
echo """
    read -u ${fd_continue}
    [[ -f \"${tmpDir}\"/.quit ]] && {
        printf '\n' >&${fd_continue}
        break
    }
    [[ -f \"${tmpDir}\"/.done ]] && doneIndicatorFlag=true"""
if ${readBytesFlag}; then
    case "${readBytesProg}" in
        'dd')
            printf 'dd bs=32768 count=%sB of="%s"/.stdin.tmp.{<#>} 2>"%s"/.stdin.tmp-status.{<#>} ' "${nBytes}" "${tmpDir}" "${tmpDir}"
            ${pipeReadFlag} && printf 'iflag=fullblock <&%s\n' "${fd_stdin}" || printf '<&%s\n' "${fd_read}"
            printf '[[ "$(<"%s"/.stdin.tmp-status.{<#>})" == *$'"'"'\\n'"'"'"0 bytes"* ]] && A=() || A[0]=1\n' "${tmpDir}"
        ;;
        'head')
            printf 'head -c %s ' "${nBytes}"
            ${pipeReadFlag} && printf '<&%s ' "${fd_stdin}" || printf '<&%s ' "${fd_read}"
            printf '>"%s"/.stdin.tmp.{<#>}\n' "${tmpDir}"
            printf '[[ $(<"%s"/.stdin.tmp.{<#>}) ]] 2>/dev/null && A[0]=1 || A=()\n' "${tmpDir}"
        ;;
        'bash')
          if ${stdinRunFlag}; then
            [[ ${tTimeout} ]] && echo "SECONDS=0"
            printf 'if read -r -d '"''"' -n %s -u %s' "${nBytes}" "${fd_read}"
            [[ ${tTimeout} ]] && printf ' -t %s' "${tTimeout}"
            echo """; then
                [[ \${REPLY} ]] && A=(\"\${REPLY}\") || A=('')
                trailingNullFlag=true"""
            ${readBytesExactFlag} && echo 'nBytesRead=1'
            echo """
            else
                [[ \${REPLY} ]] && A=(\"\${REPLY}\") || A=()
                trailingNullFlag=false"""
            ${readBytesExactFlag} && echo 'nBytesRead=0'
            echo 'fi'

            if ${readBytesExactFlag}; then
                echo """
            nBytesRead+=\${#REPLY}
            [[ \${nBytesRead} == 0 ]] || (( \${nBytesRead} >= ${nBytes} )) || {"""
        
            [[ ${tTimeout} ]] && echo "while (( \${SECONDS} < ${tTimeout} )); do" || echo "while true; do"
            echo "[[ -f \"${tmpDir}\"/.done ]] && doneIndicatorFlag=true"

            printf "if read -r -d '' -n \$(( ${nBytes} - \${nBytesRead} )) -u ${fd_read}"
            [[ ${tTimeout} ]] && printf ' -t %s' "${tTimeout}" 
            echo """; then
                    ((nBytesRead++))
                    nBytesRead+=\${#REPLY}
                    [[ \${REPLY} ]] && A+=(\"\${REPLY}\") || A+=('')
                    (( \${nBytesRead} >= ${nBytes} )) && { trailingNullFlag=true; break; }
                else
                    trailingNullFlag=false
                    [[ \${REPLY} ]] && A+=(\"\${REPLY}\")
                    { (( \${nBytesRead} >= ${nBytes} )) || ${doneIndicatorFlag}; } && { trailingNullFlag=false; break; }
                    break
                fi
            done
        }"""
            fi
            echo """
        {
            if \${trailingNullFlag}; then
                printf '%s\0' \"\${A[@]}\" 
            else
                printf '%s' \"\${A[0]}\" 
                printf '\0%s' \"\${A[@]:1}\"
            fi 
        } >\"${tmpDir}\"/.stdin.tmp.{<#>}"""
        else
            printf 'read -r -N %s -u ' "${nBytes}"
            if ${readBytesExactFlag}; then
                printf '%s ' "${fd_stdin}" 
                [[ ${tTimeout} ]] && printf '-t %s ' "${tTimeout} "
            else
                printf '%s ' ${fd_read}
            fi
            echo """
            if [[ \${REPLY} ]]; then
                echo \"\${REPLY}\" >\"${tmpDir}\"/.stdin.tmp.{<#>}
                A=('')
            else
                A=()
            fi"""
        fi
        ;;
    esac
else
    printf '%s ' "mapfile -n \${nLinesCur} -u"
    ${pipeReadFlag} && printf '%s ' ${fd_stdin} || printf '%s ' ${fd_read}
    { ${pipeReadFlag} || ${nullDelimiterFlag}; } && printf '%s ' '-t'
    echo "${delimiterReadStr} A"
    ${pipeReadFlag} || ${nullDelimiterFlag} || {
        echo """
        [[ \${#A[@]} == 0 ]] || {
            [[ \"\${A[-1]: -1}\" == ${delimiterVal} ]] || {"""
        (( ${verboseLevel} > 2 )) && echo """
                echo \"Partial read at: \${A[-1]}\" >&${fd_stderr}"""
        echo """
                until read -r -u ${fd_read} ${delimiterReadStr}; do 
                    A[-1]+=\"\${REPLY}\"; 
                done
                A[-1]+=\"\${REPLY}\"${delimiterVal}"""
        (( ${verboseLevel} > 2 )) && echo "echo \"Partial read fixed to: \${A[-1]}\" >&${fd_stderr}"
        echo "}"
    }
fi
${nOrderFlag} && echo "read -u ${fd_nOrder} nOrder"
${pipeReadFlag} || ${nullDelimiterFlag} || ${readBytesFlag} || echo "}"
echo """
    printf '\\n' >&${fd_continue}
    [[ \${#A[@]} == 0 ]] && {
        if \${doneIndicatorFlag} || [[ -f \"${tmpDir}\"/.quit ]]; then"""
${nLinesAutoFlag} && echo "printf '\\n' >&\${fd_nAuto0}"
${nOrderFlag} && echo ": >\"${tmpDir}\"/.out/.quit{<#>}"
echo """
            : >\"${tmpDir}\"/.quit
            printf '\\n' >&${fd_continue}
        break"""
{ ${inotifyFlag} || ${nOrderFlag}; } && echo "else"
${nOrderFlag} && echo "printf 'x%s\n' \"\${nOrder}\" >&\${fd_nOrder0}"
${inotifyFlag} && echo "[[ -f \"${tmpDir}\"/.done ]] && doneIndicatorFlag=true || read -u ${fd_inotify} -t 0.1"
echo """
        fi
        continue
    }"""
${nLinesAutoFlag} && { printf '%s' """
    \${nLinesAutoFlag} && {
        printf '%s\\n' \${#A[@]} >&\${fd_nAuto0}
        (( \${nLinesCur} < ${nLinesMax} )) || nLinesAutoFlag=false
    }"""
    ${fallocateFlag} && printf '%s' ' || ' || echo
}
${fallocateFlag} && echo "printf '\\n' >&\${fd_nAuto0}"
${pipeReadFlag} || ${nullDelimiterFlag} || ${readBytesFlag} || {
    echo """
        { [[ \"\${A[*]##*${delimiterVal}}\" ]] || [[ -z \${A[0]} ]]; } && {"""
    (( ${verboseLevel} > 2 )) && echo "echo \"FIXING SPLIT READ\" >&${fd_stderr}"
    echo """
            A[-1]=\"\${A[-1]%${delimiterVal}}\"
            IFS=
            mapfile ${delimiterReadStr} A <<<\"\${A[*]}\"
        }"""
}
${subshellRunFlag} && echo '(' || echo '{'
{ ${exportOrderFlag} || { ${nOrderFlag} && ${substituteStringIDFlag}; }; } && echo 'nOrder0="$(( ${nOrder##*(9)*(0)} + ${nOrder%%*(0)${nOrder##*(9)*(0)}}0 - 9 ))"'
${exportOrderFlag} && echo "printf '\034%s:\035\n' \"\${nOrder0}\""
${noFuncFlag} && echo 'IFS=$'"'"'\n'"'"
printf '%s ' "${runCmd[@]}"
if ${readBytesFlag}; then
    if ${stdinRunFlag} || ${noFuncFlag}; then 
        printf '<"%s"/%s' "${tmpDir}" '.stdin.tmp.{<#>}'
    else
        printf '"$(<"%s"/%s)"' "${tmpDir}" '.stdin.tmp.{<#>}'
    fi
else
    if ${stdinRunFlag}; then 
        printf '<<<%s' "\"\${A[@]${delimiterRemoveStr}}\""
    elif ${noFuncFlag}; then 
        printf "<<<\"\${A[*]%s}\"" "${delimiterRemoveStr}"
    elif ! ${substituteStringFlag}; then 
        printf '%s' "\"\${A[@]${delimiterRemoveStr}}\""
    fi
fi
(( ${verboseLevel} > 2 )) && echo """ || {
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
    }"""
${readBytesFlag} && { [[ ${readBytesProg//bash/} ]] || ${stdinRunFlag}; } && printf '\n\\rm -f "'"${tmpDir}"'"/.stdin.tmp.{<#>}\n'
${noFuncFlag} && echo 'IFS='
${subshellRunFlag} && printf '\n%s ' ')' || printf '\n%s ' '}'
echo "${outStr}"
${nOrderFlag} && echo "printf '%s\n' \"\${nOrder}\" >&${fd_nOrder0}"
echo """
done
} 2>&${fd_stderr} {fd_nAuto0}>&${fd_nAuto}
} 2>/dev/null
p_PID+=(\${p{<#>}_PID})""" )"

        # # # # # FORK COPROC "WORKERS" # # # # #

        # initialize read lock {fd_continue} will act as an exclusive read lock (so lines from stdin are read atomically):
        #     when there is a '\n' the pipe buffer then nothing has a read lock
        #     a process reads 1 byte from {fd_continue} to get the read lock, and
        #     when that process writes a '\n' back to the pipe it releases the read lock
        printf '\n' >&${fd_continue};

        # source the coproc code for each coproc worker
        for (( kk=0 ; kk<${nProcs} ; kk++ )); do
            [[ -f "${tmpDir}"/.quit ]] && break
            source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/${kk}}"
        done

        (( ${verboseLevel} > 1 )) && printf '\n\nALL WORKER COPROCS FORKED\n\n' >&${fd_stderr}
        (( ${verboseLevel} > 3 )) && { 
            printf '\n\nDYNAMICALLY GENERATED COPROC CODE:\n\n%s\n\n' "${coprocSrcCode}"
            declare -p fd_continue fd_inotify fd_nAuto fd_nOrder fd_nOrder0 fd_read fd_write fd_stdin fd_stdout fd_stderr 
        } >&${fd_stderr}

        # # # # # WAIT FOR THEM TO FINISH # # # # #
          #   #   PRINT OUTPUT IF ORDERED   #   #

        if ${nOrderFlag}; then
            # initialize real-time printing of ordered output as forkrun runs
            outCur=10
            continueFlag=true

            while ${continueFlag}; do

                # read order indices that are done running. 
                read -r -u ${fd_nOrder0}
                case "${REPLY}" in
                    +([0-9]))
                        # index has an output file
                        outHave[$REPLY]=1
                    ;;
                    x+([0-9]))
                        # index was empty
                        outHave[${REPLY#x}]=0
                    ;;
                    '')
                        # end condition was met
                        continueFlag=false
                    ;;
                esac

                # starting at $outCur, print all indices in sequential order that have been recorded as being run and then remove the tmp output file[s]
                while true; do
                    case "${outHave[${outCur}]}" in
                        [01])
                            [[ "${outHave[${outCur}]}" == 1 ]] && {
                                cat "${tmpDir}"/.out/x${outCur} >&${fd_stdout}
                                \rm  -f "${tmpDir}"/.out/x"${outCur}"
                            }

                            unset "outHave[$outCur]"

                            # advance outCur by 1
                            ((outCur++))
                            [[ "${outCur}" == +(9)+(0) ]] && outCur="${outCur}00"
                        ;;
                        *)
                            break
                        ;;
                    esac
                done

                # check for end condition
                [[ -f "${tmpDir}"/.quit ]] && { continueFlag=false; break; }
            done
        fi

        # wait for coprocs to finish
        (( ${verboseLevel} > 1 )) && printf '\n\nWAITING FOR WORKER COPROCS TO FINISH\n\n' >&${fd_stderr}
        wait "${p_PID[@]}"

        # if ordering output print the remaining ones
        ${nOrderFlag} && [[ -f "${tmpDir}"/.out/x${outCur} ]] && cat "${tmpDir}"/.out/x* >&${fd_stdout}

        # print final nLines count
        ${nLinesAutoFlag} && (( ${verboseLevel} > 1 )) && printf 'nLines (final) = %s   (max = %s)\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}" >&${fd_stderr}

    # open anonymous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_inotify}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_nOrder0}<><(:) {fd_read}<"${fPath}" {fd_write}>"${fPath}" {fd_stdin}<&0 {fd_stdout}>&1 {fd_stderr}>&2

}

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
    shopt -s extglob
    umask 177
    while [[ "${1}" == -@([pd]) ]]; do
        [[ "${1}" == '-p' ]] && p="$2"
        [[ "${1}" == '-d' ]] && d="$2"
        shift 2
    done
    [[ "$d" == *XXXXXX* ]] || d=''
    : "${p:=/dev/shm}" "${d:=.forkrun.XXXXXX}"

    f="${p}/${d//XXXXXX/$(printf '%06x' ${RANDOM}${RANDOM:1})}"
    until mkdir "$f"; do
        f="${p}/${d//XXXXXX/$(printf '%06x' ${RANDOM}${RANDOM:1})}"
    done 2>/dev/null
    echo "$f"
)
}

forkrun_displayHelp() {

local -i displayMain displayFlags

shopt -s extglob

case "$1" in

    -?(-)usage)
        displayMain=0
        displayFlags=0
    ;;

    -?(-)help=s?(hort))
        displayMain=1
        displayFlags=0
    ;;

    -?(-)help=f?(lags))
        displayMain=0
        displayFlags=2
    ;;

    -?(-)help=a?(ll))
        displayMain=3
        displayFlags=2
    ;;

    *)
        displayMain=2
        displayFlags=1
    ;;

esac

cat<<'EOF' >&2
# # # # # # # # # # # # # # # FORKRUN # # # # # # # # # # # # # # #

USAGE: printf '%s\n' "${args[@]}" | forkrun [-flags] [--] parFunc ["${args0[@]}"]

# LIST OF FLAGS: [-j|-P <#>] [-t <path>] ( [-l <#>] | [-L <#[,#]>]] ) ( [-b <#>] | [-B <#>[,<#>]] ) [-d <char>] [-i] [-I] [-k] [-n] [-z|-0] [-s] [-S] [-p] [-D] [-N] [-u] [-v] [-h|-?]

EOF

(( ${displayMain} > 0 )) && {
cat<<'EOF' >&2

    Usage is virtually identical to parallelizing a loop by using `xargs -P` or `parallel -m`:
        -->  Pass newline-separated (or null-separated with `-z` flag) inputs to parallelize over on stdin.
        -->  Provide function/script/binary to parallelize and initial args as function inputs.
    `forkrun` will then call the function/script/binary in parallel on several coproc "workers" (default is to use $(nproc) workers)
    Each time a worker runs the function/script/binary it will use the initial args and N lines from stdin (default: `N` is between 1-512 lines and is automatically dynamically adjusted)
        --> i.e., it will run (in parallel on each "worker"):     parFunc "${args0[@]}" "${args[@]:m:N}"    # m = number of lines from stdin already processed
    `parFunc` can be an executable binary or bash script, a bash builtin, a declared bash function / alias, or *omitted entirely* (*requires -N [-NO-FUNC] flag. See flag descriptions below for more info.*)

EXAMPLE CODE:
    # get sha256sum of all files under ${PWD}
    find ./ -type f | forkrun sha256sum

EOF
}

(( ${displayMain} > 1 )) && {
cat<<'EOF' >&2
REQUIRED DEPENDENCIES:
    Bash 4+                       : This is when coprocs were introduced. WARNING: running this code on bash 4.x  *should* work, but is largely untested. Bah 5.1+ is preferable has undergone much more testing.
    `rm`  and  `mkdir`            : Required for various tasks, and doesnt have an obvious pure-bash implementation. Either the GNU version or the Busybox version is sufficient.

OPTIONAL DEPENDENCIES (to provide enhanced functionality):
    Bash 5.1+                     : Bash arrays got a fairly major overhaul here, and in particular the mapfile command (which is used extensively to read data from the tmpfile containing stdin)
                                    got a major speedup here. Bash versions 4.0 - 5.0 *should* still work, but will be (perhaps considerably) slower.
    `fallocate` -AND- kernel 3.5+ : Required to remove already-read data from in-memory tmpfile. Without both of these stdin will accumulate in the tmpfile and won't be cleared until forkrun is finished and returns
                                    (which, especially if stdin is being fed by a long-running process, could eventually result in very high memory use).
    `inotifywait`                 : Required to efficiently wait for stdin if it is arriving much slower than the coprocs are capable of processing it (e.g. `ping 1.1.1.1 | forkrun).
                                    Without this the coprocs will non-stop try to read data from stdin, causing unnecessarily high CPU usage.
    `dd` (GNU)  -OR-  `head`      : When splitting up stdin by byte count (due to either the `-b` or `-B` flag being used), if either of these is available it will be used to read stdin instead of the builtin `read (-n|-N)`. If both are available `dd` is preferred.

EOF
}

(( ${displayMain} > 2 )) && {
cat<<'EOF' >&2
HOW IT WORKS:
    The coproc code is dynamically generated based on passed forkrun options, then K coprocs (plus some "helper function" coprocs) are forked off.
    These coprocs will groups on lines from stdin using a shared fd and run them through the specified function in parallel.
    Importantly, this means that you dont need to fork anything after the initial coprocs are set up...the same coprocs are active for the duration of forkrun, and are continuously piped new data to run.
    This is MUCH faster than the traditional "forking each call" in bash (especially for many fast tasks)...On my hardware `forkrun` is 1x-2x faster than `xargs -P $(nproc) -d $'\n'`  and 3x-8x faster than `parallel -m`.

EOF
}

(( ${displayFlags} == 1 )) && {
cat<<'EOF' >&2

# # # # # # # # # # FLAGS # # # # # # # # # #

GENERAL NOTES:
    1.  Flags must be given seperately (e.g., use `-k -v` and not `-kv`) 
    2.  Flags must be given before the name of the function being parallelized (any flags given after the function name will be assumed to be initial arguments for the function, not forkrun options).
    3.  There are also "long" versions of the flags (e.g., `--insert` is the same as `-i`). Run `forkrun --help=all` for a full list of long options/flags.


FLAGS WITH ARGUMENTS
--------------------

    (-j|-p) <#> : num worker coprocs. set number of worker coprocs. Default is $(nproc).
    -l <#>      : num lines per function call (batch size). set static number of lines to pass to the function on each function call. Disables automatic dynamic batch size adjustment. if -l=1 then the "read from a pipe" mode (-p) flag is automatically activated (unless flag `+p` is also given). Default is to use the automatic batch size adjustment.
    -L <#[,#]>  : set initial (<#>) or initial+maximum (<#,#>) lines per batch while keeping the automatic batch size adjustment enabled. Default is '1,512'
    -t <path>   : set tmp directory. set the directory where the temp files containing lines from stdin will be kept. These files will be saved inside a new mktemp-generated directory created under the directory specified here. Default is '/dev/shm', or (if unavailable) '/tmp'
    -b <bytes>  : instead of reading data using a delimiter, read up to this many bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL NOT wait and will continue with fewer bytes of data read. Automatically enables `-S` flag...disable with `+S` flag.
-B <#>[,<time>] : instead of reading data using a delimiter, read up to this many ( -B <#> )bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL wait and continue re-reading until it accumulates this many bytes or until stdin has been fully read. example: `-B 4mb`. You may optionally pass a time as another input (-B <#>,<time>) which will set a timeout on how long the read commands will wait to accumulate input (if not used, they wait indefinately). example: `-B 4096k,3.5` sets 4 mb reads with a 3.5 sec timeout.
 -d <delimiter> : set the delimiter to something other than a newline (default) or NULL ((-z|-0) flag). must be a single character.
    
FLAGS WITHOUT ARGUMENTS
-----------------------

SYNTAX NOTE: for each of these passing `-<FLAG>` enables the feasture, and passing `+<FLAG>` disables the feature. Unless otherwise noted, all features are, by default, disabled. If a given flag is passed multiple times both enabling `-<FLAG>` and disabling `+<FLAG>` some option, the last one passed is used.

    -i          : insert {}. replace `{}` with the inputs passed on stdin (instead of placing them at the end)
    -I          : insert {ID}. replace `{ID}` with an index (0, 1, ...) describing which coproc the process ran on. If -k also passed then also replace `{IND}` with an index describing the output order (the same index that the  `-n` flag prints).
    -k          : ordered output. retain input order in output. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc. 
    -n          : add ordering info to output. pre-pend each output group with an index describing its input order, demoted via `$'\n'\n$'\034'$INDEX$'\035'$'\n'`. This requires and will automatically enable the `-k` output ordering flag.
    (-0|-z)     : NULL-seperated stdin. stdin is NULL-separated, not newline separated. WARNING: this flag (by necessity) disables a check that prevents lines from occasionally being split into two seperate lines, which can happen if `parFunc` evaluates very quickly. In general a delimiter other than NULL is recommended, especially when `parFunc` evaluates very fast and/or there are many items (passed on stdin) to evaluate.
    -s          : run in subshell. run each evaluation of `parFunc` in a subshell. This adds some overhead but ensures that running `parFunc` does not alter the coproc's environment and effect future evaluations of `parFunc`.
    -S          : pass via function's stdin. pass stdin to the function being parallelized via stdin ( $parFunc <<<"${A[@]}") instead of via function inputs  ( $parFunc "${A[@]}"). DEFAULT: typically disabled, but enabled when either the (-b|-B) flag is passed (in case stdin is binary and has NULLs)
    -p          : pipe read. dont use a tmpfile and have coprocs read (via shared file descriptor) directly from stdin. Enabled by default only when `-l 1` is passed.
    -D          : delete tmpdir. Remove the tmp dir used by `forkrun` when `forkrun` exits. NOTE: the `-D` flag is enabled by default...disable with flag `+D`.
    -N          : enable no func mode. Only has an effect when `parFunc` and `initialArgs` were not given. If `-N` is not passed and `parFunc` and `initialArgs` are missing, `forkrun` will silently set `parFunc` to `printf '%s\n'`, which will basically just copy stdin to stdout.
    -u          : unescape redirects/pipes/forks/logical operators. Typically `parFunc` and `initialArgs` are run through `printf '%q'` making things like `<` , `<<` , `<<<` , `>` , `>>` , `|` , `&&` , and `||` appear as literal characters. This flag skips the `printf '%q'` call, meaning that these operators can be used to allow for piping, redirection, forking, logical comparrison, etc. to occur *inside the coproc*. 
    --          : end of forkrun options indicator. indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs. This allows using a `parFunc` that begins with a `-`. NOTE: there is no `+<FLAG>` equivilant for `--`.
    -v          : increase verbosity level by 1. Higher levels give progressively more verbose output. Default level is 0. Meaningful levels range from -1 to 4. +v decreases the verbosity level by 1.
    (-h|-?)     : display help text. use `--help=f[lags]` or `--help=a[ll]` for more details about flags that `forkrun` supports. NOTE: you must escape the `?` otherwise the shell can interpret it before passing it to forkrun.

EOF
}

(( ${displayFlags} > 1 )) && {
cat<<'EOF' >&2
# # # # # # # # # # FLAGS # # # # # # # # # #

GENERAL NOTES:
    1.  Flags are matched using extglob and have a degree of "fuzzy" matching. As such, the "short" flag options must be given separately (use `-a -b`, not `-ab`). Only the most common invocations are shown below.
          *   Refer to the code for exact extglob match criteria. Example of "fuzziness" in matching: both the short and long flags may use either 1 or 2 leading dashes ('-'). NOTE: Flags ARE case-sensitive.
    2.  All forkrun flags must be given before the name or (and arguments for) whatever you are parallelizing. By default, forkrun assumes that `parFunc` is the first input that does NOT begin with a '-' or '+'.
          *   To stop option parsing sooner (e.g., to parallelize something starting with a `-`), add a '--' after the last forkrun flag. NOTE: this will only stop option parsing sooner...forkrun will always stop at the first argument that does not begin with a '-' or '+'.

--------------------------------------------------------------------------------------------------------------------

FLAGS WITH ARGUMENTS
--------------------

SYNTAX NOTE: Arguments for flags may be passed with a (breaking or non-breaking) space ' ', equal sign ('='), or no separator (''), between the flag and the argument. i.e., the following all work:
                 -A Val   |   '-A Val'   |   -A=Val   |   -AVal   |   --A_long Val   |   '--A_long Val'   |   --A_long=Val   |   --A_longVal

----------------------------------------------------------

-j | -P | --nprocs  <#> : sets the number of worker coprocs to use
   ---->  default  : number of logical CPU cores ($(nproc))

----------------------------------------------------------

-t | --tmp[dir] <path>   : sets the root directory for where the tmpfiles used by forkrun are created.
   ---->  default  : /dev/shm ; or (if unavailable) /tmp ; or (if unavailable) ${PWD}

   NOTE: unless running on an extremely memory-constrained system, having this tmp directory on a ramdisk (e.g., a tmpfs) will greatly improve performance

----------------------------------------------------------

-l | --nlines <#>       : sets the number or lines to pass coprocs to use for each function call to this constant value, disabling the automatic dynamic batch size logic.
   ---->  default  : n/a (by default automatic dynamic batch size adjustment is enabled)

-L | --NLINES  <#[,#]>  : tweak the initial (<#>) or initial+maximum (<#,#>) number of lines per batch while keeping the automatic dynamic batch size logic enabled. <#>: sets the number of lines to pass coprocs to initially use for each function call.
   ---->  default  : 1,512

    NOTE: the automatic dynamic batch size logic will only ever maintain or increase batch size...it will never decrease batch size.

----------------------------------------------------------

-b | --bytes <bytes>  : instead of reading data using a delimiter, read up to this many ( -b <#> ) bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL NOT wait and will continue with fewer bytes of data read. This can be useful when you have a maximum chunk size you can process but do not necessairly want to wait for that much data to accumulate.

-B | --BYTES <bytes>[,<seconds>]  : instead of reading data using a delimiter, read up to this many ( -B <#> ) bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL wait and continue re-reading until it accumulates this many bytes or until stdin has been fully read. example: `-B 4mb`. 
    ---->   option: You may optionally pass a time as another input (-B <#>,<time>) which will set a timeout on how long the read commands will wait to accumulate input (if not used, they wait indefinately). Example: `-B 4096k,3.5` sets 4 mb reads with a 3.5 sec timeout. This can be useful for things like spliting a compressed or binary file into equal size chunks.

    NOTE: standard byte size notations (1000^N: k, m, g, t, p;  1024^N: ki, mi, gi, ti, pi) may be used. The trailing `b` is optional and can be either upper or lower case but always will represent bytes, never bits. <seconds> for `-B` can be a decimal but should not contain any units.
    NOTE: if GNU `dd` is available it will be used to read data. If not but `head` (GNU or busybox) is available it will be used, but will be considerably slower (order of magnitude) than `dd`. If neither is available then the builtin `read -N` will be used, which is considerably slower still.
    NOTE: if either (-b|-B) is passed, then -S will automatically be enabled, meaning that the function being parallelied will be passed data on its stdin, not its command-line input. This is required to avoid mangling stdin if it contains NULLs (which is likely if stdin is binary data). This can be overridden by passing the `+S` flag at the cost of all NULLs being dropped from stdin.

----------------------------------------------------------

-d | --delimiter <delim> : sets the delimiter used to separate inputs passed on stdin. must be a single character.
   ---->  default  : newline ($'\n') 

--------------------------------------------------------------------------------------------------------------------

FLAGS WITHOUT ARGUMENTS
-----------------------

SYNTAX NOTE: These flags serve to enable various optional subroutines. All flags (short or long) may use either 1 or 2 leading dashes ('-f' or '--f' or '-flag' or '--flag' all work) to enable these.
             To instead disable these optional subroutines, replace the leading '-' or '--' with a leading '+' or '++' or '+-'. If a flag is given multiple times, the last one is used.
             Unless otherwise noted, all of  the following flags are, by default, in the "disabled" state

----------------------------------------------------------

-i | --insert        : insert {}. replace `{}` in `parFunc [${args0[@]}]` (i.e., in what is passed on the forkrun commandline) with the inputs passed on stdin (instead of placing them at the end)
]` (
-I | --INSERT        : insert {ID}.  replace `{ID}` in `parFunc [${args0[@]}i.e., in what is passed on the forkrun commandline) with an index (0, 1, ...) indicating which coproc the process is running on. This is analagous to the `--process-slot-var` option in `xargs`. Additionally, if the `-k` flag is used in conjuction with the `-I` flag, an addition replacement will be made: `{IND}` will be replaced with the ordering INDex describing which batch it ran in. This gives the same index that the `-n` flag prints.

----------------------------------------------------------

-k | --keep[-order]  : ordered output. retain input order in output. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc.


-n | --number[-lines]: numbered ordered output. Output will be ordered and, for each group of N lines that was run in a single call, an index will be pre-pended to the output group with syntax "$'\034'${INDEX}$'\035'". Impliies -k.

----------------------------------------------------------

-z | -0 | --null     : NULL-seperated stdin. stdin is NULL-seperated, not newline seperated. Equivilant to using flag: --delimiter=''

    NOTE: this flag will disable a check that ensures that lines from stdin do not get split into 2 seperate lines. The chances of this occuring are small but nonzero.

----------------------------------------------------------

-s | --subshell[-run]: run individual calls of parFunc in a subshell. Typically, the worker coprocs run each call in their own shell. This causes them to run in a subshell. This ensures that previous runs do not alter the shell environment and affect future runs, but has some performance cost.

----------------------------------------------------------

-S | --stdin[-run]   : pass lines from stdin to parfunc via its stdin instead of using its function inputs. i.e., use `parFunc <<<"${args[@]}"` instead of `parFunc "${args[@]}"`

    NOTE: This flag is typicaly disabled, but is enabled by default only when either the (-b|-B) flag (to split data by byte count) is passed. This is to avoid mangling NULL's in stdin in case stdin is binary data (a primary use case for the (-b|-B) flags).
    
----------------------------------------------------------

-p | --pipe[-read]   : read stdin from a pipe. Typically stdin is saved to a tmpfile (on a tmpfs ramdisk) and then read from the tmpfile, which avoids the "reading 1 byte at a time from a pipe" issue and is typically faster unless you are only reading very small amounts of data for eachg parFunc call. This flag forces reading from a pipe (or from a tmpfile if `+p` is used)

    NOTE: This flag is typicaly disabled, but is enabled by default only when `--nLines=1` flag is also given (causing forkrun to only read 1 line at a time for the enritre time it is running)

----------------------------------------------------------

-D | --delete        : delete the tmpdir used by forkrun on exit. You typically want this unless you are debugging something, as the tmpdir is (by default) on a tmpfs and as such is using up memory.

    NOTE: this flag is enabled by default. use the '+' version to disable it. passing `-d` has no effect except to re-enable tmpdir deletion if `+d` was passed in a previous flag.

----------------------------------------------------------

-N | --no-func       : run with no parFunc. Typically, is parFunc is omitted (e.g., `printf '%s\n' "${args[@]}" | forkrun`) forkrun will silently use `printf '%s\n'` as parFunc, causing all lines from stdin to be printed to stdout. This flag makes forkrun instead run the lines from stdin directly as they are. Presumably these lines would contain the `parFunc` part in the lines on stdin.

    NOTE: This flag can be used to make forkrun paralellize running any generic list of commands, since the `parFunc` used on each line from stdin does not need to be the same.

----------------------------------------------------------

-u | --unescape      : dont escape `parFunc [${args0[@]}]` before having the coprocs run it. Typically, `parFunc [${args0[@]}]` is run through `printf '%q '`, making such that pipes and redirects and logical operators similiar ('|' '<<<' '<<' '<' '>' '>>' '&' '&&' '||') are treated as literal characters and dont pipe / redirect / logical operators / whatever. This flag makes forkrun skip running these through `printf '%q'`, making pipes and redirects work normally. This flag is particuarly useful in combination with the `-i` flag.

    NOTE: keep in mind that the shell will interpret the commandline before forkrun gets it, so pipes and redirects must still be passed either escaped or quoted otherwise the shell will interpret+implemnt them before forkrun does.
    EXAMPLE: the following will scan files whose paths are given on stdin and search them, for some string and, only if found, print the filename:  
             printf '%s\n' "${paths[@]}" | forkrun -i -u -l1 -- 'cat {} | grep -q someString && echo {}'

----------------------------------------------------------

-v | --verbose       :  increase verbosity level by 1. this controls what "extra info" gets printed to stderr. The default level is 0. Meaningful verbotisity levels are 0 - 4
      --> -1 [or less than -1] (nothing)
      --> 0 (only warnings and errors) (DEFAULT)
      --> 1 (errors + overview of parsed forkrun options)
      --> 2 (errors + options overview + progress notifications of when the code finishes one of its main sections)
      --> 3 (errors + options overview + progress notifications + indicators of a few runtime "milestone" events and statistics)
      --> 4 [or more than 4] (errors + options overview + progress notifications + runtime milestones + print dynamically generated coproc code and exit trap to stderr)

    NOTE: The '+' version of this flag decreases verbosity level by 1.

----------------------------------------------------------

FLAGS THAT TRIGGER PRINTING HELP/USAGE INFO TO SCREEN THEN EXIT

--usage              :  display brief usage info
-? | -h | --help     :  dispay standard help (includes brief descriptions + short names for flags)
--help=s[hort]       :  more detailed varient of '--usage'
--help=f[lags]       :  display detailed info about flags (longer descriptions, short + long names)
--help=a[ll]         :  display all help (includes detailed descriptions for flags)

--------------------------------------------------------------------------------------------------------------------

EOF
}

}

