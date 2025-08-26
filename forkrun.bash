#!/bin/bash
# shellcheck disable=SC2004,SC2015,SC2016,SC2028,SC2162 source=/dev/null

if shopt extglob | grep -qE 'off$'; then
	forkrun_extglobState='-u'
else
    forkrun_extglobState='-s'
fi
shopt -s extglob

forkrun() (
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
    local tmpDir fPath outStr delimiterVal delimiterReadStr delimiterRemoveStr exitTrapStr exitTrapStr_kill nOrder tTimeout coprocSrcCode outCur outCurHex outRead tmpDirRoot returnVal tmpVar t0 tStart0 tStart1 readBytesProg nullDelimiterProg ddQuietStr pLOAD0 trailingNullFlag lseekFlag lseekPosFlag fallocateFlag nLinesAutoFlag nLinesReadLimitFlag nSpawnFlag substituteStringFlag substituteStringIDFlag nOrderFlag readBytesFlag readBytesExactFlag nullDelimiterFlag subshellRunFlag stdinRunFlag pipeReadFlag rmTmpDirFlag exportOrderFlag noFuncFlag unescapeFlag optParseFlag continueFlag doneIndicatorFlag FORCE_allowCarriageReturnsFlag ddAvailableFlag pAddFlag fd_continue fd_nAuto fd_nAuto0 fd_nOrder fd_nOrder0 fd_read fd_read0 fd_write fd_stdout fd_stdin fd_stdin0 fd_stderr pWrite pOrder pAuto pSpawn pWrite_PID pOrder_PID pAuto_PID pSpawn_PID  DEBUG_FORKRUN
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

    tmpDir="$(mktemp -p "${tmpDirRoot}/.forkrun" -d forkrun.XXXXXX)"
    fPath="${tmpDir}"/.stdin

    mkdir -p "${tmpDir}"/.run
    : >"${fPath}"

    ${rmTmpDirFlag} && trap '\rm -rf "'"${tmpDir}"'" 2>/dev/null' EXIT

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

        enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_copy order_init order_get lseek cpuusage childusage

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
        #${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmTmpDirFlag:=true}" "${nLinesMax:=1024}" "${subshellRunFlag:=false}" "${pipeReadFlag:=false}" "${substituteStringFlag:=false}" "${substituteStringIDFlag:=false}" "${exportOrderFlag:=false}" "${unescapeFlag:=false}" "${stdinRunFlag:=false}" 

        local -i nProcs="${nProcs}" nProcsMax="${nProcsMax}" nLines="${nLines}" nLinesMax="${nLinesMax}"

        # ensure sensible nLinesMax
         ${nLinesAutoFlag} && {  (( nLinesMax < 2 * nLines )) && nLinesMax=$(( 2 * nLines )); } || { (( nLinesMax < nLines )) && nLinesMax=nLines; }

        doneIndicatorFlag=false

        # check for conflict in flags that were  defined on the commandline when forkrun was called
        ${pipeReadFlag} && ${nLinesAutoFlag} && (( ${verboseLevel} >= 0 )) && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }

#        # check for inotifywait
#        type -a inotifywait &>/dev/null && ! ${pipeReadFlag} && : "${inotifyFlag:=true}" || : "${inotifyFlag:=false}"

        # check for fallocate
        type -a fallocate &>/dev/null && ! ${pipeReadFlag} && : "${fallocateFlag:=true}" || : "${fallocateFlag:=false}"

        # require -k to use -K
        ${exportOrderFlag} && nOrderFlag=true

        # setup delimiter
        ${readBytesFlag} || {
            ${pipeReadFlag} && { lseekFlag=false; lseekPosFlag=false; }
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
                    1) evfd_copy ${fd_write} ${fd_stdin} ;;
                    2) head -z -n ${nLinesReadLimit} <&${fd_stdin} | evfd_copy ${fd_write} ;;
                    3) head -n ${nLinesReadLimit} <&${fd_stdin} | evfd_copy ${fd_write} ;;
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

            order_init

