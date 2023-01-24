#!/bin/bash

mkdir -p /mnt/ramdisk
mount -t tmpfs tmpfs /mnt/ramdisk
rsync -a /usr/lib*/* /mnt/ramdisk
cd /mnt/ramdisk

git clone https://github.com/jkool702/forkrun.git
. ./forkrun/forkrun.bash

total_size=$(du -d 0 ./ | awk '{print $1}')
num_files=$(find ./ -type f | wc -l)
echo "${num_files} files taking ${total_size} kb --> $(( ${total_size} / ${num_files} )) kb per file average"
nProcs=$(which nproc 2>/dev/null 1>/dev/null && nproc || grep -cE '^processor.*: ' /proc/cpuinfo)

unset t0
unset t1
unset tTaken

declare -a t0
declare -a t1
declare -a tTaken

echo
echo -n "number of files processed: "
t0[0]=${EPOCHREALTIME}
find ./ -type f | forkrun -j ${nProcs} sha256sum 2>/dev/null | wc -l
t1[0]=${EPOCHREALTIME}
tTaken[0]=$(bc <<< "${t1[0]} - ${t0[0]}")
printf '%s took %f seconds\n\n' "forkrun -j ${nProcs}" "${tTaken[0]}"


echo -n "number of files processed: "
t0[1]=${EPOCHREALTIME}
find ./ -type f | forkrun -k -j ${nProcs} sha256sum 2>/dev/null | wc -l
t1[1]=${EPOCHREALTIME}
tTaken[1]=$(bc <<< "${t1[1]} - ${t0[1]}")
printf '%s took %f seconds\n\n' "forkrun -k -j ${nProcs}" "${tTaken[1]}"


echo -n "number of files processed: "
t0[2]=${EPOCHREALTIME}
find ./ -type f | xargs -P ${nProcs} -L1 sha256sum 2>/dev/null | wc -l
t1[2]=${EPOCHREALTIME}
tTaken[2]=$(bc <<< "${t1[2]} - ${t0[2]}")
printf '%s took %f seconds\n\n' "xargs -P ${nProcs} -L1" "${tTaken[2]}"


echo -n "number of files processed: "
t0[3]=${EPOCHREALTIME}
find ./ -type f | xargs -P ${nProcs} sha256sum 2>/dev/null | wc -l
t1[3]=${EPOCHREALTIME}
tTaken[3]=$(bc <<< "${t1[3]} - ${t0[3]}")
printf '%s took %f seconds\n\n' "xargs -P ${nProcs}" "${tTaken[3]}"


echo 'will cite' | parallel --citation 2>/dev/null 1>/dev/null

echo -n "number of files processed: "
t0[4]=${EPOCHREALTIME}
find ./ -type f | parallel -j ${nProcs} sha256sum 2>/dev/null | wc -l
t1[4]=${EPOCHREALTIME}
tTaken[4]=$(bc <<< "${t1[4]} - ${t0[4]}")
printf '%s took %f seconds\n\n' "parallel -j ${nProcs}" "${tTaken[4]}"


echo -n "number of files processed: "
t0[5]=${EPOCHREALTIME}
find ./ -type f | parallel -j ${nProcs} -k sha256sum 2>/dev/null | wc -l
t1[5]=${EPOCHREALTIME}
tTaken[5]=$(bc <<< "${t1[5]} - ${t0[5]}")
printf '%s took %f seconds\n\n' "parallel -j ${nProcs} -k" "${tTaken[5]}"
