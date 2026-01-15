#!/usr/bin/bash

frun() (

    # # # # # SETUP # # # # #

    local test_type worker_func_src nn N nWorkers0 cmdline_str ring_ack_str delimiter_str delimiter_val
    local -g pCode fd_order fd_spawn ingress_memfd nWorkers nWorkersMax tStart
    local -gx order_flag unsafe_flag
    local -ga fd_out args P

    tStart="${EPOCHREALTIME//./}"

    toc() {
	    printf '\n%s finished at +%s us\n' "$*" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
    }

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
            printf '\npreparing to spawn %s workers at +%s us...' "$N" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
            nWorkers0="$nWorkers"
            (( ( nWorkers0 + N ) > nWorkersMax )) && (( N = nWorkersMax - nWorkers0 ))
            (( N > 0 )) && for (( nWorkers=nWorkers0; nWorkers<nWorkers0+N; nWorkers++ )); do
                spawn_worker "$nWorkers"
            done
            printf '\nspawned %s workers at +%s us\n' "$N" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
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

declare -A b64=([0]=$'108174 54088\nmd5sum:f763098c49e92d9bf3d3cfdc36188262\nsha256sum:c0adaf330e9afc27e21338cc2161454b1fb053be891c9c0e4b2dee2c40e9ebdd\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n00000000000000000000000000\n0000000000000000000000000\n000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\npCoK3N@4\n00000000\n0000000\n000000\n00000\n0000\n000\n04\n1M\n0g\n00\n__\n//\034vQlchw81.+?c0fw01-1+czb+<4?e?b,?7w0t0,;5!}wnY}21vM=g=g;g:w=2+8[2ke[9gU=1=1;1w;yZ[2cQ[8Pg}4wd[s0Q=4=8;6;abQ[EPg}2zd[Q,}3g.[w=1:g<2E0w}aw2[G08[A=2g=1+4;1;a2L[EaY}2wHM}3+c+8+s;4;2bQ[8Pg[zd[1+l+w=k@lQp.<2wHM}a2L[EaY[M=3+2=1gVnhA1;d2L[QaY}3gHM}2g1[9,[4=57Bt6g6~)?1+kKlQp.;8Lg[zd[2cQ}3U0w}fw2=g=4;5:c<17jBk0Uo6TsZ14kuOlGcsvn7N0AxHD3ivP3NXWi8fI24yb1pTc?18xs1Q0L_gi8f42cc+03_dvHc?3_9vPc<f7Q?_OnWP<q:3FUf|YBYIM?6w1;Wt3|_9uHc?1E0w<eD0|_OnyP<q0c<3FIf|YBSIM?6w4;Wq3|_9tbc?1E1g<eCg|_OnaP<q0o<3Fwf|YBMIM?6w7;Wn3|_9rHc?1E2;eBw|_OmOP<q0A<3Fkf|YBGIM?6wa;Wk3|_9qbc?1E2M<eAM|_OmqP<q0M<3F8f|YBAIM?6wd;Wh3|_9oHc?1E3w<eA0|_Om2P<q0Y<3FYfX/_YBuIM?6wg;Wu3@|9nbc?1E4g<eDg_L/_OlGP<q18<3FMfX/_YBoIM?6wj;Wr3@|9lHc?1E5;eCw_L/_OliP<q1k<3FAfX/_YBiIM?6wm;Wo3@|9kbc?1E5M<eBM_L/_OkWP<q1w<3FofX/_YBcIM?6wp;Wl3@|9iHc?1E6w<eB0_L/_OkyP<q1I<3FcfX/_YB6IM?6ws;Wi3@|9hbc?1E7g<eAg_L/_OkaP<q1U<3F0fX/_YB0IM?6wv;Wv3Z|9vHb?1E8;eDw_v/_OnOOM?q24<3FQfT/_YBWII?6wy;Ws3Z|9ubb?1E8M<eCM_v/_OnqOM?q2g<3FEfT/_YBQII?6wB;Wp3Z|9sHb?1E9w<eC0_v/_On2OM?q2s<3FsfT/_YBKII?6wE;Wm3Z|9rbb?1Eag<eBg_v/_OmGOM?q2E<3FgfT/_YBEII?6wH;Wj3Z|9pHb?1Eb;eAw_v/_OmiOM?q2Q<3F4fT/_YByII?6wK;Wg3Z|9obb?1EbM<eDM_f/_OlWOM?q3;3FUfP/_YBsII?6wN;Wt3Y|9mHb?1Ecw<eD0_f/_OlyOM?q3c<3FIfP/_YBmII?6wQ;Wq3Y|9lbb?1Edg<eCg_f/_OlaOM?q3o<3FwfP/_YBgII?6wT;Wn3Y|9jHb?1Ee;eBw_f/_OkOOM?q3A<3FkfP/_YBaII?6wW;Wk3Y|9ibb?1EeM<eAM_f/_OkqOM?q3M<3F8fP/_YB4II?6wZ;Wh3Y|9gHb?1Efw<eA0_f/&4ydfkDj?18zgl2QM?i3DUt1l8yMn@NM?i8n0t0D_U0Yvw:333N@]4ydfhDj?18zjkiQM?i2D@i8DMic7KfQz1@0d80sp8QvVQ54yb1mT8?18xs1Q2f_wpwYvh<MMYvw:3P3NXWw3TlQw<7kHlky3flb8;i8DBt0N8zjSeNg?W0D|Epf/_Yo5Ht8<5tMMYv0ccf7U]YMYu@KBT|3N@]4y5_M@4>80,5mgll1l4C9ZbVr;lld8yvJ8w@MwW1LY/Z8ysl8xs1Q3Qy9T@zH@/_w7M3_RRQ74y3N21cyup8ytYNQBJtglN1nk5uWiLZ/Yf7M19yuV8wYk1iiDuioR@0uxl_f/i8Duj8DOioD5i8D7WfjY/Z3NAgR?18yu_EBLL/QydkfZ8yst8yggAi8Bk90zE8vP/Qybl2g8i8DKi8D7i8D3WbXY/Z8yMMAj8DLNAgb_M3EnvL/Qydu07EZfL/QO9XAy9N@zF@L/i8Dvi8D5W3XX/Z8znw1WdnX/Z8ytV8ysvEOLH/QO9VQC9NKwv@/_i8RU0uyS@/_j8DCi8D7WaLW/ZcyuZ9ysjEgfL/Qy9T@wU@/_i8DLW13W/Z8xs0fxdY<2bk2zSMA1RnUfy10@4Hw<4z7h2go:ew8@L/i8RQ91yW2w<4O9ZYs]4y9M@wJ_f/i8D6i8J491x9espQo80U07lrwPIyt5oNOkO9UAy9X@x9_f/WNIf7U]hj70j8Dxj8DOi8DKi8D7W4PZ/Z8yu_EFfH/QO9Z@ys@L/i8f484O9VRJtglN1nk5uWozW/Yf7Ug]4O9ZAydfsWy<NMeyv@v/WY4f7Qg0,y9XAydftCr<NMey7@v/WWAf7Qg?ccf7U]i8DLW73W/Z8yuV8zjSmCM?i8n03Uk6|WYZCpyUf7Ug]5e_Mw<4y3X43E4vP/Qy5M7Uci8f4g5L3pwYvh<i8QZwq8?37Scs3EIfL/UD7xs1UarEv;i8RQ9229h2gcW7vW/@bv2gci8A49ewW@L/i8Ik94y5QDYxLXY<3EJ_L/Qy5M7Vqi8f4g4z1U0drMMYvx}NAgk8018zngA6bEa;i8RY923EN_z/Qybl2go3Xoiw@bvwfFbt3Z8ys58Mu4kwfFdi0Z4Mky5M7izWlf/_Yf7U]LY8<3EjLL/Qy5M7@nK<g03Fc|MYvw:18Mu0aWYBCA5d8yvJ8zjSNCw?i8fIkeyc@L/i8n0t5u0e35RkE1U.1RjbG0.?LE8.g18zjSuCw?cs3EJfH/UD2xs1V7HG0.?LE8.g18zjS9Cw?cs3EBLH/UD2xs1Um4y3N529Q5L33N@4]2W0w<4y9THY_.?cs3EHfD/UD2xs1VRKyxZ/_wPwmtp0NQAy9THY_.?cs3Ey_D/UD2xs0fy7n|HHMYvw:35@mY5Ua80,ydv2ggibwKm5xom5xo,y9v2g8i8B49235@nZ4913E_fz/Qybv2g8xs29MDwpylgA2ex8Z/_yRgA2eBv|3N@]cnVrMmwEw?NQgA85xom035@nZ4913ELvz/Qybv2g8xs29MDD1WiT/_ZCA6pCbwYvx}glt1lA5lioDRglhlkQy1X4w4?29f2h8zjS3Cg?W3TV/Z8xs0fx>1?20e34fxeI1?18zjlPCg?i8D7W7PU/@5M0@5_;4yb1lT3?2W6;bU1;i8QZk9A?cs5QIQ<4<18yMzEGLD/QObfrLd?1dxvYfxtM<15csAN_Q6U|_XAx;Kwc<2@012w0eyr@f/i8fU_M@4CgE?37SKw.E018yst8yglUPg?W6LT/@_l;ewx@v/i8QZ09A0,y9M@y2@f/i8n0t1CW2w<37Si8D7W3XU/Z8ykgA24y5M7Yii8nrgrM1;j0ZfUQO9p2g8i8QZPpw?ex6@f/i8n03Ugd.?cvqW2w<4y9N@z@Z/_i8n03UXR;i8B4913FZ:Yv,ObfuDc?371uvc[jon_3UgA|iss7:4yb1szc?18NU<g}4yb1rrc?36w1w1;i8I5GcM0,z7g1]i8I5CsM0,z7g2]i8I5yIM?cp0a018yMl_P<ict0c:18yMlMP<NA0F,yb1mnc?2bfg_4?18NU0,2}8n_uhUNM4y1N4w4?1rnk5sglR1nA5vMMYvg02bfub3?2W0.0,ydt2h0W7LS/Z8xs1_VKLc3NZ?81U.0fx2b@/_F1LX/V18NQgA4,<18zjSHBM?W1LT/Z8xs1Q7z7SKwE<18ysvER_r/Qy5M7Uai8B491zH30Yv,z7h2go01<b@_;W7nT/Z8xs0fzCM8?1czjh0is7K0z7_W5TT/Z8ysd8xs0fzJ48?18yMmGM<i8IEi8JZ,y5_M@4Hg80,kNV0Yvw:3EW_j/Qybvgx8wYk8joRA1058xvZRWrQ0o<j3Dz3UZX0w?i8QZ2ps?exLZL/i8D3i8n03Ujz>?w3xc3Ukq0w?w7w1cw@5408?81U0w0fxgo2?18yNQnOM?i8J490x8yocE.?i8J49118NUcM.<g<4y9wO01?18yQgA64O9IR01?18yocU.?yMgAicu3g,}18NUdo.}cq3o,<36wSc1;w_w13UVp2<ict490z|_joRB28fE0Az712j|_joRINh1cyulC3N@4]18yRQ0KwU<18zjl7Bw?i8DvW4zP/@5M0@4K,?bEb;i8QReFo0,y9T@wIY/_xs0fx6g5?2W2w<4yddiGm?18yt_E4ff/Un03UhU1g?KwM<18zjkpBw?i8DvWfjO/@5M0@4B0k?bE9;i8QR2Fo0,y9T@zoYL/xs0fxaw5?2W2;4yddvyl?18yt_ELfb/Un03Uh41w?KwM<18zjnBBg?i8DvWa3O/@5M0@4C0o?bE9;i8QRRFk0,y9T@y4YL/xs0fx5g5?2W2;4yddsil?18yt_Eqfb/Un03Uh0>?Kww<18zjmNBg?i8DvW4PO/@5M0@4fws?bEa;i8QRDFk0,y9T@wMYL/xs0fxco6?2W2;4yddoSl?18yt_E5fb/Un03UkF>?i8I5bsA0,z7w5w1[Wpk;f7Qg0,yddtyk?18ytZ9yuXEzLf/Un03Ujw_v/KwE;NZAy9T@z7YL/ct98xs183QDgioDmWs3Z/ZC3NZ4?1caud8ytx8Mu,i2Doic7U14yd1418Muw2i8D5WmjZ/Yf7U]cvp8znIeKwE<3ECff/Qy5M7Uji8IlBcw0,y9wyw1<f7Qg0,y3Ngx9euQfxvfZ/Z8yMgAi8Itscw0,y5M0@4FMg<@9ggg0,y3v2g8?@edgg?cq3o,<76wSc1<1j8JQ90xcyrcM.?cuRcyrcU.?j8CPi,<Yv,Cbf2iW2g<4yddo2k?3EW_3/Un03Vj0iof420D5jjDBttJ0xeRR2Qz7wRw1?3|_i8Kb8,0,ybAOw1?36wS81<13Xq3o,0,wVQg@kwS41?24M0@4Z0c0,z7wMw1<1;cv@@.w80ey6Y/_cv@@.w808A5irY?exQY/_cv@@?w808A5cXY?exyY/_cv@@.w808A57rY?exgY/_cv@@?w808A51XY?ew@Y/_i8QZ3XY?8A5YrU?eycYv/xs0fy5g2?2bfvq@?2W?w?bU4;cs3ELvb/UIZUXU?bE02<cs2@1;eyCYL/yPT8Lw?Kw4;NMbU2;W8_O/@bfrm@?2W.<370Lw8<3Eufb/UIZDHU?bE?1?cs2@>g?exxYL/yMRXLw?Ly:NM4yd5juj?18znMA8ey3Yf/ct98zngA84ydfiaj?3Ewf7/UIdhHU?bUw;cs18zhk6AM?i8RY923EkL3/P7ii8RQ9218zjQ0AM?W4_N/@b3h6@?2@8;370i8QlRp80,ydv2gwW27M/YNQAydt2gwi8QZTp8?ewuYv/yMTsLg?Ly:NM4yd5qii?18znMA8ezMX/_ct98zngA84ydfsai?3EXv3/UIdFXQ?bUw;cs18zhlPAw?i8RY923EL@/_P7ii8RQ9218zjSCAw?WbPM/ZdxvYfx8LV/Zcyv_Eq@X/QC9N4y5M0@490c?fp0a.fx183?18yMmSNg?i8KUa,0,z1VMbELK/_QC9Nkyb1pP5?18wXwE.;@4Rw8?37ri8RI943HiwYvh<goB4Dg29Mkyd5uih<NMbUw;i8DLW2LL/Z8ytUNOky9WAO9VQy3MM7EJ@X/Qyb1kz5?18eVwE.?3Ue30w?i8QZ0F8?eyTZv/xs1VGUnrt218oZJcyuR9zlOt?Yvg02bvg18wYk4W3jL/Z8euJRXQO9X@yTXL/3N@]bw1;Wq3U/ZC3NZ4<NZAyduMKW2w<ezgX/_i8n03UV7_f/i8IlOcg0,y9wy01?3FdfP/MYvg?NZAyduMGW2w<eywX/_i8n03UUn_f/oLbZ27P0i8I5AIg?cnVvU0w.?WvTX/Yf7Qg?37Si8RX3bEa;W6zL/Z8xs0fzJ_X/Z8yNlwN<i8C2e,?eDc@/_3NZ?37Si8RX2rEa;W3zL/Z8xs0fzG_X/Z8yNkMN<i8C2c,?eCs@/_3NZ0,ybwO01?1cyXcM.?i8B49118yUcE.?i8B490x8yUcU.?i8B491x8yQMA2cq3o,<18ekMA40@kwS41?1ceTgA60@kwS81?1cyrc8.?WgLY/Yf7Qg?cq3o,<76wSc1<1i8dY90w03UVA@/_WlHX/ZC3N@4]18znI8KwE;NZKxwXv/i8A494y5M0@eY_H/SbO_gxYM4yb1mX3?35@n@0c,?eDp@L/pwYvx}ijDKj0Z7ZuAK@f/3NZ?b_2;WfrK/Z8xs0fzU7T/Z1Lw?1w3FvLv/Sqgcvp8znIcKwE<3E4eX/Qy5M0@ex_H/SbO_gxYM4yb1gb3?35@D@0i,?eBJ@L/3NZ4?3EE@L/UIUW0PL/Z8zjROzw?i8D6cs3EK@L/@Dm_v/pwYvh<Lg?603Fq_v/Sof7Qg0,O9X@xEXf/WlLS/Zcyv_Ei@T/QO9_@y3Xf/ioD4i8n03Uni_f/WpbZ/Z8yMS3Mw?i8RX2HEa;cvp8ykMA4ex6Xf/i8Jc9118yo5o.?WtnV/Yf7Qg0,6@.<eBo_L/3NZ4?18znI8KwE;NZKwgXf/i8B490zFFLD/XEa;i8RX237SWfrH/Z8yNknMw?i8C2g,?eC3@v/KwU<18zjlhzw?i8DvWc_G/@5M7kji8I5Xc4?cq0oM4<7FmfD/XE6;i8QRdoU0,y9T@yAWL/xs1R2kOduMrFd_D/U0XbkMfhvLFa_D/SpCbwYvx}w_Y13UUD3g0.luW2w<45mgll1l5l8yvljyvJ8wuNo.?i8J@237SW77I/@9h2gsw_I23Ukl1g?NEgAV:37x2jk;|_Qyb1lb1?18NMk_Mg}4z71iP1[i8Koc,0,y9n2gUi8Koe,0,y9D2jE;i8Ko8,0,y9n2hgi8Koa,0,y9D2j:i8Kok,0,y9n2hoi8Kog,0,y9n2hwi8Kom,0,y9D2jo;3Xqoo,?8ys9d8;fJFxy.?y9MAUg;@SC641?3Ej_3/XU?2?ic7E0Qw5/Yv,wB?3w_Qy9NXw;2i3D7i0Z7@bw?2?i3D7i0Z3NQydL2jU;i8D2i8B4933EyKP/QObL2jU;xs0fxj4r?2bv2gsKw4;NZAOdJ2gg.?W4bI/Zcyvq_1w<4O9t2h0i8B490zEq@D/Xw3;NebXZVgA6,0,yUP_tjUWmrN218Z@98qoMA4,0,123M18MuE4i8Q44ky9h2hMi8I5ZXY0,z7w?1[i8I5VrY0,z7]18yMnnLM?ict0c:18yMn8LM?i8Jc9518ykw8i8n9t0W0L2jA]@55x40,y3v2ho,S9_g@Sx2ji;NEgAy]fBogAU;8jrj8DX3Vi49e8;ax2jx;y8gAQM<4ybh2g8icu49b+i8B494x8NQgAa:18NQgAu:18NUgAw=18NUgAA=18NUgAC=18NQgAq:37x2ic=ct491]3Vi49ec<15cuh9etR13Vf6csB42HgAy:@5m>?82Y9d8:3Ujy;i8J49618zn3_i3JQ92wfwGMa?143Xpk9119ytJ8yQgAe4QFWQ63Uw51w_81ijD33Ueq0w?jonr3UhN0w?i8IRAHU?8dY91013Ugv2w?yQooxs1Qa4y3L2jo]@42gE?7Uni8eY9b]3UmU4w?3N@4]18yTMA24O9W4y9PkMF@4Odd3ybv2gsct9cyvrEceH/Qybl2gMyTMA74O9_Kx_Wf/i8n03UWW2w?j8BQ90x8yuB9zhM7joDZNQgA4:15cvq0L2ji]@57L/_Qybh2gUi3D13Ud82<i2D8ioD0i8J49618zn3_i8n03Ukm.?h8yQ98w<19etQfwO0v?18NYr|_grU8;j2JQ94xc0TgA24O9v2gwi8Cc9a;1dyvsNXkS9NAy9J2iE;h0@SF2jw;WOAf7Ug]4y3M058wYk1ioD5iof724MVZg@3A0s0,wVS0@3xMs0,y9SHUa;j8DLj2DGW8PD/Z8xs0fx8c8?18xuQfBs948e9QK4ybv2gwi8f?ky9NAwF_AM1_AwVt2hosWd8yUMAE;4w1r2gEgoDkioD_i8KQ9aw<180uB9etR13Vb6pyUf7Ug]4wXt2gEsS98xsAfxn4b?15xfpQsIt49101;i8dY93w03Uij2<j8J493x8yQgAo4wHh2gEijD0j0Z7M4y5M0@5k0w0,AVTki8J2i8;NQgA4,<113Vb6hj7Ai3JQ92xODw@Sh2ggw@01ysa3Yw512tp8xsAfxqc9?15xfpRiky9j2ggWm43?18yTQgKwE;NZKw_V/_yogAR;fvgMuwvyogAV;eDm@L/3N@]4AVTk4fAIp52dofx?8?23v2gg.@49_T/@CM_v/ioD3ioR41g18NUgAI=18yPnJKM?i8C49a;18etwfAEgAy;4ybh2g8jiDZj8Bs9219zmM5,m9RkM1TuJ33N@4]18yTowi8I5FrI0,yb5pqX?18ys58av58wvD/MY03Urr;i3D2syq_p;ezYV/_i8IRvrI<@Shyy4M7mZi8ISWXMf7Ug]4yb1m6X?18yR08i8IljHI0,y9A?1?18yMl0KM?i8A5crI0,yb1jGX?2bg1y5M7iBi8JQ942bft2O?2W2;4z7x2gg.<g<exqVf/i8fU_M@5uL/_Qib5gCX?15xt8fx6H|EG@f/UIUW1jD/ZczgnLxM?Kko2?18zhnkxM?ioD1i8I5hX<4yddjyd?18yPwNMexmVv/WiL/_@gi8R80kObn2gwi8IRGbE0,m9WAy9PU7D/Yf,y3v2gU.@4i0k0,Obh2h8i8CI_w.80193XHEfOn/MY0j8C4Nw.8018ygRyKw?i3Da3U8V1g?i8J495142FgAy;4i8J2i8;j05s94x8ySMAs4y9x2iE;i8K499w<18wQgAa05cyWMAE;4y9x2j8;i8K499;14y5gA84y9x2iU;i8d496w1i8Jc96x8wQgAu054yTooi8KY98;1cyQgAk4Gdh0s6id7Lid7EhonSi0Z4NQy9x2i:wbMAQM;1RgrE4;iEQ4xg;18et183Qb2yVgAz;8ni3Un61<i3D1K:183Qb1i8B496wfAY0fJI29x2ic;i8JQ942_1w<eyFUL/K0c<34ULLTB2go.?ibzfZRfzFpL484zTUAxFz2gg.0.48f,z1Wwh8zgghi8B49718aux8fowj<fxNk2?18yTMAk4wVv2hU3Uc50w?i8BI9720v2gw?@54fH/U2Y9d8:3UnD1<ict491]i8JI911cyuZ9etRO4KIK3N@]4ydu058etZP6ky9SHUa;i8f50kwF@KwbU/_i8n0ttV8ymMA44Ob1qaU?18yMSzK<j8D7ijD83Uaf2w?yUgAR;8n03UDV5<j8JI94x8yjRYK<j2JI90xceSMAc0@3uNk0,Q1_kz7h2ho.<4ybh2gUi8n0t2V8w_zZtOx8wY02ctbPi0@ZQbx1;at2WfM<4yoYQwfLs0FMAxzMAy9h2hoi8I5arw0,y9u318wTMA4?fx,4?18yQgAe37ihj7AiftQ95x8ykgAo6qg{]18yTMA44ybj2gUct98yvV8ysxcaup83W_6ifvTi3Jc95wfw@Af?18xs2_.<4wfhvx8yngAk4kNZAy9v2gwWPlC3NZ4?18ytFcauG@2w<4O9X@zBUv/i8n03UiI3<iof60kOdq05ceTgA80@3WgM0,Kdb3h8eSMA40@3@wM0,AVTnaZjoDFyTMA737ijiDVj0dc90xcysVcykMAaex7U/_i8Jk932bv2gsj8D@W9rx/Z8xs0fzHQc?1cyQMAa4y9MACd70tdyvRcykMA2eBO|3NZ0,ybdh6T?18yQogi8JY9518yogAA;4yb1uCS?18yogAC;4wXL2j:3Ufr;wbMAUw:fxcQ<18yNq0L2jx]@4Fg<4yb1rmS?18at18essfwYU<2V.<4m5Zw@5M;4w1j2hgi8KQ9c;18yTMAk4y9Y4wHx2iE;i3D@i0Z2_AwfgIx8ynMAk4y5OnhFwbMAV:1QnQybv2h0i8Qldoc?bV:cs3E5@3/Qybt2h0yXMAR;4xzQey3T/_i8fU_M@4Ohk0,yb1iGS?18yQMAk4y9i0zH94ybx2ig;i2K49bw;fxlc9?2gi8K49aw<18ykgAk8eY98M;2tgW0L2jz]@5n0w0,z7h2hU:eCZ_f/3NZ4?18yUMAE;4w1r2gEj8JY9218yXgAG;4w1WkwVS44fAIp5cujFLfz/MYvg018yQgAo4y5M0@5ow40,z7NL|Z5xegfxsMm?2bh2ggh8yQ98w<29MEfw0ofy0ky3Yw59yt19etQfwYU<24M0@4DLv/@D1;pwYvx}i8CI_w.8018wTMAi?fysfW/ZcyQgAieCI@L/pF18yQo8yTUoxvYfxaE2?18yMkaJg?i8C60,0,yb1vOQ?18ygnJJ<i8I5ZHg?8J068n03Umw2<i8IRVbg?eB@@L/3N@]8eY98M;13UhD4g?NUgAz:8<3FeLL/Sqgi8Kc9a;1cyTMA84ybJ2iE;wTMA4,fx9If?180mMAa4w1WkAVTk4fAIp5cujFCvv/Sof7Ug]bw1;MSoK3N@4]18ypMAE;cq498w:WnDU/Yf7M1dxs0fBc15xehR28j03UmX_L/h8yQ98w<3FOvX/QydsfZ8yQgAo4kNM4wHh2gEWn7T/ZCA4O9WAMF@Aw3l2g8i8I5_Hc0,yb3v@P?183XHGfQy9NAy3M061VL/3M18ygnuIM?i8CkYg.8018yo40.?i8I5Qbc?cp0ag58yMn5IM?yQ0oxs0fxh4e?2bx2jk;xs0fyqI4?18yTgAg8IZhaI?bE8;icu49101<_gwY0Wdbs/Z8w_z_3Uia3g?j8D_W23s/Z8wsho.?cs1rnk5sglR1nA5vMP70cta@0w<4z7x2g6.}6q9x2ge.?yMnxGw?yogA0,?bw1;pEC49.1?2b1seG?29x2g8.?K,<1CyogA3,0,ydx2g0.?i8D7i8B4923ElJX/Un0vwXSx2ge.<g@5WMs0,yb1umO<fJE0o.?xc0fx0Me?37h2gg.<4y9WkkNZKDtY/_i8IRLb8?8J@64wXj2gU3Vf22t142e0fxoAh?25_Tgyi8KI9dw<18xuQfx7gh?1@3Qy3L2iM]@50x40,m4Zw@45Lr/QkNVeAnZf/i8n0LM4<19ysx83QnUi8I6j8QcLg;19as19zggVi070ijD03UeP1<i8Q4fQMVM7cwi8D8it7Ei2Dgj3D0igZ7M4C9@4AFM4A1O4wVNQAfgIx8esEfwW_T/Z8yoU0.?i8AdYH40,yb1vKN?2bg1y5M0@41vT/Qybt2h0yPSdGg?Kww<14y9gAG;4O9n2gwicu49101<1;W0Hr/ZcyRMA84gfJFgAG;4y3@fYfxr_Y/Z4yMmHIg?hon03UiL_f/W4Tq/@beeySTv/j8Q5AnU?bBp0w?ioD1i8I5Yao0,ybeeCw1g?ioDthj7Shj7Ai8IRob4?8J664ybh2hgh8xQ9237h2gg.<4ybv2h8i8C49aw<18yUgAC;4ybr2hMi8C49cw<18yUgAA;4y9x2iU;j8DEj8BI9719ysV9yvRcavx80QgA24y9h2h8WPYf7Q?i8JS84yb1umM?18yNnmI<i8D1i2DNi87V/Yf?@6SM<4wVMD8CLSg<3EfdT/QybdrSM<fJAoExc1RLkybdKKY3N@4]18yMmxI<i8Jg24yb5oWM?18yp<g?i8I5wb<4y91n6M?18yMlWI<yQ0oxs1QFkybt2h0yPQgG<Kww<18NUgA4,<4<3ECJD/Qy3@fYfxnH/_@bfkGM?25_M@4rf/_@zJSf/yPzElJP/QOd1j5Z?2Vhw80,yd5hpZ?19ys58yMm9Fg?i8QRuE80,ybe370W9zq/_Fbv/_MYv,C9M4y3M05cyuZ8yPnDHM?ioD1j8JI9711wu3/MY.o7x/Yf,MXt2gU3Uhi0M?i8Jc94x83XHLfSp6yrh601<4G9zcU,2?iECYNw.8018ygmkHM?icu49b+i3D23Ue0Zv/i8Je28J@68n_3UhM3g?i8I5qqY0,y9xw01?18yMlrHM?i8A5jaY0,yb1lmL?2bg1y5M0@4FMQ0,ybt2h0yPTDFw?Kww<18NUgA4,<4<3Estz/Qy3@fYfx9gh?18NUgAI=18yPkcHM?Wg3R/Yf7U]Kw8<18zjkkv<ysvEdtz/Qy3@fYfxjzX/@b3umK?25Og@4aLL/@y8R/_yPzEYtH/QOd1ulX?2V8.0,yd5r5X?19ys58yMkAF<i8QR5o40,ybe370W3fp/_FW_H/Qyd5mBX?2@g;4O9ZP70W4zo/Z8yTgAg8KY9dg<18oZ3EJdv/Qy3@fYfxrrK/@b5miK?25Qw@4GeX/@w7R/_yPzEsdH/QOd1i1X?2VHw80,yd5j1X?19ys58yMmzEM?i8QRB8<4ybe370Wbbo/_FquX/MYvh<i8IR2qU0,ybl2ggj8D03NY0{]1CpyUf7Ug]4C9Mky3M051wu7/MY0hw@Tz4U,<j07ai3D1tu54yVMAR;4y9l2gghonr3UAz2w?ibH||_vQy9@2n/MY0i2ekNw.8018ylgAieD_Zf/j2D9WmXX/Z8yPm0Hg?Kw4<18yMV8yMlxHg?i2D8u2kNQAybz2jE;iftQ9518esx83Qv1i8D2i8n0K,<183Qjgi3Bk93wfwygd?18eRgAe0@3CwI0,ybx2iE;ict497w:NUgAz:8<18wY03i3C498:fwKLP/Z8yQgAe4ydf12U.<4zhXQwfhfx8ynMAe4y9@AzTSAyb1tiI?18yoog.?i8I5PGM0,y9A0w1?18NUgAw=3FDLf/QybJ2io;i2KQ9cw<18evxO4P7iifvTct98ys58yv18Z_58ysp8yQgAk4wVY0@3ufr/Qydi058QuDFQvn/M@Tj2gUpAa9z4o,<i8Jc94xayoPe010w,y5_M@9HvP/@Cw_f/i8JQ942bfuyz?2W2;4i8B2iE;j8Bs9218NUgA4,<4<3Eptn/QObn2gwh0@SB2iE;i8fU_M@56Lv/Qib3gqI?15xsAfx0HT/_EGdj/UIUW17o/ZczgnIu<Kko2?19ys58yMlbEg?i8IUi8QlN7w0,yddj9@<NMexjRL/j8Js92143Xqk9aw<3FLvr/Qybt2h0LMo<18yoMAE;4i8B2i8;j8Bs923ELdj/Xw3;NebXZVgA6,0,yUP_tjUWmrN218Z@9cyRMA84gfJFgAy;4xFJ2gg.0.48f,ybz2iw;ic7G14w1RAwHJ2iM;i3KQ9dw;fwJ7I/Z8ypMAE;4ybdhGH?36x2i8:4z7x2iM=eADX/_i8I5@GE?cq06,<7F0Lz/Sof7Qg0,ybh2g8j8DFyTMA737ij2DVj8QI0kO9XKz3RL/i8Jk932bv2gsj8D@W1bl/Z8xs0fzF85?1cymMA24Cd70tdyvRceTgA80@26vf/Sqgj8DEj2DUi0d490x8ykgA84S5ZDlZi8Jk923Frfr/V1cyux8yTMA84ybt2hgj2DUi0d490x8ykgA84AV_Dcgi3JI911P2kAVTg@36gg0,S5ZDk@WXZCbwYvx}i8Jg84yb1imG?18at18fv/3M1SrAyb1hKG?2bg1y5M0@5a,?bZA;W7Xm/Z8yMn_Gg?3Xpga8jitrZ8yN3HLCoK3N@4]18yT0wi8I5RqA0,yb5sqF?18ys58av58wvD/MY03Upr.?i3D2syq_p;ewIRL/i8I5HqA<@Sk2y4QDmZi8IMWXMf7Ug]4yb1p6F?18yR08i8IlvGA0,y9A?1?18yMlMGg?i8A5oqA0,yb1mGF?2bg1y5M7iBi8JQ942bfg2x?2W2;4z7x2gg.<g<eyaQL/i8fU_M@5uL/_Qib3jCF?15xsAfx6H|ESZ7/UIUW4jl/Zczgkvtw?Kko2?18zhk4tw?ioD1i8I5tVU0,yddmxX?18yPwNMey6Q/_WiL/_@gi8JQ942bfomw?2W2;4z7x2gg.<g<ewfQL/i8fU_M@5HvX/Qib5rWE?15xt8fx9T@/_Eod7/UIUWcDk/ZczgmAtg?KgY4?18zhm9tg?ioD1i8I5_9Q0,ydduRW?18yPwNMewbQ/_WlX@/ZC3NZ4?18yTMAi4y9NAObn2gwi8DVi0@WWjZceTgAe4wfhcZ8wY01wur/MY0i8D7i8A5bGw0,C9O4yb3iOE?21V/_3M1Ch8CQsg.?1cypPV010w,O9xf4,2?i3D2sAxd0vhceSgA40@3t_T/Qybh2gwi8B494zFY@/_MYv,ybv2hwi0D73Uj2Y/_i8Jc9618esx83Qb1i8D7Wg7M/ZC3NZ4?18yTA8yT4oxvofxaA<18yMmyFM?i8C10,0,yb1piD?18ygm5FM?i8I5zGs?8J068n03UhX|i8JQ942bfi2v?2W2;4z7x2gg.<g<eyGQf/i8fU_M@5kf/_Qib1lCD?15xs0fx43|E@Y/_UIUW6jj/Zczgk_t<Kko2?18zhkAt<ioD1i8I5BVM0,yddoxV?18yPwNMeyCQv/Wg7/_@gi8n_Lw4<19ys183Qj@i8INj8QcLg;19av19zjgVi07SijDM3UaP;j2D8i3D23Uf7_L/i8C10,0,y91r6C?18yMmWFw?yQ0oxs0fxav@/Z8yTgAg8IZj9U?bE8;icu49101<1;Wdrf/Z8w_z_3UlY_L/yPS6Fw?xvYfx6X@/_Eas/_UIUW9bi/ZczglJsM?KlA2?18zhlisM?ioD1i8I5NpI0,yddrpU?18yPwNMezkQf/Wi_@/Yf7U]ioDSWibY/Z8zjg_j3D63Ud3|i8D6it7Ei2Dmj3D6igZ7Y4C9@4AFY4A>4wVZQAfgI3F7L/_UIl@ak?8ni3UhEYL/W9Le/@beew4QL/j8Q54Dc?bAx1<i8QlN780,C9Mkyb1jur?18zjkEu<i8IUcs3EhJ3/@AFYL/i8JQ942bfkqt?2W2;4z7x2gg.<g<ezgPL/i8fU_M@5Nf7/UIRwak?8nS3UiSYv/W2fe/@beeycQv/j8Q5pT8?bAv1<i8Qlj780,C9Mkyb1r@q?18zjmMtM?i8IUcs3EPI/_@BTYv/i8JY933EfZ3/QC9N@CZVf/i8Doi8JY9218yTgAk4C9TkMF@4w3h2g8i8B4923FD_H/Qybh2gEi8Rc3g58zkg50ky9h2gEi3D63Ud40w?i8n93UlDY/_i8Bc9119ytTFReL/Qyb1seA?2bi1x8yNmNF<i3AlEGg?8Cc98w;fwyk2?2bg1y5M0@5Mwg0,y3L2jo]@8rg80,ibD2i8;honr3Uhs0w?i8eY9b]3UiT0M?i8JQ942_1w<eykPv/j8Kk9dw<18yVgA6,?37Sjonit5J8Ks_Tk@eBCYgwic7G0QxFL2gg.0.48f,y9Q4zTUkz1Wwh80vF8yXMAI;4y9Q4wF@4MVQ7cxiiDiLCg<19zggWi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY9229YHU2;W37f/@5M0@e7g4?fq490o1<13UnD0w?ZEgA3w4<4fx,1?18yMmKEM?i8DFNE0o.<st49101;WsPM/Z8yPmgEM?i8J624wXx2j:3U8u1<i8Daj8D7i3Dn3UfvWL/i8IRqac?eCMZv/i3B496wfwJzF/Z8yUgAW;4zhp2gUi8Jc93x8es583Qf8K08;fgEgAz;4y9j2gUifvpyogAz;4yb1hiz?18yoog.?i8I53Gc0,y9y0w1?18NQgAq:3FuuD/QObt2h8yTMA737ijoDZj8DSWdLe/Z8yRgAc8JY91NcyvXEaIT/P7ij8BQ90x8yPSQEw?i8n0i0Z8MACd70vFg@H/UdY91023UlT0M?NQgA408<3FlKj/QC9TkkNZAkNVeAfVL/h0@SJ2i8;WmzC/Z8yT08xsAfxl83?2bi1y5Og@5hMc0,y5ZHA1;i8IUj8I5hW80,wfhf58yt58avBczgOR:4Cdf3580vZ8evAfwG43?1casF9et0fwKI4?2bg1y5M0@5hw80,z7x2iM=bVA;WhX@/Z8xsC_.<4Ob1AwfhcZ8ystcastczgOd:4Sd10Bd0s1cessfwLc2?1casx8NUgAI=18es8fwXPD/Z8yoo0.?i8A5Fq40,yb1qWx?2bg1y5M0@5Agg0,ybdpOx?3FAev/Qz7h2hU:cu498M;2;WmrE/Z8yTgAgbY6;i8Bc923EEIH/XY3;i8Jc9218Kc_Tk@eBCYgwNeb3ZVgA6,0,zTUAxFJ2gg.0.48f,z1Wwh8zggmi2K49b;18yPkCEg?i3DE3UatXL/i8J49518yTMAi4i8t2gwi8JI9718yogAG;4ybx2io;i8C49cw<18yUgAA;4y9x2iU;WsfL/Z8yTgAg8IZspw?bE8;W1_b/_Sx2ge.<g@44fX/@D/f/i8JQ942_1w<eztOv/K0c<34ULLTB2go.?ibzfZRfzFpL484zTUAxFz2gg.0.48f,z1Wwh8zgghi8C49b;3F_vL/UIJqG<8nJ3UgFWL/W0T9/@beexSPf/j8Q59CQ?bCh0M?i8QldCQ0,C9Mkyb1qCl?18zjmqsw?i8IUcs3EKcH/@DGWv/3NY0i8Dhifvpi8I50W<4y9xx01?18yMnZDM?i8C82,0,y9l2gUict497w:NUgAz:8<3FMer/Qybt2h0yPRRBM?Kww<18NUgA4,<4<3E_Yz/Qy3@fYfxhfX/@b1q@v?25M0@41vL/@xiOf/yPzEKYL/QOd1ppI?2VUg80,yd5nJI?19ys58yMnKB<i8QRTT40,ybe370WfT9/_FNLH/QybdAy9OAwVPDcri8KY9c;18av58evB83Qvfi3D83Ubo;j8D7WrHX/_7h2gg:4y9WuBnXf/i8Il4VY0,y9A?1?18yMk5DM?i8A5ZFU0,yb1v@u?2bg1y5M0@5Yg<4yb1uSu?3Fg_H/QOd10B9evwfwMfZ/Z9ys18QuZ9at19evxc3Qv7i8Dfj2D7i077j3D1i0Z2N@Du_f/ijDth8yQ98w<113Vb6hj7AWi3y/Z5cvp5cujF5ub/Qydf3p8esYfwRnY/Z8ytt8QuBcast8esZ83QvVi8DNi2DVi07hi3D@i0Z2QuAM_f/i8JY9418as6@g;370i8Ql9CI0,y9PuwcOf/i8JQ942bL2jk;i6fgW7z7/Z8w_z_3Uic.?i8I57VU0,w3r2hgi8BE24yb5guu?18yPTUDg?WoLW/Z8yTgAg8IZE9k?bE8;icu49101<1;W2H7/Z8w_z_3UnA_L/yMnqDg?xs0fxdr@/_Evsr/UIUWer9/Zczgn1qw?Kko2?18zhmCqw?ioD1i8I56pc0,yddgFM?18yPwNMewEOf/Wpv@/@bdoSt?25Zw@4nKX/@wMNL/yPzECsD/QOd1nhG?2Vhw80,yd5lBG?19ys58yMncAw?i8QRLmY0,ybe370WdL7/_F7@X/Qy9A?1?18yhkwDg?i8I5apQ?8J068n03Ung;i8I55VQ?eDF@L/i8JQ942bfq@k?2W2;4z7x2gg.<g<ewVNL/i8fU_M@5OeT/UIdWpM?8n93UiWXv/W8P5/@beezROf/j8Q5Q6A?bBp0w?i8QlJmA0,C9Mkyb1iyi?18zjkprM?i8IUcs3EdYv/@BXXv/wPSrD:@4p_X/@x0Nv/yPzEGsz/QOd1lBF?2VNMc0,yd5mBF?19ys58yMnsAg?i8QRPmU0,ybe370WeL6/_FafX/Qybt2h0yPTHAM?Kww<18NUgA4,<4<3Etsn/Qy9MAyb1ies?18w_H_3UnM@v/wPQqD:@4U_D/@y_Nf/yPzEacz/QOd1gdF?2Vmg80,yd5uxE?19ys58yMlrAg?i8QRj6U0,ybe370W6H6/_FH_X/MYvh<glt1lAC9RA5lglhlkQy3X1y9v2g4LM<g18yngA2eyYNv/ioD7jonSt7V5cujH5wYvw:3EgYj/UcU17lEjjDQsSd8yQgA24O9YEJY90hcyvVcau9azgMwK;g18es983QvgWfb6/Z9ysl8xs1UMDgOi8D3j8DZpF18ytF8yuW_.<ey0Nf/i8n0u0J8asdQ9Aw1NuLxAezrM/_wPw4tdp8wYgoj8D_mRR1n45tglV1n@CMM/_jg7IWnH/_Yf7Ug]8f_0DYbK,<333NZ4?11lXEa;glp1lk5kloDZkQy9YQy1X3w4?18yTU8cvrEKIn/QybuN2W2w<37SykgA6eyCNv/NQgA3:29h2gsw_Q3t1N8yTIoi8QRX6s?ewlNv/xs0fBc0fJI29h2gci8I5uFE0,y5M7g4NA0E0kydh2h0hj7_i8RI9315cuR8NQgAa:18ykgA46pCbwYvx}yTMA6bE01<i8DKW8_4/Z8xs0fzI8<18Muw4xs1@TERo_QC9XAz1UMh80RMA4eIn3NZ4?19eskfwHs<19wYogijDutbp9yMpceuxRVAQ3rwxdxvZR8KIB3NY0joJD44O9_QSbrMxcymgAaexXML/jonAt0xdyutdeiZQTAyb1r@p?18xs1Q14O9q22bh2gcxs1Ra4O9WAyb1qip?18Kg3M|/Z_wub/MY0i2ecQ0.8?fxpU<1cyTMAaeBR|3NZ0,O9_QSbvN3E5cb/QS5_TnLi874e.?370mRR1n45tglV1nYcf7M2_6;exuM/_i8D1ioI6i8A1ioJm24w>Ay9kgx8zlgAa4S5_TkJWP0f7Ug]6pCbwYvx}{]19zlsgjoJ_44S5_Tg5ijA7sKVcynAgi8AaWmj/_ZCA8JY9>NQHU3;W632/ZcyTMAaeD7_L/pwYvh<w_Y2vMKU.<ccf7Qg0,5nKwE<11lAkNZA5lglhlkQy9YQy1X2w4?18yTU8cvp8zmMA84Odr2gMW7_3/Z8yTIgKwE;NZEB490zEqYf/Qz7h2go:8B490Mf7M1CpyUf7Ug]8JY90yW0.0,y9XKyvML/i8n03UXS;ic7E18n0vJWdmfZ9yuN8Muc4j07HWNkf7U]ijD6sCd9wYggijDstbF9yMgAj3DMtuB8yTMA64Q3t2g8i8n_thPH7QObvN1cyTs8j8BY91zEzI3/QS5_Tg8j8D_j3ATte5cyv58wu40Yf/vHabv2gccta@0M<ex5Mv/WW0f7M2_6;ez6Mv/ioIk94ydj2goi8D6i8AgioJ490x80t18yko8i8J491x8xs1RbKINpwYvx}{]1CpyUf7Ug]4ydi118yQ.i8n0t0l8eh1OXAy9hx18yj7Fb|Sqgi874a.?370mRR1n45tglV1nYeg{]23_M9_1Hw1;MRmW2w<4y9Vk5nglp1lk5kkQy9YQy1X7y2?18yTU8cvrEXI7/QybmN18zjkvpM?ykgA54y9T@xDMv/i8RQ952_.<469NezlML/NAgA8025M7kjyQgAq2k0Y<fg2;fB4gA84m5V0@4Tg80,ydh2h0hj70ict493]j8SA9e;18ykgA86qgi8JQ922bv2gkKx;1cykgAaez8Mf/j8J492x8w_wg3Um20w?j8JQ931cekgAg7hHLNw<1cykgAaexuMf/j8J492x8ys58yQgAg4y90kybl2h8i072jonSi8Bh24ydl2gMtinHa6pCbwYvx}{]19zlogjoJS44S5ZDg5ijA6sKVcyn4gi8AaWmb/_Z8ytC@0,?370j8B492xczqMAs,0,yd5iFz?1cyu_Ezb/_P7Scs1cyu_Ecc7/QObh2gExs11yssfymo1?1c0QgAi4S5ZDkNWh7/_@gjoJ624Sbvx1cyvtcykgAa4O9v2gMW2q@/ZdxvZcyQgAa0@4WfX/QS9_AQV1w@5TfX/Qy9Skyd5rxy?1cyuYNMbU0.?W1e/_YNZAO9XP70Wbv0/Z1ysu5M7ywict493w:j8DCysvEbs7/Un0tgR8yUMA4,0,y5OnYlh8D_W3i/_Zcyu_EPbT/@BD|i8J493x8es5@Ukydt2gUi8BQ92x8yRgAa4wFMki9_HY1;WbW/_Z8xs1U6kybz2gg.?i8J493x8es5_ReKF3NZ4?3EqXT/UI0w_w4tdKdkeG3UKZQ48fU2g@kMEfUm0@kM0z2t818yTgAe37ih8D_W7T0/Z8zogAs080,y9h2goWNxC3NZ4?18yTgA64y9MHY1;WaqZ/Z8yTgA6bE0w<h8D_Wai@/Z8xs1_R@AK|ict493w:j8DCysvEdY3/QObh2gExs1R4kybx2gg.?i8n03UZ10M?h8D_j8B492zEcbX/QO9X@z8Lf/j8J492zFjLX/Sof7Qg0,O9_QSbvOzEDbT/QS5_TnLi874u88?370mQ5sglR1nA5vnsd8zogAs080,kN_P7ricu49e+i8B491x8zogAC080,y9h2g83N@4]18yTgA68JY91iW?E?eztLv/i8n0vFN8LITcPcPcPcPcifvCic7G1onivJd8yTgA28R2_QObp2goi8Q4w4yd1cp8ykgAa4AV72gfxgE1<f7Q?{]19yTgA64Cbl2gwgoJY9118yrgAs,?81Y92?3UhK.?i8DhyvV8zpgAs,?bY1;WeuZ/Z9yQMA646bv2ggLwc<18ysF90QMA84y1Uw3M/Z8at7EorP/QA3n2g8jon_tnjHtMYvh<ioJ764ydB2hM.?LM4<18yogAs,0,CbjO11yTsgW8GZ/Z9yQYogoJ_4bU3;i8Daigdf84y1Uw3M/Z8at7E1XP/QSbtOxcyvZ90RY8j8CQ9e;3E7XP/QS5Zw@4pw40,S9ZQAV7Tieiof4a4MXp2gE3UiL_L/ijAs90@41v/_XYM;W4KY/_4MnVL12h8ys75_DY0ioJ49218yk4wjon_3UgP.?ioIk94ydx2jw;WOIf7Ug]6pCbwYvx}{]19zksEjoJ_a4S5_Tg5ijAnsKVcynAEi8A8j8KY9e;35@7t9wYgEj3JA92wfxmX|F6fX/MYvx}WdLR/Z9yQMA646bv2ggLwc<18ysF90QMA84y1Uw3M/Z8at7E1rL/QA3n2g8jon_tmvF6f/_Sof7Qg0,CbtNx8yrgAs,0,CblO11yTYgW8vR/Z9yQYogoJ_4bU3;i8Daigdf84y1Uw3M/Z8at7EJbH/QSbrOxcyvZ90RY8j8CI9e;3EPbH/QS5XngnjoDLijAvt9_FHfX/SoK3N@4]15cvZ9wYgEj3JA92wfxp_@/_FivT/Qydx2jw;WvX@/Z8yRgAe4wVQ0@eIvP/Qydt2gUi8BQ92x8at18yRgAa4i9_HY1;i8D1j8B491zExXL/QObh2goi8n0u1R8yUgA4,0,ybl2gUi3DgvYvFqvP/Sof7Qg?ewHKv/j8J491yb08fU17jizl3Gw@bLt1i3@0AfBca3@5wfBc08Mw@4dLP/Qybt2gUct94yvZcykgAaewLLf/i8S49702?1cyQgAa4y9h2goWNN8yTgA64y9MHY1;j8B492zElbD/QObh2gEi8JQ91yW08<4i9_QO9h2gEW4yW/ZcyQgAa4y5M7_3WsPX/ZC3N@4]23_M4fzJs2?11lXEa;glp1lkkNXk5klky9Zle9@Qy1Xaw1?18yTU8cvrEDHH/Q69N8fX0M@4yw8?ewJL/_i8QZYRM0,z1W0d8zpz/NY0K:98wuc?e3_i3D3i0Z7Sbw?2?i3D3i0Z2Sey7KL/i8n0t1uW2w<37Si8D7W4eW/Z8ysl8xs1_1rS:i8RY933E_bH/Qz7h2gg;28n0tjr5@mYdpSc?37iNvBKx2io;Ne9VfY75@nX0i0@Lh2hgifvRKw;x8et183Qfgi8Bk9118zrgA4,0,i9X@zFKL/xs1R5UK492w1<B0f<3Q0w<3Uju.0.rA5;ioDocsB4yu8NZAi9X@ySJ/_ioD7i8n03Uza;Lg;11Lw;5Rcmqg{]11Kgk<19ytwNOki9Uz7Sh8DLW7yT/Z9yst8xs0fzFQ<2bfvW5?25_M@9Pw<4M1_kAVXDf6i8SY9a;3E2rH/UD1xs1RkYnVrMRXow?i8JQ9135@mW490w1?34UDA_MsnVvI183W@49cw<18ev1P9Ayb1gue?18xs1Q6w@Sg2y4M0@5eMs<Yv06pCbwYvx}io76:uBk|3NZ?eybJL/ioD6wPwm3Ug41w?yPRtxg?xvZV5j70i874G,?5JtglN1nk5ugl_3A4ydJ2iw;Kww<18NUgAE:4<3EQHr/@Lbi8SQ9a;2W2;4z7x2iw:g<eyOJL/i8fU_M@52L/_UIloEQ?8ni3UjY_L/W0mS/@beexKKv/j8Q5RRY?bA11w?i8QlbBE0,C9Mkyb1q62?18zjminM?i8IUcs3EIbv/@CZ_L/3NY0i8JZ4bEa;cvrE@bv/Q69NuBu_v/K,<33pyUf7Ug]4ybB2h0.?i8RQ92x5cvYNM4z7h2gw:4z7h2g8:ky9d2h8xt8fzL3@/Yf7Q?{]18yt58ytR8ykgAa4wFMkwVSkwfhKB8xuQfx7E1?15cvp9yux8yPgAhj79csBdav14yu94yu_Etrr/Qy5M0@83,<@4cw40,A1NAAVXDbfi8J4921C3N@4]1d0vubft@3?1c0v18ykgA88n_3UAT.?i8Kk9401?18es8fzBv@/ZcenMA20@3q|QydH2iw;i8DLWcKT/@9MEn0tkn5@mYdfm<4ybx2j8;NvBKx2g8.?Ne9VfY74MnB@NAAfHYp8eQgA47cni8I5O8I0,y5M7gb3Xp0a8j0tiIf7M18wkgA2:58yQgA84ybB2h0.?Wvn@/Yf7Qg?87W42s?7joLSg<29l2goWfGT/Z8yu_EgHv/UJk91x8yUgAO;8f20kAfHYp8eQgA47b8WWpC3NZ4?3E2Xj/UI0w_w43UjJ_L/w_xv3Vj2w_wC3Vj12cFR38fw@UfU4w@5Gw<4ybh2gwjonS3Unm_L/i8Kk9401?18yt58as58xsAfzUY<15cvrFKLX/MYvw:18zrgAE;bE8;icu49a:1;W2aQ/Z8w_z_t0N8yQgA8eCr_L/pF2bfsGa?25_TjGW76P/@beezqJL/j8Q5gRQ?bD41g?i8QlCBs0,C9Mkyb1gS<18zjn@n<i8IUcs3E7bn/@KKK,<3FLvP/QwVMw@eGfP/Qydh2gwj8JQ90x8yggAjjD@3U9E.?i8Ik94y9Ski9XAi9V@wKJv/i8D5i8n0u2VQdEIZRE4?8n_3UDS.?ig7Li8J49218eogAg,?7@XWl3Y/Yf7U]WceO/@3e0hQSQybx2h0.?i8Jk921cyngA24wVMw@d9fP/Qydv2gEW1CQ/@5M0@54LP/UJY92OW<g0bU71<W4WR/Z8zogAE;4y9h2goi8K49401?18ekgA80@dCM<4ybr2g8i8Bs90wf7Q?j3DZ3U8D1<j8J490ybl2gIcsB4yuZ8yPgAgrA5;W7GO/Z8ysd8xs1@nQkNZwYvg01CpyUf7Ug]4C9S8JY92wNOj7SjiDMgrA5;h8DyW4iO/Z8xs1@24A1NAAVTDbnyPT9w<xvYfyks3?18yQgA84Q1ZQwVx2h0.?3UZP|yTMAaewGI/_yTMAbewxI/_WiTX/Yf7Q?i8SI9a;18yu_EGbj/UD2xs0fxoU<35@mYd5BQ0,ybx2j8;NvBKx2g8.?Ne9VfY75@nX1i0@LMkwXh2ggsS58yMmyy<i8n0t5kfJA0Exc1QjuI8wvEg9M?t4e_p;8Bk91x8ykMA2ezMJf/i8DLW3yQ/@bl2goi8Jc90x8yUgAO;8f20kwfHY58eQgA47a@pwYvx}io76:uDA_v/3NZ0,ydJ2iw;Kww<18NUgAE:4<3EoH7/Qy3@fYfxubZ/@bdha8?25Zw@4RfT/@yRIf/yPzE7Hj/QOd1otq?2VSgk0,yd5tVk?19ys58yMlhvg?i8QRgBE0,ybe370W62O/_FBvT/Qydv2gEWf6N/@5M0@8b_T/UJY92OW<g0bU71<cs0NXuwyI/_i8S49a;18NMgA:ky9h2g8pF1CpyUf7Ug]8Jk92N1Kgk<19ytwNOj7Sh8DLW6uM/Z9yst8xs0fzAz@/@bv2gEcsANZA6V1g<4C9M4i9UKx2If/i8n03UUC_L/yPTbvw?xvYfytI<1c0vR8eiMAsW98yTMA2ezoIL/xs1RhcnVrMRcmM?NvBKx2g8.?Ne9VfY75@nX1i0@Lz2j8;i3Jc911P6Ayb3tK6?18xsBQ3w@Siiy4Og@5Zw4?6qgi8449:7Fg|Qi9b2h9yvlcyngA2cj1unX6i8Bs91y9O@IhpwYvx}wvIg9M?t2K_p;8f30uzXIL/i8SY9a;3EfHb/Qybx2j8;ig@LNAMVW7bdh8II94Obt2g8i8Js91zFqLz/SoK3N@4]18yTgA2bE8;icu49a:1;W7mL/Z8w_z_3Uk0|yMkBxw?xs0fxfb@/Z1yPXEdrb/QOd1pVo?2V70o0,yd5vli?19ys58yMlEuM?i8QRmlw0,ybe370W7uM/_FJ_X/Qybt2goKww<18NUgAE:4<3E1W/_Qy3@fYfxpjY/@b3ru5?25Og@4xLP/@xqHL/yPzEMX7/QOd1iNo?2VZMk0,yd5odi?19ys58yMnSuw?i8QRVRs0,ybe370W0mM/_Fh_P/Qybv2goW2qN/Z1ysq5M7l1NvBL3ptp?18yUgAO;cnVrEgA2,?cjyuj_1NvB@MQwfHYd8eQgA47cki8I58Uk0,y5M7g83Xp0a8j0thl8wsk;1WnLX/Z1wvUg9M?teK_p;463Nw7EqX7/Qybv2goWb6M/Z8yUgAO;4wfHYd8eQgA47bcWXV8ylMA6cj1unX7ysfH287X42s?7gGLSg<23MM7Ear7/Qybv2g8W6@M/Z8yUgAO;4AfHYt8eQgA47bei8Js91zFMLT/Sqgw_Y3vMKU.<ccf7Qg0,5nKwE<11lA5lglhlkQy9YQy1Xdw0.18yTU8cvpczqMAQ;ex4H/_i8JX437SKwE<11ysrEcq/_QybuNwNZHEa;ykgA6ewtH/_i8D5ykgA7eyNI/_ymMAa4z1W0f7h2gI.<4ydCf/7M2U:Ay1UM?UfZ8esd83QvoK<8018esd83Qboi8R49415cuh8ykgA44w1SQybt2ggh8DTWcWL/@5M0@81w40,Obv2hMioQI74AVXM@2LM<4ydh2gMi8B490x8zoQ?f/Kw<g1cyuV4yvvE8W/_Qy5M7VCi8D2LwE<1cyu_E7G/_Qy5M7hhj2DEi8JQ90ybv2goKx;18zqM5.3/QO9p2gMi8DEj2Dwi8B493zEyWP/Qy3@11Qgbw1;i874S?105JtglN1nk5ugl_3pwYvh<i8JQ90ybv2goKx;1cymgAc4y9n2gUW4KI/Z8w_wgts19yuN8ziMHijDL3Udb|i8RY92yWp;bU1;W36K/@5M0@e_LX/UJY91OW2;4ydt2gMW1qJ/_FVLX/V0NMeBV|pwYvx}kXI1;i8fI84ydt2gsWfOJ/Z8ys98wPw0t1ybv2gsi8D6i8B490zEgHj/Qybl2g8ysd8ytvE8WP/Qy3N229S5L3{]1jKM4<18w@Mwi8RQ91PEHaT/Qy9MAy3e01Q68JY91N8ysp8ykgA2ey2Mf/i8Jk90y9MQy9R@zjG/_i8f488DomYdCpyUf7Ug]5eX.<4y3X118zngA3exsHv/i8cU07gli8IlVU40,y5QDg7NE8o.<j7ri8D7W8CH/Z8wYggytxrMV1jKM4<18w@Mwi8RQ91PE7aT/Qy9MAy3e01Q68JY91N8ysp8ykgA2eyyVL/i8Jk90y9MQy9R@x3G/_i8f488DomYdCpyUf7Ug]45nglp1l5mZ.<5d8wuP:i8RQ91PEMGP/Qy9MQy3e?fx8s1?2br2gsw_Q13UX8.?i8JU2bEa;cvp1Lf|_E8GP/QC9NUfZ0w@5Jw40,ydfp1e?3EeGP/Qydfpde?18ysnEaWP/Qy5Xg@4cw40,y5M0@4ag4?bEa;cvp8yuZ8ykgA2eyRGL/i8JY90yW2w<37Si8B4923EDWH/Qy9h2gEhon_3UZN.?honA3UXE;i8QZenk?ewsG/_i8D5h3Kw]@5L,?8eU4:4fxu41?18zjQpjw?WaeH/Z8xs0fxaE<2W2w<37Si8D7W5KH/@W.<37Sh8DDioD7W4CI/Z8ysl8w_z_3Uio;i8QZPng?eyMGL/i8DGi8RQ9314yv_5@mZ49214ymgAgct494g:NvB_h2gMi8K02;4wFMIjx@mX8NefN8I81Kyw<35@DZ494zEdWD/Qy3@fYfxbA1?18zjRKt<W56G/Z8yqw8;pyUf7Ug]37Ji8DvW7qF/Z8wsj:yuxrnk5sglV1nYeb3qV_?25OngGW5mE/@beey@G/_i8Il1Tk0,yddmxi?18yPF8ys8NMewjGL/3NY0Lg4<3HGSof7Ug]4ybuN2W2w<37SW52G/Z1ysjFcLX/MYvx}i8RQ922W4;4i9_@x@Gf/i8fU_M@5s_X/UIRbDY?8nS3UhB_L/Wd6D/@beewWG/_j8Q5MR4?bDk1<i8Ql@AI0,C9Mkyb1mRQ?18zjlukg?i8IUcs3EvaD/@AC_L/3N@]4i9VQydt2gMh8Cw:ezcGL/xs1R48J494wB0f<3Q0w<t7n7xh:2;i8RQ922W4;4i9V@zsF/_i8fU_M@5MLX/UI5z7U?8n03UiQ_L/W2@D/YNXoIUW9qG/Zczgmnkg?Kvg4?18zhlmiM?ioD1i8I5Onc0,yddrFg?18yPwNMezoGf/Wnn@/_7xh:1;WqnZ/@b5iV@?25Qw@4evX/@zhFL/yPzEeGH/QOd1hJh?2VY.0,yd5vFa?19ys58yMlJsM?i8QRnB<4ybe370W7OE/_F@LT/MYvw:1jKM4<18w@Mwi8RQ91PEbaD/Qy9MAy3e01Q68JY91N8ysp8ykgA2ey2VL/i8Jk90y9MQy9R@xjF/_i8f488DomYdCpyUf7Ug]5eX.<4y3X218zngA7ezsGf/i8D2i8cU07goyTMA74y9NAy9h2g8W8bJ/Z8yRgA28D3i8DnW0eD/Z8wYgwytxrMSpCbwYvx}lrQ1;kQy3X1x8zngA1eybGf/i8D3i8cU07gJwTMA105_eUIZGng0,ydt2g8Kww<18NQgA2,<3Efqr/Qy3@fZQbP7Ji8DvW9SC/Z8wYgoyuxrnscf7Q?i8JU2bEa;cvrEMav/UD7WXsf7Q?yMn2v<xs1QN@xFFv/cuSbeezgGf/j8Q5i4E?bAX1w?i8QlA4A0,C9Mkyb1gdO?18zjnQjw?i8IUcs3E4Gv/@KbkXI1;i8fI84ydt2gsWcOD/Z8ys98wPw0t1ybv2gsi8D6i8B490zEMLv/Qybl2g8ysd8ytvEYWn/Qy3N229S5L3{]11lQ5mgll1l5ljKM4<18w@Noi8RQ92jEsWv/QC9NQy3e01Q2oJI92i3_gl_8kO9_@yFFv/i8f4m8DomRR1n45tglV1nYcf7Ug]4ybu0yW2w<37SgrX|_WbGC/Z9yTYgKwE;NZEB491jEFGr/QCbvNyW2w<37SykgA4eyiFL/ioJ_8bEa;cvq9M@y0FL/ioJ_abEa;cvq9h2goW6OC/@9h2gsw_Q63Ukf0w?3NZ?6pCbwYvx}honSu1J8zngAebE1;h8DTW9CB/Z8xs0fzJ01?18zmMAg8JY91iW4;4y9XKxWFv/i8fU40@5I,0,ybh2h0cvqW0w<8Dvi8B492zE@ar/QObh2h8yTMA48Dqhj79i8Rc9318zngAa4y9h2gMWeqA/Z8xs0fydQ<2bv2goi8RQ93yW2;4z7h2gU.<ew1Ff/i8fU_ThHyTMA7bEg;i8DKWeGz/Z8w_z_3Ul0|yMmquw?xs0fx3b|Efqf/UIUWaqC/Zczgnfjg?KgE7?18zhlChM?ioD1i8I5SmY0,yddsFc?18yPwNMezEFf/Wvf@/Yf7M2b5kFW?25QDibWf6y/@beexqFL/j8Q5Vks?bA9>?i8Ql6As0,C9Mkyb1oRL?18zjl@j<i8IUcs3EDaj/@Bc|3N@]bY<40W0qA/Z8yTgAg8JY910NQAy9h2g8Wd6B/@W0w<37Syt_EMWn/Qybl2h8i8nit4x5cuRC3NZ4?1cauGU<1,ybt2g8yTMA44wVMAC9R4Mfh@1cyu9d0unEWGf/Qybt2g8j8Dyyt_EOWb/Qybl2h8ijDlsI58yTMA2ewDE/_Wpn@/ZCA37rWmzZ/ZC3N@4]19yTYMKwE;NZKx0Ff/goD6WuzZ/Yf7Ug]5eX.<4y3X218zngA7eycFf/i8D2i8cU07goyTMA74y9NAy9h2g8W4bw/Z8yRgA28D3i8DnWbey/Z8wYgwytxrMSpCbwYvx}glplLg4<1ji8fIc4ydt2gcW3CA/Z8ysd8wPw0t4m3v2gc0nVSi8QZAko0,Obs0zEeqD/Un0u4l8zmMA48D1Ly:NM4y9XQyd5gt5?3Emab/Qy9XAO9ZP7JWdKB/Z8yt_EcWb/Qy3N329W5JtglX33N@4]3E6W7/UIUW8iA/Z8zjQWhw?i8D6cs3EcW7/XQ1;WY6g{]1ji8fI84ydt2gsW96z/Z8ys58wPw0t6y3v2gs0nVxi8JU2bEa;cvp8ykgA237rWfGy/@W3M<bU91<yssNMexTE/_i8Jc90y3@fZQ5ky9P@ylEv/i8f488DomYcf7Qg?8I5QDs?8n0thUf7M1CpyUf7Ug]bI1;WYNC3N@4]3EmW3/UIUWciz/Z8yNkdrg?i8QR3AI0,ybeAy9Mz70W1Cy/Z8yQMA2eL2pF11lBmZ.<5d8w@MMi8RQ90jEOqb/Qy9MQy3e?fx9;2br2g4w_Q13UWY;i8RY90zEtq7/Un03Uyd;yTMA3370Kw0,02@>g?eyEEL/w_Q23Uin;i8RI912bj2g8Ly:NM4yd5n93?18yu_EMa3/QybuMx8yuXEhaj/UJc90N8yuYNM4yd5kV3?2@8;eyqEf/i8JX44y9Xz7JW1OA/Z8yt_Eta3/Qy3N329W5JtglX3pwYvx}W5Kv/@beez4EL/i8QZAAg0,y9Nz70W7ev/@Z.<eL03NZ0,ybgMx8yst9ysrE2p/_Qy9Nky5M7hVZA0E17hHyQMA2bUw;i8RY910NM4yd5rV2?3E3W3/Qy9XP79i8Rk910NZKyuD/_yQMA3bUw;cs18zhmmgw?i8RY913EUF/_Qy9XP79i8Rk912@.<37JW6Ov/_Fe|MYvw:1cyvvECa3/QO9Z@zgD/_i8D5i8n03UlV|yTMA2ezXD/_yTMA3ezOD/_WjH/_ZCA6pCbwYvx}glt1lA5lglhlLg4<1ji8fIa4ydt2gkW0ex/Z8ysd8wPw0t114ySMA5463_gh_7XQ1;i8DvW3av/Z8wYgEyuxrnk5sglR1nA5vMV18yTw8KwE;NZKxgEf/i8JX4bEa;cvp9ysjEfq3/QybuNx8NQgA6:11ysq0fM0fxsg<15cvZ8yTIwKwE;NZKzNDL/i8D5gofZ1g@4v;4ybuOx8zjkegM?W8iv/@W<g0bU71<h8DTxs0fBc0fJI29h2g8cs3Epa3/Qy5XngNhoDBhj7AioDEcsB1Kgk<14yv9dau1cyvV4yu_ELpT/Qy5M7xMt0x90sh9euNORoJ490y5M0@5Iw<37JWh7/_Yf7M2W<g0bU71<h8DTcs3E1a3/Yt490w:i8nJtpwNXuDC_L/cvqW2w<ewQDL/i8fU_M@49L/_Qy9h2goj8RY91zF6L/_MYv0ezPDf/yPy3_MJQyof_10@4wf/_UJk90y5QDkzW4qw/Z8zjQGgw?Lg4<18ysoNMezMDf/Wo7@/Yf7M14yvt8ykgA2ewrDL/i8Jk90ybeKL7pF14yvsNXuw6DL/Wlv@/@glrQ1;kQy3X1x8zngA3ewHD/_i8D3i8cU?@4GM<4ybfqZP?18xvZQ5rU,a?Weyu/Z8NMmlsM}8IZdSI?8n_3UAL.?yPQBqM?xvYfyg41?2bfhdH?25_M@9QM<8IZ0mI?8n_3UCB;yPTLqw?xvZVuUIZ_mE?8n_ul58zjSTfM?cuTEUVT/Qydfrw_?3ERVT/QydfrE_?3EOVT/Qydfsg_?3ELVT/QydfsQ_?3EIVT/Qy9T@yXDf/i8f468DEmRT3pF3E6VT/UIZEmE?ewgDv/NMmeqw?|_@Kj3NZ?ezXDf/yPRZqw?NMlrqw?|_Un_3UxO|WY6gWdKs/@bfklG?371jZG?3|_xvYfy4z|HMp3EKVP/UIZamE?cs58SE?f|@5_M@87L/_@L1AeyrDf/yPQdqw?NMk7qw?|_Un_3UzM_L/WY6gW7Ks/@bfv5F?371uJF?3|_xvYfycb@/_HMp1li8DBglt1lA5lglhjKM4<18w@j0i87IM;4ydt2hkW7Ct/Z8ykgAc4y3e?fx3U6?2bn2hkw_I1vB59ysvEmpX/QCbjMx8yM183XUhi8Bc92zSh50120@5PgM?ct492j|_w_I2t3l8yQgAcbEa;cvp8yTwgWaOs/@9h2gAWNFC3NZ4?18zgn6fM?NQgA9f|Z8ykgAa37rj8QZeSA0,OdH2i:{]11yP@5_Twpi8RQ962W4;eyWC/_i8fU40@440o0,yb1l5N?18yXw0.?i8IlgT40,ybcAwV_w@3PMk0,Obwww1?1dxs0fyas6?18zko1i3D73UdW1w?i2DTioDYi8DXY4wfMhF8yMQ5sg?i8K10,0,Wdd2dcev0fwYU5?18yNnGs<3Xpiaoji3UjC1w?i2Doi8n03UVq1g?i8IdOT<4C9N82VoM4;fxdob?18zogAw;4y9h2h0iEQk8QS9VkyU||_T@1UL/3M18yXjh010w,y9SE7y/Yf,wxNAwzxd4,2?i2D6Y4M1oh18xvofx4Yb?19KcTcPcPcPcPci8Rc9618ysYf7Q?{]1CpyUf7Ug]6pCbwYvx}{]18yv18wYs1ivvwi8DMic7G0QOd399d0sBcasy3M318w_U9i8Dmy4v_tZp8evAfwV4b?18yvV8yvx8asV8zlr_i8fWfw@6G0I0,C9Y4C9@kybl2h0oL7Zi6YB8kg?6bN_kxL7lt4?19w@30oL7Zi6Ylykg0,QFMmof7Qg?6bOTkydgfZ8w@x0i8f2g6bOvkw0OSbOvkw0MCbNZkzHM6bN_kx_gLZ9es5RQQAVY0@4vM<4y9@4i9MAMFM4C9YkQFMkSdkvZ9w_EutzdcastyYnYErQv_NedZhI01Ne9Z?loh<Na5ZvUg4w;47SMhZQfkC3Uu140sFcasx8oZ980RgAg6pCbwYvx}{}fJDz_i8fE0ky3Mw50y7H_i3D1sKJ8o_p80TgAgcnUtYo6,ybt2h0i8JY92zEbFP/Qy5SM@4CwA0,ydj2hwi8DuirzdPcPcPcPcP4y9PMYvh<{]18yv18wYs1ivvwi8DMic7G0QOd399d0sBcasy3M318w_U9i8Dmy4v_tZp8evAfwMsa?18yvV8yvx8asV8zlr_i8fWfw@67wE0,C9Y4C9@kybl2h0oL7Zi6YBEk8?6bN_kxL7tt2?19w@30oL7Zi6Yl2kc0,QFMmof7Qg?6bOTkydgfZ8w@x0i8f2g6bOvkw0OSbOvkw0MCbNZkzHM6bN_kx_gLZcesxRQQMVNw@4vM<4y9@4i9MAMFM4C9YkQFMkSdkvZ9w_EutzdcastyYnYErQv_NedZhI01Ne9Z?nogw?Na5ZvUg4w;47SMhZQfkC3Uu140sFcasx8oZ980RgAg6pCbwYvx}{}fJDz_i8fE0ky3Mw50y7H_i3D1sKJ8o_p80TgAgcnUtYo6,ybt2h0i8QZQzE?37iW2Go/Z8zkMAo4y_PsPcPcPcPcN8ysVdxuQfxf87<f7Q?{]1cyux8wYo1ifvDj8DEic7G0QOd199d0s1cas23M319w_Q9ioDly4r_tZp8ev4fwTQ8?18yvt8yv18asZ8zlv_i8fWfw@6Iww0,C9@kC9Y4ybl2h0oL7Zi6YB8k4?6bN_kxL7lt1?19w@70oL7Zi6Ylyk40,QFO6of7Qg?6bOTkydgfZ8w@x0i8f2g6bOvkw0OSbOvkw0MCbNZkzHM6bN_kx_gLZ9es1RQQMVPM@4vM<4y9Y4i9OAMFO4C9@4QFO4SdkfZ9w_EutzdcasVyYnYErQr_NedZhI01Ne9Z?logg?Na5ZvUgcw;47SM1ZQfkC3Ue140s9cas18oZ980RgAg6pCbwYvx}{}fJD3_i8fE0ky3Mw50y7b_i3D1sKJ8o_Z80TMAgcnUtYo7,ybt2h0i8QZojA?37iWaGm/@bv2gAxvYfymU5<NSQybv2gMW7al/Z8zmnoytxrglN1nk5uglZtMV18atCU:4C9P4Mfie18zjQyo<W0mm/@0K1g:3UlE1<jonAtlwf7M0NS@DV@v/pwYvx}3Xp2aoj03UnA1g?w_JA3UiH0w?YV23MM7FQvD/V18yMR1qM?i8Js961cySgAq4ybwg01?1ezjgzj3DM3U8O@L/i8S498;18yMQkqM?i8B49420Kmc1;3Ulk@L/iofY.@4eMo0,S9VkS5V0@4OMk0,Gdd2J8ytx5cugf7Q?{]1CpyUf7Ug]4y9MAy3M061UL/3M0fJVhh01<4A1R4wVY7nzj8DCWiLW/Yf7M2X.<f183Y4qi8IdzSE0,6Y.<eB_@v/3NZ0,ybkz1cys18ZZx8w@E1i8IdqSE0,wVYw@3Ww80,y9wgw1?11L,<18yMReqw?iEQ49AwVNTc6i2DTioDYj8DzY4wfMhB8yMQMqw?i8K14,0,wVS0@36_D/QO9MAO9M4zTSL183X6h2,0,yb3gtG?3F_vz/SoK3N@4]18yMnNqg?Y8d06058zjRRnw?W5yk/_6w1g;1A4yb1t5F?18yUw0.?i3DbsRh8ysx8atx8ykgAe4MVU0@36fX/QO9Y46bvMiW4;4O9XAwFO4y9z2i:i8C498w<18ykMAi4O9r2h0Wcyi/Z8yQMAi4y3@10fx8A2?18yMlGqg?3Xp0aoj03UmS_v/yMk0og?cv@W|_Q6U.<46V.<bU2;icu498o=yogAw;8I5OS<6q9L2ie;j8DLpAi9x2i4;yogAy;6p4yoMAz;exmBf/pEeY98o:thJCwXMAzw:fx0P|FhLT/MYvw:2bfnFw?18zngAobE8;W1Kj/ZCwXMAzw:fxdP@/_F5LT/MYvw:18yMmxq<Y8d0606X.<46Y.<46@.<4ydfhht?3EZVb/YnVXY15ctJCypMAx;6bNvMx_x2i6;pAi9D2im;pAi9F2ic;pAi9J2ik;NE0k:oI5VlY?8C498;2b1thv?29x2i8;goI7yogAA;eIX3NZ4?2W|_XU3;j8DLW5Wj/_Sx2im:nkTpEeY98o:3UlR.?pEeY98U:thR8yMnrpM?i8K<40,yb5sRD?18yN98es9PHkydfkVs?3Ecpb/U2U5]fx3jY/Z8yMmBpM?i8n0t0Kbk1y5Qw@52g80,ydfhVs?3E0pb/P7rNE0k:eA3ZL/3NY0i8DOwub/MY0h0@TB54,<Kw4<1cyQA8pAm5QAMfhd8NQADTYHF:i3Dgi0Z7MAS5OrE1;j0Z4OAMVO4MfhIyU.<4S9P4S5OkMfhe3FP_P/MYvh<i8Id4ms0,y5Ong7yQ4oxs1RuAydfoVr?3Esp7/Yq05:3FrvL/MYvh<yPSanw?i8RQ962W2;4z7h2hw.<ewiAf/i8fU_M@4Vg<4ydfkBr?3Eb97/Qyb3qRC?20K1g:3UiX;i8n93UiH;j8JA93ybghy5M7i6Y8dF607Fvf/_Sof7Ug]8IZ6BU0,ydt2hoKww<3EKV3/@Cp_L/pwYvh<i8I5kmo?87z/Yf037iibX||_vQwzJdw,2?W2Gi/Z8w_z_3Uly@L/yMkGpw?xs0fx5jW/_EPoX/P7ryPzEd9b/Qyb5nRr?18zjmCeg?i8IWi8D2cs3Eyp3/@AE@L/NE0k:4Obp2gUWsPW/Z4yNnspg?honi3Ugb|W7We/@beezDAv/j8Q5Vjc?bCh1<i8QlFP80,C9Mkyb1hFr?18zjkbe<i8IUcs3Eap3/@Dc_L/Y8dE607FXvT/SoK3N@4]18yMlNpg?Y4y3q0w1KM8;fx9PV/Z8yTMAa4yddnYP?2X.<eyyAL/Wo7V/@Wc;6q9B2i:WkXV/@Vc;6q9z2i:WrPT/_Mi8d1402@c;6q9J2i:WijS/@W2w<37Si8DfWfaf/@9h2gAi8Q553c0,y9h2gEWl7P/Z8w_w1t1l9ysl8zogAw;4y9h2h0WtXV/Z8zogAw;4y9h2h0i8KN2,0,y9Sw@Swmc1?21UL/3M18xvp@hQy3Ld4,2<7wYxc0fxnQ<3Mi05N446Z.<eAkZf/pwYvh<i8JY943FxLz/Qybt2h0WvPS/Z8yTgAgeBOZv/3XuQkg.?24M7kIioDQgrQ1;WszP/Z5cs0NQKBdZL/hj70ctbFM_j/QkNOj7iWrDT/Z1Lg4<11L,<3FCvf/_18wQ4g0uBZ|3NY0{]1lLg4<1ji8fI64ydt2gcW4Kf/Z8ysd8wPw0t4t8zjRzm<W4qe/@0K1g:t318yMm@oM?i8n0t16bk1y5QDgaY8dE6,f7Qg0,ydfj5o?3E58X/Yq05]NXky9T@x3zv/i8f468DEmRT3pyUf7Ug]5eX.<4y3X218zngA7ezczL/i8D2i8cU07g7wTMA709Q54y9R@w4zv/i8f488DomYcf7Q?i8Jo24yddnMN?18ykgA24y9T@yMzv/i8Jk90y5M0@4yM<4yddlYN?18ytZ8ylgA2eyfzv/i8Jk90y5M7lli8Bk90x8yNTOow?i8QZuRs?exuzv/i8Jk90y0K1g:t2B8xtJQ1UJ368n0tkR8ylgA24ydfl1n?3EcUT/Qybl2g8NE0k:f18wSI80j7ri8DnW5uc/Z8wYgwytxrMMYvw:18yMm9ow?Y4y3g0w1ctLHSf23qNw1i8ItsS8?eKBpwYvx}glt1lBlji8fIi4ydt2gsWbOd/Z8ysd8wPw0t0R8oSMA78R5_ofU0DouLg4<18yt_EWoL/Qy3N4y9W5JtglV1nYcf7Q?i8JX2bEa;cvrE28T/QybuN2W2w<37SgoD6Wdmb/Z9ysu3_gcfx9A<18yTIoi8QRdj<4y9v2g8W6ic/YNQEn0t1V8yTMA24yddi8M?3EjoP/XE2;xs0fxpw<1cyvV4yvvEFoT/Qy3@fYfx6n/_Z8zmPH@4yblg20ew1QlQOdh2gwi8D1Ly:NM4O9NQyd5tQL?1cykgA2ewWy/_i8JZ,ybt2g8cuTEKEX/@AA|3NZ4?2W.<4y9NAi9Z@x0zv/i8fU_M@40f/_Qy9NAydfpEL<NM37JWdea/_FXvX/Sof7Qg?bE1;WlX/_Yf7M1CpyUf7Ug]45mlld8w@Mgi8RQ90PEnEP/Qy9MQy3e01Q1UdY90M2vNWZ.<4y9T@yhyL/i8f448DEmRR1nIdC3NZ4?18yTw8cvqW2w<eyMy/_i8JH44yddhAL?11ysp8yu_EaEL/Un0t4V8zjkebM?i8DLW1ub/@5M7hji8QR1yY0,y9X@w4y/_xs1Qm4yddnUK?18yu_EYoH/Un0tlR4yvsNXuy3yL/Wnn/_ZC3NZ4?2@.<4i9ZP7JW9C9/_Fm|MYvg?NZAi9ZP7JW8i9/_FhL/_MYvw:2@0w<4i9ZP7JW6C9/_Fa|MYvg018yuV8zjScbw?cs3ETUz/@Ac|pyUf7Ug]45mlld8w@Mgi8RQ90PEfEL/Qy9Nky3e?fx443?23v2gc.@e1w80,ybg0x8yst9ysrEhUz/Qy9MQy5M0@4@M8?fp0a.fxeA2<NOj7Si8Qlc2U0,y9T@zKyf/csC@.<4y9TQyd5i4K?3ES8z/P79Lw8<18ytZ8zhkobw?Wca8/YNOrU3;i8Dvi8Ql3OU?eyIyf/csC@1;4y9TQyd5ggK?3EBEz/P79Lwk<18ytZ8zhnWbg?W828/YNOrU6;i8Dvi8Ql@2Q?exGyf/csC@><4y9TQyd5uUJ?3El8z/P79Lww<18ytZ8zhnAbg?W3W8/YNOrU9;i8Dvi8QlROQ?ewEyf/csC@2w<4y9TQyd5sMJ?3E4Ez/P79LwI<18ytZ8zhn0bg?WfO7/YNOrUc;i8Dvi8QlJyQ?ezCx/_csC@3g<4y9TQyd5qoJ?3EQ8v/P79LwU<18ytZ8zhmtbg?WbG7/YNOrUf;i8Dvi8QlB2Q?eyAx/_csC@4;4y9TQyd5oYJ?3EzEv/P79Lx4<18ytZ8zhmbbg?W7y7/YNOrUi;i8Dvi8QlvOQ?exyx/_csC@4M<4y9TQyd5ngJ?3Ej8v/P79Lxg<18ytZ8zhlEbg?W3q7/YNSQy9X@xYx/_i8f448DomRR1nIegi8QZkOM?ezkxL/i8QZkiM?ez8xL/i8QZkyM?eyYxL/i8QZkOM?eyMxL/i8QZkyM?eyAxL/i8QZkyM?eyoxL/i8QZmyM?eycxL/i8QZmyM?ey0xL/i8QZmyM?exQxL/i8QZlOM?exExL/i8QZlyM?exsxL/i8QZl2M?exgxL/i8QZl2M?ex4xL/i8QZjyM?ewUxL/i8QZjOM?ewIxL/i8QZk2M?ewwxL/i8QZliM?ewkxL/i8QZmOM?ew8xL/i8QZmiM?ezYxv/i8QZm2M?ezMxv/i8QZlyM?ezAxv/WuD@/Yf7U]j8DTW527/ZcyvvEy8r/Qy9MQy5M0@5@_P/V1CpyUf7Ug]bI1;Wrb@/ZC3NZ4?18w@M8i8IZ3l4?bU1;WaK8/Z8yPS4kg?Lw4<3ECEz/Qybfldh?2@.<ey9yf/i8IZaB4?bU1;W7y8/Z8yPRpkg?Lw4<3EpUz/Qybfu1g?2@.<exmyf/i8IZ9R4?bU1;W4m8/Z8yPT6k<Lw4<3Ed8z/QybfjRh?2@.<ewzyf/i8IZB5<bU1;W1a8/Z8yPRXk<Lw4<3E0oz/Qybfv9g?2@.<ezMx/_i8IZyl<bU1;Wd@7/Z8yPRMk<Lw4<3EPEv/Qybfutg?2@.<eyZx/_i8IZrB<bU1;WaO7/Z8yPQ5k<Lw4<3ECUv/Qybfphg?2@.<eyax/_i8IZyR<bU1;W7C7/Z8yPRyk<Lw4<3Eq8v/Qybfv5f?2@.<exnx/_i8IZ05<bU1;W4q7/YNM4y3N0z3;YMYu@Ay3X0x8wYg8MM~~~~=h;hw;8;7;AQ4gUAihO01eyth0M8jgdko=i;4A<1a;iM<4Q<1f;kw<5g=lw<5A<1q;mM[1s;u46fsBvL828DhYy7ljWCFPcrtQZYh0@HMTuJJLgrNlb1qNYwxw0H41VAKg_fwv4XlcciXAJXPzYyt9rIvlkSGyOaW9UyUFFHpXeFTVTfjdGpl@pnwpJi5RctGEY!?1_;4%1W;4w^2d;4w^1b.0,w^1_.0,w%g;8%3m;4$m.0,w^1h0w0,w^1O;4w^2L0w0,w^3V.0,w^1x.0,w^2C0w0,w^2S.0,%1s;4w%G0w0,w^1l;4w%m0w0,w^1V;4%2J.0,w^27.0,w^3A;4%1K.0,w^1o0w0,w^1z;4$g.0,w^2w.0,w%70w0,w%b.0,w^11.0,w^220w0,w^1i.0,w%l0w0,w^3i.0,$V.0,w%1;8%1T.0,g^1H;4w^3k.0,$@0w0,w^2u;4w^1D.0,w^1A;4w%E.0,%2K;4%2h0w0,w%t0w0,w^>0w0,$4.0,w^2B.0,w%y0w0,w^1E0w0,w^3Y;4w^190w0,w^1R.0,g^2o.0,w^1w.0,w^3N.0,w%S0w0,w^3y.0,w%I;8%39.0,w^16;8w^3w0w0,%32;4%2o0w0,w%e0w0,w^1p.0,g^1q1<4g0p023l[c=2J0M0,g0p063n[c=191<4g0p063l[c=1J1<4g0p0e3k[c=2s0M0,g0p0a3n[c=1D0M0,g0p063o[c=3I0w0,g0p0e3p[c=2a0M0,g0p0e3n[c=2Q0w0,w,0f1Z[wg4}3d0M0,g0p0e3m[c+k0M0,g0p063p[c+T1<4g0p0a3l[c+d1<4g0p023m[c+V0M0,g0p0e3o[c+?M0,g0p0a3p[c+C1<4g0p0e3l[c=3f0w0,g0p023q[c=1k0M0,g0p0a3o[c=1W0M0,g0p023o[c=3?M0,g0p023n[c=3x0M0,g0p0a3m[c=3R0M0,g0p063m[c+C0M0,g0p023p[c+0nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0nRZzu65vpCBKomNFuCk0sThOoSxO07dQsCNBrw1Urm5Ir6Zz06RBrmdMug1Pt79zs7A0u6pOpmk0pCBKp5ZSon9Fom9Ipg1vnSlOsCVLnSNLoS5QqmZK05ZvqndLoP8PnTdQsDhLr01yqmVAnS5OsC5VnTpxsCBxoCNB069FrChvondPrSdvtC5Oqm5yr6k0oDlFr7hFrBZBsD9Lsw1JomJBnSVBtRZxsD9xulZSon9Fom9Ipg1PundzrSVC06ZMpmUSd01Opm5A06dIrTdB05ZvqndLoP8PnTdQsDhLtmNI06tBt5ZPt79FrCtvtC5Itmk0sTBPoS5Ir01JqTdQpmRMdzg0tmVIqmVH07dQsCdJs01Pt6hBsD80pDtOqnhB06RJon0Sd01JpmRPpng0nRZBrDpFsCZK07dQsCVzrn?nRZFsSZzczdvsThOt6ZIr01BtClKt6pA071Fs6k0pCdKt6MSd01PrD1OqmVQpw1yqmVAnS5OsC5VnSlIpmRBrDg0sThOpn9OrT80tmVyqmVAnTpxsCBxoCNB071LsSBUnSRBrm5IqmtK06NPpmlHdzg0oSNLoSJvpSlQt6BJpg1JpmRzq780tndIpmlM06pMsCBKt6o0s6ZIr0>sClxp3oQ06pxr6NLoS5QpjoQ06pPt65Qdzg0sSlKp6pFr6kSd01PundFrCpL07dMr6Bzpg1zrT1VnSpFr6lvsC5KpSk0rmlJsCdEsw1JomJBnS9RqmNQqmVvon9Dtw1vnThIsRZDpnhvomhAsw1JtmVJon?nRZzt7BMplZynSNLoM1Pq7lQp6ZTrw>tnhP07dBt7lMnS9RqmNQqmVvpCZOqT9RrBZOqmVD079FrCtvqmVFt5ZPt79RoTg0omhAnS9RqmNQqmU0sCBKpRZApndQsCZVnTdQsDlzt01OqmVDnTdzomVKpn9vsThOtmdQ079FrCtvoSNxqmRvsThOtmdQ079FrCtvtSZOqSlOnTdQsDlzt01OqmVDnSdIpm5Ktn1vtS5Ft6lOnTdQsDlzt01OqmVDnSBKpSlPt5ZPt79RoTg0sCBKpRZComNIrTtvsThOtmdQ079FrCtvomdHnTdQsDlzt01OqmVDnSZOp6lOnTdQsDlzt01OqmVDnSdLs7BvsThOtmdQ079FrCtvsSBDrC5InTdQsDlzt01IsSlBqRZPt79RoTg0sCBKpRZFrChBu6lOnTdQsDlzt01OqmVDnSpBt6dEpn9vsThOtmdQ079FrCtvpC5Ir6ZTnT1EundvsThOtmdQ079FrCtvrmlJpChvoT9BonhBnTdQsDlzt01OqmVDnTdBomNvsThOtmdQ079FrCtvpCdKt6NvsThOtmdQ079FrCtvs6BMplZPt79RoTg0sCBKpRZPs6NFoSlvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0r6ByoOVPrOUS06NAbmNFrDlUbnwUdyQSd2VPrOUO,tcik93nP8KcM17j4B2gRYObzcP,tcik93nP8KdM17j4B2gRYObz8U,tcik93nP8Kcjg0hQN9gAdvcyUOdM17j4B2gRYObz4M,tcik93nP8Kcjs0hQN9gAdvcyUR,tcik93nP8KcPw0hQN9gAdvcyUObzk;1?8?w02?80.01?c01?2?801g02?80.02?o?w020,?w030,?w070,?w02?8?w02?w?w020,?w01?802g01?E?M02?80.01?8?w01?802M02?8?w02?803?2?803g020,?w020,0.0a?8?w010,0.010,0.010,0.010,0.010,0.010,0.010,0.010,;10,0y.?1:w;4SBF3g?202t1=402M1@1<4=2PApo6<d0as4<g;5SBF3g?302O1<4;8yhBwo<I0L.?1:jqmAd<a09Q4<g;B96m1w?2g371<4;8uhBwo<s0Qwg?1;2gApo6<60dQ4<g;BV6m1w?1g3E1<4;1lFqgQ<g0YMg?1;2UApo6<30fQ4<g;thFF2g<w081g}13d[2=2M>}1zd[2=>>}23d[2+wPg}23i[2+9Gw}2zi[2+oGw}43i[2+EGw}4zi[2=10Hw}63i[2+QGw}6zi[2=10Gw}83i[2=1oGw}8zi[2=1BGw}a3i[2=1XGw}azi[2=26Gw}c3i[2=2lGw}czi[2=2yGw}e3i[2=2WGw}ezi[2=2XGg[3j[2=3aGw[zj[2=2KGg}23j[2=3nGw}2zj[2=2xGg}43j[2=3AGw}4zj[2=3IGw}63j[2+0GM}6zj[2+fGM}83j[2+wGM}8zj[2+NGM}a3j[2=16GM}azj[2=1lGM}c3j[2=1NGM}czj[2=1XGM}e3j[2=2iGM}ezj[2=>Hw[3k[2=2xGM[zk[2=1pGg}23k[2=2LGM}2zk[2=15Gg}43k[2=2@GM}4zk[2=3dGM}63k[2=3zGM}6zk[2=3LGM}83k[2+5H[8zk[2+hH[a3k[2+KH[azk[2+kGg}c3k[2+XH[czk[2=1nH[e3k[2=1FH[ezk[2=20uw}fzk[2+wQw[3l[2+oGw}23l[2=3ZGg}2zl[2=2Mp[3zl[2=10Qw}43l[2=10Hw}63l[2=3PGg}6zl[2=3Mow}7zl[2=1wQw}83l[2=10Gw}a3l[2=3EGg}azl[2=1wug}bzl[2=20Qw}c3l[2=1BGw}e3l[2=3uGg}ezl[2+Mow}fzl[2=2wQw[3m[2=26Gw}23m[2=3cGg}2zm[2=20og}3zm[2=30Qw}43m[2=2yGw}63m[2=2XGg}6zm[2+Mog}7zm[2=3wQw}83m[2=2XGg}a3m[2=2KGg}azm[2=10nw}bzm[2+0QM}c3m[2=2KGg}e3m[2=2xGg}ezm[2=3Mng}fzm[2+wQM[3n[2=2xGg}23n[2=2rGg}2zn[2+0u[3zn[2=10QM}43n[2=3IGw}63n[2=2fGg}6zn[2+Mng}7zn[2=1wQM}83n[2+fGM}a3n[2=25Gg}azn[2=3wn[bzn[2=20QM}c3n[2+NGM}e3n[2=1WGg}ezn[2=2gn[fzn[2=2wQM[3o[2=1lGM}23o[2=1NGg}2zo[2=3Mm[3zo[2=30QM}43o[2=1XGM}63o[2=1BGg}6zo[2=2wm[7zo[2=3wQM}83o[2=>Hw}a3o[2=1pGg}azo[2=1wm[bzo[2+0R[c3o[2=1pGg}e3o[2=15Gg}ezo[2=>tw}fzo[2+wR=3p[2=15Gg}23p[2+VGg}2zp[2=3Mtw}3zp[2=10R[43p[2=3dGM}63p[2+KGg}6zp[2+Mq[7zp[2=1wR[83p[2=3LGM}a3p[2+xGg}azp[2+gm[bzp[2=20R[c3p[2+hH[e3p[2+kGg}ezp[2=2gpw}fzp[2=2wR=3q[2+kGg}23q[2+aGg}2zq[2=30lM}3zq[2=30R[43q[2=1nH[fze[4&zf[1w<5o-13f[1w<58-1zf[1w;o-23f[1w<4E-2zf[1w<4Q-33f[1w<5c-3zf[1w<4I-43f[1w<4o-4zf[1w<4Y-53f[1w<5A-5zf[1w<5)63f[1w<4A-6zf[1w<5I-73f[1w<5g-7zf[1w<2k-83f[1w<2o-8zf[1w<5s-93f[1w<4M-9zf[1w<5M-a3f[1w<4w-azf[1w<4s-b3f[1w<5k-bzf[1w<54-c3f[1w<5w-czf[1w<3U-d3f[1w<5E-dzf[1w<4)e3f[1w<4k)3g[>;4)zg[>;8-13g[>;c-1zg[>;g-23g[>;k-2zg[>;s-33g[>;w-3zg[>;A-43g[>;E-4zg[>;I-53g[>;M-5zg[>;Q-63g[>;U-6zg[>;Y-73g[><1)7zg[><14-83g[><18-8zg[><1c-93g[><1g-9zg[><1k-a3g[><1o-azg[><1s-b3g[><1w-bzg[><1A-c3g[><1E-czg[><1I-d3g[><>-dzg[><1Q-e3g[><1U-ezg[><1Y-f3g[><2)fzg[><24)3h[><28)zh[><2c-13h[><2g-1zh[><2s-23h[><2w-2zh[><2A-33h[><2E-3zh[><2I-43h[><2M-4zh[><2Q-53h[><2U-5zh[><2Y-63h[><3)6zh[><34-73h[><38-7zh[><3c-83h[><3g-8zh[><3k-93h[><3o-9zh[><3s-a3h[><3A-azh[><3E-b3h[><3I-bzh[><3M-c3h[><3Q-czh[><3Y-d3h[><4)dzh[><44-e3h[><48-ezh[><4c-f3h[><4g!]1ComBIpmgwt6YwoT9BonhB865OsC5Vey0BsM0BsPEwrCZQ865K865OsC5V,pfkAJilkVvhAZigQlvhA5cj491gQI0bShBtyZPq6Q0bThJs016jR9bkBlenQh5gBl707hOtmk0pCZOqT9Rry1rh4l2lktt84lKom9Ipmga06RJon0W82lP06VnrT9Hpn9Pjm5U06VnrT9Hpn9P06VcqmVBsQRxu01KgDBQpnddonw.l97nQR1m?JbntLsCJBsDcJrm5Ufg0JbntLsCJBsDcMfg0JbntLsCJBsDcZ02QJr6BKpncJrm5Ufg0JbmNFrClPc3Q0biRIqmVBsPQ0biRyunhBsORJonwZ02QJoDBQpncMfg0Jbm9Vt6lPfg0JbmNFrmBQfg0JbnhFrmlLtngZ02QJpT9BpmhV02QJsClQtn9Kbm9Vt6lP02QJrTlQfg0JbnhFrmlLtng09mg0hlp6h5ZiikV7nQh1l440hlp6h5ZiikV7nQlfhw15lAp4nR99jAtvikV7hldknQh1l440hlp6h5ZiikV7nQBehQljl5Z5jQo0hlp6h5ZiikV7nRdkgl9mhg1CrT9HsDlKnSZRt?Br7ka07tOqnhBa6pAnTdMontKb21PoDlCb21Pr6lKag1CrT9HsDlKnT9FrCsKoM1TsCBQpixBtCpAnShxt64I9DoIe2A0u0E0tT9Ft6kEpChvsT1xtSUI829Un6Uyb20Oag1TsCBQpixBtCpAnSlLpyMw9ClLpBZPqmsI83wF06hOug0BsOUBr7k0kABehRZ9jAt5kRhvh4Bmildfkw1iikV7nQ91l4d8nQB4m01iikV7nQ91l4d8nRdcjRhj,p4nQZih4linR19k4k0tT9Ft6kEpCgI82pSomMI83wF07tOqnhBa6pAnSNLoS5InTdFpOMw9CZKpiMwe2A0pCZOqT9RrBZFrD1Rt01JpmRCp5ZzsClxt6kwpC5Fr6lAey0BsM>qn1B86pxqmNBp3Ew9nc0oSNLsSk0sT1IqmdB86pxqmNBp3Ew9nc0kAlgj5A0c01TsCBQpixBtCpAnShxt64I82pLrCkI83wF06BKoM1Apmc0kQl5iRZjhlg0kQl5iRZ5jAg09mNIp?Br6NA2w1Pq7lQp6ZTrBZT07dEtnhArTtKnT80sSxRt6hLtSVvsDs0tmVHrCZTry1zrSRJomVAey0BsM1OqmVDnSBKqng0sCBKpRZApndQsCZV079FrCtvsSdxrCVBsw1OqmVDnSdIomBJ079FrCtvtSZOqSlO079FrCtvoSNBomVRs5ZTomBQpn80sCBKpRZFrCtBsTg0sCBKpRZComNIrTs0sCBKpRZxoSI0sCBKpRZLsChBsw1OqmVDnSdLs7A0sCBKpRZPqmtKomM0r7dBpmI0sCBKpRZFrChBu6lO079FrCtvpClQoSxBsw1OqmVDnSpxr6NLtRZMq7BP079FrCtvrmlJpChvoT9BonhB079FrCtvsSlxr01OqmVDnSpzrDhI079FrCtvs6BMpg1OqmVDnTdMr6Bzpg1cqndQ86NLomhxoCNBsM1OqmVDnSNFsTgwmRp1kBQ0kT1IqmdB86hxt64.T9BonhB871Fs6k0sCBKpRZMqn1B83N1kB9YkAg@85JnkBQ0hCBIpi1zrSVQsCZI079FrCtvpCdKt6Mwf4p4fy0YoSRAfw1jpm5I86RBrmpA079FrCtvsSlxr20YhAg@,dOpm5Qpi1JpmRCp01OqmVDnSRBrmpAnSdOpm5Qpi0YlA5ifw1gq7BPqmdxr21ComNIrTs0jBldgi16pnhzq6lO,Vljk4wimVApnxBsw1jpmlH86pA06NPpmlH83N6h3Uwf4Z6hzUKbyU0kSBDrC5I86lSpmVQpCg0sCBKpRZPqmtKomMwf4p4fw1qpn9LbmdLs7AwqmVDpndQ079FrCtvoSZMui0YjRlkfy0YikU@059BrT9Apn8wrTlQs7lQ079FrCtvrT9Apn8wf4p4fy0Yk4pov6RBrmpAfw11oSIwoC5QoSw0sCBKpRZxoSIwf4p4fy0YhAhvjRlkfw1crStFoS5I86pxr6NLtM1jqmtKomMwqmVDpndQ,dIpm5Ktn0wtS5Ft6lO05tLsCJBsy1zrSVQsCZI079FrCtvtSZOqSlO85JFrCdYp6lzng13r65Fri1yonhzq01OqmVDnSdIomBJ85Jmgl9t85J6h5Q0kDlK87dzomVKpn80sCBKpRZPoS5KrClO83NCp3UwmTdMontKnSpAng14pndQsCZV879FrCs0imVFt6Bxr6BWpi1OqmVD87tFt6wwoSZKpCBD079FrCtvqmVFt21rhAN1hRdt079FrCtvr6BPt[6BKtC5IqmgwrDlJpn9FoO1FrChBu21CrT8wqmVApnxBp21xsD9xujEw9nc]2ZPuncLp6lSqmdBsOZPundQpmQLoT1RbSdMtj0LoS5zq6kLqmVApnwPbTdFuCk?6pLsCJOtmUwmQh5gBl7ni0BsPEBp3Ew9ncwpC5Fr6lAey0BsME<1TsCBQpixBtCpAnSBKpSlPt5ZAonhxb20CtyMwe2A?7tOqnhBa6pAnSpxr6NLtOMw9CBMb21PqnFBrSoEqn0Fag[1CrT9HsDlK85J4hk9lhRQwsCBKpRZxoSIwr7dBpmIwpC5Fr6lAey0BsME}1TsCBQpixCp5ZMqn1Bb20CrT0I87dFuClLpyxLs2AF07tOqnhBa6pAnThxsCtBt2Mw9CBMb21PqnFBrSoEqn0Fag[1TsCBQpixCp5ZDr6ZyomNvomdHb20Cs70I87dFuClLpyxMs2AF;pCZOqT9Rry1rh4l2lktt879FrCtvsSlxr21ComBIpmgW82lP2w<6pLsCJOtmUwmQh5gBl7ni1OqmVDnSdIomBJ86NPpmlH86pxqmNBp3Ew9nca:79FrCtvsT1IqmdB83N9jzUwf4Zll3Uwf4Z6hzUwf4N5jzUwmSdIrTdBng}79FrCtvpC5Ir6ZT83Ngil15fy0YhABchjUwmShOulQ0bShBtyZPq6QLpCZOqT9RryZQrn0LpCZOqT9RryVom5w1*7M0u01Q07?r01E06g0o01s05w0l01g,M0i014,?f?U03g0c?I02w09?w0>06?k01?3?80.;7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3/_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe3MUd30Ia2gw71wk40M81?Ye3gMb2wA8>o510c2.,;8:k<17jBk0.0>.;V+8?s,;3g=16McX9,?2c;wk/_g,?f1n/ZE.?c5H/@01<wm/_308?61s/YM0w?Y6z/U02?3gzL/W08?a2f/YQ0M?Q97/Ug3?>A/_Q0c?c2q/Y01<4ar/Sw4?3MF/_K.0,2E/_o1<Aaz/_w4?3gGf/60k?22F/YU1g?MaP/U05<gHv/E0k?62J/_01g?8aX/@M5?>HL/30o?62N/Zo1w?Ib7/Tw6?1wIL/H0o?22P/_g1w?Ubj/Mg7?30JL/k0s?62U/ZY>?Ecr/WM7<wN/_R0s?338/Y02<AcD/PM8?2MOL/s0w?23e/@A2[1g+nFi?5U4,r30s8A,?2g;s;S57/M,;3x163xxa3MJT28?fNEXazcA8w;1Q;h;81m/YR0w<4Ie48U2gwUozgd23y2c14Aea8o5ggUMwMp73B1w2wUMiscea4763y12P0UogIQe44be3wx82MdM.Eec4j33yx1NwUwgIMe64bd3x12PwU8jgJM3wz3NIPdPAwek8c6xwmc18Q3zw8E;L;4xo/_K:44e48c2igVgjwEe444e24sb0B8a3x153wx92O;3E;35D/Pc1;ggUgwM9e3C02lgEe44ce24Ab,M;c.?a5H/Ukc;gwUgzM923xye0Q8e88Q4hgUEz0l13z261A4ee8c7hMW02gft.Eee44ec44ea48e848e648e448e24kb;p;5M1?1EpL/SOk<1b3x2f0Ase68U3gwUwzgh23yyc1k4ec8o6h0UUwMt93F030MMd3wz3NIPdPIZg3F03wMu61EM5zgie0UY20Lsa3zx33z113yx23y123xx23x123wx12M18;N,?e2b/_8:48e48Y2gwUozwd53y2d148ea8M5ggUMxwp13zy31Qgek0at2wUUh0UMggUEgwUwgwUogwUggwU8hgI0j;102?1Azf/aw8<1i3x2f0Ase68U3gwUwzgh23yyc1k4ec8o6gMUUwMta3L080SQ12wUUgMUMggUEgwUwgwUogwUggwU8h0I<18;o080,ie/@k.<58e48Y2hMUozwd53y2d148ea8M5ggUMxwp13zy31QEeU0w3mM4ee4cec44ea48e848e648e448e2<b;aM2?2oz/_hMs<1c3x260Awd1ACf0UU4zgmc1Ec70PY32wM7244b;p;dM2?2UBL/jwI<1b3x2f0Ase68U3gwUwzgh53yyc1k4ec8o6h0UUwMt93K030_Q12wUUggUMggUEgwUwgwUogwUggwU8gwI2I0U8MYrcPsXfk0Xw0Uc7xwqc1oQ4zwef0w1c;h0c?a2x/_n.<58e48Y2hMUozwd23y2d148ea8M5ggUMxwp13zy31QEeA8840OU12wUUggUMggUEgwUwgwUogwUggwU8hMI?><2k0M?caf/Qk:ggUgwM993z1T3x133ww07;bg3?1wE/_hg;113x230AAec7se44ce2?s;R0c?92z/Y_:44e48c2igUwsgUggMU80><3Q0M?Iaf/Qk:ggUgwM993z1T3x133ww0h;1g4?3wE/_Cgc<123x2f0A8e68U3gwUwz0h13yy61koec8c6hMXM.eJ.Eec4cea44e848e648e448e244b;7;5M4<UF/_hg;113x230AAec7se44ce2?s;v.?6yD/Z5:44e48c2igUMtMUggMU802w<2s1<Cav/Y]ggUgxw963xy30Qgec09c2wUogMUgggU8hgI07;cw4<IGf/hg;113x230AAec7se44ce2018;W.?5OE/_E0w<48e48Y2gwUozwd23y2d148ea8M5ggUMxwp13zy31QAeA05E2wUUgMUMggUEgwUwgwUogwUggwU8igI07;3g5;G/_hg;113x230AAec7se44ce2?M;l0k?32H/@A:48e48U2ggUoxwd63y2314gek09A2wUwgMUoggUggwU8igI08;8w5?2IG/_Lw;113x230Agec09q2wUggMU8hwI0c;aM5?18Hf/IM4<123x2e0A4e68o3hwUwwMh43B02IMEe84ce644e448e24Eb,w<3w1g?RaT/ZY1;gwUgzM923xye0Q8e88Q4gwUEz0l13z261Aoee8c7h0VwrMEee4cec44ea48e848e648e448e248b<E;b0o?6yL/@v.<44e48o2hwUowMd43z02PwEe64ce444e24cb02M<1o1w?Tb3/P8e;ggUgxw933gp9zMee18Q5z0q3>e11wEc>x22M<2g<281w?XbX/To:ggUgxw963xy30Qgec09C3xx33x113wwE;I0o0,i/_Y7.<44e48c2igUMpwEe44ce24kb0Gka3x133wx82Pw<3s1w?ac3/R81;gwUgzM923xye0Q4e88o4ggUEwMl43D1N2wUEgMUwggUogwUggwU8hgI?3:o>?jc7/No1;gwUgzw913xy60Q4e88c4h0UMqMEe84ce644e448e24sb<M;j0s?3z2/ZG0M<48e48U2ggUoxwd13y2314gec0cw0wEe84ce644e448e248b6;807?1QNv/wg4<143x03v,e2~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~=3|_:b07[s0s[wPg[4=vwg[1=8w4[3=3c0w[Q=t7Y[p=13d[6M=8=1E=6cQ[s+w=ZvX_rM]w=k=u8A[6=c2=2w=k1g[I=6+3=ezf=w[3E1g}1g=>=n=8yv[>=EA=w=o0Y[9=1w=_L/rM;18zM}f/_SY]w[3M/ZL:8Oe[@v/rM;27~~~~~~~~~~!}acQ!1wc[m0M}2o3[dwc}160M}5o3[pwc}1S0M}8o3[Bwc}2C0M}bo3[Nwc}3m0M}eo3[Zwc[61[1o4[9wg[S1[4o4[lwg}1C1[7o4[xwg}2m1[ao4[Jwg}361[do4[Vwg}3S1=o5[5wk[C1g}3o5[hwk}1m1g}6o5[twk}261g}9o5[Fwk}2S1g}co5[Rwk}3C1g}fo5[1wo[m1w}2o6[dwo}161w}5o6[pwo}1S1w}8o6[Bwo}2C1w}bo6[Nwo}3m1w}eo6)<3||||||/M;3||/MCG[6aE!aaE}10Hw!QGw}42G!5yG[pqE!uWE}26Gw#2lGw}aaG!bGG[KWA!OGE}2KGg#3nGw}a6F!eiG[XaE!0aI[fGM!wGM}36H!4qH[lqI!sqI}1XGM#2iGM}72K!a6H[mqA!HWI}15Gg#2@GM}cSH!eeH[XWI!1qM[hH!0KH[1iF!3KI[lWM!qqM}20uw[4=8d8[oGw`fSF[I6g[1=43i[gaU`3PGg}f1y=g[1wQw}42G~WaA}1wug[4=wd8}1BGw`dWF[c68[1=a3i[xGE`3cGg}81x=g[30Qw}aaG~KWA[Mog[4=Ud8}2XGg`aWF[g5U[1+3j[HGA`2xGg}f1t=g=wQM}a6F~CWA=u=4=gdc}3IGw`8@F[c5Q[1=63j[3WI`25Gg}e1s=g[20QM}36H~uGA}2gn=4=Edc}1lGM`76F[Y5w[1=c3j[uWI`1BGg}a1o=g[3wQM}72K~mqA}1wm=4+dg}1pGg`4mF[s7o[1=23k[hqA~VGg}f1S=g[10R[cSH~bGA[Mq=4=odg}3LGM`26F[45w[1=83k[4qM~kGg}91C=g[2wR[1iF~2GA}30lM[4=Mdg}1nH(hQd3ey0EhQVlai0NdiUObz4wcz0Odj4Ocj4wa59Bp218ongwcjkKcyUNbjkF;2;1}g?hQ4A0jdxcg3c0w}85_=2VPq7dQsDhxow0KrCZQpiVDrDkKoDlFr6gJqmg0bCBKqng0bDhBu7g0bCpFrCA0bCtKtiVEondE02VAumVPumQ0bChVrDdQsw0KpSVRbDpBsDdFrSU0bCtKtiVSpn9PqmZKnT80bD9Br64Kp7BK02VOpmNxbD1It?KsCZAonhx02VKrThBbCtKtiVMsCZMpn9Qug0KpmxvpD9xrmlvq6hO02VBq5ZCsC5Jpg0Kt6hxt640bDhysTc0bCBKqnhvon9OonA0bCpFrCBvon9OonA0bChxt64KsClIbD9L02VAumVxrmBz02VDrTg0bCtLt2VMr7g0bChxt640bC9PsM0KoSZJrmlKt?KpSVRbC9RqmNAbC5Qt79FoDlQpnc~~+?b;>;8=G08}2E0w}2g*4*7w;4;6=cM2[P08[r*1*7k;1;1w[3M0w}f02+g)<1+4+A:g;o+0s=>}75U)<1&aw;4;6=7h_[t7Y[d*1*3;3S/ZL0w+w=2=M+7+w*W;2M;8=M8[30w[bw8[2:4;8=1w=gw;c;2=7y9[u8A[k1g(g(4E<3/_ZL0w[2czw}8Oe[Kw=7+8+w[1n;_L/rM8=i8Y}18zM}e+2:8;8*pw;g;2=2yg[a9[1w3M[s=2+o=7:4;gw[28DM}8yv[W0k[7;6:w=6=1W:g;8=wak}20Fg}20a)<1&ww;s;2=a2L[EaY[M*2*9k;1:w[3gHM}d2L[9,(g(2z:g;8=@b[3UI[9M7(8*Hg;4;31=zd[2bQ[4*2*bg;8:Mg[gPg}12Z[3g*w(2W;3w;c=4cQ[gLg[w*8+w=Nw;Y;3=1zd[6bQ[8*2+8=d8;1:M=wPg}22Z[2&w(3v;1w;c=acQ[ELg}d01[2+8=1+W:4;3=fze[@bU}3M*2+8=eQ;1:M[3EPM}ey_[408(w=2=3S:g;c+d8=Mw}508(w*_:w;3=53q[kcE[E*2&41<1;c*53a[bw*4+g=a.?>-ufE}20Ow}2g*4&g;c%FcE[w.(g)<')


_forkrun_bootstrap_setup --force

