#!/bin/bash

mySplit2 ()
{
    # make vars local
    local tDir kk bbPath printfFastFlag
    local -a A;
    
    # check for busybox
    bbPath="$(type -p busybox)"
    
    # choose whether to use loop or not when printing ${A[@]} with printf
    printfFastFlag=true
    #printfFastFlag=false
    
    # choose whether to use inotify
    #inotifyFlag=true
    inotifyFlag=false
    
    
    # setup tmpdir
    tDir=/tmp/"$(mktemp -d .mySplit2.XXXXXX)";
    mkdir -p "${tDir}";
    touch "${tDir}"/.record;
    {
        # setup inotify anonymous pipe and background process (in case data is arriving slowly on stdin)
        # this keeps the read process idle until there is actually something to read without using much CPU time
        ${inotifyFlag} && {
            exec {fd_inotify}<><(:);
            {
                { printf '\n'; inotifywait -m -e modify,close "${tDir}"/.record; } | "${bbPath}" tr -cd $'\n' >&${fd_inotify}
            } &
            trap 'exec {fd_inotify}>&-; kill '"$!" EXIT;
        }

        # background process to append stdin pipe to tmpfile. IMPORTANT: use '>>', not '>'
        {
            cat >>"${tDir}"/.record
            
            # indicate there is no more data to write
            touch "${tDir}"/.done;
            ${inotifyFlag} && printf '\n' >&${fd_inotify}
        } <&${fd_stdin} &
        
        # main process - read tmpfile and truncate after every read
        {
            while true; do
                if [[ -s "${tDir}"/.record ]]; then
                    # data is available - read it
                    mapfile -t A <"${tDir}"/.record;
                else
                    # check for end condition
                    [[ -f "${tDir}"/.done ]] && break
                    
                    # blocking read of {fd_inotify}
                    ${inotifyFlag} && {
                        [[ -s "${tDir}"/.record ]] || read -u ${fd_inotify}
                    }
                    
                    continue
                fi;
                
                # debug - see how many lines each mapfile consumed
                #printf 'READ %s LINES\n' "${#A[@]}" 1>&2;
 
                # truncate tmpfile
                printf '%s' "$("${bbPath}" tail -n +$(( ${#A[@]} + 1 )) < "${tDir}"/.record)" > "${tDir}"/.record;

                # loop through A and do _________
                # printf doesnt need a loop for this, but in general for more complex stuff you probably will
                if ${printfFastFlag}; then
                    printf '%s\n' "${A[@]}"
                else
                    for kk in ${!A[@]}; do
                        printf '%s\n' "${A[$kk]}";
                    done;
                fi
            done
        }
    } {fd_stdin}<&0
    
    # remove tmpdir if the code finished normally
    [[ "${tDir}" == /tmp ]] || rm -r "${tDir}"
}
