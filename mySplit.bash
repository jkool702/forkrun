#!/bin/bash

mySplit() {
## Splits up stdin into groups of ${1} lines using ${2} bash coprocs

    local tmpDir fPath nLines nProcs kk
    local -a A p_PID

    tmpDir=/tmp/"$(mktemp -d .forkrun.XXXXXXXXX)"
    fPath="${tmpDir}"/.stdin
    [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nLines="${1}" || nLines=128
    [[ "${2}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nProcs="${2}" || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')
    
    mkdir -p "${tmpDir}"
    touch "${fPath}"
    
    { coproc pWrite {
            cat  <&5 >&6 
            wc -l <"${fPath}" >"${tmpDir}"/.nLinesStdin
        } 5<&${fd_stdin} 6>&${fd_write}
    } {fd_write}>>"${fPath}" {fd_stdin}<&0

    exec {fd_continue}<><(:)
    
    trap 'exec {fd_continue}>&-' EXIT
    
    printf '1' >&${fd_continue}
    initFlag=true
    
    {
        for kk in $(seq 0 $(( ${nProcs} - 1 )) ); do
            source <(cat<<EOF
{ coproc p${kk} {
while true; do
    read -N 1 -u ${fd_continue}
    # [[ \$REPLY == 0 ]] && echo '0' >&${fd_continue} && break
    mapfile -t -n ${nLines} -u ${fd_read} A
    printf '1' >&${fd_continue}
    [[ \${#A[@]} == 0 ]] && { { \${initFlag}  && ! [[ -f "${tmpDir}"/.nLinesStdin ]]; } && continue || break; }
    \${initFlag} && initFlag=false
    printf '%s\\n' "\${A[@]}" >&${fd_stdout}
done
}
}
p_PID+=(\${p${kk}_PID})
EOF
)
        done
    } {fd_read}<"${fPath}" {fd_stdout}>&1
    
    wait ${p_PID[@]}
    
    rm -rf "${tmpDir}"

} 

# for kk in 1 2 4 8 16 32 64 128; do time {  echo "$a" | mySplit $kk 2>/dev/null; } >/dev/null; done
