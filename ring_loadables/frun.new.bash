#!/usr/bin/bash

frun() (

    # # # # # SETUP # # # # #

    local test_type worker_func_src nn N nWorkers0 cmdline_str ring_ack_str delimiter_str delimiter_val
    local -g pCode fd_order fd_spawn ingress_memfd nWorkers nWorkersMax tStart
    local -gx order_flag unsafe_flag
    local -ga fd_out args P

    : "${nWorkers:=1}" "${nWorkersMax:=$(nproc)}"

    # export vars to tune workers
    export nWorkers="${nWorkers}"
    export nWorkersMax="${nWorkersMax}"

    order_flag=false
    unsafe_flag=false
    verbose_flag=false
    delimiter_val=$'\n'

    while true; do
        case "$1" in
            -o|--order)
                order_flag=true
                ;;
            -u|--unsafe)
                unsafe_flag=true
                ;;
            -z|--null)
                delimiter_val=''
                ;;
            -d|--delim|--delimiter)
                shift 1
                delimiter_val="${1}"
                (( ${#delimiter_val} > 1 )) && {
                    printf '\nWARNING: multi-byte delimiters are not supported...only the first byte will be used.\n' >&2
                    delimiter_val="${delimiter_val[0]}"
                }
                ;;
            -v|--verbose)
                verbose_flag=true
                ;;
            --)
                shift 1
                break
                ;;
            *)
                break
                ;;
        esac
        shift 1
    done

    if ${verbose_flag}; then
        tStart="${EPOCHREALTIME//./}"
toc() {
    printf '\n%s finished at +%s us\n' "$*" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
}
    else
toc() { :; }
    fi

    # setup loadables if needed
    _forkrun_bootstrap_setup --fast

    # initialize rings with ring_init and create data memfd with ring_memfd_create
    if ${order_flag}; then
        ring_init 'fd_out'
    else
        ring_init
    fi
    toc ring_init

    ring_memfd_create ingress_memfd


    # # # # # MAIN # # # # #
    {
        # # SPAWN "HELPER PROCESSES" # #
        # these keep the worker pool fed

        # start ring_copy to populate memfd with data from stdin
        (
            ring_copy ${fd_write} ${fd0}
            ring_signal
        toc ring_copy
        ) &
        COPY_PID=$!

        # start ring_scanner to scan memfd for line breaks
        ring_pipe 'fd_spawn_r' 'fd_spawn_w'
        (
            exec {fd_spawn_r}<&-
            ring_scanner ${fd_scan} ${fd_spawn_w} "${delimiter_val}"
        toc ring_scanner
        ) &
        SCANNER_PID=$!
        exec {fd_spawn_w}>&-

        # start ring_fallow to remove already-consumed data from memfd and free memory
        ring_pipe 'fd_fallow_r' 'fd_fallow_w'
        (
            exec {fd_fallow_w}>&-
            ring_fallow ${fd_fallow_r} ${fd_write}
            toc ring_fallow
        ) &
        FALLOW_PID=$!
        exec {fd_fallow_r}<&-

        # (if enabled) start ring_order to reorder output to the order that running inputs sequentially would have produced
        ${order_flag} && {
            ring_pipe 'fd_order_r' 'fd_order_w'
            (
                exec {fd_order_w}>&-
                ring_order ${fd_order_r} 'memfd' >&${fd1}
                toc ring_order
            ) &
            ORDER_PID=$!
            exec {fd_order_r}<&-
            export FD_ORDER_PIPE="$fd_order_w"
        }

        # # SPAWN WORKER POOL # #

        # determine cmdline string
        printf -v cmdline_str '%q ' "$@"
        if ${unsafe_flag}; then
            cmdline_str='IFS='"${delimiter_val@Q}"' '"$cmdline_str"' ${A[*]}'
        else
            cmdline_str+=' "${A[@]}"'
        fi
        ring_ack_str='ring_ack $fd_fallow_w'
        ${order_flag} && { 
            cmdline_str+=' >&${fd_out[$ID]}'
            ring_ack_str+=' ${fd_out[$ID]}'
        }
        if [[ ${delimiter_val} ]]; then
            printf -v delimiter_str '%q' "${delimiter_val}"
        else
            delimiter_str="''"
        fi
        
        # define spawning function (use JIT-like optimization)
        worker_func_src='spawn_worker() {
(
  {
    ID="$1"
    shift 1
    ring_worker inc
    while ring_claim CNT $fd_read; do
        [[ "$CNT" == "0" ]] && break
        mapfile -t -u ${fd_read} -n ${CNT} -d '"${delimiter_str}"' A
        '"${cmdline_str}"'
        '"${ring_ack_str}"'
    done
    ring_worker dec
  } {fd_read}<"/proc/'"${BASHPID}"'/fd/'"${ingress_memfd}"'" 1>&${fd1} 2>&${fd2}
toc '"'"'worker '"'"'"$ID"
) &
P+=($!)
}'
        eval "${worker_func_src}"

        toc 'initial setup'

        # spawn workers dynamically
        nWorkers=0
        while true; do
            read -r -u $fd_spawn_r N
            [[ "$N" == 'x' ]] && break
            ${verbose_flag} && printf '\npreparing to spawn %s workers at +%s us...' "$N" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
            nWorkers0="$nWorkers"
            (( ( nWorkers0 + N ) > nWorkersMax )) && (( N = nWorkersMax - nWorkers0 ))
            (( N > 0 )) && for (( nWorkers=nWorkers0; nWorkers<nWorkers0+N; nWorkers++ )); do
                spawn_worker "$nWorkers"
            done
            ${verbose_flag} && printf '\nspawned %s workers at +%s us\n' "$N" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
            nWorkersA+=("$N")
        done

        toc 'spawning workers'


        exec {fd_spawn_r}<&- {fd_fallow_w}>&-
        ${order_flag} && exec {fd_order_w}>&-

        # wait for everything to finish
        wait

        # # CLEANUP # #

        # destroy the rings
        ring_destroy

        # close the fd's
        exec {fd_write}>&- {fd_scan}<&- {ingress_memfd}>&-

        toc 'MAIN FUNCTION'

        # ensure helper processes are dead
        #kill $COPY_PID $SCANNER_PID $FALLOW_PID $ORDER_PID $(jobs -p) 2>/dev/null
        #kill -9 $COPY_PID $SCANNER_PID $FALLOW_PID $ORDER_PID $(jobs -p) 2>/dev/null
        #wait $COPY_PID $SCANNER_PID $FALLOW_PID $ORDER_PID $(jobs -p) 2>/dev/null


    } {fd_write}>"/proc/${BASHPID}/fd/${ingress_memfd}" {fd_scan}<"/proc/${BASHPID}/fd/${ingress_memfd}" {fd0}<&0 {fd1}>&1 {fd2}>&2
)

_forkrun_bootstrap_setup() {
## HELPER FUNCTION TO LOAD THE RING LOADABLES USED BY FORKRUN
    #local LC_ALL=C


# Define helper functions used by _forkrun_bootstrap_setup
_forkrun_get_arch() {

    local ARCH0="$1"

    : "${ARCH0:=$(uname -m)}"

    case "$ARCH0" in
    x86_64[-_]v[2-4])
        ARCH="${ARCH0//_v/-v}"
        ;;
    x86_64)
        if grep -qE '( avx512[((cd)|(bw)|dq)|(vl)|(f))].*){5}' </proc/cpuinfo; then
            ARCH='x86_64-v4'
        elif grep -qF 'avx2' </proc/cpuinfo; then
            ARCH='x86_64-v3'
        else
            ARCH='x86_64-v2'
        fi
        ;;
    aarch64|armv7|riscv64|s390x|ppcle64)
        ARCH="$ARCH0"
        ;;
    *)
        printf '\nINVALID / UNSUPPORTED ARCH!\nSUPPORTED ARCH: x86_64 aarch64 armv7 riscv64 s390x ppcle64\n\n' >&2
        return 1
        ;;
    esac
    return 0
}



