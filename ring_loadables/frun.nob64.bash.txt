#!/usr/bin/bash
if shopt -q extglob; then
   extglob_was_set=true;
else
   shopt -s extglob;
fi

frun() {
## bash orchestrator function for forkrun, providing extremely fast shell streaming parallelization
# USAGE:  . frun.bash && printf '%s\n' "${args[@]}" | frun [-flags] [--] parFunc ["${args0[@]}"]
# FLAGS:  [-j <W>] [-l <L>][-b <bytes>] [-k|-u] [-s|-U] [-i|-I] [-d <char>][-v] [-h]
#  HELP:  . frun.bash && frun --help
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
    local cmdline_str ring_ack_str done_str delimiter_val pCode extglob_was_set worker_func_src nn N nWorkers0 arg fd0 fd1 fd2 numa_map_str parsed_numa_nodes_arg have_taskset_flag last_conflict numa_map_str exact_lines_val array_var
    local -g fd_spawn_r fd_spawn_w fd_fallow_r fd_fallow_w fd_order_r fd_order_w ingress_memfd fd_write fd_scan nWorkers nWorkersMax tStart
    local -gx order_mode unsafe_flag stdin_flag byte_mode_flag dry_run_flag LC_ALL
    local -ga fd_out P order_args ring_init_opts

    LC_ALL=C
    set +m

    if shopt -q extglob; then
        extglob_was_set=true;
    else
        shopt -s extglob;
    fi

   # --- HELPER: Expand units (IEC/IEEE prefixes) ---
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

    # --- HELPER: Display HELP ---
    _frun_displayHelp() {
        case "$1" in
            --usage|--help=usage)
                cat <<'EOF' >&2

USAGE: . frun.bash && printf '%s\n' "${args[@]}" | frun [-flags] [--] parFunc ["${args0[@]}"]
FLAGS: [-j <W>] [-l <L>][-b <bytes>] [-k|-u] [-s|-U] [-i|-I] [-d <char>][-v] [-h]
HELP:  . frun.bash && frun --help

EOF
                ;;
            *)
                _frun_displayHelp "--usage"
                cat <<'EOF' >&2

# # # # # FORKRUN V3 FLAGS # # # # #

### DATA PASSING & DELIMITERS
  <default>             : Pass arguments fully quoted via cmdline ("${A[@]}"). (no flag needed)
  -U, --unsafe          : Pass arguments unquoted via cmdline (${A[*]}).
  -s, --stdin           : Pass data to the worker via its stdin (instead of via cmdline arguments).
  -b, --bytes <N>       : Byte mode. Split the stream into N-byte chunks instead of using delimiters (implies -s). Supports standard prefixes (e.g., -b 1M).
  -z, --null            : Use NULL (\0) as the record delimiter instead of newline.
  -d, --delim <char>    : Use a custom single-character record delimiter.

### OUTPUT MODES
  --buffered            : (DEFAULT) Buffered / "atomic fan-in" mode. Output is stored in a memfd and printed once the whole batch finishes.
  -k, --ordered         : Ordered mode. Same as buffered, but output is printed strictly in input-batch order.
  -u, --realtime        : Unbuffered / realtime mode. Workers output directly to stdout. (Can cause kernel lock contention on massive streams).
  -o, --order <mode>    : Explicitly set the mode (buffered, ordered, realtime).

### WORKER & BATCH SCALING (Dynamic Ranges)
  *Syntax note: Options accepting <init>:<max> allow you to define the starting value and the upper bound for the dynamic PID controller. Setting <init> and <max> to 0 or -1 has special meaning. Examples: 1:0 (DEFAULT) (start at 1, scale to default max) | 0:-1 (start at default max, scale to maximum allowed) | 4:16 (start at 4, scale to max of 16).*

  -j, -P, --workers <W> : Set the number of concurrent workers. Supports <init>:<max> (e.g., -j 4:32). Default max is the number of logical cores.
  -l, --lines <L>       : Set the batch size (lines per worker). Supports <init>:<max> (e.g., -l 10:10000). Default max is 4096.
  -L, --exact-lines <N> : Force exactly N lines per batch. (Warning: Disables NUMA topological stealing to guarantee exact counts).
  -t, --timeout <us>    : Set the maximum wait time (in microseconds) for a partial batch before flushing early.

### STRING SUBSTITUTION
  -i, --insert          : Replace {} in the command string with the inputs passed on stdin.
  -I, --insert-id       : Replace {ID} in the command string with [{NODE_NUM}.]{WORKER_NUM}.{BATCH_NUM}. {ID} is unique per batch, and can be used to redirect output per batch.

