#!/bin/bash

mySplit() {
    ## Splits up stdin into groups of ${1} lines using ${2} bash coprocs
    # input 1: number of lines to group at a time. Default is 32
    # input 2: number of coprocs to use. Default is $(nproc)
    
    # make vars local
    local tmpDir fPath nLines nProcs kk
    local -a A p_PID

    # setup tmpdir
    tmpDir=/tmp/"$(mktemp -d .forkrun.XXXXXXXXX)"    
    fPath="${tmpDir}"/.stdin
    mkdir -p "${tmpDir}"
    touch "${fPath}"    
    
    # check inputs and set defaults if needed
    [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nLines="${1}" || nLines=128
    [[ "${2}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nProcs="${2}" || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')
    
    # spawn a coproc to write stdin to a tmpfile
    # After we are done reading all of stdin print total line count to a file (for future use)
    { coproc pWrite {
            cat  <&5 >&6 
            wc -l <"${fPath}" >"${tmpDir}"/.nLines
        } 5<&${fd_stdin} 6>&${fd_write}
    } {fd_write}>>"${fPath}" {fd_stdin}<&0


    # open anonympous pipe + populate with initial '1' + set exit trap to close it
    # this will act as an exclusive read lock - when there is a '1' buffered in the pipe then nothinghas an read lock, 
    # a process reads 1 byte from {fd_continue} to get the read lock, and that process writes a '1' back to the pipe to release the read lock
    exec {fd_continue}<><(:)
    trap 'exec {fd_continue}>&-' EXIT
    printf '1' >&${fd_continue}
    
    # dont exit read loop during init 
    initFlag=true
    
    # spawn $nProcs coprocs
    # on each loop, they will read {fd_continue}, which blocks them until they have exclusive read access
    # they then read N lines with mapfile and send 1 top {fd_continue} (so the next coproc can start to read)
    # if the read array is empty the coproc will either continue or break, depending on if end conditions are met
    # finally it will do something with the data. Currently this is a dummy printf call (for testing). 
    #
    # NOTE: by putting the read fd in a brace group surrounding all the coprocs, they will all use the same file descriptor
    # this means that whenever a coproc reads data it will start reading at the point the last coproc stopped reading at
    # This basically means that all you need to do is make sure 2 processes dont read at the same time.
    {
        for kk in $(seq 0 $(( ${nProcs} - 1 )) ); do
            source <(cat<<EOF
{ coproc p${kk} {
while true; do
    read -N 1 -u ${fd_continue}
    # [[ \$REPLY == 0 ]] && echo '0' >&${fd_continue} && break
    mapfile -t -n ${nLines} -u ${fd_read} A
    printf '1' >&${fd_continue}
    [[ \${#A[@]} == 0 ]] && { { \${initFlag} && ! [[ -f "${tmpDir}"/.nLines ]]; } && continue || break; }
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
        
    # wait for everything to finish
    # in forkrun the main process will probably manage automaticly changing nLines
    wait ${p_PID[@]}
    
    # cleanup
    rm -rf "${tmpDir}"

} 

# # # SPEED IMPROVEMENTS vs old IPC schemes
#
# nLines = 1:  ~2-3x as fast as read-byte-by-byte-from-pipe approach. 
#              Similiar speed to save-stdin-to-tmpfile-and-read-one-line-at-a-time approach.
#
# nLines > 1:  in high nLine limit (>500) speeds are similiar to split+cat approach. 
#              for intermediate nLines (10-100) speeds are 5-10x faster than split+cat approach
#              in low nLines limit (2) speeds are 20-30x faster than split+cat approach




# for kk in 1 2 4 8 16 32 64 128; do time {  echo "$a" | mySplit $kk 2>/dev/null; } >/dev/null; done

