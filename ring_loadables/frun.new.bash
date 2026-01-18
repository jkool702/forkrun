#!/usr/bin/bash
frun() {
(
    # 1. WRAPPER LOGIC (Current Shell)
    [[ "${1}" == '__exec__' ]] || {

        # Check if already setup (and FD is valid), otherwise bootstrap
        { ${FORKRUN_RING_ENABLED:-false} && [[ -n ${FORKRUN_MEMFD_LOADABLES} ]] && (( FORKRUN_MEMFD_LOADABLES > 0 )); } || _forkrun_bootstrap_setup --fast

        # Export FD for reference
        export FORKRUN_MEMFD_LOADABLES
        
        # Generate list of loadables to enable in the new shell
        (( ${#ring_funcs[@]} > 0 )) || ring_list 'ring_funcs'
        printf -v ring_enable '%s ' "${ring_funcs[@]}" 

        # EXEC into Clean Room
        # /proc/self/fd/ is safer than $BASHPID in some namespace contexts
        exec "${BASH:-bash}" --norc --noprofile -c '
            enable -f "/proc/self/fd/'"${FORKRUN_MEMFD_LOADABLES}"'" '"${ring_enable}"' ring_list
            export LC_ALL=C
            set +m
	    shopt -s extglob
	    '"$(declare -f frun)"'
            frun __exec__ "$@"
        ' -- "$@" 0<&${fd00} 1>&${fd11} 2>&${fd22}
        
        # (Exec replaces process, so we never reach here)
    }

    # 2. WORKER LOGIC (Clean Shell)
    shift 1 # Remove __exec__

    # # # # # SETUP # # # # #
    local cmdline_str ring_ack_str delimiter_val ring_init_opts pCode extglob_was_set worker_func_src nn N nWorkers0 fd0 fd1 fd2
    local -g fd_spawn_r fd_spawn_w fd_fallow_r fd_fallow_w fd_order_r fd_order_w ingress_memfd fd_write fd_scan nWorkers nWorkersMax tStart
    local -gx order_flag unsafe_flag stdin_flag mode_byte order_flag unsafe_flag LC_ALL LOCALE
    local -ga fd_out P

    LC_ALL=C
    LOCALE=C
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
        
    ${extglob_was_set} || shopt -u extglob

    # Config Vars
    order_flag=false
    unsafe_flag=false
    mode_byte=false
    verbose_flag=false
    delimiter_val=$'\n'
    ring_init_opts=()

    # Parse Arguments
    while true; do
        case "$1" in
            -o|--order)    order_flag=true ;;
            +o|--no-order) order_flag=false ;;
            
            -u|--unsafe)   unsafe_flag=true ;;
            +u|--safe)     unsafe_flag=false ;;
            
            -s|--stdin)    stdin_flag=true ;;
            +s|--no-stdin) stdin_flag=false ;; 
            
            -v|--verbose) verbose_flag=true ;;
            +v|--no-verbose) verbose_flag=false ;;

            -z|--null)    delimiter_val='' ;;
            
            -n|--lines|--limit) 
                shift; parse_count "lines" "$1" ;;
            
            -b|--bytes) 
                shift; parse_count "bytes" "$1" 
                mode_byte=true ;;
                
            --workers)  
			    shift; parse_count "workers" "$1" ;;
			
            --timeout)  
			    shift; ring_init_opts+=("--timeout=$1") ;;
            
            -d|--delim|--delimiter)
                shift; delimiter_val="${1:0:1}" ;;
				
            --) shift; break ;;
			
            *) break ;;
        esac
        shift
    done

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
    if ${order_flag}; then
        ring_init "${ring_init_opts[@]}" --out=fd_out
    else
        ring_init "${ring_init_opts[@]}"
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
        ${order_flag} && {
            ring_pipe fd_order_r fd_order_w
            (
                exec {fd_order_w}>&-
                ring_order ${fd_order_r} 'memfd' >&${fd1}
            ) &
            exec {fd_order_r}<&- 
            export FD_ORDER_PIPE=$fd_order_w
        }

        # --- WORKER DEFINITION ---
        printf -v cmdline_str '%q ' "$@"
        ring_ack_str="ring_ack $fd_fallow_w"
        ${order_flag} && ring_ack_str+=" $fd_order_w"

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
                cmdline_str='IFS='"${delimiter_val@Q}"' '"$cmdline_str"' ${A[*]}'
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

        worker_func_src='spawn_worker() {
