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
        { ${FORKRUN_RING_ENABLED:-false} && (( ${FORKRUN_MEMFD_LOADABLES:-0} > 0 )); } || _forkrun_bootstrap_setup --fast

        # Generate list of loadables to enable in the new shell
        (( ${#ring_funcs[@]} > 0 )) || ring_list 'ring_funcs'
        printf -v ring_enable '%s ' "${ring_funcs[@]}"

        [[ ${FORKRUN_FRUN_SRC} ]] || FORKRUN_FRUN_SRC="$(declare -f frun)"

        # EXEC into Clean Room
        # /proc/self/fd/ is safer than $BASHPID in some namespace contexts
        exec -c "${BASH:-bash}" --norc --noprofile -c 'enable -f "/proc/self/fd/'"${FORKRUN_MEMFD_LOADABLES}"'" '"${ring_enable}"' ring_list
export LC_ALL=C
set +m
shopt -s extglob
'"${FORKRUN_FRUN_SRC}"'
frun __exec__ "$@"
' -- "${@}" 0<&${fd00} 1>&${fd11} 2>&${fd22}

        # (Exec replaces process, so we never reach here)
    }
    # 2. WORKER LOGIC (Clean Shell)
    shift 1 # Remove __exec__

    # # # # # SETUP # # # # #
    local cmdline_str ring_ack_str done_str delimiter_val pCode extglob_was_set worker_func_src nn N nWorkers0 arg fd0 fd1 fd2
    local -g fd_spawn_r fd_spawn_w fd_fallow_r fd_fallow_w fd_order_r fd_order_w ingress_memfd fd_write fd_scan nWorkers nWorkersMax tStart
    local -gx order_mode unsafe_flag stdin_flag byte_mode_flag order_mode unsafe_flag LC_ALL
    local -ga fd_out P order_args ring_init_opts

    LC_ALL=C
    set +m

    if shopt -q extglob; then
        extglob_was_set=true;
    else
        shopt -s extglob;
    fi

    _expand_unit() {
        local val iec num p
        val="${1,,}"
        iec=false
        [[ "${val#[+-]}" == '0' ]] && { REPLY="${val}"; return 0; }
        [[ "${val}" == +* ]] && { iec=true; val="${val#+}"; }
        num="${val//[^0-9]/}"
        [[ $num ]] || if [[ ${val} ]]; then return 1; else REPLY=''; return 0; fi
        { [[ "${num}" == "${val}" ]] || [[ -z ${num} ]]; } && { REPLY="${num}"; return 0; }
        [[ "${val}" == *i* ]] && iec=true
        p=0
        case "${val}" in
            *k*) p=1 ;; *m*) p=2 ;; *g*) p=3 ;; *t*) p=4 ;; *p*) p=5 ;; *e*) p=6 ;;
        esac
        if ${iec}; then REPLY="${val[0]//[^-]/}$(( num << (10 * p) ))"; else REPLY="${val[0]//[^-]/}$(( num * (1000 ** p) ))"; fi
        return 0
    }

    # --- HELPER: Parse Ranges (N, N:M, :M, N:) ---
    _parse_count() {
        local type val v1 v2
        case "$1" in
            lines|bytes|workers)  type="$1"  ;;
            *)  return 1  ;;
        esac
        val="$2"
        if [[ "$val" == *:* ]]; then
            v1="${val%:*}"; v2="${val#*:}"

            _expand_unit "$v1"; ring_init_opts+=("--${type}0=${REPLY}");
            [[ $REPLY ]] && case "${type}" in
                lines)    byte_mode_flag=false   ;;
                bytes)    byte_mode_flag=true    ;;
            esac

            _expand_unit "$v2"; ring_init_opts+=("--${type}-max=${REPLY}")
            [[ $REPLY ]] && case "${type}" in
                workers)  nWorkersMax="${REPLY}" ;;
                lines)    byte_mode_flag=false   ;;
            esac
         else
            _expand_unit "$val"; ring_init_opts+=("--${type}=${REPLY}")
            case "${type}" in
                workers)  [[ $REPLY ]] && nWorkersMax="${REPLY}" ;;
                lines)    byte_mode_flag=false   ;;
                bytes)    byte_mode_flag=true    ;;
            esac
         fi
        return 0
    }

    # Config Vars
    order_mode='buffered'
    unsafe_flag=false
    byte_mode_flag=false
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

            # --- LIMIT (-n 100) ---
            @(-n|--limit)?(?([= $'\t'])+([0-9+-])))
                arg="${1#@(-n|--limit)?([= $'\t'])}";
                [[ ${arg}${2//+([0-9+-])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _expand_unit "${arg}" && ring_init_opts+=('--limit='"$REPLY") ;;

            # --- LINES / BATCH (-l 1k or -l 100:1k) ---
            @(-l|--lines|--batchsize)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1#@(-l|--lines|--batchsize)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _parse_count "lines" "${arg}" ;;

            # --- BYTES (-b 1M) ---
            @(-b|--bytes)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1#@(-b|--bytes)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                _parse_count "bytes" "${arg:-}" && ring_init_opts+=("--return-bytes") ;;

            # --- WORKERS (-j 4 or -j 1:8) ---
            @(-j|-P|--workers)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1#@(-j|-P|--workers)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _parse_count "workers" "${arg}" ;;

            # --- TIMEOUT (-t 5000) ---
            @(-t|--timeout)?(?([= $'\t'])+([0-9.+-])))
                arg="${1#@(-t|--timeout)?([= $'\t'])}";
                [[ ${arg}${2//+([0-9.+-])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _expand_unit "${arg}" && ring_init_opts+=('--timeout='"${REPLY}") ;;

            # --- NUMA NODES (--nodes auto) ---
            @(--nodes)?(?([= $'\t'])*))
                arg="${1#@(--nodes)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && ring_init_opts+=("--nodes=${arg}") ;;

            # --- ORDER (-o buffered) ---
            @(-o|--order)?(?([= $'\t'])@(realtime|unbuffered|buffered|atomic|order?(ed))))
                arg="${1#@(-o|--order)?([= $'\t'])}";
                [[ ${arg}${2//@(realtime|unbuffered|buffered|atomic|order?(ed))/} ]] || { shift; arg="$1"; }
                case "${arg}" in
                    realtime|unbuffered) order_mode='realtime' ;;
                    buffered|atomic)     order_mode='buffered' ;;
                    order|ordered|'')    order_mode='ordered'  ;;
                    *)                   order_mode='buffered' ;;
                esac  ;;

            # --- DELIMITER (-d x) ---
            @(-d|--delim|--delimiter)?(?([= $'\t'])*))
                arg="${1#@(-d|--delim|--delimiter)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
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
    [[ -z ${stdin_flag} ]] && {
        if ${byte_mode_flag:-false}; then
           stdin_flag=true
        else
           stdin_flag=false
        fi
    }

    if ${stdin_flag:-false}; then
        unsafe_flag=false
        ring_init_opts+=('--stdin')
    elif ${byte_mode_flag:-false}; then
        : "${stdin_flag:=true}"
        ring_init_opts+=('--stdin')
    elif ${unsafe_flag:-false}; then
        stdin_flag=false
    fi

    ${byte_mode_flag:-false} && ring_init_opts+=('--lines=x')

    [[ "${order_mode}" == "realtime" ]] || ring_init_opts+=('--out=fd_out')

    # Initialize Ring (this exports FORKRUN_NUM_NODES)
    ring_init "${ring_init_opts[@]}"
    : "${FORKRUN_NUM_NODES:=1}" # Fallback safety

    # Create Data Memfd
    ring_memfd_create ingress_memfd

    # # # # # MAIN # # # # #
    {
        ring_pipe fd_spawn_r fd_spawn_w

        # --- 1 & 2. THE PRODUCER PLUMBING ---
        if (( FORKRUN_NUM_NODES > 1 )); then
            # NUMA TOPOLOGICAL PIPELINE
            ring_pipe index_pipe_r index_pipe_w
            ring_pipe claim_pipe_r claim_pipe_w

            node_pipes_r=()
            node_pipes_w=()
            for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                ring_pipe nr nw
                node_pipes_r[i]=$nr
                node_pipes_w[i]=$nw
            done

            ordered_flag=0
            [[ "${order_mode}" == "ordered" ]] && ordered_flag=1

            ( ring_numa_ingest ${fd0} ${fd_write} $index_pipe_w $claim_pipe_r $FORKRUN_NUM_NODES $ordered_flag ) &
            ( ring_indexer_numa ${fd_scan} $index_pipe_r "${node_pipes_w[@]}" ) &

            for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                ( ring_numa_scanner ${fd_scan} $i $claim_pipe_w $fd_spawn_w $FORKRUN_NUM_NODES "${node_pipes_r[@]}" ) &
            done

            # Close Bash's copies of the pipes to allow background EOFs to cascade
            exec {index_pipe_r}<&- {index_pipe_w}>&- {claim_pipe_r}<&- {claim_pipe_w}>&-
            for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                exec {node_pipes_w[i]}>&- {node_pipes_r[i]}<&-
            done

        else
            # LEGACY FLAT PIPELINE
            ( ring_copy ${fd_write} ${fd0}; ring_signal ) &
            (
                exec {fd_spawn_r}<&-
                ring_scanner ${fd_scan} ${fd_spawn_w}
            ) &
        fi

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
                (( FORKRUN_NUM_NODES > 1 )) && order_args+=( "numa" )

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
           : "${RING_BYTES_MAX:=1000000000}" "${RING_PIPE_CAPACITY:=65536}"

            if (( RING_BYTES_MAX < RING_PIPE_CAPACITY )); then
            pCode='
                ring_pipe pr pw
                ring_splice $fd_read $pw '"''"' $REPLY "close" 2>/dev/null || break
                '"$cmdline_str"' <&$pr
                exec {pr}>&-'
            else
            pCode='
            if (( REPLY < 1048576 )); then
                ring_pipe pr pw
                ring_splice $fd_read $pw "" $REPLY "close" 2>/dev/null || break
                '"$cmdline_str"' <&$pr
                exec {pr}>&-
            else
                ( ring_splice $fd_read 1 '"''"' $REPLY "close" ) | '"$cmdline_str"'
            fi'
            fi

        elif ${byte_mode_flag}; then
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
  export RING_NODE_ID="$2"
  {
    ID="$1"
    shift 2
    ring_worker inc $fd_read
    while ring_claim; do
        [[ "$REPLY" == "0" ]] && break
        '"$pCode"'
        '"${ring_ack_str}"'
    done
    ring_worker dec
  } {fd_read}<"/proc/self/fd/'"${ingress_memfd}"'" 1>&${fd1} 2>&${fd2}
) &
P+=($!)
}'

        eval "${worker_func_src}"

        # --- SPAWN LOOP ---
        nWorkers=0
        node_idx=0
        while true; do
            read -r -u $fd_spawn_r N
            [[ "$N" == 'x' ]] && break

            target=$(( nWorkers + N ))
            (( target > nWorkersMax )) && target=$nWorkersMax

            for (( ; nWorkers < target; nWorkers++ )); do
                spawn_worker "$nWorkers" "$node_idx"
                node_idx=$(( (node_idx + 1) % FORKRUN_NUM_NODES ))
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
            ARCH='x86_64_v4'
        elif grep -qF 'avx2' </proc/cpuinfo; then
            ARCH='x86_64_v3'
        else
            ARCH='x86_64_v2'
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
        [[ -f "$1" ]] && \rm -f "$1" &>/dev/null
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

        printf -v b '%06X' "${b1}"          # always generate full 6 hex digits first

        (( outN < 6 )) && b="${b:0:$outN}"  # then slice only if it's the final group

        (( outN = outN - ${#b} ))           # subtract actual hex digits used
        printf -v outC '\\x%s' ${b:0:2} ${b:2:2} ${b:4:2}
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

    { (( ${#FUNCNAME[@]} > 1 )) && [[ "${FUNCNAME[1]}" == '_forkrun_bootstrap_setup' ]]; } || shopt ${extglobState} extglob
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
                truncate -s "${b64[$ARCH]%% *}" "${tmp_so}" && if _forkrun_base64_to_file <<<"${b64[$ARCH]}" "$tmp_so"; then
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
        export FORKRUN_MEMFD_LOADABLES_BASE64="${FORKRUN_MEMFD_LOADABLES_BASE64}"
        declare -p b64 >&${FORKRUN_MEMFD_LOADABLES_BASE64}
        ring_seal "${FORKRUN_MEMFD_LOADABLES_BASE64}"
        need_memfd_b64_flag=false
    fi

    # open a memfd, extract loadable .so to it, and seal it
    ${force_flag} && ${have_memfd_loadables_flag} && exec {FORKRUN_MEMFD_LOADABLES}>&-
    unset "FORKRUN_MEMFD_LOADABLES"
    ring_memfd_create 'FORKRUN_MEMFD_LOADABLES'
    export FORKRUN_MEMFD_LOADABLES="${FORKRUN_MEMFD_LOADABLES}"
    truncate -s "${b64[$ARCH]%% *}" "/proc/self/fd/${FORKRUN_MEMFD_LOADABLES}"
    _forkrun_base64_to_file <<<"${b64[$ARCH]}" "/proc/self/fd/${FORKRUN_MEMFD_LOADABLES}"
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
    enable -f "/proc/self/fd/${FORKRUN_MEMFD_LOADABLES}" "${ring_funcs[@]}" ring_list

    # clear massive b64 array
    unset "b64"

    return 0
}



_forkrun_file_to_base64() {

   # local nn kk kk0 k1 k2 out out0 outF outN v1 v2 nnSum hexProg quoteFlag noCompressFlag IFS IFS0
    local -I extglobState

 #   local -a charmap compressI compressV outA nnSumA
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
        : "${testFlag:=true}"
        compressI=('~' '`' '!' '#' '$' '%' '^' '&' '*' '(' ')' '-' '+' '=' '{' '[' '}' ']' ':' ';' '<' ',' '>' '.' '?' '/' '|')
        compressV=()
        kk=0
        for kk0 in 7 6 5 4 3; do
        mapfile -t compressV0 < <({ sed -E 's/(00+)(([^0]+0?[^0]+)*)/\1\n\2/g; s/([^0]+)/\1\n/g' <<<"${out}"; sed -E 's/^((....)*).*$/\1/; s/^(.)(.)(.)(.*)$/\1\2\3\4 \2\3\4  \3\4   \4   /; s/(....)/\1\n/g' <<<"${out}" | sed -zE 's/^(....)\n/\1\n\1\n/; s/\n(....)\n(....)\n(....)/\1\n\1\n\1\2\n\2\n\2\3\n\3\n\3/g'; X="${out:0:1}"; while read -r -N 1 x; do if [[ "$x" == "${X: -1}" ]] && (( ${#X} < 32 )); then X+="$x"; else (( ${#X} > 1 )) && echo "$X"; X="$x"; fi; done <<<"$out"; } | grep -E '..' | sort | uniq -c | sed -E 's/^[ \t]+//' | grep -vE '^1 ' | sort -nr -k1,1 | while read -r v1 v2; do (( v0 = v1 * ${#v2} - v1 - ${#v2} )); printf '%s %s %s %s\n' "$v0" "${#v2}" "$v1" "$v2"; done | grep -vE '^-' | sort -nr -k 1,1 | head -n $kk0 | sort -nr -k2,2 | sed -E 's/^([0-9]+ ){3}//')
        compressV+=("${compressV0[@]}")
        for (( ; kk<${#compressV[@]}; kk++)); do
            out="${out//"${compressV[$kk]}"/"${compressI[$kk]}"}"
        done
        done

        # 2 final compression runs where we re-generate the list of possible replacements and expand it to also look for simple repeated chars (with a limit of a maximum of 32 chars)
        for kk0 in 1 2; do
            compressV[$kk]="$({ { sed -E 's/(00+)(([^0]+0?[^0]+)*)/\1\n\2/g; s/([^0]+)/\1\n/g' <<<"${out}"; sed -E 's/^((....)*).*$/\1/; s/^(.)(.)(.)(.*)$/\1\2\3\4 \2\3\4  \3\4   \4   /; s/(....)/\1\n/g' <<<"${out}" | sed -zE 's/^(....)\n/\1\n\1\n/; s/\n(....)\n(....)\n(....)/\1\n\1\n\1\2\n\2\n\2\3\n\3\n\3/g'; X="${out:0:1}"; while read -r -N 1 x; do if [[ "$x" == "${X: -1}" ]] && (( ${#X} < 32 )); then X+="$x"; else (( ${#X} > 1 )) && echo "$X"; X="$x"; fi; done <<<"$out"; } | grep -E '..' | sort | uniq -c | sed -E 's/^[ \t]+//'; { read -r -N 1 y; while read -r -N 1 x; do if [[ "$x" == "${y: -1}" ]]; then y+="$x"; else echo "$y"; read -r -N 1 y; fi; done; } <<<"${out}" | grep -E '..' | sort | uniq -c| sed -E 's/^[ \t]+//' | while read -r v1 v2; do if ((${#v2} > 32 )); then (( v1 = v1 * ( ${#v2} / 32 ) )); v2="${v2:0:32}"; fi; printf '%s %s\n' "$v1" "$v2"; done } | grep -vE '^1 '   | sort -nr -k1,1 | while read -r v1 v2; do (( v0 = v1 * ${#v2} - v1 - ${#v2} )); printf '%s %s %s %s\n' "$v0" "${#v2}" "$v1" "$v2"; done | grep -vE '^-' | sort -nr -k 1,1 | head -n 1 | sed -E 's/^([0-9]+ ){3}//')"
            out="${out//"${compressV[$kk]}"/"${compressI[$kk]}"}"
            ((kk++))
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

FORKRUN_FRUN_SRC="$(declare -f frun)"
unset "b64"

# <@@@@@< _BASE64_START_ >@@@@@> #

declare -a b64=([0]=$'173040 86520\nmd5sum:16c54adc72dc5605e2f493fd1333183e\nsha256sum:be65efe982a5eae42e0411f318cedd6c80c3f7f4df2aaa301362330437902a0f\n00000000000000000000000000000000\n000000000000000000\n00000000\n00000001\n0000\n000\n00\n~~~~~~~~\nVv__\nen__\n0Vv_\n3B__\n__\n1Ms71Ms7\n!^c#\nKgg0\nbA40\n1Ms7\nTdQsDlzt\ng%41_4d4\necg40M05\n01!$\nN0;<c3Q+\ncg4%10vN\nKhg0\nz410c01j\nh3/0Zf+_\034vQlchw820g!$0301o$1`^g!kGU$^1^3w0201^1Q07$04$5~#bkw$%4Ji!1$%g$o$%4YE!jOw#fa!0cI!0QM!4$^2$1w$%jQ8#fgw$%4Z2!07g!0t!^2$0g$4!0w!02!^8!^2g!09!^4$1M$g$%4YE!jOw#fa!^3!01!%xAtelg$1!h_o#7Zw$%4vS!05Q!0ng!016hQVl4$6~`!$0gp7jBkw$g$%4YE!jOw#fa!03o!0dw!^4$4$5$0d7jBk0EES@eGiWz6H0zPW3r@uiBEnc8yM!04g%4o$4$2^o45h8w0i0qgy0w21Q21E01%qE20wg6k21080806$hw!19$iw%4I%1c$jw%54%1k$lw%5w%1p$ng%5U%1v!061OzQ5UkiUUYy8wXRu7O4sDFWo@lkZT6PeH3QhYJGRTMRb56_i4BajO81ZHMh0H08ofKmgue_61P@UiMRg_PDJbX9pQ8GESlnTvHzavDKyab9Th7xpHCK8yTWCPpZFcPVRnVBup5Rarwo@G7lc~$^M^2g$%2IE!$^6g4w`!^2Y4`!%168w`!^1B4w`!%g8`!%6x4`!%4R4g`!^4z4w`!^9K4w`!^8N4w`!^5W4g`!^2T4w`!^2L4w`!^9C4w`!^8m4w`!^6L4w`!^734`!%9f4w`!^4r4w`!^2S4`!%5F4w`!^434`!%8A4w`!^9R4w`!^614w`!^2D4`!%8F4w`!^2e4w`!^8_4w`!^5y4w`!^7T4w`!^5o4w`!^2E4w`!^b04w`!^7K4w`!^7u4`!$18`!%5g4w`!^7w4`!%7_4w`!^9r4w`!^an4w`!^2w4w`!^1@4w`!^624w`!^8M4w`!^1u4w`!^874w`!^4_4`!%3u4w`!^1l4w`!^8U4w`!^3L4`!%6@4w`!^a54`!%aE4w`!^7m4w`!^aL4w`!^684w`!^6S4w`!^974w`!%I8`!%4T4g`!^aT4w`!^bN4`!%1G4w`!^3a4`!%1M4w`!^iR4g^6!kjg!03$cB4g^6!kyg!03$g84g^6!kq!^3$iA4g^6!kk!^3$js4g^6!khM!03$fT4g^6!kqM!03$f24g^6!kt!^3$bZ4g^6!kzM!03$fB4g^6!krw!03$dm4g^6!kwM!03$b54w^2M$%gTM!0rw%gE4g^6!kow!03$dL4g^6!kw!^3$ii4g^6!kkM!03$hE4g^6!kmg!03$ek4g^6!kuw!03$ch4g^6!kz!^3$i14g^6!klw!03$j84g^6!kiw!03$bw4g^6!kAw!03$cZ4g^6!kxw!03$eL4g^6!ktM!03$fl4g^6!ksg!03$gr4g^6!kpg!03$gY4g^6!knM!03$hg4g^6!kn!^3$e14g^6!kvg!03^nRZDrmZKnTdQon9QnRY0nQBkjlZApn9BpSBPt6lOl4R3r6ZKplhxoCNB05Z9l4RvsClDqndQpn9kjkdIrSVBl65yr6k0nRZzu65vpCBKomNFuCk0sSVMsCBKt6o0rT1BrzoQ079Bomg0oSNLsSk0nRZzt7BMplZynSNLoM1vnSBPrScOcRZPt79QrSM0sSdEpmhvsSlQompCqmVFt7A0sThOoSxO07xJomNIrSc0rmlJoT1V07xCsClB06pFrChvtC5Oqm5yr6k0oCBKp5ZxsTdLoRZSon9Fom9Ipg1vnSlOsCVLnSNLoS5QqmZK069FrChvon9OonBvtC5Oqm5yr6k0rm5HplZKpntvon9OonBvtC5Oqm5yr6k0sTBPoSZKpw1vnSBPrScOcRZPt79QrTlIr01vnSlKtCBOrSU0pSlQnTdQsCBKpRZSomNRpg1PundzomNI06RHsThBrn0Sd01RrCNFrCI0nRZFsSZzczdvsThOt6ZIr01Pt6hBsD80pDtOqnhB07dQsCVzrn^nRZFsSZzczdvsThOt6ZRr01ytmBIt6BKnSlOsCZO06RJon0Sd01BtClKt6pA071Fs6k0oCBKp5ZxsD9xulZBr6lJpmVQ06pzrDhIdzg0tmVyqmVAnTpxsCBxoCNB07dQsClOsCZO071Opm5Adzg0rmlJsCdEsw1MrTdFu5ZJpmRxr6BDrw1zr6ZzqRZDpnhQqmRB071Lr6M0tndIpmlM06pMsCBKt6o0rmlJoSxO06NPpmlHdzg0pDdQongSd01ComNIrSdxt6kSd01PpmVApCBIpjoQ07dVsSBKpCY0sT1IqmdB06dLs7BvpCBIplZOomVDpg1JomJBnS9RqmNQqmVvon9Dtw1vnThIsRZDpnhvrSpCsSlQ06RRrCRxs01Ps79FrDhC07dEtnhArTtK071Rt7c0sSlQtn1voDlFr7hFrBZCrT9HsDlKnT9FrCs0sCBKpRZFrCBQn:01xp6hvoDlFr7hFrw1OqmVDnShBsThOrTBvsThOtmdQ079FrCtvsSdxrCVBsBZPt79RoTg0sCBKpRZKtmRxnSBKpSlPt5ZPt79RoTg0sCBKpRZFrChBu6lOnSVRrm5vsThOtmdQ079FrCtvrDlJolZPoS5KrClOn:01OqmVDnSdIomBJn:01OqmVDnTtLsCJBsBZPt79RoTg0sCBKpRZzr6lxrDlMnTtxqnhBsBZPt79RoTg0sCBKpRZFrCtBsThvsThOtmdQ079FrCtvpC5Ir6ZTn:01OqmVDnS5zqRZPt79RoTg0sCBKpRZLsChBsBZPt79RoTg0sCBKpRZzrT1Vn:01OqmVDnTdFpSVxr5ZPt79RoTg0r7dBpmJvsThOtmdQ079FrCtvqmVApnxBsBZPt79RoTg0sCBKpRZCpnhzq6lOn:01OqmVDnSpxr6NLtRZMq7BPn:01OqmVDnSRBrmpAnSdOpm5QplZPt79RoTg0sCBKpRZPpm5In:01OqmVDnSpzrDhIn:01OqmVDnT1Fs6lvsThOtmdQ079FrCtvsT1IqmdBn:01OqmVDnTpBsDdFrSVvsThOtmdQ079FrCtvr6BPt5ZPt79RoTg0r6ByoOVPrOUS06NAdzgKsSYKcg17j4B2gRYObzc0hQN9gAdvcyUPcM17j4B2gRYObzs0hQN9gAdvcyUOe017j4B2gRYObzcKd017j4B2gRYObz8T04tcik93nP8Kcj^hQN9gAdvcyUNdM17j4B2gRYObzg0hQN9gAdvcyUR04tcik93nP8Kcw17j4B2gRYObzcU!^8^g03^c^g01^c^w04^k^M03^c^M06^c^g07^c^g02^4^M08^c^g03^A^M03^c^M03^c^M01^4^M01^c02w0b^c^w03^k^M03^4^M05^c^g03^4^M0c^k^M0d^U^g03^c^g03^402w01^4^g01^4^g01^4^g01^4^g01^4^g01^4^g01^4^g01^4^g01^4^g$%g01%4ZM%1$0w3mBF4M$I%k1#^M%jJ$4$^6BF6P$3w^1gI$g3mBF5M$Q%km$40qmAow$c%58$10dqmAj$2w^1g4$g2mApt$0A%kH$40qmAos$8%5dM%106BF6g$1M^1k8$g1FqhBM$o%ld$40RFqhg$5%5m$10dqmAl$1%1m8$g3mBF4w$c%lI$40qmArw$2%5tw!$4YI!^c!d2!4YK!^c!cZ!4YM{fc!52!%c#6qM$%522{6rM$%526{6sM$%528{6u!52c{6w8$%52e{6wU$%52i{6zE$%52k{6Ao$%52o{6BU$%52q{6CM$%52u{6E8$%52w{6EU$%52A{6FU$%52C{6GM$%52G{6Ig$%52I{6kU$%52M{6Jg$%52O{6k!52S{6K8$%52U{6j8$%52Y{6L!52@{6Lw$%532{6Nw$%534{6Ow$%538{6PE$%53a{6QM$%53e{6S8$%53g{6T8$%53k{6VE$%53m{6Wg$%53q{6XM$%53s{6YM$%53w{6@M$%53y{6ew$%53C{6_E$%53E{6dg$%53I{70E$%53K{71E$%53O{73o$%53Q{748$%53U{75w$%53W{77g$%53@{7cw$%54!%c#7e!544{7ho$%546{7j8$%54a{7nM$%54c{7p!54g{7qU$%54i{66E$%54m{7rM$%54o{7tw$%54s{7uE$%54u{2s!54y{gw!54A{6rM$%54E{6pU$%54G{1Q!54K{gxw$%54M{6u!54Q{6p8$%54S!^c!SR!54W{gz!54Y{6wU$%55!%c#6ow$%552!^c!Sp!556{gAw$%558{6Ao$%55c{6nM$%55e{1w!55i{gC!55k{6CM$%55o{6n8$%55q!^c!Sc!55u{gDw$%55w{6EU$%55A{6m!55C!^c!R_!55G{gF!55I{6GM$%55M{6kU$%55O!^c!RU!55S{gGw$%55U{6kU$%55Y{6k!55@!^c!QX!562{gI!564{6k!568{6j8$%56a!^c!QQ!56e{gJw$%56g{6j8$%56k{6iM$%56m{17!56q{gL!56s{6Lw$%56w{6i!56y!^c!Qy!56C{gMw$%56E{6Ow$%56I{6ho$%56K!^c!Qr!56O{gO!56Q{6QM$%56U{6gE$%56W!^c!Qk!56@{gPw$%57!%c#6T8$%574{6g!576!^c!P8!57a{gR!57c{6Wg$%57g{6fg$%57i!^c!P1!57m{gSw$%57o{6YM$%57s{6ew$%57u!^c!OW!57y{gU!57A{6ew$%57E{6dg$%57G{06!57K{gVw$%57M{6dg$%57Q{6cw$%57S{0n!57W{gX!57Y{71E$%58!%c#6bM$%582!^c!T_!586{gYw$%588{748$%58c{6aE$%58e!^c!OP!58i{g@!58k{77g$%58o{69w$%58q!^c!OI!58u{g_w$%58w{7e!58A{68o$%58C!^c!N3!58G{h1!58I{7j8$%58M{67w$%58O!^c!MY!58S{h2w$%58U{7p!58Y{66E$%58@!^c!Tm!592{h4!594{66E$%598{66!59a!^c!MR!59e{h5w$%59g{7tw$%4@Y!^S`4_$05A$a`4_2$5g$a`4_4$0g$a`4_6$0o$a`4_8$4I$a`4_a$4U$a`4_c$0M$a`4_e$5k$a`4_g$4M$a`4_i$4Y$a`4_k$4o$a`4_m$54$a`4_o$5Q$a`4_q$58$a`4_s$4E$a`4_u$5Y$a`4_w$5w$a`4_y$5E$a`4_A$5o$a`4_C$2o$a`4_E$5I$a`4_G$4Q$a`4_I$4s$a`4_K$6$0a`4_M$4A$a`4_O$4w$a`4_Q$5s$a`4_S$5c$a`4_U$5M$a`4_W$3Y$a`4_Y$4$0a`4_@$5U$a`5$%8$b`502$0c$b`504$0g$b`506$0k$b`508$0s$b`50a$0A$b`50c$0E$b`50e$0I$b`50g$0Q$b`50i$0U$b`50k$0Y$b`50m$1$0b`50o$14$b`50q$18$b`50s$1c$b`50u$1g$b`50w$1k$b`50y$1o$b`50A$1s$b`50C$1w$b`50E$1A$b`50G$1E$b`50I$1I$b`50K$1M$b`50M$1Q$b`50O$1U$b`50Q$1Y$b`50S$2$0b`50U$24$b`50W$28$b`50Y$2c$b`50@$2g$b`51$02k$b`512$2s$b`514$2w$b`516$2A$b`518$2E$b`51a$2I$b`51c$2M$b`51e$2Q$b`51g$2U$b`51i$2Y$b`51k$3$0b`51m$34$b`51o$38$b`51q$3c$b`51s$3g$b`51u$3k$b`51w$3o$b`51y$3s$b`51A$3w$b`51C$3A$b`51E$3E$b`51G$3I$b`51I$3M$b`51K$3Q$b`51M$3U$b`51O$44$b`51Q$48$b`51S$4c$b`51U$4g$b`51W$4k$b!^3Hr_0M02iV1^vF_L_oecgY%9c3%29PI0g^2aa@cg4%1bA2016Dx^33u7zgf4g^jHr_3g^g7Z%UN3Me^AM1%8CRQwvMc108UN0g4^41_47^s01M304%yzPz41$g7YgQgUN0g3^kMfj++B$0c0g^2ace.3|Zk$oM1%8EAU>+Ng%3304%yxzz41$g7YgQgUN0g3^kMfj+_@R$ic0g^2a3e.3|Wk%1wM1%8E0U>+Bg%7z04%yvjz41$g7YgQgUN0g3^kMfj+_@5$Ac0g^29We.3|Tk%2EM1%8DsU>+pg%c304%yt3z41$g7YgQgUN0g3^kMfj+_Zl$Sc0g^29Ne.3|Qk%3MM1%8CUU>+dg%gz04%yqPz41$g7YgQgUN0g3^kMfj+_YB%18c0g^29Ee.3|Nk%4UM1%8CkU>+1g%l304%yozz41$g7YgQgUN0g3^kMfj+_XR%1qc0g^29ve.3|Kk%60M1%8BMU>_@Rg%pz04%ymjz41$g7YgQgUN0g3^kMfj+_X5%1Ic0g^29me.3|Hk%78M1%8BcU>_@Fg%u304%yk3z41$g7YgQgUN0g3^kMfj+_Wl%1@c0g^29de.3|Ek%8gM1%8AEU>_@tg%yz04%yhPz41$g7YgQgUN0g3^kMfj+_VB%2gc0g^294e.3|Bk%9oM1%8A4U>_@hg%D304%yfzz41$g7YgQgUN0g3^kMfj+_UR%2yc0g^28Xe.3|yk%awM1%8zwU>_@5g%Hz04%ydjz41$g7YgQgUN0g3^kMfj+_U5%2Qc0g^28Oe.3|vk%bEM1%8yYU>_ZVg%M304%yb3z41$g7YgQgUN0g3^kMfj+_Tl%36c0g^28Fe.3|sk%cMM1%8yoU>_ZJg%Qz04%y8Pz41$g7YgQgUN0g3^kMfj+_SB%3oc0g^28we.3|pk%dUM1%8xQU>_Zxg%V304%y6zz41$g7YgQgUN0g3^kMfj+_RR%3Gc0g^28ne.3|mk%f0M1%8xgU>_Zlg%Zz04%y4jz41$g7YgQgUN0g3^kMfj+_R5%3Yc0g^28ee.3|jk%g8M1%8wIU>_Z9g^12304%y23z41$g7YgQgUN0g3^kMfj+_Ql%4ec0g^285e.3|gk%hgM1%8w8U>_YZg^16z04%x_Pz41$g7YgQgUN0g3^kMfj+_PB%4wc0g^27Ye.3|dk%ioM1%8vAU>_YNg^1b304%xZzz41$g7YgQgUN0g3^kMfj+_OR%4Oc0g^27Pe.3|ak%jwM1%8v0U>_YBg^1fz04%xXjz41$g7YgQgUN0g3^kMfj+_O5%54c0g^27Ge.3|7k%kEM1%8usU>_Ypg^1k304%xV3z41$g7YgQgUN0g3^kMfj+_Nl%5mc0g^27xe.3|4k%lMM1%8tUU>_Ydg^1oz04%xSPz41$g7YgQgUN0g3^kMfj+_MB%5Ec0g^27oe.3|1k%mU!^304%yM308%yLTI4w0aw6j46%xtLI6^407M7Ygv@==1Mv04%yKz08%yKmV2g0iWM4^M0aWP40fM0cKgw0ceIP^402KMU^Q0vcgo^267KMo^s0vc0w^2aP0vN1_U7==1@K_Y5w09c2M^2aLufM_S3_spk0I02Dt^lM1%8mjUN0g%2FUg02c0w^24oY-_XVc-+Fp81I03HL_3U^g7_ws7=Mfj+_@M=]1@KfY4^9}5bzYfDo_T6Deg40gr3Nac1%1JP}2L0*_DKV1^HFPA^c-_@deMA0ec0vJv_YyzOadv_YOzPadv_Z2zQadv_ZizRa}a91If8EFQA3_XA403L0*@WGV102i[aI-+8@Os0c80vdt_YazMG46gYayDyg01UX3ME^ALW7Oaau40aH0*_O_z42$iDZ^bgr2M0ueMYa^9b@xI02Dx02pX2ETLw5pgj8g0p48c02Dxf_M[aQ4MYa2Dig0aM(_SLUX3ME^4[EFkJI02Dx02b63aV@q3z?6KNufXY0lqt80+IF^f87vI8geYflDH21$Tz0F%87z0F%2iD6M01X340mk1SX5w06g1@FWw3_@Mq^Ywt@N10XMZmuJo4%3udkA%wudkA%9asr^7Icg10g7q8U^1FPw3_@Mj^Ywt@Mx0XMZmuI84%3uc2A%wuc2A%9asr^6DG0f_X1E03O1TX543L3RpWQwg%dUQmg^21UQmg%AFNI^qvC_ZF3Eb^Kpg0WGux0f@Dx^lXez_qON@Xez_q0F@gr2M0ueMYa^94ewI02VB03GFW40_WtQ_@@V1019FPA0wasF^30*_37Hz_pE^g7_A4MYa118b01FQA02KcwYa^9c-_Z4ueMYa^11wOXab_SO1SF_j_pgs7X2w0Rg1YWS_Mc^AU_3_mfZN[oHA408eDeg1rM(_PB[IKME0b40vasp^3IdzO_05mDx02RFOA03XA902fD0C%3uD6M0gVO^c021FUg03es1o0101Gsr013D8^M086Dtf_UVM801M0xgl0w0rC4042V8012Ku8w5qsA093zsk_M_T7zBS+_T6lnp^FTg0uHDFoaLIaw010dD0*@WaV1^S[QHA407aV101agmHg0c-_WNp80o011Ab01FNA^eMVfbY0lqu406KDWg0fKgA0U@teI040dWsr013Dp40M086Dx^cVQ6M0k06FNI04etAg3^wqtQ+zD9w0702510e01Kog0gHAw04WVUy0gFOg0hKeNj_3_srA402L0*@RSV1^V[EHA40dbzgb+_T6Dqg^M(_F_URKL+ZNAw1g0eOnfbY0lqu402GD6g0fKgA06ushs%dWtH013Dch0M086Dx^wVNpM0406F_j_ZHA403yV1^CFQA^eJLYdw01c3Q+_XVGsF^@DZfZp1_WDWg0fF_j_EWsp^@DZf_AVPc01M0xgi0g0rC40eeV803xKu8woGsA+7z9K_N_T70*@MrDk7^o0vD07^o2uV102yVTlg8021VXs01M0xXb^8a1TVRIw%_FNA^eMZfbY0lqu407GDWg0fKgA0U@teQ^8dWsr013Dp40M3E6Dx^HVQ7g04w6F_j_ZKNnfbY0ls1n$3@tl8%fWtr^6DZ^7VMmw^weFRI04es5s^81Ksw030ewqtQ+nDow071251Bq^VMqg^w_F_j_NesC^s48k40U06Vx012Ki^jHDy812D9^SUO5fYvZNM(_GxVN3g06w7VR3g060D[IKsN420ewutz^s48uNB0dWwt@sm8^8fWvF^3Ii3O_05mDx03fFOA03XA902jDwE^23uDWM0gVWy0c0W1FUg02@uew0181GvQ+qDWg0fF_j_Besa^s48k5w806Vx01gKi^kHDy8eqD902HUOVvYvZNM(_FsVY2^6w7VQ2^60D[AKvIM20ewusu^s48uMk07Kwt@v18^8fXA402v0*@ueV1^JM(_Du[aI-_UWuME05M0v5xM82yDsg10FTg06atN^iDt^x[aI-_VNXA402L0*@saV1^FWS_MS^4Mfj+_CW[mrA404KV1^WFSA^c-_YrWvQ_@fBif2w^30*@TuV103iVkPg$[aQ4MYa2Dig0aM(_I9UR3ME^4Xbn_OE1ABg1g0atQ_Ylo0d^X0z_Mi9@[cHA404CV1^GFRA^c-_XvWvQ_XeV1^GM(_CoX2r_Ew1YF_j_GuPEfbY0ls3D$3@ve8^8fWvH^7DDE^20rDKp0M3E6Dx^DVVWg^weF@I04avQ+eDag0fF_j_f@OtfbY0ls2n$3@sp8^8fWur^7Dmt^20rDtl0M3E6Dx^jVRCM^weFVI04avQ+fDyM071251bF^VVww^w_F_j_i@sT^s48k4pI03DkN^23@DZfXYWV_Mi^AFOA0MKfM_Pz_ss-_V3eMI^s0veKvYh^10v@FPA^c0w^1Gkc-_WHrA40bbI9^k07V1cf2EFQA07Y-_UcrA409aV1^HM(_KGX9804w1YFOA0LY-_UUKMI0340veIy^c03uKvYh^10v@ghDMG9804011cf2wgi3MGat9^H0*@2Lzcf2w^jz03%9jI2^BqTXI0w0tqT_I2^viTXI1w06jnXH8w0k^TIaf_f07ODZf@GFOA0MI-_UHeMy_YQ0vakK042DZf@uX0z_X6R@F_j_XeIy^E03qvQ_@s7=1Y0g^1F_as8^2V1012IBQ05ask+WDx^VM5%6DP[4H9t056D5f_@FUg0fY1%1FWX9t04aD5f_@FUg01qsF^47_KKvY4w09asF0b_zYfZw_T6V102PM(_xCX2M0601Y[EKOU0280vcaK^w^akK^yVUA0GWV_MW^41_WDag1kMfj+_xeFOA0MI-_UiuMy_@o0vamK^yDZf_zFOAg^v@FOA^c-_UeKMI06s0vcgU^21uefwc%1}9Xzce$aDx01fFMA^atp^@D6g^X4cYLM1lFUg0fHDFgenD3z%3uD6M0gVO^c021FUg03es1c0101Gsr013D8^M086Dtf_UVX801M0xgk3w0rC40bKV802@Ku8w5asA01Lzcr_N_T6V2^3gp2g2ecMA$GtQ_YPI8^h86iB3U^[aHAx0a2VUH0wF_j_zGvF^@DZf_eKgA08eJi^g03rA905bH1g04^GDZf_GFgU08avQ_@rHH_1g02j04%qj6D2%[gKfM_S3_sr9t01iD5f_@FUg0ts1g^1F9rA40aaOng1qFNj+Gu408T0I%qhSOng2OFNj+Gu4^yDag01WW_MY^41_XIdw1B07ODag^M(_uqX2M0Aw1YN3w^83oU@0M%4[HKcMU$Gu406WD2g^FRA03Wsp^3IgPO_05mDx01nKuB0Vusec%dWsr013D8^M086Dx^cVM4M0406FNI04esw03^wqtQ+zDIw070251ge01Kog0KXAw0bWVUy0kFOg0decNL_7_srA8^d1Ea08UP2w%2FTj_PeMw030wpakLw02DZf@BFOA0lc-_TheKLYf^1eIy^403gv@FOA0LY-_TeeMI02g0vc8K01%alu013HH_3M^iVUH0B1_WDWg0fF_j_JqkL+_HH_3M^g7_HA9023H0w04^SVWi0wWO801^aF_j_sasF0cb0*ZM_I8L_q07OBbw08F_j_pakK022DZfZw=]1@KLY5^9efM_O3_srA40ab08%q6r0*@c7Ia^L07Olci^FTg0aFk0806Dt^CFQA1wc0N0440wI0w^1Enc-_UyNyOX2E04w1@FQA1wc0N0440wI0w^1EkI-_Uv1yOX2g0bg1@?a@KLYj^10v@[eGt9^aDag5uM(_vp6bbIaL_M07X0*@99o42^X1r_Oxp@[eGt9^2Dag5uM(_v46bbI9f@Z07WDZf_oM3%6wxgi3MEd8fYa0M0d87Yb0M4c-_To1yOX2g02w1@gi3MEc-_TdWvQ_X_0g%q1h18f2wQw_ME4^QwfMI40gM(_t76bbIaL_G07WDZf@H]1@KvY4w09ecgg%BefM_S3_suNh_Uw0SeMm^pUvKdgg040BciZ^24kKNm01o0vI0D$0uMO+Y0SuKz03Y038Cw01AmGYiL^24geKvYew010v@UM1%2kBg1^atQ01jIa^Z0nPI9w140DPIdw3Z0DP0K_Yf0f@BHw0wFrE30avQ_@7I2^Ac7XzA4%9ilbk^FTg0dFkMg06Dt^OBg1^GtQ02XIa02n0nPI9w2u0DPIdw5r0DP0K_Yf0f@BHw0gFrE30avQ_XSl0401FTj_TuMC_YA1veMS06Q2vc2X_g0f_WuE802DZf@IX3o0kg9YFrv_3WuE022DZf@zX9w0byJ@X9w0DiR@[AXA40aaDeg^[9at9^H0*ZvH2bw$7Ibg0104rIG03n0nPIFw3U0DPIBw1v0DP0K_Yf0f@BHw20FrE30cgH^23QqvQ_Tmlc401FTj_QVk0g0aDtf_fX2w0lM5YX2o0nw9YX3o1109YMbL_3M3_FqU0gamW0M2DZfZrX4IwKM1lF@w08GuE^bIdw0807OBJ_Y06aWDZfZc6biDZfZ964KDG080M4LZ0f3_FOwy0eMS+k0vc2X_g^_NyyF_j_eeMS0742vc2X_g0f_WuE402DZfYKX3o0lg9YFrv_3WuE012DZfYBN2I^8dUX9w0ag1YMbL_Y03_FqU02amW0M2DZfYmX3o0mg9YMbLZ^+FWx^avQ_MPIdw0Y0DOBJ_YfFWw0gavQ_Melck01FTj_p9k0g0aDxf@gF_j_nI2X_M^_WmK08yBKwc0F_j_ueMreaI0lqmK^aB6wc0FlU08KMU^o0v1yNF_j@Us2X_M^_NyBFrE30avQ_JDIiO2X05mDW^hFWw^qvQ_TXIiO2X05mDW014FWw01avQ_TkoiWuE0g30i_Q0Yf@Da140F_j_vxxbFWw40c1b_g3M_WsEh02DZfZQX9o03g9YN2I^8b_MbLZ^+Fq@^avQ_Gr4aM^wL7IC^a07P0K_Q0Yf@DG0w0F_j@CsgH^22Wc2X_g^_WmLy02DZfWfX9o0309YN2I^8bjFrv_3WuE082DZfW3N2I^8b6X9w02g1YFrv_YauE^yDZfVTN2I^8a@Frv_0auE08yDZfVKX1IUGM1lFqU^qkq0M2Bnw0hF_j_vKMreaI0lqmK^iB6wc0FlU0havQ_Tc7]1MvHr_0M02iV103LU_3WSfZNF@L_W620U01wEe08oc3w4}8aV101PM2%6oAM(_plX2w0rg1YBj4w0au40rr04%pxWD2%IBQ04Gsk+WDt01tN3w^7RkM4%8a1UR0M%4VkN$1FPA^qt901z08%pwr0*ZbTIww1e0nX04%wCTzA1%1aDx01_gr3MYbAm05CV1^HM4%6okFPA08c-_Sd}3KDig^M2%6oaM(_lGM1%89fNbQ^89aUV0g%2FUg1BYjJ^22iePH0c@0tKOS0mk0vGtU^1Ewfkg?9SywZhxEMfkwWS_Rm^41_X08%wyDBj2$3Izf@U0nXIGf_@0dx1A708Kho0qGtH^7zI9$iDig08[aY0M^1BHY-_SquMC01w0vA4wI0z0k%pqCD2%[QH9t05SD5f_@FTg0wc3w^21@KlcU$aur^yDp+pM1%87MUV0g%iFTj_xqsV^308%poL0*ZnSV102yX2g16M1@R+N4f4ggr3N4at90f@V1^XM(_bY[oHA402H0*ZDnIr04507PzIf3M02i_Qv4gFUg0_s-_SyecM8%1}a8o3rA402LIg3u@0lB1If3MglgM0p48k02Dt^mgm0w0udwYf^9bY1806Dx03G[9KN0dXU1mk5kc06h25^FUj_XHA403KDig0aM(_aaUS3MY^45paVYJ2iLM5w0au40cXzca$iV1^CF_j_Uqt9^GDeg^M(_jyN2Y^85RF_j_vKPE_Ps0vGtV^2DSg^F_g04cgd^21pWvr^7I3vYFM7v4C%wm72uw704011lV^Vkxg$N4w^85mgmt20el8o$cgo^21jA6n42Gi09^N2w^857gqsw4el8E$ciU^21fQ4TI1zBi3$34y%wjv0I%wjN1VU48Vkzw$N5w^84Igktgap80g034q%wil15S0wVkwg$N9w^84tgiuga9808034G%whqV202DMGE0g1^Vkyw$UP2M%2FUj_D@Kd^803udoc%4Gt4_Vt1cf4g?9qt91030*Yy3Ibf@c07P4W%wfF1cf4gm5zw0at9102V5^BM(_8fX2b_Yw1YF_j_u9k0806DxfVlF_j@ic0w^1ABWtU^70*YwOV5^Dq83R46ywZhxEMfkwWS_Rm^41_V1If3MM2%831FVw^ulc8$qvQ_BqDCw01X9z_Z01@N9Y^82OF_j@jel8Ya%bAm0eL4LM^waXHTw03^SV2g3uWWQ02w0dKgw0HGtF+_Hew0c^THSw0c^SDmg0xFQA^WsF^30*YAuV102yX2w6r_ZYN2I^827Xdw0601YX4T+M3p[cKJk^w03eNo^E0vdv_c^M044Mcg2Dl+XNA$sqM3A0824xN3Y^819X8M6w05@Aw3ML@v0+Y0gKNE+U0S1zrgo1M2bdR0a2V5w1SFXz+WtX^7zo8$iDig0a[9I0M^1Abs-_QDKME0b^vHA402qDig0bM3%6gCM(_ihX2w16g1@[9Gt9^X0c%p1_0*Z8jIa04n07WV1^CFQA02c0M^1A6I-_Qt@ME0hk0vHA402qDig09M3%6giM(_hGX2w14M1@[9Gt9^P0c%p0H0*Z5TIa04h07WV1^CFQA02c0M^1A1c-_QkeME1nw0vHA402qDig09M3%6fYM(_h3X2w3Ww1@[9Gt9^P0c%o_j0*Z3rIa0o707WV1^CFQA02c0M^1zXI-_QauME1wk0vHA402qDig0aM3%6fCM(_gsX2w67w1@[9Gt9^z0c%oZ_0*Z0_Ia0od07WV1^CFQA03I0M^1zRY-_Q0KME1x40vHA402qDig06M3%6fiM(_fRX2o6201@gp1w1GvQ^J1g60aFPA^asF^30*@MCDyM08FTv_e1wbN2Q^7ZB6bTI20kf_TXI1w2o07XI4z@_9RDz4f3^2jIwyyC05nIoyqC05mDS%FPA^cif^1_iY0w^1yKc-_UKrf108aDeg^M2%6aKM(_BTUO3MG^AFPA^c0w^1yFY-_UFasV^2V101OM2%6atM(_ByUO3MI^AKog0fs0w^1yBs-_UzXC403SV103iM2%6abM(_BdX4wYLM1lX480lgx_X5gVL0dpM3%6BlUNkM%4h_4M0450o0KDeg01FOA^c-_WAWvQ_UF1g60eFPA^GsF^30*@EyDZfZ_gk1w2asV^2Dag01M(_FZF_j_t450o0CDeg01FOA^s-_WsGvQ_SB1g60cFPA^GsF^70*@CuDZfZu68bIUz@_9RCByw40U@3MM^AX68CFw1lFZw^qvQ_SKD2g01XewYLPNpXe803wx_X4UVL0dpM5%6AvUPhg%4h_dg0eu%40gKPEfbYUmuPy^U8v@NeerM3ms1g^1Fb@cQk%14vPk02Dig01X1wYLPhpX1803wx_Xe4VL0dpM5%6B0UPVg%4h_dg0atV^7I63O_c5DI4w0e27_IUjCY0RD0k%ql7zfB$h7YR^FRA^uO8fbYImuOc0Ds8vWvp^7zwf2E^iPPg0oX803g41BX843ek1BUM3MG^AIYQ0WePw1h2wpm20Yazzcf2M^jId^5E6mV1013X3s2o41BUT3MI^AX7g2mG1BX2k01q1B[kKMJ0MSwprA404aV103lXbw4oM1@IYQ0yefwYaw01cae$0uOd^40hHDDU1zDae%6aV^1hFRL+@LB03Y03eNC0M^vKfgYb^1etg$hbDDQ5vDnw%2aV^3BF@L+@Ke03Y03esTQ%oKto^408Hfd^GV102aFPA^4fgYbZ3Ef37F_g02ci8^1@3c8W0s0g0c2T$0h5rNbQ^7TyKgw0wS30wB12E89oUM22e^AVO22630eVP22a30eFX^YetM$h}eaVUD3AU@22i^AVR22mg09y5^7@tZ$8KtR^408KtMwBI02udMwww09ciZ^1ZQqtG^7IJL_287uV5w0HWO8^w0dM6%7T4M(_0rN4U^7S@N2I^7T9WOg^w0dM(_0fN1U^7SON2I^7SVWO4^w0dM(_03N2I^7SUN8w^7SNUO1w%iFUg0bWtV%ooKLn^803s0N^w80qsF^30*YvFgbo^gi3N4c-_NA@ME0vg0vIgU^1ZzsiE^1ZAA5tc03Bj5^+Z1Lq^VkOM0f+FTI^uND_ZAwtY0N^w80qsF^30*Ytf0cg082034bM^up6Dag^M(_78M34020w1N2Y^7C8FOA^c-_NLs0N^w80cgL^1VvWsF^30*Yr91Qf3gUR2$k[sI1%1xwasV0234vM^umSV1^JM(_4e[fqt9^308%on70*Y4j4n%uln0g%omqDeg0w[bs-_MZXA403SDig^M2%65yM(_0JN5M^7B0M4%65fFPA08}2T0*Ye2V1^ZFQA^c0w^1xkI-_M5Ihs^1VaY1%1xeasV022V1^JM(_39[fqt9^308%okr0*X+0g%oiiDeg0w[bshs^1V3Y-_MIHA403SDig^M2%64WM(@_EX9w2j01Y[as-_JQ}6bIa08Q07Oh120HFUg2aIjE^1YLecwUy^1eIy^803s-_L2Yio^1YI}abz498w^91Af4gFUg1QquV^2DZ^EWNI^w0dk56w0c1%1wSWsV02118f4gM(_1I[eQ50Yh2V1^CFRA^auX^70*XA_4a%v8h1Af4gUX0y8^xFWg1FY0w^1wWI-_ToXA405bIaL_i07XIK01p07WV5^XWRc^w0dX4n+03pgomw0eJQ^803}dGDuM01X0s@LM1lFUg08@M801o1veM8^I2vecwE%547gE0j0*Yffz8d%1iDSM04M(_3HUO3g%kFZI01c-_MU@Po02a0peJD^803ecwQ%5avr0130*Ydnz8d_Q_Nj0*Yc_z8d_U_Nj0*YcDz8d_Y_Nj0*YceDp+C[aGtU^70*XwGDZfI@X1wVL0dpMe%6rKUP7w%4h_fw0}7iDZfSDgk1w2qsV^6Dag02M(_tQF_jYqYg8^1XRWvQ_hPz0f2E^iDZfQnIYQ02avQ_hf4S%uZSDZfRz[QGvQ_l_46%uYiPMg21F_jZ5Sy0YayDZfQjN5w^7L5F_jZhXA405aDZfR3[nqvQ_j_4u%uXiDZfQDUT3MI^4F_jZ8Ih8^1XFGvQ_gHzgf2M^iDZfQ5[hWvQ_g6Dmg^F_jZ8Wt9^2DZfPVITk0wavQ_eaDug^F_jZ1avp^2DZfQrFMA^avQ_caDigw0FPA01ecwYh^5c-_LNqt9202Deg04UO3N5^kM(@@XFQA^qsV^bz8f4g01j0*XX6Dig01FPA^KcwYhg05c-_LFWle013z8f4k01iDegg7M(@@tm03N4ci8^1Xqch8^1Xrl0dw01o4f4kN6Q^7Jkk1R^ci8^1XnqtX^7Ip_SO87uDZfTp[juNt_fwwpqvQ_feV1^8IY40wavQ_dbIwv_Wg6mV1^8F_jYNbfd^Hzcf2U^iVVQ1JKg^tGtX+_Djk%6bDo4%6bIRP@_0lCDcg01FTg0KKs$0hes0Ycs^bfd08ODag^VMU^g0yFRw^}1GDZ^8N1w^7I8MyE1M1^Kgw04Ke04B^9ed04Aw099814BJ2Q19qVO0i630eVQ0ia30eVS0ie30eMbs$1VM0im^94qK8E^vgG0inel84ww^siZ^1WTqtq^7IJv_i87uDZfQc[aI-_IOQ4wYcz0*XJrIa03507WBHw01?mHA402D0g%nMaDeg10M(@Wl[eqt9^308%nOP0*XsL4e%uH2V1^FUR0Oi^4M4%5YEFPA0gc-_KuXA403CDig^M2%5YuM(@SNF_jUmXA402D0*XoGV1^FM(@OB[oKMC_sM0vatU^6DZfCOgp3N4avQ_WZ1g608FPA^asF^b0*ZveDZfHGFO020au40biBaw40Aw7MNNy2FZw^qlK0w2DZfHUIYQ0batF^2D2%[eAdMYcuDZ^8N3w^7FnMCE1M1^Kgw0dKcwcB^9ed0cAw09eswcxwM3Kt0cywM3KtwczwM3HdQ013D5M%2bD7w0102bD7g0202bD4^1c41M439oMbs$14rK8I^vgH0Onel8cww^siZ^1W8Wsa^7IIf_987uDZfNiM(@TzUO0w%kFTw^s-_I@XA403b08%nuT0*WQeDZfATFkU04asV10vz8f3c01j0*XzsoEKMA04g0vKcwYcw05c-_KDucwYcM05c-_KBWvQ_OqDag^F_jY7V80Yb_DMf+04b0yg0w8i6Ptg2wAw3MNWvo^2Dq%F_jWqk50o0ODeg02FOA^I-_RiGvQ@A518608FQA02GsV^30*WYKPMg2yF_jWdeO2aao0lqvQ_ZSDegg8UO3MP^kM(@TGFrU^h8yKv8wIxyHF_j_IrdR0c2DZfErgi1w2Gt9^GDeg^M(@KBIY40MGvQ@wWi0v2_F_jW2HA402qDig07M3%5T4M(@TzX2w09g1@[9Gt9^H0c%nrL0*XtrIa^y07WV1^CFQA02c0M^1t3Y-_JOuME@ug0vFkJo02DxfDv[BGvQ@tKDK^1F_jVRS20YayPMg20F_jWYquU^2DZfDdRM0M03^==WS_Mc^A[X@fM_M3LsqvH+xwwe^X2M1ngd@[IKcwc0w01}8eDig0aFPA^c-_ICHA409bz880g^iDeg^FQA02A6ww1z0*X8PI6+Z0dxg4f2U[QHAk027H8w02^T0*WSTz8f2w02iDKL_YX3ItL0dpgne08bDFE0uD2+U[oKKM^c03auX^6DIg01FTg0WKKb^403ecwE%1at9^GDeg^M(@Nnk21w0ecwE0w01at9^GDeg^FWI04c-_Iil0wo0iDqM08FUv_VdsnYczMObAk0eCV501tgp3MOedgYb^9efwYc^9elcYbM^eegYaw09atV^11of3UF_g0gHA40b72J^1^2V8g2TKubgJXDFI47I6M1qo6iV1027UP3MS^mUM3MK^mFOA^bC7023DxQ%69gEf3wVU3MW30eU@3ME^4VkPMV%FQA06}591cf3wX7kuLg9pUOvw%kM(@M1ma3MTeMC08Iov52wYbOV101UUP3MG^4UO3MI^4FQA06c-_FDlywYdPI9w1V67PIG02r_TXz4f38^iBTw01UN3MQ^8X1T_Fi1B[JXDFI47I6_@Iw6iDCg^[RecwYc^1bDFA4R1mr^gjBw0c-_GYXA202aDN^tKgw0AKPp_@UwplywYdOV1019[9GsV^H0*WR_Ia^t07OV2g0CgoIw0rDFs4yDZfZ@FUg03s-_HXRwM803Ief_w17XIef_t2TVoEf3sX9r_Tg1Y[xWt9^2DZfZCUO2w%4FQA02GsV^30*WTbzgf2w^h1E80wk21^45wg0jIF_Y5o6iDZfYz[ueOE02n_vKcwYa^1c-_FWuS0Yfwgpqt8^3Hr_4M40iV5^A1_X08%n6T0*WhzJwf3U46mDi^1WS_Nc104?90v@US3MO^4X6v_SY1BKgA0p@s7o%oBwgYbPD0f3Ec0XzIf2w^iD6w01k13MUelcYeg^44MYe2Dig0oUO2M%kM(@IFF_j_KKJLY3^9}e_zYfRE_T6DW+0o83w062wU0xwMe0goe3w662gU21wIe0Eod3wc63MU3zI8w0r1DWDy^1?a6y0YBxEEf9wqc3Oq6zwYD1EAf9Uqb3Ow6zgYExEYfagWS_OO^41_Xz8308^iV102PFQA02GsV^30*WJrz8f2M02jz8b0g^iDig0aFPA^c-_GOucwYo^9}9bz8b0o^iDig0aFPA^c-_GKKcwYaw09ecwI2^1at9^GDeg^M(@GJUO3NM^A[4B0gYujz8b0E^iDig0aFPA^c-_GDecwYm^9}aaV5^FUO3Nk^A?yI-_IsuIE^803s-_Ft@cwYnw09eOI03U0vBw0Ymjzsf2E^iD2L+[EHAm0311Ab0MX6c^g3pUO2g%4FQA02GsV^30*WCtg8a^?IGsV^eV1^HFVI02c-_HaGsV^iV1012FWI01}2KBiMw0?hc-_H6WtD_ZHzsf2E02jzkf5g^j08%tJzHVg03^SV2g3BWNU02w0dKgw05uJN^M03udM8%2eewsyw01eegsz^1eewYcw09eegYsw09ec0sy^1ecMsxw01ec0Yr^9ecMYh^9edwsAw01eeMsB^1edwYmw09eeMYtw09eegsBw01d80YpdOmJ80Yp9Omt80YndOmQewsBzI30PK0nSVwM10F@w0f@dgYsw01bDVg4WV5^kX5Mc@w5ZKoc0hrA4^4rVbAo^WV5^KIY40Qbf10faPPg1dKoc0hato03YrlbAs01n27w$7I7g0104qPMg3hM(@YUWN8^M0cMxE07+_FiU20c0r_@%c8u0w%bDyI1b27w0w^2Bjw0wKu8wgud0Yf^944wYv2Bfw0wM(@DHX2ocww1@UM3NY^4UM3Na^Agj3O6ecMYew09asF^r0*VZzzo78U^jzIf8o^jzof3w02hEwf8wVkxO$VkxM$UR3N4^4gh1O0edgs0w095x0Ysjz4f3o02h18708UO3MQ^AX4g01w1@X5obhw1Y[a5y0Yohgwf7IM(@xmUM3No^4UO3N8^A[wKMc3cU0vHfd01zHkg03^P07y34CWn07udjZY@Vxw11m13MH50gYtjH6M05^SV1^AKuCMguIy^g03eIk^o03rA901jH4g03^SV2^rWN401w0dKgw04KNg+Y0Sbf10e6V5w15[6eNo3zM0vGtb+_HJ^8^PIK^f07Pz81g^3qi0h^QLUg0h^gh0h0auT+qi0h^NA$UUm23NpbCk0aFg8f6kM0X_0fY0UN3MJ^kUN3N6^AKo^A450Yvzzgf6802h1Uf80U@3NE^AVkPNQ%VkzNG%VkzNK%VkPNt%VkzNc%UV3Nm^Aka3NfbdR0a2DG%ITk0IbdR082Ptg30FUA^aup^1o4f7IUP3N8^4?oueSc%AeeMYkw09eOU09A0vecwYnw01eJm^803lxB801ogf64k63N@ake^5g0f7YX1g0B81SUO3Ny^4FQA^asV^70*VSbIb01T07Xzcf6w^iV5^CFQA06c-_CluME0a8oveME^U0vc-_EX5wM803Ief@X17XIef@U2TXz8f4w^jz4f7I01h14i^Aw0g05wgYuPH+6k06HI8g010dyV501im13NBed0Ymg07rA402hg8f7IX1r_C01@UU1O%AAw5Ma5y0sg3Ixwgt07Vokf74X5E9Lg1@UP3MW^4M0403Q8_UM3O6^AFQA02cgI^1N2Y-_EleME2K+vecwYiw01au8^30*VIDz8f5U^j0*VIfz8f4w^j0*VHSDZfQRm13NXeMx^40SbAk05bzgf5A01SV1^Ak23NXavQ_QVo4f7gUO3Ny^4F@w02EDw402DXwfEXeI3W012?jGsV^70*VIrIb0sU07Xzcf6w^jBjf7g^2V5^CFQA06c-_BJKMC_Sgovat9^h1cf7IUO3NR^kM(@vVUR3NG^4UX3N4^4m21N0auX^rzcf6U^iVW51HFW40_@J5^403eI6^403bDyw0iV202P4ybH6M01^Pz0f6E02jHIM01^OVUE0rUN3NK^Agl1N0edgYc^9bCk0aFgEf7wUO3O4^2FUg7_udwYww01eeMYiw01edwYbw09eeMYk^9edwYb^9bA802rz8f2E02jBjf4U^2DGg^U@3MG^4X6U1rq1Bm03NfeM80qE0vKd0Yaw01ecMYe^1bDFoajzEf38027HG_380ebIdwmz07Pz0f2E^iV201GFRw^bDH01rzUf2M^jzof2M02iVC01lVkPN2%aaUEC5wwYbjzEf3U02iV@u0iBg3NsXDOw1GV101Fk13N0}9IoFrA40bWDZ^7FOA0pc-_Ci@cMs%1c3x^+_XDFc5zInw1CM6nIqf_ME6nzof3g^jz46$jzgf3o^jzw4%2jz8f3%ho02^X0o01M1@[qavQ_Zvz4f5g^j4m%sYfzcf3E^jBif8o^7HUg02^SDig08UOVg%kM(@suX2r_VvZYM3%7esUN0M%iFUj_TchE^1Kpc-_Dnudwo%1ecw8%5c-_CtecwYa^9}2r0o%m4@DmgnfM4%5wLM3%5wQM(@s1[qavQ_UYomKcwYcw01eewYfw01}eJogf40[KuMobbY0lrA409poof80Xa82PU1Am03NeanEw03I1i0w7RrHkg02^SV201nUQ1g^5gUQ3MI^4WW4^M0dKgw0FXA403H2ew10403zU3%2j2Gw30403zga%2iV103BMKE1g1^k63w0c9q0o0g05^k02DyM01X9w2F41BUP3Nm^4WM7Ne01GWM7Nc01WX3w2LM1YUP3MW^4FOA01I-_ALecwYy^1c0u8cirFuJi^c03c0tURfTP@c0Yxw01bC6047H4^5^SV1^AWO801^cKuA0guIk^o03rA901jH4g03^SV2^gWN401w0dKgw04Hfd02GPMg3xKgA04GsF4UzI4w0L86mPPg0XU@3N4^4FPI^rf10bfIUM0zM6kEWBwwYgzI9w7a07Xzof2M^jzUf2E^iPtg2wFWA^eNK_FB0puOo0rZ0puc0Ye^1eM60t80vauE^2DZfReq81M49k0YpaDt^bUS3N4^4UN3NI^4X641vA1BUW3NAM2kXao1Aw1@ma3NfeOC1d^vBx0YnjIi03E0DVo4f48X1o96M1@US3MG^4UP3MI^4IY40OuNz2hb0pquF^2Ptg2wITk0IecwYcw01eMG0jAwpud0Ye^1avF^3Ihw4V07Pzkf5E^jzAf3U02jzwf4^2jzEf4802j2Xw$7IXg0104rIlwbX07Pzsf6o02jzof4E^jzAf5%iV1025[vGvQ03Tzgf3M^jz8f2E^iVWm2HUW3MK^8Kgw0iKMA0Y6wprDFE4bIaw9cw6jz8f4o^iV101q[dI-_ARrA204aDN08P[JKewYbw09bDEg9qV1^HFPA02I-_C0@ME01A0vaub^51I201X7w08I1BXbD_Nq1BKuCMirA402KDeg0aM(@nJX2r_Xg1YUX3MG^4KuBwmudgYbw02eOR28L0prA40bDIuf_A86nzAf5^2iV101EUW3N2^4UT3NC^4UU3N%4UV3M@^4FMw^ecMYe^1eMS14E0vbA80arzof4E^jz8f38^iVWm1HFRw^udwYbw02eOy1UmwpucMYaw01eMS20X0prCk011g4f48FM40_Wu40vTzUf2M^gEHKdwYb^92yoF_jZI@ews%1bDFE5DIl0ry07OV1^RFOA^ecwYh^x@cMYsw08rA4^fH2_780eb23w$7I3g0104rz8f38^jI80w7g6nI801ZM6nzgf4g^jz4f6U^iDiM03X440sy1BUS3NG^4X4o0r21BUM3MO^8MwU$3WP%g0cX3Q^g16UP3MO^AUU1O4^AKgc0U@fwsww095ywYgzIFwDy07Xzkf2E^jz0f2M^iPMg39X509Ss1BUO3MO^4VkzNG%VkzNK%FWA^bdR0a2Ptg2MUQ3MU^4KuCwUKN8_IQ0vcgE^1Nd@cg81w01eN12dr0prDF43iV8g0@Ku90UWvQ_HLz07$jzEf3%iVWg0Eme2w0eewYpc0B9k0YpeDx0f9UQ3N4^4X4801G1BXew66g1@m23N2bf10cCPtg2MX2z@f01@ITk0EeOo_AuwpuegYd^1ecgA%1eeMYdw01ee0I%95wMsg3Idwq@07WV102oUM3MU^4X0z@d01YN2w^73BUX0w6^4UP3MU^4XbfXUW1BFWw^avQ@TfzAf5g^j4u%sdXzcf3E^jBif8o^7HWg02^SDig08UOVM%kM(@gVX2rXP_ZYM1%72TUN0g%iFUjXNIhE^1HvY-_Aueewo%1ecw8%5c-_zz@cwYa^9c1w^1lr}2GDmgnEM4%5laM3%5lfM(@gsF_jXEKNo0Ag0vBw0YjyBW8^FgG^avQ_jbz4f3g^jzo1$jzkf3%ho85^X2w2cw1@UV3MS^4UU2g%Am21g0eMC0340vHA409zzcf5o^jH0v4U06HH0v4M07HIdLR707Pzkf4g^ho8f5QWWk^w0dMGU$4XaQ01016X2o2Dw1@UW3Nc^xFQA^ato^7Hjf4M0efHnf5Q0feDZfQCUM3Nk^4Naw^716UP3MW^4WQ%w0dVkzO6^1UOiw%kFQA02c-_zEuMC_XL_vc3w^1M7@cgU%4Gu4_Xb46%qKuV102oUS0g%4M(@frUO0w%kM(@bRUO3ME^AFRA5PXA402r0g%lbf0o%lcL0c%lbn0*UUaDZf@eFUg02I-_zKRwM803IefTt17XzAf5^2jzkf3w^iV101EUW3N2^4UT3NC^4UU3N%4UV3M@^4X5w1dg1YX6o2gM1YUN3Na^4U@3MO^4KuAgqWto^7zof2U^zIWw4QM6nz0f2E^jI1w8wM6nz0f4g^jzUf6E^iD2M03X0XXxy1BUQ3NK^4X0jXw21BUN3NS^2FUg17qv4@TyPPg0GX2w5ag1YUP3MW^4FOA01I-_xgucgYy^1ec0Yxw01eJh^c03c0u8cirFs0tURfTPXC6047H4^5^SV1^AWO801^cKuA0guIk^o03rA901jH4g03^SV2^gWN401w0dKgw04Hfd02GV2g0iUO3NS^4X1bXe41BF_g0SedMYpw09edwYiw01ee0Yk^1aup^2V101@F_g0mefwYf^1ecwYaw01bDFoaLzEf2U^yVWe0aX080PI1BKuCwgKMG08q0pecwYhw01}5GV1^SM(@7tKg80gGv406SV102SUW3MK^AKux0xHA402KDeg0aM(@cbX2w0d01YX3A^g3pX9w0kM1YU@3Nq^4gl0w0uIj^c03rDFoanz4f2M^Dz4f2U^yV2^qX1U6Bi1B[JrA409fIug0yM6nIKf@GE6mVWr18[aWsV^H0*UJHI9L_i07PzIf2E^iVWm1oUR3MK^8Xbk5Cc1B[KeNV_@gwpue0Yk^9}6DzEf48^jzsf6o^jzAf3U^jzwf4%iD2%F_jYXk5g806DZf_3FUg02I-_yylx0803Iif@@17Xzwf5^2jzkf3w^iV101FUW3N2^4UT3NC^4UV3M@^4UU3N%4X5r@Qg1YUN3Na^4U@3MO^4Kgw0FGto^6VWh1HUS3MK^8XeH@Qy1BUQ3MG^4X4o0XY1BU@3MI^4VkPN2%US3MI^AaaUECato^2DZfG2UQ3MY^4F_jYhed0Yf^1avQ_Pv4m%rD7HaB0o0ezzUf3w^jIULKHM6mVW20qX1XWkI1BUQ3NjM2kKuAwHB10YgzzUf2M^h1qC^aaXzof2M02gECato^6DZfFim03NeavQ@Lnz07$j2rw$7Irg0104rHlw02^SVWg2EKuxwduJ3^403uNa08T0puLC^403uPG^@wpuIq^403bDFA5yV8g1hKuaMkuNm07AwprA409zz8f3o^jzA2%2jzEf3%ho0a^X0zWXg1@U@3Nk^4N4w^6UoUP3MW^4VkzO6^1WNU^w0dUO5$kFQA02c-_xs@MC@Jf_vc0M^1JYucgc%4Gu4@IH4m%qbDzo5$j0*Uq_z82%1j0*UcDz8f2w02iDmgnf[9I1%1ixY1w^1iDY0M^1iys-_xlGvQ@Gpokf48X5o4kM1@UM3MG^4UO3MI^4ITk0IbdR0a3I0wlHM6mV101yIY40OqvQ@p7Ia0360nXBjf5Q^aDZfGiKgA0lHDFk6zIBLG0E6mV102mF_j_w@fwYb^1elcYgw^edwYb^92yKa9yDZfCoFMw^cgo^1Jz@LC41w0Wed0Ye^1eNe@ID0prA80aqV203CXejXGQ1BUR3Na^4UQ3NjM2kKuBg2@fwYb^1ec0Ybw02510Ygzz0f2M02gEHyyoFRw^qvQ@mFo4f7IWM7NQ01GX24^g3o?kAewYk_zgf5A01SV1^Ak23NXavQZ@OPPg0UIYQ0irfd06yV2g0QIY40I@NA0v@0pbfd02Pzof4g^iVWi0pX6c2nY1BUP3N4^4X37WCq1Bm53NteNo_2c1vKc0Yh^1ePw^40SuJu^403efwYr^1bA8^nIU0fZg6nIm0jg07No8f7AX2jWuM1@UM3N4^AUS3MW^4M4%56IFPA0g}2r0*UdWV1^S[gKcwYug05c-_wteME1ef_vecMYd^1efwYh^1efwc%9avQ@AZo0f7wX0r_eM1@UQ3Nc^4XajVOy1BU@3MO^4UN3NO^4WQU^g0dFSw^rAx01jzkf6M^iVUI11X6M^w12UW3N4^4UQ3MO^Ak63NteNq06z0ppk0YpaDt01zKoc09bfd^@PPg0t[U}62De^_KvAw8XAo0eb2jw$6VUJ3wKgM0UsbK$0uPJ^40hHDFEamV301GWQo^g0dKgw0hKJk^403uNu1aB0prA403mDag^Kos0bBxwYujIp^J07Xz8f3E^iV8g2zKuaMEY1%1h7qsV042V101qM(@1fUP3MW^4[gHAk02r0*T@nIa0i4_TPz4f3g^jzEf4g^zzEf4g02jzE1%2jzw78g02jz0f38^iV0M2wUW1O2^AVkzNc%F_jVd}6DzIf3o^jzEf3g^iV102lF_g01WsF06j0*TGnzU7$j0kg0f+@VWu0oX1k0ns1BX6z_Ya1BUN2w%4UU2M%Am62g0eNC^s0vHA406yDZf_wUO3Nk^4N4w^6MCUP3MW^4VkzO6^1W@8^w0dUOV$kFQA02c-_vwuMC_@n_vc0M^1H_@cgc%4Gu4_ZP46%pIvzo1$j0*TXTz82%1j0*TJvz8f2w02iV1^CM6%52OFRA5nc1%1gAI0M^1gBY-_vp}6yDZf@oUM3O2^4XbwILM1lWWI^w0dKgw0F@dgE^1sulck$5wMYw3HaM03^SV103wKgw09WnEw02V1012MAE0g1^U@1$AMyE0M1^UM0w%A[6I8q0k0g050M402V102mMGE1w1^FmW^51wE02DyM01X9zUVq1BUX3MQ^4UM2M%4ma1N0eOC0DM0vKdgs%1c8e$0uMd^40hKKw^803rDFk2yVW03GWQU^g0dX4805Y1BWN%g0dX183ba1BWP8^g0cKuCgqbAx06eVUH1zX0o38a1BKuA0FHDFEbzICMeBg6nzAf3g^jz49$jzIf3o^jzwb%2hoE740Xao2Bw1@[CauE^2DZfnzUN3N4^4WM4^w0dX0bUFa1BXerUEg1@me3NtePC_wI1vHf10cCDZfxzUO3NN^kFQA^I0M^1g6s-_uEeMCZzL_vc1%1H7Kcgg%4Gu4Zzb4a%pur0o%k0vzI2$j0*TJDz82%1j0*Tvfz8f2w02iDmgnF[aY1%1fIs0M^1fJI-_uwWvQZwVo4f5QX1zVW05@U@3NI^4[dasX^7IUM8Hg6lokf7AX5jVSg1@UP3N4^AFRA^qvQ_sSV101jFQA^bC704qV1^NFOA^bC702mV1^jUP3N4^4X37ZCk1BF_jUbas9^6DZfAQUS3MW^4UR3N4^4M4%4ZqFPA0g}2r0*TEOV1^S[gKcwYsg05c-_u8KMCZaf_vc3w^1GEecgU%4Gu4Z9H4e%pmzzo3$j0*TBXz82%1j0*Tnzz8f2w02iDmgjI[9I1%1fdI1w^1f9s0M^1fec-_u1qvQZ7rzcf3E^iDag06M(ZMrUN3O8^4UM3O6^4WR4^M0cM1UwN9KBM1Tzk_vfKoo0guIg^k03rA402iVWg11WO801^cWNg01w0dKgA05eIh^c03rA8013H4g06^SV2^iIY40EqvQ@Grzcf2E^jIdw2cM6mVB^gk13N2as10f@Dtfy0F_jXGIjE^1GfKcgYl^1ecMYew01el8Yxw^uJx^803qt9^zz9K%1j0*TprI9LAK_TP0k%qxjz45%1aDxfABN4w^6jsM6%4XoUW1$4M(ZTfUO0w%k[Cc-_sV@cwYa^9atp1tyV1^GM4%4WBM3%4WGM(ZRTF_jV0s0M^1FVKcgc%4Gu4ZgX4y%paX0o%jJP0*Tqjzs8$jz82%1j0*TbLz8f2w02iDmgnG[9Y1%1eus0M^1evI-_tiWvQZeHz8f3M^j0*T8fz8f4E02iDZfd@U@3MI^4aaXzof2M02gECbCk061gof48F_jRHecMYsw01eMY0kM1vrC304eDq^_FNA^1JA?JHf10fKPMg3rIYQ0XuPEYOM1vavQYNyPMg3hITk0YavQ+nzw78g02iV0M2wUW1O2^AUM3MO^AITk0Ibf10cCDZfqDIY40OrdR0a2Ptg2MF_jSIuegYk^9}6zzEf48^jzsf6o^jzwf4%jzAf3U^jz8f3w^iDqM01X2w07g1YUX3Ng^4FMw^avQ@X_zwf5^2iV101FUW3N2^4UT3NC^4UV3M@^4UU3N%4F_j_UefwYb^1eeMYk^1edgYb^9elcYgw^bA80aoEHyyoFRw^qvQZiODyg^F_jQaBxwYujIpfq407WV101uUR3N4^9U@3N4^AF_jY1ecgYdw01ee04%95wMsg3IefS_07X4C%qhfzIf5g^jzcf3E^jBif8o^7HGM02^SDig08UOGg%kM(ZNHX2rZFvZYM5%6zFUN1g%iFUjZDcgE^1zIrA409zzo2$j0*Tanz82%1j0*SX_z8f2w02iDmgls[9I1%1dvs1w^1dBs0M^1dvY-_sjavQ_nxo0f7AX0jTIg1@F_j_DIho^1ENec0Yl^1ecMYew01el8Yxw^uIw^803qt9^zz8B%1j0*T1PI9LRm_TP0U%q9Hz4e%1aDxfRdN4w^6dy[Cedwg%1c-_slKcw8%5c-_rsecwYa^9atp1lSV1^CM4%4QKM6%4R6M3%4QMM(ZLZF_jZaue0Yk^9}6DzEf48^jzsf6o^jzAf3U^jzwf4%h30f5fF_jSwuOoZTCwpqvQZRHDQ^104aPtg3MF_jNXrf10cCDZfmgVkzN4%F_jRHuegYdw01ee0A%95yMsg3IKfPP07WV102UU@3Nk^4N2w^6x2UP3MW^4WQU^w0dVkzO6^1UOgw%kFQA02c-_rDuME07n_veOb_ccwprA409KDG%F_jOJc1%1E4Kcgg%4Gu4@NH46%oJHzo1$j0*SZ3z82%1j0*SKHz8f2w02iDmgnk[9I1%1cGc1w^1cRc0M^1cGI-_rtWvQ@LqDeg01F_jXnI0w^1DUKcg8%4Gu4@TD4W%oGHzoe$j0*SW3z82%1j0*SHHz8f2w02iDmgnk[9I1%1cuc1w^1cFc0M^1cuI-_rhWvQ@Rnzkf3o^jzI5%2ho0740X0z_AM1@F_j_tI0g^1DGucg4%4Gu4_Uz4e%oD7zo3$j0*SSvz82%1j0*SE7z8f2w02iDmgls[9I1%1cfY1w^1clY0M^1cgs-_r3GvQ_Sjzkf4w^ii0l^F_jNSXf10cDBif6E^3Bif6U^2Ptg2wITk0IavQZb7i01014^7=]WS_Mc^AU_3_kfZNUO3MG^A[oXA408iBbw01M(ZCJUO3ME^AX8w09w1YFXw^aup^2BTw01UP3ME^4UO3MG^4KuCgic9e^4^bDyI4R1lF^M(ZDvKg80sGt401aDt^BFMw3V@OM05T0tKcwYa^1eJLYe^1c3Q+_oCY-_qW5ww803Ia^617XI9L_L2TWDag0aM(ZBXX8D_Oy1BF_j_VeewYa^1}buV101b[eGsF^70*SDzI9^m07OV2g2OXbw08M1YKgw0EHA404KV1^WFOA^s-_qpuMG+^vc-_qHRwg802Dag0aX1w01wh@X1r_J0J@M(ZB2F_j_QrA809uDK%F_j_MquW^6Dag1AM(ZAPF_j_K0s71MvHr_0M02iV103LU_3ZWfZNF@L_M620U01wEe08oc3w463wU1xwAe0wob3wa63gU31wYe0UX2M8XM5@[IKcwc0w01}aeDig0aFPA^c-_q1}7bIJw7N0DXBjf5M+_46%pF7zw19g^jz818w^jzwf5w02jz8f5o02jzc18E^jz018M^jzcf3g02jz0f5E02jzg18o^jzk198^jzgf3U02jzkf4o02jzo18U^jzw19o^jzof4802h3I19ogW0imJ80Ynsimt80Ynoim@MI4qs1vrC304bzcf5E^iDC^_KvB0WrAk01XIf18D0nSVwM136ViV1011Khw0irAk^CPMg3kIY40Ybfd0eSDe^_Koc0jxIQKhM04Y8u$0uMt^40hHf10d70g%pA304%pzDBi4$3Bi1$30*TL3H0w03^P22w0v+@Bnw80M0L_U%MwU2$KuaM1s8e02%ale022VUy10UQ3MS^Agi3NAak@0230*SqfI9x2S07XzAf6g^iV5^nUN3Nw^AFQA^rA4026Deg^M(ZxLUO3MI^Agh3NCecgYe^9}36Dag06M(Zu0UN3NE^4N6w^6niWR4^M0cM1UwN9KBM1Tzk_vfUM3NC^4Koo0gul8ow%cgo^1BLKl84$cgo^1BKel842%cgo^1BIKdgYfw01edg40w09}2jHg^5^TH8w04^OV2g10WNg01w0dKgA05eIh^c03rA8013H4g06^SV2^iUN3N4^Am13NseMk^o0vKNm4hQ0vecgYb^1edgYns0BecgYf^9980Yjui0f5RAw3NfR1gYl3zsf5U02iVB02XKpg0GI0@_M3_0bAk^vz0f4E02iVw023UU3Ng^AVkzMG%VkzMO%VkzN8%VkPNj%VkPMK%VkzN$kb3Ni52wYliV102V[GrdR0a2Ptg2gITk0IbdR0e2Ptg30UT3M@^4N4w^6kVgi1M1KcwYew095zwgg3zcf38^jzof3E^jH4M01^OV201z4KXHxw01^OVUE21UU3MO^AXbE0wQ1Bm53MKeNm03g0vKdMYiw01at9^2VWp2b[9@e0Yb^2}3z0*RUTzgf3o^iV1^V[9Y-_m8@MI09c0vbfd0bLzwf2M02ii0f5RVkPMK%W@I^g0cKuwwGrf10bWV102Vm63NieNE09s0vKe0Ygw01eO8^A0vedwYg^1eO61Qr0pud0Yd^1bDFI8HIi03UM6nIy03C07NoUf2UXeo5d01@N4w^6j1m5110eNo^Y0vKcwYm%Gu41iCDR^7IYQ02KM62LI0v981YnnBjf2U^2DZfZTUO2w4^4FQA02GsV^30*S0tg8f5MF_j@2pk0YnmDxf@Qm03MKeM6_X^vKdMYiw01at9^2VWp2b[9@e0Yb^2}3z0*RMDzgf3o^iVWr1G[erA402v0*RpTIb^d07OVW22FX2r_u21BUU3MI^A[Ksh8^1Apucwg2E0AeME0KA0vchE^1Anec0o2E0AeM80N80v5xwYkyi0f5RVkPMK^1X6r_rM1@UM3MQ^4UU3MG^4X0w1Qy1BUM3N2^4X0w4J01YUQ3N%4X0g3QU1AUN3Ne^4FN4^qtQ2Atocf2UX3ogR01@UO3N6^4FMA^uME0sQ0ved0Yb^1}7Dzgf3M^CV0w^X0w^g16go102atF^2V102g[aXDFI4GDeg0aXaI08c1BM(ZvIX2w6701YX6w2p01YUP3N6^4gu0w0rDFs1WV2^oX1c8Hy1BFSI^rA40bWDyM08FVv_T}9uDZ06PAw7Ntly0YbzIyfWz07XIGMp6M6nBjf2U^6DZfWq[xbDEg7L4i%oZ2Ptg2wKgA0KueMYb^2bA80byDZ^uUN112^4N6w^6fjN3w^6fkKuAgVI11^+_@PA02n0puNz0aYwpqsF06j0*Rxj4i%oWDz840F093I9L_x07Pz44$j4q%oX74e%oXaVWh3CM4403+_Xej_Ui1BNew^6efUM3MQ^4X1o^g3pX54ILM1lMBE02080WOk^M0dUXbw%AUX3MY^4X0w2GM5YFry^eN6arM3msgr^1zwY9a040g0eeQU%9eMj0Gcwpue0Yf^2ee0Yf^9eI1Yg^uHA40bvzwf5%jH0v4w07HIy06Y07Pzcf3w^iDag06M(ZjOUO3NE^4M3UwN9KBWO8^M0cM3Tzk_vfUT3NC^4FRAjybC602bH5M05^SV2g0nWU401w0dKgA0wuI8^c03rA8^vHw^6^Tzcf4g^jHgw04^OV2024KuAMqeNB070wprfd0eDzsf3U^iDWM01IY40DKN@06j0pp80YjvBif2E^2DZfYzN5w^6c2UO1g2^4N0w^6cgUM1i%AN2w^6caN1w^6bPN2I^6c8m60h0eNE_PQ0vIjE^1yZecMYe^1el8Ypw^qt9^zz8e%1j0*RBbI9LYF_TP0c%oJ3z43%1aDxfYwN4w^5SoUS1$4M(ZqeUO0w%kM(ZmEUO3ME^AFRA60rA402r0g%hSr0o%hX_0c%hSz0*RzmDZfXYN1w^6aEN0w^6aZUT0g4^4m43Nkbf1083Ihw0c07Xzcf3U^jzof5o^jIdwcug6logf5kX4o03g1@me3NiePC^w0vBwMYkPIe0Rb0DXzwf4g02ii0f4TVkzMG%IY40VOz8ITk0AavQ_Fbzwf48^jz0f2E^DIy^f07Pzkf4%iVWl1UX8k1_U1AKi40sbDyg0vz8f4o^jI9LUV07Pzsf4%iV0w^X0w^g16[watF^2V1^HKuCMiGsV^HIGM0fM6n0*RyDIa0gD07ODqM01gr0w0qu7_@Tzsf4^2jzkf2E^ii0f4_Kgw0lKdgYaw09edwYg^2edwYg^9ecwYgw01eME^M0ved0Ygw01edwYg^1eN60rj0pufwYaw01ePE_yQ0vecgYd^1eMu0r70plwMYbzIdw6I07Xz0f4U^iD0g01FTg6VKe0Yfw01edMYcw01aub^fIxM1g86mPPg1rX8k0iO1BUN3No^2FUgeRWv43BqPPg0GX2weCM1YUP3MU^4FOA01I-_jwKcgYq^1ed0Ypw01eJN^c03c0u8cirFs0tURfTPXC6067H5^5^SVWk1hWNk01w0dKgA05uIh^c03rA801jH4g06^SV1^CWO801^cKgw04Hfd02GV2g0iUO3No^4X18eBq1BN4w^66zAw7Ntp80Yj@DZfPNgu0w0qvQ_qDzsf3U^ho8f5cWRs^w0dMBU$4X5Q01016X2o2301@UR3N8^xFSA^ato^7Hrf4w0efHnf5c0feDZfUFUO3MU^4N3Q^5SzNeQ^5SuRMDNDL6uFQA^50MYq1gUf6oVkjND^1VkjNF^1FPA^I-_jxeMI_fQ0vF41YquDxfPUN1w^65iAw4gaIhE^1xjuc0o2E0AeM6_fg0vcgo^1xh5y04g34m%olf6mw^oliD90anm10h0eMm1yc0vKO80Jo0vKe0Ym^1eO40J^vbfd^HI20zZ07Pzcf3w^iDag06M(Zb7UU3No^4UR3NC^4UO3NE^4X8w8P01YWN8^M0cM4UwN9KBM4Tzk_vfKoo01eIl^k03rA4023H8w04^OVWl01WN^1w0dKgA04eIh^c03rA801nH4g06^SV2^iIYQ0aHDF827Ia0yxE6mPPg0GKuAg6bA801bHsg03^P27w01yEyVxw1A[9KIy^g031x2X4E0p012F_g2tKOQ_lE0vcgr^1wTuMj_mf0pudwU0w015xgUg3Im06P07X4a%oc_z8e8^2j42%ocD4i%obb42M^octoc440X3zZhM1@N1w^62PUP3MU^4VkzNC^1FQA02ecw4%5c-_k4uMC_jf_vc3w^1wz@cgU%4Gu4_iH4q%mRv0*R53zI6$jz82%1j0*QSvz8f2w02j0o%homV1^HFRA60s1%158I0M^159Y-_jZavQ_grIhwq386mi0f4_UQ3MG^4X4w2N01YVkPMK^1KuCgy@e0Yb^2avQ01Hz4648^j4a%o6f0cg0f+@VWh02X0c09c1BNyE^61sFOg0lWsF06j0*QGn4q%o3HzU60F093IVL_y07Pz46$j4a%o4b0cg0f+@VWh02X0f_Uy1BUQ3MQ^4UR3MG^4X08ILM1lN6w^60qFOI^uN50Jy0p9q0Yf3Hg^2^Tzl6%l2l0f5SFTgbfs8a^w20eLw^c03uc0Yf^1cgo^1w5uceo%9cgH^1w2@Mi0JJ0pue0Yf^9bdR0a2DZfOkN7w^5_GUO1M2^4N5w^5_UUR1O%AN6w^5_ON4w^5_rN6I^5_Mme110ePE_Vg0vIgo^1vTecMYe^1el8Ypw^qt9^zz81%1j0*QPHI9L@0_TP08%nXzz42%1aDxfZTN3w^5G0M6%4iZUT0M%4M(ZdPUO0w%kM(ZadUO3ME^AFRA60rA402v0g%h4L0c%h530*QNSDZfZjN4w^5@g[uGvQ@Y13kf4_FR4^qu40ubIy0ml07Oi0f4_F_j_9uME1ec1vKlcYkM^GvQ_2v4W%nUzzk1$ho8140m13NlbA90enI60aH07Xzkf3U^jInw17E6nI9w1407Vo4f5cX1w0fM5@U@3Nm^4[hqtb^7IV0LJE6loof5MX6g0c01@[nKdgYfw02ufwYfw09edwYe^1c1%13TasV042V1^CM(Zce[dHA404bz8f5M01j0*QGjIa0Pu_TP46%nOrz0f3U^jz010802iDZfOeUU3N4^AAw3Nd@l8Yaw^bf10euPMg30ITk0AavQ@OPz8e$j2rw$7Irg0104rH1w02^SVWi11KuxwIeJr^403uN50Yx0prA9013IcvKgE6nz4e8^2j4e%nKT46M^nM9o4340X1zXww1@New^5XKUP3MU^4VkzNC^1FQA02ecwU%5c-_ijeMC@SX_vc1w^1uOKcgo%4Gu4@Sn4m%mpb0o%gY_zI5$j0*QEnz82%1j0*Qp_z8f2w02iDmgok[aY1%13ns0M^13oI-_ibWvQ@Q7zs108^jIxwps07Vog140X4o6lM1@UO0g%4New^5WEMDU$1X7Q^g16WMs^w0dN5w^5WwKuxMobDF83XHhw01^TId0HTE6nH9M01^TIcw0kM6mVWl0eWPc^g0cKi4^XDyg32VWj1DKgw0rHAx07eVUA3CX5UbJ41Bm20h0eMC0QQ0vGt806iPtg2wUO3MU^4N5Q^5G3N7Q^5G2RMDNDL6u?hasV^9gkf6ok73NEel4YpM^ul4Yqg^s-_gpKMI^I0vF41Yp@Dt0CDAg7NFWtQ2pOPPg0rFPw^ecgYew02bAx0aLH8g01^P4i%nyiVC^PAw7NdXf10b92cf5RF_jVrBxgYbzzsf4^2jIlw0Q07Xz8f2E^jzgf48^iV2^CUO3MG^AUS3N%8US3N%AX4rZBM1YUS3MG^4X6w03g1YU@3MQ^4XerXZO1BAw3NfWvQ_pii0v5RAw3NfWvQ@wpokf2U[B@No_Z80vKeMYaw01ec0Ygw01atH^6V202SUX3MG^AUS3N%8US3N%AX0o5sM1YUU3MG^4X8o9Gg1YUT3Nu^4[KGvQ02GDC^1?amy0YtxEEf7wqc3NW6zwYv1EAf7Uqb3O06zgYwxEYf8gWS_Oi^41_Vosf2UX7zVug1@X8rZhg1YAw7NtuOH@s0wpudMYnw015wMYkzIe04w07WV2g2VUX3MI^8IY40WYiE^1tCYi8^1txbfd^XI6yCY0RCB28^FWI^s8q040g0ec1w%9ciH^1txKewww^9cgE^1tr98182z4m%nmtoU540Xeo7U01@mb3NseOW0EI0vKcMYe^1c01^Z2f@c0Ypw09at9^z4b%mnL0*QcjIa0u2_TOV1^FFVw^c-_eKGvQ_Upo4f3kW@%w0dUNVw^5gBg3NtGu4_iTzsf3M^jIcyCY0RD2ew10403zwS%2jItfQv07P46%njH4aM^njfI4LQHE6nzc608^hos640X7w3E01@N4w^5QBUQ1y%AN5w^5QvNew^5Q8N5I^5Qtm03x0eM8_gY0vIgE^1t2ucMYe^1el8Ypw^qt9^zz82%1j0*Q6vI9LPX_TP04%nenz41%1aDxfPON3w^5uJM6%47GUT0M%4M(Z2wUO0w%kM(Y@WUO3ME^AFRA60rA402v0g%gnz0c%gnT0*Q4GDZfPeIYQ0jHDFg6uPMg2mX7g2UU1A[4ecMYfw01bfd^OV2g0gX3o04i1B[lGt9^2VxM13FOA^}36VxM0B[4@cwYfw01eMx@wSwplxgYkPImfEi0nXzUf3U^jzcf5o^jI3w010dDHk^1^OV203BX3U93Q1BX5w9Ww1Ym43NseN4@uY0vKfwYfw09avQ_jf4q%n8D42%n8aV101mX0o3ny1Bmb3NseOW1@40vKeMYf^1edwYdw01chr^1sr@eMYb^2uNH0YL0pud0Yd^1bDEI8DIi0fN07PI9^20dCD6^_FXD+HC302bz8f2U02jzcf3^2iDe011mP3MLbAk^eVwM0w6NaV8g1b?UuPH^40hIhE^1sa@dgo2^9edgYaw01eNo2ok0vecMYd^1asF^2VxM0KUX3MG^4U@3MW^A?t@dMYcw09el8Ybw^ecMYfw09ed0Ybw01ecgYd^1bDFgeKV1^xKgM0bHA403aDag^Kos0a@eMYew01bA4^fIIgllM6n2fw$7I3g0104rzof2U^iDKg^UM3MK^AIY40HGvQ01yVWo1a[aasV^H0*PXTIa01907Pzsf2U^iDKM01go0w0uOT06CwpudgYaw01bDEo7LItgfcE6nIGf_y86nz8f38^iVWp18UQ3MI^8IY40N}3iDig^M(YUQUQ3MS^4UO3MO^4[es-_cOuMI0WE0v}4aVW22F[ym30Yb2V1^EFPA02I-_ft@MC_XQ0vecwYcw01at9^2VWp2aUU3MI^8[ec-_e1ud0Ydw01ecwYcw01}3D0*P9HIb0qL07Pzwf2M02jzsf2U^iVW22F[yuOT_VR0pudwYbw09bDFA6zzof2M^yPMg3CXbzZPw1YN4w^5JiU@10ag2gXeo3ug1YUO1$4F_g3tKc0Yaw01981Yj@V2^6[B@dwYg^2ec0Yaw09edwYg^9avQ@h3H9w01^TIgLMWM6mVWj01WQg^g0cKi401bDyg42VWk2SKgw0IrAx06iVUA0rF_jY9KlcYbw^avQ@HL4a%mNXzcf3w^jBif6o^6Dig08UO0w%kM(YVYX2rVP_ZYM3%5HWUN0M%iFUjVNIjE^1lMKdwU%1c-_eKecw8%5c-_dQKcwYa^9atp1HaV1^CM4%3@gM6%3_FM3%3@iM(YVvF_jVEHAk02KDig02M3%3@YM(YV3X2rZrLZYMa%5H1UN2w%iFUjZpsi8^1lys1w%_GI-_ev@dMw%1ecw8%5c-_dBKcwYa^9atp1VGV1^DM4%3ZkM3%3ZpM(YUCF_jZgud0Yj^1at1^6DtfIrUM3N8^4X53Tg21BUP3MQ^4UN3Nq^4WPc^g0dF@w^rAx01fzof3U^iVUI0NXeM^w12UU3Nm^4UP3MQ^Ake3NjeNE06ywppk0YnuDt01zKoc0gXfd02SDu^_IYQ0nNJQ[1rAo^v2fw$6VUJ05KgM^HA401n23w$7I3g0104qV2g26KgM06eJ1^403rA8047Hd^1^TIc0vNg6mDag^Kos08}edosf5MX7g0bw1@US3MU^4Ki40zHDyI8X0g%fIGDeg10[m}2r0*PvGV1^S[gHAk02v0*Pp7Ia0vT_TP46%mxfzwf3U^zzwf3U02jzw10802j4y%mwv42%mxzzgf3g^jz088g02j4W%mvKV0M0QUP3y2^AVkzN8%F_jSEk9gYnmi0f4_F_jS2p80Yj@DZfvaUN3MG^4X1zXZw1YUP3MQ^4Aw3Nf@MNZZswpqvQ@nTzkf3U^jH5g02^TI7Lt4E6nI9Lt107VoUf5cXerZdM5@UU3N4^AVkzMG%Aw3NdXf10euPMg30F_jRRKcMYe^1asF^r0*ORzz4f6w^jzgf6o^jHsg03^P07y34CWn07udjZY@Vxw1xWNg01g0dKuB0kuIl^o03rA901nH4g03^SV2^kWN401w0d[9KIy^g03bA801aPPg0GKgA04KcwYm^1eMi1Dawpsh8^1puqvQZcDzg6$j2fw$7Ifg0104rHUM02^SVWk1iKuwM3KJM^403uNn1kZ0prA902XI8vBHM6nz868^2j4q%mlr4aM^mmJo8640X2zVng1@N1w^5BnUP3MU^4VkzNC^1FQA02ecw4%5c-_cJuMC@kD_vc0M^1pc@cgc%4Gu4@k34u%k_L0*Pfjzo7$jz82%1j0*P0Lz8f2w02iDmgok[9I1$ZOs1w%@8I0M%ZOY-_cCavQ@hOVWm3wN2w^5A9[5KNefHY0lqu402vIi^k0nPIhwlV0DPzIf2E^jIciGZ0BDzIO%hHzIf2E02iD6M01UU3MG^4X44GLg9pUUgw^4qUU3MG^AFNI^uM10360pecMYaw01eLK^803eONaHQ2muN1^40SucX8^16KO4aHQ2muON^80SucU8^16KNbaHQ2muO1^c0SucQ8^16KOUaHQ2mqsr^jzeO%hGDV+tUP3MG^Am13NseMq12E0vKMRarM3ms8W040g0ec38%1edwYdw01ak4v+z0f3M02jzIf3M^j4mM^mavzIf2M^DIq_MX86nzwf3M^jzEf6%iV1^U[aGt9^30*OMrzgf3o^iV1^G[es-_9Ded0Yd^1ee0Yb^9bA20abIHg%4r4m%m7WV202F[yuN6_1k0vavF^6DZfMLX0o5Fc1BUT3MG^4[KKNS@d^v981Ynmi0f4_F_jQrqt8^2DZfDJN3w^5xnUP0i%AN0w^5xhN7w^5wWN0I^5xfme1N0ePC1680vIgo^1obWvQZLnzcf3w^iDag06M(YDdUN3NE^4UQ3NC^4WT4^M0cM1UwN9KBM1Tzk_vfKoo0ouIk^k03rDFg57H5g06^SV2g0lWN4^M0dKgw05eIh^o03rA402rH8w04^OV2^iIY40EqvQZJbzUf2U^iPPg0qUS3MK^AKuCga}3Xz8f2M^yPMg3yX3LYzI1BUR3MG^4X7nYya1BX8HYxk1B[IqvQ01Tz8448^j46%l@j^g0f+@V2g0iX1^dY1BN3w^5v5m50N0eNm0ek0vGsF06j0*Oyf4i%lXzzU40F093IVL_v07Pz84$iDZf_sUN3x2^4N6w^5uXN3w^5uYKuAg1I1h^+_@M502n0puNz06gwpqsF06j0*OvP4W%lV7z8e0F093I9L_x07Pz4e$j4q%lVD4e%lVGVWh06M5403+_X0n_Ui1BUM3MY^4N4w^5tQFgy^eeMYd^8eI8Yf^UKPCbbY0luIK^803ueOg^1katH^7I5yCY0RD26w10401wUk^MKE02080N6I^5tDWRU^M0dUMl$AX6c0Ly1BUS3MG^4UX3MK^8UX3MK^AXbrVJW1Boe3MY}bqDZfIMN4w^5sRUO102^4N7w^5t3UT12%AN2w^5sZNew^5sCN2I^5sXm13x0eMo_Uw0vIhE^1n9@cMYe^1el8Ypw^qt9^zz86%1j0*OEnI9LZQ_TP0c%lMfz43%1aDxfZHN5w^57bM6%3M8UT1g%4M(YG@UO0w%kM(YDoUO3ME^AFRA60rA402v0g%eVr0c%eVL0*OCyDZfZ7N7w^5rDUP3MU^4VkzNC^1FQA02ecws%5c-_ahuMC_MT_vc1w^1mM@cgo%4Gu4_Mj4i%koL0o%eYzzs4$j0*ODXz82%1j0*Opzz8f2w02iDmgua[9Y1$XlI0M%XmY-_aaavQ_K3zof3U^iVVz0CFUg2DucMYfw08uIdYfw0UGvQ@GvzU408^hos440X7w0lM1@N0w^5qoUM12%AN2w^5qiN1w^5pXN2I^5qgm50h0eNo_OM0vIjE^1mvecMYe^1el8Ypw^qt9^zz8e%1j0*OtHI9LYo_TP0c%lBzz43%1aDxfYfN4w^54wM6%3JtUT1$4M(YEjUO0w%kM(YAJUO3ME^AFRA60rA402v0g%eKL0c%eL30*OrSDZfXHUM1$4MKU$1XeQ^g16WOU^w0dKuA05HDEU5bHtg01^TI5M22g6mV2g1yX3r@Qq1BUS12%AN3w^5oiN6I^5oDm60N0eNE_Ic0vIjE^1m4@cMYe^1el8Ypw^qt9^zz8e%1j0*On7I9LWL_TP0g%lu_z44%1aDxfWCN7w^52TM(YCMUS1M%4UO0w%kM(Yz7UO3ME^AFRA65}2r0g%eEn0o%eJX0c%eEv0*OliDZfW2M1%5n3UN0g%iFUjUuYgE^1gy@dw8%1c-_9wucw8%5c-_8C@cwYa^9atp1VKV1^CM4%3FpM6%3GzM3%3FrM(YAEF_jUl@Ie^403uMg_U30puIx^403bDFc1qV8g0iKu908rDF85WV201mKi40UHDyg6mDZfZIN7w^5meUP3MU^4VkzNC^1FQA02ecws%5c-_8XeMC@1b_vc0M^1lqKcgc%4Gu4@0D4i%k3bzo4$j0*Oizz82%1j0*O4bz8f2w02iDmgup[9I1$W0c1w%Wms0M%W0I-_8PWvQZ@nz8f3o^j0*O0uV102iF_jLicho^1lechE^1ljucwk%1bA906bIp04n07OV1^SFOA^ecwYfw0x@cMYmw08rA4^fH2_5E0eb23w$7I3g0104rz4f3g^jI404yg6nI4fafM6nzUf3U^jzgf38^iDWM03XejOx21BIYQ0e@PzYDYwpuc0Yd^2c8e$0@Jw^403eNJ^40hKdwYd^9cg8^1l0rA302rz058g02j4m%lemi0f4TUO1i2^AUU3N4^AVkzMG%VkzMO%IY40VOz8ITk0AbdR0b2DZf3IX58FL0dpMBE0g1^UUlw%AF_jQLec0Ybw01bf10eyPPg0qUS3MK^A[c}8GDZfPfUR3Nq^4X5M1Yw5ZKoc0hqtE03@D6g^6SiV5^CIY40YHf10daPPg2tX9rKow5YF_jKsch8^1kBF81g2GDZfpxFQA0244MYoz4b%kbD0*Nr2DZfphN2w^5i3UR0w2^4U@3Nm^4Xek1ui1B[U}5rIVvwiM6n4a%l72DZfL6US3MU^4UR3M@^4M4%3A4FPA0g}2r0*O3qV1^S[gKcwYn^5c-_7PeMCXIP_vc0w^1kiKcg8%4Gu4XIf4W%jNbzoe$j0*O0zz82%1j0*NObz8f2w02iDmgpG[9I1$UUc1w%UPY0M%UUI-_7HWvQXF@PMg3hITk0YavQ_U6i0f4_[KGvQYX@D2g01F_j@_@J3^403uNk@Hf0puLB^403bDF45aV8g1uKu90VrDFU0eV2^2Ki40fHDyg22DZfGvKgA0yue0Yb^2bf10eyDZfpHN1w^5g4Kgc0Uecgkx^9ch8^1jW980YjvzU48802jzwf4g02jz0f3g02jBif2E^2PMg3DacyPtg2gF_jLYsho^1jTecMYe^1el8Ypw^qt9^zz85%1j0*NPHI9LKg_TP0g%kXzz44%1aDxfK7N6w^4W0M(YtVUT1w%4UO0w%kM(YqgUO3ME^AM6%3yK[9Wtp1w70g%e4L0c%e530*NNSDZfJzN4w^5egAw7Ntp80Yj@DZeXuKgA0UavQZi7zwf2E^jI5yGZ0BDzwi%hHI5w010dDzwf2E02iDZfFXm63NseNAYeo0vHA405fzkf3U^Dzcf3U02iDZfgBm33NseMQZ4o0vKd0Yfw09atp^6DZfgpU@3N2^4XejOYI1BUS3MG^4X6rOZg1YAw7NtqvQZr3zcf3w^iDag06M(YjGUN3NE^4UQ3NC^4WT4^M0cM1UwN9KBM1Tzk_vfKoo0ouIk^k03rDFg57H5g06^SV2g0lWN4^M0dKgw05eIh^o03rA402rH8w04^OV2^iIY40EqvQYjii0f4_VkPMK%F_jOIYh8^1j2HA407GPtg2wF_jLeecM8%1}e3I0M0eM6mVWj2MUX3Nm^xWXLNm03yX5I01Q1B[lGvQ_DDzof3w^j0g%dUqDeg10KgA0JrA402qV101rM(YqQ[dHA404bz8f5M01j0*NAHIa03s_TP46%kIPzIf3U^zzI10802j4W%kJv4m%kJyDZfVaVZ%g12ITk0YavQX8WV102WF_jOjKfw4w^9cgo^1iHsjH^1iMBxM4g3Itw0m07X46%kGaDZfg@KgA0yue0Yb^2bf10eyDZfkfVkzM@%F_jM1YjE^1iC@cMYe^1el8Ypw^qt9^zz8e%1j0*NvDI9L_s_TP0k%kDvz45%1aDxf_jN4w^4Q_US1$4M(YoRUO0w%kM(YlfUO3ME^AFRA65}2r0g%dMT0o%dSr0c%dM_0*NtODZf@LF@A^qvQ@1r08%kAvz42%1aDxfcvN5w^4QfUS1g%4M(Yo5UO0w%kM(YkvUO3ME^AFRA79HA402r0g%dJT0o%dMD0c%dJ_0*NqODZfbXM5%58rUN1g%iFUjU1IgE^1cUY1w%SY@dM8%1c-_5RKcw8%5c-_4YecwYa^9atp1OqV1^DM4%3qKM3%3qPM(Ym0F_jTUI0w^1hX@cg8%4Gu4_O74i%jbv0o%dEHzw4$j0*NqHz82%1j0*Ncjz8f2w02iDmgt2[ac1$SwI0M%SxY-_5lavQ_LQ7]1MvI8w090TWDa^1X28_LM1l1_XHr_0M02jz8308^jzYfWoXT6V102PFQA02GsV^30*NhiV101yUO2M4^4FQA02GsV^11Af3oM(Yk6[sKcwI1w01at9^GDeg^M(YjWk23ML}ab0*OB_H0w03^P22w0v+@B7w80M0L_U%MwU2$KuaM0s8e02%akK022Bfw01k33MNbDyQ0aV5016UQ3MG^A?l@dgYa^952wYc3zAf2M02jHI^1^R1Af5EFWA^ecMYb^1ecwYaw01c-_5OuMA06U0vKfgYgw01bDEI7HIvg1d86mV101JUO3MG^4[eqle^7zk7^Y770*MZ@Deg0a[gHA402DIj01i07P0*N5eVWp0iUZsg0v1NKuCwjrA4^bD2A%6bz8f2w^h1cf38FQA04eM803A0ves0YcwM3I-_4x@ME^MgvavE^7Ibz@_05nHr_6o40g7_HA40aSVWa1XX7r_KY1BFQA0pasV^518f30M(YcrX2P_Cg1@FQA0244MYczz8f2Y01j0*MwXIbf@c07ODW%F_j_R@sGI%oKcwYa^1eswYcwM3A4MYcyDig0gM(Yh7X2r_MN1Y[FWvQ_YA71@My^A2vGsE^7I8z@_05k7_KJLY3^9ecwc0w01efM@R3_srA40beDig0aFPA^c-_45}8bz8b0g^iDig0aFPA^46gYb30*N0qV5^oUN3ME^AVkzMG%6d91sf30FXA^ecwYa^1}3CDigg0M(Y6LX2M0d01YWM801^cX0P_Y01@FMH+XDFA3vIg1OX15CV102FURdfYfZNWSk01^cFSI^ufwE%1ePH0220pePH050wpquH012Dp+RUO3ME^4[eqt91030*MnXI8L_i07ODa%WS_QU^4X28_LM1l1_XzIa08^zzgf2E^aDt^lF_g06Ke0g1^1eeMg0w01ee0Yaw09c-_1HeO8^M0v}4yV1^AUX1$wFUj_WKNr0bc0luNs_Y40vat9^2Deg03?bs-_1YqvQ_XmDag0oM(Y9GUM2w%4gj3MGec08%9}83zwa08^zzw20802jz4f2E^aDt^bF_g03A4M413z410g^aDx^7UM0g%xFOj_ZKcg81^9ecwc%9avQ_UnI8w090DWDm^1X2k_LM1l1_XHr_0M02iV102OUO0M2^4U_3XifZN[EWt9^GDeg^M(YcO[oKcwE1^1at9^GDeg^M(YcCk23MHeOU0gk3vKcwE1w01as8^304%dcOOng0iFNj+H8y0729s^2yD^7x07FMH+@IM01Y0TB0MYaz0g%jVPzk4$aDx^4Aw5garAk08rBif2M^3zwf2w02iDKg^FWA^460Ybx1Qf38UO3ME^4[eat91030*MafIb^O07PHUw04^PIXf_M07WVWo1JF@H+XA409zIbxOX15Dz5y_M_T7Hsg04^PIpM010dDz09$jI2w0ww6jI2w1C86mDCM0gFSv_ZqvQ_YWV1^HUX2M4^4M(Y31Xbr_@01YFVw^eMFfXY0luJLZew010v@UW2g2^8Xbo05w1YF_g06KdMI1^1eewI0w01edMYb^9c-_0EuNU^M0v}buV1^HUW2M%wFUj_WI2M^1f6KfwI$Gu4^nzEe4802ho8f2EX2o05M1@N4w^4YaX1EFL0dpMxE0g1^UM5$4X501IM1lX101IM1lFTg0dueMYb^1avQ_V@Dag0oM(Y57UR2g%4gj3MIedg8%9}4nzg908^zzg20802jIJw0c07ODZ^egj2M4eeMI1%Gu4^vzkb%26D9f_SUX0w4^AUO0M%AF_j_PWt9^2Deg03UO3MH^kM(Y2kUX3MI^4F_j_oKlcYaw^avQ_Nk7]1MvI8w080DWD2^1?80v@WS_Mc^A[wKcwc0w01efMZbz_srA40aeDig0aFPA^auU^30*MvCV102iUO2w4^4FMw^ecwYcw09c0g%PEr9t01aD5f_@Iy8^c0M^1euoA%aa%uk03MMeltc$rCo0bLIy0j70TV1oa0oMe%3e8U@3MG^AMa%3e7UW3MI^AX4z+03oFTw^bAm05jIRg010dDzw6$jz8f2E^iD2%[6b9t026D5f_@Iy80cedgYb^18AM^aac^u44eDiL+X7g_fO5mIBQ0mask+WO8w^FSI028A%aa%u4e2DWL+XbU_fO5mFZv_Qk9MYgV1cf4EFOA^s-_2A@MC15I0vBxMYk30uM^Y030tM^w02DuL+X6s_LO5pgC3N3XAk09DzAf3U02iVB02Xkb3MI47gYQzzQf3M02h1EfdEUW3N%Agi3NKecwYdw0944gYi3z4f3E02jBif4o^3Bjf2E^2Dug^FUw^ecMYf^1ecwYfw01at92030*LL_Ib06907PHcw05^PIff_L07Xzkf4e09jz0f4f09jzEf3M^hgkf48k03MNasW+_IgNKW1lDzgf4%zzgf3g02goq5zwYb1oIa04m82w0ePC0gU0vBygYgzIBwe707XIq0cjo7po4f30X1w0f01@6ezzkf38^h1Qf98Kho0rI1$OMqsV0g2V1^JM(Y5B[bqsV^30*MhWV102iX2E1qw1@m33N2eMU06Q0vKeMYd^1auH023IKL@lw6hokf2Mmb2w15zwE03Ilw4H07VoAf30X9r_OM1@UP2w4^4m53MNecMYAw095w0E0Pzoa0o^jIm08X07XIq^N07OV5%UM3MK^Agu3OiefwYe^9avo^2DCg^UQ3MU^4UP3MK^4KuCglGsF^70*M72V0w0yFQg28qtQ0D@Di0fDXdg3mI1SUP2w4^4US2w6^4m02w3eN30bc0lrA803qV5^wKuB0kWsV^f0*LKZocf48X3r_Cg1@m23MIeME0C40vKOQ0H^vKI1Yaw0qKNU0BQ0v5w0Yb1oo7^X0w1pg1@X8o0jS1SUP1M1^nme3MGeM@0GVwtBwwYc3Ia03P07XzQf2E01rzkf38^jzQf2w02h1If98M4%387FPA10}2KV5w1EM(Y2K[aWsV^30*M6so4KMG0ls0vKeMs2^1ecgs0g04HA402uDh05SWM7MG01GUX3N6^AM(XWMXbw2Tg1Ym62M0}7LIxL@Tw7rzof3g^iDGM0wXar@NU1A66xoIa04m82w0bAn09LIq08Ww7po8f48X2o2Wg1@FOA0ac-@@WJ8f802w0d8f812w4eNU0JY0veeME%5HAm08DIyM0v85p1If4oF_g02k6Ms23zs70w^aDx0a2UQ1M%mUN1M1^nX1g07O1mX87_Y21BUT0w8^AUO2M%AUT3N6^4UU3MQ^4FWI08eOa_Gtwp1y6F_j@tHA402vzs70w^j0*LArItL_U07ODy%?aeJL@Tw010v@Khs0CRxwYc3IqfXp07Xzkf38^iV5w0VUP3ME^Agt3OibAm06X0g%clmDeg40[bs-@+HA402SDeg^M(X@T[AKMA_FM0vKcMYdw01el8Yi%c-_0yuMC^w0vKcMYuw^GsA0uOV1^FM(Y2I[bs-@@BWvQ_DXzc70g^hogf34UP3Oi^Ame1M3eeMs1w01eN809E0vKOU02I0vbAk01Xz4f2U02iDC%FSA^ecMYbw01bDFo5J1gf98FOA^s-@_3rA2^aDh02qFTg0HqsU0@vIAM5qM7rzc70g^jzI70o^hoU70cX4c0IM1lKgw0eXAk02WVWk1jFPA^Y-@Zz5wwYb3I9LXD07XzQ70w^iV1^DUZ3N6^AmE1M2c-@ZCKPo0mU0v5xwQ02V101ZX8o1hm1Sm43MMeN8_VA0vKdgYcw0146MYAz0g%cbyDeg40[aXAm06z0*LRGV1^HFPA^c-@_4NwiX2j_OM1@UP3MS^4VkzN8%?ArA402D0*L@bI9w0807XzQf7E^aD901A[as-_01rA402L0*Lv2DZf@A[iXAk02X0*U@KDZf@5UX3N6^AFUE^s-@ZfuOU0nQ0v5xwI03Bjf2E^2V101XF_j@fI-@@_Bxg802Dag0aX5w01wh@X5r_pgJ@M(XShX6L_i41BF_j_nbA8062DC%F_j_ZXA404qV5^wM(@ePF_jZWI-@@SBwg802Dag0aX1w01wh@X1rZTwJ@M(XRJX9rZM41BF_jZRud0Yew01atF^2VWm1tUO3MU^AVkPMK%[eqsF^70*LyiV0w02FQg09GtQ07Jokf2UF@w3V@Nu_U0wtKI1Ybw0qGsF06j0*Lj_IRLZRM6nzgf3E^iVWm1t[eqsF^70*Lw2V0w02FWj_TI-@@ylx0802Dag0aX4z_UMh@X4r_m0J@F_j_TrA809aDS%F_j_H5G0E0zItLSF07PzQf3g^iDGM0wXaTYMU1Am42w05wgYb0oq5yME0goxeMm_vA0vKNE_fe0tGsF02z0*Levi3O^E03i3O0gE13Iu03s07Nowa^gr3N6avQ^B1I70wUT1M8^2FUg0xlm0s02D9f_TF_j@2Wuq^6Dag1AF_j_gRwMYeiV201wk33MKavQ_V1oQf2EX9TZNS1S6eyDZfUuVkPMG%FUE^qvQ_l7z8f3g^iDGM0wX2HYrU1A66xoIa04m82w0avQ_abzkf3g^iDGM0wX5HYo81Am93MI5yME0howa^X9zYAw1@F_jZBudMYd^1auH023Iuw1Ww6goq5yME0howa^FTA^avQ_7UoW1y6F_jYJKcwYh^9elcYbw^52MYe2Dqg^[I@d0Yew01bDFo5KV1^VFOA^s-@ZfXA205aDh^jFTg0cRx0YbyDa0fDX480gs1Smb3MUavQ_u@Dug^F_jZyI-@ZJRwg802Dag0aX1w01wh@X1r_XwJ@M(XNaXbr_PO1Bmb3MUavQ_tgoqatV^2DZfRTFZE^qsF06iDZfXame3N5bA806lgUf2UF_j_WelcYaw^1xEFTA^avQ_m6Dq%F_jXI@I1Ybw0qGsF06iDZf_iFTA^avQ@Z4oW1y6F_jZrA6MYhyDZfR1Aw3N3GvQ@Uk7=]1MvIb06R0nXHr_0M02iV102OUO0M2^4U_3ZEfZN[EWt9^GDeg^M(XPMUO3MO^AXbw1zwd@FTw^c-_2kuIi^c03c8q01+_WkK0w306+w^327w8%2VUH0iMxU08%FtU08c0w%KBrDy8d70*LhzIa03R07ODig0aFPA^c-@YLHA406bIb03F07N18f3MM(XHAX2o0WM1@VlTNm^1FPw^uIOYlw0YHAm04fzgf4g^OBzww0[lat9^2VxM16MBU8$Ku8wxue0Yc^9bAk07t1cf7g[9Y-@ZC@MC^Q0vBxgYuyBDU^M5I^f^X5A1d81SVkzME^5UV3MP^k[rrA404CV1^DFRA^asV^30*KBKV0w22FQg0FWtQ0Z6DKg^FqU10el8Ya^1rA406SV1019[9Wtp^2Deg^M(XF1[wKMI09s0vc1w^153@c0o%4GuA0aOV202UXbH_Us1Bgi3NoecwYaw09c-@WpNy2X2o0nw1@VlTNO^1FQw^uJ2Ysw0YHAm05jzkf68^Pz0f3%jI1g1bM6n04%ibnz41$aDx012UV3MO^AUV3MG^4UX3MI^AUW3MK^AFSw3W}b2V5w2AKho09xG6M(XI0[as-@WaXA403Hzcf68^PH9w010dMq9KOP0170ps8J^66Ec1F^66Ec3F0sD3vXDOg6bIzL_uM7rzIf2M^jzEf2U^jzAf38^j2Gw4%2DZfZQFSA0w44wYf30*KvPIafYr07WB3ww0UM3MM^AF_j_cc-@Y7RyM802V102yXbw3aNp@M7%4hZUU1M%iFWg02GvE^2V5^KWS_OA^41_XBif5w^6V5^EFQA0244MYm30*KWODZf_IVkzNo^1?8at9^x1cf5wM(XKuX2r_iLZYMe%4wsUN3w%iFUj_gsgU^12Vedwc%1c-@XSKcw8%5c-@WZecwYa^9atp2K6V1^CM4%2OOM6%2QVM3%2OQM(XK1F_j_7ucwE1^1at9^GDeg^M(XJl67aDZfVIFMw^rAk0207_Kl8Ye%ecMYw%Gv4_U_zgf3c01jzgf2E02h1kf3EUR3MI^Agg3Noec0Ybw09auF^2D6g^FoU10}9Tz4f3E02iVWh13[SrAx04CVUA3kXdw0Bw1Y[7quV^2V103q[EucMYb^1ed0Yaw01bDFI6HBif2w^2V1^DFRA^c-@VRrA203aDh01mFUg0ObA80bfIG+C86nz4f3w^iV102JKgw06@cgYe^9bA80aL0I%gX7zkb%1aDF01KUP3O%4X37_aY1AX8H_IW1BUO3MK^4M(XA766bI9w0u07XBnv78^6D2^1WMbNO03OKho0ged0Yow03ecwYc^1eMA^L0ps2M^17lucgI$GtQ0ubz4f3w^jzcf8%j2yw4%2DZf@2M(XIam60w0eNE_WI4vHA40aTI9zWY05nIa^94DXIq^69DXIpwdRnTXz4f3w^jIJL@v07Pzcf8%iVWh13X480lM1YFXA^bA801Lz4f3w02j0I%gQnzkb%1aDhf@mUP3MK^4VkzNo^1?9qt9^z0*KDTIa^8_TPz4f3w^iDZf@1M6%4rSUN1w%iFUj_ZsjE^11LI1w%IaufgU%1c-@WIucw8%5c-@VO@cwYa^9atp2GiV1^JM4%2K9M3%2KeM(XFrF_j_QrA40aSDZf@w[SuMN_DL0pedgYcM05edgYb^9440Ye3z0f2E02jIG03S86nzgf2E^jz8f2M^iV101t[dY-@VVrA20baDh01jFUg0ms2g^12QKc0A%4GuA^WV202HUV3O%4UV3MU^wFOj_SGvQ_AnBif5w^6V5^wFQA0244MYm30*Kv_I9L_E_TP04%hDTz41%1aDxf_vN3w^455US0M%4M(XEXUO0w%kM(XBlUO3ME^AFRAaJHA402r0g%aNf0o%aVH0c%aNn0*KuaDZf@XM(XEtm20w0eME_Xo4vKd0Yw^1edgYe^1eNk_vGwp44wYez0*KAHI9LTO07WBjw0gFPA41@cwYeM05c-@WruegYe^146MYm3zIf2U02jzAf8^22DF01lUV3MI^4UZ3MO^AXaw2eO1BUS3MO^4UP3MG^4VkzME^5[9Wtp^3zgf3I01j0*JSjIb^T07OV103qFXA^}aaVWr1GFRA^el8Ya^1rA404CDeg^UO3MW^kM(XtaKg80kGv40n2V202RXaL_Wi1B[Hs0g^124Kc04%4GuA0rvzgf8%iV202HUQ3MU^wFOj_JucwYew05c-@Wt@cwYeM05c-@WsqvQ_nB18f5wM(Xtq69bI9w1c07XBnv78^6D6^1WNbNO03OKho0cucMYbw09ecMYow03edwYc^1eNz03r0ps0w^15Fucg8$Gu402SDq0fEKho09xGmM(Xw0gi3Noc-@Ta@d0Ybw01eeMYc^1ed0Yow03eJm^40T1FmXbg04s1BMBQ^oqwM6A^oqwMeA1Osd_Kv90puOu_ZH0tIaa0g%avQ_HzzAf3o02jzAf2U^jzwf3g02iV5w1g[SGuU0@yV1022[FrAm02IqqY-@TLXA402D0*JKGV1^WUP3Ny^cWNI^g3s6xLIwM0hM6n27g01xG30Kg01xG30Wg79MT@VYA2NX6X_TI1SUU3MQ^4UV3MS^4[HqvQ_u2BHw40FXA^avQ_4p18f3EM(XAHX2g1pw1@FkU04asV10vz8f3I01j0*KkWB7w40UN3MI^AUO3MP^kUO3MG^Agm3NoedwYbw09aup^3Bif2w^mV101J[9Wtp^3zgf3I01iDeg^M(Xpb[wKMI_NM0vauV^3zgf2E^iVWr1EVkzME^5FRA^asV^3z8f3E01j0*JzaV0w02FYg0irA80b3IKf_Eg6n0c%gfPzg3%1aDF01xUO3MI^4Kgw0C@MF_Y2wpucwYbw01c-@SkNy2X2o0801@VlTNO^1FXw^uKOYsw0YHAm06KV1^6UM3Ny^cU@3MM^4Xe^2Y1BM3%4ivUN0M%2FTg0_@cwYb^1c8G0g%ecwYb^9avQ_USDx^ame2w0ePE05E4vKPE05sbvKOb_Xj0pqvQ_GSDx^dM(Xx3m60w0eNE08I4vKNE08wbvHA40eGV102JXeL@yc1BF_j@B@cMYbw01el8Ym%rAk02iDig08M(XvlX2r_BfZYM5%4hjUN1g%iFUj_yYgo%_6@cwE%5edw4%1c-@TbKcwYa^9atp2MeV1^CM4%2zIM6%2BPM3%2zKM(XuXF_j_qGsF^H0*JFiDZfZoUP3MK^4VkzNo^1?8at9^z0*JVnI9LU@_TP0c%h1fz43%1aDxfURN2w^3XrM6%2B6UZ0w%4M(XveUO0w%kM(XrEUO3ME^AFRAaRXA402T0g%aar0c%aaL0*JTyDZfUhFOA02I-@SkqvQ_vTz8f2U^j0*JnAooKMC01U0vKltYsw^qvE^7HUL780faV5w3uUZ3Ny^cUM3MM^4X0Q02Y1BM1%4f7UN0g%2FTg0osaa0g%avQ_q30s%f@HzI7%1aDF^aF@w^rAk02XHr_ag^g7_Kl8Ym%rAk02KDig08gj3Noc-@T6qvE^6DZf_IUW3MQ^AUW3MK^4UV3MO^AFXw3W}9WV5w0H6EL0*JvaV1^GM(Xkt[hKd0Yow03eJr^40T1FrX9g04s1BMBQ^oqwMbA^oqwM1A1Osd_Kv90JuO1_ZX0tKegYcw01eewYd^1avQ_ILzAf2M02iV103qFXw3W}92V5w2KKho0aNFHM(XmWUO3MK^4M(XjA[eKcMYow03eIH^40T1EHX9c04s1BMyQ^oqwMbA^oqwM4A1Osd_Kv90IKNA_ZT0tKegYb^1}aSDZfZH=1MvHH_1g02jzYfZo_T51cf2AM(XsQ[IKcg8$Gu401qV1^OUO3MF^kM(Y1p6aaV1^HM(Xj_?aKKLYfw010v@[aWuE^70*JfaV5^GWW_M@^41_U7=]WW_Mk^AU_3_mfZNgj3MFc-@S_}bbz42$aDx^m[cKcwYag05c-_s4hyy[aY-@QNXAk02HHH_3U^g7_HA402KDG^1M(XiW?aKKLYfw010v@=]1@JLY3^9}e_zYfWE_T6DW+Uo83w044MYiz0*JHWV102OUN0w%2FUg1WRywYizIH07x1nXz8208^iDig0aFPA^c-@R@}dbz8b0g^iDig0aFPA^c-@RXecwYaw09ecwI1w01at9^GDeg^M(XnvUO3MY^AUO2M8^4FQA02GsV^30*JtaV101yUO2Ma^4FQA02GsV^30*JsqDbwg061bI6Mg^4aD7w01X1Q^g12k13MO}8bIG06J1DXz8b0M^jz02%9jIAf_f0dzI206scnWDeg03?9I-@SsrA405aBmMw0?9GsV^iV5015M(XpAX9o1Dw1@FnU10bf108vzAf3801jHug02^SV1^DM(XhO[EKME0m80v5wgYczIV+_0dzHgg010dYqgl10YcPHbw080dWV1^WX2w02w1@R_YM03^gj0N0asC+KV5w1ugk3Nccpg%2u@l8Yj%qtp042Deg02FOA13I-@QYecwYc^9eME0zw0vc2g^11S@cgA%4Gu4^nIww9c0nXBif48^zBif4o^7Bjf38^6DCg01UO3N2^4?Ts-@Q7eeMYh^9ecwYg^9ed0YaM05ed0Ydw09ee0Yfg05bAk06rzof2M02h18f4IUO3MK^Agl3NeedgYe^9elcYez+@lcYeM^el8Yaw^efgYd^9ee0Yfw09avo^2Dy%FnU0gecMYbw01ecwYb^1at9^j0*IGXIa02R17NoIf3cXbw1gI1S?mbAd04CV1^A6bbz0f3%jI1w0Q07No4f38X1w0bM5@UP3N%4m63N3bAk05LI9L+0dzzof4o^iV5w3yNK$7AX1k3L3RpFMA^uIwI%3ucxc%wucxc%9}4fHlw06^SDeg02FOA13I-@QibA207vzgf3o^jIu1%4rz8f3g^iV101DVkzME^5FRA^asV^30*IE6V0w1yFQg0DWu40azzgf2E^jzkf3w^jD96%6aPtg^VO1g030eVMI^20yVMQ^i0yo01g4ecwYfw01}3mDig0oM(XhXX2o0xxxYUM3MG^4?e@Lz^803lwuE02V2^6UM3MG^AFNE^l0uE02Dyw01FZE^uND0hm0pelcYeM^al@041gIf3EUP3MK^4UO3MI^4FQA01c-@N_eMC_R44v5wMYiNoUf38X3X_fa1TX1cuLg9pUM6w%iFYj_cWsa+Zg0q^F_j_bs0w%C0Y-@NXHA402KDS^1M(XaD?bmy0Yl3Hr_68^g7_Keg8040BavQ_CiDeg03?9I-@QQWsV^iV1012?9Glb202V5014M(Xj6FjU80bf108eDZfVBM(Xhdmb0w0eOU_L84vKOU_KYbvKegYc^1eeMYh^1eOo0bQ0vecwYg^1avo^30*ICiV1^GM(X9vUT3MG^4UW3MU^4UT3Ne^AVkzNg%VQ0f^14o42w4}3Hz8f3Q01iDig0oM(Xf4[aY-@OfXAk02REwf5gWS_Ny^41_VoUf38m33MWeMK^40SeM3^40S1EzFXw^bDV06b0Wn++@Dog01FUg08bAk012V3g09m13MW}42V5^QWPc^w0dm3ew01yQMzR++_Kv90U@OX$gKM1^80SeMw_Fu0tKdMYi^91wuW@o^g3u?kbAd04CV101A?dKIP^803lx3E^pgrDOI46VYA2SX2%g3o?sHAd06CV1^C?4KIh^803lwhE^p5bDOI1iVYA2OFME^GvC_Zvzsf4w^iDZfVvWM7MX01Gm23MXeMI_KU3vHfd06zHhM01^SV8g1SFRw^bDyk7jHlv3I0fdgIf3EF_j@Tqtp^2Dig^FPA^asF0gX0*IHuDZfYXFPA^atp^2Dig^FOA13I-@OGBw0YcyD2w0_?ceJP^o03eIn^c03udMYhw09ecgYgw09avQ_sj4y%eBuDig15UR2$4FPA^s0w%AUc-@NNGvQ_qvn03^c03n03^c^7==1@KLY5^9efM_Rz_sk4MYaj0*ITOV102OUN0w%2FUg05HA403bz8f2A01j0*NwAoEHA402L0*IkuV5^GWW_M@^41_WV1^HFWw^s-@NeHAk02HHH_3U^g7_ws7=1MvHH_1g02jzYfZo_T51cf2AM(Xd4[IKcg8$Gu401qV1^OUO3MF^kM(YtN6aaV1^HM(X4f?aKKLYfw010v@[aWuE^70*IgaV5^GWW_M@^41_U7=]WX_Mm^AU_3_mfZNgj3MFc-@P3ecg8$Gu401z04%fKPzc1$aDx^4Aw4MaGuU^30*IdzIaP@_05nHL_4%g7_GuU^70*IcPIaP@_05nHL_4%g7_ws7=]1@KLY5^9efM_Rz_sk4MYaj0*IJiV102OUN0w%2FUg05HA403bz8f2A01j0*XIAoEHA402L0*I9@V5^GWW_M@^41_WV1^HFWw^s-@MAHAk02HHH_3U^g7_ws7=1MvHr_0M02j0M%eiDzYfWg_T51cf2YM(Xap[IKcg8$Gu40fpoof2YX6M0Yw5@UO0w2^4FQA02GsV^30*IteV102iX6o0Yg9@FWz+ZsvYc3MMcgE%FrI-@NEX9f0134e%d@XHgg0w^SOjM11UP3MG^Agi9^5w2c034q%fAuV1024X0w06vZ@?keLB^c03rA90enHfw0a^R14R^WQ403^dKgw0hIod%@bbDyg6j4a%ajD0*ImV1kE^N2w^3uZgjkw0ec0c$Kc0Yb^9au40gHIq02I07Ol069sFUg0FXdR^3D0308^fD030c40dw0f30k03MOeOi0aY0vKOI06Q0vIgE%F2Y-@Ng45yw03z8f2E^hpFy04FTg13cgU%Ty5w6c1zI1w5F0nX08%8Vj0*IpDIa01d07ODig0aFPA^c-@NfWt9^6V101y69GV5^GFPA^c-@MkXA40abIa013_TNgAf3cN2w^2zhM(X46N4w^3tngha^ec1g2^144MYc2VWg1qVS1g^1y?9Ktwc10M3Gt90230*IhTIa058_TP4a%aa_0*Iej4e%dPl1wE^UWwM8^AFVw^}2L0*HUnIaj@_05nHr_6w^g7_HA402KDC^1M(WZTX2A_LM1lWS_NE^41_Xz8b0g^iDig0aFPA^c-@MRxyyF_j_2sgE%Euc-@MHsh8%S_BxwYbh14E^m550551wYcxgkf30X9P_lM1@ITk08eswYc%@swYcwg0@t2%wRut0Ye0M3A4MYe2V5^FFQA04c-@MJKMC_PT_vc2g%ZdecgA%4Gu4_Pj4W%d_Pzoe$j0*Ifbz82%1j0*I0Pz8f2w02iDmgyr[9I1$xOI1w%yJI0M%xPc-@MCqvQ_N308%8EX0*Ic6Dig0aFPA^c-@MqB0wYczIq^707Ol069sFTg0vI0w%yzs-@MGWt9^GDeg^M(X1kVkPMN%k23MMavQ_KdgFy04gj3MUbAk02GV102iM(X5iX2o05M1@m13M@alfw0306M^Y03I5^do7r4a%dCp1dy0oVkMM%1F_j@TIiE%Sn466E1zBj8$aV1^FFQA0844MYc30*I2HI9LYu_TP0k%fazz45%1aDxfYlNew^3tMFVw^edwU%1c-@Mpecw8%5c-@LvKcwYa^9atp2beV1^CM4%24YM6%29gM3%24@M(X0bF_j@YrAk09GDZf_4M2%285M(X0LFQA02GsV^30*HZxg8f30M2%27YM(X0wFQA02GsV^30*HYBg8f34F_j@mY3w%YlKcgU%4Gu4_Hn4a%dNXzo2$j0*I1jz82%1j0*HOXz8f2w02iDmgyL[9I1$wXc1w%xYc0M%wXI-@LKWvQ_F47]WW_Mk^AU_3_mfZNgj3MFc-@Mf}bbz42$aDx^m[cKcwYag05c-_Jqhyy[aY-@K1XAk02HHH_3U^g7_HA402KDG^1M(WTW?aKKLYfw010v@=]1@KLY5^9efM_Rz_sk4MYaj0*I0iV102OUN0w%2FUg05HA403bz8f2A01j0*YA4oEHA402L0*Hs@V5^GWW_M@^41_WV1^HFWw^s-@JMHAk02HHH_3U^g7_ws7=1MvHr_0M02jzYfZ8_T51cf2IM(W_c[IKcg8$Gu406XBnf2I^6D9^yN2Q^3vlVkzMI^1?8Gt9^x1cf2MM(WYhX2w0aLZY[aWtE^30*HovI9z@_05nHr_3E^g7_Kcw80w01at9^GDeg^M(WXCFQA02el8Yb%rAk0291cf2MM(WXGX2r_TfZYM1%3JEUN0g%iFUj_QYgE%Scedw8%1c-@L9Kcw8%5c-@KgbA4^bz0f2w02iV1^CFRAb8s1w%x9c1$v@s0M%v_I-@KOWvQ_WSV1^HFSw^s-@JcKMCfXY0luJLYew010v@=1MvHH_1g02jzYfZo_T51cf2AM(WYY[IKcg8$Gu401qV1^OUO3MF^kM(@Bh6aaV1^HM(WQ7?aKKLYfw010v@[aWuE^70*HfGV5^GWW_M@^41_U7=]WS_Mc^AU_3@UfZNgj3MZc-@L1}bbz42$aDx^7ma3MZeOy0145vHA402KDu^1M(WPhX2s_LM1lWS_Nk^41_Xz8208^iDig0aFPA^c-@Kc}99gAf2QUO2M4^4FQA02GsV^30*Hybz8f2U02jz8b0o^iDig0aFPA^c-@K5ucwYc^9ecwI2^1at9^GDeg^M(WU866bz8b0E^iDig0aFPA^c-@J_l0wYczIFw2D1DWDSf+k63MPbAk01Tz4f3g02h1sf48[G@Pk01^vKcwYd^1}3uDig01M(WKuX2M1lg1Ygj3N4at9013z8f2Q01j0*GV7I9w5847Pz0f4g^jzIf3401jz0f3U02iDig02FPA^}2L0*HdPzof4o^iV1^OVkzME%UP3N%AUO3ML^k[i@cwYaw0945gYg11cf3UM(WNOX2g0yg1YVkzN2^1[dWt9^zz8f3c01j0*HqbIa01b_TN1cf4gFQA04ecwYcw05c-@JBuMC_VH_vc1g%W4@cgk%4Gu4_V74q%ddL0*HtjzI6$jz82%1j0*HeKV1012UQ3ME^A[aY1w%vWGtp2zX0g%7Gj0c%7GD0*HnqDZfZHUO2Mc^4FQA02GsV^30*HkEoQGvQ_Rf0U%etzz4e%1aDxf@ON3w^3iwM6%1@PUV0M%4M(WSjUO0w%kM(WOJKgg^Kc0Ya^9}2CDmgEZM4%1VFM3%1VKM(WQXF_j_zakK^70*H0jz8f3o02jzcf4g^jz8f2E^iDig^M(WMCFQA^HA402KDeg^M(WMtUQ3N6^2FUg0bueMYe^9eewYew09auF^3zcf3o^jz8f2E^iV2g1aFlU^s9e^4^bDyI4n0*GFWV0w2iFOg05Wu4^H0*Hjlo42^X1w0gwh@UW3MW^4UO3MS^4M(WJnF_j_aedwYdw01}bDz8f3w^iV101b[dI-@INHA202aDN^nKgA0IKOY01Q0vbA806bz8f3w^iV101b[dI-@IIrA202aD9f_JFUg02I-@I@5x0803Iif_m17WV202FUQ3N6^4X4H_Dy1BF_j_KXA40bGDu%[aY-@H4eMDfXY0luJLYl^10v@]1@KLY5^9efM_Rz_sk4MYaj0*HhOV102OUN0w%2FUg05HA403bz8f2A01j0*W34oEHA402L0*GKuV5^GWW_M@^41_WV1^HFWw^s-@GSHAk02HHH_3U^g7_ws7=1MvHD_1802jzYfYU_T51cf2AM(WPA[IKcg8$Gu404nBnf2A^6DN010UV0w2^4M2%1W@M(XezX2g0901@[kI1$sXQ4wYayDeg0wFWw^c-@IvA4MYayV1^FM(WY3[aY-@GAKMGfXY0luKvYh^10v@M(WNoUO0w%kM(WJO[cI0w%uAc-@FKHA402KDG^1M(WFPX2E_LM1lWV_N4^41_U7=]WW_Mk^AU_3_mfZNgj3MFc-@Iv}bbz42$aDx^PVlPMF^1FYg0bKcw80w01at9^GDeg^M(WKSFQA03XAk02aDegg9M(WNZX2w04vZ@FWw^}2L0*GzfIaz@_05nHH_3U^g7_I0g%Ubucg4%4GtQ^qDG^1F_j_WIgE%OYuew8%1c-@HV@cw8%5c-@H0s0M%ubrA404aV1^GFWw^s-@HBqvQ_YQ7=1@KvY4w09efM_P3_sk4MYaj0*H1iV102OUN0w%2FUg0mRywYajIH01n0nV18f2EM(WLPX2g0fw1@FkU04asV10vz8f2I01j0*H1rIG01g0DXzkf2E01j0g%71mDeg0wgi3MIauo^30*GWjz8b08^h1cf2MM(WUEUR3MH^kM4%1L@FPA0844wYb30*GU_z8b0g^h1cf2MM(WUjF_g05s-@HsKcw8%5c-@Gz}3b08%7sD0*GdiDC^1[aY-@FzuMFfXY0luKvYhw010v@UO2M2^4[AI-@EzHA40abIa01^7Oh120HFUg0dKdgYaw05c1$rJWsV02118f2MFVw^c-@HhA50Yb2Dmg^FPA^}2H0*GiLzkf2I01j0g%6VSDeg0wgi3MIc-@HbA50Yb2V1^GFRA^asV^70*GheDZf@N[as-@Gf}2D0*GluV102yX2r_M01YUO3MG^kM(WLsUO3MH^kM(WLmF_j_Aws7=1MvHr_0M02jzYfYU_T51cf2YM(WIQ[IKcg8$Gu4^toEf2YXa804gh@FVw^rA402L0*Gg7Iaj@_05nHr_3U^g7_Kcw80w01at9^GDeg^M(WFw[QKcwI1^1at9^GDeg^M(WFk[oKcwI1w01el8Yc%9k0802Dt01XFTA^ecwI2^1at9^GDeg^M(Wzs[AKOE05k5vKcMI2w01as8^304%7fCOng0jFNj+HAk02qO8w^UO3MI^Ayg%EE^1Ugkatq+@8k^vFkU0451gYaODegg7M(WHyX9w0901Y?xHAk0dSDGg^[ibDFE6DBif2w^mV1^T[bqtp^30*F@CV0w12FQg0equ4^uV202AX9H_W21Bm73MHeNS05w0vGuo^2DZfZN?9KcwYb^9ale012Degg7M(WGFVkPMH%X9r_NM1YFVw^avQ_RKDig0aFPA^c-@EqeME_U3_vecwYc^945MYc2DZfZWM(WErm30w0}6bIef_617XIef_32TVoUf2IXeo04w1@?8Y-@F9XA403b08%76_0*FS@DZfYD[ac-@GS5wMo02DZf_GUO3MI^4FVw^c-@GPavQ_No7]1MvHD_1802jzYfZo_T51cf2AM(WEI[AKcg8$Gu40iH04%dwHz81$aDx^rN0U^3o6WP%M0dKgA0ceJ3^E03rA8043Hd^c^T0*GxH08%du_Bi2$30k%dvnz85$aDx01FMa%3nBUN2w%iFUg0gauF^3HKw02^TzWO%1aDh^7?bI-@Gts0g%RQKcM4$Gu4^Pz2P%1aDh^7?8c-@GoY1$ROecwg$Gu4^PzmO%1aDh^7?9s-@GksiZ%RGIgE%RHWuH^7IKL_787v0*FVf4a%dq30E%dq7Bia$30*FUv4a%dpP04%dp7Bi1$30*FTL0c%dp3Bi3$30U%cqrz0e%1aDF01ZM2%36wUR0w%iFWg0oc2w%NCKcgE%4GuA04f0U%cpjz0e%1aDF^KM2%1CsFXw^c-@Ejs0w%pDc-@EhY0w%pDs-@Egs0w%pEI-@EeY0w%pFY-@EdrA402D0*FP3IaP@_05nHD_3M^g7_HAk0230*Gtj0g%clLBj4^+@DZf_9?8s-@FNY0M%Njelcc03+Y3w%Niec0U%4Gt4_XqDZf_w?9s2M%Nec-@FH@lcI03+Y2w%NcucgE%4Gt4_VCDZf_o?8c-@FDs1$N7Klcg03+Y0w%N6Kdg8%4Gt4_TODZf_o[aquU^70*FJrIaP@_05nHD_3M^g7_KJLY3^9c3g%vSrA40e_zYfW0_T6DW+Eo83w062wU0xwMe0gMc%2Zxgj3N1c-@ERecwYe^9ecg8$Gu40nyV1022N2w^1_3ma3N1c-@DYH9f0134C%bAnHcg0w^SOjM0NUP3MG^Agi8M05yOA03IEw3F0TXIEwX90nXIK0@L_TX0o%6ILzof3U02iV5^bM7%3i5WQ%M0dKgA0geJk^E03rA8053HFg0c^TzE7$z4a%7Ur0*FXvzof2E^h1kC^m4mg2510Yfh18a0EUO3MK^Agj3NaecMYdw09440Yh3z0f3^2h1sa88UT3MO^AFXw^460Ew304%d5fzo1$aDx^oN2w^1ZnM(Wu8UR3MG^4gk9g0ecAA%5eIO^803lw3o03I2wGh07Xz48$jz8a$jI4wFVM6nzUf38^jzoe$jIp0GJ07PIgw010dDI5^@E6mVWi0NX3w0eg5YFSA^asN^6Dx^fX18FL0dpFSA^s8q040g0echE$Gt402vHIM01^OVW63yFSI^uM@arM3ms8W040g0ecjE$Gt401mVW61iFSI^uN5arM3ms9a040g0eckE$Gt4^qDJ+yFSA^uJSE%W9k0EBODx0F9UP2$4Bg2ynatQ2reVW617UQ3MI^AX3gcPW1BUO3MK^4UM0w^2gX0way01YKgA0d@MQ^o0veMS09U0vauU^2DZfZAM(WxR?uKMn+Y0SuJh^c03ud5w%1ecM8%1ecwg%AeKy^403k5Gc06h26^FUg04ufBz_z_1ec0U%AeJM^403k4nc06h21^FUgezKe0Ye^1edgw0w01ed0k%AedgYfw09eIA^403k4Oc06h23^FUg0h@cwYfw01at9^GDeg^M6%1CzM(WraUS3M@^Ak23MZeOU3sz_vHAk0bLH2M03^SV2g0bWT^2w0dKgw0u@KD^M03ly0Yfj0U%cQrzEe$zIyLXt07WDZfXbFXw^ucwYe^1c-@BbHAk02JEwf5Eqa3Ns6z0YnzHr_6M^g7_KewYe^1at9^Hz8a0g^iDeg^M(Wq5k23MZavQ_XX42%bbF1Af4EUM3MQ^A[UXf108Cl0a9rFUgdH@O7arM3msaa040g0eeoE%1eMV0rY0lpk0EBODt0zXKuzw1@NgarM3ms9q040g0ecBE%144gE12B97+[rHDFcbbHXx%ez4a%7vj0*Fynzcf2E^h14z^UN3MQ^8UT0g4^AUS0g%AXbwcu01Ygg3N4c1ePcPcP}130jsPcPcSV1^Xgh0g0rA405KVxw0AWP8^M0cWOc^w0dKgw08@Iy^403rDF82KDaw0MUO0v+ZO[I@Ni_@g9vuMg3un0prDF0b7Iy+_0dDIz0TN7DSPPg0EX4I0KM1lX9j_Y03pUP0vYfZNWRA01^cgugw0atr^7IxjW_05mDx^YX8w09M5YX8w0509YVQ0M%6VS3g0306UP0vUfZNVNh^62cVN0w030egi3NeesMc%1KtgQ^M1GsX+3DsP^k8PDs2^c0WDaM0gVM0M^w6VO3g03w6FPL_Yet$Lzet08^U3GsH013IUw0Yw6jHVg02^PD4d^e0rDo3^20rIA+M0dDIk+w0dDIw+g0dDDk9^20rDw5^20rDM8^20qDe+0VPpw01@cVTlg01@cVWy^1@cV@P^1@cVP0w03weVT0w43weVW0w83weV@0wc3weFOI0gavD_YPIJ07Hw6iV2g0k?9ecM7+_sQ8OYizzU1+_T7I3w7sE6nIB^10dzzw1_@_TeV501pgEnNaecw7_X_suM20sOwpuMQ^80Seeg7_T_sXAk0ed2DL4EUR0v_vZNX0k1La1BX8g^M3oUP0v_fZP?a48OYizzU1_Y_T7I3w6IE6nIB^40dzzw1_X_TeV501pgEnNaecw7_L_suM20pOwpuMQ^k0Seeg7_H_sXAk0ed2DL4EUR0v@LZNX0k1za1BX8g01w3oUP0v@vZP?a48OYizzU1_V_T7I3w5YE6nIB^70dzzw1_U_TeV501pgEnNaecw7_z_suM20mOwpuMQ^w0Seeg7_v_sXAk0ed2DL4EUR0vZ_ZNX0k1na1BX8g02g3oUP0vZLZP?a48OYizzU1_S_T7I3w5cE6nIB^a0dzzw1_R_TeV501pgEnNaecw7_n_suM20jOwpuMQ^I0Seeg7_j_sXAk0ed2DL4EUR0vZfZNX0k1ba1BX8g0303oUP0vY_ZP?a48OYizzU1_P_T7I3w4sE6nIB^d0dzzw1_O_TeV501pgEnNaecw7_b_suM20gOwpuMQ^U0Seeg7_7_sXAk0ed2DL4EUR0vYvZNX0k0_a1BX8g03M3oUP0vYfZP?a48OYizzU1_M_T7I3w3IE6nIB^g0dzzw1_L_TeV501pgEnNaecw7@+suM20dOwpuMQ0140Seeg7@X_sXAk0ed2DL4EUR0vXLZNX0k0Pa1BX8g04w3oUP0vXvZP?a48OYizzU1_J_T7I3w2YE6nIB^j0dzzw1_I_TeV501pgEnNaecw7@P_suM20aOwpuMQ01g0Seeg7@L_sXAk0ed2DL4EUR0vW_ZNX0k0Da1BX8g05g3oUP0vWLZP?a48OYizzU1_G_T7I3w2cE6nIB^m0dzzw1_F_TeV501pgEnNaecw7@D_suM207OwpuMQ01s0Seeg7@z_sXAk0ed2DL4EUR0vWfZNX0k0ra1BX8g0603oUP0vV_ZP?a48OYizzU1_D_T7I3w1sE6nIB^p0dzzw1_C_TeV501pgEnNaecw7@r_suM204OwpuMQ01E0Seeg7@n_sXAk0ed2DL4EUR0vVvZNX0k0fa1BX8g06M3oUP0vVfZP?a48OYizzU1_A_T7I3w0IE6nIB^s0dzzw1_z_TeV501pgEnNaecw7@f_suM201OwpuMQ01Q0Seeg7@b_sXAk0ed2DL4EUR0vULZNX0k03a1BFQE07Kc07@7_sXAk04h21f4EIYQ0WbAo0eLz8f3U^iPPg0UAw3w0c-@CuuNU2t40v440Yh30nIPcPcOV1017[4c1tPcPcPrA403h14101[JbC602nH8w03^PHcw02^SV2^OWPc^g0dKgA0gWta033zg1+_TaV1012Xbb_V0BZX10bcs1BKuA0IuMH+Y0SuMI2P4uvrfd02zIWM2X05nIDL_M0dDzc1_M_T7Hmg04^N1jy^FRI^uO5fHY0lqu403PIy^D0nPIy^k0DPDI3^20rDQd^e0rzc1_w_T7D@X^TUPDY2^e0V18f4UVM0M%6VW3g0306FPL_Yev%2wzev08^M3GsH013Dg3$rD8d^c0qDe+MVSh^22cVS0w030eFOI04eN203O0peJ5^803esMQ^M1Ksgc%1KOj+^SuNj_@^SuO3_Z^SutMA%1Kswk^81Ktww^81GsX_Y3Dkh^c8PD1T^e8PDgy^fEPD5C^fEPDk2^c0XD020ge0XDg20we0XD420Me0WDaM10FQv_PeO@0uK0pbA901WV5^KUP0v+ZPgzbNaed07+_suM40tOwpuOu^40See07_X_sXAk05B2xv4EUO0v_LZNX081Pa1BX3U^w3oUV0v_vZP?gQakYizzk1_Z_T7I1g6YE6nIzw030dzzc1_Y_TeV5^EgzbNaed07_P_suM40qOwpuOu^g0See07_L_sXAk05B2xv4EUO0v@_ZNX081Da1BX3U01g3oUV0v@LZP?gQakYizzk1_W_T7I1g6cE6nIzw060dzzc1_V_TeV5^EgzbNaed07_D_suM40nOwpuOu^s0See07_z_sXAk05B2xv4EUO0v@fZNX081ra1BX3U0203oUV0vZ_ZP?gQakYizzk1_T_T7I1g5sE6nIzw090dzzc1_S_TeV5^EgzbNaed07_r_suM40kOwpuOu^E0See07_n_sXAk05B2xv4EUO0vZvZNX081fa1BX3U02M3oUV0vZfZP?gQakYizzk1_Q_T7I1g4IE6nIzw0c0dzzc1_P_TeV5^EgzbNaed07_f_suM40hOwpuOu^Q0See07_b_sXAk05B2xv4EUO0vYLZNX0813a1BX3U03w3oUV0vYvZP?gQakYizzk1_N_T7I1g3YE6nIzw0f0dzzc1_M_TeV5^EgzbNaed07_3_suM40eOwpuOu01^See07@+sXAk05B2xv4EUO0vX_ZNX080Ta1BX3U04g3oUV0vXLZP?gQakYizzk1_K_T7I1g3cE6nIzw0i0dzzc1_J_TeV5^EgzbNaed07@T_suM40bOwpuOu01c0See07@P_sXAk05B2xv4EUO0vXfZNX080Ha1BX3U0503oUV0vW_ZP?gQakYizzk1_H_T7I1g2sE6nIzw0l0dzzc1_G_TeV5^EgzbNaed07@H_suM408OwpuOu01o0See07@D_sXAk05B2xv4EUO0vWvZNX080va1BX3U05M3oUV0vWfZP?gQakYizzk1_E_T7I1g1IE6nIzw0o0dzzc1_D_TeV5^EgzbNaed07@v_suM405OwpuOu01A0See07@r_sXAk05B2xv4EUO0vVLZNX080ja1BX3U06w3oUV0vVvZP?gQakYizzk1_B_T7I1g0YE6nIzw0r0dzzc1_A_TeV5^EgzbNaed07@j_suM402OwpuOu01M0See07@f_sXAk05B2xv4EUO0vU_ZNX0807a1BX3U07g3oUV0vULZP?gQakYizzk1_y_T7I1g0cE6mDWw0uUM0vUvZP?XA8eYiyPPg28Khw0yXfd03yi08^FQA^c0w%iYs-@wr@NE1Ow0v440Yh30nIPcPcOV1016[4c1tPcPcPrA403h14101[JbC602nH8w03^PHcw02^SV2^OWPc^g0dKgA0gWta033zg1+_TaV1012Xbb_V0BZX108rY1BKuA0IuMH+Y0SuMI26Yuvrfd02zIiM2X05nIBf_M0dDzc1_M_T7Hmg04^N1V2^FRI^uO5fHY0lqu403PIy^D0nPIy^k0DPDk3^20rDsd^e0rzc1_w_T7Dxl^vUPDw2^e0V18f4UVW0M^w6VY3g03w6FPL_YevGE03fzevw8^U3GsH013DA3^20rDId^e0qDe+MVZCg0b@cVZ0w03weFOI04ePy03O0peLB^803euwQ^M1KvMc^81KOj+^SuNj_@^SuO3_Z^Suv0A%1Kswk%1Ksgw%1GsX_Y3D3_^FEPDjc^E8PDoy^E8PDch^E8PD02^c0XDg20gc0XDo20wc0XDc20Mc0WDaM10F@v_PeOQ0uK0pbA901iV5^AUP0v+ZPgzbNaefw7+_suMe0tOwpuOk^40See07_X_sXAk05B2xv4EUO0v_LZNX081Pa1BX3g^w3oUV0v_vZP?UQauYizzk1_Z_T7I1g6YE6nIx^30dzzc1_Y_TeV5^EgzbNaefw7_P_suMe0qOwpuOk^g0See07_L_sXAk05B2xv4EUO0v@_ZNX081Da1BX3g01g3oUV0v@LZP?UQauYizzk1_W_T7I1g6cE6nIx^60dzzc1_V_TeV5^EgzbNaefw7_D_suMe0nOwpuOk^s0See07_z_sXAk05B2xv4EUO0v@fZNX081ra1BX3g0203oUV0vZ_ZP?UQauYizzk1_T_T7I1g5sE6nIx^90dzzc1_S_TeV5^EgzbNaefw7_r_suMe0kOwpuOk^E0See07_n_sXAk05B2xv4EUO0vZvZNX081fa1BX3g02M3oUV0vZfZP?UQauYizzk1_Q_T7I1g4IE6nIx^c0dzzc1_P_TeV5^EgzbNaefw7_f_suMe0hOwpuOk^Q0See07_b_sXAk05B2xv4EUO0vYLZNX0813a1BX3g03w3oUV0vYvZP?UQauYizzk1_N_T7I1g3YE6nIx^f0dzzc1_M_TeV5^EgzbNaefw7_3_suMe0eOwpuOk01^See07@+sXAk05B2xv4EUO0vX_ZNX080Ta1BX3g04g3oUV0vXLZP?UQauYizzk1_K_T7I1g3cE6nIx^i0dzzc1_J_TeV5^EgzbNaefw7@T_suMe0bOwpuOk01c0See07@P_sXAk05B2xv4EUO0vXfZNX080Ha1BX3g0503oUV0vW_ZP?UQauYizzk1_H_T7I1g2sE6nIx^l0dzzc1_G_TeV5^EgzbNaefw7@H_suMe08OwpuOk01o0See07@D_sXAk05B2xv4EUO0vWvZNX080va1BX3g05M3oUV0vWfZP?UQauYizzk1_E_T7I1g1IE6nIx^o0dzzc1_D_TeV5^EgzbNaefw7@v_suMe05OwpuOk01A0See07@r_sXAk05B2xv4EUO0vVLZNX080ja1BX3g06w3oUV0vVvZP?UQauYizzk1_B_T7I1g0YE6nIx^r0dzzc1_A_TeV5^EgzbNaefw7@j_suMe02OwpuOk01M0See07@f_sXAk05B2xv4EUO0vU_ZNX0807a1BX3g07g3oUV0vULZP?UQauYizzk1_y_T7I1g0cE6mDiw0uUM0vUvZP?h484YiyPPg28Khw0yV80w02PPg0UFQA^c0w%g7I-@tIpk0EBODx01ON2w^1mCXbsGLg9pM(VTkKgw0KKdgYaw01}8L2Kw604032yw50401ocb^m92^44yk02V5M13UO3MQ^8k90w251080PzpS+_T7I5yGZ0BD26w60403z4q%1aDF^6FjG^50M80OPPg0EM3$UcKho0is-@uDbfd03yDig^M2$_oM(VRyN2w^1lrM(VScUP3MQ^4UU3MG^4[IHfd02x1CU^UQAM3^nM3$TBM(VVTIYQ0eat9^308%3XD0*DjRoUf3QXeE0dM1@FXw^avQZKal0a9rFUg3fXA40er4q%8XvIxOCY0RDzof3g02j2yw10403zma$h1Af4EX3k1LM1lIY40yueTX+_suNbarM3ms9a0c0g0edAE%144gE12VWj2S[rGvQZMzItOCY0RD2uw10403zFW$iV5^KFQA^eMW0rY0ls-@souMC_XD_vc1g%FP@cgk%4Gu4_X34a%99uDK%US0w%4M(VSbUO0w%kM(VOBM3%10V[gHA402r0*DjKDZfpTU@2wa02gXeo3yg1YXbw1lCh@wM^hauW^6DZflmUP3MM^4?8at90130*CI3I9LlE47Pzsf4g^jzof4o^iDZfmXUO3MO^4UM0w%4X0HRIM1YUN2y4^4X77RHs1BU@3MO^4Kgc0IeIbU%cavQZqbzca0w^iV0M16X3w01w1YX2c1Za1BX38GLg9pURew^5NUPew^5oVlRg%1X3Q^g12Kho0cXA407iV3g1zUP2w2^4MzU$1X3Q^g16Ki40dXDyI3vIefkF07P2fw%43IeM1^4qVW31iX1nR941BF_jR8WvE^7H7G4^fz4a%54f0*D7jzEf3E02j4m%8IHzgf2E^jzEf3o^jzkf3g02h1IA^ghJga981403zI8$jzcf2M^j4a%52aV2g0XIY40yKsbc%oKNX02@wprDFs0KPMg2wX6^rY1BVM2w030eM(VM_UQ3MG^4N5w^2A1gi9^eciA%5442A03Hgg02^SPMg30UOhg%k[eGt90130*D5fIa06t47PzUf2U^jzce%934a%4@fIdw5B07PD8$4jD8f4Ec0X0*D0Lz4f2E^j4m%acCV102OgkIg0cgt%AUKc4A%5eIM^803lxjk01g4f4Mk53Nael4YiM^ul4Yjg^rA402F1J9^FPA^Gt9+_0*CI6_4_4KFTg0abYjYjqDxfZYUW3MW^4N2w^1evM(VLgUR3MQ^4UX3MG^4gjaM044jk2yl01^FTg0PuNEZco0v460YiyV103CIY40yavQZmj4a%a7zzcf3%jzUb%1jHjw02^Tz92%1iDig08M(VC3LNfNdGu4_QaDZf_6FXw^uIrEg^@cgE%jos-@rAJsnYizNachU%EkcgU%EisiU%xUKcgYaw0145y4034bg^96bzlF%1jH5g02^Rogn^k23Nc510YizBhf4I^7Bhf4Q^5o0j^gnqMa5^Yjzzof3o^ii0n^VkjNf^1F_g05qt9+@Deg03M(VERAg7NfWtQ01m_4_4KFTg0GrYjYjqDt^dU@2$4UR2w%4[9KPB_@n0psgE%j1Y-@reecMYaw0145ic011hr0EBg1^au4Z3do1p^Me%2vwFMX+@M8$gKdMU$Gu401qV5^gWO4^M0dKgA08uJy^E03rA801rHcg0c^RokT40X5o1MM1@N2w^1bjM(VI4UT3MG^4gh9M046NI2yi0b^FXw^avQYSdo0V^M2%2uGFMX+@M8$gKcM8$Gu401qV501gWNk^M0dKgA05uKN^E03rA805LHhg0c^Ro9340X2o1tw1@N2w^1atM(VHeUR3MG^4UX3MQ^4gh9g0451I2yi04^F_j_0edMYcw01eM2^40Sud0s%9eMgYRt0pqvQYU@VWn1HUW3MW^4Kg80pKNJ$hGvQ_Jb4a%4C_0*CG3z4f2E^j4i%9RV18x^gj3N2edOA%5eJD^803ucCg%5at9^z0*C6yDZfZaIYQ0XchE%Dhul8Yh%uc0U%5eewYew01eKM^803qt9^zzaS%1h1cf4gM(VGrX2w1aLZYN2w^18NM(VFyUR3MG^4UX3MQ^4gh9g0451I2x18r^Bg1^au40Cpo0p^X0w0@fZ@M6%2s2UP1w%2FUg0ZXfd06GDZfZrBg2ymWu401P4K%89rIlOCY0RD2mw10403z5q$h1gf4EUX3MQ^A[VHf108jIcg6_05mDZffAX6w1xw5YX6w0og1YN8w^21Sgu3Naee0Yd^9bf108V1lS^[5WvF^2V1^CX3o@LM1lFUg06@MU^U1veMS0uk2veONaHQ2mqsr^7zWW%hHIgiGZ0BCD6M01U@iw^4qX540aU1AWU8^w0cX94GLg9pX04^g3pX24^w3pXb4^M3pU@Cw^4qX50GLg9pX38GLg9pU@mw^4qX4IGLg9pU@ew^4qFNI01efAE^16Gu7_ZR14a0g[LGvQYVfH5G0g0ez4a%4on0*Crrz4f2E^j4K%80N18x^UX3MQ^AgjaM0edMc1^9el8c$440YiyPMg20IYQ06ecwYfw01bfd03zDA08364rDA1^20D0*DaLItLoR07OPPg0oIYQ0eesM0wcohKsM4^82qt9^308%2YP0*CkHIpLzu07OPPg0oVR020N16VR0g%9F_jXxaup+_HGq080ezIFw5l0nODK^2F_jOTQ7Acg2Def+WOfw^3UF_j@xI3w%C3ucMU$GtQ0iWPPg3GAw0waavQYLt1gT40FMz+@Iwg%@avQ_zD0g%9vbz44%1aDxfXjN3w^22WUS0M%4M(VCMUO0w%kM(VzaUO3ME^AFRA8cXA402r0g%2Ez0o%33X0c%2EH0*CluDZfWLM(VGiUU3MU^4UP0w%4UN202^4UO0g^2gUN3M@^AWQ8^g0dglgM0p48k02Dtf95XarOy09@Xbw07fZ@?K@KH^c03rA90aL0o%9qbH2w0a^SV2^bWW^3^dUW1w%8F_jN8ByMYfj08%2Z70*Ckn4rg^9ozIa01w07ODig0aFPA^c-@oW1yyN2w^12gXao0fW1SM(Vy@UR3MG^4kb3MZ452k02V5^Gkaig0eIO^c03rA903bH0M0a^SV2^2WW^3^dF_jO4@PE0141v}6WDZfWcN6w^1XSgp3NaedwYd^9bf108DIpOGZ0BDzVG%hp14a0g[LGtF^6DZf9pM(Vy2UT3MG^4kb3MZauF^11ID^ghKg0elc4$avQYu7Ir^u0n_04%9i3z41%1aDx^lN8w^1_EFQA0f@dgw%1asV^708%2RH0*BRv4rg^9gGDmg^gk3Na44MYh2Dag4TFWw^c-@o1XA202bHGf4E0faDZfZXU@204^4UO206^4U@3M@^AFQA02GsV^30*C51g8f3QF_jNys3w%b7@fwYfw09avQ_QKPPg1GFMw^avQ_jzIVOGZ0BDI5M010dDzXG%hqDZfUlUO3M@^4M3$IJM(VICFXw^qvQYoiPPg3EF_jQDrfd08yDZfEjIYQ0yavQZR6Di%F_jU8qvE^2DZflvFQw^avQYF@PPg3GF_jNBMs7]1@KvY4w09c3$veufM_Rz_sk4MYaj0*CaCV102OUN0w%2FUg0oYgE%fDX9f0930*BYHHCg0w^T4G%7yiOjM2hghag044xE2yl02^FTg04}2KDG%M(VpzX2E_LM1lWV_MY^41_X4e%7wT0g%95Vo0j^FMX+@M8$gKdgg$Gu401SV503wWNU^M0dKgA07KIx^E03rA80ebHfw0c^Ro0R40X0w02w1@gkdh0ato+_H9k%fz4a%3QP0*BTB1AF^gqCwa980E02DZf@V[aWuE^70*BxHIaz@_05nHD_3M^g7_ws7=WS_Mc^AMc%1WNU_3_kfZNgj3MFc-@o8rA40bbz42$aDx025ma3MFeOI0841vIgE%f5I-@nfX9f0134q%7qbHcg0w^SOjM0Ngk8M0cgE%tC}7do12^683I203A_TXzUb08^j04%2D2D2%[fH9t01eD5f_@FTg0os2g%zO@ltA$qv4^uV5^EM(VAfM1%2f0U@0g%2FUg06bAk^yDag01WU%M0dKgA0weIU^E03rA8033HgM0c^R1le08WP9g^3EXaw0609@M(VxDUW2M4^4UV0w%4UN2w^2gWU4^g0dgjyg0p48c02Dt02VFSw^}2L0*BnXI9z@_05nHr_3w^g7_HA402KDq^1M(VlMX2o_LM1lWS_MU^41_X0E%2wqOng2KFNj+GtQ_ZT4a%3E74C%8Sb0*BGv4G%7h11gD^giiwa45kE02l02^FUg0aWue+Yo2eM8$gKOo0ac0vbAk0e3H7w03^SV2g0uWP402w0dKgw0fKJ3^M03lwAAg3I9w2j07X4a%3AX0*BDt14D^gq6wa980E03IC^p07OV5028FOD+@LE^c03rA90ezHfw0a^SV2023WQw03^dglig2eIyk%WcgE%eas-@mkA5Os011pS08VkNw0f+FSw^avQ_Tr08%2jT0*BH7Ia^Y07ODig0aFPA^c-@mlNy2N2w%U7M(VoMgl9M046lo01gw9^NEQ^2btFQj@_@lcA$au8^2DZfXU[aGt9^GDeg^M(VoR[EIgE%dVc-@m3k5Os01gFS08FSw^avQ_PiDmg^gk3MH44MYayDag4TFUw^c-@lKbA202bHyf2I0faDZf@ZAw1gaavQ_Vt1B940FMz+@IwA%@cio%yCWvQ_So7]WV_Mi^AU_3_efZNgj3MFc-@mF}bbz42$aDx^ama3MFeMq+Q0SeMs0142vWuo^6V1^HM(VhKX2A_LM1lWV_N4^41_Xz8208^iDig0aFPA^c-@lPrA409bz8b0g^iDig0aFPA^c-@kouOE02M3vKdgI1w01c0M%8WGs8^2V1015IBQ0dask+WDx^PMe$zy[cH9t0emD5f_@?aqtQ05ODig02M(ViY[cKMC02L_vavQ_XaV1^OFQA^rAk02D0*BaOV1^OX2z_FvZYM2$z3FVw^c-@jvWvQ_VOV1^OFQA^bAk02D0*B9iV1^OX2z_zvZY?2Gsb+_H8^3^SVW22HUN2w%4Bg0g0au4_ZGV101jM4$ymFPA0844wYayDC%M(Vn1UO2w%4gj3MGc-@ohqvQ_SqDig01M(Vhy[cKMC_Z7_vavQ_Rw7=1@KLY5^9efM_Rz_sk4MYaj0*BtOV102OUN0w%2FUg01@lsYag^GsA012V1^HFWw^s-@jGuMGfXY0luKLYfw010v@UO0w2^4FQA02GsV^30*Bgzzcb0g^j04%24iD2%[gX9t01iD5f_@FUg0dI1g%8frA40aeOng1qFNj+Gu403r0U%23yV1^jIBQ0Uqsk+WDx^SM5$uF[gX9t05iD5f_@FTg0dHAk02aDG%M(Vog[aY-@jm@MGfXY0luKLYfw010v@?8GsV^70*BtSDG%F_j_WXAk02aDeg^M(VniFWw^avQ_@2V5^yFPA^I-@lNWuE^2DZf_lM2$vQM(V9JF_j_vgs7=WV_Mi^AU_3_mfZNgj3MFc-@lf}9bz42$aDx02dVlPMF^1FUg0TGv4051o4f2Agr0w2asq+XI8hSY0RB1EF0gUR2M%4UP1g^2kBiRg0atQ^Glol01FTg01Fk0k0aDx037Me$v0FMw^}4mOng3AFNj+Gu40bHIdw0vbnWlt501FUg0buMS01wJvFlLk06Dx^ZX3o04iR@BmRg0qtQ05ml0502FTg0ks0w%7GY-@jFquX^zIKL_0o6iV1^FFXw^c-@iKuMHfXY0luKvYf^10v@Bg1g0GtQ_Zf0g%1U30c%1Ub08%1@GDKM08M(V8gXbH_Dm1AF_j_Tpk0k0aDtf_3M2$tQFXI02c-@jr@OW_UNwpavQ_YOV1^FFXw^s-@iw@MHfXY0luKvYf^10v@X3r_JOR@Bmtg0qu4027IdL@MbnWlpB01FUg0a@MS_WAJvFlEk06Dtf@ABg1g0GtQ_W308%1VmDKM08M(VcXXbH_m61AF_j_C9k0k0aDtf_vM2$sRFXI02c-@jaKOW_QtwpavQ_Uul0502FTj_Rs0w%7dGuX^z0*ANDIKLYSo6iDZfZSM2$r_M(VceF_j_rI0M%6ZY0w%7nY-@hAY1$6Zs0M%6ZY0w%7mI-@hxY0M%6Zc0w%7mI-@hvI0M%6XI0w%7mc-@hts0M%6Wc0w%7lI-@hrc0M%6Ys0w%7lc-@hoY0M%79s0w%7kI-@hmGvQ_OE71@KvY4w09efM_Rz_sk4MYaj0*A_OV102yUN0w%2FUg1@ulsYag^qv40kTz8208^iV102iM(V3o[IKME0tU0v94482KDx07kFRA^c1$79GsV^2V1^HM(V63FRA^c1$77WsV^6V1^HM(V5TFRA^c1$76GsV^aV1^HM(V5HFRA^c1$75qsV^eV1^HM(V5vFRA^c1$74GsV^iV1^HM(V5jFRA^c1$73WsV^mV1^HM(V57FRA^c1$73asV^qV1^HM(V4XFRA^c1$71GsV^uV1^HM(V4LFRA^c1$70asV^yV1^HM(V4zFRA^c1$6_GsV^CV1^HM(V4nFRA^c1$6@asV^GV1^HM(V4bFRA^c1$6YGsV^KV1^HM(V3_FRA^c1$6WWsV^OV1^HM(V3PFRA^c1$6VqsV^SV1^HM(V3DFRA^c1$6TGsV^WV1^HM(V3rFRA^c1$6SasV^@V1^HM(V3fFRA^c1$6PWsV012V1^HM(V33FRA^c1$6OGsV016V1^HM(V2TFRA^c1$6NqsV01aV1^HM(V2HFRA^c1$6MGsV01eV1^HM(V2vFRA^c1$6LWsV01iV1^HM(V2jFRA^c1$6KasV01mV1^HM(V27FRA^c1$6IGsV01qV1^HM(V1XFRA^c1$6GWsV01uV1^HM(V1L[aWtp^30g%1GeDeg0oM(V1z[aGuo^30*A8PIaj@_05nHD_3M^g7_I0w%5XI-@hnY0w%5Xs-@hms0w%5XI-@hkY0w%5XY-@hjs0w%5YI-@hhY0w%5Zs-@hgs0w%5@c-@heY0w%5@c-@hds0w%5@c-@hbY0w%5_c-@has0w%5_c-@h8Y0w%5_c-@h7s0w%5@Y-@h5Y0w%5@Y-@h4s0w%5@I-@h2Y0w%5@I-@h1s0w%5ZY-@g_Y0w%5@c-@g@s0w%5@s-@gYY0w%5_c-@gXs0w%5_Y-@gVY0w%5_I-@gUs0w%5_I-@gSY0w%5_s-@gRs0w%5_s-@gPWvQ_ROV1^FM(V3E[as-@g0XA40bbI9LUy07OV1^GFVw^s-@fR@MFfXY0luKvYf^10v@1MvHX_1M02j4a%68nzYfZw_T6Deg01M(V9xN2w^1zeFPA^s-@imsgE%oKGsV^70*AB74a%6caDeg01M(V99N2w^1yCFPA^s-@igsgE%ovGsV^70*AzD4a%68qDeg01M(V8NN2w^1yCFPA^s-@iasgE%onGsV^70*Ay74a%68GDeg01M(V8pN2w^1xiFPA^s-@i4sgE%oCGsV^70*AwD4a%63qDeg01M(V81N2w^1wGFPA^s-@h@sgE%otGsV^70*Av74a%63GDeg01M(V7FN2w^1wKFPA^s-@hUsgE%otGsV^70*AtD4a%62WDeg01M(V7hN2w^1vKFPA^s-@hOsgE%oiGsV^70*As74a%64qDeg01M(V6VN2w^1wOFPA^s-@hIsgE%nYGsV^70*AqD4a%60aDeg01M(V6xN2w^1vOFPA^s-@hCqsF^3HX_4g^g7_ws7=WS_Mc^AUN3Mu^4F_L_oecgY%9c3$nyud0Yh^1eJLYd^10vQ!bTdVsOZApnpFoSlPbTdVsThBriZKrShBbSVLp6kBp2Zzs7lIqndQ02ZPuncLp6lSqmdBsOZPundQpmQLoT1RbSdMtj0LoS5zq6kLqmVApnwPbTdFuCk^7tLsCJBsDc0r6BKpnc0oDBQpnc0hAZiiR9ljBZ6jR93hlZ6gkNcgA53iM^bShBtyZPq6Q^2ZQrn%2ZApnoLsSxJbSpLsCJOtmUKm5xom5xo02ZQrn0LpCZOqT9RryVom5xom5w0hAZiiR9ljBZ4hk9lhM1QsDlB^1CrT9HsDlK85J4hk9lhRQwhmVxoCNBp0E^2QJrCZApncZ^1xtnhL%LsTBPbShBtCBzpncLsTBPt6lJbSVLp6kLrSVIqmVB02lR^16jR9bkBlenQVljlZejQh5kM1CrT9HsDlKey1zomVKrTgwoSxxrCtB82QJrCZApncwtSBQq6ZRt21zomNIqmVD879FrCtvp6lPt79Lui1Cqn9Pt01Jrm5Mey0BsM^biRTrT9Hpn9Pfg^biRTrT9Hpn9Pc3Q0biRTrT9Hpn9PbmRxu3Q^2QJr6BKpncZ%JbmNFrClPc3Q0biRIqmVBsORJonwZ%Jbm9Vt6lPfg^biRyunhBsP0Z02QJoDBQpncJrm5Ufg^biRIqmRFt3Q^2QJt6BJpmZRt3Q^2QJpT9BpmhV%Jbn9Bt7lOryRyunhBsM^biRLtngZ%JbndQp6BK02QJrCYJsThAqmU^2lA^15lAp4nR99jAtvh45kgg^hlp6h5ZiikV7nQlfhw15lAp4nR99jAtvikV7hldknQh1l440hlp6h5ZiikV7nQBehQljl5Z5jQo^4lmhAhvkABehRZjl45ilAk^6pLsCJOtmVvrTlQ0599jAtvk4BghlZ3gl11gQBkmg^9mNR0599jAtvgBBkhldvjk5o^1OqmVDnSBKp6lUpn9vrDlJojEwqmVPtmpCqmdFpmVQ865OpTlJpmVQsM0Br7ka^1TsCBQpixCp5ZPs65TryMwsS9RpyMwsSNBryA0pCZOqT9RrBZOqmVDbCc^6pLsCJOtmUwmQh5gBl7ni0BsPEBp3Ew9ncwpC5Fr6lAey0BsME0tT9Ft6kEpnpCp5ZAonhxnS5OsBJJulZKrShBnSBAniMw9DoI83wF07tOqnhBa6pAnTdMontKb21vsS9RpyMwnTdIpmUF07wa^1TsCBQpixCp5ZPs65TryMw8Dxsry8I838F07tOqnhBa6lSpChvpmZCb20CpmZCnTdFpOMwe2A^7tOqnhBa6lSpChvp65QolZxsD9rc5QI9DoIe2A^6hOug1JpmRCp01RrCZOp6lOpmg0rDlJog^9ncK9nkK9nk^2lPbylR0599jAtvikV7hldknQh9lABjjR80tT9Ft6kEpnpCp5ZFrCtBsThvp65QoiMw9DoI83wF^1OqmVDnSVRrm5vqmVDpndQey1FrDdRpCpFoSBBrDgwon9DtmRBrDhP^1CrT9HsDlK85J4hk9lhRQwjBldgi1RrC5SomBIom9IpiMwsDlKrCBKpO1JtmNQqiROqmVD87tFt6xLtngws6BKrCBKpME0kABehRZ2glh3i5Zjj4ZkkM^kABehRZdgkFfkw^kABehRZdikVfkw^kABehRZ2glh3i5Z9h5w^7tOqnhBa6pAnSpxr6NLtOMw9CBMb21PqnFBrSoEqn0Fag16h5ZfkAh5kBZgil1507tOqnhBa6pAnT1Fs6kI82pLs2MwsSBWpmZCa6ZMaiA0tT9Ft6kEpChvt65OpSlQb20CrT0I87dFuClLpyxLs2AF07tOqnhBa6pAb20CtC5Ib20Uag^tT9Ft6kEpChvr6ZzomNvsSBDb20CrSVBb20Uag^tT9Ft6kEpChvpSNLoC5InS5zqOMw9D1Mb21PqnFBrSoEs70Fag1CrT9HsDlKnSBKs7lQ06RBrmpAnSdOpm5Qpi1ComBIpmgW82lP06pLsCJOtmUwmQh5gBl7ni1OqmVDnTdBomMwpC5Fr6lAey0BsME0s6BMpi1ComBIpmgW82lP06dIrTdB07dMr6Bzpi1ComBIpmgW82lP0595k4Np0599jAtvjAZ4hlZ9h%pCZOqT9Rry1rh4l2lktt8599jAtvjAZ4hlZ9h21JqndPqmVDb21ComNIqmVD869xoSIwt6YwpSlQoT1Ra2Aa03^tT9Ft6kEpnpCp5ZAonhxnS5OsBJJulZKtmRxnSVLp6ltb20CrSVBb20Uag1CrT9HsDlK85J4hk9lhRQwsCBKpRZzr65Fri1IsSlBqO1ComBIpmgW82lP2w^qmVz06hBoM1jhklbnRd5l%kQl5iRZ5jAg^2lIr6g^2lIr6ga07dEtnhArTtKnTs^7dEtnhArTtKnT8^7dEtnhArTtKnT9T07lKqSVLtSUwoSZJrm5Kp3Ew9nc0tz4KdiUM%Jbm5Ir^Oc3EQcPEMe%jm5O820N838Mczo0j6BKtnw0sPcVc7w0cjkKcyUN838MczoMcj8P82xipmgwi65Q834Rbz8KciQTag^bkYP82RCr7hLfm5Rt6YwbmpKrORPt79FoTgJomNFondFrCswbmpKrORPpmRxrDhFoORFrDhBsD1LsSBQqmZK82RCrCYJrm5Qq2RBsD9KrO0JpDhOpmkJr6ZLs2RFri0JpDhOpmkJr6ZLs2RFtCdxrCZK82RCk4B3801RrCJKrTtK05pBsDdFrSUW820BsME0gDlFr7gW820w82lP82lP2w^jRcW820w820w82lP2w11sCdEey0w820w9nca04dLrn1Fr6lOey0BsME0hCNxpTcW820w82lP2w17qngwi65Pq3Ew9nca079FrCtvqmVFt01OqmVDnShBsThOrTA^79FrCtvsSdxrCVBsw^sCBKpRZKtmRxnSBKpSlPt%sCBKpRZFrChBu6lOnSVRrm40sCBKpRZKtmRxnTdzomVKpn80sCBKpRZzr65Frg^sCBKpRZTrT9Hpn80sCBKpRZzr6lxrDlMnTtxqnhBsw1OqmVDnSBKpSlPt01OqmVDnSpxr6NLtM1OqmVDnS5zqM^sCBKpRZLsChBsw^sCBKpRZzrT1V079FrCtvsSBDrC5I06NPpmlH079FrCtvqmVApnxBsw^sCBKpRZCpnhzq6lO^1OqmVDnSpxr6NLtRZMq7BP^1OqmVDnSRBrmpAnSdOpm5Qpg1OqmVDnTdBomM0sCBKpRZCoSVQr%sCBKpRZMqn1B079FrCtvsT1IqmdB079FrCtvtClOsSBLrw^j6BPt21IrS5Aom9Ipnc^79FrCtvr6BPt21rlA5ing1jq6ZT869RqmNA86RBt65Aonhx079FrCtvtClOsSBLry1rbnhYbmZYbmRYbmtYbmpYbm5t^1js6NFoSkwp65Qog1OqmVDnTdMr6Bzpi0YikU@83Nfllg@83NfhAo@83NchkU@85Jzr6ZPplQ^4dOpm5Qpi1Mqn1B079FrCtvs6BMpi0Ygl9iv594fy1rlR9t04pFr6kwoSZKt79Lr%sCBKpRZCoSVQr20YhAg@83Nzrmg@05dBomMwrmlJpCg^79FrCtvsSlxr20YhAg@^13sClxt6kwrmlJpCg^79FrCtvrmlJpChvoT9BonhB83Nmgl8@051EundFoS5I86pxr6NLtM1elkR184pBt6dEpn8^4Vljk4wimVApnxBsw^kSlBqO1Cp01IsSlBqO0YhAg@83NfhAo@85Jni4legQlt85Jmgl9t05dFpSVxr21BtClKt6pA^1OqmVDnTdFpSVxr20YhAg@^1qpn9LbmdLs7AwqmVDpndQ^1OqmVDnSdLs7Awf4Zll3Uwf4Befw^kClLsChBsy1LtnhMtng^79FrCtvrT9Apn8wf4p4fy0Yk4pov6RBrmpAfy1rtmVLsChBsClAng11oSIwoC5QoSw0sCBKpRZxoSIwf4p4fy0YhAhvjRlkfw^j6ZDqmdxr21ComNIrTs^79FrCtvpC5Ir6ZT83Ngil15fy0YhABchjUwmShOulQ0kSBDrC5I86BKpSlPt013r6lxrDlM87txqnhBsw^lSZOqSlO86dLrDhOrSM^79FrCtvtSZOqSlO85JFrCdYp6lzni1rhAht^13r65Fri1yonhzq01OqmVDnSdIomBJ85Jmgl9t85J6h5Q0kDlK84Vljk4wr6ZzomNFuClA87dzomVKpn8^79FrCtvrDlJolZPoS5KrClO83NJpmRCp3Uwf6VLp6lvqmg@83Nzr65FrlZMqn1Bfy0YsT1xtSVvpCg@83NKrShBsPUwf6VLp6lvs6BMpncKbyU@059Rry1elkR186dEtmVH86BKp6lUpn8^79FrCtvqmVApnxBsBZKtmRx83NJpmRCp3Uwf6BAu5ZMqn1Bfy0YrCZAplZMqn1BsOUKbzU^59Rry1elkR187hLs6ZIrStFoS5I86BKpSlPt01OqmVDnSVRrm5vqmVDpndQ83NFrCpAfy0YrTlQpCg@83NFp7xvs6BMpjUwf6dIomBJnT1Fs6k@83NKrShBsPUwmSZOp6lOpmht059Rry1IpmtxoTAwsSdxrCVBsw^sCBKpRZPoS5KrClO83NCp3UwmTdMontKnSpAng^h6lPt79Lui1OqmVD^19rCBQqm5IqnFB879FrCswtSBQq21zrSVCqms0sCBKpRZFrCBQ85J6j457kRQ0sCBKpRZIqndQ$^3+++_YQsf+++_OTQ++++cYX+++_YJZf+++_Pf4++++bvj+++_YJZf+++_OTQ++++cXH+++_YQ4f+++_OTi++++btz+++_YJQL+++_PeK++++btb+++_YJQL+++_OTi++++cW3+++_YPMf+++_OSO++++cX3+++_YJIL+++_PeC++++brb+++_YJIL+++_OSO++++cVP+++_YPyf+++_OSg++++bpj+++_YJAf+++_Pda++++bp3+++_YJAf+++_OSg++++cQ3+++_YPaf+++_ORK++++cL3+++_YJrL+++_PbE++++bmX+++_YJrL+++_ORK++++cJX+++_YP0f+++_OQS++++bjH+++_YJdL+++_P9U++++bjr+++_YJdL+++_OQS++++cCUf3wQc2ME920s61gg30w4!^1w!06!^o!01w16McX%1t$2T+MKg%1Af+55w%6E+Ymy$u3+NJE%2mf+76w%as+Yt@$LP+N@o%3lf+8bw%e4+YAm$Xz+PsE%45f+eCw%hE+Zq@%1bP+RMU%4@f+xzw%lg+@8e%1p3+UDU%5Pf+z6w%oc+@my%1AP+WdU%6Nf+E@w%s0+@Am%1PP+WHE%7Af+GRw%vc+@HO%20z+WMU%8gf+Haw%xY+@Nq%2cP+X7o%92f+IAw%B4+@Pq%2p3+Xfo%9Pf+JWw%Eo+@U6%2Bj+XzE%aBf+Krw%H4+@Xu%2Lz+XS8%bdf+M1w%JQ+_wy%2XP+@6o%b_f+V9w%Nc+_Ca%383+@tE%cMf+Wuw%Q4+_K6%3kw!05$^1uB8^nwe0hIc3W01!5$1P+MDU%7U!$%d$3j+NaE%2bw1ay0O92UEayMCc28Q7zwqf1koeO0Q30v8aPYXdPcLaOsweE0522M$1Q$rf+5a$jw04O63Esdy0O92UEayMCc28Q7zwqf1koeO0830oEaPYXdPcLaOsz7NwWw0kobi0Ww0sr7OcDaOYPdPIZ23Iw2xwW73owcygKa2EI9z0yd1UU6zMk30wwaPYXdPcLaOsz7NwWw0kob$^1$0Vf+6gw%3U04G92UEayMCc28Q7zwqf1koeW09i2I_ePsPbOIAeE0522M9o2I_ePsPbOIAeE0522M$%5M%4E+YpN$p%Ba92UEayMCc28Q7zwqf1koeM09KPYXdPcLaOgWw0kMeM0a92UEayMCc28Q7zwqf1lweE079OILcPsXfhwX^EAbywGb2oM8zgue1EY5$05g%68+YqZ$po0l8EayMCc28Q7zwqf1koeM09@2I_ePsPbOwWw0k8b0I8aPYXdPcLa3G01i0Jw2I_ePsPbOwWw0kobkwHfPITcOYEeE0522M$0I%1Uf+73M%4s04qa2EI9z0yd1UU6zMl63E030CMaPYXdPcLa3G01gwI$M%24f+7iM%eq04O92UEayMCc28Q7zwqf1koeM082gwHfPITcOYH93G01gwI$0m$Aj+O2o%iN016xwW73owcygKa2EI9z0yd1UU6zMla3Iwbk9wnChqq5gbI2I_ePsPbOID8NYrqStweE0522Mc2PwHfPITcOYH9Ocv6SJDo3G01gwI%1g%2Ef+cMM%d^4q63Esdy0O92UEayMCc28Q7zwqf1kEeE8c4i9wl0MaQ2I_ePsPbOID8NYro3G01hwJs2I_ePsPbOID8NYro3G01hwI%1g%2Zf+dvw^22604q63Esdy0O92UEayMCc28Q7zwqf1kEeK0pAC1Op6VEqCNCs69QnDxqv5ngaPYXdPcLaOsz7NJ_uTtPrSJDo3G01gwI$U%3if+lzg%4Y04q63Esdy0O92UEayMCc28Q7zwqf1koeQ082twHfPITcOYH9Ocv63G01hwI%1k%3xf+lPw^2DW04q63Esdy0O92UEayMCc28Q7zwqf1kEeK0lAC1Op6VEqCNCs69QnDxqv5gci30HfPITcOYH9Ocv6TZXtTdLqStweE0522M$^f$ZP+U3w%1_w1uxwW73owcygKa2EI9z0yd1UU6zMl63Ey410c1owHfPITcOYH9Ocv63G01gwI$^3w%gs+@2E$s^nEoexMS838AbywGb2oM8zgue1EY5hwXg2wbe2I_ePsPbOID8NYoeE0582M%3M%ho+@49$CE0m8oexMS838AbywGb2oM8zgue1EY5k0Xo2wc1awHfPITcOYH9Ocv63G01gwI!Y%4Cf+xBg%Ek05q63Esdy0O92UEayMCc28Q7zwqf1l0eW1s31b0aPYXdPcLaOsz7NwWw0k8b!t%1dz+V0Q%cW01cxwW73owcygKa2EI9z0yd1UU6zMlg3E060Maw2I_ePsPbOID8NYoeE0522MaI3G01NIv8OsHbPcTePQEew0q63Esdy0O92UEayMCc28Q7zwqf1gc8rwHfPITcOYH9Ocv63G01gwI$0e%1l3+VOI$pw16ywGb2oM8zgue1EY5hwX80DUaPYXdPcLa3G01gwJoPYXdPcLa3G01!e%1oP+VPw$pw16ywGb2oM8zgue1EY5hwX80DUaPYXdPcLa3G01gwJoPYXdPcLa3G01!k%1sz+VQk%6ww16xwW73owcygKa2EI9z0yd1UU6zMla3Lw3i9wl0Mg62I_ePsPbOID8NYro3G01gwI2PwHfPITcOYH9Ocv6S0Ww0k8b$e%1xP+Wdg$pw16ywGb2oM8zgue1EY5hwX80DUaPYXdPcLa3G01gwJoPYXdPcLa3G01!e%1Bz+We4$pw16ywGb2oM8zgue1EY5hwX80DUaPYXdPcLa3G01gwJoPYXdPcLa3G01!d%1Fj+WeU$p016yMCc28Q7zwqf1koeO09@2I_ePsPb3G01gwJmPYXdPcIeE04!U%6Pf+E_$1C04qa2EI9z0yd1UU6zMl63Iw2vwHfPITcOYEeE0522RzfPITcOYEeE04#c%72f+F2g%iY04q63Esdy0O92UEayMCc28Q7zwqf1kMeA0g30vUaPYXdPcLaOsz7NwWw0k8bmwHfPITcOYH9Ocv63G01gwI$^3w%to+@EB$6o0hEEayMCc28Q7zwqf1koeO09@2I_ePsPbOwWw0k8bmc_ePsPbOwWw0g$%3w%uk+@EO$6o0hEEayMCc28Q7zwqf1koeO09@2I_ePsPbOwWw0k8bmc_ePsPbOwWw0g$%4w%vg+@E_$hw0hEoexMS838AbywGb2oM8zgue1EY5hwXo0w9w2I_ePsPbOID8NYoeE0522MaEPYXdPcLaOsz7NwWw0g$0U%87f+Gt$1C04qa2EI9z0yd1UU6zMl63Iw2vwHfPITcOYEeE0522RzfPITcOYEeE04#8%8mf+Gwg%fc04q63Esdy0O92UEayMCc28Q7zwqf1koeM0dY2I_ePsPbOID8NYoeE0522Mc3wc_ePsPbOID8NYoeE04$0e%2aj+WS8$pw16ywGb2oM8zgue1EY5hwX80DUaPYXdPcLa3G01gwJoPYXdPcLa3G01!f%2e3+WSY$Nw16ygKa2EI9z0yd1UU6zMl63Kw20DEaPYXdPcLaOgWw0k8bvc_ePsPbOIAeE04$^2M%Aw+@Kj$cw0hEEayMCc28Q7zwqf1koeO082q0HfPITcOYEeE0522M%3$Bg+@KX$ro0hEAbywGb2oM8zgue1EY5hwXM0wbA2I_ePsPbOIAeE0522M$0U%9xf+I7w%8a04q63Esdy0O92UEayMCc28Q7zwqf1koeW09Y2I_ePsPbOID8NYoeE0522M$0Y%9Mf+IAM%ag04q92UEayMCc28Q7zwqf1koeO0830sUaPYXdPcLaOgWw0k8b0HbfPITcOYH93G01$h%2w3+Xis%wqw16xwW73owcygKa2EI9z0yd1UU6zMlg3G04lFwnChqq5gc3b0HfPITcOYH9Ocv6SJDo3G01gwI$0f%2Az+Zj4%12016ygKa2EI9z0yd1UU6zMlc3Iw20C8aPYXdPcLaOgWw0k8b0F3fPITcOYH93G01$04M%G8+_lB$LM0hEoexMS838AbywGb2oM8zgue1EY5j0Xg0wc170HfPITcOYH9Ocv63G01gwJq2I_ePsPbOID8NYoeE0522M$^c%2Jz+Zx4%1y016ygKa2EI9z0yd1UU6zMl63Kw20A8aPYXdPcLaOgWw0k8b$03M%Ic+_pE$jw0hEEayMCc28Q7zwqf1koeO09Y2I_ePsPbOwWw0k8b0FEaPYXdPcLa3G01gwI#$bjf+SG$9@04q92UEayMCc28Q7zwqf1koeO082T0HfPITcOYH93G01gwI2qwHfPITcOYH93G01gwI$^4$Kg+_sT%12U0hEAbywGb2oM8zgue1EY5hwX80wc2JwHfPITcOYH93G01gwI30mzfPITcOYH93G01!8%2Zj+@38%1K01czwqf1koeM0830qjfPwWw0g&&&&&&&&&&&&&&&&&&&&~~~`!^3+++++++_Y!$0d2!0PQ!jP`%4`^1!^4`!$04!^1!1eQ!^g!jT!^M!Ha!^d#3X!^6g$%jOM!01I!02!^q#fbw!07!^8$06+_Lk!2a!^5!32!^1w!c8!^E!5wg!0b!01w!^M$%jXo!^8!5Q!^k!^s!05M$%2lo!^s!jm!^8!4w!^2g!0o$06++U!iq$01L++!^8$0r+_Y!16y$06++A!0DM~~~!!01fgw&~~~~!HBw$%2KS!aZo!HZw$%2Mm!b3o!Ilw$%2NS!b9o!IJw$%2Pm!bfo!J5w$%2QS!blo!Jtw$%2Sm!bro!JRw$%2TS!bxo!Kdw$%2Vm!bDo!KBw$%2WS!bJo!KZw$%2Ym!bPo!Llw$%2ZS!bVo!LJw$%2_m!b_o!M5w$%30S!c5o!Mtw$%32m!cbo!MRw$%33S!cho!Ndw$%35m!cno!NBw$%36S!cto!NZw$%38m!czo!Olw$%39S!cFo!OJw$%3bm!cLo!P5w$%3cS++++++++++_M$%hCI#6rM`hDc#6u`0hE2#6wU`hEW#6Ao`hFu#6CM`hG2#6EU`hGu#6GM`hH4#6kU`hHk#6k`0hHy#6j8`hHM#6Lw`hIo#6Ow`hIW#6QM`hJy#6T8`hKq#6Wg`hKY#6YM`hLI#6ew`hLW#6dg`hMa#71E`hMS#748`hNo#77g`hP8#7e`0hQm#7j8`hRY#7p`0hSK#66E`hSY#7tw`hTG#2s$,0k8!16rM`hCu#1Q$,0k8o#6u`0hCi!SR$,0k8M#6wU`hC8!Sp$,0k98#6Ao`hBY#1w$,0k9w#6CM`hBO!Sc$,0k9U#6EU`hBw!R_$,0kag#6GM`hBe!RU$,0kaE#6kU`hB!0QX$,0kb!16k`0hAO!QQ$,0kbo#6j8`hAI#17$,0kbM#6Lw`hAw!Qy$,0kc8#6Ow`hAm!Qr$,0kcw#6QM`hAa!Qk$,0kcU#6T8`hA!0P8$,0kdg#6Wg`hzQ!P1$,0kdE#6YM`hzE!OW$,0ke!16ew`hzk#06$,0keo#6dg`hz8#0n$,0keM#71E`hyY!T_$,0kf8#748`hyG!OP$,0kfw#77g`hyo!OI$,0kfU#7e`0hy6!N3$,0kgg#7j8`hxU!MY$,0kgE#7p`0hxG!Tm$,0kh!166E`hxw!MR$,0kho#7tw!^4t3gPEwa4teliAwcjkKcyUN838MczoMcj8P82xipmgwi65Q834Rbz8KciQTag!w$g%104t1904Poj4!0aOw$%4fSw0KsSxPt79Qom80bCVLt6kKpSVRbC9RqmNAbmBA02VDrDkKq65Pq^Kp7BKsTBJ02VAumVPt780bCtKtiVSpn9PqmZK02VDrDkKtClOsSBLrBZO02VOpmNxbChVrw0KsClIoiVMr7g0bCBKqng0bDhBu7g0bCpFrCA0bD9Lp65Qog0KpmxvpD9xrmlvq6hO02VBq5ZCsC5Jpg0Kt6hxt640bDhysTc0bCBKqnhvon9OonA0bCpFrCBvon9OonA0bChxt64KsClIbD9L02VAumVxrmBz02VDrTg0bCtLt2VMr7g0bChxt640bC9PsM0KoSZJrmlKt^KpSVRbC9RqmNAbC5Qt79FoDlQpnc~~~$b$1M!02!0w!02!%A`^1!$%7C++o!^w!8E!0yw!0U$0c!$%w!$^2w$b!^8!32!0c8!2hw$4$0w!08!01w$M$0M!02!32!0c8!0m1`%g!$^e6++Y!^w#6y!4q8!0Mw$c!$%8!^w%4lL+_@!^8!iq!19E!0f$04$0w!08!$^1k$1!^2!4Rw!jm!18$^M!$^2!^o$nw$g!0gw$%2lo!9lw!5Q$0c$n!^w!06$6w$1!^o!Ha!2IE!03U`^4!$^1z$0g!06!aSw!Hq!0vw`^1!^w$rw$4!01w$%3dg!cR!3so`^1!$%7g$1!^o$%4fI!g@M!02E`^4!$^1W$0g!02#3@!4fU!0_U`^2!$%ww$4!^w$%h_o#7Zw!1t`%g!$^9$01!^8$%4xk!i5g!2_w`^8!$^2q$0g!g3#fa!4YE!^c`^2!$%Eg$w!40M$%jOM#fb!^c`%w!$^as$e!^c$%4YI!jOM!^w`^8!^w%2P$3M!03#fbw$%4YK!^8`^2!^8$LM$4!^M$%jP!1fc!^i`%w!$^cM$6!^c$%4Z2!jQ8!0t$04!$%8!01$3l$0g!03#fJw$%4@S!04E`^2!^8$Sw$4!^M$%k!01g!^1Y`%w!$^ec$1!^c$%51Y!k7M!1S`%8!$^3F$2!^3#il!59k!02`%2!$%Xw$4!0c`1il!^bw`^4!^g%fs$7`59Q!kC!^2g`^4!#$0M`!^59F!04d`%g!^')

_forkrun_bootstrap_setup --force