_forkrun_base64_to_file() {
    local b b0 b1 k kk fd0 fd1 out0 out outC outN outF outB outFile nnSum nnSum_md5 nnSum_sha256 noVerifyFlag doneFlag IFS extglobState
    local -a compressV compressI outA
    #local LC_ALL=C
    local -I extglobState

    {

    # parse options
    [[ "${extglobState}" == '-'[su] ]] || {
        if shopt extglob &>/dev/null; then
            extglobState='-s'
        else
            extglobState='-u'
        fi
    }
    shopt -s extglob

    [[ -t 0 ]] && {
        printf '\nERROR: pass the base64-encoded sequence on stdin. ABORTING.\n'  >&2
        return 1
    }

    # determine if we are outputting to stout or to a file
    exec {fd0}<&0
    if (( $# > 0 )); then
        [[ -f "$1" ]] && \rm -f "$1"
        outFile="$1"
        : >"${outFile}"
    else
        outFile=/proc/${BASHPID}/fd/1
    fi
    exec {fd1}>"${outFile}"

    # read dataheader and data
    read -r -d $'\034' -u "${fd0}" out0
    read -r -d '' -u "${fd0}" out
    exec {fd0}>&-

    if [[ -z ${out} ]]; then
        # if data header is missing then the base64 may have been made with standard base64 decoding. attempt to work with this.
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
    if [[ ${outFile} ]] && [[ -f "${outFile}" ]]; then
        chmod +x "${outFile}"
        (( outB > 0 )) && type -p truncate &>/dev/null && truncate --size="${outB}" "${outFile}"
        ${noVerifyFlag} || [[ "${nnSum}" == '0' ]] || { nnSumF="$("${nnSum%%\:*}" "${outFile}")"; nnSumF="${nnSumF%% *}"; grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; read -r -u ${fd_sleep} -t 2; \rm -f "${outFile}"; return 1; }; };
    elif ! { ${noVerifyFlag} || [[ "${nnSum}" == '0' ]]; }; then
        nnSumF="$("${nnSum%%\:*}" <(printf '%b' "${outF}"))"; nnSumF="${nnSumF%% *}"; grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; read -r -u ${fd_sleep} -t 2; \rm -f "${outFile}"; return 1; };
    fi

    } {fd1}>&1

    { (( ${#FUNCNAME[@]} > 1 )) && [[ "${FUNCNAME[1]}" == 'frun' ]]; } || shopt ${extglobState} extglob
}


    local tmp_so dir rf bootstrap_flag need_memfd_create_flag need_memfd_b64_flag need_b64_flag have_memfd_loadables_flag force_flag fast_flag
    local -a candidates ring_funcs

    need_memfd_create_flag=false
    need_memfd_b64_flag=false
    need_b64_flag=false
    have_memfd_loadables_flag=false
    force_flag=false
    fast_flag=false
    bootstrap_flag=false

    # check for -f|--force as input arg
    while true; do
        case "$1" in
            --fast)      fast_flag=true;  shift 1  ;;
            -f|--force)  force_flag=true; shift 1  ;;
            *)           break                     ;;
        esac
    done

    [[ $FORKRUN_MEMFD_LOADABLES ]] && (( FORKRUN_MEMFD_LOADABLES > 2 )) && [[ -f /proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES} ]] && have_memfd_loadables_flag=true

    # fast "is everything already set up" check for runtime checks
    ${fast_flag} && {
        enable ring_list || { 
            ${have_memfd_loadables_flag} && enable -f /proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES} ring_list
        }
        if ring_list 'ring_funcs' 2>/dev/null && (( ${#ring_funcs[@]} > 0 )); then
            for rf in "${ring_funcs[@]}"; do
                enable "$rf" 2>/dev/null || {
                    fast_flag=false
                    break
                }
            done
        else
            fast_flag=false
        fi
    }
    ${fast_flag} && return 0

    # check for existing b64 array
    (( ${#b64[@]} > 0 )) || need_b64_flag=true

    # check for existing memfd holding b64
    { [[ $FORKRUN_MEMFD_LOADABLES_BASE64 ]] && (( FORKRUN_MEMFD_LOADABLES_BASE64 > 2 )) && [[ -f "/proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES_BASE64}" ]]; } || need_memfd_b64_flag=true

    # if we dont have the b64 array and there isnt already a memfd holding it (to recover it from) abort
    ${need_b64_flag} && ${need_memfd_b64_flag} && {
        printf '\n\nERROR: There is no b64 array variable to generate the .so from and no memfd to recover the b64 array from. ABORTING!\nNOTE: to re-load the b64 array and setup the loadables again, run  ". %s" again.\n\n' "${BASH_SOURCE[0]}" >&2
        return 1
    }

    # check for the memfd_create loadable
    enable | sed -zE 's/\n/ /g' | grep -qE '(ring_((memfd_create)|(seal)|(list)) .*){3}' || need_memfd_create_flag=true


    # set ARCH
    _forkrun_get_arch "$1"

    # if we need the b64 get it from the memfd
    ${need_b64_flag} && {
        . "/proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES_BASE64}"
        (( ${#b64[@]} == 0 )) && {
            printf '\n\nERROR: ring_memfd_create is not loaded and there is no b64 array variable to generate the .so from. ABORTING!\nNOTE: to re-load the b64 array and setup the loadables again, run ". %s" again.\n\n' "${BASH_SOURCE[0]}" >&2
            return 1
        }
        need_b64_flag=false
    }

    # if ring_memfd_create isnt loaded then bootstrap it by briefly creating the .so in in a tmpfile and loading it
    ${need_memfd_create_flag} && {
        bootstrap_flag=true

        # Define candidates in order of preference
        candidates=(
            "${FORKRUN_TMPDIR:-}"        # user override via env var
            "${XDG_RUNTIME_DIR:-}"       # Best: Standard, private tmpfs
            "/run/user/${EUID}"          # Fallback XDG
            "/dev/shm"                   # Standard shared memory
            "/run/shm"                   # Legacy shared memory
            "${TMPDIR:-}"                # Standard env var
            "/tmp"                       # Universal fallback
            "${HOME}/.cache"             # User disk fallback
            "$PWD"                       # Last resort
        )

        # try various places to make the tmp .so file to bootstrap
        for dir in "${candidates[@]}"; do
            # Skip empty, non-existent, or non-writable directories
            { [[ $dir ]] && [[ -d "$dir" ]] && [[ -w "$dir" ]]; } || continue

            # Generate path with high entropy (30-bit random hex)
            printf -v tmp_so '%s/forkrun_boot_%s_%X%X.so' "$dir" "$BASHPID" "$RANDOM" "$RANDOM"

            # Try to extract loadable
            if _forkrun_base64_to_file "$tmp_so" <<<"${b64[$ARCH]}"; then
                chmod +x "$tmp_so"

                # CRITICAL TEST: Try to Enable loadable
                # This verifies the filesystem allows execution (noexec check)
                if enable -f "$tmp_so" ring_memfd_create ring_seal ring_list ring_pipe >/dev/null; then
                    # SUCCESS! The builtin is loaded. Delete disk artifact immediately.
                    need_memfd_create_flag=false
  else
                # If enable failed, clean up and try next candidate
                    \rm -f "$tmp_so"
fi

                # break outof loop if we found someplace that works
                ${need_memfd_create_flag} || break
            fi
        done

        # If we get here and stil dont have memfd_create we failed --> couldnt find a writable location
        ${need_memfd_create_flag} && {
            printf '\nERROR: could not write and load bootloader for loadable in any temp directory. ABORTING!\n directories checked: %s\nPlease specify a writable directory by calling "FORKRUN_TMPDIR=/path/to/writable/dir _forkrun_bootstrap_setup"\n\n' "${candidates[*]}" >&2
            return 1
        }
    }

    # if we bootstrapped or if force_flag is set, forcible re-create + seal the base64 memfd backup. if force_flag is set close the previous one
    if { ${bootstrap_flag} || ${force_flag}; } && (( ${#b64[@]} > 0 )); then

        # if force_flag is set then close the old base64 memfd
        ${force_flag} && ! ${need_memfd_b64_flag} && exec {FORKRUN_MEMFD_LOADABLES_BASE64}>&-

        # open a memfd, write b64 to it, and seal it
        ring_memfd_create 'FORKRUN_MEMFD_LOADABLES_BASE64'
        declare -p b64 >&${FORKRUN_MEMFD_LOADABLES_BASE64}
        ring_seal "${FORKRUN_MEMFD_LOADABLES_BASE64}"
        need_memfd_b64_flag=false
    fi

    # open a memfd, extract loadable .so to it, and seal it
    ${force_flag} && ${have_memfd_loadables_flag} && exec {FORKRUN_MEMFD_LOADABLES}>&-
    unset "FORKRUN_MEMFD_LOADABLES"
    ring_memfd_create 'FORKRUN_MEMFD_LOADABLES'
    _forkrun_base64_to_file <<<"${b64[$ARCH]}" "/proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES}"
    ring_seal "${FORKRUN_MEMFD_LOADABLES}"

    # get list of loadables
    ring_list 'ring_funcs'

    # unload existing ring loadables
    if ${bootstrap_flag}; then
        enable -d ring_memfd_create ring_seal ring_list
    else
        enable -d "${ring_funcs[@]}" 2>/dev/null || true
    fi

    # load ring loadables exclusively from memfd
    enable -f "/proc/${BASHPID}/fd/${FORKRUN_MEMFD_LOADABLES}" "${ring_funcs[@]}" ring_list

    # clear massive b64 array
    unset "b64"
}





_forkrun_file_to_base64() {

    local nn kk kk0 k1 k2 out out0 outF outN v1 v2 nnSum hexProg quoteFlag noCompressFlag IFS IFS0
    local -I extglobState

    local -a charmap compressI compressV outA nnSumA
    local LC_ALL=C

    [[ "${extglobState}" == '-'[su] ]] || {
        if shopt extglob &>/dev/null; then
            extglobState='-s'
        else
            extglobState='-u'
        fi
    }
    shopt -s extglob
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

    { (( ${#FUNCNAME[@]} > 1 )) && [[ "${FUNCNAME[1]}" == *'frun'* ]]; } || shopt ${extglobState} extglob
}

unset "b64"

# <@@@@@< _BASE64_START_ >@@@@@> #

declare -a b64=([0]=$'116366 58184\nmd5sum:9ad4236a2f2a64079a5c24a7a1218308\nsha256sum:cb04e5731f7fcd2470e03623e81e7f620f6c2f3e17af54edd8ac41b06e2ea9fb\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n6pCbwYvx\n00000000\n0000000\n4ybe37\n000000\n00000\n0000\n000\n04\n00\n0g\n__\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\034vQlchw81?+.c0fw01-1+czr+,4.e.b>.7w0t0><5![o8[1ww=g=g<g;A=2g=9[2ke[9gU=1=1<1w<zd[2dQ[8Tg}4wd[s0Q=4=8<6<acQ[ETg}2zt[Q>}3g?[w=1;g,2E0w}aw2[G08[A=2g=1+4<1<a2_[EbY}2wLM}3+c+8+s<4<2cQ[8Tg[zt[1+l+w=k@lQp?,2wLM}a2_[EbY[M=3+2=1gVnhA1<d2_[QbY}3gLM}2g1[9>[4=57Bt6g6~).1+kKlQp?<8Pg[zt[2dQ}3U0w}fw2=g=4<5;c,17jBk0h@D6TdMWdvujc4EecKcnRh_tliHP3NXWi8fI24yb1pTs.18xs1Q0L_gi8f42cc+03_dvHs.3_9vPs,f7Q._OnWT,q;3FUf//YBYJM.6w1<Wt3//_9uHs.1E0w,eD0//_OnyT,q0c,3FIf//YBSJM.6w4<Wq3//_9tbs.1E1g,eCg//_OnaT,q0o,3Fwf//YBMJM.6w7<Wn3//_9rHs.1E2<eBw//_OmOT,q0A,3Fkf//YBGJM.6wa<Wk3//_9qbs.1E2M,eAM//_OmqT,q0M,3F8f//YBAJM.6wd<Wh3//_9oHs.1E3w,eA0//_Om2T,q0Y,3FYfX/_YBuJM.6wg<Wu3@//9nbs.1E4g,eDg_L/_OlGT,q18,3FMfX/_YBoJM.6wj<Wr3@//9lHs.1E5<eCw_L/_OliT,q1k,3FAfX/_YBiJM.6wm<Wo3@//9kbs.1E5M,eBM_L/_OkWT,q1w,3FofX/_YBcJM.6wp<Wl3@//9iHs.1E6w,eB0_L/_OkyT,q1I,3FcfX/_YB6JM.6ws<Wi3@//9hbs.1E7g,eAg_L/_OkaT,q1U,3F0fX/_YB0JM.6wv<Wv3Z//9vHr.1E8<eDw_v/_OnOSM.q24,3FQfT/_YBWJI.6wy<Ws3Z//9ubr.1E8M,eCM_v/_OnqSM.q2g,3FEfT/_YBQJI.6wB<Wp3Z//9sHr.1E9w,eC0_v/_On2SM.q2s,3FsfT/_YBKJI.6wE<Wm3Z//9rbr.1Eag,eBg_v/_OmGSM.q2E,3FgfT/_YBEJI.6wH<Wj3Z//9pHr.1Eb<eAw_v/_OmiSM.q2Q,3F4fT/_YByJI.6wK<Wg3Z//9obr.1EbM,eDM_f/_OlWSM.q3<3FUfP/_YBsJI.6wN<Wt3Y//9mHr.1Ecw,eD0_f/_OlySM.q3c,3FIfP/_YBmJI.6wQ<Wq3Y//9lbr.1Edg,eCg_f/_OlaSM.q3o,3FwfP/_YBgJI.6wT<Wn3Y//9jHr.1Ee<eBw_f/_OkOSM.q3A,3FkfP/_YBaJI.6wW<Wk3Y//9ibr.1EeM,eAM_f/_OkqSM.q3M,3F8fP/_YB4JI.6wZ<Wh3Y//9gHr.1Efw,eA0_f/^4ydfkDz.18zgl2UM.i3DUt1l8yMn@RM.i8n0t0D_U0Yvw;333N@:4ydfhDz.18zjkiUM.i2D@i8DMic7KfQz1@0d80sp8QvVQ54yb1mTo.18xs1Q2f_wpwYvh,MMYvw;3P3NXWw3TlUw,7kHlky3flbo<i8DBt0N8zjSeRg.W0D//Epf/_Yo5Hu8,5tMMYv0ccf7U:YMYu@KBT//3N@:4y5_M@41M80>5mgll1l4C9ZbVr<lld8yvJ8w@MwW1LY/Z8ysl8xs1Q3Qy9T@zH@/_w7M3_RRQ74y3N21cyup8ytYNQBJtglN1nk5uWiLZ/Yf7M19yuV8wYk1iiDuioR@0uxl_f/i8Duj8DOioD5i8D7WfjY/Z3NAgR.18yu_EBLL/QydkfZ8yst8yggAi8Bk90zE8vP/Qybl2g8i8DKi8D7i8D3WbXY/Z8yMMAj8DLNAgb_M3EnvL/Qydu07EZfL/QO9XAy9N@zF@L/i8Dvi8D5W3XX/Z8znw1WdnX/Z8ytV8ysvEOLH/QO9VQC9NKwv@/_i8RU0uyS@/_j8DCi8D7WaLW/ZcyuZ9ysjEgfL/Qy9T@wU@/_i8DLW13W/Z8xs0fxdY,2bk2zSMA1RnUfy10@4Hw,4z7h2go;ew8@L/i8RQ91yW2w,4O9ZYs:4y9M@wJ_f/i8D6i8J491x9espQo80U07lrwPIyt5oNOkO9UAy9X@x9_f/WNIf7U:hj70j8Dxj8DOi8DKi8D7W4PZ/Z8yu_EFfH/QO9Z@ys@L/i8f484O9VRJtglN1nk5uWozW/Yf7Ug:4O9ZAydfsWO,NMeyv@v/WY4f7Qg0>y9XAydftCH,NMey7@v/WWAf7Qg.ccf7U:i8DLW73W/Z8yuV8zjSmGM.i8n03Uk6//WYZCpyUf7Ug:5e_Mw,4y3X43E4vP/Qy5M7Uci8f4g5L3pwYvh,i8QZwr8.37Scs3EIfL/UD7xs1UarEv<i8RQ9229h2gcW7vW/@bv2gci8A49ewW@L/i8Ik94y5QDYxLXY,3EJ_L/Qy5M7Vqi8f4g4z1U0drMMYvx}NAgk8018zngA6bEa<i8RY923EN_z/Qybl2go3Xoiw@bvwfFbt3Z8ys58Mu4kwfFdi0Z4Mky5M7izWlf/_Yf7U:LY8,3EjLL/Qy5M7@nK,g03Fc//MYvw;18Mu0aWYBCA5d8yvJ8zjSNGw.i8fIkeyc@L/i8n0t5u0e35RkE1U?1RjbG.g.LE8?g18zjSuGw.cs3EJfH/UD2xs1V7HG.g.LE8?g18zjS9Gw.cs3EBLH/UD2xs1Um4y3N529Q5L33N@4:2W0w,4y9THY_?.cs3EHfD/UD2xs1VRKyxZ/_wPwmtp0NQAy9THY_?.cs3Ey_D/UD2xs0fy7n//HHMYvw;35@mY5Ub80>ydv2ggibwKm5xom5xo>y9v2g8i8B49235@nZ4913E_fz/Qybv2g8xs29MDwpylgA2ex8Z/_yRgA2eBv//3N@:cnVrMmwIw.NQgA85xom035@nZ4913ELvz/Qybv2g8xs29MDD1WiT/_ZCA{}glt1lA5lioDRglhlkQy1X4w4.29f2h8zjS3Gg.W3TV/Z8xs0fx1M1.20e34fxeI1.18zjlPGg.i8D7W7PU/@5M0@5_<4yb1lTj.2W6<bU1<i8QZkaA.cs5QJQ,4,18yMzEGLD/QObfrLt.1dxvYfxtM,15csAN_Q6U//_XAx<Kwc,2@012w0eyr@f/i8fU_M@4CgE.37SKw?E018yst8yglUTg.W6LT/@_l<ewx@v/i8QZ0aA0>y9M@y2@f/i8n0t1CW2w,37Si8D7W3XU/Z8ykgA24y5M7Yii8nrgrM1<j0ZfUQO9p2g8i8QZPqw.ex6@f/i8n03Ugd?.cvqW2w,4y9N@z@Z/_i8n03UXR<i8B4913FZ;Yv>ObfuDs.371uvs[jon_3UgA//iss7;4yb1szs.18NU,g}4yb1rrs.36w1w1<i8I5GdM0>z7g1:i8I5CtM0>z7g2:i8I5yJM.cp0a018yMl_T,ict0c;18yMlMT,NA0F>yb1mns.2bfg_k.18NU0>2}8n_uhUNM4y1N4w4.1rnk5sglR1nA5vMMYvg02bfubj.2W.g0>ydt2h0W7LS/Z8xs1_VKLc3NZ.81U?0fx2b@/_F1LX/V18NQgA4>,18zjSHFM.W1LT/Z8xs1Q7z7SKwE,18ysvER_r/Qy5M7Uai8B491zH30Yv>z7h2go01,b@_<W7nT/Z8xs0fzCM8.1czjh0is7K0z7_W5TT/Z8ysd8xs0fzJ48.18yMmGQ,i8IEi8JZ>y5_M@4Hg80>kNV0Yvw;3EW_j/Qybvgx8wYk8joRA1058xvZRWrQ0o,j3Dz3UZX0w.i8QZ2qs.exLZL/i8D3i8n03Ujz1M.w3xc3Ukq0w.w7w1cw@5408.81U0w0fxgo2.18yNQnSM.i8J490x8yocE?.i8J49118NUcM?,g,4y9wO01.18yQgA64O9IR01.18yocU?.yMgAicu3g>}18NUdo?}cq3o>,36wSc1<w_w13UVp2,ict490z//_joRB28fE0Az712j//_joRINh1cyulC3N@4:18yRQ0KwU,18zjl7Fw.i8DvW4zP/@5M0@4K>.bEb<i8QReGo0>y9T@wIY/_xs0fx6g5.2W2w,4yddiGC.18yt_E4ff/Un03UhU1g.KwM,18zjkpFw.i8DvWfjO/@5M0@4B0k.bE9<i8QR2Go0>y9T@zoYL/xs0fxaw5.2W2<4yddvyB.18yt_ELfb/Un03Uh41w.KwM,18zjnBFg.i8DvWa3O/@5M0@4C0o.bE9<i8QRRGk0>y9T@y4YL/xs0fx5g5.2W2<4yddsiB.18yt_Eqfb/Un03Uh01M.Kww,18zjmNFg.i8DvW4PO/@5M0@4fws.bEa<i8QRDGk0>y9T@wMYL/xs0fxco6.2W2<4yddoSB.18yt_E5fb/Un03UkF1M.i8I5btA0>z7w5w1[Wpk<f7Qg0>yddtyA.18ytZ9yuXEzLf/Un03Ujw_v/KwE<NZAy9T@z7YL/ct98xs183QDgioDmWs3Z/ZC3NZ4.1caud8ytx8Mu>i2Doic7U14yd1418Muw2i8D5WmjZ/Yf7U:cvp8znIeKwE,3ECff/Qy5M7Uji8IlBdw0>y9wyw1,f7Qg0>y3Ngx9euQfxvfZ/Z8yMgAi8Itsdw0>y5M0@4FMg,@9ggg0>y3v2g8.@edgg.cq3o>,76wSc1,1j8JQ90xcyrcM?.cuRcyrcU?.j8CPi>,Yv>Cbf2iW2g,4yddo2A.3EW_3/Un03Vj0iof420D5jjDBttJ0xeRR2Qz7wRw1.3//_i8Kb8>0>ybAOw1.36wS81,13Xq3o>0>wVQg@kwS41.24M0@4Z0c0>z7wMw1,1<cv@@?w80ey6Y/_cv@@?w808A5isY.exQY/_cv@@.w808A5cYY.exyY/_cv@@?w808A57sY.exgY/_cv@@.w808A51YY.ew@Y/_i8QZ3YY.8A5YsU.eycYv/xs0fy5g2.2bfvre.2W.w.bU4<cs3ELvb/UIZUYU.bE02,cs2@1<eyCYL/yPT8Pw.Kw4<NMbU2<W8_O/@bfrne.2W?,370Lw8,3Eufb/UIZDIU.bE.1.cs2@1Mg.exxYL/yMRXPw.Ly;NM4yd5juz.18znMA8ey3Yf/ct98zngA84ydfiaz.3Ewf7/UIdhIU.bUw<cs18zhk6EM.i8RY923EkL3/P7ii8RQ9218zjQ0EM.W4_N/@b3h7e.2@8<370i8QlRq80>ydv2gwW27M/YNQAydt2gwi8QZTq8.ewuYv/yMTsPg.Ly;NM4yd5qiy.18znMA8ezMX/_ct98zngA84ydfsay.3EXv3/UIdFYQ.bUw<cs18zhlPEw.i8RY923EL@/_P7ii8RQ9218zjSCEw.WbPM/ZdxvYfx8LV/Zcyv_Eq@X/QC9N4y5M0@490c.fp0a?fx183.18yMmSRg.i8KUa>0>z1VMbELK/_QC9Nkyb1pPl.18wXwE?<@4Rw8.37ri8RI943HiwYvh,goB4Dg29Mkyd5uix,NMbUw<i8DLW2LL/Z8ytUNOky9WAO9VQy3MM7EJ@X/Qyb1kzl.18eVwE?.3Ue30w.i8QZ0G8.eyTZv/xs1VGUnrt218oZJcyuR9zlOt.Yvg02bvg18wYk4W3jL/Z8euJRXQO9X@yTXL/3N@:bw1<Wq3U/ZC3NZ4,NZAyduMKW2w,ezgX/_i8n03UV7_f/i8IlOdg0>y9wy01.3FdfP/MYvg.NZAyduMGW2w,eywX/_i8n03UUn_f/oLbZ27P0i8I5AJg.cnVvU0w?.WvTX/Yf7Qg.37Si8RX3bEa<W6zL/Z8xs0fzJ_X/Z8yNlwR,i8C2e>.eDc@/_3NZ.37Si8RX2rEa<W3zL/Z8xs0fzG_X/Z8yNkMR,i8C2c>.eCs@/_3NZ0>ybwO01.1cyXcM?.i8B49118yUcE?.i8B490x8yUcU?.i8B491x8yQMA2cq3o>,18ekMA40@kwS41.1ceTgA60@kwS81.1cyrc8?.WgLY/Yf7Qg.cq3o>,76wSc1,1i8dY90w03UVA@/_WlHX/ZC3N@4:18znI8KwE<NZKxwXv/i8A494y5M0@eY_H/SbO_gxYM4yb1mXj.35@n@0c>.eDp@L/pwYvx}ijDKj0Z7ZuAK@f/3NZ.b_2<WfrK/Z8xs0fzU7T/Z1Lw.1w3FvLv/Sqgcvp8znIcKwE,3E4eX/Qy5M0@ex_H/SbO_gxYM4yb1gbj.35@D@0i>.eBJ@L/3NZ4.3EE@L/UIUW0PL/Z8zjRODw.i8D6cs3EK@L/@Dm_v/pwYvh,Lg.603Fq_v/Sof7Qg0>O9X@xEXf/WlLS/Zcyv_Ei@T/QO9_@y3Xf/ioD4i8n03Uni_f/WpbZ/Z8yMS3Qw.i8RX2HEa<cvp8ykMA4ex6Xf/i8Jc9118yo5o?.WtnV/Yf7Qg0>6@?,eBo_L/3NZ4.18znI8KwE<NZKwgXf/i8B490zFFLD/XEa<i8RX237SWfrH/Z8yNknQw.i8C2g>.eC3@v/KwU,18zjlhDw.i8DvWc_G/@5M7kji8I5Xd4.cq0oM4,7FmfD/XE6<i8QRdpU0>y9T@yAWL/xs1R2kOduMrFd_D/U0XbkMfhvLFa_D/SpCbwYvx}w_Y13UW73g.gluW2w,45mgll1l5l8yvljyvJ8wuNE?.i8J@237SW77I/@9h2gkw_I23Umm1g.NEgAY;37x2jk<//_Qyb1lbh.18yVwM?.i8K8a>0>y9n2gMi8Koe>0>y9z2iE<i8Cs9ew,18yVww?.i8Bs9518yVxg?.i8Bs94x8yVx.g.i8Bs95x8yVxo?.i8Cs9e;fJFxw?.y9MAyM<@SC681.28D2jQ<3Xqoog4,@Sw6c1.28x2jT<i8fV?@6X1I.bw_<csDPi0@Zz2iE<ys8FOAybz2jE<i6fii8fV?@6DxQ.fd83XT9asx8C4y9x2jU<i07gi8C49dw,2UfM,379YQwfLoMAS<2D8i9x83W_2i8D7i8n0K>,183Qn7i8C49dw,18NMkNQ[4z71hXg[Wc7L/@@,w>z1W0d81v/7M189g.UfZ8ys6U;AwVMkwfhI58ysuU,w>wVNQwfgYt8zrMA2>0>y9MAy9h2gEWfDH/ZcyXgA2>.8n03Ulo6w.yTMA5bE1<cvpczrMA8>.eyNW/_j8D@LMo,1cynMAe4y912jES@z/Xw3<NebXZVgAa>0>yUP_tjUWmrN218Z@98qoMA8>0>123M18MuE4i8Q44ky9h2hMi8I5pYY0>z7w.1[i8I5lsY0>z7:18yMl7PM.ict0c;18yMkUPM.i8Jc9518ykw8i8n9t0W0L2jM:@5@N,4y3v2h8>S9ZM@Sx2ib<NAgAq.fBogAQM,8jrj8DP3Vi49fk<ax2jQ<y8gAQw,4yb12h8NUgAK=18ykgAg4z7h2gw;4z7h2hU;4z7x2i+4z7x2ig=4z7x2iw=4z7h2hw;cu498M=NQgA2:fB8gAZw,37Jj3DXgg@jNj79h0FI96wfxl8t.20L2ib:@4S<4ybh2hoi8RM_QwXt2gw3U9U2w.h0@Sp2g8joDWi8J49319atF1w@g1gofQ0kAVMw@3Aw80>S5Qw@4qg80>ybdgHe.23v2g8?@4ZMA.8J668n0t218wXMAU:fxe49.1@3Qy3L2iU:@5tx80>ybf2h8ytx9ysNcav1cziMUyTMA537ij8DKWb7F/Z8yRgAa8JY91hcyvrE0ez/Qy5M0@eAgE0>O9b2hcyu5dzjM6j8DPNQgA2;15cuS0L2ib:@5af/_Qybh2gMi3D13UcG2,i2D8ioD0i8J495x8zn3_i8n03Uko?.h8xI96xcevIfwPQy.18NYr//_grQ8<j2JI941c0OMAj8BQ91x9ytNdyuV8yoMAC;@SH2jj<i8CQ9b<1dyskNS@IB3NZ0>y3M058wYc1ioD4iof624MVWM@3s0s0>MV@0@3pMs0>O9@HUa<j8DDj2DyW1jD/Z8xs0fx6I8.18xtIfBs908eFQK4ybv2goi8f.ky9NAwF_AM1ZAwVt2h8sWd8yUMAC<4y9S4C9_EDli0549218yXgAI<4O9UQw1MkQV_44fAIlCA{}i3JQ921PnAy5Og@5gMI0>m4XnhMNQgA2>,18wTMAc.fx6A8.1cyQgAc4ybh2hoi2J49219es1c3Qv0i8n03UkE2,j3DXh8xI96z7h2g8?,44fAIkNXkwXt2gwsG8fJAgA28fw0oD2w_81ggDli8n93UlZ2g.csB5xeRRiQy9j2g8ioDsWlY3.18yTQgKwE<NZKy@VL/yogAR<fvgMuwvyogAY<eBl@L/pwYvh,j3DXgg@iNkk8Vg@4R0s.8dY90w13UgL_v/Wr3Z/ZczhM3i8IRvsI0>C9MAz7x2iU=4QV@M@ix2io<j2DPi0cs94O9l2goj8Bs96xc0tfHg0Yvh,i8JS84yb1jnb.18yNkCOM.i8D1i2DNi87V/Yf.@6SM,4wVMD8CLSg,3Ezev/QybdgTb,fJAoExc1RLkybdKKY3N@4:18yMnNOw.i8Jg24yb5tXa.18yp,g.i8I5QcE0>y91s7a.18yMnaOw.yQ0oxs1QFkybt2gUyPRwMw.Kww,18NUgA8>,4,3EWKf/Qy3@fYfxnH/_@b1pHa.25M0@4rf/_@wZU/_yPzEFKr/QOd1o6n.2Vhw80>yd5mqn.19ys58yMnpLM.i8QROFM.]0WezA/_Fbv/_MYv>ydi05cyRgA64Obn2hEi8Dfi8IRccE.87D/Yf>y3v2gM?@4bwk0>Obh2h0i8Cs_w?80193XHEfOn/MY0j8C4Nw?8018ygTMOg.i3Da3U8D1g.i8K499<1c0lgAg4O9SQgaF2io<i8d49201i8C49b<18yQgAk4i8F2io<i8C49cw,18yQgAs4i8r2hEi8B491x8yUgAE<4y9x2j;i8d49601i8Jc9618wQgAu054ySooi8KY98<1cyQgAk4Gdh0s6id7Lid7EhonAi0Z4NQy9x2i;wbMAQw<1RgkGd18k;Kwg,2bL2ic<i3Dgi0Z2MEn_3UmQ1,i3D1K;183Qb1i8B4960fAY0fJI29x2ic<i8JQ93y_1w,ewTUL/K0c,34ULLTB2gE?.ibzfZRfzFpL484zTUAxFz2gw?.g48f>z1Wwh8zgghi8B49718aQgA64wZy1c,@74g80>ybj2hgi3Bc97wfwM42.18yQgA64y9h2hMwbMAC:fxh_W/Z9ytO0L2ib:@5LMg0>z7h2g8;4ybn2g8j8DDjjDYswLH9Qydu05cevZP6kO9@HUa<i8f30kwF@KyjUL/i8n0ttV8ylMA24Ob1iH8.18yMQHO,j8D7ijD83Uaf2w.yUgAR<8n03UD74M.j8JA941caOgAi8AZ0cw0>MXp2gE3Ue55w.jg7Qict49501<i8J49318xs1QbAy3@fRTa4y3M08NQLd83XTgK44<FQbE_<i9zPi0@ZM2D2i6f2i8B49518yMmONM.i8BUc4y3v2g8.@4Ugc0>ybh2gMct8NXkzTt2hgi8B495wf7U:i8Js90x8yTMAc37ii8Dui8DUi2DKi0@LNAzTYQwXv2hg3Uex3M.i8n0LM4,183QnUi8BQ94x5cuR8ynMA6eIRpwYvh,j8DWj2DyLwE,1cyuvEtu7/Qy5M0@4p0M0>C3Ng5czm01j3JI91wfwWAc.1azlMJ>wXn2g83UeV3,jjDYsHNdyu6bv2gkct9dav5c0MMAj8Dej8Bc923ER@b/Qybl2gEyTMA54O9ZKwCUv/i8n03UVZ3,j8Jc9218ys9dzjM6joDQj8Ac9eBP//3NZ4.18yPmxNw.i8J644ybv2hgi8C499<18yMlVNw.i8C49a<18eXMAG;@3OM,82Y9fk;3UiZ<i8I6i8IlkYo0>wFME2Y9fg;3UiU1M.wXMAz;4fBs55xugfBc24Mg@4Eg,bA1<i3Dn3Uej<i8KY9aw,18yTgAk4y9@4Od90V8av1ceut83Qb8j0Z2VQy5OnhkwbMAY;1QiAybv2gUi8QlM98.bV;cs3EEJ/_Qybt2gUyXMAR<4xzQeweT/_i8fU_M@4Dho0>yb1rn5.1cym08j8BA950f7Q.wXMAz;9R3E2Y9fo;3UlF2,ict497w;WufY/ZCbwYvx}i8Kc99w,18ytZ80nMA84O9UQObt2goi8KQ9b<180vBcevx13Vb5cuTFT_z/MYvw;18yQgAm4y5M0@5m>0>z7NL//Z0xeQfxuAo.2bh2g8h8xI96y9MEfw0ofy0ky3Yw59yt1cevIfwZE,24M0@4Lfv/@Dd<3NZ0>y9DfU>2.i8dY94.3UDt@L/j8J4943FNLH/SoK3N@4:18yQo8yTUoxvYfxao2.18yMmGN,i8C60>0>yb1pP4.18ygmdN,i8I5BIg.8J068n03Umj2,i8IRxcg.eCg@L/3N@:8eY98M<13Uih4g.NUgAz;8,3FjfL/Sqgi8Doj8JQ91xcyud8yUMAC<4ybJ2iM<ioD4wTMA2>fxaIf.180kgA84w1MkMV@Q4fAIkNXuCNZ/_Abw1<MSoK3N@4:36x2io;4S9@@Cl@f/jon03Vj?83Z0ng8xc0fxsb@/Z4y6MAqeDg_L/i8RM_Qybh2hohj70i2J4923FC_v/QC9T4O9UAMFYAw352h8yMmEMM.i8IdGsc0>wfKKE_i8D6i8f.o7C/Yf>y91oz3.18ypjN010w>y9wg01.18yMlWMM.NA0F0kyb1m_3.2bg1y5M0@5_gQ.8K49dg,25M0@9mgg0>ybt2gUyPTKKw.Kww,18NUgA8>.3Z23M3EvdP/Qy3@fYfx38d.1cyvvEOJL/Qy1N6w1,NM5JtglN1nk5ugl_3yMmEKw.cta@?,4z7x2gm?}6q9B2gu?.Kg4<NQEC49101.2b1nmW.1CyrgA7>.bU2<yogA6>0>ydx2gg?.i8D7pECc91g1.18ykgA6ew0TL/xs1@3Lq491U1,13Un01M.i8I5zY8,@Sw1w1.24M0@4oMU.ct490w1<j8Dxhj7JWg_Q/Z8yPlCMw.yRooi3Jc93113Vf4ggD4hoDwggzE3UlS5M.xt9Q94ybH2jw<i8nJ3Uir4w.vx5cyWgAK<4S5V0@56N80>m4Xg@4d_r/P7JWjLQ/Z8xs2_?,4C9O4wfhvx8yMpczgOZ;4AFM4Cd13B80s19es0fwXs4.18zgg_j3D0sO18ysx9Qux8at1ces193Qv0ioDUiiD0ig78i3D7igZ2O4wVOw@3Nvv/Qy9zw01.18ygSmMg.i8I5DY4.8J068n03Ug9_v/i8JQ93ybfj6V.2W2<4O9n2hEj8Bk91x8NUgA8>,4,3EItH/QObl2goj8Js96x8w_z_3Una_f/yNRnMg.xtIfxbPY/_E@JD/UIUW6ft/Zczgk@zw.KlA2.19ys58yMmtJw.i8IUWps5.1cyvJ5cuQNXkybdgX1.2bhxxcySgAg4i8H2io<i8K499<37h2g8?,4y9x2iM<i8J49518yogAO<4ybh2hMi8B491x8yUgAE<4y9x2j;i8DoioDdj2DMi0c494y9h2h0WPIf7M18yQUwi8I5Bs,4y9MAwFOAy1@L/3M0fxK8,18eglPM,sy6_p<ezLTf/i8IRsc<@Shyy4M7n0i8IeWXYf7M18yMlpM,i8Jg24yb5kr,18yp,g.i8I5ec,4y91iD,18yMkOM,yQ0oxs1QGAybt2gUyPT8JM.Kww,18NUgA8>,4,3EkJD/Qy3@fYfxn//Z4yNk1M,honi3UhL//Wafo/@beewcTf/j8Q5VUM.bB60w.i8QlP8M0>C9Mkyb1j@R.18zjkMAw.i8IUcs3EjJH/@AM//pwYvx}i8D2i8IRDHY0>y3M061UL/3M1ceSMAc0@4kgc.6p4yqNm01,4AfKKM_wbMAZM;fxmMe.1cyqjm010w>wV1kW_.18yglfLM.icu49bw=3UeMZv/i8Jm28Je68n93UhC3w.i8I59XY0>y9xw01.18yMkpLM.i8A52HY0>yb1he_.2bg1y5M0@5lh80>ybdg6_.3Fp_n/XE2<i8QR48M.8D7W37o/Z8w_z_3Uma@/_yMTxLw.xsAfx7PX/_Exdv/UIUWeTq/ZczgnxyM.KjM4.18zhmJyM.ioD1i8I58bg0>yddh6h.18yPwNMewLSv/WjTX/Z8yUgAA<4wHx2iM<3UgC0w.i8KQ9a<18aXgAM<4wV@78jct98Z_sNQAy9Mky9Y4zTYky9NAwVt2hg3Uex@f/ict497w;wXMAz;4fx9fR/Z8yQgAk4ydi058QuDF_Lv/Qyd5via.2@g<4O9_P70Wdfn/Z8yTgAe8KY9dg,18oZ3EfZv/Qy3@fYfxt7K/@bfu@Z.25_M@4M@X/@yiRL/yPzE@ZD/QOd1qKa.2VI080>yd5rKa.19ys58yMkKIM.i8QR7V,]0W3To/_FxeX/MYvx}i8IRArQ0>ybl2g8j8D0A4C9Mky3M051wu7/MY0hw@Tz4U>,j07ai3D1tu54yVMAR<4y9l2g8honr3UA92g.ibH////_vQy9@2n/MY0i2ekNw?8018ylgAgeAnZv/j2D9WmHX/Z8yPkwLg.Kw4,18yMV8yMk1Lg.i2D8u2kNQAybz2jE<iftQ9518esx83Qv1i8D2i8n0K>,183Qjgi3Bk930fwz8f.18eRgAc0@3I0M0>ybx2j8<ict497w;NUgAz;8,18wY03i3C498;fwwjQ/Z8yQgAc4yd312U?,4zhWkwfhcx8ykMAc4y9OAzTSAyb1niY.18yoog?.i8I5rHM0>y9A0w1.18NUgAw=3FJ_f/Qy9@4z1U098et0fwVXS/Z5xugfxpnS/_FX_T/M@Tj2gMpECclw?.20L2jT:@4IfP/Qybv2h0i8D1wu7/MY0i8CYPw?801dxugfypDY/_FzfP/V18yTgAe8IZBrc.bE8<j8Bs96xcylgA64z7x2gw?,g,ewlRv/j8Jk91xcyRMAq4y3@fYfxiXT/@b1rKX.25M0@48fv/@xuRf/yPzENZv/QOd1qa8.2Vhw80>C9Mkyb1g6N.18yPx8zhlWy,i8QRW8Q.370W0Dm/ZcyRMAq4Obl2goWtvS/Z8yTgAebY6<i8Bc96xcylgA6ey1Rf/K0c,1cyRgA6cjy@_uk92w1.18Kc_Tk@eBCYgwi8Jc96x8qrgA8>0>123M18Z@98MuE4i8Q45AwHx2iU<i3K49e;fwy7J/_6x2io;4ybduGW.1dyvJ8NUgAK=3Fs@/_Qyb1s@W.36w1w1,1WiTU/Yf7M18yMgAj8DxyTMA537ij2DNj8QA0kO9VKysRL/i8Jk92ybv2gkj8DSWeLk/Z8xs0fzFI5.1cyigAjoQY1AS9Z4MXr2go3U9zY/_A{}j8Dwj2DMi0c494y9h2gojonJtn98yRgA6eCjZL/pF1cyu18yTMA64ybt2h8j2DMi0c494y9h2goijDZsN18eRMA27c9jjDY3Ucq1,jonJtjfHLMYv>ybk218yMnZKg.i2Dgi3T/MY0tCF8yMnPKg.yQ0oxs1RtbZA<W5Hm/Z8yMnrKg.3Xpga8jitsd8yN3HMCof7Qg0>ybs218yMmRKg.i8IlFHA0>y9MkwFYky1@v/3M0fxCc1.18es8fwG8,2_p<ew8RL/i8I5yrA,@Sk2y4QDmVi8IMWXwf7Q.i8JQ93ybfhmN.2W2<4z7x2gw?,g,eyvQL/i8fU_M@5ov/_Qib5kWV.15xt8fx57//EYd7/UIUW5Dl/ZczgkQxw.KiI4.18zhkpxw.ioD1i8I5zaU0>yddnSb.18yPwNMeyrQ/_Whb/_ZC3NZ4.18yMnNK,i8Jg24yb5tWU.18yp,g.i8I5Qbw0>y91s6U.18yMnaK,yQ0oxs0fx2n/_Z8yTgAe8IZnb,bE8<icu49201,1<Werh/Z8w_z_3UnW_L/h8IdBrw0>m5Og@4WLX/@wTQv/yPzEEdj/QOd1nK5.2Vhw80>yd5m25.19ys58yMnjHg.i8QRN8E.]0Webi/_FG_X/MYvh,i8Js9418yspcyRMA64y9SkwfKKA_j3BI93183Qnpi8f.o7C/Yf>yb3h6U.18yst8ygn_JM.pAi9H74>,wuv/MY0j8Cs@g?8018ypPN010w>wVMD9bj07Ji3JI90wfwU7Z/Z8yQgA64y9h2h0WjXM/ZC3NZ4.18yRMAm4w9MM@4Yvf/Qybn2hoi3Doi0Z2MQy9N@B9Yf/pwYvh,i8JV28JN68nS3UiN<i8I5uHs0>y9wg01.18yMlIJM.i8A5nrs0>yb1mqT.2bg1y5M0@4uf/_Qybt2gUyPTUHw.Kww,18NUgA8>,4,3EwJ3/Qy3@fYfxkT/_Z4yMkNJM.hon03UgZ//Wdff/@beewYQ/_j8Q55Ug.bB60w.i8Ql_8c0>C9Mkyb1m@I.18zjlwyg.i8IUcs3EvJ7/@D@_L/pwYvx}i8n_Lw4,19ys183Qj@i8INj8QcLg<19av19zjgVi07SijDM3U8.g.j2D8i3D23UeY_L/i8C10>0>y91o6S.18yMmaJw.yQ0oxs0fx9P@/Z8yTgAe8IZ7aU.bE8<icu49201,1<Warf/Z8w_z_3UlN_L/yPRmJw.xvYfx6f@/_E@sX/UIUW6bi/ZczgkZwM.KlA2.18zhkywM.ioD1i8I5BqI0>yddoq8.18yPwNMeyAQf/Wij@/Yf7U:ioDRWhrY/@b5vGR.25Qw@4Mfb/@ytPL/yPzE1Jb/QOd1hi3.2Vfgg0>yd5sq2.19ys58yMkVGM.i8QRaEw.]0W4zg/_Fwvb/Qydd3Zcesofw_r@/Z8ysp9Qux8atpcesp93QvMioDUiiDMig70i3DTigZ2MeDh_L/i8JY92zExZ3/QC9NKCmVv/i8JQ93ybfgiJ.2W2<4z7x2gw?,g,eyePL/i8fU_M@5Sf7/UIRfHk.8nS3UjaYv/We7d/@beexaQv/j8Q59o8.bAX1,i8Ql2E80>C9Mkyb1nSG.18zjlKxM.i8IUcs3Ezc/_@CbYv/j8DUi8JY91x8yTgAi4S9_4MFY4w312h8ykgA6eCv@L/i8eY9ew<13Upl1M.K3Y<NQLd83XSk9ew<FQ37ii9x8yogA@<4y9x2jo<i8eY9dw<13Uh5Vf/Wh3A/Z8zkM10kybh2gwioR41058ykgA84wVNw@3jwc0>y5Og@5gvf/Qy9j2g8joDYWtHH/Z8yPlaJ,i8J624wXx2iE<3UbH1w.i8Daj8D7i3Dn3UchXf/i8IR8Hg.eDaZL/i8I55Hg.8J864yb5giQ.18ehnRIM.ykMAq0@2tMk.8J068n03Une1g.i8eY9e:3UzX0w.yQgAq8n03UjL0w.i8eY9bw;3UjS1,i8JQ93y_1w,ezLPf/j8Ks9e<18yVgAa>.37Sjonrt5J8Ks_Tk@eBCYgwic7G0QxFL2gw?.g48f>y9Q4zTUkz1Wwh80vF8yXMAK<4y9Q4wF@4MVS7cxiiDjLCg,19zggXi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY91y9YHU2<W8Pe/@5M0@e@>.fq491o1,13Unf0M.ZEgA7w4,4fxdM1.18yMk9IM.j8DxNE0o?,st490w1<WnTM/Z8ypgAS<4z7x2jU=eB1_L/i3B4960fwI3F/Z8yUgAW<4zhp2gMi8JY9318yUMAG<4wVNQwfg_yU0w<Z2x2ic<i8BY9329x2ic<i3Bc950fwZY,20L2jR:@4Qg,4ybB2jU<i8Dhi8f_0nokcs2VfM,fd83XT7as58oYB80t58yUgA@<4ybL2iE<i0@Lz2jo<i2JY95183W_7i8Qkgbw1<i07ii8n9i0Z4O4wVOD88i8Dgct98Z_6bB2jk<xt9UnQwVNQyd5tB@.2@g<4wfhIt8yTMAe4y9MkC9Nj70WaPb/Z8yTgAe8KY9dg,18oZ3E6cL/Qy3@fYfxfo7.1c0mMAk4yb1rGN.18yQMAk4y9i0x8yPmGIg.i8I5CX40>y9xx01.18yRgAc4yb1p2N.18ZZF8yp08?.ict496:WmHE/Z8yRMAg8JY91gNQAS9Z4y9TKxqPv/i8Jk92ybv2gkj8DSWaDb/YNQAy972h8yPQQIg.i8n0i0Z8MASdf0rFeKD/UdY90w23UjZ?.NQgA2;1cyu7FFeX/QO9@QkNXj7JWgDB/Z43XpI96zFqun/Qybv2h0i8D1wu7/MY0i8CYPw?803Fuv7/Qz7x2iU=bVA<WoLZ/Z8xtaV?,4ybfAOb1qWM.183Qjhi8D1i2DVj8QcBg<19zjMhi07_i3DV3UaT0M.j2D8icu49bw=ijD03UfLVL/i8C60>0>y91mqM.18yMlLI,yQ0oxs0fx5PN/Z8yTgAe8IZ0qw.bE8<icu49201,1<W8L9/Z8w_z_3UjV1g.icu49bw=i8IR9H,eCcVL/ict497w;NUgAz;8,3Fquv/Qybt2gULMo,18ykMA64i8x2io<W2j9/@U0M,4ybj2goNebXZVgAa>0>yUP_tjUWmrN218qrgA8>0>123M143Xq499w,18Z@98MuE4i8Q45AybdquL.1cau18euwfwDzJ/Z8yUgAA<4i8H2io<h8D5j8JA9418yogAI<4ybh2hgi8C49cw,18yQgAs4y9h2goi8K49a<18yogAM<eCgXL/i8JQ93ybfuiC.2W2<eyiOv/ZEgA7w4,4fxhPY/_7h2g80w,eBoUv/h8IJ8aY0>m5Xg@4k@D/@z2N/_yPzEaYL/QOd1tJX.2VHgc0>yd5uJX.19ys58yMluF,i8QRjU4.]0W6T9/_F5eD/Qybt2gULMo,3E@sv/Xw3<NebXZVgAa>0>yUP_tjUWmrN218Z@98qoMA8>0>123M18MuE4i8Q44ky9x2iU<WrXW/Z8yT08xsAfxlA1.2bi1y5Og@5jw40>y5ZHA1<i8IUj8I5iWU0>wfhf58yt58avBczgOR;4Cdf3580vZ8evAfwyo2.1casF9et0fwz03.2bg1y5M0@4ffT/Qybt2gUyPS_Fg.Kww,18NUgA8>,4,3Eisv/Qy3@fYfxgvW/@b1vCJ.25M0@4@vD/@ysNL/yPzE1sH/QOd1u1W.2VUM80>yd5slW.19ys58yMkUEM.i8QRao,]0W4v8/_FKLD/Qy9QkzTSkyb1pmJ.18yoog?.i8I5zWQ0>y9y0w1.18ylgAc4z7h2hU;cu498M<2<WsLA/Z8NUgA@=18NUgAS;4,3F2tT/QybdAy9OAwVPDcri8Ks9aw,18av58etB83Qvbi3D83Ua@?.j8D7WuTU/Z8yNkgHg.i8Cg0>0>yb1gaJ.18ygnPH,i8I5_aM.8J068n03Ukg?.i8I5WGM.eDG@f/i8QY4AwVPM@3f_P/Qy9NQzhWkMFNQwVPQwfh_B8yt58avB80s58evF83Qb1WhHY/Z8yTgAe8IZkag.bE8<icu49201,1<WdH5/Z8w_z_3Ulf_f/h8IdyqM0>m5Og@4f_P/@wHNv/yPzEBcz/QOd1mZV.2Vhw80>yd5lhV.19ys58yMn7Eg.i8QRK7U.]0Wdr6/_F0fP/M@Sh2g8w@01w_01j3DX3Vb22t18xsAfxiM2.11yskNXuAFUf/i8QYdAwVPM@3QfT/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWqLZ/Z8yTgAe8IZvGc.bE8<icu49201,1<W0z5/Z8w_z_3Un5_L/yMmUGM.xs0fxbv@/_EmYj/UIUWcj7/Zczgmvu,Kko2.18zhm4u,ioD1i8I5ZW,4ydduxZ.18yPwNMew6NL/Wnz@/Z8ysJ8yTMAebV;i8QlbTw0>wFMP70i8DpW135/Z8yTgAe8KY9dg,18oZ3Evcj/Qy3@fYfxas1.18yMkzGM.i0ds9518ylw8i8Il2WI0>ybfvOG.3FRvr/QkNXj7JWvHu/Z8yp,g.i8AlTWE0>yb1uyG.2bg1y5M7kpi8I5SGE.eCE_f/goDEWjbX/Yf7Qg0>ybt2gUyPRBEw.Kww,18NUgA8>,4,3EXYf/Qy9MAyb1pSG.18w_H_3UlC_f/wPSkGw<@4mvP/@wVM/_yPzEEIr/QOd1nRT.2Vmg80>yd5m9T.19ys58yMnlDM.i8QRNDM.]0Wej4/_FpL/_MYvw;14yMl1Gw.hon03UjT@v/Wef2/@beexcNL/j8Q59Ts.bBp0w.i8Ql37s0>C9Mkyb1n@v.18zjlMv,i8IUcs3EzIj/@CU@v/i8IRWGA0>kNM8Jm64i8r2hEgoD5WjPW/Yf7U:yMniGg.xs0fxfPT/_Etsb/UIUWdX5/Zczgmetw.Knw3.18zhmutw.ioD1i8I54pY0>yddg9Y.18yPwNMewwNf/WrTT/@3foiF<3Uhc_L/W2D2/@beeyiNv/j8Q5gDo.bDz0M.i8QlkDo0>C9Mkyb1smu.18zjmSuM.i8IUcs3ERcf/@Ad_L/3NZ.{}glt1lAC9RA5lglhlkQy3X1y9v2g4LM,g18yngA2ewsM/_ioD7jonSt7V5cujH5wYvw;3EEY7/UcU17lEjjDQsSd8yQgA24O9YEJY90hcyvVcau9azgMwK<g18es983QvgW5b4/Z9ysl8xs1UMDgOi8D3j8DZpF18ytF8yuW_?,ezwMv/i8n0u0J8asdQ9Aw1NuLxAewXMv/wPw4tdp8wYgoj8D_mRR1n45tglV1n@AgMv/jg7IWnH/_Yf7Ug:8f_0DYbK>,333NZ4.11lXEa<glp1lk5kloDZkQy9YQy1X3w4.18yTU8cvrE6If/QybuN2W2w,37SykgA6ew6M/_NQgA3;29h2gsw_Q3t1N8yTIoi8QRj7k.exRML/xs0fBc0fJI29h2gci8I5SGs0>y5M7g4NA0E0kydh2h0hj7_i8RI9315cuR8NQgAa;18ykgA4{}yTMA6bE01,i8DKWe_1/Z8xs0fzI8,18Muw4xs1@TERo_QC9XAz1UMh80RMA4eIn3NZ4.19eskfwHs,19wYogijDutbp9yMpceuxRVAQ3rwxdxvZR8KIB3NY0joJD44O9_QSbrMxcymgAaezrL/_jonAt0xdyutdeiZQTAyb1h@D.18xs1Q14O9q22bh2gcxs1Ra4O9WAyb1giD.18Kg3M///Z_wub/MY0i2ecQ.g8.fxpU,1cyTMAaeBR//3NZ0>O9_QSbvN3Etb/_QS5_TnLi874e?.370mRR1n45tglV1nYcf7M2_6<ey@Mf/i8D1ioI6i8A1ioJm24w1MAy9kgx8zlgAa4S5_TkJWP0f7Ug:{}pCoK3N@4:19zlsgjoJ_44S5_Tg5ijA7sKVcynAgi8AaWmj/_ZCA8JY91MNQHU3<Wc2/_ZcyTMAaeD7_L/pwYvh,w_Y2vMKU?,ccf7Qg0>5nKwE,11lAkNZA5lglhlkQy9YQy1X2w4.18yTU8cvp8zmMA84Odr2gMWd_0/Z8yTIgKwE<NZEB490zEOY3/Qz7h2go;8B490Mf7M1CpyUf7Ug:8JY90yW.g0>y9XKz_L/_i8n03UXS<ic7E18n0vJWdmfZ9yuN8Muc4j07HWNkf7U:ijD6sCd9wYggijDstbF9yMgAj3DMtuB8yTMA64Q3t2g8i8n_thPH7QObvN1cyTs8j8BY91zEXHT/QS5_Tg8j8D_j3ATte5cyv58wu40Yf/vHabv2gccta@0M,eyBLL/WW0f7M2_6<ewCL/_ioIk94ydj2goi8D6i8AgioJ490x80t18yko8i8J491x8xs1RbKINpwYvx}pCoK3N@4:1CpyUf7Ug:4ydi118yQ?i8n0t0l8eh1OXAy9hx18yj7Fb//Sqgi874a?.370mRR1n45tglV1nYegpCoK3N@4:23_M9_1Hw1<MRmW2w,4y9Vk5nglp1lk5kkQy9YQy1X7y2.18yTU8cvrEjH/_QybmN18zjl_t,ykgA54y9T@z7LL/i8RQ952_?,469NewRMf/NAgA8025M7kjyQgAq2k0Y,fg2<fB4gA84m5V0@4Tg80>ydh2h0hj70ict493:j8SA9e<18ykgA86qgi8JQ922bv2gkKx<1cykgAaewELL/j8J492x8w_wg3Um20w.j8JQ931cekgAg7hHLNw,1cykgAaey@Lv/j8J492x8ys58yQgAg4y90kybl2h8i072jonSi8Bh24ydl2gMtinHa{}pCoK3N@4:19zlogjoJS44S5ZDg5ijA6sKVcyn4gi8AaWmb/_Z8ytC@0>.370j8B492xczqMAs>0>yd5oFM.1cyu_EXbP/P7Scs1cyu_EAbX/QObh2gExs11yssfymo1.1c0QgAi4S5ZDkNWh7/_@gjoJ624Sbvx1cyvtcykgAa4O9v2gMW8qX/ZdxvZcyQgAa0@4WfX/QS9_AQV1w@5TfX/Qy9Skyd5hxM.1cyuYNMbU.g.W7eY/YNZAO9XP70W1u@/Z1ysu5M7ywict493w;j8DCysvEzrX/Un0tgR8yUMA4>0>y5OnYlh8D_W9iY/Zcyu_EbbL/@BD//i8J493x8es5@Ukydt2gUi8BQ92x8yRgAa4wFMki9_HY1<W1WZ/Z8xs1U6kybz2gg?.i8J493x8es5_ReKF3NZ4.3EOXH/UI0w_w4tdKdkeG3UKZQ48fU2g@kMEfUm0@kM0z2t818yTgAe37ih8D_WdSZ/Z8zogAs080>y9h2goWNxC3NZ4.18yTgA64y9MHY1<W0qX/Z8yTgA6bE0w,h8D_W0iY/Z8xs1_R@AK//ict493w;j8DCysvEBXT/QObh2gExs1R4kybx2gg?.i8n03UZ10M.h8D_j8B492zEAbL/QO9X@wEKL/j8J492zFjLX/Sof7Qg0>O9_QSbvOzE_bH/QS5_TnLi874u88.370mQ5sglR1nA5vnsd8zogAs080>kN_P7ricu49e+i8B491x8zogAC080>y9h2g83N@4:18yTgA68JY91iW.E.ewZK/_i8n0vFN8LITcPcPcPcPcifvCic7G1onivJd8yTgA28R2_QObp2goi8Q4w4yd1cp8ykgAa4AV72gfxgE1,f7Q.pCoK3N@4:19yTgA64Cbl2gwgoJY9118yrgAs>.81Y92.3UhK?.i8DhyvV8zpgAs>.bY1<W4uX/Z9yQMA646bv2ggLwc,18ysF90QMA84y1Uw3M/Z8at7EMrD/QA3n2g8jon_tnjHtMYvh,ioJ764ydB2hM?.LM4,18yogAs>0>CbjO11yTsgWeGW/Z9yQYogoJ_4bU3<i8Daigdf84y1Uw3M/Z8at7EpXD/QSbtOxcyvZ90RY8j8CQ9e<3EvXD/QS5Zw@4pw40>S9ZQAV7Tieiof4a4MXp2gE3UiL_L/ijAs90@41v/_XYM<WaKV/_4MnVL12h8ys75_DY0ioJ49218yk4wjon_3UgP?.ioIk94ydx2jw<WOIf7Ug:{}pCoK3N@4:19zksEjoJ_a4S5_Tg5ijAnsKVcynAEi8A8j8KY9e<35@7t9wYgEj3JA92wfxmX//F6fX/MYvx}WdLR/Z9yQMA646bv2ggLwc,18ysF90QMA84y1Uw3M/Z8at7Eprz/QA3n2g8jon_tmvF6f/_Sof7Qg0>CbtNx8yrgAs>0>CblO11yTYgW8vR/Z9yQYogoJ_4bU3<i8Daigdf84y1Uw3M/Z8at7E5bz/QSbrOxcyvZ90RY8j8CI9e<3Ebbz/QS5XngnjoDLijAvt9_FHfX/SoK3N@4:15cvZ9wYgEj3JA92wfxp_@/_FivT/Qydx2jw<WvX@/Z8yRgAe4wVQ0@eIvP/Qydt2gUi8BQ92x8at18yRgAa4i9_HY1<i8D1j8B491zEVXz/QObh2goi8n0u1R8yUgA4>0>ybl2gUi3DgvYvFqvP/Sof7Qg.eybJL/j8J491yb08fU17jizl3Gw@bLt1i3@0AfBca3@5wfBc08Mw@4dLP/Qybt2gUct94yvZcykgAaeyfKv/i8S49702.1cyQgAa4y9h2goWNN8yTgA64y9MHY1<j8B492zEJbr/QObh2gEi8JQ91yW08,4i9_QO9h2gEWayT/ZcyQgAa4y5M7_3WsPX/ZC3N@4:23_M4fzJs2.11lXEa<glp1lkkNXk5klky9Zle9@Qy1Xaw1.18yTU8cvrE_Hv/Q69N8fX0M@4yw8.eydLf/i8QZkSE0>z1W0d8zpz/NY0K;98wuc.e3_i3D3i0Z7Sbw.2.i3D3i0Z2SezDJ/_i8n0t1uW2w,37Si8D7WaeT/Z8ysl8xs1_1rS;i8RY933Enbz/Qz7h2gg<28n0tjr5@mYdNT,37iNvBKx2io<Ne9VfY75@nX0i0@Lh2hgifvRKw<x8et183Qfgi8Bk9118zrgA4>0>i9X@x9Kf/xs1R5UK492w1,B0f,3Q0w,3Uju?.grA5<ioDocsB4yu8NZAi9X@wmJv/ioD7i8n03Uza<Lg<11Lw<5RcmqgpCoK3N@4:11Kgk,19ytwNOki9Uz7Sh8DLWdyQ/Z9yst8xs0fzFQ,2bflWj.25_M@9Pw,4M1_kAVXDf6i8SY9a<3Eqrv/UD1xs1RkYnVrMTrrM.i8JQ9135@mW490w1.34UDA_MsnVvI183W@49cw,18ev1P9Ayb1mur.18xs1Q6w@Sg2y4M0@5eMs,Yv0{}io76;uBk//3NZ.ezHI/_ioD6wPwm3Ug41w.yPSZAw.xvZV5j70i874G>.5JtglN1nk5ugl_3A4ydJ2iw<Kww,18NUgAE;4,3EcHj/@Lbi8SQ9a<2W2<4z7x2iw;g,ewiJf/i8fU_M@52L/_UIlMFE.8ni3UjY_L/W6mP/@beezeJL/j8Q5dSQ.bAt1w.i8QlzCs0>C9Mkyb1g6g.18zjnOr,i8IUcs3E4bn/@CZ_L/3NY0i8JZ4bEa<cvrEmbn/Q69NuBu_v/K>,33pyUf7Ug:4ybB2h.g.i8RQ92x5cvYNM4z7h2gw;4z7h2g8;ky9d2h8xt8fzL3@/Yf7Q.pCoK3N@4:18yt58ytR8ykgAa4wFMkwVSkwfhKB8xuQfx7E1.15cvp9yux8yPgAhj79csBdav14yu94yu_ERrf/Qy5M0@83>,@4cw40>A1NAAVXDbfi8J4921C3N@4:1d0vubfj@h.1c0v18ykgA88n_3UAT?.i8Kk9401.18es8fzBv@/ZcenMA20@3q//QydH2iw<i8DLW2KR/@9MEn0tkn5@mYdDmQ0>ybx2j8<NvBKx2g8?.Ne9VfY74MnB@NAAfHYp8eQgA47cni8I5a9A0>y5M7gb3Xp0a8j0tiIf7M18wkgA2;58yQgA84ybB2h.g.Wvn@/Yf7Qg.87W42s.7joLSg,29l2goW5GR/Z8yu_EEHj/UJk91x8yUgAO<8f20kAfHYp8eQgA47b8WWpC3NZ4.3EqX7/UI0w_w43UjJ_L/w_xv3Vj2w_wC3Vj12cFR38fw@UfU4w@5Gw,4ybh2gwjonS3Unm_L/i8Kk9401.18yt58as58xsAfzUY,15cvrFKLX/MYvw;18zrgAE<bE8<icu49a;1<W8aN/Z8w_z_t0N8yQgA8eCr_L/pF2bfiGo.25_TjGWd6M/@beewWJf/j8Q5ESE.bDw1g.i8Ql@Cg0>C9Mkyb1mSd.18zjluqw.i8IUcs3Evbb/@KKK>,3FLvP/QwVMw@eGfP/Qydh2gwj8JQ90x8yggAjjD@3U9E?.i8Ik94y9Ski9XAi9V@yeIL/i8D5i8n0u2VQdEIZdEY.8n_3UDS?.ig7Li8J49218eogAg>.7@XWl3Y/Yf7U:W2eM/@3e0hQSQybx2h.g.i8Jk921cyngA24wVMw@d9fP/Qydv2gEW7CN/@5M0@54LP/UJY92OW,g0bU71,WaWO/Z8zogAE<4y9h2goi8K49401.18ekgA80@dCM,4ybr2g8i8Bs90wf7Q.j3DZ3U8D1,j8J490ybl2gIcsB4yuZ8yPgAgrA5<WdGL/Z8ysd8xs1@nQkNZwYvg01CpyUf7Ug:4C9S8JY92wNOj7SjiDMgrA5<h8DyWaiL/Z8xs1@24A1NAAVTDbnyPQFzw.xvYfyks3.18yQgA84Q1ZQwVx2h.g.3UZP//yTMAaeyaIf/yTMAbey1If/WiTX/Yf7Q.i8SI9a<18yu_E2bb/UD2xs0fxoU,35@mYdtCE0>ybx2j8<NvBKx2g8?.Ne9VfY75@nX1i0@LMkwXh2ggsS58yMk2Bw.i8n0t5kfJA0Exc1QjuI8wvEg9M.t4e_p<8Bk91x8ykMA2exgIL/i8DLW9yN/@bl2goi8Jc90x8yUgAO<8f20kwfHY58eQgA47a@pwYvx}io76;uDA_v/3NZ0>ydJ2iw<Kww,18NUgAE;4,3EMGX/Qy3@fYfxubZ/@bdnal.25Zw@4RfT/@wlHL/yPzEvH7/QOd1utD.2VZgk0>yd5jVy.19ys58yMmNyw.i8QRECs.]0Wc2L/_FBvT/Qydv2gEW56L/@5M0@8b_T/UJY92OW,g0bU71,cs0NXuy2If/i8S49a<18NMgA;ky9h2g8pF1CpyUf7Ug:8Jk92N1Kgk,19ytwNOj7Sh8DLWcuJ/Z9yst8xs0fzAz@/@bv2gEcsANZA6V1g,4C9M4i9UKyyHv/i8n03UUC_L/yPQHz,xvYfytI,1c0vR8eiMAsW98yTMA2ewUIf/xs1RhcnVrMSIq,NvBKx2g8?.Ne9VfY75@nX1i0@Lz2j8<i3Jc911P6Ayb3jKk.18xsBQ3w@Siiy4Og@5Zw4.6qgi8449;7Fg//Qi9b2h9yvlcyngA2cj1unX6i8Bs91y9O@IhpwYvx}wvIg9M.t2K_p<8f30uxrIf/i8SY9a<3EDG/_Qybx2j8<ig@LNAMVW7bdh8II94Obt2g8i8Js91zFqLz/SoK3N@4:18yTgA2bE8<icu49a;1<WdmI/Z8w_z_3Uk0//yMm5AM.xs0fxfb@/Z1yPXEBq/_QOd1vVB.2Ve0o0>yd5llw.19ys58yMn8y,i8QRKmk.]0WduJ/_FJ_X/Qybt2goKww,18NUgAE;4,3EpWP/Qy3@fYfxpjY/@b3huj.25Og@4xLP/@yWG/_yPzE8W/_QOd1oNB.2V4Mo0>yd5udv.19ys58yMlmy,i8QRhSk.]0W6mJ/_Fh_P/Qybv2goW8qK/Z1ysq5M7l1NvBL3vtC.18yUgAO<cnVrEgA2>.cjyuj_1NvB@MQwfHYd8eQgA47cki8I5wV80>y5M7g83Xp0a8j0thl8wsk<1WnLX/Z1wvUg9M.teK_p<463Nw7EOWX/Qybv2goW16K/Z8yUgAO<4wfHYd8eQgA47bcWXV8ylMA6cj1unX7ysfH287X42s.7gGLSg,23MM7EyqX/Qybv2g8Wc@J/Z8yUgAO<4AfHYt8eQgA47bei8Js91zFMLT/Sqgw_Y3vMKU?,ccf7Qg0>5nKwE,11lA5lglhlkQy9YQy1Xdw.g18yTU8cvpczqMAQ<eyAHf/i8JX437SKwE,11ysrEAqP/QybuNwNZHEa<ykgA6exZHf/i8D5ykgA7ewhIv/ymMAa4z1W0f7h2gI?,4ydCf/7M2U;Ay1UM.UfZ8esd83QvoK,8018esd83Qboi8R49415cuh8ykgA44w1SQybt2ggh8DTW2WJ/@5M0@81w40>Obv2hMioQI74AVXM@2LM,4ydh2gMi8B490x8zoQ.f/Kw,g1cyuV4yvvEwWP/Qy5M7VCi8D2LwE,1cyu_EvGP/Qy5M7hhj2DEi8JQ90ybv2goKx<18zqM5?3/QO9p2gMi8DEj2Dwi8B493zEWWD/Qy3@11Qgbw1<i874S.105JtglN1nk5ugl_3pwYvh,i8JQ90ybv2goKx<1cymgAc4y9n2gUWaKF/Z8w_wgts19yuN8ziMHijDL3Udb//i8RY92yWp<bU1<W96H/@5M0@e_LX/UJY91OW2<4ydt2gMW7qG/_FVLX/V0NMeBV//pwYvx}kXI1<i8fI84ydt2gsW5OH/Z8ys98wPw0t1ybv2gsi8D6i8B490zEEH7/Qybl2g8ysd8ytvEwWD/Qy3N229S5L3pCoK3N@4:1jKM4,18w@Mwi8RQ91PE3aL/Qy9MAy3e01Q68JY91N8ysp8ykgA2ezyLv/i8Jk90y9MQy9R@wPGv/i8f488DomYdCpyUf7Ug:5eX?,4y3X118zngA3eyYGL/i8cU07gli8IlhUY0>y5QDg7NE8o?,j7ri8D7WeCE/Z8wYggytxrMV1jKM4,18w@Mwi8RQ91PEvaH/Qy9MAy3e01Q68JY91N8ysp8ykgA2eyyVL/i8Jk90y9MQy9R@yzGf/i8f488DomYdCpyUf7Ug:45nglp1l5mZ?,5d8wuP;i8RQ91PE8GH/Qy9MQy3e.fx8s1.2br2gsw_Q13UX8?.i8JU2bEa<cvp1Lf//_EwGD/QC9NUfZ0w@5Jw40>ydfv1r.3ECGD/Qydfvdr.18ysnEyWD/Qy5Xg@4cw40>y5M0@4ag4.bEa<cvp8yuZ8ykgA2ewlGf/i8JY90yW2w,37Si8B4923E_Wv/Qy9h2gEhon_3UZN?.honA3UXE<i8QZCo8.exYGf/i8D5h3Kw:@5L>.8eU4;4fxu41.18zjRVmM.W0eF/Z8xs0fxaE,2W2w,37Si8D7WbKE/@W?,37Sh8DDioD7WaCF/Z8ysl8w_z_3Uio<i8QZbo8.ewgGf/i8DGi8RQ9314yv_5@mZ49214ymgAgct494g;NvB_h2gMi8K02<4wFMIjx@mX8NefN8I81Kyw,35@DZ494zEBWr/Qy3@fYfxbA1.18zjTewg.Wb6D/Z8yqw8<pyUf7Ug:37Ji8DvWdqC/Z8wsj;yuxrnk5sglV1nYeb3gWd.25OngGWbmB/@beewuGv/i8IlpU80>yddsxv.18yPF8ys8NMexPF/_3NY0Lg4,3HGSof7Ug:4ybuN2W2w,37SWb2D/Z1ysjFcLX/MYvx}i8RQ922W4<4i9_@zuFv/i8fU_M@5s_X/UIRzEM.8nS3UhB_L/W36B/@beeyqGf/j8Q58RY.bDM1,i8QlmBA0>C9Mkyb1sS1.18zjm@nw.i8IUcs3ETar/@AC_L/3N@:4i9VQydt2gMh8Cw;ewIGf/xs1R48J494wB0f,3Q0w,t7n7xh;2<i8RQ922W4<4i9V@wYFv/i8fU_M@5MLX/UI5X8I.8n03UiQ_L/W8@A/YNXoIUWfqD/ZczgnTnw.Kh05.18zhmSm,ioD1i8I5ao40>yddhFu.18yPwNMewUFL/Wnn@/_7xh;1<WqnZ/@b5oWb.25Qw@4evX/@wNFf/yPzECGv/QOd1nJu.2V30k0>yd5lFo.19ys58yMndw,i8QRLBQ.]0WdOB/_F@LT/MYvw;1jKM4,18w@Mwi8RQ91PEzar/Qy9MAy3e01Q68JY91N8ysp8ykgA2ey2VL/i8Jk90y9MQy9R@yPFf/i8f488DomYdCpyUf7Ug:5eX?,4y3X218zngA7ewYFL/i8D2i8cU07goyTMA74y9NAy9h2g8W8bJ/Z8yRgA28D3i8DnW6eA/Z8wYgwytxrMSpCbwYvx}lrQ1<kQy3X1x8zngA1ezHFv/i8D3i8cU07gJwTMA105_eUIZ2o80>ydt2g8Kww,18NQgA2>,3EDqf/Qy3@fZQbP7Ji8DvWfSz/Z8wYgoyuxrnscf7Q.i8JU2bEa<cvrE8an/UD7WXsf7Q.yMkyyw.xs1QN@z9EL/cuSbeewMFL/j8Q5G5s.bBn1w.i8QlY5o0>C9Mkyb1md_.18zjlkn,i8IUcs3EsGj/@KbkXI1<i8fI84ydt2gsW2OB/Z8ys98wPw0t1ybv2gsi8D6i8B490zEMLv/Qybl2g8ysd8ytvEkWf/Qy3N229S5L3pCoK3N@4:11lQ5mgll1l5ljKM4,18w@Noi8RQ92jEQWj/QC9NQy3e01Q2oJI92i3_gl_8kO9_@w9E/_i8f4m8DomRR1n45tglV1nYcf7Ug:4ybu0yW2w,37SgrX//_W1GA/Z9yTYgKwE<NZEB491jE1Gj/QCbvNyW2w,37SykgA4ezOE/_ioJ_8bEa<cvq9M@zwE/_ioJ_abEa<cvq9h2goWcOz/@9h2gsw_Q63Ukf0w.3NZ.{}honSu1J8zngAebE1<h8DTWfCy/Z8xs0fzJ01.18zmMAg8JY91iW4<4y9XKzqEL/i8fU40@5I>0>ybh2h0cvqW0w,8Dvi8B492zEmaj/QObh2h8yTMA48Dqhj79i8Rc9318zngAa4y9h2gMW4qy/Z8xs0fydQ,2bv2goi8RQ93yW2<4z7h2gU?,exxEv/i8fU_ThHyTMA7bEg<i8DKW4Gx/Z8w_z_3Ul0//yMnWxM.xs0fx3b//EDq3/UIUW0qA/ZczgkLmM.Kio7.18zhn6l,ioD1i8I5enQ0>yddiFq.18yPwNMex8EL/Wvf@/Yf7M2b5qG7.25QDibW56w/@beeyWE/_j8Q5hlk.bAB1M.i8QluBg0>C9Mkyb1uRY.18zjnumg.i8IUcs3E_a7/@Bc//3N@:bY,40W6qx/Z8yTgAg8JY910NQAy9h2g8W36z/@W0w,37Syt_E8Wf/Qybl2h8i8nit4x5cuRC3NZ4.1cauGU,1>ybt2g8yTMA44wVMAC9R4Mfh@1cyu9d0unEiG7/Qybt2g8j8Dyyt_EaW3/Qybl2h8ijDlsI58yTMA2ey7Ef/Wpn@/ZCA37rWmzZ/ZC3N@4:19yTYMKwE<NZKywEv/goD6WuzZ/Yf7Ug:5eX?,4y3X218zngA7ezIEv/i8D2i8cU07goyTMA74y9NAy9h2g8W4bw/Z8yRgA28D3i8DnW1ew/Z8wYgwytxrMSpCbwYvx}glplLg4,1ji8fIc4ydt2gcW9Cx/Z8ysd8wPw0t4m3v2gc0nVSi8QZYlc0>Obs0zECqr/Un0u4l8zmMA48D1Ly;NM4y9XQyd5mti.3EK9/_Qy9XAO9ZP7JW3Kz/Z8yt_EAV/_Qy3N329W5JtglX33N@4:3EuVX/UIUWeix/Z8zjSqkM.i8D6cs3EAVX/XQ1<WY6gpCoK3N@4:1ji8fI84ydt2gsWf6w/Z8ys58wPw0t6y3v2gs0nVxi8JU2bEa<cvp8ykgA237rW5Gw/@W3M,bU91,yssNMeznEf/i8Jc90y3@fZQ5ky9P@zRDL/i8f488DomYcf7Qg.8I5cEk.8n0thUf7M1CpyUf7Ug:bI1<WYNC3N@4:3EKVT/UIUW2ix/Z8yNlJuw.i8QRrBw0>ybeAy9Mz70W7Cv/Z8yQMA2eL2pF11lBmZ?,5d8w@MMi8RQ90jEaq3/Qy9MQy3e.fx9<2br2g4w_Q13UWY<i8RY90zERpX/Un03Uyd<yTMA3370Kw0>02@1Mg.ew8Ef/w_Q23Uin<i8RI912bj2g8Ly;NM4yd5t9g.18yu_E89X/QybuMx8yuXEFa7/UJc90N8yuYNM4yd5qVg.2@8<ezWDv/i8JX44y9Xz7JW7Ox/Z8yt_ER9T/Qy3N329W5JtglX3pwYvx}WbKs/@beewAEf/i8QZYB40>y9Nz70Wdes/@Z?,eL03NZ0>ybgMx8yst9ysrEqpP/Qy9Nky5M7hVZA0E17hHyQMA2bUw<i8RY910NM4yd5hVg.3ErVT/Qy9XP79i8Rk910NZKz@Df/yQMA3bUw<cs18zhnSjM.i8RY913EgFT/Qy9XP79i8Rk912@?,37JWcOs/_Fe//MYvw;1cyvvE@9T/QO9Z@wMDv/i8D5i8n03UlV//yTMA2exrDv/yTMA3exiDv/WjH/_ZCA{}glt1lA5lglhlLg4,1ji8fIa4ydt2gkW6eu/Z8ysd8wPw0t114ySMA5463_gh_7XQ1<i8DvW9as/Z8wYgEyuxrnk5sglR1nA5vMV18yTw8KwE<NZKyMDv/i8JX4bEa<cvp9ysjEDpT/QybuNx8NQgA6;11ysq0fM0fxsg,15cvZ8yTIwKwE<NZKxhDf/i8D5gofZ1g@4v<4ybuOx8zjlKk,Weis/@W,g0bU71,h8DTxs0fBc0fJI29h2g8cs3EN9T/Qy5XngNhoDBhj7AioDEcsB1Kgk,14yv9dau1cyvV4yu_E7pL/Qy5M7xMt0x90sh9euNORoJ490y5M0@5Iw,37JWh7/_Yf7M2W,g0bU71,h8DTcs3Ep9T/Yt490w;i8nJtpwNXuDC_L/cvqW2w,eykC/_i8fU_M@49L/_Qy9h2goj8RY91zF6L/_MYv0exjCL/yPy3_MJQyof_10@4wf/_UJk90y5QDkzWaqt/Z8zjSajM.Lg4,18ysoNMexgCL/Wo7@/Yf7M14yvt8ykgA2exXC/_i8Jk90ybeKL7pF14yvsNXuxCC/_Wlv@/@glrQ1<kQy3X1x8zngA3eybDf/i8D3i8cU.@4GM,4ybfg@1.18xvZQ5rU>a.W4ys/Z8NMnRw[8IZBTw.8n_3UAL?.yPS5u,xvYfyg41.2bfndU.25_M@9QM,8IZonw.8n_3UCB<yPRfu,xvZVuUIZnnw.8n_ul58zjQnjg.cuTEgVL/Qydfhxd.3EdVL/QydfhFd.3EaVL/Qydfihd.3E7VL/QydfiRd.3E4VL/Qy9T@wrCL/i8f468DEmRT3pF3EuVH/UIZ0nw.exMCL/NMnKtM.//_@Kj3NZ.exrCL/yPTttM.NMmXtM.//_Un_3UxO//WY6gW3Kq/@bfqlT.371pZT.3//_xvYfy4z//HMp3E6VH/UIZyns.cs5wTs.f//@5_M@87L/_@L1AezXCv/yPRJtM.NMlDtM.//_Un_3UzM_L/WY6gWdKp/@bfl5T.371kJT.3//_xvYfycb@/_HMp1li8DBglt1lA5lglhjKM4,18w@j0i87IM<4ydt2hkWdCq/Z8ykgAc4y3e.fx1U6.2bn2hkw_I1vB59ysvEKpL/QCbjMx8yM183XUhi8Bc92zSh50120@5HgM.ct492j//_w_I2t3l8yQgAcbEa<cvp8yTwgW0Oq/@9h2gAWNFC3NZ4.18zgkCjg.NQgA9f//Z8ykgAa37rj8QZCTo0>OdH2i;pCoK3N@4:11yP@5_Twpi8RQ962W4<ewqCv/i8fU40@4Y0k0>yb1r5@.18yXw.g.i8IlETU0>ybcAwV_w@3HMk0>Obwww1.1dxs0fy8s6.18zko1i3D73Udq1w.i2DTioDYi8DXY4wfMhF8yMRBvw.i8K10>0>Wdd2dcev0fwWU5.18yNlavw.3Xpiaoji3Uj61w.i2Doi8n03UUW1g.i8IdaTU0>C9N82VoM4<fxbob.18zogAw<4y9h2h0iEQk8QS9VkyU////_T@1UL/3M18yXjh010w>y9SE7y/Yf>wxNAwzxd4>2.i2D6Y4M1oh18xvofx2Yb.19KcTcPcPcPcPci8Rc9618ysYf7Qg.{}i8DMi8f70kDTU4y9Y4z1WwdczgOijg79j2D8wY0Mi8f@2ky9REx7_Tvmi3DV3Ueh2M.i8D@i8DUi2Dei8Rm_Qy3@zUfxGwb.19yv19yvB8yRgAg6bN_kxL9q5h.1yYvR8rNTnkg.iofwM6bN_kxL5gBi.1das5C3NZ4.1yYJR8zk3_i8fEg4y3MA1yYDR80cJyYDR80c9yYvl8WY1yYvR8vQb_ijD1ttd9ev0fx7Y,18yvx4ys9cas19yv5das5dzl7_iofW7DoPj2D7oL5_a6Z7_Yjzvkr.sjyvg05S54.cixvn@418<11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug:{}3XpU_Qy3W058wY81g8xW_QwVMnbHi6fSi0dQ9435@7v61w18yTgAg4ybv2gEWaWp/Z8xtIfx9E9.18zkMAo4y9TACUPsPcPcPcPcN8ysYf7Qg.{}i8DMi8f70kDTU4y9Y4z1WwdczgOijg79j2D8wY0Mi8f@2ky9REx7_Tvmi3DV3Uc72w.i8D@i8DUi2Dei8Rm_Qy3@zUfxxUa.19yv19yvB8yRgAg6bN_kxL9i5g.1yYvR8rNRnk,iofwM6bN_kxL5oBg.1das5C3NZ4.1yYJR8zk3_i8fEg4y3MA1yYDR80cJyYDR80c9yYvl8WY1yYvR8vQb_j3D8ttdcesofx7Y,18yvx4ys9cas19yv5das5dzl7_iofW7DoPj2D7oL5_a6Z7_Yjzvkr.sjyvg05m5,cixvn@418<11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug:{}3XpU_Qy3W058wY81g8xW_QwVMnbHi6fSi0dQ9435@7v61w18yTgAg4ydfl98,NQKyGBv/i8Rc9618LYTcPcPcPcPci8DejonJ3UjO1M.3NZ.{}j8DEi8f60kzTVQO9W4z1Wwdczgiijg70j2D0wY0MiofZ2kC9Rox6_Tvmi3DN3UdZ2,i8DTi8DMi2Dfi8Rn_Qy3@zUfxH88.19yvB9yv18yRgAg6bN_kxL9q5e.1yYvR8rNTnjw.iofxM6bN_kxL5gBf.1dasxC3NZ4.1yYJR8zk3_i8fEg4y3MA1yYDR80cJyYDR80c9yYvl8WY1yYvR8vQb_ijD0ttdcesYfx7Y,18yv14ysFcasx9yvxdasxdzl3_iofW7DoPj2DeoL5_a6Z6_Yjzvkr.sjyvg05S4U.cixvn@438<11ZI0vt3R9w@3wh072j2D0i6fii0dk941CpyUf7Ug:{}3XpM_Qy3W058wY81g8xO_QwVMnbHi6f_i0dY9435@7v61M18yTgAg4ydfu56,NQKwGBf/yTMA98n_3UBK1g.ctJ8yTMAcezOAL/i8RBS8DomQ5sglR1nA5vnsegi2DpK;19ysNc3Qzwi8QZECQ.ey5A/_wbwk:@5q?0>S5V7lo3NY0ctLF6vH/Sof7Ug}@SgyC4M0@5V0k.8fXp0@4GM8.fegwYc1Wv7V/@gi8IdMnw0>ybn2hwj8JA96x8yU4.g.jEQQ8QMVY0@2kLH/Qydx2i;i8IdB7w0>y9h2h0wbBz?<@5tfH/QC3_>fx3I6.1dyuldxugfxcI5.1azjgHi8Dohj7A3NZ.{}pCoK3N@4:18ys98wY01wub/MY03Xukkg?.190th8ev1RUQO9VKBb@L/3NY0KM4,3Mi0_16Ayb3gZU.11L>,3FD_D/MYvg018yR8Mj8D0ifvoi8fG0kyb3uJT.18ev8fw@E2.18yo48?.grM1<i8IdPDs0>Gd12p8estP1AwFZQC9_4O9U_183Y4pi8IdI7s0>ybwh01.18etwfwPLV/Zcys9cys18ZZHMi0@NAgw1.18yMS7tM.WhTV/ZCbwYvx}i8I5sns.f23g1w1i8QZZmI.ezoAv/NE0k;p18yMlhtM.i8K80>0>wVOTdki8D8i2Doi8B493xceu0fwNz@/Zcyv11yTY4Kx<1cyuV8asx8yoMAw<4y9x2i8<i8Bc94xcymMAgex8Af/i8Jc94x8w_wg3Ui90w.i8I5WDo,@Sg2C4M0@5JLT/UI5w6U.37_KL//Z1K>,11Kg4,2@0w,4z7x2i6=8C498<2b1kJK.1CyrMAzw,4O9XSp4yogAx<8C498w,1Ch8Cc98M,3ERF7/Sq3L2i6;7krpEeY98U;3Ugc//WkrZ/Yf7U:yPTWrg.i8RQ962W2<eyrAf/pEeY98U;3Ujs_L/WhrZ/Yf7U:i8I58no.f23g1w1KM4,11L>,11Lw4,18zjSkqw.W7ug/_5@u_0hj7rpECs98g,1yYnY8vUgAxw,6p4ypMABw,6p4yqgAz<6p4yrgAB<cq05;6b1mlJ.29x2i;yMlkrg.yogAy<46b1UC499<3HeMYvh,KL//@@0M,4O9X@zuAf/ZEgABw<5RdSq3L2i6:@5tg4.6q3L2ie;7kti8I5mTk0>ybw.1.18yNldtg.i8Iii3D2sWR8zjTeqg.Wb6f/@0K1g;3UgQ_f/i8I59nk0>y5M7gbyR0oxt8fxgA2.18zjSuqg.W86f/YNSYq05;3F8_r/MYv>y9YE7y/Yf>gfJVhh01,bE1<j8J926p5xt9c3Qjict99Z_aWg<4wVQ4wfhY9dxsCW?,4MfhcFcesxc3Qr8K>,1dysNdxsBc3QjwWs_Y/Yf7Qg0>yb3p5Q.18xsBQ1UJ168n0tnF8zjQeqg.Wf6e/_6w1g;WmTX/Yf7Qg.8IZ2CM0>ydt2hwKww,18NQgAo>,3EAET/Qy3@fYfxek,18zjT9q,WaOe/Z8yMQJt,wbwk:@4KM,4y5Og@4GM,4Obp2gUyQ4oxs1QxL23qhw1WnP/_ZC3N@4:2bfpFH.18zngAmbE8<W3Ke/_FCvX/Sof7Qg0>yb1t5P.21U/_3M0NQAy@////_TZ88Xjo010w0eyGz/_i8fU_M@5oLH/UI5GDc.8n03Uhk@L/W4Sc/YNSUIUWbif/Z8yNnZq,i8QR9As0>ybeAy9Mz70W0Ce/_FafH/Yq05;1cySgAeeDc@L/h8Iln7c0>m5Qw@42//@z@y/_yPzEpU/_QOd1ml1.2VHgg0>yd5it,19ys58yMmqq,i8QRyQk.]0WaCd/_FPfX/_23q1w1WuTZ/ZCbwYvx}i8I5Yn8.f18wSw80rI2<3Uis@v/i8JY92x8zjn_g,KM4,3E8F3/@C1@v/Kz<1CypgAw<eBe@v/Kj<1CyoMAw<eCYZ/_Y4y3gh.Lz<1CyrgAw<eAAZL/KwE<NZAy9P@xOzv/ykgA94yd1ph,18ykgAaeBNY/_i8fU0nglioD5i8S498<18ykgAgeDu@v/i8S498<18ykgAg4ybIgw1.18ytEfJE5z?.wub/MY0i8nSvAt8wXPh010w.1Uf8j03UlZ<Y4w1sh11Lg4,3Fdfj/Sof7Qg0>ybv2h0WorU/Z8yTgAgeDYZL/i8JQ943FsLn/M@TJ54>,xc1Rb4C9Z46Z?,eDEY/_hj70ctbFjvr/QkNM37iWsfQ/Z5csANQKCVZ/_grQ1<grM1<WrDP/_Mi8d1407Fvv/_MYv0{}lrQ1<kQy3X1x8zngA3ezbzf/i8D3i8cU07h7i8QZUSk.ez6y/_wbwk;7gMi8I5fD40>y5M7ghyR0oxt9Q2L23q1w13NZ4.18zjSNpg.W9ib/_6w1g;cuR8yt_EMUH/Qy3N1y9W5JtMSoK3N@4:1jKM4,18w@Mwi8RQ91PEj8P/Qy9MAy3e01Q1UdY91M2t1h8ytvEx8H/Qy3N229S5L33NZ0>ybm0x8zjnYfw.i8B490x8yt_Ec8L/Qybl2g8xs0fx8I,18zjnvfw.i8Dvi8Bk90zE3UL/Qybl2g8xs1Rlky9l2g8i8ItsD,4ydfvJA.3ETEH/Qybl2g8wbwk;7gFi8nrt0ubgNy5M7ldi8Bk90x8zjTgp,Wbea/Z8yRgA2cq05;3Mi8dH2>NSQy9R@znyv/i8f488DomYcf7U:i8I52n,f18wQ080j7rWZzMwSIo0kyb7vdL.3HFmof7Ug:45nglplkQy3X4x8zngA7ewYy/_i8D3i8cU07gdi6dI91OdhvS3@09S7HQ1<i8DvW6C9/Z8wYh8yuxrnk5ugl_33NZ0>ybuMyW2w,37SW8ya/Z8yTIgKwE<NZA69NKxlyv/ioD7w_Q33Uip<i8JX64yddrkZ.18ynMA2ezAyv/cta5M7gui8JY90x8zjmyfg.WcS9/@W0w,8n03Umo<j8D@h8DTW2mb/Z8w_z_3UhB//i8RIW_x8yRk0w3E0t5tczkgA84y9MrUw<cs1cyst8zhltfg.j8B490zEKEz/Qybvg18yTgA237JW3Gc/_F9f/_MYvh,Kw4,18ysp4yvvEM8H/Qy3@fYfx03/_Z8ysp8zjQqfg.cs0NXuxjyf/WuT@/ZC3NZ4.2W?,eBu//3NY0pCoK3N@4:11lBlji8fI44ydt2gcWdW9/Z8ysd8wPw0t0u3v2gc0DYuLg4,18yt_E4oz/Qy3N129W5JtglX3pwYvh,i8JU237SKwE,3Ec8D/QybqN18zjmpf,goD6i8DLWaG8/@5M7hei8QRzzM0>y9X@ynyf/xs1QkQyddooY.18yu_Ex8z/Un0t5x8zjn@eM.i8DLW768/@5M7lth8DTcuTE0Uz/@BR//pwYvh,Lw4,14yvsNXuwpx/_WlL/_Yf7Q.cvp4yvsNXuw4x/_Wkr/_Yf7U:Lw8,14yvsNXuzFxL/WiL/_Yf7Q.i8DKi8QZ33M.370W5@6/_F3f/_SoK3N@4:11lBlji8fI44ydt2gcWbW8/Z8ysl8wPw03Uh10M.wTMA3>fzwo2.18yQ08i8D7ioD6Wcu5/Z8ysd8xs0fxfI2.3Sg2w43UjF0w.csANZAyd5r0X.18yt_ErEr/P79Lw4,18ytZ8zhmxeM.W5y6/YNOrU2<i8Dvi8QlC3I.ex2xL/csC@0M,4y9TQyd5oYX.3Eb8r/P79Lwg,18ytZ8zhm4eM.W1q6/YNOrU5<i8Dvi8QluzI.ew0xL/csC@1w,4y9TQyd5nwX.3EWEn/P79Lws,18ytZ8zhlKeM.Wdi5/YNOrU8<i8Dvi8Qlp3I.ey@xv/csC@2g,4y9TQyd5lsX.3EG8n/P79LwE,18ytZ8zhlceM.W9a5/YNOrUb<i8Dvi8Qlg3I.exYxv/csC@3<4y9TQyd5joX.3EpEn/P79LwQ,18ytZ8zhkCeM.W525/YNOrUe<i8Dvi8Ql7jI.ewWxv/csC@3M,4y9TQyd5hgX.3E98n/P79Lx<18ytZ8zhkfeM.W0W5/YNOrUh<i8Dvi8Ql2PI.ezUxf/csC@4w,4y9TQyd5vYW.3EUEj/P79Lxc,18ytZ8zhnQew.WcO4/YNOrUk<i8Dvi8QlW3E.eySxf/ctJ8yu_E_8j/Qy3N129S5JtglX3A4ydftcV.3El8j/Qydft4V.3Ei8j/Qydft8V.3Ef8j/QydftcV.3Ec8j/Qydft8V.3E98j/Qydft8V.3E68j/QydftEV.3E38j/QydftEV.3E08j/QydftEV.3EZ8f/QydftsV.3EW8f/QydftoV.3ET8f/QydftgV.3EQ8f/QydftgV.3EN8f/QydfsUV.3EK8f/QydfsYV.3EH8f/Qydft0V.3EE8f/QydftkV.3EB8f/QydftIV.3Ey8f/QydftAV.3Ev8f/QydftwV.3Es8f/QydftoV.3Ep8f/@DF_L/3N@:4O9Z@zgxf/j8DTW0y4/Z8ysd8xs0fxvLY/@gpCoK3N@4:2X?,eCO_L/pwYvh,i8fI24ybfoRu.2@?,ewHxL/i8IZ15Y.bU1<W1G6/Z8yPTjnw.Lw4,3E2or/QybfqFu.2@?,ezUxv/i8IZSlU.bU1<Weu5/Z8yPRwnw.Lw4,3EREn/Qybfqtu.2@?,ez5xv/i8IZhBU.bU1<Wbi5/Z8yPSZnw.Lw4,3EEUn/Qybfhhu.2@?,eyixv/i8IZ@RQ.bU1<W865/Z8yPROnw.Lw4,3Es8n/QybfgBu.2@?,exvxv/i8IZY5Q.bU1<W4W5/Z8yPRDnw.Lw4,3Efon/QybfuVt.2@?,ewIxv/i8IZxlQ.bU1<W1K5/Z8yPQknw.Lw4,3E2En/QybfgJu.2@?,ezVxf/i8IZUBQ.bU1<Wey4/Z8yPRNng.Lw4,3ERUj/Qybfo1t.2@?,ez6xf/cs18wYg8MM,fcf7LF8w@M8i8f42cc|||~~~~~~~~~~~~~~~~~~~~~~~)0>g,4o<2<1M,9d14e94Asw0jEDkgc24Q3l6=4w,19<iw,4I,1d<jM,58,1k=5o,1p<mw,5I=n<7x1zT9nXO0y9Qv8xRk@FGsP6Ttfv4gfGYdTHrrQ6YliMmIv88o0aN0upbAfPU7NeRj34KVbuYU_8DimX7RldGEIyKyu8KaqqSuPGt@tPQPqClvClU6rkxtj7qGf!,vM,1$uw,18%zg,18%iM4.18%vM4.18%4<2$Rw,1$5w4.18%kg8.18%sw,18%HM8.18%@g4.18%og4.18%Fw8.18%Jw4.1$n<18%aw8.18%lg,18%5w8.18%ug,1$Hg4.18%xM4.18%V<1$rw4.18%m08.18%oM,1$4>.18%E>.18%1M8.18%2M4.18%gg4.18%ww8.18%kw4.18%5g8.18%Qw4.1$eg4.18$g,2$tM4.14%qM,18%R>.1$fw8.18%Dw,18%pM4.18%p<18%a>.1$Hw,1$Ag8.18%7g8.18%s08.1$1>.18%Fg4.18%8w8.18%q08.18%_<18%ig8.18%tg4.14%C>.18%o>.18%Yg4.18%dw8.18%Uw4.18%b<2$Og4.18%hw,28%U08.1$Mw,1$C08.18%3w8.18%mg4.14%mwg.1406g0wVg}3+Hgc.1406g1wVM}3+igg.1406g1wVg}3+rgg.1406g3wV[3+D0c.1406g2wVM}3+pMc.1406g1wW[3+X08.1406g3wWg}3+ywc.1406g3wVM}3+J08.180101Mw[841[Pgc.1406g3wVw}3+50c.1406g1wWg}3+dMg.1406g2wVg}3+3gg.1406g0wVw}3+egc.1406g3wW[3+.c.1406g2wWg}3+9wg.1406g3wVg}3+PM8.1406g0wWw}3+l0c.1406g2wW[3+uwc.1406g0wW[3+M0c.1406g0wVM}3+Ugc.1406g2wVw}3+Zgc.1406g1wVw}3+9wc.1406g0wWg}3+05ZvpSRLrBZPt65Ot5Zv05Z9l4Rvp6lOpmtFsThBsBhdgSNLrClkom9Ipg1vilhdnT9BpSBPt6lOl4R3r6ZKplhxoCNB05ZvoTxxnSpFrC5IqnFB07dQsCdEsw1Pt79IpmU0u6Rxr6NLoM1JpmRzs7A0sThOoT1V07xCsClB06pFrChvtC5Oqm5yr6k0nRZBsD9KrRZIrSdxt6BLrw1vnSBPrScOcRZPt79QrSM0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0sTBPoSZKpw1Ls6lKdzg0sClxp01zr6ZPpg1vnSBPrScOcRZPt79QrTlIr01DpnhvsThOqmVDnTpxr7lB07dVsSdxr6M0rmJPt6lJs3oQ07lKr6BKqM1Pt79zrn.sThApn9O06pTsCBQpg1Jrm5Mdzg0rmlJsSlQ05ZvpmVSqn9Lrw1Pt79KoSRM05ZvqndLoP8PnTdQsDhLr6M0pnpBrDhCp01Mqn1B06pzrDhIdzg0sSVMsCBKt6o0oCBKp5ZxsD9xulZBr6lJpmVQ07dQsClOsCZO07lKoCBKp5ZSon9Fom9Ipg1MrTdFu5ZJpmRxr6BDrw1IsSlBqPoQ06dIrSdHnStBt7hFrmk0rmlJoSxO07lPr6lBs01Cs79FrDhC071Lr6M0s79BomgSd01ComNIrSdxt6kSd01CsThxt3oQ07dBrChCqmNBdzg0sTBPqmVCrM1Ps6NFoSk0oSZMulZCqmNBnT9xrCtB06RBrn9zq780rm5HplZytmBIt6BKnS5OpTo0nRZQr7dvpSlQnS5Ap780rnlKrm5M05ZvoThVs6lvoBZIrSc0sSxRt6hLtSU0s7lQsM1PpnhRs5ZytmBIt6BKnSpLsCJOtmVvsCBKpM1OqmVDnSBKqnhvsThOtmdQ065Ap5ZytmBIt6BK079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt01OqmVDnSdIomBJnTdQsDlzt01OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZzr6lxrDlMnTtxqnhBsBZPt79RoTg0sCBKpRZFrCtBsThvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt01OqmVDnS5zqRZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZzrT1VnTdQsDlzt01OqmVDnTdFpSVxr5ZPt79RoTg0r7dBpmJvsThOtmdQ079FrCtvqmVApnxBsBZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt01OqmVDnSpxr6NLtRZMq7BPnTdQsDlzt01OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZPpm5InTdQsDlzt01OqmVDnSpzrDhInTdQsDlzt01OqmVDnT1Fs6lvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt01OqmVDnSNFsThvsThOtmdQ06NFoCcKsSYKdw1Ip2RIqmVRu2RUe3oJdzgKsSYKcw17j4B2gRYObzc0hQN9gAdvcyUPcM17j4B2gRYObzs0hQN9gAdvcyUOe017j4B2gRYObz4Q>tcik93nP8Kczs0hQN9gAdvcyUNc017j4B2gRYObz4T>tcik93nP8Kdg17j4B2gRYObzcU>tcik93nP8KcyUR;g02.8.w020>.g03.g.w02.k.w020>.w06.8.w01.8.M01.801M01.8.w02.8.w08.8.w01.8.g02.A.g0a.c.w020>.g02.8.g02.I.w02.8.w02.M.w02.Q.w01.8.w010>02w02.8.g010>.g010>.g010>.g010>.g010>.g010>.g010>.g01;g0108w4,g<8<1dFqgQ,w0Dgg[1.I0vwg.1+IV6m1w.3g2D1,4<1tFqgQ,M0Iwg.1<28Apo6,b0bM4,g<4SBF3g.2w2t1,4<9ihBwo,A0NMg.1<27Apo6,70d84,g<A96m1w.1w3t1,4<9uhBwo,k0W?.1;lqmAd,40fc4,g<K96m1w,M3Z1,4<7kqqgA,8020k[gTg[w=I0s[oTg[w=s0s[wTg[w=8dQ[wUw[w=2rE[EUw[w=6bE}10Uw[w=abE}18Uw[w=gbU}1wUw[w=dbE}1EUw[w=gbE}20Uw[w=mbE}28Uw[w=prE}2wUw[w=uXE}2EUw[w=xHE}30Uw[w=BrE}38Uw[w=EHE}3wUw[w=KHE}3EUw[w=KXA=UM[w=OHE[8UM[w=HHA[wUM[w=RXE[EUM[w=ErA}10UM[w=VbE}18UM[w=XbE}1wUM[w+bI}1EUM[w=3XI}20UM[w=8bI}28UM[w=crI}2wUM[w=hHI}2EUM[w=lrI}30UM[w=srI}38UM[w=uXI}3wUM[w=AHI}3EUM[w=sbU=V=w=ErI[8V=w=mrA[wV=w=HXI[EV=w=hrA}10V=w=LHI}18V=w=PrI}1wV=w=UXI}1EV=w=XXI}20V=w=1rM}28V=w=4rM}2wV=w=bHM}2EV=w=5bA}30V=w=eXM}38V=w=lXM}3wV=w=qrM}3EV=w+7Q}3UV=w=8e8=Vg[w=6bE[wVg[w=_rA[EVg[w=k6s[UVg[w=ge8}10Vg[w=gbU}1wVg[w=YXA}1EVg[w=A6k}1UVg[w=oe8}20Vg[w=gbE}2wVg[w=WbA}2EVg[w=U7I}2UVg[w=we8}30Vg[w=prE}3wVg[w=THA}3EVg[w=Q6g}3UVg[w=Ee8=Vw[w=xHE[wVw[w=PbA[EVw[w=86g[UVw[w=Me8}10Vw[w=EHE}1wVw[w=KXA}1EVw[w=Q6c}1UVw[w=Ue8}20Vw[w=KXA}2wVw[w=HHA}2EVw[w=U6[2UVw[w+ec}30Vw[w=HHA}3wVw[w=ErA}3EVw[w=A6[3UVw[w=8ec=VM[w=ErA[wVM[w=CXA[EVM[w=w7E[UVM[w=gec}10VM[w=XbE}1wVM[w=zXA}1EVM[w=Q5Y}1UVM[w=oec}20VM[w=3XI}2wVM[w=xrA}2EVM[w=w5Y}2UVM[w=wec}30VM[w=crI}3wVM[w=uHA}3EVM[w=c5Y}3UVM[w=Eec=W=w=lrI[wW=w=srA[EW=w=A5I[UW=w=Mec}10W=w=uXI}1wW=w=prA}1EW=w=g5I}1UW=w=Uec}20W=w=sbU}2wW=w=mrA}2EW=w+5I}2UW=w+eg}30W=w=mrA}3wW=w=hrA}3EW=w=Y7w}3UW=w=8eg=Wg[w=hrA[wWg[w=erA[EWg[w=s7A[UWg[w=geg}10Wg[w=PrI}1wWg[w=bHA}1EWg[w=Q6E}1UWg[w=oeg}20Wg[w=XXI}2wWg[w=8rA}2EWg[w=I5E}2UWg[w=weg}30Wg[w=4rM}3wWg[w=5bA}3EWg[w=c6A}3UWg[w=Eeg=Ww[w=5bA[wWw[w=2HA[EWw[w=o5E[UWw[w=Meg}10Ww[w=lXM}3UTw}1^8TM[o,1m)gTM[o,1i)oTM[o<6)wTM[o,1a)ETM[o,1d)MTM[o,1j)UTM[o,1b-10TM[o,16-18TM[o,1f-1gTM[o,1p-1oTM[o,1g-1wTM[o,19-1ETM[o,1r-1MTM[o,1k-1UTM[o<B-20TM[o<C-28TM[o,1n-2gTM[o,1c-2oTM[o,1s-2wTM[o,18-2ETM[o,17-2MTM[o,1l-2UTM[o,1h-30TM[o,1o-38TM[o<@-3gTM[o,1q-3oTM[o,1)3wTM[o,15)0U=s<1)8U=s<2)gU=s<3)oU=s<4)wU=s<5)EU=s<7)MU=s<8)UU=s<9-10U=s<a-18U=s<b-1gU=s<c-1oU=s<d-1wU=s<e-1EU=s<f-1MU=s<g-1UU=s<h-20U=s<i-28U=s<j-2gU=s<k-2oU=s<l-2wU=s<m-2EU=s<n-2MU=s<o-2UU=s<p-30U=s<q-38U=s<r-3gU=s<s-3oU=s<t-3wU=s<u-3EU=s<v-3MU=s<w-3UU=s<x)0Ug[s<y)8Ug[s<z)gUg[s<A)oUg[s<D)wUg[s<E)EUg[s<F)MUg[s<G)UUg[s<H-10Ug[s<I-18Ug[s<J-1gUg[s<K-1oUg[s<L-1wUg[s<M-1EUg[s<N-1MUg[s<O-1UUg[s<P-20Ug[s<Q-28Ug[s<R-2gUg[s<S-2oUg[s<T-2wUg[s<V-2EUg[s<W-2MUg[s<X-2UUg[s<Y-30Ug[s<Z-38Ug[s<_-3gUg[s,1)3oUg[s,11-3wUg[s,12-3EUg[s,13-3MUg[s,14!}pC5Fr6lA87hL86dOpm5Qpi1xsD9xujEw9nc09ncW86VLt21xry1xsD9xug16jR9bkBlenQpfkAd5nQp1j4N2gkdb02ZApnoLsSxJ02ZQrn.hAZiiR9ljBZ4hk9lhM1QsDlB06pLsCJOtmUwmQh5gBl7ni15rC5yr6lA2w1Jrm5Mey0BsM1KlSZOqSlOsQRxu01KlSZOqSlOsM1Kj6BKpnddonw0rA9Vt6lPjm5U>5ihRZdglw0biRTrT9Hpn9PbmRxu3Q0biRTrT9Hpn9Pc3Q0biRTrT9Hpn9Pfg0JbmNFrClPbmRxu3Q0biRIqmVBsP0Z02QJr6BKpncZ02QJoDBQpncJrm5Ufg0Jbm9Vt6lPc3Q0biRyunhBsPQ0biRIqmRFt3Q0biRQqmRBrTlQfg0JbmtOpmlAug0Jbn9Bt7lOryRyunhBsM0JbmZRt3Q0biRQqmRBrTlQ02lA>lmhAhvkABehRZ4glh1>lmhAhvkABehRZ5jQo0hlp6h5ZiikV7nQBehQljl5Z4glh1>lmhAhvkABehRZ9jAt5kRhvhkZ6>lmhAhvkABehRZjl45ilAk0pCZOqT9RrBZLtng09mNR2w1TsCBQpixCp5ZPs65TryMwsS9RpyMwsSNBryA0pCZOqT9RrBZOqmVDbCc0tT9Ft6kEpnpCp5ZAonhxb2pSb3wF07wa07tOqnhBa6pAnTdMontKb20yu5NK8yMwcyA0tT9Ft6kEpnpCp5ZBrSoI82pBrSpvsSBDb20Uag1AsDA09ncK9mNR0599jAtvikV7hldknQh9lABjjR80kABehRZ2glh3i5Z9h5w0kABehRZ2glh3i5Zjj4ZkkM16h5ZfkAh5kBZgil1507tOqnhBa6pAb20CtC5Ib20Uag1TsCBQpixCp5ZIrSdxr5ZPqmsI82pLrCkI83wF06pLsCJOtmVvqmVMtng0rmlJpChvoT9BonhB86pxqmNBp3Ew9nc0s6BMpi1ComBIpmgW82lP06dIrTdB07dMr6Bzpi1ComBIpmgW82lP0595k4Np03.tT9Ft6kEpnpCp5ZAonhxb20CrSVBb20Uag1FrCc0p6lz05d5hkJvkQlk05d5hkJvhkV402lIr6g09mNIp0E0sSxRt6hLtSVvtM1Pq7lQp6ZTrBZO07dEtnhArTtKnT9T07lKqSVLtSUwoSZJrm5Kp3Ew9nc0sCBKpRZFrCBQ079FrCtvp6lPt79Lug1OqmVDnTdzomVKpn80sCBKpRZzr65Frg1OqmVDnTtLsCJBsw1OqmVDnSdIpm5Ktn1vtS5Ft6lO079FrCtvqmVDpndQ079FrCtvpC5Ir6ZT079FrCtvomdH079FrCtvrT9Apn80sCBKpRZzrT1V079FrCtvsSBDrC5I06NPpmlH079FrCtvqmVApnxBsw1OqmVDnSpBt6dEpn80sCBKpRZComNIrTtvs6xVsM1OqmVDnSRBrmpAnSdOpm5Qpg1OqmVDnTdBomM0sCBKpRZCoSVQr01OqmVDnT1Fs6k0sCBKpRZPs6NFoSk0j6BPt21IrS5Aom9Ipnc0sCBKpRZIqndQ85Jmgl9t05dMr6Bzpi1Aonhx>dOpm5Qpi1Mqn1B079FrCtvs6BMpi0Ygl9iv594fy1rlR9t>pFr6kwoSZKt79Lr01OqmVDnSpzrDhI83N6h3Uwf6dJp3U0kSlxr21JpmRCp01OqmVDnTdBomMwf4p4fw13sClxt6kwrmlJpCg0sCBKpRZJpmRCp5ZzsClxt6kwf5p1kzU0k6xVsSBzomMwpC5Ir6ZT>Vljk4whClQoSxBsw1elkR184BKp6lUpn80kSlBqO1Cp01IsSlBqO0YhAg@83NfhAo@byUK05dFpSVxr21BtClKt6pA079FrCtvsSBDrC5I83N6h3U0mClOrORzrT1V86BKpSlPt01OqmVDnSdLs7Awf4Zll3Uwf4Befw1ipmZOp6lO86ZRt71Rt01OqmVDnSZOp6lO83N6h3Uwf516m7NJpmRCp3U?mdH869xt6dE079FrCtvomdH83N6h3Uwf4p4nQZll3U0j6ZDqmdxr21ComNIrTs0kSBDrC5I86BKpSlPt013r6lxrDlM87txqnhBsw1nrT9Hpn8woSZKt79Lr01OqmVDnTtLsCJBsy1rqmVzv6hBoRQ?SNxqmQwoC5QoSw0sCBKpRZzr65Fri1rlA5ini1rhAht059Rry1PoS5KrClO079FrCtvsSdxrCVBsy0YpCg@85JPs65TrBZCp5Q0h6lPt79Lui1OqmVD>BKqnhFomNFuCkwsCBKpO1TqnhE86dLrCpFpM1OqmVDnSBKqngwmQpcgktjng1OqmVDnSNFsTg}1FrDpxr6BA86VRrmlOqmcwqmVApnwwpCZO86BKp6lUpmgwon9OonAW82lP}LsTBPbShBtCBzpncLsTBPt6lJbSdMtiZzs7kMbSdxoSxBbSBKp6lUcOZPqnFB.1CrT9HsDlK85J4hk9lhRQw9ncW9mgW82lP86pxqmNBp3Ew9nca<tT9Ft6kEpnpCp5ZFrCtBsThvp65QoiMw9DoI83wF.1TsCBQpixCp5ZComNIrTsI82pFs2MwsSBWpmZCa6BMaiA=pCZOqT9Rry1rh4l2lktt879FrCtvomdH86NPpmlH86pxqmNBp3Ew9nca[tT9Ft6kEpChvs6BMpiMw9CZMb21PqnFBrSoErT0Fag1TsCBQpixCp5ZQon9DpngI82pFs2MwsSBWpmZCa6BMaiA=tT9Ft6kEpChvpSNLoC5InS5zqOMw9D1Mb21PqnFBrSoEs70Fag,6pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME,1CrT9HsDlK85J4hk9lhRQwsCBKpRZzr65Fri1IsSlBqO1ComBIpmgW82lP2w<1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ}1OqmVDnSpxr6NLtO0Yk4BghjUwf4p9j4k@85JAsDBt02ZApnoLsSxJbSpLsCJOtmULt6RMbSpLsCJOtmUKm5xo?*1Y07w0t01M06M0q01A06.n01o05g0k01c>w0h01.3M0e.Q03.b.E02g08.s01w05.g.M020><1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3wYe3gMb2wA81Mo510c2?0f3wQc2ME920s61gg30w401<2;5<hQVl0>.s><eg=2.701;Q+hI3eOg1,z<84f/Q01.3Mh/_q>.31a/_w?.84L/MM2.1wjf/c08.f1o/@.w.s87/@w2.10wL/d0c.724/@40M0>8r/Z03.1wzv/.g.b2o/ZE1,A9H/Xw4.3wCL/S?.32r/_U1,s9L/Nw5.30C/_e0k.62v/@01g.I9/_W05<Ef/M0k.c2w/_I1g0>a7/MM6<Ff/m0o.52A/ZU1w,an/WM6.30Fv/Q0o.82D/Y41M.oaD/R07<G/_v0s.22V/@I1M.EbD/Zg7.2MKL/.w.12Y/YY2,cbT/T08.2wMf/F0w[k+5Wkw01u1016MM72901,A<7<dx1/Y01;UghwUoiwYbtMy.3YqeOEP928;t<4g,20hL/dg8,1b3x2e0A8e68Q3gwUwz0h93yy61k4ec8c6hMVgo0Eec4D33yx1NwUwgIMe64bd3x12PwU8i0I3s>a3z14MMUEgsoe84bc3xx2PgUggIUe24Qbs0U8MYrcPsV83B231Eo5z0id0UU2a<bM,18if/Xw<113x230AAek4Ua3x113wx72M9i2wUghgU8igIw<W;N9/YP?,44e48c2jwVw0Bka3x133wx92M1c<3>.2xa/@53<48e48Y2gwUozwd23y2d14kea8M5ggUMxwp13zy31Qsew0A3Tg4a3zx13z113yx23y123xx23x123wx52M,6g,1s?.q5r/T4E<iMUgzM973xye0Q8e88Q4gwUEz0l13z261Agee8c7igWw0MdI3gU8MYrcPsXfk0Ww0Uc7xwqc1oQ4zwef0wbJ2wUUgMUMggUEgwUwgwUogwUggwU8ggI0i<cg1.20vL/O;123x2f0A8e68U3hgUwzgh23yyc1k4ec8o6ggUUwMt43B02DgEee4gec44ea48e848e648e448e24kb>M<g0w.17/_OE2<kwUgzM973xye0Q8e88Q4gwUEz0l13z261Acee8c7iwXM20dJ?Eee4cec44ea48e848e648e448e24gb<i<602.3Awf/B>,1i3x2f0Ase68U3hgUwzgh23yyc1k4ec8o6ggUUwMta3K080RI13zx33z113yx23y123xx23x123ww.2M,2I0w.e8b/Qs7<j0Ugxw983gp9zMee18Q5z0q31Mc_0MEc1Mx12M,6g,3s0w.m8D/QUb<iMUgzM973xye0Q8e88Q4hgUEz0l13z261Agee8c7igXw0MfZ?Eee44ec44ea48e848e648e448e248b0H0e2cf6PcTePR0eU0e31Uo6z0md18U3zM80j<4g3.10Bf/RM4,1i3x2f0Ase68U3gwUwzgh23yyc1k4ec8o6ggUUwMta3F2210cK?Eee44ec44ea48e848e648e448e24sb,s<B0c.d2l/Z5;44e48c2igUMtMUggMU801M,2Q0M,9r/Qk;ggUgwM993z1T3x133ww07<dg3,MBL/fM<113x230AAe874e44ce2.s<Z0c.52m/Z5;44e48c2igUMtMUggMU8>g<k1,w9r/VA3<gwUgzM923xye0Q8e88M4ggUExwl63z231AseY>3Hg4a3z133yx13y123xx23x123wx12M,1M,1s1,S9D/Qk;ggUgwM993z1T3x133ww07<7M4,8CL/hg<113x230AAec7se44ce2.E<D?.3yq/_:44e48o2hwUowMd43z02j0Ee64ce444e24kb01M,381,P9H/Qk;ggUgwM993z1T3x133ww0i<ew4.3YCL/W08,123x2f0A8e68U3gwUwzgh23yyc1k4ec8o6ggUUwMt93F01q0Eee4cec44ea48e848e648e448e24Ab01M<Q1g.E9T/Qk;ggUgwM993z1T3x133ww0c<5g5.3gDv/F;123x2e0A4e68o3hwUwwMh43B02p0Ee84ce644e448e24Ab02<281g.j9X/XU;ggUgwM943z02mwEe44ce24ob03<2I1g.W9X/Xc1<gwUgzw913xy60Qoe88c4h0Vg0Hca3y133xx13x123wxa2M18<U0k.7iw/_v?,48e48Y2gwUozwd23y2d148ea8M5ggUMxwp63zy31Qgeo6Ya3zx33z113yx23y123xx23x123wx22M.a<2M6,8EL/DM4,113x260Aoe68c3h0UM0IUa3xx33x113wx32M0I<m0o.7Oz/Yi3w,44e48o2gMQ6ioY3zwid1oM6wMs3ogoa30s8gwI<A<y0o.6ON/ZS;44e48o2hwUowMd43z02pwUogMUgggU8a<b06.34Iv/1M4,113x230AAec6oa3x133wx52MaB2wUggMU8i0IU<T0o.ayO/Zi?,48e48Y2gwUozwd13y26144ea8c5h0VMsgEea4ce844e648e448e24kb,M<60s.cOP/Ym?,48e48U2ggUoxwd13y2314gec6Ia3y133xx13x123wx72M.c<4M7.2UJf/qwc,123x2e0A4e68o3ggUwwMh43z03808a3y133xx13x123wx22Nw,201M.Zbv/U41<h0Ug0TM13ww|~~~~~~=//_M<2M1M}707[8dQ[1=7U4=g[281=M=P08[d=fi1[6g=gTg}1I=2+q=1zt[7+8=fn@_SY:9=5=7yp[1w[30A=E=50k[b=1w+M[3ETM[8=W0k[k+s=5M[28HM[s=aa=8=60f[2g=o=fX/SY;i9Y}3/_ZL:8=Yf/rM<2cDw}fD/SY;xM~~~~~~~~~~!:2zt!0o3[5wc[C0M}3o3[hwc}1m0M}6o3[twc}260M}9o3[Fwc}2S0M}co3[Rwc}3C0M}fo3[1wg[m1[2o4[dwg}161[5o4[pwg}1S1[8o4[Bwg}2C1[bo4[Nwg}3m1[eo4[Zwg[61g}1o5[9wk[S1g}4o5[lwk}1C1g}7o5[xwk}2m1g}ao5[Jwk}361g}do5[Vwk}3S1g[o6[5wo[C1w}3o6[hwo}1m1w}6o6[two}261w}9o6[Fwo}2S1w}co6[Rwo}3C1w(/////////////Y;/////Y9Kw}1yW!2yW[gbU!dbE}10Kw#1oKw}6mW!7KW[xHE!BrE}2yKw#2WKw}bKV!cGW[HHA!RXE}2xKg#3AKw}eOW!02X[3XI!8bI[NKM#16KM}5mX!76X[uXI!AHI}1MLw#2xKM}5CV!a@X[hrA!LHI}3dKM#3zKM}e@X!0mY[4rM!bHM[kKg!XL[5uY!6CY=7Q[1=23y[6bE`3ZKg}51D=g[10Uw}42@~YXA}2gpg[4=oe8}10Kw`eyV[U7I[1=83y[prE`3uKg}d1A=g[2wUw}8qW~PbA[wp=4=Me8}2yKw`bKV[Q6c[1=e3y[KXA`2KKg}e1w=g+UM}aWV~ErA}2go=4=8ec}2xKg`9KV[w7E[1=43z[XbE`2fKg}d1v=g[1wUM[@X~xrA}20nM[4=wec[NKM`7GV[c5Y[1=a3z[lrI`1NKg}91r=g[30UM}7KX~prA}10mM[4=Uec}1MLw`5CV=5I[1+3A[mrA`15Kg}f1U=g=wV[4mV~erA}1Mug[4=geg}3dKM`2WV[Q6E[1=63A[XXI~xKg}b1q=g[20V[16Y~5bA[Mqg[4=Eeg[kKg~GV[o5E[1=c3A[lXM(4t3gPEwa4teliAwcjkKcyUN838MczkNcz4N82xipmgwi65Q834Rbz8KciQRag<w<g:40>t19>Poj40P08[1ww=KsSxPt79Qom80bCVLt6kKpSVRbC9RqmNAbmBA02VFrCBQ02VQpnxQ02VCqmVF02VDrDkKq65Pq.Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bD9Lp65Qog0KrCZQpiVDrDkKs79Ls6lOt7A0bClEnSpOomRBnSxAsw0KpmxvpD9xrmk0bDhAonhx02VQoDdP02VFrCBQnS5OsC5V02VCqmVFnS5OsC5V02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpSZQ02VDrTgKs6NQ02VAonhx02VysTc0bCdLrmRBrDg0bCtKtiVytmBIp2Vxt7hOqm9Rt6lP~~+.2M<s<2=aw2[G08[A&1&1U<1<1w[3c0w}cM2[6M&g*1R;g<o=Y08}3M0w=4*g=1+9;4<6+07+s}3Nuw(g&2E<1<1w[3Qwg}fi1[3g&g&M<ZL/rM8+9+A[c+1M=8&ew<I<2=c2g[M9[2U2=w<1<2+o=48<3;w[1UCg}7yp[50k*4*1a<//rM8=z9U}2cDw}bE=1M=2+8=lM,fX/SY2=4yv[i9Y}3w+w<2<2&6o<4;w=EE[2yw[o0Y[7+w=6=1M<1<48=yaY}28HM}ew5[1M,1w<8=1w=uw<4<2=82R[wbk[w2w(g&88<7;w[2wLM}a2_[c^w*2l;g<8=QbY}3gLM}2g1*4&EM<4<2=fz=@c[2s1M(2&aQ<1;Mg[8Tg[zd[1^w*2Q<2;c4[4dQ[gPg[Q&8&Kw<U<3=13t[4cQ[8&2+8=co<f;M=oTg}1zd[2^w=2=3i;g<c=8dQ[wPg[w&8&TM<o<3=2zt[acQ}3g?[w=2+g=ew<1;M[3UTw}fze[Y^w=2=3J;g<c=WdY}3EPM}102*8+w=Zw<4<3+3y=d8}1g2*8&fM<8;M[1gWw}53q[a^w&1?,g,3&1gSw}2U&1+4=2w4,s-7wa?:wdE[A&1^4<3%ajq[8>*4*')


_forkrun_bootstrap_setup --force

