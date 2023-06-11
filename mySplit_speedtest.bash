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

# results

echo '''
------------------------------------------------------------------------------------------------

1 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.853s        user    0m1.797s        sys     0m0.599s
LINE BATCH SIZE = 2             real    0m0.482s        user    0m1.026s        sys     0m0.330s
LINE BATCH SIZE = 4             real    0m0.350s        user    0m0.625s        sys     0m0.280s
LINE BATCH SIZE = 8             real    0m0.202s        user    0m0.439s        sys     0m0.186s
LINE BATCH SIZE = 16            real    0m0.154s        user    0m0.325s        sys     0m0.153s
LINE BATCH SIZE = 32            real    0m0.125s        user    0m0.308s        sys     0m0.101s
LINE BATCH SIZE = 64            real    0m0.119s        user    0m0.229s        sys     0m0.156s
LINE BATCH SIZE = 128           real    0m0.110s        user    0m0.263s        sys     0m0.095s
LINE BATCH SIZE = 256           real    0m0.129s        user    0m0.287s        sys     0m0.103s
LINE BATCH SIZE = 512           real    0m0.115s        user    0m0.198s        sys     0m0.162s

------------------------------------------------------------------------------------------------

2 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.836s        user    0m1.732s        sys     0m0.637s
LINE BATCH SIZE = 2             real    0m0.464s        user    0m1.032s        sys     0m0.320s
LINE BATCH SIZE = 4             real    0m0.270s        user    0m0.649s        sys     0m0.201s
LINE BATCH SIZE = 8             real    0m0.196s        user    0m0.433s        sys     0m0.182s
LINE BATCH SIZE = 16            real    0m0.143s        user    0m0.352s        sys     0m0.106s
LINE BATCH SIZE = 32            real    0m0.131s        user    0m0.287s        sys     0m0.106s
LINE BATCH SIZE = 64            real    0m0.117s        user    0m0.212s        sys     0m0.166s
LINE BATCH SIZE = 128           real    0m0.113s        user    0m0.253s        sys     0m0.115s
LINE BATCH SIZE = 256           real    0m0.111s        user    0m0.262s        sys     0m0.103s
LINE BATCH SIZE = 512           real    0m0.126s        user    0m0.271s        sys     0m0.093s

------------------------------------------------------------------------------------------------

4 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.911s        user    0m1.819s        sys     0m0.609s
LINE BATCH SIZE = 2             real    0m0.468s        user    0m0.966s        sys     0m0.408s
LINE BATCH SIZE = 4             real    0m0.270s        user    0m0.611s        sys     0m0.241s
LINE BATCH SIZE = 8             real    0m0.200s        user    0m0.442s        sys     0m0.171s
LINE BATCH SIZE = 16            real    0m0.144s        user    0m0.318s        sys     0m0.143s
LINE BATCH SIZE = 32            real    0m0.135s        user    0m0.309s        sys     0m0.096s
LINE BATCH SIZE = 64            real    0m0.109s        user    0m0.271s        sys     0m0.097s
LINE BATCH SIZE = 128           real    0m0.114s        user    0m0.266s        sys     0m0.102s
LINE BATCH SIZE = 256           real    0m0.109s        user    0m0.228s        sys     0m0.137s
LINE BATCH SIZE = 512           real    0m0.122s        user    0m0.284s        sys     0m0.092s

------------------------------------------------------------------------------------------------

8 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.932s        user    0m1.797s        sys     0m0.661s
LINE BATCH SIZE = 2             real    0m0.464s        user    0m0.921s        sys     0m0.443s
LINE BATCH SIZE = 4             real    0m0.268s        user    0m0.570s        sys     0m0.282s
LINE BATCH SIZE = 8             real    0m0.177s        user    0m0.409s        sys     0m0.174s
LINE BATCH SIZE = 16            real    0m0.142s        user    0m0.345s        sys     0m0.110s
LINE BATCH SIZE = 32            real    0m0.123s        user    0m0.290s        sys     0m0.111s
LINE BATCH SIZE = 64            real    0m0.126s        user    0m0.241s        sys     0m0.135s
LINE BATCH SIZE = 128           real    0m0.113s        user    0m0.238s        sys     0m0.129s
LINE BATCH SIZE = 256           real    0m0.115s        user    0m0.227s        sys     0m0.138s
LINE BATCH SIZE = 512           real    0m0.124s        user    0m0.279s        sys     0m0.091s

------------------------------------------------------------------------------------------------

16 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.845s        user    0m1.680s        sys     0m0.716s
LINE BATCH SIZE = 2             real    0m0.470s        user    0m0.963s        sys     0m0.403s
LINE BATCH SIZE = 4             real    0m0.268s        user    0m0.687s        sys     0m0.170s
LINE BATCH SIZE = 8             real    0m0.205s        user    0m0.425s        sys     0m0.189s
LINE BATCH SIZE = 16            real    0m0.143s        user    0m0.365s        sys     0m0.091s
LINE BATCH SIZE = 32            real    0m0.128s        user    0m0.268s        sys     0m0.146s
LINE BATCH SIZE = 64            real    0m0.117s        user    0m0.269s        sys     0m0.110s
LINE BATCH SIZE = 128           real    0m0.112s        user    0m0.206s        sys     0m0.139s
LINE BATCH SIZE = 256           real    0m0.147s        user    0m0.222s        sys     0m0.168s
LINE BATCH SIZE = 512           real    0m0.135s        user    0m0.269s        sys     0m0.096s

------------------------------------------------------------------------------------------------

32 COPROC(S)

LINE BATCH SIZE = 1             real    0m0.843s        user    0m1.800s        sys     0m0.578s
LINE BATCH SIZE = 2             real    0m0.468s        user    0m1.046s        sys     0m0.312s
LINE BATCH SIZE = 4             real    0m0.268s        user    0m0.587s        sys     0m0.263s
LINE BATCH SIZE = 8             real    0m0.180s        user    0m0.432s        sys     0m0.148s
LINE BATCH SIZE = 16            real    0m0.146s        user    0m0.298s        sys     0m0.168s
LINE BATCH SIZE = 32            real    0m0.123s        user    0m0.286s        sys     0m0.109s
LINE BATCH SIZE = 64            real    0m0.160s        user    0m0.228s        sys     0m0.219s
LINE BATCH SIZE = 128           real    0m0.135s        user    0m0.243s        sys     0m0.133s
LINE BATCH SIZE = 256           real    0m0.111s        user    0m0.244s        sys     0m0.121s
LINE BATCH SIZE = 512           real    0m0.117s        user    0m0.285s        sys     0m0.076s

'''
