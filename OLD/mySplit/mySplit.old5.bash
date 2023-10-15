#!/usr/bin/env bash

mySplit() (
    ## Splits up stdin into groups of ${1} lines using ${2} bash coprocs
    # input 1: number of lines to group at a time. Default is to automatically dynamically set nLines.
    # input 2: number of coprocs to use. Default is $(nproc)
    # 
    # DEPENDENCIES: Bash 4+ (5.2+ required for optimal speed)
    #      `cat` --AND-- `sed -i`
    #      optional: `grep -cE` --OR-- `nproc` (required to automatically set nProcs as # logical cpu cores. without one of these either it must be set manually or it gets set to "4" by default)
    # for the above external dependencies either the GNU or the busybox versions will work
        
    trap - EXIT INT TERM HUP QUIT
            
    # make vars local
    local tmpDir fPath outStr exitTrapStr exitTrapStr_kill nOrder coprocSrcCode inotifyFlag fallocateFlag nLinesAutoFlag nOrderFlag rmDirFlag pipeReadFlag fd_continue fd_inotify fd_nAuto fd_nOrder fd_wait fd_read fd_write fd_stdout fd_stdin fd_stderr pWrite_PID pNotify_PID pOrder_PID pAuto_PID fd_read_pos fd_read_pos_old fd_write_pos partialLine
    local -i nLines nLinesCur nLinesNew nLinesMax nRead nProcs nWait v9 kkMax kkCur kk
    local -a A p_PID runCmd 
  
    # setup tmpdir
    { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && tmpDir="${TMPDIR}$(mktemp -d .mySplit.XXXXXX)"; } ||[[ -d /dev/shm ]] && tmpDir=/dev/shm/"$(mktemp -d .mySplit.XXXXXX)"  || tmpDir=/tmp/"$(mktemp -d .mySplit.XXXXXX)"    
    fPath="${tmpDir}"/.stdin
    mkdir -p "${tmpDir}"
    touch "${fPath}"   
    
    {
        # check inputs and set defaults if needed
        [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nLines="${1}"; : "${nLinesAutoFlag:=false}"; shift 1; } || { nLines=1; : "${nLinesAutoFlag=true}"; }
        [[ "${1}" =~ ^[0-9]*[1-9]+[0-9]*$ ]] && { nProcs="${1}"; shift 1; } || nProcs=$({ type -a nproc 2>/dev/null 1>/dev/null && nproc; } || grep -cE '^processor.*: ' /proc/cpuinfo || printf '4')

        # determine what mySplit is using lines on stdin for
        runCmd=("${@}")
        [[ ${#runCmd[@]} == 0 ]] && runCmd=(printf '%s\n')
        runCmd=("${runCmd[@]//'%'/'%%'}")
        runCmd=("${runCmd[@]//'\'/'\\'}")

        # if reading 1 line at a time (and not automatically adjusting it) skip saving the data in a tmpfile and read directly from stdin pipe
        ${nLinesAutoFlag} || { [[ ${nLines} == 1 ]] && : "${pipeReadFlag:=true}"; }

        # check for inotifywait
        type -p inotifywait &>/dev/null && : "${inotifyFlag=true}" || : "${inotifyFlag=false}"
        
        # check for fallocate
        type -p fallocate &>/dev/null && : "${fallocateFlag=true}" || : "${fallocateFlag=false}"
        
        # set defaults for control flags/parameters
        : "${nOrderFlag:=false}" "${rmDirFlag:=true}" "${nLinesMax:=512}" "${pipeReadFlag:=false}"
            
        # cherck for a conflict that could occur is flags are defined on commandline when mySplit is called
        ${pipeReadFlag} && ${nLinesAutoFlag} && { printf '%s\n' '' 'WARNING: automatically adjusting number of lines used per function call not supported when reading directly from stdin pipe' '         Disabling reading directly from stdin pipe...a tmpfile will be used' '' >&${fd_stderr}; pipeReadFlag=false; }
    
        # if keeping tmpDir print its location to stderr
        ${rmDirFlag} || printf '\ntmpDir path: %s\n\n' "${tmpDir}" >&${fd_stderr}

        # start building exit trap string
        exitTrapStr=''
        exitTrapStr_kill=''
        
        # spawn a coproc to write stdin to a tmpfile
        # After we are done reading all of stdin indicate this by touching .done
        if ${pipeReadFlag}; then
            touch "${tmpDir}"/.done
        else
            coproc pWrite {
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
        
        # setup (ordered) output. This uses the same naming scheme as `split -d` to ensure a simple `cat /path/*` always orders things correctly.
        if ${nOrderFlag}; then

            mkdir -p "${tmpDir}"/.out
            outStr='>"'"${tmpDir}"'"/.out/x${nOrder}'
                                    
            { coproc pOrder ( 
        
                # generate enough nOrder indices (~10000) to fill up 64 kb pipe buffer
                printf '%s\n' {00..89} {9000..9899} {9900000..9998999} >&${fd_nOrder}

                # now that pipe buffer is full, add additional indices 1000 at a time (as needed)
                v9='99'
                kkMax='8'
                while ! [[ -f "${tmpDir}"/.quit ]]; do
                    v9="${v9}9"
                    kkMax="${kkMax}9"

                    for (( kk=0 ; kk<=kkMax ; kk++ )); do
                        kkCur="$(printf '%0.'"${#kkMax}"'d' "$kk")"                    
                        { source /proc/self/fd/0 >&${fd_nOrder}; }<<<"printf '%s\n' {${v9}${kkCur}000..${v9}${kkCur}999}"
                    done
                done
              )
            } 2>/dev/null
            
            exitTrapStr_kill+="${pOrder_PID} "
        else 

            outStr='>&'"${fd_stdout}"; 
        fi
        
        # setup nLinesAuto and/or fallocate truncation
        nLinesCur=${nLines}
        if ${nLinesAutoFlag} || ${fallocateFlag}; then
        
            # setup nLines indicator
            printf '%s\n' ${nLines} >"${tmpDir}"/.nLines
            
            # LOGIC FOR DYNAMICALLY SETTING 'nLines': 
            # The avg_bytes_per_line is estimated by looking at the byte offset position of fd_read and having each coproc keep track of how many lines it has read
            # the new "proposed" 'nLines' is: avg_bytes_per_line=( fd_read-pos / ( 1 + nRead ) ); nLinesNew=( 1 + (1 / nProc) * (fd_write_pos - fd_read_pos) / (1+avg_bytes_per_line) )
            # --> if proposed new 'nLines' is greater than current 'nLines' then use it (use case: stdin is arriving fairly fast, increase 'nLines' to match the rate lines are coming in on stdin)
            # --> if proposed new 'nLines' is less than or equal to current 'nLines' ignore it (i.e., nLines can only ever increase...it will never decrease)
            # --> if the new 'nLines' is greater than or equal to 'nLinesMax' or the .quit file has appeared, then break
            { coproc pAuto {
                    trap - EXIT
                    
                    ${fallocateFlag} && { nWait=${nProcs}; fd_read_pos_old=0; }
                    nRead=0
        
                    while ${fallocateFlag} || ${nLinesAutoFlag}; do 
                        
                        read -u ${fd_nAuto}
                        [[ ${REPLY} == 0 ]] && break
                        { [[ -z ${REPLY} ]] || [[ -f "${tmpDir}"/.quit ]]; } && nLinesAutoFlag=false
                        
                        read fd_read_pos </proc/self/fdinfo/${fd_read}
                        fd_read_pos=${fd_read_pos##*$'\t'}
                        
                        if ${nLinesAutoFlag}; then                    
                            
                            read fd_write_pos </proc/self/fdinfo/${fd_write}
                            fd_write_pos=${fd_write_pos##*$'\t'}
                        
                            nRead+=${REPLY}

                            nLinesNew=$(( 1 + ( ${nLinesCur} + ( ( 1 + ${nRead} ) * ( ${fd_write_pos} - ${fd_read_pos} ) ) / ( ${nProcs} * ( 1 + ${fd_read_pos} ) ) ) / 2 ))
                            
                            (( ${nLinesNew} > ${nLinesCur} )) && {
                    
                                #nLinesNew+=$(( ( ${nLinesCur} * ( ${nLinesNew} - ${nLinesCur} ) ) / 2 ))
                        
                                # unused: debug output
                                #printf 'nRead = %s ; write pos = %s ; read pos = %s; nLinesNew (proposed) = %s\n' ${nRead} ${fd_write_pos} ${fd_read_pos} ${nLinesNew} >&${fd_stderr}
          
                                (( ${nLinesNew} >= ${nLinesMax} )) && { nLinesNew=${nLinesMax}; nLinesAutoFlag=false; }

                                printf '%s\n' ${nLinesNew} >"${tmpDir}"/.nLines 
                                nLinesCur=${nLinesNew}
                                #printf 'CHANGING nLinesNew to %s\n!!!' "${nLinesNew}" >&${fd_stderr}
                            }
                        fi
                        
                        if ${fallocateFlag}; then
                            case ${nWait} in
                                0) 
                                    fd_read_pos=$(( 4096 * ( ${fd_read_pos} / 4096 ) ))
                                    (( ${fd_read_pos} > ${fd_read_pos_old} )) && {
                                        fallocate -p -o 0 -l  "${fPath}"
                                        fd_read_pos_old=${fd_read_pos}
                                    }
                                    nWait=${nProcs}
                                ;;
                                *)
                                    ((nWait--))
                                ;;
                            esac
                        fi
                        [[ -f "${tmpDir}"/.quit ]] && break                        
                    done
                    
                } 
            } 2>/dev/null

            exitTrapStr+='printf '"'"'%s\n'"'"' 0 >&'"${fd_nAuto}"'; '
            exitTrapStr_kill+="${pAuto_PID} "                  
        fi

        # set EXIT trap (dynamically determined based on which option flags were active)
        exitTrapStr="${exitTrapStr}"'kill -9 '"${exitTrapStr_kill}"' 2>/dev/null'
        ${rmDirFlag} && exitTrapStr+='; [[ -d $"'"${tmpDir}"'" ]] && rm -rf "'"${tmpDir}"'"'
        trap "${exitTrapStr}" EXIT INT TERM HUP QUIT       
        

        # populate {fd_continue} with an initial '1' 
        # {fd_continue} will act as an exclusive read lock (so lines from stdin are read atomically):
        #     when there is a '1' the pipe buffer then nothing has a read lock
        #     a process reads 1 byte from {fd_continue} to get the read lock, and 
        #     when that process writes a '1' back to the pipe it releases the read lock
        printf '\n' >&${fd_continue}; 

        # dont exit read loop during init 
        #initFlag=true
        
        # spawn $nProcs coprocs
        # on each loop, they will read {fd_continue}, which blocks them until they have exclusive read access
        # they then read N lines with mapfile and send 1 to {fd_continue} (so the next coproc can start to read)
        # if the read array is empty the coproc will either continue or break, depending on if end conditions are met
        # finally it will do something with the data.
        #
        # NOTE: All coprocs share the same fd_read file descriptor ( accomplished via `( <...>; coproc p0 ...; <...> ;  coproc pN ...; ) {fd_read}<><(:)` )
        #       This has the benefit of keeping the coprocs in sync with each other - when one reads data theb fd_read used by *all* of them is advanced.

        # generate coproc source code template (which, in turn, allows you to then spawn many coprocs very quickly)
        # this contains the code for the coprocs but has the worker ID ($kk) replaced with '%s' and '%' replaced with '%%'
        # the individual coproc's codes are then generated via printf ${coprocSrcCode} $kk $kk [$kk] and sourced
        
        coprocSrcCode="""
{ coproc p%s {
trap - EXIT INT TERM HUP QUIT
while true; do
$(${nLinesAutoFlag} && echo """
    \${nLinesAutoFlag} && read nLinesCur <\"${tmpDir}\"/.nLines
""")
    read -u ${fd_continue} 
    mapfile -n \${nLinesCur} \$([[ \${nLinesCur} == 1 ]] && printf '%%s' '-t') -u $(${pipeReadFlag} && printf '%s' ${fd_stdin} || printf '%s' ${fd_read}) A
$(${pipeReadFlag} || echo """
    [[ \${#A[@]} == 0 ]] || [[ \${nLinesCur} == 1 ]] || [[ \"\${A[-1]: -1}\" == \$'\\n' ]] || read -r -u ${fd_read} partialLine
"""
${nOrderFlag} && echo """
    read -u ${fd_nOrder} nOrder
""")
    printf '\\\\n' >&${fd_continue}; 
    [[ \${#A[@]} == 0 ]] && {
        if [[ -f \"${tmpDir}\"/.done ]]; then
$(${nLinesAutoFlag} && echo """
            printf '0\\\\n' >&\${fd_nAuto0}
""")
            [[ -f \"${tmpDir}\"/.quit ]] || touch \"${tmpDir}\"/.quit
        break
$(${inotifyFlag} && echo """
        else        
            read -u ${fd_inotify} -t 1
""")
        fi
        continue
    }
    [[ \${partialLine} ]] && { 
        A[\$(( \${#A[@]} - 1 ))]+=\"\${partialLine}\"
        partialLine=''
    }
$(${nLinesAutoFlag} && { printf '%s' """
    \${nLinesAutoFlag} && {
        printf '%%s\\\\n' \${#A[@]} >&\${fd_nAuto0}
        (( \${nLinesCur} < ${nLinesMax} )) || nLinesAutoFlag=false   
    }"""
    ${fallocateFlag} && printf '%s' ' || ' || echo
}
${fallocateFlag} && echo """printf '\\\\n' >&\${fd_nAuto0}
""") 

    $(printf '%q ' "${runCmd[@]}") \"\${A[@]%%\$'\\n'}\" ${outStr}

done
} 2>&${fd_stderr} {fd_nAuto0}>&${fd_nAuto}
} 2>/dev/null
p_PID+=(\${p%s_PID})
"""
        
        # source the coproc code for each coproc worker
        for (( kk=0 ; kk<${nProcs} ; kk++ )); do
            [[ -f "${tmpDir}"/.quit ]] && break
            source <(printf "${coprocSrcCode}" ${kk} ${kk})
        done
       
        # wait for everything to finish
        wait "${p_PID[@]}"
               
        # print output if using ordered output
        ${nOrderFlag} && cat "${tmpDir}"/.out/x*

        # print final nLines count
        ${nLinesAutoFlag} && printf 'nLines (final) = %s   (max = %s)\n'  "$(<"${tmpDir}"/.nLines)" "${nLinesMax}" >&${fd_stderr}
 
    # open anonymous pipes + other misc file descriptors for the above code block   
    } {fd_continue}<><(:) {fd_inotify}<><(:) {fd_nAuto}<><(:) {fd_nOrder}<><(:) {fd_read}<"${fPath}" {fd_write}>>"${fPath}" {fd_stdout}>&1 {fd_stdin}<&0 {fd_stderr}>&2

)
