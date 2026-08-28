#!/usr/bin/bash

cat /sys/kernel/mm/transparent_hugepage/shmem_enabled | grep -F '[always]' >/dev/null || { echo 'enabling THP' >&2; echo always | sudo tee /sys/kernel/mm/transparent_hugepage/shmem_enabled; }

./test_c_plugins.sh
./test_c_plugins_v2.sh
./test_frun.sh
./test_frun_comprehensive.sh
