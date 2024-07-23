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

mount -t tmpfs tmpfs /mnt/ramdisk

rsync -a --max-size=$((1<<21)) /usr /mnt/ramdisk

find /mnt/ramdisk -type f > /mnt/ramdisk/filelist

## info + reference times

du -d 0 -h /mnt/ramdisk
#: 11G     /mnt/ramdisk/

wc -l <filelist

## confirm no dropped lines

forkrun cksum <filelist | wc -l
#: 583878

forkrun sha512sum <filelist | wc -l
#: 583878


mapfile -t A <<<'sha1sum
sha256sum
sha512sum
sha224sum
sha384sum
md5sum 
sum -s
sum -r
cksum
b2sum
cksum -a sm3'


for nn in "${A[@]}"; do
    printf '\n----------------------------------------------\n%s\n\n' "$nn"
    time { forkrun $nn </mnt/ramdisk/filelist >/dev/null; }

    perf record -b -g -F max /bin/bash -O extglob -c 'forkrun '"$nn"' </mnt/ramdisk/filelist >/dev/null'
    perf script > out.perf
    /mnt/ramdisk/FlameGraph/stackcollapse-perf.pl --all out.perf > out.folded
    ./FlameGraph/flamegraph.pl --title="forkrun flamechart -- ${nn}" --flamechart --hash --width 4096 --height 24 out.folded  >forkrun_${nn// /_}.svg

    \rm -f out.* perf.data
    sleep 1
done

