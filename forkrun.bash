#!/bin/bash
# shellcheck disable=SC2004,SC2015,SC2016,SC2028,SC2162 source=/dev/null

shopt -s extglob

forkrun() {
## Efficiently parallelize a loop / run many tasks in parallel *extremely* fast using bash coprocs
#
# USAGE: printf '%s\n' "${args[@]}" | forkrun [-flags] [--] parFunc ["${args0[@]}"]
#
# LIST OF FLAGS: [-j|-P [-]<#>[,<#>]] [-t <path>] ( [-l <#>] | [-L <#>[,<#>]] ) [-n <#>] ( [-b <#>] | [-B <#>[,<#>]] ) [-d <char>] [-u <fd>]  [-i] [-I] [-k] [-K] [-z|-0] [-s] [-S] [-p] [-D] [-N] [-U] [-v] [-h|-?]
#
# For help / usage info, call forkrun with one of the following flags:
#
# --usage              :  display brief usage info
# -? | -h | --help     :  dispay standard help (includes brief descriptions + short names for flags)
# --help=s[hort]       :  more detailed variant of '--usage'
# --help=f[lags]       :  display detailed info about flags (longer descriptions, short + long names)
# --help=a[ll]         :  display all help (includes detailed descriptions for flags)
#
# NOTE: the `?` may need to be escaped for `-?` to trigger the help (i.e., use `forkrun '-?'` or `forkrun -\?`) (otherwise bash will parse the '?' as a special char)

############################ BEGIN FUNCTION ############################

    trap - EXIT INT TERM HUP USR1

    shopt -s extglob

    # make all variables local
    local +i nLines nLines0 nLinesMax nBytes nProcs nProcsMax  
    local tmpDir fPath outStr delimiterVal delimiterReadStr delimiterRemoveStr exitTrapStr exitTrapStr_kill nOrder tTimeout coprocSrcCode outCur tmpDirRoot returnVal tmpVar t0 tStart0 tStart1 readBytesProg nullDelimiterProg ddQuietStr pLOAD0 trailingNullFlag lseekFlag lseekPosFlag fallocateFlag nLinesAutoFlag nLinesReadLimitFlag nSpawnFlag substituteStringFlag substituteStringIDFlag nOrderFlag readBytesFlag readBytesExactFlag nullDelimiterFlag subshellRunFlag stdinRunFlag pipeReadFlag rmTmpDirFlag exportOrderFlag noFuncFlag unescapeFlag optParseFlag continueFlag doneIndicatorFlag FORCE_allowCarriageReturnsFlag ddAvailableFlag pAddFlag fd_continue fd_nAuto fd_nAuto0 fd_nOrder fd_nOrder0 fd_read fd_read0 fd_write fd_stdout fd_stdin fd_stdin0 fd_stderr pWrite pOrder pAuto pSpawn pWrite_PID pOrder_PID pAuto_PID pSpawn_PID  DEBUG_FORKRUN
    local -i PID0 nLinesCur nLinesNew nLinesRead nLinesReadLimit nRead nWait nOrder0 nBytesRead nSpawn nSpawnLast nSpawnLastCount nCPU writeFileProgType v9 kkMax kkCur kk kkProcs kkProcs0 verboseLevel pLOAD_max pLOAD_target pAd pAdd_sysLoad pAdd_lineRated tStart fd_read_pos fd_read_pos0 fd_read_pos_old fd_write_pos pAdd0 pAdd1 inLines inTime inLines0 inTime0 inLines1 nTime1 inLinesDelta inTimeDelta pAddCount pAddMin pAddSum pAddMax 
    local -a A p_PID p_PID0 runCmd outHave outPrint pLOADA pLOADA0 runLines runTime 
    local -a -i runLinesA runTimeA runWaitA runAllA spawnTimeA pLOAD1
    #noReadLinesA noReadLinesA0 

    # # # # # PARSE OPTIONS # # # # #

    : "${verboseLevel:=0}" "${returnVal:=0}" "${fd_stdin0:=0}" "${nLinesReadLimitFlag:=false}" 

    # check inputs and set defaults if needed
    [[ $# == 0 ]] && optParseFlag=false || optParseFlag=true
    while ${optParseFlag} && (( $# > 0  )) && [[ "$1" == [-+]* ]]; do
        case "${1}" in

            -?(-)@([jP]|?(n)[Pp]roc?(s))?(*([[:space:]])?([+-])*([0-9])*@([0-9,-])*?(,*([0-9])*)))
                if [[ "${1}" == -?(-)@([jP]|?(n)[Pp]roc?(s))*([[:space:]])?([+-])*([0-9])*@([0-9,-])*?(,*([0-9])*) ]]; then
                    nProcs="${1##@(-?(-)@([jP]|?(n)[Pp]roc?(s))*([[:space:]])?(+))}"
                elif [[ "${1}" == -?(-)@([jP]|?(n)[Pp]roc?(s)) ]] && [[ "${2}" == ?([+-])*([0-9])*@([0-9,-])*?(,*([0-9])*) ]]; then
                    nProcs="${2#'+'}"
                    shift 1
                fi
            ;;

            -?(-)?(n)l?(ine?(s))?(*([[:space:]])+([0-9])*))
                if [[ "${1}" == -?(-)?(n)l?(ine?(s))*([[:space:]])+([0-9])* ]]; then
                    nLines="${1##@(-?(-)?(n)l?(ine?(s))*([[:space:]]))}"
                    nLinesAutoFlag=false
                elif [[ "${1}" == -?(-)?(n)l?(ine?(s)) ]] && [[ "${2}" == +([0-9])* ]]; then
                    nLines="${2}"
                    nLinesAutoFlag=false
                    shift 1
                fi
            ;;

            -?(-)?(N)L?(INE?(S))?(*([[:space:]])+([0-9])*?(,+([0-9])*)))
                if [[ "${1}" == -?(-)?(N)L?(INE?(S))*([[:space:]])+([0-9])*?(,+([0-9])*) ]]; then
                    nLines0="${1##@(-?(-)?(N)L?(INE?(S))*([[:space:]]))}"
                    nLinesAutoFlag=true
                elif [[ "${1}" == -?(-)?(N)L?(INE?(S)) ]] && [[ "${2}" == +([0-9])*?(,+([0-9])*) ]]; then
                    nLines0="${2}"
                    nLinesAutoFlag=true
                    shift 1
                else
                    continue
                fi
                if [[ "${nLines0}" == +([0-9])*','+([0-9])* ]]; then
                    _forkrun_getVal nLinesMax "${nLines0##*,}"
                    nLines="${nLines0%%,*}"
                else
                    nLines="${nLines0}"
                fi
            ;;

            -?(-)n?(line?(s)+(?(-)lim?(it)|?(-)max))?(*([[:space:]])+([0-9])*))
                if [[ "${1}" == -?(-)n?(line?(s)+(?(-)lim?(it)|?(-)max))*([[:space:]])+([0-9])* ]]; then
                    _forkrun_getVal nLinesReadLimit "${1##@(-?(-)n?(line?(s)+(?(-)lim?(it)|?(-)max))*([[:space:]]))}"
                    nLinesReadLimitFlag=true
                elif [[ "${1}" == -?(-)n?(line?(s)+(?(-)lim?(it)|?(-)max)) ]] && [[ "${2}" == +([0-9])* ]]; then
                    _forkrun_getVal nLinesReadLimit "${2}"
                    nLinesReadLimitFlag=true
                    shift 1
                fi
            ;;

            -?(-)b?(yte?(s))?(*([[:space:]])+([0-9])*))
                if [[ "${1}" == -?(-)b?(yte?(s))*([[:space:]])+([0-9])* ]]; then
                    nBytes="${1##@(+([0-9])*)}"
                    readBytesFlag=true
                    readBytesExactFlag=false
                elif [[ "${1}" == -?(-)b?(yte?(s)) ]] && [[ "${2}" == +([0-9])* ]]; then
                    nBytes="${2}"
                    readBytesFlag=true
                    readBytesExactFlag=false
                    shift 1
                fi
            ;;

            -?(-)B?(YTE?(S))?(*([[:space:]])+([0-9])*?(,+([0-9])*?(.+([0-9])*))))
                if [[ "${1}" == -?(-)B?(YTE?(S))*([[:space:]])+([0-9])*?(,+([0-9])*?(.+([0-9])*)) ]]; then
                    nBytes="${1##@(+([0-9])*?(,+([0-9])*?(.+([0-9])*)))}"
                    readBytesFlag=true
                    readBytesExactFlag=true
                elif [[ "${1}" == -?(-)B?(YTE?(S)) ]] && [[ "${2}" == +([0-9])*?(,+([0-9])*?(.+([0-9])*)) ]]; then
                    nBytes="${2}"
                    readBytesFlag=true
                    readBytesExactFlag=true
                    shift 1
                fi
            ;;

            -?(-)t?(mp?(?(-)dir))?(*([[:space:]])+([[:graph:][:space:]])))
                if [[ "${1}" == -?(-)t?(mp?(?(-)dir))*([[:space:]])+([[:graph:][:space:]]) ]]; then
                    tmpDirRoot="${1##@(-?(-)t?(mp?(?(-)dir))*([[:space:]]))}"
                    mkdir -p "${tmpDirRoot}"
                elif [[ "${1}" == -?(-)t?(mp?(?(-)dir)) ]] && [[ "${2}" == +([[:graph:][:space:]]) ]]; then
                    tmpDirRoot="${2}"
                    mkdir -p "${tmpDirRoot}"
                    shift 1
                fi
            ;;

            -?(-)d?(elim?(iter))?(*([[:space:]])@([[:graph:][:space:]])*))
                if [[ "${1}" == -?(-)d?(elim?(iter))*([[:space:]])@([[:graph:][:space:]])* ]]; then
                    delimiterVal="${1##@(-?(-)d?(elim?(iter))*([[:space:]]))}"
                    (( ${#delimiterVal} > 1 )) && printf '\nWARNING: the delimiter must be a single character, and a multi-character string was given. Only using the 1st character.\n\n' >&2
                    (( ${#delimiterVal} == 0 )) && nullDelimiterFlag=true || delimiterVal="${delimiterVal:0:1}"
                elif [[ "${1}" == -?(-)d?(elim?(iter)) ]] && [[ "${2}" == @([[:graph:][:space:]])* ]]; then
                    (( ${#2} > 1 )) && printf '\nWARNING: the delimiter must be a single character, and a multi-character string was given. Only using the 1st character.\n\n' >&2
                    (( ${#2} == 0 )) && nullDelimiterFlag=true || delimiterVal="${2:0:1}"
                    shift 1
                fi
            ;;

            -?(-)@(u|fd|file?(-)descriptor)?(*([[:space:]])+([0-9])))
                if [[ "${1}" ==  -?(-)@(u|fd|file?(-)descriptor)*([[:space:]])+([0-9]) ]]; then
                    fd_stdin0="${1##@(-?(-)@(u|fd|file?(-)descriptor)*([[:space:]]))}"
                elif [[ "${1}" ==  -?(-)@(u|fd|file?(-)descriptor) ]] && [[ "${2}" == +([0-9]) ]]; then
                    fd_stdin0="${2}"
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

            [+-]?([+-])K?(EEP?(?(-)ORDER?(ING)?(?(-)INFO))))
                [[ "${1:0:1}" == '-' ]] && exportOrderFlag=true || exportOrderFlag=false
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

            [+-]?([+-])@(N?(O)|[Nn][Oo]?(-)func))
                [[ "${1:0:1}" == '-' ]] && noFuncFlag=true || noFuncFlag=false
            ;;

            [+-]?([+-])U?(NESCAPE))
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
            
            -?(-)@(help?(=@(a?(ll)|f?(lag?(s))|s?(hort)))|usage|[h?]))
                _forkrun_displayHelp "${1}"
                return 0
            ;;

            --)
                optParseFlag=false
            ;;

            @([-+])?([-+])+([[:graph:][:space:]]))
                printf '\nERROR: FLAG "%s" NOT RECOGNIZED. ABORTING.\n\nNOTE: If this flag was intended for the code being parallelized: then:\n1. ensure all flags for forkrun come first\n2. pass '"'"'--'"'"' to denote where forkrun flag parsing should stop.\n\nUSAGE INFO:' "$1" >&2

                _forkrun_displayHelp --usage
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

    [ -t "${fd_stdin0}" ] && {
        (( ${verboseLevel} > 0 )) && printf '\n\nERROR: STDIN is a terminal. \n\nforkrun requires STDIN to be a pipe \n(containing the inputs to parallelize over); e.g.: \n\nprintf '"'"'%%s\\n'"'"' "${args[@]}" | forkrun <parFunc> \n\nABORTING! \n\n'
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

        LC_ALL=C
        LANG=C
        IFS=

        enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_splice lseek cpuusage childusage

        export LC_ALL=C LANG=C IFS=
        FORKRUN_TMPDIR="$tmpDir"
        export FORKRUN_TMPDIR="$tmpDir"
        #umask 177
        PID0="${BASHPID}"

        shopt -s nullglob

        # dynamically set defaults for a few flags
        : "${noFuncFlag:=false}" "${readBytesFlag:=false}" "${readBytesExactFlag:=false}" "${nullDelimiterFlag:=false}" "${FORCE_allowCarriageReturnsFlag:=false}" 

        if enable lseek &>/dev/null; then
            : "${lseekFlag:=true}"
        else
            : "${lseekFlag:=false}"
        fi

        ${lseekFlag} && {
            [[ "$(lseek $fd_read 0 )" == 0 ]] && : "${lseekPosFlag:=true}" || : "${lseekPosFlag:=false}"
        }

        # determine what forkrun is using lines on stdin for
        if ${FORCE_allowCarriageReturnsFlag:-false}; then
            # NOTE: allowing carriage returns in parFunC (or its initial args) is DANGEROUS. Dont do this unless you know what you are doing.
            # As such, `FORCE_allowCarriageReturnsFlag` can only be enabled (set to `true`) using the DEBUG_FORKRUN environment variable
            runCmd=("${@}") 
        else
            runCmd=("${@//$'\r'/}")
        fi
        (( ${#runCmd[@]} > 0 )) || ${noFuncFlag} || runCmd=(printf '%s\n')
        (( ${#runCmd[@]} > 0 )) && noFuncFlag=false
        ${noFuncFlag} && runCmd=('source' '/proc/self/fd/0')
        hash "${runCmd[0]}" &>/dev/null || hash "${runCmd[0]%% *}" &>/dev/null

        # setup byte reading if passed -b or -B
        
        if ${readBytesFlag}; then
            # turn off nLinesAuto
            nLinesAutoFlag=false
            nLinesReadLimitFlag=false

            # turn on passing data via stdin (to prevent mangling NULL's in binary data) by default when byte splitting
            : "${stdinRunFlag:=true}"

            # parse read size (in bytes)
            nBytes="${nBytes,,}"
            nBytes="${nBytes//' '/}"

            [[ "${nBytes}" == +([0-9])?([kmgtpezyrq])?(i)?([b]),+([0-9])?(.+([0-9])) ]] && {
                tTimeout="${nBytes##*,}"
                [[ "${tTimeout}" == +([0-9]).*([0-9]) ]] && { tTimeout="${tTimeout%%.*}"; ((tTimeout++)); }
                nBytes="${nBytes%,*}"
            }

            _forkrun_getVal nBytes "${nBytes}"

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
#                inotifyFlag=false
            else
                pipeReadFlag=false
            fi

             [[ ${readBytesProg} == 'bash' ]] || hash "${readBytesProg}"

        else
            # set batch size
            { [[ ${nLines} ]] && { _forkrun_getVal nLines "${nLines}"; (( ${nLines} > 0 )) && : "${nLinesAutoFlag:=false}"; }; } || : "${nLinesAutoFlag:=true}"
            { [[ -z ${nLines} ]] || [[ ${nLines} == 0 ]]; } && nLines=1
        fi

        # set number of coproc workers and (if enabled) minimim worker read q length
        [[ "${nProcs}" == '-'* ]] && {
            : "${nSpawnFlag:=true}"
            nProcs="${nProcs#'-'}"
        }

        [[ "${nProcs}" == *','* ]] && {
            : "${nSpawnFlag:=true}"
            _forkrun_getVal nProcsMax "${nProcs#*,}"
        }
        _forkrun_getVal nProcs "${nProcs%%,*}"

        : "${nSpawnFlag:=false}"
        
        nCPU="$({ type -a nproc &>/dev/null && nproc; } || { type -a grep &>/dev/null && grep -cE '^processor.*: ' /proc/cpuinfo; } || { mapfile -t tmpA  </proc/cpuinfo && tmpA=("${tmpA[@]//processor*/$'\034'}") && tmpA=("${tmpA[@]//!($'\034')/}") && tmpA=("${tmpA[@]//$'\034'/1}") && tmpA="${tmpA[*]}" && tmpA="${tmpA// /}" && echo ${#tmpA}; } || printf '8')";
        (( nCPU < 1 )) && nCPU=1
        { [[ ${nProcs} ]] && (( ${nProcs:-0} > 0 )); } || { ${nSpawnFlag} && nProcs=$(( 1 + ( ${nCPU} / 4 )  )) || nProcs=${nCPU}; }

        ${nSpawnFlag} && { 
            [[ ${nProcsMax//0/} ]] || nProcsMax=$(( ${nCPU} * 2 ));
        }

        { ${nSpawnFlag} && (( ${nProcs} < ${nProcsMax} )); } || : "${nSpawnFlag:=false}"

        # if reading 1 line at a time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmTmpDirFlag:=true}" "${nLinesMax:=1024}" "${subshellRunFlag:=false}" "${pipeReadFlag:=false}" "${substituteStringFlag:=false}" "${substituteStringIDFlag:=false}" "${exportOrderFlag:=false}" "${unescapeFlag:=false}" "${stdinRunFlag:=false}" 

        local -i nProcs="${nProcs}" nProcsMax="${nProcsMax}" nLines="${nLines}" nLinesMax="${nLinesMax}"

        # ensure sensible nLinesMax
         ${nLinesAutoFlag} && {  (( nLinesMax < 2 * nLines )) && nLinesMax=$(( 2 * nLines )); } || { (( nLinesMax < nLines )) && nLinesMax=nLines; }

        doneIndicatorFlag=false

#        # check for inotifywait
#        type -a inotifywait &>/dev/null && ! ${pipeReadFlag} && : "${inotifyFlag:=true}" || : "${inotifyFlag:=false}"

        # check for fallocate
        type -a fallocate &>/dev/null && ! ${pipeReadFlag} && : "${fallocateFlag:=true}" || : "${fallocateFlag:=false}"

        # check for conflict in flags that were  defined on the commandline when forkrun was called
        ${pipeReadFlag} && ${nLinesAutoFlag} && (( ${verboseLevel} >= 0 )) && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }

        # require -k to use -K
        ${exportOrderFlag} && nOrderFlag=true

        # setup delimiter
        ${readBytesFlag} || {
            if ${nullDelimiterFlag}; then
                delimiterReadStr="-d ''"
                ${lseekFlag} && : "${nullDelimiterProg:='lseek'}"
                : "${nullDelimiterProg:=bash}"
                if type -p dd &>/dev/null; then
                    ddAvailableFlag=true
                    if dd --version | grep -qF 'coreutils'; then
                        ddQuietStr='status=none'
                    else
                        ddQuietStr='2>/dev/null'
                    fi
                else
                    : "${ddAvailableFlag=false}"
                fi
                [[ "${nullDelimiterProg}" == @(dd|bash|lseek) ]] || {
                    if ${FORCE_allowUnsafeNullDelimiterFlag}; then
                        nullDelimiterProg=''
                    else
                        nullDelimiterProg='bash'
                    fi
                }
            elif [[ -z ${delimiterVal} ]]; then
                delimiterVal='$'"'"'\n'"'"
                ${noFuncFlag} || ${lseekFlag} || delimiterRemoveStr='%$'"'"'\n'"'"
            else
                delimiterVal="$(printf '%q' "${delimiterVal}")"
                 ${lseekFlag} || {
                     ${noFuncFlag} && delimiterRemoveStr='//'"${delimiterVal}"'/;$'"'"'\n'"'" || delimiterRemoveStr="%${delimiterVal}"
                 }
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

        mkdir -p "${tmpDir}"/.{run,wait}
        ${nLinesReadLimitFlag} && echo '0' >"${tmpDir}"/.nLinesRead

        # if keeping tmpDir print its location to stderr
        ${rmTmpDirFlag} || (( ${verboseLevel} <= 0 )) || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}

        (( ${verboseLevel} > 0 )) && {
            printf '\n\n------------------- FLAGS INFO -------------------\n\nCOMMAND TO PARALLELIZE: %s\n' "$(printf '%s ' "${runCmd[@]}")"
#            ${inotifyFlag} && echo 'using inotify to efficiently wait for slow inputs on stdin'
            ${fallocateFlag} && echo 'using fallocate to shrink the tmpfile containing stdin as forkrun runs'
            ${lseekFlag} && echo 'using "lseek" loadable builtin to read data faster and more efficiently'
            ${nSpawnFlag} && printf '(-j|-P) initial / max workers: %s / %s. workers will be dynamically spawned (up to a maximum of %s workers)\n' "${nProcs}" "${nProcsMax}" "${nProcsMax}" || printf '(-j|-P) using %s coproc workers\n' ${nProcs}
            ${nLinesAutoFlag} && printf '(-L) automatically adjusting batch size (lines per function call). initial = %s line(s). maximum = %s line(s).\n' "${nLines}" "${nLinesMax}" || printf '(-l) using %s lines per function call (batch size) \n' "${nLines}"
            printf '(-t) forkrun tmpdir will be under %s\n' "${tmpDirRoot}"
            ${nLinesReadLimitFlag} && printf '(-n) forkrun will return after reading %s lines (or until it reads an EOF from stdin, whichever comes first)\n' "${nLinesReadLimit}"
            ${readBytesFlag} && printf '(-%s) data will be read in chunks of %s %s bytes using %s\n' "$(${readBytesExactFlag} && echo 'B' || echo 'b')" "$(${readBytesExactFlag} && echo 'exactly' || echo 'up to')" "${nBytes}" "${readBytesProg}"
            ${nOrderFlag} && echo '(-k) output will be ordered the same as if the inputs were run sequentially'
            ${exportOrderFlag} && echo '(-K) output batches will be numbered (index is per-batch, denoted using \\034<IND>:\\035\\n)'
            ${substituteStringFlag} && echo '(-i) replacing {} with lines from stdin'
            ${substituteStringIDFlag} && printf '%s %s\n' '(-I) replacing {ID} with coproc worker ID' "$(${nOrderFlag} && echo 'and replacing {IND} with output order INDex')"
            ${unescapeFlag} && echo '(-u) not escaping special characters in ${runCmd}'
            ${pipeReadFlag} && echo '(-p) worker coprocs will read directly from stdin pipe, not from a tmpfile'
            if ${nullDelimiterFlag}; then
                printf '((-0|-z)|(-d)) stdin will be parsed using nulls as delimiter (instead of newlines) (helper: %s)\n' "${nullDelimiterProg}"
            else
                printf '(%s) delimiter: %s\n' "$([[ "${delimiterVal}" == '$'"'"'\n'"'" ]] && echo '--' || echo '-d')" "${delimiterVal}"
            fi
            ${rmTmpDirFlag} || printf '(-r) tmpdir (%s) will NOT be automatically removed\n' "${tmpDir}"
            ${subshellRunFlag} && echo '(-s) coproc workers will run each group of N lines in a subshell'
            ${stdinRunFlag} && echo '(-S) coproc workers will pass lines to the command being parallelized via the command'"'"'s stdin'
            ${noFuncFlag} && echo '(-N) no function mode enabled: commands should be included in stdin' || printf 'tmpdir: %s\n' "${tmpDir}"
            echo "(-v) Verbosity Level: ${verboseLevel}"
            printf '\n------------------------------------------\n\n'
        } >&${fd_stderr}

        # # # # # FORK "HELPER" PROCESSES # # # # #

        tStart="${EPOCHREALTIME//./}"

        evfd_init

        # start building exit trap string
        exitTrapStr=': >"'"${tmpDir}"'"/.done;
: >"'"${tmpDir}"'"/.quit;
kill -USR1 $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) 2>/dev/null; '$'\n'

        ${pipeReadFlag} && {
            # '.done'  file makes no sense when reading from a pipe
            : >"${tmpDir}"/.done
        } || {
            ${nLinesReadLimitFlag} && type -a head &>/dev/null && { 
                if ${nullDelimiterFlag}; then
                    writeFileProgType=2
                    nLinesReadLimitFlag=false
                elif [[ "${delimiterVal}" == '$'"'"'\n'"'" ]]; then
                    writeFileProgType=3
                    nLinesReadLimitFlag=false
                fi
            }
            
            : "${writeFileProgType:=1}"
        
            # spawn a coproc to write stdin to a tmpfile
            # After we are done reading all of stdin indicate this by touching .done
            { coproc pWrite {

                export LC_ALL=C LANG=C IFS=

                trap - EXIT
                trap 'trap - TERM INT HUP USR1; kill -INT '"${PID0}"' ${BASHPID}' INT
                trap 'trap - TERM INT HUP USR1; kill -TERM '"${PID0}"' ${BASHPID}' TERM
                trap 'trap - TERM INT HUP USR1; kill -HUP '"${PID0}"' ${BASHPID}' HUP
                trap 'trap - TERM INT HUP USR1' USR1

                case ${writeFileProgType} in
                    1) cat <&${fd_stdin} | evfd_splice ${fd_write} ;;
                    2) head -z -n ${nLinesReadLimit} <&${fd_stdin} | evfd_splice ${fd_write} ;;
                    3) head -n ${nLinesReadLimit} <&${fd_stdin} | evfd_splice ${fd_write} ;;
                esac
                    
                : >"${tmpDir}"/.done
                evfd_signal
                (( ${verboseLevel} > 1 )) && printf '\nINFO: pWrite has finished - all of stdin has been saved to the tmpfile at %s\n' "${fPath}" >&${fd_stderr}
#                ${inotifyFlag} && {
#                    for (( kk=0 ; kk<=nProcs ; kk++ )); do
#                        : >&${fd_write}
#                    done
#                }
              }
            }
            exitTrapStr_kill+="${pWrite_PID} "

        }

        # setup (ordered) output. This uses the same naming scheme as `split -d` to ensure a simple `cat /path/*` always orders things correctly.
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'

            printf '%s\n' {10..89} >&${fd_nOrder}

            # fork coproc to populate a pipe (fd_nOrder) with ordered output file name indicies for the worker copropcs to use
            { coproc pOrder {

                export LC_ALL=C LANG=C IFS=

                trap - EXIT
                trap 'trap - TERM INT HUP USR1; kill -INT '"${PID0}"' ${BASHPID}' INT
                trap 'trap - TERM INT HUP USR1; kill -TERM '"${PID0}"' ${BASHPID}' TERM
                trap 'trap - TERM INT HUP USR1; kill -HUP '"${PID0}"' ${BASHPID}' HUP
                trap 'trap - TERM INT HUP USR1' USR1

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

            exitTrapStr_kill+="${pOrder_PID} "
        else
            outStr='>&'"${fd_stdout}";
        fi

        # setup automatic dynamic nLines adjustment and/or fallocate pre-truncation of (already processed) stdin
        if ${nLinesAutoFlag} || ${fallocateFlag} || ${nSpawnFlag}; then

            printf '%s\n' ${nLines} >"${tmpDir}"/.nLines

            # LOGIC FOR DYNAMICALLY SETTING 'nLines':
            # The avg_bytes_per_line is estimated by looking at the byte offset position of fd_read and having each coproc keep track of how many lines it has read
            # the new "proposed" 'nLines' is determined by estimating the average bytes per line, then taking the averge of the "current nLines" and "(numbedr unread bytes) / ( (avg bytes per line) * (nProcs) )"
            # --> if proposed new 'nLines' is greater than current 'nLines' then use it (use case: stdin is arriving fairly fast, increase 'nLines' to match the rate lines are coming in on stdin)
            # --> if proposed new 'nLines' is less than or equal to current 'nLines' ignore it (i.e., nLines can only ever increase...it will never decrease)
            # --> if the new 'nLines' is greater than or equal to 'nLinesMax' or the .quit file has appeared, then break after the current iteratrion is finished
            { coproc pAuto {

                export LC_ALL=C LANG=C IFS=

                trap '[[ -f "'"${tmpDir}"'"/.run/pAuto ]] && \rm -f "'"${tmpDir}"'"/.run/pAuto' EXIT
                trap 'trap - TERM INT HUP USR1; kill -INT '"${PID0}"' ${BASHPID}' INT
                trap 'trap - TERM INT HUP USR1; kill -TERM '"${PID0}"' ${BASHPID}' TERM
                trap 'trap - TERM INT HUP USR1; kill -HUP '"${PID0}"' ${BASHPID}' HUP
                trap 'trap - TERM INT HUP USR1' USR1

                ${fallocateFlag} && {
                    nWait=$(( 16 + ( ${nProcs} / 2 ) ))
                    fd_read_pos_old=0
                }
                nLinesRead=0

                while ${fallocateFlag} || ${nLinesAutoFlag} || ${nSpawnFlag}; do

                    read -u ${fd_nAuto} -t 0.1 || continue

                    case ${REPLY} in
                        0)
                            nLinesAutoFlag=false
                            fallocateFlag=false
                            nSpawnFlag=false
                            break
                        ;;
                        x)
                            nLinesAutoFlag=false
                        ;;
                        q)
                            nSpawnFlag=false
                        ;;
                        *)
                            if ${nLinesAutoFlag} || ${nSpawnFlag}; then
                                if ${nLinesReadLimitFlag}; then
                                    read -r nLinesRead <"${tmpDir}"/.nLinesRead
                                else
                                    nLinesRead=$(( nLinesRead + ${REPLY} ))
                                fi
                            fi
                        ;;
                    esac

                    #if ${lseekPosFlag}; then
                    #    lseek $fd_read 0 SEEK_CUR fd_read_pos
                    #    lseek $fd_write 0 SEEK_CUR fd_write_pos
                    #else
                        IFS=$'\t'
                        read -r _ fd_read_pos </proc/self/fdinfo/${fd_read}
                        read -r _ fd_write_pos </proc/self/fdinfo/${fd_write}
                        IFS=
                    #fi

                    { ${nLinesAutoFlag} || ${nSpawnFlag}; } && nLinesEst=$(( ( ( 1 + ${nLinesRead} ) * ( 1 + ${fd_write_pos} ) ) / ( 1 + ${fd_read_pos} ) ))

                    ${nSpawnFlag} && printf '%s %s\n' "${nLinesEst}" "$(( ${EPOCHREALTIME//./} - tStart ))" >"${tmpDir}"/.stdin_lines_time

                    if ${nLinesAutoFlag}; then

                        ${nSpawnFlag} && [[ -f "${tmpDir}"/.nWorkers ]] && nProcs="$(<"${tmpDir}"/.nWorkers)"

                        [[ -d "${tmpDir}"/.wait ]] && { 
                            mapfile -t nProcsA < <(: | cat "${tmpDir}"/.wait 2>/dev/null)
                            nProcsA=( ${nProcsA//0/} )
                            (( ${#nProcsA[@]} > 0 )) && (( nProcs = ( ( nProcs + ${#nProcsA[@]} ) / 2 ) ))
                        }

                        nLinesNew=$(( 1 + ( ( nLinesEst - nLinesRead ) / ( 1 + ${nProcs} ) ) ))

                        (( ${nLinesNew} > ${nLinesCur} )) && {

                            (( ${nLinesNew} >= ${nLinesMax} )) && { nLinesNew=${nLinesMax}; nLinesAutoFlag=false; }

                            printf '%s\n' ${nLinesNew} >"${tmpDir}"/.nLines

                            # verbose output
                            (( ${verboseLevel} > 2 )) && printf '\nCHANGING nLines from %s to %s!!!  --  ( nLinesRead = %s ; write pos = %s ; read pos = %s )\n' ${nLinesCur} ${nLinesNew} ${nLinesRead} ${fd_write_pos} ${fd_read_pos} >&${fd_stderr}

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
                        nSpawnFlag=false
                    }

                done

              } 2>&${fd_stderr}
            } 2>/dev/null

            exitTrapStr+='printf '"'"'0\n'"'"' >&'"${fd_nAuto}"'; '$'\n'
            printf '%s\n' "${pAuto_PID}" > "${tmpDir}"/.run/pAuto

        fi

#        # setup+fork inotifywait (if available)
#        ${inotifyFlag} && {
#            {
#                # initially add 1 newline for each coproc to fd_inotify
#                { source /proc/self/fd/0 >&${fd_inotify0}; }<<<"printf '%.0s\n' {0..${nProcs}}"
#
#                # run inotifywait
#                (
#                    export LC_ALL=C LANG=C IFS=
#
#                    trap - EXIT
#                    trap 'trap - TERM INT HUP USR1; kill -INT '"${PID0}"' ${BASHPID}' INT
#                    trap 'trap - TERM INT HUP USR1; kill -TERM '"${PID0}"' ${BASHPID}' TERM
#                    trap 'trap - TERM INT HUP USR1; kill -HUP '"${PID0}"' ${BASHPID}' HUP
#                    trap 'trap - TERM INT HUP USR1' USR1
#                    inotifywait -q -m -e modify,close --format '' "${fPath}" >&${fd_inotify0} &
#                    printf '%s\n' "${!}" >"${tmpDir}"/.run/pNotify
#                )
#
#                pNotify_PID="$(<"${tmpDir}"/.run/pNotify)"
#            } 2>/dev/null {fd_inotify0}<>&${fd_inotify}
#
#            exitTrapStr+=': > "'"${tmpDir}"'"/.stdin; '$'\n'
#            ${nOrderFlag} && exitTrapStr+=': >"'"${tmpDir}"'"/.out/.quit; '$'\n'
#            exitTrapStr_kill+="${pNotify_PID} "
#        }

        # setup dynamically spawning new worker coprocs
        # dynamic spawning is decided using 3 criteria:
        #    1) total worker coproc count must not exceed the maximum worker coproc count (by default 2 * nCPU).
        #    2) coprocs will spawn until total system cpu load is at >=90% (for all cpu cores) OR until one of the other criteria is violated. If spawning new coproc(s) lowers system load, the target (90%) will be reduced.
        #    3) coprocs will spawn until ( the average time it takes to get N lines on stdin ) >= ( ( the time it takes to process N lines ) / ( num worker coprocs ) OR until one of the other criteria is violated.
        ${nSpawnFlag} && {
            echo '1 1' >"${tmpDir}"/.stdin_lines_time
            { coproc pSpawn {


                # set traps and global vars
                export LC_ALL=C LANG=C IFS= 
                trap 'printf '"'"'q\n'"'"' >&'"${fd_nAuto}"'; printf '"'"'\n'"'"' >&'"${fd_nSpawn0}"'; [[ -f "'"${tmpDir}"'"/.run/pSpawn ]] && \rm -f "'"${tmpDir}"'"/.run/pSpawn' EXIT
                trap 'trap - TERM INT HUP USR1; kill -USR1 "${p_PID[@]}" "${p_PID0[@]}"; kill -INT '"${PID0}"' ${BASHPID} "${p_PID[@]}" "${p_PID0[@]}"' INT
                trap 'trap - TERM INT HUP USR1; kill -USR1 "${p_PID[@]}" "${p_PID0[@]}";  kill -TERM '"${PID0}"' ${BASHPID} "${p_PID[@]}" "${p_PID0[@]}"' TERM
                trap 'trap - TERM INT HUP USR1; kill -USR1 "${p_PID[@]}" "${p_PID0[@]}";  kill -HUP '"${PID0}"' ${BASHPID} "${p_PID[@]}" "${p_PID0[@]}"' HUP
                trap 'trap - TERM INT HUP USR1' USR1


                # set some initial values while we wait
                : "${nProcsMax:=$((2*${nCPU}))}" 
                kkProcs0=0
                pAddFlag=true
                inLines=0
                inTime=0
                emptyReadFlag=false

                # wait for the helper coprocs spawned by the main thread to be spawned
                read -r -u ${fd_nSpawn0}

                # fetch coproc source code from tmpdir
                coprocSrcCode="$(<"${tmpDir}"/.coprocSrcCode)"
                
                # spawn initial worker coprocs
                spawnTimeA[0]=${EPOCHREALTIME//./}
                for (( kkProcs=0 ; kkProcs<${nProcs} ; kkProcs++ )); do
                    [[ -f "${tmpDir}"/.quit ]] && break
                    source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/"${kkProcs}"}"
                    spawnTimeA[$((kkProcs+1))]="${EPOCHREALTIME//./}" 
                    echo "${kkProcs}" >"${tmpDir}"/.nWorkers
                done

                kkProcsRun="$kkProcs"
                                  
                : >"${tmpDir}"/.spawned
                (( ${verboseLevel} > 1 )) && printf '\n\n%s INITIAL WORKER COPROCS FORKED\n\n' "${nProcs}" >&${fd_stderr}
                
                
                # start dynamic spawning now that nProcs workers have already spawned
                # begin main loop
                until [[ -f "${tmpDir}"/.quit ]] || (( ${kkProcs} >= ${nProcsMax} )); do

                    # update reference point for /proc/stat-based cpu load if we just spawned worker coprocs
                    ${pAddFlag} && {
                        _forkrun_getLoad -i
                        pLOAD1[$kkProcs]=$(( ( ( ( pLOADA0 - pLOAD_bg ) << 1 ) + kkProcs ) / ( kkProcs << 1 ) ))
                        pAddFlag=false
                        (( ${verboseLevel} > 3 )) && printf 'pLOADA = ( %s %s %s %s )\nAverage load per worker coproc: %s\n' "${pLOADA[@]}" "${pLOAD1[$kkProcs]}" >&${fd_stderr}
                   }

                    # wait for new info to get average run time per batch at current worker count arrives
                    # update counts of lines run and run times for the current kkProcs
                    
                    # get data in 10 ms increments until we get some
                    A=()
                    while (( ${#A[@]} == 0 )); do
                        IFS=$'\n' read -r -u ${fd_nSpawn} -t 0.01 -d '' -a A
                    done

                    for kk in "${!A[@]}"; do
                        case "${A[$kk]}" in
                            l[0-9]*)  (( runLinesA[$kkProcsRun] += ${A[$kk]#l} ))  ;;
                            t[0-9]*)  (( runTimesA[$kkProcsRun] += ${A[$kk]#t} ))  ;;
                            k[0-9]*)  kkProcsRun0=$kkProcsRun; (( kkProcsRun += ${A[$kk]#k}))  ;;
                            0)  ((runAllA[$kkProcsRun]++))  ;;
                            1)  ((runAllA[$kkProcsRun]++)); ((runWaitA[$kkProcsRun]++))  ;;
                            q)  break  ;;
                        esac
                    done

                    

                    [[ -f "${tmpDir}"/.done ]] || {
                        # update count of lines / time for lines arriving on stdin
                        read -r inLines1 inTime1 <"${tmpDir}"/.stdin_lines_time

                        (( inLines1 > inLines )) && (( inTime1 > inTime )) && {
                            inLines0=${inLines}
                            inTime0=${inTime}
                            inLines=${inLines1}
                            inTime=${inTime1}
                        }
                    }

                    IFS=
      
                    # figure out the max number of new workers to add on this loop
                    pAddMax=$(( nProcsMax - kkProcs ))
                    (( pAddMax > ( nCPU >> 1 ) )) && pAddMax=$(( nCPU >> 1 ))
                    (( pAddMax > ( kkProcsRun << 1 ) )) && pAddMax=$(( kkProcsRun << 1 ))
                    
                    # compare data processing rate to data input rate. Dont spawn more workers if either:
                    # 1. we are already processing lines faster than they are arriving on stdin, or
                    # 2. we are processing lines more slowly than we were before the most recent spawning of additional workers

                    inLinesDelta=$(( inLines - inLines0 ))
                    inTimeDelta=$(( inTime - inTime0 ))
                      
                    # estimate how many additional workers are needed (at current lineRate_run increase rate) to make lines process as fast as they arrive on stdin  
                    pAdd_lineRate=$(( ( ( ( ${runTimeA[${kkProcsRun}]} * ( ( ( inLines * inTimeDelta ) + ( inTime * inLinesDelta ) + inTimeDelta ) / ( 1 + ( inTimeDelta << 1 ) ) ) ) + ( ( 1 + ( ${runLinesA[${kkProcsRun}]} * inTime ) ) >> 1 ) ) /  ( 1 + ( ${runLinesA[${kkProcsRun}]} * inTime ) ) ) - kkProcsRun ))
                       
                    (( pAdd_lineRate > pAddMax )) && pAddMax=${pAddMax}
                    (( pAdd_lineRate < 0 )) && pAdd_lineRate=0

                    (( pAdd = ( 1 + ( ( ( ( pAdd_lineRate << 1 ) + pAddMax ) >> 1 ) * ( 1 + runWaitA[${kkProcsRun}] ) / ( 1 + runWAllA[${kkProcsRun}] ) ) ) ))
                    
                    # compare how much our lineRate increased to how much our worker count increased
                    # ideally, increasing kkProcs by X% will increase lineRate_run by X%
                    # if lineRate_run increases less than this then e are starting to hit other bottlenecks and should slow down new coproc spawning
                    # requires that coprocs have been spawned (by pSpawn) at least once already
                    (( kkProcs0 > 0 )) && pAdd=$(( ( (  pAdd * ( 1 + nProcsMax - kkProcsRun ) * ( ( ( kkProcs0 * runTimeA[${kkProcsRun0}] * runLinesA[${kkProcsRun}] ) + ( ( kkProcsRun * nCPU ) >> 1 ) ) / ( kkProcsRun * nCPU ) ) ) + ( ( runLinesA[${kkProcsRun0}] * runTimeA[${kkProcsRun}] ) >>  1 ) ) / ( runLinesA[${kkProcsRun0}] * runTimeA[${kkProcsRun}] ) ))
                    
                    # make sure estimate is between [0::pAddMax]. continue to next loop iteration if pAdd is 0 (or is somehow negative).
                    (( pAdd < 1 )) && continue
                    (( pAdd > pAddMax )) && pAdd=${pAddMax}

                    (( ${verboseLevel} > 2 )) && printf '\nSPAWNING %s NEW WORKER COPROCS\n' "${pAdd}" >&${fd_stderr}

                    # spawn the new coproc workers
                    kkProcs0=${kkProcs}
                    for (( kk=0; kk<${pAdd}; kk++ )); do
                        source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/"${kkProcs}"}"
                        (( ${verboseLevel} > 3 )) && printf '\nSPAWNING A NEW WORKER COPROC (%s/%s). There are now %s coprocs.\n' "${kk}" "${pAdd}" "${kkProcs}" >&${fd_stderr}
                        ((kkProcs++))
                    done
                     printf 'k%s\n' ${pAdd} >&${fd_nSpawn}
    
                    # update public worker count info file
                    echo "${kkProcs}" >"${tmpDir}"/.nWorkers
                   
                    (( ${verboseLevel} > 2 )) && printf '\nSPAWNED %s NEW WORKER COPROCS. There are now %s worker coprocs.\n' "${pAdd}" "${kkProcs}" >&${fd_stderr}
                   
                    runTime0=
                    kkProcs01="${kkProcs0}"
                    ((kkProcs01++))
                    while true; do
                        IFS=','
                        read -r -u ${fd_nSpawn} -d ' ' runLines runTime
                        IFS=
                        if (( ${runTime} < spawnTimeA[${kkProcs01}] )); then
                            (( runLinesA[$kkProcs0]+=${runLines} ))
                            #(( runLines < nLines )) && noReadLinesA[$kkProcs0]=$(( noReadLinesA[$kkProcs0] + nLines - runLines ))

                            runTime0=${runTime}
                            
                        elif (( ${runTime} >= spawnTimeA[${kkProcs}] )); then
                            (( runLinesA[$kkProcs]=${runLines} ))
                            #(( runLines < nLines )) && noReadLinesA[$kkProcs]=$(( nLines - runLines )) || noReadLinesA[$kkProcs]=0
                            runTimeA[${kkProcs}]=$(( runTime - spawnTimeA[${kkProcs}] )) || runTimeA[${kkProcs}]=$(( ${EPOCHREALTIME//./} - spawnTimeA[${kkProcs}] ))
                            runTimeA[${kkProcs}]=${runTimeA[${kkProcs}]##+(0)}

                            [[ ${runTime0} ]] && {
                                runTimeA[${kkProcs0}]=$(( runTime0 - spawnTimeA[${kkProcs0}] ))
                                runTimeA[${kkProcs0}]=${runTimeA[${kkProcs0}]##+(0)}
                            }

                            break
                        fi
                    done

                done

                # wait for spawned coproc workers to finish
                [[ ${#p_PID[@]} == 0 ]] || wait "${p_PID[@]}"

              } 2>&${fd_stderr}
            } 2>/dev/null

            exitTrapStr+='echo "-1 -1" >&'"${fd_nSpawn}"'; '$'\n'
            printf '%s\n' "${pSpawn_PID}" > "${tmpDir}"/.run/pSpawn
            exitTrapStr_kill+="${pSpawn_PID} "

        }
        # # # # # DYNAMICALLY GENERATE COPROC SOURCE CODE # # # # #

        # Due to how the coproc code is dynamically generated and sourced, it cannot directly contain comments. A very brief overview of their function is below.
        #
        # on each loop, they will acquire a read lock by read {fd_continue}, which blocks them until they have exclusive read access
        # they then read N lines with mapfile and check/fix a partial read (or read N bytes with $readBytesProg) and (if -k/-K) read the output order from {fd_nOrder}
        # they then release the read lock by sending \n to {fd_continue} (so the next coproc can start to read)
        # if no data was read, the coproc will either wait/continue or break, depending on if end conditions are met
        # finally (assuming it read data) it will run it through whatever is being parallelized. If -k/-K write [x]$nOrder to {fd_nOrder0} to indicate that index has run / was empty
        #
        # NOTE: All coprocs share the same {fd_read} file descriptor ( defined just after the end of the main forkrun subshell )
        #       This has the benefit of keeping the coprocs in sync with each other - when one reads data the {fd_read} used by *all* of them is advanced.

        # generate coproc source code template (which, in turn, allows you to then spawn many coprocs very quickly and have many "code branch selection" decisions already resolved)
        # this contains the code for the coprocs but has the worker ID represented using {<#>}. coprocs will be sourced via source<<<"${coprocSrcCode//'{<#>}'/${kk}}"
        #
        # NOTE: because the (uncommented) coproc code generation dynamically adapts to all of forkrun's possible options, this part is...well...hard to follow. 
        # To see the resulting coproc code for a given set of forkrun options, run:  `echo | forkrun -vvvv <FLAGS> :`

        echo '0' >"${tmpDir}"/.lastReadPos

        coprocSrcCode="$( echo """
local p{<#>} p{<#>}_PID

{ coproc p{<#>} {
export LC_ALL=C LANG=C IFS= FORKRUN_TMPDIR=\"${tmpDir}\"

echo \"\${BASH_PID}\" >\"${tmpDir}\"/.run/p{<#>}

trap ': >\"${tmpDir}\"/.quit; 
[[ -f \"${tmpDir}\"/.run/p{<#>} ]] && \\rm -f \"${tmpDir}\"/.run/p{<#>}; 
printf '\"'\"'\n'\"'\"' >&${fd_continue}' EXIT

trap 'trap - TERM INT HUP USR1; kill -INT ${PID0} \${BASHPID}' INT
trap 'trap - TERM INT HUP USR1; kill -TERM ${PID0} \${BASHPID}' TERM
trap 'trap - TERM INT HUP USR1; kill -HUP ${PID0} \${BASHPID}' HUP
trap 'trap - TERM INT HUP USR1' USR1

while true; do"""
{ ${nLinesAutoFlag} || ${nSpawnFlag}; } && echo "{ \${nLinesAutoFlag} || \${nSpawnFlag}; } && read -r <\"${tmpDir}\"/.nLines && [[ \${REPLY} == +([0-9]) ]] && nLinesCur=\${REPLY}"
echo """
    echo 1 >\"${tmpDir}\"/.wait/p{<#>}
    read -r -u ${fd_continue} _
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
            echo '-a A'
        fi
        ;;
    esac
else
    ${nLinesReadLimitFlag} && printf '%s' """read -r nLinesRead <\"${tmpDir}\"/.nLinesRead
    (( ( nLinesReadLimit - nLinesRead ) < nLinesCur )) && nLinesCur=\$(( nLinesReadLimit - nLinesRead ))
    (( nLinesCur == 0 )) && A=() || """
    echo """ {
    evfd_wait ${fd_read} '' ${fd_nSpawn}"""
    printf '%s ' "mapfile"
    ${lseekFlag} && printf '%s ' '-t'
    printf '%s ' '-n' "\${nLinesCur}" '-u'
    ${pipeReadFlag} && printf '%s ' ${fd_stdin} || printf '%s ' ${fd_read}
    { ${pipeReadFlag} || ${nullDelimiterFlag}; } && printf '%s ' '-t'
    echo """${delimiterReadStr} A
    }"""
    ${pipeReadFlag} || { ${nullDelimiterFlag} && [[ -z ${nullDelimiterProg} ]]; } || {
        echo "[[ \${#A[@]} == 0 ]] || \${doneIndicatorFlag} || {"
        if ${lseekFlag}; then
            echo """
                lseek ${fd_read} -1 SEEK_CUR ''
                read -r -u ${fd_read} -N 1"""
                if ${nullDelimiterFlag}; then
                    echo "[[ \${#REPLY} == 0 ]] || {"
                else
                    echo "[[ \"\${REPLY}\" == ${delimiterVal} ]] || {"
                fi
        elif ${nullDelimiterFlag}; then
                echo """
                IFS=\$'\\t' read -r _ fd_read_pos </proc/self/fdinfo/${fd_read}"""
            case "${nullDelimiterProg}" in
              'dd') echo """
                { dd if=\"${fPath}\" bs=1 count=1 ${ddQuietStr} skip=\$(( fd_read_pos - 1 )) | read -t 1 -r -d ''; } || {"""
              ;;
              'bash')
                    echo """
                IFS=\$'\\t' read -r _ fd_read_pos0 </proc/self/fdinfo/${fd_read0}
                nBytes=\$(( fd_read_pos - fd_read_pos0 - \${#A[@]} ))"""
                if ${ddAvailableFlag}; then 
                  echo """
                    {
                        if (( \${nBytes}  > 65535 )); then
                            { dd if=\"${fPath}\" bs=1 count=1 ${ddQuietStr} skip=\$(( fd_read_pos - 1 )) | read -t 1 -r -d ''; } 
                        else
                            read -r -u ${fd_read0} -N \${nBytes} _
                            read -r -u ${fd_read0} -d ''
                            [[ \${#REPLY} == 0 ]]
                        fi
                    } || {"""
                else
                  echo """
                    read -r -u ${fd_read0} -N \${nBytes} _
                    read -r -u ${fd_read0} -d ''
                    [[ \${#REPLY} == 0 ]] || {"""
                fi
              ;;
            esac
        else
            echo "[[ \"\${A[-1]: -1}\" == ${delimiterVal} ]] || {"
        fi
        (( ${verboseLevel} > 2 )) && echo """
                echo \"Partial read at: \${A[-1]}\" >&${fd_stderr}"""
        echo """
                until read -r -u ${fd_read} ${delimiterReadStr}; do 
                    A[-1]+=\"\${REPLY}\"; 
                done"""
        printf '%s' "A[-1]+=\"\${REPLY}\""
    ${lseekFlag} && printf '\n' || printf '%s\n' "${delimiterVal}"
    (( ${verboseLevel} > 2 )) && echo "echo \"Partial read fixed to: \${A[-1]}\" >&${fd_stderr}"
        echo "}"
    }
fi
${pipeReadFlag} || { ${nullDelimiterFlag} && [[ -z ${nullDelimiterProg} ]]; } || ${readBytesFlag} || echo "}"
${nOrderFlag} && echo "read -r -u ${fd_nOrder} nOrder"
${nLinesReadLimitFlag} && echo """
nLinesRead+=\${#A[@]}
echo \${nLinesRead} >\"${tmpDir}\"/.nLinesRead
(( nLinesRead == nLinesReadLimit )) && {
    : >\"${tmpDir}\"/.quit
    echo '0' >\"${tmpDir}\"/.nLines
}
"""
echo """
    printf '\\n' >&${fd_continue}
    echo 0 >\"${tmpDir}\"/.wait/p{<#>}
    [[ \${#A[@]} == 0 ]] && {
        echo \"empty read (worker {<#>})\" >&${fd_stderr}
        \${doneIndicatorFlag} || { 
          [[ -f \"${tmpDir}\"/.done ]] && {"""
            if ${lseekFlag}; then 
                echo """
            lseek $fd_read 0 SEEK_CUR fd_read_pos 
            lseek $fd_write 0 SEEK_CUR fd_write_pos"""
            else
                echo """
            IFS=\$'\\t' read -r _ fd_read_pos </proc/self/fdinfo/${fd_read};
            IFS=\$'\\t' read -r _ fd_write_pos </proc/self/fdinfo/${fd_write}; 
                """
            fi
            echo """
            [[ \"\${fd_read_pos}\" == \"\${fd_write_pos}\" ]] && doneIndicatorFlag=true
          }
        }
        if \${doneIndicatorFlag} || [[ -f \"${tmpDir}\"/.quit ]]; then"""
${nLinesAutoFlag} && echo "printf 'x\\n' >&\${fd_nAuto0}"
${nOrderFlag} && echo ": >\"${tmpDir}\"/.out/.quit{<#>}"
${nSpawnFlag} && echo """printf 'q\\n' >&${fd_nSpawn}
            printf 'q\\n' >&\${fd_nAuto0}"""
echo """
            : >\"${tmpDir}\"/.quit
            printf '%.0s\\n' \"${tmpDir}\"/.run/p* >&${fd_continue}
            break"""
${nOrderFlag} && echo """else
            printf 'x%s\n' \"\${nOrder}\" >&\${fd_nOrder0}"""
echo """fi
        continue
    }"""
{ ${nLinesAutoFlag} || ${nSpawnFlag}; } && { 
    printf '%s' """
    { \${nLinesAutoFlag} || \${nSpawnFlag}; } && {
        printf '%s\\n' \${#A[@]} >&\${fd_nAuto0}
        (( \${nLinesCur} < ${nLinesMax} )) || nLinesAutoFlag=false
    }"""
    ${fallocateFlag} && printf '%s' ' || ' || echo
}
${fallocateFlag} && echo "printf '\\n' >&\${fd_nAuto0}"
${pipeReadFlag} || ${nullDelimiterFlag} || ${readBytesFlag} || ${lseekFlag} || {
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
printf '%s ' "${runCmd[@]}"
if ${readBytesFlag} && ! { [[ ${readBytesProg} == 'bash' ]] && ! ${stdinRunFlag}; }; then
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
${subshellRunFlag} && printf '\n%s ' ')' || printf '\n%s ' '}'
echo "${outStr}"
${nOrderFlag} && echo "printf '%s\\n' \"\${nOrder}\" >&${fd_nOrder0}"
${nSpawnFlag} && echo "printf 'l%s\\nt%s\\n' \${#A[@]} \${EPOCHREALTIME//./} >&${fd_nSpawn}"
echo """
done
} 2>&${fd_stderr} {fd_nAuto0}>&${fd_nAuto}
} 2>/dev/null
p_PID+=(\${p{<#>}_PID})""" )"
        
        # set traps (dynamically determined based on which option flags were active)

        # if ordering output print the remaining ones in trap
        ${nOrderFlag} && exitTrapStr+='cat </dev/null "'"${tmpDir}"'"/.out/x* >&'"${fd_stdout}"'; '$'\n'
    
        # make sure all processes are dead
        exitTrapStr+='kill $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) 2>/dev/null;
        kill -9 '"${exitTrapStr_kill}"' 2>/dev/null; 
        kill -9 $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) 2>/dev/null; '$'\n'
        
    
        # if removing tmpdir delete it in trap
        ${rmTmpDirFlag} && exitTrapStr+='\rm -rf "'"${tmpDir}"'" 2>/dev/null; '$'\n'
        exitTrapStr+='trap - INT TERM HUP USR1; 
        return ${returnVal:-0}'
        
        trap "${exitTrapStr}" EXIT

        trap 'trap - TERM INT HUP USR1; 
        returnVal=1; 
        kill -USR1 $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null); 
        kill -INT $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) '"${PID0}" INT

        trap 'trap - TERM INT HUP USR1; 
        returnVal=1; 
        kill -USR1 $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null); 
        kill -TERM $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) '"${PID0}" TERM

        trap 'trap - TERM INT HUP USR1; 
        returnVal=1; 
        kill -USR1 $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null); 
        kill -HUP $(cat </dev/null "'"${tmpDir}"'"/.run/p* 2>/dev/null) '"${PID0}" HUP
                    
        (( ${verboseLevel} > 1 )) && printf '\n\nALL HELPER COPROCS FORKED\n\n' >&${fd_stderr}
        (( ${verboseLevel} > 3 )) && { printf '\nSET TRAPS:\n\n'; trap -p; } >&${fd_stderr}

        ${nSpawnFlag} && {
            printf '%s\n' "${coprocSrcCode}" >"${tmpDir}"/.coprocSrcCode
            printf '\n' >&${fd_nSpawn0}
        }

        # # # # # FORK COPROC "WORKERS" # # # # #

        # initialize read lock {fd_continue} will act as an exclusive read lock (so lines from stdin are read atomically):
        #     when there is a '\n' the pipe buffer then nothing has a read lock
        #     a process reads 1 byte from {fd_continue} to get the read lock, and
        #     when that process writes a '\n' back to the pipe it releases the read lock
        printf '\n' >&${fd_continue};

        # source the coproc code for each coproc worker
        ${nSpawnFlag} || {
            for (( kkProcs=0 ; kkProcs<${nProcs} ; kkProcs++ )); do
                [[ -f "${tmpDir}"/.quit ]] && break
                source /proc/self/fd/0 <<<"${coprocSrcCode//'{<#>}'/"${kkProcs}"}"
            done
            echo "${kkProcs}" >"${tmpDir}"/.nWorkers                    
            : >"${tmpDir}"/.spawned
            (( ${verboseLevel} > 1 )) && printf '\n\n%s WORKER COPROCS FORKED\n\n' "${nProcs}" >&${fd_stderr}
        }

        (( ${verboseLevel} > 3 )) && { 
            printf '\n\nDYNAMICALLY GENERATED COPROC CODE:\n\n%s\n\n' "${coprocSrcCode}"
            declare -p fd_continue fd_nAuto fd_nOrder fd_nOrder0 fd_nSpawn fd_read fd_write fd_stdin fd_stdout fd_stderr 
        } >&${fd_stderr}

        # # # # # WAIT FOR THEM TO FINISH # # # # #
        #  #  #   PRINT OUTPUT IF ORDERED   #  #  #

        if ${nOrderFlag}; then
            # initialize real-time printing of ordered output as forkrun runs
            outCur=10
            continueFlag=true
            outPrint=()

            while ${continueFlag}; do

                # read order indices that are done running. 
                read -r -u ${fd_nOrder0}
                case "${REPLY}" in
                    +([0-9]))
                        # index has an output file
                        outHave[${REPLY}]=1
                    ;;
                    x+([0-9]))
                        # index was empty
                        outHave[${REPLY#x}]=0
                    ;;
                    '')
                        # end condition was met
                        continueFlag=false
                        break
                    ;;
                esac 

                # starting at $outCur, print all indices in sequential order that have been recorded as being run and then remove the tmp output file[s]
                
                while [[ "${outHave[${outCur}]}" ]]; do

                    [[ "${outHave[${outCur}]}" == 1 ]] && outPrint+=("${tmpDir}/.out/x${outCur}")
                    
                    unset "outHave[${outCur}]"
            
                    # advance outCur by 1
                    ((outCur++))
                    [[ "${outCur}" == +(9)+(0) ]] && outCur="${outCur}00"
                
                    [[ ${#outPrint[@]} == 128 ]] && {
                        cat "${outPrint[@]}"
                        \rm -f "${outPrint[@]}"
                        outPrint=()
                    }

                done

                [[ ${#outPrint[@]} == 0 ]] || {
                    cat "${outPrint[@]}"
                    \rm -f "${outPrint[@]}"
                    outPrint=()
                }
                
                # check for end condition
                [[ -f "${tmpDir}"/.quit ]] && { continueFlag=false; break; }
            done
        fi

        # wait for coprocs to finish
        (( ${verboseLevel} > 1 )) && printf '\n\nWAITING FOR WORKER COPROCS TO FINISH\n\n' >&${fd_stderr}
        #p_PID=($(_forkrun_rmdups "${p_PID[@]}" $(cat </dev/null "${tmpDir}"/.run/p[0-9]* 2>/dev/null)))
        #p_PID+=($(cat </dev/null "${tmpDir}"/.run/p[0-9]* 2>/dev/null))
        wait "${p_PID[@]}" "${pSpawn_PID}" &>/dev/null; 
        ${nSpawnFlag} && read -r -u ${fd_nSpawn0}

        # print final nLines count
        (( ${verboseLevel} > 1 )) && {
            ${nLinesAutoFlag} && printf 'nLines (final) = %s    ( max = %s )\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}"
            # ${nSpawnFlag} && printf 'final worker process count: %s\n' "$(<"${tmpDir}"/.nWorkers)"
        } >&${fd_stderr} 
        
    ${nSpawnFlag} && printf 'final worker process count: %s\n' "$(<"${tmpDir}"/.nWorkers)" >&${fd_stderr}


    # open anonymous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_nOrder0}<><(:) {fd_nSpawn}<><(:) {fd_nSpawn0}<><(:) {fd_read}<"${fPath}" {fd_read0}<"${fPath}" {fd_write}>"${fPath}" {fd_stdin}<&${fd_stdin0} {fd_stdout}>&1 {fd_stderr}>&2

}

# set up completion for forkrun
_forkrun_complete() {
    local -i kk jj
    local cmdFlag 
    local -a compsA comps0 compsT comps

    cmdFlag=false

    kk=1
    while (( ${kk} < ${COMP_CWORD} )); do
        case "${COMP_WORDS[$kk]}" in
            # forkrun option with arg - 2 inputs
            -?(-)@(@([jP]|?(n)[Pp]roc?(s)?)|?(n)l?(ine?(s))|?(N)L?(INE?(S))|b?(yte?(s))|B?(YTE?(S))|t?(mp?(?(-)dir))|d?(elim?(iter))))
                kk+=2
            ;;

            # forkrun option with arg or for displaying help - 1 input
            -?(-)@(@([jP]|?(n)[Pp]roc?(s)?)@([= ])+([0-9])|?(n)l?(ine?(s))@([= ])+([0-9])|?(N)L?(INE?(S))@([= ])+([0-9])?(,+([0-9]))|b?(yte?(s))@([= ])+([0-9])*|B?(YTE?(S))@([= ])+([0-9])*?(,+([0-9])?(.+([0-9])))|t?(mp?(?(-)dir))@([= ])+([[:graph:][:space:]])|d?(elim?(iter))@([= ])@([[:graph:][:space:]])*|help?(=@(a?(ll)|f?(lag?(s))|s?(hort)))|usage|[h?]))
                ((kk++))
            ;;

            # forkrun option without arg - 1 input
            [+-]?([+-])@(@(i?(nsert))|@(I?(D)|INSERT?(?(-)ID))|k?(eep?(?(-)order))|@(0|z?(ero)|null)|s?(ub)?(?(-)shell)?(?(-)run)|@(S|[Ss]tdin?(?(-)run))|p?(ipe)?(?(-)read)|@(D|[Dd]elete)|n?(umber)?(-)?(line?(s))|@(N?(O)|[Nn][Oo]?(-)func)|u?(nescape)|@(+(v)|verbose)))
                ((kk++))
            ;;

            # option to force stop forkrun option parsing - next option is the command being parallelized
            --)
                ((kk++))
                cmdFlag=true
                break
            ;;

            # this option is the start of the command being parallelized
            *)
                cmdFlag=true
                break
            ;;

        esac
    done

    [[ "${kk}" == "${COMP_CWORD}" ]] && ! [[ "${COMP_WORDS[${COMP_CWORD}]:0:1}" == @([-+]) ]] && cmdFlag=true

    if ${cmdFlag}; then
        # completion is not a forkrun option

        if [[ "${kk}" == "${COMP_CWORD}" ]]; then
            # completion is the command that forkrun is parallelizing
            COMPREPLY=($(compgen -c -- "${COMP_WORDS[${COMP_CWORD}]}"))

        else
            # completion is an argument for the command being parallelized
            # shift by index of the command being parallelized (which is "${kk}")
            _command_offset ${kk}
        fi

    else
        # completion is a forkrun option

        # dont complete arguments for options that are standalong seperate inputs
        (( ${kk} > ${COMP_CWORD} )) && return

        # generate array with possible completions
        mapfile -t compsA < <(printf '%s ' '' -{,-}{j,P,nprocs}{,=} $'\n' \
-t{,=} --{tmp,tmpdir}{,=} --t{,=} -{tmp,tmpdir}{,=} $'\n' \
-l{,=} --{,n}line{s,}{,=} --l{,=} -{,n}line{s,}{,=} $'\n' \
-n{,=} --n{,line}{s,}{,-}{,lim,limit}{,-}{,max}{,=}  --n{,line}{s,}{,-}{,max}{,-}{,lim,limit}{,=} --n{,=} -n{,line}{s,}{,-}{,lim,limit}{,-}{,max}{,=}  -n{,line}{s,}{,-}{,max}{,-}{,lim,limit}{,=} $'\n' \
-L{,=} --{,N}LINE{S,}{,=} --L{,=} -{,N}LINE{S,}{,=} $'\n' \
-b{,=} --byte{s,}{,=} --b{,=} -byte{s,}{,=} $'\n' \
-B{,=} --BYTE{S,}{,=} --B{,=} -BYTE{S,}{,=} $'\n' \
-d{,=} --{delim,delimiter}{,=} --d{,=} -{delim,delimiter}{,=} $'\n' \
-u{,=} --{fd,filedescriptor,file-descriptor}{,=} --u{,=} -{fd,filedescriptor,file-descriptor}{,=} $'\n' \
{-,+}i {--,++}insert {--,++}i {-,+}insert {-+,+-}i {-+,+-}insert $'\n' \
{-,+}I {--,++}INSERT{,-ID,ID} {--,++}I {-,+}INSERT{,-ID,ID}{-+,+-}I {-+,+-}INSERT{,-ID,ID} $'\n' \
{-,+}k {--,++}keep{,-order,order} {--,++}k {-,+}keep{,-order,order} {-+,+-}k {-+,+-}keep{,-order,order} $'\n' \
{-,+}K {--,++}KEEP{,ORDER,ORDERING,-ORDER,-ORDERING}{,INFO,-INFO} {--,++}K {-,+}KEEP{,ORDER,ORDERING,-ORDER,-ORDERING}{,INFO,-INFO} {-+,+-}K {-+,+-}KEEP{,ORDER,ORDERING,-ORDER,-ORDERING}{,INFO,-INFO} $'\n' \
{-,+}{z,0} {--,++}{zero,null} {--,++}{z,0} {-,+}{zero,null} {-+,+-}{z,0} {-+,+-}{zero,null} $'\n' \
{-,+}s {--,++}sub{,-}shell{-,}run {-v-,++}s {-,+}sub{,-}shell{-,}run {-+,+-}s {-+,+-}sub{,-}shell{-,}run $'\n' \
{-,+}S {--,++}{S,s}tdin{,-run,run} {--,++}S {-,+}{S,s}tdin{,-run,run} {-+,+-}S {-+,+-}{S,s}tdin{,-run,run} $'\n' \
{-,+}p {--,++}pipe{,-read,read} {--,++}p {-,+}pipe{,-read,read} {-+,+-}p {-+,+-}pipe{,-read,read} $'\n' \
{-,+}D {--,++}{D,d}elete {--,++}D {-,+}{D,d}elete {-+,+-}D {-+,+-}{D,d}elete $'\n' \
{-,+}N {--,++}{No,no,NO,nO}{,-}func {--,++}N {-,+}{No,no,NO,nO}{,-}func {-+,+-}N {-+,+-}{No,no,NO,nO}{,-}func {--,++}{No,no,NO,nO} {-,+}{No,no,NO,nO} {-+,+-}{No,no,NO,nO} $'\n' \
{-,+}U {--,++}UNESCAPE {--,++}U {-,+}UNESCAPE {-+,+-}U {-+,+-}UNESCAPE $'\n' \
{-,+}{v,vv,vvv,vvvv} {--,++}verbose {--,++}{v,vv,vvv,vvvv} {-,+}verbose {-+,+-}{v,vv,vvv,vvvv} {-+,+-}verbose $'\n' \
{--,-}usage $'\n' \
-{\?,h} --help --{\?,h} -help $'\n' \
{--,-}help={s,short} $'\n' \
{--,-}help={f,flags} $'\n' \
{--,-}help={a,all} $'\n' \
--)

        # for each possible option alias group, generate completions and use the 1st match. This prevents multiple aliases for a given option being suggested together.
        for jj in "${!compsA[@]}"; do
            if [[ "${compsA[$jj]}" == *\ "${COMP_WORDS[${COMP_CWORD}]}"* ]]; then
                mapfile -t -n 1 compsT < <( IFS=' '; compgen -W "${compsA[$jj]}" -- "${COMP_WORDS[${COMP_CWORD}]}"; )
                comps+=("${compsT[0]}")
            fi
        done

        COMPREPLY=("${comps[@]}")

    fi
}
complete -o bashdefault -o nosort -F _forkrun_complete forkrun

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

_forkrun_displayHelp() {

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

# LIST OF FLAGS: [-j|-P [-]<#>[,<#>]] [-t <path>] ( [-l <#>] | [-L <#>[,<#>]] ) ( [-b <#>] | [-B <#>[,<#>]] ) [-d <char>] [-u <fd>] [-i] [-I] [-k] [-K] [-z|-0] [-s] [-S] [-p] [-D] [-N] [-u] [-v] [-h|-?]

EOF

(( ${displayMain} > 0 )) && {
cat<<'EOF' >&2

    Usage is virtually identical to parallelizing a loop by using `xargs -P` or `parallel -m`:
        -->  Pass newline-separated (or null-separated with `-z` flag) inputs to parallelize over on stdin.
        -->  Provide function/script/binary to parallelize and initial args as function inputs.
    `forkrun` will then call the function/script/binary in parallel on several coproc "workers" (default is to use $(nproc) workers)
    Each time a worker runs the function/script/binary it will use the initial args and N lines from stdin (default: `N` is between 1-1024 lines and is automatically dynamically adjusted)
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
    `dd` (GNU)  -OR-  `head`      : When splitting up stdin by byte count (due to either the `-b` or `-B` flag being used), if available one of these will be used to read stdin (instead of the `read (-n|-N)` builtin). 
                                    If both are available `dd` is preferred. `dd` is much faster than `head`, which in much *much* faster than `read (-n|-N)`. NOTE: `dd` must be the GNU version...the busybox `dd` doesnt work here.
    `dd` (GNU|busybox)            : Required when using NULL as the delimiter to break up stdin (via `-z` flag or via `-d ''` flag). 
    `bash-completion`             : Required for bash automatic completion (on <TAB> press) to work as you are typing the forkrun commandline. 
                                    This is strictly a "quality of life" feature to make typing the forkrun cmdline easier -- it has zero effect on forkrun's execution after it has been called.

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

    (-j|-p) <#> : num worker coprocs. set number of worker coprocs. Default is $(nproc). If the number is negative (begins with a '-') then the numbner of coprocs used will be determined dynamically based on runtime conditions (see "alt syntax" below).
    (-j|-P) -[<#1>[,<#2>]]: alternate syntax to enable dynamically determining coproc count. <#1> is the initial number of coprocs spawned (default: num CPUs / 2). <#2> is the maximum number of coprocs to be spawned (default: num CPUs * 2). All values (except for the '-' / negative sign) are optional, and may be omitted (leaving just a '-') to just set max coproc count.
    -l <#>      : num lines per function call (batch size). set static number of lines to pass to the function on each function call. Disables automatic dynamic batch size adjustment. if -l=1 then the "read from a pipe" mode (-p) flag is automatically activated (unless flag `+p` is also given). Default is to use the automatic batch size adjustment.
    -L <#[,#]>  : set initial (<#>) or initial+maximum (<#,#>) lines per batch while keeping the automatic batch size adjustment enabled. Default is '1,1024'
    -n <#>      : limit forkrun to processing (at most) the first <#> lines passed on stdin.
    -t <path>   : set tmp directory. set the directory where the temp files containing lines from stdin will be kept. These files will be saved inside a new mktemp-generated directory created under the directory specified here. Default is '/dev/shm', or (if unavailable) '/tmp'
    -b <bytes>  : instead of reading data using a delimiter, read up to this many bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL NOT wait and will continue with fewer bytes of data read. Automatically enables `-S` flag...disable with `+S` flag.
-B <#>[,<time>] : instead of reading data using a delimiter, read up to this many ( -B <#> )bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL wait and continue re-reading until it accumulates this many bytes or until stdin has been fully read. example: `-B 4mb`. You may optionally pass a time as another input (-B <#>,<time>) which will set a timeout on how long the read commands will wait to accumulate input (if not used, they wait indefinately). example: `-B 4096k,3.5` sets 4 mb reads with a 3.5 sec timeout.
    -d <delim>  : set the delimiter to something other than a newline (default) or NULL ((-z|-0) flag). <delim> must be a single character.
    -u <fd>     : read data from file descriptor <fd> instead of from stdin (i.e., file descriptor 0). <fd> must be a positive integer,
    
FLAGS WITHOUT ARGUMENTS
-----------------------

SYNTAX NOTE: for each of these passing `-<FLAG>` enables the feasture, and passing `+<FLAG>` disables the feature. Unless otherwise noted, all features are, by default, disabled. If a given flag is passed multiple times both enabling `-<FLAG>` and disabling `+<FLAG>` some option, the last one passed is used.

    -i          : insert {}. replace `{}` with the inputs passed on stdin (instead of placing them at the end)
    -I          : insert {ID}. replace `{ID}` with an index (0, 1, ...) describing which coproc the process ran on. If -k also passed then also replace `{IND}` with an index describing the output order (the same index that the  `-K` flag prints).
    -k          : ordered output. output order will be the same as if the inputs were run sequentially. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc. 
    -K          : add ordering info to output. pre-pend each output group with an index describing its input order, demoted via `$'\n'\n$'\034'$INDEX$'\035'$'\n'`. This requires and will automatically enable the `-k` output ordering flag.
    (-0|-z)     : NULL-seperated stdin. stdin is NULL-separated, not newline separated. WARNING: this flag (by necessity) disables a check that prevents lines from occasionally being split into two seperate lines, which can happen if `parFunc` evaluates very quickly. In general a delimiter other than NULL is recommended, especially when `parFunc` evaluates very fast and/or there are many items (passed on stdin) to evaluate.
    -s          : run in subshell. run each evaluation of `parFunc` in a subshell. This adds some overhead but ensures that running `parFunc` does not alter the coproc's environment and effect future evaluations of `parFunc`.
    -S          : pass via function's stdin. pass stdin to the function being parallelized via stdin ( $parFunc <<<"${A[@]}") instead of via function inputs  ( $parFunc "${A[@]}"). DEFAULT: typically disabled, but enabled when either the (-b|-B) flag is passed (in case stdin is binary and has NULLs)
    -p          : pipe read. dont use a tmpfile and have coprocs read (via shared file descriptor) directly from stdin. Enabled by default only when `-l 1` is passed.
    -D          : delete tmpdir. Remove the tmp dir used by `forkrun` when `forkrun` exits. NOTE: the `-D` flag is enabled by default...disable with flag `+D`.
    -N          : enable no func mode. Only has an effect when `parFunc` and `initialArgs` were not given. If `-N` is not passed and `parFunc` and `initialArgs` are missing, `forkrun` will silently set `parFunc` to `printf '%s\n'`, which will basically just copy stdin to stdout.
    -U          : unescape redirects/pipes/forks/logical operators. Typically `parFunc` and `initialArgs` are run through `printf '%q'` making things like `<` , `<<` , `<<<` , `>` , `>>` , `|` , `&&` , and `||` appear as literal characters. This flag skips the `printf '%q'` call, meaning that these operators can be used to allow for piping, redirection, forking, logical comparrison, etc. to occur *inside the coproc*. 
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

-j | -P | --nprocs  <#> : sets the number of worker coprocs to use. If set to a negative number then the coproc count is adjusted dynamically based on read wait q depth (see alt syntax below).
   ---->  default  : number of logical CPU cores ($(nproc))

-j | -P | --nprocs -[<#1>[,<#2>]]: (alt syntax - dynamic coproc count). 
        <#1> is the initial number of coprocs spawned (--> default: num CPUs / 2). 
        <#2> is the maximum number of coprocs to be spawned (--> default: num CPUs * 2). 
    All values (except the '-' / negative sign) are optional, and may be omitted (leaving just a '-') to just set max coproc count or min wait q depth.
    EXAMPLES: `-j -` or `-j -,`: sets defaults for both parameters
              `-j -10,`: sets initial coproc count to 10, max coproc count to default (2 * nCPU) 

NOTE: Don't set max number of coprocs too high. On larger problems, it will likely hit this maximum. Setting it too high can lead to excessive resource consumption and potential performance degradation. This limit is based on the idea that only one coproc can read data at a time, spawning more until there's always at least one waiting. However, forkrun (especially with lseek) reads data very quickly (typically 100's of microseconds per operation), making it challenging to build a significant read wait q.

----------------------------------------------------------

-t | --tmp[dir] <path>   : sets the root directory for where the tmpfiles used by forkrun are created.
   ---->  default  : /dev/shm ; or (if unavailable) /tmp ; or (if unavailable) ${PWD}

   NOTE: unless running on an extremely memory-constrained system, having this tmp directory on a ramdisk (e.g., a tmpfs) will significantly improve performance...having it on a disk would massively reduce forkrun's performance.

----------------------------------------------------------

-l | --nlines <#>       : sets the number or lines to pass coprocs to use for each function call to this constant value, disabling the automatic dynamic batch size logic.
   ---->  default  : n/a (by default automatic dynamic batch size adjustment is enabled)

-L | --NLINES  <#[,#]>  : tweak the initial (<#>) or initial+maximum (<#,#>) number of lines per batch while keeping the automatic dynamic batch size logic enabled. <#>: sets the number of lines to pass coprocs to initially use for each function call.
   ---->  default  : 1,1024

    NOTE: the automatic dynamic batch size logic will only ever maintain or increase batch size...it will never decrease batch size.

----------------------------------------------------------

-n <#>  :   limit forkrun to processing (at most) the first <#> lines passed on stdin. This works the same as it does in `head -n <#>` or in `mapfile -t -n <#>`

    NOTE: this is an upper limit -- if stdin has fewer than <#> lines passed to it when it is closed, then all of stdin will be processed and forkrun will then return...it will not / can not wait for more lines.

----------------------------------------------------------

-b | --bytes <bytes>  : instead of reading data using a delimiter, read up to this many ( -b <#> ) bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL NOT wait and will continue with fewer bytes of data read. This can be useful when you have a maximum chunk size you can process but do not necessairly want to wait for that much data to accumulate.

-B | --BYTES <bytes>[,<seconds>]  : instead of reading data using a delimiter, read up to this many ( -B <#> ) bytes at a time. If fewer than this many bytes are available when a worker coproc calls `read`, then it WILL wait and continue re-reading until it accumulates this many bytes or until stdin has been fully read. example: `-B 4mb`. 
    ---->   option: You may optionally pass a time as another input (-B <#>,<time>) which will set a timeout on how long the read commands will wait to accumulate input (if not used, they wait indefinately). Example: `-B 4096k,3.5` sets 4 mb reads with a 3.5 sec timeout. This can be useful for things like spliting a compressed or binary file into equal size chunks.

    NOTE: standard byte size notations (1000^N: k, m, g, t, p;  1024^N: ki, mi, gi, ti, pi) may be used. The trailing `b` is optional and can be either upper or lower case but always will represent bytes, never bits. <seconds> for `-B` can be a decimal but should not contain any units.
    NOTE: if GNU `dd` is available it will be used to read data. If not but `head` (GNU or busybox) is available it will be used, but will be considerably slower (order of magnitude) than `dd`. If neither is available then the builtin `read -N` will be used, which is considerably slower still.
    NOTE: if either (-b|-B) is passed, then -S will automatically be enabled, meaning that the function being parallelied will be passed data on its stdin, not its command-line input. This is required to avoid mangling stdin if it contains NULLs (which is likely if stdin is binary data). This can be overridden by passing the `+S` flag at the cost of all NULLs being dropped from stdin.

----------------------------------------------------------
 
-d | --delimiter <delim> : sets the delimiter used to separate inputs passed on stdin. <delim> must be a single character.
   ---->  default  : newline ($'\n') 

----------------------------------------------------------

-u | --fd | --file-descriptor <fd> : read data from file descriptor <fd> instead of from stdin (i.e., file descriptor 0). <fd> must be a positive integer,

--------------------------------------------------------------------------------------------------------------------

FLAGS WITHOUT ARGUMENTS
-----------------------

SYNTAX NOTE: These flags serve to enable various optional subroutines. All flags (short or long) may use either 1 or 2 leading dashes ('-f' or '--f' or '-flag' or '--flag' all work) to enable these.
             To instead disable these optional subroutines, replace the leading '-' or '--' with a leading '+' or '++' or '+-'. If a flag is given multiple times, the last one is used.
             Unless otherwise noted, all of  the following flags are, by default, in the "disabled" state

----------------------------------------------------------

-i | --insert        : insert {}. replace `{}` in `parFunc [${args0[@]}]` (i.e., in what is passed on the forkrun commandline) with the inputs passed on stdin (instead of placing them at the end)
]` (
-I | --INSERT        : insert {ID}.  replace `{ID}` in `parFunc [${args0[@]}i.e., in what is passed on the forkrun commandline) with an index (0, 1, ...) indicating which coproc the process is running on. This is analagous to the `--process-slot-var` option in `xargs`. Additionally, if the `-k` flag is used in conjuction with the `-I` flag, an addition replacement will be made: `{IND}` will be replaced with the ordering INDex describing which batch it ran in. This gives the same index that the `-K` flag prints.

----------------------------------------------------------

-k | --keep[-order]  : ordered output. Output results in the same order they would have been in had the list of inputs been processed sequentially. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc.


-K | --number[-lines]: numbered ordered output. Output will be ordered and, for each group of N lines that was run in a single call, an index will be pre-pended to the output group with syntax "$'\034'${INDEX}$'\035'". Implies -k.

----------------------------------------------------------

-z | -0 | --null     : NULL-seperated stdin. stdin is NULL-seperated, not newline seperated. Equivilant to using flag: --delimiter=''

    NOTE: this flag will disable a check that ensures that lines from stdin do not get split into 2 seperate lines. The chances of this occuring are small but nonzero.

----------------------------------------------------------

-s | --subshell[-run]: run individual calls of parFunc in a subshell. Typically, the worker coprocs run each call in their own shell. This causes them to run in a subshell. This ensures that previous runs do not alter the shell environment and affect future runs, but has some performance cost.

----------------------------------------------------------

-S | --stdin[-run]   : pass lines from stdin to parfunc via its stdin instead of using its function inputs. i.e., use `parFunc <<<"${args[@]}"` instead of `parFunc "${args[@]}"`

    NOTE: This flag is typicaly disabled, but is enabled by default only when either the (-b|-B) flag (to split data by byte count) is passed. This is to avoid mangling NULL's in stdin in case stdin is binary data (a primary use case for the (-b|-B) flags).
    
----------------------------------------------------------

-p | --pipe[-read]   : read stdin directly from the pipe. Typically stdin is saved to a tmpfile (on a tmpfs ramdisk) that serves as a buffer and then data is read from the tmpfile. forkrun does this to avoid the "reading 1 byte at a time from a pipe" issue and it is typically faster unless you are only reading very small amounts of data for eachg parFunc call. This flag forces reading from a pipe (or from a tmpfile if `+p` is used)

    NOTE: This flag is typicaly disabled, but is enabled by default only when `--nLines=1` flag is also given (causing forkrun to only read 1 line at a time for the enritre time it is running)

----------------------------------------------------------

-D | --delete        : delete the tmpdir used by forkrun on exit. You typically want this unless you are debugging something, as the tmpdir is (by default) on a tmpfs and as such is using up memory.

    NOTE: this flag is enabled by default. use the '+' version to disable it. passing `-d` has no effect except to re-enable tmpdir deletion if `+d` was passed in a previous flag.

----------------------------------------------------------

-N | --no-func       : run with no parFunc. Typically, is parFunc is omitted (e.g., `printf '%s\n' "${args[@]}" | forkrun`) forkrun will silently use `printf '%s\n'` as parFunc, causing all lines from stdin to be printed to stdout. This flag makes forkrun instead run the lines from stdin directly as they are. Presumably these lines would contain the `parFunc` part in the lines on stdin.

    NOTE: This flag can be used to make forkrun paralellize running any generic list of commands, since the `parFunc` used on each line from stdin does not need to be the same.

----------------------------------------------------------

-U | --UNESCAPE      : dont escape the command forkrun will be running (i.e., `parFunc [${args0[@]}]`) before having the coprocs run it. Typically, `parFunc [${args0[@]}]` is run through `printf '%q '`, making such that pipes and redirects and logical operators similiar ('|' '<<<' '<<' '<' '>' '>>' '&' '&&' '||') are treated as literal characters and dont pipe / redirect / logical operators / whatever. This flag makes forkrun skip running these through `printf '%q'`, making pipes and redirects work normally. This flag is particuarly useful in combination with the `-i` flag.

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

_forkrun_loadable_setup() {
    ## sets up a "loadable" bash builtin for x86_64 machines
    local loadableArch cksumAlg cksumVal cksumAll loadablePre loadableDir loadableGetFlag loadableCurlFailedFlag forkrunRepo
    
    loadableGetFlag=false 
    loadableCurlFailedFlag=false
    #forkrunRepo='main'
    forkrunRepo='forkrun_testing_nSpawn_5'

    type curl &>/dev/null || {
        if [[ -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so ]]; then
            enable -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so lseek 2>/dev/null
            enable -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so childusage 2>/dev/null
        else
            enable lseek 2>/dev/null
            enable childusage 2>/dev/null
        fi
        return
    }

    if type uname &>/dev/null; then
        loadableArch="$(uname -m)"
    elif [[ -f /proc/sys/kernel/arch ]] ; then
        loadableArch="$(</proc/sys/kernel/arch)"
    else
        return 1
    fi

    { [[ "${loadableArch}" == 'x86_64' ]] || [[  "${loadableArch}" == 'aarch64' ]] || [[  "${loadableArch}" == 'riscv64' ]] || return 1; }

    if  ! [[ $USER == 'root' ]] && [[ -f /dev/shm/.forkrun.loadable/forkrun.so ]]; then 
        loadablePre='/dev/shm/.forkrun.loadable/forkrun.so'
    elif [[ -f /usr/local/lib/bash/forkrun.so ]]; then
        loadablePre='/usr/local/lib/bash/forkrun.so'
    fi

    [[ ${loadablePre} ]] && {
        for cksumAlg in sha256sum sha512sum b2sum sha1sum md5sum cksum sum; do
            type $cksumAlg &>/dev/null && break || cksumAlg=''
        done
        [[ ${cksumAlg} ]] && {
            cksumVal="$($cksumAlg "$loadablePre")"
            cksumVal="${cksumVal%% *}"
            cksumAll="$(curl 'https://raw.githubusercontent.com/jkool702/forkrun/refs/heads/'"${forkrunRepo}"'/loadables/CHECKSUMS' 2>/dev/null)"
            [[ "${cksumAll}" == *"${cksumVal}"* ]] || loadableGetFlag=true
        }
    }

    if [[ ${loadablePre} ]] && ! ${loadableGetFlag}; then
        enable -f "${loadablePre}" lseek 2>/dev/null || loadableGetFlag=true
        enable -f "${loadablePre}" childusage 2>/dev/null || loadableGetFlag=true
    else
        loadableGetFlag=true
    fi
    
    if ${loadableGetFlag}; then
        ${loadablePre} && \mv -f "${loadablePre}" "${loadablePre}".old 
        case "${USER}" in
            root)  loadableDir='/usr/local/lib/bash'  ;;
            *)  loadableDir='/dev/shm/.forkrun.loadable'  ;;
        esac
        
        mkdir -p "${loadableDir}"
        [[ "${BASH_LOADABLES_PATH}" == *"${loadableDir}"* ]] || export BASH_LOADABLES_PATH="${loadableDir}:${BASH_LOADABLES_PATH}"
        curl -o "${loadableDir}"/forkrun.so 'https://raw.githubusercontent.com/jkool702/forkrun/'"${forkrunRepo}"'/loadables/bin/'"${loadableArch}"'/forkrun.so' || loadableCurlFailedFlag=true

        [[ ${loadablePre} ]] && {
            if ${loadableCurlFailedFlag}; then
                \mv "${loadablePre}".old "${loadablePre}"
            else
                enable -d lseek 2>/dev/null
                enable -d childusage 2>/dev/null
            fi
        }
        
        enable -f "${loadableDir}"/forkrun.so lseek 2>/dev/null || return 1
        enable -f "${loadableDir}"/forkrun.so childusage 2>/dev/null || return 1
    else
        enable -f "${loadableDir}"/forkrun.so lseek 2>/dev/null || return 1
        enable -f "${loadableDir}"/forkrun.so childusage 2>/dev/null || return 1
    fi
    
    echo 'abc' >/dev/shm/.forkrun.lseek.test
    {
        read -r -u $fd -N 1
        lseek $fd -1 >/dev/null
        read -r -u $fd -N 1
        exec {fd}>&-
    } {fd}</dev/shm/.forkrun.lseek.test
    \rm -f /dev/shm/.forkrun.lseek.test

    case "$REPLY" in
        a)
            return 0
        ;;
        *)
            enable -d lseek
            printf '\nWARNING: lseek functionality has not been enabled due to an unknown runtime error.\nIf you are on x86_64 or aarch64 and are using bash 4.0 or later, please file a github issue in the forkrun repo describing this error.\n' >&2
            [[ ${loadablePre} ]] && ! ${loadableCurlFailedFlag} && {
                \rm -f "${loadablePre}"
                \mv "${loadablePre}".old "${loadablePre}"
            }
            return 1
        ;;
    esac
}

#_forkrun_loadable_setup
enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_splice lseek cpuusage childusage

enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_splice lseek cpuusage childusage


export -fp _forkrun_getVal &>/dev/null && export -nf _forkrun_getVal

_forkrun_getVal() {
    ## Expands IEC and SI prefixes to get the numeric value they represent
    #
    # IEC PREFIC (1024^N) is used if the prefix has a trailing '-i' (Ki/Mi/Gi). This is is the case without exception.
    #  SI PREFIX (1000^N) is used if the prefix is a single letter (K/M/G/...), UNLESS the number is prefaced with a '+'.
    #
    # NOTE: neither capatalization nor a trailing -b/-B have any effect. full word prefixes (e.g., '1 kilobyte') are not supported.
    #
    #  PARSING EXAMPLES:
    #        +1k = +1K = +1kb = +1KB = 1kib = 1KiB = +1kib = +1KiB = 1024
    #         1k =  1K =  1kb =  1KB = 1000

    local +i -l nn
    local vOut

    local -n vOut="$1"
    shift 1
    local -g vOut

    (( ${#pMap[@]} == 20 )) || local -Ag pMap=([k]=1 [m]=2 [g]=3 [t]=4 [p]=5 [e]=6 [z]=7 [y]=8 [r]=9 [q]=10 [ki]=1 [mi]=2 [gi]=3 [ti]=4 [pi]=5 [ei]=6 [zi]=7 [yi]=8 [ri]=9 [qi]=10)
     
    for nn in "${@%%[Bb]*}"; do    
        [[ ${nn} ]] || continue
        case "${nn// /}" in
            *'i'|'+'*)
                printf -v vOut '%s\n' "$(( ${nn//[^0-9]/} << ( 10 * ${pMap[${nn##*[0-9]}]:-0} ) ))"
            ;;
            *)
                printf -v vOut '%s\n' "$(( ${nn//[^0-9]/} * ( 1000 ** ${pMap[${nn: -1}]:-0} ) ))"
            ;;
        esac
    done
    local +n vOut
}

_forkrun_getLoad() {
    ## computes a "smoothed average system CPU load" using info gathered from /proc/stat
    # 100% load on all CPU's gives pLOAD=1000000 (1 million)
  
    # FLAGS:  
    #    '-i'|'--init':  initialize/reset load calculation. 
    # 
    #
    # pLOADA0 (input) / pLOADA (output):     ( pLOAD  cpu_ALL  cpu_LOAD  tALL )
    #     --> pLOAD:    represents the current average load level estimate between all logical CPU cores ( scaled between 0 - 1000000, or (if set) between 0 - $maxLoadNum )  
    #     --> cpu_ALL:  total sum of ALL components from /proc/stats when the last pLOAD was computed
    #     --> cpu_LOAD: total sum of the components that represent CPU load (everything except idle time and IOwait time) when the last pLOAD was computed
    #     --> tALL:     total time difference used in the last call to _forkrun_getLoad  (i.e., $(( CPU_ALL - CPU_ALL0 )) from previous run) 
 


    local -i cpu_user cpu_nice cpu_system cpu_idle cpu_IOwait cpu_irq cpu_softirq cpu_steal cpu_guest cpu_guestnice tLOAD tALL tALL0 cpu_ALL cpu_ALL0 cpu_LOAD cpu_LOAD0 pLOAD pLOAD0 
    local -i -I loadMaxVal 
    local initFlag 
        
    case "${1}" in
        -i|--init)
            initFlag=true
        ;;
        *)
            initFlag=false
            pLOAD0="${pLOADA0[0]}"
            cpu_ALL0="${pLOADA0[1]}"
            cpu_LOAD0="${pLOADA0[2]}"
            tALL0="${pLOADA0[3]}"
        ;;
    esac

    : "${loadMaxVal:=1000000}"

    IFS=' '
    read -r _ cpu_user cpu_nice cpu_system cpu_idle cpu_IOwait cpu_irq cpu_softirq cpu_steal cpu_guest cpu_guestnice </proc/stat
    IFS=
    
    cpu_LOAD=$(( cpu_user + cpu_nice + cpu_system + cpu_irq + cpu_softirq + cpu_steal + cpu_guest + cpu_guestnice ))
    cpu_ALL=$(( cpu_LOAD + cpu_idle + cpu_IOwait ))
    
    ${initFlag} && [[ "${pLOADA0[*]}" == *([0 ]) ]] && {
        pLOADA0=(0 "${cpu_ALL}" "${cpu_LOAD}" 0)
        return 0
    }

    tALL=$(( cpu_ALL - cpu_ALL0 ))

    tLOAD=$(( cpu_LOAD - cpu_LOAD0 ))
        
    (( tALL0 > ( tALL << 2 ) )) && tALL0=$((  tALL << 2 ))

    pLOAD=$(( ( loadMaxVal * ( 1 + tLOAD ) ) / ( 1 + tALL ) ))
    (( pLOAD0 > 0 )) && pLOAD=$(( ( ( ( 1 + ( tALL << 2 ) + tALL0 ) * pLOAD ) + ( 3 * tALL0 * pLOAD0 ) ) / ( 1 + ( ( tALL + tALL0 ) << 2 ) ) ))

    pLOADA=("${pLOAD}" "${cpu_ALL}" "${cpu_LOAD}" "${tALL}")
    ${initFlag} && pLOADA0=("${pLOAD}" "${cpu_ALL}" "${cpu_LOAD}" "${tALL}")

}


# export -fp _forkrun_getLoad &>/dev/null && export -nf _forkrun_getLoad
# 
# _forkrun_getLoad() (
#     ## computes a "smoothed average system CPU load" using info gathered from /proc/stat
#     #
#     # USAGE:  
#     #     mapfile -t -n 4 pLOADA  < <(_forkrun_getLoad [-i|--init] [-e|--echo] [-m|--max|--max-load maxLoadNum] )
#     #     mapfile -t -n 4 pLOADA  < <(_forkrun_getLoad [-e|--echo] [-m|--max|--max-load maxLoadNum] "${pLOADA[@]}")
#     #
#     # FLAGS:  
#     #    '-i'|'--init':  initialize/reset load calculation. 
#     #    '-e'|'--echo':  print average load to stderr in addition to printing pLOAD + cpu_ALL + cpu_LOAD to stdout
#     #    '-m'|'--max'|'--max-load' maxloadNum:  positive integer (maxLoadNum) that replaces 10000 as the number that repesents 100% load. 
#     #
#     # OUTPUTS:          pLOAD  cpu_ALL  cpu_LOAD  tALL
#     #     --> pLOAD:    represents the current average load level estimate between all logical CPU cores ( scaled between 0 - 1000000, or (if set) between 0 - $maxLoadNum )  
#     #     --> cpu_ALL:  total sum of ALL components from /proc/stats when the last pLOAD was computed
#     #     --> cpu_LOAD: total sum of the components that represent CPU load (everything except idle time and IOwait time) when the last pLOAD was computed
#     #     --> tALL:     total time difference used in the last call to _forkrun_getLoad  (i.e., $(( CPU_ALL - CPU_ALL0 )) from previous run) 
#     #
#     # INPUTS:           pLOADA=( $pLOAD  $cpu_ALL  $cpu_LOAD  $tALL )
#     #     --> Input the 3 values that were output last time _forkrun_getLoad was called. 
#     #     --> Not required if using -i flag. If any of these 3 values are not given then `-i` flag is implied
# 
#     unset IFS
# 
#     local -i loadMaxVal cpu_user cpu_nice cpu_system cpu_idle cpu_IOwait cpu_irq cpu_softirq cpu_steal cpu_guest cpu_guestnice tLOAD tALL tALL0 cpu_ALL cpu_ALL0 cpu_LOAD cpu_LOAD0 pLOAD pLOAD0 argCount
#     local initFlag echoFlag
#     
#     loadMaxVal=1000000
#     initFlag=false
#     echoFlag=false
#     argCount=0
# 
#     pLOAD0="${pLOADA0[0]}"
#     cpu_ALL0="${pLOADA0[1]}"
#     cpu_LOAD0="${pLOADA0[2]}"
#     tALL0="${pLOADA0[3]}"
# 
# 
#     while (( ${#} > 0 )); do
#         case "${1}" in
#             '-i'|'--init')
#                 initFlag=true
#             ;;
#             '-e'|'--echo')
#                 echoFlag=true
#             ;;
#             '-m'|'--max'|'--max-load')
#                 [[ "${2}" == [0-9]* ]] && {
#                     loadMaxVal="${2}"
#                     (( ${loadMaxVal} > 0 )) || loadMaxVal=10000
#                     shift 1
#                 }
#             ;;
#             [0-9]*)
#             case "${argCount}" in
#                 0)  [[ ${1} == 0 ]] && pLOAD0=1 || pLOAD0="${1}"  ;;
#                 1)  cpu_ALL0="${1}"  ;;
#                 2)  cpu_LOAD0="${1}"  ;;
#                 3)  tALL0="${1}"  ;;
#             esac
#             ((argCount++))
#             ;;
#         esac
#         shift 1
#     done
# 
#     : "${tALL0:=0}"
# 
# #    if [[ ${pLOAD0} == 0 ]] || [[ ${cpu_ALL0} == 0 ]] || [[ ${cpu_LOAD0} == 0 ]] || [[ ${tALL0} == 0 ]] || [[ -z ${pLOAD0} ]] || [[ -z ${cpu_ALL0} ]] || [[ -z ${cpu_LOAD0} ]] || [[ -z ${tALL0} ]]; then
# #        initFlag=true
# #    fi
# 
#     read -r _ cpu_user cpu_nice cpu_system cpu_idle cpu_IOwait cpu_irq cpu_softirq cpu_steal cpu_guest cpu_guestnice </proc/stat
#     
#     cpu_LOAD=$(( cpu_user + cpu_nice + cpu_system + cpu_irq + cpu_softirq + cpu_steal + cpu_guest + cpu_guestnice ))
#     cpu_ALL=$(( cpu_LOAD + cpu_idle + cpu_IOwait ))
#     
#     ${initFlag} && {
#         pLOADA=(-1 "${cpu_ALL}" "${cpu_LOAD}" 0)
#         printf '%s\n' "${pLOADA[@]}"   
#         return 0
#     }
# 
#     tALL=$(( cpu_ALL - cpu_ALL0 ))
# 
# #    pLOAD=$(( ( loadMaxVal * ( cpu_LOAD - cpu_LOAD0 ) ) / ( 1 + cpu_ALL - cpu_ALL0 ) ))
# 
#     tLOAD=$(( cpu_LOAD - cpu_LOAD0 ))
#         
#     (( tALL0 > ( tALL << 1 ) )) && tALL0=$((  tALL << 1 ))
# 
#     pLOAD=$(( ( loadMaxVal * ( 1 + tLOAD ) ) / ( 1 + tALL ) ))
#     (( pLOAD0 > 0 )) && pLOAD=$(( ( ( ( 1 + ( tALL << 2 ) + tALL0 ) * pLOAD ) + ( 3 * tALL0 * pLOAD0 ) ) / ( 1 + ( ( tALL + tALL0 ) << 2 ) ) ))
# 
#     pLOADA=("${pLOAD}" "${cpu_ALL}" "${cpu_LOAD}" "${tALL}")
#     printf '%s\n' "${pLOADA[@]}"
#     ${echoFlag} && printf 'Current System CPU Load = %s / %s\n' "${pLOAD}" "${loadMaxVal}" >&2
# )
# 
# export -fp _forkrun_getLoad_pid &>/dev/null && export -nf _forkrun_getLoad_pid
# 
# 
# _forkrun_getLoad_pid() (
#     ## computes a "smoothed average CPU load" for a specific group of PIDs using info gathered from /proc/<pid>/stat
#     #
#     # USAGE:  
#     #     mapfile -t pLOADA  < <(_forkrun_getLoad [-i|--init] [-e|--echo] [-m|--max|--max-load maxLoadNum] [--] "${pidA[@]}")
#     #     mapfile -t pLOADA  < <(_forkrun_getLoad [-e|--echo] [-m|--max|--max-load maxLoadNum] "${pLOADA[@]}" [--] "${pidA[@]}")
#     #
#     # FLAGS:  
#     #    '-i'|'--init':  initialize/reset load calculation. 
#     #    '-e'|'--echo':  print average load to stderr in addition to printing pLOAD + cpu_ALL + cpu_LOAD to stdout
#     #    '-m'|'--max'|'--max-load' maxloadNum:  positive integer (maxLoadNum) that replaces 10000 as the number that repesents 100% load. 
#     #
#     # OUTPUTS:          pLOAD  cpu_ALL  cpu_LOAD  tALL
#     #     --> pLOAD:    represents the current average load level estimate between all logical CPU cores ( scaled between 0 - 10000, or (if set) between 0 - $maxLoadNum )  
#     #     --> cpu_ALL:  total sum of ALL components from /proc/stats when the last pLOAD was computed
#     #     --> cpu_LOAD: total sum of the components that represent CPU load (everything except idle time and IOwait time) when the last pLOAD was computed
#     #     --> tALL:     total time difference used in the last call to _forkrun_getLoad  (i.e., $(( CPU_ALL - CPU_ALL0 )) from previous run) 
#     #
#     # INPUTS:           pLOADA=( $pLOAD  $cpu_ALL  $cpu_LOAD  $tALL )
#     #     --> Input the 3 values that were output last time _forkrun_getLoad was called. 
#     #     --> Not required if using -i flag. If any of these 3 values are not given then `-i` flag is implied
# 
#     unset IFS
# 
#     local -i loadMaxVal tLOAD tALL0 tALL cpu_ALL cpu_ALL0 cpu_LOAD cpu_LOAD0 pLOAD pLOAD0 argCount u0 s0 u1 s1
#     local initFlag echoFlag grep_str
#     local -a pidA cpu_ALLA cpu_LOADA
#     
#     loadMaxVal=10000
#     initFlag=false
#     echoFlag=false
#     argCount=0
# 
#     pLOAD0="${pLOADA0_new[0]}"
#     cpu_ALL0="${pLOADA0_new[1]}"
#     cpu_LOAD0="${pLOADA0_new[2]}"
#     tALL0="${pLOADA0_new[3]}"
# 
#     while (( ${#} > 0 )); do
#         case "${1}" in
#             '-i'|'--init')
#                 initFlag=
#                 argCount=4
#             ;;
#             '-e'|'--echo')
#                 echoFlag=true
#             ;;
#             '-m'|'--max'|'--max-load')
#                 [[ "${2}" == [0-9]* ]] && {
#                     loadMaxVal="${2}"
#                     (( ${loadMaxVal} > 0 )) || loadMaxVal=10000
#                     shift 1
#                 }
#             ;;
#             --)
#                 shift 1
#                 ${haveGrepFlag} && pidA=("$@") || pidA=($(printf '/proc/%s/stat' "${@}"))
#                 break
#                ;;
#             *)
#                 case "${argCount}" in
#                     0)  pLOAD0="${1}"  ;;
#                     1)  cpu_ALL0="${1}"  ;;
#                     2)  cpu_LOAD0="${1}"  ;;
#                     3)  tALL0="${1}"  ;;
#                     *)  ${haveGrepFlag} && pidA+=("${1}") || pidA+=("/proc/${1}/stat")  ;;
#                 esac
#                 ((argCount++))
#             ;;
#         esac
#         shift 1
#     done
# 
#     : "${tALL0:=0}" 
# 
#     [[ ${haveGrepFlag} ]] || { type grep &>/dev/null && haveGrepFlag=true || haveGrepFlag=false; }
#     
#     [[ "${tmpDir}" ]] || local tmpDir='/tmp' 
# 
#     read -r -a cpu_ALLA </proc/stat
# 
#     if [[ ${#pidA[@]} == 0 ]]; then
#         cpu_LOAD=${cpu_LOAD0}
#     else
#         # ALT IMPLEMENTATION (IF WE HAVE GREP)
#         if ${haveGrepFlag}; then
#             IFS='|'
#             printf -v grep_str '(%s) ' "${pidA[*]}"
#             unset IFS
#             grep -r -E "${grep_str}" /proc/[0-9]*/stat >"${tmpDir}"/.proc_pid_stat
#         else
#             echo ${pidA[@]} >&2
#             cat "${pidA[@]}" </dev/null 2>/dev/null >"${tmpDir}"/.proc_pid_stat
#         fi
#         
#         [[ ! -s "${tmpDir}"/.proc_pid_stat ]] && { \rm -f "${tmpDir}"/.proc_pid_stat; return 1; }
# 
#         IFS=' '
#         while read -r -u ${fd_stat} _ _ _ _ _ _ _ _ _ _ _ _ _ u0 s0 u1 s1 _ ; do 
#             cpu_LOADA+=($u0 $s0 $u1 $s1)
#         done {fd_stat}<"${tmpDir}"/.proc_pid_stat 
#         IFS='+'
#         cpu_LOAD=$(( ${cpu_LOADA[*]} ))
#         unset IFS
# 
#         \rm -f "${tmpDir}"/.proc_pid_stat
#     fi
# 
#     IFS='+'
#     cpu_ALL=$(( ${cpu_ALLA[*]:1} ))
#     unset IFS
#     
#     ${initFlag} && {
#         pLOADA_new=(0 "${cpu_ALL}" "${cpu_LOAD}" 0)
#         printf '%s\n' "${pLOADA_new[@]}"   
#         return 0
#     }
# 
#     tALL=$(( cpu_ALL - cpu_ALL0 ))
# 
#     tLOAD=$(( cpu_LOAD - cpu_LOAD0 ))
#         
#     (( tALL0 > ( tALL << 1 ) )) && tALL0=$(( tALL << 1 ))
# 
#     pLOAD=$(( ( loadMaxVal * ( 1 + tLOAD ) ) / ( 1 + tALL ) ))
#     (( pLOAD0 > 0 )) && pLOAD=$(( ( ( ( 1 + ( tALL << 1 ) + tALL0 ) * pLOAD ) + ( tALL0 * pLOAD0 ) ) / ( 1 + ( ( tALL + tALL0 ) << 1 ) ) ))
# 
#     pLOADA_new=("${pLOAD}" "${cpu_ALL}" "${cpu_LOAD}" "${tALL}")
#     printf '%s\n' "${pLOADA_new[@]}"
#     ${echoFlag} && printf 'Current System CPU Load = %s / %s\n' "${pLOAD}" "${loadMaxVal}" >&2
# )
