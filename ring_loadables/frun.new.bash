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
    while ring_claim OFF CNT $fd_read; do
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


declare -a b64=([0]=$'108174 54088\nmd5sum:d272d8c8b592c69f73dd1ac842fcd033\nsha256sum:ef324603bcd87fc83ca2ff5325b0ccd3f6fc93633a791f2b4928f5b96c2c9e4a\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\npCoK3N@4\n00000000\n0000000\n000000\n00000\n0000\n000\n04\n1M\n0g\n00\n__\n0S6bNTkzHSSbN_kx_mLZcet1RQQMVNM@4w;4O9O4i9MAMFM4C9@AQFMASdmLZ9w_Iutzddas5yQnYErQ7_NedZhI\034vQlchw81.+?c0fw01-1+czb+<4?e?b,?7w0t0,;5!}QnY}3hvM=g=g;g:w=2+8[2ge[90U=1=1;1w;yZ[2cQ[8Pg}4wd[s0Q=4=8;6;abQ[EPg}2zd[Q,}3g.[w=1:g<2E0w}aw2[G08[A=2g=1+4;1;a2L[EaY}2wHM}3+c+8+s;4;2bQ[8Pg[zd[1+l+w=k@lQp.<2wHM}a2L[EaY[M=3+2=1gVnhA1;d2L[QaY}3gHM}2g1[9,[4=57Bt6g6~)?1+kKlQp.;8Lg[zd[2cQ}3U0w}fw2=g=4;5:c<17jBk0CoBmT8hnkkzM35JjS9QfjXUhjLDP3NXWi8fI24yb1pTc?18xs1Q0L_gi8f42cc+03_dvHc?3_9vPc<f7Q?_OnWP<q:3FUf//YBYIM?6w1;Wt3//_9uHc?1E0w<eD0//_OnyP<q0c<3FIf//YBSIM?6w4;Wq3//_9tbc?1E1g<eCg//_OnaP<q0o<3Fwf//YBMIM?6w7;Wn3//_9rHc?1E2;eBw//_OmOP<q0A<3Fkf//YBGIM?6wa;Wk3//_9qbc?1E2M<eAM//_OmqP<q0M<3F8f//YBAIM?6wd;Wh3//_9oHc?1E3w<eA0//_Om2P<q0Y<3FYfX/_YBuIM?6wg;Wu3@//9nbc?1E4g<eDg_L/_OlGP<q18<3FMfX/_YBoIM?6wj;Wr3@//9lHc?1E5;eCw_L/_OliP<q1k<3FAfX/_YBiIM?6wm;Wo3@//9kbc?1E5M<eBM_L/_OkWP<q1w<3FofX/_YBcIM?6wp;Wl3@//9iHc?1E6w<eB0_L/_OkyP<q1I<3FcfX/_YB6IM?6ws;Wi3@//9hbc?1E7g<eAg_L/_OkaP<q1U<3F0fX/_YB0IM?6wv;Wv3Z//9vHb?1E8;eDw_v/_OnOOM?q24<3FQfT/_YBWII?6wy;Ws3Z//9ubb?1E8M<eCM_v/_OnqOM?q2g<3FEfT/_YBQII?6wB;Wp3Z//9sHb?1E9w<eC0_v/_On2OM?q2s<3FsfT/_YBKII?6wE;Wm3Z//9rbb?1Eag<eBg_v/_OmGOM?q2E<3FgfT/_YBEII?6wH;Wj3Z//9pHb?1Eb;eAw_v/_OmiOM?q2Q<3F4fT/_YByII?6wK;Wg3Z//9obb?1EbM<eDM_f/_OlWOM?q3;3FUfP/_YBsII?6wN;Wt3Y//9mHb?1Ecw<eD0_f/_OlyOM?q3c<3FIfP/_YBmII?6wQ;Wq3Y//9lbb?1Edg<eCg_f/_OlaOM?q3o<3FwfP/_YBgII?6wT;Wn3Y//9jHb?1Ee;eBw_f/_OkOOM?q3A<3FkfP/_YBaII?6wW;Wk3Y//9ibb?1EeM<eAM_f/_OkqOM?q3M<3F8fP/_YB4II?6wZ;Wh3Y//9gHb?1Efw<eA0_f/&4ydfkDj?18zgl2QM?i3DUt1l8yMn@NM?i8n0t0D_U0Yvw:333N@]4ydfhDj?18zjkiQM?i2D@i8DMic7KfQz1@0d80sp8QvVQ54yb1mT8?18xs1Q2f_wpwYvh<MMYvw:3P3NXWw3TlQw<7kHlky3flb8;i8DBt0N8zjSeNg?W0D//Epf/_Yo5Ht8<5tMMYv0ccf7U]YMYu@KBT//3N@]4y5_M@4>80,5mgll1l4C9ZbVr;lld8yvJ8w@MwW1LY/Z8ysl8xs1Q3Qy9T@zH@/_w7M3_RRQ74y3N21cyup8ytYNQBJtglN1nk5uWiLZ/Yf7M19yuV8wYk1iiDuioR@0uxl_f/i8Duj8DOioD5i8D7WfjY/Z3NAgR?18yu_EBLL/QydkfZ8yst8yggAi8Bk90zE8vP/Qybl2g8i8DKi8D7i8D3WbXY/Z8yMMAj8DLNAgb_M3EnvL/Qydu07EZfL/QO9XAy9N@zF@L/i8Dvi8D5W3XX/Z8znw1WdnX/Z8ytV8ysvEOLH/QO9VQC9NKwv@/_i8RU0uyS@/_j8DCi8D7WaLW/ZcyuZ9ysjEgfL/Qy9T@wU@/_i8DLW13W/Z8xs0fxdY<2bk2zSMA1RnUfy10@4Hw<4z7h2go:ew8@L/i8RQ91yW2w<4O9ZYs]4y9M@wJ_f/i8D6i8J491x9espQo80U07lrwPIyt5oNOkO9UAy9X@x9_f/WNIf7U]hj70j8Dxj8DOi8DKi8D7W4PZ/Z8yu_EFfH/QO9Z@ys@L/i8f484O9VRJtglN1nk5uWozW/Yf7Ug]4O9ZAydfpWy<NMeyv@v/WY4f7Qg0,y9XAydftCr<NMey7@v/WWAf7Qg?ccf7U]i8DLW73W/Z8yuV8zjSmCM?i8n03Uk6//WYZCpyUf7Ug]5e_Mw<4y3X43E4vP/Qy5M7Uci8f4g5L3pwYvh<i8QZkq8?37Scs3EIfL/UD7xs1UarEv;i8RQ9229h2gcW7vW/@bv2gci8A49ewW@L/i8Ik94y5QDYxLXY<3EJ_L/Qy5M7Vqi8f4g4z1U0drMMYvx}NAgk8018zngA6bEa;i8RY923EN_z/Qybl2go3Xoiw@bvwfFbt3Z8ys58Mu4kwfFdi0Z4Mky5M7izWlf/_Yf7U]LY8<3EjLL/Qy5M7@nK<g03Fc//MYvw:18Mu0aWYBCA5d8yvJ8zjSNCw?i8fIkeyc@L/i8n0t5u0e35RkE1U.1RjbG0.?LE8.g18zjSuCw?cs3EJfH/UD2xs1V7HG0.?LE8.g18zjS9Cw?cs3EBLH/UD2xs1Um4y3N529Q5L33N@4]2W0w<4y9THY_.?cs3EHfD/UD2xs1VRKyxZ/_wPwmtp0NQAy9THY_.?cs3Ey_D/UD2xs0fy7n//HHMYvw:35@mY5Ua80,ydv2ggibwKm5xom5xo,y9v2g8i8B49235@nZ4913E_fz/Qybv2g8xs29MDwpylgA2ex8Z/_yRgA2eBv//3N@]cnVrMmwEw?NQgA85xom035@nZ4913ELvz/Qybv2g8xs29MDD1WiT/_ZCA6pCbwYvx}glt1lA5lioDRglhlkQy1X4w4?29f2h8zjS3Cg?W3TV/Z8xs0fx>1?20e34fxdI1?18zjlPCg?i8D7W7PU/@5M0@5_;4yb1lT3?2W6;bU1;i8QZk9A?cs5QIQ<4<18yMzEGLD/QObfrLd?1dxvYfxtM<15csAN_Q6U//_XAx;Kwc<2@012w0eyr@f/i8fU_M@4qgE?37SKw.E018yst8yglUPg?W6LT/@_l;ewx@v/i8QZ09A0,y9M@y2@f/i8n0t1CW2w<37Si8D7W3XU/Z8ykgA24y5M7Yii8nrgrM1;j0ZfUQO9p2g8i8QZPpw?ex6@f/i8n03UjZ;cvqW2w<4y9N@z@Z/_i8n03UXB;i8B4913FV:Yv,ObfuDc?371uvc[jon_3UgA//iss7:4yb1szc?18NU<g}4yb1rrc?36w1w1;i8I5GcM0,z7g1]i8I5CsM0,z7g2]i8I5yIM?cp0a018yMl_P<ict0c:18yMlMP<NA0F08IZ5Ig?8n_ui0NM4y1N4w4?1rnk5sglR1nA5vMSof7Qg?8IZYIc?bE01<i8RQ943Ey_r/Qy5M7_CWYEf7Q?w7w1?@4cLX/@Am_L/A4z7h2gg.<4ydfrKn?3Ea_v/Qy5M7gucvqW2w<4y9N@zDZL/i8n0vwF8ykgA6eIc3NY0ict491w,<LXY<3Exvv/Qy5M0@ej0w0,Odd419MuU2cv_Ervv/Qy9MQy5M0@eIgw0,yb1rH<18yOx8yTQ0i8n_3Uit0w?hj7A3N@]ezXZf/i8JZ24y3Ngxdzmg40ky5_TnFLg1w?1ceucfzSI2?18zjQpBM?W7_S/Z8ysd8xs0fxcc7?20e4MfxgE2?20u,O3Uk?w?w7w2?@5Zw40,yb7ivb?18yQgA24y9wOw1?18yQgA44z7wP01<1;i8C38,0,ybh2goj8CPk,0,y9wPw1?2b12h8NUd0.}4z7wRw1[NEdw.<8fU.@eg0w0,z7h2g8//_QSdpgy3W098NMgA//_QSdrckgj8DBi8Jt0bEe;i8QRpVo0,y9T@xEY/_xs0fxbw1?2W2M<4yddlGm?18yt_Ejff/Un03UhA1g?KwE<18zjlaBw?i8DvW33P/@5M0@4u0k?bEc;i8QRepo0,y9T@wkY/_xs0fx9g5?2W2g<4yddiGm?18yt_E@fb/Un03UiE1g?Kww<18zjkoBw?i8DvWdPO/@5M0@4d0o?bEc;i8QR1po0,y9T@z0YL/xs0fx8w6?2W2g<4yddvql?18yt_EFfb/Un03Uhk1g?Kww<18zjnABg?i8DvW8zO/@5M0@4c0s?bE8;i8QRQpk0,y9T@xIYL/xs0fx2U7?2W2w<4yddrWl?18yt_Ekfb/Un03UiS1w?Kww<18zjmJBg?i8DvW3jO/@5M0@56gs0,yb1kT9?18NU1o.}eCl;3NZ4?18zjnUB<i8DvioDKWaXP/@5M0@4YfT/XEa;cvp8yt_EV_b/P7ii8n0i0Z9Q4C9RKDg_v/pwYvh<j2Dzi8Doic7w14wFS4z1@0h8zgh0ic7E0Ay9NuBQ_v/3N@]37Si8RX3HEa;WbzP/Z8xs1@4Qyb5rj8?18yo8E.?3NZ4?18wYk8ijDJ3UnP_v/i8I494yb7p38?18xs0fxas4<fyk44?18wTMA2?fzzk4?36wS01<1j8JQ90xcyrcM.?cuRcyrcU.?j8CPi,?6oK3N@4]19yPMAKwA<18zjmhB<W0LN/@5M0@kM4C3N0w9NkQVVnnrg8jJtgJ8NUdo.?//_QybyO01?18yVcE.?NEdy.<g@SwS01?18et4fB8dx.?xc0fxfg3?18NUc8.<g<37_Lw48203EFLf/P7_Lw4820291mC_?3EBff/P7_Lw0820291le_?3EwLf/P7_Lw4820291jS_?3Esff/P7_Lw0820291iu_?3EnLf/Qydfi@_?291h6_?3EHf7/Un03Uxk0w?yPQmLM?Kw08?2@1;370WdTO/@bfge_?2W?w?370Lwg<3ENLb/UIZWbU?bE1;cs2@0w<eyLYL/yPTlLw?Kw4;NMbU2;W9zO/@bfrW@?2W<g0370Lws4?3Ewvb/UIdCXU?bUw;cs18zhl8AM?i8RY923EE_3/P7ii8RQ9218zjQPAM?Wa3N/@b3mq@?2@8;370i8Ql5Vc0,ydv2gwW7bM/YNQAydt2gwi8QZ4pc?exLYv/yMQNLw?Ly:NM4yd5uqi?18znMA8ex1Yf/ct98zngA84ydfuWi?3EfL7/UId_bQ?bUw;cs18zhmRAw?i8RY923E4f3/P7ii8RQ9218zjTjAw?W0TN/@b3suZ?2@8;370i8Qlx980,ydv2gwWd_L/YNQAydt2gwi8QZJV8?ezsYf/jon_3Uip@v/j8D_W8LK/Z9ysh8xs0fx1g3?3Sg2w43Ug20M?i8I5RIk0,ybK2w1?18Mus2WdXL/Z9ysl8yMmYNg?i8eUa,;fxco2<NSQydr2h0WQEf7Qg0,69h9Q0ys58zhnRAg?cs2@8;4y9X@xbX/_i8DucsB8yuFcyut8wYc1WdvK/Z8yMlENg?i3Koa,<@3sM80,ydfhei?3ER_n/Un0uqK5STgwi6frj8DJioRsDg0f7Q?yTQ0i8f51exkX/_i3DHtuZcyu_ER@X/MYvw:2U.<eCK@f/pwYvh<cvp8znIbKwE<3EYe/_Qy5M0@eh_P/Qyb5uz4?18yo8w.?WjjY/Yf7Q?cvp8znIaKwE<3EMe/_Qy5M0@e5_P/SbO_gxYM4yb1rb4?35@n@08,?eDZ@/_3NZ4<NZAyduMOW2w<ey8X/_i8n03UXv@/_i8Ilwcg0,y9wzw1?3FPfL/MYvg?NZAyduMCW2w<exoX/_i8n03UWL@/_i8Ilkcg0,y9wz01?3FDfL/MYvg018yUcw.?j8KPc,0,y9h2ggi8K3a,0,y9h2g8i8K3e,0,y9h2goi8Jc90z6wS01;i3Bc910fB8dx.?j3JQ91wfB8dy.?j8CP2,?eAb_f/3NZ4?36wS01<1i8dY90w03UVA@/_WlHX/Z8znI8KwE;NZKygXv/i8A494y5M0@e0_L/SbO_gxYM4yb1pX3?35@n@0c,?eDF@L/pwYvx}ijDKj0Z7ZuBe@f/3NZ?b_2;W2rL/Z8xs0fzW7T/Z1Lw?1w3FDLv/Sqgcvp8znIcKwE<3EgeX/Qy5M0@eB_H/SbO_gxYM4yb1jb3?35@D@0i,?eBZ@L/3NZ4?3EQ@L/UIUW3PL/Z8zjSyzw?i8D6cs3EW@L/@DC_v/pwYvh<Lg?603Fy_v/Sof7Qg0,O9X@yoXf/WnDS/Zcyv_Eu@T/QO9_@yPXf/ioD4i8n03Uny_f/WqbZ/Z8yMSPMw?i8RX2HEa;cvp8ykMA4exSXf/i8Jc9118yo5o.?WunV/Yf7Qg0,6@.<eBE_L/3NZ4?18znI8KwE;NZKx0Xf/i8B490zFJLD/XEa;i8RX237SW2rI/Z8yNl7Mw?i8C2g,?eCj@v/Kwo<18zjm1zw?i8DvWf_G/@5M7k9j8RX1KBO@v/w3IJj0Z5@@BC@v/pwYvh<w_Y13UX_3<gluW2w<45mgll1l5l8yvljyvJ8wuNo.?i8J@237SWd7I/@9x2ig;w_I23Ukn1g?NEgAV:37x2jk;//_Qyb1q_1?18NMmsMg}4z71oD1[i8Koc,0,y9n2gMi8Koe,0,y9D2jE;i8Ko8,0,y9n2gwi8Koa,0,y9D2j:i8Kok,0,y9n2h8i8Kog,0,y9n2hgi8Kom,0,y9D2jo;3Xqoo,?8xs96wfJFxy.?y9MAUg;@SC641?3EH_3/XU?2?ic7E0Qw5/Yv,wB?3w_Qy9NXw;2i3D7i0Z7@bw?2?i3D7i0Z3NQydL2jU;i8D2i8B492zEWKP/QybL2jU;i8BY93y5M0@5Ghs?8KY99;2W.<37Sj8SY9101?3ECKP/QO9_HY6;j8BY9418ykgA2ez3Wv/K0c<34ULLTB2go.?ibzfZRfzFpL484zTUAxFz2gg.0.48f,z1Wwh8zgghi8B497x8yMlfM<icu<4}18yMkZM<ics]4yb1i_<18NQ0M:4yb1i3<18yQMA84y9i0x8xsBQ3E2Y9eg:3Umt4<i8dY94w03Xp496z6h2hM?@lx2jw;xdJ8ySMAe4ybn2gU3Vi49e8;ax2jx;y8gAQM<4ybh2g8icu49bw=i8B49618NQgA6:18NUgAw=18NUgAy=18NUgAC=18NUgAE=18NQgAm:37x2ik=ct491]3Vi49ec<15cuh8etR13Vf5csB42CMAs0@5Uhw?81Y96w03UjG;i8J49518zn3_i3JQ91wfwwIb?143XpQ9119ytZ8yQgAc4AFXQ63Vw51w_o1ijD73Uen0w?jon_3UhK0w?i8IRXXU?8dY91013UjI2g?yQooxs1Q9ky3L2jo]@4RwA?7Uki8eY9bw:3Unn4g?3NZ4?18yTMA24y9W4wHh2gUioDej8QYe8KY99:NQAO9_KybWL/j8JI93x8yRgAa8KY99;1cyuXEQKz/Qy5M0@eL0A0,O9XkCdn0k0j8BY90xcyv77h2gg:4kNXo1Y96w03Ukm//i8J49318es4fwQk8?18asx9yst8yQgAk4ydsfZ8xs0fxgI1?14y6MAs4wVTg@3BxQ0,z7NL//Z1Lww<1caTgAo4M3t2g8ioDJi8Cc9aw<1cyvl5cvp43XqA9e;18yrgAI;eIB3NZ0,y3M059wYo1ioD5i8f524QV_w@3C0s0,wVS0@3zMs0,y9SHUa;j8DLj2DGWePD/Z8xs0fx6c8?1dxvofBs948e9QK4y3M058ysp8aTgAe4w1XAwVt2h8sWp8yUMAG;4M1t2goj8DJgoDki8KQ9b;1c0v59etR13Vb5pF1CpyUf7Ug]4wXt2gosRZ8xsAfxkkb?15xeRQrYt49101;i8dY93?3Uho2<j8JY9318yQgAk4wHh2goijD7j0Z7@4y5M0@560w0,wVTki8r2hMNQgA4,<113Vb5hj7Ai3JQ91xOEg@Sh2ggw@01ysa3Yw512tl8xsAfxn49?15xeRRj4C9XQC9PAybbq@Y?3Fn0c0,ybvh2W2w<37SW9HD/@9x2jk;ZZ31W1@9x2jA;WtjW/ZCA4wVTk4fAIl52fkfx688?23v2gg.@4bvT/@CM_v/j8Rk1g18yPlsL<ioD7icu49bw=ijDq3Va49aw<18aSMAe4w3r2g8j8Bk971c0vTHgmof7Qg0,ybty18yMklL<i8Il1HM0,y9MkwFYky1@v/3M0fxJI<18es9O9HZA;W6PE/Z8yPnJKM?3Xp6a8j0trR8yPrHL0Yvx}i8I5QrI0,ybk0x8yNm@KM?i8Cg0,0,yb1r2X?18ygmxKM?i8I5GHI?8J068n0tal8yTgAg8IZgbc?bE8;icu49101<1;WcHA/Z8w_z_3UlW//yPlWKM?xvofx6P//E7uj/UIUW8rD/Zczgliy<KkY2?18zhkTy<ioD1i8I5Kr<4yddnGd?18yPwNMez8Vv/WiT/_Yf7M18yTMAo4ybdhOX?1cyRgAs4y9@kwfKKA_i8dY9301i0Z4PQy9NQy3M061V/_3M18ygnFKw?i8Cc_w.802V.<6q9z7U,<i8D1wu7/MY0i8CIPw.8018es8fwxE5?18yQgA84M1v2hwj8Dlh0@SL2iE;i8d491w1i8C49aw<18yUgAE;4i8r2hMhgDTj8JQ97x8yogAO;4ybx2io;i8C49b;18wQgAm058yQMAm4y3x2i]kibrxx8yXMAy;4Obn2gwiER47Mp8QuZ8Qux5xuR83Qj7i8C498w<20L2jj:7l3iEQ4Dg;2W1;4ibB2ik;i3Dgi0Z2MAm5Qw@5GMg0,wVMrw:i0Z2Mky9h2ho3Vf03Xr0yogAB;4ybt2h0LMo<3E3Kf/Xw3;NebXZVgA6,0,yUP_tjUWmrN218Z@98qoMA4,0,123M18MuE4i8Q44ky9h2hUj2DMi3S84M?3Usq0w?i8JY9218erMAw:@3>80,O9t2hUhoj_3Ukt@L/ioDLi8IJnXA0,y9W81Y96w03Uld1g?hj7Sj8D_joDQijDvswPH9F18znw1i3DvsNB8ytG@2w<4C3N058avHEs@f/Qy5M7nujoDCi8IZ3bA0,y9@kwVXM@2c0E?8K49dg<25M0@9cx<4Obr2hwi8AdXrw0,MHr2g8j3JI92wfw@8h?1c0SMAe4ybh2gMLM4<18xs1Qaky3@fRT8Qy3M08NQHY_;YQwfLt2Ugg<2Dgi9zPi0@ZM2D7i6f_i8I5Erw0,y9i31dxvofxdYh?18yQgAc37ii8BY95x5cuh8ySMAe4ybt2hwjoDTifvTi8B496wf7Ug]4ybj2gMj8D_ct9caut8ysx83W_7ivvTi3Jc95wfwNUe?18xs2W.<4wfht18ylgA44y9v2hghj7Si8BQ94zHdmof7Qg0,y9SAMFWHUa;j8DLW5ny/Z8xs0fxbMb?19wYo1j8RE0kMXt2gg3Uc93<iUQc9AMV@g@3f0M0,AVTna_joDGyXMAA;37ii8Bc91x9auFc0RgA24O9RAO9l2gwWb7z/Z8yRgAa8KY99;18yuXE_u7/Qybj2goi8n03UXL2M?j8Jk9218ys98zlM5,C9XkO9l2g8Wmf/_Yf7Qg0,ybdn6T?18yQogi8JY9218yogAC;4yb1kCT?18yogAE;4wXL2j:3Ufr;wbMAUw:fxcQ<18yNq0L2jx]@4Fg<4yb1hmT?18at18essfwYU<2V.<4m5Xg@5M;4w1j2gwi8KQ9c;18yTMA84y9Y4wHx2iE;i3D@i0Z2_AwfgIx8ynMA84y5OnhFwbMAV:1QnQybv2h0i8QlxEc?bV:cs3Et@3/Qybt2h0yXMAR;4xzQezzT/_i8fU_M@4zx80,yb1oGS?18yTMA84y9u0zH94ybx2io;i2K49b:fxtg8?2gi8K49aw<18ykgA88eY99g;2tgW0L2jz]@5Sws0,z7x2i+eCU_f/pyUf7Ug]4ybz2iE;j05Q91xcyuR8yXgAI;4M1YkwVS44fAIl5cujFJLz/Sof7Qg0,ybh2hgi8n03Ukv.?icv6//_Qm4V0@53xg?8J49114y6MAs8D2w@01w@81i8fO0kC9RQwVTg@3FM<8j03UixZ/_WpE;f7Q?i8Je28J@68n_3Uin0w?i8I5yHk0,y9xw01?18yMlYJg?i8A5rrk0,yb1nqR?2bg1y5M0@560w0,ybdmiR?3FDvH/MYvw:23L2ik:g@4TgQ?cu499g;2;WlnX/ZCA4ybz2iE;i8KQ9b;1cyuS3v2gg.@46wM0,M1t2goj07Ni3Dtgg@iNkkNVeCXZ/_3NY0K,<33pF36x2iE:4C9SKCC@f/jon_3Vj0hojAtgy4M0@5@_X/Qi8r2hMWgD/_Z8zn3_i8J49515cvZ8aQgA6eCIZ/_yMlfH<hj7icta@0w<46X.<46Z.<4ydL2g0.?icu490o1[yogA0,?8I55aM?6p4ypgA3w4?6p4ypMA1,?8C490w1?1Ch8CI90M1?3EGt/_Un0vwXSx2ge.<g@5Sws0,yb1jyQ<fJE0o.?xc0fx8Ub?37h2gg.<4O9YkkNXuDmZf/i8I51Xg0,C9XQy9NAyb3gaQ?1cyvF8aRgAe87C/Yf,w3l2g8i876?84,y3M0583XHGfQy91t2P?18yhjNi8C10,0,yb1sqP?36g2A1i8I5KXc?8J068n03UkA2w?yUgAR;8n03UDg0M?i8JQ942bfjGH?2W2;4z7x2gg.?fQ8f0ez8Tf/i8fU_M@4DgA0,ybv2gUW1js/Z8wsho.?cs1rnk5sglR1nA5vMQybdl6P?2bvxx8eQMAc0@jMwDgh0zw3Um53w?xvZQ94ObL2jo;jon_3UhM3w?vx5cyXgAK;4S5Zw@5@MQ0,m4Xg@4hLr/QkNVeBaZf/i8n9LM4<19ys183QnVi8Iej8QcLg;19asx9zgMVi079ijD83UdA1<i8QcfQMVMncwi8D1it7Ei2Dhj3D1igZ7O4C9@4AFO4A>4wVPQAfgI18es8fw@7T/Z8yoo0.?i8A5xr80,yb1oWO?2bg1y5M0@46fT/Qybt2h0yPQwGw?Kww<1cylgAs4z7x2gg.<g<eyBS/_j8Jk9718w_z_3Unz_f/yMlgIw?xs0fxdnY/_EYZH/UIUW5Pu/ZczgkEvM?Km82?19ys58yMmmFM?i8IUi8Ql07Y0,yddkS4<NMeyuTf/j8Jk973FAvP/Qy9TkkNXkkNV4ybduON?15yu@bhxx8yQgA8ct49101;i8JY961cyTgAu4y9x2iE;i8K49a;18yogAO;4ybx2io;i8C49b;18yux8aQgAe4w3h2g8ioDdi8B49618ynMAueI@3NY0i8JS84yb1nmN?18yNlCIg?i8D1i2DNi87V/Yf?@6SM<4wVMD8CLSg<3EPdT/QybdkSN<fJAoExc1RLkybdKKY3N@4]18yMkNIg?i8Jg24yb5hWN?18yp<g?i8I54b40,y91g6N?18yMkaIg?yQ0oxs1QFkybt2h0yPSwG<Kww<18NUgA4,<4<3EaJH/Qy3@fYfxnH/_@b1tGM?25M0@4rf/_@xZSv/yPzEVJP/QOd1r9Z?2VjM80,yd5ptZ?19ys58yMkpFw?i8QRSE80,ybe370W2zr/_Fbv/_MYv,ybv2hUioD0icu49bw=i8D@i0@WXzZceSMAc4wfhvV8yPlsI<go7w/Yf,y3M058ys58ygk_I<iECYNw.8018yTMAo87x/Yf06p6yqN601<4y9LcU,2?i3D23UeFZv/i8Je28J@68n_3UgL2w?i8I5_aY0,y9xw01?18yMnKHM?i8A5TWY0,yb1uyL?2bg1y5M0@5BMQ0,ybdtqL?3Fofn/XE2;i8QRRDM?8D7W0rp/Z8w_z_3Ukj_f/yMSSHM?xsAfx0nY/_Emtz/UIUWcbr/ZczgmDv<KiI4?18zhlPv<ioD1i8I5Zqg0,yddrq1?18yPwNMew4SL/WsrX/Z8zhkHv<LA;1cyvYNMewpSv/i8JQ942bL2jk;i6fgW8no/Z8w_z_3UkLX/_h8IRdaY0,m5Zw@47@/_@zmR/_yPzEfZL/QOd1u1X?2VJg80,yd5v1X?19ys58yMlOF<i8QRcU40,ybe370W87p/_FUeX/MYvg018yPnpHw?i8DUj8DO{]19ys18wY01go7w/Yf,ofJUh601<4M>AwVW7nxh8K49dg<19ytp5xs0fysQ5?18KL////Z_i8D89v/3M188Vj6010w,y9l2hwWn3R/ZcaszFLvL/QybdmaK?2W.<4yb3Ayb1keK?18asxU9j7ii8KY9ew<18ZTgA84wV@4wfhYt8ys98xs2U.<4wfhd18elgAc0@2W0E0,wXl2gM3Ufv2<i8K49aw<18NUgAw=37x2ik:w<4y3M0d8eogAy:@2qfj/Qybh2gMi8QY4bw1;id7Li0Z4@4y9v2gMi8DWifvqi8I5IWQ0,y9xx01?18yMmJHg?i8Cg2,0,z7x2i8=eArZf/i8KQ9a;18aXgAO;4wV@78jct98Z_sNQAy9Mky9Y4zTYky9NAybh2gwi3DM3UfTZL/i8R80kzhWuBgZL/i8JQ942bfv2A?2W2;4O9l2hMicu49101<1;W7nm/ZcyRgAs4y3@fYfxrfT/@b1i2J?25M0@4Fvv/@z3Rv/yPzEbdD/QOd1vxV?2VjM80,C9Mkyb1mqy?18yPzFO_H/Qybt2h0LMo<18ykMAsewaRL/K0c<18yQMAscjy@_uk91w1?18Kc_Tk@eBCYgwi6CQ9101?1.wY0ifvyic7G14w1RAwHJ2iU;i3KQ9dw;fwJ3J/_6x2iE:4ybdnCI?19ytF8NUgAK=3F8_3/Qyb1lWI?36w1w1<1WhfU/ZCbwYvx}i8J490xdyuybL2ig;ct99auxdziM0j8DKW23o/Z8yRgAa8KY99;18yuXErdr/Qy5M0@e>80,O9r2g8i8Rs1g19yuRceTgA40@20Lj/SpCbwYvx}j8DGi8JQ94x8auF80RgA24S5ZDlli8I5NaI0,yb3smH?18ysq1VL/3M18wso?wg0WszT/Yf7Ug]4O9WAybt2h8i2DGi0dk90xceTgA47cej3DVsMB9etQfwVQ1?1dxvpQGQQ1Z4yU=81cymMA44C9Rkw9Y4MXt2gMi8Bs91x83QnMi8DPWPAf7M18yT0wi8I5fqI0,yb3jWH?18ys98av98wvH/MY03Uqz;yQ4oxs1R9bZA;W9bn/Z8yMkjGM?3Xpga8jitrJ8yP3HKCof7Qg0,ybt2h0yPStEw?Kww<18NUgA4,<4<3E9Zj/Qy3@fZRJoIZSWE?8n_taLEwJf/UIUWeLm/ZczgmTtM?Khw4?18zhmstM?ioD1i8I57G<4yddtZY?18yPwNMewJRv/WmP/_Yf7Ug]4y9NQy9TAy3M05cyuG1V/_3M18yRMA64Obr2ggi8A5naE0,y9JfA,2?i8D6pAi9J7A,<wur/MY0i876?84,y95f5devMfwQXS/Z8ytrFNL7/Sof7Qg0,ybj2hEi0D13UhB0M?i8Jc96x8esx83Qb1i8B4913FP_7/Qy9SAybt2h8ioDti2DGi0dk90xceTgA40@3o_X/QObt2hgjoDYWlX@/@b5tKF?25Qw@4lvr/@x@QL/yPzEVZn/QOd1upS?2Vb.0,yd5pxS?19ys58yMkqDM?i8QRSTI0,ybe370W2Dk/_F5Lr/Qybt2h0yPQFEg?Kww<18NUgA4,<4<3EIZb/Qy3@fYfxr7R/@bdmeF?25Zw@4E_n/@w6QL/yPzErZn/QOd1jJS?2Vawg0,yd5i1S?19ys58yMmyDw?i8QRoTI0,ybe370Wb7j/_Fpfn/Qybv2gEW2bk/Z8ykgAeeB3Wf/i8J491xazkMN0kGdh301i8B491x8esofwTo2?18xsAfxtXS/Z9ysV9yt_F4uP/QybdsyE?18yQo8i3K49c:fwIc5?18yuF8yvB8et4fwWrL/Z8yPmwG<WgrW/Z8yMmkG<yTwoi8IlwGw0,wV5neE?29v2hM3U8B0w?yQ0oxs0fxrU4?18wXMAS]fy6Q2?2bv2hMxvYfx642?18wXMAK]fxfk3?18yTgAgbY6;W6Th/ZcyUMAS;4ybB2go.?cvpdxsBQmQyVP_tjUWmrN218MuE3i6CY9101?1.wY0i8Dgifvxic7G14w1@AybL2iU;i8Dgi2DUj3D8sO59at6@p;4Cd13B8foua.1T3kz1W0d8Z@58MuE4ytq9YAydL2g0.?Lw8<3E1Zf/Un03UUy.?ZEgA1w4<4fxi83?3Sx2ge.<g@41w40,yb1oiD?1cyv76w1w1<1NQgA4,<3Fj_f/QwVh2ho3U9ZXv/i8K49ew<18QmgAc4ybv2gMi3D7i0Z3@bw2;3Qa499g<18ynMAc4zTTUC499g<18yMkuFM?i8C64,0,yb1hyD?18yrw8.?ict495w:WhXJ/ZcyTMAo8KY99:NQAO9_KzBQL/j8JI93x8yRgAa8KY99;1cyuXEbd7/P7ij8BY90x8yMSSFw?i8n0i0Z8MACdn0k0WtnJ/Z8yMmCFw?j8DGi8IdFao0,wHl2gUi0dk90x8ysq1VL/3M18wso?wg0WpTO/@3v2gg0w@5K0c?ct49102;WsDD/Z8ytR5cuR5cujFvuD/QgfJCMAseDsWv/i8JM28n_3Umm0M?yQwoxsAfxoI3?18xvqV.<4ybe4Ob1hKC?183QjNi8Dhi2DVj8QcJg;19zjMNi07_i3DV3Ubb1<j2DaijDg3U9g1g?yQ0oxs0fxk82?18NUgAK=2@p;eAp_L/i8n9LM4<1cyMp83Qjfi8D7j2D7j8Qczg;1dzgg9jg70j3D73U8T0M?j2D8icu49bw=i3D23UcCW/_i8C60,0,y91nCB?18yMm2Fg?yQ0oxs0fx9HR/Z8yTgAg8IZ59Q?bE8;icu49101<1;W9Xe/Z8w_z_3Ujm1<icu49bw=i8IReqk?eD3WL/icu498+NUgAB:8<3FDKL/Qybt2h0LMo<18yoMAG;ewVPL/K0c<34ULLTB2go.?ibzfZRfzFpL484zTUAybz2iE;i6CQ9101?1.wY0ic7G14yd11p8yPn2F<j2DMj3DU3UazYv/i8J49218yTMAo4m9XQObt2hUi8C49aw<18yUgAE;4y9x2j8;i8K499w<18yogAI;eDgYL/i8JQ942bfgOs?2W2;eyWPL/ZEgA3w4<4fxdHZ/_FNfP/Qybt2h0LMo<3EucT/Xw3;NebXZVgA6,0,yUP_tjUWmrN218Z@98qoMA4,0,123M18MuE4i8Q44ky9x2iU;Wr_X/Z4yMQ4F<hon93UhyXv/Warc/@beewfQf/j8Q5I7<bCq0M?i8QlM7<4C9Mkyb1kap?18zjk3tw?i8IUcs3EksX/@AzXv/3NZ0,ybt2h0yPRdCM?Kww<18NUgA4,<4<3ERYP/Qy3@fYfxhvX/Z4yMm6EM?hon03Ug7@/_W2zc/@beeyhP/_j8Q5nn<bDF0w?i8QlgD<4C9Mkyb1sio?18zjm5tg?i8IUcs3EQYT/@D8@L/i8Dhifvpi8I58qc0,y9xx01?18yMkrEM?i8C82,0,y9l2gMicu498+NUgAB:8<3FuuD/QybdAy9WAwVXDcui8DFi2DNi8KQ9c;18ev583Qvei3D83Ua@.?i8DVWhbW/_7h2gg:4O9YuCkXL/i8IlEW80,y9A?1?18yMmlEw?i8A5xG80,yb1o@y?2bg1y5M0@5P;4yb1nSy?3F/D/QOd10B9evwfwX_Y/Z9ys18QuZ9at19evxc3Qv7i8Dfj2D7i077j3D1i0Z2N@Cq_f/i8JQ942bfuep?2W2;4z7x2gg.<g<exJO/_i8fU_M@5P_P/QibbhOy?15xuQfxb_Y/_ELIH/UIUW2ve/ZczgnPrw?KkY2?18zhnorw?ioD1i8I5mFs0,yddhJQ?18yPwNMexFPf/Wo3Y/Z8etR4y6MAs44fAIl5cujFRKj/Qybt2h0yPRlCg?Kww<18NUgA4,<4<3ETYH/Qy3@fYfxgD/_Z4yMSeEg?hon93UjV_L/W33a/@beeypPv/j8Q5pmU?bBf0w?i8QliCU0,C9Mkyb1sOm?18zjmdsM?i8IUcs3ESYL/@CW_L/i8QYdAwVPM@3a_L/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWgrX/Z8yTMAg4wFMrV:cs18zhn1rg?i8DdWbra/Z8yTgAg8KY9dg<18oZ3E8IH/Qy3@fYfxaA<18yMn9E<i0dI9218ymw8i8IlIq<4yb3qaw?3F_vv/Qy9A?1?18yhmfE<i8I5Ca<8J068n03UmO;i8I5xG<eC4@L/hj7Jhj7AWpjz/Z4yNRTE<honr3Ugq@/_W1D9/@beey2Pf/j8Q5jCQ?bBy0w?i8QlcSQ0,C9Mkyb1rml?18zjlSsw?i8IUcs3ENcH/@Dr@L/wPQEE:@4iL/_@zdOf/yPzEdIP/QOd1ttI?2VQ0c0,yd5utI?19ys58yMlFBg?i8QRaD80,ybe370W7za/_F2//Qybt2h0yPRUBM?Kww<18NUgA4,<4<3E0ID/Qy9MAyb1r2v?18w_H_3UmF@v/wPSDDM;@4DfD/@xcOf/yPzEJsL/QOd1o5I?2Vow80,yd5mpI?19ys58yMnEB<i8QRGn40,ybe370Wfv9/_FPvX/Sqgglt1lAC9RA5lglhlkQy3X1y9v2g4LM<g18yngA2excOv/ioD7jonSt7V5cujH5wYvw:3EQYv/UcU17lEjjDQsSd8yQgA24O9YEJY90hcyvVcau9azgMwK;g18es983QvgW8ba/Z9ysl8xs1UMDgOi8D3j8DZpF18ytF8yuW_.<ewgOf/i8n0u0J8asdQ9Aw1NuLxAexHN/_wPw4tdp8wYgoj8D_mRR1n45tglV1n@B0N/_jg7IWnH/_Yf7Ug]8f_0DYbK,<333NZ4?11lXEa;hj7_glp1lk5kloDZkQy9YQy1X2w4?18yTU8cvrEhYD/QybuN2W2w<37SykgA24C9NewMOv/ykgA38fZ0Tgpi8JX64yddmZH?15cv_EFcz/Un.g@kNQyb1g@u?18xs1Q1cp0a06U.<4i9p2goctJ5cuh8NQgA4:18zmMA66q9h2gsKL//@@.<4y9X@wGOv/xs1UpLp491UptedczngA88JY90yW0.0,O9ZKw9Of/i8n0t2BVkKxtNL/yM23@0JQKEfU17kmWXcf7U]j8DDjoJA913EaYr/QS5V7nKi874a.?370mRR1n45tglV1nYdCAewrNL/wPw4ttLFtv/_V18Muw4xs0fzCz/_@3W058Mu,i8R41318yggAWNBCA4wVMM@2FM<4C3Nx1cePgA3UgZ//ioI6i3Dotu590RU8jonAtivHaSof7Qg0,Sbr2ggj8DDioJs90xcymMA4eypNv/jonJt0BdyuN9ehMAtdJ8yMnsD<i8n0t0h8ylwwhon_3Umu;i8Dqi8I5M9M0,yV0f3///T@1UL/3M188UPg010w07hWyTMA337iLwc<3E7Ir/QObp2ggWlT/_Yf7Q?LNw<3EBIr/Qy9MkCb1Ay90kCblwx80s98yl48i8Rk911dxuhR9@IH{]1CpyUf7Ug]4Cdl2ggjoJA911dxuhQ1AAV12hOWQO9oh18ygFcySgA4eDP_L/pyUf7Ug]8f_0DYbK,<333NZ4?11lXEa;glp5cvp1lk5klld8yvd8wuME1<i8J@237Si8RI921czmMAcezfNL/i8JX4bEa;cvq9h2g8WbL6/Z8NQgA6:29h2gc3NY0{]2bv2g8Kw,?18yuXEXYn/Qy5M0@eVw<4z1W0i5M7Xuzlz_ioDIic7z14M1W@Il3N@]4AVND9ziof444AVT7iWioI494MVY7nFi8JY91xd0TgA24y5_TksWNZcyTYgj8JT24O9v2goWdX3/ZdxvZQ24O9_QMVdTjxj8DNi87x0f3/TWOyTMA337iLwc<3EBsj/@Kw3NY0LNw<3E5In/QCb52h8zkMA64y9NAy944Cbh2g8i07gi8B624ybh2goi8n0thXH8gYvg01CpyUf7Ug]4ydi118yQ.i8n0t0l8eh1OXAy9hx18yj7Ff//Sqgi874a.?370mRR1n45tglV1nYeg{]23_M9_2Xw1;MMYvh<lrEa;i8DBglt1lAkNZA5lglhji8DPi87Iu880,ybvwwNZKx6Nv/j8Jz44yddm9G?29h2gsioD7j8DDWbP4/Z8zngAkbY1;ysfEaYr/Un0thabh2hE9g3M<Z08<44fBcq5SM@4Zg80,ydh2h0hj70ict493]i8B49118zogAU;4y9h2gwpyUf7Ug]4ybt2ggyTMA7bEg;j8B492zE6cj/QObh2gEi8fU40@5yw80,Obr2gMj3B4941QnrYo;j8B492zEHIf/QObh2gEi8D1i8J49418yg58yRgAi4w>AS5Xky9kgx8zlgAc7klWNBC3NZ4?19zlkgjoJJ44S5Xng6ijB507bJj8BF44y92KBN//A4O9UrU0.?cs1cykgAa4ydD2hM.?i8Qlumo0,y9T@zGML/cvoNM4y9T@yeNf/j8J492y5M0@9og40,M3h2h8jonJtjbF8L/_SqgjoJ524Sbvh1cyuZcykgAa4O9v2gMW8r1/ZdxvZcyQgAa0@4@fX/QS9_kQVhg0fxuL@/Zcyu58zhk8pw?i8Dvcs2@0,?exOML/cvp8ytYNMewmNf/goD6xs1UDQz7h2gU:4ybt2gwysvEyIj/Un0tgR8yUMA4,0,y5OnYph8DTW972/Z8yt_Eas7/@BA//3NZ0,ybh2gUi3D1vJR8as58zlgAe4i9ZHY1;W273/Z8xs1U74ybz2gg.?i8J493x8es5_ReKL3N@4]3EOY3/UI0w_w4tdydkeG3UKZQ48fUm0@kMEfU2g@kM0z2t8d8yTgAe37ih8DTWdT3/_H60Yv,y9MAydJ2hM0w?LM4<3E4Y7/XE0w<i8SQ9702?14yvvE3Ib/Qy5M7_hWjL/_Yf7Q?i8JQ9229NQO9h2g8ict493w:ykgAaeyiM/_h8Jk92xcyQgA28n0th58yUMA4,0,y5Og@fUM<4i9RQO9h2gEW8r1/Z8yt_E7I3/QObh2gEWkf@/Yf7Q?WfK/_@3e0hQkAS5XngiA4O9XQSbrizEVc3/QS5XnnLi874u88?370mQ5sglR1nA5vnscf7M2U.<4i9L2hM.?hj7Jhj7Aict494]pEC497g1?2W//_XU1;i8SY9701?3Ebsb/Un0u8DSx2hS.?6njrj8SY9702?2bv2gsKw0a?1cyvXE1I7/Qy5M0@4p//M@9cM4?exiL/_yM23@0JQFUfU10@5jf/_@Ksi8J493x8es4fzw//Z8as54ytp8zlgAebY1;j8B490x4ylgAaex3Mv/h8Jk92xcyQgA24y5M7wsi8Kc9101?18yQgAe4wVMn_0WsH@/Yf7Qg0,i9l2g8j8B492zESrX/QObh2gEh8Jk90yb08fU17j4zl3Gw@bLt1i3@0AfBca3@5wfBc08Mw@4yvX/Qybt2gUh8Dnct9cykgA24i9l2gEWdf1/Z4yRgAa4Obh2g8WP0f7U]i8D2LM4<14ylgA24ydJ2hM0w?j8B492zEYrX/Qibl2g8j8J492x4ytuW08<4O9h2g8i8SQ9702?14ylgAaezoL/_h8Jk92xcyQgA24y5M7@FWg7@/Z8KITcPcPcPcPcifvyic7G1oni3UVD_L/zkb_i8Q4w4ydxcio0w?i8B4911deisfxgQ1<f7M1CpyUf7Ug]4CbtNx9yRswgoJ_44y9J2jw;hojS3Uhl.?i8S49e;18yt69_HY1;i8D2i8B4923ERb/_QCbhNx1yTYgLwc<18ys990Qswi87y0f3/QwFQ4y9MuxeLL/jgdD24S5XnlSWTEf7M19yQkoi8Jk922_.<4y9x2jw;ioJd846bth3Evr/_QCbjhx1yTQgLwc<18ysF90QQwi87y0f3/QwFQuzWLv/ioJ5a4O9XQQ3pgx8ykgAa4y9h2h0W12@/Z8yQgAa4y5M0@4g,0,C9NkQVpg1QykC3NOxceTMA40@4hLT/QQV9M@40v/_XYM;W3u@/_4MnVL1Qy9Msn@vM19yQswi8B184S5Xg@40,0,Cb5Qydh2h0WNQf7Qg?6pCbwYvx}ioR5a4SbrixdxuRQ1AAVlg1OXkO9qix8ygxcySMAgcnUtQC3NOxceTMA47m9WsHY/_Emvj/QCbhNx1yTYgLwc<18ys990Qswi87y0f3/QwFQ4y9MuwjLv/jgdD24S5XnlJWjP/_Yf7Qg0,Cbthx8yrgAU;4Cbli11yTQgW0vQ/Z9yQQogoJZ4bU3;i8Daigdd84y1Uw3M/Z8at7ENbP/QCbhixcyuZd0Sk8i8B492x8ykgAgezqLf/i8J492x8xs1Q3AC9NkQVpg1QB@D9_L/hj7JWs7@/Z8zkgAgeAz//w_Y13UXn0w0.luW2w<45mgll5cuR1l5l8yvljyvJ8wuOE.?i8J@237SWbWZ/Z1ysi3@Mcfx8E2?3Ejsb/Qydfghw?18Muw3i8So/Yv0bw;2i87z?3w_QwVMQwfhZyU<w,wVMQwfgJzEFXT/Qy5M7gnKwE;NZAy9N@xzLv/i8D5i8n0vMmZw;4ydv2gMW1O@/Z8NQgA4:y5M7kSNvBL3otC<NQInVrEgAC;cjyuj_1NvB@M4wfHQgAk4zTZrE;8i3Dgi0Z3Q4y9l2ggi8SQ9101?14yu_E2rX/Un0thubx2gE.?9g3M<Z08;@4Tw40,6V1g<4C9S379h8Dycvp4yu_ERHH/QC9NQy5M0@8Ow<bQ:grU;1tj5CA6pCbwYvx}grA5;ioDocsB4yu8NZAi9X@yoKL/ioD7i8n03UWt;yPQuyg?xvYfysU<1c0vR9euVPNAydL2iw;W2CZ/@9Mon0tlf5@mYdCSk0,ybt2ggNvBKx2g8.?Ne9VfY75@nX0i0@Lx2j8;i3DMsOp8yMkDAg?i8n0t1EfJA0Exc0fxjI7<f7M1CpyUf7Ug]4C1Nw;7Flf/_MYvg03EGXD/QC9NEcU5w@410o?8IZvow?8n_uhkNM4y1Naw1?1rnk5sglR1nA5vMV18zrgAE;bE8;icu49a:1;WfaV/_HOQydJ2iw;Kww<18NUgAE:4<3EQHD/Qy3@fYfxgH/_@b5oag?25Qw@4_fX/@wBKv/yPzEzHP/QOd1sty?2V8wo0,yd5jZt?19ys58yMn1xg?i8QRwC80,ybe370Wd2W/_FLvX/MYv,ybvh2W2w<37SW1yX/Z1ysnFnLT/Xw1;MSoK3N@4]18yVgAg,0,ydt2gEhj7_cs18NQgA8:18NQgA2:58yjgAi8ni3UXM_L/3NZ?6pCbwYvx}i8Dhi8Dti8B492x8as58etB83QrFi8nJ3UhW.?hj7SioDEi8IQ94kNOj79jiDMh8Dyh8DLW9mV/Z8xs0fy0M1<fx381?190sp9euVOPQybh2gwpwYvx}jg7TyPT_xw?j07Mi8B49225_M@9dM40,ybB2h0.?i3D23UVn_L/j3BY90wfwSL/_Z8zqMAE;4y9X@zHKL/ysa5M7l5NvBL3lRz?18yUgAO;cnVrEgA2,?cjyuj_1Nc5VvIp93W_6i3J4911P5Qyb1uye?18xs1Q2M@Sg2y4M7kH3NY0i85490w;1i8J49218yVgAg,?eDR_L/3NZ4?21@x0D?1QSbZA;ylgA6ewqK/_i8DLW6aW/@bl2goi8K49cw<23Mw593W_6i3J4911OOeKCpwYvh<W2KT/@b08fU10@4XvX/UfUnM@kMEfU9w@kMgzatgO3UfK3@18fxqE<18yQgA84S5Zw@5RLX/QybB2h0.?i8Dhi2D1i8n93U@f;hj7SWrH@/Yf7U]i8SQ9a;2W2;4z7x2iw:g<ex2J/_i8fU_Tgci8J4923FC_X/SqgyPTGzg?xvZQWKyhJL/yPzE@HD/QOd1jdw?2VVgk0,yd5qJq?19ys58yMkJwM?i8QRXBY0,ybe370W3OU/_HHHw1;WrTY/Z8es8fzGzY/Z8zkgA84Obt2g8i8A494QV_w@2q,0,yb52h8ytB4yuV4yuvEjHz/Qy9Nky5M7wKt3qbfvq4?25_M@9Zw40,A1XQybh2gwi3C49401?1_K@Bg_f/3N@]ezzJv/wPw4tdJ8yUgAg,0,ybl2gwj8BQ90x8es8fzijY/Z8znMAaewVJ/_xs0fxhbY/@bv2gIKw0,02@>g?exKKf/i8S49a;18ykgA64ybx2h0.?i3B4920fzpI<18ySMA24y9n2g83NZ0,MV_g@29Mg0,Obh2g8yRgAb379h8DLi8IQ946V1g<eyqJv/i8D3i8n0vBZ5cvof7Q?{]19ytybv2gEcsANZAQFY46V1g<4i9UKxAJv/i8n0vwx90sp9etVORUIZWoc?8n_3UB70M?i8J4921d0vt8eogAg,<@fs//UJY92zEiHr/UJY92PEgrr/@AJ@/_3NZ0,ydH2iw;i8DLWcyT/@9MEn03Ume;NvBL3jpw?18yUgAO;cnVrEgA2,?cjyuj_1NvB@MkwfHY58eQgA47dxi8I5MEI0,y5M7hl3Xp0a8j0t4TH287W42s?7h3LSg<29l2goi8Bc90zE4bz/Qy9X@xoJ/_yRgA64ybj2g8i8K49cw<23Mw583W_1i3J4911OLCof7Ug]4C1Nw;7FVfT/MYvg018zrgAE;bE8;icu49a:1;W8aQ/Z8w_z_3Uny_v/yPkOyM?xvofxdjZ/_ERrf/UIUW3WT/ZczglTng?KvE5?18zhnLlM?ioD1i8I5so<4yddj9t?18yPwNMey0Jv/WpnZ/Z8znMAaewhJv/xs0fy2_Z/@bv2gIKw0,02@>g?370cuTEgHr/Qydx2iw;ics49:58ykgA26qg{]2bl2gIgrA5;ioDocsANZAi9X@y7I/_ioD7i8n03UV8_L/yTMAa379cvp1Kgk<19ys14yubEoHf/Qy5M0@e9LX/UIZWU4?8n_3UDr;j07Zi3AI97eyi8JY90zE@bn/Un0tkj5@mYdr5U?cnVrEgA2,?cjyuj_1NvB@MkwfHUMAO;4wXj2ggsNF8yMTXyg?i8n9t0UfJAAExcAfxvo1?1CA4y112g;1Wkf/_Z4yiMAioDRj8BQ90z4MnB@NAy9n2goysLH4mof7Ug]87X42s?7gHLSg<23MM7E6Xr/QydL2iw;W5WR/Z8yUgAO;4AfHYpceuxOPkibb2hcyTgA24ybn2goWmHU/ZCbwYvx}i8JQ90yW2;4z7x2iw:g<eylIL/i8fU_M@50f/_UI5hoA?8n03UjO_L/goI@W5mR/ZczgmemM?KjQ6?18zhk6lw?ioD1i8I5y7U0,yddkBr?18yPwNMeynI/_Wrv@/Z8yTgA6bE8;icu49a:1;W2uO/Z8w_z_3Umk_f/yMTny<xsAfx8rY/_EuH7/UIUWeeQ/ZczgksmM?Khw6?18zhmklg?ioD1i8I55DU0,yddttq?18yPwNMewBI/_WkvY/Z8yTMA6ex6Jf/goD6xs1RgsnVrMSTn<i8K49cw<35@mW490w1?34UDA_MsnVvId83W_3i3J4911P54yb1ke8?18xs1Q20@Sg2y4M7kli875:uBX@/_go7@42s?7jHLSg<11wYo1W8KQ/Z8yTMA6ezhI/_i8K49cw<183W_3i3J4911OPeK@i8Bs91z4MnB@NUD3WMy1@N0D?1QaHZA;wYc1W4CQ/Z8yTMA2eyfI/_i8K49cw<193W_7i3J4911OPAybn2goWsbZ/ZCA8f_0TYbK,<333NZ4?11lXEa;glp1lk5klld8yvd8wuPo0,0i8J@237Sj8SI9d;3Epbb/QybuN0NZHEa;goD6W56O/Z8yTIocvqW2w<8B491zEfrb/Qy9NoB491PEQrr/UBI92x8Muw3NQgAb,<18zpz/NY0K:98wuc?e3_i3D3i0Z7Sbw?2?i3D3i0Z2S4ydh2h0hj7Ai8B491180tJ8yTgA44i9Z@zKIL/xs0fy0o1?1cyTMAs4Cdb1N9euYfwHY<18zkgAc4y9h2g8i8Sd?3/XE<40j8DKh8DTW4eO/Z8xs1@pAy9MHUa;j8DLW3WO/Z8xs1QkkMFW4ybt2g8yTMA6bEg;i8SI1g40/ZcymgAc4y9W4MFU4y9h2gUWaKL/Z8w_wgt42U.<4y1Ndw0.1rnk5sglR1nA5vMSof7Qg0,ybt2g8yTMA6bEg;j8BA9318ylMAeexHH/_i8fU47n0ioDIi8QIaQAVXM@3i//Qydv2gEKCg<2@.<exhIv/xs0fzLX@/@bv2gsKww<18zngAcewSIf/Wur@/@gcs3Fuv/_Sof7Ug]5eX.<4y3X218zngA7ewsIv/i8D2i8cU07goyTMA74y9NAy9h2g8W6aT/Z8yRgA28D3i8DnW4eL/Z8wYgwytxrMSpCbwYvx}kXI1;i8fI84ydt2gsWcOM/Z8ys98wPw0t1ybv2gsi8D6i8B490zEgIf/Qybl2g8ysd8ytvEYWX/Qy3N229S5L3{]1jKM4<18w@Mgi8RQ90PEvb3/Qy3e01Q5kyb5gu5?18xt9Q1Yq26,<4NSQy9N@yFHL/i8f448DomYegkXI1;i8fI84ydt2gsW3OM/Z8ys98wPw0t1ybv2gsi8D6i8B490zEcKr/Qybl2g8ysd8ytvEoWX/Qy3N229S5L3{]11lQ5mglhlLg4<1ji87IM;4ydt2gsWeaL/Z8ysd8wPw03Ui7.?ySMA78fZ.@eO,0,ybu0yW2w<37SgrP//_W4aL/Z9ysu3_g8fxro1?18zjSxkg?W5GL/Z8zjSAkg?i8D5W4KL/Z8xuQfx381?18xs0fx2A1?2W2w<37Si8DLi8B490zERqT/Qybv2g8KwE;NZAy9h2gwWb@J/Z8ykgAa4m5_M@fsg40,m5V0@eW;4ydflBU?3EfaX/Qy9NkgXE]fxrM1?23K1:13Unx.?i8QZaB4?ez3HL/i8n03UiG;KwE;NZAy9N@xXHL/Kw4;NZAi9VQC9N@xFH/_i8D5i8fU_M@4C;4ydfuRT?3EQaT/Qy9WAydt2gMh8D_NvBLh2gwh8BA9437h2h4:cnVvQgAc4ybw0w<18asb4UvBKOcjzYib20rEE;NvF_h2h8W5uI/Z8w_z_3UiV.?i8QZzDs?exNHv/i8CE2;6oK3N@4}NXky9T@ymHf/i874M;8DEmRR1n45ugl_3yMTeww?xsBQaKxRG/_yPzETGX/Qyb5itU?18zjlolg?i8IWi8D2cs3EcWT/MYv0bQ1;WWJC3N@4]18yTIgKwE;NZKxMHv/goD4Wjb@/Yf7Ug]4ydt2gwKx;14yv_EDGL/Qy3@fYfxnf@/@bdkW2?25Zw@4pvX/@zNGL/yPzEmGX/QOd1rdk?2VWgg0,yd5gJf?19ys58yMmdtM?i8QRjBg0,ybe370W9OI/_F9LX/MYvw:14yut8zngAc4i9E:3EXaT/Un0th2bh2h89g3M<Z08<7hRNUkg:w<4ydt2gwKx;14yuvE_aH/Qy3@fYfxsb@/@b1qO1?25M0@4JfX/@xfGL/cuSbeeySHv/j8Q5xRg?bA91g?i8QlpQU0,C9Mkyb1uBS?18zjmGkM?i8IUcs3E@aL/@BR_L/NUkg:g<eCB_v/yNlewg?xt8fx3D@/_EYqD/UIUW5GJ/Zczgkbl<Kgk5?18zhkbjw?ioD1i8I5zno0,yddkVj?18yPwNMeysG/_WvHZ/Yf7U]kXI1;i8fI84ydt2gsW4OI/Z8ys98wPw0t1ybv2gsi8D6i8B490zEgKr/Qybl2g8ysd8ytvEsWH/Qy3N229S5L3{]1jKM4<18w@Mwi8RQ91PE_aL/Qy9MAy3e01Q68JY91N8ysp8ykgA2ey2Xv/i8Jk90y9MQy9R@wzGL/i8f488DomYdCpyUf7Ug]5mZ.<5d8w@Moi8RQ90jEGWL/Qy9MQy3e01QbodY9.1vPKbfsBT?18zngA2bE8;ict490w1;W5SF/Z8w_z_t2YNXky9T@yZGv/i8f468DEmRT33NZ0,ybu0yW2w<37SWe2G/@9N@KT3NZ?8I5UDY?8n0tcvEyqz/P7JyPzEYaL/QOd1lBd?2Vn0o0,yd5q5c?19ys58yMkztg?i8QRV540,ybe370W3aG/_HyReX.<4y3X218zngA7ezIGL/i8D2i8cU07goyTMA74y9NAy9h2g8WcbT/Z8yRgA28D3i8DnW1eF/Z8wYgwytxrMSpCbwYvx}glt1lA5lglhlkXI1;i8fIm4ydt2gAW9eG/Z9yst8wPw0t0Cbr2gAw_Q5vO5cyv_EOqz/Qy3N5y9S5JtglN1nk5ugl_33N@4]18yTw8KwE;NZA6@//_@zqGv/ioJ_4bEa;cvq9h2gkWcqF/Z9yTYoKwE;NZEB4913EIGD/QCbvO2W2w<37SysfEEaD/QCbvOyW2w<37SykgA6eycGv/ykgA78fZ1w@53M8<Yvg01CpyUf7Ug]4m5ZDwri8RQ93yW.<4i9Z@yVGf/i8n03UXg.?i8RI942bv2gkKx;18yuXECGz/Qy3@10fxr01?18yQgAg37SKw8<29TQy9h2gEW1yG/ZcyQgAi8JY9129SAkNOkydj2gMi8RQ92x8ykgAcew6Gf/i8n03Uzt;yTMA64ydt2gUKww<18NQgAe,<3E8qv/Qy3@fZQqUJY91OW4;4y9XKwaF/_i8fU_M@5gf/_UI5KDQ?8n03UgO//W5SC/@beez6Gv/j8Q5LR<bAR>?i8QltQE0,C9Mkyb1vBO?18zjmWjM?i8IUcs3E2az/@DP_L/3NY0yNlGvg?xt9Qy@whFL/yPzEuGD/QOd1vpa?2Vd0s0,yd5iJa?19ys58yMmJsw?i8QRrAY0,ybe370WbOD/_Fjf/_MYvw:2_<10ewCF/_i8JQ942bv2ggct98ykgA2ezNGf/Kw8;NZEDvWeeE/Z8yRgAi4y5QDh8hj7JpwYvh<j2DGK;g18yTgA28JY9118es99ythc3Qvwj8Dyjg7BW0GD/Z8yTgA24O9UEDvWeKB/Z8yRgAi4AVRnb1i8JY90zEhWr/@Cl_L/pF0NS@BE_v/pwYvx}ioJ_cbEa;cvrEoav/Q69NKDE_v/3N@4]1jKM4<18w@Mwi8RQ91PEHav/Qy9MAy3e01Q68JY91N8ysp8ykgA2ewiUf/i8Jk90y9MQy9R@zjFv/i8f488DomYdCpyUf7Ug]45mlrQ1;kQy3X318zngA3expF/_i8D3i8cU07h5wTMA305@tAydfq99?1cyT08W5CI/@5M7x5i8RI9129MrUw;cs18yuZ8zhkoi<W7yB/Z8yuVcyvsNXuzXGf/i8DvW5eB/Z8wYgMyuxrnk5uMMYvx}W3KA/@beeyAF/_i8QZiQA0,y9Nz70W5eA/@Z.<eL1A6pCbwYvx}kQy3X218zngA7eyNFL/i8D1i8cU07hEwTMA705@okybu0yW2w<37Si8B490wNS@wqFL/KwY<2@2gg?8D7cs3EBWr/Qybj2g8w_z_t1l8ys_EJqj/Qy3N229S5L33NZ4?2b1v9W?25M7ku3NY0{]2X.<eLcpwYvx}W7Kz/@beezAFL/i8Ilbn<4yddvVd?18yPF8ys8NMewVFv/i8Jc90zHMCqgglplLg4<1ji8fIc4ydt2g4WeCB/Z8ysd8wPw03Uig;ySMA18fZ.@eL;4ydv2g8W9mA/@5M0@8zg<8JY90OW<g0bU71<cs3EOan/UJc90y3_g8fx9c<18zmMA44yd5oF6?2@8;370i8DLWe2z/Z8yTI8i8DKW6iD/@bj2gcLy:NM4y9XQyd5lF6?3EKGf/QybuN18yuXEfGv/P7Ji8DvW9iz/Z8wYgMyuxrnk5uMSof7Ug]exXEL/yPzEVan/Qydfqd7?18ysoNMeyjEL/Lg4<3HM0Yvg01cyTc8i8RI912@8;370i8QlX4k0,y9X@x9E/_csANZAy9WAO9Z@yGFf/i8n0t3mbj2gci8QlNkk0,y9XP70Ly;3E6Wf/P79i8DGLw4<1cyvvEuqj/Qy5M0@5kL/_UJY90zElWf/UJY90PEjGf/@BS//pwYvx}glt1lA5lglhlLg4<1ji8fIa4ydt2gkW6eA/Z8ysd8wPw0t114ySgA5463_0h_7XQ1;i8DvW9ay/Z8wYgEyuxrnk5sglR1nA5vMV18yTw8KwE;NZKyME/_i8JX4bEa;cvp9ysvEDqf/QybuNyW2w<37SgoD6W6Gy/Z8yTIwKwE;NZAy9h2goW5my/Z8ysl1w_M5t7N8yTIEi8QRpQo?ezIEL/Kw0,02@>g0,i9ZUn03Vj03Xr0ykgA2370WcOz/Z8xuRQc4kNV4C9W379grA5;h8DOjiDwi8RQ91x4yv_E9G7/Qy5M7xht0x90sh9euNOQUJ490y5M0@5CM<37JWhH/_Yf7Q?Kw0,02@>g0,i9ZP70W6Oz/_7h2g8:4y5XnmocuTFXLX/MYvx}W7Kw/@be8f_17iEw_Ybtaebl2g8xt9R9@ziE/_i8QZFQk?bQ1;i8D6cs3Eva3/@CJ_L/3N@]4i9ZQy9h2g8Waex/Z8yRgA28IWWYdCbwYvx}h8DTcuTExG7/@BT_L/A5mZ.<5d8w@Moi8RQ90PEGWb/Qy9MQy3e?fxaI<18yPQLtM?i8n_t1m@012w0exEEL/ics55ns}2bfrtK?25_M@9bM4?8IZFmU?8n_3UA1.?yPSjrw?xvYfytc<2bfo5K?25_M@9Fg<8IZrSU?8n_unKbfnRK?25_TBhi8QZa4c?37JW6ex/Z8zjQFgM?W5ux/Z8zjQHgM?W4Kx/Z8zjQRgM?W3@x/Z8zjQ@gM?W3ex/Z8yt_EeW3/Qy3N1y9W5JtMSqgW9Kw/@bfi5K?3EAa3/Ys53CU?f//_HAMYvg03EuW3/UIZ_mQ?cs5SSQ?f//@5_M@8sL/_@L1AexrEf/yPT5rg?NMm_rg?//_Un_3Ux8//WY6gW3Kw/@bfqBJ?371qdJ?3//_xvYfy1X//HMp3E6W3/UIZzmQ?cs5xSQ?f//@5_M@8YfX/@L1AezXD/_yPRNrg?NMlHrg?//_Un_3Uz2_L/WY6glky9Vk5nglp1lk5kkXI1;i8fAM4y1Xc;18zngAlezVEf/ioD7i8cU?@4JgA0,ibp2hkgofY0w@eFwA0,ybg0x8ykgA44CbhN18ykgA6463_0cfx5Af?3ELa7/QCbnNx8yM183XUji8Bs933Sh50120@5PwA?ct492j//_gofY17gkioJ_8bEa;cvrE4W3/UB492hcynMAa37rj8QJKmM0,OdF2i:pwYvx}goJZ08n_u1B8zngAobEg;W3Cv/Z8w_wg3UiL2g?i8I5Q7g0,Obw?1?18yNn2t<i8IWj3D73UdK2g?j8Ka2,0,S5Og@8fwE0,ydhM59es0fwN4a?1dysp9avVdyvvMj0_1eAyb3ohQ?18yU40.?iUQsdQwVS0@3rgA0,yb3mBQ<fJAAFxcAfx7ka?1cavx8xs1_1P7rWlr/_ZdyvWbv2gAi8Idg7g0,yW////_TZdyv1cyTMAa4ydJ2i:go7w/Yf0fvnioD9iyekMg.801dzpw?wg0MuYvi8Bk94x8w_w13Uj@3w?i8D3i8SQ98;19zhg6j8DMhj7ApwYvh<{]1CpyUf7Ug]4C9M4y3M051wu3/MY0hw@Tx44,<jg74i3D2tu5dxugfBs0x@8x493x9Lv////Z_wub/MY0j2eIQg.801caSMAif1d0m4gi8dY94w03UjT3g?i8Rc961cyQgAi4CVPsPcPcPcPcN8ysYf7Q?{]1CpyUf7Ug]6pCbwYvx}{]1cys18wYs1ivvxj8D0ic7G0QOd599d0t9cat23M319w_w9ioDgy4v_tZp8evAfw_ce?19yvx8yvx9asx9zl3_i8fWfw@61wY0,S9MkC9@Qy9YCbN_kxL5id7?1yYvR8rMRphM?iofxM6bN_kxL1oJ7?1dasIf7Ug]6bOXkydmfZ8w@x0i8f2g6bOpkw0UmbOpkw0S6bNTkzHSSbN_kx_mLZcetxRQQQVMg@4vM<4y9@4i9OAMFO4S9MQQFOQSdk_Z9w_EutzdcasZyYnYErQv_NedZhI01Ne9Z?lohM?Na5ZvUgcw;47SMNZQfkC3U@140tFcatx8oZ980v9CA6pCbwYvx}{}fJDz_i8fE0ky3Mw50y7H_i3D1sKJdoY190v35@7t1Nw?i8JY9118yngAgewLD/_i8Rc961dxuh8yTgAg4CUPsPcPcPcPcN8ysYfx2Ic<f7Q?{]1cyu18wYs1ivvwj8Dwic7G0QOd399d0sBcasy3M319w_M9ioDky4v_tZp8evAfwUcd?19yvx8yvx9asx9zl3_i8fWfw@6CwQ0,S9MkC9@Qy9YCbN_kxL5qd5?1yYvR8rMTphg?iofxM6bN_kxL1gJ6?1dasIf7Ug]6bOXkydmfZ8w@x0i8f2g6bOpkw0UmbOpkw0S6bNTkzHSSbN_kx_mLZ9esdRQQQVMg@4vM<4y9@4i9OAMFO4S9MQQFOQSdo_Z9w_MutzdcasZyYnYErQv_NedZhI01Ne9Z?nohg?Na5ZvUgcw;47SMNZQfkC3U@140tFcatx8oZ980v9CA6pCbwYvx}{}fJDz_i8fE0ky3Mw50y7H_i3D1sKJdoY190v35@7t1Nw?i8JY91x8yngAgeyLDv/i8dY93?i8JQ940fx7c1?19KcTcPcPcPcPci8Rc9618ysZdxuQfx9Ab<f7M1cyux8wYs1ivvwj8DEic7G0QOd399d0sBcasy3M319w_Q9ioDly4v_tZp8evAfwPIc?19yvx8yvx9asx9zl3_i8fWfw@6b0M0,S9MkC9@Qy9YCbN_kxL5id4?1yYvR8rMRph<iofxM6bN_kxL1oJ4?1dasIf7Ug]6bOXkydmfZ8w@x0i8f2g6bOpkw0UmbOpkw0S6bNTkzHSSbN_kx_mLZcetxRQQQVO0@4vM<4y9@4i9OAMFO4S9MQQFOQSdo_Z9w_MutzdcasZyYnYErQv_NedZhI01Ne9Z?loh<Na5ZvUgcw;47SMNZQfkC3U@140tFcatx8oZ980v9CA6pCbwYvx}{}fJDz_i8fE0ky3Mw50y7H_i3D1sKJ9oY180v35@7v6?18yTMAc4y9t2h0W32s/Z8yTgAg4y_PsPcPcPcPcN8zkMAo4C9OkS5Zw@46wA<Yvh<{]1cyv19wY41ifvDj8DMic7G0QOd199d0s1cas23M319w_U9ioDmgox1_Tvlj3D93UdW2w?j8Dfj8D8i2Dfi8Rn_Qy3@zUfxDIa?19yvxdysF8yv9yYvR8rNmygw?oL7Zi6YdS480,C3Uc1yYvR8rMkagM?jiD23N@]6bOXkydmfZ8w@x0i8f2g6bOpkw0UmbOpkw|01Ne9Z?nogw?Na5ZvUg4w;47SMxZQfAC3UK140t9cat18oZ980v9CA6pCbwYvx}{]143Xp0_Qy3W058wY81h8x2_QwVMnbGi6f_i07TNvxTNws0ct98zjT7ew?i8BQ943EaVz/Qydj2hwi8nri8JQ9419KcTcPcPcPcPcioD93Ui3>?{]18ytx9wY41ivvwi8Doic7G0Qydf9980vZ8avy3M318w_I9i8Djgox1_Tvlj3D93Uca2g?j8Dfj8D8i2Dfi8Rn_Qy3@zUfxwY9?19yvxdysF8yv9yYvR8rNkygg?oL7Zi6Ydm440,C3Uc1yYvR8rMmagg?jiD23N@]6bOXkydmfZ8w@x0i8f2g6bOpkw0UmbOpkw|01Ne9Z?logg?Na5ZvUg4w;47SMxZQfAC3UK140t9cat18oZ980v9CA6pCbwYvx}{]143Xp0_Qy3W058wY81h8x2_QwVMnbGi6f_i07TNvxTNws0ct98zjRmeg?Wb2m/@0v2gU07krctJcyv_EvVn/Qydpty9S5J1n45tglV1nRT3i8JQ94ybv2gActbEDFv/Qy3@fZRPUI5ECI?8n0tcnEipj/P7ryPzEI9v/Qyb5vBw?18zjnOfw?i8IWi8D2cs3E1pr/@KsKwE;NZAy9T@xkBL/ict493]ykgA9eAPZL/pF0fJA8Fxc0fxlg5?23@SgfxdI2?3PA8f30uANZL/A4yb3i5H?1cyTMAo4Obt2hEi8K10,0,Kd73t8etwfwFfS/Z8ytFcyvddyvV8yMTPqw?yTMA94S9Y4yU////_TZcyTMAa461Uf/3M19ysB8zrgAw;4Ezxc4,2?ZZtdzpw?wg0i8B494z1XNZ8w_I13UiJ1g?i8nr3UmRZL/NAgAe015cujFZvr/SoK3N@4]11LM4<3Mj0_1eAyb3npG?11Lw4<3FV_n/MYv,ybkz1cysx8ZZx8w@E1i8IdkSE0,wV@w@38wc0,y9wgw1?11Lw4<18yMQSqw?iEQ4dQAVM7c6joD6iiD@joDTY4MfMjB8yMQoqw?i8K14,0,MV@0@3xfn/QO9OAO9O4zTSL183X6h2,0,yb3uZF?3FpLn/Sqgi8I5UmA?f23g1w1i8QZplU?ex8Bf/NE0k:p18yMn1qg?i8K80,0,AVPTdki8D8j2DUi8B4941cev0fwYQ<18ytx1yTQ4Kx;1cyup8asx8yoMAw;4y9x2i8;i8Bc94xcymgAeeyUAL/i8Jc94x8w_wg3Ujx0w?i8I5mCA<@Sg2C4M0@5Jw80,kNQHH//_Lw8<1cyuub1u1w?11KM4<18NUgAxw[1Ch8Ck98U<29x2i:yMmQo<pAi9D2i4;yogAy;bw1;pEC498M<3EhFj/Sq3L2i6:7lrpEeY98U:3Ugc//i8QZnlQ?ex0A/_wbwk]@5YM40,S5Zw@4nvj/QO9YQyb3qxE?1dyvV8zrgAw;4y9n2h0j8JY92zFi0c?6of7Qg?8IZaC<4ydt2hwKww<3EOVb/Sq3L2ie]@4DfX/@KepyUf7Ug]4yb1l5E?3MwQ0o0kydftls?3EK9b/YnVXY2W.<6bNvMx_x2i6;pECk99g<36w1g;1cs1CyogABw<8I5JlY?8C498;2U.<6q9x2i4;yMmnnM?yogAy;bw1;pEC498M<11yQk0yogAA;eJ0pyUf7Ug]bH//_Lwc<1cyuvE3Ff/_q499o;1tjtCwXMAxw:fxnQ1?1CwXMAzw;1R7kyb1oJD?18yU<g?i8Ilvms0,yb4AwVMDeJi8QZ_BI?ezxAv/wbwk]@41_f/Qyb1llD?18xs1Q2UJg68ni3Ukw0M?i8QZPBI?eyNAv/ctL6w1g:WjfO/Yf7M18yvG1UL/3M0fJXhh01<bE1;j8Jh26q5ZAwfhf8NQAzTZHF:i3Dgi0Z7MAS5QHE1;j0Z4QAMVQ4MfhJ2U.<4S9RAS5QAMfhf3FCvP/MYvw:18yMT1pw?i8n9t0Kbghy5M0@5jg40,ydfjFr?3E7p7/Yq05:3FTLT/V1cavCU:4C9PAMfif3FIfT/MYvg02bfi9u?18zngAobE8;ict49601;WaGf/Z8w_z_3Ujo.?i8QZUlE?ez4Af/wbwk]@49080,yb3jxC?18xsAfxdk<1cyTgAgeBF//3NZ4?2bfs9t?18zngAmbE8;W6eg/_FAvX/Sof7Qg?ct492j//_ict493]WtfM/ZCA4Obv2gEi8I5T6k?f18wSw80rI2;3UjY@v/i8JY91x8zjnlcM?KM4<3E3pf/@Dx@v/Kz;1CypgAw;eCU@v/Kj;1CyoMAw;eAC@f/grwM;pAi9x2i:WhbR/Z1Kj;1Ch8Cc98;3FvLf/_23qhw1WqD@/_6w1g:joD@i8JQ93xcyTMAa4S9Y8JY92h9ysB8Kf////Z_go7w/Yf,Ezxc4,2?ZZtdzpw?wg0i8B494x8yQgAgc7L7Qy3@05Q34y9MQCd50rF4v7/QObEgw1?18yQ4Mi8fE0kOb3ulA?1cev0fwGA<1dxugfzG;1bwPPp?@8Bg<4Cdhw6X.<4CZ////_TYB/Yf,QzHc4,2?j2JI94xdxugfBs0x@8x493zF4L7/XYM;pECY98;3FCvn/UI5wCg?8n03Ugq_L/W2md/@beeyeAf/j8Q5tP8?bCw1<i8QlfP40,C9Mkyb1s5p?18zjm2dw?i8IUcs3EQ8X/@Dr_v/hM@TF44,<WlT//MwSwo0uDm_f/joD@i8JQ93xcyTMAa4yb3gtA?3FLfX/QC9YeAgYL/i8DTWoDS/Z9yv3Fwff/Qy9Z@DVZ/_hj70ctbFX_n/QkNOj7iWmnN/Z5cs0NQKBrZ/_hj79ctbFQvb/Qy9YeD8Zf/hj79ctbFf_j/RmZ.<5d8w@Moi8RQ90PE@UX/Qy9MQy3e01QhQydfhdo?3EZET/U2U5:1Qc4yb1mVz?18xs1Q4oJg68nit0HMwSwo.Yvh<i8QZUls?ez4zv/NE0k:37Ji8DvWfec/Z8wYgoyuxrnsdCbwYvx}kXI1;i8fI84ydt2gsW7Oe/Z8ys98wPw0t0u3v2gs0Dgki8DnWbic/Z8wYgwytxrMMYvg018yRw8i8QR5P40,y9h2g8i8DvW62d/Z8yRgA28n03Uib;i8QR@z<4y9TQy9l2g8W3@d/Z8yRgA28n0tll8ylgA24yb7q9y?18zjQHlM?W0Wd/Z8yRgA282U5:1Qaky5STg7yQcoxs1Rjky9l2g8i8QZ05s?ezzzf/i8Jk90z6w1g:Y4y3qMw1ctJ8ytvE1UP/Qy3N229S5L33N@]4yb1jBy?3Mi8d02,NS@LoY8dH6058yNQzow?WWlC3N@4]11lQ5mlld8w@N8i8RQ91PEr8T/Qy9MQy3e01Q3kxzr2gszknZw_w2txWZ.<4y9T@ypy/_i8f4i8DEmRR1nA5vMMYvg018yTI8KwE;NZKyUzf/i8JX4bEa;cvp1ysrExoL/QC9NUfZ0M@4Cg<4ybuNx8zjngbM?i8BY90zE58P/P7ixs1Q7Aybv2g8i8QRLiY?ezZy/_Kw8<25M0@5C;4O9_Ai9Z@xlzv/i8fU_M@4pv/_QydreLUi8Jl080W07hnj8R49218ys6@8;370j8D7i8Qlu2Y0,O9h2g8WeGa/Z8yTQ0i8JQ90wNXuxGzL/Wij/_Yf7Qg?bE1;i8D6h8DTWf2c/Z8w_z_3Ug0//i8D6i8QZdiY?370cuTEwUH/@DJ_L/pwYvh<Kw4<3FnL/_MYv06pCbwYvx}glplkQy3X118zngA3ewezf/i8D3i8cU07g7wTMA309_7HQ1;i8DvW46a/Z8wYggyuxrnk5uMSof7Qg0,ybu0wNZHEa;W62b/Z8ySIgi8QRJ2U0,69NAy9X@zqyL/xs1QjAyddqAK?18yu_ENUH/Un0t5d8zjmxbw?i8DLWbia/@5M7hoi8QR7OU0,y9X@yxyL/xs1Rnki9ZP7JW3ea/_Ftv/_Sof7Qg?bU1;h8DTcuTEioD/@Br//3NZ?37Sh8DTcuTEd8D/@B6//3N@]bU2;h8DTcuTE6oD/@AH//3NZ0,y9XAydfisK<NMeyfyf/WgP/_ZCbwYvx}glplkQy3X118zngA3ezKyL/i8D5i8cU?@4ggc?8dY90M13UU60w?i8J024y9NQC9NKzTx/_i8D3i8n03UjX0w?ZA0E10@4Wg8?379cvp8zhnbbg?i8DvW9W8/YNOrU1;i8Dvi8QlL2Q?ey8yf/csC@0w<4y9TQyd5rcJ?3EsEz/P79Lwc<18ytZ8zhmGbg?W5O8/YNOrU4;i8Dvi8QlDOQ?ex6yf/csC@1g<4y9TQyd5pkJ?3Ec8z/P79Lwo<18ytZ8zhmjbg?W1G8/YNOrU7;i8Dvi8QlyiQ?ew4yf/csC@2;4y9TQyd5nYJ?3EXEv/P79LwA<18ytZ8zhlObg?Wdy7/YNOrUa;i8Dvi8QlpOQ?ez2x/_csC@2M<4y9TQyd5lIJ?3EH8v/P79LwM<18ytZ8zhlhbg?W9q7/YNOrUd;i8Dvi8QlgiQ?ey0x/_csC@3w<4y9TQyd5jwJ?3EqEv/P79LwY<18ytZ8zhkLbg?W5i7/YNOrUg;i8Dvi8QlayQ?ew@x/_csC@4g<4y9TQyd5ioJ?3Ea8v/P79Lx8<18ytZ8zhkqbg?W1a7/YNOrUj;i8Dvi8Ql3OQ?ezYxL/csC@5;4y9TQyd5gcJ?3EVEr/P7ri8DLW2O7/Z8wYggytxrnk5uMV18zjTKaM?W8i6/Z8zjTIaM?W7y6/Z8zjTJaM?W6O6/Z8zjTKaM?W626/Z8zjTJaM?W5i6/Z8zjTJaM?W4y6/Z8zjTRaM?W3O6/Z8zjTRaM?W326/Z8zjTRaM?W2i6/Z8zjTOaM?W1y6/Z8zjTNaM?W0O6/Z8zjTLaM?W026/Z8zjTLaM?Wfi5/Z8zjTFaM?Wey5/Z8zjTGaM?WdO5/Z8zjTHaM?Wd25/Z8zjTMaM?Wci5/Z8zjTSaM?Wby5/Z8zjTQaM?WaO5/Z8zjTPaM?Wa25/Z8zjTNaM?W9i5/_FWvX/MYvw:1cyvvE08v/QO9Z@wUxL/i8D3i8n03UnX_f/A6pCbwYvx}KM4<3FILX/Sof7Qg0,y3X0x8yPSZk<Lw4<3EmUz/Qybfjhh?2@.<exayf/i8IZ0R4?bU1;W3C8/Z8yPTqk<Lw4<3Ea8z/QybfgBh?2@.<ewnyf/i8IZA5<bU1;W0q8/Z8yPTnk<Lw4<3EZov/Qybfnpg?2@.<ezAx/_i8IZXl<bU1;Wde7/Z8yPR4k<Lw4<3EMEv/QybfiJg?2@.<eyNx/_i8IZEB<bU1;Wa27/Z8yPQVk<Lw4<3EzUv/Qybfi1g?2@.<ex@x/_i8IZBR<bU1;W6S7/Z8yPQuk<Lw4<3En8v/Qybfrlf?2@.<exbx/_i8IZh5<bU1;W3G7/Z8yPQXk<Lw4<3Eaov/Qybfh9g?2@.<ewox/_i8IZEkY?bU1;W0u7/Z8yPSMjM?Lw4<3EZEr/P70i8f42cc<3P3NXWi8fI24y3N0z3~&?h;hw;8;7;AQ4gUAihO01eyth0M8jgdko=i;4A<1a;iM<4Q<1f;kw<5g=lw<5A<1q;mM[1s;u46fsBvL828DhYy7ljWCFPcrtQZYh0@HMTuJJLgrNlb1qNYwxw0H41VAKg_fwv4XlcciXAJXPzYyt9rIvlkSGyOaW9UyUFFHpXeFTVTfjdGpl@pnwpJi5RctGEY!?1_;4%1W;4w^2d;4w^1b.0,w^1_.0,w%g;8%3m;4$m.0,w^1h0w0,w^1O;4w^2L0w0,w^3V.0,w^1x.0,w^2C0w0,w^2S.0,%1s;4w%G0w0,w^1l;4w%m0w0,w^1V;4%2J.0,w^27.0,w^3A;4%1K.0,w^1o0w0,w^1z;4$g.0,w^2w.0,w%70w0,w%b.0,w^11.0,w^220w0,w^1i.0,w%l0w0,w^3i.0,$V.0,w%1;8%1T.0,g^1H;4w^3k.0,$@0w0,w^2u;4w^1D.0,w^1A;4w%E.0,%2K;4%2h0w0,w%t0w0,w^>0w0,$4.0,w^2B.0,w%y0w0,w^1E0w0,w^3Y;4w^190w0,w^1R.0,g^2o.0,w^1w.0,w^3N.0,w%S0w0,w^3y.0,w%I;8%39.0,w^16;8w^3w0w0,%32;4%2o0w0,w%e0w0,w^1p.0,g^1q1<4g0p023l[c=2J0M0,g0p063n[c=191<4g0p063l[c=1J1<4g0p0e3k[c=2s0M0,g0p0a3n[c=1D0M0,g0p063o[c=3I0w0,g0p0e3p[c=2a0M0,g0p0e3n[c=2Q0w0,w,,1@[wg4}3d0M0,g0p0e3m[c+k0M0,g0p063p[c+T1<4g0p0a3l[c+d1<4g0p023m[c+V0M0,g0p0e3o[c+?M0,g0p0a3p[c+C1<4g0p0e3l[c=3f0w0,g0p023q[c=1k0M0,g0p0a3o[c=1W0M0,g0p023o[c=3?M0,g0p023n[c=3x0M0,g0p0a3m[c=3R0M0,g0p063m[c+C0M0,g0p023p[c+0nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0nRZzu65vpCBKomNFuCk0sThOoSxO07dQsCNBrw1Urm5Ir6Zz06RBrmdMug1Pt79zs7A0u6pOpmk0pCBKp5ZSon9Fom9Ipg1vnSlOsCVLnSNLoS5QqmZK05ZvqndLoP8PnTdQsDhLr01yqmVAnS5OsC5VnTpxsCBxoCNB069FrChvondPrSdvtC5Oqm5yr6k0oDlFr7hFrBZBsD9Lsw1JomJBnSVBtRZxsD9xulZSon9Fom9Ipg1PundzrSVC06ZMpmUSd01Opm5A06dIrTdB05ZvqndLoP8PnTdQsDhLtmNI06tBt5ZPt79FrCtvtC5Itmk0sTBPoS5Ir01JqTdQpmRMdzg0tmVIqmVH07dQsCdJs01Pt6hBsD80pDtOqnhB06RJon0Sd01JpmRPpng0nRZBrDpFsCZK07dQsCVzrn?nRZFsSZzczdvsThOt6ZIr01BtClKt6pA071Fs6k0pCdKt6MSd01PrD1OqmVQpw1yqmVAnS5OsC5VnSlIpmRBrDg0sThOpn9OrT80tmVyqmVAnTpxsCBxoCNB071LsSBUnSRBrm5IqmtK06NPpmlHdzg0oSNLoSJvpSlQt6BJpg1JpmRzq780tndIpmlM06pMsCBKt6o0s6ZIr0>sClxp3oQ06pxr6NLoS5QpjoQ06pPt65Qdzg0sSlKp6pFr6kSd01PundFrCpL07dMr6Bzpg1zrT1VnSpFr6lvsC5KpSk0rmlJsCdEsw1JomJBnS9RqmNQqmVvon9Dtw1vnThIsRZDpnhvomhAsw1JtmVJon?nRZzt7BMplZynSNLoM1Pq7lQp6ZTrw>tnhP07dBt7lMnS9RqmNQqmVvpCZOqT9RrBZOqmVD079FrCtvqmVFt5ZPt79RoTg0omhAnS9RqmNQqmU0sCBKpRZApndQsCZVnTdQsDlzt01OqmVDnTdzomVKpn9vsThOtmdQ079FrCtvoSNxqmRvsThOtmdQ079FrCtvtSZOqSlOnTdQsDlzt01OqmVDnSdIpm5Ktn1vtS5Ft6lOnTdQsDlzt01OqmVDnSBKpSlPt5ZPt79RoTg0sCBKpRZComNIrTtvsThOtmdQ079FrCtvomdHnTdQsDlzt01OqmVDnSZOp6lOnTdQsDlzt01OqmVDnSdLs7BvsThOtmdQ079FrCtvsSBDrC5InTdQsDlzt01IsSlBqRZPt79RoTg0sCBKpRZFrChBu6lOnTdQsDlzt01OqmVDnSpBt6dEpn9vsThOtmdQ079FrCtvpC5Ir6ZTnT1EundvsThOtmdQ079FrCtvrmlJpChvoT9BonhBnTdQsDlzt01OqmVDnTdBomNvsThOtmdQ079FrCtvpCdKt6NvsThOtmdQ079FrCtvs6BMplZPt79RoTg0sCBKpRZPs6NFoSlvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0r6ByoOVPrOUS06NAbmNFrDlUbnwUdyQSd2VPrOUO,tcik93nP8KcM17j4B2gRYObzcP,tcik93nP8KdM17j4B2gRYObz8U,tcik93nP8Kcjg0hQN9gAdvcyUOdM17j4B2gRYObz4M,tcik93nP8Kcjs0hQN9gAdvcyUR,tcik93nP8KcPw0hQN9gAdvcyUObzk;1?8?w02?80.01?c01?2?801g02?80.02?o?w020,?w030,?w070,?w02?8?w02?w?w020,?w01?802g01?E?M02?80.01?8?w01?802M02?8?w02?803?2?803g020,?w020,0.0a?8?w010,0.010,0.010,0.010,0.010,0.010,0.010,0.010,;10,0y.?1:w;4SBF3g?202t1=402M1@1<4=2PApo6<d0as4<g;5SBF3g?302O1<4;8yhBwo<I0L.?1:jqmAd<a09Q4<g;B96m1w?2g371<4;8uhBwo<s0Qwg?1;2gApo6<60dQ4<g;BV6m1w?1g3E1<4;1lFqgQ<g0YMg?1;2UApo6<30fQ4<g;thFF2g<w081g}13d[2=2M>}1zd[2=>>}23d[2+wPg}23i[2=3QGg}2zi[2+3Gw}43i[2+jGw}4zi[2+gHw}63i[2+vGw}6zi[2+HGw}83i[2=13Gw}8zi[2=1gGw}a3i[2=1CGw}azi[2=1NGw}c3i[2=20Gw}czi[2=2dGw}e3i[2=2BGw}ezi[2=2CGg[3j[2=2RGw[zj[2=2pGg}23j[2=32Gw}2zj[2=2cGg}43j[2=3fGw}4zj[2=3nGw}63j[2=3HGw}6zj[2=3WGw}83j[2+bGM}8zj[2+sGM}a3j[2+NGM}azj[2=10GM}c3j[2=1sGM}czj[2=1CGM}e3j[2=1ZGM}ezj[2=10Hw[3k[2=2cGM[zk[2=14Gg}23k[2=2qGM}2zk[2+MGg}43k[2=2FGM}4zk[2=2UGM}63k[2=3eGM}6zk[2=1wHw}83k[2=3qGM}8zk[2=3CGM}a3k[2+3H[azk[2=3_G[c3k[2+gH[czk[2+IH[e3k[2+@H[ezk[2=3guw}fzk[2+wQw[3l[2+3Gw}23l[2=3EGg}2zl[2=1gog}3zl[2=10Qw}43l[2+gHw}63l[2=3uGg}6zl[2=3gnM}7zl[2=1wQw}83l[2+HGw}a3l[2=3jGg}azl[2=2Mug}bzl[2=20Qw}c3l[2=1gGw}e3l[2=39Gg}ezl[2+gnM}fzl[2=2wQw[3m[2=1NGw}23m[2=2TGg}2zm[2=1wnw}3zm[2=30Qw}43m[2=2dGw}63m[2=2CGg}6zm[2+gnw}7zm[2=3wQw}83m[2=2CGg}a3m[2=2pGg}azm[2+wmM}bzm[2+0QM}c3m[2=2pGg}e3m[2=2cGg}ezm[2=3gmw}fzm[2+wQM[3n[2=2cGg}23n[2=26Gg}2zn[2=1gu[3zn[2=10QM}43n[2=3nGw}63n[2=1WGg}6zn[2+gmw}7zn[2=1wQM}83n[2=3WGw}a3n[2=>Gg}azn[2=30mg}bzn[2=20QM}c3n[2+sGM}e3n[2=1BGg}ezn[2=>mg}fzn[2=2wQM[3o[2=10GM}23o[2=1sGg}2zo[2=3glg}3zo[2=30QM}43o[2=1CGM}63o[2=1gGg}6zo[2=20lg}7zo[2=3wQM}83o[2=10Hw}a3o[2=14Gg}azo[2=10lg}bzo[2+0R[c3o[2=14Gg}e3o[2+MGg}ezo[2=30tw}fzo[2+wR=3p[2+MGg}23p[2+AGg}2zp[2=10tM}3zp[2=10R[43p[2=2UGM}63p[2+pGg}6zp[2=2Mp[7zp[2=1wR[83p[2=1wHw}a3p[2+cGg}azp[2=3Ml[bzp[2=20R[c3p[2=3CGM}e3p[2=3_G[ezp[2+goM}fzp[2=2wR=3q[2=3_G[23q[2=3RG[2zq[2=2wl[3zq[2=30R[43q[2+IH[fze[4&zf[1w<5o-13f[1w<58-1zf[1w;o-23f[1w<4E-2zf[1w<4Q-33f[1w<5c-3zf[1w<4I-43f[1w<4o-4zf[1w<4Y-53f[1w<5A-5zf[1w<5)63f[1w<4A-6zf[1w<5I-73f[1w<5g-7zf[1w<2k-83f[1w<2o-8zf[1w<5s-93f[1w<4M-9zf[1w<5M-a3f[1w<4w-azf[1w<4s-b3f[1w<5k-bzf[1w<54-c3f[1w<5w-czf[1w<3U-d3f[1w<5E-dzf[1w<4)e3f[1w<4k)3g[>;4)zg[>;8-13g[>;c-1zg[>;g-23g[>;k-2zg[>;s-33g[>;w-3zg[>;A-43g[>;E-4zg[>;I-53g[>;M-5zg[>;Q-63g[>;U-6zg[>;Y-73g[><1)7zg[><14-83g[><18-8zg[><1c-93g[><1g-9zg[><1k-a3g[><1o-azg[><1s-b3g[><1w-bzg[><1A-c3g[><1E-czg[><1I-d3g[><>-dzg[><1Q-e3g[><1U-ezg[><1Y-f3g[><2)fzg[><24)3h[><28)zh[><2c-13h[><2g-1zh[><2s-23h[><2w-2zh[><2A-33h[><2E-3zh[><2I-43h[><2M-4zh[><2Q-53h[><2U-5zh[><2Y-63h[><3)6zh[><34-73h[><38-7zh[><3c-83h[><3g-8zh[><3k-93h[><3o-9zh[><3s-a3h[><3A-azh[><3E-b3h[><3I-bzh[><3M-c3h[><3Q-czh[><3Y-d3h[><4)dzh[><44-e3h[><48-ezh[><4c-f3h[><4g!]1ComBIpmgwt6YwoT9BonhB865OsC5Vey0BsM0BsPEwrCZQ865K865OsC5V,pfkAJilkVvhAZigQlvhA5cj491gQI0bShBtyZPq6Q0bThJs016jR9bkBlenQh5gBl707hOtmk0pCZOqT9Rry1rh4l2lktt84lKom9Ipmga06RJon0W82lP06VnrT9Hpn9Pjm5U06VnrT9Hpn9P06VcqmVBsQRxu01KgDBQpnddonw.l97nQR1m?JbntLsCJBsDcJrm5Ufg0JbntLsCJBsDcMfg0JbntLsCJBsDcZ02QJr6BKpncJrm5Ufg0JbmNFrClPc3Q0biRIqmVBsPQ0biRyunhBsORJonwZ02QJoDBQpncMfg0Jbm9Vt6lPfg0JbmNFrmBQfg0JbnhFrmlLtngZ02QJpT9BpmhV02QJrTlQfg0JbnhFrmlLtng09mg0hlp6h5ZiikV7nQh1l440hlp6h5ZiikV7nQlfhw15lAp4nR99jAtvikV7hldknQh1l440hlp6h5ZiikV7nQBehQljl5Z5jQo0hlp6h5ZiikV7nRdkgl9mhg1CrT9HsDlKnSZRt?Br7ka07tOqnhBa6pAnTdMontKb21PoDlCb21Pr6lKag1CrT9HsDlKnT9FrCsKoM1TsCBQpixBtCpAnShxt64I9DoIe2A0u0E0tT9Ft6kEpChvsT1xtSUI829Un6Uyb20Oag1TsCBQpixBtCpAnSlLpyMw9ClLpBZPqmsI83wF06hOug0BsOUBr7k0kABehRZ9jAt5kRhvh4Bmildfkw1iikV7nQ91l4d8nQB4m01iikV7nQ91l4d8nRdcjRhj,p4nQZih4linR19k4k0tT9Ft6kEpCgI82pSomMI83wF07tOqnhBa6pAnSNLoS5InTdFpOMw9CZKpiMwe2A0pCZOqT9RrBZFrD1Rt01JpmRCp5ZzsClxt6kwpC5Fr6lAey0BsM>qn1B86pxqmNBp3Ew9nc0oSNLsSk0sT1IqmdB86pxqmNBp3Ew9nc0c01TsCBQpixBtCpAnShxt64I82pLrCkI83wF06BKoM1Apmc0kQl5iRZjhlg0kQl5iRZ5jAg09mNIp?Br6NA2w1Pq7lQp6ZTrBZT07dEtnhArTtKnT80sSxRt6hLtSVvsDs0tmVHrCZTry1zrSRJomVAey0BsM1OqmVDnSBKqng0sCBKpRZApndQsCZV079FrCtvsSdxrCVBsw1OqmVDnSdIomBJ079FrCtvtSZOqSlO079FrCtvoSNBomVRs5ZTomBQpn80sCBKpRZFrCtBsTg0sCBKpRZComNIrTs0sCBKpRZxoSI0sCBKpRZLsChBsw1OqmVDnSdLs7A0sCBKpRZPqmtKomM0r7dBpmI0sCBKpRZFrChBu6lO079FrCtvpClQoSxBsw1OqmVDnSpxr6NLtRZMq7BP079FrCtvrmlJpChvoT9BonhB079FrCtvsSlxr01OqmVDnSpzrDhI079FrCtvs6BMpg1OqmVDnTdMr6Bzpg1cqndQ86NLomhxoCNBsM1OqmVDnSNFsTgwmRp1kBQ0kT1IqmdB86hxt64.T9BonhB871Fs6k0sCBKpRZMqn1B83N1kB9YkAg@85JnkBQ0hCBIpi1zrSVQsCZI079FrCtvpCdKt6Mwf4p4fy0YoSRAfw1jpm5I86RBrmpA079FrCtvsSlxr20YhAg@,dOpm5Qpi1JpmRCp01OqmVDnSRBrmpAnSdOpm5Qpi0YlA5ifw1gq7BPqmdxr21ComNIrTs0jBldgi16pnhzq6lO,Vljk4wimVApnxBsw1jpmlH86pA06NPpmlH83N6h3Uwf4Z6hzUKbyU0kSBDrC5I86lSpmVQpCg0sCBKpRZPqmtKomMwf4p4fw1qpn9LbmdLs7AwqmVDpndQ079FrCtvoSZMui0YjRlkfy0YikU@059BrT9Apn8wrTlQs7lQ079FrCtvrT9Apn8wf4p4fy0Yk4pov6RBrmpAfw11oSIwoC5QoSw0sCBKpRZxoSIwf4p4fy0YhAhvjRlkfw1crStFoS5I86pxr6NLtM1jqmtKomMwqmVDpndQ,dIpm5Ktn0wtS5Ft6lO05tLsCJBsy1zrSVQsCZI079FrCtvtSZOqSlO85JFrCdYp6lzng13r65Fri1yonhzq01itmUwsSdxrCVBsw1OqmVDnTdzomVKpn8wf6pAfy1rsT1xtSVvpCht,hBsThOrTAwsCBKpM19rCBQqm5IqnFB879FrCswtSBQq21zrSVCqms0sCBKpRZFrCBQ85J6j457kRQ0sCBKpRZIqndQ06BKtC5IqmgwrDlJpn9FoO1FrChBu21CrT8wqmVApnxBp21xsD9xujEw9nc]2ZPuncLp6lSqmdBsOZPundQpmQLoT1RbSdMtj0LoS5zq6kLqmVApnwPbTdFuCk?6pLsCJOtmUwmQh5gBl7ni0BsPEBp3Ew9ncwpC5Fr6lAey0BsME<1TsCBQpixBtCpAnSBKpSlPt5ZAonhxb20CtyMwe2A?7tOqnhBa6pAnSpxr6NLtOMw9CBMb21PqnFBrSoEqn0Fag[1CrT9HsDlK85J4hk9lhRQwsCBKpRZxoSIwr7dBpmIwpC5Fr6lAey0BsME}1TsCBQpixCp5ZMqn1Bb20CrT0I87dFuClLpyxLs2AF07tOqnhBa6pAnThxsCtBt2Mw9CBMb21PqnFBrSoEqn0Fag[1TsCBQpixCp5ZDr6ZyomNvomdHb20Cs70I87dFuClLpyxMs2AF;pCZOqT9Rry1rh4l2lktt879FrCtvsSlxr21ComBIpmgW82lP2w<6pLsCJOtmUwmQh5gBl7ni1OqmVDnSdIomBJ86NPpmlH86pxqmNBp3Ew9nca:79FrCtvsT1IqmdB83N9jzUwf4Zll3Uwf4Z6hzUwf4N5jzUwmSdIrTdBng}79FrCtvpC5Ir6ZT83Ngil15fy0YhABchjUwmShOulQ0sCBKpRZzr65Fri0YjQp6fy0YgQVkfy1rgBBkhldt85J6h5Q)?bShBtyZPq6QLpCZOqT9RryZQrn0LpCZOqT9RryVom5w1*7M0u01Q07?r01E06g0o01s05w0l01g,M0i014,?f?U03g0c?I02w09?w0>06?k01?3?80.;7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3/_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe3MUd30Ia2gw71wk40M81?Ye3gMb2wA8>o510c2.,;8:k<17jBk0.0>.;V+8?s,;3g=16McX9,?2c;wk/_g,?f1n/ZE.?c5H/@01<wm/_308?61s/YM0w?A6z/U02?10y/_W08?12c/YQ0M?w8X/U03<gAf/P0c?a2n/_Y0M?Yab/Sg4?3gFf/J.?22B/_k1<san/_g4?2MFv/50k<2C/YQ1g?EaD/TM5?3MGv/D0k0,2G/@Y1g<aL/@w5?1gG/_20o0,2K/Zk1w?AaX/Tg6?10H/_G0o<2M/_c1w?wb7/M07?10I/_j0s?e2Q/ZU>?Ycr/Ww7?>N/_Q0s?838/_Y>?UcD/Pw8;O/_r0w?73e/@w2[1g+nFi?5U4,r30s8A,?2g;s;S57/M,;3x163xxa3MJT28?fNEXazcA8w;1Q;h;81m/YR0w<4Ie48U2gwUozgd23y2c14Aea8o5ggUMwMp73B1w2wUMiscea4763y12P0UogIQe44be3wx82MdM.Eec4j33yx1NwUwgIMe64bd3x12PwU8jgJM3wz3NIPdPAwek8c6xwmc18Q3zw8E;L;4xo/_K:44e48c2igVgjwEe444e24sb0B8a3x153wx92O;3E;35D/Pc1;ggUgwM9e3C02lgEe44ce24Ab,M;c.?a5H/OEc;gwUgzM923xye0Q8e88Q4hgUEz0l13z261A4ee8c7hMW02gfb.Eee44ec44ea48e848e648e448e24sb;p;5M1<8pL/Hy8<1b3x2f0Ase68U3gwUwzgh23yyc1k4ec8o6h0UUwMt93F030@gc3wz3NIPdPIZ83F03wMu61EM5zgie0UY20Vc12wUUgMUMggUEgwUwgwUogwUggwU8ggJ8;N,?528/_8:48e48Y2gwUozwd53y2d148ea8M5ggUMxwp13zy31Qgek0at2wUUh0UMggUEgwUwgwUogwUggwU8hgI0i;102?3kyf/pw8<1i3x2f0AEe68U3gwUwzgh23yyc1k4ec8o6gMUUwMta3K080Kca3zx33z113yx23y123xx23x123wx32Qw<1s0w?@8H/Ug1;kwUgzM973xye0Qke88Q4gwUEz0l13z261A4ee8c7iwXw20db.UUgMUMggUEgwUwgwUogwUggwU8<I;G08?3Oc/@g><54e48o2i0Q6h8Y3zwh8zgmc1Ec70QY32wM724gb?1A;S08?9Oj/Ze2M<4Ie48Y2hMUozwd23y2d14kea8M5ggUMxwp43zy31QAeU0c3_g4a3zx13z113yx23y123xx23x123wx22MaM3wz3NIPdPIZg3K03wMu61EM5zgie0UY2,M<1?M?x9X/Zs1;kwUgzM973xye0Q8e88Q4gwUEz0l13z261A4ee8c7iwWgwwg3bw4a3zx13z113yx23y123xx23x123wx72M?7;903<kEf/hg;113x230AAec7se44ce2?s;I0c0,iw/Z5:44e48c2igUMtMUggMU80><3g0M?ta3/PY:ggUgwM993y1N3x133ww07;f03?2kEf/hg;113x230AAec7se44ce2014;4.?ciw/@p0M<48e48Y2gwUozwd23y2c144ea8o5hwUMwMp73L010WQ12wUMgMUEggUwgwUogwUggwU8ggI;s;m.?1OA/Z5:44e48c2igUMtMUggMU80><1U1<jaj/Qk:ggUgwM993z1T3x133ww0a;9w4?1YFf/M:113x260Aoe68c3h0UM0AMa3xx33x113wx52M0s;N.?12B/Z5:44e48c2igUMtMUggMU8,w<3A1<gan/@w2;gwUgzM923xye0Q8e88Q4gwUEz0l13z261A4ee8c7igWg0mwa3zx33z113yx23y123xx23x123wx92M0s;c0k?eiD/Z5:44e48c2igUMtMUggMU803;1g1g?5az/Wg:gwUgzw913xy60Qoe88c4h0Vg0Cga3y133xx13x123wx92M0w;x0k?92E/@@:44e48c2h0UM0BEa3x133wx62M0M;G0k?2OF/ZT.<48e48U2ggUoxwd63y2314gek0aP2wUwgMUoggUggwU8iwI0i;dM5?1UGL/LM4<123x2f0A8e68U3gwUwzgh23yyc1k4ec8o6hwUUwMt43C1L2wUUgMUMggUEgwUwgwUogwUggwU8gwI?2w;E1w?XaL/VY1;ggUgxw963xy30Qgec0be2wUogMUgggU8gMI0b;5g6?1wHv/418<113x260Acd1ACf0UU4zgmc1Ec70_g92wM7244b;9;8g6?10L/_tw;113x260Aoe68c3h0UM0Coe64ce444e22w<2I1w?Cb/_Ms1;ggUgwM993z1C2wUggMU8hgI2FgEe44ce24wbe;dw6?1YMf/kw4<123x2f0A8e68U3ggUwxwh13yy31kges74a3yx33y113xx23x123wx52M?c;1g7?2wMv/5w4<123x2e0A4e68o3ggUwwMh43z1H2wUwgMUoggUggwU8hMI?3;18>?zcb/SE3;gwUgzw913xy60Q4e88c4h0UM0O022wUwgMUoggUggwU8gwIo;v0s?cz5/@1.<4ge40dY.U8~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~-3//_:b07[s0s[wPg[4=vwg[1=8w4[3=3c0w[Q=N7Y[p=13d[6M=8=1E=6cQ[s+w=ZvX_rM]w=k=u8A[6=c2=2w=k1g[I=6+3=ezf=w[3E1g}1g=>=n=8yv[>=EA=w=o0Y[9=1w=_L/rM;18zM}f/_SY]w[3M/ZL:8Oe[@v/rM;27~~~~~~~~~~!}acQ!1wc[m0M}2o3[dwc}160M}5o3[pwc}1S0M}8o3[Bwc}2C0M}bo3[Nwc}3m0M}eo3[Zwc[61[1o4[9wg[S1[4o4[lwg}1C1[7o4[xwg}2m1[ao4[Jwg}361[do4[Vwg}3S1=o5[5wk[C1g}3o5[hwk}1m1g}6o5[twk}261g}9o5[Fwk}2S1g}co5[Rwk}3C1g}fo5[1wo[m1w}2o6[dwo}161w}5o6[pwo}1S1w}8o6[Bwo}2C1w}bo6[Nwo}3m1w}eo6)<3/////////////M;3/////_iF=WE!4WE[gHw!vGw}2KG!4eG[kaE!pGE}1NGw#20Gw}8SG!amG[FGA!JqE}2pGg#32Gw}8OF!c@G[RWE!WWE}3WGw!bGM}1OH!36H[gaI!naI}1CGM#1ZGM}42K!8OH[haA!CGI[MGg#2FGM}byH!cWH[oaU!SGI}3CGM!3H[f@E!12I[baM!fGM}3guw[4=8d8[3Gw`eyF[k64[1=43i[4aU`3uGg}d1v=g[1wQw}2KG~QWA}2Mug[4=wd8}1gGw`cCF[45Y[1=a3i[sqE`2TGg}61u=g[30Qw}8SG~FGA[gnw[4=Ud8}2CGg`9CF[85I[1+3j[CqA`2cGg}d1q=g=wQM}8OF~xGA}1gu=4=gdc}3nGw`7GF[45E[1=63j[@GE`>Gg}c1p=g[20QM}1OH~pqA}>mg[4=Edc}10GM`5OF[Q5k[1=c3j[pGI`1gGg}81l=g[3wQM}42K~haA}10lg[4+dg}14Gg`32F[M7o[1=23k[caA~AGg}41T=g[10R[byH~6qA}2Mp=4=odg}1wHw~OF[Y5g[1=83k[VGI`3_G[11z=g[2wR[f@E~Zqw}2wl=4=Mdg[IH(hQd3ey0EhQVlai0NdiUObz4wcz0Odj4Ocj4wa59Bp218ongwcjkKcyUNbjkF;2;1}g?hQ4A0jdxcg3c0w}d5_=2VPq7dQsDhxow0KrCZQpiVDrDkKoDlFr6gJqmg0bCBKqng0bDhBu7g0bCpFrCA0bCtKtiVEondE02VAumVPumQ0bChVrDdQsw0KpSVRbDpBsDdFrSU0bCtKtiVSpn9PqmZKnT80bD9Br64Kp7BK02VOpmNxbD1It?KsCZAonhx02VKrThBbCtKtiVMsCZMpn9Qug0KpmxvpD9xrmlvq6hO02VBq5ZCsC5Jpg0Kt6hxt640bDhysTc0bCBKqnhvon9OonA0bCpFrCBvon9OonA0bChxt64KsClIbD9L02VAumVxrmBz02VDrTg0bCtLt2VMr7g0bChxt640bC9PsM0KoSZJrmlKt?KpSVRbC9RqmNAbC5Qt79FoDlQpnc~~+?b;>;8=G08}2E0w}2g*4*7w;4;6=cM2[P08[r*1*7k;1;1w[3M0w}f02+g)<1+4+A:g;o+0s=>}c5U)<1&aw;4;6=ch_[N7Y[d*1*3;3S/ZL0w+w=2=M+7+w*W;2M;8=M8[30w[bw8[2:4;8=1w=gw;c;2=7y9[u8A[k1g(g(4E<3/_ZL0w[2czw}8Oe[Kw=7+8+w[1n;_L/rM8=i8Y}18zM}e+2:8;8*pw;g;2=2yg[a9[1w3M[s=2+o=7:4;gw[28DM}8yv[W0k[7;6:w=6=1W:g;8=wak}20Fg}20a)<1&ww;s;2=a2L[EaY[M*2*9k;1:w[3gHM}d2L[9,(g(2z:g;8=@b[3UI[9w7(8*Hg;4;31=zd[2bQ[4*2*bg;8:Mg[gPg}12Z[3g*w(2W;3w;c=4cQ[gLg[w*8+w=Nw;Y;3=1zd[6bQ[8*2+8=d8;1:M=wPg}22Z[2&w(3v;1w;c=acQ[ELg}d01[2+8=1+W:4;3=fze[@bU}3M*2+8=eQ;1:M[3EPM}ey_[408(w=2=3S:g;c+d8=Mw}508(w*_:w;3=53q[kcE[E*2&41<1;c*53a[bw*4+g=a.?>-ufE}20Ow}2g*4&g;c%FcE[w.(g)<')


_forkrun_bootstrap_setup --force