### LIMITS & TOPOLOGY
  -n, --limit <N>       : Stop processing after exactly N records have been claimed.
  --nodes, --numa <map> : Control NUMA topology mapping. Nodes that do not exist will be skipped (excluding for @N).
                          auto (default): Autodetect all physical online nodes.
                          @N: Oversubscribe / force N logical nodes.
                          0,1: Explicitly bind to physical NUMA nodes 0 and 1.
                          0:3: Explicitly bind to physical NUMA nodes 0 and 1 and 2 and 3.
  -N, --dry-run         : Dry run. Print the generated command strings instead of executing them.
  -v, --verbose         : Increase verbosity (prints timing and flag summaries to stderr). Implies --stats.
  +v, --no-verbose      : Decrease verbosity. Disables --stats.
  -V, --version         : Prints forkrun version number
  --stats               : Prints NUMA statistics to stderr (currently ignored for UMA)

EOF
                ;;
        esac
    }

    # Config Vars
    order_mode='buffered'
    unsafe_flag=false
    byte_mode_flag=false
    verbose_flag=false
    stats_flag=false
    dry_run_flag=false
    delimiter_val=$'\n'
    ring_init_opts=()

    # Parse Arguments
    while true; do
        case "$1" in
            -k|--keep-order|--ordered)          order_mode='ordered'  ;;
            -u|--unbuffered|--realtime)         order_mode='realtime' ;;
            --buffered|--atomic)                order_mode='buffered' ;;

            -U|--unsafe|--UNSAFE)                   unsafe_flag=true  ;;
            +U|--safe|--SAFE)                       unsafe_flag=false ;;

            -s|--stdin)                              stdin_flag=true  ;;
            +s|--no-stdin)                           stdin_flag=false ;;

            --stats)                                 stats_flag=true  ;;
            -v|--verbose)        verbose_flag=true;  stats_flag=true  ;;
            +v|--no-verbose)     verbose_flag=false; stats_flag=false ;;

            -z|--null)                            delimiter_val=''    ;;

            -N|--dry-run|--DRY-RUN)                dry_run_flag=true  ;;

            -i|--insert)                       insert_args_flag=true  ;;
            -I|--insert-id|--INSERT|--INSERT-ID) insert_id_flag=true  ;;

            # --- LIMIT (-n 100) ---
            @(-n|--limit)?(?([= $'\t'])+([0-9+-])))
                arg="${1##@(-n|--limit)?([= $'\t'])}";
                [[ ${arg}${2//+([0-9+-])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _expand_unit "${arg}" && ring_init_opts+=('--limit='"$REPLY") ;;

            # --- EXACT LINES (-L 100) ---
            @(-L|--exact-lines|--EXACT-LINES)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1##@(-L|--exact-lines|--EXACT-LINES)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && { exact_lines_val="${arg}"; last_conflict="exact_lines"; } ;;

            # --- LINES / BATCH (-l 1k or -l 100:1k) ---
            @(-l|--lines|--batchsize)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1##@(-l|--lines|--batchsize)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _parse_count "lines" "${arg}" ;;

            # --- BYTES (-b 1M) ---
            @(-b|--bytes)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1##@(-b|--bytes)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                _parse_count "bytes" "${arg:-}" && ring_init_opts+=("--return-bytes") ;;

            # --- WORKERS (-j 4 or -j 1:8) ---
            @(-j|-P|--workers)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1##@(-j|-P|--workers)?([= $'\t'])}";
                [[ ${arg}${2//?([\+\-])+([0-9:])*([a-zA-Z])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _parse_count "workers" "${arg}" ;;

            # --- TIMEOUT (-t 5000) ---
            @(-t|--timeout)?(?([= $'\t'])+([0-9.+-])))
                arg="${1##@(-t|--timeout)?([= $'\t'])}";
                [[ ${arg}${2//+([0-9.+-])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _expand_unit "${arg}" && ring_init_opts+=('--timeout='"${REPLY}") ;;

            # --- NUMA NODES (--nodes auto) ---
            @(--nodes|--numa)?(?([= $'\t'])*))
                arg="${1##@(--nodes|--numa)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && { parsed_numa_nodes_arg="${arg}"; last_conflict="nodes"; } ;;

            # --- ORDER (-o buffered) ---
            @(-o|--order)?(?([= $'\t'])@(realtime|unbuffered|buffered|atomic|order?(ed))))
                arg="${1##@(-o|--order)?([= $'\t'])}";
                [[ ${arg}${2//@(realtime|unbuffered|buffered|atomic|order?(ed))/} ]] || { shift; arg="$1"; }
                case "${arg}" in
                    realtime|unbuffered) order_mode='realtime' ;;
                    buffered|atomic)     order_mode='buffered' ;;
                    order|ordered|'')    order_mode='ordered'  ;;
                    *)                   order_mode='buffered' ;;
                esac  ;;

            # --- DELIMITER (-d x) ---
            @(-d|--delim|--delimiter)?(?([= $'\t'])*))
                arg="${1##@(-d|--delim|--delimiter)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && delimiter_val="${arg:0:1}" ;;

            # help system
            -h|-\?|--help|--help=*|--usage)  _frun_displayHelp "$1";  return 0  ;;

            -V|--version|--VERSION)   printf 'forkrun v3.0.1\n' >&2;  return 0  ;;

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
        ring_init_opts+=('--stdin' '--return-bytes')
    elif ${byte_mode_flag:-false}; then
        : "${stdin_flag:=true}"
        ring_init_opts+=('--stdin' '--return-bytes')
    elif ${unsafe_flag:-false}; then
        stdin_flag=false
    fi

    ${byte_mode_flag:-false} && ring_init_opts+=('--lines=x')

    [[ "${order_mode}" == "realtime" ]] || ring_init_opts+=('--out=fd_out')

    # --- NUMA Node Discovery and Topology Mapping ---
    : "${parsed_numa_nodes_arg:=auto}"

    _forkrun_build_numa_map() {
        local req c
        local -a online map parts req_list
        req="$1"

        if [[ -r /sys/devices/system/node/online ]]; then
            local raw; read -r raw < /sys/devices/system/node/online
            if [[ -n "$raw" ]]; then
                IFS=',' read -ra parts <<< "$raw"
                for p in "${parts[@]}"; do
                    if [[ "$p" == *-* ]]; then
                        for (( i=${p%%-*}; i<=${p##*-}; i++ )); do online+=("$i"); done
                    else
                        online+=("$p")
                    fi
                done
            fi
        fi
        (( ${#online[@]} == 0 )) && online=(0)

        map=()
        if [[ "$req" == "auto" ]]; then
            map=("${online[@]}")
        elif [[ "$req" == @* ]]; then
            # Oversubscribe / Forced Count mode: --nodes=@N
            c="${req#@}"
            for (( i=0; i<c; i++ )); do map+=("${online[ i % ${#online[@]} ]}"); done
        elif [[ "$req" == *[,:\-]* ]]; then
            # Explicit list mode
            IFS=',' read -ra parts <<< "${req//:/,}"
            for p in "${parts[@]}"; do
                if [[ "$p" == *-* ]]; then
                    for (( i=${p%%-*}; i<=${p##*-}; i++ )); do req_list+=("$i"); done
                else
                    req_list+=("$p")
                fi
            done
            # Intersect against genuinely online physical nodes
            for r in "${req_list[@]}"; do
                for o in "${online[@]}"; do
                    if (( r == o )); then map+=("$r"); break; fi
                done
            done
            (( ${#map[@]} == 0 )) && map=("${online[0]}")
        else
            # Standard Count mode
            c="$req"
            for (( i=0; i<c && i<${#online[@]}; i++ )); do map+=("${online[i]}"); done
            (( ${#map[@]} == 0 )) && map=("${online[0]}")
        fi

        # Fast native array join
        local IFS=','
        numa_map_str="${map[*]}"

        # Export the node count directly while we still have the array
        export FORKRUN_NUM_NODES="${#map[@]}"
    }

    local numa_map_str
     _forkrun_build_numa_map "$parsed_numa_nodes_arg"

    # --- Feature 2: -L vs NUMA Conflict Resolution ---
    if [[ -n "${exact_lines_val:-}" ]] && (( FORKRUN_NUM_NODES > 1 )); then
        if [[ "$last_conflict" == "exact_lines" ]]; then
            printf '\nforkrun [WARNING]: To facilitate using exactly %s arguments per batch, forkrun will run in UMA mode. NUMA optimizations prevent -L from working properly, and will be disabled.\n\n' "${exact_lines_val}" >&2
            # Force UMA mode by re-building the map with exactly 1 node
            _forkrun_build_numa_map "1"
        else
            printf '\nforkrun [WARNING]: forkrun cannot guarantee exactly %s lines per batch in NUMA mode. The -L option has been downgraded to -l, which guarantees a maximum of %s lines per batch. If you need exactly %s lines per batch, remove the --nodes option from the invocation.\n\n' "${exact_lines_val}" "${exact_lines_val}" "${exact_lines_val}" >&2
            # Downgrade to -l (clear exact lines flag so it just parses normally below)
            _parse_count "lines" "${exact_lines_val}"
            exact_lines_val=""
        fi
    fi

    # If exact_lines_val survived (either it was UMA, or we forced UMA), apply it
    if [[ -n "${exact_lines_val:-}" ]]; then
        _parse_count "lines" "${exact_lines_val}"
        ring_init_opts+=("--exact-lines")
    fi

    ring_init_opts+=("--numa-map=$numa_map_str")

    # Initialize Ring
    ring_init "${ring_init_opts[@]}"
    : "${FORKRUN_NUM_NODES:=1}" # Fallback safety

    # Create Data Memfd
    ring_memfd_create ingress_memfd

    # # # # # MAIN # # # # #
    {
        ring_pipe fd_spawn_r fd_spawn_w

        # --- 1. RING FALLOW ---
        ring_pipe fd_fallow_r fd_fallow_w

        # --- 2 & 3. THE PRODUCER PLUMBING ---
        if (( FORKRUN_NUM_NODES > 1 )); then
            # NUMA TOPOLOGICAL PIPELINE (No Pipes, Lock-Free Meta Ring)
            ordered_flag=0
            [[ "${order_mode}" == "ordered" ]] && ordered_flag=1

            ( ring_numa_ingest ${fd0} ${fd_write} $FORKRUN_NUM_NODES $ordered_flag ) &

            for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                ( ring_indexer_numa ${fd_scan} $i ) &
            done

            for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                (
                    exec {fd_fallow_w}>&-
                    ring_numa_scanner ${fd_scan} $i $fd_spawn_w $FORKRUN_NUM_NODES
                ) &
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

        (
            exec {fd_fallow_w}>&-
            if (( FORKRUN_NUM_NODES > 1 )); then
                ring_fallow_phys ${fd_fallow_r} ${fd_write}
            else
                ring_fallow ${fd_fallow_r} ${fd_write}
            fi
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

        # 1. Replace {ID} with the Worker ID, NUMA Node ID, and Worker Batch Num
        if ${insert_id_flag:-false}; then
            cmdline_str="${cmdline_str//\\{ID\\}/\${RING_NODE_ID:+\${RING_NODE_ID}.}\${ID}.\${W_BATCH}}"
        fi

        ${dry_run_flag:-false} && printf -v cmdline_str 'echo %q' "${cmdline_str}"


        ring_ack_str="ring_ack $fd_fallow_w"

        if ${stdin_flag}; then
            # STDIN PAYLOAD
            : "${RING_BYTES_MAX:=1000000000}" "${RING_PIPE_CAPACITY:=65536}"

            # opportunistically probe the kernel's granted capacity
            pCode='
            pipe_open_flag=0
            if (( REPLY <= RING_PIPE_CAPACITY - 4096 )); then
                ring_pipe pr pw
                pipe_open_flag=1
            else
                RING_PIPE_CAPACITY_CUR=0
            fi

            if (( pipe_open_flag && REPLY <= RING_PIPE_CAPACITY_CUR - 4096 )); then
                # FAST PATH (Synchronous)
                # Note: ring_splice "close" closes $pw internally. We only close $pr.
                ring_splice $fd_read $pw "" $REPLY "close" 2>/dev/null || exec {pw}>&-
                '"$cmdline_str"' <&$pr
                exec {pr}<&-
            else
                # SLOW PATH (Asynchronous)
                # Close both FDs so they do not leak into the pipeline
                (( pipe_open_flag )) && exec {pr}<&- {pw}>&-
                ( ring_splice $fd_read 1 "" $REPLY "close" ) | ( '"$cmdline_str"' )
            fi'

        elif ${byte_mode_flag}; then
            # BYTE MODE WITHOUT PASS-BY-STDIN
            # BYTE ARGS PAYLOAD
            array_var='"${A}"'
            if ${insert_args_flag:-false}; then
                cmdline_str="${cmdline_str//\\{\\}/$array_var}"
            else
                cmdline_str+=" $array_var"
            fi

            pCode='
            read -r -u $fd_read -N $REPLY A
            '"$cmdline_str"

        else
            # LINE ARGS PAYLOAD (Default)
            array_var='"${A[@]}"'
            ${unsafe_flag} && array_var='${A[*]}'

            if ${insert_args_flag:-false}; then
                cmdline_str="${cmdline_str//\\{\\}/$array_var}"
            else
                cmdline_str+=" $array_var"
            fi

            if ${unsafe_flag}; then
                cmdline_str="IFS=' ' ${cmdline_str}"
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

        type -p taskset &>/dev/null && have_taskset_flag=true || have_taskset_flag=false

        worker_func_src='spawn_worker() {
(
  LC_ALL=C
  set +m
  export RING_NODE_ID="$2"
'

        if (( FORKRUN_NUM_NODES > 1 )) && ${have_taskset_flag}; then
            worker_func_src+='
  local -a p_nodes=(${numa_map_str//,/ })
  local phys=${p_nodes[$2]}
  if [[ -r /sys/devices/system/node/node${phys}/cpulist ]]; then
      local cpu_list; read -r cpu_list < /sys/devices/system/node/node${phys}/cpulist
      [[ $cpu_list ]] && taskset -pc "$cpu_list" $BASHPID >/dev/null 2>&1
  fi
'
        fi

        worker_func_src+='
  {
    ID="$1"
    '
       ${insert_id_flag:-false} && worker_func_src+='W_BATCH=0
    '
        worker_func_src+='shift 2
    ring_worker inc $fd_read
    while ring_claim; do
        if [[ "$REPLY" != "0" ]]; then
            '
         ${insert_id_flag:-false} && worker_func_src+='((W_BATCH++))
            '
        worker_func_src+="${pCode}"'
        fi
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
        finished_scanners=0

        declare -a node_workers
        for ((i=0; i<FORKRUN_NUM_NODES; i++)); do node_workers[i]=0; done
        node_worker_max=$(( nWorkersMax / FORKRUN_NUM_NODES ))
        (( node_worker_max < 1 )) && node_worker_max=1

        while (( finished_scanners < FORKRUN_NUM_NODES )); do
            # FIX: If the pipe hits EOF (all scanners dead/exited), break out safely
            if ! read -r -u $fd_spawn_r msg; then
                break
            fi

            if [[ "$msg" == *'x'* ]]; then
                ((finished_scanners++))
                continue
            fi

            # Parse directed spawn "node:count" or legacy "count"
            if [[ "$msg" == *:* ]]; then
                node_idx="${msg%%:*}"
                spawn_count="${msg#*:}"
            else
                node_idx=0
                spawn_count="$msg"
            fi

            target=$(( node_workers[node_idx] + spawn_count ))
            (( target > node_worker_max )) && target=$node_worker_max

            for (( ; node_workers[node_idx] < target; node_workers[node_idx]++ )); do
                spawn_worker "$nWorkers" "$node_idx"
                ((nWorkers++))
            done
        done

        ${verbose_flag} && printf '\nSPAWNED %s workers (%s)\n' "${nWorkers}" "${nWorkersA[*]}" >&2

        # --- SHUTDOWN ---
        exec {fd_spawn_r}<&- {fd_fallow_w}>&-
        [[ "${order_mode}" == "realtime" ]] || exec {fd_order_w}>&-

        wait

        { ${stats_flag} || ${verbose_flag}; } && (( FORKRUN_NUM_NODES > 1 )) && ring_numa_stats

        ring_destroy
        exec {fd_write}>&- {fd_scan}>&- {ingress_memfd}>&-

    } {fd_write}>"/proc/${BASHPID}/fd/${ingress_memfd}" {fd_scan}<"/proc/${BASHPID}/fd/${ingress_memfd}" {fd0}<&0 {fd1}>&1 {fd2}>&2
    exit 0
  ) {fd00}<&0 {fd11}>&1 {fd22}>&2
}

# ==============================================================================
# BASH AUTO-COMPLETION FOR FRUN
# ==============================================================================
_frun_complete() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # V3 Supported Flags
    opts="-k --keep-order --ordered -u --unbuffered --realtime --buffered --atomic \
          -U --unsafe +U --safe -s --stdin +s --no-stdin -v --verbose +v --no-verbose \
          -z --null -N --dry-run -i --insert -I --insert-id -n --limit -L --exact-lines \
          -l --lines --batchsize -b --bytes -j -P --workers -t --timeout --nodes --numa \
          -o --order -d --delim --delimiter -h --help --usage"

    # If the user is currently typing a flag
    if [[ ${cur} == -* ]] ; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
        return 0
    fi

    # If the user is typing the command to parallelize
    if [[ ${prev} == frun || ${prev} == -* ]]; then
        COMPREPLY=( $(compgen -c -- "${cur}") )
        return 0
    fi
}
complete -F _frun_complete frun


# ==============================================================================
# AUTO-BOOTSTRAP FOR FRUN LOADABLES
# ==============================================================================
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
        if grep -qE '( avx512[cdbwdqvlf].*){5}' </proc/cpuinfo; then
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

declare -A b64=()  # REMOVED BASE64

_forkrun_bootstrap_setup --force
