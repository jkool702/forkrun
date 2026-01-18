#!/usr/bin/bash
if shopt -q extglob; then
   extglob_was_set=true;
else
   shopt -s extglob;
fi

frun() {
(
    # 1. WRAPPER LOGIC (Current Shell)
    [[ "${1}" == '__exec__' ]] || {

        # Check if already setup (and FD is valid), otherwise bootstrap
        { ${FORKRUN_RING_ENABLED:-false} && [[ -n ${FORKRUN_MEMFD_LOADABLES} ]] && (( FORKRUN_MEMFD_LOADABLES > 0 )); } || _forkrun_bootstrap_setup --fast
        
        # Generate list of loadables to enable in the new shell
        (( ${#ring_funcs[@]} > 0 )) || ring_list 'ring_funcs'
        printf -v ring_enable '%s ' "${ring_funcs[@]}" 

        # EXEC into Clean Room
        # /proc/self/fd/ is safer than $BASHPID in some namespace contexts
        exec -c "${BASH:-bash}" --norc --noprofile -c '
enable -f "/proc/self/fd/'"${FORKRUN_MEMFD_LOADABLES}"'" '"${ring_enable}"' ring_list
export LC_ALL=C
set +m
shopt -s extglob
'"$(declare -f frun)"'
frun __exec__ "$@"
' -- "${@}" 0<&${fd00} 1>&${fd11} 2>&${fd22}
        
        # (Exec replaces process, so we never reach here)
    }

    # 2. WORKER LOGIC (Clean Shell)
    shift 1 # Remove __exec__

    # # # # # SETUP # # # # #
    local cmdline_str ring_ack_str delimiter_val ring_init_opts pCode extglob_was_set worker_func_src nn N nWorkers0 arg fd0 fd1 fd2
    local -g fd_spawn_r fd_spawn_w fd_fallow_r fd_fallow_w fd_order_r fd_order_w ingress_memfd fd_write fd_scan nWorkers nWorkersMax tStart
    local -gx order_flag unsafe_flag stdin_flag mode_byte order_mode unsafe_flag LC_ALL
    local -ga fd_out P order_args

    LC_ALL=C
    set +m

    if shopt -q extglob; then
        extglob_was_set=true;
    else
        shopt -s extglob;
    fi

    # --- HELPER: Parse Ranges (N, N:M, :M, N:) ---
    parse_count() {
        local type="$1"
        local val="$2"
        local extglob_was_set=false

        case "$val" in
            +([0-9])) 
                # Static / Limit value
                ring_init_opts+=("--${type}=${val}") 
                ;;
            *([0-9]):*([0-9]))
                # Range value
                if [[ ${val%:*} ]]; then
                    ring_init_opts+=("--${type}0=${val%:*}") 
                fi
                if [[ ${val#*:} ]]; then
                    ring_init_opts+=("--${type}-max=${val#*:}") 
                fi
                ;;
            *)
                printf '\nWARNING: INPUT "%s" IS MALFORMED. IGNORING\n' "$val" >&2
                ;;
        esac

        [[ "$type" == 'workers' ]] && [[ ${val#*:} ]] && nWorkersMax="${val#*:}"
        
    }
        

    # Config Vars
    order_mode='buffered'
    unsafe_flag=false
    mode_byte=false
    verbose_flag=false
    delimiter_val=$'\n'
    ring_init_opts=()

    # Parse Arguments
    while true; do
        case "$1" in
            -k|--keep-order|--ordered)   order_mode='ordered'  ;;
            -u|--unbuffered|--realtime)  order_mode='realtime' ;;
            --buffered|--atomic)         order_mode='buffered' ;;
            
            -U|--unsafe)   unsafe_flag=true  ;;
            +U|--safe)     unsafe_flag=false ;;
            
            -s|--stdin)    stdin_flag=true  ;;
            +s|--no-stdin) stdin_flag=false ;; 
            
            -v|--verbose)    verbose_flag=true  ;;
            +v|--no-verbose) verbose_flag=false ;;

            -z|--null)    delimiter_val='' ;;
            
            -n|--limit)
                arg="${1#@(-n|--limit)?(=)}"; [[ ${arg}${2//+([0-9])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && ring_init_opts+=('--limit '"${arg}") ;;

            -l|--lines|--batchsize)
                arg="${1#@(-l|--lines|--batchsize)?(=)}"; [[ ${arg}${2//+([0-9:])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && parse_count "lines" "${arg}" ;;

            -b|--bytes) 
                arg="${1#@(-b|--bytes)?(=)}"; [[ ${arg}${2//+([0-9:])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && { parse_count "bytes" "${arg}"; mode_byte=true; } ;;
                
            -j|-P|--workers)
                arg="${1#@(-j|-P|--workers)?(=)}"; [[ ${arg}${2//+([0-9:])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && parse_count "workers" "${arg}" ;;

            -t|--timeout)
                arg="${1#@(-t|--timeout)?(=)}"; [[ ${arg}${2//+([0-9])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && ring_init_opts+=("--timeout=${arg}") ;;

            -o|--order)
                arg="${1#@(-o|--order)?(=)}";
                [[ ${arg}${2//@(realtime|unbuffered|buffered|atomic|order|ordered)/} ]] || { shift; arg="$1"; }
                case "${arg}" in
                    realtime|unbuffered) order_mode='realtime' ;;
                    buffered|atomic)     order_mode='buffered' ;;
                    order|ordered|"")    order_mode='ordered'  ;;
                    *)                   order_mode='buffered' ;;
                esac  ;;

            -d|--delim|--delimiter)
                arg="${1#@(-d|--delim|--delimiter)?(=)}"; [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && delimiter_val="${arg:0:1}" ;;

            --) shift; break ;;

            *) break ;;
        esac
        shift
    done
    unset arg

    ${extglob_was_set} || shopt -u extglob

    if ${verbose_flag}; then
        tStart="${EPOCHREALTIME//./}"
toc() {
    printf '\n%s finished at +%s us\n' "$*" "$(( ${EPOCHREALTIME//./} - tStart ))" >&$fd2
}
    else
toc() { :; }
    fi

    : "${nWorkersMax:=$(nproc)}"

    # Resolve Default Modes
    if ${mode_byte}; then
        : "${stdin_flag:=true}"
    else
        : "${stdin_flag:=false}"
    fi
    
    if ${stdin_flag}; then
        ring_init_opts+=("--return-bytes")
    fi

    # Initialize Ring
    if [[ "${order_mode}" == "realtime" ]]; then
        ring_init "${ring_init_opts[@]}"
    else
        ring_init "${ring_init_opts[@]}" --out=fd_out
    fi

    # Create Data Memfd
    ring_memfd_create ingress_memfd

    # # # # # MAIN # # # # #
    {
        # --- 1. RING COPY ---
        ( ring_copy ${fd_write} ${fd0}; ring_signal ) &
        
        # --- 2. RING SCANNER ---
        ring_pipe fd_spawn_r fd_spawn_w
        (
            exec {fd_spawn_r}<&-
            ring_scanner ${fd_scan} ${fd_spawn_w}
        ) &
        exec {fd_spawn_w}>&- 

        # --- 3. RING FALLOW ---
        ring_pipe fd_fallow_r fd_fallow_w
        (
            exec {fd_fallow_w}>&-
            ring_fallow ${fd_fallow_r} ${fd_write}
        ) &
        exec {fd_fallow_r}<&- 

        # --- 4. RING ORDER ---
        [[ "${order_mode}" == "realtime" ]] || {
            ring_pipe fd_order_r fd_order_w
            (
                exec {fd_order_w}>&-

                order_args=( "${fd_order_r}" 'memfd' )
                [[ "${order_mode}" == "buffered" ]] && order_args+=( "unordered" )

                ring_order "${order_args[@]}" >&${fd1}
            ) &
            exec {fd_order_r}<&- 
            export FD_ORDER_PIPE=$fd_order_w
        }

        # --- WORKER DEFINITION ---
        printf -v cmdline_str '%q ' "$@"

        ring_ack_str="ring_ack $fd_fallow_w"

        if ${stdin_flag}; then
            # STDIN PAYLOAD
            pCode='
            if (( REPLY < 1048576 )); then
                ring_pipe pr pw
                ring_splice $fd_read $pw "" $REPLY "close"
                '"$cmdline_str"' <&$pr
                exec {pr}>&-
            else
                ( ring_splice $fd_read 1 '"''"' $REPLY "close" ) | '"$cmdline_str"'
            fi'
            
        elif ${mode_byte}; then
            # BYTE ARGS PAYLOAD
            pCode='
            read -r -u $fd_read -N $REPLY A
            '"$cmdline_str"' "${A}"'
            
        else
            # LINE ARGS PAYLOAD (Default)
            if ${unsafe_flag}; then
                cmdline_str='IFS='"'"' '"'"' '"${cmdline_str}"' ${A[*]}'
            else
                cmdline_str+=' "${A[@]}"'
            fi
            
            if [[ ${delimiter_val} ]]; then
                printf -v delimiter_str '%q' "${delimiter_val}"
            else
                delimiter_str="''"
            fi
            
            pCode='
            mapfile -t -u $fd_read -n $REPLY -d '"${delimiter_str}"' A
            '"$cmdline_str"
        fi

        [[ "${order_mode}" == "realtime" ]] || {
            pCode+=' >&${fd_out[$ID]}'
            ring_ack_str+=' ${fd_out[$ID]}'
        }

        worker_func_src='spawn_worker() {
(
  LC_ALL=C
  set +m
  {
    ID="$1"
    shift 1
    ring_worker inc $fd_read
    while ring_claim; do
        [[ "$REPLY" == "0" ]] && break
        '"$pCode"'
        '"${ring_ack_str}"'
    done
    ring_worker dec
  } {fd_read}<"/proc/'"${BASHPID}"'/fd/'"${ingress_memfd}"'" 1>&${fd1} 2>&${fd2}
) &
P+=($!)
}'

        eval "${worker_func_src}"

        # --- SPAWN LOOP ---
        nWorkers=0
        while true; do
            read -r -u $fd_spawn_r N
            [[ "$N" == 'x' ]] && break
            
            target=$(( nWorkers + N ))
            (( target > nWorkersMax )) && target=$nWorkersMax
            
            for (( ; nWorkers < target; nWorkers++ )); do
                spawn_worker "$nWorkers"
            done
        done

        ${verbose_flag} && printf '\nSPAWNED %s workers (%s)\n' "${nWorkers}" "${nWorkersA[*]}" >&2

        # --- SHUTDOWN ---
        exec {fd_spawn_r}<&- {fd_fallow_w}>&-
        [[ "${order_mode}" == "realtime" ]] || exec {fd_order_w}>&-
        
        wait
        
        ring_destroy
        exec {fd_write}>&- {fd_scan}>&- {ingress_memfd}>&-

    } {fd_write}>"/proc/${BASHPID}/fd/${ingress_memfd}" {fd_scan}<"/proc/${BASHPID}/fd/${ingress_memfd}" {fd0}<&0 {fd1}>&1 {fd2}>&2
    exit 0
  ) {fd00}<&0 {fd11}>&1 {fd22}>&2
}

_forkrun_bootstrap_setup() {
## HELPER FUNCTION TO LOAD THE RING LOADABLES USED BY FORKRUN

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

        if (( outN < 6 )); then
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
    local -a candidates 

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
        enable -d "${ring_funcs[@]}" ring_list 2>/dev/null || true
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
declare -a b64=([0]=$'109166 54584\nmd5sum:7b5381cd30981f39df8cbd4bfe2afb3c\nsha256sum:3860de580062d8808d2b33bf30947d99ab9494607b6e7740b1ef9a01070a6b07\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n00000000\n0000000\n000000\n00000\n2giM\n0000\n000\n04\n1M\n01\n0g\n00\n__\n0>yYJR8zk3_i8fEg4y3MA1yYDR8\034vQlchw81.-?c0fw>)1-fzb-;4?e?c<?9g0A?o:4:g+1-4-E08{2w0w=w+1}g;3w0w{e02=U08{1k+5g+2-1:1!{5wX=m3I+4+4:5:m3I{1oiM{5xb=eo4=Vwg+g+g:o;2oL=9zs=CdM{3E0w{6w3+1+1:1w;82_=weY{20XM{5wa=v0E+4+s:4:CbM{2oT=9zs=2-F-w-w:o;2EL=azs=GdM{3g.{d>=2+1gVnhA1:egL=V2Y{3AbM{,1=7<=4+5fBt6g4:U08{3w0w{e02=c-M-w+kulQp0o~*g=1iVnhA1:9yY=CdM{2oT=ew2=q0c=1-g:w:1g;4telg>?7>:3A-w0,.:d-g:k}M;4telg2oYJcIaBrzwhM3IJUMpZ5vyS<N[3:hg:g:q:2?8hcog20w0ylggy0q0ar408280<0>I4g;w4>5:iw;58:upbAfcxJTjYW1YjIChYy7MmIv89PfjdG0CR8nv4gfGRj34KXQ6YlilKYw8Dx1zT9j7qGfpHeFTQFXPz_2tWSSC5vClUo0aN0yUFFHb8HEDBg@FGsyt9rIvlkSGw!?2}w$2Y:w$4I:w$6k:g$7c:g$7I:g$84:g$8Y:g$ac:g$bs:g$ck:g$dQ:g$eU:g$<1;g$141;g$2c1;g$2Y1;i$3o1;i$3Y1;i$541;i$5o1;h$5U1;i$6o1;i$7g1;i$7A1;i$841;i$8M1;i$9g1;i$9I1;i$a81;i$aA1;i$bc1;i$bE1;i$bY1;i$co1;i$dg1;i$dA1;i$e>;i$f>;i$fw1;i$0A2;i$182;i$1A2;i$2A2;h$302;i$3w2;i$3Y2;i$4s2;i$4Y2;i$5s2;y$6o2;i$6Q2;i$7o2;i$7Q2;i$8c2;i$8E2;i$9o2;i$9Q2;i$ag2;i$aI2;i$bM2;i$c82;i$cE2;i$dA2;i$dU2;i$ek2;i$eQ2;i$fk2;i$.3;h>U0Ufo=M+1o3;h>U08fk=M+2s3;h>U08fc=M+3A3;h>U0Uf8=M+4E3;i>k<cI{21.{6k3;h>U0Efg=M+783;h>U0Ufc=M+8E3;h>U0Ufk=M+9Q3;h>U0Efc=M+bo3;h>U0ofk=M+cw3;h>U0Ufg=M+dI3;h>U0Ef8=M+eU3;h>U0Efo=M-44;h>U0Efk=M+144;h>U0ofo=M+2M4;h>U0ofs=M+4<;h>U08fg=M+5g4;h>U0ofg=M+6w4;h>U08fo=M+7I4;h>U0Efs=M+8M4;h>U0of8=M+9Q4;h>U08fs=M+b44;h>U0ofc=M-1Iqm9zbDdLbzo0r6gJr6BKtnwJu3wSbjoQbDdLbz80nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0oCBKp5ZSon9Fom9Ipg1Urm5Ir6Zz07xCsClB06pFrChvtC5Oqm5yr6k0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0pSlQnTdQsCBKpRZSomNRpg1yqmVAnS5OsC5VnSlIpmRBrDg0tmVyqmVAnTpxsCBxoCNB06RxqSlvoDlFr7hFrBZxsCtS065Ap5ZytmBIt6BK07dQsCdMug1PrD1OqmVQpw1vnSBPrScOcRZPt79QrTlIr0,tnhP06lKtCBOrSU0sTBPoSZKpw1zr6ZzqRZDpnhQqmRB06pOpmk0r7dBpmISd>PpmVApCBIpjoQ071Opm5Adzg0rT1BrzoQ07lKr6BKqM1JtmVJon?rmJPt6lJs3oQ06RJon0Sd0,rSNI07dQsCNBrw1vnSdQun1BnS9vr6Zz079Bomg0tndIpmlM05ZvqndLoP8PnTdQsDhLr>PundFrCpL05ZvqndLoP8PnTdQsDhLr6M0sSxRt6hLtSU0rm5Ir6Zz06dLs7BvpCBIplZOomVDpg1Pt6hBsD80pD1OqmVQpw1JpmRzq780pCdKt6MSd>CsThxt3oQ06lSpmVQpCg0nRZzu65vpCBKomNFuCk0sThOoSxO07dQsClOsCZO06RBrndBt>zr6ZPpg,sCBKt6o0pC5Ir6ZzonhBdzg0rmlJoT1V06pTsCBQpg1Pt79zrn?nRZBsD9KrRZIrSdxt6BLrw1TsCBQpg1PundzomNI071LsSBUnSRBrm5IqmtK071Fs6k0sT1IqmdB07dQsCVzrn?rmlJsCdEsw1vnThIsRZDpnhvomhAsw1OqmVDnSdIomBJnTdQsDlzt>OqmVDnSdLs7BvsThOtmdQ079FrCtvpCdKt6NvsThOtmdQ079FrCtvs6BMplZPt79RoTg0sSlQtn1voDlFr7hFrBZCrT9HsDlKnT9FrCs0r7dBpmJvsThOtmdQ079FrCtvpC5Ir6ZTnT1EundvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt>OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZPqmtKomNvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt>OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZxoSJvsThOtmdQ079FrCtvoSNBomVRs5ZTomBQpn9vsThOtmdQ079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt>OqmVDnSBKp6lUpn9vsThOtmdQ079FrCtvqmVDpndQnTdQsDlzt>OqmVDnSBKqnhvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt>OqmVDnTdBomNvsThOtmdQ<tcik93nP8KcM17j4B2gRYObz8Kdg17j4B2gRYObzk0hQN9gAdvcyUT<tcik93nP8Kcj?hQN9gAdvcyUNd>7j4B2gRYObz4T<tcik93nP8Kczs0hQN9gAdvcyUOe>7j4B2gRYObzcP<tcik93nP8KcPw[g>0<0.>0<0.>0<0.>0<0.>0<0.03?c03g03?c?M09?c?M<?c?M03?c?M03?c?M<?c?M0d?c03g03?c02w03?c?M0b?M>w03?c?M03?c?M07?w?M03?c?M03?c?M05?c?M020<0.>0<0.>0<0.>0<0.>0<0.>0<0.>0<0.>0<0.:40.0b:4:2}jqmAd;20c84+g0b0<:g+7kqqgA;c0P.0>}jqmAd;40c84;g:5mBF3g0>g3o1;4:1tFqgQ;o0Uwg0>:2gApo6;70eM4;g:B96m1w?203T1;4:9uhBwo;A?wk0>:27Apo6;a?Q5;g:y96m1w?2M0o1g0<:behBwo;M08Mk0>:2UApo6;d02U5-;a3s=2+2wT=7zu=2-Mk=83u=2+,k=a3L=2+2Ydg{azL=2-ecM{c3L=2+1Nd=czL=2+1Uew{e3L=2+3ndg{ezL=2+3Tdg=3M=2+1gdg=zM=2+1tdg{23M=2-Rd=2zM=2+37dM{43M=2+1Xe=4zM=2+1ScM{63M=2+1Zd=6zM=2+1Ncw{83M=2-ddM{8zM=2-Fdw{a3M=2+2NdM{azM=2+1ncw{c3M=2+1Fd=czM=2+2Xdw{e3M=2-udM{ezM=2-be+3N=2+1BcM=zN=2-3dg{23N=2+2qcM{2zN=2+2Meg{43N=2+13e=4zN=2+3Tcw{63N=2+2Idw{6zN=2-UeM{83N=2+2zdM{8zN=2+36cw{a3N=2+3BdM{azN=2+2fdM{c3N=2+1Xdw{czN=2-Jcw{e3N=2-tdw{ezN=2+1Be+3O=2-Sdw=zO=2+12dw{23O=2+2zcw{2zO=2-wcw{43O=2+3Ie=4zO=2+2pdg{63O=2+2Pd=6zO=2+2wNM{7zO=2+2wXM{83O=2-ecM{a3O=2+2ecM{azO=2-MIg{bzO=2+30XM{c3O=2+1Uew{e3O=2+3yd=ezO=2+,HM{fzO=2+3wXM=3P=2+3Tdg{23P=2+2ocw{2zP=2+20Nw{3zP=2-0Y=43P=2+1tdg{63P=2+2YcM{6zP=2+2MHw{7zP=2-wY=83P=2+37dM{a3P=2+2Zd=azP=2-0Hw{bzP=2+10Y=c3P=2+1ScM{e3P=2+1Ncw{ezP=2+2MHg{fzP=2+1wY+3Q=2+1Ncw{23Q=2-Fdw{2zQ=2+30Gw{3zQ=2+20Y=43Q=2-Fdw{63Q=2+1ncw{6zQ=2+,Gw{7zQ=2+2wY=83Q=2+1ncw{a3Q=2+14dg{azQ=2-wNg{bzQ=2+30Y=c3Q=2+2Xdw{e3Q=2+3UcM{ezQ=2+2MGg{fzQ=2+3wY+3R=2-be=23R=2+2FcM{2zR=2+1wGg{3zR=2-0Yg{43R=2-3dg{63R=2-se=6zR=2-gGg{7zR=2-wYg{83R=2+2Meg{a3R=2-We=azR=2-MFg{bzR=2+10Yg{c3R=2+3Tcw{e3R=2+1jdM{ezR=2+3wF=fzR=2+1wYg=3S=2-UeM{23S=2+36cw{2zS=2+2wF=3zS=2+20Yg{43S=2+36cw{63S=2+2fdM{6zS=2+1wMM{7zS=2+2wYg{83S=2+2fdM{a3S=2+2Wcw{azS=2+3wMM{bzS=2+30Yg{c3S=2-Jcw{e3S=2+28e=ezS=2+2MJ=fzS=2+3wYg=3T=2+1Be=23T=2+1GdM{2zT=2+1gF=3zT=2-0Yw{43T=2+12dw{63T=2-wcw{6zT=2-gIM{7zT=2-wYw{83T=2-wcw{a3T=2+3Ddw{azT=2-0F=bzT=2+10Yw{c3T=2+2pdg{93u=4^a3u=1w:4)azu=1w:8)b3u=1w:c)6zv=1w;1k)73v=1w;2M)7zv=1w;38)d3u=1w;4k(zv=1w;4o)4zv=1w;4s)53v=1w;4w)1zv=1w;4E)33v=1w;4I)f3u=1w;4M)3zv=1w;4Q(3v=1w;4U)13v=1w;4Y)5zv=1w;5(dzu=1w;54)fzu=1w;58)e3u=1w;5c)c3u=1w;5g)2zv=1w;5k)23v=1w;5o)ezu=1w;5s)bzu=1w;5w)63v=1w;5A)czu=1w;5E)43v=1w;5I)ezT=,:g)f3T=,:k)fzT=,:o(3U=,:s(zU=,:w)13U=,:A)1zU=,:E)23U=,:I)2zU=,:M)33U=,:Q)3zU=,:U)43U=,:Y)4zU=,;1(53U=,;14)5zU=,;18)63U=,;1c)6zU=,;1g)73U=,;1o)7zU=,;1s)83U=,;1w)8zU=,;1A)93U=,;1E)9zU=,;1I)a3U=,;,)azU=,;1Q)b3U=,;1U)bzU=,;1Y)c3U=,;2(czU=,;24)d3U=,;28)dzU=,;2c)e3U=,;2g)ezU=,;2k)f3U=,;2o)fzU=,;2s(3V=,;2w(zV=,;2A)13V=,;2E)1zV=,;2I)23V=,;2Q)2zV=,;2U)33V=,;2Y)3zV=,;3(43V=,;34)4zV=,;3c)53V=,;3g)5zV=,;3k)63V=,;3o)6zV=,;3s)73V=,;3w)7zV=,;3A)83V=,;3E)8zV=,;3I)93V=,;3M)9zV=,;3Q)a3V=,;3U)azV=,;3Y)b3V=,;4(bzV=,;44)c3V=,;48)czV=,;4c)d3V=,;4g)1g-nFi?5U4<r30s8A<?7g:s:W2s?3k2:iMUgzw923xyd0Q8e88M4igUExwl13z231Asek60a3z19MMUEgsoe84bc3xx2PgUggIUe24wb0T>2wUMhccea4763y12P0UogIQe44be3wxd2T0e2cf6PcTei0VgwMq61oM4zgee0yw;2k:I2A?eU}ggUgwM993B1e2wUgggU8hMI2kwEe44ke24Ab8:c:1Qaw?cM4;113x230AUeo09l2wUggMU8igI0j:eg;2gaM?xgM;123x2f0A8e68U3gwUwzgh53yyc1k4ec8o6ggUUwMt73E090ZQ12wUUggUMggUEgwUwgwUogwUggwU8hgI;1A:d<?d0T?3Va:4Ie48Y2hMUozwd23y2d148ea8M5ggUMxwp43zy31QAeI0c3D0Qe2cf6PcTePR0eI0e31Uo6z0md18U3zM82XwEee4cec44ea48e848e648e448e244b<w;2s.?q6;cw}gwUgzM923xye0Qke88Q4gwUEz0l13z261A4ee8c7h0Vg0FQa3zx43z113yx23y123xx23x123wx52M1c:W<?eNw;G0w;58e48Y2hMUozwd23y2d148ea8M5ggUMxwp33zy31QEeY0w3rg4a3zx33z113yx23y123xx23x123wx42M;4w:U0w?P68?9g1:kwUgzM973xye0Qke88Q4gwUEz0l13z261A4ee8c7iwXw20dr.UUgMUMggUEgwUwgwUogwUggwU8;I:x08?21A?2H,;54e48o2i0Q6h8Y3zwh5zgl5z0pbwMs3iwka30s8h0JA:J08?a1H0>e2M;4Ie48Y2hMUozwd23y2d14kea8M5ggUMxwp43zy31QAeU0c3_g4a3zx13z113yx23y123xx23x123wx22MaM3wz3NIPdPIZg3K03wMu61EM5zgie0UY2<M:s0M?y7o?ds1:kwUgzM973xye0Q8e88Q4gwUEz0l13z261A4ee8c7iwWgwwg3bw4a3zx13z113yx23y123xx23x123wx72M?7:6M3;ou;hg:113x230AAec7se44ce2?s:z0c0<xU0>5}44e48c2igUMtMUggMU80,;2I0M?u7w?3Y}ggUgwM993y1N3x133ww07:cM3?2ou;hg:113x230AAec7se44ce2?Y:X0c?cxU?3w0M;48e48Y2gwUozwd13y2614oea8c5hMXM.d_.Eea4ce844e648e448e244b:7:2M40>Ev;hg:113x230AAec7se44ce2?s:j.?9xY0>5}44e48c2igUMtMUggMU802w;1I1;O7M?c[ggUgxw963xy30Qgec09c2wUogMUgggU8hgI07:9w40>svg?hg:113x230AAec7se44ce2>8:K.?8NZ?3E0w;48e48Y2gwUozwd23y2d148ea8M5ggUMxwp13zy31QAeA05E2wUUgMUMggUEgwUwgwUogwUggwU8igI07}g5;Mw;hg:113x230AAec7se44ce2?M:90k?62;2A}48e48U2ggUoxwd63y2314gek09A2wUwgMUoggUggwU8igI08:5w5?3sw;Lw:113x230Agec09q2wUggMU8hwI0c:7M50>Uwg?IM4;123x2e0A4e68o3hwUwwMh43B02IMEe84ce644e448e24Eb<w;2M1g0>8c?dY1:gwUgzM923xye0Q8e88Q4gwUEz0l13z261Aoee8c7h0VwrMEee4cec44ea48e848e648e448e248b;E:_0k?9y4?2v.;44e48o2hwUowMd43z02PwEe64ce444e24cb02M:E1w?38o?awe:ggUgxw933gp9zMee18Q5z0q3,d11wEc,x22M;2g;1o1w?z9g?7o}ggUgxw963xy30Qgec09C3xx33x113wwE:w0o?eik;S.;44e48o2hwUowMd43A02QwEe64ce444e24sb03w;2I1w?@9k?581:gwUgzM923xye0Q4e88o4ggUEwMl43D1N2wUEgMUwggUogwUggwU8hgI?3:3E1w?79s0>o1:gwUgzw913xy60Q4e88c4h0UMqMEe84ce644e448e24sb;M:70s;yo0>G0M;48e48U2ggUoxwd13y2314gec0cw0wEe84ce644e448e248b6:5070>4CM?wg4;143x03v<e2-16McXAfz/O8;2s8;Hfz/ZMy;A@v/P2c?53V/Yc9g?tfD/VMN?34@v/D5E?2PW/ZImM?ufH/VNt?38@L/f5Y0>jX/_Ipw?hfL/PNO?2I@/_77g?fPX/ZIt;7fP/XNQ;Y_f/_7g?5PY/Zctg?vfP/ONV?2Y_f/v7A?dPY/_cug?_fP/UNW;E_v/T7E0<zZ/_cvg?BfT/NN@?2Q_v/P7U?ezZ/@cvM?3fX/QO10>0_L/b8c?8P@/_cx;KfX/TOj?3E_L/_9c0>3/_YYBg?ff/_VOm0>U//L9s?aP/_YICM?Uf/_NY07w0t0,06M0q>A06?n>o05g0k>c<w0h>?3M0e?Q03?b?E02g08?s>w050.?M020<:1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3w4^Lp6lSbTdEriZCrT9HsDlKbThJs2ZCrT9HsDlKbBxom%0f3wQc2ME920s61gg30w403MUd30Ia2gw71wk40M81079FrCtvp6lPt79Lug1OqmVDnTtLsCJBsy1rqmVzv6hBoRQwmQp4ng15lAp4nR99jAtvh45kgg1OqmVDnSBKp6lUpn80biRyunhBsORJonwZ079FrCtvpC5Ir6ZTnT1Eunc0hlp6h5ZiikV7nQBehQljl5Z4glh1079FrCtvpCdKt6M0h6lPt79Lui1OqmVD06V2unhBsQRxu>OqmVDnTtLsCJBsw1OqmVDnSBKpSlPt?BsOUBr7k0tT9Ft6kEpChvsT1xtSUI829Un6Uyb20Oag1Apmc0sCBKpRZxoSIwf4p4fy0YhAhvjRlkfw1OqmVDnSNFsTgwmRp1kBQ0c>TsCBQpixBtCpAnShxt64I82pLrCkI83wF02QJtSZOqSlOsORJonwZ<pfkAJilkVvhAZigQlvhA5cj491gQI0bThJs>qpn9LbmdLs7AwqmVDpndQ079FrCtvrmlJpChvoT9BonhB83Nmgl8@079FrCtvsT1IqmdB059BrT9Apn8wrTlQs7lQ079FrCtvoSZMug0Jbm9Vt6lPfg1OqmVDnTdBomM0u0E0biRQqmRBrTlQfg16h5ZfkAh5kBZgil1507tOqnhBa6lSpChvp65QoiMCtyMUag1OqmVDnTdFpSVxr>Pq7lQp6ZTrBZOtM1Ps6NFoSkwpC5Fr6lAey0BsM0Jbm9Vt6lPc3Q0bShBtyZPq6Q0kSlxr21JpmRCp?BsPEwrCZQ865K865OsC5V06RBrmpAnSdOpm5Qpi1ComBIpmgW82lP05dBpmIwpCg0kT1IqmdB86hxt640k6xVsSBzomMwpC5Ir6ZT07lKrT9Apn9Bp?JbmNFrClPbmRxu3Q0biRIqmVBsPQ0kAlgj5A0sCBKpRZIqndQ079FrCtvrmlJpChvoT9BonhB07tOqnhBa6pAb20CtC5Ib20Uag1OqmVDnT1Fs6k0s6BMpi1ComBIpmgW82lP02QJrTlQfg1OqmVDnSdLs7Awf4Zll3Uwf4Befw1zr6ZPpg1jhklbnRd5l>TsCBQpixBtCpAnSlLpyMw9ClLpBZPqmsI83wF06NPpmlH06RBrmpA<pFr6kwoSZKt79Lr>OqmVDnSpzrDhI83N6h3Uwf6dJp3U0rmRxs3Ew9nc0rBtLsCJBsDc0kABehRZ9jAt5kRhvh4Bmildfkw1OqmVDnSBKqngwmQpcgktjng1iikV7nQ91l4d8nRdcjRhj<NFsTgwr6Zxp65yr6lP06VnrT9Hpn9Pjm5U<dOpm5Qpi,qn1B07lKqSVLtSUwoSZJrm5Kp3Ew9nc0sCBKpRZMqn1B83N1kB9YkAg@85JnkBQ0hAZiiR9ljBZ4hk9lhM13r65Fri1yonhzq>OqmVDnSpBt6dEpn80kDlK87dzomVKpn80sCBKpRZPoS5KrClO83NCp3UwmTdMontKnSpAng15lAp4nR99jAtvkRh1kBp507dEtnhArTtKnT80lSZOqSlO86dLrDhOrSM09mNR2w0Bp>5lAp4nR99jAtvikV7hldknQlfhw1QsDlB<NLpSBzomMwpC5Ir6ZT06NPpmlH83N6h3Uwf4Z6hzUKbyU0biRIqmVBsP0Z06pLsCJOtmVvqmVMtng0sCBKpRZFrCBQ07tOqnhBa6pAnTdMontKb21PoDlCb21Pr6lKag1elkR184pBt6dEpn80p79V05dFpSVxr21BtClKt6pA07dEtnhArTtKnTs0pC5Fr6lA87hL86dOpm5Qpi1xsD9xujEw9nc0sCBKpRZComNIrTs0biRTrT9Hpn9Pfg1OqmVDnTdzomVKpn80pCZOqT9RrBZOqmVDbCc0kQl5iRZ5jAg0sCBKpRZzr6lxrDlMnTtxqnhBsw1jqmtKomMwqmVDpndQ<Vljk4wimVApnxBsw0JbmNFrmBQfg1OqmVDnTdBomMwf4p4fw0Jbn9Bt7lOryRyunhBsM13r6lxrDlM87txqnhBsw11kAtvjk5o02QJpT9BpmhV02lIr6ga079FrCtvsSBDrC5I83N6h3U0sCBKpRZLsChBsw15lAp4nR99jAtvhkZ602lIr6g0sCBKpRZxoSI.mdH869xt6dE06pLsCJOtmVvrTlQ02QJtSZOqSlOsP0Z079FrCtvoSNxqmQwmRp1kBQwmQp4ng13sClxt6kwrmlJpCg0sCBKpRZzr65Frg1CrT9HsDlK85J4hk9lhRQwhmVxoCNBp0E0kABehRZ2glh3i5Z9h5w0rANFrClPjm5U07tOqnhBa6pAnSNLoS5InTdFpOMw9CZKpiMwe2A0biRQqmRBrTlQ<BKqnhFomNFuCkwsCBKpO1TqnhE86dLrCpFpM1FrCc[7tOqnhBa6pAnStIrS9xr5ZxoSII82pMs2MwsSBWpmZCa7,aiA;1TsCBQpixCp5ZMqn1Bb20CrT0I87dFuClLpyxLs2AF06BKtC5IqmgwrDlJpn9FoO1FrChBu21CrT8wqmVApnxBp21xsD9xujEw9nc[6pLsCJOtmUwmQh5gBl7ni0BsPEBp3Ew9ncwpC5Fr6lAey0BsME;1OqmVDnSZOp6lO83N6h3Uwf516m7NJpmRCp3UwmTlKrT9Apn9Bp5Q0pCZOqT9Rry1rh4l2lktt879FrCtvoSNxqmQwr7dBpmIwpC5Fr6lAey0BsME}pCZOqT9Rry1rh4l2lktt879FrCtvsSlxr21ComBIpmgW82lP2w;7tOqnhBa6lSpChvqmVDpndQnShxt64I82pSb20Uag?tT9Ft6kEpChvt65OpSlQb20Cqn0I87dFuClLpyxFs2AF+79FrCtvsT1IqmdB83N9jzUwf4Zll3Uwf4Z6hzUwf4N5jzUwmSdIrTdBng{2ZPuncLp6lSqmdBsOZPundQpmQLoT1RbSdMtj0LoS5zq6kLqmVApnwPbTdFuCk?7tOqnhBa6pAnSpxr6NLtOMw9CBMb21PqnFBrSoEqn0Fag=1CrT9HsDlK85J4hk9lhRQwsCBKpRZxoSIwr7dBpmIwpC5Fr6lAey0BsME*79FrCtvpC5Ir6ZT83Ngil15fy0YhABchjUwmShOulQ0YMYu@Ay3X0x8wYg8MM;fcf7LF8w@M8i8I5apc0<y5M7g2_Z18wYg8MM(03P3NXWglf_djOI?3_9jWI?3cPcPcPcPcPcPcPcPcP46X}fYBbaM?cPcPcN1KM4;3_9iiI?3cPcPcgrI2:_OksH;PcPcP46X0M;fYB5aM?cPcPcN1KMg;3_9gOI?3cPcPcgrI5:_Ok4H;PcPcP46X1w;fYB_aI?cPcPcN1KMs;3_9viH?3cPcPcgrI8:_OnIGM?PcPcP46X2g;fYBVaI?cPcPcN1KME;3_9tOH?3cPcPcgrIb:_OnkGM?PcPcP46X3:fYBPaI?cPcPcN1KMQ;3_9siH?3cPcPcgrIe:_OmYGM?PcPcP46X3M;fYBJaI?cPcPcN1KN:3_9qOH?3cPcPcgrIh:_OmAGM?PcPcP46X4w;fYBDaI?cPcPcN1KNc;3_9piH?3cPcPcgrIk:_OmcGM?PcPcP46X5g;fYBxaI?cPcPcN1KNo;3_9nOH?3cPcPcgrIn:_OlQGM?PcPcP46X6:fYBraI?cPcPcN1KNA;3_9miH?3cPcPcgrIq:_OlsGM?PcPcP46X6M;fYBlaI?cPcPcN1KNM;3_9kOH?3cPcPcgrIt:_Ol4GM?PcPcP46X7w;fYBfaI?cPcPcN1KNY;3_9jiH?3cPcPcgrIw:_OkIGM?PcPcP46X8g;fYB9aI?cPcPcN1KO8;3_9hOH?3cPcPcgrIz:_OkkGM?PcPcP46X9:fYB3aI?cPcPcN1KOk;3_9giH?3cPcPcgrIC:_OnYGw?PcPcP46X9M;fYBZaE?cPcPcN1KOw;3_9uOG?3cPcPcgrIF:_OnAGw?PcPcP46Xaw;fYBTaE?cPcPcN1KOI;3_9tiG?3cPcPcgrII:_OncGw?PcPcP46Xbg;fYBNaE?cPcPcN1KOU;3_9rOG?3cPcPcgrIL:_OmQGw?PcPcP46Xc:fYBHaE?cPcPcN1KP4;3_9qiG?3cPcPcgrIO:_OmsGw?PcPcP46XcM;fYBBaE?cPcPcN1KPg;3_9oOG?3cPcPcgrIR:_Om4Gw?PcPcP46Xdw;fYBvaE?cPcPcN1KPs;3_9niG?3cPcPcgrIU:_OlIGw?PcPcP46Xeg;fYBpaE?cPcPcN1KPE;3_9lOG?3cPcPcgrIX:_OlkGw?PcPcP46Xf:fYBjaE?cPcPcN1KPQ;3_9kiG?3cPcPc_OnyzM?PcM~-;i8QZ4qE0<yd1gGG0>8evxQ5kyb1sWe0>8xs1Q2v_w3N@[ccf7U[i8QZUqA0<yddtGF0>8avV8yv18MuU_ic7U0Qw1NAzh_Dgki8I5BoU0<y5M7g8_@1C3NZ4?333N@[fcf7LG0fpSF:tiJli8cZcEY;18yulQ34ydfkWc?3Eev/_@xA//NwlRGg;lT33NY0MMYvw}3P3NXWWnv//cPcPcPcPci8n_3Ug70w0.lp1lk5kioDQLBI;1lkQy9@Qy3X23EO_T/Qy9Nky5M7gfi8DvWcLY/@0v0f_nngsi8f484O9VAy9TP7imRR1n45tglXFS_H/MYv<C9XAy3Ng59atV9znU1WdnW/Z8ytVcyv99ysl8ysvERfT/Qf6h3k0<y9X@xS_f/i8Rg_Qy9NQy912h8ylgA2eyx@L/i8Jk90x8yuV8yst8ysfEDLT/Qyb32hcyu_6h0L_0ewZ_f/i8RU0uxQ@L/j8DKi8D7W2DX/Z8ytZ8ysnE7LP/Qydu07ElvH/Qy9TAy9N@wa@/_j8DDioD6Wf_X/Z8znw1W3rW/Zcyup8ysvEW_H/QO9XQC9NewM@L/i8DvW2zW/Z8yu_EcfH/Qy5M0@4TM;8Jgafr2g7lvw@843UiK:ict491w}W2zZ/Z8zngA6bEa:j8DTNM[i8D3WcTX/Z8ysp8yQgA64AVNDhww3w0tlK3eO9Qlz79j8Dyi8DLWdDV/_H6MYvw}15cs1cyu5cyv98yuV8ysvEPfD/Qy9X@yk@v/j8DTW8PV/Z8wYgwj8DDmRR1n45tglXFufD/MYvx{j8DSi8QZXKr/P70W9_V/_HMgYvh;i8DKi8QZLK7/P70W8vV/_HGgYvh;MMYvw}18yu_EwfD/Qy9XAydfoXA/Z8xs0fxgr//HPSpCbwYvx{kX_2:i8fIgezN@v/i8n0vwN8wYh0mYdC3NZ40>8zjT1V/_cvoNMewM@L/ysu5M7wFKxY;18zngA88B490PEB_H/UJY90N8yggAW8HX/Z8yNgAi8nivO6_LM;eyn@v/i8n0vBF8wYh0ic7w0RL33N@4[36h1gw<ydt2goKwE;18znMA8ex7@v/i8Jk91wfJxa3UJ@0@AJQfQy9Mkz1Uhi0@AR83Qj1i8n0tafFk//MYvw}2_Mw;ewK@v/i8n0vVuU0>?eAP//3N@[4z1U0HHOmqgkQy9@QydfoXv/Z8w@NgW6PU/Z8xs1QlU0Ucnliw7w107lcKE>?2@ww11<ydfkvw/YNMewQ@v/ysa5M7AuKE>?2@ww11<ydflTv/YNMewm@v/ysa5M7xoi8f4k8DgmYcf7Ug[bE2:i8DuLPY1;NMezI@L/ysa5M7DmWc7W/@3e1pRA37ii8DuLPY1;NMezb@L/ysa5M0@8tv/_@KL3N@[cnVrMlwTv/i8RY9118K2Vom5xom5w0i8BY90x8ykgA8cnVvQgA4eyY@f/i8JY90y5M8D2u1C9l2g8W8zU/@bl2g8Wl//Yf7U[NvBL1i3t/_7h2gwm5xo0cnVvQgA4exZ@f/i8JY90y5M8D2us7Fbv/_SqgpCoK3N@4[11lQ5mgll9yvl1l5lji87Ii.?8AY94ydfg7x/_E7vv/Qy5M0@47<?80Ucg@4WM40<yddnLx/Z8ysvELfD/Un03UnY:i8I5boE?bEo:Lw4;18zjQ_U/_NMmqF:g;4yb2exW@v/j8IZwWg0<S5_M@5T:4kNOj7_grz//_Ki4;2W0M;bU<a?WcLT/Z8w_z_3Uip2w?cvqW>2w<y9NQy91k2A?3ES_z/XZk:W07T/Z8zjQ5Uf/i8D3W6bS/Z8xs1Q6rEa:cvp8ysvETLv/Qy9h2g8i8n0vN98xtJ1L<;1c3Q_zj8BA90x8zjRTT/_W2rS/Z8xs0fx0Q1;NZHEa:i8D7W9XT/Z8xs0fzLk;18ykgA4eDQ:3NY0j8IZIqc?cs5HWc{1dxvYfx2j/_Z9NMs}i8I5Aac0<z7w0>=i8I5vGc?cq06<;18yMlMEM?ict<}18yMlxEM?ict08}18yMliEM?NA0E<yb1kuz0>8NQ0M}4yb1jyz?36g2A0i8I5bqc?8IZPVw0<z7w0.8{xvZV7z70i874i.?5JtglN1nk5ugl_33NZ?8IZEFw?bE>;i8RQ943EC_r/Qy5M7_CWYMf7Q?w7w1?@48LX/@A6_L/A4z7h2gg.;4ydfoLx/_E@_j/Qy5M7gucvqW2w;4y9N@xTZL/i8n0vwF8ykgA6eIc3NY0ict491w<;LXY;3Elvn/Qy5M0@er0w0<Odd419MuU2cv_Efvn/Qy9MQy5M0@eQgw0<yb1ta70>8yOx8yTQ0i8n_3UiJ0w?hj7A3N@[ezbZv/i8JZ24y3Ngxdzmg40ky5_TnFLg1w0>ceucfzTI20>8zjTkSL/W4_Q/Z8ysd8xs0fxec7?20e4MfxhE2?20u<O3Ukg0w?w7w2?@51w80<yb7t@x0>8yQgA24y9wOw10>8yQgA44z7wP>;1:i8C38<0<ybh2goj8CPk<0<y9wPw1?2b12h8NUd0.{4z7wRw1=NEdw.;cq3oM4;23@<fzBA80>8NQgA2f//Zdzmk8w@w2ics49f//ZdzmP544O9Vmof7Ug[4ybng2W3w;4yddoHq/Z8yt_EGfr/Un03UiU.?KwI;18zjmdT/_i8DvW8PS/@5M0@4p0k?bEa:i8QRtZX/Qy9T@xMZL/xs0fx7w5?2W3:4yddpfr/Z8yt_Elfr/Un03Uik1g?KwA;18zjmLTv/i8DvW3zS/@5M0@4G0k?bE8:i8QRqdL/Qy9T@wsZL/xs0fx4g6?2W3:4yddgPp/Z8yt_E0fr/Un03Uio1w?KwA;18zjmKSL/i8DvWejR/@5M0@4l0k?bE8:i8QR8ZH/Qy9T@z8Zv/xs0fx407?2W2:4yddhbu/Z8yt_EHfn/Un03Ug@,?KwE;18zjk1SL/i8DvW93R/@5M0@4Nwo?bE8:i8QR6dX/Qy9T@xQZv/xs0fxiA70>8yMnRDM?icu0m<{3FBg:Yvh;i8QRTtT/Qy9TQC9XKzeZf/xs0fxe3Z/@W2w;37Si8DvWavP/YNQAy5M4wfit19ytrFMfT/Sof7Qg0<MFUQy9S4z1U0h8atx8Mvw4i8Q4g4z1W098ysnFpfT/MYvw[NZAyduMWW2w;ewUY/_i8n0vxd8yNlsDM?i8C2a<;Yvh;i8f524AVXg@5Y_T/Qyb12h8yNQUDM?i8n03UiD1;3UB11;i8dY90w03UUR1;NEdw.;sq3oM4;5cyTgA24O9IP>;NXkO9IPw10>cyrd8.?3NY0ioIY9bE9:i8QRQJT/@xbZf/xs0fBc19wYg82sldeulRSQ24Xnkbicu3m<?f//Z8yUIw.?i8Kja<?cq3ow4;4fJEdw.?i3Dh3Vi3og4?8j03UjQ0M?icu32<;4:N_XU120w0WerO/YN_XU120w0ygk9B;WdjO/YN_XU020w0ygnPAM?WcbO/YN_XU120w0ygntAM?Wb3O/YN_XU020w0ygn7AM?W9XO/Z8zjTfAM?ygmNAM?W6PP/@5M0@8l08?8IZJFc?bE02;Lwg:NMexdYL/yPSzAM?Kw08;NMbU4:W3rO/@bfoyj?2W.;370Lw8;3E7_b/UIZtpc?bE1:cs2@0w;ew8YL/yPRuAM?Kw0<?NMbU71;Wf7N/@b3jKj?2@8:370i8QlbdH/Qydv2gwW2fM/YNQAydt2gwi8QZPtn/@wMX/_yMQ6AM?Ly}NM4yd5vLp/Z8znMA8ezOX/_ct98zngA84ydfnLr/_E_@X/UIdQp8?bUw:cs18zhnaSv/i8RY923EMu/_P7ii8RQ9218zjSBRv/WcXK/@b3pOi?2@8:370i8QlCtD/Qydv2gwW93L/YNQAydt2gwi8QZxdD/@ytXL/yMRDAw?Ly}NM4yd5mzp/Z8znMA8exvX/_ct98zngA84ydfi3p/_EreX/QS5_M@4y_D/QO9_@ybXL/ioD4i8n03UgA0M?ZA0E10@44wc0<yb1nWs0>8yXwE.?ic7D0Kw@XL/ioD5i8I5p9M0<y3K2w1:3Ujm0w?ctJ8zmMAgeJa3NZ40>1ykit08D1i8QlStz/P70Ly:18yu_EO@X/Qy9Tz79i8DGj8DDi8f30uxDXL/i8I549M0<wXC2w1;fwUc20>8zjRpSL/WbvR/@5M7CHxtJQ84xzSQO9XkCdn9Q03NZ?8JZ<y3NgjExf3/QwVWTnLj8DLWavJ/Yf7U[K<;3FEfz/Sof7Qg?37Si8RX2XEa:W73L/Z8xs0fzAvY/Z8yNmgCM?i8C28<?eAQ_f/3NZ?37Si8RX2HEa:W43L/Z8xs0fzxvY/ZyYLQ8vc18yMlqCM?NvB_w2>?3F_vL/MYvh;cvp8znIcKwE;3E2e/_Qy5M0@eT_L/Qyb5iyr0>8yo8U.?WsPX/Yf7Q?cvp8znI9KwE;3ESeX/Qy5M0@eH_L/Qyb5vyq0>8yo8M.?WpPX/Yf7Q?i8K38<0<ObIP>0>8ykgA44ybwOw10>8ykgA24ybwPw10>8ykgA64ybj2g8NEdw.;4wVj2gg3Vi3og40<MXt2go3Vi3ow40<O9IMw1?3F2_P/MYvh;NEdw.;sq3oM4;58wTMA2?fzCjX/_FmLL/Sof7Ug[4yduMyW2w;37SW43K/Z8yggAi8n03UXP@L/oLbZ27P0i8I5dFE?cnVvU0M.?WtDW/ZC3N@4[19euVc3QvRWiXU/Yf7Q?LY8;3ERKP/Qy5M0@fwvv/Q6@;60eB@Z/_pF0NZAyduMOW2w;eyMXv/i8n03UW7@L/oLbZ27P0i8I5OFA?cnWvU18.?WmTW/Yf7Qg?ez3XL/yPzEfeX/Qydfizl/Z8ysoNMeyXW/_WtrZ/ZC3NZ4?2Z;o0eBHZ/_pwYvh;j8DLW5zH/_Fm_r/QO9_@zbW/_j8D_W9fH/Z9ysh8xs0fxtbY/_FALT/Qyb3kKp0>8znIaKwE:NZAy9j2ggW2rJ/Z8yQMA44y9wlw1?3FRvD/MYvh;grU1:Wlz@/Yf7Qg0<yduMyW2w;37SWf3I/Z8ykgA2eCC@v/KwE;18znI8cvrERKP/Qyb5t@o0>8yo90.?WofV/@W3w;4yddqTm/Z8yt_Eb@X/Un0thd8yMmQC;NE1z.;uBo@v/Kwo;18zjmEQ/_i8DvW0jK/@5M7k9j8RX1KAT@v/w3IJj0Z5@@AH@v/pCoK3N@4[23_M4fzHsd0>1lXEa:glp1lk5klky9Zle9@Qy1X7w10>8yTU8cvrE4uP/UB491O3@M8fxro5?36x2g0.;cu49eg;3//_i8I56Fw0<ybC3>0>8yUwE.?i8Bs93x8yVwU.?i8Cc9b:18ypMA@:4ybC2>0>8ylMAm4ybC5>0>8ylMAk4ybC4>0>8ylMAo4ybC5w10>8ypMAY}@SC6>?28D2ij:3Xqoow4?8ys9.1;fJFxx.?3Xq0oM4?8y490s10>8w_A13Upd7;K3Y:NOvd83XSc9b:29MyDai8Kc9fw;18oZ98w_A13Ur_7g?YQwfLsAFO4yoi8C490w10>80t18yogAW:bw_:csDPi0@Zz2jE:asx8C4wfHY98yst8xs2U.;4wfhst8yogAW:4z71vCm=ics5VFo{3EMu/_XU?2?ic7E0Qw5/Yv<wB?3w_Qy9Mrw:2i3D1i0Z6Mky9NXw?2?i3D7i0Z3NQydL2go.?i8D2i8B4933EWuL/QObJ2go.?xs0fxrwq?2bv2gsKw4:NZAOdL2gM.?W87F/ZcyvW_1w;4O9v2h0i8B490zEiKD/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9h2hUi8I5bFo0<z7w0>=i8I579o0<z7[18yMkeBw?ict0c}18yMn_Bg?i8Jc95x8ykw8i8n9t0W0L2g0.:@5bh40<y3v2hg<S9ZM@Sx2ij:NAgAs?fBogAUM;8jrj8DP3Vi490k1;ax2g4.?y8gAUw;4ybh2g8icu49cw+i8B494x8NQgAa}18NUgAw+18NUgAK+18NUgAy+18NUgAC+18NUgAG+18NQgAq}37x2ik+ct491[3Vi490o1;NXkMV@Q4fAYkNOkgar2hM3Umz7g?wbMAAM}fxeA;18yQgAo4ydsfZ8eTgAa0@2BME0<gfJCgA44S9@Aybh2gUiiDqgofA0k63Z059es8fwW420>dxt8fx7w20>8yPn1B;wTMA4<fx1oa?2bhxy5M7gLi8eY9f[3Ug02w?vxV8wXMAO[fxsQi;f7Q?pCoK3N@4[18yTMA24y9S4C9P4MFY4Odb3ybv2gsct9cyuXEoev/Qybl2gMyTMA74O9ZKz_V/_i8n03UWx2w?j8BI90xcyu5dzjM6j8DPNQgA4}15cuS0L2ij[@55//Qybh2gUi3D13UcU2;i2D8ioD0i8J49618zn3_i8n03Ukm.?h8xI971cevIfwWcy0>8NYr//_grQ8:j2JI94xc0SMA24O9t2gwioDshj7Sj8DHi8Cc9a:18yrgAM}@SH2jz:joD5WOAf7Ug[4y3M059wYo1ioD4i8f324QVXw@3u0s0<MV@0@3rMs0<O9@HUa:j8DDj2DyWaPD/Z8xs0fx7c80>dxvofBs908eFQK4ybv2gwi8f?ky9NAwF_Aw1TAwVt2hgsWd8yUMAE:4O9UQS9Z4ybJ2j}j05A92y9RkC9_AM1UkMV@Q4fAIkf7Qg0<wXt2gEsRV8xsAfxlgb0>5xeRQsct491>:i8dY93w03UhV2;j8J493x8yQgAo4wHh2gEijD0j0Z7M4y5M0@5e0w0<MV@Qi8r2hMNQgA4<;113Vb5cuR8eTgAa7ay3Xp49123U069MEfO0k49Rky5Og@5zwA?379hojJtkJ8ykMA44C9TeBJ0M?i8JZ4bEa:cvrEfKr/UC49eg;3TQc7E7UC490>?3FdvH/Sof7Qg0<MV@Q4fAIl52ekfxeg7?23v2gg.@48fT/@CM_v/j8Qs0Qybdimi0>9ys98NUgAO+1devIfAEgAE:4MFYQw3n2g8j8Bk921cylMAs4M1Q@I_3NZ0<ybty18yMntAg?i8IlPF40<y9MkwFYky1@v/3M0fxJI;18es9O9HZA:W7PB/Z8yPmRAg?3Xp6a8j0trR8yPrHL0Yvx{i8I5Cp40<ybk0x8yNm6Ag?i8Cg0<0<yb1nyh0>8yglFAg?i8I5sF4?8J068n0tal8yTgAg8IZ08s?bE8:icu493>;1:W6HC/Z8w_z_3UlW//yMl2Ag?xs0fx6P//Efur/UIUWbrB/ZczgkhO/_KlM20>8zhmqPL/ioD1i8I5yno0<yddpHg/Z8yPwNMewEVv/WiT/_Yf7M18zkw1j8Jk921cyRMAs4y9PQybdtyg?21V/_3M18wTMAe<fx3U50>cyQgAi4y9DfU<2?ig@WW3YB/Yf<O9xco<2?i8AdC9;4wVOw@2dMk0<ybx2iE:j05k94xcytJ42GgAE:4y3h2gE0ky9x2jg:i8K499w;14yagAE:4y9x2j}i8J495x4y6MAs4y9x2jo:i8J497x8ykgA84y3h2hE0kybj2hEi8e498}1h8JC64ybL2i8:j8J495x9zkgU1AzhXQzhW4m5V4wfhct8QqMAK:4y9x2i8:wbMAUw:1RgkGd18k}Kwg;2bL2ik:i3Dgi0Z2MEn_3UmV1;i3D1K}183Qb1i8B496wfAY0fJI29x2ik:i8JQ942_1w;exYUL/K0c;34ULLTB2gU.?ibzfZRfzFpL484zTUAxFz2gM.0.48f<z1Wwh8zgghi8B497x8aQgA84wZy1c;@75w80<ybj2hoi3Cc98}fwMc20>8yQgA84y9h2hUwbMAE[fxgbW/Z9ytO0L2ij[@5Mgg0<z7h2gg}4ybn2ggj8DDjjDYswTHamqgi8RU0kMV_Tcpj8DWLwE;18wYc1i2DWW2fz/Z8xs1RTAy9n2ggj8I5MEU0<yb3see0>cyst9eswfwEYa?2bx2jA:xs0fyvwj0>cySgAi4y9fpOe0>caSgA24MXp2gM3UeR5w?jg7Qict495w1:i8J493x8xs1QbAy3@fRTa4y3M08NQLd83XTgK44:FQbE_:i9zPi0@ZM2D2i6f2i8B495x8yMl9zw?i8BUc4y3v2gg?@4U0c0<ybh2gUct8NXkzTt2hoi8B4961C3NZ40>8yRMA44ybv2gUct98ytV8yvx8auV83W_6ifvPi3JY95wfwZAf0>8xs2_.;4wfhvx8yngAk4kNXky9v2gwWPlC3NZ40>cyvFcaua@2w;4O9V@w5UL/i8n03Uis3;iof50kOdo05ceSMA80@3SgM0<Gdn2Q0i3Js910fw@Ac0>devNOL4S9UoJY9,NQAQFYkM3j2g8j8Dej8Bc92zEtK3/Qybl2gMyTMA74O9ZKwlUv/i8n03UWI3;j8Jc92x8ys9dzjM6joDQj8Bc90zFsv/_MYv<ybdjCd0>8yQogi8JY95x8yogAC:4yb1h6d0>8yogAG:4wXL2iM:3Ufb:wbMA1g4:fxbQ;18yMp8yNnHz;i2D2wbMA1<:fxbw7?23L2ik}g@lMkm5V0@kM8j13Uix:Kg4;18etsfwVc;18yXMAI:4ybt2hoi8DUj8QA3AwFY4MVVQwfgIxc3QbDi8n9t5i0L2g0.;7hai8JY9418zhkoOv/LA}NMewiT/_i8JQ942bL2jA:i6fgW7Xx/Z8w_z_3UjL5w?i8I5joM0<O9o0xcymgAm0Yvg023L2ik}DkewbMA1w4:fxnA80>8NUgAw+3FTLP/MYvw}18yUMAE:4O9UQS9Z4M1p2gEj8JQ9218yXgAM:4M1UkMV@44fAIkNXuDf@f/3N@[4ybh2hwi8n03Ulo.?icv6//_Q24Xg@5fxA?8J49114y6MAs8D2w@>w@81i8fO0kC9Q4MV@M@3RM;8j03UiKZ/_WsE:f7Q?i8Cs_w.8>8wTMAi?fysTW/ZcyQgAieCS@L/pyUf7Ug[4ybhwybvxy5_M@4FM80<yb1kab0>8yoo0.?i8I5d8I0<y91imb0>8yMkKyM?yQ0oxs0fxsI80>8yPksyM?Wo3W/Yf7U[wXMAB}4fxc8h?37x2ik}w;eB7@/_pF1cyud8yUMAE:4S9Z4ybJ2j}j8JQ9223v2gg.@4TMY0<M1p2gEj07xj3DXgg@iNj7JWqjT/Yf7Q?K<;33pyUf7Ug[cq49a[joDXWonU/Zdxs0fBc10wfQ1t0y4M0@5MLX/Qi8r2hMWt3@/Z8zn3_i8J49615cs18aQgAaeCbZ/_ioDsj8Dyj2DOi0dk90x8yMk_yw?i8Idg8E0<wfKKE_i8D6i8f?o7C/Yf<y91h@a0>8ypjN>0w<y9wg>0>8yMkhyw?NA0F0kyb1gqa?2bg1y5M0@5b0U?8K49eg;25M0@9m.0<ybt2h0yPRZvM?Kww;18NUgAc<?3Z23M3EWZX/Qy3@fYfx64d0>cyvvEGtP/Qy1N7w1;NM5JtglN1nk5ugl_3yMkTvM?cta@.;4z7x2gC.{6q9B2gK.?Kg4:NQEC492>?2b1gh_0>CyrgAb<?bU2:yogAa<0<ydx2gw.?i8D7pECc92g10>8ykgA8ey_Tf/xs1@3Lq492U1;13UnT,?i8I59EA;@Sw1w1?24M0@4AMU?ct491>:j8Dxhj7JWu_P/Z8yPnZy;yRooi3Jc93x13Vf4ggD4hoDwggzE3Und5M?xt9Q94ybH2jM:i8nJ3Ujf4w?vx5cyWgAO:4S5V0@5jN80<m4Xg@49Lr/P7JWiHQ/Z8xs2_.;4C9O4wfhvx8yMpczgOZ}4AFM4Cd13B80s19es0fwYo40>8zgg_j3D0sO18ysx9Qux8at1ces193Qv0ioDUiiD0ig78i3D7igZ2O4wVOw@3Jfv/Qy9zw>0>8ygQJy;i8I5dEw?8J068n03Ug8_v/i8JQ942bfs1Z?2W2:4O9n2hMj8Bk9218NUgAc<;4;3E8dT/QObl2gwj8Js9718w_z_3Un9_f/yNTKxM?xtIfxbLY/_EWtP/UIUW6bs/ZczgmZMv/KmY20>9ys58yMkYrg?i8IUWsU50>cyvJ5cuQNXkybdqm7?2bhxxcySgAi4i8H2iw:i8K49aw;37h2gg.;4y9x2jg:i8K499w;18yogAM:4ybh2hoi8C49dw;18yQgAu4y9h2gwi8DoioDdj2DMi0d490x8ykgAieIVA4ybjy18yMkJxM?i8D2i2Dai87W/Yf?@6Uw;4wV1gK70>O8rZA:Wc_q/Z8yPk8xM?3Xp6a8j0ts18yMXHLMYv<yb1v660>8yR08i8IlTEo0<y9A0>0>8yMngxw?i8A5Moo0<yb1sG6?2bg1y5M7iGi8JQ942bflxY?2W2:4z7x2gM.;g;ez2S/_i8fU_M@5v//Qib5pC60>5xt8fx6//_EAZL/UIUW0Pr/ZczglDMf/KlM20>8zhnMM/_ioD1i8I5TSI0<yddv35/Z8yPwNMex@SL/Wj3/_ZC3N@4[18ys98yPkSxw?i8f?o7y/Yf<MXr2gU3Ui70M?pAi9H5o<;ig@WX3@0L2g7.:@5DwU0<O9Fdo<2?i3A5VEk0<y91uu50>8NUgAO-fwW3R/Z8yRo8yQUoxsAfx9we0>8yMm_xg?i8C60<0<yb1r650>8ygmyxg?i8I5GUk?8J068n03UmG4w?i8IRCok?eBnZv/Kw8;18zjluL/_ysvEEtH/Qy3@fYfxoLX/@b3nC5?25Og@4vvL/@xQSL/yPzEXtD/QOd1j@@/@Vjgg0<yd5t72/Z9ys58yMn0qw?i8QRQsj/Qybe370W5_p/_FfLL/Qybx2io:i2K49c}fx5M20>8yXgAG:4wHJ2jg:i3DUsxcNQAzTZP7ii8D1i8DMifvNi8D6i3BQ95wfwW7U/Z8NUgAw+23L2ik}g@4zLn/Qybh2hoi8R80kzhWuDXZ/_i8Qlis7/XV}j8D_cs3Egdv/Qybt2h0yXMAV:4xzQeyISv/i8fU_M@5D@X/UIZx8g?8n_3UihXL/W7_p/@beezUSf/j8Q5oI7/XD60w?i8QlTc7/QC9Mkyb1sJF0>8zjnsM/_i8IUcs3EqJz/@BiXL/3NZ40>8yPkFx;i8Jk911cys1C3NZ40>CpyUf7Ug[4C9Mky3M051wu7/MY0hw@Tz4U<;j07ai3D1tu54yVMAV:4y9l2gghonr3UAG2g?ibH////_vQy9@2n/MY0i2ekNw.8>8ylgAieA7Zv/j2D9WlLX/Z8yPmEwM?Kw4;18yMV8yMm9wM?i2D8u2kNQAybz2jU:iftQ95x8esx83Qv1i8D2i8n0K<;183Qjgi3Bk93wfwDgf0>8eRgAe0@3QwM0<ybL2i8:i8Kc9bw;18NUgAw+18yUgAS:cu499g:2:i8f?QwVPQwfhIZ8es4fwJTP/Z8yQgAe4yd312U.;4zhWkwfhcx8ykMAe4y9OAzTSAyb1uu20>8yoog.?i8I5Uo80<y9A0w10>8NUgAK+18NUgAy+3Fxff/MYvh;i8DUic7w0AwVQ0@3qfr/Qm5V0@5n_r/@CV_v/3Xtc93xCyoNm>;82Y90s1:3UhW_f/i8JY94x8ys61Uv/3M18yrPe>0w<S5V0@9o_P/@Bm_f/3NY0i8JQ942bfuRT?2W2:4O9n2hMj8Bk9218NUgAc<;4;3Ejtv/QObl2gwj8Js9718w_z_3UnSZL/yMkrww?xs0fxezS/_E5Jv/UIUW8_m/ZczgnGK/_KlM20>9ys58yMlFpM?i8IUi8QlpH/_Qyddn31/YNMew1RL/j8Js971cyRgA8eCvZL/i8JQ942_1w;4y9j2hMj8Bk923Eytj/Xw3:j8Jk9234ULLTB2gU.?ibzfZRfzFpL484ybj2hMi6CQ93>0>.wY0ifvyic7G14yd11p8aUgAO:4wXx2jM:3UbpXf/NEgAE}18yPlawg?joDXicu49cw+WiLL/Z8yMkLwg?NE0o.;uDSZ/_3NY0i8J490xcyu6bv2gsct9cav5czig1j8DCW0fk/Z8yRgAc8JY91NcyvrEEJj/Qy5M0@eAwk0<O9p2g8joQY1AS9Z4MXr2gw3U8FY/_pF1cyu1cav180QgA24y9h2gwjonJtnB8yRgA8eBzZL/A4O9U4ybv2gwi8JQ951cav180QgA24y9h2gwijDZsN18eRMA47c9jjDY3Ucp1;jonJtjHHLSoK3N@4[18yR0wi8I5no;4wFQ4wZ/Yf07pGi8I5kU;8J068n0tni_p:ew2Rf/i8I5eU:@Sk2y4QDn3i8IgWY9C3NZ40>8yT0wi8I55o;4yb5gq;18ys58av58wvD/MY03Upz.?i3D23Uay:LSg;3EIdf/Qyb1uB_;fJB0Exd9RKkybceKU3NZ0<ybt2h0yPRJtg?Kww;18NUgAc<;4;3ERZj/Qy3@fYfxm7/_Z4yNmKvM?honi3Uhh//Wazk/@beewxRf/j8Q5vbD/XAY1;i8Ql1rT/QC9Mkyb1vhA0>8zjk5L/_i8IUcs3EAZf/@Ai//pwYvh;i8I5knY0<ybk0x8yNk@vM?i8Cg0<0<yb1j1_0>8ygkxvM?i8I5aDY?8J068n03UgB//i8JQ942bfrhQ?2W2:4z7x2gM.;g;ewuRf/i8fU_M@5@LX/Qib3vl@0>5xsAfxeH@/_EXZf/UIUW6zj/Zczgn3Kf/KlM20>8zhlcLf/ioD1i8I5eSg0<yddkO@/Z8yPwNMezqQL/WqL@/Yf7Qg0<ybn2h8i8D6j8Js9218ytB83XHFfQMXr2gUi0Z5Sky3M061VL/3M18yMRNvw?i8D7i8A5nTU?6p4yqNN>;87D/Yf<O9DfA<2?i8CsYg.8>8es9OiQM1XkwXr2gg3UdW_v/i8J49218ykgAieA6Yf/pwYvh;i8Js96182scfxbDP/Z8yRMAo4wVS4wfgId8ysvF4v3/Sof7Qg0<ybugybshy5Zw@4Gg;4yb1tFZ0>8yo40.?i8I5P7Q0<y91rRZ0>8yMn6vg?yQ0oxs0fx7z/_Z8yTgAg8IZk7c?bE8:icu493>;1:WbHi/Z8w_z_3Uld//h8I5AnQ0<m5M0@4fv/_@ybQL/yPzE1db/QOd1l@T/@Vn080<yd5uyW/Z9ys58yMnnow?i8QRWbP/Qybe370W7rh/_F_LX/V18xv@@.;4C9M4wfhfV8yP5czgOZ}4AFY4Cdd3B80vp9ev0fww>0>casx8es8fwYj@/Z8yo40.?i8A5WnM0<yb1v9Y?2bg1y5M0@4FfX/Qybt2h0yPRYsw?Kww;18NUgAc<;4;3EVJ7/Qy3@fYfxnD@/@bfrVY?25_M@4q_X/@yVQv/yPzEcJ7/QOd1oSS/@VrM80<yd5hqW/Z9ys58yMk5ow?i8QR5HP/Qybe370Wajg/_FbfX/MYvw}19yvnF7LP/UIloDM?8ni3UihYL/W5Th/@beezmQf/j8Q5tHv/XBe1;i8QlKHD/QC9Mkyb1qBx0>8zjmWK/_i8IUcs3Eid3/@BiYL/i8QQfQMVNw@3ZLX/Qy9NADhW4wFRAMVNAAfh_19yvx9av190s18evt93Qb0Wt7@/Z8yTMAcezDP/_ioD6WjrB/Z8yTgAg8IZp74?bE8:icu493>;1:WcXg/Z8w_z_3UmFYv/yPmCuM?xvofx9LN/_EEt3/UIUW1Hg/ZczglRJv/KkM40>8zhn@Kf/ioD1i8I5Xm;4yddvWW/Z8yPwNMeycP/_WlPN/Zcyvx8yTMA84ybt2hgjoDYj2DMi0d490x8ykgA8eCv@L/i8eY9fw:13UpV,?K3Y:NQLd83XSk9fw:FQ37ii9x8yogA2<0<y9x2jE:i8eY9ew:13UjAU/_Wq_z/Z8yQgAa4Gdj241iER48058ykgAa4wVNw@3jMc0<y5Og@54vf/Qy9j2ggjoDYWqvH/Z8yPmNuw?i8J624wXx2iM:3U8f,?i8Daj8D7i3Dn3UfwW/_i8IRynE?eCFZL/i8I5vnE?8J864yb5mJW0>8ehlsuw?ykMAs0@2C0k?8J068n03UnL1g?i8eY9f[3UzY0w?yQgAs8n03UjM0w?i8eY9cw}3Ugn1g?i8JQ942_1w;ez@Pf/j8Ks9f:18yVgAe<?37Sjonrt5J8Ks_Tk@eBCYgwic7G0QxFL2gM.0.48f<y9Q4zTUkz1Wwh80vF8yXMAO:4y9Q4wF@4MVS7cxiiDjLCg;19zggXi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY9229YHU2:W1Ld/@5M0@e@g4?fq492o1;13Unj0M?ZEgAbw4;4fxdQ10>8yMlMug?j8DxNE0o.;st491>:WkTM/Z8ypgAW:4z7x2g8.{eB1_L/i3B496wfwEHF/Z8yUgA@:4zhp2gUi8JY93x8yUMAI:4wVNQwfg_yU0w:Z2x2ik:i8BY93y9x2ik:i3Bc95wfwZY;20L2g5.:@4Qg;4ybB2g8.?i8Dhi8f_0nokcs2VfM;fd83XT7as58oYB80t58yUgA2<0<ybL2iM:i0@Lz2jE:i2JY95x83W_7i8Qkgbw1:i07ii8n9i0Z4O4wVOD88i8Dgct98Z_6bB2jA:xt9UnQwVNQyd5g2R/@@g:4wfhIt8yTMAg4y9MkC9Nj70WeLa/Z8yTgAg8KY9eg;18oZ3ElYT/Qy3@fYfx1Q80>c0mMAm4yb1i5U0>8yQMAm4y9i0x8yPkhu;i8I50Dw0<y9xx>0>8yRgAe4yb1vtT0>8ZZF8yp08.?ict496w}WjjE/Z8yRMAi8JY9,NQAS9Z4y9TKz9OL/i8Jk932bv2gsj8DSW6zb/YNQAy9n2g8i8IZCDs0<y5M4wfic9dzjM6WgDF/@3v2gg0w@4?8?ct491[j8DxWnfK/ZcyvJ5cuQNXuD7Vf/h0@Sr2hMWivB/Z8yTMAi4y9Mo7x/Yf<y9LcU<2?WkvN/Z8NUgAO+2@p:eCa_v/i8niKg4;18yPVcyMkktM?i0Z4Qky9MkwF@kOd39k}ioQY4kw1_QwV@g@2Swc0<MFO4z7x2j8+4AVM0@3Hur/Qy9xw>0>8ygnctw?i8I5Rno?8J068n03UgGYv/i8JQ942bflZI?2W2:4z7x2gM.;g;ez9O/_i8fU_M@47Mo0<z7x2j8+4ybdoNS?3FiKr/Qz7x2i-cu499g:2:WjbD/Z8yTgAgbY6:i8Bc9214y8gAE:ewLOv/K0c;18yQMA8cjy@_uk93w10>8Kc_Tk@eBCYgwi6CQ93>0>.wY0h0@Sx2iw:ifvyic7G14yd11p8yPkatw?j2Dwi3DE3U94Xv/i8K49aw;14yaMAE:4i9NkObp2h8i8C49d:18yUgAC:4y9x2j}i8J495x8yogAS:4ybh2hUi8B4923FneX/Qybt2h0yPQ_qM?Kww;3EjsD/_q492U1;13Uko_f/i8K49bw;18yQMAmct49102:i8R420p8Qux8yogAK:eDTUf/h8IJpDk0<m5Xg@40uD/@xwOL/yPzESsD/QOd1keO/@VLgc0<yd5rSO/Z9ys58yMmImw?i8QRLrj/Qybe370W4L9/_FMKz/Qybt2h0LMo;3EVYv/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9x2j8:WpTW/Z8yT08xsAfxlM1?2bi1y5Og@5kg40<y5ZHA1:i8IUj8I5Ang0<wfhf58yt58avBczgOR}4Cdf3580vZ8evAfwyA20>casF9et0fwzo3?2bg1y5M0@47fT/Qybt2h0yPTZqg?Kww;18NUgAc<;4;3EpYD/Qy3@fYfxurV/@b1jZQ?25M0@4SfD/@wWOv/yPzEIYz/QOd1gWK/@V@g80<yd5puN/Z9ys58yMm6mg?i8QRBXf/Qybe370W2n8/_FCvD/Qy9QkzTSkyb1tJP0>8yoog.?i8I5Rnc0<y9y0w10>8ylgAe4z7x2i-cu499g:2:WnjA/Z8NUgA2<{18NUgAW}4;3FxdP/QybdAy9OAwVPDcri8Ks9b:18av58etB83Qvbi3D83Ua@.?j8D7WsDU/Z8yNljsM?i8Cg0<0<yb1klP0>8ygkSsM?i8I5fTc?8J068n03Ukg.?i8I5bnc?eD6@f/i8QY4AwVPM@37fP/Qy9NQzhWkMFNQwVPQwfh_B8yt58avB80s58evF83Qb1WvvX/Z8yTgAg8IZySw?bE8:icu493>;1:Wfn7/Z8w_z_3UkI_f/h8IdP780<m5Og@47fP/@z6N/_yPzEfYv/QOd1pGI/@Vn080<yd5ieM/Z9ys58yMkim;i8QR8Xb/Qybe370Wb76/_FTvL/M@Sh2ggw@>w_>j3DX3Vb22t18xsAfxiY20>1yskNXuD4T/_i8QYdAwVPM@3PvT/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWqzZ/Z8yTgAg8IZKms?bE8:icu493>;1:W2f7/Z8w_z_3Un5_L/yMnXsg?xs0fxbv@/_EZIr/UIUW6_6/ZczgnaG/_KlM20>8zhljH/_ioD1i8I5gBs0<yddleN/Z8yPwNMezxNv/Wnz@/Z8ysJ8yTMAgbV}i8QlcGX/QwFMP70i8DpW2L4/Z8yTgAg8KY9eg;18oZ3EBYr/Qy3@fYfxaE10>8yQgAm4w,Qyb1lVN0>8ylw8i8IliT40<ybfjNN?3FHLr/QkNXj7JWpbu/Z8yp;g?i8Al7T40<yb1ixN?2bg1y5M7kpi8I56D4?eCy_f/goDEWg_X/Yf7Qg0<ybt2h0yPStpw?Kww;18NUgAc<;4;3E1Yr/Qy9MAyb1tRM0>8w_H_3Ulw_f/wPTks}@4k_P/@zhNv/yPzEiIn/QOd1qmG/@VrM80<yd5iWK/Z9ys58yMktlw?i8QRbH3/Qybe370WbP4/_FpL/_MYvw}14yMm1s;hon03Ujh@v/W7L5/@beezQNf/j8Q5jWH/XBL0w?i8QlSaT/QC9Mkyb1stl0>8zjnoH/_i8IUcs3EpIj/@Ci@v/i8IRaD;4kNM8Jm64i8r2hMgoD5WhDW/Yf7U[yMkis;xs0fxdnT/_E3sn/UIUW8r4/ZczgnMHf/KoM30>8zhlGHv/ioD1i8I5mlk0<yddmGL/Z8yPwNMezUM/_WprT/@3fshL:3Uh9_L/Wc74/@beewWNf/j8Q5FaP/XDQ0M?i8Ql7GT/QC9Mkyb1gRl0>8zjkuH/_i8IUcs3EHcf/@Aa_L/3N@[45nglp9ytp1lk5klld8w@MoynMA1bY;40i8BQ90zE7c7/QC9NQS5ZDh@hj7AWNof7U[W4f4/@3e0hRq4QVZ7dzi8J490xcyvabv2g4j8D@j2DyiEQc8bw;40i3D2i0Z7QewyML/ioD5i8n0uc9QcAy9MQO9_mqgi8Dqi8DKLM4;3E0cj/Qy5M7wbi2D3t2p80snHUp3ESYf/UcU17jmi8f464O9_RJtglN1nk5ugl_FEc7/QQ1XeBW//3N@4[23_M9_2Xw1:MMYvh;gluW2w;45mgll1l5m9_ld8yvd8wuMU1;i8J@237SW3H2/Z8yTIgKwE:NZEB491zE9Ib/Yt490M}ykgA78fZ0Tgsi8JX64yddmiH/_Edsf/Un03Vj03Xr0ykgA34yb1i9K0>8xs1Q1cp0a058zkgAg4kN_Qydr2gMhj7Jict492w}i8B4911CpyUf7Ug[8JY91yW0.0<y9XKyfMv/i8n03UX2:ic7E18n0vJWdmfZ9yuV8Muc4i0ds913H5MYvh;ijD53UaT:iof644AVTDiSioI6j3DEtupd0SU8jon_tibH9gYv<SbpN1cyvZdySY8j8BA92zEqY3/QS5V7g8joDDjjALtdV8yMlDrg?i8n0t0hcymwwyQgA38n0tixcyuF8yMlcrg?ibA0Yf///vU7y/Yf<wzzd0<2?3Umu:j8JY92zFtv/_MYvg>cyvZdyTYgW0j0/ZdxvZRXQy1N3w4;NM5JtglN1nk5ugl_33NY0LNw;3ELHX/Qy9MkCb1Ay90kCblwx80s98yl48i8Rk92xdxvZRbuIM3N@4[1CpyUf7Ug[6pCbwYvx{ioRn44SbvN1dxvZQ1kAV1TbKj8BV44y92KBA//pF2bv2gscta@0M;exgMv/j8JY92zFN_X/Sof7Qg?8f_0DYbK<;333NZ40>1lXEa:glp5cvp1lk5klld8yvd8wuME1;i8J@237Si8RI921czmMAcez_L/_i8JX4bEa:cvq9h2g8WeK/_Z8NQgA6}29h2gc3NY0pCoK3N@4[2bv2g8Kw<0>8yuXEDX/_Qy5M0@eZw;4z1W0i5M7Xuzlz_ioDIic7z14M1W@Il3N@[4AVND9ziof444AVT7iWioI494MVY7nFi8JY91xd0TgA24y5_TksWNZcyTYgj8JT24O9v2goW7W@/ZdxvZQ24O9_QMVdTjxj8DNi87x0f3/TWOyTMA337iLwc;3Eds3/@Kw3NY0LNw;3E9HT/QCb52h8zkMA64y9NAy944Cbh2g8i07gi8B624ybh2goi8n0tiXHcmof7Ug[6pCbwYvx{pCoK3N@4[18zkwgi8J<4y5M7g5i3AgsKV8ykogi8ANWi//ZCA4y1N2w4;NM5JtglN1nk5ugl_3A6pCbwYvx{w_Y2vMKU.;ccf7Qg?5mW2w;4y9Vk5nglp9yvp1lkkNXk5kgoDYkQy1X7y20>8yTU8cvrEoXX/QydduqB/@9h2gcioJ644y9NQy9h2gEW7u/_@9MQ63_0dQ6kCbvxx8zjk1Fv/hj7JW5O/_@5M44fBcl8zngAkbY1:Wau@/_6h2gw08n0thebh2hE9g3M;Z08:@kh2gwxtIfx9430>8zkgAg4kNV4z7h2gM}4OdJ2hM.?i8B49218zogAU:4y9h2go3N@4[18yTgA88JY90OW4:eydLv/i8fU40@5r.0<Obh2h0honJ3Unt.?jjD43Ulc0w?i8Jc92xdyu2@0<0<O9ZQyd5ouy/YNMew@Lf/cvpcyvsNMez2Lf/yse5M7xcict493w}i8JQ91y9T@znLv/xs1R4kybz2gg.?i8n93U_s:yt_E2XX/QO9Z@yjLf/honJ3Ulq//pyUf7Ug[4ybn2gMj0dA94x8xtJRaKAY//3NZ0<ObuN18ytZcySc8j8BY933E0XP/QS5_M@46L/_QO9@QMV8M@53L/_Qybj2gEjoDwLw>0>cyvt8zhn9Ev/cs3EwbL/P7Sj8DTcs3E1bP/Q69N8n0ual8NQgAe}18yTgA68D7W1yZ/@5M7khi8Kc91>0>8xsAfz_4;14yuvEiXT/QO9Z@zjK/_Wmr/_Z8yUMA4<0<ybh2gUi3D13UUm//i2D1i8Rk93y9THY1:W7iX/Z8xs1VQuxGLv/yM23@0hQNoRgWEfyXTgkw_w93Vj2w_xo3Vj02c8fxdn@/Z8yTgAe37iyt_EarL/Qydx2hM0w?i8B4913H4Aybt2ggi8D2LM4;3EabT/Qybt2ggKw2;29T@yDK/_i8n0vZzFy_X/MYvh;i8Jc92y@0<0<O9ZP70i8QlJa3/@xJKL/cvpcyvsNMezNKL/yse5M0@8N_T/@AC_L/i8J493x8es4fzw7/_Z8as58zlgAe4i9VHY1:W9@W/Z8xs1Uu4ybz2gg.?i8J493x8es5_ReDg_L/3NY0LNw;3EdHD/Qybl2h0i8Rc9318ysp8yh18yQgAi4w1Q4y9hwx8yQgAc4y5M7ktWO0f7M1CpyUf7Ug[4ydi118yQ.i8n0t0l8eh1OXAy9hx18yj7F8LT/@wtLf/yM23@.fx7z/_@dkeG3UKZQ58fUm0@kMEfU2g@kM0z23Uh3_L/i8JQ93wNQAi9V@znKv/i8S497020>8ykgA4eIq3N@4[18yTgA44y9MHY1:WcWX/Z8yTgA4bE0w;h8DDW4OW/Z8xs1_R@DL_v/i8S497020>5cvYNSQz7x2jw+4y9h2ggi8S499w20>8yggAi8S497>0>8ykgAa6pCbwYvx{i8JQ912bv2gcKw0a?3EXrD/Qy5M0@eO:4y@PsPcPcPcPcN8Z@p8MuE5xt9@PQybd2idgLZcySgA44yd1818zgj6i8B491x5xuQfxbY;1CA6pCbwYvx{ioJQ91x9yRgA846bv2ggi8CQ97>?20v2gw?@47w40<y9Qkybl2gEyvW_.;ezaKf/ioJc91x1yTMA4bU3:i8Daigdc9218wu80Yf/i2DhW6iW/Z5xuQfxeI;19wYgEj3BA91xRAeAH//3NY0j8D_joJ_aexcJ/_jon_tuZ8wshUww?cs1rglN1nk5uglZtMMYv<kN_QC3N2xcemgA60@4XLX/QAV72gfx4j/_@_c:ezWJL/Nc5@rMgANvV_<Cbl2gwi8Bg84S5_M@4T<0<Cb32h8zpgAU:eIt3NZ40>CpyUf7Ug[4CdlOxdyTYEjon_t0l9egZOXAO9u2x9wYgEi8A2j8KY9e:1cemgA60@4gM4?cnUt@BW//3N@4[3Ee_n/@DI_L/pwYvh;igds90xdxvYfx1Q1?20v2gw?@5Yg;eJB3NZ40>9yTsoi8CQ97>0>9yRswgoJ_4ezTZf/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhW1iV/ZdyTsEj8D_igdv24O9J2jw:W0OS/Zdxvofxdf@/Zdyvt9ehZQCQC3N2xcemgA60@5PLX/@CT_v/3N@[4CbhNx8yRgAabY1:i8C497>0>9yQYwgoJT4ezJJL/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhW8GU/ZdyTsEj8D_igdv24O9J2jw:W8aR/Zdxvofx4D@/Zdyvt9ehZQAkC3N2xcemgA60@5hfX/@AJ_v/NvxTWinZ/Z9wYgEj3JA91wfx1rZ/Z9eNMA3UhI_v/LP:3E8Hn/Yj1vCY49cn@vM19yRgA84y9k218zpgAU:eBk_L/i8Sk9e:3Fh_X/MYvh;w_Y13UXn0w0.luW2w;45mgll5cuR1l5l8yvljyvJ8wuOE.?i8J@237SWbWS/Z1ysi3@Mcfx8E2?3EHrL/QydfmKu/Z8Muw3i8So/Yv0bw:2i87z?3w_QwVMQwfhZyU;w<wVMQwfgJzEVXj/Qy5M7gnKwE:NZAy9N@xzJL/i8D5i8n0vMmZw:4ydv2gMW5OS/Z8NQgA4}y5M7kSNvBL3juq/YNQInVrEgAC:cjyuj_1NvB@M4wfHQgAk4zTZrE:8i3Dgi0Z3Q4y9l2ggi8SQ91>0>4yu_Eyrr/Un0thubx2gE.?9g3M;Z08:@4Tw40<6V1g;4C9S379h8Dycvp4yu_ElHv/QC9NQy5M0@8Ow;bQ}grU:1tj5CA6pCbwYvx{grA5:ioDocsB4yu8NZAi9X@woJ/_ioD7i8n03UWt:yPQ@lM?xvYfysU;1c0vR9euVPNAydL2iw:W6CR/@9Mon0tlf5@mYdiVD/Qybt2ggNvBKx2g8.?Ne9VfY75@nX0i0@Lx2j8:i3DMsOp8yMlfog?i8n0t1EfJA0Exc0fxjI7;f7M1CpyUf7Ug[4C1Nw:7Flf/_MYvg03EaXr/QC9NEcU5w@410o?8IZDlo?8n_uhkNM4y1Naw10>rnk5sglR1nA5vMV18zrgAE:bE8:icu49a}1:WfaR/_HOQydJ2iw:Kww;18NUgAE}4;3EQHn/Qy3@fYfxgH/_@b5qFw?25Qw@4_fX/@yBJv/yPzE7Hn/QOd1suw/@Vkgo0<yd5gau/Z9ys58yMnNhg?i8QR0G3/Qybe370W92Q/_FLvX/MYv<ybvh2W2w;37SW1yQ/Z1ysnFnLT/Xw1:MSoK3N@4[18yVgAg<0<ydt2gEhj7_cs18NQgA8}18NQgA2}58yjgAi8ni3UXM_L/3NZ?6pCbwYvx{i8Dhi8Dti8B492x8as58etB83QrFi8nJ3UhW.?hj7SioDEi8IQ94kNOj79jiDMh8Dyh8DLWdmP/Z8xs0fy0M1;fx3810>90sp9euVOPQybh2gwpwYvx{jg7TyPQvlg?j07Mi8B49225_M@9dM40<ybB2h0.?i3D23UVn_L/j3BY90wfwSL/_Z8zqMAE:4y9X@wHI/_ysa5M7l5NvBL3gSn/Z8yUgAO:cnVrEgA2<?cjyuj_1Nc5VvIp93W_6i3J4911P5Qyb1h1v0>8xs1Q2M@Sg2y4M7kH3NY0i85490w:1i8J49218yVgAg<?eDR_L/3NZ4?21@x0D0>QSbZA:ylgA6eyaIL/i8DLWaaO/@bl2goi8K49cw;23Mw593W_6i3J4911OOeKCpwYvh;WaKP/@b08fU10@4XvX/UfUnM@kMEfU9w@kMgzatgO3UfK3@18fxqE;18yQgA84S5Zw@5RLX/QybB2h0.?i8Dhi2D1i8n93U@f:hj7SWrH@/Yf7U[i8SQ9a:2W2:4z7x2iw}g;ex2I/_i8fU_Tgci8J4923FC_X/SqgyPQinw?xvZQWKwhI/_yPzEyHb/QOd1jeu/@V50o0<yd5mWr/Z9ys58yMltgM?i8QRrFT/Qybe370WfON/_HHHw1:WrTY/Z8es8fzGzY/Z8zkgA84Obt2g8i8A494QV_w@2q<0<yb52h8ytB4yuV4yuvEDH3/Qy9Nky5M7wKt3qbfhpj?25_M@9Zw40<A1XQybh2gwi3C494>0>_K@Bg_f/3N@[exzIL/wPw4tdJ8yUgAg<0<ybl2gwj8BQ90x8es8fzijY/Z8znMAaexVIL/xs0fxhbY/@bv2gIKw0<02@,g?exuIv/i8S49a:18ykgA64ybx2h0.?i3B4920fzpI;18ySMA24y9n2g83NZ0<MV_g@29Mg0<Obh2g8yRgAb379h8DLi8IQ946V1g;ewqIL/i8D3i8n0vBZ5cvof7Q?pCoK3N@4[19ytybv2gEcsANZAQFY46V1g;4i9UKzAIv/i8n0vwx90sp9etVORUIZ2l8?8n_3UB70M?i8J4921d0vt8eogAg<;@fs//UJY92zE@H3/UJY92PEYr3/@AJ@/_3NZ0<ydH2iw:i8DLW0yM/@9MEn03Ume:NvBL3uqj/Z8yUgAO:cnVrEgA2<?cjyuj_1NvB@MkwfHY58eQgA47dxi8I5WBI0<y5M7hl3Xp0a8j0t4TH287W42s?7h3LSg;29l2goi8Bc90zEwa/_Qy9X@yoH/_yRgA64ybj2g8i8K49cw;23Mw583W_1i3J4911OLCof7Ug[4C1Nw:7FVfT/MYvg>8zrgAE:bE8:icu49a}1:W8aM/Z8w_z_3Uny_v/yPlqmM?xvofxdjZ/_Elr3/UIUWcWL/ZczglTC/_KiA60>8zhmOCf/ioD1i8I5Ek;4yddraq/Z8yPwNMex0H/_WpnZ/Z8znMAaexhIf/xs0fy2_Z/@bv2gIKw0<02@,g?370cuTEcG/_Qydx2iw:ics49}58ykgA26qgpCoK3N@4[2bl2gIgrA5:ioDocsANZAi9X@w7If/ioD7i8n03UV8_L/yTMAa379cvp1Kgk;19ys14yubEUG/_Qy5M0@e9LX/UIZ2R;8n_3UDr:j07Zi3AI97eyi8JY90zEeaX/Un0tkj5@mYd79b/YnVrEgA2<?cjyuj_1NvB@MkwfHUMAO:4wXj2ggsNF8yMQzmw?i8n9t0UfJAAExcAfxvo10>CA4y112g:1Wkf/_Z4yiMAioDRj8BQ90z4MnB@NAy9n2goysLH4mof7Ug[87X42s?7gHLSg;23MM7EyWT/QydL2iw:W9WJ/Z8yUgAO:4AfHYpceuxOPkibb2hcyTgA24ybn2goWmHU/ZCbwYvx{i8JQ90yW2:4z7x2iw}g;eylHL/i8fU_M@50f/_UI5rlA?8n03UjO_L/goI@WemJ/ZczgmeCv/KmM60>8zhn9BL/ioD1i8I5K3U0<yddsCo/Z8yPwNMexnHv/Wrv@/Z8yTgA6bE8:icu49a}1:W2uK/Z8w_z_3Umk_f/yMT_m;xsAfx8rY/_E@GT/UIUW7eJ/ZczgksCv/Kks60>8zhlnBL/ioD1i8I5hzU0<yddluo/Z8yPwNMezBHf/WkvY/Z8yTMA6ey6Hf/goD6xs1RgsnVrMRDAf/i8K49cw;35@mW490w1?34UDA_MsnVvId83W_3i3J4911P54yb1mJo0>8xs1Q20@Sg2y4M7kli875}uBX@/_go7@42s?7jHLSg;11wYo1WfKH/Z8yTMA6ewhHf/i8K49cw;183W_3i3J4911OPeK@i8Bs91z4MnB@NUD3WMy1@N0D0>QaHZA:wYc1WbCH/Z8yTMA2ezfG/_i8K49cw;193W_7i3J4911OPAybn2goWsbZ/ZCA8f_0TYbK<;333NZ40>1lXEa:glp1lk5klld8yvd8wuPo0<0i8J@237Sj8SI9d:3EpaL/QybuN0NZHEa:goD6W56H/Z8yTIocvqW2w;8B491zEfqL/Qy9NoB491PEcr3/UBI92x8Muw3NQgAb<;18zpz/NY0K}98wuc?e3_i3D3i0Z7Sbw?2?i3D3i0Z2S4ydh2h0hj7Ai8B491180tJ8yTgA44i9Z@xKG/_xs0fy0o10>cyTMAs4Cdb1N9euYfwHY;18zkgAc4y9h2g8i8Sd?3/XE;40j8DKh8DTWfeF/Z8xs1@pAy9MHUa:j8DLW3WI/Z8xs1QkkMFW4ybt2g8yTMA6bEg:i8SI1g40/ZcymgAc4y9W4MFU4y9h2gUWaKH/Z8w_wgt42U.;4y1Ndw0.1rnk5sglR1nA5vMSof7Qg0<ybt2g8yTMA6bEg:j8BA9318ylMAeexHG/_i8fU47n0ioDIi8QIaQAVXM@3i//Qydv2gEKCg;2@.;eyxGv/xs0fzLX@/@bv2gsKww;18zngAceySGv/Wur@/@gcs3Fuv/_Sof7Ug[5eX.;4y3X218zngA7excGf/i8D2i8cU07goyTMA74y9NAy9h2g8WcaM/Z8yRgA28D3i8DnW9eD/Z8wYgwytxrMSpCbwYvx{kXI1:i8fI84ydt2gsWfOD/Z8ys98wPw0t1ybv2gsi8D6i8B490zE0HT/Qybl2g8ysd8ytvEgWv/Qy3N229S5L3pCoK3N@4[1jKM4;18w@Mgi8RQ90PEHav/Qy3e>Q5kyb5iZl0>8xt9Q1Yq26<;4NSQy9N@zVFL/i8f448DomYegkXI1:i8fI84ydt2gsW6OD/Z8ys98wPw0t1ybv2gsi8D6i8B490zEgKr/Qybl2g8ysd8ytvEIWr/Qy3N229S5L3pCoK3N@4[11lQ5mlrQ1:kQy1Xcw;18zngA7ewkF/_i8D3i8cU?@4mg4?8Jc91O3@g4fzFE10>8yTw8KwE:NZEBc90yZ//_@x1Gf/ioD6wTMA208fxoc10>8zjTYe;WeuF/Z8ys98yU0o:i8n03Uik0w?i8Ki8:4y9l2gwi8B492x4yvt5xvofzSs1?25Xg@eTM;4ydfrwU?3EEWD/PKE[@5JM4?8eU4}4fxtw10>8zjTnzv/W2WC/Z8xs0fxak;2W2w;37Si8D7WaqD/@W.;37SyuZ9ysrENqr/QC9NQy3@fYfx98;18zjRhe;W3OF/ZcyvF8zngAc4i9ZYnVrQgA88BI9437h2h4}cnVvQgAc4ybw0w;18asb4UvBKOcjzYib20rEE:NvF_h2h8W8iE/Z8w_z_3UgJ0w?i8QZYPs?ezuGf/j8CU2}Yvw[NXky9T@wmFv/i874O:8DEmRR1nA5vMUIda5c?8n9t2PE9Wz/UIUWa2D/Z8yNm9e;i8QR4Fj/QybeAy9Mz70W2mD/Yf7Qg?bQ1:WWJC3N@4[18yTIgKwE:NZKywFL/ysnFpLX/Sof7Ug[4ydt2gwKx:3EQqv/Qy3@fYfxo3@/@bdqBi?25Zw@4sLX/@yAF/_yPzE7qv/QOd1mWj/@V70k0<yd5g6g/Z9ys58yMnMdM?i8QR0pb/Qybe370W8@C/_Fc_X/SoK3N@4[18zngAc8DLyqw}i8B490zECqr/Qybl2g8xs0fxdM;37wx}2:i8RQ922W4:8DLW36D/Z8w_z_3Un7_L/yMk9kw?xs0fxbD@/_E1av/P7JyPzEuWr/QOd1kii/@Vf0k0<yd5l@f/Z9ys58yMledM?i8QRnV7/Qybe370WeSB/_FuLX/MYvx{i8QZpp3/@zAE/_i8QZm8T/QC9N@zlE/_jon_3Uhc_L/i8n03Uh3_L/cvpcyv@W2w;4y9h2g8W5@B/Z8yTMA2bEa:cvp8ykgA8ex9Fv/WhPZ/Yf7Q?yQgAi2k0Y;fg2:fxh3//7wx}1:WjfZ/@b5iZh?25Qw@4NvT/@wGFL/yPzEEWn/QOd1lig/@Ve0k0<yd5oue/Z9ys58yMlSdw?i8QRxV3/Qybe370W1mB/_FxLT/ReX.;4y3X218zngA7ewYE/_i8D2i8cU07goyTMA74y9NAy9h2g8WebB/Z8yRgA28D3i8DnW8ey/Z8wYgwytxrMSpCbwYvx{kXI1:i8fI84ydt2gsWeOy/Z8ys98wPw0t1ybv2gsi8D6i8B490zEgKT/Qybl2g8ysd8ytvEcWb/Qy3N229S5L3pCoK3N@4[1lLg4;1ji8fI64ydt2g4W9Ky/Z8ysd8wPw0t2S3v2g40nYXyPSFhg?i8RQ90yW2:4z7h2g8.;ewtFv/i8fU_TgLcuR8yt_EPq7/Qy3N1y9W5JtMMYvg>8yTw8KwE:NZKywE/_ysvHJMYvg02b1sFf?25M7j7WcCA/YNXoIUW42A/Zczgm8yL/KoI60>8zhkAzv/ioD1i8I54Pk0<yddiif/Z8yPwNMeyOE/_WUJjKM4;18w@Mwi8RQ91PETa7/Qy9MAy3e>Q68JY91N8ysp8ykgA2ey2Z/_i8Jk90y9MQy9R@wzEv/i8f488DomYdCpyUf7Ug[45nglp1lk5klleX.;4y3X5x8zngA9ey3Ev/ioD7i8cU07g9ySMA98fZ1nYxj8D_WdCw/Z8wYhoytxrnk5sglR1nA5vMMYvx{i8JU2bEa:cvp1LL//_ECGb/QCbvN2W2w;37SykgA5ey6EL/ioJ_6bEa:cvq9h2ggW7ay/Z9yTYwKwE:NZED3W62y/Z9yTYEKwE:NZEB491zEjab/UB491O3_gofxgY2;f7Q?pCoK3N@4[15xvpU6Qydt2gUKw4;14yvvE@q7/Qy5M0@eQ<0<ydr2h0yTMA5bEg:i8DKWdGx/Z8w_wg3UmM.?i8J4940NZHE2:ytZ8ykgAaew8Ev/j8J494ybv2ggytF5csB8zkMAc4ydt2gEi8B4933E1Gb/Qy5M0@8Tg;8JY91x8zngAebE8:ict493w1:We6y/Z8w_z_t6Kbv2gsKx:18yuXEOGb/Qy3@fYfxk3/_@b1q9d?25M0@4cL/_@ytEL/yPzE5Gb/QOd1p@c/@Vogs0<yd5vGa/Z9ys58yMnFcw?i8QR@EP/Qybe370W8yx/_FY_X/MYv08IlkAQ?8nit8LEkqb/UIUWcGx/Zczgk8zf/Km070>8zhmKyL/ioD1i8I5Dj80<yddqWc/Z8yPwNMewYEv/WkP/_Yf7U[LM;g3ENFX/Qybt2h0yTMA437ii8B490zEUp/_XE2:cvq9T@zjD/_i8Jk94x8xt9Qi4kNXmof7Qg0<MFWHw;40i8JQ90ybv2ggi3D2ioDkj0Z7U4O9UAQ1VuxaEf/i8JQ90xcyua9T@yHEv/i8Jk94x9etlOMkybv2g8W5uu/_FBvX/SqgctLFqfT/Sof7Ug[4CbvP2W2w;37SW22w/Z1ysrFWfT/MYvx{kXI1:i8fI84ydt2gsW9Ou/Z8ys98wPw0t1ybv2gsi8D6i8B490zEEJ/_Qybl2g8ysd8ytvEUVT/Qy3N229S5L3pCoK3N@4[11lBmZ.;5d8w@MMi8RQ90PEipX/Qy9MQy3e>QhodY90M1vDp8zjSHyf/j8JM2exVFv/xs1Uhkydr2ggys6@8:370i8DLi8Qlf8z/@wUDL/i8DKj8DTcuTE6Wb/Qy9T@xzDv/i8f4c8DEmRR1nIcf7Ug[exXEf/yPzEZ9/_QydfrW5/Z8ysoNMexPDv/Lg4;3HMp1CpyUf7Ug[5d8w@Mwi8RQ91PEEpT/Qy9Mky3e>Qq8dY9,1vC58yTw8KwE:NZAy9h2g8ctLESFX/XEf:LwA4?29NP70W4uv/Z8yQMA28fU_Tgli8DfWcms/Z8wYgwytxrMMYvh;yMnqiw?xs1R7wYv06pCbwYvx{KM4;3HP6of7Ug[eyXD/_yPzEd9/_Qyb5hQM0>8zjmKyL/i8IWi8D2cs3EKpX/Qybj2g8WY9CA45mlrQ1:kQy3X318zngA1ezpDf/i8D3i8cU?@4A:8JI90i3_g4fzHM;18znMA2eylD/_xs0fy8Q;2bv2gccs2W;g0bU71;W7yu/@3_g8fx9s;18zmMA48Jc90y@8:370i8QlFUr/Qy9X@ywDf/i8JX24y9XKy4Ef/yQMA34y9XP70i8QlwUr/XUw:W7Gs/Z8yTIgi8DKcuTEna3/Qy9T@yAC/_i8f4c8DEmRR1nIdC3N@4[3EKVX/UIUW3iu/Z8zjSpxf/i8D6cs3EIVL/XQ1:WY0f7Q?i8J324y9NQC9NKxFC/_i8D5i8n0t7DSg2w4t6Kbj2g8Ly:18znMA4370i8QlYUn/@zLC/_i8DLcsB8zlgA437SW8Wr/@bj2gcLy}NM4yd5sK5/Z8znMA4ez2C/_i8DLcsB8zlgA4bU1:cuTEn9L/@AX//3N@[4O9Z@xoC/_j8DTW22r/Z8ysl8xs0fxnD/_@bv2g8W8Kt/@bv2gcW8at/_FeL/_SqgpCoK3N@4[11lQ5mgll1l5mZ.;5d8w@MEi8RQ91jE4VL/Qy9MQy3e>Q44ibr2gkgofZ17YvLg4;18yt_EoFH/Qy3N2y9W5JtglN1nk5ugl_3A4ybu0yW2w;37SW32s/Z8yTIgKwE:NZAC9NewtDf/i8JX64z7h2go}469NE0_?@5N:4kN_QybuO2W2w;37SW16s/Z8ysl1w_Q53UhY:i8JXa4yddj63/_E19T/XE0>?Lws40>4yvu5M0@kM0@SM8B490wNMewQDf/i8nJt355yul5cuh9yuwNOk6V1g;4i9YAQFU4O9_Ai9X@wtDv/i8n0u71Q24A1N4AVX7blyQgA28n03UmO:cuTF4v/_MYv0bE0>?Lws40>4yvsNMezkC/_NQgA2}18xuRRC37JWur@/YNZHEa:W5ir/Z8w_z_3UgC//i8B491xcznMA6eAq//3NY0W5es/@be8f_2Ti9w_Y43Ui0//yRgA28nitifEJFL/Qydfj@1/@Z.;4y9Nz70W32p/_FwvX/MYv<i9ZQy9h2g8WaKr/Z8yRgA28IWWYtCA4i9ZP7JW9qr/_Fl_X/V1lLg4;1ji8fI64ydt2gcW3Kp/Z8ysd8wPw03UiH:i8IZJQo0<y5_TglLw.E03E@9D/Qz71pR6=yPQTf;xvYfyiY1?2bfikY?25_M@9.4?8IZ4PM?8n_3UDj:yPQ1f;xvYfyqk;2bfuYX?25_TBXyPTZeM?xvZVkkydfq9@/YNXuyzCf/i8QZsUj/@ynCf/i8QZMDX/@ybCf/i8QZNEb/@x_Cf/i8QZxUb/@xPCf/i8DvWeKn/Z8wYgoyuxrnsdCAeyHCL/yPSxeM?Wa2q/_71oUX?3//_WVcf7Q?W8Kq/@bfnQX?371lIX?3//_xvYfy7b//HMp3EqVH/UIZhjI?cs5fPI?f//@5_M@8if/_@L1AexbCL/yPQFeM?NMkzeM?//_Un_3Uwu//WY6gW2Kq/@bfgQX?371gsX?3//_xvYfyf3@/_HMp3E2VH/UIZYjE?cs5WPE?f//@5_M@8MLX/@L1A5l8yul1lQ5mgll1l5eX.;4y3Vc18wuP}i8RQ95jEypv/Qy9h2gMi8cU?@4_wk0<xzn2hkw_I33UYc1w?i8Q5ID/_Qy9h2gww_I13UYY3;i8QZw2A?exHCL/yU<:ykgAb37rj8QZs3E0<OdH2i}goI_xvZU6kydt2hwKx:3EmFz/Qy3@10fx6060>8yMmph;i8KU0<0<yb5oJ40>8yP98evUfwNs60>cyU88.?jon03UzD1w?i8R60kwVNM@3Kwo0<wFZQC9_4y9@_183Y4qi8Idjkg0<ybwg>0>ezjgzj3DM3Ucu1w?i8IlcAg;@SkyC4Qw@49ws0<wFS4y5M7YectLFl//MYvw}18yMQ9h;ioD4wbBz.:@4xwM0<ydx2i}i8B4941azhgzjoDBibz////_vU7y/Yf<ObJd4<2?i8Dqwub/MY0ii76i2e4Qg.8>9asrMj05x44ydfkEE?3EdpD/Qydj2hwib_dPcPcPcPcP4y9PAy9C2:1cyqwo:jonS3UjT2M?A6pCbwYvx{j8DMi8f60kzTVQO9Y4z1Wwdczgiijg70j2D0wY0Miof@2kC9REx6_Tvmi3DN3Udx3;i8DTi8DMi2Dfi8Rn_Qy3@zUfxCAc0>9yvx9yv58yRgAg6bN_kxL9i5W/ZyYvR8rNRnuL/iofwM6bN_kxL5oBW/Zdas5C3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_j3D8ttd9evwfx7Y;18yv14ys9cas19yvBdas5dzl7_iofW7DoPj2D6oL5_a6Z6_Yjzvkr?sjyvg05C7H/Yixvn@418:11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug[6pCbwYvx{3XpM_Qy3W058wY81g8xO_QwVMnbHi6f_i0dY9435@7v6,18yTgAg4ybv2gwWaWo/Z8xtIfx5Ea0>8zkMAo4y9TACUPsPcPcPcPcN8ysYf7Qg?6pCbwYvx{i8DMi8f70kDTU4y9Y4z1WwdczgOijg79j2D8wY0Mi8f@2ky9REx7_Tvmi3DV3Ufn2w?i8D@i8DUi2Dei8Rm_Qy3@zUfxJYa0>9yv19yvB8yRgAg6bN_kxL9q5U/ZyYvR8rNTnuf/iofwM6bN_kxL5gBV/Zdas5C3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_j3D8ttdcesofx7Y;18yvx4ys9cas19yv5das5dzl7_iofW7DoPj2D7oL5_a6Z7_Yjzvkr?sjyvg0567D/Yixvn@418:11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug[6pCbwYvx{3XpU_Qy3W058wY81g8xW_QwVMnbHi6fSi0dQ9435@7v61w18yTgAg4ydflR/_YNQKxqAL/i8Rc9618LYTcPcPcPcPci8DejonJ3UiO2;3NZ?6pCbwYvx{j8DEi8f60kzTVQO9W4z1Wwdczgiijg70j2D0wY0MiofZ2kC9Rox6_Tvmi3DN3Udd2g?i8DTi8DMi2Dfi8Rn_Qy3@zUfxDc90>9yvB9yv18yRgAg6bN_kxL9i5T/ZyYvR8rNRnt/_iofxM6bN_kxL5oBT/ZdasxC3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_ijD0ttdcesYfx7Y;18yv14ysFcasx9yvxdasxdzl3_iofW7DoPj2DeoL5_a6Z6_Yjzvkr?sjyvg05C7v/Yixvn@438:11ZI0vt3R9w@3wh072j2D0i6fii0dk941CpyUf7Ug[6pCbwYvx{3XpM_Qy3W058wY81g8xO_QwVMnbHi6f_i0dY9435@7v6,18yTgAg4ydftNW/YNQKzqAf/yTMAb8n_3UDC1g?ctJ8yTMAcezyAf/i8RBS8DomQ5sglR1nA5vnsegioD7i8fH0uy4AL/ioIkTQyb<wfLxbSh5>27gkioJkT_x83XUiZAhg.wfx6o70>8yRMAc4ybmMx83XUji8Bs923Sh5>20@490o0<ybv2gwKwE:NZKxwAL/ykgAb4yd1k9V/Z8ykgA84ibv2gIhon_3UCx@v/WorV/Yf7Qg;@SgyC4M0@5n0o?8fXp0@4MM8?fegwYc1WoDV/ZC3N@4[18yMQVfw?i8Js961cySgAq4ybwg>0>ezjgzj3DM3Uby@v/i8S498:18yMQcfw?i8B49420Kmc1:3Uke@L/iofY.@4NMo0<S9VkS5V0@4eMo0<Gdd2J8ytx5cuhCbwYvx{i8D2i8f?o7y/Yf?@TB54<;ig7ki3DMtuddyurFZvD/MYv0bI1:Y4wfMhF8yMSnfg0.rM1:Wj_V/Yf7Q?i8Jic4O9M4zTS4y3Ww58yMRPfg?i3DO3Uca0M?i8C12<0<6Y.;4yb3loZ0>azggCi3D7sMp8avt9yvNcyufMi0_16kyb3jwZ0>8yU4g.?i3Do3Ufr@f/j8D2j8D0ifvqY4wfIp48.?i8Id3PQ?eCZ@f/pyUf7Ug[4yb1vAY?3MwQ0o0kydfoQx?3Eu9b/Yq0a}6gi8I5SjM0<yby0>0>8esJPl4y9O4wFS4y9h2gUj3Dw3Ufd:j8DMgoJ_1bEg:j8DKi2D8i8Cc98:18yogAy:4y9j2h8j8BI943EG97/Qybj2h8i8fU40@4Mg80<yb1n8Y;fJA0Fxc0fxpo2?2b1g0O;N_XH//_grw1:grA1:Lw8;18NUgAxw=29x2i}yMnbcg?pECY98U;1cyuZCh8C498g;29x2i8:pAi9z2ic:W8qf/ZCwXMAxw:1ReSq3L2ie[@43f/_Qydfokw?3Es97/U2Ua[fxtc10>dxugfxq_Z/YNS@A3Z/_3NY0yPRqcg?i8RQ962W2:exrz/_pEeY98U}3UiY_L/WWVCbwYvx{i8I5yjI?f23g1w1KM4;11L<;11Lw4;18zjQc8;Wfug/_5@u_0hj7rpECs98g;1yYnY8vUgAxw;6p4ypMABw;6p4yqgAz:6p4yrgAB:cq0a}6b1skM?29x2i}yMmQc;yogAy:46b1UC499:3HeMYvh;KL//@@0M;4O9X@xKzL/ZEgABw:5RdSq3L2i6[@5zg4?6q3L2ie}7kti8I5MPE0<ybw0>0>8yNmRew?i8Iii3D2sWR8zjR67M?W36g/@0K2w}3UhSZL/i8I5zjE0<y5M7gbyR0oxt8fxmQ20>8zjQm7M?W06g/YNSYq0a}3FE_n/MYv<y9YE7y/Yf<gfJVhh>;bE1:j8J926p5xt9c3Qjict99Z_aWg:4wVQ4wfhY9dxsCW.;4MfhcFcesxc3Qr8K<;1dysNdxsBc3QjwWq_Y/Yf7Qg0<yb3vAV0>8xsBQ2UJ168n03Umi:i8QZwxU?exJz/_NE0E}eD@_v/A4wFSrw}ioDcj0Z8UeDg_v/3NZ?8IZkyY0<ydt2hwKww;18NQgAo<;3EKEX/Qy3@fYfx3410>8zjQF7w?W1if/Z8yMRZeg?wbwE[@4KM;4y5Og@4GM;4Obp2gUyQ4oxs0fx6X//MwSAo0uBA//3NZ4?2bfu8K0>8zngAmbE8:Weec/_FwvX/Sof7Qg0<yb1i4V?21U/_3M0NQAy@////_TZ88Xjo>0w0ew2zf/i8fU_M@5WLD/UI5@zw?8n03Ujs@v/Wfmd/YNSUIUW6Od/Z8yNll7w?i8QRJDz/QybeAy9Mz70Wf6c/_FIfD/Yq0a}1cySgAeeCA@L/W4qc/Z8yQMAc4yb<ybigx83XUhi8Bc923Sh5>20@5VvD/UfX0w@4BLf/Qybh2gMKwE:NZAybu13Ee8P/UB492PFT_D/Qib5m0U0>5xt8fxb_@/_EmET/UIUWdec/ZczglIsv/Ksw40>8zhmTtv/ioD1i8I5FxQ0<yddrtT/Z8yPwNMex5zf/Wo3@/_MwSwo0uC9_v/pwYvh;i8I5@js?f18wSw80rI2:3Ujs@f/i8JY9218zjkasv/KM4;3EoEX/@D1@f/Kz:1CypgAw:eCe@f/Kj:1CyoMAw:eDYZL/Y4y3gh?i8QZf,?ewDzv/i8Co8:4z7w1w+Lz:1CyrgAw:eB6Zv/i8fU0ngTioD5i8S498:18ykgAgeBQ@v/ioJv44CbvNyW2w;37Si8Bs923E3UL/UB492PFJLz/Qydx2i}i8B4941cyX48.?i8Dq3Xq1oM4?87y/Yf<S5ZDUXi8eYQg.8;u324M7lljoDQgrQ1:WjHP/Z8yTMAgeCSZ/_i8JQ943Fbfr/Qybv2h0WqbQ/Z43XuQkg.?3HNkkNM37iWoPR/Z5cs0NQKA2Zf/hj79ctbF@fr/Q6Z.;46Y.;eDyYL/3N@4[1lLg4;1ji8fI64ydt2gcWeK8/Z8ysd8wPw0t4t8zjQb6M?Wfqb/@0K2w}t318yMlmdw?i8n0t16bk1y5QDgaY8dE6<f7Qg0<ydftAq?3EN8L/Yq0a[NXky9T@w3yf/i8f468DEmRT3pyUf7Ug[5mZ.;5d8w@MEi8RQ91PEqUz/Qy9MQy3e?fxaY;2bl2gsw_E13UWy:i8JE24ydduVQ/@9l2gci8DLWcGa/@bl2gcxs0fx9o;18zjmWrL/i8DLWa@a/@5M7lGi8IJF3k0<ydfjQq?3Ea8L/U2Ua}1QcAy5XngqyQkoxs1Q4_23rhw1i8IJtPk;Yvw}18zjQ96w?Wfia/_6w2w}Y4y3rgw1i8QZY1A?ezryL/NU<://_P7Ji8DvW1u7/Z8wYgEyuxrnsdC3NZ40>8yMkxdg?Y4y3g0w1w_E2tdnEIoz/QybuN18yM183XUnZAhg.xQLHEa:cvrEMUz/Qy9NkydfoAp?3Et8H/UCE1:37JWVJCbwYvx{glt1lBlji8fIi4ydt2gsW2O7/Z8ysd8wPw0t0R8oSMA78R5_ofU0DouLg4;18yt_Euor/Qy3N4y9W5JtglV1nYcf7Q?i8JX2bEa:cvrEi8z/QybuN2W2w;37SgoD6W5m8/Z9ysu3_gcfx9A;18yTIoi8QRv6/_Qy9v2g8W4i9/YNQEn0t1V8yTMA24yddsxN/_EboD/XE2:xs0fxpw;1cyvV4yvvE5ov/Qy3@fYfx6n/_Z8zmPH@4yblg20ew1QlQOdh2gwi8D1Ly}NM4O9NQyd5iBO/ZcykgA2exWxL/i8JZ<ybt2g8cuTEmEH/@AA//3NZ4?2W.;4y9NAi9Z@yMxL/i8fU_M@40f/_Qy9NAydfr5N/YNM37JW5e8/_FXvX/Sof7Qg?bE1:WlX/_Yf7M1CpyUf7Ug[45mlld8w@Mgi8RQ90PEPEn/Qy9MQy3e>Q1UdY90M2vNWZ.;4y9T@wxxv/i8f448DEmRR1nIdC3NZ40>8yTw8cvqW2w;ezMxL/i8JH44yddl9M/Z1ysp8yu_E2Ez/Un0t4V8zjl_r/_i8DLWfu7/@5M7hji8QR06T/Qy9X@zAx/_xs1Qm4yddg5K/Z8yu_EQov/Un0tlR4yvsNXuxPx/_Wnn/_ZC3NZ4?2@.;4i9ZP7JWaC6/_Fm//MYvg?NZAi9ZP7JW9i6/_FhL/_MYvw}2@0w;4i9ZP7JW7C6/_Fa//MYvg>8yuV8zjRprL/cs3EvUj/@Ac//pyUf7Ug[45mlld8w@Mgi8RQ90PEHEj/Qy9Nky3e?fx443?23v2gc.@e1w80<ybg0x8yst9ysrE1Uj/Qy9MQy5M0@4@M8?fp0a.fxeA2;NOj7Si8QlXmX/Qy9T@w@xf/csC@.;4y9TQyd5gRG/_Ea8j/P79Lw8;18ytZ8zhl1r/_W1a4/YNOrU3:i8Dvi8Qlin3/@zYw/_csC@1:4y9TQyd5mlG/_EVEf/P79Lwk;18ytZ8zhkAr/_Wd23/YNOrU6:i8Dvi8QlhmH/@yWw/_csC@,;4y9TQyd5rNK/_EF8f/P79Lww;18ytZ8zhmdr/_W8W3/YNOrU9:i8Dvi8Qlmm/_@xUw/_csC@2w;4y9TQyd5t1G/_EoEf/P79LwI;18ytZ8zhk9q/_W4O3/YNOrUc:i8Dvi8QlfSP/@wSw/_csC@3g;4y9TQyd5jNF/_E88f/P79LwU;18ytZ8zhnUrf/W0G3/YNOrUf:i8Dvi8QlaCD/@zQwL/csC@4:4y9TQyd5m1H/_ETEb/P79Lx4;18ytZ8zhl9qL/Wcy2/YNOrUi:i8Dvi8Ql3SD/@yOwL/csC@4M;4y9TQyd5kdH/_ED8b/P79Lxg;18ytZ8zhnpqv/W8q2/YNSQy9X@wcwL/i8f448DomRR1nIegi8QZ46T/@zkwL/i8QZfmz/@z8wL/i8QZuST/@yYwL/i8QZzmX/@yMwL/i8QZISz/@yAwL/i8QZv6T/@yowL/i8QZFSz/@ycwL/i8QZa6T/@y0wL/i8QZ0SX/@xQwL/i8QZSmT/@xEwL/i8QZmCD/@xswL/i8QZDmD/@xgwL/i8QZTmH/@x4wL/i8QZV6v/@wUwL/i8QZGCL/@wIwL/i8QZVCv/@wwwL/i8QZ9CH/@wkwL/i8QZ6mD/@w8wL/i8QZWmv/@zYwv/i8QZ9SH/@zMwv/i8QZNSz/@zAwv/WuD@/Yf7U[j8DTW721/ZcyvvEe87/Qy9MQy5M0@5@_P/V1CpyUf7Ug[bI1:Wrb@/ZC3NZ40>8w@M8i8IZDhc?bU1:W4K1/Z8yPSk4M?Lw4;3EeE7/QybfoIj?2@.;ewFwv/i8IZwxc?bU1:W1y1/Z8yPRV4M?Lw4;3E1U7/Qybfn0j?2@.;ezSwf/i8IZpNc?bU1:Wem0/Z8yPRu4M?Lw4;3ER83/Qybflkj?2@.;ez3wf/i8IZj1c?bU1:Wba0/Z8yPR34M?Lw4;3EEo3/QybfjEj?2@.;eygwf/i8IZchc?bU1:W7@0/Z8yPQE4M?Lw4;3ErE3/QybfhYj?2@.;extwf/i8IZ5xc?bU1:W4O0/Z8yPQd4M?Lw4;3EeU3/Qybfggj?2@.;ewGwf/i8IZ@N8?bU1:W1C0/Z8yPTO4w?Lw4;3E283/QybfuAi?2@.;ezTv/_i8IZU18?bU1:Wep/_YNM4y3N0z3+f/////EdM=1-4-g+b-s+i1c=8+60f=2g+o+1s+G28=2+d05=5-7-c+Qfs=6+d03=2M+o-k+s0M=a+3A5=6g=20Tw{1I+2-q+7zu=7-8+f3/SY}Gx4{3@/ZL}6gi=//rM}2-M+q4I=d+5xb=ZvX_rM}U0M~~~(31g=s5~~~~~~~~&f/////////////}f/////L3k=ecM#1Nd=7wW!dsR=ZPk!k3k{1tdg!Rd=csT!7IU=tzc!vjg{1Ncw!ddM{2AS!b4T=lP8!qjg{2Xdw!udM=IU!6kP+Pk!Czc{2Meg#13e=fsO!aMS=e3I!EPs{36cw#3BdM{8YT!7IS=bj8!7jo{1Be!0Sdw{48S!acO=838!X3w{2pdg#2Pd=a37+g=2wXM=UP~zzc=MIg=4+MeY{1Uew`e8Q=saY=1+e3L=ZPk`2ocw{836+g-Y=5QR~L3c{2MHw=4+8f=37dM`bQQ+aU=1+43M=tzc`1Ncw{b2J+g=1wY=74O~ajo{30Gw=4+wf+Fdw`5sO=saE=1+a3M=lP8`14dg{235+g=30Y=bIS~@3c{2MGg=4+Uf+be~aAP=oaA=1-3N+Pk~se=12F+g+wYg{b0V~ezw=MFg=4+gf4{3Tcw`5cT=Uag=1+63N=e3I`36cw{a2A+g=20Yg{coO~zPs{1wMM=4+Ef4{2fdM`bEO=Ucc=1+c3N=bj8`28e=b2Q+g=3wYg{6kU~qzs{1gF+4-f8{12dw`20O=4bc=1+23O=838`3Ddw=2A+g=10Yw{9AR*2ET!]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=A4I{]{91b=2:1{g?hQ4A0jdxcg1oiM{6lb=2:1{g?hQ4A0jdxcg1EiM{7Bg=hQd3ey0EhQVlai0NdiUObz4wcz0Odj4Ocj4wa59Bp218ongwcjkKcyUNbjkF06RLr6gwcyUQc2UQ82xzrSRMonhFoCNB87tFt6wwhQVl86NAag;2VPq7dQsDhxow0KrCZQpiVDrDkKs79Ls6lOt7A0bCVLt6kKpSVRbC9RqmNAbmBA02VDrDkKq65Pq?Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bClEnSpOomRB02VBq5ZCsC5JplZEp780bD9Lp65Qog0KsCZAonhxbCdPt34S02VOrShxt64KoTdQcP80bD9Lp65QoiVPt78Nbz40bD9Lp65QoiVPt78Nbzw0bCpFrCA0bCBKqng0bD1It2VDrTg0bDhBu7g0bDhAonhx02VQoDdP02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpCBKqlZxsD9xug0KqmVFt5ZxsD9xug0KsClIsCZvs65Ap6BKpM0Kp65Qog0KpSZQbD1It?Kt6RvoSNLrClvt65yr6k0bC9PsM0KpSVRbC9RqmNAbC5Qt79FoDlQpnc0bCdLrmRBrDg~~(0b:,:8+U08{3w0w{3%8^7w:s:2+103=40c=A^1^34;3S/ZL0w+U0M{3w3=C-4-w^X:2M:8+Q0c{3g0M{a08=1g:4:8+1w+gM:c:2+70c=s0M=V1g&g&4I;3/_ZL0w=2G4g{aEh=K-4-8-w=1o:_L/rM8+p18{1A4w{e-1g:8:4^pM:g:2+4wj=i1c{1w3M=g+2-o+74:4:gw=2E8w{awy=Q0k=4:7M:w+6+1X}g:8+u2w{1Ua=6M7&8^xg:4:2+egL=V2Y=s.*1^9c:1}w-cg+N=M^4^2r}g;18+M34{30cg{3%g+1-Gg:4:i-0O+38=w^8-w+bs:1:cw+wcw{20O=X0o&4-g=36}g;38+43A=geg{4w2&8-4+Rg:4:6+5xb=m3I=d^1^dI:1:1w=1EiM{6wX=6M^g&1S}g:o+A4I{2geM+4&g^Ug:4:6+91f=A3Y=8^4^eE:1:1w=30jM{c0_=QnM*4^3M}g:c4=CdM{2oL+w^4^ZM:w:31=a3s=EbM=x^2^fQ:1}M=2wT=a2Y=2%w^a.0>w:c+GdM{2EL=d>=1g+8+1-4M4;Y:3+7zu=ubU=8^2-8+1Y1;e}M=20Tw{82@=2%w+2+3B}g:c+ydU{28Lw{fw^8^aM4;w:3+83v=wbY{2%.&3E1;1}M=20XM{82_=k0w*2^10.;g:c+Qfs{3gNM=w2&8^ig4;4:3+dzV=ScA!2^5A1;8}M=3o@g{dz9=9%w&1u.?,%;3oOg{4w^4^t<;4:M^8cE{1k%g+1-4:3$7ja=vg4&4&')


_forkrun_bootstrap_setup --force

${extglob_was_set} || shopt -u extglob
unset extglob_was_set
