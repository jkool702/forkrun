#!/bin/bash
if [[ ! -e /tmp/w29bash.dead && "$1" == "1" ]]; then touch /tmp/w29bash.dead; echo "PARTIAL-$1"; exit 1; fi
printf '%s\n' "$@"
