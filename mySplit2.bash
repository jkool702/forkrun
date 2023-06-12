#!/bin/bash        

mySplit2() {
    local tDir kk inotifyPID
    local -a A p_PID

    tDir=/tmp/"$(mktemp -d .mySplit2.XXXXXXXXX)" 
    mkdir -p "${tDir}"
    touch "${tDir}"/.record
    
    {
    
        trap 'kill ${inotifyPID}; exec {fd_inotify}>&-; [[ "${tDir}" == /tmp ]] || rm -r "${tDir}"' EXIT
        exec {fd_inotify}<><(:)
    
        # background inotify process
        {
            inotifywait -m -e modify,close "${tDir}"/.record | busybox tr -cd $'\n' >&${fd_inotify}
        } &
        
        inotifyPID=$!
    
        # background write porocess - append stdin pipe to tmpfile. IMPORTANT: use '>>', not '>'
        {
            cat >>"${tDir}"/.record 
            
            # indicate there is no more data to write
            touch "${tDir}"/.done
        } 0<&${fd_stdin} &
        
        p_PID+=($!)

        # main read process - read tmpfile and truncate after every read
        { 
            runFlag=true

            while ${runFlag} && read -N 1 -u ${fd_inotify}; do 
                
                # if tmpfile changed then mapfile record into array A; else continue
                if [[ -s "${tDir}"/.record ]]; then
                        # read  tmpfile
                        mapfile -t A <"${tDir}"/.record 
                else 
                    # end condition
                    [[ -f "${tDir}"/.done ]] && runFlag=false
                    continue
                fi

                # truncate tmpfile
                printf '%s' "$(busybox tail -n +$(( ${#A[@]} + 1 )) <"${tDir}"/.record)" >"${tDir}"/.record
                
                # loop through A and do _________
                # printf doesnt need a loop for this, but in general for more complex stuff you probably will
                for kk in ${!A[@]}; do
                    printf '%s\n' "${A[$kk]}"
                done 
            done
        } 

    } {fd_stdin}<&0
    
} 
