#!/bin/bash

mySplit2 ()
{
    # make vars local
    local tDir kk ;
    local -a A;
    
    # setup tmpdir
    tDir=/tmp/"$(mktemp -d .mySplit2.XXXXXX)";
    mkdir -p "${tDir}";
    touch "${tDir}"/.record;
    
    {
        # setup inotify anonymous pipe and background process (in case data is arriving slowly on stdin)
        # this keeps the read process idle until there is actually something to read without using much CPU time
        exec {fd_inotify}<><(:);
        trap 'exec {fd_inotify}>&-;' EXIT;
        {
            inotifywait -m -e modify "${tDir}"/.record | busybox tr -cd $'\n' >&${fd_inotify}
        } &
        
        # background process to append stdin pipe to tmpfile. IMPORTANT: use '>>', not '>'
        {
            cat >>"${tDir}"/.record
            
            # indicate there is no more data to write
            touch "${tDir}"/.done;
        } <&${fd_stdin} &
        
        # main process - read tmpfile and truncate after every read
        {
            while true; do
                if [[ -s "${tDir}"/.record ]]; then
                    mapfile -t A < "${tDir}"/.record;
                else
                    [[ -f "${tDir}"/.done ]] && break
                    read -u ${fd_inotify}
                    continue
                fi;
                
                # debug - see how many lines each mapfile consumed
                #printf 'READ %s LINES\n' "${#A[@]}" 1>&2;
 
                # truncate tmpfile
                printf '%s' "$(busybox tail -n +$(( ${#A[@]} + 1 )) < "${tDir}"/.record)" > "${tDir}"/.record;

                # loop through array A and do _________
                # printf doesnt need a loop for this, but in general for more complex stuff you probably will
                for kk in ${!A[@]};
                do
                    printf '%s\n' "${A[$kk]}";
                done;
            done
        }
    } {fd_stdin}<&0
    
    # remove tmpdir if the code finished normally
    [[ "${tDir}" == /tmp ]] || rm -r "${tDir}"
}
