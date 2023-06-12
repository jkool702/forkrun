#!/bin/bash

a="$(printf '64 bytes from 1.1.1.1: icmp_seq=%s ttl=55 time=16.2 ms\n' {1..10000})"


{ for mm in 1 2 4 8 16 32; do 
    printf '\n\n------------------------------------------------------------------------------------------------\n\n%s COPROC(S)\n' $mm; 
    for ll in 1 2 4 8 16 32 64 128 256 512; do 
        printf '\nLINE BATCH SIZE = %s     \t' $ll; 
        { time { echo "$a" | mySplit "$ll" 2>/dev/null | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
    done; 
done; 
printf '\n\n'; } | tee /tmp/.mySplit.speedtest

