#!/bin/bash

mySplit() {
    ## Splits up stdin into groups of ${1} lines using ${2} bash coprocs
    # input 1: number of lines to group at a time. Default is to automatically set nLines.
    # input 2: number of coprocs to use. Default is $(nproc)
            
    # make vars local
    local tmpDir fPath nLinesUpdateCmd outStr exitTrapStr nOrder coprocSrcCode inotifyFlag initFlag nLinesAutoFlag nOrderFlag rmDirFlag pipeReadFlag
    local -i nLines nLinesCur nLinesMax nProcs nDone kk
    local -a A p_PID 
  
    # setup tmpdir
    tmpDir=/tmp/"$(mktemp -d .mySplit.XXXXXX)"    
    fPath="${tmpDir}"/.stdin
    mkdir -p "${tmpDir}"
    touch "${fPath}"   
    
    (
    
        # check inputs and set defaults if needed
        [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nLines="${1}"; nLinesAutoFlag=false; } || { nLines=1; nLinesAutoFlag=true; }
        [[ "${2}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nProcs="${2}" || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')
            
        # if reading 1 line at as time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }


        # check for inotifywait
        type -p inotifywait 2>/dev/null 1>/dev/null && inotifyFlag=true
        
        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmDirFlag:=true}" "${nLinesMax:=512}" "${pipeReadFlag:=false}" "${inotifyFlag:=false}"
            
        ${pipeReadFlag} && ${nLinesAutoFlag} && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supoported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }
    
        ${rmDirFlag} || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}
        
        # spawn a coproc to write stdin to a tmpfile
        # After we are done reading all of stdin print total line count to a file 
        if ${pipeReadFlag}; then
            touch "${tmpDir}"/.done
        else
            coproc pWrite {
                cat <&${fd_stdin} >&${fd_write} 
                wc -l <"${fPath}" >"${tmpDir}"/.done
                ${inotifyFlag} && printf '\n' >&${fd_inotify}
            }
        fi
        
                       
        # setup inotify (if available) + set exit trap 
        exitTrapStr=''
        if ${inotifyFlag}; then
        
            # add 1 newline for each coproc to fd_inotify
            source <(printf 'printf '"'"'%%.0s\\n'"'"' {1..%s} ' ${nProcs} >&${fd_inotify})
            
            #{ coproc pNotify {
           
            inotifywait -q -m -e modify,close --format '' "${fPath}" >&${fd_inotify} &
            
            #   }
            #}
            #trap 'kill -9 '"${pNotify_PID}"' && rm -rf '"${tmpDir}"' || :' EXIT
            #trap 'kill '"${!}"' && rm -rf '"${tmpDir}"';' EXIT
            exitTrapStr+='kill '"${!}"'; '
        fi

        ${rmDirFlag} && exitTrapStr+='rm -rf '"${tmpDir}"'; '
        
        trap "${exitTrapStr}" EXIT

    
        # setup nLinesAuto
        if ${nLinesAutoFlag}; then
        
            # set nLines indicator
            echo ${nLines} >"${tmpDir}"/.nLines

            source <(source <(printf 'echo '"'"'echo 0 >'"${tmpDir}"'/.n'"'"'{0..%s}\; ' $(( $nProcs-1 ))))
            nDone=0
            
            { coproc pAuto {
                    trap - EXIT
                    #nLinesUpdateCmd="$(printf "echo "; source <(echo 'echo '"'"'$(( 1 + ( $(wc -l <"'"'"'"${fPath}"'"'"'") - $(<"'"'"'"${tmpDir}"'"'"'"/.n0'"'"' '"'"') - $(<"'"'"'"${tmpDir}"'"'"'"/.n'"'"'{1..'"$(( ${nProcs} - 1 ))"}' '"'"') ) / '"${nProcs}"' ))'"'"))"
#source <(cat<<EOF
nLinesUpdate() {
    local -i nLinesNew rVal
    rVal=0
    [[ -f "${tmpDir}"/.done ]] && ((rVal++))
    nLinesNew=$(( 1 + ( $(wc -l <"${fPath}") / ${nProcs} ) ))
    (( ${nLinesNew} >= ${nLinesMax} )) && { nLinesNew=${nLinesMax}; ((rVal++)); }
    (( ${nLinesNew} > $(<"${tmpDir}"/.nLines) )) && printf '%s\n' ${nLinesNew} >"${tmpDir}"/.nLines && printf 'Changing nLines to %s\n' "${nLinesNew}" >&${fd_stderr} 
    return ${rVal}
}
#EOF
#)
            
                    while read -u ${fd_nLinesAuto}; do
                        [[ ${REPLY} == 0 ]] && break
                        nLinesUpdate || break
                    done
                } 
            } 2>/dev/null
        else
            nLinesCur=${nLines}
        fi
        
        # setup (ordered) output
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'
                        
            { coproc pOrder ( 
                trap - EXIT
                
                local -i v0 v9
                
                printf '%s\n' {00..89} >&${fd_nOrder}
                
                while true; do
                    v9="${v9}9"
                    v0="${v0}0"
                    
                    source <(printf '%s\n' 'printf '"'"'%s\n'"'"' {'"${v9}"'00'"${v0}"'..'"${v9}"'89'"${v9}"'} >&'"${fd_nOrder}")
                done
            )
            } 2>/dev/null
        else 
            
            outStr='>&'"${fd_stdout}"; 
        fi

        # populate {fd_continue} with an initial '1' 
        # {fd_continue} will act as an exclusive read lock - when there is a '1' buffered in the pipe then nothinghas an read lock: 
        # a process reads 1 byte from {fd_continue} to get the read lock, and that process writes a '1' back to the pipe to release the read lock
        printf '\n' >&${fd_continue}; 

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
        coprocSrcCode="$(cat<<EOF0
{ coproc p%s {
trap - EXIT
while true; do
    read -u ${fd_continue} 
$(${nLinesAutoFlag} && cat<<EOF1
    nLinesCur=\$(<"${tmpDir}"/.nLines)
EOF1
)
    mapfile -t -n \${nLinesCur} -u $(${pipeReadFlag} && printf '%s' ${fd_stdin} || printf '%s' ${fd_read}) A
$(${nOrderFlag} && cat<<EOF2
    read -u ${fd_nOrder} nOrder
EOF2
)
    printf '\\\\n' >&${fd_continue}; 
    [[ \${#A[@]} == 0 ]] && { 
        
        if [[ -f "${tmpDir}"/.done ]]; then
            [[ -f "${tmpDir}"/.quit ]] && break
$(${inotifyFlag} && cat<<EOF3
                printf '%%.0s\\\\n' {0..${nProcs}} >&${fd_inotify}
EOF3
)
            \${initFlag} && initFlag=false || { touch "${tmpDir}"/.quit; break; }
$(${inotifyFlag} && cat<<EOF4
        else        
            read -u ${fd_inotify}
EOF4
)
        fi
        continue
    }
    
    printf '%%s\\\\n' "\${A[@]}" ${outStr}
    sed -i "1,\${#A[@]}d" "${fPath}"

$(${nLinesAutoFlag} && cat<<EOF5
    \${nLinesAutoFlag} && { 
        [[ \${nLinesCur} == ${nLinesMax} ]] && { nLinesAutoFlag=false; printf '0\\n' >&${fd_nLinesAuto}; } || {
            nDone+=\${#A[@]}
            printf '%%s\\\\n' \${nDone} >"${tmpDir}"/.n%s
            printf '\\\\n' >&${fd_nLinesAuto}
        }
    }
EOF5
)
done
} 2>&${fd_stderr}
} 2>/dev/null
p_PID+=(\${p%s_PID})
EOF0
)"

        #coprocSrcCode_kk=$(echo "${coprocSrcCode}" | grep -oE '[^%]%s' | wc -l)
        
        for kk in $( source <(printf '%s\n' 'printf '"'"'%s '"'"' {0..'"$(( ${nProcs} - 1 ))"'}') ); do
            [[ -f "${tmpDir}"/.quit ]] && break
            #source <(printf "${coprocSrcCode}" $(source <(printf 'printf "${kk}%%.0s " {1..'"${coprocSrcCode_kk}"'}')))
            source <(printf "${coprocSrcCode}" ${kk} ${kk} $(${nLinesAutoFlag} && printf '%s' ${kk}))
        done
       
        # wait for everything to finish
        # in forkrun the main process will probably manage automaticly changing nLines
        wait "${p_PID[@]}"
        
        # print output if using ordered output
        ${nOrderFlag} && kill ${pOrder_PID} && IFS=$'\n' cat "${tmpDir}"/.out/x*
        
    # open anonympous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_inotify}<><(:) {fd_nLinesAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>>"${fPath}" {fd_stdin}<&0 {fd_stdout}>&1 {fd_stderr}>&2
    
   return 0

} 
