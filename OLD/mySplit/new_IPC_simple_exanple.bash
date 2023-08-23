#!/bin/bash

gg() {
    ## simple example showing new (in progress) IPC scheme
    local -a A 
    local REPLY

    rm /tmp/gg.done /tmp/gg.stdin
    touch  /tmp/gg.done  /tmp/gg.stdin
    
    {
        cat >> /tmp/gg.stdin;
    } &
    {
        printf '\n' >&${fd0}
        {
            doneFlag=false
            while read -u ${fd0} -t 0.1 || [[ ! -f /tmp/gg.done ]]; do
                mapfile -t -n 10 -u ${fd_read} A;
                printf '\n' >&${fd0}
                [[ ${A} ]] && { printf '%s\n' "${A[@]}"; doneFlag=false; } || { { ${doneFlag} && break; } || { doneFlag=true; continue; } }
            done
        } &
          {
            doneFlag=false
            while read -u ${fd0} -t 0.1 || [[ ! -f /tmp/gg.done ]]; do
                mapfile -t -n 10 -u ${fd_read} A;
                printf '\n' >&${fd0}
                [[ ${A} ]] && { printf '%s\n' "${A[@]}"; doneFlag=false; } || { { ${doneFlag} && break; } || { doneFlag=true; continue; } }
            done
        } &
    } {fd_read}</tmp/gg.stdin {fd0}<><(:)
    wait
}
