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


declare -a b64=([0]=$'116366 58184\nmd5sum:d32472c17ab5cbe95831216ac2f2e2fd\nsha256sum:436899a5616a0ff2cad1a5bc864da7d98aefa7d720e94d2163203e8574937b7f\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n1yYKR8zlz_i8fEg4y3MA1yYCl8\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n6pCbwYvx\n00000000\n0000000\n000000\n00000\n0000\n000\n01\n04\n00\n0g\n__\n0dxyYtR8WZJyYvR8vRH_j3Dgttdcessfx8;1cysx4ys9cas19yvFdas9dzlH_iofX7DoPjiD1oJ5_a6Z1_Yjzvkr.sjyvg\034vQlchw81?+.c0fw,-1+czr+<4.e.b>.7w0t0>;5!}ooc}1xwM=g=g;g:A=2g=9[2ge[90U=1=1;1w;zd[2dQ[8Tg}4wd[s0Q=4=8;6;acQ[ETg}2zt[Q>}3g?[w=1:g<2E0w}aw2[G08[A=2g=1+4;1;a2_[EbY}2wLM}3+c+8+s;4;2cQ[8Tg[zt[1+l+w=k@lQp?<2wLM}a2_[EbY[M=3+2=1gVnhA1;d2_[QbY}3gLM}2g1[9>[4=57Bt6g6~)0,+kKlQp?;8Pg[zt[2dQ}3U0w}fw2=g=4;5:c<17jBk0FOM9va42UoZYxK2oftLM8FEEKyzP3NXWi8fI24yb1pTs0,8xs1Q0L_gi8f42cc+03_dvHs.3_9vPs<f7Q._OnWT<q:3FUf//YBYJM.6w1;Wt3//_9uHs0,E0w<eD0//_OnyT<q0c<3FIf//YBSJM.6w4;Wq3//_9tbs0,E1g<eCg//_OnaT<q0o<3Fwf//YBMJM.6w7;Wn3//_9rHs0,E2;eBw//_OmOT<q0A<3Fkf//YBGJM.6wa;Wk3//_9qbs0,E2M<eAM//_OmqT<q0M<3F8f//YBAJM.6wd;Wh3//_9oHs0,E3w<eA0//_Om2T<q0Y<3FYfX/_YBuJM.6wg;Wu3@//9nbs0,E4g<eDg_L/_OlGT<q18<3FMfX/_YBoJM.6wj;Wr3@//9lHs0,E5;eCw_L/_OliT<q1k<3FAfX/_YBiJM.6wm;Wo3@//9kbs0,E5M<eBM_L/_OkWT<q1w<3FofX/_YBcJM.6wp;Wl3@//9iHs0,E6w<eB0_L/_OkyT<q1I<3FcfX/_YB6JM.6ws;Wi3@//9hbs0,E7g<eAg_L/_OkaT<q1U<3F0fX/_YB0JM.6wv;Wv3Z//9vHr0,E8;eDw_v/_OnOSM.q24<3FQfT/_YBWJI.6wy;Ws3Z//9ubr0,E8M<eCM_v/_OnqSM.q2g<3FEfT/_YBQJI.6wB;Wp3Z//9sHr0,E9w<eC0_v/_On2SM.q2s<3FsfT/_YBKJI.6wE;Wm3Z//9rbr0,Eag<eBg_v/_OmGSM.q2E<3FgfT/_YBEJI.6wH;Wj3Z//9pHr0,Eb;eAw_v/_OmiSM.q2Q<3F4fT/_YByJI.6wK;Wg3Z//9obr0,EbM<eDM_f/_OlWSM.q3;3FUfP/_YBsJI.6wN;Wt3Y//9mHr0,Ecw<eD0_f/_OlySM.q3c<3FIfP/_YBmJI.6wQ;Wq3Y//9lbr0,Edg<eCg_f/_OlaSM.q3o<3FwfP/_YBgJI.6wT;Wn3Y//9jHr0,Ee;eBw_f/_OkOSM.q3A<3FkfP/_YBaJI.6wW;Wk3Y//9ibr0,EeM<eAM_f/_OkqSM.q3M<3F8fP/_YB4JI.6wZ;Wh3Y//9gHr0,Efw<eA0_f/&4ydfkDz0,8zgl2UM.i3DUt1l8yMn@RM.i8n0t0D_U0Yvw:333N@]4ydfhDz0,8zjkiUM.i2D@i8DMic7KfQz1@0d80sp8QvVQ54yb1mTo0,8xs1Q2f_wpwYvh<MMYvw:3P3NXWw3TlUw<7kHlky3flbo;i8DBt0N8zjSeRg.W0D//Epf/_Yo5Hu8<5tMMYv0ccf7U]YMYu@KBT//3N@]4y5_M@41M80>5mgll1l4C9ZbVr;lld8yvJ8w@MwW1LY/Z8ysl8xs1Q3Qy9T@zH@/_w7M3_RRQ74y3N21cyup8ytYNQBJtglN1nk5uWiLZ/Yf7M19yuV8wYk1iiDuioR@0uxl_f/i8Duj8DOioD5i8D7WfjY/Z3NAgR0,8yu_EBLL/QydkfZ8yst8yggAi8Bk90zE8vP/Qybl2g8i8DKi8D7i8D3WbXY/Z8yMMAj8DLNAgb_M3EnvL/Qydu07EZfL/QO9XAy9N@zF@L/i8Dvi8D5W3XX/Z8znw1WdnX/Z8ytV8ysvEOLH/QO9VQC9NKwv@/_i8RU0uyS@/_j8DCi8D7WaLW/ZcyuZ9ysjEgfL/Qy9T@wU@/_i8DLW13W/Z8xs0fxdY<2bk2zSMA1RnUfy10@4Hw<4z7h2go:ew8@L/i8RQ91yW2w<4O9ZYs]4y9M@wJ_f/i8D6i8J491x9espQo80U07lrwPIyt5oNOkO9UAy9X@x9_f/WNIf7U]hj70j8Dxj8DOi8DKi8D7W4PZ/Z8yu_EFfH/QO9Z@ys@L/i8f484O9VRJtglN1nk5uWozW/Yf7Ug]4O9ZAydfpWO<NMeyv@v/WY4f7Qg0>y9XAydftCH<NMey7@v/WWAf7Qg.ccf7U]i8DLW73W/Z8yuV8zjSmGM.i8n03Uk6//WYZCpyUf7Ug]5e_Mw<4y3X43E4vP/Qy5M7Uci8f4g5L3pwYvh<i8QZkr8.37Scs3EIfL/UD7xs1UarEv;i8RQ9229h2gcW7vW/@bv2gci8A49ewW@L/i8Ik94y5QDYxLXY<3EJ_L/Qy5M7Vqi8f4g4z1U0drMMYvx}NAgk8,8zngA6bEa;i8RY923EN_z/Qybl2go3Xoiw@bvwfFbt3Z8ys58Mu4kwfFdi0Z4Mky5M7izWlf/_Yf7U]LY8<3EjLL/Qy5M7@nK<g03Fc//MYvw:18Mu0aWYBCA5d8yvJ8zjSNGw.i8fIkeyc@L/i8n0t5u0e35RkE1U?1RjbG.g.LE8?g18zjSuGw.cs3EJfH/UD2xs1V7HG.g.LE8?g18zjS9Gw.cs3EBLH/UD2xs1Um4y3N529Q5L33N@4]2W0w<4y9THY_?.cs3EHfD/UD2xs1VRKyxZ/_wPwmtp0NQAy9THY_?.cs3Ey_D/UD2xs0fy7n//HHMYvw:35@mY5Ub80>ydv2ggibwKm5xom5xo>y9v2g8i8B49235@nZ4913E_fz/Qybv2g8xs29MDwpylgA2ex8Z/_yRgA2eBv//3N@]cnVrMmwIw.NQgA85xom035@nZ4913ELvz/Qybv2g8xs29MDD1WiT/_ZCA{}glt1lA5lioDRglhlkQy1X4w4.29f2h8zjS3Gg.W3TV/Z8xs0fx1M1.20e34fxeI10,8zjlPGg.i8D7W7PU/@5M0@5_;4yb1lTj.2W6;bU1;i8QZkaA.cs5QJQ<4<18yMzEGLD/QObfrLt0,dxvYfxtM<15csAN_Q6U//_XAx;Kwc<2@,2w0eyr@f/i8fU_M@4ugE.37SKw?E,8yst8yglUTg.W6LT/@_l;ewx@v/i8QZ0aA0>y9M@y2@f/i8n0t1CW2w<37Si8D7W3XU/Z8ykgA24y5M7Yii8nrgrM1;j0ZfUQO9p2g8i8QZPqw.ex6@f/i8n03Ugd?.cvqW2w<4y9N@z@Z/_i8n03UXR;i8B4913FZ:Yv>ObfuDs.371uvs[jon_3UgA//iss7:4yb1szs0,8NU<g}4yb1rrs.36w1w1;i8I5GdM0>z7g1]i8I5CtM0>z7g2]i8I5yJM.cp0a,8yMl_T<ict0c:18yMlMT<NA0F>yb1mns.2bfg_k0,8NU0>2}8n_uhUNM4y1N4w40,rnk5sglR1nA5vMMYvg02bfubj.2W.g0>ydt2h0W7LS/Z8xs1_VKLc3NZ.81U?0fx2b@/_F1LX/V18NQgA4><18zjSHFM.W1LT/Z8xs1Q7z7SKwE<18ysvER_r/Qy5M7Uai8B491zH30Yv>z7h2go,<b@_;W7nT/Z8xs0fzAM80,czjh0is7K0z7_W5TT/Z8ysd8xs0fzH480,8yMmGQ<i8IEi8JZ>y5_M@4Dg80>kNV0Yvw:3EW_j/Qybvgx8wYk8joRA1058xvZRWrQ0o<j3Dz3UZH0w.i8QZ2qs.exLZL/i8D3i8n03Uj31M.w3xc3Uka0w.w7w1cw@5.8.81U0w0fxvo10,8yNQnSM.i8J490x8yocE?.i8J49118NUcM?<g<4y9wO,0,8yQgA64O9IR,0,8yocU?.yMgAicu3g>}18NUdo?}cq3o><23@>fzA080,8NQgA2f//Zdzmk8w@w2ics49f//ZdzmP544O9Vkybng2W3w<4yddluC0,8yt_Emff/Un03UiU?.KwI<18zjlaFw.i8DvW3PP/@5M0@4p0k.bEa;i8QReGo0>y9T@wwY/_xs0fx7w5.2W3;4yddiCC0,8yt_E1ff/Un03Uik1g.KwA<18zjkqFw.i8DvWezO/@5M0@4G0k.bE8;i8QR2ao0>y9T@zcYL/xs0fx3g6.2W3;4yddvmB0,8yt_EIfb/Un03Ui81w.KwA<18zjnCFg.i8DvW9jO/@5M0@4l0k.bE8;i8QRRak0>y9T@xUYL/xs0fx307.2W2;4ydds6B0,8yt_Enfb/Un03UgK1M.KwE<18zjmKFg.i8DvW43O/@5M0@4Jwo.bE8;i8QRDqk0>y9T@wAYL/xs0fxhA70,8yMkZSg.icu0m>}3FBg;Yvh<i8QRWag0>y9TQC9XKyuY/_xs0fxf3Z/@W2w<37Si8DvWdvO/YNQAy5M4wfit19ytrFQfT/Sof7Qg0>MFUQy9S4z1U0h8atx8Mvw4i8Q4g4z1W098ysnFtfT/MYvw]NZAyduMWW2w<eyEY/_i8n0vxd8yNmAS<i8C2a><Yvh<i8f524AVXg@5Y_T/Qyb12h8yNS0S<i8n03UiD1<3UB11<i8dY90w03UUR1<NEdw?<kObt2g8j8CPc>.37Jj8CPe>0>O9IQw10,CbwYvx}ioIY9bE9;i8QRwqg.ezXYf/xs0fBc19wYg82sldeulRSQ24Xnkbicu3m>.f//Z8yUIw?.i8Kja>.cq3ow4<4fJEdw?.i3Dh3Vi3og4.8j03UjQ0M.icu32><4;N_XU120w0W9rP/YN_XU120w0yglpPM.W8jP/YN_XU020w0ygl3PM.W7bP/YN_XU120w0ygkJPM.W63P/YN_XU020w0ygknPM.W4XP/Z8zjQvPM.ygk1PM.W9PN/@5M0@8l08.8IZ1IY.bE02<Lwg;NMezdYL/yPTPPw.Kw08<NMbU4;WbrO/@bftze.2W?<370Lw8<3ED_b/UIZNsU.bE1;cs2@0w<ey8YL/yPSKPw.Kw0>.NMbU71<W77O/@b3oLe.2@8;370i8Qleac0>ydv2gwW9fM/YNQAydt2gwi8QZ8Wc.eygYv/yMRmPw.Ly:NM4yd5guz0,8znMA8exyYf/ct98zngA84ydfg6z.3En_7/UId8sU.bUw;cs18zhnmEw.i8RY923Ecv3/P7ii8RQ9218zjTuEw.W2XN/@b3uPd.2@8;370i8QlFq80>ydv2gwW03M/YNQAydt2gwi8QZMW8.ezZYf/yMSTPg.Ly:NM4yd5niy0,8znMA8ezfX/_ct98zngA84ydfquy.3EPf3/QS5_M@4C_D/QO9_@xXXL/ioD4i8n03Ugk0M.ZA0E10@40wc0>yb1srl0,8yXwE?.ic7D0KzeX/_ioD5i8I5Hdk0>y3K2w1;3UX60w.ctJ8zmMAgeJa3NZ40,1ykit08D1i8QlVq4.370Ly;18yu_Ee@/_Qy9Tz79i8DGj8DDi8f30uz7XL/i8I5mdk0>wVC2w1<fzDc20,8zjQ3Ew.WcvR/@5M7CHxtJQ84xzSQO9XkCdn9Q03NZ.8JZ>y3NgjEhe/_QwVWTnLj8DLWcvK/Yf7U]K><3FIfz/Sof7Qg.37Si8RX2XEa;We3L/Z8xs0fzAvY/Z8yNnoR<i8C28>.eAQ_f/3NZ.37Si8RX2HEa;Wb3L/Z8xs0fzxvY/ZyYLQ8vc18yMmyR<NvB_w2,.3F_vL/MYvh<cvp8znIcKwE<3Eue/_Qy5M0@eT_L/Qyb5n3k0,8yo8U?.WsPX/Yf7Q.cvp8znI9KwE<3Eie/_Qy5M0@eH_L/Qyb5k3k0,8yo8M?.WpPX/Yf7Q.i8K38>0>ObIP,0,8ykgA44ybwOw10,8ykgA24ybwPw10,8ykgA64ybj2g8NEdw?<4wVj2gg3Vi3og40>MXt2go3Vi3ow40>O9IMw1.3F2_P/MYvh<NEdw?<ky3v2g8.@epfL/@Bq@/_i8RX2bEa;cvrEweT/Qy912h8xs0fzwfX/ZyYLQ8vc18yMmeQM.NvB_w3,.3FWvH/Sof7Ug]4AVXAMfh_nFjLz/MYvg02_Mw<ewmX/_i8n03U@xZ/_grU<o0WpXT/ZCA37Si8RX3bEa;W33K/Z8xs0fzFvW/ZyYLQ8vc18yMkyQM.NvF_w4w1.3FvvH/MYvh<WcfH/@beewIX/_i8QZAFU0>y9Nz70WdLH/_FVLT/Sof7Qg.bQ0,w0WoLT/ZC3NZ40,cyu_EyeP/@BXZL/j8D_W6LJ/Zcyv_EE@P/QC9N4y5M0@5ULP/@Cy_v/i8IdEZ80>yduMGW2w<37Si8Bc913EpKP/Qybj2ggi8C1m>.eDB@v/3NZ40,1Lw4<3FqfX/MYvh<i8RX2bEa;cvrEceP/Qy9h2g8WrrV/@W2w<4yduMwNZKwmXf/i8IldZ80>y9wA,.3FA_D/XE6;i8QRspU0>y9T@zLWL/xs1R2kOduMrFsLD/U0XbkMfhvLFpLD/Sof7Qg.8f_?@ehMQ0>5nKwE<11lA5lglhli8DRkUDXi87Im>0>ybvwwNZKz1Xf/ykgA78fX0w@55Mk.cq49eg:NUgAR;f//Z8yMmyQg.ics5zZ4}18NMlYQg}4ybC3,0,8ylMAe4ybC3w10,8ypMAW;4ybC2,0,8ylMAk4ybC2w10,8ypMAM;4ybC5,0,8ylMAm4ybC4,0,8ylMAo4ybC5w10,8ypMAS:@SC6,.28D2ji;3Xqoow4.8ys9e4;fJFxx?.W9_M/@@<w>z1W0d81v/7M189g.UfZ8ysuU:AwVNQwfh_yU<w>wVNQwfgYt8zrMA@;4y9MAy9h2gMWdHI/ZcyXMA@;8n03Ul16M.yTMA7bE1;cvpczrgA4>.eyiXf/j8DSLMo<1cyngAg4y9h2g8WbLF/@U0M<cjy@_uk91w10,8Kc_Tk@eBCYgwifvyi6Cc91,0,?wY0ic7G14yd1158ykgAs4yb1kvg0,8NU<g}4yb1jng0,8NM]i8I59Z<4z7g3]i8I56d<4ybj2hgi8B824y5OngewbMAV]fxjoh0,8wTMAm,dyvQfJEgAQw<cq498w:3Vm49e;24SQO9@M@kx2jy;2EgAUg<8y49dc<18yQgA24z7x2iM=4y9h2h8ict492w:ict497w:icu498+icu499+icu499w=ict496w:NUgAz=37h2gg]@kx2jz;hj7AijDtgg@jNz79h0GQ98w;fxmws.20L2ji]@4Uw<4ybh2hwi8RM_QwXt2gE3Ubc2w.h0@Sl2ggioDri8J493xdauJ1w@81gofO0kAVMM@3Cw80>S5SM@4sg80>ybdube.23v2gg?@4fME.8J668n0t2x8wXMAS]fx2Aa0,@5Qy3L2iM]@5O18<Yvx}i8JY90xcyux8ysRcavxczjgUyTMA737ij8DSW83G/Z8yRgAc8JY91NcyvXEP@z/Qy5M0@eSwE0>O9t2g8i8DFioQs1QS9_st491]hj7SwbMAQw:fxhX/_Z8yQgAe4wVMg@3m0w0>wFO4C9M4ybh2hwi8RM_Qy5M0@55w40>i8J2i8;ijDt3Udi7M.icv6//_Q6@2;4MHt2h8j0dQ90xcynMA84y9z2iw;joDTcuRdysp8yrgAG;4gfJGgAU;eIF3N@4]18wY,i8f50kC9NkC3NMxcevkfwW070,8etwfwVs70,8ytG@2w<4O9XQMFWKzsV/_i8n03Uiz2<i8nJ3Vn2h23ytbx8yTMA84y3M058ysp8avVc0vV8engAm7ezi8Kc9a;180mMAa469R4C9_QybJ2iE;i07FijDtgg@iNCoK3N@4]18eTgAa7dyi8n93Uml2M.hojSt7j7h2gg?<4y3v2gU.@4J0w0>Obh2gUi8J49618aQgAa4AVM4MfhY18xs0fxn080,9etR4ybgAy;ct491,;gg@iNAkNV4wXt2gEsFUfJAgA48fw0oD2w_81ggDmi8n93Un32g.csB5xfpRhQy9j2ggWn830,8yTQgKwE;NZKydV/_yogAR;fvgMuwvyogAV;eDk@L/3NZ40,9etR13Vb6hgzm3Ugw2<wTMA4>fx2vZ/_FIfT/QC9MQCdh0k0icu49b+i8IRfsM0>y9x2iw;i3Do3Va498w<18yQgA24QF_kO9n2gwioRI1g15ytlc0tTHgMYvx}i8JS84yb1vnb0,8yNnCOM.i8D1i2DNi87V/Yf.@6SM<4wVMD8CLSg<3Ejez/QybdsTb<fJAoExc1RLkybdKKY3N@4]18yMmNOM.i8Jg24yb5pXb0,8yp<g.i8I5AcI0>y91o7b0,8yMmaOM.yQ0oxs1QFkybt2h0yPQwMM.Kww<18NUgA4><4<3EGKj/Qy3@fYfxnH/_Z4yNlpOM.honi3UhG//WfLz/@beexAV/_j8Q5c9w.bB20w.i8Ql5pw0>C9Mkyb1pv<18zjloDg.i8IUcs3EFKn/@AH//A4y9Mky3M05cyRMA84m9WAy9NQybdu_a.21Uv/3M21V/_3M18wTMAe>fx4Y50,1Kg4<1cyQgAi6p4yoNe,<4y9HfU>2.ig@WW3Zcyoje,0w>y91p_a0,8es8fwAo50,8yQgAk4gaB2i8;h8yQ98w<1c0lMAi4ybr2hMi8C49aw<18yUgAC;4y3h2gE0kObH2iw;i8C49cw<18yUgAA;4i8l2gwi8C49bw<18wQgAq058yQMAq4y3h2hU0kibtxx8yXMAw;4Obh2hgiER41Mp8QuZ8Qux5xvp83Qj7i8C498;20L2jj:7l1Kwg<1azgi5:4wVQ4wfgIabB2ic;xt8fxtc40,8es6U:4wfgI58ykgAq0@jM0@SM8C498M<18yTgAgbY6;Wery/@U0M<cjy@_uk91w10,8Kc_Tk@eBCYgwifvyi6Cc91,0,?wY0ic7G14yd1158ykgAs4wFW4wZy1c<@74w80>ybv2hgi3BY97wfwM820,8ymMAs81Y92.3UnZ@v/wbMAQw:fxvg40,8NQgA4:18ySMA44O9XQAVTn8fWOIf7Q.i8RU0kwVTTcpi8DqLwE<18wYk1i2DWW4Lz/Z8xs1RTAy9r2ggj8I5UIw0>yb3uf80,cyst9eswfwFYa.2bx2jk;xs0fyvAk0,cySMAi4y9frP80,caSMA24MXr2gM3UdX5g.jg7Zict495w1;i8J493x8xs1QbAy3@fRTa4y3M08NQLd83XTgK44;FQbE_;i9zPi0@ZM2D2i6f2i8B495x8yMlFO<i8BUc4y3v2gg.@44gg0>ybh2gUct95cuh8ZTgAm4y9h2hwpF1CpyUf7Ug]4ybv2ggi8Jc93wNQAy9_Ay9O4MFVAwfHYp8Z_t8eQMAm0@3WgY0>y5MbY1;i0Z5@4y9t2hghj7Si8BY923Hdmof7Qg0>y9SAMFWHUa;j8DLW2ny/Z8xs0fxaMc0,9wYo1j8RE0kMXt2gw3UfF3<iUQId4wXr2gg3UfW3<ijDtsHRdyuCbv2gsct9davBc0QMA24O9PAO9j2gEW8vz/Z8yRgAc8JY91NcyvXERK7/Qy5M0@eLgM0>Obj2gEi8D2ioQs1QS9_kO9j2g8Wnb/_Yf7Q.i8IRkss0>ybhx18yTMAk4y9x2ig;i8I5ass0>y9x2io;i3KY9c:fwZI<20L2jy]@4Pg<4yb5E2Y9e4:3UiB;i8I5Zso0>wFQ4wVNM@3Pw<bA1;honS3Un:i05c9518yXgAM;4ybv2hgi8DMi2K49aw<18evV83Qb@i0Z2O4y9v2hgi8n9t6C0L2jA:7hvi8JY9418zhlCAM.LA:NMexnUf/i8JQ942bL2jk;i6fgWcfv/Z8w_z_3UhS5g.i8I5qIo0>ybj2hgi8B82eIAi8K499;18aUgAK:@5kMA.918yUgAG;4y9h2hgwXMAz:9R3E2Y9ec:3Uls2<ict497w:Ws3Y/Yf7Qg0>ybz2iw;i05I92xcyTMA84ybJ2iE;i07Fi3Dogg@iNAkNVeCI@f/3NZ0>ybh2hwi8n03UlP?.icv6//_Qm4V0@5Txo.8J49114ybgAy;8D2w@,w@81i8fO0kC9Q4AVTg@3Tw<8j03UieZ/_Wt4<1C3N@4]11Lg4<1Ch8CIjw?0,8yqP@,0w>y3v2h8.@9J_H/QObh2h8WqnW/Yf7M18yQU8yTUoxvYfxaU20,8yMkWNg.i8C60>0>yb1iP50,8ygktNg.i8I59Ik.8J068n03Umg2<i8IR5ck.eBN@L/3N@]8eY98M;13Uhn4g.NUgAz:8<3FbvL/Sqgi8Kc9a;1cyTMA84ybJ2iE;wTMA4>fx8If0,80mMAa4w1WkAVTk4fAIp5cujFuvv/Sof7Ug]bw1;MSoK3N@4]18ypMAE;cq498w:WlDU/Yf7M1dxs0fBc11wfM1t0y4M0@5GLX/Qi8J2i8;Wrz@/Z8zn3_i8J49615cs18aQgAaeBgZ/_A4O9WAMF@Aw3l2g8i8I5bIg0>yb3i_40,83XHGfQy9NAy3M061VL/3M18ygkeN<i8CkYg?8,8yo4.g.i8I50cg.cp0ag58yMnRMM.yQ0oxs0fxg4e.2bx2jk;xs0fyqI40,8yTgAg8IZtbI.bE8;icu491,<_gwY0W0bt/Z8w_z_3UhW3g.j8D_W53s/Z8wsho?.cs1rnk5sglR1nA5vMP70cta@0w<4z7x2g6?}6q9x2ge?.yMkhKM.yogA0>.bw1;pEC49?1.2b1veW.29x2g8?.K><1CyogA3>0>ydx2g.g.i8D7i8B4923ExJX/Un0vwXSx2ge?<g@5SMs0>yb1hn3<fJE0o?.xc0fxfMd.37h2gg?<4y9WkkNZKCZY/_i8IRXc8.8Jm64wXj2gUgg@jM449M4k8U0@5xho.8nit2h8yWMAS;4y5Xg@4314.7Uhj8KA9b;1dxugfxoMg0,5xfofxfjR/Z5cujFY_f/Qy5OrY1;ioD0i0Z5@kyb3AOd3bQ:iiD8ioQcekw1OkAVO0@3DMg0>yd33Zces5P84y9MkDhW4wFQkMVMkAfhYx9yvx9asx90s18esZ93Qb0i3D23UeuZ/_i8C60>0>y91hX20,8yMkDMw.yQ0oxs0fx07Z/Z8yTgAg8IZKrA.bE8;h8yk9aw<1cylMA84z7x2gg?<g<ewSS/_j8Js92143Xqk9aw<18w_z_3UmX_f/h8I5RY40>m5M0@4G_P/@xVSL/yPzEUJT/QOd1qWe.2Vlg80>C9Mkyb1hOT0,8yPzFz0k0>C9TkkNZAkNV4ybdoP1.2bhxx8yQgAk4i8t2gwNQgA4><18yTMAi4y9x2iE;i8K499w<18ySMAs4y9x2j8;i8K499;18yogAK;4O9W4y9j2hMioD@j2DUi0d490x8ykgAieI@3NY0i8JS84yb1hn10,8yNk6Mg.i8D1i2DNi87V/Yf.@6SM<4wVMD8CLSg<3ErdT/QybduT;fJAoExc1RLkybdKKY3N@4]18yMnhM<i8Jg24yb5rX<18yp<g.i8I5Ic<4y91q7<18yMmGM<yQ0oxs1QFkybt2h0yPR0K<Kww<18NUgA4><4<3EOJD/Qy3@fYfxnH/_@bfnH<25_M@4rf/_@wtSv/yPzExJP/QOd1lad.2Vgw80>yd5jud0,9ys58yMmVJg.i8QRuF80>ybe370Wczq/_Fbv/_MYv>C9M4y3M058yQMAs4O9ZQC9Mkybdg_<11wu3/MY?o7x/Yf>wXj2gU3Uh20M.pAa9z4o><i8Jc94x83XHLfQG9zcU>2.iECYNw?8,8ygn4LM.icu49b+i3D23UdPZv/i8Je28J@68n_3Uj@3<i8I5CrY0>y9xw,0,8yMmbLM.i8A5vbY0>yb1om_.2bg1y5M0@4dgQ0>ybt2h0yPQnJM.Kww<18NUgA4><4<3EEtz/Qy3@fYfxd8h0,8NUgAI=18yPkYLM.WvfQ/Yf7U]Kw8<18zjkRz<ysvEptz/Qy3@fYfxjzX/@b3hm_.25Og@4aLL/@yUR/_yPzE8tL/QOd1gqc.2V7wg0>yd5tab0,9ys58yMlkJ<i8QR5p40>ybe370W6fp/_FW_H/Qyd5oGb.2@g;4O9ZP70W7zo/Z8yTgAg8KY9dg<18oZ3EVdv/Qy3@fYfxprK/@b5pi@.25Qw@4yeX/@wTR/_yPzEEdH/QOd1k6b.2VGw80>yd5l6b0,9ys58yMnjIM.i8QRB9<4ybe370Webo/_FiuX/MYvh<i8IRerU0>ybl2ggj8D0pwYvx}ioD1i8f.k61Uv/3M163Xucjw?0,c0sF8es5RUkibD2jk;i8Bk9115xtIfyica0,8KL////Z_i8DU9v/3M188Vj6,0w>y9l2h8Wv_Q/ZcaszFwLL/Qybds2Z.2W?<4yb3Ayb1q6Z0,8asxU9j7ii8KY9ew<18ZTgAk4wV@4wfhYt8ys98xs2U?<4wfhd18elgAe0@2T0Q0>wXl2gU3UcU2M.i8K49aw<18NQgAu:37x2ic:w<4y3M0d8eogAw:@2XLf/Qybh2gUi8QY4bw1;id7Li0Z5NQy9h2gUi8D2ifvqi8I55bQ0>y9xx,0,8yMkeLg.i8Cg2>0>z7x2i+eCxY/_i8KQ99w<18aXgAO;4wV@78jct98Z_sNQAy9Mky9Y4zTYky9NAybh2hgi3DM3UdUZL/i8R80kzhWuDhZv/3Xtc93xCgECchw?0,8yQMAi4G9zcU>2.jonS3UCZ_f/Wr3Y/Z8yTgAg8IZabg.bE8;h8yk9aw<1cylMA84z7x2gg?<g<eyBRv/j8Js92143Xqk9aw<18w_z_3UkGZ/_h8IdhHM0>m5Og@46Lv/@zERf/yPzEktz/QOd1hS9.2Vgw80>C9Mkyb1oKN0,8yPx8zhnRy<i8QRgEU.370W9fm/ZcyRMA84gfJFgAG;eDdZL/i8JQ942_1w<4y9z2iw;h8yk98w<1cylMA8ezYRf/K0c<34ULLTB2go?.ibzfZRfzFpL484zTUAObn2gwh0@SB2i8;i6CQ91,0,?wY0i8Kc9a;18MuE4i07mi2KQ9b;18eXgAS:@2MuP/Qy9D2iw;i8IRmHI.cq498w:icu49b+WhvL/Z8yMkWKM.NE0o?<uAi@f/pwYvh<i8J490xcyuCbv2gsct9cavBcziM1j8DKW0fn/Z8yRgAc8JY91NcyvXEkJn/Qy5M0@eAwk0>O9r2g8ioQs1QS9_kMXt2gw3U8pY/_pF1cyuxcavx80QgA24y9h2gwjonStnR8yRgA8eBYZL/A4O9W4ybv2gwi8JQ951cavx80QgA24y9h2gwijD@sN18eSMA47c9ijDt3Ucp1<jonStjXHLSoK3N@4]18yR0wi8I5prE0>wFQ4wZ/Yf07pKi8I5mXE.8J068n03UkE?.LSg<3ELJr/Qyb1j@W<fJB0Exd9RLQyb4eK@pyUf7Ug]4ybs218yMklKw.i8Il1HE0>y9MkwFYky1@v/3M0fxBI10,8es9O9HZA;W6Pm/Z8yMnJKg.3Xpga8jitrR8yP3HL0Yvx}i8I5QrA0>ybk0x8yNm@Kg.i8Cg0>0>yb1r2V0,8ygmxKg.i8I5GHA.8J068n0tal8yTgAg8IZgb4.bE8;icu491,<1;WcHi/Z8w_z_3UlW//h8IdurA0>m5Og@4qL/_@wrQL/yPzExdn/QOd1l26.2Vgw80>yd5jm60,9ys58yMmTHw.i8QRu8I0>ybe370Wcrj/_Fa//V18yTgAg8IZNr<bE8;icu491,<1;W4_i/Z8w_z_3UmJ_L/h8Il_Hw0>m5Qw@4DvX/@ywQv/yPzE2tn/QOd1tm5.2V3gg0>yd5rG50,9ys58yMkYHw.i8QR_oE0>ybe370W4Lj/_FnLX/Sof7Qg0>ybv2h8i8D6j8Js9218yvB83XHFfQMXt2gUi0Z4PQy3M061VL/3M18yst8yglKK<ioD8i8Idrbw.87D/Yf06p4yrhN,<4O9DfA>2.j8C4Yg?8,8es9Oi4Q1Z4MXp2gg3UdT_v/i8J49218ykgAieDPX/_3NY0i8JY96182ssfxdbP/Z8yQMAo4wVO4wfgI58ysvF0v3/Sof7Qg0>ybugybshy5Zw@4Gg<4yb1uaT0,8yo4.g.i8I5Rbs0>y91smT0,8yMneJM.yQ0oxs0fx7L/_Z8yTgAg8IZoaY.bE8;icu491,<1;WeHg/Z8w_z_3Ulg//h8I5Crs0>m5M0@4gf/_@wXQf/yPzEFdf/QOd1n24.2Vgw80>yd5lm40,9ys58yMnnH<i8QRC8A0>ybe370Werh/_F0v/_V18xv@@?<4C9M4wfhfV8yP5czgOZ:4AFY4Cdd3B80vp9ev0fwHc<1casx8es8fwYv@/Z8yo4.g.i8A5Yro0>yb1vGS.2bg1y5M0@4F_X/Qybt2h0yPScHw.Kww<18NUgA4><4<3E5J3/Qy3@fYfxnP@/@bfsqS.25_M@4rLX/@xFP/_yPzEQJb/QOd1pW3.2Vlg80>yd5oe30,9ys58yMk5H<i8QRNEw0>ybe370W1jh/_Fb_X/MYvw:19yvrF8LP/Qydd3ZcesofwQf/_Z8ysp9Qux8atpcesp93QvMioDUiiDMig70i3DTigZ2MeAu//yNkUJw.xt8fx7zO/_ESYX/UIUW4ji/Zczgl3wM.KhY40,8zhnRww.ioD1i8I5tWI0>yddjy80,8yPwNMey6Qf/WjDO/Z8yTgAg8IZxGQ.bE8;icu491,<1;W13f/Z8w_z_3UnkYv/yPn0Jg.xvofxcrN/_EoYX/UIUWcPh/Zczgmoww.KhQ40,8zhlZww.ioD1i8I5_WE0>ydds270,8yPwNMeweQf/WovN/Z8yTMAcex_Qf/ioD7WqTA/Z8ytx8yTMA84ybt2hgioDtj2DUi0d490x8ykgA8eCv@L/i8J492x8zkMd0kydh0k1i8B492x8esofwQg20,8xsAfxnLP/Z8ykMA44C9TuDnW/_i8I50Xk.8J864yb5v6Q0,8ehnyJ<yoMAy:@2qMg.8J068n03Un21<i8eY9dw:3Uwb0w.h8Ks98w<15xtIfxfE10,8wXMAI]fx6g30,8yTgAgbY6;Wdjd/ZcyVgAS;4ybB2go?.cvpdxt9QmQyVP_tjUWmrN218MuE3i6CY91,0,?wY0i8Dgifvxic7G14w1@AybL2iM;i8Dgi2DUj3DgsO59ata@p;4Cd13F8foua?1T3kz1W0d8Z@58MuE4ytp8yTMA88DOLw8<3Ess/_Un03UUt?.ZEgA1w4<4fxpg2.3Sx2ge?<g@4?40>yb1uWP0,8yuD6w1w1<1NQgA4><3FTf3/Qybdt2P0,8yQo8i3K49c:fwxo30,8ysFcyst8etsfwZ_G/Z8yPmEIM.Wr3R/Z8ekgAq0@2S@D/Qybx2jE;id5A93x8yQMAe4wVMkwfgYyU0w;Z2x2ic;i8Bc93x8ZZC9x2ic;i8I5lbc0>y9xx,0,8yMleIM.i8C82>0>z7h2hE:eBYWv/j8JQ94ybv2gsct9dyvRcyvrE6Y/_Qybl2gMyTMA74O9_KxGPv/ct9cyngA24ybfviO0,8xs183Qz2ioQs1@B3WL/wTMA408fxoA3.37h2gg0w<eB6Vf/ioDthj7Shj7AWv_B/Z43XqQ98w<3Fmer/Qz7x2iM=bVA;Wo3@/Z8xsC_?<4Ob1AwfhcZ8ystcastczgOd:4Sd10Bd0s1cessfwCs30,casx8NUgAI=18es8fwO7E/Z8yoo.g.i8A5hX80>yb1l2O.2bg1y5M0@55gk0>ybdjWO.3FZuv/Qz7h2hU:cu498M;2;WsLE/Z8yTgAgbY6;i8Bc9214y8gAE;ewYO/_K0c<18yQMA8cjy@_uk91w10,8Kc_Tk@eBCYgwi6CQ91,0,?wY0h0@Sx2iw;ifvyic7G14yd11p8yPm_Ig.j2Dwi3DE3U87X/_i8J49514y7gA84m9N4ybv2h8i8JI9718yogAG;4ybx2io;i8C49cw<18yUgAA;4y9x2iU;WiHM/Z8yTgAg8IZ1aA.bE8;Wbbb/_Sx2ge?<g@4o_X/@Bi_v/i8JQ942_1w<exMOL/K0c<34ULLTB2go?.ibzfZRfzFpL484zTUAxFz2gg?.g48f>z1Wwh8zgghi8C49b;3FkfP/UIJ_r<8nJ3UhYWL/Wa39/@beew9Pv/j8Q5GDQ.bCf0M.i8QlKDQ0>C9Mkyb1jOC0,8zjnZww.i8IUcs3EiYL/@AZWL/pwYvh<i8ISi8Dai3DesNJ8yXMAM;4wFYkwV@kwfhYZ8eswfwJ,0,cysvFMLP/Qybs0y5Og@57w4.8J868n93Ukj?.i8nSKg4<18yPxcyMl1I<i0Z4Yky9QkwF@kOd3bk:ioQYckw1_QwV@g@2T>0>MFOAAVQ0@2uw8.8J068n03Uho_v/i8JQ942bfrmD.2W2;4z7x2gg?<g<ew_Ov/i8fU_M@54_L/UI5XWY.8n03Ug5@/_W9b8/@beezXO/_j8Q5NTM.bDu0w.i8QlH7M0>C9Mkyb1iWB0,8zjnLwg.i8IUcs3EfsH/@D6@L/i8Dhifvpi8I5yWY0>y9xx,0,8yMm5HM.i8C82>0>y9l2gUict497w:NUgAz:8<3F2@r/Yt491]i8DFWlnI/Z8yNl1HM.i8Cg0>0>yb1jeL0,8ygkAHM.i8I5bqY.8J068n03Uk1?.i8I56WY.eAN@L/j8Q42kAV@0@3z_P/QC9M4zhXQAFQ4AV@4MfhYt8ysZcast80stces583Qb7WmHY/YfJAgA48fw0ofM0kAVTg@iMwDgi8n93Uls0w.goD6hj7AWgvy/Z5cvp5cujFU@7/Qybv2h0i2D1LA:NM4yd5mtX0,8ysTEncz/Qybt2h0yXMAR;4xzQez8N/_i8fU_M@4Lw40>yb1m@K0,80SMAk4y9q0x8yNlnHw.i8IZiaU.eCr@L/i8QYdAwVPM@36LX/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWvnZ/Z8yTgAg8IZLGk.bE8;icu491,<1;W4z7/Z8w_z_3Unk_L/yMnUHg.xs0fxcr@/_ECYr/UIUW0ja/Zczgnguw.Kk820,8zhmRuw.ioD1i8I5dWc0>yddvx_0,8yPwNMex6Of/Wov@/Z8yp<g.i8AlyWQ0>yb1piJ.2bg1y5M0@5ig40>yb1oaJ.3FmLT/UIRvWQ.8nS3UgwXL/W2b6/@beeybOv/j8Q5lTE.bB20w.i8Qlf7E0>C9Mkyb1rWy0,8zjl_vM.i8IUcs3EPsv/@DxXv/i8JQ942bfsSA.2W2;4z7x2gg?<g<exnNL/i8fU_M@5JKT/UId1WQ.8n93UiEXv/WaH5/@beewjOv/j8Q5TTA.bBl0w.i8QlN7A0>C9Mkyb1kqy0,8zjk7vM.i8IUcs3Elsv/@BFXv/wPSVH:@4dvX/@xuNv/yPzENYz/QOd1mxV.2VNgc0>yd5nxV0,9ys58yMnWEg.i8QRKTU0>ybe370W0D7/_FZLT/QybdmmI0,5cs2blxx4ybgAy;469NKCs@L/hoDwWpjW/Yf7U]i8JQ942bftSz.2W2;4z7x2gg?<g<exDNv/i8D2i8I55qM0>y3@LYfxuzX/@3fgOI;3Ujr@/_Wb74/@beewqOf/j8Q5VDw.bBl0w.i8QlOTw0>C9Mkyb1kSx0,8zjkevw.i8IUcs3Encr/@AS_L/3N@]45nglp9ytp1lk5klld8w@MoynMA1bY<40i8BQ90zEHcn/QC9NQS5ZDh@hj7AWNof7U]W3f4/@3e0hRq4QVZ7dzi8J490xcyvabv2g4j8D@j2DyiEQc8bw<40i3D2i0Z7QezyNL/ioD5i8n0uc9QcAy9MQO9_mqgi8Dqi8DKLM4<3Escj/Qy5M7wbi2D3t2p80snHUp3EOYf/UcU17jmi8f464O9_RJtglN1nk5ugl_FEcf/QQ1XeBW//3N@4]23_M9_2Xw1;MMYvh<gluW2w<4kN_Q5mgll1l5m9_ld8yvd8wuME1<i8J@237SWav5/Z8yTIgKwE;NZEB490x9ysjEAcn/UB490O3_gdQ6kybuNx8zjnftM.hj7_W0j5/@5M44fBct8yMlLGw.i8n0t0j6g2w1K><14ymgA637rhj7Aict491]i8RI91xCykgA7bH//_Lw4<18yu_EyIn/Un0u6rSh2gu6njzj8RQ922bv2g8Kw>0,cyvrEqsj/Qy5M7gFulbELsb/UI0w_wbtbG3@0hR5KKP3N@]4O9VQSbp2ggW8L2/ZdxuhRXAy1N2w4<NM5JtglN1nk5ugl_3pF3EuYb/UcU17nrWnn/_@gic7E18n03UVE//w@w1ic7w14ydh?Mi8A49eIppF18escfwGs<19wYogj3IQ90@4fv/_QCb1AwVS7nxigdu24S5V7kDWOJC3NZ40,dySMA44O9VQCbn2g8j8BI913E@s7/QS5Xng9joDIijAs97jri8I5faA0>y5M7g4i8Bo84m5_M@5Dw<4y9SAyb1i2F0,8Kg3M///Z_wub/MY0i2ecQ.g8,QuEJY90MNQHU3;W7X2/ZcySgA4eBt//3NZ.bYo;Wfr2/Z8ys59yMp8yg59yRo8i072i8Bh24ydl2ggjonAtivHaSpCbwYvx}pCoK3N@4]19zlgA44Sbp2ggjonAt0p9eggAsKJcym4gi8Aaj8JA913FY_X/SoK3N@4]23_M9_2Xw1;MMYvh<gluW2w<45mhj7Sgll1l5lji8DPi87Ia?0>ybvwwNZAydr2gwj8RI933EbYf/QybuN2W2w<37SykgA2ewrM/_ict491w:ykgA30Yv0{}yTMA2bE,<i8DKW4_2/Z8xs0fzKo<18Muw4xs1@TERo_QC9X4z1UMhc0uLH5gYvw:19espOoQC3N119etNQKACb12hcev1RWkybv2gojgdQ90x8xvZR7eIvj8J_44ObtMxcynMA6ew@Mf/jon_t0xcyvZcejtQUkO9Yky1Ug3M/Z@IEJY90MNQHU3;Wfn0/_HE0Yv0bYo;W7r1/Z9yNgAi8Rc91x8ysp8yh19yQgA24w1Q4y9hwx8yQgA64y5M7kuWO4f7Q.pCoK3N@4]18zkwgi8J>4y5M7g5i3AgsKV8ykogi8ANWj//ZCA4y1N2w4<NM5JtglN1nk5ugl_3A{}w_Y2vMKU?<ccf7Qg.5mW2w<4y9Vk5nglp5cvp1lk5kkQy9YQy1X7y20,8yTU8cvrEFI7/QOboN18zjn2tw.ykgA74C9NQO9V@wsMv/i8RQ952_?<8D3W8L2/@5M7kiyQgAq2k0Y<fg2<113Vj6xtIfxfk20,8zkgAg4kNM4z7h2gM:4y9h2ggi8S49e;18ykgA86oK3N@4]18yTgA48JY91OW4;4O9h2gEW7z0/ZcyQgAa4y3@10fxoE20,cySMAc4MVh2h0t5S_6;4O9h2gEW0X0/ZcyQgAa4y9Mkybh2h0i8A1i8Jk94x80s9dxuR8yl48i8Rk931R5uIppwYvh<ioRl44Sbrh1dxuRQ1AAVhg1OXkO9qh18ygHFsv/_V1cyu6@0>.370j8B492x8zpMAs>0>yd5tBO0,8yt_EiH/_P7Scs18yt_EXI3/QObh2gExs0fym410,c0QgAi4S5XnkOWib/_ZCA4SbhgxdyTQgj8DLj8B492xcynMAcezCLv/jon_j8J492wfxfz@/ZdyvRdekk03UnH_L/j8Dxi8Qlq780>y9TP70Lw,.3EQHX/P7Si8Dvcs3EtI3/Q69NEn0u9Z8NQgAe:18yTgA88D7WeH0/@5M7kdi8Kc91,0,8xsB_6ki9Z@zNLL/i8DvW8CZ/_Fpf/_MYvg,8yQgAe4wVMnXti2D1i8Rk93x4yvq_?<ey1L/_i8n0u1N8yUMA4>0>ybh2gUi3D1vZjHHMYvx}W2KZ/@b08fU17jozl3Gw@bLt123@5wfBca3@0AfBc08MDi3i8JQ93wNQAi9Z@wZMf/WNwf7M18ys98zrgAs08.bY1;W7eZ/@W08<4ydJ2hM0w.h8DTW6W@/Z8xs1_QuAX//3NZ0>ybt2gwystcykgA24z7h2gU:8B492zEYH/_Qibl2gEj8J490y5M7khi8Kc91,0,8xsAfz@c<14yttcykgAaezCLv/i8DvW7WY/ZcyQgAaeB3_L/3NZ.exrLf/wPw4t59dxuRQ4F1cyuZdySQEW4iZ/ZdxuRRXQy1N7y2<NM5J1n45tglV1nRT33NY0K><14yrMAs>0>kNXkkNV4z7h2h]6q9x2hQ?.KL//@@?<4ydL2hM?.W8S@/@5M7y9ZEgAtw40,BQSQOdL2hM0w.yTMA7bE02w.j8D@W6qZ/Z8xs0fx6v/_Yfyjc1.3EIHL/UI0w_wbtau3@?fxkP//HD4ybh2gUi3D13UUf//i2D1h8Dmi8Rk93y_?<4O9h2g8h8Bk92zEEXT/Qibl2gEj8J490x8xs1U74ybz2gg?.i8J493x8es5_MeDa_L/3NZ40,4ylgA24O9h2gEW3CX/ZcyQgAa4ibl2g8yM23@0hQN8RgWEfyXTgkw_w93Vj2w_xo3Vj02c8fx8D@/Z8yTgAe4i9RP7ij8B490x4ylgAaewPLL/h8Jk92xcyQgA2eIM3N@]4y9MHY1;h8Bk90x8zrgAs080>O9h2gEW56X/Z4yRgA24Obh2gEh8DnKw2<1cykgA24ydJ2hM0w.h8Bk92zEebP/Qibl2gEj8J490x8xs1_GuA1_L/ibHdPcPcPcPcP4zTUAz1Wwm5Qw@ep_X/UR2_Qyd1818zoj4C080>y9h2ggjjAD3Ukd?.3NY0pCoK3N@4]19yTsoioJn846bvN18yrgAU;4m4Zw@4lg40>ydx2jw;i8DhyvW_?<4y9MAy9h2gwW3iY/Z9yQsogoJ_4bU3;i8D2igd784y1Uw3M/Z8at18ys7EHHH/QQ3pMxdxuRRtKJW3NY0ioJ564ybl2gwLM4<18yogAU;4Cbji11yTkgWdSX/Z9yQQogoJZ4bU3;i8Daigdd84y1Uw3M/Z8at7EmHH/QCbhixcyuZd0Sk8i8B492x8ykgAgexMKL/i8J492x8xs0fx4,0,9ysldemk0t8B9wYsEj3JY910fx4rZ/Zdeisfx07/_@_c;eynKL/Nc5@rMt8ys75_DY0ioJ784y9gi1dxuQfx0,0,9yNt8zkgAgeIt3NZ40,CpyUf7Ug]4CdhixdySQEjonJt0p9elk0sKRcymAEi8A8j8JI9435@7t9wYsEj3JY911RyuDa_f/W5DQ/Z9yQsogoJ_4bU3;i8D2igd784y1Uw3M/Z8at18ys7EsXD/QQ3pMxdxuRRruAY//3NZ40,9yTkoi8CQ9e;19yRkwgoJZ4ew7Zf/ioJd646bvh2@0M<4y9OAA3ji18wu80Yf/i2DhW2iV/Z9yQkEj8DLjgdB24y9h2gEi8B4943EeHD/Qybh2gEi8n0t0V9ysldemk0t9vFOvX/QkNXuD1_L/i8R4943F8//Uf_?@eRM80>5nKwE<11lA5lhj7Jglhli8DRkUDXi87IG>0>ybvwwNZKwuKL/goD4w_I33Uia0w.WaS@/Z8zjRAr<ic7E0QydCf/7M2U:Ay1UM.UfZ8esd83QvoK<8,8esd83QboW0uW/Z8xs1Q5XEa;cvp8ysvEMXD/Qy9Nky5M7Y5Lo;18znMAcexYKL/ict491:8xs1RdInVrMTDsw.ctb5@mW499w<34UDA_MsnVvI183WZ49518Z_mW;24wVQ4wfgZ18ylgA44ydJ2gg?.h8DLW6CW/@5M7knyUgAa>.2k0Y<fg2;fxdU10,1Kgk<19ytwNOki9Uz7Sh8DLW3qT/Z9yst8xs0fycE<2Z:46@:nkNpF1CpyUf7Ug]46V1g<4C9S379h8Dycvp4yu_E@br/QC9NQy5M0@eDg<8IZvFk.8n_3UDe;j07ZijDKsYp8zrMAE;ey9Kv/ys65M7ljNvBL3vJN0,8yTgA4cnVrEgA2>.cjyuj_1NvB@M4wfHUgAO;4wVY7cCi8I5xVQ0>y5M7gq3Xp0a8j03UkX1M.3NY0pCoK3N@4]19wso;1Wlj/_Yf7Q.W0KS/Z9ysq3e1ofx?6.2bftSk.25_TAlcs18wsiE?.mRR1n45tglV1nYegi8SQ9a;2W2;4z7x2iw:g<exiJL/WYJ8zrgAE;bE8;icu49a:1;W3aS/Z8w_z_3Uka//yNnyD<xt8fxfP@/_Exrn/UIUWeWU/ZczgkDrM.Khs60,8zhmvqg.ioD1i8I58p80>yddu9K0,8yPwNMewMJ/_WrT@/Yf7M18yTQgKwE;NZKxUJ/_goD5WlXZ/@U?<cdCbwYvx}i8Kk94,0,8zngAa4kN_P70ict492]ict490w;1i8AQ94y5Qw@eYfX/MYvg,CpyUf7Ug]4y9Qky9Tky9h2gEi2D1i3Dpi0Z6Wky5Xg@4uw40>kNZAC9W4ybd2h5csANOkQFY4i9UAi9X@zRJv/i8n03Uwc?.3UgO?.ig76ijDKsIZ8yQgA86of7Ug]4Q1ZUIZnVc0>M1Y4y9h2gwxvYfyjs10,8yVgAg>0>wVMw@el_X/QMVv2g83UdH//i8SI9a;18yu_EiXv/UD2xs1RhsnVrMSZrM.i8K49cw<35@mW490w1.34UDA_Msj1unX6ig@LNAwXh2ggsNt8yMl8CM.i8n0t0IfJA0Exc1RaMYv>y1h2g8:kybh2gwi8Kk94,.3FZvX/MYvh<wvEg9M.tdy_p;8Bk91zEuHv/Qy9X@z2JL/yRgA64ybx2j8;wY81ig@LNAwXh2ggsIzHFCof7Qg.eybI/_yM23@?fxeT@/@3@5YfBca3@2ofBc48ODkcw@3Xw_wi3UmG;i8J4921dxvofxtr@/Z8yVgAg>0>y9QkwFMky5Og@fzM<4kNZKCW_L/3N@]4ydJ2iw;Kww<18NUgAE:4<3EEHf/Qy3@fZQ34ybh2gwWpL@/ZCA8IZiFE.8n_teHEYrb/UIUW5GS/Zczgmjr<KtE50,8zhkbpM.ioD1i8I5zoY0>yddkVI0,8yPwNMeysJf/WWWU?<eCZ_f/i3D23UWE_f/i8R4921cyTgA24y912hdevUfwCw10,8yNgAi8Dph8DKh8DDWaWQ/Z8ysl8xs1UbDgSyPRmAg.xvYfyvo10,90uZ8yQgA84wVx2h.g.vXLFkfP/MYvw:3EgXb/UcU17jri8K494,0,8yRgA84O9t2g8i3D23UQA_f/i8RY92zECrf/Un03Uki_f/yTMAbbE0,.Lws4.3EPHj/Qydx2iw;i8B491x8yUgAg>0>wVh2gw3USr;i8JI90x8ylMA20Yvg,cevQfwys40,cyQgA28Jk92MNOki9XQybd2h1Kgk<3E@H7/Qy9MQy5M7Vvhj7S3NZ.{}ioDoyTMAa379cvpdav11Kgk<14yubENb7/Qy5M7U8ig76ijDusJubfkCg.25_M@9hMc0>ybh2gwjg7Ti3C494,<fzTf/_@bv2gEWaGO/@bv2gIWa6O/_FbvL/MYvg,8zqMAE;4y9X@wEJf/ysa5M0@5zw<cnVrMSmr<i8K49cw<35@mW490w1.34UDA_MsnVvI583W_1i3J4911Pokyb1iao0,8xs1Qlg@Sg2y4M7hdWMy1@x0D0,QgXZA;ylgA64y9j2g8W72Q/Z8yu_EKbf/UJk91x8yQMA24ybx2j8;wY81i0@LMkwXh2ggsHVC3N@4]19wso;1WujZ/Yf7Q.i8SQ9a;2W2;4z7x2iw:g<ezyIf/i8fU_M@5ULT/UIRAFs.8nS3Ujk_v/W3mM/@beeyuI/_j8Q5RSA.bDL1g.i8QljSg0>C9Mkyb1t6c0,8zjmiqg.i8IUcs3EUb7/@Cl_v/i8RY92zEsr7/Un03UwL_v/yTMAbbE0,.Lws4<NM37JWaaO/Z8zogAE;4z712g;1i8B490xCA{}yRgAb46V1g<4C9S379cvp4yu_EVW/_QC9NQy5M0@eifX/UJY92wNOj7SgrA5;ioD0h8DyWcaL/Z8xs0fzyr@/@bfkKe.25_M@9SM<4M1_kwVb2hPEAybv2g8W5yO/@5M7l4NvBL3sNG.35@mW490w1.34UDA_MsnVvI583W@c9cw<18eQMA47cqi8IdmVo0>y5Onge3Xp9a8j93UnS?.pF18wggA:uB3//h8AI94C9ZkO9t2g8Nc5VvIp8ylMA68DbWN5C3N@4]21@N0D0,QaXZA;wYc1W7KO/Z8zrMAE;ey@Iv/i8K49cw<193W_6j3DEsIR4yOMAj8JQ90x8yRMA6eBG@f/pyUf7Ug]4ybt2g8Kww<18NUgAE:4<3EZqX/Qy3@fYfxg3/_@b1qml.25M0@4YLX/Q6bfKyRIv/j8Q5XCs.bAO1w.i8QlpC80>C9Mkyb1uya0,8zjmFpM.i8IUcs3EZW/_@CT_L/i8JQ91yW2;4z7x2iw:g<ey7HL/i8fU_M@5BfP/UIddVk.8n93Ui6_f/WdGJ/@beex3Iv/j8Q5v6s.bAd1w.i8QlZ640>C9Mkyb1nqa0,8zjkTpM.i8IUcs3Exq/_@B7_f/i8JY91zEFH3/Q69NEn0tk75@mYd5SA0>ybx2j8;NvBKx2g8?.Ne9VfY75@nX3i0@LMQwXh2ggsNh8yMmzB<i8n0t0wfJA0Exc1R5ky1Ng;7Fu_L/Q61_x0D0,QWXZA;gof60uzHIf/i8JY91zEcr3/Qybx2j8;i0@LMQwXh2ggsIPHLAy9n2goNc5VvIu9M@I8wvIg9M.t2G_p;8f30uyFIf/i8JY90zEXW/_Qybx2j8;ig@LNQwXh2ggsIV8yRMA6eD2_v/pF23_Md_2Xw1;MMYvh<gluW2w<45mgll1l5lji8DPi87IS0,>ybvwwNZAOdH2jg;WciK/Z8yTIgcvqW2w<469NKyNHL/i8JX637SKwE<29h2goW9SK/Z8ysm9h2gsW36P/@9r2gEic7E0Yt492M1;i8So/Yv0bw;2i87z.3w_QwVMQwfhZyU<w>wVMQwfgJx8zkgAg4kNV4y9h2ggi07ri8JQ9114yvvEjG/_Un03Uw6?.j8JY9719ziMsijDL3Ua_;i8R49318ykgA24ydzg./@W<1>O9XAi9Z@yzHL/i8n0vCp8ysa@2w<4O9X@yuHL/i8n0t55caux8yTgA28JY91yW4;4ydH0k10f/j8BA9318yuxcau18ykgAeewbHf/i8fU47h0K><18wsjo0>0mRR1n45tglV1nYdC3NZ40,8yTgA28JY91yW4;4O9p2gMi8Bs93zEOWL/Qy3@11RM4C9X4ydb2J9euYfwQL/_Z8znMAabFA;Lw4<3EIqT/Un03UX@_L/yTMA7bE8;i8RQ933EBGP/@DC_L/A370WnD/_ZC3N@4]1jKM4<18w@Mwi8RQ91PEvaT/Qy9MAy3e,Q68JY91N8ysp8ykgA2ez2I/_i8Jk90y9MQy9R@yzG/_i8f488DomYdCpyUf7Ug]5eX?<4y3X218zngA7ewIHv/i8D2i8cU07goyTMA74y9NAy9h2g8Wba/_Z8yRgA28D3i8DnW5eH/Z8wYgwytxrMSpCbwYvx}kXI1;i8fI44ydt2gcWdOI/Z8wPw0t1l8yNlDAg.i8nit0v6wxw1<1ctJ8ysvE2qL/Qy3N129S5L3A5eX?<4y3X218zngA7eysHf/i8D2i8cU07goyTMA74y9NAy9h2g8W3bC/Z8yRgA28D3i8DnWceG/Z8wYgwytxrMSpCbwYvx}glt1lA5klrQ1;kQy1Xc;18zngA7ex2Hf/i8D3i8cU.@4xM4.8JI91O3_g4fzIw10,8yTw8KwE;NZA6Y//_@yyG/_ioD7w_Q23UmS?.i8QZ0lU.eyWG/_i8QZ15U0>y9NuyHG/_i8nJ3UgO?.i8n03UgF?.KwE;NZAy9XQy9h2g8W3mG/Z8yTMA2bEa;cvp8ykgA8ewvGL/i8B492x5xvYfzT410,5xugfzKw<18zjSVx<W9OG/Z8ysl4eW]3UmY?.wXwg:g@5Ug40>ydfoFt.3E8WL/Qy5M0@4Gw<bEa;cvp8ysvESWH/XE1;cvp4yut9ysvEOqL/Qy9Nky3@fYfx9w<18zjRdx<W32G/Z8yuF8zngAc4i9_YnVrQgA84i9p2h0NQgAh:35@nZ49318yU08;i2D2Ne7VrIz4U_4yMw6Wa;cnWvQgAieyTGf/i8fU_M@4Kg40>ydfuW3.3EQqD/Qy9G0w<1CbwYvx}cuR8yt_EZGz/Qy1Nc;29W5JtglN1nA5vMUIdbEY.8n9t2HERqv/UIUW3WH/Z8yNm7x<i8QRK640>ybeAy9Mz70W9eF/Yf7M2Z?<eKHpwYvx}i8JX4bEa;cvrEQaD/Q69NeAO_L/3N@4]18zngA8bEg;h8D_WfWD/Z8w_z_3UlP_L/yPmKzw.xvofx6n@/_Ekqv/UIUWbGG/Zczgkjog.Ku440,8zhlHmM.ioD1i8I5Xoc0>yddqVw0,8yPwNMezYGf/Wir@/Yf7U]h8DDi8RQ9314yq]W4OG/@5M7kgyQgAi2k0Y<fg2<1Qtsu54:8<18zngA8bEg;h8DDW5OD/Z8w_z_3Un2_L/yMkczw.xs0fxbj@/_EHWr/P7JyPzE5GH/QOd1utw.2V?k0>yd5stq0,9ys58yMl9wM.i8QR2C<4ybe370W5yE/_FtvX/Yu54:4<3FFvT/UIlHEQ.8ni3UgV_L/W56C/@beeyWGv/j8Q5qS<bDZ1<i8QlqRE0>C9Mkyb1uS20,8zjmKnM.i8IUcs3E_av/@DW_v/3N@]5eX?<4y3X218zngA7eyIGf/i8D2i8cU07goyTMA74y9NAy9h2g8W4bC/Z8yRgA28D3i8DnWdeC/Z8wYgwytxrMSpCbwYvx}kXI1;i8fI84ydt2gsW5OE/Z8ys98wPw0t1ybv2gsi8D6i8B490zEwKT/Qybl2g8ysd8ytvEwWr/Qy3N229S5L3pCoK3N@4]1lLg4<1ji8fI64ydt2g4W0KE/Z8ysd8wPw0t2S3v2g40nYXyPQFx<i8RQ90yW2;4z7h2g8?<eyZFv/i8fU_TgLcuR8yt_E7qr/Qy3N1y9W5JtMMYvg,8yTw8KwE;NZKx0F/_ysvHJMYvg02b1kac.25M7j7WeCA/YNXoIUW52E/ZczgmVmg.Kl460,8zhk1mg.ioD1i8I5wU40>yddkhu0,8yPwNMeyiFL/WUJjKM4<18w@Mwi8RQ91PEjav/Qy9MAy3e,Q68JY91N8ysp8ykgA2ez2Z/_i8Jk90y9MQy9R@xPFv/i8f488DomYdCpyUf7Ug]45nglp1lk5klleX?<4y3X5x8zngA9ezPFL/ioD7i8cU07g9ySMA98fZ1nYxj8D_W2CB/Z8wYhoytxrnk5sglR1nA5vMMYvx}i8JU2bEa;cvp1LL//_EeGr/QCbvN2W2w<37SykgA5ewCFL/ioJ_6bEa;cvq9h2ggW1aC/Z9yTYwKwE;NZED3W02C/Z9yTYEKwE;NZEB491zEXan/UB491O3_gofxgY2<f7Q.pCoK3N@4]15xvpU6Qydt2gUKw4<14yvvE6qn/Qy5M0@eQ>0>ydr2h0yTMA5bEg;i8DKWfGA/Z8w_wg3UmM?.i8J4940NZHE2;ytZ8ykgAaexUFL/j8J494ybv2ggytF5csB8zkMAc4ydt2gEi8B4933EpGj/Qy5M0@8Tg<8JY91x8zngAebE8;ict493w1;W86z/Z8w_z_t6Kbv2gsKx;18yuXEqGf/Qy3@fYfxk3/_@b1hGa.25M0@4cL/_@yZEL/yPzE9Gr/QOd1hZt.2V90s0>yd5ttm0,9ys58yMlpvM.i8QR6BM0>ybe370W6yA/_FY_X/MYv08IlOEA.8nit8LEsqb/UIUWdGB/ZczglmlM.Kic70,8zhmblw.ioD1i8I53nY0>yddsVr0,8yPwNMewsFf/WkP/_Yf7U]LM<g3ExGf/Qybt2h0yTMA437ii8B490zEkqn/XE2;cvq9T@x3Fv/i8Jk94x8xt9Qi4kNXmof7Qg0>MFWHw<40i8JQ90ybv2ggi3D2ioDkj0Z7U4O9UAQ1VuxGE/_i8JQ90xcyua9T@xbEL/i8Jk94x9etlOMkybv2g8Wauy/_FBvX/SqgctLFqfT/Sof7Ug]4CbvP2W2w<37SWc2z/Z1ysrFWfT/MYvx}kXI1;i8fI84ydt2gsW0OA/Z8ys98wPw0t1ybv2gsi8D6i8B490zE4K3/Qybl2g8ysd8ytvEcWb/Qy3N229S5L3pCoK3N@4]11lBmZ?<5d8w@MMi8RQ90PEKqf/Qy9MQy3e,QhodY90M1vDp8zjQ2lw.j8JM2eyVGf/xs1Uhkydr2ggys6@8;370i8DLi8Qlu5g.ezoEv/i8DKj8DTcuTEmWn/Qy9T@yPEv/i8f4c8DEmRR1nIcf7Ug]eyrEf/yPzE1aj/QydfqJl0,8ysoNMeyPEf/Lg4<3HMp1CpyUf7Ug]5d8w@Mwi8RQ91PE4qf/Qy9Mky3e,Qq8dY91M1vC58yTw8KwE;NZAy9h2g8ctLEuGb/XEf;LwA4.29NP70Wfuy/Z8yQMA28fU_Tgli8DfW1mx/Z8wYgwytxrMMYvh<yMlixM.xs1R7wYv0{}KM4<3HP6of7Ug]ezrD/_yPzEhaf/Qyb5oRY0,8zjlumw.i8IWi8D2cs3ECq7/Qybj2g8WY9CA45mlrQ1;kQy3X318zngA1ex9EL/i8D3i8cU.@4A;8JI90i3_g4fzHM<18znMA2ezREf/xs0fy8Q<2bv2gcKw0>02@1Mg.370W2yy/@bj2g8w_Q23Uij;i8RI9118zhnGkw.Ly:NM4y9X@x0Ef/i8JX24y9XKz4E/_yQMA3bUw;cs18yuZ8zhmWkw.W1Gw/Z8yTIgi8DKW9Wz/YNXky9T@zQD/_i8f4c8DEmRR1nIdC3N@4]3ESVX/UIUW4iy/Z8zjQ3l<i8D6cs3EYVX/XQ1;WY0f7Q.j8JP24ydr2ggLy:NM4yd5kNi0,8yu_EGp/_P79cvp8yuFcyvvE2G7/Qy5M7gRyQMA34yd5ili0,8yuYNMbUw;W7Kv/YNOky9WHU1;j8DTWdCw/Z8xs0fxlb/_@bv2g8Wbuv/@bv2gcWaWv/_FtL/_Sof7Ug]45nglp1lk5klrQ1;kQy3X2x8zngA5ez3Ef/i8D3i8cU07ggh8JA91h1w_M4vN@Z?<4y9T@zODL/i8f4a8DEmRR1n45tglV1nYegi8JU2bEa;cvrE4a3/QybuN2W2w<37SioD7WfSv/Z8yTIoKwE;NZA69NKzaDL/i8JX8bEa;cvp8ykgA6eyRDL/i8D5gofY1nhYi8JXa4yddsti.3Ej9/_XE0,.Lws40,4yvu5M0@kM0@SM8B490wNMewIEf/i8nJt315cuh9yuwNOk6V1g<4i9YAQFU4ydt2goh8D_W8qt/Z8xs1Ukng8ig74ijDIsJebh2g8xs0fxpI;NXuAq//3NZ.bE0,.Lws40,4yvsNMezcD/_NQgA2:18xuRRC37JWuX@/Yf7Ug]ezrDf/yPy3_MhQG8f_2TizyRgA28nitivEcG3/Qydfgti.2Z?<4y9Nz70WdOs/_FHvX/MYvw:14yvt8ykgA2ew3DL/i8Jk90ybeKL3pyUf7Ug]4i9ZP7JWeqt/_Ft_X/V1lLg4<1ji8fI64ydt2gcW0Kv/Z8ysd8wPw03UiH;i8IZzUc0>y5_TglLw?E03EO9X/Qz71nm3[yPQnuM.xvYfyiY1.2bfglX.25_M@9?4.8IZYTE.8n_3UDj;yPTxuw.xvYfyqk<2bfsZW.25_TBXyPTtuw.xvZVkkydfoxf<NXuz3Dv/i8QZykY.eyTDv/i8QZyQY.eyHDv/i8QZBkY.eyvDv/i8QZDAY.eyjDv/i8DvW9Ks/Z8wYgoyuxrnsdCAezXDf/yPS1uw.Wf2s/_71mVW.3//_WVcf7Q.WdKs/@bflRW.371jJW.3//_xvYfy7b//HMp3EKVP/UIZ9nE.cs57TE.f//@5_M@8if/_@L1AeyrDf/yPQ9uw.NMk3uw.//_Un_3Uwu//WY6gW7Ks/@bfuRV.371utV.3//_xvYfyf3@/_HMp3EmVP/UIZQnA.cs5OTA.f//@5_M@8MLX/@L1A5mZ?<5d8w@Moi8RQ90PEqVT/Qy9MQy3e,QhQydfodS.3EpFP/U2U5:1Qc4yb1tW10,8xs1Q4oJg68nit0HMwSwo?Yvh<i8QZkno.ewQDf/NE0k:37Ji8DvW6er/Z8wYgoyuxrnsdCbwYvx}lky9Vk5nglp1lk5kkXI1;i8fAM4y1Xc;18zngAlezpDf/ioD7i8cU.@4BgA0>ibp2hkgofY0w@exwA0>ybg0x8ykgA44CbhN18ykgA6463_0cfx4Af0,9yQsoi8B49318xs0fxbY90,83XUoxdIfxbc9.3EvFT/Qyb0fp4m>83Umw2g.NQgA9f//Z1w_M4t1h9yTYwKwE;NZKzyC/_ykgA94O9v2gEctJcziS8u<j8SA98:f7Ug]46bvg25_Twpi8RQ962W4;ew9C/_i8fU40@4zMA0>yb1q2<1cyU<g.i8IlAE<4ybeAMVNM@3hwA0>Obyww10,dxsAfy1Ua0,8zks1ijD03UfN2g.joD6iiD@joDTY4MfMjF8yMRkw<i8K10>0>Kd73t8etwfwQQ90,8yMQVw<3Xp9aoj93Uhl2w.j2DUi8n0vMsNS@Bm//joD@yTMA94yb3h2<18KL////Z_joDMj8JY92x8zrgAw;461Uf/3M3TRQC9OkEzBc4>2.joSo.840c7L7Qy9l2h8i8fU?@4TwU0>y9MQydJ2i:ioQk1AO9Y4kNV91CpyUf7Ug]4C9M4y3M051wu3/MY0hw@Tx44><jg74i3D2tu5dxugfBs0x@8x493x9Lv////Z_wub/MY0j2eIQg?8,caSMAif1d0m4gi8dY94w03UjD3g.i8Rc961cyQgAi4CVPsPcPcPcPcN8ysYf7Qg.{}j8D0i8f70kDTUkO9M4z1Wwdczhiijg7ij2DgwY0MiofU2kC9Q8x7_Tvmi3DV3Uc33M.ioDUi8DUiiD8ioRg_Qy3@zUfxxof0,dys59yvJ8yv9yYvR8rNkzkM.oL7Zi6Ydmlc0>C3Us1yYvR8rMmbkM.jiDb3N@4]$0e5yYCl80dxyYtR8WZJyYvR8vRH_j3Dottddes4fx7Y<18yvx4ysFcasxdysddasJdzlf_iofW7DoPj2DfoL5_a6Z7_Yjzvkr.sjyvg05m5c.cixvn@438;11ZIcvt3R9w@fwh07qj2Doi6fii07OpF1CpyUf7Ug]{}3XpU_Qy3W058wY81g8xW_QwVMnbHjmf0ig7MNvxTgso0>ybv2ggi8BQ943EbVL/Qydj2hwjonAi8JQ9419KcTcPcPcPcPci8Df3UgX3<3NZ.{}j8Dwi8f70kDTU4O9U4z1WwdczgOijg79j2D8wY0MiofY2kC9R8x7_Tvmi3DV3Uej3g.ioDUi8DUiiD8ioRg_Qy3@zUfxGEd0,dys59yvJ8yv9yYvR8rNmzkg.oL7Zi6YdSl40>C3Us1yYvR8rMkbkw.jiDb3N@4]$0e5yYCl80dxyYtR8WZJyYvR8vRH_ijD3ttddes4fx7Y<18yvx4ysFcasxdysddasJdzmf_iofY7DoPj2DfoL5_a6Z7_Yjzvkr.sjyvg05S54.cixvn@438;11ZIcvt3R9w@fwh07qj2Doi6fii07OpF1CpyUf7Ug]{}3XpU_Qy3W058wY81g8xW_QwVMnbHjmf0ig7MNvxTgso0>ybv2goi8BQ943EHVD/Qy3v2gM>ybt2h03UhP?.irzdPcPcPcPcP4ydj2hwi8DfjonJ3UiF2M.3NY0j8DEi8f70kDTU4O9W4z1WwdczgOijg79j2D8wY0MiofZ2kC9Rox7_Tvmi3DV3Udb3<ioDUi8DUiiD8ioRg_Qy3@zUfxzMc0,dys59yvJ8yv9yYvR8rNkzk<oL7Zi6Ydml<4C3Us1yYvR8rMmbk<jiDb3N@4]$0e5yYCl80dxyYtR8WZJyYvR8vRH_j3Dottddeswfx7Y<18yvx4ysFcasxdysddasJdzmf_iofY7DoPj2DfoL5_a6Z7_Yjzvkr.sjyvg05m5<cixvn@438;11ZIcvt3R9w@fwh07qj2Doi6fii07OpF1CpyUf7Ug]{}3XpU_Qy3W058wY81g8xW_QwVMnbHimf0i07MNvxTNw.i8JY9318yngAgewMCf/i8JQ9418LYTcPcPcPcPci8Rc9619ysBdxvofx2E9<f7Qg.{}j8DMiof10kzTVQO9Y4z1Wwdczgiijg70j2D0wY0Miof@2kC9RA68gvZTRkMVOg@3ywE0>O9PQO9O4wFPQydl_Z8w_E@3Uqb2w.ioDUjoDai8DOoL7Zi6YlEAU.6bN_kxL3txe0,9w@30oL7Zi6Y52AY0>QFMwYvw:$0e5yYCl8|05S4U.cixvn@418;11ZI8vt3V9w@bwh07ij2Dgi6fii07OpF1CpyUf7Ug]{}h0@SgfZ8w@w1i8f20ki8gLZ8es5OWAxz_Qw1ZYnUtYo7037ii8QZNQo0>y9t2h0W2Kk/Z8zkMAo4y5SQybt2h0irzdPcPcPcPcP4C9Og@4AMs.{}i8Doiof10kDTU4y9S4z1Wwd8zjOii07_i2DUwY0Mi8fX2ky9QQ68gvZTRkMVOg@36wA0>O9PQO9O4wFPQydl_Z8w_E@3Uov2g.ioDUjoDai8DOoL7Zi6Yl8AQ.6bN_kxL3lxd0,9w@30oL7Zi6Y5yAQ0>QFMwYvw:$0e5yYCl8|05m4Q.cixvn@418;11ZI8vt3V9w@bwh07ij2Dgi6fii07OpF1CpyUf7Ug]{}h0@SgfZ8w@w1i8f20ki8gLZ8es5OWAxz_Qw1ZYnUtYo7037ii8QZlAk.eyMAL/w7MAe,R6P7rj8D_W7@h/Z8zmnoytxrglN1nk5uglZtMQybt2h8yTMA937iW9Wj/Z8w_z_ts@b1q9T.25M7j5W4Cg/YNSUIUWb2j/Z8yNnVr<i8QRYAE0>ybeAy9Mz70W0mi/_HD0Yv>ybv2gMKwE;NZKxfAL/ict493]ykgA9eBvZL/3NZ4<fJA8Fxc0fxlM5.23@Sgfxec2.3PA8f30uBpZL/pwYvx}i8Id4ns0>Obv2hwj8JQ96x8yU4.g.iUQsdQwVS0@2I_r/Qy9SAO9YQS9_Ayb3udS.2bv2gAjoDMibz////_vQObv2gEgo7w/Yf>C9OkydJ2i:iye4Mg?803TRQSdC.21,8ykgAic7L7Qy3@M4fxaQ50,8xtIfxtnS/_6h2gU>kNVeA5Z/_pyUf7Ug]46_?<f1c3Y4Wi8IdpDo0>6@?<eA7ZL/3NY0i8Jic4O9O4zTS4y3Ww58yMR3tw.i3DW3Ucy0M.i8C12>0>6@?<4yb3ipS0,azggTijD0sMpdysp9avVdyvvMj0_1ekyb3gxS0,8yU4g?.j3DU3UeAZv/j8Daj8D8ifvqY4wfIp48?.i8IdTTk.eC6Zv/pF18yMnhtg.Y8d06058zjRlqw.W3yg/_6w1g;1A4yb1r5R0,8yUw.g.ijDfsRh8ysxcavx8ykgAg4MVY0@3Pg<4y9S46bvgiW4;4O9VAwFO4y9z2i:i8C498w<18ykMAi4O9p2gUWaye/Z8yQMAi4y3@10fxe420,8yMlatg.3Xp0aoj03UmS0w.hj7iKL//@@0w<4O9VUI5Q6M0>6X?<4z7x2i6=6p4ypgAzw<8C498;2b1qhI0,Ch8Cs98g<29x2i8;K><1CyogAz;ewSAf/pEeY98o:tlJCwXMAzw:fx0P/_Z8zjRdqg.W32f/@0K1g:3UnP?.jonS3UhZZf/j8DPi8IdC7g0>S9_AydJ2i:i8Bs941cyTMAaeB80M.pwYvh<yPQqr<i8RQ962W2;eyXzL/pEeY98U:3Uis_L/WUVCbwYvx}i8I5gng.f23g1w1i8QZNmw.eyEzL/NvDLMbE1;oL5_27@498o<1CypgAB;cq05:4NM6q9x2im;yMmBqM.yogAw;bw1;pEC498g<2b1otH.29x2i8;K><1CyogAz;46bhg29x2ig;WQ1CbwYvx}KL//@@0M<4O9V@z@zL/ZEgABw;5RdSq3L2i6]@5vg4.6q3L2ie:7kti8I5uTc0>ybw0,0,8yNlJsM.i8Iii3D2sWR8zjTKpM.Wd6d/@0K1g:3UgDY/_i8I5hnc0>y5M7gbyR0oxt8fxi030,8zjS@pM.Wa6d/YNSYq05:3Fk_b/MYv>y9@E7y/Yf.@TJ54><Kw4<1cyR48pEnSi0Z4Yz7iifvSKA;18et183Qv2joniKw4<1c3Qjij3Dgj0Z6Qbw1;joDmjonij0Z4YeCp_f/3N@]4yb3r5O0,8xsBQ2UJ168n03Uld?.i8QZaCs.ewdzv/NE0k:eDu_v/A4MF@rw:ioDej0Z8YeCM_v/3NZ.8IZ4CE0>ydt2hwKww<18NQgAo><3ECEL/Qy3@fYfxdw10,8zjThpw.Wbic/@0K1g:3UgA0w.i8Ida780>y5Og@4Rg<4Obt2h0WmD/_Yf7Qg.8IZICA0>ydt2hoKww<3EkUP/@Ch_L/pwYvh<NQgA9f//Z8NQgAc:3FZf3/Sqgj8JY92x8yMncsg.Y4y3q0w1KM8;fxePV/Z8yTMA64yddsk_.2X?<ezZzL/Wt7V/@Wc;6q9B2i:WqzV/@Vc;6q9z2i:WhrU/Z1K3;1Ch8C498;3F0Ln/Q6Vc;6p4yoMAw;eBKY/_Y8dF607FGvX/Yq05:1dyvV8yTgAe4Obv2gEjoDMyTMA94C9OkyU////_TZ1wu3/MY0iye4Mg?803TRQSdC.21,8ykgAi4ybh2h0MuYvi8fU0ngci8D3ioQk1KANYv/j8Kx2>0>ybgj18w@w1j8IdRn<4MVY0@2Gg<4S5V0@eE;4K3fdA03Uyl;ioR60rI1;irT////_vOn/MY0jieIMg?8,caSMAi4S5V0@lM27Uy4gAeeAyYv/LP;1CyrMAw;eC9Zv/yMlOs<xs0fx1H@/_E5oD/UIUW7Wc/ZczglDfw.Kpw40,8zhkLfg.ioD1i8I5Imk0>yddn920,8yPwNMez0yL/WtLZ/Z73XuAgg?.3Fnv//23q1w1WtrY/ZdyvV8yTgAe4Obv2gEi8IdZSY.eCY_L/ioDMWg3O/Z8yvvFuvr/QC9YeBMY/_i8DTWuDT/Z5cs0NQKDvZv/hj79ctbFlv7/QkNM37iWkLT/Z5csANQKD1YL/i8DMWrzQ/Z5csANQKALZf/kXI1;i8fI84ydt2gsWeOa/Z8ys98wPw0t0u3v2gs0Dgki8DnW2i9/Z8wYgwytxrMMYvg,8yRw8i8QRxPQ0>y9h2g8i8DvWd29/Z8yRgA28n03Uib;i8QRqzQ0>y9TQy9l2g8Wa@9/Z8yRgA28n0tll8ylgA24yb7h9L0,8zjSroM.W7W9/Z8yRgA282U5:1Qaky5STg7yQcoxs1Rjky9l2g8i8QZs6c.exjyv/i8Jk90z6w1g:Y4y3qMw1ctJ8ytvEtUz/Qy3N229S5L33N@]4yb1qBK.3Mi8d02>NS@LoY8dH6058yNSjrw.WWlC3N@4]11lQ5mlld8w@N8i8RQ91PET8D/Qy9MQy3e,Q3kxzr2gszknZw_w2txWZ?<4y9T@w9yf/i8f4i8DEmRR1nA5vMMYvg,8yTI8KwE;NZKwEyv/i8JX4bEa;cvp1ysrEZov/QC9NUfZ0M@4Cg<4ybuNx8zjl0f<i8BY90zEx8z/P7ixs1Q7Aybv2g8i8QRbjM.exJyf/Kw8<25M0@5C;4O9_Ai9Z@z5yv/i8fU_M@4pv/_QydreLUi8Jl080W07hnj8R49218ys6@8;370j8D7i8QlW3I0>O9h2g8W5G7/Z8yTQ0i8JQ90wNXuzqyL/Wij/_Yf7Qg.bE1;i8D6h8DTW629/Z8w_z_3Ug0//i8D6i8QZFjI.370cuTEYUr/@DJ_L/pwYvh<Kw4<3FnL/_MYv0{}glplkQy3X118zngA3ex@yf/i8D3i8cU07g7wTMA309_7HQ1;i8DvWb66/Z8wYggyuxrnk5uMSof7Qg0>ybu0wNZHEa;Wd27/Z8ySIgi8QR93I0>69NAy9X@xax/_xs1QjAyddhAX0,8yu_EdUv/Un0t5d8zjkheM.i8DLW2i7/@5M7hoi8QRzPE0>y9X@whx/_xs1Rnki9ZP7JWae6/_Ftv/_Sof7Qg.bU1;h8DTcuTEKon/@Br//3NZ.37Sh8DTcuTEF8n/@B6//3N@]bU2;h8DTcuTEyon/@AH//3NZ0>y9XAydfpsW<NMez_xf/WgP/_ZCbwYvx}glplkQy3X118zngA3exux/_i8D5i8cU.@4ggc.8dY90M13UU60w.i8J024y9NQC9NKxDxf/i8D3i8n03UjX0w.ZA0E10@4Wg8.379cvp8zhkXew.i8DvW0W5/YNOrU1;i8Dvi8Qlb3E.ezUxf/csC@0w<4y9TQyd5icW.3EUEj/P79Lwc<18ytZ8zhkqew.WcO4/YNOrU4;i8Dvi8Ql3PE.eySxf/csC@1g<4y9TQyd5gkW.3EE8j/P79Lwo<18ytZ8zhk3ew.W8G4/YNOrU7;i8Dvi8Ql@jA.exQxf/csC@2;4y9TQyd5uYV.3EnEj/P79LwA<18ytZ8zhnyeg.W4y4/YNOrUa;i8Dvi8QlRPA.ewOxf/csC@2M<4y9TQyd5sIV.3E78j/P79LwM<18ytZ8zhn1eg.W0q4/YNOrUd;i8Dvi8QlIjA.ezMw/_csC@3w<4y9TQyd5qwV.3ESEf/P79LwY<18ytZ8zhmveg.Wci3/YNOrUg;i8Dvi8QlCzA.eyKw/_csC@4g<4y9TQyd5poV.3EC8f/P79Lx8<18ytZ8zhmaeg.W8a3/YNOrUj;i8Dvi8QlvPA.exIw/_csC@5;4y9TQyd5ncV.3ElEf/P7ri8DLW9O3/Z8wYggytxrnk5uMV18zjRue<Wfi2/Z8zjRse<Wey2/Z8zjRte<WdO2/Z8zjRue<Wd22/Z8zjRte<Wci2/Z8zjRte<Wby2/Z8zjRBe<WaO2/Z8zjRBe<Wa22/Z8zjRBe<W9i2/Z8zjRye<W8y2/Z8zjRxe<W7O2/Z8zjRve<W722/Z8zjRve<W6i2/Z8zjRpe<W5y2/Z8zjRqe<W4O2/Z8zjRre<W422/Z8zjRwe<W3i2/Z8zjRCe<W2y2/Z8zjRAe<W1O2/Z8zjRze<W122/Z8zjRxe<W0i2/_FWvX/MYvw:1cyvvEs8f/QO9Z@yEwL/i8D3i8n03UnX_f/A{}KM4<3FILX/Sof7Qg0>y3X0x8yPQJng.Lw4<3EOUj/Qybfqht.2@?<eyWxf/i8IZsRQ.bU1;WaC4/Z8yPRang.Lw4<3EC8j/QybfnBt.2@?<ey7xf/i8IZ05Q.bU1;W7q4/Z8yPR7ng.Lw4<3Epoj/Qybfups.2@?<exkxf/i8IZnlQ.bU1;W4e4/Z8yPSQn<Lw4<3EcEj/QybfpJs.2@?<ewxxf/i8IZ4BQ.bU1;W124/Z8yPSFn<Lw4<3E_Uf/Qybfp1s.2@?<ezKw/_i8IZ1RQ.bU1;WdS3/Z8yPSen<Lw4<3EP8f/Qybfils.2@?<eyXw/_i8IZJ5M.bU1;WaG3/Z8yPSHn<Lw4<3ECof/Qybfo9s.2@?<ey8w/_i8IZ4lM.bU1;W7u3/Z8yPQwn<Lw4<3EpEf/P70i8f42cc<3P3NXWi8fI24y3N0z3~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#4g<4o;2;1M<9d14e94Asw0jEDkgc24Q3l6=4w<19;iw<4I<1d;jM<58<1k=5o<1p;mw<5I=n;7x1zT9nXO0y9Qv8xRk@FGsP6Ttfv4gfGYdTHrrQ6YliMmIv88o0aN0upbAfPU7NeRj34KVbuYU_8DimX7RldGEIyKyu8KaqqSuPGt@tPQPqClvClU6rkxtj7qGf!<vM<1%uw<18^zg<18^iM40,8^vM40,8^4;2%Rw<1%5w40,8^kg80,8^sw<18^HM80,8^@g40,8^og40,8^Fw80,8^Jw40,%n;18^aw80,8^lg<18^5w80,8^ug<1%Hg40,8^xM40,8^V;1%rw40,8^m080,8^oM<1%4>0,8^E>0,8^1M80,8^2M40,8^gg40,8^ww80,8^kw40,8^5g80,8^Qw40,%eg40,8%g<2%tM40,4^qM<18^R>0,%fw80,8^Dw<18^pM40,8^p;18^a>0,%Hw<1%Ag80,8^7g80,8^s080,%1>0,8^Fg40,8^8w80,8^q080,8^_;18^ig80,8^tg40,4^C>0,8^o>0,8^Yg40,8^dw80,8^Uw40,8^b;2%Og40,8^hw<28^U080,%Mw<1%C080,8^3w80,8^mg40,4^mwg0,406g0wVg}3+Hgc0,406g1wVM}3+igg0,406g1wVg}3+rgg0,406g3wV[3+D0c0,406g2wVM}3+pMc0,406g1wW[3+X080,406g3wWg}3+ywc0,406g3wVM}3+J080,8,03gwg}841[Pgc0,406g3wVw}3+50c0,406g1wWg}3+dMg0,406g2wVg}3+3gg0,406g0wVw}3+egc0,406g3wW[3+.c0,406g2wWg}3+9wg0,406g3wVg}3+PM80,406g0wWw}3+l0c0,406g2wW[3+uwc0,406g0wW[3+M0c0,406g0wVM}3+Ugc0,406g2wVw}3+Zgc0,406g1wVw}3+9wc0,406g0wWg}3+05ZvpSRLrBZPt65Ot5Zv05Z9l4Rvp6lOpmtFsThBsBhdgSNLrClkom9Ipg1vilhdnT9BpSBPt6lOl4R3r6ZKplhxoCNB05ZvoTxxnSpFrC5IqnFB07dQsCdEsw1Pt79IpmU0u6Rxr6NLoM1JpmRzs7A0sThOoT1V07xCsClB06pFrChvtC5Oqm5yr6k0nRZBsD9KrRZIrSdxt6BLrw1vnSBPrScOcRZPt79QrSM0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0sTBPoSZKpw1Ls6lKdzg0sClxp,zr6ZPpg1vnSBPrScOcRZPt79QrTlIr,DpnhvsThOqmVDnTpxr7lB07dVsSdxr6M0rmJPt6lJs3oQ07lKr6BKqM1Pt79zrn.sThApn9O06pTsCBQpg1Jrm5Mdzg0rmlJsSlQ05ZvpmVSqn9Lrw1Pt79KoSRM05ZvqndLoP8PnTdQsDhLr6M0pnpBrDhCp,Mqn1B06pzrDhIdzg0sSVMsCBKt6o0oCBKp5ZxsD9xulZBr6lJpmVQ07dQsClOsCZO07lKoCBKp5ZSon9Fom9Ipg1MrTdFu5ZJpmRxr6BDrw1IsSlBqPoQ06dIrSdHnStBt7hFrmk0rmlJoSxO07lPr6lBs,Cs79FrDhC071Lr6M0s79BomgSd,ComNIrSdxt6kSd,CsThxt3oQ07dBrChCqmNBdzg0sTBPqmVCrM1Ps6NFoSk0oSZMulZCqmNBnT9xrCtB06RBrn9zq780rm5HplZytmBIt6BKnS5OpTo0nRZQr7dvpSlQnS5Ap780rnlKrm5M05ZvoThVs6lvoBZIrSc0sSxRt6hLtSU0s7lQsM1PpnhRs5ZytmBIt6BKnSpLsCJOtmVvsCBKpM1OqmVDnSBKqnhvsThOtmdQ065Ap5ZytmBIt6BK079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt,OqmVDnSdIomBJnTdQsDlzt,OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZzr6lxrDlMnTtxqnhBsBZPt79RoTg0sCBKpRZFrCtBsThvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt,OqmVDnS5zqRZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZzrT1VnTdQsDlzt,OqmVDnTdFpSVxr5ZPt79RoTg0r7dBpmJvsThOtmdQ079FrCtvqmVApnxBsBZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt,OqmVDnSpxr6NLtRZMq7BPnTdQsDlzt,OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZPpm5InTdQsDlzt,OqmVDnSpzrDhInTdQsDlzt,OqmVDnT1Fs6lvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt,OqmVDnSNFsThvsThOtmdQ06NFoCcKsSYKdw1Ip2RIqmVRu2RUe3oJdzgKsSYKcw17j4B2gRYObzc0hQN9gAdvcyUPcM17j4B2gRYObzs0hQN9gAdvcyUOe,7j4B2gRYObz4Q>tcik93nP8Kczs0hQN9gAdvcyUNc,7j4B2gRYObz4T>tcik93nP8Kdg17j4B2gRYObzcU>tcik93nP8KcyUR:g02.8.w020>.g03.g.w02.k.w020>.w06.8.w,.8.M,.8,M,.8.w02.8.w08.8.w,.8.g02.A.g0a.c.w020>.g02.8.g02.I.w02.8.w02.M.w02.Q.w,.8.w,0>02w02.8.g,0>.g,0>.g,0>.g,0>.g,0>.g,0>.g,0>.g,:g,08w4<g;8;1dFqgQ<w0Dgg[1.I0vwg0,+IV6m1w.3g2D1<4;1tFqgQ<M0Iwg0,;28Apo6<b0bM4<g;4SBF3g.2w2t1<4;9ihBwo<A0NMg0,;27Apo6<70d84<g;A96m1w0,w3t1<4;9uhBwo<k0W?0,:lqmAd<40fc4<g;K96m1w<M3Z1<4;7kqqgA<8020k[gTg[w=I0s[oTg[w=s0s[wTg[w=8dQ[wUw[w=ZbA[EUw[w+XE}10Uw[w=4XE}18Uw[w=4bU}1wUw[w=7XE}1EUw[w=aXE}20Uw[w=gXE}28Uw[w=kbE}2wUw[w=pHE}2EUw[w=srE}30Uw[w=wbE}38Uw[w=zrE}3wUw[w=FrE}3EUw[w=FHA=UM[w=JrE[8UM[w=CrA[wUM[w=MHE[EUM[w=zbA}10UM[w=PXE}18UM[w=RXE}1wUM[w=WXE}1EUM[w=@HE}20UM[w=2XI}28UM[w=7bI}2wUM[w=crI}2EUM[w=gbI}30UM[w=nbI}38UM[w=pHI}3wUM[w=vrI}3EUM[w=gbU=V=w=zbI[8V=w=hbA[wV=w=CHI[EV=w=cbA}10V=w=GrI}18V=w=KbI}1wV=w=PHI}1EV=w=obU}20V=w=SHI}28V=w=VHI}2wV=w+XM}2EV=w=_Xw}30V=w=4bM}38V=w=bbM}3wV=w=fHM}3EV=w=o7U}3UV=w=8e8=Vg[w+XE[wVg[w=WbA[EVg[w=Y6g[UVg[w=ge8}10Vg[w=4bU}1wVg[w=THA}1EVg[w=s6c}1UVg[w=oe8}20Vg[w=aXE}2wVg[w=QXA}2EVg[w=g7Q}2UVg[w=we8}30Vg[w=kbE}3wVg[w=OrA}3EVg[w=I68}3UVg[w=Ee8=Vw[w=srE[wVw[w=JXA[EVw[w+68[UVw[w=Me8}10Vw[w=zrE}1wVw[w=FHA}1EVw[w=I64}1UVw[w=Ue8}20Vw[w=FHA}2wVw[w=CrA}2EVw[w=M5U}2UVw[w+ec}30Vw[w=CrA}3wVw[w=zbA}3EVw[w=s5U}3UVw[w=8ec=VM[w=zbA[wVM[w=xHA[EVM[w=U7I[UVM[w=gec}10VM[w=RXE}1wVM[w=uHA}1EVM[w=I5Q}1UVM[w=oec}20VM[w=@HE}2wVM[w=sbA}2EVM[w=o5Q}2UVM[w=wec}30VM[w=7bI}3wVM[w=prA}3EVM[w=45Q}3UVM[w=Eec=W=w=gbI[wW=w=nbA[EW=w=s5A[UW=w=Mec}10W=w=pHI}1wW=w=kbA}1EW=w=85A}1UW=w=Uec}20W=w=gbU}2wW=w=hbA}2EW=w=U5w}2UW=w+eg}30W=w=hbA}3wW=w=cbA}3EW=w=k6w}3UW=w=8eg=Wg[w=cbA[wWg[w=9bA[EWg[w=Q7E[UWg[w=geg}10Wg[w=KbI}1wWg[w=6rA}1EWg[w=Q6w}1UWg[w=oeg}20Wg[w=obU}2wWg[w=3bA}2EWg[w=A5w}2UWg[w=weg}30Wg[w=VHI}3wWg[w=_Xw}3EWg[w=I6o}3UWg[w=Eeg=Ww[w=_Xw[wWw[w=Zrw[EWw[w=g5w[UWw[w=Meg}10Ww[w=bbM}3UTw}1&8TM[o<1m)gTM[o<1i)oTM[o;6)wTM[o<1a)ETM[o<1d)MTM[o<1j)UTM[o<1b-10TM[o<16-18TM[o<1f-1gTM[o<1p-1oTM[o<1g-1wTM[o<19-1ETM[o<1r-1MTM[o<1k-1UTM[o;B-20TM[o;C-28TM[o<1n-2gTM[o<1c-2oTM[o<1s-2wTM[o<18-2ETM[o<17-2MTM[o<1l-2UTM[o<1h-30TM[o<1o-38TM[o;@-3gTM[o<1q-3oTM[o<1)3wTM[o<15)0U=s;1)8U=s;2)gU=s;3)oU=s;4)wU=s;5)EU=s;7)MU=s;8)UU=s;9-10U=s;a-18U=s;b-1gU=s;c-1oU=s;d-1wU=s;e-1EU=s;f-1MU=s;g-1UU=s;h-20U=s;i-28U=s;j-2gU=s;k-2oU=s;l-2wU=s;m-2EU=s;n-2MU=s;o-2UU=s;p-30U=s;q-38U=s;r-3gU=s;s-3oU=s;t-3wU=s;u-3EU=s;v-3MU=s;w-3UU=s;x)0Ug[s;y)8Ug[s;z)gUg[s;A)oUg[s;D)wUg[s;E)EUg[s;F)MUg[s;G)UUg[s;H-10Ug[s;I-18Ug[s;J-1gUg[s;K-1oUg[s;L-1wUg[s;M-1EUg[s;N-1MUg[s;O-1UUg[s;P-20Ug[s;Q-28Ug[s;R-2gUg[s;S-2oUg[s;T-2wUg[s;V-2EUg[s;W-2MUg[s;X-2UUg[s;Y-30Ug[s;Z-38Ug[s;_-3gUg[s<1)3oUg[s<11-3wUg[s<12-3EUg[s<13-3MUg[s<14!}pC5Fr6lA87hL86dOpm5Qpi1xsD9xujEw9nc09ncW86VLt21xry1xsD9xug16jR9bkBlenQpfkAd5nQp1j4N2gkdb02ZApnoLsSxJ02ZQrn.hAZiiR9ljBZ4hk9lhM1QsDlB06pLsCJOtmUwmQh5gBl7ni15rC5yr6lA2w1Jrm5Mey0BsM1KlSZOqSlOsQRxu,KlSZOqSlOsM1Kj6BKpnddonw0rA9Vt6lPjm5U>5ihRZdglw0biRTrT9Hpn9PbmRxu3Q0biRTrT9Hpn9Pc3Q0biRTrT9Hpn9Pfg0JbmNFrClPbmRxu3Q0biRIqmVBsP0Z02QJr6BKpncZ02QJoDBQpncJrm5Ufg0Jbm9Vt6lPc3Q0biRyunhBsPQ0biRIqmRFt3Q0biRQqmRBrTlQfg0JbmtOpmlAug0JbmZRt3Q0biRQqmRBrTlQ02lA>lmhAhvkABehRZ4glh1>lmhAhvkABehRZ5jQo0hlp6h5ZiikV7nQBehQljl5Z4glh1>lmhAhvkABehRZ9jAt5kRhvhkZ6>lmhAhvkABehRZjl45ilAk0pCZOqT9RrBZLtng09mNR2w1TsCBQpixCp5ZPs65TryMwsS9RpyMwsSNBryA0pCZOqT9RrBZOqmVDbCc0tT9Ft6kEpnpCp5ZAonhxb2pSb3wF07wa07tOqnhBa6pAnTdMontKb20yu5NK8yMwcyA0tT9Ft6kEpnpCp5ZBrSoI82pBrSpvsSBDb20Uag1AsDA09ncK9mNR0599jAtvikV7hldknQh9lABjjR80kABehRZ2glh3i5Z9h5w0kABehRZ2glh3i5Zjj4ZkkM16h5ZfkAh5kBZgil1507tOqnhBa6pAb20CtC5Ib20Uag1TsCBQpixCp5ZIrSdxr5ZPqmsI82pLrCkI83wF06pLsCJOtmVvqmVMtng0rmlJpChvoT9BonhB86pxqmNBp3Ew9nc0s6BMpi1ComBIpmgW82lP06dIrTdB07dMr6Bzpi1ComBIpmgW82lP03.tT9Ft6kEpnpCp5ZAonhxb20CrSVBb20Uag1FrCc0p6lz05d5hkJvkQlk05d5hkJvhkV402lIr6g09mNIp0E0sSxRt6hLtSVvtM1Pq7lQp6ZTrBZO07dEtnhArTtKnT9T07lKqSVLtSUwoSZJrm5Kp3Ew9nc0sCBKpRZFrCBQ079FrCtvp6lPt79Lug1OqmVDnTdzomVKpn80sCBKpRZzr65Frg1OqmVDnTtLsCJBsw1OqmVDnSdIpm5Ktn1vtS5Ft6lO079FrCtvqmVDpndQ079FrCtvpC5Ir6ZT079FrCtvomdH079FrCtvrT9Apn80sCBKpRZzrT1V079FrCtvsSBDrC5I06NPpmlH079FrCtvqmVApnxBsw1OqmVDnSpBt6dEpn80sCBKpRZComNIrTtvs6xVsM1OqmVDnSRBrmpAnSdOpm5Qpg1OqmVDnTdBomM0sCBKpRZCoSVQr,OqmVDnT1Fs6k0sCBKpRZPs6NFoSk0j6BPt21IrS5Aom9Ipnc0sCBKpRZIqndQ85Jmgl9t05dMr6Bzpi1Aonhx>dOpm5Qpi1Mqn1B079FrCtvs6BMpi0Ygl9iv594fy1rlR9t>pFr6kwoSZKt79Lr,OqmVDnSpzrDhI83N6h3Uwf6dJp3U0kSlxr21JpmRCp,OqmVDnTdBomMwf4p4fw13sClxt6kwrmlJpCg0sCBKpRZJpmRCp5ZzsClxt6kwf5p1kzU0k6xVsSBzomMwpC5Ir6ZT>Vljk4whClQoSxBsw1elkR184BKp6lUpn80kSlBqO1Cp,IsSlBqO0YhAg@83NfhAo@byUK05dFpSVxr21BtClKt6pA079FrCtvsSBDrC5I83N6h3U0mClOrORzrT1V86BKpSlPt,OqmVDnSdLs7Awf4Zll3Uwf4Befw1ipmZOp6lO86ZRt71Rt,OqmVDnSZOp6lO83N6h3Uwf516m7NJpmRCp3U?mdH869xt6dE079FrCtvomdH83N6h3Uwf4p4nQZll3U0j6ZDqmdxr21ComNIrTs0kSBDrC5I86BKpSlPt,3r6lxrDlM87txqnhBsw1nrT9Hpn8woSZKt79Lr,OqmVDnTtLsCJBsy1rqmVzv6hBoRQ?SNxqmQwoC5QoSw0kDlK87dzomVKpn80sCBKpRZPoS5KrClO83NCp3UwmTdMontKnSpAng14pndQsCZV879FrCs0imVFt6Bxr6BWpi1OqmVD87tFt6wwoSZKpCBD079FrCtvqmVFt21rhAN1hRdt079FrCtvr6BPt,FrDpxr6BA86VRrmlOqmcwqmVApnwwpCZO86BKp6lUpmgwon9OonAW82lP}LsTBPbShBtCBzpncLsTBPt6lJbSdMtiZzs7kMbSdxoSxBbSBKp6lUcOZPqnFB0,CrT9HsDlK85J4hk9lhRQw9ncW9mgW82lP86pxqmNBp3Ew9nca;tT9Ft6kEpnpCp5ZFrCtBsThvp65QoiMw9DoI83wF0,TsCBQpixCp5ZComNIrTsI82pFs2MwsSBWpmZCa6BMaiA=pCZOqT9Rry1rh4l2lktt879FrCtvomdH86NPpmlH86pxqmNBp3Ew9nca[tT9Ft6kEpChvs6BMpiMw9CZMb21PqnFBrSoErT0Fag1TsCBQpixCp5ZQon9DpngI82pFs2MwsSBWpmZCa6BMaiA=tT9Ft6kEpChvpSNLoC5InS5zqOMw9D1Mb21PqnFBrSoEs70Fag<6pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME<1CrT9HsDlK85J4hk9lhRQwsCBKpRZzr65Fri1IsSlBqO1ComBIpmgW82lP2w;1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ}1OqmVDnSpxr6NLtO0Yk4BghjUwf4p9j4k@85JAsDBt079FrCtvoSNxqmQwf4Z6hzUwf4del3UwmQ9pl4ljni1rhAht).2ZApnoLsSxJbSpLsCJOtmULt6RMbSpLsCJOtmUKm5xo?(1Y07w0t,M06M0q,A06.n,o05g0k,c>w0h,.3M0e.Q03.b.E02g08.s,w05.g.M020>;1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3wYe3gMb2wA81Mo510c2?0f3wQc2ME920s61gg30w4,;2:5;hQVl0>.s>;eg=2.7,:Q+hI3eOg1<z;84f/Q,.3Mh/_q>.31a/_w?.84L/MM20,wjf/c08.a1o/@.w.U7X/@w2.2Mv/_d0c.222/@.M.I8f/YM30,0y//0c.92m/ZA1<s9z/Xg4.30Cf/R?0,2p/_Q1<k9D/Ng5.2wCv/d0k0>2t/ZY1g.A9T/VM5.3wDv/L0k.a2u/_E1g.Y9X/Mw6.3wEv/l0o.32y/ZQ1w.Uab/Ww6.2wE/_P0o.22B/Y,M.Uar/QM7.20Gf/u0s<2F/@w1M<bL/Z07<gLf/_0s.72Z/YU2<AbX/SM8;ML/E0w[k+5Wkw,u1,6MM729,<A;7;dx1/Y,:UghwUoiwYbtMy.3YqeOEP928:t;4g<20hL/dg8<1b3x2e0A8e68Q3gwUwz0h93yy61k4ec8c6hMVgo0Eec4D33yx1NwUwgIMe64bd3x12PwU8i0I3s>a3z14MMUEgsoe84bc3xx2PgUggIUe24Qbs0U8MYrcPsV83B231Eo5z0id0UU2a;bM<18if/Xw;113x230AAek4Ua3x113wx72M9i2wUghgU8igIw;W:N9/YP?<44e48c2jwVw0Bka3x133wx92M1c;3>.2xa/YW3;48e48Y2gwUozwd23y2d14kea8M5ggUMxwp13zy31Qsew0A3Tg4a3zx13z113yx23y123xx23x123wx52M<6g<1s?.65r/PAC;iMUgzM973xye0Q8e88Q4gwUEz0l13z261Agee8c7igWg0McI3gU8MYrcPsXfk0Wg0Uc7xwqc1oQ4zwef0wbT2wUUgMUMggUEgwUwgwUogwUggwU8ggI0i;cg1.3Mu/_O:123x2f0A8e68U3hgUwzgh23yyc1k4ec8o6ggUUwMt43B02DgEee4gec44ea48e848e648e448e24kb>w;g0w.t7P/So2;kwUgzM9a3xye0Q8e88Q4gwUEz0l13z261Acee8c7iwXw20bz2wUUgMUMggUEgwUwgwUogwUggwU8gMJ8;n08.9x@/@4?<58e48Y2hMUozwd53y2d148ea8M5ggUMxwp13zy31QEeU0w3iM4ee4cec44ea48e848e648e448e2<b;aw2.3sv/_A0s<1h3x260Awd1Aif0UU4i8Q5z0q31Mdf0MEc1Mx42M.p;dw2<Yx/_jwI<1b3x2f0Ase68U3gwUwzgh53yyc1k4ec8o6h0UUwMt93K030_Q12wUUggUMggUEgwUwgwUogwUggwU8gwI2I0U8MYrcPsXfk0Xw0Uc7xwqc1oQ4zwef0w1c;g0c.2ii/_n?<58e48Y2hMUozwd23y2d148ea8M5ggUMxwp13zy31QEeA8840OU12wUUggUMggUEgwUwgwUogwUggwU8hMI0,M<2g0M.J9f/Qk:ggUgwM993z1T3x133ww07;b03.3AA/_hg;113x230AAec7se44ce2.s;Q0c0,ik/Y_:44e48c2igUwsgUggMU8,M<3M0M.d9j/Qk:ggUgwM993z1T3x133ww0h;1>0,ABf/Cgc<123x2f0A8e68U3gwUwz0h13yy61koec8c6hMXM?eJ?Eec4cea44e848e648e448e244b;7;5w4.2YB/_hg;113x230AAec7se44ce2.s;u?.eOn/Z5:44e48c2igUMtMUggMU802w<2o1<79z/Y]ggUgxw963xy30Qgec09c2wUogMUgggU8hgI07;cg4.2MCf/hg;113x230AAec7se44ce2,8;V?.e2o/_E0w<48e48Y2gwUozwd23y2d148ea8M5ggUMxwp13zy31QAeA05E2wUUgMUMggUEgwUwgwUogwUggwU8igI07;305.24C/_hg;113x230AAec7se44ce2.M;k0k.bir/@A:48e48U2ggUoxwd63y2314gek09A2wUwgMUoggUggwU8igI08;8g5<MDf/Lw;113x230Agec09q2wUggMU8hwI0c;aw5.3cDf/tM4<123x2e0A4e68o3hwUwwMh43B02IMEe84ce644e448e24Eb>w<3s1g.69X/XY1;gwUgzM923xye0Q8e88Q4gwUEz0l13z261Aoee8c7h0VwrMEee4cec44ea48e848e648e448e248b<E;a0o.8Ov/@v?<44e48o2hwUowMd43z02PwEe64ce444e24cb02g<1k1w<a7/To:ggUgxw963xy30Qgec09C3xx33x113wwI;v0o.5yx/Y>w<44e48o2gMQ6ioY3zwid1oM6wMs3R0Aa30s8ggI;E;H0o.2yP/Y7?<44e48c2igUMpwEe44ce24kb0Gka3x133wx82Pw<3o1w.3bj/R81;gwUgzM923xye0Q4e88o4ggUEwMl43D1N2wUEgMUwggUogwUggwU8hgI.3:k1M.cbn/No1;gwUgzw913xy60Q4e88c4h0UMqMEe84ce644e448e24sb<M;i0s0,OS/ZG0M<48e48U2ggUoxwd13y2314gec0cw0wEe84ce644e448e248b6;7M70,oKv/wg4<143x03v>e2~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~)//_M;2M1M}707[8dQ[1=7U4=g[281=M=P08[d=5i3[6g=gTg}1I=2+q=1zt[7+8=fn@_SY]9=5=7yp[1w[30A=E=50k[b=1w+M[3ETM[8=W0k[k+s=5M[28HM[s=aa=8=60f[2g=o=fX/SY:i9Y}3/_ZL]8=Yf/rM;2cDw}fD/SY:xM~~~~~~~~~~!]2zt!0o3[5wc[C0M}3o3[hwc}1m0M}6o3[twc}260M}9o3[Fwc}2S0M}co3[Rwc}3C0M}fo3[1wg[m1[2o4[dwg}161[5o4[pwg}1S1[8o4[Bwg}2C1[bo4[Nwg}3m1[eo4[Zwg[61g}1o5[9wk[S1g}4o5[lwk}1C1g}7o5[xwk}2m1g}ao5[Jwk}361g}do5[Vwk}3S1g[o6[5wo[C1w}3o6[hwo}1m1w}6o6[two}261w}9o6[Fwo}2S1w}co6[Rwo}3C1w)</////////////Y://///_QKg[eW!1eW[4bU!7XE[HKw#13Kw}52W!6qW[srE!wbE}2dKw#2BKw}aqV!bmW[CrA!MHE}2cKg#3fKw}duW!eKW[@HE!2XI[sKM!NKM}42X!5OX[pHI!vrI}10Lw#2cKM}4iV!9GX[cbA!GrI}2UKM#3eKM}62@!dGX[VHI!0XM}3_K!?L[2OY!3WY[o7U[1=23y=XE`3EKg}f1A=g[10Uw}12@~THA}1MoM[4=oe8[HKw`deV[g7Q[1=83y[kbE`39Kg}b1y=g[2wUw}76W~JXA=ow[4=Me8}2dKw`aqV[I64[1=e3y[FHA`2pKg}c1u=g+UM}9CV~zbA}1Mnw[4=8ec}2cKg`8qV[U7I[1=43z[RXE`1WKg}b1t=g[1wUM}fGW~sbA}1wng[4=wec[sKM`6mV[45Q[1=a3z[gbI`1sKg}71p=g[30UM}6qX~kbA[wmg[4=Uec}10Lw`4iV[U5w[1+3A[hbA~MKg}51E=g=wV[32V~9bA}3guw[4=geg}2UKM`1CV[Q6w[1=63A[obU~cKg}91o=g[20V[eqX~_Xw}2Mpw[4=Eeg}3_K~fmU[g5w[1=c3A[bbM)<4t3gPEwa4teliAwcjkKcyUN838MczkNcz4N82xipmgwi65Q834Rbz8KciQRag;w;g]40>t19>Poj40P08}1xwM=KsSxPt79Qom80bCVLt6kKpSVRbC9RqmNAbmBA02VFrCBQ02VQpnxQ02VCqmVF02VDrDkKq65Pq.Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bD9Lp65Qog0KrCZQpiVDrDkKs79Ls6lOt7A0bClEnSpOomRBnSxAsw0KpmxvpD9xrmk0bDhAonhx02VQoDdP02VFrCBQnS5OsC5V02VCqmVFnS5OsC5V02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpSZQ02VDrTgKs6NQ02VAonhx02VysTc0bCdLrmRBrDg0bCtKtiVytmBIp2Vxt7hOqm9Rt6lP~~+.2M;s;2=aw2[G08[A*1*1U;1;1w[3c0w}cM2[6M*g(1R:g;o=Y08}3M0w=4(g=1+9:4;6+07+s}1hv(g*2E;1;1w[1kwM}5i3[3g*g*M;ZL/rM8+9+A[c+1M=8*ew;I;2=c2g[M9[2U2=w;1;2+o=48;3:w[1UCg}7yp[50k(4(1a;//rM8=z9U}2cDw}bE=1M=2+8=lM<fX/SY2=4yv[i9Y}3w+w;2;2*6o;4:w=EE[2yw[o0Y[7+w=6=1M;1;48=yaY}28HM}ew5[1M<1w;8=1w=uw;4;2=82R[wbk[w2w)<g*88;7:w[2wLM}a2_[c&w(2l:g;8=QbY}3gLM}2g1(4*EM;4;2=fz=@c[2o1M)<2*aQ;1:Mg[8Tg[zd[1&w(2Q;2:c4[4dQ[gPg[Q*8*Kw;U;3=13t[4cQ[8*2+8=co;f:M=oTg}1zd[2&w=2=3i:g;c=8dQ[wPg[w*8*TM;o;3=2zt[acQ}3g?[w=2+g=ew;1:M[3UTw}fze[Y&w=2=3J:g;c=WdY}3EPM}102(8+w=Zw;4;3+3y=d8}1g2(8*fM;8:M[1gWw}53q[a&w*1?<g<3*1gSw}2U*1+4=2w4<s-7wa?]wdE[A*1&4;3^ajq[8>(4(')


_forkrun_bootstrap_setup --force

