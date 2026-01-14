#!/usr/bin/bash

frun() (

    # # # # # SETUP # # # # #

    local test_type worker_func_src nn N nWorkers0 cmdline_str ring_ack_str delimiter_str delimiter_val
    local -g pCode fd_order fd_spawn ingress_memfd nWorkers nWorkersMax 
    local -gx order_flag unsafe_flag
    local -ga fd_out args P

    : "${nWorkers:=1}" "${nWorkersMax:=$(nproc)}"

    # export vars to tune workers
    export nWorkers="${nWorkers}"
    export nWorkersMax="${nWorkersMax}"

    order_flag=false
    unsafe_flag=false
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

    # setup loadables if needed
    _forkrun_bootstrap_setup --fast

    # initialize rings with ring_init and create data memfd with ring_memfd_create
    if ${order_flag}; then
        ring_init 'fd_out'
    else
        ring_init
    fi

    ring_memfd_create ingress_memfd


    # # # # # MAIN # # # # #
    {
        # # SPAWN "HELPER PROCESSES" # #
        # these keep the worker pool fed

        # start ring_copy to populate memfd with data from stdin
        (
            ring_copy ${fd_write} ${fd0}
            ring_signal
        ) &
        COPY_PID=$!

        # start ring_scanner to scan memfd for line breaks
        ring_pipe 'fd_spawn_r' 'fd_spawn_w'
        (
            exec {fd_spawn_r}<&-
            ring_scanner ${fd_scan} ${fd_spawn_w} "${delimiter_val}"
        ) &
        SCANNER_PID=$!
        exec {fd_spawn_w}>&-

        # start ring_fallow to remove already-consumed data from memfd and free memory
        ring_pipe 'fd_fallow_r' 'fd_fallow_w'
        (
            exec {fd_fallow_w}>&-
            ring_fallow ${fd_fallow_r} ${fd_write}
        ) &
        FALLOW_PID=$!
        exec {fd_fallow_r}<&-

        # (if enabled) start ring_order to reorder output to the order that running inputs sequentially would have produced
        ${order_flag} && {
            ring_pipe 'fd_order_r' 'fd_order_w'
            (
                exec {fd_order_w}>&-
                ring_order ${fd_order_r} 'memfd' >&${fd1}
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
) &
P+=($!)
}'
        eval "${worker_func_src}"

        # spawn initial workers
        nWorkers0="$nWorkers"
        for (( nWorkers=0; nWorkers<nWorkers0; nWorkers++)); do
            spawn_worker "$nWorkers"
        done

        # spawn additional workers dynamically
        while true; do
            read -r -u $fd_spawn_r N
            [[ "$N" == 'x' ]] && break
            nWorkers0="$nWorkers"
            (( ( nWorkers0 + N ) > nWorkersMax )) && (( N = nWorkersMax - nWorkers0 ))
            (( N > 0 )) && for (( nWorkers=nWorkers0; nWorkers<nWorkers0+N; nWorkers++ )); do
                spawn_worker "$nWorkers"
            done
        done


        exec {fd_spawn_r}<&- {fd_fallow_w}>&-
        ${order_flag} && exec {fd_order_w}>&-

        # wait for everything to finish
        wait

        # # CLEANUP # #

        # destroy the rings
        ring_destroy

        # close the fd's
        exec {fd_write}>&- {fd_scan}<&- {ingress_memfd}>&-

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


declare -a b64=([0]=$'116366 58184\nmd5sum:22cfa65e489efcf8b73cf3e66669f182\nsha256sum:bdcc8f34b24f1fcfae488ca6a5ea58817985b13c5b99d72df49cbd771a3cd7af\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n00000000\n0000000\n4ybe37\n000000\n00000\n0000\n000\n04\n00\n0g\n__\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\034vQlchw81?=.c0fw01+1=czr=,4.e.b>.7w0t0><5!:8o{xw=g{g<g;A{2g{9[2ge[90U{1{1<1w<zd[2dQ[8Tg}4wd[s0Q{4{8<6<acQ[ETg}2zt[Q>}3g?[w{1;g,2E0w}aw2[G08[A{2g{1=4<1<a2_[EbY}2wLM}3=c=8=s<4<2cQ[8Tg[zt[1=l=w{k@lQp?,2wLM}a2_[EbY[M{3=2{1gVnhA1<d2_[QbY}3gLM}2g1[9>[4{57Bt6g6~-.1=kKlQp?<8Pg[zt[2dQ}3U0w}fw2{g{4<5;c,17jBk0Z_oG4TK74XzPUxxS_n6ZtwvfYt7P3NXWi8fI24yb1pTs.18xs1Q0L_gi8f42cc=03_dvHs.3_9vPs,f7Q._OnWT,q;3FUf//YBYJM.6w1<Wt3//_9uHs.1E0w,eD0//_OnyT,q0c,3FIf//YBSJM.6w4<Wq3//_9tbs.1E1g,eCg//_OnaT,q0o,3Fwf//YBMJM.6w7<Wn3//_9rHs.1E2<eBw//_OmOT,q0A,3Fkf//YBGJM.6wa<Wk3//_9qbs.1E2M,eAM//_OmqT,q0M,3F8f//YBAJM.6wd<Wh3//_9oHs.1E3w,eA0//_Om2T,q0Y,3FYfX/_YBuJM.6wg<Wu3@//9nbs.1E4g,eDg_L/_OlGT,q18,3FMfX/_YBoJM.6wj<Wr3@//9lHs.1E5<eCw_L/_OliT,q1k,3FAfX/_YBiJM.6wm<Wo3@//9kbs.1E5M,eBM_L/_OkWT,q1w,3FofX/_YBcJM.6wp<Wl3@//9iHs.1E6w,eB0_L/_OkyT,q1I,3FcfX/_YB6JM.6ws<Wi3@//9hbs.1E7g,eAg_L/_OkaT,q1U,3F0fX/_YB0JM.6wv<Wv3Z//9vHr.1E8<eDw_v/_OnOSM.q24,3FQfT/_YBWJI.6wy<Ws3Z//9ubr.1E8M,eCM_v/_OnqSM.q2g,3FEfT/_YBQJI.6wB<Wp3Z//9sHr.1E9w,eC0_v/_On2SM.q2s,3FsfT/_YBKJI.6wE<Wm3Z//9rbr.1Eag,eBg_v/_OmGSM.q2E,3FgfT/_YBEJI.6wH<Wj3Z//9pHr.1Eb<eAw_v/_OmiSM.q2Q,3F4fT/_YByJI.6wK<Wg3Z//9obr.1EbM,eDM_f/_OlWSM.q3<3FUfP/_YBsJI.6wN<Wt3Y//9mHr.1Ecw,eD0_f/_OlySM.q3c,3FIfP/_YBmJI.6wQ<Wq3Y//9lbr.1Edg,eCg_f/_OlaSM.q3o,3FwfP/_YBgJI.6wT<Wn3Y//9jHr.1Ee<eBw_f/_OkOSM.q3A,3FkfP/_YBaJI.6wW<Wk3Y//9ibr.1EeM,eAM_f/_OkqSM.q3M,3F8fP/_YB4JI.6wZ<Wh3Y//9gHr.1Efw,eA0_f/&4ydfkDz.18zgl2UM.i3DUt1l8yMn@RM.i8n0t0D_U0Yvw;333N@:4ydfhDz.18zjkiUM.i2D@i8DMic7KfQz1@0d80sp8QvVQ54yb1mTo.18xs1Q2f_wpwYvh,MMYvw;3P3NXWw3TlUw,7kHlky3flbo<i8DBt0N8zjSeRg.W0D//Epf/_Yo5Hu8,5tMMYv0ccf7U:YMYu@KBT//3N@:4y5_M@41M80>5mgll1l4C9ZbVr<lld8yvJ8w@MwW1LY/Z8ysl8xs1Q3Qy9T@zH@/_w7M3_RRQ74y3N21cyup8ytYNQBJtglN1nk5uWiLZ/Yf7M19yuV8wYk1iiDuioR@0uxl_f/i8Duj8DOioD5i8D7WfjY/Z3NAgR.18yu_EBLL/QydkfZ8yst8yggAi8Bk90zE8vP/Qybl2g8i8DKi8D7i8D3WbXY/Z8yMMAj8DLNAgb_M3EnvL/Qydu07EZfL/QO9XAy9N@zF@L/i8Dvi8D5W3XX/Z8znw1WdnX/Z8ytV8ysvEOLH/QO9VQC9NKwv@/_i8RU0uyS@/_j8DCi8D7WaLW/ZcyuZ9ysjEgfL/Qy9T@wU@/_i8DLW13W/Z8xs0fxdY,2bk2zSMA1RnUfy10@4Hw,4z7h2go;ew8@L/i8RQ91yW2w,4O9ZYs:4y9M@wJ_f/i8D6i8J491x9espQo80U07lrwPIyt5oNOkO9UAy9X@x9_f/WNIf7U:hj70j8Dxj8DOi8DKi8D7W4PZ/Z8yu_EFfH/QO9Z@ys@L/i8f484O9VRJtglN1nk5uWozW/Yf7Ug:4O9ZAydfsWO,NMeyv@v/WY4f7Qg0>y9XAydftCH,NMey7@v/WWAf7Qg.ccf7U:i8DLW73W/Z8yuV8zjSmGM.i8n03Uk6//WYZCpyUf7Ug:5e_Mw,4y3X43E4vP/Qy5M7Uci8f4g5L3pwYvh,i8QZwr8.37Scs3EIfL/UD7xs1UarEv<i8RQ9229h2gcW7vW/@bv2gci8A49ewW@L/i8Ik94y5QDYxLXY,3EJ_L/Qy5M7Vqi8f4g4z1U0drMMYvx}NAgk8018zngA6bEa<i8RY923EN_z/Qybl2go3Xoiw@bvwfFbt3Z8ys58Mu4kwfFdi0Z4Mky5M7izWlf/_Yf7U:LY8,3EjLL/Qy5M7@nK,g03Fc//MYvw;18Mu0aWYBCA5d8yvJ8zjSNGw.i8fIkeyc@L/i8n0t5u0e35RkE1U?1RjbG.g.LE8?g18zjSuGw.cs3EJfH/UD2xs1V7HG.g.LE8?g18zjS9Gw.cs3EBLH/UD2xs1Um4y3N529Q5L33N@4:2W0w,4y9THY_?.cs3EHfD/UD2xs1VRKyxZ/_wPwmtp0NQAy9THY_?.cs3Ey_D/UD2xs0fy7n//HHMYvw;35@mY5Ub80>ydv2ggibwKm5xom5xo>y9v2g8i8B49235@nZ4913E_fz/Qybv2g8xs29MDwpylgA2ex8Z/_yRgA2eBv//3N@:cnVrMmwIw.NQgA85xom035@nZ4913ELvz/Qybv2g8xs29MDD1WiT/_ZCA6pCbwYvx}glt1lA5lioDRglhlkQy1X4w4.29f2h8zjS3Gg.W3TV/Z8xs0fx1M1.20e34fxeI1.18zjlPGg.i8D7W7PU/@5M0@5_<4yb1lTj.2W6<bU1<i8QZkaA.cs5QJQ,4,18yMzEGLD/QObfrLt.1dxvYfxtM,15csAN_Q6U//_XAx<Kwc,2@012w0eyr@f/i8fU_M@4CgE.37SKw?E018yst8yglUTg.W6LT/@_l<ewx@v/i8QZ0aA0>y9M@y2@f/i8n0t1CW2w,37Si8D7W3XU/Z8ykgA24y5M7Yii8nrgrM1<j0ZfUQO9p2g8i8QZPqw.ex6@f/i8n03Ugd?.cvqW2w,4y9N@z@Z/_i8n03UXR<i8B4913FZ;Yv>ObfuDs.371uvs[jon_3UgA//iss7;4yb1szs.18NU,g}4yb1rrs.36w1w1<i8I5GdM0>z7g1:i8I5CtM0>z7g2:i8I5yJM.cp0a018yMl_T,ict0c;18yMlMT,NA0F>yb1mns.2bfg_k.18NU0>2}8n_uhUNM4y1N4w4.1rnk5sglR1nA5vMMYvg02bfubj.2W.g0>ydt2h0W7LS/Z8xs1_VKLc3NZ.81U?0fx2b@/_F1LX/V18NQgA4>,18zjSHFM.W1LT/Z8xs1Q7z7SKwE,18ysvER_r/Qy5M7Uai8B491zH30Yv>z7h2go01,b@_<W7nT/Z8xs0fzCM8.1czjh0is7K0z7_W5TT/Z8ysd8xs0fzJ48.18yMmGQ,i8IEi8JZ>y5_M@4Hg80>kNV0Yvw;3EW_j/Qybvgx8wYk8joRA1058xvZRWrQ0o,j3Dz3UZX0w.i8QZ2qs.exLZL/i8D3i8n03Ujz1M.w3xc3Ukq0w.w7w1cw@5408.81U0w0fxgo2.18yNQnSM.i8J490x8yocE?.i8J49118NUcM?,g,4y9wO01.18yQgA64O9IR01.18yocU?.yMgAicu3g>}18NUdo?}cq3o>,36wSc1<w_w13UVp2,ict490z//_joRB28fE0Az712j//_joRINh1cyulC3N@4:18yRQ0KwU,18zjl7Fw.i8DvW4zP/@5M0@4K>.bEb<i8QReGo0>y9T@wIY/_xs0fx6g5.2W2w,4yddiGC.18yt_E4ff/Un03UhU1g.KwM,18zjkpFw.i8DvWfjO/@5M0@4B0k.bE9<i8QR2Go0>y9T@zoYL/xs0fxaw5.2W2<4yddvyB.18yt_ELfb/Un03Uh41w.KwM,18zjnBFg.i8DvWa3O/@5M0@4C0o.bE9<i8QRRGk0>y9T@y4YL/xs0fx5g5.2W2<4yddsiB.18yt_Eqfb/Un03Uh01M.Kww,18zjmNFg.i8DvW4PO/@5M0@4fws.bEa<i8QRDGk0>y9T@wMYL/xs0fxco6.2W2<4yddoSB.18yt_E5fb/Un03UkF1M.i8I5btA0>z7w5w1[Wpk<f7Qg0>yddtyA.18ytZ9yuXEzLf/Un03Ujw_v/KwE<NZAy9T@z7YL/ct98xs183QDgioDmWs3Z/ZC3NZ4.1caud8ytx8Mu>i2Doic7U14yd1418Muw2i8D5WmjZ/Yf7U:cvp8znIeKwE,3ECff/Qy5M7Uji8IlBdw0>y9wyw1,f7Qg0>y3Ngx9euQfxvfZ/Z8yMgAi8Itsdw0>y5M0@4FMg,@9ggg0>y3v2g8.@edgg.cq3o>,76wSc1,1j8JQ90xcyrcM?.cuRcyrcU?.j8CPi>,Yv>Cbf2iW2g,4yddo2A.3EW_3/Un03Vj0iof420D5jjDBttJ0xeRR2Qz7wRw1.3//_i8Kb8>0>ybAOw1.36wS81,13Xq3o>0>wVQg@kwS41.24M0@4Z0c0>z7wMw1,1<cv@@?w80ey6Y/_cv@@?w808A5isY.exQY/_cv@@.w808A5cYY.exyY/_cv@@?w808A57sY.exgY/_cv@@.w808A51YY.ew@Y/_i8QZ3YY.8A5YsU.eycYv/xs0fy5g2.2bfvre.2W.w.bU4<cs3ELvb/UIZUYU.bE02,cs2@1<eyCYL/yPT8Pw.Kw4<NMbU2<W8_O/@bfrne.2W?,370Lw8,3Eufb/UIZDIU.bE.1.cs2@1Mg.exxYL/yMRXPw.Ly;NM4yd5juz.18znMA8ey3Yf/ct98zngA84ydfiaz.3Ewf7/UIdhIU.bUw<cs18zhk6EM.i8RY923EkL3/P7ii8RQ9218zjQ0EM.W4_N/@b3h7e.2@8<370i8QlRq80>ydv2gwW27M/YNQAydt2gwi8QZTq8.ewuYv/yMTsPg.Ly;NM4yd5qiy.18znMA8ezMX/_ct98zngA84ydfsay.3EXv3/UIdFYQ.bUw<cs18zhlPEw.i8RY923EL@/_P7ii8RQ9218zjSCEw.WbPM/ZdxvYfx8LV/Zcyv_Eq@X/QC9N4y5M0@490c.fp0a?fx183.18yMmSRg.i8KUa>0>z1VMbELK/_QC9Nkyb1pPl.18wXwE?<@4Rw8.37ri8RI943HiwYvh,goB4Dg29Mkyd5uix,NMbUw<i8DLW2LL/Z8ytUNOky9WAO9VQy3MM7EJ@X/Qyb1kzl.18eVwE?.3Ue30w.i8QZ0G8.eyTZv/xs1VGUnrt218oZJcyuR9zlOt.Yvg02bvg18wYk4W3jL/Z8euJRXQO9X@yTXL/3N@:bw1<Wq3U/ZC3NZ4,NZAyduMKW2w,ezgX/_i8n03UV7_f/i8IlOdg0>y9wy01.3FdfP/MYvg.NZAyduMGW2w,eywX/_i8n03UUn_f/oLbZ27P0i8I5AJg.cnVvU0w?.WvTX/Yf7Qg.37Si8RX3bEa<W6zL/Z8xs0fzJ_X/Z8yNlwR,i8C2e>.eDc@/_3NZ.37Si8RX2rEa<W3zL/Z8xs0fzG_X/Z8yNkMR,i8C2c>.eCs@/_3NZ0>ybwO01.1cyXcM?.i8B49118yUcE?.i8B490x8yUcU?.i8B491x8yQMA2cq3o>,18ekMA40@kwS41.1ceTgA60@kwS81.1cyrc8?.WgLY/Yf7Qg.cq3o>,76wSc1,1i8dY90w03UVA@/_WlHX/ZC3N@4:18znI8KwE<NZKxwXv/i8A494y5M0@eY_H/SbO_gxYM4yb1mXj.35@n@0c>.eDp@L/pwYvx}ijDKj0Z7ZuAK@f/3NZ.b_2<WfrK/Z8xs0fzU7T/Z1Lw.1w3FvLv/Sqgcvp8znIcKwE,3E4eX/Qy5M0@ex_H/SbO_gxYM4yb1gbj.35@D@0i>.eBJ@L/3NZ4.3EE@L/UIUW0PL/Z8zjRODw.i8D6cs3EK@L/@Dm_v/pwYvh,Lg.603Fq_v/Sof7Qg0>O9X@xEXf/WlLS/Zcyv_Ei@T/QO9_@y3Xf/ioD4i8n03Uni_f/WpbZ/Z8yMS3Qw.i8RX2HEa<cvp8ykMA4ex6Xf/i8Jc9118yo5o?.WtnV/Yf7Qg0>6@?,eBo_L/3NZ4.18znI8KwE<NZKwgXf/i8B490zFFLD/XEa<i8RX237SWfrH/Z8yNknQw.i8C2g>.eC3@v/KwU,18zjlhDw.i8DvWc_G/@5M7kji8I5Xd4.cq0oM4,7FmfD/XE6<i8QRdpU0>y9T@yAWL/xs1R2kOduMrFd_D/U0XbkMfhvLFa_D/SpCbwYvx}w_Y13UUD3g.gluW2w,45mgll1l5l8yvljyvJ8wuNo?.i8J@237SW77I/@9h2gsw_I23Ukl1g.NEgAV;37x2jk<//_Qyb1lbh.18NMk_Qg}4z71iPh[i8Koc>0>y9n2gUi8Koe>0>y9D2jE<i8Ko8>0>y9n2hgi8Koa>0>y9D2j;i8Kok>0>y9n2hoi8Kog>0>y9n2hwi8Kom>0>y9D2jo<3Xqoo>.8ys9d8<fJFxy?.y9MAUg<@SC641.3Ej_3/XU.2.ic7E0Qw5/Yv>wB.3w_Qy9NXw<2i3D7i0Z7@bw.2.i3D7i0Z3NQydL2jU<i8D2i8B4933EyKP/QObL2jU<xs0fxj4r.2bv2gsKw4<NZAOdJ2gg?.W4bI/Zcyvq_1w,4O9t2h0i8B490zEq@D/Xw3<NebXZVgA6>0>yUP_tjUWmrN218Z@98qoMA4>0>123M18MuE4i8Q44ky9h2hMi8I5ZYY0>z7w.1[i8I5VsY0>z7:18yMnnPM.ict0c;18yMn8PM.i8Jc9518ykw8i8n9t0W0L2jA:@55x40>y3v2ho>S9_g@Sx2ji<NEgAy:fBogAU<8jrj8DX3Vi49e8<ax2jx<y8gAQM,4ybh2g8icu49b=i8B494x8NQgAa;18NQgAu;18NUgAw{18NUgAA{18NUgAC{18NQgAq;37x2ic{ct491:3Vi49ec,15cuh9etR13Vf6csB42HgAy;@5m1M.82Y9d8;3Ujy<i8J49618zn3_i3JQ92wfwGMa.143Xpk9119ytJ8yQgAe4QFWQ63Uw51w_81ijD33Ueq0w.jonr3UhN0w.i8IRAIU.8dY91013Ugv2w.yQooxs1Qa4y3L2jo:@42gE.7Uni8eY9b:3UmU4w.3N@4:18yTMA24O9W4y9PkMF@4Odd3ybv2gsct9cyvrEceH/Qybl2gMyTMA74O9_Kx_Wf/i8n03UWW2w.j8BQ90x8yuB9zhM7joDZNQgA4;15cvq0L2ji:@57L/_Qybh2gUi3D13Ud82,i2D8ioD0i8J49618zn3_i8n03Ukm?.h8yQ98w,19etQfwO0v.18NYr//_grU8<j2JQ94xc0TgA24O9v2gwi8Cc9a<1dyvsNXkS9NAy9J2iE<h0@SF2jw<WOAf7Ug:4y3M058wYk1ioD5iof724MVZg@3A0s0>wVS0@3xMs0>y9SHUa<j8DLj2DGW8PD/Z8xs0fx8c8.18xuQfBs948e9QK4ybv2gwi8f.ky9NAwF_AM1_AwVt2hosWd8yUMAE<4w1r2gEgoDkioD_i8KQ9aw,180uB9etR13Vb6pyUf7Ug:4wXt2gEsS98xsAfxn4b.15xfpQsIt49101<i8dY93w03Uij2,j8J493x8yQgAo4wHh2gEijD0j0Z7M4y5M0@5k0w0>AVTki8J2i8<NQgA4>,113Vb6hj7Ai3JQ92xODw@Sh2ggw@01ysa3Yw512tp8xsAfxqc9.15xfpRiky9j2ggWm43.18yTQgKwE<NZKw_V/_yogAR<fvgMuwvyogAV<eDm@L/3N@:4AVTk4fAIp52dofx.8.23v2gg?@49_T/@CM_v/ioD3ioR41g18NUgAI{18yPnJOM.i8C49a<18etwfAEgAy<4ybh2g8jiDZj8Bs9219zmM5>m9RkM1TuJ33N@4:18yTowi8I5FsI0>yb5prb.18ys58av58wvD/MY03Urr<i3D2syq_p<ezYV/_i8IRvsI,@Shyy4M7mZi8ISWXMf7Ug:4yb1m7b.18yR08i8IljII0>y9A.1.18yMl0OM.i8A5csI0>yb1jHb.2bg1y5M7iBi8JQ942bft32.2W2<4z7x2gg?,g,exqVf/i8fU_M@5uL/_Qib5gDb.15xt8fx6H//EG@f/UIUW1jD/ZczgnLBM.Kkk2.18zhnkBM.ioD1i8I5hY,4yddjyt.18yPwNMexmVv/WiL/_@gi8R80kObn2gwi8IRGcE0>m9WAy9PU7D/Yf>y3v2gU?@4i0k0>Obh2h8i8CI_w?80193XHEfOn/MY0j8C4Nw?8018ygRyOw.i3Da3U8V1g.i8J495142FgAy<4i8J2i8<j05s94x8ySMAs4y9x2iE<i8K499w,18wQgAa05cyWMAE<4y9x2j8<i8K499<14y5gA84y9x2iU<i8d496w1i8Jc96x8wQgAu054yTooi8KY98<1cyQgAk4Gdh0s6id7Lid7EhonSi0Z4NQy9x2i;wbMAQM<1RgrE4<iEQ4xg<18et183Qb2yVgAz<8ni3Un61,i3D1K;183Qb1i8B496wfAY0fJI29x2ic<i8JQ942_1w,eyFUL/K0c,34ULLTB2go?.ibzfZRfzFpL484zTUAxFz2gg?.g48f>z1Wwh8zgghi8B49718aux8fowj,fxNk2.18yTMAk4wVv2hU3Uc50w.i8BI9720v2gw.@54fH/U2Y9d8;3UnD1,ict491:i8JI911cyuZ9etRO4KIK3N@:4ydu058etZP6ky9SHUa<i8f50kwF@KwbU/_i8n0ttV8ymMA44Ob1qb8.18yMSzO,j8D7ijD83Uaf2w.yUgAR<8n03UDV5,j8JI94x8yjRYO,j2JI90xceSMAc0@3uNk0>Q1_kz7h2ho?,4ybh2gUi8n0t2V8w_zZtOx8wY02ctbPi0@ZQbx1<at2WfM,4yoYQwfLs0FMAxzMAy9h2hoi8I5asw0>y9u318wTMA4.fx>4.18yQgAe37ihj7AiftQ95x8ykgAo6qgpCoK3N@4:18yTMA44ybj2gUct98yvV8ysxcaup83W_6ifvTi3Jc95wfw@Af.18xs2_?,4wfhvx8yngAk4kNZAy9v2gwWPlC3NZ4.18ytFcauG@2w,4O9X@zBUv/i8n03UiI3,iof60kOdq05ceTgA80@3WgM0>Kdb3h8eSMA40@3@wM0>AVTnaZjoDFyTMA737ijiDVj0dc90xcysVcykMAaex7U/_i8Jk932bv2gsj8D@W9rx/Z8xs0fzHQc.1cyQMAa4y9MACd70tdyvRcykMA2eBO//3NZ0>ybdh77.18yQogi8JY9518yogAA<4yb1uD6.18yogAC<4wXL2j;3Ufr<wbMAUw;fxcQ,18yNq0L2jx:@4Fg,4yb1rn6.18at18essfwYU,2V?,4m5Zw@5M<4w1j2hgi8KQ9c<18yTMAk4y9Y4wHx2iE<i3D@i0Z2_AwfgIx8ynMAk4y5OnhFwbMAV;1QnQybv2h0i8Qldpc.bV;cs3E5@3/Qybt2h0yXMAR<4xzQey3T/_i8fU_M@4Ohk0>yb1iH6.18yQMAk4y9i0zH94ybx2ig<i2K49bw<fxlc9.2gi8K49aw,18ykgAk8eY98M<2tgW0L2jz:@5n0w0>z7h2hU;eCZ_f/3NZ4.18yUMAE<4w1r2gEj8JY9218yXgAG<4w1WkwVS44fAIp5cujFLfz/MYvg018yQgAo4y5M0@5ow40>z7NL//Z5xegfxsMm.2bh2ggh8yQ98w,29MEfw0ofy0ky3Yw59yt19etQfwYU,24M0@4DLv/@D1<pwYvx}i8CI_w?8018wTMAi.fysfW/ZcyQgAieCI@L/pF18yQo8yTUoxvYfxaE2.18yMkaNg.i8C60>0>yb1vP4.18ygnJN,i8I5ZIg.8J068n03Umw2,i8IRVcg.eB@@L/3N@:8eY98M<13UhD4g.NUgAz;8,3FeLL/Sqgi8Kc9a<1cyTMA84ybJ2iE<wTMA4>fx9If.180mMAa4w1WkAVTk4fAIp5cujFCvv/Sof7Ug:bw1<MSoK3N@4:18ypMAE<cq498w;WnDU/Yf7M1dxs0fBc15xehR28j03UmX_L/h8yQ98w,3FOvX/QydsfZ8yQgAo4kNM4wHh2gEWn7T/ZCA4O9WAMF@Aw3l2g8i8I5_Ic0>yb3v_3.183XHGfQy9NAy3M061VL/3M18ygnuMM.i8CkYg?8018yo4.g.i8I5Qcc.cp0ag58yMn5MM.yQ0oxs0fxh4e.2bx2jk<xs0fyqI4.18yTgAg8IZhbI.bE8<icu49101,_gwY0Wdbs/Z8w_z_3Uia3g.j8D_W23s/Z8wsho?.cs1rnk5sglR1nA5vMP70cta@0w,4z7x2g6?}6q9x2ge?.yMnxKw.yogA0>.bw1<pEC49?1.2b1seW.29x2g8?.K>,1CyogA3>0>ydx2g.g.i8D7i8B4923ElJX/Un0vwXSx2ge?,g@5WMs0>yb1un2,fJE0o?.xc0fx0Me.37h2gg?,4y9WkkNZKDtY/_i8IRLc8.8J@64wXj2gU3Vf22t142e0fxoAh.25_Tgyi8KI9dw,18xuQfx7gh.1@3Qy3L2iM:@50x40>m4Zw@45Lr/QkNVeAnZf/i8n0LM4,19ysx83QnUi8I6j8QcLg<19as19zggVi070ijD03UeP1,i8Q4fQMVM7cwi8D8it7Ei2Dgj3D0igZ7M4C9@4AFM4A1O4wVNQAfgIx8esEfwW_T/Z8yoU.g.i8AdYI40>yb1vL1.2bg1y5M0@41vT/Qybt2h0yPSdKg.Kww,14y9gAG<4O9n2gwicu49101,1<W0Hr/ZcyRMA84gfJFgAG<4y3@fYfxr_Y/Z4yMmHMg.hon03UiL_f/W4Tq/@beeySTv/j8Q5AoU.bBo0w.ioD1i8I5Ybo0>ybeeCw1g.ioDthj7Shj7Ai8IRoc4.8J664ybh2hgh8xQ9237h2gg?,4ybv2h8i8C49aw,18yUgAC<4ybr2hMi8C49cw,18yUgAA<4y9x2iU<j8DEj8BI9719ysV9yvRcavx80QgA24y9h2h8WPYf7Q.i8JS84yb1un,18yNnmM,i8D1i2DNi87V/Yf.@6SM,4wVMD8CLSg,3EfdT/QybdrT<fJAoExc1RLkybdKKY3N@4:18yMmxM,i8Jg24yb5oX,18yp,g.i8I5wc,4y91n7,18yMlWM,yQ0oxs1QFkybt2h0yPQgK,Kww,18NUgA4>,4,3ECJD/Qy3@fYfxnH/_@bfkH,25_M@4rf/_@zJSf/yPzElJP/QOd1j6d.2Vhg80>yd5hqd.19ys58yMm9Jg.i8QRuF8.]0W9zq/_Fbv/_MYv>C9M4y3M05cyuZ8yPnDLM.ioD1j8JI9711wu3/MY?o7x/Yf>MXt2gU3Uhi0M.i8Jc94x83XHLfSp6yrh601,4G9zcU>2.iECYNw?8018ygmkLM.icu49b=i3D23Ue0Zv/i8Je28J@68n_3UhM3g.i8I5qrY0>y9xw01.18yMlrLM.i8A5jbY0>yb1lm_.2bg1y5M0@4FMQ0>ybt2h0yPTDJw.Kww,18NUgA4>,4,3Estz/Qy3@fYfx9gh.18NUgAI{18yPkcLM.Wg3R/Yf7U:Kw8,18zjkkz,ysvEdtz/Qy3@fYfxjzX/@b3um@.25Og@4aLL/@y8R/_yPzEYtH/QOd1umb.2V7?0>yd5r6b.19ys58yMkAJ,i8QR5p4.]0W3fp/_FW_H/Qyd5mCb.2@g<4O9ZP70W4zo/Z8yTgAg8KY9dg,18oZ3EJdv/Qy3@fYfxrrK/@b5mi@.25Qw@4GeX/@w7R/_yPzEsdH/QOd1i2b.2VGM80>yd5j2b.19ys58yMmzIM.i8QRB9,]0Wbbo/_FquX/MYvh,i8IR2rU0>ybl2ggj8D03NY0pCoK3N@4:1CpyUf7Ug:4C9Mky3M051wu7/MY0hw@Tz4U>,j07ai3D1tu54yVMAR<4y9l2gghonr3UAz2w.ibH////_vQy9@2n/MY0i2ekNw?8018ylgAieD_Zf/j2D9WmXX/Z8yPm0Lg.Kw4,18yMV8yMlxLg.i2D8u2kNQAybz2jE<iftQ9518esx83Qv1i8D2i8n0K>,183Qjgi3Bk93wfwygd.18eRgAe0@3CwI0>ybx2iE<ict497w;NUgAz;8,18wY03i3C498;fwKLP/Z8yQgAe4ydf12U?,4zhXQwfhfx8ynMAe4y9@AzTSAyb1tiY.18yoog?.i8I5PHM0>y9A0w1.18NUgAw{3FDLf/QybJ2io<i2KQ9cw,18evxO4P7iifvTct98ys58yv18Z_58ysp8yQgAk4wVY0@3ufr/Qydi058QuDFQvn/M@Tj2gUpAa9z4o>,i8Jc94xayoPe010w>y5_M@9HvP/@Cw_f/i8JQ942bfuyP.2W2<4i8B2iE<j8Bs9218NUgA4>,4,3Eptn/QObn2gwh0@SB2iE<i8fU_M@56Lv/Qib3gqY.15xsAfx0HT/_EGdj/UIUW17o/ZczgnIy,Kkk2.19ys58yMlbIg.i8IUi8QlN8w0>yddjae,NMexjRL/j8Js92143Xqk9aw,3FLvr/Qybt2h0LMo,18yoMAE<4i8B2i8<j8Bs923ELdj/Xw3<NebXZVgA6>0>yUP_tjUWmrN218Z@9cyRMA84gfJFgAy<4xFJ2gg?.g48f>ybz2iw<ic7G14w1RAwHJ2iM<i3KQ9dw<fwJ7I/Z8ypMAE<4ybdhGX.36x2i8;4z7x2iM{eADX/_i8I5@HE.cq06>,7F0Lz/Sof7Qg0>ybh2g8j8DFyTMA737ij2DVj8QI0kO9XKz3RL/i8Jk932bv2gsj8D@W1bl/Z8xs0fzF85.1cymMA24Cd70tdyvRceTgA80@26vf/Sqgj8DEj2DUi0d490x8ykgA84S5ZDlZi8Jk923Frfr/V1cyux8yTMA84ybt2hgj2DUi0d490x8ykgA84AV_Dcgi3JI911P2kAVTg@36gg0>S5ZDk@WXZCbwYvx}i8Jg84yb1imW.18at18fv/3M1SrAyb1hKW.2bg1y5M0@5a>.bZA<W7Xm/Z8yMn_Kg.3Xpga8jitrZ8yN3HLCoK3N@4:18yT0wi8I5RrA0>yb5sqV.18ys58av58wvD/MY03Upr?.i3D2syq_p<ewIRL/i8I5HrA,@Sk2y4QDmZi8IMWXMf7Ug:4yb1p6V.18yR08i8IlvHA0>y9A.1.18yMlMKg.i8A5orA0>yb1mGV.2bg1y5M7iBi8JQ942bfg2N.2W2<4z7x2gg?,g,eyaQL/i8fU_M@5uL/_Qib3jCV.15xsAfx6H//ESZ7/UIUW4jl/Zczgkvxw.Kkk2.18zhk4xw.ioD1i8I5tWU0>yddmyb.18yPwNMey6Q/_WiL/_@gi8JQ942bfomM.2W2<4z7x2gg?,g,ewfQL/i8fU_M@5HvX/Qib5rWU.15xt8fx9T@/_Eod7/UIUWcDk/ZczgmAxg.KgI4.18zhm9xg.ioD1i8I5_aQ0>ydduSa.18yPwNMewbQ/_WlX@/ZC3NZ4.18yTMAi4y9NAObn2gwi8DVi0@WWjZceTgAe4wfhcZ8wY01wur/MY0i8D7i8A5bHw0>C9O4yb3iOU.21V/_3M1Ch8CQsg?.1cypPV010w>O9xf4>2.i3D2sAxd0vhceSgA40@3t_T/Qybh2gwi8B494zFY@/_MYv>ybv2hwi0D73Uj2Y/_i8Jc9618esx83Qb1i8D7Wg7M/ZC3NZ4.18yTA8yT4oxvofxaA,18yMmyJM.i8C10>0>yb1piT.18ygm5JM.i8I5zHs.8J068n03UhX//i8JQ942bfi2L.2W2<4z7x2gg?,g,eyGQf/i8fU_M@5kf/_Qib1lCT.15xs0fx43//E@Y/_UIUW6jj/Zczgk_x,Kkk2.18zhkAx,ioD1i8I5BWM0>yddoy9.18yPwNMeyCQv/Wg7/_@gi8n_Lw4,19ys183Qj@i8INj8QcLg<19av19zjgVi07SijDM3UaP<j2D8i3D23Uf7_L/i8C10>0>y91r6S.18yMmWJw.yQ0oxs0fxav@/Z8yTgAg8IZjaU.bE8<icu49101,1<Wdrf/Z8w_z_3UlY_L/yPS6Jw.xvYfx6X@/_Eas/_UIUW9bi/ZczglJwM.Klw2.18zhliwM.ioD1i8I5NqI0>yddrq8.18yPwNMezkQf/Wi_@/Yf7U:ioDSWibY/Z8zjg_j3D63Ud3//i8D6it7Ei2Dmj3D6igZ7Y4C9@4AFY4A1M4wVZQAfgI3F7L/_UIl@bk.8ni3UhEYL/W9Le/@beew4QL/j8Q54Ec.bAt1,i8QlN880>C9Mkyb1juH.18zjkEy,i8IUcs3EhJ3/@AFYL/i8JQ942bfkqJ.2W2<4z7x2gg?,g,ezgPL/i8fU_M@5Nf7/UIRwbk.8nS3UiSYv/W2fe/@beeycQv/j8Q5pU8.bAr1,i8Qlj880>C9Mkyb1r@G.18zjmMxM.i8IUcs3EPI/_@BTYv/i8JY933EfZ3/QC9N@CZVf/i8Doi8JY9218yTgAk4C9TkMF@4w3h2g8i8B4923FD_H/Qybh2gEi8Rc3g58zkg50ky9h2gEi3D63Ud40w.i8n93UlDY/_i8Bc9119ytTFReL/Qyb1seQ.2bi1x8yNmNJ,i3AlEHg.8Cc98w<fwyk2.2bg1y5M0@5Mwg0>y3L2jo:@8rg80>ibD2i8<honr3Uhs0w.i8eY9b:3UiT0M.i8JQ942_1w,eykPv/j8Kk9dw,18yVgA6>.37Sjonit5J8Ks_Tk@eBCYgwic7G0QxFL2gg?.g48f>y9Q4zTUkz1Wwh80vF8yXMAI<4y9Q4wF@4MVQ7cxiiDiLCg,19zggWi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY9229YHU2<W37f/@5M0@e7g4.fq490o1,13UnD0w.ZEgA3w4,4fx>1.18yMmKIM.i8DFNE0o?,st49101<WsPM/Z8yPmgIM.i8J624wXx2j;3U8u1,i8Daj8D7i3Dn3UfvWL/i8IRqbc.eCMZv/i3B496wfwJzF/Z8yUgAW<4zhp2gUi8Jc93x8es583Qf8K08<fgEgAz<4y9j2gUifvpyogAz<4yb1hiP.18yoog?.i8I53Hc0>y9y0w1.18NQgAq;3FuuD/QObt2h8yTMA737ijoDZj8DSWdLe/Z8yRgAc8JY91NcyvXEaIT/P7ij8BQ90x8yPSQIw.i8n0i0Z8MACd70vFg@H/UdY91023UlT0M.NQgA408,3FlKj/QC9TkkNZAkNVeAfVL/h0@SJ2i8<WmzC/Z8yT08xsAfxl83.2bi1y5Og@5hMc0>y5ZHA1<i8IUj8I5hX80>wfhf58yt58avBczgOR;4Cdf3580vZ8evAfwG43.1casF9et0fwKI4.2bg1y5M0@5hw80>z7x2iM{bVA<WhX@/Z8xsC_?,4Ob1AwfhcZ8ystcastczgOd;4Sd10Bd0s1cessfwLc2.1casx8NUgAI{18es8fwXPD/Z8yoo.g.i8A5Fr40>yb1qWN.2bg1y5M0@5Agg0>ybdpON.3FAev/Qz7h2hU;cu498M<2<WmrE/Z8yTgAgbY6<i8Bc923EEIH/XY3<i8Jc9218Kc_Tk@eBCYgwNeb3ZVgA6>0>zTUAxFJ2gg?.g48f>z1Wwh8zggmi2K49b<18yPkCIg.i3DE3UatXL/i8J49518yTMAi4i8t2gwi8JI9718yogAG<4ybx2io<i8C49cw,18yUgAA<4y9x2iU<WsfL/Z8yTgAg8IZsqw.bE8<W1_b/_Sx2ge?,g@44fX/@D/f/i8JQ942_1w,eztOv/K0c,34ULLTB2go?.ibzfZRfzFpL484zTUAxFz2gg?.g48f>z1Wwh8zgghi8C49b<3F_vL/UIJqH,8nJ3UgFWL/W0T9/@beexSPf/j8Q59DQ.bCd0M.i8QldDQ0>C9Mkyb1qCB.18zjmqww.i8IUcs3EKcH/@DGWv/3NY0i8Dhifvpi8I50X,4y9xx01.18yMnZHM.i8C82>0>y9l2gUict497w;NUgAz;8,3FMer/Qybt2h0yPRRFM.Kww,18NUgA4>,4,3E_Yz/Qy3@fYfxhfX/@b1q@L.25M0@41vL/@xiOf/yPzEKYL/QOd1ppY.2VTw80>yd5nJY.19ys58yMnKF,i8QRTU4.]0WfT9/_FNLH/QybdAy9OAwVPDcri8KY9c<18av58evB83Qvfi3D83Ubo<j8D7WrHX/_7h2gg;4y9WuBnXf/i8Il4WY0>y9A.1.18yMk5HM.i8A5ZGU0>yb1v@K.2bg1y5M0@5Yg,4yb1uSK.3Fg_H/QOd10B9evwfwMfZ/Z9ys18QuZ9at19evxc3Qv7i8Dfj2D7i077j3D1i0Z2N@Du_f/ijDth8yQ98w,113Vb6hj7AWi3y/Z5cvp5cujF5ub/Qydf3p8esYfwRnY/Z8ytt8QuBcast8esZ83QvVi8DNi2DVi07hi3D@i0Z2QuAM_f/i8JY9418as6@g<370i8Ql9DI0>y9PuwcOf/i8JQ942bL2jk<i6fgW7z7/Z8w_z_3Uic?.i8I57WU0>w3r2hgi8BE24yb5guK.18yPTUHg.WoLW/Z8yTgAg8IZEak.bE8<icu49101,1<W2H7/Z8w_z_3UnA_L/yMnqHg.xs0fxdr@/_Evsr/UIUWer9/Zczgn1uw.Kkk2.18zhmCuw.ioD1i8I56qc0>yddgG,18yPwNMewEOf/Wpv@/@bdoSJ.25Zw@4nKX/@wMNL/yPzECsD/QOd1nhW.2Vhg80>yd5lBW.19ys58yMncEw.i8QRLnY.]0WdL7/_F7@X/Qy9A.1.18yhkwHg.i8I5aqQ.8J068n03Ung<i8I55WQ.eDF@L/i8JQ942bfq@A.2W2<4z7x2gg?,g,ewVNL/i8fU_M@5OeT/UIdWqM.8n93UiWXv/W8P5/@beezROf/j8Q5Q7A.bBo0w.i8QlJnA0>C9Mkyb1iyy.18zjkpvM.i8IUcs3EdYv/@BXXv/wPSrH;@4p_X/@x0Nv/yPzEGsz/QOd1lBV.2VMMc0>yd5mBV.19ys58yMnsEg.i8QRPnU.]0WeL6/_FafX/Qybt2h0yPTHEM.Kww,18NUgA4>,4,3Etsn/Qy9MAyb1ieI.18w_H_3UnM@v/wPQqH;@4U_D/@y_Nf/yPzEacz/QOd1gdV.2Vm080>yd5uxU.19ys58yMlrEg.i8QRj7U.]0W6H6/_FH_X/MYvh,glt1lAC9RA5lglhlkQy3X1y9v2g4LM,g18yngA2eyYNv/ioD7jonSt7V5cujH5wYvw;3EgYj/UcU17lEjjDQsSd8yQgA24O9YEJY90hcyvVcau9azgMwK<g18es983QvgWfb6/Z9ysl8xs1UMDgOi8D3j8DZpF18ytF8yuW_?,ey0Nf/i8n0u0J8asdQ9Aw1NuLxAezrM/_wPw4tdp8wYgoj8D_mRR1n45tglV1n@CMM/_jg7IWnH/_Yf7Ug:8f_0DYbK>,333NZ4.11lXEa<hj7_glp1lk5kloDZkQy9YQy1X2w4.18yTU8cvrEJYn/QybuN2W2w,37SykgA24C9NeywNv/ykgA38fZ0Tgpi8JX64ydduVT.15cv_E5cn/Un?g@kNQyb1n@G.18xs1Q1cp0a06U?,4i9p2goctJ5cuh8NQgA4;18zmMA66q9h2gsKL//@@?,4y9X@yqNv/xs1UpLp491UptedczngA88JY90yW.g0>O9ZKxVNf/i8n0t2BVkKzdML/yM23@0JQKEfU17kmWXcf7U:j8DDjoJA913ECYb/QS5V7nKi874a?.370mRR1n45tglV1nYdCAeybML/wPw4ttLFtv/_V18Muw4xs0fzCz/_@3W058Mu>i8R41318yggAWNBCA4wVMM@2FM,4C3Nx1cePgA3UgZ//ioI6i3Dotu590RU8jonAtivHaSof7Qg0>Sbr2ggj8DDioJs90xcymMA4ew9ML/jonJt0BdyuN9ehMAtdJ8yMlcGg.i8n0t0h8ylwwhon_3Ume<i8Dqi8I5caA0>yV0f3///T@1UL/3M188UPg010w07hGyTMA337iLwc,3EzIb/QObp2ggWlT/_Yf7Q.LNw,3E1If/Qy9MkCb1Ay90kCblwx80s98yl48i8Rk911dxuhR5@IrpwYvh,ioRk911dySgA44S5V7g6ijA497bHj8Bx44y92AObp2ggWgf/_ZCbwYvx}w_Y2vMKU?,ccf7Qg0>5nKwE,11lAkNZA5lglhlkQy9YQy1X2w4.18yTU8cvp8zmMA84Odr2gMW4_3/Z8yTIgKwE<NZEB490zEeYf/Qz7h2go;8B490Mf7M1CpyUf7Ug:8JY90yW.g0>y9XKxLML/i8n03UXC<ic7E18n0vJWdmfZ9yuN8Muc4j07HWNkf7U:ijD6sCd9wYggijDstbF9yMgAj3DMtuB8yTMA64Q3t2g8i8n_thPH7QObvN1cyTs8j8BY91zEnI3/QS5_Tg8j8D_j3ATte5cyv58wu40Yf/vHabv2gccta@0M,ewlMv/WW0f7M2_6<eymMv/ioIk94ydj2goi8D6i8AgioJ490x80t18yko8i8J491x8xs1R7KIx3NZ.6pCbwYvx}i8R844ybg118xs1Q1kwV47bKi8B644y9cuA//_pF18wsgE1,cs1rnk5sglR1nA5vMV1CpyUf7Ug:8f_0DYbK>,333NZ4.1lKwE,18yul1lQ5mhj7Sgll1l5d8yvd8wuNUww.i8J@237SWcr1/ZcyScgi8QRZTo.8B491N9ystcyuvEfc7/Qydt2hgLM4,29M@yHML/xs1R4EJ496wB0f,3Q0w,gg@kNEnr3UjR0w.i8R49415cs18NQgAc;18ykgA44ydx2jw<i8B4921CbwYvx}i8JQ912bv2gsKx<1cykgAaeyoMf/j8J492x8w_wg3Uma0w.j8JI931cekgAg7htLNw,1cykgAaewKMf/j8J492x8ys58yQgAg4y90kybl2h8i072jonJi8Bh24ydl2gMthnH6mof7Qg0>Cdlh1dySQgjonJt0p9ekk0sKRcymAgi8AaWn7/_@gj8DxLw01,NM4O9h2gEi8Ss9701.18zhk8sM.i8DvW6G/_YNZz70i8DvW0X1/ZcyQgAa8n03UBx?.j0d494xdxuRRcKAy//pF1dyQk8joJZ44O9XQO9h2gEj8BY933E1HX/QS5_QObh2gE3UjU_L/joDZjjB5.@5W_X/QO9Ukyd5ptO.18ytYNMbU.g.Wfa@/YNZAy9TP70W9r0/Z1ysq5M7yvict493w;i8JQ9229N@waMv/xs1R3kybz2gg?.i8n9vNB4yvvE4r/_Qy9T@yFLv/Wmj/_Yf7Q.i8J493x8es5@TkwFMkydl2gUh8DSLM4,3EEr/_Qy5M7wsi8Kc9101.18yQgAe4wVMn_kWWYf7Ug:exbLv/yM23@0hQS8RgWEfyXTggw_xo3Vj2w_w93Vj02c9QwQybt2gUct94yvvEns3/@Io3NY0i8D2i8SQ9702.2_?,eyjLv/Kw2,18zrgAs080>i9Z@yeLL/i8n0vZ7Fe//MYvg018yTgA88D7j8B490x8NQgAe;29h2gEW1b0/Z4yRgAa4Obh2g8xs1R4kybz2gg?.i8n93U_z<h8Dnj8B492zE1HX/Qy9T@yuLf/j8J492zFg_X/MYvg03EuXP/UcU17hijonJt1agj8DLjoJJaexALv/jonJtuZ8wshUww.cs1rglN1nk5uglZtMMYv0bw1<h8CY9701.15cuR5cuh8NQgAg;1CyogAt>.bH//_Lw4,18zrMAs>.eyJLL/xs1Uyvq497o1,ptdJczrMAs08.8JY91OW.E0>O9_Ky6Lv/i8n03UhD//3UAP?.WdaX/@b08fU2TiDw_w43Ulc//WVN8yQgAe4wVMg@e3//QwFMki9RAydl2gULM4,1cykgA24i9l2gEWceZ/Z4yRgAa4Obh2g8i8n0u1N8yUMA4>0>ybh2gUi3D1vY3FOLX/MYvh,h8Bk90xcykgAaexpK/_j8J492x4yRgA28I0w_w4tcidkeG3UKZQ58fU2g@kMEfUm0@kM0z23Ui9_L/i8JQ93x4ytsNQAO9h2g8h8Bk92zEkXX/Qibl2gEj8J490zHc0Yvw;18ysa_?,4i9l2g8i8SQ9702.1cykgAaexNK/_h8Jk90xcyQgAa4i9RXE0w,j8B490x8zrgAs080>i9l2gEW5yY/Z4yRgAa4Obh2g8i8n0vWDF0vX/QyWPsPcPcPcPcN8Z@98MuE5xt8fzCv@/@dgLZ8zgi0i8S4N9w2.18ykgA44QV9M@53g4,Yv06pCbwYvx}ioJT64CblO11yTYgi8CQ9e<15xfofx5k1.18zogAU<4y9QoD@LM4,18ys98ykgA8exkLf/ioJ7646bvN2@0M,4y9MAA3hO18wu80Yf/i2Dgi8D1WcWW/Zd0Ss8jonJtnrHuwYv>Cbhhx8yRgA8bY1<i8C49e<19yQQwgoJR4ezZK/_ioJd646bvh2@0M,4y9OAA3ji18wu80Yf/i2DhW7GW/Z9yQkEj8DLjgdB24y9h2gEi8B4943EAbH/Qybh2gEi8n03Uh.g.ioD5jjBB07i9iof7a4MXv2gg3Uh6_v/jjAD3Ug1//LP<3EJXH/Yj1vCY7i8D1NvV_>CbhO18yk4wjonJ3Ug.g.ioIni8R4943H7gYvh,pCoK3N@4:19zkkEjoJJa4S5Xng6ijBl07bJj8BFa4y924Obr2h0NvxTiof7a4MXv2ggtoDFOLP/@xFZf/ioJ7646bvN2@0M,4y9MAA3hO18wu80Yf/i2Dgi8D1W9eV/Zd0Ss8jonJtmTFff/_MYvh,ioJR64y9J2jw<ioJl846bvh3E5_j/QCbjhx1yTQgLwc,18ysF90QQwi87y0f3/QwFQux4Kv/ioJ5a4O9XQQ3pgx8ykgAa4y9h2h0W5GV/Z8yQgAa4y5M7geioD5jjBB07inWsD@/Z5cuTFMvX/Qydh2h0Wif/_@3_M4fzJs2.11lXEa<glp1lkkNXk5klky9Zle9@Qy1Xaw1.18yTU8cvrEfHH/Q69N8fX0M@4yw8.ezdLL/i8QZASM0>z1W0d8zpz/NY0K;98wuc.e3_i3D3i0Z7Sbw.2.i3D3i0Z2SewDKL/i8n0t1uW2w,37Si8D7WeeV/Z8ysl8xs1_1rS;i8RY933EDbH/Qz7h2gg<28n0tjr5@mYd1Tc.37iNvBKx2io<Ne9VfY75@nX0i0@Lh2hgifvRKw<x8et183Qfgi8Bk9118zrgA4>0>i9X@y9KL/xs1R5UK492w1,B0f,3Q0w,3Uju?.grA5<ioDocsB4yu8NZAi9X@xmJ/_ioD7i8n03Uza<Lg<11Lw<5RcmqgpCoK3N@4:11Kgk,19ytwNOki9Uz7Sh8DLW1yT/Z9yst8xs0fzFQ,2bfpWl.25_M@9Pw,4M1_kAVXDf6i8SY9a<3EGrD/UD1xs1RkYnVrMQrsw.i8JQ9135@mW490w1.34UDA_MsnVvI183W@49cw,18ev1P9Ayb1qut.18xs1Q6w@Sg2y4M0@5eMs,Yv06pCbwYvx}io76;uBk//3NZ.ewHJL/ioD6wPwm3Ug41w.yPTZB,xvZV5j70i874G>.5JtglN1nk5ugl_3A4ydJ2iw<Kww,18NUgAE;4,3EsHr/@Lbi8SQ9a<2W2<4z7x2iw;g,exiJL/i8fU_M@52L/_UIl0FQ.8ni3UjY_L/WamR/@beeweKv/j8Q5tSY.bAg1w.i8QlPCA0>C9Mkyb1k6i.18zjkOrM.i8IUcs3Ekbv/@CZ_L/3NY0i8JZ4bEa<cvrECbv/Q69NuBu_v/K>,33pyUf7Ug:4ybB2h.g.i8RQ92x5cvYNM4z7h2gw;4z7h2g8;ky9d2h8xt8fzL3@/Yf7Q.pCoK3N@4:18yt58ytR8ykgAa4wFMkwVSkwfhKB8xuQfx7E1.15cvp9yux8yPgAhj79csBdav14yu94yu_E5rr/Qy5M0@83>,@4cw40>A1NAAVXDbfi8J4921C3N@4:1d0vubfn@j.1c0v18ykgA88n_3UAT?.i8Kk9401.18es8fzBv@/ZcenMA20@3q//QydH2iw<i8DLW6KT/@9MEn0tkn5@mYdTmY0>ybx2j8<NvBKx2g8?.Ne9VfY74MnB@NAAfHYp8eQgA47cni8I5q9I0>y5M7gb3Xp0a8j0tiIf7M18wkgA2;58yQgA84ybB2h.g.Wvn@/Yf7Qg.87W42s.7joLSg,29l2goW9GT/Z8yu_EUHr/UJk91x8yUgAO<8f20kAfHYp8eQgA47b8WWpC3NZ4.3EGXf/UI0w_w43UjJ_L/w_xv3Vj2w_wC3Vj12cFR38fw@UfU4w@5Gw,4ybh2gwjonS3Unm_L/i8Kk9401.18yt58as58xsAfzUY,15cvrFKLX/MYvw;18zrgAE<bE8<icu49a;1<WcaP/Z8w_z_t0N8yQgA8eCr_L/pF2bfmGq.25_TjGW16P/@beexWJL/j8Q5USM.bDj1g.i8QleCs0>C9Mkyb1qSf.18zjmur,i8IUcs3ELbj/@KKK>,3FLvP/QwVMw@eGfP/Qydh2gwj8JQ90x8yggAjjD@3U9E?.i8Ik94y9Ski9XAi9V@zeJf/i8D5i8n0u2VQdEIZtF4.8n_3UDS?.ig7Li8J49218eogAg>.7@XWl3Y/Yf7U:W6eO/@3e0hQSQybx2h.g.i8Jk921cyngA24wVMw@d9fP/Qydv2gEWbCP/@5M0@54LP/UJY92OW,g0bU71,WeWQ/Z8zogAE<4y9h2goi8K49401.18ekgA80@dCM,4ybr2g8i8Bs90wf7Q.j3DZ3U8D1,j8J490ybl2gIcsB4yuZ8yPgAgrA5<W1GO/Z8ysd8xs1@nQkNZwYvg01CpyUf7Ug:4C9S8JY92wNOj7SjiDMgrA5<h8DyWeiN/Z8xs1@24A1NAAVTDbnyPRFA,xvYfyks3.18yQgA84Q1ZQwVx2h.g.3UZP//yTMAaezaIL/yTMAbez1IL/WiTX/Yf7Q.i8SI9a<18yu_Eibj/UD2xs0fxoU,35@mYdJCM0>ybx2j8<NvBKx2g8?.Ne9VfY75@nX1i0@LMkwXh2ggsS58yMl2C,i8n0t5kfJA0Exc1QjuI8wvEg9M.t4e_p<8Bk91x8ykMA2eygJf/i8DLWdyP/@bl2goi8Jc90x8yUgAO<8f20kwfHY58eQgA47a@pwYvx}io76;uDA_v/3NZ0>ydJ2iw<Kww,18NUgAE;4,3E0H7/Qy3@fYfxubZ/@bdran.25Zw@4RfT/@xlIf/yPzELHf/QOd1itG.2VW0k0>yd5nVA.19ys58yMnNz,i8QRUCA.]0W02O/_FBvT/Qydv2gEW96N/@5M0@8b_T/UJY92OW,g0bU71,cs0NXuz2IL/i8S49a<18NMgA;ky9h2g8pF1CpyUf7Ug:8Jk92N1Kgk,19ytwNOj7Sh8DLW0uM/Z9yst8xs0fzAz@/@bv2gEcsANZA6V1g,4C9M4i9UKzyH/_i8n03UUC_L/yPRHzw.xvYfytI,1c0vR8eiMAsW98yTMA2exUIL/xs1RhcnVrMTIqw.NvBKx2g8?.Ne9VfY75@nX1i0@Lz2j8<i3Jc911P6Ayb3nKm.18xsBQ3w@Siiy4Og@5Zw4.6qgi8449;7Fg//Qi9b2h9yvlcyngA2cj1unX6i8Bs91y9O@IhpwYvx}wvIg9M.t2K_p<8f30uyrIL/i8SY9a<3ETH7/Qybx2j8<ig@LNAMVW7bdh8II94Obt2g8i8Js91zFqLz/SoK3N@4:18yTgA2bE8<icu49a;1<W1mL/Z8w_z_3Uk0//yMn5Bg.xs0fxfb@/Z1yPXERr7/QOd1jVE.2VaMo0>yd5ply.19ys58yMk8yM.i8QR@ms.]0W1uM/_FJ_X/Qybt2goKww,18NUgAE;4,3EFWX/Qy3@fYfxpjY/@b3lul.25Og@4xLP/@zWHv/yPzEoX7/QOd1sND.2V1wo0>yd5idy.19ys58yMmmyw.i8QRxSs.]0WamL/_Fh_P/Qybv2goWcqM/Z1ysq5M7l1NvBL3jtF.18yUgAO<cnVrEgA2>.cjyuj_1NvB@MQwfHYd8eQgA47cki8I5MVg0>y5M7g83Xp0a8j0thl8wsk<1WnLX/Z1wvUg9M.teK_p<463Nw7E2X7/Qybv2goW56M/Z8yUgAO<4wfHYd8eQgA47bcWXV8ylMA6cj1unX7ysfH287X42s.7gGLSg,23MM7EOr3/Qybv2g8W0@M/Z8yUgAO<4AfHYt8eQgA47bei8Js91zFMLT/Sqgw_Y3vMKU?,ccf7Qg0>5nKwE,11lA5lglhlkQy9YQy1Xdw.g18yTU8cvpczqMAQ<ezAHL/i8JX437SKwE,11ysrEQqX/QybuNwNZHEa<ykgA6eyZHL/i8D5ykgA7exhI/_ymMAa4z1W0f7h2gI?,4ydCf/7M2U;Ay1UM.UfZ8esd83QvoK,8018esd83Qboi8R49415cuh8ykgA44w1SQybt2ggh8DTW6WL/@5M0@81w40>Obv2hMioQI74AVXM@2LM,4ydh2gMi8B490x8zoQ.f/Kw,g1cyuV4yvvEMWX/Qy5M7VCi8D2LwE,1cyu_ELGX/Qy5M7hhj2DEi8JQ90ybv2goKx<18zqM5?3/QO9p2gMi8DEj2Dwi8B493zEaWP/Qy3@11Qgbw1<i874S.105JtglN1nk5ugl_3pwYvh,i8JQ90ybv2goKx<1cymgAc4y9n2gUWeKH/Z8w_wgts19yuN8ziMHijDL3Udb//i8RY92yWp<bU1<Wd6J/@5M0@e_LX/UJY91OW2<4ydt2gMWbqI/_FVLX/V0NMeBV//pwYvx}kXI1<i8fI84ydt2gsW9OJ/Z8ys98wPw0t1ybv2gsi8D6i8B490zEUHf/Qybl2g8ysd8ytvEMWL/Qy3N229S5L3pCoK3N@4:1jKM4,18w@Mwi8RQ91PEjaT/Qy9MAy3e01Q68JY91N8ysp8ykgA2ewyMf/i8Jk90y9MQy9R@xPG/_i8f488DomYdCpyUf7Ug:5eX?,4y3X118zngA3ezYHf/i8cU07gli8IlxV40>y5QDg7NE8o?,j7ri8D7W2CH/Z8wYggytxrMV1jKM4,18w@Mwi8RQ91PELaP/Qy9MAy3e01Q68JY91N8ysp8ykgA2ex2VL/i8Jk90y9MQy9R@zzGL/i8f488DomYdCpyUf7Ug:45nglp1l5mZ?,5d8wuP;i8RQ91PEoGP/Qy9MQy3e.fx8s1.2br2gsw_Q13UX8?.i8JU2bEa<cvp1Lf//_EMGL/QC9NUfZ0w@5Jw40>ydfj1u.3ESGL/Qydfjdu.18ysnEOWL/Qy5Xg@4cw40>y5M0@4ag4.bEa<cvp8yuZ8ykgA2exlGL/i8JY90yW2w,37Si8B4923EfWH/Qy9h2gEhon_3UZN?.honA3UXE<i8QZSog.eyYGL/i8D5h3Kw:@5L>.8eU4;4fxu41.18zjSVng.W4eH/Z8xs0fxaE,2W2w,37Si8D7WfKG/@W?,37Sh8DDioD7WeCH/Z8ysl8w_z_3Uio<i8QZrog.exgGL/i8DGi8RQ9314yv_5@mZ49214ymgAgct494g;NvB_h2gMi8K02<4wFMIjx@mX8NefN8I81Kyw,35@DZ494zERWz/Qy3@fYfxbA1.18zjQex,Wf6F/Z8yqw8<pyUf7Ug:37Ji8DvW1qF/Z8wsj;yuxrnk5sglV1nYeb3kWf.25OngGWfmD/@beexuG/_i8IlFUg0>yddgxy.18yPF8ys8NMeyPGv/3NY0Lg4,3HGSof7Ug:4ybuN2W2w,37SWf2F/Z1ysjFcLX/MYvx}i8RQ922W4<4i9_@wuGf/i8fU_M@5s_X/UIRPEU.8nS3UhB_L/W76D/@beezqGL/j8Q5oS4.bDq1,i8QlCBI0>C9Mkyb1gS4.18zjn@o,i8IUcs3E7aD/@AC_L/3N@:4i9VQydt2gMh8Cw;exIGL/xs1R48J494wB0f,3Q0w,t7n7xh;2<i8RQ922W4<4i9V@xYF/_i8fU_M@5MLX/UI5b8U.8n03UiQ_L/Wc@C/YNXoIUW3qG/ZczgkTog.KvE4.18zhnSmw.ioD1i8I5qoc0>yddlFw.18yPwNMexUGf/Wnn@/_7xh;1<WqnZ/@b5sWd.25Qw@4evX/@xNFL/yPzESGD/QOd1rJw.2VZwg0>yd5pFq.19ys58yMkdwM.i8QR_BY.]0W1OE/_F@LT/MYvw;1jKM4,18w@Mwi8RQ91PEPaz/Qy9MAy3e01Q68JY91N8ysp8ykgA2ex2VL/i8Jk90y9MQy9R@zPFL/i8f488DomYdCpyUf7Ug:5eX?,4y3X218zngA7exYGf/i8D2i8cU07goyTMA74y9NAy9h2g8W8bJ/Z8yRgA28D3i8DnWaeC/Z8wYgwytxrMSpCbwYvx}lrQ1<kQy3X1x8zngA1ewHGf/i8D3i8cU07gJwTMA105_eUIZiog0>ydt2g8Kww,18NQgA2>,3ETqn/Qy3@fZQbP7Ji8DvW3SC/Z8wYgoyuxrnscf7Q.i8JU2bEa<cvrEoav/UD7WXsf7Q.yMlyz,xs1QN@w9Fv/cuSbeexMGf/j8Q5W5A.bBa1w.i8Qlc5A0>C9Mkyb1qe1.18zjmknw.i8IUcs3EIGr/@KbkXI1<i8fI84ydt2gsW6OD/Z8ys98wPw0t1ybv2gsi8D6i8B490zEMLv/Qybl2g8ysd8ytvEAWn/Qy3N229S5L3pCoK3N@4:11lQ5mgll1l5ljKM4,18w@Noi8RQ92jE4Wv/QC9NQy3e01Q2oJI92i3_gl_8kO9_@x9Fv/i8f4m8DomRR1n45tglV1nYcf7Ug:4ybu0yW2w,37SgrX//_W5GC/Z9yTYgKwE<NZEB491jEhGr/QCbvNyW2w,37SykgA4ewOFL/ioJ_8bEa<cvq9M@wwFL/ioJ_abEa<cvq9h2goW0OC/@9h2gsw_Q63Ukf0w.3NZ.6pCbwYvx}honSu1J8zngAebE1<h8DTW3CB/Z8xs0fzJ01.18zmMAg8JY91iW4<4y9XKwqFv/i8fU40@5I>0>ybh2h0cvqW0w,8Dvi8B492zECar/QObh2h8yTMA48Dqhj79i8Rc9318zngAa4y9h2gMW8qA/Z8xs0fydQ,2bv2goi8RQ93yW2<4z7h2gU?,eyxE/_i8fU_ThHyTMA7bEg<i8DKW8Gz/Z8w_z_3Ul0//yMkWyw.xs0fx3b//ETqb/UIUW4qC/ZczglLng.Ki87.18zhk6lM.ioD1i8I5unY0>yddmFs.18yPwNMey8Ff/Wvf@/Yf7M2b5uG9.25QDibW96y/@beezWFv/j8Q5xls.bAx1M.i8QlKBo0>C9Mkyb1iR_.18zjkun,i8IUcs3Efaj/@Bc//3N@:bY,40Waqz/Z8yTgAg8JY910NQAy9h2g8W76B/@W0w,37Syt_EoWn/Qybl2h8i8nit4x5cuRC3NZ4.1cauGU,1>ybt2g8yTMA44wVMAC9R4Mfh@1cyu9d0unEyGf/Qybt2g8j8Dyyt_EqWb/Qybl2h8ijDlsI58yTMA2ez7EL/Wpn@/ZCA37rWmzZ/ZC3N@4:19yTYMKwE<NZKzwE/_goD6WuzZ/Yf7Ug:5eX?,4y3X218zngA7ewIFf/i8D2i8cU07goyTMA74y9NAy9h2g8W1bw/Z8yRgA28D3i8DnW5ey/Z8wYgwytxrMSpCbwYvx}glplLg4,1ji8fIc4ydt2gcWdCz/Z8ysd8wPw0t4m3v2gc0nVSi8QZclo0>Obs0zESqz/Un0u4l8zmMA48D1Ly;NM4y9XQyd5qtk.3E@a7/Qy9XAO9ZP7JW7KB/Z8yt_EQW7/Qy3N329W5JtglX33N@4:3EKW3/UIUW2iA/Z8zjTqlg.i8D6cs3EQW3/XQ1<WY6gpCoK3N@4:1ji8fI84ydt2gsW36z/Z8ys58wPw0t6y3v2gs0nVxi8JU2bEa<cvp8ykgA237rW9Gy/@W3M,bU91,yssNMewnE/_i8Jc90y3@fZQ5ky9P@wREv/i8f488DomYcf7Qg.8I5sEs.8n0thUf7M1CpyUf7Ug:bI1<WYNC3N@4:3E@V/_UIUW6iz/Z8yNmJv,i8QRHBE0>ybeAy9Mz70WbCx/Z8yQMA2eL2pF11lBmZ?,5d8w@MMi8RQ90jEqqb/Qy9MQy3e.fx9<2br2g4w_Q13UWY<i8RY90zE5q7/Un03Uyd<yTMA3370Kw0>02@1Mg.ex8EL/w_Q23Uin<i8RI912bj2g8Ly;NM4yd5h9j.18yu_Eoa3/QybuMx8yuXEVaf/UJc90N8yuYNM4yd5uVi.2@8<ewWEf/i8JX44y9Xz7JWbOz/Z8yt_E5a3/Qy3N329W5JtglX3pwYvx}WfKu/@beexAEL/i8QZcBg0>y9Nz70W1ev/@Z?,eL03NZ0>ybgMx8yst9ysrEGpX/Qy9Nky5M7hVZA0E17hHyQMA2bUw<i8RY910NM4yd5lVi.3EHV/_Qy9XP79i8Rk910NZKw@D/_yQMA3bUw<cs18zhkSkw.i8RY913EwF/_Qy9XP79i8Rk912@?,37JW0Ov/_Fe//MYvw;1cyvvEea3/QO9Z@xMD/_i8D5i8n03UlV//yTMA2eyrD/_yTMA3eyiD/_WjH/_ZCA6pCbwYvx}glt1lA5lglhlLg4,1ji8fIa4ydt2gkWaew/Z8ysd8wPw0t114ySMA5463_gh_7XQ1<i8DvWdau/Z8wYgEyuxrnk5sglR1nA5vMV18yTw8KwE<NZKzMD/_i8JX4bEa<cvp9ysjETp/_QybuNx8NQgA6;11ysq0fM0fxsg,15cvZ8yTIwKwE<NZKyhDL/i8D5gofZ1g@4v<4ybuOx8zjmKkw.W2iv/@W,g0bU71,h8DTxs0fBc0fJI29h2g8cs3E1a3/Qy5XngNhoDBhj7AioDEcsB1Kgk,14yv9dau1cyvV4yu_EnpT/Qy5M7xMt0x90sh9euNORoJ490y5M0@5Iw,37JWh7/_Yf7M2W,g0bU71,h8DTcs3EF9/_Yt490w;i8nJtpwNXuDC_L/cvqW2w,ezkDv/i8fU_M@49L/_Qy9h2goj8RY91zF6L/_MYv0eyjDf/yPy3_MJQyof_10@4wf/_UJk90y5QDkzWeqv/Z8zjTakg.Lg4,18ysoNMeygDf/Wo7@/Yf7M14yvt8ykgA2eyXDv/i8Jk90ybeKL7pF14yvsNXuyCDv/Wlv@/@glrQ1<kQy3X1x8zngA3ezbDL/i8D3i8cU.@4GM,4ybfk@3.18xvZQ5rU>a.W8yu/Z8NMkRwM}8IZRTE.8n_3UAL?.yPT5uw.xvYfyg41.2bfrdW.25_M@9QM,8IZEnE.8n_3UCB<yPSfuw.xvZVuUIZDnE.8n_ul58zjRnjM.cuTEwVT/Qydflxf.3EtVT/QydflFf.3EqVT/Qydfmhf.3EnVT/QydfmRf.3EkVT/Qy9T@xrDf/i8f468DEmRT3pF3EKVP/UIZgnE.eyMDf/NMkKuw.//_@Kj3NZ.eyrDf/yPQtuw.NMnXug.//_Un_3UxO//WY6gW7Ks/@bfulV.371tZV.3//_xvYfy4z//HMp3EmVP/UIZOnA.cs5MTA.f//@5_M@87L/_@L1AewXDf/yPSJug.NMmDug.//_Un_3UzM_L/WY6gW1Ks/@bfp5V.371oJV.3//_xvYfycb@/_HMp1li8DBglt1lA5lglhjKM4,18w@j0i87IM<4ydt2hkW1Ct/Z8ykgAc4y3e.fx5U6.2bn2hkw_I1vB59ysvE@pT/QCbjMx8yM183XUhi8Bc92zSh50120@5eMQ.ct492j//_w_I2t3l8yQgAcbEa<cvp8yTwgW4Os/@9h2gAWNFC3NZ4.18zglCjM.NQgA9f//Z8ykgAa37rj8QZSTw0>OdH2i;pCoK3N@4:11yP@5_Twpi8RQ962W4<exqC/_i8fU40@4c0o0>yb1v6,18yXw.g.i8IlUU,4ybcAwV_w@3XMk0>Obwww1.1dxs0fyes6.18zko1i3D73UeW1w.i2DTioDYi8DXY4wfMhF8yMSBw,i8K10>0>Wdd2dcev0fw@U5.18yNmaw,3Xpiaoji3UgC1M.i2Doi8n03UVW1g.i8IdqU,4C9N4ydx2i;i8B49420Kmc1<3Unc1g.iofY?@4bgM0>Gdf2d8ytwNZwYvx}pCoK3N@4:18ys98wY01wub/MY03Xukkg?.180tp8evxRUQS9Vo2Vo><fxrob.19yvhdxugfxqEb.18xvofxbUa.19KcTcPcPcPcPci8Rc9618ysZCpyUf7Ug:6pCbwYvx}pCoK3N@4:1CpyUf7Ug:4y9Y4y3NM59Z@18yv18MuE3j8QcAAQ1OkMFO8f0c4y3_wB8ytq8h_ZTRAwV@g@3F0I0>y9_Ay9@4wFPAydlLZ8w_E@3Ur92M.ioDMioDVi8Jk941yYvR8rOmxkM.oL7Zi6YtRRc0>C3Uc1yYvR8rNk9l,jiD1pwYvh,oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QAVMnnjijDM3Uh_<i8DUh8D2j2D0ioDNjiD1joRh_QC3@xVScQMFNSbNvOxLh/4UTR6M074UDQ01txj.34EnR_x0i;gvr17TgZiofxU4g1OAMFO4xzQAw3l2h0pCoK3N@4:1CpyUf7Ug}@SufZ8w@w1i8f20k28uLZ8es5OWQxzZAw3t2h0NvxTNwo0i8JQ9418yTMAaeyKC/_i8nr3Ujo2g.i8Rc9618ytV9KcTcPcPcPcPci8Df3NZ4.1CpyUf7Ug:4y9Y4y3NM59Z@18yv18MuE3j8QcAAQ1OkMFO8f0c4y3_wB8ytq8h_ZTRAwV@g@3bwE0>y9_Ay9@4wFPAydlLZ8w_E@3Upj2w.ioDMioDVi8Jk941yYvR8rOkxkw.oL7Zi6YtlR80>C3Uc1yYvR8rNm9kw.jiD1pwYvh,oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QMVO7njj3D63Uh_<i8DUh8D2j2D0ioDNjiD1joRh_QC3@xVScQMFNSbNvOxLh/4UTR6M074UDQ01lxi.34EnR_x0i;gvr17TgZiofxU4g1OAMFO4xzQAw3l2h0pCoK3N@4:1CpyUf7Ug}@SufZ8w@w1i8f20k28uLZ8es5OWQxzZAw3t2h0NvxTNwo0i8JQ9418zjRiiw.ctbEGFv/Qydj2hwib_dPcPcPcPcP4y9PAS5Xg@4l0w,Yvg01CpyUf7Ug:4O9W4y3Nw58Z@tcyux8MuE3j8Q4AAQ1M4MFM8f0c4C3_gB9ytm8hLZTRAwVYg@3Cww0>y9ZQy9Y4wFPQydl_Z8w_E@3Urt2,ioDVioDMi8Jk941yYvR8rOmxk,oL7Zi6YtRR,4C3Us1yYvR8rNk9kg.jiD8pwYvh,oLbti8R0_Qy3W418wY90oL9Zi03boL9Zi032oL7RieL0oL7Zi7Z2_QAVM7njj3Df3Uh_<i8DMh8Daj2D8ioDUjiD8joRg_QC3@xVScQMFPCbNvOxLhL_4UTR6M074UDQ01txg.34EnR_x0O;gvr07TgZiofwU4g1MAMFM4xzQAw3l2h0pCoK3N@4:1CpyUf7Ug}@SsfZ8w@w1i8f20k28sLZ8es5OWQxz_Qw3v2h0NvxTNws0i8JQ9418zjTxi,ctbEaFr/UJY92i5_M@9zwk.37ri8JY933EYFj/Qydpty9S5J1n45tglV1nRT3A4wFSrw;ioDcj0Z8U4ydfq9L.3Expn/U2U5:fxow4.1dxuhRm0Yv037rWtDV/ZC3N@4}fJA8Fxc0fxjg6.23@SgfxcI2.3PA8f30uCN@v/A4yb3s5W.18yRMAo4Obp2hEi8K10>0>Wdd2dcev0fwxbW/Z8zogAw<4yb3phW.18ykgAg82VoM4<fx3o5.1azhgzjoDBibz////_vU7y/Yf>ybJd4>2.i8Dqwub/MY0i276i2e4Qg?8018asq0Km01<3Ul7@L/jonA3Uh7@L/iEQYaQy9S4kNV0Yvg018ys98wY01wub/MY03Xukkg?.190th8evxRU@Ae@L/pwYvh,KM4,3Mi0_16Ayb3uZV.11L>,3Ff_D/MYvg018yR8Mj8D0ifvoi8fG0kyb3sJV.18ev8fw@E2.18yo48?.grM1<i8IdHDA0>Gd12p8estP1AwFZQC9_4O9U_183Y4pi8IdA7A0>ybwh01.18etwfwZLU/Zcys9cys18ZZHMi0@NAgw1.18yMRDug.WrTU/ZCbwYvx}i8I5knA.f23g1w1i8QZRmQ.eyUA/_NE0k;p18yMkNug.i8K80>0>wVOTdki8D8i2Doi8B493xceu0fw_zZ/Zcyv11yTY4Kx<1cyuV8asx8yoMAw<4y9x2i8<i8Bc94xcymMAgewEAL/i8Jc94x8w_wg3Ui90w.i8I5ODw,@Sg2C4M0@5BLT/UI5o7,37_KL//Z1K>,11Kg4,2@0w,4z7x2i6{8C498<2b1iJM.1CyrMAzw,4O9XSp4yogAx<8C498w,1Ch8Cc98M,3EJFf/Sq3L2i6;7krpEeY98U;3Ugc//WirZ/Yf7U:yPTqrM.i8RQ962W2<exXAL/pEeY98U;3Ujs_L/WvrY/Yf7U:i8I50nw.f23g1w1KM4,11L>,11Lw4,18zjRQr,W5ui/_5@u_0hj7rpECs98g,1yYnY8vUgAxw,6p4ypMABw,6p4yqgAz<6p4yrgAB<cq05;6b1klL.29x2i;yMkQrM.yogAy<46b1UC499<3HeMYvh,KL//@@0M,4O9X@y@AL/ZEgABw<5RdSq3L2i6:@5tg4.6q3L2ie;7kti8I5eTs0>ybw.1.18yNkJtM.i8Iii3D2sWR8zjSKqM.W96h/@0K1g;3Ugk_f/i8I51ns0>y5M7gbyR0oxt8fxjY2.18zjR@qM.W66h/YNSYq05;3FM_n/MYv>y9YE7y/Yf>gfJVhh01,bE1<j8J926p5xt9c3Qjict99Z_aWg<4wVQ4wfhY9dxsCW?,4MfhcFcesxc3Qr8K>,1dysNdxsBc3QjwWs_Y/Yf7Qg0>yb3n5S.18xsBQ1UJ168n0tnF8zjTKqw.Wd6g/_6w1g;WkTX/Yf7Qg.8IZWCQ0>ydt2hwKww,18NQgAo>,3EsE/_Qy3@fYfx1I1.18zjSFqw.W8Og/Z8yMQdtw.wbwk:@4Yg,4y5Og@4Ug,4Obp2gUyQ4oxs1QxL23qhw1WnP/_ZC3N@4:2bfnFJ.18zngAmbE8<W1Kg/_FCvX/Sof7Qg0>yb1r5R.21U/_3M0NQAy@////_TZ88Xjo010w0eyaAv/i8fU_M@5gLH/UI5yDk.8n03UgQ@L/W2Se/YNSUIUW9ih/Z8yNntqw.i8QR1AA0>ybeAy9Mz70WeCf/_F2fH/QC3_>fx2I1.1dxugfxvnQ/Z5cuQf7M1CpyUf7Ug:bUM<pECQ98<3FIvr/Yq05;1cySgAeeBS@L/h8Il1Dk0>m5Qw@4RvX/@yEzv/yPzE4p7/QOd1gZ3.2Vzgg0>yd5t51.19ys58yMl4qw.i8QRdks.]0W5ef/_FBLX/_23q1w1WrvZ/Yf7Q.i8I5Eng.f18wSw80rI2<3Uhc@v/i8JY92x8zjmLgw.KM4,3EQF7/@AN@v/Kj<1CyoMAw<eB@Z/_Kz<1CypgAw<eDI@f/grQ1<grM1<Y4M1oh3Fjfj/XEa<cvp8ys_E98/_UB492h8zgl6gw.i8B492zFU_b/QybIgw1.18ytEfJE5w?.wub/MY0i8nSvzV8wXPh010w.1UcUj0t7nMi8d14051Lg4,3FZvf/Qybv2h0WmDU/Z8yTgAgeBvZv/i8JQ943FRvr/QgfJWhh01,4O9VEj03Ulo//wbBz?,7kVgrQ1<WpTP/Z5cs0NQKCyZf/hj70ctbF6fr/QkNOj7iWoXT/@0Kmc1<tgvMi05N4eK1grQ1<WirV/Yf7Q.lrQ1<kQy3X1x8zngA3eyHzL/i8D3i8cU07h7i8QZMSs.eyCzv/wbwk;7gMi8I57Dc0>y5M7ghyR0oxt9Q2L23q1w13NZ4.18zjShpM.W7id/_6w1g;cuR8yt_EEUP/Qy3N1y9W5JtMSoK3N@4:1jKM4,18w@Mwi8RQ91PEb8X/Qy9MAy3e01Q1UdY91M2t1h8ytvEp8P/Qy3N229S5L33NZ0>ybm0x8zjnsg,i8B490x8yt_E48T/Qybl2g8xs0fx8I,18zjm_g,i8Dvi8Bk90zEXUP/Qybl2g8xs1Rlky9l2g8i8ItkD80>ydftJC.3ELEP/Qybl2g8wbwk;7gFi8nrt0ubgNy5M7ldi8Bk90x8zjSMpw.W9ec/Z8yRgA2cq05;3Mi8dH2>NSQy9R@yTy/_i8f488DomYcf7U:i8I5Wn4.f18wQ080j7rWZzMwSIo0kyb7tdN.3HFmof7Ug:45nglplkQy3X4x8zngA7ewszv/i8D3i8cU07gdi6dI91OdhvS3@09S7HQ1<i8DvW4Cb/Z8wYh8yuxrnk5ugl_33NZ0>ybuMyW2w,37SW6yc/Z8yTIgKwE<NZA69NKwRy/_ioD7w_Q33Uip<i8JX64yddpk_.18ynMA2ez4y/_cta5M7gui8JY90x8zjm2fM.WaSb/@W0w,8n03Umo<j8D@h8DTW0md/Z8w_z_3UhB//i8RIW_x8yRk0w3E0t5tczkgA84y9MrUw<cs1cyst8zhkZfM.j8B490zECEH/Qybvg18yTgA237JW1Ge/_F9f/_MYvh,Kw4,18ysp4yvvEE8P/Qy3@fYfx03/_Z8ysp8zjTWfw.cs0NXuwPyL/WuT@/ZC3NZ4.2W?,eBu//3NY0pCoK3N@4:11lBlji8fI44ydt2gcWbWb/Z8ysd8wPw0t0u3v2gc0DYuLg4,18yt_EYoD/Qy3N129W5JtglX3pwYvh,i8JU237SKwE,3E48L/QybqN18zjlVfw.goD6i8DLW8Ga/@5M7hei8QRrzU0>y9X@xTyL/xs1QkQyddmo@.18yu_Ep8H/Un0t5x8zjnufg.i8DLW56a/@5M7lth8DTcuTEUUD/@BR//pwYvh,Lw4,14yvsNXuzVyf/WlL/_Yf7Q.cvp4yvsNXuzAyf/Wkr/_Yf7U:Lw8,14yvsNXuz9yf/WiL/_Yf7Q.i8DKi8QZX3Q.370W3@8/_F3f/_SoK3N@4:11lBlji8fI44ydt2gcW9Wa/Z8ysl8wPw03Uh10M.wTMA3>fzwo2.18yQ08i8D7ioD6Wau7/Z8ysd8xs0fxfI2.3Sg2w43UjF0w.csANZAyd5p0Z.18yt_EjEz/P79Lw4,18ytZ8zhm1fg.W3y8/YNOrU2<i8Dvi8Qlu3Q.ewyyf/csC@0M,4y9TQyd5mYZ.3E38z/P79Lwg,18ytZ8zhlAfg.Wfq7/YNOrU5<i8Dvi8QlmzQ.ezwx/_csC@1w,4y9TQyd5lwZ.3EOEv/P79Lws,18ytZ8zhlefg.Wbi7/YNOrU8<i8Dvi8Qlh3Q.eyux/_csC@2g,4y9TQyd5jsZ.3Ey8v/P79LwE,18ytZ8zhkIfg.W7a7/YNOrUb<i8Dvi8Ql83Q.exsx/_csC@3<4y9TQyd5hoZ.3EhEv/P79LwQ,18ytZ8zhk6fg.W327/YNOrUe<i8Dvi8Ql_jM.ewqx/_csC@3M,4y9TQyd5vgY.3E18v/P79Lx<18ytZ8zhnLf,WeW6/YNOrUh<i8Dvi8QlWPM.ezoxL/csC@4w,4y9TQyd5tYY.3EMEr/P79Lxc,18ytZ8zhnkf,WaO6/YNOrUk<i8Dvi8QlO3M.eymxL/ctJ8yu_ET8r/Qy3N129S5JtglX3A4ydfrcX.3Ed8r/Qydfr4X.3Ea8r/Qydfr8X.3E78r/QydfrcX.3E48r/Qydfr8X.3E18r/Qydfr8X.3E@8n/QydfrEX.3EX8n/QydfrEX.3EU8n/QydfrEX.3ER8n/QydfrsX.3EO8n/QydfroX.3EL8n/QydfrgX.3EI8n/QydfrgX.3EF8n/QydfqUX.3EC8n/QydfqYX.3Ez8n/Qydfr0X.3Ew8n/QydfrkX.3Et8n/QydfrIX.3Eq8n/QydfrAX.3En8n/QydfrwX.3Ek8n/QydfroX.3Eh8n/@DF_L/3N@:4O9Z@yMxL/j8DTWey5/Z8ysd8xs0fxvLY/@gpCoK3N@4:2X?,eCO_L/pwYvh,i8fI24ybfmRw.2@?,ewbyf/i8IZV6,bU1<WfG7/Z8yPSPo,Lw4,3EWov/QybfoFw.2@?,ezox/_i8IZKm,bU1<Wcu7/Z8yPR0o,Lw4,3EJEv/Qybfotw.2@?,eyBx/_i8IZ9C,bU1<W9i7/Z8yPSto,Lw4,3EwUv/Qybfvhv.2@?,exOx/_i8IZSRY.bU1<W667/Z8yPRio,Lw4,3Ek8v/QybfuBv.2@?,ew_x/_i8IZQ5Y.bU1<W2W7/Z8yPR7o,Lw4,3E7ov/QybfsVv.2@?,ewcx/_i8IZplY.bU1<WfK6/Z8yPTQnM.Lw4,3EWEr/QybfuJv.2@?,ezpxL/i8IZMBY.bU1<Wcy6/Z8yPRhnM.Lw4,3EJUr/Qybfm1v.2@?,eyCxL/cs18wYg8MM,fcf7LF8w@M8i8f42cc||||~~~~~~~-0>g,4o<2<1M,9d14e94Asw0jEDkgc24Q3l6{4w,19<iw,4I,1d<jM,58,1k{5o,1p<mw,5I{n<7x1zT9nXO0y9Qv8xRk@FGsP6Ttfv4gfGYdTHrrQ6YliMmIv88o0aN0upbAfPU7NeRj34KVbuYU_8DimX7RldGEIyKyu8KaqqSuPGt@tPQPqClvClU6rkxtj7qGf!.vM,1%uw,18^zg,18^iM4.18^vM4.18^4<2%Rw,1%5w4.18^kg8.18^sw,18^HM8.18^@g4.18^og4.18^Fw8.18^Jw4.1%n<18^aw8.18^lg,18^5w8.18^ug,1%Hg4.18^xM4.18^V<1%rw4.18^m08.18^oM,1%4>.18^E>.18^1M8.18^2M4.18^gg4.18^ww8.18^kw4.18^5g8.18^Qw4.1%eg4.18%g,2%tM4.14^qM,18^R>.1%fw8.18^Dw,18^pM4.18^p<18^a>.1%Hw,1%Ag8.18^7g8.18^s08.1%1>.18^Fg4.18^8w8.18^q08.18^_<18^ig8.18^tg4.14^C>.18^o>.18^Yg4.18^dw8.18^Uw4.18^b<2%Og4.18^hw,28^U08.1%Mw,1%C08.18^3w8.18^mg4.14^mwg.1406g0wVg}3=Hgc.1406g1wVM}3=igg.1406g1wVg}3=rgg.1406g3wV[3=D0c.1406g2wVM}3=pMc.1406g1wW[3=X08.1406g3wWg}3=ywc.1406g3wVM}3=J08.180102gvw}841[Pgc.1406g3wVw}3=50c.1406g1wWg}3=dMg.1406g2wVg}3=3gg.1406g0wVw}3=egc.1406g3wW[3=.c.1406g2wWg}3=9wg.1406g3wVg}3=PM8.1406g0wWw}3=l0c.1406g2wW[3=uwc.1406g0wW[3=M0c.1406g0wVM}3=Ugc.1406g2wVw}3=Zgc.1406g1wVw}3=9wc.1406g0wWg}3=05ZvpSRLrBZPt65Ot5Zv05Z9l4Rvp6lOpmtFsThBsBhdgSNLrClkom9Ipg1vilhdnT9BpSBPt6lOl4R3r6ZKplhxoCNB05ZvoTxxnSpFrC5IqnFB07dQsCdEsw1Pt79IpmU0u6Rxr6NLoM1JpmRzs7A0sThOoT1V07xCsClB06pFrChvtC5Oqm5yr6k0nRZBsD9KrRZIrSdxt6BLrw1vnSBPrScOcRZPt79QrSM0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0sTBPoSZKpw1Ls6lKdzg0sClxp01zr6ZPpg1vnSBPrScOcRZPt79QrTlIr01DpnhvsThOqmVDnTpxr7lB07dVsSdxr6M0rmJPt6lJs3oQ07lKr6BKqM1Pt79zrn.sThApn9O06pTsCBQpg1Jrm5Mdzg0rmlJsSlQ05ZvpmVSqn9Lrw1Pt79KoSRM05ZvqndLoP8PnTdQsDhLr6M0pnpBrDhCp01Mqn1B06pzrDhIdzg0sSVMsCBKt6o0oCBKp5ZxsD9xulZBr6lJpmVQ07dQsClOsCZO07lKoCBKp5ZSon9Fom9Ipg1MrTdFu5ZJpmRxr6BDrw1IsSlBqPoQ06dIrSdHnStBt7hFrmk0rmlJoSxO07lPr6lBs01Cs79FrDhC071Lr6M0s79BomgSd01ComNIrSdxt6kSd01CsThxt3oQ07dBrChCqmNBdzg0sTBPqmVCrM1Ps6NFoSk0oSZMulZCqmNBnT9xrCtB06RBrn9zq780rm5HplZytmBIt6BKnS5OpTo0nRZQr7dvpSlQnS5Ap780rnlKrm5M05ZvoThVs6lvoBZIrSc0sSxRt6hLtSU0s7lQsM1PpnhRs5ZytmBIt6BKnSpLsCJOtmVvsCBKpM1OqmVDnSBKqnhvsThOtmdQ065Ap5ZytmBIt6BK079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt01OqmVDnSdIomBJnTdQsDlzt01OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZzr6lxrDlMnTtxqnhBsBZPt79RoTg0sCBKpRZFrCtBsThvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt01OqmVDnS5zqRZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZzrT1VnTdQsDlzt01OqmVDnTdFpSVxr5ZPt79RoTg0r7dBpmJvsThOtmdQ079FrCtvqmVApnxBsBZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt01OqmVDnSpxr6NLtRZMq7BPnTdQsDlzt01OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZPpm5InTdQsDlzt01OqmVDnSpzrDhInTdQsDlzt01OqmVDnT1Fs6lvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt01OqmVDnSNFsThvsThOtmdQ06NFoCcKsSYKdw1Ip2RIqmVRu2RUe3oJdzgKsSYKcw17j4B2gRYObzc0hQN9gAdvcyUPcM17j4B2gRYObzs0hQN9gAdvcyUOe017j4B2gRYObz4Q>tcik93nP8Kczs0hQN9gAdvcyUNc017j4B2gRYObz4T>tcik93nP8Kdg17j4B2gRYObzcU>tcik93nP8KcyUR;g02.8.w020>.g03.g.w02.k.w020>.w06.8.w01.8.M01.801M01.8.w02.8.w08.8.w01.8.g02.A.g0a.c.w020>.g02.8.g02.I.w02.8.w02.M.w02.Q.w01.8.w010>02w02.8.g010>.g010>.g010>.g010>.g010>.g010>.g010>.g01;g0108w4,g<8<1dFqgQ,w0Dgg[1.I0vwg.1=IV6m1w.3g2D1,4<1tFqgQ,M0Iwg.1<28Apo6,b0bM4,g<4SBF3g.2w2t1,4<9ihBwo,A0NMg.1<27Apo6,70d84,g<A96m1w.1w3t1,4<9uhBwo,k0W?.1;lqmAd,40fc4,g<K96m1w,M3Z1,4<7kqqgA,8020k[gTg[w{I0s[oTg[w{s0s[wTg[w{8dQ[wUw[w{2rE[EUw[w{6bE}10Uw[w{abE}18Uw[w{gbU}1wUw[w{dbE}1EUw[w{gbE}20Uw[w{mbE}28Uw[w{prE}2wUw[w{uXE}2EUw[w{xHE}30Uw[w{BrE}38Uw[w{EHE}3wUw[w{KHE}3EUw[w{KXA{UM[w{OHE[8UM[w{HHA[wUM[w{RXE[EUM[w{ErA}10UM[w{VbE}18UM[w{XbE}1wUM[w=bI}1EUM[w{3XI}20UM[w{8bI}28UM[w{crI}2wUM[w{hHI}2EUM[w{lrI}30UM[w{srI}38UM[w{uXI}3wUM[w{AHI}3EUM[w{sbU{V{w{ErI[8V{w{mrA[wV{w{HXI[EV{w{hrA}10V{w{LHI}18V{w{PrI}1wV{w{UXI}1EV{w{XXI}20V{w{1rM}28V{w{4rM}2wV{w{bHM}2EV{w{5bA}30V{w{eXM}38V{w{lXM}3wV{w{qrM}3EV{w{87I}3UV{w{8e8{Vg[w{6bE[wVg[w{_rA[EVg[w{46k[UVg[w{ge8}10Vg[w{gbU}1wVg[w{YXA}1EVg[w{k6c}1UVg[w{oe8}20Vg[w{gbE}2wVg[w{WbA}2EVg[w=7E}2UVg[w{we8}30Vg[w{prE}3wVg[w{THA}3EVg[w{A68}3UVg[w{Ee8{Vw[w{xHE[wVw[w{PbA[EVw[w{U64[UVw[w{Me8}10Vw[w{EHE}1wVw[w{KXA}1EVw[w{A64}1UVw[w{Ue8}20Vw[w{KXA}2wVw[w{HHA}2EVw[w{E5U}2UVw[w=ec}30Vw[w{HHA}3wVw[w{ErA}3EVw[w{k5U}3UVw[w{8ec{VM[w{ErA[wVM[w{CXA[EVM[w{E7w[UVM[w{gec}10VM[w{XbE}1wVM[w{zXA}1EVM[w{A5Q}1UVM[w{oec}20VM[w{3XI}2wVM[w{xrA}2EVM[w{g5Q}2UVM[w{wec}30VM[w{crI}3wVM[w{uHA}3EVM[w{Y5M}3UVM[w{Eec{W{w{lrI[wW{w{srA[EW{w{k5A[UW{w{Mec}10W{w{uXI}1wW{w{prA}1EW{w=5A}1UW{w{Uec}20W{w{sbU}2wW{w{mrA}2EW{w{M5w}2UW{w=eg}30W{w{mrA}3wW{w{hrA}3EW{w{47s}3UW{w{8eg{Wg[w{hrA[wWg[w{erA[EWg[w{A7s[UWg[w{geg}10Wg[w{PrI}1wWg[w{bHA}1EWg[w{A6w}1UWg[w{oeg}20Wg[w{XXI}2wWg[w{8rA}2EWg[w{s5w}2UWg[w{weg}30Wg[w{4rM}3wWg[w{5bA}3EWg[w{Y6o}3UWg[w{Eeg{Ww[w{5bA[wWw[w{2HA[EWw[w{85w[UWw[w{Meg}10Ww[w{lXM}3UTw}1&8TM[o,1m-gTM[o,1i-oTM[o<6-wTM[o,1a-ETM[o,1d-MTM[o,1j-UTM[o,1b+10TM[o,16+18TM[o,1f+1gTM[o,1p+1oTM[o,1g+1wTM[o,19+1ETM[o,1r+1MTM[o,1k+1UTM[o<B+20TM[o<C+28TM[o,1n+2gTM[o,1c+2oTM[o,1s+2wTM[o,18+2ETM[o,17+2MTM[o,1l+2UTM[o,1h+30TM[o,1o+38TM[o<@+3gTM[o,1q+3oTM[o,1-3wTM[o,15-0U{s<1-8U{s<2-gU{s<3-oU{s<4-wU{s<5-EU{s<7-MU{s<8-UU{s<9+10U{s<a+18U{s<b+1gU{s<c+1oU{s<d+1wU{s<e+1EU{s<f+1MU{s<g+1UU{s<h+20U{s<i+28U{s<j+2gU{s<k+2oU{s<l+2wU{s<m+2EU{s<n+2MU{s<o+2UU{s<p+30U{s<q+38U{s<r+3gU{s<s+3oU{s<t+3wU{s<u+3EU{s<v+3MU{s<w+3UU{s<x-0Ug[s<y-8Ug[s<z-gUg[s<A-oUg[s<D-wUg[s<E-EUg[s<F-MUg[s<G-UUg[s<H+10Ug[s<I+18Ug[s<J+1gUg[s<K+1oUg[s<L+1wUg[s<M+1EUg[s<N+1MUg[s<O+1UUg[s<P+20Ug[s<Q+28Ug[s<R+2gUg[s<S+2oUg[s<T+2wUg[s<V+2EUg[s<W+2MUg[s<X+2UUg[s<Y+30Ug[s<Z+38Ug[s<_+3gUg[s,1-3oUg[s,11+3wUg[s,12+3EUg[s,13+3MUg[s,14!:pC5Fr6lA87hL86dOpm5Qpi1xsD9xujEw9nc09ncW86VLt21xry1xsD9xug16jR9bkBlenQpfkAd5nQp1j4N2gkdb02ZApnoLsSxJ02ZQrn.hAZiiR9ljBZ4hk9lhM1QsDlB06pLsCJOtmUwmQh5gBl7ni15rC5yr6lA2w1Jrm5Mey0BsM1KlSZOqSlOsQRxu01KlSZOqSlOsM1Kj6BKpnddonw0rA9Vt6lPjm5U>5ihRZdglw0biRTrT9Hpn9PbmRxu3Q0biRTrT9Hpn9Pc3Q0biRTrT9Hpn9Pfg0JbmNFrClPbmRxu3Q0biRIqmVBsP0Z02QJr6BKpncZ02QJoDBQpncJrm5Ufg0Jbm9Vt6lPc3Q0biRyunhBsPQ0biRIqmRFt3Q0biRQqmRBrTlQfg0JbmtOpmlAug0Jbn9Bt7lOryRyunhBsM0JbmZRt3Q0biRQqmRBrTlQ02lA>lmhAhvkABehRZ4glh1>lmhAhvkABehRZ5jQo0hlp6h5ZiikV7nQBehQljl5Z4glh1>lmhAhvkABehRZ9jAt5kRhvhkZ6>lmhAhvkABehRZjl45ilAk0pCZOqT9RrBZLtng09mNR2w1TsCBQpixCp5ZPs65TryMwsS9RpyMwsSNBryA0pCZOqT9RrBZOqmVDbCc0tT9Ft6kEpnpCp5ZAonhxb2pSb3wF07wa07tOqnhBa6pAnTdMontKb20yu5NK8yMwcyA0tT9Ft6kEpnpCp5ZBrSoI82pBrSpvsSBDb20Uag1AsDA09ncK9mNR0599jAtvikV7hldknQh9lABjjR80kABehRZ2glh3i5Z9h5w0kABehRZ2glh3i5Zjj4ZkkM16h5ZfkAh5kBZgil1507tOqnhBa6pAb20CtC5Ib20Uag1TsCBQpixCp5ZIrSdxr5ZPqmsI82pLrCkI83wF06pLsCJOtmVvqmVMtng0rmlJpChvoT9BonhB86pxqmNBp3Ew9nc0s6BMpi1ComBIpmgW82lP06dIrTdB07dMr6Bzpi1ComBIpmgW82lP0595k4Np03.tT9Ft6kEpnpCp5ZAonhxb20CrSVBb20Uag1FrCc0p6lz05d5hkJvkQlk05d5hkJvhkV402lIr6g09mNIp0E0sSxRt6hLtSVvtM1Pq7lQp6ZTrBZO07dEtnhArTtKnT9T07lKqSVLtSUwoSZJrm5Kp3Ew9nc0sCBKpRZFrCBQ079FrCtvp6lPt79Lug1OqmVDnTdzomVKpn80sCBKpRZzr65Frg1OqmVDnTtLsCJBsw1OqmVDnSdIpm5Ktn1vtS5Ft6lO079FrCtvqmVDpndQ079FrCtvpC5Ir6ZT079FrCtvomdH079FrCtvrT9Apn80sCBKpRZzrT1V079FrCtvsSBDrC5I06NPpmlH079FrCtvqmVApnxBsw1OqmVDnSpBt6dEpn80sCBKpRZComNIrTtvs6xVsM1OqmVDnSRBrmpAnSdOpm5Qpg1OqmVDnTdBomM0sCBKpRZCoSVQr01OqmVDnT1Fs6k0sCBKpRZPs6NFoSk0j6BPt21IrS5Aom9Ipnc0sCBKpRZIqndQ85Jmgl9t05dMr6Bzpi1Aonhx>dOpm5Qpi1Mqn1B079FrCtvs6BMpi0Ygl9iv594fy1rlR9t>pFr6kwoSZKt79Lr01OqmVDnSpzrDhI83N6h3Uwf6dJp3U0kSlxr21JpmRCp01OqmVDnTdBomMwf4p4fw13sClxt6kwrmlJpCg0sCBKpRZJpmRCp5ZzsClxt6kwf5p1kzU0k6xVsSBzomMwpC5Ir6ZT>Vljk4whClQoSxBsw1elkR184BKp6lUpn80kSlBqO1Cp01IsSlBqO0YhAg@83NfhAo@byUK05dFpSVxr21BtClKt6pA079FrCtvsSBDrC5I83N6h3U0mClOrORzrT1V86BKpSlPt01OqmVDnSdLs7Awf4Zll3Uwf4Befw1ipmZOp6lO86ZRt71Rt01OqmVDnSZOp6lO83N6h3Uwf516m7NJpmRCp3U?mdH869xt6dE079FrCtvomdH83N6h3Uwf4p4nQZll3U0j6ZDqmdxr21ComNIrTs0kSBDrC5I86BKpSlPt013r6lxrDlM87txqnhBsw1nrT9Hpn8woSZKt79Lr01OqmVDnTtLsCJBsy1rqmVzv6hBoRQ?SNxqmQwoC5QoSw0sCBKpRZzr65Fri1rlA5ini1rhAht059Rry1PoS5KrClO079FrCtvsSdxrCVBsy0YpCg@85JPs65TrBZCp5Q0h6lPt79Lui1OqmVD>BKqnhFomNFuCkwsCBKpO1TqnhE86dLrCpFpM1OqmVDnSBKqngwmQpcgktjng1OqmVDnSNFsTg}1FrDpxr6BA86VRrmlOqmcwqmVApnwwpCZO86BKp6lUpmgwon9OonAW82lP}LsTBPbShBtCBzpncLsTBPt6lJbSdMtiZzs7kMbSdxoSxBbSBKp6lUcOZPqnFB.1CrT9HsDlK85J4hk9lhRQw9ncW9mgW82lP86pxqmNBp3Ew9nca<tT9Ft6kEpnpCp5ZFrCtBsThvp65QoiMw9DoI83wF.1TsCBQpixCp5ZComNIrTsI82pFs2MwsSBWpmZCa6BMaiA{pCZOqT9Rry1rh4l2lktt879FrCtvomdH86NPpmlH86pxqmNBp3Ew9nca[tT9Ft6kEpChvs6BMpiMw9CZMb21PqnFBrSoErT0Fag1TsCBQpixCp5ZQon9DpngI82pFs2MwsSBWpmZCa6BMaiA{tT9Ft6kEpChvpSNLoC5InS5zqOMw9D1Mb21PqnFBrSoEs70Fag,6pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME,1CrT9HsDlK85J4hk9lhRQwsCBKpRZzr65Fri1IsSlBqO1ComBIpmgW82lP2w<1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ}1OqmVDnSpxr6NLtO0Yk4BghjUwf4p9j4k@85JAsDBt02ZApnoLsSxJbSpLsCJOtmULt6RMbSpLsCJOtmUKm5xo?(1Y07w0t01M06M0q01A06.n01o05g0k01c>w0h01.3M0e.Q03.b.E02g08.s01w05.g.M020><1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3wYe3gMb2wA81Mo510c2?0f3wQc2ME920s61gg30w401<2;5<hQVl0>.s><eg{2.701;Q=hI3eOg1,z<84f/Q01.3Mh/_q>.31a/_w?.84L/MM2.1wjf/c08.f1o/@.w.Q7X/@w2.2wv/_d0c,22/@.M.A8f/YM3,wy//0c.72m/ZA1,k9z/Xg4.2wCf/R?.f2o/_Q1,c9D/Ng5.20Cv/d0k.22t/ZY1g.s9T/VM5.30Dv/L0k.82u/_E1g.Q9X/Mw6.30Ev/l0o.12y/ZQ1w.Mab/Ww6.20E/_P0o0>2B/Y01M.8av/QM7.30Gf/u0s0>2T/@E1M.Mbv/Z07.3gKf/_0s.32W/YU2,kbL/SM8.30LL/E0w[k=5Wkw01u1016MM72901,A<7<dx1/Y01;UghwUoiwYbtMy.3YqeOEP928;t<4g,20hL/dg8,1b3x2e0A8e68Q3gwUwz0h93yy61k4ec8c6hMVgo0Eec4D33yx1NwUwgIMe64bd3x12PwU8i0I3s>a3z14MMUEgsoe84bc3xx2PgUggIUe24Qbs0U8MYrcPsV83B231Eo5z0id0UU2a<bM,18if/Xw<113x230AAek4Ua3x113wx72M9i2wUghgU8igIw<W;N9/YP?,44e48c2jwVw0Bka3x133wx92M1c<3>.2xa/@53<48e48Y2gwUozwd23y2d14kea8M5ggUMxwp13zy31Qsew0A3Tg4a3zx13z113yx23y123xx23x123wx52M,6g,1s?.q5r/ZIB<iMUgzM973xye0Q8e88Q4gwUEz0l13z261Agee8c7igWg0Mcc3gU8MYrcPsXfk0Wg0Uc7xwqc1oQ4zwef0wbT2wUUgMUMggUEgwUwgwUogwUggwU8ggI0i<cg1.3wu/_O;123x2f0A8e68U3hgUwzgh23yyc1k4ec8o6ggUUwMt43B02DgEee4gec44ea48e848e648e448e24kb>w<g0w.p7P/Ro2<kwUgzM9a3xye0Q8e88Q4gwUEz0l13z261Acee8c7iwXw20bz2wUUgMUMggUEgwUwgwUogwUggwU8gMJ8<n08.7x@/@4?,58e48Y2hMUozwd53y2d148ea8M5ggUMxwp13zy31QEeU0w3iM4ee4cec44ea48e848e648e448e2,b<aw2.2Yv/_A0s,1h3x260Awd1Aif0UU4i8Q5z0q31Mdf0MEc1Mx42M.p<dw2,sx/_jwI,1b3x2f0Ase68U3gwUwzgh53yyc1k4ec8o6h0UUwMt93K030_Q12wUUggUMggUEgwUwgwUogwUggwU8gwI2I0U8MYrcPsXfk0Xw0Uc7xwqc1oQ4zwef0w1c<g0c,ii/_n?,58e48Y2hMUozwd23y2d148ea8M5ggUMxwp13zy31QEeA8840OU12wUUggUMggUEgwUwgwUogwUggwU8hMI.1M,2g0M.B9f/Qk;ggUgwM993z1T3x133ww07<b03.34A/_hg<113x230AAec7se44ce2.s<Q0c.fij/Y_;44e48c2igUwsgUggMU801M,3M0M.59j/Qk;ggUgwM993z1T3x133ww0h<1>.14Bf/Cgc,123x2f0A8e68U3gwUwz0h13yy61koec8c6hMXM?eJ?Eec4cea44e848e648e448e244b<7<5w4.2sB/_hg<113x230AAec7se44ce2.s<u?.cOn/Z5;44e48c2igUMtMUggMU802w,2o1,_9v/Y:ggUgxw963xy30Qgec09c2wUogMUgggU8hgI07<cg4.2gCf/hg<113x230AAec7se44ce2018<V?.c2o/_E0w,48e48Y2gwUozwd23y2d148ea8M5ggUMxwp13zy31QAeA05E2wUUgMUMggUEgwUwgwUogwUggwU8igI07<305.1AC/_hg<113x230AAec7se44ce2.M<k0k.9ir/@A;48e48U2ggUoxwd63y2314gek09A2wUwgMUoggUggwU8igI08<8g5,gDf/Lw<113x230Agec09q2wUggMU8hwI0c<aw5.2IDf/IM4,123x2e0A4e68o3hwUwwMh43B02IMEe84ce644e448e24Eb>w,3s1g.e9X/ZY1<gwUgzM923xye0Q8e88Q4gwUEz0l13z261Aoee8c7h0VwrMEee4cec44ea48e848e648e448e248b,E<a0o.cOv/@v?,44e48o2hwUowMd43z02PwEe64ce444e24cb02M,1k1w.ga7/TMe<ggUgxw933gp9zMee18Q5z0q31Mex1wEc1Mx22M,2g,241w.Aa/_To;ggUgxw963xy30Qgec09C3xx33x113wwE<H0o.eyL/Y7?,44e48c2igUMpwEe44ce24kb0Gka3x133wx82Pw,3o1w.Pb3/R81<gwUgzM923xye0Q4e88o4ggUEwMl43D1N2wUEgMUwggUogwUggwU8hgI.3;k1M.Yb7/No1<gwUgzw913xy60Q4e88c4h0UMqMEe84ce644e448e24sb,M<i0s.dOO/ZG0M,48e48U2ggUoxwd13y2314gec0cw0wEe84ce644e448e248b6<7M7,oJL/wg4,143x03v>e2|~~~~~~-//_M<2M1M}707[8dQ[1{7U4{g[281{M{P08[d{1i{6g{gTg}1I{2=q{1zt[7=8{fn@_SY:9{5{7yp[1w[30A{E{50k[b{1w=M[3ETM[8{W0k[k=s{5M[28HM[s{aa{8{60f[2g{o{fX/SY;i9Y}3/_ZL:8{Yf/rM<2cDw}fD/SY;xM~~~~~~~~~~!;2zt!o3[5wc[C0M}3o3[hwc}1m0M}6o3[twc}260M}9o3[Fwc}2S0M}co3[Rwc}3C0M}fo3[1wg[m1[2o4[dwg}161[5o4[pwg}1S1[8o4[Bwg}2C1[bo4[Nwg}3m1[eo4[Zwg[61g}1o5[9wk[S1g}4o5[lwk}1C1g}7o5[xwk}2m1g}ao5[Jwk}361g}do5[Vwk}3S1g[o6[5wo[C1w}3o6[hwo}1m1w}6o6[two}261w}9o6[Fwo}2S1w}co6[Rwo}3C1w)/////////////Y;/////Y9Kw}1yW#2yW[gbU#dbE}10Kw$1oKw}6mW#7KW[xHE#BrE}2yKw$2WKw}bKV#cGW[HHA#RXE}2xKg$3AKw}eOW!2X[3XI#8bI[NKM$16KM}5mX#76X[uXI#AHI}1MLw$2xKM}5CV#a@X[hrA#LHI}3dKM$3zKM}e@X!mY[4rM#bHM[kKg#XL[5uY#6CY[87I[1{23y[6bE`3ZKg}11B{g[10Uw}42@~YXA}1goM[4{oe8}10Kw`eyV{7E[1{83y[prE`3uKg}91y{g[2wUw}8qW~PbA}3wog[4{Me8}2yKw`bKV[A64[1{e3y[KXA`2KKg}a1u{g=UM}aWV~ErA}1gnw[4{8ec}2xKg`9KV[E7w[1{43z[XbE`2fKg}91t{g[1wUM[@X~xrA}10ng[4{wec[NKM`7GV[Y5M[1{a3z[lrI`1NKg}51p{g[30UM}7KX~prA{mg[4{Uec}1MLw`5CV[M5w[1=3A[mrA`15Kg}11T{g{wV[4mV~erA}2gtM[4{geg}3dKM`2WV[A6w[1{63A[XXI~xKg}71o{g[20V[16Y~5bA}3Mpw[4{Eeg[kKg~GV[85w[1{c3A[lXM)4t3gPEwa4teliAwcjkKcyUN838MczkNcz4N82xipmgwi65Q834Rbz8KciQRag<w<g:40>t19>Poj40P08[xw=KsSxPt79Qom80bCVLt6kKpSVRbC9RqmNAbmBA02VFrCBQ02VQpnxQ02VCqmVF02VDrDkKq65Pq.Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bD9Lp65Qog0KrCZQpiVDrDkKs79Ls6lOt7A0bClEnSpOomRBnSxAsw0KpmxvpD9xrmk0bDhAonhx02VQoDdP02VFrCBQnS5OsC5V02VCqmVFnS5OsC5V02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpSZQ02VDrTgKs6NQ02VAonhx02VysTc0bCdLrmRBrDg0bCtKtiVytmBIp2Vxt7hOqm9Rt6lP~~=.2M<s<2{aw2[G08[A*1*1U<1<1w[3c0w}cM2[6M*g(1R;g<o{Y08}3M0w{4(g{1=9;4<6=07=s[hug)g*2E<1<1w{kw[1i{3g*g*M<ZL/rM8=9=A[c=1M{8*ew<I<2{c2g[M9[2U2{w<1<2=o{48<3;w[1UCg}7yp[50k(4(1a<//rM8{z9U}2cDw}bE{1M{2=8{lM,fX/SY2{4yv[i9Y}3w=w<2<2*6o<4;w{EE[2yw[o0Y[7=w{6{1M<1<48{yaY}28HM}ew5[1M,1w<8{1w{uw<4<2{82R[wbk[w2w)g*88<7;w[2wLM}a2_[c&w(2l;g<8{QbY}3gLM}2g1(4*EM<4<2{fz{@c[2o1M)2*aQ<1;Mg[8Tg[zd[1&w(2Q<2;c4[4dQ[gPg[Q*8*Kw<U<3{13t[4cQ[8*2=8{co<f;M{oTg}1zd[2&w{2{3i;g<c{8dQ[wPg[w*8*TM<o<3{2zt[acQ}3g?[w{2=g{ew<1;M[3UTw}fze[Y&w{2{3J;g<c{WdY}3EPM}102(8=w{Zw<4<3=3y{d8}1g2(8*fM<8;M[1gWw}53q[a&w*1?,g,3*1gSw}2U*1=4{2w4,s+7wa?:wdE[A*1&4<3^ajq[8>(4(')


_forkrun_bootstrap_setup --force

