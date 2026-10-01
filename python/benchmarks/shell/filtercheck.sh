#!/bin/bash
cat /proc/self/coredump_filter
printf '%s\n' "$@"
