#!/usr/bin/bash

if shopt -q extglob; then
   extglob_was_set=true;
else
   shopt -s extglob;
fi

frun() {
## bash orchestrator function for forkrun, providing extremely fast shell streaming parallelization 
# USAGE:  . frun.bash && printf '%s\n' "${args[@]}" | frun [-flags] [--] parFunc ["${args0[@]}"]
# FLAGS:  [-j <W>] [-l <L>][-b <bytes>] [-k|-u] [-s|-U] [-i|-I] [-d <char>] [-E] [-v] [-h]
#  HELP:  . frun.bash && frun --help 
(
    # 1. WRAPPER LOGIC (Current Shell)
    [[ "${1}" == '__exec__' ]] || {

        # Check if already setup (and FD is valid), otherwise bootstrap
        { ${FORKRUN_RING_ENABLED:-false} && (( ${FORKRUN_MEMFD_LOADABLES:-0} > 0 )); } || _forkrun_bootstrap_setup --fast

        # Generate list of loadables to enable in the new shell
        (( ${#ring_funcs[@]} > 0 )) || ring_list 'ring_funcs'
        printf -v ring_enable '%s ' "${ring_funcs[@]}"

        for nn in "${@##\-*}"; do
            [[ ${nn} ]] && declare -F -- "$nn" &>/dev/null && ! [[ " ${FORKRUN_EXTRA_FUNCS} " == *" ${nn} "* ]] && FORKRUN_EXTRA_FUNCS+=" ${nn}"
        done
        FORKRUN_EXTRA_VARS+=' FORKRUN_EXTRA_FUNCS FORKRUN_EXTRA_VARS FORKRUN_EXTRA_SETUP'

        FORKRUN_FRUN_SRC+=$'\n'"$(declare -f -- frun ${FORKRUN_EXTRA_FUNCS:-} 2>/dev/null; declare -p -- ${FORKRUN_EXTRA_VARS} 2>/dev/null)"
        [[ -n "${FORKRUN_EXTRA_SETUP}" ]] && FORKRUN_FRUN_SRC+=$'\n'"${FORKRUN_EXTRA_SETUP}"

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
    FORKRUN_ORIG_ARGS=("$@")

    # # # # # SETUP # # # # #
    local cmdline_str ring_ack_str done_str delimiter_val pCode extglob_was_set worker_func_src nn N nWorkers0 arg fd0 fd1 fd2 numa_map_str parsed_numa_nodes_arg have_taskset_flag last_conflict numa_map_str exact_lines_val array_var resume_file order_mode unsafe_flag stdin_flag byte_mode_flag dry_run_flag checkpoint_file prefer_external_flag NORMAL_EXIT_FLAG c_plugin_arg
    local -g fd_spawn_r fd_spawn_w fd_fallow_r fd_fallow_w fd_order_r fd_order_w ingress_memfd fd_write fd_scan nWorkers nWorkersMax tStart
    local -gx LC_ALL
    local -a fallow_args
    local -ga fd_out P order_args ring_init_opts

    LC_ALL=C
    set +m

    if shopt -q extglob; then
        extglob_was_set=true;
    else
        shopt -s extglob;
        extglob_was_set=false;
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
        (( REPLY < -1 )) && { REPLY=$(( (1<<63) - 1 )); printf '\nWARNING: value expanded to larger than maximum int64. truncated to %s \n' "$REPLY" >&2; }
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
FLAGS: [-j <W>] [-l <L>][-b <bytes>] [-k|-u] [-s|-U] [-i|-I] [-d <char>] [-E] [-v] [-h]
HELP:  . frun.bash && frun --help 

EOF
                ;;
            *)
                _frun_displayHelp "--usage"
                cat <<'EOF' >&2

# # # # # FORKRUN V3 FLAGS # # # # #

### DATA PASSING & DELIMITERS
  <default>             : Pass arguments fully quoted via cmdline ("${A[@]}"). (no flag needed)
  -U, --unsafe          : Pass arguments unquoted via cmdline (${A[*]}). (WARNING: This flag forces Bash AST array expansion. Do NOT use this flag to speed up external binaries, as it disables the ultra-fast C-level vfork engine!)
  -X, --external        : Force external binary execution to enable the ultra-fast C-level vfork engine, which is FASTER than parallelizing the equivalent builtin command. If a command exists as both a builtin and a disk binary, this prefers the disk binary. (NOTE: If -U or -i or -I are used, the ultra-fast-path is disabled, and this flag has no effect).
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

### ERROR HANDLING & RETRIES
  -E, --retry-nonzero-exit    : Activate auto-retry machinery for commands returning non-zero exit codes. When active, `|| exit $?` is appended to the parallelized command, meaning any non-zero return triggers a worker kill and batch retry.
  *Note on subshells*: When parallelizing functions that spawn subshells without -E active,
  failures must be manually guarded to return 200 to trigger the retry machinery (along with
  137 SIGKILL and 139 SIGSEGV). To protect the entire subshell, use the following pattern:
      ff() {
        # ...
        (
          # all subshell cmds
          true   # <--- ADD THIS AT THE VERY END OF THE SUBSHELL
        ) || return 200
        # ...
      }

### CHECKPOINT & RESUME
  --resume <file>       : Resume a previously aborted pipeline using the specified checkpoint file.
                          - Buffered/Ordered modes: Provides "Exactly-Once" semantics. Ensure you truncate your output file to the byte count specified in the crash message before resuming.
                          - Realtime (-u) mode: Provides "At-Least-Once" semantics. Resuming may result in a few duplicate lines at the failure boundary.
  --checkpoint-file <f> : Specify a custom filename for the checkpoint file written on failure. (Default: .forkrun_resume)

### UNSETTING FLAGS
  +U, +s, +N, +i, +I, +E, +X, +v, --no-stats : disables the corresponding flag listed above, restoring default behavior. If both +flag and -flag are used, the last one passed is used.

### ENVIRONMENT VARS
  FORKRUN_RETRY_LIMIT   : Controls how many times a batch will be retried before it is declared poisoned. 0 means declared poisoned after the 1st failure. A negative value means it will never be declared poisoned (and could retry indefinitely). Default is 3.
  FORKRUN_EXTRA_FUNCS   : Use this to specify required sub-functions to pass into frun's environment.
      EXAMPLE: `hh() { echo "$@"; }; gg() { hh "$@"; }; ff() { gg "$@"; };`. If you call `frun ff <inputs` the definition for `ff` will automatically be available to `frun` but the definitions for `gg` and `hh` will not be. Instead, call `FORKRUN_REQ_FUNCS='gg hh' frun ff <inputs`.
  FORKRUN_EXTRA_VARS    : Use this to specify (environment) variables to pass into frun's environment
      EXAMPLE: If your code depends on variable X and X is only defined in your current shell session (and not in the code you are running) then you need to call `frun` via `FORKRUN_EXTRA_VARS='X' frun ...`
  FORKRUN_EXTRA_SETUP   : Use this to specify raw commands that need to be run in frun's environment during setup
      EXAMPLE: If you are running frun with a custom loadable builtin, then you would enable it via `FORKRUN_EXTRA_SETUP='enable -f "/path/to/custom_loadable.so" custom_loadable'`
  FORKRUN_USE_HUGETLB   : Set to '1' to have forkrun attempt to use hugepages for memfd backing. WARNING: only enable this if you have sufficient available hugepages so that forkrun does NOT run out of memory to use.

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
    is_func_flag=false
    resume_flag=false
    retry_nonzero_exit_flag=false
    prefer_external_flag=false
    delimiter_val=$'\n'
    ring_init_opts=()
    checkpoint_file='.forkrun_resume'
    c_plugin_arg=""

    # Parse Arguments
    while true; do
        case "$1" in
            -k|--keep-order|--ordered)          order_mode='ordered'  ;;
            -u|--unbuffered|--realtime)         order_mode='realtime' ;;
            --buffered|--atomic)                order_mode='buffered' ;;

            -z|--null)                              delimiter_val=''  ;;

            -U|--unsafe|--UNSAFE)                   unsafe_flag=true  ;;
            +U|--safe|--SAFE)                       unsafe_flag=false ;;

            -s|--stdin)                              stdin_flag=true  ;;
            +s|--no-stdin)                           stdin_flag=false ;;

            -N|--dry-run|--DRY-RUN)                dry_run_flag=true  ;;
            +N|--no-dry-run|--NO-DRY-RUN)          dry_run_flag=false ;;

            -i|--insert)                       insert_args_flag=true  ;;
            +i|--no-insert)                    insert_args_flag=false ;;

            -I|--insert-id|--INSERT|--INSERT-ID) insert_id_flag=true  ;;
            +I|--no-insert-id|--NO-INSERT|--NO-INSERT-ID) insert_id_flag=false ;;

            -E|--retry-nonzero-exit)    retry_nonzero_exit_flag=true  ;;
            +E|--no-retry-nonzero-exit) retry_nonzero_exit_flag=false ;;

            -X|--external|--EXTERNAL)      prefer_external_flag=true  ;;
            +X|--no-external|--NO-EXTERNAL|--internal|--INTERNAL) prefer_external_flag=false ;;

            -C|--plugin|--PLUGIN)
                arg="${1##@(-C|--plugin|--PLUGIN)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && c_plugin_arg="${arg}" ;;

            -v|--verbose)        verbose_flag=true;  stats_flag=true  ;;
            +v|--no-verbose)     verbose_flag=false; stats_flag=false ;;

            --stats)                                 stats_flag=true  ;;
            --no-stats)                              stats_flag=false ;;

            @(--checkpoint-file)?(?([= $'\t'])*))
                arg="${1##@(--checkpoint-file)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && checkpoint_file="${arg}" ;;

            @(--resume)?(?([= $'\t'])*))
                arg="${1##@(--resume)?([= $'\t'])}";
                [[ ${arg} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && resume_file="${arg}"
                if [[ -f "$resume_file" ]]; then
                    eval "$(PATH='' exec -c "${BASH:-bash}" --norc --noprofile --restricted -c 'eval "$1"; builtin declare -p FORKRUN_RESUME_HORIZON FORKRUN_RESUME_STDOUT_BYTES FORKRUN_RESUME_JAGGED FORKRUN_ORIG_ARGS FORKRUN_EXTRA_FUNCS FORKRUN_EXTRA_VARS FORKRUN_EXTRA_SETUP FORKRUN_RETRY_LIMIT' _ "$(< "$resume_file")" 2>/dev/null)"
                    resume_flag=true

                    # If the user only provided the resume file (no extra args), inject the original ones
                    if (( $# == 1 )) && (( ${#FORKRUN_ORIG_ARGS[@]} > 0 )); then

                        # Set positional parameters: keep resume_file at $1 so the bottom
                        # 'shift' safely drops it, then append the original arguments.
                        set -- "" "${FORKRUN_ORIG_ARGS[@]}"

                        # Resurrect the bash functions into the current shell environment
                        [[ -n "${FORKRUN_EXTRA_SETUP:-}" ]] && eval "${FORKRUN_EXTRA_SETUP}"
                    fi

                    # We intentionally do NOT call 'continue' here!
                    # This allows the loop to hit the 'shift' at the bottom of the case statement,
                    # which will drop $1 (the resume_file) and smoothly begin parsing the
                    # newly injected FORKRUN_ORIG_ARGS on the next iteration.
                else
                    echo "forkrun [ERROR]: Resume file '$resume_file' not found." >&2
                    return 1
                fi ;;

            # --- LIMIT (-n 100) ---
            @(-n|--limit)?(?([= $'\t'])+([0-9+-])))
                arg="${1##@(-n|--limit)?([= $'\t'])}";
                [[ ${arg}${2//+([0-9+-])/} ]] || { shift; arg="$1"; }
                [[ ${arg} ]] && _expand_unit "${arg}" && ring_init_opts+=('--limit='"$REPLY") ;;

            # --- EXACT LINES (-L 100) ---
            @(-L|--exact-lines|--LINES|--EXACT-LINES)?(?([= $'\t'])?([\+\-])+([0-9:])*([a-zA-Z])))
                arg="${1##@(-L|--exact-lines|--LINES|--EXACT-LINES)?([= $'\t'])}";
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
                _parse_count "bytes" "${arg:-}" ;;

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
                if [[ -z "${arg}" && "$1" == @(-d|--delim|--delimiter) ]]; then
                    shift; arg="$1";
                fi
                delimiter_val="${arg:0:1}" ;;

            # help system
            -h|-\?|--help|--help=*|--usage)  _frun_displayHelp "$1";  return 0  ;;

            -V|--version|--VERSION)           echo 'forkrun v3.2.1';  return 0  ;;

            --) shift; break ;;

            *) break ;;
        esac
        shift
    done
    unset arg
    # --- AST MANIPULATION FOR BASH FUNCTIONS ---
    declare -F -- "$1" &>/dev/null 2>&1 && is_func_flag=true
    if [[ -n "$1" ]] && ${is_func_flag}; then
        local func_def body body_start body_trimmed test_body
        func_def="$(declare -f -- "$1")"

        # 1. Extract the contents inside the global { ... }
        body="${func_def#*\{}"
        body="${body%\}}"

        # Trim leading and trailing whitespace
        body_trimmed="${body##+([[:space:]])}"
        body_trimmed="${body_trimmed%%+([[:space:]])}"

        # 2. Check if it visually starts and ends with parentheses
        if [[ "$body_trimmed" == \(*\) ]]; then
            # Strip the very first '(' and the very last ')'
            test_body="${body_trimmed#\(}"
            test_body="${test_body%\)}"

            # 3. THE GENIUS CHECK: Ask the Bash parser if this is valid!
            # We run this in a subshell to keep the environment perfectly clean.
            # Explicit newlines prevent trailing comments from breaking the brace.
            if ( "${BASH:-bash}" -O extglob -n -c "function _frun_syntax_check() {"$'\n'"${test_body}"$'\n'"}" ) >/dev/null 2>&1; then
                # It is a verified global subshell!
                # Strip the last ')' and inject 'true' safely inside it.
                retry_nonzero_exit_flag=true
                body_start="${body_trimmed%?}"
                eval "${func_def%%\{*}"'{'$'\n'"${body_start}"$'\n''true'$'\n'')'$'\n''}'
            fi
        fi

        unset func_def body body_start body_trimmed test_body
    fi

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

    ring_init_opts+=("--delim=${delimiter_val}")

    [[ "${order_mode}" == "realtime" ]] || ring_init_opts+=('--out=fd_out')

    # --- NUMA Node Discovery and Topology Mapping ---
    : "${parsed_numa_nodes_arg:=auto}"

    _forkrun_build_numa_map() {
        local req c
        local -a online map parts req_list
        req="$1"

        # NEW: Explicit Global UMA (No Pinning)
        if [[ "$req" == "@0" || "$req" == "0" || "$req" == "uma" || "$req" == "none" ]]; then
            export FORKRUN_NUM_NODES=1
            numa_map_str=""
            return 0
        fi

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
        export FORKRUN_NUM_NODES="${#map[@]}"

        # NEW: If 'auto' discovered a 1-node machine, skip explicit pinning
        if [[ "$req" == "auto" && "$FORKRUN_NUM_NODES" == 1 ]]; then
            numa_map_str=""
        fi
    }

    local numa_map_str
     _forkrun_build_numa_map "$parsed_numa_nodes_arg"

    # PHYSICS FIX: Small File NUMA Starvation Prevention
    # If the input is a regular file and is too small to benefit from NUMA,
    # downgrade to UMA (unless the user explicitly specified --nodes list).
    if [[ "${parsed_numa_nodes_arg}" == "auto" ]] && [[ -f /dev/stdin ]] && (( FORKRUN_NUM_NODES > 1 )); then
        local orig_pos file_size
        if ring_lseek 0 0 SEEK_CUR orig_pos; then
            if ring_lseek 0 0 SEEK_END file_size; then
                local remaining_bytes=$(( file_size - orig_pos ))
                if (( remaining_bytes > 0 && remaining_bytes < FORKRUN_NUM_NODES * 8192 )); then
                    parsed_numa_nodes_arg="1"
                    _forkrun_build_numa_map "1"
                fi
            fi
            ring_lseek 0 "${orig_pos}" SEEK_SET orig_pos
        fi
    fi

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

    if [[ -n "$numa_map_str" ]]; then
        ring_init_opts+=("--numa-map=$numa_map_str")
    fi

    # Initialize Ring
    ring_init "${ring_init_opts[@]}"
    : "${FORKRUN_NUM_NODES:=1}" # Fallback safety

    # Create Data Memfd
    ring_memfd_create ingress_memfd

    # NEW: Apply Checkpoint if Resuming
     ${resume_flag} && ring_set_resume "$FORKRUN_RESUME_HORIZON" "${FORKRUN_RESUME_JAGGED[@]}"

    # # # # # MAIN # # # # #
    {
        trap '

            status=${_ret_val:-$?}
            if ! ${NORMAL_EXIT_FLAG:-false}; then
                echo "forkrun [FATAL]: Pipeline aborted. Generating checkpoint..." >&2
                ${NORMAL_EXIT_FLAG:-true} || ring_abort

                # ALWAYS write the resume file!
                ring_dump_resume > "'"${checkpoint_file}"'"
                for nn in ${FORKRUN_EXTRA_FUNCS}; do
                    declare -F -- "${nn}" &>/dev/null && ! [[ "${FORKRUN_EXTRA_SETUP}" == *$'"'"'\n'"'"'"${nn}"$'"'"' () \n{'"'"'*'"'"'}'"'"'* ]] && FORKRUN_EXTRA_SETUP+="
$(declare -f -- "${nn}")"
                done
                declare -p -- FORKRUN_ORIG_ARGS ${FORKRUN_RETRY_LIMIT:+${FORKRUN_RETRY_LIMIT}} ${FORKRUN_EXTRA_VARS} 2>/dev/null >> "'"${checkpoint_file}"'"

                if [[ "${order_mode}" != "realtime" ]]; then
                    local safe_bytes="$(grep -E '"'"'^FORKRUN_RESUME_STDOUT_BYTES='"'"' "${checkpoint_file}")"
                    safe_bytes="${safe_bytes#*=}"
                    echo "forkrun: To resume safely, truncate your output file to exactly ${safe_bytes} bytes," >&2
                    echo "         then re-run your exact command with: --resume '"${checkpoint_file}"'" >&2
                else
                    echo "forkrun: Warning - Realtime mode (-u) checkpoint generated." >&2
                    echo "         Resuming will result in some duplicate lines at the failure boundary (At-Least-Once semantics)." >&2
                    echo "         Re-run your exact command with: --resume '"${checkpoint_file}"'" >&2
                fi
            fi
            # Clean up memory only AFTER the trap is done with it!
            ring_destroy 2>/dev/null
            return $status
        ' EXIT INT
        ring_pipe fd_spawn_r fd_spawn_w

        # --- 1. RING FALLOW ---
        ring_pipe fd_fallow_r fd_fallow_w

        # --- 2 & 3. THE PRODUCER PLUMBING ---
            declare -a fd_scan_death_r fd_scan_death_w SCANNER_P
            ring_pipe fd_trap_ack_r fd_trap_ack_w
        
            if (( FORKRUN_NUM_NODES > 1 )); then
                # NUMA TOPOLOGICAL PIPELINE
                ordered_flag=0
                [[ "${order_mode}" == "ordered" ]] && ordered_flag=1

                ( exec {fd_trap_ack_w}>&-; ring_numa_ingest ${fd0} ${fd_write} $FORKRUN_NUM_NODES $ordered_flag ) &

                for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                    ( exec {fd_trap_ack_w}>&-; ring_indexer_numa ${fd_scan} $i ) &
                done

                for (( i=0; i<FORKRUN_NUM_NODES; i++ )); do
                    ring_pipe fd_scan_death_r[$i] fd_scan_death_w[$i]
                    (
                        exec {fd_fallow_w}>&- {fd_trap_ack_w}>&-
                        ring_numa_scanner ${fd_scan} $i $fd_spawn_w $FORKRUN_NUM_NODES
                    ) &
                    SCANNER_P[$i]=$!
                    exec {fd_scan_death_w[$i]}>&-
                done

            else
                # LEGACY FLAT PIPELINE
                ( exec {fd_trap_ack_w}>&-; ring_copy ${fd_write} ${fd0}; ring_signal ) &
                ring_pipe fd_scan_death_r[0] fd_scan_death_w[0]
                (
                    exec {fd_spawn_r}<&- {fd_trap_ack_w}>&-
                    ring_scanner ${fd_scan} ${fd_spawn_w}
                ) &
                SCANNER_P[0]=$!
                exec {fd_scan_death_w[0]}>&-
            fi

        exec {fd_spawn_w}>&-

        (
            exec {fd_fallow_w}>&- {fd_trap_ack_w}>&-
            fallow_args=( "${fd_fallow_r}" "${fd_write}" )
            if (( FORKRUN_NUM_NODES > 1 )); then
                ring_fallow_phys "${fallow_args[@]}"
            else
                ring_fallow "${fallow_args[@]}"
            fi
        ) &
        exec {fd_fallow_r}<&-

        # --- 4. RING ORDER ---
        [[ "${order_mode}" == "realtime" ]] || {
            ring_pipe fd_order_r fd_order_w
            (
                exec {fd_order_w}>&- {fd_trap_ack_w}>&-

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
            cmdline_str="${cmdline_str//\\\{ID\\\}/\{\${RING_NODE_ID:+\$\{RING_NODE_ID\}.\}\$\{ID\}.\$\{W_BATCH\}\}}"
        fi

        ${dry_run_flag:-false} && printf -v cmdline_str 'echo %q' "${cmdline_str}"

        ring_ack_str="ring_ack $fd_fallow_w"

        # Determine if the target command is safe for direct posix_spawn
        local cmd_type
        if ${prefer_external_flag:-false}; then
            cmd_type=$(type -Pt "$1" 2>/dev/null)
        else
            cmd_type=$(type -t "$1" 2>/dev/null)
        fi
        local use_ultra_fast_path=false

        # Only use the fast path if it's an external file, safe mode, and no {} insertions
        if [[ "$cmd_type" == "file" ]] && ! ${unsafe_flag:-false} && ! ${insert_args_flag:-false}; then
            # Resolve absolute path (e.g., "grep" -> "/usr/bin/grep")
            local cmd_path=$(type -P "$1" 2>/dev/null)
            
            if [[ -n "$cmd_path" ]]; then
                # Check if it's a compiled binary or has a shebang
                if ring_is_spawnable "$cmd_path"; then
                    use_ultra_fast_path=true
                fi
            fi
        fi

        if [[ -n "${c_plugin_arg:-}" ]]; then
            # Ensure the user actually passed a colon!
            if [[ "$c_plugin_arg" != *:* ]]; then
                echo "forkrun [FATAL]: -C requires format 'path/to/plugin.so:function_name'" >&2
                return 1
            fi

            # C PLUGIN PAYLOAD (ULTRA-FASTEST PATH)
            local plugin_so="${c_plugin_arg%:*}"
            local plugin_fn="${c_plugin_arg#*:}"

            type -P realpath &>/dev/null && plugin_so="$(realpath "$plugin_so")"
            
            # --- JIT C-COMPILER LOGIC (With Fileless Execution) ---
            local plugin_c="${plugin_so%.so}.c"
            
            # Recompile if .so is missing, or if .c is newer than .so
            if [[ -f "$plugin_c" && ( ! -f "$plugin_so" || "$plugin_c" -nt "$plugin_so" ) ]]; then
                if type -P gcc >/dev/null; then
                    local target_so="$plugin_so"
                    local use_memfd=false

                    # Check if we have write access to the directory
                    if [[ ! -w "${plugin_so%/*}/" ]]; then
                        use_memfd=true
                    fi

                    if $use_memfd; then
                        ${verbose_flag} && echo "forkrun [INFO]: Read-only filesystem detected. Compiling $plugin_c to memfd..." >&2
                        ring_memfd_create plugin_memfd
                        target_so="/proc/self/fd/$plugin_memfd"
                    else
                        ${verbose_flag} && echo "forkrun [INFO]: Auto-compiling $plugin_c -> $plugin_so" >&2
                    fi

                    # Compile directly to the target (Disk or RAM)
                    gcc -O3 -shared -fPIC -march=native "$plugin_c" -o "$target_so" || {
                        echo "forkrun [FATAL]: Auto-compilation of $plugin_c failed." >&2
                        return 1
                    }

                    if $use_memfd; then
                        # Seal the memfd to prevent tampering, and override the plugin_so path
                        ring_seal "$plugin_memfd"
                        plugin_so="$target_so"
                    fi
                else
                    echo "forkrun [FATAL]: 'gcc' is not installed to compile $plugin_c." >&2
                    return 1
                fi
            fi

            # Sanity check: Ensure we actually have a target to execute before spawning workers
            if [[ ! -f "$plugin_so" ]]; then
                echo "forkrun [FATAL]: Plugin '$plugin_so' not found or could not be compiled." >&2
                return 1
            fi

            if [[ ${delimiter_val} ]]; then
                printf -v delimiter_str '%q' "${delimiter_val}"
            else
                delimiter_str="''"
            fi

            pCode='
            ring_call $fd_read $REPLY '"${delimiter_str} ${plugin_so@Q} ${plugin_fn@Q}"

        elif ${stdin_flag}; then
            # STDIN PAYLOAD
            if $use_ultra_fast_path; then
                # ALL-IN-C ZERO-COPY PIPELINE
                pCode='ring_exec_splice $fd_read $REPLY '"$cmdline_str"
            else
                # STANDARD BASH PIPE PIPELINE
                : "${RING_BYTES_MAX:=1000000000}" "${RING_PIPE_CAPACITY:=65536}"
                
                local exec_cmd_str="$cmdline_str"
                pCode='
                pipe_open_flag=0
                if (( REPLY <= RING_PIPE_CAPACITY - 4096 )); then
                    ring_pipe pr pw
                    pipe_open_flag=1
                else
                    RING_PIPE_CAPACITY_CUR=0
                fi

                # opportunistically probe the kernels granted capacity    
                if (( pipe_open_flag && REPLY <= RING_PIPE_CAPACITY_CUR - 4096 )); then
                    # FAST PATH (Synchronous)
                    # Note: ring_splice "close" closes $pw internally. We only close $pr.
                    ring_splice $fd_read $pw "-" $REPLY "close" 2>/dev/null || exec {pw}>&-
                    '"$exec_cmd_str"' <&$pr'
                if ${retry_nonzero_exit_flag}; then
                    pCode+=' || exit $?'
                elif ${is_func_flag}; then
                    pCode+='
                    ret=$?
                    (( ret == 137 || ret == 139 || ret == 200 )) && exit $ret'
                fi
                pCode+='
                    exec {pr}<&-
                else
                    # SLOW PATH (Asynchronous)
                    # Close both FDs so they do not leak into the pipeline
                    (( pipe_open_flag )) && exec {pr}<&- {pw}>&-
                    ( ring_splice $fd_read 1 "-" $REPLY "close" ) | ( '"$exec_cmd_str"' )'
                if ${retry_nonzero_exit_flag}; then
                    pCode+=' || exit $?'
                elif ${is_func_flag}; then
                    pCode+='
                    ret=$?
                    (( ret == 137 || ret == 139 || ret == 200 )) && exit $ret'
                fi
                pCode+='
                fi'
            fi

        elif ${byte_mode_flag}; then
            # BYTE MODE WITHOUT PASS-BY-STDIN
            # BYTE ARGS PAYLOAD
            array_var='"${A}"'
            if ${insert_args_flag:-false}; then
                cmdline_str="${cmdline_str//\\\{\\\}/$array_var}"
            else
                cmdline_str+=" $array_var"
            fi

            if $use_ultra_fast_path; then
                # Length 0 bypasses do_tokenize and acts as pure vfork wrapper
                pCode='ring_exec 0 0 '\'''\'' '"$cmdline_str"
            else
                pCode='
                ring_lseek $fd_read - SEEK_SET _dummy
                read -r -u $fd_read -N $REPLY A
                '"$cmdline_str"
            fi

        else
            # LINE ARGS PAYLOAD (Default)

            if $use_ultra_fast_path; then
                # ULTRA-FAST PATH: Bypass Bash AST entirely!
                if [[ ${delimiter_val} ]]; then
                    printf -v delimiter_str '%q' "${delimiter_val}"
                else
                    delimiter_str="''"
                fi
                
                # $cmdline_str already contains the quoted command and fixed args
                pCode='
            ring_exec $fd_read $REPLY '"${delimiter_str}"' '"$cmdline_str"
            else
                # STANDARD FAST PATH: Mapfile replacement for Shell Functions & Builtins
                array_var='"${A[@]}"'
                ${unsafe_flag} && array_var='${A[*]}'

                if ${insert_args_flag:-false}; then
                    cmdline_str="${cmdline_str//\\\{\\\}/$array_var}"
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
            ring_map $fd_read $REPLY A '"${delimiter_str}"'
            '"$cmdline_str"
            fi
        fi

        [[ "${order_mode}" == "realtime" ]] || {
            pCode+=' >&${fd_out[$RING_WID]}'
            ring_ack_str+=' ${fd_out[$RING_WID]}'
        }

       ${stdin_flag} || {
           if ${retry_nonzero_exit_flag}; then
                pCode+=' || exit $?'
            elif ${is_func_flag}; then
                pCode+='
            ret=$?
            (( ret == 137 || ret == 139 || ret == 200 )) && exit $ret'
            fi
        }

        worker_func_src='spawn_worker() {
(
  LC_ALL=C
  set +m
  export RING_NODE_ID="$2"
  export RING_WID="$3"
  export FD_TRAP_ACK_W="$4"
  
  _ring_registered=false
  
  trap '"'"'
    status=$?
    ${_ring_registered} && { ring_worker dec; ring_cleanup_waiter; }
    
    if (( status != 0 && REPLY > 0 )); then
        (( RING_NUM_KILLS++ ))'
        [[ "$order_mode" != "realtime" ]] && worker_func_src+='
        [[ -n "${fd_out[$RING_WID]:-}" ]] && ring_revert_output "${fd_out[$RING_WID]}"
        '
        worker_func_src+='
        ring_escrow_put "$RING_NODE_ID" "-" "-" "$RING_NUM_KILLS"
    fi
    
    # Notify parent that the trap successfully fired
    if (( status != 0 )); then
        echo "$RING_WID" >&"${FD_TRAP_ACK_W}" 2>/dev/null
    fi
    exit $status
  '"'"' EXIT

  trap '"'"'ring_abort
  kill -INT '"${BASHPID}'"' INT

  {
    ID="$1" # ID is passed purely for user payload compatibility/insertion
    RING_NUM_KILLS=0
    RING_POISONED=0
    REPLY=0
    '
   [[ "$order_mode" != "realtime" ]] && worker_func_src+='
    # Initialize the output tracking for this specific worker slot
    [[ -n "${fd_out[$RING_WID]:-}" ]] && ring_ack_init "${fd_out[$RING_WID]}"
    '
        ${insert_id_flag:-false} && worker_func_src+='W_BATCH=0
    '
        worker_func_src+='shift 4
    ring_worker inc
    _ring_registered=true
    while ring_claim; do
        if [[ "${RING_POISONED}" == "1" ]]; then
            echo "forkrun [WARN]: Skipping poisoned batch $RING_BATCH_IDX (killed ${RING_NUM_KILLS} times)." >&2
            echo "P:${RING_BATCH_IDX}:${RING_NUM_KILLS}" >&"${FD_TRAP_ACK_W}" 2>/dev/null
        else
            if [[ "$REPLY" != "0" ]]; then
                '
        ${insert_id_flag:-false} && worker_func_src+='((W_BATCH++))
                '
        worker_func_src+="${pCode}"'
            fi
        fi
        '"${ring_ack_str}"' || break
        
        # Reset variables natively in Bash so C does not have to allocate them
        RING_POISONED=0
        RING_NUM_KILLS=0
        REPLY=0
    done
  } {fd_read}<"/proc/self/fd/'"${ingress_memfd}"'" 1>&${fd1} 2>&${fd2}
) &
P[$3]=$!
W_NODE[$3]=$2
}'

        eval "${worker_func_src}"

        # --- SPAWN LOOP REACTOR ---
        nWorkers=0
        local -a node_workers W_NODE fd_worker_r fd_worker_w P wID_free
        
        local -A trap_ack_pending
        local _poll_timer_cmd=0
        local _timer_armed=false
        local _ret_val=0
        local -a POISONED_BATCHES=()

        for ((i=0; i<FORKRUN_NUM_NODES; i++)); do node_workers[i]=0; done
        node_worker_max=$(( nWorkersMax / FORKRUN_NUM_NODES ))
        (( node_worker_max < 1 )) && node_worker_max=1

        fd_spawn_arg="$fd_spawn_r"

        for (( nn=0; nn<($nWorkersMax+FORKRUN_NUM_NODES); nn++)); do
            wID_free[$nn]=''
        done

        while ring_poll "$fd_spawn_arg" fd_scan_death_r fd_worker_r "$_poll_timer_cmd" "$fd_trap_ack_r"; do
            _poll_timer_cmd=0

            case "$POLL_EVENT" in
                IGNORE) ;;
                TIMEOUT)
                    _timer_armed=false
                    if (( ${#trap_ack_pending[@]} > 0 )); then
                        echo "forkrun [FATAL]: Worker(s) [ ${!trap_ack_pending[@]} ] exited non-zero and EXIT trap did not confirm recovery within 3s grace period. Aborting." >&2
                        ring_abort
                        NORMAL_EXIT_FLAG=false
                        _ret_val=2
                    fi
                    ;;
                TRAP_ACK)
                    # NEW: Catch Poisoned Batch Signals
                    if [[ "$POLL_ARG1" == P:* ]]; then
                        local p_data="${POLL_ARG1#P:}"
                        POISONED_BATCHES+=("Index ${p_data%:*} (failed ${p_data##*:} times)")
                        continue
                    fi

                    wID=$POLL_ARG1
                    (( trap_ack_pending[$wID]-- ))
                    
                    # If it balanced out to 0 (DEATH arrived first), clean it up
                    if (( trap_ack_pending[$wID] == 0 )); then
                        unset 'trap_ack_pending[$wID]'
                    fi
                    
                    if (( ${#trap_ack_pending[@]} == 0 )); then
                        _poll_timer_cmd=-1 # Cancel timer cleanly
                        _timer_armed=false
                    fi
                    ;;
                SPAWN)
                    spawn_count=$POLL_ARG1
                    node_idx=$POLL_ARG2
                    
                    target=$(( node_workers[node_idx] + spawn_count ))
                    (( target > node_worker_max )) && target=$node_worker_max

                    for (( ; node_workers[node_idx] < target; node_workers[node_idx]++ )); do
                        for wID in "${!wID_free[@]}"; do break; done
                        unset 'wID_free[$wID]'
                        
                        ring_pipe fd_worker_r[$wID] fd_worker_w[$wID]
                        spawn_worker "$wID" "$node_idx" "$wID" "${fd_trap_ack_w}"
                        exec {fd_worker_w[$wID]}>&-
                        ((nWorkers++))
                    done
                    ;;
                WORKER_DEATH)
                    wID=$POLL_ARG1
                    wait "${P[$wID]}" 2>/dev/null
                    status=$?
                    
                    exec {fd_worker_r[$wID]}<&-
                    unset 'fd_worker_r[$wID]' 'fd_worker_w[$wID]' 'P[$wID]'
                    
                    node_idx=${W_NODE[$wID]:-0}
                    unset 'W_NODE[$wID]'
                    
                    (( node_workers[node_idx]-- ))
                    
                    if (( status != 0 )); then
                        (( trap_ack_pending[$wID]++ ))
                        
                        if (( trap_ack_pending[$wID] == 0 )); then
                            # TRAP_ACK already arrived! Clean up safely.
                            unset 'trap_ack_pending[$wID]'
                        elif (( trap_ack_pending[$wID] > 0 )); then
                            # Death arrived before TRAP_ACK. Arm the 3-second deadline.
                            if ! $_timer_armed; then
                                _poll_timer_cmd=3000
                                _timer_armed=true
                                echo "forkrun [WARN]: Worker $wID (node ${node_idx}) exited with status $status. Waiting up to 3s for EXIT trap confirmation." >&2
                            fi
                        fi
                        
                        # Unconditionally respawn replacement worker
                        ring_pipe fd_worker_r[$wID] fd_worker_w[$wID]
                        spawn_worker "$wID" "$node_idx" "$wID" "${fd_trap_ack_w}"
                        exec {fd_worker_w[$wID]}>&-
                        ((nWorkers++))
                        (( node_workers[node_idx]++ ))
                    else
                        wID_free[$wID]=''
                    fi
                    ;;
                SCAN_DEATH)
                    sID=$POLL_ARG1
                    wait "${SCANNER_P[$sID]}" 2>/dev/null
                    status=$?
                    
                    if (( status != 0 )); then
                        echo "forkrun [FATAL]: Scanner $sID exited with error status $status. Aborting to prevent data loss." >&2
                        ring_abort
                        NORMAL_EXIT_FLAG=false
                        _ret_val=1
                    fi
                    
                    exec {fd_scan_death_r[$sID]}<&-
                    unset 'fd_scan_death_r[$sID]' 'SCANNER_P[$sID]'
                    ;;
                EOF)
                    fd_spawn_arg="-1"
                    ;;
            esac
        done
        : "${NORMAL_EXIT_FLAG:=true}"

        ${verbose_flag} && printf '\nSPAWNED %s workers\n' "${nWorkers}" >&2

        # --- SHUTDOWN ---
        exec {fd_spawn_r}<&- {fd_fallow_w}>&- {fd_trap_ack_r}<&- {fd_trap_ack_w}>&-
        [[ "${order_mode}" == "realtime" ]] || exec {fd_order_w}>&-

        wait

        { ${stats_flag} || ${verbose_flag}; } && (( FORKRUN_NUM_NODES > 1 )) && ring_numa_stats

        if (( ${#POISONED_BATCHES[@]} > 0 )); then
            echo -e "\n=================================================================" >&2
            echo "forkrun [ERROR]: POISONED BATCH SUMMARY" >&2
            echo "=================================================================" >&2
            echo "The pipeline completed, but ${#POISONED_BATCHES[@]} batch(es) failed repeatedly" >&2
            echo "and were permanently skipped:" >&2
            for b in "${POISONED_BATCHES[@]}"; do
                echo "  - Batch $b" >&2
            done
            echo "=================================================================" >&2

            # If we were going to exit 0, change it to exit 3 to signal data loss
            (( _ret_val == 0 )) && _ret_val=3
        fi

        exec {fd_write}>&- {fd_scan}>&- {ingress_memfd}>&-

    } {fd_write}>"/proc/${BASHPID}/fd/${ingress_memfd}" {fd_scan}<"/proc/${BASHPID}/fd/${ingress_memfd}" {fd0}<&0 {fd1}>&1 {fd2}>&2
    return $_ret_val
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
          -E --retry-nonzero-exit +E --no-retry-nonzero-exit \
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
    local b b0 b1 k kk fd0 fd1 out0 out outC outN outF outB outFile nnSum nnSum_md5 nnSum_sha256 noVerifyFlag doneFlag IFS extglobState legacyFlag noCompressFlag
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

    if [[ "${1}" == '--force' ]]; then
        noVerifyFlag=true
        shift 1
    else
        noVerifyFlag=false
    fi

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
    read -r -d $'\035' -u "${fd0}" out
    if [[ -z ${out} ]]; then
        # first char of data section was $'\035' --> using standard base64(+gzip)
        legacyFlag=false
        read -r -d $'\036' -u "${fd0}" out
        if [[ -z ${out} ]]; then
            # second char of data section was $'\036' --> payload was gzip compressed
            read -r -d $'' -u "${fd0}" out
            noCompressFlag=false
        else
            noCompressFlag=true
        fi
    else
        legacyFlag=true
    fi

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
        {
            read -r outN outB
            read -r nnSum_md5
            read -r nnSum_sha256
            ${legacyFlag} && mapfile -t compressV

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
        ${legacyFlag} && (( ${#compressV[@]} > 0 )) && {
            compressI=('~' '`' '!' '#' '$' '%' '^' '&' '*' '(' ')' '-' '+' '=' '{' '[' '}' ']' ':' ';' '<' ',' '>' '.' '?' '/' '|')

            for (( kk=${#compressV[@]}-1; kk>=0; kk-- )); do
                out="${out//"${compressI[$kk]}"/"${compressV[$kk]}"}"
            done
        }
    fi

    if ${legacyFlag}; then

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

    elif ${noCompressFlag}; then
        # using standard base64, no compression
        base64 -d <<<"${out}" >&"${fd1}"

    else
        # using standard base64 + gzip compression
        base64 -d <<<"${out}" | gzip -d -c >&"${fd1}"
    fi

    exec {fd1}>&-

    # verify output file and make it executable
    if [[ ${outFile} ]] && [[ -f "${outFile}" ]]; then
        chmod +x "${outFile}"
        (( outB > 0 )) && type -p truncate &>/dev/null && truncate --size="${outB}" "${outFile}"
        ${noVerifyFlag} || [[ "${nnSum}" == '0' ]] || { nnSumF="$("${nnSum%%\:*}" "${outFile}")"; nnSumF="${nnSumF%% *}"; grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; ( read -r -u ${fd_sleep} -t 2 ) {fd_sleep}<><(:); \rm -f "${outFile}"; return 1; }; };
    elif ! { ${noVerifyFlag} || [[ "${nnSum}" == '0' ]] || ! ${legacyFlag}; }; then
        nnSumF="$("${nnSum%%\:*}" <(printf '%b' "${outF}"))"; nnSumF="${nnSumF%% *}"; grep -qF "${nnSum#*\:}" <<<"${nnSumF}" || { printf '\n\nWARNING FOR EXTRACTED LOADABLE:\n"%s"\n\nCHECKSUM DOES NOT MATCH EXPECTED VALUE!!!\nDO NOT CONTINUE UNLESS THIS WAS EXPECTED!!!\n\nEXPECTED: %s\nGOT: %s\n\nTHIS CODE WILL NOW REMOVE THE EXTRACTED .SO FILE AND ABORT\nTO FORCE KEEPING THE [POTENTIALLY CORRUPT] .SO FILE, RE-RUN THIS CODE WITH THE "--force" FLAG'  "${outFile:-\(STDOUT\)}" "${nnSum}" "${nnSumF}" >&2; ( read -r -u ${fd_sleep} -t 2 ) {fd_sleep}<><(:); \rm -f "${outFile}"; return 1; };
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
            "python"                     # Fileless fallback via python
            "perl"                       # Fileless fallback via perl
        )

        local py_script='import os,sys,time; fd=-1
try: fd=os.memfd_create("b",0)
except:
 try: import ctypes; fd=ctypes.CDLL(None).memfd_create(b"b",0)
 except: sys.exit(1)
sys.stdout.write(str(os.getpid())+" "+str(fd)+"\n"); sys.stdout.flush()
while True: time.sleep(60)'

        local pl_script='my $a=$ARGV[0]; my $s=($a=~/^x86_64/)?319:($a eq "aarch64"||$a eq "riscv64")?279:($a=~/^ppc64/)?360:($a eq "s390x")?356:0; exit 1 unless $s; my $fd=syscall($s,"b",0); exit 1 if $fd<0; print "$$ $fd\n"; $|=1; while(1){sleep 60;}'

        # try various places to make the tmp .so file to bootstrap
        for dir in "${candidates[@]}"; do
            local helper_fd="" helper_pid="" helper_out_fd=""
            
            if [[ "$dir" == "python" ]]; then
                if type -P python3 >/dev/null 2>&1; then
                    exec {helper_fd}< <(python3 -c "$py_script" 2>/dev/null)
                elif type -P python >/dev/null 2>&1; then
                    exec {helper_fd}< <(python -c "$py_script" 2>/dev/null)
                else
                    continue
                fi
                read helper_pid helper_out_fd <&$helper_fd
                if [[ -n "$helper_pid" && -n "$helper_out_fd" ]]; then
                    tmp_so="/proc/$helper_pid/fd/$helper_out_fd"
                else
                    [[ -n "$helper_fd" ]] && exec {helper_fd}<&-
                    continue
                fi
            elif [[ "$dir" == "perl" ]]; then
                if type -P perl >/dev/null 2>&1; then
                    exec {helper_fd}< <(perl -e "$pl_script" "$ARCH" 2>/dev/null)
                    read helper_pid helper_out_fd <&$helper_fd
                    if [[ -n "$helper_pid" && -n "$helper_out_fd" ]]; then
                        tmp_so="/proc/$helper_pid/fd/$helper_out_fd"
                    else
                        [[ -n "$helper_fd" ]] && exec {helper_fd}<&-
                        continue
                    fi
                else
                    continue
                fi
            else
                # Skip empty, non-existent, or non-writable directories
                { [[ $dir ]] && [[ -d "$dir" ]] && [[ -w "$dir" ]]; } || continue

                # Generate path with high entropy (30-bit random hex)
                printf -v tmp_so '%s/forkrun_boot_%s_%X%X.so' "$dir" "$BASHPID" "$RANDOM" "$RANDOM"
            fi

            # Try to extract loadable
            if truncate -s "${b64[$ARCH]%% *}" "${tmp_so}" 2>/dev/null && _forkrun_base64_to_file <<<"${b64[$ARCH]}" "$tmp_so" 2>/dev/null; then
                chmod +x "$tmp_so" 2>/dev/null

                # CRITICAL TEST: Try to Enable loadable
                # This verifies the filesystem allows execution (noexec check)
                if enable -f "$tmp_so" ring_memfd_create ring_seal ring_list ring_pipe 2>/dev/null; then
                    # SUCCESS! The builtin is loaded. 
                    need_memfd_create_flag=false
                fi
            fi

            # Clean up
            if [[ -n "$helper_pid" ]]; then
                kill "$helper_pid" 2>/dev/null
                [[ -n "$helper_fd" ]] && exec {helper_fd}<&-
            else
                \rm -f "$tmp_so" 2>/dev/null
            fi

            # break out of loop if we found someplace that works
            ${need_memfd_create_flag} || break
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

    local quoteFlag=false
    local noCompressFlag=false
    local legacyFlag=false

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
            -l|--legacy)
                legacyFlag=true
            ;;
            *) break ;;
        esac
    done

    [[ -f "${1}" ]] || {

        printf '\nERROR: "%s" not found. ABORTING.\n' "${1}" >&2
        return 1
    }

    ${legacyFlag} && {

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

    }

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
    if ${noCompressFlag} || ! ${legacyFlag}; then
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

    ${legacyFlag} || {
        # new method using standard base64 and gzip
        if ${noCompressFlag}; then
            out=$'\035'"$(base64 -w 0 <"${1}")"
        else
            out=$'\035'$'\036'"$(gzip -9 -c <"${1}" | base64 -w 0)"
        fi
    }

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

FORKRUN_FRUN_SRC="ulimit -n $(ulimit -Hn)"$'\n'
unset "b64"

# <@@@@@< _BASE64_START_ >@@@@@> #

declare -A b64=()   # removed base64

_forkrun_bootstrap_setup --force