#            printf '%s\n' {10..89} >&${fd_nOrder}
#
#            # fork coproc to populate a pipe (fd_nOrder) with ordered output file name indicies for the worker copropcs to use
#            { coproc pOrder {
#
#                export LC_ALL=C LANG=C IFS=
#
#                trap - EXIT
#                trap 'trap - TERM INT HUP USR1; kill -INT '"${PID0}"' ${BASHPID}' INT
#                trap 'trap - TERM INT HUP USR1; kill -TERM '"${PID0}"' ${BASHPID}' TERM
#                trap 'trap - TERM INT HUP USR1; kill -HUP '"${PID0}"' ${BASHPID}' HUP
#                trap 'trap - TERM INT HUP USR1' USR1
#
#                # generate enough nOrder indices (~10000) to fill up 64 kb pipe buffer
#                # start at 10 so that bash wont try to treat x0_ as an octal
#                printf '%s\n' {9000..9899} {990000..998999} >&${fd_nOrder}
#
#                # now that pipe buffer is full, add additional indices 1000 at a time (as needed)
#                v9='99'
#                kkMax='8'
#                until [[ -f "${tmpDir}"/.quit ]]; do
#                    v9="${v9}9"
#                    kkMax="${kkMax}9"
#
#                    for (( kk=0 ; kk<=kkMax ; kk++ )); do
#                        kkCur="$(printf '%0.'"${#kkMax}"'d' "$kk")"
#                        { source /proc/self/fd/0 >&${fd_nOrder}; }<<<"printf '%s\n' {${v9}${kkCur}000..${v9}${kkCur}999}"
#                    done
#                done
#
#              }
#            } 2>/dev/null
#
#            exitTrapStr_kill+="${pOrder_PID} "
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

                    if ${lseekPosFlag}; then
                        lseek $fd_read 0 SEEK_CUR fd_read_pos
                        lseek $fd_write 0 SEEK_CUR fd_write_pos
                    else
                        
                        IFS=$'\t' read -r _ fd_read_pos </proc/self/fdinfo/${fd_read}
                        IFS=$'\t' read -r _ fd_write_pos </proc/self/fdinfo/${fd_write}
                    fi

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
                trap 'printf '"'"'q\n'"'"' >&'"${fd_nAuto}"'; printf '"'"'q\n'"'"' >&'"${fd_nSpawn0}"'; [[ -f "'"${tmpDir}"'"/.run/pSpawn ]] && \rm -f "'"${tmpDir}"'"/.run/pSpawn' EXIT
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
                            t[0-9]*)  (( runTimeA[$kkProcsRun] += ${A[$kk]#t} ))  ;;
                            k[0-9]*)  kkProcsRun0=$kkProcsRun; (( kkProcsRun += ${A[$kk]#k}))  ;;
                            0)  ((runAllA[$kkProcsRun]++))  ;;
                            1)  ((runAllA[$kkProcsRun]++)); ((runWaitA[$kkProcsRun]++))  ;;
                            q)  break  ;;
                        esac
                    done

                    [[ -f "${tmpDir}"/.done ]] || {
                        # update count of lines / time for lines arriving on stdin
                        IFS=' ' read -r inLines1 inTime1 <"${tmpDir}"/.stdin_lines_time

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
                    pAdd_lineRate=$(( ( ( ( ( 1 + ${runTimeA[${kkProcsRun}]} ) * ( ( ( inLines * inTimeDelta ) + ( inTime * inLinesDelta ) + inTimeDelta ) / ( 1 + ( inTimeDelta << 1 ) ) ) ) + ( ( 1 + ( ${runLinesA[${kkProcsRun}]} * inTime ) ) >> 1 ) ) /  ( 1 + ( ${runLinesA[${kkProcsRun}]} * inTime ) ) ) - kkProcsRun ))
                       
                    (( pAdd_lineRate > pAddMax )) && pAddMax=${pAddMax}
                    (( pAdd_lineRate < 0 )) && pAdd_lineRate=0

                    (( pAdd = ( 1 + ( ( ( ( pAdd_lineRate << 1 ) + pAddMax ) >> 1 ) * ( 1 + runWaitA[${kkProcsRun}] ) / ( 1 + runAllA[${kkProcsRun}] ) ) ) ))
                    
                    # compare how much our lineRate increased to how much our worker count increased
                    # ideally, increasing kkProcs by X% will increase lineRate_run by X%
                    # if lineRate_run increases less than this then e are starting to hit other bottlenecks and should slow down new coproc spawning
                    # requires that coprocs have been spawned (by pSpawn) at least once already
                    (( kkProcs0 > 0 )) && pAdd=$(( ( (  pAdd * ( 1 + nProcsMax - kkProcsRun ) * ( ( ( kkProcs0 * runTimeA[${kkProcsRun0}] * runLinesA[${kkProcsRun}] ) + ( ( kkProcsRun * nCPU ) >> 1 ) ) / ( kkProcsRun * nCPU ) ) ) + ( ( runLinesA[${kkProcsRun0}] * runTimeA[${kkProcsRun}] ) >>  1 ) ) / ( 1 + runLinesA[${kkProcsRun0}] * runTimeA[${kkProcsRun}] ) ))
                    
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
                   
#                    runTime0=
#                    kkProcs01="${kkProcs0}"
#                    ((kkProcs01++))
#                    while true; do
#                        
#                        IFS=',' read -r -u ${fd_nSpawn} -d ' ' runLines runTime
#                        IFS=
#                        if (( ${runTime} < spawnTimeA[${kkProcs01}] )); then
#                            (( runLinesA[$kkProcs0]+=${runLines} ))
#                            #(( runLines < nLines )) && noReadLinesA[$kkProcs0]=$(( noReadLinesA[$kkProcs0] + nLines - runLines ))
#
#                            runTime0=${runTime}
#                            
#                        elif (( ${runTime} >= spawnTimeA[${kkProcs}] )); then
#                            (( runLinesA[$kkProcs]=${runLines} ))
#                            #(( runLines < nLines )) && noReadLinesA[$kkProcs]=$(( nLines - runLines )) || noReadLinesA[$kkProcs]=0
#                            runTimeA[${kkProcs}]=$(( runTime - spawnTimeA[${kkProcs}] )) || runTimeA[${kkProcs}]=$(( ${EPOCHREALTIME//./} - spawnTimeA[${kkProcs}] ))
#                            runTimeA[${kkProcs}]=${runTimeA[${kkProcs}]##+(0)}
#
#                            [[ ${runTime0} ]] && {
#                                runTimeA[${kkProcs0}]=$(( runTime0 - spawnTimeA[${kkProcs0}] ))
#                                runTimeA[${kkProcs0}]=${runTimeA[${kkProcs0}]##+(0)}
#                            }
#
#                            break
#                        fi
#                    done

                done

                # wait for spawned coproc workers to finish
                #[[ ${#p_PID[@]} == 0 ]] || wait "${p_PID[@]}"
                wait

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
    echo "{"
    ${nOrderFlag} && echo "order_get nOrder"
    ${pipeReadFlag} || echo "evfd_wait ${fd_nSpawn}"
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
        \${doneIndicatorFlag} || { 
          [[ -f \"${tmpDir}\"/.done ]] && {"""
            if ${lseekPosFlag}; then 
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
{ ${exportOrderFlag} || { ${nOrderFlag} && ${substituteStringIDFlag}; }; } && echo 'nOrder0="${nOrder:1}"'
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

        declare -p >"${tmpDir}"/.vars

        # # # # # WAIT FOR THEM TO FINISH # # # # #
        #  #  #   PRINT OUTPUT IF ORDERED   #  #  #

        if ${nOrderFlag}; then
            # initialize real-time printing of ordered output as forkrun runs
            outCur=0
            printf -v outCurHex '%X' "${outCur}"
            printf -v outCurHex '%X%s' "${#outCurHex}" "${outCurHex}"
            continueFlag=true
            outPrint=()

            while ${continueFlag}; do

                # read order indices that are done running. 
                read -r -u ${fd_nOrder0}
                (( outRead = ( 16#"${REPLY:1}" ) ))
                case "${REPLY}" in
                    +([0-9A-Fa-f]))
                        # index has an output file
                        outHave[${outRead}]=1
                    ;;
                    x+([0-9A-Fa-f]))
                        # index was empty
                        outHave[${outRead}]=0
                    ;;
                    '')
                        # end condition was met
                        continueFlag=false
                        break
                    ;;
                esac 

                # starting at $outCur, print all indices in sequential order that have been recorded as being run and then remove the tmp output file[s]
                
                while [[ "${outHave[${outCur}]}" ]]; do

                    [[ "${outHave[${outCur}]}" == 1 ]] && outPrint+=("${tmpDir}/.out/x${outCurHex}")
                    
                    unset "outHave[${outCur}]"
            
                    # advance outCur by 1
                    ((outCur++))
                    printf -v outCurHex '%X' "${outCur}"
                    printf -v outCurHex '%X%s' "${#outCurHex}" "${outCurHex}"
                
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
        #p_PID+=($(: | cat "${tmpDir}"/.run/p[0-9]* 2>/dev/null))
        if ${nSpawnFlag}; then
            read -r -u ${fd_nSpawn0}
            until [[ "${REPLY}" == 'q' ]]; do
                read -r -u ${fd_nSpawn0}
            done
            wait "${pSpawn_PID}" &>/dev/null
        else
            wait "${p_PID[@]}" &>/dev/null; 
        fi

        # print final nLines count
        (( ${verboseLevel} > 1 )) && {
            ${nLinesAutoFlag} && printf 'nLines (final) = %s    ( max = %s )\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}"
            # ${nSpawnFlag} && printf 'final worker process count: %s\n' "$(<"${tmpDir}"/.nWorkers)"
        } >&${fd_stderr} 
        
    ${nSpawnFlag} && printf 'final worker process count: %s\n' "$(<"${tmpDir}"/.nWorkers)" >&${fd_stderr}
    #${nOrderFlag} && kill -9 "${pOrder_PID}"


    # open anonymous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_nOrder0}<><(:) {fd_nSpawn}<><(:) {fd_nSpawn0}<><(:) {fd_read}<"${fPath}" {fd_read0}<"${fPath}" {fd_write}>"${fPath}" {fd_stdin}<&${fd_stdin0} {fd_stdout}>&1 {fd_stderr}>&2
    wait
)

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

export -fp _forkrun_SETUP &>/dev/null && export -nf _forkrun_SETUP

_forkrun_SETUP() {
    local -a filePathA

    local ARCH t tt k kk forkrun_git_branch outDir filePath fileCur downloadFlag localFlag  gotLoadableFlag b b0 doneFlag extglobState supportedArchFlag b64

    if shopt extglob | grep -qE 'off$'; then
	    extglobState='-u'
	else
        extglobState='-s'
	fi
    shopt -s extglob
    
    
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

export -f _forkrun_getVal

export -fp _forkrun_base64_to_file &>/dev/null && export -nf _forkrun_base64_to_file

_forkrun_base64_to_file() {
    local b b0 b1 k kk fd0 fd1 out0 out outC outN outF outB outFile nnSum noVerifyFlag doneFlag IFS extglobState
    local -a compressV compressI outA
    local -x LC_ALL=C

    # parse options
    if shopt extglob | grep -qE 'off$'; then
	    extglobState='-u'
	else
        extglobState='-s'
	fi
    shopt -s extglob

    [[ -t 0 ]] && {
        printf '\nERROR: pass the base64-encoded sequence on stdin. ABORTING.\n'  >&2
        return 1
    }

    # determine if we are outputting to stout or to a file
    exec {fd0}<&0
    if (( $# > 0 )); then
        [[ -f "$1" ]] && { \rm -f "$1" || return 1; }
        outFile="$1"
        : >"${outFile}"
        exec {fd1}>"${outFile}"
    else
        exec {fd1}>&1
    fi

    # read dataheader and data
    read -r -d $'\034' -u "${fd0}" out0
    read -r -d '' -u "${fd0}" out
    exec {fd0}>&-

    if [[ -z ${out} ]]; then
	    # if data header is mising then the base64 may have been made with standard base64 decoding. attempt to work with this.
        out="${out0}"
		grep -F '+' <<<"${out}" | grep -qF '/' && { base64 -d <<<"${out}" >&$fd1; return; }
        noVerifyFlag=true
        outN=0
        outF=''
        nnSum=0
    else
	    # parse the data header to get various parameters
        noVerifyFlag=false
        {
            read -r outN outB
            read -r nnSum_md5
            read -r nnSum_sha256
            mapfile -t compressV

        } <<<"${out0}"

        # determine checksum to use. prefer sha256
        if type -p sha256sum &>/dev/null; then
            nnSum="${nnSum_sha256}"
        elif type -p md5sum &>/dev/null; then
            nnSum="${nnSum_md5}"
        else
            noVerifyFlag=true
        fi

        # restore full base64 sequence
        (( ${#compressV[@]} > 0 )) && {
            compressI=('~' '`' '!' '#' '$' '%' '^' '&' '*' '(' ')' '-' '+' '=' '{' '[' '}' ']' ':' ';' '<' ',' '>' '.' '?' '/' '|')

            for (( kk=${#compressV[@]}-1; kk>=0; kk-- )); do
                out="${out//"${compressI[$kk]}"/"${compressV[$kk]}"}"
            done
        }
    fi

    # recreate binary from base64 sequence
	# this generates outF which is a string that contains the hex values formatted like: \x00\xFF\x9A\x...'
    # printf '%b' then will write out the binary data using that string
    while read -r -N 4 b0; do
        b0="${b0%%*([^0-9a-zA-Z@_])$'\n'}"

        [[ ${b0} ]] || break
        (( b1 = 64#0${b0}))

        if ((outN < 6 )); then
            printf -v b '%0.'"${outN}"'X' "${b1}"
            b="${b:0:${outN}}"
        else
            printf -v b '%0.6X' "${b1}"
        fi
        (( outN = outN - ${#b} ))
        printf -v outC '\\x%s' ${b:0:2} ${b:2:2} ${b:4}
        printf -v outC '%s' "${outC%%*(\\x)}"
        outF+="${outC}"
        ((outN <= 0 )) && break
    done <<<"${out}"

    printf '%b' "${outF}" >&"${fd1}"
    exec {fd1}>&-

    # verify output file and make it executable
    if [[ ${outFile} ]] && [[ -e "${outFile}" ]]; then
        chmod +x "${outFile}"
        (( outB > 0 )) && type -p truncate &>/dev/null && truncate --size="${outB}" "${outFile}"
        ${noVerifyFlag} || [[ "${nnSum}" == '0' ]] || { 
		    nnSumF="$("${nnSum%%\:*}" "${outFile}")";
			nnSumF="${nnSumF%% *}"; 
			grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; read -r -u ${fd_sleep} -t 2; \rm -f "${outFile}"; return 1; };
			};
    elif ! { ${noVerifyFlag} || [[ "${nnSum}" == '0' ]]; }; then
        nnSumF="$("${nnSum%%\:*}" <(printf '%b' "${outF}"))"; 
		nnSumF="${nnSumF%% *}"; 
		grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; read -r -u ${fd_sleep} -t 2; \rm -f "${outFile}"; return 1; };
    fi

    shopt ${extglobState} extglob
}

    export -f _forkrun_base64_to_file

    downloadFlag=false
    localFlag=false

    forceFlag=false
    outDir="/dev/shm/.forkrun/lib/${USER}-${EUID}"

    # parse inputs
    while true; do

        case "${1}" in

            -?(-)d?(ownload)*) case "${1}" in
                -?(-)d?(ownload)) downloadFlag=true; localFlag=true; forkrun_git_branch='main'  ;;
                -?(-)d?(ownload)?(=)local)  downloadFlag=true; localFlag=true  ;;
                -?(-)d?(ownload)?(=)*local*) downloadFlag=true; localFlag=true;  forkrun_git_branch="${1#-?(-)d?(ownload)?(=)}"; forkrun_git_branch="${forkrun_git_branch//?(\,)local?(\,)/}"; forkrun_git_branch="${forkrun_git_branch//[\"\']/}"  ;;
                -?(-)d?(ownload)?(=)*) downloadFlag=true;  localFlag=false; forkrun_git_branch="${1#-?(-)d?(ownload)?(=)}"  ;;
            esac  ;;
            -?(-)o?(utput)?(=)*)  outDir="${1#-?(-)o?(utput)?(=)}"  ;;
            -?(-)f?(orce)) forceFlag=true  ;;
            *)  break  ;;
        esac
        shift 1

    done

    gotFlamegraphFlag=false
    gotLoadableFlag=false

    # create required dirs
    mkdir --mode=1777 -p "/dev/shm/.forkrun"
    mkdir --mode=1777 -p "/dev/shm/.forkrun/lib"
    mkdir --mode=700 -p "${outDir}"

    # add to PATH and BASH_LOADABLES_PATH
    BASH_LOADABLES_PATH="${BASH_LOADABLES_PATH//\:${outDir}?(\/):/:}"
    BASH_LOADABLES_PATH="${BASH_LOADABLES_PATH#${outDir}?(\/)?(:)}"
    BASH_LOADABLES_PATH="${BASH_LOADABLES_PATH%?(\:)${outDir}?(\/)}"
    BASH_LOADABLES_PATH="${BASH_LOADABLES_PATH}${BASH_LOADABLES_PATH:+:}${outDir}"
    export BASH_LOADABLES_PATH="${BASH_LOADABLES_PATH}"

    PATH="${PATH//\:${outDir}?(\/):/:}"
    PATH="${PATH#${outDir}?(\/)?(:)}"
    PATH="${PATH%?(\:)${outDir}?(\/)}"
    PATH="${PATH}${PATH:+:}${outDir}"
    export PATH="${PATH}"

    ARCH="$(uname -m)"

    if ${localFlag}; then
	    # see if the files are available locallly
        for fileCur in 'forkrun.so' 'forkrun_flamegraph.pl'; do
            filePath=''
            filePathA=()
            if ${localFlag} && PATH="${PATH}:${outDir}:${PWD}$([[ -d "${PWD}/forkrun" ]] && printf ':%s/forkrun' "${PWD}")" type -p -a "${fileCur}" &>/dev/null; then
                mapfile -t filePathA < <(PATH="${PATH}:${outDir}:${PWD}$([[ -d "${PWD}/forkrun" ]] && printf ':%s/forkrun' "${PWD}")" type -p -a "${fileCur}")
                mapfile -t filePathA < <(printf '%s\n' "${filePathA[@]}" | grep -F "${outDir}"; printf '%s\n' "${filePathA[@]}" | grep -vF  "${outDir}")
                if (( ${#filePathA[@]} > 1 )) && type -p date &>/dev/null; then
                    t=$(date -r "${filePathA[0]}" '+%s')
                    k=0
                    for (( kk=1; kk<${#filePathA[@]}; kk++ )); do
                        tt=$(date -r "${filePathA[$kk]}" '+%s')
                        (( tt > t )) && k=$kk
                    done
                    filePath="${filePathA[$k]}"
                elif (( ${#filePathA[@]} > 0 )); then
                    filePath="${filePathA[0]}"
                fi
                [[ "${filePath}" ]] && {
                    chmod +x "${filePath}"
                    [[ "${filePath}" == "${outDir}/${fileCur}" ]] || {
                        \cp -f "${filePath}" "${outDir}/${fileCur}"
                        chmod +x "${outDir}/${fileCur}"
                    }
                    if [[ "${filePath}" == *'forkrun_flamegraph' ]]; then
                        gotFlamegraphFlag=true
                    elif [[ "${filePath}" == *'forkrun.so' ]]; then
                        enable -f "${outDir}/forkrun_loadables.so" getCPUtime && [[ $(getCPUtime) ]] && gotLoadableFlag=true
                    fi
                }
            fi
        done
    fi

    if ${downloadFlag} && ! ${gotLoadableFlag}; then
        # try to download the files
        : "${forkrun_git_branch:=main}"

        ${gotLoadableFlag} || {
            type -p wget &>/dev/null && wget https://raw.githubusercontent.com/jkool702/forkrun/${forkrun_git_branch:-main}/loadables/bin/${ARCH}/forkrun_loadables.so -O "${outDir}/forkrun_loadables.so" &>/dev/null
            type -p "${outDir}/forkrun_loadables.so" &>/dev/null || {
                type -p curl &>/dev/null && curl https://raw.githubusercontent.com/jkool702/forkrun/${forkrun_git_branch:-main}/loadables/bin/${ARCH}/forkrun_loadables.so >"${outDir}/forkrun_loadables.so" 2>/dev/null
            }

            if type -p "${outDir}/forkrun_loadables.so" &>/dev/null; then
                chmod +x "${outDir}/forkrun_loadables.so"
                enable -f "${outDir}/forkrun_loadables.so" getCPUtime && [[ $(getCPUtime) ]] && gotLoadableFlag=true
            fi
        }
    fi

    if ${forceFlag} || ! ${gotLoadableFlag}; then
	    # use the versions built into theis time.bash file

        # note: this base64 binary blob is generatred by using _forkrun_base64_to_file  on the arch-specific compiled shared .so file for the builtin.
        # passing this blob to the stdin of _forkrun_base64_to_file <path> will restore the original .so file (needed for the loadable builtin to get cpu time with getCPUtime) at <path>.
        # the .so file, source code and compile instructions are all available in the "forkrun" repo on github (https://github.com/jkool702/forkrun) at LOADABLES/SRC/forkrun.c.
        # The compiled .so file that this binary blob re-creates is avaiilable in the repo at LIB/LOADABLES/BIN/$ARCH/forkrun.so.
		# Note: these base64 blobs have been compressed. The information needed to decompress them is built into the start of the blob, as are the sha256 and md5 checksums for the original .so file

        supportedArchFlag=true
		case "${ARCH}" in
		    x86_64)

b64=$'66030 33016\nmd5sum:2722029594e18b2662d1464533f9bac0\nsha256sum:05dd2a63c11b0c38cb8c322e844eaab856649fc6dc2ebd2cfff8437ab712ba52\n00000000000000000000000000000000000000000000000000\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n0hQN9gAdvcyUObzk\n000000000000000\n00000000000000\n0000000000\n000000000\n00000000\n0000000\n000000\n00000\n0000\ncRj\n000\n0g\n00\n__\n0w?4g\034vQlchw81.{?c0fw01=1{7xV{>4?e?b04?7w0t?4<4#]_08]3Y0w[g[g<k;4{g[1}256M]8kr[1[1<1:M[3{c[wE}22w[4[4<6<E5Q]2wrg]a1J}c0A]102g[g[w<o>2Ung]bxJ}K6Q]30.]c01}2{4<1<aw2}G08]2E0w]3{c{8{g<4<S08]3o0w]dw2}9{A{g[k@lQp.>2E0w]aw2}G08}M[3{2[1gVnhA1<d1l}Q5k]3glg]4M[j{4[57Bt6g6~]1{kKlQp.>2wng]a1J}E6Q]1w0w]602[g[4<8;k>17jBk0.01M.<9{8?s04;g[4<5;c>17jBk0VMmDZFYoDsU_QZQ@iFOtPuUic0o~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~`?fcf7LF8w@M8i8I5ElY?4y5M7g2_Z18wYg8MM:_PnanM?_OncnM?3NZ?fYBOBY?6w;Wu3//_9s9v?1E.>eDg//_OmWnM?q08>3FMf//YBIBY?6w3<Wr3//_9qFv?1E1<eCw//_OmynM?q0k>3FAf//YBCBY?6w6<Wo3//_9p9v?1E1M>eBM//_OmanM?q0w>3Fof//YBwBY?6w9<Wl3//_9nFv?1E2w>eB0//_OlOnM?q0I>3Fcf//YBqBY?6wc<Wi3//_9m9v?1E2w>eAg//_OlqnM?q0U>3F0f//YBkBY?6wf<Wv3@//9kFv?1E4<eDw_L/_Ol2nM?q14>3FQfX/_YBeBY?6wi<Ws3@//9j9v?1E4M>eCM_L/_OkGnM?q1g>3FEfX/_YB8BY?6wl<Wp3@//9hFv?1E5w>eC0_L/_OkinM?q1s>3FsfX/_YB2BY?6wo<Wm3@//9g9v?1E6g>eBg_L/_OnWnw?q1E>3FgfX/_YBYBU?6wr<Wj3@//9uFu?1E7<eAw_L/_Onynw?q1Q>3F4fX/_YBSBU?6wu<Wg3@//9t9u?1E7M>eDM_v/_Onanw?q2<3FUfT/_YBMBU?6wx<Wt3Z//9rFu?1E8w>eD0_v/_OmOnw?q2c>3FIfT/_YBGBU?6wA<Wq3Z//9q9u?1E9g>eCg_v/_Omqnw?q2o>3FwfT/_YBABU?6wD<Wn3Z//9oFu?1Ea<eBw_v/_Om2nw?q2A>3FkfT/_YBuBU?6wG<Wk3Z//9n9u?1EaM>eAM_v/_OlGnw?q2M>3F8fT/_YBoBU?6wJ<Wh3Z//9lFu?1Ebw>eA0_v/_Olinw?q2Y>3FYfP/_YBiBU?6wM<Wu3Y/Z8zjS9oM?i8Q5wCc?4wV@7gli8I59BM?4y5M7g9_@0f7U:MMYvw;18zjRpoM?i8QRkCc?4wF_Ay9Y4z1XzZ8Mvw3i076id7@t1h8yMkZn>i8n0t0z_U6of7Qg?ccf7U:YMYu@E0Z5mc>1RaRl8wPQqn<4y9Vngci8QZTBA?ewV//W6j//61uRy>1nscf7M333N@:fcf7LHFt//MYvw;11lER7_A5lglhlkQy1Xb<23@04fxPk1?29_kybvwx9yvmW2w>37Shj7AW1T@/@9MUfZ0M@48w4?4Odr2gwytZ1Lw>w1cyuXEHvX/Un0ti18yQgAm4y5M7UmKw?1018et183Qrgi3T/M40j0Z7YAydfpMZ?3EHvL/Qy5M7guKwE<NZAy9N@yV_v/i8D5i8R0_QwZ_L/vTo3j8DRict490w1<j8DKh8DDW4f@/@5M0@8MM4?8J493xczmMA22k0Y>fg2<fxa8<NOj7SgrA5<ioDEytF4yuvEy_L/Qy5M7wu3UhZ.?yPSun>Kww>1cyuXEHvL/@L93NY0W3fX/@be8f_17iWWcvZ/Z8zjRpfg?i8D6cs3E9LL/Xw1<i874I<5JtglN1nk5uMV18zjRNd>cs3E0LL/@LqioJZ4bEa<cvrEUfP/Q69NeD6_L/3N@4:18NQgA4;1czngA44y9WkO9YAi9VEDvWdbY/Z8xs0fzMA1>fxd<3EDLH/UIUioD5w_Y4tdadh@G3UeYfxgw1?18znMA6ezK@/_xs0fy4U1?2bv2gscs2@2.?ez6@L/xs1@4QNzY4AVXw@2lw4?4MVZkAfh@VczngA2eIX3N@4:2bv2got5ANOj7SgrA5<ytHEmvH/Qy5M0@8M<8IZrBI?bE8<j8DSW7TW/@bl2gsioDEgrA5<csANZAi9V@wA@L/ioD0i8n0uqN1wTQ017joyTMA6ewI@/_yTMA7ewz@/_cs3FK_X/MYvg03EM_D/UIUW5PY/Z8zjSdeM?i8D6cs3EK_D/@Cg_L/pwYvh>yPTKmw?i8RQ90yW2<ezX@v/Wsj@/ZC3NZ4?3E6_P/QydfmsX?18ysoNMexW@v/Wk_@/Yf7Qg?46bvg3EZ_L/QydfmYX?18ysoNMexm@v/yTMA6eyd@L/yTMA7ey4@L/WhD@/Yf7U:goJZ0ey_@/_i8QZ8PI?4y9Nz70W1XV/_FY_T/Sof7Ug:8JY91MNM4y9WHU71>W4TV/@5M0@8z_X/UJY91MNMbU81>W3nV/@5M0@evLX/QNzYeBL_L/3NZ4?11lQ5mgll1l5lji87IG1>8f_0w@4Bw4?46Z:@fcw8?ewl@v/i8RQ912///Q69Nezz@L/yse5M0@5yg4?bY2<We_W/Z8ysp8xs0fzHI1?18KtIQJJu2TxJ3i8JY91x83W_Ui8DUic7_fQzTWkz1@x98ytl8avR8yTMAa4wfH_V8yvx8MvY_ifvFi8J492180QgA44wfHYp8yt58MvAii2DVi8QZGjE?4w1Pkw1NuzvZ/_ioD7i8n03Uiz.?i8D7W9LU/Z8zn0bi8DTi8BQ90zE6LD/Qybt2g8j8DVi8QlsjE?4y9NQC9Nz70WaXU/@@_M4?4O9Z@w1@f/xs1Q4eyEZ/_yPy3_N4fxgE1?1czrMAE<4m9U4O9Yj70i8QlhzE?bU04>j8D_W6DU/ZcyvvEkvz/QyddjgW?1cyv_EILD/QC9N4y5M0@4c04?4OdduoX?18yst8yuENM4O9ZKz_@f/j8DDWcvT/Z5xuQfxfo>18wsiE4>ytxrnk5sglR1nA5vMSoK3N@4:18yTU8w3YJtj@0vM5NtjC0vM80tjd1Lg4>3FlLX/@zHZL/yPzExfD/Qydfl8V?18ysoNMezzZL/KM4>3HDwYvg018zjkleg?hj7JW6DU/@5M44fBcnF5fX/Sof7Qg?4ydfigV>NMeyGZL/WYkf7Ug:ewH@v/j8DSi8QZd3A?4y9Mz70W8vS/ZcyvvEj_v/@Kq3NZ4?18zjSZe>cs3EqLr/@K53N@4:2@3M>4OdfpcU?3FmfX/MYvw;18yuVcyvsNMezXZL/Wvz@/_E8vr/UIUWbHU/ZcyvV8zjTse>i8D2cs3E5Lr/@AK//A45lyvANM469_k5ki8QlNPw?4C9ZbV;lld8wuN81>i8DDWcnS/Z8zjlOe>i8DDW1rU/Z8xs0fx4o1?18zmMAg4y9MHU01>i8D3i8DLW4nT/Z8ytZ8xs0fx1Q1?3E9fr/XUF<i8DLWavS/Z8xs0fx0s1?18ziRNe>i8RU0ky9XKzrZ/_i8n03UjH<cvZ8yuXEOfv/Qy5M0@4S<37_i8DKWbnT/Z8yst8xs0fxc8>2W2w>37SKMA>3Eafv/Q69h2g43NY0cvZ8yuXExLv/UfH0nnNi8n03Uih<i8DKcv_ErLv/XEa<cvp8ysvET_j/Qy9Xz7_ioB490zEkfv/XEa<cvp8ysvEMvj/Qy9Xz7_ioB4913EcLv/XEa<cvp8ysvEE_j/Qy9Xz7_ioB491zE5fv/XEa<cvp8ysvExvj/Qm9b2h9ykgA84y1N4w4>NM5JtglN1nsfE1_n/Qy1N4w4?2U//_RJtglN1nscf7Q?kQ69@4y9Yj70Lw.?18zhkbdM?i87I41>4ydn2ggi8DvW2vR/Z8zjnkdw?i8DvW7zS/Z8xs1Qe4y9NQy9MP70ict490w;i8Rk90x8zjnJdw?W47Q/Z8yt_Eyvj/Qybh2g8i87441>5L3cs3HYMYvw;11l4yddnIS?18zjSYdw?lld8wuM?w?W1bS/Z8xs0fx8M>18yut8ysa@?8?4y9M@x6Zv/i8n0t0C1f2hzs7kwt20NXky9T@wuZf/i874?8?4y9W5JtglP33N@:4Od9mIS?18znMA14O9VKzkZv/i8D7i8n0tcgNXmoK3N@4:2W2w>37SW6jP/YN_QO9VAw1NuyDZv/i8D7i8n0tt_HBP7JWVJC3N@4:11lQ5mgll1l5lji87IC<4ydt2gYW4nR/Z8zjnWdg?j8Iwi8D3j8DDWa3Q/@5M0@4A04?4yddgES?1cyuvEyvj/UD5xs0fxds>18zjk8e>j8DDW73Q/@9Non03UjS0w?i8QRBPo?4O9V@xnZf/xs0fxaY3?18zjmadw?j8DDW43Q/@9Non03UgS0w?i8QRsPs?4O9V@wDZf/xs0fx1s5?18zjladM?j8DDW13Q/@5M0@4@0k?4yddp8S?1cyuvE@vf/UD5xs0fx1A4?18zjnyd>j8DDWe3P/@5M0@4Lwo?4yddrUS?1cyuvEOvf/Un03Umh1w?yTMAf4y9TKx5@v/ysnFxM>6of7Qg?8dY93M23Uhi0M0.rP//_3U_Y1>yMkLkM?Lw4<NOrY1<ict496o;KL//@9h2hwyMk7kM?pEBQ96i@0w>6q9v2hIi8RY961CykMArEB496zENvf/Un03Uyd1g?ZAgApw4fxqk2?3Sh2hK.@5Fgg?4y9T@xfYL/i874C<8DEmRR1n45tglV1nYcf7M2br2gYgoD5zknZw_w23UsZ0w?i8JX2bEa<cvrEdvf/Q69NEn03Ux2.?W2nN/Z8yTIgcvqW2w>cs:4C9NewsYL/gocY9298yggA3UgI1g?w_Q33UhG0M?j8JX64yddvkP?1cyv_EAvb/UD2xs0fx3g2?18zjnBcM?j8D_W7zO/@5M0@4Uwg?37.o0_0bE1<j0Z4@8fZ1g@47.?4ybd2h4yvvEPf7/Qy3@fYfxdw4?1dxvYfxfA4?18zmMAo4y9MrUw<cs18yuZ8zhmecM?W5LN/Z8yuUNQAO9_@xeYL/cuTFUfX/MYvw;14ySgAf8IZBl4?4yU////_TZ8ykgAg463_04fzWA1?18zngAgbE8<W8TM/Z8w_w83Uis_L/W0XM/@be8f_2M@4zfX/@yuYL/i8QZZjc?4y9Nz70WfTL/_H6MYv04ybsMx8zjSRag?cs3EVK/_Sof7Qg?bQ1<Wk_@/ZC3NZ4?2bfgVh?25_Tw5W07N/@bfvJg?25_Tw5WfbM/@@?w8037_W2rO/@91uhg?25M0@8wg8?bU120w0cv_E3fb/UA5NB>8n03UwT0M?j8RA962b2Htg?1cziQzcw?cs1cyuFcyuu@8<ewWYf/ct9cyup8zjQicM?W2DN/@b2Edg?1cyuENM4O9VXUw<W17M/YNQAO9VAydfvcO?3E0f7/@Ck_v/3NY0i8QZIiw?370W0HL/_F9v/_MYvh>yTMAf4y9TKykYL/ysnFpLT/UIZaR>4ydt2h0Kww>3Emf3/Qy3@0xRtkm5V0@8gLT/QyddiQO?14yusNMew8Yf/WiPZ/Z5cv_FWLT/QybuMyW2w>37SW8LM/Z1ysjFELP/QybuMyW2w>37SW7fM/Z9ysl1w_M33Ugh1w?3UVs1w?i8QZCiw?370W6bK/_FvvX/@x8XL/Lg4>2beezsYf/i8QZAz4?4y9Nz70W3LK/_FH_P/UdY93M23Ulk1w?i8I5D5g?4y5M0@4ZMo?bA1<Y4wfMgx8zhl5cw?Lx4<NM4Odp2h0j8DDWdrK/Z8zgEKcw?i6fg3Xok4oxk9618zlgAoofU20@34wo?aw43Uk22>xs1Q4g@Sj2h0y4MAoqw23Uk52>wY01i8RQ960NQAyoNAg4o018yTI8W7_L/_F4_P/Qy9NHE1<h8DTWaHK/Z8w_z_3UiS.?i8D6i8QZyj>370cuTEbuX/@Dx@/_yPSCjw?xvZU1uypXL/yPSjjw?xvZU1uyaXL/i8QZ1P4?37JNMlTjw?//_Ys5skU?f//_EWeX/QydfuYM?3ETeX/@Cg@/_W0bJ/@beeyrX/_i8QZA3>4y9Nz70WfHI/_F5vT/Qydfh4M>NMezDXf/WgbZ/@bfhNe?18zngAgbE8<W4TK/Z8w_w83UjN_v/WaXI/@Z.>8IUW4bL/Z8zjQpc>i8D6cs3EEuP/@Al@/_i8JH881Z>fxec>18yPgAh8DTWabJ/Z8w_z_3UiK<ioDLWtvX/@3v2gY.@5XMc?4yb1tpi?18xs0fx4A4?18NM:cuTFMfH/@wOXf/yPzEO@X/QydftML?18ysoNMewGXf/yPREjg?W5_J/_71lBd?3//_Wj3Y/_E@@L/UIUW9jK/Z8zjQSbM?i8D6cs3EY@L/@Ae_f/hj7_Kw8>3F8fL/QybsN18zjT69g?cs3EP@L/@DG@/_goIY9exhXL/i8QZH2U?4y9Nz70Wb3H/_FO_L/Q6Z.>eDE@L/honJ3Ugn_L/cuTF2vH/QO9VAydfhUM>NMex_W/_WpHX/ZcoSgAf463_04fzxY4?15znMA_QkNXkC3X059oYt8ykgA24z1U098yst8ykgAaexSXf/i8D53NY0iof50rEa<cvpayPPHW1PJ/Z2ykiJ_4QVVnnyi8QZwyY?eyCW/_i8A494y5M0@4awg?bY0a>hj7JW2PI/Z8NQgA8?1?18ykgA64ydh2hwi8B4910f7Q?i8IY9eznXf/i8n03UiD<h0@Ss1dcznwjhojSt3DEy@T/Qybc4O9@6pCbwYvx]pyUf7Ug:44fJJrSh5o127iRh0@Ss058wY01hojStusNZAO9_XEa<W6zI/Z8yTgA48D7W5PQ/@5M7m8j3BI920fxes2?18yQMA66ofrQgAo4KdhaQ0iof50kyd1c4f4g1C3SZ4970f4k.i8Kk98<18yl0wWkv/_Z8yPMAW8XH/Z8wTMA6?fx3c3?1cyTMAa4O9_@wRW/_j8DWi8DKi8D7WcvH/Z8ystdxuQfxis3?15csB5cvp8wTMA2?fx7M>1dxuQfx1U1?16yMifi8J491wNQKIk3NY0i8f20ky3M2x9etkfx281?2bc4gVNDnEct9C3NZ4>Xt9k03Uj@<i8f20kMVUDnJYMZLg1x8yR08iof10kw3k11C3S_8j07OpwZPSgxC3Zj1pAAfvIp90tpcekMA27mdW2zG/Z8yTMA6ewuWL/i8QZRyI?ewiWv/ioD5i8n03Ugz0w?i8D7WcXF/Zcznwbj8D_W5bG/ZcyuBcyvV8zhmHaM?i8A494y9NP70hj7JWejF/Z5cv@ggEJYLg18yPgAiof70ux@Zf/ig75jjDDtup8yPMAjg7RWaHF/Z8yuYNXuywWv/WdLQ/ZcyuV8zjR3bg?i8D2cs3Et@D/@AHZ/_iof10kMVj2g8tvl5cvrFgL/_MYvw;18yR08i0dg44A1RAybh2g8iof10kAVMg@5G_X/@Ap//i8QZt2M?exGWf/WonU/_Ekez/QybuN2W2w>4ydt2hwNM:ioD4W5jE/Z1yNgAxt8fxvQ>18yRgAo80W?@5XM>4yW////_TZ8et183Qv2i8B49414yu_FQfv/QkNOj7_grz//_Ki4>2W0M>bU8<W9TE/Z8w_z_3Ujy<i8A5l4U?eC2@/_i8QZa28?370WcDD/_FVfv/Qybj2h0i8RY96x8ykMAooD1ioJQ3fx8ynga@4wF@AO9UkwFQg72w@bUw_E83Ubp@v/w@bUcvp1yv23NwxeyMM1jEAc1PDmsKXFLvD/Qybh2gwi8JY91x8zji0j8QY04z1VwjEi@z/QO9v2gwi8B491zFX_P/QydfpkH?3Egev/@BrZ/_i8JP44ydfk0x>NMewFV/_WkjT/Z8zjSt8g?W1zD/_Fc_v/Q6_3M>4OdbkkF?3FR_T/@zIVL/yPzExuD/QydfgEH?18ysoNMezAVL/Wv_S/Z8zjR5aM?cs3EQur/Qy9X@ypV/_WujS/ZcyTgA26pCbwYvx]3NZ?4S5Zw@4PM>4Obj2gocvp5cs11yN5dysYf7U:cs3H5mpCbwYvx]A4y3M05cev1Q7PAkxTnOiof?kQVNnhViof7a46b5QS9@uLd3NZ4?11yR44cs3H2ky3M05cev1QhPIkxTnOiof60kO9h2ggiEQkJg<1cykMA24y9RAy952jE4ev/QObj2g8i8Ik9bU1<i8D7j8J49111yM69h1vYWU@giof?kQVW7me3N@:8nS3UkU//j8BQ90zFY_L/Sof7Qg?4C3_g4fxn7Y/_HV8Jc9429j2hxys51yTgc_8BQ2LPF@_v/UD1gg@Tt0P@pEBQ2LXFWvv/Sqgi8fI24ybfsR4?2@.>exbWf/i8IZX4g?bU1<W3HE/Z8yPSbh>Lw4>3Eauz/QybfoF4?2@.>ewoWf/i8IZAkg?bU1<W0vE/Z8yPSMh>Lw4>3EZKv/QybflZ4?2@.>ezBV/_i8IZtAg?bU1<WdjD/Z8yPRlh>Lw4>3EM@v/QybflN4?2@.>eyOV/_cs18wYg8MM>fcf7LF8w@M8i8f42cc~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#0M>3k<1<1w>98987dd201adg>3w<Y<UJ4_ClyCfOzpAGNbDcZcSCERAzg0hXu2oSX1Q0zohjey9NmVNbX0NysCOnA#?1H<4w%F.?4w^1_<4w%g<8%2p<4%1a.?4w^1O<4w%W.?4w^3I<4w^2R<4w^1V<4w^2X<4w%6.?4w^2L.?4w^3k<4w^3t.?4w^2o.?4w^3O<4%3z<4w^3y.?4%1P.?4w%q.?4w^24.?4w^3r<4$7.?4w^2n.?4w^2M<4w^3d.?4w^2i.?4w%k.?4w%a.?4w^3@<4w^2v.?4$1<8%3m.?4w^2x.?4%1l<4w^2T.?4w^2D<4w^1K.?4w^1s.?4%3U<4w^32<4w%y.?4w^3c<4w^2a.?4w%I<8%2g<4w^1B<4w^16<8w%o0w?4%2_.?4w%R|0n021S}c[1Y|0n021R}c[3H.?4w050c0G}Jg[b|0n0a1S}c[1n|0n0a1R}c{A|0n061S}c[1G|0n061R}c[16|0n0e1R}c[2v|0n0a1Q}c[2e|0n0e1Q}c[2N|0n061Q}c{0nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0nRZzu65vpCBKomNFuCk0nRZFsSZzczdvsThOt6ZI06pPt65Q06tBt6lKtw1Ps6NFoSk0tT9Ft6k0nRZBsD9KrRZIrSdxt6BLrw1Pt79BsD9Lsw1ytmBIt6BKnSlOsCZO07dBrChCqmNB071Fs6k0pCdKt6M0pSlQs6BA06tBt79RsS5Dpg1PundzrSVC07dQsCNBrw1Urm5Ir6Zz07dKs79FrDhC06RHp6BO07xCsClB06pLs6lK06pMsCBKt6o0pCdIrTdB07dQsCdJs01CpSlQsM1Pt79OoSxO07dQsDhLqM1vnSBPrScOcRZPt79QrTlI05ZvqndLoP8PnSpPoS5Kpw1vnSBPrScOcRZPt79QrTlIr01JomJBnS9RqmNQqmVvon9Dtw1MrSNI05ZvqndLoP8PnTdQsDhLr6M0r7dBpmI0pnpBrDhCp01Opm5A06hMsCBKt6o0tmVyqmVAnTpxsCBxoCNB06ZMpmVAqn80sClxp6hFsw1vnSdQun1BnS9vr6Zz06dIrTdBp6BO06RBrmdMug1Jrm5M07xOpm5Ir6Zz07dBt7lMnS9RqmNQqmVvpCZOqT9RrBZIrS5Aom9Ipnc0r7dBpmJvsThOtmdQ065Ap5ZytmBIt6BK06lSpChvqmVFt5ZPt79RoTg0pnpCp5ZTomBQnTdQsDlzt01BtCpAnSdLs7BvsThOtmdQ06lSpChvsSBDrC5InTdQsDlzt01BtCpAnSdIrTdBnTdQsDlzt01LsChBsBZFrCBQnTdQsDlzt01LsChBsBZDpnhvsThOtmdQ06dEqmNAtndxpSlvsThOtmdQ06dMtnlPomtBnTdQsDlzt01Iqm9zbDdLbzo0hQN9gAdvcyUP04tcik93nP8KcPc0hQN9gAdvcyUT04tcik93nP8Kcjg0hQN9gAdvcyUR04tcik93nP8KcPw-<2?c?w01?4?M04?c?w02?8?w02?8?w02?80.02?4?M02?80.02?8?w02?8?w02?80.01?k0.03?8?w02?4?w02?8?w06?4?w07?80.08?40.01?40.01?40.01?40.<401M310w?4{jqmAa>80cI2>g<IV6m1w?1M3l0w?4<1tFqgE>o0U08?1<2kApo6>50eE2>g<5mBF2w?103R0w?4<byhBwo>c0_M8?1<1R6CA9>2?E3}E6Q}8[f0j}G6Q}8[b0j}I6Q}8[b1J}M74}8[,}O74}8{xb}Q74}8[,}S74}8[3xb}U74}8[7xb}W74}8[c1b[78}8[,}278}8[f1b}478}8[,}678}8[1xc}878}8[61c}g78}8[,}i78}8[1hl}k78}8[,}m78}8[91c}o78}8[cxc}w78}8[,}y78}8[2Jl}A78}8[,}C78}8{1d}M78}8[,}O78}8[3Rl}Q78}8[,}S78}8[3xd[7c}8[,}27c}8[6xd}47c}8[,}67c}8[a1d}87c}8[dxd}a7c}8{1e}g7c}8[,}i7c}8[31e}k7c}8[,}m7c}8[61e}o7c}8[9xe}q7c}8[4Zl}w7c}8[,}y7c}8[6Jl}A7c}8[,}C7c}8[d1e}E7c}8[11f}G7c}8[,}I7c}8[41f}M7c}8[,}O7c}8[8Bl}Q7c}8[,}S7c}8[8xf}U7c}8[d1f[7g}8[,}27g}8[11g}47g}8[,}67g}8[4xg}87g}8[,}a7g}8[81g}c7g}8[c1g}e7g}8{xh}g7g}8[,}i7g}8[41h}o7g}8[fFi}q7g}8[30t}u7g}8[c1N}w7g}8[6xh}E7g}8[eRk}G7g}8[30t}K7g}8{1O}M7g}8[9Fl}U7g}8[95k}W7g}8[30t}@7g}8[41O[7k}8[1Jl}87k}8[39l}a7k}8[30t}e7k}8[81O}g7k}8[39l}o7k}8[4hl}q7k}8[30t}u7k}8[c1O}w7k}8[4hl}E7k}8[49k}G7k}8[30t}K7k}8{1P}M7k}8[9xh}U7k}8[3xk}W7k}8[30t}@7k}8[41P[7o}8[cxh}87o}8[7Bj}a7o}8[30t}e7o}8[81P}g7o}8[bpl}o7o}8[91l}q7o}8[30t}u7o}8[c1P}w7o}8[91l}E7o}8[4Nj}G7o}8[30t}K7o}8{1Q}M7o}8[f1h}u6Y}6<dg=w6Y}6<1+y6Y}6<f+A6Y}6<dw=C6Y}6<e+E6Y}6<eg=G6Y}6<fg=I6Y}6<8w=K6Y}6<fw=M6Y}6<fM=O6Y}6<ew=Q6Y}6<eM=S6Y}6<bM=U6Y}6<cw+7[7;g=27[7;w=47[7;M=67[7<1g=87[7<1w=a7[7<1M=c7[7<2+e7[7<2g=g7[7<2w=i7[7<2M=k7[7<3+m7[7<2w=o7[7<3w=q7[7<3M=s7[7<4+u7[7<4g=w7[7<4w=y7[7<4M=A7[7<5+C7[7<5g=E7[7<5w=G7[7<5M=I7[7<6+K7[7<6g=M7[7<6w=O7[7<6M=Q7[7<7+S7[7<7g=U7[7<7w=W7[7<7M=Y7[7<8+@7[7<8g+74}7<8M=274}7<9+474}7<9g=674}7<9w=874}7<9M=a74}7<a+c74}7<ag=e74}7<aw=g74}7<aM=i74}7<b+k74}7<bg=m74}7<bw=o74}7<c+q74}7<cg=s74}7<cw=u74}7<cM=w74}7<d+pnpCp5ZzrT1Vey1RsS5DpjEwpnpCp5ZzrT1V83NLtnhvpCg@85JFrBZCp5Q+1IsSlBqPEwqmVzrT9OpmdQ86VRrm9Bsy1Lpy1xsCtRrmlKt7c;r7dBpmIW86BKtC5IqmgwpCBIpi1ApndzsCBMt6ZO82sBsOs:6NPpmlHey1LpCpPpngwrTlQ86ZC879xrCtB82sBsOs0pnpCp5ZPqmtKomMW86BKtC5IqmgwoSZRrDgw9OlP9M1BtCpAnTdFpSVxr3EwtT9LrCswrDlJoClO86ZC865OpTc[rT9Apn9vpSlQey1RsS5DpjEwrT9Apn9vpSlQ83Nmgl8@[6ZOp6lOnStBt3EwoSZRrDhBsy1KrTgwqmVFt6Bxr6BWpmg]1lkQ57hjEwoT1RtndxpSkwf7tLsCJBsBZMqmg@85JTrT9Hpn9vs6BA82UKbBQ>13rSRMtnhB87hLt65I84dgli1QqmRB86pLsy1TrT9Hpn9P865Kp21Qq6lFsy1ApndzpmVAomVQsOU[gmhAsO1CqmVFsSxBp213k5kwt6BJpi0EpD9Lri0KoT1RtndxpSkwpCBIpncF82Iwr6BSpi0Ls79LoO1QqmRBsOU[jTlQs7lQsPEwf5hfl45cnQdgllZkikR5fy0YkRBjl4ldnQdgllZkikR5fw:lld1hQkW86dEqmNAtndxpSkwmO0Jsi1Y82QJsnlFpngwng]59BoSZOp21CqmVFsSxBp21zq6BIp79BrytP84dgli1QqmRB87hL82hXt6RMh6BOviYKoT1RtndxpSkLoT1RbzNgikg@bw>4BC82sJsiswrT8w9OQJsnlFpngD86BP86tFtClKb21Ptn1MsClPsO1LtnhMtngK045QrSRFoS5Ir7AwoDlJs21x87dEon9Bp21zrTlKt6lO865Kp21Pt6ZOpi1Ft21Fry0YlA5ifw?oncwoi0NdyRAqmtFt2MwuClOrORMomhApmgwtn1Mpn9zondB86xBu21Pt79FrCsK{19rCBQqm5IqnFB864wsSxxsClA83oQbm9Ft21zrTlKt6lO86pLsy1LsChBsBZDpngK[4dIrTdB869Lt6wwpnpBrDhCp7cwomVA87lKsSlQ87pxsCBxoCNBsOU{5ljgkt5ey1BtCpAnTdFpSVxr21rf7hBsCRvpCg@85IYqmVzsClJpmVQnSdLtmVQfBQwng:kSBDrC5I84lfhzEwtT9Ft6lP83NFrCdOpmRBrDhvoSZRrDg@87hL83NQpn9JnSpAfw[w820wh6lConlIt21Qpn9JnSpA86BP84lmhAhvl4lijg{820w84hBpC5Rr7gwqmVzsClJpmVQnSdLtmVQ86BP85l9jBgSd5Zdglww82Ywcw?lld1hQkW86lSpChvoSZMui0YrTlQs7lQnSpAfy1rf6BKs7lQnSpAfBQ[gSZKt6BKtmZRsSNV87dMr6Bzpi1CsCZJ87dQp6BK87hL86ZRt71Rt5ZCp21Fry1zq7lKqTcK?11pDhBsy1BomdE86dEtmVHb21PqmtKomMwpnpBrDhCp21QrO1TomJB879BomhBsDcK[5txqngwtmVQqmMwp65Qoi1FsO1xtC5Fr65yr6kwt6YwsClxp21Lsy1xry1BtClKt6pA86BP87dFpSVxr6lA?1yui1MrSNIqmVD869Lt6wwpnpCp5ZAonhx865Kp21BtCpAnThBsCQK{0YrCZQqmpVnSpAfzEwjT1QqmZKomMwhAgwt6YwtT9Ft6kw9P0D82xKrO1TomBQai1Lsy0Dciswa7txqnhBp2AK{1FrCBQqm5IqnFB87hTrO1BtClKt6pA9TcI87dQrT9B84p486VRrm9BsDcwqmUwhlp6h5Z4glh1865Kp215lAp4nRh5kAQK?1dtndQ869B86dxr6NBp21LrCdB869BpCZOpi1RsSBKpO1BtCpAnTtxqngwbO1BtCpAnTdFpSVxr2U[lld1hQkW86NPpmlH83N6h3Uwf4Z6hBd5l3UwmPNjhklbnRhpk4k@ni1rf5p1kzVt{1drTpB87hEpi1DqnpBry1CqmNB86hBsSdOqn1QrT8wf4p4fy1yui0YjQp6kQlkfy1yunhBsOU?2QwkQl5iRZkml1582xLs7hFrSVxr2AW85d5hkJvkQlkb21jhklbnQdlky0Ep6lConlIt2AI85d5hkJvhkV4>J85p1ky0ErT1QqmZKomMFey19py1DqnpBryMwsThLsCkwrClT86pFr6kwrSpCsSlQ86BK87pxsCBxoCNB85p1kyU}J84BC85p1ky1FsO1Brn1Qui0E9OsFb21BrC5yr6kwsnlFpngwrmZApi0ErCYwrTlQs7lQaiU?59Bt7lOrDcwrClT86ZCpDdBt21Lsy1Pt6ZOpncwqngK{1zs7lRsS5Dpi0YtSZOqSlOnT1Fp3UwmPNTrT9Hpn9vs6BAfy1rf2UKbzVtng<1BtCpAnTdFpSVxr21rf7hBsCRvpCg@85IYqmVzsClJpmVQnSdLtmVQfBQwng<1BtCpAnSdLs7Awf6ZRt71Rt5ZCp3UwmPNFrD1Rt5ZCp3Vt}r7dBpmIwf4p4fy0YjQp6kQlkfy1rf5d5hkJvl5BghjVt85IYlA5ifBQ0hAZiiR9ljBZ3i5leiM1BtCpAnSdLs7AW86pPt65Qa6BKpCgFey0BsM1BtCpAnSdLs7AW87dBrChCqmNBey0BsM1BtCpAnSdLs7AW871Fs6kW82lP06lSpChvoSZMujEwsT1IqmdB86ZRt3Ew9nc0pnpCp5ZzrT1Vey1Ps6NFoSkW82lP02ZQrn?biRNtmBBt01lsS5DpjEwoSxFr6hRsS5Dpi1r82RN85Q0pSlQsDlPomtBey0BsM1PundzrSVCa5ZjgRZ3j4Jvl4dbai1ComBIpmg0t6RMh6BO02lPbOVzs7lRsS5Dpg1JqShFsy0BsPEw9nc09ncLoT1RbylA07s0pCZMpmUw9ncW82lP02ZMsCZzbOlAbTdQong09mNItg0Ls79LoOZPt65Q06dMti?r7dBpmI0r7dBpmIW82lP05d5hkJvkQlk05d5hkJvhkV402lIr6g09mNIp0E0pnpCp5ZTomBQ06lSpChvtS5Ft3EwtT9LrCswon9DsM1BtCpAnTtxqngW871Lr6MW82lP06lSpChvtS5Ft3EwsClxp21AonhxnSlSpCgW82lP030a06lSpChvtS5Ft3EwsClxp21Qpn9JnSlSpCgW82lP06lSpChvqmVFt3Ewp65Qoi1BtClKt6pAey0BsM1BtCpAnSBKqngW87hBsCQwpnpBrDhCp3Ew9nc0hlp6h5Z4glh104lmhAhvl4lijg1BtCpAnSdLs7A0pnpCp5ZPqmtKomM0pnpCp5ZPqmtKomMW87tOqnhBey0BsM1LsChBsBZFrCBQey1TsCZKpO1xsCtP06ZOp6lOnSBKqngW86RJon0W82lP06ZOp6lOnStBt?Br7w0c34OcPgRdzsUek52gQh5hw1zs7lRsS5DpjEwrmBPsSBKpO1gikhP02ZMsCZz06dMtnlPomtBey0Ls79LoO1ComBI02lIr7kw9mNItgE0oSxFr6hRsS5Dpg1CszEwtmVHrCZTry1Ptm9zrSRJomVA82sBsOs0lld1hQkW86ZOp6lOnStBt20YlA5ifw1lkQ57hjEwrT9Apn9vqmVFt01lkQ57hjEwpnpCp5Zzr6ZPpg14pmpxtmNQ83NFrD1Rt5ZCp3UwqncwsThAqmU0lld1hQkW86lSpChvtS5Ft5IYrCZQqmpVnSpAfBQ0lld1hQkW86lSpChvqmVFt01zq6BIp7lPomtB85Iwbn4wv20Jbn5RqmlQ85Q0pnpCp5ZTomBQ85IYrCZQqmpVnSpAfBQ<16McXj;w>1gKL/q<32@/@g<Mc7/Zw>20Nf/a04?236/ZQ.?Ecr/Vw1?1wN/_P04?f3k/Ys0w]1g{nFi?5U404r30s8A04?2g<s<UbD/O03<3x163xxa3MJT28?fNEXazcA8w<14<h<9yZ/@b0M>48e48U2hgUozgd23y2c144ea8o5ggUMwMp73K010Pg12wUMggUEggUwgwUogwUggwU8gwI>1c<z<e30/@_0w>48e48Y2gwUozwd23y2d148ea8M5ggUMxwp13zy31QseU243y04a3zx33z113yx23y123xx23x123wxb2M>4w>3s<kcf/VM1<gwUgzg993xyc0R0e88o4ggUEwMl73L080Rw12wUEgMUwggUogwUggwU8ggJc3yx63y113xx23x123www<a04?aj4/ZV;44e48c2mMWw809n2wUgggU8ggIM<j04>35/@T;48e48M2jMUoxwd13y2314seE.2g0Ee84ge644e448e24wbj<801?2cNv/zwE>123x2f0A8e68U3gwUwzgh23yyc1k4ec8o6ggUUwMt73J010Ws12wUUgMUMggUEgwUwgwUogwUggwU8h0I<k<Q04?cPi/@R;4ge40aM3ww~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~=f0j}I1c]2Mrg}4[Mg8}c{.}2w}1UaM]1A[E6Q}r{w[6w}2Erg]1M[2[3R_LZL]M}1g}1gdw}o[k3[a[1o3}2M[o{c[W6Y}2[9w4}5{7[1s[c4k}7[6wW}2[382w}A[6[3@/ZL;ewV}//rM;1[f3/SY;pzA]3V/ZL;6k~~~~~+K6Q#dx}164}5og}px}1S4}8og}Bx}2C4}bog}Nx}3m4}eog}Zx[64g]1oh}9x4}S4g]4oh}lx4]1C4g]7oh}xx4]2m4g]aoh}Jx4]364g]doh}Vx4]3S4g}oi}5x8}C4w]3oi}hx8]1m4w]6oi}tx8]264w]9oi}Fx8]2S4w]coi}Rx8]3C4w]foi}1xc}m4M]2oj}dxc!3/////M#?,}24I]3dkM]3xb}u4I]30iM$?3dkM]f1b}Plc}oj}61c`Plc}klg],}A4M]38j`,}aRk]3dkM}1d~3dkM]3Rl}Plc}Ujg~Plc]1Ejg],}E4Q]3ojg}1e#,}c4U]3dkM]61e}C4U]1flg$?3dkM]6Jl}Plc]3gjw]11f}Plc]10jM)Plc]29lg],}y4Y]3gjM!,}45}3dkM]4xg}Plc]20k}c1g}254]3dkM]41h#fFi}c1Q}1[c1N}q54!3Jl}30t[g{sw]9Fl`Alg}M7g}4[g78}rlg!39l}c1Q}1[81O}cBk!14lg]30t[g}30sw]4hl`gBg}M7g}4{7c]2okg!3xk}c1Q}1[41P}O54!1VkM]30t[g}20sM]bpl`A5k}M7g}4[M7c]2glg!4Nj}c1Q}1{1Q}Y54)4t3gPEwa4teliAwcjgKcyUN838MczkMcj4M82xipmgwi65Q834Qbz8KciQTag<w<g:4?4t1904Poj4.1c]104M}w<g:4?4t1904Poj4?1[m4[w<g:4?4t1904Poj40u2I]20aM}w<g:4?4t1904Poj4.1c]3V4M}w<g:4?4t1904Poj40tiI]1RaM}w<g:4?4t1904Poj40tiI]1RaM}w<g:4?4t1904Poj405x[r4[w<g:4?4t1904Poj40w2I]25aM`4<40f7_&0E<2?k.1c(Y<2?k0s1c)28<2?k0I1c)3w<101w0Q7o}1[4g<10180G6Q)6I<2?k0Y1c)7s<10140E6Q^40f7_&9o<2?k?1g]2b0M]ak<101s0F74}4[aY<2?k0A1s]2_0w]bY<2?k0k1E]2s.]cU<2?k0Y1I]1V[eA<2?k0s1M]2T[fI<2?k0c1Q]2e2w}o1>101s0E74}4[101>101w0S7o}8[1U1>101s0M74}U[2I1>101s?78}M[3E1>101s.78}M[4w1>101s0w78}E[5s1>101s0M78}E[6o1>101s?7c}U[7o1>101s.7c}U[8g1>101s0w7c]1{981>101s0M7c}M[a01>101s?7g]1o[aE1>40f7_&bg1>101?15w^40f7_&c81>2?o0u2I)cw1>101c0I6Q)dk1>101g0K6Q)dU1:Y0Q5k)f41>101s0Q7o)fQ1>101o0W6Y)1c2>2?c?1(1A2>i%2M2>i%4w2>h01s087o}M[5A2>i%7o2>w%982>g%a02>i%bQ2>i%cU2>i%eA2>i%fI2>i$E3>i%1Y3>h01s0U7k}M[303>i%4c3>h01s087k}M[5k3>i%6w3>i%7M3>i%8Y3>i%2Y4>i%a03>g%ao3>i%bI3>h01s0E7o}M[cw3>h01s0E7k}M[dI3>g%eg3>i$04>i%1g4>i%2o4>g%5o3>i%2U4>i%484>i%5c4>i%6w4>i%7A4>i%8I4>i%9U4>h01s0E7g}M[b04>i%cg4>g%dg4>w%ec4>i%co4>g%fk4>h01s0U7g}M{o5>i%245>h01s0o7g}M[345>i%4k5>h01s0o7o}M[5o5>h01s0o7k}M[6w5>i%7Q5>i?k0M2E]2R[9Q5>i%aU5>g%c05>i%d85>i%ew5>i%fI5>i$Y6>i%246>w%3I6>i%506>i%646>y%7M6>g%8w6>i$1zsDhypmtFrBcKrM1Apn9BpSBPt6lOnThJnSdIrSVBsM1vnShLnStIrS9xr5ZAt6ZOsRZxtnw0oSZJs6NBt6lAbz?nRZArRZDr6ZyomNvp7hLsDdvonlUnSpFrCBvon9OonBvpmVQsDA0pD9xrmlvp7lJrnA0nRZCsC5JplZAtmRJulZFrCBQnS5OsC5VnSlKt79V06lSpChvoSZMulZJomBK06lSpChvp65Qog1zq6BIp7lPomtBnSRxqmU0sClxp5ZMsCZznTdQong0sClxp5ZCqmVFsSxBp5ZQqmRBnSpLsBZMqmg0sClxp5Zxr6NvoT1RnThFrmk0pD9voDlFr7hFrw1BtCpAnThBsCQ0rT9Apn9voSZRrDhBsw1zs7lRsS5DplZArSc0oSxFr6hRsS5DplZArSc0rT9Apn9vpSlQnShLoM1LsChBsBZFrCBQnShLoM1BtCpAnSdIrTdBnShLoM1BtCpAnTdFpSVxr5ZArSc0pnpCp5ZzrT1VnShLoM1BtCpAnTtxqnhvp6Zz06lSpChvqmVFt5ZArSc0r7dBpmJvp6Zz06dOt6lKp5cKrM1vnQpigkR5nQleh5Zv05ZCqmVF05Zvp7dLnSxxrChIpg1vh5BegkR9gM1vnQtellZ5i5Z6kA5dhlZ8h580nRZkjkdvhkV4nRY0nQtcjQ91j5ZfhApjhlhvl452j4lv05ZFrCBQ06tBt6lKtA17j4B2gRYObz8Kdg1vnSBPrScOcRZPt79QrTlIg4tcik93nP8KcPw0pnpCp5ZTomBQnTdQsDlzt01vnSlOsCVLnSNLoS5QqmZKg4tcik93nP8KcyUR05Z9l4Rvp6lOpmtFsThBsBhdgSNLrClkom9Ipg1ytmBIt6BKnSlOsCZO05ZvqndLoP8PnTdQsDhLtmNIg4tcik93nP8KcPw0sT1IqmdBg4tcik93nP8Kdg1vnSBPrScOcRZCsSdxrCp0hQN9gAdvcyUPe01JqShFsA17j4B2gRYObz8Kdg1CoSVQr417j4B2gRYObz8Kdg1TsCBQpk17j4B2gRYObz8Kdg1BtCpAnSdLs7BvsThOtmdQ06tBt71Fp417j4B2gRYObz8Kdg1LsChBsBZFrCBQnTdQsDlzt01CoSNLsSl-0rT1BrChFsA17j4B2gRYObz8Kdg1Pt79IpmV-0rmRxs417j4B2gRYObz8Kdg1UpD9Bpg1PrD1OqmVQpA17j4B2gRYObz8Kdg1IsSlBqRZPt79RoTg0pnpCp5ZPqmtKomNvsThOtmdQ07xOpm5Ir6Zz05ZvqndLoP8PnTdQsDhLr6N0hQN9gAdvcyUPe01Pt79OoSxOg4tcik93nP8KcyUR06NPpmlHg4tcik93nP8KcyUR07xJomNIrSc0p71OqmVQpA17j4B2gRYObz8Kdg1Mqn1Bg4tcik93nP8KcyUR06dIrTdBp6BOg4tcik93nP8KcyUR079Bomh-0pCtBt7d-0sThOoSRMg4tcik93nP8KcyUR06dEqmNAtndxpSlvsThOtmdQ06pMsCBKt6p-0tmVyqmVAnTpxsCBxoCNB05ZvpSRLrBZPt65Ot5Zv06RBrmdMuk17j4B2gRYObz4Q06ZOp6lOnStBt5ZPt79RoTg0nRZFsSZzczdvsThOt6ZIg4tcik93nP8KcPw0oT1RtndxpSlvsThOtmdQ079BomhAqn9-0pnpCp5ZFrCBQnTdQsDlzt01BtCpAnSdIrTdBnTdQsDlzt01PpmVApCBIpk17j4B2gRYObz8Kdg1PpnhRs5ZytmBIt6BKnSpLsCJOtmVvr6Zxp65yr6lP071Lr6N-0rm5HplZytmBIt6BKnS5OpTo0pCZMpmV-0pSlQsDlPomtBg4tcik93nP8KcyUR07dQsDhLqQ17j4B2gRYObz8Kdg1PundzrSVCg4tcik93nP8KcyUR06lSpmVQpCh0hQN9gAdvcyUT05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0sThOpn9OrT9-0pDdQonh0hQN9gAdvcyUPcM1vnSdUolZCqmVxr6BWpk17j4B2gRYObz8Kdg1xp6hvoDlFr7hFrw1vnSdQun1BnS9vr6Zzg4tcik93nP8KcM?bDdVrnhxow0KsThOt65y02VPq7dQsDhxow0KrCZQpiVDrDkKs79Ls6lOt7A0bCVLt6kKpSVRbC9RqmNAbmBA02VFrCBQ02VQpnxQ02VCqmVF02VDrDkKq65Pq?Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bD9Lp65Qog0KpmxvpD9xrmlvq6hO02VBq5ZCsC5Jpg0KqmVFt5ZxsD9xug0KpCBKqlZxsD9xug0Kp65QoiVOpmMKsCY0bChVrC5Jqmc0bCtLt?KpSZQbD1It?Kp65Qog0KoDdP02VzrSRJpmVQ02VDrDkKoDlFr6gKonhQsCBytnhBsM~`>r<1M<8[G08]2E0w]3&8*bw<s<2[dw2}S08}A*1*44<1<1w{4{g}6M*g(2o;g<o[81[w4}203(g[1{hM<4<6[40j}g1c}R6(8*4Q<1<1w}1UaM]7wH}2w*g(1j<ZL/rM8{3{c}5{2{8*ng<I<2[50M}k3{1w}A<1<2{o[6k<3;w}1gdw]50S}5wc(4(1J<//rM8[pzA]1Ceg]8{2{2{8[uw>fX/SY2[ewV}W3A]2{0A<1<2*8A<4;w}1Eew]6wW}O0E}8{w[6[2j<1<48[c4k}Mhg]9w4}2<1o<8[1w[Dg<4<O[cx9}O4A}63(2{1[ak<1;w}3glg]d1l}j&g(2P;g<8[85o}wlw]ew1(8*Lg<U<3[a1J}E5Q}8*2{8[cA<f;M}2Erg]axt}2&w[2[3l;g<c[I6Q]2Mng}w*8*Uw<o<3[bxJ}K5Q]30.}A[2{g[eI<1;M}1UrM]7xv}s&w[2[3M;g<c[W6Y]3EnM]a01(8{w[@g<4<3[a1N}E64}M1g)8*fY<8;M}3gtw]d1C}4&w*4.>g>3*3gpw]2U*1{4[2w4>s=e2m[6s}w.)1&4<2%21E}A0A}s<9M<w[6{9;M^2Msg]a06(1*4g<c%k7w}z.(g)'
            ;;
            aarch64)

b64=
            ;;
            riscv64)
b64=            
            ;;
            *)  supportedArchFlag=false  ;;
        esac

        ${supportedArchFlag} && [[ ${b64} ]] && _forkrun_base64_to_file "${outDir}/forkrun_loadables.so" <<<"${b64}" && chmod +x "${outDir}/forkrun_loadables.so" && enable -f "${outDir}/forkrun_loadables.so" evfd_init evfd_wait evfd_signal evfd_close evfd_copy order_init order_get lseek cpuusage childusage
    fi

     shopt ${extglobState} extglob
}

export -f _forkrun_SETUP

_forkrun_SETUP --force

_forkrun_file_to_base64() {

    local nn kk kk0 k1 k2 out out0 outF outN v1 v2 nnSum hexProg quoteFlag noCompressFlag doneFlag IFS IFS0

    local -a charmap compressI compressV outA nnSumA
    local -x LC_ALL=C

    # parse inputs

    quoteFlag=false
    noCompressFlag=false

    while true; do
        case "${1}" in
            -q|--quote)
                quoteFlag=true
                shift 1
            ;;
            -n|-nc|--no-compress|--no-compression)
                noCompressFlag=true
                shift 1
            ;;
            *) break ;;
        esac
    done

    [[ -f "${1}" ]] || {

        printf '\nERROR: "%s" not found. ABORTING.\n' "${1}" >&2
        return 1
    }

    # define char mapping array that convero 0-63 --> [0-9][a-z][A-Z]@_ (bash 64# chars)
    charmap=($(printf '%s ' {0..9} {a..z} {A..Z} '@' '_'))
    doneFlag=false
    outN=0
    outA=()

    # to dump the binary as ascii hexidecimals , we need od or hexdump
    if type -p od &>/dev/null; then
        hexProg='od -x'

    elif type -p hexdump &>/dev/null; then
        hexProg='hexdump'
    else
        return 1
    fi

    # map each 12-bit segment (3x ascii hex chars, each representing 4 bits of data) into 2 base64 ascii chars (each representing 6 bits of data)
    while read -r -N 3 nn; do
        nn="${nn%$'\n'}"
        (( outN = outN + ${#nn} ))
        until (( ${#nn} == 3 )); do
            nn="${nn}"'0'
        done
        (( k1 = ( 16#${nn} >> 6 ) ));
        (( k2 = ( 16#${nn} % 64 ) ));
        outA+=("${charmap[$k1]}" "${charmap[$k2]}")
  done < <(${hexProg} -v <"${1}" | head -n -1 | sed -E 's/^[0-9a-f]+[[:space:]]+//; s/([0-9a-f]{2})([0-9a-f]{2})/\2\1/g; s/[[:space:]]//g' | sed -zE 's/\n//g');

    IFS=
    out="${outA[*]}"
    unset IFS

    (( outN = ( outN >> 1 ) << 1 ))

    # get orig file size
    if type -p stat &>/dev/null; then
        outB="$(stat -c %s "$1")"
    elif type -p wc &>/dev/null; then
        outB="$(wc -c <"$1")"
    else
        outB=0
    fi

    # embed checksums
    if type -p md5sum &>/dev/null; then
        nnSum="$(md5sum "$1")"
        nnSumA[0]="${nnSum%%[ \t]*}"
        nnSumA[0]='md5sum:'"${nnSumA[0]}"
    else
        nnSumA[0]=0
    fi
    if type -p sha256sum &>/dev/null; then
        nnSum="$(sha256sum "$1")"
        nnSumA[1]="${nnSum%%[ \t]*}"
        nnSumA[1]='sha256sum:'"${nnSumA[1]}"
    else
        nnSumA[1]=0
    fi

    # compress base64 and assemble the header
    if ${noCompressFlag}; then
        printf -v out0 '%s\n' "${outN} ${outB}" "${nnSumA[@]}"
    else
        # initial compression run
        compressI=('~' '`' '!' '#' '$' '%' '^' '&' '*' '(' ')' '-' '+' '=' '{' '[' '}' ']' ':' ';' '<' ',' '>' '.' '?' '/' '|')
        mapfile -t compressV < <(sed -E 's/(00+)(([^0]+0?[^0]+)*)/\1\n\2/g; s/([^0]+)/\1\n/g' <<<"${out}" | grep -E '..' | sort | uniq -c | sed -E 's/^[ \t]+//' | grep -vE '^1 ' | sort -nr -k1,1 | while read -r v1 v2; do (( v0 = v1 * ${#v2} - v1 - ${#v2} )); printf '%s %s %s %s\n' "$v0" "${#v2}" "$v1" "$v2"; done | grep -vE '^-' | sort -nr -k 1,1 | head -n 25 | sort -nr -k2,2 | sed -E 's/^([0-9]+ ){3}//')
        for kk in "${!compressV[@]}"; do
            out="${out//"${compressV[$kk]}"/"${compressI[$kk]}"}"
        done
        # 2 final compression runs where we re-generate the list of possible replacements and expand it to also look for simple repeated chars (with a limit of a maximum of 32 chars)
        for kk0 in 1 2; do
            ((kk++))
            compressV[$kk]="$({ sed -E 's/(00+)(([^0]+0?[^0]+)*)/\1\n\2/g; s/([^0]+)/\1\n/g' <<<"${out}" | grep -E '..' | sort | uniq -c | sed -E 's/^[ \t]+//'; { read -r -N 1 y; while read -r -N 1 x; do if [[ "$x" == "${y: -1}" ]]; then y+="$x"; else echo "$y"; read -r -N 1 y; fi; done; } <<<"${out}" | grep -E '..' | sort | uniq -c| sed -E 's/^[ \t]+//' | while read -r v1 v2; do if ((${#v2} > 32 )); then (( v1 = v1 * ( ${#v2} / 32 ) )); v2="${v2:0:32}"; fi; printf '%s %s\n' "$v1" "$v2"; done } | grep -vE '^1 '   | sort -nr -k1,1 | while read -r v1 v2; do (( v0 = v1 * ${#v2} - v1 - ${#v2} )); printf '%s %s %s %s\n' "$v0" "${#v2}" "$v1" "$v2"; done | grep -vE '^-' | sort -nr -k 1,1 | head -n 1 | sed -E 's/^([0-9]+ ){3}//')"
            out="${out//"${compressV[$kk]}"/"${compressI[$kk]}"}"
        done

        printf -v out0 '%s\n' "${outN} ${outB}" "${nnSumA[@]}" "${compressV[@]}"
    fi

    # combine header and base64
    printf -v outF '%s'$'\034''%s' "${out0%$'\n'}" "${out}"

    # print output, optionally quoted
    if ${quoteFlag}; then
        printf '%s' "${outF@Q}"
    else
        printf '%s' "${outF}"
    fi
}

# Fallback for head -n N and head -n -N
if ! type -p head >/dev/null; then
head() {
    local -a A A1
    local n kk
    if (( $# == 0 )); then
      mapfile -t -n 20 A
    else
      [[ $1 == -n ]] && shift 1
      case $1 in
         [0-9]*)  n=$1; mapfile -t -n "$n" A ;;
        -[0-9]*)

		    n=${1#-};

			(( kk = n < 20 ? 20 : n ));

			mapfile -t -n $kk A;

			(( ${#A[@]} >= n )) && while true; do
			    mapfile -t -n $kk A1

				if (( ${#A1[@]} < kk )); then
				    A=("${A[@]}" "${A1[@]}")
					break
				else
					printf '%s\n' "${A[@]}"
				fi
			    mapfile -t -n $kk A
				if (( ${#A[@]} < kk )); then
				    A=("${A1[@]}" "${A[@]}")
					break
				else
					printf '%s\n' "${A1[@]}"
				fi

			done
			if (( ( ${#A[@]} - n ) >= 0 )); then
			    A=("${A[@]:0:${#A[@]}-n}")
			else
			    return 0
			fi

		;;
		*) return 1 ;;
      esac
    fi
    printf '%s\n' "${A[@]}"
}
fi

# Fallback for tail -n N and tail -n +N
if ! type -p tail >/dev/null; then
tail() {
    local -a A A1
    local n kk
    if (( $# == 0 )); then
        n=20
	else
      [[ $1 == -n ]] && shift 1
      case $1 in
        +[0-9]*)  (( n = ${1#+} - 1 ));  mapfile -t -n $n _; mapfile -t A; printf '%s\n' "${A[@]}"; return 0  ;;
         [0-9]*)  n=$1 ;;
         *) return 1  ;;
      esac

    fi
	(( kk = n < 20 ? 20 : n ));

    mapfile -t -n $kk A;

    (( ${#A[@]} >= n )) && while true; do
        mapfile -t -n $kk A1

        if (( ${#A1[@]} < kk )); then
            A=("${A[@]}" "${A1[@]}")
            break
        else
            printf '%s\n' "${A[@]}"
        fi
        mapfile -t -n $kk A
        if (( ${#A[@]} < kk )); then
            A=("${A1[@]}" "${A[@]}")
            break
        else
            printf '%s\n' "${A1[@]}"
        fi

    done
    (( ( ${#A[@]} - n ) >= 0 )) && A=("${A[@]:${#A[@]}-n}") ;
    printf '%s\n' "${A[@]}"
}
fi

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


shopt ${forkrun_extglobState} extglob
unset forkrun_extglobState


#
#
#_forkrun_loadable_setup() {
#    ## sets up a "loadable" bash builtin for x86_64 machines
#    local loadableArch cksumAlg cksumVal cksumAll loadablePre loadableDir loadableGetFlag loadableCurlFailedFlag forkrunRepo
#    
#    loadableGetFlag=false 
#    loadableCurlFailedFlag=false
#    #forkrunRepo='main'
#    forkrunRepo='forkrun_testing_nSpawn_5'
#
#    type curl &>/dev/null || {
#        if [[ -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so ]]; then
#            enable -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so lseek 2>/dev/null
#            enable -f "${BASH_LOADABLES_PATH%%:*}"/forkrun.so childusage 2>/dev/null
#        else
#            enable lseek 2>/dev/null
#            enable childusage 2>/dev/null
#        fi
#        return
#    }
#
#    if type uname &>/dev/null; then
#        loadableArch="$(uname -m)"
#    elif [[ -f /proc/sys/kernel/arch ]] ; then
#        loadableArch="$(</proc/sys/kernel/arch)"
#    else
#        return 1
#    fi
#
#    { [[ "${loadableArch}" == 'x86_64' ]] || [[  "${loadableArch}" == 'aarch64' ]] || [[  "${loadableArch}" == 'riscv64' ]] || return 1; }
#
#    if  ! [[ $USER == 'root' ]] && [[ -f /dev/shm/.forkrun.loadable/forkrun.so ]]; then 
#        loadablePre='/dev/shm/.forkrun.loadable/forkrun.so'
#    elif [[ -f /usr/local/lib/bash/forkrun.so ]]; then
#        loadablePre='/usr/local/lib/bash/forkrun.so'
#    fi
#
#    [[ ${loadablePre} ]] && {
#        for cksumAlg in sha256sum sha512sum b2sum sha1sum md5sum cksum sum; do
#            type $cksumAlg &>/dev/null && break || cksumAlg=''
#        done
#        [[ ${cksumAlg} ]] && {
#            cksumVal="$($cksumAlg "$loadablePre")"
#            cksumVal="${cksumVal%% *}"
#            cksumAll="$(curl 'https://raw.githubusercontent.com/jkool702/forkrun/refs/heads/'"${forkrunRepo}"'/loadables/CHECKSUMS' 2>/dev/null)"
#            [[ "${cksumAll}" == *"${cksumVal}"* ]] || loadableGetFlag=true
#        }
#    }
#
#    if [[ ${loadablePre} ]] && ! ${loadableGetFlag}; then
#        enable -f "${loadablePre}" lseek 2>/dev/null || loadableGetFlag=true
#        enable -f "${loadablePre}" childusage 2>/dev/null || loadableGetFlag=true
#    else
#        loadableGetFlag=true
#    fi
#    
#    if ${loadableGetFlag}; then
#        ${loadablePre} && \mv -f "${loadablePre}" "${loadablePre}".old 
#        case "${USER}" in
#            root)  loadableDir='/usr/local/lib/bash'  ;;
#            *)  loadableDir='/dev/shm/.forkrun.loadable'  ;;
#        esac
#        
#        mkdir -p "${loadableDir}"
#        [[ "${BASH_LOADABLES_PATH}" == *"${loadableDir}"* ]] || export BASH_LOADABLES_PATH="${loadableDir}:${BASH_LOADABLES_PATH}"
#        curl -o "${loadableDir}"/forkrun.so 'https://raw.githubusercontent.com/jkool702/forkrun/'"${forkrunRepo}"'/loadables/bin/'"${loadableArch}"'/forkrun.so' || loadableCurlFailedFlag=true
#
#        [[ ${loadablePre} ]] && {
#            if ${loadableCurlFailedFlag}; then
#                \mv "${loadablePre}".old "${loadablePre}"
#            else
#                enable -d lseek 2>/dev/null
#                enable -d childusage 2>/dev/null
#            fi
#        }
#        
#        enable -f "${loadableDir}"/forkrun.so lseek 2>/dev/null || return 1
#        enable -f "${loadableDir}"/forkrun.so childusage 2>/dev/null || return 1
#    else
#        enable -f "${loadableDir}"/forkrun.so lseek 2>/dev/null || return 1
#        enable -f "${loadableDir}"/forkrun.so childusage 2>/dev/null || return 1
#    fi
#    
#    echo 'abc' >/dev/shm/.forkrun.lseek.test
#    {
#        read -r -u $fd -N 1
#        lseek $fd -1 >/dev/null
#        read -r -u $fd -N 1
#        exec {fd}>&-
#    } {fd}</dev/shm/.forkrun.lseek.test
#    \rm -f /dev/shm/.forkrun.lseek.test
#
#    case "$REPLY" in
#        a)
#            return 0
#        ;;
#        *)
#            enable -d lseek
#            printf '\nWARNING: lseek functionality has not been enabled due to an unknown runtime error.\nIf you are on x86_64 or aarch64 and are using bash 4.0 or later, please file a github issue in the forkrun repo describing this error.\n' >&2
#            [[ ${loadablePre} ]] && ! ${loadableCurlFailedFlag} && {
#                \rm -f "${loadablePre}"
#                \mv "${loadablePre}".old "${loadablePre}"
#            }
#            return 1
#        ;;
#    esac
#}
#
#
#_forkrun_loadable_setup
##enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_copy lseek cpuusage childusage
#
#enable -f forkrun_loadables.so evfd_init evfd_wait evfd_signal evfd_close evfd_copy order_init order_get lseek cpuusage childusage
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
