#!/bin/bash

mySplit() {
    ## Splits up stdin into groups of ${1} lines using ${2} bash coprocs
    # input 1: number of lines to group at a time. Default is to automatically set nLines.
    # input 2: number of coprocs to use. Default is $(nproc)
    
    #set -xv
        
    # make vars local
    local tmpDir fPath nLinesUpdateCmd outStr exitTrapStr nOrder inotifyFlag initFlag nLinesAutoFlag nOrderFlag rmDirFlag
    local -i nLines nLinesCur nLinesMax nProcs nDone kk
    local -a A p_PID
  
    # setup tmpdir
    tmpDir=/tmp/"$(mktemp -d .mySplit.XXXXXX)"    
    fPath="${tmpDir}"/.stdin
    mkdir -p "${tmpDir}"
    touch "${fPath}"    
    
    # check inputs and set defaults if needed
    [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nLines="${1}"; nLinesAutoFlag=false; } || { nLines=1; nLinesAutoFlag=true; }
    [[ "${2}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && nProcs="${2}" || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')
        
    # set nLines indicator
    echo ${nLines} >"${tmpDir}"/.nLines

    # check for inotifywait
    type -p inotifywait 2>/dev/null 1>/dev/null && inotifyFlag=true || inotifyFlag=false
    
    # set defaults for control flags/parameters
    : "${nOrderFlag:=true}" "${rmDirFlag:=true}" "${nLinesMax:=512}"
    
    (
    
        ${rmDirFlag} || printf '\ntmpDir: %s\n\n' "${tmpDir}" >&${fd_stderr}
        
            # spawn a coproc to write stdin to a tmpfile
        # After we are done reading all of stdin print total line count to a file (for future use)
        { coproc pWrite {
                cat  <&5 >&6
                wc -l <"${fPath}" >"${tmpDir}"/.done
                ${inotifyFlag} && printf '\n' >&${fd_inotify}
            }
        } 5<&${fd_stdin} 6>&${fd_write} 
        
                       
        # setup inotify (if available) + set exit trap 
        exitTrapStr=''
        if ${inotifyFlag}; then
        
            # add 1 newline for each coproc to fd_inotify
            source <(printf 'printf '"'"'%%.0s\\n'"'"' {0..%s} ' $(( $nProcs-1 ))) >&${fd_inotify}
            
            #{ coproc pNotify {
           
            inotifywait -m -e modify,close --format '' "${fPath}" 2>/dev/null >&${fd_inotify} &
            
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

            source <(source <(printf 'echo '"'"'echo 0 >'"${tmpDir}"'/.n'"'"'{0..%s}\; ' $(( $nProcs-1 ))))
            nDone=0
            
            { coproc pAuto {
                    nLinesUpdateCmd="$(printf "echo "; source <(echo 'echo '"'"'$(( 1 + ( $(wc -l <"'"'"'"${fPath}"'"'"'") - $(<"'"'"'"${tmpDir}"'"'"'"/.n0'"'"' '"'"') - $(<"'"'"'"${tmpDir}"'"'"'"/.n'"'"'{1..'"$(( ${nProcs} - 1 ))"}' '"'"') ) / '"${nProcs}"' ))'"'"))"
                    source <(cat<<EOF
nLinesUpdate() {
    local nLinesNew
    nLinesNew=\$(${nLinesUpdateCmd})
    (( \${nLinesNew} > ${nLinesMax} )) && nLinesNew=${nLinesMax}
    (( \${nLinesNew} > \$(<"${tmpDir}"/.nLines) )) && echo \${nLinesNew} >"${tmpDir}"/.nLines && printf 'Changing nLines to %s\\n' "\${nLinesNew}" >&${fd_stderr} 
    [[ \${nLinesNew} == ${nLinesMax} ]] && return 0 || return 1
}
EOF
                    )
            
                    while read -u ${fd_nLinesAuto}; do
                        [[ ${REPLY} == 0 ]] && break
                        nLinesUpdate || break
                        [[ -f "${tmpDir}"/.done ]] && break
                    done
                } 
            }
            
        fi

        # populate {fd_+continue} with an initial '1' 
        # {fd_continue} will act as an exclusive read lock - when there is a '1' buffered in the pipe then nothinghas an read lock: 
        # a process reads 1 byte from {fd_continue} to get the read lock, and that process writes a '1' back to the pipe to release the read lock
    
        # dont exit read loop during init 
        initFlag=true
        
        # initialize fd_continue
        ${nOrderFlag} && { 
        
getNextIndex() {
    ## get the name of the next indexed output number to used
    # input is current index number.

    local x
    local x_prefix
    
    [[ "${1}" == '0' ]] && echo '00' && return 0

    x_prefix=''
    [[ ${1:${#x_prefix}:1} == 0 ]] && x_prefix+='0'
    
    x="${1:${#x_prefix}}"
    
    [[ "$x" == '9' ]] && x_prefix="${x_prefix:0:-1}"

    if [[ "${x}" =~ ^9*89+$ ]]; then
        ((x++))
        x+='00'
    else
        ((x++))
    fi

    printf '%s%s' "${x_prefix}" "${x}"
}

# declare -f getNextIndex >&${fd_stderr}

        
            mkdir -p "${tmpDir}"/.out; 
            printf '%s\n' '0' >&${fd_nOrder}; 
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'; 
            

        } || { 
            
            outStr='>&'"${fd_stdout}"; 
        }
    
        printf '\n' >&${fd_continue}; 
        
        # spawn $nProcs coprocs
        # on each loop, they will read {fd_continue}, which blocks them until they have exclusive read access
        # they then read N lines with mapfile and send 1 top {fd_continue} (so the next coproc can start to read)
        # if the read array is empty the coproc will either continue or break, depending on if end conditions are met
        # finally it will do something with the data. Currently this is a dummy printf call (for testing). 
        #
        # NOTE: by putting the read fd in a brace group surrounding all the coprocs, they will all use the same file descriptor
        # this means that whenever a coproc reads data it will start reading at the point the last coproc stopped reading at
        # This basically means that all you need to do is make sure 2 processes dont read at the same time.
        for kk in $(seq 0 $(( ${nProcs} - 1 )) ); do
            source <(cat<<EOF0
{ coproc p${kk} {
while true; do
    read -u ${fd_continue} 
    nLinesCur=\$(<"${tmpDir}"/.nLines)
    mapfile -t -n \${nLinesCur} -u ${fd_read} A
    $(${nOrderFlag} && cat<<EOF1
read -u ${fd_nOrder} nOrder
nOrder=\$(getNextIndex \${nOrder})
printf '%s\n' \${nOrder} >&${fd_nOrder}
EOF1
    )
    printf '\\n' >&${fd_continue}; 
    [[ \${A} ]] || { 
        
        [[ -f "${tmpDir}"/.done ]] && { \${initFlag} && initFlag=false || { printf '\\n' >&${fd_inotify}; break; }; }
        $(${inotifyFlag} && cat<<EOF2
read -u ${fd_inotify}
EOF2
        )
        continue
    }
    
    printf '%s\\n' "\${A[@]}" ${outStr}

    \${nLinesAutoFlag} && { 
        [[ \${nLinesCur} == ${nLinesMax} ]] && { nLinesAutoFlag=false; printf '0\\n' >&${fd_nLinesAuto}; } || {
            nDone+=\${#A[@]}
            echo \${nDone} >"${tmpDir}"/.n${kk}
            printf '\\n' >&${fd_nLinesAuto}
        }
    }
done
    }
}
p_PID+=(\${p${kk}_PID})
EOF0
)
        done
       
        # wait for everything to finish
        # in forkrun the main process will probably manage automaticly changing nLines
        wait "${p_PID[@]}"
        
        # print output if using ordered output
        ${nOrderFlag} && IFS=$'\n' cat "${tmpDir}"/.out/x*
        
    # open anonympous pipes + other misc file descriptors for the above code block
    ) {fd_continue}<><(:) {fd_inotify}<><(:) {fd_nLinesAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>>"${fPath}" {fd_stdin}<&0 {fd_stdout}>&1 {fd_stderr}>&2

  
   
   return 0
    
    # cleanup
    #kill "${pNotify_PID}"
    #rm -rf "${tmpDir}"

    # exit 0


# # # SPEED IMPROVEMENTS vs old IPC schemes
#
# nLines = 1:  ~2-3x as fast as read-byte-by-byte-from-pipe approach. 
#              Similiar speed to save-stdin-to-tmpfile-and-read-one-line-at-a-time approach.
#
# nLines > 1:  in high nLine limit (>500) speeds are similiar to split+cat approach. 
#              for intermediate nLines (10-100) speeds are 5-10x faster than split+cat approach
#              in low nLines limit (2) speeds are 20-30x faster than split+cat approach



# a="$(printf '%.0s'"$(echo $(dd if=/dev/urandom bs=4096 count=1 | hexdump) | sed -E s/'^(.{4096}).*$'/'\1'/)"'\n' {1..1000})"
# for kk in 1 2 4 8 16 32 64 128; do time {  echo "$a" | mySplit $kk 2>/dev/null; } >/dev/null; done

} 
