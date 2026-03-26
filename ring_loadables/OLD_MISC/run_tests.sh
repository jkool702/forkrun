#!/usr/bin/bash

. ./test.sh

export -f ring_test

yes $'\n' | head -n 1000000000 >test.dat

printf '\n----------------------------------------\nTESTING: ring_test 2\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 2 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 2 >/dev/null"


printf '\n----------------------------------------\nTESTING: ring_test 3\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 3 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 3 >/dev/null"

seq 1000000000 >test.dat-rlptgoD

printf '\n----------------------------------------\nTESTING: ring_test 4\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 4 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 4 >/dev/null"


printf '\n----------------------------------------\nTESTING: ring_test 5\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 5 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 5 >/dev/null"

find /mnt/ramdisk/usr -type f >/mnt/ramdisk/flist

printf '\n----------------------------------------\nTESTING: ring_test 7 (small)\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 7 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 7 >/dev/null"

\cp /mnt/ramdisk/flist /mnt/ramdisk/flist0
for nn in {1..10}; do
  cat /mnt/ramdisk/flist0 >> /mnt/ramdisk/flist
done

printf '\n----------------------------------------\nTESTING: ring_test 7 (large)\n\n'
perf stat -d -d -d /usr/bin/bash -c "ring_test -n 7 >/dev/null"
perf stat -d -d -d /usr/bin/bash -c "ring_test -n -o 7 >/dev/null"
