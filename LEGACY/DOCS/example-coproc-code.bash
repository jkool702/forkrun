{ coproc pN {
export LC_ALL=C LANG=C IFS=

# record PID
echo "${BASH_PID}" >"${tmpDir}"/.run/pN

# set traps to ensure clean shutdown
trap ': >"${tmpDir}"/.quit;
[[ -f "${tmpDir}"/.run/p{<#>} ]] && \rm -f "${tmpDir}"/.run/p{<#>};
printf '"'"'\n'"'"' >&${fd_lock}' EXIT
trap 'trap - TERM INT HUP USR1; kill -INT $PPID ${BASHPID}' INT
trap 'trap - TERM INT HUP USR1; kill -TERM $PPID ${BASHPID}' TERM
trap 'trap - TERM INT HUP USR1; kill -HUP $PPID ${BASHPID}' HUP
trap 'trap - TERM INT HUP USR1' USR1

# main loop
while true; do
    
    # get current batch size and save in nLinesCur
    { ${nLinesAutoFlag} || ${nSpawnFlag}; } && read -r <"${tmpDir}"/.nLines && [[ ${REPLY} == +([0-9]) ]] && nLinesCur=${REPLY}

    # wait for exclusive read lock
    read -u ${fd_lock}
    
    # check for end condition
    [[ -f "${tmpDir}"/.quit ]] && {
        printf '\n' >&${fd_lock}
        break
    }
    [[ -f "${tmpDir}"/.done ]] && doneIndicatorFlag=true
    
    # read $nLinesCur lines of data fro,m the tmpfile the is caching stdin and save in array A
    mapfile -t -n ${nLinesCur} -u ${fd_read}  A
    
    [[ ${#A[@]} == 0 ]] || ${doneIndicatorFlag} || {
        # we read at least 1 line of data

        # rewind 1 byte usung custom lseek loadable builtin and re-read that byte to ensure it was a newline
        lseek ${fd_read} -1
        read -r -u ${fd_read} -N 1
        [[ "${REPLY}" == $'\n' ]] || {
            # if it wasnt a newline, finish reading the line and append to end of last array index
            until read -r -u ${fd_read} ; do
                A[-1]+="${REPLY}";
            done
            A[-1]+="${REPLY}" 
        }
    }

    # release exclusive read lock
    printf '\n' >&${fd_lock}

    # dealwuth case where we didnt read any data
    [[ ${#A[@]} == 0 ]] && {        
        # check for end condition
        ${doneIndicatorFlag} || {
          [[ -f "${tmpDir}"/.done ]] && {
            # check byte offsets for fd's for reading/writing data to the tmpfile
            IFS=$'\t';
            read -r _ fd_read_pos </proc/self/fdinfo/${fd_read}
            read -r _ fd_write_pos </proc/self/fdinfo/${fd_write}
            IFS=
            [[ "${fd_read_pos}" == "${fd_write_pos}" ]] && doneIndicatorFlag=true
          }
        }
        if ${doneIndicatorFlag} || [[ -f "${tmpDir}"/.quit ]]; then
            # end condition met. shutdown this coproc and tell the rest to do the same.
            printf 'x\n' >&${fd_nAuto0}

            : >"${tmpDir}"/.quit
            printf '%.0s\n' "${tmpDir}"/.run/p* >&${fd_lock}
            break
        else
            # we didnt read data but the end condition isnt met --> data is arriving slowly
            # read from a pipe that is fed a newline whenever the tmpfile has  
            # data written to it (via another process running inotifywait)
            # this allows wait for new data efficiently if it is comming in slowly
           [[ -f "${tmpDir}"/.done ]] && doneIndicatorFlag=true || read -u ${fd_wait}
        fi
        continue
    }

    # tell the proceses resposible for dynamically adjusting batch size and dynamically spawning new coprocs how many lines we just read
    { ${nLinesAutoFlag} || ${nSpawnFlag}; } && {
        printf '%s\n' ${#A[@]} >&${fd_nAuto0}
        (( ${nLinesCur} < ${fd_lock}24 )) || nLinesAutoFlag=false
    }
    
    # run the lines we read through whatever we are parallelizing
    {
        "${runCmd[@]} "${A[@]}" 
    }
  }  
}
