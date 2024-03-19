#!/usr/bin/env bash

## commands

# all files on tmpfs ramdisk
# system has 128 gb ddr4 ram and i97940x (14c/28t) cpu
# average cpu utilization is ( user time + sys time ) / real time
# lines starting with '#: ' are the outputprinted to the terminal  of the command that was just run 


## setup

cd /mnt/ramdisk

git clone https://github.com/jkool702/forkrun.git
git clone https://github.com/brendangregg/FlameGraph.git

. forkrun/forkrun.bash
export -f forkrun

find /mnt/ramdisk -type f > /mnt/ramdisk/filelist

## info + reference times

du -d 0 -h /mnt/ramdisk
#: 39G     /mnt/ramdisk/

wc -l <filelist
#: 1218957

time { find /mnt/ramdisk -type f >/dev/null; }

#: real    0m2.349s
#: user    0m1.242s
#: sys     0m1.215s


## confirm no dropped lines

forkrun cksum <filelist | wc -l
#: 1218957

forkrun sha512sum <filelist | wc -l
#: 1218957


## cksum time

time { forkrun cksum </mnt/ramdisk/filelist >/dev/null; }

#: real    0m2.542s
#: user    0m20.162s
#: sys     0m29.681s

# AVERAGE CPU UTILIZATION: 19.6 cores / 28 (logical) cores


## sha512sum time

time { forkrun sha512sum </mnt/ramdisk/filelist >/dev/null; }

#: real    0m6.050s
#: user    1m57.071s
#: sys     0m29.004s

# AVERAGE CPU UTILIZATION: 24.1 cores / 28 (logical) cores


## cksum flamechart

perf record -b -g -F max /bin/bash -O extglob -c 'forkrun cksum </mnt/ramdisk/filelist >/dev/null'
perf script > out.perf
/mnt/ramdisk/FlameGraph/stackcollapse-perf.pl --all out.perf > out.folded
./FlameGraph/flamegraph.pl --title="forkrun flamechart" --flamechart --hash --width 4096 --height 24 out.folded  >forkrun_cksum.svg


## sha512sum flamechart

perf record -b -g -F max /bin/bash -O extglob -c 'forkrun sha512sum </mnt/ramdisk/filelist >/dev/null'
perf script > out.perf
/mnt/ramdisk/FlameGraph/stackcollapse-perf.pl --all out.perf > out.folded
./FlameGraph/flamegraph.pl --title="forkrun flamechart" --flamechart --hash --width 4096 --height 24 out.folded  >forkrun_sha512sum.svg