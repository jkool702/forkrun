#!/bin/bash        

    
mySplit2() {
    local tDir kk
    local -a A

    tDir=/tmp/"$(mktemp -d .mySplit2.XXXXXXXXX)" 
    mkdir -p "${tDir}"
    touch "${tDir}"/.record
    
    {
        
        # background porocess - append stdin pipe to tmpfile. IMPORTANT: use '>>', not '>'
        {
            cat >>"${tDir}"/.record 
            
            # indicate there is no more data to write
            touch "${tDir}"/.done
        } 0<&${fd_stdin} &
        
        exec {fd_continue}<><(:)
        exec {fd_inotify}<><(:)
        trap 'exec {fd_continue}>&- {fd_inotify}>&-' EXIT
        
        # background inotify monitoring process 
        {
            inotifywait -m -e modify "${tDir}"/.record | busybox tr -d [^\n] | while read; do
                read -t 0.01 -N 1 -u ${fd_inotify} && printf '1' >&${fd_continue}
            done
        } &
   
    
        # main process - read tmpfile and truncate after every read
        { 
            until [[ -f  "${tDir}"/.done ]] && [[ -z $(<"${tDir}"/.record) ]]; do      
                
                # mapfile record into array A 
                mapfile -t A <"${tDir}"/.record 
                
                # if we read something truncate tmpfile and do something with the read data, otherwise wait
                if [[ ${#A[@]} == 0 ]]; then
                    [[ -f  "${tDir}"/.done ]] || {
                        printf '1' >&${fd_inotify}
                        read -N 1 -u ${fd_continue}
                    }
                else
                    # truncate tmpfile
                    printf '%s' "$(busybox tail -n +$(( ${#A[@]} + 1 )) <"${tDir}"/.record)" >"${tDir}"/.record
                
                    # loop through A and do _________
                    # printf doesnt need a loop for this, but in general for more complex stuff you probably will
                    for kk in ${!A[@]}; do
                        printf '%s\n' "${A[$kk]}"
                    done 
                fi

            done
        }
    } {fd_stdin}<&0
    
} 
