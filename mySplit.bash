#!/usr/bin/env bash

mySplit() {
    ## Splits up stdin into groups of ${1} lines using ${2} bash coprocs
    # input 1: number of lines to group at a time. Default is to automatically dynamically set nLines.
    # input 2: number of coprocs to use. Default is $(nproc)
    # 
    # DEPENDENCIES: Bash 4+ (5.2+ required for optimal speed)
    #      cat, grep, sed, wc (GNU or busybox versions will work...both are supported)
            
    # make vars local
    local tmpDir fPath nLinesUpdateCmd outStr exitTrapStr exitTrapStr_kill nOrder coprocSrcCode inotifyFlag initFlag stopFlag nLinesAutoFlag nOrderFlag rmDirFlag pipeReadFlag fd_continue fd_inotify fd_nLinesAuto fd_nOrder fd_wait fd_read fd_write fd_stdout fd_stdin fd_stderr pWrite_PID pNotify_PID pOrder_PID pAuto_PID 
    local -i nLines nLinesCur nLinesNew nLinesMax nProcs kk
    local -a A p_PID runCmd
  
    # setup tmpdir
    tmpDir=/tmp/"$(mktemp -d .mySplit.XXXXXX)"    
    fPath="${tmpDir}"/.stdin
    mkdir -p "${tmpDir}"
    touch "${fPath}"   
    
    (
    
        # check inputs and set defaults if needed
        [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nLines="${1}"; : "${nLinesAutoFlag:=false}"; shift 1; } || { nLines=1; nLinesAutoFlag=true; }
        [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nProcs="${1}"; shift 1; } || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')
            
        runCmd=("${@}")
        [[ ${#runCmd[@]} == 0 ]] && runCmd=(printf '%s\n')
        runCmd=("${runCmd[@]//'%'/'%%'}")
        runCmd=("${runCmd[@]//'\'/'\\\\'}")
        
        # if reading 1 line at as time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # check for inotifywait
        type -p inotifywait &>/dev/null && inotifyFlag=true || inotifyFlag=false
        
        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmDirFlag:=true}" "${nLinesMax:=512}" "${pipeReadFlag:=false}"
            
        # cherck for a conflict that could occur is flags are defined on commandline when mySplit is called
        ${pipeReadFlag} && ${nLinesAutoFlag} && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supoported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }
    
        # if keeping tmpDir print its location to stderr
        ${rmDirFlag} || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}
        
        exitTrapStr=''
        exitTrapStr_kill=''
        
        # spawn a coproc to write stdin to a tmpfile
        # After we are done reading all of stdin incidate this by touching .done
        if ${pipeReadFlag}; then
            touch "${tmpDir}"/.done
        else
            coproc pWrite {
                trap - EXIT
                cat <&${fd_stdin} >&${fd_write} 
                touch "${tmpDir}"/.done
                ${inotifyFlag} && {
                    (
                        { source /proc/self/fd/0 >&${fd_inotify0}; }<<<"printf '%.0s\n' {0..${nProcs}}"
                    ) {fd_inotify0}>&${fd_inotify}
                }
            }
            exitTrapStr_kill+="${!} "
        fi      
                       
        # setup inotify (if available) + set exit trap 
        if ${inotifyFlag}; then
        
            # add 1 newline for each coproc to fd_inotify
            { source /proc/self/fd/0 >&${fd_inotify}; }<<<"printf '%.0s\n' {0..${nProcs}}"
           
            {
                inotifywait -q -m --format '' "${fPath}" >&${fd_inotify} &
            } 2>/dev/null
            
            pNotify_PID=$!

            exitTrapStr+='[[ -f "'"${fPath}"'" ]] && rm -f "'"${fPath}"'"; '
            exitTrapStr_kill+="${pNotify_PID} "
        fi
        
        # setup (ordered) output
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'
                                    
            { coproc pOrder ( 
                trap - EXIT
                
                local -i v0 v9
                
                printf '%s\n' {00..89} >&${fd_nOrder}
                
                while ! [[ -f "${tmpDir}"/.quit ]]; do
                    v9="${v9}9"
                    v0="${v0}0"
                    
                    { source /proc/self/fd/0 >&${fd_nOrder}; }<<<"printf '%s\n' {${v9}00${v0}..${v9}89${v9}}"
                done
            )
            } 2>/dev/null
            
            exitTrapStr_kill+="${pOrder_PID} "

        else 
            
            outStr='>&'"\${fd_stdout}"; 
        fi
        
        # setup nLinesAuto
        nLinesCur=${nLines}
        if ${nLinesAutoFlag}; then
        
            # set nLines indicator
            echo ${nLines} >"${tmpDir}"/.nLines

            #source <(source <(printf 'echo '"'"'echo 0 >'"${tmpDir}"'/.n'"'"'{0..%s}\; ' $(( $nProcs-1 ))))
                      
            # LOGIC FOR DYNAMICALLY SETTING 'nLines': 
            # the new "proposed" 'nLines' is the smaller of 'nLinesMax' and $(( 1 + <num lines currently in .stdin file> / <num coproc workers> ))
            # if proposed new 'nLines' is greater than current 'nLines' then use it (use case: stdin is arriving fairly fast, increase 'nLines to match the rate lines are comming in on stdin)
            # if proposed new 'nLines' is ;ess than or equal to current 'nLines':
            #   -->  if nLines has never increased it then dont increase it (use case: stdin is arriving slowly)
            #   -->  if nLines has previously increased, new 'nLines' is $(( 1 + 1.1 * <current 'nLines'> )) (use case: stdin is arriving so fast that wc -l cant keep up --> continue to slowly increase it)
            # if the new 'nLines' is equal to 'nLinesMax' or .quit file has appeared then break
            { coproc pAuto {
                    trap - EXIT
                    stopFlag=false
                    while true; do
                    
                        read -u ${fd_nLinesAuto}
                        { [[ ${REPLY} == 0 ]] || [[ -f "${tmpDir}"/.quit ]]; } && stopFlag=true  
                        [[ -f "${fPath}" ]] || break
                        
                        nLinesNew=$(( 1 + ( $(wc -l <"${fPath}") / ${nProcs} ) ))
                        
                        (( ${nLinesNew} <= ${nLinesCur} )) && (( ${nLinesCur} > ${nLines} )) && nLinesNew=$(( ( ( 11 * ${nLinesCur} ) / 10 ) + 1 ))
                                                
                        (( ${nLinesNew} >= ${nLinesMax} )) && { nLinesNew=${nLinesMax}; stopFlag=true; }

                        (( ${nLinesNew} > ${nLinesCur} )) && {
                            printf '%s\n' ${nLinesNew} >"${tmpDir}"/.nLines 
                            nLinesCur=${nLinesNew}
                        }
                        
                        ${stopFlag} && break
                    done
                } 
            } 2>/dev/null

            exitTrapStr+='printf '"'"'%s\n'"'"' 0 >&'"${fd_nLinesAuto}"'; '
            exitTrapStr_kill+="${pAuto_PID} "
            
            printf '\n' >&${fd_nLinesAuto}
            
        fi
        
        # set EXIT trap (dynamically determined based on which option nflags were active)
        exitTrapStr="${exitTrapStr}"'kill '"${exitTrapStr_kill}"' 2>/dev/null'
        ${rmDirFlag} && exitTrapStr+='; [[ -d $"'"${tmpDir}"'" ]] && rm -rf "'"${tmpDir}"'"'
        trap "${exitTrapStr}" EXIT        
        

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
        # This basically means that all you need to do is make sure 2 processes dont read at the same time and deal with stopping condiutions.

        # generate coproc source code template
        # this contains the code for the coprocs but has the worker ID ($kk) replaced with '%s' and '%' replaced with '%%'
        # the individual coproc's codes are then generated via printf ${coprocSrcCode} $kk $kk and sourced
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
$(${nLinesAutoFlag} && cat<<EOF3
                printf '0\\\\n' >&${fd_nLinesAuto}
EOF3
)
            \${initFlag} && initFlag=false || { touch "${tmpDir}"/.quit; break; }
$(${inotifyFlag} && cat<<EOF4
        else        
            read -u ${fd_inotify} -t 1
EOF4
)
        fi
        continue
    }
    
    ${runCmd[@]} "\${A[@]}" ${outStr}
    sed -i "1,\${#A[@]}d" "${fPath}"

$(${nLinesAutoFlag} && cat<<EOF5
    \${nLinesAutoFlag} && {
        printf '\\\\n' >&${fd_nLinesAuto}
        [[ \${nLinesCur} == ${nLinesMax} ]] && nLinesAutoFlag=false
    }
EOF5
)
done
} 2>&${fd_stderr}
} 2>/dev/null
p_PID+=(\${p%s_PID})
EOF0
)"
        
        # source the coproc code for each coproc worker
        for kk in $( { source /proc/self/fd/0; } <<<"printf '%s ' {0..$(( ${nProcs} - 1 ))}" ); do
            [[ -f "${tmpDir}"/.quit ]] && break
            source <(printf "${coprocSrcCode}" ${kk} ${kk})
        done
       
        # wait for everything to finish
        wait ${p_PID[@]}
               
        # print output if using ordered output
        ${nOrderFlag} && IFS=$'\n' cat "${tmpDir}"/.out/x*

        # print final nLines count
        #${nLinesAutoFlag} && printf 'nLines (final) = %s   (max = %s)\n'  $(<"${tmpDir}"/.nLines) ${nLinesMax} >&${fd_stderr}
 
    # open anonympous pipes + other misc file descriptors for the above code block   
    ) {fd_continue}<><(:) {fd_inotify}<><(:) {fd_nLinesAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>>"${fPath}" {fd_stdout}>&1 {fd_stdin}<&0 {fd_stderr}>&2

}
