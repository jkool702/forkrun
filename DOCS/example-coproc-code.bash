{ coproc pN {
export LC_ALL=C LANG=C IFS=

# record PID
echo "${BASH_PID}" >"/dev/shm/.forkrun.UGrRHY"/.run/pN

# set traps to ensure clean shutdown
trap ': >"/dev/shm/.forkrun.UGrRHY"/.quit;
[[ -f "/dev/shm/.forkrun.UGrRHY"/.run/p{<#>} ]] && \rm -f "/dev/shm/.forkrun.UGrRHY"/.run/p{<#>};
printf '"'"'\n'"'"' >&${fd_lock}' EXIT
trap 'trap - TERM INT HUP USR1; kill -INT $PPID ${BASHPID}' INT
trap 'trap - TERM INT HUP USR1; kill -TERM $PPID ${BASHPID}' TERM
trap 'trap - TERM INT HUP USR1; kill -HUP $PPID ${BASHPID}' HUP
trap 'trap - TERM INT HUP USR1' USR1

# main loop
while true; do
    
    # get current batch size and save in nLinesCur
    { ${nLinesAutoFlag} || ${nSpawnFlag}; } && read -r <"/dev/shm/.forkrun.UGrRHY"/.nLines && [[ ${REPLY} == +([0-9]) ]] && nLinesCur=${REPLY}

    # wait for exclusive read lock
    read -u ${fd_lock}
    
    # check for end condition
    [[ -f "/dev/shm/.forkrun.UGrRHY"/.quit ]] && {
        printf '\n' >&${fd_lock}
        break
    }
    [[ -f "/dev/shm/.forkrun.UGrRHY"/.done ]] && doneIndicatorFlag=true
    
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

    [[ ${#A[@]} == 0 ]] && {
        # we didnt read any data
        
        # check for end condition
        ${doneIndicatorFlag} || {
          [[ -f "/dev/shm/.forkrun.UGrRHY"/.done ]] && {
            # check byte offsets for fd's for reading/writing data to the tmpfile
            IFS=$'\t';
            read -r _ fd_read_pos </proc/self/fdinfo/${fd_read}
            read -r _ fd_write_pos </proc/self/fdinfo/${fd_write}
            IFS=
            [[ "${fd_read_pos}" == "${fd_write_pos}" ]] && doneIndicatorFlag=true
          }
        }
        if ${doneIndicatorFlag} || [[ -f "/dev/shm/.forkrun.UGrRHY"/.quit ]]; then
            # end condition met. shutdown this coproc and tell the rest to do the same.
            printf 'x\n' >&${fd_nAuto0}
            kill -9 $BASH_PID &>/dev/null

            : >"/dev/shm/.forkrun.UGrRHY"/.quit
            printf '%.0s\n' "/dev/shm/.forkrun.UGrRHY"/.run/p* >&${fd_lock}
            break
        else
            # we didnt read data but the end condition isnt met --> data is arriving slowly
            # read from a pipe that is fed a newline whenever the tmpfile has  
            # data written to it (via another process running inotifywait)
            # this allows wait for new data efficiently if it is comming in slowly
           [[ -f "/dev/shm/.forkrun.UGrRHY"/.done ]] && doneIndicatorFlag=true || read -u ${fd_wait}
        fi
        continue
    }

    # tell the proces resposible for dynamically adjusting batch size how many lines we just read
    { ${nLinesAutoFlag} || ${nSpawnFlag}; } && {
        printf '%s\n' ${#A[@]} >&${fd_nAuto0}
        (( ${nLinesCur} < ${fd_lock}24 )) || nLinesAutoFlag=false
    }
    
    # run the data weread through whatever we are parallelizing
    {
        <whateverIsBeingParallelized> "${A[@]}" 
    }
  }  
}
