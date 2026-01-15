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

declare -a b64=([0]=$'108590 54296\nmd5sum:5a344426e2f14e2451bbf0f4b08be325\nsha256sum:27fc2459e01c372943f3b681f81bb533a0249e8d31ef2c73b12968da18b605c7\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n00000000\n0000000\n000000\n00000\n2MiM\n0000\n000\n04\n01\n1M\n0g\n00\n__\n0ioDNjiD1joRh_QC3@xVScQMFNSbNvOxLh/4UTR6M\034vQlchw81.-?c0fw,)1-dza-;4?e?c<?9g0A?o:4:g+1-4-E08{2w0w=w+1}g;3w0w{e02=U08{1k+5g+2-1:1!{80X=w3I+4+4:5:w3I{20iM{81b=UnY{3xvM+g+g:o;1EKM{6zr=qdI{3E0w{9w4+1+1:1w;62@=oeU{1wXw{5wa=v0E+4+s:4:qbI{1ESM{6zr=2-l-w-w:o;1UKM{7zr=udI{3g.{d,=2+1gVnhA1:eML=X2Y{3IbM{>1=7<=4+5fBt6g4:U08{3w0w{e02=c-M-w+kulQp0o~*g=1iVnhA1:6yX=qdI{1ESM{ew2=C.=1-g:w:1g;4telg,?7,:3A-w,M.:d-g:k}M;4telg1pjvUntBB7N3M328g1urQjCLuTDg}3:hg:g:q:2?8hcog20w0ylggy0q0ar408280<0,I4g;w4,5:iw;58:upbAfcxJTjYW1YjIChYy7MmIv89PfjdG0CR8nv4gfGRj34KXQ6YlilKYw8Dx1zT9j7qGfpHeFTQFXPz_2tWSSC5vClUo0aN0yUFFHb8HEDBg@FGsyt9rIvlkSGw!?2}w$2Y:w$4I:w$6k:g$7c:g$7I:g$84:g$8Y:g$ac:g$bs:g$ck:g$dQ:g$eU:g$<1;g$141;g$2c1;g$2Y1;i$3o1;i$3Y1;i$541;i$5o1;h$5U1;i$6o1;i$7g1;i$7A1;i$841;i$8M1;i$9g1;i$9I1;i$a81;i$aA1;i$bc1;i$bE1;i$bY1;i$co1;i$dg1;i$dA1;i$e,;i$f,;i$fw1;i$0A2;i$182;i$1A2;i$2A2;h$302;i$3w2;i$3Y2;i$4s2;i$4Y2;i$5s2;y$6o2;i$6Q2;i$7o2;i$7Q2;i$8c2;i$8E2;i$9o2;i$9Q2;i$ag2;i$aI2;i$bM2;i$c82;i$cE2;i$dA2;i$dU2;i$ek2;i$eQ2;i$fk2;i$.3;h,U0Mfk=M+1o3;h,U?fg=M+2s3;h,U?f8=M+3A3;h,U0Mf4=M+4E3;i,k0UcA{21.{6k3;h,U0wfc=M+783;h,U0Mf8=M+8E3;h,U0Mfg=M+9Q3;h,U0wf8=M+bo3;h,U.fg=M+cw3;h,U0Mfc=M+dI3;h,U0wf4=M+eU3;h,U0wfk=M-44;h,U0wfg=M+144;h,U.fk=M+2M4;h,U.fo=M+4<;h,U?fc=M+5g4;h,U.fc=M+6w4;h,U?fk=M+7I4;h,U0wfo=M+8M4;h,U.f4=M+9Q4;h,U?fo=M+b44;h,U.f8=M-1Iqm9zbDdLbzo0r6gJr6BKtnwJu3wSbjoQbDdLbz80nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0oCBKp5ZSon9Fom9Ipg1Urm5Ir6Zz07xCsClB06pFrChvtC5Oqm5yr6k0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0pSlQnTdQsCBKpRZSomNRpg1yqmVAnS5OsC5VnSlIpmRBrDg0tmVyqmVAnTpxsCBxoCNB06RxqSlvoDlFr7hFrBZxsCtS065Ap5ZytmBIt6BK07dQsCdMug1PrD1OqmVQpw1vnSBPrScOcRZPt79QrTlIr,MtnhP06lKtCBOrSU0sTBPoSZKpw1zr6ZzqRZDpnhQqmRB06pOpmk0r7dBpmISd,PpmVApCBIpjoQ071Opm5Adzg0rT1BrzoQ07lKr6BKqM1JtmVJon?rmJPt6lJs3oQ06RJon0Sd,MrSNI07dQsCNBrw1vnSdQun1BnS9vr6Zz079Bomg0tndIpmlM05ZvqndLoP8PnTdQsDhLr,PundFrCpL05ZvqndLoP8PnTdQsDhLr6M0sSxRt6hLtSU0rm5Ir6Zz06dLs7BvpCBIplZOomVDpg1Pt6hBsD80pD1OqmVQpw1JpmRzq780pCdKt6MSd,CsThxt3oQ06lSpmVQpCg0nRZzu65vpCBKomNFuCk0sThOoSxO07dQsClOsCZO06RBrndBt,zr6ZPpg>sCBKt6o0pC5Ir6ZzonhBdzg0rmlJoT1V06pTsCBQpg1Pt79zrn?nRZBsD9KrRZIrSdxt6BLrw1TsCBQpg1PundzomNI071LsSBUnSRBrm5IqmtK071Fs6k0sT1IqmdB07dQsCVzrn?rmlJsCdEsw1vnThIsRZDpnhvomhAsw1OqmVDnSdIomBJnTdQsDlzt,OqmVDnSdLs7BvsThOtmdQ079FrCtvpCdKt6NvsThOtmdQ079FrCtvs6BMplZPt79RoTg0sSlQtn1voDlFr7hFrBZCrT9HsDlKnT9FrCs0r7dBpmJvsThOtmdQ079FrCtvpC5Ir6ZTnT1EundvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt,OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZPqmtKomNvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt,OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZxoSJvsThOtmdQ079FrCtvoSNBomVRs5ZTomBQpn9vsThOtmdQ079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt,OqmVDnSBKp6lUpn9vsThOtmdQ079FrCtvqmVDpndQnTdQsDlzt,OqmVDnSBKqnhvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt,OqmVDnTdBomNvsThOtmdQ<tcik93nP8KcM17j4B2gRYObz8Kdg17j4B2gRYObzk0hQN9gAdvcyUT<tcik93nP8Kcj?hQN9gAdvcyUNd,7j4B2gRYObz4T<tcik93nP8Kczs0hQN9gAdvcyUOe,7j4B2gRYObzcP<tcik93nP8KcPw[g,0<0.,0<0.,0<0.,0<0.,0<0.03?c03g03?c?M09?c?M<?c?M03?c?M03?c?M<?c?M0d?c03g03?c02w03?c?M0b?M,w03?c?M03?c?M07?w?M03?c?M03?c?M05?c?M020<0.,0<0.,0<0.,0<0.,0<0.,0<0.,0<0.,0<0.:40.0b:4:2}jqmAd;20c84+g0b0<:g+7kqqgA;c0P.0,}jqmAd;40c84;g:5mBF3g0,g3o1;4:1tFqgQ;o0Uwg0,:2gApo6;70eM4;g:B96m1w?203T1;4:9uhBwo;A?wk0,:27Apo6;a?Q5;g:y96m1w?2M0o1g0<:behBwo;M08Mk0,:2UApo6;d02U5-;73r=2+>SM{4zt=2-Mk=53t=2+>k=83K=2+3Jdg{8zK=2-PcM{a3K=2+2Id=azK=2+2wew{c3K=2-8dw{czK=2-Edw{e3K=2+21dg{ezK=2+2edg=3L=2+>d+zL=2-ke=23L=2+38e=2zL=2+2rcM{43L=2+2Ud=4zL=2+2mcw{63L=2+1qdM{6zL=2+1Sdw{83L=2+3@dM{8zL=2+1Ycw{a3L=2+2Ad=azL=2-8dM{c3L=2+1HdM{czL=2+1oe=e3L=2+2acM{ezL=2-Qdg=3M=2+2_cM=zM=2+1qdw{23M=2+2ge=2zM=2-scM{43M=2+3Vdw{4zM=2+1weM{63M=2+3MdM{6zM=2+3Hcw{83M=2-Oe=8zM=2+3sdM{a3M=2+38dw{azM=2+3xcM{c3M=2+1edw{czM=2+2Oe=e3M=2+23dw{ezM=2+2fdw=3N=2+38cw=zN=2+1wcw{23N=2-Veg{2zN=2+3adg{43N=2+3Ad=4zN=2+>Nw{5zN=2+20Xw{63N=2-PcM{83N=2+2PcM{8zN=2+2gI=9zN=2+2wXw{a3N=2+2wew{c3N=2-jdg{czN=2+3gHw{dzN=2+30Xw{e3N=2-Edw=3O=2+2Zcw=zO=2+1gNg{1zO=2+3wXw{23O=2+2edg{43O=2+3TcM{4zO=2-gHw{5zO=2-0XM{63O=2-ke=83O=2+3Kd=8zO=2+1wHg{9zO=2-wXM{a3O=2+2rcM{c3O=2+2mcw{czO=2-gHg{dzO=2+10XM{e3O=2+2mcw=3P=2+1Sdw=zP=2-wGw{1zP=2+1wXM{23P=2+1Sdw{43P=2+1Ycw{4zP=2+3gGg{5zP=2+20XM{63P=2+1Ycw{83P=2+1Rdg{8zP=2+3MMM{9zP=2+2wXM{a3P=2-8dM{c3P=2-Pd=czP=2-gGg{dzP=2+30XM{e3P=2+1oe+3Q=2+3ecM=zQ=2+30G=1zQ=2+3wXM{23Q=2-Qdg{43Q=2+1Fe=4zQ=2+>G=5zQ=2-0Y=63Q=2+1qdw{83Q=2+27e=8zQ=2+3gF=9zQ=2-wY=a3Q=2-scM{c3Q=2+2wdM{czQ=2+20F=dzQ=2+10Y=e3Q=2+1weM=3R=2+3Hcw=zR=2+10F=1zR=2+1wY=23R=2+3Hcw{43R=2+3sdM{4zR=2-MMw{5zR=2+20Y=63R=2+3sdM{83R=2+3vcw{8zR=2+2MMw{9zR=2+2wY=a3R=2+3xcM{c3R=2+3le=czR=2-gJ=dzR=2+30Y=e3R=2+2Oe+3S=2+2TdM=zS=2+3MEM{1zS=2+3wY=23S=2+2fdw{43S=2+1wcw{4zS=2+>Iw{5zS=2-0Yg{63S=2+1wcw{83S=2-QdM{8zS=2+2wEM{9zS=2-wYg{a3S=2+3adg{63t=4^73t=1w:4)7zt=1w:8)83t=1w:c)3zu=1w;1k)43u=1w;2M)4zu=1w;38)a3t=1w;4k)dzt=1w;4o)1zu=1w;4s)23u=1w;4w)ezt=1w;4E(3u=1w;4I)c3t=1w;4M(zu=1w;4Q)d3t=1w;4U)e3t=1w;4Y)2zu=1w;5(azt=1w;54)czt=1w;58)b3t=1w;5c)93t=1w;5g)fzt=1w;5k)f3t=1w;5o)bzt=1w;5s)8zt=1w;5w)33u=1w;5A)9zt=1w;5E)13u=1w;5I)czS=>:g)d3S=>:k)dzS=>:o)e3S=>:s)ezS=>:w)f3S=>:A)fzS=>:E(3T=>:I(zT=>:M)13T=>:Q)1zT=>:U)23T=>:Y)2zT=>;1(33T=>;14)3zT=>;18)43T=>;1c)4zT=>;1g)53T=>;1o)5zT=>;1s)63T=>;1w)6zT=>;1A)73T=>;1E)7zT=>;1I)83T=>;>)8zT=>;1Q)93T=>;1U)9zT=>;1Y)a3T=>;2(azT=>;24)b3T=>;28)bzT=>;2c)c3T=>;2g)czT=>;2k)d3T=>;2o)dzT=>;2s)e3T=>;2w)ezT=>;2A)f3T=>;2E)fzT=>;2I(3U=>;2Q(zU=>;2U)13U=>;2Y)1zU=>;3(23U=>;34)2zU=>;3c)33U=>;3g)3zU=>;3k)43U=>;3o)4zU=>;3s)53U=>;3w)5zU=>;3A)63U=>;3E)6zU=>;3I)73U=>;3M)7zU=>;3Q)83U=>;3U)8zU=>;3Y)93U=>;4(9zU=>;44)a3U=>;48)azU=>;4c)b3U=>;4g)1g-nFi?5U4<r30s8A<?7g:s:W2s?3k2:iMUgzw923xyd0Q8e88M4igUExwl13z231Asek60a3z19MMUEgsoe84bc3xx2PgUggIUe24wb0T,2wUMhccea4763y12P0UogIQe44be3wxd2T0e2cf6PcTei0VgwMq61oM4zgee0yw;2k:I2A?eU}ggUgwM993B1e2wUgggU8hMI2kwEe44ke24Ab8:c:1Qaw?cM4;113x230AUeo09l2wUggMU8igI0j:eg;2gaM?xgM;123x2f0A8e68U3gwUwzgh53yyc1k4ec8o6ggUUwMt73E090ZQ12wUUggUMggUEgwUwgwUogwUggwU8hgI;1A:d<?d0T?3Va:4Ie48Y2hMUozwd23y2d148ea8M5ggUMxwp43zy31QAeI0c3D0Qe2cf6PcTePR0eI0e31Uo6z0md18U3zM82XwEee4cec44ea48e848e648e448e244b<w;2s.?q6;cw}gwUgzM923xye0Qke88Q4gwUEz0l13z261A4ee8c7h0Vg0FQa3zx43z113yx23y123xx23x123wx52M1c:W<?eNw;G0w;58e48Y2hMUozwd23y2d148ea8M5ggUMxwp33zy31QEeY0w3rg4a3zx33z113yx23y123xx23x123wx42M;4w:U0w?P68?9g1:kwUgzM973xye0Qke88Q4gwUEz0l13z261A4ee8c7iwXw20dr.UUgMUMggUEgwUwgwUogwUggwU8;I:x08?21A0,7>;4Me48o2i0Q6ioY3zwid1oM6wMs3fMca30s8ggI;1A:J080<1H0,e2M;4Ie48Y2hMUozwd23y2d14kea8M5ggUMxwp43zy31QAeU0c3_g4a3zx13z113yx23y123xx23x123wx22MaM3wz3NIPdPIZg3K03wMu61EM5zgie0UY2<M:s0M?a7o?ds1:kwUgzM973xye0Q8e88Q4gwUEz0l13z261A4ee8c7iwWgwwg3bw4a3zx13z113yx23y123xx23x123wx72M?7:6M3?2UtM?hg:113x230AAec7se44ce2?s:z0c?exT0,5}44e48c2igUMtMUggMU8,M;2I0M?67w?3Y}ggUgwM993y1N3x133ww07:cM3;Uu;hg:113x230AAec7se44ce2,4:X0c?6xU?2p0M;48e48Y2gwUozwd23y2c144ea8o5hwUMwMp73L,0WQ12wUMgMUEggUwgwUogwUggwU8ggI:s:d.?c1X0,5}44e48c2igUMtMUggMU8,M;1k1;Y7I0<k}ggUgwM993z1T3x133ww0a:7g4;wv;M}113x260Aoe68c3h0UM0AMa3xx33x113wx52M0s:E.?bhY0,5}44e48c2igUMtMUggMU8<w;3,;V7M?ew2:gwUgzM923xye0Q8e88Q4gwUEz0l13z261A4ee8c7igWg0mwa3zx33z113yx23y123xx23x123wx92M0s:30k?8x_0,5}44e48c2igUMtMUggMU803}I1g?K7Y?ag}gwUgzw913xy60Qoe88c4h0Vg0Cga3y133xx13x123wx92M0w:o0k?3i;2@}44e48c2h0UM0BEa3x133wx62M0M:x0k?d2;2P.;48e48U2ggUoxwd63y2314gek0aP2wUwgMUoggUggwU8iwI0i:bw50,sww?TM4;123x2f0A8e68U3gwUwzgh23yyc1k4ec8o6hwUUwMt43C1L2wUUgMUMggUEgwUwgwUogwUggwU8gwI?2w:41w?Y8c?9Y1:ggUgxw963xy30Qgec0be2wUogMUgggU8gMI0b:3060,Axg0<wU;113x260Acd1ACf0UU4zgmc1Ec70S462wM7248b:9:6060,kAM?tw:113x260Aoe68c3h0UM0Coe64ce444e22w;281w?H9c?3o1:ggUgxw963xy30Qgeg0bi2wUogMUgggU8hMI0e:bg6?30B;kw4;123x2f0A8e68U3ggUwxwh13yy31kges74a3yx33y113xx23x123wx52M?c:f06?3ABg?5w4;123x2e0A4e68o3ggUwwMh43z1H2wUwgMUoggUggwU8hMI?3}A>?Q9o?6E3:gwUgzw913xy60Q4e88c4h0UM0O022wUwgMUoggUggwU8gwIo:m0s;Oq?21.;4ge40dY.U8-4r0PK8@f/8w;9gw?2A@f/R280,PV/_48M?ifD/MgB0,I@v/B34?bPV/@kmw?9fH/Shr0,M@L/B5Q?c3W/YQnM?3fL/UhC;Y@/_R74?ajX/@QsM?ZfL/MhQ;k_f/l7g?3jY/@kt;lfP/@hQ0,Q_f/x7w?bPY/_ku;TfP/OhV?3Y_f/V7A?2zZ/YQuw?ifT/OhZ?2k_v/t7Q?bjZ/YAvw?WfT/@h@;c_L/F8;43@/@4ww?zfX/Oi4?2U_L/h98?ez@/_4Aw0<f/_Mik;Y//p9k?7z/_@4Bw?Hf//ip?3w//~![v,U07g0s,I06w0p,w05M0m,k05?j,8<g.?Y03w0d?M02M0a?A02?7?o,g<?c?w,}vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf/Y0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MU1^bShBtyZPq6QLpCZOqT9RryZQrn0LpCZOqT9RryVom5w%3MUd30Ia2gw71wk40M81?Ye3gMb2wA8>o510c2.1OqmVDnShBsThOrTA0hlp6h5ZiikV7nQh1l440sCBKpRZFrChBu6lO02QJoDBQpncJrm5Ufg1OqmVDnSpxr6NLtRZMq7BP<lmhAhvkABehRZ9jAt5kRhvh45kgg1OqmVDnSpzrDhI<hBsThOrTAwsCBKpM1KgDBQpnddonw0sCBKpRZTrT9Hpn80sCBKpRZFrCtBsTg09ncK9mNR07tOqnhBa6pAnTdMontKb20yu5NK8yMwcyA0p6lz079FrCtvomdH83N6h3Uwf4p4nQZll3U0sCBKpRZIqndQ85Jmgl9t03?tT9Ft6kEpnpCp5ZAonhxb20CrSVBb20Uag0JbntLsCJBsDcJrm5Ufg16jR9bkBlenQpfkAd5nQp1j4N2gkdb02ZQrn?mClOrORzrT1V86BKpSlPt,OqmVDnSRBrmpAnSdOpm5Qpi0YlA5ifw1OqmVDnTdMr6Bzpg1ipmZOp6lO86ZRt71Rt,OqmVDnSdLs7A0biRyunhBsPQ0sCBKpRZTrT9Hpn8wmSBKoTNApmdt079FrCtvsSlxr,U2w0JbnhFrmlLtngZ<p4nQZih4linR19k4k0tT9Ft6kEpnpCp5ZAonhxb2pSb3wF079FrCtvsSBDrC5I07dEtnhArTtKnT9T07dMr6Bzpi1ComBIpmgW82lP02QJoDBQpncMfg0Lp6lSbTdErg1jpm5I86RBrmpA02lPey1KrTgwomUwon9OonA0rmlJpChvoT9BonhB86pxqmNBp3Ew9nc0kSlBqO1Cp,js6NFoSkwp65Qog1gq7BPqmdxr21ComNIrTs0biRIqmVBsORJonwZ02QJr6BKpncZ0595k4Np079FrCtvr6BPt,OqmVDnSRBrmpAnSdOpm5Qpg1TsCBQpixCp2Mw9Dpxr2Mwe2A0sCBKpRZMqn1B071Fs6kwpC5Fr6lAey0BsM0JbmZRt3Q0sCBKpRZzrT1V83Nfllg@83N9jzU0oSNLsSk0kQl5iRZjhlg0tT9Ft6kEpnpCp5ZBrSoI82pBrSpvsSBDb20Uag1IsSlBqM1JpmRCp,6qmNB86dLrDhOrSM0sCBKpRZCoSVQr20YhAg@83Nzrmg@06RJon0W82lP06VnrT9Hpn9P0599jAtvikV7hldknQh9lABjjR80sCBKpRZFrCBQ85J6j457kRQ0kABehRZ2glh3i5Zjj4ZkkM1cqndQ86NLomhxoCNBsM1KlSZOqSlOsQRxu,3sClxt6kws6BMpg1RrCJKrTtK86dLrmRxrCgW82lP079FrCtvs6BMpi0Ygl9iv594fy1rlR9t<pfkAJilkVvh4l2lks.SNxqmQwoC5QoSw0sCBKpRZLsChBsy0YhAg@83NghBxYrmlJpCg@079FrCtvpClQoSxBsw1itmUwsSdxrCVBsw1OqmVDnTdzomVKpn8wf6pAfy1rsT1xtSVvpCht<lmhAhvkABehRZjl45ilAk0sSxRt6hLtSVvsw1nrT9Hpn8woSZKt79Lr?Br7ka02lA<lmhAhvkABehRZ9jAt5kRhvhkZ607hOtmk0j6ZDqmdxr21ComNIrTs0r7dBpmIwf4p4fy0YjQp6fyUKbw0JbmNFrClPc3Q0pCZOqT9RrBZFrD1Rt,OqmVDnSBKqng0tT9Ft6kEpChvsT1xtSUI87dytmoI87dIpmUF<Vljk4whClQoSxBsw1AsDA0kSBDrC5I86lSpmVQpCg0sSxRt6hLtSVvtM1ComBIpmgwt6YwoT9BonhB865OsC5Vey0BsM1OqmVDnSpxr6NLtM0JbntLsCJBsDcZ079FrCtvsSdxrCVBsw1CrT9HsDlKnT9FrCsKoM1jhklbnQleh,OqmVDnSdIpm5Ktn1vtS5Ft6lO05dFpSVxr21FrCtBsTg0jBldgi19rChBu6lO02QJr6BJqngZ079FrCtvsSlxr20YhAg@02QJsClQtn9Kbm9Vt6lP<dIpm5Ktn0wtS5Ft6lO<5ihRZdglw0biRDsClBp7A09mNIp0E0sCBKpRZPqmtKomMwf4p4fw1OqmVDnSZOp6lO<lmhAhvkABehRZ5jQo09mNIp,OqmVDnS5zqM11oSIwoC5QoSw0pCZOqT9RrBZLtng0biRTrT9Hpn9Pc3Q0sCBKpRZzr65Fri1rlA5ini1rhAht<dOpm5Qpi1JpmRCp,OqmVDnSdIomBJ06pLsCJOtmUwmQh5gBl7ni15rC5yr6lA2w1iikV7nQ91l4d8nQB4m,Kj6BKpnddonw0tT9Ft6kEpChvr6ZzomNvsSBDb20CrSVBb20Uag0JbnhFrmlLtng0imVFt6Bxr6BWpi1OqmVD87tFt6wwoSZKpCBD06BKoM-tT9Ft6kEpChvpSNLoC5InS5zqOMw9D>b21PqnFBrSoEs70Fag;7tOqnhBa6pAnT1Fs6kI82pLs2MwsSBWpmZCa6ZMaiA0qmVSomNFp21KtmRBsCBz86BKp6lU86pLsy1FrChBu6lA865OsC5Vey0BsM[pCZOqT9Rry1rh4l2lktt82lPeylAey0BsO1ComBIpmgW82lP2w;6pLsCJOtmUwmQh5gBl7ni1OqmVDnSdIomBJ86NPpmlH86pxqmNBp3Ew9nca}6pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME;1TsCBQpixBtCpAnSBKpSlPt5ZAonhxb20CtyMwe2A?7tOqnhBa6pAnThxsCtBt2Mw9CBMb21PqnFBrSoEqn0Fag=1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ=LsTBPbShBtCBzpncLsTBPt6lJbSdMtiZzs7kMbSdxoSxBbSBKp6lUcOZPqnFB0,TsCBQpixCp5ZComNIrTsI82pFs2MwsSBWpmZCa6BMaiA+pCZOqT9Rry1rh4l2lktt879FrCtvomdH86NPpmlH86pxqmNBp3Ew9nca*1OqmVDnSpxr6NLtO0Yk4BghjUwf4p9j4k@85JAsDBt0fcf7LF8w@M8i8f42cc;3P3NXWi8fI24yb1t6h0,8xs1Q0L_gi8f42cc[fcf7LF1k_YR_aE?fYB_GE?cPcPcPcPcPcPcPcPcPcgrI}_OnIGw?PcPcP46X.;fYBVaE?cPcPcN1KM8;3_9tOG?3cPcPcgrI3:_OnkGw?PcPcP46X1:fYBPaE?cPcPcN1KMk;3_9siG?3cPcPcgrI6:_OmYGw?PcPcP46X>;fYBJaE?cPcPcN1KMw;3_9qOG?3cPcPcgrI9:_OmAGw?PcPcP46X2w;fYBDaE?cPcPcN1KMI;3_9piG?3cPcPcgrIc:_OmcGw?PcPcP46X3g;fYBxaE?cPcPcN1KMU;3_9nOG?3cPcPcgrIf:_OlQGw?PcPcP46X4:fYBraE?cPcPcN1KN4;3_9miG?3cPcPcgrIi:_OlsGw?PcPcP46X4M;fYBlaE?cPcPcN1KNg;3_9kOG?3cPcPcgrIl:_Ol4Gw?PcPcP46X5w;fYBfaE?cPcPcN1KNs;3_9jiG?3cPcPcgrIo:_OkIGw?PcPcP46X6g;fYB9aE?cPcPcN1KNE;3_9hOG?3cPcPcgrIr:_OkkGw?PcPcP46X7:fYB3aE?cPcPcN1KNQ;3_9giG?3cPcPcgrIu:_OnYGg?PcPcP46X7M;fYBZaA?cPcPcN1KO:3_9uOF?3cPcPcgrIx:_OnAGg?PcPcP46X8w;fYBTaA?cPcPcN1KOc;3_9tiF?3cPcPcgrIA:_OncGg?PcPcP46X9g;fYBNaA?cPcPcN1KOo;3_9rOF?3cPcPcgrID:_OmQGg?PcPcP46Xa:fYBHaA?cPcPcN1KOA;3_9qiF?3cPcPcgrIG:_OmsGg?PcPcP46XaM;fYBBaA?cPcPcN1KOM;3_9oOF?3cPcPcgrIJ:_Om4Gg?PcPcP46Xbw;fYBvaA?cPcPcN1KOY;3_9niF?3cPcPcgrIM:_OlIGg?PcPcP46Xcg;fYBpaA?cPcPcN1KP8;3_9lOF?3cPcPcgrIP:_OlkGg?PcPcP46Xd:fYBjaA?cPcPcN1KPk;3_9kiF?3cPcPcgrIS:_OkYGg?PcPcP46XdM;fYBdaA?cPcPcN1KPw;3_9iOF?3cPcPcgrIV:_OkAGg?PcPcP46Xew;fYB7aA?cPcPcN1KPI;3_9hiF?3cPcPcgrIY:_OkcGg?PcPcP46Xfg;fYB1aA?cPcPcP_9pae?3cP-0i8QZYqw0<yd1uGE0,8evxQ5kyb1pWd0,8xs1Q2v_w3N@[ccf7U[i8QZMqw0<yddrGE0,8avV8yv18MuU_ic7U0Qw1NAzh_Dgki8I5poQ0<y5M7g8_@1C3NZ4?333N@[fcf7LG0fnSE:tiJli8cZ0EU;18yulQ34ydfhWb?3Emv/_@xA//NwllG:lT33NY0MMYvw}3P3NXWWnv//cPcPcPcPci8n_3Ug70w0.lp1lk5kioDQLBI;1lkQy9@Qy3X23EW_T/Qy9Nky5M7gfi8DvWeLY/@0v0f_nngsi8f484O9VAy9TP7imRR1n45tglXF@_H/MYv<C9XAy3Ng59atV9znU1WfnW/Z8ytVcyv99ysl8ysvEZfT/Qf6h3k0<y9X@ym_f/i8Rg_Qy9NQy912h8ylgA2ez1@L/i8Jk90x8yuV8yst8ysfELLT/Qyb32hcyu_6h0L_0ext_f/i8RU0uyk@L/j8DKi8D7W4DX/Z8ytZ8ysnEfLP/Qydu07EtvH/Qy9TAy9N@wG@/_j8DDioD6W1_Y/Z8znw1W5rW/Zcyup8ysvE2_L/QO9XQC9Nexg@L/i8DvW4zW/Z8yu_EkfH/Qy5M0@4TM;8Jgafr2g7lvw@843UiK:ict491w}W4zZ/Z8zngA6bEa:j8DTNM[i8D3WeTX/Z8ysp8yQgA64AVNDhww3w0tlK3eO9Qlz79j8Dyi8DLWfDV/_H6MYvw}15cs1cyu5cyv98yuV8ysvEXfD/Qy9X@yQ@v/j8DTWaPV/Z8wYgwj8DDmRR1n45tglXFCfD/MYvx{j8DSi8QZfKv/P70Wb_V/_HMgYvh;i8DKi8QZ@u7/P70WavV/_HGgYvh;MMYvw}18yu_EEfD/Qy9XAydftLA/Z8xs0fxgr//HPSpCbwYvx{kX_2:i8fIgewh@L/i8n0vwN8wYh0mYdC3NZ40,8zjTFV/_cvoNMexg@L/ysu5M7wFKxY;18zngA88B490PEJ_H/UJY90N8yggAWaHX/Z8yNgAi8nivO6_LM;eyT@v/i8n0vBF8wYh0ic7w0RL33N@4[36h1gw<ydt2goKwE;18znMA8exD@v/i8Jk91wfJxa3UJ@0@AJQfQy9Mkz1Uhi0@AR83Qj1i8n0tafFk//MYvw}2_Mw;exe@v/i8n0vVuU0,?eAP//3N@[4z1U0HHOmqgkQy9@Qydfrfv/Z8w@NgW8PU/Z8xs1QlU0Ucnliw7w107lcKE,?2@ww11<ydfobw/YNMexk@v/ysa5M7AuKE,?2@ww11<ydfobv/YNMewS@v/ysa5M7xoi8f4k8DgmYcf7Ug[bE2:i8DuLPY1;NMewc@/_ysa5M7DmWe7W/@3e1pRA37ii8DuLPY1;NMezH@L/ysa5M0@8tv/_@KL3N@[cnVrMmwTv/i8RY9118K2Vom5xom5w0i8BY90x8ykgA8cnVvQgA4ezs@f/i8JY90y5M8D2u1C9l2g8WazU/@bl2g8Wl//Yf7U[NvBL1m3t/_7h2gwm5xo0cnVvQgA4eyt@f/i8JY90y5M8D2us7Fbv/_SqgpCoK3N@4[11lQ5mgll9yvl1l5lji87Ii.?8AY94ydfjbx/_Efvv/Qy5M0@47<?80Ucg@4WM40<yddszx/Z8ysvETfD/Un03UnY:i8I5_ow?bEo:Lw4;18zjScU/_NMlWEM;g;4yb2eyq@v/j8IZoWc0<S5_M@5T:4kNOj7_grz//_Ki4;2W0M;bU<a?WeLT/Z8w_z_3Uip2w?cvqW,2w<y9NQy91i2z?3E@_z/XZk:W27T/Z8zjQSUf/i8D3W8bS/Z8xs1Q6rEa:cvp8ysvE_Lv/Qy9h2g8i8n0vN98xtJ1L<;1c3Q_zj8BA90x8zjSET/_W4rS/Z8xs0fx0Q1;NZHEa:i8D7WbXT/Z8xs0fzLk;18ykgA4eDQ:3NY0j8IZAq8?cs5zW8{1dxvYfx2j/_Z9NMs}i8I5sa80<z7w0,=i8I5nG8?cq06<;18yMlgEw?ict<}18yMl1Ew?ict08}18yMkOEw?NA0E<yb1iuy0,8NQ0M}4yb1hyy?36g2A0i8I53q8?8IZHVs0<z7w0.8{xvZV7z70i874i.?5JtglN1nk5ugl_33NZ?8IZwFs?bE,;i8RQ943EK_r/Qy5M7_CWYMf7Q?w7w1?@48LX/@A6_L/A4z7h2gg.;4ydftzx/_E6_n/Qy5M7gucvqW2w;4y9N@ynZL/i8n0vwF8ykgA6eIc3NY0ict491w<;LXY;3Etvn/Qy5M0@er0w0<Odd419MuU2cv_Envn/Qy9MQy5M0@eQgw0<yb1qa60,8yOx8yTQ0i8n_3UiJ0w?hj7A3N@[ezHZv/i8JZ24y3Ngxdzmg40ky5_TnFLg1w0,ceucfzTI20,8zjTVSL/W6_Q/Z8ysd8xs0fxec7?20e4MfxhE2?20u<O3Ukg0w?w7w2?@51w80<yb7r@w0,8yQgA24y9wOw10,8yQgA44z7wP,;1:i8C38<0<ybh2goj8CPk<0<y9wPw1?2b12h8NUd0.{4z7wRw1=NEdw.;cq3oM4;23@<fzBA80,8NQgA2f//Zdzmk8w@w2ics49f//ZdzmP544O9Vmof7Ug[4ybng2W3w;4yddq_q/Z8yt_EOfr/Un03UiU.?KwI;18zjnqT/_i8DvWaPS/@5M0@4p0k?bEa:i8QRNdX/Qy9T@ygZL/xs0fx7w5?2W3:4yddsjr/Z8yt_Etfr/Un03Uik1g?KwA;18zjnYTv/i8DvW5zS/@5M0@4G0k?bE8:i8QRCtL/Qy9T@wYZL/xs0fx4g6?2W3:4yddj7p/Z8yt_E8fr/Un03Uio1w?KwA;18zjnFSL/i8DvW0jS/@5M0@4l0k?bE8:i8QRidH/Qy9T@zEZv/xs0fx407?2W2:4yddl_u/Z8yt_EPfn/Un03Ug@>?KwE;18zjkYSL/i8DvWb3R/@5M0@4Nwo?bE8:i8QRptX/Qy9T@ykZv/xs0fxiA70,8yMnlDw?icu0m<{3FBg:Yvh;i8QRaJX/Qy9TQC9XKzKZf/xs0fxe3Z/@W2w;37Si8DvWcvP/YNQAy5M4wfit19ytrFMfT/Sof7Qg0<MFUQy9S4z1U0h8atx8Mvw4i8Q4g4z1W098ysnFpfT/MYvw[NZAyduMWW2w;exoY/_i8n0vxd8yNkYDw?i8C2a<;Yvh;i8f524AVXg@5Y_T/Qyb12h8yNQoDw?i8n03UiD1;3UB11;i8dY90w03UUR1;NEdw.;sq3oM4;5cyTgA24O9IP,;NXkO9IPw10,cyrd8.?3NY0ioIY9bE9:i8QR7ZX/@xHZf/xs0fBc19wYg82sldeulRSQ24Xnkbicu3m<?f//Z8yUIw.?i8Kja<?cq3ow4;4fJEdw.?i3Dh3Vi3og4?8j03UjQ0M?icu32<;4:N_XU120w0W0rP/YN_XU120w0ygnFAw?WfjO/YN_XU020w0ygnjAw?WebO/YN_XU120w0ygmZAw?Wd3O/YN_XU020w0ygmDAw?WbXO/Z8zjSLAw?ygmhAw?W8PP/@5M0@8l08?8IZBF8?bE02;Lwg:NMexJYL/yPS3Aw?Kw08;NMbU4:W5rO/@bfmyi?2W.;370Lw8;3Ef_b/UIZlp8?bE1:cs2@0w;ewEYL/yPQ@Aw?Kw0<?NMbU71;W17O/@b3hKi?2@8:370i8QlutH/Qydv2gwW4fM/YNQAydt2gwi8QZYJn/@xgX/_yMTCAg?Ly}NM4yd5kzq/Z8znMA8ewiYf/ct98zngA84ydfszr/_E7@/_UIdIp4?bUw:cs18zhknSL/i8RY923EUu/_P7ii8RQ9218zjTaRv/WeXK/@b3nOh?2@8:370i8QlVJD/Qydv2gwWb3L/YNQAydt2gwi8QZQtD/@yZXL/yMR7Ag?Ly}NM4yd5rnp/Z8znMA8ex_X/_ct98zngA84ydfmTp/_EzeX/QS5_M@4y_D/QO9_@yHXL/ioD4i8n03UgA0M?ZA0E10@44wc0<yb1lWr0,8yXwE.?ic7D0KxuXL/ioD5i8I5h9I0<y3K2w1:3Ujm0w?ctJ8zmMAgeJa3NZ40,1ykit08D1i8Ql9JD/P70Ly:18yu_EW@X/Qy9Tz79i8DGj8DDi8f30uy7XL/i8I5Y9E0<wXC2w1;fwUc20,8zjSCSL/WbvR/@5M7CHxtJQ84xzSQO9XkCdn9Q03NZ?8JZ<y3NgjEFf3/QwVWTnLj8DLWcvJ/Yf7U[K<;3FEfz/Sof7Qg?37Si8RX2XEa:W93L/Z8xs0fzAvY/Z8yNlMCw?i8C28<?eAQ_f/3NZ?37Si8RX2HEa:W63L/Z8xs0fzxvY/ZyYLQ8vc18yMkWCw?NvB_w2,?3F_vL/MYvh;cvp8znIcKwE;3Eae/_Qy5M0@eT_L/Qyb5gyq0,8yo8U.?WsPX/Yf7Q?cvp8znI9KwE;3E@eX/Qy5M0@eH_L/Qyb5typ0,8yo8M.?WpPX/Yf7Q?i8K38<0<ObIP,0,8ykgA44ybwOw10,8ykgA24ybwPw10,8ykgA64ybj2g8NEdw.;4wVj2gg3Vi3og40<MXt2go3Vi3ow40<O9IMw1?3F2_P/MYvh;NEdw.;sq3oM4;58wTMA2?fzCjX/_FmLL/Sof7Ug[4yduMyW2w;37SW63K/Z8yggAi8n03UXP@L/oLbZ27P0i8I55FA?cnVvU0M.?WtDW/ZC3N@4[19euVc3QvRWiXU/Yf7Q?LY8;3EZKP/Qy5M0@fwvv/Q6@;60eB@Z/_pF0NZAyduMOW2w;ezgXv/i8n03UW7@L/oLbZ27P0i8I5GFw?cnWvU18.?WmTW/Yf7Qg?ezzXL/yPzEneX/QydflDl/Z8ysoNMezrW/_WtrZ/ZC3NZ4?2Z;o0eBHZ/_pwYvh;j8DLW7zH/_Fm_r/QO9_@zHW/_j8D_WbfH/Z9ysh8xs0fxtbY/_FALT/Qyb3iKo0,8znIaKwE:NZAy9j2ggW4rJ/Z8yQMA44y9wlw1?3FRvD/MYvh;grU1:Wlz@/Yf7Qg0<yduMyW2w;37SW13J/Z8ykgA2eCC@v/KwE;18znI8cvrEZKP/Qyb5r@n0,8yo90.?WofV/@W3w;4yddvHm/Z8yt_Ej@X/Un0thd8yMmkBM?NE1z.;uBo@v/Kwo;18zjnpQ/_i8DvW2jK/@5M7k9j8RX1KAT@v/w3IJj0Z5@@AH@v/pCoK3N@4[23_M4fzHsd0,1lXEa:glp1lk5klky9Zle9@Qy1X7w10,8yTU8cvrEcuP/UB491O3@M8fxro5?36x2g0.;cu49eg;3//_i8I5@Fo0<ybC3,0,8yUwE.?i8Bs93x8yVwU.?i8Cc9b:18ypMA@:4ybC2,0,8ylMAm4ybC5,0,8ylMAk4ybC4,0,8ylMAo4ybC5w10,8ypMAY}@SC6,?28D2ij:3Xqoow4?8ys9.1;fJFxx.?3Xq0oM4?8y490s10,8w_A13Upd7;K3Y:NOvd83XSc9b:29MyDai8Kc9fw;18oZ98w_A13Ur_7g?YQwfLsAFO4yoi8C490w10,80t18yogAW:bw_:csDPi0@Zz2jE:asx8C4wfHY98yst8xs2U.;4wfhst8yogAW:4z71tCl=ics5NFk{3EMu/_XU?2?ic7E0Qw5/Yv<wB?3w_Qy9Mrw:2i3D1i0Z6Mky9NXw?2?i3D7i0Z3NQydL2go.?i8D2i8B4933E2uP/QObJ2go.?xs0fxrwq?2bv2gsKw4:NZAOdL2gM.?Wa7F/ZcyvW_1w;4O9v2h0i8B490zEqKD/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9h2hUi8I53Fk0<z7w0,=i8I5_9g0<z7[18yMnKB;ict0c}18yMnvB;i8Jc95x8ykw8i8n9t0W0L2g0.:@5bh40<y3v2hg<S9ZM@Sx2ij:NAgAs?fBogAUM;8jrj8DP3Vi490k1;ax2g4.?y8gAUw;4ybh2g8icu49cw+i8B494x8NQgAa}18NUgAw+18NUgAK+18NUgAy+18NUgAC+18NUgAG+18NQgAq}37x2ik+ct491[3Vi490o1;NXkMV@Q4fAYkNOkgar2hM3Umz7g?wbMAAM}fxeA;18yQgAo4ydsfZ8eTgAa0@2BME0<gfJCgA44S9@Aybh2gUiiDqgofA0k63Z059es8fwW420,dxt8fx7w20,8yPmxAM?wTMA4<fx1oa?2bhxy5M7gLi8eY9f[3Ug02w?vxV8wXMAO[fxsQi;f7Q?pCoK3N@4[18yTMA24y9S4C9P4MFY4Odb3ybv2gsct9cyuXEwev/Qybl2gMyTMA74O9ZKwvWf/i8n03UWx2w?j8BI90xcyu5dzjM6j8DPNQgA4}15cuS0L2ij[@55//Qybh2gUi3D13UcU2;i2D8ioD0i8J49618zn3_i8n03Ukm.?h8xI971cevIfwWcy0,8NYr//_grQ8:j2JI94xc0SMA24O9t2gwioDshj7Sj8DHi8Cc9a:18yrgAM}@SH2jz:joD5WOAf7Ug[4y3M059wYo1ioD4i8f324QVXw@3u0s0<MV@0@3rMs0<O9@HUa:j8DDj2DyWcPD/Z8xs0fx7c80,dxvofBs908eFQK4ybv2gwi8f?ky9NAwF_Aw1TAwVt2hgsWd8yUMAE:4O9UQS9Z4ybJ2j}j05A92y9RkC9_AM1UkMV@Q4fAIkf7Qg0<wXt2gEsRV8xsAfxlgb0,5xeRQsct491,:i8dY93w03UhV2;j8J493x8yQgAo4wHh2gEijD0j0Z7M4y5M0@5e0w0<MV@Qi8r2hMNQgA4<;113Vb5cuR8eTgAa7ay3Xp49123U069MEfO0k49Rky5Og@5zwA?379hojJtkJ8ykMA44C9TeBJ0M?i8JZ4bEa:cvrEnKr/UC49eg;3TQc7E7UC490,?3FdvH/Sof7Qg0<MV@Q4fAIl52ekfxeg7?23v2gg.@48fT/@CM_v/j8Qs0Qybdgmh0,9ys98NUgAO+1devIfAEgAE:4MFYQw3n2g8j8Bk921cylMAs4M1Q@I_3NZ0<ybty18yMmZA;i8IlHF;4y9MkwFYky1@v/3M0fxJI;18es9O9HZA:W9PB/Z8yPmlA;3Xp6a8j0trR8yPrHL0Yvx{i8I5up;4ybk0x8yNlCA;i8Cg0<0<yb1lyg0,8ygl9A;i8I5kF;8J068n0tal8yTgAg8IZU8k?bE8:icu493,;1:W8HC/Z8w_z_3UlW//yMkyA;xs0fx6P//Enur/UIUWdrB/ZczglcO/_KkE20,8zhnDPL/ioD1i8I5mnk0<ydduHg/Z8yPwNMex8Vv/WiT/_Yf7M18zkw1j8Jk921cyRMAs4y9PQybdryf?21V/_3M18wTMAe<fx3U50,cyQgAi4y9DfU<2?ig@WW3YB/Yf<O9xco<2?i8Adu8Y0<wVOw@2dMk0<ybx2iE:j05k94xcytJ42GgAE:4y3h2gE0ky9x2jg:i8K499w;14yagAE:4y9x2j}i8J495x4y6MAs4y9x2jo:i8J497x8ykgA84y3h2hE0kybj2hEi8e498}1h8JC64ybL2i8:j8J495x9zkgU1AzhXQzhW4m5V4wfhct8QqMAK:4y9x2i8:wbMAUw:1RgkGd18k}Kwg;2bL2ik:i3Dgi0Z2MEn_3UmV1;i3D1K}183Qb1i8B496wfAY0fJI29x2ik:i8JQ942_1w;eysUL/K0c;34ULLTB2gU.?ibzfZRfzFpL484zTUAxFz2gM.0.48f<z1Wwh8zgghi8B497x8aQgA84wZy1c;@75w80<ybj2hoi3Cc98}fwMc20,8yQgA84y9h2hUwbMAE[fxgbW/Z9ytO0L2ij[@5Mgg0<z7h2gg}4ybn2ggj8DDjjDYswTHamqgi8RU0kMV_Tcpj8DWLwE;18wYc1i2DWW4fz/Z8xs1RTAy9n2ggj8I5EEQ0<yb3qed0,cyst9eswfwEYa?2bx2jA:xs0fyvwj0,cySgAi4y9fnOd0,caSgA24MXp2gM3UeR5w?jg7Qict495w1:i8J493x8xs1QbAy3@fRTa4y3M08NQLd83XTgK44:FQbE_:i9zPi0@ZM2D2i6f2i8B495x8yMkFzg?i8BUc4y3v2gg?@4U0c0<ybh2gUct8NXkzTt2hoi8B4961C3NZ40,8yRMA44ybv2gUct98ytV8yvx8auV83W_6ifvPi3JY95wfwZAf0,8xs2_.;4wfhvx8yngAk4kNXky9v2gwWPlC3NZ40,cyvFcaua@2w;4O9V@wBUL/i8n03Uis3;iof50kOdo05ceSMA80@3SgM0<Gdn2Q0i3Js910fw@Ac0,devNOL4S9UoJY9>NQAQFYkM3j2g8j8Dej8Bc92zEBK3/Qybl2gMyTMA74O9ZKwRUv/i8n03UWI3;j8Jc92x8ys9dzjM6joDQj8Bc90zFsv/_MYv<ybdhCc0,8yQogi8JY95x8yogAC:4yb1v6b0,8yogAG:4wXL2iM:3Ufb:wbMA1g4:fxbQ;18yMp8yNnbyM?i2D2wbMA1<:fxbw7?23L2ik}g@lMkm5V0@kM8j13Uix:Kg4;18etsfwVc;18yXMAI:4ybt2hoi8DUj8QA3AwFY4MVVQwfgIxc3QbDi8n9t5i0L2g0.;7hai8JY9418zhlBOv/LA}NMewOT/_i8JQ942bL2jA:i6fgW9Xx/Z8w_z_3UjL5w?i8I5boI0<O9o0xcymgAm0Yvg023L2ik}DkewbMA1w4:fxnA80,8NUgAw+3FTLP/MYvw}18yUMAE:4O9UQS9Z4M1p2gEj8JQ9218yXgAM:4M1UkMV@44fAIkNXuDf@f/3N@[4ybh2hwi8n03Ulo.?icv6//_Q24Xg@5fxA?8J49114y6MAs8D2w@,w@81i8fO0kC9Q4MV@M@3RM;8j03UiKZ/_WsE:f7Q?i8Cs_w.8,8wTMAi?fysTW/ZcyQgAieCS@L/pyUf7Ug[4ybhwybvxy5_M@4FM80<yb1iaa0,8yoo0.?i8I558E0<y91gma0,8yMkeyw?yQ0oxs0fxsI80,8yPnYyg?Wo3W/Yf7U[wXMAB}4fxc8h?37x2ik}w;eB7@/_pF1cyud8yUMAE:4S9Z4ybJ2j}j8JQ9223v2gg.@4TMY0<M1p2gEj07xj3DXgg@iNj7JWqjT/Yf7Q?K<;33pyUf7Ug[cq49a[joDXWonU/Zdxs0fBc10wfQ1t0y4M0@5MLX/Qi8r2hMWt3@/Z8zn3_i8J49615cs18aQgAaeCbZ/_ioDsj8Dyj2DOi0dk90x8yMkvyg?i8Id88A0<wfKKE_i8D6i8f?o7C/Yf<y91v@80,8ypjN,0w<y9wg,0,8yMnNy;NA0F0kyb1uq8?2bg1y5M0@5b0U?8K49eg;25M0@9m.0<ybt2h0yPRtvw?Kww;18NUgAc<?3Z23M3E2Z/_Qy3@fYfx64d0,cyvvEOtP/Qy1N7w1;NM5JtglN1nk5ugl_3yMknvw?cta@.;4z7x2gC.{6q9B2gK.?Kg4:NQEC492,?2b1uhZ0,CyrgAb<?bU2:yogAa<0<ydx2gw.?i8D7pECc92g10,8ykgA8ezvTf/xs1@3Lq492U1;13UnT>?i8I51Ew;@Sw1w1?24M0@4AMU?ct491,:j8Dxhj7JWu_P/Z8yPntxM?yRooi3Jc93x13Vf4ggD4hoDwggzE3Und5M?xt9Q94ybH2jM:i8nJ3Ujf4w?vx5cyWgAO:4S5V0@5jN80<m4Xg@49Lr/P7JWiHQ/Z8xs2_.;4C9O4wfhvx8yMpczgOZ}4AFM4Cd13B80s19es0fwYo40,8zgg_j3D0sO18ysx9Qux8at1ces193Qv0ioDUiiD0ig78i3D7igZ2O4wVOw@3Jfv/Qy9zw,0,8ygQdxM?i8I55Es?8J068n03Ug8_v/i8JQ942bfq1Y?2W2:4O9n2hMj8Bk9218NUgAc<;4;3EgdT/QObl2gwj8Js9718w_z_3Un9_f/yNTexw?xtIfxbLY/_E2tT/UIUW8bs/ZczgnUMv/KlQ20,9ys58yMkcr;i8IUWsU50,cyvJ5cuQNXkybdom6?2bhxxcySgAi4i8H2iw:i8K49aw;37h2gg.;4y9x2jg:i8K499w;18yogAM:4ybh2hoi8C49dw;18yQgAu4y9h2gwi8DoioDdj2DMi0d490x8ykgAieIVA4ybjy18yMkdxw?i8D2i2Dai87W/Yf?@6Uw;4wV1uK50,O8rZA:We_q/Z8yPnExg?3Xp6a8j0ts18yMXHLMYv<yb1t650,8yR08i8IlLEk0<y9A0,0,8yMmMxg?i8A5Eok0<yb1qG5?2bg1y5M7iGi8JQ942bfjxX?2W2:4z7x2gM.;g;ezyS/_i8fU_M@5v//Qib5nC50,5xt8fx6//_EIZL/UIUW2Pr/ZczgmyMf/KkE20,8zhkZNf/ioD1i8I5HSE0<yddk36/Z8yPwNMeyuSL/Wj3/_ZC3N@4[18ys98yPkmxg?i8f?o7y/Yf<MXr2gU3Ui70M?pAi9H5o<;ig@WX3@0L2g7.:@5DwU0<O9Fdo<2?i3A5NEg0<y91su40,8NUgAO-fwW3R/Z8yRo8yQUoxsAfx9we0,8yMmvx;i8C60<0<yb1p640,8ygm2x;i8I5yUg?8J068n03UmG4w?i8IRuog?eBnZv/Kw8;18zjmpL/_ysvEMtH/Qy3@fYfxoLX/@b3lC4?25Og@4vvL/@ykSL/yPzE3tH/QOd1mi@/@Vfgg0<yd5hX3/Z9ys58yMmgqg?i8QR8sn/Qybe370W7_p/_FfLL/Qybx2io:i2K49c}fx5M20,8yXgAG:4wHJ2jg:i3DUsxcNQAzTZP7ii8D1i8DMifvNi8D6i3BQ95wfwW7U/Z8NUgAw+23L2ik}g@4zLn/Qybh2hoi8R80kzhWuDXZ/_i8QlBI7/XV}j8D_cs3Eodv/Qybt2h0yXMAV:4xzQezcSv/i8fU_M@5D@X/UIZp8c?8n_3UihXL/W9_p/@beewoSv/j8Q5HY7/XCQ0w?i8Qlasb/QC9Mkyb1pJE0,8zjkINf/i8IUcs3EyJz/@BiXL/3NZ40,8yPk9wM?i8Jk911cys1C3NZ40,CpyUf7Ug[4C9Mky3M051wu7/MY0hw@Tz4U<;j07ai3D1tu54yVMAV:4y9l2gghonr3UAG2g?ibH////_vQy9@2n/MY0i2ekNw.8,8ylgAieA7Zv/j2D9WlLX/Z8yPm8ww?Kw4;18yMV8yMlFww?i2D8u2kNQAybz2jU:iftQ95x8esx83Qv1i8D2i8n0K<;183Qjgi3Bk93wfwDgf0,8eRgAe0@3QwM0<ybL2i8:i8Kc9bw;18NUgAw+18yUgAS:cu499g:2:i8f?QwVPQwfhIZ8es4fwJTP/Z8yQgAe4yd312U.;4zhWkwfhcx8ykMAe4y9OAzTSAyb1su10,8yoog.?i8I5Mo40<y9A0w10,8NUgAK+18NUgAy+3Fxff/MYvh;i8DUic7w0AwVQ0@3qfr/Qm5V0@5n_r/@CV_v/3Xtc93xCyoNm,;82Y90s1:3UhW_f/i8JY94x8ys61Uv/3M18yrPe,0w<S5V0@9o_P/@Bm_f/3NY0i8JQ942bfsRS?2W2:4O9n2hMj8Bk9218NUgAc<;4;3Ertv/QObl2gwj8Js9718w_z_3UnSZL/yMnXw;xs0fxezS/_EdJv/UIUWa_m/ZczgkBLf/KkE20,9ys58yMkVpw?i8IUi8QlIX/_Qydds31/YNMewxRL/j8Js971cyRgA8eCvZL/i8JQ942_1w;4y9j2hMj8Bk923EGtj/Xw3:j8Jk9234ULLTB2gU.?ibzfZRfzFpL484ybj2hMi6CQ93,0,.wY0ifvyic7G14yd11p8aUgAO:4wXx2jM:3UbpXf/NEgAE}18yPkGw;joDXicu49cw+WiLL/Z8yMkfw;NE0o.;uDSZ/_3NY0i8J490xcyu6bv2gsct9cav5czig1j8DCW2fk/Z8yRgAc8JY91NcyvrEMJj/Qy5M0@eAwk0<O9p2g8joQY1AS9Z4MXr2gw3U8FY/_pF1cyu1cav180QgA24y9h2gwjonJtnB8yRgA8eBzZL/A4O9U4ybv2gwi8JQ951cav180QgA24y9h2gwijDZsN18eRMA47c9jjDY3Ucp1;jonJtjHHLSoK3N@4[18yR0wi8I5fnY0<wFQ4wZ/Yf07pGi8I5cTY?8J068n0tni_p:ewyRf/i8I56TY;@Sk2y4QDn3i8IgWY9C3NZ40,8yT0wi8I5ZnU0<yb5up@0,8ys58av58wvD/MY03Upz.?i3D23Uay:LSg;3EQdf/Qyb1sB@;fJB0Exd9RKkybceKU3NZ0<ybt2h0yPRdt;Kww;18NUgAc<;4;3EZZj/Qy3@fYfxm7/_Z4yNmevw?honi3Uhh//Wczk/@beex1Rf/j8Q5JXD/XAI1;i8QlkHT/QC9Mkyb1shz0,8zjllL/_i8IUcs3EIZf/@Ai//pwYvh;i8I5cnU0<ybk0x8yNkuvw?i8Cg0<0<yb1h1@0,8ygk1vw?i8I52DU?8J068n03UgB//i8JQ942bfphP?2W2:4z7x2gM.;g;ew@Rf/i8fU_M@5@LX/Qib3tlZ0,5xsAfxeH@/_E3Zj/UIUW8zj/Zczgn@Kf/KkE20,8zhmpLf/ioD1i8I52Sc0<yddpO@/Z8yPwNMezWQL/WqL@/Yf7Qg0<ybn2h8i8D6j8Js9218ytB83XHFfQMXr2gUi0Z5Sky3M061VL/3M18yMRhvg?i8D7i8A5fTQ?6p4yqNN,;87D/Yf<O9DfA<2?i8CsYg.8,8es9OiQM1XkwXr2gg3UdW_v/i8J49218ykgAieA6Yf/pwYvh;i8Js96182scfxbDP/Z8yRMAo4wVS4wfgId8ysvF4v3/Sof7Qg0<ybugybshy5Zw@4Gg;4yb1rFY0,8yo40.?i8I5H7M0<y91pRY0,8yMmCv;yQ0oxs0fx7z/_Z8yTgAg8IZc78?bE8:icu493,;1:WdHi/Z8w_z_3Uld//h8I5snM0<m5M0@4fv/_@yHQL/yPzE9db/QOd1pGT/@Viw80<yd5jmX/Z9ys58yMmDog?i8QRebT/Qybe370W9rh/_F_LX/V18xv@@.;4C9M4wfhfV8yP5czgOZ}4AFY4Cdd3B80vp9ev0fww,0,casx8es8fwYj@/Z8yo40.?i8A5OnI0<yb1t9X?2bg1y5M0@4FfX/Qybt2h0yPRssg?Kww;18NUgAc<;4;3E1Jb/Qy3@fYfxnD@/@bfpVX?25_M@4q_X/@zpQv/yPzEkJ7/QOd1syS/@Vng80<yd5meW/Z9ys58yMnlo;i8QRpHP/Qybe370Wcjg/_FbfX/MYvw}19yvnF7LP/UIlgDI?8ni3UihYL/W7Th/@beezSQf/j8Q5FXv/XA@1;i8Ql1XH/QC9Mkyb1nBw0,8zjkaLf/i8IUcs3Eqd3/@BiYL/i8QQfQMVNw@3ZLX/Qy9NADhW4wFRAMVNAAfh_19yvx9av190s18evt93Qb0Wt7@/Z8yTMAcew7Qf/ioD6WjrB/Z8yTgAg8IZh7;bE8:icu493,;1:WeXg/Z8w_z_3UmFYv/yPm6uw?xvofx9LN/_EMt3/UIUW3Hg/ZczgmMJv/KjM40,8zhlbKv/ioD1i8I5LlY0<yddkWX/Z8yPwNMeyIP/_WlPN/Zcyvx8yTMA84ybt2hgjoDYj2DMi0d490x8ykgA8eCv@L/i8eY9fw:13UpV>?K3Y:NQLd83XSk9fw:FQ37ii9x8yogA2<0<y9x2jE:i8eY9ew:13UjAU/_Wq_z/Z8yQgAa4Gdj241iER48058ykgAa4wVNw@3jMc0<y5Og@54vf/Qy9j2ggjoDYWqvH/Z8yPmhug?i8J624wXx2iM:3U8f>?i8Daj8D7i3Dn3UfwW/_i8IRqnA?eCFZL/i8I5nnA?8J864yb5kJV0,8ehkYug?ykMAs0@2C0k?8J068n03UnL1g?i8eY9f[3UzY0w?yQgAs8n03UjM0w?i8eY9cw}3Ugn1g?i8JQ942_1w;ewuPv/j8Ks9f:18yVgAe<?37Sjonrt5J8Ks_Tk@eBCYgwic7G0QxFL2gM.0.48f<y9Q4zTUkz1Wwh80vF8yXMAO:4y9Q4wF@4MVS7cxiiDjLCg;19zggXi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY9229YHU2:W3Ld/@5M0@e@g4?fq492o1;13Unj0M?ZEgAbw4;4fxdQ10,8yMlgu;j8DxNE0o.;st491,:WkTM/Z8ypgAW:4z7x2g8.{eB1_L/i3B496wfwEHF/Z8yUgA@:4zhp2gUi8JY93x8yUMAI:4wVNQwfg_yU0w:Z2x2ik:i8BY93y9x2ik:i3Bc95wfwZY;20L2g5.:@4Qg;4ybB2g8.?i8Dhi8f_0nokcs2VfM;fd83XT7as58oYB80t58yUgA2<0<ybL2iM:i0@Lz2jE:i2JY95x83W_7i8Qkgbw1:i07ii8n9i0Z4O4wVOD88i8Dgct98Z_6bB2jA:xt9UnQwVNQyd5kSR/@@g:4wfhIt8yTMAg4y9MkC9Nj70W0Lb/Z8yTgAg8KY9eg;18oZ3EtYT/Qy3@fYfx1Q80,c0mMAm4yb1g5T0,8yQMAm4y9i0x8yPnNtw?i8I5UDo0<y9xx,0,8yRgAe4yb1ttS0,8ZZF8yp08.?ict496w}WjjE/Z8yRMAi8JY9>NQAS9Z4y9TKzFOL/i8Jk932bv2gsj8DSW8zb/YNQAy9n2g8i8IZuDo0<y5M4wfic9dzjM6WgDF/@3v2gg0w@4?8?ct491[j8DxWnfK/ZcyvJ5cuQNXuD7Vf/h0@Sr2hMWivB/Z8yTMAi4y9Mo7x/Yf<y9LcU<2?WkvN/Z8NUgAO+2@p:eCa_v/i8niKg4;18yPVcyMnQtg?i0Z4Qky9MkwF@kOd39k}ioQY4kw1_QwV@g@2Swc0<MFO4z7x2j8+4AVM0@3Hur/Qy9xw,0,8ygmItg?i8I5Jnk?8J068n03UgGYv/i8JQ942bfjZH?2W2:4z7x2gM.;g;ezFO/_i8fU_M@47Mo0<z7x2j8+4ybdmNR?3FiKr/Qz7x2i-cu499g:2:WjbD/Z8yTgAgbY6:i8Bc9214y8gAE:exfOv/K0c;18yQMA8cjy@_uk93w10,8Kc_Tk@eBCYgwi6CQ93,0,.wY0h0@Sx2iw:ifvyic7G14yd11p8yPnGt;j2Dwi3DE3U94Xv/i8K49aw;14yaMAE:4i9NkObp2h8i8C49d:18yUgAC:4y9x2j}i8J495x8yogAS:4ybh2hUi8B4923FneX/Qybt2h0yPQvqw?Kww;3ErsD/_q492U1;13Uko_f/i8K49bw;18yQMAmct49102:i8R420p8Qux8yogAK:eDTUf/h8IJhDg0<m5Xg@40uD/@y0OL/yPzE@sD/QOd1p2O/@VH0c0<yd5gGP/Z9ys58yMlYmg?i8QR3rn/Qybe370W6L9/_FMKz/Qybt2h0LMo;3E1Yz/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9x2j8:WpTW/Z8yT08xsAfxlM1?2bi1y5Og@5kg40<y5ZHA1:i8IUj8I5snc0<wfhf58yt58avBczgOR}4Cdf3580vZ8evAfwyA20,casF9et0fwzo3?2bg1y5M0@47fT/Qybt2h0yPTtq;Kww;18NUgAc<;4;3ExYD/Qy3@fYfxurV/@b1hZP?25M0@4SfD/@xqOv/yPzEQYz/QOd1kCK/@VVM80<yd5uiN/Z9ys58yMlmm;i8QRVXf/Qybe370W4n8/_FCvD/Qy9QkzTSkyb1rJO0,8yoog.?i8I5Jn80<y9y0w10,8ylgAe4z7x2i-cu499g:2:WnjA/Z8NUgA2<{18NUgAW}4;3FxdP/QybdAy9OAwVPDcri8Ks9b:18av58etB83Qvbi3D83Ua@.?j8D7WsDU/Z8yNkPsw?i8Cg0<0<yb1ilO0,8ygkmsw?i8I57T8?8J068n03Ukg.?i8I53n8?eD6@f/i8QY4AwVPM@37fP/Qy9NQzhWkMFNQwVPQwfh_B8yt58avB80s58evF83Qb1WvvX/Z8yTgAg8IZqSs?bE8:icu493,;1:W1n8/Z8w_z_3UkI_f/h8IdH740<m5Og@47fP/@zCN/_yPzEnYv/QOd1tmI/@Viw80<yd5n2M/Z9ys58yMnylw?i8QRsXb/Qybe370Wd76/_FTvL/M@Sh2ggw@,w_,j3DX3Vb22t18xsAfxiY20,1yskNXuD4T/_i8QYdAwVPM@3PvT/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWqzZ/Z8yTgAg8IZCmo?bE8:icu493,;1:W4f7/Z8w_z_3Un5_L/yMnrs;xs0fxbv@/_E5Iv/UIUW8_6/Zczgk5Hf/KkE20,8zhmwH/_ioD1i8I54Bo0<yddqeN/Z8yPwNMew1NL/Wnz@/Z8ysJ8yTMAgbV}i8QlvWX/QwFMP70i8DpW4L4/Z8yTgAg8KY9eg;18oZ3EJYr/Qy3@fYfxaE10,8yQgAm4w>Qyb1jVM0,8ylw8i8IlaT;4ybfhNM?3FHLr/QkNXj7JWpbu/Z8yp;g?i8Al_SY0<yb1gxM?2bg1y5M7kpi8I5@CY?eCy_f/goDEWg_X/Yf7Qg0<ybt2h0yPRZpg?Kww;18NUgAc<;4;3E9Yr/Qy9MAyb1rRL0,8w_H_3Ulw_f/wPSQrM:@4k_P/@zNNv/yPzEqIn/QOd1u2G/@Vng80<yd5nKK/Z9ys58yMnJl;i8QRvH3/Qybe370WdP4/_FpL/_MYvw}14yMlxrM?hon03Ujh@v/W9L5/@beewkNv/j8Q5yGH/XBt0w?i8Ql9qX/QC9Mkyb1ptk0,8zjkEIf/i8IUcs3ExIj/@Ci@v/i8IR2CY0<kNM8Jm64i8r2hMgoD5WhDW/Yf7U[yMnOrw?xs0fxdnT/_Ebsn/UIUWar4/ZczgkZHv/KnI30,8zhmTHv/ioD1i8I5alg0<yddrGL/Z8yPwNMewoNf/WprT/@3fqhK:3Uh9_L/We74/@beexqNf/j8Q5YqP/XDA0M?i8QlqWT/QC9Mkyb1tRj0,8zjlKH/_i8IUcs3EPcf/@Aa_L/3N@[45nglp9ytp1lk5klld8w@MoynMA1bY;40i8BQ90zEfc7/QC9NQS5ZDh@hj7AWNof7U[W6f4/@3e0hRq4QVZ7dzi8J490xcyvabv2g4j8D@j2DyiEQc8bw;40i3D2i0Z7Qex2ML/ioD5i8n0uc9QcAy9MQO9_mqgi8Dqi8DKLM4;3E8cj/Qy5M7wbi2D3t2p80snHUp3E@Yf/UcU17jmi8f464O9_RJtglN1nk5ugl_FMc7/QQ1XeBW//3N@4[23_M9_2Xw1:MMYvh;gluW2w;45mgll1l5m9_ld8yvd8wuMU1;i8J@237SW5H2/Z8yTIgKwE:NZEB491zEhIb/Yt490M}ykgA78fZ0Tgsi8JX64yddr6H/_Elsf/Un03Vj03Xr0ykgA34yb1g9J0,8xs1Q1cp0a058zkgAg4kN_Qydr2gMhj7Jict492w}i8B4911CpyUf7Ug[8JY91yW0.0<y9XKyLMv/i8n03UX2:ic7E18n0vJWdmfZ9yuV8Muc4i0ds913H5MYvh;ijD53UaT:iof644AVTDiSioI6j3DEtupd0SU8jon_tibH9gYv<SbpN1cyvZdySY8j8BA92zEyY3/QS5V7g8joDDjjALtdV8yMl7r;i8n0t0hcymwwyQgA38n0tixcyuF8yMkIr;ibA0Yf///vU7y/Yf<wzzd0<2?3Umu:j8JY92zFtv/_MYvg,cyvZdyTYgW2j0/ZdxvZRXQy1N3w4;NM5JtglN1nk5ugl_33NY0LNw;3ETHX/Qy9MkCb1Ay90kCblwx80s98yl48i8Rk92xdxvZRbuIM3N@4[1CpyUf7Ug[6pCbwYvx{ioRn44SbvN1dxvZQ1kAV1TbKj8BV44y92KBA//pF2bv2gscta@0M;exMMv/j8JY92zFN_X/Sof7Qg?8f_0DYbK<;333NZ40,1lXEa:glp5cvp1lk5klld8yvd8wuME1;i8J@237Si8RI921czmMAcewvMf/i8JX4bEa:cvq9h2g8W0L0/Z8NQgA6}29h2gc3NY0pCoK3N@4[2bv2g8Kw<0,8yuXELX/_Qy5M0@eZw;4z1W0i5M7Xuzlz_ioDIic7z14M1W@Il3N@[4AVND9ziof444AVT7iWioI494MVY7nFi8JY91xd0TgA24y5_TksWNZcyTYgj8JT24O9v2goW9W@/ZdxvZQ24O9_QMVdTjxj8DNi87x0f3/TWOyTMA337iLwc;3Els3/@Kw3NY0LNw;3EhHT/QCb52h8zkMA64y9NAy944Cbh2g8i07gi8B624ybh2goi8n0tiXHcmof7Ug[6pCbwYvx{pCoK3N@4[18zkwgi8J<4y5M7g5i3AgsKV8ykogi8ANWi//ZCA4y1N2w4;NM5JtglN1nk5ugl_3A6pCbwYvx{w_Y2vMqU.;cdlKwE;18yul1lQ5mgll1l5d8yvd8wuNUww?i8J@237SW8W@/Z8yRIgi8QR7Gr/UB491h8yt_EFX/_Qydt2hgLM4;11ysjEZrX/Yp492?xs1R4UJ496wB0f;3Q0w;3Vh49215xugfxdQ20,8zkgAg4kNM4z7h2gM}4OdF2jw:i8B4921CA4ybt2gwyTMA5bEg:j8B492zEWbT/QObh2gEi8fU40@5ww80<Obt2gMj3B4941QqXYo:j8B492zETHL/QObh2gEi8D1i8J49418yg58yRgAi4w>AS5ZAy9kgx8zlgAc7kBWOxCpyUf7Ug[6pCbwYvx{ioRm44Sbtx1dxvpQ1kAV1DbKj8BN44y92KBy//i8DpLw,;NM4O9h2gEj8SI97,0,8zhlXEL/j8DLW2OY/YNZz70j8DLWb2Y/ZcyQgAa8n.oD73UBC.?j0d494xdxvpRcuAh//A4SbhwxdyTUgj8DTj8B492xcynMAcewSLf/jon_j8J492wfxez@/ZdyvVdegofxtP@/Z8ytB8zhk9EL/j8DLcs2@0<?eyPK/_cvpcyuYNMewTLf/goD7xs1UE4z7h2gU}4O9VED7W4SZ/@5M7kdi8Kc91,0,8xsB_5ki9_@y4Lv/j8DLW0OY/_Fp//Qybh2gUi3D1vK58zngAe4y9t2gEi8Jk92x8as54yvW_.;eyKK/_i8n0u1B8yUMA4<0<ybh2gUi3D1vZjHGgYvh;W8KZ/@b08fU17jrzl3Gw@bLt123@0AfBca3@5wfBc08MDi0i8JQ93wNQAi9_@xdK/_i8S497020,8ykgA6eIopwYvh;i8JQ91x8ysa_.;ex6Lv/i8JQ91yW08;4i9_@z4K/_i8n0vZvFbL/_Qz7h2gU}4O9VED7W5uY/ZcyQgAa8n0th58yUgA4<0<y5M0@fggc0<i9_QO9h2gEW82Y/Zcyu_E2bL/QObh2gEWkX@/ZC3NZ40,cyvZdyTYEW8OV/ZdxvZRXQy1N7y2;NM5J1n45tglV1nRT3i8S497020,5cvYNSQz7x2jw+4y9h2goi8S499w20,8ykgA20Yvx{i8JQ91ybv2gkKw0a?3E_rH/Qy5M7WsibXdPcPcPcPcP4zTVAz1Wwm5QDXji8JQ90ydgLZcySgA64yd1818zgj6i8B492x9ehMA3Uka.?3NZ?6pCbwYvx{ioJQ91x9yRgA846bv2ggi8CQ97,?20v2gw?@4rw40<y9QoD@i8Sk97,?2_.;eznKv/ioJc91x1yTMA4bU3:i8Daigdc9218wu80Yf/i2DhW76X/Z90RMA24S5_TlQWTsf7Qg0<CbhNx8zpgAs<?bY1:i8C497,0,9yQYwgoJT4exWKv/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhW1uX/ZdyTsEj8D_igdv24O9J2jw:W0@U/Zdxvofx6o10,dyvt9ehZQzAC3N2xceSgAa0@4H_X/QAV72gfx0n/_@_c:ezbJ/_Nc5@rMgAi8D1NvV_<Cbh2gwi8B184S5_M@4cM40<Cb52h8zogAU:eIH3N@4[1CpyUf7Ug[6pCbwYvx{ioR7a4SbvOxdxvZQ1kAV5TbKj8BVa4y924ObL2jw:NvxTiof4a4MXp2gE3UlK//Whz@/Yf7Ug[ezrZv/ioJc91x1yTMA4bU3:i8Daigdc9218wu80Yf/i2DhW1mW/Z90RMA24S5_TlDWhz/_ZC3NZ40,9yTsoi8CQ97,0,9yRswgoJ_4ey7Zv/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhWciV/ZdySYEj8D_igdv24O9H2jw:WbOS/ZdxuRQ5QS9XQAV7TivWqP@/ZCbwYvx{hj7_iof4a4MXp2gE3Umv_L/WkDZ/Z8zogAU:eD@_L/i8Jk93x8et0fzH7Y/Z8zngAe4y9t2gEi2Dgi8Jk92x4yvW_.;4y9MkO9h2goW7uT/ZcyQgA64y5M7wti8K491,0,8yRgAe4wVQ7_7WmDY/ZC3NZ4?3EiXD/QObh2goyM23@0hQQERgWEfyXTgkw_w93Vj2w_xo3Vj02c8fx3rY/Z8yTgAe37ih8D_j8B492zE_Xr/Qydx2hM0w?j8J492x8ykgA6eIsi8JQ91x8ysa_.;4O9h2gEWfiU/ZcyQgAa4ybt2goKw2;14yvZcykgAaexEJ/_j8J492x8xs1_M@Dc@/_pwYvx{w_Y13UXn0w0.luW2w;45mgll5cuR1l5l8yvljyvJ8wuOE.?i8J@237SW3WT/Z1ysi3@Mcfx8E2?3E3rP/QydfvOu/Z8Muw3i8So/Yv0bw:2i87z?3w_QwVMQwfhZyU;w<wVMQwfgJzEpXn/Qy5M7gnKwE:NZAy9N@zzJL/i8D5i8n0vMmZw:4ydv2gMWdOS/Z8NQgA4}y5M7kSNvBL3tuq/YNQInVrEgAC:cjyuj_1NvB@M4wfHQgAk4zTZrE:8i3Dgi0Z3Q4y9l2ggi8SQ91,0,4yu_E2rv/Un0thubx2gE.?9g3M;Z08:@4Tw40<6V1g;4C9S379h8Dycvp4yu_ERHv/QC9NQy5M0@8Ow;bQ}grU:1tj5CA6pCbwYvx{grA5:ioDocsB4yu8NZAi9X@yoJ/_ioD7i8n03UWt:yPR@lw?xvYfysU;1c0vR9euVPNAydL2iw:WeCR/@9Mon0tlf5@mYdWVD/Qybt2ggNvBKx2g8.?Ne9VfY75@nX0i0@Lx2j8:i3DMsOp8yMmfo;i8n0t1EfJA0Exc0fxjI7;f7M1CpyUf7Ug[4C1Nw:7Flf/_MYvg03EGXr/QC9NEcU5w@410o?8IZTlk?8n_uhkNM4y1Naw10,rnk5sglR1nA5vMV18zrgAE:bE8:icu49a}1:W7aS/_HOQydJ2iw:Kww;18NUgAE}4;3EkHr/Qy3@fYfxgH/_@b5uFv?25Qw@4_fX/@wBJL/yPzEDHn/QOd1k@x/@V8go0<yd5q@u/Z9ys58yMkxhg?i8QRIG3/Qybe370W12R/_FLvX/MYv<ybvh2W2w;37SW9yQ/Z1ysnFnLT/Xw1:MSoK3N@4[18yVgAg<0<ydt2gEhj7_cs18NQgA8}18NQgA2}58yjgAi8ni3UXM_L/3NZ?6pCbwYvx{i8Dhi8Dti8B492x8as58etB83QrFi8nJ3UhW.?hj7SioDEi8IQ94kNOj79jiDMh8Dyh8DLW5mQ/Z8xs0fy0M1;fx3810,90sp9euVOPQybh2gwpwYvx{jg7TyPRvl;j07Mi8B49225_M@9dM40<ybB2h0.?i3D23UVn_L/j3BY90wfwSL/_Z8zqMAE:4y9X@yHI/_ysa5M7l5NvBL3qSn/Z8yUgAO:cnVrEgA2<?cjyuj_1Nc5VvIp93W_6i3J4911P5Qyb1l1u0,8xs1Q2M@Sg2y4M7kH3NY0i85490w:1i8J49218yVgAg<?eDR_L/3NZ4?21@x0D0,QSbZA:ylgA6ewaI/_i8DLW2aP/@bl2goi8K49cw;23Mw593W_6i3J4911OOeKCpwYvh;W2KQ/@b08fU10@4XvX/UfUnM@kMEfU9w@kMgzatgO3UfK3@18fxqE;18yQgA84S5Zw@5RLX/QybB2h0.?i8Dhi2D1i8n93U@f:hj7SWrH@/Yf7U[i8SQ9a:2W2:4z7x2iw}g;ez2I/_i8fU_Tgci8J4923FC_X/SqgyPRing?xvZQWKyhI/_yPzE2Hf/QOd1rKu/@VV0k0<yd5hKs/Z9ys58yMmdgw?i8QR7FX/Qybe370W7OO/_HHHw1:WrTY/Z8es8fzGzY/Z8zkgA84Obt2g8i8A494QV_w@2q<0<yb52h8ytB4yuV4yuvE7H7/Qy9Nky5M7wKt3qbflpi?25_M@9Zw40<A1XQybh2gwi3C494,0,_K@Bg_f/3N@[ezzIL/wPw4tdJ8yUgAg<0<ybl2gwj8BQ90x8es8fzijY/Z8znMAaezVIL/xs0fxhbY/@bv2gIKw0<02@>g?ezuIv/i8S49a:18ykgA64ybx2h0.?i3B4920fzpI;18ySMA24y9n2g83NZ0<MV_g@29Mg0<Obh2g8yRgAb379h8DLi8IQ946V1g;eyqIL/i8D3i8n0vBZ5cvof7Q?pCoK3N@4[19ytybv2gEcsANZAQFY46V1g;4i9UKxAIL/i8n0vwx90sp9etVORUIZil4?8n_3UB70M?i8J4921d0vt8eogAg<;@fs//UJY92zEuH7/UJY92PEsr7/@AJ@/_3NZ0<ydH2iw:i8DLW8yM/@9MEn03Ume:NvBL3oqk/Z8yUgAO:cnVrEgA2<?cjyuj_1NvB@MkwfHY58eQgA47dxi8I5aBI0<y5M7hl3Xp0a8j0t4TH287W42s?7h3LSg;29l2goi8Bc90zE0b3/Qy9X@woIf/yRgA64ybj2g8i8K49cw;23Mw583W_1i3J4911OLCof7Ug[4C1Nw:7FVfT/MYvg,8zrgAE:bE8:icu49a}1:W0aN/Z8w_z_3Uny_v/yPmqmw?xvofxdjZ/_ERr3/UIUW4WM/Zczgn_C/_KvA50,8zhlvCv/ioD1i8I5QjY0<yddmar/Z8yPwNMez0H/_WpnZ/Z8znMAaezhIf/xs0fy2_Z/@bv2gIKw0<02@>g?370cuTEIG/_Qydx2iw:ics49}58ykgA26qgpCoK3N@4[2bl2gIgrA5:ioDocsANZAi9X@y7If/ioD7i8n03UV8_L/yTMAa379cvp1Kgk;19ys14yubEoH3/Qy5M0@e9LX/UIZiQY?8n_3UDr:j07Zi3AI97eyi8JY90zEKaX/Un0tkj5@mYdL9b/YnVrEgA2<?cjyuj_1NvB@MkwfHUMAO:4wXj2ggsNF8yMRzmg?i8n9t0UfJAAExcAfxvo10,CA4y112g:1Wkf/_Z4yiMAioDRj8BQ90z4MnB@NAy9n2goysLH4mof7Ug[87X42s?7gHLSg;23MM7E2WX/QydL2iw:W1WK/Z8yUgAO:4AfHYpceuxOPkibb2hcyTgA24ybn2goWmHU/ZCbwYvx{i8JQ90yW2:4z7x2iw}g;ewlH/_i8fU_M@50f/_UI5Hlw?8n03UjO_L/goI@W6mK/ZczgkmCL/KjM60,8zhlSB/_ioD1i8I5W3Q0<yddnCp/Z8yPwNMeznHv/Wrv@/Z8yTgA6bE8:icu49a}1:WauK/Z8w_z_3Umk_f/yMQ_m;xsAfx8rY/_EuGX/UIUWfeJ/ZczgmACv/Khs60,8zhk4B/_ioD1i8I5tzQ0<yddgup/Z8yPwNMexBHv/WkvY/Z8yTMA6ew6Hv/goD6xs1RgsnVrMQ7Av/i8K49cw;35@mW490w1?34UDA_MsnVvId83W_3i3J4911P54yb1qJn0,8xs1Q20@Sg2y4M7kli875}uBX@/_go7@42s?7jHLSg;11wYo1W7KI/Z8yTMA6eyhHf/i8K49cw;183W_3i3J4911OPeK@i8Bs91z4MnB@NUD3WMy1@N0D0,QaHZA:wYc1W3CI/Z8yTMA2exfHf/i8K49cw;193W_7i3J4911OPAybn2goWsbZ/ZCA8f_0TYbK<;333NZ40,1lXEa:glp1lk5klld8yvd8wuPo0<0i8J@237Sj8SI9d:3EVaL/QybuN0NZHEa:goD6Wd6H/Z8yTIocvqW2w;8B491zELqL/Qy9NoB491PEAr3/UBI92x8Muw3NQgAb<;18zpz/NY0K}98wuc?e3_i3D3i0Z7Sbw?2?i3D3i0Z2S4ydh2h0hj7Ai8B491180tJ8yTgA44i9Z@zKG/_xs0fy0o10,cyTMAs4Cdb1N9euYfwHY;18zkgAc4y9h2g8i8Sd?3/XE;40j8DKh8DTW7eG/Z8xs1@pAy9MHUa:j8DLWbWI/Z8xs1QkkMFW4ybt2g8yTMA6bEg:i8SI1g40/ZcymgAc4y9W4MFU4y9h2gUW2KI/Z8w_wgt42U.;4y1Ndw0.1rnk5sglR1nA5vMSof7Qg0<ybt2g8yTMA6bEg:j8BA9318ylMAeezHG/_i8fU47n0ioDIi8QIaQAVXM@3i//Qydv2gEKCg;2@.;ewxGL/xs0fzLX@/@bv2gsKww;18zngAcewSGL/Wur@/@gcs3Fuv/_Sof7Ug[5eX.;4y3X218zngA7ezcGf/i8D2i8cU07goyTMA74y9NAy9h2g8W2aN/Z8yRgA28D3i8DnW1eE/Z8wYgwytxrMSpCbwYvx{kXI1:i8fI84ydt2gsW7OE/Z8ys98wPw0t1ybv2gsi8D6i8B490zEoHT/Qybl2g8ysd8ytvEMWv/Qy3N229S5L3pCoK3N@4[1jKM4;18w@Mgi8RQ90PEbaz/Qy3e,Q5kyb5mZk0,8xt9Q1Yq26<;4NSQy9N@xVF/_i8f448DomYegkXI1:i8fI84ydt2gsWeOD/Z8ys98wPw0t1ybv2gsi8D6i8B490zEEKr/Qybl2g8ysd8ytvEcWv/Qy3N229S5L3pCoK3N@4[11lQ5mglhlLg4;1ji87IM:4ydt2gsW9aD/Z8ysd8wPw03Ui7.?ySMA78fZ.@eO<0<ybu0yW2w;37SgrP//_WcaE/Z9ysu3_g8fxro10,8zjT8A/_W1GD/Z8zjSvAf/i8D5W0KD/Z8xuQfx3810,8xs0fx2A1?2W2w;37Si8DLi8B490zEBqz/Qybv2g8KwE:NZAy9h2gwW7@E/Z8ykgAa4m5_M@fsg40<m5V0@eW:4ydfs4T?3E_aD/Qy9NkgXE[fxrM1?23K1}13Unx.?i8QZhUX/@y3FL/i8n03UiG:KwE:NZAy9N@zXF/_Kw4:NZAi9VQC9N@wpF/_i8D5i8fU_M@4C:4ydflkT?3EAaD/Qy9WAydt2gMh8D_NvBLh2gwh8BA9437h2h4}cnVvQgAc4ybw0w;18asb4UvBKOcjzYib20rEE:NvF_h2h8WduE/Z8w_z_3UiV.?i8QZZzo?ewNGv/i8CE2:6oK3N@4{NXky9T@xCFv/i874M:8DEmRR1n45ugl_3yMQSkw?xsBQaKxRGf/yPzEXGv/Qyb5osT0,8zjlEBf/i8IWi8D2cs3EsWv/MYv0bQ1:WWJC3N@4[18yTIgKwE:NZKzMFL/goD4Wjb@/Yf7Ug[4ydt2gwKx:14yv_E7Gz/Qy3@fYfxnf@/@bdrph?25Zw@4pvX/@zNF/_yPzEqGv/QOd1sej/@VZ.0<yd5nKg/Z9ys58yMnJdw?i8QRvFb/Qybe370WdOC/_F9LX/MYvw}14yut8zngAc4i9E}3EXar/Un0th2bh2h89g3M;Z08;7hRNUkg}w;4ydt2gwKx:14yuvEvav/Qy3@fYfxsb@/@b1hhh?25M0@4JfX/@xfF/_cuSbeez6FL/j8Q5BVb/XAk1g?i8QlRU/_QC9Mkyb1kAS0,8zjnqAv/i8IUcs3Eear/@BR_L/NUkg}g;eCB_v/yNmSk;xt8fx3D@/_EYqr/UIUW6GC/ZczglbAv/Kh050,8zhlXz/_ioD1i8I5Xjk0<yddnWh/Z8yPwNMezsFv/WvHZ/Yf7U[kXI1:i8fI84ydt2gsWfOz/Z8ys98wPw0t1ybv2gsi8D6i8B490zEwKr/Qybl2g8ysd8ytvEgWf/Qy3N229S5L3pCoK3N@4[1jKM4;18w@Mwi8RQ91PEHaf/Qy9MAy3e,Q68JY91N8ysp8ykgA2ey2Xv/i8Jk90y9MQy9R@zPEL/i8f488DomYdCpyUf7Ug[5mZ.;5d8w@Moi8RQ90jEmWf/Qy9MQy3e,QbodY9.1vPKbfiB50,8zngA2bE8:ict490w1:WdSB/Z8w_z_t2YNXky9T@ydEL/i8f468DEmRT33NZ0<ybu0yW2w;37SW62A/@9N@KT3NZ?8I5iAY?8n0tcvEyqn/P7JyPzE0an/QOd1lCb/@VmMo0<yd5h6e/Z9ys58yMm3d;i8QR593/Qybe370W7aA/_HyReX.;4y3X218zngA7eysEL/i8D2i8cU07goyTMA74y9NAy9h2g8WcbT/Z8yRgA28D3i8DnWeex/Z8wYgwytxrMSpCbwYvx{glt1lA5lglhlkXI1:i8fIm4ydt2gAW4ey/Z9yst8wPw0t0Cbr2gAw_Q5vO5cyv_ECq7/Qy3N5y9S5JtglN1nk5ugl_33N@4[18yTw8KwE:NZA6@//_@xqE/_ioJ_4bEa:cvq9h2gkW4qz/Z9yTYoKwE:NZEB4913EcGf/QCbvO2W2w;37SysfE8af/QCbvOyW2w;37SykgA6ewcE/_ykgA78fZ1w@53M8;Yvg,CpyUf7Ug[4m5ZDwri8RQ93yW.;4i9Z@yVEL/i8n03UXg.?i8RI942bv2gkKx:18yuXECGb/Qy3@10fxr,0,8yQgAg37SKw8;29TQy9h2gEWcyx/ZcyQgAi8JY9129SAkNOkydj2gMi8RQ92x8ykgAcez6EL/i8n03Uzt:yTMA64ydt2gUKww;18NQgAe<;3EEqf/Qy3@fZQqUJY91OW4:4y9XKyaE/_i8fU_M@5gf/_UI58AQ?8n03UgO//W5Sz/@beezmEL/j8Q5zUT/XAN>?i8QlVUL/QC9Mkyb1lAO0,8zjnGzv/i8IUcs3Eiab/@DP_L/3NY0yNnij;xt9Qy@whE/_yPzEyGb/QOd1vmc/@Vc0s0<yd5pKb/Z9ys58yMkdcw?i8QRDET/Qybe370WfOx/_Fjf/_MYvw}2_;10ey6D/_i8JQ942bv2ggct98ykgA2eyxEf/Kw8:NZEDvW9ew/Z8yRgAi4y5QDh8hj7JpwYvh;j2DGK:g18yTgA28JY9118es99ythc3Qvwj8Dyjg7BW0Gx/Z8yTgA24O9UEDvW6Ky/Z8yRgAi4AVRnb1i8JY90zE5V/_@Cl_L/pF0NS@BE_v/pwYvx{ioJ_cbEa:cvrEUa3/Q69NKDE_v/3N@4[1jKM4;18w@Mwi8RQ91PEn9/_Qy9MAy3e,Q68JY91N8ysp8ykgA2ex2Uf/i8Jk90y9MQy9R@yzDL/i8f488DomYdCpyUf7Ug[45mlrQ1:kQy3X318zngA3ew9D/_i8D3i8cU07h5wTMA305@tAydfpy9/ZcyT08W1CC/@5M7x5i8RI9129MrUw:cs18yuZ8zhkFyv/Wfyu/Z8yuVcyvsNXuyXEL/i8DvW2eu/Z8wYgMyuxrnk5uMMYvx{W3Kx/@beeyQEf/i8QZCor/Qy9Nz70W3eu/@Z.;eL1A6pCbwYvx{kQy3X218zngA7exxDL/i8D1i8cU07hEwTMA705@okybu0yW2w;37Si8B490wNS@yqD/_KwY;2@2gg?8D7cs3E1W3/Qybj2g8w_z_t1l8ys_ExpT/Qy3N229S5L33NZ4?2b1lFa?25M7ku3NY0pCoK3N@4[2X.;eLcpwYvx{W7Kw/@beezQD/_i8IlziY0<yddnqb/Z8yPF8ys8NMexVD/_i8Jc90zHMCqgglplLg4;1ji8fIc4ydt2g4W9Ct/Z8ysd8wPw03Uig:ySMA18fZ.@eL:4ydv2g8W5mw/@5M0@8zg;8JY90MNMbE0,?Lws4?3Ee9/_UfZ0w@4BM;4ydr2ggyQMA2bUw:cs18zhmkx/_i8DLW62t/Z8yTI8i8DKW2ix/@bj2gci8DLcs18zhlMx/_Ly:3EeFT/QybuN18yuUNXuzYEf/i8DvW6is/Z8wYgMyuxrnk5uMSof7Ug[exXD/_yPzEZ9X/QydfmG5/Z8ysoNMexPDf/Lg4;3HM0Yvg,8yQc8i8D7ioD6W2Cs/Z8ysl8xs1Quvp0a0hQqUJc90y@8:4ydv2ggcs18zhnwxL/Wa@s/Z8yuYNOkydl2ggcvrEjFP/UJc90O@8:370i8QlK8r/Qydv2ggW8as/Z8yuYNOkydl2ggLw4:NXuwsDf/WjL/_Yf7U[j8DTW1ys/ZcyvvEU9L/Qy9Nky5M0@5uv/_UJY90zEiVX/UJY90PEgFX/@AW//pF1CpyUf7Ug[45nglp1lk5klrQ1:kQy3X2x8zngA5ezjC/_i8D3i8cU07ggh8JI91h1w_Q4vN@Z.;4y9T@wyC/_i8f4a8DEmRR1n45tglV1nYegi8JU2bEa:cvrEY9P/QybuN2W2w;37SioD4WdSs/Z8yTIoict491w}goD6w3Y03Un4:hj7_i8JX8bEa:cvrEQpP/Qy9Nk63_gkfx7M;18yTIEi8QR0Ej/@z4Dv/Kw0<02@>g0<i9ZUn03Vj03Xr0ykgA2370Wfis/Z8xuRQckm9VkkNV4C9W379grA5:h8DOjiDwj8D@h8DLWdSt/Z8xs1Us7g8ig74ijDIsJmbh2g8xs0fxr8:NXuAh//3NY0Kw0<02@>g0<i9ZP70W9is/_7h2g8}4y5XnmocuTFVLX/P7SKwE;3E59P/Qy3@fYfx2r/_Z8ykgA64Odv2goWhH/_Yf7M3E4VT/UIUw_Ybt8C3_Mgfx83/_@bl2g8xt9R8@xSDf/i8QZ6Eb/XQ1:i8D6cs3EY9D/@C1_L/3NY0h8DTi8B490zEqVP/Qybl2g8yPHHNSqgh8DTcuTElFP/@Bn_L/A5mZ.;5d8w@Moi8RQ90PE@VD/Qy9MQy3e?fxaI;18yPQThw?i8n_t1m@,2w0eyUCL/ics57ko{2bfrsX?25_M@9bM4?8IZFjI?8n_3UA1.?yPSjeM?xvYfytc;2bfo4X?25_M@9Fg;8IZrPI?8n_unKbfnQX?25_TBhi8QZpT/_P7JW6ep/Z8zjRwxv/W5up/Z8zjS7v/_W4Kp/Z8zjSPw/_W3@p/Z8zjRQw/_W3ep/Z8yt_EGVz/Qy3N1y9W5JtMSqgW6Kr/@bfi4X?3Eo9L/Ys53zI?f//_HAMYvg03EiVL/UIZ_jE?cs5SPE?f//@5_M@8sL/_@L1AewHC/_yPT5ew?NMm_ew?//_Un_3Ux8//WY6gW0Kr/@bfqAW?371qcW?3//_xvYfy1X//HMp3EWVH/UIZzjE?cs5xPE?f//@5_M@8YfX/@L1AezbCL/yPRNew?NMlHew?//_Un_3Uz2_L/WY6glky9Vk5nglp1lk5kkXI1:i8fAM4y1Xc:18zngAlex9Cf/i8B49318wPw03Ugu1w?yRMAl8fX0nVhioD7W5Cp/Z9yQY8i8I0i0@@4ky9j2gwZAhg.wfxqQc?23@M9Qdkybh2gMKwE:NZAybu13El9D/UB492N4yTMAb4m5_TAEWN0f7Q?i8Q5dU3/Qy9h2gwi8QZHiw?ezECL/yU<:ykgAb37rj8QZHjA0<OdH2i}pF1CpyUf7Ug[46bfUn_u1B8zngAobEg:WcGo/Z8w_wg3Ujw1g?i8I5Okc0<ybK0,0,8yNmXgM?i8IOi3D@3Uev1g?j8K22<0<S5M0@8tMo0<ydhw58essfwQE60,8avt9yvN8yvLMi0_16Ayb3nR30,8yU40.?jEQQ8QMVY0@3Dwk0<yb5m93;fJB8Fxd8fxbo60,8atx8xs0fzyE50,8yMR3gM?ioD4wbBz.:@4FwI0<ydx2i}i8B4941azhgzjoDBibz////_vU7y/Yf<ybJd4<2?i8Dqwub/MY0i276i2e4Qg.8,8asrMj05x44y5Zw@47MI0<CUPsPcPcPcPcN8zkMAo4y9PQy9Y4y3NM59Z@18yv18MuE3j8QcAAQ1OkMFO8f0c4y3_wB8ytq8h_ZTRAwV@g@3AgI0<y9_Ay9@4wFPAydlLZ8w_E@3UqE2M?ioDMioDVi8Jk941yYvR8rOnxuL/oL7Zi6Yt5TL/QC3Uc1yYvR8rNl9u/_jiD1pwYvh;oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QAVMnnjijDM3Uh_:i8DUh8D2j2D|074UDQ,lxX/_4EnR_x0i}gvr17TgZiofxU4g1OAMFO4xzQAw3l2h0pCoK3N@4[1CpyUf7Ug{@SufZ8w@w1i8f20k28uLZ8es5OWQxzZAw3t2h0NvxTNwo0i8JQ9418yTMA8ewKCv/i8nr3Uiq2g?i8Rc9618ytV9KcTcPcPcPcPci8Df3NZ40,CpyUf7Ug[4y9Y4y3NM59Z@18yv18MuE3j8QcAAQ1OkMFO8f0c4y3_wB8ytq8h_ZTRAwV@g@3>E0<y9_Ay9@4wFPAydlLZ8w_E@3Uou2w?ioDMioDVi8Jk941yYvR8rOlxuv/oL7Zi6YtBTD/QC3Uc1yYvR8rNn9uv/jiD1pwYvh;oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QMVO7njj3D63Uh_:i8DUh8D2j2D|074UDQ,txV/_4EnR_x0i}gvr17TgZiofxU4g1OAMFO4xzQAw3l2h0pCoK3N@4[1CpyUf7Ug{@SufZ8w@w1i8f20k28uLZ8es5OWQxzZAw3t2h0NvxTNwo0i8JQ9418zjQGwf/ctbE@Fb/Qydj2hwib_dPcPcPcPcP4y9PAS5Xg@4Yws;Yvg,CpyUf7Ug[4O9W4y3Nw58Z@tcyux8MuE3j8Q4AAQ>4MFM8f0c4C3_gB9ytm8hLZTRAwVYg@3vgw0<y9ZQy9Y4wFPQydl_Z8w_E@3UqO2;ioDVioDMi8Jk941yYvR8rOnxt/_oL7Zi6Yt5Tz/QC3Us1yYvR8rNl9uf/jiD8pwYvh;oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QAVM7njj3Df3Uh_:i8DMh8Daj2D8ioDUjiD8joRg_QC3@xVScQMFPCbNvOxLhL_4UTR6M074UDQ,lxU/_4EnR_x0O}gvr07TgZiofwU4g>AMFM4xzQAw3l2h0pCoK3N@4[1CpyUf7Ug{@SsfZ8w@w1i8f20k28sLZ8es5OWQxz_Qw3v2h0NvxTNws0i8JQ9418zjSdu/_ctbEuF7/UJY92O5_M@9rwk?37ri8JY933EwF7/Qydpty9S5J1n45tglV1nRT3A4wFSrw}ioDcj0Z8U4ydfsEy?3E1pn/U2U5[fxmw40,dxuhRm0Yv037rWiDW/ZC3N@4{fJA8Fxc0fxug5?23@SgfxaI2?3PA8f30uA1@L/A4yb3uAZ0,8yRMAo4Obp2hEi8K10<0<Wdd2dcev0fwCbW/Z8zogAw:4yb3rMZ0,8ykgAg82VoM4:fxojW/Z9w_M13UgX1w?joDBjonA3Ujb1g?iEQQaQy9S4kNV0Yvg,CpyUf7Ug[6pCbwYvx{i8D2i8f?o7y/Yf?@TB54<;ig7ki3DMtudcyurFm_H/MYv0bI1:Y4wfMhF8yMQTfg0.rM1:Wq_V/Yf7Q?i8Jic4O9M4zTS4y3Ww58yMQjfg?i3DO3UfG0w?i8C12<0<6Y.;4yb3voY0,azggCi3D7sMp8avt9yvNcyufMi0_16kyb3twY0,8yU4g.?i3Do3Udb@v/j8D2j8D0ifvqY4wfIp48.?i8IdHPM?eAJ@v/pyUf7Ug[4yb1pAY?3MwQ0o0kydfhQx?3Em9f/Yq05}6gi8I5ujM0<yby0,0,8esJPl4y9O4wFS4y9h2gUj3Dw3Uco_L/j8DMgoJ_1bEg:j8DKi2D8i8Cc98:18yogAy:4y9j2h8j8BI943Ey9b/Qybj2h8i8fU40@4yg80<yb1h8Y;fJA0Fxc0fxrrZ/@b1q0N;N_XH//_grw1:grA1:Lw8;18NUgAxw=29x2i}yMlHcg?pECY98U;1cyuZCh8C498g;29x2i8:pAi9z2ic:W6qg/ZCwXMAxw:1R6Sq3L2ie[@43f/_@B6_v/3N@[8IZ6z40<ydt2hwKww;3EmV3/Sq3L2ie[@4TfX/@Am_v/3N@[4yb1kAX?3MwQ0o0rI1:grM1:grU1:i8QZL1Y?ezTAv/NvDLM4kNSSq9D2i4:oL5_27@498o;1Ch8Cs99o;1Ch8CA98M;1Ch8CQ99g;36w1g:1yMm5c;yogAw:8I5t3;8C498w;11yMu9x2ig:WPIf7Qg?bH//_Lwc;1cyu_ErE//q499o:1tjtCwXMAxw}fxnk10,CwXMAzw:1R7kyb1ocW0,8yU;g?i8IltjE0<yb4AwVMDeJi8QZZxU?ewNAv/wbwk[@4dfP/Qyb1kQW0,8xs1Q2UJg68ni3Uk90w?i8QZNxU?ew1Av/ctL6w1g}WjfS/Yf7M18yva1UL/3M143Xukkg.?2W.;4ObigxChonij0Z4Qz7iivvOKA:18et183Qv2jon9Kw4;1c3Qjaj3D8j0Z6Obw1:joDcjon9j0Z4UeDf_f/3NZ40,8yMSVeg?i8n9t0ubghy5M7lWi8QZdxU?exNAf/NE0k}eBJ@/_3NZ4?2bfiEL0,8zngAobE8:ict496,:Wdaf/Z8w_z_3UjB:i8QZYhQ?ewIAf/i8IdljA?82U5[fxbI;18xsAfxaI;1cySgAe8J168n0t8rMwSAo0uBY//pwYvx{yPSWbw?i8RQ95yW2:ezXzv/WpD@/ZC3NZ40,8yMnVe;wuf/MY0ct98LL////Z_i2eQS0.803E6ET/Qy3@fYfxmbW/@b1t8U?25M0@4lfH/@wdz/_ctKbeey4zL/i8Il7hU0<yddtpV/Z8yPF8ys8NMew9zL/WizW/_6w1g}j8JA93zFPfH/Qib5ogU0,5xt8fx0L//ELEX/UIUW3ue/ZczgnlsL/Kr440,8zhl8t/_ioD1i8I5KxQ0<yddkJV/Z8yPwNMeyFzv/WsP@/_MwSwo0uDJ_v/pyUf7Ug[4yb1hAU?3Mi8dE206X0w:@4DfD/Qybv2gwi8QRrTb/XI1:Waaf/_FwvD/XEM:pECk98:3FjLD/XAM:pECc98:3FLfv/_18wQ4g0bUM:pECQ98:3F9fr/XEa:cvp8ys_EIEP/UB492N8zgmBs/_i8B4923Fjvf/Qy3@05Q5kC9Nkydx2i}i8B4943FTLD/Qydx2i}i8B49418yX48.?i8Dq3Xq1oM4?87y/Yf<y5ZDV7i8eYQg.8;u3O4M0@5vg;f180n4ggrQ1:WkjQ/ZC3NZ40,8yTMAgeC6@f/i8JQ943F_fr/Qybt2h0WnbR/YfJXhh,;8j0tiN9yvh1Lg4;3F@ff/QkNM37iWkTS/Z5cs0NQKD3Zf/hj79ctbFKvv/Q6Z.;46Y.;eD9Y/_Y4y3gh,WnT/_Yf7M1CpyUf7Ug[5mZ.;5d8w@Moi8RQ90PEeUH/Qy9MQy3e,QhQydfgIr?3EhET/U2U5}1Qc4yb1moS0,8xs1Q4oJg68nit0HMwSwo.Yvh;i8QZShE?ewkzv/NE0k}37Ji8DvW5e9/Z8wYgoyuxrnsdCbwYvx{lrQ1:kQy3X2x8zngA7eyXyv/i8D3i8cU?@4HM;8Jk91O3@w4fzG8;18ySw8i8QRqTr/UBk90N8yu_E6EP/UJk90O5M0@4Bw;4yddgZM/Z8yu_E_UL/Un0tmF8yOSQdg?i8QZfhE?exUzf/wbwk}7gOi8nJt1Gbhhy5M7gjY8dJ6058yOS7dg?3N@[4ydfgAq?3Eh8P/Yq05}3Mi8dJ2058zjTM6g?W2Kc/_7w.;3//_cuR8yt_EpUz/Qy3N2y9W5JtMSof7Qg0<yb1j4R?3Mi8d02063@w9QRuw1yL/i8JX44yb<wfLxvSh5,27i@KwE:NZKwjyL/i8D5i8QZyhA?ez4y/_yqw4:cuTHCSoK3N@4[11lQ5mlld8w@N8i8RQ91PEv8z/Qy9MQy3e,Q3kxzr2gszknZw_w2txWZ.;4y9T@z9x/_i8f4i8DEmRR1nA5vMMYvg,8yTI8KwE:NZKyoyv/i8JX4bEa:cvp1ysrEFoD/QC9NUfZ0M@4Cg;4ybuNx8zjntsf/i8BY90zEB8H/P7ixs1Q7Aybv2g8i8QRhnf/@xZyL/Kw8;25M0@5C:4O9_Ai9Z@xByf/i8fU_M@4pv/_QydreLUi8Jl080W07hnj8R49218ys6@8:370j8D7i8QlFDf/QO9h2g8WcG7/Z8yTQ0i8JQ90wNXuyay/_Wij/_Yf7Qg?bE1:i8D6h8DTW028/Z8w_z_3Ug0//i8D6i8QZbDf/P70cuTEEUD/@DJ_L/pwYvh;Kw4;3FnL/_MYv06pCbwYvx{glplkQy3X118zngA3ewux/_i8D3i8cU07g7wTMA309_7HQ1:i8DvW766/Z8wYggyuxrnk5uMSof7Qg0<ybu0wNZHEa:W428/Z8ySIgi8QRPT7/Q69NAy9X@xqyv/xs1QjAyddvNM/Z8yu_EhUD/Un0t5d8zjlHrL/i8DLW3i9/@5M7hoi8QRoC/_Qy9X@wxyv/xs1Rnki9ZP7JWce8/_Ftv/_Sof7Qg?bU1:h8DTcuTE@ov/@Br//3NZ?37Sh8DTcuTEV8v/@B6//3N@[bU2:h8DTcuTEOov/@AH//3NZ0<y9XAydfrFL/YNMezfxv/WgP/_ZCbwYvx{glplkQy3X118zngA3ez@xv/i8D5i8cU?@4ggc?8dY90M13UU60w?i8J024y9NQC9NKxnxv/i8D3i8n03UjX0w?ZA0E10@4Wg8?379cvp8zhlGsf/i8DvW8W5/YNOrU1:i8Dvi8QlvmL/@xUxv/csC@0w;4y9TQyd5rVM/_EoEn/P79Lwc;18ytZ8zhn6sv/W4O5/YNOrU4:i8Dvi8QlKCL/@wSxv/csC@1g;4y9TQyd5q5M/_E88n/P79Lwo;18ytZ8zhmqq/_W0G5/YNOrU7:i8Dvi8Qlen3/@zQxf/csC@2:4y9TQyd5gFN/_ETEj/P79LwA;18ytZ8zhnmsf/Wcy4/YNOrUa:i8Dvi8Ql9mP/@yOxf/csC@2M;4y9TQyd5nhI/_ED8j/P79LwM;18ytZ8zhmwrv/W8q4/YNOrUd:i8Dvi8QlAmH/@xMxf/csC@3w;4y9TQyd5nlK/_EmEj/P79LwY;18ytZ8zhl_qL/W4i4/YNOrUg:i8Dvi8QlMmP/@wKxf/csC@4g;4y9TQyd5rhH/_E68j/P79Lx8;18ytZ8zhlAqL/W0a4/YNOrUj:i8Dvi8QlF6P/@zIw/_csC@5:4y9TQyd5iVH/_EREf/P7ri8DLW5O3/Z8wYggytxrnk5uMV18zjSdrL/W2i4/Z8zjSJqv/W1y4/Z8zjTUrL/W0O4/Z8zjQasf/W024/Z8zjQ8qL/Wfi3/Z8zjTVrL/Wey3/Z8zjTYqv/WdO3/Z8zjSBrL/Wd23/Z8zjS0r/_Wci3/Z8zjRmr/_Wby3/Z8zjSLqL/WaO3/Z8zjQ8q/_Wa23/Z8zjQ@rf/W9i3/Z8zjQVqv/W8y3/Z8zjQDrv/W7O3/Z8zjQXqv/W723/Z8zjS7q/_W6i3/Z8zjS4qL/W5y3/Z8zjQ@qv/W4O3/Z8zjS8q/_W423/Z8zjQsqL/W3i3/_FWvX/MYvw}1cyvvEM8b/QO9Z@y8wL/i8D3i8n03UnX_f/A6pCbwYvx{KM4;3FILX/Sof7Qg0<y3X0x8yPSt4M?Lw4;3ECUb/Qybfpgj?2@.;eyawL/i8IZyNc?bU1:W7C2/Z8yPS24M?Lw4;3Eq8b/QybfnAj?2@.;exnwL/i8IZs1c?bU1:W4q2/Z8yPRD4M?Lw4;3Edob/QybflUj?2@.;ewAwL/i8IZlhc?bU1:W1e2/Z8yPRc4M?Lw4;3E0Eb/Qybfkcj?2@.;ezNwv/i8IZexc?bU1:We21/Z8yPQN4M?Lw4;3EPU7/Qybfiwj?2@.;ey@wv/i8IZ7Nc?bU1:WaS1/Z8yPQm4M?Lw4;3ED87/QybfgQj?2@.;eybwv/i8IZ11c?bU1:W7G1/Z8yPTX4w?Lw4;3Eqo7/Qybfv8i?2@.;exowv/i8IZWh8?bU1:W4u1/Z8yPTw4w?Lw4;3EdE7/P70i8f42cc+/////ZMSM=4-g+1-I+>=184M=w+o0Y=9+1w+5M=2E8w=8+Q0k=k-s-M=2MZw=o+Q0c=b+1w+1g=>3+E+egk=p+53t=6M+8+1E+idQ=s-w+Yf/rM:2G4g{fX/SY}p18{3/_ZL[8+3+2giM=Q+w4I{3R_LZL}3w3~~~(0c5=>k~~~~~~~~~f/////////////}f/////Xjk=PcM#2Id=a0W!0wS=a3o!wjk{2edg#>d=1gU!cwU=CPc!K3g{2mcw#1qdM{7oS!fUT=v38!F3g=8dM#1HdM{5wU!8EP=d3k!LPc{1qdw#2ge=>P!fAS=o3I!Y3s{3Hcw!Oe=dMT!cwS=Ujc!jzo{2Oe!23dw{8YS!cwO=o38!ejA{3adg#3Ad=736+g=20Xw{3cP~IPc{2gI+4+EeU{2wew`1cR=QaU=1+c3K=a3o`2Zcw{535+g=3wXw{8UR~ZPc=gHw=4-eY=ke~eUQ=oaQ=1+23L=CPc`2mcw{12J+g=10XM{9oO~tzo=wGw=4+oeY{1Sdw`7MO=QaA=1+83L=v38`1Rdg{f33+g=2wXM=wT~cPg=gGg=4+MeY{1oe~cUP=Maw=1+e3L=d3k`1Fe=72E+g-Y=5ES~xPw{3gF+4+8f+scM`a0T=wag=1+43M=o3I`3Hcw{42A+g=1wY=eIO~T3s=MMw=4+wf=3sdM`dYO=Ic8=1+a3M=Ujc`3le=12Q+g=30Y=b8U~JPs{3MEM=4+Uf=2fdw`60O=sb8=1-3N=o38~QdM{a2z+g+wYg{cER*1USM#]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=I4I{]{b1b=2:1{g?hQ4A0jdxcg20iM{8Rb=2:1{g?hQ4A0jdxcg2giM{7Bg=hQd3ey0EhQVlai0NdiUObz4wcz0Odj4Ocj4wa59Bp218ongwcjkKcyUNbjkF06RLr6gwcyUQc2UQ82xzrSRMonhFoCNB87tFt6wwhQVl86NAag;2VPq7dQsDhxow0KrCZQpiVDrDkKs79Ls6lOt7A0bCVLt6kKpSVRbC9RqmNAbmBA02VDrDkKq65Pq?Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bClEnSpOomRB02VBq5ZCsC5JplZEp780bD9Lp65Qog0KsCZAonhxbCdPt34S02VOrShxt64KoTdQcP80bD9Lp65QoiVPt78Nbz40bD9Lp65QoiVPt78Nbzw0bCpFrCA0bCBKqng0bD1It2VDrTg0bDhBu7g0bDhAonhx02VQoDdP02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpCBKqlZxsD9xug0KqmVFt5ZxsD9xug0KsClIsCZvs65Ap6BKpM0Kp65Qog0KpSZQbD1It?Kt6RvoSNLrClvt65yr6k0bC9PsM0KpSVRbC9RqmNAbC5Qt79FoDlQpnc0bCdLrmRBrDg~~(0b:>:8+U08{3w0w{3%8^7w:s:2+103=40c=A^1^34;3S/ZL0w+U0M{3w3=C-4-w^X:2M:8+Q0c{3g0M{a08=1g:4:8+1w+gM:c:2+70c=s0M=V1g&g&4I;3/_ZL0w=2G4g{aEh=K-4-8-w=1o:_L/rM8+p18{1A4w{e-1g:8:4^pM:g:2+4wj=i1c{1w3M=g+2-o+74:4:gw=2E8w{awy=Q0k=4:7M:w+6+1X}g:8+u2w{1Ua=7g7&8^xg:4:2+eML=X2Y=s.*1^9c:1}w=10cg{40N=M^4^2r}g;18-38+cw{3%g+1-Gg:4:i+40O=g38=w^8-w+bs:1:cw=1wcw{60O=@go&4-g=36}g;38+o3A{1weg{202&8-4+Rg:4:6+81b=w3I=d^1^dI:1:1w=2giM{90X=6M^g&1S}g:o+I4I{2MeM+4&g^Ug:4:6+b1f=I3Y=8^4^eE:1:1w=30jM{c0_=EnI*4^3M}g:c4=qdI{1EKM=w^4^ZM:w:31=73r=sbI=d^2^fQ:1}M=>SM{72X=2%w^a.0,w:c+udI{1UKM{d,=1g+8+1-4M4;Y:3+4zt=ibQ=8^2-8+1Y1;e}M=1gTg{52Z=2%w+2+3B}g:c+mdQ{1oLg{fw^8^aM4;w:3+53u=kbU{2M.&g&3E1;1}M=1wXw{62@=k0w*2^10.;g:c+Ifo{2MNw=w2&8^ig4;4:3+bzU=Kcw!2^5A1;8}M=2U@=bz8=9%w&1u.0,M%;2UO=4w^4^t<;4:M%cA{1k%g+1-4:3$5j9=vg4&4&')


_forkrun_bootstrap_setup --force

