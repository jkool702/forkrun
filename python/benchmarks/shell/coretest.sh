#!/bin/bash
echo "$(cat /tmp/corecnt 2>/dev/null || echo 0)" > /tmp/corecnt_tmp
n=$(($(cat /tmp/corecnt 2>/dev/null || echo 0) + 1))
echo "$n" > /tmp/corecnt
ulimit -c >> /tmp/corelog
if [[ "$n" -le 2 ]]; then exit 1; fi
printf '%s\n' "$@"
