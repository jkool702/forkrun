#!/usr/bin/env bash

## commands

# all files on tmpfs ramdisk
# system has 128 gb ddr4 ram and i97940x (14c/28t) cpu
# average cpu utilization is ( user time + sys time ) / real time
# lines starting with '#: ' are the outputprinted to the terminal  of the command that was just run 


## setup

cd /mnt/ramdisk

#git clone https://github.com/jkool702/forkrun.git
git clone https://github.com/brendangregg/FlameGraph.git

#. forkrun/forkrun.bash
export -f forkrun

renice --priority -20 --pid $$

[[ "$USER" == 'root' ]] && {
	for nn in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo 'performance' >"${nn}"; done
}

#mount -t tmpfs tmpfs /mnt/ramdisk

#rsync -a --max-size=$((1<<21)) /usr /mnt/ramdisk

find /mnt/ramdisk -type f -print0> /mnt/ramdisk/filelist0

## info + reference times

du -d 0 -h /mnt/ramdisk
#: 11G     /mnt/ramdisk/

wc -l <filelist

## confirm no dropped lines

forkrun -z cksum <filelist0 | wc -l
#: 583878

forkrun -z sha512sum <filelist0 | wc -l
#: 583878


mapfile -t A <<<'sha1sum
sha256sum
sha512sum
sha224sum
sha384sum
sha512sum
md5sum 
sum -s
sum -r
cksum
b2sum
cksum -a sm3
xxhsum
xxhsum -H3'

ff() {
sha1sum "${@}"
sha256sum "${@}"
sha512sum "${@}"
sha224sum "${@}"
sha384sum "${@}"
sha512sum "${@}"
md5sum  "${@}"
sum -s "${@}"
sum -r "${@}"
cksum "${@}"
b2sum "${@}"
cksum -a sm3 "${@}"
xxhsum "${@}"
xxhsum -H3 "${@}"
}
export -f ff
export A


mkdir -p ./test1 ./test2

cd ./test1
  perf record -b -g -F max /bin/bash -O extglob -c 'forkrun -z ff </mnt/ramdisk/filelist >/dev/null'
    perf script > out.perf
    /mnt/ramdisk/FlameGraph/stackcollapse-perf.pl --all out.perf > out.folded
    /mnt/ramdisk/FlameGraph/flamegraph.pl --title="forkrun -- 13 checksums (combined via ff)" --flamechart --width 4096 --height 24 out.folded  >forkrun_all_combined-ff_new.svg
    /mnt/ramdisk/timep/timep_flamegraph.pl --title="forkrun --color=time -- 13 checksums (combined via ff)" --flamechart --width 4096 --height 24 out.folded  >forkrun_all_combined-ff_time.svg

cd ../test2
  perf record -b -g -F max /bin/bash -O extglob -c 'for nn in "${A[@]}"; do forkrun -z '"$nn"' </mnt/ramdisk/filelist0 >/dev/null; done'
    perf script > out.perf
    /mnt/ramdisk/FlameGraph/stackcollapse-perf.pl --all out.perf > out.folded
    /mnt/ramdisk/FlameGraph/flamegraph.pl --title="forkrun -- 13 checksums (seperate)" --flamechart --hash --width 4096 --height 24 out.folded  >forkrun_all_new.svg
    /mnt/ramdisk/timep/timep_flamegraph.pl --title="forkrun --color=time -- 13 checksums" --flamechart --width 4096 --height 24 out.folded  >forkrun_all_combined-ff_time.svg
    
  cd ../



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

# ./flamegraph.pl --title="forkrun flamechart" --subtitle='combined hash algs | dynamic coproc count' --flamechart --minwidth 1 --height 20 --width 4200  out.folded  >forkrun_flamechart.svg


