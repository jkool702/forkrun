#!/bin/bash

readtf() {
    ## READ data from stdin by buffering it in a TmpFile and then run it through the funcIntion given as input.
    #
    # USAGE: echo "${input}" | readtf [{-1|-l|--loop}] "${func}" ["${args[@]}"]
    # 
    # NOTE: the above is a drop-in replacement for the standard `while read; do ...` loop:
    #       echo "${input}" | while read -r; do "${func}" "${args[@]}" "${REPLY}"; done
    #
    # HOW: This is done by saving stdin to a tmpfile (in memory/ram) in a background process. Another process simultaniously
    #      uses mapfile to read that data into an array (`A`). After each mapfile the tmpfile is cleared (lower memory use).
    # 
    # WHY: reading data from a pipe reads byte-by-byte, which is slow. Reading data from a tmpfile doesnt. As such, if there is
    #      sufficient data available on stdin (at least 4 KB or so) for each `mapfile` then `readtf` is faster than a read loop.
    #
    # FLAGS: setting the 1st input to any of '-1' or '-l' or '--loop' makes readtf passes data to the specified funcIntion one line at a time
    #   [normal operation]:  mapfile -t A <tmpfile; "${func}" "${args[@]}" "${A[@]}"
    #  [-1|--loop flag set]: mapfile -t A <tmpfile; for kk in "${!A[@]}"; do "${func}" "${args[@]}" "${A[$kk]}"; done
    #
    # SPECIAL CASE - NO INPUT: if "${funcIn}" is not given, running `echo "${input}" | readtf [-1]` is equivilant to `echo "${input}" | readtf [-1] printf '%s\n'`
    #    (I'm not sure if there are any use cases outside of [speed]testing where this special case is actually useful, but it is availiable nonetheless)
    #
    # KNOWN ISSUES: on systems without `inotifywait`, `readtf` will continually try to read the tmpfile. If data on stdin is arriving slowly this results in high CPU usage (maxing out 1 core). 
    #    If the system has `inotifywait` (which is most modern non-embedded systems running linux) this isn't an issue, but without inotifywait preventing this results in unacceptably high latency.
    
    # make vars local
    local tDir kk bbPath inotifyFlag loopFlag printfFlag runFlag;
    local -a A;
    
    # check for busybox
    bbPath="$(type -p busybox)";
    
    # check for inotifywait
    type -p inotifywait >/dev/null 2>&1 && inotifyFlag=true || inotifyFlag=false
    
    # check whether to use loop or not when printing ${A[@]} with printf
    if { [[ "${1}" == -[1l] ]] || [[ "${1}" == --loop ]]; }; then
        loopFlag=true;
        shift 1
    else
        loopFlag=false;
    fi
    
    # check for no input special case
    [[ ${#} == 0 ]] && printfFlag='printf %s\n' || printfFlag=''
    
    # setup tmpdir
    tDir=/tmp/"$(mktemp -d .mySplit2.XXXXXX)";
    mkdir -p "${tDir}";
    touch "${tDir}"/.record;
    
    # remove tmpdir if the code finished normally
    {
        # setup inotify anonymous pipe and background process (in case data is arriving slowly on stdin)
        # this keeps the read process idle until there is actually something to read without using much CPU time
        ${inotifyFlag} && {
            exec {fd_inotify}<><(:);
            printf '\n' >&${fd_inotify}
            {
                inotifywait -m -e modify,close --format '' "${tDir}"/.record 2>/dev/null >&${fd_inotify};
            } &
            [[ "${tDir}" == '/tmp' ]] && trap 'exec {fd_inotify}>&-;' EXIT || trap 'exec {fd_inotify}>&-; rm -r '"${tDir}"';' EXIT;
            
        } || {
            [[ "${tDir}" == '/tmp' ]] || trap 'rm -r '"${tDir}" EXIT
        }

        # background process to append stdin pipe to tmpfile. IMPORTANT: use '>>', not '>'
        {
            cat >>"${tDir}"/.record;
            
            # indicate there is no more data to write
            touch "${tDir}"/.done;
            ${inotifyFlag} && printf '\n' >&${fd_inotify};
        } <&${fd_stdin} &
        
        # main process - read tmpfile and truncate after every read
        {
            while true; do
               
                if [[ -s "${tDir}"/.record ]]; then
                    mapfile -t A <"${tDir}"/.record;
                else
                    [[ -f "${tDir}"/.done ]] && break 
                    ${inotifyFlag} && read -u ${fd_inotify} 
                    continue
                fi
        
                # debug - see how many lines each mapfile consumed
                #printf 'READ %s LINES\n' "${#A[@]}" 1>&2;
 
                # truncate tmpfile
                printf '%s' "$("${bbPath}" tail -n +$(( ${#A[@]} + 1 )) < "${tDir}"/.record)" > "${tDir}"/.record;

                # loop through A and do _________
                if ${loopFlag}; then
                    for kk in ${!A[@]}; do
                        ${printfFlag}"${@}" "${A[$kk]}";
                    done;
                else
                    ${printfFlag}"${@}" "${A[@]}";
                fi;
            done;
        }
    } {fd_stdin}<&0 
    
    
}

    # SPEEDTEST - PRINT EVERYTHING UNDER /tmp
    #
    # printf '\n%s' 'BASE CASE:         '; { time { find /tmp;} >/dev/null ; } 2>&1 | sed -zE s/'(.)\n'/'\1\t'/g; echo; sleep 0.1s; \
    # printf '\n%s' 'pipe to readtf:    '; { time { find /tmp | readtf;} >/dev/null ; } 2>&1 | sed -zE s/'(.)\n'/'\1\t'/g; echo;  sleep 0.1s; \
    # printf '\n%s' 'pipe to read loop: '; { time { find /tmp | while read -r; do echo "$REPLY"; done; } >/dev/null ; } 2>&1 | sed -zE s/'(.)\n'/'\1\t'/g; echo;
    #
    # BASE CASE:
    # real    0m0.046s        user    0m0.018s        sys     0m0.026s
    # 
    # pipe to readtf:
    # real    0m0.139s        user    0m0.080s        sys     0m0.083s
    # 
    # pipe to read loop:
    # real    0m1.042s        user    0m0.395s        sys     0m1.075s