(
  LC_ALL=C
  LOCALE=C
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
        ${order_flag} && exec {fd_order_w}>&-
        
        wait
        
        ring_destroy
        exec {fd_write}>&- {fd_scan}>&- {ingress_memfd}>&-

    } {fd_write}>"/proc/${BASHPID}/fd/${ingress_memfd}" {fd_scan}<"/proc/${BASHPID}/fd/${ingress_memfd}" {fd0}<&0 {fd1}>&1 {fd2}>&2
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
declare -a b64=([0]=$'108782 54392\nmd5sum:ee398519c70d82c21c66f1993d232470\nsha256sum:f886e0b5390163f4faa21de91b05ec1f609091cb1599ac8bb5989900dfb1d562\n0000000000000000000000000000000000000000\n000000000000000000000000000000000000000\n00000000000000000000000000000\n0000000000000000000000000000\n0000000000000000000000000\n000000000000000000000\n00000000000000000000\n0000000000000000000\n000000000000000000\n000000000000000\n00000000000000\n0000000000\n000000000\n6pCbwYvx\n00000000\n0000000\n000000\n00000\n0000\n000\n04\n01\n1M\n0g\n00\n__\n0,yYJR8zk3_i8fEg4y3MA1yYDR8\034vQlchw81.-?c0fw,)1-3zb-;4?e?c<?9g0A?o:4:g+1-4-E08[2w0w{w+1]g;3w0w[e02{U08[1k+5g+2-1:1![80X{w3I+4+4:5:w3I[20iM[81b{ko{1hw-g+g:o;3oKM[dzr{SdI[3E0w[2w4+1+1:1w;c2@{MeU[30Xw[5wa{v0E+4+s:4:SbI[3oSM[dzr{2-l-w-w:o;3EKM[ezr{WdI[3g.[d,{2+1gVnhA1:eML{X2Y[3IbM[>1{7<{4+5fBt6g4:U08[3w0w[e02{c-M-w+kulQp0o~*g{1iVnhA1:dyX{SdI[3oSM[ew2{a.{1-g:w:1g;4telg,?7,:3A-w,M.:d-g:k]M;4telg1o1HCRNrbppDiUCRJM7r8Wlex6t}3:hg:g:q:2?8hcog20w0ylggy0q0ar408280<0,I4g;w4,5:iw;58:upbAfcxJTjYW1YjIChYy7MmIv89PfjdG0CR8nv4gfGRj34KXQ6YlilKYw8Dx1zT9j7qGfpHeFTQFXPz_2tWSSC5vClUo0aN0yUFFHb8HEDBg@FGsyt9rIvlkSGw!?2]w$2Y:w$4I:w$6k:g$7c:g$7I:g$84:g$8Y:g$ac:g$bs:g$ck:g$dQ:g$eU:g$<1;g$141;g$2c1;g$2Y1;i$3o1;i$3Y1;i$541;i$5o1;h$5U1;i$6o1;i$7g1;i$7A1;i$841;i$8M1;i$9g1;i$9I1;i$a81;i$aA1;i$bc1;i$bE1;i$bY1;i$co1;i$dg1;i$dA1;i$e,;i$f,;i$fw1;i$0A2;i$182;i$1A2;i$2A2;h$302;i$3w2;i$3Y2;i$4s2;i$4Y2;i$5s2;y$6o2;i$6Q2;i$7o2;i$7Q2;i$8c2;i$8E2;i$9o2;i$9Q2;i$ag2;i$aI2;i$bM2;i$c82;i$cE2;i$dA2;i$dU2;i$ek2;i$eQ2;i$fk2;i$.3;h,U08fo{M+1o3;h,U0ofg{M+2s3;h,U0of8{M+3A3;h,U08f8{M+4E3;i,k0kcE[21.[6k3;h,U0Ufc{M+783;h,U08fc{M+8E3;h,U08fk{M+9Q3;h,U0Uf8{M+bo3;h,U0Efg{M+cw3;h,U08fg{M+dI3;h,U0Uf4{M+eU3;h,U0Ufk{M-44;h,U0Ufg{M+144;h,U0Efk{M+2M4;h,U0Efo{M+4<;h,U0ofc{M+5g4;h,U0Efc{M+6w4;h,U0ofk{M+7I4;h,U0Ufo{M+8M4;h,U0Ef4{M+9Q4;h,U0ofo{M+b44;h,U0Ef8{M-1Iqm9zbDdLbzo0r6gJr6BKtnwJu3wSbjoQbDdLbz80nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0oCBKp5ZSon9Fom9Ipg1Urm5Ir6Zz07xCsClB06pFrChvtC5Oqm5yr6k0oCBKp5ZxsD9xulZSon9Fom9Ipg1yqmVAnS5PsSZznTpxsCBxoCNB069RqmNQqmVvpn9OrT80rm5HplZKpntvon9OonBvtC5Oqm5yr6k0pSlQnTdQsCBKpRZSomNRpg1yqmVAnS5OsC5VnSlIpmRBrDg0tmVyqmVAnTpxsCBxoCNB06RxqSlvoDlFr7hFrBZxsCtS065Ap5ZytmBIt6BK07dQsCdMug1PrD1OqmVQpw1vnSBPrScOcRZPt79QrTlIr,MtnhP06lKtCBOrSU0sTBPoSZKpw1zr6ZzqRZDpnhQqmRB06pOpmk0r7dBpmISd,PpmVApCBIpjoQ071Opm5Adzg0rT1BrzoQ07lKr6BKqM1JtmVJon?rmJPt6lJs3oQ06RJon0Sd,MrSNI07dQsCNBrw1vnSdQun1BnS9vr6Zz079Bomg0tndIpmlM05ZvqndLoP8PnTdQsDhLr,PundFrCpL05ZvqndLoP8PnTdQsDhLr6M0sSxRt6hLtSU0rm5Ir6Zz06dLs7BvpCBIplZOomVDpg1Pt6hBsD80pD1OqmVQpw1JpmRzq780pCdKt6MSd,CsThxt3oQ06lSpmVQpCg0nRZzu65vpCBKomNFuCk0sThOoSxO07dQsClOsCZO06RBrndBt,zr6ZPpg>sCBKt6o0pC5Ir6ZzonhBdzg0rmlJoT1V06pTsCBQpg1Pt79zrn?nRZBsD9KrRZIrSdxt6BLrw1TsCBQpg1PundzomNI071LsSBUnSRBrm5IqmtK071Fs6k0sT1IqmdB07dQsCVzrn?rmlJsCdEsw1vnThIsRZDpnhvomhAsw1OqmVDnSdIomBJnTdQsDlzt,OqmVDnSdLs7BvsThOtmdQ079FrCtvpCdKt6NvsThOtmdQ079FrCtvs6BMplZPt79RoTg0sSlQtn1voDlFr7hFrBZCrT9HsDlKnT9FrCs0r7dBpmJvsThOtmdQ079FrCtvpC5Ir6ZTnT1EundvsThOtmdQ079FrCtvpC5Ir6ZTnTdQsDlzt,OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZPqmtKomNvsThOtmdQ079FrCtvsT1IqmdBnTdQsDlzt,OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZxoSJvsThOtmdQ079FrCtvoSNBomVRs5ZTomBQpn9vsThOtmdQ079FrCtvp6lPt79LulZPt79RoTg0sCBKpRZCpnhzq6lOnTdQsDlzt,OqmVDnSBKp6lUpn9vsThOtmdQ079FrCtvqmVDpndQnTdQsDlzt,OqmVDnSBKqnhvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0sCBKpRZPoS5KrClOnTdQsDlzt,OqmVDnTdBomNvsThOtmdQ<tcik93nP8KcM17j4B2gRYObz8Kdg17j4B2gRYObzk0hQN9gAdvcyUT<tcik93nP8Kcj?hQN9gAdvcyUNd,7j4B2gRYObz4T<tcik93nP8Kczs0hQN9gAdvcyUOe,7j4B2gRYObzcP<tcik93nP8KcPw}g,0<0.,0<0.,0<0.,0<0.,0<0.03?c03g03?c?M09?c?M<?c?M03?c?M03?c?M<?c?M0d?c03g03?c02w03?c?M0b?M,w03?c?M03?c?M07?w?M03?c?M03?c?M05?c?M020<0.,0<0.,0<0.,0<0.,0<0.,0<0.,0<0.,0<0.:40.0b:4:2]jqmAd;20c84+g0b0<:g+7kqqgA;c0P.0,]jqmAd;40c84;g:5mBF3g0,g3o1;4:1tFqgQ;o0Uwg0,:2gApo6;70eM4;g:B96m1w?203T1;4:9uhBwo;A?wk0,:27Apo6;a?Q5;g:y96m1w?2M0o1g0<:behBwo;M08Mk0,:2UApo6;d02U5-;e3r{2+3wSM[bzt{2-Mk{c3t{2+>k{e3K{2+3Odg[ezK{2+1ecM{3L{2+2Nd+zL{2+2wew[23L{2-ddw[2zL{2-Jdw[43L{2+26dg[4zL{2+2jdg[63L{2+1Rd{6zL{2-pe{83L{2+3de{8zL{2+2ScM[a3L{2+2Zd{azL{2+2Ncw[c3L{2+1vdM[czL{2+1Xdw[e3L{2-3e{ezL{2+2ncw{3M{2+2Fd+zM{2-ddM[23M{2+>dM[2zM{2+1te{43M{2+2BcM[4zM{2-Vdg[63M{2+3qcM[6zM{2+1vdw[83M{2+2le{8zM{2-TcM[a3M{2+3@dw[azM{2+1weM[c3M{2+3RdM[czM{2-6cM[e3M{2-Te{ezM{2+3xdM{3N{2+3ddw{zN{2+1Jcw[23N{2+1jdw[2zN{2+2Te{43N{2+28dw[4zN{2+2kdw[63N{2+3zcw[6zN{2+1wcw[83N{2-@eg[8zN{2+3fdg[a3N{2+3Fd{azN{2+3wNw[bzN{2+3wXw[c3N{2+1ecM[e3N{2+3ecM[ezN{2+2gI{fzN{2-0XM{3O{2+2wew[23O{2-odg[2zO{2+3gHw[3zO{2-wXM[43O{2-Jdw[63O{2+3ocw[6zO{2+30Ng[7zO{2+10XM[83O{2+2jdg[a3O{2+3YcM[azO{2-gHw[bzO{2+1wXM[c3O{2-pe{e3O{2+3Pd{ezO{2+1wHg[fzO{2+20XM{3P{2+2ScM[23P{2+2Ncw[2zP{2-gHg[3zP{2+2wXM[43P{2+2Ncw[63P{2+1Xdw[6zP{2-wGw[7zP{2+30XM[83P{2+1Xdw[a3P{2+2ncw[azP{2+3gGg[bzP{2+3wXM[c3P{2+2ncw[e3P{2+1Wdg[ezP{2+1wN{fzP{2-0Y+3Q{2-ddM[23Q{2-Ud{2zQ{2-gGg[3zQ{2-wY{43Q{2+1te{63Q{2+3FcM[6zQ{2+30G{7zQ{2+10Y{83Q{2-Vdg[a3Q{2+1Ke{azQ{2+>G{bzQ{2+1wY{c3Q{2+1vdw[e3Q{2+2ce{ezQ{2+3gF{fzQ{2+20Y+3R{2-TcM[23R{2+2BdM[2zR{2+20F{3zR{2+2wY{43R{2+1weM[63R{2-6cM[6zR{2+10F{7zR{2+30Y{83R{2-6cM[a3R{2+3xdM[azR{2+2wMw[bzR{2+3wY{c3R{2+3xdM[e3R{2+3Wcw[ezR{2-wMM[fzR{2-0Yg{3S{2+1Jcw[23S{2+3qe{2zS{2-gJ{3zS{2-wYg[43S{2+2Te{63S{2+2YdM[6zS{2+3MEM[7zS{2+10Yg[83S{2+2kdw[a3S{2+1wcw[azS{2+>Iw[bzS{2+1wYg[c3S{2+1wcw[e3S{2-VdM[ezS{2+2wEM[fzS{2+20Yg{3T{2+3fdg[d3t{4^e3t{1w:4)ezt{1w:8)f3t{1w:c)azu{1w;1k)b3u{1w;2M)bzu{1w;38)13u{1w;4k)4zu{1w;4o)8zu{1w;4s)93u{1w;4w)5zu{1w;4E)73u{1w;4I)33u{1w;4M)7zu{1w;4Q)43u{1w;4U)53u{1w;4Y)9zu{1w;5(1zu{1w;54)3zu{1w;58)23u{1w;5c(3u{1w;5g)6zu{1w;5k)63u{1w;5o)2zu{1w;5s)fzt{1w;5w)a3u{1w;5A(zu{1w;5E)83u{1w;5I)2zT{>:g)33T{>:k)3zT{>:o)43T{>:s)4zT{>:w)53T{>:A)5zT{>:E)63T{>:I)6zT{>:M)73T{>:Q)7zT{>:U)83T{>:Y)8zT{>;1(93T{>;14)9zT{>;18)a3T{>;1c)azT{>;1g)b3T{>;1o)bzT{>;1s)c3T{>;1w)czT{>;1A)d3T{>;1E)dzT{>;1I)e3T{>;>)ezT{>;1Q)f3T{>;1U)fzT{>;1Y(3U{>;2(0zU{>;24)13U{>;28)1zU{>;2c)23U{>;2g)2zU{>;2k)33U{>;2o)3zU{>;2s)43U{>;2w)4zU{>;2A)53U{>;2E)5zU{>;2I)63U{>;2Q)6zU{>;2U)73U{>;2Y)7zU{>;3(83U{>;34)8zU{>;3c)93U{>;3g)9zU{>;3k)a3U{>;3o)azU{>;3s)b3U{>;3w)bzU{>;3A)c3U{>;3E)czU{>;3I)d3U{>;3M)dzU{>;3Q)e3U{>;3U)ezU{>;3Y)f3U{>;4(fzU{>;44(3V{>;48(zV{>;4c)13V{>;4g)1g-nFi?5U4<r30s8A<?7g:s:W2s?3k2:iMUgzw923xyd0Q8e88M4igUExwl13z231Asek60a3z19MMUEgsoe84bc3xx2PgUggIUe24wb0T,2wUMhccea4763y12P0UogIQe44be3wxd2T0e2cf6PcTei0VgwMq61oM4zgee0yw;2k:I2A?eU]ggUgwM993B1e2wUgggU8hMI2kwEe44ke24Ab8:c:1Qaw?cM4;113x230AUeo09l2wUggMU8igI0j:eg;2gaM?xgM;123x2f0A8e68U3gwUwzgh53yyc1k4ec8o6ggUUwMt73E090ZQ12wUUggUMggUEgwUwgwUogwUggwU8hgI;1A:d<?d0T?3Va:4Ie48Y2hMUozwd23y2d148ea8M5ggUMxwp43zy31QAeI0c3D0Qe2cf6PcTePR0eI0e31Uo6z0md18U3zM82XwEee4cec44ea48e848e648e448e244b<w;2s.?q6;cw]gwUgzM923xye0Qke88Q4gwUEz0l13z261A4ee8c7h0Vg0FQa3zx43z113yx23y123xx23x123wx52M1c:W<?eNw;G0w;58e48Y2hMUozwd23y2d148ea8M5ggUMxwp33zy31QEeY0w3rg4a3zx33z113yx23y123xx23x123wx42M;4w:U0w?P68?9g1:kwUgzM973xye0Qke88Q4gwUEz0l13z261A4ee8c7iwXw20dr.UUgMUMggUEgwUwgwUogwUggwU8;I:x08?21A0,7>;4Me48o2i0Q6ioY3zwid1oM6wMs3fMca30s8ggI;1A:J080<1H0,e2M;4Ie48Y2hMUozwd23y2d14kea8M5ggUMxwp43zy31QAeU0c3_g4a3zx13z113yx23y123xx23x123wx22MaM3wz3NIPdPIZg3K03wMu61EM5zgie0UY2<M:s0M?a7o?ds1:kwUgzM973xye0Q8e88Q4gwUEz0l13z261A4ee8c7iwWgwwg3bw4a3zx13z113yx23y123xx23x123wx72M?7:6M3?2UtM?hg:113x230AAec7se44ce2?s:z0c?exT0,5]44e48c2igUMtMUggMU8,M;2I0M?67w?3Y]ggUgwM993y1N3x133ww07:cM3;Uu;hg:113x230AAec7se44ce2,4:X0c?6xU?2p0M;48e48Y2gwUozwd23y2c144ea8o5hwUMwMp73L,0WQ12wUMgMUEggUwgwUogwUggwU8ggI:s:d.?c1X0,5]44e48c2igUMtMUggMU8,M;1k1;Y7I0<k]ggUgwM993z1T3x133ww0a:7g4;wv;M]113x260Aoe68c3h0UM0AMa3xx33x113wx52M0s:E.?bhY0,5]44e48c2igUMtMUggMU8<w;3,;V7M?ew2:gwUgzM923xye0Q8e88Q4gwUEz0l13z261A4ee8c7igWg0mwa3zx33z113yx23y123xx23x123wx92M0s:30k?8x_0,5]44e48c2igUMtMUggMU803]I1g?K7Y?ag]gwUgzw913xy60Qoe88c4h0Vg0Cga3y133xx13x123wx92M0w:o0k?3i;2@]44e48c2h0UM0BEa3x133wx62M0M:x0k?d2;2P.;48e48U2ggUoxwd63y2314gek0aP2wUwgMUoggUggwU8iwI0i:bw50,sww?TM4;123x2f0A8e68U3gwUwzgh23yyc1k4ec8o6hwUUwMt43C1L2wUUgMUMggUEgwUwgwUogwUggwU8gwI?2w:41w?Y8c?9Y1:ggUgxw963xy30Qgec0be2wUogMUgggU8gMI0b:3060,Axg?xMU;113x260Acd1ACf0UU4zgmc1Ec70O462wM7248b:9:606?34AM?tw:113x260Aoe68c3h0UM0Coe64ce444e22w;281w?79g?3o1:ggUgxw963xy30Qgeg0bi2wUogMUgggU8hMI0e:bg6;MBg?kw4;123x2f0A8e68U3ggUwxwh13yy31kges74a3yx33y113xx23x123wx52M?c:f060,kBw?5w4;123x2e0A4e68o3ggUwwMh43z1H2wUwgMUoggUggwU8hMI?3]A>0.9s?6E3:gwUgzw913xy60Q4e88c4h0UM0O022wUwgMUoggUggwU8gwIo:m0s?7Oq?21.;4ge40dY.U8-4r0PK8@f/8w;9gw?2A@f/R280,PV/_48M?ifD/MgB0,I@v/B34?bPV/@kmw?9fH/Shr0,M@L/B5Q?c3W/YQnM?3fL/UhC;Y@/_R74?ajX/@QsM?ZfL/MhQ;k_f/l7g?3jY/@kt;lfP/@hQ0,Q_f/x7w?bPY/_ku;TfP/OhV?3Y_f/V7A?2zZ/YQuw?ifT/OhZ?2k_v/t7Q?bjZ/YAvw?WfT/@h@;c_L/F8;43@/@4ww?zfX/Oi4?2U_L/J98?ez@/YQAM0<f/_Tik;Y//R9k?7z//QBw?Hf/_Siq?3w//~!}v,U07g0s,I06w0p,w05M0m,k05?j,8<g.?Y03w0d?M02M0a?A02?7?o,g<?c?w,]vY3_Mn_1_Y9_ML_3vYf_M7_0_Y5_Mv_2vYb_MT_3_Y1_Mf_1vY7_MD_2_Yd_M/0vY3_Mn_1_Y9_ML_3vYf/Y0_Mb_1fY6_Mz_2LYc_MX_0fY2_Mj_1LY8_MH_3fYe_M3_0LY4_Mr_2fYa_MP_3LY0_Mb_1fY6_Mz_2LYc_MU1^bShBtyZPq6QLpCZOqT9RryZQrn0LpCZOqT9RryVom5w%3MUd30Ia2gw71wk40M81?Ye3gMb2wA8>o510c2.1OqmVDnShBsThOrTA0sCBKpRZTrT9Hpn8wmSBKoTNApmdt85J6h5Q0hlp6h5ZiikV7nQh1l440sCBKpRZFrChBu6lO02QJoDBQpncJrm5Ufg1OqmVDnSpxr6NLtRZMq7BP<lmhAhvkABehRZ9jAt5kRhvh45kgg1OqmVDnSpzrDhI<hBsThOrTAwsCBKpM1KgDBQpnddonw0sCBKpRZTrT9Hpn80sCBKpRZFrCtBsTg09ncK9mNR07tOqnhBa6pAnTdMontKb20yu5NK8yMwcyA0p6lz079FrCtvomdH83N6h3Uwf4p4nQZll3U0sCBKpRZIqndQ85Jmgl9t03?tT9Ft6kEpnpCp5ZAonhxb20CrSVBb20Uag0JbntLsCJBsDcJrm5Ufg16jR9bkBlenQpfkAd5nQp1j4N2gkdb02ZQrn?mClOrORzrT1V86BKpSlPt,OqmVDnSRBrmpAnSdOpm5Qpi0YlA5ifw1OqmVDnTdMr6Bzpg1ipmZOp6lO86ZRt71Rt,OqmVDnSdLs7A0biRyunhBsPQ0sCBKpRZPpm5I07wa02QJt6BJpmZRt3Q0hAhvjR94hl9vk4Bghg1TsCBQpixBtCpAnShxt64I9DoIe2A0sCBKpRZPqmtKomM0sSxRt6hLtSVvsDs0sT1IqmdB86pxqmNBp3Ew9nc0biRyunhBsP0Z02ZApnoLsSxJ05dBomMwrmlJpCg09ncW86VLt21xry1xsD9xug1JpmRCp5ZzsClxt6kwpC5Fr6lAey0BsM1jpmlH86pA05dMr6Bzpi1Aonhx051EundFoS5I86pxr6NLtM0JbmNFrClPbmRxu3Q0biRIqmVBsPQ0kAlgj5A0sCBKpRZIqndQ079FrCtvrmlJpChvoT9BonhB07tOqnhBa6pAb20CtC5Ib20Uag1OqmVDnT1Fs6k0s6BMpi1ComBIpmgW82lP02QJrTlQfg1OqmVDnSdLs7Awf4Zll3Uwf4Befw1zr6ZPpg1jhklbnRd5l,TsCBQpixBtCpAnSlLpyMw9ClLpBZPqmsI83wF06NPpmlH06RBrmpA<pFr6kwoSZKt79Lr,OqmVDnSpzrDhI83N6h3Uwf6dJp3U0rmRxs3Ew9nc0rBtLsCJBsDc0kABehRZ9jAt5kRhvh4Bmildfkw1OqmVDnSBKqngwmQpcgktjng1iikV7nQ91l4d8nRdcjRhj<NFsTgwr6Zxp65yr6lP06VnrT9Hpn9Pjm5U<dOpm5Qpi>qn1B07lKqSVLtSUwoSZJrm5Kp3Ew9nc0sCBKpRZMqn1B83N1kB9YkAg@85JnkBQ0hAZiiR9ljBZ4hk9lhM13r65Fri1yonhzq,OqmVDnSZOp6lO83N6h3Uwf516m7NJpmRCp3U0sCBKpRZCpnhzq6lO059Rry1PoS5KrClO079FrCtvsSdxrCVBsy0YpCg@85JPs65TrBZCp5Q0hlp6h5ZiikV7nRdkgl9mhg1Pq7lQp6ZTrBZO05tLsCJBsy1zrSVQsCZI02lItgE09mg0hlp6h5ZiikV7nQBehQljl5Z5jQo0t79Rpg1crStFoS5I86pxr6NLtM1IsSlBqO0YhAg@83NfhAo@byUK02QJr6BKpncMfg1CrT9HsDlKnSBKs7lQ079FrCtvqmVFt,TsCBQpixCp5ZPs65TryMwsS9RpyMwsSNBryA0jBldgi16pnhzq6lO06hOug1jqmtKomMwpnpBrDhCp,Pq7lQp6ZTrBZT06pxqmNBp21QrO1zsClxt6kwon9OonAW82lP079FrCtvpC5Ir6ZT02QJtSZOqSlOsPQ0sCBKpRZPoS5KrClO06pLsCJOtmVvsCBKpOVz05d5hkJvhkV4079FrCtvoSNBomVRs5ZTomBQpn80kSBDrC5I86BKpSlPt,elkR184BKp6lUpn80biRIqmRFt3Q0sCBKpRZPpm5I83N6h3U0biROpnhRsCUJoDBQpnc.SNBomVRs21TomBQpn8.l97nQR1m?JbmtOpmlAug0Br6NA2w1OqmVDnTdFpSVxr20YhAg@079FrCtvrT9Apn80hlp6h5ZiikV7nQlfhw0Br6NA079FrCtvomdH<5zqO1yonhzq,CrT9HsDlKnSZRt?JbntLsCJBsDcMfg1OqmVDnSdIomBJ85Jmgl9t85J6h5Q.T9BonhB86RBrmpA079FrCtvoSNxqmQ0pCZOqT9Rry1rh4l2lktt84lKom9Ipmga0599jAtvgA5kgQxvikho06VcqmVBsQRxu,TsCBQpixCp5ZIrSdxr5ZPqmsI82pLrCkI83wF02QJt6BJpmZRt,9rCBQqm5IqnFB879FrCswtSBQq21zrSVCqms0qmVz:tT9Ft6kEpChvpSNLoC5InS5zqOMw9D>b21PqnFBrSoEs70Fag;7tOqnhBa6pAnT1Fs6kI82pLs2MwsSBWpmZCa6ZMaiA0qmVSomNFp21KtmRBsCBz86BKp6lU86pLsy1FrChBu6lA865OsC5Vey0BsM}pCZOqT9Rry1rh4l2lktt82lPeylAey0BsO1ComBIpmgW82lP2w;6pLsCJOtmUwmQh5gBl7ni1OqmVDnSdIomBJ86NPpmlH86pxqmNBp3Ew9nca]6pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME;1TsCBQpixBtCpAnSBKpSlPt5ZAonhxb20CtyMwe2A?7tOqnhBa6pAnThxsCtBt2Mw9CBMb21PqnFBrSoEqn0Fag{1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ{LsTBPbShBtCBzpncLsTBPt6lJbSdMtiZzs7kMbSdxoSxBbSBKp6lUcOZPqnFB0,TsCBQpixCp5ZComNIrTsI82pFs2MwsSBWpmZCa6BMaiA+pCZOqT9Rry1rh4l2lktt879FrCtvomdH86NPpmlH86pxqmNBp3Ew9nca*1OqmVDnSpxr6NLtO0Yk4BghjUwf4p9j4k@85JAsDBt0fcf7LF8w@M8i8f42cc;3P3NXWi8fI24yb1k6i0,8xs1Q0L_gi8f42cc}fcf7LF1k_YRnaI?fYBnGI?cPcPcPcPcPcPcPcPcPcgrI]_OlcGM?PcPcP46X.;fYBhaI?cPcPcN1KM8;3_9jOH?3cPcPcgrI3:_OkQGM?PcPcP46X1:fYBbaI?cPcPcN1KMk;3_9iiH?3cPcPcgrI6:_OksGM?PcPcP46X>;fYB5aI?cPcPcN1KMw;3_9gOH?3cPcPcgrI9:_Ok4GM?PcPcP46X2w;fYB_aE?cPcPcN1KMI;3_9viG?3cPcPcgrIc:_OnIGw?PcPcP46X3g;fYBVaE?cPcPcN1KMU;3_9tOG?3cPcPcgrIf:_OnkGw?PcPcP46X4:fYBPaE?cPcPcN1KN4;3_9siG?3cPcPcgrIi:_OmYGw?PcPcP46X4M;fYBJaE?cPcPcN1KNg;3_9qOG?3cPcPcgrIl:_OmAGw?PcPcP46X5w;fYBDaE?cPcPcN1KNs;3_9piG?3cPcPcgrIo:_OmcGw?PcPcP46X6g;fYBxaE?cPcPcN1KNE;3_9nOG?3cPcPcgrIr:_OlQGw?PcPcP46X7:fYBraE?cPcPcN1KNQ;3_9miG?3cPcPcgrIu:_OlsGw?PcPcP46X7M;fYBlaE?cPcPcN1KO:3_9kOG?3cPcPcgrIx:_Ol4Gw?PcPcP46X8w;fYBfaE?cPcPcN1KOc;3_9jiG?3cPcPcgrIA:_OkIGw?PcPcP46X9g;fYB9aE?cPcPcN1KOo;3_9hOG?3cPcPcgrID:_OkkGw?PcPcP46Xa:fYB3aE?cPcPcN1KOA;3_9giG?3cPcPcgrIG:_OnYGg?PcPcP46XaM;fYBZaA?cPcPcN1KOM;3_9uOF?3cPcPcgrIJ:_OnAGg?PcPcP46Xbw;fYBTaA?cPcPcN1KOY;3_9tiF?3cPcPcgrIM:_OncGg?PcPcP46Xcg;fYBNaA?cPcPcN1KP8;3_9rOF?3cPcPcgrIP:_OmQGg?PcPcP46Xd:fYBHaA?cPcPcN1KPk;3_9qiF?3cPcPcgrIS:_OmsGg?PcPcP46XdM;fYBBaA?cPcPcN1KPw;3_9oOF?3cPcPcgrIV:_Om4Gg?PcPcP46Xew;fYBvaA?cPcPcN1KPI;3_9niF?3cPcPcgrIY:_OlIGg?PcPcP46Xfg;fYBpaA?cPcPcP_9gaf?3cP-0i8QZkqA0<yd1kGF0,8evxQ5kyb1gWe0,8xs1Q2v_w3N@}ccf7U}i8QZ8qA0<yddhGF0,8avV8yv18MuU_ic7U0Qw1NAzh_Dgki8I5RoQ0<y5M7g8_@1C3NZ4?333N@}fcf7LG0ftSE:tiJli8cZsEU;18yulQ34ydfoWb?3Emv/_@xA//NwmRG:lT33NY0MMYvw]3P3NXWWnv//cPcPcPcPci8n_3Ug70w0.lp1lk5kioDQLBI;1lkQy9@Qy3X23EW_T/Qy9Nky5M7gfi8DvWeLY/@0v0f_nngsi8f484O9VAy9TP7imRR1n45tglXF@_H/MYv<C9XAy3Ng59atV9znU1WfnW/Z8ytVcyv99ysl8ysvEZfT/Qf6h3k0<y9X@ym_f/i8Rg_Qy9NQy912h8ylgA2ez1@L/i8Jk90x8yuV8yst8ysfELLT/Qyb32hcyu_6h0L_0ext_f/i8RU0uyk@L/j8DKi8D7W4DX/Z8ytZ8ysnEfLP/Qydu07EtvH/Qy9TAy9N@wG@/_j8DDioD6W1_Y/Z8znw1W5rW/Zcyup8ysvE2_L/QO9XQC9Nexg@L/i8DvW4zW/Z8yu_EkfH/Qy5M0@4TM;8Jgafr2g7lvw@843UiK:ict491w]W4zZ/Z8zngA6bEa:j8DTNM}i8D3WeTX/Z8ysp8yQgA64AVNDhww3w0tlK3eO9Qlz79j8Dyi8DLWfDV/_H6MYvw]15cs1cyu5cyv98yuV8ysvEXfD/Qy9X@yQ@v/j8DTWaPV/Z8wYgwj8DDmRR1n45tglXFCfD/MYvx[j8DSi8QZfKv/P70Wb_V/_HMgYvh;i8DKi8QZ_K7/P70WavV/_HGgYvh;MMYvw]18yu_EEfD/Qy9XAydfu3A/Z8xs0fxgr//HPSpCbwYvx[kX_2:i8fIgewh@L/i8n0vwN8wYh0mYdC3NZ40,8zjTFV/_cvoNMexg@L/ysu5M7wFKxY;18zngA88B490PEJ_H/UJY90N8yggAWaHX/Z8yNgAi8nivO6_LM;eyT@v/i8n0vBF8wYh0ic7w0RL33N@4}36h1gw<ydt2goKwE;18znMA8exD@v/i8Jk91wfJxa3UJ@0@AJQfQy9Mkz1Uhi0@AR83Qj1i8n0tafFk//MYvw]2_Mw;exe@v/i8n0vVuU0,?eAP//3N@}4z1U0HHOmqgkQy9@QydfsXv/Z8w@NgW8PU/Z8xs1QlU0Ucnliw7w107lcKE,?2@ww11<ydfovw/YNMexk@v/ysa5M7AuKE,?2@ww11<ydfpTv/YNMewS@v/ysa5M7xoi8f4k8DgmYcf7Ug}bE2:i8DuLPY1;NMewc@/_ysa5M7DmWe7W/@3e1pRA37ii8DuLPY1;NMezH@L/ysa5M0@8tv/_@KL3N@}cnVrMmwTv/i8RY9118K2Vom5xom5w0i8BY90x8ykgA8cnVvQgA4ezs@f/i8JY90y5M8D2u1C9l2g8WazU/@bl2g8Wl//Yf7U}NvBL1m3t/_7h2gwm5xo0cnVvQgA4eyt@f/i8JY90y5M8D2us7Fbv/_SqgpCoK3N@4}11lQ5mgll9yvl1l5lji87Ii.?8AY94ydfjvx/_Efvv/Qy5M0@47<?80Ucg@4WM40<yddsTx/Z8ysvETfD/Un03UnY:i8I5roA?bEo:Lw4;18zjShU/_NMnqEM;g;4yb2eyq@v/j8IZMWc0<S5_M@5T:4kNOj7_grz//_Ki4;2W0M;bU<a?WeLT/Z8w_z_3Uip2w?cvqW,2w<y9NQy91o2z?3E@_z/XZk:W27T/Z8zjQXUf/i8D3W8bS/Z8xs1Q6rEa:cvp8ysvE_Lv/Qy9h2g8i8n0vN98xtJ1L<;1c3Q_zj8BA90x8zjSJT/_W4rS/Z8xs0fx0Q1;NZHEa:i8D7WbXT/Z8xs0fzLk;18ykgA4eDQ:3NY0j8IZYq8?cs5XW8[1dxvYfx2j/_Z9NMs]i8I5Qa80<z7w0,{i8I5LG8?cq06<;18yMmMEw?ict<]18yMmxEw?ict08]18yMmiEw?NA0E<yb1ouy0,8NQ0M]4yb1nyy?36g2A0i8I5rq8?8IZ3Vw0<z7w0.8[xvZV7z70i874i.?5JtglN1nk5ugl_33NZ?8IZUFs?bE,;i8RQ943EK_r/Qy5M7_CWYMf7Q?w7w1?@48LX/@A6_L/A4z7h2gg.;4ydftTx/_E6_n/Qy5M7gucvqW2w;4y9N@ynZL/i8n0vwF8ykgA6eIc3NY0ict491w<;LXY;3Etvn/Qy5M0@er0w0<Odd419MuU2cv_Envn/Qy9MQy5M0@eQgw0<yb1ha70,8yOx8yTQ0i8n_3UiJ0w?hj7A3N@}ezHZv/i8JZ24y3Ngxdzmg40ky5_TnFLg1w0,ceucfzTI20,8zjQkS/_W6_Q/Z8ysd8xs0fxec7?20e4MfxhE2?20u<O3Ukg0w?w7w2?@51w80<yb7h@x0,8yQgA24y9wOw10,8yQgA44z7wP,;1:i8C38<0<ybh2goj8CPk<0<y9wPw1?2b12h8NUd0.[4z7wRw1{NEdw.;cq3oM4;23@<fzBA80,8NQgA2f//Zdzmk8w@w2ics49f//ZdzmP544O9Vmof7Ug}4ybng2W3w;4yddsHq/Z8yt_EOfr/Un03UiU.?KwI;18zjnvT/_i8DvWaPS/@5M0@4p0k?bEa:i8QROtX/Qy9T@ygZL/xs0fx7w5?2W3:4yddsDr/Z8yt_Etfr/Un03Uik1g?KwA;18zjk1TL/i8DvW5zS/@5M0@4G0k?bE8:i8QRDJL/Qy9T@wYZL/xs0fx4g6?2W3:4yddkPp/Z8yt_E8fr/Un03Uio1w?KwA;18zjnKSL/i8DvW0jS/@5M0@4l0k?bE8:i8QRoZH/Qy9T@zEZv/xs0fx407?2W2:4yddmju/Z8yt_EPfn/Un03Ug@>?KwE;18zjl1SL/i8DvWb3R/@5M0@4Nwo?bE8:i8QRqJX/Qy9T@ykZv/xs0fxiA70,8yMkRDM?icu0m<[3FBg:Yvh;i8QRbZX/Qy9TQC9XKzKZf/xs0fxe3Z/@W2w;37Si8DvWcvP/YNQAy5M4wfit19ytrFMfT/Sof7Qg0<MFUQy9S4z1U0h8atx8Mvw4i8Q4g4z1W098ysnFpfT/MYvw}NZAyduMWW2w;exoY/_i8n0vxd8yNmsDw?i8C2a<;Yvh;i8f524AVXg@5Y_T/Qyb12h8yNRUDw?i8n03UiD1;3UB11;i8dY90w03UUR1;NEdw.;sq3oM4;5cyTgA24O9IP,;NXkO9IPw10,cyrd8.?3NY0ioIY9bE9:i8QR9dX/@xHZf/xs0fBc19wYg82sldeulRSQ24Xnkbicu3m<?f//Z8yUIw.?i8Kja<?cq3ow4;4fJEdw.?i3Dh3Vi3og4?8j03UjQ0M?icu32<;4:N_XU120w0W0rP/YN_XU120w0ygl9AM?WfjO/YN_XU020w0ygkPAM?WebO/YN_XU120w0ygktAM?Wd3O/YN_XU020w0ygk7AM?WbXO/Z8zjQfAM?ygnNAw?W8PP/@5M0@8l08?8IZZF8?bE02;Lwg:NMexJYL/yPTzAw?Kw08;NMbU4:W5rO/@bfsyi?2W.;370Lw8;3Ef_b/UIZJp8?bE1:cs2@0w;ewEYL/yPSuAw?Kw0<?NMbU71;W17O/@b3nKi?2@8:370i8QlvJH/Qydv2gwW4fM/YNQAydt2gwi8QZ3tr/@xgX/_yMR6Aw?Ly]NM4yd5kTq/Z8znMA8ewiYf/ct98zngA84ydfsTr/_E7@/_UId4p8?bUw:cs18zhksSL/i8RY923EUu/_P7ii8RQ9218zjTBRv/WeXK/@b3tOh?2@8:370i8QlWZD/Qydv2gwWb3L/YNQAydt2gwi8QZRJD/@yZXL/yMSDAg?Ly]NM4yd5rHp/Z8znMA8ex_X/_ct98zngA84ydfnbp/_EzeX/QS5_M@4y_D/QO9_@yHXL/ioD4i8n03UgA0M?ZA0E10@44wc0<yb1rWr0,8yXwE.?ic7D0KxuXL/ioD5i8I5F9I0<y3K2w1:3Ujm0w?ctJ8zmMAgeJa3NZ40,1ykit08D1i8QlaZD/P70Ly:18yu_EW@X/Qy9Tz79i8DGj8DDi8f30uy7XL/i8I5k9I0<wXC2w1;fwUc20,8zjSHSL/WbvR/@5M7CHxtJQ84xzSQO9XkCdn9Q03NZ?8JZ<y3NgjEFf3/QwVWTnLj8DLWcvJ/Yf7U}K<;3FEfz/Sof7Qg?37Si8RX2XEa:W93L/Z8xs0fzAvY/Z8yNngCw?i8C28<?eAQ_f/3NZ?37Si8RX2HEa:W63L/Z8xs0fzxvY/ZyYLQ8vc18yMmqCw?NvB_w2,?3F_vL/MYvh;cvp8znIcKwE;3Eae/_Qy5M0@eT_L/Qyb5myq0,8yo8U.?WsPX/Yf7Q?cvp8znI9KwE;3E@eX/Qy5M0@eH_L/Qyb5jyq0,8yo8M.?WpPX/Yf7Q?i8K38<0<ObIP,0,8ykgA44ybwOw10,8ykgA24ybwPw10,8ykgA64ybj2g8NEdw.;4wVj2gg3Vi3og40<MXt2go3Vi3ow40<O9IMw1?3F2_P/MYvh;NEdw.;sq3oM4;58wTMA2?fzCjX/_FmLL/Sof7Ug}4yduMyW2w;37SW63K/Z8yggAi8n03UXP@L/oLbZ27P0i8I5tFA?cnVvU0M.?WtDW/ZC3N@4}19euVc3QvRWiXU/Yf7Q?LY8;3EZKP/Qy5M0@fwvv/Q6@;60eB@Z/_pF0NZAyduMOW2w;ezgXv/i8n03UW7@L/oLbZ27P0i8I52FA?cnWvU18.?WmTW/Yf7Qg?ezzXL/yPzEneX/QydflXl/Z8ysoNMezrW/_WtrZ/ZC3NZ4?2Z;o0eBHZ/_pwYvh;j8DLW7zH/_Fm_r/QO9_@zHW/_j8D_WbfH/Z9ysh8xs0fxtbY/_FALT/Qyb3oKo0,8znIaKwE:NZAy9j2ggW4rJ/Z8yQMA44y9wlw1?3FRvD/MYvh;grU1:Wlz@/Yf7Qg0<yduMyW2w;37SW13J/Z8ykgA2eCC@v/KwE;18znI8cvrEZKP/Qyb5h@o0,8yo90.?WofV/@W3w;4yddv_m/Z8yt_Ej@X/Un0thd8yMnQBM?NE1z.;uBo@v/Kwo;18zjnuQ/_i8DvW2jK/@5M7k9j8RX1KAT@v/w3IJj0Z5@@AH@v/pCoK3N@4}23_M4fzHsd0,1lXEa:glp1lk5klky9Zle9@Qy1X7w10,8yTU8cvrEcuP/UB491O3@M8fxro5?36x2g0.;cu49eg;3//_i8I5mFs0<ybC3,0,8yUwE.?i8Bs93x8yVwU.?i8Cc9b:18ypMA@:4ybC2,0,8ylMAm4ybC5,0,8ylMAk4ybC4,0,8ylMAo4ybC5w10,8ypMAY]@SC6,?28D2ij:3Xqoow4?8ys9.1;fJFxx.?3Xq0oM4?8y490s10,8w_A13Upd7;K3Y:NOvd83XSc9b:29MyDai8Kc9fw;18oZ98w_A13Ur_7g?YQwfLsAFO4yoi8C490w10,80t18yogAW:bw_:csDPi0@Zz2jE:asx8C4wfHY98yst8xs2U.;4wfhst8yogAW:4z71jCm{ics59Fo[3EMu/_XU?2?ic7E0Qw5/Yv<wB?3w_Qy9Mrw:2i3D1i0Z6Mky9NXw?2?i3D7i0Z3NQydL2go.?i8D2i8B4933E2uP/QObJ2go.?xs0fxrwq?2bv2gsKw4:NZAOdL2gM.?Wa7F/ZcyvW_1w;4O9v2h0i8B490zEqKD/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9h2hUi8I5rFk0<z7w0,{i8I5n9k0<z7}18yMleBg?ict0c]18yMk_Bg?i8Jc95x8ykw8i8n9t0W0L2g0.:@5bh40<y3v2hg<S9ZM@Sx2ij:NAgAs?fBogAUM;8jrj8DP3Vi490k1;ax2g4.?y8gAUw;4ybh2g8icu49cw+i8B494x8NQgAa]18NUgAw+18NUgAK+18NUgAy+18NUgAC+18NUgAG+18NQgAq]37x2ik+ct491}3Vi490o1;NXkMV@Q4fAYkNOkgar2hM3Umz7g?wbMAAM]fxeA;18yQgAo4ydsfZ8eTgAa0@2BME0<gfJCgA44S9@Aybh2gUiiDqgofA0k63Z059es8fwW420,dxt8fx7w20,8yPk1B;wTMA4<fx1oa?2bhxy5M7gLi8eY9f}3Ug02w?vxV8wXMAO}fxsQi;f7Q?pCoK3N@4}18yTMA24y9S4C9P4MFY4Odb3ybv2gsct9cyuXEwev/Qybl2gMyTMA74O9ZKwvWf/i8n03UWx2w?j8BI90xcyu5dzjM6j8DPNQgA4]15cuS0L2ij}@55//Qybh2gUi3D13UcU2;i2D8ioD0i8J49618zn3_i8n03Ukm.?h8xI971cevIfwWcy0,8NYr//_grQ8:j2JI94xc0SMA24O9t2gwioDshj7Sj8DHi8Cc9a:18yrgAM]@SH2jz:joD5WOAf7Ug}4y3M059wYo1ioD4i8f324QVXw@3u0s0<MV@0@3rMs0<O9@HUa:j8DDj2DyWcPD/Z8xs0fx7c80,dxvofBs908eFQK4ybv2gwi8f?ky9NAwF_Aw1TAwVt2hgsWd8yUMAE:4O9UQS9Z4ybJ2j]j05A92y9RkC9_AM1UkMV@Q4fAIkf7Qg0<wXt2gEsRV8xsAfxlgb0,5xeRQsct491,:i8dY93w03UhV2;j8J493x8yQgAo4wHh2gEijD0j0Z7M4y5M0@5e0w0<MV@Qi8r2hMNQgA4<;113Vb5cuR8eTgAa7ay3Xp49123U069MEfO0k49Rky5Og@5zwA?379hojJtkJ8ykMA44C9TeBJ0M?i8JZ4bEa:cvrEnKr/UC49eg;3TQc7E7UC490,?3FdvH/Sof7Qg0<MV@Q4fAIl52ekfxeg7?23v2gg.@48fT/@CM_v/j8Qs0Qybdmmh0,9ys98NUgAO+1devIfAEgAE:4MFYQw3n2g8j8Bk921cylMAs4M1Q@I_3NZ0<ybty18yMktAg?i8Il3F40<y9MkwFYky1@v/3M0fxJI;18es9O9HZA:W9PB/Z8yPnRA;3Xp6a8j0trR8yPrHL0Yvx[i8I5Sp;4ybk0x8yNn6A;i8Cg0<0<yb1ryg0,8ygmFA;i8I5IF;8J068n0tal8yTgAg8IZg8o?bE8:icu493,;1:W8HC/Z8w_z_3UlW//yMm2A;xs0fx6P//Enur/UIUWdrB/ZczglhO/_KlI20,8zhnIPL/ioD1i8I5Onk0<ydduHg/Z8yPwNMex8Vv/WiT/_Yf7M18zkw1j8Jk921cyRMAs4y9PQybdhyg?21V/_3M18wTMAe<fx3U50,cyQgAi4y9DfU<2?ig@WW3YB/Yf<O9xco<2?i8AdS8Y0<wVOw@2dMk0<ybx2iE:j05k94xcytJ42GgAE:4y3h2gE0ky9x2jg:i8K499w;14yagAE:4y9x2j]i8J495x4y6MAs4y9x2jo:i8J497x8ykgA84y3h2hE0kybj2hEi8e498]1h8JC64ybL2i8:j8J495x9zkgU1AzhXQzhW4m5V4wfhct8QqMAK:4y9x2i8:wbMAUw:1RgkGd18k]Kwg;2bL2ik:i3Dgi0Z2MEn_3UmV1;i3D1K]183Qb1i8B496wfAY0fJI29x2ik:i8JQ942_1w;eysUL/K0c;34ULLTB2gU.?ibzfZRfzFpL484zTUAxFz2gM.0.48f<z1Wwh8zgghi8B497x8aQgA84wZy1c;@75w80<ybj2hoi3Cc98]fwMc20,8yQgA84y9h2hUwbMAE}fxgbW/Z9ytO0L2ij}@5Mgg0<z7h2gg]4ybn2ggj8DDjjDYswTHamqgi8RU0kMV_Tcpj8DWLwE;18wYc1i2DWW4fz/Z8xs1RTAy9n2ggj8I50EU0<yb3gee0,cyst9eswfwEYa?2bx2jA:xs0fyvwj0,cySgAi4y9ftOd0,caSgA24MXp2gM3UeR5w?jg7Qict495w1:i8J493x8xs1QbAy3@fRTa4y3M08NQLd83XTgK44:FQbE_:i9zPi0@ZM2D2i6f2i8B495x8yMm9zg?i8BUc4y3v2gg?@4U0c0<ybh2gUct8NXkzTt2hoi8B4961C3NZ40,8yRMA44ybv2gUct98ytV8yvx8auV83W_6ifvPi3JY95wfwZAf0,8xs2_.;4wfhvx8yngAk4kNXky9v2gwWPlC3NZ40,cyvFcaua@2w;4O9V@wBUL/i8n03Uis3;iof50kOdo05ceSMA80@3SgM0<Gdn2Q0i3Js910fw@Ac0,devNOL4S9UoJY9>NQAQFYkM3j2g8j8Dej8Bc92zEBK3/Qybl2gMyTMA74O9ZKwRUv/i8n03UWI3;j8Jc92x8ys9dzjM6joDQj8Bc90zFsv/_MYv<ybdnCc0,8yQogi8JY95x8yogAC:4yb1l6c0,8yogAG:4wXL2iM:3Ufb:wbMA1g4:fxbQ;18yMp8yNkHz;i2D2wbMA1<:fxbw7?23L2ik]g@lMkm5V0@kM8j13Uix:Kg4;18etsfwVc;18yXMAI:4ybt2hoi8DUj8QA3AwFY4MVVQwfgIxc3QbDi8n9t5i0L2g0.;7hai8JY9418zhlGOv/LA]NMewOT/_i8JQ942bL2jA:i6fgW9Xx/Z8w_z_3UjL5w?i8I5zoI0<O9o0xcymgAm0Yvg023L2ik]DkewbMA1w4:fxnA80,8NUgAw+3FTLP/MYvw]18yUMAE:4O9UQS9Z4M1p2gEj8JQ9218yXgAM:4M1UkMV@44fAIkNXuDf@f/3N@}4ybh2hwi8n03Ulo.?icv6//_Q24Xg@5fxA?8J49114y6MAs8D2w@,w@81i8fO0kC9Q4MV@M@3RM;8j03UiKZ/_WsE:f7Q?i8Cs_w.8,8wTMAi?fysTW/ZcyQgAieCS@L/pyUf7Ug}4ybhwybvxy5_M@4FM80<yb1oaa0,8yoo0.?i8I5t8E0<y91mma0,8yMlKyw?yQ0oxs0fxsI80,8yPlsyw?Wo3W/Yf7U}wXMAB]4fxc8h?37x2ik]w;eB7@/_pF1cyud8yUMAE:4S9Z4ybJ2j]j8JQ9223v2gg.@4TMY0<M1p2gEj07xj3DXgg@iNj7JWqjT/Yf7Q?K<;33pyUf7Ug}cq49a}joDXWonU/Zdxs0fBc10wfQ1t0y4M0@5MLX/Qi8r2hMWt3@/Z8zn3_i8J49615cs18aQgAaeCbZ/_ioDsj8Dyj2DOi0dk90x8yMl_yg?i8Idw8A0<wfKKE_i8D6i8f?o7C/Yf<y91l@90,8ypjN,0w<y9wg,0,8yMlhyg?NA0F0kyb1kq9?2bg1y5M0@5b0U?8K49eg;25M0@9m.0<ybt2h0yPSZvw?Kww;18NUgAc<?3Z23M3E2Z/_Qy3@fYfx64d0,cyvvEOtP/Qy1N7w1;NM5JtglN1nk5ugl_3yMlTvw?cta@.;4z7x2gC.[6q9B2gK.?Kg4:NQEC492,?2b1kh@0,CyrgAb<?bU2:yogAa<0<ydx2gw.?i8D7pECc92g10,8ykgA8ezvTf/xs1@3Lq492U1;13UnT>?i8I5pEw;@Sw1w1?24M0@4AMU?ct491,:j8Dxhj7JWu_P/Z8yPkZy;yRooi3Jc93x13Vf4ggD4hoDwggzE3Und5M?xt9Q94ybH2jM:i8nJ3Ujf4w?vx5cyWgAO:4S5V0@5jN80<m4Xg@49Lr/P7JWiHQ/Z8xs2_.;4C9O4wfhvx8yMpczgOZ]4AFM4Cd13B80s19es0fwYo40,8zgg_j3D0sO18ysx9Qux8at1ces193Qv0ioDUiiD0ig78i3D7igZ2O4wVOw@3Jfv/Qy9zw,0,8ygRJxM?i8I5tEs?8J068n03Ug8_v/i8JQ942bfg1Z?2W2:4O9n2hMj8Bk9218NUgAc<;4;3EgdT/QObl2gwj8Js9718w_z_3Un9_f/yNQKxM?xtIfxbLY/_E2tT/UIUW8bs/ZczgnZMv/KmU20,9ys58yMlYr;i8IUWsU50,cyvJ5cuQNXkybdum6?2bhxxcySgAi4i8H2iw:i8K49aw;37h2gg.;4y9x2jg:i8K499w;18yogAM:4ybh2hoi8C49dw;18yQgAu4y9h2gwi8DoioDdj2DMi0d490x8ykgAieIVA4ybjy18yMlJxw?i8D2i2Dai87W/Yf?@6Uw;4wV1kK60,O8rZA:We_q/Z8yPl8xw?3Xp6a8j0ts18yMXHLMYv<yb1j660,8yR08i8Il7Eo0<y9A0,0,8yMkgxw?i8A50oo0<yb1gG6?2bg1y5M7iGi8JQ942bfpxX?2W2:4z7x2gM.;g;ezyS/_i8fU_M@5v//Qib5tC50,5xt8fx6//_EIZL/UIUW2Pr/ZczgmDMf/KlI20,8zhl2Nf/ioD1i8I57SI0<yddk36/Z8yPwNMeyuSL/Wj3/_ZC3N@4}18ys98yPlSxg?i8f?o7y/Yf<MXr2gU3Ui70M?pAi9H5o<;ig@WX3@0L2g7.:@5DwU0<O9Fdo<2?i3A59Ek0<y91iu50,8NUgAO-fwW3R/Z8yRo8yQUoxsAfx9we0,8yMn_x;i8C60<0<yb1v640,8ygnyx;i8I5WUg?8J068n03UmG4w?i8IRSog?eBnZv/Kw8;18zjmuL/_ysvEMtH/Qy3@fYfxoLX/@b3rC4?25Og@4vvL/@ykSL/yPzE3tH/QOd1n@@/@Vj.0<yd5if3/Z9ys58yMk0qw?i8QR8sn/Qybe370W7_p/_FfLL/Qybx2io:i2K49c]fx5M20,8yXgAG:4wHJ2jg:i3DUsxcNQAzTZP7ii8D1i8DMifvNi8D6i3BQ95wfwW7U/Z8NUgAw+23L2ik]g@4zLn/Qybh2hoi8R80kzhWuDXZ/_i8QlCY7/XV]j8D_cs3Eodv/Qybt2h0yXMAV:4xzQezcSv/i8fU_M@5D@X/UIZN8c?8n_3UihXL/W9_p/@beewoSv/j8Q5Jc7/XD50w?i8QlbIb/QC9Mkyb1gJF0,8zjkINf/i8IUcs3EyJz/@BiXL/3NZ40,8yPlFwM?i8Jk911cys1C3NZ40,CpyUf7Ug}4C9Mky3M051wu7/MY0hw@Tz4U<;j07ai3D1tu54yVMAV:4y9l2gghonr3UAG2g?ibH////_vQy9@2n/MY0i2ekNw.8,8ylgAieA7Zv/j2D9WlLX/Z8yPnEww?Kw4;18yMV8yMn9ww?i2D8u2kNQAybz2jU:iftQ95x8esx83Qv1i8D2i8n0K<;183Qjgi3Bk93wfwDgf0,8eRgAe0@3QwM0<ybL2i8:i8Kc9bw;18NUgAw+18yUgAS:cu499g:2:i8f?QwVPQwfhIZ8es4fwJTP/Z8yQgAe4yd312U.;4zhWkwfhcx8ykMAe4y9OAzTSAyb1iu20,8yoog.?i8I58o80<y9A0w10,8NUgAK+18NUgAy+3Fxff/MYvh;i8DUic7w0AwVQ0@3qfr/Qm5V0@5n_r/@CV_v/3Xtc93xCyoNm,;82Y90s1:3UhW_f/i8JY94x8ys61Uv/3M18yrPe,0w<S5V0@9o_P/@Bm_f/3NY0i8JQ942bfiRT?2W2:4O9n2hMj8Bk9218NUgAc<;4;3Ertv/QObl2gwj8Js9718w_z_3UnSZL/yMlrwg?xs0fxezS/_EdJv/UIUWa_m/ZczgkGLf/KlI20,9ys58yMmFpw?i8IUi8QlKb/_Qydds31/YNMewxRL/j8Js971cyRgA8eCvZL/i8JQ942_1w;4y9j2hMj8Bk923EGtj/Xw3:j8Jk9234ULLTB2gU.?ibzfZRfzFpL484ybj2hMi6CQ93,0,.wY0ifvyic7G14yd11p8aUgAO:4wXx2jM:3UbpXf/NEgAE]18yPmaw;joDXicu49cw+WiLL/Z8yMlLw;NE0o.;uDSZ/_3NY0i8J490xcyu6bv2gsct9cav5czig1j8DCW2fk/Z8yRgAc8JY91NcyvrEMJj/Qy5M0@eAwk0<O9p2g8joQY1AS9Z4MXr2gw3U8FY/_pF1cyu1cav180QgA24y9h2gwjonJtnB8yRgA8eBzZL/A4O9U4ybv2gwi8JQ951cav180QgA24y9h2gwijDZsN18eRMA47c9jjDY3Ucp1;jonJtjHHLSoK3N@4}18yR0wi8I5DnY0<wFQ4wZ/Yf07pGi8I5ATY?8J068n0tni_p:ewyRf/i8I5uTY;@Sk2y4QDn3i8IgWY9C3NZ40,8yT0wi8I5lnY0<yb5kp_0,8ys58av58wvD/MY03Upz.?i3D23Uay:LSg;3EQdf/Qyb1iB_;fJB0Exd9RKkybceKU3NZ0<ybt2h0yPSJt;Kww;18NUgAc<;4;3EZZj/Qy3@fYfxm7/_Z4yNnKvw?honi3Uhh//Wczk/@beex1Rf/j8Q5LbD/XAX1;i8QllXT/QC9Mkyb1jhA0,8zjllL/_i8IUcs3EIZf/@Ai//pwYvh;i8I5AnU0<ybk0x8yNl@vw?i8Cg0<0<yb1n1@0,8yglxvw?i8I5qDU?8J068n03UgB//i8JQ942bfvhP?2W2:4z7x2gM.;g;ew@Rf/i8fU_M@5@LX/Qib3jl@0,5xsAfxeH@/_E3Zj/UIUW8zj/Zczgk3Kv/KlI20,8zhmuLf/ioD1i8I5uSc0<yddpO@/Z8yPwNMezWQL/WqL@/Yf7Qg0<ybn2h8i8D6j8Js9218ytB83XHFfQMXr2gUi0Z5Sky3M061VL/3M18yMSNvg?i8D7i8A5DTQ?6p4yqNN,;87D/Yf<O9DfA<2?i8CsYg.8,8es9OiQM1XkwXr2gg3UdW_v/i8J49218ykgAieA6Yf/pwYvh;i8Js96182scfxbDP/Z8yRMAo4wVS4wfgId8ysvF4v3/Sof7Qg0<ybugybshy5Zw@4Gg;4yb1hFZ0,8yo40.?i8I537Q0<y91vRY0,8yMk6vg?yQ0oxs0fx7z/_Z8yTgAg8IZA78?bE8:icu493,;1:WdHi/Z8w_z_3Uld//h8I5QnM0<m5M0@4fv/_@yHQL/yPzE9db/QOd1p@T/@VmM80<yd5jGX/Z9ys58yMknow?i8QRebT/Qybe370W9rh/_F_LX/V18xv@@.;4C9M4wfhfV8yP5czgOZ]4AFY4Cdd3B80vp9ev0fww,0,casx8es8fwYj@/Z8yo40.?i8A5anM0<yb1j9Y?2bg1y5M0@4FfX/Qybt2h0yPSYsg?Kww;18NUgAc<;4;3E1Jb/Qy3@fYfxnD@/@bfvVX?25_M@4q_X/@zpQv/yPzEkJ7/QOd1sSS/@Vrw80<yd5myW/Z9ys58yMl5og?i8QRpHP/Qybe370Wcjg/_FbfX/MYvw]19yvnF7LP/UIlEDI?8ni3UihYL/W7Th/@beezSQf/j8Q5Hbv/XBd1;i8Ql3bH/QC9Mkyb1uBw0,8zjkaLf/i8IUcs3Eqd3/@BiYL/i8QQfQMVNw@3ZLX/Qy9NADhW4wFRAMVNAAfh_19yvx9av190s18evt93Qb0Wt7@/Z8yTMAcew7Qf/ioD6WjrB/Z8yTgAg8IZF7;bE8:icu493,;1:WeXg/Z8w_z_3UmFYv/yPnCuw?xvofx9LN/_EMt3/UIUW3Hg/ZczgmRJv/KkI40,8zhlgKv/ioD1i8I5bm;4yddkWX/Z8yPwNMeyIP/_WlPN/Zcyvx8yTMA84ybt2hgjoDYj2DMi0d490x8ykgA8eCv@L/i8eY9fw:13UpV>?K3Y:NQLd83XSk9fw:FQ37ii9x8yogA2<0<y9x2jE:i8eY9ew:13UjAU/_Wq_z/Z8yQgAa4Gdj241iER48058ykgAa4wVNw@3jMc0<y5Og@54vf/Qy9j2ggjoDYWqvH/Z8yPnNug?i8J624wXx2iM:3U8f>?i8Daj8D7i3Dn3UfwW/_i8IROnA?eCFZL/i8I5LnA?8J864yb5qJV0,8ehmsug?ykMAs0@2C0k?8J068n03UnL1g?i8eY9f}3UzY0w?yQgAs8n03UjM0w?i8eY9cw]3Ugn1g?i8JQ942_1w;ewuPv/j8Ks9f:18yVgAe<?37Sjonrt5J8Ks_Tk@eBCYgwic7G0QxFL2gM.0.48f<y9Q4zTUkz1Wwh80vF8yXMAO:4y9Q4wF@4MVS7cxiiDjLCg;19zggXi3S7yw40tMR8Muw3ifvxic7G18Dmi8JY9229YHU2:W3Ld/@5M0@e@g4?fq492o1;13Unj0M?ZEgAbw4;4fxdQ10,8yMmMu;j8DxNE0o.;st491,:WkTM/Z8ypgAW:4z7x2g8.[eB1_L/i3B496wfwEHF/Z8yUgA@:4zhp2gUi8JY93x8yUMAI:4wVNQwfg_yU0w:Z2x2ik:i8BY93y9x2ik:i3Bc95wfwZY;20L2g5.:@4Qg;4ybB2g8.?i8Dhi8f_0nokcs2VfM;fd83XT7as58oYB80t58yUgA2<0<ybL2iM:i0@Lz2jE:i2JY95x83W_7i8Qkgbw1:i07ii8n9i0Z4O4wVOD88i8Dgct98Z_6bB2jA:xt9UnQwVNQyd5laR/@@g:4wfhIt8yTMAg4y9MkC9Nj70W0Lb/Z8yTgAg8KY9eg;18oZ3EtYT/Qy3@fYfx1Q80,c0mMAm4yb1m5T0,8yQMAm4y9i0x8yPlhtM?i8I5gDs0<y9xx,0,8yRgAe4yb1jtT0,8ZZF8yp08.?ict496w]WjjE/Z8yRMAi8JY9>NQAS9Z4y9TKzFOL/i8Jk932bv2gsj8DSW8zb/YNQAy9n2g8i8IZSDo0<y5M4wfic9dzjM6WgDF/@3v2gg0w@4?8?ct491}j8DxWnfK/ZcyvJ5cuQNXuD7Vf/h0@Sr2hMWivB/Z8yTMAi4y9Mo7x/Yf<y9LcU<2?WkvN/Z8NUgAO+2@p:eCa_v/i8niKg4;18yPVcyMlktw?i0Z4Qky9MkwF@kOd39k]ioQY4kw1_QwV@g@2Swc0<MFO4z7x2j8+4AVM0@3Hur/Qy9xw,0,8ygkctw?i8I55no?8J068n03UgGYv/i8JQ942bfpZH?2W2:4z7x2gM.;g;ezFO/_i8fU_M@47Mo0<z7x2j8+4ybdsNR?3FiKr/Qz7x2i-cu499g:2:WjbD/Z8yTgAgbY6:i8Bc9214y8gAE:exfOv/K0c;18yQMA8cjy@_uk93w10,8Kc_Tk@eBCYgwi6CQ93,0,.wY0h0@Sx2iw:ifvyic7G14yd11p8yPlatg?j2Dwi3DE3U94Xv/i8K49aw;14yaMAE:4i9NkObp2h8i8C49d:18yUgAC:4y9x2j]i8J495x8yogAS:4ybh2hUi8B4923FneX/Qybt2h0yPR_qw?Kww;3ErsD/_q492U1;13Uko_f/i8K49bw;18yQMAmct49102:i8R420p8Qux8yogAK:eDTUf/h8IJFDg0<m5Xg@40uD/@y0OL/yPzE@sD/QOd1pmO/@VL0c0<yd5g@P/Z9ys58yMnImg?i8QR3rn/Qybe370W6L9/_FMKz/Qybt2h0LMo;3E1Yz/Xw3:NebXZVgAe<0<yUP_tjUWmrN218Z@98qoMAc<0<123M18MuE4i8Q44ky9x2j8:WpTW/Z8yT08xsAfxlM1?2bi1y5Og@5kg40<y5ZHA1:i8IUj8I5Qnc0<wfhf58yt58avBczgOR]4Cdf3580vZ8evAfwyA20,casF9et0fwzo3?2bg1y5M0@47fT/Qybt2h0yPQZqg?Kww;18NUgAc<;4;3ExYD/Qy3@fYfxurV/@b1nZP?25M0@4SfD/@xqOv/yPzEQYz/QOd1kWK/@V@080<yd5uCN/Z9ys58yMn6m;i8QRVXf/Qybe370W4n8/_FCvD/Qy9QkzTSkyb1hJP0,8yoog.?i8I55nc0<y9y0w10,8ylgAe4z7x2i-cu499g:2:WnjA/Z8NUgA2<[18NUgAW]4;3FxdP/QybdAy9OAwVPDcri8Ks9b:18av58etB83Qvbi3D83Ua@.?j8D7WsDU/Z8yNmjsw?i8Cg0<0<yb1olO0,8yglSsw?i8I5vT8?8J068n03Ukg.?i8I5rn8?eD6@f/i8QY4AwVPM@37fP/Qy9NQzhWkMFNQwVPQwfh_B8yt58avB80s58evF83Qb1WvvX/Z8yTgAg8IZOSs?bE8:icu493,;1:W1n8/Z8w_z_3UkI_f/h8Id3780<m5Og@47fP/@zCN/_yPzEnYv/QOd1tGI/@VmM80<yd5nmM/Z9ys58yMlilM?i8QRsXb/Qybe370Wd76/_FTvL/M@Sh2ggw@,w_,j3DX3Vb22t18xsAfxiY20,1yskNXuD4T/_i8QYdAwVPM@3PvT/Qy9RQzhWkMFNQwVPQwfh_B8yv58avB80t58evV83QbhWqzZ/Z8yTgAg8IZ@mo?bE8:icu493,;1:W4f7/Z8w_z_3Un5_L/yMkXsg?xs0fxbv@/_E5Iv/UIUW8_6/ZczgkaHf/KlI20,8zhmBH/_ioD1i8I5wBo0<yddqeN/Z8yPwNMew1NL/Wnz@/Z8ysJ8yTMAgbV]i8QlxaX/QwFMP70i8DpW4L4/Z8yTgAg8KY9eg;18oZ3EJYr/Qy3@fYfxaE10,8yQgAm4w>Qyb1pVM0,8ylw8i8IlyT;4ybfnNM?3FHLr/QkNXj7JWpbu/Z8yp;g?i8AlnT;4yb1mxM?2bg1y5M7kpi8I5mD;eCy_f/goDEWg_X/Yf7Qg0<ybt2h0yPTtpg?Kww;18NUgAc<;4;3E9Yr/Qy9MAyb1hRM0,8w_H_3Ulw_f/wPQks]@4k_P/@zNNv/yPzEqIn/QOd1umG/@Vrw80<yd5o2K/Z9ys58yMltlg?i8QRvH3/Qybe370WdP4/_FpL/_MYvw]14yMn1rM?hon03Ujh@v/W9L5/@beewkNv/j8Q5zWH/XBK0w?i8QlaGX/QC9Mkyb1gtl0,8zjkEIf/i8IUcs3ExIj/@Ci@v/i8IRqCY0<kNM8Jm64i8r2hMgoD5WhDW/Yf7U}yMlirM?xs0fxdnT/_Ebsn/UIUWar4/Zczgl2Hv/KoI30,8zhmYHv/ioD1i8I5Clg0<yddrGL/Z8yPwNMewoNf/WprT/@3fghL:3Uh9_L/We74/@beexqNf/j8Q5ZGP/XDP0M?i8QlsaT/QC9Mkyb1kRk0,8zjlKH/_i8IUcs3EPcf/@Aa_L/3N@}45nglp9ytp1lk5klld8w@MoynMA1bY;40i8BQ90zEfc7/QC9NQS5ZDh@hj7AWNof7U}W6f4/@3e0hRq4QVZ7dzi8J490xcyvabv2g4j8D@j2DyiEQc8bw;40i3D2i0Z7Qex2ML/ioD5i8n0uc9QcAy9MQO9_mqgi8Dqi8DKLM4;3E8cj/Qy5M7wbi2D3t2p80snHUp3E@Yf/UcU17jmi8f464O9_RJtglN1nk5ugl_FMc7/QQ1XeBW//3N@4}23_M9_2Xw1:MMYvh;gluW2w;45mgll1l5m9_ld8yvd8wuMU1;i8J@237SW5H2/Z8yTIgKwE:NZEB491zEhIb/Yt490M]ykgA78fZ0Tgsi8JX64yddrqH/_Elsf/Un03Vj03Xr0ykgA34yb1m9J0,8xs1Q1cp0a058zkgAg4kN_Qydr2gMhj7Jict492w]i8B4911CpyUf7Ug}8JY91yW0.0<y9XKyLMv/i8n03UX2:ic7E18n0vJWdmfZ9yuV8Muc4i0ds913H5MYvh;ijD53UaT:iof644AVTDiSioI6j3DEtupd0SU8jon_tibH9gYv<SbpN1cyvZdySY8j8BA92zEyY3/QS5V7g8joDDjjALtdV8yMmDr;i8n0t0hcymwwyQgA38n0tixcyuF8yMmcr;ibA0Yf///vU7y/Yf<wzzd0<2?3Umu:j8JY92zFtv/_MYvg,cyvZdyTYgW2j0/ZdxvZRXQy1N3w4;NM5JtglN1nk5ugl_33NY0LNw;3ETHX/Qy9MkCb1Ay90kCblwx80s98yl48i8Rk92xdxvZRbuIM3N@4}1CpyUf7Ug}=[ioRn44SbvN1dxvZQ1kAV1TbKj8BV44y92KBA//pF2bv2gscta@0M;exMMv/j8JY92zFN_X/Sof7Qg?8f_0DYbK<;333NZ40,1lXEa:glp5cvp1lk5klld8yvd8wuME1;i8J@237Si8RI921czmMAcewvMf/i8JX4bEa:cvq9h2g8W0L0/Z8NQgA6]29h2gc3NY0pCoK3N@4}2bv2g8Kw<0,8yuXELX/_Qy5M0@eZw;4z1W0i5M7Xuzlz_ioDIic7z14M1W@Il3N@}4AVND9ziof444AVT7iWioI494MVY7nFi8JY91xd0TgA24y5_TksWNZcyTYgj8JT24O9v2goW9W@/ZdxvZQ24O9_QMVdTjxj8DNi87x0f3/TWOyTMA337iLwc;3Els3/@Kw3NY0LNw;3EhHT/QCb52h8zkMA64y9NAy944Cbh2g8i07gi8B624ybh2goi8n0tiXHcmof7Ug}=[pCoK3N@4}18zkwgi8J<4y5M7g5i3AgsKV8ykogi8ANWi//ZCA4y1N2w4;NM5JtglN1nk5ugl_3A=[w_Y2vMqU.;cdlKwE;18yul1lQ5mgll1l5d8yvd8wuNUww?i8J@237SW8W@/Z8yRIgi8QR8Wr/UB491h8yt_EFX/_Qydt2hgLM4;11ysjEZrX/Yp492?xs1R4UJ496wB0f;3Q0w;3Vh49215xugfxdQ20,8zkgAg4kNM4z7h2gM]4OdF2jw:i8B4921CA4ybt2gwyTMA5bEg:j8B492zEWbT/QObh2gEi8fU40@5ww80<Obt2gMj3B4941QqXYo:j8B492zETHL/QObh2gEi8D1i8J49418yg58yRgAi4w>AS5ZAy9kgx8zlgAc7kBWOxCpyUf7Ug}=[ioRm44Sbtx1dxvpQ1kAV1DbKj8BN44y92KBy//i8DpLw,;NM4O9h2gEj8SI97,0,8zhmmEL/j8DLW2OY/YNZz70j8DLWb2Y/ZcyQgAa8n.oD73UBC.?j0d494xdxvpRcuAh//A4SbhwxdyTUgj8DTj8B492xcynMAcewSLf/jon_j8J492wfxez@/ZdyvVdegofxtP@/Z8ytB8zhkAEL/j8DLcs2@0<?eyPK/_cvpcyuYNMewTLf/goD7xs1UE4z7h2gU]4O9VED7W4SZ/@5M7kdi8Kc91,0,8xsB_5ki9_@y4Lv/j8DLW0OY/_Fp//Qybh2gUi3D1vK58zngAe4y9t2gEi8Jk92x8as54yvW_.;eyKK/_i8n0u1B8yUMA4<0<ybh2gUi3D1vZjHGgYvh;W8KZ/@b08fU17jrzl3Gw@bLt123@0AfBca3@5wfBc08MDi0i8JQ93wNQAi9_@xdK/_i8S497020,8ykgA6eIopwYvh;i8JQ91x8ysa_.;ex6Lv/i8JQ91yW08;4i9_@z4K/_i8n0vZvFbL/_Qz7h2gU]4O9VED7W5uY/ZcyQgAa8n0th58yUgA4<0<y5M0@fggc0<i9_QO9h2gEW82Y/Zcyu_E2bL/QObh2gEWkX@/ZC3NZ40,cyvZdyTYEW8OV/ZdxvZRXQy1N7y2;NM5J1n45tglV1nRT3i8S497020,5cvYNSQz7x2jw+4y9h2goi8S499w20,8ykgA20Yvx[i8JQ91ybv2gkKw0a?3E_rH/Qy5M7WsibXdPcPcPcPcP4zTVAz1Wwm5QDXji8JQ90ydgLZcySgA64yd1818zgj6i8B492x9ehMA3Uka.?3NZ?=[ioJQ91x9yRgA846bv2ggi8CQ97,?20v2gw?@4rw40<y9QoD@i8Sk97,?2_.;eznKv/ioJc91x1yTMA4bU3:i8Daigdc9218wu80Yf/i2DhW76X/Z90RMA24S5_TlQWTsf7Qg0<CbhNx8zpgAs<?bY1:i8C497,0,9yQYwgoJT4exWKv/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhW1uX/ZdyTsEj8D_igdv24O9J2jw:W0@U/Zdxvofx6o10,dyvt9ehZQzAC3N2xceSgAa0@4H_X/QAV72gfx0n/_@_c:ezbJ/_Nc5@rMgAi8D1NvV_<Cbh2gwi8B184S5_M@4cM40<Cb52h8zogAU:eIH3N@4}1CpyUf7Ug}=[ioR7a4SbvOxdxvZQ1kAV5TbKj8BVa4y924ObL2jw:NvxTiof4a4MXp2gE3UlK//Whz@/Yf7Ug}ezrZv/ioJc91x1yTMA4bU3:i8Daigdc9218wu80Yf/i2DhW1mW/Z90RMA24S5_TlDWhz/_ZC3NZ40,9yTsoi8CQ97,0,9yRswgoJ_4ey7Zv/ioJf646bvN2@0M;4y9OAA3jO18wu80Yf/i2DhWciV/ZdySYEj8D_igdv24O9H2jw:WbOS/ZdxuRQ5QS9XQAV7TivWqP@/ZCbwYvx[hj7_iof4a4MXp2gE3Umv_L/WkDZ/Z8zogAU:eD@_L/i8Jk93x8et0fzH7Y/Z8zngAe4y9t2gEi2Dgi8Jk92x4yvW_.;4y9MkO9h2goW7uT/ZcyQgA64y5M7wti8K491,0,8yRgAe4wVQ7_7WmDY/ZC3NZ4?3EiXD/QObh2goyM23@0hQQERgWEfyXTgkw_w93Vj2w_xo3Vj02c8fx3rY/Z8yTgAe37ih8D_j8B492zE_Xr/Qydx2hM0w?j8J492x8ykgA6eIsi8JQ91x8ysa_.;4O9h2gEWfiU/ZcyQgAa4ybt2goKw2;14yvZcykgAaexEJ/_j8J492x8xs1_M@Dc@/_pwYvx[w_Y13UXn0w0.luW2w;45mgll5cuR1l5l8yvljyvJ8wuOE.?i8J@237SW3WT/Z1ysi3@Mcfx8E2?3E3rP/Qydfg6v/Z8Muw3i8So/Yv0bw:2i87z?3w_QwVMQwfhZyU;w<wVMQwfgJzEpXn/Qy5M7gnKwE:NZAy9N@zzJL/i8D5i8n0vMmZw:4ydv2gMWdOS/Z8NQgA4]y5M7kSNvBL3tuq/YNQInVrEgAC:cjyuj_1NvB@M4wfHQgAk4zTZrE:8i3Dgi0Z3Q4y9l2ggi8SQ91,0,4yu_E2rv/Un0thubx2gE.?9g3M;Z08:@4Tw40<6V1g;4C9S379h8Dycvp4yu_ERHv/QC9NQy5M0@8Ow;bQ]grU:1tj5CA=[grA5:ioDocsB4yu8NZAi9X@yoJ/_ioD7i8n03UWt:yPTulw?xvYfysU;1c0vR9euVPNAydL2iw:WeCR/@9Mon0tlf5@mYdWVD/Qybt2ggNvBKx2g8.?Ne9VfY75@nX0i0@Lx2j8:i3DMsOp8yMnLo;i8n0t1EfJA0Exc0fxjI7;f7M1CpyUf7Ug}4C1Nw:7Flf/_MYvg03EGXr/QC9NEcU5w@410o?8IZflo?8n_uhkNM4y1Naw10,rnk5sglR1nA5vMV18zrgAE:bE8:icu49a]1:W7aS/_HOQydJ2iw:Kww;18NUgAE]4;3EkHr/Qy3@fYfxgH/_@b5kFw?25Qw@4_fX/@wBJL/yPzEDHn/QOd1k@x/@VdMo0<yd5riu/Z9ys58yMmhhg?i8QRIG3/Qybe370W12R/_FLvX/MYv<ybvh2W2w;37SW9yQ/Z1ysnFnLT/Xw1:MSoK3N@4}18yVgAg<0<ydt2gEhj7_cs18NQgA8]18NQgA2]58yjgAi8ni3UXM_L/3NZ?=[i8Dhi8Dti8B492x8as58etB83QrFi8nJ3UhW.?hj7SioDEi8IQ94kNOj79jiDMh8Dyh8DLW5mQ/Z8xs0fy0M1;fx3810,90sp9euVOPQybh2gwpwYvx[jg7TyPS_l;j07Mi8B49225_M@9dM40<ybB2h0.?i3D23UVn_L/j3BY90wfwSL/_Z8zqMAE:4y9X@yHI/_ysa5M7l5NvBL3qSn/Z8yUgAO:cnVrEgA2<?cjyuj_1Nc5VvIp93W_6i3J4911P5Qyb1r1u0,8xs1Q2M@Sg2y4M7kH3NY0i85490w:1i8J49218yVgAg<?eDR_L/3NZ4?21@x0D0,QSbZA:ylgA6ewaI/_i8DLW2aP/@bl2goi8K49cw;23Mw593W_6i3J4911OOeKCpwYvh;W2KQ/@b08fU10@4XvX/UfUnM@kMEfU9w@kMgzatgO3UfK3@18fxqE;18yQgA84S5Zw@5RLX/QybB2h0.?i8Dhi2D1i8n93U@f:hj7SWrH@/Yf7U}i8SQ9a:2W2:4z7x2iw]g;ez2I/_i8fU_Tgci8J4923FC_X/SqgyPSOng?xvZQWKyhI/_yPzE2Hf/QOd1rKu/@V@wk0<yd5i2s/Z9ys58yMnZgw?i8QR7FX/Qybe370W7OO/_HHHw1:WrTY/Z8es8fzGzY/Z8zkgA84Obt2g8i8A494QV_w@2q<0<yb52h8ytB4yuV4yuvE7H7/Qy9Nky5M7wKt3qbfrpi?25_M@9Zw40<A1XQybh2gwi3C494,0,_K@Bg_f/3N@}ezzIL/wPw4tdJ8yUgAg<0<ybl2gwj8BQ90x8es8fzijY/Z8znMAaezVIL/xs0fxhbY/@bv2gIKw0<02@>g?ezuIv/i8S49a:18ykgA64ybx2h0.?i3B4920fzpI;18ySMA24y9n2g83NZ0<MV_g@29Mg0<Obh2g8yRgAb379h8DLi8IQ946V1g;eyqIL/i8D3i8n0vBZ5cvof7Q?pCoK3N@4}19ytybv2gEcsANZAQFY46V1g;4i9UKxAIL/i8n0vwx90sp9etVORUIZGl4?8n_3UB70M?i8J4921d0vt8eogAg<;@fs//UJY92zEuH7/UJY92PEsr7/@AJ@/_3NZ0<ydH2iw:i8DLW8yM/@9MEn03Ume:NvBL3oqk/Z8yUgAO:cnVrEgA2<?cjyuj_1NvB@MkwfHY58eQgA47dxi8I5yBI0<y5M7hl3Xp0a8j0t4TH287W42s?7h3LSg;29l2goi8Bc90zE0b3/Qy9X@woIf/yRgA64ybj2g8i8K49cw;23Mw583W_1i3J4911OLCof7Ug}4C1Nw:7FVfT/MYvg,8zrgAE:bE8:icu49a]1:W0aN/Z8w_z_3Uny_v/yPnWmw?xvofxdjZ/_ERr3/UIUW4WM/Zczgn_C/_KgY60,8zhlACv/ioD1i8I5gk;4yddmar/Z8yPwNMez0H/_WpnZ/Z8znMAaezhIf/xs0fy2_Z/@bv2gIKw0<02@>g?370cuTEIG/_Qydx2iw:ics49]58ykgA26qgpCoK3N@4}2bl2gIgrA5:ioDocsANZAi9X@y7If/ioD7i8n03UV8_L/yTMAa379cvp1Kgk;19ys14yubEoH3/Qy5M0@e9LX/UIZGQY?8n_3UDr:j07Zi3AI97eyi8JY90zEKaX/Un0tkj5@mYdL9b/YnVrEgA2<?cjyuj_1NvB@MkwfHUMAO:4wXj2ggsNF8yMT3mg?i8n9t0UfJAAExcAfxvo10,CA4y112g:1Wkf/_Z4yiMAioDRj8BQ90z4MnB@NAy9n2goysLH4mof7Ug}87X42s?7gHLSg;23MM7E2WX/QydL2iw:W1WK/Z8yUgAO:4AfHYpceuxOPkibb2hcyTgA24ybn2goWmHU/ZCbwYvx[i8JQ90yW2:4z7x2iw]g;ewlH/_i8fU_M@50f/_UI53lA?8n03UjO_L/goI@W6mK/ZczgkmCL/Kl860,8zhlXB/_ioD1i8I5m3U0<yddnCp/Z8yPwNMeznHv/Wrv@/Z8yTgA6bE8:icu49a]1:WauK/Z8w_z_3Umk_f/yMSvm;xsAfx8rY/_EuGX/UIUWfeJ/ZczgmACv/KiQ60,8zhk9B/_ioD1i8I5VzQ0<yddgup/Z8yPwNMexBHv/WkvY/Z8yTMA6ew6Hv/goD6xs1RgsnVrMQ7Av/i8K49cw;35@mW490w1?34UDA_MsnVvId83W_3i3J4911P54yb1gJo0,8xs1Q20@Sg2y4M7kli875]uBX@/_go7@42s?7jHLSg;11wYo1W7KI/Z8yTMA6eyhHf/i8K49cw;183W_3i3J4911OPeK@i8Bs91z4MnB@NUD3WMy1@N0D0,QaHZA:wYc1W3CI/Z8yTMA2exfHf/i8K49cw;193W_7i3J4911OPAybn2goWsbZ/ZCA8f_0TYbK<;333NZ40,1lXEa:glp1lk5klld8yvd8wuPo0<0i8J@237Sj8SI9d:3EVaL/QybuN0NZHEa:goD6Wd6H/Z8yTIocvqW2w;8B491zELqL/Qy9NoB491PEAr3/UBI92x8Muw3NQgAb<;18zpz/NY0K]98wuc?e3_i3D3i0Z7Sbw?2?i3D3i0Z2S4ydh2h0hj7Ai8B491180tJ8yTgA44i9Z@zKG/_xs0fy0o10,cyTMAs4Cdb1N9euYfwHY;18zkgAc4y9h2g8i8Sd?3/XE;40j8DKh8DTW7eG/Z8xs1@pAy9MHUa:j8DLWbWI/Z8xs1QkkMFW4ybt2g8yTMA6bEg:i8SI1g40/ZcymgAc4y9W4MFU4y9h2gUW2KI/Z8w_wgt42U.;4y1Ndw0.1rnk5sglR1nA5vMSof7Qg0<ybt2g8yTMA6bEg:j8BA9318ylMAeezHG/_i8fU47n0ioDIi8QIaQAVXM@3i//Qydv2gEKCg;2@.;ewxGL/xs0fzLX@/@bv2gsKww;18zngAcewSGL/Wur@/@gcs3Fuv/_Sof7Ug}5eX.;4y3X218zngA7ezcGf/i8D2i8cU07goyTMA74y9NAy9h2g8W2aN/Z8yRgA28D3i8DnW1eE/Z8wYgwytxrMSpCbwYvx[kXI1:i8fI84ydt2gsW7OE/Z8ys98wPw0t1ybv2gsi8D6i8B490zEoHT/Qybl2g8ysd8ytvEMWv/Qy3N229S5L3pCoK3N@4}1jKM4;18w@Mgi8RQ90PEbaz/Qy3e,Q5kyb5sZk0,8xt9Q1Yq26<;4NSQy9N@xVF/_i8f448DomYegkXI1:i8fI84ydt2gsWeOD/Z8ys98wPw0t1ybv2gsi8D6i8B490zEEKr/Qybl2g8ysd8ytvEcWv/Qy3N229S5L3pCoK3N@4}11lQ5mglhlLg4;1ji87IM:4ydt2gsW9aD/Z8ysd8wPw03Ui7.?ySMA78fZ.@eO<0<ybu0yW2w;37SgrP//_WcaE/Z9ysu3_g8fxro10,8zjTdA/_W1GD/Z8zjSAAf/i8D5W0KD/Z8xuQfx3810,8xs0fx2A1?2W2w;37Si8DLi8B490zEBqz/Qybv2g8KwE:NZAy9h2gwW7@E/Z8ykgAa4m5_M@fsg40<m5V0@eW:4ydfj4U?3E_aD/Qy9NkgXE}fxrM1?23K1]13Unx.?i8QZj8X/@y3FL/i8n03UiG:KwE:NZAy9N@zXF/_Kw4:NZAi9VQC9N@wpF/_i8D5i8fU_M@4C:4ydfskT?3EAaD/Qy9WAydt2gMh8D_NvBLh2gwh8BA9437h2h4]cnVvQgAc4ybw0w;18asb4UvBKOcjzYib20rEE:NvF_h2h8WduE/Z8w_z_3UiV.?i8QZpzs?ewNGv/i8CE2:6oK3N@4[NXky9T@xCFv/i874M:8DEmRR1n45ugl_3yMSmkw?xsBQaKxRGf/yPzEXGv/Qyb5vsT0,8zjlEBf/i8IWi8D2cs3EsWv/MYv0bQ1:WWJC3N@4}18yTIgKwE:NZKzMFL/goD4Wjb@/Yf7Ug}4ydt2gwKx:14yv_E7Gz/Qy3@fYfxnf@/@bdhpi?25Zw@4pvX/@zNF/_yPzEqGv/QOd1sej/@V2wk0<yd5o2g/Z9ys58yMltdM?i8QRvFb/Qybe370WdOC/_F9LX/MYvw]14yut8zngAc4i9E]3EXar/Un0th2bh2h89g3M;Z08;7hRNUkg]w;4ydt2gwKx:14yuvEvav/Qy3@fYfxsb@/@b1nhh?25M0@4JfX/@xfF/_cuSbeez6FL/j8Q5BVb/XAG1g?i8QlT8/_QC9Mkyb1rAS0,8zjnqAv/i8IUcs3Eear/@BR_L/NUkg]g;eCB_v/yNkmkg?xt8fx3D@/_EYqr/UIUW6GC/ZczglbAv/Kio50,8zhm0z/_ioD1i8I5njo0<yddnWh/Z8yPwNMezsFv/WvHZ/Yf7U}kXI1:i8fI84ydt2gsWfOz/Z8ys98wPw0t1ybv2gsi8D6i8B490zEwKr/Qybl2g8ysd8ytvEgWf/Qy3N229S5L3pCoK3N@4}1jKM4;18w@Mwi8RQ91PEHaf/Qy9MAy3e,Q68JY91N8ysp8ykgA2ey2Xv/i8Jk90y9MQy9R@zPEL/i8f488DomYdCpyUf7Ug}5mZ.;5d8w@Moi8RQ90jEmWf/Qy9MQy3e,QbodY9.1vPKbfoB50,8zngA2bE8:ict490w1:WdSB/Z8w_z_t2YNXky9T@ydEL/i8f468DEmRT33NZ0<ybu0yW2w;37SW62A/@9N@KT3NZ?8I5GAY?8n0tcvEyqn/P7JyPzE0an/QOd1lWb/@Vsgo0<yd5hqe/Z9ys58yMnPd;i8QR593/Qybe370W7aA/_HyReX.;4y3X218zngA7eysEL/i8D2i8cU07goyTMA74y9NAy9h2g8WcbT/Z8yRgA28D3i8DnWeex/Z8wYgwytxrMSpCbwYvx[glt1lA5lglhlkXI1:i8fIm4ydt2gAW4ey/Z9yst8wPw0t0Cbr2gAw_Q5vO5cyv_ECq7/Qy3N5y9S5JtglN1nk5ugl_33N@4}18yTw8KwE:NZA6@//_@xqE/_ioJ_4bEa:cvq9h2gkW4qz/Z9yTYoKwE:NZEB4913EcGf/QCbvO2W2w;37SysfE8af/QCbvOyW2w;37SykgA6ewcE/_ykgA78fZ1w@53M8;Yvg,CpyUf7Ug}4m5ZDwri8RQ93yW.;4i9Z@yVEL/i8n03UXg.?i8RI942bv2gkKx:18yuXECGb/Qy3@10fxr,0,8yQgAg37SKw8;29TQy9h2gEWcyx/ZcyQgAi8JY9129SAkNOkydj2gMi8RQ92x8ykgAcez6EL/i8n03Uzt:yTMA64ydt2gUKww;18NQgAe<;3EEqf/Qy3@fZQqUJY91OW4:4y9XKyaE/_i8fU_M@5gf/_UI5wAQ?8n03UgO//W5Sz/@beezmEL/j8Q5zUT/XB7>?i8QlX8L/QC9Mkyb1sAO0,8zjnGzv/i8IUcs3Eiab/@DP_L/3NY0yNkOjg?xt9Qy@whE/_yPzEyGb/QOd1vGc/@Vhws0<yd5q2b/Z9ys58yMlZcw?i8QRDET/Qybe370WfOx/_Fjf/_MYvw]2_;10ey6D/_i8JQ942bv2ggct98ykgA2eyxEf/Kw8:NZEDvW9ew/Z8yRgAi4y5QDh8hj7JpwYvh;j2DGK:g18yTgA28JY9118es99ythc3Qvwj8Dyjg7BW0Gx/Z8yTgA24O9UEDvW6Ky/Z8yRgAi4AVRnb1i8JY90zE5V/_@Cl_L/pF0NS@BE_v/pwYvx[ioJ_cbEa:cvrEUa3/Q69NKDE_v/3N@4}1jKM4;18w@Mwi8RQ91PEn9/_Qy9MAy3e,Q68JY91N8ysp8ykgA2ex2Uf/i8Jk90y9MQy9R@yzDL/i8f488DomYdCpyUf7Ug}45mlrQ1:kQy3X318zngA3ew9D/_i8D3i8cU07h5wTMA305@tAydfpS9/ZcyT08W1CC/@5M7x5i8RI9129MrUw:cs18yuZ8zhkKyv/Wfyu/Z8yuVcyvsNXuyXEL/i8DvW2eu/Z8wYgMyuxrnk5uMMYvx[W3Kx/@beeyQEf/i8QZDEr/Qy9Nz70W3eu/@Z.;eL1A=[kQy3X218zngA7exxDL/i8D1i8cU07hEwTMA705@okybu0yW2w;37Si8B490wNS@yqD/_KwY;2@2gg?8D7cs3E1W3/Qybj2g8w_z_t1l8ys_ExpT/Qy3N229S5L33NZ4?2b1rFa?25M7ku3NY0pCoK3N@4}2X.;eLcpwYvx[W7Kw/@beezQD/_i8Il_iY0<yddnqb/Z8yPF8ys8NMexVD/_i8Jc90zHMCqgglplLg4;1ji8fIc4ydt2g4W9Ct/Z8ysd8wPw03Uig:ySMA18fZ.@eL:4ydv2g8W5mw/@5M0@8zg;8JY90MNMbE0,?Lws4?3Ee9/_UfZ0w@4BM;4ydr2ggyQMA2bUw:cs18zhmpx/_i8DLW62t/Z8yTI8i8DKW2ix/@bj2gci8DLcs18zhlRx/_Ly:3EeFT/QybuN18yuUNXuzYEf/i8DvW6is/Z8wYgMyuxrnk5uMSof7Ug}exXD/_yPzEZ9X/Qydfm@5/Z8ysoNMexPDf/Lg4;3HM0Yvg,8yQc8i8D7ioD6W2Cs/Z8ysl8xs1Quvp0a0hQqUJc90y@8:4ydv2ggcs18zhnBxL/Wa@s/Z8yuYNOkydl2ggcvrEjFP/UJc90O@8:370i8QlLor/Qydv2ggW8as/Z8yuYNOkydl2ggLw4:NXuwsDf/WjL/_Yf7U}j8DTW1ys/ZcyvvEU9L/Qy9Nky5M0@5uv/_UJY90zEiVX/UJY90PEgFX/@AW//pF1CpyUf7Ug}45nglp1lk5klrQ1:kQy3X2x8zngA5ezjC/_i8D3i8cU07ggh8JI91h1w_Q4vN@Z.;4y9T@wyC/_i8f4a8DEmRR1n45tglV1nYegi8JU2bEa:cvrEY9P/QybuN2W2w;37SioD4WdSs/Z8yTIoict491w]goD6w3Y03Un4:hj7_i8JX8bEa:cvrEQpP/Qy9Nk63_gkfx7M;18yTIEi8QR1Uj/@z4Dv/Kw0<02@>g0<i9ZUn03Vj03Xr0ykgA2370Wfis/Z8xuRQckm9VkkNV4C9W379grA5:h8DOjiDwj8D@h8DLWdSt/Z8xs1Us7g8ig74ijDIsJmbh2g8xs0fxr8:NXuAh//3NY0Kw0<02@>g0<i9ZP70W9is/_7h2g8]4y5XnmocuTFVLX/P7SKwE;3E59P/Qy3@fYfx2r/_Z8ykgA64Odv2goWhH/_Yf7M3E4VT/UIUw_Ybt8C3_Mgfx83/_@bl2g8xt9R8@xSDf/i8QZ7Ub/XQ1:i8D6cs3EY9D/@C1_L/3NY0h8DTi8B490zEqVP/Qybl2g8yPHHNSqgh8DTcuTElFP/@Bn_L/A5mZ.;5d8w@Moi8RQ90PE@VD/Qy9MQy3e?fxaI;18yPSnhw?i8n_t1m@,2w0eyUCL/ics5vko[2bfhsY?25_M@9bM4?8IZ1jM?8n_3UA1.?yPTPeM?xvYfytc;2bfu4X?25_M@9Fg;8IZPPI?8n_unKbftQX?25_TBhi8QZwD/_P7JW6ep/Z8zjRBxv/W5up/Z8zjSyv/_W4Kp/Z8zjSUw/_W3@p/Z8zjRVw/_W3ep/Z8yt_EGVz/Qy3N1y9W5JtMSqgW6Kr/@bfo4X?3Eo9L/Ys5rzI?f//_HAMYvg03EiVL/UIZnjI?cs5ePI?f//@5_M@8sL/_@L1AewHC/_yPQBeM?NMkveM?//_Un_3Ux8//WY6gW0Kr/@bfgAX?371gcX?3//_xvYfy1X//HMp3EWVH/UIZXjE?cs5VPE?f//@5_M@8YfX/@L1AezbCL/yPThew?NMnbew?//_Un_3Uz2_L/WY6glky9Vk5nglp1lk5kkXI1:i8fAM4y1Xc:18zngAlex9Cf/i8B49318wPw03Uju1g?i6ds95i3@Mcfz@M50,8zgm8wf/i8B49223@M4fzNMc0,8zjRwag?W2Kr/@bw.;29h2gIctJczjRgew?j8SI98:11yP@5_Twpi8RQ962W4:ewqCv/i8fU40@4g0o0<yb1nB40,8yXw0.?i8IlqQg0<ybcAwV_w@3ZMk0<Obwww10,dxs0fycs60,8zko1i3D73Ueq1w?i2DTioDYi8DXY4wfMhF8yMQJh;i8K10<0<Wdd2dcev0fw_U50,8yNkih;3Xpiaoji3Ug6>?i2Doi8n0vMUNS@Bn//3N@}4yb3uB30,9ysi0Kmc1:3Uh83;i8S498:18ykgAg4Gd52ddyul8Kf////Z_wub/MY0i8KQQg.8,8ytG1UL/3M188sp88Ujh,0w<wFNL1c0m4gi8nS3UjB2M?irzdPcPcPcPcP4ydj2hwi8DfpwYvh;i8DMi8f70kDTU4y9Y4z1WwdczgOijg79j2D8wY0Mi8f@2ky9REx7_Tvmi3DV3Ud93;i8D@i8DUi2Dei8Rm_Qy3@zUfxC0c0,9yv19yvB8yRgAg6bN_kxL9i5X/ZyYvR8rNRnu/_iofwM6bN_kxL5oBX/Zdas5C3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_j3D8ttd9ev0fx7Y;18yvx4ys9cas19yv5das5dzl7_iofW7DoPj2D7oL5_a6Z7_Yjzvkr?sjyvg05C7L/Yixvn@418:11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug}=[3XpU_Qy3W058wY81g8xW_QwVMnbHi6fSi0dQ9435@7v61w18yTgAg4ybv2gwW6Wp/Z8xtIfx5Ea0,8zkMAo4y9TACUPsPcPcPcPcN8ysYf7Qg?=[i8DMi8f70kDTU4y9Y4z1WwdczgOijg79j2D8wY0Mi8f@2ky9REx7_Tvmi3DV3Ue_2w?i8D@i8DUi2Dei8Rm_Qy3@zUfxJoa0,9yv19yvB8yRgAg6bN_kxL9q5V/ZyYvR8rNTnuv/iofwM6bN_kxL5gBW/Zdas5C3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_j3D8ttdcesofx7Y;18yvx4ys9cas19yv5das5dzl7_iofW7DoPj2D7oL5_a6Z7_Yjzvkr?sjyvg0567H/Yixvn@418:11ZI4vt3R9w@7wh07aj2D8i6fii0dk941CpyUf7Ug}=[3XpU_Qy3W058wY81g8xW_QwVMnbHi6fSi0dQ9435@7v61w18yTgAg4ydfm@0/YNQKwWA/_i8Rc9618LYTcPcPcPcPci8DejonJ3UiO2;3NZ?=[j8DEi8f60kzTVQO9W4z1Wwdczgiijg70j2D0wY0MiofZ2kC9Rox6_Tvmi3DN3UcR2g?i8DTi8DMi2Dfi8Rn_Qy3@zUfxCE90,9yvB9yv18yRgAg6bN_kxL9i5U/ZyYvR8rNRnuf/iofxM6bN_kxL5oBU/ZdasxC3NZ4|0cJyYDR80c9yYvl8WY1yYvR8vQb_ijD0ttdcesYfx7Y;18yv14ysFcasx9yvxdasxdzl3_iofW7DoPj2DeoL5_a6Z6_Yjzvkr?sjyvg05C7z/Yixvn@438:11ZI0vt3R9w@3wh072j2D0i6fii0dk941CpyUf7Ug}=[3XpM_Qy3W058wY81g8xO_QwVMnbHi6f_i0dY9435@7v6>18yTgAg4ydft9X/YNQKyWAv/yTMAb8n_3UDC1g?ctJ8yTMAcez2Av/i8RBS8DomQ5sglR1nA5vnsegioD7i8fH0uxAA/_ioIkTQyb<wfLxbSh5,27gkioJkT_x83XUiZAhg.wfx4w70,8yRMAc4ybmMx83XUji8Bs923Sh5,20@490o0<ybv2gwKwE:NZKx0A/_ykgAb4yd1jxW/Z8ykgA84ibv2gIhon_3UD1@v/WqrV/Yf7Qg;@SgyC4M0@5n0o?8fXp0@4MM8?fegwYc1WqDV/ZC3N@4}18yMQVfw?i8Js961cySgAq4ybwg,0,ezjgzj3DM3U82@L/i8S498:18yMQcfw?i8B49420Kmc1:3UkK@L/iofY.@4Ggo0<S9VkS5V0@4eMo0<Gdd2J8ytx5cuhCbwYvx[i8D2i8f?o7y/Yf?@TB54<;ig7ki3DMtudcyurF5vH/MYv0bI1:Y4wfMhF8yMSnfg0.rM1:Wl_V/Yf7Q?i8Jic4O9M4zTS4y3Ww58yMRPfg?i3DO3Uca0M?i8C12<0<6Y.;4yb3loZ0,azggCi3D7sMp8avt9yvNcyufMi0_16kyb3jwZ0,8yU4g.?i3Do3UfX@f/j8D2j8D0ifvqY4wfIp48.?i8Id3PQ?eDt@f/pyUf7Ug}4yb1vAY?3MwQ0o0kydfoQx?3Em9f/Yq05]6gi8I5SjM0<yby0,0,8esJPl4y9O4wFS4y9h2gUj3Dw3Ufd:j8DMgoJ_1bEg:j8DKi2D8i8Cc98:18yogAy:4y9j2h8j8BI943Ey9b/Qybj2h8i8fU40@4Mg80<yb1n8Y;fJA0Fxc0fxpo2?2b1g0O;N_XH//_grw1:grA1:Lw8;18NUgAxw{29x2i]yMnbcg?pECY98U;1cyuZCh8C498g;29x2i8:pAi9z2ic:W6qg/ZCwXMAxw:1ReSq3L2ie}@43f/_Qydfokw?3Ek9b/U2U5}fxtc10,dxugfxq_Z/YNS@AzZ/_3NY0yPRqcg?i8RQ962W2:ewXAf/pEeY98U]3UiY_L/WWVCbwYvx[i8I5yjI?f23g1w1KM4;11L<;11Lw4;18zjQc8;Wduh/_5@u_0hj7rpECs98g;1yYnY8vUgAxw;6p4ypMABw;6p4yqgAz:6p4yrgAB:cq05]6b1skM?29x2i]yMmQc;yogAy:46b1UC499:3HeMYvh;KL//@@0M;4O9X@xez/_ZEgABw:5RdSq3L2i6}@5zg4?6q3L2ie]7kti8I5MPE0<ybw0,0,8yNmRew?i8Iii3D2sWR8zjR67M?W16h/@0K1g]3UimZL/i8I5zjE0<y5M7gbyR0oxt8fxmQ20,8zjQm7M?We6g/YNSYq05]3FM_n/MYv<y9YE7y/Yf<gfJVhh,;bE1:j8J926p5xt9c3Qjict99Z_aWg:4wVQ4wfhY9dxsCW.;4MfhcFcesxc3Qr8K<;1dysNdxsBc3QjwWq_Y/Yf7Qg0<yb3vAV0,8xsBQ2UJ168n03Umi:i8QZwxU?exdAf/NE0k]eD@_v/A4wFSrw]ioDcj0Z8UeDg_v/3NZ?8IZkyY0<ydt2hwKww;18NQgAo<;3ECE/_Qy3@fYfx3410,8zjQF7w?Wfif/Z8yMRZeg?wbwk}@4KM;4y5Og@4GM;4Obp2gUyQ4oxs0fx6X//MwSAo0uBA//3NZ4?2bfu8K0,8zngAmbE8:Wced/_FwvX/Sof7Qg0<yb1i4V?21U/_3M0NQAy@////_TZ88Xjo,0w0ezyzf/i8fU_M@5WLD/UI5@zw?8n03Ujs@v/Wdme/YNSUIUW4Oe/Z8yNll7w?i8QRDDD/QybeAy9Mz70Wd6d/_FIfD/Yq05]1cySgAeeCA@L/W2qd/Z8yQMAc4yb<ybigx83XUhi8Bc923Sh5,20@5VvD/UfX0w@4JLf/Qybh2gMKwE:NZAybu13E68T/UB492PFT_D/Qib5m0U0,5xt8fxb_@/_EeEX/UIUWbed/ZczglIsL/Kss40,8zhn9tL/ioD1i8I5FxQ0<yddstU/Z8yPwNMewBzv/Wo3@/_MwSwo0uC9_v/pwYvh;i8I5@js?f18wSw80rI2:3Ujs@f/i8JY9218zjkasL/KM4;3E8E/_@D1@f/Kz:1CypgAw:eCe@f/Kj:1CyoMAw:eDYZL/Y4y3gh?Lz:1CyrgAw:eBAZv/i8fU0ngTioD5i8S498:18ykgAgeCi@v/ioJv44CbvNyW2w;37Si8Bs923E3oP/UB492PFRfz/Qydx2i]i8B49418yX48.?i8Dq3Xq1oM4?87y/Yf<y5ZDV1i8eYQg.8;u3q4M7lXY4w1sh11Lg4;3Fxff/MYvg,8yTMAgeDeZ/_i8JQ943Fhfr/Qybt2h0WrHQ/YfJXhh,;8j0tiN9yvh1Lg4;3FeLf/QkNM37iWpnR/Z5cs0NQKAbZf/hj79ctbF0vv/Q6Z.;46Y.;eAbY/_Y4y3gh,WU9C3N@4}1lLg4;1ji8fI64ydt2gcWcK9/Z8ysd8wPw0t4t8zjQb6M?Wdqc/@0K1g]t318yMlmdw?i8n0t16bk1y5QDgaY8dE6<f7Qg0<ydftAq?3EF8P/Yq05}NXky9T@zzyf/i8f468DEmRT3pyUf7Ug}5mZ.;5d8w@MEi8RQ91PEiUD/Qy9MQy3e?fxaY;2bl2gsw_E13UWy:i8JE24yddg1S/@9l2gci8DLWaGb/@bl2gcxs0fx9o;18zjmWr/_i8DLW8@b/@5M7lGi8IJF3k0<ydfjQq?3E28P/U2U5]1QcAy5XngqyQkoxs1Q4_23rhw1i8IJtPk;Yvw]18zjQ96w?Wdib/_6w1g]Y4y3rgw1i8QZY1A?eyXy/_NU<://_P7Ji8DvWfu7/Z8wYgEyuxrnsdC3NZ40,8yMkxdg?Y4y3g0w1w_E2tdnEAoD/QybuN18yM183XUnZAhg.xQLHEa:cvrEEUD/Qy9NkydfoAp?3El8L/UCE1:37JWVJCbwYvx[glt1lBlji8fIi4ydt2gsW0O8/Z8ysd8wPw0t0R8oSMA78R5_ofU0DouLg4;18yt_Emov/Qy3N4y9W5JtglV1nYcf7Q?i8JX2bEa:cvrEa8D/QybuN2W2w;37SgoD6W3m9/Z9ysu3_gcfx9A;18yTIoi8QRsD3/Qy9v2g8W2ia/YNQEn0t1V8yTMA24yddtFO/_E3oH/XE2:xs0fxpw;1cyvV4yvvEZov/Qy3@fYfx6n/_Z8zmPH@4yblg20ew1QlQOdh2gwi8D1Ly]NM4O9NQyd5jJP/ZcykgA2exqx/_i8JZ<ybt2g8cuTE6EL/@AA//3NZ4?2W.;4y9NAi9Z@ygx/_i8fU_M@40f/_Qy9NAydfsdO/YNM37JW3e9/_FXvX/Sof7Qg?bE1:WlX/_Yf7M1CpyUf7Ug}45mlld8w@Mgi8RQ90PEHEr/Qy9MQy3e,Q1UdY90M2vNWZ.;4y9T@w1xL/i8f448DEmRR1nIdC3NZ40,8yTw8cvqW2w;ezgx/_i8JH44yddmhN/Z1ysp8yu_EWEz/Un0t4V8zjmhsf/i8DLWdu8/@5M7hji8QR06X/Qy9X@z4yf/xs1Qm4yddvtK/Z8yu_EIoz/Un0tlR4yvsNXuxjyf/Wnn/_ZC3NZ4?2@.;4i9ZP7JW8C7/_Fm//MYvg?NZAi9ZP7JW7i7/_FhL/_MYvw]2@0w;4i9ZP7JW5C7/_Fa//MYvg,8yuV8zjRfr/_cs3EnUn/@Ac//pyUf7Ug}45mlld8w@Mgi8RQ90PEzEn/Qy9Nky3e?fx443?23v2gc.@e1w80<ybg0x8yst9ysrEVUj/Qy9MQy5M0@4@M8?fp0a.fxeA2;NOj7Si8Ql_S/_Qy9T@wuxv/csC@.;4y9TQyd5gRH/_E28n/P79Lw8;18ytZ8zhljsf/Wfa4/YNOrU3:i8Dvi8QlmT7/@zsxf/csC@1:4y9TQyd5mlH/_ENEj/P79Lwk;18ytZ8zhkSsf/Wb24/YNOrU6:i8Dvi8QlhmL/@yqxf/csC@>;4y9TQyd5sVL/_Ex8j/P79Lww;18ytZ8zhmvsf/W6W4/YNOrU9:i8Dvi8QlqT3/@xoxf/csC@2w;4y9TQyd5t1H/_EgEj/P79LwI;18ytZ8zhk9rf/W2O4/YNOrUc:i8Dvi8QldmT/@wmxf/csC@3g;4y9TQyd5jNG/_E08j/P79LwU;18ytZ8zhkarL/WeG3/YNOrUf:i8Dvi8QlaCH/@zkw/_csC@4:4y9TQyd5lpI/_ELEf/P79Lx4;18ytZ8zhl9q/_Way3/YNOrUi:i8Dvi8Ql3SH/@yiw/_csC@4M;4y9TQyd5jBI/_Ev8f/P79Lxg;18ytZ8zhnpqL/W6q3/YNSQy9X@zIwL/i8f448DomRR1nIegi8QZ8CX/@yQw/_i8QZfmD/@yEw/_i8QZzmX/@ysw/_i8QZDS/_@ygw/_i8QZISD/@y4w/_i8QZzCX/@xUw/_i8QZFSD/@xIw/_i8QZeCX/@xww/_i8QZ5m/_@xkw/_i8QZWSX/@x8w/_i8QZmCH/@wYw/_i8QZDmH/@wMw/_i8QZQSL/@wAw/_i8QZV6z/@wow/_i8QZL6P/@wcw/_i8QZVCz/@w0w/_i8QZ76L/@zQwL/i8QZ6mH/@zEwL/i8QZWmz/@zswL/i8QZ7mL/@zgwL/i8QZNSD/@z4wL/WuD@/Yf7U}j8DTW522/ZcyvvE68b/Qy9MQy5M0@5@_P/V1CpyUf7Ug}bI1:Wrb@/ZC3NZ40,8w@M8i8IZDhc?bU1:W2K2/Z8yPSk4M?Lw4;3E6Eb/QybfoIj?2@.;ew9wL/i8IZwxc?bU1:Wfy1/Z8yPRV4M?Lw4;3EVU7/Qybfn0j?2@.;ezmwv/i8IZpNc?bU1:Wcm1/Z8yPRu4M?Lw4;3EJ87/Qybflkj?2@.;eyzwv/i8IZj1c?bU1:W9a1/Z8yPR34M?Lw4;3Ewo7/QybfjEj?2@.;exMwv/i8IZchc?bU1:W5@1/Z8yPQE4M?Lw4;3EjE7/QybfhYj?2@.;ewZwv/i8IZ5xc?bU1:W2O1/Z8yPQd4M?Lw4;3E6U7/Qybfggj?2@.;ewawv/i8IZ@N8?bU1:WfC0/Z8yPTO4w?Lw4;3EW83/QybfuAi?2@.;eznwf/i8IZU18?bU1:Wcq0/YNM4y3N0z3+f/////UdI{1-4-g+b-s+i1c{8+60f{2g+o+1s+G28{2+d05{5-7-c+4fs{6+d03{2M+o-k+s0M{a+3A5{6g{30Tg[1I+2-q+bzt{7-8+f3/SY]Gx4[3@/ZL]6gi{//rM]2-M+A4I{d+81b{ZvX_rM]U0M~~~(31g{s5~~~~~~~~&f/////////////]f/////Yzk[1ecM#2Nd{a0W!0QS{bjo!xzk[2jdg#1Rd{1AU!cQU{Jzc!Ljg[2Ncw#1vdM[7IS!0cU{BP8!Gjg{ddM#>dM[5QU!akP{ejk!Szc[1vdw#2le{3sP!fUS{o3I!Zjs{6cM!Te{e4T!cQS{rj8!kPo[2Te!28dw[9gS!ecO{o38!fzA[3fdg#3Fd{e36+g{3wXw[4UP~Pzc[2gI+4-eY[2wew`1wR{QaU{1+23L{bjo`3ocw[c35+g{10XM[9cR~_3c{gHw{4+oeY{pe~fcQ{oaQ{1+83L{Jzc`2Ncw[12J+g{2wXM[b4O~uPo{wGw{4+MeY[1Xdw`9sO{QaA{1+e3L{BP8`1Wdg[634+g-Y+QT~e3g{gGg{4+8f{1te~eAP{Maw{1+43M{ejk`1Ke{72E+g{1wY{5YS~z3w[3gF+4+wf+TcM`akT{wag{1+a3M{o3I~6cM[42A+g{30Y+oP~Ujs[2wMw{4+Uf{3xdM`fEO{8cc{1-3N{rj8`3qe{12Q+g+wYg[bsU~L3s[3MEM{4+gf4[2kdw`60O{sb8{1+63N{o38~VdM[a2z+g{20Yg[cYR*3ESM#2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{I4I[2MiM[b1b{2:1[g?hQ4A0jdxcg20iM[8Rb{2:1[g?hQ4A0jdxcg2giM[7Bg{hQd3ey0EhQVlai0NdiUObz4wcz0Odj4Ocj4wa59Bp218ongwcjkKcyUNbjkF06RLr6gwcyUQc2UQ82xzrSRMonhFoCNB87tFt6wwhQVl86NAag;2VPq7dQsDhxow0KrCZQpiVDrDkKs79Ls6lOt7A0bCVLt6kKpSVRbC9RqmNAbmBA02VDrDkKq65Pq?Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bClEnSpOomRB02VBq5ZCsC5JplZEp780bD9Lp65Qog0KsCZAonhxbCdPt34S02VOrShxt64KoTdQcP80bD9Lp65QoiVPt78Nbz40bD9Lp65QoiVPt78Nbzw0bCpFrCA0bCBKqng0bD1It2VDrTg0bDhBu7g0bDhAonhx02VQoDdP02VAonhxbD9Br2VOrM0Kp7BKomRFoM0KpCBKqlZxsD9xug0KqmVFt5ZxsD9xug0KsClIsCZvs65Ap6BKpM0Kp65Qog0KpSZQbD1It?Kt6RvoSNLrClvt65yr6k0bC9PsM0KpSVRbC9RqmNAbC5Qt79FoDlQpnc0bCdLrmRBrDg~~(0b:>:8+U08[3w0w[3%8^7w:s:2+103{40c{A^1^34;3S/ZL0w+U0M[3w3{C-4-w^X:2M:8+Q0c[3g0M[a08{1g:4:8+1w+gM:c:2+70c{s0M{V1g&g&4I;3/_ZL0w{2G4g[aEh{K-4-8-w{1o:_L/rM8+p18[1A4w[e-1g:8:4^pM:g:2+4wj{i1c[1w3M{g+2-o+74:4:gw{2E8w[awy{Q0k{4:7M:w+6+1X]g:8+u2w[1Ua{7g7&8^xg:4:2+eML{X2Y{s.*1^9c:1]w{10cg[40N{M^4^2r]g;18-38+cw[3%g+1-Gg:4:i+40O{g38{w^8-w+bs:1:cw{1wcw[60O{_wo&4-g{36]g;38+o3A[1weg[202&8-4+Rg:4:6+81b{w3I{d^1^dI:1:1w{2giM[90X{6M^g&1S]g:o+I4I[2MeM+4&g^Ug:4:6+b1f{I3Y{8^4^eE:1:1w{30jM[c0_{4nM*4^3M]g:c4{SdI[3oKM{w^4^ZM:w:31{e3r{UbI{d^2^fQ:1]M{3wSM[e2X{2%w^a.0,w:c+WdI[3EKM[d,{1g+8+1-4M4;Y:3+bzt{KbQ{8^2-8+1Y1;e]M{30Tg[c2Z{2%w+2+3B]g:c+OdQ[38Lg[fw^8^aM4;w:3+c3u{MbU[10.&g&3E1;1]M{30Xw[c2@{k0w*2^10.;g:c+4fs{gNM{w2&8^ig4;4:3+1zV{6cA!2^5A1;8]M+o@g[1z9{9%w&1u.0,M$oOg[4w^4^t<;4:M^ocA[1k%g+1-4:3$bj9{vg4&4&')


_forkrun_bootstrap_setup --force

